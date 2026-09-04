# -*- coding: utf-8 -*-
"""Generate source-bound GDB instructions from a current code index.

The generator is deliberately feature agnostic.  It never assumes FCTA,
FCTB, a particular object type, or a fixed breakpoint.  A caller supplies a
real function/symbol and observation-derived condition; the current source
index resolves the function location and records the variables/calls visible
in that version.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = "code-gdb-plan.v1"


def load_code_index(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"code index root must be an object: {path}")
    return payload


def _as_rows(value: object) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [dict(item) for item in value if isinstance(item, Mapping)]
    return []


def _functions(index: Mapping[str, Any]) -> list[dict[str, Any]]:
    return _as_rows(index.get("functions"))


def _resolve_function(
    index: Mapping[str, Any], function_name: str
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    candidates = [
        row for row in _functions(index) if str(row.get("name", "")) == function_name
    ]
    return (candidates[0] if len(candidates) == 1 else None), candidates


def _variable_rows(index: Mapping[str, Any], key: str, function_name: str) -> list[dict[str, Any]]:
    return [
        row
        for row in _as_rows(index.get(key))
        if str(row.get("function", "")) == function_name
    ]


def _call_names(index: Mapping[str, Any], function_name: str) -> list[str]:
    calls = index.get("calls", {})
    if isinstance(calls, Mapping):
        value = calls.get(function_name, [])
        if isinstance(value, list):
            return [str(item) for item in value if str(item).strip()]
    return [
        str(row.get("callee") or row.get("callee_name"))
        for row in _as_rows(calls)
        if str(row.get("caller") or row.get("caller_name")) == function_name
        and str(row.get("callee") or row.get("callee_name")).strip()
    ]


def _condition_rows(index: Mapping[str, Any], function_name: str) -> list[dict[str, Any]]:
    return [
        row
        for row in _as_rows(index.get("conditions"))
        if str(row.get("function", "")) == function_name
    ]


def _scope_status(
    *,
    resolved: Mapping[str, Any] | None,
    line_was_explicit: bool,
    watch_variables: list[str],
    condition: str,
    object_scope: Mapping[str, Any] | None,
) -> tuple[str, list[str]]:
    if line_was_explicit:
        return "caller_selected_line", []
    signature = str((resolved or {}).get("signature", ""))
    parameter_names = set(
        re.findall(r"\b[A-Za-z_]\w*\s*(?=[,)])", signature.split("(", 1)[-1])
    )
    expressions = list(watch_variables)
    if condition:
        expressions.append(condition)
    if isinstance(object_scope, Mapping):
        expressions.append(str(object_scope.get("expression", "")))
    roots = {
        match
        for expression in expressions
        for match in re.findall(r"\b[A-Za-z_]\w*", expression)
    }
    # A source expression rooted at a function parameter is valid at entry;
    # every other root may be a local/global whose initialization point is not
    # proven by a function-start line.  Do not classify it as invalid—surface
    # the exact validation action instead.
    unresolved = sorted(root for root in roots if root not in parameter_names)
    if unresolved:
        return "requires_source_line_validation", [
            "function-entry breakpoint does not prove scope/initialization for: "
            + ", ".join(unresolved)
        ]
    return "function_entry_scope_proven", []


def _join_condition(
    *,
    condition: str,
    frame_scope: Mapping[str, Any] | None,
    object_scope: Mapping[str, Any] | None,
) -> tuple[str, list[str]]:
    parts: list[str] = []
    provenance: list[str] = []
    if str(condition or "").strip():
        parts.append(str(condition).strip())
        provenance.append("caller.condition")
    if isinstance(frame_scope, Mapping):
        variable = str(frame_scope.get("variable", "")).strip()
        start = frame_scope.get("start")
        end = frame_scope.get("end")
        if variable and start is not None and end is not None:
            parts.append(f"{variable} >= {start} && {variable} <= {end}")
            provenance.append("caller.frame_scope")
        elif variable and frame_scope.get("equals") is not None:
            parts.append(f"{variable} == {frame_scope.get('equals')}")
            provenance.append("caller.frame_scope")
    if isinstance(object_scope, Mapping):
        expression = str(object_scope.get("expression", "")).strip()
        if expression and object_scope.get("equals") is not None:
            parts.append(f"{expression} == {object_scope.get('equals')}")
            provenance.append("caller.object_scope")
    # The same fact may arrive through two views of one event (for example,
    # an explicit condition and an object-scope selector). Keep the generated
    # condition copyable and readable instead of repeating an identical clause.
    unique_parts: list[str] = []
    unique_provenance: list[str] = []
    for part, origin in zip(parts, provenance):
        if part in unique_parts:
            continue
        unique_parts.append(part)
        unique_provenance.append(origin)
    return " && ".join(f"({part})" for part in unique_parts), unique_provenance


def _location(file_path: str, line: Any) -> str:
    if not file_path or line in (None, ""):
        return ""
    return f"{file_path}:{int(line)}"


def build_code_gdb_plan(
    *,
    code_index: Mapping[str, Any],
    function_name: str = "",
    source_file: str = "",
    line: int | None = None,
    condition: str = "",
    frame_scope: Mapping[str, Any] | None = None,
    object_scope: Mapping[str, Any] | None = None,
    watch_variables: list[str] | None = None,
    auto_continue: bool = False,
    backtrace_depth: int = 12,
    source_root: str = "",
) -> dict[str, Any]:
    """Resolve a source location and produce generic, copyable GDB commands."""
    function = str(function_name or "").strip()
    source = dict(code_index)
    resolved, same_name = _resolve_function(source, function) if function else (None, [])
    diagnostics: list[str] = []
    if function and len(same_name) > 1:
        diagnostics.append(f"ambiguous_function:{function}:{len(same_name)}")
    if function and not same_name:
        diagnostics.append(f"function_not_found:{function}")
    if function and not resolved:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "blocked",
            "query": {"function": function},
            "source_context": {
                "source_root": source.get("source_root", source_root),
                "snapshot_hash": source.get("snapshot_hash", ""),
            },
            "diagnostics": diagnostics,
            "breakpoints": [],
            "gdb_commands": [],
        }

    resolved_file = str(source_file or (resolved or {}).get("file_path", "")).strip()
    resolved_line = line if line is not None else (resolved or {}).get("start_line")
    if not resolved_file or resolved_line in (None, ""):
        diagnostics.append("source_location_missing")
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "blocked",
            "query": {"function": function, "source_file": source_file, "line": line},
            "source_context": {
                "source_root": source.get("source_root", source_root),
                "snapshot_hash": source.get("snapshot_hash", ""),
            },
            "diagnostics": diagnostics,
            "breakpoints": [],
            "gdb_commands": [],
        }

    resolved_condition, condition_sources = _join_condition(
        condition=condition,
        frame_scope=frame_scope,
        object_scope=object_scope,
    )
    watches = [str(item).strip() for item in (watch_variables or []) if str(item).strip()]
    read_rows = _variable_rows(source, "variables_read", function) if function else []
    write_rows = _variable_rows(source, "variables_written", function) if function else []
    known_variable_names = sorted(
        {
            str(row.get("var_name") or row.get("name", ""))
            for row in read_rows + write_rows
            if str(row.get("var_name") or row.get("name", "")).strip()
        }
    )
    location = _location(resolved_file, resolved_line)
    scope_status, scope_diagnostics = _scope_status(
        resolved=resolved,
        line_was_explicit=line is not None,
        watch_variables=watches,
        condition=condition,
        object_scope=object_scope,
    )
    breakpoint = {
        "id": "bp-1",
        "function": function,
        "file": resolved_file,
        "line": int(resolved_line),
        "location": location,
        "condition": resolved_condition,
        "condition_sources": condition_sources,
        "watch_variables": watches,
        "location_source": "caller_line" if line is not None else "function_start_line",
        "scope_status": scope_status,
        "scope_note": (
            "function-entry locals may be uninitialized; use an explicit downstream "
            "source line when a local variable is required"
        ),
    }
    commands: list[str] = ["set pagination off", "set breakpoint pending on"]
    if source_root:
        commands.append(f"directory {source_root}")
    break_command = f"break {location}"
    if resolved_condition:
        break_command += f" if {resolved_condition}"
    commands.append(break_command)
    commands.extend(["bt " + str(max(1, int(backtrace_depth))), "info args", "info locals"])
    commands.extend(f"p {item}" for item in watches)
    if auto_continue:
        commands.append("continue")
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "ready",
        "query": {
            "function": function,
            "source_file": source_file,
            "line": line,
            "condition": condition,
            "frame_scope": dict(frame_scope or {}),
            "object_scope": dict(object_scope or {}),
        },
        "source_context": {
            "source_root": source.get("source_root", source_root),
            "snapshot_hash": source.get("snapshot_hash", ""),
            "parser": source.get("parser", "unknown"),
        },
        "resolution": {
            "function": resolved or {},
            "calls": _call_names(source, function) if function else [],
            "variables_read": read_rows,
            "variables_written": write_rows,
            "known_variable_names": known_variable_names,
            "conditions": _condition_rows(source, function) if function else [],
        },
        "breakpoints": [breakpoint],
        "gdb_commands": commands,
        "diagnostics": diagnostics
        + scope_diagnostics
        + [
            "GDB commands are generated from caller observations and current source index; no feature-specific breakpoint is built in.",
            "The GDB service must validate source/binary identity before execution.",
        ],
    }


__all__ = ["SCHEMA_VERSION", "build_code_gdb_plan", "load_code_index"]
