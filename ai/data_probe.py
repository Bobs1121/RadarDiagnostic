# -*- coding: utf-8 -*-
"""
DataProbe — stateless data query executor for the radar analysis pipeline.

Design goal
-----------
This module has **zero business knowledge**. It answers the question:
"given a field (or an arithmetic expression over fields), group it by some
dimension, filter by another expression, and return a set of statistics
(min/max/p50/p90/count/...)". It does NOT know what ADAS functions are,
what BSD/LCA are, or which variables are "important". That knowledge lives
in ``VariableQueryPlanner``.

What it runs on
---------------
A :class:`parsers.frame_store.FrameStore` (a thin wrapper around SQLite).
The available source tables are:

  - ``radar_objects`` (per-frame per-object rows)
  - ``radar_debug``   (per-frame per-radar vehicle-state snapshot)
  - ``bag_frames``    (raw bag topics, structured in JSON)
  - ``can_frames``    (CAN decoded signals, JSON)
  - ``warning_events`` (precomputed edge events per function)

The ``table`` argument selects one of these.

Expression engine
-----------------
``field`` and ``filter`` support arithmetic expressions (``dist_y + 0.25 *
obj_width``, ``abs(dist_y) < 4.12``, etc.) using the ``asteval`` library for
safe evaluation — **no** Python ``eval``. Allowed names come from two
sources:

  1. Columns of the selected table.
  2. A small set of built-in **semantic fields**:
       - ``side``       → 'left' if dist_y >= 0 else 'right'
       - ``in_window``  → True if the row falls inside any provided test
                          window [t_start, t_end]

Group-by is applied after expression evaluation.

Returned shape (JSON-friendly)
------------------------------
::

    {
      "field": "<as given>",
      "table": "radar_objects",
      "row_count": 12345,
      "groups": {
        "<group_key>": {
          "count": 7000,
          "min":  -4.26,
          "max":   4.22,
          "mean":  0.03,
          "p10":  -4.15,
          "p50":   0.01,
          "p90":   4.08,
          "std":   2.15,
        },
        ...
      },
      "global": { ... same stats if no group_by ... },
    }

Typical usage
-------------
>>> probe = DataProbe(store, windows=[(t0_ns, t1_ns), ...])
>>> result = probe.query(
...     field="dist_y + 0.25 * obj_length",
...     table="radar_objects",
...     group_by="side",
...     filter="in_window and dist_x < 0",
...     stats=["min", "max", "p50", "p90", "count"],
... )
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field as dc_field
from typing import Any, Optional

try:
    from asteval import Interpreter
except ImportError:  # pragma: no cover
    Interpreter = None  # type: ignore

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None  # type: ignore


# ── Allowed stats & columns per table ──────────────────────────────────────

_SUPPORTED_STATS = {"count", "min", "max", "mean", "std", "p10", "p50", "p90"}

# Columns exposed per table (keep in sync with FrameStore schema).
# Extra computed columns are appended during query to support semantic fields.
TABLE_COLUMNS: dict[str, list[str]] = {
    "radar_objects": [
        "timestamp_ns", "timestamp_sec", "radar_id", "frame_id", "obj_id",
        "obj_class", "life_cycle",
        "dist_x", "dist_y", "vel_x", "vel_y",
        "vel_abs_x", "vel_abs_y",
        "ttc", "ddci",
        "bsd_flag", "lca_flag", "dow_flag", "rcw_flag",
        "rcta_flag", "rctb_flag", "fcta_flag", "fctb_flag",
        "source",
    ],
    "radar_debug": [
        "timestamp_ns", "timestamp_sec", "radar_id", "frame_id",
        "actual_spd", "yaw_rate", "lat_accel", "long_accel",
        "steer_angle", "actual_gear",
        "fl_whl_spd", "fr_whl_spd", "rl_whl_spd", "rr_whl_spd",
        "bsd_enable", "lca_enable", "dow_enable", "rcw_enable",
        "rcta_enable", "rctb_enable", "fcta_enable", "fctb_enable",
        "bld_warning_flag", "bld_percent", "bld_score",
    ],
    "warning_events": [
        "func_name", "direction", "radar_id",
        "start_ns", "end_ns", "duration_ms",
        "trigger_source", "associated_obj_id", "max_ttc", "min_dist",
    ],
}

# Each table carries its timestamp column under slightly different names.
TABLE_TS_COLUMN = {
    "radar_objects": "timestamp_ns",
    "radar_debug":   "timestamp_ns",
    "warning_events": "start_ns",
}

# Semantic fields are computed from base columns (applied row-wise in numpy).
# value: (required_columns, description)
SEMANTIC_FIELDS = {
    "side": (
        ["dist_y"],
        "'left' if dist_y >= 0 else 'right' — target on left/right of ego",
    ),
    "in_window": (
        [],  # uses probe.windows, not a column
        "True if the row's timestamp falls inside any provided test window",
    ),
    "is_stable_target": (
        ["life_cycle"],
        "life_cycle >= 5 — radar has tracked this object stably for several "
        "frames (filters out flickering ghost targets and short-lived clutter)",
    ),
}

# Threshold for ``is_stable_target``. Radar tracking typically stabilises in
# 3–5 frames; we pick 5 to bias towards *real* targets even if a handful of
# early frames of a real object are dropped.
_STABLE_TARGET_MIN_LIFE = 5


# ── Safe expression evaluation ────────────────────────────────────────────

class _SafeEvaluator:
    """Thin wrapper around asteval used for **vectorised** numpy evaluation.

    asteval already whitelists Python operations; we further restrict the
    symbol table to known columns + safe numpy helpers.
    """

    def __init__(self):
        if Interpreter is None:
            raise RuntimeError(
                "asteval is required for DataProbe. Run `pip install asteval`.",
            )
        if np is None:
            raise RuntimeError("numpy is required for DataProbe.")

        # asteval 1.0+ minimal mode: arithmetic, comparisons, boolean ops,
        # function calls on symtable entries. No imports / listcomps / assign.
        self.aeval = Interpreter(
            minimal=True,
            use_numpy=True,
            max_statement_length=500,
        )
        # Expose safe numpy functions for vectorised operations.
        # (np.abs handles negative arrays element-wise; the built-in ``abs``
        # on a numpy array also dispatches to ``np.abs``, so both work.)
        for fn in ("abs", "sqrt", "where", "clip", "minimum", "maximum",
                   "isfinite", "isnan", "log", "exp"):
            if hasattr(np, fn):
                self.aeval.symtable[fn] = getattr(np, fn)

    def eval(self, expr: str, columns: dict[str, "np.ndarray"]):
        """Evaluate ``expr`` with column arrays exposed as variables.

        Raises:
            ValueError: if the expression references unknown names or is
                syntactically invalid.
        """
        # Reset only error list; keep whitelisted numpy helpers in symtable.
        for k, v in columns.items():
            self.aeval.symtable[k] = v
        # Clear prior errors before evaluation so state doesn't leak across calls
        self.aeval.error = []
        result = self.aeval.eval(expr, show_errors=False)
        if self.aeval.error:
            msgs = "; ".join(str(getattr(e, "msg", "?")) for e in self.aeval.error)
            raise ValueError(f"Expression error in {expr!r}: {msgs}")
        return result


# ── The probe ────────────────────────────────────────────────────────────

@dataclass
class ProbeResult:
    """Structured result, trivially JSON-serialisable."""
    field: str
    table: str
    row_count: int
    group_by: Optional[str] = None
    filter: Optional[str] = None
    groups: dict[str, dict[str, float]] = dc_field(default_factory=dict)
    global_stats: dict[str, float] = dc_field(default_factory=dict)
    error: Optional[str] = None

    def to_dict(self) -> dict:
        out: dict[str, Any] = {
            "field": self.field,
            "table": self.table,
            "row_count": self.row_count,
        }
        if self.group_by:
            out["group_by"] = self.group_by
        if self.filter:
            out["filter"] = self.filter
        if self.groups:
            out["groups"] = self.groups
        if self.global_stats:
            out["global"] = self.global_stats
        if self.error:
            out["error"] = self.error
        return out


class DataProbe:
    """Execute a single query plan produced by the planner."""

    def __init__(self, store, windows: Optional[list] = None):
        """
        Args:
            store: a :class:`FrameStore` instance. Only ``store.conn`` is used.
            windows: optional list of (t_start_ns, t_end_ns) tuples — powers
                the ``in_window`` semantic field. Tuples may also be
                (start_sec, end_sec); heuristic detection below.
        """
        self.store = store
        self.windows_ns = self._normalise_windows(windows or [])
        self._evaluator = _SafeEvaluator()

    # ------------------------------------------------------------------

    @staticmethod
    def _normalise_windows(raw: list) -> list[tuple[int, int]]:
        """Accept windows given as (ns, ns) or (sec, sec); return ns."""
        out: list[tuple[int, int]] = []
        for item in raw:
            if item is None:
                continue
            # TestWindow dataclass instances expose t_start/t_end (sec)
            t_start = getattr(item, "t_start", None)
            t_end = getattr(item, "t_end", None)
            if t_start is None or t_end is None:
                # tuple/list
                try:
                    t_start, t_end = item[0], item[1]
                except (IndexError, TypeError):
                    continue
            t_start = float(t_start)
            t_end = float(t_end)
            # Heuristic: values > 1e12 are already ns; else seconds → ns
            if t_start < 1e12:
                t_start = int(t_start * 1e9)
                t_end = int(t_end * 1e9)
            out.append((int(t_start), int(t_end)))
        return out

    # ------------------------------------------------------------------

    def query(
        self,
        field: str,
        table: str = "radar_objects",
        group_by: Optional[str] = None,
        filter: Optional[str] = None,
        stats: Optional[list[str]] = None,
        max_rows: int = 500_000,
    ) -> dict:
        """Execute one probe query.

        Args:
            field: column name or arithmetic expression.
            table: one of ``radar_objects``, ``radar_debug``, ``warning_events``.
            group_by: column name or semantic field (``side``).
            filter: boolean expression; rows evaluating truthy are kept.
            stats: subset of ``{count,min,max,mean,std,p10,p50,p90}``;
                default ``[count,min,max,mean,p50,p90]``.
            max_rows: hard cap on rows pulled from SQL (safety fuse).

        Returns: a plain dict (see module docstring).
        """
        stats = [s for s in (stats or ["count", "min", "max", "mean", "p50", "p90"])
                 if s in _SUPPORTED_STATS]
        if table not in TABLE_COLUMNS:
            return ProbeResult(
                field=field, table=table, row_count=0,
                error=f"unsupported table {table!r}; allowed: {list(TABLE_COLUMNS)}",
            ).to_dict()

        # 1) Determine which columns we need from SQL
        expr_names = _collect_names(field) | _collect_names(filter or "")
        if group_by:
            expr_names |= _collect_names(group_by)

        # Drop semantic fields — they are computed, not loaded from SQL.
        base_needed = set()
        used_semantic = set()
        for name in expr_names:
            if name in SEMANTIC_FIELDS:
                used_semantic.add(name)
                base_needed |= set(SEMANTIC_FIELDS[name][0])
            elif name in TABLE_COLUMNS[table]:
                base_needed.add(name)
            # else: ignored here — asteval will raise when evaluating if unknown

        ts_col = TABLE_TS_COLUMN.get(table)
        if "in_window" in used_semantic and ts_col:
            base_needed.add(ts_col)

        if not base_needed:
            # Fallback: pull timestamp only so the evaluator has a row count
            base_needed = {ts_col or TABLE_COLUMNS[table][0]}

        # 2) Pull rows from SQLite (no aggregation yet — we need raw rows
        #    to evaluate expressions. Safe: we hard-cap max_rows.)
        col_list = sorted(base_needed)
        sql = f"SELECT {', '.join(col_list)} FROM {table} LIMIT {int(max_rows)}"
        cur: sqlite3.Cursor = self.store.conn.execute(sql)
        rows = cur.fetchall()
        if not rows:
            return ProbeResult(
                field=field, table=table, row_count=0,
                group_by=group_by, filter=filter,
            ).to_dict()

        # 3) Transpose to numpy column dict
        cols: dict[str, Any] = {}
        for i, cname in enumerate(col_list):
            raw_col = [r[i] for r in rows]
            try:
                cols[cname] = np.array(raw_col, dtype=float)
            except (TypeError, ValueError):
                cols[cname] = np.array(raw_col, dtype=object)

        # 4) Materialise semantic fields
        if "side" in used_semantic and "dist_y" in cols:
            # vectorised categorical: 'right' if dist_y < 0 else 'left'
            cols["side"] = np.where(cols["dist_y"] < 0, "right", "left")
        if "in_window" in used_semantic and ts_col:
            ts = cols[ts_col]
            in_win = np.zeros(len(ts), dtype=bool)
            for (t0, t1) in self.windows_ns:
                in_win |= (ts >= t0) & (ts <= t1)
            cols["in_window"] = in_win
        if "is_stable_target" in used_semantic and "life_cycle" in cols:
            cols["is_stable_target"] = cols["life_cycle"] >= _STABLE_TARGET_MIN_LIFE

        # 5) Apply filter
        if filter:
            # Auto-rewrite Python boolean ``and``/``or``/``not`` into numpy
            # element-wise operators. Python's short-circuit logic calls
            # ``bool(array)`` which raises on multi-element arrays. The planner
            # prompt can tell the LLM about this, but we silently fix common
            # cases too so correct-looking expressions don't error out.
            filter_expr = _rewrite_bool_ops(filter)
            try:
                mask = self._evaluator.eval(filter_expr, cols)
            except ValueError as e:
                return ProbeResult(
                    field=field, table=table, row_count=len(rows),
                    group_by=group_by, filter=filter,
                    error=str(e),
                ).to_dict()
            mask = np.asarray(mask, dtype=bool)
            if mask.shape != (len(rows),):
                mask = np.broadcast_to(mask, (len(rows),)).copy()
            cols = {k: v[mask] if hasattr(v, "__len__") and len(v) == len(rows) else v
                    for k, v in cols.items()}
            rows_after_filter = int(mask.sum())
        else:
            rows_after_filter = len(rows)

        if rows_after_filter == 0:
            return ProbeResult(
                field=field, table=table, row_count=0,
                group_by=group_by, filter=filter,
            ).to_dict()

        # 6) Evaluate main field expression
        try:
            values = self._evaluator.eval(field, cols)
        except ValueError as e:
            return ProbeResult(
                field=field, table=table, row_count=rows_after_filter,
                group_by=group_by, filter=filter,
                error=str(e),
            ).to_dict()
        values = np.asarray(values)
        if values.shape == ():  # scalar result → broadcast
            values = np.full(rows_after_filter, values.item())

        # Coerce to float where possible (ignore non-numeric gracefully)
        try:
            values = values.astype(float)
        except (TypeError, ValueError):
            return ProbeResult(
                field=field, table=table, row_count=rows_after_filter,
                group_by=group_by, filter=filter,
                error="field expression did not produce numeric output",
            ).to_dict()

        # 7) Group & aggregate
        result = ProbeResult(
            field=field, table=table, row_count=rows_after_filter,
            group_by=group_by, filter=filter,
        )
        if group_by:
            if group_by not in cols:
                return ProbeResult(
                    field=field, table=table, row_count=rows_after_filter,
                    group_by=group_by, filter=filter,
                    error=f"group_by {group_by!r} is not in loaded columns",
                ).to_dict()
            gcol = cols[group_by]
            unique_keys = np.unique(gcol)
            for key in unique_keys:
                mask = (gcol == key)
                sub = values[mask]
                sub = sub[np.isfinite(sub)]
                if sub.size == 0:
                    continue
                key_str = _coerce_key(key)
                result.groups[key_str] = _compute_stats(sub, stats)
        else:
            finite = values[np.isfinite(values)]
            if finite.size:
                result.global_stats = _compute_stats(finite, stats)

        return result.to_dict()


# ── Helpers ──────────────────────────────────────────────────────────────


def _compute_stats(arr, stats: list[str]) -> dict[str, float]:
    """Compute requested stats on a 1-D numeric numpy array."""
    out: dict[str, float] = {}
    if "count" in stats:
        out["count"] = int(arr.size)
    if "min" in stats:
        out["min"] = round(float(np.min(arr)), 4)
    if "max" in stats:
        out["max"] = round(float(np.max(arr)), 4)
    if "mean" in stats:
        out["mean"] = round(float(np.mean(arr)), 4)
    if "std" in stats:
        out["std"] = round(float(np.std(arr)), 4)
    for p_name, q in (("p10", 10), ("p50", 50), ("p90", 90)):
        if p_name in stats:
            out[p_name] = round(float(np.percentile(arr, q)), 4)
    return out


def _coerce_key(key) -> str:
    """Make a group-key JSON-safe (handles numpy scalars, bytes, etc.)."""
    if isinstance(key, (bytes, bytearray)):
        return key.decode("utf-8", "replace")
    if hasattr(key, "item"):
        key = key.item()
    if isinstance(key, float) and key.is_integer():
        key = int(key)
    return str(key)


def _rewrite_bool_ops(expr: str) -> str:
    """Rewrite ``a and b`` → ``(a) & (b)`` via proper AST manipulation.

    Why this is needed:
        Python's ``and``/``or``/``not`` are short-circuit and call
        ``bool(array)``, which raises on multi-element numpy arrays. The
        vectorised equivalents are ``&``/``|``/``~``. A naive regex replace
        breaks precedence (``&`` binds tighter than ``<``), so we use
        :mod:`ast` to rewrite the expression tree and ``ast.unparse`` to
        serialise it back — this naturally preserves parentheses.

    If parsing fails (asteval accepts a superset in some configs), we
    return the original expression untouched; the downstream evaluator
    will surface the error.
    """
    import ast as _ast
    try:
        tree = _ast.parse(expr, mode="eval")
    except SyntaxError:
        return expr

    class _BoolToBit(_ast.NodeTransformer):
        def visit_BoolOp(self, node):
            new_op = _ast.BitAnd() if isinstance(node.op, _ast.And) else _ast.BitOr()
            self.generic_visit(node)
            acc = node.values[0]
            for right in node.values[1:]:
                acc = _ast.BinOp(left=acc, op=new_op, right=right)
            return _ast.copy_location(acc, node)

        def visit_UnaryOp(self, node):
            self.generic_visit(node)
            if isinstance(node.op, _ast.Not):
                return _ast.copy_location(
                    _ast.UnaryOp(op=_ast.Invert(), operand=node.operand),
                    node,
                )
            return node

    new_tree = _BoolToBit().visit(tree)
    _ast.fix_missing_locations(new_tree)
    try:
        return _ast.unparse(new_tree)
    except AttributeError:  # pragma: no cover — Python < 3.9
        return expr


def _collect_names(expr: str) -> set[str]:
    """Very small tokenizer — extract identifiers from an expression.

    We're not trying to be a Python parser; the evaluator will do that.
    This is only used to decide which SQL columns to pull up-front.
    """
    import re as _re
    if not expr:
        return set()
    # Match Python identifiers, ignoring keywords / builtins handled elsewhere
    tokens = set(_re.findall(r"[A-Za-z_][A-Za-z0-9_]*", expr))
    _SKIP = {
        "and", "or", "not", "True", "False", "None",
        "if", "else", "in", "is",
        "abs", "min", "max", "sum", "len", "sqrt",
        "where", "clip", "minimum", "maximum",
        "isfinite", "isnan",
    }
    return tokens - _SKIP
