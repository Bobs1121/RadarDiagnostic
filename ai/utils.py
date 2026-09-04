# -*- coding: utf-8 -*-
"""
Shared utilities for the AI analysis pipeline.

- parse_json_from_llm: robust JSON extraction from LLM responses
- extract_relevant_sections: keyword-based source code section extractor
- FUNC_FIELD_MAP: canonical field name mapping for all 8 ADAS functions
"""
from __future__ import annotations

import json
import re
import sys
from typing import Optional


# ── JSON Parsing ─────────────────────────────────────────────────────

_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_FENCE_JSON_RE = re.compile(
    r"```(?:json|JSON)?\s*(\{.*?\})\s*```",
    re.DOTALL,
)
_TRAILING_COMMA_RE = re.compile(r",(\s*[}\]])")
# Last-resort: greedily grab the outermost balanced {...} block.
# We pair braces manually because regex can't balance, but for typical LLM
# outputs the LLM emits one JSON object with no nested top-level
# ambiguities, so the lazy match works.
_OUTERMOST_OBJECT_RE = re.compile(r"\{(?:[^{}]|\{[^{}]*\})*\}", re.DOTALL)


def _strip_wrappers(content: str) -> str:
    """Remove ``<think>`` blocks and markdown code fences.

    LLMs (Qwen3 especially) often emit reasoning inside ``<think>...</think>``
    tags, or wrap the answer in ``` fences.  Both break the
    *first-brace / last-brace* slicing heuristic because a stray ``{`` in the
    thinking block would become the slice start.
    """
    s = content.strip()
    s = _THINK_BLOCK_RE.sub("", s).strip()
    if s.startswith("```"):
        lines = s.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        while lines and lines[-1].strip().startswith("```"):
            lines.pop()
        s = "\n".join(lines).strip()
    return s


def _log_parse_failure(content: str, context: str, err: Exception) -> None:
    """Print a compact diagnostic line to stderr.

    Only called when *every* parse strategy has failed, so noise is minimal.
    """
    tag = f"[{context}] " if context else ""
    head = content[:300].replace("\n", " ⏎ ")
    tail_part = ""
    if len(content) > 600:
        tail = content[-300:].replace("\n", " ⏎ ")
        tail_part = f" tail={tail!r}"
    msg = (
        f"[parse_json_from_llm] {tag}FAILED: {type(err).__name__}: {err} "
        f"(len={len(content)}, head={head!r}{tail_part})"
    )
    print(msg, file=sys.stderr)


def parse_json_from_llm(
    content: str,
    fallback: Optional[dict] = None,
    context: str = "",
    max_retries: int = 2,
) -> dict:
    """Robustly extract a JSON object from an LLM response.

    Tries, in order:
      1. ``json.loads`` on the cleaned content (strips ``</think>`` blocks and
         leading/trailing code fences).
      2. Match a fenced ``\\`\\`\\`json {...} \\`\\`\\`\\`` block.
      3. Slice from first ``{`` to last ``}`` and parse.
      4. Same slice, but remove trailing commas before ``}``/``]``.
      5. Retry with additional repair strategies (up to ``max_retries`` times):
         - Remove unquoted keys
         - Fix single-quoted strings
         - Remove trailing content after closing brace

    On total failure, logs a diagnostic line to stderr (only if every strategy
    fails) and returns ``fallback`` (or ``{}`).

    The ``context`` argument is a short label (e.g. ``"moderator_challenge"``)
    that gets included in the diagnostic log so operators can tell which call
    site tripped.
    """
    if not content or not content.strip():
        return fallback or {}

    cleaned = _strip_wrappers(content)
    last_err: Optional[Exception] = None

    # Strategy 1: direct parse
    try:
        return json.loads(cleaned)
    except (ValueError, json.JSONDecodeError) as e:
        last_err = e

    # Strategy 2: fenced JSON block
    fence_match = _FENCE_JSON_RE.search(cleaned)
    if fence_match:
        try:
            return json.loads(fence_match.group(1))
        except (ValueError, json.JSONDecodeError) as e:
            last_err = e

    # Strategy 3: brace slice (first-to-last)
    snippet = None
    if "{" in cleaned and "}" in cleaned:
        start = cleaned.index("{")
        end = cleaned.rindex("}") + 1
        snippet = cleaned[start:end]
        try:
            return json.loads(snippet)
        except (ValueError, json.JSONDecodeError) as e:
            last_err = e

        # Strategy 4: remove trailing commas
        repaired = _TRAILING_COMMA_RE.sub(r"\1", snippet)
        if repaired != snippet:
            try:
                return json.loads(repaired)
            except (ValueError, json.JSONDecodeError) as e:
                last_err = e

    # Strategy 5: outer-object regex (handles LLM "{"..."}" embedded in
    # markdown prose or surrounded by stray words).
    if snippet is None:
        m = _OUTERMOST_OBJECT_RE.search(cleaned)
        if m:
            try:
                return json.loads(m.group(0))
            except (ValueError, json.JSONDecodeError) as e:
                last_err = e

    # Strategy 6+: retry with progressive repair (up to max_retries times).
    base = snippet if snippet is not None else cleaned
    last_repaired = None
    for attempt in range(max_retries):
        repaired = _advanced_repair(base, last_repaired)
        if not repaired:
            break
        last_repaired = repaired
        try:
            return json.loads(repaired)
        except (ValueError, json.JSONDecodeError) as e:
            last_err = e

    if last_err is not None:
        _log_parse_failure(content, context, last_err)
    return fallback or {}


