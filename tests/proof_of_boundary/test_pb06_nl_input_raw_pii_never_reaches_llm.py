# PB-06 (domain): Natural-language input raw-PII-never-reaches-LLM boundary.
#
# The natural-language extraction path (NLCaseFactsExtractionService) sends
# raw user text to an LLM prompt. If a caller's free-form text contains a
# real name, student ID, department, or Japanese-script name, that text must
# never leave this process in an outbound LLM call -- Layer 1 of
# PreProcessNode._extra_security_gate_input (contains_disallowed_identifier
# on the RAW input) must reject before _build_llm()/extract() is ever
# invoked. This test verifies that boundary directly, independent of the
# end-to-end assertions in test_pb01_custom_pii_rejection.py.

from unittest.mock import Mock

from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from src.nodes.pre_process_node import PreProcessNode


def _call_with_mocked_llm(user_input: str) -> tuple[dict, Mock]:
    node = PreProcessNode()
    # NLCaseFactsExtractionService is the component that would actually build
    # an LLM client and call it for the natural-language path -- mock its
    # _build_llm so we can assert whether it was ever reached, independent
    # of PreProcessNode's own _build_llm (used later for the rationale draft,
    # which only runs after case facts are already accepted).
    mock_build_llm = Mock(return_value=Mock(complete=Mock(return_value={"content": "{}"})))
    node._nl_extraction_service._build_llm = mock_build_llm
    state = {"user_input": user_input, "caller_trust_level": TrustLevel.VERIFIED_EXTERNAL.value}
    result = node(state)
    return result, mock_build_llm


class TestRawPiiNeverReachesLlm:
    def test_leaked_name_rejected_before_any_llm_call(self):
        text = "Reported by Jane Doe: a student copied text verbatim, case CASE-2026-0060."
        result, mock_build_llm = _call_with_mocked_llm(text)
        assert result["status"] == AgentStatus.ERROR.value
        mock_build_llm.assert_not_called()

    def test_leaked_department_rejected_before_any_llm_call(self):
        text = "A complaint from the Department of Physics about copied lab data, case CASE-2026-0061."
        result, mock_build_llm = _call_with_mocked_llm(text)
        assert result["status"] == AgentStatus.ERROR.value
        mock_build_llm.assert_not_called()

    def test_leaked_student_id_rejected_before_any_llm_call(self):
        text = "Student ID 20239999 submitted altered experimental data, case CASE-2026-0062."
        result, mock_build_llm = _call_with_mocked_llm(text)
        assert result["status"] == AgentStatus.ERROR.value
        mock_build_llm.assert_not_called()

    def test_leaked_japanese_name_rejected_before_any_llm_call(self):
        text = "Case involves 山田太郎 and copied text, case CASE-2026-0063."
        result, mock_build_llm = _call_with_mocked_llm(text)
        assert result["status"] == AgentStatus.ERROR.value
        mock_build_llm.assert_not_called()

    def test_clean_natural_language_input_does_reach_llm(self):
        text = "A student submitted an essay with several paragraphs copied verbatim from an online source."
        _, mock_build_llm = _call_with_mocked_llm(text)
        # Sanity check for the mock itself: clean NL text (no disallowed
        # identifier) must still reach the LLM-based extraction path,
        # otherwise the "never reaches LLM" assertions above would be
        # vacuously true for every input, not just PII-bearing ones.
        mock_build_llm.assert_called()

    def test_valid_json_input_does_not_trigger_nl_extraction_llm_call(self):
        # The legacy JSON-string path is untouched by this refactor: it must
        # not build an LLM client at all (parse_case_facts doesn't call it),
        # confirming Layer-1/NL-extraction only activates for non-JSON input.
        import json

        payload = json.dumps(
            {
                "misconduct_type": "plagiarism",
                "evidence_description": "Text copied verbatim without citation.",
                "subject_role_category": "undergraduate student",
                "case_id": "CASE-2026-0064",
            }
        )
        _, mock_build_llm = _call_with_mocked_llm(payload)
        mock_build_llm.assert_not_called()
