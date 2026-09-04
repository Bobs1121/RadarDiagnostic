# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import io
import time

from ai.capability.pi_tool_bridge import available_capabilities, invoke_capability
from ai.capability.module_bridge import ModuleToolAdapter
from ai.capability.registry import module_input_schema
from ai.pi_bridge import DEFAULT_PI_SYSTEM_PROMPT, PiBridge
from scripts.gen_pi_extension import generate
from ai.modules.pi import PiModule, discover_case_artifacts, _select_pi_tools, _resolve_question_event_filter, _build_evidence_anchor


def test_pi_catalog_contains_leaf_modules_and_excludes_recursive_roots():
    catalog = available_capabilities()
    assert "pi-context" in catalog
    assert "code-gdb-plan" in catalog
    assert "gdb-service" in catalog
    assert "pi" not in catalog
    assert "agent-loop" not in catalog
    assert "agent-repl" not in catalog
    assert "ask_user" not in catalog


def test_pi_catalog_uses_one_canonical_code_query_entry():
    catalog = available_capabilities()
    assert "code-analyze" in catalog
    assert "code-query" not in catalog
    assert "find-code-definition" not in catalog
    assert "extract-ast-dependency" not in catalog


def test_legacy_module_pi_schema_is_inferred_from_run_and_cli_contracts():
    schema = module_input_schema(__import__("ai.modules", fromlist=["MODULE_REGISTRY"]).MODULE_REGISTRY["bsd-data-bridge"])
    assert "mode" in schema["properties"]
    assert "mf4_path" in schema["properties"]
    assert "output_dir" in schema["properties"]
    assert "mode" in schema["required"]


def test_module_bridge_reuses_existing_from_cli_args_constructor_mapping():
    class _LegacyModule:
        name = "legacy"
        description = "legacy"

        def __init__(self, value=""):
            self.value = value

        @classmethod
        def from_cli_args(cls, args):
            return cls(getattr(args, "value", ""))

        def safe_run(self, **params):
            return type("Result", (), {"ok": True, "data": {"value": self.value, **params}, "message": "ok", "artifacts": []})()

        def run(self, *, mode: str, **_):
            return self.safe_run(mode=mode)

    result = ModuleToolAdapter(_LegacyModule).safe_execute({"mode": "x", "value": "constructor-input"})
    assert result["status"] == "ok"
    assert result["data"]["value"] == "constructor-input"


def test_pi_bridge_dispatches_module_with_json_envelope():
    result = invoke_capability(
        "pi-context",
        {"case_dir": "/data/case-1", "project_id": "demo"},
    )
    assert result["status"] == "ok"
    assert result["data"]["schema_version"] == "pi-orchestration-context.v1"


def test_pi_bridge_keeps_gdb_execution_approval_gated():
    result = invoke_capability(
        "gdb-service",
        {
            "target": {"pid": 42, "program": "/tmp/program"},
            "commands": ["p frame_counter"],
            "execute": True,
        },
    )
    assert result["status"] == "error"
    assert result["data"]["approval_required"] is True


def test_generated_pi_extension_forwards_params_through_one_bridge():
    ts = generate([
        {
            "name": "pi-context",
            "kind": "module",
            "description": "context",
            "parameters": {"type": "object", "properties": {}},
            "expose_to_pi": True,
        },
        {
            "name": "pi",
            "kind": "module",
            "description": "root",
            "parameters": {"type": "object", "properties": {}},
            "expose_to_pi": False,
        },
        {
            "name": "ask_user",
            "kind": "tool",
            "description": "internal",
            "parameters": {"type": "object", "properties": {}},
            "expose_to_pi": False,
        },
    ])
    assert "fileURLToPath" in ts
    assert "pythonExecutable" in ts
    assert "ai.capability.pi_tool_bridge" in ts
    assert '"--params", JSON.stringify(params ?? {})' in ts
    assert '"cli.py"' not in ts
    assert ts.count('name: "pi-context"') == 1
    assert 'name: "pi"' not in ts
    assert 'name: "ask_user"' not in ts
    json.dumps(ts)


def test_pi_bridge_explicitly_loads_project_extension_and_disables_builtin_tools(tmp_path, monkeypatch):
    extension = tmp_path / ".pi" / "extensions" / "radar-capabilities.ts"
    extension.parent.mkdir(parents=True)
    extension.write_text("export default () => {};", encoding="utf-8")
    calls = []

    class _FakeProcess:
        pass

    def fake_popen(command, **kwargs):
        calls.append((command, kwargs))
        return _FakeProcess()

    monkeypatch.setattr("ai.pi_bridge._find_pi", lambda: "pi")
    monkeypatch.setattr("ai.pi_bridge.subprocess.Popen", fake_popen)
    bridge = PiBridge(
        provider="test-provider",
        project_root=str(tmp_path),
        extension_path=str(extension),
        auto_generate_extension=False,
        allow_builtin_tools=False,
    )
    bridge._spawn()
    command = calls[0][0]
    assert "--extension" in command
    assert str(extension) in command
    assert "--no-builtin-tools" in command
    assert "--append-system-prompt" in command


