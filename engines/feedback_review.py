# -*- coding: utf-8 -*-
"""Deterministic review of user feedback before any knowledge publication."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = "feedback-review.v1"
FEEDBACK_KINDS = frozenset({"feedback_confirmed", "feedback_rejected", "feedback_irrelevant"})


class FeedbackReviewError(ValueError):
    """Raised when a feedback review input is malformed."""


def _load_run(value: Mapping[str, Any] | None, path: str) -> dict[str, Any]:
    if value is not None:
        if not isinstance(value, Mapping):
            raise FeedbackReviewError("analysis_run must be an object")
        return dict(value)
    if not str(path or "").strip():
        raise FeedbackReviewError("analysis_run or analysis_run_path is required")
    target = Path(path).expanduser().resolve()
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FeedbackReviewError(f"analysis_run_invalid:{type(exc).__name__}:{target}") from exc
    if not isinstance(payload, Mapping):
        raise FeedbackReviewError("analysis_run root must be an object")
    return dict(payload)


def _binding_mismatches(run_binding: Mapping[str, Any], feedback_binding: Mapping[str, Any]) -> list[dict[str, Any]]:
    mismatches: list[dict[str, Any]] = []
    for field in ("project_id", "variant_id", "source_context_id", "source_snapshot_hash", "data_fingerprint", "binary_fingerprint", "config_fingerprint"):
        expected = run_binding.get(field)
        actual = feedback_binding.get(field)
        if expected not in (None, "") and actual not in (None, "") and str(expected) != str(actual):
            mismatches.append({"field": field, "run": expected, "feedback": actual})
        elif expected not in (None, "") and actual in (None, ""):
            mismatches.append({"field": field, "run": expected, "feedback": None, "reason": "feedback_binding_missing"})
    return mismatches


def _materialize_feedback(rows: Any) -> list[dict[str, Any]]:
    """Resolve AnalysisRun entity refs without treating summaries as facts."""
    if not isinstance(rows, list):
        return []
    result: list[dict[str, Any]] = []
    for item in rows:
        if not isinstance(item, Mapping):
            continue
        path_text = item.get("path") or item.get("artifact_path")
        if path_text:
            try:
                payload = json.loads(Path(str(path_text)).expanduser().resolve().read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                result.append({**dict(item), "_materialization_status": "failed"})
                continue
            if isinstance(payload, Mapping):
                result.append({**dict(payload), "_ref": dict(item)})
                continue
        result.append(dict(item))
    return result


def review_feedback(
    *,
    analysis_run: Mapping[str, Any] | None = None,
    analysis_run_path: str = "",
    require_user_confirmation: bool = True,
) -> dict[str, Any]:
    run = _load_run(analysis_run, analysis_run_path)
    if run.get("schema_version") != "analysis-run.v1":
        raise FeedbackReviewError("analysis_run_schema_unsupported")
    run_binding = run.get("binding") if isinstance(run.get("binding"), Mapping) else {}
    entities = run.get("user_observations")
    if not isinstance(entities, list):
        entities = (run.get("entities") or {}).get("user_observations", []) if isinstance(run.get("entities"), Mapping) else []
    entities = _materialize_feedback(entities)
    feedback: list[dict[str, Any]] = []
    diagnostics: list[str] = []
    conflicts: list[dict[str, Any]] = []
    counts = {kind: 0 for kind in sorted(FEEDBACK_KINDS)}
    for item in entities:
        if not isinstance(item, Mapping):
            continue
        kind = str(item.get("kind") or "")
        if kind not in FEEDBACK_KINDS:
            continue
        counts[kind] += 1
        binding = item.get("binding") if isinstance(item.get("binding"), Mapping) else {}
        mismatch = _binding_mismatches(run_binding, binding)
        if mismatch:
            conflicts.extend({"observation_id": item.get("observation_id"), **row} for row in mismatch)
        feedback.append({
            "observation_id": item.get("observation_id"),
            "kind": kind,
            "summary": item.get("summary", ""),
            "target": item.get("target", {}),
            "binding": dict(binding),
            "evidence_layer": item.get("evidence_layer", "user_observation"),
            "runtime_eligible": item.get("runtime_eligible", False),
            "created_by": item.get("created_by", ""),
            "binding_status": "conflict" if mismatch else "matched",
            "artifact_ref": item.get("artifact_path") or item.get("path"),
        })
    if conflicts:
        diagnostics.append("feedback_binding_conflict")
    if any(item.get("created_by") != "user" for item in feedback):
        diagnostics.append("feedback_created_by_not_user")
    if any(item.get("runtime_eligible") is not False for item in feedback):
        diagnostics.append("feedback_runtime_eligible_must_be_false")
    if not feedback:
        diagnostics.append("no_explicit_user_feedback")
    if conflicts or diagnostics and any(item in diagnostics for item in ("feedback_created_by_not_user", "feedback_runtime_eligible_must_be_false")):
        gate_status = "blocked"
        gate_reason = "feedback identity/authority validation failed"
    elif require_user_confirmation and counts["feedback_confirmed"] == 0:
        gate_status = "approval_required"
        gate_reason = "a user confirmation is required before knowledge publication"
    else:
        gate_status = "approval_required"
        gate_reason = "knowledge publication remains an explicit separate action"
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "blocked" if gate_status == "blocked" else "ready",
        "run_id": run.get("run_id", ""),
        "binding": dict(run_binding),
        "feedback": feedback,
        "counts": counts,
        "conflicts": conflicts,
        "knowledge_publish_gate": {
            "status": gate_status,
            "reason": gate_reason,
            "writes_knowledge": False,
            "requires_explicit_publish_action": True,
        },
        "diagnostics": list(dict.fromkeys(diagnostics)),
    }


__all__ = ["FEEDBACK_KINDS", "FeedbackReviewError", "PUBLISH_PLAN_SCHEMA_VERSION", "SCHEMA_VERSION", "build_knowledge_publish_plan", "review_feedback"]


PUBLISH_PLAN_SCHEMA_VERSION = "feedback-knowledge-plan.v1"


def build_knowledge_publish_plan(
    *,
    feedback_review: Mapping[str, Any],
    candidate_pattern: Mapping[str, Any],
    approved: bool = False,
    actor: str = "user",
    freshness: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate a proposed knowledge publication without writing memory."""
    if feedback_review.get("schema_version") != SCHEMA_VERSION:
        raise FeedbackReviewError("feedback_review_schema_unsupported")
    if not isinstance(candidate_pattern, Mapping):
        raise FeedbackReviewError("candidate_pattern_must_be_object")
    review_binding = feedback_review.get("binding") if isinstance(feedback_review.get("binding"), Mapping) else {}
    variant_id = str(review_binding.get("variant_id") or "")
    candidate_scope = candidate_pattern.get("variant_scope")
    candidate_scope = [str(item) for item in candidate_scope or [] if str(item)] if isinstance(candidate_scope, list) else []
    counts = feedback_review.get("counts") if isinstance(feedback_review.get("counts"), Mapping) else {}
    confirmed_count = int(counts.get("feedback_confirmed", 0) or 0)
    diagnostics: list[str] = []
    if feedback_review.get("status") == "blocked":
        diagnostics.append("feedback_review_blocked")
    if not variant_id:
        diagnostics.append("variant_binding_missing")
    if not candidate_scope or variant_id not in candidate_scope:
        diagnostics.append("candidate_pattern_variant_scope_mismatch")
    if confirmed_count <= 0:
        diagnostics.append("user_confirmation_missing")
    if str(actor or "") != "user":
        diagnostics.append("publish_actor_must_be_user")
    if not isinstance(freshness, Mapping):
        diagnostics.append("freshness_inputs_missing")
    status = "ready" if approved and not diagnostics else "approval_required" if not diagnostics else "blocked"
    return {
        "schema_version": PUBLISH_PLAN_SCHEMA_VERSION,
        "status": status,
        "run_id": feedback_review.get("run_id", ""),
        "variant_id": variant_id,
        "feedback_review_ref": feedback_review.get("artifact_path") or feedback_review.get("run_id", ""),
        "candidate_pattern": dict(candidate_pattern),
        "approval": {"approved": bool(approved), "actor": str(actor or ""), "required": True},
        "freshness": dict(freshness or {}),
        "diagnostics": list(dict.fromkeys(diagnostics)),
        "writes_knowledge": False,
        "next_action": "explicit_knowledge_publish" if status == "ready" else "collect_user_approval_and_freshness",
    }


