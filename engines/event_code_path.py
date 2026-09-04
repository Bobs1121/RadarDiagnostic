# -*- coding: utf-8 -*-
"""Build a generic event-to-source investigation path.

This engine is intentionally not a feature rule engine.  It consumes an event
selected by an upstream data/public-runtime tool and a current
``code-index.v1``.  It then projects the source facts into five navigational
layers and delegates copyable breakpoint construction to the existing generic
``code_gdb_plan`` engine.

The layer names (output/handler/situation/target/input) are an investigation
view, not assertions about how a particular project implements a feature.  A
project may expose no clean boundary for one layer; the result records that as
an empty or missing layer with diagnostics.
"""
from __future__ import annotations

import json
import re
from collections import deque
from pathlib import Path
from typing import Any, Mapping

from .code_gdb_plan import build_code_gdb_plan


SCHEMA_VERSION = "event-code-path.v1"
_IDENTIFIER_RE = re.compile(r"\b[A-Za-z_]\w*\b")
_C_KEYWORDS = frozenset({
    "if", "else", "while", "for", "switch", "case", "default", "return",
    "sizeof", "true", "false", "NULL", "const", "static", "void", "int",
    "float", "double", "char", "struct", "enum", "union", "typedef",
})


class EventCodePathError(ValueError):
    """Raised when the event/code context contract cannot be consumed."""


def _load_json(path: str | Path) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EventCodePathError(f"cannot read code artifact {target}: {exc}") from exc
    if not isinstance(value, dict):
        raise EventCodePathError(f"code artifact root must be object: {target}")
    return value


def load_code_index(*, code_index_path: str = "", context_path: str = "") -> dict[str, Any]:
    """Load either a direct index or the index referenced by a context."""
    if code_index_path:
        index = _load_json(code_index_path)
    elif context_path:
        context = _load_json(context_path)
        artifacts = context.get("artifacts", {}) or {}
        path = str(artifacts.get("code_index", ""))
        if not path:
            raise EventCodePathError("code context does not reference code_index")
        index = _load_json(path)
        # ``code-index.v1`` is intentionally a compact query artifact and
        # stores the content snapshot as ``snapshot_hash``.  The enclosing
        # ``code-context.v1`` additionally carries the product/source
        # identity (for example the remote arbe source snapshot and context
        # id).  Preserve that identity when the caller supplies a context;
        # otherwise a freshly derived event path can look version-conflicted
        # even though it was built from the same context snapshot.
        context_source = context.get("source_context", {})
        if isinstance(context_source, Mapping):
            index = dict(index)
            for key in (
                "source_context_id",
                "source_snapshot_hash",
                "project_id",
                "variant_id",
                "coem",
                "vehicle",
                "remote_host",
                "remote_source_root",
                "remote_git_head",
                "algo_git_head",
            ):
                if index.get(key) in (None, "") and context_source.get(key) not in (None, ""):
                    index[key] = context_source.get(key)
    else:
        raise EventCodePathError("code_index_path or context_path is required")
    if index.get("schema_version") != "code-index.v1":
        # The sibling cr60-debug-harness intentionally keeps its source index
        # independent from radarAnalyze's contract and currently emits the
        # same structural fields without a schema_version.  Normalize that
        # boundary in memory; do not rewrite the upstream artifact.
        required_legacy_keys = {"files", "functions", "calls"}
        if not required_legacy_keys.issubset(index):
            raise EventCodePathError(
                f"unsupported code index schema: {index.get('schema_version')}"
            )
        index = {
            **index,
            "schema_version": "code-index.v1",
            "source_schema_version": index.get("schema_version", "legacy-harness-index"),
            "adapter": "cr60-debug-harness-code-index-compat.v1",
        }
    return index


def _rows(index: Mapping[str, Any], key: str) -> list[dict[str, Any]]:
    value = index.get(key, [])
    return [dict(row) for row in value if isinstance(row, Mapping)] if isinstance(value, list) else []


def _functions(index: Mapping[str, Any]) -> list[dict[str, Any]]:
    return _rows(index, "functions")


