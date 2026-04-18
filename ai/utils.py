# -*- coding: utf-8 -*-
"""
Shared utilities for the AI analysis pipeline.

- parse_json_from_llm: robust JSON extraction from LLM responses
- extract_relevant_sections: keyword-based source code section extractor
- FUNC_FIELD_MAP: canonical field name mapping for all 8 ADAS functions
"""
from __future__ import annotations

import json
from typing import Optional


# ── JSON Parsing ─────────────────────────────────────────────────────

def parse_json_from_llm(content: str, fallback: Optional[dict] = None) -> dict:
    """
    Extract and parse a JSON object from an LLM response that may contain
    surrounding markdown, explanation text, or code fences.

    Returns the parsed dict, or `fallback` if parsing fails.
    """
    if not content or not content.strip():
        return fallback or {}
    try:
        start = content.index("{")
        end = content.rindex("}") + 1
        return json.loads(content[start:end])
    except (ValueError, json.JSONDecodeError):
        return fallback or {}


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
