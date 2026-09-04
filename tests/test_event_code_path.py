# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path

from ai.modules import MODULE_REGISTRY
from ai.modules.event_code_path import EventCodePathModule
from engines.event_code_path import build_event_code_path


def _index() -> dict:
    return {
        "schema_version": "code-index.v1",
        "source_root": "/src",
        "snapshot_hash": "source-1",
        "parser": "fixture",
        "files": [],
        "functions": [
            {
                "id": "FUNCTION:AlarmHandler",
                "name": "AlarmHandler",
                "file_path": "alarm.c",
                "start_line": 20,
                "end_line": 40,
                "return_type": "void",
                "params": "int frame_counter",
                "signature": "void AlarmHandler(int frame_counter)",
                "source_hash": "file-1",
            },
            {
                "id": "FUNCTION:SelectTarget",
                "name": "SelectTarget",
                "file_path": "target.c",
                "start_line": 5,
                "end_line": 15,
                "return_type": "int",
                "params": "int id",
                "signature": "int SelectTarget(int id)",
                "source_hash": "file-2",
            },
        ],
        "calls": {"AlarmHandler": ["SelectTarget"]},
        "variables_read": [
            {"function": "AlarmHandler", "var_name": "frame_counter", "line": 21},
            {"function": "AlarmHandler", "var_name": "sObj->objID", "line": 22},
        ],
        "variables_written": [
            {"function": "AlarmHandler", "var_name": "alarm_state", "line": 30},
        ],
        "signals": [
            {"function": "AlarmHandler", "signal_name": "WarningTx", "access": "write", "line": 32},
            {"function": "AlarmHandler", "signal_name": "VehicleSpeed", "access": "read", "line": 21},
        ],
        "conditions": [
            {
                "function": "AlarmHandler",
                "expression": "frame_counter >= 100 && sObj->objID == 44",
                "file_path": "alarm.c",
                "line": 24,
                "source_hash": "file-1",
            }
        ],
        "parameters": [
            {"name": "WarningThreshold", "value": 2.0, "file_path": "param.h", "line": 3}
        ],
        "states": [],
        "semantics": [],
        "edges": [],
        "summary": {},
    }


def test_event_code_path_is_generic_and_builds_copyable_root_plan():
    payload = build_event_code_path(
        event={
            "event_id": "evt-1",
            "function": "AlarmHandler",
            "frame_scope": {"variable": "frame_counter", "start": 100, "end": 105},
            "object_scope": {"expression": "sObj->objID", "equals": 44},
            "watch_variables": ["sObj->objID"],
        },
        code_index=_index(),
    )
    assert payload["status"] == "ready"
    assert payload["source_context"]["snapshot_hash"] == "source-1"
    assert payload["resolution"]["function"]["name"] == "AlarmHandler"
    assert payload["layers"]["output"]["nodes"][0]["name"] == "WarningTx"
    assert payload["layers"]["target"]["nodes"][0]["name"] == "sObj->objID"
    assert payload["breakpoint_groups"][0]["gdb_plan"]["gdb_commands"][-1].startswith("p ")
    assert "frame_counter" in payload["required_runtime_tokens"]


def test_event_code_path_exposes_dynamic_caller_and_helper_condition_chain():
    index = _index()
    index["functions"].extend([
        {
            "id": "FUNCTION:Caller", "name": "Caller", "file_path": "caller.c",
            "start_line": 1, "end_line": 20, "signature": "void Caller(void)",
        },
        {
            "id": "FUNCTION:PrepareState", "name": "PrepareState", "file_path": "state.c",
            "start_line": 2, "end_line": 12, "signature": "void PrepareState(void)",
        },
    ])
    index["calls"] = {
        "Caller": ["PrepareState", "AlarmHandler"],
        "AlarmHandler": ["SelectTarget"],
    }
    index["conditions"].extend([
        {"function": "Caller", "expression": "system_state == 2", "file_path": "caller.c", "line": 8},
        {"function": "PrepareState", "expression": "vehicle_speed > 0", "file_path": "state.c", "line": 5},
        {"function": "SelectTarget", "expression": "target.dynFlg >= 1", "file_path": "target.c", "line": 7},
    ])
    payload = build_event_code_path(event={"function": "AlarmHandler"}, code_index=index)
    chain = payload["resolution"]["condition_chain"]
    assert [item["chain_function"] for item in chain] == ["PrepareState", "Caller", "AlarmHandler", "SelectTarget"]
    assert chain[0]["chain_relation"] == "caller_precondition_helper"
    assert chain[1]["chain_relation"] == "caller_precondition"
    assert chain[2]["chain_relation"] == "event_root"
    assert chain[3]["chain_relation"] == "event_callee"


