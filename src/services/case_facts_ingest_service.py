"""AgentCore Platform v1.0"""

# Step 1 — CaseFactsIngest. Pure Python, no framework imports (service
# modules must not depend on the agenticstar SDK or on framework
# security-gate code directly).
#
# Custom pre-processing check (proposal §3): reject real names / student IDs
# in evidence_description or subject_role_category. This is separate from,
# and in addition to, the platform S-1 normalizer (HTML strip + truncation).
#
# Detection design note (IMPLEMENTATION_LOG.md A8): a bare "two capitalized
# words" pattern false-positives on legitimate headings/labels. Real-name
# detection here requires a cue word ("name", "student", "professor",
# "advisor", "reported by", "subject name") immediately before the candidate
# name — never a bare capitalization scan. Bare "subject" was deliberately
# excluded from the cue list: this template's own report headings use
# "Subject Role Category" (a field label, not a person reference), which a
# bare "subject" cue false-positives on — confirmed by e2e testing.
#
# Platform-mask interaction (found by running against the real
# agenticstar-agentcore framework, not just the local test stub):
# FunctionNode's @final _security_gate_input() runs the platform's own
# detect_pii() scan on `user_input` and replaces matches with the literal
# token "[MASKED]" *before* calling this node's _extra_security_gate_input()
# hook. A real name the platform already caught (e.g. "Jane Doe") therefore
# never reaches NAME_CUE_RE as itself — it arrives as "[MASKED]", which does
# not match the cue+capitalized-name pattern, so a naive check would let the
# case silently proceed with the name replaced rather than being rejected as
# the proposal requires ("custom pre-processing check" = reject, not
# mask-and-continue). contains_disallowed_identifier() therefore also treats
# the literal PLATFORM_MASK_TOKEN as a rejection signal: if the platform had
# to redact something, that is itself evidence the caller sent un-anonymized
# case facts.
#
# Detection scope and honest limitation (review finding H1): the checks
# below cover four concrete, testable patterns — (1) cue-gated ASCII
# personal names, (2) 6-10 digit ID-shaped runs, (3) department/affiliation
# cue phrases, (4) cue-gated Japanese (kanji/kana) personal names. This is a
# best-effort, defense-in-depth heuristic layer, NOT a guarantee of
# detecting arbitrary free-text PII in every script or phrasing — reliable
# universal free-text PII detection is not feasible for a keyword/regex
# layer. Primary responsibility for submitting genuinely anonymized case
# facts rests with the calling disciplinary-committee system (proposal §3);
# this layer is a secondary check, not a substitute for anonymization at the
# source. See docs/02_design.md "S-2/S-3 Detection Scope" for the full
# policy statement.

from __future__ import annotations

import json
import re

REQUIRED_FIELDS = ("misconduct_type", "evidence_description", "subject_role_category", "case_id")

# Public (not underscore-prefixed): reused by output_validate_service.py for
# the independent step-7 belt-and-suspenders re-scan — one shared PII-shape
# definition instead of two to maintain.
NAME_CUE_RE = re.compile(
    r"(?i:name|student|professor|advisor|reported by|subject name)\s*[:\-]?\s+([A-Z][a-z]+\s[A-Z][a-z]+)"
)
STUDENT_ID_RE = re.compile(r"\b\d{6,10}\b")

# Department/affiliation cue phrases (proposal §3 S-3: output must contain
# "no subject name, student ID, or department"). Detects the cue phrase
# itself followed by at least one more word — presence of the phrase alone
# already reveals institutional affiliation, regardless of what follows.
DEPARTMENT_CUE_RE = re.compile(
    r"(?i:department of|faculty of|school of|institute of|graduate school of|division of|dept\.?\s+of)\s+\S"
)

# Japanese-script detection: unlike NAME_CUE_RE (which must be cue-gated
# because bare "two capitalized words" false-positives on this template's
# own English headings — IMPLEMENTATION_LOG.md A8), a bare run of 2+
# kanji/hiragana/katakana characters carries NO such false-positive risk:
# every string this template itself generates (headings, disclaimer,
# fallback templates) is pure ASCII English. evidence_description/
# subject_role_category are documented as English free text (proposal's
# generated report is English-language MEXT documentation); any embedded
# CJK-script run is therefore inherently suspicious untranslated content
# (commonly a name) and is rejected without needing a cue word.
JAPANESE_SCRIPT_RE = re.compile(r"[一-鿿぀-ゟ゠-ヿ]{2,}")

# Literal token the platform's default S-2 PII scan substitutes in place of a
# detected identifier. Presence of this token means the platform already
# found something to redact in this field.
PLATFORM_MASK_TOKEN = "[MASKED]"


def parse_case_facts(raw: str) -> tuple[dict[str, str] | None, str | None]:
    """Parse the caller-supplied JSON case facts string.

    Returns (case_facts, None) on success or (None, error_message) on failure.
    """
    if not raw or not raw.strip():
        return None, "CaseFactsIngest: user_input is empty"

    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None, "CaseFactsIngest: user_input is not valid JSON"

    if not isinstance(payload, dict):
        return None, "CaseFactsIngest: user_input JSON must be an object"

    missing = [f for f in REQUIRED_FIELDS if not str(payload.get(f, "")).strip()]
    if missing:
        return None, f"CaseFactsIngest: missing required field(s): {', '.join(missing)}"

    case_facts = {field: str(payload[field]).strip() for field in REQUIRED_FIELDS}
    return case_facts, None


def looks_like_natural_language(raw: str) -> bool:
    """True when `raw` is non-empty but NOT a JSON object -- i.e. the
    parse_case_facts() JSON path does not apply, so natural-language
    extraction (via NLCaseFactsExtractionService) is the only remaining
    option. Empty input is left to parse_case_facts's own "user_input is
    empty" error untouched."""
    text = (raw or "").strip()
    if not text:
        return False
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return True
    return not isinstance(parsed, dict)


def contains_disallowed_identifier(text: str) -> bool:
    """True if `text` appears to carry a real ASCII name (cue-word gated), a
    student-ID-shaped digit run, a department/affiliation cue phrase, an
    embedded Japanese-script run, or already shows the platform's own
    PLATFORM_MASK_TOKEN (meaning the platform's S-2 scan already redacted an
    identifier here — itself grounds for rejection, see module docstring).
    Used to reject evidence_description / subject_role_category — never
    applied to case_id (an intentionally coded anonymized reference, not
    free text).

    Scope note (review finding H1): this is a best-effort heuristic layer over a
    fixed set of concrete patterns, not an exhaustive free-text PII
    detector — see module docstring "Detection scope and honest limitation".
    """
    if not text:
        return False
    return (
        bool(NAME_CUE_RE.search(text))
        or bool(STUDENT_ID_RE.search(text))
        or bool(DEPARTMENT_CUE_RE.search(text))
        or bool(JAPANESE_SCRIPT_RE.search(text))
        or PLATFORM_MASK_TOKEN in text
    )
