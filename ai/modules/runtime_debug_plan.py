# -*- coding: utf-8 -*-
"""Pi-callable planner for a provenance-bound runtime debug session."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from engines.runtime_debug_plan import build_runtime_debug_plan, load_json_object

from .base import BaseModule, ModuleResult


class RuntimeDebugPlanModule(BaseModule):
    """Build a plan; never starts ROS, replay or GDB."""

    name = "runtime-debug-plan"
    description = "Build a source/data-bound replay and GDB readiness plan from one alarm event"
    tags = ["runtime", "debug", "gdb", "plan", "atomic"]
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "bundle": {"type": "object"},
            "bundle_path": {"type": "string"},
            "event_id": {"type": "string"},
            "event_index": {"type": "integer"},
            "runtime_mode": {"type": "string"},
            "preflight": {"type": "object"},
            "preflight_path": {"type": "string"},
            "event_code_path": {"type": "object"},
            "event_code_path_path": {"type": "string"},
            "source_context": {"type": "object"},
            "binary_context": {"type": "object"},
            "permissions": {"type": "object"},
            "output": {"type": "string"},
        },
        "additionalProperties": False,
    }
    output_schema: dict[str, Any] = {
        "type": "object",
        "required": ["schema_version", "status", "execution_status", "event", "readiness", "breakpoints", "gdb_commands"],
    }

    def run(
        self,
        *,
        bundle: Mapping[str, Any] | None = None,
        bundle_path: str = "",
        event_id: str = "",
        event_index: int = 0,
        runtime_mode: str = "auto",
        preflight: Mapping[str, Any] | None = None,
        preflight_path: str = "",
        event_code_path: Mapping[str, Any] | None = None,
        event_code_path_path: str = "",
        source_context: Mapping[str, Any] | None = None,
        binary_context: Mapping[str, Any] | None = None,
        permissions: Mapping[str, Any] | None = None,
        output: str = "",
        **_: Any,
    ) -> ModuleResult:
        try:
            static_bundle = dict(bundle) if isinstance(bundle, Mapping) else load_json_object(bundle_path, label="bundle") if bundle_path else None
            if static_bundle is None:
                return ModuleResult.fail("bundle or bundle_path is required", module=self.name)
            effective_preflight = dict(preflight) if isinstance(preflight, Mapping) else load_json_object(preflight_path, label="preflight") if preflight_path else None
            effective_event_code_path = (
                dict(event_code_path)
                if isinstance(event_code_path, Mapping)
                else load_json_object(event_code_path_path, label="event_code_path")
                if event_code_path_path
                else None
            )
            payload = build_runtime_debug_plan(
                static_bundle,
                event_id=event_id,
                event_index=int(event_index),
                runtime_mode=runtime_mode,
                preflight=effective_preflight,
                source_context=source_context,
                binary_context=binary_context,
                permissions=permissions,
                event_code_path=effective_event_code_path,
            )
            artifact_paths: list[str] = []
            if str(output or "").strip():
                path = Path(output).expanduser().resolve()
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                artifact_paths.append(str(path))
                payload["artifact_path"] = str(path)
        except (OSError, ValueError, TypeError) as exc:
            return ModuleResult.fail(
                f"runtime debug plan failed: {type(exc).__name__}: {exc}",
                module=self.name,
            )
        status = str(payload.get("status", "blocked"))
        return ModuleResult(
            ok=status not in {"blocked", "failed"},
            message=f"runtime-debug-plan:{status}",
            module=self.name,
            data=payload,
            artifacts=artifact_paths,
        )

    @classmethod
    def register_cli(cls, subparsers: Any) -> Any:
        parser = super().register_cli(subparsers)
        parser.add_argument("--bundle-path", required=True)
        parser.add_argument("--event-id", default="")
        parser.add_argument("--event-index", type=int, default=0)
        parser.add_argument("--runtime-mode", default="auto")
        parser.add_argument("--preflight-path", default="")
        parser.add_argument("--event-code-path", dest="event_code_path_path", default="")
        parser.add_argument("--source-context", default="", help="JSON source context supplement")
        parser.add_argument("--binary-context", default="", help="JSON binary context")
        parser.add_argument("--permissions", default="", help="JSON approval/permission state")
        parser.add_argument("--output", default="")
        return parser

    @classmethod
    def from_cli_args(cls, args: Any) -> "RuntimeDebugPlanModule":
        for name in ("source_context", "binary_context", "permissions"):
            value = str(getattr(args, name, "") or "")
            if not value:
                setattr(args, name, None)
                continue
            parsed = json.loads(value)
            if not isinstance(parsed, dict):
                raise ValueError(f"{name} must be a JSON object")
            setattr(args, name, parsed)
        return cls()


__all__ = ["RuntimeDebugPlanModule"]
