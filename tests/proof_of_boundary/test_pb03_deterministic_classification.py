# PB-03 (domain): Deterministic-vs-LLM authority boundary
# (IMPLEMENTATION_LOG.md A4 / docs/02_design.md Design Decision Record).
#
# Legally-significant decisions (misconduct classification, severity tier,
# sanction range) must never accept an `llm` parameter — confirmed here by
# inspecting the function signatures directly, not just by behavioral
# testing (a future edit could add an `llm` param without changing observed
# behavior in a small test matrix).

import inspect

from src.services.misconduct_classify_service import classify_misconduct
from src.services.sanction_range_lookup_service import lookup_sanction_range


class TestDeterministicAuthorityBoundary:
    def test_classify_misconduct_has_no_llm_parameter(self):
        assert "llm" not in inspect.signature(classify_misconduct).parameters

    def test_lookup_sanction_range_has_no_llm_parameter(self):
        assert "llm" not in inspect.signature(lookup_sanction_range).parameters

    def test_classify_misconduct_is_pure_deterministic(self):
        # Same input -> same output, always (no hidden randomness/LLM call).
        args = ("fabrication of results", "invented data across three trials")
        assert classify_misconduct(*args) == classify_misconduct(*args)

    def test_lookup_sanction_range_is_pure_deterministic(self):
        kb = {
            "kb_version": "test-1.0",
            "source": "PB-03 Test Fixture",
            "provenance_verified": True,
            "institution_scope_note": "TEST.",
            "ranges": {"plagiarism:severe": "Expulsion."},
        }
        assert lookup_sanction_range(kb, "plagiarism", "severe") == lookup_sanction_range(kb, "plagiarism", "severe")
