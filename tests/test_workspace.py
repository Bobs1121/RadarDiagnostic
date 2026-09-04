# -*- coding: utf-8 -*-
"""Offline tests for the V3 Workspace inheritance layer."""
from __future__ import annotations

from pathlib import Path

from core.workspace import Workspace


def _write(path: Path, text: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_workspace_inherits_nested_config_and_dbc_files(tmp_path: Path) -> None:
    workspaces = tmp_path / ".workspaces"
    base = workspaces / "base_core"
    variant = workspaces / "gen6_gwm_b26"

    _write(
        base / "config.yaml",
        """
workspace_id: base_core
resources:
  dbcs:
    - dbc/base.dbc
  requirements:
    - requirements/base.yaml
ai:
  remote:
    model: base-model
  local:
    enabled: true
""",
    )
    _write(base / "dbc" / "base.dbc", "VERSION base\n")

    _write(
        variant / "config.yaml",
        """
workspace_id: gen6_gwm_b26
inherits_from: base_core
resources:
  requirements:
    - requirements/gwm.yaml
ai:
  remote:
    temperature: 0.2
""",
    )
    _write(variant / "dbc" / "gwm.dbc", "VERSION gwm\n")

    workspace = Workspace("gen6_gwm_b26", workspaces)

    merged = workspace.get_config()
    assert merged["workspace_id"] == "gen6_gwm_b26"
    assert merged["resources"]["dbcs"] == ["dbc/base.dbc"]
    assert merged["resources"]["requirements"] == ["requirements/gwm.yaml"]
    assert merged["ai"]["remote"]["model"] == "base-model"
    assert merged["ai"]["remote"]["temperature"] == 0.2
    assert merged["ai"]["local"]["enabled"] is True

    assert [p.name for p in workspace.get_dbc_files()] == ["base.dbc", "gwm.dbc"]


def test_workspace_source_paths_prefer_coem_then_base_common(tmp_path: Path) -> None:
    workspaces = tmp_path / ".workspaces"
    base = workspaces / "base_core"
    variant = workspaces / "gen6_gwm_b26"

    _write(base / "config.yaml", "workspace_id: base_core\n")
    _write(base / "common" / "core.c")
    _write(variant / "config.yaml", "inherits_from: base_core\n")
    _write(variant / "coem" / "override.c")

    workspace = Workspace("gen6_gwm_b26", workspaces)

    assert workspace.get_source_paths() == [
        variant / "coem",
        base / "common",
    ]


def test_workspace_source_paths_fallback_to_local_common(tmp_path: Path) -> None:
    workspaces = tmp_path / ".workspaces"
    variant = workspaces / "gen6_gwm_b26"

    _write(variant / "config.yaml", "workspace_id: gen6_gwm_b26\n")
    _write(variant / "common" / "fallback.c")

    workspace = Workspace("gen6_gwm_b26", workspaces)

    assert workspace.get_source_paths() == [variant / "common"]


def test_workspace_from_variant_sanitizes_variant_id(tmp_path: Path) -> None:
    workspaces = tmp_path / ".workspaces"
    _write(workspaces / "coem_GWM_B26" / "config.yaml", "workspace_id: coem_GWM_B26\n")

    class VariantLike:
        variant_id = "coem/GWM_B26"

    workspace = Workspace.from_variant(VariantLike(), workspaces)

    assert workspace.name == "coem_GWM_B26"
    assert workspace.workspace_dir == workspaces / "coem_GWM_B26"
