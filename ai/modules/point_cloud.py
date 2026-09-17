"""Point-cloud perception input audit and evidence report module."""
from __future__ import annotations

import html
import hashlib
import json
import math
import time
import uuid
from pathlib import Path
from typing import Any, Mapping, Sequence

from engines.point_cloud_replay import (
    build_perception_analysis,
    build_perception_input_contract,
    build_perception_lineage,
    build_stage_coverage,
    build_perception_stage_map,
    build_perception_run_evidence,
    build_perception_comparison,
    build_perception_code_flow,
    audit_perception_capture,
    build_perception_scene,
    build_perception_timeline,
    build_perception_warmup_analysis,
    build_perception_hypothesis_set,
    build_perception_capability_manifest,
    load_perception_artifact,
    build_perception_validation,
    audit_public_perception_source_contract,
    bind_public_perception_capture,
)

from .base import BaseModule, ModuleResult


_POINT_CLOUD_OUTPUT_ROOT = Path(__file__).resolve().parents[2] / "outputs" / "point_cloud_analysis"
_STATUS_LABELS = {
    "blocked": "受阻",
    "partial": "部分证据",
    "ready": "证据可用",
    "not_available": "不可用",
    "unknown": "未知",
    "observed": "已观测",
    "derived": "推导",
    "completed": "已完成",
    "planned": "已计划",
    "source_candidate": "源码候选",
    "runtime_observed": "运行时观测",
    "runtime_derived": "运行时推导",
    "valid": "有效",
    "valid_with_warnings": "有效但有提示",
    "not_required": "不要求",
}
_INPUT_BOUNDARY_LABELS = {
    "not_available": "未提供点云输入",
    "target_only": "仅有目标输出，缺少前级点云",
    "target_injection_only": "仅有目标注入数据，不能作为感知输入",
    "empty_public_pointcloud_observation": "观测到空的公开点云消息",
    "post_detection_point_cloud": "后处理点云",
}
_CONCLUSION_LABELS = {
    "facts_only": "事实与缺口",
    "candidate_only": "候选原因",
    "inference": "推理结论",
}
_STRATEGY_LABELS = {
    "point_cloud": "点云前级感知",
    "sgu_injection": "SGU 目标注入",
}
_STAGE_LABELS = {
    "input_decode": "输入解析",
    "dot_preprocess": "点迹预处理",
    "environment_detect": "环境检测",
    "dot_filter": "点迹过滤",
    "cluster": "聚类",
    "track": "航迹跟踪",
    "track_output": "航迹输出",
    "adas_func": "ADAS 功能输出",
}


def _html_token_label(value: Any, labels: Mapping[str, str]) -> str:
    token = str(value or "not_available")
    label = labels.get(token, "未映射")
    return f"{html.escape(label)} <code>{html.escape(token)}</code>"


def _new_point_cloud_output_dir() -> Path:
    stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime())
    return _POINT_CLOUD_OUTPUT_ROOT / f"run-{stamp}-{uuid.uuid4().hex[:8]}"


def _write_offline_readme(directory: Path) -> Path:
    path = directory / "perception-report-README.md"
    path.write_text(
        "# Perception report bundle\n\n"
        "Keep this directory intact so the report can resolve its relative JSONL evidence attachments; "
        "the report-local JSONL and index references remain valid if the whole folder is copied. "
        "The HTML scene is self-contained and does not load external web assets.\n\n"
        "## Open offline\n\n"
        "1. Open a terminal in this directory.\n"
        "2. Run `python -m http.server 8765 --bind 127.0.0.1`.\n"
        "3. Open `http://127.0.0.1:8765/perception-report.html` in a browser.\n"
        "4. Stop the local server with `Ctrl+C` when finished.\n\n"
        "The server binds only to localhost and serves these local files; no external network is required. "
        "The report status and evidence gaps remain authoritative even when the HTML renders successfully.\n",
        encoding="utf-8",
    )
    return path


def _load(value: Mapping[str, Any] | None, path: str) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if not path:
        return {}
    try:
        payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def _load_capture(value: Mapping[str, Any] | None, path: str) -> tuple[dict[str, Any], dict[str, Any]]:
    if isinstance(value, Mapping):
        return dict(value), {}
    if not path:
        return {}, {}
    payload = load_perception_artifact(path)
    audit = payload.pop("_artifact_audit", {}) if isinstance(payload, Mapping) else {}
    return dict(payload) if isinstance(payload, Mapping) else {}, dict(audit) if isinstance(audit, Mapping) else {}


def _rows(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, Mapping):
        return [dict(value)]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [dict(item) for item in value if isinstance(item, Mapping)]
    return []


def _bounded_code_context(value: Mapping[str, Any], path: str) -> dict[str, Any]:
    """Project stage definitions and one-hop callers/callees in one index read."""
    context = dict(value)
    artifacts = context.get("artifacts") if isinstance(context.get("artifacts"), Mapping) else {}
    index_path = str(artifacts.get("code_index") or "")
    if not index_path:
        return context
    index_file = Path(index_path).expanduser().resolve()
    if not index_file.exists():
        raise FileNotFoundError(f"code index artifact not found: {index_file}")
    index = json.loads(index_file.read_text(encoding="utf-8"))
    if not isinstance(index, Mapping):
        raise ValueError("code index root must be an object")

    focus_functions = (
        "PostProcessMainTI", "DataProcInit", "DotPrePosTI", "EnvModelDetect", "DotFilter",
        "ObjCluster", "ObjTrack", "OutputTrkObj", "AdasFunc", "FrontRadarAdas",
        "FrontCrossTrafficAlertAndBrake", "FctaSkipFlg", "FctaDirectRunning", "FctaTurning",
        "HandleFctaLeftWarningFlag", "HandleFctbLeftWarningFlag",
        "HandleFctaRightWarningFlag", "HandleFctbRightWarningFlag",
    )
    def _leaf_function_name(value: Any) -> str:
        return str(value or "").rsplit("::", 1)[-1]

    focus_set = set(focus_functions)
    raw_calls = index.get("calls") if isinstance(index.get("calls"), Mapping) else {}
    calls: dict[str, list[str]] = {}
    related_function_names = set(focus_functions)
    for caller, raw_callees in raw_calls.items():
        caller_name = str(caller)
        callees = [
            str(item)
            for item in raw_callees or []
            if item not in (None, "")
        ] if isinstance(raw_callees, Sequence) and not isinstance(raw_callees, (str, bytes, bytearray)) else []
        caller_match = _leaf_function_name(caller_name) in focus_set
        matched_callees = [
            item for item in callees
            if _leaf_function_name(item) in focus_set
        ]
        if caller_match:
            selected_callees = callees
            related_function_names.add(caller_name)
            related_function_names.update(callees)
        elif matched_callees:
            selected_callees = matched_callees
            related_function_names.add(caller_name)
            related_function_names.update(matched_callees)
        else:
            continue
        output = calls.setdefault(caller_name, [])
        for callee in selected_callees:
            if callee not in output:
                output.append(callee)
    calls = {name: calls[name] for name in sorted(calls)}

    raw_functions = index.get("functions") if isinstance(index.get("functions"), list) else []
    functions: list[dict[str, Any]] = []
    function_seen: set[tuple[str, str, int]] = set()
    relevant_leaves = {_leaf_function_name(name) for name in related_function_names}
    for item in raw_functions:
        if not isinstance(item, Mapping):
            continue
        name = str(item.get("name", ""))
        if _leaf_function_name(name) not in relevant_leaves:
            continue
        identity = (
            name,
            str(item.get("file_path", "")),
            int(item.get("start_line") or 0),
        )
        if identity not in function_seen:
            function_seen.add(identity)
            functions.append(dict(item))
    functions.sort(key=lambda item: (
        0 if _leaf_function_name(item.get("name", "")) in focus_set else 1,
        str(item.get("file_path", "")),
        int(item.get("start_line") or 0),
        str(item.get("name", "")),
    ))
    matched_focus = sorted({
        _leaf_function_name(item.get("name", ""))
        for item in functions
        if _leaf_function_name(item.get("name", "")) in focus_set
    })
    missing_focus = [name for name in focus_functions if name not in matched_focus]
    functions_truncated = len(functions) > 80
    functions = functions[:80]

    conditions: list[dict[str, Any]] = []
    condition_seen: set[str] = set()
    raw_conditions = index.get("conditions") if isinstance(index.get("conditions"), list) else []
    condition_texts = [
        json.dumps(item, ensure_ascii=False, sort_keys=True, default=str).lower()
        if isinstance(item, Mapping) else ""
        for item in raw_conditions
    ]
    conditions_truncated = False
    for token in ("fcta", "fctb", "bLeftFctaWarning", "bRightFctaWarning"):
        matched_conditions = [
            item for item, rendered in zip(raw_conditions, condition_texts)
            if token.lower() in rendered and isinstance(item, Mapping)
        ]
        if len(matched_conditions) > 30:
            conditions_truncated = True
        for item in matched_conditions[:30]:
            key = json.dumps(item, ensure_ascii=False, sort_keys=True, default=str)
            if key not in condition_seen:
                condition_seen.add(key)
                conditions.append(dict(item))
    conditions_truncated = conditions_truncated or len(conditions) > 120
    conditions = conditions[:120]
    return {
        "schema_version": context.get("schema_version", "code-context.v1"),
        "context_id": context.get("context_id", ""),
        "source_context": context.get("source_context", {}),
        "artifact_path": context.get("artifact_path") or path,
        "index_path": index_path,
        "summary": context.get("summary", {}),
        "calls": calls,
        "functions": functions,
        "conditions": conditions[:120],
        "function_resolution": {
            "basis": "exact function name or qualified leaf name from code-index",
            "requested_names": list(focus_functions),
            "matched_names": matched_focus,
            "missing_names": missing_focus,
            "truncated": functions_truncated,
        },
        "truncated": {"functions": functions_truncated, "conditions": conditions_truncated},
        "limitations": [
            "bounded source context projection; full Code Context index remains available at index_path",
            "function rows are selected by exact stage name or direct call-neighbor name; substring collisions are not treated as definitions",
        ],
    }


def _write_point_artifact(points: Sequence[Mapping[str, Any]], directory: Path) -> dict[str, Any]:
    path = directory / "perception-points.jsonl"
    digest = hashlib.sha256()
    count = 0
    with path.open("w", encoding="utf-8", newline="") as handle:
        for row in points:
            line = json.dumps(dict(row), ensure_ascii=False, separators=(",", ":"), default=str) + "\n"
            handle.write(line)
            digest.update(line.encode("utf-8"))
            count += 1
    return {
        "path": path.name,
        "absolute_path": str(path),
        "format": "jsonl",
        "point_count": count,
        "sha256": digest.hexdigest(),
        "status": "observed",
    }


