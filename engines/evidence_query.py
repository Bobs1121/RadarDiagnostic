"""Generic, provenance-preserving queries over CR60 evidence artifacts.

This engine deliberately sits between the sibling harness/viewer artifacts and
Pi.  It does not parse a bag, infer a target, evaluate a feature rule, or
search a source tree.  Its one job is to return a bounded slice of already
produced evidence for a selected event/frame/field.  That makes it useful for
both the detailed report recipe and conversational follow-up questions.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = "evidence-query.v1"
DEFAULT_FIELDS = ("alarm", "frame", "ego", "target", "code.call_chain", "breakpoint_pack", "evidence_gaps")


class EvidenceQueryError(ValueError):
    """Raised when an evidence query or artifact is malformed."""


def _load_object(
    value: Mapping[str, Any] | None,
    path_text: str,
    *,
    label: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, str | None]:
    if value is not None:
        if not isinstance(value, Mapping):
            return None, None, f"{label}_must_be_object"
        payload = dict(value)
        return payload, {
            "label": label,
            "source": "inline",
            "schema_version": payload.get("schema_version", ""),
            "sha256": _hash(payload),
        }, None
    if not str(path_text or "").strip():
        return None, None, None
    path = Path(path_text).expanduser().resolve()
    try:
        raw = path.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return None, None, f"{label}_invalid:{type(exc).__name__}:{path}"
    if not isinstance(payload, Mapping):
        return None, None, f"{label}_must_be_object:{path}"
    data = dict(payload)
    return data, {
        "label": label,
        "source": "file",
        "path": str(path),
        "schema_version": data.get("schema_version", ""),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }, None


def _hash(value: object) -> str:
    text = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _as_text_list(value: Sequence[Any] | str | None) -> list[str]:
    if isinstance(value, str):
        value = [value]
    result: list[str] = []
    for item in value or []:
        text = str(item or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _get_path(value: Any, path: str) -> tuple[bool, Any]:
    """Read a dotted path with list indexes without inventing missing values."""
    current = value
    text = str(path or "").strip().strip(".")
    if not text:
        return True, current
    for segment in text.split("."):
        if isinstance(current, Mapping) and segment in current:
            current = current[segment]
        elif isinstance(current, list) and segment.isdigit():
            index = int(segment)
            if 0 <= index < len(current):
                current = current[index]
            else:
                return False, None
        else:
            return False, None
    return True, current


def _first_non_empty(mapping: Mapping[str, Any], keys: Sequence[str]) -> tuple[Any, str]:
    for key in keys:
        value = mapping.get(key)
        if value not in (None, "", []):
            return value, key
    return None, ""


def _first_frame(event: Mapping[str, Any]) -> dict[str, Any]:
    """Return a selected frame without calling a replay target an alarm edge."""
    value, source = _first_non_empty(
        event,
        ("first_on_frame", "threshold_crossing_frame"),
    )
    if value is not None:
        return {
            "frame_id": value,
            "source": source,
            "definition": "output_first_frame_candidate",
            "confidence": "observed_event_field",
        }

    precheck = event.get("frame_precheck")
    if isinstance(precheck, Mapping):
        value = precheck.get("alarm_first_frame_id")
        if value not in (None, "", []):
            return {
                "frame_id": value,
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
            "confidence": "selected_frame_not_alarm_edge",
        }
    return {
        "frame_id": None,
        "source": "not_available",
        "definition": "not_available",
        "confidence": "not_available",
    }


def _event_frame_ids(event: Mapping[str, Any]) -> set[str]:
    values: set[str] = set()
    for path in ("frame_evidence", "timeline.frames"):
        ok, rows = _get_path(event, path)
        if not ok or not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            value = row.get("frame_id")
            if value not in (None, "", []):
                values.add(str(value))
    summary = _first_frame(event)
    if summary.get("frame_id") not in (None, "", []):
        values.add(str(summary["frame_id"]))
    return values


def _event_matches(
    event: Mapping[str, Any],
    *,
    event_id: str,
    function: str,
    side: str,
    radar_id: str,
    frame_id: str,
) -> bool:
    identity = event.get("identity") if isinstance(event.get("identity"), Mapping) else {}
    event_function = str(event.get("function") or identity.get("function") or "")
    event_side = str(identity.get("side") or event.get("side") or "")
    if not event_side and event_function.rsplit("_", 1)[-1].upper() in {"L", "R"}:
        event_side = event_function.rsplit("_", 1)[-1].upper()
    event_radar = event.get("radar_id")
    if event_radar in (None, ""):
        event_radar = identity.get("radar_id")
    if event_id and str(event.get("event_id") or "") != event_id:
        return False
    if function:
        requested_function = function.upper()
        actual_function = event_function.upper()
        if actual_function != requested_function and not actual_function.startswith(requested_function + "_"):
            return False
    if side and event_side.upper() != side.upper():
        return False
    if radar_id and str(event_radar) != radar_id:
        return False
    if frame_id and frame_id not in _event_frame_ids(event):
        return False
    return True


def _slice_rows(
    rows: Any,
    *,
    max_items: int,
    selected_frame_id: str = "",
    frame_key: str = "frame_id",
) -> tuple[list[Any], bool]:
    if not isinstance(rows, list):
        return [], False
    limit = max(1, int(max_items))
    if len(rows) <= limit:
        return list(rows), False
    selected_index = next(
        (
            index
            for index, row in enumerate(rows)
            if isinstance(row, Mapping)
            and selected_frame_id
            and str(row.get(frame_key, "")) == selected_frame_id
        ),
        None,
    )
    if selected_index is None:
        return list(rows[:limit]), True
    head = max(1, limit // 2)
    start = max(0, min(selected_index - head // 2, len(rows) - limit))
    sliced = list(rows[start : start + limit])
    return sliced, True


def _source_refs(
    event: Mapping[str, Any],
    refs: Sequence[Mapping[str, Any]],
    *,
    include_values: bool = True,
) -> list[dict[str, Any]]:
    result = [deepcopy(dict(item)) for item in refs]
    for path in (
        "evidence_refs",
        "frame.source_ref",
        "target.observation_source_ref",
        "target.geometry.corner_code_ref",
        "code",
        "breakpoint_pack",
    ):
        ok, value = _get_path(event, path)
        if not ok:
            continue
        if not include_values:
            candidate = {"path": path, "status": "available"}
        elif isinstance(value, Mapping):
            candidate = {"path": path, "keys": sorted(str(key) for key in value)}
        elif isinstance(value, list):
            candidate = {"path": path, "value": deepcopy(value)}
        else:
            candidate = {"path": path, "value": value}
        result.append(candidate)
    return result


def _event_function_aliases(event: Mapping[str, Any]) -> set[str]:
    """Return explicit event/source function names usable for runtime joins.

    A recorded event is often named after the externally visible feature and
    side (for example ``FCTA_R``), while a GDB observation is named after the
    real source entry function.  The viewer projection already carries that
    entry function under ``details.feature.entry_function``.  Joining those
    explicit names is safe; inventing a feature-to-function naming convention
    here would not be.
    """
    values: set[str] = set()
    for path in (
        "function",
        "identity.function",
        "handler_function",
        "target_function",
        "code_function",
        "details.feature.entry_function",
        "details.feature.handler_function",
        "details.code.entry_function",
        "feature.entry_function",
        "code.entry_function",
    ):
        ok, value = _get_path(event, path)
        if ok and value not in (None, ""):
            values.add(str(value).strip().upper())
    return {value for value in values if value}


def _event_object_ids_for_runtime(event: Mapping[str, Any]) -> set[str]:
    """Collect explicit selected/candidate object ids for join prioritisation."""
    values: set[str] = set()
    paths = (
        "target_obj_id",
        "selected_target.obj_id",
        "selected_target.object_id",
        "target.obj_id",
        "target.object_id",
        "target.selected.obj_id",
        "target.selected.object_id",
        "details.target_obj_id",
        "details.selected_target.obj_id",
        "details.target.selected.obj_id",
    )
    for path in paths:
        ok, value = _get_path(event, path)
        if ok and value not in (None, ""):
            values.add(str(value))
    for path in ("target_candidates", "target.candidates", "details.target_candidates"):
        ok, rows = _get_path(event, path)
        if not ok or not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            value = row.get("obj_id", row.get("object_id", row.get("objID")))
            if value not in (None, ""):
                values.add(str(value))
    return values


def _runtime_row_frame(row: Mapping[str, Any]) -> str:
    identity = row.get("identity") if isinstance(row.get("identity"), Mapping) else {}
    return str(
        row.get("frame_id")
        or identity.get("frame_id")
        or identity.get("frame")
        or identity.get("frame_counter")
        or ""
    )


def _runtime_row_object(row: Mapping[str, Any]) -> str:
    identity = row.get("identity") if isinstance(row.get("identity"), Mapping) else {}
    value = (
        row.get("object_id")
        or identity.get("object_id")
        or identity.get("obj_id")
        or identity.get("objID")
    )
    return str(value) if value not in (None, "") else ""


def _prioritised_runtime_rows(
    rows: list[dict[str, Any]],
    event: Mapping[str, Any],
    *,
    max_items: int,
) -> tuple[list[dict[str, Any]], bool]:
    """Keep same-frame GDB/selected-object/public rows before the long tail."""
    limit = max(1, int(max_items))
    selected_frame = str(_first_frame(event).get("frame_id") or "")
    target_ids = _event_object_ids_for_runtime(event)
    required: list[dict[str, Any]] = []
    optional: list[dict[str, Any]] = []
    for row in rows:
        layer = str(row.get("layer") or "")
        exact_frame = bool(selected_frame and _runtime_row_frame(row) == selected_frame)
        object_match = bool(target_ids and _runtime_row_object(row) in target_ids)
        if exact_frame and (
            layer == "gdb_observation"
            or object_match
            or layer == "runtime_with_frame"
        ):
            required.append(row)
        else:
            optional.append(row)
    selected = required[:limit]
    if len(selected) < limit:
        selected.extend(optional[: limit - len(selected)])
    # If the required slice itself exceeded the limit, keep the GDB rows and
    # selected target first; this is the only case where it is useful to sort
    # within the required set.  All rows retain their original producer order
    # after the priority partition.
    if len(required) > limit:
        selected = sorted(
            required,
            key=lambda row: (
                0 if str(row.get("layer") or "") == "gdb_observation" else 1,
                0 if _runtime_row_object(row) in target_ids else 1,
            ),
        )[:limit]
    return selected, len(rows) > len(selected)


def _runtime_matches(
    runtime: Mapping[str, Any] | None,
    event: Mapping[str, Any],
    *,
    max_items: int,
) -> tuple[list[dict[str, Any]], str]:
    if not isinstance(runtime, Mapping):
        return [], "not_provided"
    event_id = str(event.get("event_id") or "")
    identity = event.get("identity") if isinstance(event.get("identity"), Mapping) else {}
    function_aliases = _event_function_aliases(event)
    function = str(event.get("function") or identity.get("function") or "").upper()
    radar = event.get("radar_id") or identity.get("radar_id")
    frame = _first_frame(event).get("frame_id")
    matches: list[dict[str, Any]] = []
    fallback: list[dict[str, Any]] = []
    for row in runtime.get("observations", []) or []:
        if not isinstance(row, Mapping):
            continue
        row_identity = row.get("identity") if isinstance(row.get("identity"), Mapping) else {}
        row_event = str(row.get("event_id") or row_identity.get("event_id") or "")
        row_function = str(row.get("function") or row_identity.get("function") or "").upper()
        row_radar = row.get("radar_id") or row_identity.get("radar_id")
        row_frame = row.get("frame_id") or row_identity.get("frame_id")
        if event_id and row_event == event_id:
            matches.append(deepcopy(dict(row)))
            continue
        if (
            row_function in function_aliases
            and str(row_radar) == str(radar)
            and frame not in (None, "")
            and str(row_frame) == str(frame)
        ):
            matches.append(deepcopy(dict(row)))
            continue
        if (
            not row_function
            and str(row_radar) == str(radar)
            and frame not in (None, "")
            and str(row_frame) == str(frame)
        ):
            # The observation is at the same explicit frame/radar but its
            # callback scope did not carry a feature name.  It is useful
            # runtime evidence, but the unresolved function attribution must
            # remain visible to the caller.
            matches.append(deepcopy(dict(row)))
            continue
        if row_function in function_aliases and str(row_radar) == str(radar):
            fallback.append(deepcopy(dict(row)))
    if matches:
        selected, truncated = _prioritised_runtime_rows(
            matches,
            event,
            max_items=max_items,
        )
        function_unresolved = any(
            not str(
                (item.get("function") if isinstance(item, Mapping) else "")
                or ((item.get("identity") or {}).get("function") if isinstance(item, Mapping) and isinstance(item.get("identity"), Mapping) else "")
            )
            for item in selected
        )
        status = "exact_frame_radar_function_unresolved" if function_unresolved else "exact_event_or_frame"
        return selected, status + ("_truncated" if truncated else "")
    if fallback:
        selected, truncated = _slice_rows(fallback, max_items=max_items, selected_frame_id=str(frame or ""))
        return selected, "same_function_radar_window" + ("_truncated" if truncated else "")
    return [], "no_matching_observation"


def _compact_code(code: Any) -> tuple[Any, bool]:
    """Keep code refs useful to Pi without copying a multi-megabyte index."""
    if not isinstance(code, Mapping):
        return deepcopy(code), False
    result: dict[str, Any] = {}
    truncated = False
    for key in ("call_chain", "feature_functions", "confidence", "geometry_function"):
        if key in code:
            result[key] = deepcopy(code[key])
    def compact_row(row: Any) -> Any:
        if not isinstance(row, Mapping):
            return deepcopy(row)
        keep = (
            "name", "token", "expression", "variable", "value", "operator", "left", "right",
            "function", "file", "line", "field", "status", "source_ref", "code_ref",
            "dependencies", "formula", "unit", "kind",
        )
        return {key: deepcopy(row[key]) for key in keep if row.get(key) not in (None, "", [])}

    for key in ("parameters", "conditions"):
        value = code.get(key)
        if isinstance(value, list):
            result[key] = [compact_row(row) for row in value[:60]]
            truncated = truncated or len(value) > 60
        elif value is not None:
            result[key] = deepcopy(value)
    groups = code.get("condition_groups")
    if isinstance(groups, Mapping):
        compact_groups: dict[str, Any] = {}
        for index, (name, value) in enumerate(groups.items()):
            if index >= 24:
                truncated = True
                break
            if isinstance(value, list):
                compact_groups[str(name)] = [compact_row(row) for row in value[:12]]
                truncated = truncated or len(value) > 12
            else:
                compact_groups[str(name)] = deepcopy(value)
        result["condition_groups"] = compact_groups
        if len(groups) > 24:
            truncated = True
    for key in ("source_ref", "diagnostics"):
        if key in code:
            result[key] = deepcopy(code[key])
    return result, truncated


def _compact_details(base: Mapping[str, Any], *, max_targets: int = 24) -> dict[str, Any]:
    details: dict[str, Any] = {}
    truncated = False
    for key, value in base.items():
        if key == "code":
            code, code_truncated = _compact_code(value)
            details[key] = code
            truncated = truncated or code_truncated
        elif key == "runtime":
            details[key] = _compact_runtime_projection(value)
        elif key == "timeline":
            details[key] = _compact_timeline(value, max_targets=max_targets)
        elif key in {"frame_evidence", "target_candidates", "target"}:
            details[key] = deepcopy(value)
        else:
            # Event-level scalar/ego/ROI values are small; copy them so the
            # returned query can never mutate the loaded artifact.
            details[key] = deepcopy(value)
    if truncated:
        details["code_evidence_truncated"] = True
    return details


def _compact_timeline(value: Any, *, max_targets: int) -> Any:
    if not isinstance(value, Mapping):
        return deepcopy(value)
    result = {
        key: deepcopy(value[key])
        for key in ("selected_frame_index", "key_frames", "frame_count", "frames_truncated")
        if value.get(key) not in (None, "", [])
    }
    frames = value.get("frames")
    if not isinstance(frames, list):
        return result
    compact_frames: list[dict[str, Any]] = []
    for frame in frames:
        if not isinstance(frame, Mapping):
            compact_frames.append({"value": deepcopy(frame)})
            continue
        item = {
            key: deepcopy(frame[key])
            for key in (
                "frame_id", "frame_id_source", "timestamp_sec", "sequence_index", "topic",
                "decode_ok", "lgu_num", "sgu_num", "source_ref", "ego", "object_count",
                "adas_enables", "calibration", "mileage", "roi_layers",
            )
            if frame.get(key) not in (None, "", [])
        }
        targets = frame.get("targets")
        if isinstance(targets, list):
            item["targets"] = deepcopy(targets[: max(1, int(max_targets))])
            if len(targets) > max_targets:
                item["targets_truncated"] = True
        runtime = frame.get("runtime")
        if isinstance(runtime, Mapping):
            item["runtime"] = {
                key: deepcopy(runtime[key])
                for key in ("status", "observation_count", "association", "diagnostics")
                if runtime.get(key) not in (None, "", [])
            }
        compact_frames.append(item)
    result["frames"] = compact_frames
    return result


def _compact_runtime_projection(value: Any) -> Any:
    if not isinstance(value, Mapping):
        return deepcopy(value)
    result: dict[str, Any] = {}
    for key in ("status", "observation_count", "session_status", "binding_status", "geometry", "disturbance"):
        if value.get(key) not in (None, "", []):
            result[key] = deepcopy(value[key])
    for key in ("diagnostics", "attempts"):
        rows = value.get(key)
        if isinstance(rows, list):
            result[key] = deepcopy(rows[:12])
            if len(rows) > 12:
                result[f"{key}_truncated"] = True
    for key in ("fields", "observations"):
        rows = value.get(key)
        if not isinstance(rows, list):
            continue
        compact_rows: list[Any] = []
        for row in rows[:12]:
            if not isinstance(row, Mapping):
                compact_rows.append(deepcopy(row))
                continue
            item = {
                name: deepcopy(row[name])
                for name in ("observation_id", "layer", "status", "identity", "source", "geometry", "diagnostics")
                if row.get(name) not in (None, "", [])
            }
            field_rows = row.get("fields")
            if isinstance(field_rows, list):
                item["fields"] = deepcopy(field_rows[:80])
                if len(field_rows) > 80:
                    item["fields_truncated"] = True
            compact_rows.append(item)
        result[key] = compact_rows
        if len(rows) > 12:
            result[f"{key}_truncated"] = True
    return result


def _bounded_field_score(value: Any) -> int:
    if not isinstance(value, Mapping):
        return 0
    raw_token = str(value.get("token") or value.get("code_token") or value.get("access_path") or "")
    token = raw_token.lower()
    if not token:
        return 0
    scores = (
        ("objfcta", 120), ("objfctb", 118), ("rightfcta", 116), ("leftfcta", 114),
        ("rightfctb", 112), ("leftfctb", 110), ("finter", 108), ("fint", 106),
        ("fttc", 104), ("fddci", 102), ("distx", 100), ("disty", 100),
        ("velabs", 98), ("velx", 96), ("vely", 96), ("objid", 94), ("frameid", 94),
        ("warning", 92), ("flag", 90), ("roi", 88), ("yaw", 86), ("length", 84),
        ("width", 84), ("brake", 82), ("counter", 80),
    )
    score = max((score for hint, score in scores if hint in token), default=0)
    # A failed/optimized-out observation must not win the one-token-per-family
    # reduction over a numeric observation from the same runtime field family.
    # The full evidence remains available in the source artifact; this only
    # controls which fields survive the bounded Pi/event projection.
    status = str(value.get("status") or "observed").lower()
    if status not in {"observed", "derived"}:
        return max(0, score - 500)
    # Prediction fields are consumed by the scene read model. Prefer an
    # observed numeric local token over a qualified fallback such as
    # ``sObj->fInterX`` or a pointer-formatted ``fInterX`` argument when both
    # are present. The pointer value is a valid GDB observation, but it is not
    # the scalar needed for a plot annotation.
    if raw_token.strip().lower() in {"finterx", "fintery", "fttmy", "fttmx", "fttmxobj"}:
        field_value = value.get("value")
        if isinstance(field_value, (int, float)) and not isinstance(field_value, bool):
            score = max(score, 150)
        elif isinstance(field_value, str) and field_value.strip().lower().startswith(("0x", "inf", "nan")):
            return max(0, score - 500)
    return score


def _bounded_field_family(value: Any) -> str:
    if not isinstance(value, Mapping):
        return ""
    token = str(value.get("token") or value.get("code_token") or value.get("access_path") or "")
    token = token.replace("->", ".")
    return token.rsplit(".", 1)[-1].lower()


def _bound_field_list(value: list[Any], limit: int) -> list[Any]:
    """Keep list head/tail plus high-value tokenized runtime fields."""
    if len(value) <= limit:
        return deepcopy(value)
    head = max(1, limit // 2)
    tail = min(max(0, limit - head), max(0, limit // 8))
    context_indices = list(range(head)) + list(range(max(head, len(value) - tail), len(value)))
    important: list[int] = []
    seen_tokens: set[str] = set()
    for _, index in sorted(
        ((_bounded_field_score(item), index) for index, item in enumerate(value)),
        key=lambda item: (-item[0], item[1]),
    ):
        score = _bounded_field_score(value[index])
        if score <= 0:
            continue
        item = value[index]
        token = _bounded_field_family(item)
        if token in seen_tokens:
            continue
        seen_tokens.add(token)
        important.append(index)
        if len(important) >= max(1, limit * 3 // 4):
            break
    selected_indices: list[int] = []
    # Keep the leading context first (frame/ego/call inputs), then fill the
    # remaining budget with high-value fields from the normalized tail.
    for index in context_indices + important:
        if index not in selected_indices:
            selected_indices.append(index)
        if len(selected_indices) >= limit:
            break
    selected_indices.sort()
    return deepcopy([value[index] for index in selected_indices])


def _bound_query_value(value: Any, *, max_rows: int) -> Any:
    """Bound list-heavy field values returned to Pi, keeping their tokens."""
    if isinstance(value, list):
        limit = max(1, int(max_rows))
        result = deepcopy(value[:limit])
        if len(value) > limit:
            result = _bound_field_list(value, limit)
            return {"items": result, "truncated": True, "total": len(value)}
        return result
    if isinstance(value, Mapping):
        return {
            str(key): _bound_query_value(child, max_rows=max_rows)
            for key, child in value.items()
        }
    return deepcopy(value)


def _project_event(
    event: Mapping[str, Any],
    *,
    viewer_event: Mapping[str, Any] | None,
    fields: Sequence[str],
    max_frames: int,
    max_targets: int,
    refs: Sequence[Mapping[str, Any]],
    runtime: Mapping[str, Any] | None,
    include_details: bool,
    max_field_rows: int,
) -> dict[str, Any]:
    # viewer-model is a presentation projection of the same bundle.  Prefer
    # it when available for the detailed scene, but preserve the bundle event
    # as the provenance source and never silently merge unknown fields.
    base = dict(viewer_event or event)
    first = _first_frame(base)
    selected_frame = str(first.get("frame_id") or "")
    frame_ok, frame_rows = _get_path(base, "timeline.frames")
    frame_path = "timeline.frames"
    if not frame_ok or not isinstance(frame_rows, list):
        frame_ok, frame_rows = _get_path(base, "frame_evidence")
        frame_path = "frame_evidence"
    if frame_ok and isinstance(frame_rows, list):
        sliced, truncated = _slice_rows(
            frame_rows,
            max_items=max_frames,
            selected_frame_id=selected_frame,
        )
        if frame_path == "timeline.frames":
            timeline = dict(base.get("timeline") or {})
            timeline["frames"] = sliced
            timeline["frames_truncated"] = truncated
            base["timeline"] = timeline
        else:
            base["frame_evidence"] = sliced
            base["frame_evidence_truncated"] = truncated

    for path in ("target_candidates", "target.candidates"):
        ok, rows = _get_path(base, path)
        if not ok or not isinstance(rows, list):
            continue
        sliced, truncated = _slice_rows(rows, max_items=max_targets)
        if path == "target_candidates":
            base["target_candidates"] = sliced
            base["target_candidates_truncated"] = truncated
        else:
            target_projection = dict(base.get("target") or {})
            target_projection["candidates"] = sliced
            target_projection["candidates_truncated"] = truncated
            base["target"] = target_projection

    compact_base = _compact_details(base, max_targets=max_targets)

    identity = base.get("identity") if isinstance(base.get("identity"), Mapping) else {}
    function = str(base.get("function") or identity.get("function") or "")
    radar_id = base.get("radar_id") or identity.get("radar_id")
    side_value = identity.get("side") or base.get("side")
    if side_value in (None, "") and function.rsplit("_", 1)[-1].upper() in {"L", "R"}:
        side_value = function.rsplit("_", 1)[-1].upper()
    target = base.get("target") if isinstance(base.get("target"), Mapping) else {}
    selected_target = target.get("selected") if isinstance(target.get("selected"), Mapping) else {}
    facts: list[dict[str, Any]] = []
    requested_fields = _as_text_list(fields)
    effective_fields = requested_fields or list(DEFAULT_FIELDS)
    for path in effective_fields:
        ok, value = _get_path(base, path)
        facts.append({
            "path": path,
            "value": _bound_query_value(value, max_rows=max_field_rows) if ok else None,
            "status": "observed_or_projected" if ok else "not_available",
            "source": "viewer_model" if viewer_event is not None else "diagnosis_bundle",
        })

    runtime_rows, runtime_status = _runtime_matches(runtime, base, max_items=max_frames)
    runtime_rows = [
        _bound_query_value(row, max_rows=max_field_rows)
        for row in runtime_rows
    ]
    return {
        "event_id": base.get("event_id") or event.get("event_id"),
        "summary": {
            "function": function or None,
            "side": side_value,
            "radar_id": radar_id,
            "radar_pos": identity.get("radar_name") or identity.get("radar_pos"),
            "source": base.get("source") or identity.get("source"),
            "alarm": deepcopy(base.get("alarm") or {
                key: base.get(key)
                for key in ("start_time_sec", "end_time_sec", "sample_count", "confidence")
                if base.get(key) not in (None, "")
            }),
            "first_frame": first,
            "target_obj_id": (
                selected_target.get("obj_id")
                or target.get("obj_id")
                or base.get("selected_target", {}).get("obj_id")
                if isinstance(base.get("selected_target"), Mapping)
                else selected_target.get("obj_id") or target.get("obj_id")
            ),
            "target_index": deepcopy(target.get("index_mapping", {})),
        },
        "details": compact_base if include_details else {"event_id": base.get("event_id") or event.get("event_id")},
        "facts": facts,
        "runtime_observations": runtime_rows,
        "runtime_association": runtime_status,
        "source_refs": _source_refs(event, refs, include_values=include_details),
        "provenance": {
            "bundle_event_id": event.get("event_id"),
            "viewer_event_used": viewer_event is not None,
            "selected_frame_id": first.get("frame_id"),
            "selected_frame_definition": first.get("definition"),
        },
    }


def build_evidence_query(
    *,
    bundle: Mapping[str, Any] | None = None,
    bundle_path: str = "",
    viewer_model: Mapping[str, Any] | None = None,
    viewer_model_path: str = "",
    runtime_evidence: Mapping[str, Any] | None = None,
    runtime_evidence_path: str = "",
    event_id: str = "",
    event_index: int | None = None,
    function: str = "",
    side: str = "",
    radar_id: str | int = "",
    frame_id: str | int = "",
    fields: Sequence[str] | str | None = None,
    max_events: int = 20,
    max_frames: int = 24,
    max_targets: int = 24,
    include_details: bool = False,
    max_field_rows: int = 32,
) -> dict[str, Any]:
    """Build a bounded evidence slice from explicit artifacts."""
    requested_fields = _as_text_list(fields)
    effective_fields = requested_fields or list(DEFAULT_FIELDS)
    bundle_obj, bundle_ref, bundle_error = _load_object(bundle, bundle_path, label="bundle")
    viewer_obj, viewer_ref, viewer_error = _load_object(
        viewer_model, viewer_model_path, label="viewer_model"
    )
    runtime_obj, runtime_ref, runtime_error = _load_object(
        runtime_evidence, runtime_evidence_path, label="runtime_evidence"
    )
    if runtime_obj is None and isinstance(bundle_obj, Mapping) and isinstance(bundle_obj.get("runtime_evidence"), Mapping):
        runtime_obj = dict(bundle_obj["runtime_evidence"])
        runtime_ref = {
            "label": "runtime_evidence",
            "source": "embedded_in_bundle",
            "schema_version": runtime_obj.get("schema_version", ""),
        }
    errors = [item for item in (bundle_error, viewer_error, runtime_error) if item]
    if bundle_obj is None and viewer_obj is None:
        errors.append("bundle_or_viewer_model_required")
    if errors:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "blocked",
            "query": {},
            "events": [],
            "input_refs": [item for item in (bundle_ref, viewer_ref, runtime_ref) if item],
            "artifact_refs": [item for item in (bundle_ref, viewer_ref, runtime_ref) if item],
            "diagnostics": list(dict.fromkeys(errors)),
        }

    bundle_events = [
        item for item in _as_list(bundle_obj.get("alarm_events") if bundle_obj else [])
        if isinstance(item, Mapping)
    ]
    viewer_events = [
        item for item in _as_list(viewer_obj.get("events") if viewer_obj else [])
        if isinstance(item, Mapping)
    ]
    viewer_by_id = {
        str(item.get("event_id")): item
        for item in viewer_events
        if item.get("event_id") not in (None, "")
    }
    source_events = bundle_events or viewer_events
    filtered_events = [
        item
        for item in source_events
        if _event_matches(
            viewer_by_id.get(str(item.get("event_id"))) or item,
            event_id=str(event_id or "").strip(),
            function=str(function or "").strip(),
            side=str(side or "").strip(),
            radar_id=str(radar_id or "").strip(),
            frame_id=str(frame_id or "").strip(),
        )
    ]
    if event_index is not None:
        index = int(event_index)
        selected_events = [filtered_events[index]] if 0 <= index < len(filtered_events) else []
    else:
        selected_events = filtered_events
    selected_events, events_truncated = _slice_rows(
        selected_events,
        max_items=max_events,
    )
    refs = [item for item in (bundle_ref, viewer_ref, runtime_ref) if item]
    projected = [
        _project_event(
            event,
            viewer_event=viewer_by_id.get(str(event.get("event_id"))),
            fields=requested_fields,
            max_frames=max_frames,
            max_targets=max_targets,
            refs=refs,
            runtime=runtime_obj,
            include_details=bool(include_details),
            max_field_rows=max_field_rows,
        )
        for event in selected_events
    ]
    diagnostics: list[str] = []
    if not projected:
        diagnostics.append("no_event_matches_query")
    if events_truncated:
        diagnostics.append("event_results_truncated")
    if viewer_obj is None:
        diagnostics.append("viewer_model_not_supplied_bundle_projection_used")
    if runtime_obj is None:
        diagnostics.append("runtime_evidence_not_supplied")
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "ready" if projected else "not_found",
        "query": {
            "event_id": str(event_id or ""),
            "event_index": event_index,
            "function": str(function or ""),
            "side": str(side or ""),
            "radar_id": radar_id,
            "frame_id": frame_id,
            "fields": requested_fields,
            "effective_fields": effective_fields,
            "max_events": int(max_events),
            "max_frames": int(max_frames),
            "max_targets": int(max_targets),
            "include_details": bool(include_details),
            "max_field_rows": int(max_field_rows),
        },
        "case": deepcopy((bundle_obj or viewer_obj or {}).get("case", {})),
        "provenance": {
            "bundle": bundle_ref or {},
            "viewer_model": viewer_ref or {},
            "runtime_evidence": runtime_ref or {},
            "bundle_schema_version": (bundle_obj or {}).get("schema_version", ""),
            "viewer_schema_version": (viewer_obj or {}).get("schema_version", ""),
            "runtime_schema_version": (runtime_obj or {}).get("schema_version", ""),
        },
        "matched_event_count": len(projected),
        "events": projected,
        "artifact_refs": refs,
        "diagnostics": list(dict.fromkeys(diagnostics)),
    }


__all__ = ["EvidenceQueryError", "SCHEMA_VERSION", "build_evidence_query"]
