# -*- coding: utf-8 -*-
"""
DataDiagnosticsModule (M4) — probe & summarise recorded vehicle data with
**no code knowledge**.

This is the "no code" data explorer: it runs a single :class:`engines.data_probe.DataProbe`
query over a :class:`parsers.frame_store.FrameStore` (``radar_objects``,
``radar_debug``, ``warning_events`` …) and returns min/max/mean/percentile
statistics, optionally grouped and/or filtered. It knows nothing about the
source code or ADAS semantics.

Run standalone::

    python cli.py data-explore --field dist_x --table radar_objects \\
        --stats count,min,max --case-dir cases/FCTA001

or from Python (inject a prebuilt store)::

    from ai.modules.data_diagnostics import DataDiagnosticsModule
    res = DataDiagnosticsModule(store=store).safe_run(
        field="dist_y", table="radar_objects", stats=["p50", "p90"])
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from .base import BaseModule, ModuleResult

log = logging.getLogger(__name__)


class DataDiagnosticsModule(BaseModule):
    """M4 — stateless data probe over a :class:`FrameStore`."""

    name = "data-explore"
    description = "Probe & summarize vehicle data without code (M4)"

    def __init__(self, store: Any | None = None) -> None:
        """
        Args:
            store: an already-built ``FrameStore``. Injectable for tests and
                orchestrator composition. When ``None``, :meth:`run` fails
                cleanly with ``"no data store loaded"``.
        """
        self._store = store

    # ── factory ────────────────────────────────────────────────────────

    @classmethod
    def from_case(
        cls,
        case_dir: str | Path,
        *,
        config: Optional[dict] = None,
        project_root: Optional[Path] = None,
        on_status: Any = None,
    ) -> "DataDiagnosticsModule":
        """Build a module by loading a case directory into a ``FrameStore``.

        Heavy parsing dependencies are imported lazily; on any failure
        (missing deps, unreadable case, parse error) a module with *no* store
        is returned so :meth:`run` degrades to a clean failure instead of
        raising at import/construction time.
        """
        try:
            case_dir = Path(case_dir)
            if project_root is None:
                # repo root == two levels up from ai/modules/data_diagnostics.py
                project_root = Path(__file__).resolve().parents[2]
            if config is None:
                from config import load_config
                config = load_config()
            from parsers.case_loader import load_case_data
            result = load_case_data(
                case_dir, config, project_root, on_status=on_status,
            )
            return cls(store=result.store)
        except Exception:  # noqa: BLE001 - optional dependency / IO guard
            log.exception(
                "from_case failed for %s; returning storeless module", case_dir,
            )
            return cls(store=None)

    # ── execution ──────────────────────────────────────────────────────

    def run(
        self,
        *,
        field: str,
        table: str = "radar_objects",
        group_by: Optional[str] = None,
        filter: Optional[str] = None,  # noqa: A002 - mirrors DataProbe.query API
        stats: Optional[list[str]] = None,
        **_: Any,
    ) -> ModuleResult:
        """Run one probe query and package the result.

        Args:
            field: column name or arithmetic expression to summarise.
            table: source table (``radar_objects``, ``radar_debug``,
                ``warning_events``).
            group_by: column or semantic field to group by (e.g. ``side``).
            filter: boolean expression; only truthy rows are kept.
            stats: subset of ``{count,min,max,mean,std,p10,p50,p90}``. A
                comma-separated string is also accepted (CLI convenience).
        """
        if self._store is None:
            return ModuleResult.fail("no data store loaded", module=self.name)

        if isinstance(stats, str):
            stats = [s.strip() for s in stats.split(",") if s.strip()]

        try:
            from engines.data_probe import DataProbe
        except Exception as exc:  # noqa: BLE001 - optional dependency guard
            return ModuleResult.fail(
                f"DataProbe unavailable: {type(exc).__name__}: {exc}",
                module=self.name,
            )

        try:
            probe = DataProbe(self._store, windows=[])
            result = probe.query(
                field=field, table=table, group_by=group_by,
                filter=filter, stats=stats,
            )
        except Exception as exc:  # noqa: BLE001 - keep run() graceful
            return ModuleResult.fail(
                f"probe query failed: {type(exc).__name__}: {exc}",
                module=self.name,
            )

        err = result.get("error") if isinstance(result, dict) else None
        if err:
            return ModuleResult.fail(err, module=self.name, data=result)
        return ModuleResult.success(
            message=f"data-explore:{table}.{field}",
            module=self.name,
            data=result,
        )

    # ── CLI ────────────────────────────────────────────────────────────

    @classmethod
    def register_cli(cls, subparsers: Any) -> Any:
        parser = super().register_cli(subparsers)
        parser.add_argument(
            "--field", required=True,
            help="Column name or arithmetic expression to summarise.",
        )
        parser.add_argument(
            "--table", default="radar_objects",
            help="Source table (radar_objects, radar_debug, warning_events).",
        )
        parser.add_argument(
            "--group-by", default=None,
            help="Column or semantic field to group by (e.g. side).",
        )
        parser.add_argument(
            "--filter", default=None,
            help="Boolean expression; only rows evaluating truthy are kept.",
        )
        parser.add_argument(
            "--stats", default=None,
            help="Comma list: count,min,max,mean,std,p10,p50,p90.",
        )
        parser.add_argument(
            "--case-dir", default=None,
            help="Case directory to load into a FrameStore (uses from_case).",
        )
        return parser

    @classmethod
    def from_cli_args(cls, args: Any) -> "DataDiagnosticsModule":
        case_dir = getattr(args, "case_dir", None)
        if case_dir:
            return cls.from_case(case_dir)
        return cls()
