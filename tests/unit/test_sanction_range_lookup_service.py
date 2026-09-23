# EDU-C2-024 — Unit Tests: sanction_range_lookup_service (step 5)
#
# Rewritten for review finding H2: the sanction-range table is no longer
# a hardcoded Python dict — it is loaded from an institution-configurable,
# versioned JSON KB file, fail-closed on any problem.

import json

import pytest

from src.services.sanction_range_lookup_service import (
    REQUIRED_KB_KEYS,
    SanctionKbError,
    is_sample_kb,
    load_sanction_kb,
    lookup_sanction_range,
)

_VALID_KB = {
    "kb_version": "test-1.0",
    "source": "Unit Test Fixture",
    "provenance_verified": True,
    "institution_scope_note": "TEST SCOPE NOTE.",
    "ranges": {
        "plagiarism:minor": "Written warning.",
        "fabrication:severe": "Expulsion.",
    },
}


def _write_kb(tmp_path, data) -> str:
    path = tmp_path / "kb.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


class TestLoadSanctionKb:
    def test_valid_kb_loads(self, tmp_path):
        kb_path = _write_kb(tmp_path, _VALID_KB)
        kb = load_sanction_kb(kb_path)
        assert kb["kb_version"] == "test-1.0"
        assert kb["source"] == "Unit Test Fixture"

    def test_missing_file_fails_closed(self, tmp_path):
        with pytest.raises(SanctionKbError, match="not found"):
            load_sanction_kb(str(tmp_path / "does_not_exist.json"))

    def test_invalid_json_fails_closed(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("{not valid json", encoding="utf-8")
        with pytest.raises(SanctionKbError, match="not valid JSON"):
            load_sanction_kb(str(path))

    def test_missing_required_key_fails_closed(self, tmp_path):
        incomplete = {"kb_version": "1.0", "ranges": {"a:b": "c"}, "provenance_verified": True}  # missing "source"
        kb_path = _write_kb(tmp_path, incomplete)
        with pytest.raises(SanctionKbError, match="missing required key"):
            load_sanction_kb(kb_path)

    def test_empty_ranges_fails_closed(self, tmp_path):
        empty_ranges = {"kb_version": "1.0", "source": "x", "provenance_verified": True, "ranges": {}}
        kb_path = _write_kb(tmp_path, empty_ranges)
        with pytest.raises(SanctionKbError, match="empty or invalid"):
            load_sanction_kb(kb_path)

    def test_non_object_json_fails_closed(self, tmp_path):
        kb_path = _write_kb(tmp_path, ["not", "an", "object"])
        with pytest.raises(SanctionKbError, match="must be a JSON object"):
            load_sanction_kb(kb_path)

    def test_required_kb_keys_documented(self):
        assert set(REQUIRED_KB_KEYS) == {"kb_version", "source", "ranges", "provenance_verified"}

    def test_missing_provenance_verified_fails_closed(self, tmp_path):
        # provenance_verified is required — no silent omission (review finding M1).
        no_provenance = {"kb_version": "1.0", "source": "x", "ranges": {"a:b": "c"}}
        kb_path = _write_kb(tmp_path, no_provenance)
        with pytest.raises(SanctionKbError, match="provenance_verified"):
            load_sanction_kb(kb_path)

    def test_unverified_kb_warns_but_still_loads(self, tmp_path):
        # Fail-safe, not fail-open: STG/dev legitimately runs against an
        # unverified sample KB, so this warns rather than raising. Production
        # go/no-go is gated by the STG Sign-off Record checklist instead.
        unverified = dict(_VALID_KB, provenance_verified=False)
        kb_path = _write_kb(tmp_path, unverified)
        with pytest.warns(UserWarning, match="provenance_verified=false"):
            kb = load_sanction_kb(kb_path)
        assert kb["ranges"]

    def test_verified_kb_does_not_warn(self, tmp_path, recwarn):
        kb_path = _write_kb(tmp_path, _VALID_KB)
        load_sanction_kb(kb_path)
        assert len(recwarn) == 0


class TestIsSampleKb:
    def test_unverified_kb_is_sample(self):
        assert is_sample_kb(dict(_VALID_KB, provenance_verified=False)) is True

    def test_verified_kb_is_not_sample(self):
        assert is_sample_kb(_VALID_KB) is False

    def test_missing_field_treated_as_sample(self):
        assert is_sample_kb({"ranges": {}}) is True


class TestLookupSanctionRange:
    def test_known_combination(self):
        text = lookup_sanction_range(_VALID_KB, "fabrication", "severe")
        assert "Expulsion" in text
        assert "TEST SCOPE NOTE" in text

    def test_unknown_combination_fails_closed(self):
        with pytest.raises(SanctionKbError, match="no entry"):
            lookup_sanction_range(_VALID_KB, "not-a-real-type", "not-a-real-severity")

    def test_no_llm_parameter_in_signature(self):
        import inspect

        assert "llm" not in inspect.signature(lookup_sanction_range).parameters

    def test_deterministic(self):
        args = (_VALID_KB, "plagiarism", "minor")
        assert lookup_sanction_range(*args) == lookup_sanction_range(*args)


class TestShippedReferenceKb:
    """Confirms the reference KB shipped with the template
    (src/services/kb/sanction_ranges.json) is itself valid and covers all
    classification x severity combinations the deterministic classifier can
    produce."""

    def test_shipped_kb_is_valid_and_complete(self):
        import pathlib

        kb_path = pathlib.Path(__file__).parents[2] / "src" / "services" / "kb" / "sanction_ranges.json"
        with pytest.warns(UserWarning, match="provenance_verified=false"):
            kb = load_sanction_kb(str(kb_path))
        classifications = ("fabrication", "falsification", "plagiarism", "other")
        severities = ("minor", "moderate", "severe")
        for classification in classifications:
            for severity in severities:
                # Must not raise for any combination classify_misconduct() can produce.
                text = lookup_sanction_range(kb, classification, severity)
                assert text
                assert kb["institution_scope_note"] in text

    def test_shipped_kb_is_flagged_as_sample_pending_verification(self):
        # review finding M1: the shipped reference KB is sample data, not a
        # citation-backed production policy — must be explicitly flagged,
        # not silently treated as authoritative.
        import pathlib

        kb_path = pathlib.Path(__file__).parents[2] / "src" / "services" / "kb" / "sanction_ranges.json"
        with pytest.warns(UserWarning):
            kb = load_sanction_kb(str(kb_path))
        assert is_sample_kb(kb) is True
        assert "SAMPLE" in kb["kb_version"]
