# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import hashlib
from pathlib import Path

from ai.modules import MODULE_REGISTRY
from ai.modules.public_runtime import PublicRuntimeNormalizeModule
from engines.arbe.public_runtime import (
    detect_warning_rising_edges,
    normalize_public_runtime,
    runtime_capture_from_topic_inventory,
)


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


def test_public_runtime_projects_ros_inventory_object_rows_as_stamped_unbound_capture(tmp_path: Path):
    sample_text = (
        "ObjectsBuffer:\n"
        "- ID: 0\n"
        "  objID: 44\n"
        "  distX: 5.0\n"
        "  distY: -1.25\n"
    )
    inventory = {
        "schema_version": "ros-topic-inventory.v1",
        "status": "ready",
        "observed_at_utc": "2026-09-15T06:20:00.000Z",
        "server": {"host": "10.190.171.44", "user": "test", "port": 22, "transport": "ssh"},
        "requested_topics": ["/wf/objectlist_2"],
        "topics": [
            {
                "topic": "/wf/objectlist_2",
                "type": "arbe_msgs/wfObjectMsg",
                "publishers": ["/radar2_visualization_engine"],
                "subscribers": ["/arbe_gui"],
                "publisher_count": 1,
                "subscriber_count": 1,
                "data_observable": True,
                "status": "ready",
                "message_schema": {
                    "status": "ready",
                    "message_type": "arbe_msgs/wfObjectMsg",
                    "message_definition_sha256": "definition-sha",
                    "field_count": 2,
                    "field_catalog_truncated": False,
                    "field_catalog": [
                        {
                            "message_type": "arbe_msgs/wfObjectMsg",
                            "name": "ObjectsBuffer",
                            "type": "arbe_msgs/wfSObj[]",
                            "path": "arbe_msgs/wfObjectMsg.ObjectsBuffer",
                        },
                        {
                            "message_type": "arbe_msgs/wfSObj",
                            "name": "objID",
                            "type": "uint32",
                            "path": "arbe_msgs/wfSObj.objID",
                        },
                    ],
                },
                "sample": {
                    "status": "observed",
                    "message_observed": True,
                    "observed_at_utc": "2026-09-15T06:20:01.000Z",
                    "observation_clock": "client_utc",
                    "stdout": sample_text,
                    "stdout_sha256": hashlib.sha256(sample_text.encode("utf-8")).hexdigest(),
                    "stdout_char_count": len(sample_text),
                    "stdout_truncated": False,
                },
            }
        ],
    }
    plan = {
        "schema_version": "public-topic-plan.v1",
        "status": "ready",
        "source_schema": {
            "preflight_server": {"host": "10.190.171.44", "user": "test", "port": 22, "transport": "ssh"},
            "preflight_workspace": {"arbe_root": "/home/test/arbe", "algo_source": {"head": "abc"}},
        },
        "channels": [
            {
                "channel_id": "algorithm_object_display_{radar_id}",
                "topic": "/wf/objectlist_{radar_id}",
                "source_kind": "ros_wfObjectMsg",
                "frame_key": "not_in_message",
                "guarantee": "display subset without a frame id",
            }
        ],
    }
    preflight = {
        "schema_version": "arbe-preflight.v1",
        "status": "ready",
        "server": {"host": "10.190.171.44", "user": "test", "port": 22, "transport": "ssh"},
        "workspace": {"arbe_root": "/home/test/arbe", "algo_source": {"head": "abc"}},
        "public_evidence": {
            "objectlist_frame_contract": {"status": "source_verified"},
        },
    }
    inventory_path = tmp_path / "inventory.json"
    preflight_path = tmp_path / "preflight.json"
    preflight_path.write_text(json.dumps(preflight), encoding="utf-8")
    preflight_sha256 = hashlib.sha256(preflight_path.read_bytes()).hexdigest()
    plan["source_schema"]["preflight_sha256"] = preflight_sha256
    inventory["runtime_binding"] = {
        "status": "preflight_bound",
        "preflight_path": str(preflight_path),
        "preflight_sha256": preflight_sha256,
    }
    inventory_path.write_text(json.dumps(inventory), encoding="utf-8")
    plan_path = tmp_path / "topic-plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    output_path = tmp_path / "runtime-snapshot.json"

    result = PublicRuntimeNormalizeModule().safe_run(
        capture_path=str(inventory_path),
        topic_plan_path=str(plan_path),
        preflight_path=str(preflight_path),
        object_association_mode="auto",
        output=str(output_path),
    )

    assert result.ok is True
    assert result.data["status"] == "partial"
    assert result.data["snapshots"] == []
    assert len(result.data["unbound_objects"]) == 1
    row = result.data["unbound_objects"][0]
    assert row["association_status"] == "unbound"
    assert row["radar_id"] == 2
    assert row["frame_id"] is None
    assert row["fields"]["objID"] == 44
    assert row["fields"]["distY"] == -1.25
    assert row["fields"]["source_ref"]["field_path"] == "arbe_msgs/wfObjectMsg.ObjectsBuffer"
    metadata = result.data["capture_metadata"]
    assert metadata["inventory_sha256"] == hashlib.sha256(inventory_path.read_bytes()).hexdigest()
    assert metadata["observed_sample_count"] == 1
    assert metadata["identity_binding"]["status"] == "not_bound"
    assert "source_snapshot_hash" in metadata["identity_binding"]["required_before_runtime_evidence_consumption"]
    assert metadata["topic_plan_binding_status"] == "bound"
    assert metadata["association_policy"]["cross_topic_frame_association"] == "not_asserted"
    assert result.data["association_policy"]["object_association_mode"] == "publication_order"
    assert result.data["association_policy"]["time_neighbour_matching"] is False
    assert "objectlist_rows_missing_publication_sequence" in result.data["diagnostics"]
    assert output_path.exists()


