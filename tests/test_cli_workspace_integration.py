# -*- coding: utf-8 -*-
"""Offline tests for the PR1 workspace/CLI integration."""
from __future__ import annotations

from pathlib import Path

from rich.console import Console

import cli


def test_resolve_workspace_context_defaults_to_sanitized_variant(tmp_path: Path) -> None:
    ctx = cli.resolve_workspace_context(
        {"identity": {"variant_id": "coem/GWM_B26"}},
        project_root=tmp_path,
    )

    assert ctx["name"] == "coem_GWM_B26"
    assert ctx["path"] == str(tmp_path / ".workspaces" / "coem_GWM_B26")
    assert ctx["exists"] is False


def test_resolve_workspace_context_override_takes_precedence(tmp_path: Path) -> None:
    ctx = cli.resolve_workspace_context(
        {"identity": {"variant_id": "gen6/gwm_b26"}},
        workspace_override="coem/Custom_Ws",
        project_root=tmp_path,
    )

    assert ctx["name"] == "coem_Custom_Ws"
    assert ctx["path"] == str(tmp_path / ".workspaces" / "coem_Custom_Ws")


def test_resolve_workspace_context_matches_workspace_sanitizer(tmp_path: Path) -> None:
    from core.workspace import Workspace

    class VariantLike:
        variant_id = "coem/GWM_B26"

    workspace_dir = tmp_path / "coem_GWM_B26"
    workspace_dir.mkdir()
    (workspace_dir / "config.yaml").write_text(
        "workspace_id: coem_GWM_B26\n", encoding="utf-8"
    )
    workspace = Workspace.from_variant(VariantLike(), tmp_path)

    assert cli._sanitize_workspace_name(VariantLike.variant_id) == workspace.name


def test_main_accepts_workspace_override_without_case_data(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}
    record_console = Console(record=True, width=160)

    def fake_load_config(variant_id=None, package_profile_id=None):
        captured["variant_id"] = variant_id
        captured["package_profile_id"] = package_profile_id
        return {
            "default_variant": "gen6/gwm_b26",
            "identity": {"variant_id": "gen6/gwm_b26"},
            "paths": {},
        }

    def fake_show_codegraph_stats(config):
        captured["config"] = config

    monkeypatch.setattr(cli, "console", record_console)
    monkeypatch.setattr(cli, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(cli, "load_config", fake_load_config)
    monkeypatch.setattr(cli, "_resolve_snapshot", lambda config, snapshot, root: {})
    monkeypatch.setattr(cli, "_show_codegraph_stats", fake_show_codegraph_stats)
    monkeypatch.setattr(
        cli.sys,
        "argv",
        [
            "cli.py",
            "--variant",
            "gen6/gwm_b26",
            "--workspace",
            "coem/Custom_Ws",
            "--codegraph-stats",
        ],
    )

    cli.main()

    assert captured["variant_id"] == "gen6/gwm_b26"
    assert captured["package_profile_id"] is None
    config = captured["config"]
    assert isinstance(config, dict)
    assert config["identity"]["workspace"] == "coem_Custom_Ws"
    assert config["identity"]["workspace_dir"] == str(
        tmp_path / ".workspaces" / "coem_Custom_Ws"
    )
    output = record_console.export_text()
    assert "Identity: variant=gen6/gwm_b26" in output
    assert "Workspace: coem_Custom_Ws (absent)" in output
