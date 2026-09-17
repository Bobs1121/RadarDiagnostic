from __future__ import annotations

import json
import hashlib
import shutil
from pathlib import Path

from jsonschema import Draft202012Validator

from ai.modules import MODULE_REGISTRY
from ai.modules.point_cloud import PointCloudAnalyzeModule, _bounded_code_context
from ai.modules.point_cloud_batch import PointCloudBatchModule
from ai.modules.point_cloud_validate import PointCloudValidateModule
from ai.modules.point_cloud_read import PointCloudReadModule
from ai.modules.execution_binding import ExecutionBindingModule
from engines.arbe.execution_binding import derive_execution_identity, verify_execution_binding
from ai.modules.point_cloud_plan import PointCloudPlanModule
from engines.point_cloud_replay import (
    build_perception_input_contract,
    build_perception_lineage,
    build_point_cloud_replay_plan,
    build_perception_stage_map,
    build_perception_run_evidence,
    build_perception_comparison,
    build_stage_coverage,
    audit_perception_capture,
    build_perception_scene,
    build_perception_timeline,
    build_perception_warmup_analysis,
    build_perception_injection_audit,
    build_perception_hypothesis_set,
    build_perception_capability_manifest,
    build_perception_code_flow,
    build_perception_validation,
    audit_runtime_workspace_alignment,
    audit_public_perception_source_contract,
    bind_public_perception_capture,
    audit_perception_artifact,
    load_perception_artifact,
    register_perception_artifact_adapter,
    PERCEPTION_ARTIFACT_ADAPTERS,
)


def _preflight(hilmodel: str = "0") -> dict:
    return {
        "schema_version": "arbe-preflight.v1",
        "build": {"macros": {"HILMODEL": hilmodel, "BUILDMODEL": "2", "PF_BUILD_FUNTEST_SGU_INJECTION": "0"}, "binary_fingerprint": "bin-sha"},
        "workspace": {"outer": {"head": "outer-sha"}, "algo_source": {"head": "algo-sha"}},
        "configuration": {"resolved": {"coem_name": "TEST"}},
        "runtime": {"ros_master_uri": "http://localhost:11311", "processes": [{"pid": 1}]},
    }


def _ready_input_contract(data: str = "data-sha") -> dict:
    return {
        "schema_version": "perception-input-contract.v1",
        "status": "ready",
        "point_count": 1,
        "data_fingerprint": data,
        "layout_status": "verified",
        "target_usage": {"status": "observed", "injection_detected": False},
    }


def test_point_cloud_plan_blocks_target_injection_build():
    plan = build_point_cloud_replay_plan(
        remote_bag_path="/data/case.bag",
        point_cloud_topic="/radar/points",
        preflight=_preflight("2"),
        source_context={"data_fingerprint": "data-sha"},
    )
    assert plan["status"] == "blocked"
    assert any("hilmodel" in item for item in plan["diagnostics"])
    assert plan["gates"][0]["status"] == "blocked"


def test_point_cloud_plan_is_ready_only_with_hilmodel_zero_and_identity():
    plan = build_point_cloud_replay_plan(
        remote_bag_path="/data/case.bag",
        point_cloud_topic="/radar/points",
        output_topics=["/perception/objects"],
        server_host="server",
        preflight=_preflight("0"),
        source_context={"data_fingerprint": "data-sha", "source_context_id": "source-sha"},
        warmup_frames=175,
        duration_sec=12.0,
        input_contract=_ready_input_contract(),
    )
    assert plan["status"] == "ready"
    assert plan["strategy"]["warmup_frames_requested"] == 175
    assert plan["plan_hash"]
    assert plan["execution_plan"]["strategy"] == "point_cloud"
    assert plan["execution_plan"]["input_topics"] == ["/radar/points"]


def test_point_cloud_plan_requires_auditable_input_and_rejects_injection():
    blocked = build_point_cloud_replay_plan(
        remote_bag_path="/data/case.bag",
        point_cloud_topic="/radar/points",
        preflight=_preflight("0"),
        source_context={"data_fingerprint": "data-sha", "source_context_id": "source-sha"},
        input_contract={"schema_version": "perception-input-contract.v1", "status": "partial", "target_usage": {"status": "not_available"}},
    )
    assert blocked["status"] == "blocked"
    injected = build_point_cloud_replay_plan(
        remote_bag_path="/data/case.bag",
        point_cloud_topic="/radar/points",
        preflight=_preflight("0"),
        source_context={"data_fingerprint": "data-sha", "source_context_id": "source-sha"},
        input_contract={"schema_version": "perception-input-contract.v1", "status": "ready", "target_usage": {"injection_detected": True}},
    )
    assert injected["status"] == "blocked"
    assert "recorded_target_injection_detected" in injected["diagnostics"]


def test_point_cloud_plan_execution_profile_binds_to_sim_verify_plan():
    preflight = _preflight("0")
    source = {"data_fingerprint": "data-sha", "source_context_id": "source-sha"}
    plan = build_point_cloud_replay_plan(
        remote_bag_path="/data/case.bag",
        remote_capture_base="/tmp/pc/run",
        point_cloud_topic="/radar/points",
        output_topics=["/perception/objects"],
        server_host="server",
        preflight=preflight,
        source_context=source,
        duration_sec=12.0,
        input_contract=_ready_input_contract(),
    )
    assert plan["status"] == "ready"
    binding = ExecutionBindingModule().safe_run(
        plan=plan,
        preflight=preflight,
        source_context=source,
        approved=True,
        approval_id="pc-approval",
        run_id="pc-attempt-1",
    )
    assert binding.data["status"] == "approved"
    identity, _ = derive_execution_identity(preflight=preflight, source_context=source)
    check = verify_execution_binding(
        binding.data,
        current_identity=identity,
        approved=True,
        plan=plan["execution_plan"],
    )
    assert check["status"] == "verified"


def test_point_cloud_plan_blocks_runtime_process_from_different_workspace():
    preflight = _preflight("0")
    preflight["workspace"]["arbe_root"] = "/home/hoz2wx/CR60LIGHT/cr60_light_arbe"
    preflight["runtime"]["processes"] = [{"pid": 77, "radar_id": 2, "command": "/home/hoz2wx/CR60LIGHT/cr60_light_arbe_0909int/devel/lib/arbe_visualization_engine"}]
    plan = build_point_cloud_replay_plan(
        remote_bag_path="/data/case.bag",
        point_cloud_topic="/radar/points",
        preflight=preflight,
        source_context={"data_fingerprint": "data", "source_context_id": "source"},
    )
    assert plan["status"] == "blocked"
    assert "runtime_process_workspace_mismatch" in plan["diagnostics"]
    assert plan["runtime_binding"]["status"] == "conflict"


def test_runtime_alignment_does_not_accept_workspace_text_in_an_argument():
    result = audit_runtime_workspace_alignment({
        "workspace": {"arbe_root": "/home/target"},
        "runtime": {"processes": [{"pid": 7, "command": "/usr/bin/arbe_visualization_engine --workspace /home/target"}]},
    })
    assert result["status"] == "conflict"
    assert "runtime_process_workspace_mismatch" in result["diagnostics"]


def test_point_cloud_plan_blocks_missing_contract_and_short_warmup_window():
    plan = build_point_cloud_replay_plan(
        server_host="server",
        remote_bag_path="/data/case.bag",
        point_cloud_topic="/radar/points",
        output_topics=["/perception/objects"],
        preflight=_preflight("0"),
        source_context={"data_fingerprint": "data-sha", "source_context_id": "source-sha"},
        duration_sec=4.0,
    )
    assert plan["status"] == "blocked"
    assert "point_cloud_input_contract_missing" in plan["diagnostics"]
    assert any(item.startswith("point_cloud_replay_window_short_for_warmup") for item in plan["diagnostics"])


def test_point_cloud_plan_blocks_conflicting_live_source_snapshot():
    preflight = _preflight("0")
    preflight["workspace"]["outer"]["content_fingerprint"] = "outer-live"
    preflight["workspace"]["algo_source"]["content_fingerprint"] = "algo-live"
    plan = build_point_cloud_replay_plan(
        server_host="server",
        remote_bag_path="/data/case.bag",
        point_cloud_topic="/radar/points",
        output_topics=["/perception/objects"],
        preflight=preflight,
        source_context={"data_fingerprint": "data", "source_context_id": "stale-source"},
        input_contract={"status": "ready", "point_count": 1, "target_usage": {"status": "observed", "injection_detected": False}},
        duration_sec=12.0,
    )
    assert plan["status"] == "blocked"
    assert "source_context_id:explicit_vs_live_preflight" in plan["diagnostics"]


def test_point_cloud_plan_consumes_ros_topic_inventory_gate():
    preflight = _preflight("0")
    inventory = {"schema_version": "ros-topic-inventory.v1", "status": "ready", "topics": [{"topic": "/radar/points", "status": "ready", "type": "sensor_msgs/PointCloud", "publisher_count": 1, "subscriber_count": 1}]}
    ready = build_point_cloud_replay_plan(
        remote_bag_path="/data/case.bag",
        point_cloud_topic="/radar/points",
        preflight=preflight,
        source_context={"data_fingerprint": "data", "source_context_id": "source"},
        topic_inventory=inventory,
    )
    assert next(g for g in ready["gates"] if g["id"] == "ros_input_topic_contract")["status"] == "passed"
    partial_inventory = {"status": "ready", "topics": [{"topic": "/radar/points", "status": "ready", "type": "sensor_msgs/PointCloud", "publisher_count": 1, "subscriber_count": 1, "message_observable": False}]}
    partial = build_point_cloud_replay_plan(
        remote_bag_path="/data/case.bag",
        point_cloud_topic="/radar/points",
        preflight=preflight,
        source_context={"data_fingerprint": "data", "source_context_id": "source"},
        topic_inventory=partial_inventory,
    )
    assert next(g for g in partial["gates"] if g["id"] == "ros_input_topic_contract")["status"] == "partial"
    missing = build_point_cloud_replay_plan(
        remote_bag_path="/data/case.bag",
        point_cloud_topic="/radar/points",
        preflight=preflight,
        source_context={"data_fingerprint": "data", "source_context_id": "source"},
        topic_inventory={"status": "ready", "topics": [{"topic": "/other", "status": "ready"}]},
    )
    assert missing["status"] == "blocked"
    assert "point_cloud_ros_input_topic_not_observed" in missing["diagnostics"]


def test_input_contract_preserves_missing_fields_and_aliases():
    contract = build_perception_input_contract(
        [{"frameID": 10, "radar_id": 2, "dist": 5.0, "ang": -2.0, "vel": 1.2, "power": 9.0}],
        source_context={"data_fingerprint": "data-sha"},
    )
    assert contract["status"] == "ready"
    assert contract["point_count"] == 1
    assert contract["points"][0]["range"] == 5.0
    assert contract["points"][0]["doppler"] == 1.2
    assert contract["field_counts"]["snr"] == 0


