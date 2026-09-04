# -*- coding: utf-8 -*-
"""
ai.agent — real ReAct agent (LLM plans, deterministic tools execute).

``ReActPlanner`` uses the ModelRouter to decompose an objective into a sequence
of :class:`AgentToolCall` steps; :class:`ai.agent_loop.AgentLoop` executes them
deterministically. The loop is wrapped *outside* the fixed 8-step diagnosis
pipeline: each action still calls a deterministic tool (DataProbe / TPE /
CodeGraph / requirement trace), so evidence stays reproducible.

See docs/production/31-software-architecture.md §2.6.5 and ADR-7.
"""
from __future__ import annotations

from ai.agent.react_planner import ReActPlanner, ReActStep, ReActTrace, run_react

__all__ = ["ReActPlanner", "ReActStep", "ReActTrace", "run_react"]
