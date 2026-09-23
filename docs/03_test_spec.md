# Test Specification

## Test Strategy
- Coverage target: 100% of `src/services/*.py` and `src/nodes/*.py` (all deterministic
  domain logic and node dispatch paths)
- Test types: Unit (`tests/unit/`) + Proof-of-Boundary (`tests/proof_of_boundary/`).
  No integration tests — the sanction-range KB is a local, institution-configurable
  JSON file (`src/services/kb/sanction_ranges.json`, overridable via `config.yaml`'s `kb_path`),
  not a remote service; LLM is optional with a deterministic fallback for every
  drafting step.
- Real-CI confirmation: verified against the real `agenticstar-agentcore` framework
  (not only a local stub) both in local development and on the MR pipeline —
  all 12 CI jobs green. Local dev verification additionally used `check-security.sh`
  and `check-local.sh` (EngineerGuide/ScriptCheckCI) end to end, including a live
  Stage 5 STG invoke smoke check (`overall: PASS`).

## Detection Scope Statement (review finding H1)

The S-2 custom pre-processing check (`src/services/case_facts_ingest_service.py`)
and the S-3 output re-scan (`src/services/output_validate_service.py`) cover four
concrete, testable identifier patterns:

1. Cue-gated ASCII personal names (e.g. "Reported by John Smith")
2. 6–10 digit ID-shaped runs (student IDs)
3. Department/affiliation cue phrases ("Department of X", "Faculty of X", "School of X", "Institute of X", "Graduate School of X", "Division of X")
4. Embedded Japanese-script (kanji/hiragana/katakana) runs — no cue word required,
   since this template's own generated content is pure ASCII English

**This is a best-effort, defense-in-depth heuristic layer, not an exhaustive
free-text PII detector.** Reliable universal free-text PII detection (arbitrary
scripts, arbitrary phrasing, no false negatives) is not feasible for a
keyword/regex layer. Primary responsibility for submitting genuinely anonymized
case facts rests with the calling disciplinary-committee system (proposal §3);
this layer is a secondary check, not a substitute for anonymization at the
source. See `docs/02_design.md` "S-2/S-3 Detection Scope" for the full policy
statement and `src/services/case_facts_ingest_service.py` module docstring for
implementation detail.

## Framework Compliance Tests (Mandatory)

| TC-ID | Test | Expected Result | Result |
|-------|------|----------------|--------|
| TC-01 | State contract: flat TypedDict (`src/schemas/state.py`) | Type check pass, no Pydantic/dataclass — confirmed by `tests/proof_of_boundary/test_state_safety.py` | PASS |
| TC-02 | Invalid/malformed input rejected | `PreProcessNode` custom S-2 gate rejects malformed JSON / missing fields — `tests/unit/test_pre_process_node.py::TestPreProcessNodeSecurityGate` | PASS |
| TC-03 | No JWT/Credential in State | CI `gate-credential-scan`: 0 violations | PASS (MR pipeline green) |
| TC-04 | InvocationContext via `from_state()` only | No node in this template constructs `InvocationContext` directly (confirmed by code review — no secret-gated dependency is required; every drafting step has a deterministic fallback) | PASS |
| TC-05 | S-4: no duplicate lifecycle events in `execute()` | `node_start`/`node_complete`/`node_error` absent from all 3 `execute()` bodies (confirmed by code review) | PASS |
| TC-06 | S-2: `_security_gate_input()` not overridden | `FunctionNode.__init_subclass__` raises `TypeError` if overridden — none of the 3 nodes override it (only `_extra_security_gate_input()` on `PreProcessNode`) | PASS |
| TC-07 | S-3: `_security_gate_output()` not overridden | Same as TC-06 — only `_extra_security_gate_output()` on `PostProcessNode` | PASS |
| TC-08 | `required_trust_level` enforced (via `__call__`, not `execute()`) | `tests/unit/test_pre_process_node.py::test_trust_gate_denies_anonymous_caller` (calls `node(state)`) | PASS |
| TC-09 | S-2 `_extra_security_gate_input()` non-trivial | `PreProcessNode` rejects real name/student ID/department/Japanese-script identifier — `tests/unit/test_pre_process_node.py` | PASS |
| TC-10 | S-3 `_extra_security_gate_output()` non-trivial | `PostProcessNode` independently re-scans for subject PII, may raise — `tests/unit/test_post_process_node.py::TestPostProcessNodeOutputGateHook` | PASS |
| TC-11 | S-4: ≥1 domain `emit_trace_event()` per node | `misconduct_classified` (pre_process), `llm_call`×2 + `sanction_range_looked_up` incl. KB version/source (main), `output_pii_scan` (post_process) — confirmed by code review | PASS |

## Proof-of-Boundary Tests (Mandatory)

| PB-ID | Boundary | Test | Expected Result | Result |
|-------|----------|------|----------------|--------|
| PB-1 | BaseNode → AuditLogger | `emit_trace_event()` fires on every node (see TC-11) | No silent failures | PASS |
| PB-2 | State serialization | `test_state_safety.py` | No Pydantic/dataclass/credential fields in `src/schemas/state.py` | PASS |
| PB-3 | L1 → External service | N/A — the sanction-range KB is a local, institution-configurable file (not a remote service call); LLM is optional, not required | Not applicable | N/A |
| PB-4 | Import isolation | `test_import_isolation.py` | AST scan: 0 violations across `src/` (including `src/services/`, which import neither `framework` nor `shared`) | PASS |
| PB-5 | Checkpoint safety | Covered by PB-2 (same state definition) | No JWT/Pydantic in checkpoint | PASS |
| PB-6 | Invoke execution order | `test_pb_invoke_order.py` (state customized with a valid case-facts JSON `user_input` + a test sanction KB fixture covering MainNode's `state.get(..., default)` fallback combo, so neither PreProcessNode's custom S-2 gate nor MainNode's KB lookup short-circuits before the full order completes) | S-1 → `node_start` → S-2 → `execute()` → S-3 → `node_complete`, for all 3 nodes | PASS |
| PB-7 | HITL interrupt propagation | Not applicable — `config/config.yaml` does not set `hitl.enabled: true` (legal counsel / integrity officer review is an out-of-band human process, not a technical `interrupt()` checkpoint; see `docs/02_design.md`) | **Auto-waived — non-HITL** | SKIPPED (2 tests, by design) |

## Domain Proof-of-Boundary Tests

| PB-ID | Boundary | Test | Expected Result | Result |
|-------|----------|------|----------------|--------|
| PB-01 | Custom S-2 pre-processing check (CaseFactsIngest → MainNode) | `test_pb01_custom_pii_rejection.py` | A case with a leaked real name, student ID, department/affiliation, **or Japanese-script identifier** never produces `report_draft`/`misconduct_classification` state — rejected before reaching `main` (review finding H3: covers every prohibited identifier class named in proposal §3, not just name/ID) | PASS |
| PB-02 | S-3 output gate (belt-and-suspenders re-scan) | `test_pb02_s3_output_pii_block.py` | A report with a leaked name/student ID/**department/Japanese-script identifier** is blocked via the real `__call__()` pipeline, and independently via the gate hook even if the execute()-level check is bypassed | PASS |
| PB-03 | Deterministic-vs-LLM authority | `test_pb03_deterministic_classification.py` | `classify_misconduct()` / `lookup_sanction_range()` signatures have no `llm` parameter; both are pure functions | PASS |
| PB-04 | Advisory-only guarantee (proposal §11 Risk #1) | `test_pb04_advisory_only_no_ruling_language.py` | No adversarial LLM output survives into the assembled report (evidence review, intent analysis, **and classification rationale — review finding M1**); this template's own fallback templates contain no ruling-shaped language | PASS |
| PB-05 | Sanction-range KB governance (review finding H2/M2/M1-round-2) | `test_pb05_sanction_kb_governance.py` | Default `kb_path` compiles and carries version/source provenance and is correctly flagged `is_sample_kb() == True`; a missing or structurally invalid KB file fails `agent.compile()` (fail-closed); a custom `kb_path` genuinely overrides the shipped reference KB **via the real deployment loading path** (`src.api.server._load_runtime_config()` reading a temp `config.yaml`, not only constructor injection — review finding H1/M2 round 2); importing `src.api.server` itself (the actual entry point) compiles successfully against the real repo files | PASS |

> **Pre-CoE gate checklist:** PB-1 through PB-6 are mandatory (PB-3 N/A per
> above). PB-7 is auto-waived — non-HITL. PB-01 through PB-05 are
> domain-specific additions covering this template's highest proposal risks
> (§11 Risk #1: LLM legal-quality risk; §11 Risk #2: institution-specific
> policy variation; and the S-2/S-3 no-subject-PII/department requirement).

## Business Logic Tests

| TC-ID | Test | Input | Expected Result | Result |
|-------|------|-------|----------------|--------|
| BL-01 | MEXT taxonomy classification — fabrication/falsification/plagiarism/other | Keyword-bearing `misconduct_type`/`evidence_description` per category | Correct classification returned deterministically | PASS (`test_misconduct_classify_service.py`) |
| BL-02 | Severity tier — minor/moderate/severe | Keyword-bearing text ("repeated pattern", "isolated citation error", neutral) | Correct severity tier, default `moderate` when unmatched | PASS (`test_misconduct_classify_service.py`) |
| BL-03 | Sanction range KB — load/validate + lookup, valid & invalid KB files | Valid KB, missing file, invalid JSON, missing required key, empty ranges, unknown classification/severity combination | Valid KB loads with version/source; every failure mode raises `SanctionKbError` (fail-closed) rather than substituting a silent default | PASS (`test_sanction_range_lookup_service.py`) |
| BL-04 | Report assembly — all MEXT sections present | Full set of drafted sections | Markdown report contains Allegation Overview, Investigation Procedure, Evidence Review, Intent Analysis, Sanction Recommendation | PASS (`test_report_assemble_service.py`) |
| BL-05 | Mandatory disclaimer on every released report | Clean report draft | Output is prefixed with the "AI DRAFT — NOT A FINAL DETERMINATION" disclaimer | PASS (`test_output_validate_service.py`) |
| BL-06 | Real-name/student-ID false-positive regression (A8) | Text containing this template's own heading label "Subject Role Category" | Not flagged as a PII violation | PASS (`test_output_validate_service.py::test_own_heading_not_false_positive`) |
| BL-07 | Department/affiliation detection (review finding H1) | "Department of Physics", "Faculty of Engineering", "School of Medicine"; cue phrase with nothing following | Flagged as identifiers; bare cue phrase with no following word not flagged | PASS (`test_case_facts_ingest_service.py`) |
| BL-08 | Japanese-script identifier detection (review finding H1) | Bare "山田太郎" (no cue word needed) | Flagged as an identifier | PASS (`test_case_facts_ingest_service.py`) |
| BL-09 | Classification-rationale ruling-language filter (review finding M1) | Adversarial LLM stub returning ruling-shaped text | Discarded in favor of the deterministic fallback rationale | PASS (`test_misconduct_classify_service.py::test_llm_ruling_language_discarded_fail_safe`) |
| BL-10 | Operator-facing config.yaml loading path (review finding H1, round 2) | Temp `config.yaml` with a custom `kb_path`, loaded via `src.api.server._load_runtime_config()` (the exact function the real entry point calls) | Custom KB reaches the compiled agent; a malformed configured `kb_path` fails `agent.compile()` the same way as constructor injection | PASS (`test_pb05_sanction_kb_governance.py::TestDeploymentConfigLoadingPath`) |
| BL-11 | KB provenance gate (review finding M1, round 2) | Shipped `src/services/kb/sanction_ranges.json`; a KB missing `provenance_verified`; a KB with `provenance_verified: false` | Missing key fails closed (`SanctionKbError`); `false` loads but emits a `UserWarning` naming the file and version; `is_sample_kb()` correctly classifies both the shipped KB (`True`) and a verified test KB (`False`) | PASS (`test_sanction_range_lookup_service.py`, `test_pb05_sanction_kb_governance.py`) |

## Test Execution Summary
- Execution date: 2026-09-17
- LLM provider migrated Anthropic → Azure OpenAI (per-invocation
  `AzureOpenAIService`, see `docs/02_design.md` "LLM Provider"); input format
  extended to accept natural-language free text as the primary path, with
  the legacy JSON-encoded string still fully supported (see `docs/02_design.md`
  "Input Format").
- Current suite: 155 collected (152 passed, 3 skipped — PB-7 HITL cases not
  applicable to this template's non-interrupt design). New coverage added
  for the provider swap and NL-input: `test_azure_openai_service.py`,
  `test_nl_case_facts_extraction_service.py`,
  `test_pb06_nl_input_raw_pii_never_reaches_llm.py`, plus NL-input cases
  added to `test_pb01_custom_pii_rejection.py` and a rewritten
  `test_server_llm_injection.py` (server boots without Azure secrets, LLM
  built per-invocation not at module scope, two invocations never share a
  client instance).
- Verified against the real `agenticstar-agentcore` framework, both locally
  and on the MR CI pipeline — not solely a local dev stub. **Auditability
  (review finding L1, round 2):** exact pipeline evidence for this revision is
  the MR !1 pipeline at commit `b6d5d3fc` and each subsequent push —
  see the repository's MR !1 for the live job list/logs/artifacts; record the specific job URL here
  again after the next pipeline run confirms this revision.
- Local gates after migration: `pytest tests/`, `ruff check src/`,
  `ruff format --check src/`, and strict `mypy src/` pass. The distributed
  security/local scripts and live Stage 5 evidence are rerun before handoff.
- Coverage: 100% of `src/services/*.py` (7/7 modules) and `src/nodes/*.py` (3/3 modules)
  have dedicated unit tests, plus 5 domain proof-of-boundary tests (PB-01 through PB-05,
  PB-05 now also covering the real deployment config-loading path)
