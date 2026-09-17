"""Decode the post-detection ``PERInfoOutStruct.dotTrans`` payload in an LGU bag.

This helper is intentionally read-only.  It does not start ROS, change an arbe
workspace, or claim that the dotTrans payload represents ADC/FFT/CFAR input.
The C source contract is explicit: dotOutStrunct is 16 bytes and the variable
dot array is the tail of ``PERInfoOutStruct`` after the fixed prefix.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path
from typing import Any, Iterable, Mapping


# `dotOutStrunct` is 16 bytes in the current public layout.  The four metric
# fields and power/SNR/RCS are signed; quality/index/ambiguity fields are
# uint8.  Treating all tail bytes as signed changes values above 127 and can
# silently corrupt quality and local-peer metadata.
DOT_STRUCT = struct.Struct("<hhhhbbbBBBBB")
OBJ_STRUCT = struct.Struct("<hhHHhBBBbbbbbbbbBBBhhhhHh")
DOT_LAYOUT_PROFILE: dict[str, Any] = {
    "name": "arbe_PERInfoOutStruct_debug_tail_v3",
    "version": "v3",
    "fixed_prefix_size": 728,
    "dot_struct_size": DOT_STRUCT.size,
    "dot_struct_format": DOT_STRUCT.format,
    "max_dot_count": 4096,
    # A profile bundled with this helper is a parser contract, not proof that
    # the recording producer used exactly this layout. `verified` binds the
    # C layout to a source snapshot; recording compatibility is separate.
    "source_snapshot_hash": "",
    "verified": False,
}
OBJ_LAYOUT_PROFILE: dict[str, Any] = {
    "name": "arbe_PERInfoOutStruct_debug_tail_v3",
    "version": "v3",
    "object_offset": 8,
    "object_struct_size": OBJ_STRUCT.size,
    "max_object_count": 16,
    "source_snapshot_hash": "",
    "verified": False,
}


def bind_layout_profile(
    *,
    source_snapshot_hash: str,
    source_contract_ref: str,
    fixed_prefix_size: int = 728,
    verified: bool = True,
    recording_compatibility: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Bind the parser layout to an active source and optional recording proof.

    The helper does not inspect a repository or invent a hash.  Callers must
    provide the source snapshot/contract reference produced by their current
    code-context probe. Source binding alone cannot verify a recording; a
    recording compatibility object must name the exact file hash, version,
    source snapshot, and hash-bound evidence reference.
    """
    snapshot = str(source_snapshot_hash or "").strip()
    contract_ref = str(source_contract_ref or "").strip()
    if not snapshot or not contract_ref:
        raise ValueError("layout_source_binding_requires_snapshot_and_contract")
    profile = dict(DOT_LAYOUT_PROFILE)
    profile.update({
        "fixed_prefix_size": int(fixed_prefix_size),
        "source_snapshot_hash": snapshot,
        "source_contract_ref": contract_ref,
        "verified": bool(verified),
        "recording_compatibility": dict(recording_compatibility or {}),
    })
    return profile


