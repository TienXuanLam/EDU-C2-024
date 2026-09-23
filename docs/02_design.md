# Template Design Specification

## Position in AgentCore Architecture

- **Agent Class**: `UniversityAcademicMisconductInvestigationReportDraftingAgent`
- **L1 Base**: `AgentBaseGraph` (Cat 2 — fixed multi-step domain workflow, not an
  autonomous think→act→observe loop; see docs/01_proposal.md Cat Judgment Rationale)
- **Pattern**: `DocGenerationAgent` (Level 2 label; mechanism is always
  L1-direct `AgentBaseGraph` inheritance)
- **Three-Layer Separation**:
  - State: flat `TypedDict` composition (`src/schemas/state.py`, extends `AgentState`)
  - Node: L1 inheritance (Template Method: `execute(self, state) -> dict` override only)
  - Graph: Cat 2 composition: fixed outer `AgentBaseGraph`, a `GraphNode` in its
    `main` slot, and an inner `BaseGraph` that owns the domain topology

## Architecture Overview

### Cat 2 topology (latest scaffold contract)

The outer graph retains the platform's fixed three-slot backbone. Its `main`
slot is `MisconductWorkflowGraphNode`; that node invokes
`MisconductDomainWorkflowGraph`, an inner `BaseGraph` under `src/graph/`.
The inner graph preserves the approved seven-step business sequence by wiring
the existing three security-gated domain dispatchers linearly:

```
outer: initialize → OuterInputNode → MisconductWorkflowGraphNode → OuterOutputNode → finalize

inner: PreProcessNode
  → CaseFactsIngest            (step 1 — case_facts_ingest_service.parse_case_facts +
                                          contains_disallowed_identifier, also wired into
                                          _extra_security_gate_input as the custom S-2 check)
  → MisconductTypeClassify     (step 2 — misconduct_classify_service.classify_misconduct
                                          [deterministic] + build_classification_rationale
                                          [LLM narrative only, optional])

  → MainNode
  → EvidenceReviewDraft        (step 3 — evidence_review_draft_service.draft_evidence_review
                                          [LLM with deterministic fallback])
  → IntentDeterminationDraft   (step 4 — intent_determination_draft_service.draft_intent_analysis
                                          [LLM with deterministic fallback + ruling-language filter])
  → SanctionRangeLookup        (step 5 — sanction_range_lookup_service.lookup_sanction_range
                                          [deterministic, file-backed KB — src/services/kb/sanction_ranges.json,
                                          institution-configurable via config.yaml's kb_path])
  → ReportAssemble             (step 6 — report_assemble_service.assemble_report
                                          [deterministic string assembly])

  → PostProcessNode
  → OutputValidate             (step 7 — output_validate_service.find_subject_pii_violations +
                                          attach_disclaimer; also wired into
                                          _extra_security_gate_output as a second,
                                          independent re-scan — defense in depth)
```

### Node Configuration

| Node | Responsibility | Input State | Output State | Inherits/Overrides |
|------|---------------|-------------|--------------|-------------------|
| initialize | Standard state setup | — | `session_id`, `caller_trust_level`, `node_history=[]`, `error_log=[]` | `InitializeNode` (default) |
| outer pre_process | Normalize and forward the caller input to the domain boundary | `user_input` | `validated_input` | `OuterInputNode` / `FunctionNode` |
| outer main | Invoke the complete inner domain workflow and merge only its declared output | `validated_input` | domain result fields, `formatted_output` | `MisconductWorkflowGraphNode` / `GraphNode` |
| outer post_process | Emit the outer completion audit event | merged domain output | success status | `OuterOutputNode` / `FunctionNode` |
| inner case ingest/classify | Parse+validate facts; reject identifiers; classify type and severity deterministically | `user_input` | normalized case and classification fields | `PreProcessNode` / `FunctionNode` |
| inner review/assemble | Draft review and intent sections, perform governed KB lookup, assemble report | classification and evidence fields | draft sections and `report_draft` | `MainNode` / `FunctionNode` |
| inner output validation | Re-scan PII and attach the mandatory disclaimer | `report_draft` | `output_pii_violations`, `formatted_output` | `PostProcessNode` / `FunctionNode` |
| finalize | Assemble final output from state | `formatted_output` | response | `FinalizeNode` (default) |

