# -*- coding: utf-8 -*-
"""Approval-gated ``catkin_make`` capability for an explicit arbe workspace."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from engines.arbe.build import BuildCommandRunner, LocalShellRunner, run_catkin_make
from engines.arbe.preflight import SshCommandRunner

from .base import BaseModule, ModuleResult


class ArbeBuildModule(BaseModule):
    """Build only; branch/CUDA/config/start are separate capabilities."""

    name = "arbe-build"
    description = "Build an explicit arbe workspace with catkin_make"
    tags = ["arbe", "build", "catkin", "remote", "provider", "approval-gated", "atomic"]
    requires_approval = True
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "arbe_root": {"type": "string"},
            "server_host": {"type": "string"},
            "server_user": {"type": "string"},
            "server_port": {"type": "integer"},
            "identity_file": {"type": "string"},
            "ros_setup": {"type": "string"},
            "catkin_make_args": {"type": "array", "items": {"type": "string"}},
            "execute": {"type": "boolean"},
            "approved": {"type": "boolean"},
            "timeout_sec": {"type": "number"},
            "output": {"type": "string"},
        },
        "required": ["arbe_root"],
        "additionalProperties": False,
    }
    output_schema: dict[str, Any] = {
        "type": "object",
        "required": ["schema_version", "status", "target", "command"],
    }

    def __init__(self, *, runner: BuildCommandRunner | None = None, project_root: str | Path | None = None) -> None:
        self._runner = runner
        self._project_root = Path(project_root).expanduser().resolve() if project_root else Path(__file__).resolve().parents[2]

    def _build_runner(
        self,
        *,
        server_host: str,
        server_user: str,
        server_port: int,
        identity_file: str,
    ) -> BuildCommandRunner:
        if self._runner is not None:
            return self._runner
        if server_host.strip():
            return SshCommandRunner(
                host=server_host,
                username=server_user,
                port=server_port,
                identity_file=identity_file,
            )
        return LocalShellRunner()

    def _resolve_output(self, output: str) -> Path:
        path = Path(output).expanduser()
        if not path.is_absolute():
            path = self._project_root / path
        return path.resolve()

    def run(
        self,
        *,
        arbe_root: str,
        server_host: str = "",
        server_user: str = "",
        server_port: int = 22,
        identity_file: str = "",
        ros_setup: str = "/opt/ros/noetic/setup.bash",
        catkin_make_args: list[str] | None = None,
        execute: bool = False,
        approved: bool = False,
        timeout_sec: float = 3600.0,
        output: str = "",
        **_: Any,
    ) -> ModuleResult:
        if not str(arbe_root or "").strip():
            return ModuleResult.fail("arbe_root is required; build will not guess a workspace", module=self.name)
        if server_port < 1 or server_port > 65535:
            return ModuleResult.fail(f"server_port out of range: {server_port}", module=self.name)
        try:
            runner = self._build_runner(
                server_host=str(server_host or ""),
                server_user=str(server_user or ""),
                server_port=int(server_port),
                identity_file=str(identity_file or ""),
            )
            payload = run_catkin_make(
                runner=runner,
                arbe_root=str(arbe_root),
                server_host=str(server_host or ""),
                server_user=str(server_user or ""),
                server_port=int(server_port),
                ros_setup=str(ros_setup or ""),
                catkin_make_args=list(catkin_make_args or []),
                execute=bool(execute and approved),
                timeout_sec=float(timeout_sec),
            )
            if execute and not approved and payload.get("status") == "planned":
                payload["status"] = "approval_required"
                payload["execute_requested"] = True
                payload["diagnostics"] = ["catkin_make requires explicit approved=true"]
            artifacts: list[str] = []
            if output:
                path = self._resolve_output(output)
                path.parent.mkdir(parents=True, exist_ok=True)
                payload["artifact_path"] = str(path)
                path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                artifacts.append(str(path))
        except (OSError, ValueError, TypeError) as exc:
            return ModuleResult.fail(f"arbe build failed: {type(exc).__name__}: {exc}", module=self.name)
        status = str(payload.get("status", "failed"))
        bounded = payload
        if output and status not in {"failed", "timeout"}:
            bounded = {
                key: payload.get(key)
                for key in (
                    "schema_version", "status", "target", "command", "catkin_make_args",
                    "execute_requested", "duration_sec", "diagnostics", "artifact_path",
                )
                if key in payload
            }
        return ModuleResult(
            ok=status in {"planned", "approval_required", "completed"},
            message=f"arbe-build:{status}",
            module=self.name,
            data=bounded,
            artifacts=artifacts,
        )

    @classmethod
    def register_cli(cls, subparsers: Any) -> Any:
        parser = super().register_cli(subparsers)
        parser.add_argument("--arbe-root", required=True)
        parser.add_argument("--host", dest="server_host", default="")
        parser.add_argument("--user", dest="server_user", default="")
        parser.add_argument("--port", dest="server_port", type=int, default=22)
        parser.add_argument("--identity-file", default="")
        parser.add_argument("--ros-setup", default="/opt/ros/noetic/setup.bash")
        parser.add_argument("--catkin-make-arg", dest="catkin_make_args", action="append", default=[])
        parser.add_argument("--execute", action="store_true")
        parser.add_argument("--approved", action="store_true")
        parser.add_argument("--timeout-sec", type=float, default=3600.0)
        parser.add_argument("--output", default="")
        return parser

    @classmethod
    def from_cli_args(cls, args: Any) -> "ArbeBuildModule":
        return cls()


__all__ = ["ArbeBuildModule"]
