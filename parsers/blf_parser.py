# -*- coding: utf-8 -*-
"""
BLF file parser with DBC-based signal decoding.
"""
import can
import datetime
from pathlib import Path
from typing import Iterator, Optional
from dataclasses import dataclass, field
from .dbc_loader import DbcLoader


@dataclass
class CanFrame:
    """A single decoded CAN frame."""
    timestamp: float
    datetime_str: str
    channel: int
    can_id: int
    can_id_hex: str
    dlc: int
    is_extended: bool
    is_fd: bool
    raw_data: bytes
    raw_hex: str
    message_name: Optional[str] = None
    signals: dict = field(default_factory=dict)


class BlfParser:
    """Parse BLF files and decode CAN signals using DBC definitions."""

    def __init__(self, blf_path: str | Path, dbc_loader: Optional[DbcLoader] = None):
        self.blf_path = Path(blf_path)
        if not self.blf_path.exists():
            raise FileNotFoundError(f"BLF file not found: {self.blf_path}")
        self.dbc = dbc_loader
        self._metadata = None

    def get_metadata(self) -> dict:
        """Get BLF file metadata by scanning all messages."""
        if self._metadata:
            return self._metadata
        from collections import Counter
        reader = can.BLFReader(str(self.blf_path))
        msg_count = 0
        arb_ids = Counter()
        channels = Counter()
        first_ts = last_ts = None
        for msg in reader:
            msg_count += 1
            arb_ids[msg.arbitration_id] += 1
            if msg.channel is not None:
                channels[msg.channel] += 1
            if first_ts is None:
                first_ts = msg.timestamp
            last_ts = msg.timestamp

        duration = (last_ts - first_ts) if first_ts and last_ts else 0
        self._metadata = {
            "file": self.blf_path.name,
            "size_mb": self.blf_path.stat().st_size / 1024 / 1024,
            "message_count": msg_count,
            "duration_sec": duration,
            "start_time": datetime.datetime.fromtimestamp(first_ts).isoformat() if first_ts else None,
            "end_time": datetime.datetime.fromtimestamp(last_ts).isoformat() if last_ts else None,
            "unique_can_ids": len(arb_ids),
            "channels": dict(channels),
            "top_ids": [
                {"can_id_hex": f"0x{cid:X}", "count": cnt}
                for cid, cnt in arb_ids.most_common(20)
            ],
        }
        return self._metadata

    def iter_frames(
        self,
        can_ids: Optional[set[int]] = None,
        decode: bool = True,
    ) -> Iterator[CanFrame]:
        """
        Iterate over CAN frames, optionally filtering by CAN ID and decoding signals.

        Args:
            can_ids: Filter to specific CAN IDs. None = all.
            decode: If True and DBC is loaded, decode signals.
        """
        reader = can.BLFReader(str(self.blf_path))
        for msg in reader:
            if can_ids and msg.arbitration_id not in can_ids:
                continue

            data_hex = " ".join(f"{b:02x}" for b in msg.data)
            dt_str = datetime.datetime.fromtimestamp(msg.timestamp).isoformat()
            msg_name = None
            signals = {}

            if decode and self.dbc:
                msg_name = self.dbc.get_message_name(msg.arbitration_id)
                decoded = self.dbc.decode(msg.arbitration_id, msg.data)
                if decoded:
                    signals = decoded

            yield CanFrame(
                timestamp=msg.timestamp,
                datetime_str=dt_str,
                channel=msg.channel or 0,
                can_id=msg.arbitration_id,
                can_id_hex=f"0x{msg.arbitration_id:X}",
                dlc=msg.dlc,
                is_extended=msg.is_extended_id,
                is_fd=msg.is_fd,
                raw_data=msg.data,
                raw_hex=data_hex,
                message_name=msg_name,
                signals=signals,
            )

    def get_signal_timeline(
        self,
        can_id: int,
        signal_names: Optional[list[str]] = None,
    ) -> list[dict]:
        """
        Extract a timeline of specific signals from a CAN ID.
        Useful for tracking variable changes over time.
        """
        timeline = []
        for frame in self.iter_frames(can_ids={can_id}, decode=True):
            if not frame.signals:
                continue
            entry = {
                "timestamp": frame.timestamp,
                "datetime": frame.datetime_str,
            }
            if signal_names:
                entry.update({k: v for k, v in frame.signals.items() if k in signal_names})
            else:
                entry.update(frame.signals)
            timeline.append(entry)
        return timeline
