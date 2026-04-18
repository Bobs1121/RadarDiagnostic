# -*- coding: utf-8 -*-
"""
Frame-by-frame analyzer: tracks key variable changes over time,
detects anomalies, and builds variable change timelines.

V2: Accepts TestWindow list to focus extraction on test-active periods.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Optional

from .model_router import ModelRouter
from .test_window_detector import TestWindow
from .utils import get_func_fields


class FrameAnalyzer:
    """Analyze frame-by-frame data and track key variable changes."""

    def __init__(self, router: ModelRouter, variables_path: Optional[str | Path] = None):
        self.router = router
        self.variables = []
        if variables_path:
            p = Path(variables_path)
            if p.exists():
                self.variables = json.loads(p.read_text(encoding="utf-8"))

    def get_variables_for_function(self, func_name: str) -> list[dict]:
        return [
            v for v in self.variables
            if v.get("function", "").upper() == func_name.upper()
            or v.get("function", "").upper() == "COMMON"
        ]

    def analyze_bag_timeline(
        self, store, topic: str, func_name: Optional[str] = None,
    ) -> dict:
        """Analyze a bag topic's data over time, detecting state changes."""
        frames = store.query_bag_by_topic(topic)
        if not frames:
            return {"error": f"No frames found for topic {topic}"}

        prev_fields = None
        changes = []
        for frame in frames:
            fields = frame.get("fields", {})
            ts = frame.get("timestamp_sec", 0)
            if prev_fields is not None:
                diffs = self._detect_changes(prev_fields, fields)
                if diffs:
                    changes.append({"timestamp": ts, "changes": diffs})
            prev_fields = fields

        return {
            "topic": topic,
            "frame_count": len(frames),
            "change_count": len(changes),
            "changes": changes,
            "time_range": {
                "start": frames[0].get("timestamp_sec"),
                "end": frames[-1].get("timestamp_sec"),
            },
        }

    _COMMON_DIAG_FIELDS = [
        "car_spd", "actual_gear", "sys_power_mod", "steer_angle", "yaw_rate",
    ]
    _COMMON_TRC_FIELDS = ["dist_x", "dist_y", "vel_x", "ttc", "ddci"]

    @staticmethod
    def _get_diag_fields(func_name: str) -> list[str]:
        fmap = get_func_fields(func_name)
        fields = list(FrameAnalyzer._COMMON_DIAG_FIELDS)
        for k in ["state", "enable", "enable_cap", "error_status"]:
            if fmap.get(k):
                fields.append(fmap[k])
        fields.extend(fmap.get("warnings", []))
        return fields

    @staticmethod
    def _get_trc_diag_fields(func_name: str) -> list[str]:
        fmap = get_func_fields(func_name)
        fields = list(FrameAnalyzer._COMMON_TRC_FIELDS)
        if fmap.get("obj_warning_flag"):
            fields.append(fmap["obj_warning_flag"])
        return fields

    @staticmethod
    def _get_state_fields(func_name: str) -> list[str]:
        fmap = get_func_fields(func_name)
        fields = []
        for k in ["state", "enable"]:
            if fmap.get(k):
                fields.append(fmap[k])
        fields.extend(fmap.get("warnings", []))
        return fields

    # ── Main evidence extraction (V2 — window-aware) ─────────────────────

    def extract_evidence(
        self,
        store,
        func_name: str,
        windows: Optional[list[TestWindow]] = None,
    ) -> dict:
        """
        Extract concrete numeric evidence from data.
        If `windows` is provided, only frames within those windows are analyzed
        (full resolution, no subsampling). Otherwise falls back to uniform sampling.
        """
        evidence: dict = {}

        if windows:
            evidence["test_windows"] = [
                {"t_start": round(w.t_start, 2), "t_end": round(w.t_end, 2),
                 "duration": round(w.duration, 1), "reason": w.trigger_reason}
                for w in windows
            ]

        # 1. Warning state changes (compact)
        self._extract_warnings(store, evidence, windows)

        # 2. EgoCarInfo — the most important data source
        all_timeline: list[dict] = []
        all_transitions: list[dict] = []

        fmap = get_func_fields(func_name)
        ego_topics = fmap.get("ego_topics", [])
        for topic in ego_topics:
            side = topic.split("/")[-2] if "/" in topic else "unknown"
            if windows:
                ego_frames = self._query_windowed(store, topic, windows)
            else:
                ego_frames = store.query_bag_by_topic(topic)
            if not ego_frames:
                continue

            samples, transitions = self._extract_from_frames(
                ego_frames, side, windows is not None, func_name,
            )
            evidence[f"ego_{side}"] = samples
            all_timeline.extend(samples)
            all_transitions.extend(transitions)

            self._compute_stats(evidence, samples, side)

        all_timeline.sort(key=lambda s: s["t"])
        evidence["timeline"] = all_timeline
        evidence["state_transitions"] = all_transitions

        # 3. Radar object evidence (from radar_objects table)
        self._extract_object_evidence(store, evidence, func_name, windows)

        # 4. Radar debug / ADAS enable evidence
        self._extract_debug_evidence(store, evidence, windows)

        # 5. Warning events summary
        self._extract_warning_events(store, evidence, func_name)

        # 6. CAN signal summary (compact)
        can_ids_info = store.get_can_ids()
        if can_ids_info:
            evidence["can_summary"] = [
                {"id": c["can_id_hex"], "name": c.get("message_name", "?"), "count": c["count"]}
                for c in can_ids_info[:15]
            ]

        # 7. Build key facts summary
        evidence["KEY_FACTS"] = self._build_key_facts(evidence, windows, func_name)

        # 8. TPE placeholder — orchestrator fills this after Phase 3.6.
        # Downstream consumers should treat missing ``tpe_report`` as
        # "TPE did not run" rather than "no patterns found"; the engine
        # must be explicitly invoked to emit evidence here.
        evidence.setdefault("tpe_report", None)
        evidence.setdefault("tpe_block", None)
        return evidence

    @staticmethod
    def append_tpe_block(evidence: dict, tpe_block: str, tpe_report: dict) -> None:
        """
        Splice a TPE narration into ``evidence['KEY_FACTS']`` and keep the
        structured report around for anyone who needs it.
        """
        if not tpe_block:
            return
        current = evidence.get("KEY_FACTS") or ""
        separator = "\n\n" + "=" * 50 + "\n"
        evidence["KEY_FACTS"] = current + separator + tpe_block
        evidence["tpe_block"] = tpe_block
        evidence["tpe_report"] = tpe_report

    # ── Radar object / debug evidence ────────────────────────────────────

    @staticmethod
    def _extract_object_evidence(store, evidence: dict, func_name: str, windows):
        """Add per-object warning snapshots from radar_objects table."""
        try:
            warned_objs = store.query_objects_with_warning(func_name)
        except Exception:
            return
        if not warned_objs:
            evidence["radar_objects_summary"] = {"warned_count": 0}
            return

        snapshots = []
        for o in warned_objs[:200]:
            snapshots.append({
                "t_ns": o["timestamp_ns"],
                "t_sec": round(o["timestamp_ns"] / 1e9, 3),
                "radar": o["radar_id"],
                "obj_id": o["obj_id"],
                "dist_x": o.get("dist_x"),
                "dist_y": o.get("dist_y"),
                "vel_abs_x": o.get("vel_abs_x"),
                "ttc": o.get("ttc"),
                "ddci": o.get("ddci"),
            })

        evidence["radar_objects_warned"] = snapshots[:100]
        evidence["radar_objects_summary"] = {
            "warned_count": len(warned_objs),
            "radars_involved": list({o["radar_id"] for o in warned_objs}),
            "obj_ids_involved": list({o["obj_id"] for o in warned_objs[:100]}),
        }

        if snapshots:
            ttcs = [s["ttc"] for s in snapshots if s["ttc"] is not None and s["ttc"] != 0]
            dists = [abs(s["dist_x"]) for s in snapshots if s["dist_x"] is not None]
            if ttcs:
                evidence["radar_objects_summary"]["ttc_range"] = [
                    round(min(ttcs), 2), round(max(ttcs), 2)
                ]
            if dists:
                evidence["radar_objects_summary"]["dist_range"] = [
                    round(min(dists), 2), round(max(dists), 2)
                ]

    @staticmethod
    def _extract_debug_evidence(store, evidence: dict, windows):
        """Add ADAS enable states and BLD info from radar_debug table."""
        try:
            if windows:
                dbg_rows = []
                for w in windows:
                    chunk = store.query_debug_in_window(
                        int(w.t_start * 1e9), int(w.t_end * 1e9)
                    )
                    dbg_rows.extend(chunk)
            else:
                dbg_rows = store.query_debug_in_window(0, int(9e18))
        except Exception:
            return
        if not dbg_rows:
            return

        adas_summary: dict[str, set] = {}
        bld_flags: list = []
        for d in dbg_rows:
            for func in ("bsd", "lca", "dow", "rcw", "rcta", "rctb", "fcta", "fctb"):
                col = f"{func}_enable"
                val = d.get(col)
                if val is not None:
                    adas_summary.setdefault(func, set()).add(int(val))
            if d.get("bld_warning_flag"):
                bld_flags.append(d["bld_warning_flag"])

        evidence["adas_enable_states"] = {
            k: sorted(v) for k, v in adas_summary.items()
        }
        if bld_flags:
            evidence["bld_summary"] = {
                "triggered_count": sum(1 for f in bld_flags if f != 0),
                "total_samples": len(dbg_rows),
            }

    @staticmethod
    def _extract_warning_events(store, evidence: dict, func_name: str):
        """Add warning event summaries from warning_events table."""
        try:
            events = store.query_warning_events(func_name)
        except Exception:
            return
        if not events:
            return
        evidence["warning_events"] = [
            {
                "radar": e["radar_id"],
                "obj_id": e.get("associated_obj_id"),
                "start_sec": round(e["start_ns"] / 1e9, 3),
                "end_sec": round(e["end_ns"] / 1e9, 3) if e.get("end_ns") else None,
                "duration_ms": e.get("duration_ms"),
                "min_dist": e.get("min_dist"),
                "max_ttc": e.get("max_ttc"),
            }
            for e in events[:50]
        ]

    # ── Internal helpers ─────────────────────────────────────────────────

    @staticmethod
    def _query_windowed(store, topic: str, windows: list[TestWindow]) -> list[dict]:
        """Query frames within all windows (no subsampling)."""
        frames: list[dict] = []
        for w in windows:
            t_start_ns = int(w.t_start * 1e9)
            t_end_ns = int(w.t_end * 1e9)
            chunk = store.query_bag_by_topic(topic, time_start_ns=t_start_ns, time_end_ns=t_end_ns)
            frames.extend(chunk)
        # Deduplicate by timestamp_ns (windows might overlap)
        seen = set()
        unique = []
        for f in frames:
            ts = f.get("timestamp_ns", 0)
            if ts not in seen:
                seen.add(ts)
                unique.append(f)
        unique.sort(key=lambda f: f.get("timestamp_ns", 0))
        return unique

    def _extract_from_frames(
        self,
        ego_frames: list[dict],
        side: str,
        full_resolution: bool,
        func_name: str,
    ) -> tuple[list[dict], list[dict]]:
        """
        Extract diagnostic samples and state transitions from frames.
        If full_resolution, keep all frames; otherwise subsample to ~50.
        """
        diag_fields = self._get_diag_fields(func_name)
        trc_fields = self._get_trc_diag_fields(func_name)
        state_fields = self._get_state_fields(func_name)

        if full_resolution:
            frame_iter = ego_frames
        else:
            step = max(1, len(ego_frames) // 50)
            frame_iter = ego_frames[::step][:50]

        samples: list[dict] = []
        transitions: list[dict] = []
        prev_states: dict = {}

        for f in frame_iter:
            fields = f.get("fields", {})
            sample = {"t": round(f["timestamp_sec"], 3), "side": side}

            for key in diag_fields:
                if key in fields:
                    sample[key] = fields[key]

            for i in range(4):
                prefix = f"trc_{i}_"
                vel_x = fields.get(f"{prefix}vel_x", 0) or 0
                dist_x = fields.get(f"{prefix}dist_x", 0) or 0
                if abs(vel_x) > 0.1 or abs(dist_x) > 0.1:
                    for fld in trc_fields:
                        k = f"{prefix}{fld}"
                        if k in fields:
                            sample[k] = fields[k]

            samples.append(sample)

            for sk in state_fields:
                cur_val = fields.get(sk)
                if cur_val is None:
                    continue
                prev_val = prev_states.get(sk)
                if prev_val is not None and cur_val != prev_val:
                    transitions.append({
                        "t": round(f["timestamp_sec"], 3),
                        "side": side,
                        "field": sk,
                        "from": prev_val,
                        "to": cur_val,
                    })
                prev_states[sk] = cur_val

        return samples, transitions

    def _extract_warnings(self, store, evidence: dict, windows: Optional[list[TestWindow]]):
        """Extract warning state data (compact)."""
        if windows:
            warnings = self._query_windowed(store, "/corner_radar/warning_status_raw", windows)
        else:
            warnings = store.query_bag_by_topic("/corner_radar/warning_status_raw")
        if not warnings:
            return

        states = []
        for w in warnings:
            wb = w.get("fields", {}).get("warning_bytes", [])
            states.append({"t": round(w["timestamp_sec"], 3), "bytes": wb[:20]})

        if len(states) > 60:
            step = max(1, len(states) // 60)
            states = states[::step][:60]

        evidence["warning_states"] = {
            "total_frames": len(warnings),
            "sampled": states,
        }

    def _compute_stats(self, evidence: dict, samples: list[dict], side: str):
        car_spds = [s.get("car_spd", 0) for s in samples if "car_spd" in s]
        if car_spds:
            evidence[f"ego_{side}_stats"] = {
                "car_spd_min": round(min(car_spds), 2),
                "car_spd_max": round(max(car_spds), 2),
                "car_spd_avg": round(sum(car_spds) / len(car_spds), 2),
            }
        for i in range(4):
            vels = [s.get(f"trc_{i}_vel_x", 0) for s in samples if f"trc_{i}_vel_x" in s]
            if vels and any(abs(v) > 0.1 for v in vels):
                evidence[f"trc_{i}_stats_{side}"] = {
                    "vel_x_min": round(min(vels), 2),
                    "vel_x_max": round(max(vels), 2),
                    "vel_x_avg": round(sum(vels) / len(vels), 2),
                    "nonzero_frames": sum(1 for v in vels if abs(v) > 0.1),
                }

    def _build_key_facts(
        self, evidence: dict, windows: Optional[list[TestWindow]],
        func_name: str,
    ) -> str:
        """Build structured key facts from evidence — window-aware, function-aware."""
        fmap = get_func_fields(func_name)
        state_key = fmap.get("state", "")
        enable_key = fmap.get("enable", "")
        warning_keys = fmap.get("warnings", [])
        obj_wflag = fmap.get("obj_warning_flag", "")
        side_prefix = fmap.get("side_prefix", "front")

        facts: list[str] = []

        if windows:
            for i, w_info in enumerate(evidence.get("test_windows", [])):
                facts.append(
                    f"[窗口{i+1}] {w_info['t_start']}s ~ {w_info['t_end']}s "
                    f"({w_info['duration']}s) — {w_info['reason']}"
                )
        else:
            facts.append("[全段数据] (未检测到窗口，使用均匀抽样)")

        transitions = evidence.get("state_transitions", [])
        if transitions:
            facts.append(f"\n[状态跳变] ({len(transitions)}次)")
            for tr in transitions[:20]:
                facts.append(
                    f"  t={tr['t']}s {tr['side']} {tr['field']}: "
                    f"{tr['from']}→{tr['to']}"
                )
        else:
            facts.append("\n[状态跳变] 无")

        for side in [f"{side_prefix}_left", f"{side_prefix}_right"]:
            samples = evidence.get(f"ego_{side}", [])
            if not samples:
                continue

            facts.append(f"\n[{side}] ({len(samples)}帧)")

            spd_vals = [s["car_spd"] for s in samples if "car_spd" in s]
            if spd_vals:
                facts.append(
                    f"  car_spd: min={min(spd_vals):.3f}, max={max(spd_vals):.3f}, "
                    f"avg={sum(spd_vals)/len(spd_vals):.3f}"
                )

            if state_key:
                states = [s.get(state_key) for s in samples if state_key in s]
                if states:
                    sc = Counter(states)
                    facts.append(
                        f"  {state_key}: {dict(sc)} "
                        f"(0=None,1=Init,2=Standby,3=Active,4=Off,5=Failure,6=Passive)"
                    )

            if enable_key:
                enables = [s.get(enable_key) for s in samples if enable_key in s]
                if enables:
                    facts.append(f"  {enable_key}: {dict(Counter(enables))}")

            for wk in warning_keys:
                wvals = [s.get(wk) for s in samples if wk in s]
                if wvals:
                    facts.append(f"  {wk}: {dict(Counter(wvals))}")

            for i in range(4):
                trc_samples = [(s["t"], s.get(f"trc_{i}_vel_x", 0))
                               for s in samples if f"trc_{i}_vel_x" in s]
                if trc_samples and any(abs(v) > 0.1 for _, v in trc_samples):
                    active = [(t, v) for t, v in trc_samples if abs(v) > 0.1]
                    vels = [v for _, v in active]
                    times = [t for t, _ in active]
                    facts.append(
                        f"  trc_{i}: vel_x [{min(vels):.1f}, {max(vels):.1f}] m/s "
                        f"(≈{abs(min(vels))*3.6:.0f}~{abs(max(vels))*3.6:.0f} km/h), "
                        f"存在 {min(times):.2f}s~{max(times):.2f}s ({len(active)}帧)"
                    )

                    ttc_vals = [s.get(f"trc_{i}_ttc", 0) for s in samples
                                if f"trc_{i}_ttc" in s and abs(s.get(f"trc_{i}_vel_x", 0) or 0) > 0.1]
                    if ttc_vals:
                        facts.append(f"    ttc: [{min(ttc_vals):.2f}, {max(ttc_vals):.2f}]s")

                    dx_vals = [s.get(f"trc_{i}_dist_x", 0) for s in samples
                               if f"trc_{i}_dist_x" in s and abs(s.get(f"trc_{i}_vel_x", 0) or 0) > 0.1]
                    if dx_vals:
                        facts.append(f"    dist_x: [{min(dx_vals):.1f}, {max(dx_vals):.1f}]m")

                    if obj_wflag:
                        wflags = [s.get(f"trc_{i}_{obj_wflag}")
                                  for s in samples if f"trc_{i}_{obj_wflag}" in s]
                        if wflags and any(f != 0 for f in wflags):
                            facts.append(f"    {obj_wflag}: {dict(Counter(wflags))}")

        # ── Causal-layer evidence (clearly labeled) ──────────────────
        facts.append("\n" + "=" * 50)
        facts.append("[因果层次说明] 以下数据分为「观测层」和「配置层」，"
                     "根因分析必须沿因果链向上追溯：")
        facts.append("  观测层(雷达端) → 仅说明「发生了什么」")
        facts.append("  配置层(ECU端)  → 说明「为什么发生」→ 需追溯到代码逻辑")

        # Layer 1: Observations (radar-side, EFFECT not CAUSE)
        obj_summary = evidence.get("radar_objects_summary", {})
        if obj_summary.get("warned_count", 0) > 0:
            facts.append(f"\n[观测层·雷达目标告警] {func_name} 共{obj_summary['warned_count']}帧有告警")
            facts.append("  ⚠ 这是雷达输出的观测结果，不是ECU决策的原因")
            if obj_summary.get("radars_involved"):
                facts.append(f"  涉及雷达: {obj_summary['radars_involved']}")
            if obj_summary.get("ttc_range"):
                rng = obj_summary["ttc_range"]
                facts.append(f"  TTC范围: [{rng[0]}, {rng[1]}]s")
            if obj_summary.get("dist_range"):
                rng = obj_summary["dist_range"]
                facts.append(f"  距离范围: [{rng[0]}, {rng[1]}]m")

        w_events = evidence.get("warning_events", [])
        if w_events:
            facts.append(f"\n[观测层·告警事件] {len(w_events)}个事件段")
            for we in w_events[:5]:
                dur = f"{we['duration_ms']:.0f}ms" if we.get("duration_ms") else "?"
                facts.append(
                    f"  radar={we['radar']} obj={we.get('obj_id')} "
                    f"t={we['start_sec']}~{we.get('end_sec','?')}s ({dur}) "
                    f"min_d={we.get('min_dist')} max_ttc={we.get('max_ttc')}"
                )

        # Layer 2: Configuration/state (ECU-side, closer to root cause)
        adas_en = evidence.get("adas_enable_states", {})
        if adas_en:
            fn_lower = func_name.lower()
            facts.append(f"\n[配置层·ADAS使能] (来自wfAutosarData outputData内嵌调试信息)")
            facts.append("  ⚠ 使能状态是ECU内部决策的结果，需追溯：哪段代码/信号导致了此状态？")
            if fn_lower in adas_en:
                vals = adas_en[fn_lower]
                status_str = "启用" if vals == [1] else ("禁用" if vals == [0] else f"混合{vals}")
                facts.append(f"  {func_name}: {status_str}")
            disabled = [k for k, v in adas_en.items() if v == [0]]
            if disabled:
                facts.append(f"  被禁用的功能: {', '.join(disabled)}")
            facts.append("  → 追溯方向: ASWIN_SystemState.c 中的使能判定 ← RteComMapping 的CAN信号")

        return "\n".join(facts) if facts else "(no egoCarInfo data)"

    # ── Timeline formatting for experts ──────────────────────────────────

    @staticmethod
    def format_timeline(
        timeline: list[dict], max_lines: int = 200, func_name: str = "",
    ) -> str:
        """Format timeline into compact text for expert consumption."""
        if not timeline:
            return "(无时间线数据)"

        fmap = get_func_fields(func_name)
        state_key = fmap.get("state", "")
        enable_key = fmap.get("enable", "")
        warning_keys = fmap.get("warnings", [])

        lines: list[str] = []
        step = max(1, len(timeline) // max_lines)
        for row in timeline[::step][:max_lines]:
            parts = [f"t={row['t']:.2f}"]
            if "car_spd" in row:
                parts.append(f"spd={row['car_spd']:.2f}")
            if state_key and state_key in row:
                parts.append(f"st={row[state_key]}")
            if enable_key and enable_key in row:
                parts.append(f"en={row[enable_key]}")
            for idx, wk in enumerate(warning_keys):
                if wk in row:
                    label = "wL" if idx == 0 else "wR"
                    parts.append(f"{label}={row[wk]}")

            trk_parts = []
            for i in range(4):
                vx = row.get(f"trc_{i}_vel_x")
                if vx is not None and abs(vx) > 0.1:
                    dx = row.get(f"trc_{i}_dist_x", 0)
                    dy = row.get(f"trc_{i}_dist_y", 0)
                    ttc = row.get(f"trc_{i}_ttc", 0)
                    trk_parts.append(f"t{i}(vx={vx:.1f} dx={dx:.1f} dy={dy:.1f} ttc={ttc:.1f})")
            if trk_parts:
                parts.append("| " + " ".join(trk_parts))

            lines.append(" ".join(parts))

        return "\n".join(lines)

    @staticmethod
    def _detect_changes(prev: dict, curr: dict) -> list[dict]:
        changes = []
        all_keys = set(list(prev.keys()) + list(curr.keys()))
        skip_keys = {"raw_hex", "payload_preview", "objects_preview"}
        for key in all_keys:
            if key in skip_keys:
                continue
            old_val = prev.get(key)
            new_val = curr.get(key)
            if old_val != new_val:
                changes.append({"field": key, "old": old_val, "new": new_val})
        return changes

    @staticmethod
    def _sample_frames(frames: list, max_count: int) -> list:
        if len(frames) <= max_count:
            return frames
        step = len(frames) / max_count
        return [frames[int(i * step)] for i in range(max_count)]
