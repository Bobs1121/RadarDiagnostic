from __future__ import annotations

import json
from pathlib import Path

from ai.modules.point_cloud import PointCloudAnalyzeModule
from ai.modules.sim_verify import SimVerifyModule
from ai.modules.execution_binding import ExecutionBindingModule
from engines.point_cloud_replay import build_point_cloud_replay_plan
from engines.arbe.replay_provider import parse_warning_trace_csv


def test_warning_trace_keeps_generic_bits_without_current_mapping(tmp_path: Path):
    path = tmp_path / "trace.csv"
    path.write_text("event_sec,radar_id,frame_id,w1,w2\n1.0,2,10,1,0\n", encoding="utf-8")
    rows = parse_warning_trace_csv(path)
    assert rows[0].active_warnings() == ["w1"]
    assert rows[0].warning_mapping_source == "not_provided"


def test_warning_trace_uses_explicit_current_mapping(tmp_path: Path):
    path = tmp_path / "trace.csv"
    path.write_text("event_sec,radar_id,frame_id,w1,w2\n1.0,2,10,1,0\n", encoding="utf-8")
    rows = parse_warning_trace_csv(path, warning_names=["PROJECT_WARN_A", "PROJECT_WARN_B"])
    assert rows[0].active_warnings() == ["PROJECT_WARN_A"]
    assert rows[0].warning_mapping_source == "explicit_names"


def test_sim_verify_local_reads_case_runtime_warning_contract_and_writes_replay_artifact(tmp_path: Path):
    (tmp_path / "runtime_schema.json").write_text(
        '{"warning_contract":{"bits":{"1":"PROJECT_WARN_A"}}}',
        encoding="utf-8",
    )
    (tmp_path / "sample_algo_warning_trace.csv").write_text(
        "event_sec,radar_id,frame_id,w1\n1.0,2,10,1\n",
        encoding="utf-8",
    )
    output = tmp_path / "replay.json"
    result = SimVerifyModule().safe_run(
        mode="local", case_dir=str(tmp_path), output=str(output)
    )
    assert result.ok
    assert result.data["schema_version"] == "arbe-replay-result.v1"
    assert result.data["active_warnings"] == {"PROJECT_WARN_A": 1}
    assert output.is_file()


def test_sim_verify_remote_execution_requires_execution_binding():
    result = SimVerifyModule().safe_run(
        mode="remote_public",
        server_host="server",
        remote_bag_path="/data/example.bag",
        remote_capture_base="/tmp/run/public",
        input_topics=["/wf/corner_radar/lgu_data_1"],
        output_topics=["/corner_radar/warning_status_with_frame"],
        execute=True,
        approved=True,
    )
    assert result.ok
    assert result.data["status"] == "blocked"
    assert "execution_binding_missing" in result.data["diagnostics"]


def test_sim_verify_point_cloud_requires_ready_plan_before_remote_replay():
    result = SimVerifyModule().safe_run(
        mode="remote_public",
        strategy="point_cloud",
        server_host="server",
        remote_bag_path="/data/example.bag",
        remote_capture_base="/tmp/run/public",
        input_topics=["/radar/points"],
        output_topics=["/perception/objects"],
        point_cloud_plan={"schema_version": "point-cloud-replay-plan.v1", "mode": "point_cloud", "status": "blocked", "diagnostics": ["point_cloud_requires_hilmodel_0_current=2"]},
    )
    assert result.ok
    assert result.data["status"] == "blocked"
    assert "point_cloud_plan_required_and_must_be_ready" in result.data["diagnostics"]


def test_sim_verify_point_cloud_accepts_ready_plan_for_side_effect_free_planning():
    preflight = {
        "build": {"macros": {"HILMODEL": "0", "BUILDMODEL": "2", "PF_BUILD_FUNTEST_SGU_INJECTION": "0"}, "binary_fingerprint": "bin"},
        "workspace": {"outer": {"head": "outer"}, "algo_source": {"head": "algo"}},
        "configuration": {"resolved": {"coem_name": "TEST"}},
        "runtime": {"ros_master_uri": "http://localhost:11311", "processes": [{"pid": 1}]},
    }
    plan = build_point_cloud_replay_plan(
        remote_bag_path="/data/example.bag",
        remote_capture_base="/tmp/pc/run",
        point_cloud_topic="/radar/points",
        output_topics=["/perception/objects"],
        server_host="server",
        duration_sec=12.0,
        preflight=preflight,
        source_context={"data_fingerprint": "data", "source_context_id": "source"},
        input_contract={"schema_version": "perception-input-contract.v1", "status": "ready", "point_count": 1, "data_fingerprint": "data", "layout_status": "verified", "target_usage": {"status": "observed", "injection_detected": False}},
    )
    result = SimVerifyModule().safe_run(
        mode="remote_public",
        strategy="point_cloud",
        server_host="server",
        remote_bag_path="/data/example.bag",
        remote_capture_base="/tmp/pc/run",
        duration_sec=12.0,
        input_topics=["/radar/points"],
        output_topics=["/perception/objects"],
        point_cloud_plan=plan,
        execute=False,
    )
    assert result.ok
    assert result.data["status"] == "planned"
    assert result.data["strategy"] == "point_cloud"


