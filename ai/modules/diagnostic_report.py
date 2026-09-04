"""Pi-facing detailed report projection module."""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from engines.diagnostic_report import build_diagnostic_report, write_diagnostic_report

from .base import BaseModule, ModuleResult


class DiagnosticReportModule(BaseModule):
    """Project static/runtime/code/AI artifacts into one detailed report."""

    name = "diagnosis-report"
    description = "生成单事件或全数据的证据绑定详细诊断报告"
    tags = ["diagnosis", "report", "evidence", "code", "runtime", "atomic", "local-write"]
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "bundle": {"type": "object"},
            "bundle_path": {"type": "string"},
            "viewer_model": {"type": "object"},
            "viewer_model_path": {"type": "string"},
            "runtime_evidence": {"type": "object"},
            "runtime_evidence_path": {"type": "string"},
            "runtime_debug_plan": {"type": "object"},
            "runtime_debug_plan_path": {"type": "string"},
            "preflight": {"type": "object"},
            "preflight_path": {"type": "string"},
            "code_context": {"type": "object"},
            "code_context_path": {"type": "string"},
            "event_code_path": {"type": "object"},
            "event_code_path_path": {"type": "string"},
            "condition_trace": {"type": "object"},
            "condition_trace_path": {"type": "string"},
            "gdb_session": {"type": "object"},
            "gdb_session_path": {"type": "string"},
            "analysis": {"type": "object"},
            "analysis_run": {"type": "object"},
            "analysis_run_path": {"type": "string"},
            "event_id": {"type": "string"},
            "event_index": {"type": "integer"},
            "function": {"type": "string"},
            "side": {"type": "string"},
            "radar_id": {"type": ["string", "integer"]},
            "frame_id": {"type": ["string", "integer"]},
            "output_endpoint": {"type": "string", "enum": ["auto", "algorithm", "can_tx"], "default": "algorithm"},
            "can_data_status": {"type": "string", "enum": ["present", "absent", "not_detected", "unknown"]},
            "max_events": {"type": "integer", "default": 100},
            "max_frames": {"type": "integer", "default": 24},
            "max_targets": {"type": "integer", "default": 24},
            "output_dir": {"type": "string"},
            "response_mode": {"type": "string", "enum": ["summary", "full"], "default": "summary"},
        },
        "anyOf": [
            {"required": ["bundle"]},
            {"required": ["bundle_path"]},
            {"required": ["viewer_model"]},
            {"required": ["viewer_model_path"]},
        ],
        "additionalProperties": False,
    }
    output_schema: dict[str, Any] = {
        "type": "object",
        "required": ["schema_version", "status", "overview", "event_index", "alert_timeline", "diagnostic_narrative", "conclusion", "diagnosis"],
        "properties": {
            "can_output": {"type": "object", "additionalProperties": True},
            "arbe_preflight": {"type": "object", "additionalProperties": True},
        },
    }

    def run(
        self,
        *,
        bundle: Mapping[str, Any] | None = None,
        bundle_path: str = "",
        viewer_model: Mapping[str, Any] | None = None,
        viewer_model_path: str = "",
        runtime_evidence: Mapping[str, Any] | None = None,
        runtime_evidence_path: str = "",
        runtime_debug_plan: Mapping[str, Any] | None = None,
        runtime_debug_plan_path: str = "",
        preflight: Mapping[str, Any] | None = None,
        preflight_path: str = "",
        code_context: Mapping[str, Any] | None = None,
        code_context_path: str = "",
        event_code_path: Mapping[str, Any] | None = None,
        event_code_path_path: str = "",
        condition_trace: Mapping[str, Any] | None = None,
        condition_trace_path: str = "",
        gdb_session: Mapping[str, Any] | None = None,
        gdb_session_path: str = "",
        analysis: Mapping[str, Any] | None = None,
        analysis_run: Mapping[str, Any] | None = None,
        analysis_run_path: str = "",
        event_id: str = "",
        event_index: int | None = None,
        function: str = "",
        side: str = "",
        radar_id: str | int = "",
        frame_id: str | int = "",
        output_endpoint: str = "algorithm",
        can_data_status: str = "",
        max_events: int = 100,
        max_frames: int = 24,
        max_targets: int = 24,
        output_dir: str = "",
        response_mode: str = "summary",
        **_: Any,
    ) -> ModuleResult:
        try:
            report = build_diagnostic_report(
                bundle=bundle,
                bundle_path=bundle_path,
                viewer_model=viewer_model,
                viewer_model_path=viewer_model_path,
                runtime_evidence=runtime_evidence,
                runtime_evidence_path=runtime_evidence_path,
                runtime_debug_plan=runtime_debug_plan,
                runtime_debug_plan_path=runtime_debug_plan_path,
                preflight=preflight,
                preflight_path=preflight_path,
                code_context=code_context,
                code_context_path=code_context_path,
                event_code_path=event_code_path,
                event_code_path_path=event_code_path_path,
                condition_trace=condition_trace,
                condition_trace_path=condition_trace_path,
                gdb_session=gdb_session,
                gdb_session_path=gdb_session_path,
                analysis=analysis,
                analysis_run=analysis_run,
                analysis_run_path=analysis_run_path,
                event_id=event_id,
                event_index=event_index,
                function=function,
                side=side,
                radar_id=radar_id,
                frame_id=frame_id,
                output_endpoint=output_endpoint,
                can_data_status=can_data_status,
                max_events=max_events,
                max_frames=max_frames,
                max_targets=max_targets,
            )
        except (OSError, TypeError, ValueError, KeyError) as exc:
            return ModuleResult.fail(
                f"diagnosis-report:failed: {exc}",
                module=self.name,
                error_type=type(exc).__name__,
            )

        artifacts: list[str] = []
        if str(output_dir or "").strip():
            artifacts = write_diagnostic_report(report, output_dir)
            report["artifact_paths"] = artifacts
            report["artifact_path"] = next((path for path in artifacts if path.endswith("diagnostic-report.json")), artifacts[0] if artifacts else "")
        response_mode = str(response_mode or "summary").lower()
        if response_mode not in {"summary", "full"}:
            return ModuleResult.fail(
                "diagnosis-report:response_mode must be summary or full",
                module=self.name,
            )
        response = report if response_mode == "full" or not output_dir else self._summary_response(report)
        response["response_mode"] = response_mode
        status = str(report.get("status", "partial"))
        return ModuleResult(
            ok=status != "blocked",
            message=f"diagnosis-report:{status}",
            module=self.name,
            artifacts=artifacts,
            data=response,
        )

    @staticmethod
    def _summary_response(report: Mapping[str, Any]) -> dict[str, Any]:
        """Keep Pi's tool result small; the full report remains on disk."""
        narrative = report.get("diagnostic_narrative") if isinstance(report.get("diagnostic_narrative"), Mapping) else {}
        story = report.get("diagnostic_story") if isinstance(report.get("diagnostic_story"), Mapping) else {}
        assessment = narrative.get("alarm_assessment") if isinstance(narrative.get("alarm_assessment"), Mapping) else {}

        def pick(value: Any, keys: tuple[str, ...]) -> dict[str, Any]:
            if not isinstance(value, Mapping):
                return {}
            return {key: deepcopy(value[key]) for key in keys if value.get(key) not in (None, "", [])}

        compact_story: dict[str, Any] = {}
        for key in ("schema_version", "status", "title", "operating_condition", "code_path", "geometry", "output", "output_chain", "conclusion"):
            if story.get(key) not in (None, "", []):
                compact_story[key] = deepcopy(story[key])
        walk = story.get("condition_walk") if isinstance(story.get("condition_walk"), Mapping) else {}
        if walk:
            compact_story["condition_walk"] = {
                **pick(walk, ("text", "scope", "counts")),
                "steps": [
                    {
                        key: deepcopy(item[key])
                        for key in (
                            "order", "source", "category", "category_label", "status", "prose",
                            "expression", "substituted_expression", "bindings", "missing_tokens",
                            "chain_function", "chain_relation",
                        )
                        if item.get(key) not in (None, "", [])
                    }
                    for item in walk.get("steps", [])[:12]
                    if isinstance(item, Mapping)
                ],
            }
        flow = narrative.get("analysis_flow") if isinstance(narrative.get("analysis_flow"), Mapping) else report.get("analysis_flow")
        compact_flow = pick(flow, ("schema_version", "status", "policy"))
        if isinstance(flow, Mapping):
            compact_steps: list[dict[str, Any]] = []
            for item in flow.get("steps", [])[:8]:
                if not isinstance(item, Mapping):
                    continue
                compact_step = pick(item, ("step_id", "order", "kind", "title", "status", "summary", "current_relation", "should_alert", "statement"))
                if item.get("kind") == "fct_output_mapping" and isinstance(item.get("output_chain"), Mapping):
                    chain = item["output_chain"]
                    compact_step["output_chain"] = {
                        **pick(chain, ("schema_version", "status", "source_status", "primary_internal_signal", "primary_external_signal", "text")),
                        "steps": [
                            pick(step, ("order", "kind", "status", "token", "signal", "value", "expression", "source_ref", "send_ref", "text"))
                            for step in chain.get("steps", [])[:6]
                            if isinstance(step, Mapping)
                        ],
                    }
                compact_steps.append(compact_step)
            compact_flow["steps"] = compact_steps
        selected = report.get("selected_event")
        selected_response: dict[str, Any] = {}
        selected = report.get("selected_event")
        if isinstance(selected, Mapping):
            selected_response = {
                key: selected[key]
                for key in ("event_id", "summary", "runtime_association", "provenance", "source_refs")
                if key in selected
            }
            facts = selected.get("facts")
            if isinstance(facts, list):
                selected_response["facts"] = []
                for fact in facts[:24]:
                    if not isinstance(fact, Mapping):
                        continue
                    item = dict(fact)
                    value = item.get("value")
                    if isinstance(value, list) and len(value) > 20:
                        item["value"] = value[:20]
                        item["truncated"] = True
                    elif isinstance(value, Mapping) and len(value) > 40:
                        keys = list(value)[:40]
                        item["value"] = {key: value[key] for key in keys}
                        item["truncated"] = True
                    selected_response["facts"].append(item)
                if len(facts) > 24:
                    selected_response["facts_truncated"] = True
            selected_response["details_ref"] = {
                "status": "available_in_artifact",
                "artifact_path": next(
                    (path for path in report.get("artifact_paths", []) if str(path).endswith("diagnostic-report.json")),
                    "",
                ),
            }
        gdb = report.get("gdb_confirmation") if isinstance(report.get("gdb_confirmation"), Mapping) else {}
        response = {
            "schema_version": report.get("schema_version"),
            "status": report.get("status"),
            "identity": deepcopy(report.get("identity", {})),
            "overview": deepcopy(report.get("overview", {})),
            "selected_event": selected_response,
            "diagnostic_narrative": {
                "schema_version": narrative.get("schema_version"),
                "status": narrative.get("status"),
                "executive_summary": narrative.get("executive_summary", ""),
                "alarm_assessment": deepcopy(assessment),
                "condition_assessment": deepcopy(narrative.get("condition_assessment", {})),
                "condition_digest": deepcopy(narrative.get("condition_digest", {})),
                "output_chain": deepcopy(narrative.get("output_chain", {})),
                "next_actions": deepcopy(narrative.get("next_actions", [])[:8]) if isinstance(narrative.get("next_actions"), list) else [],
            },
            "diagnostic_story": compact_story,
            "analysis_flow": compact_flow,
            "geometry_projection": pick(report.get("geometry_projection"), ("status", "source", "collision_status", "instantaneous_relation", "collision_evidence", "predicted_intersection", "algorithm_branch")),
            "gdb_confirmation": pick(gdb, ("status", "actual_hit", "session_status", "evidence_status", "frame_id", "radar_id", "object_id", "function", "source_location", "captured_fields", "observed_field_count", "missing_probe_count", "algorithm_rising_frame", "frame_relation_to_algorithm_rise", "statement")),
            "execution_context": deepcopy(report.get("execution_context", {})),
            "output_policy": deepcopy(report.get("output_policy", {})),
            "artifact_paths": deepcopy(report.get("artifact_paths", [])),
            "artifact_path": report.get("artifact_path", ""),
            "diagnostics": deepcopy(report.get("diagnostics", [])[:24]) if isinstance(report.get("diagnostics"), list) else [],
        }
        response["summary_only"] = True
        return response

    @classmethod
    def register_cli(cls, subparsers: Any) -> Any:
        parser = super().register_cli(subparsers)
        parser.add_argument("--bundle", dest="bundle_path", default="")
        parser.add_argument("--viewer-model", dest="viewer_model_path", default="")
        parser.add_argument("--runtime-evidence", dest="runtime_evidence_path", default="")
        parser.add_argument("--runtime-debug-plan", dest="runtime_debug_plan_path", default="")
        parser.add_argument("--preflight", dest="preflight_path", default="")
        parser.add_argument("--code-context", dest="code_context_path", default="")
        parser.add_argument("--event-code-path", dest="event_code_path_path", default="")
        parser.add_argument("--condition-trace", dest="condition_trace_path", default="")
        parser.add_argument("--gdb-session", dest="gdb_session_path", default="")
        parser.add_argument("--analysis", default="", help="AI diagnosis-panel result JSON")
        parser.add_argument("--analysis-run", dest="analysis_run_path", default="")
        parser.add_argument("--event-id", default="")
        parser.add_argument("--event-index", type=int, default=None)
        parser.add_argument("--function", default="")
        parser.add_argument("--side", default="")
        parser.add_argument("--radar-id", default="")
        parser.add_argument("--frame-id", default="")
        parser.add_argument("--output-endpoint", choices=["auto", "algorithm", "can_tx"], default="algorithm")
        parser.add_argument("--can-data-status", choices=["present", "absent", "not_detected", "unknown"], default="")
        parser.add_argument("--max-events", type=int, default=100)
        parser.add_argument("--max-frames", type=int, default=24)
        parser.add_argument("--max-targets", type=int, default=24)
        parser.add_argument("--output-dir", default="")
        parser.add_argument("--response-mode", choices=["summary", "full"], default="summary")
        return parser

    @classmethod
    def from_cli_args(cls, args: Any) -> "DiagnosticReportModule":
        analysis_text = getattr(args, "analysis", "")
        if analysis_text:
            try:
                args.analysis = json.loads(analysis_text)
            except json.JSONDecodeError as exc:
                raise ValueError(f"analysis must be valid JSON: {exc.msg}") from exc
            if not isinstance(args.analysis, dict):
                raise ValueError("analysis must decode to an object")
        return cls()


__all__ = ["DiagnosticReportModule"]
