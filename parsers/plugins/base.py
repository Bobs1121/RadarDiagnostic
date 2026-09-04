# -*- coding: utf-8 -*-
"""
ParserPlugin SPI — the contract for pluggable data-format ingestion.

Any new format (``.asc``, ``.xlsx``, custom) is added by implementing
:class:`ParserPlugin` and registering it via ``@PluginRegistry.register("parser", ext)``.
No change to ``parsers.case_loader.load_case_data`` is required beyond the
registry lookup (which already falls back to legacy glob handlers).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


@dataclass
class ParserContext:
    """Shared context handed to every parser plugin by case_loader."""

    config: dict
    project_root: Path
    workspace: Any = None
    dbc: Any = None
    on_status: Optional[callable] = None

    def status(self, step: str, detail: str = "") -> None:
        if self.on_status:
            self.on_status(step, detail)


@dataclass
class ParserResult:
    """What a parser plugin produced for one file."""

    metadata: Optional[dict] = None
    # Format-agnostic: case_loader merges these into the result.
    metric: Optional[dict] = None
    warnings: list[str] = field(default_factory=list)


class ParserPlugin(ABC):
    """Ingest one file of a given format into a FrameStore."""

    #: File extension this plugin handles, e.g. ``".bag"``.
    extension: str = ""

    @abstractmethod
    def load(self, path: Path, store: Any, ctx: ParserContext) -> ParserResult:
        """Parse ``path`` and write normalized rows into ``store``.

        Returns a :class:`ParserResult` with metadata/warnings. Must not raise
        for malformed input — degrade and record a warning instead.
        """
        raise NotImplementedError

    def matches(self, path: Path) -> bool:
        return path.suffix.lower() == self.extension.lower()