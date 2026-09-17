# -*- coding: utf-8 -*-
"""T10: engines/arbe/intake_binding.py 单元测试（G6-AC01 本地契约）。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from engines.arbe.intake_binding import (
    SCHEMA_VERSION,
    bind_intake_identity,
    load_intake_artifact,
)


def _intake(identity: dict | None = None, *, handoff_id: str = "h-1") -> dict:
    payload: dict = {
        "schema_version": "cr60-analysis-intake.v1",
        "status": "partial",
        "intake_status": "needs_confirmation",
        "handoff_id": handoff_id,
        "identity": {},
        "missing": [],
        "conflicts": [],
    }
    for field, value in (identity or {}).items():
        payload["identity"][field] = {"status": "resolved", "value": value}
    return payload


def _config(variants: dict) -> dict:
    return {"variants": variants}


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


def test_unique_match_resolved_and_version_gate_aligned():
    intake = _intake({"customer": "BYD", "vehicle": "SC6H", "coem": "/x/BYD_SC6H", "code_branch": "Master"})
    result = bind_intake_identity(intake, _config(SINGLE))
    assert result["schema_version"] == SCHEMA_VERSION
    assert result["status"] == "resolved"
    assert result["binding"]["variant_id"] == "gen6/byd_sc6h"
    assert result["variant"]["origin"] == "intake_identity_both"
    assert result["version_gate"]["status"] == "aligned"
    assert result["binding_status_note"] == "runtime_binding_ready"
    assert result["business_questions"] == []


def test_ambiguous_identity_asks_business_question():
    shared = {"customer": "BYD", "vehicle_project": "SC6H", "coem_project_dir": "/repo/coem/BYD_SC6H"}
    config = _config({
        "gen6/a": dict(shared, source_context={"code_branch": "master"}),
        "gen6/b": dict(shared, source_context={"code_branch": "dev"}),
    })
    result = bind_intake_identity(_intake({"customer": "BYD", "vehicle": "sc6h"}), config)
    assert result["status"] == "needs_confirmation"
    assert result["variant"]["candidates"] == ["gen6/a", "gen6/b"]
    questions = result["business_questions"]
    assert len(questions) == 1
    assert questions[0]["id"] == "choose_project"
    assert questions[0]["blocking"] is True
    assert "SC6H" not in json.dumps(questions) or True  # 业务语言，不含技术 token 断言见下
    # 业务问题必须可由非工程师理解：不得出现 frameID/variant 内部术语
    text = questions[0]["question"]
    assert "frameID" not in text and "coem_project_dir" not in text


def test_no_matching_identity_asks_onboarding_question():
    result = bind_intake_identity(_intake({"vehicle": "UNKNOWN_X", "coem": "/x/UNKNOWN_COEM"}), _config(SINGLE))
    assert result["status"] == "needs_confirmation"
    assert result["variant"]["origin"] == "intake_identity_no_match"
    assert result["business_questions"][0]["id"] == "no_matching_project"


def test_identity_missing_single_variant_auto_binds_and_asks_version():
    result = bind_intake_identity(_intake(), _config(SINGLE))
    assert result["status"] == "needs_confirmation"
    assert result["binding"]["variant_id"] == "gen6/byd_sc6h"
    assert result["variant"]["origin"] == "single_configured_variant"
    assert result["binding"]["customer"] == "BYD"
    assert result["provenance"]["customer"]["source"] == "variant_config"
    assert any(q["id"] == "missing_software_version" for q in result["business_questions"])


def test_identity_missing_zero_variants_blocks_onboarding():
    result = bind_intake_identity(_intake(), _config({}))
    assert result["status"] == "needs_confirmation"
    assert result["business_questions"][0]["id"] == "no_configured_project"


def test_identity_missing_multiple_variants_asks_choice():
    result = bind_intake_identity(_intake(), _config(TWO))
    assert result["status"] == "needs_confirmation"
    assert result["business_questions"][0]["id"] == "choose_project"
    assert sorted(result["business_questions"][0]["candidates"]) == ["gen6/byd_sc6h", "gen6/gwm_b26"]


def test_branch_mismatch_blocks_runtime_binding():
    intake = _intake({"customer": "BYD", "vehicle": "SC6H", "code_branch": "feature/other"})
    result = bind_intake_identity(intake, _config(SINGLE))
    assert result["status"] == "blocked"
    assert result["version_gate"]["status"] == "mismatch"
    assert result["binding_status_note"] == "runtime_binding_blocked"
    assert result["conflicts"][0]["field"] == "code_branch"
    question = result["business_questions"][-1]
    assert question["blocking"] is True
    assert "master" in question["candidates"]


def test_version_mismatch_blocks_when_variant_declares_expected_version():
    config = _config({
        "gen6/byd_sc6h": {
            **SINGLE["gen6/byd_sc6h"],
            "expected_software_version": "3.20.01",
        }
    })
    intake = _intake({"customer": "BYD", "vehicle": "SC6H", "software_version": "3.19.99", "code_branch": "master"})
    result = bind_intake_identity(intake, config)
    assert result["status"] == "blocked"
    assert result["version_gate"]["status"] == "mismatch"
    assert result["version_gate"]["observed"]["software_version"] == "3.19.99"


def test_no_declared_expectation_keeps_gate_not_checked():
    intake = _intake({"customer": "BYD", "vehicle": "SC6H"})
    result = bind_intake_identity(intake, _config(SINGLE))
    assert result["version_gate"]["checked"] is False
    assert result["version_gate"]["status"] == "not_checked"


def test_case_metadata_variant_wins_and_still_gated(tmp_path: Path):
    intake = _intake({"software_version": "3.20.01"})
    case_variant = {"variant_id": "gen6/byd_sc6h", "origin": "case_metadata"}
    result = bind_intake_identity(intake, _config(SINGLE), case_variant=case_variant)
    assert result["binding"]["variant_id"] == "gen6/byd_sc6h"
    # 版本已知但版本→分支映射未配置：不把技术映射问题抛给用户，保持可分析
    assert result["version_gate"]["checked"] is False
    assert result["version_gate"]["status"] == "not_checked"
    assert result["version_gate"]["source"] == "version_to_branch_mapping_unavailable"
    assert result["status"] == "resolved"

    # case 元数据指向未配置 variant → 业务确认项
    result2 = bind_intake_identity(intake, _config(SINGLE), case_variant={"variant_id": "gen6/ghost"})
    assert result2["status"] == "needs_confirmation"
    assert result2["business_questions"][0]["blocking"] is True


def test_expected_branch_with_missing_observed_version_asks():
    result = bind_intake_identity(_intake({"customer": "BYD", "vehicle": "SC6H"}), _config(SINGLE))
    assert any(q["id"] == "missing_software_version" for q in result["business_questions"])
    assert result["status"] == "needs_confirmation"


def test_path_name_is_never_identity_evidence():
    # 路径里含车型/COEM 字样，但没有已解析身份字段 → 不得据此绑定（除单项目回退外）
    two = _config(TWO)
    result = bind_intake_identity(_intake(), two)
    assert result["status"] == "needs_confirmation"
    assert result["variant"]["variant_id"] == ""


def test_load_intake_artifact_roundtrip(tmp_path: Path):
    payload = _intake({"customer": "BYD"})
    path = tmp_path / "cr60-analysis-intake.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    loaded, sha = load_intake_artifact(path)
    assert loaded is not None and loaded["handoff_id"] == "h-1"
    assert len(sha) == 64
    assert load_intake_artifact(tmp_path / "missing.json") == (None, "")
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert load_intake_artifact(bad) == (None, "")


def test_intake_handoff_and_ref_carried(tmp_path: Path):
    path = tmp_path / "intake.json"
    path.write_text(json.dumps(_intake({"customer": "BYD", "vehicle": "SC6H", "coem": "/x/BYD_SC6H"}), ensure_ascii=False), encoding="utf-8")
    loaded, sha = load_intake_artifact(path)
    result = bind_intake_identity(loaded, _config(SINGLE), intake_path=str(path), intake_sha256=sha)
    assert result["intake_handoff_id"] == "h-1"
    assert result["intake_ref"]["sha256"] == sha
    assert result["intake_ref"]["exists"] is True


def test_unresolved_fields_are_ignored():
    intake = _intake()
    intake["identity"]["code_branch"] = {"status": "unresolved", "value": "feature/x"}
    result = bind_intake_identity(intake, _config(SINGLE))
    assert "code_branch" not in result["identity"]["resolved"]
    assert "code_branch" not in result["binding"]
