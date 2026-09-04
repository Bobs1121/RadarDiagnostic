# -*- coding: utf-8 -*-
"""
RequirementModule (M3 + M8): a composable :class:`~ai.modules.base.BaseModule`
wrapping the requirement loader, tracer, and reviewer.

Modes:
    ``trace``   — build requirement↔code↔signal traceability only.
    ``review``  — audit requirements for structural/semantic defects only.
    ``all``     — run both and return a combined payload.

All heavy dependencies (LLM router, CodeGraph, signal mapping) are optional and
injected through the constructor, so the module runs offline by default.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ai.modules.base import BaseModule, ModuleResult
from core.materials import StructuredRequirementSet

from .loader import RequirementLoader
from .reviewer import RequirementReviewer
from .tracer import RequirementTracer

log = logging.getLogger(__name__)

_VALID_MODES = ("trace", "review", "all")


class RequirementModule(BaseModule):
    """Standalone capability exposing requirement trace + review (M3/M8)."""

    name = "req-review"
    description = "Review & trace ADAS requirements (M3/M8)"

    def __init__(
        self,
        router: Any = None,
        codegraph: Any = None,
        signal_mapping: dict | None = None,
    ) -> None:
        self.router = router
        self.codegraph = codegraph
        self.signal_mapping = signal_mapping or {}

    # ── run ────────────────────────────────────────────────────────────

    def run(
        self,
        *,
        req_dir: str | Path | None = None,
        req_set: StructuredRequirementSet | dict | None = None,
        mode: str = "review",
        variant_id: str = "",
        **_: Any,
    ) -> ModuleResult:
        resolved = self._resolve_req_set(req_dir, req_set, variant_id)
        if resolved is None or not resolved.requirements:
            return ModuleResult.fail(
                "no requirements found (provide req_dir or req_set)",
                module=self.name,
            )

        mode = (mode or "review").lower()
        if mode not in _VALID_MODES:
            return ModuleResult.fail(f"unknown mode: {mode}", module=self.name)

        data: dict[str, Any] = {
            "variant_id": resolved.variant_id,
            "n_reqs": len(resolved.requirements),
            "mode": mode,
        }

        if mode in ("trace", "all"):
            tracer = RequirementTracer(
                codegraph=self.codegraph, signal_mapping=self.signal_mapping
            )
            data["traces"] = tracer.trace_set(resolved)

        if mode in ("review", "all"):
            reviewer = RequirementReviewer(
                router=self.router, signal_mapping=self.signal_mapping
            )
            data["review"] = reviewer.review(resolved)

        return ModuleResult.success(
            message=self._summarize(data), module=self.name, **data
        )

    # ── helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _resolve_req_set(
        req_dir: str | Path | None,
        req_set: StructuredRequirementSet | dict | None,
        variant_id: str,
    ) -> StructuredRequirementSet | None:
        if req_set is not None:
            if isinstance(req_set, StructuredRequirementSet):
                return req_set
            if isinstance(req_set, dict):
                try:
                    return StructuredRequirementSet.from_dict(req_set)
                except Exception:  # noqa: BLE001 - malformed dict => treat as missing
                    return None
            return None
        if req_dir:
            return RequirementLoader().load_yaml_dir(Path(req_dir), variant_id=variant_id)
        return None

    @staticmethod
    def _summarize(data: dict) -> str:
        bits = [f"{data['n_reqs']} requirement(s)"]
        traces = data.get("traces")
        if traces is not None:
            covered = sum(1 for t in traces if t.get("coverage") == "full")
            bits.append(f"trace: {covered}/{len(traces)} fully covered")
        review = data.get("review")
        if review is not None:
            n_issues = review.get("summary", {}).get("n_issues", 0)
            bits.append(f"review: {n_issues} issue(s)")
        return "; ".join(bits)

    # ── CLI wiring (integration owner attaches this to cli.py) ──────────

    @classmethod
    def register_cli(cls, subparsers: Any) -> Any:
        parser = super().register_cli(subparsers)
        parser.add_argument(
            "--req-dir", dest="req_dir", default=None,
            help="Directory of requirement *.yaml files to load.",
        )
        parser.add_argument(
            "--mode", choices=list(_VALID_MODES), default="review",
            help="Operation mode: trace, review, or all.",
        )
        parser.add_argument(
            "--variant", dest="variant_id", default="",
            help="Variant id scope for the loaded requirements.",
        )
        return parser

    @classmethod
    def from_cli_args(cls, args: Any) -> "RequirementModule":
        return cls()
