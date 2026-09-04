# -*- coding: utf-8 -*-
"""Pi capability for approval-gated invocation of the upstream data transfer skill."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from engines.arbe.preflight import LocalShellRunner, SshCommandRunner
from engines.arbe.transfer import DataTransferRunner, run_transfer

from .base import BaseModule, ModuleResult


class CR60DataTransferModule(BaseModule):
    """Invoke an explicitly configured upstream transfer script on Linux."""

    name = "cr60-data-transfer"
    description = "Run the configured bosch-data-transfert script after explicit approval"
    tags = ["cr60", "data", "transfer", "remote", "approval-gated", "atomic"]
    requires_approval = True
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "server_host": {"type": "string"},
            "server_user": {"type": "string"},
            "server_port": {"type": "integer"},
            "identity_file": {"type": "string"},
            "script_path": {"type": "string"},
            "input_path": {"type": "string"},
            "destination_root": {"type": "string"},
            "source_type": {"type": "string", "enum": ["xlsx", "list"]},
            "source_prefix": {"type": "string"},
            "python_executable": {"type": "string"},
            "execute": {"type": "boolean"},
            "approved": {"type": "boolean"},
            "timeout_sec": {"type": "number"},
            "output": {"type": "string"},
        },
        "required": ["script_path", "input_path", "destination_root"],
        "additionalProperties": False,
    }
    output_schema: dict[str, Any] = {
        "type": "object",
        "required": ["schema_version", "status", "target", "command", "side_effects"],
    }

    def __init__(self, *, runner: DataTransferRunner | None = None, project_root: Path | str | None = None) -> None:
        self._runner = runner
        self._project_root = (
            Path(project_root).expanduser().resolve()
            if project_root
            else Path(__file__).resolve().parents[2]
        )

    def _runner_for(self, host: str, user: str, port: int, identity_file: str) -> DataTransferRunner:
        if self._runner is not None:
            return self._runner
        if str(host or "").strip():
            return SshCommandRunner(host=str(host), username=str(user), port=int(port), identity_file=str(identity_file or ""))
        return LocalShellRunner()

    def _write(self, payload: dict[str, Any], output: str) -> list[str]:
        if not str(output or "").strip():
            return []
        path = Path(output).expanduser()
        if not path.is_absolute():
            path = self._project_root / path
        path = path.resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        payload["artifact_path"] = str(path)
        return [str(path)]

    def run(
        self,
        *,
        server_host: str = "",
        server_user: str = "",
        server_port: int = 0,
        identity_file: str = "",
        script_path: str,
        input_path: str,
        destination_root: str,
        source_type: str = "list",
        source_prefix: str = "",
        python_executable: str = "python3",
        execute: bool = False,
        approved: bool = False,
        timeout_sec: float = 1800.0,
        output: str = "",
        **_: Any,
    ) -> ModuleResult:
        if int(server_port) < 0 or int(server_port) > 65535:
            return ModuleResult.fail(f"server_port out of range: {server_port}", module=self.name)
        try:
            effective_port = int(server_port or 22)
            runner = self._runner_for(server_host, server_user, effective_port, identity_file)
            payload = run_transfer(
                runner=runner,
                server_host=server_host,
                server_user=server_user,
                server_port=effective_port,
                script_path=script_path,
                input_path=input_path,
                destination_root=destination_root,
                source_type=source_type,
                source_prefix=source_prefix,
                python_executable=python_executable,
                execute=bool(execute),
                approved=bool(approved),
                timeout_sec=float(timeout_sec),
            )
            artifacts = self._write(payload, output)
        except (OSError, TypeError, ValueError) as exc:
            return ModuleResult.fail(
                f"CR60 data transfer failed: {type(exc).__name__}: {exc}",
                module=self.name,
            )
        status = str(payload.get("status", "failed"))
        return ModuleResult(
            ok=status in {"planned", "approval_required", "completed"},
            message=f"cr60-data-transfer:{status}",
            module=self.name,
            data=payload,
            artifacts=artifacts,
        )

    @classmethod
    def register_cli(cls, subparsers: Any) -> Any:
        parser = super().register_cli(subparsers)
        parser.add_argument("--host", dest="server_host", default="")
        parser.add_argument("--user", dest="server_user", default="")
        parser.add_argument("--port", dest="server_port", type=int, default=0)
        parser.add_argument("--identity-file", default="")
        parser.add_argument("--script-path", required=True)
        parser.add_argument("--input-path", required=True)
        parser.add_argument("--destination-root", required=True)
        parser.add_argument("--source-type", default="list", choices=["xlsx", "list"])
        parser.add_argument("--source-prefix", default="")
        parser.add_argument("--python-executable", default="python3")
        parser.add_argument("--execute", action="store_true")
        parser.add_argument("--approved", action="store_true")
        parser.add_argument("--timeout-sec", type=float, default=1800.0)
        parser.add_argument("--output", default="")
        return parser

    @classmethod
    def from_cli_args(cls, args: Any) -> "CR60DataTransferModule":
        return cls()


__all__ = ["CR60DataTransferModule"]
