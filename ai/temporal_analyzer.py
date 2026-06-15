# -*- coding: utf-8 -*-
"""
Temporal Analyzer
=================

Extracts time-series features (NOT just value distributions) from signals.

Why this exists
---------------
The existing ``frame_analyzer`` summarises signals via ``Counter(values)`` —
which collapses the temporal axis and hides critical patterns such as

* a signal being ``1`` for 98 % of the time but dropping to ``0`` for 120 ms
  right when a hold-release check fires;
* a warning flag that oscillates rapidly so the debounced state never latches;
* an accumulator that keeps getting reset because its driving condition is
  met only in short bursts.

``TemporalAnalyzer`` computes the primitives that make these scenarios
explicit:

* **edges** — every ``(t, from, to)`` transition
* **runs**  — contiguous ``(value, t_start, t_end, duration)`` segments
* **stats** — min/max/total duration per value; edge count; transition rate
* **pattern tag** — a coarse qualitative label (``stable`` /
  ``brief_pulses`` / ``oscillating`` / ``edge_dominated``)

The module is deterministic (no AI). It is the data-side half of the
Temporal Pattern Engine; the code-side half is ``pattern_extractor`` and
they are stitched together by ``causal_aligner``.
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable, Optional


__all__ = [
    "Edge",
    "Run",
    "SignalTimeline",
    "TemporalFeature",
    "TemporalAnalyzer",
    "format_temporal_features",
]


# ── Core datatypes ───────────────────────────────────────────────────────


@dataclass
class Edge:
    """A single transition ``from_value -> to_value`` at time ``t`` (seconds)."""
    t: float
    from_val: object
    to_val: object


@dataclass
class Run:
    """A contiguous segment where the signal holds ``value`` for ``duration``s."""
    value: object
    t_start: float
    t_end: float

    @property
    def duration(self) -> float:
        return self.t_end - self.t_start


@dataclass
class SignalTimeline:
    """A raw ``[(t, value), ...]`` series bundled with a name for logging."""
    name: str
    samples: list[tuple[float, object]]

    def is_empty(self) -> bool:
        return not self.samples


@dataclass
class TemporalFeature:
    """
    Full temporal fingerprint of a single signal.

    ``runs_by_value`` lets callers answer questions like
    "what is the shortest time AEBBAActv stayed at 0?" in O(1).
    """
    signal_name: str
    sample_count: int
    t_start: float
    t_end: float
    value_distribution: dict[object, int]
    edges: list[Edge]
    runs: list[Run]
    runs_by_value: dict[object, list[Run]] = field(default_factory=dict)
    stats: dict = field(default_factory=dict)
    pattern_tag: str = "stable"

    @property
    def duration(self) -> float:
        return max(0.0, self.t_end - self.t_start)

    @property
    def edge_rate(self) -> float:
        """Transitions per second across the observed span."""
        return len(self.edges) / self.duration if self.duration > 0 else 0.0

    def min_run_duration(self, value: object) -> Optional[float]:
        runs = self.runs_by_value.get(value, [])
        if not runs:
            return None
        return min(r.duration for r in runs)

    def max_run_duration(self, value: object) -> Optional[float]:
        runs = self.runs_by_value.get(value, [])
        if not runs:
            return None
        return max(r.duration for r in runs)

    def total_time_at(self, value: object) -> float:
        return sum(r.duration for r in self.runs_by_value.get(value, []))

    def brief_runs_at(self, value: object, threshold_sec: float) -> list[Run]:
        """Return every run of ``value`` whose duration is < ``threshold_sec``."""
        return [r for r in self.runs_by_value.get(value, []) if r.duration < threshold_sec]

    def to_dict(self) -> dict:
        return {
            "signal_name": self.signal_name,
            "sample_count": self.sample_count,
            "span_sec": round(self.duration, 3),
            "t_start": round(self.t_start, 3),
            "t_end": round(self.t_end, 3),
            "value_distribution": {str(k): v for k, v in self.value_distribution.items()},
            "edge_count": len(self.edges),
            "edge_rate_hz": round(self.edge_rate, 3),
            "edges_preview": [
                {"t": round(e.t, 3), "from": e.from_val, "to": e.to_val}
                for e in self.edges[:20]
            ],
            "runs_preview": [
                {"value": r.value, "t_start": round(r.t_start, 3),
                 "t_end": round(r.t_end, 3), "duration_ms": round(r.duration * 1000, 1)}
                for r in self.runs[:20]
            ],
            "stats": self.stats,
            "pattern_tag": self.pattern_tag,
        }


# ── Analyzer ─────────────────────────────────────────────────────────────


class TemporalAnalyzer:
    """
    Derives :class:`TemporalFeature` objects from raw signal timelines.

    The analyser itself has no I/O; helper methods are provided to pull
    timelines from a ``FrameStore`` so callers can stay concise.
    """

    BRIEF_PULSE_THRESHOLD_SEC = 0.5
    HIGH_EDGE_RATE_HZ = 2.0

    def analyze(self, timeline: SignalTimeline) -> Optional[TemporalFeature]:
        """Return a :class:`TemporalFeature` or ``None`` if the timeline is empty."""
        if timeline.is_empty():
            return None

        samples = sorted(timeline.samples, key=lambda tv: tv[0])
        t_first = samples[0][0]
        t_last = samples[-1][0]

        edges, runs = self._runs_and_edges(samples, t_last)
        runs_by_value: dict[object, list[Run]] = {}
        for r in runs:
            runs_by_value.setdefault(r.value, []).append(r)

        distribution: dict[object, int] = dict(Counter(v for _, v in samples))

        stats = self._compute_stats(runs, runs_by_value, distribution, len(samples))
        pattern_tag = self._classify_pattern(runs, runs_by_value, stats,
                                             span=t_last - t_first)

        return TemporalFeature(
            signal_name=timeline.name,
            sample_count=len(samples),
            t_start=t_first,
            t_end=t_last,
            value_distribution=distribution,
            edges=edges,
            runs=runs,
            runs_by_value=runs_by_value,
            stats=stats,
            pattern_tag=pattern_tag,
        )

    @staticmethod
    def _runs_and_edges(
        samples: list[tuple[float, object]], t_last: float,
    ) -> tuple[list[Edge], list[Run]]:
        """Walk the timeline once, emitting runs and the edges between them."""
        edges: list[Edge] = []
        runs: list[Run] = []

        run_value = samples[0][1]
        run_start = samples[0][0]
        prev_t = samples[0][0]

        for t, v in samples[1:]:
            if v != run_value:
                runs.append(Run(value=run_value, t_start=run_start, t_end=t))
                edges.append(Edge(t=t, from_val=run_value, to_val=v))
                run_value = v
                run_start = t
            prev_t = t

        runs.append(Run(value=run_value, t_start=run_start, t_end=max(prev_t, t_last)))
        return edges, runs

    def _compute_stats(
        self, runs: list[Run], runs_by_value: dict[object, list[Run]],
        distribution: dict[object, int], sample_count: int,
    ) -> dict:
        stats: dict = {
            "edge_count": max(0, len(runs) - 1),
            "run_count": len(runs),
            "run_durations_ms": {
                "min": round(min(r.duration for r in runs) * 1000, 1),
                "max": round(max(r.duration for r in runs) * 1000, 1),
                "median": round(_median([r.duration for r in runs]) * 1000, 1),
            },
        }

        per_value: dict = {}
        for value, group in runs_by_value.items():
            durations = [r.duration for r in group]
            per_value[str(value)] = {
                "run_count": len(group),
                "total_sec": round(sum(durations), 3),
                "min_ms": round(min(durations) * 1000, 1),
                "max_ms": round(max(durations) * 1000, 1),
                "median_ms": round(_median(durations) * 1000, 1),
                "frame_count": distribution.get(value, 0),
            }
        stats["per_value"] = per_value

        brief_pulses = {}
        for value, group in runs_by_value.items():
            short = [r for r in group if r.duration < self.BRIEF_PULSE_THRESHOLD_SEC]
            if short:
                brief_pulses[str(value)] = {
                    "count": len(short),
                    "shortest_ms": round(min(r.duration for r in short) * 1000, 1),
                    "shortest_at_t": round(min(short, key=lambda r: r.duration).t_start, 3),
                }
        if brief_pulses:
            stats["brief_pulses"] = brief_pulses

        return stats

    def _classify_pattern(
        self, runs: list[Run], runs_by_value: dict[object, list[Run]],
        stats: dict, span: float,
    ) -> str:
        """Return a coarse human-readable tag describing the time-series shape."""
        if len(runs) <= 1:
            return "stable"

        edge_rate = (len(runs) - 1) / span if span > 0 else 0.0
        if edge_rate >= self.HIGH_EDGE_RATE_HZ:
            return "oscillating"

        if "brief_pulses" in stats:
            pulse_total = sum(info["count"] for info in stats["brief_pulses"].values())
            if pulse_total >= 1 and len(runs_by_value) >= 2:
                return "brief_pulses"

        if len(runs_by_value) == 2 and edge_rate > 0.1:
            return "edge_dominated"

        return "stable"

    # ── Convenience loaders ──────────────────────────────────────────────

    @staticmethod
    def load_can_signal(store, message_name: str, signal_name: str) -> SignalTimeline:
        """Build a :class:`SignalTimeline` for a CAN signal via ``FrameStore``."""
        frames = store.query_can_by_name(message_name)
        samples: list[tuple[float, object]] = []
        for f in frames:
            sigs = f.get("signals", {})
            if signal_name in sigs and sigs[signal_name] is not None:
                samples.append((f["timestamp"], sigs[signal_name]))
        return SignalTimeline(name=f"{message_name}.{signal_name}", samples=samples)

    @staticmethod
    def load_bag_field(
        store, topic: str, field_name: str,
        time_start_ns: Optional[int] = None,
        time_end_ns: Optional[int] = None,
    ) -> SignalTimeline:
        """Build a :class:`SignalTimeline` from a ROS bag topic field."""
        frames = store.query_bag_by_topic(topic, time_start_ns, time_end_ns)
        samples: list[tuple[float, object]] = []
        for f in frames:
            fields = f.get("fields", {})
            if field_name in fields and fields[field_name] is not None:
                samples.append((f["timestamp_sec"], fields[field_name]))
        return SignalTimeline(name=f"{topic}::{field_name}", samples=samples)

    def analyze_many(
        self, timelines: Iterable[SignalTimeline],
    ) -> dict[str, TemporalFeature]:
        """Analyse a batch of timelines; empty ones are silently dropped."""
        out: dict[str, TemporalFeature] = {}
        for tl in timelines:
            feat = self.analyze(tl)
            if feat is not None:
                out[tl.name] = feat
        return out

    def detect_threshold_crossings(
        self,
        timeline: SignalTimeline,
        threshold: float,
        direction: str = "either",
    ) -> list[dict]:
        """Detect threshold crossing points in a signal timeline.

        Args:
            timeline: Signal time series.
            threshold: Numeric threshold value.
            direction: "rising" (below→above), "falling" (above→below), or "either".

        Returns:
            List of dicts with crossing point details:
            [{t, from_val, to_val, direction, dwell_time_sec, ...}, ...]
        """
        if timeline.is_empty():
            return []

        samples = sorted(timeline.samples, key=lambda tv: tv[0])
        crossings: list[dict] = []

        for i in range(1, len(samples)):
            t_prev, v_prev = samples[i - 1]
            t_curr, v_curr = samples[i]

            # Only consider numeric values
            try:
                vp = float(v_prev)
                vc = float(v_curr)
            except (TypeError, ValueError):
                continue

            prev_above = vp >= threshold
            curr_above = vc >= threshold

            if prev_above == curr_above:
                continue  # No crossing

            if direction == "rising" and curr_above:
                # Was below, now above
                crossings.append({
                    "t": round(t_curr, 3),
                    "from_val": v_prev,
                    "to_val": v_curr,
                    "direction": "rising",
                    "signal_name": timeline.name,
                    "threshold": threshold,
                })
            elif direction == "falling" and not curr_above:
                # Was above, now below
                crossings.append({
                    "t": round(t_curr, 3),
                    "from_val": v_prev,
                    "to_val": v_curr,
                    "direction": "falling",
                    "signal_name": timeline.name,
                    "threshold": threshold,
                })
            elif direction == "either":
                dir_label = "rising" if curr_above else "falling"
                crossings.append({
                    "t": round(t_curr, 3),
                    "from_val": v_prev,
                    "to_val": v_curr,
                    "direction": dir_label,
                    "signal_name": timeline.name,
                    "threshold": threshold,
                })

        # Compute dwell time (time since last crossing or start)
        for idx, cx in enumerate(crossings):
            if idx == 0:
                cx["dwell_time_sec"] = round(cx["t"] - samples[0][0], 3)
            else:
                cx["dwell_time_sec"] = round(cx["t"] - crossings[idx - 1]["t"], 3)

        return crossings


# ── Helpers ──────────────────────────────────────────────────────────────


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def format_temporal_features(
    features: dict[str, TemporalFeature],
    highlight_value: object = 0,
    brief_threshold_ms: float = 500.0,
) -> str:
    """Compact human-readable summary suitable for expert prompts."""
    if not features:
        return "(无时序特征数据)"

    parts: list[str] = ["### 时序特征摘要"]
    for name, f in features.items():
        parts.append(
            f"\n**{name}** ({f.sample_count}帧, {f.duration:.1f}s跨度, "
            f"{len(f.edges)}次跳变, 模式={f.pattern_tag})"
        )
        parts.append(f"  值分布: { {str(k): v for k, v in f.value_distribution.items()} }")

        per_value = f.stats.get("per_value", {})
        for v_key, info in per_value.items():
            parts.append(
                f"  值={v_key}: {info['run_count']}段, "
                f"最短{info['min_ms']}ms / 中位{info['median_ms']}ms / 最长{info['max_ms']}ms, "
                f"累计{info['total_sec']}s ({info['frame_count']}帧)"
            )

        brief = f.stats.get("brief_pulses", {})
        if brief:
            pulses_desc = ", ".join(
                f"值={k}出现{v['count']}次短脉冲(最短{v['shortest_ms']}ms @ t={v['shortest_at_t']}s)"
                for k, v in brief.items()
            )
            parts.append(f"  ⚠ 短脉冲(<{brief_threshold_ms}ms): {pulses_desc}")

        if f.edges:
            preview = ", ".join(
                f"t={e.t:.2f}s({e.from_val}→{e.to_val})" for e in f.edges[:6]
            )
            if len(f.edges) > 6:
                preview += f", ...+{len(f.edges)-6}"
            parts.append(f"  前几次跳变: {preview}")

    return "\n".join(parts)


def dump_features_json(features: dict[str, TemporalFeature]) -> str:
    """Debug helper: serialise all features to a JSON string."""
    return json.dumps(
        {name: f.to_dict() for name, f in features.items()},
        ensure_ascii=False, indent=2, default=str,
    )