def _advanced_repair(text: str, prev: Optional[str] = None) -> Optional[str]:
    """Apply advanced JSON repair strategies.

    Phase 15 / 2.2.2: chain successive repair passes when called
    repeatedly. Each call applies one extra strategy on top of ``prev``
    (which is the result of the previous call) — this lets the
    ``max_retries`` loop in :func:`parse_json_from_llm` make *progress*
    instead of bailing out on the same dead-end snippet.
    """
    import re
    if not text:
        return None
    base = prev if prev is not None else text

    repaired = base

    # Pass A: collapse single-quoted strings → double-quoted.
    #         Done first because LLMs often mix both styles mid-field.
    repaired = repaired.replace("'", '"')

    # Pass B: remove control characters that JSON forbids raw.
    repaired = re.sub(r"[\x00-\x1f]", " ", repaired)

    # Pass C: drop trailing commas before } or ].
    repaired = _TRAILING_COMMA_RE.sub(r"\1", repaired)

    # Pass D: re-slice to the outermost {...} block to drop stray prose.
    if "{" in repaired and "}" in repaired:
        start = repaired.index("{")
        end = repaired.rindex("}") + 1
        repaired = repaired[start:end]

    # Pass E: if the string still isn't parseable, try converting
    #         Python booleans/nulls/None (common LLM hallucination).
    repaired = re.sub(r"\bTrue\b", "true", repaired)
    repaired = re.sub(r"\bFalse\b", "false", repaired)
    repaired = re.sub(r"\bNone\b", "null", repaired)

    return repaired if repaired != base else None


# ── Source Code Section Extraction ───────────────────────────────────

def extract_relevant_sections(
    text: str,
    keywords: list[str],
    context_lines: int = 15,
    max_chunks: int = 30,
) -> str:
    """
    Extract code sections surrounding lines that match any keyword.
    Overlapping ranges are merged. Returns a string with line-numbered chunks.
    """
    lines = text.split("\n")
    ranges: list[tuple[int, int]] = []

    kw_lower = [k.lower() for k in keywords]
    for i, line in enumerate(lines):
        ll = line.lower()
        if any(k in ll for k in kw_lower):
            s = max(0, i - context_lines)
            e = min(len(lines), i + context_lines + 1)
            ranges.append((s, e))

    if not ranges:
        return ""

    ranges.sort()
    merged = [ranges[0]]
    for s, e in ranges[1:]:
        ps, pe = merged[-1]
        if s <= pe + 5:
            merged[-1] = (ps, max(pe, e))
        else:
            merged.append((s, e))

    parts = []
    for s, e in merged[:max_chunks]:
        chunk = "\n".join(f"L{s+j+1}: {lines[s+j]}" for j in range(e - s))
        parts.append(chunk)
    return "\n...\n".join(parts)


def build_keyword_variants(func_name: str) -> list[str]:
    """Generate common C naming variants for an ADAS function name."""
    fn = func_name.upper()
    cap = func_name.capitalize()
    return [fn.lower(), fn, f"f{cap}", f"b{cap}", f"{cap}"]


# ── Canonical function list (single source of truth) ─────────────────

ALL_FUNCTIONS: list[str] = ["BSD", "LCA", "DOW", "RCW", "RCTA", "RCTB", "FCTA", "FCTB"]

# ── Function ↔ Field Mapping (all 8 ADAS functions) ─────────────────

