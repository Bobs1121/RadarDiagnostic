"""Evidence-layer neutral alarm timeline projection.

The sibling harness and arbe expose several different alarm views.  This
engine does not decide whether an ADAS feature should warn; it only projects
already produced evidence into one comparable timeline while preserving the
source layer and frame semantics.

Supported producers are intentionally structural rather than feature-specific:

* ``diagnosis_bundle.alarm_events`` / viewer events -> ``recorded_raw`` or the
  layer carried by the event;
* ``runtime-snapshot-with-frame.v1`` -> warning rising edges and snapshots;
* ``runtime-case-evidence.v1`` -> observations and optional warning rows;
* replay/trace payloads -> rows carrying ``replay_algorithm`` or an explicit
  source/layer.

Missing evidence is represented as ``not_available`` or ``not_evaluated``;
there is no timestamp-neighbour object association here.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = "alert-timeline.v1"

EVIDENCE_LAYERS = (
    "recorded_raw",
    "replay_algorithm",
    "runtime_with_frame",
    "objectlist_candidate",
    "gdb_observation",
    "can_tx_observation",
)

_LAYER_ALIASES = {
    "raw": "recorded_raw",
    "recorded": "recorded_raw",
    "recorded_raw": "recorded_raw",
    "raw_warning": "recorded_raw",
    "algorithm": "replay_algorithm",
    "replay": "replay_algorithm",
    "replay_algorithm": "replay_algorithm",
    "algorithm_output": "replay_algorithm",
    "simulation": "replay_algorithm",
    "simulation_output": "replay_algorithm",
    "arbe": "replay_algorithm",
    "public": "runtime_with_frame",
    "runtime": "runtime_with_frame",
    "runtime_with_frame": "runtime_with_frame",
    "objectlist": "objectlist_candidate",
    "objectlist_candidate": "objectlist_candidate",
    "gdb": "gdb_observation",
    "gdb_observation": "gdb_observation",
    "can": "can_tx_observation",
    "can_tx": "can_tx_observation",
    "can_tx_observation": "can_tx_observation",
}


class AlertTimelineError(ValueError):
    """Raised when an alert timeline input is malformed."""


def _hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _load_object(value: Mapping[str, Any] | None, path_text: str, *, label: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None, str | None]:
    if value is not None:
        if not isinstance(value, Mapping):
            return None, None, f"{label}_must_be_object"
        payload = deepcopy(dict(value))
        return payload, {"label": label, "source": "inline", "sha256": _hash(payload)}, None
    text = str(path_text or "").strip()
    if not text:
        return None, None, None
    path = Path(text).expanduser().resolve()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return None, None, f"{label}_invalid:{type(exc).__name__}:{path}"
    if not isinstance(payload, Mapping):
        return None, None, f"{label}_must_be_object:{path}"
    data = deepcopy(dict(payload))
    return data, {"label": label, "source": "file", "path": str(path), "sha256": _hash(data)}, None


def _as_rows(value: Any) -> list[Mapping[str, Any]]:
    if value is None:
        return []
    if isinstance(value, Mapping):
        return [value]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [row for row in value if isinstance(row, Mapping)]
    return []


def _first(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value not in (None, "", []):
            return value
    return None


def _layer(value: Any, default: str) -> str:
    raw = str(value or "").strip().lower()
    return _LAYER_ALIASES.get(raw, raw if raw in EVIDENCE_LAYERS else default)


def _side(function: Any, value: Any = None) -> Any:
    if value not in (None, ""):
        return value
    text = str(function or "")
    suffix = text.rsplit("_", 1)[-1].upper() if "_" in text else ""
    return suffix if suffix in {"L", "R"} else None


def _identity(row: Mapping[str, Any]) -> Mapping[str, Any]:
    value = row.get("identity")
    return value if isinstance(value, Mapping) else row


def _event_view(event: Mapping[str, Any]) -> dict[str, Any]:
    """Flatten an evidence-query event without losing its wrapper identity."""
    details = event.get("details")
    if not isinstance(details, Mapping):
        return dict(event)
    result = deepcopy(dict(details))
    for key in ("event_id", "function", "side", "radar_id", "source"):
        if result.get(key) in (None, "", []) and event.get(key) not in (None, "", []):
            result[key] = event.get(key)
    summary = event.get("summary")
    if isinstance(summary, Mapping):
        result.setdefault("summary", deepcopy(dict(summary)))
        for key in ("function", "side", "radar_id", "source"):
            if result.get(key) in (None, "", []) and summary.get(key) not in (None, "", []):
                result[key] = summary.get(key)
        if isinstance(summary.get("first_frame"), Mapping) and not isinstance(result.get("frame"), Mapping):
            result["frame"] = deepcopy(dict(summary["first_frame"]))
    result.setdefault("event_id", event.get("event_id"))
    return result


def _number(value: Any) -> Any:
    if value in (None, "", []):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return value
    return int(number) if number.is_integer() else number


def _identity_value(payload: Mapping[str, Any] | None, key: str) -> Any:
    if not isinstance(payload, Mapping):
        return None
    candidates: list[Mapping[str, Any]] = [payload]
    for container_name in ("provenance", "source_context", "identity", "run", "binding"):
        container = payload.get(container_name)
        if isinstance(container, Mapping):
            candidates.append(container)
            nested_identity = container.get("identity")
            if isinstance(nested_identity, Mapping):
                candidates.append(nested_identity)
    for container in candidates:
        value = container.get(key)
        if value not in (None, "", []):
            return value
    return None


def _identity_conflicts(bundle: Mapping[str, Any] | None, runtime: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(bundle, Mapping) or not isinstance(runtime, Mapping):
        return []
    conflicts: list[dict[str, Any]] = []
    for key in ("data_fingerprint", "source_context_id", "source_snapshot_hash", "binary_fingerprint"):
        left = _identity_value(bundle, key)
        right = _identity_value(runtime, key)
        if left not in (None, "", []) and right not in (None, "", []) and str(left) != str(right):
            conflicts.append({
                "field": key,
                "bundle": left,
                "runtime": right,
                "reason": "runtime_overlay_and_static_bundle_have_different_identity",
            })
    return conflicts


def _frame_status(row: Mapping[str, Any], *, frame: Any, default: str = "not_available") -> str:
    if frame in (None, "", []):
        return "not_available"
    if str(row.get("layer") or "").lower() in {"gdb_observation", "can_tx_observation"}:
        return "observed"
    explicit = str(_first(row, "frame_status", "association_status", "frame_confidence", "selection_confidence") or "").lower()
    if explicit in {"frame_verified", "observed", "exact_frame", "exact"}:
        return "observed"
    if explicit in {"callback_correlated", "publication_correlated", "derived"}:
        return "derived"
    frame_source = str(_first(row, "frame_source", "frame_id_source", "target_frame_source") or "").lower()
    if "derived" in frame_source or "publication_order" in frame_source:
        return "derived"
    if frame_source in {"wfautosardata.frameid", "algorithm_frame", "replay_trace.frame_id", "frame_counter", "can_tx"} or any(
        marker in frame_source
        for marker in ("warning_status_with_frame", "radar_info", "object_message_frame")
    ):
        return "observed"
    return default


def _target_fields(row: Mapping[str, Any]) -> tuple[Any, dict[str, Any]]:
    row = _event_view(row) if isinstance(row.get("details"), Mapping) else row
    selected = row.get("selected_target") if isinstance(row.get("selected_target"), Mapping) else row.get("target")
    if not isinstance(selected, Mapping):
        selected = row
    raw = selected.get("raw") if isinstance(selected.get("raw"), Mapping) else selected
    indices: dict[str, Any] = {}
    aliases = {
        "raw_sgu_index": ("raw_sgu_index", "input_index", "trc_index_i"),
        "algorithm_object_index": ("algorithm_object_index", "algorithm_index"),
        "objectlist_index": ("objectlist_index", "object_index"),
    }
    for name, keys in aliases.items():
        value = _first(selected, *keys)
        if value in (None, "", []):
            value = _first(raw, *keys)
        if value in (None, "", []):
            mapping = selected.get("index_mapping")
            if isinstance(mapping, Mapping):
                value = _first(mapping, *keys)
        if value in (None, "", []):
            mapping = row.get("target_index")
            if isinstance(mapping, Mapping):
                value = _first(mapping, *keys)
        if value not in (None, "", []):
            indices[name] = value
    object_id = _first(selected, "obj_id", "objID", "object_id", "objectId")
    if object_id in (None, "", []):
        object_id = _first(raw, "obj_id", "objID", "object_id", "objectId")
    identity = _identity(row)
    if object_id in (None, "", []):
        object_id = _first(identity, "object_id", "obj_id", "objID", "objectId")
    for name, keys in aliases.items():
        if name not in indices:
            value = _first(identity, *keys)
            if value not in (None, "", []):
                indices[name] = value
    return object_id, indices


def _event_first_frame(event: Mapping[str, Any]) -> tuple[Any, str, str]:
    event = _event_view(event)
    for key in ("first_on_frame", "threshold_crossing_frame"):
        value = event.get(key)
        if value not in (None, "", []):
            return value, "observed", key
    precheck = event.get("frame_precheck")
    if isinstance(precheck, Mapping):
        value = _first(precheck, "alarm_first_frame_id", "frame_id")
        if value not in (None, "", []):
            confidence = str(precheck.get("alarm_first_frame_confidence", "derived"))
            return value, "observed" if confidence in {"frame_verified", "exact_frame"} else "derived", str(precheck.get("alarm_first_frame_source", "frame_precheck"))
    frame = event.get("frame")
    if isinstance(frame, Mapping):
        value = _first(frame, "target_frame", "alarm_first_frame_id", "frame_id")
        if value not in (None, "", []):
            return value, _frame_status(frame, frame=value, default="derived"), str(_first(frame, "target_frame_source", "frame_id_source") or "frame")
    replay = event.get("replay_plan")
    if isinstance(replay, Mapping):
        value = _first(replay, "target_frame_id", "frame_id")
        if value not in (None, "", []):
            return value, "derived", str(_first(replay, "target_frame_source", "replay_plan") or "replay_plan")
    return None, "not_available", "not_available"


def _event_row(event: Mapping[str, Any], *, default_layer: str = "recorded_raw") -> dict[str, Any]:
    event = _event_view(event)
    identity = _identity(event)
    function = _first(event, "function") or _first(identity, "function")
    side = _side(function, _first(event, "side") or _first(identity, "side"))
    radar = _first(event, "radar_id") or _first(identity, "radar_id")
    event_layer = _first(event, "source", "layer") or _first(identity, "source", "layer")
    frame, frame_status, frame_source = _event_first_frame(event)
    object_id, indices = _target_fields(event)
    alarm = event.get("alarm") if isinstance(event.get("alarm"), Mapping) else event
    return {
        "source_id": _layer(event_layer, default_layer),
        "layer": _layer(event_layer, default_layer),
        "function": function,
        "side": side,
        "radar_id": radar,
        "frame_id": frame,
        "frame_status": frame_status,
        "frame_source": frame_source,
        "time_sec": _first(event, "start_time_sec", "timestamp_sec") or _first(alarm, "start_time_sec", "timestamp_sec"),
        "transition": "rising_candidate",
        "value": 1,
        "signal": function,
        "object_id": object_id,
        "indices": indices,
        "event_id": event.get("event_id"),
        "evidence_refs": deepcopy(event.get("evidence_refs", [])) if isinstance(event.get("evidence_refs"), list) else [],
        "status": "observed" if frame_status == "observed" else "derived" if frame_status == "derived" else "partial",
    }


def _warning_rows_from_mapping(value: Any) -> list[tuple[str, Any]]:
    if isinstance(value, Mapping):
        return [(str(name), state) for name, state in value.items()]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        result: list[tuple[str, Any]] = []
        for item in value:
            if isinstance(item, Mapping):
                name = _first(item, "signal_name", "function", "name", "token")
                if name not in (None, ""):
                    result.append((str(name), _first(item, "value", "active", "state") if _first(item, "value", "active", "state") is not None else 1))
            elif isinstance(item, str) and item.strip():
                result.append((item.strip(), 1))
        return result
    return []


def _runtime_row(*, row: Mapping[str, Any], signal: Any, value: Any, default_layer: str, transition: str = "active") -> dict[str, Any]:
    identity = _identity(row)
    function = _first(row, "function") or _first(identity, "function")
    signal_name = str(signal or function or "").strip() or None
    if not function and signal_name and not signal_name.lower().startswith(("w", "warning")):
        function = signal_name
    frame = _first(row, "frame_id", "frameID", "frame_counter") or _first(identity, "frame_id", "frameID", "frame_counter")
    radar = _first(row, "radar_id", "radar") or _first(identity, "radar_id", "radar")
    object_id, indices = _target_fields(row)
    frame_fact = {**dict(identity), **dict(row)}
    frame_status = _frame_status(frame_fact, frame=frame)
    return {
        "source_id": _layer(_first(row, "source", "layer", "authority"), default_layer),
        "layer": _layer(_first(row, "source", "layer", "authority"), default_layer),
        "function": function,
        "side": _side(function, _first(row, "side") or _first(identity, "side")),
        "radar_id": radar,
        "frame_id": frame,
        "frame_status": frame_status,
        "frame_source": _first(row, "frame_source", "frame_id_source") or _first(identity, "frame_source", "frame_id_source"),
        "time_sec": _first(row, "timestamp_sec", "record_time", "time_sec", "bag_time") or _first(identity, "timestamp_sec", "record_time", "time_sec"),
        "transition": transition,
        "value": value,
        "signal": signal_name,
        "object_id": object_id,
        "indices": indices,
        "event_id": _first(row, "event_id") or _first(identity, "event_id"),
        "evidence_refs": deepcopy(row.get("evidence_refs", [])) if isinstance(row.get("evidence_refs"), list) else [],
        "status": "observed" if frame_status == "observed" else "derived" if frame not in (None, "", []) else "partial",
    }


def _runtime_rows(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for nested_key in ("runtime_snapshot", "runtime_evidence", "snapshot"):
        nested = payload.get(nested_key)
        if isinstance(nested, Mapping) and nested is not payload:
            result.extend(_runtime_rows(nested))
    schema = str(payload.get("schema_version", ""))
    default_layer = "runtime_with_frame"
    if schema == "runtime-case-evidence.v1":
        for edge in _as_rows(payload.get("warning_rising_edges")):
            edge_value = _first(edge, "value", "active")
            result.append(_runtime_row(row=edge, signal=_first(edge, "signal_name", "function", "name"), value=1 if edge_value is None else edge_value, default_layer="runtime_with_frame", transition="rising"))
        for observation in _as_rows(payload.get("observations")):
            identity = _identity(observation)
            warning_value = _first(observation, "warnings", "warning", "active_warnings", "active", "alarm")
            warning_pairs = _warning_rows_from_mapping(warning_value)
            had_warning_fields = bool(warning_pairs)
            if warning_pairs:
                for name, value in warning_pairs:
                    result.append(_runtime_row(row=observation, signal=name, value=value, default_layer=_layer(observation.get("layer"), default_layer)))
            else:
                warning_fields: list[tuple[str, Any]] = []
                for field in _as_rows(observation.get("fields")):
                    source = field.get("source") if isinstance(field.get("source"), Mapping) else {}
                    token = str(field.get("token") or "").lower()
                    scope = str(field.get("scope") or source.get("signal_name") or "").strip()
                    source_kind = str(source.get("kind") or "").lower()
                    if scope and ("warning" in source_kind or "warning" in token):
                        warning_fields.append((scope, field.get("value")))
                had_warning_fields = bool(warning_fields)
                for name, value in warning_fields:
                    result.append(_runtime_row(row=observation, signal=name, value=value, default_layer=_layer(observation.get("layer"), default_layer)))
            if not had_warning_fields:
                # Keep a function-scoped observation even when it contains no
                # warning field.  This makes the runtime source visible while
                # leaving the alarm value unresolved.
                function = _first(observation, "function") or _first(identity, "function")
                if function:
                    result.append(_runtime_row(row=observation, signal=function, value=_first(observation, "value", "active"), default_layer=_layer(observation.get("layer"), default_layer), transition="observation"))
                elif _first(identity, "frame_id", "frameID", "frame_counter") not in (None, ""):
                    # Preserve a frame-bound ego/object/GDB observation even
                    # when it has no feature callback name.  The report can
                    # show its fields without inventing a warning signal.
                    result.append(_runtime_row(row=observation, signal=None, value=None, default_layer=_layer(observation.get("layer"), default_layer), transition="observation"))
    elif schema == "runtime-snapshot-with-frame.v1":
        for edge in _as_rows(payload.get("warning_rising_edges")):
            edge_value = _first(edge, "value", "active")
            result.append(_runtime_row(row=edge, signal=_first(edge, "signal_name", "function", "name"), value=1 if edge_value is None else edge_value, default_layer="runtime_with_frame", transition="rising"))
        for snapshot in _as_rows(payload.get("snapshots")):
            warning = snapshot.get("warning") if isinstance(snapshot.get("warning"), Mapping) else {}
            pairs = _warning_rows_from_mapping(_first(warning, "warnings", "active_warnings", "active", "bits"))
            for name, value in pairs:
                if bool(value):
                    result.append(_runtime_row(row={**dict(snapshot), "layer": "runtime_with_frame"}, signal=name, value=value, default_layer="runtime_with_frame"))
    # Generic replay/GDB/CAN payloads: accept explicit rows but never infer a
    # layer from a feature name.
    for key, fallback_layer in (
        ("replay_rows", "replay_algorithm"),
        ("trace", "replay_algorithm"),
        ("events", "replay_algorithm"),
        ("gdb_observations", "gdb_observation"),
        ("can_tx_observations", "can_tx_observation"),
        ("can_tx", "can_tx_observation"),
    ):
        for item in _as_rows(payload.get(key)):
            warnings = _first(item, "warnings", "warning", "active_warnings", "active")
            pairs = _warning_rows_from_mapping(warnings)
            if pairs:
                for name, value in pairs:
                    result.append(_runtime_row(row=item, signal=name, value=value, default_layer=fallback_layer))
            else:
                signal = _first(item, "signal", "signal_name", "function", "name", "token")
                if signal:
                    result.append(_runtime_row(row={**dict(item), "layer": item.get("layer", fallback_layer)}, signal=signal, value=_first(item, "value", "active", "state"), default_layer=fallback_layer))
    return result


def _event_frames(event: Mapping[str, Any]) -> list[dict[str, Any]]:
    event = _event_view(event)
    details = event.get("details") if isinstance(event.get("details"), Mapping) else event
    timeline = details.get("timeline") if isinstance(details, Mapping) and isinstance(details.get("timeline"), Mapping) else {}
    rows = timeline.get("frames") if isinstance(timeline, Mapping) else None
    if not isinstance(rows, list):
        rows = details.get("frame_evidence") if isinstance(details, Mapping) else []
    if not isinstance(rows, list):
        rows = []
    warmup = details.get("frame", {}).get("warmup") if isinstance(details.get("frame"), Mapping) and isinstance(details.get("frame", {}).get("warmup"), Mapping) else {}
    warmup_ids = {str(item.get("frame_id")) for item in _as_rows(warmup.get("frame_refs")) if item.get("frame_id") not in (None, "")}
    selected = _first(details.get("frame", {}) if isinstance(details.get("frame"), Mapping) else {}, "target_frame", "alarm_first_frame_id")
    result: list[dict[str, Any]] = []
    for row in rows:
        frame = _first(row, "frame_id", "frameID", "frame_counter")
        if frame in (None, ""):
            continue
        if str(frame) == str(selected):
            state = "selected_analysis_frame"
        elif str(frame) in warmup_ids:
            state = "warmup"
        else:
            state = "context"
        result.append({
            "frame_id": frame,
            "time_sec": _first(row, "timestamp_sec", "time_sec", "record_time"),
            "state": state,
            "frame_status": "observed" if str(_first(row, "frame_id_source", "source") or "").lower() in {"wfasutodata.frameid", "wfautosardata.frameid", "algorithm_frame"} else "derived",
            "source": _first(row, "source_ref", "topic", "source"),
        })
    for item in _as_rows(warmup.get("frame_refs")):
        frame = _first(item, "frame_id", "frameID", "frame_counter")
        if frame in (None, "") or any(str(existing.get("frame_id")) == str(frame) for existing in result):
            continue
        result.append({
            "frame_id": frame,
            "time_sec": _first(item, "timestamp_sec", "time_sec"),
            "state": "warmup",
            "frame_status": "observed" if item.get("frame_id_source") else "derived",
            "source": _first(item, "source_ref", "topic", "source"),
        })
    return result


def _match(row: Mapping[str, Any], *, event_id: str, function: str, side: str, radar_id: str, frame_id: str) -> bool:
    if event_id and str(row.get("event_id") or "") != event_id:
        return False
    if function:
        actual = str(row.get("function") or row.get("signal") or "").upper()
        expected = function.upper()
        if actual and actual != expected and not actual.startswith(expected + "_"):
            return False
    if side and row.get("side") not in (None, "") and str(row.get("side")).upper() != side.upper():
        return False
    if radar_id and row.get("radar_id") not in (None, "") and str(row.get("radar_id")) != radar_id:
        return False
    if frame_id and str(row.get("frame_id")) != frame_id:
        return False
    return True


def _source_status(rows: list[dict[str, Any]], layer: str) -> str:
    layer_rows = [row for row in rows if row.get("layer") == layer]
    if not layer_rows:
        return "not_available"
    if any(row.get("status") == "observed" for row in layer_rows):
        return "observed"
    if any(row.get("status") == "derived" for row in layer_rows):
        return "derived"
    return "partial"


def _compare(rows: list[dict[str, Any]], left: str, right: str) -> dict[str, Any]:
    left_rows = [row for row in rows if row.get("layer") == left]
    right_rows = [row for row in rows if row.get("layer") == right]
    base = {"left": left, "right": right, "status": "not_evaluated", "differences": [], "resolution": "none"}
    if not left_rows or not right_rows:
        base["reason"] = "one_or_both_evidence_layers_not_available"
        return base
    left_keys = {(str(row.get("function") or row.get("signal") or ""), str(row.get("side") or ""), str(row.get("radar_id") or "")) for row in left_rows}
    right_keys = {(str(row.get("function") or row.get("signal") or ""), str(row.get("side") or ""), str(row.get("radar_id") or "")) for row in right_rows}
    if left_keys != right_keys:
        base["status"] = "different"
        base["differences"].append({"kind": "scope", "left": sorted(left_keys), "right": sorted(right_keys)})
    def target_keys(items: list[dict[str, Any]]) -> set[tuple[str, str, str, str, str]]:
        result: set[tuple[str, str, str, str, str]] = set()
        for item in items:
            object_id = item.get("object_id")
            indices = item.get("indices") if isinstance(item.get("indices"), Mapping) else {}
            if object_id in (None, "", []) and not indices:
                continue
            result.add((
                str(object_id),
                str(indices.get("raw_sgu_index", "")),
                str(indices.get("algorithm_object_index", "")),
                str(indices.get("objectlist_index", "")),
                str(item.get("frame_id", "")),
            ))
        return result
    left_targets = target_keys(left_rows)
    right_targets = target_keys(right_rows)
    if left_targets and right_targets and left_targets != right_targets:
        base["status"] = "different"
        base["differences"].append({"kind": "target_identity", "left": sorted(left_targets), "right": sorted(right_targets)})
    left_frames = {str(row.get("frame_id")) for row in left_rows if row.get("frame_id") not in (None, "") and row.get("frame_status") == "observed"}
    right_frames = {str(row.get("frame_id")) for row in right_rows if row.get("frame_id") not in (None, "") and row.get("frame_status") == "observed"}
    if left_frames and right_frames:
        if left_frames == right_frames and base["status"] != "different":
            base["status"] = "same"
            base["resolution"] = "source_authoritative"
        elif left_frames != right_frames:
            base["status"] = "different"
            base["differences"].append({"kind": "frame", "left": sorted(left_frames), "right": sorted(right_frames)})
    else:
        base["status"] = "not_comparable"
        base["reason"] = "at_least_one_layer_has_no_observed_algorithm_frame"
    return base


def _bound_timeline_rows(
    rows: list[dict[str, Any]],
    *,
    limit: int,
    selected_frame: Any = None,
) -> tuple[list[dict[str, Any]], bool]:
    """Bound rows while retaining selected-frame and every evidence layer."""
    max_rows = max(1, int(limit))
    if len(rows) <= max_rows:
        return rows, False
    selected_text = str(selected_frame) if selected_frame not in (None, "", []) else ""
    priority = [
        row for row in rows
        if selected_text and str(row.get("frame_id")) == selected_text
    ]
    bounded: list[dict[str, Any]] = []
    seen: set[int] = set()
    for row in priority:
        marker = id(row)
        if marker not in seen and len(bounded) < max_rows:
            seen.add(marker)
            bounded.append(row)
    buckets: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if id(row) in seen:
            continue
        buckets.setdefault(str(row.get("layer", "unknown")), []).append(row)
    bucket_names = list(buckets)
    while len(bounded) < max_rows and bucket_names:
        next_names: list[str] = []
        for name in bucket_names:
            bucket = buckets[name]
            if bucket and len(bounded) < max_rows:
                bounded.append(bucket.pop(0))
            if bucket:
                next_names.append(name)
        bucket_names = next_names
    return bounded, True


def _mark_transitions(rows: list[dict[str, Any]]) -> None:
    """Mark deterministic 0↔non-zero changes within one evidence stream."""
    def active(value: Any) -> bool:
        return value not in (None, "", 0, 0.0, False, "0", "false", "False", "off", "OFF")

    groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        if row.get("layer") == "recorded_raw":
            continue
        key = (
            str(row.get("layer", "")),
            str(row.get("function") or row.get("signal") or ""),
            str(row.get("side") or ""),
            str(row.get("radar_id") or ""),
        )
        groups.setdefault(key, []).append(row)
    for grouped in groups.values():
        grouped.sort(
            key=lambda row: (
                float(row.get("time_sec")) if isinstance(row.get("time_sec"), (int, float)) else float("inf"),
                int(row.get("frame_id")) if str(row.get("frame_id", "")).lstrip("-").isdigit() else 10**18,
            )
        )
        previous = False
        seen_sample = False
        for row in grouped:
            current = active(row.get("value"))
            if row.get("transition") in (None, "", "active", "observation"):
                if current and not previous:
                    # A capture beginning while a signal is already active
                    # does not prove a rising edge; require an earlier
                    # explicit sample in this stream.
                    row["transition"] = "rising" if seen_sample else "active"
                elif not current and previous:
                    row["transition"] = "falling"
                elif current:
                    row["transition"] = "active"
                else:
                    row["transition"] = "inactive"
            previous = current
            seen_sample = True


def build_alert_timeline(
    *,
    bundle: Mapping[str, Any] | None = None,
    bundle_path: str = "",
    viewer_model: Mapping[str, Any] | None = None,
    viewer_model_path: str = "",
    runtime_evidence: Mapping[str, Any] | None = None,
    runtime_evidence_path: str = "",
    selected_event: Mapping[str, Any] | None = None,
    event_id: str = "",
    function: str = "",
    side: str = "",
    radar_id: str | int = "",
    frame_id: str | int = "",
    max_rows: int = 240,
) -> dict[str, Any]:
    bundle_obj, bundle_ref, bundle_error = _load_object(bundle, bundle_path, label="bundle")
    viewer_obj, viewer_ref, viewer_error = _load_object(viewer_model, viewer_model_path, label="viewer_model")
    runtime_obj, runtime_ref, runtime_error = _load_object(runtime_evidence, runtime_evidence_path, label="runtime_evidence")
    errors = [item for item in (bundle_error, viewer_error, runtime_error) if item]
    conflicts = _identity_conflicts(bundle_obj, runtime_obj)
    if bundle_obj is None and viewer_obj is None and not isinstance(selected_event, Mapping):
        errors.append("bundle_or_viewer_model_or_selected_event_required")
    bundle_events = [row for row in _as_rows(bundle_obj.get("alarm_events") if bundle_obj else None)]
    viewer_events = [row for row in _as_rows(viewer_obj.get("events") if viewer_obj else None)]
    viewer_by_id = {str(row.get("event_id")): row for row in viewer_events if row.get("event_id") not in (None, "")}
    if isinstance(selected_event, Mapping):
        source_event = selected_event
        event_rows = [source_event]
    else:
        event_rows = bundle_events or viewer_events
        source_event = None
    context_rows: list[dict[str, Any]] = []
    if isinstance(selected_event, Mapping):
        context_rows = [_event_row(selected_event, default_layer="recorded_raw")]
    else:
        for event in event_rows:
            viewer_event = viewer_by_id.get(str(event.get("event_id")))
            context_rows.append(_event_row(viewer_event or event, default_layer=str(event.get("source") or "recorded_raw")))
    current_event = source_event
    if current_event is None and (event_id or function or side or radar_id or frame_id):
        for event in event_rows:
            candidate = viewer_by_id.get(str(event.get("event_id"))) or event
            candidate_row = _event_row(candidate, default_layer=str(event.get("source") or "recorded_raw"))
            if _match(candidate_row, event_id=str(event_id or ""), function=str(function or ""), side=str(side or ""), radar_id=str(radar_id or ""), frame_id=str(frame_id or "")):
                current_event = candidate
                break
    rows: list[dict[str, Any]] = []
    for event in event_rows:
        viewer_event = viewer_by_id.get(str(event.get("event_id")))
        item = _event_row(viewer_event or event, default_layer=str(event.get("source") or "recorded_raw"))
        if item.get("event_id") in (None, ""):
            item["event_id"] = event.get("event_id")
        if _match(item, event_id=str(event_id or ""), function=str(function or ""), side=str(side or ""), radar_id=str(radar_id or ""), frame_id=str(frame_id or "")):
            rows.append(item)
        if source_event is None and not selected_event and not function and not side and not radar_id and not frame_id and not event_id:
            # Keep all events in a batch timeline, bounded below.
            continue
    # If this is a batch projection, the loop above already contains all
    # source events.  If a selected event was supplied, its details may hold
    # the exact frame map that is not present in the bundle event.
    if source_event is None and not (function or side or radar_id or frame_id or event_id):
        rows = [_event_row(viewer_by_id.get(str(event.get("event_id"))) or event, default_layer=str(event.get("source") or "recorded_raw")) for event in event_rows]
    runtime_rows = _runtime_rows(runtime_obj) if isinstance(runtime_obj, Mapping) else []
    scope_flat = _event_view(current_event) if isinstance(current_event, Mapping) else {}
    scope_identity = _identity(scope_flat)
    scope_summary = scope_flat.get("summary") if isinstance(scope_flat.get("summary"), Mapping) else {}
    runtime_event_id = str(event_id or (scope_flat.get("event_id") if isinstance(scope_flat, Mapping) else ""))
    runtime_function = str(function or _first(scope_flat, "function") or _first(scope_summary, "function") or _first(scope_identity, "function") or "")
    runtime_side = str(side or _first(scope_flat, "side") or _first(scope_summary, "side") or _first(scope_identity, "side") or "")
    runtime_radar_id = str(radar_id or _first(scope_flat, "radar_id") or _first(scope_summary, "radar_id") or _first(scope_identity, "radar_id") or "")
    runtime_rows = [
        row for row in runtime_rows
        if _match(
            row,
            # A runtime producer often cannot carry the static event_id.  In
            # that case function/side/radar/frame remain the binding keys;
            # do not discard an otherwise eligible observation.
            event_id=runtime_event_id if row.get("event_id") not in (None, "") else "",
            function=runtime_function,
            side=runtime_side,
            radar_id=runtime_radar_id,
            # Keep the selected frame as report scope, but retain runtime
            # transitions in the same event/radar window (for example an
            # algorithm rising edge one cycle before a time-aligned raw
            # candidate).  The comparison layer will mark that as different
            # or not_comparable instead of hiding the clue.
            frame_id="",
        )
    ]
    _mark_transitions(runtime_rows)
    rows.extend(runtime_rows)
    limit = max(1, int(max_rows))
    selected_frame_for_bound = frame_id
    if selected_frame_for_bound in (None, "", []):
        selected_frame_for_bound = _event_first_frame(current_event)[0] if isinstance(current_event, Mapping) else None
    rows, truncated = _bound_timeline_rows(rows, limit=limit, selected_frame=selected_frame_for_bound)

    if current_event is None and rows and rows[0].get("event_id"):
        for event in event_rows:
            if str(event.get("event_id")) == str(rows[0].get("event_id")):
                current_event = viewer_by_id.get(str(event.get("event_id"))) or event
                break
    playback = _event_frames(current_event) if isinstance(current_event, Mapping) else []
    for item in runtime_rows:
        frame = item.get("frame_id")
        if frame in (None, ""):
            continue
        existing = next((entry for entry in playback if str(entry.get("frame_id")) == str(frame)), None)
        if existing is None:
            playback.append({"frame_id": frame, "time_sec": item.get("time_sec"), "state": "runtime_observed", "frame_status": item.get("frame_status"), "source": item.get("source_id")})
        elif existing.get("state") == "context" and item.get("frame_status") == "observed":
            existing["state"] = "runtime_observed"
    playback.sort(key=lambda item: (float(item.get("time_sec")) if isinstance(item.get("time_sec"), (int, float)) else float("inf"), str(item.get("frame_id"))))
    playback_context_rows = [*context_rows, *runtime_rows]
    for entry in playback:
        frame = str(entry.get("frame_id"))
        alarm_rows: list[dict[str, Any]] = [
            {"layer": row.get("layer"), "function": row.get("function") or row.get("signal"), "side": row.get("side"), "radar_id": row.get("radar_id"), "transition": row.get("transition"), "value": row.get("value"), "status": row.get("status")}
            for row in playback_context_rows if str(row.get("frame_id")) == frame
        ]
        unique_alarm_rows: list[dict[str, Any]] = []
        seen_alarm_rows: set[str] = set()
        for alarm_row in alarm_rows:
            key = json.dumps(alarm_row, ensure_ascii=False, sort_keys=True, default=str)
            if key not in seen_alarm_rows:
                seen_alarm_rows.add(key)
                unique_alarm_rows.append(alarm_row)
        entry["alarm_rows"] = unique_alarm_rows
        alarm_signals: list[str] = []
        for item in unique_alarm_rows:
            signal = str(item.get("function") or item.get("signal") or "")
            if signal and signal not in alarm_signals:
                alarm_signals.append(signal)
        entry["alarm_signals"] = alarm_signals

    source_layers = []
    for layer in EVIDENCE_LAYERS:
        layer_rows = [row for row in rows if row.get("layer") == layer]
        source_layers.append({
            "id": layer,
            "layer": layer,
            "authority": {"recorded_raw": "bag", "replay_algorithm": "arbe_replay", "runtime_with_frame": "arbe_public_runtime", "objectlist_candidate": "arbe_public_objectlist", "gdb_observation": "headless_gdb", "can_tx_observation": "can_trace"}[layer],
            "status": "conflict" if conflicts and layer != "recorded_raw" and layer_rows else _source_status(rows, layer),
            "row_count": len(layer_rows),
        })
    comparisons = [_compare(rows, left, right) for left, right in (("recorded_raw", "replay_algorithm"), ("recorded_raw", "runtime_with_frame"), ("replay_algorithm", "runtime_with_frame"), ("runtime_with_frame", "gdb_observation"), ("runtime_with_frame", "can_tx_observation"))]
    scope_event = current_event if isinstance(current_event, Mapping) else {}
    scope_identity = scope_event.get("identity") if isinstance(scope_event.get("identity"), Mapping) else {}
    summary = scope_event.get("summary") if isinstance(scope_event.get("summary"), Mapping) else {}
    selected_function = function or _first(scope_event, "function") or _first(summary, "function") or _first(scope_identity, "function")
    selected_side = side or _first(scope_event, "side") or _first(summary, "side") or _first(scope_identity, "side") or _side(selected_function)
    selected_radar = radar_id or _first(scope_event, "radar_id") or _first(summary, "radar_id") or _first(scope_identity, "radar_id")
    data_fingerprint = _identity_value(bundle_obj, "data_fingerprint")
    source_context_id = _identity_value(bundle_obj, "source_context_id")
    identity_gaps: list[str] = []
    if bundle_obj is not None and data_fingerprint in (None, "", []):
        identity_gaps.append("data_fingerprint_not_available")
    if bundle_obj is not None and source_context_id in (None, "", []):
        identity_gaps.append("source_context_id_not_available")
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "blocked" if errors or conflicts else "partial" if identity_gaps and (rows or playback) else "ready" if rows or playback else "partial",
        "scope": {
            "data_fingerprint": data_fingerprint,
            "source_context_id": source_context_id,
            "event_id": _first(scope_event, "event_id") or event_id,
            "function": selected_function,
            "side": selected_side,
            "radar_id": selected_radar,
            "frame_id": frame_id or _first(summary.get("first_frame", {}) if isinstance(summary.get("first_frame"), Mapping) else {}, "frame_id"),
            "identity_status": "partial" if identity_gaps else "ready",
            "identity_gaps": identity_gaps,
        },
        "sources": source_layers,
        "rows": rows,
        "context_alarm_rows": context_rows[:limit],
        "playback_frame_map": playback,
        "comparisons": comparisons,
        "conflicts": conflicts,
        "disturbance": deepcopy(runtime_obj.get("disturbance", {})) if isinstance(runtime_obj, Mapping) and isinstance(runtime_obj.get("disturbance"), Mapping) else {"status": "not_evaluated"},
        "input_refs": [ref for ref in (bundle_ref, viewer_ref, runtime_ref) if ref],
        "diagnostics": list(dict.fromkeys(errors + identity_gaps + [f"identity_conflict:{item['field']}" for item in conflicts] + (["timeline_rows_truncated"] if truncated else []))),
    }


__all__ = ["EVIDENCE_LAYERS", "SCHEMA_VERSION", "AlertTimelineError", "build_alert_timeline"]
