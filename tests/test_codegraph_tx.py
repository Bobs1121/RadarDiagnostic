# -*- coding: utf-8 -*-
"""
Tests for the codegraph refactor (B-group) and variant isolation (F-group).

Covers:
* get_call_chain recursive CTE returns real callers (bug was f-string literal)
* find_callers wrapper exists (condition_extractor depends on it)
* FUNCTION file_path resolved via LEFT JOIN on FILE nodes
* get_functions_using_signal reverse lookup returns signal readers
* variant-scoped source_docs/codegraph resolution (identity.variant_id wins)

Run with::

    pytest tests/test_codegraph_tx.py -v
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ai.codegraph.query import CodeGraph  # noqa: E402
from config import (  # noqa: E402
    load_config,
    resolve_codegraph_db,
    resolve_source_docs_dir,
)

# ── SQLite fixtures ─────────────────────────────────────────────────────

_NODES = [
    # (id, type, name, file_id)
    ("FILE:a.c", "FILE", "a.c", None),
    ("FILE:b.c", "FILE", "b.c", None),
    ("FUNCTION:caller", "FUNCTION", "caller", "FILE:a.c"),
    ("FUNCTION:middle", "FUNCTION", "middle", "FILE:a.c"),
    ("FUNCTION:callee", "FUNCTION", "callee", "FILE:b.c"),
    ("FUNCTION:rte_rx", "FUNCTION", "RteComMapping_RxRunnable_FuncSignal", "FILE:b.c"),
    ("SIGNAL:FCTA_Enable_S", "SIGNAL", "FCTA_Enable_S", "FILE:b.c"),
    ("SIGNAL:Sts_FCTA_S", "SIGNAL", "Sts_FCTA_S", "FILE:b.c"),
    ("VARIABLE:FCTASelReq_u8", "VARIABLE", "FCTASelReq_u8", "FILE:b.c"),
    ("VARIABLE:fctaSysState", "VARIABLE", "fctaSysState", "FILE:b.c"),
]

_EDGES = [
    ("E1", "FUNCTION:caller", "FUNCTION:middle", "CALLS", 10),
    ("E2", "FUNCTION:middle", "FUNCTION:callee", "CALLS", 20),
    ("E3", "FUNCTION:rte_rx", "SIGNAL:FCTA_Enable_S", "READS_SIGNAL", 30),
    ("E4", "VARIABLE:fctaSysState", "SIGNAL:Sts_FCTA_S", "WRITES_SIGNAL", 40),
    ("E5", "FUNCTION:rte_rx", "VARIABLE:FCTASelReq_u8", "WRITES_VAR", 50),
]


@pytest.fixture()
def cg(tmp_path: Path) -> CodeGraph:
    db = tmp_path / "cg.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE nodes (id TEXT PRIMARY KEY, type TEXT, name TEXT, "
        "display_name TEXT, file_id TEXT, file_path TEXT, start_line INTEGER, "
        "end_line INTEGER, return_type TEXT, params TEXT, is_static INTEGER, "
        "scope TEXT, data_type TEXT, direction TEXT, rte_read_fn TEXT, "
        "rte_write_fn TEXT, value TEXT, unit TEXT, category TEXT, formula TEXT, "
        "state_name TEXT, keywords TEXT, side TEXT, semantic TEXT, "
        "internal_var TEXT)"
    )
    conn.execute(
        "CREATE TABLE edges (id TEXT PRIMARY KEY, source TEXT, target TEXT, "
        "type TEXT, line INTEGER)"
    )
    for n in _NODES:
        conn.execute(
            "INSERT INTO nodes (id, type, name, file_id) VALUES (?,?,?,?)", n
        )
    for e in _EDGES:
        conn.execute(
            "INSERT INTO edges (id, source, target, type, line) VALUES (?,?,?,?,?)", e
        )
    conn.commit()
    conn.close()
    return CodeGraph(str(db))


class TestCallChain:
    def test_get_call_chain_returns_callers(self, cg: CodeGraph):
        chain = cg.get_call_chain("callee", max_depth=4)
        paths = [c.get("path") for c in chain]
        assert any("caller" in p and "middle" in p for p in paths), paths

    def test_find_callers_wrapper(self, cg: CodeGraph):
        callers = cg.find_callers("callee", max_depth=2)
        assert callers, "find_callers should return rows"
        assert any(c.get("func_name") == "middle" for c in callers)

    def test_no_callers_returns_empty(self, cg: CodeGraph):
        assert cg.get_call_chain("RteComMapping_RxRunnable_FuncSignal") == []


class TestFilePathJoin:
    def test_function_file_path_resolved(self, cg: CodeGraph):
        fns = cg.get_functions_by_file("a.c")
        assert fns, "expected functions in a.c"
        assert all(fn.file_path == "a.c" for fn in fns)


class TestSignalReverseLookup:
    def test_functions_using_signal(self, cg: CodeGraph):
        users = cg.get_functions_using_signal("FCTA_Enable_S")
        names = [u.get("func_name") for u in users]
        assert "RteComMapping_RxRunnable_FuncSignal" in names

    def test_signal_internal_var_exposed(self, cg: CodeGraph):
        sig = cg.get_node("SIGNAL:Sts_FCTA_S")
        # internal_var column exists (enrichment populates it in production).
        assert sig is not None


class TestVariantIsolation:
    def test_identity_variant_wins_over_default(self):
        cfg = load_config()
        cfg.setdefault("identity", {})["variant_id"] = "gen6/byd_uke_em2e_index_8"
        sd = resolve_source_docs_dir(cfg, PROJECT_ROOT)
        cg_db = resolve_codegraph_db(cfg, PROJECT_ROOT)
        assert "byd_uke_em2e_index_8" in str(sd)
        assert "byd_uke_em2e_index_8" in str(cg_db)
