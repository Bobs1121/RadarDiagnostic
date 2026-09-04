"""Deterministic projection for the detailed CR60 diagnostic report.

The report is intentionally not a second diagnosis engine.  It projects
explicit bundle/viewer/runtime/code/ledger artifacts into a bounded, readable
package.  An optional AI panel result is carried as an inference section and
never overwrites observed or derived facts.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import html
import json
import math
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from .alert_timeline import build_alert_timeline
from .condition_trace import build_condition_trace
from .diagnostic_narrative import build_diagnostic_narrative
from .evidence_query import build_evidence_query


SCHEMA_VERSION = "diagnostic-report.v1"


def _hash(value: object) -> str:
    text = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _load_object(
    value: Mapping[str, Any] | None,
    path_text: str,
    *,
    label: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, str | None]:
    if value is not None:
        if not isinstance(value, Mapping):
            return None, None, f"{label}_must_be_object"
        payload = deepcopy(dict(value))
        return payload, {"label": label, "source": "inline", "sha256": _hash(payload)}, None
    if not str(path_text or "").strip():
        return None, None, None
    path = Path(path_text).expanduser().resolve()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return None, None, f"{label}_invalid:{type(exc).__name__}:{path}"
    if not isinstance(payload, Mapping):
        return None, None, f"{label}_must_be_object:{path}"
    data = deepcopy(dict(payload))
    return data, {"label": label, "source": "file", "path": str(path), "sha256": _hash(data)}, None


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _field_rows(value: Any) -> list[Mapping[str, Any]]:
    """Unwrap bounded field arrays returned by evidence-query."""
    if isinstance(value, list):
        return [item for item in value if isinstance(item, Mapping)]
    if isinstance(value, Mapping):
        items = value.get("items")
        if isinstance(items, list):
            return [item for item in items if isinstance(item, Mapping)]
        if value.get("token") or value.get("code_token") or value.get("access_path"):
            return [value]
    return []


def _first_frame(event: Mapping[str, Any]) -> dict[str, Any]:
    for key in ("first_on_frame", "threshold_crossing_frame"):
        if event.get(key) not in (None, "", []):
            return {
                "frame_id": event.get(key),
                "source": key,
                "definition": "output_first_frame_candidate",
                "confidence": "observed_event_field",
            }
    precheck = event.get("frame_precheck")
    if isinstance(precheck, Mapping) and precheck.get("alarm_first_frame_id") not in (None, "", []):
        return {
            "frame_id": precheck.get("alarm_first_frame_id"),
            "source": precheck.get("alarm_first_frame_source", "frame_precheck"),
            "definition": "alarm_first_frame_candidate",
            "confidence": precheck.get("alarm_first_frame_confidence", "derived"),
        }
    replay = event.get("replay_plan")
    if isinstance(replay, Mapping) and replay.get("target_frame_id") not in (None, "", []):
        return {
            "frame_id": replay.get("target_frame_id"),
            "source": replay.get("target_frame_source", "replay_plan"),
            "definition": "selected_analysis_frame",
            "confidence": "selected_frame_not_alarm_edge",
        }
    frame = event.get("frame")
    if isinstance(frame, Mapping) and frame.get("target_frame") not in (None, "", []):
        return {
            "frame_id": frame.get("target_frame"),
            "source": frame.get("target_frame_source", "viewer_model"),
            "definition": "selected_analysis_frame",
            "confidence": frame.get("selection_confidence", "selected_frame_not_alarm_edge"),
        }
    return {"frame_id": None, "source": "not_available", "definition": "not_available", "confidence": "not_available"}


def _event_summary(event: Mapping[str, Any]) -> dict[str, Any]:
    identity = event.get("identity") if isinstance(event.get("identity"), Mapping) else {}
    frame = _first_frame(event)
    target = event.get("selected_target") if isinstance(event.get("selected_target"), Mapping) else {}
    selected = event.get("target") if isinstance(event.get("target"), Mapping) else {}
    if isinstance(selected.get("selected"), Mapping):
        target = selected["selected"]
    elif selected.get("obj_id") not in (None, "") or selected.get("objID") not in (None, ""):
        target = selected
    alarm = event.get("alarm") if isinstance(event.get("alarm"), Mapping) else {}
    function = event.get("function") or identity.get("function")
    side = identity.get("side") or event.get("side")
    if side in (None, "") and isinstance(function, str) and function.rsplit("_", 1)[-1].upper() in {"L", "R"}:
        side = function.rsplit("_", 1)[-1].upper()
    return {
        "event_id": event.get("event_id"),
        "function": function,
        "side": side,
        "radar_id": event.get("radar_id") or identity.get("radar_id"),
        "radar_pos": identity.get("radar_name") or identity.get("radar_pos"),
        "source": event.get("source") or identity.get("source"),
        "start_time_sec": event.get("start_time_sec") if event.get("start_time_sec") not in (None, "") else alarm.get("start_time_sec"),
        "end_time_sec": event.get("end_time_sec") if event.get("end_time_sec") not in (None, "") else alarm.get("end_time_sec"),
        "first_frame": frame,
        "target_obj_id": target.get("obj_id") or target.get("objID"),
        "evidence_status": event.get("evidence_status") or event.get("confidence"),
    }


def _condition_facts_from_event(event: Mapping[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Flatten only explicit same-frame field facts for condition tracing."""
    details = event.get("details") if isinstance(event.get("details"), Mapping) else event
    values: dict[str, Any] = {}
    for group_name in ("ego", "target"):
        group = details.get(group_name) if isinstance(details, Mapping) else None
        if not isinstance(group, Mapping):
            continue
        for field in group.get("fields", []) or []:
            if not isinstance(field, Mapping):
                continue
            for key in ("access_path", "code_token"):
                token = str(field.get(key, "") or "").strip()
                if token:
                    values[token] = dict(field)

    # Runtime observations are eligible only when the observation carries the
    # selected algorithm frame.  A same-function time-window observation is
    # useful for display, but it must not silently become a condition binding.
    selected_frame = ""
    summary = event.get("summary") if isinstance(event.get("summary"), Mapping) else {}
    first = summary.get("first_frame") if isinstance(summary.get("first_frame"), Mapping) else {}
    selected_frame = str(first.get("frame_id") or "")
    runtime_association = str(event.get("runtime_association") or "")
    runtime_rows: list[Mapping[str, Any]] = []
    runtime_rows.extend(row for row in event.get("runtime_observations", []) or [] if isinstance(row, Mapping))
    runtime_projection = details.get("runtime") if isinstance(details, Mapping) and isinstance(details.get("runtime"), Mapping) else {}
    runtime_rows.extend(row for row in runtime_projection.get("observations", []) or [] if isinstance(row, Mapping))
    for observation in runtime_rows:
        identity = observation.get("identity") if isinstance(observation.get("identity"), Mapping) else observation
        observation_frame = str(
            observation.get("frame_id")
            or identity.get("frame_id")
            or identity.get("frameID")
            or ""
        )
        exact_scope = runtime_association.startswith("exact_") or runtime_association in {"frame_verified", "callback_correlated"}
        if selected_frame and observation_frame and observation_frame != selected_frame:
            continue
        if selected_frame and not observation_frame and not exact_scope:
            continue
        if runtime_association and not exact_scope and observation_frame != selected_frame:
            continue
        layer = str(observation.get("layer") or "runtime_with_frame")
        for field_order, field in enumerate(_field_rows(observation.get("fields"))):
            token = str(field.get("token") or field.get("code_token") or field.get("access_path") or "").strip()
            if not token:
                continue
            # A GDB expression can be syntactically valid but unavailable at
            # the current stack frame (``No symbol``, optimized out, etc.).
            # Keep that row in runtime evidence for audit, but do not let its
            # empty/non-value overwrite a valid same-source macro, enum, or
            # public observation already collected for the condition trace.
            field_status = str(field.get("status") or "observed").lower()
            if field_status in {"not_found", "not_available", "optimized_out", "conflict"}:
                continue
            if field.get("value") in (None, "") and field_status != "observed":
                continue
            # ``info args/locals`` in a batch transcript can span several
            # stops.  Without a stop-location binding, a later local snapshot
            # may be incorrectly applied to an earlier condition (notably a
            # counter updated by a warning handler).  Such locals remain in
            # the report's runtime evidence, but only explicitly printed
            # source tokens/struct fields participate in condition truth.
            if str(field.get("scope") or "").lower() in {"args", "locals"}:
                continue
            fact = dict(field)
            fact.setdefault("source_kind", f"runtime_{layer}")
            fact.setdefault("confidence", "runtime_same_frame")
            if fact.get("source") in (None, ""):
                fact["source"] = observation.get("source") or observation.get("source_ref")
            if fact.get("runtime_ref") in (None, "") and observation.get("code_chain"):
                fact["runtime_ref"] = observation.get("code_chain")
            values[token] = fact

    # Active ROI projections carry source parameter rows.  They are useful as
    # current-code facts, but are never converted to runtime local variables.
    parameter_rows: list[dict[str, Any]] = []
    for layer in details.get("roi_layers", []) if isinstance(details, Mapping) else []:
        if not isinstance(layer, Mapping):
            continue
        for row in layer.get("parameter_values", []) or []:
            if isinstance(row, Mapping):
                parameter = dict(row)
                # The active ROI layer is an explicit source-derived
                # configuration projection.  Mark its origin so the
                # condition engine may use it, while keeping local variables
                # that the regex code index calls "parameters" out of the
                # numeric binding set.
                parameter["source_kind"] = "active_source_parameter"
                parameter["parameter_origin"] = "active_roi_projection"
                parameter_rows.append(parameter)
    return values, parameter_rows


