# -*- coding: utf-8 -*-
"""Approval-gated adapter for formal existing-PID arbe GDB attach."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from ai.providers.cr60_harness import Cr60HarnessProvider
from engines.runtime_debug_plan import load_json_object, validate_runtime_debug_plan

from .base import BaseModule, ModuleResult


class RuntimeDebugAttachModule(BaseModule):
    """Attach a validated debug plan to a running formal visualization node."""

    name = "runtime-debug-attach"
    description = "Attach an approved source-bound GDB plan to an existing formal arbe PID"
    tags = ["runtime", "debug", "gdb", "attach", "formal", "provider", "approval-gated", "atomic"]
    requires_approval = True
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "harness_root": {"type": "string"},
            "profile": {"type": "string"},
            "bag": {"type": "string"},
            "debug_plan_path": {"type": "string"},
            "target_frame": {"type": "integer"},
            "radar_id": {"type": "integer"},
            "start_sec": {"type": "number"},
            "duration_sec": {"type": "number"},
            "node_pattern": {"type": "string"},
            "topic": {"type": "string"},
            "ros_master_uri": {"type": "string"},
            "replay": {"type": "boolean"},
            "wait_sec": {"type": "number"},
            "keep_remote_logs": {"type": "boolean"},
            "execute": {"type": "boolean"},
            "approved": {"type": "boolean"},
            "python_executable": {"type": "string"},
            "timeout_sec": {"type": "number"},
            "session_output": {"type": "string"},
            "output": {"type": "string"},
        },
        "required": ["harness_root", "profile", "bag", "debug_plan_path", "target_frame", "radar_id"],
        "additionalProperties": False,
    }
    output_schema: dict[str, Any] = {
        "type": "object",
        "required": ["schema_version", "status", "mode", "command"],
    }

    def run(
        self,
        *,
        harness_root: str,
        profile: str,
        bag: str,
        debug_plan_path: str,
        target_frame: int,
        radar_id: int,
        start_sec: float = 504.0,
        duration_sec: float = 22.0,
        node_pattern: str = "/radar{radar_id}_visualization_engine/arbe_visualization_engine",
        topic: str = "",
        ros_master_uri: str = "http://127.0.0.1:11311",
        replay: bool = False,
        wait_sec: float = 30.0,
        keep_remote_logs: bool = False,
        execute: bool = False,
        approved: bool = False,
        python_executable: str = "",
        timeout_sec: float = 3600.0,
        session_output: str = "",
        output: str = "",
        **_: Any,
    ) -> ModuleResult:
        try:
            plan = load_json_object(debug_plan_path, label="runtime_debug_plan")
            errors = validate_runtime_debug_plan(plan)
            if errors:
                return ModuleResult.fail(
                    "runtime debug plan invalid: " + "; ".join(errors),
                    module=self.name,
                )
            readiness = plan.get("readiness", {}) or {}
            if plan.get("status") == "blocked" or plan.get("execution_status") == "blocked" or (
                isinstance(readiness, Mapping) and readiness.get("status") == "blocked"
            ):
                return ModuleResult.fail(
                    "runtime debug plan is blocked; formal attach is refused",
                    module=self.name,
                    readiness=readiness,
                )
            event = plan.get("event", {}) or {}
            if isinstance(event, Mapping):
                plan_radar = event.get("radar_id")
                plan_frame = event.get("target_frame")
                if plan_radar not in (None, "") and int(plan_radar) != int(radar_id):
                    return ModuleResult.fail(
                        f"debug plan radar_id={plan_radar} does not match radar_id={radar_id}",
                        module=self.name,
                    )
                if plan_frame not in (None, "") and int(plan_frame) != int(target_frame):
                    return ModuleResult.fail(
                        f"debug plan target_frame={plan_frame} does not match target_frame={target_frame}",
                        module=self.name,
                    )
            provider = Cr60HarnessProvider(
                harness_root=harness_root,
                python_executable=python_executable,
                timeout_sec=timeout_sec,
            )
            payload = provider.run_gdb_attach_plan(
                profile=profile,
                bag=bag,
                debug_plan=debug_plan_path,
                target_frame=int(target_frame),
                radar_id=int(radar_id),
                start_sec=float(start_sec),
                duration_sec=float(duration_sec),
                node_pattern=node_pattern,
                topic=topic,
                ros_master_uri=ros_master_uri,
                replay=bool(replay),
                wait_sec=float(wait_sec),
                session_output=session_output,
                keep_remote_logs=bool(keep_remote_logs),
                execute=bool(execute and approved),
            )
            if execute and not approved and payload.get("status") == "planned":
                payload["status"] = "approval_required"
                payload["execute_requested"] = True
                payload["diagnostics"] = ["formal GDB attach requires explicit approved=true"]
            payload_status = str(payload.get("status", "failed"))
            if payload_status == "blocked":
                isolated_session_output = ""
                if str(session_output or "").strip():
                    original_session_path = Path(session_output).expanduser()
                    isolated_session_output = str(
                        original_session_path.with_name(
                            f"{original_session_path.stem}.isolated{original_session_path.suffix or '.json'}"
                        )
                    )
                payload["fallback"] = {
                    "capability": "runtime-debug-run",
                    "requires_approval": True,
                    "reason": "formal existing-PID attach was blocked; isolated launch-under-GDB is the configured fallback",
                    "params": {
                        "harness_root": harness_root,
                        "profile": profile,
                        "bag": bag,
                        "debug_plan_path": debug_plan_path,
                        "target_frame": int(target_frame),
                        "radar_id": int(radar_id),
                        "start_sec": float(start_sec),
                        "duration_sec": float(duration_sec),
                        "session_output": isolated_session_output,
                    },
                }
            if output:
                path = Path(output).expanduser().resolve()
                path.parent.mkdir(parents=True, exist_ok=True)
                payload["artifact_path"] = str(path)
                path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                output_artifacts = [str(path)]
            else:
                output_artifacts = []
        except (OSError, ValueError, TypeError, KeyError) as exc:
            return ModuleResult.fail(
                f"formal GDB attach failed: {type(exc).__name__}: {exc}",
                module=self.name,
            )
        status = str(payload.get("status", "failed"))
        bounded = payload
        if output:
            bounded = {
                key: payload.get(key)
                for key in (
                    "schema_version", "mode", "harness_root", "command", "command_display",
                    "execute_requested", "status", "artifacts", "session_output", "artifact_path",
                    "gdb_session_status", "gdb_evidence_status", "attach_status", "diagnostics",
                    "fallback", "blockers",
                )
                if key in payload
            }
        return ModuleResult(
            ok=status in {"planned", "approval_required", "completed", "completed_with_runtime_warnings"},
            message=f"runtime-debug-attach:{status}",
            module=self.name,
            data=bounded,
            artifacts=output_artifacts + list(payload.get("artifacts", []) or []),
        )

    @classmethod
    def register_cli(cls, subparsers: Any) -> Any:
        parser = super().register_cli(subparsers)
        parser.add_argument("--harness-root", required=True)
        parser.add_argument("--profile", required=True)
        parser.add_argument("--bag", required=True)
        parser.add_argument("--debug-plan-path", required=True)
        parser.add_argument("--target-frame", type=int, required=True)
        parser.add_argument("--radar-id", type=int, choices=[1, 2, 3, 4], required=True)
        parser.add_argument("--start-sec", type=float, default=504.0)
        parser.add_argument("--duration-sec", type=float, default=22.0)
        parser.add_argument("--node-pattern", default="/radar{radar_id}_visualization_engine/arbe_visualization_engine")
        parser.add_argument("--topic", default="")
        parser.add_argument("--ros-master-uri", default="http://127.0.0.1:11311")
        parser.add_argument("--replay", action="store_true")
        parser.add_argument("--wait-sec", type=float, default=30.0)
        parser.add_argument("--keep-remote-logs", action="store_true")
        parser.add_argument("--execute", action="store_true")
        parser.add_argument("--approved", action="store_true")
        parser.add_argument("--python-executable", default="")
        parser.add_argument("--timeout-sec", type=float, default=3600.0)
        parser.add_argument("--session-output", default="")
        parser.add_argument("--output", default="")
        return parser

    @classmethod
    def from_cli_args(cls, args: Any) -> "RuntimeDebugAttachModule":
        return cls()


__all__ = ["RuntimeDebugAttachModule"]
