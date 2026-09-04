#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
FrameSync KPI script for corner radar GT CSV + rosbag.

Compared with bag_csv_kpi_batch.py, this script uses the PM-defined KPI standard:
1) TP: pred interval overlaps GT interval.
2) FP: pred interval does not overlap any GT interval.
3) FN: within a complete GT interval, no pred interval exists.

Special case:
- If one GT interval has multiple pred alarm segments, still count TP.
- Mark as interruption and export separate interruption statistics.
- Supports csv/xlsx/both report output.
"""

import argparse
import csv
import datetime as dt
import math
import os
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from bag_csv_kpi_batch import (
    Interval,
    CsvMeta,
    BatchJob,
    K_ADAS_WARN_COUNT,
    K_ADAS_LABEL_NAMES,
    load_gt_csv,
    build_pred_intervals,
    collect_jobs,
    ensure_output_dir,
    write_index,
    export_batch_aggregate_report,
    export_batch_aggregate_report_from_output_dir,
    radar_direction_from_id,
    fmt6,
    fmt_opt,
    mean_or_nan,
    export_excel_report_from_csv,
    K_DEFAULT_EA_THRESHOLD_SEC,
    K_DEFAULT_ED_THRESHOLD_SEC,
    K_DEFAULT_LA_THRESHOLD_SEC,
    K_DEFAULT_LD_THRESHOLD_SEC,
)


@dataclass
class MetricRowStd:
    radar_id: int
    label_index: int
    label_name: str
    gt_count: int
    pred_count: int
    tp: int
    fn: int
    fp: int
    tpr: float
    fpr: float
    fnr: float
    precision: float
    f1: float
    mean_delay: float
    min_delay: float
    max_delay: float
    mean_overlap: float
    interrupted_tp: int
    interruption_count: int
    interruption_tp_ratio: float
    mean_interrupt_gap: float
    max_interrupt_gap: float
    mean_tp_duration: float
    mean_fn_duration: float
    mean_fp_duration: float
    ea_count: int
    mean_ea_duration: float
    ed_count: int
    mean_ed_duration: float
    la_count: int
    mean_la_duration: float
    ld_count: int
    mean_ld_duration: float
    double_warning_count: int
    mean_double_warning_duration: float


@dataclass
class EventRowStd:
    radar_id: int
    label_index: int
    label_name: str
    event_type: str
    gt_start: float
    gt_end: float
    pred_start: float
    pred_end: float
    delay: float
    overlap: float
    pred_segments: int
    interruption_count: int
    pred_first_start: float = math.nan
    pred_last_end: float = math.nan
    pred_active_duration: float = math.nan
    pred_span_duration: float = math.nan
    interruption_gaps: List[float] = field(default_factory=list)
    is_interrupted: int = 0
    start_offset: float = math.nan
    end_offset: float = math.nan
    ea_duration: float = math.nan
    ed_duration: float = math.nan
    la_duration: float = math.nan
    ld_duration: float = math.nan
    is_ea: int = 0
    is_ed: int = 0
    is_la: int = 0
    is_ld: int = 0
    double_warning_duration: float = math.nan


def interval_overlap_sec(s0: float, e0: float, s1: float, e1: float) -> float:
    return max(0.0, min(e0, e1) - max(s0, s1))


def is_interval_match_strict_overlap(s0: float, e0: float, s1: float, e1: float) -> bool:
    return interval_overlap_sec(s0, e0, s1, e1) > 0.0


def _merge_segments(segments: List[Tuple[float, float]], merge_tol: float = 1e-9) -> List[Tuple[float, float]]:
    if not segments:
        return []
    segments = sorted(segments, key=lambda x: (x[0], x[1]))
    merged: List[Tuple[float, float]] = [segments[0]]
    for s, e in segments[1:]:
        last_s, last_e = merged[-1]
        if s <= last_e + merge_tol:
            merged[-1] = (last_s, max(last_e, e))
        else:
            merged.append((s, e))
    return merged


def compute_metrics_framesync_standard(
    gt: List[Interval],
    pred: List[Interval],
    ea_threshold_sec: float,
    ed_threshold_sec: float,
    la_threshold_sec: float,
    ld_threshold_sec: float,
) -> Tuple[List[MetricRowStd], List[EventRowStd]]:
    gt_by: Dict[Tuple[int, int], List[Interval]] = {}
    pred_by: Dict[Tuple[int, int], List[Interval]] = {}
    for it in gt:
        gt_by.setdefault((it.radar_id, it.label_index), []).append(it)
    for it in pred:
        pred_by.setdefault((it.radar_id, it.label_index), []).append(it)

    keys = sorted(set(gt_by.keys()) | set(pred_by.keys()))
    metrics: List[MetricRowStd] = []
    events: List[EventRowStd] = []

    total_gt = total_pred = total_tp = total_fn = total_fp = 0
    total_interrupted_tp = 0
    total_interruption_count = 0
    total_delays: List[float] = []
    total_overlaps: List[float] = []
    total_interrupt_gaps: List[float] = []
    total_tp_durations: List[float] = []
    total_fn_durations: List[float] = []
    total_fp_durations: List[float] = []
    total_ea_durations: List[float] = []
    total_ed_durations: List[float] = []
    total_la_durations: List[float] = []
    total_ld_durations: List[float] = []
    total_double_warning_durations: List[float] = []

    for key in keys:
        rid, li = key
        lname = K_ADAS_LABEL_NAMES.get(li, "")
        g = sorted(gt_by.get(key, []), key=lambda x: (x.start_sec, x.end_sec))
        p = sorted(pred_by.get(key, []), key=lambda x: (x.start_sec, x.end_sec))

        pred_overlaps_any = [False] * len(p)
        tp = fn = fp = 0
        interrupted_tp = 0
        interruption_count = 0
        delays: List[float] = []
        overlaps: List[float] = []
        interrupt_gaps: List[float] = []
        tp_durations: List[float] = []
        fn_durations: List[float] = []
        fp_durations: List[float] = []
        ea_durations: List[float] = []
        ed_durations: List[float] = []
        la_durations: List[float] = []
        ld_durations: List[float] = []
        double_warning_durations: List[float] = []

        for gv in g:
            overlap_idx: List[int] = []
            for pi, pv in enumerate(p):
                if is_interval_match_strict_overlap(gv.start_sec, gv.end_sec, pv.start_sec, pv.end_sec):
                    overlap_idx.append(pi)
                    pred_overlaps_any[pi] = True

            if not overlap_idx:
                fn += 1
                gt_duration = max(0.0, gv.end_sec - gv.start_sec)
                fn_durations.append(gt_duration)
                total_fn_durations.append(gt_duration)
                events.append(
                    EventRowStd(
                        radar_id=rid,
                        label_index=li,
                        label_name=lname,
                        event_type="FN",
                        gt_start=gv.start_sec,
                        gt_end=gv.end_sec,
                        pred_start=math.nan,
                        pred_end=math.nan,
                        delay=math.nan,
                        overlap=math.nan,
                        pred_segments=0,
                        interruption_count=0,
                        pred_first_start=math.nan,
                        pred_last_end=math.nan,
                        pred_active_duration=math.nan,
                        pred_span_duration=math.nan,
                        interruption_gaps=[],
                        is_interrupted=0,
                        start_offset=math.nan,
                        end_offset=math.nan,
                        ea_duration=math.nan,
                        ed_duration=math.nan,
                        la_duration=math.nan,
                        ld_duration=math.nan,
                        is_ea=0,
                        is_ed=0,
                        is_la=0,
                        is_ld=0,
                        double_warning_duration=math.nan,
                    )
                )
                continue

            tp += 1
            overlap_idx.sort(key=lambda pi: (p[pi].start_sec, p[pi].end_sec))
            primary = p[overlap_idx[0]]
            first_pred_start = primary.start_sec
            last_pred_end = max(p[pi].end_sec for pi in overlap_idx)
            delay = primary.start_sec - gv.start_sec
            delays.append(delay)
            total_delays.append(delay)

            clipped: List[Tuple[float, float]] = []
            for pi in overlap_idx:
                s = max(gv.start_sec, p[pi].start_sec)
                e = min(gv.end_sec, p[pi].end_sec)
                if e >= s:
                    clipped.append((s, e))
            merged = _merge_segments(clipped)
            total_overlap = sum(max(0.0, e - s) for s, e in merged)
            overlaps.append(total_overlap)
            total_overlaps.append(total_overlap)

            full_segments = _merge_segments([(p[pi].start_sec, p[pi].end_sec) for pi in overlap_idx])
            pred_active_duration = sum(max(0.0, e - s) for s, e in full_segments)
            pred_span_duration = max(0.0, last_pred_end - first_pred_start)
            tp_durations.append(pred_active_duration)
            total_tp_durations.append(pred_active_duration)

            start_offset = first_pred_start - gv.start_sec
            end_offset = last_pred_end - gv.end_sec
            ea_duration = max(0.0, -start_offset)
            ed_duration = max(0.0, -end_offset)
            la_duration = max(0.0, start_offset)
            ld_duration = max(0.0, end_offset)
            is_ea = 1 if ea_duration > ea_threshold_sec else 0
            is_ed = 1 if ed_duration > ed_threshold_sec else 0
            is_la = 1 if la_duration > la_threshold_sec else 0
            is_ld = 1 if ld_duration > ld_threshold_sec else 0
            if is_ea:
                ea_durations.append(ea_duration)
                total_ea_durations.append(ea_duration)
            if is_ed:
                ed_durations.append(ed_duration)
                total_ed_durations.append(ed_duration)
            if is_la:
                la_durations.append(la_duration)
                total_la_durations.append(la_duration)
            if is_ld:
                ld_durations.append(ld_duration)
                total_ld_durations.append(ld_duration)

            pred_segments = len(merged)
            gt_interruptions = max(0, pred_segments - 1)
            gaps: List[float] = []
            double_warning_duration = max(0.0, pred_span_duration - pred_active_duration)
            if gt_interruptions > 0:
                interrupted_tp += 1
                interruption_count += gt_interruptions
                double_warning_durations.append(double_warning_duration)
                total_double_warning_durations.append(double_warning_duration)
                for i in range(len(merged) - 1):
                    gap = max(0.0, merged[i + 1][0] - merged[i][1])
                    gaps.append(gap)
                    interrupt_gaps.append(gap)
                    total_interrupt_gaps.append(gap)

            events.append(
                EventRowStd(
                    radar_id=rid,
                    label_index=li,
                    label_name=lname,
                    event_type="TP",
                    gt_start=gv.start_sec,
                    gt_end=gv.end_sec,
                    pred_start=primary.start_sec,
                    pred_end=primary.end_sec,
                    delay=delay,
                    overlap=total_overlap,
                    pred_segments=pred_segments,
                    interruption_count=gt_interruptions,
                    pred_first_start=first_pred_start,
                    pred_last_end=last_pred_end,
                    pred_active_duration=pred_active_duration,
                    pred_span_duration=pred_span_duration,
                    interruption_gaps=gaps,
                    is_interrupted=1 if gt_interruptions > 0 else 0,
                    start_offset=start_offset,
                    end_offset=end_offset,
                    ea_duration=ea_duration,
                    ed_duration=ed_duration,
                    la_duration=la_duration,
                    ld_duration=ld_duration,
                    is_ea=is_ea,
                    is_ed=is_ed,
                    is_la=is_la,
                    is_ld=is_ld,
                    double_warning_duration=double_warning_duration,
                )
            )

        for pi, pv in enumerate(p):
            if pred_overlaps_any[pi]:
                continue
            fp += 1
            fp_duration = max(0.0, pv.end_sec - pv.start_sec)
            fp_durations.append(fp_duration)
            total_fp_durations.append(fp_duration)
            events.append(
                EventRowStd(
                    radar_id=rid,
                    label_index=li,
                    label_name=lname,
                    event_type="FP",
                    gt_start=math.nan,
                    gt_end=math.nan,
                    pred_start=pv.start_sec,
                    pred_end=pv.end_sec,
                    delay=math.nan,
                    overlap=math.nan,
                    pred_segments=1,
                    interruption_count=0,
                    pred_first_start=pv.start_sec,
                    pred_last_end=pv.end_sec,
                    pred_active_duration=max(0.0, pv.end_sec - pv.start_sec),
                    pred_span_duration=max(0.0, pv.end_sec - pv.start_sec),
                    interruption_gaps=[],
                    is_interrupted=0,
                    start_offset=math.nan,
                    end_offset=math.nan,
                    ea_duration=math.nan,
                    ed_duration=math.nan,
                    la_duration=math.nan,
                    ld_duration=math.nan,
                    is_ea=0,
                    is_ed=0,
                    is_la=0,
                    is_ld=0,
                    double_warning_duration=math.nan,
                )
            )

        denom_tp_fn = tp + fn
        denom_all = tp + fn + fp
        denom_prec = tp + fp
        tpr = (tp / denom_tp_fn) if denom_tp_fn > 0 else 0.0
        fnr = (fn / denom_tp_fn) if denom_tp_fn > 0 else 0.0
        fpr = (fp / denom_all) if denom_all > 0 else 0.0
        precision = (tp / denom_prec) if denom_prec > 0 else 0.0
        f1 = (2.0 * precision * tpr / (precision + tpr)) if (precision + tpr) > 0 else 0.0

        mean_delay = min_delay = max_delay = mean_overlap = math.nan
        if delays:
            mean_delay = sum(delays) / len(delays)
            min_delay = min(delays)
            max_delay = max(delays)
        if overlaps:
            mean_overlap = sum(overlaps) / len(overlaps)

        mean_interrupt_gap = max_interrupt_gap = math.nan
        if interrupt_gaps:
            mean_interrupt_gap = sum(interrupt_gaps) / len(interrupt_gaps)
            max_interrupt_gap = max(interrupt_gaps)

        interruption_tp_ratio = (interrupted_tp / tp) if tp > 0 else 0.0
        mean_tp_duration = mean_or_nan(tp_durations)
        mean_fn_duration = mean_or_nan(fn_durations)
        mean_fp_duration = mean_or_nan(fp_durations)
        mean_ea_duration = mean_or_nan(ea_durations)
        mean_ed_duration = mean_or_nan(ed_durations)
        mean_la_duration = mean_or_nan(la_durations)
        mean_ld_duration = mean_or_nan(ld_durations)
        mean_double_warning_duration = mean_or_nan(double_warning_durations)

        metrics.append(
            MetricRowStd(
                radar_id=rid,
                label_index=li,
                label_name=lname,
                gt_count=len(g),
                pred_count=len(p),
                tp=tp,
                fn=fn,
                fp=fp,
                tpr=tpr,
                fpr=fpr,
                fnr=fnr,
                precision=precision,
                f1=f1,
                mean_delay=mean_delay,
                min_delay=min_delay,
                max_delay=max_delay,
                mean_overlap=mean_overlap,
                interrupted_tp=interrupted_tp,
                interruption_count=interruption_count,
                interruption_tp_ratio=interruption_tp_ratio,
                mean_interrupt_gap=mean_interrupt_gap,
                max_interrupt_gap=max_interrupt_gap,
                mean_tp_duration=mean_tp_duration,
                mean_fn_duration=mean_fn_duration,
                mean_fp_duration=mean_fp_duration,
                ea_count=len(ea_durations),
                mean_ea_duration=mean_ea_duration,
                ed_count=len(ed_durations),
                mean_ed_duration=mean_ed_duration,
                la_count=len(la_durations),
                mean_la_duration=mean_la_duration,
                ld_count=len(ld_durations),
                mean_ld_duration=mean_ld_duration,
                double_warning_count=interrupted_tp,
                mean_double_warning_duration=mean_double_warning_duration,
            )
        )

        total_gt += len(g)
        total_pred += len(p)
        total_tp += tp
        total_fn += fn
        total_fp += fp
        total_interrupted_tp += interrupted_tp
        total_interruption_count += interruption_count

    denom_tp_fn = total_tp + total_fn
    denom_all = total_tp + total_fn + total_fp
    denom_prec = total_tp + total_fp
    total_tpr = (total_tp / denom_tp_fn) if denom_tp_fn > 0 else 0.0
    total_fnr = (total_fn / denom_tp_fn) if denom_tp_fn > 0 else 0.0
    total_fpr = (total_fp / denom_all) if denom_all > 0 else 0.0
    total_precision = (total_tp / denom_prec) if denom_prec > 0 else 0.0
    total_f1 = (2.0 * total_precision * total_tpr / (total_precision + total_tpr)) if (total_precision + total_tpr) > 0 else 0.0
    total_interruption_tp_ratio = (total_interrupted_tp / total_tp) if total_tp > 0 else 0.0

    total_mean_delay = total_min_delay = total_max_delay = total_mean_overlap = math.nan
    if total_delays:
        total_mean_delay = sum(total_delays) / len(total_delays)
        total_min_delay = min(total_delays)
        total_max_delay = max(total_delays)
    if total_overlaps:
        total_mean_overlap = sum(total_overlaps) / len(total_overlaps)

    total_mean_interrupt_gap = total_max_interrupt_gap = math.nan
    if total_interrupt_gaps:
        total_mean_interrupt_gap = sum(total_interrupt_gaps) / len(total_interrupt_gaps)
        total_max_interrupt_gap = max(total_interrupt_gaps)
    total_mean_tp_duration = mean_or_nan(total_tp_durations)
    total_mean_fn_duration = mean_or_nan(total_fn_durations)
    total_mean_fp_duration = mean_or_nan(total_fp_durations)
    total_mean_ea_duration = mean_or_nan(total_ea_durations)
    total_mean_ed_duration = mean_or_nan(total_ed_durations)
    total_mean_la_duration = mean_or_nan(total_la_durations)
    total_mean_ld_duration = mean_or_nan(total_ld_durations)
    total_mean_double_warning_duration = mean_or_nan(total_double_warning_durations)

    metrics.append(
        MetricRowStd(
            radar_id=0,
            label_index=0,
            label_name="ALL",
            gt_count=total_gt,
            pred_count=total_pred,
            tp=total_tp,
            fn=total_fn,
            fp=total_fp,
            tpr=total_tpr,
            fpr=total_fpr,
            fnr=total_fnr,
            precision=total_precision,
            f1=total_f1,
            mean_delay=total_mean_delay,
            min_delay=total_min_delay,
            max_delay=total_max_delay,
            mean_overlap=total_mean_overlap,
            interrupted_tp=total_interrupted_tp,
            interruption_count=total_interruption_count,
            interruption_tp_ratio=total_interruption_tp_ratio,
            mean_interrupt_gap=total_mean_interrupt_gap,
            max_interrupt_gap=total_max_interrupt_gap,
            mean_tp_duration=total_mean_tp_duration,
            mean_fn_duration=total_mean_fn_duration,
            mean_fp_duration=total_mean_fp_duration,
            ea_count=len(total_ea_durations),
            mean_ea_duration=total_mean_ea_duration,
            ed_count=len(total_ed_durations),
            mean_ed_duration=total_mean_ed_duration,
            la_count=len(total_la_durations),
            mean_la_duration=total_mean_la_duration,
            ld_count=len(total_ld_durations),
            mean_ld_duration=total_mean_ld_duration,
            double_warning_count=total_interrupted_tp,
            mean_double_warning_duration=total_mean_double_warning_duration,
        )
    )

    return metrics, events


def build_pred_intervals_from_warning_csv(
    warning_csv_path: str,
) -> Tuple[List[Interval], Dict[str, float]]:
    """
    Build pred intervals from algorithm warning trace CSV.
    Required columns:
      - event_sec
      - radar_id
      - w1..w15
    """
    stats: Dict[str, float] = {
        "warning_msgs": 0,
        "warning_short_msgs": 0,
        "warning_invalid_radar": 0,
        "lgu_msgs": 0,
        "lgu_valid_stamp_msgs": 0,
    }

    pred: List[Interval] = []
    active = [[False] * (K_ADAS_WARN_COUNT + 1) for _ in range(5)]
    start_sec = [[0.0] * (K_ADAS_WARN_COUNT + 1) for _ in range(5)]
    last_warn_sec = [0.0] * 5

    rows: List[Tuple[float, int, List[int]]] = []
    with open(warning_csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                event_sec = float(row.get("event_sec", "0"))
                rid = int(row.get("radar_id", "0"))
            except Exception:
                stats["warning_short_msgs"] += 1
                continue

            if rid < 1 or rid > 4:
                stats["warning_invalid_radar"] += 1
                continue
            if not math.isfinite(event_sec) or event_sec <= 0.0:
                stats["warning_short_msgs"] += 1
                continue

            values: List[int] = [0]
            valid = True
            for li in range(1, K_ADAS_WARN_COUNT + 1):
                key = f"w{li}"
                if key not in row:
                    valid = False
                    break
                try:
                    values.append(1 if int(row[key]) > 0 else 0)
                except Exception:
                    valid = False
                    break

            if not valid:
                stats["warning_short_msgs"] += 1
                continue

            rows.append((event_sec, rid, values))

    rows.sort(key=lambda x: x[0])

    for event_sec, rid, values in rows:
        stats["warning_msgs"] += 1

        if last_warn_sec[rid] > 0.0 and event_sec + 0.5 < last_warn_sec[rid]:
            pred.clear()
            for rr in range(1, 5):
                for li in range(1, K_ADAS_WARN_COUNT + 1):
                    active[rr][li] = False
                    start_sec[rr][li] = 0.0
                last_warn_sec[rr] = 0.0

        last_warn_sec[rid] = event_sec

        for li in range(1, K_ADAS_WARN_COUNT + 1):
            now_on = values[li] > 0
            prev_on = active[rid][li]

            if now_on and not prev_on:
                active[rid][li] = True
                start_sec[rid][li] = event_sec
                continue

            if (not now_on) and prev_on:
                s = start_sec[rid][li]
                if s <= 0.0 or event_sec < s:
                    s = event_sec
                pred.append(
                    Interval(
                        radar_id=rid,
                        label_index=li,
                        label_name=K_ADAS_LABEL_NAMES[li],
                        start_sec=s,
                        end_sec=event_sec,
                    )
                )
                active[rid][li] = False
                start_sec[rid][li] = 0.0

    for rid in range(1, 5):
        for li in range(1, K_ADAS_WARN_COUNT + 1):
            if not active[rid][li]:
                continue
            s = start_sec[rid][li]
            e = last_warn_sec[rid]
            if e <= 0.0:
                e = s
            if e < s:
                e = s
            pred.append(
                Interval(
                    radar_id=rid,
                    label_index=li,
                    label_name=K_ADAS_LABEL_NAMES[li],
                    start_sec=s,
                    end_sec=e,
                )
            )

    pred.sort(key=lambda x: (x.start_sec, x.end_sec, x.radar_id, x.label_index))
    return pred, stats


def export_kpi_framesync(
    summary_path: str,
    events_path: str,
    metrics: List[MetricRowStd],
    events: List[EventRowStd],
    tol_sec: float,
    ea_threshold_sec: float,
    ed_threshold_sec: float,
    la_threshold_sec: float,
    ld_threshold_sec: float,
    csv_meta: CsvMeta,
    playback_bag_path: str,
) -> None:
    now_utc_dt = dt.datetime.now(dt.timezone.utc)
    now_cn_dt = now_utc_dt.astimezone(dt.timezone(dt.timedelta(hours=8)))
    now_utc = now_utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    now_cn = now_cn_dt.strftime("%Y-%m-%dT%H:%M:%S+08:00")
    csv_path = csv_meta.csv_path
    gt_bag_path = csv_meta.bag_path
    bag_start = csv_meta.bag_start_sec

    os.makedirs(os.path.dirname(summary_path), exist_ok=True)

    with open(summary_path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "generated_at_utc",
                "generated_at_cn",
                "label_csv_path",
                "playback_bag_path",
                "gt_bag_path",
                "kpi_tolerance_sec",
                "radar_id",
                "radar_direction",
                "label_name",
                "gt_intervals",
                "pred_intervals",
                "tp",
                "fn",
                "fp",
                "tpr",
                "fpr",
                "fnr",
                "precision",
                "f1",
                "mean_delay_sec",
                "min_delay_sec",
                "max_delay_sec",
                "mean_overlap_sec",
                "interrupted_tp",
                "interruption_count",
                "interruption_tp_ratio",
                "mean_interrupt_gap_sec",
                "max_interrupt_gap_sec",
                "mean_tp_duration_sec",
                "mean_fn_duration_sec",
                "mean_fp_duration_sec",
                "ea_count",
                "mean_ea_duration_sec",
                "ed_count",
                "mean_ed_duration_sec",
                "la_count",
                "mean_la_duration_sec",
                "ld_count",
                "mean_ld_duration_sec",
                "double_warning_count",
                "mean_double_warning_duration_sec",
                "ea_threshold_sec",
                "ed_threshold_sec",
                "la_threshold_sec",
                "ld_threshold_sec",
            ]
        )

        for row in metrics:
            has_tp = row.tp > 0
            has_interrupt = row.interruption_count > 0
            w.writerow(
                [
                    now_utc,
                    now_cn,
                    csv_path,
                    playback_bag_path,
                    gt_bag_path,
                    fmt6(tol_sec),
                    row.radar_id,
                    radar_direction_from_id(row.radar_id),
                    row.label_name,
                    row.gt_count,
                    row.pred_count,
                    row.tp,
                    row.fn,
                    row.fp,
                    fmt6(row.tpr),
                    fmt6(row.fpr),
                    fmt6(row.fnr),
                    fmt6(row.precision),
                    fmt6(row.f1),
                    (fmt6(row.mean_delay) if has_tp else ""),
                    (fmt6(row.min_delay) if has_tp else ""),
                    (fmt6(row.max_delay) if has_tp else ""),
                    (fmt6(row.mean_overlap) if has_tp else ""),
                    row.interrupted_tp,
                    row.interruption_count,
                    fmt6(row.interruption_tp_ratio),
                    (fmt6(row.mean_interrupt_gap) if has_interrupt else ""),
                    (fmt6(row.max_interrupt_gap) if has_interrupt else ""),
                    (fmt6(row.mean_tp_duration) if row.tp > 0 else ""),
                    (fmt6(row.mean_fn_duration) if row.fn > 0 else ""),
                    (fmt6(row.mean_fp_duration) if row.fp > 0 else ""),
                    row.ea_count,
                    (fmt6(row.mean_ea_duration) if row.ea_count > 0 else ""),
                    row.ed_count,
                    (fmt6(row.mean_ed_duration) if row.ed_count > 0 else ""),
                    row.la_count,
                    (fmt6(row.mean_la_duration) if row.la_count > 0 else ""),
                    row.ld_count,
                    (fmt6(row.mean_ld_duration) if row.ld_count > 0 else ""),
                    row.double_warning_count,
                    (fmt6(row.mean_double_warning_duration) if row.double_warning_count > 0 else ""),
                    fmt6(ea_threshold_sec),
                    fmt6(ed_threshold_sec),
                    fmt6(la_threshold_sec),
                    fmt6(ld_threshold_sec),
                ]
            )

    with open(events_path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "generated_at_utc",
                "generated_at_cn",
                "label_csv_path",
                "playback_bag_path",
                "gt_bag_path",
                "radar_id",
                "radar_direction",
                "label_name",
                "event_type",
                "gt_start_abs",
                "gt_end_abs",
                "pred_start_abs",
                "pred_end_abs",
                "pred_first_start_abs",
                "pred_last_end_abs",
                "gt_start_rel",
                "gt_end_rel",
                "pred_start_rel",
                "pred_end_rel",
                "pred_first_start_rel",
                "pred_last_end_rel",
                "delay_sec",
                "overlap_sec",
                "gt_duration_sec",
                "pred_duration_sec",
                "pred_active_duration_sec",
                "pred_span_duration_sec",
                "pred_segments",
                "interruption_count",
                "interruption_gaps_sec",
                "is_interrupted",
                "start_offset_sec",
                "end_offset_sec",
                "ea_duration_sec",
                "ed_duration_sec",
                "la_duration_sec",
                "ld_duration_sec",
                "is_ea",
                "is_ed",
                "is_la",
                "is_ld",
                "double_warning_duration_sec",
            ]
        )

        for ev in events:
            gt_dur = (
                max(0.0, ev.gt_end - ev.gt_start)
                if math.isfinite(ev.gt_start) and math.isfinite(ev.gt_end)
                else math.nan
            )
            pred_dur = (
                max(0.0, ev.pred_end - ev.pred_start)
                if math.isfinite(ev.pred_start) and math.isfinite(ev.pred_end)
                else math.nan
            )
            gt_start_rel = (
                ev.gt_start - bag_start
                if math.isfinite(ev.gt_start) and bag_start > 0.0
                else math.nan
            )
            gt_end_rel = (
                ev.gt_end - bag_start
                if math.isfinite(ev.gt_end) and bag_start > 0.0
                else math.nan
            )
            pred_start_rel = (
                ev.pred_start - bag_start
                if math.isfinite(ev.pred_start) and bag_start > 0.0
                else math.nan
            )
            pred_end_rel = (
                ev.pred_end - bag_start
                if math.isfinite(ev.pred_end) and bag_start > 0.0
                else math.nan
            )
            pred_first_start_rel = (
                ev.pred_first_start - bag_start
                if math.isfinite(ev.pred_first_start) and bag_start > 0.0
                else math.nan
            )
            pred_last_end_rel = (
                ev.pred_last_end - bag_start
                if math.isfinite(ev.pred_last_end) and bag_start > 0.0
                else math.nan
            )
            gaps = ";".join(f"{g:.6f}" for g in ev.interruption_gaps) if ev.interruption_gaps else ""

            w.writerow(
                [
                    now_utc,
                    now_cn,
                    csv_path,
                    playback_bag_path,
                    gt_bag_path,
                    ev.radar_id,
                    radar_direction_from_id(ev.radar_id),
                    ev.label_name,
                    ev.event_type,
                    fmt_opt(ev.gt_start),
                    fmt_opt(ev.gt_end),
                    fmt_opt(ev.pred_start),
                    fmt_opt(ev.pred_end),
                    fmt_opt(ev.pred_first_start),
                    fmt_opt(ev.pred_last_end),
                    fmt_opt(gt_start_rel),
                    fmt_opt(gt_end_rel),
                    fmt_opt(pred_start_rel),
                    fmt_opt(pred_end_rel),
                    fmt_opt(pred_first_start_rel),
                    fmt_opt(pred_last_end_rel),
                    fmt_opt(ev.delay),
                    fmt_opt(ev.overlap),
                    fmt_opt(gt_dur),
                    fmt_opt(pred_dur),
                    fmt_opt(ev.pred_active_duration),
                    fmt_opt(ev.pred_span_duration),
                    ev.pred_segments,
                    ev.interruption_count,
                    gaps,
                    ev.is_interrupted,
                    fmt_opt(ev.start_offset),
                    fmt_opt(ev.end_offset),
                    fmt_opt(ev.ea_duration),
                    fmt_opt(ev.ed_duration),
                    fmt_opt(ev.la_duration),
                    fmt_opt(ev.ld_duration),
                    ev.is_ea,
                    ev.is_ed,
                    ev.is_la,
                    ev.is_ld,
                    fmt_opt(ev.double_warning_duration),
                ]
            )


def run_one_job(
    bag_path: str,
    csv_path: str,
    output_dir: str,
    warning_topic: str,
    lgu_prefix: str,
    warning_csv: str,
    ea_threshold_sec: float,
    ed_threshold_sec: float,
    la_threshold_sec: float,
    ld_threshold_sec: float,
    report_format: str,
    verbose: bool,
) -> Tuple[bool, str, str, str, str, str]:
    gt, meta, warns = load_gt_csv(csv_path)

    if warning_csv:
        pred, stats = build_pred_intervals_from_warning_csv(
            warning_csv_path=warning_csv,
        )
    else:
        pred, stats = build_pred_intervals(
            bag_path=bag_path,
            warning_topic=warning_topic,
            lgu_prefix=lgu_prefix,
        )

    metrics, events = compute_metrics_framesync_standard(
        gt=gt,
        pred=pred,
        ea_threshold_sec=ea_threshold_sec,
        ed_threshold_sec=ed_threshold_sec,
        la_threshold_sec=la_threshold_sec,
        ld_threshold_sec=ld_threshold_sec,
    )

    base = os.path.splitext(os.path.basename(bag_path))[0]
    summary_path = os.path.join(output_dir, f"{base}_adas_kpi_summary.csv")
    events_path = os.path.join(output_dir, f"{base}_adas_kpi_summary_events.csv")
    xlsx_path = os.path.join(output_dir, f"{base}_adas_kpi_report.xlsx")

    export_kpi_framesync(
        summary_path=summary_path,
        events_path=events_path,
        metrics=metrics,
        events=events,
        tol_sec=0.0,
        ea_threshold_sec=ea_threshold_sec,
        ed_threshold_sec=ed_threshold_sec,
        la_threshold_sec=la_threshold_sec,
        ld_threshold_sec=ld_threshold_sec,
        csv_meta=meta,
        playback_bag_path=os.path.abspath(bag_path),
    )

    report_format = (report_format or "").strip().lower()
    if report_format not in ("csv", "xlsx", "both"):
        raise ValueError(f"Unsupported report_format: {report_format}")

    exported_xlsx = ""
    if report_format in ("xlsx", "both"):
        note = (
            "5G-aligned extra stats included; strict-overlap matching; "
            f"EA/ED/LA/LD thresholds={ea_threshold_sec:.3f}/{ed_threshold_sec:.3f}/{la_threshold_sec:.3f}/{ld_threshold_sec:.3f} sec"
        )
        export_excel_report_from_csv(
            excel_path=xlsx_path,
            summary_csv_path=summary_path,
            events_csv_path=events_path,
            report_note=note,
        )
        exported_xlsx = xlsx_path

    if report_format == "xlsx":
        try:
            os.remove(summary_path)
        except Exception:
            pass
        try:
            os.remove(events_path)
        except Exception:
            pass
        summary_path = ""
        events_path = ""

    details: List[str] = []
    if warns:
        details.append("; ".join(warns))
    if verbose:
        source_desc = f"warning_csv={warning_csv}" if warning_csv else f"warning_topic={warning_topic}"
        details.append(
            "{source}, warning_msgs={warning_msgs}, lgu_msgs={lgu_msgs}, pred_intervals={pred_count}".format(
                source=source_desc,
                warning_msgs=int(stats.get("warning_msgs", 0)),
                lgu_msgs=int(stats.get("lgu_msgs", 0)),
                pred_count=len(pred),
            )
        )
    if exported_xlsx:
        details.append(f"xlsx={exported_xlsx}")
    detail = "done" if not details else "done; " + " | ".join(details)
    return True, detail, summary_path, events_path, exported_xlsx, "\n".join(warns)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="FrameSync KPI tool (PM standard) for bag + GT csv")

    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--input-dir", help="Directory mode: recursively match bag+csv pairs")
    mode.add_argument("--bag", help="Single mode: input bag path")

    p.add_argument("--csv", help="Single mode: GT CSV path (required with --bag)")
    p.add_argument("--output-dir", default="", help="Output directory")
    p.add_argument("--warning-topic", default="/corner_radar/warning_status_raw", help="Warning topic in bag")
    p.add_argument(
        "--warning-csv",
        default="",
        help="Optional warning trace CSV (event_sec,radar_id,w1..w15). If set, use it instead of --warning-topic.",
    )
    p.add_argument("--lgu-prefix", default="/wf/corner_radar/lgu_data_", help="LGU topic prefix")
    # Kept for CLI compatibility; ignored in FrameSync strict-overlap mode.
    p.add_argument("--tol", type=float, default=0.0, help="Deprecated. Ignored in strict-overlap mode.")
    p.add_argument(
        "--report-format",
        choices=["csv", "xlsx", "both"],
        default="both",
        help="Output format: csv, xlsx, or both. Default: both",
    )
    p.add_argument("--ea-threshold-sec", type=float, default=K_DEFAULT_EA_THRESHOLD_SEC, help="EA threshold in seconds")
    p.add_argument("--ed-threshold-sec", type=float, default=K_DEFAULT_ED_THRESHOLD_SEC, help="ED threshold in seconds")
    p.add_argument("--la-threshold-sec", type=float, default=K_DEFAULT_LA_THRESHOLD_SEC, help="LA threshold in seconds")
    p.add_argument("--ld-threshold-sec", type=float, default=K_DEFAULT_LD_THRESHOLD_SEC, help="LD threshold in seconds")
    p.add_argument("--verbose", action="store_true", help="Print extra stats")

    args = p.parse_args()
    if args.bag and not args.csv:
        p.error("--csv is required when --bag is used")
    if args.input_dir and args.warning_csv:
        p.error("--warning-csv is only supported with --bag mode")
    return args


def main() -> int:
    args = parse_args()

    rows: List[Dict[str, str]] = []
    success = 0
    failed = 0

    if args.input_dir:
        input_dir = os.path.abspath(args.input_dir)
        jobs, missing = collect_jobs(input_dir)
        if not jobs:
            print("[ERROR] No matched bag+csv jobs found.", file=sys.stderr)
            if missing:
                print("[INFO] Missing examples:", file=sys.stderr)
                for m in missing[:10]:
                    print("  -", m, file=sys.stderr)
            return 2

        out_dir = ensure_output_dir(args.output_dir if args.output_dir else "", input_dir)
        print(f"[INFO] Batch jobs: {len(jobs)}")
        print(f"[INFO] Output dir: {out_dir}")
        if missing:
            print(f"[WARN] Missing csv for {len(missing)} bag(s). Skipped.")

        for i, job in enumerate(jobs, start=1):
            print(f"[INFO] ({i}/{len(jobs)}) bag={job.bag_path}")
            row = {
                "bag_path": job.bag_path,
                "csv_path": job.csv_path,
                "status": "FAILED",
                "summary_path": "",
                "events_path": "",
                "xlsx_path": "",
                "detail": "",
            }
            try:
                ok, detail, sum_path, ev_path, xlsx_path, _warns = run_one_job(
                    bag_path=job.bag_path,
                    csv_path=job.csv_path,
                    output_dir=out_dir,
                    warning_topic=args.warning_topic,
                    lgu_prefix=args.lgu_prefix,
                    warning_csv="",
                    ea_threshold_sec=float(args.ea_threshold_sec),
                    ed_threshold_sec=float(args.ed_threshold_sec),
                    la_threshold_sec=float(args.la_threshold_sec),
                    ld_threshold_sec=float(args.ld_threshold_sec),
                    report_format=args.report_format,
                    verbose=bool(args.verbose),
                )
                row["status"] = "OK" if ok else "FAILED"
                row["summary_path"] = sum_path
                row["events_path"] = ev_path
                row["xlsx_path"] = xlsx_path
                row["detail"] = detail
                if ok:
                    success += 1
                else:
                    failed += 1
            except Exception as exc:
                failed += 1
                row["detail"] = f"FAILED: {exc}"
            rows.append(row)

        index_path = os.path.join(out_dir, "batch_kpi_index.csv")
        write_index(index_path, rows)
        batch_csv_path, batch_xlsx_path = export_batch_aggregate_report(out_dir, rows)
        print(f"[INFO] Done. success={success}, failed={failed}")
        print(f"[INFO] Index: {index_path}")
        if batch_csv_path:
            print(f"[INFO] Batch CSV : {batch_csv_path}")
        if batch_xlsx_path:
            print(f"[INFO] Batch XLSX: {batch_xlsx_path}")
        return 0 if failed == 0 else 1

    bag_path = os.path.abspath(args.bag)
    csv_path = os.path.abspath(args.csv)
    base_dir = os.path.dirname(bag_path)
    out_dir = ensure_output_dir(args.output_dir if args.output_dir else "", base_dir)

    row = {
        "bag_path": bag_path,
        "csv_path": csv_path,
        "status": "FAILED",
        "summary_path": "",
        "events_path": "",
        "xlsx_path": "",
        "detail": "",
    }

    try:
        ok, detail, sum_path, ev_path, xlsx_path, _warns = run_one_job(
            bag_path=bag_path,
            csv_path=csv_path,
            output_dir=out_dir,
            warning_topic=args.warning_topic,
            lgu_prefix=args.lgu_prefix,
            warning_csv=os.path.abspath(args.warning_csv) if args.warning_csv else "",
            ea_threshold_sec=float(args.ea_threshold_sec),
            ed_threshold_sec=float(args.ed_threshold_sec),
            la_threshold_sec=float(args.la_threshold_sec),
            ld_threshold_sec=float(args.ld_threshold_sec),
            report_format=args.report_format,
            verbose=bool(args.verbose),
        )
        row["status"] = "OK" if ok else "FAILED"
        row["summary_path"] = sum_path
        row["events_path"] = ev_path
        row["xlsx_path"] = xlsx_path
        row["detail"] = detail
        success = 1 if ok else 0
        failed = 0 if ok else 1
    except Exception as exc:
        failed = 1
        success = 0
        row["detail"] = f"FAILED: {exc}"

    rows.append(row)
    index_path = os.path.join(out_dir, "batch_kpi_index.csv")
    write_index(index_path, rows)
    batch_csv_path, batch_xlsx_path = export_batch_aggregate_report_from_output_dir(out_dir)

    print(f"[INFO] Done. success={success}, failed={failed}")
    print(f"[INFO] Summary: {row['summary_path']}")
    print(f"[INFO] Events : {row['events_path']}")
    print(f"[INFO] XLSX   : {row.get('xlsx_path', '')}")
    print(f"[INFO] Index  : {index_path}")
    if batch_csv_path:
        print(f"[INFO] Batch CSV : {batch_csv_path}")
    if batch_xlsx_path:
        print(f"[INFO] Batch XLSX: {batch_xlsx_path}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
