# -*- coding: utf-8 -*-
"""
AgentLoopModule — standalone wrapper for the offline deterministic AgentLoop.

This module exposes the planned-tool execution loop as a V3 standalone capability
without touching legacy diagnosis defaults. It accepts a plain-language objective
plus a pre-baked sequence of tool calls, executes them with the deterministic
tool registry, and returns the serializable Agent state snapshot.
"""
from __future__ import annotations

import json
import sys
from collections.abc import Mapping, Sequence
from typing import Any

from ai.agent_loop import AgentLoop, AgentState, AgentStep, AgentToolCall
from ai.tools.base import build_tool_result, serialize_jsonable

from .base import BaseModule, ModuleResult


def _default_tool_registry() -> dict[str, Any]:
    from ai.tools import TOOL_REGISTRY

    registry = dict(TOOL_REGISTRY)
    from ai.capability.module_bridge import build_module_tool_registry

    registry.update(build_module_tool_registry())
    return registry


class AgentLoopModule(BaseModule):
    """V3 standalone offline Agent loop runner."""

    name = "agent-loop"
    description = "Run a deterministic offline AgentLoop plan (V3)"

    def __init__(
        self,
        *,
        tool_registry: Mapping[str, Any] | None = None,
        ask_human_tool_name: str = "ask_human",
    ) -> None:
        self._tool_registry = (
            dict(tool_registry) if tool_registry is not None else _default_tool_registry()
        )
        self._ask_human_tool_name = ask_human_tool_name

    def run(
        self,
        *,
        objective: str = "",
        tool_calls: Sequence[dict[str, Any] | str] | dict[str, Any] | str | None = None,
        **_: Any,
    ) -> ModuleResult:
        objective_text = str(objective or "")
        plan, error_message = self._normalize_tool_calls(tool_calls)
        if error_message:
            return self._fail_with_state(
                objective=objective_text,
                message=error_message,
                raw_tool_calls=tool_calls,
            )

        state = AgentLoop(
            self._tool_registry,
            ask_human_tool_name=self._ask_human_tool_name,
        ).run(plan)
        state_dict = state.to_dict()

        if state.status == "error":
            return ModuleResult.fail(
                state.last_result.get("message") or "agent-loop:error",
                module=self.name,
                objective=objective_text,
                state=state_dict,
            )

        return ModuleResult.success(
            message=f"agent-loop:{state.status}",
            module=self.name,
            objective=objective_text,
            state=state_dict,
        )

    @classmethod
    def register_cli(cls, subparsers: Any) -> Any:
        parser = super().register_cli(subparsers)
        parser.add_argument(
            "--objective",
            default="",
            help="Plain-language objective for the offline AgentLoop run.",
        )
        parser.add_argument(
            "--tool-call",
            dest="tool_calls",
            action="append",
            default=[],
            metavar="JSON",
            help="Planned tool call as JSON. Repeat for multiple steps.",
        )
        return parser

    @classmethod
    def from_cli_args(cls, args: Any) -> "AgentLoopModule":
        return cls()

    @staticmethod
    def _normalize_tool_calls(
        tool_calls: Sequence[dict[str, Any] | str] | dict[str, Any] | str | None,
    ) -> tuple[list[AgentToolCall | dict[str, Any]], str]:
        if tool_calls is None:
            raw_items: list[Any] = []
        elif isinstance(tool_calls, (str, AgentToolCall)) or isinstance(tool_calls, Mapping):
            raw_items = [tool_calls]
        else:
            raw_items = list(tool_calls)

        plan: list[AgentToolCall | dict[str, Any]] = []
        for index, raw_call in enumerate(raw_items):
            if isinstance(raw_call, AgentToolCall):
                plan.append(raw_call)
                continue
            if isinstance(raw_call, str):
                try:
                    decoded = json.loads(raw_call)
                except json.JSONDecodeError as exc:
                    return [], f"invalid tool_call JSON at index {index}: {exc.msg}"
                if not isinstance(decoded, Mapping):
                    return [], f"tool_call JSON at index {index} must decode to an object"
                plan.append(dict(decoded))
                continue
            if isinstance(raw_call, Mapping):
                plan.append(dict(raw_call))
                continue
            return [], f"tool_call at index {index} must be a mapping or JSON string"
        return plan, ""

    def _fail_with_state(
        self,
        *,
        objective: str,
        message: str,
        raw_tool_calls: Sequence[dict[str, Any] | str] | dict[str, Any] | str | None,
    ) -> ModuleResult:
        error_result = build_tool_result(
            status="error",
            message=message,
            data={"raw_tool_calls": serialize_jsonable(raw_tool_calls)},
        )
        state = AgentState(plan=[], status="error")
        state.steps.append(
            AgentStep(
                index=0,
                tool_name="<invalid-tool-call>",
                params={},
                step_status="error",
                result=error_result,
            )
        )
        state.last_result = dict(error_result)
        state.next_step_index = 1
        return ModuleResult.fail(
            message,
            module=self.name,
            objective=objective,
            state=state.to_dict(),
        )


__all__ = ["AgentLoopModule"]


def _sync_parent_registry() -> None:
    """Keep ai.modules.MODULE_REGISTRY coherent on direct submodule imports."""
    parent = sys.modules.get("ai.modules")
    if parent is None:
        return

    registry = getattr(parent, "MODULE_REGISTRY", None)
    if isinstance(registry, dict):
        registry.setdefault(AgentLoopModule.name, AgentLoopModule)

    exported = getattr(parent, "__all__", None)
    if isinstance(exported, list) and "AgentLoopModule" not in exported:
        exported.append("AgentLoopModule")


_sync_parent_registry()
