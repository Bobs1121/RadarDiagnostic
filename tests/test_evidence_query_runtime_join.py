# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path

from ai.modules.evidence_query import EvidenceQueryModule
from engines.evidence_query import _bound_field_list, build_evidence_query


def _event() -> dict:
    return {
        "event_id": "evt-1",
        "function": "FCTA_R",
        "radar_id": 2,
        "frame_precheck": {"alarm_first_frame_id": 100},
        "details": {"feature": {"entry_function": "FrontCrossTrafficAlertAndBrake"}},
        "target": {"selected": {"obj_id": 44}},
    }


def test_runtime_join_keeps_source_entry_gdb_and_selected_public_object():
    runtime = {
        "observations": [
            {
                "observation_id": "public-frame",
                "layer": "runtime_with_frame",
                "identity": {"radar_id": 2, "frame_id": 100},
                "fields": [],
            },
            {
                "observation_id": "public-other-object",
                "layer": "objectlist_candidate",
                "identity": {"radar_id": 2, "frame_id": 100, "object_id": 7},
                "fields": [],
            },
            {
                "observation_id": "public-selected-object",
                "layer": "objectlist_candidate",
                "identity": {"radar_id": 2, "frame_id": 100, "object_id": 44},
                "fields": [{"token": "objID", "value": 44}],
            },
            {
                "observation_id": "gdb-source-entry",
                "layer": "gdb_observation",
                "identity": {
                    "radar_id": 2,
                    "frame_id": 100,
                    "object_id": 44,
                    "function": "FrontCrossTrafficAlertAndBrake",
                },
                "fields": [{"token": "fTTMX", "value": 1.0}],
            },
        ],
    }
    result = build_evidence_query(
        bundle={"alarm_events": [_event()]},
        viewer_model={"events": [_event()]},
        runtime_evidence=runtime,
        function="FCTA",
        side="R",
        radar_id=2,
        frame_id=100,
        max_events=1,
        max_frames=3,
        max_targets=4,
        include_details=True,
    )
    rows = result["events"][0]["runtime_observations"]
    ids = {row["observation_id"] for row in rows}
    assert "gdb-source-entry" in ids
    assert "public-selected-object" in ids
    assert "public-frame" in ids
    assert result["events"][0]["runtime_association"] == "exact_event_or_frame_truncated"


def test_bounded_runtime_fields_keep_numeric_prediction_over_pointer_or_missing_token():
    rows = [
        {"token": "frameID", "value": 47877, "status": "observed"},
        {"token": "fInterX", "value": "", "status": "not_found"},
        {"token": "fInterX", "value": "0x7fffffffcb08", "status": "observed"},
    ]
    rows.extend({"token": f"noise_{index}", "value": index, "status": "observed"} for index in range(400))
    rows.extend([
        {"token": "fInterX", "value": 8.38272381, "status": "observed"},
        {"token": "fInterY", "value": 0.0, "status": "observed"},
        {"token": "fTTMY", "value": 0.564559579, "status": "observed"},
    ])

    bounded = _bound_field_list(rows, 256)
    numeric_x = [row for row in bounded if row.get("token") == "fInterX" and isinstance(row.get("value"), (int, float))]
    assert numeric_x
    assert numeric_x[-1]["value"] == 8.38272381


