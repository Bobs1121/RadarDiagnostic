from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from ai.agent_loop import AgentLoop
from ai.capability.module_bridge import build_module_tool_registry
from ai.capability.pi_tool_bridge import available_capabilities
from ai.modules.pi import PiModule
from engines.diagnostic_report import build_diagnostic_report, write_diagnostic_report
from engines.analysis_ledger import AnalysisLedger
from engines.evidence_query import build_evidence_query


def _bundle() -> dict:
    return {
        "schema_version": "diagnosis-bundle.v1",
        "case": {"case_id": "CASE-1", "data_id": "demo.bag", "bag": "/data/demo.bag"},
        "provenance": {"project": "demo", "source_context_id": "source-1", "source_snapshot_hash": "src-1"},
        "source_context": {"source_context_id": "source-1", "source_snapshot_hash": "src-1"},
        "code_evidence": {"status": "ready"},
        "alarm_events": [
            {
                "event_id": "event-a",
                "function": "FUNC_A_L",
                "radar_id": 3,
                "source": "algorithm_output",
                "start_time_sec": 1.0,
                "end_time_sec": 2.0,
                "first_on_frame": 100,
                "selected_target": {"obj_id": 44},
                "frame_evidence": [
                    {"frame_id": 99, "ego": {"speed": 2.0}, "objects": [{"obj_id": 44}]},
                    {"frame_id": 100, "ego": {"speed": 2.5}, "objects": [{"obj_id": 44}]},
                ],
                "breakpoint_pack": {
                    "breakpoints": [{"function": "FuncA", "condition": "frame_counter == 100"}],
                },
            },
            {
                "event_id": "event-b",
                "function": "FUNC_A_L",
                "radar_id": 3,
                "source": "algorithm_output",
                "start_time_sec": 5.0,
                "end_time_sec": 6.0,
                "first_on_frame": 200,
                "frame_evidence": [{"frame_id": 200}],
            },
        ],
    }


def _viewer() -> dict:
    return {
        "schema_version": "viewer-model.v1",
        "data_name": "demo.bag",
        "case": {"case_id": "CASE-1", "bag": "/data/demo.bag"},
        "events": [
            {
                "event_id": "event-a",
                "identity": {"function": "FUNC_A_L", "side": "L", "radar_id": 3, "radar_name": "Rear_Left"},
                "alarm": {"start_time_sec": 1.0, "end_time_sec": 2.0, "sample_count": 3},
                "frame": {
                    "target_frame": 100,
                    "target_frame_source": "first_on_frame",
                    "selection_confidence": "observed_event_field",
                },
                "ego": {"fields": [{"code_token": "g_ego.speed", "value": 2.5}]},
                "target": {
                    "selected": True,
                    "obj_id": 44,
                    "fields": [{"code_token": "objInfo->trcOutData[i].objID", "value": 44}],
                    "index_mapping": {"algorithm_object_index": 0, "confidence": "observed"},
                },
                "timeline": {"frames": [{"frame_id": 99}, {"frame_id": 100}]},
                "code": {"call_chain": ["FuncA"], "conditions": [{"token": "gate", "line": 10}]},
                "breakpoint_pack": {"gdb_commands": ["break FuncA"]},
            },
        ],
    }


