# PB-01 (domain): Custom S-2 pre-processing check boundary.
#
# Verifies the CaseFactsIngest custom pre-processing check (proposal §3 — a
# custom check *in addition to* the platform S-1 normalizer) actually blocks
# a case containing a real name, student ID, department/affiliation, or
# Japanese-script identifier before it can reach MainNode — i.e. no
# classification/report state is ever produced for rejected input. Covers
# every prohibited identifier class named in proposal §3 S-3 ("no subject
# name, student ID, or department") — review finding H3.

import json

from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from src.nodes.main_node import MainNode
from src.nodes.pre_process_node import PreProcessNode

_TEST_SANCTION_KB = {
    "kb_version": "test-1.0",
    "source": "PB-01 Test Fixture",
    "provenance_verified": True,
    "institution_scope_note": "TEST SCOPE NOTE.",
    "ranges": {"plagiarism:moderate": "Written warning."},
}


def _invoke_pre_then_main(user_input: str) -> dict:
    # A single BaseNode.__call__() only returns that node's own partial
    # update + framework bookkeeping — it does NOT re-include unrelated
    # pre-existing fields (that accumulation is normally done by the
    # LangGraph engine across the whole compiled graph run, not by a single
    # node in isolation). To correctly simulate the pipeline here without a
    # compiled graph, merge each node's result into a persistent running
    # state ourselves — found necessary by running this test against the
    # real framework (caller_trust_level was silently dropped between the
    # two calls otherwise, causing MainNode's own S-1 gate to reject with
    # ANONYMOUS instead of reaching the intended assertion).
    full_state = {"user_input": user_input, "caller_trust_level": TrustLevel.VERIFIED_EXTERNAL.value}
    pre = PreProcessNode()
    full_state.update(pre(full_state))
    if full_state.get("status") == AgentStatus.ERROR.value:
        return full_state  # AgentBaseGraph routes ERROR straight to finalize — main is skipped
    main = MainNode(sanction_kb=_TEST_SANCTION_KB)
    full_state.update(main(full_state))
    return full_state


def _case_payload(**overrides) -> str:
    payload = {
        "misconduct_type": "plagiarism",
        "evidence_description": "Text copied verbatim without citation.",
        "subject_role_category": "undergraduate student",
        "case_id": "CASE-2026-0051",
    }
    payload.update(overrides)
    return json.dumps(payload)


class TestCustomPiiRejectionBoundary:
    def test_leaked_name_never_reaches_main_node(self):
        payload = json.dumps(
            {
                "misconduct_type": "plagiarism",
                "evidence_description": "Reported by Jane Doe, text copied verbatim.",
                "subject_role_category": "undergraduate student",
                "case_id": "CASE-2026-0050",
            }
        )
        state = _invoke_pre_then_main(payload)
        assert state["status"] == AgentStatus.ERROR.value
        assert "report_draft" not in state
        assert "misconduct_classification" not in state

    def test_leaked_department_never_reaches_main_node(self):
        payload = _case_payload(evidence_description="A complaint from the Department of Physics.")
        state = _invoke_pre_then_main(payload)
        assert state["status"] == AgentStatus.ERROR.value
        assert "report_draft" not in state

    def test_leaked_student_id_never_reaches_main_node(self):
        payload = _case_payload(evidence_description="Student ID 20239999 submitted altered data.")
        state = _invoke_pre_then_main(payload)
        assert state["status"] == AgentStatus.ERROR.value
        assert "report_draft" not in state

    def test_leaked_japanese_name_never_reaches_main_node(self):
        payload = _case_payload(evidence_description="Case involves 山田太郎 and copied text.")
        state = _invoke_pre_then_main(payload)
        assert state["status"] == AgentStatus.ERROR.value
        assert "report_draft" not in state

    def test_clean_case_reaches_main_node(self):
        payload = _case_payload()
        state = _invoke_pre_then_main(payload)
        assert state["status"] == AgentStatus.SUCCESS.value
        assert state["report_draft"]


class TestCustomPiiRejectionBoundaryNaturalLanguageInput:
    """Same identifier classes as above, but via free-form NL text instead
    of JSON -- the raw-input Layer 1 scan (pre_process_node.py) must reject
    these before natural-language extraction ever calls an LLM."""

    def test_leaked_name_never_reaches_main_node(self):
        text = "Reported by Jane Doe: a student copied text verbatim, case CASE-2026-0050."
        state = _invoke_pre_then_main(text)
        assert state["status"] == AgentStatus.ERROR.value
        assert "report_draft" not in state

    def test_leaked_department_never_reaches_main_node(self):
        text = "A complaint from the Department of Physics about copied lab data, case CASE-2026-0051."
        state = _invoke_pre_then_main(text)
        assert state["status"] == AgentStatus.ERROR.value
        assert "report_draft" not in state

    def test_leaked_student_id_never_reaches_main_node(self):
        text = "Student ID 20239999 submitted altered experimental data, case CASE-2026-0052."
        state = _invoke_pre_then_main(text)
        assert state["status"] == AgentStatus.ERROR.value
        assert "report_draft" not in state

    def test_leaked_japanese_name_never_reaches_main_node(self):
        text = "Case involves 山田太郎 and copied text, case CASE-2026-0053."
        state = _invoke_pre_then_main(text)
        assert state["status"] == AgentStatus.ERROR.value
        assert "report_draft" not in state

    def test_clean_natural_language_case_reaches_main_node(self, monkeypatch):
        monkeypatch.setenv("STG_MOCK_MODE", "true")
        text = "A student submitted an essay with several paragraphs copied verbatim from an online source."
        state = _invoke_pre_then_main(text)
        assert state["status"] == AgentStatus.SUCCESS.value
        assert state["report_draft"]
