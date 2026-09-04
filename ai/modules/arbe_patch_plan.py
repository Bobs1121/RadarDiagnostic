# -*- coding: utf-8 -*-
"""Pi capability for read-only, configurable arbe simulation-patch checks."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from engines.arbe.patch_plan import PatchPlanRunner, resolve_patch_plan
from engines.arbe.preflight import LocalShellRunner, SshCommandRunner

from .base import BaseModule, ModuleResult


def _load_json(value: Mapping[str, Any] | None, path: str, label: str) -> dict[str, Any]:
    if value is not None:
        if not isinstance(value, Mapping):
            raise ValueError(f"{label} must be a JSON object")
        return dict(value)
    text = str(path or "").strip()
    if not text:
        return {}
    artifact = Path(text).expanduser().resolve()
    try:
        loaded = json.loads(artifact.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"{label} artifact cannot be read: {artifact}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} artifact is not valid JSON: {artifact}: {exc.msg}") from exc
    if not isinstance(loaded, Mapping):
        raise ValueError(f"{label} artifact must contain a JSON object")
    return dict(loaded)


class ArbePatchPlanModule(BaseModule):
    """Inspect configured simulation adaptations without applying them."""

    name = "arbe-patch-plan"
    description = "Read-only inspect configurable arbe simulation adaptation checks and dirty diffs"
    tags = ["arbe", "patch", "simulation", "source", "read-only", "atomic"]
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
            "checks": {"type": "array", "items": {"type": "object"}},
            "include_diff": {"type": "boolean"},
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
        "required": ["schema_version", "status", "target", "check_specs", "checks", "source"],
    }

    def __init__(
        self,
        *,
        runner: PatchPlanRunner | None = None,
        project_root: Path | str | None = None,
    ) -> None:
        self._runner = runner
        self._project_root = (
            Path(project_root).expanduser().resolve()
            if project_root
            else Path(__file__).resolve().parents[2]
        )

    def _runner_for(self, host: str, user: str, port: int, identity_file: str) -> PatchPlanRunner:
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
        preflight: Mapping[str, Any] | None = None,
        preflight_path: str = "",
        arbe_root: str = "",
        algo_source_root: str = "",
        checks: list[Mapping[str, Any]] | None = None,
        include_diff: bool = True,
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
            intake_payload = _load_json(intake, intake_path, "intake")
            preflight_payload = _load_json(preflight, preflight_path, "preflight")
            environment = intake_payload.get("environment")
            if not isinstance(environment, Mapping):
                environment = {}
            server = environment.get("server") if isinstance(environment.get("server"), Mapping) else {}
            arbe = environment.get("arbe") if isinstance(environment.get("arbe"), Mapping) else {}
            selected_arbe = str(arbe_root or arbe.get("workspace") or "").strip()
            selected_algo = str(algo_source_root or arbe.get("algo_source_root") or "").strip()
            if not selected_algo and selected_arbe:
                selected_algo = selected_arbe.rstrip("/") + "/src/algo_source"
            selected_host = str(server_host or server.get("host") or "").strip()
            selected_user = str(server_user or server.get("user") or "").strip()
            selected_port = int(server_port or server.get("port") or 22)
            if str(intake_payload.get("status", "")).strip() == "blocked":
                return ModuleResult.fail(
                    "intake is blocked; simulation patch inspection requires confirmed source context",
                    module=self.name,
                    schema_version="arbe-patch-plan.v1",
                    status="blocked",
                    diagnostics=["intake_blocked_requires_confirmation"],
                )
            if not selected_arbe:
                return ModuleResult.fail(
                    "arbe_root is required; patch plan will not guess a workspace",
                    module=self.name,
                )
            if not selected_algo:
                selected_algo = selected_arbe.rstrip("/") + "/src/algo_source"
            runner = self._runner_for(selected_host, selected_user, selected_port, identity_file)
            payload = resolve_patch_plan(
                runner=runner,
                arbe_root=selected_arbe,
                algo_source_root=selected_algo,
                checks=checks,
                include_diff=bool(include_diff),
                server_host=selected_host,
                server_user=selected_user,
                server_port=selected_port,
                execute=bool(execute),
                timeout_sec=float(timeout_sec),
            )
            payload["provenance"]["preflight_schema_version"] = str(
                preflight_payload.get("schema_version", "")
            )
            artifacts = self._write(payload, output)
        except (OSError, TypeError, ValueError) as exc:
            return ModuleResult.fail(
                f"arbe patch plan failed: {type(exc).__name__}: {exc}",
                module=self.name,
            )
        status = str(payload.get("status", "failed"))
        return ModuleResult(
            ok=status not in {"blocked", "failed", "needs_action"},
            message=f"arbe-patch-plan:{status}",
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
        parser.add_argument("--checks", default="", help="optional JSON array of check definitions")
        parser.add_argument("--no-diff", dest="include_diff", action="store_false")
        parser.set_defaults(include_diff=True)
        parser.add_argument("--host", dest="server_host", default="")
        parser.add_argument("--user", dest="server_user", default="")
        parser.add_argument("--port", dest="server_port", type=int, default=0)
        parser.add_argument("--identity-file", default="")
        parser.add_argument("--execute", action="store_true")
        parser.add_argument("--timeout-sec", type=float, default=30.0)
        parser.add_argument("--output", default="")
        return parser

    @classmethod
    def from_cli_args(cls, args: Any) -> "ArbePatchPlanModule":
        checks_text = getattr(args, "checks", "")
        if checks_text:
            try:
                args.checks = json.loads(checks_text)
            except json.JSONDecodeError as exc:
                raise ValueError(f"checks must be valid JSON: {exc.msg}") from exc
            if not isinstance(args.checks, list):
                raise ValueError("checks must decode to a JSON array")
        else:
            args.checks = None
        return cls()


__all__ = ["ArbePatchPlanModule"]
