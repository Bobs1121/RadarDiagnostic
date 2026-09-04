# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path

from ai.modules import MODULE_REGISTRY
from ai.modules.base import ModuleResult
from ai.modules.cr60_precheck import CR60PrecheckModule
from ai.capability.registry import capability_catalog
from ai.providers.cr60_harness import (
    Cr60HarnessProvider,
    HarnessCommandResult,
    _last_json_object,
    convert_intake_to_manifest,
)
from ai.capability.module_bridge import ModuleToolAdapter, build_module_tool_registry
from ai.agent_loop import AgentLoop
from engines.arbe.intake import build_intake


def _fake_harness_root(tmp_path: Path) -> Path:
    root = tmp_path / "harness"
    (root / "cr60_debug_harness").mkdir(parents=True)
    (root / "tools").mkdir()
    (root / "web").mkdir()
    (root / "cr60_debug_harness" / "cli.py").write_text("", encoding="utf-8")
    (root / "tools" / "build_html_reports.py").write_text("", encoding="utf-8")
    (root / "config.toml").write_text("", encoding="utf-8")
    return root


class _FakeExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], Path, float]] = []

    def run(self, command: list[str], *, cwd: Path, timeout_sec: float) -> HarnessCommandResult:
        self.calls.append((command, cwd, timeout_sec))
        return HarnessCommandResult(
            command=tuple(command),
            returncode=0,
            stdout=json.dumps({"failed_count": 0, "blocked_count": 0}),
        )


def test_provider_builds_shell_free_folder_command(tmp_path: Path):
    root = _fake_harness_root(tmp_path)
    provider = Cr60HarnessProvider(harness_root=root, python_executable="python")
    command = provider.build_folder_command(
        profile="config.toml",
        input_dir="/home/test/data",
        output_dir=tmp_path / "out",
        context=str(tmp_path / "context.json"),
        functions=["FCTA", "FCTB"],
        customer_claim='quote "is preserved"',
    )

    assert command[:5] == ["python", "-m", "cr60_debug_harness.cli", "folder-analyze", "--profile"]
    assert str(root / "config.toml") in command
    assert "--input-dir" in command
    assert "--context" in command
    assert "--function" in command
    assert "quote \"is preserved\"" in command


def test_provider_returns_per_case_artifact_refs_after_batch_execution(tmp_path: Path):
    root = _fake_harness_root(tmp_path)
    output = tmp_path / "out"
    case = output / "cases" / "case-1"
    data = output / "data" / "case-1"
    case.mkdir(parents=True)
    data.mkdir(parents=True)
    (case / "diagnosis_bundle.json").write_text("{}", encoding="utf-8")
    (data / "viewer-model.json").write_text("{}", encoding="utf-8")
    (data / "report.html").write_text("<html></html>", encoding="utf-8")
    provider = Cr60HarnessProvider(harness_root=root, executor=_FakeExecutor())
    result = provider.run_command(
        ["python", "-m", "fake"], execute=True, mode="folder", output_dir=output
    )
    assert result["output_dir"] == str(output.resolve())
    assert result["case_artifacts"] == [{
        "case_id": "case-1",
        "bundle_path": str((case / "diagnosis_bundle.json").resolve()),
        "viewer_model_path": str((data / "viewer-model.json").resolve()),
        "report_path": str((data / "report.html").resolve()),
    }]


def test_provider_plan_does_not_execute_or_create_output(tmp_path: Path):
    root = _fake_harness_root(tmp_path)
    executor = _FakeExecutor()
    output = tmp_path / "not-created"
    context = tmp_path / "context.json"
    context.write_text("{}", encoding="utf-8")
    provider = Cr60HarnessProvider(harness_root=root, executor=executor)
    result = provider.run_folder(
        profile="config.toml",
        input_dir="/home/test/data",
        output_dir=output,
        context=str(context),
        execute=False,
    )

    assert result["status"] == "planned"
    assert executor.calls == []
    assert not output.exists()


def test_handoff_conversion_preserves_each_case_and_provenance(tmp_path: Path):
    bag = tmp_path / "sample.bag"
    bag.write_bytes(b"bag")
    intake = build_intake(
        data_paths=[str(bag)],
        ticket_id="CRGVI-1829",
        software_version="BL03RC02.7_S",
        vehicle="QZHCX",
        coem="BYD_UKE",
        code_branch="release/BL03RC02.7_S",
        function=["FCTA", "FCTB"],
    )
    assert intake["status"] == "ready"
    manifest, errors, warnings = convert_intake_to_manifest(intake, source_path="intake.json")

    assert errors == []
    assert warnings == []
    assert manifest is not None
    case = manifest["cases"][0]
    assert case["case_id"] == "CRGVI-1829"
    assert case["bag"] == str(bag)
    assert case["functions"] == ["FCTA", "FCTB"]
    assert case["upstream_provenance"]["handoff_id"] == intake["handoff_id"]


def test_handoff_requires_explicit_allow_for_partial(tmp_path: Path):
    intake = build_intake(
        data_paths=["/home/test/sample.bag"],
        software_version="v1",
        vehicle="TEST",
        coem="TEST_COEM",
        code_branch="main",
    )
    assert intake["status"] == "partial"
    manifest, errors, _ = convert_intake_to_manifest(intake)
    assert manifest is None
    assert any("allow_partial" in item for item in errors)
    manifest, errors, _ = convert_intake_to_manifest(intake, allow_partial=True)
    assert errors == []
    assert manifest is not None


