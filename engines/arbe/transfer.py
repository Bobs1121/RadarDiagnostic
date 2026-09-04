# -*- coding: utf-8 -*-
"""Approval-bound adapter for the upstream ``bosch-data-transfert`` script."""
from __future__ import annotations

import shlex
import time
from typing import Any, Protocol

from .preflight import CommandResult


SCHEMA_VERSION = "cr60-data-transfer-session.v1"


class DataTransferRunner(Protocol):
    def run(self, command: str, *, timeout_sec: float) -> CommandResult:
        ...


def _q(value: str) -> str:
    return shlex.quote(str(value))


def _safe_source_type(value: str) -> str:
    text = str(value or "").strip().lower()
    if text not in {"xlsx", "list"}:
        raise ValueError("source_type must be xlsx or list")
    return text


def build_transfer_command(
    *,
    script_path: str,
    input_path: str,
    destination_root: str,
    source_type: str = "list",
    source_prefix: str = "",
    python_executable: str = "python3",
) -> str:
    """Build a remote command with all paths passed as shell-quoted tokens."""

    script = str(script_path or "").strip()
    input_file = str(input_path or "").strip()
    destination = str(destination_root or "").strip()
    interpreter = str(python_executable or "").strip()
    if not script or not input_file or not destination or not interpreter:
        raise ValueError("script_path, input_path, destination_root and python_executable are required")
    if not destination.startswith("/") and not destination.startswith("~"):
        raise ValueError("destination_root must be an explicit absolute or home-relative Linux path")
    source_kind = _safe_source_type(source_type)
    if any(ord(char) < 32 for char in script + input_file + destination + interpreter):
        raise ValueError("transfer paths contain a control character")
    parts = [
        _q(interpreter),
        _q(script),
        _q(input_file),
        "--src-type",
        _q(source_kind),
        "--dst",
        _q(destination),
    ]
    if source_prefix:
        parts.extend(["--src", _q(str(source_prefix).strip())])
    return " ".join(parts)


def run_transfer(
    *,
    runner: DataTransferRunner,
    server_host: str = "",
    server_user: str = "",
    server_port: int = 22,
    script_path: str,
    input_path: str,
    destination_root: str,
    source_type: str = "list",
    source_prefix: str = "",
    python_executable: str = "python3",
    execute: bool = False,
    approved: bool = False,
    timeout_sec: float = 1800.0,
) -> dict[str, Any]:
    command = build_transfer_command(
        script_path=script_path,
        input_path=input_path,
        destination_root=destination_root,
        source_type=source_type,
        source_prefix=source_prefix,
        python_executable=python_executable,
    )
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": "planned",
        "target": {
            "host": str(server_host or "").strip(),
            "user": str(server_user or "").strip(),
            "port": int(server_port),
            "script_path": str(script_path),
            "input_path": str(input_path),
            "destination_root": str(destination_root),
        },
        "command": command,
        "source_type": _safe_source_type(source_type),
        "source_prefix": str(source_prefix or ""),
        "execute_requested": bool(execute),
        "approved": bool(approved),
        "upstream": "bosch-data-transfert",
        "side_effects": ["remote data copy", "remote destination directory creation by upstream script"],
        "diagnostics": [],
    }
    if not execute:
        return payload
    if not approved:
        payload["status"] = "approval_required"
        payload["diagnostics"].append("data_transfer_requires_explicit_approved_true")
        return payload
    started = time.monotonic()
    result = runner.run(command, timeout_sec=max(1.0, float(timeout_sec)))
    payload["command_result"] = result.to_dict()
    payload["duration_sec"] = round(time.monotonic() - started, 6)
    if result.timed_out:
        payload["status"] = "timeout"
        payload["diagnostics"].append("data_transfer_timeout")
    elif result.returncode == 0:
        payload["status"] = "completed"
    else:
        payload["status"] = "failed"
        payload["diagnostics"].append(f"data_transfer_returncode:{result.returncode}")
    return payload


__all__ = [
    "DataTransferRunner",
    "SCHEMA_VERSION",
    "build_transfer_command",
    "run_transfer",
]
