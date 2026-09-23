"""AgentCore Platform v1.0"""

# Step 2 — MisconductTypeClassify.
#
# Design Decision Record (docs/02_design.md): classification (misconduct
# type + severity tier) directly determines the sanction range looked up in
# step 5 — a legally significant decision. Per IMPLEMENTATION_LOG.md A4,
# decisions with legal/technical consequence must be deterministic (no `llm`
# parameter in the signature); LLM is used only to generate a non-authoritative
# rationale sentence in build_classification_rationale(), never to decide the
# classification itself.

from __future__ import annotations

from src.services.intent_determination_draft_service import contains_ruling_language
from src.services.llm_types import LlmClient, completion_text

VALID_CLASSIFICATIONS = ("fabrication", "falsification", "plagiarism", "other")
VALID_SEVERITY_TIERS = ("minor", "moderate", "severe")

_CLASSIFICATION_KEYWORDS: dict[str, tuple[str, ...]] = {
    "fabrication": (
        "fabricat",
        "invented data",
        "made up data",
        "did not conduct",
        "never performed",
        "false data",
        "nonexistent experiment",
    ),
    "falsification": (
        "falsif",
        "altered data",
        "manipulat",
        "selectively omitted",
        "changed results",
        "doctored image",
        "cherry-pick",
    ),
    "plagiarism": (
        "plagiar",
        "copied without attribution",
        "verbatim",
        "without citation",
        "copied text",
        "unattributed",
    ),
}

_SEVERE_KEYWORDS = (
    "repeated",
    "pattern of",
    "multiple publications",
    "intentional",
    "large-scale",
    "dissertation",
    "thesis",
    "grant fraud",
    "federal funding",
    "prior offense",
)

_MINOR_KEYWORDS = (
    "minor",
    "isolated",
    "first offense",
    "unintentional",
    "inadvertent",
    "citation error",
    "formatting error",
)


def classify_misconduct(misconduct_type_input: str, evidence_description: str) -> tuple[str, str]:
    """Deterministic keyword-rule classification. Returns (classification, severity_tier).

    No `llm` parameter — this signature is asserted by a PB test (A4 principle).
    """
    text = f"{misconduct_type_input} {evidence_description}".lower()

    classification = "other"
    for category, keywords in _CLASSIFICATION_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            classification = category
            break

    if any(keyword in text for keyword in _SEVERE_KEYWORDS):
        severity = "severe"
    elif any(keyword in text for keyword in _MINOR_KEYWORDS):
        severity = "minor"
    else:
        severity = "moderate"

    return classification, severity


def build_classification_rationale(classification: str, severity: str, llm: LlmClient | None = None) -> str:
    """Narrative-only rationale sentence. Never changes classification/severity —
    those are already decided by classify_misconduct() before this is called.

    Fail-safe (review finding M1): applies the same ruling-language discard
    filter as the other LLM-generated sections (evidence_review_draft_service,
    intent_determination_draft_service) — this text is inserted verbatim into
    the released report by report_assemble_service, so it must not be exempt
    from the "no code path releases ruling-shaped output" guarantee.
    """
    fallback = (
        f"Classified as '{classification}' (severity: {severity}) based on "
        "keyword-rule matching against the MEXT 2023 misconduct taxonomy."
    )
    if llm is None:
        return fallback
    prompt = (
        f"In one sentence, explain why a university misconduct case was classified as "
        f"'{classification}' with severity '{severity}'. Do not restate a different "
        "classification or severity — only explain the given one."
    )
    try:
        text = completion_text(llm.complete(prompt))
    except Exception:
        return fallback

    if not text or contains_ruling_language(text):
        return fallback
    return text
