"""Unit tests for NLCaseFactsExtractionService."""

from __future__ import annotations

import json
from typing import Any

import pytest

from src.services.nl_case_facts_extraction_service import (
    MAX_NL_INPUT_CHARS,
    NLCaseFactsExtractionError,
    NLCaseFactsExtractionService,
)

_VALID_FACTS = {
    "misconduct_type": "plagiarism in submitted essay",
    "evidence_description": "Several paragraphs copied verbatim from an online source.",
    "subject_role_category": "undergraduate student",
    "case_id": "CASE-2026-0001",
}


class _FakeLLM:
    def __init__(self, responses: list[Any]) -> None:
        self._responses = list(responses)
        self.calls = 0

    def complete(self, _messages: list[dict[str, str]]) -> Any:
        self.calls += 1
        response = self._responses[min(self.calls - 1, len(self._responses) - 1)]
        if isinstance(response, Exception):
            raise response
        return response


def _content(payload: Any) -> dict[str, Any]:
    return {"content": json.dumps(payload), "tool_calls": [], "model": "fake"}


def _service_with(llm: _FakeLLM) -> NLCaseFactsExtractionService:
    service = NLCaseFactsExtractionService()
    service._build_llm = lambda state: llm  # type: ignore[method-assign]
    return service


def test_extract_rejects_empty_text() -> None:
    service = NLCaseFactsExtractionService()
    with pytest.raises(NLCaseFactsExtractionError) as exc_info:
        service.extract({}, "")
    assert exc_info.value.code == "S1_EMPTY_INPUT"


def test_extract_rejects_text_over_max_chars() -> None:
    service = NLCaseFactsExtractionService()
    with pytest.raises(NLCaseFactsExtractionError) as exc_info:
        service.extract({}, "x" * (MAX_NL_INPUT_CHARS + 1))
    assert exc_info.value.code == "S1_INPUT_TOO_LONG"


def test_extract_returns_all_four_fields_from_natural_language_text() -> None:
    llm = _FakeLLM([_content(_VALID_FACTS)])
    result = _service_with(llm).extract({}, "A student copied paragraphs from an online source, case CASE-2026-0001.")
    assert result == _VALID_FACTS
    assert llm.calls == 1


def test_extract_repairs_once_on_malformed_first_attempt() -> None:
    llm = _FakeLLM(
        [
            _content({"misconduct_type": "plagiarism"}),  # missing 3 fields
            _content(_VALID_FACTS),
        ]
    )
    result = _service_with(llm).extract({}, "some case description")
    assert result == _VALID_FACTS
    assert llm.calls == 2


def test_extract_raises_after_repair_still_fails() -> None:
    llm = _FakeLLM([_content({"misconduct_type": "plagiarism"})])
    with pytest.raises(NLCaseFactsExtractionError) as exc_info:
        _service_with(llm).extract({}, "not much useful information here")
    assert exc_info.value.code == "S1_NL_EXTRACTION_FAILED"
    assert llm.calls == 2


def test_extract_raises_when_llm_unavailable() -> None:
    service = NLCaseFactsExtractionService()

    def _raise(_state: dict[str, Any]) -> Any:
        raise RuntimeError("no secret")

    service._build_llm = _raise  # type: ignore[method-assign]
    with pytest.raises(NLCaseFactsExtractionError) as exc_info:
        service.extract({}, "a case description")
    assert exc_info.value.code == "S2_LLM_ERROR"


def test_stg_mock_llm_returns_deterministic_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STG_MOCK_MODE", "true")
    service = NLCaseFactsExtractionService()
    result = service.extract({}, "a plagiarism case description")
    assert set(result) == {"misconduct_type", "evidence_description", "subject_role_category", "case_id"}
    assert result["case_id"] == "CASE-STG-0001"


def test_extract_strips_code_fences() -> None:
    llm = _FakeLLM([{"content": f"```json\n{json.dumps(_VALID_FACTS)}\n```", "tool_calls": [], "model": "fake"}])
    result = _service_with(llm).extract({}, "a plagiarism case description")
    assert result == _VALID_FACTS


def test_extract_rejects_extra_or_missing_field_names() -> None:
    payload = dict(_VALID_FACTS)
    payload["student_name"] = "should not appear"
    llm = _FakeLLM([_content(payload)])
    with pytest.raises(NLCaseFactsExtractionError) as exc_info:
        _service_with(llm).extract({}, "a case description")
    assert exc_info.value.code == "S1_NL_EXTRACTION_FAILED"
    assert llm.calls == 2
