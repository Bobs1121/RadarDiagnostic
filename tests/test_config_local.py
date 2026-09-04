# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from config import get_variant, load_config


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_load_config_merges_local_override_and_resolves_env(monkeypatch, tmp_path: Path) -> None:
    config_path = _write(
        tmp_path / "config.yaml",
        """
ai:
  remote:
    base_url: "${BASE_URL:-http://base}"
    model: base-model
nested:
  keep: base
  replace: from-base
list_value:
  - base-a
  - base-b
source_context:
  allow_branch_mismatch: false
""",
    )
    _write(
        tmp_path / "config.local.yaml",
        """
ai:
  remote:
    api_key: "${LOCAL_API_KEY:-local-key}"
nested:
  replace: from-local
  add: local-only
list_value:
  - local-a
source_context:
  code_branch: "${LOCAL_BRANCH:-feature/onboard}"
""",
    )
    monkeypatch.setenv("BASE_URL", "http://resolved-base")
    monkeypatch.setenv("LOCAL_API_KEY", "resolved-key")

    config = load_config(config_path)

    assert config["ai"]["remote"] == {
        "base_url": "http://resolved-base",
        "model": "base-model",
        "api_key": "resolved-key",
    }
    assert config["nested"] == {
        "keep": "base",
        "replace": "from-local",
        "add": "local-only",
    }
    assert config["list_value"] == ["local-a"]
    assert config["source_context"]["allow_branch_mismatch"] is False
    assert config["source_context"]["code_branch"] == "feature/onboard"


@pytest.mark.parametrize(
    "local_text, expected",
    [
        ("[\n", "Invalid local config YAML"),
        ("- not-a-mapping\n", "must contain a YAML mapping/object"),
    ],
)
def test_load_config_rejects_invalid_local_config(local_text: str, expected: str, tmp_path: Path) -> None:
    config_path = _write(tmp_path / "config.yaml", "ai:\n  local:\n    model: ok\n")
    local_path = _write(tmp_path / "config.local.yaml", local_text)

    with pytest.raises(ValueError) as exc_info:
        load_config(config_path)

    message = str(exc_info.value)
    assert expected in message
    assert str(local_path) in message


def test_project_intake_minimal_local_config_expands_to_internal_identity(tmp_path: Path) -> None:
    repo = tmp_path / "cr60_light"
    coem = repo / "coem" / "BYD_SC6H"
    dbc_dir = coem / "dbc"
    req_dir = coem / "requirements"
    case_dir = tmp_path / "cases" / "sc6hrcta001"
    (repo / "adas").mkdir(parents=True)
    coem.mkdir(parents=True)
    dbc_dir.mkdir(parents=True)
    req_dir.mkdir(parents=True)
    case_dir.mkdir(parents=True)
    front_dbc = _write(dbc_dir / "front.dbc", "VERSION \"front\"\n")
    rear_dbc = _write(dbc_dir / "rear.dbc", "VERSION \"rear\"\n")
    _write(req_dir / "rcta.md", "# RCTA\n")

    config_path = _write(
        tmp_path / "config.yaml",
        """
platforms:
  gen6_c_radar:
    language: c
    build_system: scons
default_variant: gen6/gwm_b26
codebases: {}
variants: {}
package_profiles: {}
""",
    )
    _write(
        tmp_path / "config.local.yaml",
        f"""
project_intake:
  default: byd_sc6h
  projects:
    byd_sc6h:
      code_root: {repo}
      branch: master
      coem: BYD_SC6H
      data: {case_dir}
      dbc:
        - {dbc_dir}
      requirements:
        - {req_dir}
""",
    )

    config = load_config(config_path)

    assert config["default_variant"] == "gen6/byd_sc6h"
    assert config["codebases"]["cr60_light"]["root_path"] == str(repo.resolve())
    assert config["codebases"]["cr60_light"]["branch"] == "master"

    variant_raw = config["variants"]["gen6/byd_sc6h"]
    assert variant_raw["codebase_id"] == "cr60_light"
    assert variant_raw["customer"] == "BYD"
    assert variant_raw["vehicle_project"] == "SC6H"
    assert variant_raw["coem_project_dir"] == "coem/BYD_SC6H"
    assert variant_raw["scope"]["include_globs"] == ["coem/BYD_SC6H/**", "adas/**"]
    assert variant_raw["source_context"]["source_root"] == str(repo.resolve())
    assert variant_raw["source_context"]["code_branch"] == "master"
    assert variant_raw["source_context"]["memory_dir"] == ".workspaces/gen6_byd_sc6h/memory"
    assert variant_raw["data_dir"] == str(case_dir.resolve())
    assert variant_raw["requirement_overlays"] == [str(req_dir.resolve())]
    assert variant_raw["dbc_sets"]["default"]["files"] == sorted(
        [str(front_dbc.resolve()), str(rear_dbc.resolve())],
        key=str.lower,
    )

    variant, codebase, _platform = get_variant(config)
    assert variant.variant_id == "gen6/byd_sc6h"
    assert codebase.root_path == str(repo.resolve())


