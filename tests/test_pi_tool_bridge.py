# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import io
import hashlib
import time
from pathlib import Path

from ai.capability.pi_tool_bridge import _main, available_capabilities, invoke_capability
from ai.capability.module_bridge import ModuleToolAdapter
from ai.capability.registry import capability_catalog, module_input_schema
from ai.pi_bridge import DEFAULT_PI_SOURCE_SYSTEM_PROMPT, DEFAULT_PI_SYSTEM_PROMPT, PiBridge
from scripts.gen_pi_extension import generate
from ai.modules.pi import PiModule, discover_case_artifacts, _select_pi_tools, _select_pi_task_scope, _resolve_question_event_filter, _build_evidence_anchor, _load_pi_context_with_anchor, _ensure_current_code_context, _derive_pi_session_id


def test_pi_source_only_inferred_turn_creates_durable_analysis_run(tmp_path):
    from engines.analysis_ledger import AnalysisLedger

    module = PiModule()
    kwargs = {"project_root": str(tmp_path)}
    module._prepare_analysis_run(
        case_dir="",
        goal="查询当前源码函数调用链",
        kwargs=kwargs,
    )

    assert kwargs["_resolved_task_scope"] == "source_code"
    assert module._analysis_run is not None
    assert module._analysis_ledger_root == (tmp_path / "outputs" / "analysis_runs").resolve()
    assert kwargs["analysis_run_id"] == module._analysis_run["run_id"]
    assert kwargs["analysis_ledger_root"] == str(module._analysis_ledger_root)

    saved = AnalysisLedger(module._analysis_ledger_root).read_run(module._analysis_run["run_id"])
    assert saved["goal"]["task_scope"] == "source_code"
    assert saved["goal"]["question"] == "查询当前源码函数调用链"


def test_pi_source_context_refresh_metrics_count_build_reuse_and_failure(tmp_path):
    from engines.analysis_ledger import AnalysisLedger

    ledger_root = tmp_path / "ledger"
    ledger = AnalysisLedger(ledger_root)
    run = ledger.create_run(owner="pi", goal={"question": "查当前源码函数"})
    module = PiModule()
    module._analysis_run = run
    module._analysis_ledger_root = ledger_root

    module._record_code_context_metrics({
        "refresh_operation": "built",
        "refresh_duration_sec": 0.2,
    })
    module._record_code_context_metrics({
        "refresh_operation": "reused",
        "refresh_duration_sec": 0.1,
    })
    module._record_code_context_metrics({"refresh_operation": "failed"})

    metrics = ledger.read_run(run["run_id"])["metrics"]
    assert metrics["code_index_refresh_attempt_count"] == 3
    assert metrics["code_index_build_count"] == 1
    assert metrics["code_index_cache_hit_count"] == 1
    assert metrics["code_index_refresh_failure_count"] == 1
    assert round(metrics["code_index_refresh_duration_sec_total"], 6) == 0.3


def test_downstream_function_question_auto_selects_source_code_tools():
    question = "PostProcessMainTI 的直接下游函数有哪些？"
    tools = _select_pi_tools(
        question=question,
        case_dir="",
        batch="",
        interactive=False,
    )
    scope = _select_pi_task_scope(
        question=question,
        case_dir="",
        batch="",
        tools=tools,
    )

    assert scope == "source_code"
    assert "code-analyze" in tools
    assert "code-context-read" in tools


def test_non_source_pi_question_does_not_create_implicit_analysis_run(tmp_path):
    module = PiModule()
    kwargs = {"project_root": str(tmp_path)}
    module._prepare_analysis_run(
        case_dir="",
        goal="你好",
        kwargs=kwargs,
    )

    assert module._analysis_run is None
    assert not (tmp_path / "outputs" / "analysis_runs").exists()


def test_analysis_run_gets_a_distinct_stable_pi_session_id():
    assert _derive_pi_session_id("run-20260915-a1b2", "run-20260915-a1b2") == "pi-run-20260915-a1b2"
    assert _derive_pi_session_id("", "pi-context-run-a1b2") == "pi-context-run-a1b2"
    assert len(_derive_pi_session_id("r" * 128)) <= 128


def test_pi_analysis_ledger_tool_step_reads_nested_result_status(tmp_path):
    from engines.analysis_ledger import AnalysisLedger

    root = tmp_path / "ledger"
    ledger = AnalysisLedger(root)
    run = ledger.create_run(
        owner="pi",
        goal={"question": "查当前源码调用链"},
    )
    module = PiModule()
    module._analysis_run = run
    module._analysis_ledger_root = root

    module._record_tool_step({
        "type": "tool_execution_end",
        "toolName": "code-analyze",
        "toolCallId": "call-nested-status",
        "result": {"details": {
            "status": "ok",
            "message": "source index done",
            "data": {
                "backend": "source_code_index",
                "result_bounds": {
                    "limit": 5,
                    "total_count": 12,
                    "returned_count": 5,
                    "truncated": True,
                },
            },
            "artifacts": [],
        }},
    })

    saved = ledger.read_run(run["run_id"])
    assert saved["steps"][0]["status"] == "completed"
    assert saved["metrics"]["code_index_query_success_count"] == 1
    step = json.loads(Path(saved["steps"][0]["path"]).read_text(encoding="utf-8"))
    assert step["gaps"] == []
    assert step["metrics"]["code_index_backend"] == "source_code_index"
    assert step["metrics"]["result_returned_count"] == 5
    assert step["metrics"]["result_total_count"] == 12
    assert step["metrics"]["result_truncated"] is True


def test_pi_run_returns_finalized_analysis_run_status(monkeypatch, tmp_path):
    module = PiModule(task_scope="source_code")
    source_root = tmp_path / "source"
    source_root.mkdir()
    context_path = tmp_path / "code-context.json"
    index_path = tmp_path / "code-index.json"
    context_path.write_text("{}", encoding="utf-8")
    index_path.write_text("{}", encoding="utf-8")
    context_hash = hashlib.sha256(context_path.read_bytes()).hexdigest()
    index_hash = hashlib.sha256(index_path.read_bytes()).hexdigest()

    context = {
        "schema_version": "pi-orchestration-context.v1",
        "task_scope": "source_code",
        "status": "ready",
        "project": {
            "project_id": "BYD_SC6H",
            "variant_id": "gen6/byd_sc6h",
            "customer": "BYD",
            "vehicle": "SC6H",
            "coem": "BYD_SC6H",
        },
        "data": {"status": "not_required"},
        "source": {
            "source_context_id": "source-context-test",
            "source_snapshot_hash": "snapshot-test",
            "code_index_hash": index_hash,
            "code_context": {
                "code_context_path": str(context_path),
                "code_context_sha256": context_hash,
                "code_index_path": str(index_path),
                "code_index_hash": index_hash,
                "source_root": str(source_root),
                "source_snapshot_hash": "snapshot-test",
            },
        },
        "artifacts": [],
    }

    class _Bridge:
        pass

    def fake_build_bridge(_case_dir, _kwargs):
        module._context = context
        module._sync_analysis_run_context()
        return _Bridge()

    monkeypatch.setattr(module, "_build_bridge", fake_build_bridge)
    monkeypatch.setattr(module, "_prompt_with_ledger", lambda _bridge, _question: {
        "status": "ok",
        "message": "agent_settled",
        "answer": "静态源码查询已完成",
        "event_summary": {
            "tool_events": [{"name": "code-analyze", "status": "ok"}],
        },
    })
    monkeypatch.setattr("ai.modules.pi._build_evidence_anchor", lambda **_: None)

    result = module.run(
        question="查询当前源码函数调用链",
        project_root=str(tmp_path),
    )

    assert result.ok
    assert result.data["analysis_run_status"] == "completed"
    saved = json.loads(Path(result.data["analysis_run_path"]).read_text(encoding="utf-8"))
    assert saved["status"] == "completed"
    assert saved["binding"]["source_snapshot_hash"] == "snapshot-test"
    assert saved["binding"]["code_index_hash"] == index_hash


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


