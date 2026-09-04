# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from ai.capability.module_bridge import build_module_tool_registry
from ai.modules import MODULE_REGISTRY
from ai.modules.runtime_debug_attach import RuntimeDebugAttachModule
from ai.providers.cr60_harness import Cr60HarnessProvider


ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT.parent / "cr60-debug-harness"
PROFILE = HARNESS / "config" / "arbe_noetic_example.toml"


def _write_plan(tmp_path: Path, *, status: str = "partial") -> Path:
    plan = {
        "schema_version": "runtime-debug-plan.v1",
        "status": status,
        "execution_status": "approval_required" if status != "blocked" else "blocked",
        "event": {"event_id": "event-1", "radar_id": 2, "target_frame": 47877},
        "replay": {"strategy": "sgu_injection"},
        "target": {"obj_id": 44},
        "breakpoints": [{
            "function": "Gate",
            "location": {"file": "src/gate.c", "line": 1},
            "condition": "frame_counter == 47877",
            "watch": ["frame_counter", "i"],
        }],
        "gdb_commands": ["break src/gate.c:1 if frame_counter == 47877"],
        "capture_fields": [{"token": "frame_counter"}],
        "readiness": {
            "status": status,
            "blocking_gates": ["binary"] if status == "blocked" else [],
            "warning_gates": [],
            "gates": [],
        },
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
    }
    value.update(extra)
    return value


def test_formal_attach_is_registered_and_plan_only_is_safe(tmp_path):
    assert MODULE_REGISTRY["runtime-debug-attach"] is RuntimeDebugAttachModule
    result = RuntimeDebugAttachModule().safe_run(**_params(_write_plan(tmp_path)))
    assert result.ok is True
    assert result.data["status"] == "planned"
    assert result.data["mode"] == "gdb_formal_attach"
    assert "tools.run_gdb_attach_plan" in result.data["command"]
    assert "--execute" not in result.data["command"]
    assert "--replay" not in result.data["command"]


def test_formal_attach_requires_approval(tmp_path):
    result = RuntimeDebugAttachModule().safe_run(
        **_params(_write_plan(tmp_path), execute=True, approved=False)
    )
    assert result.ok is True
    assert result.data["status"] == "approval_required"
    assert result.data["execute_requested"] is True


def test_formal_attach_refuses_blocked_plan(tmp_path):
    result = RuntimeDebugAttachModule().safe_run(
        **_params(_write_plan(tmp_path, status="blocked"), execute=True, approved=True)
    )
    assert result.ok is False
    assert "plan is blocked" in result.message


def test_formal_attach_bounds_provider_result_and_preserves_artifact(tmp_path):
    plan_path = _write_plan(tmp_path)
    output_path = tmp_path / "attach-result.json"
    payload = {
        "schema_version": "cr60-harness-provider.v1",
        "mode": "gdb_formal_attach",
        "status": "completed_with_runtime_warnings",
        "command": ["python", "runner"],
        "command_display": "python runner",
        "stdout": "FULL FORMAL ATTACH TRANSCRIPT",
        "session_output": str(tmp_path / "session.json"),
        "gdb_session_status": "succeeded",
        "gdb_evidence_status": "partial",
        "attach_status": "attached",
        "diagnostics": ["gdb_expression_not_observed"],
        "artifacts": [str(tmp_path / "session.json")],
    }
    with patch.object(Cr60HarnessProvider, "run_gdb_attach_plan", return_value=payload):
        result = RuntimeDebugAttachModule().safe_run(
            **_params(plan_path, execute=True, approved=True, output=str(output_path))
        )
    assert result.ok is True
    assert "stdout" not in result.data
    stored = json.loads(output_path.read_text(encoding="utf-8"))
    assert stored["stdout"] == payload["stdout"]
    assert stored["artifact_path"] == str(output_path.resolve())


def test_formal_attach_returns_approval_gated_isolated_fallback_when_blocked(tmp_path):
    plan_path = _write_plan(tmp_path)
    output_path = tmp_path / "blocked-attach.json"
    payload = {
        "schema_version": "cr60-harness-provider.v1",
        "mode": "gdb_formal_attach",
        "status": "blocked",
        "command": ["python", "runner"],
        "artifacts": [],
        "diagnostics": ["formal_attach_blocked:gdb_attach_failed"],
    }
    with patch.object(Cr60HarnessProvider, "run_gdb_attach_plan", return_value=payload):
        result = RuntimeDebugAttachModule().safe_run(
            **_params(plan_path, execute=True, approved=True, output=str(output_path))
        )
    assert result.ok is False
    assert result.data["fallback"]["capability"] == "runtime-debug-run"
    assert result.data["fallback"]["requires_approval"] is True
    assert result.data["fallback"]["params"]["target_frame"] == 47877
    assert json.loads(output_path.read_text(encoding="utf-8"))["fallback"]["capability"] == "runtime-debug-run"


def test_module_bridge_exposes_formal_attach_approval_gate(tmp_path):
    tools = build_module_tool_registry(names=["runtime-debug-attach"])
    result = tools["runtime-debug-attach"].safe_execute(
        _params(_write_plan(tmp_path), execute=True, approved=True)
    )
    assert result["status"] == "error"
    assert result["data"]["approval_required"] is True
