# -*- coding: utf-8 -*-
from __future__ import annotations

from ai.capability.registry import capability_catalog
from ai.modules import MODULE_REGISTRY
from ai.modules.runtime_debug_plan import RuntimeDebugPlanModule
from engines.runtime_debug_plan import build_runtime_debug_plan


def _bundle() -> dict:
    return {
        "schema_version": "diagnosis-bundle.v1",
        "status": "ready",
        "case": {"case_id": "C1", "bag": "/data/C1/a.bag"},
        "provenance": {
            "bag_path": "/data/C1/a.bag",
            "source_context_id": "ctx-1",
            "source_snapshot_hash": "source-1",
        },
        "source_context": {
            "source_context_id": "ctx-1",
            "source_snapshot_hash": "source-1",
            "status": "resolved",
            "identity": {"outer_head": "outer-1", "algo_head": "algo-1"},
        },
        "code_evidence": {"snapshot_hash": "source-1"},
        "runtime_schema": {"schema_version": "runtime-schema.v1"},
        "alarm_events": [{
            "event_id": "event-1",
            "function": "FCTA_R",
            "radar_id": 2,
            "replay_plan": {
                "target_frame_id": 100,
                "target_frame_source": "recorded_first_on_frame",
                "strategy": "sgu_injection",
                "warmup": {"ready": True, "actual_frames": 5},
            },
            "frame_precheck": {"alarm_first_frame_confidence": "recorded_frame_id"},
            "selected_target": {"obj_id": 44, "raw": {"input_index": 0, "algorithm_object_index": 0}},
            "target_candidates": [{"obj_id": 44}],
            "frame_evidence": [{"frame_id": 100}],
            "breakpoint_pack": {
                "breakpoints": [{
                    "id": "bp-1",
                    "function": "CurrentFunction",
                    "location": {"file": "src/current.c", "line": 42, "confidence": "source"},
                    "condition": "frame_counter == 100 && sObj->objID == 44",
                    "watch": ["frame_counter", "i", "sObj->objID", "objInfo->trcOutData[i].flag"],
                    "scope_status": "source-line-resolved",
                }],
                "gdb_commands": ["break src/current.c:42 if frame_counter == 100"],
                "vscode_handoff": {"mode": "manual-user-debug"},
            },
        }],
    }


def _preflight() -> dict:
    return {
        "workspace": {"outer": {"head": "outer-1"}, "algo_source": {"head": "algo-1"}},
        "build": {"binary_candidates": ["/opt/arbe/devel/lib/engine"], "binary_fingerprint": "elf-1", "macros": {"HILMODEL": "2"}},
        "gdb": {"available": True, "path": "/usr/bin/gdb"},
        "runtime": {"processes": [{"pid": 7, "radar_id": 2}]},
    }


def test_runtime_debug_plan_is_source_and_event_bound():
    result = build_runtime_debug_plan(
        _bundle(),
        preflight=_preflight(),
        permissions={"approved": True},
    )
    assert result["schema_version"] == "runtime-debug-plan.v1"
    assert result["status"] == "ready"
    assert result["execution_status"] == "ready"
    assert result["event"]["target_frame"] == 100
    assert result["target"]["obj_id"] == 44
    assert "objInfo->trcOutData[i].flag" in [item["token"] for item in result["capture_fields"]]
    assert result["gdb_commands"] == ["break src/current.c:42 if frame_counter == 100"]
    assert result["vscode_handoff"]["mode"] == "manual-user-debug"
    assert result["readiness"]["blocking_gates"] == []


def test_runtime_debug_plan_adds_source_condition_probe_for_computed_locals():
    result = build_runtime_debug_plan(
        _bundle(),
        preflight=_preflight(),
        event_code_path={
            "schema_version": "event-code-path.v1",
            "resolution": {
                "function": {"name": "CurrentFunction", "file_path": "src/current.c", "start_line": 40, "end_line": 100},
                "conditions": [
                    {"function": "CurrentFunction", "file_path": "src/current.c", "line": 70, "expression": "if (fTTMX <= threshold && fTTMY >= 0.0f)"},
                    {"function": "CurrentFunction", "file_path": "src/current.c", "line": 71, "expression": "&& (flag > 0)"},
                ],
            },
        },
        permissions={"approved": True},
    )
    probes = [item for item in result["breakpoints"] if item.get("phase") == "source_condition"]
    assert len(probes) == 1
    assert probes[0]["location"]["line"] == 70
    assert probes[0]["condition"] == "frame_counter == 100 && sObj->objID == 44"
    assert probes[0]["watch"] == ["fTTMX", "threshold", "fTTMY"]
    assert "source_condition_breakpoints_added:1" in result["diagnostics"]