def test_code_analyze_schema_explains_direction_and_name_field():
    registry = __import__("ai.modules", fromlist=["MODULE_REGISTRY"]).MODULE_REGISTRY
    schema = module_input_schema(registry["code-analyze"])

    assert "callers=谁调用目标函数" in schema["properties"]["kind"]["description"]
    assert "callees=目标函数调用谁" in schema["properties"]["kind"]["description"]
    assert "参数名固定为 name" in schema["properties"]["name"]["description"]


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


def test_pi_bridge_preserves_bounded_code_analyze_results():
    code_index = {
        "source_root": "/snapshot/gen6",
        "snapshot_hash": "gen6-source-hash",
        "parser": "codegraph_sqlite",
        "functions": [{"name": "PostProcessMainTI", "file_path": "postProcess.c"}],
        "calls": {
            "PostProcessMainTI": [f"Stage{i:02d}" for i in range(12)],
        },
    }

    result = invoke_capability(
        "code-analyze",
        {
            "kind": "call_chain",
            "name": "PostProcessMainTI",
            "max_depth": 1,
            "max_results": 4,
            "code_index": code_index,
        },
    )

    assert result["status"] == "ok"
    assert len(result["data"]["data"]) == 4
    assert result["data"]["result_bounds"] == {
        "limit": 4,
        "total_count": 12,
        "returned_count": 4,
        "truncated": True,
    }
    assert "4/12 rows; truncated" in result["message"]


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


def test_registered_pi_source_read_schemas_hide_filesystem_output_paths():
    names = ("code-analyze", "event-code-path", "code-gdb-plan")
    module_registry = __import__("ai.modules", fromlist=["MODULE_REGISTRY"]).MODULE_REGISTRY
    catalog = {item["name"]: item for item in capability_catalog()}
    for name in names:
        schema = module_input_schema(module_registry[name])
        assert "output" not in schema.get("properties", {})
        assert "output" not in catalog[name]["parameters"].get("properties", {})
        ts = generate([catalog[name]])
        block = ts.split(f'name: "{name}"', 1)[1].split("  });", 1)[0]
        assert '"output"' not in block


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
        thinking="off",
        load_context_files=False,
        discover_extensions=False,
        load_skills=False,
        replace_system_prompt=True,
    )
    bridge._spawn()
    command = calls[0][0]
    assert "--extension" in command
    assert str(extension) in command
    assert "--no-builtin-tools" in command
    assert "--system-prompt" in command
    assert "--append-system-prompt" not in command
    assert "--approve" in command
    assert command[command.index("--thinking") + 1] == "off"
    assert "--no-context-files" in command
    assert "--no-extensions" in command
    assert "--no-skills" in command


def test_pi_bridge_explicit_empty_allowlist_disables_all_tools(tmp_path, monkeypatch):
    extension = tmp_path / ".pi" / "extensions" / "radar-capabilities.ts"
    extension.parent.mkdir(parents=True)
    extension.write_text("export default () => {};", encoding="utf-8")
    calls = []

    class _FakeProcess:
        pass

    monkeypatch.setattr("ai.pi_bridge._find_pi", lambda: "pi")
    monkeypatch.setattr(
        "ai.pi_bridge.subprocess.Popen",
        lambda command, **kwargs: calls.append(command) or _FakeProcess(),
    )
    bridge = PiBridge(
        provider="test-provider",
        model="test-model",
        project_root=str(tmp_path),
        extension_path=str(extension),
        auto_generate_extension=False,
        tools=[],
    )
    bridge._spawn()

    assert "--no-tools" in calls[0]
    assert "--tools" not in calls[0]


def test_pi_bridge_child_process_receives_exact_code_index_binding(tmp_path, monkeypatch):
    index_path = tmp_path / "code-index.json"
    source_root = tmp_path / "source"
    source_root.mkdir()
    index_path.write_text(json.dumps({
        "schema_version": "code-index.v1",
        "source_root": str(source_root),
        "snapshot_hash": "snapshot-a",
    }), encoding="utf-8")
    index_hash = hashlib.sha256(index_path.read_bytes()).hexdigest()
    context_path = tmp_path / "code-context.json"
    context_path.write_text(json.dumps({
        "schema_version": "code-context.v1",
        "source_context": {
            "project_id": "BYD_SC6H",
            "variant_id": "gen6/byd_sc6h",
            "source_root": str(source_root),
            "snapshot_hash": "snapshot-a",
        },
        "artifacts": {"code_index": str(index_path), "code_index_sha256": index_hash},
    }), encoding="utf-8")
    captured = {}
    monkeypatch.setattr("ai.pi_bridge._find_pi", lambda: "pi")
    monkeypatch.setattr(
        "ai.pi_bridge.subprocess.Popen",
        lambda command, **kwargs: captured.update(kwargs) or object(),
    )
    monkeypatch.setenv("CR60_PI_ANALYSIS_RUN_ID", "stale-run")
    monkeypatch.setenv("CR60_PI_ANALYSIS_LEDGER_ROOT", str(tmp_path / "stale-ledger"))
    bridge = PiBridge(
        provider="test-provider",
        load_project_extension=False,
        analysis_run_id="run-bound",
        analysis_ledger_root=str(tmp_path / "ledger"),
        code_index_binding={
            "task_scope": "source_code",
            "code_context_path": str(context_path),
            "code_context_sha256": hashlib.sha256(context_path.read_bytes()).hexdigest(),
            "code_index_path": str(index_path),
            "code_index_hash": index_hash,
            "source_root": str(source_root),
            "source_snapshot_hash": "snapshot-a",
            "project_id": "BYD_SC6H",
            "variant_id": "gen6/byd_sc6h",
        },
    )

    bridge._spawn()
    child_env = captured["env"]
    assert child_env["CR60_PI_TASK_SCOPE"] == "source_code"
    assert child_env["CR60_PI_CODE_CONTEXT_PATH"] == str(context_path)
    assert child_env["CR60_PI_CODE_CONTEXT_SHA256"] == hashlib.sha256(context_path.read_bytes()).hexdigest()
    assert child_env["CR60_PI_CODE_INDEX_PATH"] == str(index_path)
    assert child_env["CR60_PI_CODE_INDEX_SHA256"] == index_hash
    assert child_env["CR60_PI_SOURCE_ROOT"] == str(source_root)
    assert child_env["CR60_PI_SOURCE_SNAPSHOT_HASH"] == "snapshot-a"
    assert child_env["CR60_PI_VARIANT_ID"] == "gen6/byd_sc6h"
    assert child_env["CR60_PI_ANALYSIS_RUN_ID"] == "run-bound"
    assert child_env["CR60_PI_ANALYSIS_LEDGER_ROOT"] == str(tmp_path / "ledger")