def test_point_cloud_analysis_preserves_capture_source_context_conflicts(tmp_path: Path):
    result = PointCloudAnalyzeModule().safe_run(
        capture={
            "point_rows": [{"range": 1.0, "azimuth": 0.1, "doppler": 0.2, "radar_id": 2}],
            "source_context": {"data_fingerprint": "data", "source_context_id": "capture-source"},
        },
        source_context={
            "data_fingerprint": "data",
            "source_context_id": "analysis-source",
            "binary_fingerprint": "binary",
            "config_fingerprint": "config",
            "session_id": "session",
        },
        output_dir=str(tmp_path),
    )

    assert result.ok
    contract = result.data["analysis"]["input_contract"]
    assert contract["status"] == "partial"
    assert contract["source_context_binding"]["status"] == "conflict"
    assert "source_context_id" in contract["source_context_binding"]["conflicts"]
    assert "source_context_identity_conflict" in contract["diagnostics"]
    assert result.data["analysis"]["capability_manifest"]["freshness"]["status"] == "conflict"
    assert result.data["analysis"]["status"] == "partial"
    report_html = (tmp_path / "perception-report.html").read_text(encoding="utf-8")
    assert "source_context_binding" in report_html
    assert "identity_conflict" in report_html
    assert "layout_binding" in report_html


def test_raw_lgu_layout_is_partial_until_recording_version_is_bound():
    source_hash = "source-snapshot"
    recording_hash = "a" * 64
    profile = {
        "name": "arbe_PERInfoOutStruct_debug_tail_v3",
        "version": "v3",
        "fixed_prefix_size": 728,
        "dot_struct_size": 16,
        "dot_struct_format": "<hhhhbbbBBBBB",
        "source_snapshot_hash": source_hash,
        "source_contract_ref": "perception_public_api.h@source-snapshot",
        "verified": True,
    }
    source_context = {
        "data_fingerprint": recording_hash,
        "source_context_id": source_hash,
        "layout_profile": profile,
    }
    contract = build_perception_input_contract(
        [{
            "range": 1.0,
            "azimuth": 2.0,
            "doppler": 3.0,
            "source": "PERInfoOutStruct.dotTrans",
            "status": "observed_with_layout_warning",
            "source_ref": {"raw_token": "PERInfoOutStruct.dotTrans"},
        }],
        source_context=source_context,
        message_schema={
            "type": "arbe_msgs/wfAutosarData",
            "payload": "PERInfoOutStruct.dotTrans",
            "layout_profile": profile,
        },
        target_usage={"status": "observed", "injection_detected": False},
        artifact_audit={"status": "observed", "sha256": recording_hash},
    )

    assert contract["status"] == "partial"
    assert contract["layout_status"] == "recording_version_unbound"
    assert contract["layout_binding"]["source_layout_status"] == "verified"
    assert contract["layout_binding"]["data_binding_status"] == "aligned"
    assert contract["points"][0]["status"] == "partial"
    assert "input_recording_version_unbound" in contract["diagnostics"]

    plan = build_point_cloud_replay_plan(
        server_host="server",
        remote_bag_path="/data/case.bag",
        point_cloud_topic="/radar/lgu",
        output_topics=["/perception/objects"],
        remote_capture_base="/tmp/pc/run",
        duration_sec=12.0,
        preflight=_preflight("0"),
        source_context={**source_context, "binary_fingerprint": "bin", "config_fingerprint": "config", "session_id": "session"},
        input_contract=contract,
    )
    layout_gate = next(item for item in plan["gates"] if item["id"] == "point_cloud_input_layout")
    assert layout_gate["status"] == "blocked"
    assert plan["status"] == "blocked"


def test_raw_lgu_layout_data_hash_conflict_blocks_execution_even_with_source_profile():
    profile = {
        "name": "arbe_PERInfoOutStruct_debug_tail_v3",
        "version": "v3",
        "fixed_prefix_size": 728,
        "dot_struct_size": 16,
        "source_snapshot_hash": "source-snapshot",
        "source_contract_ref": "perception_public_api.h@source-snapshot",
        "verified": True,
    }
    contract = build_perception_input_contract(
        [{"range": 1.0, "azimuth": 2.0, "doppler": 3.0, "source": "PERInfoOutStruct.dotTrans"}],
        source_context={"data_fingerprint": "context-bag-hash", "source_context_id": "source-snapshot", "layout_profile": profile},
        message_schema={"type": "arbe_msgs/wfAutosarData", "payload": "PERInfoOutStruct.dotTrans", "layout_profile": profile},
        artifact_audit={"status": "observed", "sha256": "different-artifact-hash"},
    )
    assert contract["status"] == "partial"
    assert contract["layout_status"] == "conflict"
    assert contract["layout_binding"]["data_binding_status"] == "conflict"
    assert "input_layout_identity_conflict" in contract["diagnostics"]


def test_raw_lgu_layout_verified_only_with_recording_compatibility_evidence(tmp_path: Path):
    source_hash = "source-snapshot"
    recording_hash = "a" * 64
    evidence_path = tmp_path / "recording-layout-review.json"
    evidence_path.write_bytes(b"reviewed layout compatibility fixture")
    evidence_sha = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    profile = {
        "name": "arbe_PERInfoOutStruct_debug_tail_v3",
        "version": "v3",
        "fixed_prefix_size": 728,
        "dot_struct_size": 16,
        "source_snapshot_hash": source_hash,
        "source_contract_ref": "perception_public_api.h@source-snapshot",
        "verified": True,
        "recording_compatibility": {
            "status": "verified",
            "source_snapshot_hash": source_hash,
            "recording_fingerprint": recording_hash,
            "recording_version": "producer-build-v3",
            "compatibility_evidence_ref": str(evidence_path.resolve()),
            "compatibility_evidence_sha256": evidence_sha,
        },
    }
    contract = build_perception_input_contract(
        [{"range": 1.0, "azimuth": 2.0, "doppler": 3.0, "source": "PERInfoOutStruct.dotTrans", "status": "observed"}],
        source_context={"data_fingerprint": recording_hash, "source_context_id": source_hash, "layout_profile": profile},
        message_schema={"type": "arbe_msgs/wfAutosarData", "payload": "PERInfoOutStruct.dotTrans", "layout_profile": profile},
        target_usage={"status": "observed", "injection_detected": False},
        artifact_audit={"status": "observed", "sha256": recording_hash},
    )
    assert contract["status"] == "ready"
    assert contract["layout_status"] == "verified"
    assert contract["layout_binding"]["recording_version"] == "producer-build-v3"


def test_raw_lgu_layout_requires_artifact_and_source_data_fingerprint_to_match():
    source_hash = "source-snapshot"
    recording_hash = "a" * 64
    profile = {
        "name": "arbe_PERInfoOutStruct_debug_tail_v3",
        "version": "v3",
        "fixed_prefix_size": 728,
        "dot_struct_size": 16,
        "source_snapshot_hash": source_hash,
        "source_contract_ref": "perception_public_api.h@source-snapshot",
        "verified": True,
        "recording_compatibility": {
            "status": "verified",
            "source_snapshot_hash": source_hash,
            "recording_fingerprint": recording_hash,
            "recording_version": "producer-build-v3",
            "compatibility_evidence_ref": "recording-layout-review.json",
            "compatibility_evidence_sha256": "b" * 64,
        },
    }
    contract = build_perception_input_contract(
        [{"range": 1.0, "azimuth": 2.0, "doppler": 3.0, "source": "PERInfoOutStruct.dotTrans", "status": "observed"}],
        source_context={"data_fingerprint": "another-bag-hash", "source_context_id": source_hash, "layout_profile": profile},
        message_schema={"type": "arbe_msgs/wfAutosarData", "payload": "PERInfoOutStruct.dotTrans", "layout_profile": profile},
        target_usage={"status": "observed", "injection_detected": False},
        artifact_audit={"status": "observed", "sha256": recording_hash},
    )

    assert contract["status"] == "partial"
    assert contract["layout_status"] == "conflict"
    assert contract["layout_binding"]["data_binding_status"] == "conflict"
    assert "input_layout_identity_conflict" in contract["diagnostics"]


def test_input_contract_audits_radars_targets_and_non_finite_values():
    contract = build_perception_input_contract(
        [
            {"frameID": 10, "radar_id": 1, "dist": 5.0, "ang": float("nan"), "vel": 1.2},
            {"frameID": 11, "radar_id": 2, "dist": 6.0, "ang": 0.2, "vel": 1.3},
        ],
        message_schema={"type": "dotTrans", "fields": ["frameID", "dist"]},
        target_rows=[{"frame_id": 10, "object_id": 44}],
        conversion={"status": "observed", "source_ref": "adapter.c:10"},
        source_context={"data_fingerprint": "data-sha"},
    )
    assert contract["status"] == "partial"
    assert len(contract["radar_summary"]) == 2
    assert contract["target_usage"]["status"] == "observed"
    assert contract["points"][0]["azimuth"] is None
    assert contract["points"][0]["field_status"]["azimuth"]["status"] == "non_finite"
    json.dumps(contract, allow_nan=False)


def test_capture_audit_uses_payload_shape_and_rejects_target_only():
    target_only = audit_perception_capture({"object_rows": [{"objID": 44}], "topics": ["/looks-like-points"]})
    assert target_only["status"] == "blocked"
    assert target_only["topic_names_used_for_classification"] is False
    assert "target_or_object_rows_only_not_point_cloud_input" in target_only["diagnostics"]
    target_contract = build_perception_input_contract(
        [], target_rows=[{"objID": 44}], payload_audit=target_only,
    )
    assert target_contract["status"] == "blocked"
    assert target_contract["input_boundary"] == "target_only"
    points = audit_perception_capture({"point_rows": [{"frame_id": 1}], "object_rows": [{"objID": 44}]})
    assert points["status"] == "ready"
    assert points["payloads"]["point_cloud"]["source_key"] == "point_rows"
    Draft202012Validator(json.loads((Path(__file__).resolve().parents[1] / "contracts" / "perception-input-audit.v1.schema.json").read_text(encoding="utf-8"))).validate(points)
    empty_frame = audit_perception_capture({
        "point_rows": [],
        "stage_evidence": [{"stage": "point_cloud", "status": "completed", "runtime_proof": "observed", "source_ref": {"topic": "/wf/corner_radar/rviz/pointcloud_2", "message_seq": 12}}],
    })
    assert empty_frame["status"] == "blocked"
    assert empty_frame["payloads"]["point_cloud"] == {"source_key": "point_rows", "row_count": 0, "status": "observed_empty", "message_count": 1}
    Draft202012Validator(json.loads((Path(__file__).resolve().parents[1] / "contracts" / "perception-input-audit.v1.schema.json").read_text(encoding="utf-8"))).validate(empty_frame)
    empty_contract = build_perception_input_contract([], payload_audit=empty_frame)
    assert empty_contract["input_boundary"] == "empty_public_pointcloud_observation"


