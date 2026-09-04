# -*- coding: utf-8 -*-
"""Offline tests for the dry-run-first workspace migration script."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import scripts.migrate_to_workspaces as migration


def _write(path: Path, text: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_main_dry_run_prints_plan_without_mutation(tmp_path: Path, capsys) -> None:
    _write(tmp_path / "memory" / "projects" / "coem_GWM_B26" / "project.md", "# legacy\n")
    _write(
        tmp_path / "memory" / "projects" / "coem_GWM_B26" / "functions" / "FCTA.json",
        "{}",
    )

    exit_code = migration.main(["--project-root", str(tmp_path)])

    assert exit_code == 0
    assert not (tmp_path / ".workspaces").exists()

    plan = json.loads(capsys.readouterr().out)
    assert plan["mode"] == "dry-run"
    assert plan["summary"]["legacy_project_count"] == 1

    entry = plan["entries"][0]
    assert entry["legacy_variant"] == "coem_GWM_B26"
    assert entry["workspace_name"] == "coem_GWM_B26"
    assert entry["memory_target_dir"] == str(
        Path(".workspaces") / "coem_GWM_B26" / "memory"
    )
    assert set(entry["source_files"]) == {"functions\\FCTA.json", "project.md"}
    assert entry["config_exists"] is False
    assert entry["manifest_exists"] is False
    assert str(Path(".workspaces") / "coem_GWM_B26" / "memory") in entry[
        "missing_standard_dirs"
    ]


def test_execute_migration_creates_workspace_config_dirs_and_copies_memory(
    tmp_path: Path,
) -> None:
    legacy_dir = tmp_path / "memory" / "projects" / "gwm_b26"
    _write(legacy_dir / "project.md", "# project memory\n")
    _write(legacy_dir / "patterns.json", "[]")
    _write(legacy_dir / "functions" / "FCTA.json", '{"function": "FCTA"}')

    plan = migration.execute_migration(tmp_path)

    assert plan["mode"] == "execute"
    assert plan["summary"]["projects_migrated"] == 1
    workspace_dir = tmp_path / ".workspaces" / "gwm_b26"
    memory_dir = workspace_dir / "memory"

    for dirname in migration.STANDARD_WORKSPACE_DIRS:
        assert (workspace_dir / dirname).is_dir()

    assert (memory_dir / "project.md").read_text(encoding="utf-8") == "# project memory\n"
    assert (memory_dir / "patterns.json").read_text(encoding="utf-8") == "[]"
    assert legacy_dir.joinpath("project.md").exists()

    config = yaml.safe_load((workspace_dir / "config.yaml").read_text(encoding="utf-8"))
    assert config["workspace_id"] == "gwm_b26"
    assert config["migration"]["legacy_variant"] == "gwm_b26"
    assert config["migration"]["legacy_memory_dir"] == str(
        Path("memory") / "projects" / "gwm_b26"
    )
    assert config["migration"]["strategy"] == "copy-missing-only"

    manifest = json.loads((workspace_dir / migration.MANIFEST_FILENAME).read_text(encoding="utf-8"))
    assert manifest["workspace_id"] == "gwm_b26"
    assert set(manifest["copied_files"]) == {
        "functions\\FCTA.json",
        "patterns.json",
        "project.md",
    }
    assert manifest["config_created"] is True
    assert manifest["skipped_existing"] == []


def test_execute_migration_skips_existing_workspace_memory_files(tmp_path: Path) -> None:
    legacy_dir = tmp_path / "memory" / "projects" / "sc6h"
    _write(legacy_dir / "project.md", "legacy value\n")

    workspace_dir = tmp_path / ".workspaces" / "sc6h"
    _write(workspace_dir / "memory" / "project.md", "workspace value\n")
    _write(workspace_dir / "config.yaml", "workspace_id: sc6h\n")

    plan = migration.execute_migration(tmp_path)

    entry = plan["entries"][0]
    assert (workspace_dir / "memory" / "project.md").read_text(encoding="utf-8") == (
        "workspace value\n"
    )
    assert entry["config_created"] is False
    assert entry["copied_files"] == []
    assert entry["skipped_existing"] == ["project.md"]

    manifest = json.loads((workspace_dir / migration.MANIFEST_FILENAME).read_text(encoding="utf-8"))
    assert manifest["config_created"] is False
    assert manifest["copied_files"] == []
    assert manifest["skipped_existing"] == ["project.md"]


def test_dry_run_after_execute_reports_no_remaining_migration(tmp_path: Path) -> None:
    legacy_dir = tmp_path / "memory" / "projects" / "gwm_b26"
    _write(legacy_dir / "project.md", "# project memory\n")
    _write(legacy_dir / "functions" / "FCTA.json", "{}")

    migration.execute_migration(tmp_path)
    plan = migration.build_migration_plan(tmp_path)

    assert plan["summary"]["legacy_project_count"] == 1
    assert plan["summary"]["projects_requiring_migration"] == 0
    assert plan["summary"]["source_file_count"] == 2
    assert plan["summary"]["missing_target_file_count"] == 0
    entry = plan["entries"][0]
    assert entry["needs_migration"] is False
    assert entry["missing_target_files"] == []
