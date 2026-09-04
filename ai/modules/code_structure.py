# -*- coding: utf-8 -*-
"""
CodeStructureModule (M1) — query code structure with **no recorded data**.

This is the "no data" code assistant: it answers questions about functions,
call graphs, signal usage and calibration parameters purely from the CodeGraph
SQLite knowledge base (built offline by :mod:`ai.codegraph`). It never touches
``.bag`` / ``.blf`` recordings.

Run standalone::

    python cli.py code-query --query-type stats --db-path memory/codegraph.db
    python cli.py code-query --query-type signal_users --signal FCTA_Warn \\
        --db-path memory/codegraph.db

or from Python::

    from ai.modules.code_structure import CodeStructureModule
    mod = CodeStructureModule(db_path="memory/codegraph.db")
    res = mod.safe_run(query_type="callers", name="FctbAlarmProcess")
"""
from __future__ import annotations

import dataclasses
import logging
from pathlib import Path
from typing import Any

from .base import BaseModule, ModuleResult

log = logging.getLogger(__name__)

#: Supported ``query_type`` values (also used as CLI ``--query-type`` choices).
QUERY_TYPES: tuple[str, ...] = (
    "stats",
    "function",
    "callers",
    "callees",
    "call_chain",
    "signal_users",
    "signals_of",
    "vars_read",
    "vars_written",
    "calib",
)

#: Query types that require a function ``name`` argument.
_NEEDS_NAME = frozenset({
    "function", "callers", "callees", "call_chain",
    "signals_of", "vars_read", "vars_written",
})


def _to_jsonable(obj: Any) -> Any:
    """Normalise CodeGraph return values into JSON-friendly structures.

    ``NodeInfo`` (a dataclass) becomes a plain dict; lists/tuples are mapped
    element-wise; dicts and scalars pass through unchanged.
    """
    if obj is None:
        return None
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return dataclasses.asdict(obj)
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(x) for x in obj]
    return obj


class CodeStructureModule(BaseModule):
    """M1 — code structure Q&A backed by a read-only CodeGraph DB."""

    name = "code-query"
    description = "Query code structure without data (M1)"
    # Legacy CLI/AgentLoop compatibility. Pi uses the source-index-aware
    # ``code-analyze`` capability as the single code-query entry point.
    expose_to_pi = False

    def __init__(
        self,
        codegraph: Any | None = None,
        db_path: str | Path | None = None,
    ) -> None:
        """
        Args:
            codegraph: an already-opened ``CodeGraph`` (or a compatible stub).
                Takes precedence over ``db_path``.
            db_path: path to an existing CodeGraph SQLite DB, opened lazily on
                first use. If neither is supplied, :meth:`run` fails cleanly.
        """
        self._graph = codegraph
        self._db_path = Path(db_path) if db_path else None

    # ── graph acquisition ──────────────────────────────────────────────

    def _get_graph(self) -> Any | None:
        """Return a usable CodeGraph, lazily opening it from ``db_path``.

        Returns ``None`` when neither an injected graph nor a readable DB is
        available. The heavy import lives here so the module file imports even
        when optional deps are missing.
        """
        if self._graph is not None:
            return self._graph
        if self._db_path is None:
            return None
        try:
            from ..codegraph.query import CodeGraph
        except Exception:  # noqa: BLE001 - optional dependency guard
            log.exception("CodeGraph import failed")
            return None
        graph = CodeGraph(self._db_path)
        if not getattr(graph, "is_available", True):
            return None
        self._graph = graph
        return graph

    # ── execution ──────────────────────────────────────────────────────

    def run(
        self,
        *,
        query_type: str,
        name: str = "",
        signal: str = "",
        max_depth: int = 5,
        **_: Any,
    ) -> ModuleResult:
        """Dispatch a single code-structure query.

        Args:
            query_type: one of :data:`QUERY_TYPES`.
            name: function name (or calibration category for ``calib``).
            signal: signal name (required for ``signal_users``).
            max_depth: recursion depth for ``call_chain``.
        """
        if query_type not in QUERY_TYPES:
            return ModuleResult.fail(
                f"unknown query_type {query_type!r}; "
                f"choose one of {list(QUERY_TYPES)}",
                module=self.name,
            )

        graph = self._get_graph()
        if graph is None:
            return ModuleResult.fail(
                "no CodeGraph available; pass codegraph=... or "
                "db_path=<existing DB>",
                module=self.name,
            )

        if query_type in _NEEDS_NAME and not name:
            return ModuleResult.fail(
                f"query_type {query_type!r} requires 'name'", module=self.name,
            )
        if query_type == "signal_users" and not signal:
            return ModuleResult.fail(
                "query_type 'signal_users' requires 'signal'", module=self.name,
            )

        payload = self._dispatch(graph, query_type, name, signal, max_depth)
        return ModuleResult.success(
            message=f"code-query:{query_type}",
            module=self.name,
            data=_to_jsonable(payload),
        )

    @staticmethod
    def _dispatch(
        graph: Any, query_type: str, name: str, signal: str, max_depth: int,
    ) -> Any:
        """Map a validated ``query_type`` to the matching CodeGraph method."""
        if query_type == "stats":
            return graph.get_stats()
        if query_type == "function":
            return graph.get_function_by_name(name)
        if query_type == "callers":
            return graph.get_callers(name)
        if query_type == "callees":
            return graph.get_callees(name)
        if query_type == "call_chain":
            return graph.get_call_chain(name, max_depth)
        if query_type == "signal_users":
            return graph.get_functions_using_signal(signal)
        if query_type == "signals_of":
            return graph.get_signals_used_by(name)
        if query_type == "vars_read":
            return graph.get_variables_read_by(name)
        if query_type == "vars_written":
            return graph.get_variables_written_by(name)
        if query_type == "calib":
            return graph.get_calibration_params(name or None)
        raise ValueError(query_type)  # unreachable — validated in run()

    # ── CLI ────────────────────────────────────────────────────────────

    @classmethod
    def register_cli(cls, subparsers: Any) -> Any:
        parser = super().register_cli(subparsers)
        parser.add_argument(
            "--query-type", required=True, choices=list(QUERY_TYPES),
            help="Kind of code-structure query to run.",
        )
        parser.add_argument(
            "--name", default="",
            help="Function name (or calibration category for --query-type calib).",
        )
        parser.add_argument(
            "--signal", default="",
            help="Signal name for --query-type signal_users.",
        )
        parser.add_argument(
            "--max-depth", type=int, default=5,
            help="Max recursion depth for --query-type call_chain.",
        )
        parser.add_argument(
            "--db-path", default=None,
            help="Path to an existing CodeGraph SQLite DB.",
        )
        return parser

    @classmethod
    def from_cli_args(cls, args: Any) -> "CodeStructureModule":
        return cls(db_path=getattr(args, "db_path", None))
