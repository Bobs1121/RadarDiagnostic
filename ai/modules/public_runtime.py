# -*- coding: utf-8 -*-
"""Pi-visible normalizer for public arbe runtime capture rows."""
from __future__ import annotations

import json
import hashlib
from pathlib import Path
from typing import Any, Mapping, Sequence

from engines.arbe.public_runtime import (
    OBJECT_ASSOCIATION_MODES,
    OBJECT_VALIDITY_POLICIES,
    PublicRuntimeError,
    normalize_public_runtime,
    runtime_capture_from_topic_inventory,
)
from engines.arbe.ros_inventory import SCHEMA_VERSION as ROS_TOPIC_INVENTORY_SCHEMA

from .base import BaseModule, ModuleResult


def _json_object(text: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"expected JSON object: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise ValueError("expected JSON object")
    return value


def _json_array(text: str) -> list[Any]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"expected JSON array: {exc.msg}") from exc
    if not isinstance(value, list):
        raise ValueError("expected JSON array")
    return value


def _warning_names_from_schema(value: Mapping[str, Any] | None) -> list[str]:
    contract = value.get("warning_contract") if isinstance(value, Mapping) else None
    bits = contract.get("bits") if isinstance(contract, Mapping) else None
    if not isinstance(bits, Mapping):
        return []
    return [
        str(bits[key]).strip()
        for key in sorted(bits, key=lambda item: int(item) if str(item).isdigit() else 10**9)
        if str(bits[key]).strip()
    ]


