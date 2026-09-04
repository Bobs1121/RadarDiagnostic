# -*- coding: utf-8 -*-
"""Pi-facing source condition evidence module."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from engines.condition_trace import ConditionTraceError, build_condition_trace

from .base import BaseModule, ModuleResult


class ConditionTraceModule(BaseModule):
    """Evaluate only explicitly bound current-source conditions."""

    name = "condition-trace"
    description = "按当前源码条件和同帧真实字段生成条件证据"
    tags = ["condition", "evidence", "source-bound", "report", "atomic", "read-only"]
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "conditions": {"type": ["array", "object"]},
            "values": {"type": "object"},
            "parameters": {"type": ["array", "object"]},
            "event_id": {"type": "string"},
            "function": {"type": "string"},
            "frame_id": {},
            "source_root": {"type": "string"},
            "max_conditions": {"type": "integer", "default": 80},
            "output": {"type": "string"},
        },
        "required": ["conditions"],
        "additionalProperties": False,
    }
    output_schema: dict[str, Any] = {
        "type": "object",
        "required": ["schema_version", "status", "conditions", "summary"],
    }

    def run(
        self,
        *,
        conditions: Any,
        values: Mapping[str, Any] | None = None,
        parameters: Any = None,
        event_id: str = "",
        function: str = "",
        frame_id: Any = None,
        source_root: str = "",
        max_conditions: int = 80,
        output: str = "",
        **_: Any,
    ) -> ModuleResult:
        try:
            payload = build_condition_trace(
                conditions=conditions,
                values=values,
                parameters=parameters,
                event_id=event_id,
                function=function,
                frame_id=frame_id,
                source_root=source_root,
                max_conditions=max_conditions,
            )
        except (ConditionTraceError, TypeError, ValueError) as exc:
            return ModuleResult.fail(
                f"condition-trace:failed: {exc}",
                module=self.name,
                error_type=type(exc).__name__,
            )
        artifacts: list[str] = []
        if str(output or "").strip():
            path = Path(output).expanduser().resolve()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            payload["artifact_path"] = str(path)
            artifacts.append(str(path))
        return ModuleResult(
            ok=True,
            message=f"condition-trace:{payload.get('status')}",
            module=self.name,
            artifacts=artifacts,
            data=payload,
        )

    @classmethod
    def register_cli(cls, subparsers: Any) -> Any:
        parser = super().register_cli(subparsers)
        parser.add_argument("--conditions", type=json.loads, required=True)
        parser.add_argument("--values", type=json.loads, default={})
        parser.add_argument("--parameters", type=json.loads, default={})
        parser.add_argument("--event-id", default="")
        parser.add_argument("--function", default="")
        parser.add_argument("--frame-id", default=None)
        parser.add_argument("--source-root", default="")
        parser.add_argument("--max-conditions", type=int, default=80)
        parser.add_argument("--output", default="")
        return parser

    @classmethod
    def from_cli_args(cls, args: Any) -> "ConditionTraceModule":
        return cls()


__all__ = ["ConditionTraceModule"]