def publish_feedback_knowledge(
    *,
    publish_plan: Mapping[str, Any],
    knowledge_dir: str | Path,
    actor: str = "user",
    approved: bool = False,
) -> dict[str, Any]:
    """Persist an explicitly approved, variant-scoped pattern.

    This is intentionally a separate side-effecting leaf. The plan itself is
    write-free; publication requires the module approval gate and a concrete
    knowledge directory supplied by the caller.
    """
    if not isinstance(publish_plan, Mapping) or publish_plan.get("schema_version") != PUBLISH_PLAN_SCHEMA_VERSION:
        raise FeedbackReviewError("publish_plan_schema_unsupported")
    if publish_plan.get("status") != "ready":
        raise FeedbackReviewError("publish_plan_not_ready")
    if str(actor or "") != "user" or not approved:
        raise FeedbackReviewError("explicit_user_approval_required")
    pattern = publish_plan.get("candidate_pattern")
    if not isinstance(pattern, Mapping):
        raise FeedbackReviewError("candidate_pattern_missing")
    variant_id = str(publish_plan.get("variant_id") or "")
    scope = pattern.get("variant_scope")
    if not variant_id or not isinstance(scope, list) or variant_id not in [str(item) for item in scope]:
        raise FeedbackReviewError("candidate_variant_scope_mismatch")
    from core.diagnosis_bundle import KnowledgeStore, RootCausePattern

    selected = dict(pattern)
    selected.setdefault("variant_scope", [variant_id])
    selected.setdefault("metadata", {})
    selected["metadata"] = {
        **(selected["metadata"] if isinstance(selected["metadata"], Mapping) else {}),
        "published_from_feedback_plan": True,
        "feedback_review_ref": publish_plan.get("feedback_review_ref"),
        "run_id": publish_plan.get("run_id"),
        "publication_actor": actor,
    }
    stored = KnowledgeStore(Path(knowledge_dir)).add_pattern(RootCausePattern.from_dict(selected))
    return {
        "schema_version": "feedback-knowledge-publication.v1",
        "status": "published",
        "pattern": stored.to_dict(),
        "knowledge_dir": str(Path(knowledge_dir).expanduser().resolve()),
        "run_id": publish_plan.get("run_id", ""),
        "variant_id": variant_id,
        "actor": actor,
        "approved": True,
        "writes_knowledge": True,
    }
