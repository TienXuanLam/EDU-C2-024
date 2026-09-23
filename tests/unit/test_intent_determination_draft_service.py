# EDU-C2-024 — Unit Tests: intent_determination_draft_service (step 4)
#
# Highest legal-risk section (proposal §11 Risk #1) — covers the fail-safe
# design: any LLM output containing ruling-shaped language must be discarded
# in favor of the deterministic fallback, and the advisory sentence must
# always be present.

from src.services.intent_determination_draft_service import (
    BANNED_RULING_PHRASES,
    contains_ruling_language,
    draft_intent_analysis,
)

_ADVISORY_MARKER = "does not constitute a final determination"


class TestContainsRulingLanguage:
    def test_detects_ruling_phrase(self):
        assert contains_ruling_language("We find that the subject is guilty of misconduct.") is True

    def test_clean_analysis_not_flagged(self):
        assert contains_ruling_language("The evidence suggests possible deliberate intent.") is False


class TestDraftIntentAnalysis:
    def test_fallback_without_llm_has_advisory_sentence(self):
        text = draft_intent_analysis("evidence text", "fabrication", "severe", llm=None)
        assert _ADVISORY_MARKER in text

    def test_fallback_without_llm_contains_no_ruling_language(self):
        text = draft_intent_analysis("evidence text", "fabrication", "severe", llm=None).lower()
        for phrase in BANNED_RULING_PHRASES:
            assert phrase not in text

    def test_llm_output_used_when_safe(self):
        class StubLLM:
            def complete(self, prompt):
                return "Analysis suggests negligence rather than deliberate intent."

        text = draft_intent_analysis("evidence text", "falsification", "minor", llm=StubLLM())
        assert "Analysis suggests negligence" in text
        assert _ADVISORY_MARKER in text

    def test_llm_ruling_language_discarded_fail_safe(self):
        class RulingLLM:
            def complete(self, prompt):
                return "We hereby determine the subject is guilty of severe misconduct."

        text = draft_intent_analysis("evidence text", "fabrication", "severe", llm=RulingLLM())
        assert "guilty" not in text.lower()
        assert _ADVISORY_MARKER in text

    def test_llm_failure_falls_back(self):
        class BrokenLLM:
            def complete(self, prompt):
                raise RuntimeError("boom")

        text = draft_intent_analysis("evidence text", "other", "moderate", llm=BrokenLLM())
        assert _ADVISORY_MARKER in text

    def test_llm_empty_response_falls_back(self):
        class EmptyLLM:
            def complete(self, prompt):
                return ""

        text = draft_intent_analysis("evidence text", "other", "moderate", llm=EmptyLLM())
        assert _ADVISORY_MARKER in text
