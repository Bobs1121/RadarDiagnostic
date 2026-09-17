"""Deterministic point-cloud replay planning and perception evidence helpers.

This module deliberately plans the point-cloud path without starting ROS or
changing an arbe workspace.  It keeps the HILMODEL/build gate explicit: a
target-injection run is not a point-cloud perception run.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import csv
import io
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


PLAN_SCHEMA = "point-cloud-replay-plan.v1"
CONTRACT_SCHEMA = "perception-input-contract.v1"
RUN_SCHEMA = "perception-run.v1"
COMPARISON_SCHEMA = "perception-comparison.v1"
SCENE_SCHEMA = "perception-scene.v1"
TIMELINE_SCHEMA = "perception-timeline.v1"
WARMUP_SCHEMA = "perception-warmup-analysis.v1"
INJECTION_SCHEMA = "perception-injection-audit.v1"
HYPOTHESIS_SCHEMA = "perception-hypothesis-set.v1"
CAPABILITY_SCHEMA = "perception-capability-manifest.v1"
ARTIFACT_SCHEMA = "perception-artifact-audit.v1"
VALIDATION_SCHEMA = "perception-validation.v1"
STAGE_NAMES = (
    "input_decode",
    "dot_preprocess",
    "environment_detect",
    "dot_filter",
    "cluster",
    "track",
    "track_output",
    "adas_func",
)

STAGE_FUNCTIONS: dict[str, tuple[str, ...]] = {
    "input_decode": ("corner_radar_post_process_data_callback", "BagTransTIMerge"),
    "dot_preprocess": ("DotPrePosTI",),
    "environment_detect": ("EnvModelDetect",),
    "dot_filter": ("DotFilter",),
    "cluster": ("ObjCluster",),
    "track": ("ObjTrack",),
    "track_output": ("OutputTrkObj",),
    "adas_func": ("AdasFunc",),
}


def _hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _is_sha256_digest(value: Any) -> bool:
    return bool(re.fullmatch(r"[0-9a-fA-F]{64}", str(value or "").strip()))


def _local_file_matches_sha256(path_value: Any, expected_sha256: Any) -> bool:
    path_text = str(path_value or "").strip()
    expected = str(expected_sha256 or "").strip().lower()
    if not path_text or not _is_sha256_digest(expected):
        return False
    path = Path(path_text).expanduser()
    if not path.is_absolute() or not path.is_file():
        return False
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return False
    return digest.hexdigest() == expected


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _int_or_default(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _safe_value(value: Any) -> tuple[Any, dict[str, Any] | None]:
    """Return a JSON-safe scalar and preserve non-finite input provenance.

    ``json.dumps`` accepts NaN/Infinity by default even though those literals
    are not valid JSON.  Point-cloud artifacts are exchanged with Pi and must
    therefore encode such values as ``null`` while retaining the original
    literal and a machine-readable reason.
    """
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return None, {"raw_literal": repr(value), "status": "non_finite", "reason": "non_finite_input"}
    if isinstance(value, (str, int, bool)) or value is None:
        return value, None
    try:
        json.dumps(value, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError):
        return str(value), {"raw_literal": repr(value), "status": "coerced", "reason": "non_json_scalar"}
    return value, None


def _safe_tree(value: Any) -> Any:
    """Recursively make a captured raw payload valid JSON."""
    if isinstance(value, Mapping):
        return {str(key): _safe_tree(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe_tree(item) for item in value]
    return _safe_value(value)[0]


def _safe_evidence_row(value: Mapping[str, Any]) -> dict[str, Any]:
    """Make a captured evidence row strict-JSON-safe and retain bad scalars."""
    field_status: dict[str, Any] = dict(value.get("field_status", {})) if isinstance(value.get("field_status"), Mapping) else {}

    def visit(item: Any, path: str) -> Any:
        if isinstance(item, Mapping):
            return {str(key): visit(child, f"{path}.{key}" if path else str(key)) for key, child in item.items()}
        if isinstance(item, (list, tuple)):
            return [visit(child, f"{path}[{index}]") for index, child in enumerate(item)]
        safe, marker = _safe_value(item)
        if marker:
            field_status[path or "value"] = marker
        return safe

    row = visit(value, "")
    if field_status:
        row["field_status"] = field_status
        row.setdefault("status", "partial")
        diagnostics = list(row.get("diagnostics", []) or [])
        diagnostics.append("non_finite_or_non_json_evidence_value")
        row["diagnostics"] = list(dict.fromkeys(diagnostics))
    return row


_STRUCTURED_ARTIFACT_SUFFIXES = {".json", ".jsonl", ".ndjson", ".csv"}
_BINARY_ARTIFACT_SUFFIXES = {".mf4", ".blf", ".db3"}
PERCEPTION_ARTIFACT_ADAPTERS: dict[str, dict[str, Any]] = {
    ".json": {"parser": "json_object", "loader": None},
    ".jsonl": {"parser": "json_lines", "loader": None},
    ".ndjson": {"parser": "json_lines", "loader": None},
    ".csv": {"parser": "csv_rows", "loader": None},
    # ROS bag support is attached below through a lazy loader so importing the
    # control plane does not require ROS/rosbags on every workstation.
    ".bag": {"parser": "rosbags_wfautosar", "loader": None},
}


def _load_rosbag_perception_artifact(path: Path) -> Mapping[str, Any]:
    """Decode bounded wfAutosarData perception rows from a ROS1 bag.

    This adapter only exposes the post-detection dotTrans/object boundary.  It
    never labels ADC/FFT/CFAR as available and leaves the layout profile
    unverified until an active source snapshot binds it.
    """
    try:
        from parsers.bag_parser import BagParser
        from tools.decode_lgu_output import DOT_LAYOUT_PROFILE

        point_rows: list[dict[str, Any]] = []
        output_rows: list[dict[str, Any]] = []
        stage_evidence: list[dict[str, Any]] = []
        topics: list[str] = []
        for index, frame in enumerate(BagParser(path).iter_frames(skip_images=True)):
            if index >= 2000:
                break
            fields = frame.fields if isinstance(frame.fields, Mapping) else {}
            if not fields.get("point_rows"):
                continue
            topics.append(frame.topic)
            for row in fields.get("point_rows", []) or []:
                point_rows.append(dict(row))
            for row in fields.get("output_rows", []) or []:
                output_rows.append(dict(row))
            stage_evidence.append({
                "stage": "input_decode",
                "frame_id": fields.get("wfa_frame_id"),
                "status": "completed" if fields.get("point_rows") else "partial",
                "runtime_proof": "observed",
                "input_count": len(fields.get("point_rows", []) or []),
                "output_count": len(fields.get("point_rows", []) or []),
                "source_ref": {"topic": frame.topic, "timestamp_ns": frame.timestamp_ns, "message_seq": fields.get("seq")},
            })
    except Exception as exc:  # noqa: BLE001 - adapter boundary reports a blocked artifact
        raise RuntimeError(f"rosbag_perception_parse_failed:{type(exc).__name__}") from exc
    return {
        "schema_version": "perception-capture.v1",
        "input_boundary": "post_detection_point_cloud",
        "point_rows": point_rows,
        "output_rows": output_rows,
        "stage_evidence": stage_evidence,
        "topics": sorted(set(topics)),
        "message_schema": {
            "type": "arbe_msgs/wfAutosarData",
            "payload": "PERInfoOutStruct.dotTrans",
            "status": "source_layout_binding_required",
            "layout_profile": dict(DOT_LAYOUT_PROFILE),
        },
        "target_usage": {"status": "not_available", "basis": "wfAutosarData_dotTrans_only"},
        "diagnostics": ["layout_profile_requires_active_source_binding", "private_perception_stage_trace_not_available"],
    }


PERCEPTION_ARTIFACT_ADAPTERS[".bag"]["loader"] = _load_rosbag_perception_artifact


def register_perception_artifact_adapter(
    suffixes: Sequence[str] | str,
    *,
    parser: str,
    loader: Callable[[Path], Mapping[str, Any]] | None,
) -> None:
    """Register an external artifact adapter without changing the core parser."""
    values = [suffixes] if isinstance(suffixes, str) else list(suffixes)
    for suffix in values:
        normalized = str(suffix).lower()
        if not normalized.startswith("."):
            normalized = "." + normalized
        PERCEPTION_ARTIFACT_ADAPTERS[normalized] = {"parser": str(parser), "loader": loader}


def audit_perception_artifact(path: str | Path) -> dict[str, Any]:
    """Audit an artifact's available parser boundary without guessing its data."""
    target = Path(path).expanduser().resolve()
    registered_formats = sorted(PERCEPTION_ARTIFACT_ADAPTERS)
    registered_parsers = sorted({str(item.get("parser")) for item in PERCEPTION_ARTIFACT_ADAPTERS.values() if item.get("parser")})
    if not target.is_file():
        return {
            "schema_version": ARTIFACT_SCHEMA,
            "status": "blocked",
            "path": str(target),
            "format": target.suffix.lower().lstrip("."),
            "size_bytes": 0,
            "sha256": "",
            "parser": "none",
            "registered_formats": registered_formats,
            "registered_parsers": registered_parsers,
            "payload_shape": {},
            "diagnostics": ["artifact_missing"],
        }
    digest = hashlib.sha256()
    size = 0
    try:
        with target.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                size += len(chunk)
                digest.update(chunk)
    except OSError as exc:
        return {
            "schema_version": ARTIFACT_SCHEMA,
            "status": "blocked",
            "path": str(target),
            "format": target.suffix.lower().lstrip("."),
            "size_bytes": 0,
            "sha256": "",
            "parser": "none",
            "registered_formats": registered_formats,
            "registered_parsers": registered_parsers,
            "payload_shape": {},
            "diagnostics": [f"artifact_unreadable:{type(exc).__name__}"],
        }
    suffix = target.suffix.lower()
    adapter = PERCEPTION_ARTIFACT_ADAPTERS.get(suffix)
    if adapter is not None:
        parser = str(adapter.get("parser") or "custom")
        status = "supported"
        diagnostics: list[str] = []
    elif suffix in _BINARY_ARTIFACT_SUFFIXES:
        parser = "not_attached"
        status = "unsupported"
        diagnostics = [f"binary_parser_not_attached:{suffix.lstrip('.')}"]
    else:
        parser = "unknown"
        status = "unsupported"
        diagnostics = ["artifact_format_not_supported"]
    return {
        "schema_version": ARTIFACT_SCHEMA,
        "status": status,
        "path": str(target),
        "format": suffix.lstrip("."),
        "size_bytes": size,
        "sha256": digest.hexdigest(),
        "parser": parser,
        "registered_formats": registered_formats,
        "registered_parsers": registered_parsers,
        "payload_shape": {},
        "diagnostics": diagnostics,
    }


def _classify_artifact_row(row: Mapping[str, Any]) -> str:
    explicit = str(row.get("kind") or row.get("row_kind") or row.get("record_type") or row.get("type") or "").lower()
    if explicit in {"point", "dot", "point_cloud", "dottrans"}:
        return "point_rows"
    if explicit in {"cluster", "clu"}:
        return "cluster_rows"
    if explicit in {"track", "trajectory"}:
        return "track_rows"
    if explicit in {"output", "object", "objectlist", "target"}:
        return "output_rows"
    if explicit in {"stage", "stage_evidence", "trace"}:
        return "stage_evidence"
    # Shape-based inference is limited to field structure and never uses topic names.
    keys = {str(key).lower() for key in row}
    if ({"range", "dist", "distance"} & keys) and ({"azimuth", "ang", "angle", "theta"} & keys) and ({"doppler", "vel", "velocity"} & keys):
        return "point_rows"
    if "cluster_id" in keys or "clusterid" in keys:
        return "cluster_rows"
    if "track_id" in keys or "trackid" in keys:
        return "track_rows"
    if "stage" in keys and ({"input_count", "output_count", "runtime_proof", "status"} & keys):
        return "stage_evidence"
    if {"objid", "object_id", "output_key"} & keys:
        return "output_rows"
    return "unknown_rows"


