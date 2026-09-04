# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse

from ai.modules.agent_loop import AgentLoopModule
from ai.tools.base import BaseTool


class _EchoTool(BaseTool):
    name = "echo_tool"
    description = "Echo params for agent-loop module tests"
    parameters_schema = {
        "type": "object",
        "properties": {
            "value": {"type": "string"},
        },
        "required": ["value"],
        "additionalProperties": False,
    }

    def execute(self, params: dict[str, object]) -> dict[str, object]:
        return self.ok(
            message="echo_tool:ok",
            data={"echoed": params["value"]},
        )


def test_agent_loop_module_runs_with_injected_registry():
    module = AgentLoopModule(tool_registry={"echo_tool": _EchoTool})

    result = module.safe_run(
        objective="echo a value",
        tool_calls=[{"tool": "echo_tool", "params": {"value": "hello"}}],
    )

    assert result.ok is True
    assert result.data["objective"] == "echo a value"
    assert result.data["state"]["status"] == "completed"
    assert result.data["state"]["steps"][0]["result"]["data"] == {"echoed": "hello"}


def test_agent_loop_module_parses_json_string_tool_calls():
    module = AgentLoopModule(tool_registry={"echo_tool": _EchoTool})

    result = module.safe_run(
        tool_calls=['{"tool":"echo_tool","params":{"value":"json"}}'],
    )

    assert result.ok is True
    assert result.data["state"]["plan"] == [
        {"tool_name": "echo_tool", "params": {"value": "json"}}
    ]


def test_agent_loop_module_reports_invalid_json_failure():
    module = AgentLoopModule(tool_registry={"echo_tool": _EchoTool})

    result = module.safe_run(
        objective="broken json",
        tool_calls=['{"tool":"echo_tool","params":{"value":"oops"}'],
    )

    assert result.ok is False
    assert "invalid tool_call JSON at index 0" in result.message
    assert result.data["objective"] == "broken json"
    assert result.data["state"]["status"] == "error"
    assert result.data["state"]["steps"][0]["tool_name"] == "<invalid-tool-call>"


def test_agent_loop_module_treats_input_required_as_success():
    module = AgentLoopModule(tool_registry={"echo_tool": _EchoTool})

    result = module.safe_run(
        objective="ask a follow-up",
        tool_calls=[
            {"tool": "ask_human", "params": {"question": "Need expected behavior?"}},
        ],
    )

    assert result.ok is True
    assert result.message == "agent-loop:input_required"
    assert result.data["state"]["status"] == "input_required"
    assert result.data["state"]["pending_input"]["question"] == "Need expected behavior?"


def test_agent_loop_module_cli_parser_wires_repeated_tool_call_args():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="module")
    AgentLoopModule.register_cli(subparsers)

    args = parser.parse_args([
        "agent-loop",
        "--objective", "inspect warning output",
        "--tool-call", '{"tool":"echo_tool","params":{"value":"one"}}',
        "--tool-call", '{"tool":"echo_tool","params":{"value":"two"}}',
    ])

    assert args.module == "agent-loop"
    assert args.objective == "inspect warning output"
    assert args.tool_calls == [
        '{"tool":"echo_tool","params":{"value":"one"}}',
        '{"tool":"echo_tool","params":{"value":"two"}}',
    ]