### Step Detail (7 proposal steps → 3 node dispatchers)

| Step | Node | Service module | Deterministic / LLM |
|------|------|----------------|---------------------|
| 1. CaseFactsIngest | pre_process | `case_facts_ingest_service.py` + `nl_case_facts_extraction_service.py` | JSON path: deterministic (JSON parse + regex identifier check). Natural-language path: LLM extraction (fallback only, JSON-first) |
| 2. MisconductTypeClassify | pre_process | `misconduct_classify_service.py` | Classification/severity: deterministic keyword rules. Rationale text only: LLM (optional) |
| 3. EvidenceReviewDraft | main | `evidence_review_draft_service.py` | LLM (optional) with deterministic template fallback |
| 4. IntentDeterminationDraft | main | `intent_determination_draft_service.py` | LLM (optional) with deterministic fallback; ruling-language output filter always active |
| 5. SanctionRangeLookup | main | `sanction_range_lookup_service.py` | Deterministic; KB loaded from file (`load_sanction_kb()`), fail-closed |
| 6. ReportAssemble | main | `report_assemble_service.py` | Deterministic string assembly |
| 7. OutputValidate | post_process | `output_validate_service.py` | Deterministic regex re-scan + disclaimer |

### LLM Provider

`PreProcessNode` (rationale text, natural-language case-facts extraction)
and `MainNode` (evidence review, intent analysis) call **Azure OpenAI**, via
`AzureOpenAIService.create_client(state)` (`src/services/azure_openai_service.py`)
— the same per-invocation pattern used across the fleet: no client is ever
built at module/constructor scope, only inside `execute()` via
`InvocationContext.from_state(state).secrets.require(...)`. `AzureLlmAdapter`
wraps `AzureOpenAIClient.complete(messages)` into this template's
`LlmClient.complete(prompt)` Protocol (`src/services/llm_types.py`) so the
three drafting services need no changes for the provider swap. Required
secrets: `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`,
`AZURE_OPENAI_DEPLOYMENT`. **Fail-open by design**: every drafting service
already falls back to a deterministic template when `llm=None`, so a
missing/invalid secret must never surface as an error — this agent must
always be able to produce a draft report, with or without a working LLM.

### Input Format: Plain-Text-First with LLM-Fallback Extraction

Callers (chiefly the Marketplace chat UI) supply a case description as a
single free-form sentence, e.g. *"A student submitted an essay in which
several paragraphs were copied verbatim from an online source, case
CASE-2026-0001, an undergraduate student."* Programmatic callers may still
send the legacy JSON-encoded string with the four required fields
(`misconduct_type`, `evidence_description`, `subject_role_category`,
`case_id`) directly in `input` — both paths are fully supported and behave
identically once case facts are extracted.

`PreProcessNode._extra_security_gate_input` tries the JSON path first
(`parse_case_facts`, no LLM call); only when `user_input` is not valid JSON
does it fall back to `NLCaseFactsExtractionService.extract()`
(`src/services/nl_case_facts_extraction_service.py`), which calls the LLM
once (with one corrective retry on malformed shape) to extract the same
four fields from the free-form text.

**PII ordering is critical and enforced in two layers**: since NL-extraction
sends raw user text to an LLM prompt, `contains_disallowed_identifier()` is
run on the **entire raw input** *before* either the JSON or NL path runs
(Layer 1) — a name/ID/department typed into free-form text must never leave
this process in an outbound LLM call. The pre-existing re-scan of the parsed
`evidence_description`/`subject_role_category` fields (Layer 2) still runs
afterward as defense-in-depth. See `tests/proof_of_boundary/test_pb06_nl_input_raw_pii_never_reaches_llm.py`
for the boundary test verifying Layer 1 blocks before any LLM client is
even constructed.

There is no fourth `AgentBaseGraph` slot to run extraction as a separate
node before `PreProcessNode` — the three-slot outer graph
(`pre_process`/`main`/`post_process`) is fixed, so extraction runs as a
preprocessing step inside `PreProcessNode`, still in the `pre_process`
dispatcher.

### Data Flow

