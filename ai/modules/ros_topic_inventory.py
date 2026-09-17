# -*- coding: utf-8 -*-
"""Atomic read-only ROS topic inventory capability."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from engines.arbe.ros_inventory import RosTopicInventory

from .base import BaseModule, ModuleResult


class RosTopicInventoryModule(BaseModule):
    """Inspect configured ROS topics without changing the remote runtime."""

    name = "ros-topic-inventory"
    description = (
        "Read-only ROS topic/type/publisher/subscriber inventory for an arbe runtime; "
        "optionally bind to an arbe-preflight.v1 artifact and return a bounded field catalog from the active message definition"
    )
    tags = ["ros", "arbe", "public-evidence", "atomic", "read-only"]
    requires_approval = False
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "topics": {"type": "array", "items": {"type": "string"}},
            "server_host": {"type": "string"},
            "server_user": {"type": "string"},
            "server_port": {"type": "integer"},
            "preflight_path": {
                "type": "string",
                "description": "Optional arbe-preflight.v1 input; resolves the server and binds the inventory sample to its server/workspace hash.",
            },
            "ros_setup": {"type": "string"},
            "workspace_setup": {"type": "string"},
            "timeout_sec": {"type": "number"},
            "execute": {"type": "boolean"},
            "sample_once": {"type": "boolean"},
            "sample_timeout_sec": {"type": "number"},
            "inspect_message_schemas": {
                "type": "boolean",
                "description": "Enable when current message fields are needed; reads rosmsg show and returns a bounded, hash-bound field catalog.",
            },
            "output": {"type": "string"},
        },
        "required": ["topics"],
        "additionalProperties": False,
    }
    output_schema: dict[str, Any] = {
        "type": "object",
        "required": ["schema_version", "status", "requested_topics", "topics"],
    }

    def run(
        self,
        *,
        topics: list[str],
        server_host: str = "",
        server_user: str = "",
        server_port: int = 22,
        preflight_path: str = "",
        ros_setup: str = "",
        workspace_setup: str = "",
        timeout_sec: float = 20.0,
        execute: bool = False,
        sample_once: bool = False,
        sample_timeout_sec: float = 5.0,
        inspect_message_schemas: bool = False,
        output: str = "",
        **_: Any,
    ) -> ModuleResult:
        if not isinstance(topics, list) or not topics:
            return ModuleResult.fail("topics must be a non-empty list", module=self.name)
        runtime_binding: dict[str, Any] = {"status": "not_bound", "preflight_sha256": ""}
        if preflight_path:
            try:
                preflight_file = Path(preflight_path).expanduser().resolve()
                preflight_bytes = preflight_file.read_bytes()
                preflight_value = json.loads(preflight_bytes)
                if not isinstance(preflight_value, dict) or preflight_value.get("schema_version") != "arbe-preflight.v1":
                    raise ValueError("preflight_path must point to arbe-preflight.v1")
                preflight_server = preflight_value.get("server")
                preflight_server = preflight_server if isinstance(preflight_server, dict) else {}
                preflight_host = str(preflight_server.get("host") or "").strip()
                preflight_user = str(preflight_server.get("user") or "").strip()
                try:
                    preflight_port = int(preflight_server.get("port", server_port))
                except (TypeError, ValueError):
                    preflight_port = int(server_port)
                if server_host and preflight_host and str(server_host).strip() != preflight_host:
                    raise ValueError("server_host conflicts with preflight identity")
                if server_user and preflight_user and str(server_user).strip() != preflight_user:
                    raise ValueError("server_user conflicts with preflight identity")
                if int(server_port) != 22 and int(server_port) != preflight_port:
                    raise ValueError("server_port conflicts with preflight identity")
                server_host = str(server_host or preflight_host)
                server_user = str(server_user or preflight_user)
                server_port = preflight_port
                workspace = preflight_value.get("workspace")
                workspace = dict(workspace) if isinstance(workspace, dict) else {}
                preflight_status = str(preflight_value.get("status") or "unknown")
                binding_status = (
                    "preflight_bound"
                    if preflight_status == "ready" and preflight_host and preflight_user and workspace
                    else "preflight_partial"
                )
                configuration = preflight_value.get("configuration")
                configuration = configuration if isinstance(configuration, dict) else {}
                build = preflight_value.get("build")
                build = build if isinstance(build, dict) else {}
                runtime_binding = {
                    "status": binding_status,
                    "preflight_path": str(preflight_file),
                    "preflight_sha256": hashlib.sha256(preflight_bytes).hexdigest(),
                    "preflight_status": preflight_status,
                    "server": {
                        "host": preflight_host,
                        "user": preflight_user,
                        "port": preflight_port,
                        "transport": str(preflight_server.get("transport") or "ssh"),
                    },
                    "workspace": workspace,
                    "binary_fingerprint": str(build.get("binary_fingerprint") or ""),
                    "config_fingerprint": str(configuration.get("content_fingerprint") or ""),
                }
            except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
                return ModuleResult.fail(
                    f"invalid preflight binding: {type(exc).__name__}: {exc}",
                    module=self.name,
                )
        inventory = RosTopicInventory(
            server_host=server_host,
            server_user=server_user,
            server_port=server_port,
            timeout_sec=timeout_sec,
        )
        payload = inventory.run(
            topics=[str(item) for item in topics],
            ros_setup=ros_setup,
            workspace_setup=workspace_setup,
            execute=execute,
            sample_once=sample_once,
            sample_timeout_sec=sample_timeout_sec,
            inspect_message_schemas=inspect_message_schemas,
            runtime_binding=runtime_binding,
        )
        artifacts: list[str] = []
        if output:
            path = Path(output).expanduser().resolve()
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
                artifacts.append(str(path))
                payload["artifact_path"] = str(path)
            except OSError as exc:
                return ModuleResult(
                    ok=False,
                    message=f"ROS inventory output failed: {type(exc).__name__}: {exc}",
                    module=self.name,
                    data=payload,
                    artifacts=artifacts,
                )
        return ModuleResult(
            ok=payload.get("status") not in {"blocked", "failed"},
            message=f"ros-topic-inventory:{payload.get('status', 'unknown')}",
            module=self.name,
            data=payload,
            artifacts=artifacts,
        )

    @classmethod
    def register_cli(cls, subparsers: Any) -> Any:
        parser = super().register_cli(subparsers)
        parser.add_argument("--topic", dest="topics", action="append", default=[], required=True)
        parser.add_argument("--host", dest="server_host", default="")
        parser.add_argument("--user", dest="server_user", default="")
        parser.add_argument("--port", dest="server_port", type=int, default=22)
        parser.add_argument("--preflight-path", default="")
        parser.add_argument("--ros-setup", default="")
        parser.add_argument("--workspace-setup", default="")
        parser.add_argument("--timeout-sec", type=float, default=20.0)
        parser.add_argument("--execute", action="store_true")
        parser.add_argument(
            "--sample-once",
            action="store_true",
            help="After inventory, bounded read-only rostopic echo -n 1 for each topic.",
        )
        parser.add_argument("--sample-timeout-sec", type=float, default=5.0)
        parser.add_argument(
            "--inspect-message-schemas",
            action="store_true",
            help="Read current ROS message definitions with rosmsg show and hash the field catalog.",
        )
        parser.add_argument("--output", default="")
        return parser

    @classmethod
    def from_cli_args(cls, args: Any) -> "RosTopicInventoryModule":
        return cls()


__all__ = ["RosTopicInventoryModule"]
