# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ai.agent_tool_registry import build_agent_tool_registry, resolve_agent_tool_context
from ai.modules.agent_loop import AgentLoopModule


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
        return _FakeFunction(
            id=f"FUNCTION:{name}",
            type="FUNCTION",
            name=name,
            file_path=r"coem\adas\alarm.c",
            start_line=10,
            end_line=24,
        )

    def get_callers(self, name: str):
        return []

    def get_callees(self, name: str):
        return []

    def get_call_chain(self, name: str, max_depth: int = 5):
        return []

    def get_signals_used_by(self, name: str):
        return []

    def get_variables_read_by(self, name: str):
        return []

    def get_variables_written_by(self, name: str):
        return []

    def get_functions_using_signal(self, signal_name: str):
        if signal_name != "FCTA_WARN":
            return []
        return [{"func_name": "FctaAlarmProcess", "file_id": "FILE:coem\\adas\\alarm.c"}]


def test_build_agent_tool_registry_store_only():
    context = resolve_agent_tool_context(store=object())

    registry = build_agent_tool_registry(context)

    assert set(registry) == {"plot_signal", "query_can_data"}


def test_resolve_agent_tool_context_uses_config_paths(tmp_path: Path):
    source_root = tmp_path / "src"
    source_root.mkdir()
    codegraph_db = tmp_path / "memory" / "codegraph" / "tooling.db"
    codegraph_db.parent.mkdir(parents=True)
    codegraph_db.write_text("", encoding="utf-8")

    context = resolve_agent_tool_context(
        project_root=tmp_path,
        store=object(),
        config={
            "project": {"codegraph_db_path": str(codegraph_db)},
            "paths": {"source_code": str(source_root)},
        },
    )

    registry = build_agent_tool_registry(context)

    assert context.codegraph_db_path == codegraph_db
    assert context.source_root == source_root
    assert set(registry) == {
        "detect_time_pattern",
        "extract-ast-dependency",
        "find-code-definition",
        "plot_signal",
        "query_can_data",
    }


def test_requirement_dir_loads_trace_requirement_tool_for_agent_loop(tmp_path: Path):
    req_dir = tmp_path / "requirements"
    req_dir.mkdir()
    (req_dir / "fcta.yaml").write_text(
        "\n".join([
            "req_id: REQ-FCTA-001",
            "feature: FCTA",
            "description: Raise FCTA warning output when FCTA_WARN is asserted.",
            "activation_conditions:",
            "  - signal_alias: FCTA_WARN",
            '    operator: "=="',
            "    value: 1",
            "expected_output_signal: FCTA_WARN",
            "",
        ]),
        encoding="utf-8",
    )

    context = resolve_agent_tool_context(
        project_root=tmp_path,
        config={"identity": {"variant_id": "gen6/gwm_b26"}},
        codegraph=_FakeCodeGraph(),
        requirement_dir=req_dir,
        signal_mapping={"can_to_internal": {"FCTA_WARN": ["warnState"]}},
    )

    registry = build_agent_tool_registry(context)
    module = AgentLoopModule(tool_registry=registry)

    result = module.safe_run(
        objective="trace loaded requirement",
        tool_calls=[{"tool": "trace-requirement", "params": {"req_id": "REQ-FCTA-001"}}],
    )

    assert context.req_set is not None
    assert context.req_set.variant_id == "gen6/gwm_b26"
    assert result.ok is True
    trace = result.data["state"]["steps"][0]["result"]["data"]["trace"]
    assert trace["req_id"] == "REQ-FCTA-001"
    assert trace["coverage"] == "full"
    assert trace["linked_functions"] == ["FctaAlarmProcess"]


def test_missing_optional_dirs_do_not_raise(tmp_path: Path):
    context = resolve_agent_tool_context(
        project_root=tmp_path,
        config={
            "project": {
                "codegraph_db_path": str(tmp_path / "missing" / "codegraph.db"),
                "requirement_dir": str(tmp_path / "missing" / "requirements"),
            },
            "paths": {"source_code": str(tmp_path / "missing" / "src")},
        },
        store=object(),
    )

    registry = build_agent_tool_registry(context)

    assert context.codegraph_db_path == tmp_path / "missing" / "codegraph.db"
    assert context.requirement_dir == tmp_path / "missing" / "requirements"
    assert context.source_root == tmp_path / "missing" / "src"
    assert set(registry) == {"plot_signal", "query_can_data"}


class _WorkspaceLike:
    name = "gen6_gwm_b26"

    def __init__(self, root: Path) -> None:
        self.workspace_dir = root
        self._memory_dir = root / "memory"
        self._source_dir = root / "coem"

    def get_config(self):
        return {"identity": {"variant_id": "gen6/gwm_b26"}}

    def get_source_paths(self):
        return [self._source_dir]

    def get_memory_dir(self):
        self._memory_dir.mkdir(parents=True, exist_ok=True)
        return self._memory_dir

    def get_requirements_schema(self):
        return {
            "FCTA": {
                "requirement_id": "REQ-FCTA-WORKSPACE",
                "statement": "Workspace requirement should trace FCTA_WARN.",
                "linked_signals": ["FCTA_WARN"],
            }
        }


def test_workspace_fallbacks_resolve_requirements_and_codegraph_path(tmp_path: Path):
    workspace_root = tmp_path / "ws"
    source_dir = workspace_root / "coem"
    source_dir.mkdir(parents=True)
    workspace = _WorkspaceLike(workspace_root)

    codegraph_db = workspace.get_memory_dir() / "codegraph.db"
    codegraph_db.write_text("", encoding="utf-8")

    context = resolve_agent_tool_context(
        project_root=tmp_path,
        workspace=workspace,
        codegraph=_FakeCodeGraph(),
        signal_mapping={"can_to_internal": {"FCTA_WARN": ["warnState"]}},
    )
    registry = build_agent_tool_registry(context)

    assert context.source_root == source_dir
    assert context.codegraph_db_path == codegraph_db
    assert context.req_set is not None
    assert "REQ-FCTA-WORKSPACE" in context.req_set.requirements
    assert "trace-requirement" in registry
