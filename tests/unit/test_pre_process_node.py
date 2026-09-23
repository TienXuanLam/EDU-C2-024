# EDU-C2-024 — Unit Tests: PreProcessNode (steps 1-2: CaseFactsIngest + MisconductTypeClassify)

import inspect
import json

from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from src.nodes.pre_process_node import PreProcessNode


def _valid_payload(**overrides) -> str:
    payload = {
        "misconduct_type": "fabrication of experimental results",
        "evidence_description": "The dataset does not match the raw instrument logs.",
        "subject_role_category": "graduate student",
        "case_id": "CASE-2026-0001",
    }
    payload.update(overrides)
    return json.dumps(payload)


class TestPreProcessNodeExecute:
    def setup_method(self):
        self.node = PreProcessNode()

    def test_success_path(self):
        state = {"user_input": _valid_payload()}
        result = self.node.execute(state)
        assert result["status"] == AgentStatus.SUCCESS.value
        assert result["case_id"] == "CASE-2026-0001"
        assert result["misconduct_classification"] == "fabrication"

    def test_execute_method_signature(self):
        sig = inspect.signature(PreProcessNode.execute)
        params = list(sig.parameters.keys())
        assert len(params) >= 2
        assert params[1] == "state"
        assert "_invoke_impl" not in PreProcessNode.__dict__


class TestPreProcessNodeSecurityGate:
    def setup_method(self):
        self.node = PreProcessNode()

    def _call(self, user_input: str, trust=TrustLevel.VERIFIED_EXTERNAL):
        state = {"user_input": user_input, "caller_trust_level": trust.value}
        return self.node(state)  # via __call__ — exercises the full gate pipeline

    def test_trust_gate_denies_anonymous_caller(self):
        result = self._call(_valid_payload(), trust=TrustLevel.ANONYMOUS)
        assert result["status"] == AgentStatus.ERROR.value

    def test_rejects_real_name_in_evidence_description(self):
        result = self._call(_valid_payload(evidence_description="Reported by John Smith during review."))
        assert result["status"] == AgentStatus.ERROR.value
        # Caught by Layer 1 (raw-input scan, runs before any JSON parsing or
        # LLM call) rather than Layer 2 (parsed-field re-scan) here, since the
        # name appears verbatim in the raw JSON string too -- either layer's
        # message satisfies the "rejected for containing an identifier" intent.
        assert any("name" in e and ("identifier" in e or "student ID" in e) for e in result["error_log"])

    def test_rejects_student_id_in_subject_role_category(self):
        result = self._call(_valid_payload(subject_role_category="student ID 20231234"))
        assert result["status"] == AgentStatus.ERROR.value

    def test_rejects_malformed_json(self):
        result = self._call("not-json")
        assert result["status"] == AgentStatus.ERROR.value

    def test_accepts_clean_payload(self):
        result = self._call(_valid_payload())
        assert result["status"] == AgentStatus.SUCCESS.value
        assert "PreProcessNode" in result["node_history"]
