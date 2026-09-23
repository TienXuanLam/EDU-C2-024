"""Minimal structural contract used by optional drafting clients."""

from typing import Any, Protocol


class LlmClient(Protocol):
    def complete(self, prompt: Any) -> Any: ...


def completion_text(response: object) -> str:
    """Normalize SDK canonical responses and simple test/provider strings."""
    if isinstance(response, str):
        return response
    if isinstance(response, dict):
        content = response.get("content")
        return content if isinstance(content, str) else ""
    return ""
