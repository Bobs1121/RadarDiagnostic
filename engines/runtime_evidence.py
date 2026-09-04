# -*- coding: utf-8 -*-
"""Deterministic runtime-evidence normalisation and bundle binding.

This engine is the boundary between a runtime producer (headless GDB, a
public ROS-with-frame trace, or a future runtime bridge) and its consumers
(the HTML projection and Pi).  It deliberately does not know any ADAS
feature.  A producer supplies the source/binary/data binding and, when it
uses text markers, may supply a marker-field map whose values are real source
tokens.

The engine never replaces a static bag fact.  ``merge_runtime_evidence``
creates a derived bundle with a separate ``runtime_evidence`` section and
annotates only the matched event references.  A source/data identity conflict
therefore prevents a runtime observation from being presented as belonging to
the static event.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re
import shlex
from pathlib import Path
from typing import Any, Iterable, Mapping

from .gdb_service import parse_gdb_transcript


SCHEMA_VERSION = "runtime-case-evidence.v1"
GDB_SESSION_SCHEMA_VERSION = "gdb-session.v1"

_FIELD_STATUSES = {
    "observed",
    "derived",
    "not_available",
    "optimized_out",
    "not_found",
    "conflict",
}
_MARKER_RE = re.compile(
    r"^(?P<marker>[A-Z][A-Z0-9_]*)\s+(?P<body>.*?\b[A-Za-z_][A-Za-z0-9_]*=.+)$"
)
_SOURCE_LOCATION_RE = re.compile(r"(?:at\s+)?(?P<file>[^\s:]+):(?P<line>\d+)")
_PATH_KEYS = ("bag", "bag_path", "data_path", "path")
_RUNNER_METRIC_RE = re.compile(r"^(?P<key>[A-Z][A-Z0-9_]*)=(?P<value>.*)$")


def _json_file(path_text: str, *, label: str) -> dict[str, Any]:
    path = Path(path_text).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"{label}_not_found:{path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label}_invalid:{type(exc).__name__}:{path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label}_must_be_object:{path}")
    return value


def load_runtime_input(
    value: Mapping[str, Any] | None = None,
    path_text: str = "",
    *,
    label: str,
) -> dict[str, Any] | None:
    """Load one JSON artifact without accepting an ambiguous second source."""
    if value is not None:
        if not isinstance(value, Mapping):
            raise ValueError(f"{label}_must_be_object")
        return deepcopy(dict(value))
    if str(path_text or "").strip():
        return _json_file(str(path_text), label=label)
    return None


def _normalise_path(value: Any) -> str:
    return str(value or "").strip().replace("\\", "/").rstrip("/").lower()


def _basename(value: Any) -> str:
    return _normalise_path(value).rsplit("/", 1)[-1]


def _sha256_text(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8", errors="replace")).hexdigest()


def _parse_scalar(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return ""
    if text.lower() in {"true", "false"}:
        return text.lower() == "true"
    if text.lower() in {"null", "none"}:
        return None
    # GDB prints small integer fields as ``4 '\\004'`` (and sometimes
    # ``2 '\\002'``).  Keep the numeric value while the raw GDB text remains
    # available in the field/source record.
    gdb_numeric = re.fullmatch(r"([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)\s+['\"].*['\"]", text)
    if gdb_numeric:
        return _parse_scalar(gdb_numeric.group(1))
    if re.fullmatch(r"[-+]?\d+", text):
        try:
            return int(text)
        except ValueError:
            pass
    if re.fullmatch(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?", text):
        try:
            return float(text)
        except ValueError:
            pass
    return text


def _parse_runner_metrics(text: str) -> dict[str, Any]:
    """Read summary metrics emitted by the isolated runner, if present."""
    result: dict[str, Any] = {}
    for raw in str(text or "").splitlines():
        match = _RUNNER_METRIC_RE.match(raw.strip())
        if not match:
            continue
        result[match.group("key").lower()] = _parse_scalar(match.group("value"))
    return result


def _disturbance_from_transcript(text: str, parsed: Mapping[str, Any]) -> dict[str, Any]:
    metrics = _parse_runner_metrics(text)
    diagnostics = list(parsed.get("diagnostics", []) or []) if isinstance(parsed, Mapping) else []
    combined = str(text or "")
    # ``No symbol`` is common when a source condition contains a macro, an
    # enum, or a local that is outside the current stop frame.  It is an
    # evidence gap, not proof that attaching/continuing perturbed replay.  A
    # disturbance claim needs a process/ptrace/memory/runner failure signal.
    strong_runtime_error = any(
        marker in combined
        for marker in (
            "Cannot access memory",
            "Can't attach",
            "Could not attach",
            "Cannot attach",
            "ptrace:",
            "Operation not permitted",
            "No frame",
            "No stack",
            "Error in sourced command file",
            "not in executable format",
            "no core file handler",
        )
    )
    error_present = (
        "gdb_command_error_present" in diagnostics
        or "gdb_expression_not_observed" in diagnostics
    )
    if strong_runtime_error:
        status = "suspected"
        reason = "GDB transcript contains command/expression errors; replay output may be perturbed."
    elif metrics.get("play_rc") not in (None, 0):
        status = "confirmed"
        reason = "rosbag play returned a non-zero code."
    elif error_present:
        status = "not_evaluated"
        reason = "Some GDB expressions were unavailable at a stop; replay disturbance was not established."
    else:
        status = "not_evaluated"
        reason = "No replay-vs-baseline comparison was supplied."
    return {
        "status": status,
        "reason": reason,
        "metrics": metrics,
        "source": "isolated_runner_summary" if metrics else "gdb_transcript",
        "diagnostics": diagnostics,
    }


def _parse_key_values(body: str) -> dict[str, Any]:
    """Parse shell-like ``key=value`` marker tokens.

    GDB ``printf`` markers are intentionally simple and may quote a value.
    Unknown keys are retained; this is important for code revisions that add
    a runtime field before the harness itself is upgraded.
    """
    try:
        tokens = shlex.split(str(body or ""), posix=True)
    except ValueError:
        tokens = str(body or "").split()
    result: dict[str, Any] = {}
    for token in tokens:
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        key = key.strip()
        if key:
            result[key] = _parse_scalar(value)
    return result


def parse_runtime_markers(text: str) -> list[dict[str, Any]]:
    """Return feature-neutral machine markers found in a GDB transcript.

    The parser recognises both the explicit ``CR60_RUNTIME`` contract and
    legacy uppercase ``KEY=value`` lines emitted by an experiment adapter.
    It does not interpret a marker as a source variable; the optional
    ``marker_field_map`` in :func:`normalize_runtime_evidence` supplies that
    mapping.
    """
    markers: list[dict[str, Any]] = []
    for line_number, raw in enumerate(str(text or "").splitlines(), start=1):
        line = raw.strip()
        match = _MARKER_RE.match(line)
        if not match:
            continue
        marker = match.group("marker")
        fields = _parse_key_values(match.group("body"))
        if not fields:
            continue
        markers.append({"marker": marker, "fields": fields, "raw": line, "line": line_number})
    return markers


def _int(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _identity_from_values(
    values: Mapping[str, Any],
    *,
    binding: Mapping[str, Any] | None = None,
    run: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a non-guessing observation identity from explicit aliases."""
    source = {}
    source.update(dict(run or {}))
    source.update(dict(binding or {}))

    def first(*keys: str) -> Any:
        for key in keys:
            if key in values and values.get(key) not in (None, ""):
                return values.get(key)
            if key in source and source.get(key) not in (None, ""):
                return source.get(key)
        return None

    identity: dict[str, Any] = {
        "event_id": first("event_id"),
        "data_fingerprint": first("data_fingerprint"),
        "radar_id": _int(first("radar_id", "radar")),
        "radar_pos": first("radar_pos"),
        "frame_id": _int(first("frame_id", "frame", "frame_counter", "target_frame")),
        "frame_source": str(first("frame_source", "frame_id_source") or "").strip(),
        "object_id": first("object_id", "obj_id", "objID"),
        "algorithm_index": _int(first("algorithm_index", "algorithm_object_index", "i")),
        "raw_input_index": _int(first("raw_input_index", "raw_sgu_index")),
        "objectlist_index": _int(first("objectlist_index")),
        "function": first("function", "function_name"),
    }
    if identity["object_id"] is not None:
        try:
            identity["object_id"] = int(identity["object_id"])
        except (TypeError, ValueError):
            identity["object_id"] = str(identity["object_id"])
    location = first("source_location")
    if isinstance(location, Mapping):
        identity["source_location"] = deepcopy(dict(location))
    else:
        file_path = first("source_file", "file")
        line = _int(first("source_line", "line"))
        if file_path or line is not None:
            identity["source_location"] = {"file": file_path or "", "line": line}
    return {key: value for key, value in identity.items() if value not in (None, "")}


def _field(
    token: Any,
    value: Any,
    *,
    status: str = "observed",
    phase: str = "unknown",
    scope: str = "",
    source: Mapping[str, Any] | None = None,
    code_ref: Mapping[str, Any] | None = None,
    raw: str = "",
) -> dict[str, Any]:
    normalized_status = status if status in _FIELD_STATUSES else "observed"
    normalized_phase = phase if phase in {"before", "during", "after", "unknown"} else "unknown"
    return {
        "token": str(token or "unknown"),
        "value": _parse_scalar(value),
        "status": normalized_status,
        "phase": normalized_phase,
        "scope": str(scope or ""),
        "source": deepcopy(dict(source or {})),
        "code_ref": deepcopy(dict(code_ref or {})),
        "raw": str(raw or ""),
    }


