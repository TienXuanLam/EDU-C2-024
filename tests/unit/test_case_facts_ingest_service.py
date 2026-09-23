# EDU-C2-024 — Unit Tests: case_facts_ingest_service (step 1)

import json

from src.services.case_facts_ingest_service import (
    PLATFORM_MASK_TOKEN,
    contains_disallowed_identifier,
    parse_case_facts,
)


class TestParseCaseFacts:
    def test_valid_payload(self):
        raw = json.dumps(
            {
                "misconduct_type": "plagiarism in submitted essay",
                "evidence_description": "text copied without citation",
                "subject_role_category": "undergraduate student",
                "case_id": "CASE-2026-0001",
            }
        )
        case_facts, error = parse_case_facts(raw)
        assert error is None
        assert case_facts["case_id"] == "CASE-2026-0001"
        assert case_facts["misconduct_type"] == "plagiarism in submitted essay"

    def test_empty_input(self):
        case_facts, error = parse_case_facts("")
        assert case_facts is None
        assert "empty" in error

    def test_invalid_json(self):
        case_facts, error = parse_case_facts("not-json")
        assert case_facts is None
        assert "not valid JSON" in error

    def test_json_not_object(self):
        case_facts, error = parse_case_facts(json.dumps(["a", "b"]))
        assert case_facts is None
        assert "must be an object" in error

    def test_missing_required_field(self):
        raw = json.dumps({"misconduct_type": "x", "evidence_description": "y", "subject_role_category": "z"})
        case_facts, error = parse_case_facts(raw)
        assert case_facts is None
        assert "case_id" in error


class TestContainsDisallowedIdentifier:
    def test_clean_text_passes(self):
        assert contains_disallowed_identifier("The submitted dataset does not match the raw logs.") is False

    def test_cue_gated_name_detected(self):
        assert contains_disallowed_identifier("Reported by John Smith during the review.") is True

    def test_bare_capitalization_not_flagged(self):
        # A8 lesson: bare "two capitalized words" must NOT be treated as a name
        # without a cue word — this is a legitimate heading-like phrase.
        assert contains_disallowed_identifier("Work Order was submitted late.") is False

    def test_student_id_digit_run_detected(self):
        assert contains_disallowed_identifier("Student ID 20231234 submitted the file.") is True

    def test_short_digit_run_not_flagged(self):
        assert contains_disallowed_identifier("Filed in 2026, revision 04.") is False

    def test_empty_text(self):
        assert contains_disallowed_identifier("") is False

    def test_platform_mask_token_treated_as_rejection_signal(self):
        # Regression test (found by running against the real
        # agenticstar-agentcore framework, not just the local test stub):
        # FunctionNode's default S-2 scan masks a detected real name to the
        # literal token "[MASKED]" *before* this hook runs, so the original
        # name pattern is gone by the time we see it. Treating the mask
        # token itself as a rejection signal ensures the case is still
        # rejected (per proposal §3), not silently processed with the name
        # replaced.
        assert contains_disallowed_identifier(f"Reported by {PLATFORM_MASK_TOKEN}, text copied.") is True

    # --- review finding H1 regression tests: department/affiliation + Japanese ---
    # identifiers, per proposal §3 S-3 ("no subject name, student ID, or
    # department"). These are the exact probes cited in the review finding.

    def test_department_of_phrase_detected(self):
        assert contains_disallowed_identifier("Department of Physics reported the issue.") is True

    def test_faculty_of_phrase_detected(self):
        assert contains_disallowed_identifier("Faculty of Engineering student submitted the essay.") is True

    def test_school_of_phrase_detected(self):
        assert contains_disallowed_identifier("A School of Medicine case.") is True

    def test_department_phrase_with_nothing_following_not_flagged(self):
        # Cue phrase with nothing after it (end of string) should not match —
        # the pattern requires an actual department name to follow, so this
        # exercises the "at least one more word" boundary explicitly.
        assert contains_disallowed_identifier("The report mentions a department of") is False

    def test_bare_japanese_name_detected_without_cue(self):
        # No cue word needed for Japanese script — see module docstring:
        # this template's own generated content is pure ASCII English, so a
        # bare CJK run carries no false-positive risk against our own output.
        assert contains_disallowed_identifier("Case involves 山田太郎 and copied text.") is True

    def test_japanese_common_word_also_flagged_by_design(self):
        # Documented trade-off (module docstring "Detection scope and honest
        # limitation"): any embedded CJK-script run is treated as suspicious,
        # since evidence_description is expected to be English free text.
        # This may over-reject legitimate quoted Japanese terminology — an
        # accepted false-positive bias in favor of never under-rejecting a
        # name (module docstring).
        assert contains_disallowed_identifier("学生") is True