def test_pi_tool_bridge_injects_only_verified_context_bound_code_index(tmp_path, monkeypatch):
    source_root = tmp_path / "source"
    source_root.mkdir()
    index_path = tmp_path / "code-index.json"
    index_path.write_text(json.dumps({
        "schema_version": "code-index.v1",
        "source_root": str(source_root),
        "snapshot_hash": "snapshot-a",
        "functions": [{"name": "Root", "file_path": "root.c"}],
        "calls": {"Root": ["Leaf"]},
    }), encoding="utf-8")
    monkeypatch.setenv("CR60_PI_CODE_INDEX_PATH", str(index_path))
    monkeypatch.setenv("CR60_PI_CODE_INDEX_SHA256", hashlib.sha256(index_path.read_bytes()).hexdigest())
    monkeypatch.setenv("CR60_PI_SOURCE_ROOT", str(source_root))
    monkeypatch.setenv("CR60_PI_SOURCE_SNAPSHOT_HASH", "snapshot-a")
    monkeypatch.setenv("CR60_PI_TASK_SCOPE", "source_code")
    monkeypatch.setenv("CR60_PI_PROJECT_ID", "BYD_SC6H")
    monkeypatch.setenv("CR60_PI_VARIANT_ID", "gen6/byd_sc6h")

    result = invoke_capability("code-analyze", {"kind": "call_chain", "name": "Root", "max_depth": 1})
    assert result["status"] == "ok"
    assert result["data"]["backend"] == "source_code_index"
    assert result["data"]["source_context"]["snapshot_hash"] == "snapshot-a"

    write_path = tmp_path / "blocked-output.json"
    write = invoke_capability("code-analyze", {
        "kind": "call_chain", "name": "Root", "output": str(write_path),
    })
    assert write["status"] == "error"
    assert "output file paths are disabled" in write["message"]
    assert not write_path.exists()

    conflict = invoke_capability("code-analyze", {
        "kind": "call_chain", "name": "Root", "code_index_path": str(tmp_path / "other.json"),
    })
    assert conflict["status"] == "error"
    assert "conflicts with PiRunContext" in conflict["message"]

    inline = invoke_capability("code-analyze", {
        "kind": "call_chain", "name": "Root", "code_index": {"snapshot_hash": "other"},
    })
    assert inline["status"] == "error"
    assert "inline code_index cannot override" in inline["message"]

    index_path.write_text(index_path.read_text(encoding="utf-8") + " ", encoding="utf-8")
    changed = invoke_capability("code-analyze", {"kind": "call_chain", "name": "Root"})
    assert changed["status"] == "error"
    assert "file hash changed" in changed["message"]


def test_pi_ledger_tools_bind_active_run_and_reject_conflicts(tmp_path, monkeypatch):
    from engines.analysis_ledger import AnalysisLedger

    ledger_root = tmp_path / "analysis_runs"
    ledger = AnalysisLedger(ledger_root)
    created = ledger.create_run(
        run_id="run-bound",
        owner="pi",
        goal={"question": "逐步验证当前报警原因"},
    )
    monkeypatch.setenv("CR60_PI_ANALYSIS_RUN_ID", created["run_id"])
    monkeypatch.setenv("CR60_PI_ANALYSIS_LEDGER_ROOT", str(ledger_root))

    hypothesis = invoke_capability("analysis-hypothesis-record", {
        "category": "perception",
        "statement": "当前输出行不足以区分聚类阶段是否丢失目标",
        "status": "open",
        "rank": 1,
        "confidence_band": "unknown",
        "actor": "ai",
        "required_evidence": [{"kind": "runtime_stage_trace", "status": "not_available"}],
    })
    assert hypothesis["status"] == "ok"
    assert hypothesis["data"]["run_id"] == "run-bound"
    assert hypothesis["data"]["status"] == "open"

    experiment = invoke_capability("debug-experiment-record", {
        "action": "plan",
        "question": "获取同一帧的聚类输入和输出以区分阶段缺失与后续过滤",
        "method": "public_runtime",
        "hypothesis_refs": [{"path": hypothesis["data"]["artifact_path"]}],
        "expected_discrimination": [
            {"observation": "目标已在聚类输出中", "supports": "后续阶段候选"},
            {"observation": "目标未进入聚类输出", "supports": "聚类阶段候选"},
        ],
    })
    assert experiment["status"] == "ok"
    assert experiment["data"]["run_id"] == "run-bound"

    readback = invoke_capability("analysis-run-read", {"include_entities": True})
    assert readback["status"] == "ok"
    assert readback["data"]["run_id"] == "run-bound"
    assert len(readback["data"]["entities"]["hypotheses"]) == 1
    assert len(readback["data"]["entities"]["experiments"]) == 1

    conflict = invoke_capability("analysis-run-update", {
        "run_id": "run-other",
        "status": "failed",
    })
    assert conflict["status"] == "error"
    assert "conflicts with the current Pi AnalysisRun binding" in conflict["message"]

    root_conflict = invoke_capability("analysis-run-update", {
        "ledger_root": str(tmp_path / "other-ledger"),
        "status": "failed",
    })
    assert root_conflict["status"] == "error"
    assert "ledger_root conflicts with the current Pi AnalysisRun binding" in root_conflict["message"]

    duplicate = invoke_capability("analysis-run-create", {
        "question": "duplicate run",
    })
    assert duplicate["status"] == "error"
    assert "already has an active AnalysisRun" in duplicate["message"]

    saved = ledger.read_run("run-bound")
    assert saved["status"] == "created"

    monkeypatch.delenv("CR60_PI_ANALYSIS_RUN_ID")
    monkeypatch.delenv("CR60_PI_ANALYSIS_LEDGER_ROOT")
    unbound = invoke_capability("analysis-hypothesis-record", {
        "category": "perception",
        "statement": "should not be written without a bound run",
        "status": "open",
        "actor": "ai",
    })
    assert unbound["status"] == "error"
    assert "requires an active AnalysisRun binding" in unbound["message"]


def test_pi_tool_bridge_injects_hash_verified_code_context_for_reads(tmp_path, monkeypatch):
    source_root = tmp_path / "source"
    source_root.mkdir()
    index_path = tmp_path / "code-index.json"
    index_path.write_text(json.dumps({
        "schema_version": "code-index.v1",
        "source_root": str(source_root),
        "snapshot_hash": "snapshot-a",
        "summary": {"functions": 3},
    }), encoding="utf-8")
    index_hash = hashlib.sha256(index_path.read_bytes()).hexdigest()
    context_path = tmp_path / "code-context.json"
    context_path.write_text(json.dumps({
        "schema_version": "code-context.v1",
        "context_id": "context-a",
        "source_context": {
            "project_id": "BYD_SC6H",
            "variant_id": "gen6/byd_sc6h",
            "source_root": str(source_root),
            "snapshot_hash": "snapshot-a",
        },
        "artifacts": {"code_index": str(index_path), "code_index_sha256": index_hash},
    }), encoding="utf-8")
    monkeypatch.setenv("CR60_PI_CODE_CONTEXT_PATH", str(context_path))
    monkeypatch.setenv("CR60_PI_CODE_CONTEXT_SHA256", hashlib.sha256(context_path.read_bytes()).hexdigest())
    monkeypatch.setenv("CR60_PI_CODE_INDEX_PATH", str(index_path))
    monkeypatch.setenv("CR60_PI_CODE_INDEX_SHA256", index_hash)
    monkeypatch.setenv("CR60_PI_SOURCE_ROOT", str(source_root))
    monkeypatch.setenv("CR60_PI_SOURCE_SNAPSHOT_HASH", "snapshot-a")
    monkeypatch.setenv("CR60_PI_PROJECT_ID", "BYD_SC6H")
    monkeypatch.setenv("CR60_PI_VARIANT_ID", "gen6/byd_sc6h")

    result = invoke_capability("code-context-read", {"section": "summary"})
    assert result["status"] == "ok"
    assert result["data"]["index_path"] == str(index_path.resolve())
    assert result["data"]["data"] == {"functions": 3}

    conflict = invoke_capability("code-context-read", {
        "context_path": str(tmp_path / "another-context.json"),
        "section": "summary",
    })
    assert conflict["status"] == "error"
    assert "conflicts with PiRunContext" in conflict["message"]

    context_path.write_text(context_path.read_text(encoding="utf-8") + " ", encoding="utf-8")
    tampered = invoke_capability("code-context-read", {"section": "summary"})
    assert tampered["status"] == "error"
    assert "artifact hash changed" in tampered["message"]