```
Outer: START → initialize → outer input → GraphNode → outer output → finalize → END
Inner: START → case ingest/classify → review/assemble → output validation → END
```

No retry loop is expected in normal operation (no external I/O with transient
failure modes — no network/DB calls). `AgentStatus.ERROR` from `pre_process`
(malformed input / rejected identifier) routes directly to `finalize`,
skipping `main`/`post_process` — no report is drafted from rejected input.
`AgentStatus.ERROR` from `post_process` (PII re-scan hit) also routes to
`finalize` — a report that fails the final PII check is never released.

### S-2/S-3 Detection Scope (review finding H1)

The proposal (§3) states the S-2/S-3 requirement as "no subject name, student
ID, or department" anywhere in input or output. The custom pre-processing
check (`case_facts_ingest_service.contains_disallowed_identifier`) and the
output re-scan (`output_validate_service.find_subject_pii_violations`) enforce
this via **four concrete, testable patterns** — this is the complete,
precisely-defined policy, not an illustrative subset:

1. Cue-gated ASCII personal names — a name-introducing cue word
   (`name`/`student`/`professor`/`advisor`/`reported by`/`subject name`)
   immediately followed by a two-capitalized-word pattern.
2. 6–10 digit ID-shaped runs (student IDs).
3. Department/affiliation cue phrases — `department of`/`faculty of`/
   `school of`/`institute of`/`graduate school of`/`division of` followed by
   at least one more word.
4. Embedded Japanese-script (kanji/hiragana/katakana) runs of 2+ characters —
   **no cue word required**, because this template's own generated content
   (headings, disclaimer, fallback templates) is pure ASCII English, so a
   bare CJK-script run carries no false-positive risk against our own output
   (unlike the ASCII case, where a bare "two capitalized words" pattern
   false-positives on legitimate headings — `IMPLEMENTATION_LOG.md` A8).

**Honest limitation, stated precisely rather than as an absolute guarantee:**
this is a best-effort, defense-in-depth heuristic layer, not an exhaustive
free-text PII detector. It will not catch every conceivable phrasing of every
identifier in every language (e.g. an uncued ASCII name, or an identifier
embedded in a script this layer does not scan). Reliable universal free-text
PII detection is not feasible for a keyword/regex layer at any reasonable
false-positive rate. **Primary responsibility for submitting genuinely
anonymized case facts rests with the calling disciplinary-committee system**
(proposal §3) — this layer is a secondary, defense-in-depth check, not a
substitute for anonymization at the source. See
`docs/03_test_spec.md` "Detection Scope Statement" for the corresponding test
coverage and `src/services/case_facts_ingest_service.py` module docstring for
the implementation-level detail.

### State Definition

| Field | Type | Producer | Consumer | Purpose |
|-------|------|----------|----------|---------|
| `case_id` | `str` | pre_process (step 1) | main, post_process | Anonymized case reference code — the only per-case identifier carried in state |
| `misconduct_type_input` | `str` | pre_process (step 1) | pre_process (step 2), main | Caller-supplied raw misconduct description |
| `evidence_description` | `str` | pre_process (step 1) | pre_process (step 2), main, post_process (re-scan) | Free-text evidence; S-2-checked for special-category personal data (要配慮個人情報) at the gate |
| `subject_role_category` | `str` | pre_process (step 1) | main (report heading) | e.g. "graduate student", "faculty" — role only, never a name |
| `misconduct_classification` | `str` | pre_process (step 2) | main | One of `fabrication`/`falsification`/`plagiarism`/`other` — deterministic (ADR-005 note: plain `str`, no enum object stored) |
| `severity_tier` | `str` | pre_process (step 2) | main | One of `minor`/`moderate`/`severe` — deterministic |
| `classification_rationale` | `str` | pre_process (step 2) | main (report heading) | Narrative-only text; never overrides classification/severity |
| `evidence_review_section` | `str` | main (step 3) | main (step 6) | Drafted Markdown subsection |
| `intent_analysis_section` | `str` | main (step 4) | main (step 6) | Drafted Markdown subsection; always carries the mandatory advisory sentence |
| `sanction_range_text` | `str` | main (step 5) | main (step 6) | KB lookup result, always carries the institution-scope note |
| `report_draft` | `str` | main (step 6) | post_process (step 7) | Full assembled Markdown, pre-disclaimer |
| `output_pii_violations` | `str` (JSON-encoded `list[str]`, ADR-005) | post_process (step 7) | audit / test assertions | `"[]"` when clean; non-empty blocks release |

