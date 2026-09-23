"""AgentCore Platform v1.0"""

# Step 5 — SanctionRangeLookup.
#
# review finding H2: the original implementation embedded a generic
# English sanction matrix directly in Python, with no institution-configurable
# KB path, no versioning/provenance, and no fail-closed behavior for a
# missing/invalid policy — contradicting the proposal's "KB (./kb/) lookup"
# design and its own Risk #2 mitigation ("institution-specific application is
# the responsibility of the academic integrity officer" only means something
# if the KB is genuinely swappable per institution).
#
# Fixed design: the sanction range table now lives in an external, versioned
# JSON file (default: src/services/kb/sanction_ranges.json, overridable via config.yaml's
# kb_path — see src/graph/graph.py). load_sanction_kb() is fail-closed: a
# missing file, invalid JSON, or missing required keys raises SanctionKbError
# at agent construction time rather than silently falling back to a
# hardcoded default. lookup_sanction_range() remains a pure, deterministic
# function over the loaded KB dict — no `llm` parameter (IMPLEMENTATION_LOG.md
# A4); an unmapped classification/severity combination raises rather than
# silently substituting a generic range, so a caller-supplied KB that omits a
# combination fails closed instead of masking the gap.
#
# review finding M1 (second round): the shipped reference KB
# (src/services/kb/sanction_ranges.json) is sample data aligned with general knowledge of
# the MEXT 2023 guideline, NOT extracted with verified page/section
# citations from the primary document — it must not be mistaken for a
# citation-backed, production-ready policy. `provenance_verified` is now a
# required KB field: every KB (shipped or institution-supplied) must
# explicitly declare `true`/`false` — no silent omission. `load_sanction_kb()`
# warns loudly (via `warnings.warn`, non-fatal — STG/dev legitimately runs
# against the unverified sample) when `provenance_verified` is `false`; the
# actual production go/no-go gate is the STG Sign-off Record checklist in
# docs/07_operation_guide.md, which requires explicit human attestation that
# provenance has been verified before the ⑤→⑥ stage transition.

from __future__ import annotations

import json
import warnings
from pathlib import Path
from typing import Any

REQUIRED_KB_KEYS = ("kb_version", "source", "ranges", "provenance_verified")


class SanctionKbError(Exception):
    """Raised when the sanction-range KB is missing, malformed, or incomplete.

    Deliberately fail-closed (review finding H2): callers must not catch this to
    substitute a silent default — an institution must supply a valid,
    versioned policy KB before this template can produce sanction
    recommendations.
    """


def load_sanction_kb(kb_path: str) -> dict[str, Any]:
    """Load and validate the sanction-range KB file. Raises SanctionKbError on
    any problem — called once at agent construction time (src/graph/graph.py
    register_nodes()), so a misconfigured kb_path fails agent.compile() loudly
    rather than degrading silently at invoke time."""
    path = Path(kb_path)
    if not path.is_file():
        raise SanctionKbError(
            f"Sanction range KB not found at '{kb_path}'. Set config.yaml's "
            "kb_path to a valid institution policy KB file (see src/services/kb/sanction_ranges.json "
            "for the reference schema)."
        )

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SanctionKbError(f"Sanction range KB at '{kb_path}' is not valid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise SanctionKbError(f"Sanction range KB at '{kb_path}' must be a JSON object.")

    missing = [key for key in REQUIRED_KB_KEYS if key not in data]
    if missing:
        raise SanctionKbError(f"Sanction range KB at '{kb_path}' missing required key(s): {', '.join(missing)}.")

    if not isinstance(data["ranges"], dict) or not data["ranges"]:
        raise SanctionKbError(f"Sanction range KB at '{kb_path}' has an empty or invalid 'ranges' object.")

    if data["provenance_verified"] is not True:
        warnings.warn(
            f"Sanction range KB at '{kb_path}' (v{data.get('kb_version', 'unknown')}) has "
            "provenance_verified=false — this KB has NOT been verified against a cited primary "
            "policy source and must not be used in production. See docs/07_operation_guide.md "
            "'Knowledge Base Setup' and the STG Sign-off Record checklist.",
            stacklevel=2,
        )

    return data


def is_sample_kb(sanction_kb: dict[str, Any]) -> bool:
    """True when the loaded KB has not been provenance-verified — used by the
    STG Sign-off Record checklist and local go-live checks (review finding M1)."""
    return sanction_kb.get("provenance_verified") is not True


def lookup_sanction_range(sanction_kb: dict[str, Any], classification: str, severity: str) -> str:
    """Deterministic KB lookup — no `llm` parameter (asserted by a PB test,
    A4 principle). Raises SanctionKbError (fail-closed) if the KB does not
    define a range for this classification/severity combination — an
    institution-supplied KB that omits a combination must not silently
    substitute a generic range."""
    key = f"{classification}:{severity}"
    ranges = sanction_kb["ranges"]
    if key not in ranges:
        raise SanctionKbError(
            f"Sanction range KB v{sanction_kb.get('kb_version', 'unknown')} "
            f"(source: {sanction_kb.get('source', 'unknown')}) has no entry for '{key}'."
        )
    scope_note = sanction_kb.get("institution_scope_note", "")
    return f"{ranges[key]} {scope_note}".strip()
