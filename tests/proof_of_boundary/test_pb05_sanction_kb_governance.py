# PB-05 (domain): Sanction-range KB governance boundary (review finding H2/M2).
#
# Verifies the approved workflow's config surface — kb_path — actually
# governs which sanction-policy KB the compiled agent uses, and that a
# misconfigured kb_path fails agent.compile() loudly (fail-closed) rather
# than falling back to a silent default.

import json

import pytest

from src.graph.graph import UniversityAcademicMisconductInvestigationReportDraftingAgent as Agent
from src.services.sanction_range_lookup_service import SanctionKbError, is_sample_kb


class TestSanctionKbGovernance:
    def test_default_kb_path_compiles_and_carries_provenance(self):
        agent = Agent(config={})
        agent.compile()
        sanction_kb = agent._nodes["main"]._sanction_kb
        assert sanction_kb["kb_version"]
        assert sanction_kb["source"]
        assert "ranges" in sanction_kb

    def test_default_shipped_kb_is_flagged_as_unverified_sample(self):
        # review finding M1: the shipped reference KB must never be silently
        # mistaken for a citation-backed production policy.
        agent = Agent(config={})
        with pytest.warns(UserWarning, match="provenance_verified=false"):
            agent.compile()
        assert is_sample_kb(agent._nodes["main"]._sanction_kb) is True

    def test_missing_kb_path_fails_agent_compile(self):
        agent = Agent(config={"kb_path": "kb/does_not_exist.json"})
        with pytest.raises(SanctionKbError, match="not found"):
            agent.compile()

    def test_invalid_kb_path_content_fails_agent_compile(self, tmp_path):
        bad_kb = tmp_path / "bad_kb.json"
        bad_kb.write_text(json.dumps({"kb_version": "1.0"}), encoding="utf-8")  # missing 'source', 'ranges'
        agent = Agent(config={"kb_path": str(bad_kb)})
        with pytest.raises(SanctionKbError, match="missing required key"):
            agent.compile()

    def test_custom_kb_path_overrides_default(self, tmp_path):
        custom_kb = tmp_path / "custom_kb.json"
        custom_kb.write_text(
            json.dumps(
                {
                    "kb_version": "institution-2026.1",
                    "source": "Test Institution Policy",
                    "provenance_verified": True,
                    "institution_scope_note": "Institution-specific note.",
                    "ranges": {"plagiarism:moderate": "Custom institution sanction."},
                }
            ),
            encoding="utf-8",
        )
        agent = Agent(config={"kb_path": str(custom_kb)})
        agent.compile()
        sanction_kb = agent._nodes["main"]._sanction_kb
        assert sanction_kb["kb_version"] == "institution-2026.1"
        assert sanction_kb["source"] == "Test Institution Policy"


class TestDeploymentConfigLoadingPath:
    """review finding H1 (second round) + M2: PB-05 above only proved constructor
    injection (Agent(config={"kb_path": ...})) — it did not prove the
    *documented, operator-facing* configuration mechanism (editing
    config/config.yaml and having src/api/server.py pick it up) actually
    works. These tests exercise src.api.server._load_runtime_config() —
    the exact function the real entry point calls at import/startup time —
    against real temp config.yaml files, and against the real repo config.yaml."""

    def test_load_runtime_config_reads_real_repo_config_yaml(self):
        # Uses the actual config/config.yaml shipped in this repo (no kb_path
        # override committed there — see it fall back to the code-level
        # default in test_default_kb_path_compiles_and_carries_provenance).
        from src.api.server import _load_runtime_config

        cfg = _load_runtime_config()
        assert cfg["max_retry"] == 3
        assert cfg["memory_enabled"] is False

    def test_operator_edited_config_yaml_kb_path_reaches_compiled_agent(self, tmp_path):
        # Simulates an operator following docs/07_operation_guide.md: author
        # a custom KB file, then set kb_path in config.yaml (not via Python
        # constructor kwargs) — the exact documented deployment step.
        from src.api.server import _load_runtime_config

        custom_kb = tmp_path / "institution_kb.json"
        custom_kb.write_text(
            json.dumps(
                {
                    "kb_version": "institution-2026.2",
                    "source": "Operator-edited config.yaml Test",
                    "provenance_verified": True,
                    "institution_scope_note": "Note.",
                    "ranges": {"plagiarism:moderate": "Institution sanction via config.yaml."},
                }
            ),
            encoding="utf-8",
        )
        operator_config_yaml = tmp_path / "config.yaml"
        operator_config_yaml.write_text(
            f"max_retry: 3\nmemory_enabled: false\ntimeout_s: 30\nkb_path: {custom_kb}\n",
            encoding="utf-8",
        )

        loaded = _load_runtime_config(operator_config_yaml)
        agent = Agent(config=loaded)
        agent.compile()
        sanction_kb = agent._nodes["main"]._sanction_kb
        assert sanction_kb["kb_version"] == "institution-2026.2"

    def test_operator_edited_config_yaml_with_malformed_kb_path_blocks_compile(self, tmp_path):
        # The documented deployment path must fail closed too, not just the
        # constructor-injection path.
        from src.api.server import _load_runtime_config

        operator_config_yaml = tmp_path / "config.yaml"
        operator_config_yaml.write_text(
            "max_retry: 3\nmemory_enabled: false\ntimeout_s: 30\nkb_path: does/not/exist.json\n",
            encoding="utf-8",
        )
        loaded = _load_runtime_config(operator_config_yaml)
        agent = Agent(config=loaded)
        with pytest.raises(SanctionKbError, match="not found"):
            agent.compile()

    def test_real_server_module_constructs_successfully(self):
        # Smoke test of the actual entry point: importing src.api.server runs
        # its module-level `agent = Agent(config=_load_runtime_config());
        # agent.compile()` against the real repo config/config.yaml and
        # src/services/kb/sanction_ranges.json — proving the full documented
        # path works end-to-end, not just its individual pieces in isolation.
        import src.api.server as server_module

        assert server_module.agent._nodes["main"]._sanction_kb["kb_version"]