**State Constraints (mandatory):**
- Flat TypedDict only (primitives + JSON-serializable types) — confirmed, all fields above are `str`
- No JWT, API keys, credentials in State
- `InvocationContext` obtained via `InvocationContext.from_state(state)` inside `execute()` only — not stored in State (this template does not currently call any secret-gated dependency, but the pattern is reserved for the optional `llm` client)
- No Pydantic models, dataclass, arbitrary Python objects
- **No subject name, student ID, or department in any field** — proposal §3 S-5 requirement; enforced at ingest (custom S-2 check) and re-verified at output (S-3 belt-and-suspenders re-scan)

## Security Design (S-1 → S-4)

| Layer | Implementation | Risk mitigated (proposal §11) |
|-------|---------------|-------------------------------|
| S-1 | All 3 `FunctionNode` subclasses declare `required_trust_level = TrustLevel.VERIFIED_EXTERNAL` explicitly (no implicit `ANONYMOUS`) | Restricts invocation to authenticated disciplinary-committee callers |
| S-2 (custom) | `PreProcessNode._extra_security_gate_input()` parses case facts and rejects (sets `status=ERROR`, does not raise) when `evidence_description` or `subject_role_category` contains any of the 4 patterns in "S-2/S-3 Detection Scope" above (cue-gated ASCII name, digit-run ID, department/affiliation cue phrase, embedded Japanese-script run) — separate from, and in addition to, the platform S-1 HTML-strip/truncate normalizer (proposal §3) | Reduces the risk of special-category personal data (要配慮個人情報) or a subject identifier reaching downstream nodes, within the stated detection scope (best-effort, not exhaustive — see scope section) |
| S-3 | `PostProcessNode._extra_security_gate_output()` re-scans the assembled `formatted_output.report_markdown` for the same 4 patterns, independently of the step-7 execute()-level check (may raise to block entirely — defense in depth, a `SecurityGateOutputNode` pattern used elsewhere in the fleet) | Belt-and-suspenders: reduces risk of subject name/student ID/department/Japanese-script identifier in output even if step 1's check is ever bypassed, within the stated detection scope |
| S-4 | `emit_trace_event()` called at least once per node: `misconduct_classified` (pre_process), `llm_call` × 2 when an LLM is configured + `sanction_range_looked_up` incl. KB version/source (main), `output_pii_scan` (post_process) | Audit trail per invocation (proposal §3 S-4 requirement) |
| Risk #1 (LLM legal-quality risk, 🔴 High) | Classification/severity are deterministic (never LLM-decided); evidence-review draft, intent-analysis draft, **and classification rationale** (review finding M1) all discard any LLM output containing ruling-shaped language (`intent_determination_draft_service.contains_ruling_language`), falling back to a safe deterministic template; intent analysis additionally always appends the mandatory advisory sentence; `output_validate_service.attach_disclaimer()` prepends "AI DRAFT — NOT A FINAL DETERMINATION" to every released report | Mitigates legally-inappropriate LLM output — no code path can ship a "ruling" |
| Risk #2 (KB cannot absorb institution variation, 🟡 Medium) | review finding H2: the sanction-range table is no longer a hardcoded Python dict — it is a versioned, provenance-tagged JSON file (`src/services/kb/sanction_ranges.json`), loaded via `config.yaml`'s institution-configurable `kb_path` (`sanction_range_lookup_service.load_sanction_kb()`). **review finding H1 (round 2):** `config.yaml` is only auto-loaded by AgentRegistry in a full platform deployment — confirmed empirically that it is *not* auto-loaded when the agent class is constructed directly, which is what this template's own `src/api/server.py` entry point does. `server.py` now loads `config/config.yaml` itself (`_load_runtime_config()`) and passes it as the agent's `config=`, so `kb_path` (and `max_retry`/`memory_enabled`/`timeout_s`) actually take effect through this template's real entry point. Loading and lookup are both fail-closed (`SanctionKbError`): a missing/invalid file, or a classification/severity combination the KB does not define, fails rather than silently substituting a generic range. `institution_scope_note` (KB-file-supplied, not hardcoded) is appended to every sanction range returned. **review finding M1 (round 2):** the shipped KB is explicit sample data (`kb_version: "SAMPLE-2023.1"`, `provenance_verified: false`) — not a citation-backed production policy; `load_sanction_kb()` warns loudly when an active KB is unverified, and the STG Sign-off checklist requires explicit attestation that a verified KB is active before the ⑤→⑥ stage gate | An institution can genuinely swap in its own approved policy KB through the actual documented deployment mechanism; a misconfigured or incomplete policy fails loudly instead of shipping an uncontrolled generic recommendation; the shipped sample can never be silently mistaken for verified institution policy |
| Risk #3 (response time, 🟡 Medium) | No external network I/O (no live LLM call is required — deterministic fallback runs when `llm` is not configured; the sanction KB is a local file read once at agent construction, not a per-invocation remote call); token volume is bounded by fixed section templates | Predictable latency; no retry-inducing external dependency |

