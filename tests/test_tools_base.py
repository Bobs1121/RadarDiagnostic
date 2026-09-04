# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import ai.tools as tools_pkg
from ai.tools.base import BaseTool


@dataclass
class _Payload:
    name: str
    output: Path


class _EchoTool(BaseTool):
    name = "echo"
    description = "Echo a string"
    parameters_schema = {
        "type": "object",
        "properties": {
            "text": {"type": "string"},
            "count": {"type": "integer"},
        },
        "required": ["text"],
        "additionalProperties": False,
    }

    def execute(self, params: dict[str, object]) -> dict[str, object]:
        payload = _Payload(
            name=str(params["text"]),
            output=Path("artifacts") / f"{params['text']}.json",
        )
        return self.ok(
            data={"payload": payload, "count": params.get("count", 1)},
            message="echo complete",
            artifacts=[payload.output],
        )


class _BoomTool(BaseTool):
    name = "boom"
    description = "Always raises"

    def execute(self, params: dict[str, object]) -> dict[str, object]:
        raise RuntimeError(f"boom:{params.get('token', 'missing')}")


class _BadSchemaTool(BaseTool):
    name = "bad-schema"
    description = "Bad schema"
    parameters_schema = []  # type: ignore[assignment]

    def execute(self, params: dict[str, object]) -> dict[str, object]:
        return self.ok()


class _PayloadOnlyTool(BaseTool):
    name = "payload-only"
    description = "Returns plain payload"

    def execute(self, params: dict[str, object]) -> dict[str, object]:
        return {"payload_path": Path("reports") / "report.json", "params": params}


def test_safe_execute_returns_json_serializable_envelope():
    result = _EchoTool().safe_execute({"text": "demo", "count": 2})

    assert result == {
        "status": "ok",
        "message": "echo complete",
        "data": {
            "payload": {
                "name": "demo",
                "output": str(Path("artifacts") / "demo.json"),
            },
            "count": 2,
        },
        "artifacts": [str(Path("artifacts") / "demo.json")],
    }


def test_safe_execute_rejects_non_dict_params():
    result = _EchoTool().safe_execute(["not", "a", "dict"])

    assert result["status"] == "error"
    assert "params must be a dict" in result["message"]
    assert result["data"] == {}
    assert result["artifacts"] == []


def test_safe_execute_validates_required_and_typed_params():
    missing = _EchoTool().safe_execute({"count": 1})
    wrong_type = _EchoTool().safe_execute({"text": 123})
    unexpected = _EchoTool().safe_execute({"text": "demo", "extra": True})

    assert "missing required parameter(s): text" in missing["message"]
    assert "parameter 'text' must match schema type 'string'" in wrong_type["message"]
    assert "unexpected parameter(s): extra" in unexpected["message"]


def test_safe_execute_catches_execute_exceptions():
    result = _BoomTool().safe_execute({"token": "x"})

    assert result["status"] == "error"
    assert result["message"] == "RuntimeError: boom:x"
    assert result["data"] == {}
    assert result["artifacts"] == []


def test_safe_execute_rejects_invalid_schema_contract():
    result = _BadSchemaTool().safe_execute({})

    assert result["status"] == "error"
    assert result["message"] == "TypeError: parameters_schema must be a dict"


def test_safe_execute_wraps_plain_payload_results():
    result = _PayloadOnlyTool().safe_execute({"mode": "summary"})

    assert result == {
        "status": "ok",
        "message": "",
        "data": {
            "payload_path": str(Path("reports") / "report.json"),
            "params": {"mode": "summary"},
        },
        "artifacts": [],
    }


def test_tool_registry_exports_pr3_tools():
    expected = {
        "query_can_data",
        "detect_time_pattern",
        "plot_signal",
        "find-code-definition",
        "extract-ast-dependency",
        "trace-requirement",
    }

    assert expected.issubset(set(tools_pkg.TOOL_REGISTRY))
    for name in expected:
        assert issubclass(tools_pkg.TOOL_REGISTRY[name], tools_pkg.BaseTool)