def test_pi_bridge_uses_persistent_session_id_instead_of_ephemeral_mode(tmp_path, monkeypatch):
    extension = tmp_path / "radar-capabilities.ts"
    extension.write_text("export default () => {};", encoding="utf-8")
    calls = []

    class _FakeProcess:
        pass

    monkeypatch.setattr("ai.pi_bridge._find_pi", lambda: "pi")
    monkeypatch.setattr("ai.pi_bridge.subprocess.Popen", lambda command, **kwargs: calls.append(command) or _FakeProcess())
    bridge = PiBridge(
        provider="test-provider",
        project_root=str(tmp_path),
        extension_path=str(extension),
        auto_generate_extension=False,
        session_dir=str(tmp_path / "sessions"),
        session_id="analysis-run-1",
    )
    bridge._spawn()
    command = calls[0]
    assert "--session-id" in command
    assert "analysis-run-1" in command
    assert "--no-session" not in command


def test_pi_bridge_context_prompt_is_compact_and_read_only():
    bridge = PiBridge(
        load_project_extension=False,
        context={
            "schema_version": "pi-orchestration-context.v1",
            "status": "partial",
            "run_id": "run-1",
            "context_fingerprint": "context-hash",
            "project": {"variant_id": "demo"},
            "data": {"root": "/data", "cases": [{"case_id": "x"}]},
            "source": {"source_context_fingerprint": "source-hash"},
            "build": {"large": "omitted"},
            "runtime": {},
            "policy": {"execution": "plan_only"},
            "artifacts": [],
            "freshness": {},
            "missing": ["code_branch"],
            "conflicts": [],
            "diagnostics": [],
        },
    )
    prompt = bridge._context_system_prompt()
    assert "PiRunContext" in prompt
    assert "source-hash" in prompt
    assert "只能追加工具 artifact" in prompt


def test_pi_bridge_rejects_unversioned_explicit_context():
    bridge = PiBridge(load_project_extension=False, context={"status": "ready"})
    try:
        bridge._context_system_prompt()
    except ValueError as exc:
        assert "schema_version" in str(exc)
    else:
        raise AssertionError("unversioned context must fail closed")


def test_pi_bridge_timeout_is_bounded_when_stdout_has_no_event(monkeypatch):
    class _BlockingStdout:
        def __iter__(self):
            return self

        def __next__(self):
            time.sleep(2)
            raise StopIteration

    class _FakeProcess:
        pid = None
        stdin = io.StringIO()
        stdout = _BlockingStdout()

        def kill(self):
            return None

    process = _FakeProcess()
    bridge = PiBridge(load_project_extension=False)
    monkeypatch.setattr(bridge, "_spawn", lambda: process)
    started = time.monotonic()
    result = bridge.prompt("no output", timeout=0.05)
    elapsed = time.monotonic() - started
    assert result["status"] == "timeout"
    assert elapsed < 1.0


def test_pi_case_discovery_uses_batch_manifest_for_split_viewer_artifact(tmp_path):
    batch = tmp_path / "batch"
    case = batch / "cases" / "case-1"
    data = batch / "data" / "case-1"
    case.mkdir(parents=True)
    data.mkdir(parents=True)
    (case / "diagnosis_bundle.json").write_text("{}", encoding="utf-8")
    (data / "viewer-model.json").write_text("{}", encoding="utf-8")
    (data / "runtime_schema.json").write_text("{}", encoding="utf-8")
    (batch / "batch-index.json").write_text(
        json.dumps({"datasets": [{"case_id": "case-1", "data_id": "case-1", "model": "./data/case-1/viewer-model.json"}]}),
        encoding="utf-8",
    )
    discovered = discover_case_artifacts(str(case))
    assert discovered["viewer_model_path"].endswith("data\\case-1\\viewer-model.json")
    assert discovered["runtime_schema_path"].endswith("data\\case-1\\runtime_schema.json")
    assert discovered["batch_index_path"].endswith("batch-index.json")


