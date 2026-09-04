# -*- coding: utf-8 -*-
"""Pi capability for read-only verification of prepared CR60 data."""
from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from engines.arbe.data_prep import DataPrepRunner, verify_data
from engines.arbe.preflight import LocalShellRunner, SshCommandRunner

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


def _bag_items(case: Mapping[str, Any]) -> list[str]:
    raw = case.get("bag_paths")
    if raw is None:
        raw = case.get("files")
    if raw is None and case.get("bag"):
        raw = [case.get("bag")]
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    paths: list[str] = []
    for item in raw:
        if isinstance(item, Mapping):
            item = item.get("path") or item.get("bag") or ""
        text = str(item or "").strip()
        if text:
            paths.append(text)
    return paths


def _explicit_entries(
    *,
    intake: Mapping[str, Any],
    data_paths: list[str] | None,
    destination_root: str,
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    data = intake.get("data") if isinstance(intake.get("data"), Mapping) else {}
    cases = data.get("cases") if isinstance(data.get("cases"), list) else []
    for case_index, case in enumerate(cases):
        if not isinstance(case, Mapping):
            continue
        case_id = str(case.get("case_id") or f"case-{case_index + 1}").strip()
        destination = ""
        if str(destination_root or "").strip():
            destination = str(PurePosixPath(str(destination_root).rstrip("/")) / case_id)
        for path in _bag_items(case):
            entries.append(
                {"case_id": case_id, "source_path": path, "destination_dir": destination}
            )
    if not entries:
        for index, path in enumerate(data_paths or []):
            entries.append(
                {
                    "case_id": f"case-{index + 1}",
                    "source_path": str(path),
                    "destination_dir": "",
                }
            )
    return entries


class CR60DataPrepVerifyModule(BaseModule):
    """Verify Linux-visible source/destination data without copying it."""

    name = "cr60-data-prep-verify"
    description = "Read-only verify CR60 data files, size and SHA-256 before/after transfer"
    tags = ["cr60", "data", "transfer", "verify", "read-only", "atomic"]
    requires_approval = False
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "intake": {"type": "object"},
            "intake_path": {"type": "string"},
            "data_paths": {"type": "array", "items": {"type": "string"}},
            "destination_root": {"type": "string"},
            "source_prefix": {"type": "string"},
            "extensions": {"type": "array", "items": {"type": "string"}},
            "check_destination": {"type": "boolean"},
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
        "required": [
            "schema_version",
            "status",
            "verification_policy",
            "entries",
            "cases",
            "provenance",
        ],
    }

    def __init__(
        self,
        *,
        runner: DataPrepRunner | None = None,
        project_root: Path | str | None = None,
    ) -> None:
        self._runner = runner
        self._project_root = (
            Path(project_root).expanduser().resolve()
            if project_root
            else Path(__file__).resolve().parents[2]
        )

    def _runner_for(self, host: str, user: str, port: int, identity_file: str) -> DataPrepRunner:
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
        data_paths: list[str] | None = None,
        destination_root: str = "",
        source_prefix: str = "",
        extensions: list[str] | None = None,
        check_destination: bool = False,
        server_host: str = "",
        server_user: str = "",
        server_port: int = 0,
        identity_file: str = "",
        execute: bool = False,
        timeout_sec: float = 60.0,
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
                    message="cr60-data-prep-verify:blocked",
                    module=self.name,
                    data={
                        "schema_version": "cr60-data-prep-verification.v1",
                        "status": "blocked",
                        "diagnostics": ["intake_blocked_requires_confirmation"],
                    },
                )
            environment = intake_payload.get("environment")
            if not isinstance(environment, Mapping):
                environment = {}
            server = environment.get("server") if isinstance(environment.get("server"), Mapping) else {}
            selected_host = str(server_host or server.get("host") or "").strip()
            selected_user = str(server_user or server.get("user") or "").strip()
            selected_port = int(server_port or server.get("port") or 22)
            entries = _explicit_entries(
                intake=intake_payload,
                data_paths=data_paths,
                destination_root=destination_root,
            )
            if not entries:
                return ModuleResult.fail(
                    "no data paths found; provide intake or data_paths",
                    module=self.name,
                )
            runner = self._runner_for(selected_host, selected_user, selected_port, identity_file)
            payload = verify_data(
                runner=runner,
                entries=entries,
                extensions=extensions,
                source_prefix=source_prefix,
                check_destination=bool(check_destination),
                server_host=selected_host,
                server_user=selected_user,
                server_port=selected_port,
                execute=bool(execute),
                timeout_sec=float(timeout_sec),
            )
            payload["provenance"]["intake_status"] = str(intake_payload.get("status", ""))
            payload["provenance"]["handoff_id"] = str(intake_payload.get("handoff_id", ""))
            artifacts = self._write(payload, output)
        except (OSError, TypeError, ValueError) as exc:
            return ModuleResult.fail(
                f"CR60 data verification failed: {type(exc).__name__}: {exc}",
                module=self.name,
            )
        status = str(payload.get("status", "failed"))
        return ModuleResult(
            ok=status not in {"blocked", "failed"},
            message=f"cr60-data-prep-verify:{status}",
            module=self.name,
            data=payload,
            artifacts=artifacts,
        )

    @classmethod
    def register_cli(cls, subparsers: Any) -> Any:
        parser = super().register_cli(subparsers)
        parser.add_argument("--intake", dest="intake_path", default="")
        parser.add_argument("--data", dest="data_paths", action="append", default=[])
        parser.add_argument("--destination-root", default="")
        parser.add_argument("--source-prefix", default="")
        parser.add_argument("--extension", dest="extensions", action="append", default=[])
        parser.add_argument("--check-destination", action="store_true")
        parser.add_argument("--host", dest="server_host", default="")
        parser.add_argument("--user", dest="server_user", default="")
        parser.add_argument("--port", dest="server_port", type=int, default=0)
        parser.add_argument("--identity-file", default="")
        parser.add_argument("--execute", action="store_true")
        parser.add_argument("--timeout-sec", type=float, default=60.0)
        parser.add_argument("--output", default="")
        return parser

    @classmethod
    def from_cli_args(cls, args: Any) -> "CR60DataPrepVerifyModule":
        if not getattr(args, "extensions", None):
            args.extensions = None
        return cls()


__all__ = ["CR60DataPrepVerifyModule"]
