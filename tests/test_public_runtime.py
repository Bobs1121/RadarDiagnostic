# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path

from ai.modules import MODULE_REGISTRY
from ai.modules.public_runtime import PublicRuntimeNormalizeModule
from engines.arbe.public_runtime import detect_warning_rising_edges, normalize_public_runtime


def test_public_runtime_binds_warning_and_ego_by_frame_but_not_timestamp_only_object():
    payload = normalize_public_runtime(
        warning_rows=[{"source": "warning_status_with_frame", "data": [2, 47877, 0, 0, 0, 0, 0]}],
        radar_info_rows=[{"data": [2.0, 3.2, 0.1, 1.0, 47877.0, 10.0]}],
        object_rows=[
            {"radar_id": 2, "header_stamp": 123.4, "objID": 44, "distX": 5.0}
        ],
    )
    assert payload["status"] == "ready"
    assert len(payload["snapshots"]) == 1
    snapshot = payload["snapshots"][0]
    assert snapshot["radar_id"] == 2
    assert snapshot["frame_id"] == 47877
    assert snapshot["warning"]["warnings"] == [0, 0, 0, 0, 0]
    assert snapshot["radar_info"]["ego_speed"] == 3.2
    assert snapshot["objects"] == []
    assert payload["unbound_objects"][0]["association_status"] == "unbound"
    assert payload["association_policy"]["time_neighbour_matching"] is False


def test_public_runtime_accepts_explicit_frame_or_callback_association():
    payload = normalize_public_runtime(
        warning_rows=[{"radar_id": 1, "frame_id": 10, "callback_id": "c10"}],
        object_rows=[
            {"radar_id": 1, "frame_id": 10, "object_index": 0, "objID": 7},
            {"radar_id": 1, "callback_id": "c10", "object_index": 1, "objID": 8},
        ],
    )
    assert len(payload["snapshots"]) == 1
    statuses = [row["association_status"] for row in payload["snapshots"][0]["objects"]]
    assert statuses == ["frame_verified", "callback_correlated"]


def test_public_runtime_binds_object_by_verified_publication_order_only_when_opted_in():
    payload = normalize_public_runtime(
        warning_rows=[
            {"source": "warning_status_with_frame", "data": [2, 10] + [0] * 15, "message_seq": 2},
            {"source": "warning_status_with_frame", "data": [2, 11] + [0] * 15, "message_seq": 5},
        ],
        object_rows=[
            {"radar_id": 2, "object_message_seq": 1, "object_index": 0, "objID": 44},
            {"radar_id": 2, "object_message_seq": 3, "object_index": 0, "objID": 44},
        ],
        object_association_mode="publication_order",
    )
    assert payload["unbound_objects"] == []
    assert [
        (item["frame_id"], item["objects"][0]["association_status"])
        for item in payload["snapshots"]
    ] == [(10, "publication_correlated"), (11, "publication_correlated")]
    assert payload["association_policy"]["object_association_mode"] == "publication_order"
    evidence = payload["snapshots"][0]["objects"][0]["association_evidence"]
    assert evidence["confidence"] == "derived"
    assert evidence["object_message_seq"] == 1
    assert evidence["warning_message_seq"] == 2
    assert evidence["warning_frame_id"] == 10


def test_public_runtime_auto_uses_publication_order_only_with_source_proof():
    payload = normalize_public_runtime(
        warning_rows=[
            {"source": "warning_status_with_frame", "data": [2, 10] + [0] * 15, "message_seq": 2},
            {"source": "warning_status_with_frame", "data": [2, 11] + [0] * 15, "message_seq": 5},
        ],
        object_rows=[
            {"radar_id": 2, "object_message_seq": 1, "objID": 44},
            {"radar_id": 2, "object_message_seq": 3, "objID": 44},
        ],
        object_association_mode="auto",
        preflight={
            "public_evidence": {
                "objectlist_frame_contract": {"status": "source_verified"},
            },
        },
    )
    assert payload["association_policy"]["requested_object_association_mode"] == "auto"
    assert payload["association_policy"]["object_association_mode"] == "publication_order"
    assert payload["snapshots"][0]["objects"][0]["association_status"] == "publication_correlated"


def test_public_runtime_matches_arbe_gui_negative_id_sentinel_policy():
    payload = normalize_public_runtime(
        warning_rows=[{"radar_id": 2, "frame_id": 10}],
        object_rows=[
            {"radar_id": 2, "frame_id": 10, "ID": -1, "objID": 0},
            {"radar_id": 2, "frame_id": 10, "ID": 0, "objID": 44},
        ],
        object_validity_policy="arbe_wf_sobj",
    )
    assert [item["fields"]["ID"] for item in payload["snapshots"][0]["objects"]] == [0]
    assert payload["ignored_objects"][0]["reason"] == "arbe_wf_sobj_negative_ID_sentinel"


def test_public_runtime_detects_rising_edges_with_external_source_mapping():
    rows = [
        {"radar_id": 2, "frame_id": 10, "bits": [0, 0]},
        {"radar_id": 2, "frame_id": 11, "bits": [1, 0]},
        {"radar_id": 2, "frame_id": 12, "bits": [2, 1]},
    ]
    edges = detect_warning_rising_edges(rows, warning_names=["FCTA_R", "FCTB_R"])
    assert [(row["frame_id"], row["signal_name"], row["value"]) for row in edges] == [
        (11, "FCTA_R", 1),
        (12, "FCTB_R", 1),
    ]


def test_public_runtime_persists_warning_mapping_for_later_runtime_normalization():
    payload = normalize_public_runtime(
        warning_rows=[{"radar_id": 2, "frame_id": 10, "bits": [1, 0]}],
        warning_names=["FCTA_R", "FCTB_R"],
    )
    assert payload["warning_names"] == ["FCTA_R", "FCTB_R"]


def test_public_runtime_module_reads_capture_file_and_writes_artifact(tmp_path: Path):
    capture = tmp_path / "capture.json"
    capture.write_text(
        json.dumps({"warning_rows": [{"radar_id": 3, "frame_id": 20}]}),
        encoding="utf-8",
    )
    output = tmp_path / "runtime.json"
    result = PublicRuntimeNormalizeModule().safe_run(
        capture_path=str(capture), output=str(output)
    )
    assert result.ok
    assert output.exists()
    assert result.data["schema_version"] == "runtime-snapshot-with-frame.v1"
    assert MODULE_REGISTRY["public-runtime-normalize"] is PublicRuntimeNormalizeModule
