# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from ai.capability.module_bridge import build_module_tool_registry
from ai.modules import MODULE_REGISTRY
from ai.modules.runtime_debug_run import RuntimeDebugRunModule
from ai.providers.cr60_harness import Cr60HarnessProvider


ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT.parent / "cr60-debug-harness"
PROFILE = HARNESS / "config" / "arbe_noetic_example.toml"


def _write_plan(tmp_path: Path) -> Path:
    plan = {
        "schema_version": "runtime-debug-plan.v1",
        "status": "partial",
        "execution_status": "approval_required",
        "event": {"event_id": "event-1", "radar_id": 2, "target_frame": 47877},
        "replay": {"strategy": "sgu_injection"},
        "target": {"obj_id": 44},
        "breakpoints": [{"function": "Gate", "location": {"file": "src/gate.c", "line": 1}, "condition": "frame_counter == 47877", "watch": ["frame_counter"]}],
        "gdb_commands": ["break src/gate.c:1 if frame_counter == 47877"],
        "capture_fields": [{"token": "frame_counter"}],
        "readiness": {"status": "partial", "blocking_gates": [], "warning_gates": ["approval"], "gates": []},
    }
    path = tmp_path / "runtime-debug-plan.json"
    path.write_text(json.dumps(plan), encoding="utf-8")
    return path


def _params(plan: Path, **extra):
    value = {
        "harness_root": str(HARNESS),
        "profile": str(PROFILE),
        "bag": "/home/hoz2wx/CR60LIGHT/data/qzh/CRGVI-1829/corner_radar_net_2026-07-19-11-56-15_11.bag",
        "debug_plan_path": str(plan),
        "target_frame": 47877,
        "radar_id": 2,
        "start_sec": 518.9,
        "duration_sec": 3.0,
        "session_output": str(ROOT / "outputs" / "test_gdb_session.json"),
    }
    value.update(extra)
    return value


def test_runtime_debug_run_is_registered_and_plan_only_is_safe(tmp_path):
    assert MODULE_REGISTRY["runtime-debug-run"] is RuntimeDebugRunModule
    result = RuntimeDebugRunModule().safe_run(**_params(_write_plan(tmp_path)))
    assert result.ok is True
    assert result.data["status"] == "planned"
    assert result.data["mode"] == "gdb_isolated_plan"
    assert "--debug-plan" in result.data["command"]


def test_runtime_debug_run_requires_approval_for_execute(tmp_path):
    result = RuntimeDebugRunModule().safe_run(**_params(_write_plan(tmp_path), execute=True, approved=False))
    assert result.ok is True
    assert result.data["status"] == "approval_required"
    assert "requires explicit approved=true" in result.data["diagnostics"][0]


def test_runtime_debug_run_refuses_blocked_plan_even_when_approved(tmp_path):
    plan_path = _write_plan(tmp_path)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan["status"] = "blocked"
    plan["execution_status"] = "blocked"
    plan["readiness"]["status"] = "blocked"
    plan["readiness"]["blocking_gates"] = ["binary"]
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    result = RuntimeDebugRunModule().safe_run(**_params(plan_path, execute=True, approved=True))
    assert result.ok is False
    assert "plan is blocked" in result.message


def test_module_bridge_rejects_execute_without_supervisor_permission(tmp_path):
    tools = build_module_tool_registry(names=["runtime-debug-run"])
    result = tools["runtime-debug-run"].safe_execute(_params(_write_plan(tmp_path), execute=True, approved=True))
    assert result["status"] == "error"
    assert result["data"]["approval_required"] is True


def test_runtime_debug_run_bounds_inline_result_but_preserves_transcript_artifact(tmp_path):
    plan_path = _write_plan(tmp_path)
    output_path = tmp_path / "provider-result.json"
    provider_payload = {
        "schema_version": "cr60-harness-provider.v1",
        "mode": "gdb_isolated_plan",
        "status": "completed_with_runtime_warnings",
        "execute_requested": True,
        "command": ["python", "runner"],
        "command_display": "python runner",
        "stdout": "FULL TRANSCRIPT SHOULD NOT BE INLINE",
        "stderr": "",
        "session_output": str(tmp_path / "session.json"),
        "gdb_session_status": "succeeded",
        "gdb_evidence_status": "partial",
        "diagnostics": ["gdb_command_error_present"],
        "artifacts": [str(tmp_path / "session.json")],
    }
    with patch.object(Cr60HarnessProvider, "run_gdb_plan", return_value=provider_payload):
        result = RuntimeDebugRunModule().safe_run(
            **_params(
                plan_path,
                execute=True,
                approved=True,
                output=str(output_path),
            )
        )
    assert result.ok is True
    assert "stdout" not in result.data
    assert result.data["artifact_path"] == str(output_path.resolve())
    stored = json.loads(output_path.read_text(encoding="utf-8"))
    assert stored["stdout"] == provider_payload["stdout"]
    assert stored["artifact_path"] == str(output_path.resolve())
