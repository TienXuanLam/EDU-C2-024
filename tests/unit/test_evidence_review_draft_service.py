# EDU-C2-024 — Unit Tests: evidence_review_draft_service (step 3)

from src.services.evidence_review_draft_service import draft_evidence_review


class TestDraftEvidenceReview:
    def test_fallback_without_llm(self):
        text = draft_evidence_review("The dataset does not match raw logs.", "fabrication", "severe", llm=None)
        assert "Evidence Review" in text
        assert "fabrication" in text
        assert "The dataset does not match raw logs." in text

    def test_llm_used_when_available(self):
        class StubLLM:
            def complete(self, prompt):
                return "LLM-drafted evidence review section."

        text = draft_evidence_review("evidence text", "plagiarism", "minor", llm=StubLLM())
        assert text == "LLM-drafted evidence review section."

    def test_llm_failure_falls_back(self):
        class BrokenLLM:
            def complete(self, prompt):
                raise RuntimeError("boom")

        text = draft_evidence_review("evidence text", "plagiarism", "minor", llm=BrokenLLM())
        assert "Evidence Review" in text

    def test_llm_empty_response_falls_back(self):
        class EmptyLLM:
            def complete(self, prompt):
                return ""

        text = draft_evidence_review("evidence text", "other", "moderate", llm=EmptyLLM())
        assert "Evidence Review" in text

    def test_llm_ruling_language_discarded_fail_safe(self):
        # Regression test: a single LLM instance also used for step 4 (intent
        # analysis) can drift into ruling-shaped language here too — must be
        # discarded the same way, not just in the intent analysis section.
        class RulingLLM:
            def complete(self, prompt):
                return "We hereby determine the subject is guilty of severe misconduct."

        text = draft_evidence_review("evidence text", "fabrication", "severe", llm=RulingLLM())
        assert "guilty" not in text.lower()
        assert "Evidence Review" in text

    def test_sdk_canonical_response_content_is_used(self):
        class CanonicalLLM:
            def complete(self, prompt):
                return {"content": "## Evidence Review\n\nCanonical SDK response."}

        text = draft_evidence_review("evidence text", "plagiarism", "moderate", llm=CanonicalLLM())
        assert text == "## Evidence Review\n\nCanonical SDK response."