> **S-2/S-3 gate behaviour (ADR-017):** all 3 nodes are `FunctionNode` subclasses — the
> framework `@final` gate always runs automatically; extended only via
> `_extra_security_gate_input()` / `_extra_security_gate_output()`, never by overriding the
> `@final` methods themselves.

## Framework Utilization

### Shared Components Used
- [x] `InvocationContext` — reserved access point for the optional `llm` client's own secret
      handling; this template does not itself call `ctx.secrets.require()` (no required-secret
      dependency — every drafting step has a deterministic fallback)
- [ ] ConnectionPolicy — not used (no external service calls)
- [x] S-2: `_extra_security_gate_input()` on `PreProcessNode` — custom real-name/student-ID
      rejection (see Security Design table above)
- [x] S-3: `_extra_security_gate_output()` on `PostProcessNode` — independent PII re-scan,
      may raise to block release entirely
- [x] S-4: `emit_trace_event()` — domain events on all 3 nodes (see Security Design table)

### Composition Pattern

- **Pattern**: Cat 2 local subgraph composition via `GraphNode`
- **Composition target**: `MisconductDomainWorkflowGraph` (`BaseGraph`)
- **Error propagation strategy**: `propagate`; HITL propagation disabled because
  this workflow has no technical interrupt checkpoint

## Import Isolation Confirmation
- [x] Template does not import agenticstar-platform SDK (Level 0)
- [x] Import targets: `framework/` and `shared/` only (no `agents/base/` required)
- [x] `src/services/*.py` import neither `framework` nor `shared` — pure Python domain logic only

## Class Name Consistency

| Source | Value |
|--------|-------|
| `config/agent.yaml` `class` | `src.graph.graph.UniversityAcademicMisconductInvestigationReportDraftingAgent` |
| `src/graph/graph.py` class name | `UniversityAcademicMisconductInvestigationReportDraftingAgent` |
| `src/graph/graph.py` `name` property | `"UniversityAcademicMisconductInvestigationReportDraftingAgent"` |
| `src/api/server.py` import | `from src.graph.graph import UniversityAcademicMisconductInvestigationReportDraftingAgent` |

## Design Decision Record

