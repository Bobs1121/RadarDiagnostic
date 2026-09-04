# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from tools.run_agent_loop_smoke import run_agent_loop_smoke

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _steps_by_name(state: dict) -> dict[str, dict]:
    return {step["tool_name"]: step for step in state["steps"]}


def test_agent_loop_smoke_helper_composes_real_tools():
    result = run_agent_loop_smoke()

    assert result.ok is True
    state = result.data["state"]
    assert state["status"] == "completed"

    step_names = [step["tool_name"] for step in state["steps"]]
    assert step_names == [
        "trace-requirement",
        "find-code-definition",
        "query_can_data",
        "plot_signal",
    ]

    steps = _steps_by_name(state)
    trace = steps["trace-requirement"]["result"]["data"]["trace"]
    assert trace["coverage"] == "full" or bool(trace["linked_functions"])

    definition = steps["find-code-definition"]["result"]["data"]
    assert definition["found"] is True
    assert definition["definition"]["file_path"] == r"coem\adas\alarm.c"

    query = steps["query_can_data"]["result"]["data"]
    assert query["probe_source"] == "data-probe"
    assert query["result"]["row_count"] >= 1
    assert query["result"]["global"]["count"] >= 1

    plot = steps["plot_signal"]["result"]["data"]
    assert plot["preview_status"] == "available"
    assert plot["preview"]["point_count"] >= 1


def test_agent_loop_smoke_script_prints_json_and_exits_zero():
    completed = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "tools" / "run_agent_loop_smoke.py")],
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
        check=False,
    )

    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    assert payload["ok"] is True
    assert payload["data"]["state"]["status"] == "completed"