def test_target_only_capture_blocks_full_replay_but_keeps_static_source_analysis(tmp_path: Path):
    stage_map = {
        "schema_version": "perception-stage-map.v1",
        "stages": {
            "cluster": [{"function": "ObjCluster", "source_ref": {"path": "src/cluster.c", "line": 818, "token": "ObjCluster"}}],
            "track": [{"function": "ObjTrack", "source_ref": {"path": "src/track.c", "line": 16095, "token": "ObjTrack"}}],
            "adas_func": [{"function": "AdasFunc", "source_ref": {"path": "coem/BYD_SC6H/adasFunc.c", "line": 10730, "token": "AdasFunc"}}],
        },
    }
    result = PointCloudAnalyzeModule().safe_run(
        capture={"object_rows": [{"ID": 44, "objID": 9, "topic": "/wf/objectlist_2"}], "message_schema": {"type": "arbe_msgs/wfObjectMsg"}},
        stage_map=stage_map,
        code_context={"schema_version": "code-context.v1", "functions": [{"name": "ObjTrack"}, {"name": "AdasFunc"}], "calls": {"ObjTrack": ["TrackMatchAndFilt", "TrackCreate", "TrackManage"]}},
        condition_trace={"schema_version": "condition-trace.v1", "status": "partial", "conditions": [{"condition_id": "c1", "function": "AdasFunc", "expression": "warning == 1", "source_ref": {"path": "coem/BYD_SC6H/adasFunc.c", "line": 10730}, "evaluation": {"status": "not_evaluable", "reason": "runtime_warning_missing"}, "missing_tokens": ["warning"]}]},
        output_dir=str(tmp_path),
    )
    assert result.ok
    assert result.data["status"] == "blocked"
    analysis = result.data["analysis"]
    assert analysis["input_contract"]["input_boundary"] == "target_only"
    assert analysis["input_contract"]["payload_audit"]["status"] == "blocked"
    assert "target_or_object_rows_only_not_point_cloud_input" in analysis["input_contract"]["payload_audit"]["diagnostics"]
    bindings = analysis["code_flow"]["stage_bindings"]
    track_binding = next(row for row in bindings if row["stage"] == "track")
    adas_binding = next(row for row in bindings if row["stage"] == "adas_func")
    assert track_binding["status"] == "source_candidate"
    assert track_binding["source_candidates"][0]["function"] == "ObjTrack"
    assert adas_binding["source_candidates"][0]["function"] == "AdasFunc"
    assert analysis["code_flow"]["condition_bindings"][0]["evaluation_status"] == "not_evaluable"
    html_text = (tmp_path / "perception-report.html").read_text(encoding="utf-8")
    assert "源码流程与阶段映射" in html_text
    assert "ObjTrack" in html_text and "AdasFunc" in html_text
    assert "target_or_object_rows_only_not_point_cloud_input" in html_text


def test_lineage_never_guesses_edges_from_time_or_index():
    missing = build_perception_lineage(
        points=[{"point_key": "p1", "frame_id": 10}],
        tracks=[{"track_id": "t1", "frame_id": 10}],
    )
    assert missing["status"] == "not_available"
    assert missing["edge_count"] == 0
    explicit = build_perception_lineage(
        edges=[{"relation_kind": "point_supports_cluster", "from": "p1", "to": "c1", "status": "observed"}],
        points=[{"point_key": "p1"}],
        clusters=[{"cluster_id": "c1"}],
    )
    assert explicit["status"] == "observed"
    assert explicit["edge_count"] == 1
    invalid = build_perception_lineage(
        edges=[{"relation_kind": "point_supports_cluster", "from": "missing", "to": "c1"}],
        points=[{"point_key": "p1"}],
        clusters=[{"cluster_id": "c1"}],
    )
    assert invalid["status"] == "not_available"
    assert invalid["edge_count"] == 0
    assert len(invalid["invalid_edges"]) == 1
    reused = build_perception_lineage(
        edges=[{"relation_kind": "track_matches_previous", "from": "t1", "to": "t1", "status": "derived"}],
        tracks=[{"track_id": "t1", "frame_id": 10}, {"track_id": "t1", "frame_id": 11}],
    )
    assert "track_id_reused_without_identity_basis:t1" in reused["identity_warnings"]


def test_public_perception_binding_uses_source_order_and_explicit_uid_fields(tmp_path: Path):
    source_root = tmp_path / "algo" / "adas" / "symmetry" / "perception"
    (source_root / "src").mkdir(parents=True)
    vis_path = tmp_path / "visualization_node.cpp"
    (source_root / "src" / "postProcess.c").write_text(
        "#if 0 == HILMODEL\nvoid f(){ DotPrePosTI(); EnvModelDetect(); DotFilter(); ObjCluster(); ObjTrack(); OutputTrkObj(); AdasFunc(); }\n#endif\n",
        encoding="utf-8",
    )
    (source_root / "src" / "cluster.c").write_text("dotInfo[pointIndex].clusterID = (int8_t)clusterID;\n", encoding="utf-8")
    (source_root / "src" / "objAttribCal.c").write_text(
        "pDctnPts[i].objectUID = clusterInfo->clusterData[clusterID].objectUID;\n", encoding="utf-8"
    )
    (source_root / "src" / "track.c").write_text(
        "clusterInfo->clusterData[i].objectUID = pTemp->objUnqID;\n", encoding="utf-8"
    )
    vis_path.write_text(
        "void corner_radar_post_process_data_callback(Msg* msg) {\n"
        "  if (is_wf_postprocess_enable) {\n"
        "    PostProcessMainTI();\n"
        "    if (is_wf_tracdisp_enable) { wf_object_display_handler(); }\n"
        "    cloud_corner.points[i].cluster_id = algo_dotInfoC[i].clusterID;\n"
        "    cloud_corner.points[i].track_id = algo_dotInfoC[i].objectUID;\n"
        "    tar.ID = algo_objInfo.trcOutData[i].objUnqID;\n"
        "  }\n"
        "  corner_radar_pcl_pub.publish(output);\n"
        "}\n"
        "void wf_object_display_handler(){ wf_objectlist_pub.publish(ObjectListMsg_global); }\n",
        encoding="utf-8",
    )
    contract = audit_public_perception_source_contract(
        source_root=source_root,
        visualization_source_path=vis_path,
        build_macros={"HILMODEL": "0", "BUILDMODEL": "2"},
    )
    assert contract["status"] == "source_verified"
    capture = {
        "stage_evidence": [
            {"stage": "track", "status": "completed", "runtime_proof": "observed", "source_ref": {"topic": "/wf/objectlist_2", "message_seq": 10}},
            {"stage": "point_cloud", "status": "completed", "runtime_proof": "observed", "source_ref": {"topic": "/wf/corner_radar/rviz/pointcloud_2", "message_seq": 11}},
        ],
        "object_rows": [{"ID": 77, "objID": 9, "object_message_seq": 10, "radar_id": 2, "topic": "/wf/objectlist_2"}],
        "point_rows": [
            {"point_index": 0, "cluster_id": 2, "track_id": 77.0, "radar_id": 2, "source_ref": {"topic": "/wf/corner_radar/rviz/pointcloud_2", "message_seq": 11}},
            {"point_index": 1, "cluster_id": 2, "track_id": 77.0, "radar_id": 2, "source_ref": {"topic": "/wf/corner_radar/rviz/pointcloud_2", "message_seq": 11}},
        ],
    }
    bound = bind_public_perception_capture(capture, source_contract=contract, capture_id="attempt-1")
    assert bound["callback_binding_summary"]["status"] == "derived"
    assert bound["callback_binding_summary"]["binding_count"] == 1
    assert "not algorithm frameID/counter or warmup frame count" in bound["callback_binding_summary"]["sequence_semantics"]
    assert bound["callback_binding_summary"]["algorithm_frame_counter_status"] == "not_available"
    assert bound["callback_binding_summary"]["warmup_frame_relation"] == "not_evaluable"
    assert any("must not be compared to requested warmup frames" in item for item in bound["limitations"])
    assert bound["track_population"] == {
        "status": "observed_subset",
        "scope": "public_objectlist_output_rows",
        "track_nodes_mirror_output_rows": True,
        "internal_candidate_track_population": "not_available",
        "internal_mature_track_population": "not_available",
        "cluster_supports_track_scope": "unique_cluster_track_pairs_where_point_track_uid_matches_captured_public_objectlist_id",
        "track_emits_output_scope": "one_unique_derived_edge_per_captured_public_objectlist_output_row",
        "unclustered_point_scope": "cluster_id_minus_one_has_no_cluster_node_or_point_support_edge; track_lifecycle_not_inferred",
        "source_topics": ["/wf/objectlist_2"],
        "identity_basis": "wfSObj.ID == objUnqID",
        "limitation": "track nodes mirror captured public objectlist output rows; this is not a complete internal candidate or mature tracker snapshot",
    }
    assert bound["relation_scopes"]["point_supports_cluster"] == {
        "population": "public_pointcloud_rows",
        "inclusion_condition": "cluster_id > 0",
        "basis": "PointCloud2.cluster_id <- algo_dotInfoC[i].clusterID",
        "limitation": "rows with cluster_id <= 0 have no edge in this public lineage; absence does not identify the algorithm stage that set the value",
    }
    assert len(bound["lineage_edges"]) == 5
    assert {row["relation_kind"] for row in bound["lineage_edges"]} == {
        "point_supports_cluster", "cluster_supports_track", "track_emits_output"
    }
    assert bound["track_rows"][0]["algorithm_track_id"] == 77
    assert bound["track_rows"][0]["population_scope"] == "public_objectlist_output_rows"
    assert bound["point_rows"][0]["frame_domain"] == "source_proven_public_callback_order"

    report_dir = tmp_path / "public-track-population-report"
    analyzed = PointCloudAnalyzeModule().safe_run(
        capture=bound,
        selected_frame=bound["callback_bindings"][0]["callback_key"],
        output_dir=str(report_dir),
    )
    assert analyzed.ok
    report = json.loads((report_dir / "perception-report.json").read_text(encoding="utf-8"))
    lineage = report["analysis"]["lineage"]
    assert lineage["track_population"]["scope"] == "public_objectlist_output_rows"
    assert lineage["relation_scopes"]["point_supports_cluster"]["inclusion_condition"] == "cluster_id > 0"
    assert lineage["track_population"]["internal_candidate_track_population"] == "not_available"
    assert lineage["node_counts"]["tracks"] == lineage["node_counts"]["outputs"] == 1
    assert lineage["relation_counts"]["cluster_supports_track"] == 1
    assert lineage["raw_relation_counts"]["cluster_supports_track"] == 2
    assert lineage["relation_summaries"]["cluster_supports_track"] == {
        "from_node_kind": "clusters",
        "to_node_kind": "tracks",
        "edge_row_count": 1,
        "unique_pair_count": 1,
        "unique_from_node_count": 1,
        "unique_to_node_count": 1,
    }
    assert report["validation"]["checks"]["track_population_scope"] is True
    assert report["validation"]["checks"]["relation_scopes"] is True
    callback_read = PointCloudReadModule().safe_run(
        report_path=str(report_dir / "perception-report.json"), section="lineage", limit=10,
    )
    assert callback_read.data["data"]["track_population"]["scope"] == "public_objectlist_output_rows"
    assert callback_read.data["data"]["relation_scopes"]["point_supports_cluster"]["inclusion_condition"] == "cluster_id > 0"
    assert callback_read.data["data"]["relation_counts"]["cluster_supports_track"] == 1
    assert callback_read.data["data"]["raw_relation_counts"]["cluster_supports_track"] == 2


