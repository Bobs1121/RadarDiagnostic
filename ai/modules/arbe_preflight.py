# -*- coding: utf-8 -*-
"""Standalone Pi capability for read-only arbe preflight.

The module is intentionally thin: deterministic probing lives in
engines.arbe.preflight and this class only turns it into the common
BaseModule/CLI contract.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from engines.arbe.preflight import (
    ArbePreflight,
    CommandRunner,
    LocalShellRunner,
    SshCommandRunner,
)
from .base import BaseModule, ModuleResult


PreflightFactory = Callable[..., ArbePreflight]


class ArbePreflightModule(BaseModule):
    """Read-only environment, target and CAN-output-chain preflight."""

    name = "arbe-preflight"
    description = (
        "Read-only probe of arbe/source/config/binary/GDB/runtime readiness"
    )
    tags = ["arbe", "preflight", "source", "runtime"]
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "server_host": {"type": "string"},
            "server_user": {"type": "string"},
            "server_port": {"type": "integer"},
            "identity_file": {"type": "string"},
            "arbe_root": {"type": "string"},
            "algo_source_root": {"type": "string"},
            "ros_setup": {"type": "string"},
            "ros_master_uri": {"type": "string"},
            "timeout_sec": {"type": "number"},
            "include_process_snapshot": {"type": "boolean"},
            "output": {"type": "string"},
        },
        "required": ["arbe_root"],
        "additionalProperties": False,
    }
    output_schema: dict[str, Any] = {
        "type": "object",
        "required": ["schema_version", "status", "workspace", "runtime", "can_output"],
        "properties": {
            "can_output": {"type": "object", "additionalProperties": True},
            "public_evidence": {"type": "object", "additionalProperties": True},
        },
    }

    def __init__(
        self,
        *,
        preflight_factory: PreflightFactory | None = None,
        runner: CommandRunner | None = None,
        project_root: Path | str | None = None,
    ) -> None:
        self._preflight_factory = preflight_factory or ArbePreflight
        self._runner = runner
        self._project_root = (
            Path(project_root).resolve()
            if project_root
            else Path(__file__).resolve().parents[2]
        )

    def _build_runner(
        self,
        *,
        server_host: str,
        server_user: str,
        server_port: int,
        identity_file: str,
    ) -> CommandRunner:
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
        algo_source_root: str = "",
        ros_setup: str = "/opt/ros/noetic/setup.bash",
        ros_master_uri: str = "",
        timeout_sec: float = 20.0,
        include_process_snapshot: bool = True,
        output: str = "",
        **_: Any,
    ) -> ModuleResult:
        root = str(arbe_root or "").strip()
        if not root:
            return ModuleResult.fail(
                "arbe_root is required; preflight will not guess a workspace",
                module=self.name,
            )
        if server_port < 1 or server_port > 65535:
            return ModuleResult.fail(
                f"server_port out of range: {server_port}",
                module=self.name,
            )

        runner = self._build_runner(
            server_host=str(server_host or ""),
            server_user=str(server_user or ""),
            server_port=int(server_port),
            identity_file=str(identity_file or ""),
        )
        try:
            probe = self._preflight_factory(
                runner=runner,
                server_host=str(server_host or ""),
                server_user=str(server_user or ""),
                arbe_root=root,
                algo_source_root=str(algo_source_root or ""),
                ros_setup=str(ros_setup or ""),
                ros_master_uri=str(ros_master_uri or ""),
                timeout_sec=float(timeout_sec),
                include_process_snapshot=bool(include_process_snapshot),
            )
            payload = probe.run()
        except Exception as exc:  # noqa: BLE001 - module boundary
            return ModuleResult.fail(
                f"arbe preflight failed: {type(exc).__name__}: {exc}",
                module=self.name,
            )

        artifacts: list[str] = []
        if str(output or "").strip():
            output_path = self._resolve_output(output)
            try:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                artifacts.append(str(output_path))
                payload["artifact_path"] = str(output_path)
            except OSError as exc:
                return ModuleResult(
                    ok=False,
                    message=f"preflight output write failed: {type(exc).__name__}: {exc}",
                    module=self.name,
                    data=payload,
                    artifacts=artifacts,
                )

        status = str(payload.get("status", "unknown"))
        return ModuleResult(
            ok=True,
            message=f"arbe-preflight:{status}",
            module=self.name,
            data=payload,
            artifacts=artifacts,
        )

    @classmethod
    def register_cli(cls, subparsers: Any) -> Any:
        parser = super().register_cli(subparsers)
        parser.add_argument(
            "--host",
            dest="server_host",
            default="",
            help="Linux server host/IP. Empty means local POSIX execution.",
        )
        parser.add_argument("--user", dest="server_user", default="", help="SSH user.")
        parser.add_argument("--port", dest="server_port", type=int, default=22)
        parser.add_argument(
            "--identity-file",
            default="",
            help="Optional SSH identity file path.",
        )
        parser.add_argument(
            "--arbe-root",
            required=True,
            help="Confirmed arbe workspace path on the target host.",
        )
        parser.add_argument(
            "--algo-source-root",
            default="",
            help="Optional source submodule path; defaults to <arbe-root>/src/algo_source.",
        )
        parser.add_argument(
            "--ros-master-uri",
            default="",
            help="Optional ROS master URI used for node discovery; empty preserves remote environment.",
        )
        parser.add_argument(
            "--ros-setup",
            default="/opt/ros/noetic/setup.bash",
            help="ROS setup script sourced before node discovery.",
        )
        parser.add_argument("--timeout-sec", type=float, default=20.0)
        parser.add_argument(
            "--no-process-snapshot",
            action="store_true",
            help="Skip ps/rosnode readiness probes.",
        )
        parser.add_argument(
            "--output",
            default="",
            help="Optional local JSON artifact output path.",
        )
        return parser

    @classmethod
    def from_cli_args(cls, args: Any) -> "ArbePreflightModule":
        return cls()


__all__ = ["ArbePreflightModule"]
