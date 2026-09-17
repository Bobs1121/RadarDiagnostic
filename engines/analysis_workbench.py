# -*- coding: utf-8 -*-
"""Read-only AnalysisRun projection for a lightweight investigation workbench."""
from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = "analysis-workbench.v1"


class AnalysisWorkbenchError(ValueError):
    """Raised when an AnalysisRun projection is malformed."""


def _load_json(path: str | Path) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AnalysisWorkbenchError(f"analysis_run_invalid:{type(exc).__name__}:{target}") from exc
    if not isinstance(payload, Mapping):
        raise AnalysisWorkbenchError("analysis_run_root_must_be_object")
    return dict(payload)


def _materialize_refs(rows: Any, *, limit: int = 128) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        return []
    result: list[dict[str, Any]] = []
    for item in rows[:limit]:
        if not isinstance(item, Mapping):
            continue
        path = item.get("path") or item.get("artifact_path")
        if path:
            try:
                payload = _load_json(str(path))
            except AnalysisWorkbenchError:
                payload = dict(item)
            result.append({**payload, "_ref": dict(item)})
        else:
            result.append(dict(item))
    return result


def _feedback_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    labels = {
        "feedback_confirmed": "用户确认",
        "feedback_rejected": "用户否定",
        "feedback_irrelevant": "用户标记无关",
    }
    result: list[dict[str, Any]] = []
    for item in rows:
        kind = str(item.get("kind") or "")
        if kind not in labels:
            continue
        result.append({
            "observation_id": item.get("observation_id"),
            "kind": kind,
            "label": labels[kind],
            "summary": item.get("summary", ""),
            "target": item.get("target", {}),
            "binding": item.get("binding", {}),
            "created_by": item.get("created_by", ""),
            "runtime_eligible": item.get("runtime_eligible", False),
            "evidence_layer": item.get("evidence_layer", "user_observation"),
        })
    return result


def build_analysis_workbench(
    *,
    analysis_run: Mapping[str, Any] | None = None,
    analysis_run_path: str = "",
    feedback_review: Mapping[str, Any] | None = None,
    feedback_review_path: str = "",
) -> dict[str, Any]:
    run = dict(analysis_run) if isinstance(analysis_run, Mapping) else _load_json(analysis_run_path)
    if run.get("schema_version") != "analysis-run.v1":
        raise AnalysisWorkbenchError("analysis_run_schema_unsupported")
    refs = {
        "analysis_run": {"path": str(Path(analysis_run_path).expanduser().resolve())} if analysis_run_path else {"source": "inline"},
    }
    steps = _materialize_refs(run.get("steps"))
    hypotheses = _materialize_refs(run.get("hypotheses"))
    experiments = _materialize_refs(run.get("experiments"))
    observations = _materialize_refs(run.get("user_observations"))
    feedback = _feedback_rows(observations)
    review = dict(feedback_review) if isinstance(feedback_review, Mapping) else None
    if review is None and feedback_review_path:
        review = _load_json(feedback_review_path)
        refs["feedback_review"] = {"path": str(Path(feedback_review_path).expanduser().resolve())}
    if review is not None and review.get("schema_version") != "feedback-review.v1":
        raise AnalysisWorkbenchError("feedback_review_schema_unsupported")
    counts = {
        "steps": len(steps),
        "hypotheses": len(hypotheses),
        "experiments": len(experiments),
        "user_observations": len(observations),
        "feedback": len(feedback),
    }
    next_actions: list[dict[str, Any]] = []
    if review is not None:
        gate = review.get("knowledge_publish_gate") if isinstance(review.get("knowledge_publish_gate"), Mapping) else {}
        if str(gate.get("status") or "") == "approval_required":
            next_actions.append({"id": "feedback-knowledge-plan", "tool": "feedback-knowledge-plan", "reason": "先提供候选 pattern、freshness 和用户批准，再考虑 knowledge 发布"})
    if any(str(item.get("status") or "") in {"planned", "approval_required"} for item in experiments):
        next_actions.append({"id": "run-planned-experiment", "tool": "debug-experiment-record", "reason": "从已有 planned experiment 继续，不重复创建独立状态"})
    status = str(run.get("status") or "partial")
    if status not in {"created", "running", "completed", "partial", "blocked", "failed"}:
        status = "partial"
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "ready" if status != "blocked" else "partial",
        "run": {
            "run_id": run.get("run_id", ""),
            "status": status,
            "goal": run.get("goal", {}),
            "binding": run.get("binding", {}),
            "metrics": run.get("metrics", {}),
        },
        "counts": counts,
        "analysis_trail": steps,
        "hypothesis_board": hypotheses,
        "experiments": experiments,
        "user_observations": observations,
        "feedback": feedback,
        "feedback_review": review or {},
        "next_actions": next_actions,
        "provenance": refs,
        "policy": "Workbench is a read-only projection of AnalysisRun; it does not execute tools, mutate ledger, or publish knowledge.",
    }


def write_analysis_workbench(payload: Mapping[str, Any], output_dir: str | Path) -> list[str]:
    root = Path(output_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    rows = []
    for item in payload.get("feedback", []) or []:
        if not isinstance(item, Mapping):
            continue
        rows.append(
            f"<tr><td>{html.escape(str(item.get('label', item.get('kind', ''))))}</td>"
            f"<td>{html.escape(str(item.get('summary', '')))}</td>"
            f"<td><code>{html.escape(str(item.get('created_by', '')))}</code></td>"
            f"<td><code>{html.escape(str((item.get('binding') or {}).get('variant_id', 'not_available')))}</code></td></tr>"
        )
    feedback_html = (
        '<h2>Feedback</h2><table><thead><tr><th>Kind</th><th>Summary</th><th>Actor</th><th>Variant</th></tr></thead>'
        f'<tbody>{"".join(rows) or "<tr><td colspan=\"4\">No feedback</td></tr>"}</tbody></table>'
    )
    html_text = (
        "<!doctype html><meta charset='utf-8'><title>Analysis Workbench</title>"
        "<style>body{font:14px system-ui;max-width:1200px;margin:32px auto;padding:0 20px}"
        "table{width:100%;border-collapse:collapse}td,th{border-bottom:1px solid #ddd;text-align:left;padding:8px}"
        "code{font-family:monospace}</style>"
        f"<h1>Analysis Workbench</h1><p>Status: <code>{html.escape(str(payload.get('status')))}</code>; "
        f"Run: <code>{html.escape(str((payload.get('run') or {}).get('run_id')))}</code></p>"
        f"{feedback_html}<h2>Next actions</h2><ul>"
        + "".join(f"<li><code>{html.escape(str(item.get('tool')))}</code> {html.escape(str(item.get('reason')))}</li>" for item in payload.get("next_actions", []) or [])
        + "</ul><p>Read-only projection; no ledger or knowledge mutation.</p>"
    )
    json_path = root / "analysis-workbench.json"
    html_path = root / "analysis-workbench.html"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    html_path.write_text(html_text, encoding="utf-8")
    return [str(json_path), str(html_path)]


__all__ = ["AnalysisWorkbenchError", "SCHEMA_VERSION", "build_analysis_workbench", "write_analysis_workbench"]
