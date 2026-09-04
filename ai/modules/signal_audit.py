# -*- coding: utf-8 -*-
"""
SignalAuditModule — deterministic BLF key-signal extraction and audit.

This standalone wrapper exposes the signal-audit engine as a stable V3
module boundary. It parses a BLF into a FrameStore (with optional DBC
decoding), then either:

  * ``audit`` — checks the key-chain switch signals against the contract
    table (enum validity, presence, UI-mode echo contract), or
  * ``extract`` — extracts value distribution / enum validity for any
    user-provided signal names (ad-hoc BLF queries).

Run standalone::

    python cli.py signal-audit --blf-path cases/EM2E_FCTAFCTB_SwitchAutoOn/x.blf --mode audit
    python cli.py signal-audit --blf-path x.blf --mode extract --signals ADCMode_UI_Status,FCTA_Enable_S

or from Python::

    from ai.modules.signal_audit import SignalAuditModule
    mod = SignalAuditModule(blf_path="x.blf", dbc_paths=[...])
    res = mod.safe_run(mode="audit")
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from engines.signal_audit import SIGNAL_AUDIT_CONTRACT, SignalAuditEngine
from parsers.dbc_loader import DbcLoader
from parsers.frame_store import FrameStore
from .base import BaseModule, ModuleResult

log = logging.getLogger(__name__)

AUDIT_MODES: tuple[str, ...] = ("audit", "extract", "signals")


class SignalAuditModule(BaseModule):
    """Deterministic BLF key-signal extraction / contract audit."""

    name = "signal-audit"
    description = "Extract and audit key CAN signals from a BLF (enum validity + contract)"

    def __init__(
        self,
        *,
        blf_path: str | Path | None = None,
        dbc_paths: list[str | Path] | tuple[str, ...] | None = None,
        contract: list[dict[str, Any]] | None = None,
    ) -> None:
        self._blf_path = Path(blf_path) if blf_path else None
        self._dbc_paths = [Path(p) for p in (dbc_paths or [])]
        self._contract = contract

    # ── data loading ─────────────────────────────────────────────────
    def _load_store(self) -> tuple[FrameStore, DbcLoader | None]:
        from parsers.blf_parser import BlfParser

        store = FrameStore()
        dbc_loader = DbcLoader(self._dbc_paths) if self._dbc_paths else None
        if self._blf_path is None or not self._blf_path.exists():
            raise ValueError(f"BLF not found: {self._blf_path}")
        parser = BlfParser(self._blf_path, dbc_loader=dbc_loader)
        store.bulk_insert_can(parser.iter_frames(decode=True))
        return store, dbc_loader

    # ── run ──────────────────────────────────────────────────────────
    def run(
        self,
        *,
        mode: str,
        signals: str = "",
        **_: Any,
    ) -> ModuleResult:
        if mode not in AUDIT_MODES:
            return ModuleResult.fail(
                f"unknown mode {mode!r}; choose one of {list(AUDIT_MODES)}",
                module=self.name,
            )
        if self._blf_path is None:
            return ModuleResult.fail(
                "signal-audit requires 'blf_path'", module=self.name,
            )

        try:
            store, dbc_loader = self._load_store()
        except Exception as exc:
            log.exception("load store failed")
            return ModuleResult.fail(
                f"failed to load BLF {self._blf_path}: {exc}", module=self.name,
            )

        engine = SignalAuditEngine(contract=self._contract)

        if mode == "audit":
            result = engine.audit(store, dbc_loader)
            anomaly_count = len(result["anomalies"])
            return ModuleResult.success(
                message=(
                    f"signal-audit:audit ({len(result['entries'])} signals, "
                    f"{anomaly_count} anomaly)"
                ),
                module=self.name,
                mode=mode,
                blf=str(self._blf_path),
                entries=[
                    {
                        "signal": e.name,
                        "role": e.role,
                        "present": e.present,
                        "can_id": e.can_id,
                        "message_name": e.message_name,
                        "frame_count": e.frame_count,
                        "observed_values": e.observed_values,
                        "legal_choices": e.legal_choices,
                        "anomalies": e.anomalies,
                        "notes": e.notes,
                    }
                    for e in result["entries"]
                ],
                anomalies=result["anomalies"],
                anomaly_count=anomaly_count,
                markdown=result["markdown"],
                contract_note=result["contract_note"],
            )

        if mode == "signals":
            names = [c["name"] for c in SIGNAL_AUDIT_CONTRACT]
            result = engine.extract_signals(store, names, dbc_loader)
            return ModuleResult.success(
                message=f"signal-audit:signals ({len(result['signals'])} extracted)",
                module=self.name,
                mode=mode,
                signals=result["signals"],
            )

        # mode == "extract"
        signal_names = [s.strip() for s in signals.split(",") if s.strip()]
        if not signal_names:
            return ModuleResult.fail(
                "mode 'extract' requires 'signals' (comma-separated names)",
                module=self.name,
            )
        result = engine.extract_signals(store, signal_names, dbc_loader)
        return ModuleResult.success(
            message=f"signal-audit:extract ({len(signal_names)} signals)",
            module=self.name,
            mode=mode,
            blf=str(self._blf_path),
            signals=result["signals"],
        )

    @classmethod
    def register_cli(cls, subparsers: Any) -> Any:
        parser = super().register_cli(subparsers)
        parser.add_argument(
            "--mode",
            required=True,
            choices=list(AUDIT_MODES),
            help="audit: contract check of key-chain signals; extract: "
                 "user-selected signals; signals: list contract signals.",
        )
        parser.add_argument(
            "--blf-path",
            default=None,
            help="Path to the BLF recording to parse.",
        )
        parser.add_argument(
            "--dbc",
            action="append",
            default=[],
            help="DBC file path for decoding. Repeat for multiple files.",
        )
        parser.add_argument(
            "--signals",
            default="",
            help="Comma-separated signal names for --mode extract.",
        )
        return parser

    @classmethod
    def from_cli_args(cls, args: Any) -> "SignalAuditModule":
        return cls(
            blf_path=getattr(args, "blf_path", None),
            dbc_paths=list(getattr(args, "dbc", None) or []),
        )
