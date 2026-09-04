# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from ai.modules import MODULE_REGISTRY
from ai.modules.base import ModuleResult
from ai.modules.cr60_intake import CR60IntakeModule
from engines.arbe.intake import build_intake


def test_intake_is_material_first_and_fail_closed_for_missing_binding(tmp_path: Path):
    bag = tmp_path / "record.bag"
    bag.write_bytes(b"bag")
    payload = build_intake(data_paths=[str(bag)])

    assert payload["schema_version"] == "cr60-analysis-intake.v1"
    assert payload["status"] == "blocked"
    assert payload["intake_status"] == "needs_confirmation"
    assert payload["data"]["paths"][0]["local_validation"] == "exists"
    assert "software_version" in payload["missing"]
    assert "code_branch_or_version_to_branch_mapping" in payload["missing"]
    assert payload["input_policy"]["path_names_are_not_identity_evidence"] is True


def test_intake_resolves_explicit_identity_and_records_remote_validation(tmp_path: Path):
    payload = build_intake(
        data_paths=["/home/hoz2wx/CR60LIGHT/data/qzh/CRGVI-1829/sample.bag"],
        software_version="BL03RC02.7_S",
        vehicle="QZHCX",
        coem="BYD_UKE",
        code_branch="release/BL03RC02.7_S",
        function=["FCTA", "FCTB"],
        server_host="10.190.171.44",
        arbe_root="/home/hoz2wx/CR60LIGHT/cr60_light_arbe",
    )

    assert payload["status"] == "partial"
    assert payload["intake_status"] == "needs_confirmation"
    assert payload["identity"]["software_version"]["value"] == "BL03RC02.7_S"
    assert payload["identity"]["function"]["value"] == ["FCTA", "FCTB"]
    assert payload["data"]["paths"][0]["local_validation"] == "remote_unverified"
    assert any(item["type"] == "remote_validation" for item in payload["confirmation_required"])


def test_intake_parses_json_material_and_builds_handoff(tmp_path: Path):
    material = tmp_path / "case.json"
    material.write_text(
        json.dumps(
            {
                "ticket_id": "CRGVI-1829",
                "trigger_function": ["FCTA", "FCTB"],
                "vehicle": "QZHCX",
                "trigger_version": "BL03RC02.7_S",
                "coem": "BYD_UKE",
                "code_branch": "release/BL03RC02.7_S",
                "data_path": "/tmp/record.bag",
            }
        ),
        encoding="utf-8",
    )
    payload = build_intake(material_paths=[str(material)], match_text=["CRGVI-1829"])

    assert payload["status"] == "partial"
    assert payload["intake_status"] == "needs_confirmation"
    assert payload["identity"]["ticket_id"]["value"] == "CRGVI-1829"
    assert payload["identity"]["vehicle"]["value"] == "QZHCX"
    assert payload["identity"]["coem"]["value"] == "BYD_UKE"
    assert payload["data"]["paths"][0]["path"] == "/tmp/record.bag"


def test_intake_xlsx_uses_current_cr60_b_c_e_g_j_contract(tmp_path: Path):
    openpyxl = pytest.importorskip("openpyxl")
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "03_QZH"
    # Header names intentionally do not all use the same language as the
    # runtime workbook; the parser must recognize the documented aliases.
    sheet.append(["unused", "Ticket No.", "Trigger Function", "unused", "Vehicle", "unused", "Trigger Version", "unused", "unused", "Data Path"])
    sheet.append(["", "CRGVI-1829", "FCTA/FCTB", "", "QZHCX", "", "BL03RC02.7_S", "", "", "/tmp/record.bag"])
    path = tmp_path / "BYD_CR60LT_功能问题清单.xlsx"
    workbook.save(path)

    payload = build_intake(
        material_paths=[str(path)],
        data_paths=["/tmp/record.bag"],
        ticket_id="CRGVI-1829",
        match_text=["CRGVI-1829"],
        coem="BYD_UKE",
        code_branch="release/BL03RC02.7_S",
    )

    assert payload["identity"]["vehicle"]["value"] == "QZHCX"
    assert payload["identity"]["software_version"]["value"] == "BL03RC02.7_S"
    assert payload["identity"]["function"]["value"] == ["FCTA/FCTB"]
    assert payload["materials"][0]["matched_rows"] == 1
    assert payload["materials"][0]["sheets"][0]["mapping"]["G"] == "software_version"
    assert payload["environment"]["vehicle"]["model"] == "QZHCX"
    assert payload["data"]["cases"][0]["source_selector"]["algo_submodule_branch"] == "release/BL03RC02.7_S"


def test_intake_module_writes_schema_artifact(tmp_path: Path):
    output = tmp_path / "intake.json"
    result = CR60IntakeModule().safe_run(
        data_paths=["/home/test/sample.bag"],
        software_version="v1",
        vehicle="TEST",
        coem="TEST_COEM",
        code_branch="main",
        output=str(output),
    )

    assert isinstance(result, ModuleResult)
    assert result.ok is True
    assert result.module == "cr60-intake"
    assert output.exists()
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert saved["schema_version"] == "cr60-analysis-intake.v1"
    assert saved["handoff_id"].startswith("intake-")
    assert saved["data"]["cases"]
    assert str(output) in result.artifacts


def test_intake_cli_and_registry():
    assert MODULE_REGISTRY["cr60-intake"] is CR60IntakeModule
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers()
    CR60IntakeModule.register_cli(sub)
    args = parser.parse_args(
        [
            "cr60-intake",
            "--data",
            "/tmp/record.bag",
            "--software-version",
            "v1",
            "--vehicle",
            "TEST",
            "--coem",
            "TEST_COEM",
            "--code-branch",
            "main",
        ]
    )
    assert args._module_cls is CR60IntakeModule
    assert args.data_paths == ["/tmp/record.bag"]
