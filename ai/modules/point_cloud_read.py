"""Bounded read-only queries over an existing perception report."""
from __future__ import annotations

import json
import hashlib
import math
from pathlib import Path
from typing import Any, Mapping

from .base import BaseModule, ModuleResult


SECTIONS = ("summary", "stages", "lineage", "timeline", "scene", "run", "source", "gaps")


def _object(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _rows(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [dict(row) for row in value if isinstance(row, Mapping)]
    return []


def _count(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _row_frame_key(row: Mapping[str, Any]) -> str:
    raw = row.get("raw") if isinstance(row.get("raw"), Mapping) else {}
    return str(row.get("frame_key") or raw.get("frame_key") or "")


def _compact_mapping(value: Any, *, keys: tuple[str, ...]) -> dict[str, Any]:
    source = _object(value)
    return {key: source[key] for key in keys if key in source and source[key] is not None}


def _compact_lineage_node(kind: str, row: Mapping[str, Any]) -> dict[str, Any]:
    """Keep report queries useful to Pi without forwarding raw message payloads."""
    common = ("frame_key", "frame_domain", "epoch", "radar_id", "status")
    if kind == "points":
        keys = common + (
            "point_key", "point_index", "id", "x", "y", "z", "range", "azimuth", "elevation",
            "doppler", "power", "snr", "noise", "rcs", "cluster_id", "track_id", "source",
        )
        result = {key: row[key] for key in keys if key in row and row[key] is not None}
        source_ref = _compact_mapping(row.get("source_ref"), keys=("topic", "message_seq", "point_index", "point_step", "row_step", "byte_offset"))
        field_status = row.get("field_status")
        if source_ref:
            result["source_ref"] = source_ref
        if isinstance(field_status, Mapping) and field_status:
            result["field_status"] = dict(field_status)
        return result
    if kind == "clusters":
        keys = common + ("cluster_id", "algorithm_cluster_id", "identity_basis")
        return {key: row[key] for key in keys if key in row and row[key] is not None}
    identity_keys = common + (
        "track_key", "output_key", "tracker_instance", "algorithm_track_id", "track_id", "ID", "objID",
        "objUnqID", "obj_conf", "obj_class", "class_conf", "age", "last_frame_update", "distX", "distY",
        "velAbsX", "velAbsY", "fTTC", "fDDCI", "identity_basis", "object_message_seq", "object_index", "topic",
    ) + tuple(
        f"obj{feature}{suffix}"
        for feature in ("Bsd", "Lca", "Dow", "Rcw", "Rcta", "Rctb", "Fcta", "Fctb")
        for suffix in ("WarningFlag",)
    )
    result = {key: row[key] for key in identity_keys if key in row and row[key] is not None}
    for field, nested_keys in (
        ("position", ("x", "y", "z", "dx", "dy", "dz")),
        ("velocity", ("x_dot", "y_dot", "velocity", "Vx", "Vy")),
        ("bounding_box", ("scale_x", "scale_y", "scale_z", "orientation")),
    ):
        nested = _compact_mapping(row.get(field), keys=nested_keys)
        if nested:
            result[field] = nested
    field_status = row.get("field_status")
    if isinstance(field_status, Mapping) and field_status:
        result["field_status"] = dict(field_status)
    diagnostics = row.get("diagnostics")
    if isinstance(diagnostics, list) and diagnostics:
        result["diagnostics"] = [str(item)[:240] for item in diagnostics[:8]]
    return result


def _compact_lineage_edge(row: Mapping[str, Any]) -> dict[str, Any]:
    result = {key: row[key] for key in ("relation_kind", "from", "to", "from_node_kind", "to_node_kind", "status", "validation", "frame_key") if key in row and row[key] is not None}
    basis = _compact_mapping(row.get("basis_ref"), keys=("path", "line", "token", "sha256"))
    if basis:
        result["basis_ref"] = basis
    return result


def _evidence_value_label(value: Any) -> str:
    if value is None:
        return "not_available"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        number = float(value)
        if not math.isfinite(number):
            return "non_finite"
        return str(int(number)) if number.is_integer() else format(number, ".8g")
    return str(value)[:120]


def _field_value_counts(rows: Mapping[str, list[dict[str, Any]]]) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {}
    for node_kind, field in (
        ("points", "cluster_id"), ("points", "track_id"),
        ("clusters", "algorithm_cluster_id"), ("tracks", "algorithm_track_id"),
        ("outputs", "algorithm_track_id"),
    ):
        key = f"{node_kind}.{field}"
        counts: dict[str, int] = {}
        for row in rows.get(node_kind, []):
            label = _evidence_value_label(row.get(field))
            counts[label] = counts.get(label, 0) + 1
        if counts:
            result[key] = dict(sorted(counts.items()))
    return result


def _field_value_summaries(value_counts: Mapping[str, Mapping[str, int]]) -> dict[str, dict[str, int]]:
    return {
        field: {
            "total_count": sum(max(0, _count(count)) for count in counts.values()),
            "unique_value_count": len(counts),
        }
        for field, counts in value_counts.items()
    }


def _relation_value_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        relation = str(row.get("relation_kind") or row.get("kind") or "")
        if relation:
            counts[relation] = counts.get(relation, 0) + 1
    return dict(sorted(counts.items()))


def _relation_value_summaries(rows: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        relation = str(row.get("relation_kind") or row.get("kind") or "")
        if relation:
            grouped.setdefault(relation, []).append(row)
    return {
        relation: {
            "from_node_kind": str(items[0].get("from_node_kind") or "not_available"),
            "to_node_kind": str(items[0].get("to_node_kind") or "not_available"),
            "edge_row_count": len(items),
            "unique_pair_count": len({(str(row.get("from") or row.get("source") or ""), str(row.get("to") or row.get("target") or "")) for row in items}),
            "unique_from_node_count": len({str(row.get("from") or row.get("source") or "") for row in items}),
            "unique_to_node_count": len({str(row.get("to") or row.get("target") or "") for row in items}),
        }
        for relation, items in sorted(grouped.items())
    }


def _bounded(value: Any, limit: int) -> Any:
    """Return a JSON-safe bounded projection without mutating the source."""
    if isinstance(value, Mapping):
        return {str(key): _bounded(child, limit) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_bounded(row, limit) for row in list(value)[:limit]]
    if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
        return None
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _has_long_sequence(value: Any, limit: int) -> bool:
    if isinstance(value, Mapping):
        return any(_has_long_sequence(child, limit) for child in value.values())
    if isinstance(value, (list, tuple)):
        return len(value) > limit or any(_has_long_sequence(child, limit) for child in list(value)[:limit])
    return False


def _artifact_file(report_path: Path, reference: Mapping[str, Any]) -> Path:
    raw = str(reference.get("path") or "")
    if not raw:
        raise ValueError("artifact_path_missing")
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = report_path.parent / candidate
    candidate = candidate.resolve()
    if candidate.parent != report_path.parent.resolve():
        raise ValueError("artifact_outside_report_directory")
    return candidate


def _read_indexed_lineage_slice(
    report_path: Path,
    reference: Mapping[str, Any],
    callback_key: str,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, int], list[str]]:
    selected: dict[str, list[dict[str, Any]]] = {
        "points": [], "clusters": [], "tracks": [], "outputs": [], "edges": [], "raw_edges": [], "invalid_edges": [],
    }
    diagnostics: list[str] = []
    counts_by_type = {"point": 0, "cluster": 0, "track": 0, "output": 0, "edge": 0, "raw_edge": 0, "invalid_edge": 0}
    type_to_kind = {
        "point": "points", "cluster": "clusters", "track": "tracks", "output": "outputs",
        "edge": "edges", "raw_edge": "raw_edges", "invalid_edge": "invalid_edges",
    }
    index_ref = _object(reference.get("index_ref"))
    try:
        index_path = _artifact_file(report_path, index_ref)
        index_bytes = index_path.read_bytes()
        if hashlib.sha256(index_bytes).hexdigest() != str(index_ref.get("sha256") or ""):
            raise ValueError("lineage_index_hash_mismatch")
        index = json.loads(index_bytes.decode("utf-8"))
        if not isinstance(index, Mapping) or index.get("schema_version") != "perception-lineage-index.v1":
            raise ValueError("lineage_index_schema_mismatch")
        artifact_path = _artifact_file(report_path, reference)
        expected_artifact_path = str(index.get("artifact_path") or "")
        if expected_artifact_path:
            expected_path = Path(expected_artifact_path).expanduser()
            if not expected_path.is_absolute():
                expected_path = report_path.parent / expected_path
            if expected_path.resolve() != artifact_path:
                raise ValueError("lineage_index_artifact_path_mismatch")
        if str(index.get("artifact_sha256") or "") != str(reference.get("sha256") or ""):
            raise ValueError("lineage_index_artifact_hash_reference_mismatch")
        expected_size = _count(index.get("artifact_size_bytes"), -1)
        if expected_size < 0 or artifact_path.stat().st_size != expected_size or (reference.get("size_bytes") is not None and _count(reference.get("size_bytes"), -1) != expected_size):
            raise ValueError("lineage_artifact_size_mismatch")
        expected_total_counts = _object(index.get("counts"))
        reference_counts = _object(reference.get("counts"))
        for record_type, expected in reference_counts.items():
            if _count(expected, -1) != _count(expected_total_counts.get(record_type), -2):
                raise ValueError(f"lineage_index_total_count_mismatch:{record_type}")
        callbacks = _object(index.get("callbacks"))
        block = callbacks.get(callback_key)
        if not isinstance(block, Mapping):
            raise ValueError("lineage_callback_not_indexed")
        offset = _count(block.get("offset"), -1)
        length = _count(block.get("length"), -1)
        if offset < 0 or length < 0 or offset + length > expected_size:
            raise ValueError("lineage_callback_range_invalid")
        with artifact_path.open("rb") as handle:
            handle.seek(offset)
            payload = handle.read(length)
        if len(payload) != length or hashlib.sha256(payload).hexdigest() != str(block.get("sha256") or ""):
            raise ValueError("lineage_callback_block_hash_mismatch")
        row_count = 0
        selected_node_keys: set[str] = set()
        for line in payload.splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line.decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError):
                raise ValueError("lineage_callback_invalid_jsonl")
            if not isinstance(record, Mapping):
                raise ValueError("lineage_callback_identity_mismatch")
            record_type = str(record.get("record_type") or "")
            kind = type_to_kind.get(record_type)
            row = record.get("row")
            if not kind or not isinstance(row, Mapping):
                raise ValueError("lineage_callback_record_invalid")
            if kind in {"points", "clusters", "tracks", "outputs"}:
                row_callback = _row_frame_key(row)
                if row_callback and row_callback != callback_key:
                    raise ValueError("lineage_callback_node_identity_mismatch")
                for key in ("point_key", "cluster_id", "track_key", "output_key", "track_id", "object_id", "objID", "ID", "id"):
                    if row.get(key) not in (None, ""):
                        selected_node_keys.add(str(row[key]))
            else:
                row_callback = _row_frame_key(row)
                if row_callback and row_callback != callback_key:
                    raise ValueError("lineage_callback_edge_identity_mismatch")
                endpoints = [str(row.get(key) or "") for key in ("from", "to", "source", "target")]
                if not row_callback and not any(endpoint in selected_node_keys or callback_key in endpoint for endpoint in endpoints):
                    raise ValueError("lineage_callback_edge_unbound")
            selected[kind].append(dict(row))
            counts_by_type[record_type] = counts_by_type.get(record_type, 0) + 1
            row_count += 1
        expected_counts = _object(block.get("counts"))
        if row_count != _count(block.get("row_count"), -1):
            raise ValueError("lineage_callback_row_count_mismatch")
        for record_type, actual in counts_by_type.items():
            if actual != _count(expected_counts.get(record_type), 0):
                raise ValueError(f"lineage_callback_count_mismatch:{record_type}")
    except FileNotFoundError:
        diagnostics.append("lineage_index_or_artifact_missing")
    except (OSError, ValueError, UnicodeError, json.JSONDecodeError) as exc:
        diagnostics.append(str(exc) if isinstance(exc, ValueError) else f"lineage_index_unreadable:{type(exc).__name__}")
    return selected, {key: len(value) for key, value in selected.items()}, list(dict.fromkeys(diagnostics))


def _read_lineage_slice(
    report_path: Path,
    reference: Mapping[str, Any],
    callback_key: str,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, int], list[str]]:
    if _object(reference.get("index_ref")):
        return _read_indexed_lineage_slice(report_path, reference, callback_key)
    selected: dict[str, list[dict[str, Any]]] = {
        "points": [], "clusters": [], "tracks": [], "outputs": [], "edges": [], "raw_edges": [], "invalid_edges": [],
    }
    total_counts: dict[str, int] = {}
    diagnostics: list[str] = []
    digest = hashlib.sha256()
    row_count = 0
    selected_node_keys: set[str] = set()

    def belongs(key: Any) -> bool:
        value = str(key or "")
        return value == callback_key or value.startswith(callback_key + ":") or (":" + callback_key + ":") in value

    try:
        artifact_path = _artifact_file(report_path, reference)
        with artifact_path.open("rb") as handle:
            for line in handle:
                digest.update(line)
                if not line.strip():
                    continue
                row_count += 1
                try:
                    record = json.loads(line.decode("utf-8"))
                except (UnicodeError, json.JSONDecodeError):
                    diagnostics.append("lineage_artifact_invalid_jsonl")
                    continue
                if not isinstance(record, Mapping):
                    diagnostics.append("lineage_artifact_record_not_object")
                    continue
                record_type = str(record.get("record_type") or "")
                row = record.get("row") if isinstance(record.get("row"), Mapping) else {}
                total_counts[record_type] = total_counts.get(record_type, 0) + 1
                kind = {
                    "point": "points", "cluster": "clusters", "track": "tracks", "output": "outputs",
                    "edge": "edges", "raw_edge": "raw_edges", "invalid_edge": "invalid_edges",
                }.get(record_type)
                if not kind:
                    diagnostics.append(f"lineage_artifact_unknown_record_type:{record_type or 'missing'}")
                    continue
                if kind in {"edges", "raw_edges", "invalid_edges"}:
                    include = belongs(row.get("frame_key")) or belongs(row.get("from")) or belongs(row.get("to")) or str(row.get("from") or "") in selected_node_keys or str(row.get("to") or "") in selected_node_keys
                else:
                    include = _row_frame_key(row) == callback_key
                    if include:
                        for key in ("point_key", "cluster_id", "track_key", "output_key", "track_id", "id"):
                            if row.get(key) not in (None, ""):
                                selected_node_keys.add(str(row[key]))
                if include:
                    selected[kind].append(dict(row))
    except FileNotFoundError:
        diagnostics.append("lineage_artifact_missing")
    except (OSError, ValueError) as exc:
        diagnostics.append(str(exc) if isinstance(exc, ValueError) else f"lineage_artifact_unreadable:{type(exc).__name__}")

    expected_hash = str(reference.get("sha256") or "")
    expected_rows = reference.get("row_count")
    expected_counts = _object(reference.get("counts"))
    if not diagnostics and expected_hash and digest.hexdigest() != expected_hash:
        diagnostics.append("lineage_artifact_hash_mismatch")
    if not diagnostics and expected_rows is not None and _count(expected_rows, -1) != row_count:
        diagnostics.append("lineage_artifact_row_count_mismatch")
    for record_type, expected in expected_counts.items():
        if not diagnostics and _count(expected, -1) != total_counts.get(str(record_type), 0):
            diagnostics.append(f"lineage_artifact_count_mismatch:{record_type}")
    return selected, {key: len(value) for key, value in selected.items()}, list(dict.fromkeys(diagnostics))


def _read_point_slice(report_path: Path, reference: Mapping[str, Any], callback_key: str) -> tuple[list[dict[str, Any]], list[str]]:
    selected: list[dict[str, Any]] = []
    diagnostics: list[str] = []
    digest = hashlib.sha256()
    row_count = 0
    try:
        artifact_path = _artifact_file(report_path, reference)
        with artifact_path.open("rb") as handle:
            for line in handle:
                digest.update(line)
                if not line.strip():
                    continue
                row_count += 1
                try:
                    point = json.loads(line.decode("utf-8"))
                except (UnicodeError, json.JSONDecodeError):
                    diagnostics.append("point_artifact_invalid_jsonl")
                    continue
                if not isinstance(point, Mapping):
                    diagnostics.append("point_artifact_record_not_object")
                    continue
                raw = point.get("raw") if isinstance(point.get("raw"), Mapping) else {}
                point_frame = str(point.get("frame_key") or raw.get("frame_key") or "")
                if point_frame == callback_key:
                    selected.append(dict(point))
    except FileNotFoundError:
        diagnostics.append("point_artifact_missing")
    except (OSError, ValueError) as exc:
        diagnostics.append(str(exc) if isinstance(exc, ValueError) else f"point_artifact_unreadable:{type(exc).__name__}")
    expected_hash = str(reference.get("sha256") or "")
    if not diagnostics and expected_hash and digest.hexdigest() != expected_hash:
        diagnostics.append("point_artifact_hash_mismatch")
    expected_count = reference.get("point_count")
    if not diagnostics and expected_count is not None and _count(expected_count, -1) != row_count:
        diagnostics.append("point_artifact_count_mismatch")
    return selected, list(dict.fromkeys(diagnostics))


class PointCloudReadModule(BaseModule):
    """Read a small, report-backed perception slice for Pi or an operator."""

    name = "point-cloud-read"
    description = "对已有 perception-report 做有界只读查询；同时区分规范关系边、原始重复边和唯一端点计数；lineage 默认定位报告选中帧，不重新解析 rosbag 或启动 ROS"
    tags = ["point-cloud", "perception", "report", "read", "query", "read-only", "atomic"]
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "report_path": {"type": "string"},
            "section": {"type": "string", "enum": list(SECTIONS), "default": "summary"},
            "callback_key": {"type": "string", "description": "完整 callback key；section=lineage 未传时默认使用报告当前 selected_frame"},
            "limit": {"type": "integer", "default": 40, "minimum": 1, "maximum": 200},
            "offset": {"type": "integer", "default": 0, "minimum": 0, "description": "lineage 分页偏移量"},
        },
        "required": ["report_path"],
        "additionalProperties": False,
    }
    output_schema: dict[str, Any] = {
        "type": "object",
        "required": ["schema_version", "status", "section", "report_ref", "data", "truncated"],
    }

    def run(
        self,
        *,
        report_path: str,
        section: str = "summary",
        callback_key: str = "",
        limit: int = 40,
        offset: int = 0,
        **_: Any,
    ) -> ModuleResult:
        path = Path(report_path).expanduser().resolve()
        callback_key = str(callback_key or "").strip()
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return ModuleResult(ok=True, message="point-cloud-read:not_found", module=self.name, data={
                "schema_version": "perception-report-query.v1", "status": "not_found", "section": section,
                "report_ref": str(path), "data": {}, "truncated": False,
                "diagnostics": ["perception_report_missing"],
            })
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            return ModuleResult(ok=True, message="point-cloud-read:invalid", module=self.name, data={
                "schema_version": "perception-report-query.v1", "status": "blocked", "section": section,
                "report_ref": str(path), "data": {}, "truncated": False,
                "diagnostics": [f"perception_report_unreadable:{type(exc).__name__}"],
            })
        if not isinstance(report, Mapping) or report.get("schema_version") != "perception-report.v1":
            return ModuleResult(ok=True, message="point-cloud-read:schema_mismatch", module=self.name, data={
                "schema_version": "perception-report-query.v1", "status": "blocked", "section": section,
                "report_ref": str(path), "data": {}, "truncated": False,
                "diagnostics": ["perception_report_schema_mismatch"],
            })
        if section not in SECTIONS:
            return ModuleResult.fail(f"unsupported section: {section}", module=self.name)
        try:
            limit = min(200, max(1, int(limit)))
        except (TypeError, ValueError):
            limit = 40
        offset = _count(offset, 0)
        offset = max(0, offset)
        callback_key_basis = "requested" if callback_key else ""
        analysis = _object(report.get("analysis"))
        contract = _object(analysis.get("input_contract"))
        coverage = _object(analysis.get("stage_coverage"))
        lineage = _object(analysis.get("lineage"))
        scene = _object(analysis.get("scene"))
        run = _object(analysis.get("run_evidence"))
        source_contract = _object(analysis.get("source_execution_contract"))
        callback_summary = _object(analysis.get("callback_binding_summary"))
        callback_bindings = _rows(analysis.get("callback_bindings"))
        if section == "lineage" and not callback_key:
            selected_frame = str(scene.get("selected_frame") or "")
            if selected_frame and any(str(row.get("callback_key") or "") == selected_frame for row in callback_bindings):
                callback_key = selected_frame
                callback_key_basis = "report_selected_frame"
        truncated = False
        query_diagnostics: list[str] = []
        result_status = "ready" if report.get("status") not in {"blocked", "invalid"} else str(report.get("status"))

        if section == "summary":
            node_groups = _object(lineage.get("nodes"))
            node_counts = _object(lineage.get("node_counts"))
            point_artifact = _object(contract.get("points_artifact"))
            if not node_counts:
                node_counts = {kind: len(_rows(node_groups.get(kind))) for kind in ("points", "clusters", "tracks", "outputs")}
                if node_groups.get("points_truncated") or contract.get("points_truncated"):
                    node_counts["points"] = _count(point_artifact.get("point_count") or contract.get("point_count"), node_counts["points"])
            data: Any = {
                "report_status": report.get("status"),
                "analysis_status": analysis.get("status"),
                "conclusion_level": analysis.get("conclusion_level"),
                "strategy": analysis.get("strategy"),
                "problem": analysis.get("problem"),
                "input": {
                    "boundary": contract.get("input_boundary"),
                    "layout_status": contract.get("layout_status"),
                    "point_count": contract.get("point_count"),
                    "radar_summary": contract.get("radar_summary", []),
                    "target_usage": contract.get("target_usage", {}),
                },
                "stage_coverage": {
                    "status": coverage.get("status"),
                    "available_stage_count": coverage.get("available_stage_count"),
                    "derived_stage_count": coverage.get("derived_stage_count"),
                    "total_stage_count": coverage.get("total_stage_count"),
                    "stages": [
                        {key: row.get(key) for key in ("stage", "status", "runtime_proof", "input_count", "output_count", "frame_count", "source_ref")}
                        for row in _rows(coverage.get("stages"))
                    ],
                },
                "lineage": {
                    **{key: lineage.get(key) for key in ("status", "edge_count", "relation_kinds", "identity_warnings")},
                    "relation_counts": lineage.get("relation_counts", {}),
                    "raw_relation_counts": lineage.get("raw_relation_counts", {}),
                    "relation_summaries": lineage.get("relation_summaries", {}),
                    "track_population": lineage.get("track_population", {}),
                    "relation_scopes": lineage.get("relation_scopes", {}),
                    "invalid_edge_count": _count(lineage.get("invalid_edge_count"), len(lineage.get("invalid_edges", []) or [])),
                    "raw_edge_count": _count(lineage.get("raw_edge_count"), len(lineage.get("raw_edges", []) or [])),
                    "node_counts": {kind: _count(node_counts.get(kind), len(_rows(node_groups.get(kind)))) for kind in ("points", "clusters", "tracks", "outputs")},
                    "nodes_truncated": bool(lineage.get("nodes_truncated") or node_groups.get("points_truncated")),
                    "edges_truncated": bool(lineage.get("edges_truncated")),
                    "lineage_artifact": lineage.get("lineage_artifact", {}),
                },
                "callback_binding": dict(callback_summary),
                "run": {key: run.get(key) for key in ("status", "terminal_status", "reset_status", "warmup", "runtime_proof", "diagnostics")},
                "scene": {key: scene.get(key) for key in ("status", "selected_frame", "selection_basis", "coordinate_frame", "counts")},
                "gaps": _rows(analysis.get("gaps")),
                "validation": report.get("validation", {}),
            }
        elif section == "stages":
            data = [
                {key: row.get(key) for key in ("stage", "status", "runtime_proof", "input_count", "output_count", "frames", "frame_count", "source_ref", "diagnostics", "evidence_rows")}
                for row in _rows(coverage.get("stages"))
            ]
        elif section == "lineage":
            nodes = _object(lineage.get("nodes"))
            edges = _rows(lineage.get("edges"))
            invalid = _rows(lineage.get("invalid_edges"))
            raw_edges = _rows(lineage.get("raw_edges"))
            full_node_counts = _object(lineage.get("node_counts"))
            node_rows: dict[str, list[dict[str, Any]]] = {kind: _rows(nodes.get(kind)) for kind in ("points", "clusters", "tracks", "outputs")}
            if not full_node_counts:
                full_node_counts = {kind: len(node_rows[kind]) for kind in node_rows}
                if nodes.get("points_truncated") or contract.get("points_truncated"):
                    point_artifact_ref = _object(contract.get("points_artifact"))
                    full_node_counts["points"] = _count(point_artifact_ref.get("point_count") or contract.get("point_count"), len(node_rows["points"]))
            if callback_key:
                def matches(row: Mapping[str, Any]) -> bool:
                    return _row_frame_key(row) == callback_key

                lineage_artifact_ref = _object(lineage.get("lineage_artifact"))
                if lineage_artifact_ref:
                    selected, selected_counts, diagnostics = _read_lineage_slice(path, lineage_artifact_ref, callback_key)
                    if diagnostics:
                        query_diagnostics.extend(diagnostics)
                        result_status = "partial"
                        for kind in node_rows:
                            node_rows[kind] = [row for row in node_rows[kind] if matches(row)]
                        def fallback_edge_matches(row: Mapping[str, Any]) -> bool:
                            return callback_key in str(row.get("from", "")) or callback_key in str(row.get("to", "")) or _row_frame_key(row) == callback_key
                        edges = [row for row in edges if fallback_edge_matches(row)]
                        raw_edges = [row for row in raw_edges if fallback_edge_matches(row)]
                        invalid = [row for row in invalid if fallback_edge_matches(row)]
                        full_node_counts = {kind: len(node_rows[kind]) for kind in node_rows}
                    else:
                        node_rows = {kind: selected[kind] for kind in ("points", "clusters", "tracks", "outputs")}
                        edges = selected["edges"]
                        raw_edges = selected["raw_edges"]
                        invalid = selected["invalid_edges"]
                        full_node_counts = {kind: selected_counts[kind] for kind in ("points", "clusters", "tracks", "outputs")}
                else:
                    point_artifact_ref = _object(contract.get("points_artifact"))
                    if point_artifact_ref and (nodes.get("points_truncated") or contract.get("points_truncated")):
                        point_rows, diagnostics = _read_point_slice(path, point_artifact_ref, callback_key)
                        if diagnostics:
                            query_diagnostics.extend(diagnostics)
                            result_status = "partial"
                        else:
                            node_rows["points"] = point_rows
                    else:
                        node_rows["points"] = [row for row in node_rows["points"] if matches(row)]
                    for kind in ("clusters", "tracks", "outputs"):
                        node_rows[kind] = [row for row in node_rows[kind] if matches(row)]
                    def edge_matches(row: Mapping[str, Any]) -> bool:
                        return callback_key in str(row.get("from", "")) or callback_key in str(row.get("to", "")) or _row_frame_key(row) == callback_key
                    edges = [row for row in edges if edge_matches(row)]
                    raw_edges = [row for row in raw_edges if edge_matches(row)]
                    invalid = [row for row in invalid if edge_matches(row)]
                    full_node_counts = {kind: len(node_rows[kind]) for kind in node_rows}
            node_counts = {kind: _count(full_node_counts.get(kind), len(node_rows[kind])) for kind in ("points", "clusters", "tracks", "outputs")}
            node_totals = {kind: _count(node_counts.get(kind), len(node_rows[kind])) for kind in node_rows}
            full_edge_count = len(edges) if callback_key else _count(lineage.get("edge_count"), len(edges))
            if callback_key and not query_diagnostics:
                relation_counts = _relation_value_counts(edges)
                raw_relation_counts = _relation_value_counts(raw_edges)
                relation_summaries = _relation_value_summaries(edges)
                field_counts = _field_value_counts(node_rows)
            elif callback_key:
                relation_counts = {}
                raw_relation_counts = {}
                relation_summaries = {}
                field_counts = {}
            else:
                relation_counts = _object(lineage.get("relation_counts")) if not lineage.get("edges_truncated") else {}
                raw_relation_counts = _object(lineage.get("raw_relation_counts")) if not lineage.get("raw_edges_truncated") else {}
                relation_summaries = _object(lineage.get("relation_summaries")) if not lineage.get("edges_truncated") else {}
                field_counts = {} if lineage.get("nodes_truncated") or nodes.get("points_truncated") else _field_value_counts(node_rows)
            field_summaries = _field_value_summaries(field_counts)
            inline_nodes = {
                kind: [_compact_lineage_node(kind, row) for row in rows[offset:offset + limit]]
                for kind, rows in node_rows.items()
            }
            edge_page = [_compact_lineage_edge(row) for row in edges[offset:offset + limit]]
            invalid_page = [_compact_lineage_edge(row) for row in invalid[offset:offset + limit]]
            raw_page = [_compact_lineage_edge(row) for row in raw_edges[offset:offset + limit]]
            data = {
                "status": lineage.get("status"),
                "relation_kinds": lineage.get("relation_kinds", []),
                "relation_counts": dict(relation_counts),
                "raw_relation_counts": dict(raw_relation_counts),
                "relation_summaries": relation_summaries,
                "track_population": lineage.get("track_population", {}),
                "relation_scopes": lineage.get("relation_scopes", {}),
                "field_counts": field_counts,
                "field_summaries": field_summaries,
                "identity_warnings": lineage.get("identity_warnings", []),
                "node_counts": node_counts,
                "nodes": inline_nodes,
                "edges": edge_page,
                "raw_edges": raw_page,
                "invalid_edges": invalid_page,
                "raw_edge_count": len(raw_edges) if callback_key else _count(lineage.get("raw_edge_count"), len(raw_edges)),
                "full_invalid_edge_count": len(invalid) if callback_key else _count(lineage.get("invalid_edge_count"), len(invalid)),
                "callback_key": callback_key or None,
                "callback_key_basis": callback_key_basis or ("not_requested" if not callback_key else "requested"),
                "full_edge_count": full_edge_count,
                "page": {
                    "offset": offset,
                    "limit": limit,
                    "has_more": {
                        **{kind: node_totals[kind] > offset + limit for kind in node_totals},
                        "edges": (len(edges) if callback_key else _count(lineage.get("edge_count"), len(edges))) > offset + limit,
                    },
                },
            }
            truncated = any(total > offset + limit for total in (*node_totals.values(), len(edges) if callback_key else _count(lineage.get("edge_count"), len(edges)), len(invalid) if callback_key else _count(lineage.get("invalid_edge_count"), len(invalid)), len(raw_edges) if callback_key else _count(lineage.get("raw_edge_count"), len(raw_edges))))
            if not callback_key:
                truncated = truncated or bool(lineage.get("nodes_truncated") or nodes.get("points_truncated") or lineage.get("edges_truncated") or lineage.get("raw_edges_truncated") or lineage.get("invalid_edges_truncated"))
        elif section == "scene":
            data = dict(scene)
        elif section == "timeline":
            data = dict(_object(analysis.get("timeline")))
            if callback_key and str(data.get("selected_frame") or "") != callback_key:
                query_diagnostics.append("timeline_not_available_for_requested_callback")
                result_status = "partial"
        elif section == "run":
            data = dict(run)
        elif section == "source":
            code_flow = _object(analysis.get("code_flow"))
            data = {
                "source_execution_contract": dict(source_contract),
                "source_context": analysis.get("source_context", {}),
                "code_flow": dict(code_flow),
            }
        else:
            data = _rows(analysis.get("gaps"))
        if isinstance(data, list) and len(data) > limit:
            data = data[:limit]
            truncated = True
        truncated = truncated or _has_long_sequence(data, limit)
        return ModuleResult(ok=True, message=f"point-cloud-read:{section}", module=self.name, data={
            "schema_version": "perception-report-query.v1",
            "status": result_status,
            "section": section,
            "report_ref": str(path),
            "data": _bounded(data, limit),
            "truncated": truncated,
            "diagnostics": list(dict.fromkeys(query_diagnostics)),
        })

    @classmethod
    def register_cli(cls, subparsers: Any) -> Any:
        parser = super().register_cli(subparsers)
        parser.add_argument("--report-path", required=True)
        parser.add_argument("--section", choices=SECTIONS, default="summary")
        parser.add_argument("--callback-key", default="")
        parser.add_argument("--limit", type=int, default=40)
        parser.add_argument("--offset", type=int, default=0)
        return parser

    @classmethod
    def from_cli_args(cls, args: Any) -> "PointCloudReadModule":
        return cls()


__all__ = ["PointCloudReadModule", "SECTIONS"]
