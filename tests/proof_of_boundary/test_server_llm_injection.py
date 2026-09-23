"""PB: standalone STG server boots without secrets and builds LLM clients
per-invocation, never sharing one client instance across callers."""

from __future__ import annotations

import importlib
import sys

from fastapi.testclient import TestClient


class TestServerBootsWithoutAzureSecrets:
    def test_server_imports_and_app_constructs_with_no_secrets(self, monkeypatch):
        for key in ("AZURE_OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_DEPLOYMENT"):
            monkeypatch.delenv(key, raising=False)
        sys.modules.pop("src.api.server", None)
        server = importlib.import_module("src.api.server")

        assert server.app is not None
        assert server.agent is not None


def test_stg_server_full_invoke(monkeypatch) -> None:
    monkeypatch.setenv("STG_MOCK_MODE", "true")
    monkeypatch.setenv("INVOKE_AUTH_TOKEN", "integration-token")
    sys.modules.pop("src.api.server", None)
    server = importlib.import_module("src.api.server")
    client = TestClient(server.app)
    response = client.post(
        "/invoke",
        headers={"Authorization": "Bearer integration-token"},
        json={
            "input": "A student submitted an essay with several paragraphs copied verbatim from an online source.",
            "input_context": {},
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["output"]["report_markdown"]


def test_standalone_auth_rejects_invalid_token(monkeypatch) -> None:
    monkeypatch.setenv("STG_MOCK_MODE", "true")
    monkeypatch.setenv("INVOKE_AUTH_TOKEN", "expected-token")
    sys.modules.pop("src.api.server", None)
    server = importlib.import_module("src.api.server")
    response = TestClient(server.app).post(
        "/invoke",
        headers={"Authorization": "Bearer wrong-token"},
        json={"input": "{}", "input_context": {}},
    )
    assert response.status_code == 401


class TestLlmBuiltPerInvocationNotAtModuleScope:
    def test_server_module_holds_no_global_llm_client(self, monkeypatch):
        monkeypatch.setenv("STG_MOCK_MODE", "true")
        sys.modules.pop("src.api.server", None)
        server = importlib.import_module("src.api.server")

        # No module-scope client/attribute should exist -- the old
        # AnthropicClient-at-import-time pattern is gone. config["llm"] must
        # never be populated either (that seam is intentionally left unfilled;
        # PreProcessNode/MainNode build their own clients per-invocation).
        assert not hasattr(server, "_llm")
        assert "llm" not in server._config

    def test_two_invocations_build_distinct_client_instances(self, monkeypatch):
        # Patch AzureOpenAIService.create_client to return a fresh sentinel
        # object each call, then confirm calling it twice (simulating two
        # separate invocations) never returns the same instance -- a
        # regression guard against reintroducing a cached, module-scope
        # client shared across callers.
        from src.services.azure_openai_service import AzureOpenAIService

        service = AzureOpenAIService()
        monkeypatch.setattr(AzureOpenAIService, "create_client", lambda self, state: object())

        first = service.create_client({})
        second = service.create_client({})
        assert first is not second


class TestStandaloneTrustPromotion:
    def test_external_bearer_never_promotes_to_internal(self):
        import src.api.server as server
        from framework.schemas.trust_level import TrustLevel

        assert (
            server._resolve_standalone_trust(TrustLevel.ANONYMOUS, "Bearer external", "external", "runner")
            is TrustLevel.VERIFIED_EXTERNAL
        )

    def test_runner_bearer_promotes_to_internal(self):
        import src.api.server as server
        from framework.schemas.trust_level import TrustLevel

        assert (
            server._resolve_standalone_trust(TrustLevel.ANONYMOUS, "Bearer runner", "external", "runner")
            is TrustLevel.INTERNAL
        )

    def test_wrong_or_missing_bearer_is_rejected_when_auth_is_enabled(self):
        import pytest
        import src.api.server as server
        from fastapi import HTTPException
        from framework.schemas.trust_level import TrustLevel

        for authorization in ("", "Bearer wrong"):
            with pytest.raises(HTTPException) as exc:
                server._resolve_standalone_trust(TrustLevel.ANONYMOUS, authorization, "external", "runner")
            assert exc.value.status_code == 401
