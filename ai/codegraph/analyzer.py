# -*- coding: utf-8 -*-
"""
Static Analyzer — regex-based C code analysis for CodeGraph.

Phases implemented:
  1. File Index       — scan files, compute hashes
  2. Function Extract — find FUNCTION nodes with line ranges
  3. Call Graph       — CALLS edges between functions
  4. Variable Access  — READS_VAR / WRITES_VAR edges
  5. Signal Interface — READS_SIGNAL / WRITES_SIGNAL edges (Rte_*, ReadSignal, WriteSignal)
  6. State Machine    — STATE nodes + TRANSITION edges
  7. Module Binding   — BELONGS_TO edges from FUNC_KEYWORDS
  8. Cross-Module     — auto-discover shared entities (computed by query layer)
  9. Calibration Params — CALIB_PARAM nodes from paraDefine.h etc.
 10. Behaviour Patterns — pattern labels on edges (HoldRelease, etc.)
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Optional


# ── Helpers ────────────────────────────────────────────────────────────

# Keywords that look like function defs but aren't
_CONTROL_KEYWORDS = frozenset({
    "if", "else", "while", "for", "switch", "do", "return",
    "typedef", "struct", "enum", "union", "case", "default",
    "sizeof", "alignof", "defined",
})

# Regex: function definition
# Matches: [static inline CONST] return_type function_name(params)
# The opening { is expected on the SAME or NEXT line
_FUNC_DEF_RE = re.compile(
    r"^(?:(?:static|inline|CONST|const)\s+)*"
    r"(?P<ret>\w[\w\s\*?]*?)\s+"       # return type (may include *_t, pointers)
    r"(?P<name>\w+)\s*"                 # function name
    r"\((?P<params>[^)]*)\)"            # params
    r"\s*$"
)

# Regex: function call inside a function body
_FUNC_CALL_RE = re.compile(r"\b(?P<name>\w+)\s*\(")

# Regex: Rte Read/Write patterns
_RTE_READ_RE = re.compile(
    r"\bRte_(?:\w+_)?Read_(?P<module>\w+)_(?P<signal>\w+)\s*\("
)
_RTE_WRITE_RE = re.compile(
    r"\bRte_(?:\w+_)?Write_(?P<module>\w+)_(?P<signal>\w+)\s*\("
)

# Regex: RteLite Read/Write (GWM_B26 style: RteLite_Read_SignalName(&port))
_RTELite_READ_RE = re.compile(
    r"\bRteLite_Read_(?P<signal>\w+)\s*\("
)
_RTELite_WRITE_RE = re.compile(
    r"\bRteLite_Write_(?P<signal>\w+)\s*\("
)

# Regex: AUTOSAR P2S/S2P ReadSignal/WriteSignal (bare)
_READ_SIGNAL_RE = re.compile(
    r"\bReadSignal\s*\(\s*(?P<signal>\w+)\s*\)"
)
_WRITE_SIGNAL_RE = re.compile(
    r"\bWriteSignal\s*\(\s*(?P<signal>\w+)\s*,\s*(?P<var>\w+)"
)

# Regex: RteComMapping macro calls (GWM_B26 style)
# RteComMapping_ReadSignal(SignalName)(&var) → expands to RteLite_Read_SignalName(&var)
# RteComMapping_WriteSignal(SignalName)(expr) → expands to RteLite_Write_SignalName(expr)
_RTE_MAPPING_READ_RE = re.compile(
    r"\bRteComMapping_ReadSignal\s*\(\s*(?P<signal>\w+)\s*\)"
)
_RTE_MAPPING_WRITE_RE = re.compile(
    r"\bRteComMapping_WriteSignal\s*\(\s*(?P<signal>\w+)\s*\)"
)

# Regex: global variable write patterns
_VAR_WRITE_ASSIGN_RE = re.compile(r"\b(?P<var>\w+)\s*=[^=]")
_VAR_WRITE_INC_RE = re.compile(r"\b(?P<var>\w+)\s*(?:\+\+|--)\b|(?:\+\+|--)\s*\b(?P<var2>\w+)\b")
_STRUCT_FIELD_WRITE_RE = re.compile(
    r"\b(?P<struct>\w+)(?:->|\.)(?P<field>\w+)\s*=[^=]"
)

# Regex: #include
_INCLUDE_RE = re.compile(r'^\s*#\s*include\s*[<"](?P<path>[^>"]+)[>"]')

# Regex: systemState assignment (state machine)
_STATE_ASSIGN_RE = re.compile(
    r"(?P<target>\w+(?:->|\.)?systemState)\s*=\s*(?P<value>\w+)"
)

# Regex: state switch/if patterns
_STATE_SWITCH_RE = re.compile(
    r"\b(?:switch|if)\s*\(\s*(?P<state_var>\w+(?:->|\.)?systemState)\s*(?:==\s*(?P<comp_val>\w+))?\s*\)"
)

# Regex: calibration params in paraDefine.h style
# e.g. float fFctbActiveUpSpd = 21.0f;  or  #define FCTB_ACTIVE_UP_SPD 21.0f
_CALIB_DEFINE_RE = re.compile(
    r"#\s*define\s+(?P<name>\w+)\s+(?P<value>[0-9]+(?:\.[0-9]+)?f?)"
)
_CALIB_ASSIGN_RE = re.compile(
    r"^(?:static\s+)?(?P<type>\w+(?:_t)?)\s+(?P<name>\w+)\s*=\s*(?P<value>[0-9]+(?:\.[0-9]+)?f?)\s*;"
)

# Regex: behaviour patterns
_HOLD_RELEASE_RE = re.compile(
    r"if\s*\(.*?\)\s*\{[^}]*?(?P<var>\w+)\s*=\s*(?:false|0|FALSE|NULL)[^}]*?\}",
    re.DOTALL,
)
_ACCUMULATE_RE = re.compile(
    r"(?P<var>\w+)\s*\+=\s*(?P<dt>\w+)"
)
_HYSTERESIS_RE = re.compile(
    r"(?P<var>\w+)\s*(?:<|>|<=|>=)\s*(?P<v1>[0-9.]+).*?(?P=var)\s*(?:<|>|<=|>=)\s*(?P<v2>[0-9.]+)"
)
_DEBOUNCE_RE = re.compile(
    r"(?P<cnt>\w+)\s*\+\+.*?if\s*\(.*?(?P=cnt)\s*>=?\s*(?P<threshold>\d+)"
)
_EDGE_TRIGGER_RE = re.compile(
    r"(?P<prev>\w+[_]?prev|prev_?\w+)\s*==\s*0\s*&\s*&\s*(?P<cur>\w+[_]?cur|cur_?\w+)\s*[!=]=\s*0"
)


def _parse_c_number(s: str) -> float:
    """Parse C numeric literal (handles f/F/l/L suffixes)."""
    return float(s.lower().rstrip("fl"))


def normalize_path(p: str) -> str:
    """Convert backslashes to forward slashes for consistent storage."""
    return p.replace("\\", "/")


def file_hash(path: Path) -> str:
    """SHA-256 of file content, first 16 hex chars."""
    data = path.read_bytes()
    return hashlib.sha256(data).hexdigest()[:16]


def strip_strings_and_comments(line: str) -> str:
    """Remove C string literals and comments to avoid false positives."""
    # Remove // comments
    line = re.sub(r"//.*$", "", line)
    # Remove /* ... */ block comments (single-line)
    line = re.sub(r"/\*.*?\*/", "", line)
    # Remove "string literals"
    line = re.sub(r'"[^"]*"', '""', line)
    # Remove 'char literals'
    line = re.sub(r"'[^']*'", "''", line)
    return line


# ── Phase 1: File Index ────────────────────────────────────────────────

def phase1_file_index(source_root: Path, key_files: list[str]) -> list[dict]:
    """
    Scan source files, compute hashes, return list of file info dicts.

    Returns: [{file_path (normalized), full_path, hash, line_count, exists}]
    """
    results = []
    for rel_path in key_files:
        norm = normalize_path(rel_path)
        full = source_root / norm
        info = {
            "file_path": norm,
            "full_path": full,
            "exists": full.exists(),
            "hash": None,
            "line_count": 0,
        }
        if full.exists():
            info["hash"] = file_hash(full)
            info["line_count"] = full.read_text(encoding="utf-8", errors="replace").count("\n") + 1
        results.append(info)
    return results


# ── Phase 2: Function Extraction ───────────────────────────────────────

def phase2_extract_functions(file_path: Path, rel_path: str) -> list[dict]:
    """
    Extract function definitions from a C source file.

    Returns: [{name, start_line, end_line, return_type, params, is_static}]
    Lines are 1-indexed.
    """
    try:
        text = file_path.read_text(encoding="utf-8", errors="replace")
    except (OSError, PermissionError):
        return []

    lines = text.split("\n")
    functions = []

    i = 0
    while i < len(lines):
        line = lines[i].strip()

        # Skip preprocessor, comments, empty
        if not line or line.startswith("#") or line.startswith("//") or line.startswith("/*"):
            i += 1
            continue

        # Support both common C styles:
        #   int f(void)\n   {
        # and
        #   int f(void) { ... }
        # The historical matcher only accepted the first style even though
        # its contract/documentation says the opening brace may be on either
        # line.  Strip the body suffix only for matching the signature; the
        # original line is still used by _find_function_end().
        signature_line = line.split("{", 1)[0].rstrip() if "{" in line else line
        m = _FUNC_DEF_RE.match(signature_line)
        if m and m.group("name") not in _CONTROL_KEYWORDS:
            # Verify next non-empty line contains {
            found_brace = "{" in line
            for j in range(i + 1, min(i + 3, len(lines))):
                if "{" in lines[j]:
                    found_brace = True
                    break

            if found_brace:
                func_name = m.group("name")
                ret_type = m.group("ret").strip()
                params = m.group("params").strip()
                start_line = i + 1  # 1-indexed
                end_line = _find_function_end(lines, i)
                is_static = 1 if "static" in line.lower() else 0

                # Skip if it looks like a type or macro, not a real function
                if _looks_like_function(func_name, ret_type):
                    functions.append({
                        "name": func_name,
                        "start_line": start_line,
                        "end_line": end_line,
                        "return_type": ret_type,
                        "params": params,
                        "is_static": is_static,
                    })
                    # ``end_line`` is 1-indexed while ``i`` is a zero-indexed
                    # list position.  Advancing to ``end_line`` skips exactly
                    # the closing-brace line and keeps the next definition;
                    # ``end_line + 1`` silently dropped adjacent functions.
                    i = end_line
                    continue

        i += 1

    return functions


def _looks_like_function(name: str, ret_type: str) -> bool:
    """Filter out false positives: constructors, type aliases, etc."""
    # Skip if return type looks like a keyword
    if ret_type.lower() in ("void", "int", "float", "double", "char", "bool",
                             "uint8_t", "uint16_t", "uint32_t", "uint64_t",
                             "int8_t", "int16_t", "int32_t", "int64_t",
                             "bool", "status", "t_status", "t_result"):
        return True
    # Skip very short names (likely macros)
    if len(name) <= 2:
        return False
    return True


def _find_function_end(lines: list[str], start: int) -> int:
    """Find the closing } of a function body using brace counting.

    Returns 1-indexed line number.
    """
    depth = 0
    found_open = False
    for i in range(start, len(lines)):
        clean = strip_strings_and_comments(lines[i])
        for ch in clean:
            if ch == "{":
                depth += 1
                found_open = True
            elif ch == "}":
                depth -= 1
                if found_open and depth == 0:
                    return i + 1  # 1-indexed
    return len(lines)  # fallback: end of file


# ── Phase 3: Call Graph ────────────────────────────────────────────────

def phase3_call_graph(file_path: Path, functions: list[dict], known_functions: set[str]) -> list[dict]:
    """
    Extract function calls within each function body.

    Returns: [{caller, callee, line}] for CALLS edges.
    """
    try:
        text = file_path.read_text(encoding="utf-8", errors="replace")
    except (OSError, PermissionError):
        return []

    lines = text.split("\n")
    calls = []

    for func in functions:
        caller = func["name"]
        for line_num in range(func["start_line"], min(func["end_line"] + 1, len(lines))):
            line = lines[line_num - 1]  # 0-indexed -> line_num is 1-indexed
            clean = strip_strings_and_comments(line)

            for m in _FUNC_CALL_RE.finditer(clean):
                callee = m.group("name")
                # Only record calls to known functions (filter noise)
                if callee in known_functions and callee != caller:
                    calls.append({
                        "caller": caller,
                        "callee": callee,
                        "line": line_num,
                    })

    return calls


# ── Phase 4: Variable Access ───────────────────────────────────────────

def phase4_variable_access(
    file_path: Path,
    functions: list[dict],
    known_variables: set[str],
) -> list[dict]:
    """
    Extract variable reads/writes within function bodies.

    Returns: [{function, var_name, access_type, line}]
    access_type: 'read' | 'write'
    """
    if not known_variables:
        return []

    try:
        text = file_path.read_text(encoding="utf-8", errors="replace")
    except (OSError, PermissionError):
        return []

    lines = text.split("\n")
    accesses = []

    kv_patterns = [re.compile(r"\b" + re.escape(v) + r"\b") for v in known_variables]

    for func in functions:
        for line_num in range(func["start_line"], min(func["end_line"] + 1, len(lines))):
            line = lines[line_num - 1]
            clean = strip_strings_and_comments(line)

            # Skip comments and preprocessor
            if clean.startswith("//") or clean.startswith("#") or not clean.strip():
                continue

            for pat in kv_patterns:
                if not pat.search(clean):
                    continue

                var_name = pat.pattern[2:-2]  # extract name from \bNAME\b pattern

                # Determine read vs write
                access_type = _classify_var_access(clean, var_name)
                if access_type:
                    accesses.append({
                        "function": func["name"],
                        "var_name": var_name,
                        "access_type": access_type,
                        "line": line_num,
                    })

    return accesses


def _classify_var_access(clean_line: str, var_name: str) -> Optional[str]:
    """Classify variable access as 'read' or 'write'."""
    # Write patterns (check before read)
    write_patterns = [
        rf"(?:^|[^.&>])(?:{var_name})\s*=[^=]",   # var = ... (not ==)
        rf"(?:{var_name})\s*\+\+",                  # var++
        rf"\+\+\s*(?:{var_name})",                  # ++var
        rf"(?:{var_name})\s*--",                    # var--
        rf"--\s*(?:{var_name})",                    # --var
        rf"(?:\w+)(?:->|\.)\s*{var_name}\s*=[^=]",  # struct->var = or struct.var =
    ]
    for pat in write_patterns:
        if re.search(pat, clean_line):
            return "write"

    # Read: any other occurrence
    if re.search(rf"\b{re.escape(var_name)}\b", clean_line):
        return "read"

    return None


# ── Phase 5: Signal Interface ──────────────────────────────────────────

def phase5_signal_interface(file_path: Path, functions: list[dict]) -> list[dict]:
    """
    Extract Rte_Read/Rte_Write/ReadSignal/WriteSignal/RteLite_Read/RteLite_Write calls.

    Returns: [{function, signal_name, signal_module, access_type, rte_call, line}]
    access_type: 'read' | 'write'

    For header files (.h) with function declarations, scans entire file
    to extract signal interface declarations.
    """
    try:
        text = file_path.read_text(encoding="utf-8", errors="replace")
    except (OSError, PermissionError):
        return []

    lines = text.split("\n")
    signals = []

    # Determine scan range: function bodies for .c, entire file for .h
    is_header = file_path.suffix == ".h"

    if is_header:
        # For headers with function declarations, scan entire file
        for line_num, line in enumerate(lines, 1):
            clean = strip_strings_and_comments(line)
            _extract_signal_matches_from_line(clean, line_num, signals, None)
    else:
        for func in functions:
            for line_num in range(func["start_line"], min(func["end_line"] + 1, len(lines))):
                line = lines[line_num - 1]
                clean = strip_strings_and_comments(line)
                _extract_signal_matches_from_line(clean, line_num, signals, func["name"])

    return signals


def _extract_signal_matches_from_line(clean: str, line_num: int, signals: list, func_name: str | None):
    """Extract all signal access patterns from a single cleaned line."""
    # Rte_Read
    for m in _RTE_READ_RE.finditer(clean):
        signals.append({"function": func_name, "signal_name": m.group("signal"),
                         "signal_module": m.group("module"), "access_type": "read",
                         "rte_call": m.group(0), "line": line_num})

    # Rte_Write
    for m in _RTE_WRITE_RE.finditer(clean):
        signals.append({"function": func_name, "signal_name": m.group("signal"),
                         "signal_module": m.group("module"), "access_type": "write",
                         "rte_call": m.group(0), "line": line_num})

    # RteLite_Read
    for m in _RTELite_READ_RE.finditer(clean):
        signals.append({"function": func_name, "signal_name": m.group("signal"),
                         "signal_module": None, "access_type": "read",
                         "rte_call": m.group(0), "line": line_num})

    # RteLite_Write
    for m in _RTELite_WRITE_RE.finditer(clean):
        signals.append({"function": func_name, "signal_name": m.group("signal"),
                         "signal_module": None, "access_type": "write",
                         "rte_call": m.group(0), "line": line_num})

    # RteComMapping_ReadSignal (GWM_B26 macro → RteLite_Read_<signal>)
    for m in _RTE_MAPPING_READ_RE.finditer(clean):
        signals.append({"function": func_name, "signal_name": m.group("signal"),
                         "signal_module": None, "access_type": "read",
                         "rte_call": m.group(0), "line": line_num})

    # RteComMapping_WriteSignal (GWM_B26 macro → RteLite_Write_<signal>)
    for m in _RTE_MAPPING_WRITE_RE.finditer(clean):
        signals.append({"function": func_name, "signal_name": m.group("signal"),
                         "signal_module": None, "access_type": "write",
                         "rte_call": m.group(0), "line": line_num})


# ── Phase 6: State Machine ─────────────────────────────────────────────

def phase6_state_machine(file_path: Path, functions: list[dict]) -> list[dict]:
    """
    Extract state machine transitions.

    Returns: [{function, target_var, state_value, line}]
    """
    try:
        text = file_path.read_text(encoding="utf-8", errors="replace")
    except (OSError, PermissionError):
        return []

    lines = text.split("\n")
    states = []

    for func in functions:
        for line_num in range(func["start_line"], min(func["end_line"] + 1, len(lines))):
            line = lines[line_num - 1]
            clean = strip_strings_and_comments(line)

            # State assignment: xxx.systemState = VALUE
            for m in _STATE_ASSIGN_RE.finditer(clean):
                states.append({
                    "function": func["name"],
                    "target_var": m.group("target"),
                    "state_value": m.group("value"),
                    "line": line_num,
                })

            # State comparison: if(state == VALUE)
            for m in _STATE_SWITCH_RE.finditer(clean):
                if m.group("comp_val"):
                    states.append({
                        "function": func["name"],
                        "target_var": m.group("state_var"),
                        "state_value": m.group("comp_val"),
                        "line": line_num,
                    })

    return states


# ── Phase 7: Module Binding ────────────────────────────────────────────

def phase7_module_binding(
    functions: list[dict],
    func_keywords: dict[str, list[str]],
) -> list[dict]:
    """
    Bind functions to ADAS modules based on FUNC_KEYWORDS.

    Returns: [{function, module, binding_method}]
    """
    bindings = []
    for func in functions:
        name_lower = func["name"].lower()
        params_lower = (func.get("params") or "").lower()
        combined = f"{name_lower} {params_lower}"

        for module, keywords in func_keywords.items():
            kw_lower = [k.lower() for k in keywords]
            if any(k in combined for k in kw_lower):
                bindings.append({
                    "function": func["name"],
                    "module": module,
                    "binding_method": "keyword",
                })
                break  # first match wins (priority order in FUNC_KEYWORDS)

    return bindings


# ── Phase 9: Calibration Parameters ────────────────────────────────────

def phase9_calibration_params(file_path: Path, rel_path: str) -> list[dict]:
    """
    Extract calibration parameters from header files (paraDefine.h, etc.).

    Returns: [{name, value, type, line, source_file}]
    """
    try:
        text = file_path.read_text(encoding="utf-8", errors="replace")
    except (OSError, PermissionError):
        return []

    lines = text.split("\n")
    params = []

    for i, line in enumerate(lines, 1):
        clean = strip_strings_and_comments(line)

        # #define NAME VALUE
        m = _CALIB_DEFINE_RE.search(clean)
        if m:
            params.append({
                "name": m.group("name"),
                "value": _parse_c_number(m.group("value")),
                "type": "define",
                "line": i,
                "source_file": normalize_path(rel_path),
            })
            continue

        # type name = value;
        m = _CALIB_ASSIGN_RE.search(clean)
        if m:
            name = m.group("name")
            # Only include if it looks like a calibration param (prefixed with f/FGap/Line etc.)
            if name[0].isupper() or name.startswith("f") or name.startswith("F"):
                params.append({
                    "name": name,
                    "value": _parse_c_number(m.group("value")),
                    "type": m.group("type"),
                    "line": i,
                    "source_file": normalize_path(rel_path),
                })

    return params


# ── Phase 10: Behaviour Patterns ───────────────────────────────────────

def phase10_behaviour_patterns(file_path: Path, functions: list[dict]) -> list[dict]:
    """
    Detect behaviour patterns within function bodies.

    Returns: [{function, pattern_type, var_name, line, detail}]
    """
    try:
        text = file_path.read_text(encoding="utf-8", errors="replace")
    except (OSError, PermissionError):
        return []

    lines = text.split("\n")
    patterns = []

    for func in functions:
        body_lines = lines[func["start_line"] - 1 : func["end_line"]]
        body_text = "\n".join(body_lines)

        # HoldRelease: if(cond){var=false/0}
        for m in _HOLD_RELEASE_RE.finditer(body_text):
            var = m.group("var")
            # Find line number
            pos = m.start()
            line_in_body = body_text[:pos].count("\n") + 1
            patterns.append({
                "function": func["name"],
                "pattern_type": "HoldRelease",
                "var_name": var,
                "line": func["start_line"] + line_in_body - 1,
                "detail": m.group(0)[:80],
            })

        # Accumulate: var += dt
        for i, body_line in enumerate(body_lines):
            clean = strip_strings_and_comments(body_line)
            for m in _ACCUMULATE_RE.finditer(clean):
                patterns.append({
                    "function": func["name"],
                    "pattern_type": "Accumulate",
                    "var_name": m.group("var"),
                    "line": func["start_line"] + i,
                    "detail": f"{m.group('var')} += {m.group('dt')}",
                })

        # EdgeTrigger: prev==0 && cur!=0
        for i, body_line in enumerate(body_lines):
            clean = strip_strings_and_comments(body_line)
            for m in _EDGE_TRIGGER_RE.finditer(clean):
                patterns.append({
                    "function": func["name"],
                    "pattern_type": "EdgeTrigger",
                    "var_name": m.group("cur"),
                    "line": func["start_line"] + i,
                    "detail": m.group(0)[:80],
                })

    return patterns
