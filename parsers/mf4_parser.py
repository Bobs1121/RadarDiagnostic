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

    def to_dict(self):
        return {
            "file": self.file,
            "size_mb": self.size_mb,
            "duration_sec": self.duration_sec,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "channel_count": self.channel_count,
            "sample_count": self.sample_count,
            "channels": self.channels,
        }


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
        # If no specific channels requested, we still shouldn't load everything due to RAM.
        # But we need to load *something*. For visualization, we often want all scalar channels.
        # But it's safer to only load what's explicitly requested later via iter_frames.
        # Wait, if we are loading the case, we need to populate FrameStore.
        # Let's extract a safe subset of channels if channels is None.
        if channels is None:
            logger.info("Mf4Parser.write_to_store: No channels specified. Loading all scalar channels can take high RAM. We will extract channels that are not raw bytes.")
            try:
                from asammdf import MDF
                with MDF(self.mf4_path) as mdf:
                    safe_channels = []
                    for ch in mdf.channels_db.keys():
                        if "CAN_DataFrame" not in ch and "CAN_ErrorFrame" not in ch:
                            safe_channels.append(ch)
                    channels = safe_channels
            except ImportError:
                return 0

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
        """Parse MF4 metadata using asammdf."""
        try:
            from asammdf import MDF
            import numpy as np
        except ImportError:
            logger.warning("Mf4Parser._parse_mf4_metadata: asammdf not installed.")
            return Mf4Meta(
                file=self.mf4_path.name,
                size_mb=self.mf4_path.stat().st_size / 1024 / 1024,
                duration_sec=0.0,
                channel_count=0,
                sample_count=0,
            )

        with MDF(self.mf4_path) as mdf:
            channels = list(mdf.channels_db.keys())
            # Usually the first channel group has the master time channel
            start_time = 0.0
            end_time = 0.0
            sample_count = 0
            
            # Simple duration heuristic if groups exist
            if mdf.groups:
                for i, group in enumerate(mdf.groups):
                    try:
                        # get the master channel (time)
                        master_ch = mdf.get_master(i)
                        if len(master_ch) > 0:
                            t_min = float(master_ch[0])
                            t_max = float(master_ch[-1])
                            end_time = max(end_time, t_max)
                            sample_count += len(master_ch)
                    except Exception as e:
                        logger.debug(f"Failed to get master channel for group {i}: {e}")

            return Mf4Meta(
                file=self.mf4_path.name,
                size_mb=self.mf4_path.stat().st_size / 1024 / 1024,
                duration_sec=end_time - start_time,
                start_time=start_time,
                end_time=end_time,
                channel_count=len(channels),
                sample_count=sample_count,
                channels=channels,
            )

    def _parse_mf4_frames(self, channels: Optional[list[str]] = None) -> Iterator[Mf4Frame]:
        """Parse MF4 frames using asammdf. Groups samples by timestamp."""
        try:
            from asammdf import MDF
        except ImportError:
            logger.warning("Mf4Parser._parse_mf4_frames: asammdf not installed.")
            return iter([])

        with MDF(self.mf4_path) as mdf:
            if channels is None:
                # To dump ALL channels safely without crashing on VLSD/duplicates,
                # we'd need to iterate groups. For our FrameStore usecase, it's safer
                # to only process explicitly requested channels, or we risk OOM / crashes.
                logger.warning("Mf4Parser._parse_mf4_frames: Extracting all channels is disabled for stability. Please provide a list of channels.")
                return iter([])

            # Dictionary to collect points: timestamp -> {channel: value}
            # This is a basic pivot in python.
            time_series = {}

            for ch_name in channels:
                try:
                    # mdf.get() can find the channel if it's unique.
                    # If there are duplicates, we might need whereis, but get() often handles the primary one.
                    sig = mdf.get(ch_name)
                    timestamps = sig.timestamps
                    samples = sig.samples
                    
                    for i in range(len(timestamps)):
                        t = float(timestamps[i])
                        v = samples[i]
                        
                        # filter out NaN and complex types
                        if isinstance(v, (int, float, bool)):
                            if t not in time_series:
                                time_series[t] = {}
                            time_series[t][ch_name] = v
                except Exception as e:
                    logger.debug(f"Failed to extract channel {ch_name}: {e}")

            # Yield sorted frames
            for ts in sorted(time_series.keys()):
                yield Mf4Frame(
                    timestamp=ts,
                    channel="MF4_DATA",
                    values=time_series[ts],
                )


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