def test_stage_coverage_preserves_multiframe_rows_and_truncation():
    coverage = build_stage_coverage([
        {"stage": "track", "run_id": "r", "attempt_id": "a", "frame_domain": "algo", "epoch": 1, "frame_id": 10, "status": "completed", "runtime_proof": "observed", "input_count": 3, "output_count": 1},
        {"stage": "track", "run_id": "r", "attempt_id": "a", "frame_domain": "algo", "epoch": 1, "frame_id": 11, "status": "partial", "input_count": 2, "output_count": 0, "truncated": True},
    ])
    row = next(item for item in coverage["stages"] if item["stage"] == "track")
    assert row["frame_count"] == 2
    assert row["input_count"] == 5
    assert row["output_count"] == 1
    assert row["truncated"] is True
    assert len(row["evidence_rows"]) == 2
    assert row["runtime_proof"] == "observed"


def test_scene_requires_explicit_frame_and_timeline_keeps_exact_frames():
    unavailable = build_perception_scene(points=[{"frame_id": 9, "range": 5.0, "azimuth": 0.0}])
    assert unavailable["status"] == "not_available"
    assert "selected_frame_missing" in unavailable["diagnostics"]
    scene = build_perception_scene(
        points=[{"frame_id": 9, "point_key": "p9", "range": 5.0, "azimuth": 0.0}, {"frame_id": 10, "point_key": "p10", "range": 7.0, "azimuth": 1.0}],
        tracks=[{"frame_id": 10, "track_id": "t10"}],
        selected_frame=10,
        angle_unit="rad",
        range_unit="m",
    )
    assert scene["status"] == "observed"
    assert scene["counts"]["points"] == 1
    assert scene["layers"]["points"][0]["coordinate_status"] == "derived"
    timeline = build_perception_timeline(
        stage_coverage={"stages": [{"stage": "track", "evidence_rows": [{"frame_key": "9", "status": "completed"}, {"frame_key": "10", "status": "completed"}]}]},
        tracks=[{"frame_id": 10, "track_id": "t10"}],
        selected_frame=10,
    )
    assert timeline["status"] == "observed"
    assert timeline["rows"][0]["frame_key"] == "10"
    assert timeline["rows"][0]["track_ids"] == ["t10"]


def test_timeline_reports_public_uid_recurrence_without_claiming_physical_identity():
    callback_bindings = [
        {"callback_key": "cap:radar2:callback:1-2", "radar_id": 2, "object_message_seq": 1, "pointcloud_message_seq": 2, "method": "source_proven_adjacent_publication_order"},
        {"callback_key": "cap:radar2:callback:3-4", "radar_id": 2, "object_message_seq": 3, "pointcloud_message_seq": 4, "method": "source_proven_adjacent_publication_order"},
        {"callback_key": "cap:radar2:callback:5-6", "radar_id": 2, "object_message_seq": 5, "pointcloud_message_seq": 6, "method": "source_proven_adjacent_publication_order"},
    ]
    timeline = build_perception_timeline(
        tracks=[
            {"frame_key": "cap:radar2:callback:1-2", "frame_domain": "source_proven_public_callback_order", "algorithm_track_id": 43, "population_scope": "public_objectlist_output_rows"},
            {"frame_key": "cap:radar2:callback:3-4", "frame_domain": "source_proven_public_callback_order", "algorithm_track_id": 43, "population_scope": "public_objectlist_output_rows"},
            {"frame_key": "cap:radar2:callback:1-2", "frame_domain": "source_proven_public_callback_order", "algorithm_track_id": 20_000_001, "population_scope": "public_objectlist_output_rows"},
            {"frame_key": "cap:radar2:callback:3-4", "frame_domain": "source_proven_public_callback_order", "algorithm_track_id": 20_000_001, "population_scope": "public_objectlist_output_rows"},
        ],
        selected_frame="cap:radar2:callback:3-4",
        callback_bindings=callback_bindings,
        callback_binding_summary={"status": "derived", "binding_count": 3, "point_message_count": 3, "object_message_count": 3, "diagnostics": []},
        track_population={"scope": "public_objectlist_output_rows", "identity_basis": "wfSObj.ID == objUnqID"},
    )
    assert timeline["uid_recurrence_status"] == "derived"
    assert timeline["uid_recurrence_scope"] == "public_objectlist_output_rows_adjacent_callbacks_same_capture_and_radar"
    assert {row["algorithm_track_id"] for row in timeline["public_uid_recurrences"]} == {43, 20_000_001}
    recurrence = next(row for row in timeline["public_uid_recurrences"] if row["algorithm_track_id"] == 43)
    assert recurrence["match_grade"] == "same_public_uid_adjacent_callback"
    assert "does not prove physical-object identity" in recurrence["limitation"]

    unavailable = build_perception_timeline(tracks=[{"frame_key": "cap:radar2:callback:3-4", "algorithm_track_id": 43}], selected_frame="cap:radar2:callback:3-4")
    assert unavailable["uid_recurrence_status"] == "not_available"
    assert unavailable["public_uid_recurrences"] == []