def test_runtime_debug_plan_uses_dynamic_condition_chain_functions():
    result = build_runtime_debug_plan(
        _bundle(),
        preflight=_preflight(),
        event_code_path={
            "schema_version": "event-code-path.v1",
            "resolution": {
                "function": {"name": "CurrentFunction", "file_path": "src/current.c", "start_line": 40, "end_line": 100},
                "condition_chain": [
                    {
                        "function": "StateGate", "chain_function": "StateGate", "chain_relation": "caller_precondition_helper",
                        "condition_kind": "if", "file_path": "src/state.c", "line": 12, "expression": "system_state == 2",
                    },
                    {
                        "function": "CurrentFunction", "chain_function": "CurrentFunction", "chain_relation": "event_root",
                        "condition_kind": "if", "file_path": "src/current.c", "line": 70, "expression": "if (fTTMX <= threshold)",
                    },
                ],
            },
        },
        permissions={"approved": True},
    )
    probes = [item for item in result["breakpoints"] if item.get("phase") == "source_condition"]
    assert {item["function"] for item in probes} == {"StateGate", "CurrentFunction"}
    assert {item["chain_relation"] for item in probes} == {"caller_precondition_helper", "event_root"}
    assert any(item.get("source_expression") == "if (fTTMX <= threshold)" for item in probes)


def test_runtime_debug_plan_blocks_execution_when_binary_is_unknown():
    result = build_runtime_debug_plan(_bundle(), permissions={"approved": True})
    assert result["status"] == "blocked"
    assert result["execution_status"] == "blocked"
    assert "binary" in result["readiness"]["blocking_gates"]
    assert "gdb" in result["readiness"]["warning_gates"]


def test_runtime_debug_plan_requires_approval_but_can_be_ready_to_execute():
    result = build_runtime_debug_plan(_bundle(), preflight=_preflight())
    assert result["status"] == "partial"  # approval is a warning, not a missing plan fact
    assert result["execution_status"] == "approval_required"
    assert "approval" in result["readiness"]["warning_gates"]


def test_runtime_debug_plan_fails_closed_for_unknown_event():
    result = build_runtime_debug_plan(_bundle(), event_id="missing")
    assert result["status"] == "blocked"
    assert result["breakpoints"] == []
    assert "event_not_found:missing" in result["diagnostics"]


def test_runtime_debug_plan_blocks_bundle_preflight_source_conflict():
    preflight = _preflight()
    preflight["workspace"]["algo_source"]["head"] = "different-algo"
    result = build_runtime_debug_plan(_bundle(), preflight=preflight, permissions={"approved": True})
    assert result["status"] == "blocked"
    assert "source_preflight_compatibility" in result["readiness"]["blocking_gates"]


def test_runtime_debug_plan_blocks_explicit_source_context_conflict():
    result = build_runtime_debug_plan(
        _bundle(),
        source_context={"source_context_id": "different-context"},
        preflight=_preflight(),
        permissions={"approved": True},
    )
    assert result["status"] == "blocked"
    assert "source_explicit_compatibility" in result["readiness"]["blocking_gates"]


def test_runtime_debug_plan_blocks_unsafe_commands_before_gdb_service():
    bundle = _bundle()
    bundle["alarm_events"][0]["breakpoint_pack"]["gdb_commands"] = ["shell echo unsafe"]
    result = build_runtime_debug_plan(bundle, preflight=_preflight(), permissions={"approved": True})
    assert result["status"] == "blocked"
    assert "gdb_commands" in result["readiness"]["blocking_gates"]
    assert any(item.startswith("gdb_command:") for item in result["diagnostics"])


def test_runtime_debug_plan_blocks_code_schema_fingerprint_conflict():
    bundle = _bundle()
    bundle["runtime_schema"]["source_context"] = {"source_snapshot_hash": "different-source"}
    result = build_runtime_debug_plan(bundle, preflight=_preflight(), permissions={"approved": True})
    assert result["status"] == "blocked"
    assert "source_artifact_compatibility" in result["readiness"]["blocking_gates"]


def test_runtime_debug_plan_is_pi_registered():
    assert MODULE_REGISTRY["runtime-debug-plan"] is RuntimeDebugPlanModule
    entry = {item["name"]: item for item in capability_catalog()}["runtime-debug-plan"]
    assert entry["expose_to_pi"] is True
    assert "atomic" in entry["tags"]


def test_runtime_debug_plan_commands_can_be_typed_ref_to_gdb_service():
    from ai.agent_loop import AgentLoop
    from ai.capability.module_bridge import build_module_tool_registry

    registry = build_module_tool_registry(names=["runtime-debug-plan", "gdb-service"])
    state = AgentLoop(registry).run([
        {
            "tool": "runtime-debug-plan",
            "params": {
                "bundle": _bundle(),
                "preflight": _preflight(),
                "permissions": {"approved": False},
            },
        },
        {
            "tool": "gdb-service",
            "params": {
                "target": {"pid": 7, "program": "/opt/arbe/devel/lib/engine"},
                "commands": {"$ref": "steps[0].result.data.gdb_commands"},
            },
        },
    ])
    assert state.status == "completed"
    assert state.steps[1].resolved_params["commands"]
    assert state.steps[1].result["data"]["status"] == "planned"
