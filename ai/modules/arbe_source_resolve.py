# -*- coding: utf-8 -*-
"""Pi capability for read-only source branch/tag resolution."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from engines.arbe.preflight import LocalShellRunner, SshCommandRunner
from engines.arbe.source import SourceResolutionRunner, resolve_source

from .base import BaseModule, ModuleResult


def _load_intake(value: Mapping[str, Any] | None, path: str) -> dict[str, Any]:
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


def _intake_value(payload: Mapping[str, Any], group: str, field: str) -> str:
    group_value = payload.get(group)
    if not isinstance(group_value, Mapping):
        return ""
    item = group_value.get(field)
    if isinstance(item, Mapping):
        item = item.get("value", "")
    if isinstance(item, list):
        item = item[0] if len(item) == 1 else ""
    return str(item or "").strip()


class ArbeSourceResolveModule(BaseModule):
    """Resolve a source target from explicit input/current intake without checkout."""

    name = "arbe-source-resolve"
    description = "Read-only resolve current algo_source branch/tag and configured version mapping"
    tags = ["arbe", "source", "git", "version", "read-only", "atomic"]
    requires_approval = False
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "intake": {"type": "object"},
            "intake_path": {"type": "string"},
            "arbe_root": {"type": "string"},
            "algo_source_root": {"type": "string"},
            "requested_ref": {"type": "string"},
            "software_version": {"type": "string"},
            "ref_prefix": {"type": "string"},
            "version_suffix_strip": {"type": "string"},
            "remote_name": {"type": "string"},
            "remote_query": {"type": "boolean"},
            "server_host": {"type": "string"},
            "server_user": {"type": "string"},
            "server_port": {"type": "integer"},
            "identity_file": {"type": "string"},
            "execute": {"type": "boolean"},
            "timeout_sec": {"type": "number"},
            "output": {"type": "string"},
        },
        "additionalProperties": False,
    }
    output_schema: dict[str, Any] = {
        "type": "object",
        "required": ["schema_version", "status", "target", "current_source", "resolution"],
    }

    def __init__(
        self,
        *,
        runner: SourceResolutionRunner | None = None,
        project_root: Path | str | None = None,
    ) -> None:
        self._runner = runner
        self._project_root = (
            Path(project_root).expanduser().resolve()
            if project_root
            else Path(__file__).resolve().parents[2]
        )

    def _runner_for(self, host: str, user: str, port: int, identity_file: str) -> SourceResolutionRunner:
        if self._runner is not None:
            return self._runner
        if str(host or "").strip():
            return SshCommandRunner(
                host=str(host),
                username=str(user),
                port=int(port),
                identity_file=str(identity_file or ""),
            )
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
        intake: Mapping[str, Any] | None = None,
        intake_path: str = "",
        arbe_root: str = "",
        algo_source_root: str = "",
        requested_ref: str = "",
        software_version: str = "",
        ref_prefix: str = "",
        version_suffix_strip: str = "",
        remote_name: str = "origin",
        remote_query: bool = False,
        server_host: str = "",
        server_user: str = "",
        server_port: int = 0,
        identity_file: str = "",
        execute: bool = False,
        timeout_sec: float = 30.0,
        output: str = "",
        **_: Any,
    ) -> ModuleResult:
        if int(server_port) < 0 or int(server_port) > 65535:
            return ModuleResult.fail(f"server_port out of range: {server_port}", module=self.name)
        try:
            intake_payload = _load_intake(intake, intake_path)
            if (
                str(intake_payload.get("status", "")).strip() == "blocked"
                or str(intake_payload.get("intake_status", "")).strip()
                == "blocked_missing_input"
            ):
                return ModuleResult(
                    ok=False,
                    message="arbe-source-resolve:blocked",
                    module=self.name,
                    data={
                        "schema_version": "arbe-source-resolution.v1",
                        "status": "blocked",
                        "diagnostics": ["intake_blocked_requires_confirmation"],
                    },
                )
            environment = intake_payload.get("environment")
            if not isinstance(environment, Mapping):
                environment = {}
            server = environment.get("server") if isinstance(environment.get("server"), Mapping) else {}
            arbe = environment.get("arbe") if isinstance(environment.get("arbe"), Mapping) else {}
            build = environment.get("build") if isinstance(environment.get("build"), Mapping) else {}
            selected_arbe = str(arbe_root or arbe.get("workspace") or "").strip()
            selected_algo = str(
                algo_source_root or arbe.get("algo_source_root") or ""
            ).strip()
            if not selected_algo and selected_arbe:
                selected_algo = selected_arbe.rstrip("/") + "/src/algo_source"
            selected_ref = str(
                requested_ref
                or _intake_value(intake_payload, "source_context", "code_branch")
                or build.get("code_branch")
                or ""
            ).strip()
            selected_version = str(
                software_version
                or _intake_value(intake_payload, "identity", "software_version")
                or build.get("software_version")
                or ""
            ).strip()
            selected_host = str(server_host or server.get("host") or "").strip()
            selected_user = str(server_user or server.get("user") or "").strip()
            selected_port = int(server_port or server.get("port") or 22)
            if not selected_algo:
                return ModuleResult.fail(
                    "algo_source_root is required; source resolver will not guess a workspace",
                    module=self.name,
                )
            runner = self._runner_for(selected_host, selected_user, selected_port, identity_file)
            payload = resolve_source(
                runner=runner,
                arbe_root=selected_arbe,
                algo_source_root=selected_algo,
                requested_ref=selected_ref,
                software_version=selected_version,
                ref_prefix=ref_prefix,
                version_suffix_strip=version_suffix_strip,
                remote_name=remote_name,
                remote_query=bool(remote_query),
                server_host=selected_host,
                server_user=selected_user,
                server_port=selected_port,
                execute=bool(execute),
                timeout_sec=float(timeout_sec),
            )
            artifacts = self._write(payload, output)
        except (OSError, TypeError, ValueError) as exc:
            return ModuleResult.fail(
                f"arbe source resolution failed: {type(exc).__name__}: {exc}",
                module=self.name,
            )
        status = str(payload.get("status", "failed"))
        return ModuleResult(
            ok=status not in {"blocked", "failed"},
            message=f"arbe-source-resolve:{status}",
            module=self.name,
            data=payload,
            artifacts=artifacts,
        )

    @classmethod
    def register_cli(cls, subparsers: Any) -> Any:
        parser = super().register_cli(subparsers)
        parser.add_argument("--intake", dest="intake_path", default="")
        parser.add_argument("--arbe-root", default="")
        parser.add_argument("--algo-source-root", default="")
        parser.add_argument("--requested-ref", default="")
        parser.add_argument("--software-version", default="")
        parser.add_argument("--ref-prefix", default="")
        parser.add_argument("--version-suffix-strip", default="")
        parser.add_argument("--remote-name", default="origin")
        parser.add_argument("--remote-query", action="store_true")
        parser.add_argument("--host", dest="server_host", default="")
        parser.add_argument("--user", dest="server_user", default="")
        parser.add_argument("--port", dest="server_port", type=int, default=0)
        parser.add_argument("--identity-file", default="")
        parser.add_argument("--execute", action="store_true")
        parser.add_argument("--timeout-sec", type=float, default=30.0)
        parser.add_argument("--output", default="")
        return parser

    @classmethod
    def from_cli_args(cls, args: Any) -> "ArbeSourceResolveModule":
        return cls()


__all__ = ["ArbeSourceResolveModule"]
