# -*- coding: utf-8 -*-
from __future__ import annotations

from ai.modules import MODULE_REGISTRY
from ai.modules.base import ModuleResult
from ai.modules.code_analyze import CodeAnalyzeModule


def _source_index() -> dict:
    return {
        "source_root": "/snapshot/arbe",
        "snapshot_hash": "source-hash",
        "parser": "regex-low",
        "files": ["a.c"],
        "functions": [
            {"name": "Gate", "file_path": "a.c", "start_line": 10, "end_line": 30},
            {"name": "Compute", "file_path": "a.c", "start_line": 40, "end_line": 50},
            {"name": "Emit", "file_path": "a.c", "start_line": 60, "end_line": 70},
        ],
        "calls": {"Gate": ["Compute", "Emit"], "Compute": []},
        "variables_read": {"Gate": [{"var_name": "frame_counter", "line": 14}]},
        "variables_written": {"Gate": [{"var_name": "warning_flag", "line": 25}]},
        "conditions": [
            {
                "function": "Gate",
                "file_path": "a.c",
                "line": 20,
                "expression": "frame_counter > 0",
            }
        ],
        "parameters": [{"name": "FctaRoi", "value": "10.0", "category": "ROI"}],
    }


def test_code_analyze_prefers_current_source_index_and_preserves_identity():
    result = CodeAnalyzeModule().safe_run(
        kind="call_chain", name="Gate", code_index=_source_index(), max_depth=2
    )
    assert isinstance(result, ModuleResult)
    assert result.ok is True
    assert result.data["backend"] == "source_code_index"
    assert result.data["source_context"]["snapshot_hash"] == "source-hash"
    assert any(row["callee"] == "Compute" for row in result.data["data"])


def test_code_analyze_source_index_exposes_real_variables_and_parameters():
    module = CodeAnalyzeModule()
    variables = module.safe_run(kind="vars_read", name="Gate", code_index=_source_index())
    params = module.safe_run(kind="calib", name="ROI", code_index=_source_index())
    assert variables.data["data"][0]["var_name"] == "frame_counter"
    assert params.data["data"][0]["name"] == "FctaRoi"
    assert MODULE_REGISTRY["code-analyze"] is CodeAnalyzeModule


def test_code_analyze_source_index_returns_conditions_for_the_real_function():
    result = CodeAnalyzeModule().safe_run(
        kind="conditions", name="Gate", code_index=_source_index()
    )
    assert result.ok is True
    assert result.data["data"][0]["expression"] == "frame_counter > 0"
