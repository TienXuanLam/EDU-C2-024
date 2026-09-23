"""AgentCore Platform v1.0"""

# main dispatcher — wraps step 3 (EvidenceReviewDraft), step 4
# (IntentDeterminationDraft), step 5 (SanctionRangeLookup), and step 6
# (ReportAssemble).

import os
from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_state import AgentState
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.services.llm.base_llm import BaseLLM
from shared.utils.audit_logger import emit_trace_event

from src.services.azure_openai_service import AzureLlmAdapter, AzureOpenAIService, StgDraftingLLM
from src.services.evidence_review_draft_service import draft_evidence_review
from src.services.intent_determination_draft_service import draft_intent_analysis
from src.services.llm_types import LlmClient
from src.services.report_assemble_service import assemble_report
from src.services.sanction_range_lookup_service import (
    is_sample_kb,
    load_sanction_kb,
    lookup_sanction_range,
)


class MainNode(FunctionNode):
    """Step 3-6: draft evidence review + intent analysis, look up sanction
    range, assemble the full MEXT-guideline report draft."""

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def __init__(self, sanction_kb: dict[str, Any] | None = None, llm_config: dict[str, Any] | None = None) -> None:
        if sanction_kb is None:
            from src.graph.domain_workflow_graph import _DEFAULT_KB_PATH

            sanction_kb = load_sanction_kb(str(_DEFAULT_KB_PATH))
        self._sanction_kb = sanction_kb
        self._llm_service = AzureOpenAIService(llm_config)

    def _build_llm(self, state: dict[str, Any]) -> BaseLLM | None:
        """Build a fresh, secret-bound Azure OpenAI client for this
        invocation, or None if unavailable. Production path only -- see
        _drafting_llm() for STG_MOCK_MODE handling and adapter wrapping."""
        try:
            return self._llm_service.create_client(state)
        except Exception:  # noqa: BLE001 — missing/invalid secret; fail-open to deterministic
            return None

    def _drafting_llm(self, state: dict[str, Any]) -> LlmClient | None:
        """Return the LlmClient the drafting services should call, or None
        to fall back to their deterministic templates -- see
        PreProcessNode._drafting_llm's docstring for the fail-open rationale
        and the STG stub split (this must be prose, not case-facts JSON)."""
        if os.environ.get("STG_MOCK_MODE", "").lower() == "true":
            return StgDraftingLLM()
        azure_client = self._build_llm(state)
        return AzureLlmAdapter(azure_client) if azure_client is not None else None

    def execute(self, state: AgentState) -> dict[str, Any]:
        classification = state.get("misconduct_classification", "other")
        severity = state.get("severity_tier", "moderate")
        evidence_description = state.get("evidence_description", "")

        llm = self._drafting_llm(state)

        evidence_review_section = draft_evidence_review(evidence_description, classification, severity, llm=llm)
        if llm is not None:
            emit_trace_event("llm_call", {"step": "evidence_review_draft"}, state)

        intent_analysis_section = draft_intent_analysis(evidence_description, classification, severity, llm=llm)
        if llm is not None:
            emit_trace_event("llm_call", {"step": "intent_determination_draft"}, state)

        sanction_range_text = lookup_sanction_range(self._sanction_kb, classification, severity)
        emit_trace_event(
            "sanction_range_looked_up",
            {
                "classification": classification,
                "severity_tier": severity,
                "kb_version": self._sanction_kb.get("kb_version"),
                "kb_source": self._sanction_kb.get("source"),
                "kb_is_sample": is_sample_kb(self._sanction_kb),
            },
            state,
        )

        report_draft = assemble_report(
            case_id=state.get("case_id", ""),
            misconduct_type_input=state.get("misconduct_type_input", ""),
            subject_role_category=state.get("subject_role_category", ""),
            classification=classification,
            severity=severity,
            classification_rationale=state.get("classification_rationale", ""),
            evidence_review_section=evidence_review_section,
            intent_analysis_section=intent_analysis_section,
            sanction_range_text=sanction_range_text,
        )

        return {
            "evidence_review_section": evidence_review_section,
            "intent_analysis_section": intent_analysis_section,
            "sanction_range_text": sanction_range_text,
            "report_draft": report_draft,
            "status": AgentStatus.SUCCESS.value,
        }
