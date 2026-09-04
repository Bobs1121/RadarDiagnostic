# -*- coding: utf-8 -*-
"""Offline tests for case-metadata-driven CLI variant resolution."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
import yaml

import cli
import config as config_module


def _write_yaml(path: Path, payload: dict) -> Path:
    path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return path


def test_resolve_variant_from_case_metadata_variant_id_wins_over_default_variant(
    tmp_path: Path,
) -> None:
    case_dir = tmp_path / "CASE001"
    case_dir.mkdir()
    _write_yaml(case_dir / "case.yaml", {"identity": {"variant": "sc6h"}})

    config = {
        "default_variant": "gen6/gwm_b26",
        "variants": {
            "gen6/gwm_b26": {"codebase_id": "legacy"},
            "gen6/byd_sc6h": {"codebase_id": "cr60_light"},
        },
    }

    resolved = cli._resolve_variant_from_case_metadata(config, case_dir)

    assert resolved is not None
    assert resolved["variant_id"] == "gen6/byd_sc6h"
    assert resolved["origin"] == "case_metadata"
    assert resolved["metadata"]["variant_id"] == "sc6h"


def test_resolve_variant_from_case_metadata_matches_project_identity_fields(
    tmp_path: Path,
) -> None:
    case_dir = tmp_path / "CASE002"
    case_dir.mkdir()
    (case_dir / "metadata.json").write_text(
        json.dumps(
            {
                "project": {
                    "customer": "BYD",
                    "vehicle_project": "SC6H",
                    "coem_project": "BYD_SC6H",
                }
            }
        ),
        encoding="utf-8",
    )

    config = {
        "default_variant": "gen6/gwm_b26",
        "variants": {
            "gen6/gwm_b26": {
                "customer": "GWM",
                "vehicle_project": "B26",
                "coem_project_dir": "coem/GWM_B26",
            },
            "gen6/byd_sc6h": {
                "customer": "byd",
                "vehicle_project": "SC-6H",
                "coem_project_dir": "coem/BYD_SC6H",
            },
        },
    }

    resolved = cli._resolve_variant_from_case_metadata(config, case_dir)

    assert resolved is not None
    assert resolved["variant_id"] == "gen6/byd_sc6h"
    assert resolved["metadata"]["customer"] == "BYD"
    assert resolved["metadata"]["vehicle_project"] == "SC6H"
    assert resolved["metadata"]["coem_project_dir"] == "BYD_SC6H"


def test_resolve_variant_from_case_metadata_ambiguous_match_raises(
    tmp_path: Path,
) -> None:
    case_dir = tmp_path / "CASE003"
    case_dir.mkdir()
    _write_yaml(
        case_dir / "case.yml",
        {"customer": "BYD", "vehicle_project": "SC6H"},
    )

    config = {
        "default_variant": "gen6/gwm_b26",
        "variants": {
            "gen6/byd_sc6h_a": {
                "customer": "BYD",
                "vehicle_project": "SC6H",
            },
            "gen6/byd_sc6h_b": {
                "customer": "byd",
                "vehicle_project": "sc-6h",
            },
        },
    }

    with pytest.raises(ValueError, match="Pass --variant") as exc_info:
        cli._resolve_variant_from_case_metadata(config, case_dir)

    message = str(exc_info.value)
    assert "gen6/byd_sc6h_a" in message
    assert "gen6/byd_sc6h_b" in message


def test_main_uses_case_metadata_variant_before_runtime_config_load(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    case_dir = tmp_path / "CASE004"
    case_dir.mkdir()
    _write_yaml(
        case_dir / "case.yaml",
        {
            "project": {
                "customer": "BYD",
                "vehicle_project": "SC6H",
                "coem_project_dir": "coem/BYD_SC6H",
            }
        },
    )
    (case_dir / "recording.blf").write_text("", encoding="utf-8")

    captured: dict[str, object] = {}
    base_config = {
        "default_variant": "gen6/gwm_b26",
        "variants": {
            "gen6/gwm_b26": {
                "customer": "GWM",
                "vehicle_project": "B26",
                "coem_project_dir": "coem/GWM_B26",
            },
            "gen6/byd_sc6h": {
                "customer": "BYD",
                "vehicle_project": "SC6H",
                "coem_project_dir": "coem/BYD_SC6H",
            },
        },
    }

    def fake_base_load_config(config_path: Path) -> dict:
        captured["base_config_path"] = config_path
        return copy.deepcopy(base_config)

    def fake_runtime_load_config(variant_id=None, package_profile_id=None) -> dict:
        captured["variant_id"] = variant_id
        captured["package_profile_id"] = package_profile_id
        return {
            "default_variant": "gen6/gwm_b26",
            "identity": {"variant_id": variant_id or "gen6/gwm_b26"},
            "paths": {},
            "project": {},
        }

    def fake_apply_source_context(config, **kwargs):
        return config.setdefault("identity", {})

    def fake_run_query(case_path: Path, question: str, runtime_config: dict) -> None:
        captured["query_case_path"] = case_path
        captured["question"] = question
        captured["runtime_config"] = copy.deepcopy(runtime_config)

    monkeypatch.setattr(cli, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(config_module, "load_config", fake_base_load_config)
    monkeypatch.setattr(cli, "load_config", fake_runtime_load_config)
    monkeypatch.setattr(cli, "apply_source_context", fake_apply_source_context)
    monkeypatch.setattr(cli, "_resolve_snapshot", lambda *args, **kwargs: {})
    monkeypatch.setattr(cli, "_run_query", fake_run_query)
    monkeypatch.setattr(
        cli.sys,
        "argv",
        ["cli.py", str(case_dir), "--query", "which variant?"],
    )

    cli.main()

    assert captured["base_config_path"] == tmp_path / "config.yaml"
    assert captured["variant_id"] == "gen6/byd_sc6h"
    runtime_config = captured["runtime_config"]
    assert isinstance(runtime_config, dict)
    assert runtime_config["identity"]["variant_origin"] == "case_metadata"
    assert runtime_config["identity"]["case_metadata"]["customer"] == "BYD"
    assert runtime_config["identity"]["case_metadata"]["vehicle_project"] == "SC6H"
    assert runtime_config["identity"]["case_metadata"]["coem_project_dir"] == "coem/BYD_SC6H"