def test_project_intake_requires_dbc(tmp_path: Path) -> None:
    repo = tmp_path / "cr60_light"
    (repo / "coem" / "BYD_SC6H").mkdir(parents=True)
    config_path = _write(tmp_path / "config.yaml", "{}\n")
    _write(
        tmp_path / "config.local.yaml",
        f"""
project_intake:
  default: byd_sc6h
  projects:
    byd_sc6h:
      code_root: {repo}
      branch: master
      coem: BYD_SC6H
      requirements: []
""",
    )

    with pytest.raises(ValueError, match=r"project_intake\.projects\.byd_sc6h\.dbc is required"):
        load_config(config_path)


def _write_yaml(path: Path, payload: dict) -> Path:
    path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return path


def _build_intake_repo(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    code_root = tmp_path / "cr60_light"
    (code_root / "coem" / "BYD_SC6H" / "buildscripts").mkdir(parents=True)
    (code_root / "coem" / "BYD_SC6H" / "buildscripts" / "build.bat").write_text(
        "echo build\n",
        encoding="utf-8",
    )
    (
        code_root / "coem" / "BYD_SC6H" / "components" / "AswPerception" / "func"
    ).mkdir(parents=True)
    (
        code_root / "coem" / "BYD_SC6H" / "components" / "AswPerception" / "func" / "adasFunc.c"
    ).write_text("void adasFunc(void) {}\n", encoding="utf-8")
    (
        code_root / "coem" / "SERES_E68" / "components" / "AswIf" / "ASW_IN"
    ).mkdir(parents=True)
    (
        code_root / "coem" / "SERES_E68" / "components" / "AswIf" / "ASW_IN" / "ASWIN_SystemState.c"
    ).write_text("void wrongCustomer(void) {}\n", encoding="utf-8")
    (code_root / "adas" / "algo").mkdir(parents=True)
    (code_root / "adas" / "symmetry" / "perception" / "src").mkdir(parents=True)
    (
        code_root / "adas" / "symmetry" / "perception" / "src" / "track.c"
    ).write_text("void track(void) {}\n", encoding="utf-8")
    (code_root / "adas" / "symmetry" / "perception" / "include").mkdir(parents=True)
    (
        code_root / "adas" / "symmetry" / "perception" / "include" / "paraDefine.h"
    ).write_text("#define TTC 2.0f\n", encoding="utf-8")
    (code_root / "asw" / "platform").mkdir(parents=True)
    dbc_root = tmp_path / "dbc_store"
    (dbc_root / "nested").mkdir(parents=True)
    (dbc_root / "nested" / "rear.dbc").write_text('VERSION "rear"\n', encoding="utf-8")
    (dbc_root / "front.dbc").write_text('VERSION "front"\n', encoding="utf-8")
    requirements_dir = tmp_path / "requirements"
    requirements_dir.mkdir(parents=True)
    (requirements_dir / "overlay.yaml").write_text("req_id: REQ-1\n", encoding="utf-8")
    case_dir = tmp_path / "cases" / "CASE001"
    case_dir.mkdir(parents=True)
    return code_root, dbc_root, requirements_dir, case_dir


def test_load_config_expands_project_intake_minimal_local_schema(tmp_path: Path) -> None:
    code_root, dbc_root, requirements_dir, case_dir = _build_intake_repo(tmp_path)
    config_path = _write(
        tmp_path / "config.yaml",
        """
platforms:
  gen6_c_radar:
    language: c
    build_system: scons
runtime:
  auto_dream_on_case_start: false
""",
    )
    _write_yaml(
        tmp_path / "config.local.yaml",
        {
            "project_intake": {
                "default": "byd_sc6h",
                "projects": {
                    "byd_sc6h": {
                        "code_root": str(code_root),
                        "branch": "feature/byd",
                        "coem": "BYD_SC6H",
                        "data": str(case_dir),
                        "dbc": str(dbc_root),
                        "requirements": str(requirements_dir),
                    }
                },
            }
        },
    )

    config = load_config(config_path)

    assert config["default_variant"] == "gen6/byd_sc6h"
    assert config["codebases"]["cr60_light"] == {
        "root_path": str(code_root.resolve()),
        "platform_id": "gen6_c_radar",
        "branch": "feature/byd",
    }

    variant = config["variants"]["gen6/byd_sc6h"]
    assert variant["codebase_id"] == "cr60_light"
    assert variant["customer"] == "BYD"
    assert variant["vehicle_project"] == "SC6H"
    assert variant["coem_project_dir"] == "coem/BYD_SC6H"
    assert variant["scope"] == {
        "include_globs": [
            "coem/BYD_SC6H/**",
            "adas/**",
            "asw/**",
        ],
        "exclude_globs": [
            "**/.git/**",
            "**/build/**",
            "**/__pycache__/**",
        ],
    }
    assert variant["build_entry"] == "coem/BYD_SC6H/buildscripts/build.bat"
    assert variant["dbc_sets"]["default"]["files"] == [
        str((dbc_root / "front.dbc").resolve()),
        str((dbc_root / "nested" / "rear.dbc").resolve()),
    ]
    assert variant["requirement_overlays"] == [str(requirements_dir.resolve())]
    assert (
        "coem\\BYD_SC6H\\components\\AswPerception\\func\\adasFunc.c"
        in variant["key_source_files"]
    )
    assert not any("SERES_E68" in path for path in variant["key_source_files"])
    assert not any(
        "SERES_E68" in path
        for paths in variant["source_domains"].values()
        for path in paths
    )
    assert variant["source_domains"]["customer_project"] == ["coem/BYD_SC6H"]
    assert "algorithm" in variant["source_domains"]
    assert variant["source_context"] == {
        "source_root": str(code_root.resolve()),
        "code_branch": "feature/byd",
        "allow_branch_mismatch": False,
        "workspace_dir": ".workspaces/gen6_byd_sc6h",
        "source_docs_dir": ".workspaces/gen6_byd_sc6h/source_docs",
        "memory_dir": ".workspaces/gen6_byd_sc6h/memory",
        "codegraph_db_path": ".workspaces/gen6_byd_sc6h/memory/codegraph/codegraph.db",
        "snapshots_dir": ".workspaces/gen6_byd_sc6h/memory/snapshots",
        "semantic_index_dir": ".workspaces/gen6_byd_sc6h/memory/semantic",
    }
    assert variant["knowledge_policy"] == {
        "reuse_from": [],
        "invalidate_on": [
            "code_commit_change",
            "dbc_hash_change",
            "requirement_hash_change",
            "source_scope_change",
        ],
    }
    assert variant["intake_key"] == "byd_sc6h"
    assert variant["data_dir"] == str(case_dir.resolve())
    assert variant["case_dir"] == str(case_dir.resolve())
    assert config["package_profiles"]["gen6/byd_sc6h/default"] == {
        "variant_id": "gen6/byd_sc6h",
        "build_flags": {},
    }


def test_load_config_project_intake_preserves_explicit_entries_and_stable_collision_id(
    tmp_path: Path,
) -> None:
    code_root, _, requirements_dir, _ = _build_intake_repo(tmp_path)
    dbc_file = tmp_path / "single.dbc"
    dbc_file.write_text('VERSION "solo"\n', encoding="utf-8")
    config_path = _write(
        tmp_path / "config.yaml",
        """
default_variant: gen6/legacy
codebases:
  cr60_light:
    root_path: D:\\legacy
    platform_id: gen6_c_radar
variants:
  gen6/legacy:
    codebase_id: cr60_light
    display_name: Legacy
  gen6/byd_sc6h:
    signal_alias_overrides:
      warn_signal: WARN_SIG
package_profiles:
  gen6/legacy/default:
    variant_id: gen6/legacy
    build_flags:
      mode: legacy
""",
    )
    _write_yaml(
        tmp_path / "config.local.yaml",
        {
            "project_intake": {
                "default": "byd_sc6h",
                "projects": {
                    "byd_sc6h": {
                        "code_root": str(code_root),
                        "coem": "coem/BYD_SC6H",
                        "dbc": [str(dbc_file)],
                        "requirements": [str(requirements_dir)],
                    }
                },
            }
        },
    )

    config = load_config(config_path)

    assert config["default_variant"] == "gen6/byd_sc6h"
    assert config["codebases"]["cr60_light"]["root_path"] == "D:\\legacy"
    assert config["codebases"]["cr60_light_byd_sc6h"]["root_path"] == str(code_root.resolve())
    assert config["variants"]["gen6/legacy"]["display_name"] == "Legacy"
    assert (
        config["variants"]["gen6/byd_sc6h"]["signal_alias_overrides"]["warn_signal"]
        == "WARN_SIG"
    )
    assert config["variants"]["gen6/byd_sc6h"]["codebase_id"] == "cr60_light_byd_sc6h"
    assert "gen6/legacy/default" in config["package_profiles"]


@pytest.mark.parametrize("missing_field", ["code_root", "coem", "dbc"])
def test_load_config_project_intake_requires_required_fields(
    missing_field: str,
    tmp_path: Path,
) -> None:
    code_root, dbc_root, _, _ = _build_intake_repo(tmp_path)
    config_path = _write(tmp_path / "config.yaml", "ai:\n  local:\n    model: ok\n")
    project_entry = {
        "code_root": str(code_root),
        "coem": "BYD_SC6H",
        "dbc": str(dbc_root),
    }
    project_entry.pop(missing_field)
    _write_yaml(
        tmp_path / "config.local.yaml",
        {
            "project_intake": {
                "default": "demo",
                "projects": {
                    "demo": project_entry,
                },
            }
        },
    )

    with pytest.raises(ValueError) as exc_info:
        load_config(config_path)

    assert f"project_intake.projects.demo.{missing_field}" in str(exc_info.value)
