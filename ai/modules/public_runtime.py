# -*- coding: utf-8 -*-
"""Pi-visible normalizer for public arbe runtime capture rows."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from engines.arbe.public_runtime import (
    OBJECT_ASSOCIATION_MODES,
    OBJECT_VALIDITY_POLICIES,
    PublicRuntimeError,
    load_capture,
    normalize_public_runtime,
)

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
    description = "归一化 arbe 公共运行时报警、自车和目标属性快照"
    tags = ["arbe", "ros", "runtime", "objectlist", "frame", "atomic"]
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "capture_path": {"type": "string"},
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
            capture = load_capture(capture_path) if capture_path else {}
            if preflight is None and preflight_path:
                preflight_value = json.loads(
                    Path(preflight_path).expanduser().read_text(encoding="utf-8")
                )
                if not isinstance(preflight_value, Mapping):
                    raise ValueError("preflight root must be an object")
                preflight = dict(preflight_value)
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
