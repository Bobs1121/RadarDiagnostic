# -*- coding: utf-8 -*-
"""PiModule (V4 P1) — pi 统一对话入口（BaseModule）。

通过 :class:`ai.pi_bridge.PiBridge` 驱动 pi CLI（--mode rpc），实现
"统一对话 + 整体调度中枢"：用户自然语言 → pi 规划 → 调度 radarAnalyze
能力工具 → 综合回答。独立运行::

    python cli.py pi --question "帮我抽取车速信号" --case-dir cases/xxx
    python cli.py pi --batch questions.json
    python cli.py pi --interactive
"""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
import re
import time
from typing import Any, Mapping

from .base import BaseModule, ModuleResult

log = logging.getLogger(__name__)


def discover_case_artifacts(case_dir: str) -> dict[str, str]:
    """Discover canonical artifacts for one case, including batch siblings.

    The independent Sprint1 harness deliberately keeps static ``cases/<id>``
    and browser ``data/<id>`` outputs separate.  A Pi user normally passes
    the case directory, so the batch manifest is the only safe way to bind
    the companion viewer/report files without guessing from a bag name.  The
    manifest match is by its explicit ``case_id``/``data_id`` fields and all
    discovered paths remain ordinary artifact refs.
    """
    if not str(case_dir or "").strip():
        return {}
    root = Path(case_dir).expanduser()
    if root.is_file():
        root = root.parent
    if not root.is_dir():
        return {}
    candidates = {
        "diagnosis_bundle_path": ("diagnosis_bundle.json",),
        "viewer_model_path": ("viewer-model.json", "viewer_model.json"),
        "runtime_evidence_path": ("runtime_evidence.json", "runtime-case-evidence.v1.json"),
        "runtime_debug_plan_path": ("runtime_debug_plan.json", "runtime-debug-plan.v1.json"),
        "preflight_path": ("arbe-preflight.json", "arbe_preflight.json", "preflight.json"),
        "code_context_path": ("code-context.json", "code_context.json"),
        "event_code_path_path": ("event-code-path.json", "event_code_path.json"),
        "condition_trace_path": ("condition-trace.json", "condition_trace.json"),
        "gdb_session_path": ("gdb-session.json", "gdb_session.json", "gdb-session.v1.json"),
        "diagnostic_report_path": ("diagnostic-report.json", "diagnostic_report.json"),
        "perception_report_path": ("perception-report.json",),
        "viewer_report_path": ("report.html", "report.htm"),
        "evidence_query_path": ("evidence-query.json", "evidence_query.json"),
        "runtime_schema_path": ("runtime_schema.json", "runtime-schema.json"),
        "media_manifest_path": ("media_manifest.json", "media-manifest.json"),
        "vscode_handoff_path": ("vscode_handoff.json", "vscode-handoff.json"),
        "intake_path": ("cr60-analysis-intake.json", "cr60_analysis_intake.json", "intake.json"),
    }
    result: dict[str, str] = {}
    for output_key, names in candidates.items():
        for name in names:
            path = root / name
            if path.is_file():
                result[output_key] = str(path.resolve())
                break
    if "gdb_session_path" not in result:
        gdb_candidates = sorted(root.glob("gdb-session*.json"))
        if len(gdb_candidates) == 1:
            result["gdb_session_path"] = str(gdb_candidates[0].resolve())

    # Resolve the sibling ``data/<case_id>`` and ``cases/<case_id>`` outputs
    # only through the authoritative batch-index manifest.  This works when
    # the caller passes either side of the split and also when the manifest is
    # one level above the passed directory.
    case_id = root.name
    manifest_candidates = [
        root / "batch-index.json",
        root.parent / "batch-index.json",
        root.parent.parent / "batch-index.json",
    ]
    manifest_path = next((path for path in manifest_candidates if path.is_file()), None)
    if manifest_path is not None:
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            manifest = None
        datasets = manifest.get("datasets", []) if isinstance(manifest, Mapping) else []
        match = next(
            (
                item for item in datasets
                if isinstance(item, Mapping)
                and case_id in {str(item.get("case_id", "")), str(item.get("data_id", ""))}
            ),
            None,
        )
        if isinstance(match, Mapping):
            result.setdefault("batch_index_path", str(manifest_path.resolve()))
            for key, manifest_key in (
                ("viewer_model_path", "model"),
                ("viewer_report_path", "report"),
            ):
                relative = str(match.get(manifest_key, "") or "").strip()
                if not relative:
                    continue
                companion = (manifest_path.parent / Path(relative)).resolve()
                if companion.is_file():
                    result[key] = str(companion)

            # If the caller passed the browser data directory, discover the
            # static bundle from the matching cases directory.  Conversely,
            # when the caller passed cases/<id>, discover the viewer sibling.
            batch_root = manifest_path.parent
            for key, relative in (
                ("diagnosis_bundle_path", Path("cases") / case_id / "diagnosis_bundle.json"),
                ("viewer_model_path", Path("data") / case_id / "viewer-model.json"),
                ("runtime_schema_path", Path("data") / case_id / "runtime_schema.json"),
                ("media_manifest_path", Path("data") / case_id / "media_manifest.json"),
            ):
                companion = (batch_root / relative).resolve()
                if companion.is_file():
                    result.setdefault(key, str(companion))

    return result


