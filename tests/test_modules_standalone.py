# -*- coding: utf-8 -*-
"""
Standalone, fully-offline tests for the M1/M4 capability modules.

No network, no LLM, no real .bag/.blf files. M1 uses an injected fake
CodeGraph stub; M4 builds a real in-memory :class:`FrameStore` (SQLite
``:memory:``) and probes it.
"""
from __future__ import annotations

import argparse

import pytest

from ai.modules.base import BaseModule, ModuleResult
from ai.modules.code_structure import CodeStructureModule
from ai.modules.data_diagnostics import DataDiagnosticsModule


# ── M1: CodeStructureModule (fake CodeGraph) ───────────────────────────────

class _FakeCodeGraph:
    """Minimal stand-in exposing only the methods the module calls."""

    is_available = True

    def get_stats(self) -> dict:
        return {
            "available": True,
            "total_nodes": 42,
            "total_edges": 100,
            "node_counts": {"FUNCTION": 30, "SIGNAL": 12},
        }

    def get_function_by_name(self, name: str) -> dict:
        return {"id": f"FUNCTION:{name}", "name": name, "type": "FUNCTION"}

    def get_functions_using_signal(self, signal_name: str) -> list[dict]:
        return [
            {"func_name": "FctaAlarmProcess", "signal_name": signal_name},
            {"func_name": "FctaUpdateStatus", "signal_name": signal_name},
        ]

    def get_callers(self, func_name: str) -> list[dict]:
        return [{"caller_name": "MainLoop", "target": func_name}]

    def get_calibration_params(self, category=None) -> list[dict]:
        return [{"name": "K_FCTA_TTC", "category": category or "all"}]


def test_modules_are_base_subclasses_with_names():
    assert issubclass(CodeStructureModule, BaseModule)
    assert issubclass(DataDiagnosticsModule, BaseModule)
    assert CodeStructureModule.name == "code-query"
    assert DataDiagnosticsModule.name == "data-explore"


def test_code_structure_stats():
    mod = CodeStructureModule(codegraph=_FakeCodeGraph())
    res = mod.safe_run(query_type="stats")
    assert isinstance(res, ModuleResult)
    assert res.ok is True
    assert res.module == "code-query"
    payload = res.data["data"]
    assert payload["total_nodes"] == 42
    assert payload["node_counts"]["FUNCTION"] == 30


def test_code_structure_signal_users():
    mod = CodeStructureModule(codegraph=_FakeCodeGraph())
    res = mod.safe_run(query_type="signal_users", signal="FCTA_Warn")
    assert res.ok is True
    payload = res.data["data"]
    assert isinstance(payload, list)
    assert len(payload) == 2
    assert payload[0]["signal_name"] == "FCTA_Warn"


def test_code_structure_function_lookup():
    mod = CodeStructureModule(codegraph=_FakeCodeGraph())
    res = mod.safe_run(query_type="function", name="FctbAlarmProcess")
    assert res.ok is True
    assert res.data["data"]["name"] == "FctbAlarmProcess"


def test_code_structure_unknown_query_type_fails():
    mod = CodeStructureModule(codegraph=_FakeCodeGraph())
    res = mod.safe_run(query_type="does_not_exist")
    assert res.ok is False
    assert "unknown query_type" in res.message


def test_code_structure_signal_users_without_signal_fails():
    mod = CodeStructureModule(codegraph=_FakeCodeGraph())
    res = mod.safe_run(query_type="signal_users")
    assert res.ok is False


def test_code_structure_no_graph_fails_gracefully():
    mod = CodeStructureModule()  # no codegraph, no db_path
    res = mod.safe_run(query_type="stats")
    assert isinstance(res, ModuleResult)
    assert res.ok is False
    assert "no CodeGraph" in res.message


def test_code_structure_cli_wiring():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers()
    CodeStructureModule.register_cli(sub)
    args = parser.parse_args(
        ["code-query", "--query-type", "stats", "--db-path", "x.db"],
    )
    assert args.query_type == "stats"
    assert args._module_cls is CodeStructureModule
    mod = CodeStructureModule.from_cli_args(args)
    assert isinstance(mod, CodeStructureModule)


# ── M4: DataDiagnosticsModule (real in-memory FrameStore) ──────────────────

# DataProbe needs asteval + numpy; skip the live-probe tests if unavailable.
try:
    import numpy as _np  # noqa: F401
    import asteval as _asteval  # noqa: F401
    _HAS_PROBE_DEPS = True
except Exception:  # pragma: no cover - environment dependent
    _HAS_PROBE_DEPS = False


def _make_store():
    """Build a real in-memory FrameStore with a few radar_objects rows."""
    from parsers.frame_store import FrameStore

    store = FrameStore(":memory:")
    store.bulk_insert_radar_objects([
        {"timestamp_ns": 1_000_000_000, "radar_id": 1, "obj_id": 1,
         "dist_x": -2.0, "dist_y": 1.0},
        {"timestamp_ns": 1_000_000_000, "radar_id": 1, "obj_id": 2,
         "dist_x": -5.0, "dist_y": -1.0},
        {"timestamp_ns": 2_000_000_000, "radar_id": 1, "obj_id": 1,
         "dist_x": 3.0, "dist_y": 0.5},
    ])
    return store


def test_data_diagnostics_no_store_fails():
    mod = DataDiagnosticsModule()
    res = mod.safe_run(field="dist_x")
    assert isinstance(res, ModuleResult)
    assert res.ok is False
    assert res.message == "no data store loaded"


@pytest.mark.skipif(not _HAS_PROBE_DEPS, reason="asteval/numpy not installed")
def test_data_diagnostics_probe_global_stats():
    store = _make_store()
    mod = DataDiagnosticsModule(store=store)
    res = mod.safe_run(
        field="dist_x", table="radar_objects", stats=["count", "min", "max"],
    )
    assert isinstance(res, ModuleResult)
    assert res.ok is True
    assert res.module == "data-explore"
    result = res.data["data"]
    assert result["row_count"] == 3
    g = result["global"]
    assert g["count"] == 3
    assert g["min"] == -5.0
    assert g["max"] == 3.0


@pytest.mark.skipif(not _HAS_PROBE_DEPS, reason="asteval/numpy not installed")
def test_data_diagnostics_group_by_side():
    store = _make_store()
    mod = DataDiagnosticsModule(store=store)
    res = mod.safe_run(
        field="dist_x", table="radar_objects", group_by="side",
        stats=["count"],
    )
    assert res.ok is True
    groups = res.data["data"]["groups"]
    # dist_y >= 0 → 'left' (2 rows: obj1@t1, obj1@t2); dist_y < 0 → 'right' (1)
    assert groups["left"]["count"] == 2
    assert groups["right"]["count"] == 1


@pytest.mark.skipif(not _HAS_PROBE_DEPS, reason="asteval/numpy not installed")
def test_data_diagnostics_stats_comma_string():
    store = _make_store()
    mod = DataDiagnosticsModule(store=store)
    # stats given as a comma string (CLI convenience) must be accepted.
    res = mod.safe_run(field="dist_x", stats="count,min")
    assert res.ok is True
    assert res.data["data"]["global"]["count"] == 3


def test_data_diagnostics_cli_wiring():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers()
    DataDiagnosticsModule.register_cli(sub)
    args = parser.parse_args(
        ["data-explore", "--field", "dist_x", "--stats", "count,min"],
    )
    assert args.field == "dist_x"
    assert args._module_cls is DataDiagnosticsModule
    mod = DataDiagnosticsModule.from_cli_args(args)
    assert isinstance(mod, DataDiagnosticsModule)
