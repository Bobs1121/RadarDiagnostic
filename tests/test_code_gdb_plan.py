# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path

from ai.capability.registry import capability_catalog
from ai.modules import MODULE_REGISTRY
from ai.modules.base import ModuleResult
from ai.modules.code_gdb_plan import CodeGdbPlanModule
from engines.code_gdb_plan import build_code_gdb_plan


def _index() -> dict:
    return {
        "source_root": "/workspace/arbe",
        "snapshot_hash": "source-hash",
        "parser": "regex-low",
        "functions": [
            {
                "name": "RuntimeGate",
                "file_path": "src/algo/gate.c",
                "start_line": 42,
                "end_line": 80,
                "signature": "void RuntimeGate(objOutStruct* sObj)",
                "confidence": "regex-low",
            }
        ],
        "calls": {"RuntimeGate": ["ComputeGate", "EmitWarning"]},
        "variables_read": [
            {"function": "RuntimeGate", "var_name": "sObj", "line": 50},
            {"function": "RuntimeGate", "var_name": "frame_counter", "line": 51},
        ],
        "variables_written": [
            {"function": "RuntimeGate", "var_name": "warning_flag", "line": 70}
        ],
        "conditions": [
            {"function": "RuntimeGate", "file_path": "src/algo/gate.c", "line": 51, "expression": "if (frame_counter > 0)"}
        ],
    }


def test_code_analysis_generates_only_caller_bound_generic_commands():
    payload = build_code_gdb_plan(
        code_index=_index(),
        function_name="RuntimeGate",
        condition="warning_flag != 0",
        frame_scope={"variable": "frame_counter", "start": 47872, "end": 47877},
        object_scope={"expression": "sObj->objID", "equals": 44},
        watch_variables=["sObj->objID", "warning_flag"],
    )
    assert payload["status"] == "ready"
    assert payload["breakpoints"][0]["file"] == "src/algo/gate.c"
    assert payload["breakpoints"][0]["line"] == 42
    condition = payload["breakpoints"][0]["condition"]
    assert "frame_counter >= 47872" in condition
    assert "sObj->objID == 44" in condition
    assert "FCTA" not in json.dumps(payload)
    assert any(item.startswith("break src/algo/gate.c:42") for item in payload["gdb_commands"])
    assert "p sObj->objID" in payload["gdb_commands"]
    assert payload["breakpoints"][0]["scope_status"] == "requires_source_line_validation"
    assert any("scope/initialization" in item for item in payload["diagnostics"])


def test_code_analysis_fails_closed_for_unknown_function():
    payload = build_code_gdb_plan(code_index=_index(), function_name="NotInIndex")
    assert payload["status"] == "blocked"
    assert payload["gdb_commands"] == []
    assert "function_not_found:NotInIndex" in payload["diagnostics"]


def test_code_analysis_records_caller_selected_line_for_local_scope():
    payload = build_code_gdb_plan(
        code_index=_index(),
        function_name="RuntimeGate",
        line=70,
        watch_variables=["warning_flag"],
    )
    assert payload["breakpoints"][0]["location_source"] == "caller_line"
    assert payload["breakpoints"][0]["scope_status"] == "caller_selected_line"


def test_code_gdb_module_reads_artifact_and_registers():
    path = Path("tests") / "_temporary_code_index_for_test.json"
    try:
        path.write_text(json.dumps(_index()), encoding="utf-8")
        result = CodeGdbPlanModule().safe_run(
            code_index_path=str(path),
            function_name="RuntimeGate",
            watch_variables=["sObj->objID"],
        )
    finally:
        if path.exists():
            path.unlink()
    assert isinstance(result, ModuleResult)
    assert result.ok is True
    assert result.data["schema_version"] == "code-gdb-plan.v1"
    assert MODULE_REGISTRY["code-gdb-plan"] is CodeGdbPlanModule
    catalog = {item["name"]: item for item in capability_catalog()}
    assert "atomic" in catalog["code-gdb-plan"]["tags"]