def test_sim_verify_point_cloud_executes_only_after_plan_binding_with_fake_provider(monkeypatch, tmp_path: Path):
    preflight = {
        "build": {"macros": {"HILMODEL": "0", "BUILDMODEL": "2", "PF_BUILD_FUNTEST_SGU_INJECTION": "0"}, "binary_fingerprint": "bin"},
        "workspace": {"outer": {"head": "outer"}, "algo_source": {"head": "algo"}},
        "configuration": {"resolved": {"coem_name": "TEST"}},
        "runtime": {"ros_master_uri": "http://localhost:11311", "processes": [{"pid": 1}]},
    }
    source = {"data_fingerprint": "data", "source_context_id": "source"}
    plan = build_point_cloud_replay_plan(
        remote_bag_path="/data/example.bag",
        remote_capture_base="/tmp/pc/run",
        point_cloud_topic="/radar/points",
        output_topics=["/perception/objects"],
        server_host="server",
        duration_sec=12.0,
        preflight=preflight,
        source_context=source,
        input_contract={"schema_version": "perception-input-contract.v1", "status": "ready", "point_count": 1, "data_fingerprint": "data", "layout_status": "verified", "target_usage": {"status": "observed", "injection_detected": False}},
    )
    binding = ExecutionBindingModule().safe_run(
        plan=plan,
        preflight=preflight,
        source_context=source,
        approved=True,
        approval_id="pc-approval",
        run_id="pc-attempt-1",
    )
    assert binding.data["status"] == "approved"

    class FakeProvider:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def capture_public(self, **kwargs):
            assert kwargs["execute"] is True
            assert kwargs["attempt_id"] == "pc-attempt-1"
            capture_path = Path(kwargs["local_capture_path"])
            capture_path.write_text(json.dumps({
                "point_rows": [{"frame_id": 1, "range": 5.0, "azimuth": 0.1, "doppler": 0.2}],
                "stage_evidence": [{"stage": "input_decode", "frame_id": 1, "status": "completed", "runtime_proof": "observed"}],
                "completion": {"status": "completed", "stage_count": 1},
            }), encoding="utf-8")
            return {"schema_version": "arbe-public-replay-session.v1", "status": "completed", "completion": {"status": "completed", "stage_count": 1}, "local_capture_json": str(capture_path), "artifacts": [str(capture_path)]}

    monkeypatch.setattr("engines.arbe.remote_replay.RemoteArbeReplayProvider", FakeProvider)
    result = SimVerifyModule().safe_run(
        mode="remote_public",
        strategy="point_cloud",
        server_host="server",
        remote_bag_path="/data/example.bag",
        remote_capture_base="/tmp/pc/run",
        duration_sec=12.0,
        input_topics=["/radar/points"],
        output_topics=["/perception/objects"],
        local_capture_path=str(tmp_path / "pc-capture.json"),
        point_cloud_plan=plan,
        preflight=preflight,
        source_context=source,
        execution_binding=binding.data,
        execute=True,
        approved=True,
        output=str(tmp_path / "sim-verify-point-cloud.json"),
    )
    assert result.ok
    assert result.data["status"] == "partial"
    assert result.data["analysis_handoff"]["status"] == "ready"
    assert result.data["analysis_handoff"]["recommended_tool"] == "point-cloud-analyze"
    assert result.data["strategy"] == "point_cloud"
    assert result.data["execution_binding"]["status"] == "verified"
    handoff = result.data["analysis_handoff"]
    analysis_inputs = handoff["analysis_inputs"]
    assert analysis_inputs["replay_plan"]["plan_hash"] == plan["plan_hash"]
    assert analysis_inputs["execution_binding"]["point_cloud_plan_hash"] == plan["plan_hash"]
    assert Path(analysis_inputs["run_evidence_path"]).is_file()
    analyzed = PointCloudAnalyzeModule().safe_run(
        analysis_handoff=handoff,
        output_dir=str(tmp_path / "analyzed"),
    )
    assert analyzed.ok, analyzed.message
    assert analyzed.data["analysis"]["run_evidence"]["plan_hash"] == plan["plan_hash"]
    assert analyzed.data["analysis"]["run_evidence"]["status"] == "partial"
    assert analyzed.data["analysis"]["status"] == "partial"
    assert analyzed.data["analysis"]["capability_manifest"]["status"] != "ready"
    analyzed_from_file = PointCloudAnalyzeModule().safe_run(
        analysis_handoff_path=str(tmp_path / "sim-verify-point-cloud.json"),
        output_dir=str(tmp_path / "analyzed-from-file"),
    )
    assert analyzed_from_file.ok, analyzed_from_file.message
    assert analyzed_from_file.data["analysis"]["run_evidence"]["plan_hash"] == plan["plan_hash"]
    assert analyzed_from_file.data["status"] == "partial"
    analysis_inputs = result.data["analysis_handoff"]["analysis_inputs"]
    assert analysis_inputs["replay_plan"]["plan_hash"] == plan["plan_hash"]
    assert analysis_inputs["execution_binding"]["point_cloud_plan_hash"] == plan["plan_hash"]
    assert Path(analysis_inputs["run_evidence_path"]).is_file()
    analyzed = PointCloudAnalyzeModule().safe_run(
        analysis_handoff=result.data["analysis_handoff"],
        output_dir=str(tmp_path / "analyzed"),
    )
    assert analyzed.ok, analyzed.message
    assert analyzed.data["status"] == "partial"  # fake provider has no reset/warm-up ACK
    assert analyzed.data["analysis"]["run_evidence"]["plan_hash"] == plan["plan_hash"]
    assert analyzed.data["analysis"]["capability_manifest"]["identity_binding"]["execution_binding_status"] == "verified"