def _resolve_function(index: Mapping[str, Any], event: Mapping[str, Any]) -> tuple[dict[str, Any] | None, list[str], list[str]]:
    """Resolve a unique real function from explicit event/function signal facts."""
    diagnostics: list[str] = []
    candidates: list[str] = []
    preferred_source_candidates: list[str] = []
    breakpoint_pack = event.get("breakpoint_pack")
    if isinstance(breakpoint_pack, Mapping):
        breakpoints = breakpoint_pack.get("breakpoints", [])
        if isinstance(breakpoints, list):
            for row in breakpoints:
                if not isinstance(row, Mapping):
                    continue
                function_name = str(row.get("function", "") or "").strip()
                if function_name and str(row.get("id", "")) in {"function-entry", "event-root"}:
                    preferred_source_candidates.append(function_name)
    for key in ("function", "target_function", "code_function", "handler_function"):
        value = str(event.get(key, "") or "").strip()
        if value:
            candidates.append(value)
    signal = str(event.get("output_signal", event.get("signal", "")) or "").strip()
    if signal:
        for row in _rows(index, "signals"):
            if str(row.get("signal_name", row.get("name", ""))) == signal:
                function = str(row.get("function", "") or "").strip()
                if function:
                    candidates.append(function)
    candidates = list(dict.fromkeys(preferred_source_candidates + candidates))
    functions = _functions(index)
    names = {str(row.get("name", "")): row for row in functions}
    preferred_matches = [name for name in preferred_source_candidates if name in names]
    if len(set(preferred_matches)) == 1:
        selected = preferred_matches[0]
        return names[selected], [selected], diagnostics
    matched = [name for name in candidates if name in names]
    if not matched:
        if candidates:
            diagnostics.append("function_not_found:" + ",".join(candidates))
        else:
            diagnostics.append("event_has_no_function_or_output_signal")
        return None, [], diagnostics
    if len(set(matched)) > 1:
        diagnostics.append("ambiguous_function:" + ",".join(matched))
        return None, matched, diagnostics
    return names[matched[0]], matched, diagnostics


def _callers(index: Mapping[str, Any], function: str) -> list[str]:
    calls = index.get("calls", {})
    if not isinstance(calls, Mapping):
        return []
    return sorted(
        str(caller) for caller, callees in calls.items()
        if isinstance(callees, list) and function in {str(item) for item in callees}
    )


def _callees(index: Mapping[str, Any], function: str) -> list[str]:
    calls = index.get("calls", {})
    if not isinstance(calls, Mapping):
        return []
    value = calls.get(function, [])
    return list(dict.fromkeys(str(item) for item in value if str(item).strip())) if isinstance(value, list) else []


def _function_rows(index: Mapping[str, Any], key: str, function: str) -> list[dict[str, Any]]:
    return [row for row in _rows(index, key) if str(row.get("function", "")) == function]


def _execution_chain_functions(
    index: Mapping[str, Any],
    *,
    root: str,
    callers: list[str],
    callees: list[str],
) -> list[tuple[str, str]]:
    """Return a bounded source call-path candidate list in call order.

    The code index does not contain a runtime branch trace.  This therefore
    deliberately returns *candidate* functions with a relation label instead
    of claiming that every branch executed.  Direct caller children before
    ``root`` expose upstream gates (for example a system-state helper), while
    root callees expose target filtering, geometry, handler and output-state
    candidates.  The event/report layer keeps the labels and evaluates only
    values explicitly observed for the selected frame.
    """
    result: list[tuple[str, str]] = []
    seen: set[str] = set()
    post_callers: list[str] = []

    def add(name: Any, relation: str) -> None:
        value = str(name or "").strip()
        if not value or value in seen:
            return
        seen.add(value)
        result.append((value, relation))

    for caller in callers:
        caller_children = _callees(index, caller)
        root_seen = False
        for child in caller_children:
            if child == root:
                root_seen = True
                break
            add(child, "caller_precondition_helper")
        # The index preserves the callee list in source discovery order, but
        # does not carry call-site line numbers.  Put helpers that lead into
        # the event root before the caller's post-call gate conditions; keep
        # the relation explicit rather than claiming an exact branch trace.
        add(caller, "caller_precondition")
        if root_seen:
            post_callers.extend(caller_children[caller_children.index(root) + 1:])
    add(root, "event_root")
    for child in callees:
        add(child, "event_callee")
    for child in post_callers:
        add(child, "caller_postcondition")
    return result