def _read_json_object(path_text: str) -> dict[str, Any] | None:
    if not str(path_text or "").strip():
        return None
    try:
        payload = json.loads(Path(path_text).expanduser().resolve().read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return dict(payload) if isinstance(payload, Mapping) else None


def _resolve_question_event_filter(
    question: str,
    *,
    bundle_path: str,
    viewer_model_path: str,
    kwargs: Mapping[str, Any],
) -> dict[str, Any]:
    """Resolve only event tokens already present in the input artifacts."""
    result: dict[str, Any] = {}
    for key in ("event_id", "function", "side", "radar_id", "frame_id"):
        value = kwargs.get(key)
        if value not in (None, "", []):
            result[key] = value
    if result.get("event_id") or result.get("function"):
        return result
    candidates: list[dict[str, Any]] = []
    for payload in (_read_json_object(bundle_path), _read_json_object(viewer_model_path)):
        if not isinstance(payload, Mapping):
            continue
        items = payload.get("alarm_events") or payload.get("events") or []
        for item in items:
            if not isinstance(item, Mapping):
                continue
            identity = item.get("identity") if isinstance(item.get("identity"), Mapping) else {}
            function = item.get("function") or identity.get("function")
            event_id = item.get("event_id")
            if function or event_id:
                candidates.append({
                    "event_id": event_id,
                    "function": function,
                    "side": identity.get("side") or item.get("side"),
                    "radar_id": identity.get("radar_id") or item.get("radar_id"),
                })
    query = str(question or "").upper()
    matches = [item for item in candidates if str(item.get("function") or "").upper() in query]
    unique_functions = list(dict.fromkeys(str(item.get("function") or "") for item in matches if item.get("function")))
    radar_match = re.search(r"(?:RADAR|雷达)\s*[_:= -]?\s*([0-9]+)", query)
    frame_match = re.search(r"(?:FRAMEID|FRAME|帧)\s*[_:= -]?\s*([0-9]+)", query)
    if radar_match:
        result["radar_id"] = radar_match.group(1)
    if frame_match:
        result["frame_id"] = frame_match.group(1)
    if len(unique_functions) == 1:
        # Multiple events of the same function are normal.  Keep the
        # function/side filter and let the report's event selection use any
        # explicit frame/radar supplied by the caller; never fall back to the
        # first event of a different function.
        result["function"] = unique_functions[0]
        function_text = unique_functions[0].upper()
        if function_text.endswith("_L"):
            result.setdefault("side", "L")
        elif function_text.endswith("_R"):
            result.setdefault("side", "R")
        if len(matches) == 1:
            result.update({key: value for key, value in matches[0].items() if value not in (None, "", [])})
        unique_events = list(dict.fromkeys(str(item.get("event_id") or "") for item in matches if item.get("event_id")))
        if len(unique_events) > 1 and not result.get("event_id") and not result.get("frame_id") and not result.get("radar_id"):
            result["_ambiguous"] = True
            result["candidate_event_ids"] = unique_events[:12]
    elif len(matches) == 1:
        result.update({key: value for key, value in matches[0].items() if value not in (None, "", [])})
    else:
        unique_events = list(dict.fromkeys(str(item.get("event_id") or "") for item in candidates if item.get("event_id")))
        if not result.get("frame_id") and not result.get("radar_id") and len(unique_events) > 1:
            result["_ambiguous"] = True
            result["candidate_event_ids"] = unique_events[:12]
    return result


def _build_evidence_anchor(
    *,
    question: str,
    case_dir: str,
    discovered: Mapping[str, str],
    kwargs: Mapping[str, Any],
    output_dir: str = "",
) -> dict[str, Any] | None:
    """Build a bounded deterministic report summary for Pi's context."""
    text = str(question or "").lower()
    detail_intent = bool(output_dir or kwargs.get("generate_report") or kwargs.get("perception_report_path")) or any(token in text for token in (
        "报警", "诊断", "根因", "误报", "正报", "报告", "目标", "自车", "代码条件", "runtime", "运行时", "gdb",
    ))
    if not detail_intent:
        return None
    bundle_path = str(kwargs.get("diagnosis_bundle_path") or discovered.get("diagnosis_bundle_path") or "")
    viewer_path = str(kwargs.get("viewer_model_path") or discovered.get("viewer_model_path") or "")
    runtime_path = str(kwargs.get("runtime_evidence_path") or discovered.get("runtime_evidence_path") or "")
    preflight = kwargs.get("preflight") if isinstance(kwargs.get("preflight"), Mapping) else None
    preflight_path = str(kwargs.get("preflight_path") or discovered.get("preflight_path") or "")
    runtime_debug_plan_path = str(kwargs.get("runtime_debug_plan_path") or discovered.get("runtime_debug_plan_path") or "")
    code_context_path = str(kwargs.get("code_context_path") or discovered.get("code_context_path") or "")
    event_code_path = str(kwargs.get("event_code_path_path") or discovered.get("event_code_path_path") or "")
    condition_trace_path = str(kwargs.get("condition_trace_path") or discovered.get("condition_trace_path") or "")
    gdb_session_path = str(kwargs.get("gdb_session_path") or discovered.get("gdb_session_path") or "")
    analysis_run_path = str(kwargs.get("analysis_run_path") or "")
    perception_report_path = str(kwargs.get("perception_report_path") or discovered.get("perception_report_path") or "")
    output_endpoint = str(kwargs.get("output_endpoint") or "algorithm")
    can_data_status = str(kwargs.get("can_data_status") or "")
    if perception_report_path:
        try:
            perception_report = json.loads(Path(perception_report_path).expanduser().read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            return {
                "schema_version": "deterministic-evidence-anchor.v1",
                "status": "partial",
                "error": f"perception_report_anchor_unavailable:{type(exc).__name__}",
                "artifact_refs": [{"kind": "perception_report", "path": perception_report_path}],
                "report_artifacts": [],
                "policy": "The perception report could not be verified; do not invent its contents.",
            }
        if not isinstance(perception_report, Mapping) or perception_report.get("schema_version") != "perception-report.v1":
            return {
                "schema_version": "deterministic-evidence-anchor.v1",
                "status": "blocked",
                "error": "perception_report_schema_mismatch",
                "artifact_refs": [{"kind": "perception_report", "path": perception_report_path}],
                "report_artifacts": [],
                "policy": "The supplied artifact is not a supported perception report.",
            }
        analysis = perception_report.get("analysis") if isinstance(perception_report.get("analysis"), Mapping) else {}
        contract = analysis.get("input_contract") if isinstance(analysis.get("input_contract"), Mapping) else {}
        coverage = analysis.get("stage_coverage") if isinstance(analysis.get("stage_coverage"), Mapping) else {}
        lineage = analysis.get("lineage") if isinstance(analysis.get("lineage"), Mapping) else {}
        lineage_nodes = lineage.get("nodes") if isinstance(lineage.get("nodes"), Mapping) else {}
        lineage_node_counts = lineage.get("node_counts") if isinstance(lineage.get("node_counts"), Mapping) else {}
        if not lineage_node_counts:
            lineage_node_counts = {
                kind: len(lineage_nodes.get(kind, []) or []) if isinstance(lineage_nodes.get(kind), list) else 0
                for kind in ("points", "clusters", "tracks", "outputs")
            }
            point_artifact = contract.get("points_artifact") if isinstance(contract.get("points_artifact"), Mapping) else {}
            if lineage_nodes.get("points_truncated") or contract.get("points_truncated"):
                lineage_node_counts["points"] = int(point_artifact.get("point_count") or contract.get("point_count") or lineage_node_counts["points"])
        run = analysis.get("run_evidence") if isinstance(analysis.get("run_evidence"), Mapping) else {}
        scene = analysis.get("scene") if isinstance(analysis.get("scene"), Mapping) else {}
        timeline = analysis.get("timeline") if isinstance(analysis.get("timeline"), Mapping) else {}
        callback_binding = analysis.get("callback_binding_summary") if isinstance(analysis.get("callback_binding_summary"), Mapping) else {}
        source_contract = analysis.get("source_execution_contract") if isinstance(analysis.get("source_execution_contract"), Mapping) else {}
        code_flow = analysis.get("code_flow") if isinstance(analysis.get("code_flow"), Mapping) else {}
        code_context = code_flow.get("code_context") if isinstance(code_flow.get("code_context"), Mapping) else {}
        stage_rows = coverage.get("stages") if isinstance(coverage.get("stages"), list) else []
        report_hash = hashlib.sha256(Path(perception_report_path).read_bytes()).hexdigest()
        anchor_data = {
            "schema_version": "perception-report-anchor.v1",
            "report_status": perception_report.get("status"),
            "analysis_status": analysis.get("status"),
            "conclusion_level": analysis.get("conclusion_level"),
            "problem": analysis.get("problem", ""),
            "strategy": analysis.get("strategy", "point_cloud"),
            "input": {
                "boundary": contract.get("input_boundary"),
                "layout_status": contract.get("layout_status"),
                "point_count": contract.get("point_count", 0),
                "radar_summary": contract.get("radar_summary", []),
                "target_usage": contract.get("target_usage", {}),
                "losses": contract.get("losses", {}),
            },
            "stage_coverage": {
                "status": coverage.get("status"),
                "available_stage_count": coverage.get("available_stage_count", 0),
                "derived_stage_count": coverage.get("derived_stage_count", 0),
                "total_stage_count": coverage.get("total_stage_count", len(stage_rows)),
                "stages": [
                    {key: row.get(key) for key in ("stage", "status", "runtime_proof", "input_count", "output_count", "frame_count", "source_ref", "diagnostics")}
                    for row in stage_rows if isinstance(row, Mapping)
                ],
            },
            "lineage": {
                "status": lineage.get("status"),
                "edge_count": lineage.get("edge_count", 0),
                "raw_edge_count": lineage.get("raw_edge_count", len(lineage.get("raw_edges", []) or [])),
                "relation_counts": lineage.get("relation_counts", {}),
                "raw_relation_counts": lineage.get("raw_relation_counts", {}),
                "relation_summaries": lineage.get("relation_summaries", {}),
                "relation_scopes": lineage.get("relation_scopes", {}),
                "relation_kinds": lineage.get("relation_kinds", []),
                "track_population": lineage.get("track_population", {}),
                "invalid_edge_count": lineage.get("invalid_edge_count", len(lineage.get("invalid_edges", []) or [])),
                "identity_warnings": lineage.get("identity_warnings", []),
                "node_counts": {kind: int(lineage_node_counts.get(kind, 0) or 0) for kind in ("points", "clusters", "tracks", "outputs")},
                "nodes_truncated": bool(lineage.get("nodes_truncated") or lineage_nodes.get("points_truncated")),
                "edges_truncated": bool(lineage.get("edges_truncated")),
                "lineage_artifact": lineage.get("lineage_artifact", {}),
            },
            "callback_binding": dict(callback_binding),
            "run": {
                "status": run.get("status"),
                "terminal_status": run.get("terminal_status"),
                "observed_frame_count": len(run.get("observed_frames", []) or []),
                "completed_frame_count": len(run.get("completed_frames", []) or []),
                "warmup": run.get("warmup", {}),
                "reset_status": run.get("reset_status"),
                "diagnostics": run.get("diagnostics", []),
            },
            "scene": {key: scene.get(key) for key in ("status", "selected_frame", "selection_basis", "coordinate_frame", "counts")},
            "timeline": {
                "status": timeline.get("status"),
                "uid_recurrence_status": timeline.get("uid_recurrence_status", "not_available"),
                "uid_recurrence_scope": timeline.get("uid_recurrence_scope", "not_available"),
                "public_uid_recurrences": [dict(row) for row in (timeline.get("public_uid_recurrences", []) or [])[:20] if isinstance(row, Mapping)],
            },
            "gaps": [
                {key: row.get(key) for key in ("id", "severity", "message")}
                for row in analysis.get("gaps", []) or [] if isinstance(row, Mapping)
            ],
            "source_execution_contract": {
                "status": source_contract.get("status"),
                "publication_order": source_contract.get("publication_order", {}),
                "source_refs": source_contract.get("source_refs", {}),
                "source_file_hashes": source_contract.get("source_file_hashes", {}),
                "diagnostics": source_contract.get("diagnostics", []),
                "limitations": source_contract.get("limitations", []),
            },
            "code_context": {
                "context_id": code_context.get("context_id", ""),
                "calls": code_context.get("calls", {}),
                "functions": code_context.get("functions", []),
                "conditions": code_context.get("conditions", []),
            },
            "validation": perception_report.get("validation", {}),
        }
        return {
            "schema_version": "deterministic-evidence-anchor.v1",
            "status": "ready" if str(perception_report.get("status")) not in {"blocked", "invalid"} else "partial",
            "scope": {"kind": "point_cloud_perception_report", "strategy": "point_cloud"},
            "perception_report": anchor_data,
            "artifact_refs": [{"kind": "perception_report", "path": perception_report_path, "sha256": report_hash}],
            "report_artifacts": [perception_report_path],
            "policy": "Facts below are a deterministic projection of this hashed perception-report.v1. Preserve observed, derived, not_available and inference as separate evidence levels. This report is partial and cannot confirm a root cause.",
        }
    if not bundle_path and not viewer_path:
        return None
    try:
        from engines.diagnostic_report import build_diagnostic_report, write_diagnostic_report

        selector = _resolve_question_event_filter(
            question, bundle_path=bundle_path, viewer_model_path=viewer_path, kwargs=kwargs,
        )
        if selector.get("_ambiguous"):
            return {
                "status": "partial",
                "error": "event_scope_ambiguous",
                "candidate_event_ids": list(selector.get("candidate_event_ids", []) or []),
                "artifact_refs": [
                    {"kind": key, "path": value}
                    for key, value in (("diagnosis_bundle", bundle_path), ("viewer_model", viewer_path), ("runtime_evidence", runtime_path), ("arbe_preflight", preflight_path))
                    if value
                ],
                "policy": "Multiple events match the available artifacts; Pi must ask for a business-level function/radar/frame selection before stating a single-event conclusion.",
                "report_artifacts": [],
            }
        report = build_diagnostic_report(
            bundle_path=bundle_path,
            viewer_model_path=viewer_path,
            runtime_evidence_path=runtime_path,
            preflight=preflight,
            preflight_path=preflight_path,
            runtime_debug_plan_path=runtime_debug_plan_path,
            code_context_path=code_context_path,
            event_code_path_path=event_code_path,
            condition_trace_path=condition_trace_path,
            gdb_session_path=gdb_session_path,
            analysis_run_path=analysis_run_path,
            event_id=str(selector.get("event_id") or ""),
            function=str(selector.get("function") or ""),
            side=str(selector.get("side") or ""),
            radar_id=selector.get("radar_id", ""),
            frame_id=selector.get("frame_id", ""),
            output_endpoint=output_endpoint,
            can_data_status=can_data_status,
            max_events=1,
            max_frames=12,
            max_targets=8,
        )
        report_artifacts = write_diagnostic_report(report, output_dir) if str(output_dir or "").strip() else []
    except (OSError, TypeError, ValueError, KeyError) as exc:
        return {"status": "partial", "error": f"deterministic_anchor_failed:{type(exc).__name__}:{exc}"}
    narrative = report.get("diagnostic_narrative") if isinstance(report.get("diagnostic_narrative"), Mapping) else {}
    assessment = narrative.get("alarm_assessment") if isinstance(narrative.get("alarm_assessment"), Mapping) else {}
    geometry = report.get("geometry_projection") if isinstance(report.get("geometry_projection"), Mapping) else {}
    gdb_confirmation = report.get("gdb_confirmation") if isinstance(report.get("gdb_confirmation"), Mapping) else {}
    execution_context = report.get("execution_context") if isinstance(report.get("execution_context"), Mapping) else {}
    story = report.get("diagnostic_story") if isinstance(report.get("diagnostic_story"), Mapping) else narrative.get("diagnostic_story", {})
    story_summary: dict[str, Any] = {}
    if isinstance(story, Mapping):
        story_summary = {
            key: story.get(key)
            for key in ("schema_version", "status", "title", "operating_condition", "code_path", "geometry", "output", "conclusion")
            if story.get(key) not in (None, "", [])
        }
        condition_walk = story.get("condition_walk") if isinstance(story.get("condition_walk"), Mapping) else {}
        story_summary["condition_walk"] = {
            key: condition_walk.get(key)
            for key in ("text", "scope", "counts")
            if condition_walk.get(key) not in (None, "", [])
        }
        story_summary["condition_walk"]["steps"] = [
            {
                key: item.get(key)
                for key in ("order", "source", "category_label", "status", "prose", "expression", "substituted_expression", "missing_tokens")
                if item.get(key) not in (None, "", [])
            }
            for item in condition_walk.get("steps", []) or []
            if isinstance(item, Mapping)
        ][:12]
    flow = narrative.get("analysis_flow") if isinstance(narrative.get("analysis_flow"), Mapping) else {}
    flow_steps: list[dict[str, Any]] = []
    for step in flow.get("steps", []) or []:
        if not isinstance(step, Mapping):
            continue
        item = {
            key: step.get(key)
            for key in ("step_id", "order", "kind", "title", "status", "summary", "scope", "counts", "current_relation", "should_alert", "statement")
            if step.get(key) not in (None, "", [])
        }
        if step.get("kind") == "geometry_and_prediction":
            prediction = step.get("prediction") if isinstance(step.get("prediction"), Mapping) else {}
            item["prediction"] = {
                key: prediction.get(key)
                for key in ("x", "y", "time", "x_token", "y_token", "time_token", "roi_relations")
                if prediction.get(key) not in (None, "", [])
            }
        if step.get("kind") == "output_decision":
            policy = step.get("output_policy") if isinstance(step.get("output_policy"), Mapping) else {}
            item["output_policy"] = {
                key: policy.get(key)
                for key in ("effective_endpoint", "can_data_status", "can_required")
                if policy.get(key) not in (None, "", [])
            }
            item["supporting_condition_sources"] = [
                (condition.get("source_ref") or {})
                for condition in step.get("supporting_conditions", []) or []
                if isinstance(condition, Mapping)
            ][:12]
        flow_steps.append(item)
    return {
        "status": "ready" if report.get("status") != "blocked" else "blocked",
        "report_status": report.get("status"),
        "scope": narrative.get("scope", {}),
        "executive_summary": narrative.get("executive_summary", ""),
        "narrative": list(narrative.get("narrative", []) or [])[:16],
        "alarm_assessment": {
            key: assessment.get(key)
            for key in ("status", "should_alert", "statement", "object_warning_observed", "algorithm_rising_frames", "can_tx_rising_frames", "output_endpoint", "output_authority", "can_data_status", "can_required")
            if assessment.get(key) not in (None, "", [])
        },
        "output_policy": narrative.get("output_policy", {}),
        "gdb_confirmation": {
            key: gdb_confirmation.get(key)
            for key in ("status", "actual_hit", "session_status", "evidence_status", "frame_id", "radar_id", "object_id", "function", "source_location", "captured_fields", "observed_field_count", "missing_probe_count", "statement")
            if gdb_confirmation.get(key) not in (None, "", [])
        },
        "execution_context": {
            key: execution_context.get(key)
            for key in ("data_source", "algorithm_execution", "workspace", "hilmodel", "buildmodel", "replay_strategy", "replay_mode_label", "warmup", "lgu_topic", "algorithm_warning_topic", "algorithm_warning_with_frame_topic", "algorithm_warning_source", "gdb_status", "gdb_actual_hit", "statement")
            if execution_context.get(key) not in (None, "", [])
        },
        "diagnostic_story": story_summary,
        "analysis_flow": {
            "schema_version": flow.get("schema_version"),
            "status": flow.get("status"),
            "steps": flow_steps,
        },
        "condition_assessment": narrative.get("condition_assessment", {}),
        "condition_digest": narrative.get("condition_digest", {}),
        "key_conditions": list(narrative.get("condition_items", []) or [])[:10],
        "operating_condition": narrative.get("operating_condition", {}),
        "runtime_facts": list(narrative.get("runtime_facts", []) or [])[:32],
        "can_output": narrative.get("can_output", {}),
        "geometry": {
            key: geometry.get(key)
            for key in ("status", "source", "collision_status", "collision_evidence")
            if geometry.get(key) not in (None, "", [])
        },
        "can_output": narrative.get("can_output", {}),
        "artifact_refs": [
            {"kind": key, "path": value}
            for key, value in (
                ("diagnosis_bundle", bundle_path),
                ("viewer_model", viewer_path),
                ("runtime_evidence", runtime_path),
                ("arbe_preflight", preflight_path),
                ("runtime_debug_plan", runtime_debug_plan_path),
                ("code_context", code_context_path),
                ("event_code_path", event_code_path),
                ("condition_trace", condition_trace_path),
                ("gdb_session", gdb_session_path),
            )
            if value
        ],
        "report_artifacts": report_artifacts,
        "policy": "Deterministic anchor is the fact source. Pi may explain it but must not add observed/runtime/CAN facts absent from this anchor.",
    }


def _load_pi_context_with_anchor(
    context: Any,
    *,
    context_path: str,
    evidence_anchor: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """Load the chosen context before attaching deterministic report facts."""
    resolved: dict[str, Any] | None = dict(context) if isinstance(context, Mapping) else None
    if resolved is None and context_path:
        try:
            value = json.loads(Path(context_path).expanduser().read_text(encoding="utf-8"))
            if isinstance(value, Mapping):
                resolved = dict(value)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            log.warning("PiModule: context artifact preview failed: %s", exc)
    if resolved is not None and isinstance(evidence_anchor, Mapping):
        resolved["evidence_anchor"] = dict(evidence_anchor)
    return resolved


def _select_pi_tools(
    *,
    question: str,
    case_dir: str,
    batch: str,
    interactive: bool,
    replay_strategy: str = "",
    explicit: Any = None,
) -> list[str] | None:
    """Choose a bounded Pi tool set without binding a feature or code symbol.

    Pi remains the planner.  This is only a provider-facing tool allowlist:
    it reduces tool-schema overload for models that do not reliably choose
    from a 50+ tool catalog.  The allowlist is filtered against the live
    catalog, so adding/removing modules does not create stale names.
    """
    if isinstance(explicit, (list, tuple)) and explicit:
        selected = [str(item).strip() for item in explicit if str(item).strip()]
    else:
        text = f"{question} {batch} {replay_strategy}".lower()
        # Technical vocabulary is useful when users provide it, but a target
        # lifecycle question must still reach perception tools when the user
        # describes only the symptom in business language.
        perception_terms = (
            "点云", "感知", "point cloud", "point_cloud", "perception", "cluster", "聚类",
            "track", "跟踪", "目标生成", "目标消失", "前级", "dottrans", "lgu",
        )
        perception_symptoms = (
            "目标为什么没", "为什么目标没", "目标没被", "目标未被", "目标没能",
            "没检出", "没有检出", "未检出", "漏检", "漏报", "没生成", "未生成",
            "生成失败", "目标不见", "目标消失", "突然消失", "跟踪丢失", "跟丢",
            "航迹中断", "id跳变", "id复用", "目标跳变", "missed detection",
            "not detected", "not generated", "track lost", "object disappeared", "id jump",
        )
        perception = any(token in text for token in perception_terms + perception_symptoms)
        batch_intent = bool(batch) or any(token in text for token in ("批量", "文件夹", "batch", "多个数据"))
        detail = any(token in text for token in (
            "报警", "目标", "自车", "frame", "帧", "属性", "事件", "报告", "诊断", "根因",
        )) or bool(case_dir)
        code = any(token in text for token in (
            "代码", "源码", "调用链", "调用目标", "直接下游", "下游", "上游", "被调用",
            "调用者", "函数", "callee", "caller", "callers", "callees", "变量", "参数",
            "断点", "gdb", "debug", "条件",
        ))
        runtime = any(token in text for token in (
            "runtime", "运行时", "回放", "仿真", "ros", "播放", "中间变量", "实时", "gdb", "debug", "断点",
            "objectlist", "wfsobj", "目标属性", "目标字段",
        ))
        runtime = runtime or perception
        prep = any(token in text for token in (
            "预检查", "批量", "文件夹", "bag", "传输", "部署", "可视化", "切分支", "补丁", "编译", "启动",
        ))
        diagnosis = any(token in text for token in (
            "根因", "正报", "误报", "诊断", "详细报告", "最终报告", "最终诊断", "原因", "diagnosis", "root cause",
        ))
        memory = any(token in text for token in ("记忆", "历史案例", "历史", "memory", "案例"))
        feedback = any(token in text for token in (
            "反馈", "确认", "否定", "拒绝", "无关", "标记正报", "标记误报",
            "feedback", "confirmed", "rejected", "irrelevant",
        ))
        selected = []
        if interactive:
            # Keep a compact but domain-capable starter set in ordinary Pi
            # sessions. A brittle keyword match must not make point-cloud
            # capabilities invisible for the rest of the conversation.
            selected += [
                "evidence-query", "code-analyze", "signal-extract", "data-analyze",
                "point-cloud-plan", "point-cloud-analyze", "point-cloud-read", "point-cloud-validate",
                "project-capability-manifest", "sim-verify",
            ]
        if batch_intent:
            selected.append("point-cloud-batch")
        if detail:
            selected += ["evidence-query", "alert-timeline", "diagnosis-report", "event-code-path", "condition-trace"]
        if code or detail:
            selected += [
                "code-context-read", "code-context-refresh", "code-learn", "code-analyze",
                "event-code-path", "code-gdb-plan", "arbe-preflight", "arbe-source-resolve",
            ]
        if runtime:
            selected += [
                "public-topic-plan", "public-evidence-audit", "evidence-query", "runtime-evidence-normalize",
                "runtime-evidence-validate", "runtime-evidence-compose", "runtime-evidence-merge", "runtime-debug-plan",
                "runtime-debug-run", "runtime-debug-attach", "gdb-service", "ros-topic-inventory",
                "public-runtime-normalize", "sim-verify",
            ]
        if perception:
            selected += [
                "point-cloud-plan", "point-cloud-analyze", "point-cloud-read", "point-cloud-validate", "point-cloud-batch",
                "arbe-execution-binding", "project-capability-manifest", "code-context-read",
            ]
        if prep:
            selected += [
                "cr60-intake", "cr60-precheck", "cr60-data-prep-verify", "cr60-data-transfer",
                "arbe-preflight", "arbe-source-resolve", "arbe-cuda-resolve", "arbe-patch-plan",
                "arbe-build", "arbe-formal-start", "arbe-formal-stop",
            ]
        if diagnosis:
            selected += ["diagnosis-panel", "memory-recall"]
        if memory:
            selected += ["memory-recall"]
        if feedback:
            selected += ["feedback-review", "analysis-user-observation"]
        if diagnosis or runtime or interactive:
            selected += [
                "analysis-hypothesis-record",
                "debug-experiment-record",
                "analysis-user-observation",
            ]
        # Ledger tools are always useful for progressive, resumable runs.
        selected += [
            "analysis-run-read",
            "analysis-step-record",
            "analysis-run-update",
            "analysis-claim-append",
        ]
        if interactive and not selected:
            selected += ["evidence-query", "code-analyze", "signal-extract", "data-analyze"]
        if not selected:
            # Unknown intent gets a deliberately small, high-value starter
            # set.  Pi can be restarted with an explicit tool allowlist when
            # the user changes domains.
            selected = ["evidence-query", "code-analyze", "signal-extract", "data-analyze"]

    try:
        from ai.capability.pi_tool_bridge import available_capabilities

        available = set(available_capabilities())
        selected = [name for name in dict.fromkeys(selected) if name in available]
    except Exception:  # noqa: BLE001 - bridge still receives no allowlist
        selected = list(dict.fromkeys(selected))
    return selected or None


def _select_pi_task_scope(
    *,
    question: str,
    case_dir: str,
    batch: str,
    tools: list[str] | None,
    explicit: str = "",
    kwargs: Mapping[str, Any] | None = None,
) -> str:
    """Keep code-only questions usable without inventing a recorded case."""
    requested = str(explicit or "").strip().lower()
    if requested in {"case_analysis", "source_code"}:
        return requested
    kwargs = kwargs if isinstance(kwargs, Mapping) else {}
    if case_dir or batch:
        return "case_analysis"
    case_artifacts = (
        "diagnosis_bundle_path", "viewer_model_path", "runtime_evidence_path",
        "runtime_debug_plan_path", "preflight_path", "gdb_session_path",
        "diagnostic_report_path", "perception_report_path", "condition_trace_path",
    )
    if any(kwargs.get(key) not in (None, "", []) for key in case_artifacts):
        return "case_analysis"
    text = str(question or "").lower()
    code_intent = any(token in text for token in (
        "代码", "源码", "调用链", "函数", "变量", "参数", "断点", "gdb",
        "debug", "source", "call chain", "function", "code index",
    ))
    data_or_runtime_intent = any(token in text for token in (
        "诊断", "根因", "报警", "误报", "正报", "漏检", "未检出", "没检出",
        "目标消失", "录制", "数据", "bag", "回放", "仿真", "runtime", "运行时",
        "实际命中", "实时", "attach", "selected frame",
    ))
    code_tools = {
        "code-analyze", "code-context-read", "code-context-refresh", "code-learn",
        "event-code-path", "code-gdb-plan",
    }
    if not code_intent and tools and set(tools).issubset(code_tools):
        code_intent = True
    return "source_code" if code_intent and not data_or_runtime_intent else "case_analysis"


def _derive_pi_session_id(analysis_run_id: str = "", context_run_id: str = "") -> str:
    """Keep Pi's resumable conversation ID distinct from the durable AnalysisRun ID."""
    run_id = str(analysis_run_id or "").strip()
    if run_id:
        candidate = f"pi-{run_id}"
        if len(candidate) <= 128:
            return candidate
        digest = hashlib.sha256(run_id.encode("utf-8", errors="replace")).hexdigest()[:40]
        return f"pi-{digest}"
    return str(context_run_id or "").strip()


def _ensure_current_code_context(
    *,
    project_root: str,
    project_id: str = "",
    variant_id: str = "",
) -> dict[str, str]:
    """Refresh or reuse a code context inside the configured variant snapshot area."""
    from config import (
        get_variant,
        load_config,
        resolve_snapshots_dir,
        resolve_source_docs_dir,
        resolve_variant_id,
    )
    from .code_context import CodeContextRefreshModule

    harness_root = Path(project_root or Path.cwd()).expanduser().resolve()
    config_path = harness_root / "config.yaml"
    if not config_path.is_file():
        default_root = Path(__file__).resolve().parents[2]
        if harness_root != default_root:
            raise FileNotFoundError("project config.yaml was not found at project_root")
        config_path = default_root / "config.yaml"
    config = load_config(config_path)
    variants = config.get("variants", {})

    def _configured_variant(identifier: str) -> str:
        token = str(identifier or "").strip()
        if not token:
            return resolve_variant_id(config, None)
        candidate = resolve_variant_id(config, token)
        if candidate in variants:
            return candidate
        folded = token.casefold()
        matches: list[str] = []
        for current_id, entry in variants.items():
            if not isinstance(entry, Mapping):
                continue
            coem_dir = str(entry.get("coem_project_dir") or "").replace("\\", "/").strip("/")
            aliases = {
                str(current_id),
                str(entry.get("display_name") or ""),
                str(entry.get("project_key") or ""),
                coem_dir,
                coem_dir.rsplit("/", 1)[-1] if coem_dir else "",
            }
            if any(alias and alias.casefold() == folded for alias in aliases):
                matches.append(str(current_id))
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise ValueError("project identity matches multiple configured variants")
        return candidate

    requested = str(variant_id or project_id or "").strip()
    selected_variant = _configured_variant(requested)
    if requested and project_id and variant_id:
        project_variant = _configured_variant(str(project_id))
        explicit_variant = _configured_variant(str(variant_id))
        if project_variant != explicit_variant:
            raise ValueError("project_id and variant_id resolve to different configured variants")
    variant, codebase, _ = get_variant(config, selected_variant)
    variant_raw = config.get("variants", {}).get(selected_variant, {})
    if not isinstance(variant_raw, Mapping):
        raise ValueError("configured variant entry is invalid")
    source_settings = variant_raw.get("source_context", {})
    source_settings = source_settings if isinstance(source_settings, Mapping) else {}
    configured_source_root = str(source_settings.get("source_root") or codebase.root_path or "").strip()
    if not configured_source_root:
        raise ValueError("configured variant has no source_root")
    source_root = Path(configured_source_root).expanduser().resolve()
    if not source_root.is_dir():
        raise ValueError("configured variant source_root is unavailable")

    snapshots_root = resolve_snapshots_dir(
        config, harness_root, variant_id=selected_variant
    ).expanduser().resolve()
    output_dir = (snapshots_root / "code_context_current").resolve()
    try:
        output_dir.relative_to(snapshots_root)
    except ValueError as exc:
        raise ValueError("code-context output escapes the configured variant snapshots directory") from exc

    coem_dir = str(variant_raw.get("coem_project_dir") or "").strip().replace("\\", "/")
    coem = coem_dir.rsplit("/", 1)[-1] if coem_dir else ""
    source_identity = {
        "project_id": str(variant_raw.get("display_name") or variant.display_name or selected_variant),
        "variant_id": selected_variant,
        "customer": str(variant_raw.get("customer") or ""),
        "vehicle": str(variant_raw.get("vehicle_project") or ""),
        "coem": coem,
        "configured_branch": str(source_settings.get("expected_branch") or codebase.branch or ""),
    }
    key_files = list(variant.key_source_files or [])
    source_docs_dir = resolve_source_docs_dir(
        config, harness_root, variant_id=selected_variant
    )
    refresh_started = time.perf_counter()
    refreshed = CodeContextRefreshModule().run(
        source_root=str(source_root),
        output_dir=str(output_dir),
        db_path=str(output_dir / "codegraph.db"),
        key_files=key_files or None,
        source_identity=source_identity,
        source_docs_dir=str(source_docs_dir),
        probe_git=True,
        use_ast=True,
        force=False,
    )
    refresh_duration_sec = round(time.perf_counter() - refresh_started, 6)
    if not refreshed.ok:
        raise RuntimeError(str(refreshed.message or "code-context refresh failed"))
    refresh_data = refreshed.data if isinstance(refreshed.data, Mapping) else {}
    artifacts = refresh_data.get("artifacts", {})
    artifacts = artifacts if isinstance(artifacts, Mapping) else {}
    context_path = str(artifacts.get("code_context", "") or "") if isinstance(artifacts, Mapping) else ""
    index_path = str(artifacts.get("code_index", "") or "") if isinstance(artifacts, Mapping) else ""
    if not context_path or not index_path or not Path(context_path).is_file() or not Path(index_path).is_file():
        raise RuntimeError("code-context refresh did not produce the required context and index artifacts")
    return {
        "project_id": source_identity["project_id"],
        "variant_id": selected_variant,
        "source_root": str(source_root),
        "code_context_path": str(Path(context_path).expanduser().resolve()),
        "code_index_path": str(Path(index_path).expanduser().resolve()),
        "refresh_operation": str(refresh_data.get("operation") or "unknown"),
        "refresh_duration_sec": refresh_duration_sec,
    }


class PiModule(BaseModule):
    name = "pi"
    description = "统一对话入口：按用户问题调用 radarAnalyze 能力（通过 Pi）"
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "question": {"type": "string"},
            "case_dir": {"type": "string"},
            "batch": {"type": "string"},
            "interactive": {"type": "boolean"},
            "task_scope": {"type": "string", "enum": ["case_analysis", "source_code"]},
            "provider": {"type": "string"},
            "model": {"type": "string"},
            "thinking": {
                "type": "string",
                "enum": ["off", "minimal", "low", "medium", "high", "xhigh", "max"],
            },
            "session_dir": {"type": "string"},
            "project_root": {"type": "string"},
            "project_id": {"type": "string"},
            "variant_id": {"type": "string"},
            "replay_strategy": {"type": "string"},
            "radar_id": {"type": "string"},
            "context": {"type": "object"},
            "context_path": {"type": "string"},
            "diagnosis_bundle_path": {"type": "string"},
            "viewer_model_path": {"type": "string"},
            "runtime_evidence_path": {"type": "string"},
            "runtime_debug_plan_path": {"type": "string"},
            "preflight_path": {"type": "string"},
            "preflight": {"type": "object"},
            "code_context_path": {"type": "string"},
            "event_code_path_path": {"type": "string"},
            "condition_trace_path": {"type": "string"},
            "gdb_session_path": {"type": "string"},
            "diagnostic_report_path": {"type": "string"},
            "perception_report_path": {"type": "string"},
            "event_id": {"type": "string"},
            "function": {"type": "string"},
            "side": {"type": "string"},
            "frame_id": {"type": ["string", "integer"]},
            "output_endpoint": {"type": "string", "enum": ["auto", "algorithm", "can_tx"], "default": "algorithm"},
            "can_data_status": {"type": "string", "enum": ["present", "absent", "not_detected", "unknown"]},
            "timeout": {"type": "number", "default": 300},
            "output_dir": {"type": "string"},
            "generate_report": {"type": "boolean", "default": False},
            "extension_path": {"type": "string"},
            "load_project_extension": {"type": "boolean"},
            "auto_generate_extension": {"type": "boolean"},
            "allow_builtin_tools": {"type": "boolean"},
            "tools": {"type": "array", "items": {"type": "string"}},
            "session_id": {"type": "string"},
            "analysis_run_id": {"type": "string"},
            "analysis_ledger_root": {"type": "string"},
        },
        "additionalProperties": False,
    }

    def __init__(
        self,
        *,
        case_dir: str = "",
        session_dir: str = "",
        provider: str = "",
        model: str = "",
        task_scope: str = "",
        thinking: str = "",
    ):
        super().__init__()
        self.case_dir = Path(case_dir) if case_dir else None
        self.session_dir = session_dir
        self.provider = provider
        self.model = model
        self.task_scope = task_scope
        self.thinking = thinking
        self._context: dict[str, Any] | None = None
        self._analysis_run: dict[str, Any] | None = None
        self._analysis_ledger_root: Path | None = None
        #: T10: 材料/数据身份绑定结果（cr60-intake-binding.v1）
        self._intake_binding: dict[str, Any] | None = None
        #: 运行时收集 pi 事件（流式文本 / tool_execution 等），供可观测。
        self._events: list[dict] = []
        #: Tool end events are recorded once as child AnalysisSteps.  The
        #: final dialogue step still keeps the compact turn summary.
        self._recorded_tool_event_keys: set[str] = set()
        self._recorded_anchor_keys: set[str] = set()
        self._prompt_timeout: float | None = None
        self._evidence_anchor: dict[str, Any] | None = None

    # ── 主入口 ────────────────────────────────────────────────────

    def run(self, *, question: str = "", case_dir: str = "", batch: str = "",
            interactive: bool = False, **kwargs: Any) -> ModuleResult:
        if not case_dir:
            case_dir = str(self.case_dir) if self.case_dir else ""

        if not batch and not interactive and not question:
            return ModuleResult.fail(
                "需要 question 或 --batch / --interactive", module=self.name
            )

        self._prepare_analysis_run(
            case_dir=case_dir,
            goal=question or (f"批量处理问题清单：{batch}" if batch else "Pi 交互分析"),
            batch=batch,
            interactive=interactive,
            kwargs=kwargs,
        )
        # ── T10: 材料/数据身份绑定门（G6-AC01）─────────────────────
        # 在构造 bridge / 调用模型前，把 intake 身份确定性地绑定到已配置
        # variant；歧义/缺失/错版本以业务语言问题返回，不进入 runtime。
        # 仅当存在数据/材料输入时才绑定——纯对话不涉及版本风险。
        if not batch and (case_dir or kwargs.get("material_paths") or kwargs.get("intake_path")):
            intake_binding = self._resolve_case_identity_binding(case_dir, kwargs)
            if (
                intake_binding is not None
                and intake_binding.get("status") != "resolved"
                and str(kwargs.get("_resolved_task_scope") or "") == "case_analysis"
            ):
                self._finalize_analysis_run("partial")
                return ModuleResult.fail(
                    "身份绑定未完成，已暂停分析以避免引用错误的项目或代码版本。",
                    module=self.name,
                    intake_binding_status=str(intake_binding.get("status") or ""),
                    binding=dict(intake_binding.get("binding") or {}),
                    business_questions=list(intake_binding.get("business_questions") or []),
                    version_gate=dict(intake_binding.get("version_gate") or {}),
                    intake_ref=dict(intake_binding.get("intake_ref") or {}),
                    intake_handoff_id=str(intake_binding.get("intake_handoff_id") or ""),
                    next_action="回答上述业务问题或补充材料后重新发起；已有分析进度保留在该 AnalysisRun 中。",
                    analysis_run_id=(self._analysis_run or {}).get("run_id", ""),
                    analysis_run_status=(self._analysis_run or {}).get("status", "not_created"),
                    analysis_run_path=(self._analysis_run or {}).get("artifact_path", ""),
                )
        try:
            self._prompt_timeout = float(kwargs.get("timeout")) if kwargs.get("timeout") not in (None, "") else None
        except (TypeError, ValueError):
            self._prompt_timeout = None
        # Keep the historical two-argument _build_bridge override point
        # usable for callers/tests while passing the turn intent to the
        # built-in implementation for tool allowlist selection.
        bridge_kwargs = dict(kwargs)
        bridge_kwargs.update({
            "_pi_question": question,
            "_pi_batch": batch,
            "_pi_interactive": interactive,
        })
        bridge = self._build_bridge(case_dir, bridge_kwargs)
        if bridge is None:
            return ModuleResult.fail("pi 不可用（未安装或缺少 provider）", module=self.name)
        if bridge_kwargs.get("_resolved_task_scope") == "source_code":
            resolution_error = bridge_kwargs.get("_source_context_resolution_error")
            context = self._context if isinstance(self._context, Mapping) else {}
            source = context.get("source") if isinstance(context.get("source"), Mapping) else {}
            code_context = source.get("code_context") if isinstance(source.get("code_context"), Mapping) else {}
            source_hash = source.get("source_snapshot_hash") or code_context.get("source_snapshot_hash")
            binding_missing = [
                key for key in (
                    "code_context_path", "code_context_sha256",
                    "code_index_path", "code_index_hash", "source_root", "source_snapshot_hash",
                )
                if not code_context.get(key)
            ]
            if resolution_error or not source_hash or binding_missing or context.get("status") == "blocked":
                return ModuleResult.fail(
                    "当前配置的源码快照未能通过身份与索引校验，查询已暂停以避免引用旧代码索引。",
                    module=self.name,
                    task_scope="source_code",
                    context_status=context.get("status", "not_created"),
                    context_missing=list(context.get("missing", []) or []),
                    context_conflicts=list(context.get("conflicts", []) or []),
                    diagnostics=[
                        *list(context.get("diagnostics", []) or []),
                        *( ["code_context_index_binding_incomplete"] if binding_missing else [] ),
                    ],
                    code_context_binding_missing=binding_missing,
                    source_context_resolution_error=(
                        type(resolution_error).__name__ if isinstance(resolution_error, BaseException)
                        else str(resolution_error or "")
                    ),
                )

        try:
            if batch:
                return self._run_batch(bridge, batch)
            if interactive:
                return self._run_interactive(bridge)
            result = self._prompt_with_ledger(bridge, question)
            module_result = self._result_from_prompt(result, case_dir)
            self._finalize_analysis_run("completed" if module_result.ok else "partial")
            if self._analysis_run:
                module_result.data.update({
                    "analysis_run_id": self._analysis_run.get("run_id", ""),
                    "analysis_run_status": self._analysis_run.get("status", "not_created"),
                    "analysis_run_path": self._analysis_run.get("artifact_path", ""),
                })
            return module_result
        except Exception as exc:  # noqa: BLE001
            log.exception("PiModule.run failed")
            return ModuleResult.fail(f"{type(exc).__name__}: {exc}", module=self.name)

    # ── 实现 ──────────────────────────────────────────────────────

    def _build_bridge(
        self,
        case_dir: str,
        kwargs: dict,
        *,
        question: str = "",
        batch: str = "",
        interactive: bool = False,
    ):
        """构造 PiBridge；provider/model 取 CLI/构造优先级。

        session_dir 未显式指定时，从项目隔离上下文派生
        ``<workspace>/sessions/<project>``（P6 会话绑定项目），保证跨项目
        会话树不串扰。
        """
        from ai.pi_bridge import DEFAULT_PI_SOURCE_SYSTEM_PROMPT, PiBridge
        question = question or str(kwargs.get("_pi_question") or "")
        batch = batch or str(kwargs.get("_pi_batch") or "")
        interactive = bool(interactive or kwargs.get("_pi_interactive", False))
        provider = kwargs.get("provider") or self.provider or ""
        model = kwargs.get("model") or self.model or ""
        session_dir = kwargs.get("session_dir") or self.session_dir or ""
        project_root = kwargs.get("project_root") or str(Path.cwd())
        context = kwargs.get("context")
        context_path = kwargs.get("context_path") or ""
        extension_path = kwargs.get("extension_path") or ""
        load_project_extension = kwargs.get("load_project_extension", True)
        auto_generate_extension = kwargs.get("auto_generate_extension", True)
        allow_builtin_tools = kwargs.get("allow_builtin_tools", False)
        tools = _select_pi_tools(
            question=question,
            case_dir=case_dir,
            batch=batch,
            interactive=interactive,
            replay_strategy=str(kwargs.get("replay_strategy") or ""),
            explicit=kwargs.get("tools"),
        )
        task_scope = _select_pi_task_scope(
            question=question,
            case_dir=case_dir,
            batch=batch,
            tools=tools,
            explicit=str(kwargs.get("task_scope") or self.task_scope or ""),
            kwargs=kwargs,
        )
        kwargs["_resolved_task_scope"] = task_scope
        if task_scope == "source_code":
            source_read_only_tool_order = [
                "code-context-read", "code-analyze", "event-code-path", "code-gdb-plan",
            ]
            source_read_only_tools = set(source_read_only_tool_order)
            tools = [name for name in (tools or []) if name in source_read_only_tools]
            if not kwargs.get("tools") and not tools:
                tools = list(source_read_only_tool_order)
        system_prompt = str(kwargs.get("system_prompt") or "")
        if not system_prompt and task_scope == "source_code":
            system_prompt = DEFAULT_PI_SOURCE_SYSTEM_PROMPT
        load_context_files = kwargs.get("load_context_files")
        if load_context_files is None:
            # Source-only queries use a compact, scope-specific prompt and the
            # bound code-context artifact instead of loading the entire project
            # instruction tree into a constrained provider context.
            load_context_files = task_scope != "source_code"
        discover_extensions = kwargs.get("discover_extensions")
        if discover_extensions is None:
            discover_extensions = task_scope != "source_code"
        load_skills = kwargs.get("load_skills")
        if load_skills is None:
            load_skills = task_scope != "source_code"
        discovered = discover_case_artifacts(case_dir)
        intake_context_path = kwargs.get("intake_path") or discovered.get("intake_path", "")
        diagnosis_bundle_path = kwargs.get("diagnosis_bundle_path") or discovered.get("diagnosis_bundle_path", "")
        viewer_model_path = kwargs.get("viewer_model_path") or discovered.get("viewer_model_path", "")
        runtime_evidence_path = kwargs.get("runtime_evidence_path") or discovered.get("runtime_evidence_path", "")
        runtime_debug_plan_path = kwargs.get("runtime_debug_plan_path") or discovered.get("runtime_debug_plan_path", "")
        preflight_path = kwargs.get("preflight_path") or discovered.get("preflight_path", "")
        preflight = kwargs.get("preflight") if isinstance(kwargs.get("preflight"), Mapping) else None
        code_context_path = kwargs.get("code_context_path") or discovered.get("code_context_path", "")
        if task_scope == "source_code" and not code_context_path:
            try:
                current_code = _ensure_current_code_context(
                    project_root=project_root,
                    project_id=str(kwargs.get("project_id") or ""),
                    variant_id=str(kwargs.get("variant_id") or ""),
                )
                self._record_code_context_metrics(current_code)
                code_context_path = current_code["code_context_path"]
                kwargs["code_context_path"] = code_context_path
                kwargs["code_index_path"] = current_code["code_index_path"]
                kwargs["project_id"] = current_code["project_id"]
                kwargs["variant_id"] = current_code["variant_id"]
            except Exception as exc:  # noqa: BLE001 - fail closed before provider call
                self._record_code_context_metrics({"refresh_operation": "failed"})
                kwargs["_source_context_resolution_error"] = exc
                log.warning("PiModule: current source context refresh failed: %s", exc)
        event_code_path_path = kwargs.get("event_code_path_path") or discovered.get("event_code_path_path", "")
        condition_trace_path = kwargs.get("condition_trace_path") or discovered.get("condition_trace_path", "")
        diagnostic_report_path = kwargs.get("diagnostic_report_path") or discovered.get("diagnostic_report_path", "")
        evidence_anchor = _build_evidence_anchor(
            question=question,
            case_dir=case_dir,
            discovered={**discovered, "viewer_model_path": viewer_model_path, "preflight_path": preflight_path, "code_context_path": code_context_path, "event_code_path_path": event_code_path_path, "condition_trace_path": condition_trace_path},
            kwargs={
                **kwargs,
                "runtime_evidence_path": runtime_evidence_path,
                "preflight": preflight,
                "preflight_path": preflight_path,
                "runtime_debug_plan_path": runtime_debug_plan_path,
                "code_context_path": code_context_path,
                "condition_trace_path": condition_trace_path,
                "analysis_run_path": str((self._analysis_run or {}).get("artifact_path") or ""),
            },
            output_dir=self._resolve_report_output_dir(kwargs, question),
        )
        self._evidence_anchor = evidence_anchor
        self._record_evidence_anchor_step(evidence_anchor)
        analysis_run = self._analysis_run or {}
        analysis_run_id = str(analysis_run.get("run_id") or "")
        analysis_run_ref = str(analysis_run.get("artifact_path") or "")
        run_id = str(kwargs.get("run_id") or analysis_run_id or "")
        artifact_refs = list(kwargs.get("artifact_refs") or [])
        for key, path in discovered.items():
            artifact_refs.append({"kind": key, "path": path})
        for key, path in (
            ("diagnosis_bundle_path", diagnosis_bundle_path),
            ("viewer_model_path", viewer_model_path),
            ("runtime_evidence_path", runtime_evidence_path),
            ("runtime_debug_plan_path", runtime_debug_plan_path),
            ("preflight_path", preflight_path),
            ("code_context_path", code_context_path),
            ("event_code_path_path", event_code_path_path),
            ("condition_trace_path", condition_trace_path),
            ("gdb_session_path", str(kwargs.get("gdb_session_path") or "")),
            ("diagnostic_report_path", diagnostic_report_path),
            ("perception_report_path", str(kwargs.get("perception_report_path") or discovered.get("perception_report_path", ""))),
        ):
            if path and not any(item.get("kind") == key and item.get("path") == path for item in artifact_refs):
                artifact_refs.append({"kind": key, "path": path})
        if evidence_anchor:
            for path in evidence_anchor.get("report_artifacts", []) or []:
                if path and not any(item.get("path") == path for item in artifact_refs):
                    artifact_refs.append({"kind": "diagnostic_report", "path": path})
        if analysis_run_ref:
            artifact_refs.append({
                "kind": "analysis_run",
                "path": analysis_run_ref,
                "schema_version": "analysis-run.v1",
            })
        if self._analysis_ledger_root:
            artifact_refs.append({
                "kind": "analysis_ledger_root",
                "path": str(self._analysis_ledger_root),
                "schema_version": "analysis-run.v1",
            })
        if not isinstance(context, dict) and not context_path:
            # Give every Pi prompt a deterministic binding, even if it is
            # partial and Pi must ask the user for identity/source fields.
            try:
                from engines.pi_context import build_pi_orchestration_context

                context = build_pi_orchestration_context(
                    task_scope=task_scope,
                    case_dir=case_dir,
                    project_root=project_root,
                    project_id=str(kwargs.get("project_id") or ""),
                    variant_id=str(kwargs.get("variant_id") or ""),
                    replay_strategy=str(kwargs.get("replay_strategy") or ""),
                    radar_id=str(kwargs.get("radar_id") or ""),
                    run_id=run_id,
                    artifact_refs=artifact_refs,
                    intake_path=intake_context_path,
                    preflight=preflight,
                    preflight_path=preflight_path,
                    code_context_path=code_context_path,
                    runtime_evidence_path=runtime_evidence_path,
                    diagnosis_bundle_path=diagnosis_bundle_path,
                    runtime_debug_plan_path=runtime_debug_plan_path,
                )
            except Exception as exc:  # noqa: BLE001 - context boundary
                log.warning("PiModule: automatic context build failed: %s", exc)
                context = None
        self._context = _load_pi_context_with_anchor(
            context,
            context_path=context_path,
            evidence_anchor=evidence_anchor,
        )
        self._persist_context_artifact()
        self._sync_analysis_run_context()
        source = self._context.get("source", {}) if isinstance(self._context, Mapping) else {}
        source = source if isinstance(source, Mapping) else {}
        source_code_context = source.get("code_context", {})
        source_code_context = source_code_context if isinstance(source_code_context, Mapping) else {}
        project = self._context.get("project", {}) if isinstance(self._context, Mapping) else {}
        project = project if isinstance(project, Mapping) else {}
        code_index_binding = {
            "task_scope": task_scope,
            "code_context_path": source_code_context.get("code_context_path"),
            "code_context_sha256": source_code_context.get("code_context_sha256"),
            "code_index_path": source_code_context.get("code_index_path"),
            "code_index_hash": source_code_context.get("code_index_hash"),
            "source_root": source_code_context.get("source_root"),
            "source_snapshot_hash": source_code_context.get("source_snapshot_hash"),
            "project_id": project.get("project_id"),
            "variant_id": project.get("variant_id"),
        }
        if not all(code_index_binding.get(key) for key in (
            "code_index_path", "code_index_hash", "source_root", "source_snapshot_hash",
        )):
            code_index_binding = {}
        if not session_dir:
            derived = self._derive_session_dir(case_dir, kwargs)
            if derived:
                session_dir = str(derived)
        try:
            return PiBridge(
                provider=provider, model=model,
                thinking=str(kwargs.get("thinking") or self.thinking or ""),
                system_prompt=system_prompt,
                load_context_files=bool(load_context_files),
                discover_extensions=bool(discover_extensions),
                load_skills=bool(load_skills),
                replace_system_prompt=task_scope == "source_code",
                session_dir=session_dir or None,
                on_event=self._on_event,
                project_root=project_root,
                extension_path=extension_path or None,
                load_project_extension=bool(load_project_extension),
                auto_generate_extension=bool(auto_generate_extension),
                allow_builtin_tools=bool(allow_builtin_tools),
                tools=tools,
                context=self._context,
                context_path=context_path or None,
                session_id=(
                    str(kwargs.get("session_id") or "")
                    or _derive_pi_session_id(
                        analysis_run_id,
                        str((self._context or {}).get("run_id") or ""),
                    )
                ),
                analysis_run_id=analysis_run_id,
                analysis_ledger_root=str(self._analysis_ledger_root or ""),
                code_index_binding=code_index_binding,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("PiModule: PiBridge 构造失败: %s", exc)
            return None

    def _record_evidence_anchor_step(self, anchor: Mapping[str, Any] | None) -> None:
        """Record the deterministic report anchor as a visible ledger step."""
        if not isinstance(anchor, Mapping) or not self._analysis_run or not self._analysis_ledger_root:
            return
        try:
            key = hashlib.sha256(
                json.dumps(anchor, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
            ).hexdigest()
        except (TypeError, ValueError):
            key = repr(anchor)
        if key in self._recorded_anchor_keys:
            return
        self._recorded_anchor_keys.add(key)
        try:
            from engines.analysis_ledger import AnalysisLedger

            ledger = AnalysisLedger(self._analysis_ledger_root)
            step = ledger.begin_step(
                str(self._analysis_run["run_id"]),
                stage="evidence-anchor",
                tool_calls=[{"name": "diagnosis-report", "event_type": "deterministic_projection", "status": str(anchor.get("status", "partial"))}],
                created_by="pi",
            )
            refs = [dict(item) for item in anchor.get("artifact_refs", []) or [] if isinstance(item, Mapping) and item.get("path")]
            refs.extend({"kind": "diagnostic_report", "path": path} for path in anchor.get("report_artifacts", []) or [] if path)
            status = "completed" if anchor.get("status") == "ready" else "partial"
            gaps = [] if status == "completed" else [{
                "id": "deterministic_anchor_incomplete",
                "status": "partial",
                "reason": str(anchor.get("error") or "anchor is partial"),
            }]
            ledger.complete_step(
                str(self._analysis_run["run_id"]),
                str(step["step_id"]),
                status=status,
                output_artifact_refs=refs,
                observations=[{
                    "kind": "deterministic_evidence_anchor",
                    "scope": anchor.get("scope", {}),
                    "should_alert": (anchor.get("alarm_assessment") or {}).get("should_alert"),
                    "condition_scope": (anchor.get("condition_digest") or {}).get("scope"),
                    "collision_status": (anchor.get("geometry") or {}).get("collision_status"),
                }],
                gaps=gaps,
                user_visible_summary="已生成确定性报告事实锚点" if status == "completed" else "确定性报告事实锚点不完整",
                next_action_candidates=[],
            )
            self._analysis_run = ledger.read_run(str(self._analysis_run["run_id"]))
        except Exception as exc:  # noqa: BLE001 - ledger is observability only
            log.warning("PiModule: record evidence anchor step failed: %s", exc)

    def _record_code_context_metrics(self, outcome: Mapping[str, Any]) -> None:
        """Accumulate source-index refresh/reuse metrics for this AnalysisRun."""
        if not self._analysis_run or not self._analysis_ledger_root:
            return
        operation = str(outcome.get("refresh_operation") or outcome.get("operation") or "").strip().lower()
        metrics: dict[str, float] = {"code_index_refresh_attempt_count": 1}
        if operation == "built":
            metrics["code_index_build_count"] = 1
        elif operation == "reused":
            metrics["code_index_cache_hit_count"] = 1
        elif operation == "failed":
            metrics["code_index_refresh_failure_count"] = 1
        else:
            metrics["code_index_refresh_unknown_count"] = 1
        try:
            elapsed = float(outcome.get("refresh_duration_sec") or 0)
        except (TypeError, ValueError):
            elapsed = 0
        if 0 <= elapsed < 3600:
            metrics["code_index_refresh_duration_sec_total"] = elapsed
        try:
            from engines.analysis_ledger import AnalysisLedger

            ledger = AnalysisLedger(self._analysis_ledger_root)
            self._analysis_run = ledger.update_run(
                str(self._analysis_run["run_id"]),
                metrics=metrics,
                metric_mode="increment",
                actor="pi",
            )
        except Exception as exc:  # noqa: BLE001 - metrics must not disable Pi
            log.warning("PiModule: code context metrics update failed: %s", exc)

    def _resolve_report_output_dir(self, kwargs: Mapping[str, Any], question: str) -> str:
        """Resolve a local report directory only for an explicit report request."""
        explicit = str(kwargs.get("output_dir") or "").strip()
        requested = bool(kwargs.get("generate_report")) or any(token in str(question or "").lower() for token in (
            "生成报告", "详细报告", "诊断报告", "导出报告", "generate report", "diagnostic report",
        ))
        if explicit:
            return explicit
        if not requested or not self._analysis_run:
            return ""
        run_dir = str(self._analysis_run.get("run_dir") or "").strip()
        return str(Path(run_dir).resolve() / "diagnostic-report") if run_dir else ""

    def _prepare_analysis_run(
        self,
        *,
        case_dir: str,
        goal: str,
        kwargs: dict[str, Any],
        batch: str = "",
        interactive: bool = False,
    ) -> None:
        """Create or resume the durable run used by Pi's progressive UI.

        The ledger is local orchestration state, not a replacement for the
        evidence artifacts.  Creating it here lets a one-shot Pi question and
        an interactive session share the same run without asking the user to
        understand ledger internals.
        """
        requested_id = str(kwargs.get("analysis_run_id") or "").strip()
        if self._analysis_run is not None and not requested_id:
            return
        available_tools = _select_pi_tools(
            question=goal,
            case_dir=case_dir,
            batch=batch,
            interactive=interactive,
            replay_strategy=str(kwargs.get("replay_strategy") or ""),
            explicit=kwargs.get("tools"),
        )
        task_scope = _select_pi_task_scope(
            question=goal,
            case_dir=case_dir,
            batch=batch,
            tools=available_tools,
            explicit=str(
                kwargs.get("_resolved_task_scope")
                or kwargs.get("task_scope")
                or self.task_scope
                or ""
            ),
            kwargs=kwargs,
        )
        kwargs["_resolved_task_scope"] = task_scope
        if not requested_id and not (
            case_dir
            or kwargs.get("context")
            or kwargs.get("context_path")
            or kwargs.get("batch")
            or batch
            or interactive
            or kwargs.get("analysis_ledger_root")
            or task_scope == "source_code"
        ):
            return
        try:
            from engines.analysis_ledger import AnalysisLedger

            project_root = Path(kwargs.get("project_root") or Path.cwd()).expanduser().resolve()
            ledger_root = Path(
                str(kwargs.get("analysis_ledger_root") or project_root / "outputs" / "analysis_runs")
            ).expanduser()
            if not ledger_root.is_absolute():
                ledger_root = project_root / ledger_root
            ledger = AnalysisLedger(ledger_root.resolve())
            discovered_refs = [
                {"kind": key, "path": path}
                for key, path in discover_case_artifacts(case_dir).items()
            ]
            explicit_refs = [
                {"kind": key, "path": str(kwargs.get(key))}
                for key in (
                    "diagnosis_bundle_path", "viewer_model_path", "runtime_evidence_path",
                    "runtime_debug_plan_path", "preflight_path", "event_code_path_path", "diagnostic_report_path",
                    "perception_report_path",
                    "code_context_path", "condition_trace_path", "gdb_session_path",
                )
                if kwargs.get(key) not in (None, "", [])
            ]
            for ref in explicit_refs:
                if ref not in discovered_refs:
                    discovered_refs.append(ref)
            if requested_id:
                self._analysis_run = ledger.read_run(requested_id)
            else:
                self._analysis_run = ledger.create_run(
                    owner=str(kwargs.get("operator") or "pi"),
                    goal={
                        "question": str(goal or "Pi analysis"),
                        "case_dir": str(case_dir or ""),
                        "mode": "dialogue",
                        "task_scope": task_scope,
                    },
                    binding={
                        key: kwargs.get(key)
                        for key in ("project_id", "variant_id", "replay_strategy", "radar_id")
                        if kwargs.get(key) not in (None, "", [])
                    },
                    policy={"execution": "plan_only"},
                    artifact_refs=discovered_refs,
                )
            self._analysis_ledger_root = ledger_root.resolve()
            kwargs["analysis_run_id"] = str(self._analysis_run.get("run_id") or "")
            kwargs["analysis_ledger_root"] = str(self._analysis_ledger_root)
        except Exception as exc:  # noqa: BLE001 - ledger must not disable Pi
            log.warning("PiModule: analysis run unavailable: %s", exc)
            self._analysis_run = None
            self._analysis_ledger_root = None

    def _resolve_case_identity_binding(
        self,
        case_dir: str,
        kwargs: dict[str, Any],
    ) -> dict[str, Any] | None:
        """T10：把材料/数据身份确定性绑定到已配置 variant（case_analysis 专用）。

        优先级：case 元数据匹配 > 显式 ``--intake`` artifact > case 目录内发现的
        intake artifact > ``--material`` 现场解析（in-process cr60-intake，只读）>
        显式 variant > 单配置项目自动复用。产出 ``cr60-intake-binding.v1``；
        resolved 时把 variant_id 注入 kwargs 供 context builder 与 run 绑定使用。
        source_code / batch 跳过（source_code 无数据需求；batch 由后续切片处理）。
        """
        from engines.arbe.intake_binding import bind_intake_identity, load_intake_artifact

        if str(kwargs.get("_resolved_task_scope") or "") != "case_analysis":
            return None
        try:
            from config import load_config

            config = load_config()
        except Exception as exc:  # noqa: BLE001 - fail-closed via empty config
            log.warning("PiModule: config load for intake binding failed: %s", exc)
            config = {}

        intake_payload: dict[str, Any] | None = None
        intake_path = str(kwargs.get("intake_path") or "")
        intake_sha = ""
        if not intake_path and case_dir:
            discovered = discover_case_artifacts(case_dir)
            intake_path = str(discovered.get("intake_path") or "")
        if intake_path:
            intake_payload, intake_sha = load_intake_artifact(intake_path)
            if intake_payload is None:
                log.warning("PiModule: intake artifact unreadable: %s", intake_path)

        material_paths = kwargs.get("material_paths") or []
        if intake_payload is None and material_paths:
            try:
                from ai.modules.cr60_intake import CR60IntakeModule

                material_result = CR60IntakeModule().run(
                    data_paths=[str(case_dir)] if case_dir else [],
                    material_paths=[str(item) for item in material_paths if str(item).strip()],
                    match_text=str(kwargs.get("match_text") or ""),
                )
                if material_result.ok and isinstance(material_result.data, Mapping):
                    candidate = {
                        key: value
                        for key, value in material_result.data.items()
                        if key != "artifact_path"
                    }
                    if candidate.get("schema_version"):
                        intake_payload = candidate
                        if material_result.artifacts:
                            intake_path = str(material_result.artifacts[0])
            except Exception as exc:  # noqa: BLE001 - material parsing is optional
                log.warning("PiModule: in-process material intake failed: %s", exc)

        case_variant: dict[str, Any] | None = None
        case_variant_error = ""
        if case_dir:
            try:
                import cli as _cli

                case_variant = _cli._resolve_variant_from_case_metadata(config, case_dir)
            except ValueError as exc:
                case_variant_error = str(exc)
            except Exception as exc:  # noqa: BLE001 - metadata is optional identity input
                log.debug("PiModule: case metadata variant resolution skipped: %s", exc)

        binding = bind_intake_identity(
            intake_payload,
            config,
            case_variant=case_variant,
            case_variant_error=case_variant_error,
            explicit_variant_id=str(kwargs.get("variant_id") or ""),
            intake_path=intake_path,
            intake_sha256=intake_sha,
        )
        self._intake_binding = binding
        if binding.get("status") == "resolved":
            bound_variant = str((binding.get("binding") or {}).get("variant_id") or "")
            if bound_variant and not str(kwargs.get("variant_id") or "").strip():
                kwargs["variant_id"] = bound_variant
        return binding

    def _persist_context_artifact(self) -> None:
        """Persist the compact context next to the run when a run exists."""
        if not isinstance(self._context, dict) or not self._analysis_run:
            return
        run_dir = self._analysis_run.get("run_dir")
        if not run_dir:
            return
        try:
            path = Path(str(run_dir)).expanduser().resolve() / "pi-orchestration-context.json"
            path.write_text(json.dumps(self._context, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            self._context["artifact_path"] = str(path)
        except OSError as exc:
            log.warning("PiModule: context artifact write failed: %s", exc)

    def _sync_analysis_run_context(self) -> None:
        """Bind the durable run to the exact context used by this Pi turn."""
        if not isinstance(self._context, Mapping) or not self._analysis_run or not self._analysis_ledger_root:
            return
        try:
            from engines.analysis_ledger import AnalysisLedger

            project = self._context.get("project") if isinstance(self._context.get("project"), Mapping) else {}
            data = self._context.get("data") if isinstance(self._context.get("data"), Mapping) else {}
            source = self._context.get("source") if isinstance(self._context.get("source"), Mapping) else {}
            build = self._context.get("build") if isinstance(self._context.get("build"), Mapping) else {}
            binding = {
                key: value
                for key, value in {
                    "project_id": project.get("project_id"),
                    "variant_id": project.get("variant_id"),
                    "customer": project.get("customer"),
                    "vehicle": project.get("vehicle"),
                    "coem": project.get("coem"),
                    "data_fingerprint": data.get("data_fingerprint"),
                    "source_context_id": source.get("source_context_id"),
                    "source_snapshot_hash": source.get("source_snapshot_hash"),
                    "code_index_hash": source.get("code_index_hash"),
                    "binary_fingerprint": build.get("binary_fingerprint"),
                }.items()
                if value not in (None, "", [])
            }
            refs = [
                dict(item)
                for item in self._context.get("artifacts", []) or []
                if isinstance(item, Mapping) and item.get("path")
            ]
            binding_result = self._intake_binding if isinstance(self._intake_binding, Mapping) else {}
            if binding_result:
                handoff_id = str(binding_result.get("intake_handoff_id") or "")
                if handoff_id:
                    binding["intake_handoff_id"] = handoff_id
                binding["intake_binding_status"] = str(binding_result.get("status") or "")
                intake_ref = binding_result.get("intake_ref") if isinstance(binding_result.get("intake_ref"), Mapping) else {}
                intake_ref_path = str(intake_ref.get("path") or "")
                if intake_ref_path and not any(
                    item.get("path") == intake_ref_path for item in refs
                ):
                    refs.append({
                        "kind": "intake",
                        "path": intake_ref_path,
                        "schema_version": "cr60-analysis-intake.v1",
                    })
            ledger = AnalysisLedger(self._analysis_ledger_root)
            self._analysis_run = ledger.update_run(
                str(self._analysis_run["run_id"]),
                binding=binding,
                artifact_refs=refs,
                actor="pi",
            )
        except Exception as exc:  # noqa: BLE001 - binding is a quality layer
            log.warning("PiModule: analysis context binding failed: %s", exc)

    def _prompt_with_ledger(self, bridge: Any, question: str) -> dict[str, Any]:
        start = len(self._events)
        if self._prompt_timeout is None:
            result = bridge.prompt(question)
        else:
            result = bridge.prompt(question, timeout=self._prompt_timeout)
        context = self._context if isinstance(self._context, Mapping) else {}
        if context.get("task_scope") == "source_code" and result.get("status") == "ok":
            event_summary = result.get("event_summary")
            event_summary = event_summary if isinstance(event_summary, Mapping) else {}
            allowed_source_tools = {
                "code-analyze", "code-context-read", "event-code-path", "code-gdb-plan",
            }
            successful_source_tool = any(
                isinstance(event, Mapping)
                and str(event.get("name") or "") in allowed_source_tools
                and str(event.get("status") or "").lower() in {"ok", "success", "completed"}
                for event in event_summary.get("tool_events", []) or []
            )
            if not successful_source_tool:
                # Source claims must be derived from one of the bound static
                # code tools. Discard ungrounded final text and persist a
                # partial/failed turn instead of treating agent_settled as success.
                result = {
                    **result,
                    "status": "error",
                    "answer": "",
                    "message": "source_code_tool_evidence_missing",
                }
        self._record_prompt_step(question, result, self._events[start:])
        return result

    def _record_prompt_step(
        self,
        question: str,
        result: Mapping[str, Any],
        events: list[dict[str, Any]],
    ) -> None:
        """Append one user-visible dialogue step without storing model CoT."""
        if not self._analysis_run or not self._analysis_ledger_root:
            return
        try:
            from engines.analysis_ledger import AnalysisLedger

            tool_calls: list[dict[str, Any]] = []
            artifact_refs: list[dict[str, Any]] = []
            for event in events:
                if not isinstance(event, Mapping):
                    continue
                event_type = str(event.get("type") or "")
                if "tool" in event_type.lower():
                    name = event.get("toolName") or event.get("tool_name") or event.get("name")
                    if name:
                        nested_result = event.get("result") if isinstance(event.get("result"), Mapping) else {}
                        tool_calls.append({
                            "name": str(name),
                            "event_type": event_type,
                            "status": str(event.get("status") or nested_result.get("status", "observed")),
                        })
                artifact_refs.extend(self._event_artifact_refs(event))
            # Preserve event order while avoiding duplicate refs from the
            # tool-execution start/end pair and nested JSON envelopes.
            deduped_refs: list[dict[str, Any]] = []
            for ref in artifact_refs:
                if ref not in deduped_refs:
                    deduped_refs.append(ref)
            ledger = AnalysisLedger(self._analysis_ledger_root)
            step = ledger.begin_step(
                str(self._analysis_run["run_id"]),
                stage="dialogue",
                tool_calls=tool_calls,
                created_by="pi",
            )
            status = "completed" if result.get("status") == "ok" else "partial"
            gaps = [] if status == "completed" else [{
                "id": "pi_turn_incomplete",
                "status": "partial",
                "reason": str(result.get("message") or result.get("status") or "Pi turn did not settle"),
            }]
            ledger.complete_step(
                str(self._analysis_run["run_id"]),
                str(step["step_id"]),
                status=status,
                output_artifact_refs=deduped_refs,
                observations=[{
                    "kind": "pi_dialogue_turn",
                    "question": str(question or "")[:1000],
                    "result_status": result.get("status"),
                    "event_count": int(result.get("event_count", len(events)) or 0),
                    "answer_available": bool(result.get("answer")),
                }],
                gaps=gaps,
                user_visible_summary=("Pi 已完成本轮分析" if status == "completed" else "Pi 本轮分析未完整结束，保留缺口"),
                next_action_candidates=[],
            )
            self._analysis_run = ledger.read_run(str(self._analysis_run["run_id"]))
        except Exception as exc:  # noqa: BLE001 - ledger is observability, not truth
            log.warning("PiModule: record dialogue step failed: %s", exc)

    @classmethod
    def _event_artifact_refs(cls, event: Mapping[str, Any]) -> list[dict[str, Any]]:
        """Extract artifact refs from Pi's nested tool result envelope.

        Pi custom tools return ``details: out``.  Depending on the Pi version,
        the RPC event places that object under ``result``, ``details`` or a
        JSON text content block.  Ledger observability must understand all
        three without treating arbitrary model prose as an artifact.
        """
        refs: list[dict[str, Any]] = []

        def visit(value: Any, depth: int = 0) -> None:
            if depth > 4:
                return
            if isinstance(value, Mapping):
                for key in ("artifacts", "artifact_paths"):
                    items = value.get(key)
                    if isinstance(items, list):
                        for item in items:
                            if isinstance(item, Mapping) and item.get("path"):
                                refs.append(dict(item))
                            elif isinstance(item, str) and item.strip():
                                refs.append({"path": item.strip(), "source": "pi_tool_event"})
                    elif isinstance(items, str) and items.strip():
                        refs.append({"path": items.strip(), "source": "pi_tool_event"})
                for key in ("artifact_path", "output_path"):
                    item = value.get(key)
                    if isinstance(item, str) and item.strip():
                        refs.append({"path": item.strip(), "source": "pi_tool_event"})
                for key in ("result", "details", "data", "content", "text"):
                    child = value.get(key)
                    if isinstance(child, str) and key == "text" and len(child) <= 1_000_000:
                        try:
                            decoded = json.loads(child)
                        except (TypeError, ValueError):
                            decoded = None
                        if decoded is not None:
                            visit(decoded, depth + 1)
                    else:
                        visit(child, depth + 1)
            elif isinstance(value, list):
                for item in value[:80]:
                    visit(item, depth + 1)

        visit(event)
        return refs

    def _finalize_analysis_run(self, status: str) -> None:
        if not self._analysis_run or not self._analysis_ledger_root:
            return
        try:
            from engines.analysis_ledger import AnalysisLedger

            ledger = AnalysisLedger(self._analysis_ledger_root)
            self._analysis_run = ledger.update_run(
                str(self._analysis_run["run_id"]),
                status=status,
                current_stage="deliver",
                actor="pi",
            )
        except Exception as exc:  # noqa: BLE001 - observability only
            log.warning("PiModule: finalize analysis run failed: %s", exc)

    def _derive_session_dir(self, case_dir: str, kwargs: dict):
        """从项目上下文解析 pi 会话目录（P6 项目隔离）。"""
        from pathlib import Path
        try:
            from config import load_config
            from ai.capability import resolve_project_context_from_case
            root = kwargs.get("project_root") or str(Path.cwd())
            cfg = load_config()
            src = case_dir if case_dir and Path(case_dir).exists() else root
            ctx = resolve_project_context_from_case(cfg, root, src)
            sessions = ctx.workspace_dir / "sessions"
            return sessions / ctx.namespace()
        except Exception as exc:  # noqa: BLE001
            log.warning("PiModule: session-dir 派生失败: %s", exc)
            return None

    def _on_event(self, ev: dict) -> None:
        self._events.append(ev)
        self._record_tool_step(ev)

    def _record_tool_step(self, event: Mapping[str, Any]) -> None:
        """Persist one completed Pi tool call as a visible ledger step.

        Pi versions place the custom-tool result under slightly different
        keys.  This method records only tool metadata/status/artifact refs, not
        model reasoning or arbitrary prompt text.  It is observability: a
        failure here must never change the tool result.
        """
        if not self._analysis_run or not self._analysis_ledger_root or not isinstance(event, Mapping):
            return
        event_type = str(event.get("type") or "").lower()
        if "tool" not in event_type:
            return
        if not ("end" in event_type or "result" in event_type or "complete" in event_type):
            return
        name = event.get("toolName") or event.get("tool_name") or event.get("name")
        if not name:
            return
        try:
            event_json = json.dumps(event, ensure_ascii=False, sort_keys=True, default=str)
            event_key = hashlib.sha256(event_json.encode("utf-8", errors="replace")).hexdigest()
        except (TypeError, ValueError):
            event_key = f"{event_type}:{name}:{len(self._events)}"
        if event_key in self._recorded_tool_event_keys:
            return
        self._recorded_tool_event_keys.add(event_key)
        try:
            from engines.analysis_ledger import AnalysisLedger

            result = event.get("result") if isinstance(event.get("result"), Mapping) else {}
            event_details = event.get("details") if isinstance(event.get("details"), Mapping) else {}
            if not result and event_details:
                result = event_details
            result_details = (
                result.get("details")
                if isinstance(result.get("details"), Mapping)
                else event_details
            )
            raw_status = str(
                event.get("status")
                or result.get("status")
                or result_details.get("status")
                or ("ok" if result.get("ok") is True else "")
                or ("ok" if result_details.get("ok") is True else "")
                or "partial"
            ).lower()
            if raw_status in {"ok", "ready", "completed", "succeeded", "success"}:
                step_status = "completed"
            elif raw_status in {"blocked", "approval_required", "needs_confirmation"}:
                step_status = "blocked"
            elif raw_status in {"failed", "error", "cancelled", "canceled"}:
                step_status = "failed"
            else:
                step_status = "partial"
            result_data = (
                result_details.get("data")
                if isinstance(result_details.get("data"), Mapping)
                else {}
            )
            step_metrics: dict[str, Any] = {}
            run_metrics: dict[str, float] = {}
            if str(name) == "code-analyze":
                backend = str(result_data.get("backend") or "not_available")
                step_metrics["code_index_backend"] = backend
                bounds = result_data.get("result_bounds")
                bounds = bounds if isinstance(bounds, Mapping) else {}
                for field in ("limit", "total_count", "returned_count"):
                    value = bounds.get(field)
                    if isinstance(value, int) and not isinstance(value, bool):
                        step_metrics[f"result_{field}"] = value
                if "truncated" in bounds:
                    step_metrics["result_truncated"] = bool(bounds.get("truncated"))
                if step_status != "completed":
                    run_metrics["code_index_query_failure_count"] = 1
                elif backend == "source_code_index":
                    run_metrics["code_index_query_success_count"] = 1
                    returned_count = bounds.get("returned_count")
                    total_count = bounds.get("total_count")
                    if isinstance(returned_count, int) and not isinstance(returned_count, bool):
                        run_metrics["code_index_query_rows_returned"] = returned_count
                    if isinstance(total_count, int) and not isinstance(total_count, bool):
                        run_metrics["code_index_query_rows_total"] = total_count
                elif backend == "codegraph_db":
                    run_metrics["legacy_codegraph_query_count"] = 1
                else:
                    run_metrics["code_index_query_unclassified_count"] = 1
            stage_name = re.sub(r"[^A-Za-z0-9._-]+", "-", f"tool-{name}")[:120].strip("-") or "tool-call"
            refs = self._event_artifact_refs(event)
            ledger = AnalysisLedger(self._analysis_ledger_root)
            step = ledger.begin_step(
                str(self._analysis_run["run_id"]),
                stage=stage_name,
                tool_calls=[{"name": str(name), "event_type": event_type, "status": raw_status}],
                created_by="pi",
            )
            gaps = []
            if step_status != "completed":
                gaps.append({
                    "id": f"tool_{stage_name}_incomplete",
                    "status": step_status,
                    "reason": str(result.get("message") or raw_status),
                })
            ledger.complete_step(
                str(self._analysis_run["run_id"]),
                str(step["step_id"]),
                status=step_status,
                output_artifact_refs=refs,
                observations=[{
                    "kind": "pi_tool_execution",
                    "tool": str(name),
                    "event_type": event_type,
                    "result_status": raw_status,
                }],
                gaps=gaps,
                user_visible_summary=f"Pi 工具 {name}：{raw_status}",
                next_action_candidates=[],
                metrics=step_metrics,
            )
            run_id = str(self._analysis_run["run_id"])
            self._analysis_run = ledger.read_run(run_id)
            if run_metrics:
                self._analysis_run = ledger.update_run(
                    run_id,
                    metrics=run_metrics,
                    metric_mode="increment",
                    actor="pi",
                )
        except Exception as exc:  # noqa: BLE001 - ledger observability only
            log.warning("PiModule: record tool step failed: %s", exc)

    def _run_batch(self, bridge, batch_path: str) -> ModuleResult:
        try:
            with open(batch_path, "r", encoding="utf-8") as f:
                questions = json.load(f)
        except Exception as exc:  # noqa: BLE001
            return ModuleResult.fail(f"读取 batch 失败: {exc}", module=self.name)
        if not isinstance(questions, list):
            return ModuleResult.fail("batch JSON 需为问题字符串列表", module=self.name)
        answers = []
        for q in questions:
            r = self._prompt_with_ledger(bridge, str(q))
            answers.append({"question": q, "status": r.get("status"),
                            "answer": r.get("answer", "")})
        self._finalize_analysis_run(
            "completed" if all(item.get("status") == "ok" for item in answers) else "partial"
        )
        batch_ok = all(item.get("status") == "ok" for item in answers)
        return ModuleResult(
            ok=batch_ok,
            message=f"pi batch 完成: {len(answers)} 条",
            module=self.name,
            data={
                "answers": answers,
                "event_count": len(self._events),
                **self._context_result_data(),
            },
        )

    def _run_interactive(self, bridge) -> ModuleResult:
        print("Pi 交互模式（空行 / Ctrl+C 退出）")
        history = []
        try:
            while True:
                try:
                    line = input("pi> ").strip()
                except (EOFError, KeyboardInterrupt):
                    break
                if not line:
                    break
                r = self._prompt_with_ledger(bridge, line)
                history.append({"q": line, "a": r.get("answer", "")})
                if r.get("answer"):
                    print(r["answer"])
        except Exception as exc:  # noqa: BLE001
            return ModuleResult.fail(f"interactive 异常: {exc}", module=self.name)
        return ModuleResult.success(message="pi interactive 结束",
                                    module=self.name, exchanges=history,
                                    **self._context_result_data())

    @staticmethod
    def _iter_nested_tool_payloads(value: Any, depth: int = 0):
        if depth > 6:
            return
        if isinstance(value, Mapping):
            yield value
            for key in ("result", "details", "data", "content", "text"):
                child = value.get(key)
                if key == "text" and isinstance(child, str) and len(child) <= 1_000_000:
                    try:
                        decoded = json.loads(child)
                    except (TypeError, ValueError):
                        decoded = None
                    if decoded is not None:
                        yield from PiModule._iter_nested_tool_payloads(decoded, depth + 1)
                else:
                    yield from PiModule._iter_nested_tool_payloads(child, depth + 1)
        elif isinstance(value, list):
            for child in value[:80]:
                yield from PiModule._iter_nested_tool_payloads(child, depth + 1)

    @classmethod
    def _completed_code_analyze_data(cls, events: list[Mapping[str, Any]]) -> dict[str, Any] | None:
        """Return a completed call_chain payload for a source-only text fallback."""
        for event in events:
            if not isinstance(event, Mapping):
                continue
            for candidate in cls._iter_nested_tool_payloads(event):
                event_type = str(candidate.get("type") or "").lower()
                tool_name = str(
                    candidate.get("toolName")
                    or candidate.get("tool_name")
                    or candidate.get("name")
                    or ""
                )
                tool_result_role = (
                    str(candidate.get("role") or "").lower() in {"toolresult", "tool_result"}
                )
                completed_tool_event = (
                    "tool_execution" in event_type
                    and any(token in event_type for token in ("end", "result", "complete"))
                )
                if tool_name != "code-analyze" or not (tool_result_role or completed_tool_event):
                    continue
                for payload in cls._iter_nested_tool_payloads(candidate):
                    if str(payload.get("status") or "").lower() != "ok":
                        continue
                    data = payload.get("data")
                    if (
                        isinstance(data, Mapping)
                        and data.get("kind") == "call_chain"
                        and data.get("backend")
                        and isinstance(data.get("data"), list)
                    ):
                        return dict(data)
        return None

    @staticmethod
    def _format_code_analyze_call_chain(data: Mapping[str, Any]) -> str:
        rows = data.get("data")
        if not isinstance(rows, list):
            return ""
        paths = [
            str(row.get("path"))
            for row in rows
            if isinstance(row, Mapping) and row.get("path")
        ]
        if not paths:
            return ""
        bounds = data.get("result_bounds") if isinstance(data.get("result_bounds"), Mapping) else {}
        source_context = data.get("source_context") if isinstance(data.get("source_context"), Mapping) else {}
        lines = ["Pi 模型没有补充文字答复；以下仅投影 code-analyze 工具结果。"]
        if source_context.get("snapshot_hash"):
            lines.append(f"source snapshot: {source_context['snapshot_hash']}")
        if bounds:
            lines.append(
                "result_bounds: "
                f"{bounds.get('returned_count', len(paths))}/{bounds.get('total_count', len(paths))} "
                f"(limit={bounds.get('limit', len(paths))}, truncated={str(bool(bounds.get('truncated'))).lower()})"
            )
        lines.extend(f"- {path}" for path in paths)
        lines.append("以上是静态 source candidate，不代表编译或 runtime 命中。")
        return "\n".join(lines)

    def _result_from_prompt(self, result: dict, case_dir: str) -> ModuleResult:
        report_artifacts = list((self._evidence_anchor or {}).get("report_artifacts", []) or [])
        tool_calls: list[dict[str, Any]] = []
        tool_artifact_refs: list[dict[str, Any]] = []
        for event in self._events:
            if not isinstance(event, Mapping):
                continue
            event_type = str(event.get("type") or "").lower()
            tool_execution_completed = (
                "tool" in event_type
                and ("execution" in event_type or "result" in event_type)
                and any(marker in event_type for marker in ("end", "result", "complete"))
            )
            if not tool_execution_completed:
                continue
            name = event.get("toolName") or event.get("tool_name") or event.get("name")
            if name:
                nested_result = event.get("result") if isinstance(event.get("result"), Mapping) else {}
                if not nested_result and isinstance(event.get("details"), Mapping):
                    nested_result = event.get("details")
                nested_details = nested_result.get("details") if isinstance(nested_result, Mapping) else {}
                nested_status = (
                    nested_details.get("status")
                    if isinstance(nested_details, Mapping)
                    else None
                )
                tool_calls.append({
                    "name": str(name),
                    "event_type": event_type,
                    "status": str(
                        event.get("status")
                        or nested_result.get("status")
                        or nested_status
                        or "observed"
                    ),
                })
            tool_artifact_refs.extend(self._event_artifact_refs(event))
        deduped_tool_calls: list[dict[str, Any]] = []
        for item in tool_calls:
            if item not in deduped_tool_calls:
                deduped_tool_calls.append(item)
        deduped_tool_refs: list[dict[str, Any]] = []
        for item in tool_artifact_refs:
            if item not in deduped_tool_refs:
                deduped_tool_refs.append(item)
        tool_artifact_paths = [
            str(item.get("path"))
            for item in deduped_tool_refs
            if item.get("path") not in (None, "")
        ]
        artifacts = list(dict.fromkeys([*report_artifacts, *tool_artifact_paths]))
        answer = str(result.get("answer", "") or "")
        common_data = {
            "answer": answer,
            "event_count": result.get("event_count", 0),
            "pi_event_summary": result.get("event_summary", {}),
            "case_dir": case_dir,
            "tool_calls": deduped_tool_calls,
            "tool_artifact_refs": deduped_tool_refs,
            **self._context_result_data(),
        }
        if result.get("status") != "ok":
            return ModuleResult(
                ok=False,
                message=result.get("message", "pi 调用未完成"),
                module=self.name,
                artifacts=artifacts,
                data=common_data,
            )
        if not answer.strip():
            context = self._context or {}
            if context.get("task_scope") == "source_code":
                code_result = self._completed_code_analyze_data(self._events)
                projected_answer = (
                    self._format_code_analyze_call_chain(code_result)
                    if code_result is not None
                    else ""
                )
                if projected_answer:
                    return ModuleResult.success(
                        message="pi: source-code tool result projected; model final text unavailable",
                        module=self.name,
                        answer=projected_answer,
                        answer_mode="tool_result_projection",
                        ai_final_synthesis_status="not_available",
                        event_count=result.get("event_count", 0),
                        case_dir=case_dir,
                        artifacts=artifacts,
                        report_artifacts=report_artifacts,
                        tool_calls=deduped_tool_calls,
                        tool_artifact_refs=deduped_tool_refs,
                        **self._context_result_data(),
                    )
            return ModuleResult(
                ok=False,
                message="Pi 已结束本轮，但没有生成可展示的最终答复",
                module=self.name,
                artifacts=artifacts,
                data={**common_data, "error": "empty_final_answer"},
            )
        return ModuleResult.success(
            message=f"pi: {result.get('message', 'ok')}",
            module=self.name,
            answer=answer,
            event_count=result.get("event_count", 0),
            pi_event_summary=result.get("event_summary", {}),
            case_dir=case_dir,
            artifacts=artifacts,
            report_artifacts=report_artifacts,
            tool_calls=deduped_tool_calls,
            tool_artifact_refs=deduped_tool_refs,
            **self._context_result_data(),
        )

    def _context_result_data(self) -> dict[str, Any]:
        """Expose only context identity/status in the Pi result envelope."""
        context = self._context or {}
        return {
            "context_fingerprint": context.get("context_fingerprint", ""),
            "context_status": context.get("status", "not_created"),
            "context_run_id": context.get("run_id", ""),
            "context_missing": list(context.get("missing", []) or []),
            "context_conflicts": list(context.get("conflicts", []) or []),
            "analysis_run_id": (self._analysis_run or {}).get("run_id", ""),
            "analysis_run_status": (self._analysis_run or {}).get("status", "not_created"),
            "analysis_run_path": (self._analysis_run or {}).get("artifact_path", ""),
        }

    # ── CLI ───────────────────────────────────────────────────────

    @classmethod
    def register_cli(cls, subparsers: Any) -> Any:
        p = super().register_cli(subparsers)
        p.add_argument("--question", default="", help="用户问题")
        p.add_argument("--case-dir", default="", help="数据目录")
        p.add_argument(
            "--intake",
            dest="intake_path",
            default="",
            help="cr60-analysis-intake.v1 artifact 路径；缺省时自动发现 case 目录内的 intake",
        )
        p.add_argument(
            "--material",
            dest="material_paths",
            nargs="+",
            default=None,
            help="材料文件/目录（问题单表格、JSON、文本等），用于自动解析软件版本/车型/COEM",
        )
        p.add_argument(
            "--match-text",
            dest="match_text",
            default="",
            help="多行材料的问题行匹配关键词（ticket 号或数据文件名）",
        )
        p.add_argument("--batch", default="", help="批量问题 JSON 文件路径")
        p.add_argument("--interactive", action="store_true", help="交互模式")
        p.add_argument(
            "--tools",
            nargs="+",
            default=None,
            help="显式限制 Pi capability allowlist；默认根据问题意图选择",
        )
        p.add_argument("--task-scope", choices=["case_analysis", "source_code"], default="")
        p.add_argument("--provider", default="", help="pi provider")
        p.add_argument("--model", default="", help="pi model")
        p.add_argument(
            "--thinking",
            choices=["off", "minimal", "low", "medium", "high", "xhigh", "max"],
            default="",
            help="可选 Pi thinking level；留空时使用 Pi 用户配置",
        )
        p.add_argument("--session-dir", default="", help="会话目录")
        p.add_argument("--session-id", default="", help="可恢复的 Pi session ID")
        p.add_argument("--analysis-run-id", default="", help="继续已有 AnalysisRun")
        p.add_argument("--analysis-ledger-root", default="", help="AnalysisRun ledger 根目录")
        p.add_argument("--project-root", default="", help="radarAnalyze project root")
        p.add_argument("--diagnosis-bundle", dest="diagnosis_bundle_path", default="")
        p.add_argument("--viewer-model", dest="viewer_model_path", default="")
        p.add_argument("--runtime-evidence", dest="runtime_evidence_path", default="")
        p.add_argument("--runtime-debug-plan", dest="runtime_debug_plan_path", default="")
        p.add_argument("--preflight", dest="preflight_path", default="")
        p.add_argument("--code-context", dest="code_context_path", default="")
        p.add_argument("--event-code-path", dest="event_code_path_path", default="")
        p.add_argument("--condition-trace", dest="condition_trace_path", default="")
        p.add_argument("--gdb-session", dest="gdb_session_path", default="")
        p.add_argument("--diagnostic-report", dest="diagnostic_report_path", default="")
        p.add_argument("--event-id", default="")
        p.add_argument("--function", default="")
        p.add_argument("--side", default="")
        p.add_argument("--frame-id", default="")
        p.add_argument("--output-endpoint", choices=["auto", "algorithm", "can_tx"], default="algorithm")
        p.add_argument("--can-data-status", choices=["present", "absent", "not_detected", "unknown"], default="")
        p.add_argument("--timeout", type=float, default=300)
        p.add_argument("--output-dir", default="", help="显式要求报告时的本地输出目录")
        p.add_argument("--generate-report", action="store_true", help="生成确定性 HTML/JSON/Markdown 报告")
        p.add_argument(
            "--context", "--context-path", dest="context_path", default="",
            help="PiRunContext JSON artifact path",
        )
        p.add_argument("--extension-path", default="", help="generated Pi extension path")
        p.add_argument("--no-project-extension", dest="load_project_extension", action="store_false")
        p.add_argument("--no-auto-generate-extension", dest="auto_generate_extension", action="store_false")
        p.add_argument("--allow-builtin-tools", action="store_true")
        p.set_defaults(_module_cls=cls)
        return p

    @classmethod
    def from_cli_args(cls, args: Any) -> "PiModule":
        return cls(
            case_dir=getattr(args, "case_dir", ""),
            session_dir=getattr(args, "session_dir", ""),
            provider=getattr(args, "provider", ""),
            model=getattr(args, "model", ""),
            task_scope=getattr(args, "task_scope", ""),
            thinking=getattr(args, "thinking", ""),
        )


__all__ = ["PiModule", "discover_case_artifacts"]
