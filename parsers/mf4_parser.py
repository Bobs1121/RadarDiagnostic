# -*- coding: utf-8 -*-
"""
MF4 (ASAM MFD4) measurement file parser.

Parses .mf4 files and writes measurement data to FrameStore.

DEPENDENCY STATUS:
    Requires `asammdf` or `mffparser` library, neither of which is currently
    available in the project environment (blocked by network/artifactory).
    This module provides the full interface and integration scaffolding;
    the core parsing logic is stubbed with NotImplementedError until the
    dependency can be installed.

TODO (when dependency available):
    - pip install asammdf  (preferred) or mffparser
    - Replace _parse_mf4_* stubs with actual implementation
    - Test with real MF4 measurement data
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Optional

logger = logging.getLogger(__name__)


@dataclass
class Mf4Frame:
    """A single parsed frame from an MF4 file."""
    timestamp: float
    channel: str
    values: dict  # signal_name -> value
    raw_data: Optional[bytes] = None


@dataclass
class Mf4Meta:
    """Metadata about a parsed MF4 file."""
    file: str
    size_mb: float
    duration_sec: float
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    channel_count: int = 0
    sample_count: int = 0
    channels: list[str] = field(default_factory=list)


class Mf4Parser:
    """Parse ASAM MFD4 measurement files and write to FrameStore."""

    def __init__(self, mf4_path: str | Path):
        self.mf4_path = Path(mf4_path)
        if not self.mf4_path.exists():
            raise FileNotFoundError(f"MF4 file not found: {self.mf4_path}")
        self._metadata: Optional[Mf4Meta] = None

    def get_metadata(self) -> dict:
        """Get MF4 file metadata without iterating all samples."""
        if self._metadata:
            return self._metadata.to_dict()
        meta = self._parse_mf4_metadata()
        self._metadata = meta
        return meta.to_dict()

    def iter_frames(self, channels: Optional[list[str]] = None) -> Iterator[Mf4Frame]:
        """
        Iterate over all samples, yielding Mf4Frame objects.

        Args:
            channels: Filter to specific channels. None = all channels.
        """
        return self._parse_mf4_frames(channels)

    def write_to_store(self, store, channels: Optional[list[str]] = None,
                       batch_size: int = 1000) -> int:
        """
        Parse MF4 file and write directly to FrameStore can_frames table.

        Returns the total number of frames written.
        """
        frames = list(self.iter_frames(channels))
        if not frames:
            return 0

        # Convert Mf4Frame to CanFrame-compatible dicts for bulk insert
        can_frames = []
        for f in frames:
            can_frames.append({
                "timestamp": f.timestamp,
                "datetime_str": "",
                "channel": 0,
                "can_id": 0,  # MF4 doesn't have CAN IDs directly
                "can_id_hex": "0x000",
                "dlc": 0,
                "message_name": f.channel,
                "raw_hex": f.raw_data.hex() if f.raw_data else "",
                "signals": f.values,
            })

        return store.bulk_insert_can_from_dict(can_frames, batch_size=batch_size)

    # ------------------------------------------------------------------ #
    # Internal: MF4 parsing (stubbed — dependency not available)
    # ------------------------------------------------------------------ #

    def _parse_mf4_metadata(self) -> Mf4Meta:
        """Parse MF4 metadata. STUB — requires asammdf/mffparser."""
        logger.warning(
            "Mf4Parser._parse_mf4_metadata: STUB — asammdf/mffparser not installed. "
            "Install with: pip install asammdf"
        )
        return Mf4Meta(
            file=self.mf4_path.name,
            size_mb=self.mf4_path.stat().st_size / 1024 / 1024,
            duration_sec=0.0,
            channel_count=0,
            sample_count=0,
        )

    def _parse_mf4_frames(self, channels: Optional[list[str]] = None) -> Iterator[Mf4Frame]:
        """Parse MF4 frames. STUB — requires asammdf/mffparser."""
        logger.warning(
            "Mf4Parser._parse_mf4_frames: STUB — asammdf/mffparser not installed. "
            "No MF4 data will be loaded."
        )
        return iter([])


def check_mf4_dependency() -> bool:
    """Check if an MF4 parsing library is available."""
    try:
        import asammdf  # noqa: F401
        return True
    except ImportError:
        pass
    try:
        import mffparser  # noqa: F401
        return True
    except ImportError:
        pass
    return False