def _execution_condition_chain(
    index: Mapping[str, Any],
    *,
    functions: list[tuple[str, str]],
) -> list[dict[str, Any]]:
    """Attach source conditions to the candidate call path.

    A row carries its original source location plus ``chain_*`` metadata.  It
    remains a candidate until the runtime evidence binds and evaluates it;
    callers with several call sites are not silently converted into one AND
    expression by this projection.
    """
    result: list[dict[str, Any]] = []
    function_orders = {function: order for order, (function, _) in enumerate(functions, start=1)}
    relations = {function: relation for function, relation in functions}
    emitted: set[str] = set()

    def emit(function: str, *, call_site_line: int | None = None) -> None:
        if function in emitted:
            return
        emitted.add(function)
        relation = relations.get(function, "event_callee")
        rows = sorted(
            _function_rows(index, "conditions", function),
            key=lambda row: int(row.get("line") or 0),
        )
        for source_order, condition in enumerate(rows, start=1):
            row = dict(condition)
            row["chain_function"] = function
            row["chain_relation"] = relation
            row["chain_function_order"] = function_orders.get(function, len(function_orders) + 1)
            row["chain_source_order"] = source_order
            if call_site_line is not None:
                row["chain_call_site_line"] = call_site_line
            result.append(row)

    # When source is available, interleave direct callee conditions at the
    # actual call site inside the event root.  This is what keeps a target
    # filter such as a helper's dyn/track gate between the root's input setup
    # and its later ROI/prediction checks instead of appending every helper at
    # the end of the report.
    for function, relation in functions:
        if function in emitted:
            continue
        if relation == "event_root":
            own_rows = sorted(
                _function_rows(index, "conditions", function),
                key=lambda row: int(row.get("line") or 0),
            )
            child_names = [child for child in _callees(index, function) if child in relations]
            child_sites = _function_call_sites(index, function, child_names)
            if child_sites:
                for row in own_rows:
                    row_line = int(row.get("line") or 0)
                    while child_sites and child_sites[0][0] <= row_line:
                        site_line, child = child_sites.pop(0)
                        emit(child, call_site_line=site_line)
                    # Emit the root row without going through the sorted
                    # helper again so the source order remains exact.
                    emitted.add(function)
                    root_row = dict(row)
                    root_row["chain_function"] = function
                    root_row["chain_relation"] = relation
                    root_row["chain_function_order"] = function_orders.get(function, 1)
                    root_row["chain_source_order"] = len([item for item in result if item.get("chain_function") == function]) + 1
                    result.append(root_row)
                while child_sites:
                    site_line, child = child_sites.pop(0)
                    emit(child, call_site_line=site_line)
                continue
        emit(function)
    return result


def _function_call_sites(
    index: Mapping[str, Any],
    function: str,
    callees: list[str],
) -> list[tuple[int, str]]:
    """Find direct callee call lines from the current source when available."""
    if not callees:
        return []
    function_row = next(
        (row for row in _functions(index) if str(row.get("name") or "") == function),
        None,
    )
    source_root_text = str(index.get("source_root") or "").strip()
    source_root = Path(source_root_text)
    file_path = str((function_row or {}).get("file_path") or "").strip()
    if not file_path:
        return []
    source_file = Path(file_path).expanduser()
    if not source_file.is_absolute():
        if not source_root_text:
            return []
        source_file = source_root / source_file
    try:
        lines = source_file.resolve().read_text(encoding="utf-8", errors="replace").splitlines()
    except (OSError, ValueError):
        return []
    start = max(1, int((function_row or {}).get("start_line") or 1))
    end = min(len(lines), int((function_row or {}).get("end_line") or len(lines)))
    patterns = {
        child: re.compile(rf"\b{re.escape(child)}\s*\(")
        for child in callees
    }
    sites: list[tuple[int, str]] = []
    seen: set[str] = set()
    for line_number in range(start, end + 1):
        text = lines[line_number - 1]
        for child in callees:
            if child in seen:
                continue
            if patterns[child].search(text):
                seen.add(child)
                sites.append((line_number, child))
    return sorted(sites)