def _unbound_ros_object_snapshot() -> dict:
    return {
        "schema_version": "runtime-snapshot-with-frame.v1",
        "status": "partial",
        "source_context": {"runtime_source": "ros-topic-inventory.v1"},
        "capture_metadata": {
            "schema_version": "public-runtime-capture-metadata.v1",
            "identity_binding": {"status": "not_bound"},
            "inventory_path": "outputs/inventory.json",
            "inventory_sha256": "inventory-sha",
            "topic_samples": [
                {
                    "topic": "/wf/objectlist_2",
                    "message_type": "arbe_msgs/wfObjectMsg",
                    "message_definition_sha256": "definition-sha",
                    "object_field_count": 3,
                    "object_field_catalog_truncated": False,
                    "object_field_catalog": [
                        {"token": "ID", "type": "int32", "source_path": "arbe_msgs/wfSObj.ID"},
                        {"token": "objID", "type": "uint32", "source_path": "arbe_msgs/wfSObj.objID"},
                        {"token": "distX", "type": "float32", "source_path": "arbe_msgs/wfSObj.distX"},
                    ],
                }
            ],
        },
        "warning_rising_edges": [],
        "snapshots": [],
        "unbound_objects": [
            {
                "association_status": "unbound",
                "radar_id": 2,
                "frame_id": None,
                "callback_id": None,
                "object_index": 0,
                "fields": {
                    "ID": 0,
                    "objID": 44,
                    "distX": 5.0,
                    "radar_id": 2,
                    "topic": "/wf/objectlist_2",
                    "source_ref": {
                        "topic": "/wf/objectlist_2",
                        "field_path": "arbe_msgs/wfObjectMsg.ObjectsBuffer",
                        "sample_sha256": "sample-sha",
                    },
                },
            }
        ],
        "association_policy": {"time_neighbour_matching": False},
        "diagnostics": ["objectlist_rows_without_frame_or_callback_remain_unbound"],
    }


def test_runtime_snapshot_query_returns_bounded_schema_backed_unbound_object_fields():
    result = build_evidence_query(
        runtime_snapshot=_unbound_ros_object_snapshot(),
        radar_id=2,
        fields=["objID", "distX"],
        max_targets=2,
        max_field_rows=2,
    )
    assert result["status"] == "partial"
    assert result["events"] == []
    assert result["matched_event_count"] == 0
    assert result["matched_runtime_object_count"] == 1
    assert result["runtime_snapshot_total_count"] == 1
    row = result["runtime_snapshot_rows"][0]
    assert row["association_status"] == "unbound"
    assert row["event_association_status"] == "not_available"
    assert {field["token"]: field["value"] for field in row["field_rows"]} == {
        "objID": 44,
        "distX": 5.0,
    }
    assert row["source_ref"]["inventory_sha256"] == "inventory-sha"
    assert "runtime_snapshot_identity_not_bound" in result["diagnostics"]


def test_runtime_snapshot_query_does_not_match_unbound_objects_to_a_requested_frame():
    result = build_evidence_query(
        runtime_snapshot=_unbound_ros_object_snapshot(),
        radar_id=2,
        frame_id=47877,
    )
    assert result["status"] == "not_found"
    assert result["runtime_snapshot_rows"] == []
    assert result["matched_runtime_object_count"] == 0
    assert "unbound_runtime_snapshot_rows_excluded_by_frame_filter" in result["diagnostics"]
    assert "runtime_snapshot_has_no_exact_frame_match" in result["diagnostics"]


def test_runtime_snapshot_query_marks_tokens_missing_from_current_message_schema():
    result = build_evidence_query(
        runtime_snapshot=_unbound_ros_object_snapshot(),
        radar_id=2,
        fields=["inventedAlias"],
    )
    field = result["runtime_snapshot_rows"][0]["field_rows"][0]
    assert field["token"] == "inventedAlias"
    assert field["status"] == "not_available"
    assert field["reason"] == "field_not_in_current_message_definition"


def test_evidence_query_module_accepts_runtime_snapshot_without_bundle(tmp_path: Path):
    snapshot_path = tmp_path / "runtime-snapshot.json"
    snapshot_path.write_text(json.dumps(_unbound_ros_object_snapshot()), encoding="utf-8")
    result = EvidenceQueryModule().safe_run(
        runtime_snapshot_path=str(snapshot_path),
        radar_id=2,
        fields=["objID"],
    )
    assert result.ok is True
    assert result.data["status"] == "partial"
    assert result.data["runtime_snapshot_rows"][0]["field_rows"][0]["value"] == 44
