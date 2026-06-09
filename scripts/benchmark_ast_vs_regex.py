#!/usr/bin/env python3
"""
AST vs Regex comparison script.

Runs CodeGraph builder twice on D:/cr60_light (GWM_B26):
  1. use_ast=False (regex mode)  -> codegraph_regex.db
  2. use_ast=True  (AST mode)    -> codegraph_ast.db

Compares node/edge counts and prints a summary table.

Usage:
    python scripts/benchmark_ast_vs_regex.py
"""
import sys
import os
from pathlib import Path

# Ensure project root is on path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import yaml

# Import modules directly without triggering ai/__init__.py (which requires openai)
def _load_module(name: str, path: Path):
    """Load a .py module without triggering __init__.py."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod

# Pre-register 'ai' and 'ai.codegraph' as namespace packages so relative imports work
import types
import importlib.machinery
import importlib.util as iu

# Create 'ai' as a package (with __path__ so subpackages are found)
_ai_pkg = types.ModuleType("ai")
_ai_pkg.__path__ = [str(ROOT / "ai")]
_ai_pkg.__file__ = str(ROOT / "ai" / "__init__.py")  # won't execute it
sys.modules["ai"] = _ai_pkg

# Create 'ai.codegraph' as a subpackage
_cg_pkg = types.ModuleType("ai.codegraph")
_cg_pkg.__path__ = [str(ROOT / "ai" / "codegraph")]
_cg_pkg.__file__ = str(ROOT / "ai" / "codegraph" / "__init__.py")
sys.modules["ai.codegraph"] = _cg_pkg

# Now we can safely load builder (relative imports will resolve)
_builder_mod = _load_module("ai.codegraph.builder", ROOT / "ai" / "codegraph" / "builder.py")
CodeGraphBuilder = _builder_mod.CodeGraphBuilder

# Load FUNC_KEYWORDS — inlined to avoid importing code_learner (which requires model_router -> openai)
FUNC_KEYWORDS = {
    "BSD":  ["bsd", "Bsd", "BSD", "bLeftBsd", "bRightBsd", "bsdSystemState", "BSD_LCA_warning"],
    "LCA":  ["lca", "Lca", "LCA", "bLeftLca", "bRightLca", "lcaSystemState"],
    "DOW":  ["dow", "Dow", "DOW", "bLeftDow", "bRightDow", "dowSystemState", "DOW_warning"],
    "RCW":  ["rcw", "Rcw", "RCW", "bRcw", "rcwSystemState", "RSDS_RCW"],
    "RCTA": ["rcta", "Rcta", "RCTA", "bLeftRcta", "bRightRcta", "rctaSystemState", "RCTA_warning"],
    "RCTB": ["rctb", "Rctb", "RCTB", "rctbSystemState", "RctbBrake",
             "RSDS_Brkg", "RSDS_RCTABrk", "RCTB_FUNC_GAP"],
    "FCTA": ["fcta", "Fcta", "FCTA", "bLeftFcta", "bRightFcta", "fctaSystemState", "FCTA_Warn"],
    "FCTB": ["fctb", "Fctb", "FCTB", "fctbSystemState", "FctbBrake", "FctbKeepBrake",
             "CR_BrkgReq", "FCTB_FUNC_GAP", "FctbDetect"],
}


def load_config():
    cfg_path = ROOT / "config.yaml"
    with open(cfg_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def run_build(db_path: str, use_ast: bool) -> dict:
    cfg = load_config()
    source_root = cfg["paths"]["source_code"]
    key_files = cfg["paths"]["key_source_files"]
    
    # Build result summary
    builder = CodeGraphBuilder(
        db_path=db_path,
        source_root=source_root,
        key_files=key_files,
        func_keywords=FUNC_KEYWORDS,
        use_ast=use_ast,
    )
    result = builder.build()
    
    # Query DB for detailed stats
    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    
    stats = {}
    # Node counts by type
    rows = conn.execute(
        "SELECT type, COUNT(*) as cnt FROM nodes GROUP BY type ORDER BY cnt DESC"
    ).fetchall()
    stats["nodes_by_type"] = {r["type"]: r["cnt"] for r in rows}
    stats["total_nodes"] = sum(stats["nodes_by_type"].values())
    
    # Edge counts by type
    rows = conn.execute(
        "SELECT type, COUNT(*) as cnt FROM edges GROUP BY type ORDER BY cnt DESC"
    ).fetchall()
    stats["edges_by_type"] = {r["type"]: r["cnt"] for r in rows}
    stats["total_edges"] = sum(stats["edges_by_type"].values())
    
    # Build metadata
    stats["build_type"] = result.build_type
    stats["files_scanned"] = result.files_scanned
    stats["files_changed"] = result.files_changed
    stats["duration"] = round(result.duration_sec, 2)
    stats["success"] = result.success
    stats["error"] = result.error
    
    conn.close()
    return stats


def print_comparison(regex_stats: dict, ast_stats: dict):
    print("=" * 78)
    print("  AST vs Regex — CodeGraph Build Comparison")
    print("=" * 78)
    
    # Build summary
    print(f"\n{'Metric':<30} {'Regex':>12} {'AST':>12} {'Delta':>12}")
    print("-" * 78)
    
    print(f"{'Build duration (s)':<30} {regex_stats['duration']:>12.1f} {ast_stats['duration']:>12.1f} {ast_stats['duration']-regex_stats['duration']:>+12.1f}")
    print(f"{'Files scanned':<30} {regex_stats['files_scanned']:>12} {ast_stats['files_scanned']:>12}")
    print(f"{'Total nodes':<30} {regex_stats['total_nodes']:>12} {ast_stats['total_nodes']:>12} {ast_stats['total_nodes']-regex_stats['total_nodes']:>+12}")
    print(f"{'Total edges':<30} {regex_stats['total_edges']:>12} {ast_stats['total_edges']:>12} {ast_stats['total_edges']-regex_stats['total_edges']:>+12}")
    
    # Node type comparison
    print(f"\n{'Node Type':<30} {'Regex':>12} {'AST':>12} {'Delta':>12}")
    print("-" * 78)
    all_node_types = set(list(regex_stats["nodes_by_type"].keys()) + list(ast_stats["nodes_by_type"].keys()))
    for nt in sorted(all_node_types):
        r = regex_stats["nodes_by_type"].get(nt, 0)
        a = ast_stats["nodes_by_type"].get(nt, 0)
        d = a - r
        marker = " <<" if d > 0 and d > r * 0.1 else (">>" if d < 0 and d < -r * 0.1 else "")
        print(f"{nt:<30} {r:>12} {a:>12} {d:>+12}{marker}")
    
    # Edge type comparison
    print(f"\n{'Edge Type':<30} {'Regex':>12} {'AST':>12} {'Delta':>12}")
    print("-" * 78)
    all_edge_types = set(list(regex_stats["edges_by_type"].keys()) + list(ast_stats["edges_by_type"].keys()))
    for et in sorted(all_edge_types):
        r = regex_stats["edges_by_type"].get(et, 0)
        a = ast_stats["edges_by_type"].get(et, 0)
        d = a - r
        marker = " <<" if d > 0 and d > r * 0.1 else (">>" if d < 0 and d < -r * 0.1 else "")
        print(f"{et:<30} {r:>12} {a:>12} {d:>+12}{marker}")
    
    # Signal details
    print("\n" + "=" * 78)
    print("  Signal Analysis")
    print("=" * 78)
    
    import sqlite3
    for mode_name, db_path in [("Regex", str(ROOT / "scripts" / "codegraph_regex.db")),
                                ("AST", str(ROOT / "scripts" / "codegraph_ast.db"))]:
        if not Path(db_path).exists():
            continue
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        
        # Signal count
        sig_count = conn.execute("SELECT COUNT(*) as c FROM nodes WHERE type='SIGNAL'").fetchone()["c"]
        print(f"\n  [{mode_name}] SIGNAL nodes: {sig_count}")
        
        # READS_SIGNAL edges
        reads = conn.execute("SELECT COUNT(*) as c FROM edges WHERE type='READS_SIGNAL'").fetchone()["c"]
        writes = conn.execute("SELECT COUNT(*) as c FROM edges WHERE type='WRITES_SIGNAL'").fetchone()["c"]
        print(f"    READS_SIGNAL edges: {reads}, WRITES_SIGNAL edges: {writes}")
        
        # Sample signals
        print(f"    Sample signals:")
        sigs = conn.execute("SELECT name FROM nodes WHERE type='SIGNAL' ORDER BY name LIMIT 10").fetchall()
        for s in sigs:
            print(f"      - {s['name']}")
        
        # State count
        state_count = conn.execute("SELECT COUNT(*) as c FROM nodes WHERE type='STATE'").fetchone()["c"]
        transition_count = conn.execute("SELECT COUNT(*) as c FROM edges WHERE type='TRANSITION'").fetchone()["c"]
        print(f"    STATE nodes: {state_count}, TRANSITION edges: {transition_count}")
        
        # Variable count
        var_count = conn.execute("SELECT COUNT(*) as c FROM nodes WHERE type='VARIABLE'").fetchone()["c"]
        var_reads = conn.execute("SELECT COUNT(*) as c FROM edges WHERE type='READS_VAR'").fetchone()["c"]
        var_writes = conn.execute("SELECT COUNT(*) as c FROM edges WHERE type='WRITES_VAR'").fetchone()["c"]
        print(f"    VARIABLE nodes: {var_count}, READS_VAR: {var_reads}, WRITES_VAR: {var_writes}")
        
        conn.close()
    
    print("\n" + "=" * 78)
    print("  Comparison complete. DBs saved in scripts/ directory.")
    print("=" * 78)


def main():
    import shutil
    
    script_dir = ROOT / "scripts"
    regex_db = str(script_dir / "codegraph_regex.db")
    ast_db = str(script_dir / "codegraph_ast.db")
    
    # Clean old DBs
    for db in [regex_db, ast_db]:
        if os.path.exists(db):
            os.remove(db)
        if os.path.exists(db + "-wal"):
            os.remove(db + "-wal")
        if os.path.exists(db + "-shm"):
            os.remove(db + "-shm")
    
    print("Running Regex mode...")
    regex_stats = run_build(regex_db, use_ast=False)
    print(f"  Done. Nodes={regex_stats['total_nodes']}, Edges={regex_stats['total_edges']}, "
          f"Time={regex_stats['duration']}s")
    
    print("\nRunning AST mode...")
    ast_stats = run_build(ast_db, use_ast=True)
    print(f"  Done. Nodes={ast_stats['total_nodes']}, Edges={ast_stats['total_edges']}, "
          f"Time={ast_stats['duration']}s")
    
    print()
    print_comparison(regex_stats, ast_stats)


if __name__ == "__main__":
    main()