def test_pi_tool_allowlist_is_bounded_and_live_catalog_filtered():
    selected = _select_pi_tools(
        question="诊断 FCTA_R 报警帧目标和自车属性，结合运行时公共/GDB证据并给出代码链路",
        case_dir="D:/case-1",
        batch="",
        interactive=False,
    )
    assert selected is not None
    assert "evidence-query" in selected
    assert "event-code-path" in selected
    assert "diagnosis-report" in selected
    assert "code-context-refresh" in selected
    assert "code-learn" in selected
    assert "arbe-preflight" in selected
    assert "runtime-evidence-compose" in selected
    assert "analysis-run-read" in selected
    assert "analysis-hypothesis-record" in selected
    assert "debug-experiment-record" in selected
    assert len(selected) < len(available_capabilities())


def test_pi_prompt_requires_current_source_chain_before_code_reasoning():
    assert "固定功能模板" in DEFAULT_PI_SYSTEM_PROMPT
    assert "caller/callee" in DEFAULT_PI_SYSTEM_PROMPT
    assert "code-analyze/event-code-path" in DEFAULT_PI_SYSTEM_PROMPT
    assert "arbe 可视化工具报警灯对应的算法输出" in DEFAULT_PI_SYSTEM_PROMPT


def test_pi_event_anchor_keeps_explicit_function_when_case_has_multiple_events(tmp_path):
    bundle = tmp_path / "diagnosis_bundle.json"
    viewer = tmp_path / "viewer-model.json"
    bundle.write_text(json.dumps({
        "alarm_events": [
            {"event_id": "bsd-1", "function": "BSD_R", "radar_id": 4},
            {"event_id": "fcta-1", "function": "FCTA_R", "radar_id": 2},
        ]
    }), encoding="utf-8")
    viewer.write_text(json.dumps({
        "events": [
            {"event_id": "fcta-1", "identity": {"function": "FCTA_R", "side": "R", "radar_id": 2}},
            {"event_id": "fcta-2", "identity": {"function": "FCTA_R", "side": "R", "radar_id": 2}},
        ]
    }), encoding="utf-8")
    selected = _resolve_question_event_filter(
        "分析 FCTA_R/R 的报警", bundle_path=str(bundle), viewer_model_path=str(viewer), kwargs={},
    )
    assert selected["function"] == "FCTA_R"
    assert selected["side"] == "R"
    assert selected.get("event_id") is None


def test_pi_evidence_anchor_uses_current_function_and_runtime_artifact(tmp_path):
    bundle = tmp_path / "diagnosis_bundle.json"
    viewer = tmp_path / "viewer-model.json"
    runtime = tmp_path / "runtime-evidence.json"
    bundle.write_text(json.dumps({
        "schema_version": "diagnosis-bundle.v1",
        "case": {"case_id": "case-1", "bag": "/data/case-1.bag"},
        "alarm_events": [{"event_id": "fcta-event", "function": "FCTA_R", "radar_id": 2, "first_on_frame": 100}],
    }), encoding="utf-8")
    viewer.write_text(json.dumps({
        "schema_version": "viewer-model.v1",
        "events": [{
            "event_id": "fcta-event", "identity": {"function": "FCTA_R", "side": "R", "radar_id": 2},
            "frame": {"target_frame": 100, "target_frame_source": "frameID", "selection_confidence": "observed"},
            "target": {"selected": True, "obj_id": 44, "fields": [{"code_token": "objInfo->trcOutData[i].objID", "value": 44}]},
        }],
    }), encoding="utf-8")
    runtime.write_text(json.dumps({
        "schema_version": "runtime-case-evidence.v1",
        "run": {"data_fingerprint": "d", "source_context_id": "s"},
        "observations": [], "evidence_layers": [],
    }), encoding="utf-8")
    anchor = _build_evidence_anchor(
        question="请分析 FCTA_R/R 报警并给出当前报告结论",
        case_dir=str(tmp_path),
        discovered={"diagnosis_bundle_path": str(bundle), "viewer_model_path": str(viewer)},
        kwargs={"runtime_evidence_path": str(runtime)},
        output_dir=str(tmp_path / "diagnostic-report"),
    )
    assert anchor is not None
    assert anchor["scope"]["function"] == "FCTA_R"
    assert anchor["scope"]["side"] == "R"
    assert any(item["kind"] == "runtime_evidence" for item in anchor["artifact_refs"])
    assert any(path.endswith("diagnostic-report.html") for path in anchor["report_artifacts"])


