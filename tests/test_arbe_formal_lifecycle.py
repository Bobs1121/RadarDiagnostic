# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path

from ai.capability.registry import capability_catalog
from ai.capability.module_bridge import build_module_tool_registry
from ai.modules import MODULE_REGISTRY
from ai.modules.arbe_formal_start import ArbeFormalStartModule
from ai.modules.arbe_formal_stop import ArbeFormalStopModule


ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT.parent / "cr60-debug-harness"
PROFILE = HARNESS / "config" / "arbe_noetic_example.toml"


def test_formal_start_and_stop_are_registered_as_approval_gated_atomic_tools():
    assert MODULE_REGISTRY["arbe-formal-start"] is ArbeFormalStartModule
    assert MODULE_REGISTRY["arbe-formal-stop"] is ArbeFormalStopModule
    entries = {item["name"]: item for item in capability_catalog()}
    assert entries["arbe-formal-start"]["expose_to_pi"] is True
    assert entries["arbe-formal-start"]["requires_approval"] is True
    assert "atomic" in entries["arbe-formal-stop"]["tags"]


def test_formal_start_plan_only_does_not_touch_remote_workspace():
    result = ArbeFormalStartModule().safe_run(
        harness_root=str(HARNESS),
        profile=str(PROFILE),
    )
    assert result.ok is True
    assert result.data["status"] == "planned"
    assert result.data["mode"] == "arbe_formal_start"
    assert "tools.run_arbe_formal_start" in result.data["command"]
    assert "--execute" not in result.data["command"]


def test_formal_start_execute_requires_approval():
    result = ArbeFormalStartModule().safe_run(
        harness_root=str(HARNESS),
        profile=str(PROFILE),
        execute=True,
        approved=False,
    )
    assert result.ok is True
    assert result.data["status"] == "approval_required"
    assert result.data["execute_requested"] is True


def test_formal_stop_plan_only_requires_an_owned_session(tmp_path):
    session = tmp_path / "start-session.json"
    session.write_text(
        json.dumps(
            {
                "schema_version": "arbe-start-session.v1",
                "status": "started",
                "session_id": "s1",
                "ownership": "tool_started",
                "target": {"host": "host"},
                "start": {"pid": 1234, "ros_master_uri": "http://127.0.0.1:11311"},
            }
        ),
        encoding="utf-8",
    )
    result = ArbeFormalStopModule().safe_run(
        harness_root=str(HARNESS),
        profile=str(PROFILE),
        session_path=str(session),
    )
    assert result.ok is True
    assert result.data["status"] == "planned"
    assert result.data["mode"] == "arbe_formal_stop"


def test_formal_stop_blocks_external_session_before_remote_execution(tmp_path):
    session = tmp_path / "external-session.json"
    session.write_text(
        json.dumps(
            {
                "schema_version": "arbe-start-session.v1",
                "status": "already_running",
                "session_id": "external",
                "ownership": "external",
                "target": {"host": "host"},
                "start": {"pid": None},
            }
        ),
        encoding="utf-8",
    )
    result = ArbeFormalStopModule().safe_run(
        harness_root=str(HARNESS),
        profile=str(PROFILE),
        session_path=str(session),
    )
    assert result.ok is False
    assert result.data["status"] == "blocked"
    assert "arbe_start_session_not_tool_owned" in result.data["blockers"]


def test_module_bridge_blocks_formal_start_side_effect_without_supervisor_permission():
    tools = build_module_tool_registry(names=["arbe-formal-start"])
    result = tools["arbe-formal-start"].safe_execute(
        {"harness_root": str(HARNESS), "profile": str(PROFILE), "execute": True, "approved": True}
    )
    assert result["status"] == "error"
    assert result["data"]["approval_required"] is True