def _valid_sha256(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return len(text) == 64 and all(char in "0123456789abcdef" for char in text)


def _layout_profile_status(
    profile: Mapping[str, Any] | None,
    *,
    recording_fingerprint: str = "",
) -> str:
    """Require an active source layout and this exact recording to be bound."""
    layout = dict(profile or {})
    source_hash = str(layout.get("source_snapshot_hash") or "").strip()
    source_ref = str(layout.get("source_contract_ref") or "").strip()
    if not bool(layout.get("verified")) or not source_hash or not source_ref:
        return "source_layout_unverified"
    compatibility = layout.get("recording_compatibility")
    compatibility = compatibility if isinstance(compatibility, Mapping) else {}
    if str(compatibility.get("status") or "") != "verified":
        return "recording_version_unbound"
    if str(compatibility.get("source_snapshot_hash") or "").strip() != source_hash:
        return "source_layout_conflict"
    expected_recording = str(compatibility.get("recording_fingerprint") or "").strip().lower()
    actual_recording = str(recording_fingerprint or "").strip().lower()
    if not _valid_sha256(expected_recording) or not _valid_sha256(actual_recording):
        return "recording_fingerprint_unavailable"
    if expected_recording != actual_recording:
        return "recording_fingerprint_conflict"
    recording_version = str(
        compatibility.get("recording_version")
        or compatibility.get("recording_source_fingerprint")
        or compatibility.get("producer_binary_fingerprint")
        or ""
    ).strip()
    evidence_ref = str(
        compatibility.get("compatibility_evidence_ref")
        or compatibility.get("evidence_ref")
        or ""
    ).strip()
    evidence_sha = compatibility.get("compatibility_evidence_sha256") or compatibility.get("evidence_sha256")
    if not recording_version or not evidence_ref or not _valid_sha256(evidence_sha):
        return "recording_compatibility_evidence_incomplete"
    evidence_path = Path(evidence_ref).expanduser()
    if not evidence_path.is_absolute() or not evidence_path.is_file():
        return "recording_compatibility_evidence_unavailable"
    evidence_digest = hashlib.sha256()
    try:
        with evidence_path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                evidence_digest.update(chunk)
    except OSError:
        return "recording_compatibility_evidence_unavailable"
    if evidence_digest.hexdigest() != str(evidence_sha).strip().lower():
        return "recording_compatibility_evidence_hash_conflict"
    return "verified"
POINT_FIELD_FORMATS = {
    1: ("b", 1), 2: ("B", 1), 3: ("h", 2), 4: ("H", 2),
    5: ("i", 4), 6: ("I", 4), 7: ("f", 4), 8: ("d", 8),
}
SCHEMA_VERSION = "perception-capture.v1"


def decode_dot_buffer(
    output_data: bytes | bytearray | memoryview,
    *,
    frame_id: int,
    lgu_num: int,
    radar_id: str | int = "",
    topic: str = "",
    source_message_seq: int | None = None,
    layout_profile: Mapping[str, Any] | None = None,
    recording_fingerprint: str = "",
    dot_offset: int | None = None,
) -> list[dict[str, Any]]:
    """Decode ``dotTrans`` with a source- and recording-bound layout.

    The old implementation inferred the array offset from ``len(raw)``.  That
    makes a truncated or padded message look valid.  The fixed prefix/offset is
    now part of the parser profile; callers can override it only explicitly.
    Values remain available with a layout warning until the exact recording is
    bound to a reviewed compatibility record.
    """
    raw = bytes(output_data)
    count = max(0, int(lgu_num))
    profile = dict(DOT_LAYOUT_PROFILE)
    if isinstance(layout_profile, Mapping):
        profile.update(dict(layout_profile))
    layout_status = _layout_profile_status(profile, recording_fingerprint=recording_fingerprint)
    try:
        struct_size = int(profile.get("dot_struct_size", DOT_STRUCT.size))
        prefix_size = int(profile.get("fixed_prefix_size", 728))
        max_count = int(profile.get("max_dot_count", 4096))
    except (TypeError, ValueError) as exc:
        raise ValueError("dot_layout_profile_invalid") from exc
    if struct_size != DOT_STRUCT.size:
        raise ValueError(f"dot_layout_profile_struct_size_mismatch:{struct_size}:{DOT_STRUCT.size}")
    if count > max_count:
        raise ValueError(f"outputData_lgu_num_exceeds_layout:{count}:{max_count}")
    offset = prefix_size if dot_offset is None else int(dot_offset)
    if offset < 0 or offset + count * struct_size > len(raw):
        raise ValueError(f"outputData_short_for_lgu_num_layout:{len(raw)}:{offset}:{count}:{struct_size}")
    rows: list[dict[str, Any]] = []
    for index in range(count):
        values = DOT_STRUCT.unpack_from(raw, offset + index * DOT_STRUCT.size)
        distance, velocity, azimuth, elevation, power, snr, rcs, peer, theta_q, phi_q, dv_q, ambiguous = values
        rows.append({
            "point_key": f"{topic or 'lgu'}:{frame_id}:{index}",
            "frame_id": int(frame_id),
            "radar_id": radar_id,
            "range": distance / 100.0,
            "doppler": velocity / 100.0,
            "azimuth": azimuth / 100.0,
            "elevation": elevation / 100.0,
            "power": int(power),
            "snr": int(snr),
            "rcs": int(rcs),
            "quality": {"azimuth": int(theta_q), "elevation": int(phi_q), "velocity": int(dv_q)},
            "azimuth_ambiguous": bool(ambiguous),
            "source": "PERInfoOutStruct.dotTrans",
            "source_ref": {
                "topic": topic,
                "frame_id": int(frame_id),
                "message_seq": source_message_seq,
                "byte_offset": offset + index * DOT_STRUCT.size,
                "struct_size": DOT_STRUCT.size,
                "raw_token": "PERInfoOutStruct.dotTrans",
                "layout_profile": profile.get("name", "unknown"),
                "source_layout_verified": bool(profile.get("verified", False)),
                "recording_layout_status": layout_status,
                "layout_verified": layout_status == "verified",
                "source_snapshot_hash": str(profile.get("source_snapshot_hash", "")),
            },
            "status": "observed" if layout_status == "verified" else "observed_with_layout_warning",
        })
    return rows


def decode_object_buffer(
    output_data: bytes | bytearray | memoryview,
    *,
    frame_id: int,
    sgu_num: int,
    radar_id: str | int = "",
    topic: str = "",
    layout_profile: Mapping[str, Any] | None = None,
    recording_fingerprint: str = "",
) -> list[dict[str, Any]]:
    """Decode the fixed ``PERInfoOutStruct.objTrans`` output array."""
    raw = bytes(output_data)
    profile = dict(OBJ_LAYOUT_PROFILE)
    if isinstance(layout_profile, Mapping):
        profile.update(dict(layout_profile))
    layout_status = _layout_profile_status(profile, recording_fingerprint=recording_fingerprint)
    count = max(0, min(int(sgu_num), int(profile.get("max_object_count", 16))))
    offset = int(profile.get("object_offset", 8))
    struct_size = int(profile.get("object_struct_size", OBJ_STRUCT.size))
    if struct_size != OBJ_STRUCT.size:
        raise ValueError(f"object_layout_profile_struct_size_mismatch:{struct_size}:{OBJ_STRUCT.size}")
    if len(raw) < offset + count * struct_size:
        raise ValueError(f"outputData_short_for_sgu_num:{len(raw)}:{offset}:{count}")
    rows: list[dict[str, Any]] = []
    for index in range(count):
        values = OBJ_STRUCT.unpack_from(raw, offset + index * OBJ_STRUCT.size)
        dist_x, dist_y, length, width, yaw, obj_id, obj_type, dyn, *rest = values
        warnings = rest[:8]
        refer_pt, lifecycle, history_dist, vel_x, vel_y, vel_abs_x, vel_abs_y, f_ttc, f_ddci = rest[8:]
        rows.append({
            "output_key": f"{topic or 'lgu'}:{frame_id}:obj:{index}",
            "frame_id": int(frame_id),
            "radar_id": radar_id,
            "object_index": index,
            "object_id": int(obj_id),
            "object_type": int(obj_type),
            "dist_x": dist_x / 100.0,
            "dist_y": dist_y / 100.0,
            "length": length / 100.0,
            "width": width / 100.0,
            "yaw": yaw / 100.0,
            "vel_x": vel_x / 100.0,
            "vel_y": vel_y / 100.0,
            "vel_abs_x": vel_abs_x / 100.0,
            "vel_abs_y": vel_abs_y / 100.0,
            "f_ttc": f_ttc / 100.0,
            "f_ddci": f_ddci / 100.0,
            "dynamic_flag": int(dyn),
            "warning_flags": {
                name: int(value) for name, value in zip(("bsd", "lca", "dow", "rcw", "rcta", "rctb", "fcta", "fctb"), warnings)
            },
            "reference_point": int(refer_pt),
            "lifecycle": int(lifecycle),
            "history_moving_distance": int(history_dist),
            "source": "PERInfoOutStruct.objTrans",
            "source_ref": {
                "topic": topic,
                "frame_id": int(frame_id),
                "byte_offset": offset + index * OBJ_STRUCT.size,
                "struct_size": OBJ_STRUCT.size,
                "raw_token": "PERInfoOutStruct.objTrans",
                "layout_profile": profile.get("name", "unknown"),
                "source_layout_verified": bool(profile.get("verified", False)),
                "recording_layout_status": layout_status,
                "layout_verified": layout_status == "verified",
                "source_snapshot_hash": str(profile.get("source_snapshot_hash", "")),
            },
            "status": "observed" if layout_status == "verified" else "observed_with_layout_warning",
        })
    return rows


def decode_pointcloud2_message(message: Any, *, topic: str = "") -> list[dict[str, Any]]:
    """Decode a sensor_msgs/PointCloud2-like object without ROS dependencies."""
    fields = list(getattr(message, "fields", []) or [])
    raw = bytes(getattr(message, "data", b"") or b"")
    width = int(getattr(message, "width", 0) or 0)
    height = int(getattr(message, "height", 1) or 1)
    point_step = int(getattr(message, "point_step", 0) or 0)
    row_step = int(getattr(message, "row_step", point_step * width) or 0)
    endian = ">" if bool(getattr(message, "is_bigendian", False)) else "<"
    if width < 0 or height < 0 or point_step <= 0 or row_step <= 0:
        raise ValueError("pointcloud2_invalid_layout")
    if row_step < width * point_step:
        raise ValueError("pointcloud2_row_step_shorter_than_row")
    expected_bytes = row_step * height
    if len(raw) < expected_bytes:
        raise ValueError(f"pointcloud2_data_truncated:{len(raw)}:{expected_bytes}")
    rows: list[dict[str, Any]] = []
    for index in range(width * height):
        row_index, column = divmod(index, width or 1)
        base = row_index * row_step + column * point_step
        values: dict[str, Any] = {}
        row_status = "observed"
        row_diagnostics: list[str] = []
        for field in fields:
            name = str(getattr(field, "name", "") or "")
            datatype = int(getattr(field, "datatype", 0) or 0)
            offset = int(getattr(field, "offset", 0) or 0)
            count = max(1, int(getattr(field, "count", 1) or 1))
            spec = POINT_FIELD_FORMATS.get(datatype)
            if not name or spec is None:
                continue
            fmt, size = spec
            if offset < 0 or offset + size * count > point_step:
                values[name] = None
                row_status = "partial"
                row_diagnostics.append(f"field_outside_point_step:{name}")
                continue
            try:
                unpacked = struct.unpack_from(endian + (fmt * count), raw, base + offset)
            except struct.error:
                values[name] = None
                row_status = "partial"
                row_diagnostics.append(f"field_data_unavailable:{name}")
                continue
            values[name] = unpacked[0] if count == 1 else list(unpacked)
        values.update({
            "point_index": index,
            "source": "sensor_msgs/PointCloud2",
            "source_ref": {"topic": topic, "point_index": index, "point_step": point_step, "row_step": row_step},
            "status": row_status,
            "diagnostics": row_diagnostics,
        })
        rows.append(values)
    return rows


def _file_audit(path: str | Path) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    digest = hashlib.sha256()
    size = 0
    with target.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            size += len(chunk)
            digest.update(chunk)
    return {"path": str(target), "size_bytes": size, "sha256": digest.hexdigest(), "status": "observed"}


def decode_bag(
    bag_path: str | Path,
    *,
    topic: str,
    limit: int = 200,
    radar_id: str | int = "",
    data_fingerprint: str = "",
    source_context_id: str = "",
    layout_profile: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Read a bounded number of LGU messages using the target's rosbag runtime."""
    try:
        import rosbag  # type: ignore
    except ImportError as exc:  # pragma: no cover - depends on remote ROS runtime
        raise RuntimeError("rosbag_python_not_available") from exc
    target = str(Path(bag_path).expanduser())
    artifact_audit = _file_audit(target)
    effective_profile = dict(DOT_LAYOUT_PROFILE if layout_profile is None else layout_profile)
    recording_fingerprint = str(artifact_audit.get("sha256") or "")
    layout_status = _layout_profile_status(effective_profile, recording_fingerprint=recording_fingerprint)
    effective_profile["recording_layout_status"] = layout_status
    if data_fingerprint and recording_fingerprint and data_fingerprint == recording_fingerprint:
        data_binding_status = "aligned"
    elif data_fingerprint and recording_fingerprint:
        data_binding_status = "conflict"
    else:
        data_binding_status = "not_available"
    points: list[dict[str, Any]] = []
    object_rows: list[dict[str, Any]] = []
    message_count = 0
    with rosbag.Bag(target, "r") as bag:
        for _, message, _ in bag.read_messages(topics=[topic]):
            message_count += 1
            frame_id = int(getattr(message, "frameID", 0))
            lgu_num = int(getattr(message, "LGUNum", 0))
            output_data = getattr(message, "outputData", b"")
            header = getattr(message, "header", None)
            sequence = int(getattr(header, "seq", message_count)) if header is not None else message_count
            points.extend(decode_dot_buffer(
                output_data,
                frame_id=frame_id,
                lgu_num=lgu_num,
                radar_id=radar_id,
                topic=topic,
                source_message_seq=sequence,
                layout_profile=effective_profile,
                recording_fingerprint=recording_fingerprint,
            ))
            # Object rows are output evidence from the same payload; they are
            # intentionally kept separate from point input and no lineage edge
            # is inferred between them.
            object_rows.extend(decode_object_buffer(
                output_data,
                frame_id=frame_id,
                sgu_num=int(getattr(message, "SGUNum", 0)),
                radar_id=radar_id,
                topic=topic,
                layout_profile=effective_profile,
                recording_fingerprint=recording_fingerprint,
            ))
            if message_count >= max(1, int(limit)):
                break
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "ready" if points and layout_status == "verified" and data_binding_status == "aligned" else "partial",
        "input_boundary": "post_detection_point_cloud",
        "message_schema": {
            "type": "arbe_msgs/wfAutosarData",
            "payload": "PERInfoOutStruct.dotTrans",
            "dot_struct_size": DOT_STRUCT.size,
            "layout_profile": effective_profile,
            "layout_status": layout_status,
        },
        "source_context": {
            "data_fingerprint": data_fingerprint,
            "source_context_id": source_context_id,
        },
        "artifact_audit": artifact_audit,
        "data_binding": {
            "status": data_binding_status,
            "source_data_fingerprint": str(data_fingerprint or ""),
            "artifact_sha256": recording_fingerprint,
            "relationship": "same_recording" if data_binding_status == "aligned" else "conflict" if data_binding_status == "conflict" else "not_available",
        },
        "layout_status": layout_status,
        "topic": topic,
        "radar_id": radar_id,
        "message_count": message_count,
        "point_rows": points,
        "output_rows": object_rows,
        "target_usage": {"status": "not_available", "basis": "dotTrans_only"},
        "limitations": [
            "dotTrans is post-detection point evidence; it does not prove ADC/FFT/CFAR execution",
            "object/cluster/track lineage is not decoded by this helper",
        ],
        "diagnostics": (
            ([] if points else ["no_dot_rows_decoded"])
            + ([layout_status] if layout_status != "verified" else [])
            + (["input_data_fingerprint_conflict"] if data_binding_status == "conflict" else [])
            + (["input_data_fingerprint_unavailable"] if data_binding_status == "not_available" else [])
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bag-path", required=True)
    parser.add_argument("--topic", required=True)
    parser.add_argument("--radar-id", default="")
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--data-fingerprint", default="")
    parser.add_argument("--source-context-id", default="")
    parser.add_argument("--layout-source-hash", default="", help="Resolved active source snapshot hash")
    parser.add_argument("--layout-contract-ref", default="", help="Resolved C layout contract reference")
    parser.add_argument("--layout-prefix-size", type=int, default=728)
    parser.add_argument("--recording-compatibility-path", default="", help="Reviewed recording/source layout compatibility evidence JSON")
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    recording_compatibility: Mapping[str, Any] | None = None
    if args.recording_compatibility_path:
        evidence_path = Path(args.recording_compatibility_path).expanduser().resolve()
        evidence_bytes = evidence_path.read_bytes()
        evidence_value = json.loads(evidence_bytes.decode("utf-8"))
        if not isinstance(evidence_value, Mapping):
            raise ValueError("recording_compatibility_evidence_must_be_object")
        recording_compatibility = dict(evidence_value)
        evidence_sha = hashlib.sha256(evidence_bytes).hexdigest()
        declared_evidence_sha = str(
            recording_compatibility.get("compatibility_evidence_sha256")
            or recording_compatibility.get("evidence_sha256")
            or ""
        ).strip()
        if declared_evidence_sha and declared_evidence_sha.lower() != evidence_sha:
            raise ValueError("recording_compatibility_evidence_hash_mismatch")
        recording_compatibility["compatibility_evidence_ref"] = str(evidence_path)
        recording_compatibility["compatibility_evidence_sha256"] = evidence_sha
    layout_profile = None
    if args.layout_source_hash or args.layout_contract_ref:
        layout_profile = bind_layout_profile(
            source_snapshot_hash=args.layout_source_hash,
            source_contract_ref=args.layout_contract_ref,
            fixed_prefix_size=args.layout_prefix_size,
            recording_compatibility=recording_compatibility,
        )
    payload = decode_bag(
        args.bag_path,
        topic=args.topic,
        radar_id=args.radar_id,
        limit=args.limit,
        data_fingerprint=args.data_fingerprint,
        source_context_id=args.source_context_id,
        layout_profile=layout_profile,
    )
    encoded = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        Path(args.output).expanduser().resolve().write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DOT_STRUCT", "OBJ_STRUCT", "DOT_LAYOUT_PROFILE", "OBJ_LAYOUT_PROFILE", "bind_layout_profile",
    "decode_dot_buffer", "decode_object_buffer", "decode_pointcloud2_message",
    "decode_bag", "main",
]
