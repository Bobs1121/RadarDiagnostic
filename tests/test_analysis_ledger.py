from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from ai.capability.registry import capability_catalog
from ai.modules import MODULE_REGISTRY
from ai.modules.analysis_ledger import (
    AnalysisClaimAppendModule,
    AnalysisRunCreateModule,
    AnalysisRunReadModule,
    AnalysisRunUpdateModule,
    AnalysisStepRecordModule,
)
from ai.modules.analysis_collaboration import (
    AnalysisHypothesisRecordModule,
    AnalysisUserObservationModule,
    DebugExperimentRecordModule,
)
from engines.analysis_ledger import AnalysisLedger, LedgerConflict


def _create(ledger: AnalysisLedger, run_id: str = "run-test") -> dict:
    return ledger.create_run(
        run_id=run_id,
        owner="tester",
        goal={
            "question": "判断报警链路并逐步准备 debug",
            "customer_claim": "客户认为误报警",
        },
        binding={
            "project_id": "cr60-light",
            "variant_id": "BYD_UKE_03_QZH",
            "data_fingerprint": "bag-sha",
            "source_fingerprint": "source-sha",
        },
        artifact_refs=[{"path": "/tmp/intake.json", "schema_version": "cr60-analysis-intake.v1"}],
    )


def test_create_and_read_analysis_run(tmp_path: Path):
    ledger = AnalysisLedger(tmp_path / "ledger")
    created = _create(ledger)

    assert created["schema_version"] == "analysis-run.v1"
    assert created["status"] == "created"
    assert created["goal"]["question"]
    assert Path(created["artifact_path"]).is_file()
    events = (Path(created["run_dir"]) / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(events) == 1
    assert json.loads(events[0])["event"] == "run_created"

    read = ledger.read_run("run-test")
    assert read["summary"]["step_count"] == 0
    assert read["summary"]["claim_count"] == 0


def test_duplicate_run_and_step_lifecycle_conflicts(tmp_path: Path):
    ledger = AnalysisLedger(tmp_path / "ledger")
    _create(ledger)
    with pytest.raises(LedgerConflict):
        _create(ledger)

    step = ledger.begin_step("run-test", step_id="step-event-map", stage="event-map")
    assert step["status"] == "running"
    with pytest.raises(LedgerConflict):
        ledger.begin_step("run-test", step_id="step-event-map", stage="event-map")

    completed = ledger.complete_step(
        "run-test",
        "step-event-map",
        status="partial",
        output_artifact_refs=[{"path": "/tmp/events.json"}],
        observations=[{"statement": "发现多个报警事件"}],
        gaps=[{"code": "can_tx_unobserved", "critical": True}],
        conflicts=[{"code": "algorithm_vs_raw_frame"}],
        user_visible_summary="已定位算法报警候选，但最终 CAN Tx 仍缺失",
        next_action_candidates=[{"action": "build-event-code-path"}],
        metrics={"bag_full_read_count": 1},
    )
    assert completed["status"] == "partial"
    assert completed["duration_sec"] is not None
    with pytest.raises(LedgerConflict):
        ledger.complete_step("run-test", "step-event-map")

    run = ledger.read_run("run-test")
    assert run["status"] == "partial"
    assert run["summary"]["critical_gap_count"] == 1
    assert run["metrics"]["time_to_first_useful_clue_sec"] is not None
    assert run["steps"][0]["summary"].startswith("已定位")
    assert run["metrics"]["bag_full_read_count"] == 1

    updated = ledger.update_run(
        "run-test",
        current_stage="debug-ready",
        metrics={"time_to_debug_ready_sec": 12.5, "gdb_stop_count": 2},
        metric_mode="merge",
    )
    assert updated["current_stage"] == "debug-ready"
    assert updated["metrics"]["time_to_debug_ready_sec"] == 12.5
    assert updated["metrics"]["gdb_stop_count"] == 2
    incremented = ledger.update_run(
        "run-test", metrics={"gdb_stop_count": 3}, metric_mode="increment"
    )
    assert incremented["metrics"]["gdb_stop_count"] == 5


def test_claim_accuracy_gates_and_step_linking(tmp_path: Path):
    ledger = AnalysisLedger(tmp_path / "ledger")
    _create(ledger)
    ledger.begin_step("run-test", step_id="step-scene", stage="scene-and-target")

    with pytest.raises(ValueError, match="AI-created claims cannot be marked observed"):
        ledger.append_claim(
            "run-test",
            scope="target",
            statement="目标 44 在报警帧存在",
            status="observed",
            created_by="ai",
            evidence_refs=[{"path": "/tmp/frame.json"}],
        )
    with pytest.raises(ValueError, match="observed claims require"):
        ledger.append_claim(
            "run-test",
            scope="target",
            statement="目标 44 在报警帧存在",
            status="observed",
            created_by="tool",
        )

    observed = ledger.append_claim(
        "run-test",
        claim_id="claim-target-44",
        step_id="step-scene",
        scope="target",
        statement="当前 artifact 在 frameID=47877 记录了 objID=44",
        status="observed",
        created_by="tool",
        evidence_refs=[{"path": "/tmp/frame.json", "frame_id": 47877}],
        binding={"radar_id": 2, "frame_id": 47877, "obj_id": 44},
    )
    inferred = ledger.append_claim(
        "run-test",
        scope="root-cause",
        statement="当前证据更接近 situation/feature 层问题",
        status="inferred",
        created_by="ai",
        evidence_refs=[{"ref": "claim-target-44"}],
        assumptions=["当前目标身份映射有效"],
    )

    assert observed["status"] == "observed"
    assert inferred["status"] == "inferred"
    result = ledger.read_run("run-test", include_entities=True)
    assert result["summary"]["claim_count"] == 2
    assert len(result["entities"]["claims"]) == 2
    assert result["entities"]["steps"][0]["claim_refs"][0]["id"] == "claim-target-44"


def test_hypothesis_state_history_and_user_confirmation_gate(tmp_path: Path):
    ledger = AnalysisLedger(tmp_path / "ledger")
    _create(ledger)
    hypothesis = ledger.upsert_hypothesis(
        "run-test",
        hypothesis_id="hyp-geometry",
        category="situation",
        statement="目标几何投影与当前 ROI 不一致",
        status="open",
        rank=1,
        confidence_band="low",
        required_evidence=["same-frame runtime ROI"],
        actor="tool",
    )
    updated = ledger.upsert_hypothesis(
        "run-test",
        hypothesis_id="hyp-geometry",
        status="supported",
        reason="GDB 同帧多边形已获得，但输出链仍缺失",
        actor="ai",
        supporting_claim_refs=[{"path": "/tmp/gdb.json"}],
    )
    assert updated["status"] == "supported"
    assert len(updated["history"]) == 2
    assert updated["history"][-1]["status_before"] == "open"
    with pytest.raises(ValueError, match="only a user"):
        ledger.upsert_hypothesis(
            "run-test", hypothesis_id="hyp-geometry", status="confirmed_by_user", actor="ai"
        )
    confirmed = ledger.upsert_hypothesis(
        "run-test", hypothesis_id="hyp-geometry", status="confirmed_by_user", actor="user", reason="用户确认"
    )
    assert confirmed["status"] == "confirmed_by_user"
    run = ledger.read_run("run-test")
    assert run["summary"]["hypothesis_count"] == 1
    assert run["hypotheses"][0]["status"] == "confirmed_by_user"
    root = Path(__file__).resolve().parents[1]
    hypothesis_schema = json.loads((root / "contracts" / "hypothesis.v1.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(hypothesis_schema).validate(confirmed)


def test_experiment_requires_plan_before_result_and_preserves_updates(tmp_path: Path):
    ledger = AnalysisLedger(tmp_path / "ledger")
    _create(ledger)
    with pytest.raises(ValueError, match="create an experiment as planned"):
        ledger.record_experiment(
            "run-test", question="读取报警帧局部变量", method="gdb", status="completed"
        )
    plan = ledger.record_experiment(
        "run-test",
        question="读取报警帧局部变量",
        method="gdb",
        status="planned",
        target={"event_id": "event-1", "frame_id": 100, "radar_id": 2, "object_id": 44},
        expected_discrimination=["若 fTTMY 不满足则优先排查 situation"],
        actor="tool",
    )
    result = ledger.record_experiment(
        "run-test",
        experiment_id=plan["experiment_id"],
        status="partial",
        observations=[{"kind": "gdb", "statement": "fTTMY 未找到"}],
        conclusion_delta=[{"hypothesis_id": "hyp-geometry", "effect": "still_open"}],
        disturbance={"status": "suspected"},
        actor="tool",
    )
    assert result["status"] == "partial"
    assert result["method"] == "gdb"
    assert len(result["updates"]) == 2
    run = ledger.read_run("run-test")
    assert run["summary"]["experiment_count"] == 1
    assert run["experiments"][0]["status"] == "partial"
    root = Path(__file__).resolve().parents[1]
    experiment_schema = json.loads((root / "contracts" / "debug-experiment.v1.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(experiment_schema).validate(result)


def test_user_observation_is_separate_from_runtime_evidence(tmp_path: Path):
    ledger = AnalysisLedger(tmp_path / "ledger")
    _create(ledger)
    observation = ledger.append_user_observation(
        "run-test",
        kind="manual_vscode",
        summary="VSCode 停在 adasFunc.c:10140，看到 i=0",
        content="用户手工观察：objID=44",
        target={"frame_id": 100, "radar_id": 2, "object_id": 44},
        artifact_refs=[{"path": "/tmp/vscode.txt"}],
    )
    assert observation["schema_version"] == "user-observation.v1"
    assert observation["runtime_eligible"] is False
    assert observation["evidence_layer"] == "user_observation"
    read = ledger.read_run("run-test", include_entities=True)
    assert read["summary"]["user_observation_count"] == 1
    assert read["entities"]["user_observations"][0]["created_by"] == "user"
    root = Path(__file__).resolve().parents[1]
    observation_schema = json.loads((root / "contracts" / "user-observation.v1.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(observation_schema).validate(observation)


def test_concurrent_step_writes_are_serialized(tmp_path: Path):
    ledger = AnalysisLedger(tmp_path / "ledger")
    _create(ledger)

    def begin(index: int) -> str:
        payload = ledger.begin_step(
            "run-test",
            step_id=f"step-{index}",
            stage=f"stage-{index}",
        )
        return payload["step_id"]

    with ThreadPoolExecutor(max_workers=6) as pool:
        ids = list(pool.map(begin, range(12)))

    assert len(set(ids)) == 12
    run = ledger.read_run("run-test")
    assert run["summary"]["step_count"] == 12
    assert run["event_sequence"] == 13
    events = (Path(run["run_dir"]) / "events.jsonl").read_text(encoding="utf-8").splitlines()
    sequences = [json.loads(line)["sequence"] for line in events]
    assert sequences == list(range(1, 14))


def test_ledger_modules_are_pi_registered_and_compose(tmp_path: Path):
    names = {
        "analysis-run-create": AnalysisRunCreateModule,
        "analysis-run-read": AnalysisRunReadModule,
        "analysis-run-update": AnalysisRunUpdateModule,
        "analysis-step-record": AnalysisStepRecordModule,
        "analysis-claim-append": AnalysisClaimAppendModule,
        "analysis-hypothesis-record": AnalysisHypothesisRecordModule,
        "debug-experiment-record": DebugExperimentRecordModule,
        "analysis-user-observation": AnalysisUserObservationModule,
    }
    catalog = {item["name"]: item for item in capability_catalog()}
    for name, module_cls in names.items():
        assert MODULE_REGISTRY[name] is module_cls
        assert catalog[name]["expose_to_pi"] is True
        assert catalog[name]["requires_approval"] is False

    create = AnalysisRunCreateModule(project_root=tmp_path).safe_run(
        ledger_root="runs",
        run_id="run-module",
        question="逐步分析一条报警数据",
        binding={"data_fingerprint": "data-1", "source_fingerprint": "source-1"},
    )
    assert create.ok is True

    begin = AnalysisStepRecordModule(project_root=tmp_path).safe_run(
        ledger_root="runs",
        action="begin",
        run_id="run-module",
        step_id="step-static",
        stage="event-map",
        tool_calls=[{"name": "cr60-precheck"}],
    )
    assert begin.ok is True

    complete = AnalysisStepRecordModule(project_root=tmp_path).safe_run(
        ledger_root="runs",
        action="complete",
        run_id="run-module",
        step_id="step-static",
        status="completed",
        observations=[{"statement": "发现 2 个报警事件"}],
        user_visible_summary="已形成事件地图",
    )
    assert complete.ok is True

    claim = AnalysisClaimAppendModule(project_root=tmp_path).safe_run(
        ledger_root="runs",
        run_id="run-module",
        step_id="step-static",
        scope="event",
        statement="当前数据存在 2 个算法报警事件",
        status="observed",
        created_by="tool",
        evidence_refs=[{"path": "/tmp/events.json"}],
    )
    assert claim.ok is True

    update = AnalysisRunUpdateModule(project_root=tmp_path).safe_run(
        ledger_root="runs",
        run_id="run-module",
        current_stage="debug-ready",
        metrics={"time_to_debug_ready_sec": 3.2},
    )
    assert update.ok is True
    assert update.data["metrics"]["time_to_debug_ready_sec"] == 3.2

    hypothesis = AnalysisHypothesisRecordModule(project_root=tmp_path).safe_run(
        ledger_root="runs",
        run_id="run-module",
        hypothesis_id="hyp-module",
        category="perception",
        statement="目标对象属性需要进一步核实",
        status="open",
    )
    assert hypothesis.ok is True

    experiment = DebugExperimentRecordModule(project_root=tmp_path).safe_run(
        ledger_root="runs",
        action="plan",
        run_id="run-module",
        question="获取报警帧的 GDB 局部变量",
        method="gdb",
        target={"frame_id": 47877, "radar_id": 2, "object_id": 44},
        hypothesis_refs=[{"path": hypothesis.data["artifact_path"]}],
    )
    assert experiment.ok is True

    observation = AnalysisUserObservationModule(project_root=tmp_path).safe_run(
        ledger_root="runs",
        run_id="run-module",
        kind="manual_vscode",
        summary="用户确认断点停在目标循环",
        experiment_id=experiment.data["experiment_id"],
    )
    assert observation.ok is True
    assert observation.data["runtime_eligible"] is False

    read = AnalysisRunReadModule(project_root=tmp_path).safe_run(
        ledger_root="runs",
        run_id="run-module",
        include_entities=True,
    )
    assert read.ok is True
    assert read.data["summary"]["step_count"] == 1
    assert read.data["summary"]["claim_count"] == 1
    assert read.data["summary"]["hypothesis_count"] == 1
    assert read.data["summary"]["experiment_count"] == 1
    assert read.data["summary"]["user_observation_count"] == 1


def test_analysis_step_cli_wiring():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers()
    AnalysisStepRecordModule.register_cli(sub)
    args = parser.parse_args(
        [
            "analysis-step-record",
            "--action",
            "begin",
            "--run-id",
            "run-cli",
            "--stage",
            "event-map",
            "--tool-calls",
            '[{"name":"cr60-precheck"}]',
        ]
    )
    assert args._module_cls is AnalysisStepRecordModule
    assert args.tool_calls[0]["name"] == "cr60-precheck"


def test_new_ledger_contracts_are_valid_json():
    root = Path(__file__).resolve().parents[1]
    names = [
        "analysis-run.v1.schema.json",
        "analysis-step.v1.schema.json",
        "claim.v1.schema.json",
        "hypothesis.v1.schema.json",
        "debug-experiment.v1.schema.json",
        "user-observation.v1.schema.json",
        "analysis-ledger-event.v1.schema.json",
    ]
    for name in names:
        payload = json.loads((root / "contracts" / name).read_text(encoding="utf-8"))
        assert payload["$schema"].endswith("2020-12/schema")


def test_created_run_step_and_claim_validate_against_contracts(tmp_path: Path):
    ledger = AnalysisLedger(tmp_path / "ledger")
    run = _create(ledger)
    step = ledger.begin_step("run-test", step_id="step-contract", stage="event-map")
    step = ledger.complete_step(
        "run-test",
        "step-contract",
        observations=[{"statement": "event map ready"}],
    )
    claim = ledger.append_claim(
        "run-test",
        step_id="step-contract",
        scope="event",
        statement="one event was observed",
        status="observed",
        created_by="tool",
        evidence_refs=[{"path": "/tmp/events.json"}],
    )
    root = Path(__file__).resolve().parents[1]
    pairs = [
        (run, "analysis-run.v1.schema.json"),
        (step, "analysis-step.v1.schema.json"),
        (claim, "claim.v1.schema.json"),
    ]
    for payload, schema_name in pairs:
        schema = json.loads((root / "contracts" / schema_name).read_text(encoding="utf-8"))
        Draft202012Validator(schema).validate(payload)


def test_run_update_binds_context_and_rejects_identity_drift(tmp_path: Path):
    ledger = AnalysisLedger(tmp_path / "ledger")
    _create(ledger)
    updated = ledger.update_run(
        "run-test",
        binding={"source_snapshot_hash": "source-1", "data_fingerprint": "bag-sha"},
        artifact_refs=[{"kind": "bundle", "path": "/tmp/bundle.json"}],
    )
    assert updated["binding"]["source_snapshot_hash"] == "source-1"
    assert any(item.get("kind") == "bundle" for item in updated["artifacts"])
    with pytest.raises(LedgerConflict):
        ledger.update_run("run-test", binding={"source_snapshot_hash": "other-source"})
