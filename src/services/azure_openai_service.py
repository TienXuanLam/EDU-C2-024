"""Azure OpenAI client construction for EDU-C2-024."""

from typing import Any

from framework.schemas.invocation_context import InvocationContext
from shared.services.llm.azure_openai_client import AzureOpenAIClient

_PASSTHROUGH_KEYS = ("temperature", "max_tokens")


class AzureOpenAIService:
    """Build the AgentCore Azure OpenAI client from invocation-scoped secrets."""

    def __init__(self, llm_config: dict[str, Any] | None = None) -> None:
        self._llm_config = dict(llm_config or {})

    def create_client(self, state: dict[str, Any]) -> AzureOpenAIClient:
        """Create a client without reading secrets from process environment variables."""
        ctx = InvocationContext.from_state(state)
        config: dict[str, Any] = {key: value for key, value in self._llm_config.items() if key in _PASSTHROUGH_KEYS}
        config["api_key"] = ctx.secrets.require("AZURE_OPENAI_API_KEY")
        config["azure_endpoint"] = ctx.secrets.require("AZURE_OPENAI_ENDPOINT")
        config["azure_deployment"] = ctx.secrets.require("AZURE_OPENAI_DEPLOYMENT")
        return AzureOpenAIClient(config)


class StgDraftingLLM:
    """Deterministic Stage 5 stand-in for narrative-drafting LLM calls
    (classification rationale, evidence review, intent analysis) -- distinct
    from NLCaseFactsExtractionService's own STG stub, which must return
    structured case-facts JSON instead of prose. Never selected implicitly
    in production."""

    def complete(self, prompt: str) -> Any:
        return "Stage 5 deterministic drafting placeholder text."


class AzureLlmAdapter:
    """Adapts AzureOpenAIClient.complete(messages) to this template's
    LlmClient.complete(prompt) Protocol (src/services/llm_types.py) so the
    existing drafting services (evidence_review_draft_service,
    intent_determination_draft_service, misconduct_classify_service) need no
    changes -- they already unwrap a {"content": str} dict via
    completion_text().
    """

    def __init__(self, client: AzureOpenAIClient) -> None:
        self._client = client

    def complete(self, prompt: str) -> Any:
        return self._client.complete([{"role": "user", "content": prompt}])
