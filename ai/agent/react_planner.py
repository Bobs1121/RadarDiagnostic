# -*- coding: utf-8 -*-
"""Real ReAct agent: LLM plans sub-steps, deterministic tools execute them.

ReAct (Reason + Act): the LLM reasons about the objective and emits a JSON
plan of tool calls; :class:`ai.agent_loop.AgentLoop` executes them
deterministically. Results are fed back to the LLM for the next iteration
until the model signals completion or a step limit is reached.

This wraps *outside* the fixed diagnosis pipeline (see ADR-7): every action
still invokes a deterministic tool, so evidence remains reproducible.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Optional

from ai.agent_loop import AgentLoop, AgentToolCall
from ai.utils import parse_json_from_llm

log = logging.getLogger(__name__)

#: LLM is asked to return a JSON object of this shape (max steps for one round).
_PLAN_SCHEMA_HINT = """\
{
  "reasoning": "why these steps",
  "steps": [
    {"tool": "tool_name", "params": {...}}
  ],
  "done": false,
  "answer": ""
}
"""


@dataclass
class ReActStep:
    """One executed tool call in the ReAct trace."""

    index: int
    tool: str
    params: dict[str, Any]
    status: str  # ok | error
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ReActTrace:
    """Full trace of a ReAct run."""

    objective: str
    steps: list[ReActStep] = field(default_factory=list)
    status: str = "pending"  # running | completed | error | max_steps
    answer: str = ""
    raw_responses: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ReActPlanner:
    """LLM-driven planner that composes a ReAct loop over deterministic tools."""

    def __init__(
        self,
        router: Any,
        tool_registry: Mapping[str, Any],
        *,
        max_steps: int = 8,
        max_rounds: int = 3,
        ask_human_tool_name: str = "ask_human",
    ) -> None:
        self.router = router
        self.tool_registry = dict(tool_registry)
        self.max_steps = max(1, int(max_steps))
        self.max_rounds = max(1, int(max_rounds))
        self.ask_human_tool_name = ask_human_tool_name

    # ── Public entry ────────────────────────────────────────────────────

    def run(
        self,
        objective: str,
        context: str = "",
        *,
        fallback_plan: Optional[list[dict[str, Any]]] = None,
    ) -> ReActTrace:
        """Run the ReAct loop: plan → execute → observe → replan.

        ``fallback_plan`` (list of ``{"tool":..., "params":...}``) is executed
        first if provided, or used as the deterministic fallback when the LLM
        is unavailable.
        """
        trace = ReActTrace(objective=objective)
        loop = AgentLoop(self.tool_registry, ask_human_tool_name=self.ask_human_tool_name)
        executed_calls: list[AgentToolCall] = []

        if fallback_plan:
            trace.status = "running"
            state = loop.run(fallback_plan)
            self._absorb_loop_state(trace, state)
            return trace

        for _round in range(self.max_rounds):
            trace.status = "running"
            plan = self._llm_plan(objective, context, executed_calls, trace)
            if not plan:
                log.warning("ReAct: LLM plan empty; marking completed with no steps")
                trace.status = "completed"
                return trace
            trace.raw_responses.append(json.dumps(plan, ensure_ascii=False))

            calls = self._calls_from_plan(plan)
            if not calls:
                if plan.get("done"):
                    trace.status = "completed"
                    trace.answer = str(plan.get("answer") or "")
                    return trace
                trace.status = "error"
                return trace

            state = loop.run(calls)
            self._absorb_loop_state(trace, state)
            executed_calls.extend(calls)

            if state.status == "input_required":
                trace.status = "input_required"
                return trace
            if state.status == "error":
                trace.status = "error"
                return trace
            # Let the LLM decide whether to continue in the next round.
            if plan.get("done"):
                trace.status = "completed"
                trace.answer = str(plan.get("answer") or "")
                return trace

        trace.status = "max_steps" if len(trace.steps) >= self.max_steps else "completed"
        return trace

    # ── LLM planning ────────────────────────────────────────────────────

    def _llm_plan(
        self,
        objective: str,
        context: str,
        executed: list[AgentToolCall],
        trace: ReActTrace,
    ) -> Optional[dict[str, Any]]:
        tool_desc = self._render_tool_descriptions()
        executed_text = "\n".join(
            f"  [{s.index}] {s.tool} -> {s.status}: {s.summary[:120]}"
            for s in trace.steps[-6:]
        ) or "  (none yet)"

        system = (
            "You are a deterministic ReAct planner for an ADAS radar diagnosis tool.\n"
            "You plan SEQUENTIAL tool calls. Every tool is deterministic and safe. "
            "Never invent facts — only request tools to gather them.\n\n"
            "Available tools:\n"
            f"{tool_desc}\n\n"
            "Respond with ONLY a JSON object of this exact shape:\n"
            f"{_PLAN_SCHEMA_HINT}\n"
            "Rules:\n"
            " - 'steps' are the tool calls for THIS round (1-3).\n"
            " - Set 'done': true + a concise 'answer' when the objective is satisfied.\n"
            " - Prefer the fewest tools that answer the objective.\n"
            " - To pass typed output between steps, use a value like "
            "{\"$ref\":\"steps[0].result.data.field\"}; never interpolate or invent it.\n"
        )
        user = (
            f"Objective: {objective}\n"
            f"Context:\n{context or '(none)'}\n\n"
            f"Steps already executed:\n{executed_text}"
        )
        try:
            resp = self.router.chat(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                complexity="complex",
                temperature=0.2,
                max_tokens=1200,
            )
        except Exception as exc:  # noqa: BLE001 - boundary guard
            log.warning("ReAct: LLM plan failed (%s); returning no steps", exc)
            return None
        content = (resp or {}).get("content") or ""
        parsed = parse_json_from_llm(content, fallback=None)
        if not isinstance(parsed, dict):
            log.warning("ReAct: LLM plan not JSON (%s chars)", len(content))
            return None
        return parsed

    def _calls_from_plan(self, plan: dict[str, Any]) -> list[AgentToolCall]:
        calls: list[AgentToolCall] = []
        for raw in plan.get("steps", []) or []:
            if not isinstance(raw, dict):
                continue
            tool = raw.get("tool") or raw.get("tool_name")
            if not tool:
                continue
            params = raw.get("params") or {}
            if not isinstance(params, dict):
                params = {}
            calls.append(AgentToolCall(tool_name=str(tool), params=dict(params)))
        return calls

    # ── Absorb loop results ─────────────────────────────────────────────

    def _absorb_loop_state(self, trace: ReActTrace, state: Any) -> None:
        for step in state.steps:
            summary = self._summarize_result(step.result)
            trace.steps.append(
                ReActStep(
                    index=len(trace.steps),
                    tool=step.tool_name,
                    params=dict(step.params),
                    status=step.step_status,
                    summary=summary,
                )
            )
        if state.status != "running":
            trace.status = state.status

    @staticmethod
    def _summarize_result(result: dict[str, Any]) -> str:
        try:
            payload = json.dumps(result, ensure_ascii=False, default=str)
        except Exception:  # noqa: BLE001
            payload = str(result)
        return payload[:300]

    # ── Tool description rendering ──────────────────────────────────────

    def _render_tool_descriptions(self) -> str:
        lines: list[str] = []
        for name, entry in sorted(self.tool_registry.items()):
            desc = ""
            parameters: dict[str, Any] = {}
            if isinstance(entry, type):
                desc = getattr(entry, "description", "") or ""
                parameters = getattr(entry, "parameters_schema", {}) or {}
            else:
                desc = getattr(entry, "description", "") or ""
                parameters = getattr(entry, "parameters_schema", {}) or {}
            schema_text = ""
            if parameters:
                try:
                    schema_text = " input=" + json.dumps(parameters, ensure_ascii=False, separators=(",", ":"))
                except (TypeError, ValueError):
                    schema_text = ""
            lines.append(f"- {name}: {desc}{schema_text}")
        return "\n".join(lines) or "(no tools)"


def run_react(
    router: Any,
    tool_registry: Mapping[str, Any],
    objective: str,
    context: str = "",
    *,
    max_steps: int = 8,
    max_rounds: int = 3,
) -> ReActTrace:
    """Convenience wrapper around :class:`ReActPlanner`."""
    return ReActPlanner(
        router, tool_registry, max_steps=max_steps, max_rounds=max_rounds,
    ).run(objective, context)


__all__ = ["ReActPlanner", "ReActStep", "ReActTrace", "run_react"]
