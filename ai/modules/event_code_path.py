# -*- coding: utf-8 -*-
"""Pi-visible event-to-current-source path builder."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from engines.event_code_path import (
    EventCodePathError,
    build_event_code_path,
    load_code_index,
)

from .base import BaseModule, ModuleResult


def _json_object(text: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"expected JSON object: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise ValueError("expected JSON object")
    return value


class EventCodePathModule(BaseModule):
    """Bind one selected data/runtime event to the current code index."""

    name = "event-code-path"
    description = "将事件绑定到当前源码函数、调用链、条件、变量和 GDB 计划"
    tags = ["code", "event", "call-chain", "gdb", "source-bound", "atomic"]
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "event": {"type": "object"},
            "code_index_path": {"type": "string"},
            "context_path": {"type": "string"},
            "source_root": {"type": "string"},
            "max_call_depth": {"type": "integer"},
            "max_breakpoints": {"type": "integer"},
            "output": {"type": "string"},
        },
        "required": ["event"],
        "anyOf": [
            {"required": ["code_index_path"]},
            {"required": ["context_path"]},
        ],
        "additionalProperties": False,
    }
    output_schema: dict[str, Any] = {
        "type": "object",
        "required": ["schema_version", "status", "event", "source_context", "layers"],
    }

    def run(
        self,
        *,
        event: Mapping[str, Any],
        code_index_path: str = "",
        context_path: str = "",
        source_root: str = "",
        max_call_depth: int = 2,
        max_breakpoints: int = 8,
        output: str = "",
        **_: Any,
    ) -> ModuleResult:
        try:
            index = load_code_index(
                code_index_path=code_index_path,
                context_path=context_path,
            )
            payload = build_event_code_path(
                event=event,
                code_index=index,
                source_root=source_root,
                max_call_depth=max_call_depth,
                max_breakpoints=max_breakpoints,
            )
            if output:
                path = Path(output).expanduser().resolve()
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                payload["artifact_path"] = str(path)
                artifacts = [str(path)]
            else:
                artifacts = []
        except (EventCodePathError, OSError, TypeError, ValueError) as exc:
            return ModuleResult.fail(
                f"event-code-path:failed: {exc}",
                module=self.name,
                error_type=type(exc).__name__,
            )
        return ModuleResult(
            ok=True,
            message=f"event-code-path:{payload.get('status', 'unknown')}",
            module=self.name,
            artifacts=artifacts,
            data=payload,
        )

    @classmethod
    def register_cli(cls, subparsers: Any) -> Any:
        parser = super().register_cli(subparsers)
        parser.add_argument("--event", type=_json_object, required=True)
        parser.add_argument("--code-index-path", default="")
        parser.add_argument("--context-path", default="")
        parser.add_argument("--source-root", default="")
        parser.add_argument("--max-call-depth", type=int, default=2)
        parser.add_argument("--max-breakpoints", type=int, default=8)
        parser.add_argument("--output", default="")
        return parser

    @classmethod
    def from_cli_args(cls, args: Any) -> "EventCodePathModule":
        return cls()


__all__ = ["EventCodePathModule"]
