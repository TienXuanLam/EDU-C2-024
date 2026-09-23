# EDU-C2-024 — Unit Tests: MainNode (steps 3-6: draft evidence review + intent
# analysis, sanction range lookup, report assembly)
#
# Rewritten from the scaffold stub (IMPLEMENTATION_LOG.md A7) — the original
# stub tested a generic "process input" MainNode that no longer matches this
# template's real business logic.

import inspect

from framework.schemas.agent_status import AgentStatus
from src.nodes.main_node import MainNode

_TEST_SANCTION_KB = {
    "kb_version": "test-1.0",
    "source": "Unit Test Fixture",
    "provenance_verified": True,
    "institution_scope_note": "TEST SCOPE NOTE.",
    "ranges": {
        "fabrication:severe": "Expulsion.",
    },
}


def _base_state(**overrides) -> dict:
    state = {
        "case_id": "CASE-2026-0001",
        "misconduct_type_input": "fabrication of experimental results",
        "subject_role_category": "graduate student",
        "evidence_description": "The dataset does not match the raw instrument logs.",
        "misconduct_classification": "fabrication",
        "severity_tier": "severe",
        "classification_rationale": "Matched fabrication keywords.",
    }
    state.update(overrides)
    return state


class TestMainNode:
    def setup_method(self):
        self.node = MainNode(sanction_kb=_TEST_SANCTION_KB)

    def test_success_path_without_llm(self):
        result = self.node.execute(_base_state())
        assert result["status"] == AgentStatus.SUCCESS.value
        assert "Evidence Review" in result["evidence_review_section"]
        assert "Intent Analysis" in result["intent_analysis_section"]
        assert result["sanction_range_text"]
        assert "CASE-2026-0001" in result["report_draft"]

    def test_success_path_with_llm(self):
        class StubAzureClient:
            """Mimics AzureOpenAIClient.complete(messages) -> {"content": str},
            the shape AzureLlmAdapter wraps -- not the LlmClient.complete(prompt)
            Protocol that draft services see after adaptation."""

            def complete(self, messages):
                return {"content": "Stub LLM narrative text."}

        # MainNode builds its LLM client per-invocation via _build_llm(state)
        # (see its docstring) -- tests inject a fake client by monkeypatching
        # the instance method rather than constructor injection.
        node = MainNode(sanction_kb=_TEST_SANCTION_KB)
        node._build_llm = lambda state: StubAzureClient()
        result = node.execute(_base_state())
        assert result["status"] == AgentStatus.SUCCESS.value
        assert "Stub LLM narrative text." in result["evidence_review_section"]

    def test_report_never_contains_ruling_language_even_with_ruling_llm(self):
        class RulingAzureClient:
            def complete(self, messages):
                return {"content": "We hereby determine the subject is guilty."}

        node = MainNode(sanction_kb=_TEST_SANCTION_KB)
        node._build_llm = lambda state: RulingAzureClient()
        result = node.execute(_base_state())
        assert "guilty" not in result["report_draft"].lower()

    def test_execute_method_signature(self):
        sig = inspect.signature(MainNode.execute)
        params = list(sig.parameters.keys())
        assert len(params) >= 2
        assert params[1] == "state"
        assert "_invoke_impl" not in MainNode.__dict__
