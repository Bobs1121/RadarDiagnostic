from __future__ import annotations

from engines.arbe.execution_binding import (
    build_execution_binding,
    derive_execution_identity,
    verify_execution_binding,
)
from ai.modules.execution_binding import ExecutionBindingModule


def _identity() -> dict[str, str]:
    return {
        "data_fingerprint": "data-sha",
        "source_context_id": "source-sha",
        "binary_fingerprint": "binary-sha",
        "config_fingerprint": "config-sha",
        "session_id": "ros-session-1",
    }


def test_execution_binding_round_trip_verifies_plan_and_identity():
    plan = {"remote_bag_path": "/data/case.bag", "duration_sec": 4}
    binding = build_execution_binding(
        plan=plan,
        identity=_identity(),
        approval_id="approval-1",
        approved=True,
        run_id="attempt-1",
    )
    result = verify_execution_binding(
        binding,
        current_identity=_identity(),
        approved=True,
        plan=plan,
    )
    assert result["status"] == "verified"
    assert result["run_id"] == "attempt-1"


def test_execution_binding_blocks_identity_drift_and_plan_change():
    plan = {"remote_bag_path": "/data/case.bag", "duration_sec": 4}
    binding = build_execution_binding(
        plan=plan,
        identity=_identity(),
        approval_id="approval-1",
        approved=True,
        run_id="attempt-1",
    )
    changed = {**_identity(), "binary_fingerprint": "different-binary"}
    result = verify_execution_binding(
        binding,
        current_identity=changed,
        approved=True,
        plan={**plan, "duration_sec": 5},
    )
    assert result["status"] == "blocked"
    assert "identity_mismatch:binary_fingerprint" in result["reasons"]
    assert "execution_plan_changed" in result["reasons"]


def test_execution_binding_module_produces_binding_after_approval():
    plan = {"remote_bag_path": "/data/case.bag", "duration_sec": 4}
    pending = ExecutionBindingModule().safe_run(
        plan=plan,
        identity=_identity(),
        approved=False,
    )
    assert pending.data["status"] == "approval_required"
    result = ExecutionBindingModule().safe_run(
        plan=plan,
        identity=_identity(),
        approval_id="approval-test",
        approved=True,
        run_id="attempt-test",
    )
    assert result.ok
    assert result.data["schema_version"] == "arbe-execution-binding.v1"
    assert result.data["approval_id"] == "approval-test"


def test_execution_binding_module_blocks_incomplete_identity():
    result = ExecutionBindingModule().safe_run(
        plan={"remote_bag_path": "/data/case.bag"},
        identity={"data_fingerprint": "data"},
        approved=True,
    )
    assert result.ok
    assert result.data["status"] == "blocked"
    assert "binary_fingerprint" in result.data["missing_identity"]


def test_execution_identity_derives_source_binary_config_and_session_from_preflight():
    identity, provenance = derive_execution_identity(
        source_context={"data_fingerprint": "data"},
        preflight={
            "server": {"host": "server"},
            "workspace": {
                "outer": {"head": "outer-sha"},
                "algo_source": {"head": "algo-sha", "status": "dirty"},
            },
            "configuration": {"resolved": {"coem_name": "BYD_UKE"}},
            "build": {"binary_fingerprint": "binary-sha"},
            "runtime": {"ros_master_uri": "http://localhost:11311", "processes": [{"pid": 42}]},
        },
    )
    assert identity["data_fingerprint"] == "data"
    assert identity["binary_fingerprint"] == "binary-sha"
    assert all(identity[key] for key in ("source_context_id", "config_fingerprint", "session_id"))
    assert provenance["source_context_id"].startswith("derived:")


def test_execution_identity_conflict_is_exposed_when_live_content_hash_disagrees():
    identity, provenance = derive_execution_identity(
        source_context={"source_context_id": "stale-source", "data_fingerprint": "data"},
        preflight={
            "workspace": {
                "outer": {"head": "outer", "content_fingerprint": "outer-content"},
                "algo_source": {"head": "algo", "content_fingerprint": "algo-content"},
            },
            "configuration": {"content_fingerprint": "config-content", "resolved": {}},
            "build": {"binary_fingerprint": "binary"},
            "runtime": {"ros_master_uri": "http://localhost:11311", "processes": [{"pid": 1}]},
        },
    )
    assert identity["source_context_id"] == "stale-source"
    assert "source_context_id:explicit_vs_live_preflight" in provenance["__conflicts__"]


def test_execution_binding_module_consumes_preflight_shape_without_manual_technical_fields():
    result = ExecutionBindingModule().safe_run(
        plan={"remote_bag_path": "/data/case.bag"},
        source_context={"data_fingerprint": "data"},
        preflight={
            "server": {"host": "server"},
            "workspace": {
                "outer": {"head": "outer-sha"},
                "algo_source": {"head": "algo-sha"},
            },
            "configuration": {"resolved": {"coem_name": "BYD_UKE"}},
            "build": {"binary_fingerprint": "binary-sha"},
            "runtime": {"ros_master_uri": "http://localhost:11311", "processes": [{"pid": 42}]},
        },
        approved=True,
        approval_id="approval-preflight",
    )
    assert result.ok
    assert result.data["status"] == "approved"
    assert result.data["identity_provenance"]["binary_fingerprint"] == "preflight.build.binary_fingerprint"


def test_execution_binding_module_unwraps_remote_replay_plan_artifact(tmp_path):
    plan_path = tmp_path / "remote-plan.json"
    plan_path.write_text(
        '{"execution_plan":{"remote_bag_path":"/data/case.bag","duration_sec":4, '
        '"input_topics":["/wf/corner_radar/lgu_data_2"], '
        '"output_topics":["/corner_radar/warning_status_with_frame"]}}',
        encoding="utf-8",
    )
    result = ExecutionBindingModule().safe_run(
        plan_path=str(plan_path),
        identity=_identity(),
        approved=True,
        approval_id="approval-plan",
    )
    assert result.ok
    assert result.data["plan_hash"]
