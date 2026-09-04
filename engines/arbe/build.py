# -*- coding: utf-8 -*-
"""Approval-aware, feature-neutral remote ``catkin_make`` primitive."""
from __future__ import annotations

import shlex
import time
from typing import Any, Protocol

from .preflight import CommandResult, LocalShellRunner


SCHEMA_VERSION = "arbe-build-session.v1"


class BuildCommandRunner(Protocol):
    def run(self, command: str, *, timeout_sec: float) -> CommandResult:
        ...


def _safe_tokens(values: list[str] | None) -> list[str]:
    result: list[str] = []
    for value in values or []:
        text = str(value or "").strip()
        if not text:
            continue
        if any(char in text for char in ("\x00", "\r", "\n", ";", "`", "$")):
            raise ValueError("catkin_make_args contain an unsafe shell character")
        result.append(text)
    return result


def build_catkin_make_command(
    *,
    arbe_root: str,
    ros_setup: str = "/opt/ros/noetic/setup.bash",
    catkin_make_args: list[str] | None = None,
) -> str:
    """Build a parameterized shell command; never infer a workspace path."""
    root = str(arbe_root or "").strip()
    if not root:
        raise ValueError("arbe_root is required")
    setup = str(ros_setup or "").strip()
    if not setup:
        raise ValueError("ros_setup is required")
    args = _safe_tokens(catkin_make_args)
    suffix = " " + " ".join(shlex.quote(item) for item in args) if args else ""
    return f"source {shlex.quote(setup)} && cd {shlex.quote(root)} && catkin_make{suffix}"


def run_catkin_make(
    *,
    runner: BuildCommandRunner,
    arbe_root: str,
    server_host: str = "",
    server_user: str = "",
    server_port: int = 22,
    ros_setup: str = "/opt/ros/noetic/setup.bash",
    catkin_make_args: list[str] | None = None,
    execute: bool = False,
    timeout_sec: float = 3600.0,
) -> dict[str, Any]:
    """Plan or run one build and preserve the runner result verbatim."""
    command = build_catkin_make_command(
        arbe_root=arbe_root,
        ros_setup=ros_setup,
        catkin_make_args=catkin_make_args,
    )
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": "planned",
        "target": {
            "host": str(server_host or ""),
            "user": str(server_user or ""),
            "port": int(server_port),
            "arbe_root": str(arbe_root),
            "ros_setup": str(ros_setup),
        },
        "command": command,
        "catkin_make_args": list(catkin_make_args or []),
        "execute_requested": bool(execute),
        "diagnostics": [],
    }
    if not execute:
        return payload
    started = time.monotonic()
    result = runner.run(command, timeout_sec=max(1.0, float(timeout_sec)))
    payload["command_result"] = result.to_dict()
    payload["duration_sec"] = round(time.monotonic() - started, 6)
    if result.timed_out:
        payload["status"] = "timeout"
        payload["diagnostics"].append("catkin_make_timeout")
    elif result.returncode == 0:
        payload["status"] = "completed"
    else:
        payload["status"] = "failed"
        payload["diagnostics"].append(f"catkin_make_returncode:{result.returncode}")
    return payload


__all__ = ["BuildCommandRunner", "CommandResult", "LocalShellRunner", "SCHEMA_VERSION", "build_catkin_make_command", "run_catkin_make"]
