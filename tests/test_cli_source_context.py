# -*- coding: utf-8 -*-
"""Offline tests for CLI source-root and branch intake metadata."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import cli


def _run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        check=True,
        text=True,
    )


def _init_git_repo(repo: Path, branch: str = "feature/source-context") -> None:
    repo.mkdir()

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

    (repo / "tracked.txt").write_text("ready\n", encoding="utf-8")
    _run_git(repo, "add", "tracked.txt")
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


def test_apply_source_context_override_updates_paths_project_and_identity(tmp_path: Path) -> None:
    source_root = tmp_path / "source-tree"
    source_root.mkdir()
    config = {
        "paths": {"source_code": "legacy-source"},
        "project": {"source_code": "legacy-source"},
        "identity": {"variant_id": "gen6/gwm_b26"},
    }

    identity = cli.apply_source_context(
        config,
        source_root_override="source-tree",
        project_root=tmp_path,
    )

    expected = str(source_root.resolve())
    assert config["paths"]["source_code"] == expected
    assert config["project"]["source_code"] == expected
    assert identity["source_root"] == expected
    assert identity["source_root_origin"] == "cli"
    assert identity["code_branch_expected"] is None
    assert identity["code_branch_current"] is None
    assert identity["code_branch_status"] == "not_checked"
    assert identity["source_context_origin"] == "cli"


def test_apply_source_context_matching_branch_records_match(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_git_repo(repo, branch="feature/source-context")
    config = {"paths": {}, "project": {}, "identity": {}}

    identity = cli.apply_source_context(
        config,
        source_root_override=str(repo),
        code_branch="feature/source-context",
        project_root=tmp_path,
    )

    assert identity["source_root"] == str(repo.resolve())
    assert identity["code_branch_expected"] == "feature/source-context"
    assert identity["code_branch_current"] == "feature/source-context"
    assert identity["code_branch_status"] == "match"
    assert identity["source_root_origin"] == "cli"
    assert identity["code_branch_origin"] == "cli"
    assert identity["source_context_origin"] == "cli"


def test_apply_source_context_branch_mismatch_raises_by_default(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_git_repo(repo, branch="feature/source-context")
    config = {"paths": {}, "project": {}, "identity": {}}

    with pytest.raises(ValueError, match="expected 'release/candidate', current 'feature/source-context'"):
        cli.apply_source_context(
            config,
            source_root_override=str(repo),
            code_branch="release/candidate",
            project_root=tmp_path,
        )

    assert config["identity"]["code_branch_current"] == "feature/source-context"
    assert config["identity"]["code_branch_status"] == "mismatch"


def test_apply_source_context_branch_mismatch_can_be_allowed(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_git_repo(repo, branch="feature/source-context")
    config = {"paths": {}, "project": {}, "identity": {}}

    identity = cli.apply_source_context(
        config,
        source_root_override=str(repo),
        code_branch="release/candidate",
        allow_branch_mismatch=True,
        project_root=tmp_path,
    )

    assert identity["code_branch_current"] == "feature/source-context"
    assert identity["code_branch_expected"] == "release/candidate"
    assert identity["code_branch_status"] == "mismatch_allowed"
    assert "expected 'release/candidate'" in identity["code_branch_note"]
    assert identity["allow_branch_mismatch"] is True
    assert identity["allow_branch_mismatch_origin"] == "cli"


def test_apply_source_context_non_git_source_root_records_warning_status(tmp_path: Path) -> None:
    source_root = tmp_path / "plain-source"
    source_root.mkdir()
    config = {"paths": {"source_code": str(source_root)}, "project": {}, "identity": {}}

    identity = cli.apply_source_context(
        config,
        code_branch="feature/source-context",
        project_root=tmp_path,
    )

    assert identity["source_root"] == str(source_root)
    assert identity["code_branch_expected"] == "feature/source-context"
    assert identity["code_branch_current"] is None
    assert identity["code_branch_status"] == "not_git_repo"
    assert "git repository" in identity["code_branch_note"].lower()


def test_apply_source_context_uses_config_defaults_without_cli_args(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_git_repo(repo, branch="feature/source-context")
    config = {
        "paths": {},
        "project": {},
        "identity": {},
        "source_context": {
            "source_root": "repo",
            "code_branch": "feature/source-context",
        },
    }

    identity = cli.apply_source_context(config, project_root=tmp_path)

    assert identity["source_root"] == str(repo.resolve())
    assert identity["source_root_origin"] == "config"
    assert identity["code_branch_expected"] == "feature/source-context"
    assert identity["code_branch_origin"] == "config"
    assert identity["code_branch_current"] == "feature/source-context"
    assert identity["code_branch_status"] == "match"
    assert identity["source_context_origin"] == "config"


def test_apply_source_context_variant_defaults_override_top_level(tmp_path: Path) -> None:
    top_repo = tmp_path / "top-repo"
    variant_repo = tmp_path / "variant-repo"
    _init_git_repo(top_repo, branch="release/candidate")
    _init_git_repo(variant_repo, branch="feature/source-context")
    config = {
        "paths": {},
        "project": {},
        "identity": {"variant_id": "gen6/gwm_b26"},
        "source_context": {
            "source_root": "top-repo",
            "code_branch": "release/candidate",
        },
        "variants": {
            "gen6/gwm_b26": {
                "source_context": {
                    "source_root": "variant-repo",
                    "code_branch": "feature/source-context",
                }
            }
        },
    }

    identity = cli.apply_source_context(config, project_root=tmp_path)

    assert identity["source_root"] == str(variant_repo.resolve())
    assert identity["source_root_origin"] == "variant:gen6/gwm_b26"
    assert identity["code_branch_expected"] == "feature/source-context"
    assert identity["code_branch_origin"] == "variant:gen6/gwm_b26"
    assert identity["code_branch_current"] == "feature/source-context"
    assert identity["code_branch_status"] == "match"
    assert identity["source_context_origin"] == "variant:gen6/gwm_b26"


def test_apply_source_context_cli_overrides_config_defaults(tmp_path: Path) -> None:
    config_repo = tmp_path / "config-repo"
    cli_repo = tmp_path / "cli-repo"
    _init_git_repo(config_repo, branch="release/candidate")
    _init_git_repo(cli_repo, branch="feature/source-context")
    config = {
        "paths": {},
        "project": {},
        "identity": {},
        "source_context": {
            "source_root": "config-repo",
            "code_branch": "release/candidate",
        },
    }

    identity = cli.apply_source_context(
        config,
        source_root_override="cli-repo",
        code_branch="feature/source-context",
        project_root=tmp_path,
    )

    assert identity["source_root"] == str(cli_repo.resolve())
    assert identity["source_root_origin"] == "cli"
    assert identity["code_branch_expected"] == "feature/source-context"
    assert identity["code_branch_origin"] == "cli"
    assert identity["code_branch_current"] == "feature/source-context"
    assert identity["code_branch_status"] == "match"
    assert identity["source_context_origin"] == "cli"


def test_apply_source_context_config_allows_branch_mismatch(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_git_repo(repo, branch="feature/source-context")
    config = {
        "paths": {},
        "project": {},
        "identity": {},
        "source_context": {
            "source_root": "repo",
            "code_branch": "release/candidate",
            "allow_branch_mismatch": True,
        },
    }

    identity = cli.apply_source_context(config, project_root=tmp_path)

    assert identity["source_root"] == str(repo.resolve())
    assert identity["code_branch_expected"] == "release/candidate"
    assert identity["code_branch_current"] == "feature/source-context"
    assert identity["code_branch_status"] == "mismatch_allowed"
    assert identity["allow_branch_mismatch"] is True
    assert identity["allow_branch_mismatch_origin"] == "config"


def test_apply_source_context_without_configured_branch_keeps_not_checked(tmp_path: Path) -> None:
    source_root = tmp_path / "source-tree"
    source_root.mkdir()
    config = {
        "paths": {"source_code": str(source_root)},
        "project": {"source_code": str(source_root)},
        "identity": {},
    }

    identity = cli.apply_source_context(config, project_root=tmp_path)

    assert identity["source_root"] == str(source_root)
    assert identity["source_root_origin"] == "derived_codebase"
    assert identity["code_branch_expected"] is None
    assert identity["code_branch_current"] is None
    assert identity["code_branch_status"] == "not_checked"
