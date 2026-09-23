"""AgentCore Platform v1.0"""

# ADR-005: State must be a flat TypedDict (see ADR-005 for the prohibited
# alternatives). LangGraph checkpoints use msgpack serialization, so only
# plain serializable fields are allowed. Do NOT add credentials or secrets.
#
# Node-count reconciliation: the proposal's Agent Workflow (§4) describes a
# 7-step pipeline, but AgentBaseGraph only exposes 3 domain slots
# (pre_process/main/post_process). The 7 steps are pure-Python step helpers
# invoked in sequence inside the 3 real FunctionNode dispatchers — see
# docs/02_design.md "Architecture Overview" for the full mapping. State
# fields below are named per step output, not per node, so the data flow is
# traceable regardless of which node currently owns a given step.

from framework.schemas.agent_state import AgentState


class State(AgentState):
    """Agent state for UniversityAcademicMisconductInvestigationReportDraftingAgent.

    No field ever holds a subject name, student ID, or department — the only
    per-case identifier carried through the pipeline is the caller-supplied
    anonymized `case_id` code (§3 Security Requirements — S-5: no PII in
    AgentState).
    """

    # Step 1 — CaseFactsIngest (parsed from user_input, a JSON string with
    # keys: misconduct_type, evidence_description, subject_role_category,
    # case_id)
    case_id: str
    misconduct_type_input: str
    evidence_description: str
    subject_role_category: str

    # Step 2 — MisconductTypeClassify (deterministic; see docs/02_design.md
    # Design Decision Record — classification is legally significant and
    # must not be LLM-authoritative)
    misconduct_classification: str  # fabrication | falsification | plagiarism | other
    severity_tier: str  # minor | moderate | severe
    classification_rationale: str  # narrative-only; never overrides the two fields above

    # Step 3 — EvidenceReviewDraft
    evidence_review_section: str

    # Step 4 — IntentDeterminationDraft (advisory only — never a final ruling)
    intent_analysis_section: str

    # Step 5 — SanctionRangeLookup (deterministic KB lookup)
    sanction_range_text: str

    # Step 6 — ReportAssemble
    report_draft: str

    # Step 7 — OutputValidate (S-3: belt-and-suspenders re-scan, independent
    # of the platform's default credential scan)
    output_pii_violations: str  # JSON-encoded list[str] (ADR-005) — "[]" when clean
