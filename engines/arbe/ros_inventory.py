# -*- coding: utf-8 -*-
"""Read-only ROS topic inventory for a configured arbe runtime."""
from __future__ import annotations

import hashlib
import re
import shlex
from datetime import datetime, timezone
from typing import Any, Mapping, Protocol

from .preflight import CommandResult, LocalShellRunner, SshCommandRunner


SCHEMA_VERSION = "ros-topic-inventory.v1"
_TOPIC_RE = re.compile(r"^/[A-Za-z0-9_./~-]+$")
_ROS_TYPE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*/[A-Za-z][A-Za-z0-9_]*$")
_ROS_FIELD_RE = re.compile(
    r"^([A-Za-z][A-Za-z0-9_/]*(?:\[[^\]]*\])?)\s+([A-Za-z][A-Za-z0-9_]*)\s*(?:=.*)?$"
)
_MAX_MESSAGE_DEFINITION_CHARS = 250_000
_MAX_MESSAGE_FIELD_CATALOG_ITEMS = 512
_MAX_TOPIC_SAMPLE_CHARS = 20_000
_START = "__CR60_TOPIC_START__"
_END = "__CR60_TOPIC_END__"


class InventoryRunner(Protocol):
    def run(self, command: str, *, timeout_sec: float) -> CommandResult:
        ...


def _q(value: str) -> str:
    return shlex.quote(str(value))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


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


def build_message_definition_command(
    *,
    message_type: str,
    ros_setup: str = "",
    workspace_setup: str = "",
) -> str:
    """Build a read-only rosmsg query for one validated ROS message type."""
    value = str(message_type).strip()
    if not _ROS_TYPE_RE.fullmatch(value):
        raise ValueError(f"message_type_invalid:{message_type}")
    prefix: list[str] = []
    if ros_setup:
        prefix.append(f"source {_q(ros_setup)}")
    if workspace_setup:
        prefix.append(f"source {_q(workspace_setup)}")
    prefix.append(f"rosmsg show {_q(value)}")
    return " && ".join(prefix)


def parse_message_definition(text: str, *, root_type: str) -> list[dict[str, str]]:
    """Parse field paths from the active ``rosmsg show`` output."""
    fields: list[dict[str, str]] = []
    current_type = str(root_type).strip()
    for raw_line in str(text).splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("MSG:"):
            nested_type = line.split(":", 1)[1].strip()
            if _ROS_TYPE_RE.fullmatch(nested_type):
                current_type = nested_type
            continue
        match = _ROS_FIELD_RE.fullmatch(line)
        if not match:
            continue
        field_type, name = match.groups()
        fields.append({
            "message_type": current_type,
            "name": name,
            "type": field_type,
            "path": f"{current_type}.{name}",
        })
    return fields


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
        inspect_message_schemas: bool = False,
        runtime_binding: Mapping[str, Any] | None = None,
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
            "inspect_message_schemas": bool(inspect_message_schemas),
            "runtime_binding": dict(runtime_binding) if isinstance(runtime_binding, Mapping) else {
                "status": "not_bound",
                "preflight_sha256": "",
            },
            "diagnostics": [],
        }
        if not execute:
            return payload
        result = self.runner.run(command, timeout_sec=self.timeout_sec)
        rows = parse_inventory_output(result.stdout)
        if inspect_message_schemas:
            for row in rows:
                row["message_schema"] = self._inspect_message_schema(
                    message_type=str(row.get("type") or "").strip(),
                    ros_setup=ros_setup,
                    workspace_setup=workspace_setup,
                )
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
                "observed_at_utc": _utc_now(),
                "topics": rows,
                "command_result": result.to_dict(),
                "diagnostics": ([result.stderr.strip()] if result.stderr.strip() else []),
            }
        )
        return payload

    def _inspect_message_schema(
        self,
        *,
        message_type: str,
        ros_setup: str,
        workspace_setup: str,
    ) -> dict[str, Any]:
        try:
            command = build_message_definition_command(
                message_type=message_type,
                ros_setup=ros_setup,
                workspace_setup=workspace_setup,
            )
        except ValueError as exc:
            return {
                "status": "blocked",
                "message_type": message_type,
                "diagnostics": [str(exc)],
            }
        result = self.runner.run(command, timeout_sec=self.timeout_sec)
        full_text = str(result.stdout or "")
        bounded_text = full_text[:_MAX_MESSAGE_DEFINITION_CHARS]
        fields = parse_message_definition(bounded_text, root_type=message_type)
        definition_truncated = len(full_text) > _MAX_MESSAGE_DEFINITION_CHARS
        catalog_truncated = (
            len(fields) > _MAX_MESSAGE_FIELD_CATALOG_ITEMS or definition_truncated
        )
        status = (
            "failed" if not result.ok
            else "empty" if not fields
            else "partial" if catalog_truncated
            else "ready"
        )
        return {
            "status": status,
            "message_type": message_type,
            "message_definition_sha256": hashlib.sha256(full_text.encode("utf-8")).hexdigest(),
            "definition_char_count": len(full_text),
            "field_catalog": fields[:_MAX_MESSAGE_FIELD_CATALOG_ITEMS],
            "field_count": len(fields),
            "field_catalog_truncated": catalog_truncated,
            "definition_truncated": definition_truncated,
            "command_result": {
                "command": command,
                "returncode": result.returncode,
                "timed_out": result.timed_out,
                "duration_sec": round(float(result.duration_sec), 6),
                "stderr": str(result.stderr or "")[:4000],
            },
            "diagnostics": (
                [] if status == "ready" else
                ["message_definition_unavailable"] if status == "failed" else
                ["message_definition_has_no_fields"] if status == "empty" else
                ["message_definition_field_catalog_truncated"]
            ),
        }

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
        full_stdout = str(result.stdout or "")
        observed = bool(full_stdout.strip()) and result.returncode == 0
        status = "observed" if observed else "no_message" if result.returncode == 124 else "failed"
        return {
            "status": status,
            "message_observed": observed,
            "observed_at_utc": _utc_now(),
            "observation_clock": "client_utc",
            "returncode": result.returncode,
            "timed_out": result.timed_out,
            "stdout": full_stdout[:_MAX_TOPIC_SAMPLE_CHARS],
            "stdout_sha256": hashlib.sha256(full_stdout.encode("utf-8")).hexdigest(),
            "stdout_char_count": len(full_stdout),
            "stdout_truncated": len(full_stdout) > _MAX_TOPIC_SAMPLE_CHARS,
            "stderr": result.stderr[:4000],
            "duration_sec": round(result.duration_sec, 6),
            "command": command,
        }


__all__ = [
    "SCHEMA_VERSION",
    "RosTopicInventory",
    "build_inventory_command",
    "build_message_definition_command",
    "parse_inventory_output",
    "parse_message_definition",
    "validate_topics",
]