def test_sim_verify_rechecks_runtime_workspace_alignment_before_provider():
    result = SimVerifyModule().safe_run(
        mode="remote_public",
        strategy="point_cloud",
        server_host="server",
        remote_bag_path="/data/example.bag",
        remote_capture_base="/tmp/pc/run",
        input_topics=["/radar/points"],
        output_topics=["/perception/objects"],
        point_cloud_plan={
            "schema_version": "point-cloud-replay-plan.v1",
            "mode": "point_cloud",
            "status": "ready",
            "target": {"remote_bag_path": "/data/example.bag", "remote_capture_base": "/tmp/pc/run", "start_sec": 0.0, "duration_sec": 4.0, "output_topics": ["/perception/objects"]},
        },
        preflight={
            "workspace": {"arbe_root": "/home/target"},
            "runtime": {"processes": [{"pid": 5, "command": "/home/other/devel/arbe_visualization_engine"}]},
        },
    )
    assert result.ok
    assert result.data["status"] == "blocked"
    assert "runtime_process_workspace_mismatch" in result.data["diagnostics"]


def test_sim_verify_blocks_live_source_identity_conflict_before_provider():
    result = SimVerifyModule().safe_run(
        mode="remote_public",
        strategy="point_cloud",
        server_host="server",
        remote_bag_path="/data/example.bag",
        remote_capture_base="/tmp/pc/run",
        input_topics=["/radar/points"],
        output_topics=["/perception/objects"],
        point_cloud_plan={
            "schema_version": "point-cloud-replay-plan.v1",
            "mode": "point_cloud",
            "status": "ready",
            "target": {"server": {"host": "server", "user": "", "port": 22}, "remote_bag_path": "/data/example.bag", "remote_capture_base": "/tmp/pc/run", "start_sec": 0.0, "duration_sec": 4.0, "output_topics": ["/perception/objects"]},
        },
        preflight={
            "build": {"macros": {"HILMODEL": "0", "PF_BUILD_FUNTEST_SGU_INJECTION": "0"}, "binary_fingerprint": "bin"},
            "workspace": {"outer": {"head": "outer", "content_fingerprint": "outer-live"}, "algo_source": {"head": "algo", "content_fingerprint": "algo-live"}},
            "configuration": {"resolved": {"coem_name": "TEST"}},
            "runtime": {"ros_master_uri": "http://localhost:11311", "processes": [{"pid": 1}]},
        },
        source_context={"data_fingerprint": "data", "source_context_id": "stale-source"},
        execute=True,
        approved=True,
        execution_binding={"schema_version": "arbe-execution-binding.v1", "status": "approved"},
    )
    assert result.data["status"] == "blocked"
    assert "source_context_id:explicit_vs_live_preflight" in result.data["diagnostics"]
