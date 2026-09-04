# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path

from ai.agent_loop import AgentLoop, AgentToolCall, resolve_agent_references
from ai.tools.base import BaseTool


class _ReqTool(BaseTool):
    name = "req_lookup"
    description = "Load requirement facts"
    parameters_schema = {
        "type": "object",
        "properties": {
            "req_id": {"type": "string"},
        },
        "required": ["req_id"],
        "additionalProperties": False,
    }

    def execute(self, params: dict[str, object]) -> dict[str, object]:
        req_id = str(params["req_id"])
        return self.ok(
            data={"req_id": req_id, "summary": f"requirement:{req_id}"},
            message="requirement loaded",
            artifacts=[Path("artifacts") / f"{req_id}.json"],
        )


class _CodeTool(BaseTool):
    name = "code_lookup"
    description = "Load code facts"
    parameters_schema = {
        "type": "object",
        "properties": {
            "symbol": {"type": "string"},
        },
        "required": ["symbol"],
        "additionalProperties": False,
    }

    def execute(self, params: dict[str, object]) -> dict[str, object]:
        return self.ok(
            data={"symbol": params["symbol"], "location": "adasFunc.c:123"},
            message="code loaded",
        )


class _DataTool(BaseTool):
    name = "data_lookup"
    description = "Load data facts"
    parameters_schema = {
        "type": "object",
        "properties": {
            "signal": {"type": "string"},
        },
        "required": ["signal"],
        "additionalProperties": False,
    }

    def execute(self, params: dict[str, object]) -> dict[str, object]:
        return self.ok(
            data={"signal": params["signal"], "samples": [0, 1, 1]},
            message="data loaded",
        )


class _BoomTool(BaseTool):
    name = "boom"
    description = "Always raises"

    def execute(self, params: dict[str, object]) -> dict[str, object]:
        raise RuntimeError(f"boom:{params.get('token', 'missing')}")


class _UnusedTool(BaseTool):
    name = "unused"
    description = "Must never run"

    def execute(self, params: dict[str, object]) -> dict[str, object]:
        raise AssertionError("ask_human should stop before this tool runs")


class _PlanProducerTool(BaseTool):
    name = "plan_producer"
    description = "produce commands"

    def execute(self, params: dict[str, object]) -> dict[str, object]:
        return self.ok(data={"commands": ["p frame_counter", str(params["label"])]})


class _PlanConsumerTool(BaseTool):
    name = "plan_consumer"
    description = "consume commands"
    parameters_schema = {
        "type": "object",
        "properties": {"commands": {"type": "array"}},
        "required": ["commands"],
        "additionalProperties": False,
    }

    def execute(self, params: dict[str, object]) -> dict[str, object]:
        return self.ok(data={"received": params["commands"]})


def test_agent_loop_runs_multi_step_plan_successfully():
    loop = AgentLoop({
        "req_lookup": _ReqTool,
        "code_lookup": _CodeTool(),
        "data_lookup": _DataTool,
    })

    state = loop.run([
        AgentToolCall(tool_name="req_lookup", params={"req_id": "REQ-1"}),
        {"tool_name": "code_lookup", "params": {"symbol": "Bsd_CheckWarning"}},
        {"tool": "data_lookup", "params": {"signal": "BSD_warning"}},
    ])

    assert state.status == "completed"
    assert state.next_step_index == 3
    assert [step.tool_name for step in state.steps] == [
        "req_lookup",
        "code_lookup",
        "data_lookup",
    ]
    assert [step.step_status for step in state.steps] == ["ok", "ok", "ok"]
    assert state.last_result["data"] == {
        "signal": "BSD_warning",
        "samples": [0, 1, 1],
    }
    assert state.artifacts == [str(Path("artifacts") / "REQ-1.json")]


def test_agent_loop_reports_unknown_tool_as_structured_error():
    loop = AgentLoop({"req_lookup": _ReqTool})

    state = loop.run([
        {"tool_name": "missing_tool", "params": {"req_id": "REQ-1"}},
    ])

    assert state.status == "error"
    assert len(state.steps) == 1
    assert state.steps[0].tool_name == "missing_tool"
    assert state.steps[0].step_status == "error"
    assert state.steps[0].result["message"] == "Unknown tool: missing_tool"
    assert state.steps[0].result["data"]["available_tools"] == ["req_lookup"]


def test_agent_loop_preserves_safe_execute_error_results():
    loop = AgentLoop({"boom": _BoomTool})

    state = loop.run([
        {"tool_name": "boom", "params": {"token": "x"}},
    ])

    assert state.status == "error"
    assert state.steps[0].result["status"] == "error"
    assert state.steps[0].result["message"] == "RuntimeError: boom:x"


def test_agent_loop_stops_with_input_required_for_ask_human():
    loop = AgentLoop({
        "req_lookup": _ReqTool,
        "unused": _UnusedTool,
    })

    state = loop.run([
        {"tool_name": "req_lookup", "params": {"req_id": "REQ-1"}},
        {"tool_name": "ask_human", "params": {"question": "Need expected behavior?"}},
        {"tool_name": "unused", "params": {}},
    ])

    assert state.status == "input_required"
    assert state.next_step_index == 2
    assert [step.tool_name for step in state.steps] == ["req_lookup", "ask_human"]
    assert state.steps[-1].step_status == "input_required"
    assert state.pending_input == {
        "tool_name": "ask_human",
        "question": "Need expected behavior?",
        "params": {"question": "Need expected behavior?"},
    }


def test_agent_state_is_json_serializable():
    loop = AgentLoop({"req_lookup": _ReqTool})
    state = loop.run([
        {"tool_name": "req_lookup", "params": {"req_id": "REQ-JSON"}},
    ])

    payload = state.to_dict()
    encoded = json.dumps(payload)
    decoded = json.loads(encoded)

    assert decoded["status"] == "completed"
    assert decoded["plan"] == [{"tool_name": "req_lookup", "params": {"req_id": "REQ-JSON"}}]
    assert decoded["steps"][0]["result"]["artifacts"] == [
        str(Path("artifacts") / "REQ-JSON.json"),
    ]


def test_agent_loop_resolves_typed_artifact_reference_between_atomic_tools():
    loop = AgentLoop({
        "plan_producer": _PlanProducerTool,
        "plan_consumer": _PlanConsumerTool,
    })
    state = loop.run([
        {"tool": "plan_producer", "params": {"label": "generated"}},
        {
            "tool": "plan_consumer",
            "params": {"commands": {"$ref": "steps[0].result.data.commands"}},
        },
    ])
    assert state.status == "completed"
    assert state.steps[1].params["commands"] == {
        "$ref": "steps[0].result.data.commands"
    }
    assert state.steps[1].resolved_params["commands"] == [
        "p frame_counter",
        "generated",
    ]
    assert state.last_result["data"]["received"] == ["p frame_counter", "generated"]


def test_agent_loop_fails_closed_for_missing_artifact_reference():
    state = AgentLoop({"plan_consumer": _PlanConsumerTool}).run([
        {
            "tool": "plan_consumer",
            "params": {"commands": {"$ref": "steps[9].result.data.commands"}},
        }
    ])
    assert state.status == "error"
    assert "step index out of range" in state.steps[0].result["message"]


def test_resolve_agent_references_rejects_unstructured_interpolation():
    state = AgentLoop({}).run([])
    try:
        resolve_agent_references({"x": {"$ref": "steps[0].result"}}, state)
    except ValueError as exc:
        assert "step index out of range" in str(exc)
    else:
        raise AssertionError("missing reference should fail closed")