def _derive_condition_trace(
    *,
    event: Mapping[str, Any] | None,
    event_code_path: Mapping[str, Any] | None,
    bundle: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(event, Mapping):
        return build_condition_trace(conditions=None)
    resolution = event_code_path.get("resolution") if isinstance(event_code_path, Mapping) and isinstance(event_code_path.get("resolution"), Mapping) else {}
    # ``condition_chain`` is generated from the current source call path.  It
    # includes enclosing gates and relevant helper functions in execution
    # order (with relation metadata) while retaining ``conditions`` as the
    # event-root compatibility view.
    conditions = (
        resolution.get("condition_chain") or resolution.get("conditions", [])
        if isinstance(resolution, Mapping)
        else []
    )
    source_root = str((event_code_path.get("source_context") or {}).get("source_root", "")) if isinstance(event_code_path, Mapping) else ""
    if not conditions and isinstance(bundle, Mapping):
        code_evidence = bundle.get("code_evidence") if isinstance(bundle.get("code_evidence"), Mapping) else {}
        raw_conditions = code_evidence.get("conditions", []) if isinstance(code_evidence, Mapping) else []
        details = event.get("details") if isinstance(event.get("details"), Mapping) else event
        feature = details.get("feature") if isinstance(details, Mapping) and isinstance(details.get("feature"), Mapping) else {}
        entry_function = str(feature.get("entry_function", "") or "")
        breakpoint_pack = details.get("breakpoint_pack") if isinstance(details, Mapping) and isinstance(details.get("breakpoint_pack"), Mapping) else {}
        breakpoint_functions = {
            str(row.get("function", ""))
            for row in breakpoint_pack.get("breakpoints", []) or []
            if isinstance(row, Mapping) and row.get("function")
        }
        # Prefer the feature entry function.  The breakpoint pack may list
        # downstream handlers as well, but mixing every handler's condition
        # into one event would make the report look like a single conjunction.
        candidates = {entry_function} if entry_function else breakpoint_functions
        if isinstance(raw_conditions, list):
            conditions = [
                dict(row) for row in raw_conditions
                if isinstance(row, Mapping) and (not candidates or str(row.get("function", "")) in candidates)
            ]
            if not conditions and breakpoint_functions and entry_function:
                conditions = [
                    dict(row) for row in raw_conditions
                    if isinstance(row, Mapping) and str(row.get("function", "")) in breakpoint_functions
                ]
        source_root = source_root or str(code_evidence.get("source_root", "") or "")
    # ``code-index.parameters`` is intentionally not treated as a constant
    # table here.  The current sibling regex index also records local derived
    # assignments (for example warning counters) under that section.  Only
    # explicit active ROI parameter projections and caller-provided parameter
    # facts are safe inputs for deterministic condition evaluation.
    parameters: list[dict[str, Any]] = []
    values, active_parameters = _condition_facts_from_event(event)
    parameters.extend(active_parameters)
    summary = event.get("summary") if isinstance(event.get("summary"), Mapping) else {}
    first = summary.get("first_frame") if isinstance(summary.get("first_frame"), Mapping) else {}
    return build_condition_trace(
        conditions=conditions,
        values=values,
        parameters=parameters,
        event_id=str(event.get("event_id", "") or ""),
        function=str(summary.get("function", "") or ""),
        frame_id=first.get("frame_id"),
        source_root=source_root,
        max_conditions=240,
    )


def _artifact_ref(ref: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(ref, Mapping):
        return {}
    return {
        key: deepcopy(ref[key])
        for key in ("label", "source", "path", "sha256", "schema_version")
        if ref.get(key) not in (None, "", [])
    }


def _source_snapshot_hash(value: Mapping[str, Any] | None) -> str:
    if not isinstance(value, Mapping):
        return ""
    provenance = value.get("provenance") if isinstance(value.get("provenance"), Mapping) else {}
    source = value.get("source_context") if isinstance(value.get("source_context"), Mapping) else {}
    identity = source.get("identity") if isinstance(source.get("identity"), Mapping) else {}
    containers = (provenance, source, identity)
    # A bundle may carry both the source snapshot identity and the hash of a
    # legacy/index projection under ``provenance.source_index_hash``.  The
    # two hashes are not interchangeable: the former binds source/code/binary
    # evidence, while the latter identifies an adapter artifact.  Prefer the
    # actual source snapshot fields across all containers before falling back
    # to an index hash, otherwise a valid current-source report is falsely
    # blocked merely because provenance happens to be visited first.
    for keys in (("source_snapshot_hash", "snapshot_hash"), ("source_index_hash", "code_index_hash")):
        for item in containers:
            for key in keys:
                if item.get(key) not in (None, "", []):
                    return str(item[key])
    return ""


def _identity_field(value: Mapping[str, Any] | None, field: str) -> str:
    if not isinstance(value, Mapping):
        return ""
    containers: list[Mapping[str, Any]] = [value]
    for key in ("provenance", "source_context", "identity", "run", "binary"):
        item = value.get(key)
        if isinstance(item, Mapping):
            containers.append(item)
            nested = item.get("identity")
            if isinstance(nested, Mapping):
                containers.append(nested)
    for item in containers:
        candidate = item.get(field)
        if candidate not in (None, "", []):
            return str(candidate)
    return ""


def _identity_conflicts(
    *,
    label_left: str,
    left: Mapping[str, Any] | None,
    label_right: str,
    right: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    if not isinstance(left, Mapping) or not isinstance(right, Mapping):
        return []
    conflicts: list[dict[str, Any]] = []
    for field in ("source_context_id", "source_snapshot_hash", "binary_fingerprint", "data_fingerprint"):
        left_value = _identity_field(left, field)
        right_value = _identity_field(right, field)
        if left_value and right_value and left_value != right_value:
            conflicts.append({
                "field": field,
                label_left: left_value,
                label_right: right_value,
                "reason": "artifacts_are_bound_to_different_identities",
            })
    return conflicts


def _source_output_mapping(
    preflight: Mapping[str, Any] | None,
    selected_event: Mapping[str, Any] | None,
    event_code_path: Mapping[str, Any] | None = None,
    code_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Select source Tx mappings for the current event without claiming a send."""
    can_output = preflight.get("can_output") if isinstance(preflight, Mapping) and isinstance(preflight.get("can_output"), Mapping) else {}
    source_output_chain = can_output.get("source_output_chain") if isinstance(can_output.get("source_output_chain"), Mapping) else {}
    source_output_chain_rows = {
        str(item.get("signal") or "").strip(): item
        for item in source_output_chain.get("rows", []) or []
        if isinstance(item, Mapping) and str(item.get("signal") or "").strip()
    }

    def member_paths(expression: Any) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for match in re.finditer(
            r"\b[A-Za-z_][A-Za-z0-9_]*(?:(?:->|\.)[A-Za-z_][A-Za-z0-9_]*)+",
            str(expression or ""),
        ):
            token = match.group(0)
            if token not in seen:
                seen.add(token)
                result.append(token)
        return result

    def enrich_source_row(row: dict[str, Any], signal: str, expression: str) -> dict[str, Any]:
        chain_row = source_output_chain_rows.get(signal)
        if isinstance(chain_row, Mapping):
            row["internal_member_paths"] = list(chain_row.get("internal_member_paths", []) or [])
            row["producer_member_paths"] = list(chain_row.get("producer_member_paths", []) or [])
            row["producer_function_names"] = list(chain_row.get("producer_function_names", []) or [])
            row["producer_function_refs"] = [
                dict(item) for item in chain_row.get("producer_function_refs", []) or [] if isinstance(item, Mapping)
            ]
            if isinstance(chain_row.get("primary_assignment"), Mapping):
                row["primary_assignment"] = deepcopy(dict(chain_row.get("primary_assignment") or {}))
            row["internal_assignments"] = [
                dict(item) for item in chain_row.get("assignments", []) or [] if isinstance(item, Mapping)
            ]
            row["assignment_status"] = str(chain_row.get("assignment_status") or "not_scanned")
            row["source_output_chain_status"] = str(source_output_chain.get("status") or "source_scan_partial")
        else:
            row["internal_member_paths"] = member_paths(expression)
            row["producer_member_paths"] = []
            row["producer_function_names"] = []
            row["producer_function_refs"] = []
            row["internal_assignments"] = []
            row["assignment_status"] = "not_scanned"
            row["source_output_chain_status"] = "not_scanned"
        return row
    mappings = [item for item in can_output.get("write_mappings", []) or [] if isinstance(item, Mapping)]
    transport_mappings = [item for item in can_output.get("transport_mappings", []) or [] if isinstance(item, Mapping)]
    source = "arbe_preflight.can_output.write_mappings+transport_mappings"
    if not mappings and not transport_mappings:
        fallback_rows: list[dict[str, Any]] = []
        if isinstance(event_code_path, Mapping):
            resolution = event_code_path.get("resolution") if isinstance(event_code_path.get("resolution"), Mapping) else {}
            fallback_rows.extend(
                dict(item) for item in resolution.get("output_signals", []) or [] if isinstance(item, Mapping)
            )
            if fallback_rows:
                source = "event_code_path.resolution.output_signals"
        if not fallback_rows and isinstance(code_context, Mapping):
            output_mapping = code_context.get("output_mapping")
            if isinstance(output_mapping, Mapping):
                fallback_rows.extend(
                    dict(item) for item in output_mapping.get("mappings", []) or [] if isinstance(item, Mapping)
                )
                if fallback_rows:
                    source = "code_context.output_mapping"
        if fallback_rows:
            mappings = [
                {
                    "signal": item.get("signal") or item.get("signal_name") or item.get("can_signal"),
                    "expression": item.get("expression", ""),
                    "source_ref": item.get("source_ref") or {
                        key: item.get(key)
                        for key in ("file_path", "line", "source_file", "source_hash")
                        if item.get(key) not in (None, "")
                    },
                    "snippet": item.get("snippet", ""),
                }
                for item in fallback_rows
                if item.get("signal") or item.get("signal_name") or item.get("can_signal")
            ]
    if not mappings and not transport_mappings:
        return {
            "status": "not_available" if not can_output else "source_mapping_not_found",
            "signals": [],
            "candidate_count": len(can_output.get("candidate_signal_tokens", []) or []),
            "source": "arbe_preflight.can_output",
            "source_output_chain": deepcopy(dict(source_output_chain)) if source_output_chain else {},
        }
    summary = selected_event.get("summary") if isinstance(selected_event, Mapping) and isinstance(selected_event.get("summary"), Mapping) else {}
    function = str(summary.get("function") or "").strip()
    side = str(summary.get("side") or "").upper()
    normalized_function = re.sub(r"[^a-z0-9]", "", function.lower())
    feature = next(
        (item for item in ("fcta", "fctb", "rcta", "rctb", "rcw", "lca", "bsd", "dow") if item in normalized_function),
        "",
    )
    selected: list[dict[str, Any]] = []
    selected_by_signal: dict[str, dict[str, Any]] = {}
    mapping_expression_by_signal = {
        str(item.get("signal") or item.get("can_signal") or "").strip(): str(item.get("expression") or "")
        + " " + str(item.get("snippet") or "")
        for item in mappings
        if str(item.get("signal") or item.get("can_signal") or "").strip()
    }

    def in_scope(signal: str, expression: str) -> bool:
        searchable = f"{signal} {expression}".lower()
        if feature and feature not in searchable:
            return False
        if side in {"L", "R"}:
            if side == "R" and "left" in searchable and "right" not in searchable:
                return False
            if side == "L" and "right" in searchable and "left" not in searchable:
                return False
        return True

    for mapping in mappings:
        signal = str(mapping.get("signal") or mapping.get("can_signal") or "").strip()
        expression = str(mapping.get("expression") or "").strip()
        if not signal or not in_scope(signal, expression):
            continue
        source_ref = mapping.get("source_ref") if isinstance(mapping.get("source_ref"), Mapping) else {}
        row = enrich_source_row({
            "signal": signal,
            "expression": expression,
            "source_ref": deepcopy(dict(source_ref)),
            "snippet": mapping.get("snippet", ""),
            "status": "source_candidate",
            "runtime_observed": False,
        }, signal, expression)
        selected.append(row)
        selected_by_signal.setdefault(signal, row)
        if len(selected) >= 24:
            break
    for mapping in transport_mappings:
        signal = str(mapping.get("signal") or "").strip()
        transport_expression = mapping_expression_by_signal.get(signal, "")
        if not transport_expression:
            transport_expression = str(mapping.get("com_signal") or signal)
        if not signal or not in_scope(signal, transport_expression):
            continue
        transport = {
            "rte_lite_function": mapping.get("rte_lite_function") or f"RteLite_Write_{signal}",
            "source_ref": deepcopy(dict(mapping.get("source_ref") or {})),
            "com_send_source_ref": deepcopy(dict(mapping.get("com_send_source_ref") or {})),
            "com_signal": mapping.get("com_signal") or "",
            "writer_snippet": mapping.get("writer_snippet") or "",
            "send_snippet": mapping.get("send_snippet") or "",
            "source_kind": mapping.get("source_kind") or "source_rte_lite_to_com_send",
        }
        row = selected_by_signal.get(signal)
        if row is None:
            if len(selected) >= 24:
                continue
            row = enrich_source_row({
                "signal": signal,
                "expression": "",
                "source_ref": deepcopy(dict(transport.get("source_ref") or {})),
                "snippet": transport.get("writer_snippet", ""),
                "status": "source_candidate",
                "runtime_observed": False,
            }, signal, "")
            selected.append(row)
            selected_by_signal[signal] = row
        row.setdefault("transport_mappings", []).append(transport)
    return {
        "status": "source_candidate" if selected else "source_mapping_not_found_for_scope",
        "function": function,
        "side": side,
        "signals": selected,
        "candidate_count": len(mappings),
        "transport_candidate_count": len(transport_mappings),
        "selected_count": len(selected),
        "source": source,
        "source_output_chain": deepcopy(dict(source_output_chain)) if source_output_chain else {},
        "policy": "Static RteComMapping/ RteLite/Com_SendSignal mapping is not CAN Tx runtime evidence.",
    }


def _analysis_trace(analysis_run: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(analysis_run, Mapping):
        return {"status": "not_provided", "step_count": 0, "steps": []}
    raw_steps = analysis_run.get("steps") or (analysis_run.get("entities") or {}).get("steps", [])
    entities = analysis_run.get("entities") if isinstance(analysis_run.get("entities"), Mapping) else {}

    def load_entity(ref: Any) -> Mapping[str, Any] | None:
        if not isinstance(ref, Mapping):
            return None
        path_text = str(ref.get("path") or ref.get("artifact_path") or "").strip()
        if path_text:
            try:
                loaded = json.loads(Path(path_text).expanduser().resolve().read_text(encoding="utf-8"))
                if isinstance(loaded, Mapping):
                    return loaded
            except (OSError, UnicodeError, json.JSONDecodeError):
                pass
        return ref

    def load_entity_rows(name: str, fields: tuple[str, ...], limit: int) -> list[dict[str, Any]]:
        refs = analysis_run.get(name) or entities.get(name, [])
        result: list[dict[str, Any]] = []
        for ref in _as_list(refs):
            detail = load_entity(ref)
            if not isinstance(detail, Mapping):
                continue
            row = {
                key: deepcopy(detail[key])
                for key in fields
                if detail.get(key) not in (None, "", [])
            }
            path_text = str(ref.get("path") or ref.get("artifact_path") or "").strip() if isinstance(ref, Mapping) else ""
            if path_text:
                row["artifact_path"] = path_text
            if row:
                result.append(row)
            if len(result) >= limit:
                break
        return result

    steps: list[dict[str, Any]] = []
    for item in _as_list(raw_steps):
        if not isinstance(item, Mapping):
            continue
        # ``analysis-run.json`` normally stores compact entity references.
        # Read the referenced step once so the report can show the useful,
        # user-visible facts without embedding the complete ledger payload or
        # any model reasoning.  A caller may also pass full step entities via
        # ``include_entities=true``.
        detail: Mapping[str, Any] = item
        step_path = str(item.get("path") or item.get("artifact_path") or "").strip()
        if step_path:
            try:
                loaded = json.loads(Path(step_path).expanduser().resolve().read_text(encoding="utf-8"))
                if isinstance(loaded, Mapping):
                    detail = loaded
            except (OSError, UnicodeError, json.JSONDecodeError):
                detail = item

        def compact_rows(value: Any, keys: tuple[str, ...], limit: int) -> list[dict[str, Any]]:
            rows: list[dict[str, Any]] = []
            for row in value if isinstance(value, list) else []:
                if not isinstance(row, Mapping):
                    continue
                compact = {
                    key: deepcopy(row[key])
                    for key in keys
                    if row.get(key) not in (None, "", [])
                }
                if compact:
                    rows.append(compact)
                if len(rows) >= limit:
                    break
            return rows

        observations = compact_rows(
            detail.get("observations"),
            ("kind", "statement", "tool", "event_type", "result_status", "scope", "should_alert", "status"),
            6,
        )
        gaps = compact_rows(
            detail.get("gaps"),
            ("id", "code", "status", "reason", "critical"),
            8,
        )
        conflicts = compact_rows(
            detail.get("conflicts"),
            ("id", "field", "status", "reason", "expected", "actual"),
            6,
        )
        next_actions = compact_rows(
            detail.get("next_action_candidates"),
            ("id", "tool", "name", "reason", "expected_discrimination"),
            6,
        )
        step = {
            "step_id": detail.get("step_id") or item.get("id") or item.get("step_id"),
            "stage": detail.get("stage") or item.get("stage"),
            "status": detail.get("status") or item.get("status"),
            "user_visible_summary": detail.get("user_visible_summary") or item.get("summary") or "",
            "artifact_path": step_path,
            "observation_count": len(detail.get("observations", []) or []) if isinstance(detail.get("observations"), list) else 0,
            "observations": observations,
            "gap_count": len(detail.get("gaps", []) or []) if isinstance(detail.get("gaps"), list) else 0,
            "gaps": gaps,
            "conflict_count": len(detail.get("conflicts", []) or []) if isinstance(detail.get("conflicts"), list) else 0,
            "conflicts": conflicts,
            "claim_ref_count": len(detail.get("claim_refs", []) or []) if isinstance(detail.get("claim_refs"), list) else 0,
            "next_action_candidates": next_actions,
        }
        steps.append({key: value for key, value in step.items() if value not in (None, "", [])})
    hypotheses = load_entity_rows(
        "hypotheses",
        (
            "hypothesis_id", "category", "statement", "rank", "confidence_band", "status",
            "supporting_claim_refs", "contradicting_claim_refs", "required_evidence", "experiment_refs",
            "history", "updated_at",
        ),
        24,
    )
    experiments = load_entity_rows(
        "experiments",
        (
            "experiment_id", "question", "method", "status", "target", "plan_ref", "approval",
            "session_ref", "watch_groups", "expected_discrimination", "observations", "disturbance",
            "conclusion_delta", "hypothesis_refs", "updates", "updated_at",
        ),
        24,
    )
    user_observations = load_entity_rows(
        "user_observations",
        (
            "observation_id", "kind", "summary", "experiment_id", "hypothesis_refs", "artifact_refs",
            "created_by", "created_at", "evidence_layer", "runtime_eligible", "target",
        ),
        24,
    )
    for row in hypotheses:
        row["supporting_claim_count"] = len(row.get("supporting_claim_refs", []) or [])
        row["contradicting_claim_count"] = len(row.get("contradicting_claim_refs", []) or [])
        row["required_evidence_count"] = len(row.get("required_evidence", []) or [])
        row["experiment_ref_count"] = len(row.get("experiment_refs", []) or [])
        row["history_count"] = len(row.get("history", []) or [])
        for key in ("supporting_claim_refs", "contradicting_claim_refs", "required_evidence", "experiment_refs", "history"):
            row.pop(key, None)
    for row in experiments:
        row["watch_group_count"] = len(row.get("watch_groups", []) or [])
        row["expected_discrimination_count"] = len(row.get("expected_discrimination", []) or [])
        row["observation_count"] = len(row.get("observations", []) or [])
        row["conclusion_delta_count"] = len(row.get("conclusion_delta", []) or [])
        row["update_count"] = len(row.get("updates", []) or [])
        row.pop("watch_groups", None)
        row.pop("expected_discrimination", None)
        row.pop("observations", None)
        row.pop("conclusion_delta", None)
        row.pop("updates", None)
    for row in user_observations:
        row["artifact_ref_count"] = len(row.get("artifact_refs", []) or [])
        row["hypothesis_ref_count"] = len(row.get("hypothesis_refs", []) or [])
        row.pop("artifact_refs", None)
        row.pop("hypothesis_refs", None)
    return {
        "status": analysis_run.get("status", "provided"),
        "run_id": analysis_run.get("run_id", ""),
        "current_stage": analysis_run.get("current_stage", ""),
        "step_count": len(steps),
        "claim_count": len(analysis_run.get("claims", []) or []),
        "steps": steps,
        "hypotheses": hypotheses,
        "experiments": experiments,
        "user_observations": user_observations,
    }


def _frame_mapping_conflicts(selected: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """Detect radar/frame mapping inconsistencies in the selected event."""
    event = selected if isinstance(selected, Mapping) else {}
    summary = event.get("summary") if isinstance(event.get("summary"), Mapping) else {}
    details = event.get("details") if isinstance(event.get("details"), Mapping) else {}
    frame = details.get("frame") if isinstance(details.get("frame"), Mapping) else {}
    expected_radar = summary.get("radar_id")
    if expected_radar in (None, ""):
        return []
    expected = str(expected_radar)
    observations: list[tuple[str, Any, Any]] = []
    gui_mapping = frame.get("gui_main_mapping") if isinstance(frame.get("gui_main_mapping"), Mapping) else {}
    if gui_mapping.get("radar_id") not in (None, ""):
        observations.append(("frame.gui_main_mapping.radar_id", gui_mapping.get("radar_id"), gui_mapping.get("topic")))
    source_ref = frame.get("source_ref") if isinstance(frame.get("source_ref"), Mapping) else {}
    topic = str(source_ref.get("topic") or "")
    match = re.search(r"(?:lgu_data|radar)[_-]([0-9]+)", topic, re.IGNORECASE)
    if match:
        observations.append(("frame.source_ref.topic", match.group(1), topic))
    conflicts: list[dict[str, Any]] = []
    for path, actual, evidence in observations:
        if str(actual) == expected:
            continue
        conflicts.append({
            "field": path,
            "expected_radar_id": expected_radar,
            "actual_radar_id": actual,
            "evidence": evidence,
            "reason": "selected event radar does not match an embedded frame mapping; do not use the conflicting mapping for this event",
        })
    return conflicts


def _detect_can_data_status(
    bundle: Mapping[str, Any] | None,
    runtime: Mapping[str, Any] | None,
    explicit_status: str = "",
) -> str:
    """Detect whether CAN data is in scope without treating CAN as mandatory.

    The batch bundle historically contains radar/camera topics but no CAN
    inventory.  In that case ``not_detected`` is intentional: the report uses
    the algorithm output endpoint and states that CAN was not supplied.  A
    future parser can publish an explicit ``present``/``absent`` status or a
    topic inventory; only then does the CAN endpoint become a required check.
    """
    normalized = str(explicit_status or "").strip().lower()
    if normalized in {"present", "absent", "not_detected", "unknown"}:
        return normalized
    runtime_observations = (runtime or {}).get("observations", []) if isinstance(runtime, Mapping) else []
    for observation in runtime_observations:
        if isinstance(observation, Mapping) and str(observation.get("layer") or "") == "can_tx_observation":
            return "present"

    containers: list[Mapping[str, Any]] = []
    if isinstance(bundle, Mapping):
        containers.append(bundle)
        for key in ("data_quality", "signal_summary", "arbe_precheck"):
            value = bundle.get(key)
            if isinstance(value, Mapping):
                containers.append(value)
    for container in containers:
        for key in ("can_data_status", "can_status"):
            value = container.get(key)
            if isinstance(value, str) and value.strip().lower() in {"present", "absent", "not_detected", "unknown"}:
                return value.strip().lower()
        for key in ("can_available", "has_can", "can_present"):
            value = container.get(key)
            if isinstance(value, bool):
                return "present" if value else "absent"
        for key in ("can_topics", "can_channels", "can_signals", "can_frames", "can_data", "can_inventory"):
            value = container.get(key)
            if value not in (None, "", [], {}):
                return "present"
        for key in ("topics", "topic_inventory", "channels", "signals"):
            value = container.get(key)
            if not isinstance(value, (Mapping, list)):
                continue
            rows = value.items() if isinstance(value, Mapping) else enumerate(value)
            for row_key, row_value in rows:
                text = f"{row_key} {row_value}".lower()
                if "can" in text and "can_output" not in text:
                    return "present"
    return "not_detected"


def _gdb_confirmation(
    runtime: Mapping[str, Any] | None,
    selected: Mapping[str, Any] | None,
    session: Mapping[str, Any] | None = None,
    timeline: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Summarize whether GDB actually hit the selected frame/object.

    This is an evidence summary, not a claim that every GDB expression was
    available. A successful runner with some ``No symbol`` probes is reported
    as a successful partial observation, while frame/object identity must
    still match before it is called exact.
    """
    if not isinstance(runtime, Mapping):
        return {"schema_version": "gdb-confirmation.v1", "status": "not_available", "actual_hit": False, "statement": "本次没有提供 GDB 运行结果。"}
    summary = selected.get("summary") if isinstance(selected, Mapping) and isinstance(selected.get("summary"), Mapping) else {}
    first = summary.get("first_frame") if isinstance(summary.get("first_frame"), Mapping) else {}
    expected_frame = str(first.get("frame_id") or "")
    expected_object = str(summary.get("target_obj_id") or "")
    expected_radar = str(summary.get("radar_id") or "")
    timeline_rows = timeline.get("rows", []) if isinstance(timeline, Mapping) else []
    rising_frames = [
        row.get("frame_id")
        for row in timeline_rows
        if isinstance(row, Mapping)
        and str(row.get("function") or row.get("signal") or "") == str(summary.get("function") or "")
        and str(row.get("radar_id") or "") == expected_radar
        and row.get("transition") == "rising"
        and row.get("frame_id") not in (None, "")
    ]
    algorithm_rising_frame = rising_frames[0] if rising_frames else None
    observations = [item for item in selected.get("runtime_observations", []) or [] if isinstance(item, Mapping)] if isinstance(selected, Mapping) else []
    gdb_observations = [item for item in observations if str(item.get("layer") or "") == "gdb_observation"]
    exact_rows: list[Mapping[str, Any]] = []
    for observation in gdb_observations:
        identity = observation.get("identity") if isinstance(observation.get("identity"), Mapping) else {}
        frame_match = not expected_frame or str(identity.get("frame_id") or identity.get("frame_counter") or "") == expected_frame
        object_match = not expected_object or str(identity.get("object_id") or "") == expected_object
        radar_match = not expected_radar or str(identity.get("radar_id") or "") == expected_radar
        if frame_match and object_match and radar_match:
            exact_rows.append(observation)
    layers = [item for item in runtime.get("evidence_layers", []) or [] if isinstance(item, Mapping)]
    gdb_layer = next((item for item in layers if str(item.get("id") or item.get("kind") or "") == "gdb_observation"), {})
    gdb_layer_status = str(gdb_layer.get("status") or "not_available")
    artifacts = runtime.get("artifacts") if isinstance(runtime.get("artifacts"), Mapping) else {}
    transcript = str(artifacts.get("gdb_transcript") or "")
    session_obj = session if isinstance(session, Mapping) else {}
    runner_status = str(session_obj.get("status") or "not_available")
    run = runtime.get("run") if isinstance(runtime.get("run"), Mapping) else {}
    diagnostics = [str(item) for item in runtime.get("diagnostics", []) or []]
    missing = 0
    observed = 0
    captured: list[tuple[int, int, dict[str, Any]]] = []
    for observation in exact_rows:
        for field_order, field in enumerate(_field_rows(observation.get("fields"))):
            status = str(field.get("status") or "observed")
            if status in {"observed", "derived"} and field.get("value") not in (None, ""):
                observed += 1
                token = str(field.get("token") or field.get("code_token") or field.get("access_path") or "")
                normalized_token = re.sub(r"[^a-z0-9]", "", token.lower())
                # Keep the alarm-relevant scalar values from any project. Do
                # not hard-code one feature's output member names; warning,
                # flag, frame/object identity, motion and prediction tokens
                # are the source-visible concepts shared by the report.
                scalar_value = not (
                    isinstance(field.get("value"), str)
                    and (field.get("value", "").lstrip().startswith(("0x", "(", "{")) or len(field.get("value", "")) > 180)
                )
                key_field = (
                    normalized_token in {"frameid", "i"}
                    or "objid" in normalized_token
                    or any(marker in normalized_token for marker in ("warning", "flag", "finter", "fint", "ttm", "ttc", "dist", "vel", "yaw", "roi"))
                )
                if key_field and scalar_value:
                    if normalized_token.startswith("adaswarning"):
                        priority = 0
                    elif "warning" in normalized_token or "flag" in normalized_token:
                        priority = 1
                    elif normalized_token in {"frameid", "i"} or "objid" in normalized_token:
                        priority = 2
                    elif any(marker in normalized_token for marker in ("ttm", "ttc", "finter", "fint")):
                        priority = 3
                    else:
                        priority = 4
                    captured.append((priority, field_order, {"token": token, "value": field.get("value"), "status": status}))
            elif status in {"not_found", "not_available", "optimized_out"}:
                missing += 1
    deduped_captured: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for _, _, item in sorted(captured, key=lambda row: (row[0], row[1])):
        key = (item["token"], repr(item["value"]))
        if key not in seen:
            seen.add(key)
            deduped_captured.append(item)
        if len(deduped_captured) >= 32:
            break
    actual_hit = bool(exact_rows and gdb_layer_status in {"observed", "derived"})
    status = "confirmed" if actual_hit else "partial" if gdb_observations or transcript else "not_available"
    source_location = {}
    if exact_rows and isinstance(exact_rows[0].get("identity"), Mapping):
        source_location = deepcopy(exact_rows[0]["identity"].get("source_location") or {})
    statement = (
        f"GDB 已在 frameID={expected_frame or '当前帧'} 命中目标处理路径，"
        f"并关联到 objID={expected_object or '当前目标'}；已获取 {observed} 个运行时字段。"
        if actual_hit else
        "当前有 GDB 产物，但还不能证明它与选定报警帧和目标完全对应。"
        if status == "partial" else
        "本次没有可确认的 GDB 命中。"
    )
    frame_relation = "not_evaluated"
    if expected_frame and algorithm_rising_frame not in (None, ""):
        try:
            delta = int(expected_frame) - int(algorithm_rising_frame)
            frame_relation = (
                "same_as_algorithm_rise" if delta == 0
                else f"{delta}_frames_after_algorithm_rise" if delta > 0
                else f"{abs(delta)}_frames_before_algorithm_rise"
            )
        except (TypeError, ValueError):
            frame_relation = "not_comparable"
    return {
        "schema_version": "gdb-confirmation.v1",
        "status": status,
        "actual_hit": actual_hit,
        "session_status": runner_status if session_obj else "inferred_from_transcript" if transcript else "not_available",
        "runner_status_verified": runner_status == "succeeded",
        "evidence_status": gdb_layer_status,
        "frame_id": first.get("frame_id"),
        "algorithm_rising_frame": algorithm_rising_frame,
        "frame_relation_to_algorithm_rise": frame_relation,
        "radar_id": summary.get("radar_id"),
        "object_id": summary.get("target_obj_id"),
        "function": summary.get("function"),
        "source_location": source_location,
        "transcript": transcript,
        "run_id": run.get("run_id"),
        "captured_fields": deduped_captured,
        "observed_field_count": observed,
        "missing_probe_count": missing,
        "diagnostics": diagnostics,
        "statement": statement,
        "policy": "GDB hit is confirmed only when the normalized GDB observation, frame, radar and object identity match; unavailable probes remain gaps and do not invalidate other captured fields.",
    }


def _execution_context_summary(
    preflight: Mapping[str, Any] | None,
    plan: Mapping[str, Any] | None,
    runtime: Mapping[str, Any] | None,
    gdb: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Describe how the selected evidence was produced, without guessing mode."""
    preflight_obj = preflight if isinstance(preflight, Mapping) else {}
    plan_obj = plan if isinstance(plan, Mapping) else {}
    runtime_obj = runtime if isinstance(runtime, Mapping) else {}
    configuration = preflight_obj.get("configuration") if isinstance(preflight_obj.get("configuration"), Mapping) else {}
    resolved = configuration.get("resolved") if isinstance(configuration.get("resolved"), Mapping) else {}
    macros = preflight_obj.get("build", {}).get("macros", {}) if isinstance(preflight_obj.get("build"), Mapping) else {}
    replay = plan_obj.get("replay") if isinstance(plan_obj.get("replay"), Mapping) else {}
    warmup = replay.get("warmup") if isinstance(replay.get("warmup"), Mapping) else {}
    strategy = str(replay.get("strategy") or replay.get("mode") or "not_available")
    mode_label = {
        "sgu_injection": "SGU 目标级注入",
        "pointcloud": "点云级仿真",
        "point_cloud": "点云级仿真",
        "raw_pointcloud": "点云级仿真",
    }.get(strategy.lower(), strategy)
    run = runtime_obj.get("run") if isinstance(runtime_obj.get("run"), Mapping) else {}
    gdb_obj = gdb if isinstance(gdb, Mapping) else {}
    source_identity = plan_obj.get("source_identity") if isinstance(plan_obj.get("source_identity"), Mapping) else {}
    identity = source_identity.get("identity") if isinstance(source_identity.get("identity"), Mapping) else {}
    arbe_contract = identity.get("arbe") if isinstance(identity.get("arbe"), Mapping) else {}
    warning_topic = str(arbe_contract.get("warning_topic") or "/corner_radar/warning_status")
    warning_with_frame_topic = str(arbe_contract.get("warning_with_frame_topic") or "/corner_radar/warning_status_with_frame")
    return {
        "data_source": "录制 bag",
        "bag": run.get("bag"),
        "algorithm_execution": "arbe 工作区中的本地算法仿真" if run.get("workspace") else "算法仿真方式未确认",
        "workspace": run.get("workspace"),
        "hilmodel": replay.get("hilmodel") or macros.get("HILMODEL"),
        "buildmodel": macros.get("BUILDMODEL"),
        "replay_strategy": strategy,
        "replay_mode_label": mode_label,
        "warmup": {
            key: warmup.get(key)
            for key in ("requested_frames", "actual_frames", "start_frame_id", "target_frame_id", "radar_id")
            if warmup.get(key) not in (None, "", [])
        },
        "lgu_topic": f"/wf/corner_radar/lgu_data_{run.get('radar_id')}" if run.get("radar_id") not in (None, "") else "not_available",
        "algorithm_warning_topic": warning_topic,
        "algorithm_warning_with_frame_topic": warning_with_frame_topic,
        "algorithm_warning_source": "algo_adasWarning",
        "radar_ids": resolved.get("radar_ids", []),
        "gdb_status": gdb_obj.get("status", "not_available"),
        "gdb_actual_hit": bool(gdb_obj.get("actual_hit")),
        "statement": (
            f"输入为录制 bag，使用 HILMODEL={replay.get('hilmodel') or macros.get('HILMODEL') or '未确认'} 的 {mode_label} 回放；"
            "GDB 只观察该仿真进程，不改变原始 bag。"
        ),
    }


def _build_diagnostic_conclusion(
    *,
    selected: Mapping[str, Any] | None,
    timeline: Mapping[str, Any] | None,
    diagnosis: Mapping[str, Any],
    conflicts: list[Mapping[str, Any]],
    output_policy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a conservative user-facing conclusion envelope.

    This is not an ADAS rule evaluator.  It states what the evidence package
    currently proves and what it cannot prove, so a generated report never
    looks like a confirmed false/true alarm merely because HTML generation
    succeeded.
    """
    summary = selected.get("summary") if isinstance(selected, Mapping) and isinstance(selected.get("summary"), Mapping) else {}
    first = summary.get("first_frame") if isinstance(summary.get("first_frame"), Mapping) else {}
    function = summary.get("function") or "selected event"
    side = summary.get("side") or ""
    radar = summary.get("radar_id")
    frame = first.get("frame_id")
    endpoint = str((output_policy or {}).get("effective_endpoint") or "can_tx")
    can_required = bool((output_policy or {}).get("can_required", endpoint == "can_tx"))
    timeline_sources = {
        str(item.get("layer")): item
        for item in (timeline.get("sources", []) if isinstance(timeline, Mapping) else [])
        if isinstance(item, Mapping)
    }
    layers_to_require = ["replay_algorithm", "runtime_with_frame", "gdb_observation"]
    if can_required:
        layers_to_require.append("can_tx_observation")
    missing_layers = [
        layer for layer in layers_to_require
        if str((timeline_sources.get(layer) or {}).get("status", "not_available")) == "not_available"
    ]
    gaps = [dict(item) for item in diagnosis.get("evidence_gaps", []) if isinstance(item, Mapping)]
    identity_gaps = list((timeline.get("scope") or {}).get("identity_gaps", []) or []) if isinstance(timeline, Mapping) and isinstance(timeline.get("scope"), Mapping) else []
    if conflicts:
        level = "blocked"
        status = "blocked"
    else:
        level = "facts_only"
        status = "partial" if gaps or missing_layers else "ready"
    sentence = (
        f"已确认数据中存在 {function}{('/' + str(side)) if side else ''} 的记录报警候选"
        f"（radar={radar if radar not in (None, '') else 'N/A'}，选定分析帧={frame if frame not in (None, '') else 'N/A'}）。"
        "当前报告只把它作为证据事实，不把它升级为正报或误报结论。"
    )
    if first.get("confidence") == "selected_frame_not_alarm_edge":
        sentence += (
            "选定帧来自时间对齐/回放候选，算法输出上升沿需以运行态时间线为准。"
            if endpoint == "algorithm"
            else "选定帧来自时间对齐/回放候选，尚未证明为算法输出或 CAN 上升沿。"
        )
    if missing_layers:
        sentence += "尚未提供：" + "、".join(missing_layers) + "，因此不能完成静态与运行态复现比较。"
    elif endpoint == "algorithm":
        sentence += "本报告以 arbe 可视化工具报警灯对应的算法最终输出作为报警终点。"
    if identity_gaps:
        sentence += "当前身份绑定仍缺少：" + "、".join(str(item) for item in identity_gaps) + "。"
    mapping_conflicts = [
        dict(item) for item in diagnosis.get("frame_mapping_conflicts", []) if isinstance(item, Mapping)
    ]
    if mapping_conflicts:
        sentence += "事件内部存在 radar/frame 映射冲突，已按事件 radar 保留并禁止使用冲突映射。"
    return {
        "status": status,
        "level": level,
        "statement": sentence,
        "confirmed_facts": [
            item for item in (
                f"event={summary.get('event_id') or selected.get('event_id') if isinstance(selected, Mapping) else ''}",
                f"function={function}",
                f"radar_id={radar}",
                f"selected_frame={frame}",
            ) if item and not item.endswith("=None")
        ],
        "not_proven": [
            *(["CAN Tx rising-edge frame"] if can_required else []),
            "all runtime local variables and state-machine counters",
            "final true-alarm/false-alarm classification",
        ],
        "missing_evidence_layers": missing_layers,
        "identity_gaps": identity_gaps,
        "blocking_gaps": gaps,
        "mapping_conflicts": mapping_conflicts,
        "conflicts": [dict(item) for item in conflicts],
        "output_policy": deepcopy(dict(output_policy or {})),
        "policy": "Only observed/derived evidence is stated as fact; inference requires explicit AI or user confirmation and cannot overwrite facts.",
    }


def _build_diagnosis_section(
    *,
    bundle: Mapping[str, Any],
    runtime: Mapping[str, Any] | None,
    code_context: Mapping[str, Any] | None,
    analysis: Mapping[str, Any] | None,
    query_events: list[Mapping[str, Any]],
    condition_trace: Mapping[str, Any] | None,
    conflicts: list[Mapping[str, Any]] | None = None,
    frame_mapping_conflicts: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    gaps: list[dict[str, Any]] = []
    if conflicts:
        gaps.append({
            "id": "artifact_identity_conflict",
            "status": "blocked",
            "reason": "bundle/code/runtime artifacts have conflicting data/source/binary identity",
        })
    if frame_mapping_conflicts:
        gaps.append({
            "id": "frame_radar_mapping_conflict",
            "status": "partial",
            "reason": "selected event contains an embedded radar/frame mapping inconsistent with the selected radar",
        })
    if isinstance(runtime, Mapping):
        disturbance = runtime.get("disturbance") if isinstance(runtime.get("disturbance"), Mapping) else {}
        disturbance_status = str(disturbance.get("status") or "").lower()
        if disturbance_status in {"suspected", "confirmed"}:
            gaps.append({
                "id": "runtime_disturbance_suspected",
                "status": "partial",
                "reason": str(disturbance.get("reason") or "runtime replay/debug disturbance is present"),
            })
    if not query_events:
        gaps.append({"id": "event_not_selected", "status": "blocked", "reason": "no event matches the selected query"})
    if not isinstance(runtime, Mapping):
        gaps.append({"id": "runtime_not_supplied", "status": "runtime_probe_required", "reason": "runtime values are not present in the report inputs"})
    if not isinstance(code_context, Mapping) and not (bundle.get("code_evidence") or bundle.get("code_context")):
        gaps.append({"id": "code_context_not_supplied", "status": "runtime_probe_required", "reason": "current source context/index is not attached"})
    for event in query_events:
        summary = event.get("summary") if isinstance(event.get("summary"), Mapping) else {}
        first = summary.get("first_frame") if isinstance(summary.get("first_frame"), Mapping) else {}
        if first.get("confidence") == "selected_frame_not_alarm_edge":
            gaps.append({"id": "alarm_first_frame_not_exact", "status": "runtime_probe_required", "reason": "the available frame is a selected analysis frame, not a proven output/CAN rising edge"})
        target_index = summary.get("target_index")
        if not target_index:
            gaps.append({"id": "algorithm_object_index_not_proven", "status": "not_available", "reason": "the event projection has no proven algorithm container index"})
        runtime_association = str(event.get("runtime_association") or "")
        if runtime_association == "no_matching_observation":
            gaps.append({"id": "runtime_event_not_bound", "status": "runtime_probe_required", "reason": "a runtime artifact exists but no observation can be bound to this event identity/frame"})
        elif "function_unresolved" in runtime_association:
            gaps.append({"id": "runtime_function_scope_unresolved", "status": "partial", "reason": "runtime observation matches the explicit frame/radar but did not carry a feature callback name"})
    if isinstance(condition_trace, Mapping):
        trace_summary = condition_trace.get("summary") if isinstance(condition_trace.get("summary"), Mapping) else {}
        if trace_summary.get("not_evaluable", 0) or trace_summary.get("unsupported", 0):
            gaps.append({
                "id": "condition_trace_partial",
                "status": "runtime_probe_required",
                "reason": "one or more source conditions could not be evaluated from same-frame explicit values",
            })
    gaps = list({str(item.get("id")): item for item in gaps}.values())
    if isinstance(analysis, Mapping):
        panel = analysis.get("panel_result")
        classification = analysis.get("classification")
        return {
            "status": "inference_with_gaps" if gaps else "inference",
            "classification": deepcopy(classification) if isinstance(classification, Mapping) else None,
            "panel_result": deepcopy(panel) if isinstance(panel, Mapping) else deepcopy(analysis),
        "evidence_gaps": gaps,
        "frame_mapping_conflicts": [dict(item) for item in frame_mapping_conflicts or [] if isinstance(item, Mapping)],
        "interpretation_policy": "AI interpretation is inference; it cannot overwrite observed/derived fields.",
        }
    return {
        "status": "pending" if not gaps else "blocked" if conflicts else "partial",
        "classification": deepcopy(bundle.get("triage") or bundle.get("initial_triage") or {}),
        "panel_result": None,
        "evidence_gaps": gaps,
        "frame_mapping_conflicts": [dict(item) for item in frame_mapping_conflicts or [] if isinstance(item, Mapping)],
        "interpretation_policy": "No AI diagnosis supplied. This report is an evidence package, not a final true/false-alarm conclusion.",
    }


def _next_actions(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    diagnosis = report.get("diagnosis") if isinstance(report.get("diagnosis"), Mapping) else {}
    gap_ids = {str(item.get("id")) for item in diagnosis.get("evidence_gaps", []) if isinstance(item, Mapping)}
    if "event_not_selected" in gap_ids:
        actions.append({"id": "select-event", "tool": "evidence-query", "reason": "选择一个功能/侧别/radar/帧后再生成详细事件报告"})
    if "code_context_not_supplied" in gap_ids:
        actions.append({"id": "prepare-code-context", "tool": "code-context-read", "reason": "读取当前 source fingerprint 下的相关函数、变量和条件"})
    if "runtime_not_supplied" in gap_ids or "alarm_first_frame_not_exact" in gap_ids:
        actions.append({"id": "public-runtime-first", "tool": "public-topic-plan", "reason": "先检查 with-frame warning、ego/radar_info 和 objectlist 的可用性"})
        actions.append({"id": "runtime-debug-if-needed", "tool": "runtime-debug-plan", "reason": "公共证据不足时生成当前 source/data 绑定的 GDB 计划"})
    if "condition_trace_partial" in gap_ids and "runtime-debug-if-needed" not in {str(item.get("id")) for item in actions}:
        actions.append({"id": "condition-runtime-values", "tool": "runtime-debug-plan", "reason": "读取条件表达式缺失的运行时局部变量，再回填同一 frame 的条件 trace"})
    timeline = report.get("alert_timeline") if isinstance(report.get("alert_timeline"), Mapping) else {}
    source_status = {
        str(item.get("layer")): str(item.get("status"))
        for item in timeline.get("sources", []) or []
        if isinstance(item, Mapping)
    }
    output_policy = report.get("output_policy") if isinstance(report.get("output_policy"), Mapping) else {}
    if output_policy.get("can_required", True) and source_status.get("can_tx_observation") != "observed":
        actions.append({"id": "can-tx-observation", "tool": "code-gdb-plan", "reason": "当前还没有精确 CAN Tx 0→非零上升沿；继续解析真实 signal token 并生成可执行观测计划"})
    if source_status.get("objectlist_candidate") == "derived":
        actions.append({"id": "stamped-object-snapshot", "tool": "public-topic-plan", "reason": "objectlist 仍是 derived publication-order 关联；需要 callback/stamped snapshot 或 GDB 才能证明目标绝对同帧"})
    deduped: list[dict[str, Any]] = []
    seen_actions: set[tuple[str, str]] = set()
    for action in actions:
        if not isinstance(action, Mapping):
            continue
        key = (str(action.get("tool", "")), str(action.get("reason", "")))
        if key not in seen_actions:
            seen_actions.add(key)
            deduped.append(action)
    actions = deduped
    if not actions:
        actions.append({"id": "review-hypotheses", "tool": "diagnosis-panel", "reason": "基于当前证据解释候选根因，并由用户选择下一实验"})
    return actions


def _markdown(report: Mapping[str, Any]) -> str:
    identity = report.get("identity") if isinstance(report.get("identity"), Mapping) else {}
    overview = report.get("overview") if isinstance(report.get("overview"), Mapping) else {}
    output_policy = report.get("output_policy") if isinstance(report.get("output_policy"), Mapping) else {}
    lines = [
        "# CR60 Detailed Diagnostic Report",
        "",
        "> This is an evidence projection. Observed, derived and inferred values remain separate.",
        "",
        "## 1. Run and data",
        "",
        f"- case: `{identity.get('case_id', 'not_available')}`",
        f"- data: `{identity.get('data_name') or identity.get('bag') or 'not_available'}`",
        f"- source context: `{identity.get('source_context_id') or identity.get('source_snapshot_hash') or 'not_available'}`",
        f"- events: {overview.get('event_count', 0)}",
        f"- report status: `{report.get('status')}`",
        f"- alarm output endpoint: `{output_policy.get('effective_endpoint', 'not_available')}` (arbe visualization alarm-lamp output)",
        "",
        "## 2. Event map",
        "",
        "| event | function | side | radar | first frame | source |",
        "|---|---|---|---:|---:|---|",
    ]
    for event in report.get("event_index", []) or []:
        first = event.get("first_frame") if isinstance(event.get("first_frame"), Mapping) else {}
        lines.append(
            f"| `{event.get('event_id', '')}` | `{event.get('function', '')}` | `{event.get('side', '')}` | "
            f"{event.get('radar_id', '')} | `{first.get('frame_id', 'N/A')}` | `{event.get('source', '')}` |"
        )
    selected = report.get("selected_event")
    if isinstance(selected, Mapping):
        lines.extend(["", "## 3. Selected event detail", ""])
        summary = selected.get("summary") if isinstance(selected.get("summary"), Mapping) else {}
        narrative_preview = report.get("diagnostic_narrative") if isinstance(report.get("diagnostic_narrative"), Mapping) else {}
        lines.extend([
            f"- function/side/radar: `{summary.get('function')}` / `{summary.get('side')}` / `{summary.get('radar_id')}`",
            f"- first/selected frame: `{(summary.get('first_frame') or {}).get('frame_id', 'N/A')}` ({(summary.get('first_frame') or {}).get('definition', 'N/A')})",
            f"- target objID: `{summary.get('target_obj_id', 'N/A')}`",
            f"- runtime association: `{selected.get('runtime_association', 'not_provided')}`",
            f"- executive summary: {narrative_preview.get('executive_summary', 'not_available')}",
            "",
            "> Full selected-event fields are retained in `diagnostic-report.json`; they are not duplicated here.",
        ])
    narrative = report.get("diagnostic_narrative") if isinstance(report.get("diagnostic_narrative"), Mapping) else {}
    timeline = report.get("alert_timeline") if isinstance(report.get("alert_timeline"), Mapping) else {}
    if timeline:
        lines.extend(["", "## 4. Evidence-layer alert timeline", "", "| layer | signal/function | radar | frame | frame status | transition | value |", "|---|---|---:|---:|---|---|---:|"])
        for row in _timeline_display_rows(report):
            if not isinstance(row, Mapping):
                continue
            lines.append(
                f"| `{row.get('layer', '')}` | `{row.get('function') or row.get('signal') or ''}` | "
                f"{row.get('radar_id', '')} | `{row.get('frame_id', 'N/A')}` | `{row.get('frame_status', '')}` | "
                f"`{row.get('transition', '')}` | `{row.get('value', 'N/A')}` |"
            )
        lines.extend(["", "### Playback frame map", "", "| frame | time (sec) | state | alarm rows | alarm signals |", "|---:|---:|---|---:|---|"])
        narrative_scope = narrative.get("scope") if isinstance(narrative.get("scope"), Mapping) else {}
        selected_frame = str(narrative_scope.get("frame_id") or "")
        playback_items = [
            item for item in timeline.get("playback_frame_map", []) or []
            if isinstance(item, Mapping)
            and (not selected_frame or str(item.get("frame_id") or "") == selected_frame or item.get("alarm_rows"))
        ]
        for item in playback_items[:24]:
            if isinstance(item, Mapping):
                lines.append(f"| `{item.get('frame_id', '')}` | {item.get('time_sec', 'N/A')} | `{item.get('state', '')}` | {len(item.get('alarm_rows', []) or [])} | `{', '.join(str(value) for value in item.get('alarm_signals', []) or [])}` |")
        lines.extend(["", "### Layer comparisons", "", "| left | right | status | reason |", "|---|---|---|---|"])
        for item in timeline.get("comparisons", []) or []:
            if isinstance(item, Mapping):
                lines.append(f"| `{item.get('left', '')}` | `{item.get('right', '')}` | `{item.get('status', '')}` | {item.get('reason', '')} |")
    preflight_summary = report.get("arbe_preflight") if isinstance(report.get("arbe_preflight"), Mapping) else {}
    public_summary = preflight_summary.get("public_evidence") if isinstance(preflight_summary.get("public_evidence"), Mapping) else {}
    public_contract = public_summary.get("objectlist_frame_contract") if isinstance(public_summary.get("objectlist_frame_contract"), Mapping) else {}
    lines.extend(["", "## 4.1 Public runtime binding", ""])
    if public_contract:
        lines.extend([
            f"- source contract: `{public_contract.get('status', 'not_available')}`",
            f"- automatic association mode: `{public_contract.get('association_mode', 'strict')}`",
            f"- basis: {public_contract.get('basis', '')}",
            "",
            "| marker | source |",
            "|---|---|",
        ])
        for label, key in (
            ("callback", "callback"),
            ("objectlist publish", "objectlist_publish"),
            ("handler call", "objectlist_handler_call"),
            ("warning_with_frame publish", "warning_with_frame_publish"),
        ):
            ref = public_contract.get(key) if isinstance(public_contract.get(key), Mapping) else {}
            path = ref.get("path") or ref.get("file_path") or "source"
            line = ref.get("line")
            lines.append(f"| `{label}` | `{path}:{line if line not in (None, '') else 'N/A'}` |")
    else:
        lines.append("- status: `not_available`; no source proof for public object/frame correlation was provided.")
    assessment = narrative.get("alarm_assessment") if isinstance(narrative.get("alarm_assessment"), Mapping) else {}
    if narrative:
        lines.extend(["", "## 5. Diagnostic narrative", "", f"- should_alert: `{assessment.get('should_alert', 'indeterminate')}`", f"- status: `{assessment.get('status', 'insufficient_evidence')}`", f"- statement: {assessment.get('statement', '')}", f"- executive summary: {narrative.get('executive_summary', '')}", ""])
        for item in narrative.get("narrative", []) or []:
            lines.append(f"- {item}")
    runtime_facts = [item for item in narrative.get("runtime_facts", []) or [] if isinstance(item, Mapping)]
    if runtime_facts:
        lines.extend(["", "### Runtime/GDB fields", "", "| layer | frame | association | token | value | status |", "|---|---:|---|---|---|---|"])
        for field in runtime_facts:
            lines.append(f"| `{field.get('layer', '')}` | `{field.get('frame_id', 'N/A')}` | `{field.get('association', 'not_available')}` | `{field.get('token', '')}` | `{field.get('value', 'N/A')}` | `{field.get('status', 'not_available')}` |")
    trace = report.get("condition_trace") if isinstance(report.get("condition_trace"), Mapping) else {}
    if trace:
        display_conditions, condition_total = _condition_display_items(report)
        lines.extend(["", "## 6. Key alarm condition trace", "", f"> Showing {len(display_conditions)} / {condition_total} key source conditions. The complete condition-trace JSON remains the machine-readable source.", "", "| status | source | expression | substituted expression | reason |", "|---|---|---|---|---|"])
        for item in display_conditions:
            if not isinstance(item, Mapping):
                continue
            evaluation = item.get("evaluation") if isinstance(item.get("evaluation"), Mapping) else {}
            source_ref = item.get("source_ref") if isinstance(item.get("source_ref"), Mapping) else {}
            source = f"{source_ref.get('file_path', '')}:{source_ref.get('line', '')}"
            lines.append(
                f"| `{item.get('status') or evaluation.get('status', 'not_evaluable')}` | `{source}` | "
                f"`{str(item.get('expression', '')).replace('`', '')}` | "
                f"`{str(item.get('substituted_expression', '')).replace('`', '')}` | "
                f"{item.get('reason') or evaluation.get('reason', '')} |"
            )
    can_output = report.get("can_output") if isinstance(report.get("can_output"), Mapping) else {}
    can_output_signals = [item for item in can_output.get("signals", []) or [] if isinstance(item, Mapping)]
    lines.extend(["", "## 6.1 Source output chain", ""])
    if can_output_signals:
        lines.extend([
            "> The following external signal tokens are static candidates selected from the current source RteCom/WriteSignal mapping; runtime execution remains a separate evidence layer.",
            "",
            "| signal | source expression | source | evidence |",
            "|---|---|---|---|",
        ])
        for item in can_output_signals:
            source_ref = item.get("source_ref") if isinstance(item.get("source_ref"), Mapping) else {}
            source_path = source_ref.get("path") or source_ref.get("file_path") or "source"
            source_line = source_ref.get("line")
            source = f"{source_path}:{source_line}" if source_line not in (None, "") else str(source_path)
            lines.append(
                f"| `{str(item.get('signal', '')).replace('|', '\\|')}` | "
                f"`{str(item.get('expression', '')).replace('`', '').replace('|', '\\|')}` | "
                f"`{source.replace('|', '\\|')}` | `{item.get('status', 'source_candidate')}` |"
            )
    else:
        lines.append(f"- status: `{can_output.get('status', 'not_available')}`; no event-scoped source output candidate was selected.")
    selected_details = selected.get("details") if isinstance(selected, Mapping) and isinstance(selected.get("details"), Mapping) else {}
    debug_pack = selected_details.get("breakpoint_pack") if isinstance(selected_details.get("breakpoint_pack"), Mapping) else {}
    debug_breakpoints = [item for item in debug_pack.get("breakpoints", []) or [] if isinstance(item, Mapping)]
    if debug_breakpoints:
        lines.extend(["", "## 7. Debug anchors", "", "| function | source | condition |", "|---|---|---|"])
        for item in debug_breakpoints:
            location = item.get("location") if isinstance(item.get("location"), Mapping) else item
            source = f"{location.get('file', location.get('file_path', ''))}:{location.get('line', 'N/A')}"
            lines.append(f"| `{item.get('function', '')}` | `{source}` | `{str(item.get('condition', 'not_available')).replace('`', '')}` |")
    diagnosis = report.get("diagnosis") if isinstance(report.get("diagnosis"), Mapping) else {}
    conclusion = report.get("conclusion") if isinstance(report.get("conclusion"), Mapping) else {}
    if conclusion:
        lines.extend(["", "## 8. Evidence conclusion", "", f"- level: `{conclusion.get('level')}`", f"- status: `{conclusion.get('status')}`", f"- statement: {conclusion.get('statement', '')}", ""])
    lines.extend(["", "## 9. Diagnosis status", "", f"- status: `{diagnosis.get('status')}`", f"- policy: {diagnosis.get('interpretation_policy', '')}", ""])
    for gap in diagnosis.get("evidence_gaps", []) or []:
        if isinstance(gap, Mapping):
            lines.append(f"- gap `{gap.get('id')}` ({gap.get('status')}): {gap.get('reason')}")
    analysis = diagnosis.get("panel_result")
    if isinstance(analysis, Mapping):
        lines.extend(["", "### AI interpretation (inference)", "", "```json", json.dumps(analysis, ensure_ascii=False, indent=2, default=str), "```"])
    lines.extend(["", "## 10. Next actions", ""])
    for action in report.get("next_actions", []) or []:
        if isinstance(action, Mapping):
            lines.append(f"- `{action.get('tool')}` — {action.get('reason')}")
    analysis_trace = report.get("analysis_trace") if isinstance(report.get("analysis_trace"), Mapping) else {}
    lines.extend(["", "## 11. Analysis trail", "", f"- status: `{analysis_trace.get('status')}`", f"- steps: {analysis_trace.get('step_count', 0)}"])
    trace_steps = [item for item in analysis_trace.get("steps", []) or [] if isinstance(item, Mapping)]
    if trace_steps:
        lines.extend(["", "| stage | status | summary | observations | gaps | next actions |", "|---|---|---|---:|---:|---:|"])
        for step in trace_steps:
            lines.append(
                f"| `{step.get('stage', '')}` | `{step.get('status', '')}` | "
                f"{step.get('user_visible_summary', '')} | {step.get('observation_count', 0)} | "
                f"{step.get('gap_count', 0)} | {len(step.get('next_action_candidates', []) or [])} |"
            )
    hypotheses = [item for item in analysis_trace.get("hypotheses", []) or [] if isinstance(item, Mapping)]
    experiments = [item for item in analysis_trace.get("experiments", []) or [] if isinstance(item, Mapping)]
    user_observations = [item for item in analysis_trace.get("user_observations", []) or [] if isinstance(item, Mapping)]
    if hypotheses:
        lines.extend(["", "### Hypothesis Board", "", "| category | candidate | status | rank | support/contradict | required evidence |", "|---|---|---|---:|---:|---:|"])
        for item in hypotheses:
            lines.append(
                f"| `{item.get('category', '')}` | {str(item.get('statement', '')).replace('|', '\\|')} | "
                f"`{item.get('status', '')}` | {item.get('rank', '') or '—'} | "
                f"{item.get('supporting_claim_count', 0)}/{item.get('contradicting_claim_count', 0)} | "
                f"{item.get('required_evidence_count', 0)} |"
            )
    if experiments:
        lines.extend(["", "### Next Experiments", "", "| question | method | status | target | observations/deltas |", "|---|---|---|---|---:|"])
        for item in experiments:
            target = item.get("target") if isinstance(item.get("target"), Mapping) else {}
            target_text = ", ".join(f"{key}={target[key]}" for key in ("event_id", "radar_id", "frame_id", "object_id") if target.get(key) not in (None, "", []))
            lines.append(
                f"| {str(item.get('question', '')).replace('|', '\\|')} | `{item.get('method', '')}` | "
                f"`{item.get('status', '')}` | `{target_text or '—'}` | "
                f"{item.get('observation_count', 0)}/{item.get('conclusion_delta_count', 0)} |"
            )
    if user_observations:
        lines.extend(["", "### User observations", "", "| kind | summary | experiment | attachments |", "|---|---|---|---:|"])
        for item in user_observations:
            lines.append(
                f"| `{item.get('kind', '')}` | {str(item.get('summary', '')).replace('|', '\\|')} | "
                f"`{item.get('experiment_id', '') or '—'}` | {item.get('artifact_ref_count', 0)} |"
            )
    return "\n".join(lines) + "\n"


def _scene_svg(report: Mapping[str, Any]) -> str:
    """Render an evidence-only top view with the current x/y convention."""
    selected = report.get("selected_event") if isinstance(report.get("selected_event"), Mapping) else {}
    details = selected.get("details") if isinstance(selected.get("details"), Mapping) else {}
    ego = details.get("ego") if isinstance(details.get("ego"), Mapping) else {}
    target = details.get("target") if isinstance(details.get("target"), Mapping) else {}
    ego_points = [item for item in ego.get("polygon", []) or [] if isinstance(item, Mapping)]
    geometry = target.get("geometry") if isinstance(target.get("geometry"), Mapping) else {}
    target_points = [item for item in geometry.get("polygon", geometry.get("corners", [])) or [] if isinstance(item, Mapping)]
    runtime_geometry = _runtime_geometry(selected)
    if runtime_geometry.get("target_points"):
        target_points = runtime_geometry["target_points"]
    geometry_projection = report.get("geometry_projection") if isinstance(report.get("geometry_projection"), Mapping) else _geometry_projection(selected)
    predicted = geometry_projection.get("predicted_intersection") if isinstance(geometry_projection.get("predicted_intersection"), Mapping) else {}
    predicted_point = (
        predicted
        if isinstance(predicted.get("x"), (int, float)) and isinstance(predicted.get("y"), (int, float))
        else {}
    )
    roi_points: list[tuple[str, list[Mapping[str, Any]]]] = []
    for layer in details.get("roi_layers", []) or []:
        if not isinstance(layer, Mapping):
            continue
        polygons = layer.get("polygons") if isinstance(layer.get("polygons"), Mapping) else {}
        for side, points in polygons.items():
            if isinstance(points, list) and points:
                roi_points.append((f"{layer.get('feature', 'ROI')} {side}", [p for p in points if isinstance(p, Mapping)]))
    for label, points in runtime_geometry.get("roi_points", []) or []:
        if points:
            roi_points.append((label, points))
    all_points = ego_points + target_points + [point for _, points in roi_points for point in points]
    if predicted_point:
        all_points.append(predicted_point)
    numeric = [
        (float(point["x"]), float(point["y"]))
        for point in all_points
        if isinstance(point.get("x"), (int, float)) and isinstance(point.get("y"), (int, float))
    ]
    if not numeric:
        return '<div class="scene-empty">No same-frame polygon/ROI geometry is available. <code>containment_state=not_evaluated</code></div>'
    min_x = min(item[0] for item in numeric)
    max_x = max(item[0] for item in numeric)
    min_y = min(item[1] for item in numeric)
    max_y = max(item[1] for item in numeric)
    span_x = max(max_x - min_x, 1.0)
    span_y = max(max_y - min_y, 1.0)
    scale = min(760.0 / (span_y + 4.0), 390.0 / (span_x + 4.0))
    mid_x = (min_x + max_x) / 2.0
    mid_y = (min_y + max_y) / 2.0

    def point(item: Mapping[str, Any]) -> str:
        sx = 450.0 + (mid_y - float(item.get("y", 0.0))) * scale
        sy = 270.0 + (mid_x - float(item.get("x", 0.0))) * scale
        return f"{sx:.1f},{sy:.1f}"

    def poly(points: list[Mapping[str, Any]]) -> str:
        return " ".join(point(item) for item in points)

    ego_poly = poly(ego_points) if ego_points else ""
    target_poly = poly(target_points) if target_points else ""
    origin_x = 450.0 + mid_y * scale
    origin_y = 270.0 + mid_x * scale
    collision_status = str(geometry_projection.get("collision_status") or "not_evaluated")
    heading = geometry.get("heading_vector") if isinstance(geometry.get("heading_vector"), Mapping) else {}
    position = geometry.get("position") if isinstance(geometry.get("position"), Mapping) else {}
    arrow = ""
    if isinstance(position.get("x"), (int, float)) and isinstance(position.get("y"), (int, float)):
        hx = float(heading.get("x", 0.0) or 0.0)
        hy = float(heading.get("y", 0.0) or 0.0)
        length = max((hx * hx + hy * hy) ** 0.5, 1.0)
        end = {"x": float(position["x"]) + hx / length * 1.8, "y": float(position["y"]) + hy / length * 1.8}
        arrow = f'<line class="heading" x1="{point(position).split(",")[0]}" y1="{point(position).split(",")[1]}" x2="{point(end).split(",")[0]}" y2="{point(end).split(",")[1]}" marker-end="url(#arrow)" />'
    prediction_markup = ""
    prediction_text = ""
    if predicted_point:
        if target_points:
            center = {
                "x": sum(float(item.get("x", 0.0)) for item in target_points) / len(target_points),
                "y": sum(float(item.get("y", 0.0)) for item in target_points) / len(target_points),
            }
        else:
            center = predicted_point
        start = point(center).split(",")
        end = point(predicted_point).split(",")
        prediction_x_token = str(predicted.get("x_token") or "x")
        prediction_y_token = str(predicted.get("y_token") or "y")
        prediction_time_token = str(predicted.get("time_token") or "time")
        prediction_time_suffix = (
            " · " + html.escape(prediction_time_token) + "=" + _format_report_value(predicted.get("time")) + "s"
            if predicted.get("time") not in (None, "") else ""
        )
        prediction_markup = (
            f'<line class="prediction" x1="{start[0]}" y1="{start[1]}" '
            f'x2="{end[0]}" y2="{end[1]}" marker-end="url(#prediction-arrow)" />'
            f'<circle class="prediction-point" cx="{end[0]}" cy="{end[1]}" r="6" />'
            f'<text class="prediction-label" x="{float(end[0]) + 8:.1f}" y="{float(end[1]) - 8:.1f}">'
            f'predicted {html.escape(prediction_x_token)}={_format_report_value(predicted_point.get("x"))}, '
            f'{html.escape(prediction_y_token)}={_format_report_value(predicted_point.get("y"))}'
            f'{prediction_time_suffix}'
            '</text>'
        )
        prediction_text = (
            f'prediction: {prediction_x_token}={_format_report_value(predicted_point.get("x"))}, '
            f'{prediction_y_token}={_format_report_value(predicted_point.get("y"))}'
            f'{(" · " + prediction_time_token + "=" + _format_report_value(predicted.get("time")) + "s") if predicted.get("time") not in (None, "") else ""}'
        )
    roi_markup = "".join(
        f'<polygon class="{"roi-runtime" if label.startswith("runtime ") else "roi"}" points="{poly(points)}" /><text class="roi-label" x="{point(points[0]).split(",")[0]}" y="{float(point(points[0]).split(",")[1]) - 6:.1f}">{html.escape(label)}</text>'
        for label, points in roi_points if len(points) >= 2
    )
    target_point_markup = "".join(
        f'<circle class="target-corner" cx="{point(item).split(",")[0]}" cy="{point(item).split(",")[1]}" r="4" />'
        f'<text class="corner-label" x="{float(point(item).split(",")[0]) + 6:.1f}" y="{float(point(item).split(",")[1]) - 6:.1f}">{html.escape(str(item.get("label") or f"P{index}"))}</text>'
        for index, item in enumerate(target_points)
    )
    target_label = html.escape(str(target.get("obj_id", "target")))
    branch_text = ""
    branch = geometry_projection.get("algorithm_branch") if isinstance(geometry_projection.get("algorithm_branch"), Mapping) else {}
    if branch.get("expression"):
        branch_text = f' · gate: {branch.get("expression")}'
    return f'''<svg class="scene-svg" viewBox="0 0 900 540" role="img" aria-label="ego target and ROI top view">
<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" /></marker><marker id="prediction-arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path class="prediction-marker" d="M0,0 L8,4 L0,8 z" /></marker></defs>
<line class="axis" x1="{origin_x:.1f}" y1="30" x2="{origin_x:.1f}" y2="510" /><line class="axis" x1="30" y1="{origin_y:.1f}" x2="870" y2="{origin_y:.1f}" />
<text class="axis-label" x="{origin_x + 8:.1f}" y="42">+X forward</text><text class="axis-label" x="780" y="{origin_y - 8:.1f}">-Y right</text>
<text class="geometry-source" x="42" y="70">geometry: {html.escape(str(runtime_geometry.get("source", "static_or_not_available")))}</text>
<text class="collision-label" x="42" y="90">instantaneous: {html.escape(collision_status)}{html.escape(branch_text)}</text>
{f'<text class="prediction-label" x="42" y="110">{html.escape(prediction_text)}</text>' if prediction_text else ''}
{roi_markup}
{f'<polygon class="ego" points="{ego_poly}" />' if ego_poly else ''}
{f'<polygon class="target" points="{target_poly}" />' if target_poly else ''}
{target_point_markup}
{arrow}
{prediction_markup}
<text class="ego-label" x="{point(ego_points[0]).split(',')[0] if ego_points else 450}" y="{float(point(ego_points[0]).split(',')[1]) - 8 if ego_points else 500:.1f}">EGO</text>
<text class="target-label" x="{point(target_points[0]).split(',')[0] if target_points else 450}" y="{float(point(target_points[0]).split(',')[1]) - 8 if target_points else 120:.1f}">objID {target_label}</text>
</svg>'''


def _runtime_geometry(selected: Mapping[str, Any]) -> dict[str, Any]:
    """Select same-frame runtime polygons without changing static evidence."""
    if not isinstance(selected, Mapping):
        return {"source": "static_or_not_available", "layer": "", "frame_id": "", "association": "", "target_points": [], "roi_points": [], "roi_counts": []}
    summary = selected.get("summary") if isinstance(selected.get("summary"), Mapping) else {}
    first = summary.get("first_frame") if isinstance(summary.get("first_frame"), Mapping) else {}
    selected_frame = str(first.get("frame_id") or "")

    def points(value: Any) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        if not isinstance(value, list):
            return result
        for item in value:
            if isinstance(item, Mapping) and isinstance(item.get("x"), (int, float)) and isinstance(item.get("y"), (int, float)):
                result.append({"x": item["x"], "y": item["y"]})
            elif isinstance(item, (list, tuple)) and len(item) >= 2 and isinstance(item[0], (int, float)) and isinstance(item[1], (int, float)):
                result.append({"x": item[0], "y": item[1]})
        return result

    candidates: list[tuple[int, Mapping[str, Any]]] = []
    for observation in selected.get("runtime_observations", []) or []:
        if not isinstance(observation, Mapping):
            continue
        identity = observation.get("identity") if isinstance(observation.get("identity"), Mapping) else {}
        observation_frame = str(identity.get("frame_id") or observation.get("frame_id") or "")
        if selected_frame and observation_frame and observation_frame != selected_frame:
            continue
        layer = str(observation.get("layer") or "runtime_with_frame")
        rank = {"gdb_observation": 0, "runtime_with_frame": 1, "objectlist_candidate": 2}.get(layer, 3)
        geometry = observation.get("geometry") if isinstance(observation.get("geometry"), Mapping) else {}
        if geometry:
            candidates.append((rank, observation))
    candidates.sort(key=lambda item: item[0])
    for _, observation in candidates:
        geometry = observation.get("geometry") if isinstance(observation.get("geometry"), Mapping) else {}
        target_points = points(
            geometry.get("runtime_target_polygon")
            or geometry.get("target_polygon")
            or geometry.get("polygon")
            or geometry.get("corners")
        )
        roi_points: list[tuple[str, list[dict[str, Any]]]] = []
        roi_counts: list[dict[str, Any]] = []
        runtime_roi = geometry.get("runtime_roi") if isinstance(geometry.get("runtime_roi"), Mapping) else {}
        for name, value in runtime_roi.items():
            if not isinstance(value, Mapping):
                continue
            row = points(value.get("points"))
            if row:
                roi_points.append((f"runtime {name}", row))
                roi_counts.append({"name": str(name), "num": value.get("num") if value.get("num") not in (None, "") else len(row)})
        if target_points or roi_points:
            identity = observation.get("identity") if isinstance(observation.get("identity"), Mapping) else {}
            association = identity.get("frame_source") or observation.get("association_status")
            if not association and observation.get("layer") == "gdb_observation":
                association = "gdb_stop_exact_frame"
            return {
                "source": f"{observation.get('layer', 'runtime')} / {association or 'runtime'}",
                "layer": observation.get("layer", "runtime"),
                "frame_id": observation_frame,
                "association": association or "runtime",
                "object_id": identity.get("object_id"),
                "target_points": target_points,
                "roi_points": roi_points,
                "roi_counts": roi_counts,
            }
    return {"source": "static_or_not_available", "layer": "", "frame_id": "", "association": "", "target_points": [], "roi_points": [], "roi_counts": []}


def _runtime_numeric_fact(selected: Mapping[str, Any], token_names: Sequence[str]) -> dict[str, Any]:
    """Select a numeric runtime token for a derived scene annotation.

    This is intentionally a small read-model helper.  It does not calculate a
    feature result and it does not equate a local variable with a public field;
    it only selects an explicitly observed numeric token already present in the
    selected runtime observations.  Exact token spelling wins over a qualified
    token suffix, and GDB observations win over public/object-list projections.
    """
    wanted = {str(item).strip() for item in token_names if str(item).strip()}
    if not wanted or not isinstance(selected, Mapping):
        return {}
    candidates: list[tuple[int, int, int, Mapping[str, Any], Mapping[str, Any], str]] = []
    for observation_order, observation in enumerate(selected.get("runtime_observations", []) or []):
        if not isinstance(observation, Mapping):
            continue
        identity = observation.get("identity") if isinstance(observation.get("identity"), Mapping) else {}
        layer = str(observation.get("layer") or "")
        layer_rank = {"gdb_observation": 0, "runtime_with_frame": 1, "objectlist_candidate": 2}.get(layer, 3)
        for field_order, field in enumerate(_field_rows(observation.get("fields"))):
            token = str(field.get("token") or field.get("code_token") or field.get("access_path") or "").strip()
            if not token:
                continue
            normalized = token.replace("->", ".").replace("*", "")
            exact = 1 if token in wanted else 0
            suffix = normalized.rsplit(".", 1)[-1]
            if not exact and suffix not in wanted:
                continue
            value = field.get("value")
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                continue
            status = str(field.get("status") or "observed").lower()
            if status not in {"observed", "derived"}:
                continue
            candidates.append((layer_rank, -exact, -field_order, field, identity, str(observation.get("observation_id", ""))))
    if not candidates:
        return {}
    _, _, _, field, identity, observation_id = sorted(candidates, key=lambda item: (item[0], item[1], item[2]))[0]
    return {
        "token": str(field.get("token") or field.get("code_token") or field.get("access_path") or ""),
        "value": field.get("value"),
        "status": str(field.get("status") or "observed"),
        "source": deepcopy(field.get("source") or {}),
        "observation_id": observation_id,
        "frame_id": identity.get("frame_id") or identity.get("frame_counter"),
    }


def _runtime_prediction_token_candidates(selected: Mapping[str, Any]) -> dict[str, list[str]]:
    """Discover numeric prediction tokens from the current runtime evidence.

    The report does not own a feature rule table.  It only recognizes the
    source token families that describe a crossing/intersection point and an
    optional time-to-event value.  The actual spelling is selected from the
    current runtime artifact, so another project can use e.g.
    ``intersection_x``/``time_to_cross`` without changing the renderer.
    """
    patterns = {
        "x": re.compile(r"(?:f?inter(?:section)?|cross(?:ing)?point)x$", re.IGNORECASE),
        "y": re.compile(r"(?:f?inter(?:section)?|cross(?:ing)?point)y$", re.IGNORECASE),
        "time": re.compile(r"(?:f?ttm(?:x|y)?|time(?:to)?(?:cross|inter(?:section)?)?[xy]?)$", re.IGNORECASE),
    }
    candidates: dict[str, list[tuple[int, int, int, str]]] = {key: [] for key in patterns}
    for observation_order, observation in enumerate(selected.get("runtime_observations", []) or []):
        if not isinstance(observation, Mapping):
            continue
        for field_order, field in enumerate(_field_rows(observation.get("fields"))):
            token = str(field.get("token") or field.get("code_token") or field.get("access_path") or "").strip()
            if not token:
                continue
            value = field.get("value")
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                continue
            status = str(field.get("status") or "observed").lower()
            if status not in {"observed", "derived"}:
                continue
            normalized = token.replace("->", ".").replace("*", "")
            suffix = normalized.rsplit(".", 1)[-1]
            compact_suffix = re.sub(r"[_-]", "", suffix)
            for kind, pattern in patterns.items():
                if not pattern.fullmatch(compact_suffix):
                    continue
                # Prefer an unqualified scalar token (``fInterX``) over a
                # structure-qualified copy (``objInfo->...fInterX``). For a
                # time family, prefer the lateral/y crossing time when it is
                # available because the point's y coordinate is the quantity
                # being projected into a side ROI; this is geometry semantics,
                # not a feature-specific rule.
                canonical = 0 if normalized.lower() == suffix.lower() else 1
                axis_priority = (
                    0 if kind == "time" and compact_suffix.lower().endswith("y")
                    else 1 if kind == "time" and compact_suffix.lower().endswith("x")
                    else 2
                )
                candidates[kind].append((canonical, axis_priority, observation_order * 100000 + field_order, token))
    result: dict[str, list[str]] = {}
    for kind, rows in candidates.items():
        tokens: list[str] = []
        seen: set[str] = set()
        for _, _, _, token in sorted(rows, key=lambda item: (item[0], item[1], item[2])):
            if token in seen:
                continue
            seen.add(token)
            tokens.append(token)
        result[kind] = tokens
    return result


def _source_roi_branch_gate(
    condition_trace: Mapping[str, Any] | None,
    *,
    side: str,
    source_root: str = "",
) -> dict[str, Any]:
    """Describe a source ROI-availability branch when the current code proves it.

    The important distinction is between an ROI being configured/populated and
    the target polygon being inside it.  The report derives this description
    from the current condition/source text instead of embedding feature behavior.
    """
    rows = condition_trace.get("conditions", []) if isinstance(condition_trace, Mapping) else []
    if not isinstance(rows, list):
        return {}
    expected = "right" if str(side or "").upper() == "R" else "left" if str(side or "").upper() == "L" else ""
    candidates: list[Mapping[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        expression = str(row.get("expression") or "")
        if not re.search(r"[A-Za-z_]\w*Roi\s*->\s*num\s*>\s*0", expression, flags=re.IGNORECASE):
            continue
        if expected and expected not in expression.lower():
            continue
        candidates.append(row)
    if not candidates and expected:
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            expression = str(row.get("expression") or "")
            if re.search(r"[A-Za-z_]\w*Roi\s*->\s*num\s*>\s*0", expression, flags=re.IGNORECASE):
                candidates.append(row)
    if not candidates:
        return {}
    row = candidates[0]
    expression = str(row.get("expression") or "").strip()
    roi_match = re.search(r"(?P<roi>[A-Za-z_]\w*Roi)\s*->\s*num", expression, flags=re.IGNORECASE)
    roi_token = roi_match.group("roi") if roi_match else "ROI"
    evaluation = row.get("evaluation") if isinstance(row.get("evaluation"), Mapping) else {}
    gate: dict[str, Any] = {
        "status": str(evaluation.get("status") or "not_evaluated"),
        "condition_id": row.get("condition_id"),
        "roi_token": roi_token,
        "expression": expression,
        "source_ref": deepcopy(row.get("source_ref") or {}),
        "evaluation": deepcopy(dict(evaluation)),
        "meaning": "ROI availability gate; it is not a target-polygon containment test.",
    }
    source_ref = row.get("source_ref") if isinstance(row.get("source_ref"), Mapping) else {}
    try:
        line_number = int(source_ref.get("line") or 0)
    except (TypeError, ValueError):
        line_number = 0
    if source_root and source_ref.get("file_path") and line_number > 0:
        source_file = Path(str(source_ref["file_path"])).expanduser()
        if not source_file.is_absolute():
            source_file = Path(source_root).expanduser() / source_file
            if not source_file.exists() and str(source_ref["file_path"]).replace("\\", "/").startswith("src/"):
                source_file = Path(source_root).expanduser() / str(source_ref["file_path"])[4:]
        try:
            lines = source_file.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            lines = []
        for index in range(max(0, line_number - 1), min(len(lines), line_number + 10)):
            assignment = re.search(
                r"\b(?P<flag>(?:left|right)Flag)\s*=\s*(?:true|1)\b",
                lines[index],
                flags=re.IGNORECASE,
            )
            if assignment:
                gate["flag_token"] = assignment.group("flag")
                gate["source_assignment"] = {
                    "file_path": str(source_ref.get("file_path") or ""),
                    "line": index + 1,
                    "expression": lines[index].strip(),
                }
                gate["meaning"] = (
                    f"{gate['flag_token']} is enabled from {roi_token}->num > 0U; "
                    "the current source does not use this branch as a target-polygon containment test."
                )
                break
    return gate


def _xy_points(value: Any) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return points
    for item in value:
        if isinstance(item, Mapping) and isinstance(item.get("x"), (int, float)) and isinstance(item.get("y"), (int, float)):
            points.append((float(item["x"]), float(item["y"])))
        elif isinstance(item, Sequence) and not isinstance(item, (str, bytes)) and len(item) >= 2 and isinstance(item[0], (int, float)) and isinstance(item[1], (int, float)):
            points.append((float(item[0]), float(item[1])))
    return points


def _cross(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _point_on_segment(a: tuple[float, float], b: tuple[float, float], p: tuple[float, float], epsilon: float = 1e-9) -> bool:
    return abs(_cross(a, b, p)) <= epsilon and min(a[0], b[0]) - epsilon <= p[0] <= max(a[0], b[0]) + epsilon and min(a[1], b[1]) - epsilon <= p[1] <= max(a[1], b[1]) + epsilon


def _segments_intersect(
    a: tuple[float, float],
    b: tuple[float, float],
    c: tuple[float, float],
    d: tuple[float, float],
) -> bool:
    ab_c = _cross(a, b, c)
    ab_d = _cross(a, b, d)
    cd_a = _cross(c, d, a)
    cd_b = _cross(c, d, b)
    epsilon = 1e-9
    if ((ab_c > epsilon and ab_d < -epsilon) or (ab_c < -epsilon and ab_d > epsilon)) and ((cd_a > epsilon and cd_b < -epsilon) or (cd_a < -epsilon and cd_b > epsilon)):
        return True
    return (_point_on_segment(a, b, c) or _point_on_segment(a, b, d) or _point_on_segment(c, d, a) or _point_on_segment(c, d, b))


def _point_in_polygon(point: tuple[float, float], polygon: list[tuple[float, float]]) -> bool:
    if len(polygon) < 3:
        return False
    inside = False
    x, y = point
    for index, current in enumerate(polygon):
        previous = polygon[index - 1]
        if _point_on_segment(previous, current, point):
            return True
        if (current[1] > y) != (previous[1] > y):
            crossing_x = (previous[0] - current[0]) * (y - current[1]) / (previous[1] - current[1]) + current[0]
            if x < crossing_x:
                inside = not inside
    return inside


def _polygon_relation(left: Any, right: Any) -> str:
    """Return an observable geometric relation for two closed polygons."""
    first = _xy_points(left)
    second = _xy_points(right)
    if len(first) < 3 or len(second) < 3:
        return "not_evaluated"
    for index, point in enumerate(first):
        next_point = first[(index + 1) % len(first)]
        for other_index, other_point in enumerate(second):
            other_next = second[(other_index + 1) % len(second)]
            if _segments_intersect(point, next_point, other_point, other_next):
                return "intersects"
    if _point_in_polygon(first[0], second) or _point_in_polygon(second[0], first):
        return "intersects"
    return "disjoint"


def _feature_hint_from_function(function: Any) -> str:
    normalized = str(function or "").upper().replace("_", "")
    for token in ("FCTA", "FCTB", "RCTA", "RCTB", "RCW", "LCA", "BSD", "DOW"):
        if token in normalized:
            return token
    return ""


def _geometry_projection(
    selected: Mapping[str, Any] | None,
    *,
    condition_trace: Mapping[str, Any] | None = None,
    source_root: str = "",
) -> dict[str, Any]:
    """Expose geometry source/status as a machine-readable report field."""
    event = selected if isinstance(selected, Mapping) else {}
    details = event.get("details") if isinstance(event.get("details"), Mapping) else {}
    summary = event.get("summary") if isinstance(event.get("summary"), Mapping) else {}
    feature_hint = _feature_hint_from_function(summary.get("function"))
    side_hint = str(summary.get("side") or "").upper()
    target = details.get("target") if isinstance(details.get("target"), Mapping) else {}
    static_geometry = target.get("geometry") if isinstance(target.get("geometry"), Mapping) else {}
    static_target = static_geometry.get("polygon") or static_geometry.get("corners") or []
    static_roi: list[dict[str, Any]] = []
    for layer in details.get("roi_layers", []) if isinstance(details, Mapping) else []:
        if not isinstance(layer, Mapping):
            continue
        layer_feature = str(layer.get("feature") or "").upper()
        if feature_hint and layer_feature and layer_feature != feature_hint:
            continue
        polygons = layer.get("polygons") if isinstance(layer.get("polygons"), Mapping) else {}
        for name, points in polygons.items():
            if isinstance(points, list) and points:
                name_text = str(name)
                if side_hint in {"L", "R"} and name_text.lower() in {"left", "right"}:
                    expected_side = "left" if side_hint == "L" else "right"
                    if name_text.lower() != expected_side:
                        continue
                static_roi.append({"name": f"{layer.get('feature', 'ROI')} {name}", "points": deepcopy(points)})
    runtime = _runtime_geometry(event)
    runtime_available = bool(runtime.get("target_points") or runtime.get("roi_points"))
    if runtime_available:
        status = "runtime_observed_or_derived"
        source = runtime.get("source", "runtime")
    elif static_target or static_roi:
        status = "source_derived_or_profile"
        source = "static_event_projection"
    else:
        status = "not_evaluated"
        source = "not_available"
    runtime_target = deepcopy(runtime.get("target_points", []))
    runtime_roi = [
        {"name": name, "points": deepcopy(points)}
        for name, points in runtime.get("roi_points", []) or []
    ]
    roi_counts = {
        str(item.get("name")): item.get("num")
        for item in runtime.get("roi_counts", []) or []
        if isinstance(item, Mapping)
    }
    for item in runtime_roi:
        raw_name = str(item.get("name", "")).replace("runtime ", "", 1)
        if raw_name in roi_counts:
            item["num"] = roi_counts[raw_name]
    collision_evidence: list[dict[str, Any]] = []

    def add_relations(target_points: Any, roi_entries: list[Mapping[str, Any]], *, evidence_kind: str, frame_id: Any = None, association: str = "") -> list[str]:
        relations: list[str] = []
        for roi in roi_entries:
            relation = _polygon_relation(target_points, roi.get("points"))
            relations.append(relation)
            collision_evidence.append({
                "evidence_kind": evidence_kind,
                "roi": roi.get("name", "ROI"),
                "relation": relation,
                "roi_num": roi.get("num"),
                "frame_id": frame_id,
                "association": association,
                "coordinate_semantics": "x-forward,y-positive-left",
            })
        return relations

    runtime_relations: list[str] = []
    if runtime_target and runtime_roi:
        runtime_quality = "observed" if runtime.get("layer") in {"gdb_observation", "runtime_with_frame"} and runtime.get("association") not in {"", "not_available", "publication_order_derived"} else "derived"
        runtime_relations = add_relations(
            runtime_target,
            runtime_roi,
            evidence_kind=f"runtime_{runtime_quality}",
            frame_id=runtime.get("frame_id"),
            association=str(runtime.get("association") or ""),
        )
    static_relations: list[str] = []
    if not runtime_relations and static_target and static_roi:
        static_relations = add_relations(
            static_target,
            static_roi,
            evidence_kind="source_derived",
            frame_id=(static_geometry.get("source_ref") or {}).get("frame_id") if isinstance(static_geometry.get("source_ref"), Mapping) else None,
            association="source_projection_same_event",
        )
    relations = runtime_relations or static_relations
    if relations and all(item == "intersects" for item in relations):
        collision_status = ("observed" if runtime_relations and collision_evidence[0].get("evidence_kind") == "runtime_observed" else "source_derived") + "_intersects"
    elif relations and all(item == "disjoint" for item in relations):
        collision_status = ("observed" if runtime_relations and collision_evidence[0].get("evidence_kind") == "runtime_observed" else "source_derived") + "_disjoint"
    else:
        collision_status = "not_evaluated"
    prediction_tokens = _runtime_prediction_token_candidates(event)
    predicted_x = _runtime_numeric_fact(event, prediction_tokens.get("x", [])[:1])
    predicted_y = _runtime_numeric_fact(event, prediction_tokens.get("y", [])[:1])
    predicted_time = _runtime_numeric_fact(event, prediction_tokens.get("time", [])[:1])
    predicted_intersection: dict[str, Any] = {}
    if predicted_x and predicted_y:
        time_token = predicted_time.get("token") if predicted_time else ""
        time_value = predicted_time.get("value") if predicted_time else None
        predicted_intersection = {
            "x": predicted_x.get("value"),
            "y": predicted_y.get("value"),
            "time": time_value,
            "time_token": time_token,
            # Keep the historical key when the current source really uses
            # fTTMY; consumers can migrate to the generic time/time_token
            # pair without losing the existing report contract.
            "fTTMY": time_value if time_token.replace("->", ".").replace("*", "").rsplit(".", 1)[-1].lower() == "fttmy" else None,
            "status": "observed",
            "source_kind": "runtime_observed",
            "x_token": predicted_x.get("token"),
            "y_token": predicted_y.get("token"),
            "ttm_y_token": time_token,
            "prediction_token_candidates": prediction_tokens,
            "frame_id": predicted_x.get("frame_id") or predicted_y.get("frame_id"),
            "observation_id": predicted_x.get("observation_id") or predicted_y.get("observation_id"),
        }
        if runtime_roi:
            predicted_intersection["roi_relations"] = [
                {
                    "roi": item.get("name", "ROI"),
                    "relation": "on_or_inside" if _point_in_polygon(
                        (float(predicted_intersection["x"]), float(predicted_intersection["y"])),
                        _xy_points(item.get("points")),
                    ) else "outside",
                }
                for item in runtime_roi
                if isinstance(item, Mapping) and len(_xy_points(item.get("points"))) >= 3
            ]
    algorithm_branch = _source_roi_branch_gate(
        condition_trace,
        side=side_hint,
        source_root=source_root,
    )
    return {
        "status": status,
        "source": source,
        "runtime_target_polygon": runtime_target,
        "runtime_roi": runtime_roi,
        "static_target_polygon": deepcopy(static_target),
        "static_roi": static_roi,
        "collision_status": collision_status,
        "instantaneous_relation": collision_status,
        "collision_evidence": collision_evidence,
        "predicted_intersection": predicted_intersection,
        "algorithm_branch": algorithm_branch,
        "collision_policy": "current polygon/ROI relation and code prediction are separate evidence; ROI availability/TTM branch logic is never replaced by direct polygon containment",
    }


def _format_report_value(value: Any) -> str:
    if value is None:
        return "not_available"
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def _parameter_table_html(report: Mapping[str, Any]) -> str:
    """Render one structured table for the selected operating point.

    The table is deliberately a projection, not a second source of truth.
    Static/input facts, source operands and runtime observations keep their
    own evidence labels so equal-looking values are not silently merged.
    """
    selected = report.get("selected_event") if isinstance(report.get("selected_event"), Mapping) else {}
    narrative = report.get("diagnostic_narrative") if isinstance(report.get("diagnostic_narrative"), Mapping) else {}
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()

    def status_label(value: Any) -> str:
        return {
            "observed_in_bag": "已获取",
            "observed_runtime_input": "已获取",
            "derived_runtime_mapping": "已映射",
            "observed": "已获取",
            "derived": "已计算",
            "bound": "已代入",
            "not_evaluable": "无法确认",
            "not_found": "未找到",
            "not_available": "不可用",
            "unsupported": "暂不支持",
        }.get(str(value or ""), str(value or "未确认"))

    def source_text(value: Any) -> str:
        if not isinstance(value, Mapping):
            return str(value or "not_available")
        if value.get("topic"):
            suffix = f" frame={value.get('frame_id')}" if value.get("frame_id") not in (None, "") else ""
            return f"录制数据 · {value.get('topic')}{suffix}"
        if value.get("file_path") or value.get("line") not in (None, ""):
            return f"当前代码 · {value.get('file_path', 'source')}:{value.get('line', 'N/A')}"
        if value.get("kind"):
            kind = str(value.get("kind")).lower()
            return {
                "gdb_expression": "GDB 表达式",
                "gdb_locals": "GDB 局部变量",
                "gdb_struct_parse": "GDB 结构体",
                "ros_public_warning": "算法运行输出",
                "ros_public_radar_info": "算法运行自车信息",
                "ros_public_objectlist": "算法运行目标信息",
                "runtime_observed": "运行态计算",
            }.get(kind, str(value.get("kind")))
        return "not_available"

    def add(
        group: str,
        role: str,
        item: Mapping[str, Any],
        *,
        token: Any = None,
        value: Any = None,
        unit: Any = None,
        status: Any = None,
        source: Any = None,
        frame: Any = None,
    ) -> None:
        actual_token = str(token if token not in (None, "") else item.get("token") or item.get("code_token") or item.get("access_path") or "").strip()
        if not actual_token:
            return
        actual_value = item.get("value") if value is None else value
        actual_status = str(status if status not in (None, "") else item.get("status") or item.get("source_kind") or "not_available")
        key = (group, actual_token, repr(actual_value), actual_status)
        if key in seen:
            return
        seen.add(key)
        rows.append({
            "group": group,
            "role": role,
            "token": actual_token,
            "value": actual_value,
            "unit": unit if unit not in (None, "") else item.get("unit"),
            "status": actual_status,
            "source": source if source not in (None, "") else item.get("source") or item.get("source_ref") or item.get("code_ref"),
            "frame": frame if frame not in (None, "") else item.get("frame_id"),
        })

    operating = narrative.get("operating_condition") if isinstance(narrative.get("operating_condition"), Mapping) else {}
    for key, label, role in (("ego", "自车", "输入工况"), ("target", "目标", "输入工况")):
        for item in operating.get(key, []) or []:
            if isinstance(item, Mapping):
                add(label, role, item)

    condition_items = [item for item in narrative.get("condition_items", []) or [] if isinstance(item, Mapping)]
    for condition in condition_items:
        source_ref = condition.get("source_ref") if isinstance(condition.get("source_ref"), Mapping) else {}
        line_text = f"{source_ref.get('file_path', 'source')}:{source_ref.get('line', 'N/A')}"
        for binding in condition.get("bindings", []) or []:
            if not isinstance(binding, Mapping) or binding.get("status") != "bound":
                continue
            binding_item = dict(binding)
            binding_item["source"] = binding.get("source") or binding.get("source_ref") or binding.get("code_ref") or line_text
            binding_item["frame_id"] = selected.get("summary", {}).get("first_frame", {}).get("frame_id") if isinstance(selected.get("summary"), Mapping) and isinstance(selected.get("summary", {}).get("first_frame"), Mapping) else None
            add("源码参数/条件", f"条件 {line_text}", binding_item)

    geometry = report.get("geometry_projection") if isinstance(report.get("geometry_projection"), Mapping) else {}
    prediction = geometry.get("predicted_intersection") if isinstance(geometry.get("predicted_intersection"), Mapping) else {}
    if prediction.get("x") not in (None, ""):
        add("几何/预测", "预测交点", prediction, token=prediction.get("x_token"), value=prediction.get("x"), source={"kind": prediction.get("source_kind"), "observation_id": prediction.get("observation_id")}, frame=prediction.get("frame_id"))
    if prediction.get("y") not in (None, ""):
        add("几何/预测", "预测交点", prediction, token=prediction.get("y_token"), value=prediction.get("y"), source={"kind": prediction.get("source_kind"), "observation_id": prediction.get("observation_id")}, frame=prediction.get("frame_id"))
    if prediction.get("time") not in (None, ""):
        add("几何/预测", "预测时间", prediction, token=prediction.get("time_token"), value=prediction.get("time"), unit="s", source={"kind": prediction.get("source_kind"), "observation_id": prediction.get("observation_id")}, frame=prediction.get("frame_id"))

    for item in narrative.get("runtime_facts", []) or []:
        if isinstance(item, Mapping):
            add("runtime 中间量", str(item.get("layer") or "runtime"), item)

    if not rows:
        return '<div class="scene-empty">No parameter or operating-point facts are available.</div>'
    markup: list[str] = []
    for item in rows[:72]:
        source = source_text(item.get("source"))
        if item.get("frame") not in (None, "") and "frame=" not in source:
            source = f"{source} · frame={item.get('frame')}"
        unit = f" {item.get('unit')}" if item.get("unit") not in (None, "") else ""
        markup.append(
            f'<tr><td>{html.escape(str(item.get("group")))}</td><td>{html.escape(str(item.get("role")))}</td>'
            f'<td><code>{html.escape(str(item.get("token")))}</code></td><td>{html.escape(_format_report_value(item.get("value")) + unit)}</td>'
            f'<td><span class="status {html.escape(str(item.get("status"))) }" title="{html.escape(str(item.get("status")))}">{html.escape(status_label(item.get("status")))}</span></td>'
            f'<td>{html.escape(source)}</td></tr>'
        )
    truncated = len(rows) > 72
    note = f'<div class="meta">Showing 72 / {len(rows)} unique operating/source/runtime facts; complete fields remain in the selected event artifact.</div>' if truncated else '<div class="meta">Static input, source parameter and runtime facts are kept as separate evidence rows; same values are not silently merged across layers.</div>'
    style = '<style>.parameter-scroll{max-height:560px;overflow:auto;border:1px solid var(--line);border-radius:10px}.parameter-table{min-width:980px}.parameter-table thead th{position:sticky;top:0;background:#121c1a;z-index:1}.parameter-table th:nth-child(1){width:120px}.parameter-table th:nth-child(2){width:150px}.parameter-table th:nth-child(3){width:31%}.parameter-table th:nth-child(4){width:15%}.parameter-table th:nth-child(5){width:120px}.parameter-table th:nth-child(6){width:24%}.parameter-table tbody tr:hover{background:#16241f}</style>'
    return (
        style + '<div class="parameter-scroll"><table class="parameter-table"><thead><tr><th>类别</th><th>用途</th><th>真实 code token</th><th>数值</th><th>数据状态</th><th>数据来源</th></tr></thead>'
        + f'<tbody>{"".join(markup)}</tbody></table></div>' + note
    )


def _condition_chain_table_html(report: Mapping[str, Any]) -> str:
    """Render the bounded, source-ordered condition chain as a table."""
    story = report.get("diagnostic_story") if isinstance(report.get("diagnostic_story"), Mapping) else {}
    walk = story.get("condition_walk") if isinstance(story.get("condition_walk"), Mapping) else {}
    steps = [item for item in walk.get("steps", []) or [] if isinstance(item, Mapping)]
    if not steps:
        return '<div class="scene-empty">当前没有可呈现的 source condition chain。</div>'

    status_labels = {
        "satisfied": "成立",
        "not_satisfied": "未成立",
        "not_evaluable": "无法确认",
        "unsupported": "暂不支持",
    }
    markup: list[str] = []
    for item in steps:
        status = str(item.get("status") or "not_evaluable")
        function = html.escape(str(item.get("chain_function") or "当前 source"))
        source = html.escape(str(item.get("source") or ""))
        function_cell = f"<strong>{function}</strong>" + (f'<div class="meta">{source}</div>' if source and source != function else "")
        prose = html.escape(str(item.get("prose") or "当前条件没有可呈现的自然语言说明。"))
        bindings = []
        for binding in item.get("bindings", []) or []:
            if not isinstance(binding, Mapping) or binding.get("status") != "bound":
                continue
            token = str(binding.get("token") or "token")
            value = _format_report_value(binding.get("value"))
            bindings.append(f"{token}={value}")
        binding_text = html.escape("；".join(bindings[:8]) or "无可确认的同帧值")
        source_detail = (
            f'<details><summary>查看源码表达式</summary><div class="story-code">'
            f'<div><code>{source}</code></div><code>{html.escape(str(item.get("expression") or "not_available"))}</code>'
            f'<br><span>代入后：</span><code>{html.escape(str(item.get("substituted_expression") or "not_available"))}</code></div></details>'
        )
        markup.append(
            f'<tr><td>{html.escape(str(item.get("order") or ""))}</td>'
            f'<td>{function_cell}</td>'
            f'<td>{prose}{source_detail}</td>'
            f'<td><code>{binding_text}</code></td>'
            f'<td><span class="status {html.escape(status)}">{html.escape(status_labels.get(status, status))}</span></td></tr>'
        )
    style = '<style>.condition-chain-scroll{max-height:460px;overflow:auto;border:1px solid var(--line);border-radius:10px}.condition-chain-table{min-width:1120px}.condition-chain-table thead th{position:sticky;top:0;background:#121c1a;z-index:1}.condition-chain-table th:nth-child(1){width:58px}.condition-chain-table th:nth-child(2){width:180px}.condition-chain-table th:nth-child(3){width:38%}.condition-chain-table th:nth-child(4){width:38%}.condition-chain-table th:nth-child(5){width:100px}.condition-chain-table td code{white-space:pre-wrap}</style>'
    counts = walk.get("counts") if isinstance(walk.get("counts"), Mapping) else {}
    count_text = "、".join(
        f"{label}={counts.get(key, 0)}"
        for key, label in (("satisfied", "成立"), ("not_satisfied", "未成立"), ("not_evaluable", "无法确认"), ("unsupported", "暂不支持"))
        if counts.get(key, 0)
    )
    note = f'<div class="meta">按当前 source 条件链展示 {len(steps)} 条关键条件；{html.escape(count_text) if count_text else "没有求值结果"}。完整链路保留在 condition-trace artifact。</div>'
    return style + '<div class="condition-chain-scroll"><table class="condition-chain-table"><thead><tr><th>顺序</th><th>源码函数/位置</th><th>自然语言判断</th><th>关键同帧值</th><th>结果</th></tr></thead><tbody>' + "".join(markup) + '</tbody></table></div>' + note


def _execution_context_html(report: Mapping[str, Any]) -> str:
    context = report.get("execution_context") if isinstance(report.get("execution_context"), Mapping) else {}
    if not context:
        return '<div class="scene-empty">No replay/GDB execution context is available.</div>'
    warmup = context.get("warmup") if isinstance(context.get("warmup"), Mapping) else {}
    warmup_text = "未使用预热"
    if warmup:
        warmup_text = (
            f"{warmup.get('actual_frames', warmup.get('requested_frames', ''))} 帧，"
            f"frame {warmup.get('start_frame_id', 'N/A')} → {warmup.get('target_frame_id', 'N/A')}"
        )
    gdb_status = "GDB 已确认命中" if context.get("gdb_actual_hit") else "GDB 未确认命中"
    rows = [
        ("输入数据", "录制 bag" if context.get("data_source") else "未确认"),
        ("算法运行", context.get("algorithm_execution") or "未确认"),
        ("仿真模式", f"HILMODEL={context.get('hilmodel', '未确认')} · {context.get('replay_mode_label', '未确认')}"),
        ("预热帧", warmup_text),
        ("GDB", f"{gdb_status} · {context.get('gdb_status', '未确认')}"),
        ("算法报警灯输入", f"{context.get('algorithm_warning_source', '未确认')} → {context.get('algorithm_warning_topic', '未确认')}"),
        ("逐帧定位通道", context.get("algorithm_warning_with_frame_topic") or "未确认"),
    ]
    return (
        '<table class="execution-table"><thead><tr><th>项目</th><th>本次实际使用</th></tr></thead><tbody>'
        + "".join(f'<tr><td>{html.escape(str(key))}</td><td>{html.escape(str(value))}</td></tr>' for key, value in rows)
        + '</tbody></table>'
        + f'<div class="meta">{html.escape(str(context.get("statement") or ""))}</div>'
    )


def _diagnostic_story_html(report: Mapping[str, Any]) -> str:
    """Render the human-readable alarm path without exposing internal layers."""
    story = report.get("diagnostic_story") if isinstance(report.get("diagnostic_story"), Mapping) else {}
    if not story:
        narrative = report.get("diagnostic_narrative") if isinstance(report.get("diagnostic_narrative"), Mapping) else {}
        story = narrative.get("diagnostic_story") if isinstance(narrative.get("diagnostic_story"), Mapping) else {}
    if not story:
        return '<div class="scene-empty">No evidence-bound narrative is available.</div>'

    def status_label(status: Any) -> str:
        return {
            "satisfied": "成立",
            "not_satisfied": "未成立",
            "not_evaluable": "无法确认",
            "unsupported": "暂不支持求值",
            "yes_observed": "已观察到报警",
            "algorithm_output_observed": "算法输出已观察",
            "can_tx_observed": "CAN 输出已观察",
            "runtime_observed": "运行时已观察",
            "observed_zero_or_unknown": "已获取但未确认报警值",
            "source_candidate": "源码候选",
            "source_mapping_candidate": "源码映射候选",
            "algorithm_observed_source_mapping_candidate": "算法已观察 / 映射为源码候选",
            "partially_runtime_observed": "部分运行时已观察",
            "not_scanned": "尚未扫描",
            "not_found": "源码未找到",
            "partial": "部分可确认",
            "confirmed": "已确认",
            "observed": "已获取",
            "ready": "已完成",
        }.get(str(status or ""), str(status or "未确认"))

    def badge(status: Any) -> str:
        return f'<span class="status {html.escape(str(status or "not_evaluated"))}">{html.escape(status_label(status))}</span>'

    def alert_label(value: Any) -> str:
        return {
            "yes_observed": "已观察到报警",
            "supported_yes": "代码条件支持报警",
            "indeterminate": "暂不能确定",
            "no_observed": "未观察到报警",
        }.get(str(value or ""), str(value or "暂不能确定"))

    def binding_text(bindings: Any) -> str:
        values = []
        for item in bindings or []:
            if not isinstance(item, Mapping) or item.get("status") != "bound":
                continue
            token = str(item.get("token") or item.get("code_token") or "token")
            value = _format_report_value(item.get("value"))
            unit = f" {item.get('unit')}" if item.get("unit") else ""
            values.append(f"{token}={value}{unit}")
        return "；".join(values)

    operating = story.get("operating_condition") if isinstance(story.get("operating_condition"), Mapping) else {}
    code_path = story.get("code_path") if isinstance(story.get("code_path"), Mapping) else {}
    condition_walk = story.get("condition_walk") if isinstance(story.get("condition_walk"), Mapping) else {}
    geometry = story.get("geometry") if isinstance(story.get("geometry"), Mapping) else {}
    output = story.get("output") if isinstance(story.get("output"), Mapping) else {}
    output_chain = story.get("output_chain") if isinstance(story.get("output_chain"), Mapping) else {}
    conclusion = story.get("conclusion") if isinstance(story.get("conclusion"), Mapping) else {}
    gdb = report.get("gdb_confirmation") if isinstance(report.get("gdb_confirmation"), Mapping) else {}
    condition_cards: list[str] = []
    for item in condition_walk.get("steps", []) or []:
        if not isinstance(item, Mapping):
            continue
        source = html.escape(str(item.get("source") or "source"))
        bindings = binding_text(item.get("bindings"))
        binding_markup = f'<div class="story-bindings">变量代入：<code>{html.escape(bindings)}</code></div>' if bindings else ""
        missing = [str(value) for value in item.get("missing_tokens", []) or []]
        missing_markup = f'<div class="story-missing">缺少同帧变量：{html.escape(", ".join(missing))}</div>' if missing else ""
        condition_cards.append(
            f'<li class="story-condition"><div class="story-condition-head"><span>第 {html.escape(str(item.get("order")))} 步 · {html.escape(str(item.get("category_label") or "源码条件"))}</span>{badge(item.get("status"))}</div>'
            f'<p>{html.escape(str(item.get("prose") or ""))}</p>{binding_markup}{missing_markup}'
            f'<details><summary>查看源码条件</summary><div class="story-code"><div><code>{source}</code></div><code>{html.escape(str(item.get("expression") or "not_available"))}</code><br><span>代入后：</span><code>{html.escape(str(item.get("substituted_expression") or "not_available"))}</code></div></details></li>'
        )
    conditions_block = (
        '<ol class="story-conditions">' + "".join(condition_cards) + '</ol>'
        if condition_cards else '<div class="story-muted">当前没有可确认的源码条件。</div>'
    )
    prediction = geometry.get("prediction") if isinstance(geometry.get("prediction"), Mapping) else {}
    prediction_line = ""
    if prediction.get("x") not in (None, "") and prediction.get("y") not in (None, ""):
        prediction_line = (
            f'<div class="story-facts"><code>{html.escape(str(prediction.get("x_token") or "x"))}={html.escape(_format_report_value(prediction.get("x")))}</code> · '
            f'<code>{html.escape(str(prediction.get("y_token") or "y"))}={html.escape(_format_report_value(prediction.get("y")))}</code>'
            + (
                f' · <code>{html.escape(str(prediction.get("time_token") or "time"))}={html.escape(_format_report_value(prediction.get("time")))}s</code>'
                if prediction.get("time") not in (None, "") else ""
            )
            + '</div>'
        )
    output_policy = output.get("policy") if isinstance(output.get("policy"), Mapping) else {}
    gdb_location = gdb.get("source_location") if isinstance(gdb.get("source_location"), Mapping) else {}
    gdb_location_text = (
        f'{gdb_location.get("file") or gdb_location.get("file_path")}:{gdb_location.get("line")}'
        if (gdb_location.get("file") or gdb_location.get("file_path")) and gdb_location.get("line") not in (None, "")
        else "当前 source location 未提供"
    )
    gdb_edge_text = ""
    if gdb.get("algorithm_rising_frame") not in (None, ""):
        relation = str(gdb.get("frame_relation_to_algorithm_rise") or "")
        relation_label = "与算法上升沿同帧" if relation == "same_as_algorithm_rise" else f"算法上升沿之后 {relation.split('_', 1)[0]} 帧" if relation.endswith("_frames_after_algorithm_rise") else f"算法上升沿之前 {relation.split('_', 1)[0]} 帧" if relation.endswith("_frames_before_algorithm_rise") else "与算法上升沿无法对齐"
        gdb_edge_text = f"；算法输出上升沿：frame={gdb.get('algorithm_rising_frame')}（{relation_label}）"
    gdb_field_markup = "".join(
        f'<span class="flow-chip"><code>{html.escape(str(item.get("token")))}</code>={html.escape(_format_report_value(item.get("value")))}</span>'
        for item in gdb.get("captured_fields", [])[:16]
        if isinstance(item, Mapping)
    )
    gdb_block = (
        f'<div class="story-gdb" style="margin-top:10px;padding:10px;border:1px dashed var(--line);border-radius:9px;background:#0d1916"><div><strong>GDB 命中确认</strong> {badge(gdb.get("status"))}</div>'
        f'<p>{html.escape(str(gdb.get("statement") or "当前没有可确认的 GDB 结果。"))}</p>'
        f'<p>命中位置：<code>{html.escape(gdb_location_text)}</code>；帧：<code>{html.escape(str(gdb.get("frame_id") or "未确认"))}</code>；目标：<code>objID={html.escape(str(gdb.get("object_id") or "未确认"))}</code>；已获取字段：{html.escape(str(gdb.get("observed_field_count", 0)))}{html.escape(gdb_edge_text)}</p>'
        + (f'<div class="story-facts">{gdb_field_markup}</div>' if gdb_field_markup else "")
        + (f'<p class="story-muted">部分 GDB 探针不可用（{html.escape(str(gdb.get("missing_probe_count", 0)))} 个），这只表示变量缺口，不覆盖已经获取的字段。</p>' if gdb.get("missing_probe_count") else "")
        + '</div>'
    ) if gdb else '<div class="story-gdb" style="margin-top:10px;padding:10px;border:1px dashed var(--line);border-radius:9px;background:#0d1916"><strong>GDB 命中确认</strong><p class="story-muted">当前报告没有 GDB 运行证据。</p></div>'
    output_chain_cards: list[str] = []
    for item in output_chain.get("steps", []) or []:
        if not isinstance(item, Mapping):
            continue
        source_ref = item.get("source_ref") if isinstance(item.get("source_ref"), Mapping) else {}
        if not source_ref:
            source_ref = item.get("send_ref") if isinstance(item.get("send_ref"), Mapping) else {}
        location = ""
        if source_ref.get("path") and source_ref.get("line") not in (None, ""):
            location = f' <code>{html.escape(str(source_ref.get("path")))}:{html.escape(str(source_ref.get("line")))}</code>'
        primary_assignment = item.get("primary_assignment") if isinstance(item.get("primary_assignment"), Mapping) else {}
        assignment_markup = ""
        if primary_assignment:
            assignment_ref = primary_assignment.get("source_ref") if isinstance(primary_assignment.get("source_ref"), Mapping) else {}
            assignment_location = (
                f'{assignment_ref.get("path")}:{assignment_ref.get("line")}'
                if assignment_ref.get("path") and assignment_ref.get("line") not in (None, "")
                else "source"
            )
            assignment_markup = (
                f'<div class="story-bindings">生产赋值候选：<code>{html.escape(str(primary_assignment.get("snippet") or primary_assignment.get("rhs") or "not_available"))}</code>'
                f' · {html.escape(assignment_location)}</div>'
            )
        output_chain_cards.append(
            f'<li class="story-output-step"><div class="story-condition-head"><span>{html.escape(str(item.get("kind") or "output"))} · <code>{html.escape(str(item.get("token") or item.get("signal") or "not_available"))}</code>{location}</span>{badge(item.get("status"))}</div>'
            f'<p>{html.escape(str(item.get("text") or ""))}</p>{assignment_markup}</li>'
        )
    output_chain_markup = (
        f'<div class="story-output-status">{badge(output_chain.get("status"))} · '
        f'算法输出之后的源码/运行时链路</div><ol class="story-output-chain">{"".join(output_chain_cards)}</ol>'
        if output_chain_cards
        else '<div class="story-muted">当前没有可确认的算法输出后续映射。</div>'
    )
    style = '<style>.story-shell{display:grid;gap:12px}.story-lead,.story-panel,.story-conclusion{border:1px solid var(--line);border-radius:10px;padding:14px;background:#0b1513}.story-lead{border-left:3px solid var(--accent);font-size:15px;line-height:1.8;color:var(--ink)}.story-panel h3{margin:0 0 6px;color:var(--ink)}.story-panel>p{margin:0 0 10px}.story-conditions,.story-output-chain{display:grid;gap:8px;margin:0;padding-left:0;list-style:none;max-height:760px;overflow:auto}.story-condition,.story-output-step{border:1px solid var(--line);border-radius:9px;padding:11px;background:#101b18}.story-condition-head{display:flex;justify-content:space-between;gap:10px;align-items:center;color:var(--ink);font-weight:600}.story-condition p,.story-output-step p{margin:8px 0;color:var(--ink);line-height:1.75}.story-bindings,.story-missing{font-size:12px;margin-top:6px;color:var(--muted);overflow-wrap:anywhere}.story-missing{color:var(--warn)}.story-code{margin-top:8px;padding:9px;background:#08100e;border-radius:8px;overflow:auto;line-height:1.8}.story-facts{margin-top:8px;display:flex;flex-wrap:wrap;gap:7px;color:var(--accent)}.story-facts code{border:1px solid var(--line);border-radius:999px;padding:4px 8px;background:#101d19}.story-output-status{margin:8px 0;color:var(--muted)}.story-output-step{border-left:2px solid #547d6e}.story-conclusion{border-color:#3e9e7e;background:#0d1d18}.story-conclusion p{margin:6px 0 0;color:var(--ink);line-height:1.8;white-space:pre-line}.story-muted{color:var(--muted);font-size:12px}</style>'
    return (
        style + '<div class="story-shell">'
        + f'<div class="story-lead">{html.escape(str(operating.get("text") or "当前工况信息不足。"))}</div>'
        + f'<div class="story-panel"><h3>1 · 进入哪条代码路径</h3><p>{html.escape(str(code_path.get("text") or "当前没有可确认的函数调用路径。"))}</p>{gdb_block}</div>'
        + f'<div class="story-panel"><h3>2 · 代码条件如何命中</h3><p>{html.escape(str(condition_walk.get("text") or "按源码条件和同帧变量逐步判断。"))}</p>{conditions_block}</div>'
        + f'<div class="story-panel"><h3>3 · 当前空间关系和预测</h3><p>{html.escape(str(geometry.get("text") or "当前没有足够几何数据。"))}</p>{prediction_line}</div>'
         + f'<div class="story-panel"><h3>4 · 最终报警结论</h3><div class="story-conclusion">{badge(output.get("status"))}<span class="flow-decision-label">{html.escape(alert_label(output.get("should_alert")))}</span><p>{html.escape(str(output.get("text") or "当前没有足够证据形成最终结论。"))}</p><p class="story-muted">本次判断终点：{html.escape("arbe 报警灯对应算法最终输出" if output_policy.get("effective_endpoint") == "algorithm" else "CAN 输出" if output_policy.get("effective_endpoint") == "can_tx" else "未确定")}。</p></div><p><strong>结论：</strong>{html.escape(str(conclusion.get("text") or output.get("text") or "当前无法形成结论。"))}</p></div>'
         + f'<div class="story-panel"><h3>5 · 算法输出之后的 FCT / 对外映射</h3><p>这里继续沿当前 source 说明算法报警值如何进入内部状态和对外 signal；源码候选不会被冒充成同帧运行时事实。</p>{output_chain_markup}</div>'
        + '</div>'
    )


def _fact_table_html(report: Mapping[str, Any]) -> str:
    """Render the compact operating-condition facts using real source tokens."""
    selected = report.get("selected_event") if isinstance(report.get("selected_event"), Mapping) else {}
    details = selected.get("details") if isinstance(selected.get("details"), Mapping) else {}
    narrative = report.get("diagnostic_narrative") if isinstance(report.get("diagnostic_narrative"), Mapping) else {}
    operating = narrative.get("operating_condition") if isinstance(narrative.get("operating_condition"), Mapping) else {}
    rows: list[str] = []
    for group_name, label in (("target", "target"), ("ego", "ego")):
        fields = _field_rows(operating.get(group_name))
        if not fields:
            group = details.get(group_name) if isinstance(details.get(group_name), Mapping) else {}
            fields = _field_rows(group.get("fields"))[:14]
        for item in fields:
            token = item.get("token") or item.get("code_token") or item.get("access_path") or ""
            if not token:
                continue
            value = _format_report_value(item.get("value"))
            unit = str(item.get("unit") or "")
            status = str(item.get("status") or item.get("source_kind") or "not_available")
            rows.append(
                f"<tr><td>{html.escape(label)}</td><td>{html.escape(str(item.get('label', token)))}</td>"
                f"<td><code>{html.escape(str(token))}</code></td><td>{html.escape(value)}{html.escape((' ' + unit) if unit else '')}</td>"
                f"<td><span class=\"status\">{html.escape(status)}</span></td></tr>"
            )
    if not rows:
        return '<div class="scene-empty">No compact ego/target operating facts are available.</div>'
    return ('<table><thead><tr><th>Group</th><th>Field</th><th>Code token</th><th>Value</th><th>Evidence</th></tr></thead><tbody>'
            + "".join(rows)
            + '</tbody></table><div class="meta">Only key operating facts are shown here; the selected event JSON retains the complete field set.</div>')


def _runtime_fact_table_html(report: Mapping[str, Any]) -> str:
    """Render runtime/GDB facts separately from recorded input facts."""
    selected = report.get("selected_event") if isinstance(report.get("selected_event"), Mapping) else {}
    narrative = report.get("diagnostic_narrative") if isinstance(report.get("diagnostic_narrative"), Mapping) else {}
    narrative_facts = [item for item in narrative.get("runtime_facts", []) or [] if isinstance(item, Mapping)]
    observations = [item for item in selected.get("runtime_observations", []) or [] if isinstance(item, Mapping)]
    if not narrative_facts and not observations:
        return '<div class="scene-empty">No exact runtime observation is attached to this event. Public runtime/GDB evidence is still required for runtime-only values.</div>'
    rows: list[str] = []
    if narrative_facts:
        for field in narrative_facts:
            layer = str(field.get("layer") or "runtime")
            frame = field.get("frame_id") or "N/A"
            association = field.get("association") or "not_available"
            token = field.get("token") or field.get("code_token") or field.get("access_path") or ""
            status = str(field.get("status") or "not_available")
            rows.append(
                f"<tr><td>{html.escape(layer)}</td><td><code>{html.escape(str(frame))}</code></td>"
                f"<td>{html.escape(str(association))}</td><td><code>{html.escape(str(token))}</code></td><td>{html.escape(_format_report_value(field.get('value')))}</td>"
                f"<td><span class=\"status {html.escape(status)}\">{html.escape(status)}</span></td></tr>"
            )
    else:
        for observation in observations:
            identity = observation.get("identity") if isinstance(observation.get("identity"), Mapping) else {}
            layer = str(observation.get("layer", "runtime"))
            frame = identity.get("frame_id") or observation.get("frame_id") or "N/A"
            association = identity.get("frame_source") or observation.get("association_status") or "not_available"
            for field in _field_rows(observation.get("fields"))[:24]:
                token = field.get("token") or field.get("code_token") or field.get("access_path") or ""
                rows.append(
                    f"<tr><td>{html.escape(layer)}</td><td><code>{html.escape(str(frame))}</code></td>"
                    f"<td>{html.escape(str(association))}</td><td><code>{html.escape(str(token))}</code></td><td>{html.escape(_format_report_value(field.get('value')))}</td>"
                    f"<td><span class=\"status {html.escape(str(field.get('status', 'not_available')))}\">{html.escape(str(field.get('status', 'not_available')))}</span></td></tr>"
                )
    if not rows:
        return '<div class="scene-empty">Runtime observation exists but contains no field rows.</div>'
    return ('<table><thead><tr><th>Layer</th><th>Frame</th><th>Association</th><th>Runtime code token</th><th>Value</th><th>Status</th></tr></thead><tbody>'
            + "".join(rows[:32])
            + '</tbody></table><div class="meta">Only key runtime/GDB facts are shown; full observations and transcripts remain in the selected-event artifact.</div>')


def _timeline_display_rows(report: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    timeline = report.get("alert_timeline") if isinstance(report.get("alert_timeline"), Mapping) else {}
    narrative = report.get("diagnostic_narrative") if isinstance(report.get("diagnostic_narrative"), Mapping) else {}
    scope = narrative.get("scope") if isinstance(narrative.get("scope"), Mapping) else {}
    selected_frame = str(scope.get("frame_id") or "")
    target_id = str(scope.get("target_obj_id") or "")
    source_rows = [item for item in timeline.get("rows", []) or [] if isinstance(item, Mapping)]
    candidates: list[tuple[int, int, Mapping[str, Any]]] = []
    for order, item in enumerate(source_rows):
        layer = str(item.get("layer") or "")
        frame = str(item.get("frame_id") or "")
        object_id = str(item.get("object_id") or "")
        transition = str(item.get("transition") or "")
        if layer == "objectlist_candidate" and target_id and object_id != target_id:
            continue
        is_selected = bool(selected_frame and frame == selected_frame)
        is_transition = transition in {"rising", "rising_candidate", "active"}
        if selected_frame and not is_selected and not is_transition:
            continue
        layer_rank = {"can_tx_observation": 0, "runtime_with_frame": 1, "gdb_observation": 1, "replay_algorithm": 2, "recorded_raw": 3, "objectlist_candidate": 4}.get(layer, 5)
        candidates.append((0 if is_selected else 1, layer_rank, item))
    candidates.sort(key=lambda item: (item[0], item[1], str(item[2].get("frame_id") or "")))
    selected: list[Mapping[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for _, _, item in candidates:
        key = (str(item.get("layer")), str(item.get("frame_id")), str(item.get("signal") or item.get("function")), str(item.get("object_id") or ""))
        if key in seen:
            continue
        seen.add(key)
        selected.append(item)
        if len(selected) >= 24:
            break
    if not selected:
        return source_rows[:12]
    return selected


def _timeline_display_label(layer: Any) -> str:
    return {
        "recorded_raw": "原始录制报警",
        "replay_algorithm": "仿真算法输出",
        "runtime_with_frame": "算法运行输出",
        "gdb_observation": "GDB 现场",
        "can_tx_observation": "CAN 输出",
        "objectlist_candidate": "目标属性记录",
    }.get(str(layer or ""), str(layer or "未知来源"))


def _timeline_transition_label(value: Any) -> str:
    return {
        "rising": "上升沿",
        "rising_candidate": "上升沿候选",
        "active": "持续报警",
        "inactive": "未报警",
        "falling": "下降沿",
    }.get(str(value or ""), str(value or "未确认"))


def _timeline_frame_status_label(value: Any) -> str:
    return {
        "observed": "已获取",
        "derived": "推导",
        "not_evaluated": "无法确认",
        "not_comparable": "无法对齐",
    }.get(str(value or ""), str(value or "未确认"))


def _alert_timeline_html(report: Mapping[str, Any]) -> str:
    """Render the bounded cross-layer timeline without hiding absent layers."""
    timeline = report.get("alert_timeline") if isinstance(report.get("alert_timeline"), Mapping) else {}
    if not timeline:
        return '<div class="scene-empty">No alert timeline projection is available.</div>'
    rows: list[str] = []
    display_rows = _timeline_display_rows(report)
    for item in display_rows:
        if not isinstance(item, Mapping):
            continue
        rows.append(
            "<tr>"
            f"<td><span class=\"status\" title=\"{html.escape(str(item.get('layer', '')))}\">{html.escape(_timeline_display_label(item.get('layer')))}</span></td>"
            f"<td>{html.escape(str(item.get('function') or item.get('signal') or 'N/A'))}</td>"
            f"<td>{html.escape(str(item.get('side') or 'N/A'))}</td>"
            f"<td>{html.escape(str(item.get('radar_id') if item.get('radar_id') not in (None, '') else 'N/A'))}</td>"
            f"<td><code>{html.escape(str(item.get('frame_id') if item.get('frame_id') not in (None, '') else 'N/A'))}</code></td>"
            f"<td>{html.escape(_timeline_frame_status_label(item.get('frame_status')))}</td>"
            f"<td>{html.escape(_timeline_transition_label(item.get('transition')))}</td>"
            f"<td>{html.escape(str(item.get('value') if item.get('value') not in (None, '') else 'N/A'))}</td>"
            "</tr>"
        )
    frame_rows: list[str] = []
    narrative = report.get("diagnostic_narrative") if isinstance(report.get("diagnostic_narrative"), Mapping) else {}
    scope = narrative.get("scope") if isinstance(narrative.get("scope"), Mapping) else {}
    selected_frame = str(scope.get("frame_id") or "")
    playback_items = [item for item in timeline.get("playback_frame_map", []) or [] if isinstance(item, Mapping)]
    playback_candidates = [
        item for item in playback_items
        if not selected_frame
        or str(item.get("frame_id") or "") == selected_frame
        or item.get("alarm_rows")
    ]
    for item in timeline.get("playback_frame_map", []) or []:
        if not isinstance(item, Mapping):
            continue
        if item not in playback_candidates:
            continue
        alarm_signals = ", ".join(str(value) for value in item.get("alarm_signals", []) or []) or "无"
        frame_rows.append(
            "<tr>"
            f"<td><code>{html.escape(str(item.get('frame_id', '')))}</code></td>"
            f"<td>{html.escape(str(item.get('time_sec') if item.get('time_sec') not in (None, '') else 'N/A'))}</td>"
            f"<td>{html.escape(str(item.get('state', '')))}</td>"
            f"<td>{len(item.get('alarm_rows', []) or [])}</td>"
            f"<td>{html.escape(alarm_signals)}</td>"
            "</tr>"
        )
    compare_rows: list[str] = []
    for item in timeline.get("comparisons", []) or []:
        if not isinstance(item, Mapping):
            continue
        compare_rows.append(
            "<tr>"
            f"<td>{html.escape(str(item.get('left', '')))}</td>"
            f"<td>{html.escape(str(item.get('right', '')))}</td>"
            f"<td><span class=\"status {html.escape(str(item.get('status', '')))}\">{html.escape(str(item.get('status', '')))}</span></td>"
            f"<td>{html.escape(str(item.get('reason', '')))}</td>"
            "</tr>"
        )
    return (
        "<div class=\"timeline-grid\">"
        "<div><h3>报警来源</h3><table><thead><tr><th>来源</th><th>功能</th><th>侧别</th><th>雷达</th><th>帧</th><th>数据状态</th><th>报警状态</th><th>数值</th></tr></thead>"
        f"<tbody>{''.join(rows) or '<tr><td colspan=\"8\">No rows</td></tr>'}</tbody></table><div class=\"meta\">Showing {len(rows)} key rows around the selected frame; the full timeline is in alert-timeline.v1 JSON.</div></div>"
        "<div><h3>播放帧</h3><table><thead><tr><th>帧</th><th>时间（秒）</th><th>状态</th><th>报警记录</th><th>报警功能</th></tr></thead>"
        f"<tbody>{''.join(frame_rows[:24]) or '<tr><td colspan=\"5\">No playback frame map</td></tr>'}</tbody></table><div class=\"meta\">Showing alarm/selected playback frames only.</div></div>"
        "<div><h3>结果对照</h3><table><thead><tr><th>对象</th><th>对象</th><th>状态</th><th>说明</th></tr></thead>"
        f"<tbody>{''.join(compare_rows) or '<tr><td colspan=\"4\">No comparisons</td></tr>'}</tbody></table></div>"
        "</div>"
    )


def _analysis_trace_html(report: Mapping[str, Any]) -> str:
    """Render a compact, user-visible ledger trail without model CoT."""
    trace = report.get("analysis_trace") if isinstance(report.get("analysis_trace"), Mapping) else {}
    steps = [item for item in trace.get("steps", []) or [] if isinstance(item, Mapping)]
    if not steps:
        return '<div class="scene-empty">No AnalysisRun step summary is attached to this report.</div>'

    def value_text(value: Any) -> str:
        if isinstance(value, (Mapping, list)):
            return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
        return str(value)

    cards: list[str] = []
    for index, step in enumerate(steps, start=1):
        stage = html.escape(str(step.get("stage") or "step"))
        status = html.escape(str(step.get("status") or "not_available"))
        summary = html.escape(str(step.get("user_visible_summary") or ""))
        observations = []
        for item in step.get("observations", []) or []:
            if not isinstance(item, Mapping):
                continue
            parts = []
            for key in ("statement", "tool", "kind", "result_status", "should_alert", "scope", "status"):
                if item.get(key) not in (None, "", []):
                    parts.append(f"{key}={value_text(item[key])}")
            if parts:
                observations.append(f"<li>{html.escape(' · '.join(parts))}</li>")
        gaps = []
        for item in step.get("gaps", []) or []:
            if not isinstance(item, Mapping):
                continue
            label = item.get("id") or item.get("code") or "gap"
            reason = item.get("reason") or item.get("status") or ""
            gaps.append(f"<li><code>{html.escape(str(label))}</code> {html.escape(str(reason))}</li>")
        next_actions = []
        for item in step.get("next_action_candidates", []) or []:
            if not isinstance(item, Mapping):
                continue
            label = item.get("tool") or item.get("name") or item.get("id") or "next"
            reason = item.get("reason") or ""
            next_actions.append(f"<li><code>{html.escape(str(label))}</code> {html.escape(str(reason))}</li>")
        detail = ""
        if gaps or next_actions:
            detail = (
                '<details><summary>缺口 / 下一步</summary>'
                + ("<h4>Gaps</h4><ul>" + "".join(gaps) + "</ul>" if gaps else "")
                + ("<h4>Next actions</h4><ul>" + "".join(next_actions) + "</ul>" if next_actions else "")
                + "</details>"
            )
        cards.append(
            f'<article class="trace-card"><div class="trace-head"><span>#{index} {stage}</span>'
            f'<span class="status {status}">{status}</span></div>'
            f'<p>{summary or "No user-visible summary."}</p>'
            + ("<h4>Observations</h4><ul>" + "".join(observations) + "</ul>" if observations else "")
            + detail
            + "</article>"
        )
    return f'<div class="trace-grid">{"".join(cards)}</div>'


def _collaboration_board_html(report: Mapping[str, Any]) -> str:
    """Render hypothesis/experiment/user-observation summaries compactly."""
    trace = report.get("analysis_trace") if isinstance(report.get("analysis_trace"), Mapping) else {}
    hypotheses = [item for item in trace.get("hypotheses", []) or [] if isinstance(item, Mapping)]
    experiments = [item for item in trace.get("experiments", []) or [] if isinstance(item, Mapping)]
    observations = [item for item in trace.get("user_observations", []) or [] if isinstance(item, Mapping)]
    if not (hypotheses or experiments or observations):
        return ""

    def cell(value: Any) -> str:
        if isinstance(value, (Mapping, list)):
            value = json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
        return html.escape(str(value))

    blocks: list[str] = []
    if hypotheses:
        rows = []
        for item in hypotheses:
            rows.append(
                "<tr>"
                f"<td>{cell(item.get('category') or '—')}</td>"
                f"<td>{cell(item.get('statement') or '—')}</td>"
                f"<td><span class=\"status {cell(item.get('status') or 'open')}\">{cell(item.get('status') or 'open')}</span></td>"
                f"<td>{cell(item.get('rank') or '—')}</td>"
                f"<td>{cell(item.get('supporting_claim_count', 0))} / {cell(item.get('contradicting_claim_count', 0))}</td>"
                f"<td>{cell(item.get('required_evidence_count', 0))}</td>"
                "</tr>"
            )
        blocks.append(
            "<div><h3>Hypothesis Board</h3>"
            "<table><thead><tr><th>Category</th><th>Candidate</th><th>Status</th><th>Rank</th><th>Support / contradict</th><th>Required evidence</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table></div>"
        )
    if experiments:
        rows = []
        for item in experiments:
            target = item.get("target") if isinstance(item.get("target"), Mapping) else {}
            target_text = ", ".join(
                f"{key}={target[key]}"
                for key in ("event_id", "radar_id", "frame_id", "object_id")
                if target.get(key) not in (None, "", [])
            ) or "—"
            approval = item.get("approval") if isinstance(item.get("approval"), Mapping) else {}
            approval_text = approval.get("status") or approval.get("approved") or "not_requested"
            rows.append(
                "<tr>"
                f"<td>{cell(item.get('question') or '—')}</td>"
                f"<td>{cell(item.get('method') or '—')}</td>"
                f"<td><span class=\"status {cell(item.get('status') or 'planned')}\">{cell(item.get('status') or 'planned')}</span></td>"
                f"<td><code>{cell(target_text)}</code></td>"
                f"<td>{cell(approval_text)}</td>"
                f"<td>{cell(item.get('observation_count', 0))} / {cell(item.get('conclusion_delta_count', 0))}</td>"
                "</tr>"
            )
        blocks.append(
            "<div><h3>Next Experiments</h3>"
            "<table><thead><tr><th>Question</th><th>Method</th><th>Status</th><th>Target</th><th>Approval</th><th>Observations / deltas</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table></div>"
        )
    if observations:
        rows = []
        for item in observations:
            target = item.get("target") if isinstance(item.get("target"), Mapping) else {}
            target_text = ", ".join(
                f"{key}={target[key]}"
                for key in ("radar_id", "frame_id", "object_id")
                if target.get(key) not in (None, "", [])
            ) or "—"
            rows.append(
                "<tr>"
                f"<td>{cell(item.get('kind') or 'note')}</td>"
                f"<td>{cell(item.get('summary') or '—')}</td>"
                f"<td><code>{cell(target_text)}</code></td>"
                f"<td>{cell(item.get('experiment_id') or '—')}</td>"
                f"<td>{cell(item.get('artifact_ref_count', 0))}</td>"
                "</tr>"
            )
        blocks.append(
            "<div><h3>User Observations</h3>"
            "<table><thead><tr><th>Kind</th><th>Summary</th><th>Target</th><th>Experiment</th><th>Attachments</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table><div class=\"meta\">用户观察保持独立层，不自动成为 runtime observed。</div></div>"
        )
    return f'<div class="collab-grid">{"".join(blocks)}</div>'


def _condition_display_items(
    report: Mapping[str, Any],
) -> tuple[list[Mapping[str, Any]], int]:
    narrative = report.get("diagnostic_narrative") if isinstance(report.get("diagnostic_narrative"), Mapping) else {}
    selected = [item for item in narrative.get("condition_items", []) or [] if isinstance(item, Mapping)]
    trace = report.get("condition_trace") if isinstance(report.get("condition_trace"), Mapping) else {}
    all_items = [item for item in trace.get("conditions", []) or [] if isinstance(item, Mapping)]
    return selected or all_items[:8], len(all_items)


def _condition_rows_html(report: Mapping[str, Any]) -> str:
    items, total = _condition_display_items(report)
    rows: list[str] = []
    for item in items:
        evaluation = item.get("evaluation") if isinstance(item.get("evaluation"), Mapping) else {}
        source = item.get("source_ref") if isinstance(item.get("source_ref"), Mapping) else {}
        status = str(item.get("status") or evaluation.get("status") or "not_evaluable")
        reason = str(item.get("reason") or evaluation.get("reason") or "")
        source_text = f"{source.get('file_path', 'source')}:{source.get('line', '')}".rstrip(":")
        rows.append(
            f"<tr><td><span class=\"status {html.escape(status)}\">{html.escape(status)}</span></td>"
            f"<td><code>{html.escape(source_text)}</code></td>"
            f"<td><code>{html.escape(str(item.get('expression', '')))}</code></td>"
            f"<td><code>{html.escape(str(item.get('substituted_expression', '')))}</code></td>"
            f"<td>{html.escape(reason)}</td></tr>"
        )
    omitted = max(0, total - len(items))
    if omitted:
        rows.append(f'<tr><td colspan="5" class="meta">其余 {omitted} 条候选条件保留在 condition-trace.v1 JSON 中，未在首屏展开。</td></tr>')
    return "".join(rows)


def _can_output_html(report: Mapping[str, Any]) -> str:
    """Render source-derived CAN output candidates without claiming a send."""
    payload = report.get("can_output") if isinstance(report.get("can_output"), Mapping) else {}
    signals = [item for item in payload.get("signals", []) or [] if isinstance(item, Mapping)]
    status = str(payload.get("status") or "not_available")
    if not signals:
        return (
            f'<div class="scene-empty">No source output mapping is available for this event. '
            f'<code>{html.escape(status)}</code></div>'
        )
    rows: list[str] = []
    for item in signals:
        source_ref = item.get("source_ref") if isinstance(item.get("source_ref"), Mapping) else {}
        source_path = source_ref.get("path") or source_ref.get("file_path") or "source"
        source_line = source_ref.get("line")
        source = f"{source_path}:{source_line}" if source_line not in (None, "") else str(source_path)
        transport_rows = [row for row in item.get("transport_mappings", []) or [] if isinstance(row, Mapping)]
        transport_text = "—"
        if transport_rows:
            transport = transport_rows[0]
            send_ref = transport.get("com_send_source_ref") if isinstance(transport.get("com_send_source_ref"), Mapping) else {}
            send_path = send_ref.get("path") or send_ref.get("file_path") or "source"
            send_line = send_ref.get("line")
            send_location = f"{send_path}:{send_line}" if send_line not in (None, "") else str(send_path)
            transport_text = f"{transport.get('rte_lite_function') or 'RteLite_Write'} → Com_SendSignal @ {send_location}"
        internal_paths = [str(value) for value in item.get("internal_member_paths", []) or [] if str(value).strip()]
        internal_text = " · ".join(internal_paths[:3]) or "not_available"
        assignments = [row for row in item.get("internal_assignments", []) or [] if isinstance(row, Mapping)]
        primary_assignment = item.get("primary_assignment") if isinstance(item.get("primary_assignment"), Mapping) else None
        primary_assignment = primary_assignment or next((row for row in assignments if row.get("active") is True), None)
        assignment_text = str(item.get("assignment_status") or "not_scanned")
        if primary_assignment:
            ref = primary_assignment.get("source_ref") if isinstance(primary_assignment.get("source_ref"), Mapping) else {}
            assignment_text += f" @ {ref.get('path')}:{ref.get('line')}"
        rows.append(
            "<tr>"
            f"<td><code>{html.escape(str(item.get('signal') or ''))}</code></td>"
            f"<td><code>{html.escape(str(item.get('expression') or ''))}</code></td>"
            f"<td><code>{html.escape(internal_text)}</code><br><span class=\"meta\">{html.escape(assignment_text)}</span></td>"
            f"<td><code>{html.escape(source)}</code></td>"
            f"<td><code>{html.escape(transport_text)}</code></td>"
            f"<td><span class=\"status {html.escape(str(item.get('status') or 'source_candidate'))}\">"
            f"{html.escape(str(item.get('status') or 'source_candidate'))}</span></td>"
            "</tr>"
        )
    return (
        '<div class="meta">当前事件从实际 source 的 WriteSignal 映射中筛选出的候选；'
        '这里把算法输出之后的内部字段、对外 signal 和发送函数放在一行，便于继续回到代码核对。</div>'
        '<table><thead><tr><th>对外 signal token</th><th>source expression</th><th>FCT internal token / assignment</th><th>source</th><th>RteLite / Com</th><th>evidence</th></tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table>'
        f'<div class="meta">selected {len(signals)} / source candidates {html.escape(str(payload.get("candidate_count", "N/A")))} · '
        '运行时执行观测仍是独立证据层。</div>'
    )


def _public_contract_html(report: Mapping[str, Any]) -> str:
    """Render the source proof used for public object/frame correlation."""
    preflight = report.get("arbe_preflight") if isinstance(report.get("arbe_preflight"), Mapping) else {}
    public = preflight.get("public_evidence") if isinstance(preflight.get("public_evidence"), Mapping) else {}
    contract = public.get("objectlist_frame_contract") if isinstance(public.get("objectlist_frame_contract"), Mapping) else {}
    status = str(contract.get("status") or "not_available")
    if not contract:
        return f'<div class="scene-empty">No public object/frame source contract is attached. <code>{html.escape(status)}</code></div>'

    def ref_text(value: Any) -> str:
        if not isinstance(value, Mapping):
            return "not_available"
        path = value.get("path") or value.get("file_path") or "source"
        line = value.get("line")
        return f"{path}:{line}" if line not in (None, "") else str(path)

    rows = []
    for label, key in (
        ("callback", "callback"),
        ("objectlist publish", "objectlist_publish"),
        ("handler call", "objectlist_handler_call"),
        ("warning_with_frame publish", "warning_with_frame_publish"),
    ):
        rows.append(
            f"<tr><td>{html.escape(label)}</td><td><code>{html.escape(ref_text(contract.get(key)))}</code></td></tr>"
        )
    preconditions = "".join(
        f"<li>{html.escape(str(item))}</li>"
        for item in contract.get("preconditions", []) or []
    )
    return (
        f'<div class="meta"><span class="status {html.escape(status)}">{html.escape(status)}</span> · '
        f'association mode: <code>{html.escape(str(contract.get("association_mode") or "strict"))}</code> · '
        f'{html.escape(str(contract.get("basis") or ""))}</div>'
        '<table><thead><tr><th>Source marker</th><th>Location</th></tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table>'
        + (f'<details><summary>correlation preconditions</summary><ul>{preconditions}</ul></details>' if preconditions else "")
    )


def _debug_anchors_html(report: Mapping[str, Any]) -> str:
    """Render copyable, source-bound breakpoint conditions without transcripts."""
    selected = report.get("selected_event") if isinstance(report.get("selected_event"), Mapping) else {}
    details = selected.get("details") if isinstance(selected.get("details"), Mapping) else {}
    pack = details.get("breakpoint_pack") if isinstance(details.get("breakpoint_pack"), Mapping) else {}
    breakpoints = [item for item in pack.get("breakpoints", []) or [] if isinstance(item, Mapping)]
    if not breakpoints:
        plan = details.get("debug_plan") if isinstance(details.get("debug_plan"), Mapping) else {}
        breakpoints = [item for item in plan.get("breakpoints", []) or [] if isinstance(item, Mapping)]
    if not breakpoints:
        return '<div class="scene-empty">No source-bound breakpoint conditions are available.</div>'
    rows: list[str] = []
    commands: list[str] = []
    for index, item in enumerate(breakpoints, start=1):
        location = item.get("location") if isinstance(item.get("location"), Mapping) else item
        file_path = location.get("file") or location.get("file_path") or "source"
        line = location.get("line") or "N/A"
        function = item.get("function") or "N/A"
        condition = str(item.get("condition") or "").strip() or "not_available"
        rows.append(
            f"<tr><td>{html.escape(str(function))}</td><td><code>{html.escape(str(file_path))}:{html.escape(str(line))}</code></td>"
            f"<td><code>{html.escape(condition)}</code></td><td>{html.escape(str(item.get('purpose') or ''))}</td></tr>"
        )
        if file_path != "source" and line != "N/A" and condition != "not_available":
            commands.extend([f"break {file_path}:{line}", f"condition {index} {condition}"])
    gdb_commands = pack.get("gdb_commands") if isinstance(pack.get("gdb_commands"), list) else []
    if gdb_commands:
        commands = [str(item) for item in gdb_commands if str(item).strip()]
    copy_text = "\n".join(commands) if commands else "\n".join(
        str(item.get("copy_text") or item.get("condition") or "")
        for item in breakpoints
        if str(item.get("copy_text") or item.get("condition") or "").strip()
    )
    return (
        '<table><thead><tr><th>Function</th><th>Source</th><th>VSCode/GDB condition</th><th>Purpose</th></tr></thead><tbody>'
        + "".join(rows)
        + '</tbody></table><details><summary>copyable breakpoint commands</summary><pre>'
        + html.escape(copy_text or "not_available")
        + '</pre></details>'
    )


def _analysis_flow_html(report: Mapping[str, Any]) -> str:
    """Render the compact evidence-to-conclusion walkthrough."""
    narrative = report.get("diagnostic_narrative") if isinstance(report.get("diagnostic_narrative"), Mapping) else {}
    flow = narrative.get("analysis_flow") if isinstance(narrative.get("analysis_flow"), Mapping) else {}
    steps = [item for item in flow.get("steps", []) or [] if isinstance(item, Mapping)]
    if not steps:
        return '<div class="scene-empty">No structured diagnostic flow is available.</div>'
    style = """
<style>
.analysis-flow{display:grid;gap:12px}.flow-step{display:grid;grid-template-columns:48px 1fr;gap:14px;border:1px solid var(--line);border-radius:12px;padding:14px;background:#0d1916}.flow-index{display:grid;place-items:start center;color:var(--accent);font:700 16px/1.2 ui-monospace,monospace;padding-top:3px}.flow-body{min-width:0}.flow-head{display:flex;justify-content:space-between;gap:10px;align-items:center}.flow-head h3{margin:0;color:var(--ink)}.flow-summary{margin:4px 0 10px;color:var(--muted)}.flow-facts{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:8px}.flow-fact-group,.flow-branch,.flow-decision{border:1px solid var(--line);border-radius:9px;padding:10px;background:#0b1513}.flow-group-label,.flow-category{display:block;color:var(--muted);font-size:11px;letter-spacing:.08em;margin-bottom:6px}.flow-chips,.flow-bindings{display:flex;flex-wrap:wrap;gap:6px}.flow-chip{display:inline-flex;gap:4px;align-items:center;border:1px solid var(--line);border-radius:999px;padding:3px 7px;background:#101d19;color:var(--ink);font:12px/1.3 ui-monospace,monospace}.flow-conditions{display:grid;gap:8px}.flow-counts{color:var(--muted);font:12px/1.4 ui-monospace,monospace;margin:4px 0}.flow-condition{border:1px solid var(--line);border-left:3px solid var(--line);border-radius:9px;padding:10px;background:#0b1513}.flow-condition:has(.status.satisfied){border-left-color:#3e9e7e}.flow-condition:has(.status.not_satisfied){border-left-color:#a45151}.flow-condition:has(.status.not_evaluable),.flow-condition:has(.status.unsupported){border-left-color:#8f6e3b}.flow-condition-head{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.flow-condition-head code{margin-left:auto;color:var(--muted)}.flow-expression{display:block;color:var(--ink);white-space:pre-wrap;overflow-wrap:anywhere;margin:8px 0}.flow-substitution{display:grid;grid-template-columns:70px minmax(0,1fr);gap:8px;align-items:start;color:var(--muted);font-size:12px}.flow-substitution code{white-space:pre-wrap;overflow-wrap:anywhere;color:var(--accent)}.flow-bindings{margin-top:8px}.flow-missing{margin-top:8px;color:var(--warn);font-size:12px}.flow-explanation{margin-top:8px;color:var(--muted);font-size:12px}.flow-geometry-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:8px}.flow-geometry-grid>div{border:1px solid var(--line);border-radius:9px;padding:10px;background:#0b1513}.flow-prediction{color:var(--accent);overflow-wrap:anywhere}.flow-branch{margin-top:8px}.flow-decision-label{margin-left:8px;color:var(--ink);font:600 13px/1.4 ui-monospace,monospace}.flow-muted{color:var(--muted);font-size:12px}.flow-step p{margin-bottom:0}
</style>
"""
    style += '<style>.flow-chain{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin:10px 0;padding:8px 10px;border:1px dashed var(--line);border-radius:8px;color:var(--accent);font:12px/1.4 ui-monospace,monospace}.flow-chain-muted{color:var(--warn)}.flow-conditions{max-height:760px;overflow:auto;padding-right:4px}</style>'

    def status_badge(status: Any) -> str:
        value = str(status or "not_evaluated")
        return f'<span class="status {html.escape(value)}">{html.escape(value)}</span>'

    def fact_groups(step: Mapping[str, Any]) -> str:
        groups: list[str] = []
        for key, label in (("ego_facts", "自车"), ("target_facts", "目标")):
            facts = [item for item in step.get(key, []) or [] if isinstance(item, Mapping)]
            if not facts:
                continue
            chips = "".join(
                f'<span class="flow-chip"><code>{html.escape(str(item.get("token") or "token"))}</code>'
                f'={html.escape(_format_report_value(item.get("value")))}'
                f'{html.escape((" " + str(item.get("unit"))) if item.get("unit") else "")}</span>'
                for item in facts[:12]
            )
            groups.append(
                f'<div class="flow-fact-group"><div class="flow-group-label">{label}</div>'
                f'<div class="flow-chips">{chips}</div></div>'
            )
        return (
            '<div class="flow-facts">' + "".join(groups) + '</div>'
            if groups else '<div class="flow-muted">同帧自车/目标属性不可用。</div>'
        )

    def condition_cards(step: Mapping[str, Any]) -> str:
        cards: list[str] = []
        for item in step.get("conditions", []) or []:
            if not isinstance(item, Mapping):
                continue
            source = item.get("source_ref") if isinstance(item.get("source_ref"), Mapping) else {}
            source_text = f'{source.get("file_path", "source")}:{source.get("line", "N/A")}'
            bindings = [binding for binding in item.get("bindings", []) or [] if isinstance(binding, Mapping)]
            binding_markup = "".join(
                f'<span class="flow-chip"><code>{html.escape(str(binding.get("token") or "token"))}</code>='
                f'{html.escape(_format_report_value(binding.get("value")))}</span>'
                for binding in bindings
                if binding.get("status") == "bound"
            )
            missing = [str(value) for value in item.get("missing_tokens", []) or []]
            missing_markup = (
                f'<div class="flow-missing">缺少同帧量：{html.escape(", ".join(missing))}</div>'
                if missing else ""
            )
            cards.append(
                f'<article class="flow-condition">'
                f'<div class="flow-condition-head"><span class="flow-category">{html.escape(str(item.get("category_label") or "源码条件"))}</span>'
                f'<code>{html.escape(source_text)}</code>{status_badge(item.get("status"))}</div>'
                f'<code class="flow-expression">{html.escape(str(item.get("expression") or "not_available"))}</code>'
                f'<div class="flow-substitution"><span>代入结果</span><code>{html.escape(str(item.get("substituted_expression") or "not_available"))}</code></div>'
                + (f'<div class="flow-bindings">{binding_markup}</div>' if binding_markup else "")
                + missing_markup
                + f'<div class="flow-explanation">{html.escape(str(item.get("explanation") or item.get("reason") or ""))}</div>'
                + '</article>'
            )
        if not cards:
            return '<div class="flow-muted">没有可展示的关键源码条件。</div>'
        return '<div class="flow-conditions">' + "".join(cards) + '</div>'

    def geometry_content(step: Mapping[str, Any]) -> str:
        relation = str(step.get("current_relation") or "not_evaluated")
        prediction = step.get("prediction") if isinstance(step.get("prediction"), Mapping) else {}
        branch = step.get("algorithm_branch") if isinstance(step.get("algorithm_branch"), Mapping) else {}
        parts = [
            f'<div class="flow-geometry-grid"><div><span class="flow-group-label">当前几何</span>'
            f'<div>{status_badge(relation)}</div><p>当前 polygon 与 ROI 的关系只表示这一时刻的空间位置。</p></div>'
        ]
        if prediction.get("x") not in (None, "") and prediction.get("y") not in (None, ""):
            prediction_text = (
                f'<code>{html.escape(str(prediction.get("x_token") or "x"))}={html.escape(_format_report_value(prediction.get("x")))}</code> · '
                f'<code>{html.escape(str(prediction.get("y_token") or "y"))}={html.escape(_format_report_value(prediction.get("y")))}</code>'
            )
            if prediction.get("time") not in (None, ""):
                prediction_text += (
                    f' · <code>{html.escape(str(prediction.get("time_token") or "time"))}='
                    f'{html.escape(_format_report_value(prediction.get("time")))}s</code>'
                )
            relations = ", ".join(
                str(item.get("relation"))
                for item in prediction.get("roi_relations", []) or []
                if isinstance(item, Mapping)
            )
            parts.append(
                f'<div><span class="flow-group-label">代码预测</span><div class="flow-prediction">{prediction_text}</div>'
                f'<p>预测 ROI 关系：{html.escape(relations or "not_evaluated")}；这是预测点，不是当前目标矩形。</p></div>'
            )
        else:
            parts.append(
                '<div><span class="flow-group-label">代码预测</span>'
                '<div class="flow-muted">未获取到可用于绘图的交点/穿越点 runtime token。</div></div>'
            )
        parts.append('</div>')
        if branch.get("expression"):
            assignment = branch.get("source_assignment") if isinstance(branch.get("source_assignment"), Mapping) else {}
            branch_text = f'<code>{html.escape(str(branch.get("expression")))}</code>'
            if assignment.get("expression"):
                branch_text += (
                    f' → <code>{html.escape(str(assignment.get("expression")))}</code>'
                    f' ({html.escape(str(assignment.get("file_path")))}:{html.escape(str(assignment.get("line")))})'
                )
            parts.append(
                f'<div class="flow-branch"><span class="flow-group-label">源码分支</span><div>{branch_text}</div>'
                '<p>该分支表示 ROI/区域可用性，不等于目标已经侵入 ROI。</p></div>'
            )
        return "".join(parts)

    def output_content(step: Mapping[str, Any]) -> str:
        policy = step.get("output_policy") if isinstance(step.get("output_policy"), Mapping) else {}
        supporting = [item for item in step.get("supporting_conditions", []) or [] if isinstance(item, Mapping)]
        not_satisfied = [item for item in step.get("not_satisfied_conditions", []) or [] if isinstance(item, Mapping)]
        support_text = "、".join(
            f'{(item.get("source_ref") or {}).get("file_path", "source")}:{(item.get("source_ref") or {}).get("line", "N/A")}'
            for item in supporting[:8]
        )
        not_satisfied_text = "、".join(
            f'{(item.get("source_ref") or {}).get("file_path", "source")}:{(item.get("source_ref") or {}).get("line", "N/A")}'
            for item in not_satisfied[:4]
        )
        chain = (
            f'<div class="flow-chain"><span>满足关键条件 {len(supporting)} 条</span>'
            + (f' <code>{html.escape(support_text)}</code>' if support_text else "")
            + (f' <span class="flow-chain-muted">；未满足分支 {html.escape(not_satisfied_text)}</span>' if not_satisfied_text else "")
            + '</div>'
        )
        return (
            f'<div class="flow-decision">{status_badge(step.get("status"))} '
            f'<span class="flow-decision-label">should_alert={html.escape(str(step.get("should_alert") or "indeterminate"))}</span>'
            f'<p>{html.escape(str(step.get("statement") or "当前没有足够证据形成输出结论。"))}</p>'
            f'{chain}'
            f'<div class="flow-chips"><span class="flow-chip">endpoint=<code>{html.escape(str(policy.get("effective_endpoint") or "not_available"))}</code></span>'
            f'<span class="flow-chip">CAN=<code>{html.escape(str(policy.get("can_data_status") or "not_detected"))}</code></span>'
            f'<span class="flow-chip">can_required=<code>{html.escape(str(policy.get("can_required", True)).lower())}</code></span></div></div>'
        )

    def output_chain_content(step: Mapping[str, Any]) -> str:
        chain = step.get("output_chain") if isinstance(step.get("output_chain"), Mapping) else {}
        chain_steps = [item for item in chain.get("steps", []) or [] if isinstance(item, Mapping)]
        if not chain_steps:
            return '<div class="flow-muted">当前没有可确认的算法输出后续映射。</div>'
        rows: list[str] = []
        for item in chain_steps[:8]:
            ref = item.get("source_ref") if isinstance(item.get("source_ref"), Mapping) else item.get("send_ref") if isinstance(item.get("send_ref"), Mapping) else {}
            location = f'{ref.get("path")}:{ref.get("line")}' if ref.get("path") and ref.get("line") not in (None, "") else ""
            rows.append(
                f'<tr><td>{html.escape(str(item.get("kind") or "output"))}</td>'
                f'<td><code>{html.escape(str(item.get("token") or item.get("signal") or "not_available"))}</code></td>'
                f'<td>{html.escape(str(item.get("value")) if item.get("value") not in (None, "") else "—")}</td>'
                f'<td>{html.escape(location)}</td><td>{status_badge(item.get("status"))}</td>'
                f'<td>{html.escape(str(item.get("text") or ""))}</td></tr>'
            )
        omitted = max(0, len(chain_steps) - len(rows))
        return (
            f'<div class="flow-chain"><span>主链：<code>{html.escape(str(chain.get("primary_internal_signal") or "not_available"))}</code>'
            f' → <code>{html.escape(str(chain.get("primary_external_signal") or "not_available"))}</code></span>'
            f' {status_badge(chain.get("status"))}</div>'
            '<table><thead><tr><th>环节</th><th>真实 token</th><th>同帧值</th><th>源码位置</th><th>证据</th><th>说明</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table>'
            + (f'<div class="flow-muted">其余 {omitted} 个输出候选保留在 diagnostic-output-chain.v1。</div>' if omitted else "")
        )

    cards: list[str] = []
    for step in steps:
        kind = str(step.get("kind") or "")
        if kind == "input_context":
            body = fact_groups(step)
        elif kind == "source_condition_walk":
            counts = step.get("counts") if isinstance(step.get("counts"), Mapping) else {}
            count_text = " / ".join(
                f'{key}={counts.get(key, 0)}'
                for key in ("satisfied", "not_satisfied", "not_evaluable", "unsupported")
            )
            body = f'<div class="flow-counts">{html.escape(count_text)}</div>{condition_cards(step)}'
        elif kind == "geometry_and_prediction":
            body = geometry_content(step)
        elif kind == "output_decision":
            body = output_content(step)
        elif kind == "fct_output_mapping":
            body = output_chain_content(step)
        else:
            body = f'<div class="flow-muted">{html.escape(str(step.get("summary") or "not_available"))}</div>'
        cards.append(
            f'<article class="flow-step"><div class="flow-index">{int(step.get("order") or len(cards) + 1):02d}</div>'
            f'<div class="flow-body"><div class="flow-head"><h3>{html.escape(str(step.get("title") or "诊断步骤"))}</h3>{status_badge(step.get("status"))}</div>'
            f'<p class="flow-summary">{html.escape(str(step.get("summary") or ""))}</p>{body}</div></article>'
        )
    return style + '<div class="analysis-flow">' + "".join(cards) + '</div>'


def _html(report: Mapping[str, Any], markdown: str) -> str:
    title = html.escape(str((report.get("identity") or {}).get("data_name") or "CR60 detailed diagnostic report"))
    selected = report.get("selected_event")
    detail = json.dumps(selected or {}, ensure_ascii=False, indent=2, default=str)
    diagnosis = json.dumps(report.get("diagnosis") or {}, ensure_ascii=False, indent=2, default=str)
    conclusion = json.dumps(report.get("conclusion") or {}, ensure_ascii=False, indent=2, default=str)
    condition_trace = report.get("condition_trace") if isinstance(report.get("condition_trace"), Mapping) else {}
    narrative = report.get("diagnostic_narrative") if isinstance(report.get("diagnostic_narrative"), Mapping) else {}
    condition_rows = _condition_rows_html(report)
    condition_items, condition_total = _condition_display_items(report)
    assessment = narrative.get("alarm_assessment") if isinstance(narrative.get("alarm_assessment"), Mapping) else {}
    output_policy = report.get("output_policy") if isinstance(report.get("output_policy"), Mapping) else {}
    should_alert = str(assessment.get("should_alert", "indeterminate"))
    should_alert_label = {
        "yes_observed": "已观察到报警",
        "supported_yes": "代码条件支持报警",
        "indeterminate": "暂不能确定",
        "no_observed": "未观察到报警",
    }.get(should_alert, should_alert)
    story = report.get("diagnostic_story") if isinstance(report.get("diagnostic_story"), Mapping) else {}
    story_conclusion = story.get("conclusion") if isinstance(story.get("conclusion"), Mapping) else {}
    executive_summary = html.escape(str(story_conclusion.get("text") or narrative.get("executive_summary") or "当前没有可生成的证据绑定文字摘要。"))
    narrative_items = [str(item) for item in narrative.get("narrative", []) or []]
    narrative_full = "".join(f"<li>{html.escape(item)}</li>" for item in narrative_items)
    narrative_json = json.dumps(narrative, ensure_ascii=False, indent=2, default=str)
    condition_json = json.dumps(condition_trace, ensure_ascii=False, indent=2, default=str)
    scene = _scene_svg(report)
    story_html = _diagnostic_story_html(report)
    execution_context_html = _execution_context_html(report)
    parameter_table = _parameter_table_html(report)
    condition_chain_table = _condition_chain_table_html(report)
    fact_table = _fact_table_html(report)
    runtime_fact_table = _runtime_fact_table_html(report)
    analysis_trace_html = _analysis_trace_html(report)
    collaboration_board_html = _collaboration_board_html(report)
    can_output_html = _can_output_html(report)
    public_contract_html = _public_contract_html(report)
    debug_anchors = _debug_anchors_html(report)
    timeline = report.get("alert_timeline") if isinstance(report.get("alert_timeline"), Mapping) else {}
    timeline_html = _alert_timeline_html(report)
    timeline_json = json.dumps(timeline, ensure_ascii=False, indent=2, default=str)
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title><style>
:root{{color-scheme:dark;--bg:#0b1110;--panel:#121c1a;--line:#28403a;--ink:#e6f0eb;--muted:#94aaa1;--accent:#7fe0bb;--warn:#f2bc67;--bad:#e87979}}
 body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.55 ui-sans-serif,system-ui,sans-serif}}main{{max-width:1320px;margin:0 auto;padding:32px}}h1{{font-size:26px;margin:0 0 8px}}h2{{font-size:17px;margin:0 0 14px}}h3{{font-size:14px;margin:10px 0;color:var(--ink)}}h4{{font-size:12px;margin:10px 0 4px;color:var(--ink)}}p,.meta{{color:var(--muted)}}section{{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:18px;margin:16px 0}}details{{border-top:1px solid var(--line);padding:12px 0}}details:first-child{{border-top:0}}summary{{cursor:pointer;color:var(--accent);font-weight:600}}pre{{overflow:auto;max-height:520px;background:#09100f;border:1px solid var(--line);border-radius:10px;padding:14px;color:#cfe6dc}}table{{width:100%;border-collapse:collapse;table-layout:fixed}}td,th{{text-align:left;border-bottom:1px solid var(--line);padding:8px;color:var(--muted);vertical-align:top;overflow-wrap:anywhere}}th{{color:var(--ink)}}code{{color:var(--accent)}}.scene{{background:#0b1513;border:1px solid var(--line);border-radius:12px;padding:8px;overflow:auto}}.scene-svg{{width:100%;min-width:620px;height:auto;background:radial-gradient(circle at center,#13201c,#09100f)}}.axis{{stroke:#46655b;stroke-dasharray:4 6;stroke-width:1}}.axis-label,.roi-label,.geometry-source{{fill:#78958a;font-size:11px;letter-spacing:.08em}}.ego{{fill:#4cae8b33;stroke:#6ce0b5;stroke-width:2}}.target{{fill:#d39a3b55;stroke:#f2bc67;stroke-width:2}}.target-corner{{fill:#f2bc67;stroke:#f8df9f;stroke-width:1}}.corner-label{{fill:#f2bc67;font-size:10px;font-weight:700}}.collision-label{{fill:#f2bc67;font-size:11px;letter-spacing:.08em}}.roi{{fill:#bd9d3b18;stroke:#a58c43;stroke-dasharray:5 5;stroke-width:1.5}}.roi-runtime{{fill:#4c9f8b1f;stroke:#6ce0b5;stroke-dasharray:3 4;stroke-width:2}}.heading{{stroke:#f2bc67;stroke-width:2.5}}.prediction{{stroke:#6ce0b5;stroke-width:2;stroke-dasharray:6 5;opacity:.9}}.prediction-point{{fill:#6ce0b5;stroke:#d4f5e5;stroke-width:1.5}}.prediction-label{{fill:#6ce0b5;font-size:11px;letter-spacing:.04em}}.prediction-marker{{fill:#6ce0b5}}marker path{{fill:#f2bc67}}.ego-label{{fill:#9ae7c7;font-weight:700;font-size:13px}}.target-label{{fill:#f2bc67;font-weight:700;font-size:13px}}.scene-empty{{padding:32px;color:var(--muted);text-align:center;border:1px dashed var(--line);border-radius:12px}}.status{{font-family:ui-monospace,monospace;font-size:12px;padding:2px 6px;border-radius:99px;border:1px solid var(--line)}}.status.satisfied,.status.same{{color:var(--accent);border-color:#3e9e7e}}.status.not_satisfied,.status.different{{color:var(--bad);border-color:#a45151}}.status.not_evaluable,.status.unsupported,.status.not_comparable,.status.not_evaluated,.status.indeterminate{{color:var(--warn);border-color:#8f6e3b}}.status.yes_observed{{color:var(--accent);border-color:#3e9e7e}}.status.supported_yes{{color:#d4e58d;border-color:#758c42}}.narrative-assessment{{border:1px solid var(--line);border-radius:10px;padding:12px;background:#0b1513;margin-bottom:12px}}.executive-summary{{font-size:15px;line-height:1.8;white-space:pre-line;border-left:3px solid var(--accent);padding:10px 14px;background:#0d1916;color:var(--ink);border-radius:0 8px 8px 0}}.timeline-grid{{display:grid;gap:14px}}.timeline-grid>div{{border:1px solid var(--line);border-radius:10px;padding:10px;overflow:auto}}.timeline-grid table{{min-width:860px}}.trace-grid{{display:grid;gap:10px}}.trace-card{{border:1px solid var(--line);border-radius:10px;padding:12px;background:#0d1916}}.trace-head{{display:flex;justify-content:space-between;gap:10px;align-items:center;color:var(--ink)}}.trace-card ul{{margin:6px 0 0;padding-left:20px;color:var(--muted)}}
 </style></head><body><main><header><div class="meta">CR60 / DETAILED DIAGNOSTIC REPORT</div><h1>{title}</h1><p>本报告把报警时刻的数据、当前源码条件和运行结果整理成可追溯的工程分析。</p></header>
<section><h2>概览</h2><div class="meta">报告状态：<code>{html.escape(str(report.get('status')))}</code> · 事件数：<code>{html.escape(str((report.get('overview') or {{}}).get('event_count',0)))}</code> · 时间线：<code>{html.escape(str((report.get('overview') or {{}}).get('timeline_status','not_available')))}</code> · 判断终点：<code>{html.escape('算法最终输出' if output_policy.get('effective_endpoint') == 'algorithm' else 'CAN 输出' if output_policy.get('effective_endpoint') == 'can_tx' else '未确定')}</code></div></section>
<section><h2>本次实际执行方式</h2><div class="meta">区分实车录制输入和本地算法仿真；这部分说明报警数据是如何产生的。</div>{execution_context_html}</section>
<section><h2>报警事件</h2><table><thead><tr><th>事件</th><th>功能</th><th>侧别</th><th>雷达</th><th>首帧/分析帧</th></tr></thead><tbody>{''.join(f"<tr><td><code>{html.escape(str(e.get('event_id','')))}</code></td><td>{html.escape(str(e.get('function','')))}</td><td>{html.escape(str(e.get('side','')))}</td><td>{html.escape(str(e.get('radar_id','')))}</td><td><code>{html.escape(str((e.get('first_frame') or {{}}).get('frame_id','N/A')))}</code></td></tr>" for e in report.get('event_index',[]) or [] if isinstance(e,Mapping))}</tbody></table></section>
<section><h2>总结性分析结论</h2><div class="narrative-assessment"><span class="status {html.escape(should_alert)}">{html.escape(should_alert_label)}</span> {html.escape(str(assessment.get('statement', '当前没有足够证据形成报警结论。')))}</div><p class="executive-summary">{executive_summary}</p><h3>报警条件链</h3><div class="meta">按当前 source 的真实调用关系和源码顺序呈现，不把不同分支拼成固定流程。</div>{condition_chain_table}<h3>报警帧关键数据</h3><div class="meta">下面表格是本次结论使用的自车、目标、源码参数和 runtime 中间量；保留真实 code token、数值、来源和帧号。</div>{parameter_table}{f'<details><summary>展开原始文字证据（{len(narrative_items)} 条）</summary><ol>{narrative_full}</ol></details>' if narrative_full else ''}<details><summary>diagnostic-narrative.v1 JSON</summary><pre>{html.escape(narrative_json)}</pre></details></section>
<section><h2>报警工况图</h2><div class="meta">实线表示报警时刻目标和 ROI；虚线/交点表示代码运行态预测结果。坐标：+X 向前，+Y 向左。</div><div class="scene">{scene}</div></section>
<section><h2>报警命中流程</h2><div class="meta">按当前 source 的真实执行顺序，说明数据如何代入代码条件并到达 arbe 报警灯输出。</div>{story_html}</section>
 <section><h2>报警帧时间线</h2><div class="meta">查看原始报警、算法输出和各播放帧的状态；完整时间线可展开。</div>{timeline_html}<details><summary>完整报警帧时间线 JSON</summary><pre>{html.escape(timeline_json)}</pre></details></section>
 <section><h2>数据与报警帧关联</h2><details><summary>查看关联检查结果</summary>{public_contract_html}</details></section>
 <section><h2>Evidence detail tables</h2><details open><summary>Recorded / static frame facts</summary><div class="meta">原始输入和 viewer projection 的紧凑字段。</div>{fact_table}</details><details><summary>Runtime / GDB facts</summary><div class="meta">运行时字段与记录输入分开保留。</div>{runtime_fact_table}</details></section>
 <section><h2>完整代码条件明细</h2><details><summary>展开 {len(condition_items)} / {condition_total} 条关键条件</summary><div class="meta">这里保留源表达式、代入结果和求值原因；主叙事已用自然语言解释命中过程。</div><table><thead><tr><th>状态</th><th>源码位置</th><th>源表达式</th><th>代入表达式</th><th>说明</th></tr></thead><tbody>{condition_rows or '<tr><td colspan="5">No key source condition rows are available.</td></tr>'}</tbody></table></details><details><summary>完整 condition-trace JSON</summary><pre>{html.escape(condition_json)}</pre></details></section>
 <section><h2>报警输出信号路径</h2><details open>{can_output_html}</details></section>
 <section><h2>可复制的断点条件</h2><div class="meta">这些条件来自当前事件的源码断点包，复制前确认 source 和 binary 对齐。</div>{debug_anchors}</section>
 <section><h2>当前报警完整数据</h2><details><summary>展开完整事件数据</summary><pre>{html.escape(detail)}</pre></details></section>
<section><h2>调查过程记录</h2><details><summary>展开分析账本和用户观察</summary><div class="meta">这里记录工具阶段、观察、缺口和下一步，不影响上面的数据与结论。</div>{analysis_trace_html}{collaboration_board_html}</details></section>
<section><h2>证据完整性</h2><details><summary>展开完整性检查和未证明事项</summary><pre>{html.escape(conclusion)}</pre></details></section>
<section><h2>分析限制</h2><details><summary>展开缺口说明</summary><pre>{html.escape(diagnosis)}</pre></details></section>
<section><h2>建议下一步</h2><ul>{''.join(f"<li><code>{html.escape(str(a.get('tool','')))}</code> · {html.escape(str(a.get('reason','')))}</li>" for a in report.get('next_actions',[]) or [] if isinstance(a,Mapping))}</ul></section>
<section><h2>文本报告</h2><details><summary>展开 Markdown 文本</summary><pre>{html.escape(markdown)}</pre></details></section>
</main></body></html>"""


def build_diagnostic_report(
    *,
    bundle: Mapping[str, Any] | None = None,
    bundle_path: str = "",
    viewer_model: Mapping[str, Any] | None = None,
    viewer_model_path: str = "",
    runtime_evidence: Mapping[str, Any] | None = None,
    runtime_evidence_path: str = "",
    runtime_debug_plan: Mapping[str, Any] | None = None,
    runtime_debug_plan_path: str = "",
    preflight: Mapping[str, Any] | None = None,
    preflight_path: str = "",
    code_context: Mapping[str, Any] | None = None,
    code_context_path: str = "",
    event_code_path: Mapping[str, Any] | None = None,
    event_code_path_path: str = "",
    condition_trace: Mapping[str, Any] | None = None,
    condition_trace_path: str = "",
    gdb_session: Mapping[str, Any] | None = None,
    gdb_session_path: str = "",
    analysis: Mapping[str, Any] | None = None,
    analysis_run: Mapping[str, Any] | None = None,
    analysis_run_path: str = "",
    event_id: str = "",
    event_index: int | None = None,
    function: str = "",
    side: str = "",
    radar_id: str | int = "",
    frame_id: str | int = "",
    output_endpoint: str = "algorithm",
    can_data_status: str = "",
    max_events: int = 100,
    max_frames: int = 24,
    max_targets: int = 24,
) -> dict[str, Any]:
    bundle_obj, bundle_ref, bundle_error = _load_object(bundle, bundle_path, label="bundle")
    viewer_obj, viewer_ref, viewer_error = _load_object(viewer_model, viewer_model_path, label="viewer_model")
    runtime_obj, runtime_ref, runtime_error = _load_object(runtime_evidence, runtime_evidence_path, label="runtime_evidence")
    plan_obj, plan_ref, plan_error = _load_object(runtime_debug_plan, runtime_debug_plan_path, label="runtime_debug_plan")
    preflight_obj, preflight_ref, preflight_error = _load_object(preflight, preflight_path, label="arbe_preflight")
    context_obj, context_ref, context_error = _load_object(code_context, code_context_path, label="code_context")
    path_obj, path_ref, path_error = _load_object(event_code_path, event_code_path_path, label="event_code_path")
    trace_obj, trace_ref, trace_error = _load_object(condition_trace, condition_trace_path, label="condition_trace")
    run_obj, run_ref, run_error = _load_object(analysis_run, analysis_run_path, label="analysis_run")
    gdb_session_obj, gdb_session_ref, gdb_session_error = _load_object(gdb_session, gdb_session_path, label="gdb_session")
    runtime_normalization_error = ""
    if isinstance(runtime_obj, Mapping) and runtime_obj.get("schema_version") == "runtime-case-evidence.v1":
        try:
            from .runtime_evidence import normalize_runtime_evidence

            runtime_obj = normalize_runtime_evidence(runtime_obj)
        except (TypeError, ValueError, KeyError) as exc:
            runtime_normalization_error = f"runtime_evidence_normalization_failed:{type(exc).__name__}:{exc}"
    if runtime_obj is None and isinstance(bundle_obj, Mapping) and isinstance(bundle_obj.get("runtime_evidence"), Mapping):
        runtime_obj = dict(bundle_obj["runtime_evidence"])
        runtime_ref = {"label": "runtime_evidence", "source": "embedded_in_bundle", "schema_version": runtime_obj.get("schema_version", "")}
    if plan_obj is None and isinstance(bundle_obj, Mapping) and isinstance(bundle_obj.get("runtime_debug_plan"), Mapping):
        plan_obj = dict(bundle_obj["runtime_debug_plan"])
        plan_ref = {"label": "runtime_debug_plan", "source": "embedded_in_bundle", "schema_version": plan_obj.get("schema_version", "")}
    errors = [item for item in (bundle_error, viewer_error, runtime_error, plan_error, preflight_error, context_error, path_error, trace_error, run_error, gdb_session_error) if item]
    if runtime_normalization_error:
        errors.append(runtime_normalization_error)
    if bundle_obj is None and viewer_obj is None:
        errors.append("bundle_or_viewer_model_required")
    conflicts: list[dict[str, Any]] = []
    for label, artifact in (
        ("code_context", context_obj),
        ("event_code_path", path_obj),
        ("runtime_evidence", runtime_obj),
        ("gdb_session", gdb_session_obj),
    ):
        for conflict in _identity_conflicts(
            label_left="bundle",
            left=bundle_obj,
            label_right=label,
            right=artifact,
        ):
            if conflict not in conflicts:
                conflicts.append(conflict)
    bundle_source_hash = _source_snapshot_hash(bundle_obj)
    context_source_hash = _source_snapshot_hash(context_obj)
    if bundle_source_hash and context_source_hash and bundle_source_hash != context_source_hash:
        conflicts.append({
            "field": "source_snapshot_hash",
            "bundle": bundle_source_hash,
            "code_context": context_source_hash,
            "reason": "bundle_and_code_context_are_bound_to_different_source_snapshots",
        })
        errors.append("code_context_source_snapshot_mismatch")
    for conflict in conflicts:
        errors.append(f"artifact_identity_mismatch:{conflict.get('field', 'unknown')}:{next((key for key in ('code_context', 'event_code_path', 'runtime_evidence') if key in conflict), 'artifact')}")
    base = bundle_obj or viewer_obj or {}
    source_events = [item for item in _as_list(base.get("alarm_events") if bundle_obj else base.get("events")) if isinstance(item, Mapping)]
    if viewer_obj and isinstance(viewer_obj.get("events"), list):
        source_events = [item for item in viewer_obj.get("events", []) if isinstance(item, Mapping)]
    query = build_evidence_query(
        bundle=bundle_obj,
        viewer_model=viewer_obj,
        runtime_evidence=runtime_obj,
        event_id=event_id,
        event_index=event_index,
        function=function,
        side=side,
        radar_id=radar_id,
        frame_id=frame_id,
        max_events=1,
        max_frames=max_frames,
        max_targets=max_targets,
        include_details=True,
        # The report must retain the full normalized runtime field set for
        # condition binding (including struct-derived fields after the first
        # bounded slice).  The HTML read model still renders only key facts.
        max_field_rows=256,
    )
    selected = query.get("events", [])[0] if query.get("events") else None
    timeline_obj = build_alert_timeline(
        bundle=bundle_obj,
        viewer_model=viewer_obj,
        runtime_evidence=runtime_obj,
        # Let the timeline engine retain all same-data event rows for the
        # playback frame map when a concrete filter is present.  A direct
        # index-only report still passes the query projection below.
        selected_event=(
            selected
            if isinstance(selected, Mapping) and not any((event_id, function, side, radar_id, frame_id))
            else None
        ),
        event_id=event_id,
        function=function,
        side=side,
        radar_id=radar_id,
        frame_id=frame_id,
    )
    timeline_conflicts = [
        dict(item) for item in timeline_obj.get("conflicts", []) or [] if isinstance(item, Mapping)
    ]
    for conflict in timeline_conflicts:
        if conflict not in conflicts:
            conflicts.append(conflict)
    if timeline_conflicts:
        errors.extend(f"alert_timeline_identity_conflict:{item.get('field', 'unknown')}" for item in timeline_conflicts)
    if trace_obj is None:
        trace_event = selected
        if conflicts and isinstance(selected, Mapping):
            # Do not let a runtime artifact with a conflicting identity feed
            # the deterministic condition binder.  Keep the original query
            # and conflict visible, but make the condition result a gap.
            trace_event = deepcopy(dict(selected))
            trace_event["runtime_observations"] = []
            trace_event["runtime_association"] = "identity_conflict"
        trace_obj = _derive_condition_trace(event=trace_event, event_code_path=path_obj, bundle=base)
    frame_mapping_conflicts = _frame_mapping_conflicts(selected if isinstance(selected, Mapping) else None)
    geometry_source_root = str(
        ((path_obj.get("source_context") or {}).get("source_root", ""))
        if isinstance(path_obj, Mapping)
        else ""
    )
    geometry_projection_obj = _geometry_projection(
        selected if isinstance(selected, Mapping) else None,
        condition_trace=trace_obj,
        source_root=geometry_source_root,
    )
    gdb_confirmation_obj = _gdb_confirmation(
        runtime_obj,
        selected if isinstance(selected, Mapping) else None,
        gdb_session_obj,
        timeline_obj,
    )
    execution_context_obj = _execution_context_summary(preflight_obj, plan_obj, runtime_obj, gdb_confirmation_obj)
    can_output_obj = _source_output_mapping(
        preflight_obj,
        selected if isinstance(selected, Mapping) else None,
        event_code_path=path_obj,
        code_context=context_obj,
    )
    narrative_obj = build_diagnostic_narrative(
        selected_event=selected if isinstance(selected, Mapping) else None,
        condition_trace=trace_obj,
        alert_timeline=timeline_obj,
        geometry_projection=geometry_projection_obj,
        frame_mapping_conflicts=frame_mapping_conflicts,
        can_output=can_output_obj,
        event_code_path=path_obj,
        output_endpoint=output_endpoint,
        can_data_status=_detect_can_data_status(bundle_obj, runtime_obj, can_data_status),
    )
    event_map_query = build_evidence_query(
        bundle=bundle_obj,
        viewer_model=viewer_obj,
        runtime_evidence=runtime_obj,
        event_id=event_id,
        event_index=event_index,
        function=function,
        side=side,
        radar_id=radar_id,
        frame_id=frame_id,
        max_events=max_events,
        max_frames=1,
        max_targets=max_targets,
        include_details=False,
    )
    event_index_rows = []
    for item in event_map_query.get("events", []) or []:
        if not isinstance(item, Mapping):
            continue
        summary = item.get("summary") if isinstance(item.get("summary"), Mapping) else {}
        row = deepcopy(dict(summary))
        row["event_id"] = item.get("event_id")
        event_index_rows.append(row)
    case = base.get("case") if isinstance(base.get("case"), Mapping) else {}
    provenance = base.get("provenance") if isinstance(base.get("provenance"), Mapping) else {}
    source = base.get("source_context") if isinstance(base.get("source_context"), Mapping) else {}
    source_identity = source.get("identity") if isinstance(source.get("identity"), Mapping) else {}
    runtime_run = runtime_obj.get("run") if isinstance(runtime_obj, Mapping) and isinstance(runtime_obj.get("run"), Mapping) else {}
    identity = {
        "case_id": case.get("case_id") or case.get("data_id"),
        "data_name": case.get("bag") or case.get("data_id") or base.get("data_name"),
        "bag": case.get("bag") or provenance.get("bag_path") or runtime_run.get("bag"),
        "source_context_id": base.get("source_context_id") or provenance.get("source_context_id") or source.get("source_context_id") or source_identity.get("source_context_id") or runtime_run.get("source_context_id"),
        "source_snapshot_hash": provenance.get("source_snapshot_hash") or source.get("source_snapshot_hash") or source_identity.get("source_snapshot_hash") or runtime_run.get("source_snapshot_hash"),
        "project": provenance.get("project") or source.get("project_id") or source_identity.get("project_id") or runtime_run.get("project_id"),
        "variant_id": base.get("variant_id") or provenance.get("variant_id") or source.get("variant_id") or source_identity.get("variant_id") or runtime_run.get("variant_id"),
    }
    diagnosis_section = _build_diagnosis_section(
        bundle=base,
        runtime=runtime_obj,
        code_context=context_obj,
        analysis=analysis,
        query_events=[selected] if isinstance(selected, Mapping) else [],
        condition_trace=trace_obj,
        frame_mapping_conflicts=frame_mapping_conflicts,
        conflicts=conflicts,
    )
    timeline_identity_gaps = (timeline_obj.get("scope") or {}).get("identity_gaps", []) if isinstance(timeline_obj.get("scope"), Mapping) else []
    if timeline_identity_gaps:
        diagnosis_section.setdefault("evidence_gaps", []).append({
            "id": "identity_fingerprint_incomplete",
            "status": "partial",
            "reason": ", ".join(str(item) for item in timeline_identity_gaps),
        })
        if diagnosis_section.get("status") == "pending":
            diagnosis_section["status"] = "partial"
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
            "status": "blocked" if errors else "ready" if selected else "partial",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "identity": identity,
        "overview": {
            "event_count": len(source_events),
            "event_count_returned": len(event_index_rows),
            "function_counts": {
                str(name): sum(1 for item in event_index_rows if str(item.get("function")) == str(name))
                for name in sorted({str(item.get("function")) for item in event_index_rows if item.get("function")})
            },
            "radars": sorted({str(item.get("radar_id")) for item in event_index_rows if item.get("radar_id") not in (None, "")}),
            "runtime_status": runtime_obj.get("status", "not_available") if isinstance(runtime_obj, Mapping) else "not_available",
            "code_context_status": context_obj.get("status", "not_available") if isinstance(context_obj, Mapping) else "not_available",
            "timeline_status": timeline_obj.get("status", "not_available"),
            "timeline_row_count": len(timeline_obj.get("rows", []) or []),
            "timeline_frame_count": len(timeline_obj.get("playback_frame_map", []) or []),
            "should_alert": (narrative_obj.get("alarm_assessment") or {}).get("should_alert", "indeterminate"),
        },
        "event_index": event_index_rows,
        "selected_event": selected,
        "frame_mapping_conflicts": frame_mapping_conflicts,
        "diagnosis": diagnosis_section,
        "alert_timeline": timeline_obj,
        "diagnostic_narrative": narrative_obj,
        "diagnostic_story": deepcopy(narrative_obj.get("diagnostic_story") or {}),
        "analysis_flow": deepcopy(narrative_obj.get("analysis_flow") or {}),
        "geometry_projection": geometry_projection_obj,
        "gdb_confirmation": gdb_confirmation_obj,
        "execution_context": execution_context_obj,
        "can_output": can_output_obj,
        "output_policy": deepcopy(narrative_obj.get("output_policy") or {}),
        "arbe_preflight": {
            "status": preflight_obj.get("status", "not_available") if isinstance(preflight_obj, Mapping) else "not_available",
            "artifact_ref": _artifact_ref(preflight_ref),
            "server": deepcopy(preflight_obj.get("server", {})) if isinstance(preflight_obj, Mapping) else {},
            "workspace": deepcopy(preflight_obj.get("workspace", {})) if isinstance(preflight_obj, Mapping) else {},
            "configuration": deepcopy(preflight_obj.get("configuration", {})) if isinstance(preflight_obj, Mapping) else {},
            "build": deepcopy(preflight_obj.get("build", {})) if isinstance(preflight_obj, Mapping) else {},
            "runtime": {
                key: deepcopy(preflight_obj.get("runtime", {}).get(key))
                for key in ("status", "expected_process_pattern", "bash_start_required", "ros_nodes")
                if isinstance(preflight_obj, Mapping)
                and isinstance(preflight_obj.get("runtime"), Mapping)
                and preflight_obj.get("runtime", {}).get(key) not in (None, "", [])
            },
            "gdb": deepcopy(preflight_obj.get("gdb", {})) if isinstance(preflight_obj, Mapping) else {},
            "public_evidence": deepcopy(preflight_obj.get("public_evidence", {})) if isinstance(preflight_obj, Mapping) else {},
        },
        "next_actions": [],
        "analysis_trace": _analysis_trace(run_obj),
        "code_context": {
            "status": context_obj.get("status", "not_available") if isinstance(context_obj, Mapping) else "not_available",
            "summary": deepcopy(context_obj.get("summary", {})) if isinstance(context_obj, Mapping) else {},
            "artifact_ref": _artifact_ref(context_ref),
            "event_code_path": deepcopy(path_obj) if isinstance(path_obj, Mapping) else {},
            "runtime_debug_plan": deepcopy(plan_obj) if isinstance(plan_obj, Mapping) else {},
        },
        "condition_trace": deepcopy(trace_obj) if isinstance(trace_obj, Mapping) else {},
        "conclusion": {},
        "evidence_layers": [
            {"layer": "recorded_or_static_bundle", "status": "present" if bundle_obj else "not_available", "ref": _artifact_ref(bundle_ref)},
            {"layer": "viewer_projection", "status": "present" if viewer_obj else "not_available", "ref": _artifact_ref(viewer_ref)},
            {"layer": "runtime_observation", "status": runtime_obj.get("status", "present") if isinstance(runtime_obj, Mapping) else "not_available", "ref": _artifact_ref(runtime_ref)},
            {"layer": "arbe_preflight", "status": preflight_obj.get("status", "present") if isinstance(preflight_obj, Mapping) else "not_available", "ref": _artifact_ref(preflight_ref)},
            {"layer": "condition_trace", "status": trace_obj.get("status", "not_available") if isinstance(trace_obj, Mapping) else "not_available", "ref": _artifact_ref(trace_ref)},
            {"layer": "alert_timeline", "status": timeline_obj.get("status", "not_available"), "ref": {}},
            {"layer": "ai_interpretation", "status": "present_inference" if isinstance(analysis, Mapping) else "not_provided", "ref": {}},
        ],
        "input_refs": [_artifact_ref(item) for item in (bundle_ref, viewer_ref, runtime_ref, plan_ref, preflight_ref, context_ref, path_ref, trace_ref, run_ref, gdb_session_ref) if item],
        "artifact_refs": [_artifact_ref(item) for item in (bundle_ref, viewer_ref, runtime_ref, plan_ref, preflight_ref, context_ref, path_ref, trace_ref, gdb_session_ref) if item],
        "analysis_run_ref": _artifact_ref(run_ref),
        "conflicts": conflicts,
        "diagnostics": list(dict.fromkeys(
            errors
            + list(query.get("diagnostics", []) or [])
            + list(timeline_obj.get("diagnostics", []) or [])
        )),
    }
    report["conclusion"] = _build_diagnostic_conclusion(
        selected=selected if isinstance(selected, Mapping) else None,
        timeline=timeline_obj,
        diagnosis=report["diagnosis"],
        conflicts=conflicts,
        output_policy=narrative_obj.get("output_policy") if isinstance(narrative_obj.get("output_policy"), Mapping) else {},
    )
    report["conclusion"]["should_alert"] = (narrative_obj.get("alarm_assessment") or {}).get("should_alert", "indeterminate")
    report["conclusion"]["alarm_assessment"] = deepcopy(narrative_obj.get("alarm_assessment") or {})
    report["next_actions"] = _next_actions(report)
    report["report_fingerprint"] = _hash({key: value for key, value in report.items() if key not in {"generated_at", "report_fingerprint"}})
    return report


def write_diagnostic_report(report: Mapping[str, Any], output_dir: str | Path) -> list[str]:
    root = Path(output_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    markdown = _markdown(report)
    outputs = {
        "diagnostic-report.json": json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n",
        "diagnostic-report.md": markdown,
        "diagnostic-report.html": _html(report, markdown),
    }
    paths: list[str] = []
    for name, content in outputs.items():
        path = root / name
        path.write_text(content, encoding="utf-8")
        paths.append(str(path))
    return paths


__all__ = ["SCHEMA_VERSION", "build_diagnostic_report", "write_diagnostic_report"]