class PublicRuntimeNormalizeModule(BaseModule):
    """Normalize public samples with strict or source-proven publication order."""

    name = "public-runtime-normalize"
    description = "归一化 arbe 公共运行时报警、自车和目标属性；支持 ros-topic-inventory 单消息样本"
    tags = ["arbe", "ros", "runtime", "objectlist", "frame", "atomic"]
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "capture_path": {
                "type": "string",
                "description": "Existing runtime capture or ros-topic-inventory.v1 artifact with bounded message samples.",
            },
            "topic_plan_path": {
                "type": "string",
                "description": "Optional public-topic-plan.v1 artifact; channel roles are used only when its preflight host/workspace identity matches the current preflight artifact.",
            },
            "warning_rows": {"type": "array", "items": {"type": "object"}},
            "radar_info_rows": {"type": "array", "items": {"type": "object"}},
            "object_rows": {"type": "array", "items": {"type": "object"}},
            "source_context": {"type": "object"},
            "warning_names": {"type": "array", "items": {"type": "string"}},
            "object_association_mode": {"type": "string", "enum": sorted(OBJECT_ASSOCIATION_MODES)},
            "object_validity_policy": {"type": "string", "enum": sorted(OBJECT_VALIDITY_POLICIES)},
            "preflight": {"type": "object"},
            "preflight_path": {"type": "string"},
            "runtime_schema_path": {"type": "string"},
            "output": {"type": "string"},
        },
        "anyOf": [
            {"required": ["capture_path"]},
            {"required": ["warning_rows"]},
            {"required": ["radar_info_rows"]},
            {"required": ["object_rows"]},
        ],
        "additionalProperties": False,
    }
    output_schema: dict[str, Any] = {
        "type": "object",
        "required": ["schema_version", "status", "snapshots", "unbound_objects", "association_policy"],
    }

    def run(
        self,
        *,
        capture_path: str = "",
        topic_plan_path: str = "",
        warning_rows: Sequence[Mapping[str, Any]] | None = None,
        radar_info_rows: Sequence[Mapping[str, Any]] | None = None,
        object_rows: Sequence[Mapping[str, Any]] | None = None,
        source_context: Mapping[str, Any] | None = None,
        warning_names: Sequence[str] | None = None,
        object_association_mode: str = "auto",
        object_validity_policy: str = "preserve",
        preflight: Mapping[str, Any] | None = None,
        preflight_path: str = "",
        runtime_schema_path: str = "",
        output: str = "",
        **_: Any,
    ) -> ModuleResult:
        try:
            capture_path_resolved = str(Path(capture_path).expanduser().resolve()) if capture_path else ""
            capture_bytes = Path(capture_path_resolved).read_bytes() if capture_path_resolved else b""
            capture_value = json.loads(capture_bytes) if capture_bytes else {}
            if not isinstance(capture_value, Mapping):
                raise ValueError("runtime capture root must be an object")
            capture = dict(capture_value)
            capture_sha256 = hashlib.sha256(capture_bytes).hexdigest() if capture_bytes else ""
            preflight_sha256 = ""
            if preflight is None and preflight_path:
                preflight_bytes = Path(preflight_path).expanduser().resolve().read_bytes()
                preflight_value = json.loads(preflight_bytes)
                if not isinstance(preflight_value, Mapping):
                    raise ValueError("preflight root must be an object")
                if preflight_value.get("schema_version") != "arbe-preflight.v1":
                    raise ValueError("preflight_path must point to arbe-preflight.v1")
                preflight = dict(preflight_value)
                preflight_sha256 = hashlib.sha256(preflight_bytes).hexdigest()
            if capture.get("schema_version") == ROS_TOPIC_INVENTORY_SCHEMA:
                topic_plan: Mapping[str, Any] | None = None
                topic_plan_sha256 = ""
                topic_plan_path_resolved = ""
                if topic_plan_path:
                    topic_plan_file = Path(topic_plan_path).expanduser().resolve()
                    topic_plan_bytes = topic_plan_file.read_bytes()
                    topic_plan_value = json.loads(topic_plan_bytes.decode("utf-8"))
                    if not isinstance(topic_plan_value, Mapping) or topic_plan_value.get("schema_version") != "public-topic-plan.v1":
                        raise ValueError("topic_plan_path must point to public-topic-plan.v1")
                    topic_plan = dict(topic_plan_value)
                    topic_plan_sha256 = hashlib.sha256(topic_plan_bytes).hexdigest()
                    topic_plan_path_resolved = str(topic_plan_file)
                capture = runtime_capture_from_topic_inventory(
                    capture,
                    inventory_path=capture_path_resolved,
                    inventory_sha256=capture_sha256,
                    topic_plan=topic_plan,
                    topic_plan_path=topic_plan_path_resolved,
                    topic_plan_sha256=topic_plan_sha256,
                    preflight=preflight,
                    preflight_sha256=preflight_sha256,
                )
            elif topic_plan_path:
                raise ValueError("topic_plan_path requires a ros-topic-inventory.v1 capture")
            resolved_warning_names = list(warning_names or [])
            if not resolved_warning_names:
                resolved_warning_names = [
                    str(item) for item in capture.get("warning_names", []) or [] if str(item).strip()
                ]
            if not resolved_warning_names and runtime_schema_path:
                schema_value = json.loads(
                    Path(runtime_schema_path).expanduser().read_text(encoding="utf-8")
                )
                if isinstance(schema_value, Mapping):
                    resolved_warning_names = _warning_names_from_schema(schema_value)
            payload = normalize_public_runtime(
                warning_rows=warning_rows if warning_rows is not None else capture.get("warning_rows", capture.get("warning")),
                radar_info_rows=radar_info_rows if radar_info_rows is not None else capture.get("radar_info_rows", capture.get("radar_info")),
                object_rows=object_rows if object_rows is not None else capture.get("object_rows", capture.get("objects")),
                source_context=source_context if source_context is not None else capture.get("source_context", {}),
                warning_names=resolved_warning_names,
                object_association_mode=object_association_mode,
                object_validity_policy=object_validity_policy,
                preflight=preflight if preflight is not None else capture.get("preflight", {}),
                capture_metadata=capture.get("capture_metadata"),
                capture_diagnostics=capture.get("diagnostics", []),
            )
        except (PublicRuntimeError, OSError, TypeError, ValueError) as exc:
            return ModuleResult.fail(
                f"public-runtime-normalize:failed: {exc}",
                module=self.name,
                error_type=type(exc).__name__,
            )
        artifacts: list[str] = []
        if output:
            path = Path(output).expanduser().resolve()
            protected_inputs = [capture_path, topic_plan_path, preflight_path, runtime_schema_path]
            if any(
                str(Path(value).expanduser().resolve()) == str(path)
                for value in protected_inputs
                if value
            ):
                return ModuleResult.fail(
                    "public-runtime-normalize:output_must_not_overwrite_input_artifact",
                    module=self.name,
                    data=payload,
                )
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            payload["artifact_path"] = str(path)
            artifacts.append(str(path))
        return ModuleResult(
            ok=payload["status"] != "blocked",
            message=f"public-runtime-normalize:{payload['status']}",
            module=self.name,
            artifacts=artifacts,
            data=payload,
        )

    @classmethod
    def register_cli(cls, subparsers: Any) -> Any:
        parser = super().register_cli(subparsers)
        parser.add_argument("--capture-path", default="")
        parser.add_argument(
            "--topic-plan-path",
            default="",
            help="Optional source-bound public-topic-plan.v1; needs the matching current preflight artifact.",
        )
        parser.add_argument("--warning-rows", type=_json_array, default=None)
        parser.add_argument("--radar-info-rows", type=_json_array, default=None)
        parser.add_argument("--object-rows", type=_json_array, default=None)
        parser.add_argument("--source-context", type=_json_object, default={})
        parser.add_argument("--warning-names", type=_json_array, default=None)
        parser.add_argument("--object-association-mode", choices=sorted(OBJECT_ASSOCIATION_MODES), default="auto")
        parser.add_argument("--object-validity-policy", choices=sorted(OBJECT_VALIDITY_POLICIES), default="preserve")
        parser.add_argument("--preflight", dest="preflight_path", default="")
        parser.add_argument("--runtime-schema", dest="runtime_schema_path", default="")
        parser.add_argument("--output", default="")
        return parser

    @classmethod
    def from_cli_args(cls, args: Any) -> "PublicRuntimeNormalizeModule":
        return cls()


__all__ = ["PublicRuntimeNormalizeModule"]
