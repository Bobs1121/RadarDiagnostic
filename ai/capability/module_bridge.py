# -*- coding: utf-8 -*-
"""Expose registered ``BaseModule`` capabilities as Agent-callable tools.

``MODULE_REGISTRY`` is the CLI/module registry; ``AgentLoop`` consumes
``BaseTool`` instances.  This bridge keeps those two contracts separate while
allowing Pi/ReAct to call deterministic modules through the same JSON result
envelope.  A module that contains an explicit ``execute`` switch is planned
only by default; the orchestration supervisor must construct the bridge with
``allow_execution=True`` after the user approval gate.  The default bridge
auto-discovers all registered leaf capabilities, so new modules become
composable without editing this file.
"""
from __future__ import annotations

from typing import Any, Iterable

from ai.tools.base import BaseTool


# These modules are orchestration roots rather than leaf capabilities.  Exclude
# them from the module-as-tool bridge to avoid Pi recursively invoking another
# Pi/AgentLoop.  Every other registered BaseModule is discoverable by default;
# adding a module to MODULE_REGISTRY is therefore sufficient to make it a
# composable tool.
_DEFAULT_EXCLUDED_MODULES = {"pi", "agent-repl", "agent-loop"}


class ModuleToolAdapter(BaseTool):
    """Adapt one registered ``BaseModule`` to the ``BaseTool`` contract."""

    def __init__(self, module_cls: type, *, allow_execution: bool = False) -> None:
        self.module_cls = module_cls
        self.allow_execution = bool(allow_execution)
        self.name = str(getattr(module_cls, "name", "module"))
        self.description = str(getattr(module_cls, "description", "") or "")
        from ai.capability.registry import module_input_schema

        self.parameters_schema = module_input_schema(module_cls)

    def execute(self, params: dict[str, Any]) -> dict[str, Any]:
        # `execute=true` is the explicit side-effect/remote-operation switch
        # used by CR60 precheck.  Planning remains available to Pi, but actual
        # execution is opened only by the supervisor after user confirmation.
        requires_approval = bool(getattr(self.module_cls, "requires_approval", False))
        approval_mode = str(getattr(self.module_cls, "approval_mode", "explicit_execute"))
        execution_requested = params.get("execute") is True or approval_mode == "always"
        if execution_requested and requires_approval and not self.allow_execution:
            return self.error(
                f"module '{self.name}' requires approval before execution",
                data={
                    "approval_required": True,
                    "module": self.name,
                    "approval_mode": approval_mode,
                },
            )
        # Reuse the module's existing CLI-to-constructor mapping when it has
        # one.  This is important for legacy modules whose file/source inputs
        # are constructor state (BSD MF4, signal-audit BLF, code-learn paths)
        # rather than explicit run() parameters.  Pi still supplies a plain
        # JSON object; no argparse parsing or shell execution occurs here.
        try:
            from types import SimpleNamespace

            module = self.module_cls.from_cli_args(SimpleNamespace(**params))
        except Exception:  # noqa: BLE001 - constructor fallback is fail-soft
            module = self.module_cls()
        result = module.safe_run(**params)
        if result.ok:
            return self.ok(
                data=result.data,
                message=result.message,
                artifacts=result.artifacts,
            )
        return self.error(
            result.message or f"module '{self.name}' failed",
            data=result.data,
            artifacts=result.artifacts,
        )


def build_module_tool_registry(
    *,
    names: Iterable[str] | None = None,
    allow_execution: bool = False,
) -> dict[str, ModuleToolAdapter]:
    """Build AgentLoop tools from the module registry.

    The default excludes recursive dialogue modules.  Names can be supplied by
    a supervisor to narrow the registry further; unknown names are ignored so
    optional modules do not break startup.
    """
    from ai.modules import MODULE_REGISTRY

    selected = (
        list(names)
        if names is not None
        else [name for name in sorted(MODULE_REGISTRY) if name not in _DEFAULT_EXCLUDED_MODULES]
    )
    result: dict[str, ModuleToolAdapter] = {}
    for name in selected:
        if name in _DEFAULT_EXCLUDED_MODULES:
            continue
        module_cls = MODULE_REGISTRY.get(name)
        if module_cls is None:
            continue
        result[name] = ModuleToolAdapter(
            module_cls,
            allow_execution=allow_execution,
        )
    return result


def available_module_tools() -> dict[str, dict[str, Any]]:
    """Return module tool metadata without instantiating modules."""
    from ai.modules import MODULE_REGISTRY
    from ai.capability.registry import module_input_schema

    result: dict[str, dict[str, Any]] = {}
    for name, module_cls in sorted(MODULE_REGISTRY.items()):
        if name in _DEFAULT_EXCLUDED_MODULES:
            continue
        result[name] = {
            "name": name,
            "description": str(getattr(module_cls, "description", "") or ""),
            "parameters_schema": module_input_schema(module_cls),
            "requires_approval": bool(getattr(module_cls, "requires_approval", False)),
            "approval_mode": str(getattr(module_cls, "approval_mode", "none")),
            "expose_to_pi": bool(getattr(module_cls, "expose_to_pi", True)),
        }
    return result


__all__ = [
    "ModuleToolAdapter",
    "available_module_tools",
    "build_module_tool_registry",
]
