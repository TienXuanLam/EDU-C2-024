# PB-04 (domain): "Advisory only" guarantee (proposal §11 Risk #1, 🔴 High).
#
# No code path may ship ruling-shaped language ("we find", "is guilty", "we
# hereby determine", "final ruling", "the committee rules") in a released
# report, regardless of what an adversarial/misbehaving LLM returns. Mirrors
# the same PB-04 advisory_only enforcement test pattern used elsewhere in the
# fleet — includes both a behavioral battery (adversarial LLM stubs) and a
# static scan of this template's own fallback template strings.

import ast
import pathlib

from src.services.intent_determination_draft_service import (
    BANNED_RULING_PHRASES,
    draft_intent_analysis,
)
from src.services.evidence_review_draft_service import draft_evidence_review
from src.services.report_assemble_service import assemble_report


class _AdversarialLLM:
    def __init__(self, text: str):
        self._text = text

    def complete(self, prompt: str) -> str:
        return self._text


ADVERSARIAL_OUTPUTS = [
    "We find that the subject is guilty of severe misconduct.",
    "We hereby determine this case warrants expulsion.",
    "Final ruling: the committee rules against the subject.",
    "We conclude that the subject is responsible beyond doubt.",
]


class TestAdvisoryOnlyBehavioral:
    def test_no_adversarial_llm_output_survives_into_assembled_report(self):
        for adversarial_text in ADVERSARIAL_OUTPUTS:
            llm = _AdversarialLLM(adversarial_text)
            evidence_section = draft_evidence_review("evidence", "fabrication", "severe", llm=llm)
            intent_section = draft_intent_analysis("evidence", "fabrication", "severe", llm=llm)

            report = assemble_report(
                case_id="CASE-2026-PB04",
                misconduct_type_input="fabrication",
                subject_role_category="graduate student",
                classification="fabrication",
                severity="severe",
                classification_rationale="r",
                evidence_review_section=evidence_section,
                intent_analysis_section=intent_section,
                sanction_range_text="s",
            )
            lowered = report.lower()
            for phrase in BANNED_RULING_PHRASES:
                assert phrase not in lowered, f"banned phrase '{phrase}' leaked via LLM output '{adversarial_text}'"


class TestAdvisoryOnlyStaticScan:
    # intent_determination_draft_service.py is deliberately excluded: it
    # defines BANNED_RULING_PHRASES itself (the deny-list necessarily
    # contains the phrases) and its LLM prompt instructs the model NOT to
    # use ruling language ("Do NOT issue a final ruling...") — both are
    # legitimate self-references, not a leak. Its fallback_body content is
    # covered directly by test_intent_determination_draft_service.py.
    _EXCLUDED_FILES = {"intent_determination_draft_service.py"}

    def test_fallback_templates_contain_no_ruling_language(self):
        # Self-check: none of this template's own deterministic fallback
        # strings may contain banned ruling language either.
        src_dir = pathlib.Path(__file__).parents[2] / "src" / "services"
        offenders = []
        for path in src_dir.glob("*.py"):
            if path.name in self._EXCLUDED_FILES:
                continue
            source = path.read_text(encoding="utf-8")
            for node in ast.walk(ast.parse(source, filename=str(path))):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    lowered = node.value.lower()
                    for phrase in BANNED_RULING_PHRASES:
                        if phrase in lowered:
                            offenders.append(f"{path.name}:{node.lineno} contains '{phrase}'")
        assert offenders == [], "\n".join(offenders)
