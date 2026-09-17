# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path

from ai.capability.registry import capability_catalog
from ai.modules import MODULE_REGISTRY
from ai.modules.feedback_review import FeedbackReviewModule
from ai.modules.feedback_knowledge_plan import FeedbackKnowledgePlanModule
from ai.modules.feedback_knowledge_publish import FeedbackKnowledgePublishModule
from engines.feedback_review import review_feedback
from engines.feedback_review import build_knowledge_publish_plan, publish_feedback_knowledge


def _run(*feedback: dict) -> dict:
    return {
        "schema_version": "analysis-run.v1",
        "run_id": "run-feedback",
        "binding": {
            "variant_id": "gen6/byd_sc6h",
            "source_snapshot_hash": "source-1",
            "data_fingerprint": "data-1",
        },
        "user_observations": list(feedback),
    }


def _feedback(kind: str, *, binding: dict | None = None) -> dict:
    return {
        "schema_version": "user-observation.v1",
        "observation_id": f"obs-{kind}",
        "kind": kind,
        "summary": kind,
        "binding": binding or {
            "variant_id": "gen6/byd_sc6h",
            "source_snapshot_hash": "source-1",
            "data_fingerprint": "data-1",
        },
        "created_by": "user",
        "evidence_layer": "user_observation",
        "runtime_eligible": False,
    }


def test_feedback_review_requires_explicit_publish_action_and_keeps_counts():
    payload = review_feedback(
        analysis_run=_run(
            _feedback("feedback_confirmed"),
            _feedback("feedback_rejected"),
            _feedback("feedback_irrelevant"),
        )
    )
    assert payload["status"] == "ready"
    assert payload["counts"] == {
        "feedback_confirmed": 1,
        "feedback_irrelevant": 1,
        "feedback_rejected": 1,
    }
    assert payload["knowledge_publish_gate"]["status"] == "approval_required"
    assert payload["knowledge_publish_gate"]["writes_knowledge"] is False
    assert payload["diagnostics"] == []


def test_feedback_review_blocks_binding_or_authority_conflicts():
    payload = review_feedback(
        analysis_run=_run(
            {
                **_feedback("feedback_confirmed", binding={"variant_id": "other-variant"}),
                "runtime_eligible": True,
            }
        )
    )
    assert payload["status"] == "blocked"
    assert payload["knowledge_publish_gate"]["status"] == "blocked"
    assert "feedback_binding_conflict" in payload["diagnostics"]
    assert "feedback_runtime_eligible_must_be_false" in payload["diagnostics"]


def test_feedback_review_module_reads_analysis_run_artifact_and_is_cataloged(tmp_path: Path):
    path = tmp_path / "analysis-run.json"
    path.write_text(json.dumps(_run(_feedback("feedback_rejected"))), encoding="utf-8")
    result = FeedbackReviewModule().safe_run(analysis_run_path=str(path), output=str(tmp_path / "review.json"))
    assert result.ok is True
    assert result.data["knowledge_publish_gate"]["status"] == "approval_required"
    assert MODULE_REGISTRY["feedback-review"] is FeedbackReviewModule
    catalog = {item["name"]: item for item in capability_catalog()}
    assert catalog["feedback-review"]["expose_to_pi"] is True


def test_feedback_review_materializes_user_observation_refs(tmp_path: Path):
    observation_path = tmp_path / "user-observation.json"
    observation_path.write_text(
        json.dumps(_feedback("feedback_confirmed")), encoding="utf-8"
    )
    run = _run({
        "kind": "feedback_confirmed",
        "summary": "summary ref",
        "path": str(observation_path),
    })
    payload = review_feedback(analysis_run=run)
    assert payload["counts"]["feedback_confirmed"] == 1
    assert payload["feedback"][0]["binding_status"] == "matched"


def test_feedback_knowledge_plan_requires_explicit_user_approval_and_freshness():
    review = review_feedback(
        analysis_run=_run(_feedback("feedback_confirmed"))
    )
    pattern = {
        "title": "用户确认的候选模式",
        "description": "仍需独立证据验证后才能发布",
        "variant_scope": ["gen6/byd_sc6h"],
        "category": "algorithm",
    }
    pending = build_knowledge_publish_plan(
        feedback_review=review,
        candidate_pattern=pattern,
        approved=False,
        actor="user",
        freshness={"config_identity_hash": "cfg"},
    )
    assert pending["status"] == "approval_required"
    assert pending["writes_knowledge"] is False
    ready = build_knowledge_publish_plan(
        feedback_review=review,
        candidate_pattern=pattern,
        approved=True,
        actor="user",
        freshness={"config_identity_hash": "cfg"},
    )
    assert ready["status"] == "ready"
    assert ready["next_action"] == "explicit_knowledge_publish"


def test_feedback_knowledge_plan_module_is_cataloged_without_writing(tmp_path: Path):
    review = review_feedback(analysis_run=_run(_feedback("feedback_confirmed")))
    result = FeedbackKnowledgePlanModule().safe_run(
        feedback_review=review,
        candidate_pattern={"title": "candidate", "variant_scope": ["gen6/byd_sc6h"]},
        approved=False,
        freshness={"config_identity_hash": "cfg"},
    )
    assert result.ok is True
    assert result.data["writes_knowledge"] is False
    assert MODULE_REGISTRY["feedback-knowledge-plan"] is FeedbackKnowledgePlanModule
    catalog = {item["name"]: item for item in capability_catalog()}
    assert catalog["feedback-knowledge-plan"]["expose_to_pi"] is True


def test_feedback_knowledge_publish_requires_approval_and_writes_only_scoped_pattern(tmp_path: Path):
    review = review_feedback(analysis_run=_run(_feedback("feedback_confirmed")))
    plan = build_knowledge_publish_plan(
        feedback_review=review,
        candidate_pattern={
            "title": "approved feedback pattern",
            "description": "user-approved candidate",
            "variant_scope": ["gen6/byd_sc6h"],
            "category": "algorithm",
        },
        approved=True,
        actor="user",
        freshness={"config_identity_hash": "cfg"},
    )
    try:
        publish_feedback_knowledge(
            publish_plan=plan,
            knowledge_dir=tmp_path / "knowledge",
            approved=False,
            actor="user",
        )
    except Exception as exc:
        assert "approval" in str(exc)
    else:
        raise AssertionError("publication must require explicit approval")
    published = publish_feedback_knowledge(
        publish_plan=plan,
        knowledge_dir=tmp_path / "knowledge",
        approved=True,
        actor="user",
    )
    assert published["status"] == "published"
    assert published["writes_knowledge"] is True
    pattern_dir = tmp_path / "knowledge" / "patterns"
    files = list(pattern_dir.glob("*.json"))
    assert len(files) == 1
    saved = json.loads(files[0].read_text(encoding="utf-8"))
    assert saved["variant_scope"] == ["gen6/byd_sc6h"]
    assert saved["metadata"]["published_from_feedback_plan"] is True
    assert MODULE_REGISTRY["feedback-knowledge-publish"] is FeedbackKnowledgePublishModule
    catalog = {item["name"]: item for item in capability_catalog()}
    assert catalog["feedback-knowledge-publish"]["requires_approval"] is True
