# -*- coding: utf-8 -*-
"""Read-only ROS topic inventory for a configured arbe runtime."""
from __future__ import annotations

import re
import shlex
from typing import Any, Protocol

from .preflight import CommandResult, LocalShellRunner, SshCommandRunner


SCHEMA_VERSION = "ros-topic-inventory.v1"
_TOPIC_RE = re.compile(r"^/[A-Za-z0-9_./~-]+$")
_START = "__CR60_TOPIC_START__"
_END = "__CR60_TOPIC_END__"


class InventoryRunner(Protocol):
    def run(self, command: str, *, timeout_sec: float) -> CommandResult:
        ...


def _q(value: str) -> str:
    return shlex.quote(str(value))


def validate_topics(topics: list[str]) -> list[str]:
    errors: list[str] = []
    for index, topic in enumerate(topics):
        if not _TOPIC_RE.fullmatch(str(topic).strip()):
            errors.append(f"topic[{index}]_invalid:{topic}")
    return errors


def build_inventory_command(
    *,
    topics: list[str],
    ros_setup: str = "",
    workspace_setup: str = "",
) -> str:
    errors = validate_topics(topics)
    if errors:
        raise ValueError("; ".join(errors))
    prefix: list[str] = []
    if ros_setup:
        prefix.append(f"source {_q(ros_setup)}")
    if workspace_setup:
        prefix.append(f"source {_q(workspace_setup)}")
    commands: list[str] = []
    for topic in topics:
        marker = _START + topic
        commands.append(
            f"printf '%s\\n' {_q(marker)}; "
            f"rostopic type {_q(topic)} 2>/dev/null || true; "
            f"rostopic info {_q(topic)} 2>/dev/null || true; "
            f"printf '%s\\n' {_q(_END)}"
        )
    body = " && ".join(commands) if commands else "true"
    return " && ".join(prefix + [body])


def build_sample_command(
    *,
    topic: str,
    ros_setup: str = "",
    workspace_setup: str = "",
    timeout_sec: float = 5.0,
) -> str:
    """Build a bounded, read-only one-message sample command."""
    errors = validate_topics([topic])
    if errors:
        raise ValueError("; ".join(errors))
    seconds = max(0.5, min(float(timeout_sec), 60.0))
    prefix: list[str] = []
    if ros_setup:
        prefix.append(f"source {_q(ros_setup)}")
    if workspace_setup:
        prefix.append(f"source {_q(workspace_setup)}")
    prefix.append(
        f"timeout {seconds:g}s rostopic echo -n 1 {_q(topic)}"
    )
    return " && ".join(prefix)