def test_event_code_path_projects_source_tx_mapping_for_entry_function():
    index = _index()
    index["functions"].append({
        "id": "FUNCTION:FCTA_R",
        "name": "FCTA_R",
        "file_path": "adas.c",
        "start_line": 50,
        "end_line": 80,
        "signature": "void FCTA_R(void)",
    })
    index["output_mapping"] = {
        "source_hash": "tx-source-1",
        "signal_to_expr": {
            "WarnRight": ["AdasStM.Frontright_FCTA"],
            "OtherSignal": ["other.state"],
        },
        "mappings": [
            {
                "can_signal": "WarnRight",
                "expression": "AdasStM.Frontright_FCTA",
                "source_file": "RteComMapping_Tx.c",
                "line": 42,
                "function": "TxRunnable",
            },
            {
                "can_signal": "OtherSignal",
                "expression": "other.state",
                "source_file": "RteComMapping_Tx.c",
                "line": 43,
                "function": "TxRunnable",
            },
        ],
    }
    payload = build_event_code_path(event={"function": "FCTA_R"}, code_index=index)
    assert [row["signal_name"] for row in payload["resolution"]["output_signals"]] == ["WarnRight"]
    assert payload["layers"]["output"]["nodes"][0]["source_ref"]["file_path"] == "RteComMapping_Tx.c"


def test_event_code_path_fails_closed_on_ambiguous_source_resolution():
    index = _index()
    index["signals"].append(
        {"function": "SelectTarget", "signal_name": "WarningTx", "access": "write", "line": 10}
    )
    payload = build_event_code_path(
        event={"output_signal": "WarningTx"},
        code_index=index,
    )
    assert payload["status"] == "blocked"
    assert any(item.startswith("ambiguous_function:") for item in payload["diagnostics"])


def test_event_code_path_module_reads_context_and_writes_optional_artifact(tmp_path: Path):
    index_path = tmp_path / "code-index.json"
    index_path.write_text(json.dumps(_index()), encoding="utf-8")
    output = tmp_path / "event-code-path.json"
    result = EventCodePathModule().safe_run(
        event={"function": "AlarmHandler"},
        code_index_path=str(index_path),
        output=str(output),
    )
    assert result.ok
    assert output.exists()
    assert MODULE_REGISTRY["event-code-path"] is EventCodePathModule


def test_event_code_path_preserves_enclosing_context_identity(tmp_path: Path):
    index_path = tmp_path / "code-index.json"
    context_path = tmp_path / "code-context.json"
    index = _index()
    index_path.write_text(json.dumps(index), encoding="utf-8")
    context_path.write_text(
        json.dumps({
            "schema_version": "code-context.v1",
            "source_context": {
                "source_context_id": "ctx-1",
                "source_snapshot_hash": "remote-source-1",
                "project_id": "demo",
            },
            "artifacts": {"code_index": str(index_path)},
        }),
        encoding="utf-8",
    )
    payload = build_event_code_path(
        event={"function": "AlarmHandler"},
        code_index={
            **index,
            "source_snapshot_hash": "remote-source-1",
            "source_context_id": "ctx-1",
            "project_id": "demo",
        },
    )
    assert payload["source_context"]["source_snapshot_hash"] == "remote-source-1"
    assert payload["source_context"]["source_context_id"] == "ctx-1"

    from engines.event_code_path import load_code_index

    loaded = load_code_index(context_path=str(context_path))
    assert loaded["source_snapshot_hash"] == "remote-source-1"
    assert loaded["source_context_id"] == "ctx-1"


def test_event_code_path_adapts_sibling_harness_index_and_prefers_real_entry():
    index = _index()
    index.pop("schema_version")
    index["functions"].append({
        "name": "FrontCrossTrafficAlertAndBrake",
        "file_path": "adasFunc.c",
        "start_line": 100,
        "end_line": 120,
    })
    payload = build_event_code_path(
        event={
            "function": "FCTA_R",
            "breakpoint_pack": {
                "breakpoints": [
                    {"id": "input-entry", "function": "AlarmHandler"},
                    {"id": "function-entry", "function": "FrontCrossTrafficAlertAndBrake"},
                ]
            },
        },
        code_index=index,
    )
    assert payload["status"] == "ready"
    assert payload["source_context"]["adapter"] == "cr60-debug-harness-code-index-compat.v1"
    assert payload["resolution"]["function"]["name"] == "FrontCrossTrafficAlertAndBrake"