def _output_signal_rows(index: Mapping[str, Any], function: str) -> list[dict[str, Any]]:
    """Project source-derived Tx mappings relevant to the resolved function."""
    output_mapping = index.get("output_mapping")
    if not isinstance(output_mapping, Mapping):
        mapping_path = str(index.get("output_mapping_path", "") or "").strip()
        if mapping_path:
            try:
                loaded = _load_json(mapping_path)
                output_mapping = loaded if isinstance(loaded, Mapping) else {}
            except EventCodePathError:
                output_mapping = {}
    if not isinstance(output_mapping, Mapping):
        return []
    signal_to_expr = output_mapping.get("signal_to_expr")
    if not isinstance(signal_to_expr, Mapping) or not signal_to_expr:
        return []
    try:
        from .signal_mapper import get_output_signals_for_function

        names = set(get_output_signals_for_function(function, tx_signals=dict(signal_to_expr)))
    except (ImportError, TypeError, ValueError):
        names = set()
    if not names:
        return []
    rows: list[dict[str, Any]] = []
    for item in output_mapping.get("mappings", []) or []:
        if not isinstance(item, Mapping) or str(item.get("can_signal", "")) not in names:
            continue
        rows.append({
            "function": item.get("function") or None,
            "access": "write",
            "signal_name": item.get("can_signal", ""),
            "expression": item.get("expression", ""),
            "direction": "write",
            "file_path": item.get("source_file", ""),
            "line": item.get("line"),
            "source_hash": item.get("source_hash", output_mapping.get("source_hash", "")),
            "source": "source_output_mapping",
        })
    return rows


def _source_ref(row: Mapping[str, Any]) -> dict[str, Any]:
    result = {
        key: row.get(key)
        for key in ("file_path", "line", "column", "start_line", "end_line", "source_hash")
        if row.get(key) not in (None, "")
    }
    if row.get("name"):
        result["symbol"] = row["name"]
    if row.get("function"):
        result["function"] = row["function"]
    return result


def _required_runtime_tokens(
    conditions: list[Mapping[str, Any]],
    variable_rows: list[Mapping[str, Any]],
    event: Mapping[str, Any],
) -> list[str]:
    values = [str(row.get("expression", "")) for row in conditions]
    values.extend(str(row.get("var_name", "")) for row in variable_rows)
    values.extend(str(value) for value in event.get("watch_variables", []) or [])
    tokens: list[str] = []
    for expression in values:
        for token in _IDENTIFIER_RE.findall(expression):
            if token not in _C_KEYWORDS and token not in tokens:
                tokens.append(token)
    return tokens


