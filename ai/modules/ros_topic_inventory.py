# -*- coding: utf-8 -*-
"""Atomic read-only ROS topic inventory capability."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from engines.arbe.ros_inventory import RosTopicInventory

from .base import BaseModule, ModuleResult


class RosTopicInventoryModule(BaseModule):
    """Inspect configured ROS topics without changing the remote runtime."""

    name = "ros-topic-inventory"
    description = "Read-only ROS topic type/publisher/subscriber inventory for an arbe runtime"
    tags = ["ros", "arbe", "public-evidence", "atomic", "read-only"]
    requires_approval = False
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "topics": {"type": "array", "items": {"type": "string"}},
            "server_host": {"type": "string"},
            "server_user": {"type": "string"},
            "server_port": {"type": "integer"},
            "ros_setup": {"type": "string"},
            "workspace_setup": {"type": "string"},
            "timeout_sec": {"type": "number"},
            "execute": {"type": "boolean"},
            "sample_once": {"type": "boolean"},
            "sample_timeout_sec": {"type": "number"},
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
        ros_setup: str = "",
        workspace_setup: str = "",
        timeout_sec: float = 20.0,
        execute: bool = False,
        sample_once: bool = False,
        sample_timeout_sec: float = 5.0,
        output: str = "",
        **_: Any,
    ) -> ModuleResult:
        if not isinstance(topics, list) or not topics:
            return ModuleResult.fail("topics must be a non-empty list", module=self.name)
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
        parser.add_argument("--output", default="")
        return parser

    @classmethod
    def from_cli_args(cls, args: Any) -> "RosTopicInventoryModule":
        return cls()


__all__ = ["RosTopicInventoryModule"]
