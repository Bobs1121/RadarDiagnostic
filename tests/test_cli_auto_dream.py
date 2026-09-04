# -*- coding: utf-8 -*-
"""Offline tests for CLI auto-dream intake behavior."""
from __future__ import annotations

from pathlib import Path

from rich.console import Console

import cli


def _make_case_dir(tmp_path: Path) -> Path:
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    (case_dir / "recording.bag").write_text("", encoding="utf-8")
    return case_dir


def _base_config(auto_dream_on_case_start: bool = False) -> dict:
    return {
        "default_variant": "gen6/gwm_b26",
        "identity": {"variant_id": "gen6/gwm_b26"},
        "paths": {},
        "project": {},
        "runtime": {
            "auto_dream_on_case_start": auto_dream_on_case_start,
        },
    }


def _patch_main_dependencies(
    monkeypatch,
    tmp_path: Path,
    config: dict,
    dream_calls: list[bool],
    diagnosis_calls: list[tuple[Path, str, str]],
) -> None:
    monkeypatch.setattr(cli, "console", Console(record=True, width=160))
    monkeypatch.setattr(
        cli,
        "load_config",
        lambda variant_id=None, package_profile_id=None: config,
    )
    monkeypatch.setattr(
        cli,
        "apply_source_context",
        lambda *args, **kwargs: args[0].setdefault("identity", {}),
    )
    monkeypatch.setattr(cli, "_resolve_snapshot", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        cli,
        "resolve_workspace_context",
        lambda *args, **kwargs: {
            "name": "gen6_gwm_b26",
            "path": str(tmp_path / ".workspaces" / "gen6_gwm_b26"),
            "exists": False,
        },
    )
    monkeypatch.setattr(
        cli,
        "_run_dream",
        lambda force=False, config=None: dream_calls.append(force),
    )
    monkeypatch.setattr(
        cli,
        "_run_diagnosis",
        lambda case_dir, problem, expected, config=None: diagnosis_calls.append(
            (case_dir, problem, expected)
        ),
    )
    monkeypatch.setattr(cli, "_run_query", lambda *args, **kwargs: None)


def test_daily_case_run_skips_auto_dream_by_default(
    monkeypatch,
    tmp_path: Path,
) -> None:
    case_dir = _make_case_dir(tmp_path)
    dream_calls: list[bool] = []
    diagnosis_calls: list[tuple[Path, str, str]] = []
    _patch_main_dependencies(
        monkeypatch,
        tmp_path,
        _base_config(auto_dream_on_case_start=False),
        dream_calls,
        diagnosis_calls,
    )
    monkeypatch.setattr(
        cli.sys,
        "argv",
        ["cli.py", str(case_dir), "-p", "missing alarm", "-e", "should alarm"],
    )

    cli.main()

    assert dream_calls == []
    assert diagnosis_calls == [(case_dir, "missing alarm", "should alarm")]


def test_runtime_config_can_enable_auto_dream_on_case_start(
    monkeypatch,
    tmp_path: Path,
) -> None:
    case_dir = _make_case_dir(tmp_path)
    dream_calls: list[bool] = []
    diagnosis_calls: list[tuple[Path, str, str]] = []
    _patch_main_dependencies(
        monkeypatch,
        tmp_path,
        _base_config(auto_dream_on_case_start=True),
        dream_calls,
        diagnosis_calls,
    )
    monkeypatch.setattr(
        cli.sys,
        "argv",
        ["cli.py", str(case_dir), "-p", "missing alarm", "-e", "should alarm"],
    )

    cli.main()

    assert dream_calls == [False]
    assert diagnosis_calls == [(case_dir, "missing alarm", "should alarm")]


def test_auto_dream_flag_opt_in_runs_gated_dream_once(
    monkeypatch,
    tmp_path: Path,
) -> None:
    case_dir = _make_case_dir(tmp_path)
    dream_calls: list[bool] = []
    diagnosis_calls: list[tuple[Path, str, str]] = []
    _patch_main_dependencies(
        monkeypatch,
        tmp_path,
        _base_config(auto_dream_on_case_start=False),
        dream_calls,
        diagnosis_calls,
    )
    monkeypatch.setattr(
        cli.sys,
        "argv",
        [
            "cli.py",
            str(case_dir),
            "-p",
            "missing alarm",
            "-e",
            "should alarm",
            "--auto-dream",
        ],
    )

    cli.main()

    assert dream_calls == [False]
    assert diagnosis_calls == [(case_dir, "missing alarm", "should alarm")]


def test_dream_flag_keeps_force_mode_without_extra_auto_dream(
    monkeypatch,
    tmp_path: Path,
) -> None:
    case_dir = _make_case_dir(tmp_path)
    dream_calls: list[bool] = []
    diagnosis_calls: list[tuple[Path, str, str]] = []
    _patch_main_dependencies(
        monkeypatch,
        tmp_path,
        _base_config(auto_dream_on_case_start=True),
        dream_calls,
        diagnosis_calls,
    )
    monkeypatch.setattr(
        cli.sys,
        "argv",
        [
            "cli.py",
            str(case_dir),
            "--dream",
            "-p",
            "missing alarm",
            "-e",
            "should alarm",
        ],
    )

    cli.main()

    assert dream_calls == [True]
    assert diagnosis_calls == [(case_dir, "missing alarm", "should alarm")]


def test_run_dream_bypasses_gate_when_freshness_changed(monkeypatch, tmp_path: Path) -> None:
    import memory.auto_dream as auto_dream_module
    import memory.memory_system as memory_system_module

    calls: list[tuple[bool, str | None]] = []
    freshness_updates: list[bool] = []

    class _StubMemorySystem:
        def __init__(self, project_root, memory_dir=None, config=None):
            self.memory_dir = Path(memory_dir or (tmp_path / "memory"))

    class _StubAutoDream:
        def __init__(self, memory_system, router, project_root, config=None):
            pass

        def try_dream(self, on_status=None, force=False, reason=None):
            calls.append((force, reason))
            return {
                "summary": "ok",
                "conflicts_found": [],
                "_code_learning": {"skipped": True},
            }

    monkeypatch.setattr(memory_system_module, "MemorySystem", _StubMemorySystem)
    monkeypatch.setattr(auto_dream_module, "AutoDream", _StubAutoDream)
    monkeypatch.setattr(cli, "get_router", lambda config: object())

    def fake_check(config, project_root, update=False):
        freshness_updates.append(update)
        return config["identity"]["freshness"]

    monkeypatch.setattr(cli, "_check_variant_freshness", fake_check)

    config = {
        "identity": {
            "variant_id": "gen6/gwm_b26",
            "freshness": {
                "any_changed": True,
                "code_changed": False,
                "constants_changed": False,
                "changed_keys": ["requirements_hash"],
                "state_path": str(tmp_path / "memory" / "freshness_state.json"),
            },
        },
        "project": {"memory_dir": str(tmp_path / "memory")},
    }

    cli._run_dream(force=False, config=config)

    assert calls == [(True, "variant freshness drift: requirements_hash")]
    # Requirement drift alone is not resolved by the current Dream modules.
    # Do not advance the global baseline and accidentally mark stale
    # requirement knowledge as fresh.
    assert freshness_updates == []
