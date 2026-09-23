"""Natural-language to JSON extraction for academic-misconduct case facts.

Runs only as a fallback inside PreProcessNode when user_input is not already
valid JSON (see pre_process_node.py::_extra_security_gate_input). Never
trusted blindly: the JSON this service returns is fed back through the exact
same parse_case_facts()-equivalent field validation and
contains_disallowed_identifier() re-scan as the legacy JSON path.

This module is intentionally NOT "pure Python, no framework imports" like
case_facts_ingest_service.py -- it needs an LLM client, so it lives with the
other framework-aware service (azure_openai_service.py), not alongside the
pure-Python ingest module.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from shared.services.llm.base_llm import BaseLLM

from src.services.azure_openai_service import AzureOpenAIService
from src.services.case_facts_ingest_service import REQUIRED_FIELDS

MAX_NL_INPUT_CHARS = 4096
MAX_REPAIR_ROUNDS = 1

_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)

_SYSTEM_PROMPT = """You are a strict data-extraction assistant for a university \
academic-misconduct case description typed in free-form prose by a disciplinary \
committee member. Extract ONLY these four fields, verbatim or lightly \
summarized from what is explicitly stated:
{"misconduct_type": <string>, "evidence_description": <string>, "subject_role_category": <string>, "case_id": <string>}

Rules:
- Never invent a field value that is not stated or clearly implied in the text.
- If a real person's name, student ID number, or department/affiliation
  appears in the text, do NOT copy it into evidence_description or
  subject_role_category verbatim -- generalize it away (e.g. "a student"
  instead of a name) or omit it; this input is expected to already be
  anonymized per policy, so a name/ID/department should not normally be
  present.
- case_id should be a case tracking or reference code, not a person's name.
- subject_role_category should describe a role (e.g. "undergraduate student",
  "graduate student", "faculty member"), not an identity.
- Return ONLY a single JSON object, no markdown code fences, no commentary,
  with exactly these four keys and no others."""

_USER_TEMPLATE = "Extract the case facts from this text:\n{text}"

_REPAIR_TEMPLATE = """Your previous JSON output was invalid: {error}

Previous output:
{previous}

Re-extract from the ORIGINAL text below and return corrected JSON in the \
exact required shape. Original text:
{text}"""


class NLCaseFactsExtractionError(Exception):
    """Raised when NL extraction cannot produce a usable candidate after retry."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class _StgCaseFactsExtractionLLM:
    """Deterministic Stage 5 adapter; never selected implicitly in production."""

    def complete(self, _messages: list[dict[str, str]]) -> dict[str, Any]:
        return {
            "content": json.dumps(
                {
                    "misconduct_type": "plagiarism in submitted essay",
                    "evidence_description": (
                        "Several full paragraphs were copied verbatim from an online "
                        "source without citation or quotation marks."
                    ),
                    "subject_role_category": "undergraduate student",
                    "case_id": "CASE-STG-0001",
                }
            ),
            "tool_calls": [],
            "model": "stg-deterministic",
        }


class NLCaseFactsExtractionService:
    """Extract the four required case-fact fields from free-form chat text."""

    def __init__(self, llm_config: dict[str, Any] | None = None) -> None:
        self._llm_service = AzureOpenAIService(llm_config)

    def _build_llm(self, state: dict[str, Any]) -> BaseLLM:
        """Build a fresh, secret-bound LLM client for this invocation.

        Same per-invocation rationale as the drafting nodes: never cache a
        client at construction time. STG_MOCK_MODE=true returns a
        deterministic stub instead of a real client.
        """
        if os.environ.get("STG_MOCK_MODE", "").lower() == "true":
            return _StgCaseFactsExtractionLLM()
        return self._llm_service.create_client(state)

    def extract(self, state: dict[str, Any], raw_text: str) -> dict[str, str]:
        """Return a dict with exactly REQUIRED_FIELDS keys, all non-empty strings.

        Raises NLCaseFactsExtractionError on any unrecoverable failure -- the
        caller (PreProcessNode) must catch this and map it to a rejection,
        never let it propagate past the node boundary.
        """
        text = (raw_text or "").strip()
        if not text:
            raise NLCaseFactsExtractionError("S1_EMPTY_INPUT", "user_input text is empty")
        if len(text) > MAX_NL_INPUT_CHARS:
            raise NLCaseFactsExtractionError(
                "S1_INPUT_TOO_LONG", f"user_input text exceeds {MAX_NL_INPUT_CHARS} characters"
            )

        try:
            llm = self._build_llm(state)
        except Exception as exc:  # noqa: BLE001 — missing/invalid secret
            raise NLCaseFactsExtractionError(
                "S2_LLM_ERROR", f"No LLM client is configured for case-facts extraction: {type(exc).__name__}"
            ) from exc

        prompt = _USER_TEMPLATE.format(text=text)
        attempt, error = self._call_and_parse(llm, prompt)
        if error:
            for _ in range(MAX_REPAIR_ROUNDS):
                repair_prompt = _REPAIR_TEMPLATE.format(error=error, previous=json.dumps(attempt or {}), text=text)
                attempt, error = self._call_and_parse(llm, repair_prompt)
                if not error:
                    break
        if error or attempt is None:
            raise NLCaseFactsExtractionError(
                "S1_NL_EXTRACTION_FAILED",
                f"Could not extract case facts from the provided text: {error}. "
                "Please describe the misconduct type, the evidence, the subject's "
                "role (e.g. undergraduate student), and a case reference code.",
            )
        return attempt

    def _call_and_parse(self, llm: BaseLLM, prompt: str) -> tuple[dict[str, str] | None, str | None]:
        try:
            response = llm.complete(
                [{"role": "system", "content": _SYSTEM_PROMPT}, {"role": "user", "content": prompt}]
            )
        except Exception as exc:  # noqa: BLE001
            return None, f"LLM call failed: {type(exc).__name__}"
        if not isinstance(response, dict) or not isinstance(response.get("content"), str):
            return None, "LLM response does not follow the canonical SDK contract"
        raw = response["content"]
        if len(raw) > 8192:
            return None, "LLM response exceeds size limit"
        cleaned = _CODE_FENCE_RE.sub("", raw).strip()
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError:
            return None, "LLM output is not valid JSON"
        if not isinstance(parsed, dict):
            return None, "LLM output must be a JSON object"

        if set(parsed) != set(REQUIRED_FIELDS):
            return parsed, f"extracted JSON must contain exactly these fields: {list(REQUIRED_FIELDS)}"
        missing = [f for f in REQUIRED_FIELDS if not str(parsed.get(f, "")).strip()]
        if missing:
            return parsed, f"extracted JSON is missing value(s) for: {missing}"

        return {field: str(parsed[field]).strip() for field in REQUIRED_FIELDS}, None
