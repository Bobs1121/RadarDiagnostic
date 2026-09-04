# -*- coding: utf-8 -*-
"""Build a provenance-bound, feature-neutral runtime debug plan.

The plan is intentionally a *planner*, not an executor.  It consumes the
current Sprint1 bundle and optional preflight result, validates the facts that
must be true before GDB/replay can run, and emits the exact breakpoint pack
that the current source analysis produced.  It never invents a breakpoint or
turns a time-aligned frame into an exact CAN frame.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping

from .gdb_service import validate_gdb_commands


SCHEMA_VERSION = "runtime-debug-plan.v1"


def load_json_object(path: str | Path, *, label: str) -> dict[str, Any]:
    target = Path(path).expanduser()
    if not target.exists():
        raise FileNotFoundError(f"{label}_not_found:{target}")
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label}_invalid:{type(exc).__name__}:{target}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label}_must_be_object:{target}")
    return value


def _as_int(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value in (None, ""):
        return None
    if str(value).strip().lower() in {"true", "1", "yes", "on"}:
        return True
    if str(value).strip().lower() in {"false", "0", "no", "off"}:
        return False
    return None


def _fingerprint(value: Mapping[str, Any]) -> str:
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _event_frame_ids(event: Mapping[str, Any]) -> set[int]:
    result: set[int] = set()
    replay = event.get("replay_plan", {}) or {}
    precheck = event.get("frame_precheck", {}) or {}
    for value in (
        replay.get("target_frame_id"),
        precheck.get("alarm_first_frame_id"),
        event.get("threshold_crossing_frame"),
        event.get("first_on_frame"),
    ):
        number = _as_int(value)
        if number is not None:
            result.add(number)
    for frame in event.get("frame_evidence", []) or []:
        if isinstance(frame, Mapping):
            number = _as_int(frame.get("frame_id"))
            if number is not None:
                result.add(number)
    return result


def _select_event(bundle: Mapping[str, Any], event_id: str, event_index: int) -> tuple[dict[str, Any] | None, list[str]]:
    events = [dict(item) for item in bundle.get("alarm_events", []) or [] if isinstance(item, Mapping)]
    diagnostics: list[str] = []
    if event_id:
        matches = [item for item in events if str(item.get("event_id", "")) == str(event_id)]
        if len(matches) == 1:
            return matches[0], diagnostics
        if len(matches) > 1:
            diagnostics.append(f"ambiguous_event_id:{event_id}:{len(matches)}")
        else:
            diagnostics.append(f"event_not_found:{event_id}")
        return None, diagnostics
    if not events:
        return None, ["bundle_has_no_alarm_events"]
    if event_index < 0 or event_index >= len(events):
        return None, [f"event_index_out_of_range:{event_index}:{len(events)}"]
    return events[event_index], diagnostics


def _bundle_source(bundle: Mapping[str, Any], explicit: Mapping[str, Any] | None) -> dict[str, Any]:
    source_context = bundle.get("source_context", {}) or {}
    provenance = bundle.get("provenance", {}) or {}
    result: dict[str, Any] = {}
    if isinstance(source_context, Mapping):
        result.update({
            "source_context_id": source_context.get("source_context_id"),
            "source_snapshot_hash": source_context.get("source_snapshot_hash")
            or (source_context.get("identity", {}) or {}).get("source_snapshot_hash"),
            "code_index_hash": source_context.get("code_index_hash"),
            "status": source_context.get("status"),
            "identity": deepcopy(dict(source_context.get("identity", {}) or {})),
        })
    if isinstance(provenance, Mapping):
        result.setdefault("source_context_id", provenance.get("source_context_id"))
        result.setdefault("source_snapshot_hash", provenance.get("source_snapshot_hash"))
        result["data_fingerprint"] = provenance.get("data_fingerprint")
        result["bag"] = provenance.get("bag_path") or provenance.get("bag")
    if isinstance(explicit, Mapping):
        # Explicit context is allowed to add/confirm facts but is not allowed
        # to silently replace the bundle identity; conflicts are reported by
        # the readiness gate below.
        result["explicit"] = deepcopy(dict(explicit))
    if not result.get("data_fingerprint") and result.get("bag"):
        result["data_fingerprint"] = "bag-path:" + str(result["bag"]).replace("\\", "/").rstrip("/").lower()
    return {key: value for key, value in result.items() if value not in (None, "")}


def _preflight_value(preflight: Mapping[str, Any], *paths: str) -> Any:
    current: Any = preflight
    for path in paths:
        if not isinstance(current, Mapping):
            return None
        current = current.get(path)
    return current


def _gate(name: str, status: str, *, reason: str = "", evidence: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return {
        "name": name,
        "status": status,
        "reason": reason,
        "evidence": deepcopy(dict(evidence or {})),
    }


def _target_identity(event: Mapping[str, Any]) -> dict[str, Any]:
    selected = event.get("selected_target", {}) or {}
    raw = selected.get("raw", {}) if isinstance(selected, Mapping) else {}
    raw = raw if isinstance(raw, Mapping) else {}
    return {
        "obj_id": selected.get("obj_id") if isinstance(selected, Mapping) else None,
        "raw_sgu_index": raw.get("input_index", raw.get("raw_sgu_index")),
        "algorithm_object_index": raw.get("algorithm_object_index"),
        "objectlist_index": raw.get("trc_index_i", raw.get("objectlist_index")),
        "source_layer": raw.get("source_layer", "unknown"),
        "algorithm_object_index_confidence": raw.get("algorithm_object_index_confidence", "not_available"),
        "candidate_count": len(event.get("target_candidates", []) or []),
    }


def _radar_context(
    bundle: Mapping[str, Any],
    event: Mapping[str, Any],
    preflight: Mapping[str, Any],
) -> dict[str, Any]:
    """Resolve radar installation metadata from current context/config only."""
    radar_id = _as_int(event.get("radar_id"))
    source_context = bundle.get("source_context", {}) or {}
    identity = source_context.get("identity", {}) if isinstance(source_context, Mapping) else {}
    arbe = identity.get("arbe", {}) if isinstance(identity, Mapping) else {}
    configured = arbe.get(f"radar{radar_id}", {}) if isinstance(arbe, Mapping) and radar_id is not None else {}
    configured = dict(configured) if isinstance(configured, Mapping) else {}
    resolved = _preflight_value(preflight, "configuration", "resolved")
    resolved = resolved if isinstance(resolved, Mapping) else {}
    index = radar_id - 1 if radar_id is not None else -1
    for field in ("radar_pos", "orientation", "yaw_in_degrees", "radar_x_offset", "radar_y_offset", "radar_z_offset"):
        if field in configured or index < 0:
            continue
        values = resolved.get(field)
        if isinstance(values, list) and index < len(values):
            configured[field] = values[index]
    if radar_id is not None:
        configured.setdefault("radar_id", radar_id)
    return configured


def _normalise_breakpoints(event: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    pack = event.get("breakpoint_pack", {}) or {}
    if not isinstance(pack, Mapping):
        return [], ["breakpoint_pack_invalid"]
    rows: list[dict[str, Any]] = []
    diagnostics: list[str] = []
    for index, item in enumerate(pack.get("breakpoints", []) or []):
        if not isinstance(item, Mapping):
            diagnostics.append(f"breakpoint_invalid:{index}")
            continue
        location = item.get("location", {}) or {}
        if not isinstance(location, Mapping):
            location = {}
        function = str(item.get("function", "")).strip()
        file_path = str(location.get("file", item.get("file", "")) or "").strip()
        line = _as_int(location.get("line", item.get("line")))
        condition = str(item.get("condition", "")).strip()
        if not function or not file_path or line is None:
            diagnostics.append(f"breakpoint_location_missing:{index}")
            continue
        row = {
            "id": item.get("id", f"bp-{index + 1}"),
            "function": function,
            "location": {"file": file_path, "line": line, "confidence": location.get("confidence")},
            "condition": condition,
            "watch": list(item.get("watch", item.get("watch_variables", [])) or []),
            "scope_status": item.get("scope_status", "not_reported"),
            "scope_note": item.get("scope_note", ""),
            "purpose": item.get("purpose", ""),
            "copy_text": item.get("copy_text", ""),
            "source_index_hash": item.get("source_index_hash", ""),
        }
        rows.append(row)
    if not rows:
        diagnostics.append("no_valid_breakpoints")
    return rows, diagnostics


def _scope_condition_for_source_line(
    scope_condition: str,
    event_code_path: Mapping[str, Any],
    file_path: str,
    line: int,
    *,
    start_line: int,
    end_line: int | None,
) -> str:
    """Drop scope clauses that refer to locals not declared at this line."""
    if not scope_condition:
        return ""
    source_context = event_code_path.get("source_context") if isinstance(event_code_path.get("source_context"), Mapping) else {}
    source_root = str(source_context.get("source_root") or "").strip()
    if not source_root:
        return scope_condition
    source_file = Path(file_path).expanduser()
    if not source_file.is_absolute():
        source_file = Path(source_root).expanduser() / source_file
    try:
        source_file = source_file.resolve()
        source_file.relative_to(Path(source_root).expanduser().resolve())
        lines = source_file.read_text(encoding="utf-8", errors="replace").splitlines()
    except (OSError, ValueError):
        return scope_condition
    first = max(0, start_line - 1)
    last = min(len(lines), end_line or len(lines))
    token_re = re.compile(r"\b[A-Za-z_]\w*(?:(?:->|\.)[A-Za-z_]\w*|\[[^\]]+\])*")
    clauses = [item.strip() for item in scope_condition.split("&&") if item.strip()]
    retained: list[str] = []
    for clause in clauses:
        invalid = False
        for token in token_re.findall(clause):
            root = re.split(r"->|\.|\[", token, maxsplit=1)[0]
            if root in {"frame_counter", "frameID"}:
                continue
            declaration_re = re.compile(
                rf"\b(?:[A-Za-z_]\w*\s+)+(?:[*&]\s*)?{re.escape(root)}\s*="
            )
            declarations = [
                index + 1
                for index, source_line in enumerate(lines[first:last], start=first)
                if declaration_re.search(source_line)
            ]
            if declarations and min(declarations) > line:
                invalid = True
                break
        if not invalid:
            retained.append(clause)
    return " && ".join(retained)


def _source_condition_breakpoints(
    event: Mapping[str, Any],
    event_code_path: Mapping[str, Any] | None,
    *,
    max_items: int = 8,
) -> list[dict[str, Any]]:
    """Create post-assignment source-line probes from the current code path.

    The sibling harness breakpoint pack usually stops at an entry/handler. A
    source condition line is a better place to capture computed locals such as
    TTC/ROI counters after their preceding helper call. This helper only
    projects explicit condition rows from ``event_code_path``; it does not
    infer a feature or invent a source location.
    """
    if not isinstance(event_code_path, Mapping):
        return []
    resolution = event_code_path.get("resolution") if isinstance(event_code_path.get("resolution"), Mapping) else {}
    function = resolution.get("function") if isinstance(resolution.get("function"), Mapping) else {}
    function_name = str(function.get("name") or "").strip()
    function_file = str(function.get("file_path") or "").strip()
    start_line = _as_int(function.get("start_line")) or 0
    end_line = _as_int(function.get("end_line"))
    if not function_name or not function_file:
        return []
    scope_condition = ""
    pack = event.get("breakpoint_pack") if isinstance(event.get("breakpoint_pack"), Mapping) else {}
    for item in pack.get("breakpoints", []) or []:
        if not isinstance(item, Mapping):
            continue
        candidate_function = str(item.get("function") or "").strip()
        condition = str(item.get("condition") or "").strip()
        if condition and candidate_function in {function_name, ""}:
            scope_condition = condition
            break
    if not scope_condition:
        replay = event.get("replay_plan") if isinstance(event.get("replay_plan"), Mapping) else {}
        target_frame = _as_int(replay.get("target_frame_id"))
        if target_frame is not None:
            scope_condition = f"frame_counter == {target_frame}"

    token_re = re.compile(r"\b[A-Za-z_]\w*(?:(?:->|\.)[A-Za-z_]\w*|\[[^\]]+\])*")
    ignored = {
        "if", "else", "true", "false", "fabs", "fabsf", "abs", "min", "max",
        "float", "double", "int", "bool", "uint8_t", "uint16_t", "uint32_t",
        "int8_t", "int16_t", "int32_t", "int64_t", "size_t", "const", "static",
    }
    conditions = [
        row for row in (resolution.get("condition_chain") or resolution.get("conditions", [])) or []
        if isinstance(row, Mapping)
    ]
    candidates: list[dict[str, Any]] = []
    seen_lines: set[tuple[str, str, int]] = set()
    for row in conditions:
        row_function = str(row.get("chain_function") or row.get("function") or function_name).strip()
        file_path = str(row.get("file_path") or function_file).strip()
        line = _as_int(row.get("line"))
        expression = str(row.get("expression") or "").strip()
        if not file_path or line is None:
            continue
        # A breakpoint on the first `if` line is stable for a multiline C
        # condition; continuation rows would duplicate the same stop.  The
        # code index may store the keyword separately as ``condition_kind``.
        condition_kind = str(row.get("condition_kind") or "").lower()
        if not condition_kind and not re.match(r"^(?:if|while|for|switch)\b", expression):
            continue
        key = (row_function, file_path, line)
        if key in seen_lines:
            continue
        seen_lines.add(key)
        line_scope_condition = _scope_condition_for_source_line(
            scope_condition,
            event_code_path,
            file_path,
            line,
            start_line=start_line if row_function == function_name else 0,
            end_line=end_line if row_function == function_name else None,
        )
        watches = []
        for token in token_re.findall(expression):
            if token in ignored or token.isdigit() or token in watches:
                continue
            watches.append(token)
        candidates.append({
            "id": f"source-condition-{row_function}-{line}",
            "function": row_function,
            "location": {"file": file_path, "line": line, "confidence": row.get("confidence")},
            "condition": line_scope_condition,
            "source_expression": expression,
            "watch": watches[:24],
            "scope_status": "source_condition_line",
            "scope_note": "captures locals at the current source condition after preceding assignments/helpers",
            "purpose": "capture source-condition operands and computed locals",
            "source_ref": {
                key: row.get(key)
                for key in ("file_path", "line", "end_line", "source_hash", "confidence")
                if row.get(key) not in (None, "")
            },
            "phase": "source_condition",
            "chain_relation": row.get("chain_relation"),
        })
    def probe_score(item: Mapping[str, Any]) -> int:
        expression = str(item.get("source_expression") or item.get("condition") or "").lower()
        score = 0
        if "systemstate" in expression:
            score = max(score, 125)
        if re.search(r"(?:->|\.)dynflg\b", expression):
            score = max(score, 114)
        if any(marker in expression for marker in ("ttm", "ttc", "inter", "ddci", "threshold")):
            score = max(score, 115)
        if "enable" in expression:
            score = max(score, 110)
        if any(marker in expression for marker in ("warningnum", "warning", "flag", "output")):
            score = max(score, 105)
        if any(marker in expression for marker in ("carspd", "speed", "vel", "gear", "yaw", "accel")):
            score = max(score, 90)
        if any(marker in expression for marker in ("roi", "polygon")):
            score = max(score, 80)
        return score

    # Keep at least one high-value probe for each source-chain function before
    # filling remaining slots in source order.  The score is derived from the
    # current expression; it does not name or assume a particular feature.
    limit = max(0, int(max_items))
    selected: list[dict[str, Any]] = []
    seen_functions: set[str] = set()
    best_by_function: dict[str, dict[str, Any]] = {}
    for item in candidates:
        name = str(item.get("function") or "")
        current = best_by_function.get(name)
        if current is None or (probe_score(item), -len(selected)) > (probe_score(current), -len(selected)):
            best_by_function[name] = item
    ordered_best: list[dict[str, Any]] = []
    if function_name in best_by_function:
        ordered_best.append(best_by_function[function_name])
    ordered_best.extend(
        item for item in candidates
        if best_by_function.get(str(item.get("function") or "")) is item
        and item not in ordered_best
    )
    for item in ordered_best:
        name = str(item.get("function") or "")
        if name not in seen_functions:
            seen_functions.add(name)
            selected.append(item)
        if len(selected) >= limit:
            return selected[:limit]
    for item in candidates:
        if item not in selected:
            selected.append(item)
        if len(selected) >= limit:
            break
    return selected


def validate_runtime_debug_plan(payload: Mapping[str, Any]) -> list[str]:
    """Validate the stable plan contract without executing anything."""
    errors: list[str] = []
    if not isinstance(payload, Mapping):
        return ["runtime_debug_plan_must_be_object"]
    if payload.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version_mismatch:{payload.get('schema_version', '')}")
    if payload.get("status") not in {"ready", "partial", "blocked", "failed"}:
        errors.append("status_invalid")
    if payload.get("execution_status") not in {"ready", "approval_required", "blocked"}:
        errors.append("execution_status_invalid")
    for key in ("event", "replay", "target", "readiness"):
        if not isinstance(payload.get(key), Mapping):
            errors.append(f"{key}_missing_or_invalid")
    for key in ("breakpoints", "gdb_commands", "capture_fields"):
        if not isinstance(payload.get(key), list):
            errors.append(f"{key}_missing_or_invalid")
    readiness = payload.get("readiness", {})
    if isinstance(readiness, Mapping):
        if readiness.get("status") not in {"ready", "partial", "blocked"}:
            errors.append("readiness.status_invalid")
        if not isinstance(readiness.get("gates", []), list):
            errors.append("readiness.gates_invalid")
    return errors


def _capture_fields(breakpoints: list[Mapping[str, Any]], event: Mapping[str, Any]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for breakpoint in breakpoints:
        scope = str(breakpoint.get("function", ""))
        phase = "during"
        for value in breakpoint.get("watch", []) or []:
            token = str(value or "").strip()
            if not token or token in seen:
                continue
            seen.add(token)
            result.append({
                "token": token,
                "scope": scope,
                "phase": phase,
                "source": "breakpoint_pack.watch",
            })
    selected = event.get("selected_target", {}) or {}
    raw = selected.get("raw", {}) if isinstance(selected, Mapping) else {}
    raw = raw if isinstance(raw, Mapping) else {}
    # These are not feature rules: they are identity fields already present in
    # the event, needed to relate a GDB stop to its bag object.
    for token in ("frame_counter", "i", "sObj->objID"):
        if token in seen:
            continue
        if token == "i" and raw.get("algorithm_object_index") is None:
            continue
        seen.add(token)
        result.append({"token": token, "scope": "identity", "phase": "during", "source": "event_identity"})
    return result


def build_runtime_debug_plan(
    bundle: Mapping[str, Any],
    *,
    event_id: str = "",
    event_index: int = 0,
    runtime_mode: str = "auto",
    preflight: Mapping[str, Any] | None = None,
    source_context: Mapping[str, Any] | None = None,
    binary_context: Mapping[str, Any] | None = None,
    permissions: Mapping[str, Any] | None = None,
    event_code_path: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a plan and readiness gates without starting replay or GDB."""
    diagnostics: list[str] = []
    event, event_diagnostics = _select_event(bundle, event_id, int(event_index))
    diagnostics.extend(event_diagnostics)
    if event is None:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "blocked",
            "execution_status": "blocked",
            "event": {"event_id": event_id, "event_index": event_index},
            "breakpoints": [],
            "gdb_commands": [],
            "vscode_handoff": {},
            "capture_fields": [],
            "readiness": {"status": "blocked", "gates": [], "blocking_gates": ["event"]},
            "diagnostics": diagnostics,
        }

    preflight_obj = dict(preflight or {}) if isinstance(preflight, Mapping) else {}
    source = _bundle_source(bundle, source_context)
    replay = event.get("replay_plan", {}) or {}
    warmup = replay.get("warmup", {}) or {}
    target = _target_identity(event)
    radar = _radar_context(bundle, event, preflight_obj)
    target_frame = _as_int(replay.get("target_frame_id"))
    frame_source = str(replay.get("target_frame_source", "") or "")
    frame_confidence = str(
        (event.get("frame_precheck", {}) or {}).get("alarm_first_frame_confidence", "")
        or (event.get("frame_precheck", {}) or {}).get("target_frame_confidence", "")
        or ""
    )
    strategy = str(replay.get("strategy", "") or "")
    if runtime_mode == "auto":
        runtime_mode = strategy or "unknown"
    breakpoints, breakpoint_diagnostics = _normalise_breakpoints(event)
    diagnostics.extend(breakpoint_diagnostics)
    source_condition_breakpoints = _source_condition_breakpoints(event, event_code_path)
    if source_condition_breakpoints:
        breakpoints.extend(source_condition_breakpoints)
        diagnostics.append(f"source_condition_breakpoints_added:{len(source_condition_breakpoints)}")
    capture_fields = _capture_fields(breakpoints, event)
    breakpoint_pack = event.get("breakpoint_pack", {}) or {}
    gdb_commands = list(breakpoint_pack.get("gdb_commands", []) or []) if isinstance(breakpoint_pack, Mapping) else []
    vscode_handoff = deepcopy(dict(breakpoint_pack.get("vscode_handoff", {}) or {})) if isinstance(breakpoint_pack, Mapping) else {}
    command_errors = validate_gdb_commands(gdb_commands)
    diagnostics.extend(f"gdb_command:{item}" for item in command_errors)

    source_id = str(source.get("source_context_id", "") or "")
    source_hash = str(source.get("source_snapshot_hash", "") or "")
    bag = str(source.get("bag", "") or (bundle.get("case", {}) or {}).get("bag", ""))
    static_status = str(bundle.get("status", "") or "")
    gates: list[dict[str, Any]] = []
    gates.append(_gate(
        "bundle",
        "pass" if static_status in {"ready", "partial"} else "blocked",
        reason="diagnosis bundle is available" if static_status in {"ready", "partial"} else "bundle is not ready",
        evidence={"status": static_status},
    ))
    gates.append(_gate(
        "source_context",
        "pass" if source_id or source_hash else "blocked",
        reason="source context fingerprint is present" if source_id or source_hash else "source context fingerprint is missing",
        evidence={"source_context_id": source_id, "source_snapshot_hash": source_hash},
    ))
    source_identity = source.get("identity", {}) if isinstance(source.get("identity"), Mapping) else {}
    source_dirty = bool(
        source.get("status") == "resolved_dirty"
        or source_identity.get("outer_dirty")
        or source_identity.get("algo_dirty")
    )
    gates.append(_gate(
        "source_cleanliness",
        "warn" if source_dirty else "pass" if source_id or source_hash else "blocked",
        reason="active source context is dirty; build/runtime must be treated as non-reproducible" if source_dirty else "source context is clean" if source_id or source_hash else "source cleanliness cannot be assessed",
        evidence={"status": source.get("status"), "outer_dirty": source_identity.get("outer_dirty"), "algo_dirty": source_identity.get("algo_dirty")},
    ))
    preflight_outer_head = _preflight_value(preflight_obj, "workspace", "outer", "head")
    preflight_algo_head = _preflight_value(preflight_obj, "workspace", "algo_source", "head")
    source_head_mismatches: dict[str, Any] = {}
    if source_identity.get("outer_head") and preflight_outer_head and str(source_identity.get("outer_head")) != str(preflight_outer_head):
        source_head_mismatches["outer_head"] = {"bundle": source_identity.get("outer_head"), "preflight": preflight_outer_head}
    if source_identity.get("algo_head") and preflight_algo_head and str(source_identity.get("algo_head")) != str(preflight_algo_head):
        source_head_mismatches["algo_head"] = {"bundle": source_identity.get("algo_head"), "preflight": preflight_algo_head}
    gates.append(_gate(
        "source_preflight_compatibility",
        "blocked" if source_head_mismatches else "pass" if preflight_outer_head or preflight_algo_head else "warn",
        reason="bundle source heads conflict with current preflight" if source_head_mismatches else "bundle and preflight source heads are compatible" if preflight_outer_head or preflight_algo_head else "preflight source heads were not provided",
        evidence={"mismatches": source_head_mismatches, "bundle_outer_head": source_identity.get("outer_head"), "preflight_outer_head": preflight_outer_head, "bundle_algo_head": source_identity.get("algo_head"), "preflight_algo_head": preflight_algo_head},
    ))
    explicit_source = source.get("explicit", {}) if isinstance(source.get("explicit"), Mapping) else {}
    explicit_mismatches: dict[str, Any] = {}
    for field in ("source_context_id", "source_snapshot_hash"):
        explicit_value = explicit_source.get(field)
        bundle_value = source.get(field)
        if explicit_value not in (None, "") and bundle_value not in (None, "") and str(explicit_value) != str(bundle_value):
            explicit_mismatches[field] = {"bundle": bundle_value, "explicit": explicit_value}
    gates.append(_gate(
        "source_explicit_compatibility",
        "blocked" if explicit_mismatches else "pass" if explicit_source or source_id or source_hash else "blocked",
        reason="explicit source context conflicts with bundle" if explicit_mismatches else "explicit source context is compatible" if explicit_source else "no separate source context was supplied",
        evidence={"mismatches": explicit_mismatches, "explicit": explicit_source},
    ))
    code_evidence = bundle.get("code_evidence", {}) or {}
    runtime_schema = bundle.get("runtime_schema", {}) or {}
    code_hash = code_evidence.get("snapshot_hash") if isinstance(code_evidence, Mapping) else None
    schema_hash = (runtime_schema.get("source_context", {}) or {}).get("source_snapshot_hash") if isinstance(runtime_schema, Mapping) else None
    source_artifact_hash_mismatch = bool(code_hash and schema_hash and str(code_hash) != str(schema_hash))
    gates.append(_gate(
        "source_artifact_compatibility",
        "blocked" if source_artifact_hash_mismatch else "pass" if code_hash or schema_hash else "warn",
        reason="code index and runtime schema fingerprints conflict" if source_artifact_hash_mismatch else "code index/runtime schema fingerprint is present" if code_hash or schema_hash else "code index/runtime schema fingerprint is unavailable",
        evidence={"code_index_hash": code_hash, "runtime_schema_hash": schema_hash},
    ))
    gates.append(_gate(
        "data_binding",
        "pass" if bag else "blocked",
        reason="bag path is bound" if bag else "bag path is missing",
        evidence={"bag": bag},
    ))
    exact_frame_sources = {"recorded_threshold_frame", "recorded_first_on_frame", "runtime_with_frame"}
    frame_status = (
        "pass"
        if target_frame is not None and frame_source in exact_frame_sources and "time_aligned" not in frame_confidence
        else "warn"
        if target_frame is not None
        else "blocked"
    )
    gates.append(_gate(
        "event_frame",
        frame_status,
        reason=(
            "event has a concrete replay frame source"
            if frame_status == "pass"
            else "frame exists but source is time-aligned/unspecified"
            if target_frame is not None
            else "target frame is missing"
        ),
        evidence={"target_frame": target_frame, "frame_source": frame_source, "confidence": frame_confidence},
    ))
    target_status = "pass" if target.get("obj_id") not in (None, "") and target.get("candidate_count", 0) == 1 else "warn" if target.get("obj_id") not in (None, "") else "blocked"
    gates.append(_gate(
        "target_identity",
        target_status,
        reason="one target candidate has an object ID" if target_status == "pass" else "object ID exists but candidates are not unique" if target_status == "warn" else "no unique target object ID",
        evidence=target,
    ))
    strategy_status = "pass" if strategy not in {"", "needs_confirmation", "unknown"} and str(warmup.get("ready", True)).lower() not in {"false", "0"} else "warn" if strategy else "blocked"
    gates.append(_gate(
        "replay_strategy",
        strategy_status,
        reason="replay strategy and warm-up are selected" if strategy_status == "pass" else "replay strategy/warm-up requires confirmation" if strategy_status == "warn" else "replay strategy is missing",
        evidence={"mode": runtime_mode, "strategy": strategy, "warmup": warmup},
    ))

    build_info = _preflight_value(preflight_obj, "build")
    macros = build_info.get("macros", {}) if isinstance(build_info, Mapping) else {}
    if not isinstance(macros, Mapping):
        macros = {}
    if runtime_mode == "sgu_injection":
        hilmodel = macros.get("HILMODEL")
        gates.append(_gate(
            "hilmodel",
            "pass" if str(hilmodel) == "2" else "blocked" if hilmodel not in (None, "") else "warn",
            reason="HILMODEL=2 is confirmed by current preflight" if str(hilmodel) == "2" else "HILMODEL is not 2; SGU injection plan cannot be treated as valid" if hilmodel not in (None, "") else "HILMODEL was not reported by preflight",
            evidence={"HILMODEL": hilmodel, "macros": dict(macros)},
        ))

    binary = dict(binary_context or {}) if isinstance(binary_context, Mapping) else {}
    binary_candidates = _preflight_value(preflight_obj, "build", "binary_candidates") or _preflight_value(preflight_obj, "binary_candidates") or []
    if not isinstance(binary_candidates, list):
        binary_candidates = [binary_candidates] if binary_candidates else []
    binary_fingerprint = (
        binary.get("fingerprint")
        or binary.get("binary_fingerprint")
        or _preflight_value(preflight_obj, "build", "binary_fingerprint")
        or _preflight_value(preflight_obj, "binary", "fingerprint")
    )
    binary_status = "pass" if binary_fingerprint else "warn" if binary_candidates else "blocked"
    gates.append(_gate(
        "binary",
        binary_status,
        reason="binary fingerprint is available" if binary_status == "pass" else "binary candidate exists but identity is not verified" if binary_status == "warn" else "no binary candidate or fingerprint was provided",
        evidence={"candidates": binary_candidates, "fingerprint": binary_fingerprint},
    ))
    gdb_info = _preflight_value(preflight_obj, "gdb")
    gdb_available = _as_bool(gdb_info.get("available")) if isinstance(gdb_info, Mapping) else None
    if gdb_available is None and isinstance(gdb_info, Mapping):
        gdb_available = bool(gdb_info.get("path"))
    gates.append(_gate(
        "gdb",
        "pass" if gdb_available is True else "warn" if not preflight_obj else "blocked",
        reason="GDB is available in preflight" if gdb_available is True else "GDB availability was not confirmed" if not preflight_obj else "preflight did not report usable GDB",
        evidence=dict(gdb_info or {}) if isinstance(gdb_info, Mapping) else {},
    ))
    ptrace_scope = gdb_info.get("ptrace_scope") if isinstance(gdb_info, Mapping) else None
    ptrace_status = (
        "warn"
        if str(ptrace_scope) in {"1", "2"}
        else "pass"
        if str(ptrace_scope) == "0"
        else "not_evaluated"
    )
    gates.append(_gate(
        "gdb_attach_permission",
        ptrace_status,
        reason=(
            "Linux ptrace policy is restricted; formal existing-PID attach requires a permitted process relationship or explicit operator setup"
            if str(ptrace_scope) in {"1", "2"}
            else "Linux ptrace policy is unrestricted"
            if str(ptrace_scope) == "0"
            else "ptrace_scope was not reported; formal attach permission remains unverified"
        ),
        evidence={
            "ptrace_scope": ptrace_scope,
            "attach_mode": gdb_info.get("attach_mode") if isinstance(gdb_info, Mapping) else "",
            "policy_change_allowed": False,
        },
    ))
    gates.append(_gate(
        "gdb_commands",
        "blocked" if command_errors else "pass" if gdb_commands else "warn",
        reason="GDB commands pass the service allowlist" if gdb_commands and not command_errors else "GDB command list contains unsupported/unsafe commands" if command_errors else "no GDB commands were produced",
        evidence={"count": len(gdb_commands), "errors": command_errors},
    ))
    processes = _preflight_value(preflight_obj, "runtime", "processes")
    processes = processes if isinstance(processes, list) else []
    radar_processes = [
        item for item in processes
        if isinstance(item, Mapping) and _as_int(item.get("radar_id")) == _as_int(event.get("radar_id"))
    ]
    process_status = "pass" if len(radar_processes) == 1 else "warn" if not preflight_obj or len(radar_processes) > 1 else "warn"
    gates.append(_gate(
        "process_target",
        process_status,
        reason="one current process matches the event radar" if len(radar_processes) == 1 else "process target must be resolved after bash start/launch-under-GDB",
        evidence={"radar_id": event.get("radar_id"), "matches": radar_processes},
    ))
    approved = bool((permissions or {}).get("approved", False)) if isinstance(permissions, Mapping) else False
    gates.append(_gate(
        "approval",
        "pass" if approved else "warn",
        reason="explicit runtime/GDB approval is present" if approved else "execution remains approval-gated",
        evidence={"approved": approved},
    ))

    blocking = [str(item.get("name")) for item in gates if item.get("status") == "blocked"]
    warnings = [str(item.get("name")) for item in gates if item.get("status") == "warn"]
    if blocking:
        readiness_status = "blocked"
    elif warnings:
        readiness_status = "partial"
    else:
        readiness_status = "ready"
    execution_status = "approval_required" if not blocking and not approved else "ready" if not blocking else "blocked"
    if any(item.get("scope_status") in {"requires_source_line_validation", "not_reported"} for item in breakpoints):
        diagnostics.append("one_or_more_breakpoints_have_scope_validation_risk")
    if target_frame is not None and frame_source in {"nearest_lgu_frame_to_alarm_start", "first_observed_warning_nearest_lgu", "event_frame_id_or_nearest_time"}:
        diagnostics.append("target_frame_is_not_proven_as_can_tx_rising_edge")
    plan_identity = {
        "event_id": event.get("event_id"),
        "event_index": event_index,
        "function": event.get("function"),
        "radar_id": event.get("radar_id"),
        "target_frame": target_frame,
        "target": target,
        "source_context_id": source_id,
        "source_snapshot_hash": source_hash,
        "bag": bag,
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "ready" if readiness_status == "ready" else "partial" if readiness_status == "partial" else "blocked",
        "execution_status": execution_status,
        "plan_fingerprint": _fingerprint(plan_identity),
        "event": {
            "event_id": event.get("event_id"),
            "function": event.get("function"),
            "radar_id": event.get("radar_id"),
            "side": str(event.get("function", "")).rsplit("_", 1)[-1] if "_" in str(event.get("function", "")) else "",
            "target_frame": target_frame,
            "target_frame_source": frame_source,
            "target_frame_confidence": frame_confidence,
            "frame_domain": "frame_counter" if frame_source or target_frame is not None else "not_available",
        },
        "replay": {
            "mode": runtime_mode,
            "strategy": strategy,
            "hilmodel": macros.get("HILMODEL") if isinstance(macros, Mapping) else None,
            "warmup": deepcopy(dict(warmup)) if isinstance(warmup, Mapping) else {},
            "post_window_end_sec": replay.get("post_window_end_sec"),
        },
        "radar": radar,
        "target": target,
        "source_identity": source,
        "binary_identity": {
            "fingerprint": binary_fingerprint,
            "candidates": binary_candidates,
            "preflight": deepcopy(dict(binary)) if binary else {},
        },
        "process_target": {
            "node_pattern": _preflight_value(preflight_obj, "runtime", "node_pattern") or _preflight_value(preflight_obj, "node_pattern"),
            "processes": deepcopy(_preflight_value(preflight_obj, "runtime", "processes") or []),
            "selected_process": deepcopy(radar_processes[0]) if len(radar_processes) == 1 else None,
            "radar_id": event.get("radar_id"),
        },
        "breakpoints": breakpoints,
        "gdb_commands": gdb_commands,
        "gdb_command_validation": {"status": "blocked" if command_errors else "pass" if gdb_commands else "not_available", "errors": command_errors},
        "vscode_handoff": vscode_handoff,
        "capture_fields": capture_fields,
        "readiness": {
            "status": readiness_status,
            "blocking_gates": blocking,
            "warning_gates": warnings,
            "gates": gates,
        },
        "permissions": {
            "approved": approved,
            "requires_approval": True,
            "side_effects": ["replay may publish/consume ROS state", "GDB may stop or perturb the target process"],
        },
        "diagnostics": list(dict.fromkeys(diagnostics)),
        "source_of_breakpoints": {
            "bundle_breakpoint_pack": True,
            "code_snapshot_hash": (bundle.get("code_evidence", {}) or {}).get("snapshot_hash"),
            "runtime_schema_version": (bundle.get("runtime_schema", {}) or {}).get("schema_version"),
        },
    }


__all__ = ["SCHEMA_VERSION", "build_runtime_debug_plan", "load_json_object", "validate_runtime_debug_plan"]
