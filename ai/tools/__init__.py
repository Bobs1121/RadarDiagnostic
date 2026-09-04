# -*- coding: utf-8 -*-
"""Agent-callable deterministic tools for the V3 tool loop.

Imports are guarded so an optional dependency in one tool group cannot break
the base contract or other tool groups.
"""

from .base import BaseTool, build_tool_result, serialize_jsonable

__all__ = [
    "BaseTool",
    "TOOL_REGISTRY",
    "build_tool_result",
    "serialize_jsonable",
]

#: Registry of Agent-callable deterministic tools, keyed by their ``name``.
TOOL_REGISTRY: dict[str, type[BaseTool]] = {}

try:
    from .data_tools import DetectTimePatternTool, PlotSignalTool, QueryCanDataTool

    for _tool_cls in (QueryCanDataTool, DetectTimePatternTool, PlotSignalTool):
        TOOL_REGISTRY[_tool_cls.name] = _tool_cls

    __all__.extend([
        "DetectTimePatternTool",
        "PlotSignalTool",
        "QueryCanDataTool",
    ])
except Exception:  # noqa: BLE001 - optional tool group
    pass

try:
    from .code_tools import (
        ExtractASTDependencyTool,
        FindCodeDefinitionTool,
        TraceRequirementTool,
    )

    for _tool_cls in (
        FindCodeDefinitionTool,
        ExtractASTDependencyTool,
        TraceRequirementTool,
    ):
        TOOL_REGISTRY[_tool_cls.name] = _tool_cls

    __all__.extend([
        "ExtractASTDependencyTool",
        "FindCodeDefinitionTool",
        "TraceRequirementTool",
    ])
except Exception:  # noqa: BLE001 - optional tool group
    pass

try:
    from .ask_user import AskHumanTool

    TOOL_REGISTRY[AskHumanTool.name] = AskHumanTool

    __all__.append("AskHumanTool")
except Exception:  # noqa: BLE001 - optional tool group
    pass