def test_precheck_module_returns_provider_payload(tmp_path: Path):
    root = _fake_harness_root(tmp_path)
    executor = _FakeExecutor()
    module = CR60PrecheckModule()
    context = tmp_path / "context.json"
    context.write_text("{}", encoding="utf-8")
    # `context` only needs to be a declared artifact for command planning; the
    # independent harness validates its contents when the command executes.
    result = module.safe_run(
        mode="folder",
        harness_root=str(root),
        profile="config.toml",
        input_dir="/home/test/data",
        output_dir=str(tmp_path / "out"),
        context=str(context),
        execute=False,
    )

    assert isinstance(result, ModuleResult)
    assert result.ok is True
    assert result.data["schema_version"] == "cr60-harness-provider.v1"
    assert result.data["status"] == "planned"
    assert MODULE_REGISTRY["cr60-precheck"] is CR60PrecheckModule


def test_provider_prefers_outer_json_summary_with_nested_objects():
    parsed = _last_json_object("log line\n{\n  \"summary\": {\"blocked_count\": 0}\n}\n")
    assert parsed == {"summary": {"blocked_count": 0}}


def test_provider_plans_existing_manifest_mode(tmp_path: Path):
    root = _fake_harness_root(tmp_path)
    context = tmp_path / "context.json"
    context.write_text("{}", encoding="utf-8")
    manifest = tmp_path / "manifest.toml"
    manifest.write_text('[[cases]]\ncase_id = "case-1"\nbag = "/tmp/a.bag"\n', encoding="utf-8")
    provider = Cr60HarnessProvider(harness_root=root, python_executable="python")
    result = provider.run_manifest(
        profile="config.toml",
        manifest=manifest,
        output_dir=tmp_path / "out",
        context=str(context),
        execute=False,
    )
    assert result["status"] == "planned"
    assert result["mode"] == "manifest"
    assert result["command"][3] == "batch-analyze"
    assert str(manifest) in result["command"]


def test_precheck_module_accepts_manifest_mode(tmp_path: Path):
    root = _fake_harness_root(tmp_path)
    context = tmp_path / "context.json"
    context.write_text("{}", encoding="utf-8")
    manifest = tmp_path / "manifest.toml"
    manifest.write_text('[[cases]]\ncase_id = "case-1"\nbag = "/tmp/a.bag"\n', encoding="utf-8")
    result = CR60PrecheckModule().safe_run(
        mode="manifest",
        harness_root=str(root),
        profile="config.toml",
        manifest_path=str(manifest),
        output_dir=str(tmp_path / "out"),
        context=str(context),
        execute=False,
    )
    assert result.ok is True
    assert result.data["mode"] == "manifest"
    assert result.data["status"] == "planned"


def test_capability_catalog_exposes_module_input_schema():
    entry = next(item for item in capability_catalog() if item["name"] == "cr60-precheck")
    assert entry["kind"] == "module"
    assert entry["parameters"]["required"] == ["mode", "harness_root", "profile", "output_dir"]
    assert entry["output_schema"]["required"] == ["schema_version", "status", "mode", "command"]


def test_module_bridge_calls_safe_plan_and_blocks_unapproved_execute(tmp_path: Path):
    tools = build_module_tool_registry(names=["cr60-precheck"])
    tool = tools["cr60-precheck"]
    context = tmp_path / "context.json"
    context.write_text("{}", encoding="utf-8")
    root = _fake_harness_root(tmp_path)
    params = {
        "mode": "folder",
        "harness_root": str(root),
        "profile": "config.toml",
        "input_dir": "/home/test/data",
        "output_dir": str(tmp_path / "out"),
        "context": str(context),
    }
    planned = tool.safe_execute(params)
    assert planned["status"] == "ok"
    assert planned["data"]["status"] == "planned"

    blocked = tool.safe_execute({**params, "execute": True})
    assert blocked["status"] == "error"
    assert blocked["data"]["approval_required"] is True


def test_module_bridge_can_be_opened_by_supervisor_after_approval(tmp_path: Path):
    class _TinyModule:
        name = "tiny"
        description = "tiny"
        input_schema = {"type": "object", "properties": {"value": {"type": "string"}}}

        def __init__(self):
            pass

        def safe_run(self, **params):
            return type("Result", (), {"ok": True, "data": params, "message": "ok", "artifacts": []})()

    adapter = ModuleToolAdapter(_TinyModule, allow_execution=True)
    result = adapter.safe_execute({"value": "approved"})
    assert result["status"] == "ok"
    assert result["data"]["value"] == "approved"


def test_default_module_bridge_discovers_registered_leaf_capabilities():
    tools = build_module_tool_registry()
    assert {"code-analyze", "code-learn", "signal-extract", "public-topic-plan"}.issubset(
        tools
    )
    assert "pi" not in tools
    assert "agent-repl" not in tools
    assert "agent-loop" not in tools


def test_project_init_is_approval_gated_in_module_bridge():
    tools = build_module_tool_registry(names=["project-init"])
    blocked = tools["project-init"].safe_execute({"name": "x", "code_root": "x"})
    assert blocked["status"] == "error"
    assert blocked["data"]["approval_required"] is True


def test_pi_can_compose_code_gdb_plan_into_gdb_service_with_typed_ref():
    from tests.test_code_gdb_plan import _index

    registry = build_module_tool_registry(
        names=["code-gdb-plan", "gdb-service"]
    )
    state = AgentLoop(registry).run([
        {
            "tool": "code-gdb-plan",
            "params": {
                "code_index": _index(),
                "function_name": "RuntimeGate",
                "line": 70,
                "watch_variables": ["warning_flag"],
            },
        },
        {
            "tool": "gdb-service",
            "params": {
                "target": {"host": "10.190.171.44", "pid": 42, "program": "/tmp/program"},
                "commands": {"$ref": "steps[0].result.data.gdb_commands"},
            },
        },
    ])
    assert state.status == "completed"
    assert state.steps[1].resolved_params["commands"]
    assert state.steps[1].result["data"]["status"] == "planned"
