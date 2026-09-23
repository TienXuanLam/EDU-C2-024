"""AgentCore Platform v1.0"""

# Step 3 — EvidenceReviewDraft. Narrative generation (not a legal decision) —
# LLM is appropriate here, with a deterministic fallback template when no
# LLM is configured (IMPLEMENTATION_LOG.md B5 pattern).
#
# Fail-safe note: reuses intent_determination_draft_service.contains_ruling_language
# — any LLM-drafted section can drift into ruling-shaped language, not just the
# intent analysis section, so the same discard-on-detection filter applies here
# too (found by test_main_node.py during e2e-style node testing: a single
# ruling-prone LLM leaked "guilty" through this section, not just step 4).

from __future__ import annotations

from src.services.intent_determination_draft_service import contains_ruling_language
from src.services.llm_types import LlmClient, completion_text


def draft_evidence_review(
    evidence_description: str,
    classification: str,
    severity: str,
    llm: LlmClient | None = None,
) -> str:
    fallback = (
        "## Evidence Review\n\n"
        f"**Evidence Type:** Documentary case evidence submitted by the disciplinary committee.\n\n"
        f"**Review Method:** Manual review of the submitted evidence against the MEXT 2023 "
        f"misconduct taxonomy for '{classification}' (severity: {severity}).\n\n"
        f"**Findings Summary:** {evidence_description}\n"
    )
    if llm is None:
        return fallback
    prompt = (
        "Draft the 'Evidence Review' section of a university academic misconduct "
        "investigation report. Cover: evidence type, review method, and a findings "
        "summary. Do not issue a ruling, verdict, or sanction recommendation — this "
        "section only reviews the evidence.\n\n"
        f"Misconduct classification: {classification}\n"
        f"Severity tier: {severity}\n"
        f"Evidence description: {evidence_description}\n"
    )
    try:
        text = completion_text(llm.complete(prompt))
    except Exception:
        return fallback

    if not text or contains_ruling_language(text):
        return fallback
    return text
