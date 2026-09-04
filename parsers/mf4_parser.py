# -*- coding: utf-8 -*-
"""
MF4 (ASAM MFD4) measurement file parser.

Parses .mf4 files and writes measurement data to FrameStore.

Requires ``asammdf`` (install: ``pip install asammdf``).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Optional

import numpy as np

logger = logging.getLogger(__name__)


_CAN_CHANNEL_KEYWORDS = frozenset({
    "CAN_DataFrame", "CAN_ErrorFrame", "CAN_RemoteFrame",
    "CAN_DataFrame2", "CAN_ErrorFrame2",
})

_SKIP_CHANNEL_KEYWORDS = frozenset({
    "t", "time", "timestamp", "CAN_DataFrame", "CAN_ErrorFrame",
    "CAN_RemoteFrame", "CAN_DataFrame2", "CAN_ErrorFrame2",
})


@dataclass
class Mf4Frame:
    timestamp: float
    channel: str
    values: dict
    raw_data: Optional[bytes] = None


@dataclass
class Mf4Meta:
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


def _to_scalar(v: Any) -> Any:
    """Convert a numpy/pandas scalar to Python native type, or None if not representable."""
    if isinstance(v, (int, float, bool, str)):
        return v
    if isinstance(v, bytes):
        return None
    if isinstance(v, np.floating):
        val = float(v)
        return None if np.isnan(val) or np.isinf(val) else val
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.bool_):
        return bool(v)
    if isinstance(v, np.ndarray):
        return None
    if isinstance(v, (list, tuple)):
        return None
    try:
        f = float(v)
        if np.isnan(f) or np.isinf(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


def _interleave_sorted(*iterables):
    """Merge sorted iterables of (timestamp, payload) tuples.

    Each iterable yields (ts, payload) in ascending ts order.
    Yields (ts, payload_0, payload_1, ...) in globally ascending ts order.
    Payload is None for iterables that have no value at that ts.
    """
    import heapq
    heap = []
    for idx, it in enumerate(iterables):
        try:
            ts, payload = next(it)
            heapq.heappush(heap, (ts, idx, payload, it))
        except StopIteration:
            pass
    while heap:
        ts, idx, payload, it = heapq.heappop(heap)
        yield ts, idx, payload
        try:
            nts, npayload = next(it)
            heapq.heappush(heap, (nts, idx, npayload, it))
        except StopIteration:
            pass


def _extract_can_from_mf4_channel(ch_name: str, samples: np.ndarray) -> list[dict]:
    """Try to extract CAN ID + data bytes from a raw CAN channel in MF4.

    Some MF4 files store CAN bus data as structured channels
    (e.g. CAN_DataFrame with sub-channels ID, DLC, Data).
    This is a best-effort heuristic.
    """
    results = []
    if len(samples) == 0:
        return results
    try:
        structured = samples.dtype.names is not None
    except Exception:
        structured = False
    if not structured:
        return results
    for record in samples:
        if record is None:
            continue
        try:
            can_id = int(record.get("ID", 0) if structured else 0)
            dlc = int(record.get("DLC", 0) if structured else 0)
            raw = record.get("Data", b"") if structured else b""
            if isinstance(raw, np.ndarray):
                raw = bytes(raw.tolist())
            elif isinstance(raw, bytes):
                pass
            else:
                raw = b""
            results.append({
                "can_id": can_id,
                "dlc": dlc,
                "raw_data": raw,
            })
        except Exception:
            continue
    return results


class Mf4Parser:
    """Parse ASAM MFD4 measurement files and write to FrameStore."""

    def __init__(self, mf4_path: str | Path):
        self.mf4_path = Path(mf4_path)
        if not self.mf4_path.exists():
            raise FileNotFoundError(f"MF4 file not found: {self.mf4_path}")
        self._metadata: Optional[Mf4Meta] = None

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def get_metadata(self) -> dict:
        if self._metadata:
            return self._metadata.to_dict()
        meta = self._parse_metadata()
        self._metadata = meta
        return meta.to_dict()

    def iter_frames(self, channels: Optional[list[str]] = None) -> Iterator[Mf4Frame]:
        return self._parse_frames(channels)

    def write_to_store(self, store, channels: Optional[list[str]] = None,
                       batch_size: int = 1000) -> int:
        """Iterate MF4 frames and write directly into FrameStore *can_frames* table.

        Returns total frames written.
        """
        from asammdf import MDF

        if channels is None:
            with MDF(self.mf4_path) as mdf:
                channels = sorted({
                    ch for ch in mdf.channels_db
                    if not any(kw in ch for kw in _SKIP_CHANNEL_KEYWORDS)
                })
            if not channels:
                logger.info("Mf4Parser: no scalar channels found in %s", self.mf4_path.name)
                return 0

        count = 0
        batch: list[dict] = []
        for frame in self.iter_frames(channels):
            batch.append({
                "timestamp": frame.timestamp,
                "datetime_str": "",
                "channel": 0,
                "can_id": 0,
                "can_id_hex": "0x000",
                "dlc": 0,
                "message_name": frame.channel,
                "raw_hex": frame.raw_data.hex() if frame.raw_data else "",
                "signals": frame.values,
            })
            count += 1
            if len(batch) >= batch_size:
                store.bulk_insert_can_from_dict(batch, batch_size=batch_size)
                batch.clear()
        if batch:
            store.bulk_insert_can_from_dict(batch, batch_size=batch_size)
        return count

    # ------------------------------------------------------------------ #
    # Internal: Metadata
    # ------------------------------------------------------------------ #

    def _parse_metadata(self) -> Mf4Meta:
        from asammdf import MDF

        with MDF(self.mf4_path) as mdf:
            channels = sorted(mdf.channels_db.keys())
            start_time = 0.0
            end_time = 0.0
            sample_count = 0

            for i, group in enumerate(mdf.groups):
                try:
                    master = mdf.get_master(i)
                    if len(master) > 0:
                        t_min = float(master[0])
                        t_max = float(master[-1])
                        start_time = min(start_time, t_min) if i > 0 else t_min
                        end_time = max(end_time, t_max)
                        sample_count += len(master)
                except Exception:
                    pass

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

    # ------------------------------------------------------------------ #
    # Internal: Frame parsing
    # ------------------------------------------------------------------ #

    def _parse_frames(self, channels: Optional[list[str]] = None) -> Iterator[Mf4Frame]:
        """Iterate MF4 frames, yielding one :class:`Mf4Frame` per timestamp.

        Uses group-based iteration internally and interleaves channels
        by timestamp to produce a unified chronological stream.
        """
        from asammdf import MDF

        with MDF(self.mf4_path) as mdf:
            if channels is None:
                channels = sorted({
                    ch for ch in mdf.channels_db
                    if not any(kw in ch for kw in _SKIP_CHANNEL_KEYWORDS)
                })
            if not channels:
                return

            channel_set = set(channels)
            sig_cache: list[Optional[np.ndarray]] = [None] * len(channel_set)
            ch_names: list[str] = []
            ch_idx_map: dict[str, int] = {}

            for name in channels:
                if name in ch_idx_map:
                    continue
                ch_idx_map[name] = len(ch_names)
                ch_names.append(name)

            n = len(ch_names)

            def _channel_iter(idx: int) -> Iterator[tuple[float, Any]]:
                name = ch_names[idx]
                try:
                    ch_db = mdf.channels_db
                    occurrences = ch_db.get(name) if hasattr(ch_db, 'get') else None
                    
                    if isinstance(occurrences, tuple) and len(occurrences) == 2:
                        # Single occurrence — read directly
                        g_idx, ch_idx = occurrences
                        try:
                            sig = mdf.get(index=(g_idx, ch_idx), raw=False)
                            if sig and sig.timestamps and sig.samples:
                                try:
                                    timestamps = sig.timestamps
                                    samples = sig.samples
                                    arr_len = len(timestamps)
                                    for i in range(arr_len):
                                        ts = float(timestamps[i])
                                        val = _to_scalar(samples[i])
                                        if val is not None:
                                            yield ts, val
                                except Exception:
                                    pass
                        except Exception:
                            pass
                    elif isinstance(occurrences, tuple) and len(occurrences) > 2:
                        # Multiple occurrences — try each until one works
                        try:
                            for occ in occurrences:  # each occ is (group_idx, ch_idx)
                                try:
                                    sig = mdf.get(index=occ, raw=False)
                                    if sig and sig.timestamps and sig.samples:
                                        try:
                                            timestamps = sig.timestamps
                                            samples = sig.samples
                                            arr_len = len(timestamps)
                                            for i in range(arr_len):
                                                ts = float(timestamps[i])
                                                val = _to_scalar(samples[i])
                                                if val is not None:
                                                    yield ts, val
                                        except Exception:
                                            pass
                                        return  # Use first valid occurrence
                                except Exception:
                                    continue
                        except Exception:
                            pass
                    else:
                        # Fallback
                        try:
                            sig = mdf.get(name, raw=False)
                            if sig and sig.timestamps and sig.samples:
                                timestamps = sig.timestamps
                                samples = sig.samples
                                if timestamps is not None and samples is not None:
                                    for i in range(len(timestamps)):
                                        ts = float(timestamps[i])
                                        val = _to_scalar(samples[i])
                                        if val is not None:
                                            yield ts, val
                        except Exception:
                            pass
                except Exception:
                    return

            iters = [_channel_iter(i) for i in range(n)]
            current: dict[int, Optional[Any]] = {i: None for i in range(n)}
            last_ts: Optional[float] = None
            for ts, idx, val in _interleave_sorted(*iters):
                current[idx] = val
                if last_ts is not None and ts != last_ts:
                    values = {
                        ch_names[i]: current[i]
                        for i in range(n)
                        if current[i] is not None
                    }
                    if values:
                        yield Mf4Frame(timestamp=last_ts, channel="MF4", values=values)
                    current = {i: current[i] for i in range(n)}
                last_ts = ts

            if last_ts is not None:
                values = {
                    ch_names[i]: current[i]
                    for i in range(n)
                    if current[i] is not None
                }
                if values:
                    yield Mf4Frame(timestamp=last_ts, channel="MF4", values=values)


def check_mf4_dependency() -> bool:
    """Check if an MF4 parsing library is available."""
    try:
        import asammdf  # noqa: F401
        return True
    except ImportError:
        pass
    return False


# ─── Xpeng Reco (RCC1010) MF4 channel schema ─────────────────────────────

# Xpeng 5th-gen RCC1010 MF4 signal prefixes categorization.
# Maps signal name prefixes to semantic categories used by the
# reco_fw component architecture.

_XPENG_RECO_CHANNEL_CATEGORIES: list[tuple[str, frozenset[str]]] = [
    # Radar direct output (RRL = RearLeft, RRR = RearRight)
    ("radar_output", frozenset({
        "BYD_5R1V_RadarRearcorner_V2_5.",
    })),
    # Public CAN matrix signals
    ("can_public", frozenset({
        "CR_PublicCAN_Matrix_V1_2_0_20260402.",
    })),
    # Lane / road boundary
    ("lane_boundary", frozenset({
        "CR60LT_L.",
        "CR60LT_LS.",
    })),
    # PER output interfaces (FusedObjects etc.)
    ("fused_objects", frozenset({
        "FusedObjects",
        "per_fusedObjects",
    })),
    # Ego vehicle state
    ("ego", frozenset({
        "EgoVehicle",
        "HostVehicle",
        "VCU_",
        "g_ego",
        "actual_gear",
        "actual_spd",
    })),
    # Failure / diagnostics
    ("failure_diag", frozenset({
        "FailureReactionStates",
        "DsmState",
        "ServiceState",
        "OOS",
        "Outspec",
    })),
]

# Categories that count as "data channels" (not pure time/bus metadata)
_DATA_CHANNEL_PREFIXES: frozenset[str] = frozenset({
    "ABS_",
    "ACC_",
    "ADAS_",
    "AX", "AY", "AZ",  # body acceleration
    "BrakePedal",
    "CarAccel",
    "CarSpeed",
    "EPS_",
    "ESP_",
    "FCTA_",
    "FCTB_",
    "FRONT_",
    "GearSts",
    "LCA_",
    "RCW_",
    "RCTA_",
    "RCTB_",
    "RearRadar",
    "Right_Radar",
    "RRadar_",
    "RRB_",
    "STEER_",
    "VehicleSpd",
    "VCU_",
    "YawRate",
    "YawRate",
    "actual_",
    "abs_",
    "car_spd",
    "dctc",
    "dow_",
    "fcta_",
    "fctb_",
    "fused_",
    "gear_s",
    "lca_",
    "rcw_",
    "rcta_",
    "rctb_",
})

# Prefixes that identify "time / bus / metadata-only" channels
_SKIP_CHANNEL_KEYWORDS = frozenset({
    # Multi-char keywords treated as substring matches:
    "BusChannel", "isADASSync",
    "CAN_DataFrame", "CAN_ErrorFrame",
    "CAN_RemoteFrame", "CAN_DataFrame2", "CAN_ErrorFrame2",
    # Long prefix to avoid accidental substring matches:
    "CR_PublicCAN_Matrix_V1_2_0_20260402.Child_ID_",
})

# Single-char exact names that should ONLY match the full channel name
_SKIP_EXACT_NAMES = frozenset({"t", "time", "timestamp"})


def is_xpeng_data_channel(channel_name: str) -> bool:
    """Return True if the channel is likely a meaningful data signal."""
    if channel_name in _SKIP_EXACT_NAMES:
        return False
    return not any(kw in channel_name for kw in _SKIP_CHANNEL_KEYWORDS
                   if len(kw) > 3)


def classify_xpeng_mf4_channels(channels: list[str]) -> dict[str, list[str]]:
    """Classify MF4 signal names into semantic categories.

    Returns a dict mapping category name → list of signal names.
    Categories: ``radar_output``, ``can_public``, ``fused_objects``,
    ``ego``, ``failure_diag``, ``unknown``.
    """
    result: dict[str, list[str]] = {
        "radar_output": [], "can_public": [], "fused_objects": [],
        "lane_boundary": [], "ego": [], "failure_diag": [],
        "unknown": [],
    }
    for ch in channels:
        classified = False
        for category, prefixes in _XPENG_RECO_CHANNEL_CATEGORIES:
            if any(pfx in ch for pfx in prefixes):
                result[category].append(ch)
                classified = True
                break
        if not classified:
            if ch in _DATA_CHANNEL_PREFIXES or any(kw in ch for kw in ["_", "dctc", "yaw"]):
                result["unknown"].append(ch)
            else:
                result["unknown"].append(ch)
    # Remove empty categories
    return {k: v for k, v in result.items() if v}