def _make_layers(
    *,
    function: Mapping[str, Any],
    callers: list[str],
    callees: list[str],
    signals: list[Mapping[str, Any]],
    conditions: list[Mapping[str, Any]],
    variables_read: list[Mapping[str, Any]],
    variables_written: list[Mapping[str, Any]],
    parameters: list[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Project facts into a stable view without claiming semantic ownership."""
    output_nodes = [
        {
            "kind": "signal",
            "name": row.get("signal_name", ""),
            "access": row.get("access", ""),
            "source_ref": _source_ref(row),
            "fact": dict(row),
        }
        for row in signals
        if str(row.get("access", "")) == "write"
    ]
    handler_nodes = [
        {
            "kind": "function",
            "name": function.get("name", ""),
            "role": "event_root",
            "source_ref": _source_ref(function),
        },
        *[
            {"kind": "caller", "name": name, "role": "caller_candidate"}
            for name in callers
        ],
        *[
            {"kind": "callee", "name": name, "role": "callee_candidate"}
            for name in callees
        ],
    ]
    situation_nodes = [
        {
            "kind": "condition",
            "name": row.get("expression", ""),
            "source_ref": _source_ref(row),
            "fact": dict(row),
        }
        for row in conditions
    ] + [
        {
            "kind": "parameter",
            "name": row.get("name", ""),
            "source_ref": _source_ref(row),
            "fact": dict(row),
        }
        for row in parameters
    ]
    target_nodes = [
        {
            "kind": "variable",
            "name": row.get("var_name", ""),
            "access": "read",
            "source_ref": _source_ref(row),
            "fact": dict(row),
        }
        for row in variables_read
        if "." in str(row.get("var_name", ""))
        or "->" in str(row.get("var_name", ""))
        or "obj" in str(row.get("var_name", "")).lower()
    ] + [
        {
            "kind": "variable",
            "name": row.get("var_name", ""),
            "access": "write",
            "source_ref": _source_ref(row),
            "fact": dict(row),
        }
        for row in variables_written
        if "." in str(row.get("var_name", ""))
        or "->" in str(row.get("var_name", ""))
        or "obj" in str(row.get("var_name", "")).lower()
    ]
    target_names = {
        str(node.get("name", ""))
        for node in target_nodes
        if str(node.get("name", ""))
    }
    input_nodes = [
        {
            "kind": "signal",
            "name": row.get("signal_name", ""),
            "access": row.get("access", ""),
            "source_ref": _source_ref(row),
            "fact": dict(row),
        }
        for row in signals
        if str(row.get("access", "")) == "read"
    ] + [
        {
            "kind": "variable",
            "name": row.get("var_name", ""),
            "access": "read",
            "source_ref": _source_ref(row),
            "fact": dict(row),
        }
        for row in variables_read
        if str(row.get("var_name", "")) not in target_names
    ]
    return {
        "output": {"nodes": output_nodes, "status": "available" if output_nodes else "not_found"},
        "handler": {"nodes": handler_nodes, "status": "available"},
        "situation": {"nodes": situation_nodes, "status": "available" if situation_nodes else "not_found"},
        "target": {"nodes": target_nodes, "status": "available" if target_nodes else "not_found"},
        "input": {"nodes": input_nodes, "status": "available" if input_nodes else "not_found"},
    }


def build_event_code_path(
    *,
    event: Mapping[str, Any],
    code_index: Mapping[str, Any],
    source_root: str = "",
    max_call_depth: int = 2,
    max_breakpoints: int = 8,
) -> dict[str, Any]:
    """Build an event-bound, source-traceable investigation artifact."""
    if not isinstance(event, Mapping):
        raise EventCodePathError("event must be an object")
    if code_index.get("schema_version") != "code-index.v1":
        if not {"files", "functions", "calls"}.issubset(code_index):
            raise EventCodePathError("code_index must be code-index.v1")
        code_index = {
            **dict(code_index),
            "schema_version": "code-index.v1",
            "source_schema_version": code_index.get("schema_version", "legacy-harness-index"),
            "adapter": "cr60-debug-harness-code-index-compat.v1",
        }

    function, matched, diagnostics = _resolve_function(code_index, event)
    source_context = {
        "source_root": code_index.get("source_root", source_root),
        "snapshot_hash": code_index.get("snapshot_hash", ""),
        "parser": code_index.get("parser", "unknown"),
    }
    for key in (
        "source_context_id",
        "source_snapshot_hash",
        "project_id",
        "variant_id",
        "coem",
        "vehicle",
        "remote_host",
        "remote_source_root",
        "remote_git_head",
        "algo_git_head",
    ):
        if code_index.get(key) not in (None, ""):
            source_context[key] = code_index[key]
    # Keep the source-index boundary visible in the output.  This matters
    # when the current source context was produced by a sibling harness: the
    # event path can consume it without rewriting it, but the report must not
    # make the adapted artifact look like a native code-index.v1 artifact.
    for key in ("source_schema_version", "adapter"):
        if code_index.get(key) not in (None, ""):
            source_context[key] = code_index[key]
    base = {
        "schema_version": SCHEMA_VERSION,
        "event": dict(event),
        "source_context": source_context,
        "resolution": {"candidate_functions": matched},
        "diagnostics": diagnostics,
        "layers": {},
        "breakpoint_groups": [],
        "required_runtime_tokens": [],
        "static_evaluation": {
            "status": "not_evaluated",
            "reason": "event does not carry a runtime value map",
            "conditions": [],
        },
    }
    if function is None:
        base["status"] = "blocked"
        return base

    function_name = str(function.get("name", ""))
    callers = _callers(code_index, function_name)
    callees = _callees(code_index, function_name)
    # Keep the event path bounded; the full graph remains in code-index.
    if max_call_depth <= 1:
        callees = callees[: max(1, int(max_breakpoints))]
    else:
        queue: deque[tuple[str, int]] = deque((name, 1) for name in callees)
        seen = set(callees)
        while queue:
            current, depth = queue.popleft()
            if depth >= max(1, int(max_call_depth)):
                continue
            for child in _callees(code_index, current):
                if child not in seen:
                    seen.add(child)
                    queue.append((child, depth + 1))
        callees = [name for name in _callees(code_index, function_name) if name in seen]
        for name in sorted(seen):
            if name not in callees:
                callees.append(name)

    reads = _function_rows(code_index, "variables_read", function_name)
    writes = _function_rows(code_index, "variables_written", function_name)
    signals = _function_rows(code_index, "signals", function_name)
    mapped_output_rows = _output_signal_rows(code_index, function_name)
    seen_signal_names = {
        str(row.get("signal_name") or row.get("name") or "")
        for row in signals
        if str(row.get("signal_name") or row.get("name") or "")
    }
    signals.extend(
        row for row in mapped_output_rows
        if str(row.get("signal_name") or "") not in seen_signal_names
    )
    conditions = _function_rows(code_index, "conditions", function_name)
    execution_functions = _execution_chain_functions(
        code_index,
        root=function_name,
        callers=callers,
        callees=callees,
    )
    condition_chain = _execution_condition_chain(code_index, functions=execution_functions)
    chain_reads = [
        row for function, _ in execution_functions
        for row in _function_rows(code_index, "variables_read", function)
    ]
    chain_writes = [
        row for function, _ in execution_functions
        for row in _function_rows(code_index, "variables_written", function)
    ]
    condition_text = " ".join(str(row.get("expression", "")) for row in conditions)
    parameter_names = {
        token.lower()
        for token in _IDENTIFIER_RE.findall(condition_text)
    }
    parameters = [
        row for row in _rows(code_index, "parameters")
        if str(row.get("name", "")).lower() in parameter_names
        or str(row.get("name", "")) in set(str(x) for x in event.get("parameter_names", []) or [])
    ]
    layers = _make_layers(
        function=function,
        callers=callers,
        callees=callees,
        signals=signals,
        conditions=conditions,
        variables_read=reads,
        variables_written=writes,
        parameters=parameters,
    )
    base["layers"] = layers
    base["resolution"].update({
        "function": dict(function),
        "callers": callers,
        "callees": callees,
        "signals": signals,
        "output_signals": mapped_output_rows,
        "variables_read": reads,
        "variables_written": writes,
        "conditions": conditions,
        "condition_chain": condition_chain,
        "condition_chain_functions": [
            {"function": function, "relation": relation, "order": order}
            for order, (function, relation) in enumerate(execution_functions, start=1)
        ],
        "parameters": parameters,
    })
    base["required_runtime_tokens"] = _required_runtime_tokens(
        condition_chain, chain_reads + chain_writes, event
    )

    frame_scope = event.get("frame_scope") if isinstance(event.get("frame_scope"), Mapping) else None
    object_scope = event.get("object_scope") if isinstance(event.get("object_scope"), Mapping) else None
    watches = [str(item) for item in event.get("watch_variables", []) or [] if str(item).strip()]
    watches.extend(
        str(row.get("var_name", ""))
        for row in chain_reads + chain_writes
        if str(row.get("var_name", "")).strip() and str(row.get("var_name", "")) not in watches
    )
    gdb_plan = build_code_gdb_plan(
        code_index=code_index,
        function_name=function_name,
        condition=str(event.get("condition", "") or ""),
        frame_scope=frame_scope,
        object_scope=object_scope,
        watch_variables=watches[:40],
        source_root=str(code_index.get("source_root", source_root) or source_root),
    )
    if gdb_plan.get("breakpoints"):
        base["breakpoint_groups"].append({
            "id": "event-root",
            "purpose": "event root: verify runtime condition and output-side state",
            "gdb_plan": gdb_plan,
            "source": "code-gdb-plan.v1",
        })
    function_rows = {str(row.get("name", "")): row for row in _functions(code_index)}
    for index, callee in enumerate(callees[: max(0, int(max_breakpoints) - 1)], start=1):
        row = function_rows.get(callee)
        if not row or row.get("start_line") in (None, ""):
            continue
        base["breakpoint_groups"].append({
            "id": f"callee-{index}",
            "purpose": "downstream call candidate; validate after event root",
            "source_ref": _source_ref(row),
            "function": callee,
            "condition": str(event.get("condition", "") or ""),
            "watch_variables": [],
        })
    if event.get("runtime_values"):
        runtime_values = event.get("runtime_values")
        if isinstance(runtime_values, Mapping):
            missing = [token for token in base["required_runtime_tokens"] if token not in runtime_values]
            base["static_evaluation"] = {
                "status": "partial" if missing else "available",
                "conditions": conditions,
                "runtime_values_present": sorted(str(key) for key in runtime_values),
                "missing_tokens": missing,
                "reason": "simple expression evaluator is deliberately not inferred here",
            }
    base["status"] = "ready" if function.get("file_path") and function.get("start_line") else "partial"
    return base


__all__ = [
    "SCHEMA_VERSION",
    "EventCodePathError",
    "build_event_code_path",
    "load_code_index",
]
