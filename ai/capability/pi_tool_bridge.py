# -*- coding: utf-8 -*-
"""Pi's single JSON boundary for radarAnalyze capabilities.

The generated TypeScript extension is intentionally thin.  It calls this
module with ``--name`` and ``--params``; this bridge then dispatches to either
the existing ``BaseTool`` registry or a registered leaf ``BaseModule`` adapter.
This keeps Pi's tool protocol, approval gate, and JSON envelope in one place.

The bridge never grants side-effect permission by default.  A future
supervisor may call :func:`invoke_capability` with ``allow_execution=True``
after a user approval artifact has been created; the Pi extension itself never
passes that flag.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from typing import Any

from ai.tools import TOOL_REGISTRY
from ai.capability.module_bridge import (
    _DEFAULT_EXCLUDED_MODULES,
    available_module_tools,
    build_module_tool_registry,
)
from ai.capability.tool_bridge import available_tools, invoke_tool

log = logging.getLogger(__name__)


def available_capabilities() -> dict[str, dict[str, Any]]:
    """Return the Pi-visible capability catalog without instantiation."""
    result: dict[str, dict[str, Any]] = {}
    for name, item in available_module_tools().items():
        if item.get("expose_to_pi", True):
            result[name] = {**item, "kind": "module", "expose_to_pi": True}
    for name, item in available_tools().items():
        cls = TOOL_REGISTRY.get(name)
        if cls is not None and not bool(getattr(cls, "expose_to_pi", True)):
            continue
        if name not in result:
            result[name] = {**item, "kind": "tool", "expose_to_pi": True}
    return dict(sorted(result.items()))


def _error(message: str, *, data: Any = None) -> dict[str, Any]:
    return {
        "status": "error",
        "message": str(message),
        "data": data if isinstance(data, (dict, list)) else ({} if data is None else {"value": data}),
        "artifacts": [],
    }


def invoke_capability(
    name: str,
    params: dict[str, Any] | None = None,
    *,
    allow_execution: bool = False,
) -> dict[str, Any]:
    """Dispatch one Pi capability through the canonical Python boundary."""
    capability_name = str(name or "").strip()
    if not capability_name:
        return _error("capability name is required")
    if capability_name in _DEFAULT_EXCLUDED_MODULES:
        return _error(f"capability '{capability_name}' is an orchestration root, not a Pi leaf tool")

    module_registry = build_module_tool_registry(
        names=[capability_name], allow_execution=allow_execution
    )
    module_tool = module_registry.get(capability_name)
    if module_tool is not None:
        return module_tool.safe_execute(params or {})
    if capability_name in TOOL_REGISTRY:
        return invoke_tool(capability_name, params or {})

    return _error(
        f"unknown Pi capability '{capability_name}'",
        data={"available": sorted(available_capabilities())},
    )


def _main(argv: list[str] | None = None) -> int:
    # Pi invokes this process from Node/VS Code on Windows as well as from a
    # UTF-8 Linux terminal.  Reconfigure the process boundary before any
    # catalog/result JSON is printed so Chinese diagnostics cannot fail on a
    # cp1252 console after the tool itself has already succeeded.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass
    parser = argparse.ArgumentParser(description="Pi unified capability bridge")
    parser.add_argument("--name", "--tool", dest="name", help="Pi capability name")
    parser.add_argument("--params", default="{}", help="JSON object passed to the capability")
    parser.add_argument("--list", action="store_true", help="print Pi-visible capability catalog")
    parser.add_argument(
        "--allow-execution",
        action="store_true",
        help="internal supervisor-only switch; never used by the generated Pi extension",
    )
    args = parser.parse_args(argv)
    if args.list:
        print(json.dumps(available_capabilities(), ensure_ascii=False, indent=2))
        return 0
    if not args.name:
        print(json.dumps(_error("--name is required"), ensure_ascii=False))
        return 1
    try:
        params = json.loads(args.params) if args.params else {}
    except json.JSONDecodeError as exc:
        print(json.dumps(_error(f"params is not valid JSON: {exc.msg}"), ensure_ascii=False))
        return 1
    if not isinstance(params, dict):
        print(json.dumps(_error("params must decode to a JSON object"), ensure_ascii=False))
        return 1
    result = invoke_capability(args.name, params, allow_execution=args.allow_execution)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if result.get("status") == "ok" else 1


__all__ = ["available_capabilities", "invoke_capability"]


if __name__ == "__main__":
    raise SystemExit(_main())
