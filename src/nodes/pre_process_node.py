"""AgentCore Platform v1.0"""

# pre_process dispatcher — wraps step 1 (CaseFactsIngest) and step 2
# (MisconductTypeClassify) per the node-count reconciliation in
# docs/02_design.md (7 proposal steps -> 3 AgentBaseGraph slots).

import os
from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_state import AgentState
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.services.llm.base_llm import BaseLLM
from shared.utils.audit_logger import emit_trace_event

from src.services.azure_openai_service import AzureLlmAdapter, AzureOpenAIService, StgDraftingLLM
from src.services.case_facts_ingest_service import (
    contains_disallowed_identifier,
    looks_like_natural_language,
    parse_case_facts,
)
from src.services.llm_types import LlmClient
from src.services.misconduct_classify_service import build_classification_rationale, classify_misconduct
from src.services.nl_case_facts_extraction_service import NLCaseFactsExtractionError, NLCaseFactsExtractionService


class PreProcessNode(FunctionNode):
    """Step 1 (CaseFactsIngest) + Step 2 (MisconductTypeClassify)."""

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def __init__(self, llm_config: dict[str, Any] | None = None) -> None:
        self._llm_service = AzureOpenAIService(llm_config)
        self._nl_extraction_service = NLCaseFactsExtractionService(llm_config)

    def _build_llm(self, state: dict[str, Any]) -> BaseLLM | None:
        """Build a fresh, secret-bound Azure OpenAI client for this
        invocation, or None if unavailable (missing/invalid secret).
        Production path only -- see _drafting_llm() for STG_MOCK_MODE
        handling and adapter wrapping."""
        try:
            return self._llm_service.create_client(state)
        except Exception:  # noqa: BLE001 — missing/invalid secret; fail-open to deterministic
            return None

    def _drafting_llm(self, state: dict[str, Any]) -> LlmClient | None:
        """Return the LlmClient this node's drafting services should call,
        or None to fall back to their deterministic templates. EDU-C2-024 is
        fail-open by design (see evidence_review_draft_service.py /
        intent_determination_draft_service.py): every drafting service
        already falls back to a deterministic template when llm is None, so
        a missing/invalid secret must never surface as an error to the
        caller -- unlike a fail-closed template, this agent must always be
        able to produce a draft report.

        STG_MOCK_MODE=true returns a deterministic narrative stub directly
        (already LlmClient-shaped, complete(prompt) -> str) -- distinct from
        NLCaseFactsExtractionService's own STG stub, which must return
        structured case-facts JSON instead of prose.
        """
        if os.environ.get("STG_MOCK_MODE", "").lower() == "true":
            return StgDraftingLLM()
        azure_client = self._build_llm(state)
        return AzureLlmAdapter(azure_client) if azure_client is not None else None

    def _extra_security_gate_input(self, state: AgentState) -> AgentState:
        # S-2 custom pre-processing check (proposal §3): reject real names /
        # student IDs in evidence_description or subject_role_category.
        # Separate from, and in addition to, the platform S-1 normalizer.
        # Must not raise — surface rejection via state["status"].
        state = dict(state)
        raw = state.get("user_input", "")

        # Layer 1: scan the RAW text before it can ever reach an LLM prompt,
        # whether via NL-extraction below or the JSON path. A name/ID/
        # department typed into free-form NL input must never leave this
        # process in an outbound LLM call.
        if contains_disallowed_identifier(raw):
            state["status"] = AgentStatus.ERROR.value
            state["error_log"] = [
                "CaseFactsIngest: rejected — input appears to contain a real name, "
                "student ID, or department (custom S-2 pre-processing check, raw-input scan)"
            ]
            return state

        case_facts: dict[str, str]
        if looks_like_natural_language(raw):
            try:
                case_facts = self._nl_extraction_service.extract(state, raw)
            except NLCaseFactsExtractionError as exc:
                state["status"] = AgentStatus.ERROR.value
                state["error_log"] = [f"CaseFactsIngest: {exc.message}"]
                return state
        else:
            parsed_case_facts, error = parse_case_facts(raw)
            if error:
                state["status"] = AgentStatus.ERROR.value
                state["error_log"] = [error]
                return state
            assert parsed_case_facts is not None
            case_facts = parsed_case_facts

        # Layer 2 (unchanged): re-scan the parsed/extracted fields — defense
        # in depth for PII the LLM itself might reintroduce (rare, but the
        # extraction prompt cannot be trusted as the sole safeguard).
        for field in ("evidence_description", "subject_role_category"):
            if contains_disallowed_identifier(case_facts[field]):
                state["status"] = AgentStatus.ERROR.value
                state["error_log"] = [
                    f"CaseFactsIngest: rejected — '{field}' appears to contain a real "
                    "name or student ID (custom S-2 pre-processing check)"
                ]
                return state

        # Cache so execute() doesn't re-parse the JSON path or re-call the
        # LLM for the NL path (verified: FunctionNode.__call__ passes this
        # same state dict straight from _security_gate_input() to execute()).
        state["_case_facts"] = case_facts
        return state

    def execute(self, state: AgentState) -> dict[str, Any]:
        case_facts = state.get("_case_facts")
        if case_facts is None:
            # Defense in depth: unreachable in normal operation, the gate
            # hook above already populates this or rejects.
            case_facts, error = parse_case_facts(state.get("user_input", ""))
            if error:
                return {"status": AgentStatus.ERROR.value, "error_log": [error]}

        classification, severity = classify_misconduct(
            case_facts["misconduct_type"], case_facts["evidence_description"]
        )
        rationale = build_classification_rationale(classification, severity, llm=self._drafting_llm(state))

        emit_trace_event(
            "misconduct_classified",
            {"classification": classification, "severity_tier": severity},
            state,
        )

        return {
            "case_id": case_facts["case_id"],
            "misconduct_type_input": case_facts["misconduct_type"],
            "evidence_description": case_facts["evidence_description"],
            "subject_role_category": case_facts["subject_role_category"],
            "misconduct_classification": classification,
            "severity_tier": severity,
            "classification_rationale": rationale,
            "status": AgentStatus.SUCCESS.value,
        }
