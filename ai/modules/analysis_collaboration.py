"""Pi-visible atomic modules for collaborative evidence review.

These modules persist hypotheses, debug experiments and manual observations in
the existing AnalysisLedger.  They do not run a command, evaluate a feature
rule or promote user text to runtime evidence.
"""
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


class _CollaborationModule(BaseModule):
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


class AnalysisHypothesisRecordModule(_CollaborationModule):
    name = "analysis-hypothesis-record"
    description = "Create or update one evidence-bound root-cause hypothesis"
    tags = ["analysis", "hypothesis", "collaboration", "atomic", "local-write"]
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "ledger_root": {"type": "string"},
            "hypothesis_id": {"type": "string"},
            "category": {"type": "string"},
            "statement": {"type": "string"},
            "status": {"type": "string", "enum": ["", "open", "testing", "supported", "weakened", "rejected", "confirmed_by_user"]},
            "rank": {"type": ["integer", "null"]},
            "confidence_band": {"type": "string", "enum": ["", "low", "medium", "high", "unknown"]},
            "supporting_claim_refs": {"type": "array", "items": {}},
            "contradicting_claim_refs": {"type": "array", "items": {}},
            "required_evidence": {"type": "array", "items": {}},
            "experiment_refs": {"type": "array", "items": {}},
            "binding": {"type": "object"},
            "reason": {"type": "string"},
            "actor": {"type": "string", "enum": ["tool", "ai", "user", "pi"]},
            "run_id": {"type": "string"},
        },
        "required": ["run_id"],
        "additionalProperties": False,
    }
    output_schema = {
        "type": "object",
        "required": ["schema_version", "hypothesis_id", "run_id", "status", "history", "artifact_path"],
    }

    def run(
        self,
        *,
        run_id: str,
        ledger_root: str = "",
        hypothesis_id: str = "",
        category: str = "",
        statement: str = "",
        status: str = "",
        rank: int | None = None,
        confidence_band: str = "",
        supporting_claim_refs: Sequence[Any] | None = None,
        contradicting_claim_refs: Sequence[Any] | None = None,
        required_evidence: Sequence[Any] | None = None,
        experiment_refs: Sequence[Any] | None = None,
        binding: Mapping[str, Any] | None = None,
        reason: str = "",
        actor: str = "tool",
        **_: Any,
    ) -> ModuleResult:
        try:
            payload = self._ledger(ledger_root).upsert_hypothesis(
                run_id,
                hypothesis_id=hypothesis_id,
                category=category,
                statement=statement,
                status=status,
                rank=rank,
                confidence_band=confidence_band,
                supporting_claim_refs=supporting_claim_refs,
                contradicting_claim_refs=contradicting_claim_refs,
                required_evidence=required_evidence,
                experiment_refs=experiment_refs,
                binding=binding,
                reason=reason,
                actor=actor,
            )
        except (LedgerError, OSError, TypeError, ValueError) as exc:
            return self._failure(self.name, exc)
        return ModuleResult(
            ok=True,
            message=f"{self.name}:{payload['hypothesis_id']}:{payload['status']}",
            module=self.name,
            artifacts=[payload["artifact_path"], payload["run_artifact_path"]],
            data=payload,
        )

    @classmethod
    def register_cli(cls, subparsers: Any) -> Any:
        parser = super().register_cli(subparsers)
        parser.add_argument("--ledger-root", default=cls.default_ledger_root)
        parser.add_argument("--run-id", required=True)
        parser.add_argument("--hypothesis-id", default="")
        parser.add_argument("--category", default="")
        parser.add_argument("--statement", default="")
        parser.add_argument("--status", default="")
        parser.add_argument("--rank", type=int, default=None)
        parser.add_argument("--confidence-band", default="")
        parser.add_argument("--supporting-claim-refs", type=_json_array, default=[])
        parser.add_argument("--contradicting-claim-refs", type=_json_array, default=[])
        parser.add_argument("--required-evidence", type=_json_array, default=[])
        parser.add_argument("--experiment-refs", type=_json_array, default=[])
        parser.add_argument("--binding", type=_json_object, default={})
        parser.add_argument("--reason", default="")
        parser.add_argument("--actor", choices=["tool", "ai", "user", "pi"], default="tool")
        return parser


