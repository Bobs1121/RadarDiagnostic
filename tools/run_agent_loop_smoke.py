# -*- coding: utf-8 -*-
"""Deterministic real-tool smoke harness for the PR5 Agent loop."""
from __future__ import annotations

import argparse
import io
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
else:
    sys.stdout = io.TextIOWrapper(
        sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True
    )
    sys.stderr = io.TextIOWrapper(
        sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True
    )

from ai.agent_tool_registry import (
    build_agent_tool_registry,
    resolve_agent_tool_context,
)
from ai.modules.agent_loop import AgentLoopModule
from ai.modules.base import ModuleResult
from core.materials import RequirementSpec, StructuredRequirementSet
from parsers.frame_store import FrameStore

SMOKE_REQUIREMENT_ID = "REQ-FCTA-SMOKE-001"
SMOKE_FUNCTION_NAME = "FctaAlarmProcess"
SMOKE_SIGNAL_NAME = "FCTA_WARN"
SMOKE_MESSAGE_NAME = "ADASWarnMsg"
SMOKE_CAN_SIGNAL = "WarnCAN"


@dataclass
class _SmokeFunctionDef:
    id: str
    type: str
    name: str
    file_path: str
    start_line: int
    end_line: int


class _SmokeCodeGraph:
    """Tiny deterministic CodeGraph-like backend for real tool classes."""

    def get_function_by_name(self, name: str) -> _SmokeFunctionDef | None:
        if name != SMOKE_FUNCTION_NAME:
            return None
        return _SmokeFunctionDef(
            id=f"FUNCTION:{name}",
            type="FUNCTION",
            name=name,
            file_path=r"coem\adas\alarm.c",
            start_line=42,
            end_line=96,
        )

    def get_functions_using_signal(self, signal_name: str) -> list[dict[str, Any]]:
        if signal_name != SMOKE_SIGNAL_NAME:
            return []
        return [{
            "func_name": SMOKE_FUNCTION_NAME,
            "file_id": r"FILE:coem\adas\alarm.c",
        }]

    def get_callers(self, name: str) -> list[dict[str, Any]]:
        return [{"caller_name": "MainLoop", "target": name, "line": 21}]

    def get_callees(self, name: str) -> list[dict[str, Any]]:
        return [{"callee_name": "FctaWarnOutput", "source": name, "line": 68}]

    def get_call_chain(self, name: str, max_depth: int = 5) -> list[dict[str, Any]]:
        return [{
            "func_name": "MainLoop",
            "depth": 1,
            "path": f"MainLoop -> {name}",
            "max_depth": max_depth,
        }]

    def get_signals_used_by(self, name: str) -> list[dict[str, Any]]:
        return [{"signal_name": SMOKE_SIGNAL_NAME, "type": "READS_SIGNAL", "line": 55}]

    def get_variables_read_by(self, name: str) -> list[dict[str, Any]]:
        return [{"var_name": "ego_speed", "type": "READS_VAR", "line": 58}]

    def get_variables_written_by(self, name: str) -> list[dict[str, Any]]:
        return [{"var_name": "warn_state", "type": "WRITES_VAR", "line": 74}]


