# -*- coding: utf-8 -*-
"""Atomic code-analysis capability that emits source-bound GDB instructions."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from engines.code_gdb_plan import build_code_gdb_plan, load_code_index

from .base import BaseModule, ModuleResult


class CodeGdbPlanModule(BaseModule):
    """Resolve a real current-source function and build generic GDB commands."""

    name = "code-gdb-plan"
    description = "Analyze current code index and generate generic source-bound GDB instructions"
    tags = ["code", "gdb", "plan", "atomic"]
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "code_index_path": {"type": "string"},
            "code_index": {"type": "object"},
            "function_name": {"type": "string"},
            "source_file": {"type": "string"},
            "line": {"type": "integer"},
            "condition": {"type": "string"},
            "frame_scope": {"type": "object"},
            "object_scope": {"type": "object"},
            "watch_variables": {"type": "array", "items": {"type": "string"}},
            "auto_continue": {"type": "boolean"},
            "backtrace_depth": {"type": "integer"},
            "source_root": {"type": "string"},
            "output": {"type": "string"},
        },
        "additionalProperties": False,
    }
    output_schema: dict[str, Any] = {
        "type": "object",
        "required": ["schema_version", "status", "resolution", "breakpoints", "gdb_commands"],
    }

    def run(
        self,
        *,
        code_index_path: str = "",
        code_index: Mapping[str, Any] | None = None,
        function_name: str = "",
        source_file: str = "",
        line: int | None = None,
        condition: str = "",
        frame_scope: Mapping[str, Any] | None = None,
        object_scope: Mapping[str, Any] | None = None,
        watch_variables: list[str] | None = None,
        auto_continue: bool = False,
        backtrace_depth: int = 12,
        source_root: str = "",
        output: str = "",
        **_: Any,
    ) -> ModuleResult:
        try:
            if isinstance(frame_scope, str):
                frame_scope = _json_object(frame_scope, "frame_scope")
            if isinstance(object_scope, str):
                object_scope = _json_object(object_scope, "object_scope")
            index = (
                dict(code_index)
                if isinstance(code_index, Mapping)
                else load_code_index(code_index_path)
            )
            if not index:
                return ModuleResult.fail(
                    "code_index_path or code_index is required", module=self.name
                )
            payload = build_code_gdb_plan(
                code_index=index,
                function_name=function_name,
                source_file=source_file,
                line=line,
                condition=condition,
                frame_scope=frame_scope,
                object_scope=object_scope,
                watch_variables=watch_variables,
                auto_continue=auto_continue,
                backtrace_depth=backtrace_depth,
                source_root=source_root,
            )
        except Exception as exc:  # noqa: BLE001 - external source artifact boundary
            return ModuleResult.fail(
                f"code GDB plan failed: {type(exc).__name__}: {exc}",
                module=self.name,
            )
        artifacts: list[str] = []
        if output:
            path = Path(output).expanduser().resolve()
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
                artifacts.append(str(path))
                payload["artifact_path"] = str(path)
            except OSError as exc:
                return ModuleResult(
                    ok=False,
                    message=f"code GDB plan output failed: {type(exc).__name__}: {exc}",
                    module=self.name,
                    data=payload,
                    artifacts=artifacts,
                )
        return ModuleResult(
            ok=payload.get("status") != "blocked",
            message=f"code-gdb-plan:{payload.get('status', 'unknown')}",
            module=self.name,
            data=payload,
            artifacts=artifacts,
        )

    @classmethod
    def register_cli(cls, subparsers: Any) -> Any:
        parser = super().register_cli(subparsers)
        parser.add_argument("--code-index-path", default="")
        parser.add_argument("--function-name", default="")
        parser.add_argument("--source-file", default="")
        parser.add_argument("--line", type=int, default=None)
        parser.add_argument("--condition", default="")
        parser.add_argument("--frame-scope", default="", help="JSON object")
        parser.add_argument("--object-scope", default="", help="JSON object")
        parser.add_argument("--watch-variable", dest="watch_variables", action="append", default=[])
        parser.add_argument("--auto-continue", action="store_true")
        parser.add_argument("--backtrace-depth", type=int, default=12)
        parser.add_argument("--source-root", default="")
        parser.add_argument("--output", default="")
        return parser

    @classmethod
    def from_cli_args(cls, args: Any) -> "CodeGdbPlanModule":
        return cls()


def _json_object(value: str, name: str) -> dict[str, Any] | None:
    if not value.strip():
        return None
    decoded = json.loads(value)
    if not isinstance(decoded, dict):
        raise ValueError(f"{name} JSON must be an object")
    return decoded


__all__ = ["CodeGdbPlanModule"]
