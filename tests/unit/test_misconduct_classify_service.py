# EDU-C2-024 — Unit Tests: misconduct_classify_service (step 2)

import inspect

from src.services.misconduct_classify_service import (
    build_classification_rationale,
    classify_misconduct,
)


class TestClassifyMisconductDeterminism:
    def test_no_llm_parameter_in_signature(self):
        """IMPLEMENTATION_LOG.md A4: legally-significant decisions must be
        deterministic — classify_misconduct() must not accept an `llm` param."""
        assert "llm" not in inspect.signature(classify_misconduct).parameters

    def test_fabrication_detected(self):
        classification, severity = classify_misconduct(
            "fabricated the results", "Data was invented for three trials."
        )
        assert classification == "fabrication"

    def test_falsification_detected(self):
        classification, _ = classify_misconduct("altered data in the table", "selectively omitted outliers")
        assert classification == "falsification"

    def test_plagiarism_detected(self):
        classification, _ = classify_misconduct("plagiarism in essay", "copied verbatim without citation")
        assert classification == "plagiarism"

    def test_unmatched_defaults_to_other(self):
        classification, _ = classify_misconduct("unusual behavior", "unclear situation")
        assert classification == "other"

    def test_severe_keyword_detected(self):
        _, severity = classify_misconduct("fabrication", "a repeated pattern across the dissertation")
        assert severity == "severe"

    def test_minor_keyword_detected(self):
        _, severity = classify_misconduct("plagiarism", "an isolated citation error, first offense")
        assert severity == "minor"

    def test_default_severity_is_moderate(self):
        _, severity = classify_misconduct("plagiarism", "copied text without citation")
        assert severity == "moderate"


class TestClassificationRationale:
    def test_fallback_without_llm(self):
        rationale = build_classification_rationale("fabrication", "severe", llm=None)
        assert "fabrication" in rationale
        assert "severe" in rationale

    def test_llm_failure_falls_back(self):
        class BrokenLLM:
            def complete(self, prompt):
                raise RuntimeError("boom")

        rationale = build_classification_rationale("plagiarism", "minor", llm=BrokenLLM())
        assert "plagiarism" in rationale

    def test_llm_rationale_used_when_available(self):
        class StubLLM:
            def complete(self, prompt):
                return "Custom rationale text."

        rationale = build_classification_rationale("plagiarism", "minor", llm=StubLLM())
        assert rationale == "Custom rationale text."

    def test_llm_ruling_language_discarded_fail_safe(self):
        # review finding M1: this rationale is inserted verbatim into the
        # released report (report_assemble_service) — it must not be exempt
        # from the same fail-safe ruling-language filter as the other
        # LLM-generated sections.
        class RulingLLM:
            def complete(self, prompt):
                return "We hereby determine the subject is guilty of severe misconduct."

        rationale = build_classification_rationale("fabrication", "severe", llm=RulingLLM())
        assert "guilty" not in rationale.lower()
        assert "fabrication" in rationale

    def test_llm_empty_response_falls_back(self):
        class EmptyLLM:
            def complete(self, prompt):
                return ""

        rationale = build_classification_rationale("other", "moderate", llm=EmptyLLM())
        assert "other" in rationale
