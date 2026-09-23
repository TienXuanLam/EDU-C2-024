"""AgentCore Platform v1.0"""

# Step 4 — IntentDeterminationDraft. Highest legal risk section (proposal
# §11 Risk #1) — deliberate-vs-negligent intent must never be an LLM final
# ruling. Design: LLM (if configured) drafts narrative discussion only; a
# mandatory advisory sentence is appended deterministically regardless of
# LLM output, and any ruling-shaped language from the LLM is detected and
# discarded in favor of the deterministic fallback (fail-safe, not
# fail-open).

from __future__ import annotations

from src.services.llm_types import LlmClient, completion_text

_ADVISORY_SENTENCE = (
    "This intent analysis is a draft assessment only, for committee and legal counsel "
    "review — it does not constitute a final determination of intent."
)

BANNED_RULING_PHRASES = (
    "we find that",
    "we conclude that the subject is",
    "is guilty",
    "we hereby determine",
    "final ruling",
    "the committee rules",
)


def contains_ruling_language(text: str) -> bool:
    lowered = text.lower()
    return any(phrase in lowered for phrase in BANNED_RULING_PHRASES)


def draft_intent_analysis(
    evidence_description: str,
    classification: str,
    severity: str,
    llm: LlmClient | None = None,
) -> str:
    fallback_body = (
        "## Intent Analysis\n\n"
        f"**Deliberate vs. Negligent:** Based on the submitted evidence for this "
        f"'{classification}' case (severity: {severity}), the record should be assessed "
        "for indicators of deliberate intent (e.g., repeated pattern, concealment) versus "
        "negligence (e.g., isolated error, lack of awareness of standards).\n\n"
        "**Aggravating / Mitigating Factors:** Reviewers should weigh factors such as prior "
        "offenses, cooperation with the investigation, and scale of impact.\n\n"
        f"_{_ADVISORY_SENTENCE}_\n"
    )

    if llm is None:
        return fallback_body

    prompt = (
        "Draft the 'Intent Analysis' section of a university academic misconduct "
        "investigation report: discuss deliberate-vs-negligent indicators and "
        "aggravating/mitigating factors found in the evidence. Do NOT issue a final "
        "ruling, verdict, or guilt determination — present analysis only, for human "
        "committee and legal counsel review.\n\n"
        f"Misconduct classification: {classification}\n"
        f"Severity tier: {severity}\n"
        f"Evidence description: {evidence_description}\n"
    )
    try:
        text = completion_text(llm.complete(prompt))
    except Exception:
        return fallback_body

    if not text or contains_ruling_language(text):
        # Fail-safe: discard LLM output entirely rather than risk shipping
        # ruling-shaped language; the deterministic fallback is always safe.
        return fallback_body

    return f"{text}\n\n_{_ADVISORY_SENTENCE}_\n"