def _source_location_from_backtrace(backtrace: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    for row in backtrace:
        text = str(row.get("frame", ""))
        match = _SOURCE_LOCATION_RE.search(text)
        if match:
            return {"file": match.group("file"), "line": int(match.group("line"))}
    return {}


def _generic_observation(
    *,
    parsed: Mapping[str, Any],
    identity: Mapping[str, Any],
    run: Mapping[str, Any],
    source: Mapping[str, Any],
) -> dict[str, Any]:
    fields: list[dict[str, Any]] = []
    for row in parsed.get("expressions", []) or []:
        if isinstance(row, Mapping):
            fields.append(
                _field(
                    row.get("expression"),
                    row.get("value"),
                    status=str(row.get("status", "observed")),
                    source={**dict(source), "kind": "gdb_expression"},
                    raw=str(row.get("raw", "")),
                )
            )
    for section in ("args", "locals"):
        for row in parsed.get(section, []) or []:
            if isinstance(row, Mapping):
                fields.append(
                    _field(
                        row.get("name"),
                        row.get("value"),
                        status=str(row.get("status", "observed")),
                        scope=section,
                        source={**dict(source), "kind": f"gdb_{section}"},
                        raw=str(row.get("raw", "")),
                    )
                )
    location = dict(identity.get("source_location") or {})
    if not location:
        location = _source_location_from_backtrace(parsed.get("backtrace", []) or [])
    normalized_identity = dict(identity)
    if location:
        normalized_identity["source_location"] = location
    observation: dict[str, Any] = {
        "observation_id": f"gdb:{run.get('run_id', 'unbound')}:transcript",
        "layer": "gdb_observation",
        "identity": normalized_identity,
        "fields": fields,
        "call_chain": [deepcopy(dict(item)) for item in parsed.get("backtrace", []) or [] if isinstance(item, Mapping)],
        "diagnostics": list(parsed.get("diagnostics", []) or []),
    }
    if parsed.get("stops"):
        observation["stops"] = list(parsed.get("stops", []) or [])
    return observation


def _flatten_public_value(value: Any, prefix: str = "") -> list[tuple[str, Any]]:
    if isinstance(value, Mapping):
        rows: list[tuple[str, Any]] = []
        for key, child in value.items():
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            rows.extend(_flatten_public_value(child, child_prefix))
        return rows
    if isinstance(value, (list, tuple)):
        rows = []
        for index, child in enumerate(value):
            rows.extend(_flatten_public_value(child, f"{prefix}[{index}]"))
        return rows
    return [(prefix, value)]


def _public_snapshot_context(
    snapshot: Mapping[str, Any],
    session: Mapping[str, Any] | None,
) -> dict[str, Any]:
    context = snapshot.get("source_context", {})
    result = dict(context) if isinstance(context, Mapping) else {}
    target = session.get("target", {}) if isinstance(session, Mapping) else {}
    if isinstance(target, Mapping):
        for source_key, target_key in (
            ("host", "server"),
            ("remote_bag_path", "bag"),
            ("ros_master_uri", "ros_master_uri"),
        ):
            if target_key not in result and target.get(source_key) not in (None, ""):
                result[target_key] = target[source_key]
    return result


def _public_run_data(
    snapshot: Mapping[str, Any],
    *,
    run: Mapping[str, Any] | None,
    binding: Mapping[str, Any] | None,
    session: Mapping[str, Any] | None,
    snapshot_hash: str,
) -> dict[str, Any]:
    context = _public_snapshot_context(snapshot, session)
    result = dict(run or {})
    aliases = {
        "server": ("server", "remote_host", "host"),
        "workspace": ("workspace", "arbe_root", "remote_workspace"),
        "bag": ("bag", "bag_path", "remote_bag_path", "data_path"),
        "source_context_id": ("source_context_id",),
        "source_snapshot_hash": ("source_snapshot_hash", "snapshot_hash"),
        "project_id": ("project_id",),
        "variant_id": ("variant_id",),
        "coem": ("coem",),
        "vehicle": ("vehicle",),
        "radar_id": ("radar_id", "radar"),
    }
    sources = [dict(binding or {}), context]
    for target_key, candidates in aliases.items():
        if result.get(target_key) not in (None, ""):
            continue
        for source in sources:
            for key in candidates:
                if source.get(key) not in (None, ""):
                    result[target_key] = deepcopy(source[key])
                    break
            if result.get(target_key) not in (None, ""):
                break
    result.setdefault("run_id", f"public-runtime:{snapshot_hash[:16]}")
    if not result.get("data_fingerprint") and result.get("bag"):
        result["data_fingerprint"] = "bag-path:" + _normalise_path(result["bag"])
    result.setdefault(
        "source_context_id",
        str(result.get("source_snapshot_hash") or f"public-runtime:{snapshot_hash[:16]}"),
    )
    result.setdefault("data_fingerprint", "")
    return result


def normalize_public_runtime_evidence(
    snapshot: Mapping[str, Any],
    *,
    run: Mapping[str, Any] | None = None,
    binding: Mapping[str, Any] | None = None,
    warning_names: list[str] | None = None,
    artifacts: Mapping[str, Any] | None = None,
    session: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Project a public runtime snapshot into the canonical evidence overlay."""
    if not isinstance(snapshot, Mapping):
        raise ValueError("public_runtime_snapshot_must_be_object")
    snapshot_hash = _sha256_text(
        json.dumps(snapshot, ensure_ascii=False, sort_keys=True, default=str)
    )
    run_data = _public_run_data(
        snapshot,
        run=run,
        binding=binding,
        session=session,
        snapshot_hash=snapshot_hash,
    )
    names = list(warning_names or snapshot.get("warning_names", []) or [])
    diagnostics = [str(item) for item in snapshot.get("diagnostics", []) or []]
    snapshots = [
        item for item in snapshot.get("snapshots", []) or []
        if isinstance(item, Mapping)
    ]
    unbound_objects = [
        item for item in snapshot.get("unbound_objects", []) or []
        if isinstance(item, Mapping)
    ]
    ignored_objects = [
        item for item in snapshot.get("ignored_objects", []) or []
        if isinstance(item, Mapping)
    ]
    observations: list[dict[str, Any]] = []
    layer_states: dict[str, str] = {}

    def source_for(row: Mapping[str, Any], kind: str) -> dict[str, Any]:
        return {
            "kind": kind,
            "topic": row.get("topic", ""),
            "record_time": row.get("record_time"),
            "message_seq": row.get("message_seq"),
            "header_stamp": row.get("header_stamp"),
        }

    def append_public_observation(
        *,
        observation_id: str,
        layer: str,
        identity: Mapping[str, Any],
        fields: list[dict[str, Any]],
        source: Mapping[str, Any],
        diagnostics_for_observation: list[str] | None = None,
    ) -> None:
        if not fields and not diagnostics_for_observation:
            return
        observations.append({
            "observation_id": observation_id,
            "layer": layer,
            "identity": dict(identity),
            "fields": fields,
            "diagnostics": list(diagnostics_for_observation or []),
            "source": dict(source),
        })
        existing = layer_states.get(layer)
        if existing is None:
            layer_states[layer] = "observed" if layer == "runtime_with_frame" else "derived"

    for snapshot_row in snapshots:
        radar_id = snapshot_row.get("radar_id")
        frame_id = snapshot_row.get("frame_id")
        identity = {
            "data_fingerprint": run_data.get("data_fingerprint", ""),
            "radar_id": _int(radar_id),
            "frame_id": _int(frame_id),
            "frame_source": "warning_status_with_frame/radar_info",
        }
        fields: list[dict[str, Any]] = []
        warning = snapshot_row.get("warning")
        if isinstance(warning, Mapping):
            data = list(warning.get("data", []) or [])
            bits = list(warning.get("warnings", []) or [])
            source_name = str(warning.get("source") or "warning_status")
            offset = 2 if "with_frame" in source_name.lower() else 1
            for index, value in enumerate(bits):
                signal_name = names[index] if index < len(names) else f"w{index + 1}"
                fields.append(_field(
                    f"{source_name}.data[{index + offset}]",
                    value,
                    source={**source_for(warning, "ros_public_warning"), "signal_name": signal_name},
                    scope=signal_name,
                ))
            if not bits:
                for index, value in enumerate(data[offset:]):
                    fields.append(_field(
                        f"{source_name}.data[{index + offset}]",
                        value,
                        source=source_for(warning, "ros_public_warning"),
                    ))
            layer_states["runtime_with_frame"] = "observed"
        radar_info = snapshot_row.get("radar_info")
        if isinstance(radar_info, Mapping):
            aliases = {
                1: "ego_speed",
                2: "yaw_rate",
                3: "detections_number",
                4: "frame_id",
                5: "cycle_time_ms",
                6: "bld_warning_flag",
                7: "bld_percent",
                8: "mileage",
            }
            for index, value in enumerate(list(radar_info.get("data", []) or [])):
                fields.append(_field(
                    f"radar_info.data[{index}]",
                    value,
                    source={**source_for(radar_info, "ros_public_radar_info"),
                            "field_name": aliases.get(index, "")},
                    scope=aliases.get(index, ""),
                ))
            layer_states["runtime_with_frame"] = "observed"
        append_public_observation(
            observation_id=f"public:{run_data['run_id']}:{radar_id}:{frame_id}:frame",
            layer="runtime_with_frame",
            identity=identity,
            fields=fields,
            source={"kind": "arbe_public_runtime_snapshot", "snapshot_sha256": snapshot_hash},
        )
        for object_record in snapshot_row.get("objects", []) or []:
            if not isinstance(object_record, Mapping):
                continue
            object_fields = object_record.get("fields", {})
            if not isinstance(object_fields, Mapping):
                continue
            object_index = _int(object_record.get("object_index"))
            object_id = object_fields.get("objID", object_fields.get("object_id"))
            association = str(object_record.get("association_status") or "unbound")
            object_layer = (
                "runtime_with_frame"
                if association in {"frame_verified", "callback_correlated"}
                else "objectlist_candidate"
            )
            object_identity = {
                **identity,
                "frame_source": (
                    "object_message_frame" if association == "frame_verified"
                    else "callback" if association == "callback_correlated"
                    else "publication_order_derived" if association == "publication_correlated"
                    else "not_available"
                ),
                "object_id": object_id,
                "objectlist_index": object_index,
            }
            object_fields_out: list[dict[str, Any]] = []
            ignored_keys = {
                "topic", "record_time", "message_seq", "object_message_seq",
                "header_stamp", "radar_id", "object_index", "association_evidence",
            }
            for path, value in _flatten_public_value(object_fields):
                root = path.split(".", 1)[0].split("[", 1)[0]
                if root in ignored_keys:
                    continue
                index_text = str(object_index) if object_index is not None else "?"
                object_fields_out.append(_field(
                    f"wfObjectMsg.ObjectsBuffer[{index_text}].{path}",
                    value,
                    status="observed",
                    source={
                        "kind": "ros_public_objectlist",
                        "topic": object_fields.get("topic", ""),
                        "association_status": association,
                        "object_message_seq": object_fields.get("object_message_seq"),
                    },
                ))
            append_public_observation(
                observation_id=(
                    f"public:{run_data['run_id']}:{radar_id}:{frame_id}:"
                    f"object:{object_index}:{object_id}"
                ),
                layer=object_layer,
                identity=object_identity,
                fields=object_fields_out,
                source={"kind": "arbe_public_objectlist", "snapshot_sha256": snapshot_hash},
                diagnostics_for_observation=(
                    ["object_frame_is_derived_from_publication_order"]
                    if association == "publication_correlated" else []
                ),
            )

    for object_record in unbound_objects:
        object_fields = object_record.get("fields", {})
        if not isinstance(object_fields, Mapping):
            continue
        radar_id = object_record.get("radar_id")
        object_id = object_fields.get("objID", object_fields.get("object_id"))
        object_index = _int(object_record.get("object_index"))
        fields: list[dict[str, Any]] = []
        for path, value in _flatten_public_value(object_fields):
            root = path.split(".", 1)[0].split("[", 1)[0]
            if root in {"topic", "record_time", "message_seq", "object_message_seq",
                        "header_stamp", "radar_id", "object_index", "association_evidence"}:
                continue
            index_text = str(object_index) if object_index is not None else "?"
            fields.append(_field(
                f"wfObjectMsg.ObjectsBuffer[{index_text}].{path}",
                value,
                source={"kind": "ros_public_objectlist", "association_status": "unbound"},
            ))
        append_public_observation(
            observation_id=f"public:{run_data['run_id']}:{radar_id}:unbound:object:{object_index}:{object_id}",
            layer="objectlist_candidate",
            identity={
                "data_fingerprint": run_data.get("data_fingerprint", ""),
                "radar_id": _int(radar_id),
                "object_id": object_id,
                "objectlist_index": object_index,
                "frame_source": "not_available",
            },
            fields=fields,
            source={"kind": "arbe_public_unbound_objectlist", "snapshot_sha256": snapshot_hash},
            diagnostics_for_observation=["object_frame_not_available"],
        )
    if unbound_objects:
        diagnostics.append("public_objectlist_unbound")
    if ignored_objects:
        diagnostics.append(f"public_objectlist_ignored_objects:{len(ignored_objects)}")
    if any(item == "objectlist_candidate" for item in layer_states):
        if unbound_objects:
            layer_states["objectlist_candidate"] = "partial"
        else:
            layer_states["objectlist_candidate"] = "derived"
    if not observations:
        status = "blocked"
        diagnostics.append("public_runtime_snapshot_has_no_observations")
    elif str(snapshot.get("status", "")) == "blocked":
        status = "blocked"
    elif unbound_objects or str(snapshot.get("status", "")) == "partial":
        status = "partial"
    else:
        status = "ready"
    evidence_layers = [
        {
            "id": layer_id,
            "kind": layer_id,
            "authority": "arbe_public_runtime",
            "status": layer_status,
            "source": {"snapshot_sha256": snapshot_hash},
            "diagnostics": [],
        }
        for layer_id, layer_status in sorted(layer_states.items())
    ]
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "run": run_data,
        "producer": {
            "kind": "arbe_public_runtime",
            "input_schema": str(snapshot.get("schema_version", "runtime-snapshot-with-frame.v1")),
            "normalizer": "radarAnalyze.engines.runtime_evidence",
        },
        "normalization": {
            "marker_count": 0,
            "commands": [],
            "snapshot_sha256": snapshot_hash,
        },
        "evidence_layers": evidence_layers,
        "observations": observations,
        "attempts": [],
        "warmup": {},
        "comparisons": [],
        "diagnostics": list(dict.fromkeys(diagnostics)),
        "disturbance": {
            "status": "not_evaluated",
            "reason": "No replay-vs-baseline comparison was supplied.",
            "metrics": {},
            "source": "public_runtime_snapshot",
            "diagnostics": [],
        },
        "artifacts": {
            **{
                str(key): str(value)
                for key, value in (artifacts or {}).items()
                if value not in (None, "")
            },
            "public_runtime_snapshot_sha256": snapshot_hash,
        },
    }
    if isinstance(session, Mapping):
        result["artifacts"].setdefault(
            "public_replay_session_schema", str(session.get("schema_version", ""))
        )
    return result


def _marker_identity_fields() -> set[str]:
    return {
        "observation_id", "event_id", "data_fingerprint", "radar_id", "radar_pos", "radar",
        "frame_id", "frame_source", "frame", "frame_counter", "target_frame", "object_id",
        "obj_id", "objID", "algorithm_index", "algorithm_object_index", "raw_input_index",
        "raw_sgu_index", "objectlist_index", "function", "function_name", "source_file",
        "source_line", "file", "line", "phase", "scope", "status", "token", "field_token",
        "value", "field_value", "layer", "marker",
    }


def _marker_observations(
    markers: list[Mapping[str, Any]],
    *,
    run: Mapping[str, Any],
    binding: Mapping[str, Any],
    marker_field_map: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    known_identity = _marker_identity_fields()
    field_map = marker_field_map if isinstance(marker_field_map, Mapping) else {}
    for marker_row in markers:
        marker = str(marker_row.get("marker", ""))
        values = dict(marker_row.get("fields", {}) or {})
        if not marker:
            continue
        # ``CR60_GDB_EXPR`` is an instrumentation line consumed by
        # parse_gdb_transcript; treating every expression marker as a separate
        # runtime observation would create a frame-less duplicate observation.
        if marker in {"CR60_GDB_EXPR", "CR60_GDB_ERROR"}:
            continue
        observation_id = str(
            values.get("observation_id")
            or f"gdb-marker:{marker.lower()}:{values.get('radar_id', values.get('radar', ''))}:{values.get('frame_id', values.get('frame', values.get('frame_counter', '')))}:{values.get('object_id', values.get('objID', ''))}"
        )
        item = grouped.setdefault(
            observation_id,
            {
                "observation_id": observation_id,
                "layer": str(values.get("layer") or "gdb_observation"),
                "identity": _identity_from_values(values, binding=binding, run=run),
                "fields": [],
                "call_chain": [],
                "diagnostics": [],
                "markers": [],
            },
        )
        item["identity"].update(_identity_from_values(values, binding=binding, run=run))
        item["markers"].append({"marker": marker, "raw": marker_row.get("raw", ""), "line": marker_row.get("line")})

        token = values.get("field_token", values.get("token"))
        field_value = values.get("field_value", values.get("value"))
        if token is not None:
            item["fields"].append(
                _field(
                    token,
                    field_value,
                    status=str(values.get("status", "observed")),
                    phase=str(values.get("phase", "unknown")),
                    scope=str(values.get("scope", "")),
                    source={"kind": "gdb_marker", "marker": marker, "line": marker_row.get("line")},
                    raw=str(marker_row.get("raw", "")),
                )
            )
            continue

        mapping = field_map.get(marker, {}) if isinstance(field_map, Mapping) else {}
        if not isinstance(mapping, Mapping):
            mapping = {}
        for key, value in values.items():
            if key in known_identity or key in mapping and mapping.get(key) in (None, ""):
                continue
            source_token = mapping.get(key, key)
            item["fields"].append(
                _field(
                    source_token,
                    value,
                    status=str(values.get(f"{key}_status", "observed")),
                    phase=str(values.get("phase", "unknown")),
                    scope=str(values.get("scope", "")),
                    source={"kind": "gdb_marker", "marker": marker, "line": marker_row.get("line")},
                    raw=str(marker_row.get("raw", "")),
                )
            )
    return list(grouped.values())


def _append_observed_field(
    observation: dict[str, Any],
    token: str,
    value: Any,
    *,
    phase: str = "unknown",
    scope: str = "",
    source: Mapping[str, Any] | None = None,
) -> None:
    if value in (None, "") or not str(token or ""):
        return
    fields = observation.setdefault("fields", [])
    if any(isinstance(item, Mapping) and str(item.get("token", "")) == token for item in fields):
        return
    fields.append(
        _field(
            token,
            value,
            status="observed",
            phase=phase,
            scope=scope,
            source=source,
        )
    )


def _enrich_canonical_replay_details(payload: dict[str, Any]) -> None:
    """Lift an older detailed replay section into the stable observations.

    The first runtime experiment stored rich values under
    ``runtime_replay_layer.runs`` while the canonical observations only held
    the identity and a few handler fields.  Keeping this compatibility step
    here makes old producer artifacts usable by the new HTML/Pi consumers and
    does not invent values when a detail is absent.
    """
    replay = payload.get("runtime_replay_layer", {}) or {}
    runs = replay.get("runs", []) if isinstance(replay, Mapping) else []
    if not isinstance(runs, list):
        return
    observations = payload.get("observations", []) or []
    if not isinstance(observations, list):
        return

    for observation in observations:
        if not isinstance(observation, dict):
            continue
        if observation.get("layer") != "gdb_observation":
            continue
        identity = observation.get("identity", {}) or {}
        if not isinstance(identity, Mapping):
            continue
        radar_id = _int(identity.get("radar_id"))
        frame_id = _int(identity.get("frame_id"))
        object_id = identity.get("object_id")
        candidates = []
        for run in runs:
            if not isinstance(run, Mapping):
                continue
            if radar_id is not None and _int(run.get("radar_id")) != radar_id:
                continue
            run_frame = _int(run.get("target_frame"))
            if frame_id is not None and run_frame is not None and frame_id != run_frame:
                continue
            handler = run.get("handler_observation", {}) or {}
            run_object = handler.get("objID", handler.get("object_id")) if isinstance(handler, Mapping) else None
            if object_id not in (None, "") and run_object not in (None, "") and str(object_id) != str(run_object):
                continue
            candidates.append(run)
        if not candidates:
            continue
        run = candidates[0]
        source = {"kind": "gdb_replay_detail", "run_id": run.get("run_id", "")}
        entry = run.get("front_cross_traffic_entry", {}) or {}
        if isinstance(entry, Mapping):
            for key, token in {
                "frame_counter": "frame_counter",
                "arg_radar_id": "arg_radar_id",
                "carSpd": "g_egoCarAddInfo.carSpd",
                "actual_gear": "g_egoCarAddInfo.actual_gear",
                "bFctaDetectFlg": "bFctaDetectFlg",
                "bFctbDetectFlg": "bFctbDetectFlg",
                "radius": "curvature_radius",
                "objInfo_trcNum": "objInfo->trcNum",
            }.items():
                _append_observed_field(observation, token, entry.get(key), phase="during", scope="FrontCrossTrafficAlertAndBrake", source=source)
            warning_before = entry.get("adasWarning_before_function", {})
            if isinstance(warning_before, Mapping):
                for key, value in warning_before.items():
                    _append_observed_field(observation, f"adasWarning->{key}", value, phase="before", scope="FrontCrossTrafficAlertAndBrake", source=source)
        handler = run.get("handler_observation", {}) or {}
        if not isinstance(handler, Mapping):
            handler = {}
        if isinstance(handler, Mapping):
            handler_function = str(handler.get("function", ""))
            handler_scope = handler_function or "handler"
            for key, token in {
                "i": "i",
                "objID": "sObj->objID",
                "fTTC": "sObj->fTTC",
                "fDDCI": "sObj->fDDCI",
                "objFctaWarningFlag_snapshot": "sObj->objFctaWarningFlag",
                "objFctbWarningFlag_snapshot": "sObj->objFctbWarningFlag",
                "objFctaWarningFlag_array_after_condition": "objInfo->trcOutData[i].objFctaWarningFlag",
                "objFctbWarningFlag_array_after_condition": "objInfo->trcOutData[i].objFctbWarningFlag",
                "leftFctaFlag": "objInfo->trcOutData[i].leftFctaFlag",
                "rightFctaFlag": "objInfo->trcOutData[i].rightFctaFlag",
                "leftFctbFlag": "objInfo->trcOutData[i].leftFctbFlag",
                "rightFctbFlag": "objInfo->trcOutData[i].rightFctbFlag",
                "target_length": "sObj->length",
                "target_width": "sObj->width",
                "target_yawAng": "sObj->yawAng",
                "fIntAng": "sObj->fIntAng",
                "fInterX": "sObj->fInterX",
                "fInterY": "sObj->fInterY",
            }.items():
                _append_observed_field(observation, token, handler.get(key), phase="during", scope=handler_scope, source=source)
            velocity = handler.get("target_velocity", {})
            if isinstance(velocity, Mapping):
                for key, token in {
                    "velX": "sObj->velX",
                    "velY": "sObj->velY",
                    "velAbsX": "sObj->velAbsX",
                    "velAbsY": "sObj->velAbsY",
                }.items():
                    _append_observed_field(observation, token, velocity.get(key), phase="during", scope=handler_scope, source=source)
        geometry = observation.setdefault("geometry", {})
        if not isinstance(geometry, dict):
            geometry = {}
            observation["geometry"] = geometry
        if run.get("runtime_target_polygon"):
            geometry["runtime_target_polygon"] = deepcopy(run.get("runtime_target_polygon"))
        if run.get("runtime_roi"):
            geometry["runtime_roi"] = deepcopy(run.get("runtime_roi"))
        if handler.get("fInterX") is not None or handler.get("fInterY") is not None:
            geometry["predicted_intersection"] = {
                "fInterX": handler.get("fInterX"),
                "fInterY": handler.get("fInterY"),
            }
        if run.get("runtime_output_after_function"):
            geometry["runtime_output_after_function"] = deepcopy(run.get("runtime_output_after_function"))
        diagnostic = f"legacy_replay_details_lifted:{run.get('run_id', '')}"
        if diagnostic not in observation.setdefault("diagnostics", []):
            observation["diagnostics"].append(diagnostic)


_C_STRUCT_NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"


def _parse_gdb_struct_points(value: Any) -> tuple[int | None, list[list[float]]]:
    text = str(value or "")
    number = re.search(r"\bnum\s*=\s*(\d+)", text)
    count = int(number.group(1)) if number else None
    points = [
        [float(x), float(y)]
        for x, y in re.findall(
            rf"\bx\s*=\s*({_C_STRUCT_NUMBER})\s*,\s*y\s*=\s*({_C_STRUCT_NUMBER})",
            text,
        )
    ]
    if count is not None:
        points = points[: max(0, count)]
    return count, points


def _parse_gdb_struct_fields(value: Any) -> dict[str, Any]:
    text = str(value or "")
    result: dict[str, Any] = {}
    names = (
        "distX", "distY", "distZ", "length", "width", "height", "yawAng",
        "objID", "objType", "dynFlg", "lifeCycle", "fTTC", "fDDCI", "fPredTTC",
        "fIntAng", "fInterX", "fInterY", "velX", "velY", "velAbsX", "velAbsY",
        "objFctaWarningFlag", "objFctbWarningFlag", "leftFctaFlag", "rightFctaFlag",
        "leftFctbFlag", "rightFctbFlag",
    )
    for name in names:
        match = re.search(rf"\b{re.escape(name)}\s*=\s*({_C_STRUCT_NUMBER}|true|false)", text)
        if match:
            result[name] = _parse_scalar(match.group(1))
    return result


def _normalise_existing_gdb_fields(observation: dict[str, Any]) -> None:
    """Normalise scalar values already stored by an older GDB producer.

    Fresh transcript fields go through :func:`_field`, but canonical
    artifacts may have been written before that normalisation existed.  Keep
    the original text in ``raw_value`` and expose the numeric/bool value to
    condition binding and the compact report.  Struct dumps are intentionally
    left untouched; their dedicated parser handles those separately.
    """
    fields = observation.get("fields", []) or []
    if not isinstance(fields, list):
        return
    for field in fields:
        if not isinstance(field, dict) or "value" not in field:
            continue
        value = field.get("value")
        normalized = _parse_scalar(value)
        if normalized != value:
            field.setdefault("raw_value", value)
            field["value"] = normalized


def _enrich_gdb_struct_observation(observation: dict[str, Any]) -> None:
    """Extract stable scalar/point facts from ordinary GDB C-struct output."""
    fields = observation.get("fields", []) or []
    geometry = observation.setdefault("geometry", {})
    if not isinstance(geometry, dict):
        geometry = {}
        observation["geometry"] = geometry
    insertion_offset = 0
    for field_index, field in enumerate(list(fields)):
        if not isinstance(field, Mapping):
            continue
        token = str(field.get("token", ""))
        value = field.get("value")
        if token in {"*objPoly", "objPoly"} or token.endswith("->objPoly"):
            count, points = _parse_gdb_struct_points(value)
            if points:
                geometry["runtime_target_polygon"] = points
                geometry["runtime_target_polygon_num"] = count if count is not None else len(points)
                geometry["polygon_token"] = token
            continue
        if token in {"*leftRoi", "leftRoi", "*rightRoi", "rightRoi"}:
            count, points = _parse_gdb_struct_points(value)
            if points:
                roi = geometry.setdefault("runtime_roi", {})
                side = "leftRoi" if "left" in token.lower() else "rightRoi"
                roi[side] = {"num": count if count is not None else len(points), "points": points}
            continue
        if token not in {"*sObj", "sObj", "objInfo->trcOutData[i]"} and not token.endswith("->trcOutData[i]"):
            continue
        parsed = _parse_gdb_struct_fields(value)
        if not parsed:
            continue
        prefix = "sObj" if "sObj" in token else "objInfo->trcOutData[i]"
        # Put fields that drive condition/side/output decisions first.  The
        # remainder stays available in the full observation, while a bounded
        # Pi/report slice still receives the useful values.
        priority = (
            "objFctaWarningFlag", "objFctbWarningFlag", "leftFctaFlag", "rightFctaFlag",
            "leftFctbFlag", "rightFctbFlag", "fInterX", "fInterY", "fIntAng",
            "fTTC", "fDDCI", "distX", "distY", "length", "width", "yawAng",
            "velX", "velY", "velAbsX", "velAbsY", "objID", "dynFlg", "lifeCycle",
        )
        ordered_names = [name for name in priority if name in parsed]
        ordered_names.extend(name for name in parsed if name not in ordered_names)
        current_source_index = field_index + insertion_offset
        immediate_tokens = {
            str(item.get("token", ""))
            for item in fields[current_source_index + 1: current_source_index + 1 + len(ordered_names)]
            if isinstance(item, Mapping)
        }
        parsed_fields: list[dict[str, Any]] = []
        for name in ordered_names:
            parsed_value = parsed[name]
            parsed_token = f"{prefix}->{name}" if prefix == "sObj" else f"{prefix}.{name}"
            # Legacy replay-detail enrichment may already have emitted the
            # same token as a textual GDB value (for example ``4 '\\004'``).
            # Replace those values with the scalar parse instead of treating
            # the duplicate as a reason to keep the less useful string.
            for existing in fields:
                if isinstance(existing, dict) and str(existing.get("token", "")) == parsed_token:
                    existing["value"] = parsed_value
                    existing["status"] = "observed"
                    existing["source"] = {"kind": "gdb_struct_parse", "source_token": token}
            if parsed_token in immediate_tokens:
                continue
            parsed_fields.append(_field(
                parsed_token,
                parsed_value,
                status="observed",
                phase=str(field.get("phase", "during")),
                scope=str(field.get("scope", "")),
                source={"kind": "gdb_struct_parse", "source_token": token},
            ))
        # Keep parsed scalars adjacent to the source struct.  Evidence-query
        # intentionally bounds field arrays; appending them after a long
        # struct dump made the most useful runtime values disappear from the
        # bounded slice even though they had been successfully parsed.
        if parsed_fields:
            insert_at = field_index + 1 + insertion_offset
            fields[insert_at:insert_at] = parsed_fields
            insertion_offset += len(parsed_fields)
        if observation.get("identity", {}).get("object_id") in (None, "") and parsed.get("objID") not in (None, ""):
            observation.setdefault("identity", {})["object_id"] = parsed.get("objID")


def validate_runtime_evidence(payload: Mapping[str, Any]) -> list[str]:
    """Validate the stable subset of runtime-case-evidence.v1 dependency-free."""
    errors: list[str] = []
    if not isinstance(payload, Mapping):
        return ["runtime_evidence_must_be_object"]
    if payload.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version_mismatch:{payload.get('schema_version', '')}")
    if payload.get("status") not in {"ready", "partial", "blocked", "failed"}:
        errors.append("status_invalid")
    run = payload.get("run")
    if not isinstance(run, Mapping):
        errors.append("run_missing_or_invalid")
    else:
        for key in ("run_id", "data_fingerprint", "source_context_id"):
            if not isinstance(run.get(key), str):
                errors.append(f"run.{key}_must_be_string")
    layers = payload.get("evidence_layers")
    if not isinstance(layers, list):
        errors.append("evidence_layers_missing_or_invalid")
    observations = payload.get("observations")
    if not isinstance(observations, list):
        errors.append("observations_missing_or_invalid")
    else:
        for index, observation in enumerate(observations):
            if not isinstance(observation, Mapping):
                errors.append(f"observations[{index}]_must_be_object")
                continue
            if not str(observation.get("observation_id", "")):
                errors.append(f"observations[{index}].observation_id_missing")
            if observation.get("layer") not in {
                "recorded_raw", "replay_algorithm", "runtime_with_frame", "gdb_observation",
                "can_tx_observation", "source_derived", "objectlist_candidate", "media",
            }:
                errors.append(f"observations[{index}].layer_invalid")
            if not isinstance(observation.get("identity", {}), Mapping):
                errors.append(f"observations[{index}].identity_invalid")
            fields = observation.get("fields")
            if not isinstance(fields, list):
                errors.append(f"observations[{index}].fields_invalid")
                continue
            for field_index, field in enumerate(fields):
                if not isinstance(field, Mapping) or not str(field.get("token", "")):
                    errors.append(f"observations[{index}].fields[{field_index}].token_missing")
                elif field.get("status") not in _FIELD_STATUSES:
                    errors.append(f"observations[{index}].fields[{field_index}].status_invalid")
    return errors


def _bundle_binding(bundle: Mapping[str, Any]) -> dict[str, Any]:
    provenance = bundle.get("provenance", {}) or {}
    source_context = bundle.get("source_context", {}) or {}
    source_identity = source_context.get("identity", {}) if isinstance(source_context, Mapping) else {}
    case = bundle.get("case", {}) or {}
    binding: dict[str, Any] = {
        "case_id": case.get("case_id"),
        "data_fingerprint": provenance.get("data_fingerprint"),
        "bag": provenance.get("bag_path") or case.get("bag"),
        "source_context_id": provenance.get("source_context_id") or source_context.get("source_context_id"),
        "source_snapshot_hash": provenance.get("source_snapshot_hash") or source_context.get("source_snapshot_hash") or source_identity.get("source_snapshot_hash"),
        "binary_fingerprint": provenance.get("binary_fingerprint") or source_context.get("binary_fingerprint") or source_identity.get("binary_fingerprint"),
        "variant_id": provenance.get("variant_id") or case.get("variant_id"),
        "coem": provenance.get("coem") or case.get("coem") or source_identity.get("coem"),
        "vehicle": provenance.get("vehicle") or case.get("vehicle") or source_identity.get("vehicle"),
    }
    if not binding["data_fingerprint"] and binding.get("bag"):
        binding["data_fingerprint"] = f"bag-path:{_normalise_path(binding['bag'])}"
    return {key: value for key, value in binding.items() if value not in (None, "")}


def _runtime_binding(evidence: Mapping[str, Any]) -> dict[str, Any]:
    run = evidence.get("run", {}) or {}
    result = dict(run) if isinstance(run, Mapping) else {}
    if not result.get("bag"):
        for artifact in (evidence.get("artifacts", {}) or {}).values() if isinstance(evidence.get("artifacts", {}), Mapping) else []:
            if str(artifact).lower().endswith(".bag"):
                result["bag"] = artifact
                break
    return result


def _same_scalar(left: Any, right: Any) -> bool:
    return str(left).strip() == str(right).strip() if left is not None and right is not None else False


def validate_runtime_binding(bundle: Mapping[str, Any], evidence: Mapping[str, Any]) -> dict[str, Any]:
    """Compare runtime and static identities without guessing.

    ``verified`` means the case data and source context are explicitly bound.
    A missing binary fingerprint is ``partial`` because this bundle cannot
    prove ELF parity, but matching observations may still be displayed with
    that limitation visible.  A mismatch is ``conflict`` and is never
    eligible for event overlay.
    """
    static = _bundle_binding(bundle)
    runtime = _runtime_binding(evidence)
    diagnostics: list[str] = []
    comparisons: list[dict[str, Any]] = []
    conflict = False
    partial = False

    def compare(name: str, left: Any, right: Any, *, required: bool = False) -> None:
        nonlocal conflict, partial
        if left in (None, "") or right in (None, ""):
            status = "not_comparable"
            if required:
                partial = True
                diagnostics.append(f"binding_missing:{name}")
        elif _same_scalar(left, right):
            status = "same"
        else:
            status = "different"
            conflict = True
            diagnostics.append(f"binding_conflict:{name}")
        comparisons.append({"left": f"static.{name}", "right": f"runtime.{name}", "status": status, "resolution": "none"})

    compare("source_context_id", static.get("source_context_id"), runtime.get("source_context_id"), required=True)
    compare("source_snapshot_hash", static.get("source_snapshot_hash"), runtime.get("source_snapshot_hash"), required=True)

    static_bag = static.get("bag")
    runtime_bag = runtime.get("bag")
    if static_bag and runtime_bag:
        if _normalise_path(static_bag) == _normalise_path(runtime_bag):
            bag_status = "same"
        elif _basename(static_bag) and _basename(static_bag) == _basename(runtime_bag):
            bag_status = "not_comparable"
            partial = True
            diagnostics.append("binding_data_path_only_basename_match")
        else:
            bag_status = "different"
            conflict = True
            diagnostics.append("binding_conflict:bag")
    else:
        bag_status = "not_comparable"
        partial = True
        diagnostics.append("binding_missing:bag")
    comparisons.append({"left": "static.bag", "right": "runtime.bag", "status": bag_status, "resolution": "none"})

    static_data = static.get("data_fingerprint")
    runtime_data = runtime.get("data_fingerprint")
    if static_data and runtime_data:
        data_status = "same" if _same_scalar(static_data, runtime_data) else "different"
        if data_status == "different":
            # A path-derived bundle fingerprint and a producer-provided hash
            # can be different representations of the same explicit bag.
            if static_bag and runtime_bag and _normalise_path(static_bag) == _normalise_path(runtime_bag):
                data_status = "not_comparable"
                partial = True
                diagnostics.append("binding_data_fingerprint_representation_differs")
            else:
                conflict = True
                diagnostics.append("binding_conflict:data_fingerprint")
    else:
        data_status = "not_comparable"
        partial = True
        diagnostics.append("binding_missing:data_fingerprint")
    comparisons.append({"left": "static.data_fingerprint", "right": "runtime.data_fingerprint", "status": data_status, "resolution": "none"})

    static_binary = static.get("binary_fingerprint")
    runtime_binary = runtime.get("binary_fingerprint")
    if static_binary and runtime_binary:
        binary_status = "same" if _same_scalar(static_binary, runtime_binary) else "different"
        if binary_status == "different":
            conflict = True
            diagnostics.append("binding_conflict:binary_fingerprint")
    else:
        binary_status = "not_comparable"
        partial = True
        diagnostics.append("binding_missing:binary_fingerprint")
    comparisons.append({"left": "static.binary_fingerprint", "right": "runtime.binary_fingerprint", "status": binary_status, "resolution": "none"})

    if conflict:
        status = "conflict"
    elif partial:
        status = "partial"
    else:
        status = "verified"
    required_binding_verified = not any(
        diagnostic in diagnostics
        for diagnostic in ("binding_missing:source_context_id", "binding_missing:bag")
    )
    return {
        "status": status,
        "overlay_eligible": status in {"verified", "partial"} and not conflict and required_binding_verified,
        "required_binding_verified": required_binding_verified,
        "static": static,
        "runtime": runtime,
        "comparisons": comparisons,
        "diagnostics": list(dict.fromkeys(diagnostics)),
    }


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
        value_int = _int(value)
        if value_int is not None:
            result.add(value_int)
    for frame in event.get("frame_evidence", []) or []:
        if isinstance(frame, Mapping):
            value_int = _int(frame.get("frame_id"))
            if value_int is not None:
                result.add(value_int)
    return result


def _event_object_ids(event: Mapping[str, Any]) -> set[str]:
    result: set[str] = set()
    selected = event.get("selected_target", {}) or {}
    for item in [selected, *(event.get("target_candidates", []) or [])]:
        if not isinstance(item, Mapping):
            continue
        value = item.get("obj_id", item.get("object_id"))
        if value not in (None, ""):
            result.add(str(value))
    return result


def match_runtime_observations(
    bundle: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Match observations to one static event by identity, never by proximity alone."""
    events = [item for item in bundle.get("alarm_events", []) or [] if isinstance(item, Mapping)]
    result: list[dict[str, Any]] = []
    for observation in evidence.get("observations", []) or []:
        if not isinstance(observation, Mapping):
            continue
        identity = observation.get("identity", {}) or {}
        if not isinstance(identity, Mapping):
            identity = {}
        observation_id = str(observation.get("observation_id", ""))
        explicit_event = identity.get("event_id")
        candidates: list[Mapping[str, Any]] = []
        if explicit_event not in (None, ""):
            candidates = [event for event in events if str(event.get("event_id", "")) == str(explicit_event)]
        else:
            radar_id = _int(identity.get("radar_id", identity.get("radar")))
            frame_id = _int(identity.get("frame_id", identity.get("frame", identity.get("frame_counter"))))
            object_id = identity.get("object_id", identity.get("obj_id", identity.get("objID")))
            for event in events:
                if radar_id is not None and _int(event.get("radar_id")) != radar_id:
                    continue
                frame_ids = _event_frame_ids(event)
                if frame_id is not None and frame_id not in frame_ids:
                    continue
                object_ids = _event_object_ids(event)
                if object_id not in (None, "") and object_ids and str(object_id) not in object_ids:
                    continue
                candidates.append(event)
        if len(candidates) == 1:
            status = "matched"
            event_id = str(candidates[0].get("event_id", ""))
        elif len(candidates) > 1:
            status = "ambiguous"
            event_id = ""
        else:
            status = "unmatched"
            event_id = ""
        result.append(
            {
                "observation_id": observation_id,
                "event_id": event_id or None,
                "candidate_event_ids": [str(item.get("event_id", "")) for item in candidates],
                "status": status,
                "identity": deepcopy(dict(identity)),
            }
        )
    return result


def _scope_runtime_evidence(
    bundle: Mapping[str, Any],
    evidence: Mapping[str, Any],
    scope: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Select an event/radar/frame/object slice without changing source evidence."""
    if not isinstance(scope, Mapping) or not scope:
        return deepcopy(dict(evidence)), {
            "mode": "full",
            "source_observation_count": len(evidence.get("observations", []) or []),
            "selected_observation_count": len(evidence.get("observations", []) or []),
        }
    event_ids = scope.get("event_ids", scope.get("event_id", []))
    if isinstance(event_ids, str):
        event_ids = [event_ids]
    if not isinstance(event_ids, list):
        event_ids = []
    events = [
        event for event in bundle.get("alarm_events", []) or []
        if isinstance(event, Mapping)
        and (not event_ids or str(event.get("event_id", "")) in {str(item) for item in event_ids})
    ]
    if event_ids and not events:
        result = deepcopy(dict(evidence))
        result["observations"] = []
        scope_result = {
            "mode": "event_slice",
            "event_ids": [str(item) for item in event_ids],
            "radar_ids": [],
            "frame_ids": [],
            "object_ids": [],
            "source_observation_count": len(evidence.get("observations", []) or []),
            "selected_observation_count": 0,
            "diagnostics": ["scope_event_not_found"],
        }
        result["scope"] = scope_result
        return result, scope_result
    radar_values = scope.get("radar_ids", scope.get("radar_id", []))
    if isinstance(radar_values, (str, int, float)):
        radar_values = [radar_values]
    radar_ids = {_int(item) for item in radar_values} if isinstance(radar_values, list) else set()
    frame_ids = {
        frame
        for event in events
        for frame in _event_frame_ids(event)
    }
    scoped_frames = scope.get("frame_ids", [])
    if isinstance(scoped_frames, (str, int, float)):
        scoped_frames = [scoped_frames]
    if isinstance(scoped_frames, list):
        frame_ids.update(_int(item) for item in scoped_frames if _int(item) is not None)
    object_ids = {
        str(item)
        for event in events
        for item in _event_object_ids(event)
    }
    scoped_objects = scope.get("object_ids", scope.get("object_id", []))
    if isinstance(scoped_objects, (str, int, float)):
        scoped_objects = [scoped_objects]
    if isinstance(scoped_objects, list):
        object_ids.update(str(item) for item in scoped_objects)
    observations = []
    for observation in evidence.get("observations", []) or []:
        if not isinstance(observation, Mapping):
            continue
        identity = observation.get("identity", {})
        identity = identity if isinstance(identity, Mapping) else {}
        observation_radar = _int(identity.get("radar_id", identity.get("radar")))
        observation_frame = _int(
            identity.get("frame_id", identity.get("frame", identity.get("frame_counter")))
        )
        observation_object = identity.get(
            "object_id", identity.get("obj_id", identity.get("objID")
        )
        )
        if radar_ids and observation_radar not in radar_ids:
            continue
        if frame_ids and observation_frame is not None and observation_frame not in frame_ids:
            continue
        if object_ids and observation_object not in (None, ""):
            if str(observation_object) not in object_ids:
                continue
        elif object_ids and observation_frame is None and observation_object in (None, ""):
            continue
        observations.append(deepcopy(dict(observation)))
    result = deepcopy(dict(evidence))
    result["observations"] = observations
    scope_result = {
        "mode": "event_slice" if events or event_ids else "explicit_slice",
        "event_ids": [str(item) for item in event_ids],
        "radar_ids": sorted(item for item in radar_ids if item is not None),
        "frame_ids": sorted(frame_ids),
        "object_ids": sorted(object_ids),
        "source_observation_count": len(evidence.get("observations", []) or []),
        "selected_observation_count": len(observations),
    }
    result["scope"] = scope_result
    return result, scope_result


def _runtime_field_comparisons(observations: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Compare repeated fields only when identity and phase are identical."""
    grouped: dict[
        tuple[Any, Any, Any, str, str],
        dict[str, tuple[Any, str]],
    ] = {}
    for observation in observations:
        identity = observation.get("identity", {}) or {}
        if not isinstance(identity, Mapping):
            continue
        key_prefix = (
            identity.get("radar_id"),
            identity.get("frame_id"),
            identity.get("object_id"),
        )
        for field in observation.get("fields", []) or []:
            if not isinstance(field, Mapping) or str(field.get("status", "observed")) != "observed":
                continue
            token = str(field.get("token", ""))
            if not token:
                continue
            phase = str(field.get("phase", "unknown"))
            scope = str(field.get("scope", ""))
            observation_id = str(observation.get("observation_id", ""))
            # Repeated fields within one observation are samples from the same
            # producer, not a disagreement. Keep one value per observation so
            # a large public frame series does not create a quadratic list.
            grouped.setdefault((*key_prefix, token, phase), {}).setdefault(
                observation_id, (field.get("value"), scope)
            )
    comparisons: list[dict[str, Any]] = []
    for key, values_by_observation in grouped.items():
        if len(values_by_observation) < 2:
            continue
        rows = [
            (observation_id, value, scope)
            for observation_id, (value, scope) in values_by_observation.items()
        ]
        for row_index, (first_id, first_value, first_scope) in enumerate(rows[:-1]):
            for other_id, other_value, other_scope in rows[row_index + 1 :]:
                # Repeated ``i``/token rows inside one handler observation are
                # object-loop samples, not producer disagreement. Compare
                # only distinct observation IDs (for example short-vs-long
                # warm-up sessions).
                if other_id == first_id:
                    continue
                same = first_value == other_value and first_scope == other_scope
                comparisons.append({
                    "left": f"{first_id}:{key[3]}",
                    "right": f"{other_id}:{key[3]}",
                    "status": "same" if same else "different",
                    "differences": [] if same else [{
                        "token": key[3],
                        "phase": key[4],
                        "left_value": first_value,
                        "right_value": other_value,
                        "left_scope": first_scope,
                        "right_scope": other_scope,
                    }],
                    "resolution": "not_auto_resolved" if not same else "none",
                })
    return comparisons


def compose_runtime_evidence(
    existing: Mapping[str, Any] | None,
    incoming: Mapping[str, Any],
) -> dict[str, Any]:
    """Combine runtime producers without discarding earlier evidence.

    A case may have a public with-frame trace, a long-warmup GDB session and a
    short-warmup GDB session.  The canonical envelope has one primary ``run``
    for compatibility, while ``runs`` preserves every producer binding.  IDs
    are kept unique; a duplicate observation is retained under a deterministic
    ``#N`` suffix rather than silently replacing the older sample.
    """
    left = deepcopy(dict(existing)) if isinstance(existing, Mapping) else {}
    right = deepcopy(dict(incoming))
    result = deepcopy(right)
    left_run = left.get("run", {}) if isinstance(left.get("run"), Mapping) else {}
    right_run = right.get("run", {}) if isinstance(right.get("run"), Mapping) else {}
    runs: list[dict[str, Any]] = []
    for item in [*(left.get("runs", []) or []), left_run, *(right.get("runs", []) or []), right_run]:
        if not isinstance(item, Mapping) or not any(item.values()):
            continue
        key = json.dumps(dict(item), ensure_ascii=False, sort_keys=True, default=str)
        if any(json.dumps(row, ensure_ascii=False, sort_keys=True, default=str) == key for row in runs):
            continue
        runs.append(deepcopy(dict(item)))
    result["runs"] = runs
    result["run_count"] = len(runs)

    layers: list[dict[str, Any]] = []
    for item in [*(left.get("evidence_layers", []) or []), *(right.get("evidence_layers", []) or [])]:
        if not isinstance(item, Mapping):
            continue
        key = str(item.get("id", "")) or json.dumps(dict(item), sort_keys=True, default=str)
        existing_layer = next((row for row in layers if str(row.get("id", "")) == key), None)
        if existing_layer is None:
            layers.append(deepcopy(dict(item)))
        else:
            statuses = {str(existing_layer.get("status", "")), str(item.get("status", ""))}
            if "conflict" in statuses:
                existing_layer["status"] = "conflict"
            elif "partial" in statuses:
                existing_layer["status"] = "partial"
            diagnostics = list(dict.fromkeys([*(existing_layer.get("diagnostics", []) or []), *(item.get("diagnostics", []) or [])]))
            if diagnostics:
                existing_layer["diagnostics"] = diagnostics
    result["evidence_layers"] = layers

    observations: list[dict[str, Any]] = []
    used_ids: dict[str, int] = {}
    for item in [*(left.get("observations", []) or []), *(right.get("observations", []) or [])]:
        if not isinstance(item, Mapping):
            continue
        observation = deepcopy(dict(item))
        base_id = str(observation.get("observation_id", "runtime-observation"))
        used_ids[base_id] = used_ids.get(base_id, 0) + 1
        if used_ids[base_id] > 1:
            observation["observation_id"] = f"{base_id}#{used_ids[base_id]}"
        observations.append(observation)
    result["observations"] = observations
    attempts: list[dict[str, Any]] = []
    for item in [*(left.get("attempts", []) or []), *(right.get("attempts", []) or [])]:
        if not isinstance(item, Mapping):
            continue
        key = json.dumps(dict(item), ensure_ascii=False, sort_keys=True, default=str)
        if any(json.dumps(row, ensure_ascii=False, sort_keys=True, default=str) == key for row in attempts):
            continue
        attempts.append(deepcopy(dict(item)))
    result["attempts"] = attempts
    if (
        not any(isinstance(item, Mapping) for item in (right.get("observations", []) or []))
        and str(right.get("status", "")) in {"blocked", "failed"}
        and isinstance(left.get("run"), Mapping)
        and left.get("run")
    ):
        # Keep the compatibility ``run`` field pointed at the latest usable
        # evidence.  The blocked/failed producer remains auditable in
        # ``runs`` and ``attempts``; otherwise a failed cleanup/attach attempt
        # would make older consumers discard valid observations from an earlier
        # producer.
        result["run"] = deepcopy(dict(left["run"]))
    result["comparisons"] = [
        deepcopy(dict(item))
        for item in [*(left.get("comparisons", []) or []), *(right.get("comparisons", []) or [])]
        if isinstance(item, Mapping)
    ]
    result["comparisons"].extend(_runtime_field_comparisons(observations))
    result["diagnostics"] = list(dict.fromkeys([*(left.get("diagnostics", []) or []), *(right.get("diagnostics", []) or [])]))
    left_disturbance = left.get("disturbance", {}) if isinstance(left.get("disturbance"), Mapping) else {}
    right_disturbance = right.get("disturbance", {}) if isinstance(right.get("disturbance"), Mapping) else {}
    severity = {"not_evaluated": 0, "suspected": 1, "confirmed": 2}
    left_status = str(left_disturbance.get("status", "not_evaluated"))
    right_status = str(right_disturbance.get("status", "not_evaluated"))
    chosen_status = left_status if severity.get(left_status, 0) >= severity.get(right_status, 0) else right_status
    result["disturbance"] = {
        "status": chosen_status,
        "reason": str(right_disturbance.get("reason") or left_disturbance.get("reason") or "No replay disturbance comparison was supplied."),
        "metrics": {**dict(left_disturbance.get("metrics", {}) or {}), **dict(right_disturbance.get("metrics", {}) or {})},
        "source": "composite_runner_summary",
        "diagnostics": list(dict.fromkeys([*(left_disturbance.get("diagnostics", []) or []), *(right_disturbance.get("diagnostics", []) or [])])),
    }
    result["producer"] = {
        "kind": "runtime-evidence-composite",
        "producers": [left.get("producer", {}), right.get("producer", {})],
    }
    statuses = {
        str(item.get("status"))
        for item in (left, right)
        if isinstance(item, Mapping) and item.get("status") not in (None, "")
    }
    if not statuses:
        statuses = {"partial"}
    if statuses == {"blocked"}:
        composite_status = "blocked"
    elif statuses == {"failed"}:
        composite_status = "failed"
    elif statuses & {"blocked", "failed", "partial"}:
        # A failed/blocked attempt must not poison already available public or
        # GDB evidence; it makes the composite partial and remains visible in
        # ``attempts``/diagnostics.
        composite_status = "partial"
    else:
        composite_status = "ready"
    result["status"] = composite_status
    return result


def normalize_runtime_evidence(
    payload: Mapping[str, Any] | None = None,
    *,
    transcript: str = "",
    stderr: str = "",
    commands: list[str] | None = None,
    run: Mapping[str, Any] | None = None,
    binding: Mapping[str, Any] | None = None,
    marker_field_map: Mapping[str, Any] | None = None,
    artifacts: Mapping[str, Any] | None = None,
    public_warning_names: list[str] | None = None,
) -> dict[str, Any]:
    """Normalize a GDB session/transcript or pass through canonical evidence."""
    source_payload = deepcopy(dict(payload or {})) if isinstance(payload, Mapping) else {}
    public_snapshot: Mapping[str, Any] | None = None
    public_session: Mapping[str, Any] | None = None
    if source_payload.get("schema_version") == "runtime-snapshot-with-frame.v1":
        public_snapshot = source_payload
    elif isinstance(source_payload.get("runtime_snapshot"), Mapping):
        public_snapshot = source_payload["runtime_snapshot"]
        public_session = source_payload
    if public_snapshot is not None:
        return normalize_public_runtime_evidence(
            public_snapshot,
            run=run,
            binding=binding,
            warning_names=public_warning_names,
            artifacts=artifacts,
            session=public_session,
        )
    if source_payload.get("schema_version") == SCHEMA_VERSION:
        result = source_payload
        # Canonical artifacts can be produced by an older normalizer that
        # kept ``p objInfo->trcOutData[i]`` as one GDB string.  Enrich on read
        # so report/Pi consumers receive the same scalar source tokens as a
        # freshly normalized transcript, without changing the evidence layer.
        for observation in result.get("observations", []) or []:
            if isinstance(observation, dict) and observation.get("layer") == "gdb_observation":
                _normalise_existing_gdb_fields(observation)
                _enrich_gdb_struct_observation(observation)
        _enrich_canonical_replay_details(result)
        result.setdefault("producer", {"kind": "runtime-evidence-artifact"})
        result.setdefault("normalization", {"normalizer": "radarAnalyze.engines.runtime_evidence"})
        result.setdefault("diagnostics", [])
        result.setdefault("evidence_layers", [])
        result.setdefault("observations", [])
        result.setdefault("artifacts", {})
        result.setdefault("comparisons", [])
        validation_errors = validate_runtime_evidence(result)
        if validation_errors:
            result["status"] = "blocked"
            result["diagnostics"] = list(dict.fromkeys([*result.get("diagnostics", []), *validation_errors]))
        return result

    source_transcript = str(transcript or "")
    source_stderr = str(stderr or "")
    source_commands = list(commands or [])
    if not source_transcript and isinstance(source_payload, Mapping):
        source_transcript = str(source_payload.get("stdout", "") or "")
        source_stderr = source_stderr or str(source_payload.get("stderr", "") or "")
        source_commands = source_commands or list(source_payload.get("commands", []) or [])
    parsed = source_payload.get("observations") if isinstance(source_payload.get("observations"), Mapping) else None
    if not parsed:
        parsed = parse_gdb_transcript(source_transcript, source_commands, stderr=source_stderr)
    run_data: dict[str, Any] = dict(run or {})
    source_run = source_payload.get("target", {}) if isinstance(source_payload.get("target"), Mapping) else {}
    for key in ("run_id", "data_fingerprint", "source_context_id", "source_snapshot_hash", "binary_fingerprint", "server", "workspace", "bag", "project_id", "variant_id", "coem", "vehicle", "radar_id", "node_name", "attach_mode", "attach_status", "attach_blocked_reason"):
        if key not in run_data and key in source_payload:
            run_data[key] = source_payload.get(key)
        if key not in run_data and key in source_run:
            run_data[key] = source_run.get(key)
    run_data.setdefault("run_id", "runtime-run-unbound")
    run_data.setdefault("data_fingerprint", "")
    run_data.setdefault("source_context_id", "")
    if not run_data.get("data_fingerprint") and run_data.get("bag"):
        run_data["data_fingerprint"] = "bag-path:" + _normalise_path(run_data["bag"])
        run_data["data_fingerprint_source"] = "bag_path_derived"
    combined_transcript = "\n".join(item for item in (source_transcript, source_stderr) if item)
    attach_blocked = (
        str(source_payload.get("status", "")) == "blocked"
        or str(source_run.get("attach_status", "")) == "blocked"
        or bool(re.search(r"^ATTACH_STATUS=blocked$", combined_transcript, flags=re.MULTILINE))
    )
    attach_reason_match = re.search(
        r"^ATTACH_BLOCKED_REASON=(?P<reason>.+)$",
        combined_transcript,
        flags=re.MULTILINE,
    )
    attach_reason = (
        str(source_run.get("attach_blocked_reason", "")).strip()
        or (attach_reason_match.group("reason").strip() if attach_reason_match else "")
    )
    if attach_blocked:
        run_data["attach_status"] = "blocked"
        if attach_reason:
            run_data["attach_blocked_reason"] = attach_reason
    marker_binding = dict(binding or {})
    if not marker_binding:
        marker_binding = dict(run_data)
    marker_rows = parse_runtime_markers("\n".join(item for item in (source_transcript, source_stderr) if item))
    source_meta = {
        "kind": "gdb_transcript",
        "transcript_sha256": _sha256_text(source_transcript),
        "stderr_sha256": _sha256_text(source_stderr) if source_stderr else "",
    }
    disturbance = _disturbance_from_transcript(
        "\n".join(item for item in (source_transcript, source_stderr) if item),
        parsed,
    )
    observations: list[dict[str, Any]] = []
    if parsed and not attach_blocked:
        generic = _generic_observation(
            parsed=parsed,
            identity=_identity_from_values(source_run, binding=marker_binding, run=run_data),
            run=run_data,
            source=source_meta,
        )
        _enrich_gdb_struct_observation(generic)
        generic["disturbance"] = deepcopy(disturbance)
        if generic.get("fields") or generic.get("call_chain") or generic.get("stops") or generic.get("diagnostics"):
            observations.append(generic)
    if not attach_blocked:
        observations.extend(
            _marker_observations(
                marker_rows,
                run=run_data,
                binding=marker_binding,
                marker_field_map=marker_field_map,
            )
        )
    diagnostics = list(parsed.get("diagnostics", []) or []) if isinstance(parsed, Mapping) else []
    if attach_blocked:
        diagnostics.append("runtime_execution_blocked")
        if attach_reason:
            diagnostics.append(f"runtime_execution_blocked:{attach_reason}")
    if not source_transcript and not source_payload.get("observations"):
        diagnostics.append("gdb_transcript_missing")
    if not run_data.get("data_fingerprint"):
        diagnostics.append("binding_missing:data_fingerprint")
    if not run_data.get("source_context_id"):
        diagnostics.append("binding_missing:source_context_id")
    layer_status = "observed" if observations else "not_available"
    result_status = "blocked" if attach_blocked else "ready" if observations and not diagnostics else "partial"
    attempts = []
    if attach_blocked:
        attempts.append(
            {
                "status": "blocked",
                "kind": "runtime_debug_attempt",
                "reason": attach_reason or "runtime_execution_blocked",
                "target": deepcopy(run_data),
                "source": source_meta,
                "diagnostics": list(dict.fromkeys(diagnostics)),
            }
        )
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": result_status,
        "run": run_data,
        "producer": {
            "kind": "headless_gdb",
            "input_schema": source_payload.get("schema_version", "gdb-transcript") if source_payload else "gdb-transcript",
            "normalizer": "radarAnalyze.engines.runtime_evidence",
        },
        "normalization": {
            "marker_count": len(marker_rows),
            "commands": source_commands,
            "transcript_sha256": source_meta["transcript_sha256"],
            "stderr_sha256": source_meta["stderr_sha256"],
        },
        "evidence_layers": [
            {
                "id": "gdb_observation",
                "kind": "gdb_observation",
                "authority": "headless_gdb_transcript",
                "status": layer_status,
                "source": source_meta,
                "diagnostics": list(dict.fromkeys(diagnostics)),
            }
        ],
        "observations": observations,
        "attempts": attempts,
        "warmup": {},
        "comparisons": [],
        "diagnostics": list(dict.fromkeys(diagnostics)),
        "disturbance": disturbance,
        "artifacts": {str(key): str(value) for key, value in (artifacts or {}).items() if value not in (None, "")},
    }
    if source_transcript:
        result["artifacts"].setdefault("gdb_transcript_sha256", source_meta["transcript_sha256"])
    return result


def _observation_by_id(evidence: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        str(item.get("observation_id")): item
        for item in evidence.get("observations", []) or []
        if isinstance(item, Mapping) and str(item.get("observation_id", ""))
    }


def merge_runtime_evidence(
    bundle: Mapping[str, Any],
    evidence: Mapping[str, Any],
    *,
    scope: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a static-plus-runtime derived bundle with provenance gates."""
    scoped_evidence, scope_result = _scope_runtime_evidence(bundle, evidence, scope)
    evidence_copy = compose_runtime_evidence(bundle.get("runtime_evidence"), scoped_evidence)
    validation_errors = validate_runtime_evidence(evidence_copy)
    binding = validate_runtime_binding(bundle, evidence_copy)
    matches = match_runtime_observations(bundle, evidence_copy) if not validation_errors else []
    matched_count = sum(1 for item in matches if item.get("status") == "matched")
    diagnostics = list(dict.fromkeys([
        *validation_errors,
        *binding.get("diagnostics", []),
        *[f"runtime_observation_{item['status']}:{item.get('observation_id', '')}" for item in matches if item.get("status") != "matched"],
    ]))
    if validation_errors or binding.get("status") == "conflict":
        merge_status = "blocked"
    elif not matched_count:
        merge_status = "partial"
        diagnostics.append("runtime_no_event_match")
    elif binding.get("status") == "partial" or matched_count < len(matches):
        merge_status = "partial"
    else:
        merge_status = "ready"

    merged = deepcopy(dict(bundle))
    # These are additive keys.  Static alarm_events/frame facts remain byte
    # for byte in their original locations; only runtime_refs are appended.
    merged["runtime_evidence"] = evidence_copy
    merged["runtime_merge"] = {
        "schema_version": "runtime-evidence-merge.v1",
        "status": merge_status,
        "binding": binding,
        "observation_matches": matches,
        "matched_observation_count": matched_count,
        "observation_count": len(matches),
        "scope": scope_result,
        "diagnostics": diagnostics,
    }
    match_by_event: dict[str, list[str]] = {}
    for item in matches:
        if binding.get("overlay_eligible") and item.get("status") == "matched" and item.get("event_id"):
            match_by_event.setdefault(str(item["event_id"]), []).append(str(item.get("observation_id", "")))
    for event in merged.get("alarm_events", []) or []:
        if not isinstance(event, dict):
            continue
        event_id = str(event.get("event_id", ""))
        observation_ids = match_by_event.get(event_id, [])
        event["runtime_overlay"] = {
            "status": "matched" if observation_ids else "blocked" if binding.get("status") == "conflict" else "not_matched",
            "observation_ids": observation_ids,
            "source": "runtime_evidence" if observation_ids else "none",
        }
    return merged


def runtime_summary(
    evidence: Mapping[str, Any],
    merge: Mapping[str, Any] | None = None,
    *,
    max_observations: int = 24,
) -> dict[str, Any]:
    """Bounded deterministic projection safe to put into a Pi prompt/context."""
    observations = [item for item in evidence.get("observations", []) or [] if isinstance(item, Mapping)]
    limit = max(0, int(max_observations))
    if limit == 0:
        sampled_observations = []
    elif len(observations) > limit:
        head_count = limit // 2
        tail_count = limit - head_count
        sampled_observations = [*observations[:head_count], *observations[-tail_count:]]
    else:
        sampled_observations = observations
    return {
        "schema_version": evidence.get("schema_version"),
        "status": evidence.get("status", "not_available"),
        "run": deepcopy(dict(evidence.get("run", {}) or {})),
        "runs": deepcopy(list(evidence.get("runs", []) or [])),
        "run_count": int(evidence.get("run_count", len(evidence.get("runs", []) or []))),
        "evidence_layers": [
            {
                "id": item.get("id"),
                "kind": item.get("kind"),
                "authority": item.get("authority"),
                "status": item.get("status"),
            }
            for item in (evidence.get("evidence_layers", []) or [])
            if isinstance(item, Mapping)
        ],
        "observation_count": len(observations),
        "observation_sampled": len(sampled_observations) < len(observations),
        "observation_sample_limit": limit,
        "observations": deepcopy(sampled_observations),
        "attempts": deepcopy(list(evidence.get("attempts", []) or [])),
        "warmup": deepcopy(dict(evidence.get("warmup", {}) or {})),
        "comparisons": deepcopy(list(evidence.get("comparisons", []) or [])),
        "disturbance": deepcopy(dict(evidence.get("disturbance", {}) or {})),
        "diagnostics": list(evidence.get("diagnostics", []) or []),
        "merge": deepcopy(dict(merge or {})),
    }


__all__ = [
    "GDB_SESSION_SCHEMA_VERSION",
    "SCHEMA_VERSION",
    "compose_runtime_evidence",
    "load_runtime_input",
    "match_runtime_observations",
    "merge_runtime_evidence",
    "normalize_runtime_evidence",
    "normalize_public_runtime_evidence",
    "parse_runtime_markers",
    "runtime_summary",
    "validate_runtime_binding",
    "validate_runtime_evidence",
]
