# -*- coding: utf-8 -*-
"""
Requirement → Code → Signal tracer (M3).

Given a :class:`~core.materials.RequirementSpec`, build a deterministic
traceability triple linking the requirement to the C functions/files that touch
its signals (via :class:`ai.codegraph.query.CodeGraph`) and confirm each signal
is observable in the DBC signal mapping.

The tracer performs **no** LLM calls, and both external dependencies
(``codegraph`` and ``signal_mapping``) are optional/injectable so it runs in
unit tests without a real database.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from core.materials import RequirementSpec, StructuredRequirementSet

if TYPE_CHECKING:  # pragma: no cover - typing only, avoids a heavy runtime import
    from ai.codegraph.query import CodeGraph

log = logging.getLogger(__name__)


class RequirementTracer:
    """Build requirement↔code↔signal traceability, purely deterministically."""

    def __init__(
        self,
        codegraph: "CodeGraph | None" = None,
        signal_mapping: dict | None = None,
    ) -> None:
        self.codegraph = codegraph
        self.signal_mapping = signal_mapping or {}
        self._known_signals = self._build_known_signals(self.signal_mapping)

    # ── public API ─────────────────────────────────────────────────────

    def trace(self, spec: RequirementSpec | None) -> dict:
        """Return a ``{req -> code -> signal}`` traceability record for ``spec``."""
        if spec is None:
            return {
                "req_id": "",
                "statement": "",
                "signals": [],
                "coverage": "none",
                "gaps": ["empty requirement"],
                "linked_functions": [],
                "linked_files": [],
            }

        signals = [s for s in (spec.linked_signals or []) if s]
        signal_entries: list[dict] = []
        all_functions: list[str] = []
        all_files: list[str] = []
        gaps: list[str] = []
        resolved = 0

        for sig in signals:
            functions, files = self._lookup_signal(sig)
            in_dbc = self._signal_in_dbc(sig)
            if functions:
                resolved += 1
            else:
                gaps.append(f"{sig}: no code function linked")
            if not in_dbc:
                gaps.append(f"{sig}: not found in signal mapping")
            for fn in functions:
                if fn not in all_functions:
                    all_functions.append(fn)
            for fp in files:
                if fp not in all_files:
                    all_files.append(fp)
            signal_entries.append(
                {
                    "name": sig,
                    "in_dbc": in_dbc,
                    "functions": functions,
                    "files": files,
                }
            )

        if not signals:
            gaps.append("no linked signals")

        return {
            "req_id": spec.requirement_id,
            "statement": spec.statement,
            "signals": signal_entries,
            "coverage": self._classify_coverage(len(signals), resolved),
            "gaps": gaps,
            "linked_functions": all_functions,
            "linked_files": all_files,
        }

    def trace_set(self, req_set: StructuredRequirementSet | dict | None) -> list[dict]:
        """Trace every requirement in a set (or plain id->spec dict)."""
        reqs = self._as_reqs(req_set)
        return [self.trace(spec) for spec in reqs.values()]

    # ── internals ──────────────────────────────────────────────────────

    @staticmethod
    def _as_reqs(req_set) -> dict:
        if req_set is None:
            return {}
        reqs = getattr(req_set, "requirements", None)
        if reqs is None and isinstance(req_set, dict):
            reqs = req_set
        return reqs or {}

    @staticmethod
    def _classify_coverage(n_signals: int, n_resolved: int) -> str:
        if n_signals == 0 or n_resolved == 0:
            return "none"
        if n_resolved >= n_signals:
            return "full"
        return "partial"

    def _lookup_signal(self, sig: str) -> tuple[list[str], list[str]]:
        """Return (functions, files) touching ``sig`` per the CodeGraph."""
        if self.codegraph is None:
            return [], []
        try:
            rows = self.codegraph.get_functions_using_signal(sig) or []
        except Exception as exc:  # noqa: BLE001 - external DB guard
            log.debug("codegraph lookup failed for %s: %s", sig, exc)
            return [], []

        functions: list[str] = []
        files: list[str] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            fn = row.get("func_name") or row.get("name")
            if fn and fn not in functions:
                functions.append(fn)
            raw_file = row.get("file_id") or row.get("file_path") or row.get("file")
            if raw_file:
                fpath = str(raw_file)
                if fpath.startswith("FILE:"):
                    fpath = fpath[len("FILE:"):]
                if fpath and fpath not in files:
                    files.append(fpath)
        return functions, files

    def _signal_in_dbc(self, sig: str) -> bool:
        if not self._known_signals:
            return False
        return sig in self._known_signals

    @staticmethod
    def _build_known_signals(signal_mapping: dict) -> set[str]:
        """Collect every CAN signal name observable in the mapping."""
        known: set[str] = set()
        if not isinstance(signal_mapping, dict):
            return known
        c2i = signal_mapping.get("can_to_internal")
        if isinstance(c2i, dict):
            known.update(k for k in c2i if isinstance(k, str))
        i2c = signal_mapping.get("internal_to_can")
        if isinstance(i2c, dict):
            for vals in i2c.values():
                if isinstance(vals, list):
                    known.update(v for v in vals if isinstance(v, str))
        for m in signal_mapping.get("mappings") or []:
            if isinstance(m, dict) and isinstance(m.get("can_signal"), str):
                known.add(m["can_signal"])
        s2e = signal_mapping.get("signal_to_expr")
        if isinstance(s2e, dict):
            known.update(k for k in s2e if isinstance(k, str))
        return known
