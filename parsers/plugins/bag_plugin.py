# -*- coding: utf-8 -*-
"""BAG parser plugin — ingests ``.bag`` ROS bags via BagParser.

The deep wfAutosarData/wfObjectMsg extraction into ``radar_objects`` /
``radar_debug`` is deliberately kept in ``case_loader`` (it is tightly coupled
to topic discovery and legacy topic fallbacks). This plugin handles the base
frame ingestion + metadata, and exposes the discovered radar topics for the
deep-parse step in case_loader.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from core.plugin import PluginRegistry
from parsers.plugins.base import ParserContext, ParserPlugin, ParserResult


@PluginRegistry.register("parser", ".bag")
class BagParserPlugin(ParserPlugin):
    extension = ".bag"

    def load(self, path: Path, store: Any, ctx: ParserContext) -> ParserResult:
        from parsers.bag_parser import BagParser

        parser = BagParser(path)
        meta = parser.get_metadata()
        for frame in parser.iter_frames():
            store.insert_bag_frame(frame)
        return ParserResult(metadata=meta, metric={"format": "bag"})