FUNC_FIELD_MAP: dict[str, dict] = {
    "FCTA": {
        "state": "fcta_system_state",
        "enable": "fcta_enable",
        "enable_cap": "fcta_enable_capture",
        "warnings": ["left_fcta_warning", "right_fcta_warning"],
        "error_status": "get_rdafcta_error_status",
        "obj_warning_flag": "obj_fcta_warning_flag",
        "obj_brake_flag": None,
        "side_prefix": "front",
        "ego_topics": [
            "/wf/ego_car_info/front_left/parsed",
            "/wf/ego_car_info/front_right/parsed",
        ],
    },
    "FCTB": {
        "state": "fctb_system_state",
        "enable": "fctb_enable",
        "enable_cap": "fctb_enable_capture",
        "warnings": [],
        "error_status": "get_rdafctb_error_status",
        "obj_warning_flag": "obj_fctb_warning_flag",
        "obj_brake_flag": None,
        "side_prefix": "front",
        "ego_topics": [
            "/wf/ego_car_info/front_left/parsed",
            "/wf/ego_car_info/front_right/parsed",
        ],
    },
    "BSD": {
        "state": "bsd_system_state",
        "enable": "bsd_enable",
        "enable_cap": "bsd_enable_capture",
        "warnings": ["left_bsd_warning", "right_bsd_warning"],
        "error_status": "get_rdabsd_error_status",
        "obj_warning_flag": "obj_bsd_warning_flag",
        "obj_brake_flag": None,
        "side_prefix": "rear",
        "ego_topics": [
            "/wf/ego_car_info/rear_left/parsed",
            "/wf/ego_car_info/rear_right/parsed",
        ],
    },
    "LCA": {
        "state": "lca_system_state",
        "enable": "lca_enable",
        "enable_cap": "lca_enable_capture",
        "warnings": ["left_lca_warning", "right_lca_warning"],
        "error_status": "get_rdalca_error_status",
        "obj_warning_flag": "obj_lca_warning_flag",
        "obj_brake_flag": None,
        "side_prefix": "rear",
        "ego_topics": [
            "/wf/ego_car_info/rear_left/parsed",
            "/wf/ego_car_info/rear_right/parsed",
        ],
    },
    "DOW": {
        "state": "dow_system_state",
        "enable": "dow_enable",
        "enable_cap": "dow_enable_capture",
        "warnings": ["left_dow_warning", "right_dow_warning"],
        "error_status": "get_rdadow_error_status",
        "obj_warning_flag": "obj_dow_warning_flag",
        "obj_brake_flag": None,
        "side_prefix": "rear",
        "ego_topics": [
            "/wf/ego_car_info/rear_left/parsed",
            "/wf/ego_car_info/rear_right/parsed",
        ],
    },
    "RCW": {
        "state": "rcw_system_state",
        "enable": "rcw_enable",
        "enable_cap": "rcw_enable_capture",
        "warnings": ["left_rcw_warning", "right_rcw_warning"],
        "error_status": "get_rdarcw_error_status",
        "obj_warning_flag": "obj_rcw_warning_flag",
        "obj_brake_flag": None,
        "side_prefix": "rear",
        "ego_topics": [
            "/wf/ego_car_info/rear_left/parsed",
            "/wf/ego_car_info/rear_right/parsed",
        ],
    },
    "RCTA": {
        "state": "rcta_system_state",
        "enable": "rcta_enable",
        "enable_cap": "rcta_enable_capture",
        "warnings": ["left_rcta_warning", "right_rcta_warning"],
        "error_status": "get_rdarcta_error_status",
        "obj_warning_flag": "obj_rcta_warning_flag",
        "obj_brake_flag": None,
        "side_prefix": "rear",
        "ego_topics": [
            "/wf/ego_car_info/rear_left/parsed",
            "/wf/ego_car_info/rear_right/parsed",
        ],
    },
    "RCTB": {
        "state": "rctb_system_state",
        "enable": "rctb_enable",
        "enable_cap": "rctb_enable_capture",
        "warnings": [],
        "error_status": "get_rdarctb_error_status",
        "obj_warning_flag": "obj_rctb_warning_flag",
        "obj_brake_flag": None,
        "side_prefix": "rear",
        "ego_topics": [
            "/wf/ego_car_info/rear_left/parsed",
            "/wf/ego_car_info/rear_right/parsed",
        ],
    },
}


_EMPTY_FUNC_FIELDS: dict = {
    "state": "",
    "enable": "",
    "enable_cap": "",
    "warnings": [],
    "error_status": "",
    "obj_warning_flag": "",
    "obj_brake_flag": None,
    "side_prefix": "",
    "ego_topics": [],
    "_unknown": True,
}


def get_func_fields(func_name: str) -> dict:
    """Return field mapping for a function.

    Unknown/empty names return a neutral template with ``_unknown=True`` so
    callers can detect the situation and react honestly instead of silently
    treating an unrecognised case as FCTA.
    """
    if not func_name:
        return dict(_EMPTY_FUNC_FIELDS)
    return FUNC_FIELD_MAP.get(func_name.upper(), dict(_EMPTY_FUNC_FIELDS))


def infer_side_prefix(func_name: str, config: dict | None = None) -> str:
    """Infer front/rear prefix from config, falling back to canonical map.

    When an unknown function name is encountered we at least try to respect
    ``config.yaml``'s ``functions.front`` / ``functions.rear`` listing before
    giving up.
    """
    if not func_name:
        return ""
    fn = func_name.upper()
    fmap = FUNC_FIELD_MAP.get(fn)
    if fmap:
        return fmap.get("side_prefix", "")
    if config:
        funcs = (config or {}).get("functions", {}) or {}
        if fn in [f.upper() for f in funcs.get("front", []) or []]:
            return "front"
        if fn in [f.upper() for f in funcs.get("rear", []) or []]:
            return "rear"
    return ""
