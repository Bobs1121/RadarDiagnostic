# -*- coding: utf-8 -*-
"""
ReActModule — standalone wrapper for the real ReAct agent (LLM plans + tools).

This module exposes the ReAct loop as a V3 standalone capability: the LLM
(``ReActPlanner``) decomposes a plain-language objective into deterministic tool
calls, executed by :class:`ai.agent_loop.AgentLoop`. When ``--no-llm`` is set (or
``--tool-call`` is provided), it runs a fully deterministic fallback plan.
"""
from __future__ import annotations

import json
import sys
from collections.abc import Mapping, Sequence
from typing import Any

from .base import BaseModule, ModuleResult


def _default_tool_registry() -> dict[str, Any]:
    from ai.tools import TOOL_REGISTRY

    registry = dict(TOOL_REGISTRY)
    from ai.capability.module_bridge import build_module_tool_registry

    registry.update(build_module_tool_registry())
    return registry


def _make_router() -> Any:
    """Build a ModelRouter from config, or None when unavailable."""
    from config import load_config

    try:
        from ai.model_router import ModelRouter

        cfg = load_config()
        return ModelRouter(cfg)
    except Exception:  # noqa: BLE001 - boundary guard
        return None


class ReActModule(BaseModule):
    """V3 standalone real-ReAct agent runner (LLM plans, tools execute)."""

    name = "agent-repl"
    description = "Run a real ReAct agent: LLM plans deterministic tool calls"

    def __init__(
        self,
        *,
        router: Any = None,
        tool_registry: Mapping[str, Any] | None = None,
        max_steps: int = 8,
        max_rounds: int = 3,
        use_llm: bool = True,
    ) -> None:
        self._router = router
        self._tool_registry = (
            dict(tool_registry) if tool_registry is not None else _default_tool_registry()
        )
        self._max_steps = int(max_steps)
        self._max_rounds = int(max_rounds)
        self._use_llm = bool(use_llm)

    def run(
        self,
        *,
        objective: str = "",
        context: str = "",
        tool_calls: Sequence[dict[str, Any] | str] | dict[str, Any] | str | None = None,
        use_llm: bool | None = None,
        **_: Any,
    ) -> ModuleResult:
        from ai.agent.react_planner import ReActPlanner

        objective_text = str(objective or "")
        context_text = str(context or "")
        llm_enabled = self._use_llm if use_llm is None else bool(use_llm)

        # Deterministic fallback plan (either given or derived when LLM off).
        fallback_plan = self._normalize_tool_calls(tool_calls)
        if not llm_enabled and not fallback_plan:
            return ModuleResult.fail(
                "agent-repl: --no-llm requires --tool-call steps or --objective to plan",
                module=self.name,
            )

        router = self._router if self._use_llm else None
        if router is None and llm_enabled:
            router = _make_router()

        planner = ReActPlanner(
            router,
            self._tool_registry,
            max_steps=self._max_steps,
            max_rounds=self._max_rounds,
        )
        trace = planner.run(
            objective_text,
            context_text,
            fallback_plan=fallback_plan or None,
        )
        trace_dict = trace.to_dict()

        if trace.status == "error":
            return ModuleResult.fail(
                "agent-repl:error",
                module=self.name,
                objective=objective_text,
                trace=trace_dict,
            )
        return ModuleResult.success(
            message=f"agent-repl:{trace.status}",
            module=self.name,
            objective=objective_text,
            trace=trace_dict,
        )

    @classmethod
    def register_cli(cls, subparsers: Any) -> Any:
        parser = super().register_cli(subparsers)
        parser.add_argument("--objective", default="", help="Plain-language objective.")
        parser.add_argument("--context", default="", help="Optional diagnostic context.")
        parser.add_argument(
            "--tool-call",
            dest="tool_calls",
            action="append",
            default=[],
            metavar="JSON",
            help="Deterministic fallback tool call. Repeat for multiple steps.",
        )
        parser.add_argument(
            "--no-llm",
            dest="no_llm",
            action="store_true",
            help="Run deterministically without the LLM planner.",
        )
        return parser

    @classmethod
    def from_cli_args(cls, args: Any) -> "ReActModule":
        return cls(
            router=None,
            max_steps=getattr(args, "max_steps", 8) or 8,
            max_rounds=getattr(args, "max_rounds", 3) or 3,
            use_llm=not bool(getattr(args, "no_llm", False)),
        )

    @staticmethod
    def _normalize_tool_calls(
        tool_calls: Sequence[dict[str, Any] | str] | dict[str, Any] | str | None,
    ) -> list[dict[str, Any]]:
        if tool_calls is None:
            raw_items: list[Any] = []
        elif isinstance(tool_calls, str) or isinstance(tool_calls, Mapping):
            raw_items = [tool_calls]
        else:
            raw_items = list(tool_calls)
        out: list[dict[str, Any]] = []
        for raw in raw_items:
            if isinstance(raw, str):
                try:
                    decoded = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if isinstance(decoded, Mapping):
                    out.append(dict(decoded))
            elif isinstance(raw, Mapping):
                out.append(dict(raw))
        return out


__all__ = ["ReActModule"]


def _sync_parent_registry() -> None:
    """Keep ai.modules.MODULE_REGISTRY coherent on direct submodule imports."""
    parent = sys.modules.get("ai.modules")
    if parent is None:
        return

    registry = getattr(parent, "MODULE_REGISTRY", None)
    if isinstance(registry, dict):
        registry.setdefault(ReActModule.name, ReActModule)

    exported = getattr(parent, "__all__", None)
    if isinstance(exported, list) and "ReActModule" not in exported:
        exported.append("ReActModule")


_sync_parent_registry()
