from __future__ import annotations

import struct
import hashlib
import json
import sys
from types import SimpleNamespace

from tools.decode_lgu_output import DOT_STRUCT, OBJ_STRUCT, decode_bag, decode_dot_buffer, decode_object_buffer, decode_pointcloud2_message, bind_layout_profile, main


def test_decode_dot_buffer_preserves_units_and_source_provenance():
    prefix = bytes(728)
    row = DOT_STRUCT.pack(500, -125, 250, -50, -3, 7, 4, 2, 90, 80, 70, 1)
    payload = decode_dot_buffer(prefix + row, frame_id=42, lgu_num=1, radar_id=2, topic="/wf/corner_radar/lgu_data_2", source_message_seq=9)
    assert len(payload) == 1
    point = payload[0]
    assert point["range"] == 5.0
    assert point["doppler"] == -1.25
    assert point["azimuth"] == 2.5
    assert point["elevation"] == -0.5
    assert point["quality"] == {"azimuth": 90, "elevation": 80, "velocity": 70}
    assert point["source_ref"]["byte_offset"] == 728
    assert point["source_ref"]["raw_token"] == "PERInfoOutStruct.dotTrans"


def test_decode_dot_buffer_rejects_short_payload():
    try:
        decode_dot_buffer(b"\x00", frame_id=1, lgu_num=1)
    except ValueError as exc:
        assert "outputData_short_for_lgu_num" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("short outputData must be rejected")


def test_decode_dot_buffer_keeps_unsigned_quality_values_and_requires_fixed_layout(tmp_path):
    row = DOT_STRUCT.pack(500, -125, 250, -50, -3, 7, 4, 2, 250, 200, 180, 1)
    point = decode_dot_buffer(bytes(728) + row, frame_id=1, lgu_num=1)[0]
    assert point["quality"] == {"azimuth": 250, "elevation": 200, "velocity": 180}
    assert point["status"] == "observed_with_layout_warning"
    profile = bind_layout_profile(source_snapshot_hash="source-sha", source_contract_ref="perception_public_api.h")
    source_only = decode_dot_buffer(bytes(728) + row, frame_id=1, lgu_num=1, layout_profile=profile)[0]
    assert source_only["status"] == "observed_with_layout_warning"
    assert source_only["source_ref"]["source_layout_verified"] is True
    assert source_only["source_ref"]["recording_layout_status"] == "recording_version_unbound"
    assert source_only["source_ref"]["layout_verified"] is False

    evidence_path = tmp_path / "recording-layout-review.json"
    evidence_path.write_bytes(b"reviewed layout compatibility fixture")
    evidence_sha = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    bound_profile = bind_layout_profile(
        source_snapshot_hash="source-sha",
        source_contract_ref="perception_public_api.h",
        recording_compatibility={
            "status": "verified",
            "source_snapshot_hash": "source-sha",
            "recording_fingerprint": "a" * 64,
            "recording_version": "producer-build-v3",
            "compatibility_evidence_ref": str(evidence_path.resolve()),
            "compatibility_evidence_sha256": evidence_sha,
        },
    )
    verified = decode_dot_buffer(
        bytes(728) + row,
        frame_id=1,
        lgu_num=1,
        layout_profile=bound_profile,
        recording_fingerprint="a" * 64,
    )[0]
    assert verified["status"] == "observed"
    assert verified["source_ref"]["layout_verified"] is True

    mismatched = decode_dot_buffer(
        bytes(728) + row,
        frame_id=1,
        lgu_num=1,
        layout_profile=bound_profile,
        recording_fingerprint="c" * 64,
    )[0]
    assert mismatched["status"] == "observed_with_layout_warning"
    assert mismatched["source_ref"]["recording_layout_status"] == "recording_fingerprint_conflict"


def test_decode_bag_binds_recording_compatibility_to_exact_file_hash(tmp_path, monkeypatch):
    bag_path = tmp_path / "capture.bag"
    bag_bytes = b"versioned-recording-fixture"
    bag_path.write_bytes(bag_bytes)
    bag_hash = hashlib.sha256(bag_bytes).hexdigest()
    point_bytes = bytes(728) + bytes.fromhex("6400c8002c0190010102030405060701")
    evidence_path = tmp_path / "recording-layout-review.json"
    evidence_path.write_bytes(b"reviewed layout compatibility fixture")
    evidence_sha = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    message = SimpleNamespace(
        frameID=12,
        LGUNum=1,
        SGUNum=0,
        outputData=point_bytes,
        header=SimpleNamespace(seq=3),
    )

    class FakeBag:
        def __init__(self, path, mode):
            assert path == str(bag_path)
            assert mode == "r"

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read_messages(self, *, topics):
            assert topics == ["/wf/corner_radar/lgu_data_2"]
            yield topics[0], message, None

    monkeypatch.setitem(sys.modules, "rosbag", SimpleNamespace(Bag=FakeBag))
    profile = bind_layout_profile(
        source_snapshot_hash="source-sha",
        source_contract_ref="perception_public_api.h@source-sha",
        recording_compatibility={
            "status": "verified",
            "source_snapshot_hash": "source-sha",
            "recording_fingerprint": bag_hash,
            "recording_version": "producer-build-v3",
            "compatibility_evidence_ref": str(evidence_path.resolve()),
            "compatibility_evidence_sha256": evidence_sha,
        },
    )

    aligned = decode_bag(
        bag_path,
        topic="/wf/corner_radar/lgu_data_2",
        data_fingerprint=bag_hash,
        layout_profile=profile,
    )
    assert aligned["status"] == "ready"
    assert aligned["layout_status"] == "verified"
    assert aligned["data_binding"]["status"] == "aligned"
    assert aligned["point_rows"][0]["status"] == "observed"
    assert aligned["point_rows"][0]["quality"] == {"azimuth": 5, "elevation": 6, "velocity": 7}

    mismatch = decode_bag(
        bag_path,
        topic="/wf/corner_radar/lgu_data_2",
        data_fingerprint="different-source-hash",
        layout_profile=profile,
    )
    assert mismatch["status"] == "partial"
    assert mismatch["data_binding"]["status"] == "conflict"
    assert "input_data_fingerprint_conflict" in mismatch["diagnostics"]


