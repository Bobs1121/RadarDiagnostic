# -*- coding: utf-8 -*-
"""T10: PiModule 入口的 intake 身份绑定接线测试（G6-AC01 本地契约）。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai.modules.pi import PiModule


SINGLE = {
    "gen6/byd_sc6h": {
        "customer": "BYD",
        "vehicle_project": "SC6H",
        "coem_project_dir": "/repo/coem/BYD_SC6H",
        "source_context": {"code_branch": "master"},
    }
}
TWO = {
    **SINGLE,
    "gen6/gwm_b26": {
        "customer": "GWM",
        "vehicle_project": "B26",
        "coem_project_dir": "/repo/coem/GWM_B26",
        "source_context": {"code_branch": "release/2.0"},
    },
}


@pytest.fixture()
def patch_config(monkeypatch):
    def _patch(variants: dict):
        import config as config_module

        monkeypatch.setattr(
            config_module, "load_config", lambda *a, **k: {"variants": variants}
        )
        return variants

    return _patch


def test_gate_blocks_identity_missing_multiple_projects(tmp_path: Path, patch_config):
    patch_config(TWO)
    case_dir = tmp_path / "case001"
    case_dir.mkdir()
    module = PiModule()
    result = module.run(
        question="为什么右侧目标没有报警",
        case_dir=str(case_dir),
        project_root=str(tmp_path),
    )
    assert result.ok is False
    assert result.data["intake_binding_status"] == "needs_confirmation"
    questions = result.data["business_questions"]
    assert questions and questions[0]["blocking"] is True
    assert questions[0]["id"] == "choose_project"
    # 未调用模型：gate 在 bridge 之前返回
    assert result.data["analysis_run_id"]  # run 已创建，进度保留
    text = json.dumps(questions, ensure_ascii=False)
    assert "frameID" not in text and "PID" not in text


def test_binding_resolved_single_variant_via_material(tmp_path: Path, patch_config):
    patch_config(SINGLE)
    case_dir = tmp_path / "case001"
    case_dir.mkdir()
    material = tmp_path / "ticket.txt"
    material.write_text("software_version: 3.20.01\nticket: TR-123\n", encoding="utf-8")
    module = PiModule()
    binding = module._resolve_case_identity_binding(
        str(case_dir),
        {"_resolved_task_scope": "case_analysis", "material_paths": [str(material)]},
    )
    assert binding is not None
    assert binding["status"] == "resolved"
    assert binding["binding"]["variant_id"] == "gen6/byd_sc6h"
    assert binding["binding"]["software_version"] == "3.20.01"
    assert binding["variant"]["origin"] == "single_configured_variant"


def test_binding_resolved_via_intake_artifact_and_injects_variant(tmp_path: Path, patch_config):
    patch_config(SINGLE)
    case_dir = tmp_path / "case001"
    case_dir.mkdir()
    intake = {
        "schema_version": "cr60-analysis-intake.v1",
        "status": "partial",
        "handoff_id": "h-42",
        "identity": {
            "customer": {"status": "resolved", "value": "BYD"},
            "vehicle": {"status": "resolved", "value": "SC6H"},
            "code_branch": {"status": "resolved", "value": "master"},
        },
    }
    intake_file = case_dir / "cr60-analysis-intake.json"
    intake_file.write_text(json.dumps(intake, ensure_ascii=False), encoding="utf-8")
    module = PiModule()
    kwargs: dict = {"_resolved_task_scope": "case_analysis"}
    binding = module._resolve_case_identity_binding(str(case_dir), kwargs)
    assert binding["status"] == "resolved"
    assert binding["intake_handoff_id"] == "h-42"
    assert binding["intake_ref"]["sha256"]
    assert kwargs["variant_id"] == "gen6/byd_sc6h"
    assert module._intake_binding is binding


def test_branch_mismatch_gates(tmp_path: Path, patch_config):
    patch_config(SINGLE)
    case_dir = tmp_path / "case001"
    case_dir.mkdir()
    intake = {
        "schema_version": "cr60-analysis-intake.v1",
        "status": "partial",
        "identity": {
            "customer": {"status": "resolved", "value": "BYD"},
            "vehicle": {"status": "resolved", "value": "SC6H"},
            "code_branch": {"status": "resolved", "value": "feature/wrong"},
        },
    }
    (case_dir / "cr60-analysis-intake.json").write_text(
        json.dumps(intake, ensure_ascii=False), encoding="utf-8"
    )
    module = PiModule()
    result = module.run(
        question="为什么没有报警",
        case_dir=str(case_dir),
        project_root=str(tmp_path),
    )
    assert result.ok is False
    assert result.data["intake_binding_status"] == "blocked"
    assert result.data["version_gate"]["status"] == "mismatch"
    assert result.data["business_questions"][-1]["blocking"] is True


def test_explicit_variant_id_wins(tmp_path: Path, patch_config):
    patch_config(TWO)
    case_dir = tmp_path / "case001"
    case_dir.mkdir()
    module = PiModule()
    binding = module._resolve_case_identity_binding(
        str(case_dir),
        {"_resolved_task_scope": "case_analysis", "variant_id": "gen6/gwm_b26"},
    )
    # 显式项目被采纳；缺版本仍触发必要业务问题（错版本不进入 runtime 的前置）
    assert binding["binding"]["variant_id"] == "gen6/gwm_b26"
    assert binding["variant"]["origin"] == "explicit_input"
    assert binding["status"] == "needs_confirmation"
    assert any(q["id"] == "missing_software_version" for q in binding["business_questions"])


def test_case_metadata_multiple_match_becomes_business_question(tmp_path: Path, patch_config, monkeypatch):
    patch_config(TWO)
    shared = {"customer": "BYD", "vehicle_project": "SC6H", "coem_project_dir": "/repo/coem/BYD_SC6H"}
    ambiguous = {
        "gen6/a": dict(shared, source_context={"code_branch": "master"}),
        "gen6/b": dict(shared, source_context={"code_branch": "dev"}),
    }
    patch_config(ambiguous)
    case_dir = tmp_path / "case001"
    case_dir.mkdir()
    (case_dir / "case.yaml").write_text(
        "customer: BYD\nvehicle_project: SC6H\n", encoding="utf-8"
    )
    module = PiModule()
    result = module.run(
        question="为什么没有报警",
        case_dir=str(case_dir),
        project_root=str(tmp_path),
    )
    assert result.ok is False
    assert result.data["intake_binding_status"] == "needs_confirmation"
    assert result.data["business_questions"][0]["id"] == "choose_project"
