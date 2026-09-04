# -*- coding: utf-8 -*-
"""Offline tests for case_loader workspace DBC resolution."""
from __future__ import annotations

from pathlib import Path

import pytest

from parsers import case_loader
from parsers import blf_parser as _blf_parser_mod


class _StubWorkspace:
    def __init__(self, dbc_files: list[Path]):
        self._dbc_files = dbc_files

    def get_dbc_files(self) -> list[Path]:
        return list(self._dbc_files)


def test_load_case_data_prefers_workspace_dbc_files_before_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    project_root = tmp_path / "project"
    project_root.mkdir()
    workspace_dbcs = [
        tmp_path / "workspace" / "base.dbc",
        tmp_path / "workspace" / "variant.dbc",
    ]
    config = {"paths": {"dbc_files": ["legacy_a.dbc", "legacy_b.dbc"]}}
    created: list[object] = []

    class FakeDbcLoader:
        def __init__(self, dbc_paths, base_dir=None):
            self.dbc_paths = list(dbc_paths)
            self.base_dir = base_dir
            created.append(self)

    monkeypatch.setattr(case_loader, "DbcLoader", FakeDbcLoader)

    result = case_loader.load_case_data(
        case_dir,
        config,
        project_root,
        workspace=_StubWorkspace(workspace_dbcs),
    )

    assert len(created) == 1
    assert created[0].dbc_paths == workspace_dbcs + ["legacy_a.dbc", "legacy_b.dbc"]
    assert created[0].base_dir == project_root
    assert result.dbc is created[0]


def test_load_case_data_uses_legacy_config_dbc_files_without_workspace(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    project_root = tmp_path / "project"
    project_root.mkdir()
    config = {"paths": {"dbc_files": ["legacy_only.dbc"]}}
    created: list[object] = []

    class FakeDbcLoader:
        def __init__(self, dbc_paths, base_dir=None):
            self.dbc_paths = list(dbc_paths)
            self.base_dir = base_dir
            created.append(self)

    monkeypatch.setattr(case_loader, "DbcLoader", FakeDbcLoader)

    result = case_loader.load_case_data(case_dir, config, project_root)

    assert len(created) == 1
    assert created[0].dbc_paths == ["legacy_only.dbc"]
    assert created[0].base_dir == project_root
    assert result.dbc is created[0]


def test_load_case_data_accepts_minimal_config_when_workspace_provides_dbcs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    project_root = tmp_path / "project"
    project_root.mkdir()
    workspace_dbcs = [tmp_path / "workspace" / "only.dbc"]
    created: list[object] = []

    class FakeDbcLoader:
        def __init__(self, dbc_paths, base_dir=None):
            self.dbc_paths = list(dbc_paths)
            self.base_dir = base_dir
            created.append(self)

    monkeypatch.setattr(case_loader, "DbcLoader", FakeDbcLoader)

    result = case_loader.load_case_data(
        case_dir,
        {},
        project_root,
        workspace=_StubWorkspace(workspace_dbcs),
    )

    assert len(created) == 1
    assert created[0].dbc_paths == workspace_dbcs
    assert result.dbc is created[0]


def test_load_case_data_keeps_empty_dbc_resolution_degraded_for_blf(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    blf_path = case_dir / "capture.blf"
    blf_path.write_bytes(b"")
    project_root = tmp_path / "project"
    project_root.mkdir()
    config = {"paths": {"dbc_files": []}}
    captured: dict[str, object] = {}

    def fail_dbc_loader(*args, **kwargs):
        raise AssertionError("DbcLoader should not be constructed when no DBC paths are resolved")

    class FakeBlfParser:
        def __init__(self, blf_path, dbc_loader=None):
            captured["blf_path"] = blf_path
            captured["dbc_loader"] = dbc_loader

        def get_metadata(self) -> dict:
            return {"file": "capture.blf", "message_count": 0}

        def iter_frames(self, decode=True):
            captured["decode"] = decode
            return []

    monkeypatch.setattr(case_loader, "DbcLoader", fail_dbc_loader)
    # The plugin dispatch lazily imports BlfParser from parsers.blf_parser,
    # so we patch there (case_loader.BlfParser is no longer the dispatch seam).
    monkeypatch.setattr(_blf_parser_mod, "BlfParser", FakeBlfParser)

    result = case_loader.load_case_data(
        case_dir,
        config,
        project_root,
        workspace=_StubWorkspace([]),
    )

    assert result.dbc is None
    assert captured["blf_path"] == blf_path
    assert captured["dbc_loader"] is None
    assert captured["decode"] is True
    assert result.blf_meta == {"file": "capture.blf", "message_count": 0}
