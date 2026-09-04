# -*- coding: utf-8 -*-
"""tool-bridge — 统一工具调用桥（V4 P1）。

把 TOOL_REGISTRY 里的 BaseTool 统一暴露为一个 JSON-in / JSON-out 入口，
供 pi 扩展（registerTool.execute）、ReAct 兜底、或外部脚本调用：

    python -m ai.capability.tool_bridge --tool plot_signal --params '{"signal_name":"veh_spd"}'

契约（与 BaseTool.safe_execute 一致）：返回
    {"status":"ok"|"error", "message", "data", "artifacts"}

实现要点：
- 工具实例化走 AgentToolContext / build_agent_tool_registry（注入 store/
  codegraph/source_root/cache_dir），而非裸 JSON——因为 BaseTool 的
  parameters_schema 只描述 execute 参数，构造需已解析的上下文。
- fail-soft：未知工具/坏参数/执行异常一律返回 error envelope，不 raise。
"""
from __future__ import annotations

import json
import keyword
import logging
from dataclasses import dataclass
from typing import Any

from ai.tools import TOOL_REGISTRY
from ai.tools.base import BaseTool

log = logging.getLogger(__name__)

#: ---------- 工具上下文 --------------------------------------------------
# 通过 build_agent_tool_registry 注入确定性上下文（store/codegraph/...）
# 预构建一次，避免每次调用重建（往后接 pi 时复用同一份工具实例）。

_registry_cache: dict[str, BaseTool] | None = None


def _tool_context(config: dict | None = None):
    """解析完整 agent tool context（复用 agent_tool_registry.resolve）。"""
    from ai.agent_tool_registry import resolve_agent_tool_context, build_agent_tool_registry
    try:
        from config import load_config
        from pathlib import Path
        project_root = Path.cwd()
        cfg = load_config() if config is None else config
        ctx = resolve_agent_tool_context(config=cfg, project_root=project_root)
        return build_agent_tool_registry(ctx)
    except Exception as exc:  # noqa: BLE001
        log.warning("tool-bridge: context resolve failed: %s", exc)
        return {}


def get_tool_registry(force_rebuild: bool = False) -> dict[str, BaseTool]:
    """返回可供调用的工具实例表（懒构建 + 缓存）。"""
    global _registry_cache
    if _registry_cache is None or force_rebuild:
        _registry_cache = _tool_context()
    return _registry_cache


def available_tools() -> dict[str, dict]:
    """返回工具元信息（name → {name, description, parameters_schema}）。

    供 pi 扩展 / 工具目录 / 目录自述使用；不实例化（避免副作用）。
    """
    out: dict[str, dict] = {}
    for name, cls in TOOL_REGISTRY.items():
        out[name] = {
            "name": name,
            "description": getattr(cls, "description", ""),
            "parameters_schema": getattr(cls, "parameters_schema", {}),
        }
    return out


def invoke_tool(tool_name: str, params: dict[str, Any]) -> dict[str, Any]:
    """调用一个工具，返回 BaseTool envelope（不 raise）。"""
    if not tool_name:
        return _err("tool 名不能为空")
    if tool_name not in TOOL_REGISTRY:
        available = ", ".join(sorted(TOOL_REGISTRY)) or "(空)"
        return _err(f"未知工具 '{tool_name}'，可用: {available}")

    try:
        registry = get_tool_registry()
        tool = registry.get(tool_name)
        if tool is None:
            # 未解析出上下文实例：尝试裸构造（仅对无需注入的工具有效）
            cls = TOOL_REGISTRY[tool_name]
            try:
                tool = cls()
            except Exception:
                return _err(f"工具 '{tool_name}' 需要注入上下文，无法独立构造")
        result = tool.safe_execute(params or {})
        return result if isinstance(result, dict) else _err("工具返回非 dict")
    except Exception as exc:  # noqa: BLE001 - fail-soft 边界
        log.exception("tool-bridge invoke '%s' failed", tool_name)
        return _err(f"{type(exc).__name__}: {exc}")


def _err(message: str) -> dict[str, Any]:
    return {
        "status": "error",
        "message": message,
        "data": {},
        "artifacts": [],
    }


#: ---------- CLI 入口 ----------------------------------------------------
# 用法：python -m ai.capability.tool_bridge --tool plot_signal --params '{...}'
def _main(argv: list[str] | None = None) -> int:
    import argparse
    p = argparse.ArgumentParser(description="统一工具调用桥 (tool-bridge)")
    p.add_argument("--tool", required=True, help="工具名")
    p.add_argument("--params", default="{}", help="工具参数 JSON")
    p.add_argument("--list", action="store_true", help="列出可用工具")
    args = p.parse_args(argv)

    if args.list:
        print(json.dumps(invoke_tools_list(), ensure_ascii=False, indent=1))
        return 0
    try:
        params = json.loads(args.params) if args.params else {}
    except json.JSONDecodeError:
        print(json.dumps(_err("params 不是合法 JSON"), ensure_ascii=False))
        return 1
    result = invoke_tool(args.tool, params)
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0 if result.get("status") == "ok" else 1


def invoke_tools_list() -> dict:
    return invoke_tools()


def invoke_tools() -> dict[str, Any]:
    return available_tools()


#: 兼容旧名 —— 供外部用 `invoke_tool` 与 `available_tools` 即可。
__all__ = [
    "invoke_tool",
    "available_tools",
    "get_tool_registry",
    "invoke_tools",
]