class DebugExperimentRecordModule(_CollaborationModule):
    name = "debug-experiment-record"
    description = "Plan or record one bounded debug experiment in an AnalysisRun"
    tags = ["analysis", "experiment", "debug", "collaboration", "atomic", "local-write"]
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "ledger_root": {"type": "string"},
            "action": {"type": "string", "enum": ["plan", "update"]},
            "run_id": {"type": "string"},
            "experiment_id": {"type": "string"},
            "question": {"type": "string"},
            "method": {"type": "string", "enum": ["", "static_query", "public_runtime", "replay", "gdb", "manual_vscode", "parameter_what_if"]},
            "status": {"type": "string", "enum": ["", "planned", "approval_required", "running", "completed", "partial", "blocked", "failed"]},
            "target": {"type": "object"},
            "plan_ref": {"type": ["object", "null"]},
            "approval": {"type": "object"},
            "session_ref": {"type": ["object", "null"]},
            "watch_groups": {"type": "array", "items": {}},
            "expected_discrimination": {"type": "array", "items": {}},
            "observations": {"type": "array", "items": {}},
            "disturbance": {"type": "object"},
            "conclusion_delta": {"type": "array", "items": {}},
            "hypothesis_refs": {"type": "array", "items": {}},
            "binding": {"type": "object"},
            "reason": {"type": "string"},
            "actor": {"type": "string", "enum": ["tool", "ai", "user", "pi"]},
        },
        "required": ["action", "run_id"],
        "additionalProperties": False,
    }
    output_schema = {
        "type": "object",
        "required": ["schema_version", "experiment_id", "run_id", "question", "method", "status", "observations", "conclusion_delta", "artifact_path"],
    }

    def run(
        self,
        *,
        action: str,
        run_id: str,
        ledger_root: str = "",
        experiment_id: str = "",
        question: str = "",
        method: str = "",
        status: str = "",
        target: Mapping[str, Any] | None = None,
        plan_ref: Mapping[str, Any] | None = None,
        approval: Mapping[str, Any] | None = None,
        session_ref: Mapping[str, Any] | None = None,
        watch_groups: Sequence[Any] | None = None,
        expected_discrimination: Sequence[Any] | None = None,
        observations: Sequence[Any] | None = None,
        disturbance: Mapping[str, Any] | None = None,
        conclusion_delta: Sequence[Any] | None = None,
        hypothesis_refs: Sequence[Any] | None = None,
        binding: Mapping[str, Any] | None = None,
        reason: str = "",
        actor: str = "tool",
        **_: Any,
    ) -> ModuleResult:
        operation = str(action or "").strip()
        if operation not in {"plan", "update"}:
            return ModuleResult.fail(f"{self.name}: action must be plan or update", module=self.name)
        if operation == "plan":
            if experiment_id:
                return ModuleResult.fail(f"{self.name}: plan must not reuse experiment_id", module=self.name)
            selected_status = "planned"
        else:
            if not experiment_id:
                return ModuleResult.fail(f"{self.name}: experiment_id is required for update", module=self.name)
            selected_status = status
            if not selected_status:
                return ModuleResult.fail(f"{self.name}: status is required for update", module=self.name)
        try:
            payload = self._ledger(ledger_root).record_experiment(
                run_id,
                experiment_id=experiment_id,
                question=question,
                method=method,
                status=selected_status,
                target=target,
                plan_ref=plan_ref,
                approval=approval,
                session_ref=session_ref,
                watch_groups=watch_groups,
                expected_discrimination=expected_discrimination,
                observations=observations,
                disturbance=disturbance,
                conclusion_delta=conclusion_delta,
                hypothesis_refs=hypothesis_refs,
                binding=binding,
                reason=reason,
                actor=actor,
            )
        except (LedgerError, OSError, TypeError, ValueError) as exc:
            return self._failure(self.name, exc)
        return ModuleResult(
            ok=True,
            message=f"{self.name}:{payload['experiment_id']}:{payload['status']}",
            module=self.name,
            artifacts=[payload["artifact_path"], payload["run_artifact_path"]],
            data=payload,
        )

    @classmethod
    def register_cli(cls, subparsers: Any) -> Any:
        parser = super().register_cli(subparsers)
        parser.add_argument("--ledger-root", default=cls.default_ledger_root)
        parser.add_argument("--action", required=True, choices=["plan", "update"])
        parser.add_argument("--run-id", required=True)
        parser.add_argument("--experiment-id", default="")
        parser.add_argument("--question", default="")
        parser.add_argument("--method", default="")
        parser.add_argument("--status", default="")
        parser.add_argument("--target", type=_json_object, default={})
        parser.add_argument("--plan-ref", type=_json_object, default=None)
        parser.add_argument("--approval", type=_json_object, default={})
        parser.add_argument("--session-ref", type=_json_object, default=None)
        parser.add_argument("--watch-groups", type=_json_array, default=[])
        parser.add_argument("--expected-discrimination", type=_json_array, default=[])
        parser.add_argument("--observations", type=_json_array, default=[])
        parser.add_argument("--disturbance", type=_json_object, default={})
        parser.add_argument("--conclusion-delta", type=_json_array, default=[])
        parser.add_argument("--hypothesis-refs", type=_json_array, default=[])
        parser.add_argument("--binding", type=_json_object, default={})
        parser.add_argument("--reason", default="")
        parser.add_argument("--actor", choices=["tool", "ai", "user", "pi"], default="tool")
        return parser


