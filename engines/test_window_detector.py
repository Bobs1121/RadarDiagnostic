# -*- coding: utf-8 -*-
"""
Test Window Detector: automatically locates the time period when the
actual test case was triggered within a long bag recording.

Pure data-driven — no AI calls. Uses rule-based edge detection on
egoCarInfo fields (speed, state machine, target tracks, warnings).
"""
from __future__ import annotations

from dataclasses import dataclass, field as dc_field

from ai.utils import get_func_fields


@dataclass
class TestEvent:
    """A single detected event in the time series."""
    t: float
    event_type: str        # "target_appear", "state_change", "speed_enter", "warning_on", etc.
    detail: str

@dataclass
class TestWindow:
    """A detected test-active time window."""
    t_start: float
    t_end: float
    trigger_reason: str
    events: list[TestEvent] = dc_field(default_factory=list)

    @property
    def duration(self) -> float:
        return self.t_end - self.t_start

    def contains(self, t: float) -> bool:
        return self.t_start <= t <= self.t_end

_PADDING_SEC = 2.0
_MIN_TARGET_FRAMES = 3
_TARGET_VEL_THRESH = 0.5     # m/s — any track with |vel_x| above this is "present"
_TARGET_DIST_THRESH = 0.3    # m
_FALLBACK_WINDOW_SEC = 10.0

_GENERIC_SPEED_THRESHOLDS = [0.5, 5.0, 10.0, 21.0]


