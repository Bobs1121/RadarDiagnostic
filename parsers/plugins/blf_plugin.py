# -*- coding: utf-8 -*-
"""BLF parser plugin — ingests ``.blf`` CAN logs via BlfParser."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from core.plugin import PluginRegistry
from parsers.plugins.base import ParserContext, ParserPlugin, ParserResult


@PluginRegistry.register("parser", ".blf")
class BlfParserPlugin(ParserPlugin):
    extension = ".blf"

    def load(self, path: Path, store: Any, ctx: ParserContext) -> ParserResult:
        from parsers.blf_parser import BlfParser

        try:
            parser = BlfParser(path, dbc_loader=ctx.dbc)
            meta = parser.get_metadata()
            store.bulk_insert_can(parser.iter_frames(decode=True))
            return ParserResult(metadata=meta, metric={"format": "blf"})
        except Exception as exc:  # pragma: no cover - malformed input guard
            return ParserResult(
                metadata=None,
                warnings=[f"BLF {path.name} parse failed: {exc}"],
            )