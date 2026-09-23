"""Outer Cat 2 graph for the academic-misconduct report workflow."""

from framework.graph.agent_base_graph import AgentBaseGraph

from src.graph.misconduct_workflow_node import MisconductWorkflowGraphNode
from src.nodes.outer_input_node import OuterInputNode
from src.nodes.outer_output_node import OuterOutputNode
from src.schemas.state import State


class UniversityAcademicMisconductInvestigationReportDraftingAgent(AgentBaseGraph):
    """Expose the fixed platform backbone around the seven-step domain graph."""

    @property
    def name(self) -> str:
        return "UniversityAcademicMisconductInvestigationReportDraftingAgent"

    @property
    def state_schema(self) -> type:
        return State

    def register_nodes(self) -> None:
        super().register_nodes()
        self._nodes["pre_process"] = OuterInputNode()
        self._nodes["main"] = MisconductWorkflowGraphNode(config=self.config)
        self._nodes["post_process"] = OuterOutputNode()
