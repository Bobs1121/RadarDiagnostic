# -*- coding: utf-8 -*-
"""Approval-gated cleanup for a tool-owned formal arbe start session."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ai.providers.cr60_harness import Cr60HarnessProvider

from .base import BaseModule, ModuleResult


class ArbeFormalStopModule(BaseModule):
    """Stop only the process group proven to belong to formal-start."""

    name = "arbe-formal-stop"
    description = "Stop only a tool-owned formal arbe start session"
    tags = ["arbe", "stop", "formal", "ros", "provider", "approval-gated", "atomic"]
    requires_approval = True
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "harness_root": {"type": "string"},
            "profile": {"type": "string"},
            "session_path": {"type": "string"},
            "execute": {"type": "boolean"},
            "approved": {"type": "boolean"},
            "python_executable": {"type": "string"},
            "timeout_sec": {"type": "number"},
            "output": {"type": "string"},
        },
        "required": ["harness_root", "profile", "session_path"],
        "additionalProperties": False,
    }
    output_schema: dict[str, Any] = {
        "type": "object",
        "required": ["schema_version", "status", "mode", "command"],
    }

    def run(
        self,
        *,
        harness_root: str,
        profile: str,
        session_path: str,
        execute: bool = False,
        approved: bool = False,
        python_executable: str = "",
        timeout_sec: float = 120.0,
        output: str = "",
        **_: Any,
    ) -> ModuleResult:
        try:
            provider = Cr60HarnessProvider(
                harness_root=harness_root,
                python_executable=python_executable,
                timeout_sec=timeout_sec,
            )
            payload = provider.run_formal_stop(
                profile=profile,
                session_path=session_path,
                output=output,
                execute=bool(execute and approved),
            )
            if execute and not approved and payload.get("status") == "planned":
                payload["status"] = "approval_required"
                payload["execute_requested"] = True
                payload["diagnostics"] = ["formal arbe stop requires explicit approved=true"]
            if output and payload.get("status") not in {"blocked", "failed"} and not Path(output).expanduser().resolve().is_file():
                path = Path(output).expanduser().resolve()
                path.parent.mkdir(parents=True, exist_ok=True)
                payload["artifact_path"] = str(path)
                path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                output_artifacts = [str(path)]
            else:
                output_artifacts = [str(Path(output).expanduser().resolve())] if output and Path(output).expanduser().resolve().is_file() else []
        except (OSError, ValueError, TypeError, KeyError) as exc:
            return ModuleResult.fail(
                f"formal arbe stop failed: {type(exc).__name__}: {exc}",
                module=self.name,
            )
        status = str(payload.get("status", "failed"))
        bounded = payload
        if output and status not in {"blocked", "failed"}:
            bounded = {
                key: payload.get(key)
                for key in (
                    "schema_version", "mode", "harness_root", "command", "command_display",
                    "execute_requested", "status", "artifacts", "stop_status", "artifact_path",
                    "diagnostics",
                )
                if key in payload
            }
        return ModuleResult(
            ok=status in {"planned", "approval_required", "completed", "stopped"},
            message=f"arbe-formal-stop:{status}",
            module=self.name,
            data=bounded,
            artifacts=output_artifacts + list(payload.get("artifacts", []) or []),
        )

    @classmethod
    def register_cli(cls, subparsers: Any) -> Any:
        parser = super().register_cli(subparsers)
        parser.add_argument("--harness-root", required=True)
        parser.add_argument("--profile", required=True)
        parser.add_argument("--session-path", required=True)
        parser.add_argument("--execute", action="store_true")
        parser.add_argument("--approved", action="store_true")
        parser.add_argument("--python-executable", default="")
        parser.add_argument("--timeout-sec", type=float, default=120.0)
        parser.add_argument("--output", default="")
        return parser

    @classmethod
    def from_cli_args(cls, args: Any) -> "ArbeFormalStopModule":
        return cls()


__all__ = ["ArbeFormalStopModule"]
