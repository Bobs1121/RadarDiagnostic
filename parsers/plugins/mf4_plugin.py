# -*- coding: utf-8 -*-
"""MF4 parser plugin — ingests ``.mf4`` measurement data via Mf4Parser."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from core.plugin import PluginRegistry
from parsers.plugins.base import ParserContext, ParserPlugin, ParserResult


@PluginRegistry.register("parser", ".mf4")
class Mf4ParserPlugin(ParserPlugin):
    extension = ".mf4"

    def __init__(self) -> None:
        self._available: bool | None = None

    def _check_available(self) -> bool:
        if self._available is None:
            from parsers.mf4_parser import check_mf4_dependency
            self._available = check_mf4_dependency()
        return self._available

    def load(self, path: Path, store: Any, ctx: ParserContext) -> ParserResult:
        if not self._check_available():
            return ParserResult(
                metadata=None,
                warnings=[f"MF4 {path.name} found but asammdf not installed — skipped"],
            )
        from parsers.mf4_parser import Mf4Parser

        try:
            parser = Mf4Parser(path)
            meta = parser.get_metadata()
            parser.write_to_store(store)
            return ParserResult(metadata=meta, metric={"format": "mf4"})
        except Exception as exc:  # pragma: no cover - malformed input guard
            return ParserResult(
                metadata=None,
                warnings=[f"MF4 {path.name} parse failed: {exc}"],
            )