def _classify_artifact_rows(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = {
        "point_rows": [], "cluster_rows": [], "track_rows": [], "output_rows": [], "stage_evidence": [], "unknown_rows": []
    }
    for row in rows:
        if isinstance(row, Mapping):
            grouped[_classify_artifact_row(row)].append(dict(row))
    return grouped


def load_perception_artifact(path: str | Path) -> dict[str, Any]:
    """Load only attached structured formats and retain an audit envelope."""
    audit = audit_perception_artifact(path)
    if audit.get("status") != "supported":
        return {"_artifact_audit": audit}
    target = Path(path).expanduser().resolve()
    try:
        adapter = PERCEPTION_ARTIFACT_ADAPTERS.get(target.suffix.lower()) or {}
        custom_loader = adapter.get("loader")
        if callable(custom_loader):
            custom_payload = custom_loader(target)
            result = dict(custom_payload) if isinstance(custom_payload, Mapping) else {"unknown_rows": []}
        elif audit["parser"] == "json_object":
            payload = json.loads(target.read_text(encoding="utf-8"))
            if isinstance(payload, Mapping):
                result = dict(payload)
            elif isinstance(payload, list):
                result = _classify_artifact_rows(payload)
            else:
                result = {"unknown_rows": []}
        elif audit["parser"] == "json_lines":
            rows = []
            for line in target.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    value = json.loads(line)
                    if isinstance(value, Mapping):
                        rows.append(value)
            result = _classify_artifact_rows(rows)
        else:
            with target.open("r", encoding="utf-8", newline="") as handle:
                result = _classify_artifact_rows(list(csv.DictReader(handle)))
    except (OSError, UnicodeError, json.JSONDecodeError, csv.Error, ValueError, ImportError, RuntimeError) as exc:
        audit["status"] = "blocked"
        audit["diagnostics"] = list(audit.get("diagnostics", []) or []) + [f"artifact_parse_failed:{type(exc).__name__}"]
        return {"_artifact_audit": audit}
    audit["payload_shape"] = {key: len(value) for key, value in result.items() if isinstance(value, list)}
    result["_artifact_audit"] = audit
    return result


def build_perception_stage_map(
    source_root: str | Path,
    *,
    source_files: Sequence[str] | None = None,
    max_file_bytes: int = 8 * 1024 * 1024,
) -> dict[str, Any]:
    """Find stage functions in an explicit source snapshot.

    This is static source evidence.  A match proves a candidate source
    location, never that the function ran in a replay.
    """
    root = Path(source_root).expanduser().resolve()
    paths: list[Path] = []
    if source_files:
        paths = [(root / item).resolve() if not Path(item).is_absolute() else Path(item).resolve() for item in source_files]
    elif root.is_dir():
        paths = [
            path for path in root.rglob("*")
            if path.suffix.lower() in {".c", ".h", ".cc", ".cpp", ".hpp"}
            and not any(part in {"build", "devel", ".git"} for part in path.parts)
        ]
    matches: dict[str, list[dict[str, Any]]] = {stage: [] for stage in STAGE_NAMES}
    digest = hashlib.sha256()
    scanned: list[str] = []
    for path in sorted(paths):
        if not path.is_file():
            continue
        try:
            raw = path.read_bytes()
            if len(raw) > max_file_bytes:
                continue
            text = raw.decode("utf-8", errors="replace")
        except OSError:
            continue
        scanned.append(str(path))
        digest.update(str(path).encode("utf-8"))
        digest.update(raw)
        lines = text.splitlines()
        for stage, functions in STAGE_FUNCTIONS.items():
            for function in functions:
                pattern = re.compile(rf"\b{re.escape(function)}\s*\(")
                for line_index, line in enumerate(lines, start=1):
                    if not pattern.search(line):
                        continue
                    context = "\n".join(lines[max(0, line_index - 25):line_index])
                    condition = ""
                    if "HILMODEL" in context:
                        condition = "HILMODEL_preprocessor_context"
                    guard = ""
                    activation = "unknown"
                    for context_line in reversed(lines[max(0, line_index - 80):line_index]):
                        stripped = context_line.strip()
                        if stripped.startswith("#if") and "HILMODEL" in stripped:
                            guard = stripped[3:].strip()
                            activation = "HILMODEL==0" if re.search(r"(?:0\s*==\s*HILMODEL|HILMODEL\s*==\s*0)", guard) else "HILMODEL_expression"
                            break
                        if stripped.startswith("#if") and "BUILDMODEL" in stripped:
                            guard = stripped[3:].strip()
                            activation = "BUILDMODEL_expression"
                            break
                    try:
                        relative = str(path.relative_to(root)).replace("\\", "/")
                    except ValueError:
                        relative = str(path)
                    matches[stage].append({
                        "function": function,
                        "source_ref": {
                            "path": relative,
                            "line": line_index,
                            "source_root": str(root),
                        },
                        "status": "source_candidate",
                        "preprocessor_context": condition,
                        "compile_guard": guard,
                        "activation_requirement": activation,
                        "snippet": line.strip()[:400],
                    })
    return {
        "schema_version": "perception-stage-map.v1",
        "status": "ready" if any(matches.values()) else "not_available",
        "source_root": str(root),
        "source_snapshot_hash": digest.hexdigest() if scanned else "",
        "scanned_files": scanned,
        "stages": matches,
        "runtime_proof": "not_available",
    }


def _get_preflight_macro(preflight: Mapping[str, Any], name: str) -> str | None:
    build = _mapping(preflight.get("build"))
    macros = _mapping(build.get("macros"))
    if name in macros:
        return str(macros[name])
    identity = _mapping(preflight.get("identity"))
    macros = _mapping(identity.get("macros"))
    return str(macros[name]) if name in macros else None


def _audit_runtime_workspace_alignment(preflight: Mapping[str, Any]) -> dict[str, Any]:
    """Check that discovered runtime processes belong to the planned workspace."""
    workspace = _mapping(preflight.get("workspace"))
    runtime = _mapping(preflight.get("runtime"))
    root = str(workspace.get("arbe_root") or workspace.get("path") or "").rstrip("/")
    processes = runtime.get("processes")
    processes = processes if isinstance(processes, Sequence) and not isinstance(processes, (str, bytes, bytearray)) else []
    if not processes or not root:
        return {"status": "not_available", "workspace_root": root, "matched": [], "mismatched": [], "diagnostics": []}
    # A command line is not an executable identity: a workspace path may occur
    # in an argument while the process actually runs another binary.  Prefer a
    # path obtained from /proc/<pid>/exe (or an equivalent preflight field) and
    # only use the first absolute command token as a conservative fallback.
    import posixpath
    def normalized(value: Any) -> str:
        text = str(value or "").strip().replace("\\", "/")
        return posixpath.normpath(text) if text.startswith("/") else ""

    root = normalized(root)
    def within_workspace(path: str) -> bool:
        return bool(path and root and (path == root or path.startswith(root + "/")))

    matched: list[dict[str, Any]] = []
    mismatched: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    for process in processes:
        if not isinstance(process, Mapping):
            continue
        command = str(process.get("command") or "")
        executable = normalized(
            process.get("executable_path")
            or process.get("exe")
            or process.get("proc_exe")
            or process.get("/proc_exe")
        )
        if not executable and command:
            try:
                import shlex
                first = shlex.split(command, posix=True)[0] if shlex.split(command, posix=True) else ""
            except (ValueError, IndexError):
                first = ""
            if first.startswith("/"):
                executable = normalized(first)
        row = {
            "pid": process.get("pid"),
            "radar_id": process.get("radar_id"),
            "command": command,
            "executable_path": executable,
            "identity_source": "proc_exe_or_preflight" if executable else "not_available",
        }
        if executable and within_workspace(executable):
            matched.append(row)
        elif executable:
            mismatched.append(row)
        else:
            unresolved.append(row)
    if mismatched:
        status = "conflict"
        diagnostics = ["runtime_process_workspace_mismatch"]
    elif matched and not unresolved:
        status = "aligned"
        diagnostics = []
    elif matched and unresolved:
        status = "not_available"
        diagnostics = ["runtime_process_executable_unresolved"]
    else:
        status = "not_available"
        diagnostics = ["runtime_process_executable_unresolved"] if unresolved else ["runtime_process_command_missing"]
    return {
        "status": status,
        "workspace_root": root,
        "matched": matched,
        "mismatched": mismatched,
        "unresolved": unresolved,
        "diagnostics": diagnostics,
    }


def audit_runtime_workspace_alignment(preflight: Mapping[str, Any] | None) -> dict[str, Any]:
    """Public read-only runtime/workspace identity gate for execution adapters."""
    return _audit_runtime_workspace_alignment(_mapping(preflight))


def build_point_cloud_replay_plan(
    *,
    server_host: str = "",
    server_user: str = "",
    server_port: int = 22,
    remote_bag_path: str = "",
    point_cloud_topic: str = "",
    output_topics: Sequence[str] | None = None,
    remote_capture_base: str = "",
    input_topics: Sequence[str] | None = None,
    ros_setup: str = "/opt/ros/noetic/setup.bash",
    workspace_setup: str = "",
    ros_master_uri: str = "http://localhost:11311",
    start_sec: float = 0.0,
    duration_sec: float = 4.0,
    frame_period_sec: float = 0.066,
    warmup_frames: int = 175,
    preflight: Mapping[str, Any] | None = None,
    source_context: Mapping[str, Any] | None = None,
    input_contract: Mapping[str, Any] | None = None,
    topic_inventory: Mapping[str, Any] | None = None,
    stage_map: Mapping[str, Any] | None = None,
    source_root: str = "",
    source_files: Sequence[str] | None = None,
    run_id: str = "",
) -> dict[str, Any]:
    """Build a plan and readiness gates for post-detection point-cloud replay."""
    preflight = _mapping(preflight)
    source_context = _mapping(source_context)
    from engines.arbe.execution_binding import derive_execution_identity
    derived_identity, identity_provenance = derive_execution_identity(
        preflight=preflight,
        source_context=source_context,
    )
    if not stage_map and str(source_root or "").strip():
        stage_map = build_perception_stage_map(source_root, source_files=source_files)
    output_topics = [str(item) for item in (output_topics or []) if str(item).strip()]
    input_topics = [str(item) for item in (input_topics or [point_cloud_topic]) if str(item).strip()]
    diagnostics: list[str] = []
    gates: list[dict[str, Any]] = []
    identity_conflicts = str(identity_provenance.get("__conflicts__") or "").strip()
    if identity_conflicts:
        diagnostics.extend(item for item in identity_conflicts.split(";") if item)
        gates.append({
            "id": "identity_source_conflict",
            "status": "blocked",
            "observed": {"conflicts": identity_conflicts.split(";")},
            "reason": "plan identity must come from one current source/config snapshot",
        })

    if not str(remote_bag_path).strip():
        diagnostics.append("remote_bag_path_missing")
    if not str(server_host).strip():
        diagnostics.append("remote_server_target_missing")
    if not str(point_cloud_topic).strip():
        diagnostics.append("point_cloud_topic_missing")
    if not output_topics:
        diagnostics.append("point_cloud_output_topics_missing")
    try:
        warmup_frames = int(warmup_frames)
    except (TypeError, ValueError):
        warmup_frames = 0
    if not 150 <= warmup_frames <= 200:
        diagnostics.append("point_cloud_warmup_must_be_150_to_200")
    try:
        frame_period_sec = float(frame_period_sec)
    except (TypeError, ValueError):
        frame_period_sec = 0.0
    warmup_duration_sec = warmup_frames * frame_period_sec if frame_period_sec > 0 else 0.0
    if warmup_duration_sec and float(duration_sec) < warmup_duration_sec:
        diagnostics.append(
            f"point_cloud_replay_window_short_for_warmup:{float(duration_sec):g}:{warmup_duration_sec:g}"
        )

    contract = _mapping(input_contract)
    inventory = _mapping(topic_inventory)
    injection_audit = build_perception_injection_audit(
        preflight=preflight,
        target_usage=_mapping(contract.get("target_usage")),
    )
    contract_status = str(contract.get("status", "blocked")) if contract else "not_available"
    gates.append({
        "id": "point_cloud_input_contract",
        "status": "passed" if contract_status == "ready" else "blocked" if contract_status in {"blocked", "not_available"} else "partial",
        "observed": {"status": contract_status, "point_count": contract.get("point_count", 0)},
        "reason": "the selected input must be auditable before a point-cloud replay can run",
    })
    if not contract:
        diagnostics.append("point_cloud_input_contract_missing")
    elif contract_status != "ready":
        diagnostics.append("point_cloud_input_contract_blocked")
    layout_status = str(contract.get("layout_status", "not_available"))
    layout_binding = _mapping(contract.get("layout_binding"))
    contract_schema = _mapping(contract.get("message_schema"))
    contract_schema_rows = [contract_schema]
    nested_contract_schemas = contract_schema.get("schemas")
    if isinstance(nested_contract_schemas, Sequence) and not isinstance(nested_contract_schemas, (str, bytes, bytearray)):
        contract_schema_rows.extend(_mapping(item) for item in nested_contract_schemas if isinstance(item, Mapping))
    schema_declares_binary_layout = bool(layout_binding.get("required")) or any(
        "perinfoutstruct.dottrans" in str(row.get("payload") or "").lower()
        or "dottrans" in str(row.get("type") or "").lower()
        or str(row.get("type") or "").lower() in {"arbe_msgs/wfautosardata", "arbe_msgs_rvizbag/wfautosardata"}
        for row in contract_schema_rows
    )
    if schema_declares_binary_layout and (layout_status != "verified" or layout_binding.get("status") != "verified"):
        diagnostics.append("point_cloud_input_layout_unverified")
        gates.append({
            "id": "point_cloud_input_layout",
            "status": "blocked",
            "observed": {"layout_status": layout_status, "layout_binding": dict(layout_binding), "message_schema": contract.get("message_schema")},
            "reason": "point-cloud input bytes and their recording version must be bound to the active source layout before replay",
        })
    target_info = _mapping(contract.get("target_usage"))
    if target_info.get("injection_detected") is True:
        diagnostics.append("recorded_target_injection_detected")
        gates.append({
            "id": "recorded_target_injection_absent",
            "status": "blocked",
            "observed": target_info,
            "reason": "point-cloud replay cannot claim perception provenance when target injection is active",
        })
    inventory_rows = inventory.get("topics") if isinstance(inventory.get("topics"), Sequence) and not isinstance(inventory.get("topics"), (str, bytes, bytearray)) else []
    input_inventory_row = next((row for row in inventory_rows if isinstance(row, Mapping) and str(row.get("topic")) == str(point_cloud_topic)), None)
    if inventory:
        if input_inventory_row is None or str(input_inventory_row.get("status")) in {"not_found", "failed"}:
            inventory_gate_status = "blocked"
            diagnostics.append("point_cloud_ros_input_topic_not_observed")
        elif not input_inventory_row.get("publisher_count") or not input_inventory_row.get("subscriber_count"):
            inventory_gate_status = "partial"
        elif input_inventory_row.get("message_observable") is False:
            inventory_gate_status = "partial"
        else:
            inventory_gate_status = "passed"
        gates.append({
            "id": "ros_input_topic_contract",
            "status": inventory_gate_status,
            "observed": dict(input_inventory_row or {}),
            "reason": "point-cloud input topic must be observed with publisher and subscriber before execution",
        })
    injection_state = injection_audit.get("injection_enabled")
    if injection_state is True:
        diagnostics.append("injection_macro_or_target_usage_enabled")
        injection_gate_status = "blocked"
    elif injection_state is False:
        injection_gate_status = "passed"
    else:
        diagnostics.append("injection_state_unavailable")
        injection_gate_status = "blocked"
    gates.append({
        "id": "injection_audit",
        "status": injection_gate_status,
        "observed": injection_audit,
        "reason": "point-cloud replay requires an explicit absent-injection observation",
    })

    hilmodel = _get_preflight_macro(preflight, "HILMODEL")
    buildmodel = _get_preflight_macro(preflight, "BUILDMODEL")
    if hilmodel != "0":
        diagnostics.append(
            "point_cloud_requires_hilmodel_0_current=" + (hilmodel or "not_available")
        )
    gates.append({
        "id": "source_build_point_cloud_mode",
        "status": "passed" if hilmodel == "0" else "blocked",
        "observed": {"HILMODEL": hilmodel, "BUILDMODEL": buildmodel},
        "reason": "post-detection perception stages are compiled only in the HILMODEL=0 branch",
    })
    runtime_binding = _audit_runtime_workspace_alignment(preflight)
    gates.append({
        "id": "runtime_workspace_alignment",
        "status": "blocked" if runtime_binding.get("status") == "conflict" else "passed" if runtime_binding.get("status") == "aligned" else "not_available",
        "observed": runtime_binding,
        "reason": "runtime processes must belong to the planned workspace before point-cloud execution",
    })
    if runtime_binding.get("status") == "conflict":
        diagnostics.extend(str(item) for item in runtime_binding.get("diagnostics", []) or [])
    elif runtime_binding.get("workspace_root") and runtime_binding.get("status") != "aligned":
        diagnostics.extend(str(item) for item in runtime_binding.get("diagnostics", []) or [])
        diagnostics.append("runtime_workspace_alignment_required_for_existing_session")

    binary = derived_identity.get("binary_fingerprint")
    source_id = derived_identity.get("source_context_id")
    data_id = derived_identity.get("data_fingerprint")
    for key, value in (
        ("binary_fingerprint", binary),
        ("source_context_id", source_id),
        ("data_fingerprint", data_id),
        ("config_fingerprint", derived_identity.get("config_fingerprint")),
        ("session_id", derived_identity.get("session_id")),
    ):
        gates.append({
            "id": key,
            "status": "passed" if value not in (None, "") else "blocked",
            "value": value,
            "reason": "identity must be bound before replay",
        })
        if value in (None, ""):
            diagnostics.append(key + "_missing")

    status = "ready" if not diagnostics and hilmodel == "0" and contract_status == "ready" and (layout_status == "verified" or not schema_declares_binary_layout) else "blocked"
    plan = {
        "schema_version": PLAN_SCHEMA,
        "status": status,
        "mode": "point_cloud",
        "run_id": str(run_id or ""),
        "target": {
            "server": {"host": str(server_host), "user": str(server_user), "port": int(server_port)},
            "remote_bag_path": str(remote_bag_path),
            "point_cloud_topic": str(point_cloud_topic),
            "output_topics": output_topics,
            "start_sec": float(start_sec),
            "duration_sec": float(duration_sec),
            "frame_period_sec": frame_period_sec,
            "warmup_duration_sec": warmup_duration_sec,
            "remote_capture_base": str(remote_capture_base),
        },
        "execution_plan": {
            "server": {"host": str(server_host), "user": str(server_user), "port": int(server_port)},
            "remote_bag_path": str(remote_bag_path),
            "remote_capture_base": str(remote_capture_base),
            "start_sec": float(start_sec),
            "duration_sec": float(duration_sec),
            "frame_period_sec": frame_period_sec,
            "warmup_duration_sec": warmup_duration_sec,
            "input_topics": input_topics,
            "output_topics": output_topics,
            "ros_setup": str(ros_setup),
            "workspace_setup": str(workspace_setup),
            "ros_master_uri": str(ros_master_uri),
            "strategy": "point_cloud",
            "warmup_frames": warmup_frames,
        },
        "strategy": {
            "name": "point_cloud",
            "warmup_frames_requested": warmup_frames,
            "warmup_range": [150, 200],
            "warmup_candidates": [150, 175, 200],
            "warmup_sensitivity_required": True,
            "frame_period_sec": frame_period_sec,
            "warmup_duration_sec": warmup_duration_sec,
            "reset_required": True,
            "completion_ack_required": True,
        },
        "identity": {
            "data_fingerprint": data_id,
            "source_context_id": source_id,
            "binary_fingerprint": binary,
            "config_fingerprint": derived_identity.get("config_fingerprint", ""),
            "session_id": derived_identity.get("session_id", ""),
            "provenance": identity_provenance,
            "preflight_schema": preflight.get("schema_version"),
        },
        "runtime_binding": runtime_binding,
        "topic_inventory": dict(inventory),
        "stage_map": dict(stage_map or {}),
        "input_contract_ref": {
            "schema_version": contract.get("schema_version", ""),
            "status": contract.get("status", "not_available"),
            "data_fingerprint": contract.get("data_fingerprint", ""),
            "layout_status": contract.get("layout_status", "not_available"),
        } if contract else {},
        "injection_audit": injection_audit,
        "stage_names": list(STAGE_NAMES),
        "gates": gates,
        "diagnostics": diagnostics,
    }
    plan["plan_hash"] = _hash(plan)
    return plan


def normalize_point_rows(
    rows: Sequence[Mapping[str, Any]] | None,
    *,
    source: str = "point_cloud_capture",
) -> list[dict[str, Any]]:
    """Normalize point aliases while preserving raw fields and provenance."""
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(rows or []):
        if not isinstance(raw, Mapping):
            continue
        row = dict(raw)
        def first(*keys: str) -> Any:
            for key in keys:
                if row.get(key) not in (None, ""):
                    return row[key]
            return None
        values: dict[str, Any] = {
            "point_key": str(first("point_key", "id") or f"{source}:{index}"),
            "source_index": index,
            "frame_id": first("frame_id", "frameID", "frame_counter", "frameCounter"),
            "radar_id": first("radar_id", "radar", "radarId"),
            "range": first("range", "dist", "distance"),
            "azimuth": first("azimuth", "ang", "angle", "theta"),
            "elevation": first("elevation", "phi"),
            "doppler": first("doppler", "vel", "radial_velocity", "velocity"),
            "power": first("power", "signal", "sig"),
            "snr": first("snr"),
            "noise": first("noise", "noi"),
            "rcs": first("rcs", "rcs_est", "Rcs"),
            "quality": first("quality", "thetaQly", "phiQly", "dvQly"),
        }
        non_finite: dict[str, Any] = {}
        safe_values: dict[str, Any] = {}
        for key, value in values.items():
            safe, marker = _safe_value(value)
            safe_values[key] = safe
            if marker:
                non_finite[key] = marker
        source_status = str(row.get("status") or "observed")
        normalized_status = (
            "partial"
            if source_status in {"partial", "not_available"} or "warning" in source_status
            else source_status
        )
        normalized.append({
            **safe_values,
            "status": normalized_status,
            "source_status": source_status,
            "source": source,
            "raw": _safe_tree(row),
            "field_status": non_finite,
        })
    return normalized


def audit_perception_capture(capture: Mapping[str, Any] | None) -> dict[str, Any]:
    """Audit a decoded capture by payload shape, never by topic name.

    A capture producer may expose point/cluster/track/object rows under the
    conventional keys below.  Unknown keys are retained as opaque metadata;
    an object/target list alone is explicitly not accepted as point-cloud
    input evidence.
    """
    payload = _mapping(capture)
    known = {
        "point_cloud": ("point_rows", "points", "dot_rows"),
        "clusters": ("cluster_rows", "clusters"),
        "tracks": ("track_rows", "tracks"),
        "outputs": ("output_rows", "outputs"),
        "targets": ("target_rows", "object_rows", "objects"),
    }
    stage_names_by_payload = {
        "point_cloud": {"point_cloud"},
        "clusters": {"cluster"},
        "tracks": {"track"},
        "outputs": {"track_output", "track"},
        "targets": {"target", "track"},
    }
    stage_rows = [dict(row) for row in payload.get("stage_evidence", []) or [] if isinstance(row, Mapping)]
    summary: dict[str, Any] = {}
    for kind, keys in known.items():
        for key in keys:
            value = payload.get(key)
            if isinstance(value, Mapping):
                count = 1
            elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
                count = len(value)
            else:
                continue
            if count > 0:
                summary[kind] = {"source_key": key, "row_count": count, "status": "observed"}
            else:
                observed_empty_messages = [
                    row for row in stage_rows
                    if str(row.get("stage") or "") in stage_names_by_payload[kind]
                    and str(row.get("runtime_proof") or "") in {"observed", "completed"}
                    and str(_mapping(row.get("source_ref")).get("message_seq") or "")
                ]
                if observed_empty_messages:
                    summary[kind] = {
                        "source_key": key,
                        "row_count": 0,
                        "status": "observed_empty",
                        "message_count": len(observed_empty_messages),
                    }
                else:
                    continue
            break
    diagnostics: list[str] = []
    point_payload = summary.get("point_cloud") or {}
    if str(point_payload.get("status") or "") == "observed_empty":
        diagnostics.append("point_cloud_payload_empty")
    elif "point_cloud" not in summary:
        diagnostics.append("point_cloud_payload_missing")
        if "targets" in summary:
            diagnostics.append("target_or_object_rows_only_not_point_cloud_input")
    point_count = int(point_payload.get("row_count") or 0)
    return {
        "schema_version": "perception-input-audit.v1",
        "status": "ready" if point_count > 0 else "blocked",
        "payloads": summary,
        "message_schema": dict(payload.get("message_schema")) if isinstance(payload.get("message_schema"), Mapping) else {"status": "not_available"},
        "topics": [],
        "topic_names_used_for_classification": False,
        "diagnostics": diagnostics,
    }


def build_perception_input_contract(
    points: Sequence[Mapping[str, Any]] | None,
    *,
    source_context: Mapping[str, Any] | None = None,
    strategy: str = "point_cloud",
    message_schema: Mapping[str, Any] | None = None,
    target_rows: Sequence[Mapping[str, Any]] | None = None,
    target_usage: Mapping[str, Any] | None = None,
    conversion: Mapping[str, Any] | None = None,
    payload_audit: Mapping[str, Any] | None = None,
    artifact_audit: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Audit point-cloud completeness without filling missing fields."""
    normalized = normalize_point_rows(points)
    required = ("range", "azimuth", "doppler")
    field_names = (
        "range", "azimuth", "elevation", "doppler", "power", "snr", "noise", "rcs", "quality"
    )
    counts = {key: sum(row.get(key) not in (None, "") for row in normalized) for key in field_names}
    missing_required = [key for key in required if not counts.get(key)]
    status = "ready" if normalized and not missing_required else "partial" if normalized else "blocked"
    partial_point_count = sum(1 for row in normalized if str(row.get("status") or "") != "observed")
    if partial_point_count and status == "ready":
        status = "partial"
    by_radar: dict[str, list[dict[str, Any]]] = {}
    for row in normalized:
        radar = str(row.get("radar_id") if row.get("radar_id") not in (None, "") else "unknown")
        by_radar.setdefault(radar, []).append(row)
    radar_summary = []
    for radar, radar_rows in sorted(by_radar.items()):
        radar_counts = {key: sum(item.get(key) not in (None, "") for item in radar_rows) for key in field_names}
        radar_missing = [key for key in required if not radar_counts.get(key)]
        radar_summary.append({
            "radar_id": radar,
            "point_count": len(radar_rows),
            "frame_ids": sorted({str(item.get("frame_id")) for item in radar_rows if item.get("frame_id") not in (None, "")}),
            "field_counts": radar_counts,
            "missing_required_fields": radar_missing,
            "status": "ready" if not radar_missing else "partial",
        })
    if status == "ready" and any(item["status"] != "ready" for item in radar_summary):
        status = "partial"
    explicit_target_usage = dict(target_usage) if isinstance(target_usage, Mapping) else {}
    if not explicit_target_usage:
        explicit_target_usage = {
            "status": "observed" if target_rows else "not_available",
            "target_row_count": len(target_rows or []),
            "basis": "explicit_target_rows" if target_rows else "not_supplied",
        }
    else:
        explicit_target_usage.setdefault("status", "not_available")
        explicit_target_usage.setdefault("basis", "explicit_metadata")
    source_meta = _mapping(source_context)
    source_context_conflicts = [
        str(item) for item in source_meta.get("identity_conflicts", []) or [] if str(item).strip()
    ]
    payload_audit_obj = _mapping(payload_audit)
    schema_meta = (
        dict(message_schema)
        if isinstance(message_schema, Mapping)
        else dict(payload_audit_obj.get("message_schema"))
        if isinstance(payload_audit_obj.get("message_schema"), Mapping)
        else {}
    )
    audited_payloads = _mapping(payload_audit_obj.get("payloads"))
    if normalized:
        input_boundary = "public_stage_point_cloud_observation" if str(schema_meta.get("status", "")) == "multiple" else "post_detection_point_cloud"
    elif str(_mapping(audited_payloads.get("point_cloud")).get("status") or "") == "observed_empty":
        input_boundary = "empty_public_pointcloud_observation"
    elif strategy == "sgu_injection" or bool(explicit_target_usage.get("injection_detected")):
        input_boundary = "target_injection_only"
    elif target_rows or _int_or_default(explicit_target_usage.get("target_row_count"), 0) > 0 or "targets" in audited_payloads:
        input_boundary = "target_only"
    else:
        input_boundary = "not_available"
    schema_rows = [schema_meta]
    nested_schemas = schema_meta.get("schemas")
    if isinstance(nested_schemas, Sequence) and not isinstance(nested_schemas, (str, bytes, bytearray)):
        schema_rows.extend(dict(item) for item in nested_schemas if isinstance(item, Mapping))
    raw_payload_required = any(
        "perinfoutstruct.dottrans" in str(row.get("payload") or "").lower()
        or "dottrans" in str(row.get("type") or "").lower()
        or str(row.get("type") or "").lower() in {"arbe_msgs/wfautosardata", "arbe_msgs_rvizbag/wfautosardata"}
        for row in schema_rows
    ) or any(
        str(_mapping(row.get("source_ref")).get("raw_token") or row.get("source") or "").lower()
        == "perinfoutstruct.dottrans"
        for row in normalized
    )
    pointcloud2_self_describing = any(
        str(row.get("type") or "").lower() == "sensor_msgs/pointcloud2"
        for row in schema_rows
    ) or any(
        str(_mapping(row.get("source_ref")).get("topic_type") or "").lower() == "sensor_msgs/pointcloud2"
        and _mapping(row.get("source_ref")).get("point_step") not in (None, "")
        and _mapping(row.get("source_ref")).get("row_step") not in (None, "")
        for row in normalized
    )
    layout_meta = schema_meta.get("layout_profile") if isinstance(schema_meta.get("layout_profile"), Mapping) else None
    if layout_meta is None:
        layout_meta = next(
            (_mapping(row.get("layout_profile")) for row in schema_rows if isinstance(row.get("layout_profile"), Mapping)),
            None,
        )
    if layout_meta is None and isinstance(source_meta.get("layout_profile"), Mapping):
        layout_meta = _mapping(source_meta.get("layout_profile"))
    active_snapshot = _mapping(source_meta.get("source_snapshot"))
    active_source_hash = str(
        source_meta.get("source_snapshot_hash")
        or active_snapshot.get("source_snapshot_hash")
        or source_meta.get("source_context_id")
        or source_meta.get("source_context_fingerprint")
        or ""
    ).strip()
    profile_source_hash = str(_mapping(layout_meta).get("source_snapshot_hash") or "").strip()
    profile_source_verified = bool(_mapping(layout_meta).get("verified")) and bool(profile_source_hash)
    if raw_payload_required:
        if profile_source_hash and active_source_hash and profile_source_hash != active_source_hash:
            source_layout_status = "conflict"
        elif profile_source_verified and active_source_hash and profile_source_hash == active_source_hash:
            source_layout_status = "verified"
        else:
            source_layout_status = "unverified"
    else:
        source_layout_status = "not_required"

    artifact_audit_obj = _mapping(artifact_audit)
    artifact_sha = str(artifact_audit_obj.get("sha256") or "").strip()
    source_data_fingerprint = str(source_meta.get("data_fingerprint") or "").strip()
    source_data_binding = _mapping(
        schema_meta.get("source_data_binding")
        or source_meta.get("source_data_binding")
        or artifact_audit_obj.get("source_data_binding")
    )
    bound_source_fingerprint = str(
        source_data_binding.get("source_data_fingerprint")
        or source_data_binding.get("data_fingerprint")
        or ""
    ).strip()
    bound_artifact_fingerprint = str(
        source_data_binding.get("artifact_sha256")
        or source_data_binding.get("artifact_fingerprint")
        or ""
    ).strip()
    source_binding_ref = str(
        source_data_binding.get("evidence_ref")
        or source_data_binding.get("source_ref")
        or ""
    ).strip()
    source_binding_status = str(source_data_binding.get("status") or "").strip()
    source_binding_evidence_sha = str(
        source_data_binding.get("evidence_sha256")
        or source_data_binding.get("compatibility_evidence_sha256")
        or ""
    ).strip()
    if not raw_payload_required:
        data_binding_status = "not_required"
    elif source_binding_status == "conflict":
        data_binding_status = "conflict"
    elif artifact_sha and source_data_fingerprint and artifact_sha == source_data_fingerprint:
        data_binding_status = "aligned"
    elif (
        source_binding_status in {"derived_bound", "verified"}
        and artifact_sha
        and source_data_fingerprint
        and bound_source_fingerprint == source_data_fingerprint
        and bound_artifact_fingerprint == artifact_sha
        and source_binding_ref
        and _local_file_matches_sha256(source_binding_ref, source_binding_evidence_sha)
    ):
        data_binding_status = "derived_bound"
    elif artifact_sha and source_data_fingerprint:
        data_binding_status = "conflict"
    else:
        data_binding_status = "not_available"

    recording_compatibility = _mapping(_mapping(layout_meta).get("recording_compatibility"))
    if not recording_compatibility:
        recording_compatibility = _mapping(schema_meta.get("recording_compatibility"))
    if not recording_compatibility:
        recording_compatibility = next(
            (_mapping(row.get("recording_compatibility")) for row in schema_rows if isinstance(row.get("recording_compatibility"), Mapping)),
            {},
        )
    compatibility_status = str(recording_compatibility.get("status") or "not_available")
    compatibility_recording_fingerprint = str(
        recording_compatibility.get("recording_fingerprint")
        or recording_compatibility.get("artifact_sha256")
        or ""
    ).strip()
    compatibility_source_hash = str(recording_compatibility.get("source_snapshot_hash") or "").strip()
    compatibility_ref = str(
        recording_compatibility.get("compatibility_evidence_ref")
        or recording_compatibility.get("evidence_ref")
        or ""
    ).strip()
    compatibility_evidence_sha = str(
        recording_compatibility.get("compatibility_evidence_sha256")
        or recording_compatibility.get("evidence_sha256")
        or ""
    ).strip()
    recording_version = str(
        recording_compatibility.get("recording_version")
        or recording_compatibility.get("recording_source_fingerprint")
        or recording_compatibility.get("producer_binary_fingerprint")
        or ""
    ).strip()
    layout_diagnostics: list[str] = []
    if not raw_payload_required:
        layout_status = "self_describing" if pointcloud2_self_describing else "not_required"
    elif source_layout_status == "conflict" or data_binding_status == "conflict":
        layout_status = "conflict"
        layout_diagnostics.append("input_layout_identity_conflict")
    elif source_layout_status != "verified":
        layout_status = "unverified"
        layout_diagnostics.append("input_layout_profile_unverified")
    elif (
        compatibility_status == "verified"
        and artifact_sha
        and compatibility_recording_fingerprint == artifact_sha
        and compatibility_source_hash == profile_source_hash
        and recording_version
        and compatibility_ref
        and _local_file_matches_sha256(compatibility_ref, compatibility_evidence_sha)
        and data_binding_status in {"aligned", "derived_bound"}
    ):
        layout_status = "verified"
    else:
        layout_status = "recording_version_unbound"
        layout_diagnostics.append("input_recording_version_unbound")
    if source_context_conflicts:
        layout_status = "conflict"
        data_binding_status = "conflict"
        layout_diagnostics.append("source_context_identity_conflict")
    layout_binding = {
        "status": layout_status,
        "required": raw_payload_required,
        "source_layout_status": source_layout_status,
        "source_snapshot_hash": profile_source_hash,
        "active_source_snapshot_hash": active_source_hash,
        "data_binding_status": data_binding_status,
        "recording_fingerprint": artifact_sha,
        "source_data_fingerprint": source_data_fingerprint,
        "recording_compatibility_status": compatibility_status,
        "recording_version": recording_version,
        "compatibility_evidence_ref": compatibility_ref,
        "compatibility_evidence_sha256": compatibility_evidence_sha,
        "source_data_binding_evidence_sha256": source_binding_evidence_sha,
        "diagnostics": layout_diagnostics,
    }
    if (raw_payload_required and layout_status != "verified" or source_context_conflicts) and status == "ready":
        status = "partial"
    losses = {
        "missing_required_fields": list(missing_required),
        "missing_optional_fields": [key for key in field_names if not counts.get(key) and key not in required],
        "non_finite_fields": sorted({key for row in normalized for key in (row.get("field_status") or {})}),
        "partial_point_count": partial_point_count,
    }
    return {
        "schema_version": CONTRACT_SCHEMA,
        "status": status,
        "strategy": strategy,
        "input_boundary": input_boundary,
        "raw_sensor_frontend": "not_available",
        "point_count": len(normalized),
        "field_counts": counts,
        "required_fields": list(required),
        "missing_required_fields": missing_required,
        "data_fingerprint": _mapping(source_context).get("data_fingerprint"),
        "source_context_id": _mapping(source_context).get("source_context_id") or _mapping(source_context).get("source_context_fingerprint"),
        "source_context_binding": {
            "status": "conflict" if source_context_conflicts else str(source_meta.get("source_context_binding_status") or "not_available"),
            "conflicts": source_context_conflicts,
            "conflict_sources": [dict(item) for item in source_meta.get("identity_conflict_sources", []) or [] if isinstance(item, Mapping)],
        },
        "points": normalized,
        "radar_summary": radar_summary,
        "message_schema": schema_meta or {"status": "not_available"},
        "layout_status": layout_status,
        "layout_binding": layout_binding,
        "target_usage": explicit_target_usage,
        "conversion": dict(conversion or {"status": "not_available"}),
        "losses": losses,
        "supported_paths": {
            "point_cloud": "ready" if status == "ready" else "partial",
            "raw_sensor_frontend": "not_available",
            "sgu_injection": "separate_strategy" if strategy == "point_cloud" else "selected",
        },
        "payload_audit": dict(payload_audit or {}),
        "artifact_audit": dict(artifact_audit or {}),
        "limitations": [
            "point cloud input does not prove ADC/FFT/CFAR execution",
            "missing fields remain unavailable and are not replaced with zero",
            "topic names alone do not establish a point-cloud or target-injection path",
        ],
        "diagnostics": layout_diagnostics + (["input_point_rows_partial"] if partial_point_count else []),
    }


def build_stage_coverage(
    stage_evidence: Sequence[Mapping[str, Any]] | None = None,
    *,
    stage_map: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Project stage evidence into a stable coverage table."""
    rows = [dict(item) for item in (stage_evidence or []) if isinstance(item, Mapping)]
    normalized_rows: list[dict[str, Any]] = []
    for row in rows:
        stage = str(row.get("stage") or "")
        if not stage:
            continue
        frame_id = row.get("frame_id", row.get("frameID"))
        frame_domain = str(row.get("frame_domain") or row.get("domain") or "")
        epoch = row.get("epoch")
        frame_key = row.get("frame_key")
        if frame_key in (None, "") and frame_id not in (None, ""):
            frame_key = ":".join(item for item in (frame_domain, str(epoch) if epoch not in (None, "") else "", str(frame_id)) if item)
        status = str(row.get("status") or "not_available")
        # A status such as ``completed`` can be emitted by a parser or a
        # planned fixture.  Runtime provenance must be an explicit producer
        # assertion; never infer it from a generic status/count.
        runtime_proof = str(row.get("runtime_proof") or "not_available")
        normalized_rows.append({
            **row,
            "stage": stage,
            "frame_id": frame_id,
            "frame_domain": frame_domain,
            "epoch": epoch,
            "frame_key": frame_key or "",
            "status": status,
            "runtime_proof": runtime_proof,
            "truncated": bool(row.get("truncated", False)),
            "artifact_refs": list(row.get("artifact_refs", []) or []) if isinstance(row.get("artifact_refs", []), Sequence) and not isinstance(row.get("artifact_refs", []), (str, bytes, bytearray)) else [],
        })
    rows = normalized_rows
    by_stage: dict[str, list[dict[str, Any]]] = {}
    for item in rows:
        by_stage.setdefault(str(item.get("stage")), []).append(item)
    stage_map_rows = _mapping(stage_map).get("stages") if isinstance(_mapping(stage_map).get("stages"), Mapping) else _mapping(stage_map)
    result: list[dict[str, Any]] = []
    for stage in STAGE_NAMES:
        source = stage_map_rows.get(stage)
        if isinstance(source, Sequence) and not isinstance(source, (str, bytes, bytearray)):
            source = source[0] if source else None
        stage_rows = by_stage.get(stage, [])
        row = dict(stage_rows[-1]) if stage_rows else {}
        source_status = source.get("status") if isinstance(source, Mapping) else None
        input_count = sum(item.get("input_count", 0) for item in stage_rows if isinstance(item.get("input_count"), (int, float))) if stage_rows else row.get("input_count")
        output_count = sum(item.get("output_count", 0) for item in stage_rows if isinstance(item.get("output_count"), (int, float))) if stage_rows else row.get("output_count")
        frame_keys = list(dict.fromkeys(str(item.get("frame_key")) for item in stage_rows if item.get("frame_key") not in (None, "")))
        stage_status = str(row.get("status") or source_status or "not_available")
        stage_runtime = row.get("runtime_proof", "not_available") if row else "not_available"
        if stage_rows and any(str(item.get("status")) in {"observed", "completed", "partial"} for item in stage_rows):
            stage_status = "partial" if any(str(item.get("status")) == "partial" for item in stage_rows) else "completed" if all(str(item.get("status")) == "completed" for item in stage_rows) else "observed"
        if stage_rows and any(str(item.get("runtime_proof")) in {"observed", "completed"} for item in stage_rows):
            stage_runtime = "observed"
        result.append({
            "stage": stage,
            "status": stage_status,
            "input_count": input_count,
            "output_count": output_count,
            "frames": frame_keys or row.get("frames", []),
            "frame_count": len(frame_keys),
            "evidence_rows": stage_rows,
            "truncated": any(bool(item.get("truncated")) for item in stage_rows),
            "source_ref": row.get("source_ref") or (source if isinstance(source, Mapping) else None),
            "runtime_proof": stage_runtime,
            "diagnostics": row.get("diagnostics", []),
        })
    # Only a completed row with explicit runtime proof is an available stage.
    # Static source candidates and partial parser rows remain visible but do
    # not satisfy the replay coverage gate.
    available = sum(
        row["status"] == "completed"
        and str(row.get("runtime_proof")) in {"observed", "completed"}
        for row in result
    )
    observed_partial = sum(
        str(row.get("runtime_proof")) in {"observed", "completed"}
        and row["status"] in {"observed", "partial"}
        for row in result
    )
    return {
        "schema_version": "perception-stage-evidence.v1",
        "status": "ready" if available == len(result) else "partial" if available else "not_available",
        "stages": result,
        "available_stage_count": available,
        "observed_partial_stage_count": observed_partial,
        "derived_stage_count": sum(1 for row in result if str(row.get("runtime_proof")) == "derived"),
        "total_stage_count": len(result),
    }


def build_perception_lineage(
    *,
    edges: Sequence[Mapping[str, Any]] | None = None,
    points: Sequence[Mapping[str, Any]] | None = None,
    clusters: Sequence[Mapping[str, Any]] | None = None,
    tracks: Sequence[Mapping[str, Any]] | None = None,
    outputs: Sequence[Mapping[str, Any]] | None = None,
    track_population: Mapping[str, Any] | None = None,
    relation_scopes: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an explicit point→cluster→track→output graph; never guess edges."""
    edge_rows = [_safe_evidence_row(item) for item in (edges or []) if isinstance(item, Mapping)]
    nodes = {
        "points": [_safe_evidence_row(item) for item in (points or []) if isinstance(item, Mapping)],
        "clusters": [_safe_evidence_row(item) for item in (clusters or []) if isinstance(item, Mapping)],
        "tracks": [_safe_evidence_row(item) for item in (tracks or []) if isinstance(item, Mapping)],
        "outputs": [_safe_evidence_row(item) for item in (outputs or []) if isinstance(item, Mapping)],
    }
    node_ids = {
        "point": {str(item.get("point_key") or item.get("id")) for item in nodes["points"] if item.get("point_key") not in (None, "") or item.get("id") not in (None, "")},
        "cluster": {str(item.get("cluster_id") or item.get("id")) for item in nodes["clusters"] if item.get("cluster_id") not in (None, "") or item.get("id") not in (None, "")},
        "track": {str(item.get("track_key") or item.get("track_id") or item.get("id")) for item in nodes["tracks"] if item.get("track_key") not in (None, "") or item.get("track_id") not in (None, "") or item.get("id") not in (None, "")},
        "output": {str(item.get("output_key") or item.get("object_id") or item.get("id")) for item in nodes["outputs"] if item.get("output_key") not in (None, "") or item.get("object_id") not in (None, "") or item.get("id") not in (None, "")},
    }
    kind_types = {
        "point_supports_cluster": ("point", "cluster"),
        "cluster_supports_track": ("cluster", "track"),
        "track_emits_output": ("track", "output"),
        "point_rejected_by_filter": ("point", "point"),
        "track_matches_previous": ("track", "track"),
        "cluster_splits": ("cluster", "cluster"),
        "cluster_merges": ("cluster", "cluster"),
    }
    node_kind_labels = {"point": "points", "cluster": "clusters", "track": "tracks", "output": "outputs"}
    valid_edges: list[dict[str, Any]] = []
    invalid_edges: list[dict[str, Any]] = []
    seen_cluster_track_pairs: set[tuple[str, str]] = set()
    for edge in edge_rows:
        item = dict(edge)
        kind = str(item.get("relation_kind") or item.get("kind") or "")
        from_key = str(item.get("from") or item.get("source") or "")
        to_key = str(item.get("to") or item.get("target") or "")
        expected = kind_types.get(kind)
        valid = bool(expected and from_key and to_key and from_key in node_ids[expected[0]] and to_key in node_ids[expected[1]])
        if valid:
            item.setdefault("from_node_kind", node_kind_labels[expected[0]])
            item.setdefault("to_node_kind", node_kind_labels[expected[1]])
            if kind == "cluster_supports_track":
                # This is a graph relation, not one row per supporting point.
                # Keep raw multiplicity in raw_edges; canonical edges are unique by cluster/track identity.
                relation_key = (from_key, to_key)
                if relation_key in seen_cluster_track_pairs:
                    continue
                seen_cluster_track_pairs.add(relation_key)
            item.setdefault("status", "observed")
            valid_edges.append(item)
        else:
            item["status"] = "not_available"
            item["validation"] = "node_or_relation_unresolved"
            invalid_edges.append(item)
    kinds = {str(item.get("relation_kind") or item.get("kind") or "") for item in valid_edges}
    relation_counts: dict[str, int] = {}
    for edge in valid_edges:
        relation_kind = str(edge.get("relation_kind") or edge.get("kind") or "")
        if relation_kind:
            relation_counts[relation_kind] = relation_counts.get(relation_kind, 0) + 1
    raw_relation_counts: dict[str, int] = {}
    for edge in edge_rows:
        relation_kind = str(edge.get("relation_kind") or edge.get("kind") or "")
        if relation_kind:
            raw_relation_counts[relation_kind] = raw_relation_counts.get(relation_kind, 0) + 1
    relation_summaries: dict[str, dict[str, int]] = {}
    for relation_kind in sorted({str(item.get("relation_kind") or item.get("kind") or "") for item in valid_edges} - {""}):
        relation_rows = [item for item in valid_edges if str(item.get("relation_kind") or item.get("kind") or "") == relation_kind]
        relation_summaries[relation_kind] = {
            "from_node_kind": str(relation_rows[0].get("from_node_kind") or "not_available"),
            "to_node_kind": str(relation_rows[0].get("to_node_kind") or "not_available"),
            "edge_row_count": len(relation_rows),
            "unique_pair_count": len({(str(item.get("from") or item.get("source") or ""), str(item.get("to") or item.get("target") or "")) for item in relation_rows}),
            "unique_from_node_count": len({str(item.get("from") or item.get("source") or "") for item in relation_rows}),
            "unique_to_node_count": len({str(item.get("to") or item.get("target") or "") for item in relation_rows}),
        }
    identity_warnings: list[str] = []
    track_frames: dict[str, set[str]] = {}
    for track in nodes["tracks"]:
        track_id = track.get("track_key", track.get("track_id", track.get("id")))
        frame = _frame_key(track)
        if track_id not in (None, "") and frame:
            track_frames.setdefault(str(track_id), set()).add(frame)
    for track_id, frames in track_frames.items():
        if len(frames) > 1 and not any(
            track.get("tracker_instance") not in (None, "") or track.get("birth_frame") not in (None, "")
            for track in nodes["tracks"] if str(track.get("track_key", track.get("track_id", track.get("id", "")))) == track_id
        ):
            identity_warnings.append(f"track_id_reused_without_identity_basis:{track_id}")
    return {
        "schema_version": "perception-lineage.v1",
        "status": (
            "observed" if any(str(item.get("status")) == "observed" for item in valid_edges)
            else "derived" if valid_edges
            else "not_available"
        ),
        "nodes": nodes,
        "node_counts": {kind: len(rows) for kind, rows in nodes.items()},
        "edges": valid_edges,
        "raw_edges": edge_rows,
        "invalid_edges": invalid_edges,
        "edge_count": len(valid_edges),
        "raw_edge_count": len(edge_rows),
        "invalid_edge_count": len(invalid_edges),
        "relation_kinds": sorted(item for item in kinds if item),
        "relation_counts": relation_counts,
        "raw_relation_counts": raw_relation_counts,
        "relation_summaries": relation_summaries,
        **({"track_population": dict(track_population)} if track_population else {}),
        **({"relation_scopes": dict(relation_scopes)} if relation_scopes else {}),
        "identity_warnings": identity_warnings,
        "limitations": [] if valid_edges else ["no valid explicit lineage edges were supplied; no point-to-track relation was inferred"],
    }


def build_perception_analysis(
    *,
    input_contract: Mapping[str, Any],
    stage_coverage: Mapping[str, Any],
    lineage: Mapping[str, Any],
    source_context: Mapping[str, Any] | None = None,
    code_flow: Mapping[str, Any] | None = None,
    problem: str = "",
    run_evidence: Mapping[str, Any] | None = None,
    comparison: Mapping[str, Any] | None = None,
    scene: Mapping[str, Any] | None = None,
    timeline: Mapping[str, Any] | None = None,
    warmup_analysis: Mapping[str, Any] | None = None,
    hypothesis_set: Mapping[str, Any] | None = None,
    capability_manifest: Mapping[str, Any] | None = None,
    source_execution_contract: Mapping[str, Any] | None = None,
    callback_binding_summary: Mapping[str, Any] | None = None,
    callback_bindings: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Compose a bounded analysis read model for Pi/report consumers."""
    input_status = str(input_contract.get("status", "blocked"))
    stage_status = str(stage_coverage.get("status", "not_available"))
    lineage_status = str(lineage.get("status", "not_available"))
    run_status = str((run_evidence or {}).get("status", "not_available"))
    capability = _mapping(capability_manifest)
    if input_status == "blocked":
        status = "blocked"
    elif (
        input_status == "ready"
        and stage_status == "ready"
        and lineage_status == "observed"
        and run_status == "completed"
        and str(capability.get("status") or "") == "ready"
        and str(_mapping(capability.get("freshness")).get("status") or "") == "verified"
        and str(_mapping(capability.get("identity_binding")).get("status") or "") == "aligned"
    ):
        status = "ready"
    else:
        status = "partial"
    gaps: list[dict[str, Any]] = []
    source_context_conflicts = [
        str(item) for item in _mapping(source_context).get("identity_conflicts", []) or [] if str(item).strip()
    ]
    if source_context_conflicts:
        gaps.append({
            "id": "source_context_identity_conflict",
            "severity": "high",
            "message": "the capture and explicitly supplied source contexts disagree; execution conclusions remain blocked",
            "conflicts": source_context_conflicts,
        })
    for item in input_contract.get("missing_required_fields", []) or []:
        gaps.append({"id": f"input_missing:{item}", "severity": "high", "message": "required point field is unavailable"})
    if stage_status != "ready":
        derived_stages = sum(
            1 for row in (_mapping(stage_coverage).get("stages") or [])
            if isinstance(row, Mapping) and str(row.get("runtime_proof")) == "derived"
        )
        gaps.append({
            "id": "perception_stage_evidence_partial",
            "severity": "high",
            "message": f"{derived_stages} stages are derived from source and public output fields; private per-frame trace or input capture remains missing",
        })
    if lineage_status == "not_available":
        gaps.append({"id": "perception_lineage_missing", "severity": "high", "message": "point/cluster/track/output edges were not supplied"})
    elif lineage_status == "derived":
        gaps.append({"id": "perception_lineage_derived", "severity": "medium", "message": "lineage is derived from source-bound public output fields and exact callback-order bindings, not private stage trace"})
    run_obj = dict(run_evidence or {})
    if not run_obj:
        gaps.append({"id": "perception_run_evidence_missing", "severity": "high", "message": "runtime run/attempt evidence was not supplied"})
    elif str(run_obj.get("status", "")) not in {"completed", "ready"}:
        gaps.append({"id": "perception_run_incomplete", "severity": "high", "message": "replay attempt has no complete runtime frame ledger"})
    comparison_obj = dict(comparison or {})
    if comparison_obj and str(comparison_obj.get("status", "")) == "not_available":
        gaps.append({"id": "perception_comparison_unavailable", "severity": "medium", "message": "recorded-to-replay explicit frame identity match was not supplied"})
    scene_obj = dict(scene or {})
    timeline_obj = dict(timeline or {})
    if scene_obj and str(scene_obj.get("status", "")) == "not_available":
        gaps.append({"id": "perception_scene_unavailable", "severity": "medium", "message": "an explicit selected frame was not supplied for the scene projection"})
    warmup_obj = dict(warmup_analysis or {})
    if warmup_obj and str(warmup_obj.get("status", "")) in {"not_available", "warmup_sensitive"}:
        gaps.append({"id": "perception_warmup_not_stable", "severity": "medium", "message": "independent warm-up attempts are missing or not stable"})
    hypothesis_obj = dict(hypothesis_set or {})
    hypothesis_rows = hypothesis_obj.get("hypotheses") if isinstance(hypothesis_obj.get("hypotheses"), Sequence) and not isinstance(hypothesis_obj.get("hypotheses"), (str, bytes, bytearray)) else []
    capability_obj = dict(capability_manifest or {})
    return {
        "schema_version": "perception-analysis.v1",
        "status": status,
        "problem": problem,
        "strategy": input_contract.get("strategy", "point_cloud"),
        "conclusion_level": (
            "supported_hypothesis" if status == "ready" and hypothesis_rows
            else "candidate_only" if hypothesis_rows
            else "facts_only"
        ),
        "input_contract": input_contract,
        "source_context_binding": dict(_mapping(input_contract.get("source_context_binding"))),
        "stage_coverage": stage_coverage,
        "lineage": lineage,
        "source_context": dict(source_context or {}),
        "code_flow": dict(code_flow or {}),
        "run_evidence": run_obj,
        "comparison": comparison_obj,
        "scene": scene_obj,
        "timeline": timeline_obj,
        "warmup_analysis": warmup_obj,
        "hypothesis_set": hypothesis_obj,
        "capability_manifest": capability_obj,
        "source_execution_contract": dict(source_execution_contract or {}),
        "callback_binding_summary": dict(callback_binding_summary or {}),
        "callback_bindings": [dict(item) for item in (callback_bindings or []) if isinstance(item, Mapping)],
        "gaps": gaps,
        "hypotheses": [],
        "next_actions": [
            {"id": "capture_missing_stage_evidence", "reason": "collect stage-boundary trace before making a perception root-cause claim"}
        ] if gaps else [],
    }


def build_perception_code_flow(
    *,
    stage_map: Mapping[str, Any] | None = None,
    stage_coverage: Mapping[str, Any] | None = None,
    code_context: Mapping[str, Any] | None = None,
    event_code_path: Mapping[str, Any] | None = None,
    condition_trace: Mapping[str, Any] | None = None,
    source_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Bind static source candidates to independently supplied runtime hits."""
    stage_map_obj = _mapping(stage_map)
    code_context_obj = _mapping(code_context)
    code_context_source = _mapping(code_context_obj.get("source_context"))
    report_source = _mapping(source_context)
    stage_map_root = str(stage_map_obj.get("source_root") or "").strip()
    code_context_root = str(
        code_context_source.get("source_root")
        or code_context_obj.get("source_root")
        or ""
    ).strip()
    report_source_root = str(report_source.get("source_root") or "").strip()
    code_context_hash = str(
        code_context_source.get("snapshot_hash")
        or code_context_obj.get("snapshot_hash")
        or code_context_obj.get("source_snapshot_hash")
        or ""
    ).strip()
    stage_map_hash = str(stage_map_obj.get("source_snapshot_hash") or "").strip()
    identity_conflicts: set[str] = set()
    for identity_source in (report_source, code_context_source):
        identity_conflicts.update(
            str(item) for item in identity_source.get("identity_conflicts", []) or [] if str(item).strip()
        )
    if report_source.get("source_context_binding_status") == "conflict":
        identity_conflicts.add("report_source_context_binding_conflict")

    def normalize_root(value: str) -> str:
        return os.path.normcase(os.path.normpath(str(value).replace("/", os.sep).replace("\\", os.sep))) if value else ""

    def normalize_relative(value: Any) -> str:
        result = str(value or "").replace("\\", "/")
        while result.startswith("./"):
            result = result[2:]
        return result

    roots = [root for root in (stage_map_root, code_context_root, report_source_root) if root]
    normalized_roots = {normalize_root(root) for root in roots}
    if identity_conflicts:
        code_context_binding_status = "identity_conflict"
    elif len(normalized_roots) > 1:
        code_context_binding_status = "source_root_conflict"
    elif stage_map_root and code_context_root and code_context_obj:
        code_context_binding_status = "file_manifest_unavailable"
    else:
        code_context_binding_status = "not_available"

    code_context_files = code_context_source.get("files")
    if not isinstance(code_context_files, list):
        code_context_files = code_context_obj.get("files") if isinstance(code_context_obj.get("files"), list) else []
    code_file_hashes = {
        normalize_relative(item.get("path")): str(item.get("sha256", "")).strip()
        for item in code_context_files
        if isinstance(item, Mapping) and normalize_relative(item.get("path")) and item.get("sha256")
    }
    current_file_hashes: dict[str, str] = {}
    stage_files = stage_map_obj.get("scanned_files")
    stage_files = stage_files if isinstance(stage_files, list) else []
    if code_context_binding_status == "file_manifest_unavailable" and stage_files and code_file_hashes:
        root_path = Path(stage_map_root).expanduser().resolve()
        for raw_path in stage_files:
            candidate = Path(str(raw_path)).expanduser()
            if not candidate.is_absolute():
                candidate = root_path / candidate
            resolved = candidate.resolve()
            try:
                relative = normalize_relative(resolved.relative_to(root_path))
            except ValueError:
                identity_conflicts.add("stage_map_file_outside_source_root")
                continue
            try:
                digest = hashlib.sha256(resolved.read_bytes()).hexdigest()
            except OSError:
                continue
            current_file_hashes[relative] = digest
        if identity_conflicts:
            code_context_binding_status = "identity_conflict"
        elif set(current_file_hashes) != set(code_file_hashes):
            code_context_binding_status = "file_set_mismatch"
        elif any(current_file_hashes[path] != code_file_hashes[path] for path in current_file_hashes):
            code_context_binding_status = "source_content_mismatch"
        else:
            code_context_binding_status = "same_file_snapshot"
    code_context_binding = {
        "status": code_context_binding_status,
        "basis": "per_file_sha256_match",
        "stage_map_source_root": stage_map_root,
        "stage_map_snapshot_hash": stage_map_hash,
        "code_context_source_root": code_context_root,
        "code_context_snapshot_hash": code_context_hash,
        "report_source_root": report_source_root,
        "identity_conflicts": sorted(identity_conflicts),
        "matched_file_count": len(current_file_hashes) if code_context_binding_status == "same_file_snapshot" else 0,
        "source_files_missing_from_code_context": sorted(set(current_file_hashes) - set(code_file_hashes))[:20],
        "code_context_files_missing_from_stage_map": sorted(set(code_file_hashes) - set(current_file_hashes))[:20],
        "mismatched_file_paths": sorted(
            path for path in set(current_file_hashes) & set(code_file_hashes)
            if current_file_hashes[path] != code_file_hashes[path]
        )[:20],
        "limitation": "per-file hash equality binds source candidates to one input snapshot; it does not prove a function ran",
    }
    code_context_functions = code_context_obj.get("functions")
    code_context_functions = code_context_functions if isinstance(code_context_functions, list) else []
    definitions_by_name: dict[str, list[dict[str, Any]]] = {}
    if code_context_binding_status == "same_file_snapshot":
        for function in code_context_functions:
            if not isinstance(function, Mapping):
                continue
            name = str(function.get("name", "")).strip()
            if not name:
                continue
            definition = {
                "function": name,
                "signature": str(function.get("signature", "")),
                "source_ref": {
                    "path": str(function.get("file_path", function.get("path", ""))),
                    "line": function.get("start_line"),
                    "end_line": function.get("end_line"),
                    "source_hash": str(function.get("source_hash", "")),
                },
                "basis": "code-index-function-definition",
                "status": "source_candidate",
                "runtime_proof": "not_available",
                "code_context_snapshot_hash": code_context_hash,
            }
            definitions_by_name.setdefault(name.rsplit("::", 1)[-1], []).append(definition)

    stage_rows = _mapping(stage_coverage).get("stages")
    stage_rows = stage_rows if isinstance(stage_rows, Sequence) and not isinstance(stage_rows, (str, bytes, bytearray)) else []
    coverage_by_stage = {str(item.get("stage")): item for item in stage_rows if isinstance(item, Mapping) and item.get("stage")}
    mapped = stage_map_obj.get("stages") if isinstance(stage_map_obj.get("stages"), Mapping) else {}
    bindings: list[dict[str, Any]] = []
    for stage in STAGE_NAMES:
        candidates = mapped.get(stage, []) if isinstance(mapped, Mapping) else []
        if isinstance(candidates, Mapping):
            candidates = [candidates]
        candidate_names = {
            str(item.get("function", "")).rsplit("::", 1)[-1]
            for item in candidates
            if isinstance(item, Mapping) and str(item.get("function", "")).strip()
        }
        candidate_names.update(STAGE_FUNCTIONS.get(stage, ()))
        function_definitions: list[dict[str, Any]] = []
        definition_seen: set[tuple[str, str, int]] = set()
        for name in sorted(candidate_names):
            for definition in definitions_by_name.get(name, []):
                source_ref = _mapping(definition.get("source_ref"))
                identity = (
                    str(definition.get("function", "")),
                    str(source_ref.get("path", "")),
                    int(source_ref.get("line") or 0),
                )
                if identity not in definition_seen:
                    definition_seen.add(identity)
                    function_definitions.append(dict(definition))
        runtime = coverage_by_stage.get(stage, {})
        runtime_proof = str(runtime.get("runtime_proof", "not_available"))
        if runtime_proof in {"observed", "completed"}:
            binding_status = "runtime_observed"
            gap = ""
        elif runtime_proof == "derived":
            binding_status = "runtime_derived"
            gap = "private_stage_trace_missing"
        else:
            binding_status = "source_candidate" if candidates else "not_available"
            gap = "runtime_hit_missing"
        bindings.append({
            "stage": stage,
            "source_candidates": [dict(item) for item in candidates if isinstance(item, Mapping)],
            "function_definition_candidates": function_definitions,
            "function_definition_status": "available" if function_definitions else "not_available",
            "runtime_proof": runtime_proof,
            "status": binding_status,
            "input_count": runtime.get("input_count"),
            "output_count": runtime.get("output_count"),
            "frames": runtime.get("frames", []),
            "gap": gap,
        })
    trace_obj = _mapping(condition_trace)
    condition_rows = trace_obj.get("conditions")
    condition_rows = condition_rows if isinstance(condition_rows, Sequence) and not isinstance(condition_rows, (str, bytes, bytearray)) else []
    condition_bindings = []
    for condition in condition_rows:
        if not isinstance(condition, Mapping):
            continue
        evaluation = condition.get("evaluation") if isinstance(condition.get("evaluation"), Mapping) else {}
        condition_bindings.append({
            "condition_id": condition.get("condition_id", ""),
            "function": condition.get("function", condition.get("chain_function", "")),
            "stage": condition.get("stage", ""),
            "expression": condition.get("expression", ""),
            "source_ref": condition.get("source_ref", {}),
            "evaluation_status": evaluation.get("status", "not_evaluable"),
            "evaluation_reason": evaluation.get("reason", ""),
            "missing_tokens": list(condition.get("missing_tokens", []) or []),
        })
    return {
        "schema_version": "perception-code-flow.v1",
        "source_context": dict(source_context or {}),
        "code_context_binding": code_context_binding,
        "stage_bindings": bindings,
        "code_context": dict(code_context or {}),
        "event_code_path": dict(event_code_path or {}),
        "condition_trace": trace_obj,
        "condition_bindings": condition_bindings,
        "limitations": [
            "source candidates do not prove the compiled function ran",
            "runtime_observed is emitted only from direct stage evidence; runtime_derived remains source plus public-output inference",
        ],
    }


def _same_frame(row: Mapping[str, Any], selected_frame: Any, *, frame_domain: str = "", epoch: Any = None) -> bool:
    """Match a frame only by explicit frame token/domain/epoch."""
    if selected_frame in (None, ""):
        return False
    row_frame = _frame_key(row)
    selected = str(selected_frame)
    if row_frame == selected:
        return True
    row_domain = str(row.get("frame_domain") or row.get("domain") or "")
    row_epoch = row.get("epoch")
    if frame_domain and row_domain and row_domain != str(frame_domain):
        return False
    if epoch not in (None, "") and row_epoch not in (None, "") and str(row_epoch) != str(epoch):
        return False
    return str(row.get("frame_id", row.get("frameID", ""))) == selected


def build_perception_scene(
    *,
    points: Sequence[Mapping[str, Any]] | None = None,
    clusters: Sequence[Mapping[str, Any]] | None = None,
    tracks: Sequence[Mapping[str, Any]] | None = None,
    outputs: Sequence[Mapping[str, Any]] | None = None,
    selected_frame: Any = None,
    selection_basis: str = "",
    frame_domain: str = "",
    epoch: Any = None,
    angle_unit: str = "unknown",
    range_unit: str = "unknown",
    coordinate_frame: str = "radar",
) -> dict[str, Any]:
    """Build a deterministic scene projection for one explicitly selected frame.

    The scene never chooses a nearest frame.  Coordinate projection is only
    performed when the producer declares the angle unit; otherwise raw values
    remain available with an unavailable plot coordinate.
    """
    raw_points = [_safe_evidence_row(item) for item in (points or []) if isinstance(item, Mapping)]
    raw_clusters = [_safe_evidence_row(item) for item in (clusters or []) if isinstance(item, Mapping)]
    raw_tracks = [_safe_evidence_row(item) for item in (tracks or []) if isinstance(item, Mapping)]
    raw_outputs = [_safe_evidence_row(item) for item in (outputs or []) if isinstance(item, Mapping)]
    diagnostics: list[str] = []
    if selected_frame in (None, ""):
        diagnostics.append("selected_frame_missing")
        return {
            "schema_version": SCENE_SCHEMA,
            "status": "not_available",
            "selected_frame": None,
            "selection_basis": str(selection_basis or "not_selected"),
            "frame_domain": frame_domain,
            "epoch": epoch,
            "coordinate_frame": coordinate_frame,
            "angle_unit": angle_unit,
            "range_unit": range_unit,
            "layers": {"points": [], "clusters": [], "tracks": [], "outputs": []},
            "counts": {"points": 0, "clusters": 0, "tracks": 0, "outputs": 0},
            "diagnostics": diagnostics,
            "limitations": ["scene requires an explicitly selected frame; no nearest-frame fallback is used"],
        }
    selected = lambda row: _same_frame(row, selected_frame, frame_domain=frame_domain, epoch=epoch)
    selected_points = [row for row in raw_points if selected(row)]
    selected_clusters = [row for row in raw_clusters if selected(row)]
    selected_tracks = [row for row in raw_tracks if selected(row)]
    selected_outputs = [row for row in raw_outputs if selected(row)]

    def canonical_cluster_id(value: Any) -> str:
        try:
            return str(int(float(value)))
        except (TypeError, ValueError, OverflowError):
            return str(value or "")

    plot_points: list[dict[str, Any]] = []
    for row in selected_points:
        value: dict[str, Any] = {
            "point_key": row.get("point_key") or row.get("id"),
            "frame_key": _frame_key(row),
            "frame_domain": row.get("frame_domain", frame_domain),
            "epoch": row.get("epoch", epoch),
            "radar_id": row.get("radar_id"),
            "cluster_id": row.get("cluster_id"),
            "track_id": row.get("track_id"),
            "range": row.get("range", row.get("dist", row.get("distance"))),
            "azimuth": row.get("azimuth", row.get("ang", row.get("angle"))),
            "coordinate_status": "not_available",
            "x": None,
            "y": None,
            "source_ref": row.get("source_ref"),
        }
        # Prefer producer coordinates when a structured PointCloud2 row
        # supplies x/y. These are output coordinates in its declared frame;
        # recomputing them from compressed range/azimuth would discard mount
        # orientation, calibration and offsets already applied by the source.
        if row.get("x") not in (None, "") and row.get("y") not in (None, ""):
            try:
                observed_x = float(row.get("x"))
                observed_y = float(row.get("y"))
                if not math.isfinite(observed_x) or not math.isfinite(observed_y):
                    raise ValueError("non_finite_coordinate")
                value.update({"x": observed_x, "y": observed_y, "coordinate_status": "observed"})
                plot_points.append(value)
                continue
            except (TypeError, ValueError, OverflowError):
                diagnostics.append("scene_observed_coordinate_unavailable")
        try:
            distance = float(value["range"])
            angle = float(value["azimuth"])
            if not math.isfinite(distance) or not math.isfinite(angle):
                raise ValueError("non_finite_coordinate")
            if str(range_unit).lower() in {"", "unknown", "na", "n/a"}:
                raise ValueError("range_unit_unknown")
            if str(angle_unit).lower() in {"deg", "degree", "degrees"}:
                angle = math.radians(angle)
            elif str(angle_unit).lower() not in {"rad", "radian", "radians"}:
                raise ValueError("angle_unit_unknown")
            value.update({"x": distance * math.cos(angle), "y": distance * math.sin(angle), "coordinate_status": "derived"})
        except (TypeError, ValueError, OverflowError):
            if value["range"] not in (None, "") or value["azimuth"] not in (None, ""):
                diagnostics.append("scene_coordinate_unavailable")
        plot_points.append(value)
    cluster_point_groups: dict[str, list[dict[str, Any]]] = {}
    for point in plot_points:
        cluster_key = canonical_cluster_id(point.get("cluster_id"))
        if cluster_key and cluster_key != "0":
            cluster_point_groups.setdefault(cluster_key, []).append(point)
    scene_clusters: list[dict[str, Any]] = []
    for raw_cluster in selected_clusters:
        cluster = dict(raw_cluster)
        cluster_key = canonical_cluster_id(cluster.get("algorithm_cluster_id", cluster.get("cluster_id")))
        members = cluster_point_groups.get(cluster_key, [])
        usable: list[dict[str, Any]] = []
        for point in members:
            try:
                if math.isfinite(float(point.get("x"))) and math.isfinite(float(point.get("y"))):
                    usable.append(point)
            except (TypeError, ValueError, OverflowError):
                continue
        cluster.update({
            "coordinate_status": "not_available",
            "support_point_count": len(members),
            "coordinate_basis": "not_available",
        })
        observed_cluster_xy: tuple[float, float] | None = None
        try:
            cx, cy = float(cluster.get("x")), float(cluster.get("y"))
            if math.isfinite(cx) and math.isfinite(cy):
                observed_cluster_xy = (cx, cy)
        except (TypeError, ValueError, OverflowError):
            observed_cluster_xy = None
        if observed_cluster_xy is not None:
            cluster.update({"x": observed_cluster_xy[0], "y": observed_cluster_xy[1], "coordinate_status": "observed", "coordinate_basis": "producer_cluster_coordinate"})
        elif usable:
            cluster.update({
                "x": sum(float(point["x"]) for point in usable) / len(usable),
                "y": sum(float(point["y"]) for point in usable) / len(usable),
                "coordinate_status": "derived",
                "coordinate_basis": "mean_of_exact_point_cluster_id",
                "support_point_count": len(usable),
            })
        scene_clusters.append(cluster)
    layers = {
        "points": plot_points,
        "clusters": scene_clusters,
        "tracks": selected_tracks,
        "outputs": selected_outputs,
    }
    counts = {key: len(value) for key, value in layers.items()}
    status = "observed" if any(counts.values()) else "not_available"
    if status == "not_available":
        diagnostics.append("selected_frame_has_no_explicit_rows")
    return {
        "schema_version": SCENE_SCHEMA,
        "status": status,
        "selected_frame": str(selected_frame),
        "selection_basis": str(selection_basis or "explicit_frame_token"),
        "frame_domain": frame_domain,
        "epoch": epoch,
        "coordinate_frame": coordinate_frame,
        "angle_unit": angle_unit,
        "range_unit": range_unit,
        "layers": layers,
        "counts": counts,
        "diagnostics": list(dict.fromkeys(diagnostics)),
        "limitations": ["derived x/y coordinates use only the declared radar coordinate frame; no vehicle transform is inferred"],
    }


def build_perception_timeline(
    *,
    stage_coverage: Mapping[str, Any] | None = None,
    tracks: Sequence[Mapping[str, Any]] | None = None,
    outputs: Sequence[Mapping[str, Any]] | None = None,
    selected_frame: Any = None,
    callback_bindings: Sequence[Mapping[str, Any]] | None = None,
    callback_binding_summary: Mapping[str, Any] | None = None,
    track_population: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Project exact-frame rows and source-bound adjacent public UID recurrence."""
    buckets: dict[str, dict[str, Any]] = {}
    stage_rows = _mapping(stage_coverage).get("stages")
    if isinstance(stage_rows, Sequence) and not isinstance(stage_rows, (str, bytes, bytearray)):
        for stage_row in stage_rows:
            if not isinstance(stage_row, Mapping):
                continue
            stage = str(stage_row.get("stage") or "")
            evidence_rows = stage_row.get("evidence_rows")
            evidence_rows = evidence_rows if isinstance(evidence_rows, Sequence) and not isinstance(evidence_rows, (str, bytes, bytearray)) else []
            if not evidence_rows and stage_row.get("frames"):
                evidence_rows = [{"frame_key": frame, "status": stage_row.get("status"), "runtime_proof": stage_row.get("runtime_proof")} for frame in stage_row.get("frames", [])]
            for row in evidence_rows:
                if not isinstance(row, Mapping):
                    continue
                frame = _frame_key(row)
                if not frame:
                    continue
                if selected_frame not in (None, "") and str(frame) != str(selected_frame):
                    continue
                bucket = buckets.setdefault(frame, {"frame_key": frame, "stages": [], "track_ids": [], "output_ids": [], "status": "observed"})
                bucket["stages"].append({"stage": stage, "status": row.get("status", stage_row.get("status")), "runtime_proof": row.get("runtime_proof", stage_row.get("runtime_proof")), "input_count": row.get("input_count"), "output_count": row.get("output_count")})
    for kind, rows in (("track_ids", tracks or []), ("output_ids", outputs or [])):
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            frame = _frame_key(row)
            if not frame or (selected_frame not in (None, "") and str(frame) != str(selected_frame)):
                continue
            bucket = buckets.setdefault(frame, {"frame_key": frame, "stages": [], "track_ids": [], "output_ids": [], "status": "observed"})
            key = row.get("track_id") if kind == "track_ids" else row.get("output_key", row.get("object_id", row.get("id")))
            if key not in (None, ""):
                bucket[kind].append(str(key))
    rows = sorted(buckets.values(), key=lambda item: (0, int(item["frame_key"])) if str(item["frame_key"]).isdigit() else (1, str(item["frame_key"])))
    bindings = [dict(item) for item in (callback_bindings or []) if isinstance(item, Mapping)]
    binding_summary = _mapping(callback_binding_summary)
    track_population_obj = _mapping(track_population)
    public_rows_by_frame: dict[str, set[int]] = {}

    def public_track_uid(row: Mapping[str, Any]) -> int | None:
        raw_uid = row.get("algorithm_track_id")
        if raw_uid is None:
            raw_uid = row.get("track_id", row.get("ID"))
        # ObjectList algorithm_track_id is decoded as an integer field. Keep
        # exact uint32 identities above float32's 2**24 boundary; only point
        # cloud float32 UIDs need _exact_public_uid's precision restriction.
        if isinstance(raw_uid, int) and not isinstance(raw_uid, bool):
            return raw_uid if 0 <= raw_uid <= 4_294_967_295 else None
        return _exact_public_uid(raw_uid)

    for row in tracks or []:
        if (
            not isinstance(row, Mapping)
            or str(row.get("population_scope") or "") != "public_objectlist_output_rows"
            or str(row.get("frame_domain") or "") != "source_proven_public_callback_order"
        ):
            continue
        frame = _frame_key(row)
        uid = public_track_uid(row)
        if frame and uid is not None:
            public_rows_by_frame.setdefault(frame, set()).add(uid)
    binding_count = len(bindings)
    binding_diagnostics = binding_summary.get("diagnostics") or []
    uid_recurrence_available = bool(
        track_population_obj.get("scope") == "public_objectlist_output_rows"
        and binding_count >= 2
        and str(binding_summary.get("status")) == "derived"
        and _int_or_default(binding_summary.get("binding_count"), -1) == binding_count
        and _int_or_default(binding_summary.get("point_message_count"), -1) == binding_count
        and _int_or_default(binding_summary.get("object_message_count"), -1) == binding_count
        and not binding_diagnostics
        and selected_frame not in (None, "")
        and any(str(item.get("callback_key") or "") == str(selected_frame) for item in bindings)
        and all(str(item.get("method") or "") == "source_proven_adjacent_publication_order" for item in bindings)
    )
    uid_recurrences: list[dict[str, Any]] = []
    if uid_recurrence_available:
        for previous, current in zip(bindings, bindings[1:]):
            previous_frame = str(previous.get("callback_key") or "")
            current_frame = str(current.get("callback_key") or "")
            if not previous_frame or not current_frame:
                continue
            if selected_frame not in (None, "") and str(selected_frame) not in {previous_frame, current_frame}:
                continue
            if str(previous.get("radar_id") or "") != str(current.get("radar_id") or ""):
                continue
            capture_prefix = previous_frame.split(":radar", 1)[0]
            if not capture_prefix or capture_prefix != current_frame.split(":radar", 1)[0]:
                continue
            try:
                previous_point_seq = int(previous.get("pointcloud_message_seq"))
                current_object_seq = int(current.get("object_message_seq"))
            except (TypeError, ValueError, OverflowError):
                continue
            if current_object_seq != previous_point_seq + 1:
                continue
            shared_ids = sorted(public_rows_by_frame.get(previous_frame, set()) & public_rows_by_frame.get(current_frame, set()))
            for uid in shared_ids:
                uid_recurrences.append({
                    "previous_frame_key": previous_frame,
                    "current_frame_key": current_frame,
                    "radar_id": current.get("radar_id"),
                    "algorithm_track_id": uid,
                    "status": "derived",
                    "match_grade": "same_public_uid_adjacent_callback",
                    "identity_basis": str(track_population_obj.get("identity_basis") or "wfSObj.ID == objUnqID"),
                    "callback_binding_method": "source_proven_adjacent_publication_order",
                    "previous_object_message_seq": previous.get("object_message_seq"),
                    "current_object_message_seq": current.get("object_message_seq"),
                    "limitation": "same public UID recurrence only; does not prove physical-object identity, ID non-reuse outside adjacent callbacks, or internal tracker lifecycle",
                })
    return {
        "schema_version": TIMELINE_SCHEMA,
        "status": "observed" if rows else "not_available",
        "selected_frame": None if selected_frame in (None, "") else str(selected_frame),
        "rows": rows,
        "uid_recurrence_status": "derived" if uid_recurrence_available else "not_available",
        "uid_recurrence_scope": "public_objectlist_output_rows_adjacent_callbacks_same_capture_and_radar" if uid_recurrence_available else "not_available",
        "public_uid_recurrences": uid_recurrences,
        "diagnostics": [] if rows else ["explicit_frame_timeline_rows_missing"],
        "limitations": [
            "timeline uses exact frame keys only and does not carry forward a previous frame",
            "same public UID recurrence is derived evidence only and does not prove physical-object identity or internal tracker continuity",
        ],
    }


def _frame_key(row: Mapping[str, Any]) -> str:
    """Return an explicit frame token without falling back to timestamp/index."""
    for key in ("frame_key", "frame_id", "frameID", "frame_counter", "frameCounter"):
        value = row.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def audit_public_perception_source_contract(
    *,
    source_root: str | Path,
    visualization_source_path: str | Path,
    build_macros: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Audit source mappings needed to interpret public perception output.

    This proves source-side field flow and publication order only. It does not
    claim runtime execution; that requires matching observations in the
    replay capture as performed by :func:`bind_public_perception_capture`.
    """
    root = Path(source_root).expanduser().resolve()
    visualization_path = Path(visualization_source_path).expanduser().resolve()
    relative_files = {
        "postprocess": Path("src/postProcess.c"),
        "cluster": Path("src/cluster.c"),
        "point_track_map": Path("src/objAttribCal.c"),
        "track_identity": Path("src/track.c"),
    }
    paths = {name: (root / relative).resolve() for name, relative in relative_files.items()}
    paths["visualization"] = visualization_path
    content: dict[str, str] = {}
    refs: dict[str, dict[str, Any]] = {}
    diagnostics: list[str] = []
    for name, path in paths.items():
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            diagnostics.append(f"source_file_missing:{name}")
            continue
        content[name] = text

    def ref(name: str, token: str) -> dict[str, Any] | None:
        text = content.get(name)
        if text is None:
            return None
        for line_number, line in enumerate(text.splitlines(), start=1):
            if token in line:
                try:
                    rel_path = str(paths[name].relative_to(root)).replace("\\", "/")
                except ValueError:
                    rel_path = str(paths[name])
                return {"path": rel_path, "line": line_number, "token": token}
        return None

    required_tokens = {
        "postprocess_hilmodel_guard": ("postprocess", "#if 0 == HILMODEL"),
        "postprocess_dot_preprocess": ("postprocess", "DotPrePosTI("),
        "postprocess_environment_detect": ("postprocess", "EnvModelDetect("),
        "postprocess_dot_filter": ("postprocess", "DotFilter("),
        "postprocess_cluster_call": ("postprocess", "ObjCluster("),
        "postprocess_track_call": ("postprocess", "ObjTrack("),
        "postprocess_track_output": ("postprocess", "OutputTrkObj("),
        "postprocess_adas_call": ("postprocess", "AdasFunc("),
        "cluster_assigns_point_id": ("cluster", "dotInfo[pointIndex].clusterID ="),
        "point_inherits_track_uid": ("point_track_map", "pDctnPts[i].objectUID = clusterInfo->clusterData[clusterID].objectUID"),
        "track_uid_to_cluster": ("track_identity", "clusterInfo->clusterData[i].objectUID = pTemp->objUnqID"),
        "visual_point_cluster_field": ("visualization", "cloud_corner.points[i].cluster_id = algo_dotInfoC[i].clusterID"),
        "visual_point_track_field": ("visualization", "cloud_corner.points[i].track_id = algo_dotInfoC[i].objectUID"),
        "visual_object_uid_field": ("visualization", "tar.ID = algo_objInfo.trcOutData[i].objUnqID"),
        "visual_object_publication": ("visualization", "wf_objectlist_pub.publish(ObjectListMsg_global)"),
        "visual_pointcloud_publication": ("visualization", "corner_radar_pcl_pub.publish(output)"),
    }
    for key, (name, token) in required_tokens.items():
        found = ref(name, token)
        if found:
            refs[key] = found
        else:
            diagnostics.append(f"source_marker_missing:{key}")

    viewer = content.get("visualization", "")
    callback_start = viewer.rfind("void corner_radar_post_process_data_callback(")
    callback_end = viewer.find("\nvoid ", callback_start + 1) if callback_start >= 0 else -1
    callback = viewer[callback_start:callback_end if callback_end >= 0 else None] if callback_start >= 0 else ""
    main_call = callback.find("PostProcessMainTI(")
    postprocess_guard = callback.rfind("if (is_wf_postprocess_enable)", 0, main_call) if main_call >= 0 else -1
    branch_open = callback.find("{", postprocess_guard) if postprocess_guard >= 0 else -1

    def block_end(text: str, open_index: int) -> int:
        """Find a matching C brace while ignoring comments and quoted strings."""
        if open_index < 0:
            return -1
        depth = 1
        i = open_index + 1
        state = "code"
        while i < len(text):
            ch = text[i]
            nxt = text[i + 1] if i + 1 < len(text) else ""
            if state == "line_comment":
                if ch == "\n":
                    state = "code"
                i += 1
                continue
            if state == "block_comment":
                if ch == "*" and nxt == "/":
                    state = "code"
                    i += 2
                else:
                    i += 1
                continue
            if state in {"string", "char"}:
                if ch == "\\":
                    i += 2
                    continue
                if (state == "string" and ch == '"') or (state == "char" and ch == "'"):
                    state = "code"
                i += 1
                continue
            if ch == "/" and nxt == "/":
                state = "line_comment"
                i += 2
                continue
            if ch == "/" and nxt == "*":
                state = "block_comment"
                i += 2
                continue
            if ch == '"':
                state = "string"
                i += 1
                continue
            if ch == "'":
                state = "char"
                i += 1
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return i
            i += 1
        return -1

    branch_end = block_end(callback, branch_open)
    branch = callback[postprocess_guard:branch_end + 1] if postprocess_guard >= 0 and branch_end >= 0 else ""
    object_handler = branch.find("wf_object_display_handler();")
    cloud_publish = callback.find("corner_radar_pcl_pub.publish(output);", branch_end + 1 if branch_end >= 0 else 0)
    if cloud_publish >= 0:
        refs["visual_pointcloud_publication"] = {
            "path": str(visualization_path),
            "line": viewer[:callback_start + cloud_publish].count("\n") + 1,
            "token": "corner_radar_pcl_pub.publish(output);",
        }
    source_order_verified = bool(
        callback
        and postprocess_guard >= 0
        and branch_end > branch_open
        and main_call >= 0
        and object_handler >= 0
        and main_call < branch_open + object_handler
        and "cloud_corner.points[i].cluster_id = algo_dotInfoC[i].clusterID" in branch
        and "cloud_corner.points[i].track_id = algo_dotInfoC[i].objectUID" in branch
        and cloud_publish > branch_end
    )
    if not source_order_verified:
        diagnostics.append("public_track_pointcloud_callback_order_not_verified")
    marker_disable = "is_wf_cluster_disp_enable = false;" in viewer
    if marker_disable:
        diagnostics.append("cluster_marker_display_disabled_in_source")
    macros = _mapping(build_macros)
    hilmodel = str(macros.get("HILMODEL", ""))
    compile_mode_verified = hilmodel == "0"
    if not compile_mode_verified:
        diagnostics.append("active_binary_hilmodel_zero_not_verified")

    file_hashes: dict[str, str] = {}
    for name, path in paths.items():
        if path.is_file():
            file_hashes[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    required_ok = len(refs) == len(required_tokens) and source_order_verified and compile_mode_verified
    return {
        "schema_version": "perception-source-execution-contract.v1",
        "status": "source_verified" if required_ok else "partial",
        "source_root": str(root),
        "visualization_source_path": str(visualization_path),
        "source_file_hashes": file_hashes,
        "source_refs": refs,
        "publication_order": {
            "status": "source_verified" if source_order_verified else "not_available",
            "order": ["PostProcessMainTI", "wf_object_display_handler", "corner_radar_pcl_pub.publish"],
            "same_callback": True if source_order_verified else None,
        },
        "cluster_marker_display_disabled": marker_disable,
        "build_macros": {key: macros.get(key) for key in ("HILMODEL", "BUILDMODEL", "PF_BUILD_FUNTEST_SGU_INJECTION") if key in macros},
        "compile_mode_verified": compile_mode_verified,
        "diagnostics": list(dict.fromkeys(diagnostics)),
        "limitations": [
            "source matches describe field flow but do not alone prove the branch executed",
            "public callback-order binding is scoped to the recorded attempt and does not recover original LGU frameID",
            "cluster markers may be unavailable while per-point clusterID remains present in PointCloud2",
        ],
    }


def bind_public_perception_capture(
    capture: Mapping[str, Any],
    *,
    source_contract: Mapping[str, Any],
    capture_id: str = "",
) -> dict[str, Any]:
    """Derive callback-scoped public lineage only with a source proof.

    Pairing uses an exact adjacent bag message sequence and the source-audited
    publication order. It never pairs rows by nearest time, row index, or
    numeric ID alone.
    """
    payload = dict(capture)
    proof = _mapping(source_contract)
    if str(proof.get("status")) != "source_verified":
        payload["source_execution_contract"] = dict(proof)
        payload["callback_bindings"] = []
        payload["lineage_edges"] = []
        payload.setdefault("diagnostics", []).append("public_callback_source_contract_not_verified")
        return payload

    point_rows = [dict(row) for row in payload.get("point_rows", []) if isinstance(row, Mapping)]
    object_rows = [dict(row) for row in payload.get("object_rows", []) if isinstance(row, Mapping)]
    stage_rows = [dict(row) for row in payload.get("stage_evidence", []) if isinstance(row, Mapping)]
    point_stage_by_seq: dict[int, dict[str, Any]] = {}
    track_stage_by_seq: dict[int, dict[str, Any]] = {}
    for row in stage_rows:
        source_ref = _mapping(row.get("source_ref"))
        seq = source_ref.get("message_seq")
        if seq in (None, ""):
            continue
        try:
            seq_num = int(seq)
        except (TypeError, ValueError):
            continue
        topic = str(source_ref.get("topic") or "")
        if str(row.get("stage")) == "point_cloud":
            point_stage_by_seq[seq_num] = row
        elif str(row.get("stage")) == "track":
            track_stage_by_seq[seq_num] = row

    def radar_for_stage(row: Mapping[str, Any]) -> str:
        topic = str(_mapping(row.get("source_ref")).get("topic") or "")
        suffix = topic.rsplit("_", 1)[-1]
        return suffix if suffix.isdigit() else ""

    bindings: list[dict[str, Any]] = []
    callback_by_point_seq: dict[int, str] = {}
    callback_by_object_seq: dict[int, str] = {}
    diagnostics: list[str] = []
    capture_scope = str(capture_id or _hash({
        "point_messages": sorted(point_stage_by_seq),
        "track_messages": sorted(track_stage_by_seq),
        "source_hashes": proof.get("source_file_hashes", {}),
    })[:16])
    for object_seq, object_stage in sorted(track_stage_by_seq.items()):
        point_seq = object_seq + 1
        point_stage = point_stage_by_seq.get(point_seq)
        if point_stage is None:
            diagnostics.append(f"public_callback_pointcloud_missing_after_objectlist:{object_seq}")
            continue
        object_radar = radar_for_stage(object_stage)
        point_radar = radar_for_stage(point_stage)
        if not object_radar or object_radar != point_radar:
            diagnostics.append(f"public_callback_radar_mismatch:{object_seq}:{point_seq}")
            continue
        callback_key = f"{capture_scope}:radar{object_radar}:callback:{object_seq}-{point_seq}"
        binding = {
            "callback_key": callback_key,
            "radar_id": int(object_radar),
            "object_message_seq": object_seq,
            "pointcloud_message_seq": point_seq,
            "status": "derived",
            "method": "source_proven_adjacent_publication_order",
            "basis_ref": {
                "source_contract_schema": proof.get("schema_version"),
                "source_refs": proof.get("source_refs", {}),
                "publication_order": proof.get("publication_order", {}),
                "limitation": "callback identity is exact for this capture only; original LGU frameID was not recorded",
            },
        }
        bindings.append(binding)
        callback_by_point_seq[point_seq] = callback_key
        callback_by_object_seq[object_seq] = callback_key

    if len(point_stage_by_seq) != len(bindings) or len(track_stage_by_seq) != len(bindings):
        diagnostics.append("public_callback_binding_incomplete")
    for row in point_rows:
        source_ref = _mapping(row.get("source_ref"))
        try:
            seq = int(source_ref.get("message_seq"))
        except (TypeError, ValueError):
            continue
        callback_key = callback_by_point_seq.get(seq)
        if not callback_key:
            continue
        row.setdefault("point_key", f"{source_ref.get('topic')}:{seq}:{row.get('point_index', row.get('source_index', ''))}")
        row["frame_key"] = callback_key
        row["frame_domain"] = "source_proven_public_callback_order"
        row["epoch"] = capture_scope
    valid_objects: list[dict[str, Any]] = []
    track_rows: list[dict[str, Any]] = []
    output_rows: list[dict[str, Any]] = []
    object_callback: dict[int, str] = {}
    for row in object_rows:
        try:
            object_seq = int(row.get("object_message_seq"))
        except (TypeError, ValueError):
            continue
        callback_key = callback_by_object_seq.get(object_seq)
        if not callback_key:
            continue
        row["frame_key"] = callback_key
        row["frame_domain"] = "source_proven_public_callback_order"
        row["epoch"] = capture_scope
        try:
            unique_id = int(row.get("ID"))
        except (TypeError, ValueError):
            unique_id = -1
        if unique_id < 0:
            row["status"] = "ignored_sentinel"
            continue
        row["algorithm_track_id"] = unique_id
        row["track_id"] = unique_id
        row["track_key"] = f"{callback_key}:track:{unique_id}"
        row["output_key"] = f"{callback_key}:output:{unique_id}"
        row["status"] = "observed"
        valid_objects.append(row)
        track_rows.append({
            **row,
            "tracker_instance": callback_key,
            "identity_basis": "wfSObj.ID == objUnqID",
            "population_scope": "public_objectlist_output_rows",
        })
        output_rows.append({**row, "identity_basis": "wfSObj.ID == objUnqID"})
        object_callback.setdefault(object_seq, callback_key)

    cluster_nodes: dict[str, dict[str, Any]] = {}
    track_ids_by_callback: dict[str, set[int]] = {}
    for obj in valid_objects:
        callback_key = str(obj.get("frame_key") or "")
        if callback_key:
            track_ids_by_callback.setdefault(callback_key, set()).add(int(obj["algorithm_track_id"]))
    lineage_edges: list[dict[str, Any]] = []
    for point in point_rows:
        callback_key = str(point.get("frame_key") or "")
        point_key = str(point.get("point_key") or "")
        if not callback_key or not point_key:
            continue
        try:
            cluster_id = int(float(point.get("cluster_id", 0) or 0))
        except (TypeError, ValueError, OverflowError):
            cluster_id = 0
        track_uid = _exact_public_uid(point.get("track_id", 0))
        if cluster_id > 0:
            cluster_key = f"{callback_key}:cluster:{cluster_id}"
            cluster_nodes.setdefault(cluster_key, {
                "cluster_id": cluster_key,
                "algorithm_cluster_id": cluster_id,
                "frame_key": callback_key,
                "frame_domain": "source_proven_public_callback_order",
                "epoch": capture_scope,
                "radar_id": point.get("radar_id"),
                "status": "observed",
                "identity_basis": "PointCloud2.cluster_id <- algo_dotInfoC[i].clusterID",
            })
            lineage_edges.append({
                "relation_kind": "point_supports_cluster",
                "from": point_key,
                "to": cluster_key,
                "status": "derived",
                "basis_ref": proof.get("source_refs", {}).get("visual_point_cluster_field"),
            })
            if track_uid is not None and track_uid > 0 and track_uid in track_ids_by_callback.get(callback_key, set()):
                track_key = f"{callback_key}:track:{track_uid}"
                lineage_edges.append({
                    "relation_kind": "cluster_supports_track",
                    "from": cluster_key,
                    "to": track_key,
                    "status": "derived",
                    "basis_ref": {
                        "point_track_field": proof.get("source_refs", {}).get("visual_point_track_field"),
                        "point_to_track_uid": proof.get("source_refs", {}).get("point_inherits_track_uid"),
                        "track_uid_to_cluster": proof.get("source_refs", {}).get("track_uid_to_cluster"),
                    },
                })

    output_ids_by_callback: dict[str, dict[int, str]] = {}
    for row in output_rows:
        callback_key = str(row.get("frame_key") or "")
        output_ids_by_callback.setdefault(callback_key, {})[int(row["algorithm_track_id"])] = str(row["output_key"])
        track_key = str(row["track_key"])
        lineage_edges.append({
            "relation_kind": "track_emits_output",
            "from": track_key,
            "to": str(row["output_key"]),
            "status": "derived",
            "basis_ref": {
                "track_output": proof.get("source_refs", {}).get("visual_object_uid_field"),
                "callback_binding_method": "source_proven_adjacent_publication_order",
            },
        })

    # A cluster marker producer is deliberately disabled in this source, but
    # the per-point cluster_id and track_id fields are direct algorithm output
    # in each successfully paired callback. Record stage rows as observations
    # with the field-level provenance, not as private function hits.
    # Replace the raw per-topic track counts with callback-scoped counts after
    # removing ID=-1 display sentinels. This prevents duplicate/double-counted
    # track_output rows in the report.
    derived_stage_rows = [
        row for row in stage_rows
        if str(row.get("stage")) not in {"track", "track_output"}
    ]
    for binding in bindings:
        callback_key = str(binding["callback_key"])
        point_seq = int(binding["pointcloud_message_seq"])
        callback_points = [row for row in point_rows if str(row.get("frame_key")) == callback_key]
        positive_clusters = {int(float(row.get("cluster_id", 0) or 0)) for row in callback_points if _numeric_positive(row.get("cluster_id"))}
        tracked_points = sum(1 for row in callback_points if _numeric_positive(row.get("track_id")))
        object_count = sum(1 for row in valid_objects if str(row.get("frame_key")) == callback_key)
        derived_stage_rows.append({
            "stage": "track",
            "frame_key": callback_key,
            "frame_domain": "source_proven_public_callback_order",
            "epoch": capture_scope,
            "status": "completed" if object_count else "partial",
            "runtime_proof": "observed" if object_count else "not_available",
            "input_count": len(positive_clusters),
            "output_count": object_count,
            "source_ref": proof.get("source_refs", {}).get("visual_object_uid_field"),
            "evidence_kind": "public_point_cluster_fields_and_track_output",
            "capture_message_seq": point_seq,
        })
        if positive_clusters:
            derived_stage_rows.append({
                "stage": "cluster",
                "frame_key": callback_key,
                "frame_domain": "source_proven_public_callback_order",
                "epoch": capture_scope,
                "status": "completed",
                "runtime_proof": "observed",
                "input_count": len(callback_points),
                "output_count": len(positive_clusters),
                "source_ref": proof.get("source_refs", {}).get("visual_point_cluster_field"),
                "evidence_kind": "public_output_field",
                "capture_message_seq": point_seq,
            })
        if tracked_points or object_count:
            derived_stage_rows.append({
                "stage": "track_output",
                "frame_key": callback_key,
                "frame_domain": "source_proven_public_callback_order",
                "epoch": capture_scope,
                "status": "completed",
                "runtime_proof": "observed",
                "input_count": tracked_points,
                "output_count": object_count,
                "source_ref": proof.get("source_refs", {}).get("visual_object_uid_field"),
                "evidence_kind": "public_track_output",
                "capture_message_seq": point_seq,
            })
        # The source proves these calls execute in order inside the active
        # HILMODEL=0 post-process branch.  Their internal values were not
        # captured, so preserve them as derived branch evidence only.
        for stage_name, source_key in (
            ("dot_preprocess", "postprocess_dot_preprocess"),
            ("environment_detect", "postprocess_environment_detect"),
            ("dot_filter", "postprocess_dot_filter"),
            ("track", "postprocess_track_call"),
            ("adas_func", "postprocess_adas_call"),
        ):
            derived_stage_rows.append({
                "stage": stage_name,
                "frame_key": callback_key,
                "frame_domain": "source_proven_public_callback_order",
                "epoch": capture_scope,
                "status": "derived",
                "runtime_proof": "derived",
                "input_count": None,
                "output_count": None,
                "source_ref": proof.get("source_refs", {}).get(source_key),
                "evidence_kind": "source_control_flow_derived_from_callback_output",
                "capture_message_seq": point_seq,
            })
    payload["point_rows"] = point_rows
    payload["object_rows"] = object_rows
    payload["track_rows"] = track_rows
    payload["cluster_rows"] = list(cluster_nodes.values())
    payload["output_rows"] = output_rows
    payload["lineage_edges"] = lineage_edges
    payload["track_population"] = {
        "status": "observed_subset" if track_stage_by_seq else "not_available",
        "scope": "public_objectlist_output_rows",
        "track_nodes_mirror_output_rows": True,
        "internal_candidate_track_population": "not_available",
        "internal_mature_track_population": "not_available",
        "cluster_supports_track_scope": "unique_cluster_track_pairs_where_point_track_uid_matches_captured_public_objectlist_id",
        "track_emits_output_scope": "one_unique_derived_edge_per_captured_public_objectlist_output_row",
        "unclustered_point_scope": "cluster_id_minus_one_has_no_cluster_node_or_point_support_edge; track_lifecycle_not_inferred",
        "source_topics": sorted({
            str(_mapping(row.get("source_ref")).get("topic"))
            for row in track_stage_by_seq.values()
            if _mapping(row.get("source_ref")).get("topic") not in (None, "")
        }),
        "identity_basis": "wfSObj.ID == objUnqID",
        "limitation": "track nodes mirror captured public objectlist output rows; this is not a complete internal candidate or mature tracker snapshot",
    }
    payload["relation_scopes"] = {
        "point_supports_cluster": {
            "population": "public_pointcloud_rows",
            "inclusion_condition": "cluster_id > 0",
            "basis": "PointCloud2.cluster_id <- algo_dotInfoC[i].clusterID",
            "limitation": "rows with cluster_id <= 0 have no edge in this public lineage; absence does not identify the algorithm stage that set the value",
        }
    }
    payload["stage_evidence"] = derived_stage_rows
    payload["source_execution_contract"] = dict(proof)
    payload["callback_bindings"] = bindings
    payload["diagnostics"] = list(payload.get("diagnostics", []) or []) + diagnostics
    payload["limitations"] = list(payload.get("limitations", []) or []) + [
        "callback keys are a capture-local frame domain derived from exact adjacent message sequence and source publication order",
        "raw input LGU frameID was not captured in this attempt; callback keys are not raw frameID",
        "ROS bag message_seq is capture-order only; it is not an algorithm frame counter and must not be compared to requested warmup frames",
        "private local arrays/intermediate values are not observed by public topics",
    ]
    payload["callback_binding_summary"] = {
        "status": "derived" if bindings and not diagnostics else "partial" if bindings else "not_available",
        "binding_count": len(bindings),
        "point_message_count": len(point_stage_by_seq),
        "object_message_count": len(track_stage_by_seq),
        "paired_message_count": len(bindings),
        "lineage_edge_count": len(lineage_edges),
        "cluster_count": len(cluster_nodes),
        "track_output_count": len(output_rows),
        "sequence_semantics": "message_seq is bag capture order, not algorithm frameID/counter or warmup frame count",
        "algorithm_frame_counter_status": "not_available",
        "warmup_frame_relation": "not_evaluable",
        "first_callback_key": bindings[0]["callback_key"] if bindings else "",
        "last_callback_key": bindings[-1]["callback_key"] if bindings else "",
        "diagnostics": list(dict.fromkeys(diagnostics)),
    }
    return payload


def _numeric_positive(value: Any) -> bool:
    try:
        number = float(value)
        return math.isfinite(number) and number > 0
    except (TypeError, ValueError, OverflowError):
        return False


def _exact_public_uid(value: Any) -> int | None:
    """Decode a float32-rendered uint32 UID only when integer identity is exact."""
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    # PointCloud2's `track_id` is float32. Above 2**24 adjacent integer IDs
    # cannot all be represented exactly, so refusing those joins is safer
    # than silently mapping them to the wrong object.
    if not math.isfinite(number) or not number.is_integer() or abs(number) > 16_777_216:
        return None
    return int(number)


def build_perception_run_evidence(
    *,
    run_id: str = "",
    attempt_id: str = "",
    plan_hash: str = "",
    terminal_status: str = "planned",
    warmup_requested: int = 175,
    warmup_completed: int | None = None,
    observed_frames: Sequence[Any] | None = None,
    completed_frames: Sequence[Any] | None = None,
    stage_evidence: Sequence[Mapping[str, Any]] | None = None,
    reset_events: Sequence[Mapping[str, Any]] | None = None,
    identity: Mapping[str, Any] | None = None,
    diagnostics: Sequence[str] | None = None,
    failure_reason: str = "",
) -> dict[str, Any]:
    """Normalize one replay attempt's lifecycle and completed-frame ledger.

    The producer may be a real runner or an external harness.  This function
    never turns a process return code into stage success: completed frames and
    explicit reset/identity observations remain separate fields.
    """
    run_id = str(run_id or "")
    attempt_id = str(attempt_id or "")
    terminal_status = str(terminal_status or "planned")
    requested = max(0, int(warmup_requested or 0))
    warmup_done = None if warmup_completed is None else max(0, int(warmup_completed))
    observed = [str(item) for item in (observed_frames or []) if item not in (None, "")]
    completed = [str(item) for item in (completed_frames or []) if item not in (None, "")]
    # Preserve producer order while de-duplicating frame tokens.
    observed = list(dict.fromkeys(observed))
    completed = list(dict.fromkeys(completed))
    observed_set = set(observed)
    unknown_completed = [item for item in completed if observed_set and item not in observed_set]
    reset_rows = [dict(item) for item in (reset_events or []) if isinstance(item, Mapping)]
    reset_completed = any(
        str(item.get("status", "")).lower() in {"completed", "ready"}
        or str(item.get("event", "")).lower() in {"reset_completed", "reset_ready"}
        for item in reset_rows
    )
    run_diagnostics = [str(item) for item in (diagnostics or []) if str(item).strip()]
    if not run_id:
        run_diagnostics.append("run_id_missing")
    if not attempt_id:
        run_diagnostics.append("attempt_id_missing")
    if not str(plan_hash or "").strip():
        run_diagnostics.append("plan_hash_missing")
    if completed and not observed:
        run_diagnostics.append("observed_frames_missing")
    if requested and warmup_done is not None and warmup_done < requested:
        run_diagnostics.append("warmup_incomplete")
    if unknown_completed:
        run_diagnostics.append("completed_frame_not_in_observed_frames")
    if not reset_rows:
        run_diagnostics.append("reset_evidence_missing")
    if failure_reason:
        run_diagnostics.append(str(failure_reason))
    stage_rows = [dict(item) for item in (stage_evidence or []) if isinstance(item, Mapping)]
    completed_stage_rows = []
    for row in stage_rows:
        frame = _frame_key(row)
        if frame and frame in set(completed):
            completed_stage_rows.append(row)
    lifecycle_complete = reset_completed and (not requested or warmup_done is not None and warmup_done >= requested)
    if terminal_status in {"completed", "success"} and completed:
        status = "completed" if run_id and attempt_id and plan_hash and observed and not unknown_completed and lifecycle_complete else "partial"
    elif completed or terminal_status in {"partial", "failed", "timeout", "interrupted"}:
        status = "partial"
    else:
        status = "blocked" if run_diagnostics else "planned"
    return {
        "schema_version": RUN_SCHEMA,
        "status": status,
        "run_id": run_id,
        "attempt_id": attempt_id,
        "plan_hash": str(plan_hash or ""),
        "terminal_status": terminal_status,
        "identity": dict(identity or {}),
        "warmup": {
            "requested": requested,
            "completed": warmup_done,
            "status": "ready" if warmup_done is not None and warmup_done >= requested else "not_available" if warmup_done is None else "partial",
        },
        "observed_frames": observed,
        "completed_frames": completed,
        "analyzed_frames": completed,
        "completed_stage_evidence": completed_stage_rows,
        "reset_events": reset_rows,
        "reset_status": "ready" if reset_completed else "not_available",
        "failure": {"reason": failure_reason, "recoverable": terminal_status in {"timeout", "interrupted", "partial"}},
        "diagnostics": list(dict.fromkeys(run_diagnostics)),
        "runtime_proof": "observed" if completed and terminal_status in {"completed", "success"} else "not_available",
    }


def build_perception_warmup_analysis(
    runs: Sequence[Mapping[str, Any]] | None = None,
    *,
    required_range: Sequence[int] = (150, 200),
) -> dict[str, Any]:
    """Compare independent warm-up attempts without treating one as ground truth."""
    rows = [dict(item) for item in (runs or []) if isinstance(item, Mapping)]
    diagnostics: list[str] = []
    normalized: list[dict[str, Any]] = []
    signatures: list[str] = []
    for row in rows:
        warmup_obj = row.get("warmup") if isinstance(row.get("warmup"), Mapping) else {}
        try:
            requested = int(row.get("warmup_requested", warmup_obj.get("requested", 0)))
        except (TypeError, ValueError):
            requested = 0
        completed = row.get("warmup_completed", warmup_obj.get("completed"))
        try:
            completed = int(completed) if completed not in (None, "") else None
        except (TypeError, ValueError):
            completed = None
        status = str(row.get("status", row.get("terminal_status", "not_available")))
        signature = row.get("output_signature", row.get("trajectory_signature", row.get("signature")))
        signature_text = "" if signature in (None, "") else str(signature)
        if signature_text:
            signatures.append(signature_text)
        normalized.append({
            "run_id": str(row.get("run_id", "")),
            "attempt_id": str(row.get("attempt_id", "")),
            "warmup_requested": requested,
            "warmup_completed": completed,
            "status": status,
            "output_signature": signature_text,
            "completed_frames": [str(item) for item in (row.get("completed_frames", []) or [])],
        })
    if not normalized:
        diagnostics.append("warmup_runs_missing")
    elif len(normalized) < 2 or len(set(item["warmup_requested"] for item in normalized if item["warmup_requested"])) < 2:
        diagnostics.append("warmup_comparison_insufficient")
    requested_values = [item["warmup_requested"] for item in normalized if item["warmup_requested"]]
    if requested_values and any(value < int(required_range[0]) or value > int(required_range[-1]) for value in requested_values):
        diagnostics.append("warmup_outside_recommended_range")
    if normalized and any(item["status"] not in {"completed", "ready", "success"} for item in normalized):
        diagnostics.append("warmup_attempt_incomplete")
    if normalized and any(not item["output_signature"] for item in normalized):
        diagnostics.append("warmup_output_signature_missing")
    stable = bool(normalized) and not diagnostics and len(set(signatures)) <= 1 and len(signatures) == len(normalized)
    return {
        "schema_version": WARMUP_SCHEMA,
        "status": "stable" if stable else "warmup_sensitive" if normalized else "not_available",
        "required_range": [int(required_range[0]), int(required_range[-1])],
        "runs": normalized,
        "metrics": {
            "run_count": len(normalized),
            "requested_values": requested_values,
            "unique_output_signatures": len(set(signatures)),
            "stable": stable,
        },
        "diagnostics": list(dict.fromkeys(diagnostics)),
        "conclusion_level": "facts_only",
        "limitations": ["warm-up stability is a consistency observation, not proof of perception correctness"],
    }


def build_perception_injection_audit(
    *,
    preflight: Mapping[str, Any] | None = None,
    target_usage: Mapping[str, Any] | None = None,
    stage_coverage: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Keep injection macro and target-source observations separate from replay success."""
    pf = _mapping(preflight)
    build = _mapping(pf.get("build"))
    macros = _mapping(build.get("macros"))
    macro_presence = _mapping(build.get("macro_presence"))
    injection_macros = {
        str(key): value for key, value in macros.items()
        if "INJECTION" in str(key).upper() or "SGU" in str(key).upper()
    }
    explicit_target = dict(target_usage) if isinstance(target_usage, Mapping) else {}
    enabled_values = []
    for key, value in injection_macros.items():
        text = str(value).strip().lower()
        if text in {"1", "true", "on", "yes", "enabled"}:
            enabled_values.append(key)
    injection_enabled: bool | None = True if enabled_values else False if injection_macros else None
    if injection_enabled is None and str(macro_presence.get("PF_BUILD_FUNTEST_SGU_INJECTION", "")) == "absent":
        injection_enabled = False
    if explicit_target.get("injection_detected") is True:
        injection_enabled = True
    stage_rows = _mapping(stage_coverage).get("stages")
    runtime_stage_count = 0
    if isinstance(stage_rows, Sequence) and not isinstance(stage_rows, (str, bytes, bytearray)):
        runtime_stage_count = sum(
            1 for row in stage_rows if isinstance(row, Mapping) and str(row.get("runtime_proof", "")) in {"observed", "completed"}
        )
    diagnostics: list[str] = []
    if injection_enabled is True:
        diagnostics.append("target_injection_or_injection_macro_enabled")
    if injection_enabled is None:
        diagnostics.append("injection_macro_state_missing")
    if explicit_target.get("status") in (None, "", "not_available"):
        diagnostics.append("target_usage_source_missing")
    if runtime_stage_count == 0:
        diagnostics.append("perception_stage_runtime_proof_missing")
    status = "observed" if injection_enabled is not None or explicit_target else "not_available"
    return {
        "schema_version": INJECTION_SCHEMA,
        "status": status,
        "injection_enabled": injection_enabled,
        "injection_macros": injection_macros,
        "target_usage": explicit_target,
        "runtime_stage_count": runtime_stage_count,
        "gates": {
            "target_injection_absent": "passed" if injection_enabled is False else "blocked" if injection_enabled is True else "not_available",
            "perception_stage_runtime": "passed" if runtime_stage_count else "not_available",
        },
        "diagnostics": list(dict.fromkeys(diagnostics)),
        "conclusion_level": "facts_only",
    }


def build_perception_hypothesis_set(
    hypotheses: Sequence[Mapping[str, Any]] | None = None,
    experiments: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Carry up to three AI/user candidates without upgrading evidence status."""
    source_rows = [dict(item) for item in (hypotheses or []) if isinstance(item, Mapping)]
    experiment_rows = [dict(item) for item in (experiments or []) if isinstance(item, Mapping)]
    diagnostics: list[str] = []
    if len(source_rows) > 3:
        diagnostics.append("hypothesis_list_truncated_to_top_3")
    normalized: list[dict[str, Any]] = []
    for index, row in enumerate(source_rows[:3], start=1):
        normalized.append({
            "rank": row.get("rank", index),
            "category": str(row.get("category", "unknown")),
            "statement": str(row.get("statement", "")),
            "status": str(row.get("status", "candidate")),
            "confidence_band": str(row.get("confidence_band", "unknown")),
            "evidence_status": str(row.get("evidence_status", "not_available")),
            "supporting_refs": list(row.get("supporting_refs", row.get("evidence_refs", [])) or []),
            "contradicting_refs": list(row.get("contradicting_refs", []) or []),
            "required_experiment": row.get("required_experiment", row.get("experiment", {})),
            "limitations": list(row.get("limitations", []) or []),
        })
    for item in normalized:
        if not item["statement"]:
            diagnostics.append(f"hypothesis_statement_missing_rank:{item['rank']}")
    return {
        "schema_version": HYPOTHESIS_SCHEMA,
        "status": "provided" if normalized or experiment_rows else "not_available",
        "hypotheses": normalized,
        "experiments": experiment_rows,
        "diagnostics": list(dict.fromkeys(diagnostics)),
        "conclusion_level": "candidate_only",
        "limitations": ["hypotheses are candidates only; they do not create observed claims or confirm a root cause"],
    }


def build_perception_capability_manifest(
    *,
    input_contract: Mapping[str, Any],
    stage_coverage: Mapping[str, Any],
    source_context: Mapping[str, Any] | None = None,
    replay_plan: Mapping[str, Any] | None = None,
    run_evidence: Mapping[str, Any] | None = None,
    execution_binding: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Declare what the supplied point-cloud artifacts prove for routing."""
    contract = _mapping(input_contract)
    coverage = _mapping(stage_coverage)
    context = _mapping(source_context)
    plan = _mapping(replay_plan)
    run = _mapping(run_evidence)
    binding = _mapping(execution_binding)
    binding_status = str(binding.get("status") or "not_available")
    binding_hash = str(binding.get("binding_hash") or "").strip()
    plan_identity = _mapping(plan.get("identity"))
    run_identity = _mapping(run.get("identity"))
    plan_status = str(plan.get("status") or "not_available")
    run_status = str(run.get("status") or "not_available")
    stages = coverage.get("stages") if isinstance(coverage.get("stages"), Sequence) and not isinstance(coverage.get("stages"), (str, bytes, bytearray)) else []
    runtime_stages = [
        str(row.get("stage")) for row in stages
        if isinstance(row, Mapping)
        and str(row.get("status")) == "completed"
        and str(row.get("runtime_proof", "")) in {"observed", "completed"}
    ]
    unsupported: list[dict[str, Any]] = []
    if str(contract.get("status")) != "ready":
        unsupported.append({"id": "point-cloud-input", "reason": "input_contract_not_ready", "required_inputs": ["range", "azimuth", "doppler"]})
    if not runtime_stages:
        unsupported.append({"id": "perception-runtime-stages", "reason": "stage_runtime_proof_missing", "required_inputs": ["stage producer or runtime trace"]})
    if plan_status != "ready":
        unsupported.append({
            "id": "point-cloud-replay-plan",
            "reason": "replay_plan_blocked" if plan_status == "blocked" else "replay_plan_not_ready" if plan else "replay_plan_missing",
            "required_inputs": ["identity-bound point-cloud-replay-plan.v1 with status=ready"],
        })
    if run_status != "completed" or str(run.get("runtime_proof") or "") not in {"observed", "completed"}:
        unsupported.append({
            "id": "perception-run",
            "reason": "runtime_run_not_completed",
            "required_inputs": ["producer-owned completed run, reset/warm-up evidence, and completed frames"],
        })
    if binding_status != "verified" or not binding_hash:
        unsupported.append({
            "id": "execution-binding",
            "reason": "execution_binding_not_verified",
            "required_inputs": ["revalidated approved binding for this plan and run"],
        })

    identity_sources: dict[str, list[Any]] = {
        "data_fingerprint": [contract.get("data_fingerprint"), context.get("data_fingerprint")],
        "source_context_id": [
            contract.get("source_context_id"),
            context.get("source_context_id"),
            context.get("source_context_fingerprint"),
        ],
        "binary_fingerprint": [context.get("binary_fingerprint")],
        "config_fingerprint": [context.get("config_fingerprint")],
        "session_id": [context.get("session_id")],
    }
    identity: dict[str, str] = {}
    identity_missing: list[str] = []
    identity_conflicts: list[str] = []
    for field, raw_values in identity_sources.items():
        values = list(dict.fromkeys(str(value).strip() for value in raw_values if value not in (None, "") and str(value).strip()))
        expected = values[0] if values else ""
        plan_value = str(plan_identity.get(field) or "").strip()
        run_value = str(run_identity.get(field) or "").strip()
        identity[field] = expected or plan_value or run_value
        if len(values) > 1:
            identity_conflicts.append(field)
        if not expected:
            identity_missing.append(field)
        for source_name, observed in (("plan", plan_value), ("run", run_value)):
            if not observed:
                identity_missing.append(f"{source_name}.{field}")
            elif expected and observed != expected:
                identity_conflicts.append(f"{source_name}.{field}")
        if plan_value and run_value and plan_value != run_value:
            identity_conflicts.append(f"plan_run.{field}")
    identity_conflicts.extend(
        str(item) for item in context.get("identity_conflicts", []) or [] if str(item).strip()
    )

    runtime_binding = _mapping(plan.get("runtime_binding"))
    target = _mapping(plan.get("target"))
    target_server = _mapping(target.get("server"))
    plan_hash = str(plan.get("plan_hash") or "").strip()
    run_plan_hash = str(run.get("plan_hash") or run_identity.get("plan_hash") or "").strip()
    binding_plan_hash = str(binding.get("point_cloud_plan_hash") or "").strip()
    binding_run_id = str(binding.get("run_id") or "").strip()
    run_id = str(run.get("run_id") or "").strip()
    attempt_id = str(run.get("attempt_id") or "").strip()
    if binding_status != "verified" or not binding_hash:
        identity_missing.append("execution_binding_verification")
    if not binding_plan_hash:
        identity_missing.append("execution_binding.point_cloud_plan_hash")
    elif plan_hash and binding_plan_hash != plan_hash:
        identity_conflicts.append("execution_binding.point_cloud_plan_hash")
    if not binding_run_id or not run_id:
        identity_missing.append("execution_binding.run_id")
    elif binding_run_id != run_id:
        identity_conflicts.append("execution_binding.run_id")
    if not run_id:
        identity_missing.append("run.run_id")
    if not attempt_id:
        identity_missing.append("run.attempt_id")
    if not plan_hash:
        identity_missing.append("plan.plan_hash")
    if not run_plan_hash:
        identity_missing.append("run.plan_hash")
    elif plan_hash and run_plan_hash != plan_hash:
        identity_conflicts.append("run.plan_hash")
    if str(runtime_binding.get("status") or "") == "conflict":
        identity_conflicts.append("runtime_workspace")
    elif (
        str(runtime_binding.get("status") or "") != "aligned"
        or not str(runtime_binding.get("workspace_root") or "").strip()
        or not str(target_server.get("host") or "").strip()
    ):
        identity_missing.append("plan.runtime_target_binding")
    identity_missing = list(dict.fromkeys(identity_missing))
    identity_conflicts = list(dict.fromkeys(identity_conflicts))
    identity_binding_status = "conflict" if identity_conflicts else "partial" if identity_missing else "aligned"
    if identity_conflicts or identity_missing:
        unsupported.append({
            "id": "execution-identity",
            "reason": "execution_identity_conflict" if identity_conflicts else "execution_identity_not_bound_across_context_plan_and_run",
            "required_inputs": list(dict.fromkeys(identity_conflicts + identity_missing)),
        })

    freshness_verified = (
        plan_status == "ready"
        and run_status == "completed"
        and str(run.get("runtime_proof") or "") in {"observed", "completed"}
        and identity_binding_status == "aligned"
        and bool(plan_hash)
        and plan_hash == run_plan_hash
        and binding_status == "verified"
        and bool(binding_hash)
        and binding_plan_hash == plan_hash
        and binding_run_id == run_id
        and str(runtime_binding.get("status") or "") == "aligned"
        and bool(str(runtime_binding.get("workspace_root") or "").strip())
        and bool(str(target_server.get("host") or "").strip())
    )
    freshness_status = "conflict" if identity_conflicts else "verified" if freshness_verified else "partial"
    data_fingerprint = identity.get("data_fingerprint", "")
    source_id = identity.get("source_context_id", "")
    binary = identity.get("binary_fingerprint", "")
    config = identity.get("config_fingerprint", "")
    session_id = identity.get("session_id", "")
    if not binary:
        unsupported.append({"id": "binary-identity", "reason": "binary_fingerprint_missing", "required_inputs": ["execution binding/preflight"]})
    if not config:
        unsupported.append({"id": "config-identity", "reason": "config_fingerprint_missing", "required_inputs": ["resolved configuration fingerprint"]})
    status = (
        "blocked"
        if identity_conflicts or contract.get("status") in {"blocked", "not_available"}
        else "ready"
        if str(contract.get("status")) == "ready" and runtime_stages and freshness_verified and not unsupported
        else "partial"
    )
    return {
        "schema_version": CAPABILITY_SCHEMA,
        "status": status,
        "strategy": str(contract.get("strategy", "point_cloud")),
        "identity": {
            "data_fingerprint": data_fingerprint,
            "source_context_id": source_id,
            "binary_fingerprint": binary,
            "config_fingerprint": config,
            "session_id": session_id,
        },
        "identity_binding": {
            "status": identity_binding_status,
            "plan_hash": plan_hash,
            "run_plan_hash": run_plan_hash,
            "run_id": run_id,
            "attempt_id": attempt_id,
            "workspace_root": str(runtime_binding.get("workspace_root") or ""),
            "server_host": str(target_server.get("host") or ""),
            "execution_binding_status": binding_status,
            "execution_binding_hash": binding_hash,
            "binding_plan_hash": binding_plan_hash,
            "binding_run_id": binding_run_id,
            "missing_fields": identity_missing,
            "conflicts": identity_conflicts,
        },
        "supported_stages": list(dict.fromkeys(runtime_stages)),
        "static_stage_count": sum(1 for row in stages if isinstance(row, Mapping) and row.get("source_ref")),
        "runtime_stage_count": len(runtime_stages),
        "supported_paths": {
            "post_detection_point_cloud": status if str(contract.get("status")) in {"ready", "partial"} else "blocked",
            "raw_sensor_frontend": "not_available",
        },
        "unsupported": unsupported,
        "freshness": {
            "status": freshness_status,
            "basis": ["contract/context identity", "ready plan identity", "completed run identity", "aligned runtime workspace", "plan/run fingerprint equality"],
            "data_fingerprint": data_fingerprint,
            "source_context_id": source_id,
            "binary_fingerprint": binary,
            "config_fingerprint": config,
            "session_id": session_id,
        },
        "run_status": run_status,
        "diagnostics": [] if status == "ready" else list(dict.fromkeys(item["reason"] for item in unsupported)),
    }


def build_perception_validation(
    *,
    report: Mapping[str, Any],
    analysis: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate cross-artifact invariants after report projection."""
    errors: list[str] = []
    warnings: list[str] = []
    contract = _mapping(analysis.get("input_contract"))
    coverage = _mapping(analysis.get("stage_coverage"))
    lineage = _mapping(analysis.get("lineage"))
    run = _mapping(analysis.get("run_evidence"))
    hypotheses = _mapping(analysis.get("hypothesis_set")).get("hypotheses")
    hypotheses = hypotheses if isinstance(hypotheses, Sequence) and not isinstance(hypotheses, (str, bytes, bytearray)) else []
    if report.get("schema_version") != "perception-report.v1":
        errors.append("report_schema_mismatch")
    points = contract.get("points", []) or []
    if contract.get("points_truncated"):
        if contract.get("inline_point_count") != len(points) or int(contract.get("inline_point_count", 0)) > int(contract.get("point_count", 0)):
            errors.append("input_inline_point_count_mismatch")
        warnings.append("points_inline_truncated_to_bounded_report")
    elif contract.get("point_count") != len(points):
        errors.append("input_point_count_mismatch")
    stages = coverage.get("stages")
    if isinstance(stages, Sequence) and not isinstance(stages, (str, bytes, bytearray)):
        available = sum(
            1 for item in stages
            if isinstance(item, Mapping)
            and str(item.get("status")) == "completed"
            and str(item.get("runtime_proof", "")) in {"observed", "completed"}
        )
        if coverage.get("available_stage_count") != available:
            errors.append("stage_available_count_mismatch")
        if coverage.get("total_stage_count") != len(stages):
            errors.append("stage_total_count_mismatch")
    lineage_edges = lineage.get("edges", []) or []
    if lineage.get("edges_truncated"):
        artifact = _mapping(lineage.get("lineage_artifact"))
        counts = _mapping(artifact.get("counts"))
        total_edge_count = _int_or_default(lineage.get("edge_count"), -1)
        if _int_or_default(lineage.get("inline_edge_count"), -1) != len(lineage_edges) or total_edge_count < len(lineage_edges):
            errors.append("lineage_inline_edge_count_mismatch")
        if _int_or_default(counts.get("edge"), -1) != total_edge_count or not artifact.get("sha256") or not artifact.get("path"):
            errors.append("lineage_artifact_edge_count_mismatch")
        warnings.append("lineage_edges_truncated_to_bounded_report")
    elif lineage.get("edge_count") != len(lineage_edges):
        errors.append("lineage_edge_count_mismatch")
    if not lineage.get("edges_truncated"):
        observed_relation_counts: dict[str, int] = {}
        observed_relation_summaries: dict[str, dict[str, int]] = {}
        for edge in lineage_edges:
            if not isinstance(edge, Mapping):
                continue
            relation_kind = str(edge.get("relation_kind") or edge.get("kind") or "")
            if not relation_kind:
                continue
            observed_relation_counts[relation_kind] = observed_relation_counts.get(relation_kind, 0) + 1
            summary = observed_relation_summaries.setdefault(relation_kind, {
                "from_node_kind": str(edge.get("from_node_kind") or "not_available"),
                "to_node_kind": str(edge.get("to_node_kind") or "not_available"),
                "edge_row_count": 0,
                "unique_pair_count": 0,
                "unique_from_node_count": 0,
                "unique_to_node_count": 0,
            })
            summary["edge_row_count"] += 1
        for relation_kind, summary in observed_relation_summaries.items():
            relation_rows = [edge for edge in lineage_edges if isinstance(edge, Mapping) and str(edge.get("relation_kind") or edge.get("kind") or "") == relation_kind]
            summary["unique_pair_count"] = len({(str(edge.get("from") or edge.get("source") or ""), str(edge.get("to") or edge.get("target") or "")) for edge in relation_rows})
            summary["unique_from_node_count"] = len({str(edge.get("from") or edge.get("source") or "") for edge in relation_rows})
            summary["unique_to_node_count"] = len({str(edge.get("to") or edge.get("target") or "") for edge in relation_rows})
        if lineage.get("relation_counts") is not None and dict(lineage.get("relation_counts") or {}) != observed_relation_counts:
            errors.append("lineage_relation_count_mismatch")
        if lineage.get("relation_summaries") is not None and dict(lineage.get("relation_summaries") or {}) != observed_relation_summaries:
            errors.append("lineage_relation_summary_mismatch")
    if not lineage.get("raw_edges_truncated"):
        raw_relation_rows = lineage.get("raw_edges", []) or []
        observed_raw_relation_counts: dict[str, int] = {}
        for edge in raw_relation_rows:
            if not isinstance(edge, Mapping):
                continue
            relation_kind = str(edge.get("relation_kind") or edge.get("kind") or "")
            if relation_kind:
                observed_raw_relation_counts[relation_kind] = observed_raw_relation_counts.get(relation_kind, 0) + 1
        if lineage.get("raw_relation_counts") is not None and dict(lineage.get("raw_relation_counts") or {}) != observed_raw_relation_counts:
            errors.append("lineage_raw_relation_count_mismatch")
    for rows_key, count_key, artifact_key in (
        ("raw_edges", "raw_edge_count", "raw_edge"),
        ("invalid_edges", "invalid_edge_count", "invalid_edge"),
    ):
        rows = lineage.get(rows_key, []) or []
        if lineage.get(f"{rows_key}_truncated"):
            artifact = _mapping(lineage.get("lineage_artifact"))
            counts = _mapping(artifact.get("counts"))
            total = _int_or_default(lineage.get(count_key), -1)
            inline = _int_or_default(lineage.get(f"inline_{rows_key}_count"), -1)
            if inline != len(rows) or total < len(rows) or _int_or_default(counts.get(artifact_key), -1) != total:
                errors.append(f"lineage_artifact_count_mismatch:{artifact_key}")
        elif lineage.get(count_key) is not None and _int_or_default(lineage.get(count_key), -1) != len(rows):
            errors.append(f"lineage_count_mismatch:{artifact_key}")
    lineage_nodes = _mapping(lineage.get("nodes"))
    full_node_counts = _mapping(lineage.get("node_counts"))
    inline_node_counts = _mapping(lineage.get("inline_node_counts"))
    for kind in ("points", "clusters", "tracks", "outputs"):
        inline_count = len(lineage_nodes.get(kind, []) or [])
        full_count = _int_or_default(full_node_counts.get(kind, inline_count), inline_count)
        if inline_node_counts and _int_or_default(inline_node_counts.get(kind, -1), -1) != inline_count:
            errors.append(f"lineage_inline_node_count_mismatch:{kind}")
        if full_count < inline_count:
            errors.append(f"lineage_node_count_mismatch:{kind}")
    track_population = _mapping(lineage.get("track_population"))
    if track_population.get("scope") == "public_objectlist_output_rows":
        if track_population.get("status") not in {"observed_subset", "not_available"}:
            errors.append("track_population_status_mismatch")
        if track_population.get("track_nodes_mirror_output_rows") is not True:
            errors.append("track_population_mirror_contract_mismatch")
        if track_population.get("internal_candidate_track_population") != "not_available" or track_population.get("internal_mature_track_population") != "not_available":
            errors.append("track_population_internal_state_overclaimed")
        if track_population.get("cluster_supports_track_scope") != "unique_cluster_track_pairs_where_point_track_uid_matches_captured_public_objectlist_id":
            errors.append("track_population_cluster_edge_scope_mismatch")
        if track_population.get("track_emits_output_scope") != "one_unique_derived_edge_per_captured_public_objectlist_output_row":
            errors.append("track_population_output_edge_scope_mismatch")
        if track_population.get("unclustered_point_scope") != "cluster_id_minus_one_has_no_cluster_node_or_point_support_edge; track_lifecycle_not_inferred":
            errors.append("track_population_unclustered_scope_mismatch")
        if _int_or_default(full_node_counts.get("tracks"), -1) != _int_or_default(full_node_counts.get("outputs"), -2):
            errors.append("track_population_output_count_mismatch")
        if track_population.get("status") == "not_available" and _int_or_default(full_node_counts.get("tracks"), 0) != 0:
            errors.append("track_population_status_count_mismatch")
    relation_scopes = _mapping(lineage.get("relation_scopes"))
    point_cluster_scope = _mapping(relation_scopes.get("point_supports_cluster"))
    if point_cluster_scope and point_cluster_scope.get("inclusion_condition") != "cluster_id > 0":
        errors.append("relation_scope_inclusion_mismatch:point_supports_cluster")
    if lineage.get("nodes_truncated") and not _mapping(lineage.get("lineage_artifact")).get("path"):
        errors.append("lineage_artifact_missing_for_truncated_nodes")
    if str(analysis.get("status")) == "ready":
        if str(contract.get("status") or "") != "ready":
            errors.append("ready_without_ready_input_contract")
        if str(run.get("status")) not in {"completed", "ready"}:
            errors.append("ready_without_completed_run")
        if str(coverage.get("status")) != "ready":
            errors.append("ready_without_stage_coverage")
        if str(lineage.get("status")) != "observed":
            errors.append("ready_without_lineage")
    if len(hypotheses) > 3:
        errors.append("hypothesis_top3_limit_exceeded")
    capability = _mapping(analysis.get("capability_manifest"))
    if str(capability.get("status")) == "ready" and not capability.get("runtime_stage_count"):
        errors.append("capability_ready_without_runtime_stage")
    if str(analysis.get("status")) == "ready":
        if str(capability.get("status") or "") != "ready":
            errors.append("ready_without_ready_capability_manifest")
        if str(_mapping(capability.get("freshness")).get("status") or "") != "verified":
            errors.append("ready_without_verified_capability_freshness")
        if str(_mapping(capability.get("identity_binding")).get("status") or "") != "aligned":
            errors.append("ready_without_aligned_execution_identity")
    artifact = _mapping(contract.get("artifact_audit"))
    if str(artifact.get("status")) == "supported" and not str(artifact.get("sha256") or ""):
        warnings.append("supported_artifact_hash_missing")
    scene = _mapping(analysis.get("scene"))
    if scene.get("selected_frame") not in (None, "") and str(scene.get("status")) == "not_available":
        warnings.append("selected_frame_scene_not_available")
    status = "invalid" if errors else "valid_with_warnings" if warnings else "valid"
    return {
        "schema_version": VALIDATION_SCHEMA,
        "status": status,
        "errors": list(dict.fromkeys(errors)),
        "warnings": list(dict.fromkeys(warnings)),
        "checks": {
            "report_schema": report.get("schema_version") == "perception-report.v1",
            "point_count": not any(item in errors for item in ("input_point_count_mismatch", "input_inline_point_count_mismatch")),
            "stage_counts": not any(item.startswith("stage_") for item in errors),
            "lineage_count": "lineage_edge_count_mismatch" not in errors,
            "relation_counts": not any(item.startswith("lineage_relation_") for item in errors),
            "ready_policy": not any(item.startswith("ready_") for item in errors),
            "hypothesis_limit": "hypothesis_top3_limit_exceeded" not in errors,
            "track_population_scope": not any(item.startswith("track_population_") for item in errors),
            "relation_scopes": not any(item.startswith("relation_scope_") for item in errors),
        },
        "conclusion_level": "validation_only",
    }


def build_perception_comparison(
    *,
    recorded_rows: Sequence[Mapping[str, Any]] | None = None,
    replay_rows: Sequence[Mapping[str, Any]] | None = None,
    explicit_matches: Sequence[Mapping[str, Any]] | None = None,
    alignment: Mapping[str, Any] | None = None,
    recorded_identity: Mapping[str, Any] | None = None,
    replay_identity: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compare two layers using explicit frame/identity evidence only.

    No match is created from timestamp proximity, array position, or equal
    numeric IDs across strategies.  Consumers can pass producer-owned match
    rows, or opt into deterministic exact-key matching with an explicit
    ``alignment.method``.
    """
    recorded = [dict(item) for item in (recorded_rows or []) if isinstance(item, Mapping)]
    replay = [dict(item) for item in (replay_rows or []) if isinstance(item, Mapping)]
    alignment_obj = dict(alignment or {})
    matches = [dict(item) for item in (explicit_matches or []) if isinstance(item, Mapping)]
    diagnostics: list[str] = []
    match_basis = "explicit_producer_match"
    if not matches and alignment_obj.get("method") in {"exact_frame_key", "explicit_identity"}:
        key_fields = alignment_obj.get("key_fields") or ["radar_id", "frame_id", "object_key"]
        key_fields = [str(item) for item in key_fields if str(item).strip()]
        right_by_key: dict[tuple[str, ...], dict[str, Any]] = {}
        for row in replay:
            key = tuple(str(row.get(field, "")) for field in key_fields)
            if all(key):
                right_by_key.setdefault(key, row)
        for left in recorded:
            key = tuple(str(left.get(field, "")) for field in key_fields)
            right = right_by_key.get(key) if all(key) else None
            if right is not None:
                matches.append({
                    "left": left,
                    "right": right,
                    "status": "derived",
                    "basis_ref": {"method": alignment_obj.get("method"), "key_fields": key_fields},
                })
        match_basis = "deterministic_exact_key"
    if not matches:
        diagnostics.append("explicit_frame_identity_match_missing")
    else:
        def _comparison_order(item: Mapping[str, Any]) -> tuple[int, str]:
            right = item.get("right") if isinstance(item.get("right"), Mapping) else {}
            left = item.get("left") if isinstance(item.get("left"), Mapping) else {}
            token = _frame_key(right) or _frame_key(left)
            try:
                return (0, f"{int(token):020d}")
            except (TypeError, ValueError):
                return (1, token)
        matches.sort(key=_comparison_order)
    divergence = None
    compared_field_count = 0
    differing_field_count = 0
    for item in matches:
        left = item.get("left") if isinstance(item.get("left"), Mapping) else {}
        right = item.get("right") if isinstance(item.get("right"), Mapping) else {}
        fields = item.get("fields") or alignment_obj.get("compare_fields") or ("range", "azimuth", "doppler", "track_id", "status")
        differences = []
        for field in fields:
            field = str(field)
            if field not in left or field not in right:
                continue
            compared_field_count += 1
            if left.get(field) != right.get(field):
                differences.append({"field": field, "recorded": left.get(field), "replay": right.get(field)})
        if differences and divergence is None:
            divergence = {
                "frame_id": _frame_key(right) or _frame_key(left) or "",
                "radar_id": right.get("radar_id", left.get("radar_id", "")),
                "differences": differences,
                "basis_ref": item.get("basis_ref") or {"match_basis": match_basis},
            }
        differing_field_count += len(differences)
    explicit_observed = any(str(item.get("status", "")) == "observed" for item in matches)
    status = "observed" if explicit_observed else "derived" if matches else "not_available"
    if matches and not compared_field_count:
        diagnostics.append("comparison_fields_unavailable")
    if recorded_identity and replay_identity and dict(recorded_identity) != dict(replay_identity):
        diagnostics.append("recorded_replay_identity_differs")
    return {
        "schema_version": COMPARISON_SCHEMA,
        "status": status,
        "recorded_identity": dict(recorded_identity or {}),
        "replay_identity": dict(replay_identity or {}),
        "alignment": alignment_obj,
        "match_basis": match_basis,
        "recorded_row_count": len(recorded),
        "replay_row_count": len(replay),
        "match_count": len(matches),
        "matches": matches,
        "first_divergence": divergence,
        "metrics": {
            "compared_field_count": compared_field_count,
            "differing_field_count": differing_field_count,
            "consistency_ratio": (1.0 - differing_field_count / compared_field_count) if compared_field_count else None,
            "precision_recall_available": False,
            "precision_recall_reason": "trusted_ground_truth_not_supplied",
        },
        "diagnostics": list(dict.fromkeys(diagnostics)),
        "conclusion_level": "facts_only",
        "limitations": [
            "equal IDs across strategies are not treated as physical identity without an explicit match basis",
            "no timestamp-nearest or array-index match is inferred",
        ],
    }


__all__ = [
    "PLAN_SCHEMA", "CONTRACT_SCHEMA", "RUN_SCHEMA", "COMPARISON_SCHEMA", "SCENE_SCHEMA", "TIMELINE_SCHEMA", "WARMUP_SCHEMA", "INJECTION_SCHEMA", "HYPOTHESIS_SCHEMA", "CAPABILITY_SCHEMA", "ARTIFACT_SCHEMA", "VALIDATION_SCHEMA", "STAGE_NAMES",
    "build_point_cloud_replay_plan", "audit_runtime_workspace_alignment", "normalize_point_rows", "register_perception_artifact_adapter", "audit_perception_artifact", "load_perception_artifact", "audit_perception_capture",
    "build_perception_input_contract", "build_stage_coverage",
    "build_perception_lineage", "build_perception_analysis",
    "build_perception_run_evidence", "build_perception_warmup_analysis", "build_perception_injection_audit", "build_perception_hypothesis_set", "build_perception_capability_manifest", "build_perception_validation", "build_perception_comparison", "build_perception_code_flow",
    "build_perception_scene", "build_perception_timeline",
]
