"""Standalone HTTP adapter for EDU-C2-024."""

from __future__ import annotations

import os
import secrets
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from langgraph.checkpoint.memory import MemorySaver
from pydantic import BaseModel, Field

from framework.schemas.invocation_context import InvocationContext
from framework.schemas.trust_level import TrustLevel
from framework.secrets.context import bound_secrets
from framework.utils.config_loader import load_config
from shared.secrets import factory as secrets_factory
from src.graph.graph import UniversityAcademicMisconductInvestigationReportDraftingAgent

app = FastAPI(title="Agent")

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "config.yaml"


def _load_runtime_config(config_path: Path | None = None) -> dict[str, Any]:
    """Load standalone runtime configuration using the registry convention."""
    path = config_path or _CONFIG_PATH
    return dict(load_config(str(path))) if path.exists() else {}


_config = _load_runtime_config()
_secrets_provider = secrets_factory(
    namespace="EDU",
    agent_name="UniversityAcademicMisconductInvestigationReportDraftingAgent",
)
# No config["llm"] seam filled here: PreProcessNode/MainNode build their own
# secret-bound AzureOpenAIClient per invocation via _build_llm(state) -- see
# their docstrings. config stays the plain tuning dict (temperature/max_tokens).
# The server boots without AZURE_OPENAI_* secrets; only real LLM-drafted
# sections fail open to deterministic templates until they're provisioned.

agent = UniversityAcademicMisconductInvestigationReportDraftingAgent(config=_config)
_hitl_enabled = bool(agent.config.get("hitl", {}).get("enabled", False))
_needs_checkpointer = bool(agent.config.get("memory_enabled")) or _hitl_enabled
agent.compile(checkpointer=MemorySaver() if _needs_checkpointer else None)
agent.provision_secrets(_secrets_provider)


class InvokeRequest(BaseModel):
    input: str = Field(default="", max_length=4096)
    session_id: str = Field(default="", max_length=256)
    input_context: dict[str, Any] = Field(default_factory=dict)


def _bearer_matches(supplied: str, expected: str) -> bool:
    return secrets.compare_digest(supplied.encode(), f"Bearer {expected}".encode())


def _resolve_standalone_trust(
    current: TrustLevel,
    authorization: str,
    invoke_auth_token: str | None,
    internal_runner_token: str | None,
) -> TrustLevel:
    """Map distinct external and runner credentials without privilege elevation."""
    if current is not TrustLevel.ANONYMOUS:
        return current
    if internal_runner_token and _bearer_matches(authorization, internal_runner_token):
        return TrustLevel.INTERNAL
    if invoke_auth_token and _bearer_matches(authorization, invoke_auth_token):
        return TrustLevel.VERIFIED_EXTERNAL
    if internal_runner_token or invoke_auth_token:
        raise HTTPException(status_code=401, detail="Token is invalid or expired.")
    return TrustLevel.ANONYMOUS


@app.post("/invoke")
async def invoke(req: InvokeRequest, request: Request) -> dict[str, Any]:
    trust = _resolve_standalone_trust(
        getattr(request.state, "trust_level", TrustLevel.ANONYMOUS),
        request.headers.get("authorization", ""),
        os.environ.get("INVOKE_AUTH_TOKEN"),
        os.environ.get("STG_INTERNAL_RUNNER_TOKEN"),
    )
    with bound_secrets(agent._secrets_provider):
        ctx = InvocationContext(
            session_id=req.session_id or str(uuid4()),
            caller_trust_level=trust,
            caller_id=getattr(request.state, "caller_id", ""),
        )
        return cast(dict[str, Any], agent.invoke(req.input, ctx=ctx, input_context=dict(req.input_context)))


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "agent": "UniversityAcademicMisconductInvestigationReportDraftingAgent",
    }
