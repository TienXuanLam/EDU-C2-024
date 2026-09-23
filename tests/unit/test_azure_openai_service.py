"""Unit tests for AzureOpenAIService and AzureLlmAdapter."""

from __future__ import annotations

import pytest

from src.services.azure_openai_service import AzureLlmAdapter, AzureOpenAIService


def test_create_client_raises_when_secret_missing() -> None:
    # No InvocationContext-shaped state fields present -> from_state() or
    # secrets.require() must fail closed with an exception, never silently
    # construct a client with a missing credential.
    service = AzureOpenAIService()
    with pytest.raises(Exception):  # noqa: B017 — exact exception type is framework-internal
        service.create_client({})


class _RecordingAzureClient:
    def __init__(self) -> None:
        self.received_messages: list[dict[str, str]] | None = None

    def complete(self, messages: list[dict[str, str]]) -> dict[str, str]:
        self.received_messages = messages
        return {"content": "adapted response"}


def test_azure_llm_adapter_wraps_prompt_as_messages_list() -> None:
    client = _RecordingAzureClient()
    adapter = AzureLlmAdapter(client)
    response = adapter.complete("draft this section")
    assert client.received_messages == [{"role": "user", "content": "draft this section"}]
    assert response == {"content": "adapted response"}


def test_azure_llm_adapter_returns_raw_dict_response_unwrapped_by_completion_text() -> None:
    from src.services.llm_types import completion_text

    client = _RecordingAzureClient()
    adapter = AzureLlmAdapter(client)
    text = completion_text(adapter.complete("draft this section"))
    assert text == "adapted response"
