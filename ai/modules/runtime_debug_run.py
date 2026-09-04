# -*- coding: utf-8 -*-
"""Approval-gated adapter that runs a source-bound isolated GDB plan."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from ai.providers.cr60_harness import Cr60HarnessProvider
from engines.runtime_debug_plan import load_json_object, validate_runtime_debug_plan

from .base import BaseModule, ModuleResult


class RuntimeDebugRunModule(BaseModule):
    """Execute the plan-bound harness runner only after explicit approval."""

    name = "runtime-debug-run"
    description = "Run one approved isolated ROS/GDB session from runtime-debug-plan.v1"
    tags = ["runtime", "debug", "gdb", "replay", "provider", "approval-gated"]
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
            "master_port": {"type": "integer"},
            "start_sec": {"type": "number"},
            "duration_sec": {"type": "number"},
            "session_output": {"type": "string"},
            "keep_remote_logs": {"type": "boolean"},
            "execute": {"type": "boolean"},
            "approved": {"type": "boolean"},
            "python_executable": {"type": "string"},
            "timeout_sec": {"type": "number"},
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
        master_port: int = 11322,
        start_sec: float = 504.0,
        duration_sec: float = 22.0,
        session_output: str = "",
        keep_remote_logs: bool = False,
        execute: bool = False,
        approved: bool = False,
        python_executable: str = "",
        timeout_sec: float = 3600.0,
        output: str = "",
        **_: Any,
    ) -> ModuleResult:
        try:
            plan = load_json_object(debug_plan_path, label="runtime_debug_plan")
            plan_errors = validate_runtime_debug_plan(plan)
            if plan_errors:
                return ModuleResult.fail(
                    "runtime debug plan invalid: " + "; ".join(plan_errors),
                    module=self.name,
                )
            plan_readiness = plan.get("readiness", {}) or {}
            if plan.get("status") == "blocked" or plan.get("execution_status") == "blocked" or (
                isinstance(plan_readiness, Mapping) and plan_readiness.get("status") == "blocked"
            ):
                return ModuleResult.fail(
                    "runtime debug plan is blocked; resolve readiness gates before execution",
                    module=self.name,
                    readiness=plan_readiness,
                )
            plan_event = plan.get("event", {}) or {}
            if isinstance(plan_event, Mapping):
                plan_radar = plan_event.get("radar_id")
                plan_frame = plan_event.get("target_frame")
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
            payload = provider.run_gdb_plan(
                profile=profile,
                bag=bag,
                debug_plan=debug_plan_path,
                target_frame=int(target_frame),
                radar_id=int(radar_id),
                master_port=int(master_port),
                start_sec=float(start_sec),
                duration_sec=float(duration_sec),
                session_output=session_output,
                keep_remote_logs=bool(keep_remote_logs),
                execute=bool(execute and approved),
            )
            if execute and not approved and payload.get("status") == "planned":
                payload["status"] = "approval_required"
                payload["diagnostics"] = ["runtime GDB execution requires explicit approved=true"]
            if output and payload.get("status") not in {"blocked", "failed"}:
                path = Path(output).expanduser().resolve()
                path.parent.mkdir(parents=True, exist_ok=True)
                payload["artifact_path"] = str(path)
                path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                artifacts = [str(path)]
            else:
                artifacts = []
        except (OSError, ValueError, TypeError) as exc:
            return ModuleResult.fail(
                f"runtime debug run failed: {type(exc).__name__}: {exc}",
                module=self.name,
            )
        status = str(payload.get("status", "failed"))
        # Keep the Pi/tool response bounded.  The complete GDB transcript is
        # intentionally preserved in the session artifact and, when requested,
        # in ``output``; returning it inline would make a normal conversation
        # exceed context limits and would encourage consumers to treat a
        # transcript as structured evidence.  This summary still carries the
        # execution state, diagnostics, and artifact paths needed for the next
        # atomic tool.
        result_data: dict[str, Any] = payload
        if output and status not in {"blocked", "failed"}:
            result_data = {
                key: payload.get(key)
                for key in (
                    "schema_version",
                    "mode",
                    "harness_root",
                    "command",
                    "command_display",
                    "execute_requested",
                    "status",
                    "artifacts",
                    "session_output",
                    "artifact_path",
                    "gdb_session_status",
                    "gdb_evidence_status",
                    "diagnostics",
                )
                if key in payload
            }
        return ModuleResult(
            ok=status in {"planned", "approval_required", "completed", "completed_with_case_failures", "completed_with_runtime_warnings"},
            message=f"runtime-debug-run:{status}",
            module=self.name,
            data=result_data,
            artifacts=artifacts + list(payload.get("artifacts", []) or []),
        )

    @classmethod
    def register_cli(cls, subparsers: Any) -> Any:
        parser = super().register_cli(subparsers)
        parser.add_argument("--harness-root", required=True)
        parser.add_argument("--profile", required=True)
        parser.add_argument("--bag", required=True)
        parser.add_argument("--debug-plan-path", required=True)
        parser.add_argument("--target-frame", type=int, required=True)
        parser.add_argument("--radar-id", type=int, required=True)
        parser.add_argument("--master-port", type=int, default=11322)
        parser.add_argument("--start-sec", type=float, default=504.0)
        parser.add_argument("--duration-sec", type=float, default=22.0)
        parser.add_argument("--session-output", default="")
        parser.add_argument("--keep-remote-logs", action="store_true")
        parser.add_argument("--execute", action="store_true")
        parser.add_argument("--approved", action="store_true")
        parser.add_argument("--python-executable", default="")
        parser.add_argument("--timeout-sec", type=float, default=3600.0)
        parser.add_argument("--output", default="")
        return parser

    @classmethod
    def from_cli_args(cls, args: Any) -> "RuntimeDebugRunModule":
        return cls()


__all__ = ["RuntimeDebugRunModule"]