| Decision | Option A | Option B | Chosen | Rationale |
|----------|----------|----------|--------|-----------|
| L1 base type | `AgentBaseGraph` | `AutonomousBaseGraph` | **A** | Fixed 7-step pipeline with deterministic termination — no autonomous think→act loop needed (Cat 2, not Cat 3) |
| Node-count reconciliation | Register 7 nodes directly | 7 pure-Python step helpers inside 3 real `FunctionNode`s | **B** | `AgentBaseGraph` only exposes 3 domain slots; registering a 4th+ node is not possible without bypassing the S-1/S-2/S-3 gate pipeline (`IMPLEMENTATION_LOG.md` A2) |
| MisconductTypeClassify authority | LLM decides classification + severity (as literally described in proposal §4 step table) | Deterministic keyword-rule engine decides; LLM only drafts a non-authoritative rationale sentence | **B** | Classification directly determines the sanction range (step 5) — a legally significant decision. `IMPLEMENTATION_LOG.md` A4: decisions with legal/financial/technical consequence must be deterministic; LLM is narrative-only. Also directly serves proposal §11 Risk #1 |
| IntentDeterminationDraft ruling risk | Trust LLM output as-is (fastest to implement) | Always append mandatory advisory sentence + discard any LLM output containing ruling-shaped language, falling back to a safe deterministic template | **B** | Highest-risk section per proposal §11 Risk #1 (🔴 High) — fail-safe over fail-open; mirrors the "escalation-only, never a final ruling" pattern used elsewhere in the fleet |
| Real-name/student-ID detection pattern | Bare "two capitalized words" regex | Cue-word-gated pattern (`name`/`student`/`professor`/`advisor`/`reported by`/`subject name`) + digit-run pattern, cue list deliberately excluding bare `subject` | **B** | `IMPLEMENTATION_LOG.md` A8: bare capitalization always false-positives on the template's own generated headings — confirmed directly during e2e testing of this template (bare `subject` cue matched this template's own "Subject Role Category" heading) |
| Detection scope: department + Japanese identifiers (review finding H1) | Leave detection at name/ID only, since proposal's literal step table doesn't enumerate every pattern | Add department/affiliation cue-phrase detection and bare (no-cue) Japanese-script detection; document the remaining residual limitation precisely rather than claim an absolute no-PII guarantee | **B** | Proposal §3 S-3 explicitly names "department" among prohibited output content; this is a Japanese-university MEXT context, so Japanese-script identifiers are squarely in scope. Reviewer-confirmed gap: "Department of Physics", "Faculty of Engineering", and a bare Japanese name all passed the original detector |
| Sanction-range policy source (review finding H2) | Hardcoded Python dict (`_SANCTION_KB` constant in `sanction_range_lookup_service.py`) | Versioned, provenance-tagged JSON file (`src/services/kb/sanction_ranges.json`), institution-overridable via `config.yaml`'s `kb_path`, fail-closed on load/lookup failure | **B** | Proposal's own Step Detail table literally specifies "KB (./kb/) lookup" — a hardcoded in-code matrix cannot be swapped per institution, contradicting proposal §11 Risk #2's mitigation ("institution-specific application is the responsibility of the academic integrity officer" only holds if the KB is genuinely swappable) |
| `config.yaml` loading for the standalone entry point (review finding H1, round 2) | Assume the framework auto-populates `self.config` from `config.yaml` at construction, per `config-and-secrets.md`'s general statement | `src/api/server.py` explicitly loads `config/config.yaml` (`_load_runtime_config()`) and passes it as `Agent(config=...)` | **B** | Empirically disproved the assumption: `Agent()` with no `config=` argument leaves `self.config == {}` after `compile()` — `config-and-secrets.md`'s "loaded by the framework at agent construction time" describes AgentRegistry's production deployment path, not direct instantiation. This template's own entry point bypasses AgentRegistry, so it must load the file itself or the documented `kb_path`/`max_retry`/etc. overrides are silently inert |
| Shipped sanction-range KB provenance (review finding M1, round 2) | Present the shipped KB as authoritative MEXT 2023 data (as originally written) | Explicitly relabel as `SAMPLE-2023.1` / `provenance_verified: false`, add a load-time warning, and gate final go-live attestation at the STG Sign-off checklist | **B** | The shipped ranges are aligned with general knowledge of the MEXT 2023 guideline but were not extracted with verified page/section citations from the primary document — presenting them as authoritative would be a false assurance for legally consequential sanction recommendations. Honest labeling + a load-time warning + an explicit go-live attestation gate is safer than fabricating citations or silently shipping unverified data as fact |
| PII re-scan location (step 7) | Only in `execute()` | Both in `execute()` (blocks release, sets `output_pii_violations`) and independently in `_extra_security_gate_output()` (may raise) | **B** | Defense in depth — mirrors the `SecurityGateOutputNode` pattern used elsewhere in the fleet, independent of the step-1 ingest check |
| Composition pattern | Three domain functions directly in the outer backbone | `GraphNode` wrapping an inner workflow | **B** | The latest Cat 2 scaffold requires domain complexity to live behind the outer graph's `main` boundary; the inner graph preserves the approved deterministic ordering and security gates |
