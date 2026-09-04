# -*- coding: utf-8 -*-
"""Atomic, approval-gated headless GDB service capability."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from engines.gdb_service import HeadlessGdbService

from .base import BaseModule, ModuleResult


class GdbServiceModule(BaseModule):
    """Execute generic GDB commands supplied by an upstream code-analysis tool."""

    name = "gdb-service"
    description = "Generic headless GDB attach/inspect service; no feature-specific breakpoints"
    tags = ["gdb", "runtime", "atomic", "approval-gated"]
    requires_approval = True
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "target": {"type": "object"},
            "commands": {"type": "array", "items": {"type": "string"}},
            "execute": {"type": "boolean"},
            "approved": {"type": "boolean"},
            "timeout_sec": {"type": "number"},
            "output": {"type": "string"},
        },
        "required": ["target", "commands"],
        "additionalProperties": False,
    }
    output_schema: dict[str, Any] = {
        "type": "object",
        "required": ["schema_version", "status", "target", "commands"],
    }

    def run(
        self,
        *,
        target: Mapping[str, Any],
        commands: list[str],
        execute: bool = False,
        approved: bool = False,
        timeout_sec: float = 120.0,
        output: str = "",
        **_: Any,
    ) -> ModuleResult:
        if not isinstance(target, Mapping):
            return ModuleResult.fail("target must be an object", module=self.name)
        if not isinstance(commands, list):
            return ModuleResult.fail("commands must be a list", module=self.name)
        service = HeadlessGdbService(timeout_sec=timeout_sec)
        payload = service.run(
            target=target,
            commands=commands,
            execute=execute,
            approved=approved,
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
                    message=f"GDB service output failed: {type(exc).__name__}: {exc}",
                    module=self.name,
                    data=payload,
                    artifacts=artifacts,
                )
        status = str(payload.get("status", "unknown"))
        ok = status in {"planned", "succeeded", "approval_required"}
        return ModuleResult(
            ok=ok,
            message=f"gdb-service:{status}",
            module=self.name,
            data=payload,
            artifacts=artifacts,
        )

    @classmethod
    def register_cli(cls, subparsers: Any) -> Any:
        parser = super().register_cli(subparsers)
        parser.add_argument("--target", required=True, help="JSON target object")
        parser.add_argument("--command", dest="commands", action="append", default=[], required=True)
        parser.add_argument("--execute", action="store_true")
        parser.add_argument("--approved", action="store_true")
        parser.add_argument("--timeout-sec", type=float, default=120.0)
        parser.add_argument("--output", default="")
        return parser

    @classmethod
    def from_cli_args(cls, args: Any) -> "GdbServiceModule":
        return cls()


__all__ = ["GdbServiceModule"]