def test_point_cloud_report_projects_adjacent_public_uid_recurrence_to_html_and_read_tool(tmp_path: Path):
    callback_bindings = [
        {"callback_key": f"cap:radar2:callback:{seq}-{seq+1}", "radar_id": 2, "object_message_seq": seq, "pointcloud_message_seq": seq + 1, "method": "source_proven_adjacent_publication_order"}
        for seq in (1, 3, 5, 7)
    ]
    track_population = {
        "status": "observed_subset",
        "scope": "public_objectlist_output_rows",
        "track_nodes_mirror_output_rows": True,
        "internal_candidate_track_population": "not_available",
        "internal_mature_track_population": "not_available",
        "cluster_supports_track_scope": "unique_cluster_track_pairs_where_point_track_uid_matches_captured_public_objectlist_id",
        "track_emits_output_scope": "one_unique_derived_edge_per_captured_public_objectlist_output_row",
        "unclustered_point_scope": "cluster_id_minus_one_has_no_cluster_node_or_point_support_edge; track_lifecycle_not_inferred",
        "identity_basis": "wfSObj.ID == objUnqID",
        "limitation": "public objectlist output rows only; no internal tracker snapshot",
    }
    frames = [row["callback_key"] for row in callback_bindings]
    capture = {
        "selected_frame": frames[1],
        "frame_domain": "source_proven_public_callback_order",
        "epoch": "cap",
        "callback_bindings": callback_bindings,
        "callback_binding_summary": {
            "status": "derived", "binding_count": 4, "point_message_count": 4,
            "object_message_count": 4, "diagnostics": [],
        },
        "track_population": track_population,
        "track_rows": [
            {"track_key": f"{frames[index]}:track:43", "track_id": 43, "algorithm_track_id": 43, "frame_key": frames[index], "frame_domain": "source_proven_public_callback_order", "epoch": "cap", "radar_id": 2, "population_scope": "public_objectlist_output_rows", "identity_basis": "wfSObj.ID == objUnqID"}
            for index in (0, 1, 3)
        ],
        "output_rows": [
            {"output_key": f"{frames[index]}:output:43", "algorithm_track_id": 43, "frame_key": frames[index], "frame_domain": "source_proven_public_callback_order", "epoch": "cap", "radar_id": 2}
            for index in (0, 1, 3)
        ],
    }
    output_dir = tmp_path / "uid-recurrence-report"
    result = PointCloudAnalyzeModule().safe_run(capture=capture, selected_frame=frames[1], output_dir=str(output_dir))
    assert result.ok
    report_path = output_dir / "perception-report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    timeline = report["analysis"]["timeline"]
    assert timeline["uid_recurrence_status"] == "derived"
    assert len(timeline["public_uid_recurrences"]) == 1
    assert timeline["public_uid_recurrences"][0]["previous_frame_key"] == frames[0]
    assert timeline["public_uid_recurrences"][0]["current_frame_key"] == frames[1]
    assert timeline["public_uid_recurrences"][0]["algorithm_track_id"] == 43
    assert timeline["public_uid_recurrences"][0]["limitation"].startswith("same public UID recurrence only")
    assert "same_public_uid_adjacent_callback" in (output_dir / "perception-report.html").read_text(encoding="utf-8")

    query = PointCloudReadModule().safe_run(report_path=str(report_path), section="timeline")
    assert query.data["data"]["uid_recurrence_status"] == "derived"
    assert query.data["data"]["public_uid_recurrences"] == timeline["public_uid_recurrences"]
    wrong_frame = PointCloudReadModule().safe_run(report_path=str(report_path), section="timeline", callback_key=frames[3])
    assert wrong_frame.data["status"] == "partial"
    assert "timeline_not_available_for_requested_callback" in wrong_frame.data["diagnostics"]
    timeline_schema = json.loads((Path(__file__).resolve().parents[1] / "contracts" / "perception-timeline.v1.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(timeline_schema).validate(timeline)


def test_scene_retains_point_identity_and_uses_exact_cluster_ids_for_centroids():
    scene = build_perception_scene(
        points=[
            {"frame_key": "cb-1", "point_key": "p1", "x": 1.0, "y": 2.0, "cluster_id": 7, "track_id": 43, "radar_id": 2},
            {"frame_key": "cb-1", "point_key": "p2", "x": 3.0, "y": 4.0, "cluster_id": 7, "track_id": 43, "radar_id": 2},
            {"frame_key": "cb-1", "point_key": "p3", "x": 90.0, "y": 90.0, "cluster_id": 8, "track_id": 99, "radar_id": 2},
        ],
        clusters=[{"frame_key": "cb-1", "cluster_id": "cb-1:cluster:7", "algorithm_cluster_id": 7}],
        tracks=[{"frame_key": "cb-1", "track_key": "cb-1:track:43", "algorithm_track_id": 43}],
        outputs=[{"frame_key": "cb-1", "output_key": "cb-1:output:43", "algorithm_track_id": 43}],
        selected_frame="cb-1",
        frame_domain="source_proven_public_callback_order",
        coordinate_frame="image_radar",
    )
    assert scene["layers"]["points"][0]["coordinate_status"] == "observed"
    assert scene["layers"]["points"][0]["cluster_id"] == 7
    assert scene["layers"]["points"][0]["track_id"] == 43
    cluster = scene["layers"]["clusters"][0]
    assert cluster["coordinate_status"] == "derived"
    assert cluster["coordinate_basis"] == "mean_of_exact_point_cluster_id"
    assert cluster["support_point_count"] == 2
    assert (cluster["x"], cluster["y"]) == (2.0, 3.0)
    assert len(scene["layers"]["tracks"]) == len(scene["layers"]["outputs"]) == 1


def test_warmup_analysis_distinguishes_stable_and_sensitive_attempts():
    stable = build_perception_warmup_analysis([
        {"run_id": "r150", "attempt_id": "a1", "warmup_requested": 150, "warmup_completed": 150, "status": "completed", "output_signature": "sig"},
        {"run_id": "r200", "attempt_id": "a2", "warmup_requested": 200, "warmup_completed": 200, "status": "completed", "output_signature": "sig"},
    ])
    assert stable["status"] == "stable"
    assert stable["metrics"]["stable"] is True
    sensitive = build_perception_warmup_analysis([
        {"warmup_requested": 150, "warmup_completed": 150, "status": "completed", "output_signature": "sig-a"},
        {"warmup_requested": 200, "warmup_completed": 200, "status": "completed", "output_signature": "sig-b"},
    ])
    assert sensitive["status"] == "warmup_sensitive"
    assert "warmup_runs_missing" not in sensitive["diagnostics"]


def test_injection_audit_blocks_explicit_sgu_injection_macro():
    audit = build_perception_injection_audit(
        preflight={"build": {"macros": {"HILMODEL": "0", "PF_BUILD_FUNTEST_SGU_INJECTION": "1"}}},
        target_usage={"status": "observed", "injection_detected": True},
    )
    assert audit["status"] == "observed"
    assert audit["injection_enabled"] is True
    assert audit["gates"]["target_injection_absent"] == "blocked"
    Draft202012Validator(json.loads((Path(__file__).resolve().parents[1] / "contracts" / "perception-injection-audit.v1.schema.json").read_text(encoding="utf-8"))).validate(audit)


def test_hypothesis_set_is_candidate_only_and_limited_to_top_three():
    hypotheses = build_perception_hypothesis_set(
        [{"category": "filter", "statement": "candidate-1", "evidence_status": "partial"},
         {"category": "track", "statement": "candidate-2"},
         {"category": "config", "statement": "candidate-3"},
         {"category": "other", "statement": "candidate-4"}],
        [{"method": "replay", "question": "does changing the input conversion move the first divergence?"}],
    )
    assert len(hypotheses["hypotheses"]) == 3
    assert hypotheses["conclusion_level"] == "candidate_only"
    assert "hypothesis_list_truncated_to_top_3" in hypotheses["diagnostics"]
    Draft202012Validator(json.loads((Path(__file__).resolve().parents[1] / "contracts" / "perception-hypothesis-set.v1.schema.json").read_text(encoding="utf-8"))).validate(hypotheses)


def test_capability_manifest_exposes_unsupported_runtime_without_overclaiming():
    capability = build_perception_capability_manifest(
        input_contract={"schema_version": "perception-input-contract.v1", "status": "ready", "strategy": "point_cloud", "data_fingerprint": "data", "source_context_id": "source"},
        stage_coverage={"status": "partial", "stages": [{"stage": "track", "status": "source_candidate", "source_ref": {"path": "track.c"}, "runtime_proof": "not_available"}]},
        source_context={"data_fingerprint": "data", "source_context_id": "source"},
        replay_plan={"status": "ready"},
    )
    assert capability["status"] == "partial"
    assert "perception-runtime-stages" in {item["id"] for item in capability["unsupported"]}
    assert capability["freshness"]["status"] == "partial"
    Draft202012Validator(json.loads((Path(__file__).resolve().parents[1] / "contracts" / "perception-capability-manifest.v1.schema.json").read_text(encoding="utf-8"))).validate(capability)


def test_capability_manifest_does_not_treat_identity_strings_as_freshness_proof():
    identity = {
        "data_fingerprint": "data",
        "source_context_id": "source",
        "binary_fingerprint": "binary",
        "config_fingerprint": "config",
        "session_id": "session",
    }
    capability = build_perception_capability_manifest(
        input_contract={"status": "ready", "strategy": "point_cloud", "data_fingerprint": "data", "source_context_id": "source"},
        stage_coverage={"stages": [{"stage": "cluster", "status": "completed", "runtime_proof": "observed", "source_ref": {"path": "cluster.cpp"}}]},
        source_context=identity,
        replay_plan={"status": "ready"},
        run_evidence={"status": "completed", "runtime_proof": "observed"},
    )

    assert capability["status"] == "partial"
    assert capability["freshness"]["status"] == "partial"
    assert capability["identity_binding"]["status"] == "partial"
    assert "execution-identity" in {item["id"] for item in capability["unsupported"]}


def test_capability_manifest_requires_plan_run_and_current_identity_to_align():
    identity = {
        "data_fingerprint": "data",
        "source_context_id": "source",
        "binary_fingerprint": "binary",
        "config_fingerprint": "config",
        "session_id": "session",
    }
    contract = {"status": "ready", "strategy": "point_cloud", "data_fingerprint": "data", "source_context_id": "source"}
    coverage = {"stages": [{"stage": "cluster", "status": "completed", "runtime_proof": "observed", "source_ref": {"path": "cluster.cpp"}}]}
    context = dict(identity)
    plan = {
        "status": "ready",
        "plan_hash": "plan-hash",
        "identity": dict(identity),
        "target": {"server": {"host": "10.0.0.1"}},
        "runtime_binding": {"status": "aligned", "workspace_root": "/home/test/arbe"},
    }
    run = {
        "status": "completed",
        "runtime_proof": "observed",
        "plan_hash": "plan-hash",
        "run_id": "run-1",
        "attempt_id": "attempt-1",
        "identity": dict(identity),
    }
    execution_binding = {
        "status": "verified",
        "binding_hash": "binding-hash",
        "point_cloud_plan_hash": "plan-hash",
        "run_id": "run-1",
    }

    aligned = build_perception_capability_manifest(
        input_contract=contract,
        stage_coverage=coverage,
        source_context=context,
        replay_plan=plan,
        run_evidence=run,
        execution_binding=execution_binding,
    )
    assert aligned["status"] == "ready"
    assert aligned["freshness"]["status"] == "verified"
    assert aligned["identity_binding"]["status"] == "aligned"

    run["identity"]["binary_fingerprint"] = "different-binary"
    conflicted = build_perception_capability_manifest(
        input_contract=contract,
        stage_coverage=coverage,
        source_context=context,
        replay_plan=plan,
        run_evidence=run,
        execution_binding=execution_binding,
    )
    assert conflicted["status"] == "blocked"
    assert conflicted["freshness"]["status"] == "conflict"
    assert conflicted["identity_binding"]["status"] == "conflict"


def test_report_validation_rejects_ready_without_runtime_invariants():
    validation = build_perception_validation(
        report={"schema_version": "perception-report.v1"},
        analysis={
            "status": "ready",
            "input_contract": {"point_count": 1, "points": [{}]},
            "stage_coverage": {"status": "partial", "available_stage_count": 0, "total_stage_count": 1, "stages": [{"status": "not_available"}]},
            "lineage": {"status": "not_available", "edge_count": 0, "edges": []},
            "run_evidence": {"status": "partial"},
            "hypothesis_set": {"hypotheses": []},
        },
    )
    assert validation["status"] == "invalid"
    assert "ready_without_completed_run" in validation["errors"]
    assert "ready_without_ready_capability_manifest" in validation["errors"]


def test_structured_artifact_adapter_classifies_jsonl_csv_and_blocks_binary(tmp_path: Path):
    jsonl = tmp_path / "points.jsonl"
    jsonl.write_text(
        '{"frame_id":1,"range":5.0,"azimuth":0.1,"doppler":0.2}\n'
        '{"kind":"track","frame_id":1,"track_id":"t1"}\n',
        encoding="utf-8",
    )
    audit = audit_perception_artifact(jsonl)
    assert audit["status"] == "supported"
    payload = load_perception_artifact(jsonl)
    assert len(payload["point_rows"]) == 1
    assert len(payload["track_rows"]) == 1
    jsonl.write_text(
        '{"type":"stage","stage":"track","frame_id":1,"status":"completed"}\n',
        encoding="utf-8",
    )
    typed_payload = load_perception_artifact(jsonl)
    assert len(typed_payload["stage_evidence"]) == 1
    csv_path = tmp_path / "points.csv"
    csv_path.write_text("frame_id,dist,ang,vel\n2,6.0,0.2,0.3\n", encoding="utf-8")
    csv_payload = load_perception_artifact(csv_path)
    assert len(csv_payload["point_rows"]) == 1
    binary = tmp_path / "capture.MF4"
    binary.write_bytes(b"not parsed here")
    binary_audit = audit_perception_artifact(binary)
    assert binary_audit["status"] == "unsupported"
    assert "binary_parser_not_attached:mf4" in binary_audit["diagnostics"]
    assert ".json" in binary_audit["registered_formats"]
    assert "json_object" in binary_audit["registered_parsers"]
    Draft202012Validator(json.loads((Path(__file__).resolve().parents[1] / "contracts" / "perception-artifact-audit.v1.schema.json").read_text(encoding="utf-8"))).validate(binary_audit)


def test_artifact_adapter_registry_accepts_external_loader(tmp_path: Path):
    custom = tmp_path / "sample.pcloud"
    custom.write_text("external", encoding="utf-8")
    register_perception_artifact_adapter(
        ".pcloud",
        parser="external_test",
        loader=lambda path: {"point_rows": [{"frame_id": 3, "range": 4.0, "azimuth": 0.0, "doppler": 0.1}], "source_path": str(path)},
    )
    try:
        audit = audit_perception_artifact(custom)
        payload = load_perception_artifact(custom)
        assert audit["status"] == "supported"
        assert audit["parser"] == "external_test"
        assert len(payload["point_rows"]) == 1
    finally:
        PERCEPTION_ARTIFACT_ADAPTERS.pop(".pcloud", None)


def test_point_cloud_analyze_writes_partial_report_without_stage_evidence(tmp_path: Path):
    result = PointCloudAnalyzeModule().safe_run(
        point_rows=[{"frame_id": 10, "radar_id": 2, "range": 5.0, "azimuth": 1.0, "doppler": 0.2}],
        source_context={"data_fingerprint": "data-sha"},
        output_dir=str(tmp_path),
    )
    assert result.ok
    assert result.data["schema_version"] == "perception-report.v1"
    assert result.data["status"] == "partial"
    assert any(item.endswith("perception-report.html") for item in result.artifacts)
    assert json.loads((tmp_path / "perception-report.json").read_text(encoding="utf-8"))["status"] == "partial"
    validation = result.data["validation"]
    assert validation["schema_version"] == "perception-validation.v1"
    Draft202012Validator(json.loads((Path(__file__).resolve().parents[1] / "contracts" / "perception-validation.v1.schema.json").read_text(encoding="utf-8"))).validate(validation)


def test_run_evidence_keeps_completed_frame_ledger_and_failure_attempt():
    run = build_perception_run_evidence(
        run_id="run-1",
        attempt_id="attempt-2",
        terminal_status="interrupted",
        warmup_requested=175,
        warmup_completed=120,
        observed_frames=[1, 2, 3],
        completed_frames=[1, 2, 99],
        reset_events=[{"event": "reset_started", "status": "observed"}],
        failure_reason="ssh_disconnect",
    )
    assert run["status"] == "partial"
    assert run["analyzed_frames"] == ["1", "2", "99"]
    assert "completed_frame_not_in_observed_frames" in run["diagnostics"]
    assert run["reset_status"] == "not_available"


def test_comparison_requires_explicit_identity_and_reports_first_divergence():
    unavailable = build_perception_comparison(
        recorded_rows=[{"frame_id": 10, "track_id": 1, "range": 5.0}],
        replay_rows=[{"frame_id": 11, "track_id": 1, "range": 6.0}],
    )
    assert unavailable["status"] == "not_available"
    assert "explicit_frame_identity_match_missing" in unavailable["diagnostics"]
    compared = build_perception_comparison(
        recorded_rows=[{"radar_id": 2, "frame_id": 10, "object_key": "r1", "range": 5.0}],
        replay_rows=[{"radar_id": 2, "frame_id": 10, "object_key": "r1", "range": 6.0}],
        alignment={"method": "exact_frame_key", "key_fields": ["radar_id", "frame_id", "object_key"]},
    )
    assert compared["status"] == "derived"
    assert compared["first_divergence"]["frame_id"] == "10"
    assert compared["first_divergence"]["differences"][0]["field"] == "range"
    assert compared["metrics"]["consistency_ratio"] == 0.0
    assert compared["metrics"]["precision_recall_available"] is False


def test_point_cloud_contracts_validate_produced_projection(tmp_path: Path):
    result = PointCloudAnalyzeModule().safe_run(
        point_rows=[{"frame_id": 10, "radar_id": 2, "range": 5.0, "azimuth": 1.0, "doppler": 0.2}],
        source_context={"data_fingerprint": "data-sha"},
        output_dir=str(tmp_path),
    )
    root = Path(__file__).resolve().parents[1]
    report = json.loads((tmp_path / "perception-report.json").read_text(encoding="utf-8"))
    Draft202012Validator(json.loads((root / "contracts" / "perception-report.v1.schema.json").read_text(encoding="utf-8"))).validate(report)
    Draft202012Validator(json.loads((root / "contracts" / "perception-analysis.v1.schema.json").read_text(encoding="utf-8"))).validate(result.data["analysis"])


def test_run_and_comparison_contracts_validate():
    root = Path(__file__).resolve().parents[1]
    run = build_perception_run_evidence(
        run_id="r",
        attempt_id="a",
        plan_hash="plan-hash",
        terminal_status="completed",
        warmup_requested=1,
        warmup_completed=1,
        completed_frames=[1],
        observed_frames=[1],
        reset_events=[{"event": "reset_completed"}],
    )
    assert run["status"] == "completed"
    missing_plan_binding = build_perception_run_evidence(
        run_id="r",
        attempt_id="a",
        terminal_status="completed",
        warmup_requested=1,
        warmup_completed=1,
        completed_frames=[1],
        observed_frames=[1],
        reset_events=[{"event": "reset_completed"}],
    )
    assert missing_plan_binding["status"] == "partial"
    assert "plan_hash_missing" in missing_plan_binding["diagnostics"]
    comparison = build_perception_comparison(explicit_matches=[{"status": "observed", "left": {"frame_id": 1}, "right": {"frame_id": 1}}])
    Draft202012Validator(json.loads((root / "contracts" / "perception-run.v1.schema.json").read_text(encoding="utf-8"))).validate(run)
    Draft202012Validator(json.loads((root / "contracts" / "perception-comparison.v1.schema.json").read_text(encoding="utf-8"))).validate(comparison)
    scene = build_perception_scene(points=[{"frame_id": 1, "range": 1.0, "azimuth": 0.0}], selected_frame=1, angle_unit="rad")
    timeline = build_perception_timeline(stage_coverage={"stages": [{"stage": "track", "evidence_rows": [{"frame_key": "1", "status": "completed"}]}]}, selected_frame=1)
    warmup = build_perception_warmup_analysis([{"warmup_requested": 175, "warmup_completed": 175, "status": "completed", "output_signature": "sig"}])
    Draft202012Validator(json.loads((root / "contracts" / "perception-scene.v1.schema.json").read_text(encoding="utf-8"))).validate(scene)
    Draft202012Validator(json.loads((root / "contracts" / "perception-timeline.v1.schema.json").read_text(encoding="utf-8"))).validate(timeline)
    Draft202012Validator(json.loads((root / "contracts" / "perception-warmup-analysis.v1.schema.json").read_text(encoding="utf-8"))).validate(warmup)


def test_point_cloud_modules_are_registered():
    assert MODULE_REGISTRY["point-cloud-plan"] is PointCloudPlanModule
    assert MODULE_REGISTRY["point-cloud-analyze"] is PointCloudAnalyzeModule
    assert MODULE_REGISTRY["point-cloud-batch"] is PointCloudBatchModule
    assert MODULE_REGISTRY["point-cloud-validate"] is PointCloudValidateModule
    assert MODULE_REGISTRY["point-cloud-read"] is PointCloudReadModule


def test_point_cloud_read_returns_bounded_report_summary_and_callback_lineage(tmp_path: Path):
    report_path = tmp_path / "perception-report.json"
    report_path.write_text(json.dumps({
        "schema_version": "perception-report.v1",
        "status": "partial",
        "validation": {"status": "valid_with_warnings", "errors": [], "warnings": ["partial"]},
        "analysis": {
            "status": "partial",
            "conclusion_level": "facts_only",
            "strategy": "point_cloud",
            "input_contract": {"point_count": 1000, "input_boundary": "public_stage_point_cloud_observation"},
            "stage_coverage": {"status": "partial", "available_stage_count": 2, "derived_stage_count": 4, "total_stage_count": 8, "stages": [{"stage": str(i)} for i in range(10)]},
            "lineage": {
                "status": "derived", "edge_count": 3,
                "relation_kinds": ["point_supports_cluster"], "edges": [
                    {"from": "cb-1:p1", "to": "cb-1:c1", "relation_kind": "point_supports_cluster"},
                    {"from": "cb-2:p2", "to": "cb-2:c2", "relation_kind": "point_supports_cluster"},
                ],
                "invalid_edges": [], "nodes": {
                    "points": [{"point_key": "cb-1:p1", "frame_key": "cb-1"}, {"point_key": "cb-2:p2", "frame_key": "cb-2"}],
                    "clusters": [{"cluster_id": "cb-1:c1", "frame_key": "cb-1"}, {"cluster_id": "cb-2:c2", "frame_key": "cb-2"}],
                    "tracks": [], "outputs": [],
                },
            },
            "scene": {"status": "observed", "selected_frame": "cb-1", "counts": {"points": 1}},
            "run_evidence": {"status": "partial", "reset_status": "not_available"},
            "source_execution_contract": {"status": "source_verified"},
            "callback_binding_summary": {"status": "derived", "binding_count": 2},
            "callback_bindings": [{"callback_key": "cb-1"}, {"callback_key": "cb-2"}],
            "code_flow": {"stage_bindings": []},
            "gaps": [{"id": f"gap-{i}"} for i in range(5)],
        },
    }), encoding="utf-8")
    result = PointCloudReadModule().safe_run(report_path=str(report_path), section="lineage", callback_key="cb-1", limit=1)
    assert result.ok
    assert result.data["status"] == "ready"
    assert result.data["truncated"] is False
    assert result.data["data"]["node_counts"]["points"] == 1
    assert result.data["data"]["edges"][0]["from"] == "cb-1:p1"
    Draft202012Validator(json.loads((Path(__file__).resolve().parents[1] / "contracts" / "perception-report-query.v1.schema.json").read_text(encoding="utf-8"))).validate(result.data)

    selected_frame = PointCloudReadModule().safe_run(report_path=str(report_path), section="lineage", limit=10)
    assert selected_frame.data["data"]["callback_key"] == "cb-1"
    assert selected_frame.data["data"]["callback_key_basis"] == "report_selected_frame"
    assert selected_frame.data["data"]["node_counts"]["points"] == 1

    summary = PointCloudReadModule().safe_run(report_path=str(report_path), section="summary", limit=2)
    assert summary.ok
    assert summary.data["data"]["stage_coverage"]["derived_stage_count"] == 4
    assert summary.data["truncated"] is True


def test_point_cloud_report_bounds_large_lineage_and_read_recovers_exact_callback_slice(tmp_path: Path):
    point_rows = [
        {"point_key": f"cb-{index}:p", "frame_key": f"cb-{index}", "frame_id": index, "radar_id": 2, "range": 5.0, "azimuth": 0.1, "doppler": 0.2, "cluster_id": index + 1, "track_id": index + 1, "raw": {"payload_blob": "x" * 2048}}
        for index in range(5)
    ]
    cluster_rows = [{"cluster_id": f"cb-{index}:c", "algorithm_cluster_id": index + 1, "frame_key": f"cb-{index}"} for index in range(5)]
    track_rows = [{"track_key": f"cb-{index}:t", "algorithm_track_id": index + 1, "frame_key": f"cb-{index}"} for index in range(5)]
    output_rows = [{"output_key": f"cb-{index}:o", "algorithm_track_id": index + 1, "frame_key": f"cb-{index}"} for index in range(5)]
    edges = []
    for index in range(5):
        edges.extend([
            {"from": f"cb-{index}:p", "to": f"cb-{index}:c", "relation_kind": "point_supports_cluster"},
            {"from": f"cb-{index}:c", "to": f"cb-{index}:t", "relation_kind": "cluster_supports_track"},
            {"from": f"cb-{index}:t", "to": f"cb-{index}:o", "relation_kind": "track_emits_output"},
        ])
    result = PointCloudAnalyzeModule().safe_run(
        point_rows=point_rows,
        cluster_rows=cluster_rows,
        track_rows=track_rows,
        output_rows=output_rows,
        lineage_edges=edges,
        max_inline_points=2,
        output_dir=str(tmp_path),
    )
    assert result.ok
    report_path = tmp_path / "perception-report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    lineage = report["analysis"]["lineage"]
    assert report["validation"]["status"] == "valid_with_warnings"
    assert report["validation"]["checks"]["lineage_count"] is True
    assert lineage["node_counts"] == {"points": 5, "clusters": 5, "tracks": 5, "outputs": 5}
    assert report["analysis"]["input_contract"]["points_artifact"]["path"] == "perception-points.jsonl"
    assert lineage["lineage_artifact"]["path"] == "perception-lineage.jsonl"
    assert lineage["lineage_artifact"]["index_ref"]["path"] == "perception-lineage-index.v1.json"
    assert lineage["edges_truncated"] is True
    assert len(lineage["edges"]) == 2
    assert len(lineage["nodes"]["points"]) == 2
    lineage_path = tmp_path / lineage["lineage_artifact"]["path"]
    index_path = tmp_path / lineage["lineage_artifact"]["index_ref"]["path"]
    assert lineage_path.is_file()
    assert index_path.is_file()
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index_schema = json.loads((Path(__file__).resolve().parents[1] / "contracts" / "perception-lineage-index.v1.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(index_schema).validate(index)
    assert report_path.stat().st_size < 100_000

    summary = PointCloudReadModule().safe_run(report_path=str(report_path), section="summary", limit=20)
    assert summary.data["data"]["lineage"]["node_counts"] == {"points": 5, "clusters": 5, "tracks": 5, "outputs": 5}

    callback = PointCloudReadModule().safe_run(report_path=str(report_path), section="lineage", callback_key="cb-4", limit=20)
    assert callback.data["status"] == "ready"
    assert callback.data["truncated"] is False
    assert callback.data["data"]["node_counts"] == {"points": 1, "clusters": 1, "tracks": 1, "outputs": 1}
    assert callback.data["data"]["full_edge_count"] == 3
    assert callback.data["data"]["relation_counts"] == {"cluster_supports_track": 1, "point_supports_cluster": 1, "track_emits_output": 1}
    assert callback.data["data"]["raw_relation_counts"] == callback.data["data"]["relation_counts"]
    assert callback.data["data"]["relation_summaries"]["cluster_supports_track"] == {
        "from_node_kind": "clusters",
        "to_node_kind": "tracks",
        "edge_row_count": 1,
        "unique_pair_count": 1,
        "unique_from_node_count": 1,
        "unique_to_node_count": 1,
    }
    assert callback.data["data"]["field_counts"]["points.track_id"] == {"5": 1}
    assert callback.data["data"]["field_counts"]["points.cluster_id"] == {"5": 1}
    assert callback.data["data"]["field_summaries"]["points.track_id"] == {"total_count": 1, "unique_value_count": 1}
    assert {row["relation_kind"] for row in callback.data["data"]["edges"]} == {
        "point_supports_cluster", "cluster_supports_track", "track_emits_output",
    }
    assert {row["frame_key"] for row in callback.data["data"]["nodes"]["points"]} == {"cb-4"}
    assert "raw" not in callback.data["data"]["nodes"]["points"][0]

    one_row_page = PointCloudReadModule().safe_run(report_path=str(report_path), section="lineage", callback_key="cb-4", limit=1)
    assert one_row_page.data["truncated"] is True
    assert one_row_page.data["data"]["relation_counts"] == callback.data["data"]["relation_counts"]
    assert one_row_page.data["data"]["field_counts"] == callback.data["data"]["field_counts"]

    copied = tmp_path / "copied-bundle"
    copied.mkdir()
    bundle_files = (
        "perception-report.json", "perception-report.html", "perception-report-README.md",
        "perception-points.jsonl", "perception-lineage.jsonl", "perception-lineage-index.v1.json",
    )
    for name in bundle_files:
        shutil.copy2(tmp_path / name, copied / name)
    relocated = PointCloudReadModule().safe_run(
        report_path=str(copied / "perception-report.json"), section="lineage", callback_key="cb-4", limit=20,
    )
    assert relocated.data["status"] == "ready"
    assert relocated.data["data"]["node_counts"] == {"points": 1, "clusters": 1, "tracks": 1, "outputs": 1}
    assert relocated.data["data"]["full_edge_count"] == 3

    callback_range = index["callbacks"]["cb-4"]
    with lineage_path.open("r+b") as handle:
        handle.seek(callback_range["offset"])
        block_prefix = handle.read(callback_range["length"])
        tampered_block = block_prefix.replace(b"cb-4", b"cb-9", 1)
        assert tampered_block != block_prefix
        handle.seek(callback_range["offset"])
        handle.write(tampered_block)
    tampered = PointCloudReadModule().safe_run(report_path=str(report_path), section="lineage", callback_key="cb-4", limit=20)
    assert tampered.data["status"] == "partial"
    assert "lineage_callback_block_hash_mismatch" in tampered.data["diagnostics"]


def test_point_cloud_analyze_auto_persists_large_artifacts_when_output_dir_is_omitted(tmp_path: Path, monkeypatch):
    import ai.modules.point_cloud as point_cloud_module

    monkeypatch.setattr(point_cloud_module, "_POINT_CLOUD_OUTPUT_ROOT", tmp_path / "point-cloud-analysis")
    result = PointCloudAnalyzeModule().safe_run(
        point_rows=[{"frame_id": index, "range": 5.0, "azimuth": 0.1, "doppler": 0.2} for index in range(5)],
        max_inline_points=2,
    )
    assert result.ok
    output = Path(result.data["artifact_output"]["directory"])
    assert result.data["artifact_output"]["automatic"] is True
    assert (output / "perception-points.jsonl").is_file()
    assert (output / "perception-report.json").is_file()
    assert (output / "perception-report.html").is_file()
    readme = output / "perception-report-README.md"
    assert readme.is_file()
    assert str(readme) in result.data["artifact_paths"]
    assert "python -m http.server 8765 --bind 127.0.0.1" in readme.read_text(encoding="utf-8")
    assert result.data["analysis"]["input_contract"]["points_truncated"] is True
    assert result.data["validation"]["status"] == "valid_with_warnings"


def test_point_cloud_html_exposes_interactive_exact_frame_scene_without_cross_frame_overlay(tmp_path: Path):
    result = PointCloudAnalyzeModule().safe_run(
        point_rows=[
            {"point_key": "p1</script><script>alert(1)</script>", "frame_key": "cb-1", "frame_id": 1, "radar_id": 2, "x": 1.0, "y": 2.0, "range": 5.0, "azimuth": 0.1, "doppler": 0.2, "cluster_id": 7, "track_id": 43},
            {"point_key": "p2", "frame_key": "cb-1", "frame_id": 1, "radar_id": 2, "x": 3.0, "y": 4.0, "range": 6.0, "azimuth": 0.2, "doppler": 0.3, "cluster_id": 7, "track_id": 43},
        ],
        cluster_rows=[{"cluster_id": "cb-1:cluster:7", "algorithm_cluster_id": 7, "frame_key": "cb-1"}],
        track_rows=[{"track_key": "cb-1:track:43", "algorithm_track_id": 43, "track_id": 43, "frame_key": "cb-1", "distX": 60.0, "distY": 10.0}],
        output_rows=[{"output_key": "cb-1:output:43", "algorithm_track_id": 43, "track_id": 43, "frame_key": "cb-1", "distX": 60.0, "distY": 10.0}],
        stage_evidence=[{"stage": "cluster", "frame_key": "cb-1", "status": "completed", "runtime_proof": "observed", "input_count": 2, "output_count": 1}],
        selected_frame="cb-1",
        frame_domain="source_proven_public_callback_order",
        coordinate_frame="image_radar",
        output_dir=str(tmp_path),
    )
    assert result.ok
    html_text = (tmp_path / "perception-report.html").read_text(encoding="utf-8")
    readme_text = (tmp_path / "perception-report-README.md").read_text(encoding="utf-8")
    assert 'id="selected-frame-svg"' in html_text
    assert 'id="scene-model"' in html_text
    assert 'data-toggle-layer="clusters"' in html_text
    assert "图层可用性" in html_text
    assert "Input LGU dotTrans" in html_text
    assert "Pre-filter point rows" in html_text
    assert "PointCloud2 point layer" in html_text
    assert 'class="object-select"' in html_text
    assert 'class="point-select"' in html_text
    assert 'class="cluster-select"' in html_text
    assert "选中帧证据" in html_text
    assert "已完成 <code>completed</code> / 已观测 <code>observed</code>" in html_text
    assert "mean_of_exact_point_cluster_id" in html_text
    assert "not spatially overlaid" in html_text
    assert "p1</script><script>alert" not in html_text
    assert "p1\\u003c/script\\u003e" in html_text
    assert "does not load external web assets" in readme_text


def test_point_cloud_validate_reads_existing_report_without_reanalysis(tmp_path: Path):
    report = PointCloudAnalyzeModule().safe_run(
        point_rows=[{"frame_id": 1, "range": 5.0, "azimuth": 0.1, "doppler": 0.2}],
        output_dir=str(tmp_path / "report"),
    )
    output = tmp_path / "validation.json"
    result = PointCloudValidateModule().safe_run(
        report_path=str(tmp_path / "report" / "perception-report.json"),
        output=str(output),
    )
    assert result.ok
    assert result.data["schema_version"] == "perception-validation.v1"
    assert result.data["status"] in {"valid", "valid_with_warnings"}
    assert output.is_file()


def test_large_point_report_is_bounded_and_writes_jsonl_artifact(tmp_path: Path):
    points = [{"frame_id": 1, "point_key": f"p{i}", "range": 5.0 + i, "azimuth": 0.1, "doppler": 0.2} for i in range(5)]
    result = PointCloudAnalyzeModule().safe_run(
        point_rows=points,
        max_inline_points=2,
        output_dir=str(tmp_path),
    )
    assert result.ok
    report = json.loads((tmp_path / "perception-report.json").read_text(encoding="utf-8"))
    contract = report["analysis"]["input_contract"]
    assert contract["point_count"] == 5
    assert contract["inline_point_count"] == 2
    assert contract["points_truncated"] is True
    assert (tmp_path / "perception-points.jsonl").is_file()
    assert report["validation"]["status"] in {"valid_with_warnings", "valid"}
    assert any(str(tmp_path / "perception-points.jsonl") == path for path in report["artifact_paths"])


def test_point_cloud_batch_keeps_good_bad_and_empty_cases(tmp_path: Path):
    good = tmp_path / "good.json"
    good.write_text(json.dumps({"point_rows": [{"frame_id": 1, "radar_id": 2, "range": 4.0, "azimuth": 0.1, "doppler": 0.2}]}), encoding="utf-8")
    bad = tmp_path / "bad.json"
    bad.write_text("{broken", encoding="utf-8")
    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"point_rows": [{"frame_id": 2, "radar_id": 2, "range": 4.2, "azimuth": 0.0, "doppler": 0.0}], "warning_rows": []}), encoding="utf-8")
    output = tmp_path / "out"
    result = PointCloudBatchModule().safe_run(
        manifest={"cases": [
            {"case_id": "good", "capture_path": str(good)},
            {"case_id": "bad", "capture_path": str(bad)},
            {"case_id": "empty", "capture_path": str(empty)},
        ]},
        output_dir=str(output),
    )
    assert result.ok
    assert result.data["case_count"] == 3
    assert result.data["failed_count"] == 1
    assert {item["case_id"] for item in result.data["cases"]} == {"good", "bad", "empty"}
    assert (output / "perception-batch-index.json").is_file()
    assert (output / "cases" / "good" / "perception-report.json").is_file()
    Draft202012Validator(json.loads((Path(__file__).resolve().parents[1] / "contracts" / "perception-batch-index.v1.schema.json").read_text(encoding="utf-8")).copy()).validate(result.data)


def test_point_cloud_batch_uses_structured_adapter_and_preserves_binary_gap(tmp_path: Path):
    csv_path = tmp_path / "points.csv"
    csv_path.write_text("frame_id,dist,ang,vel\n1,5.0,0.1,0.2\n", encoding="utf-8")
    mf4_path = tmp_path / "capture.MF4"
    mf4_path.write_bytes(b"binary placeholder")
    output = tmp_path / "batch"
    result = PointCloudBatchModule().safe_run(
        manifest={"cases": [
            {"case_id": "csv", "capture_path": str(csv_path)},
            {"case_id": "mf4", "capture_path": str(mf4_path)},
        ]},
        output_dir=str(output),
    )
    assert result.ok
    csv_entry = next(item for item in result.data["cases"] if item["case_id"] == "csv")
    mf4_entry = next(item for item in result.data["cases"] if item["case_id"] == "mf4")
    assert csv_entry["artifact_audit"]["format"] == "csv"
    assert (output / "cases" / "csv" / "perception-report.json").is_file()
    assert mf4_entry["artifact_audit"]["status"] == "unsupported"
    assert "binary_parser_not_attached:mf4" in mf4_entry["failure_reason"]


def test_point_cloud_batch_index_carries_metadata_and_offline_filter(tmp_path: Path):
    output = tmp_path / "batch"
    result = PointCloudBatchModule().safe_run(
        manifest={"cases": [{
            "case_id": "case-fcta",
            "project_id": "CR60-BYD",
            "function": "FCTA",
            "stage": "track",
            "point_rows": [{"frame_id": 1, "range": 5.0, "azimuth": 0.1, "doppler": 0.2}],
        }]},
        output_dir=str(output),
    )
    assert result.ok
    entry = result.data["cases"][0]
    assert entry["project_id"] == "CR60-BYD"
    html = (output / "perception-batch-index.html").read_text(encoding="utf-8")
    assert 'id="filter"' in html
    assert "CR60-BYD" in html
    metrics = (output / "perception-batch-metrics.csv").read_text(encoding="utf-8")
    assert "point_count" in metrics
    assert "case-fcta" in metrics


def test_source_stage_map_preserves_real_function_and_macro_context(tmp_path: Path):
    source = tmp_path / "postProcess.c"
    source.write_text(
        "#if 0 == HILMODEL\n"
        "void PostProcessMainTI(void) { DotFilter(1); ObjCluster(1); ObjTrack(1); }\n"
        "void AdasFunc(void) {}\n",
        encoding="utf-8",
    )
    stage_map = build_perception_stage_map(tmp_path)
    assert stage_map["status"] == "ready"
    assert stage_map["source_snapshot_hash"]
    assert stage_map["stages"]["dot_filter"][0]["source_ref"]["line"] == 2
    assert stage_map["stages"]["dot_filter"][0]["preprocessor_context"] == "HILMODEL_preprocessor_context"
    assert stage_map["stages"]["dot_filter"][0]["activation_requirement"] == "HILMODEL==0"
    assert stage_map["stages"]["adas_func"][0]["status"] == "source_candidate"
    Draft202012Validator(json.loads((Path(__file__).resolve().parents[1] / "contracts" / "perception-stage-map.v1.schema.json").read_text(encoding="utf-8"))).validate(stage_map)


def test_bounded_code_context_reads_index_once_and_matches_stage_functions_exactly(tmp_path: Path, monkeypatch):
    source_file = tmp_path / "perception.c"
    source_file.write_text("void PostProcessMainTI(void) { DotFilter(); AdasFunc(); }\n", encoding="utf-8")
    source_hash = hashlib.sha256(source_file.read_bytes()).hexdigest()
    index_path = tmp_path / "code-index.json"
    index_path.write_text(json.dumps({
        "schema_version": "code-index.v1",
        "source_root": str(tmp_path),
        "snapshot_hash": "snapshot-1",
        "files": [{"path": "perception.c", "sha256": source_hash}],
        "functions": [
            {"name": "PostProcessMainTI", "file_path": "perception.c", "start_line": 1, "end_line": 1},
            {"name": "DotFilter", "file_path": "perception.c", "start_line": 2, "end_line": 8},
            {"name": "ResetDotFilter", "file_path": "perception.c", "start_line": 10, "end_line": 12},
            {"name": "UnrelatedDotFilterHelper", "file_path": "other.c", "start_line": 1, "end_line": 2},
            {"name": "AdasFunc", "file_path": "adas.c", "start_line": 20, "end_line": 40},
            {"name": "FrontCrossTrafficAlertAndBrake", "file_path": "adas.c", "start_line": 50, "end_line": 80},
            {"name": "FctaDirectRunning", "file_path": "adas.c", "start_line": 90, "end_line": 100},
        ],
        "calls": {
            "PostProcessMainTI": ["DotFilter", "AdasFunc"],
            "DotFilter": ["ResetDotFilter"],
            "FrontCrossTrafficAlertAndBrake": ["FctaDirectRunning"],
            "UnrelatedDotFilterHelper": [],
        },
        "conditions": [{"function": "AdasFunc", "expression": "fcta_enabled == 1"}],
    }), encoding="utf-8")
    context = {
        "schema_version": "code-context.v1",
        "context_id": "ctx-1",
        "source_context": {
            "source_root": str(tmp_path),
            "snapshot_hash": "snapshot-1",
            "files": [{"path": "perception.c", "sha256": source_hash}],
        },
        "artifacts": {"code_index": str(index_path)},
        "summary": {"functions": 7, "calls": 4},
    }
    original_read_text = Path.read_text
    code_index_reads = []

    def _count_index_read(path, *args, **kwargs):
        if path.resolve() == index_path.resolve():
            code_index_reads.append(path)
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", _count_index_read)
    projected = _bounded_code_context(context, str(tmp_path / "code-context.json"))

    names = {item["name"] for item in projected["functions"]}
    assert code_index_reads == [index_path]
    assert {"DotFilter", "AdasFunc", "FctaDirectRunning"}.issubset(names)
    assert "UnrelatedDotFilterHelper" not in names
    assert "DotFilter" in projected["function_resolution"]["matched_names"]
    assert "DotFilter" not in projected["function_resolution"]["missing_names"]
    assert projected["truncated"]["functions"] is False


def test_code_flow_uses_function_definitions_only_when_all_file_hashes_match(tmp_path: Path):
    source_file = tmp_path / "dotFilter.c"
    source_file.write_text("void DotFilter(void) {}\n", encoding="utf-8")
    source_hash = hashlib.sha256(source_file.read_bytes()).hexdigest()
    stage_map = {
        "schema_version": "perception-stage-map.v1",
        "source_root": str(tmp_path),
        "source_snapshot_hash": "stage-map-hash",
        "scanned_files": [str(source_file.resolve())],
        "stages": {
            "dot_filter": [{
                "function": "DotFilter",
                "source_ref": {"path": "dotFilter.c", "line": 1},
                "snippet": "DotFilter();",
                "status": "source_candidate",
            }],
        },
    }
    code_context = {
        "schema_version": "code-index.v1",
        "source_root": str(tmp_path),
        "snapshot_hash": "code-index-hash",
        "files": [{"path": "dotFilter.c", "sha256": source_hash}],
        "functions": [{
            "name": "DotFilter",
            "file_path": "dotFilter.c",
            "start_line": 1,
            "end_line": 1,
            "signature": "void DotFilter(void)",
            "source_hash": source_hash[:16],
        }],
    }
    flow = build_perception_code_flow(
        stage_map=stage_map,
        code_context=code_context,
        source_context={"source_root": str(tmp_path)},
    )

    assert flow["code_context_binding"]["status"] == "same_file_snapshot"
    binding = next(row for row in flow["stage_bindings"] if row["stage"] == "dot_filter")
    assert binding["status"] == "source_candidate"
    assert binding["runtime_proof"] == "not_available"
    assert binding["function_definition_candidates"][0]["source_ref"]["line"] == 1
    assert binding["function_definition_candidates"][0]["basis"] == "code-index-function-definition"

    report_dir = tmp_path / "static-report"
    result = PointCloudAnalyzeModule().safe_run(
        point_rows=[],
        stage_map=stage_map,
        code_context=code_context,
        source_context={"source_root": str(tmp_path)},
        output_dir=str(report_dir),
    )
    assert result.ok
    assert result.data["status"] == "blocked"
    assert result.data["analysis"]["code_flow"]["code_context_binding"]["status"] == "same_file_snapshot"
    html_text = (report_dir / "perception-report.html").read_text(encoding="utf-8")
    assert "CodeIndex 函数定义候选" in html_text
    assert "function definition candidate" in html_text
    assert "dotFilter.c:1" in html_text
    assert "not_available" in html_text

    mismatched = dict(code_context)
    mismatched["source_root"] = str(tmp_path / "other")
    mismatched_flow = build_perception_code_flow(
        stage_map=stage_map,
        code_context=mismatched,
        source_context={"source_root": str(tmp_path)},
    )
    assert mismatched_flow["code_context_binding"]["status"] == "source_root_conflict"
    assert next(row for row in mismatched_flow["stage_bindings"] if row["stage"] == "dot_filter")["function_definition_candidates"] == []


def test_point_cloud_report_keeps_code_flow_artifacts(tmp_path: Path):
    result = PointCloudAnalyzeModule().safe_run(
        point_rows=[{"frame_id": 10, "radar_id": 2, "range": 5.0, "azimuth": 1.0, "doppler": 0.2}],
        code_context={"schema_version": "code-context.v1", "source_snapshot_hash": "source-sha"},
        event_code_path={"schema_version": "event-code-path.v1", "status": "partial"},
        condition_trace={"schema_version": "condition-trace.v1", "status": "partial", "conditions": [{"condition_id": "c1", "function": "ObjTrack", "expression": "speed > 0", "source_ref": {"path": "track.c", "line": 10}, "evaluation": {"status": "not_evaluable", "reason": "speed_missing"}, "missing_tokens": ["speed"]}]},
        output_dir=str(tmp_path),
    )
    assert result.ok
    assert result.data["analysis"]["code_flow"]["code_context"]["source_snapshot_hash"] == "source-sha"
    assert result.data["analysis"]["code_flow"]["stage_bindings"]
    assert all(item["status"] in {"not_available", "source_candidate"} for item in result.data["analysis"]["code_flow"]["stage_bindings"])
    assert result.data["analysis"]["code_flow"]["condition_bindings"][0]["evaluation_status"] == "not_evaluable"


def test_point_cloud_report_collapses_full_json_and_localizes_primary_summary(tmp_path: Path):
    stage_map = {
        "schema_version": "perception-stage-map.v1",
        "stages": {
            "dot_filter": [{
                "function": "DotFilter",
                "source_ref": {"path": "dotFilter.c", "line": 2226},
                "status": "source_candidate",
            }],
        },
    }
    result = PointCloudAnalyzeModule().safe_run(
        point_rows=[],
        stage_map=stage_map,
        output_dir=str(tmp_path),
    )

    assert result.ok
    html_text = (tmp_path / "perception-report.html").read_text(encoding="utf-8")
    assert "<h1>点云感知分析报告</h1>" in html_text
    assert "受阻" in html_text and "<code>blocked</code>" in html_text
    assert "未提供点云输入" in html_text and "<code>not_available</code>" in html_text
    assert "阶段覆盖" in html_text and "点迹过滤" in html_text and "dot_filter" in html_text
    assert "<details><summary>查看载荷结构与解析诊断</summary><pre>" in html_text
    assert "<details><summary>查看完整输入契约字段</summary><pre>" in html_text
    assert "图层可用性" in html_text


def test_point_cloud_report_projects_run_and_comparison(tmp_path: Path):
    result = PointCloudAnalyzeModule().safe_run(
        point_rows=[{"frame_id": 10, "radar_id": 2, "range": 5.0, "azimuth": 1.0, "doppler": 0.2}],
        recorded_rows=[{"radar_id": 2, "frame_id": 10, "object_key": "o1", "range": 5.0}],
        replay_rows=[{"radar_id": 2, "frame_id": 10, "object_key": "o1", "range": 5.5}],
        selected_frame=10,
        angle_unit="rad",
        range_unit="m",
        track_rows=[{"frame_id": 10, "track_id": "t1"}],
        comparison_alignment={"method": "exact_frame_key", "key_fields": ["radar_id", "frame_id", "object_key"]},
            run_evidence={
                "run_id": "run-1",
                "attempt_id": "attempt-1",
                "plan_hash": "plan-hash-1",
                "terminal_status": "completed",
            "observed_frames": [10],
            "completed_frames": [10],
            "warmup_completed": 175,
            "reset_events": [{"event": "reset_completed"}],
        },
        output_dir=str(tmp_path),
    )
    assert result.ok
    assert result.data["analysis"]["run_evidence"]["status"] == "completed"
    assert result.data["analysis"]["comparison"]["first_divergence"]["frame_id"] == "10"
    assert result.data["analysis"]["scene"]["selected_frame"] == "10"
    assert result.data["analysis"]["timeline"]["rows"][0]["track_ids"] == ["t1"]
    assert "选中帧场景与精确回调记录" in (tmp_path / "perception-report.html").read_text(encoding="utf-8")
