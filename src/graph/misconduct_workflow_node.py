"""GraphNode boundary for the academic-misconduct domain workflow."""

from __future__ import annotations

from typing import Any, ClassVar

from framework.nodes.graph_node import GraphNode
from framework.schemas.agent_state import AgentState
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel

from src.graph.domain_workflow_graph import MisconductDomainWorkflowGraph
from src.graph.domain_workflow_graph import _DEFAULT_KB_PATH
from src.services.sanction_range_lookup_service import load_sanction_kb


class MisconductWorkflowGraphNode(GraphNode):
    """Run the seven-step workflow as the Cat 2 outer graph's main slot."""

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL
    error_strategy: ClassVar[str] = "propagate"
    propagate_hitl: ClassVar[bool] = False

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = dict(config or {})
        self._sanction_kb = load_sanction_kb(str(self._config.get("kb_path", _DEFAULT_KB_PATH)))
        self._config["sanction_kb"] = self._sanction_kb

    def get_subgraph(self) -> MisconductDomainWorkflowGraph:
        return MisconductDomainWorkflowGraph(config=self._config)

    def extract_input(self, state: AgentState) -> str:
        return str(state.get("validated_input", state.get("user_input", "")))

    def merge_output(self, state: AgentState, sub_result: dict[str, Any]) -> dict[str, Any]:
        output = sub_result.get("output")
        if not isinstance(output, dict):
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["Misconduct workflow returned malformed output."],
            }
        merged = dict(output)
        merged["status"] = sub_result.get("status", AgentStatus.ERROR.value)
        if sub_result.get("error_log"):
            merged["error_log"] = sub_result["error_log"]
        return merged
