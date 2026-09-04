# -*- coding: utf-8 -*-
"""Stage 1 tests: verify P0 fixes in ai/orchestrator.py.

Covers:
- P0-1:  codegraph_db_path is now a real, independently-resolvable property.
- P0-1b: platform_id unwraps the get_variant() tuple correctly.
- P0-2:  adapter dispatch uses self.platform_id (not variant_id).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config import load_config  # noqa: E402
from ai.orchestrator import Orchestrator  # noqa: E402


def _make_orchestrator(tmp_path: Path, monkeypatch, variant_id: str = "gen6/gwm_b26"):
    config = load_config()
    config["identity"] = {
        "variant_id": variant_id,
        "project_key": variant_id.split("/")[-1],
    }
    monkeypatch.setattr(Orchestrator, "_init_signal_maps", lambda self: None)
    return Orchestrator(config, tmp_path)


# ── P0-1b: platform_id tuple unpack ─────────────────────────────────────────

def test_platform_id_resolves_real_platform(tmp_path: Path, monkeypatch) -> None:
    """platform_id returns the codebase's real platform, not the fallback."""
    orch = _make_orchestrator(tmp_path, monkeypatch, variant_id="gen6/gwm_b26")
    pid = orch.platform_id
    assert pid == "gen6_c_radar"  # gwm_cr60light codebase → gen6_c_radar


def test_platform_id_is_str_not_tuple(tmp_path: Path, monkeypatch) -> None:
    """Regression: platform_id must be a plain str, not the (v,cb,pf) tuple."""
    orch = _make_orchestrator(tmp_path, monkeypatch, variant_id="gen6/gwm_b26")
    assert isinstance(orch.platform_id, str)


# ── P0-1: codegraph_db_path property exists & resolves ──────────────────────

def test_codegraph_db_path_exists(tmp_path: Path, monkeypatch) -> None:
    """codegraph_db_path is a real property returning a Path (no AttributeError)."""
    orch = _make_orchestrator(tmp_path, monkeypatch, variant_id="gen6/gwm_b26")
    p = orch.codegraph_db_path
    assert isinstance(p, Path)


def test_platform_id_and_codegraph_path_independent(tmp_path: Path, monkeypatch) -> None:
    """The two properties are independently resolvable (no orphaned dead code)."""
    orch = _make_orchestrator(tmp_path, monkeypatch, variant_id="gen6/gwm_b26")
    assert isinstance(orch.platform_id, str)
    assert isinstance(orch.codegraph_db_path, Path)


# ── P0-2: adapter dispatch uses platform_id ─────────────────────────────────

def test_adapter_dispatch_uses_platform_id(monkeypatch) -> None:
    """_get_code_learner_adapter passes self.platform_id, not variant_id."""
    fake_adapter = object()

    import ai.orchestrator as orch_mod
    from ai.platform_adapters import factory

    captured = {}
    def _fake_get(platform_id, *a, **k):
        captured["platform_id"] = platform_id
        return fake_adapter

    monkeypatch.setattr(factory, "get_code_learner_adapter", _fake_get)
    # Cause the orchestrator to import the factory lazily inside the method.
    monkeypatch.setattr(orch_mod.Orchestrator, "platform_id", property(lambda self: "gen6_c_radar"))

    orch = object.__new__(Orchestrator)
    orch._code_learner_adapter = None
    orch.config = {"paths": {"source_code": "."}}
    orch.project_root = Path(".")
    orch.identity = type("I", (), {"variant_id": "gen6/gwm_b26"})()

    adapter = orch._get_code_learner_adapter()
    assert adapter is fake_adapter
    assert captured.get("platform_id") == "gen6_c_radar"