# -*- coding: utf-8 -*-
"""Dry-run-first migration from legacy ``memory/projects`` into V3 workspaces."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
STANDARD_WORKSPACE_DIRS = ("memory", "dbc", "requirements", "source_docs", "codegraph")
MANIFEST_FILENAME = "migration_manifest.json"


def sanitize_workspace_name(variant: str) -> str:
    """Match ``Workspace.from_variant()`` naming for variant-scoped sandboxes."""
    return str(variant).replace("/", "_").replace("\\", "_")


def _rel(path: Path, root: Path) -> str:
    """Return a project-relative path string for audit output."""
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _sorted_relative_files(source_dir: Path) -> list[str]:
    """Return all source files relative to ``source_dir`` in deterministic order."""
    files: list[str] = []
    for path in sorted(source_dir.rglob("*")):
        if path.is_file():
            files.append(str(path.relative_to(source_dir)))
    return files


def _build_workspace_config(
    *,
    workspace_name: str,
    legacy_variant: str,
    legacy_dir: Path,
    workspace_dir: Path,
    project_root: Path,
) -> dict[str, Any]:
    return {
        "workspace_id": workspace_name,
        "migration": {
            "legacy_variant": legacy_variant,
            "legacy_memory_dir": _rel(legacy_dir, project_root),
            "memory_target_dir": _rel(workspace_dir / "memory", project_root),
            "tool": "scripts/migrate_to_workspaces.py",
            "strategy": "copy-missing-only",
            "standard_dirs": list(STANDARD_WORKSPACE_DIRS),
        },
    }


def discover_legacy_projects(project_root: Path | str = PROJECT_ROOT) -> list[dict[str, str]]:
    """Discover direct child directories under ``memory/projects``."""
    root = Path(project_root)
    legacy_root = root / "memory" / "projects"
    if not legacy_root.exists():
        return []

    projects: list[dict[str, str]] = []
    for legacy_dir in sorted(path for path in legacy_root.iterdir() if path.is_dir()):
        workspace_name = sanitize_workspace_name(legacy_dir.name)
        projects.append(
            {
                "legacy_variant": legacy_dir.name,
                "workspace_name": workspace_name,
                "legacy_memory_dir": _rel(legacy_dir, root),
                "workspace_dir": _rel(root / ".workspaces" / workspace_name, root),
                "memory_target_dir": _rel(
                    root / ".workspaces" / workspace_name / "memory", root
                ),
            }
        )
    return projects


def build_migration_plan(project_root: Path | str = PROJECT_ROOT) -> dict[str, Any]:
    """Return the dry-run plan without mutating the filesystem."""
    root = Path(project_root)
    legacy_root = root / "memory" / "projects"
    workspaces_root = root / ".workspaces"
    entries: list[dict[str, Any]] = []

    for discovered in discover_legacy_projects(root):
        legacy_variant = discovered["legacy_variant"]
        workspace_name = discovered["workspace_name"]
        legacy_dir = legacy_root / legacy_variant
        workspace_dir = workspaces_root / workspace_name
        memory_target_dir = workspace_dir / "memory"
        config_path = workspace_dir / "config.yaml"
        manifest_path = workspace_dir / MANIFEST_FILENAME
        source_files = _sorted_relative_files(legacy_dir)
        standard_dir_paths = [workspace_dir / name for name in STANDARD_WORKSPACE_DIRS]
        missing_target_files = [
            rel_path
            for rel_path in source_files
            if not (memory_target_dir / rel_path).exists()
        ]

        entries.append(
            {
                "legacy_variant": legacy_variant,
                "workspace_name": workspace_name,
                "legacy_memory_dir": _rel(legacy_dir, root),
                "workspace_dir": _rel(workspace_dir, root),
                "memory_target_dir": _rel(memory_target_dir, root),
                "workspace_exists": workspace_dir.exists(),
                "memory_target_exists": memory_target_dir.exists(),
                "config_path": _rel(config_path, root),
                "config_exists": config_path.exists(),
                "manifest_path": _rel(manifest_path, root),
                "manifest_exists": manifest_path.exists(),
                "source_files": source_files,
                "source_file_count": len(source_files),
                "missing_target_files": missing_target_files,
                "missing_target_file_count": len(missing_target_files),
                "standard_dirs": list(STANDARD_WORKSPACE_DIRS),
                "missing_standard_dirs": [
                    _rel(path, root) for path in standard_dir_paths if not path.exists()
                ],
                "needs_migration": (
                    bool(missing_target_files)
                    or not config_path.exists()
                    or not manifest_path.exists()
                    or any(not path.exists() for path in standard_dir_paths)
                ),
            }
        )

    return {
        "project_root": str(root),
        "legacy_projects_dir": _rel(legacy_root, root),
        "workspaces_dir": _rel(workspaces_root, root),
        "mode": "dry-run",
        "entries": entries,
        "summary": {
            "legacy_project_count": len(entries),
            "projects_requiring_migration": sum(
                1 for entry in entries if entry["needs_migration"]
            ),
            "source_file_count": sum(entry["source_file_count"] for entry in entries),
            "missing_target_file_count": sum(
                entry["missing_target_file_count"] for entry in entries
            ),
        },
    }


def _copy_missing_files(source_dir: Path, target_dir: Path) -> tuple[list[str], list[str]]:
    copied: list[str] = []
    skipped_existing: list[str] = []

    for source_path in sorted(source_dir.rglob("*")):
        rel_path = source_path.relative_to(source_dir)
        target_path = target_dir / rel_path
        if source_path.is_dir():
            target_path.mkdir(parents=True, exist_ok=True)
            continue

        target_path.parent.mkdir(parents=True, exist_ok=True)
        if target_path.exists():
            skipped_existing.append(str(rel_path))
            continue

        shutil.copy2(source_path, target_path)
        copied.append(str(rel_path))

    return copied, skipped_existing


def execute_migration(project_root: Path | str = PROJECT_ROOT) -> dict[str, Any]:
    """Create workspace sandboxes and copy legacy memory without deleting sources."""
    root = Path(project_root)
    plan = build_migration_plan(root)
    plan["mode"] = "execute"

    for entry in plan["entries"]:
        legacy_dir = root / entry["legacy_memory_dir"]
        workspace_dir = root / entry["workspace_dir"]
        memory_target_dir = root / entry["memory_target_dir"]
        config_path = root / entry["config_path"]
        manifest_path = root / entry["manifest_path"]

        workspace_dir.mkdir(parents=True, exist_ok=True)

        created_dirs: list[str] = []
        for dirname in STANDARD_WORKSPACE_DIRS:
            dir_path = workspace_dir / dirname
            if not dir_path.exists():
                dir_path.mkdir(parents=True, exist_ok=True)
                created_dirs.append(_rel(dir_path, root))

        config_created = False
        if not config_path.exists():
            config = _build_workspace_config(
                workspace_name=entry["workspace_name"],
                legacy_variant=entry["legacy_variant"],
                legacy_dir=legacy_dir,
                workspace_dir=workspace_dir,
                project_root=root,
            )
            config_path.write_text(
                yaml.safe_dump(config, sort_keys=False, allow_unicode=True),
                encoding="utf-8",
            )
            config_created = True

        copied_files, skipped_existing = _copy_missing_files(legacy_dir, memory_target_dir)

        manifest = {
            "workspace_id": entry["workspace_name"],
            "legacy_variant": entry["legacy_variant"],
            "legacy_memory_dir": entry["legacy_memory_dir"],
            "workspace_dir": entry["workspace_dir"],
            "memory_target_dir": entry["memory_target_dir"],
            "config_path": entry["config_path"],
            "config_created": config_created,
            "standard_dirs": list(STANDARD_WORKSPACE_DIRS),
            "created_dirs": created_dirs,
            "source_files": entry["source_files"],
            "copied_files": copied_files,
            "skipped_existing": skipped_existing,
            "tool": "scripts/migrate_to_workspaces.py",
            "strategy": "copy-missing-only",
        }
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        entry.update(
            {
                "config_created": config_created,
                "manifest_written": True,
                "created_dirs": created_dirs,
                "copied_files": copied_files,
                "copied_file_count": len(copied_files),
                "skipped_existing": skipped_existing,
                "skipped_existing_count": len(skipped_existing),
                "workspace_exists": True,
                "memory_target_exists": True,
                "config_exists": True,
                "manifest_exists": True,
                "needs_migration": False,
            }
        )

    plan["summary"] = {
        "legacy_project_count": len(plan["entries"]),
        "projects_migrated": len(plan["entries"]),
        "copied_file_count": sum(
            entry.get("copied_file_count", 0) for entry in plan["entries"]
        ),
        "skipped_existing_count": sum(
            entry.get("skipped_existing_count", 0) for entry in plan["entries"]
        ),
    }
    return plan


def print_plan(plan: dict[str, Any]) -> None:
    json.dump(plan, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Migrate legacy memory/projects variants into V3 workspaces."
    )
    parser.add_argument(
        "--project-root",
        default=str(PROJECT_ROOT),
        help="Repository root containing memory/projects and .workspaces.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Apply the migration. Without this flag, only print a dry-run plan.",
    )
    args = parser.parse_args(argv)

    project_root = Path(args.project_root).resolve()
    plan = execute_migration(project_root) if args.execute else build_migration_plan(project_root)
    print_plan(plan)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
