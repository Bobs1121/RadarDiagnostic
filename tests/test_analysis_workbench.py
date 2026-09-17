# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path

from ai.capability.registry import capability_catalog
from ai.modules import MODULE_REGISTRY
from ai.modules.analysis_workbench import AnalysisWorkbenchModule
from engines.analysis_workbench import build_analysis_workbench, write_analysis_workbench


def _run() -> dict:
    return {
        "schema_version": "analysis-run.v1",
        "run_id": "run-workbench",
        "status": "partial",
        "binding": {"variant_id": "gen6/byd_sc6h", "source_snapshot_hash": "source-1", "data_fingerprint": "data-1"},
        "goal": {"question": "逐步审查反馈"},
        "metrics": {"time_to_first_useful_clue_sec": 1.2},
        "steps": [{"stage": "event-map", "status": "completed", "summary": "event mapped"}],
        "hypotheses": [{"category": "algorithm", "statement": "candidate", "status": "open", "rank": 1}],
        "experiments": [{"question": "区分实验", "method": "public_runtime", "status": "planned", "target": {"radar_id": 2}}],
        "user_observations": [{"kind": "feedback_confirmed", "summary": "用户确认", "created_by": "user", "binding": {"variant_id": "gen6/byd_sc6h"}, "runtime_eligible": False}],
    }


def test_analysis_workbench_is_read_only_projection_and_renders_feedback(tmp_path: Path):
    payload = build_analysis_workbench(
        analysis_run=_run(),
        feedback_review={"schema_version": "feedback-review.v1", "status": "ready", "counts": {"feedback_confirmed": 1}, "knowledge_publish_gate": {"status": "approval_required"}},
    )
    assert payload["schema_version"] == "analysis-workbench.v1"
    assert payload["counts"]["feedback"] == 1
    assert payload["next_actions"]
    paths = write_analysis_workbench(payload, tmp_path)
    assert len(paths) == 2
    assert "用户确认" in (tmp_path / "analysis-workbench.html").read_text(encoding="utf-8")
    assert "approval_required" in (tmp_path / "analysis-workbench.json").read_text(encoding="utf-8")


def test_analysis_workbench_module_is_cataloged(tmp_path: Path):
    run_path = tmp_path / "run.json"
    run_path.write_text(json.dumps(_run()), encoding="utf-8")
    result = AnalysisWorkbenchModule().safe_run(analysis_run_path=str(run_path), output_dir=str(tmp_path / "workbench"))
    assert result.ok is True
    assert MODULE_REGISTRY["analysis-workbench"] is AnalysisWorkbenchModule
    catalog = {item["name"]: item for item in capability_catalog()}
    assert catalog["analysis-workbench"]["expose_to_pi"] is True