def test_pi_tool_bridge_binds_event_and_gdb_code_tools_to_current_snapshot(tmp_path, monkeypatch):
    source_root = tmp_path / "source"
    source_root.mkdir()
    index_path = tmp_path / "code-index.json"
    index_path.write_text(json.dumps({
        "schema_version": "code-index.v1",
        "source_root": str(source_root),
        "snapshot_hash": "snapshot-a",
    }), encoding="utf-8")
    index_hash = hashlib.sha256(index_path.read_bytes()).hexdigest()
    context_path = tmp_path / "code-context.json"
    context_path.write_text(json.dumps({
        "schema_version": "code-context.v1",
        "source_context": {
            "project_id": "DEMO",
            "variant_id": "gen6/demo",
            "source_root": str(source_root),
            "snapshot_hash": "snapshot-a",
        },
        "artifacts": {"code_index": str(index_path), "code_index_sha256": index_hash},
    }), encoding="utf-8")
    monkeypatch.setenv("CR60_PI_CODE_CONTEXT_PATH", str(context_path))
    monkeypatch.setenv("CR60_PI_CODE_CONTEXT_SHA256", hashlib.sha256(context_path.read_bytes()).hexdigest())
    monkeypatch.setenv("CR60_PI_CODE_INDEX_PATH", str(index_path))
    monkeypatch.setenv("CR60_PI_CODE_INDEX_SHA256", index_hash)
    monkeypatch.setenv("CR60_PI_SOURCE_ROOT", str(source_root))
    monkeypatch.setenv("CR60_PI_SOURCE_SNAPSHOT_HASH", "snapshot-a")
    monkeypatch.setenv("CR60_PI_PROJECT_ID", "DEMO")
    monkeypatch.setenv("CR60_PI_VARIANT_ID", "gen6/demo")
    observed = {}

    class _CaptureTool:
        def __init__(self, name):
            self.name = name

        def safe_execute(self, params):
            observed[self.name] = dict(params)
            return {"status": "ok", "message": "captured", "data": dict(params), "artifacts": []}

    monkeypatch.setattr(
        "ai.capability.pi_tool_bridge.build_module_tool_registry",
        lambda *, names, allow_execution: {name: _CaptureTool(name) for name in names},
    )
    event_result = invoke_capability("event-code-path", {"event": {"function": "Root"}})
    gdb_result = invoke_capability("code-gdb-plan", {"function_name": "Root"})

    assert event_result["status"] == "ok"
    assert observed["event-code-path"]["context_path"] == str(context_path.resolve())
    assert "code_index_path" not in observed["event-code-path"]
    assert observed["event-code-path"]["source_root"] == str(source_root)
    assert gdb_result["status"] == "ok"
    assert observed["code-gdb-plan"]["code_index_path"] == str(index_path.resolve())
    assert observed["code-gdb-plan"]["source_root"] == str(source_root)


def test_ensure_current_code_context_uses_configured_variant_snapshot_area(tmp_path, monkeypatch):
    from types import SimpleNamespace

    config_path = tmp_path / "config.yaml"
    config_path.write_text("{}\n", encoding="utf-8")
    source_root = tmp_path / "source"
    source_root.mkdir()
    snapshots = tmp_path / ".workspaces" / "gen6_demo" / "memory" / "snapshots"
    source_docs = tmp_path / ".workspaces" / "gen6_demo" / "source_docs"
    cfg = {
        "variants": {
            "gen6/demo": {
                "display_name": "DEMO",
                "customer": "ACME",
                "vehicle_project": "DEMO_CAR",
                "coem_project_dir": "coem/DEMO_CAR",
                "key_source_files": ["coem/DEMO_CAR/main.c"],
                "source_context": {"source_root": str(source_root)},
            },
        },
    }
    monkeypatch.setattr("config.load_config", lambda path: cfg)
    monkeypatch.setattr("config.resolve_variant_id", lambda config, identifier: identifier or "gen6/demo")
    monkeypatch.setattr("config.get_variant", lambda config, variant_id: (
        SimpleNamespace(variant_id=variant_id, display_name="DEMO", key_source_files=["coem/DEMO_CAR/main.c"]),
        SimpleNamespace(root_path=str(source_root), branch="main"),
        None,
    ))
    monkeypatch.setattr("config.resolve_snapshots_dir", lambda *args, **kwargs: snapshots)
    monkeypatch.setattr("config.resolve_source_docs_dir", lambda *args, **kwargs: source_docs)
    captured = {}

    class _Refresh:
        def run(self, **kwargs):
            captured.update(kwargs)
            output = Path(kwargs["output_dir"])
            output.mkdir(parents=True)
            context_path = output / "code-context.json"
            index_path = output / "code-index.json"
            context_path.write_text("{}", encoding="utf-8")
            index_path.write_text("{}", encoding="utf-8")
            return SimpleNamespace(ok=True, message="code-context-refresh:built", data={
                "artifacts": {"code_context": str(context_path), "code_index": str(index_path)},
            })

    monkeypatch.setattr("ai.modules.code_context.CodeContextRefreshModule", _Refresh)
    result = _ensure_current_code_context(project_root=str(tmp_path), project_id="DEMO")

    assert result["project_id"] == "DEMO"
    assert result["variant_id"] == "gen6/demo"
    assert Path(captured["output_dir"]) == snapshots / "code_context_current"
    assert Path(captured["db_path"]) == snapshots / "code_context_current" / "codegraph.db"
    assert captured["source_root"] == str(source_root.resolve())
    assert captured["key_files"] == ["coem/DEMO_CAR/main.c"]
    assert captured["source_identity"]["coem"] == "DEMO_CAR"


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


