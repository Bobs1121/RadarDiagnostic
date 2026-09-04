# -*- coding: utf-8 -*-
"""CapabilityRegistry — V4 P0 能力清单（单一来源）。

扫描两个注册表生成统一的能力清单，供 pi 工具目录 / tool-bridge / 扩展生成器：
    * MODULE_REGISTRY（ai/modules/）— BaseModule 能力（独立 CLI / safe_run）
    * TOOL_REGISTRY（ai/tools/）    — BaseTool 确定性工具（parameters_schema）

与 D-PI-6 对齐：**不另起 CapabilityModule**，能力 = 现有三件套。本模块只做
“收集元信息 → 导出清单”，不改变两端契约。

用法::

    from ai.capability.registry import capability_catalog
    catalog  # [ {name, kind, description, tags, parameters, output_schema}, ... ]
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
import inspect
from typing import Any


#: BaseModule 默认 tags（可按模块名补充）
_MODULE_TAGS: dict[str, list[str]] = {
    "pi": ["dialogue", "orchestrate"],
    "pi-context": ["pi", "orchestration", "context", "provenance", "atomic"],
    "signal-extract": ["data", "extract"],
    "sim-verify": ["sim", "verify"],
    "arbe-preflight": ["arbe", "preflight", "runtime"],
    "cr60-intake": ["cr60", "intake", "materials", "provenance"],
    "cr60-precheck": ["cr60", "sprint1", "bag", "report", "harness"],
    "public-topic-plan": ["arbe", "ros", "public-evidence", "atomic"],
    "public-evidence-audit": ["arbe", "ros", "public-evidence", "audit", "atomic"],
    "code-gdb-plan": ["code", "gdb", "plan", "atomic"],
    "gdb-service": ["gdb", "runtime", "atomic", "approval-gated"],
    "ros-topic-inventory": ["ros", "arbe", "public-evidence", "atomic", "read-only"],
    "code-learn": ["code", "learn"],
    "code-analyze": ["code", "analyze"],
    "code-query": ["code", "query"],
    "req-analyze": ["req", "analyze"],
    "req-review": ["req", "review"],
    "diag": ["diag"],
}


@dataclass
class Capability:
    """一项能力的声明式元信息。"""

    name: str
    kind: str                      # "module" 或 "tool"
    description: str = ""
    tags: list[str] = field(default_factory=list)
    parameters: dict = field(default_factory=dict)  # JSON Schema（module/tool）
    output_schema: dict = field(default_factory=dict)  # module result data schema
    requires_approval: bool = False
    approval_mode: str = "none"
    expose_to_pi: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _json_type_for_annotation(annotation: Any) -> str | None:
    """Map common Python annotations to a conservative JSON Schema type."""
    if annotation in (inspect.Parameter.empty, Any, None):
        return None
    text = str(annotation).lower()
    if "bool" in text:
        return "boolean"
    if "float" in text or "number" in text:
        return "number"
    if "int" in text:
        return "integer"
    if "list" in text or "sequence" in text or "tuple" in text or "set" in text:
        return "array"
    if "mapping" in text or "dict" in text:
        return "object"
    if "path" in text or "str" in text or "string" in text:
        return "string"
    # Custom dataclasses/requirement sets are passed as structured JSON when
    # possible; unknown annotations remain unconstrained rather than rejected.
    if "object" in text:
        return "object"
    return None


def _schema_from_run_signature(cls) -> dict[str, Any]:
    """Infer a conservative input schema for legacy modules without one."""
    try:
        signature = inspect.signature(cls.run)
    except (TypeError, ValueError):
        return {"type": "object", "properties": {}, "additionalProperties": True}

    properties: dict[str, dict[str, Any]] = {}
    required: list[str] = []
    accepts_kwargs = False
    for name, parameter in signature.parameters.items():
        if name == "self":
            continue
        if parameter.kind == inspect.Parameter.VAR_KEYWORD:
            accepts_kwargs = True
            continue
        if parameter.kind in {inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.POSITIONAL_ONLY}:
            continue
        if name in {"on_status", "on_event", "router", "config"}:
            # Callbacks and service objects are not JSON tool inputs.
            continue
        prop: dict[str, Any] = {}
        json_type = _json_type_for_annotation(parameter.annotation)
        if json_type:
            prop["type"] = json_type
        if parameter.default is not inspect.Parameter.empty and parameter.default is not None:
            if isinstance(parameter.default, (str, int, float, bool, list, dict)):
                prop["default"] = parameter.default
        if name == "mode" and isinstance(getattr(cls, "MODES", None), (list, tuple, set)):
            prop["enum"] = list(getattr(cls, "MODES"))
        properties[name] = prop
        if parameter.default is inspect.Parameter.empty:
            required.append(name)

    return {
        "type": "object",
        "properties": properties,
        **({"required": required} if required else {}),
        "additionalProperties": accepts_kwargs,
    }


def _schema_from_cli(cls) -> dict[str, Any]:
    """Infer JSON parameters from a module's argparse declaration.

    Legacy modules often put file/context inputs in ``from_cli_args`` and keep
    ``run(**kwargs)`` intentionally small.  Reading the parser declaration is
    safer than publishing an empty Pi schema, while still remaining a
    read-only operation (no arguments are parsed and no module is executed).
    """
    try:
        import argparse

        root = argparse.ArgumentParser(add_help=False)
        subparsers = root.add_subparsers(dest="_module_name")
        parser = cls.register_cli(subparsers)
    except Exception:  # noqa: BLE001 - legacy CLI declarations are optional
        return {"type": "object", "properties": {}, "additionalProperties": True}

    properties: dict[str, dict[str, Any]] = {}
    required: list[str] = []
    for action in getattr(parser, "_actions", []):
        option_strings = list(getattr(action, "option_strings", []) or [])
        name = str(getattr(action, "dest", "") or "")
        if not option_strings or not name or name in {"help", "_module_cls"}:
            continue
        prop: dict[str, Any] = {}
        action_name = action.__class__.__name__
        if action_name in {"_StoreTrueAction", "_StoreFalseAction"}:
            prop["type"] = "boolean"
        else:
            item_type = _json_type_for_annotation(getattr(action, "type", None)) or "string"
            nargs = getattr(action, "nargs", None)
            is_array = action_name == "_AppendAction" or nargs in {"*", "+"} or isinstance(nargs, int) and nargs > 1
            if is_array:
                prop["type"] = "array"
                prop["items"] = {"type": item_type}
            else:
                prop["type"] = item_type
        choices = getattr(action, "choices", None)
        if choices is not None:
            try:
                prop["enum"] = list(choices)
            except TypeError:
                pass
        default = getattr(action, "default", argparse.SUPPRESS)
        if default not in (argparse.SUPPRESS, None) and isinstance(default, (str, int, float, bool, list, dict)):
            prop["default"] = default
        properties[name] = prop
        if bool(getattr(action, "required", False)):
            required.append(name)

    return {
        "type": "object",
        "properties": properties,
        **({"required": required} if required else {}),
        "additionalProperties": True,
    }


def module_input_schema(cls) -> dict[str, Any]:
    """Return declared schema, or a signature-derived legacy fallback."""
    declared = getattr(cls, "input_schema", None)
    if isinstance(declared, dict) and declared.get("properties") is not None:
        return dict(declared)
    signature_schema = _schema_from_run_signature(cls)
    cli_schema = _schema_from_cli(cls)
    properties = dict(signature_schema.get("properties", {}))
    for name, prop in cli_schema.get("properties", {}).items():
        properties.setdefault(name, prop)
    required = list(signature_schema.get("required", []))
    for name in cli_schema.get("required", []):
        if name not in required:
            required.append(name)
    result: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": bool(
            signature_schema.get("additionalProperties", True)
            or cli_schema.get("additionalProperties", True)
        ),
    }
    if required:
        result["required"] = required
    return result

def _module_capability(name: str, cls) -> Capability | None:
    description = str(getattr(cls, "description", "") or "")
    declared_tags = getattr(cls, "tags", None)
    tags = list(declared_tags or _MODULE_TAGS.get(name, []))
    try:
        parameters = module_input_schema(cls)
    except (TypeError, ValueError):
        parameters = {}
    try:
        output_schema = dict(getattr(cls, "output_schema", {}) or {})
    except (TypeError, ValueError):
        output_schema = {}
    requires_approval = bool(getattr(cls, "requires_approval", False))
    approval_mode = (
        str(getattr(cls, "approval_mode", "explicit_execute"))
        if requires_approval else "none"
    )
    expose_to_pi = name not in {"pi", "agent-repl", "agent-loop"} and bool(
        getattr(cls, "expose_to_pi", True)
    )
    return Capability(
        name=name,
        kind="module",
        description=description,
        tags=tags,
        parameters=parameters,
        output_schema=output_schema,
        requires_approval=requires_approval,
        approval_mode=approval_mode,
        expose_to_pi=expose_to_pi,
    )


def _tool_capability(name: str, tool_cls) -> Capability | None:
    try:
        params = getattr(tool_cls, "parameters_schema", {}) or {}
    except Exception:  # noqa: BLE001
        params = {}
    return Capability(
        name=name,
        kind="tool",
        description=str(getattr(tool_cls, "description", "") or ""),
        tags=["tool"],
        parameters=params,
        requires_approval=bool(getattr(tool_cls, "requires_approval", False)),
        approval_mode=str(getattr(tool_cls, "approval_mode", "none")),
        expose_to_pi=bool(getattr(tool_cls, "expose_to_pi", True)),
    )


def list_capabilities(
    include_modules: bool = True,
    include_tools: bool = True,
) -> list[Capability]:
    """构建能力清单（模块 + 工具），确定性排序。"""
    out: list[Capability] = []

    if include_modules:
        try:
            from ai.modules import MODULE_REGISTRY
        except Exception:  # noqa: BLE001
            MODULE_REGISTRY = {}
        for name in sorted(MODULE_REGISTRY):
            cap = _module_capability(name, MODULE_REGISTRY[name])
            if cap is not None:
                out.append(cap)

    if include_tools:
        try:
            from ai.tools import TOOL_REGISTRY
        except Exception:  # noqa: BLE001
            TOOL_REGISTRY = {}
        for name in sorted(TOOL_REGISTRY):
            cap = _tool_capability(name, TOOL_REGISTRY[name])
            if cap is not None:
                out.append(cap)

    return out


def capability_catalog() -> list[dict]:
    """JSON 友好能力清单（供打印 / 扩展生成 / 目录自述）。"""
    return [c.to_dict() for c in list_capabilities()]


def catalog_json(indent: int = 2) -> str:
    """把能力清单序列化为 JSON 字符串。"""
    return json.dumps(capability_catalog(), ensure_ascii=False, indent=indent)


__all__ = [
    "Capability",
    "module_input_schema",
    "list_capabilities",
    "capability_catalog",
    "catalog_json",
]
