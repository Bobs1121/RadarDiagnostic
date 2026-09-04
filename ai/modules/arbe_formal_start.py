# -*- coding: utf-8 -*-
"""Approval-gated formal arbe ``bash start`` capability."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ai.providers.cr60_harness import Cr60HarnessProvider

from .base import BaseModule, ModuleResult


class ArbeFormalStartModule(BaseModule):
    """Start formal arbe only through the owned provider session boundary."""

    name = "arbe-formal-start"
    description = "Start formal arbe bash start with an owned auditable session"
    tags = ["arbe", "start", "formal", "ros", "provider", "approval-gated", "atomic"]
    requires_approval = True
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "harness_root": {"type": "string"},
            "profile": {"type": "string"},
            "ros_master_uri": {"type": "string"},
            "start_path": {"type": "string"},
            "ready_timeout_sec": {"type": "number"},
            "clean_remote_log": {"type": "boolean"},
            "execute": {"type": "boolean"},
            "approved": {"type": "boolean"},
            "python_executable": {"type": "string"},
            "timeout_sec": {"type": "number"},
            "session_output": {"type": "string"},
            "output": {"type": "string"},
        },
        "required": ["harness_root", "profile"],
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
        ros_master_uri: str = "http://127.0.0.1:11311",
        start_path: str = "",
        ready_timeout_sec: float = 45.0,
        clean_remote_log: bool = False,
        execute: bool = False,
        approved: bool = False,
        python_executable: str = "",
        timeout_sec: float = 3600.0,
        session_output: str = "",
        output: str = "",
        **_: Any,
    ) -> ModuleResult:
        try:
            provider = Cr60HarnessProvider(
                harness_root=harness_root,
                python_executable=python_executable,
                timeout_sec=timeout_sec,
            )
            payload = provider.run_formal_start(
                profile=profile,
                ros_master_uri=ros_master_uri,
                start_path=start_path,
                ready_timeout_sec=float(ready_timeout_sec),
                clean_remote_log=bool(clean_remote_log),
                session_output=session_output,
                execute=bool(execute and approved),
            )
            if execute and not approved and payload.get("status") == "planned":
                payload["status"] = "approval_required"
                payload["execute_requested"] = True
                payload["diagnostics"] = ["formal arbe start requires explicit approved=true"]
            if output and payload.get("status") not in {"blocked", "failed"}:
                path = Path(output).expanduser().resolve()
                path.parent.mkdir(parents=True, exist_ok=True)
                payload["artifact_path"] = str(path)
                path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                output_artifacts = [str(path)]
            else:
                output_artifacts = []
        except (OSError, ValueError, TypeError, KeyError) as exc:
            return ModuleResult.fail(
                f"formal arbe start failed: {type(exc).__name__}: {exc}",
                module=self.name,
            )
        status = str(payload.get("status", "failed"))
        bounded = payload
        if output and status not in {"blocked", "failed"}:
            bounded = {
                key: payload.get(key)
                for key in (
                    "schema_version", "mode", "harness_root", "command", "command_display",
                    "execute_requested", "status", "artifacts", "session_output", "start_status",
                    "ownership", "session_id", "artifact_path", "diagnostics",
                )
                if key in payload
            }
        return ModuleResult(
            ok=status in {"planned", "approval_required", "completed", "already_running", "partial"},
            message=f"arbe-formal-start:{status}",
            module=self.name,
            data=bounded,
            artifacts=output_artifacts + list(payload.get("artifacts", []) or []),
        )

    @classmethod
    def register_cli(cls, subparsers: Any) -> Any:
        parser = super().register_cli(subparsers)
        parser.add_argument("--harness-root", required=True)
        parser.add_argument("--profile", required=True)
        parser.add_argument("--ros-master-uri", default="http://127.0.0.1:11311")
        parser.add_argument("--start-path", default="")
        parser.add_argument("--ready-timeout-sec", type=float, default=45.0)
        parser.add_argument("--clean-remote-log", action="store_true")
        parser.add_argument("--execute", action="store_true")
        parser.add_argument("--approved", action="store_true")
        parser.add_argument("--python-executable", default="")
        parser.add_argument("--timeout-sec", type=float, default=3600.0)
        parser.add_argument("--session-output", default="")
        parser.add_argument("--output", default="")
        return parser

    @classmethod
    def from_cli_args(cls, args: Any) -> "ArbeFormalStartModule":
        return cls()


__all__ = ["ArbeFormalStartModule"]
