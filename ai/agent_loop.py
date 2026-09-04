# -*- coding: utf-8 -*-
"""Minimal offline Agent/ReAct loop for deterministic planned tool execution."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
import re
from typing import Any

from ai.tools.base import BaseTool, build_tool_result, serialize_jsonable

ToolRegistryEntry = BaseTool | type[BaseTool]


@dataclass
class AgentToolCall:
    """A planned tool invocation that can cross a JSON boundary."""

    tool_name: str
    params: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_value(cls, value: AgentToolCall | Mapping[str, Any]) -> AgentToolCall:
        if isinstance(value, cls):
            return cls(
                tool_name=str(value.tool_name),
                params=serialize_jsonable(dict(value.params)),
            )
        if not isinstance(value, Mapping):
            raise TypeError("plan entry must be an AgentToolCall or mapping")

        tool_name = value.get("tool_name", value.get("tool"))
        if not tool_name:
            raise ValueError("plan entry must include tool_name")

        params = value.get("params", {})
        if params is None:
            params = {}
        if not isinstance(params, Mapping):
            raise TypeError("plan entry params must be a mapping")

        return cls(
            tool_name=str(tool_name),
            params=serialize_jsonable(dict(params)),
        )

    def to_dict(self) -> dict[str, Any]:
        return serialize_jsonable(asdict(self))


@dataclass
class AgentStep:
    """A single executed step in the deterministic Agent loop."""

    index: int
    tool_name: str
    params: dict[str, Any]
    step_status: str
    result: dict[str, Any]
    resolved_params: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return serialize_jsonable(asdict(self))


@dataclass
class AgentState:
    """Serializable state snapshot for a deterministic Agent loop run."""

    plan: list[AgentToolCall]
    status: str = "pending"
    steps: list[AgentStep] = field(default_factory=list)
    next_step_index: int = 0
    last_result: dict[str, Any] = field(default_factory=dict)
    artifacts: list[Any] = field(default_factory=list)
    pending_input: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return serialize_jsonable(asdict(self))


class _ErrorTool(BaseTool):
    """Produces a structured tool error through the normal safe_execute path."""

    def __init__(self, tool_name: str, message: str, *, data: dict[str, Any] | None = None) -> None:
        self.name = tool_name
        self.description = message
        self._message = message
        self._data = dict(data or {})

    def execute(self, params: dict[str, Any]) -> dict[str, Any]:
        payload = dict(self._data)
        if params:
            payload["params"] = serialize_jsonable(params)
        return self.error(self._message, data=payload)


class AgentLoop:
    """Runs a deterministic plan of Agent-callable tools without any LLM."""

    def __init__(
        self,
        tool_registry: Mapping[str, ToolRegistryEntry],
        *,
        ask_human_tool_name: str = "ask_human",
    ) -> None:
        self.tool_registry = dict(tool_registry)
        self.ask_human_tool_name = ask_human_tool_name

    def run(self, plan: Sequence[AgentToolCall | Mapping[str, Any]]) -> AgentState:
        state = AgentState(plan=[])
        for raw_call in plan:
            try:
                state.plan.append(AgentToolCall.from_value(raw_call))
            except (TypeError, ValueError) as exc:
                return self._append_error_step(
                    state,
                    tool_name="<invalid-plan>",
                    params={},
                    message=f"Invalid plan entry: {exc}",
                )

        if not state.plan:
            state.status = "completed"
            return state

        state.status = "running"
        for index, call in enumerate(state.plan):
            state.next_step_index = index
            if call.tool_name == self.ask_human_tool_name:
                return self._mark_input_required(state, index, call)

            try:
                resolved_params = resolve_agent_references(call.params, state)
            except (TypeError, ValueError) as exc:
                return self._append_error_step(
                    state,
                    tool_name=call.tool_name,
                    params=call.params,
                    message=f"Invalid artifact reference: {exc}",
                )

            tool = self._resolve_tool(call.tool_name)
            result = tool.safe_execute(resolved_params)
            step_status = "ok" if result.get("status") == "ok" else "error"
            self._append_step(
                state,
                AgentStep(
                    index=index,
                    tool_name=call.tool_name,
                    params=serialize_jsonable(call.params),
                    step_status=step_status,
                    result=serialize_jsonable(result),
                    resolved_params=serialize_jsonable(resolved_params),
                ),
            )
            if step_status == "error":
                state.status = "error"
                return state

        state.status = "completed"
        return state

    def _resolve_tool(self, tool_name: str) -> BaseTool:
        entry = self.tool_registry.get(tool_name)
        if entry is None:
            return _ErrorTool(
                tool_name,
                f"Unknown tool: {tool_name}",
                data={"available_tools": sorted(self.tool_registry)},
            )
        if isinstance(entry, BaseTool):
            return entry
        if isinstance(entry, type) and issubclass(entry, BaseTool):
            try:
                return entry()
            except Exception as exc:  # noqa: BLE001 - boundary guard
                return _ErrorTool(
                    tool_name,
                    f"Failed to initialize tool {tool_name}: {type(exc).__name__}: {exc}",
                )
        return _ErrorTool(
            tool_name,
            f"Invalid tool registry entry for {tool_name}",
            data={"entry_type": type(entry).__name__},
        )

    def _mark_input_required(self, state: AgentState, index: int, call: AgentToolCall) -> AgentState:
        question = self._extract_question(call.params)
        prompt_payload = {
            "tool_name": call.tool_name,
            "question": question,
            "params": serialize_jsonable(call.params),
        }
        result = build_tool_result(
            status="ok",
            message=question or "Input required",
            data=prompt_payload,
            artifacts=[],
        )
        self._append_step(
            state,
            AgentStep(
                index=index,
                tool_name=call.tool_name,
                params=serialize_jsonable(call.params),
                step_status="input_required",
                result=result,
            ),
        )
        state.pending_input = prompt_payload
        state.status = "input_required"
        return state

    def _append_error_step(
        self,
        state: AgentState,
        *,
        tool_name: str,
        params: dict[str, Any],
        message: str,
    ) -> AgentState:
        result = _ErrorTool(tool_name, message).safe_execute(params)
        self._append_step(
            state,
            AgentStep(
                index=state.next_step_index,
                tool_name=tool_name,
                params=serialize_jsonable(params),
                step_status="error",
                result=result,
            ),
        )
        state.status = "error"
        return state

    def _append_step(self, state: AgentState, step: AgentStep) -> None:
        state.steps.append(step)
        state.last_result = dict(step.result)
        artifacts = step.result.get("artifacts", [])
        serialized_artifacts = serialize_jsonable(artifacts)
        if isinstance(serialized_artifacts, list):
            state.artifacts.extend(serialized_artifacts)
        else:
            state.artifacts.append(serialized_artifacts)
        state.next_step_index = step.index + 1

    @staticmethod
    def _extract_question(params: dict[str, Any]) -> str:
        for key in ("question", "prompt", "message"):
            value = params.get(key)
            if value:
                return str(value)
        return ""


__all__ = [
    "AgentLoop",
    "AgentState",
    "AgentStep",
    "AgentToolCall",
    "resolve_agent_references",
]


def resolve_agent_references(value: Any, state: AgentState) -> Any:
    """Resolve explicit ``{"$ref": "steps[0].result.data.field"}`` values.

    References are deliberately structured rather than string interpolation:
    lists/dicts remain typed, missing paths fail closed, and the original plan
    is still retained in ``AgentState.plan`` for auditability.
    """
    if isinstance(value, Mapping):
        if set(value) == {"$ref"}:
            return _resolve_agent_reference(str(value["$ref"]), state)
        return {str(key): resolve_agent_references(child, state) for key, child in value.items()}
    if isinstance(value, list):
        return [resolve_agent_references(child, state) for child in value]
    if isinstance(value, tuple):
        return [resolve_agent_references(child, state) for child in value]
    return value


def _resolve_agent_reference(reference: str, state: AgentState) -> Any:
    text = str(reference or "").strip()
    match = re.fullmatch(r"steps\[(\d+)\]\.(.+)", text)
    if not match:
        raise ValueError(
            f"unsupported reference {reference!r}; expected steps[N].result.data.field"
        )
    index = int(match.group(1))
    if index < 0 or index >= len(state.steps):
        raise ValueError(f"step index out of range: {index}")
    path = match.group(2).split(".")
    current: Any = state.steps[index].result
    if path and path[0] == "result":
        path = path[1:]
    for segment in path:
        if isinstance(current, Mapping) and segment in current:
            current = current[segment]
            continue
        if isinstance(current, list) and segment.isdigit():
            numeric = int(segment)
            if numeric < len(current):
                current = current[numeric]
                continue
        raise ValueError(f"reference path missing at {segment!r}: {reference}")
    return serialize_jsonable(current)