def build_smoke_store() -> FrameStore:
    store = FrameStore(":memory:")
    store.bulk_insert_radar_objects([
        {
            "timestamp_ns": 1_000_000_000,
            "radar_id": 1,
            "frame_id": 10,
            "obj_id": 101,
            "obj_class": 1,
            "life_cycle": 5,
            "dist_x": 11.5,
            "dist_y": -1.2,
            "vel_x": -2.0,
            "vel_y": 0.0,
            "ttc": 2.4,
            "fcta_flag": 1,
            "source": "wfa",
        },
        {
            "timestamp_ns": 1_100_000_000,
            "radar_id": 1,
            "frame_id": 11,
            "obj_id": 101,
            "obj_class": 1,
            "life_cycle": 6,
            "dist_x": 9.8,
            "dist_y": -1.0,
            "vel_x": -2.2,
            "vel_y": 0.0,
            "ttc": 2.1,
            "fcta_flag": 1,
            "source": "wfa",
        },
        {
            "timestamp_ns": 1_200_000_000,
            "radar_id": 1,
            "frame_id": 12,
            "obj_id": 101,
            "obj_class": 1,
            "life_cycle": 7,
            "dist_x": 8.2,
            "dist_y": -0.8,
            "vel_x": -2.5,
            "vel_y": 0.0,
            "ttc": 1.7,
            "fcta_flag": 0,
            "source": "wfa",
        },
    ])
    store.bulk_insert_can_from_dict([
        {
            "timestamp": 1.0,
            "datetime_str": "1970-01-01T00:00:01",
            "channel": 1,
            "can_id": 0x321,
            "can_id_hex": "0x321",
            "dlc": 8,
            "message_name": SMOKE_MESSAGE_NAME,
            "raw_hex": "0000000000000000",
            "signals": {SMOKE_CAN_SIGNAL: 0, "AliveCounter": 1},
        },
        {
            "timestamp": 1.1,
            "datetime_str": "1970-01-01T00:00:01.100000",
            "channel": 1,
            "can_id": 0x321,
            "can_id_hex": "0x321",
            "dlc": 8,
            "message_name": SMOKE_MESSAGE_NAME,
            "raw_hex": "0100000000000000",
            "signals": {SMOKE_CAN_SIGNAL: 1, "AliveCounter": 2},
        },
        {
            "timestamp": 1.2,
            "datetime_str": "1970-01-01T00:00:01.200000",
            "channel": 1,
            "can_id": 0x321,
            "can_id_hex": "0x321",
            "dlc": 8,
            "message_name": SMOKE_MESSAGE_NAME,
            "raw_hex": "0100000000000000",
            "signals": {SMOKE_CAN_SIGNAL: 1, "AliveCounter": 3},
        },
    ])
    return store


def build_smoke_requirement_set() -> StructuredRequirementSet:
    req_set = StructuredRequirementSet(variant_id="smoke/gen6")
    req_set.add(RequirementSpec(
        requirement_id=SMOKE_REQUIREMENT_ID,
        material_id="mat-smoke",
        variant_id="smoke/gen6",
        scope="function",
        statement="Raise FCTA warning output when FCTA_WARN is asserted.",
        linked_signals=[SMOKE_SIGNAL_NAME],
        linked_functions=[SMOKE_FUNCTION_NAME],
        priority="critical",
        evidence_policy="code+can+data",
    ))
    return req_set


def build_smoke_tool_registry(store: FrameStore) -> dict[str, Any]:
    context = resolve_agent_tool_context(
        project_root=PROJECT_ROOT,
        store=store,
        codegraph=_SmokeCodeGraph(),
        req_set=build_smoke_requirement_set(),
        signal_mapping={
            "can_to_internal": {
                SMOKE_SIGNAL_NAME: ["warn_state"],
                SMOKE_CAN_SIGNAL: ["warn_can_state"],
            },
        },
    )
    return build_agent_tool_registry(context)


def build_smoke_plan() -> list[dict[str, Any]]:
    return [
        {
            "tool": "trace-requirement",
            "params": {"req_id": SMOKE_REQUIREMENT_ID},
        },
        {
            "tool": "find-code-definition",
            "params": {"name": SMOKE_FUNCTION_NAME},
        },
        {
            "tool": "query_can_data",
            "params": {
                "field": "ttc",
                "table": "radar_objects",
                "filter": "fcta_flag > 0",
                "stats": ["count", "min", "max"],
            },
        },
        {
            "tool": "plot_signal",
            "params": {
                "message_name": SMOKE_MESSAGE_NAME,
                "signal_name": SMOKE_CAN_SIGNAL,
                "preview_limit": 3,
            },
        },
    ]


def run_agent_loop_smoke(*, objective: str = "offline req-code-data-plot smoke") -> ModuleResult:
    store = build_smoke_store()
    try:
        module = AgentLoopModule(tool_registry=build_smoke_tool_registry(store))
        return module.safe_run(objective=objective, tool_calls=build_smoke_plan())
    finally:
        store.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print the JSON payload instead of compact JSON.",
    )
    args = parser.parse_args(argv)

    result = run_agent_loop_smoke()
    payload = result.to_dict()
    if args.pretty:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(payload, ensure_ascii=False))

    state = payload.get("data", {}).get("state", {})
    state_status = state.get("status") if isinstance(state, dict) else None
    return 0 if result.ok and state_status == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
