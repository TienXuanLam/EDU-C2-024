"""Inner seven-step academic-misconduct report workflow."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from langgraph.graph import END, START

from framework.graph.base_graph import BaseGraph
from framework.schemas.agent_status import AgentStatus

from src.nodes.main_node import MainNode
from src.nodes.post_process_node import PostProcessNode
from src.nodes.pre_process_node import PreProcessNode
from src.schemas.state import State
from src.services.sanction_range_lookup_service import load_sanction_kb

_DEFAULT_KB_PATH = Path(__file__).resolve().parents[1] / "services" / "kb" / "sanction_ranges.json"


class MisconductDomainWorkflowGraph(BaseGraph):
    """Own the ordered ingest, drafting, policy lookup, and output gates."""

    @property
    def name(self) -> str:
        return "edu_c2_024_misconduct_domain_workflow"

    @property
    def state_schema(self) -> type:
        return State

    def _validate_config(self) -> None:
        if "sanction_kb" not in self.config:
            load_sanction_kb(str(self.config.get("kb_path", _DEFAULT_KB_PATH)))

    def register_nodes(self) -> None:
        configured_kb = self.config.get("sanction_kb")
        sanction_kb = (
            configured_kb
            if isinstance(configured_kb, dict)
            else load_sanction_kb(str(self.config.get("kb_path", _DEFAULT_KB_PATH)))
        )
        # LLM tuning only (temperature/max_tokens) -- PreProcessNode/MainNode
        # each build their own secret-bound AzureOpenAIClient per invocation
        # via _build_llm(state); no client is ever assigned to this dict.
        llm_config = {k: v for k, v in self.config.items() if k in ("temperature", "max_tokens")}
        self._nodes = {
            "case_ingest_and_classify": PreProcessNode(llm_config=llm_config),
            "review_and_assemble": MainNode(sanction_kb=sanction_kb, llm_config=llm_config),
            "validate_output": PostProcessNode(),
        }

    def add_edges(self) -> None:
        self._sg.add_edge(START, "case_ingest_and_classify")
        self._sg.add_edge("case_ingest_and_classify", "review_and_assemble")
        self._sg.add_edge("review_and_assemble", "validate_output")
        self._sg.add_edge("validate_output", END)

    def route(self, state: State) -> str:
        return END

    def get_output(self, state: State) -> dict[str, Any]:
        fields = (
            "case_id",
            "misconduct_type_input",
            "subject_role_category",
            "misconduct_classification",
            "severity_tier",
            "classification_rationale",
            "evidence_review_section",
            "intent_analysis_section",
            "sanction_range_text",
            "report_draft",
            "output_pii_violations",
            "formatted_output",
        )
        return {
            "output": {key: state.get(key) for key in fields if state.get(key) is not None},
            "status": state.get("status", AgentStatus.ERROR.value),
            "error_log": state.get("error_log", []),
            "trace_id": state.get("trace_id", ""),
        }
