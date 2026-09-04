# -*- coding: utf-8 -*-
"""Pi orchestration-context capability.

This is a deterministic context binder, not an LLM summariser. It combines
explicit intake/preflight/diagnosis/runtime artifacts so Pi can compose later
tools against one project/data/source binding.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from engines.pi_context import build_pi_orchestration_context

from .base import BaseModule, ModuleResult


class PiContextModule(BaseModule):
    name = "pi-context"
    description = "Build an immutable provenance-bound Pi orchestration context"
    tags = ["pi", "orchestration", "context", "provenance", "atomic"]
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "intake": {"type": "object"},
            "intake_path": {"type": "string"},
            "preflight": {"type": "object"},
            "preflight_path": {"type": "string"},
            "case_dir": {"type": "string"},
            "project_root": {"type": "string"},
            "project_id": {"type": "string"},
            "variant_id": {"type": "string"},
            "operator": {"type": "string"},
            "run_id": {"type": "string"},
            "replay_strategy": {"type": "string"},
            "radar_id": {"type": "string"},
            "freshness": {"type": "object"},
            "policy": {"type": "object"},
            "artifact_refs": {"type": "array", "items": {"type": "object"}},
            "runtime_evidence": {"type": "object"},
            "runtime_evidence_path": {"type": "string"},
            "diagnosis_bundle": {"type": "object"},
            "diagnosis_bundle_path": {"type": "string"},
            "runtime_debug_plan": {"type": "object"},
            "runtime_debug_plan_path": {"type": "string"},
            "capability_manifest": {"type": "object"},
            "capability_manifest_path": {"type": "string"},
            "output": {"type": "string"}
        },
        "additionalProperties": False
    }
    output_schema: dict[str, Any] = {
        "type": "object",
        "required": [
            "schema_version", "status", "run_id", "context_fingerprint", "project", "data",
            "source", "policy", "artifacts", "missing", "conflicts"
        ]
    }

    def run(
        self,
        *,
        intake: Mapping[str, Any] | None = None,
        intake_path: str = "",
        preflight: Mapping[str, Any] | None = None,
        preflight_path: str = "",
        case_dir: str = "",
        project_root: str = "",
        project_id: str = "",
        variant_id: str = "",
        operator: str = "",
        run_id: str = "",
        replay_strategy: str = "",
        radar_id: str = "",
        freshness: Mapping[str, Any] | None = None,
        policy: Mapping[str, Any] | None = None,
        artifact_refs: list[Mapping[str, Any]] | None = None,
        runtime_evidence: Mapping[str, Any] | None = None,
        runtime_evidence_path: str = "",
        diagnosis_bundle: Mapping[str, Any] | None = None,
        diagnosis_bundle_path: str = "",
        runtime_debug_plan: Mapping[str, Any] | None = None,
        runtime_debug_plan_path: str = "",
        capability_manifest: Mapping[str, Any] | None = None,
        capability_manifest_path: str = "",
        output: str = "",
        **_: Any,
    ) -> ModuleResult:
        payload = build_pi_orchestration_context(
            intake=intake,
            intake_path=intake_path,
            preflight=preflight,
            preflight_path=preflight_path,
            case_dir=case_dir,
            project_root=project_root,
            project_id=project_id,
            variant_id=variant_id,
            operator=operator,
            run_id=run_id,
            replay_strategy=replay_strategy,
            radar_id=radar_id,
            freshness=freshness,
            policy=policy,
            artifact_refs=artifact_refs,
            runtime_evidence=runtime_evidence,
            runtime_evidence_path=runtime_evidence_path,
            diagnosis_bundle=diagnosis_bundle,
            diagnosis_bundle_path=diagnosis_bundle_path,
            runtime_debug_plan=runtime_debug_plan,
            runtime_debug_plan_path=runtime_debug_plan_path,
            capability_manifest=capability_manifest,
            capability_manifest_path=capability_manifest_path,
        )
        artifacts: list[str] = []
        if str(output or "").strip():
            path = Path(output).expanduser().resolve()
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
                artifacts.append(str(path))
                payload["artifact_path"] = str(path)
            except OSError as exc:
                return ModuleResult(
                    ok=False,
                    message=f"pi-context output failed: {type(exc).__name__}: {exc}",
                    module=self.name,
                    data=payload,
                    artifacts=artifacts,
                )
        status = str(payload.get("status", "blocked"))
        return ModuleResult(
            ok=status != "blocked",
            message=f"pi-context:{status}",
            module=self.name,
            data=payload,
            artifacts=artifacts,
        )

    @classmethod
    def register_cli(cls, subparsers: Any) -> Any:
        parser = super().register_cli(subparsers)
        parser.add_argument("--intake", dest="intake_path", default="")
        parser.add_argument("--preflight", dest="preflight_path", default="")
        parser.add_argument("--case-dir", default="")
        parser.add_argument("--project-root", default="")
        parser.add_argument("--project-id", default="")
        parser.add_argument("--variant-id", default="")
        parser.add_argument("--operator", default="")
        parser.add_argument("--run-id", default="")
        parser.add_argument("--replay-strategy", default="")
        parser.add_argument("--radar-id", default="")
        parser.add_argument("--policy", default="", help="policy JSON object")
        parser.add_argument("--runtime-evidence", "--runtime-evidence-path", dest="runtime_evidence_path", default="")
        parser.add_argument("--diagnosis-bundle", "--diagnosis-bundle-path", dest="diagnosis_bundle_path", default="")
        parser.add_argument("--runtime-debug-plan", "--runtime-debug-plan-path", dest="runtime_debug_plan_path", default="")
        parser.add_argument("--capability-manifest", "--capability-manifest-path", dest="capability_manifest_path", default="")
        parser.add_argument("--output", default="")
        return parser

    @classmethod
    def from_cli_args(cls, args: Any) -> "PiContextModule":
        policy_text = getattr(args, "policy", "")
        if policy_text:
            try:
                args.policy = json.loads(policy_text)
            except json.JSONDecodeError as exc:
                raise ValueError(f"policy must be valid JSON: {exc.msg}") from exc
            if not isinstance(args.policy, dict):
                raise ValueError("policy must decode to a JSON object")
        return cls()


__all__ = ["PiContextModule"]
