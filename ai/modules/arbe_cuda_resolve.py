# -*- coding: utf-8 -*-
"""Pi capability for read-only, current-source CUDA/config resolution."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from engines.arbe.cuda import (
    CudaResolutionRunner,
    LocalShellRunner,
    SshCommandRunner,
    resolve_cuda,
)

from .base import BaseModule, ModuleResult


def _load_intake_for_runtime(
    value: Mapping[str, Any] | None,
    path: str,
) -> dict[str, Any]:
    if value is not None:
        if not isinstance(value, Mapping):
            raise ValueError("intake must be a JSON object")
        return dict(value)
    text = str(path or "").strip()
    if not text:
        return {}
    artifact = Path(text).expanduser().resolve()
    try:
        loaded = json.loads(artifact.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"intake artifact cannot be read: {artifact}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"intake artifact is not valid JSON: {artifact}: {exc.msg}") from exc
    if not isinstance(loaded, Mapping):
        raise ValueError("intake artifact must contain a JSON object")
    return dict(loaded)


class ArbeCudaResolveModule(BaseModule):
    """Discover the current vehicle CUDA workbook and config alignment.

    This is intentionally read-only.  Copying the selected workbook or editing
    ``launch_config_4radars.yaml`` belongs to a later approval-gated atomic
    capability and is never implied by this module.
    """

    name = "arbe-cuda-resolve"
    description = "Read-only resolve current arbe vehicle CUDA workbook and YAML alignment"
    tags = ["arbe", "cuda", "config", "source", "read-only", "atomic"]
    requires_approval = False
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "intake": {"type": "object"},
            "intake_path": {"type": "string"},
            "preflight": {"type": "object"},
            "preflight_path": {"type": "string"},
            "arbe_root": {"type": "string"},
            "algo_source_root": {"type": "string"},
            "vehicle": {"type": "string"},
            "coem": {"type": "string"},
            "cuda_sheet": {"type": "string"},
            "server_host": {"type": "string"},
            "server_user": {"type": "string"},
            "server_port": {"type": "integer"},
            "identity_file": {"type": "string"},
            "config_dir": {"type": "string"},
            "config_name": {"type": "string"},
            "execute": {"type": "boolean"},
            "timeout_sec": {"type": "number"},
            "output": {"type": "string"},
        },
        "additionalProperties": False,
    }
    output_schema: dict[str, Any] = {
        "type": "object",
        "required": [
            "schema_version",
            "status",
            "target",
            "candidates",
            "selected",
            "configuration",
            "provenance",
        ],
    }

    def __init__(
        self,
        *,
        runner: CudaResolutionRunner | None = None,
        project_root: Path | str | None = None,
    ) -> None:
        self._runner = runner
        self._project_root = (
            Path(project_root).expanduser().resolve()
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
    ) -> CudaResolutionRunner:
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
        intake: Mapping[str, Any] | None = None,
        intake_path: str = "",
        preflight: Mapping[str, Any] | None = None,
        preflight_path: str = "",
        arbe_root: str = "",
        algo_source_root: str = "",
        vehicle: str = "",
        coem: str = "",
        cuda_sheet: str = "",
        server_host: str = "",
        server_user: str = "",
        server_port: int = 0,
        identity_file: str = "",
        config_dir: str = "",
        config_name: str = "launch_config_4radars.yaml",
        execute: bool = False,
        timeout_sec: float = 30.0,
        output: str = "",
        **_: Any,
    ) -> ModuleResult:
        if int(server_port) < 0 or int(server_port) > 65535:
            return ModuleResult.fail(
                f"server_port out of range: {server_port}",
                module=self.name,
            )
        try:
            intake_payload = _load_intake_for_runtime(intake, intake_path)
            environment = intake_payload.get("environment")
            if not isinstance(environment, Mapping):
                environment = {}
            server = environment.get("server") if isinstance(environment.get("server"), Mapping) else {}
            effective_host = str(server_host or server.get("host") or "").strip()
            effective_user = str(server_user or server.get("user") or "").strip()
            effective_port = int(server_port or server.get("port") or 22)
            runner = self._build_runner(
                server_host=effective_host,
                server_user=effective_user,
                server_port=effective_port,
                identity_file=str(identity_file or ""),
            )
            payload = resolve_cuda(
                runner=runner,
                intake=intake,
                intake_path=intake_path,
                preflight=preflight,
                preflight_path=preflight_path,
                arbe_root=arbe_root,
                algo_source_root=algo_source_root,
                vehicle=vehicle,
                coem=coem,
                expected_sheet=cuda_sheet,
                server_host=effective_host,
                server_user=effective_user,
                server_port=effective_port,
                config_dir=config_dir,
                config_name=config_name,
                execute=bool(execute),
                timeout_sec=float(timeout_sec),
            )
        except (OSError, TypeError, ValueError) as exc:
            return ModuleResult.fail(
                f"arbe CUDA resolution failed: {type(exc).__name__}: {exc}",
                module=self.name,
            )

        artifacts: list[str] = []
        if str(output or "").strip():
            path = self._resolve_output(output)
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                artifacts.append(str(path))
                payload["artifact_path"] = str(path)
            except OSError as exc:
                return ModuleResult(
                    ok=False,
                    message=f"arbe CUDA output write failed: {type(exc).__name__}: {exc}",
                    module=self.name,
                    data=payload,
                    artifacts=artifacts,
                )

        status = str(payload.get("status", "failed"))
        return ModuleResult(
            ok=status not in {"blocked", "failed"},
            message=f"arbe-cuda-resolve:{status}",
            module=self.name,
            data=payload,
            artifacts=artifacts,
        )

    @classmethod
    def register_cli(cls, subparsers: Any) -> Any:
        parser = super().register_cli(subparsers)
        parser.add_argument("--intake", dest="intake_path", default="")
        parser.add_argument("--preflight", dest="preflight_path", default="")
        parser.add_argument("--arbe-root", default="")
        parser.add_argument("--algo-source-root", default="")
        parser.add_argument("--vehicle", default="")
        parser.add_argument("--coem", default="")
        parser.add_argument("--cuda-sheet", default="")
        parser.add_argument("--host", dest="server_host", default="")
        parser.add_argument("--user", dest="server_user", default="")
        parser.add_argument("--port", dest="server_port", type=int, default=0)
        parser.add_argument("--identity-file", default="")
        parser.add_argument("--config-dir", default="")
        parser.add_argument("--config-name", default="launch_config_4radars.yaml")
        parser.add_argument("--execute", action="store_true")
        parser.add_argument("--timeout-sec", type=float, default=30.0)
        parser.add_argument("--output", default="")
        return parser

    @classmethod
    def from_cli_args(cls, args: Any) -> "ArbeCudaResolveModule":
        return cls()


__all__ = ["ArbeCudaResolveModule"]
