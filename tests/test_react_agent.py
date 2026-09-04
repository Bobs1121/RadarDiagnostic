# -*- coding: utf-8 -*-
"""Stage 5 tests: real ReAct agent (ReActPlanner + AgentLoop).

Uses a fake ModelRouter (returns a canned JSON plan) with the real deterministic
tool registry — proving the LLM plans and the deterministic tools execute,
without any live LLM or real data files.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


class _FakeRouter:
    """Returns a scripted sequence of JSON plans."""

    def __init__(self, responses: list[dict]):
        self._responses = list(responses)
        self.calls: list[dict] = []

    def chat(self, messages, **kwargs):
        self.calls.append({"messages": messages, "kwargs": kwargs})
        plan = self._responses.pop(0) if self._responses else {"done": True, "answer": ""}
        return {"content": __import__("json").dumps(plan, ensure_ascii=False)}


# ── ReActPlanner unit tests ────────────────────────────────────────────────

class TestReActPlanner:
    def test_llm_plan_executes_tools_and_completes(self):
        from ai.agent.react_planner import ReActPlanner
        from ai.agent_tool_registry import build_agent_tool_registry
        from ai.agent_tool_registry import AgentToolContext
        from parsers.frame_store import FrameStore

        # Build a store with radar_objects rows so query_can_data works.
        store = FrameStore(":memory:")
        store.bulk_insert_radar_objects([
            {"timestamp_ns": 1_000_000_000, "radar_id": 1, "obj_id": 1,
             "dist_x": -2.0, "dist_y": 1.0, "ttc": 2.4},
        ])
        context = AgentToolContext(
            project_root=_PROJECT_ROOT,
            store=store,
            codegraph=None,
            req_set=None,
            signal_mapping={"can_to_internal": {"WarnCAN": ["warn_state"]}},
        )
        registry = build_agent_tool_registry(context)

        router = _FakeRouter([
            {"reasoning": "query the data", "steps": [
                {"tool": "query_can_data", "params": {"field": "ttc", "table": "radar_objects", "stats": ["count"]}},
            ], "done": False},
            {"reasoning": "done", "steps": [], "done": True, "answer": "ttc observed"},
        ])
        planner = ReActPlanner(router, registry, max_rounds=3)
        trace = planner.run("check ttc", "FCTA case")

        assert trace.status == "completed"
        assert len(trace.steps) >= 1
        assert trace.steps[0].tool == "query_can_data"
        assert trace.answer == "ttc observed"
        assert len(router.calls) == 2

    def test_fallback_plan_executes_deterministically(self):
        from ai.agent.react_planner import ReActPlanner
        from ai.tools.base import BaseTool

        calls: list[str] = []

        class _T(BaseTool):
            name = "demo"
            description = "demo tool"
            def execute(self, params):
                calls.append(params.get("x"))
                return self.ok(data={"echo": params.get("x")})

        planner = ReActPlanner(router=None, tool_registry={"demo": _T})
        trace = planner.run(
            "demo", fallback_plan=[{"tool": "demo", "params": {"x": 1}},
                                    {"tool": "demo", "params": {"x": 2}}],
        )
        assert trace.status == "completed"
        assert calls == [1, 2]
        assert len(trace.steps) == 2

    def test_llm_failure_returns_no_steps(self):
        from ai.agent.react_planner import ReActPlanner

        class _BrokenRouter:
            def chat(self, messages, **kwargs):
                raise RuntimeError("llm down")

        planner = ReActPlanner(_BrokenRouter(), {})
        trace = planner.run("anything")
        assert trace.status == "completed"
        assert trace.steps == []

    def test_run_react_helper(self):
        from ai.agent.react_planner import run_react
        from ai.tools.base import BaseTool

        class _T(BaseTool):
            name = "t"
            description = ""
            def execute(self, params):
                return self.ok()

        # Fake router returns an immediate "done" plan → helper completes.
        router = _FakeRouter([
            {"reasoning": "nothing to do", "steps": [], "done": True, "answer": "ok"},
        ])
        trace = run_react(router, {"t": _T}, "obj")
        assert trace.status == "completed"
        assert trace.answer == "ok"


# ── ReAct + AgentLoop integration (deterministic) ─────────────────────────

class TestReActIntegration:
    def test_react_uses_real_tools_no_llm_with_fallback(self):
        """End-to-end: fallback plan through real tool registry completes."""
        from ai.agent.react_planner import ReActPlanner
        from ai.agent_tool_registry import AgentToolContext, build_agent_tool_registry
        from parsers.frame_store import FrameStore

        store = FrameStore(":memory:")
        store.bulk_insert_radar_objects([
            {"timestamp_ns": 1_000_000_000, "radar_id": 1, "obj_id": 1,
             "dist_x": -2.0, "dist_y": 1.0, "ttc": 2.4, "fcta_flag": 1},
        ])
        context = AgentToolContext(
            project_root=_PROJECT_ROOT, store=store,
            codegraph=None, req_set=None,
            signal_mapping={"can_to_internal": {"WarnCAN": ["warn_state"]}},
        )
        registry = build_agent_tool_registry(context)

        planner = ReActPlanner(router=None, tool_registry=registry)
        trace = planner.run(
            "check ttc",
            fallback_plan=[{"tool": "query_can_data", "params": {"field": "ttc", "table": "radar_objects"}}],
        )
        assert trace.status == "completed"
        assert trace.steps[0].tool == "query_can_data"
        assert trace.steps[0].status == "ok"


# ── ReActModule (CLI wrapper) ──────────────────────────────────────────────

class TestReActModule:
    def test_registered_in_module_registry(self):
        from ai.modules import MODULE_REGISTRY

        assert "agent-repl" in MODULE_REGISTRY

    def test_no_llm_requires_fallback_plan(self):
        from ai.modules.react_agent import ReActModule

        res = ReActModule(use_llm=False).run(objective="x", tool_calls=None)
        assert res.ok is False

    def test_deterministic_fallback_plan(self):
        from ai.modules.react_agent import ReActModule
        from ai.tools.base import BaseTool

        calls: list[int] = []

        class _T(BaseTool):
            name = "demo"
            description = ""
            def execute(self, params):
                calls.append(params.get("n"))
                return self.ok()

        mod = ReActModule(use_llm=False, tool_registry={"demo": _T})
        res = mod.run(
            objective="demo",
            tool_calls=[{"tool": "demo", "params": {"n": 1}},
                        {"tool": "demo", "params": {"n": 2}}],
        )
        assert res.ok is True
        assert calls == [1, 2]
        trace = res.data["trace"]
        assert trace["status"] == "completed"
        assert len(trace["steps"]) == 2