def test_public_runtime_does_not_parse_truncated_ros_inventory_sample(tmp_path: Path):
    inventory = {
        "schema_version": "ros-topic-inventory.v1",
        "status": "ready",
        "server": {},
        "topics": [
            {
                "topic": "/wf/objectlist_2",
                "type": "arbe_msgs/wfObjectMsg",
                "sample": {
                    "status": "observed",
                    "message_observed": True,
                    "stdout": "ObjectsBuffer:\\n- ID: 0\\n",
                    "stdout_sha256": "sample-hash",
                    "stdout_char_count": 20,
                    "stdout_truncated": True,
                },
                "message_schema": {"status": "ready", "message_type": "arbe_msgs/wfObjectMsg"},
            }
        ],
    }
    capture_path = tmp_path / "truncated-inventory.json"
    capture_path.write_text(json.dumps(inventory), encoding="utf-8")
    result = PublicRuntimeNormalizeModule().safe_run(capture_path=str(capture_path))
    assert result.ok is True
    assert result.data["status"] == "partial"
    assert result.data["unbound_objects"] == []
    assert "topic_sample_truncated:/wf/objectlist_2" in result.data["diagnostics"]
    assert result.data["capture_metadata"]["observed_sample_count"] == 1


def test_public_runtime_does_not_overwrite_ros_inventory_input(tmp_path: Path):
    capture_path = tmp_path / "inventory.json"
    original = json.dumps({
        "schema_version": "ros-topic-inventory.v1",
        "status": "ready",
        "server": {},
        "topics": [],
    })
    capture_path.write_text(original, encoding="utf-8")
    result = PublicRuntimeNormalizeModule().safe_run(
        capture_path=str(capture_path), output=str(capture_path)
    )
    assert result.ok is False
    assert "output_must_not_overwrite_input_artifact" in result.message
    assert capture_path.read_text(encoding="utf-8") == original


def test_public_runtime_does_not_project_raw_can_warning_as_algorithm_warning():
    sample_text = "data:\n- 1\n- 7\n"
    inventory = {
        "schema_version": "ros-topic-inventory.v1",
        "status": "ready",
        "topics": [
            {
                "topic": "/wf/raw_can_warning_2",
                "type": "std_msgs/Int32MultiArray",
                "sample": {
                    "status": "observed",
                    "message_observed": True,
                    "stdout": sample_text,
                    "stdout_sha256": hashlib.sha256(sample_text.encode("utf-8")).hexdigest(),
                    "stdout_char_count": len(sample_text),
                    "stdout_truncated": False,
                },
            }
        ],
    }
    plan = {
        "schema_version": "public-topic-plan.v1",
        "channels": [
            {
                "channel_id": "raw_can_warning",
                "topic": "/wf/raw_can_warning_2",
                "source_kind": "ros_can_decoder",
                "frame_key": "not_in_message",
            }
        ],
    }
    capture = runtime_capture_from_topic_inventory(inventory, topic_plan=plan)
    assert capture["warning_rows"] == []
    assert capture["radar_info_rows"] == []
    assert "topic_sample_role_not_resolved:/wf/raw_can_warning_2" in capture["diagnostics"]


def test_public_runtime_ignores_topic_plan_when_preflight_identity_conflicts():
    sample_text = "data:\n- 2\n- 47877\n- 1\n"
    inventory = {
        "schema_version": "ros-topic-inventory.v1",
        "status": "ready",
        "server": {"host": "10.0.0.2", "user": "tester", "port": 22, "transport": "ssh"},
        "topics": [
            {
                "topic": "/corner_radar/warning_status_with_frame_2",
                "type": "std_msgs/Int32MultiArray",
                "sample": {
                    "status": "observed",
                    "message_observed": True,
                    "stdout": sample_text,
                    "stdout_sha256": hashlib.sha256(sample_text.encode("utf-8")).hexdigest(),
                    "stdout_char_count": len(sample_text),
                    "stdout_truncated": False,
                },
            }
        ],
    }
    workspace = {"arbe_root": "/opt/arbe", "algo_source": {"head": "abc"}}
    plan = {
        "schema_version": "public-topic-plan.v1",
        "status": "ready",
        "source_schema": {
            "preflight_server": {"host": "10.0.0.1", "user": "tester", "port": 22, "transport": "ssh"},
            "preflight_workspace": workspace,
            "preflight_sha256": "current-preflight-sha",
        },
        "channels": [
            {
                "channel_id": "algorithm_warning_with_frame_2",
                "topic": "/corner_radar/warning_status_with_frame_2",
                "source_kind": "ros_algorithm_warning",
                "frame_key": "data[1]",
            }
        ],
    }
    preflight = {
        "server": {"host": "10.0.0.2", "user": "tester", "port": 22, "transport": "ssh"},
        "workspace": workspace,
    }
    inventory["runtime_binding"] = {
        "status": "preflight_bound",
        "preflight_sha256": "current-preflight-sha",
    }
    capture = runtime_capture_from_topic_inventory(
        inventory,
        topic_plan=plan,
        preflight=preflight,
        preflight_sha256="current-preflight-sha",
    )
    assert capture["warning_rows"] == []
    assert capture["capture_metadata"]["topic_plan_binding_status"] == "identity_conflict"
    assert "topic_plan_inventory_preflight_identity_conflict" in capture["diagnostics"]
    assert "topic_sample_role_not_resolved:/corner_radar/warning_status_with_frame_2" in capture["diagnostics"]
