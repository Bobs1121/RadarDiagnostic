# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import hashlib
import subprocess
from pathlib import Path

import yaml

from ai.modules import MODULE_REGISTRY
from ai.modules.project_init import ProjectInitModule


def _write(path: Path, text: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        check=True,
        text=True,
    )


def _init_git_repo(repo: Path, branch: str = "master") -> None:
    repo.mkdir(parents=True, exist_ok=True)
    init = subprocess.run(
        ["git", "init", "-b", branch],
        cwd=repo,
        capture_output=True,
        check=False,
        text=True,
    )
    if init.returncode != 0:
        _run_git(repo, "init")
        _run_git(repo, "branch", "-m", branch)

    _write(repo / "README.txt", "repo ready\n")
    _run_git(repo, "add", "README.txt")
    _run_git(
        repo,
        "-c",
        "user.name=Copilot Test",
        "-c",
        "user.email=copilot-test@example.com",
        "commit",
        "-m",
        "init",
    )


def _build_cr60_repo(repo: Path, *, coem_dirs: tuple[str, ...] = ("BYD_SC6H",)) -> None:
    _init_git_repo(repo, branch="master")
    files = [
        "common/shared_header.h",
        "adas/symmetry/perception/src/objAttribCal.c",
        "adas/symmetry/perception/src/track.c",
        "adas/symmetry/perception/src/postProcess.c",
        "adas/symmetry/perception/include/perception_public_def.h",
        "adas/symmetry/perception/include/structDefine.h",
        "adas/symmetry/perception/include/paraDefine.h",
        "adas/symmetry/perception/include/globalVarDefine.h",
    ]
    for coem_dir in coem_dirs:
        files.extend(
            [
                f"coem/{coem_dir}/buildscripts/build.bat",
                f"coem/{coem_dir}/components/AswPerception/func/adasFunc.c",
                f"coem/{coem_dir}/components/AswPerception/func/adasFunc.h",
                f"coem/{coem_dir}/components/AswIf/ASW_IN/ASWIN_SystemState.c",
                f"coem/{coem_dir}/components/AswIf/ASW_IN/ASWIN_SystemState.h",
                f"coem/{coem_dir}/components/AswIf/ASW_IN/RteComMapping.c",
                f"coem/{coem_dir}/components/AswIf/ASW_IN/RteComMapping.h",
                f"coem/{coem_dir}/components/AswIf/ASW_OUT/ASWOUT_OutCalc.c",
            ]
        )
    for rel in files:
        _write(repo / rel, "/* file */\n")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_project_init_dry_run_builds_cr60_light_variant_metadata(tmp_path: Path) -> None:
    project_root = tmp_path / "radarAnalyze"
    project_root.mkdir()
    code_root = tmp_path / "cr60_light"
    _build_cr60_repo(code_root)
    case_dir = tmp_path / "cases" / "CASE001"
    case_dir.mkdir(parents=True)
    dbc_a = _write(tmp_path / "dbc" / "primary.dbc", 'VERSION "A"\n')
    dbc_b = _write(tmp_path / "dbc" / "private.dbc", 'VERSION "B"\n')
    req_dir = tmp_path / "requirements"
    _write(req_dir / "feature.yaml", "req_id: REQ-1\n")
    _write(req_dir / "notes.txt", "notes\n")
    _write(req_dir / "ignore.bin", "skip\n")
    req_file = _write(tmp_path / "materials" / "traceability.md", "# traceability\n")

    module = ProjectInitModule(project_root=project_root)
    result = module.safe_run(
        name="CR60 Light",
        code_root=str(code_root),
        dbcs=[str(dbc_a), str(dbc_b)],
        customer="BYD",
        vehicle_project="SC6H",
        requirements=[str(req_dir), str(req_file)],
        case_dir=str(case_dir),
        dry_run=True,
    )

    assert result.ok is True
    assert result.message == "project-init:ready"
    assert result.data["variant_id"] == "gen6/byd_sc6h"
    assert result.data["codebase_id"] == "cr60_light"
    assert result.data["coem_project_dir"] == "coem/BYD_SC6H"
    assert result.data["workspace_dir"] == str(project_root / ".workspaces" / "gen6_byd_sc6h")
    assert result.data["config_path"] == str(project_root / "config.local.yaml")
    assert result.data["expected_branch"] == "master"
    assert result.data["current_branch"] == "master"
    assert result.data["current_commit"]
    assert not (project_root / "config.local.yaml").exists()
    assert not (project_root / ".workspaces" / "gen6_byd_sc6h").exists()

    local_config = result.data["local_config"]
    variant_cfg = local_config["variants"]["gen6/byd_sc6h"]
    codebase_cfg = local_config["codebases"]["cr60_light"]
    assert codebase_cfg["root_path"] == str(code_root.resolve())
    assert codebase_cfg["expected_branch"] == "master"
    assert codebase_cfg["current_branch"] == "master"
    assert codebase_cfg["current_commit"]
    assert variant_cfg["customer"] == "BYD"
    assert variant_cfg["vehicle_project"] == "SC6H"
    assert variant_cfg["coem_project_dir"] == "coem/BYD_SC6H"
    assert variant_cfg["build_entry"] == "coem/BYD_SC6H/buildscripts/build.bat"
    assert variant_cfg["scope"]["include_globs"] == [
        "coem/BYD_SC6H/**",
        "common/**",
        "adas/symmetry/**",
    ]
    assert variant_cfg["knowledge_policy"] == {
        "reuse_from": [],
        "invalidate_on": [
            "code_commit_change",
            "dbc_hash_change",
            "requirement_hash_change",
            "source_scope_change",
        ],
    }
    assert variant_cfg["requirement_overlays"] == [
        str(req_dir.resolve()),
        str(req_file.resolve()),
    ]
    assert variant_cfg["dbc_sets"]["default"]["files"] == [
        str(dbc_a.resolve()),
        str(dbc_b.resolve()),
    ]
    assert variant_cfg["source_context"]["source_docs_dir"] == str(
        Path(".workspaces") / "gen6_byd_sc6h" / "source_docs"
    )
    assert variant_cfg["source_context"]["memory_dir"] == str(
        Path(".workspaces") / "gen6_byd_sc6h" / "memory"
    )
    assert variant_cfg["source_context"]["codegraph_db_path"] == str(
        Path(".workspaces") / "gen6_byd_sc6h" / "memory" / "codegraph" / "codegraph.db"
    )
    assert variant_cfg["source_context"]["snapshots_dir"] == str(
        Path(".workspaces") / "gen6_byd_sc6h" / "memory" / "snapshots"
    )
    assert variant_cfg["source_domains"]["customer_project"] == ["coem/BYD_SC6H"]
    assert "coem\\BYD_SC6H\\components\\AswPerception\\func\\adasFunc.c" in variant_cfg["key_source_files"]

    requirement_manifest = result.data["requirement_manifest"]
    assert requirement_manifest["validated_paths"] == [
        str(req_dir.resolve()),
        str(req_file.resolve()),
    ]
    assert requirement_manifest["requirement_sources"][0]["type"] == "directory"
    assert requirement_manifest["requirement_sources"][0]["file_count"] == 2
    assert [item["relative_path"] for item in requirement_manifest["requirement_sources"][0]["files"]] == [
        "feature.yaml",
        "notes.txt",
    ]
    assert requirement_manifest["requirement_sources"][1]["type"] == "file"
    assert requirement_manifest["requirement_sources"][1]["sha256"] == _sha256(req_file.resolve())

    hit_resolution = result.data["hit_resolution"]
    assert hit_resolution["priority"] == [
        "explicit --variant",
        "case metadata",
        "config.local default_variant",
    ]
    assert hit_resolution["resolved"] == {
        "variant_id": "gen6/byd_sc6h",
        "codebase_id": "cr60_light",
        "customer": "BYD",
        "vehicle_project": "SC6H",
        "coem_project_dir": "coem/BYD_SC6H",
        "expected_branch": "master",
        "current_branch": "master",
        "current_commit": result.data["current_commit"],
        "dbc": [str(dbc_a.resolve()), str(dbc_b.resolve())],
        "requirements": [str(req_dir.resolve()), str(req_file.resolve())],
    }
    assert '--variant "gen6/byd_sc6h"' in result.data["run_command"]


