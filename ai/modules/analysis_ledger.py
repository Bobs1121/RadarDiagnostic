# -*- coding: utf-8 -*-
"""Pi-visible atomic modules for the deterministic Analysis Ledger."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from engines.analysis_ledger import (
    AnalysisLedger,
    LedgerConflict,
    LedgerError,
    LedgerNotFound,
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


class _LedgerModule(BaseModule):
    default_ledger_root = "outputs/analysis_runs"

    def __init__(self, *, project_root: str | Path | None = None) -> None:
        self._project_root = (
            Path(project_root).expanduser().resolve()
            if project_root
            else Path(__file__).resolve().parents[2]
        )

    def _ledger(self, ledger_root: str) -> AnalysisLedger:
        path = Path(str(ledger_root or self.default_ledger_root)).expanduser()
        if not path.is_absolute():
            path = self._project_root / path
        return AnalysisLedger(path.resolve())

    def _failure(self, operation: str, exc: Exception) -> ModuleResult:
        status = (
            "not_found"
            if isinstance(exc, LedgerNotFound)
            else "conflict"
            if isinstance(exc, LedgerConflict)
            else "failed"
        )
        return ModuleResult.fail(
            f"{operation}:{status}: {exc}",
            module=self.name,
            status=status,
            error_type=type(exc).__name__,
        )


class AnalysisRunCreateModule(_LedgerModule):
    name = "analysis-run-create"
    description = "Create one durable AnalysisRun for progressive evidence and debug work"
    tags = ["analysis", "ledger", "run", "create", "atomic", "local-write"]
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "ledger_root": {"type": "string"},
            "run_id": {"type": "string"},
            "owner": {"type": "string"},
            "goal": {"type": "object"},
            "question": {"type": "string"},
            "customer_claim": {"type": "string"},
            "expected": {"type": "string"},
            "binding": {"type": "object"},
            "policy": {"type": "object"},
            "artifact_refs": {"type": "array", "items": {}},
        },
        "anyOf": [{"required": ["goal"]}, {"required": ["question"]}],
        "additionalProperties": False,
    }
    output_schema = {
        "type": "object",
        "required": ["schema_version", "run_id", "goal", "status", "artifact_path"],
    }

    def run(
        self,
        *,
        ledger_root: str = "",
        run_id: str = "",
        owner: str = "",
        goal: Mapping[str, Any] | None = None,
        question: str = "",
        customer_claim: str = "",
        expected: str = "",
        binding: Mapping[str, Any] | None = None,
        policy: Mapping[str, Any] | None = None,
        artifact_refs: Sequence[Any] | None = None,
        **_: Any,
    ) -> ModuleResult:
        normalized_goal = dict(goal or {})
        if question:
            normalized_goal.setdefault("question", question)
        if customer_claim:
            normalized_goal.setdefault("customer_claim", customer_claim)
        if expected:
            normalized_goal.setdefault("expected", expected)
        try:
            payload = self._ledger(ledger_root).create_run(
                run_id=run_id,
                owner=owner,
                goal=normalized_goal,
                binding=binding,
                policy=policy,
                artifact_refs=artifact_refs,
            )
        except (LedgerError, OSError, TypeError, ValueError) as exc:
            return self._failure("analysis-run-create", exc)
        return ModuleResult(
            ok=True,
            message=f"analysis-run-create:{payload['run_id']}",
            module=self.name,
            artifacts=[payload["artifact_path"]],
            data=payload,
        )

    @classmethod
    def register_cli(cls, subparsers: Any) -> Any:
        parser = super().register_cli(subparsers)
        parser.add_argument("--ledger-root", default=cls.default_ledger_root)
        parser.add_argument("--run-id", default="")
        parser.add_argument("--owner", default="")
        parser.add_argument("--question", required=True)
        parser.add_argument("--customer-claim", default="")
        parser.add_argument("--expected", default="")
        parser.add_argument("--binding", type=_json_object, default={})
        parser.add_argument("--policy", type=_json_object, default={})
        parser.add_argument("--artifact-refs", type=_json_array, default=[])
        return parser


class AnalysisRunReadModule(_LedgerModule):
    name = "analysis-run-read"
    description = "Read one AnalysisRun summary and optionally its durable entities"
    tags = ["analysis", "ledger", "run", "read", "atomic", "read-only"]
    input_schema = {
        "type": "object",
        "properties": {
            "ledger_root": {"type": "string"},
            "run_id": {"type": "string"},
            "include_entities": {"type": "boolean"},
        },
        "required": ["run_id"],
        "additionalProperties": False,
    }
    output_schema = {
        "type": "object",
        "required": ["schema_version", "run_id", "summary", "artifact_path"],
    }

    def run(
        self,
        *,
        run_id: str,
        ledger_root: str = "",
        include_entities: bool = False,
        **_: Any,
    ) -> ModuleResult:
        try:
            payload = self._ledger(ledger_root).read_run(
                run_id, include_entities=bool(include_entities)
            )
        except (LedgerError, OSError, TypeError, ValueError) as exc:
            return self._failure("analysis-run-read", exc)
        return ModuleResult(
            ok=True,
            message=f"analysis-run-read:{run_id}",
            module=self.name,
            artifacts=[payload["artifact_path"]],
            data=payload,
        )

    @classmethod
    def register_cli(cls, subparsers: Any) -> Any:
        parser = super().register_cli(subparsers)
        parser.add_argument("--ledger-root", default=cls.default_ledger_root)
        parser.add_argument("--run-id", required=True)
        parser.add_argument("--include-entities", action="store_true")
        return parser


class AnalysisRunUpdateModule(_LedgerModule):
    name = "analysis-run-update"
    description = "Update AnalysisRun status, stage, and explicit run metrics"
    tags = ["analysis", "ledger", "run", "update", "metrics", "atomic", "local-write"]
    input_schema = {
        "type": "object",
        "properties": {
            "ledger_root": {"type": "string"},
            "run_id": {"type": "string"},
            "status": {
                "type": "string",
                "enum": ["created", "running", "partial", "blocked", "failed", "completed"],
            },
            "current_stage": {"type": "string"},
            "metrics": {"type": "object"},
            "metric_mode": {"type": "string", "enum": ["merge", "increment"]},
            "actor": {"type": "string"},
            "binding": {"type": "object"},
            "artifact_refs": {"type": "array", "items": {}},
        },
        "required": ["run_id"],
        "additionalProperties": False,
    }
    output_schema = {
        "type": "object",
        "required": ["schema_version", "run_id", "status", "metrics", "summary"],
    }

    def run(
        self,
        *,
        run_id: str,
        ledger_root: str = "",
        status: str = "",
        current_stage: str = "",
        metrics: Mapping[str, Any] | None = None,
        metric_mode: str = "merge",
        actor: str = "tool",
        binding: Mapping[str, Any] | None = None,
        artifact_refs: Sequence[Any] | None = None,
        **_: Any,
    ) -> ModuleResult:
        try:
            payload = self._ledger(ledger_root).update_run(
                run_id,
                status=status,
                current_stage=current_stage,
                metrics=metrics,
                metric_mode=metric_mode,
                actor=actor,
                binding=binding,
                artifact_refs=artifact_refs,
            )
        except (LedgerError, OSError, TypeError, ValueError) as exc:
            return self._failure("analysis-run-update", exc)
        return ModuleResult(
            ok=True,
            message=f"analysis-run-update:{run_id}",
            module=self.name,
            artifacts=[payload["artifact_path"]],
            data=payload,
        )

    @classmethod
    def register_cli(cls, subparsers: Any) -> Any:
        parser = super().register_cli(subparsers)
        parser.add_argument("--ledger-root", default=cls.default_ledger_root)
        parser.add_argument("--run-id", required=True)
        parser.add_argument("--status", default="")
        parser.add_argument("--current-stage", default="")
        parser.add_argument("--metrics", type=_json_object, default={})
        parser.add_argument("--metric-mode", choices=["merge", "increment"], default="merge")
        parser.add_argument("--actor", default="tool")
        parser.add_argument("--binding", type=_json_object, default={})
        parser.add_argument("--artifact-refs", type=_json_array, default=[])
        return parser


class AnalysisStepRecordModule(_LedgerModule):
    name = "analysis-step-record"
    description = "Begin or complete one visible AnalysisStep in an AnalysisRun"
    tags = ["analysis", "ledger", "step", "atomic", "local-write"]
    input_schema = {
        "type": "object",
        "properties": {
            "ledger_root": {"type": "string"},
            "action": {"type": "string", "enum": ["begin", "complete"]},
            "run_id": {"type": "string"},
            "step_id": {"type": "string"},
            "stage": {"type": "string"},
            "status": {
                "type": "string",
                "enum": ["completed", "partial", "blocked", "failed", "skipped"],
            },
            "created_by": {"type": "string"},
            "actor": {"type": "string"},
            "input_artifact_refs": {"type": "array", "items": {}},
            "output_artifact_refs": {"type": "array", "items": {}},
            "tool_calls": {"type": "array", "items": {}},
            "observations": {"type": "array", "items": {}},
            "gaps": {"type": "array", "items": {}},
            "conflicts": {"type": "array", "items": {}},
            "user_visible_summary": {"type": "string"},
            "next_action_candidates": {"type": "array", "items": {}},
            "metrics": {"type": "object"},
        },
        "required": ["action", "run_id"],
        "additionalProperties": False,
    }
    output_schema = {
        "type": "object",
        "required": ["schema_version", "step_id", "run_id", "stage", "status"],
    }

    def run(
        self,
        *,
        action: str,
        run_id: str,
        ledger_root: str = "",
        step_id: str = "",
        stage: str = "",
        status: str = "completed",
        created_by: str = "tool",
        actor: str = "tool",
        input_artifact_refs: Sequence[Any] | None = None,
        output_artifact_refs: Sequence[Any] | None = None,
        tool_calls: Sequence[Any] | None = None,
        observations: Sequence[Any] | None = None,
        gaps: Sequence[Any] | None = None,
        conflicts: Sequence[Any] | None = None,
        user_visible_summary: str = "",
        next_action_candidates: Sequence[Any] | None = None,
        metrics: Mapping[str, Any] | None = None,
        **_: Any,
    ) -> ModuleResult:
        operation = str(action or "").strip()
        try:
            ledger = self._ledger(ledger_root)
            if operation == "begin":
                if not stage:
                    raise ValueError("stage is required when action=begin")
                payload = ledger.begin_step(
                    run_id,
                    step_id=step_id,
                    stage=stage,
                    created_by=created_by,
                    input_artifact_refs=input_artifact_refs,
                    tool_calls=tool_calls,
                    metrics=metrics,
                )
            elif operation == "complete":
                if not step_id:
                    raise ValueError("step_id is required when action=complete")
                payload = ledger.complete_step(
                    run_id,
                    step_id,
                    status=status,
                    actor=actor,
                    output_artifact_refs=output_artifact_refs,
                    observations=observations,
                    gaps=gaps,
                    conflicts=conflicts,
                    user_visible_summary=user_visible_summary,
                    next_action_candidates=next_action_candidates,
                    metrics=metrics,
                )
            else:
                raise ValueError("action must be begin or complete")
        except (LedgerError, OSError, TypeError, ValueError) as exc:
            return self._failure("analysis-step-record", exc)
        return ModuleResult(
            ok=True,
            message=f"analysis-step-record:{operation}:{payload['step_id']}",
            module=self.name,
            artifacts=[payload["artifact_path"], payload["run_artifact_path"]],
            data=payload,
        )

    @classmethod
    def register_cli(cls, subparsers: Any) -> Any:
        parser = super().register_cli(subparsers)
        parser.add_argument("--ledger-root", default=cls.default_ledger_root)
        parser.add_argument("--action", required=True, choices=["begin", "complete"])
        parser.add_argument("--run-id", required=True)
        parser.add_argument("--step-id", default="")
        parser.add_argument("--stage", default="")
        parser.add_argument("--status", default="completed")
        parser.add_argument("--created-by", default="tool")
        parser.add_argument("--actor", default="tool")
        parser.add_argument("--input-artifact-refs", type=_json_array, default=[])
        parser.add_argument("--output-artifact-refs", type=_json_array, default=[])
        parser.add_argument("--tool-calls", type=_json_array, default=[])
        parser.add_argument("--observations", type=_json_array, default=[])
        parser.add_argument("--gaps", type=_json_array, default=[])
        parser.add_argument("--conflicts", type=_json_array, default=[])
        parser.add_argument("--summary", dest="user_visible_summary", default="")
        parser.add_argument("--next-actions", dest="next_action_candidates", type=_json_array, default=[])
        parser.add_argument("--metrics", type=_json_object, default={})
        return parser


class AnalysisClaimAppendModule(_LedgerModule):
    name = "analysis-claim-append"
    description = "Append one evidence-bound engineering Claim to an AnalysisRun"
    tags = ["analysis", "ledger", "claim", "evidence", "atomic", "local-write"]
    input_schema = {
        "type": "object",
        "properties": {
            "ledger_root": {"type": "string"},
            "run_id": {"type": "string"},
            "step_id": {"type": "string"},
            "claim_id": {"type": "string"},
            "scope": {"type": "string"},
            "statement": {"type": "string"},
            "status": {
                "type": "string",
                "enum": ["observed", "derived", "inferred", "contradicted", "not_available"],
            },
            "created_by": {"type": "string", "enum": ["tool", "ai", "user"]},
            "evidence_refs": {"type": "array", "items": {}},
            "assumptions": {"type": "array", "items": {}},
            "conflicts": {"type": "array", "items": {}},
            "binding": {"type": "object"},
        },
        "required": ["run_id", "scope", "statement", "status", "created_by"],
        "additionalProperties": False,
    }
    output_schema = {
        "type": "object",
        "required": ["schema_version", "claim_id", "run_id", "statement", "status"],
    }

    def run(
        self,
        *,
        run_id: str,
        scope: str,
        statement: str,
        status: str,
        created_by: str,
        ledger_root: str = "",
        step_id: str = "",
        claim_id: str = "",
        evidence_refs: Sequence[Any] | None = None,
        assumptions: Sequence[Any] | None = None,
        conflicts: Sequence[Any] | None = None,
        binding: Mapping[str, Any] | None = None,
        **_: Any,
    ) -> ModuleResult:
        try:
            payload = self._ledger(ledger_root).append_claim(
                run_id,
                step_id=step_id,
                claim_id=claim_id,
                scope=scope,
                statement=statement,
                status=status,
                created_by=created_by,
                evidence_refs=evidence_refs,
                assumptions=assumptions,
                conflicts=conflicts,
                binding=binding,
            )
        except (LedgerError, OSError, TypeError, ValueError) as exc:
            return self._failure("analysis-claim-append", exc)
        return ModuleResult(
            ok=True,
            message=f"analysis-claim-append:{payload['claim_id']}",
            module=self.name,
            artifacts=[payload["artifact_path"], payload["run_artifact_path"]],
            data=payload,
        )

    @classmethod
    def register_cli(cls, subparsers: Any) -> Any:
        parser = super().register_cli(subparsers)
        parser.add_argument("--ledger-root", default=cls.default_ledger_root)
        parser.add_argument("--run-id", required=True)
        parser.add_argument("--step-id", default="")
        parser.add_argument("--claim-id", default="")
        parser.add_argument("--scope", required=True)
        parser.add_argument("--statement", required=True)
        parser.add_argument("--status", required=True)
        parser.add_argument("--created-by", required=True)
        parser.add_argument("--evidence-refs", type=_json_array, default=[])
        parser.add_argument("--assumptions", type=_json_array, default=[])
        parser.add_argument("--conflicts", type=_json_array, default=[])
        parser.add_argument("--binding", type=_json_object, default={})
        return parser


__all__ = [
    "AnalysisClaimAppendModule",
    "AnalysisRunCreateModule",
    "AnalysisRunReadModule",
    "AnalysisRunUpdateModule",
    "AnalysisStepRecordModule",
]