class AnalysisUserObservationModule(_CollaborationModule):
    name = "analysis-user-observation"
    description = "Append a user's manual VSCode/GDB/screenshot/note observation"
    tags = ["analysis", "user", "observation", "debug", "collaboration", "atomic", "local-write"]
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "ledger_root": {"type": "string"},
            "run_id": {"type": "string"},
            "observation_id": {"type": "string"},
            "kind": {"type": "string", "enum": ["manual_vscode", "gdb_transcript", "screenshot", "note"]},
            "summary": {"type": "string"},
            "content": {"type": "string"},
            "artifact_refs": {"type": "array", "items": {}},
            "target": {"type": "object"},
            "experiment_id": {"type": "string"},
            "hypothesis_refs": {"type": "array", "items": {}},
            "binding": {"type": "object"},
        },
        "required": ["run_id", "summary"],
        "additionalProperties": False,
    }
    output_schema = {
        "type": "object",
        "required": ["schema_version", "observation_id", "run_id", "kind", "summary", "runtime_eligible", "artifact_path"],
    }

    def run(
        self,
        *,
        run_id: str,
        summary: str,
        ledger_root: str = "",
        observation_id: str = "",
        kind: str = "note",
        content: str = "",
        artifact_refs: Sequence[Any] | None = None,
        target: Mapping[str, Any] | None = None,
        experiment_id: str = "",
        hypothesis_refs: Sequence[Any] | None = None,
        binding: Mapping[str, Any] | None = None,
        **_: Any,
    ) -> ModuleResult:
        try:
            payload = self._ledger(ledger_root).append_user_observation(
                run_id,
                observation_id=observation_id,
                kind=kind,
                summary=summary,
                content=content,
                artifact_refs=artifact_refs,
                target=target,
                experiment_id=experiment_id,
                hypothesis_refs=hypothesis_refs,
                binding=binding,
                created_by="user",
            )
        except (LedgerError, OSError, TypeError, ValueError) as exc:
            return self._failure(self.name, exc)
        return ModuleResult(
            ok=True,
            message=f"{self.name}:{payload['observation_id']}",
            module=self.name,
            artifacts=[payload["artifact_path"], payload["run_artifact_path"]],
            data=payload,
        )

    @classmethod
    def register_cli(cls, subparsers: Any) -> Any:
        parser = super().register_cli(subparsers)
        parser.add_argument("--ledger-root", default=cls.default_ledger_root)
        parser.add_argument("--run-id", required=True)
        parser.add_argument("--observation-id", default="")
        parser.add_argument("--kind", choices=["manual_vscode", "gdb_transcript", "screenshot", "note"], default="note")
        parser.add_argument("--summary", required=True)
        parser.add_argument("--content", default="")
        parser.add_argument("--artifact-refs", type=_json_array, default=[])
        parser.add_argument("--target", type=_json_object, default={})
        parser.add_argument("--experiment-id", default="")
        parser.add_argument("--hypothesis-refs", type=_json_array, default=[])
        parser.add_argument("--binding", type=_json_object, default={})
        return parser


__all__ = [
    "AnalysisHypothesisRecordModule",
    "AnalysisUserObservationModule",
    "DebugExperimentRecordModule",
]
