# -*- coding: utf-8 -*-
"""Atomic public ROS evidence-channel planning capability."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from engines.arbe.public_evidence import (
    build_public_topic_plan,
    load_json_mapping,
    load_profile_mapping,
)

from .base import BaseModule, ModuleResult


class PublicTopicPlanModule(BaseModule):
    """Describe public per-frame channels without attaching GDB or ROS."""

    name = "public-topic-plan"
    description = "Plan public arbe ROS/bag evidence channels that do not require GDB"
    tags = ["arbe", "ros", "public-evidence", "atomic"]
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "profile_path": {"type": "string"},
            "preflight_path": {"type": "string"},
            "runtime_schema_path": {"type": "string"},
            "topic_inventory_path": {"type": "string"},
            "output": {"type": "string"},
        },
        "additionalProperties": False,
    }
    output_schema: dict[str, Any] = {
        "type": "object",
        "required": ["schema_version", "status", "channels", "without_gdb"],
    }

    def run(
        self,
        *,
        profile_path: str = "",
        preflight_path: str = "",
        runtime_schema_path: str = "",
        topic_inventory_path: str = "",
        output: str = "",
        **_: Any,
    ) -> ModuleResult:
        try:
            profile = load_profile_mapping(profile_path) if profile_path else {}
            preflight = load_json_mapping(preflight_path) if preflight_path else {}
            runtime_schema = (
                load_json_mapping(runtime_schema_path) if runtime_schema_path else {}
            )
            topic_inventory = (
                load_json_mapping(topic_inventory_path) if topic_inventory_path else {}
            )
            payload = build_public_topic_plan(
                profile=profile,
                preflight=preflight,
                runtime_schema=runtime_schema,
                topic_inventory=topic_inventory,
            )
        except Exception as exc:  # noqa: BLE001 - external material boundary
            return ModuleResult.fail(
                f"public topic plan failed: {type(exc).__name__}: {exc}",
                module=self.name,
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
                    message=f"public topic plan output failed: {type(exc).__name__}: {exc}",
                    module=self.name,
                    data=payload,
                    artifacts=artifacts,
                )
        return ModuleResult(
            ok=payload.get("status") != "blocked",
            message=f"public-topic-plan:{payload.get('status', 'unknown')}",
            module=self.name,
            data=payload,
            artifacts=artifacts,
        )

    @classmethod
    def register_cli(cls, subparsers: Any) -> Any:
        parser = super().register_cli(subparsers)
        parser.add_argument("--profile-path", default="")
        parser.add_argument("--preflight-path", default="")
        parser.add_argument("--runtime-schema-path", default="")
        parser.add_argument("--topic-inventory-path", default="")
        parser.add_argument("--output", default="")
        return parser

    @classmethod
    def from_cli_args(cls, args: Any) -> "PublicTopicPlanModule":
        return cls()


__all__ = ["PublicTopicPlanModule"]