def test_decode_lgu_cli_hashes_reviewed_recording_compatibility_evidence(tmp_path, monkeypatch):
    bag_path = tmp_path / "capture.bag"
    bag_bytes = b"versioned-recording-fixture"
    bag_path.write_bytes(bag_bytes)
    bag_hash = hashlib.sha256(bag_bytes).hexdigest()
    evidence_path = tmp_path / "recording-layout-compatibility.json"
    evidence_path.write_text(json.dumps({
        "status": "verified",
        "source_snapshot_hash": "source-sha",
        "recording_fingerprint": bag_hash,
        "recording_version": "producer-build-v3",
    }), encoding="utf-8")
    point_bytes = bytes(728) + bytes.fromhex("6400c8002c0190010102030405060701")
    message = SimpleNamespace(frameID=12, LGUNum=1, SGUNum=0, outputData=point_bytes, header=SimpleNamespace(seq=3))

    class FakeBag:
        def __init__(self, path, mode):
            assert path == str(bag_path)
            assert mode == "r"

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read_messages(self, *, topics):
            yield topics[0], message, None

    monkeypatch.setitem(sys.modules, "rosbag", SimpleNamespace(Bag=FakeBag))
    output_path = tmp_path / "capture.json"
    monkeypatch.setattr(sys, "argv", [
        "decode_lgu_output.py",
        "--bag-path", str(bag_path),
        "--topic", "/wf/corner_radar/lgu_data_2",
        "--data-fingerprint", bag_hash,
        "--layout-source-hash", "source-sha",
        "--layout-contract-ref", "perception_public_api.h@source-sha",
        "--recording-compatibility-path", str(evidence_path),
        "--output", str(output_path),
    ])

    assert main() == 0
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    compatibility = payload["message_schema"]["layout_profile"]["recording_compatibility"]
    assert payload["status"] == "ready"
    assert payload["layout_status"] == "verified"
    assert compatibility["compatibility_evidence_ref"] == str(evidence_path.resolve())
    assert compatibility["compatibility_evidence_sha256"] == hashlib.sha256(evidence_path.read_bytes()).hexdigest()


def test_decode_object_buffer_keeps_output_fields_separate_from_points():
    values = (1200, -300, 400, 200, 150, 44, 2, 1, 1, 0, 0, 0, 0, 0, 1, 0, 2, 3, 4, 5, 6, 7, 8, 900, -20)
    payload = bytes(8) + OBJ_STRUCT.pack(*values) + bytes(728 - 8 - OBJ_STRUCT.size)
    rows = decode_object_buffer(payload, frame_id=42, sgu_num=1, radar_id=2, topic="/wf/corner_radar/lgu_data_2")
    assert rows[0]["object_id"] == 44
    assert rows[0]["dist_x"] == 12.0
    assert rows[0]["dist_y"] == -3.0
    assert rows[0]["warning_flags"]["fcta"] == 1
    assert rows[0]["source_ref"]["raw_token"] == "PERInfoOutStruct.objTrans"


def test_decode_pointcloud2_message_uses_declared_field_offsets():
    class Field:
        def __init__(self, name, offset, datatype, count=1):
            self.name, self.offset, self.datatype, self.count = name, offset, datatype, count

    class Message:
        width = 2
        height = 1
        point_step = 12
        row_step = 24
        is_bigendian = False
        fields = [Field("x", 0, 7), Field("y", 4, 7), Field("z", 8, 7)]
        data = struct.pack("<fff", 1.0, 2.0, 3.0) + struct.pack("<fff", -1.0, -2.0, -3.0)

    rows = decode_pointcloud2_message(Message(), topic="/wf/corner_radar/rviz/pointcloud_2")
    assert rows[0]["x"] == 1.0
    assert rows[1]["z"] == -3.0
    assert rows[0]["source_ref"]["point_step"] == 12


def test_decode_pointcloud2_rejects_truncated_row_and_marks_field_layout_partial():
    class Field:
        name, offset, datatype, count = "x", 8, 7, 1

    class Message:
        width = 1
        height = 1
        point_step = 4
        row_step = 4
        is_bigendian = False
        fields = [Field()]
        data = b"\x00" * 4

    rows = decode_pointcloud2_message(Message())
    assert rows[0]["status"] == "partial"
    assert "field_outside_point_step:x" in rows[0]["diagnostics"]
