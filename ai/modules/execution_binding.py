"""Pi capability that turns an approved plan into an execution binding."""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Mapping

from engines.arbe.execution_binding import (
    REQUIRED_IDENTITY_FIELDS,
    build_execution_binding,
    derive_execution_identity,
)

from .base import BaseModule, ModuleResult


def _load_object(value: Mapping[str, Any] | None, path: str) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if not path:
        return {}
    try:
        payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def _identity_from_inputs(
    identity: Mapping[str, Any] | None,
    preflight: Mapping[str, Any] | None,
    source_context: Mapping[str, Any] | None,
) -> tuple[dict[str, str], dict[str, str]]:
    return derive_execution_identity(
        identity=identity,
        preflight=preflight,
        source_context=source_context,
    )


class ExecutionBindingModule(BaseModule):
    """Create a plan-bound binding without executing replay or SSH."""

    name = "arbe-execution-binding"
    description = "Create an approved data/source/binary/session binding for arbe execution"
    tags = ["arbe", "execution", "binding", "approval", "provenance", "atomic"]
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "plan": {"type": "object"},
            "plan_path": {"type": "string"},
            "identity": {"type": "object"},
            "preflight": {"type": "object"},
            "preflight_path": {"type": "string"},
            "source_context": {"type": "object"},
            "source_context_path": {"type": "string"},
            "approval_id": {"type": "string"},
            "approved": {"type": "boolean"},
            "run_id": {"type": "string"},
            "output": {"type": "string"},
        },
        "additionalProperties": False,
    }
    output_schema: dict[str, Any] = {
        "type": "object",
        "required": ["schema_version", "status"],
    }

    def run(
        self,
        *,
        plan: Mapping[str, Any] | None = None,
        plan_path: str = "",
        identity: Mapping[str, Any] | None = None,
        preflight: Mapping[str, Any] | None = None,
        preflight_path: str = "",
        source_context: Mapping[str, Any] | None = None,
        source_context_path: str = "",
        approval_id: str = "",
        approved: bool = False,
        run_id: str = "",
        output: str = "",
        **_: Any,
    ) -> ModuleResult:
        effective_plan = _load_object(plan, plan_path)
        if isinstance(effective_plan.get("execution_plan"), Mapping):
            effective_plan = dict(effective_plan["execution_plan"])
        effective_preflight = _load_object(preflight, preflight_path)
        effective_source_context = _load_object(source_context, source_context_path)
        if not effective_plan:
            return ModuleResult(
                ok=True,
                message="arbe-execution-binding:blocked",
                module=self.name,
                data={
                    "schema_version": "arbe-execution-binding.v1",
                    "status": "blocked",
                    "diagnostics": ["execution_plan_missing"],
                },
            )
        effective_run_id = str(run_id or "").strip() or f"attempt-{uuid.uuid4().hex[:12]}"
        effective_identity, identity_provenance = _identity_from_inputs(
            identity, effective_preflight, effective_source_context
        )
        identity_conflicts = str(identity_provenance.get("__conflicts__") or "").strip()
        missing = [key for key, value in effective_identity.items() if not value]
        if not approved:
            return ModuleResult(
                ok=True,
                message="arbe-execution-binding:approval_required",
                module=self.name,
                data={
                    "schema_version": "arbe-execution-binding.v1",
                    "status": "approval_required",
                    "run_id": effective_run_id,
                    "plan": effective_plan,
                    "missing_identity": missing,
                    "identity_conflicts": identity_conflicts.split(";") if identity_conflicts else [],
                    "identity_provenance": identity_provenance,
                    "diagnostics": ["approved=true is required after the user reviews the plan"],
                },
            )
        if identity_conflicts:
            return ModuleResult(
                ok=True,
                message="arbe-execution-binding:identity_conflict",
                module=self.name,
                data={
                    "schema_version": "arbe-execution-binding.v1",
                    "status": "blocked",
                    "run_id": effective_run_id,
                    "missing_identity": missing,
                    "identity_conflicts": identity_conflicts.split(";"),
                    "identity_provenance": identity_provenance,
                    "diagnostics": ["identity_sources_conflict_live_preflight_recheck_required"],
                },
            )
        if missing:
            return ModuleResult(
                ok=True,
                message="arbe-execution-binding:blocked",
                module=self.name,
                data={
                    "schema_version": "arbe-execution-binding.v1",
                    "status": "blocked",
                    "run_id": effective_run_id,
                    "missing_identity": missing,
                    "identity_provenance": identity_provenance,
                    "diagnostics": ["current data/source/binary/config/session identity is incomplete"],
                },
            )
        effective_approval_id = str(approval_id or "").strip() or f"approval-{effective_run_id}"
        try:
            binding = build_execution_binding(
                plan=effective_plan,
                identity=effective_identity,
                approval_id=effective_approval_id,
                approved=True,
                run_id=effective_run_id,
            )
        except (TypeError, ValueError) as exc:
            return ModuleResult.fail(
                f"execution binding failed: {type(exc).__name__}: {exc}", module=self.name
            )
        payload = {
            **binding,
            "status": "approved",
            "approval_source": "approved_flag",
            "identity_provenance": identity_provenance,
        }
        artifacts: list[str] = []
        if str(output or "").strip():
            path = Path(output).expanduser().resolve()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            payload["artifact_path"] = str(path)
            artifacts.append(str(path))
        return ModuleResult(
            ok=True,
            message="arbe-execution-binding:approved",
            module=self.name,
            artifacts=artifacts,
            data=payload,
        )

    @classmethod
    def register_cli(cls, subparsers: Any) -> Any:
        parser = super().register_cli(subparsers)
        parser.add_argument("--plan-path", default="")
        parser.add_argument("--preflight-path", default="")
        parser.add_argument("--identity", default="", help="JSON identity object")
        parser.add_argument("--source-context", default="", help="JSON source context")
        parser.add_argument("--source-context-path", default="")
        parser.add_argument("--approval-id", default="")
        parser.add_argument("--approved", action="store_true")
        parser.add_argument("--run-id", default="")
        parser.add_argument("--output", default="")
        return parser

    @classmethod
    def from_cli_args(cls, args: Any) -> "ExecutionBindingModule":
        for name in ("identity", "source_context"):
            value = str(getattr(args, name, "") or "")
            if value:
                setattr(args, name, json.loads(value))
            else:
                setattr(args, name, None)
        return cls()


__all__ = ["ExecutionBindingModule"]
