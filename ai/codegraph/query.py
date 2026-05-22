# -*- coding: utf-8 -*-
"""
CodeGraph Query API.

Public class:
    CodeGraph(db_path) — open an existing CodeGraph DB for querying.

All methods return plain dicts/lists — no ORM, no magic. Designed to be
called from orchestrator probe/condition/expert_panel steps.
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger(__name__)


@dataclass
class NodeInfo:
    """Flattened node + metadata."""
    id: str
    type: str
    name: str
    display_name: Optional[str] = None
    file_path: Optional[str] = None
    file_id: Optional[str] = None
    start_line: Optional[int] = None
    end_line: Optional[int] = None
    return_type: Optional[str] = None
    params: Optional[str] = None
    is_static: bool = False
    scope: Optional[str] = None
    data_type: Optional[str] = None
    direction: Optional[str] = None
    rte_read_fn: Optional[str] = None
    rte_write_fn: Optional[str] = None
    value: Optional[float] = None
    unit: Optional[str] = None
    category: Optional[str] = None
    formula: Optional[str] = None
    state_name: Optional[str] = None
    keywords: Optional[str] = None
    side: Optional[str] = None
    semantic: Optional[str] = None


@dataclass
class EdgeInfo:
    """Flattened edge + metadata."""
    id: str
    source: str
    target: str
    type: str
    line: Optional[int] = None
    column: Optional[int] = None
    condition: Optional[str] = None
    pattern: Optional[str] = None
    rte_call: Optional[str] = None
    binding_method: Optional[str] = None
    macro_name: Optional[str] = None
    struct_name: Optional[str] = None
    field_name: Optional[str] = None


class CodeGraph:
    """
    Query interface for CodeGraph SQLite database.

    Usage:
        cg = CodeGraph("memory/codegraph.db")

        # Check if available
        if cg.is_available:
            functions = cg.get_functions_by_module("FCTB")
            callers = cg.get_callers("FctaFctbUpdateStatus")
            signals = cg.get_signals_used_by("FctbAlarmProcess")
    """

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.conn: Optional[sqlite3.Connection] = None
        if self.is_available:
            self._connect()

    @property
    def is_available(self) -> bool:
        """Check if the CodeGraph DB exists and is readable."""
        return self.db_path.exists()

    def _connect(self):
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.row_factory = sqlite3.Row

    def close(self):
        if self.conn:
            self.conn.close()
            self.conn = None

    # ── Stats / Health ──────────────────────────────────────────────────

    def get_stats(self) -> dict:
        """Return summary statistics."""
        if not self.conn:
            return {"available": False}

        nodes = self.conn.execute("SELECT type, COUNT(*) as c FROM nodes GROUP BY type").fetchall()
        edges = self.conn.execute("SELECT type, COUNT(*) as c FROM edges GROUP BY type").fetchall()

        builds = self.conn.execute(
            "SELECT COUNT(*) as total, MAX(build_time) as last FROM build_log"
        ).fetchone()

        return {
            "available": True,
            "db_path": str(self.db_path),
            "node_counts": {r["type"]: r["c"] for r in nodes},
            "edge_counts": {r["type"]: r["c"] for r in edges},
            "total_nodes": sum(r["c"] for r in nodes),
            "total_edges": sum(r["c"] for r in edges),
            "total_builds": builds["total"],
            "last_build": builds["last"],
        }

    # ── Node Queries ────────────────────────────────────────────────────

    def get_node(self, node_id: str) -> Optional[NodeInfo]:
        """Get a single node by ID."""
        row = self.conn.execute("SELECT * FROM nodes WHERE id=?", (node_id,)).fetchone()
        if not row:
            return None
        return self._row_to_node(row)

    def get_functions_by_file(self, file_path: str) -> list[NodeInfo]:
        """Get all functions defined in a file."""
        file_id = f"FILE:{file_path}"
        rows = self.conn.execute(
            "SELECT * FROM nodes WHERE type='FUNCTION' AND file_id=? ORDER BY start_line",
            (file_id,),
        ).fetchall()
        return [self._row_to_node(r) for r in rows]

    def get_functions_by_module(self, module: str) -> list[NodeInfo]:
        """Get all functions bound to an ADAS module (e.g. 'FCTB', 'BSD')."""
        mod_id = f"MODULE:{module}"
        rows = self.conn.execute(
            """SELECT n.* FROM nodes n
               JOIN edges e ON e.source = n.id
               WHERE n.type='FUNCTION' AND e.target=? AND e.type='BELONGS_TO'
               ORDER BY n.start_line""",
            (mod_id,),
        ).fetchall()
        return [self._row_to_node(r) for r in rows]

    def get_function_by_name(self, name: str) -> Optional[NodeInfo]:
        """Find a function by name."""
        node_id = f"FUNCTION:{name}"
        return self.get_node(node_id)

    def get_signals(self) -> list[NodeInfo]:
        """Get all SIGNAL nodes."""
        rows = self.conn.execute(
            "SELECT * FROM nodes WHERE type='SIGNAL' ORDER BY name"
        ).fetchall()
        return [self._row_to_node(r) for r in rows]

    def get_calibration_params(self, category: Optional[str] = None) -> list[NodeInfo]:
        """Get calibration parameter nodes."""
        if category:
            rows = self.conn.execute(
                "SELECT * FROM nodes WHERE type='CALIB_PARAM' AND category=? ORDER BY name",
                (category,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM nodes WHERE type='CALIB_PARAM' ORDER BY name"
            ).fetchall()
        return [self._row_to_node(r) for r in rows]

    def get_functions_in_range(self, start_line: int, end_line: int, file_path: Optional[str] = None) -> list[NodeInfo]:
        """Get functions that overlap with a line range."""
        if file_path:
            file_id = f"FILE:{file_path}"
            rows = self.conn.execute(
                """SELECT * FROM nodes
                   WHERE type='FUNCTION' AND file_id=?
                     AND start_line <= ? AND end_line >= ?
                   ORDER BY start_line""",
                (file_id, end_line, start_line),
            ).fetchall()
        else:
            rows = self.conn.execute(
                """SELECT * FROM nodes
                   WHERE type='FUNCTION'
                     AND start_line <= ? AND end_line >= ?
                   ORDER BY start_line""",
                (end_line, start_line),
            ).fetchall()
        return [self._row_to_node(r) for r in rows]

    # ── Edge / Relationship Queries ─────────────────────────────────────

    def get_callers(self, func_name: str) -> list[dict]:
        """Get functions that call the given function."""
        target = f"FUNCTION:{func_name}"
        rows = self.conn.execute(
            """SELECT e.*, n.name as caller_name, n.file_id, n.start_line, n.end_line
               FROM edges e
               JOIN nodes n ON n.id = e.source
               WHERE e.target=? AND e.type='CALLS'
               ORDER BY e.line""",
            (target,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_callees(self, func_name: str) -> list[dict]:
        """Get functions called by the given function."""
        source = f"FUNCTION:{func_name}"
        rows = self.conn.execute(
            """SELECT e.*, n.name as callee_name, n.file_id, n.start_line, n.end_line
               FROM edges e
               JOIN nodes n ON n.id = e.target
               WHERE e.source=? AND e.type='CALLS'
               ORDER BY e.line""",
            (source,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_call_chain(self, func_name: str, max_depth: int = 5) -> list[dict]:
        """Get the full call chain (recursive callers) up to max_depth."""
        # Use recursive CTE
        query = """
        WITH RECURSIVE chain(func_name, func_id, depth, path) AS (
            SELECT ?, f"FUNCTION:?", 0, ?
            UNION ALL
            SELECT n.name, e.source, c.depth + 1, c.path || ' -> ' || n.name
            FROM chain c
            JOIN edges e ON e.target = c.func_id AND e.type = 'CALLS'
            JOIN nodes n ON n.id = e.source
            WHERE c.depth < ?
        )
        SELECT * FROM chain WHERE depth > 0
        """
        target = f"FUNCTION:{func_name}"
        rows = self.conn.execute(query, (func_name, func_name, func_name, max_depth)).fetchall()
        return [dict(r) for r in rows]

    def get_variables_read_by(self, func_name: str) -> list[dict]:
        """Get variables read by a function."""
        source = f"FUNCTION:{func_name}"
        rows = self.conn.execute(
            """SELECT e.*, n.name as var_name, n.data_type, n.scope
               FROM edges e
               JOIN nodes n ON n.id = e.target
               WHERE e.source=? AND e.type='READS_VAR'
               ORDER BY e.line""",
            (source,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_variables_written_by(self, func_name: str) -> list[dict]:
        """Get variables written by a function."""
        source = f"FUNCTION:{func_name}"
        rows = self.conn.execute(
            """SELECT e.*, n.name as var_name, n.data_type, n.scope
               FROM edges e
               JOIN nodes n ON n.id = e.target
               WHERE e.source=? AND e.type='WRITES_VAR'
               ORDER BY e.line""",
            (source,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_functions_reading_var(self, var_name: str) -> list[dict]:
        """Reverse lookup: which functions read this variable?"""
        target = f"VARIABLE:{var_name}"
        rows = self.conn.execute(
            """SELECT e.*, n.name as func_name, n.file_id, n.start_line, n.end_line
               FROM edges e
               JOIN nodes n ON n.id = e.source
               WHERE e.target=? AND e.type='READS_VAR'
               ORDER BY e.line""",
            (target,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_functions_writing_var(self, var_name: str) -> list[dict]:
        """Reverse lookup: which functions write this variable?"""
        target = f"VARIABLE:{var_name}"
        rows = self.conn.execute(
            """SELECT e.*, n.name as func_name, n.file_id, n.start_line, n.end_line
               FROM edges e
               JOIN nodes n ON n.id = e.source
               WHERE e.target=? AND e.type='WRITES_VAR'
               ORDER BY e.line""",
            (target,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_signals_used_by(self, func_name: str) -> list[dict]:
        """Get signals read/written by a function."""
        source = f"FUNCTION:{func_name}"
        rows = self.conn.execute(
            """SELECT e.*, n.name as signal_name, n.direction, n.rte_read_fn, n.rte_write_fn
               FROM edges e
               JOIN nodes n ON n.id = e.target
               WHERE e.source=? AND e.type IN ('READS_SIGNAL', 'WRITES_SIGNAL')
               ORDER BY e.line""",
            (source,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_functions_using_signal(self, signal_name: str) -> list[dict]:
        """Reverse lookup: which functions use this signal?"""
        target = f"SIGNAL:{signal_name}"
        rows = self.conn.execute(
            """SELECT e.*, n.name as func_name, n.file_id, n.start_line, n.end_line
               FROM edges e
               JOIN nodes n ON n.id = e.source
               WHERE e.target=? AND e.type IN ('READS_SIGNAL', 'WRITES_SIGNAL')
               ORDER BY e.line""",
            (target,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_shared_functions(self, module_a: str, module_b: str) -> list[NodeInfo]:
        """Find functions shared between two ADAS modules."""
        mod_a = f"MODULE:{module_a}"
        mod_b = f"MODULE:{module_b}"
        rows = self.conn.execute(
            """SELECT DISTINCT n.* FROM nodes n
               WHERE n.type='FUNCTION'
                 AND n.id IN (SELECT source FROM edges WHERE target=? AND type='BELONGS_TO')
                 AND n.id IN (SELECT source FROM edges WHERE target=? AND type='BELONGS_TO')
               ORDER BY n.name""",
            (mod_a, mod_b),
        ).fetchall()
        return [self._row_to_node(r) for r in rows]

    def get_shared_signals(self, module_a: str, module_b: str) -> list[NodeInfo]:
        """Find signals shared between two ADAS modules."""
        mod_a = f"MODULE:{module_a}"
        mod_b = f"MODULE:{module_b}"

        # Find all function IDs for each module
        funcs_a = self.conn.execute(
            "SELECT source FROM edges WHERE target=? AND type='BELONGS_TO'", (mod_a,)
        ).fetchall()
        funcs_b = self.conn.execute(
            "SELECT source FROM edges WHERE target=? AND type='BELONGS_TO'", (mod_b,)
        ).fetchall()

        func_ids_a = {r["source"] for r in funcs_a}
        func_ids_b = {r["source"] for r in funcs_b}
        shared_funcs = func_ids_a & func_ids_b

        if not shared_funcs:
            return []

        # Find signals used by shared functions
        placeholders = ",".join("?" * len(shared_funcs))
        rows = self.conn.execute(
            f"""SELECT DISTINCT n.* FROM nodes n
               WHERE n.type='SIGNAL'
                 AND n.id IN (
                   SELECT target FROM edges
                   WHERE source IN ({placeholders})
                     AND type IN ('READS_SIGNAL', 'WRITES_SIGNAL')
                 )
               ORDER BY n.name""",
            list(shared_funcs),
        ).fetchall()
        return [self._row_to_node(r) for r in rows]

    def get_state_transitions(self, func_name: str) -> list[dict]:
        """Get state machine transitions made by a function."""
        source = f"FUNCTION:{func_name}"
        rows = self.conn.execute(
            """SELECT e.*, n.name as state_name
               FROM edges e
               JOIN nodes n ON n.id = e.target
               WHERE e.source=? AND e.type='TRANSITION'
               ORDER BY e.line""",
            (source,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_patterns_for(self, func_name: str) -> list[dict]:
        """Get behaviour patterns detected in a function."""
        source = f"FUNCTION:{func_name}"
        rows = self.conn.execute(
            """SELECT * FROM edges
               WHERE source=? AND pattern IS NOT NULL AND pattern != ''
               ORDER BY line""",
            (source,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Semantic Queries ────────────────────────────────────────────────

    def get_semantics(self, node_id: str, focus: Optional[str] = None) -> list[dict]:
        """Get LLM-learned semantics for a node."""
        if focus:
            rows = self.conn.execute(
                "SELECT * FROM node_semantics WHERE node_id=? AND focus=?",
                (node_id, focus),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM node_semantics WHERE node_id=?",
                (node_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_semantics_for_module(self, module: str, focus: Optional[str] = None) -> list[dict]:
        """Get semantics for all nodes in a module."""
        mod_id = f"MODULE:{module}"
        func_rows = self.conn.execute(
            "SELECT source FROM edges WHERE target=? AND type='BELONGS_TO'", (mod_id,)
        ).fetchall()
        func_ids = [r["source"] for r in func_rows]

        results = []
        for fid in func_ids:
            results.extend(self.get_semantics(fid, focus))
        return results

    # ── Natural Language Query (keyword-based) ──────────────────────────

    def search(self, keyword: str) -> dict:
        """
        Search across nodes and edges by keyword.

        Returns: {functions: [], signals: [], variables: [], files: [], calib_params: []}
        """
        like = f"%{keyword}%"
        result = {}

        for node_type in ("FUNCTION", "SIGNAL", "VARIABLE", "FILE", "CALIB_PARAM", "MODULE"):
            rows = self.conn.execute(
                "SELECT * FROM nodes WHERE type=? AND (name LIKE ? OR display_name LIKE ?)",
                (node_type, like, like),
            ).fetchall()
            key = node_type.lower() + "s"
            if key.endswith("es"):
                key = key  # functions -> functions
            result[key] = [self._row_to_node(r).name for r in rows]

        return result

    def find_related(self, entity: str) -> dict:
        """
        Find all entities related to a given entity (function name, signal name, variable name).

        Returns: {
            entity_id: str,
            entity_type: str,
            callers: [...],
            callees: [...],
            reads_vars: [...],
            writes_vars: [...],
            reads_signals: [...],
            writes_signals: [...],
            module: str,
            patterns: [...],
        }
        """
        result = {
            "entity": entity,
            "callers": [],
            "callees": [],
            "reads_vars": [],
            "writes_vars": [],
            "reads_signals": [],
            "writes_signals": [],
            "module": None,
            "patterns": [],
        }

        # Try to find the entity as a function first
        func_id = f"FUNCTION:{entity}"
        node = self.get_node(func_id)

        if not node:
            # Try as signal
            sig_id = f"SIGNAL:{entity}"
            node = self.get_node(sig_id)

        if not node:
            # Try as variable
            var_id = f"VARIABLE:{entity}"
            node = self.get_node(var_id)

        if not node:
            return result

        result["entity_id"] = node.id
        result["entity_type"] = node.type
        result["entity_name"] = node.name

        if node.type == "FUNCTION":
            result["callers"] = [r["caller_name"] for r in self.get_callers(entity)]
            result["callees"] = [r["callee_name"] for r in self.get_callees(entity)]
            result["reads_vars"] = [r["var_name"] for r in self.get_variables_read_by(entity)]
            result["writes_vars"] = [r["var_name"] for r in self.get_variables_written_by(entity)]
            sigs = self.get_signals_used_by(entity)
            result["reads_signals"] = [r["signal_name"] for r in sigs if r["type"] == "READS_SIGNAL"]
            result["writes_signals"] = [r["signal_name"] for r in sigs if r["type"] == "WRITES_SIGNAL"]
            result["patterns"] = self.get_patterns_for(entity)

            # Module
            mod_rows = self.conn.execute(
                """SELECT n.name FROM nodes n
                   JOIN edges e ON e.target = n.id
                   WHERE e.source=? AND e.type='BELONGS_TO'""",
                (func_id,),
            ).fetchall()
            if mod_rows:
                result["module"] = mod_rows[0]["name"]

        elif node.type == "SIGNAL":
            funcs = self.get_functions_using_signal(entity)
            result["read_by"] = [r["func_name"] for r in funcs if r["type"] == "READS_SIGNAL"]
            result["written_by"] = [r["func_name"] for r in funcs if r["type"] == "WRITES_SIGNAL"]

        elif node.type == "VARIABLE":
            result["read_by"] = [r["func_name"] for r in self.get_functions_reading_var(entity)]
            result["written_by"] = [r["func_name"] for r in self.get_functions_writing_var(entity)]

        return result

    # ── Internal Helpers ────────────────────────────────────────────────

    @staticmethod
    def _row_to_node(row: sqlite3.Row) -> NodeInfo:
        d = dict(row)
        return NodeInfo(
            id=d["id"],
            type=d["type"],
            name=d["name"],
            display_name=d.get("display_name"),
            file_path=d.get("file_path"),
            file_id=d.get("file_id"),
            start_line=d.get("start_line"),
            end_line=d.get("end_line"),
            return_type=d.get("return_type"),
            params=d.get("params"),
            is_static=bool(d.get("is_static", 0)),
            scope=d.get("scope"),
            data_type=d.get("data_type"),
            direction=d.get("direction"),
            rte_read_fn=d.get("rte_read_fn"),
            rte_write_fn=d.get("rte_write_fn"),
            value=d.get("value"),
            unit=d.get("unit"),
            category=d.get("category"),
            formula=d.get("formula"),
            state_name=d.get("state_name"),
            keywords=d.get("keywords"),
            side=d.get("side"),
            semantic=d.get("semantic"),
        )