def _write_lineage_artifact(
    lineage: Mapping[str, Any],
    directory: Path,
    *,
    callback_keys: Sequence[str] = (),
) -> dict[str, Any]:
    """Persist callback-contiguous JSONL plus a hash-bound byte-range index."""
    path = directory / "perception-lineage.jsonl"
    index_path = directory / "perception-lineage-index.v1.json"
    nodes = lineage.get("nodes") if isinstance(lineage.get("nodes"), Mapping) else {}
    row_sources = (
        ("point", nodes.get("points", [])),
        ("cluster", nodes.get("clusters", [])),
        ("track", nodes.get("tracks", [])),
        ("output", nodes.get("outputs", [])),
        ("edge", lineage.get("edges", [])),
        ("raw_edge", lineage.get("raw_edges", [])),
        ("invalid_edge", lineage.get("invalid_edges", [])),
    )
    def row_frame(row: Mapping[str, Any]) -> str:
        raw = row.get("raw") if isinstance(row.get("raw"), Mapping) else {}
        return str(row.get("frame_key") or raw.get("frame_key") or "")

    node_callbacks: dict[str, set[str]] = {}
    groups: dict[str | None, list[tuple[str, Mapping[str, Any]]]] = {}
    for callback in callback_keys:
        callback = str(callback or "")
        if callback:
            groups.setdefault(callback, [])
    normalized_sources: list[tuple[str, list[Mapping[str, Any]]]] = []
    for record_type, value in row_sources:
        rows = value if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)) else []
        mapping_rows = [row for row in rows if isinstance(row, Mapping)]
        normalized_sources.append((record_type, mapping_rows))
        if record_type in {"point", "cluster", "track", "output"}:
            for row in mapping_rows:
                callback = row_frame(row)
                if not callback:
                    continue
                keys = {
                    str(row.get(key)) for key in ("point_key", "cluster_id", "track_key", "output_key", "track_id", "object_id", "objID", "ID", "id")
                    if row.get(key) not in (None, "")
                }
                for key in keys:
                    node_callbacks.setdefault(key, set()).add(callback)

    def record_callback(record_type: str, row: Mapping[str, Any]) -> str | None:
        explicit = row_frame(row)
        if explicit:
            return explicit
        if record_type not in {"edge", "raw_edge", "invalid_edge"}:
            return None
        candidates: set[str] = set()
        for endpoint in (row.get("from"), row.get("to"), row.get("source"), row.get("target")):
            if endpoint not in (None, ""):
                candidates.update(node_callbacks.get(str(endpoint), set()))
        return next(iter(candidates)) if len(candidates) == 1 else None

    for record_type, rows in normalized_sources:
        for row in rows:
            callback = record_callback(record_type, row)
            groups.setdefault(callback, []).append((record_type, row))

    counts: dict[str, int] = {}
    callbacks_index: dict[str, dict[str, Any]] = {}
    digest = hashlib.sha256()
    row_count = 0
    unbound_index: dict[str, Any] | None = None
    with path.open("wb") as handle:
        for callback in sorted(groups, key=lambda item: (item is None, item or "")):
            start = handle.tell()
            block_digest = hashlib.sha256()
            block_counts: dict[str, int] = {}
            block_rows = 0
            for record_type, row in groups[callback]:
                payload = {"record_type": record_type, "row": dict(row)}
                line = (json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str) + "\n").encode("utf-8")
                handle.write(line)
                digest.update(line)
                block_digest.update(line)
                counts[record_type] = counts.get(record_type, 0) + 1
                block_counts[record_type] = block_counts.get(record_type, 0) + 1
                row_count += 1
                block_rows += 1
            block = {
                "offset": start,
                "length": handle.tell() - start,
                "row_count": block_rows,
                "counts": block_counts,
                "sha256": block_digest.hexdigest(),
            }
            if callback is None:
                unbound_index = block
            else:
                callbacks_index[callback] = block

    artifact_sha256 = digest.hexdigest()
    index_payload = {
        "schema_version": "perception-lineage-index.v1",
        "artifact_path": path.name,
        "artifact_sha256": artifact_sha256,
        "artifact_size_bytes": path.stat().st_size,
        "row_count": row_count,
        "counts": counts,
        "callbacks": callbacks_index,
        "unbound": unbound_index or {"offset": path.stat().st_size, "length": 0, "row_count": 0, "counts": {}, "sha256": hashlib.sha256(b"").hexdigest()},
    }
    index_bytes = (json.dumps(index_payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    index_path.write_bytes(index_bytes)
    return {
        "path": path.name,
        "absolute_path": str(path),
        "format": "jsonl",
        "row_count": row_count,
        "counts": counts,
        "size_bytes": path.stat().st_size,
        "sha256": artifact_sha256,
        "index_ref": {"path": index_path.name, "absolute_path": str(index_path), "format": "json", "sha256": hashlib.sha256(index_bytes).hexdigest(), "callback_count": len(callbacks_index)},
        "status": "observed",
    }


def _bound_analysis(
    analysis: Mapping[str, Any],
    *,
    max_inline_points: int,
    point_artifact: Mapping[str, Any] | None,
    lineage_artifact: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Keep report JSON bounded while preserving full points and lineage artifacts."""
    bounded = dict(analysis)
    contract = dict(analysis.get("input_contract", {}) or {}) if isinstance(analysis.get("input_contract"), Mapping) else {}
    points = contract.get("points") if isinstance(contract.get("points"), list) else []
    if len(points) > max_inline_points:
        contract["points"] = points[:max_inline_points]
        contract["inline_point_count"] = len(contract["points"])
        contract["points_truncated"] = True
        point_reference = dict(point_artifact or {"status": "not_written"})
        point_reference.pop("absolute_path", None)
        contract["points_artifact"] = point_reference
    else:
        contract["inline_point_count"] = len(points)
        contract["points_truncated"] = False
    bounded["input_contract"] = contract
    lineage = analysis.get("lineage") if isinstance(analysis.get("lineage"), Mapping) else None
    if lineage:
        lineage_copy = dict(lineage)
        nodes = lineage.get("nodes") if isinstance(lineage.get("nodes"), Mapping) else None
        if nodes:
            nodes_copy = dict(nodes)
            full_node_counts = lineage_copy.get("node_counts") if isinstance(lineage_copy.get("node_counts"), Mapping) else {
                kind: len(nodes_copy.get(kind, []) or []) for kind in ("points", "clusters", "tracks", "outputs")
            }
            lineage_copy["node_counts"] = {kind: int(full_node_counts.get(kind, len(nodes_copy.get(kind, []) or [])) or 0) for kind in ("points", "clusters", "tracks", "outputs")}
            inline_node_counts: dict[str, int] = {}
            nodes_truncated = False
            for kind in ("points", "clusters", "tracks", "outputs"):
                rows = nodes_copy.get(kind)
                if isinstance(rows, list):
                    inline_node_counts[kind] = min(len(rows), max_inline_points)
                    if lineage_artifact and len(rows) > max_inline_points:
                        nodes_copy[kind] = rows[:max_inline_points]
                        nodes_truncated = True
                        if kind == "points":
                            nodes_copy["points_truncated"] = True
            if lineage_artifact:
                lineage_copy["inline_node_counts"] = inline_node_counts
                lineage_copy["nodes_truncated"] = nodes_truncated
            lineage_copy["nodes"] = nodes_copy
        if lineage_artifact:
            for key in ("edges", "raw_edges", "invalid_edges"):
                rows = lineage_copy.get(key)
                if isinstance(rows, list):
                    lineage_copy[f"inline_{key}_count"] = min(len(rows), max_inline_points)
                    if len(rows) > max_inline_points:
                        lineage_copy[key] = rows[:max_inline_points]
                        lineage_copy[f"{key}_truncated"] = True
                    else:
                        lineage_copy[f"{key}_truncated"] = False
            lineage_copy["inline_edge_count"] = len(lineage_copy.get("edges", []) or [])
            lineage_copy["edges_truncated"] = bool(lineage_copy.get("edges_truncated"))
            lineage_reference = dict(lineage_artifact)
            lineage_reference.pop("absolute_path", None)
            index_reference = lineage_reference.get("index_ref")
            if isinstance(index_reference, Mapping):
                portable_index_reference = dict(index_reference)
                portable_index_reference.pop("absolute_path", None)
                lineage_reference["index_ref"] = portable_index_reference
            lineage_copy["lineage_artifact"] = lineage_reference
        bounded["lineage"] = lineage_copy
    return bounded


def _html_report(payload: Mapping[str, Any]) -> str:
    analysis = payload.get("analysis", {}) if isinstance(payload.get("analysis"), Mapping) else {}
    contract = analysis.get("input_contract", {}) if isinstance(analysis.get("input_contract"), Mapping) else {}
    artifact_audit = contract.get("artifact_audit", {}) if isinstance(contract.get("artifact_audit"), Mapping) else {}
    stages = analysis.get("stage_coverage", {}).get("stages", []) if isinstance(analysis.get("stage_coverage"), Mapping) else []
    gaps = analysis.get("gaps", []) if isinstance(analysis.get("gaps"), list) else []
    code_flow = analysis.get("code_flow", {}) if isinstance(analysis.get("code_flow"), Mapping) else {}
    run_evidence = analysis.get("run_evidence", {}) if isinstance(analysis.get("run_evidence"), Mapping) else {}
    comparison = analysis.get("comparison", {}) if isinstance(analysis.get("comparison"), Mapping) else {}
    scene = analysis.get("scene", {}) if isinstance(analysis.get("scene"), Mapping) else {}
    timeline = analysis.get("timeline", {}) if isinstance(analysis.get("timeline"), Mapping) else {}
    warmup_analysis = analysis.get("warmup_analysis", {}) if isinstance(analysis.get("warmup_analysis"), Mapping) else {}
    hypothesis_set = analysis.get("hypothesis_set", {}) if isinstance(analysis.get("hypothesis_set"), Mapping) else {}
    capability_manifest = analysis.get("capability_manifest", {}) if isinstance(analysis.get("capability_manifest"), Mapping) else {}
    validation = payload.get("validation", {}) if isinstance(payload.get("validation"), Mapping) else {}
    source_contract = analysis.get("source_execution_contract", {}) if isinstance(analysis.get("source_execution_contract"), Mapping) else {}
    callback_binding = analysis.get("callback_binding_summary", {}) if isinstance(analysis.get("callback_binding_summary"), Mapping) else {}
    lineage = analysis.get("lineage", {}) if isinstance(analysis.get("lineage"), Mapping) else {}
    track_population = lineage.get("track_population", {}) if isinstance(lineage.get("track_population"), Mapping) else {}
    input_artifact = contract.get("points_artifact", {}) if isinstance(contract.get("points_artifact"), Mapping) else {}
    lineage_artifact = lineage.get("lineage_artifact", {}) if isinstance(lineage.get("lineage_artifact"), Mapping) else {}
    selected_frame_key = str(scene.get("selected_frame") or "")
    analysis_status = str(analysis.get("status", "blocked"))
    conclusion_level = str(analysis.get("conclusion_level", "facts_only"))
    strategy_name = str(analysis.get("strategy", "point_cloud"))
    artifact_status = str(artifact_audit.get("status", "not_available"))
    artifact_format = str(artifact_audit.get("format", "not_available"))
    artifact_parser = str(artifact_audit.get("parser", "not_available"))
    contract_status = str(contract.get("status", "not_available"))
    input_boundary = str(contract.get("input_boundary", "not_available"))
    layout_status = str(contract.get("layout_status", "not_available"))

    def _selected_stage_evidence(row: Mapping[str, Any]) -> str:
        evidence_rows = row.get("evidence_rows", []) if isinstance(row.get("evidence_rows"), list) else []
        selected_rows = [
            item for item in evidence_rows
            if isinstance(item, Mapping)
            and str(item.get("frame_key") or item.get("frame_id") or item.get("frameID") or "") == selected_frame_key
        ]
        if not selected_rows:
            return "not_available"
        return " · ".join(
            f"{_html_token_label(item.get('status', 'not_available'), _STATUS_LABELS)} / "
            f"{_html_token_label(item.get('runtime_proof', 'not_available'), _STATUS_LABELS)}: "
            f"{html.escape(str(item.get('input_count', 'not_available')))} → {html.escape(str(item.get('output_count', 'not_available')))}"
            for item in selected_rows
        )

    stage_row_html: list[str] = []
    for row in stages:
        if not isinstance(row, Mapping):
            continue
        stage_key = str(row.get("stage", ""))
        stage_name = _STAGE_LABELS.get(stage_key, "未映射")
        stage_row_html.append(
            "<tr>"
            f"<td>{html.escape(stage_name)} <code>{html.escape(stage_key)}</code></td>"
            f"<td>{_html_token_label(row.get('status', 'not_available'), _STATUS_LABELS)}</td>"
            f"<td>{html.escape(str(row.get('input_count', 'not_available')))}</td>"
            f"<td>{html.escape(str(row.get('output_count', 'not_available')))}</td>"
            f"<td>{_html_token_label(row.get('runtime_proof', 'not_available'), _STATUS_LABELS)}</td>"
            f"<td>{_selected_stage_evidence(row)}</td>"
            "</tr>"
        )
    stage_rows = "".join(stage_row_html)
    gap_rows = "".join(
        f"<li><strong>{html.escape(str(item.get('id', 'gap')))}</strong>: {html.escape(str(item.get('message', '')))}</li>"
        for item in gaps if isinstance(item, Mapping)
    )
    scene_layers = scene.get("layers", {}) if isinstance(scene.get("layers"), Mapping) else {}
    scene_points = scene_layers.get("points", []) if isinstance(scene_layers.get("points"), list) else []
    scene_clusters = scene_layers.get("clusters", []) if isinstance(scene_layers.get("clusters"), list) else []
    scene_tracks = scene_layers.get("tracks", []) if isinstance(scene_layers.get("tracks"), list) else []
    scene_outputs = scene_layers.get("outputs", []) if isinstance(scene_layers.get("outputs"), list) else []

    def _scene_xy(row: Any) -> tuple[float, float] | None:
        if not isinstance(row, Mapping) or row.get("coordinate_status") not in {"observed", "derived"}:
            return None
        try:
            x_value, y_value = float(row.get("x")), float(row.get("y"))
        except (TypeError, ValueError, OverflowError):
            return None
        return (x_value, y_value) if math.isfinite(x_value) and math.isfinite(y_value) else None

    point_xy = [(index, _scene_xy(row)) for index, row in enumerate(scene_points)]
    cluster_xy = [(index, _scene_xy(row)) for index, row in enumerate(scene_clusters)]
    coordinates = [xy for _, xy in (*point_xy, *cluster_xy) if xy is not None]
    if coordinates:
        xs = [item[0] for item in coordinates]
        ys = [item[1] for item in coordinates]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        span_x = max(max_x - min_x, 1e-9)
        span_y = max(max_y - min_y, 1e-9)
        def screen(x: float, y: float) -> tuple[float, float]:
            return 35 + (x - min_x) / span_x * 530, 405 - (y - min_y) / span_y * 360

        scene_points_display = scene_points[:2000]
        scene_clusters_display = scene_clusters[:2000]
        scene_point_marks = []
        for index, row in enumerate(scene_points_display):
            xy = _scene_xy(row)
            if xy is None:
                continue
            cx, cy = screen(*xy)
            status = str(row.get("coordinate_status") or "not_available")
            cluster_id = html.escape(str(row.get("cluster_id", "")), quote=True)
            track_id = html.escape(str(row.get("track_id", "")), quote=True)
            point_key = html.escape(str(row.get("point_key", "")), quote=True)
            scene_points_display[index] = dict(row)
            scene_point_marks.append(
                f'<circle class="scene-mark scene-point coordinate-{status}" data-scene-kind="points" data-scene-index="{index}" '
                f'data-cluster-id="{cluster_id}" data-track-id="{track_id}" cx="{cx:.2f}" cy="{cy:.2f}" r="3.6">'
                f'<title>point {point_key} · cluster={cluster_id or "not_available"} · track={track_id or "not_available"} · x={xy[0]:.3f}, y={xy[1]:.3f}</title></circle>'
            )
        scene_cluster_marks = []
        for index, row in enumerate(scene_clusters_display):
            xy = _scene_xy(row)
            if xy is None:
                continue
            cx, cy = screen(*xy)
            radius = 7
            cluster_id = html.escape(str(row.get("algorithm_cluster_id", row.get("cluster_id", ""))), quote=True)
            cluster_key = html.escape(str(row.get("cluster_id", "")), quote=True)
            points_count = html.escape(str(row.get("support_point_count", "not_available")), quote=True)
            scene_clusters_display[index] = dict(row)
            scene_cluster_marks.append(
                f'<polygon class="scene-mark scene-cluster coordinate-{html.escape(str(row.get("coordinate_status", "not_available")))}" '
                f'data-scene-kind="clusters" data-scene-index="{index}" data-cluster-id="{cluster_id}" '
                f'points="{cx:.2f},{cy-radius:.2f} {cx+radius:.2f},{cy:.2f} {cx:.2f},{cy+radius:.2f} {cx-radius:.2f},{cy:.2f}">'
                f'<title>cluster {cluster_key} · algorithm_cluster_id={cluster_id} · support points={points_count} · coordinate_status={html.escape(str(row.get("coordinate_status", "not_available")))}</title></polygon>'
            )
        scene_svg = (
            '<svg id="selected-frame-svg" viewBox="0 0 600 440" role="img" aria-label="selected frame point and exact cluster scene">'
            '<rect x="0" y="0" width="600" height="440" fill="#0d1211" stroke="#365048"/>'
            '<line x1="300" y1="25" x2="300" y2="415" stroke="#243c35"/><line x1="25" y1="220" x2="575" y2="220" stroke="#243c35"/>'
            f'<g id="cluster-layer" data-layer="clusters">{"".join(scene_cluster_marks)}</g>'
            f'<g id="point-layer" data-layer="points">{"".join(scene_point_marks)}</g></svg>'
        )
    else:
        scene_points_display = scene_points[:2000]
        scene_clusters_display = scene_clusters[:2000]
        scene_svg = '<p>Selected-frame coordinates unavailable; no nearest-frame fallback was used.</p>'

    scene_model = {
        "points": scene_points_display,
        "clusters": scene_clusters_display,
        "tracks": scene_tracks[:200],
        "outputs": scene_outputs[:200],
        "counts": scene.get("counts", {}),
    }
    scene_json = json.dumps(scene_model, ensure_ascii=False, separators=(",", ":"), default=str)
    scene_json = scene_json.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")

    def _object_rows(rows: Sequence[Any], kind: str, label: str) -> str:
        result = []
        for index, row in enumerate(rows):
            if not isinstance(row, Mapping):
                continue
            identity = row.get("algorithm_track_id", row.get("track_id", row.get("ID", row.get("objID", "not_available"))))
            position = row.get("position") if isinstance(row.get("position"), Mapping) else {}
            x_value = row.get("distX", position.get("x", "not_available"))
            y_value = row.get("distY", position.get("y", "not_available"))
            result.append(
                "<tr>"
                f"<td>{html.escape(label)}</td>"
                f'<td><button type="button" class="object-select" data-object-kind="{kind}" data-object-index="{index}">{html.escape(str(identity))}</button></td>'
                f"<td>{html.escape(str(row.get('frame_key', 'not_available')))}</td>"
                f"<td>{html.escape(str(row.get('status', 'not_available')))}</td>"
                f"<td>{html.escape(str(x_value))}, {html.escape(str(y_value))}</td>"
                "</tr>"
            )
        return "".join(result)

    object_rows_html = _object_rows(scene_tracks[:200], "tracks", "Track") + _object_rows(scene_outputs[:200], "outputs", "Output")
    point_rows_html = "".join(
        "<tr>"
        f'<td><button type="button" class="point-select" data-point-index="{index}">Point {html.escape(str(row.get("point_key", index)))}</button></td>'
        f"<td>{html.escape(str(row.get('point_key', 'not_available')))}</td>"
        f"<td>{html.escape(str(row.get('cluster_id', 'not_available')))}</td>"
        f"<td>{html.escape(str(row.get('track_id', 'not_available')))}</td>"
        f"<td>{html.escape(str(row.get('range', 'not_available')))}, {html.escape(str(row.get('azimuth', 'not_available')))}</td>"
        f"<td>{html.escape(str(row.get('x', 'not_available')))}, {html.escape(str(row.get('y', 'not_available')))} · {html.escape(str(row.get('coordinate_status', 'not_available')))}</td>"
        "</tr>"
        for index, row in enumerate(scene_points_display) if isinstance(row, Mapping)
    )
    cluster_rows_html = "".join(
        "<tr>"
        f'<td><button type="button" class="cluster-select" data-cluster-index="{index}">Cluster {html.escape(str(row.get("algorithm_cluster_id", row.get("cluster_id", index))))}</button></td>'
        f"<td>{html.escape(str(row.get('algorithm_cluster_id', row.get('cluster_id', 'not_available'))))}</td>"
        f"<td>{html.escape(str(row.get('support_point_count', 'not_available')))}</td>"
        f"<td>{html.escape(str(row.get('x', 'not_available')))}, {html.escape(str(row.get('y', 'not_available')))} · {html.escape(str(row.get('coordinate_status', 'not_available')))}</td>"
        "</tr>"
        for index, row in enumerate(scene_clusters_display) if isinstance(row, Mapping)
    )
    stage_bindings = code_flow.get("stage_bindings", []) if isinstance(code_flow.get("stage_bindings"), list) else []
    code_context_binding = code_flow.get("code_context_binding", {}) if isinstance(code_flow.get("code_context_binding"), Mapping) else {}
    code_rows = []
    for binding in stage_bindings:
        if not isinstance(binding, Mapping):
            continue
        source_candidates = binding.get("source_candidates", []) if isinstance(binding.get("source_candidates"), list) else []
        source_refs = []
        for candidate in source_candidates[:3]:
            if not isinstance(candidate, Mapping):
                continue
            ref = candidate.get("source_ref") if isinstance(candidate.get("source_ref"), Mapping) else {}
            where = f"{ref.get('path', 'not_available')}:{ref.get('line', 'not_available')}"
            token = candidate.get("snippet") or ref.get("token") or ""
            source_refs.append(
                f"stage-map candidate · {html.escape(str(candidate.get('function', '')))} · "
                f"{html.escape(str(where))} · <code>{html.escape(str(token))}</code>"
            )
        definition_candidates = binding.get("function_definition_candidates", []) if isinstance(binding.get("function_definition_candidates"), list) else []
        definition_refs = []
        for definition in definition_candidates[:5]:
            if not isinstance(definition, Mapping):
                continue
            ref = definition.get("source_ref") if isinstance(definition.get("source_ref"), Mapping) else {}
            start_line = ref.get("line", "not_available")
            end_line = ref.get("end_line")
            where = f"{ref.get('path', 'not_available')}:{start_line}"
            if end_line not in (None, "") and str(end_line) != str(start_line):
                where += f"-{end_line}"
            signature = str(definition.get("signature") or "")[:240]
            definition_refs.append(
                f"function definition candidate · {html.escape(str(definition.get('function', '')))} · "
                f"{html.escape(str(where))} · <code>{html.escape(signature)}</code>"
            )
        code_rows.append(
            "<tr>"
            f"<td>{html.escape(_STAGE_LABELS.get(str(binding.get('stage', '')), '未映射'))} <code>{html.escape(str(binding.get('stage', '')))}</code></td>"
            f"<td>{_html_token_label(binding.get('status', 'not_available'), _STATUS_LABELS)}</td>"
            f"<td>{_html_token_label(binding.get('runtime_proof', 'not_available'), _STATUS_LABELS)}</td>"
            f"<td>{'<br>'.join(source_refs) if source_refs else 'source candidate not available'}</td>"
            f"<td>{'<br>'.join(definition_refs) if definition_refs else html.escape(str(binding.get('function_definition_status', 'not_available')))}</td>"
            "</tr>"
        )
    def _artifact_link(label: str, ref: Mapping[str, Any]) -> str:
        raw = str(ref.get("path") or "")
        if not raw:
            return ""
        name = Path(raw).name
        return f'<a href="{html.escape(name, quote=True)}">{html.escape(label)} · {html.escape(name)}</a>'

    artifact_links = " · ".join(link for link in (
        _artifact_link("完整点迹行", input_artifact),
        _artifact_link("完整 lineage 行", lineage_artifact),
        _artifact_link("lineage 索引", lineage_artifact.get("index_ref", {}) if isinstance(lineage_artifact.get("index_ref"), Mapping) else {}),
    ) if link)
    invalid_edge_count = lineage.get("invalid_edge_count", len(lineage.get("invalid_edges", []) or []))
    relation_counts_text = html.escape(json.dumps(lineage.get("relation_counts", {}), ensure_ascii=False))
    raw_relation_counts_text = html.escape(json.dumps(lineage.get("raw_relation_counts", {}), ensure_ascii=False))
    stage_by_name = {
        str(row.get("stage") or ""): row
        for row in stages if isinstance(row, Mapping)
    }

    def _stage_has_runtime_rows(stage_name: str) -> bool:
        row = stage_by_name.get(stage_name, {})
        evidence_rows = row.get("evidence_rows", []) if isinstance(row.get("evidence_rows"), list) else []
        return any(
            isinstance(item, Mapping)
            and str(item.get("runtime_proof", "")) in {"observed", "completed"}
            and str(item.get("status", "")) in {"completed", "observed", "partial"}
            for item in evidence_rows
        )

    capability_layers = [
        ("Input LGU dotTrans", "not_available", "input_decode has no runtime evidence; current point rows are public PointCloud2 outputs."),
        ("Public PointCloud2 point layer", "observed" if scene_points else "not_available", "Observed output coordinates and source_ref are retained in the selected-frame scene."),
        ("Pre-filter point rows", "observed" if _stage_has_runtime_rows("dot_filter") else "not_available", "Private before/after filter rows are not captured; source-derived stage candidates remain labeled derived."),
        ("Cluster membership / centroid", "derived" if scene_clusters else "not_available", "Membership uses exact cluster_id; centroid, when available, is derived from same-callback points."),
        ("Mature track / objectlist", "observed" if scene_tracks or scene_outputs else "not_available", "Public rows remain in their own property table; no unverified coordinate transform is applied."),
        ("Candidate track rows", "observed" if _stage_has_runtime_rows("track") and any(str(row.get("status")) == "candidate" for row in scene_tracks) else "not_available", "No explicit candidate-track payload was supplied."),
        ("ADAS ROI / warning output", "observed" if analysis.get("warning_rows") or analysis.get("roi_rows") else "not_available", "No same-callback ADAS warning/ROI rows are available in this capture."),
        ("Recorded ↔ replay comparison", str(comparison.get("status", "not_available")), str(comparison.get("match_basis", "explicit match evidence unavailable"))),
        ("AI hypotheses", "candidate_only" if (hypothesis_set.get("hypotheses") or []) else "not_available", "No candidate-only hypotheses were supplied to this deterministic report."),
    ]
    capability_layer_rows = "".join(
        f"<tr><td>{html.escape(name)}</td><td><code>{html.escape(status)}</code></td><td>{html.escape(detail)}</td></tr>"
        for name, status, detail in capability_layers
    )
    timeline_rows = "".join(
        "<tr>" + "".join(f"<td>{html.escape(str(value))}</td>" for value in (
            row.get("frame_key", ""), len(row.get("stages", []) or []), ", ".join(str(item) for item in row.get("track_ids", []) or []), ", ".join(str(item) for item in row.get("output_ids", []) or [])
        )) + "</tr>"
        for row in timeline.get("rows", []) or [] if isinstance(row, Mapping)
    )
    uid_recurrence_rows = "".join(
        "<tr>" + "".join(f"<td>{html.escape(str(value))}</td>" for value in (
            row.get("previous_frame_key", ""), row.get("current_frame_key", ""), row.get("algorithm_track_id", ""),
            row.get("status", "not_available"), row.get("match_grade", "not_available"),
        )) + "</tr>"
        for row in timeline.get("public_uid_recurrences", []) or [] if isinstance(row, Mapping)
    )
    if not object_rows_html:
        object_rows_html = '<tr><td colspan="5">No explicit track/output rows for the selected frame.</td></tr>'
    scene_script = """
<script>
(() => {
  const source = document.getElementById("scene-model");
  const panel = document.getElementById("scene-detail");
  if (!source || !panel) return;
  const model = JSON.parse(source.textContent || "{}");
  const canonical = value => {
    if (value === null || value === undefined || value === "") return "";
    const number = Number(value);
    return Number.isFinite(number) ? String(number) : String(value);
  };
  const clearLinked = () => document.querySelectorAll(".scene-mark.is-linked").forEach(node => node.classList.remove("is-linked"));
  const showDetails = (kind, row) => {
    panel.replaceChildren();
    const heading = document.createElement("h4");
    heading.textContent = `${kind} evidence`;
    const detail = document.createElement("pre");
    detail.textContent = JSON.stringify(row, null, 2);
    panel.append(heading, detail);
  };
  const highlightPoints = (field, value) => {
    clearLinked();
    if (value === null || value === undefined || value === "") return;
    const sought = canonical(value);
    document.querySelectorAll(".scene-point").forEach(node => {
      const match = canonical(field === "track_id" ? node.dataset.trackId : node.dataset.clusterId) === sought;
      if (match) node.classList.add("is-linked");
    });
    document.querySelectorAll(".scene-cluster").forEach(node => {
      if (field === "cluster_id" && canonical(node.dataset.clusterId) === sought) node.classList.add("is-linked");
    });
  };
  document.querySelectorAll("[data-toggle-layer]").forEach(toggle => {
    toggle.addEventListener("change", () => {
      const layer = document.getElementById(`${toggle.dataset.toggleLayer}-layer`);
      if (layer) layer.hidden = !toggle.checked;
    });
  });
  document.querySelectorAll("[data-scene-kind]").forEach(node => {
    const select = () => {
      const kind = node.dataset.sceneKind;
      const row = (model[kind] || [])[Number(node.dataset.sceneIndex)];
      if (!row) return;
      clearLinked();
      if (kind === "points") {
        highlightPoints(row.track_id !== null && row.track_id !== undefined ? "track_id" : "cluster_id", row.track_id ?? row.cluster_id);
      } else if (kind === "clusters") {
        highlightPoints("cluster_id", row.algorithm_cluster_id ?? row.cluster_id);
      }
      showDetails(kind, row);
    };
    node.addEventListener("click", select);
    node.addEventListener("keydown", event => {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); select(); }
    });
    node.setAttribute("tabindex", "0");
    node.setAttribute("role", "button");
  });
  document.querySelectorAll(".object-select").forEach(button => {
    button.addEventListener("click", () => {
      const kind = button.dataset.objectKind;
      const row = (model[kind] || [])[Number(button.dataset.objectIndex)];
      if (!row) return;
      const trackId = row.algorithm_track_id ?? row.track_id ?? row.ID ?? row.objID;
      highlightPoints("track_id", trackId);
      showDetails(kind, row);
    });
  });
  document.querySelectorAll(".point-select").forEach(button => {
    button.addEventListener("click", () => {
      const row = (model.points || [])[Number(button.dataset.pointIndex)];
      if (!row) return;
      const field = row.track_id !== null && row.track_id !== undefined ? "track_id" : "cluster_id";
      highlightPoints(field, row[field]);
      showDetails("points", row);
    });
  });
  document.querySelectorAll(".cluster-select").forEach(button => {
    button.addEventListener("click", () => {
      const row = (model.clusters || [])[Number(button.dataset.clusterIndex)];
      if (!row) return;
      highlightPoints("cluster_id", row.algorithm_cluster_id ?? row.cluster_id);
      showDetails("clusters", row);
    });
  });
  const pointFilter = document.getElementById("point-filter");
  if (pointFilter) pointFilter.addEventListener("input", () => {
    const query = pointFilter.value.toLowerCase();
    document.querySelectorAll("#point-list tbody tr").forEach(row => { row.hidden = !row.textContent.toLowerCase().includes(query); });
  });
  const clear = document.getElementById("clear-scene-selection");
  if (clear) clear.addEventListener("click", () => { clearLinked(); panel.textContent = "请选择点迹、簇、航迹或输出行查看精确帧证据。"; });
})();
</script>
"""
    return f"""<!doctype html>
<html lang="zh-CN"><meta charset="utf-8"><link rel="icon" href="data:,"><title>点云感知分析报告</title>
<style>body{{font:14px system-ui,sans-serif;background:#101615;color:#e5f1eb;margin:24px}}section{{border:1px solid #365048;border-radius:10px;padding:16px;margin:12px 0}}table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #365048;padding:7px;text-align:left;vertical-align:top}}code{{color:#8fe3bd}}.blocked{{color:#ff9d9d}}.partial{{color:#ffd58a}}.scene-grid{{display:grid;grid-template-columns:minmax(320px,2fr) minmax(260px,1fr);gap:14px;align-items:start}}#selected-frame-svg{{width:100%;height:auto;min-height:320px;background:#0d1211;border:1px solid #365048;border-radius:8px}}.scene-toolbar{{display:flex;gap:16px;align-items:center;flex-wrap:wrap;margin:8px 0 12px}}.scene-mark{{cursor:pointer;stroke-width:1.4}}.scene-point.coordinate-observed{{fill:#65d6c0;stroke:#d5fff6}}.scene-point.coordinate-derived{{fill:#ffbd69;stroke:#fff0d4;stroke-dasharray:2 1}}.scene-cluster.coordinate-derived{{fill:#f0a54a;stroke:#fff0d4;stroke-dasharray:4 2}}.scene-cluster.coordinate-observed{{fill:#c49aff;stroke:#eee0ff}}.scene-mark:hover,.scene-mark.is-linked{{stroke:#fff;stroke-width:3;filter:drop-shadow(0 0 5px #fff)}}.scene-note{{color:#bdcec8}}#scene-detail{{min-height:180px;max-height:460px;overflow:auto;background:#0d1211;padding:10px;border-radius:8px}}#scene-detail pre,pre{{white-space:pre-wrap;overflow-wrap:anywhere}}.object-select{{background:#233b34;color:#dff7ed;border:1px solid #648678;border-radius:5px;padding:5px 8px;cursor:pointer}}.legend{{display:flex;gap:14px;flex-wrap:wrap}}.source-cards{{font-size:13px}}.source-cards code{{overflow-wrap:anywhere}}details{{margin:10px 0}}details>summary{{cursor:pointer;color:#9de2cc;font-weight:600;padding:6px 0}}input[type=search]{{background:#0d1211;color:#e5f1eb;border:1px solid #648678;border-radius:5px;padding:6px;margin:8px 0}}@media(max-width:850px){{.scene-grid{{grid-template-columns:1fr}}}}</style>
<h1>点云感知分析报告</h1>
<section><strong>状态：</strong> <span class="{html.escape(analysis_status)}">{html.escape(_STATUS_LABELS.get(analysis_status, '未映射'))}</span> <code>{html.escape(analysis_status)}</code>
 · <strong>结论层级：</strong> {_html_token_label(conclusion_level, _CONCLUSION_LABELS)}
 · <strong>分析策略：</strong> {_html_token_label(strategy_name, _STRATEGY_LABELS)}</section>
<section><h2>输入材料</h2><p>解析状态：{_html_token_label(artifact_status, _STATUS_LABELS)}；格式：<code>{html.escape(artifact_format)}</code>；解析器：<code>{html.escape(artifact_parser)}</code>；SHA-256：<code>{html.escape(str(artifact_audit.get('sha256','')))}</code></p><details><summary>查看载荷结构与解析诊断</summary><pre>{html.escape(json.dumps({'payload_shape': artifact_audit.get('payload_shape',{}), 'diagnostics': artifact_audit.get('diagnostics',[])}, ensure_ascii=False, indent=2))}</pre></details></section>
<section><h2>输入契约</h2><p>状态：{_html_token_label(contract_status, _STATUS_LABELS)}；数据边界：{_html_token_label(input_boundary, _INPUT_BOUNDARY_LABELS)}；布局：{_html_token_label(layout_status, _STATUS_LABELS)}；点迹数量：{html.escape(str(contract.get('point_count',0)))}；原始传感器前端：<code>{html.escape(str(contract.get('raw_sensor_frontend','not_available')))}</code></p><details><summary>查看完整输入契约字段</summary><pre>{html.escape(json.dumps({'data_fingerprint': contract.get('data_fingerprint',''), 'source_context_id': contract.get('source_context_id',''), 'source_context_binding': contract.get('source_context_binding',{}), 'artifact_audit': contract.get('artifact_audit',{}), 'layout_binding': contract.get('layout_binding',{}), 'payload_audit': contract.get('payload_audit',{}), 'field_counts': contract.get('field_counts',{}), 'radar_summary': contract.get('radar_summary',[]), 'target_usage': contract.get('target_usage',{}), 'losses': contract.get('losses',{}), 'diagnostics': contract.get('diagnostics',[])}, ensure_ascii=False, indent=2))}</pre></details></section>
<section><h2>阶段覆盖</h2><table><thead><tr><th>阶段</th><th>状态</th><th>输入数</th><th>输出数</th><th>运行证据</th><th>选中帧证据</th></tr></thead><tbody>{stage_rows}</tbody></table></section>
<section><h2>图层可用性</h2><p>缺失图层会作为证据缺口显示；不补造未采集的阶段或比较结果。</p><table><thead><tr><th>图层</th><th>证据状态</th><th>依据 / 缺口</th></tr></thead><tbody>{capability_layer_rows}</tbody></table></section>
<section><h2>选中帧场景与精确回调记录</h2>
<p>frame: <code>{html.escape(str(scene.get('selected_frame', 'not_available')))}</code>; selection basis: <code>{html.escape(str(scene.get('selection_basis', 'not_available')))}</code>; status: <code>{html.escape(str(scene.get('status', 'not_available')))}</code>; point coordinate frame: <code>{html.escape(str(scene.get('coordinate_frame', 'not_available')))}</code></p>
<p>Counts: points {html.escape(str(scene.get('counts', {}).get('points', 0) if isinstance(scene.get('counts'), Mapping) else 0))}, clusters {html.escape(str(scene.get('counts', {}).get('clusters', 0) if isinstance(scene.get('counts'), Mapping) else 0))}, tracks {html.escape(str(scene.get('counts', {}).get('tracks', 0) if isinstance(scene.get('counts'), Mapping) else 0))}, outputs {html.escape(str(scene.get('counts', {}).get('outputs', 0) if isinstance(scene.get('counts'), Mapping) else 0))}. Point/cluster records are shown in their declared point frame; track/output objects stay in the property list and are not spatially overlaid without a verified transform.</p>
<div class="scene-toolbar"><label><input type="checkbox" data-toggle-layer="points" checked> Points ({len(scene_points_display)})</label><label><input type="checkbox" data-toggle-layer="clusters" checked> Exact-ID cluster centroids ({len(scene_clusters_display)})</label><button id="clear-scene-selection" type="button" class="object-select">清除选择</button><span class="legend"><span>● observed point</span><span>◆ derived exact-cluster centroid</span><span>✦ selected/link-matched</span></span></div>
<div class="scene-grid"><div>{scene_svg}<p class="scene-note">点击未遮挡的点迹或簇标记可查看该帧字段；重叠点迹可从精确行列表选择。簇中心按相同 `cluster_id` 的点迹求均值，属于派生显示坐标。</p></div><aside><h3>所选证据</h3><div id="scene-detail" aria-live="polite">请选择点迹、簇、航迹或输出行查看精确帧证据。</div></aside></div>
<details><summary>精确点迹行 ({len(scene_points_display)})</summary><label for="point-filter">按点迹键 / 簇 / 航迹筛选</label> <input id="point-filter" type="search"><table id="point-list"><thead><tr><th></th><th>point_key</th><th>cluster_id</th><th>track_id</th><th>range, azimuth</th><th>x, y / coordinate evidence</th></tr></thead><tbody>{point_rows_html}</tbody></table></details>
<details><summary>精确簇行 ({len(scene_clusters_display)})</summary><table><thead><tr><th></th><th>algorithm_cluster_id</th><th>support points</th><th>x, y / coordinate evidence</th></tr></thead><tbody>{cluster_rows_html}</tbody></table></details>
<div class="object-panel"><h3>航迹与输出对象（精确回调）</h3><table><thead><tr><th>Layer</th><th>Algorithm ID</th><th>Frame key</th><th>状态</th><th>distX, distY</th></tr></thead><tbody>{object_rows_html}</tbody></table><p class="scene-note">点击对象后按 source-bound 航迹 UID 高亮具有相同 `track_id` 的 PointCloud2 点迹；不会将对象坐标变换到点云坐标系。</p></div>
<script type="application/json" id="scene-model">{scene_json}</script>{scene_script}</section>
<section><h2>逐帧时间线</h2><table><thead><tr><th>帧</th><th>阶段</th><th>航迹 ID</th><th>输出 ID</th></tr></thead><tbody>{timeline_rows or '<tr><td colspan="4">无显式帧时间线</td></tr>'}</tbody></table><h3>相邻公开 UID 重现</h3><p>status: <code>{html.escape(str(timeline.get('uid_recurrence_status', 'not_available')))}</code>; scope: <code>{html.escape(str(timeline.get('uid_recurrence_scope', 'not_available')))}</code>. Same UID recurrence is derived evidence only; it does not confirm a physical object or internal tracker lifecycle.</p><table><thead><tr><th>前一回调</th><th>当前回调</th><th>公开 UID</th><th>Status</th><th>匹配等级</th></tr></thead><tbody>{uid_recurrence_rows or '<tr><td colspan="5">No source-bound adjacent public UID recurrence for this selected frame.</td></tr>'}</tbody></table></section>
<section><h2>预热敏感性</h2><p>status: <code>{html.escape(str(warmup_analysis.get('status', 'not_available')))}</code>; runs: {html.escape(str((warmup_analysis.get('metrics') or {}).get('run_count', 0) if isinstance(warmup_analysis.get('metrics'), Mapping) else 0))}</p><details><summary>查看预热指标与诊断</summary><pre>{html.escape(json.dumps({'required_range': warmup_analysis.get('required_range', [150, 200]), 'metrics': warmup_analysis.get('metrics', {}), 'diagnostics': warmup_analysis.get('diagnostics', [])}, ensure_ascii=False, indent=2))}</pre></details></section>
<section><h2>候选原因与区分实验</h2><p>status: <code>{html.escape(str(hypothesis_set.get('status', 'not_available')))}</code>; candidates: {html.escape(str(len(hypothesis_set.get('hypotheses', []) or [])))}</p><ul>{''.join(f"<li><strong>#{html.escape(str(item.get('rank', '')))} {html.escape(str(item.get('category', 'unknown')))}</strong>: {html.escape(str(item.get('statement', '')))} · evidence={html.escape(str(item.get('evidence_status', 'not_available')))}</li>" for item in hypothesis_set.get('hypotheses', []) or [] if isinstance(item, Mapping)) or '<li>未提供候选原因。</li>'}</ul></section>
<section><h2>能力与知识新鲜度</h2><p>status: <code>{html.escape(str(capability_manifest.get('status', 'not_available')))}</code>; runtime stages: {html.escape(str(capability_manifest.get('runtime_stage_count', 0)))}/{html.escape(str(len(analysis.get('stage_coverage', {}).get('stages', []) if isinstance(analysis.get('stage_coverage'), Mapping) else [])))}</p><details><summary>查看支持路径、freshness 与证据缺口</summary><pre>{html.escape(json.dumps({'supported_paths': capability_manifest.get('supported_paths', {}), 'unsupported': capability_manifest.get('unsupported', []), 'freshness': capability_manifest.get('freshness', {}), 'diagnostics': capability_manifest.get('diagnostics', [])}, ensure_ascii=False, indent=2))}</pre></details></section>
<section><h2>报告完整性校验</h2><p>status: <code>{html.escape(str(validation.get('status', 'not_available')))}</code>; errors: {html.escape(str(len(validation.get('errors', []) or [])))}; warnings: {html.escape(str(len(validation.get('warnings', []) or [])))}</p><details><summary>查看校验结果与检查项</summary><pre>{html.escape(json.dumps({'errors': validation.get('errors', []), 'warnings': validation.get('warnings', []), 'checks': validation.get('checks', {})}, ensure_ascii=False, indent=2))}</pre></details></section>
<section><h2>证据缺口</h2><ul>{gap_rows or '<li>无</li>'}</ul></section>
<section><h2>运行与尝试记录</h2><p>status: <code>{html.escape(str(run_evidence.get('status','not_available')))}</code>; run: <code>{html.escape(str(run_evidence.get('run_id','not_available')))}</code>; attempt: <code>{html.escape(str(run_evidence.get('attempt_id','not_available')))}</code>; completed frames: {html.escape(str(len(run_evidence.get('completed_frames',[]) or [])))}</p><details><summary>查看运行/尝试完整记录</summary><pre>{html.escape(json.dumps({'warmup': run_evidence.get('warmup',{}), 'reset_status': run_evidence.get('reset_status','not_available'), 'failure': run_evidence.get('failure',{}), 'diagnostics': run_evidence.get('diagnostics',[])}, ensure_ascii=False, indent=2))}</pre></details></section>
<section><h2>录制与回放对比</h2><p>status: <code>{html.escape(str(comparison.get('status','not_available')))}</code>; matches: {html.escape(str(comparison.get('match_count',0)))}</p><details><summary>查看对齐依据、指标与首个分歧</summary><pre>{html.escape(json.dumps({'match_basis': comparison.get('match_basis','not_available'), 'metrics': comparison.get('metrics',{}), 'first_divergence': comparison.get('first_divergence'), 'diagnostics': comparison.get('diagnostics',[])}, ensure_ascii=False, indent=2))}</pre></details></section>
<section><h2>源码流程与阶段映射</h2><p>Stage-map token 行是源码候选，可能对应声明、定义或调用点；CodeIndex 函数定义另列。所有源码项均不证明函数在本次运行命中，只有 Runtime proof 列表示捕获的运行输出证据。CodeIndex binding: <code>{html.escape(str(code_context_binding.get('status', 'not_available')))}</code>; code snapshot: <code>{html.escape(str(code_context_binding.get('code_context_snapshot_hash', 'not_available')))}</code>; stage-map snapshot: <code>{html.escape(str(code_context_binding.get('stage_map_snapshot_hash', 'not_available')))}</code>.</p><table class="source-cards"><thead><tr><th>阶段</th><th>源码绑定状态</th><th>运行证据</th><th>Stage-map 候选 / token</th><th>CodeIndex 函数定义候选</th></tr></thead><tbody>{''.join(code_rows) or '<tr><td colspan="5">No source-stage bindings</td></tr>'}</tbody></table><details><summary>完整源码 / ADAS code-flow 工件</summary><pre>{html.escape(json.dumps(code_flow, ensure_ascii=False, indent=2) if code_flow else 'No source-bound code artifact was supplied.')}</pre></details></section>
<section><h2>源码契约与回调绑定</h2><p>source contract: <code>{html.escape(str(source_contract.get('status', 'not_available')))}</code>; public callback bindings: <code>{html.escape(str(callback_binding.get('binding_count', 0)))}</code>; binding status: <code>{html.escape(str(callback_binding.get('status', 'not_available')))}</code></p><details><summary>查看发布顺序、回调证据与限制</summary><pre>{html.escape(json.dumps({'publication_order': source_contract.get('publication_order', {}), 'cluster_marker_display_disabled': source_contract.get('cluster_marker_display_disabled'), 'first_callback_key': callback_binding.get('first_callback_key', ''), 'last_callback_key': callback_binding.get('last_callback_key', ''), 'callback_diagnostics': callback_binding.get('diagnostics', []), 'limitations': callback_binding.get('limitations', [])}, ensure_ascii=False, indent=2))}</pre></details></section>
<section><h2>点迹、簇、航迹与输出关联</h2><p>status=<code>{html.escape(str(lineage.get('status', 'not_available')))}</code>; points/clusters/tracks/outputs={html.escape(json.dumps(lineage.get('node_counts', {}), ensure_ascii=False))}; track population scope=<code>{html.escape(str(track_population.get('scope', 'not_available')))}</code>; canonical edges={html.escape(str(lineage.get('edge_count', 0)))}; canonical relation counts={relation_counts_text}; raw relation rows={raw_relation_counts_text}; invalid={html.escape(str(invalid_edge_count))}. Relation counts are normalized edge pairs; raw relation rows can include duplicate supporting rows. Links use source-bound fields and exact callback-order bindings; no timestamp-nearest match is inferred.</p><details><summary>查看关系计数、身份范围与限制</summary><pre>{html.escape(json.dumps({'relation_summaries': lineage.get('relation_summaries', {}), 'relation_scopes': lineage.get('relation_scopes', {}), 'track_population': lineage.get('track_population', {}), 'identity_warnings': lineage.get('identity_warnings', []), 'limitations': lineage.get('limitations', [])}, ensure_ascii=False, indent=2))}</pre></details></section>
<section><h2>证据附件</h2><p>{artifact_links or '没有外置点迹或 lineage 附件。'}</p></section>
</html>"""


class PointCloudAnalyzeModule(BaseModule):
    """Audit point-cloud inputs and project perception evidence for reports."""

    name = "point-cloud-analyze"
    description = "审计点云输入并生成感知阶段、lineage 和 ADAS 联合分析证据"
    tags = ["point-cloud", "perception", "adas", "evidence", "report", "atomic"]
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "capture": {"type": "object"},
            "capture_path": {"type": "string"},
            "analysis_handoff": {"type": "object"},
            "analysis_handoff_path": {"type": "string"},
            "point_rows": {"type": "array", "items": {"type": "object"}},
            "recorded_rows": {"type": "array", "items": {"type": "object"}},
            "replay_rows": {"type": "array", "items": {"type": "object"}},
            "cluster_rows": {"type": "array", "items": {"type": "object"}},
            "track_rows": {"type": "array", "items": {"type": "object"}},
            "output_rows": {"type": "array", "items": {"type": "object"}},
            "lineage_edges": {"type": "array", "items": {"type": "object"}},
            "stage_evidence": {"type": "array", "items": {"type": "object"}},
            "message_schema": {"type": "object"},
            "target_rows": {"type": "array", "items": {"type": "object"}},
            "target_usage": {"type": "object"},
            "conversion": {"type": "object"},
            "run_evidence": {"type": "object"},
            "run_evidence_path": {"type": "string"},
            "warmup_runs": {"type": "array", "items": {"type": "object"}},
            "hypotheses": {"type": "array", "items": {"type": "object"}},
            "experiments": {"type": "array", "items": {"type": "object"}},
            "replay_plan": {"type": "object"},
            "replay_plan_path": {"type": "string"},
            "execution_binding": {"type": "object"},
            "execution_binding_path": {"type": "string"},
            "comparison_matches": {"type": "array", "items": {"type": "object"}},
            "comparison_alignment": {"type": "object"},
            "recorded_identity": {"type": "object"},
            "replay_identity": {"type": "object"},
            "selected_frame": {"type": ["string", "integer"]},
            "selection_basis": {"type": "string"},
            "frame_domain": {"type": "string"},
            "epoch": {},
            "angle_unit": {"type": "string"},
            "range_unit": {"type": "string"},
            "coordinate_frame": {"type": "string"},
            "max_inline_points": {
                "type": "integer", "default": 200, "minimum": 1,
                "description": "JSON 报告中点云与 lineage 的最大内嵌行数；超出时写入带 SHA-256 的 JSONL 附件",
            },
            "stage_map": {"type": "object"},
            "source_root": {"type": "string"},
            "source_files": {"type": "array", "items": {"type": "string"}},
            "visualization_source_path": {"type": "string"},
            "source_context": {"type": "object"},
            "source_context_path": {"type": "string"},
            "code_context": {"type": "object"},
            "code_context_path": {"type": "string"},
            "event_code_path": {"type": "object"},
            "event_code_path_path": {"type": "string"},
            "condition_trace": {"type": "object"},
            "condition_trace_path": {"type": "string"},
            "strategy": {"type": "string", "enum": ["point_cloud", "sgu_injection"]},
            "problem": {"type": "string"},
            "output_dir": {
                "type": "string",
                "description": "可选报告目录；大型分析省略时自动写入 outputs/point_cloud_analysis/run-*",
            },
        },
        "anyOf": [{"required": ["capture"]}, {"required": ["capture_path"]}, {"required": ["point_rows"]}],
        "additionalProperties": False,
    }
    output_schema: dict[str, Any] = {
        "type": "object",
        "required": ["schema_version", "status", "analysis"],
    }

    def run(
        self,
        *,
        capture: Mapping[str, Any] | None = None,
        capture_path: str = "",
        analysis_handoff: Mapping[str, Any] | None = None,
        analysis_handoff_path: str = "",
        point_rows: Sequence[Mapping[str, Any]] | None = None,
        recorded_rows: Sequence[Mapping[str, Any]] | None = None,
        replay_rows: Sequence[Mapping[str, Any]] | None = None,
        cluster_rows: Sequence[Mapping[str, Any]] | None = None,
        track_rows: Sequence[Mapping[str, Any]] | None = None,
        output_rows: Sequence[Mapping[str, Any]] | None = None,
        lineage_edges: Sequence[Mapping[str, Any]] | None = None,
        stage_evidence: Sequence[Mapping[str, Any]] | None = None,
        message_schema: Mapping[str, Any] | None = None,
        target_rows: Sequence[Mapping[str, Any]] | None = None,
        target_usage: Mapping[str, Any] | None = None,
        conversion: Mapping[str, Any] | None = None,
        run_evidence: Mapping[str, Any] | None = None,
        run_evidence_path: str = "",
        warmup_runs: Sequence[Mapping[str, Any]] | None = None,
        hypotheses: Sequence[Mapping[str, Any]] | None = None,
        experiments: Sequence[Mapping[str, Any]] | None = None,
        replay_plan: Mapping[str, Any] | None = None,
        replay_plan_path: str = "",
        execution_binding: Mapping[str, Any] | None = None,
        execution_binding_path: str = "",
        comparison_matches: Sequence[Mapping[str, Any]] | None = None,
        comparison_alignment: Mapping[str, Any] | None = None,
        recorded_identity: Mapping[str, Any] | None = None,
        replay_identity: Mapping[str, Any] | None = None,
        selected_frame: Any = None,
        selection_basis: str = "",
        frame_domain: str = "",
        epoch: Any = None,
        angle_unit: str = "unknown",
        range_unit: str = "unknown",
        coordinate_frame: str = "radar",
        max_inline_points: int = 200,
        stage_map: Mapping[str, Any] | None = None,
        source_root: str = "",
        source_files: Sequence[str] | None = None,
        visualization_source_path: str = "",
        source_context: Mapping[str, Any] | None = None,
        source_context_path: str = "",
        code_context: Mapping[str, Any] | None = None,
        code_context_path: str = "",
        event_code_path: Mapping[str, Any] | None = None,
        event_code_path_path: str = "",
        condition_trace: Mapping[str, Any] | None = None,
        condition_trace_path: str = "",
        strategy: str = "point_cloud",
        problem: str = "",
        output_dir: str = "",
        **_: Any,
    ) -> ModuleResult:
        started_at = time.monotonic()
        handoff_root = _load(analysis_handoff, analysis_handoff_path)
        nested_handoff = handoff_root.get("analysis_handoff")
        handoff = dict(nested_handoff) if isinstance(nested_handoff, Mapping) else handoff_root
        handoff_inputs = handoff.get("analysis_inputs") if isinstance(handoff.get("analysis_inputs"), Mapping) else handoff
        if not capture_path:
            capture_path = str(handoff_inputs.get("capture_path") or handoff.get("capture_path") or "")
        if capture is None and isinstance(handoff_inputs.get("capture"), Mapping):
            capture = dict(handoff_inputs.get("capture"))
        if source_context is None and not source_context_path and isinstance(handoff_inputs.get("source_context"), Mapping):
            source_context = dict(handoff_inputs.get("source_context"))
        if run_evidence is None and not run_evidence_path and isinstance(handoff_inputs.get("run_evidence"), Mapping):
            run_evidence = dict(handoff_inputs.get("run_evidence"))
        if not run_evidence_path:
            run_evidence_path = str(handoff_inputs.get("run_evidence_path") or handoff.get("run_evidence_path") or "")
        if replay_plan is None and not replay_plan_path and isinstance(handoff_inputs.get("replay_plan"), Mapping):
            replay_plan = dict(handoff_inputs.get("replay_plan"))
        if execution_binding is None and not execution_binding_path and isinstance(handoff_inputs.get("execution_binding"), Mapping):
            execution_binding = dict(handoff_inputs.get("execution_binding"))
        if execution_binding is None and execution_binding_path:
            execution_binding = _load(None, execution_binding_path)
        supplied_rows = {
            "point_rows": point_rows is not None,
            "cluster_rows": cluster_rows is not None,
            "track_rows": track_rows is not None,
            "output_rows": output_rows is not None,
            "lineage_edges": lineage_edges is not None,
            "stage_evidence": stage_evidence is not None,
            "target_rows": target_rows is not None,
        }
        capture_obj, artifact_audit = _load_capture(capture, capture_path)
        if point_rows is None:
            point_rows = capture_obj.get("point_rows") or capture_obj.get("points") or capture_obj.get("dot_rows")
        if cluster_rows is None:
            cluster_rows = capture_obj.get("cluster_rows") or capture_obj.get("clusters")
        if track_rows is None:
            track_rows = capture_obj.get("track_rows") or capture_obj.get("tracks")
        if output_rows is None:
            output_rows = capture_obj.get("output_rows") or capture_obj.get("outputs")
        if lineage_edges is None:
            lineage_edges = capture_obj.get("lineage_edges") or capture_obj.get("edges")
        if stage_evidence is None:
            stage_evidence = capture_obj.get("stage_evidence") or capture_obj.get("stages")
        if recorded_rows is None:
            recorded_rows = capture_obj.get("recorded_rows")
        if replay_rows is None:
            replay_rows = capture_obj.get("replay_rows")
        if target_rows is None:
            target_rows = capture_obj.get("target_rows")
        if message_schema is None:
            message_schema = capture_obj.get("message_schema")
        if target_usage is None:
            target_usage = capture_obj.get("target_usage")
        if conversion is None:
            conversion = capture_obj.get("conversion")
        if run_evidence is None:
            run_evidence = capture_obj.get("run_evidence")
        if run_evidence is None and run_evidence_path:
            run_evidence = _load(None, run_evidence_path)
        if warmup_runs is None:
            warmup_runs = capture_obj.get("warmup_runs")
        if hypotheses is None:
            hypotheses = capture_obj.get("hypotheses")
        if experiments is None:
            experiments = capture_obj.get("experiments")
        if replay_plan is None:
            replay_plan = capture_obj.get("replay_plan")
        if replay_plan is None and replay_plan_path:
            replay_plan = _load(None, replay_plan_path)
        if comparison_matches is None:
            comparison_matches = capture_obj.get("comparison_matches")
        if comparison_alignment is None:
            comparison_alignment = capture_obj.get("comparison_alignment")
        if condition_trace is None:
            condition_trace = capture_obj.get("condition_trace")
        if selected_frame is None:
            selected_frame = capture_obj.get("selected_frame")
        if not frame_domain:
            frame_domain = str(capture_obj.get("frame_domain") or "")
        if epoch is None and "epoch" in capture_obj:
            epoch = capture_obj.get("epoch")
        angle_unit = str(capture_obj.get("angle_unit") or angle_unit or "unknown")
        range_unit = str(capture_obj.get("range_unit") or range_unit or "unknown")
        coordinate_frame = str(capture_obj.get("coordinate_frame") or coordinate_frame or "radar")
        provided_source = _load(source_context, source_context_path)
        raw_capture_source = capture_obj.get("source_context")
        capture_source = dict(raw_capture_source) if isinstance(raw_capture_source, Mapping) else {}
        effective_source = dict(provided_source or capture_source)
        source_conflicts = [
            str(item) for item in effective_source.get("identity_conflicts", []) or [] if str(item).strip()
        ]
        source_conflict_details = [
            dict(item) for item in effective_source.get("identity_conflict_sources", []) or [] if isinstance(item, Mapping)
        ]
        shared_source_fields: list[str] = []
        source_binding_status = "not_available"
        if provided_source and capture_source:
            for key in (
                "data_fingerprint",
                "source_context_id",
                "source_context_fingerprint",
                "binary_fingerprint",
                "config_fingerprint",
                "session_id",
            ):
                provided_value = str(provided_source.get(key) or "").strip()
                capture_value = str(capture_source.get(key) or "").strip()
                if provided_value and capture_value:
                    shared_source_fields.append(key)
                    if provided_value != capture_value:
                        source_conflicts.append(key)
                        source_conflict_details.append({
                            "field": key,
                            "provided_source": provided_value,
                            "capture_source": capture_value,
                        })
            if shared_source_fields:
                source_binding_status = "matched"
        if source_conflicts:
            source_binding_status = "conflict"
            effective_source["identity_conflicts"] = sorted(set(source_conflicts))
            effective_source["identity_conflict_sources"] = source_conflict_details
        effective_source["source_context_binding_status"] = source_binding_status
        snapshot = effective_source.get("source_snapshot") if isinstance(effective_source.get("source_snapshot"), Mapping) else {}
        local_source_artifacts = snapshot.get("local_artifacts") if isinstance(snapshot.get("local_artifacts"), Mapping) else {}
        if not source_root:
            source_root = str(local_source_artifacts.get("algo_source_root") or "")
        if not visualization_source_path:
            visualization_source_path = str(local_source_artifacts.get("visualization_source_path") or "")
        source_execution_contract: dict[str, Any] = {}
        callback_binding_summary: dict[str, Any] = {}
        if strategy == "point_cloud" and source_root and visualization_source_path and capture_obj:
            source_build = snapshot.get("build") if isinstance(snapshot.get("build"), Mapping) else {}
            source_execution_contract = audit_public_perception_source_contract(
                source_root=source_root,
                visualization_source_path=visualization_source_path,
                build_macros=source_build.get("macros") if isinstance(source_build.get("macros"), Mapping) else {},
            )
            capture_obj = bind_public_perception_capture(
                capture_obj,
                source_contract=source_execution_contract,
                capture_id=str(artifact_audit.get("sha256") or "") if isinstance(artifact_audit, Mapping) else "",
            )
            callback_binding_summary = dict(capture_obj.get("callback_binding_summary") or {})
            if not supplied_rows["point_rows"]:
                point_rows = capture_obj.get("point_rows") or []
            if not supplied_rows["cluster_rows"]:
                cluster_rows = capture_obj.get("cluster_rows") or []
            if not supplied_rows["track_rows"]:
                track_rows = capture_obj.get("track_rows") or []
            if not supplied_rows["output_rows"]:
                output_rows = capture_obj.get("output_rows") or []
            if not supplied_rows["lineage_edges"]:
                lineage_edges = capture_obj.get("lineage_edges") or []
            if not supplied_rows["stage_evidence"]:
                stage_evidence = capture_obj.get("stage_evidence") or []
            if not supplied_rows["target_rows"]:
                target_rows = capture_obj.get("target_rows") or []
        bound_layout = effective_source.get("layout_profile") if isinstance(effective_source.get("layout_profile"), Mapping) else None
        schema_text = json.dumps(message_schema or {}, ensure_ascii=False) if isinstance(message_schema, Mapping) else ""
        if bound_layout is not None and ("wfAutosarData" in schema_text or "dotTrans" in schema_text):
            effective_schema = dict(message_schema or {}) if isinstance(message_schema, Mapping) else {}
            effective_schema["layout_profile"] = dict(bound_layout)
            message_schema = effective_schema
        payload_audit = audit_perception_capture(
            capture_obj or {"point_rows": point_rows, "target_rows": target_rows, "stage_evidence": stage_evidence}
        )
        capture_artifact_audit = capture_obj.get("artifact_audit")
        input_artifact_audit = (
            dict(capture_artifact_audit)
            if isinstance(capture_artifact_audit, Mapping) and capture_artifact_audit.get("sha256")
            else dict(artifact_audit)
        )
        capture_data_binding = capture_obj.get("data_binding")
        if isinstance(capture_data_binding, Mapping):
            input_artifact_audit["source_data_binding"] = dict(capture_data_binding)
        effective_code_context = _load(code_context, code_context_path)
        if effective_code_context.get("schema_version") == "code-context.v1" and isinstance(effective_code_context.get("artifacts"), Mapping):
            try:
                effective_code_context = _bounded_code_context(effective_code_context, code_context_path)
            except (OSError, ValueError, TypeError, KeyError):
                effective_code_context["projection_status"] = "partial"
                effective_code_context["projection_diagnostic"] = "bounded_code_context_projection_failed"
        effective_event_code_path = _load(event_code_path, event_code_path_path)
        effective_condition_trace = _load(condition_trace, condition_trace_path)
        effective_stage_map = stage_map or capture_obj.get("stage_map")
        if not effective_stage_map and str(source_root or "").strip():
            effective_stage_map = build_perception_stage_map(source_root, source_files=source_files)
        contract = build_perception_input_contract(
            point_rows,
            source_context=effective_source,
            strategy=strategy,
            message_schema=message_schema,
            target_rows=target_rows,
            target_usage=target_usage,
            conversion=conversion,
            payload_audit=payload_audit,
            artifact_audit=input_artifact_audit,
        )
        coverage = build_stage_coverage(stage_evidence, stage_map=effective_stage_map)
        lineage = build_perception_lineage(
            edges=lineage_edges,
            points=point_rows,
            clusters=cluster_rows,
            tracks=track_rows,
            outputs=output_rows,
            track_population=capture_obj.get("track_population") if isinstance(capture_obj.get("track_population"), Mapping) else {},
            relation_scopes=capture_obj.get("relation_scopes") if isinstance(capture_obj.get("relation_scopes"), Mapping) else {},
        )
        run_obj = dict(run_evidence or {})
        if run_obj and run_obj.get("schema_version") != "perception-run.v1":
            run_obj = build_perception_run_evidence(
                run_id=str(run_obj.get("run_id", "")),
                attempt_id=str(run_obj.get("attempt_id", "")),
                plan_hash=str(run_obj.get("plan_hash", "")),
                terminal_status=str(run_obj.get("terminal_status", run_obj.get("status", "planned"))),
                warmup_requested=run_obj.get("warmup_requested", 175),
                warmup_completed=run_obj.get("warmup_completed"),
                observed_frames=run_obj.get("observed_frames", []),
                completed_frames=run_obj.get("completed_frames", []),
                stage_evidence=stage_evidence,
                reset_events=run_obj.get("reset_events", []),
                identity=run_obj.get("identity", {}),
                diagnostics=run_obj.get("diagnostics", []),
                failure_reason=str(run_obj.get("failure_reason", "")),
            )
        if callback_binding_summary and callback_binding_summary.get("binding_count"):
            callback_frames = [str(item.get("callback_key")) for item in capture_obj.get("callback_bindings", []) or [] if isinstance(item, Mapping) and item.get("callback_key")]
            existing_warmup = run_obj.get("warmup") if isinstance(run_obj.get("warmup"), Mapping) else {}
            run_obj = build_perception_run_evidence(
                run_id=str(run_obj.get("run_id", "")),
                attempt_id=str(run_obj.get("attempt_id", "")),
                plan_hash=str(run_obj.get("plan_hash", "")),
                terminal_status="partial",
                warmup_requested=int(existing_warmup.get("requested", 175) or 175),
                warmup_completed=existing_warmup.get("completed"),
                observed_frames=callback_frames,
                completed_frames=callback_frames,
                stage_evidence=stage_evidence,
                reset_events=run_obj.get("reset_events", []),
                identity=run_obj.get("identity", effective_source),
                diagnostics=list(run_obj.get("diagnostics", []) or []) + ["callback_scoped_public_outputs_bound"],
                failure_reason="reset_and_warmup_ack_not_available",
            )
        if not stage_evidence and run_obj.get("completed_stage_evidence"):
            coverage = build_stage_coverage(run_obj.get("completed_stage_evidence"), stage_map=effective_stage_map)
        comparison = build_perception_comparison(
            recorded_rows=recorded_rows,
            replay_rows=replay_rows,
            explicit_matches=comparison_matches,
            alignment=comparison_alignment,
            recorded_identity=recorded_identity,
            replay_identity=replay_identity,
        ) if recorded_rows or replay_rows or comparison_matches else {}
        scene = build_perception_scene(
            points=point_rows,
            clusters=cluster_rows,
            tracks=track_rows,
            outputs=output_rows,
            selected_frame=selected_frame,
            selection_basis=selection_basis,
            frame_domain=frame_domain,
            epoch=epoch,
            angle_unit=angle_unit,
            range_unit=range_unit,
            coordinate_frame=coordinate_frame,
        )
        timeline = build_perception_timeline(
            stage_coverage=coverage,
            tracks=track_rows,
            outputs=output_rows,
            selected_frame=selected_frame,
            callback_bindings=capture_obj.get("callback_bindings", []) if isinstance(capture_obj.get("callback_bindings"), list) else [],
            callback_binding_summary=callback_binding_summary or (capture_obj.get("callback_binding_summary") if isinstance(capture_obj.get("callback_binding_summary"), Mapping) else {}),
            track_population=capture_obj.get("track_population") if isinstance(capture_obj.get("track_population"), Mapping) else {},
        )
        warmup_analysis = build_perception_warmup_analysis(warmup_runs)
        hypothesis_set = build_perception_hypothesis_set(hypotheses, experiments)
        capability_manifest = build_perception_capability_manifest(
            input_contract=contract,
            stage_coverage=coverage,
            source_context=effective_source,
            replay_plan=replay_plan if isinstance(replay_plan, Mapping) else {},
            run_evidence=run_obj,
            execution_binding=execution_binding if isinstance(execution_binding, Mapping) else {},
        )
        code_flow = build_perception_code_flow(
            stage_map=effective_stage_map,
            stage_coverage=coverage,
            code_context=effective_code_context,
            event_code_path=effective_event_code_path,
            condition_trace=effective_condition_trace,
            source_context=effective_source,
        )
        analysis = build_perception_analysis(
            input_contract=contract,
            stage_coverage=coverage,
            lineage=lineage,
            source_context=effective_source,
            problem=problem,
            code_flow=code_flow,
            run_evidence=run_obj,
            comparison=comparison,
            scene=scene,
            timeline=timeline,
            warmup_analysis=warmup_analysis,
            hypothesis_set=hypothesis_set,
            capability_manifest=capability_manifest,
            source_execution_contract=source_execution_contract or capture_obj.get("source_execution_contract", {}),
            callback_binding_summary=callback_binding_summary or capture_obj.get("callback_binding_summary", {}),
            callback_bindings=capture_obj.get("callback_bindings", []),
        )
        try:
            max_inline_points = max(1, int(max_inline_points))
        except (TypeError, ValueError):
            max_inline_points = 200
        point_artifact: dict[str, Any] | None = None
        lineage_artifact: dict[str, Any] | None = None
        artifacts: list[str] = []
        output_directory: Path | None = None
        automatic_output_dir = False
        if str(output_dir or "").strip():
            output_directory = Path(output_dir).expanduser().resolve()
            output_directory.mkdir(parents=True, exist_ok=True)
        lineage_value = analysis.get("lineage") if isinstance(analysis.get("lineage"), Mapping) else {}
        lineage_nodes = lineage_value.get("nodes") if isinstance(lineage_value.get("nodes"), Mapping) else {}
        lineage_lists = [
            *(lineage_nodes.get(kind, []) for kind in ("points", "clusters", "tracks", "outputs")),
            *(lineage_value.get(kind, []) for kind in ("edges", "raw_edges", "invalid_edges")),
        ]
        needs_point_artifact = len(contract.get("points", []) or []) > max_inline_points
        needs_lineage_artifact = any(isinstance(rows, list) and len(rows) > max_inline_points for rows in lineage_lists)
        if output_directory is None and (needs_point_artifact or needs_lineage_artifact):
            output_directory = _new_point_cloud_output_dir()
            output_directory.mkdir(parents=True, exist_ok=False)
            automatic_output_dir = True
        if needs_point_artifact and output_directory:
            point_artifact = _write_point_artifact(contract.get("points", []) or [], output_directory)
            artifacts.append(str(point_artifact["absolute_path"]))
        if needs_lineage_artifact and output_directory:
            callback_keys = [
                str(row.get("callback_key") or "")
                for row in (analysis.get("callback_bindings", []) or [])
                if isinstance(row, Mapping) and row.get("callback_key")
            ]
            lineage_artifact = _write_lineage_artifact(lineage_value, output_directory, callback_keys=callback_keys)
            artifacts.append(str(lineage_artifact["absolute_path"]))
            if isinstance(lineage_artifact.get("index_ref"), Mapping) and lineage_artifact["index_ref"].get("path"):
                artifacts.append(str(lineage_artifact["index_ref"].get("absolute_path") or (output_directory / str(lineage_artifact["index_ref"]["path"]))))
        bounded_analysis = _bound_analysis(
            analysis,
            max_inline_points=max_inline_points,
            point_artifact=point_artifact,
            lineage_artifact=lineage_artifact,
        )
        payload = {
            "schema_version": "perception-report.v1",
            "status": bounded_analysis["status"],
            "analysis": bounded_analysis,
            "source_stage_map": effective_stage_map or {},
            "artifact_audit": artifact_audit,
            "generated_by": self.name,
            "performance": {"analysis_duration_sec": None},
            "artifact_output": {
                "directory": str(output_directory) if output_directory else "",
                "automatic": automatic_output_dir,
            },
        }
        payload["performance"]["analysis_duration_sec"] = round(time.monotonic() - started_at, 6)
        payload["validation"] = build_perception_validation(report=payload, analysis=bounded_analysis)
        if output_directory is not None:
            json_path = output_directory / "perception-report.json"
            html_path = output_directory / "perception-report.html"
            readme_path = _write_offline_readme(output_directory)
            payload["artifact_paths"] = [str(json_path), str(html_path), str(readme_path), *artifacts]
            json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            html_path.write_text(_html_report(payload), encoding="utf-8")
            artifacts.extend([str(json_path), str(html_path), str(readme_path)])
        return ModuleResult(
            ok=True,
            message=f"point-cloud-analyze:{bounded_analysis['status']}",
            module=self.name,
            artifacts=artifacts,
            data=payload,
        )

    @classmethod
    def register_cli(cls, subparsers: Any) -> Any:
        parser = super().register_cli(subparsers)
        parser.add_argument("--capture-path", default="")
        parser.add_argument("--point-rows", type=json.loads, default=None)
        parser.add_argument("--recorded-rows", type=json.loads, default=None)
        parser.add_argument("--replay-rows", type=json.loads, default=None)
        parser.add_argument("--stage-evidence", type=json.loads, default=None)
        parser.add_argument("--lineage-edges", type=json.loads, default=None)
        parser.add_argument("--message-schema", type=json.loads, default=None)
        parser.add_argument("--target-rows", type=json.loads, default=None)
        parser.add_argument("--target-usage", type=json.loads, default=None)
        parser.add_argument("--conversion", type=json.loads, default=None)
        parser.add_argument("--run-evidence-path", default="")
        parser.add_argument("--warmup-runs", type=json.loads, default=None)
        parser.add_argument("--replay-plan-path", default="")
        parser.add_argument("--comparison-matches", type=json.loads, default=None)
        parser.add_argument("--comparison-alignment", type=json.loads, default=None)
        parser.add_argument("--condition-trace-path", default="")
        parser.add_argument("--selected-frame", default=None)
        parser.add_argument("--selection-basis", default="")
        parser.add_argument("--frame-domain", default="")
        parser.add_argument("--epoch", default=None)
        parser.add_argument("--angle-unit", default="unknown")
        parser.add_argument("--range-unit", default="unknown")
        parser.add_argument("--coordinate-frame", default="radar")
        parser.add_argument("--max-inline-points", type=int, default=200, help="单份报告内嵌的点迹/lineage 最大行数，超出后写入 JSONL 附件")
        parser.add_argument("--source-context-path", default="")
        parser.add_argument("--strategy", choices=["point_cloud", "sgu_injection"], default="point_cloud")
        parser.add_argument("--problem", default="")
        parser.add_argument("--output-dir", default="")
        return parser

    @classmethod
    def from_cli_args(cls, args: Any) -> "PointCloudAnalyzeModule":
        return cls()


__all__ = ["PointCloudAnalyzeModule"]
