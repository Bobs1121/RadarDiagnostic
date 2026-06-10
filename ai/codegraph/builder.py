# -*- coding: utf-8 -*-
"""
CodeGraph Builder — orchestrates the analysis phases and persists results to SQLite.

Public API:
    builder = CodeGraphBuilder(db_path, source_root, key_files, func_keywords)
    result = builder.build()  # returns BuildResult

The builder is designed to be called silently from orchestrator Step 1.
If the DB doesn't exist, it does a full build. If it exists, it does incremental.
"""
from __future__ import annotations

import logging
import os
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from . import analyzer
from .schema import INIT_SQL, SCHEMA_VERSION

try:
    from .ast_builder import ASTBuilder
    AST_AVAILABLE = True
except ImportError:
    AST_AVAILABLE = False
    ASTBuilder = None  # type: ignore

log = logging.getLogger(__name__)


@dataclass
class BuildResult:
    """Summary of a build run."""
    build_type: str = "incremental"  # full | incremental | skip
    files_scanned: int = 0
    files_changed: int = 0
    nodes_added: int = 0
    edges_added: int = 0
    nodes_removed: int = 0
    edges_removed: int = 0
    duration_sec: float = 0.0
    success: bool = True
    error: str = ""


class CodeGraphBuilder:
    """
    Incremental builder for CodeGraph SQLite database.

    Usage:
        builder = CodeGraphBuilder(
            db_path="memory/codegraph.db",
            source_root=Path("D:/cr60_light"),
            key_files=[...],            # from config.yaml key_source_files
            func_keywords={...},        # from ai.utils FUNC_KEYWORDS
            calib_files=[...],          # from config.yaml calib_source_files
        )
        result = builder.build()
    """

    def __init__(
        self,
        db_path: str | Path,
        source_root: str | Path,
        key_files: list[str],
        func_keywords: dict[str, list[str]],
        calib_files: Optional[list[str]] = None,
        use_ast: bool = False,
        source_docs_dir: Optional[Path] = None,
    ):
        self.db_path = Path(db_path)
        self.source_root = Path(source_root)
        self.key_files = key_files
        self.func_keywords = func_keywords
        self.calib_files = calib_files or []
        self.use_ast = use_ast and AST_AVAILABLE
        self.source_docs_dir = source_docs_dir
        self.conn: Optional[sqlite3.Connection] = None
        self._ast_results_by_file: dict = {}

        if self.use_ast and not AST_AVAILABLE:
            log.warning("CodeGraph: use_ast=True but tree-sitter not installed; falling back to regex")
            self.use_ast = False

    # ── Public API ──────────────────────────────────────────────────────

    def build(self) -> BuildResult:
        """Run the build. Full if new DB, incremental if existing."""
        start = time.time()
        result = BuildResult(duration_sec=0.0)

        try:
            self._connect()
            self._ensure_schema()

            # Phase 1: File Index — compute hashes
            file_infos = analyzer.phase1_file_index(self.source_root, self.key_files + self.calib_files)
            result.files_scanned = len(file_infos)

            # Determine changed files
            changed = self._find_changed_files(file_infos)
            result.files_changed = len(changed)

            if not changed:
                result.build_type = "skip"
                result.duration_sec = time.time() - start
                log.info("CodeGraph: no files changed, skipping build (%.1fs)", result.duration_sec)
                self._log_build(result)
                return result

            # Collect all function names for cross-reference
            if self.use_ast:
                all_functions, known_func_names = self._ast_extract_all(file_infos)
            else:
                all_functions = self._extract_all_functions(file_infos)
                known_func_names = set()
                for _, fns in all_functions:
                    known_func_names.update(f["name"] for f in fns)

            # Clear old data for changed files
            changed_files = [f["file_path"] for f in changed]
            removed = self._purge_changed(changed_files)
            result.nodes_removed += removed.get("nodes", 0)
            result.edges_removed += removed.get("edges", 0)

            # Build new data for all files (not just changed — we need cross-references)
            self._insert_file_nodes(file_infos)

            # Phase 2: Functions
            func_count = self._insert_function_nodes(all_functions)
            result.nodes_added += func_count

            # Phase 9: Calibration params (only for calib files)
            self._insert_calibration_params(file_infos)
            result.nodes_added += len([f for f in file_infos if f["file_path"] in [c for c in self.calib_files]])

            # Phase 3: Call Graph
            calls = self._extract_all_calls(all_functions, known_func_names)
            edge_count = self._insert_call_edges(calls)
            result.edges_added += edge_count

            # Phase 4: Variable Access
            var_accesses = self._extract_all_var_accesses(all_functions)
            edge_count = self._insert_var_edges(var_accesses)
            result.edges_added += edge_count

            # Phase 5: Signal Interface
            signals = self._extract_all_signals(all_functions)
            edge_count = self._insert_signal_edges(signals)
            result.edges_added += edge_count

            # Phase 6: State Machine
            states = self._extract_all_states(all_functions)
            self._insert_state_edges(states)
            result.edges_added += len(states)

            # Phase 7: Module Binding
            if self.use_ast and hasattr(self, '_ast_results_by_file'):
                # AST mode: use extracted bindings
                all_bindings = []
                for ar in self._ast_results_by_file.values():
                    for b in ar.bindings:
                        all_bindings.append(b)
                edge_count = self._insert_module_binding_edges(all_bindings)
            else:
                all_func_list = []
                for fi, fns in all_functions:
                    for f in fns:
                        f["file_path"] = fi["file_path"]
                    all_func_list.extend(fns)
                bindings = analyzer.phase7_module_binding(all_func_list, self.func_keywords)
                edge_count = self._insert_module_binding_edges(bindings)
            result.edges_added += edge_count

            # Phase 10: Behaviour Patterns (label edges)
            self._insert_behaviour_patterns(all_functions)

            # Phase 11: Signal Enrichment — backfill DBC/variable mapping
            self._enrich_signal_nodes()

            # Update file hashes
            self._update_file_hashes(file_infos)

            result.build_type = "incremental" if self._schema_version_exists() else "full"
            result.duration_sec = time.time() - start
            result.success = True

            log.info(
                "CodeGraph build: type=%s files=%d changed=%d nodes+%d -%d edges+%d -%d %.1fs",
                result.build_type, result.files_scanned, result.files_changed,
                result.nodes_added, result.nodes_removed,
                result.edges_added, result.edges_removed,
                result.duration_sec,
            )

        except Exception as e:
            result.success = False
            result.error = str(e)
            result.duration_sec = time.time() - start
            log.error("CodeGraph build failed: %s", e, exc_info=True)

        self._log_build(result)
        self._close()
        return result

    # ── Internal: DB Management ─────────────────────────────────────────

    def _connect(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.row_factory = sqlite3.Row

    def _close(self):
        if self.conn:
            self.conn.close()
            self.conn = None

    def _ensure_schema(self):
        self.conn.executescript(INIT_SQL)
        # Check version
        row = self.conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
        if not row:
            self.conn.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
        elif row["version"] < SCHEMA_VERSION:
            # For now, just rebuild (migrate later if needed)
            log.info("CodeGraph: schema upgrade needed (%d -> %d), will rebuild", row["version"], SCHEMA_VERSION)
            self._drop_all()
            self.conn.executescript(INIT_SQL)
            self.conn.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))

    def _schema_version_exists(self) -> bool:
        row = self.conn.execute("SELECT 1 FROM schema_version LIMIT 1").fetchone()
        return row is not None

    def _drop_all(self):
        """Drop all tables for schema migration."""
        self.conn.execute("PRAGMA foreign_keys=OFF")
        tables = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        for t in tables:
            self.conn.execute(f"DROP TABLE IF EXISTS {t['name']}")
        self.conn.execute("PRAGMA foreign_keys=ON")

    def _log_build(self, result: BuildResult):
        self.conn.execute(
            """INSERT INTO build_log
               (build_type, files_scanned, files_changed, nodes_added, edges_added,
                nodes_removed, edges_removed, duration_sec, summary)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                result.build_type, result.files_scanned, result.files_changed,
                result.nodes_added, result.edges_added,
                result.nodes_removed, result.edges_removed,
                result.duration_sec,
                result.error or f"OK ({result.build_type})",
            ),
        )
        self.conn.commit()

    # ── Internal: Change Detection ──────────────────────────────────────

    def _find_changed_files(self, file_infos: list[dict]) -> list[dict]:
        """Compare current hashes against stored hashes. Return changed files."""
        current_hashes = {fi["file_path"]: fi["hash"] for fi in file_infos if fi["exists"]}

        stored = {}
        rows = self.conn.execute("SELECT file_path, hash FROM file_hashes").fetchall()
        for r in rows:
            stored[r["file_path"]] = r["hash"]

        changed = []
        for fi in file_infos:
            fp = fi["file_path"]
            if not fi["exists"]:
                # File was deleted
                if fp in stored:
                    changed.append(fi)
                continue

            old_hash = stored.get(fp)
            if old_hash is None or old_hash != fi["hash"]:
                changed.append(fi)

        return changed

    # ── Internal: Extract & Insert ──────────────────────────────────────

    def _ast_extract_all(self, file_infos: list[dict]) -> tuple[list[tuple], set[str]]:
        """AST-based extraction using ASTBuilder. Returns (all_functions, known_func_names).
        
        Replaces phases 2-7, 9 with tree-sitter AST traversal.
        Phases 4 (variable access on known vars) and 10 (behaviour patterns) still
        use analyzer.py because they depend on known_variable sets and regex patterns.
        """
        ast_builder = ASTBuilder(
            func_keywords=self.func_keywords,
        )
        
        # Build all files through AST
        files_to_build = [
            (Path(fi["full_path"]), fi["file_path"])
            for fi in file_infos
            if fi["exists"]
        ]
        ast_results = ast_builder.build_files(files_to_build)
        
        # Convert to (file_info, [function_dicts]) format matching _insert_function_nodes
        all_functions = []
        known_func_names = set()
        
        # Create a lookup for file_infos
        fi_map = {fi["file_path"]: fi for fi in file_infos}
        
        for ar in ast_results:
            fi = fi_map.get(ar.file_path)
            if not fi:
                continue
            
            funcs = ar.functions
            known_func_names.update(f["name"] for f in funcs)
            all_functions.append((fi, funcs))
        
        # Store AST results on self so other methods can access them
        self._ast_results_by_file = {ar.file_path: ar for ar in ast_results}
        
        log.info("CodeGraph AST: extracted %d functions across %d files",
                 len(known_func_names), len(ast_results))
        
        return all_functions, known_func_names

    def _extract_all_functions(self, file_infos: list[dict]) -> list[tuple]:
        """Return list of (file_info, [function_dicts])."""
        results = []
        for fi in file_infos:
            if not fi["exists"]:
                results.append((fi, []))
                continue
            full_path = fi["full_path"]
            rel_path = fi["file_path"]
            fns = analyzer.phase2_extract_functions(full_path, rel_path)
            results.append((fi, fns))
        return results

    def _insert_file_nodes(self, file_infos: list[dict]):
        """Insert FILE nodes."""
        for fi in file_infos:
            if not fi["exists"]:
                continue
            node_id = f"FILE:{fi['file_path']}"
            self.conn.execute(
                """INSERT OR REPLACE INTO nodes (id, type, name, file_path, source_hash)
                   VALUES (?, 'FILE', ?, ?, ?)""",
                (node_id, fi["file_path"], fi["file_path"], fi["hash"]),
            )
        self.conn.commit()

    def _insert_function_nodes(self, all_functions: list[tuple]) -> int:
        """Insert FUNCTION nodes and FILE_INcludes edges. Returns count."""
        count = 0
        for fi, fns in all_functions:
            if not fi["exists"]:
                continue
            file_id = f"FILE:{fi['file_path']}"
            for fn in fns:
                node_id = f"FUNCTION:{fn['name']}"
                self.conn.execute(
                    """INSERT OR REPLACE INTO nodes
                       (id, type, name, file_id, start_line, end_line,
                        return_type, params, is_static, source_hash)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (
                        node_id, "FUNCTION", fn["name"], file_id,
                        fn["start_line"], fn["end_line"],
                        fn["return_type"], fn["params"], fn["is_static"],
                        fi["hash"],
                    ),
                )
                count += 1

                # FILE includes FUNCTION edge
                edge_id = f"{file_id}->{node_id}:FILE_INcludes:0"
                self.conn.execute(
                    """INSERT OR REPLACE INTO edges (id, source, target, type, line)
                       VALUES (?,?,?,?,?)""",
                    (edge_id, file_id, node_id, "FILE_INcludes", fn["start_line"]),
                )

        self.conn.commit()
        return count

    def _extract_all_calls(self, all_functions: list[tuple], known_funcs: set[str]) -> list[dict]:
        # AST mode: use stored AST results directly
        if self.use_ast and hasattr(self, '_ast_results_by_file'):
            calls = []
            for ar in self._ast_results_by_file.values():
                # Filter to known functions only
                for c in ar.calls:
                    if c["callee"] in known_funcs:
                        calls.append(c)
            return calls
        
        # Regex mode: use analyzer
        calls = []
        for fi, fns in all_functions:
            if not fi["exists"]:
                continue
            file_calls = analyzer.phase3_call_graph(fi["full_path"], fns, known_funcs)
            calls.extend(file_calls)
        return calls

    def _insert_call_edges(self, calls: list[dict]) -> int:
        count = 0
        for c in calls:
            source = f"FUNCTION:{c['caller']}"
            target = f"FUNCTION:{c['callee']}"
            edge_id = f"{source}->{target}:CALLS:{c['line']}"
            self.conn.execute(
                """INSERT OR REPLACE INTO edges (id, source, target, type, line)
                   VALUES (?,?,?,?,?)""",
                (edge_id, source, target, "CALLS", c["line"]),
            )
            count += 1
        self.conn.commit()
        return count

    def _extract_all_var_accesses(self, all_functions: list[tuple]) -> list[dict]:
        """Extract variable accesses for known variables.

        Collect variable candidates from:
        1. SIGNAL nodes (already extracted in phase 5)
        2. Global variables from globalVarDefine.h
        3. Common variable naming patterns (fXXX, bXXX, nXXX)
        """
        # Collect known variables from existing VARIABLE nodes
        existing_vars = set()
        try:
            rows = self.conn.execute(
                "SELECT name FROM nodes WHERE type='VARIABLE'"
            ).fetchall()
            existing_vars = {r["name"] for r in rows}
        except Exception:
            pass

        # Also collect variables matching common ADAS naming patterns
        # f = float, b = bool, n = int, FGap = Front Gap, etc.
        import re as _re
        VAR_PATTERN = _re.compile(r"\b([fbn]\w+|b[A-Z]\w+|F[A-Z]\w+|R[A-Z]\w+)\b")

        all_accesses = []
        for fi, fns in all_functions:
            if not fi["exists"]:
                continue
            # Build candidate set from file content
            try:
                text = fi["full_path"].read_text(encoding="utf-8", errors="replace")
                candidates = VAR_PATTERN.findall(text)
                # Deduplicate and filter keywords
                candidates = {c for c in candidates if c.isidentifier() and not c.startswith("_")}
            except (OSError, PermissionError):
                candidates = existing_vars

            # Merge with existing known vars
            known = existing_vars | candidates
            accesses = analyzer.phase4_variable_access(fi["full_path"], fns, known)
            all_accesses.extend(accesses)

        return all_accesses

    def _insert_var_edges(self, accesses: list[dict]) -> int:
        count = 0
        for a in accesses:
            func_id = f"FUNCTION:{a['function']}"
            var_id = f"VARIABLE:{a['var_name']}"
            edge_type = "WRITES_VAR" if a["access_type"] == "write" else "READS_VAR"
            edge_id = f"{func_id}->{var_id}:{edge_type}:{a['line']}"

            # Ensure FUNCTION node exists
            func_exists = self.conn.execute(
                "SELECT 1 FROM nodes WHERE id=?", (func_id,)
            ).fetchone()
            if not func_exists:
                continue  # skip if function wasn't extracted (not in our codebase)

            # Create VARIABLE node if needed
            self.conn.execute(
                """INSERT OR IGNORE INTO nodes (id, type, name)
                   VALUES (?, 'VARIABLE', ?)""",
                (var_id, a["var_name"]),
            )

            self.conn.execute(
                """INSERT OR REPLACE INTO edges (id, source, target, type, line)
                   VALUES (?,?,?,?,?)""",
                (edge_id, func_id, var_id, edge_type, a["line"]),
            )
            count += 1
        self.conn.commit()
        return count

    def _extract_all_signals(self, all_functions: list[tuple]) -> list[dict]:
        # AST mode: use stored results
        if self.use_ast and hasattr(self, '_ast_results_by_file'):
            signals = []
            for ar in self._ast_results_by_file.values():
                for s in ar.signals:
                    signals.append(s)
            return signals
        
        # Regex mode
        signals = []
        for fi, fns in all_functions:
            if not fi["exists"]:
                continue
            file_signals = analyzer.phase5_signal_interface(fi["full_path"], fns)
            signals.extend(file_signals)
        return signals

    def _insert_signal_edges(self, signals: list[dict]) -> int:
        count = 0
        seen = set()
        for s in signals:
            func_name = s.get("function")
            if func_name:
                func_id = f"FUNCTION:{func_name}"
                # Verify function node exists; skip if not
                existing = self.conn.execute(
                    "SELECT 1 FROM nodes WHERE id = ?", (func_id,)
                ).fetchone()
                if not existing:
                    continue
            else:
                # Header file signal declarations: use FILE node as source
                func_id = None  # handled below

            sig_key = f"{s.get('signal_module', '')}_{s['signal_name']}" if s.get('signal_module') else s['signal_name']
            sig_id = f"SIGNAL:{sig_key}"

            # Create SIGNAL node with data-variable mapping fields
            rte_fn = s.get("rte_call", "")
            self.conn.execute(
                """INSERT OR IGNORE INTO nodes
                   (id, type, name, direction, can_name, can_id,
                    dbc_name, dbc_id, dbc_signal_name, internal_var,
                    rte_port_id, rte_read_fn, rte_write_fn)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (sig_id, "SIGNAL", sig_key, s.get("access_type"),
                 s.get("can_name"), s.get("can_id"),
                 s.get("dbc_name"), s.get("dbc_id"), s.get("dbc_signal_name"),
                 s.get("internal_var"), s.get("rte_port_id"),
                 s.get("rte_read_fn"), s.get("rte_write_fn")),
            )

            if func_id:
                edge_type = "READS_SIGNAL" if s["access_type"] == "read" else "WRITES_SIGNAL"
                edge_id = f"{func_id}->{sig_id}:{edge_type}:{s['line']}"

                if edge_id not in seen:
                    self.conn.execute(
                        """INSERT OR REPLACE INTO edges (id, source, target, type, line, rte_call)
                           VALUES (?,?,?,?,?,?)""",
                        (edge_id, func_id, sig_id, edge_type, s["line"], s.get("rte_call", "")),
                    )
                    seen.add(edge_id)
                    count += 1

        self.conn.commit()
        return count

    def _extract_all_states(self, all_functions: list[tuple]) -> list[dict]:
        # AST mode: use stored results
        if self.use_ast and hasattr(self, '_ast_results_by_file'):
            states = []
            for ar in self._ast_results_by_file.values():
                for s in ar.states:
                    states.append(s)
            return states
        
        # Regex mode
        states = []
        for fi, fns in all_functions:
            if not fi["exists"]:
                continue
            file_states = analyzer.phase6_state_machine(fi["full_path"], fns)
            states.extend(file_states)
        return states

    def _insert_state_edges(self, states: list[dict]):
        for s in states:
            func_id = f"FUNCTION:{s['function']}"
            state_id = f"STATE:{s['state_value']}"

            # Create STATE node
            self.conn.execute(
                """INSERT OR IGNORE INTO nodes (id, type, name, state_name)
                   VALUES (?,?,?,?)""",
                (state_id, "STATE", s["state_value"], s["state_value"]),
            )

            # TRANSITION edge
            edge_id = f"{func_id}->{state_id}:TRANSITION:{s['line']}"
            self.conn.execute(
                """INSERT OR REPLACE INTO edges (id, source, target, type, line)
                   VALUES (?,?,?,?,?)""",
                (edge_id, func_id, state_id, "TRANSITION", s["line"]),
            )
        self.conn.commit()

    def _insert_module_binding_edges(self, bindings: list[dict]) -> int:
        count = 0
        for b in bindings:
            func_id = f"FUNCTION:{b['function']}"
            mod_id = f"MODULE:{b['module']}"

            # Create MODULE node
            self.conn.execute(
                """INSERT OR IGNORE INTO nodes (id, type, name)
                   VALUES (?, 'MODULE', ?)""",
                (mod_id, b["module"]),
            )

            edge_id = f"{func_id}->{mod_id}:BELONGS_TO:0"
            self.conn.execute(
                """INSERT OR REPLACE INTO edges (id, source, target, type, binding_method)
                   VALUES (?,?,?,?,?)""",
                (edge_id, func_id, mod_id, "BELONGS_TO", b["binding_method"]),
            )
            count += 1
        self.conn.commit()
        return count

    def _insert_calibration_params(self, file_infos: list[dict]):
        """Extract and insert calibration parameters from header files."""
        # AST mode: use stored results
        if self.use_ast and hasattr(self, '_ast_results_by_file'):
            calib_paths = [normalize_path(c) for c in self.calib_files]
            for fi in file_infos:
                fp = fi["file_path"]
                if not fi["exists"] or fp not in calib_paths:
                    continue
                ar = self._ast_results_by_file.get(fp)
                if not ar:
                    continue
                for p in ar.calibration_params:
                    node_id = f"CALIB_PARAM:{p['name']}"
                    self.conn.execute(
                        """INSERT OR REPLACE INTO nodes
                           (id, type, name, value, line, defined_in, source_hash)
                           VALUES (?,?,?,?,?,?,?)""",
                        (node_id, "CALIB_PARAM", p["name"], p["value"],
                         p["line"], p["source_file"], fi["hash"]),
                    )
            self.conn.commit()
            return
        
        # Regex mode
        calib_paths = [normalize_path(c) for c in self.calib_files]
        for fi in file_infos:
            if not fi["exists"] or fi["file_path"] not in calib_paths:
                continue
            params = analyzer.phase9_calibration_params(fi["full_path"], fi["file_path"])
            for p in params:
                node_id = f"CALIB_PARAM:{p['name']}"
                self.conn.execute(
                    """INSERT OR REPLACE INTO nodes
                       (id, type, name, value, line, defined_in, source_hash)
                       VALUES (?,?,?,?,?,?,?)""",
                    (node_id, "CALIB_PARAM", p["name"], p["value"],
                     p["line"], p["source_file"], fi["hash"]),
                )
        self.conn.commit()

    def _insert_behaviour_patterns(self, all_functions: list[tuple]):
        """Detect and label behaviour patterns on edges."""
        for fi, fns in all_functions:
            if not fi["exists"]:
                continue
            patterns = analyzer.phase10_behaviour_patterns(fi["full_path"], fns)
            for p in patterns:
                func_id = f"FUNCTION:{p['function']}"
                var_id = f"VARIABLE:{p['var_name']}"
                # Label the READS_VAR/WRITES_VAR edge with the pattern
                edge_id = f"{func_id}->{var_id}:READS_VAR:{p['line']}"
                self.conn.execute(
                    """UPDATE edges SET pattern=?
                       WHERE id=?""",
                    (p["pattern_type"], edge_id),
                )
                # If no read edge, try write
                if self.conn.total_changes == 0:
                    edge_id_w = f"{func_id}->{var_id}:WRITES_VAR:{p['line']}"
                    self.conn.execute(
                        """UPDATE edges SET pattern=?
                           WHERE id=?""",
                        (p["pattern_type"], edge_id_w),
                    )
        self.conn.commit()

    def _enrich_signal_nodes(self):
        """Phase 11: Enrich SIGNAL nodes with DBC/variable mapping from signal_mapping.json."""
        if not self.source_docs_dir:
            return
        mapping_path = self.source_docs_dir / "signal_mapping.json"
        if not mapping_path.exists():
            return
        try:
            import json as _json
            mapping_data = _json.loads(mapping_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return

        # Build lookup: CAN signal name -> {internal_var, can_name, can_id, ...}
        mappings = mapping_data.get("mappings", [])
        can_to_var: dict[str, str] = {}
        can_to_info: dict[str, dict] = {}
        for m in mappings:
            can_sig = m.get("can_signal", "")
            int_var = m.get("internal_var", "")
            if can_sig and int_var:
                can_to_var[can_sig.lower()] = int_var
                can_to_info[can_sig.lower()] = m

        # Update existing SIGNAL nodes
        rows = self.conn.execute(
            "SELECT id, name FROM nodes WHERE type='SIGNAL'"
        ).fetchall()

        updated = 0
        for row in rows:
            sig_id = row["id"]
            sig_name = row["name"] or ""
            # Try to match by signal name (case-insensitive)
            info = can_to_info.get(sig_name.lower())
            if not info:
                # Try matching on signal_name part (after module prefix)
                for k, v in can_to_info.items():
                    if k in sig_name.lower() or sig_name.lower() in k:
                        info = v
                        break

            if info:
                int_var = info.get("internal_var", "")
                dbc_name = info.get("dbc_file", "")
                dbc_signal = info.get("dbc_signal_name", sig_name)
                can_name = info.get("can_name", sig_name)
                can_id = info.get("can_id", "")
                rte_port = info.get("rte_port_id", "")
                rte_read = info.get("rte_read_fn", "")
                rte_write = info.get("rte_write_fn", "")
                self.conn.execute(
                    """UPDATE nodes SET internal_var=COALESCE(NULLIF(?, ''), internal_var),
                       can_name=COALESCE(NULLIF(?, ''), can_name),
                       can_id=COALESCE(NULLIF(?, ''), can_id),
                       dbc_name=COALESCE(NULLIF(?, ''), dbc_name),
                       dbc_signal_name=COALESCE(NULLIF(?, ''), dbc_signal_name),
                       rte_port_id=COALESCE(NULLIF(?, ''), rte_port_id),
                       rte_read_fn=COALESCE(NULLIF(?, ''), rte_read_fn),
                       rte_write_fn=COALESCE(NULLIF(?, ''), rte_write_fn)
                       WHERE id=?""",
                    (int_var, can_name, can_id, dbc_name, dbc_signal,
                     rte_port, rte_read, rte_write, sig_id),
                )
                updated += 1

        self.conn.commit()
        if updated:
            log.info("CodeGraph: enriched %d SIGNAL nodes with data-variable mapping", updated)

    # ── Internal: Purge Changed ─────────────────────────────────────────

    def _purge_changed(self, changed_files: list[str]) -> dict:
        """Remove nodes and edges for changed files. Returns {nodes, edges} counts."""
        if not changed_files:
            return {"nodes": 0, "edges": 0}

        # Find FILE nodes for changed files
        file_ids = [f"FILE:{fp}" for fp in changed_files]
        placeholders = ",".join("?" * len(file_ids))

        # Count edges to remove
        edge_count = self.conn.execute(
            f"SELECT COUNT(*) FROM edges WHERE source IN ({placeholders}) OR target IN ({placeholders})",
            file_ids + file_ids,
        ).fetchone()[0]

        # Count function nodes (children of these files)
        func_rows = self.conn.execute(
            f"SELECT id FROM nodes WHERE type='FUNCTION' AND file_id IN ({placeholders})",
            file_ids,
        ).fetchall()
        func_ids = [r["id"] for r in func_rows]

        # Also find all nodes that belong to these files (signals, vars defined in them)
        all_node_ids = list(file_ids) + func_ids

        # Edges involving these nodes
        if all_node_ids:
            all_placeholders = ",".join("?" * len(all_node_ids))
            edge_count = self.conn.execute(
                f"SELECT COUNT(*) FROM edges WHERE source IN ({all_placeholders}) OR target IN ({all_placeholders})",
                all_node_ids + all_node_ids,
            ).fetchone()[0]

            # Remove edges
            self.conn.execute(
                f"DELETE FROM edges WHERE source IN ({all_placeholders}) OR target IN ({all_placeholders})",
                all_node_ids + all_node_ids,
            )

            # Remove nodes
            node_count = self.conn.execute(
                f"DELETE FROM nodes WHERE id IN ({all_placeholders})",
                all_node_ids,
            ).rowcount
        else:
            node_count = 0

        self.conn.commit()
        return {"nodes": node_count, "edges": edge_count}

    def _update_file_hashes(self, file_infos: list[dict]):
        """Update file_hashes table with current hashes."""
        for fi in file_infos:
            if not fi["exists"]:
                continue
            self.conn.execute(
                """INSERT OR REPLACE INTO file_hashes (file_path, hash, line_count, analyzed_at)
                   VALUES (?,?,?,datetime('now'))""",
                (fi["file_path"], fi["hash"], fi["line_count"]),
            )
        self.conn.commit()


def normalize_path(p: str) -> str:
    """Convert backslashes to forward slashes for consistent storage."""
    return p.replace("\\", "/")