def test_pi_bridge_does_not_auto_approve_external_custom_extension(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    project_root.mkdir()
    extension = tmp_path / "custom-extension.ts"
    extension.write_text("export default () => {};", encoding="utf-8")
    commands = []
    class _FakeProcess:
        pass

    monkeypatch.setattr("ai.pi_bridge._find_pi", lambda: "pi")
    monkeypatch.setattr(
        "ai.pi_bridge.subprocess.Popen",
        lambda command, **kwargs: commands.append(command) or _FakeProcess(),
    )
    PiBridge(
        provider="test-provider",
        project_root=str(project_root),
        extension_path=str(extension),
        auto_generate_extension=False,
    )._spawn()

    assert "--extension" in commands[0]
    assert str(extension) in commands[0]
    assert "--approve" not in commands[0]


def test_pi_bridge_context_prompt_is_compact_and_read_only():
    bridge = PiBridge(
        load_project_extension=False,
        context={
            "schema_version": "pi-orchestration-context.v1",
            "task_scope": "source_code",
            "status": "partial",
            "run_id": "run-1",
            "context_fingerprint": "context-hash",
            "project": {"variant_id": "demo", "provenance": {"long": "unused-project-detail" * 500}},
            "data": {"status": "not_required", "required": False, "paths": ["/case/data"] * 500},
            "source": {"source_snapshot_hash": "source-hash"},
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
    assert "source-only" in prompt.lower()
    assert "not_required" in prompt
    assert "unused-project-detail" not in prompt
    assert len(prompt) < 1500


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


def test_pi_bridge_returns_sanitized_stop_and_tool_event_summary(monkeypatch):
    rpc_events = [
        {
            "type": "message_end",
            "message": {
                "role": "assistant",
                "provider": "ollama",
                "model": "qwen3.5:9b",
                "stopReason": "toolUse",
                "rawStopReason": "tool_calls",
                "usage": {"input": 100, "output": 30, "reasoning": 12, "totalTokens": 130},
                "content": [
                    {"type": "thinking", "thinking": "private reasoning must not escape"},
                    {"type": "toolCall", "id": "call-1", "name": "code-analyze", "arguments": {"name": "F"}},
                ],
            },
        },
        {
            "type": "tool_execution_end",
            "toolName": "code-analyze",
            "toolCallId": "call-1",
            "status": "ok",
            "result": {"details": {"status": "ok", "artifacts": [{"path": "result.json"}]}},
        },
        {"type": "agent_settled"},
    ]

    class _FakeProcess:
        def __init__(self):
            self.stdin = io.StringIO()
            self.stdout = io.StringIO("".join(json.dumps(event) + "\n" for event in rpc_events))
            self.pid = None
            self.killed = False

        def kill(self):
            self.killed = True

    process = _FakeProcess()
    bridge = PiBridge(load_project_extension=False)
    monkeypatch.setattr(bridge, "_spawn", lambda: process)
    result = bridge.prompt("query", timeout=1)

    summary = result["event_summary"]
    assert result["status"] == "ok"
    assert summary["assistant_messages"][0]["stop_reason"] == "toolUse"
    assert summary["assistant_messages"][0]["usage"] == {
        "input": 100,
        "output": 30,
        "totalTokens": 130,
    }
    assert summary["assistant_messages"][0]["content_types"] == ["toolCall"]
    assert summary["tool_calls"] == [{"id": "call-1", "name": "code-analyze"}]
    assert summary["tool_events"] == [{
        "event_type": "tool_execution_end",
        "name": "code-analyze",
        "tool_call_id": "call-1",
        "status": "ok",
    }]
    assert "private reasoning" not in json.dumps(summary)


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


def test_pi_tool_allowlist_reaches_point_cloud_capabilities_from_business_language():
    selected = _select_pi_tools(
        question="用录制数据重新仿真前级感知，分析点云聚类和跟踪并生成报告",
        case_dir="D:/case-pc",
        batch="",
        interactive=False,
    )
    assert selected is not None
    assert {"point-cloud-plan", "point-cloud-analyze", "point-cloud-validate", "point-cloud-batch"}.issubset(selected)
    assert "arbe-execution-binding" in selected


def test_pi_tool_allowlist_routes_plain_target_lifecycle_symptoms_without_jargon():
    selected = _select_pi_tools(
        question="这个目标为什么没被检出，后面又突然消失了？",
        case_dir="",
        batch="",
        interactive=False,
    )
    assert selected is not None
    assert {"point-cloud-plan", "point-cloud-analyze", "point-cloud-read", "point-cloud-validate"}.issubset(selected)
    assert "sim-verify" in selected


def test_pi_tool_allowlist_routes_objectlist_attributes_to_public_runtime_capture():
    selected = _select_pi_tools(
        question="读取当前 ObjectList 目标属性，并保留它与报警帧的关联状态",
        case_dir="",
        batch="",
        interactive=False,
    )
    assert selected is not None
    assert {"public-topic-plan", "ros-topic-inventory", "public-runtime-normalize"}.issubset(selected)


def test_pi_objectlist_field_request_includes_bounded_snapshot_query():
    selected = _select_pi_tools(
        question="当前 ObjectList 字段有哪些？",
        case_dir="",
        batch="",
        interactive=False,
    )
    assert selected is not None
    assert {"ros-topic-inventory", "public-runtime-normalize", "evidence-query"}.issubset(selected)


def test_pi_feedback_intent_routes_to_review_and_user_observation():
    selected = _select_pi_tools(
        question="我确认这个候选是正报，请审查并记录反馈",
        case_dir="",
        batch="",
        interactive=False,
    )
    assert selected is not None
    assert {"feedback-review", "analysis-user-observation"}.issubset(selected)


def test_pi_task_scope_keeps_static_code_lookup_separate_from_case_diagnosis():
    assert _select_pi_task_scope(
        question="查当前 Gen6 源码调用链",
        case_dir="",
        batch="",
        tools=["code-analyze"],
    ) == "source_code"
    assert _select_pi_task_scope(
        question="查当前 Gen6 源码调用链",
        case_dir="D:/case-1",
        batch="",
        tools=["code-analyze"],
    ) == "case_analysis"
    assert _select_pi_task_scope(
        question="目标为什么没检出，查一下源码调用链",
        case_dir="",
        batch="",
        tools=["code-analyze", "point-cloud-analyze"],
    ) == "case_analysis"


def test_pi_module_binds_source_only_scope_from_explicit_code_context(monkeypatch, tmp_path):
    captured = {}
    source_root = tmp_path / "source"
    source_root.mkdir()
    code_index_path = tmp_path / "code-index.json"
    code_index_path.write_text(json.dumps({
        "schema_version": "code-index.v1",
        "source_root": str(source_root),
        "snapshot_hash": "gen6-static-snapshot",
    }), encoding="utf-8")
    code_context_path = tmp_path / "code-context.json"
    code_context_path.write_text(json.dumps({
        "schema_version": "code-context.v1",
        "context_id": "source-context-gen6",
        "source_context": {
            "project_id": "BYD_SC6H",
            "variant_id": "gen6/byd_sc6h",
            "coem": "BYD_SC6H",
            "source_root": str(source_root),
            "snapshot_hash": "gen6-static-snapshot",
            "source_role": "local_static_source_not_remote_runtime_bound",
            "runtime_binding": "not_available",
            "binary_fingerprint": "not_available",
            "compile_macro_observation": "not_observed",
            "recording_binding": "not_available",
        },
        "artifacts": {
            "code_index": str(code_index_path),
            "code_index_sha256": hashlib.sha256(code_index_path.read_bytes()).hexdigest(),
        },
    }), encoding="utf-8")

    class _CapturePiBridge:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr("ai.pi_bridge.PiBridge", _CapturePiBridge)
    module = PiModule()
    monkeypatch.setattr(module, "_prepare_analysis_run", lambda **_: None)
    monkeypatch.setattr(module, "_persist_context_artifact", lambda: None)
    monkeypatch.setattr(module, "_sync_analysis_run_context", lambda: None)
    monkeypatch.setattr("ai.modules.pi._build_evidence_anchor", lambda **_: None)
    monkeypatch.setattr(
        module,
        "_prompt_with_ledger",
        lambda _bridge, _question: {"status": "ok", "message": "fake", "answer": "静态调用链已返回"},
    )

    result = module.run(
        question="查当前 Gen6 源码调用链",
        provider="test-provider",
        project_root=str(tmp_path),
        code_context_path=str(code_context_path),
        thinking="off",
    )

    context = captured["context"]
    assert result.ok
    assert context["task_scope"] == "source_code"
    assert context["status"] == "ready"
    assert context["data"]["status"] == "not_required"
    assert context["source"]["source_snapshot_hash"] == "gen6-static-snapshot"
    assert context["source"]["code_context"]["code_index_path"] == str(code_index_path.resolve())
    assert context["source"]["code_context"]["code_context_path"] == str(code_context_path.resolve())
    assert context["source"]["code_context"]["code_context_sha256"]
    assert captured["code_index_binding"]["code_index_hash"] == context["source"]["code_index_hash"]
    assert any(ref.get("kind") == "code_context" for ref in context["artifacts"])
    assert "code-analyze" in captured["tools"]
    assert set(captured["tools"]).issubset({
        "code-context-read", "code-analyze", "event-code-path", "code-gdb-plan",
    })
    assert captured["thinking"] == "off"
    assert captured["system_prompt"] == DEFAULT_PI_SOURCE_SYSTEM_PROMPT
    assert "直接调用目标、它调用了谁或下游" in DEFAULT_PI_SOURCE_SYSTEM_PROMPT
    assert "kind=callees" in DEFAULT_PI_SOURCE_SYSTEM_PROMPT
    assert "kind=callers" in DEFAULT_PI_SOURCE_SYSTEM_PROMPT
    assert "结果以内联方式返回，不要传 output 文件路径" in DEFAULT_PI_SOURCE_SYSTEM_PROMPT
    assert captured["load_context_files"] is False
    assert captured["replace_system_prompt"] is True
    assert captured["discover_extensions"] is False
    assert captured["load_skills"] is False


def test_pi_module_automatically_refreshes_current_configured_source_context(monkeypatch, tmp_path):
    source_root = tmp_path / "source"
    source_root.mkdir()
    index_path = tmp_path / "code-index.json"
    index_path.write_text(json.dumps({
        "schema_version": "code-index.v1",
        "source_root": str(source_root),
        "snapshot_hash": "snapshot-current",
        "functions": [],
        "calls": {},
    }), encoding="utf-8")
    context_path = tmp_path / "code-context.json"
    context_path.write_text(json.dumps({
        "schema_version": "code-context.v1",
        "context_id": "context-current",
        "source_context": {
            "project_id": "BYD_SC6H",
            "variant_id": "gen6/byd_sc6h",
            "customer": "BYD",
            "vehicle": "SC6H",
            "coem": "BYD_SC6H",
            "source_root": str(source_root),
            "snapshot_hash": "snapshot-current",
        },
        "artifacts": {
            "code_index": str(index_path),
            "code_index_sha256": hashlib.sha256(index_path.read_bytes()).hexdigest(),
        },
    }), encoding="utf-8")
    auto_called = {}
    monkeypatch.setattr("ai.modules.pi._ensure_current_code_context", lambda **kwargs: (
        auto_called.update(kwargs) or {
            "project_id": "BYD_SC6H",
            "variant_id": "gen6/byd_sc6h",
            "source_root": str(source_root),
            "code_context_path": str(context_path),
            "code_index_path": str(index_path),
        }
    ))
    captured = {}

    class _CapturePiBridge:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr("ai.pi_bridge.PiBridge", _CapturePiBridge)
    module = PiModule()
    monkeypatch.setattr(module, "_prepare_analysis_run", lambda **_: None)
    monkeypatch.setattr(module, "_persist_context_artifact", lambda: None)
    monkeypatch.setattr(module, "_sync_analysis_run_context", lambda: None)
    monkeypatch.setattr("ai.modules.pi._build_evidence_anchor", lambda **_: None)
    monkeypatch.setattr(
        module,
        "_prompt_with_ledger",
        lambda _bridge, _question: {"status": "ok", "message": "fake", "answer": "已使用当前快照"},
    )

    result = module.run(
        question="查当前 Gen6 源码调用链",
        provider="test-provider",
        project_root=str(tmp_path),
        tools=["code-analyze"],
    )

    assert result.ok
    assert auto_called["project_root"] == str(tmp_path)
    assert captured["context"]["status"] == "ready"
    assert captured["context"]["source"]["code_index_path"] == str(index_path.resolve())
    assert captured["code_index_binding"]["source_snapshot_hash"] == "snapshot-current"
    assert captured["code_index_binding"]["variant_id"] == "gen6/byd_sc6h"


def test_pi_source_only_turn_suppresses_unverified_final_text(monkeypatch):
    module = PiModule()
    module._context = {"task_scope": "source_code", "status": "ready"}
    recorded = {}
    monkeypatch.setattr(module, "_record_prompt_step", lambda question, result, events: recorded.update(result))
    result = module._prompt_with_ledger(
        type("_TextOnlyBridge", (), {
            "prompt": lambda self, question: {
                "status": "ok",
                "answer": "unsupported source claim",
                "message": "agent_settled",
                "event_summary": {"tool_events": []},
            },
        })(),
        "查源码调用链",
    )

    assert result["status"] == "error"
    assert result["message"] == "source_code_tool_evidence_missing"
    assert result["answer"] == ""
    assert recorded["status"] == "error"


def test_pi_source_only_turn_accepts_bound_source_tool_result(monkeypatch):
    module = PiModule()
    module._context = {"task_scope": "source_code", "status": "ready"}
    recorded = {}
    monkeypatch.setattr(module, "_record_prompt_step", lambda question, result, events: recorded.update(result))
    result = module._prompt_with_ledger(
        type("_ToolBackedBridge", (), {
            "prompt": lambda self, question: {
                "status": "ok",
                "answer": "verified static result",
                "message": "agent_settled",
                "event_summary": {
                    "tool_events": [{"name": "code-analyze", "status": "ok"}],
                },
            },
        })(),
        "查源码调用链",
    )

    assert result["status"] == "ok"
    assert result["answer"] == "verified static result"
    assert recorded["status"] == "ok"


def test_pi_module_blocks_source_only_lookup_without_bound_code_context(monkeypatch, tmp_path):
    class _CapturePiBridge:
        def __init__(self, **kwargs):
            pass

    prompt_called = {"value": False}
    monkeypatch.setattr("ai.pi_bridge.PiBridge", _CapturePiBridge)
    module = PiModule()
    monkeypatch.setattr(module, "_prepare_analysis_run", lambda **_: None)
    monkeypatch.setattr(module, "_persist_context_artifact", lambda: None)
    monkeypatch.setattr(module, "_sync_analysis_run_context", lambda: None)
    monkeypatch.setattr("ai.modules.pi._build_evidence_anchor", lambda **_: None)

    def fake_prompt(_bridge, _question):
        prompt_called["value"] = True
        return {"status": "ok", "message": "fake", "answer": "unbound"}

    monkeypatch.setattr(module, "_prompt_with_ledger", fake_prompt)
    result = module.run(
        question="查当前 Gen6 源码调用链",
        provider="test-provider",
        project_root=str(tmp_path),
        tools=["code-analyze"],
    )

    assert result.ok is False
    assert result.data["context_status"] == "blocked"
    assert "source.code_context" in result.data["context_missing"]
    assert prompt_called["value"] is False


def test_pi_module_run_passes_plain_lifecycle_allowlist_to_pi(monkeypatch, tmp_path):
    captured = {}

    class _CapturePiBridge:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr("ai.pi_bridge.PiBridge", _CapturePiBridge)
    module = PiModule()
    monkeypatch.setattr(module, "_prepare_analysis_run", lambda **_: None)
    monkeypatch.setattr(module, "_persist_context_artifact", lambda: None)
    monkeypatch.setattr(module, "_sync_analysis_run_context", lambda: None)
    monkeypatch.setattr("ai.modules.pi._build_evidence_anchor", lambda **_: None)
    monkeypatch.setattr(
        module,
        "_prompt_with_ledger",
        lambda _bridge, _question: {"status": "ok", "message": "fake", "answer": "candidate"},
    )

    result = module.run(
        question="这个目标为什么没被检出，后面又突然消失了？",
        provider="test-provider",
        project_root=str(tmp_path),
        session_dir=str(tmp_path / "sessions"),
        context={"schema_version": "pi-orchestration-context.v1", "status": "partial"},
    )

    assert result.ok
    assert {"point-cloud-plan", "point-cloud-analyze", "point-cloud-read", "point-cloud-validate", "sim-verify"}.issubset(
        set(captured["tools"])
    )


def test_pi_plain_symptom_flow_can_execute_bounded_code_analyze_through_bridge(monkeypatch, tmp_path):
    captured = {}
    code_index = {
        "source_root": "/snapshot/gen6",
        "snapshot_hash": "gen6-source-hash",
        "parser": "codegraph_sqlite",
        "functions": [{"name": "PostProcessMainTI", "file_path": "postProcess.c"}],
        "calls": {
            "PostProcessMainTI": [f"Stage{i:02d}" for i in range(12)],
        },
    }

    class _CapturePiBridge:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    def fake_prompt(_bridge, _question):
        assert "code-analyze" in captured["tools"]
        response = invoke_capability(
            "code-analyze",
            {
                "kind": "call_chain",
                "name": "PostProcessMainTI",
                "max_depth": 1,
                "max_results": 4,
                "code_index": code_index,
            },
        )
        captured["code_analyze_response"] = response
        return {"status": "ok", "message": "fake bounded code lookup", "answer": "静态调用链已返回"}

    monkeypatch.setattr("ai.pi_bridge.PiBridge", _CapturePiBridge)
    module = PiModule()
    monkeypatch.setattr(module, "_prepare_analysis_run", lambda **_: None)
    monkeypatch.setattr(module, "_persist_context_artifact", lambda: None)
    monkeypatch.setattr(module, "_sync_analysis_run_context", lambda: None)
    monkeypatch.setattr("ai.modules.pi._build_evidence_anchor", lambda **_: None)
    monkeypatch.setattr(module, "_prompt_with_ledger", fake_prompt)

    result = module.run(
        question="这个目标为什么没被检出，后面又突然消失了？",
        provider="test-provider",
        project_root=str(tmp_path),
        session_dir=str(tmp_path / "sessions"),
        context={"schema_version": "pi-orchestration-context.v1", "status": "partial"},
    )

    tool_result = captured["code_analyze_response"]
    assert result.ok
    assert {"point-cloud-analyze", "code-analyze"}.issubset(set(captured["tools"]))
    assert tool_result["status"] == "ok"
    assert tool_result["data"]["result_bounds"] == {
        "limit": 4,
        "total_count": 12,
        "returned_count": 4,
        "truncated": True,
    }


def test_pi_bridge_cli_executes_bounded_code_analyze_json(capsys):
    code_index = {
        "source_root": "/snapshot/gen6",
        "snapshot_hash": "gen6-source-hash",
        "parser": "codegraph_sqlite",
        "functions": [{"name": "PostProcessMainTI", "file_path": "postProcess.c"}],
        "calls": {
            "PostProcessMainTI": [f"Stage{i:02d}" for i in range(12)],
        },
    }
    params = {
        "kind": "call_chain",
        "name": "PostProcessMainTI",
        "max_depth": 1,
        "max_results": 3,
        "code_index": code_index,
    }

    exit_code = _main([
        "--name", "code-analyze",
        "--params", json.dumps(params, ensure_ascii=False),
    ])
    response = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert response["status"] == "ok"
    assert response["data"]["result_bounds"] == {
        "limit": 3,
        "total_count": 12,
        "returned_count": 3,
        "truncated": True,
    }
    assert "3/12 rows; truncated" in response["message"]


def test_interactive_pi_starter_does_not_hide_perception_tools_behind_keywords():
    selected = _select_pi_tools(
        question="先帮我看一下",
        case_dir="",
        batch="",
        interactive=True,
    )
    assert selected is not None
    assert {"point-cloud-plan", "point-cloud-analyze", "point-cloud-read", "point-cloud-validate", "sim-verify"}.issubset(selected)
    assert "point-cloud-batch" not in selected
    assert len(selected) < len(available_capabilities())


def test_pi_prompt_requires_current_source_chain_before_code_reasoning():
    assert "固定功能模板" in DEFAULT_PI_SYSTEM_PROMPT
    assert "caller/callee" in DEFAULT_PI_SYSTEM_PROMPT
    assert "code-analyze/event-code-path" in DEFAULT_PI_SYSTEM_PROMPT
    assert "arbe 可视化工具报警灯对应的算法输出" in DEFAULT_PI_SYSTEM_PROMPT
    assert "inline nodes" in DEFAULT_PI_SYSTEM_PROMPT


def test_pi_prompt_does_not_turn_perception_field_mismatch_into_causal_evidence():
    assert "计数差异只证明存在差异" in DEFAULT_PI_SYSTEM_PROMPT
    assert "当前源码或 runtime 证据" in DEFAULT_PI_SYSTEM_PROMPT
    assert "最多记录 3 个候选并按当前证据排序" in DEFAULT_PI_SYSTEM_PROMPT
    assert "成本最低且区分度最高的一个实验" in DEFAULT_PI_SYSTEM_PROMPT
    assert "confirmed_by_user 只能由用户确认" in DEFAULT_PI_SYSTEM_PROMPT
    assert "cluster_id=-1" in DEFAULT_PI_SYSTEM_PROMPT
    assert "不能证明 track 被 TrackManage 删除" in DEFAULT_PI_SYSTEM_PROMPT
    assert "public_objectlist_output_rows" in DEFAULT_PI_SYSTEM_PROMPT
    assert "ros-topic-inventory" in DEFAULT_PI_SYSTEM_PROMPT
    assert "没有共同 message_seq" in DEFAULT_PI_SYSTEM_PROMPT
    assert "新本地 output artifact" in DEFAULT_PI_SYSTEM_PROMPT
    assert "同一个 preflight_path" in DEFAULT_PI_SYSTEM_PROMPT
    assert "evidence-query runtime_snapshot_path" in DEFAULT_PI_SYSTEM_PROMPT
    assert "frame_id 查询不能命中 unbound ObjectList" in DEFAULT_PI_SYSTEM_PROMPT
    assert "不代表完整 candidate/mature 内部航迹集合" in DEFAULT_PI_SYSTEM_PROMPT
    assert "unique_cluster_track_pairs_where_point_track_uid_matches_captured_public_objectlist_id" in DEFAULT_PI_SYSTEM_PROMPT
    assert "不能推断 gate/maturity" in DEFAULT_PI_SYSTEM_PROMPT
    assert "不得据此断言它进入或未进入 track gate" in DEFAULT_PI_SYSTEM_PROMPT
    assert "若没有独立证据区分机制，应返回 0 个 hypothesis" in DEFAULT_PI_SYSTEM_PROMPT
    assert "不要为了 Top-3 配额填满候选" in DEFAULT_PI_SYSTEM_PROMPT
    assert "raw_relation_counts 统计提交的原始边行，可能包含重复或无效行" in DEFAULT_PI_SYSTEM_PROMPT
    assert "relation_summaries 的 unique_from_node_count/unique_to_node_count" in DEFAULT_PI_SYSTEM_PROMPT
    assert "interpret relation_summaries by its from_node_kind/to_node_kind" in DEFAULT_PI_SYSTEM_PROMPT
    assert "cluster_id=0 与 -1 都没有此边" in DEFAULT_PI_SYSTEM_PROMPT
    assert "读取 point-cloud-read section=timeline" in DEFAULT_PI_SYSTEM_PROMPT
    assert "public UID recurrence 与 physical identity" in DEFAULT_PI_SYSTEM_PROMPT
    assert "timeline.uid_recurrence_status=`derived`" in DEFAULT_PI_SYSTEM_PROMPT
    assert "UID 消失/重现只报告缺口" in DEFAULT_PI_SYSTEM_PROMPT
    assert "若 invalid_edge_count=0，raw 与规范计数差只应解释为重复关系行" in DEFAULT_PI_SYSTEM_PROMPT
    assert "不得称 lost/untracked/gate failure" in DEFAULT_PI_SYSTEM_PROMPT
    assert "跨点迹数、簇数、航迹数的比值必须标成实体数之比" in DEFAULT_PI_SYSTEM_PROMPT
    assert "不能称覆盖率/成功率/过滤率" in DEFAULT_PI_SYSTEM_PROMPT
    assert "captured public-ID-match edge 的 cluster nodes" in DEFAULT_PI_SYSTEM_PROMPT
    assert "observed-cluster public-ID-match fraction" in DEFAULT_PI_SYSTEM_PROMPT


def test_pi_context_path_receives_deterministic_perception_anchor_before_prompt_build(tmp_path):
    context_path = tmp_path / "pi-context.json"
    context_path.write_text(json.dumps({
        "schema_version": "pi-orchestration-context.v1",
        "status": "ready",
        "run_id": "run-1",
        "context_fingerprint": "ctx-1",
        "project": {}, "data": {}, "source": {}, "build": {}, "runtime": {},
        "policy": {}, "artifacts": [], "freshness": {}, "missing": [], "conflicts": [], "diagnostics": [],
    }), encoding="utf-8")
    anchor = {
        "schema_version": "deterministic-evidence-anchor.v1",
        "status": "ready",
        "perception_report": {"lineage": {"node_counts": {"points": 31440, "clusters": 10576, "tracks": 3260, "outputs": 3260}}},
    }
    context = _load_pi_context_with_anchor(None, context_path=str(context_path), evidence_anchor=anchor)
    assert context is not None
    bridge = PiBridge(context=context)
    prompt = bridge._context_system_prompt()
    assert context["evidence_anchor"] == anchor
    assert '"points": 31440' in prompt
    assert '"clusters": 10576' in prompt
    assert '"tracks": 3260' in prompt


def test_pi_perception_anchor_reports_full_counts_when_inline_lineage_is_truncated(tmp_path):
    report_path = tmp_path / "perception-report.json"
    report_path.write_text(json.dumps({
        "schema_version": "perception-report.v1",
        "status": "partial",
        "analysis": {
            "status": "partial",
            "input_contract": {"point_count": 31440, "points_truncated": True, "points_artifact": {"point_count": 31440}},
            "stage_coverage": {"stages": []},
            "lineage": {
                "status": "derived",
                "edge_count": 40257,
                "raw_edge_count": 40257,
                "invalid_edge_count": 0,
                "relation_summaries": {"cluster_supports_track": {"from_node_kind": "clusters", "to_node_kind": "tracks", "edge_row_count": 3451, "unique_pair_count": 3451, "unique_from_node_count": 3451, "unique_to_node_count": 2485}},
                "relation_counts": {"cluster_supports_track": 3451},
                "raw_relation_counts": {"cluster_supports_track": 11265},
                "relation_scopes": {"point_supports_cluster": {"population": "public_pointcloud_rows", "inclusion_condition": "cluster_id > 0", "basis": "PointCloud2.cluster_id <- algo_dotInfoC[i].clusterID", "limitation": "rows with cluster_id <= 0 do not enter this relation"}},
                "track_population": {
                    "status": "observed_subset",
                    "scope": "public_objectlist_output_rows",
                    "track_nodes_mirror_output_rows": True,
                    "internal_candidate_track_population": "not_available",
                    "internal_mature_track_population": "not_available",
                    "cluster_supports_track_scope": "unique_cluster_track_pairs_where_point_track_uid_matches_captured_public_objectlist_id",
                    "track_emits_output_scope": "one_unique_derived_edge_per_captured_public_objectlist_output_row",
                    "unclustered_point_scope": "cluster_id_minus_one_has_no_cluster_node_or_point_support_edge; track_lifecycle_not_inferred",
                    "limitation": "track nodes mirror captured public objectlist output rows",
                },
                "node_counts": {"points": 31440, "clusters": 10576, "tracks": 3260, "outputs": 3260},
                "nodes": {"points": [{"point_key": "prefix-only"}], "clusters": [], "tracks": [], "outputs": [], "points_truncated": True},
                "edges": [], "raw_edges": [], "invalid_edges": [],
            },
            "run_evidence": {}, "scene": {}, "callback_binding_summary": {},
            "timeline": {
                "status": "observed",
                "selected_frame": "cap:radar2:callback:2-3",
                "uid_recurrence_status": "observed",
                "uid_recurrence_scope": "public_objectlist_output_rows_adjacent_callbacks_same_capture_and_radar",
                "public_uid_recurrences": [{
                    "previous_frame_key": "cap:radar2:callback:1-2",
                    "current_frame_key": "cap:radar2:callback:2-3",
                    "algorithm_track_id": 43,
                    "status": "derived",
                    "match_grade": "same_public_uid_adjacent_callback",
                    "limitation": "same UID recurrence only; no physical identity claim",
                }],
            },
            "source_execution_contract": {}, "code_flow": {}, "gaps": [],
        },
    }), encoding="utf-8")
    anchor = _build_evidence_anchor(
        question="分析点云感知回放",
        case_dir="",
        discovered={},
        kwargs={"perception_report_path": str(report_path)},
    )
    assert anchor is not None
    assert anchor["status"] == "ready"
    assert anchor["perception_report"]["lineage"]["node_counts"] == {
        "points": 31440, "clusters": 10576, "tracks": 3260, "outputs": 3260,
    }
    assert anchor["perception_report"]["lineage"]["edge_count"] == 40257
    assert anchor["perception_report"]["lineage"]["track_population"]["scope"] == "public_objectlist_output_rows"
    assert anchor["perception_report"]["lineage"]["track_population"]["internal_candidate_track_population"] == "not_available"
    assert anchor["perception_report"]["lineage"]["relation_summaries"]["cluster_supports_track"]["unique_pair_count"] == 3451
    assert anchor["perception_report"]["lineage"]["raw_relation_counts"]["cluster_supports_track"] == 11265
    assert anchor["perception_report"]["lineage"]["relation_scopes"]["point_supports_cluster"]["inclusion_condition"] == "cluster_id > 0"
    assert anchor["perception_report"]["timeline"]["uid_recurrence_status"] == "observed"
    assert anchor["perception_report"]["timeline"]["public_uid_recurrences"][0]["match_grade"] == "same_public_uid_adjacent_callback"


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
    ledger.append_user_observation(
        "run-trail",
        kind="feedback_confirmed",
        summary="用户确认这个候选是正报",
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
    assert any(item["kind"] == "feedback_confirmed" for item in report["analysis_trace"]["user_observations"])
    html = (tmp_path / "diagnostic-report" / "diagnostic-report.html").read_text(encoding="utf-8")
    assert "Hypothesis Board" in html
    assert "Next Experiments" in html
    assert "用户确认" in html


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


def test_pi_empty_final_answer_is_not_success_and_preserves_tool_artifact(tmp_path):
    artifact = tmp_path / "bounded-code-result.json"
    module = PiModule()
    module._events = [{
        "type": "tool_execution_end",
        "toolName": "code-analyze",
        "result": {
            "status": "ok",
            "details": {"artifacts": [{"path": str(artifact)}]},
        },
    }]

    result = module._result_from_prompt(
        {
            "status": "ok",
            "message": "agent_settled",
            "answer": "",
            "event_summary": {"assistant_messages": [{"stop_reason": "length"}]},
        },
        case_dir="",
    )

    assert result.ok is False
    assert result.data["error"] == "empty_final_answer"
    assert result.data["tool_calls"] == [{
        "name": "code-analyze",
        "event_type": "tool_execution_end",
        "status": "ok",
    }]
    assert result.artifacts == [str(artifact)]
    assert result.data["tool_artifact_refs"] == [{"path": str(artifact)}]
    assert result.data["pi_event_summary"]["assistant_messages"][0]["stop_reason"] == "length"


def test_pi_source_code_empty_answer_projects_completed_code_analyze_result():
    module = PiModule()
    module._context = {"task_scope": "source_code"}
    module._events = [{
        "type": "tool_execution_end",
        "toolName": "code-analyze",
        "toolCallId": "call-1",
        "status": "ok",
        "result": {
            "status": "ok",
            "details": {
                "status": "ok",
                "data": {
                    "kind": "call_chain",
                    "backend": "source_code_index",
                    "source_context": {"snapshot_hash": "source-hash"},
                    "data": [
                        {"path": "PostProcessMainTI -> DataProcInit"},
                        {"path": "PostProcessMainTI -> DotPrePosTI"},
                    ],
                    "result_bounds": {
                        "limit": 2,
                        "total_count": 13,
                        "returned_count": 2,
                        "truncated": True,
                    },
                },
                "artifacts": [{"path": "outputs/code-analyze.json"}],
            },
        },
    }]

    result = module._result_from_prompt(
        {"status": "ok", "message": "agent_settled", "answer": ""},
        case_dir="",
    )

    assert result.ok is True
    assert result.data["answer_mode"] == "tool_result_projection"
    assert result.data["ai_final_synthesis_status"] == "not_available"
    assert "2/13" in result.data["answer"]
    assert "source-hash" in result.data["answer"]
    assert "PostProcessMainTI -> DotPrePosTI" in result.data["answer"]
    assert "不代表编译或 runtime 命中" in result.data["answer"]
    assert result.artifacts == ["outputs/code-analyze.json"]


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
