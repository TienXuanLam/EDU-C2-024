# EDU-C2-024 — Unit Tests: output_validate_service (step 7 — S-3 belt-and-suspenders)

from src.services.output_validate_service import (
    MANDATORY_DISCLAIMER,
    attach_disclaimer,
    find_subject_pii_violations,
)


class TestFindSubjectPiiViolations:
    def test_clean_report_has_no_violations(self):
        report = (
            "# Report — Case CASE-2026-0001\n\n"
            "- **Case ID:** CASE-2026-0001\n"
            "- **Subject Role Category:** graduate student\n"
            "## Evidence Review\n\nSample findings text.\n"
        )
        assert find_subject_pii_violations(report) == []

    def test_leaked_name_detected(self):
        report = "Reported by Jane Doe, the essay copies text verbatim."
        violations = find_subject_pii_violations(report)
        assert any("name" in v for v in violations)

    def test_leaked_student_id_detected(self):
        report = "Student ID 20239876 submitted the falsified data."
        violations = find_subject_pii_violations(report)
        assert any("student ID" in v for v in violations)

    def test_own_heading_not_false_positive(self):
        # Regression test for the false-positive found during e2e testing
        # (IMPLEMENTATION_LOG.md A8) — the template's own "Subject Role
        # Category" heading must never be flagged.
        report = "- **Subject Role Category:** undergraduate student\n"
        assert find_subject_pii_violations(report) == []

    # --- review finding H1 regression tests ---

    def test_leaked_department_detected(self):
        report = "The case originated in the Department of Physics."
        violations = find_subject_pii_violations(report)
        assert any("department" in v for v in violations)

    def test_leaked_japanese_name_detected(self):
        report = "Case notes mention 山田太郎 as a witness."
        violations = find_subject_pii_violations(report)
        assert any("Japanese" in v for v in violations)


class TestAttachDisclaimer:
    def test_disclaimer_prepended(self):
        result = attach_disclaimer("# Report body")
        assert result.startswith(MANDATORY_DISCLAIMER)
        assert "# Report body" in result

    def test_disclaimer_mentions_review_requirement(self):
        assert "legal counsel" in MANDATORY_DISCLAIMER.lower()
        assert "not a final determination" in MANDATORY_DISCLAIMER.lower()