def parse_inventory_output(text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    section = ""
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith(_START):
            if current is not None:
                rows.append(current)
            current = {
                "topic": line[len(_START) :],
                "type": "",
                "publishers": [],
                "subscribers": [],
                "publisher_count": 0,
                "subscriber_count": 0,
                "data_observable": False,
                "status": "not_found",
            }
            section = ""
            continue
        if line == _END:
            if current is not None:
                current["status"] = (
                    "ready"
                    if current["type"] or current["publishers"] or current["subscribers"]
                    else "not_found"
                )
                current["publisher_count"] = len(current["publishers"])
                current["subscriber_count"] = len(current["subscribers"])
                current["data_observable"] = bool(current["publishers"])
                rows.append(current)
            current = None
            section = ""
            continue
        if current is None:
            continue
        if line.startswith("Type:"):
            current["type"] = line.split(":", 1)[1].strip()
            continue
        if not section and not current["type"] and line:
            # `rostopic type /topic` prints only the type name, while
            # `rostopic info /topic` prints a `Type:` label.  Accept both.
            current["type"] = line
            continue
        if line == "Publishers:":
            section = "publishers"
            continue
        if line == "Subscribers:":
            section = "subscribers"
            continue
        if line.startswith("*") and section in {"publishers", "subscribers"}:
            current[section].append(line[1:].strip())
    if current is not None:
        current["publisher_count"] = len(current["publishers"])
        current["subscriber_count"] = len(current["subscribers"])
        current["data_observable"] = bool(current["publishers"])
        rows.append(current)
    return rows


class RosTopicInventory:
    """Read-only topic/type/publisher/subscriber probe."""

    def __init__(
        self,
        *,
        runner: InventoryRunner | None = None,
        server_host: str = "",
        server_user: str = "",
        server_port: int = 22,
        timeout_sec: float = 20.0,
    ) -> None:
        self.server_host = str(server_host).strip()
        self.server_user = str(server_user).strip()
        self.server_port = int(server_port)
        self.timeout_sec = max(0.5, float(timeout_sec))
        self.runner = runner or (
            SshCommandRunner(
                host=self.server_host,
                username=self.server_user,
                port=self.server_port,
            )
            if self.server_host
            else LocalShellRunner()
        )

    def run(
        self,
        *,
        topics: list[str],
        ros_setup: str = "",
        workspace_setup: str = "",
        execute: bool = False,
        sample_once: bool = False,
        sample_timeout_sec: float = 5.0,
    ) -> dict[str, Any]:
        try:
            command = build_inventory_command(
                topics=topics,
                ros_setup=ros_setup,
                workspace_setup=workspace_setup,
            )
        except ValueError as exc:
            return {
                "schema_version": SCHEMA_VERSION,
                "status": "blocked",
                "topics": [],
                "diagnostics": [str(exc)],
            }
        payload: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "status": "planned",
            "server": {
                "host": self.server_host,
                "user": self.server_user,
                "port": self.server_port,
                "transport": "ssh" if self.server_host else "local",
            },
            "requested_topics": list(topics),
            "command": command,
            "topics": [],
            "sample_once": bool(sample_once),
            "sample_timeout_sec": max(0.5, min(float(sample_timeout_sec), 60.0)),
            "diagnostics": [],
        }
        if not execute:
            return payload
        result = self.runner.run(command, timeout_sec=self.timeout_sec)
        rows = parse_inventory_output(result.stdout)
        if sample_once:
            for row in rows:
                sample = self._sample_topic(
                    topic=str(row.get("topic", "")),
                    ros_setup=ros_setup,
                    workspace_setup=workspace_setup,
                    timeout_sec=sample_timeout_sec,
                )
                row["publisher_present"] = bool(row.get("publisher_count", 0))
                row["message_observable"] = bool(sample.get("message_observed"))
                row["observability_basis"] = "single_message_sample"
                row["sample"] = sample
                row["data_observable"] = bool(sample.get("message_observed"))
        payload.update(
            {
                "status": "ready" if result.ok else "failed",
                "topics": rows,
                "command_result": result.to_dict(),
                "diagnostics": ([result.stderr.strip()] if result.stderr.strip() else []),
            }
        )
        return payload

    def _sample_topic(
        self,
        *,
        topic: str,
        ros_setup: str,
        workspace_setup: str,
        timeout_sec: float,
    ) -> dict[str, Any]:
        try:
            command = build_sample_command(
                topic=topic,
                ros_setup=ros_setup,
                workspace_setup=workspace_setup,
                timeout_sec=timeout_sec,
            )
        except ValueError as exc:
            return {
                "status": "blocked",
                "message_observed": False,
                "diagnostics": [str(exc)],
            }
        result = self.runner.run(command, timeout_sec=max(self.timeout_sec, float(timeout_sec) + 2.0))
        observed = bool(result.stdout.strip()) and result.returncode == 0
        status = "observed" if observed else "no_message" if result.returncode == 124 else "failed"
        return {
            "status": status,
            "message_observed": observed,
            "returncode": result.returncode,
            "timed_out": result.timed_out,
            "stdout": result.stdout[:20000],
            "stderr": result.stderr[:4000],
            "duration_sec": round(result.duration_sec, 6),
            "command": command,
        }


__all__ = [
    "SCHEMA_VERSION",
    "RosTopicInventory",
    "build_inventory_command",
    "parse_inventory_output",
    "validate_topics",
]
