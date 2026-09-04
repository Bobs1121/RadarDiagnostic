# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass

from ai.modules.base import ModuleResult
from ai.tools.code_tools import (
    ExtractASTDependencyTool,
    FindCodeDefinitionTool,
    TraceRequirementTool,
)
from core.materials import RequirementSpec, StructuredRequirementSet


@dataclass
class _FakeFunction:
    id: str
    type: str
    name: str
    file_path: str
    start_line: int
    end_line: int


class _FakeCodeGraph:
    def get_function_by_name(self, name: str):
        if name == "MissingFn":
            return None
        return _FakeFunction(
            id=f"FUNCTION:{name}",
            type="FUNCTION",
            name=name,
            file_path=r"coem\adas\alarm.c",
            start_line=12,
            end_line=48,
        )

    def get_callers(self, name: str):
        return [{"caller_name": "MainLoop", "target": name, "line": 100}]

    def get_callees(self, name: str):
        return [{"callee_name": "EvaluateWarning", "source": name, "line": 120}]

    def get_call_chain(self, name: str, max_depth: int = 5):
        return [{"func_name": "MainLoop", "depth": 1, "path": f"MainLoop -> {name}", "max_depth": max_depth}]

    def get_signals_used_by(self, name: str):
        return [{"signal_name": "FCTA_WARN", "type": "READS_SIGNAL", "line": 140}]

    def get_variables_read_by(self, name: str):
        return [{"var_name": "vehSpeed", "type": "READS_VAR", "line": 150}]

    def get_variables_written_by(self, name: str):
        return [{"var_name": "warnState", "type": "WRITES_VAR", "line": 160}]

    def get_functions_using_signal(self, signal_name: str):
        if signal_name == "FCTA_WARN":
            return [{"func_name": "FctaAlarmProcess", "file_id": "FILE:coem\\adas\\alarm.c"}]
        return []


class _FakeCodeStructureModule:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def safe_run(self, **kwargs):
        self.calls.append(kwargs)
        return ModuleResult.success(
            message="code-query:function",
            module="code-query",
            data={
                "name": kwargs["name"],
                "file_path": r"coem\adas\module.c",
                "start_line": 7,
                "end_line": 19,
            },
        )


class _FakeSignalBridge:
    def safe_run(self, *, mode: str, query: str = "", **kwargs):
        assert mode == "function-outputs"
        assert query
        return ModuleResult.success(
            message="signal-bridge:function-outputs",
            module="signal-bridge",
            data={
                "matches": ["FCTA_WARN_OUT", "FCTA_WARN_REQ"],
                "sources": {"output_mapping": "injected"},
            },
        )


class _ExplodingCodeGraph:
    def get_function_by_name(self, name: str):
        raise RuntimeError("boom")


def test_find_code_definition_with_codegraph():
    tool = FindCodeDefinitionTool(codegraph=_FakeCodeGraph())

    result = tool.safe_execute(name="FctaAlarmProcess")

    assert result["status"] == "ok"
    assert result["tool"] == "find-code-definition"
    assert result["data"]["found"] is True
    assert result["data"]["definition"]["file_path"] == r"coem\adas\alarm.c"
    assert result["data"]["definition"]["start_line"] == 12


def test_find_code_definition_uses_module_like_backend():
    backend = _FakeCodeStructureModule()
    tool = FindCodeDefinitionTool(code_structure=backend)

    result = tool.safe_execute(name="FctaAlarmProcess")

    assert result["status"] == "ok"
    assert result["data"]["backend"]["source"] == "code-structure-module"
    assert backend.calls[0]["query_type"] == "function"
    assert result["data"]["definition"]["file_path"] == r"coem\adas\module.c"


def test_find_code_definition_returns_structured_error():
    tool = FindCodeDefinitionTool(codegraph=_ExplodingCodeGraph())

    result = tool.safe_execute(name="AnyFn")

    assert result["status"] == "error"
    assert "get_function_by_name failed" in result["message"]


def test_extract_ast_dependency_collects_sections_and_function_outputs():
    tool = ExtractASTDependencyTool(
        codegraph=_FakeCodeGraph(),
        signal_bridge=_FakeSignalBridge(),
    )

    result = tool.safe_execute(name="FctaAlarmProcess", max_depth=3)

    assert result["status"] == "ok"
    assert result["data"]["counts"]["callers"] == 1
    assert result["data"]["counts"]["function_outputs"] == 2
    assert result["data"]["dependencies"]["signals"][0]["signal_name"] == "FCTA_WARN"
    assert result["data"]["dependencies"]["function_outputs"] == [
        "FCTA_WARN_OUT",
        "FCTA_WARN_REQ",
    ]
    assert result["data"]["signal_bridge"]["status"] == "ok"


def test_extract_ast_dependency_missing_graph_is_graceful_error():
    tool = ExtractASTDependencyTool()

    result = tool.safe_execute(name="FctaAlarmProcess")

    assert result["status"] == "error"
    assert result["data"]["backend"]["available"] is False
    assert result["data"]["dependencies"]["callers"] == []
    assert "no AST dependency data available" in result["message"]


def test_trace_requirement_single_spec():
    spec = RequirementSpec(
        requirement_id="REQ-FCTA-001",
        statement="Warn when FCTA warns.",
        linked_signals=["FCTA_WARN"],
    )
    tool = TraceRequirementTool(
        codegraph=_FakeCodeGraph(),
        signal_mapping={"can_to_internal": {"FCTA_WARN": ["warnState"]}},
    )

    result = tool.safe_execute(spec=spec)

    assert result["status"] == "ok"
    assert result["data"]["mode"] == "trace-one"
    assert result["data"]["trace"]["coverage"] == "full"
    assert result["data"]["trace"]["linked_functions"] == ["FctaAlarmProcess"]


def test_trace_requirement_set_and_req_id_lookup():
    req_set = StructuredRequirementSet(variant_id="gwm_b26")
    req_set.add(
        RequirementSpec(
            requirement_id="REQ-FCTA-001",
            statement="Warn when FCTA warns.",
            linked_signals=["FCTA_WARN"],
        )
    )
    req_set.add(
        RequirementSpec(
            requirement_id="REQ-FCTA-002",
            statement="Track missing signal.",
            linked_signals=["FCTA_MISSING"],
        )
    )
    tool = TraceRequirementTool(
        req_set=req_set,
        codegraph=_FakeCodeGraph(),
        signal_mapping={"can_to_internal": {"FCTA_WARN": ["warnState"]}},
    )

    one = tool.safe_execute(req_id="REQ-FCTA-001")
    all_traces = tool.safe_execute()

    assert one["status"] == "ok"
    assert one["data"]["trace"]["coverage"] == "full"
    assert all_traces["status"] == "ok"
    assert all_traces["data"]["mode"] == "trace-set"
    assert all_traces["data"]["trace_count"] == 2


def test_trace_requirement_missing_req_id_is_structured_error():
    req_set = StructuredRequirementSet(variant_id="gwm_b26")
    req_set.add(RequirementSpec(requirement_id="REQ-FCTA-001"))
    tool = TraceRequirementTool(req_set=req_set)

    result = tool.safe_execute(req_id="REQ-UNKNOWN")

    assert result["status"] == "error"
    assert result["data"]["available_req_ids"] == ["REQ-FCTA-001"]
