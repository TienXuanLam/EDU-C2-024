# EDU-C2-024 — Unit Tests: report_assemble_service (step 6)

from src.services.report_assemble_service import assemble_report


class TestAssembleReport:
    def test_report_contains_all_mandatory_sections(self):
        report = assemble_report(
            case_id="CASE-2026-0001",
            misconduct_type_input="plagiarism in submitted essay",
            subject_role_category="undergraduate student",
            classification="plagiarism",
            severity="minor",
            classification_rationale="Matched plagiarism keywords.",
            evidence_review_section="## Evidence Review\n\nSample text.",
            intent_analysis_section="## Intent Analysis\n\nSample text.",
            sanction_range_text="Written warning.",
        )
        assert "Allegation Overview" in report
        assert "Investigation Procedure" in report
        assert "Evidence Review" in report
        assert "Intent Analysis" in report
        assert "Sanction Recommendation" in report
        assert "CASE-2026-0001" in report

    def test_report_does_not_hardcode_a_subject_name_field(self):
        report = assemble_report(
            case_id="CASE-2026-0002",
            misconduct_type_input="fabrication",
            subject_role_category="graduate student",
            classification="fabrication",
            severity="severe",
            classification_rationale="r",
            evidence_review_section="e",
            intent_analysis_section="i",
            sanction_range_text="s",
        )
        assert "student name" not in report.lower()
        assert "subject:" not in report.lower()