def test_pi_evidence_anchor_report_includes_analysis_trail(tmp_path):
    from engines.analysis_ledger import AnalysisLedger

    ledger = AnalysisLedger(tmp_path / "ledger")
    run = ledger.create_run(
        run_id="run-trail",
        goal={"question": "保留阶段性线索"},
    )
    step = ledger.begin_step("run-trail", stage="event-map", created_by="tool")
    ledger.complete_step(
        "run-trail",
        step["step_id"],
        status="partial",
        observations=[{"kind": "event", "statement": "发现 FCTA_R 报警候选"}],
        gaps=[{"id": "can_tx_unobserved", "reason": "没有 CAN Tx"}],
        next_action_candidates=[{"tool": "runtime-debug-plan", "reason": "获取同帧变量"}],
        user_visible_summary="已定位事件，等待运行态证据",
    )
    hypothesis = ledger.upsert_hypothesis(
        "run-trail",
        hypothesis_id="hyp-trail",
        category="situation",
        statement="动态 ROI 或状态机条件仍缺运行时证据",
        status="open",
        actor="tool",
    )
    experiment = ledger.record_experiment(
        "run-trail",
        question="读取选定帧的局部变量",
        method="gdb",
        status="planned",
        target={"event_id": "fcta-event", "frame_id": 100, "radar_id": 2, "object_id": 44},
        hypothesis_refs=[{"path": hypothesis["artifact_path"]}],
    )
    ledger.append_user_observation(
        "run-trail",
        kind="manual_vscode",
        summary="用户看到断点命中但尚未记录 CAN 输出",
        experiment_id=experiment["experiment_id"],
    )
    bundle = tmp_path / "diagnosis_bundle.json"
    viewer = tmp_path / "viewer-model.json"
    bundle.write_text(json.dumps({
        "schema_version": "diagnosis-bundle.v1",
        "case": {"case_id": "case-1", "bag": "/data/case-1.bag"},
        "alarm_events": [{"event_id": "fcta-event", "function": "FCTA_R", "radar_id": 2, "first_on_frame": 100}],
    }), encoding="utf-8")
    viewer.write_text(json.dumps({
        "schema_version": "viewer-model.v1",
        "events": [{"event_id": "fcta-event", "identity": {"function": "FCTA_R", "side": "R", "radar_id": 2}, "frame": {"target_frame": 100}}],
    }), encoding="utf-8")
    anchor = _build_evidence_anchor(
        question="生成 FCTA_R 详细报告",
        case_dir=str(tmp_path),
        discovered={"diagnosis_bundle_path": str(bundle), "viewer_model_path": str(viewer)},
        kwargs={"analysis_run_path": run["artifact_path"]},
        output_dir=str(tmp_path / "diagnostic-report"),
    )
    report = json.loads((tmp_path / "diagnostic-report" / "diagnostic-report.json").read_text(encoding="utf-8"))
    assert anchor is not None
    assert report["analysis_trace"]["step_count"] == 1
    assert report["analysis_trace"]["steps"][0]["stage"] == "event-map"
    assert report["analysis_trace"]["steps"][0]["gap_count"] == 1
    assert report["analysis_trace"]["hypotheses"][0]["status"] == "open"
    assert report["analysis_trace"]["experiments"][0]["status"] == "planned"
    assert report["analysis_trace"]["user_observations"][0]["runtime_eligible"] is False
    html = (tmp_path / "diagnostic-report" / "diagnostic-report.html").read_text(encoding="utf-8")
    assert "Hypothesis Board" in html
    assert "Next Experiments" in html


def test_pi_records_nested_tool_artifact_refs():
    event = {
        "type": "tool_execution_end",
        "toolName": "diagnosis-report",
        "result": {"details": {"artifacts": [{"path": "report/diagnostic-report.json"}]}},
    }
    assert PiModule._event_artifact_refs(event) == [{"path": "report/diagnostic-report.json"}]


def test_pi_timeout_is_reported_as_unsuccessful_even_when_partial_text_exists(monkeypatch):
    class _TimeoutBridge:
        def prompt(self, message):
            return {"status": "timeout", "answer": "partial", "message": "timeout/无回答", "event_count": 2}

    module = PiModule()
    monkeypatch.setattr(module, "_build_bridge", lambda case_dir, kwargs: _TimeoutBridge())
    result = module.safe_run(question="读取报警摘要")
    assert result.ok is False
    assert result.data["answer"] == "partial"


def test_evidence_query_does_not_treat_format_name_as_output_path(tmp_path):
    from ai.modules.evidence_query import EvidenceQueryModule

    bundle = {
        "schema_version": "diagnosis-bundle.v1",
        "case": {"case_id": "case-1"},
        "alarm_events": [],
    }
    result = EvidenceQueryModule().safe_run(
        bundle=bundle,
        function="FCTA_R",
        output="json",
    )
    assert result.ok
    assert result.artifacts == []
    assert "artifact_path" not in result.data
    assert not (tmp_path / "json").exists()