class TestWindowDetector:
    """Detect test-active windows from a FrameStore's egoCarInfo data."""

    def detect(
        self,
        store,
        func_name: str,
        speed_thresholds: list[float] | None = None,
    ) -> list[TestWindow]:
        """
        Main entry: returns a list of TestWindow sorted by t_start.
        Uses egoCarInfo events + warning_events table + radar_objects approach events.

        ``speed_thresholds`` can be supplied by the caller (e.g. derived from
        ``source_docs/{FUNC}_conditions.json``) so that BSD/RCTB/… get their
        own activation bands instead of the FCT-centric generic list.
        """
        func_name = func_name.upper()
        fmap = get_func_fields(func_name)

        thresholds = list(speed_thresholds) if speed_thresholds else list(_GENERIC_SPEED_THRESHOLDS)
        thresholds = sorted({round(float(v), 3) for v in thresholds if v is not None})

        all_events: list[TestEvent] = []

        for topic in fmap.get("ego_topics", []):
            frames = store.query_bag_by_topic(topic)
            if not frames:
                continue
            series = self._build_series(frames, fmap)
            if not series:
                continue

            all_events.extend(self._detect_target_events(series))
            all_events.extend(self._detect_state_transitions(series, fmap))
            all_events.extend(self._detect_warning_events(series, fmap))
            all_events.extend(self._detect_speed_events(series, thresholds))

        # P3-2: also use warning_events table for edge detection
        all_events.extend(self._detect_warning_edge_events(store, func_name))
        # P3-2: also detect rapid object approach from radar_objects
        all_events.extend(self._detect_object_approach_events(store, func_name))

        if not all_events:
            return self._fallback(store, fmap)

        all_events.sort(key=lambda e: e.t)
        windows = self._merge_events(all_events)

        if not windows:
            return self._fallback(store, fmap)

        return windows

    @staticmethod
    def _detect_warning_edge_events(store, func_name: str) -> list[TestEvent]:
        """Use warning_events table to generate TestEvents at flag edges."""
        events: list[TestEvent] = []
        try:
            w_events = store.query_warning_events(func_name)
        except Exception:
            return events
        for we in w_events:
            t_start_sec = we["start_ns"] / 1e9
            events.append(TestEvent(
                t=t_start_sec,
                event_type="warning_edge_on",
                detail=f"{func_name} obj_flag on (radar={we.get('radar_id')} obj={we.get('associated_obj_id')})",
            ))
            if we.get("end_ns"):
                events.append(TestEvent(
                    t=we["end_ns"] / 1e9,
                    event_type="warning_edge_off",
                    detail=f"{func_name} obj_flag off",
                ))
        return events

    @staticmethod
    def _detect_object_approach_events(store, func_name: str) -> list[TestEvent]:
        """Detect objects rapidly approaching (dist_x decreasing) in radar_objects."""
        events: list[TestEvent] = []
        try:
            warned = store.query_objects_with_warning(func_name)
        except Exception:
            return events
        if not warned:
            return events

        by_obj: dict[tuple, list] = {}
        for o in warned:
            key = (o["radar_id"], o["obj_id"])
            by_obj.setdefault(key, []).append(o)

        for key, frames in by_obj.items():
            if len(frames) < 2:
                continue
            frames.sort(key=lambda x: x["timestamp_ns"])
            first_dist = abs(frames[0].get("dist_x") or 999)
            last_dist = abs(frames[-1].get("dist_x") or 999)
            if first_dist > 1.0 and last_dist < first_dist * 0.5:
                t_sec = frames[len(frames) // 2]["timestamp_ns"] / 1e9
                events.append(TestEvent(
                    t=t_sec,
                    event_type="object_approach",
                    detail=f"obj {key[1]} radar {key[0]}: dist {first_dist:.1f}→{last_dist:.1f}m",
                ))
        return events

    # ── Series Builder ───────────────────────────────────────────────────

    @staticmethod
    def _build_series(frames: list[dict], fmap: dict | None = None) -> list[dict]:
        """Extract compact time series from raw frame dicts."""
        extra_keys = set()
        if fmap:
            if fmap.get("state"):
                extra_keys.add(fmap["state"])
            if fmap.get("enable"):
                extra_keys.add(fmap["enable"])
            for w in fmap.get("warnings", []):
                extra_keys.add(w)

        series = []
        for f in frames:
            fields = f.get("fields", {})
            if not fields:
                continue
            row = {"t": f.get("timestamp_sec", 0.0)}
            row["car_spd"] = fields.get("car_spd", 0.0)
            row["actual_gear"] = fields.get("actual_gear")
            for k in extra_keys:
                row[k] = fields.get(k, 0)
            for i in range(4):
                row[f"trc_{i}_vel_x"] = fields.get(f"trc_{i}_vel_x", 0.0)
                row[f"trc_{i}_dist_x"] = fields.get(f"trc_{i}_dist_x", 0.0)
                row[f"trc_{i}_dist_y"] = fields.get(f"trc_{i}_dist_y", 0.0)
            series.append(row)
        return series

    # ── Event Detectors ──────────────────────────────────────────────────

    @staticmethod
    def _detect_target_events(series: list[dict]) -> list[TestEvent]:
        """Detect when a target track appears or disappears."""
        events: list[TestEvent] = []
        for i in range(4):
            vk, dk = f"trc_{i}_vel_x", f"trc_{i}_dist_x"
            prev_present = False
            run_start = 0.0
            run_len = 0
            for row in series:
                vel = abs(row.get(vk, 0.0) or 0.0)
                dist = abs(row.get(dk, 0.0) or 0.0)
                cur_present = vel > _TARGET_VEL_THRESH or dist > _TARGET_DIST_THRESH
                if cur_present and not prev_present:
                    run_start = row["t"]
                    run_len = 1
                elif cur_present and prev_present:
                    run_len += 1
                elif not cur_present and prev_present:
                    if run_len >= _MIN_TARGET_FRAMES:
                        events.append(TestEvent(
                            t=run_start,
                            event_type="target_appear",
                            detail=f"trc_{i} appeared (持续{run_len}帧)",
                        ))
                        events.append(TestEvent(
                            t=row["t"],
                            event_type="target_disappear",
                            detail=f"trc_{i} disappeared",
                        ))
                    run_len = 0
                prev_present = cur_present
            if prev_present and run_len >= _MIN_TARGET_FRAMES:
                events.append(TestEvent(
                    t=run_start,
                    event_type="target_appear",
                    detail=f"trc_{i} appeared (持续{run_len}帧到结尾)",
                ))
        return events

    @staticmethod
    def _detect_state_transitions(series: list[dict], fmap: dict) -> list[TestEvent]:
        state_key = fmap.get("state", "fcta_system_state")
        events: list[TestEvent] = []
        prev_state = None
        for row in series:
            st = row.get(state_key)
            if st is None:
                continue
            if prev_state is not None and st != prev_state:
                events.append(TestEvent(
                    t=row["t"],
                    event_type="state_change",
                    detail=f"{state_key}: {prev_state}→{st}",
                ))
            prev_state = st
        return events

    @staticmethod
    def _detect_warning_events(series: list[dict], fmap: dict) -> list[TestEvent]:
        events: list[TestEvent] = []
        for wk in fmap.get("warnings", []):
            prev_val = 0
            for row in series:
                val = row.get(wk, 0) or 0
                if val != prev_val:
                    direction = "on" if val > prev_val else "off"
                    events.append(TestEvent(
                        t=row["t"],
                        event_type=f"warning_{direction}",
                        detail=f"{wk}: {prev_val}→{val}",
                    ))
                prev_val = val
        return events

    @staticmethod
    def _detect_speed_events(
        series: list[dict], thresholds: list[float],
    ) -> list[TestEvent]:
        """Detect when car_spd crosses per-function activation thresholds."""
        events: list[TestEvent] = []
        prev_spd = None
        for row in series:
            spd = row.get("car_spd", 0.0) or 0.0
            if prev_spd is not None:
                for th in thresholds:
                    crossed_up = prev_spd < th and spd >= th
                    crossed_down = prev_spd >= th and spd < th
                    if crossed_up or crossed_down:
                        d = "↑" if crossed_up else "↓"
                        events.append(TestEvent(
                            t=row["t"],
                            event_type="speed_cross",
                            detail=f"car_spd {d} {th} km/h ({prev_spd:.2f}→{spd:.2f})",
                        ))
            prev_spd = spd
        return events

    # ── Merge & Fallback ─────────────────────────────────────────────────

    @staticmethod
    def _merge_events(events: list[TestEvent]) -> list[TestWindow]:
        """Merge nearby events into windows with padding."""
        if not events:
            return []

        intervals: list[tuple[float, float, list[TestEvent]]] = []
        for ev in events:
            t0 = ev.t - _PADDING_SEC
            t1 = ev.t + _PADDING_SEC
            merged = False
            for idx, (s, e, evts) in enumerate(intervals):
                if t0 <= e and t1 >= s:
                    intervals[idx] = (min(s, t0), max(e, t1), evts + [ev])
                    merged = True
                    break
            if not merged:
                intervals.append((t0, t1, [ev]))

        # Second pass: merge overlapping intervals
        intervals.sort(key=lambda x: x[0])
        merged: list[tuple[float, float, list[TestEvent]]] = [intervals[0]]
        for s, e, evts in intervals[1:]:
            ps, pe, pevts = merged[-1]
            if s <= pe:
                merged[-1] = (ps, max(pe, e), pevts + evts)
            else:
                merged.append((s, e, evts))

        windows = []
        for s, e, evts in merged:
            reasons = set()
            for ev in evts:
                if ev.event_type == "target_appear":
                    reasons.add("目标出现")
                elif ev.event_type == "state_change":
                    reasons.add("状态跳变")
                elif ev.event_type.startswith("warning"):
                    reasons.add("报警变化")
                elif ev.event_type == "speed_cross":
                    reasons.add("速度变化")
            windows.append(TestWindow(
                t_start=max(0, s),
                t_end=e,
                trigger_reason=" + ".join(sorted(reasons)) or "事件检测",
                events=evts,
            ))
        return windows

    def _fallback(self, store, fmap: dict | None = None) -> list[TestWindow]:
        """When no events found, pick the densest target-present interval."""
        topics = (fmap or {}).get("ego_topics", [
            "/wf/ego_car_info/front_left/parsed",
            "/wf/ego_car_info/front_right/parsed",
        ])
        for topic in topics:
            frames = store.query_bag_by_topic(topic)
            if not frames:
                continue
            series = self._build_series(frames)
            if not series:
                continue

            # Find the region with most non-zero target tracks
            best_score, best_t = 0, series[len(series) // 2]["t"]
            for row in series:
                score = sum(
                    1 for i in range(4)
                    if abs(row.get(f"trc_{i}_vel_x", 0) or 0) > _TARGET_VEL_THRESH
                )
                if score > best_score:
                    best_score = score
                    best_t = row["t"]

            if best_score > 0:
                half = _FALLBACK_WINDOW_SEC / 2
                return [TestWindow(
                    t_start=max(0, best_t - half),
                    t_end=best_t + half,
                    trigger_reason=f"fallback: 目标密度最高区域 (score={best_score})",
                    events=[],
                )]

            # Last resort: middle 10 seconds
            t0 = series[0]["t"]
            t1 = series[-1]["t"]
            mid = (t0 + t1) / 2
            half = min(_FALLBACK_WINDOW_SEC / 2, (t1 - t0) / 2)
            return [TestWindow(
                t_start=mid - half,
                t_end=mid + half,
                trigger_reason="fallback: 数据中段",
                events=[],
            )]

        return []


# ── Formatting Helpers (for orchestrator / expert panel) ─────────────

def format_windows(windows: list[TestWindow]) -> str:
    """Format windows into a compact text block."""
    if not windows:
        return "(未检测到测试窗口)"
    parts = []
    for i, w in enumerate(windows):
        parts.append(
            f"窗口{i+1}: [{w.t_start:.2f}s ~ {w.t_end:.2f}s] "
            f"({w.duration:.1f}s) — {w.trigger_reason}"
        )
        if w.events:
            for ev in w.events[:15]:
                parts.append(f"  t={ev.t:.2f}s {ev.event_type}: {ev.detail}")
            if len(w.events) > 15:
                parts.append(f"  ... +{len(w.events)-15} more events")
    return "\n".join(parts)