def test_evidence_query_filters_before_event_index_and_keeps_missing_field_explicit():
    payload = build_evidence_query(
        bundle=_bundle(),
        viewer_model=_viewer(),
        function="FUNC_A_L",
        event_index=1,
        fields=["target.fields", "target.missing", "ego.fields"],
        max_frames=2,
    )

    assert payload["status"] == "ready"
    assert payload["events"][0]["event_id"] == "event-b"
    assert payload["events"][0]["facts"][1]["status"] == "not_available"
    assert payload["events"][0]["details"] == {"event_id": "event-b"}
    schema = json.loads(Path("contracts/evidence-query.v1.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(payload)


def test_evidence_query_without_fields_returns_default_scene_facts_for_conversation():
    payload = build_evidence_query(bundle=_bundle(), viewer_model=_viewer(), event_id="event-a")
    facts = {item["path"]: item for item in payload["events"][0]["facts"]}
    assert "ego" in facts
    assert "target" in facts
    assert "frame" in facts


def test_evidence_query_bounded_runtime_fields_preserve_structured_output_tokens():
    runtime_fields = [{"token": f"debug_noise_{index}", "value": index} for index in range(40)]
    runtime_fields.extend([
        {"token": "objInfo->trcOutData[i].objFctaWarningFlag", "value": 4},
        {"token": "objInfo->trcOutData[i].fInterX", "value": 8.3},
    ])
    payload = build_evidence_query(
        bundle=_bundle(), viewer_model=_viewer(), event_id="event-a",
        runtime_evidence={
            "schema_version": "runtime-case-evidence.v1",
            "run": {"run_id": "r", "data_fingerprint": "d", "source_context_id": "s"},
            "evidence_layers": [],
            "observations": [{
                "layer": "gdb_observation",
                "identity": {"event_id": "event-a", "radar_id": 3, "frame_id": 100},
                "fields": runtime_fields,
            }],
        },
        max_field_rows=8,
    )
    fields = payload["events"][0]["runtime_observations"][0]["fields"]
    fields = fields["items"] if isinstance(fields, dict) else fields
    tokens = {item["token"] for item in fields}
    assert "objInfo->trcOutData[i].objFctaWarningFlag" in tokens
    assert "objInfo->trcOutData[i].fInterX" in tokens


def test_evidence_query_uses_viewer_identity_when_bundle_event_lacks_side():
    payload = build_evidence_query(
        bundle=_bundle(), viewer_model=_viewer(), function="FUNC_A_L", side="L"
    )
    assert payload["matched_event_count"] == 2
    assert all(item["summary"]["side"] == "L" for item in payload["events"])


def test_evidence_query_accepts_a_function_namespace_prefix_without_feature_rules():
    payload = build_evidence_query(bundle=_bundle(), function="FUNC_A")
    assert payload["matched_event_count"] == 2


def test_diagnostic_report_projects_selected_event_and_optional_ai_as_inference(tmp_path: Path):
    report = build_diagnostic_report(
        bundle=_bundle(),
        viewer_model=_viewer(),
        function="FUNC_A_L",
        event_id="event-a",
        analysis={"classification": {"task_type": "diagnose"}, "panel_result": {"final_verdict": "candidate"}},
    )
    assert report["schema_version"] == "diagnostic-report.v1"
    assert report["status"] == "ready"
    assert report["selected_event"]["summary"]["target_obj_id"] == 44
    assert report["event_index"][0]["event_id"] == "event-a"
    assert report["diagnosis"]["status"].startswith("inference")
    assert report["diagnosis"]["interpretation_policy"]

    paths = write_diagnostic_report(report, tmp_path)
    assert {Path(path).name for path in paths} == {
        "diagnostic-report.json", "diagnostic-report.md", "diagnostic-report.html"
    }
    schema = json.loads(Path("contracts/diagnostic-report.v1.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(json.loads((tmp_path / "diagnostic-report.json").read_text(encoding="utf-8")))


def test_diagnostic_report_blocks_mixed_source_context(tmp_path: Path):
    report = build_diagnostic_report(
        bundle=_bundle(),
        code_context={
            "schema_version": "code-context.v1",
            "status": "ready",
            "source_context": {"source_snapshot_hash": "different-source"},
        },
    )
    assert report["status"] == "blocked"
    assert "code_context_source_snapshot_mismatch" in report["diagnostics"]
    assert report["conflicts"][0]["field"] == "source_snapshot_hash"


def test_new_capabilities_are_pi_visible_and_composable():
    catalog = available_capabilities()
    assert "evidence-query" in catalog
    assert "diagnosis-report" in catalog
    registry = build_module_tool_registry(names=["evidence-query", "diagnosis-report"])
    state = AgentLoop(registry).run([
        {"tool": "evidence-query", "params": {"bundle": _bundle(), "function": "FUNC_A_L", "event_id": "event-a", "fields": ["target.obj_id"]}},
        {"tool": "diagnosis-report", "params": {"bundle": _bundle(), "event_id": "event-a"}},
    ])
    assert state.status == "completed"
    assert state.steps[0].result["data"]["events"][0]["event_id"] == "event-a"
    assert state.steps[1].result["data"]["schema_version"] == "diagnostic-report.v1"


def test_pi_module_records_a_dialogue_turn_in_analysis_ledger(tmp_path: Path, monkeypatch):
    class FakeBridge:
        def prompt(self, question):
            return {"status": "ok", "answer": "已完成", "event_count": 2, "message": "agent_settled"}

    module = PiModule()
    monkeypatch.setattr(module, "_build_bridge", lambda case_dir, kwargs: FakeBridge())
    result = module.run(
        question="查看这条数据的报警事件",
        case_dir=str(tmp_path),
        project_root=str(tmp_path),
        analysis_ledger_root=str(tmp_path / "ledger"),
    )
    assert result.ok is True
    run_path = Path(result.data["analysis_run_path"])
    assert run_path.is_file()
    run = json.loads(run_path.read_text(encoding="utf-8"))
    assert len(run["steps"]) == 1
    assert run["steps"][0]["stage"] == "dialogue"

    resumed = PiModule()
    monkeypatch.setattr(resumed, "_build_bridge", lambda case_dir, kwargs: FakeBridge())
    resumed_result = resumed.run(
        question="继续查看目标属性",
        case_dir=str(tmp_path),
        project_root=str(tmp_path),
        analysis_run_id=run["run_id"],
        analysis_ledger_root=str(tmp_path / "ledger"),
    )
    assert resumed_result.ok is True
    resumed_run = json.loads(run_path.read_text(encoding="utf-8"))
    assert len(resumed_run["steps"]) == 2


def test_pi_module_binds_auto_run_to_context_identity(tmp_path: Path, monkeypatch):
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    (case_dir / "diagnosis_bundle.json").write_text(json.dumps({
        "schema_version": "diagnosis-bundle.v1",
        "case": {"case_id": "CASE-1", "bag": "/data/demo.bag"},
        "provenance": {"project": "demo", "source_context_id": "ctx", "source_snapshot_hash": "src"},
        "alarm_events": [],
    }), encoding="utf-8")

    class FakeBridge:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    import ai.pi_bridge as pi_bridge
    monkeypatch.setattr(pi_bridge, "PiBridge", FakeBridge)
    module = PiModule()
    kwargs = {
        "project_root": str(tmp_path),
        "analysis_ledger_root": str(tmp_path / "ledger"),
    }
    module._prepare_analysis_run(case_dir=str(case_dir), goal="bind", kwargs=kwargs)
    bridge = module._build_bridge(str(case_dir), kwargs)
    assert isinstance(bridge, FakeBridge)
    run = json.loads(Path(module._analysis_run["artifact_path"]).read_text(encoding="utf-8"))
    assert run["binding"]["source_context_id"] == "ctx"
    assert run["binding"]["source_snapshot_hash"] == "src"
    assert any(item.get("kind") == "diagnosis_bundle_path" for item in run["artifacts"])


def test_pi_module_records_tool_end_as_visible_analysis_step(tmp_path: Path):
    ledger = AnalysisLedger(tmp_path / "ledger")
    run = ledger.create_run(goal={"question": "record tool"}, owner="pi")
    module = PiModule()
    module._analysis_run = run
    module._analysis_ledger_root = tmp_path / "ledger"
    module._on_event({
        "type": "tool_execution_end",
        "toolName": "alert-timeline",
        "result": {"status": "ok", "artifacts": [{"path": str(tmp_path / "timeline.json")}]},
    })
    persisted = ledger.read_run(run["run_id"])
    assert len(persisted["steps"]) == 1
    assert persisted["steps"][0]["stage"] == "tool-alert-timeline"