def test_project_init_writes_local_overlay_and_manifest_preserves_other_entries(tmp_path: Path) -> None:
    project_root = tmp_path / "radarAnalyze"
    project_root.mkdir()
    code_root = tmp_path / "cr60_light"
    _build_cr60_repo(code_root, coem_dirs=("BYD_SC6H", "GWM_B26"))
    dbc_path = _write(tmp_path / "dbc" / "primary.dbc", 'VERSION "A"\n')
    req_dir = tmp_path / "requirements"
    req_yaml = _write(req_dir / "customer" / "overlay.yaml", "req_id: REQ-2\n")

    existing_local = project_root / "config.local.yaml"
    existing_local.write_text(
        yaml.safe_dump(
            {
                "default_variant": "gen6/legacy",
                "codebases": {"legacy": {"root_path": "D:\\legacy", "platform_id": "gen6_c_radar"}},
                "variants": {
                    "gen6/legacy": {
                        "codebase_id": "legacy",
                        "display_name": "Legacy",
                        "default_package_profile": "gen6/legacy/default",
                    }
                },
                "package_profiles": {
                    "gen6/legacy/default": {"variant_id": "gen6/legacy", "build_flags": {"vehicle_type": "LEGACY"}}
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    module = ProjectInitModule(project_root=project_root)
    result = module.safe_run(
        name="BYD SC6H",
        code_root=str(code_root),
        dbcs=[str(dbc_path)],
        customer="BYD",
        vehicle_project="SC6H",
        requirements=[str(req_dir)],
    )

    assert result.ok is True
    assert result.message == "project-init:written"

    local_config = yaml.safe_load(existing_local.read_text(encoding="utf-8"))
    assert local_config["default_variant"] == "gen6/byd_sc6h"
    assert "legacy" in local_config["codebases"]
    assert "gen6/legacy" in local_config["variants"]
    assert local_config["variants"]["gen6/byd_sc6h"]["source_context"]["memory_dir"] == str(
        Path(".workspaces") / "gen6_byd_sc6h" / "memory"
    )
    assert local_config["variants"]["gen6/byd_sc6h"]["coem_project_dir"] == "coem/BYD_SC6H"
    assert local_config["variants"]["gen6/byd_sc6h"]["requirement_overlays"] == [str(req_dir.resolve())]
    assert local_config["package_profiles"]["gen6/byd_sc6h/default"]["variant_id"] == "gen6/byd_sc6h"

    workspace_dir = project_root / ".workspaces" / "gen6_byd_sc6h"
    assert workspace_dir.exists()
    assert (workspace_dir / "source_docs").exists()
    assert (workspace_dir / "memory" / "codegraph").exists()
    assert (workspace_dir / "memory" / "snapshots").exists()
    assert (workspace_dir / "memory" / "semantic").exists()
    assert (workspace_dir / "requirements").exists()

    workspace_config = yaml.safe_load((workspace_dir / "config.yaml").read_text(encoding="utf-8"))
    assert workspace_config["workspace_id"] == "gen6_byd_sc6h"
    assert workspace_config["variant_id"] == "gen6/byd_sc6h"
    assert workspace_config["resources"]["requirement_manifest"] == "requirements/sources.yaml"

    workspace_manifest = yaml.safe_load((workspace_dir / "manifest.yaml").read_text(encoding="utf-8"))
    assert workspace_manifest["variant_id"] == "gen6/byd_sc6h"
    assert workspace_manifest["codebase_id"] == "cr60_light"
    assert workspace_manifest["customer"] == "BYD"
    assert workspace_manifest["vehicle_project"] == "SC6H"
    assert workspace_manifest["coem_project_dir"] == "coem/BYD_SC6H"
    assert workspace_manifest["expected_branch"] == "master"
    assert workspace_manifest["current_branch"] == "master"
    assert workspace_manifest["current_commit"]
    assert workspace_manifest["knowledge_dirs"]["source_docs_dir"] == str(
        Path(".workspaces") / "gen6_byd_sc6h" / "source_docs"
    )

    dbc_manifest = yaml.safe_load((workspace_dir / "dbc" / "sources.yaml").read_text(encoding="utf-8"))
    assert dbc_manifest["dbc_sources"][0]["source_path"] == str(dbc_path.resolve())
    assert dbc_manifest["dbc_sources"][0]["sha256"] == _sha256(dbc_path.resolve())

    requirement_manifest = yaml.safe_load((workspace_dir / "requirements" / "sources.yaml").read_text(encoding="utf-8"))
    assert requirement_manifest["validated_paths"] == [str(req_dir.resolve())]
    assert requirement_manifest["requirement_sources"][0]["type"] == "directory"
    assert requirement_manifest["requirement_sources"][0]["files"][0]["relative_path"] == "customer/overlay.yaml"
    assert requirement_manifest["requirement_sources"][0]["files"][0]["sha256"] == _sha256(req_yaml.resolve())


def test_project_init_requires_explicit_coem_project_when_inference_is_ambiguous(tmp_path: Path) -> None:
    project_root = tmp_path / "radarAnalyze"
    project_root.mkdir()
    code_root = tmp_path / "cr60_light"
    _build_cr60_repo(code_root, coem_dirs=("BYD_SC6H", "GWM_B26"))
    dbc_path = _write(tmp_path / "dbc" / "primary.dbc", 'VERSION "A"\n')

    module = ProjectInitModule(project_root=project_root)
    result = module.safe_run(
        name="CR60 Light",
        code_root=str(code_root),
        dbcs=[str(dbc_path)],
        dry_run=True,
    )

    assert result.ok is False
    assert "--coem-project" in result.message
    assert "BYD_SC6H" in result.message
    assert "GWM_B26" in result.message


def test_project_init_registry_and_cli_repeatable_args() -> None:
    assert MODULE_REGISTRY["project-init"] is ProjectInitModule

    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="module")
    ProjectInitModule.register_cli(subparsers)

    args = parser.parse_args(
        [
            "project-init",
            "--name",
            "CR60 Light",
            "--code-root",
            "D:\\cr60_light",
            "--dbc",
            "one.dbc",
            "--dbc",
            "two.dbc",
            "--customer",
            "BYD",
            "--vehicle-project",
            "SC6H",
            "--coem-project",
            "BYD_SC6H",
            "--requirements",
            "req-a",
            "--requirements",
            "req-b",
            "--dry-run",
        ]
    )

    assert args.module == "project-init"
    assert args.dbcs == ["one.dbc", "two.dbc"]
    assert args.customer == "BYD"
    assert args.vehicle_project == "SC6H"
    assert args.coem_project == "BYD_SC6H"
    assert args.requirements == ["req-a", "req-b"]
    assert args.expected_branch == "master"
    assert args.dry_run is True
