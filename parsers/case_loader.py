# -*- coding: utf-8 -*-
"""
Common case data loading logic shared by Orchestrator and DataQueryEngine.
Parses BAG and BLF files from a case directory into a FrameStore, with
optional TimeSync construction.  Also populates radar_objects, radar_debug,
and warning_events tables from deep-parsed wfAutosarData / wfObjectMsg.
"""
from __future__ import annotations

import datetime
from pathlib import Path
from typing import Optional

from .bag_parser import BagParser, TOPIC_RADAR_ID, discover_radar_topics
from .blf_parser import BlfParser
from .dbc_loader import DbcLoader
from .frame_store import FrameStore
from .time_sync import TimeSync
from .mf4_parser import Mf4Parser, check_mf4_dependency

# Legacy hardcoded topic lists — kept for backward compatibility when
# auto-discovery is not available or returns no results.
_WFA_TOPICS_LEGACY = {
    "/wf/corner_radar/lgu_data_1",
    "/wf/corner_radar/lgu_data_2",
    "/wf/corner_radar/lgu_data_3",
    "/wf/corner_radar/lgu_data_4",
}
_WFO_TOPICS_LEGACY = {
    "/wf/objectlist_1",
    "/wf/objectlist_2",
    "/wf/objectlist_3",
    "/wf/objectlist_4",
}

_FLAG_COL_MAP = {
    "BSD": "bsd_flag", "LCA": "lca_flag", "DOW": "dow_flag",
    "RCW": "rcw_flag", "RCTA": "rcta_flag", "RCTB": "rctb_flag",
    "FCTA": "fcta_flag", "FCTB": "fctb_flag",
}


class CaseLoadResult:
    """Container for everything produced by loading a case directory."""
    __slots__ = ("store", "bag_meta", "blf_meta", "mf4_meta", "sync", "dbc")

    def __init__(self):
        self.store: Optional[FrameStore] = None
        self.bag_meta: Optional[dict] = None
        self.blf_meta: Optional[dict] = None
        self.mf4_meta: Optional[dict] = None
        self.sync: Optional[TimeSync] = None
        self.dbc: Optional[DbcLoader] = None


def load_case_data(
    case_dir: Path,
    config: dict,
    project_root: Path,
    on_status=None,
) -> CaseLoadResult:
    """
    Parse all BAG/BLF files in *case_dir* and return a CaseLoadResult.
    Deep-parses wfAutosarData/wfObjectMsg into radar_objects/radar_debug
    and builds warning_events post-hoc.
    """
    def status(step, detail=""):
        if on_status:
            on_status(step, detail)

    result = CaseLoadResult()
    result.store = FrameStore()

    dbc_paths = config["paths"].get("dbc_files", [])
    result.dbc = DbcLoader(dbc_paths, base_dir=project_root) if dbc_paths else None

    bag_metas: list[dict] = []
    blf_metas: list[dict] = []

    obj_rows: list[dict] = []
    dbg_rows: list[dict] = []

    for bf in case_dir.glob("*.bag"):
        status("parse", f"Parsing {bf.name}...")
        parser = BagParser(bf)
        bag_metas.append(parser.get_metadata())

        # P1.2: Auto-discover radar topics from this bag
        discovered = discover_radar_topics(bf)
        wfa_topics = {t for t, info in discovered.items() if info["type"] == "wfa"}
        wfo_topics = {t for t, info in discovered.items() if info["type"] == "wfo"}

        # Fall back to legacy hardcoded topics if discovery found nothing
        if not wfa_topics:
            wfa_topics = _WFA_TOPICS_LEGACY
            status("parse", "  Topic discovery: using legacy WFA topics")
        if not wfo_topics:
            wfo_topics = _WFO_TOPICS_LEGACY
            status("parse", "  Topic discovery: using legacy WFO topics")

        # Build topic -> radar_id map from discovery (merge with legacy)
        topic_radar_id = dict(TOPIC_RADAR_ID)
        for t, info in discovered.items():
            if info["radar_id"] and t not in topic_radar_id:
                topic_radar_id[t] = info["radar_id"]

        if wfa_topics != _WFA_TOPICS_LEGACY or wfo_topics != _WFO_TOPICS_LEGACY:
            status("parse", f"  Topic discovery: {len(wfa_topics)} WFA + {len(wfo_topics)} WFO topics")

        for frame in parser.iter_frames():
            result.store.insert_bag_frame(frame)

            # Extract deep data from wfAutosarData
            if frame.topic in wfa_topics:
                radar_id = topic_radar_id.get(frame.topic, 0)
                fld = frame.fields
                frame_id = fld.get("wfa_frame_id", 0)
                for obj in fld.get("objects", []):
                    obj_rows.append({
                        "timestamp_ns": frame.timestamp_ns,
                        "radar_id": radar_id,
                        "frame_id": frame_id,
                        "obj_id": obj["obj_id"],
                        "obj_class": obj.get("obj_class", 0),
                        "life_cycle": obj.get("life_cycle", 0),
                        "dist_x": obj.get("dist_x"),
                        "dist_y": obj.get("dist_y"),
                        "vel_x": obj.get("vel_x"),
                        "vel_y": obj.get("vel_y"),
                        "vel_abs_x": obj.get("vel_abs_x"),
                        "vel_abs_y": obj.get("vel_abs_y"),
                        "ttc": obj.get("ttc"),
                        "ddci": obj.get("ddci"),
                        "bsd_flag": obj.get("bsd_flag", 0),
                        "lca_flag": obj.get("lca_flag", 0),
                        "dow_flag": obj.get("dow_flag", 0),
                        "rcw_flag": obj.get("rcw_flag", 0),
                        "rcta_flag": obj.get("rcta_flag", 0),
                        "rctb_flag": obj.get("rctb_flag", 0),
                        "fcta_flag": obj.get("fcta_flag", 0),
                        "fctb_flag": obj.get("fctb_flag", 0),
                        "source": "wfa",
                    })
                dbg = fld.get("debug_info")
                if dbg:
                    dbg_rows.append({
                        "timestamp_ns": frame.timestamp_ns,
                        "radar_id": radar_id,
                        "frame_id": frame_id,
                        **dbg,
                    })

            # Extract full objects from wfObjectMsg (supplementary)
            elif frame.topic in wfo_topics:
                radar_id = topic_radar_id.get(frame.topic, 0)
                for obj in frame.fields.get("objects", []):
                    obj_rows.append({
                        "timestamp_ns": frame.timestamp_ns,
                        "radar_id": radar_id,
                        "frame_id": 0,
                        "obj_id": obj.get("objID", 0),
                        "obj_class": obj.get("obj_class", 0),
                        "life_cycle": obj.get("age", 0),
                        "dist_x": obj.get("distX"),
                        "dist_y": obj.get("distY"),
                        "vel_x": obj.get("vel_x"),
                        "vel_y": obj.get("vel_y"),
                        "vel_abs_x": obj.get("velAbsX"),
                        "vel_abs_y": obj.get("velAbsY"),
                        "ttc": obj.get("fTTC"),
                        "ddci": obj.get("fDDCI"),
                        "bsd_flag": obj.get("objBsdWarningFlag", 0),
                        "lca_flag": obj.get("objLcaWarningFlag", 0),
                        "dow_flag": obj.get("objDowWarningFlag", 0),
                        "rcw_flag": obj.get("objRcwWarningFlag", 0),
                        "rcta_flag": obj.get("objRctaWarningFlag", 0),
                        "rctb_flag": obj.get("objRctbWarningFlag", 0),
                        "fcta_flag": obj.get("objFctaWarningFlag", 0),
                        "fctb_flag": obj.get("objFctbWarningFlag", 0),
                        "source": "wfo",
                    })
        result.store.conn.commit()

    # Bulk insert deep-parsed data
    if obj_rows:
        status("parse", f"Writing {len(obj_rows)} radar objects...")
        result.store.bulk_insert_radar_objects(obj_rows)
    if dbg_rows:
        status("parse", f"Writing {len(dbg_rows)} radar debug records...")
        result.store.bulk_insert_radar_debug(dbg_rows)

    # BLF (DBC-based CAN signals)
    for bf in case_dir.glob("*.blf"):
        status("parse", f"Parsing {bf.name} (DBC decode)...")
        parser = BlfParser(bf, dbc_loader=result.dbc)
        blf_metas.append(parser.get_metadata())
        result.store.bulk_insert_can(parser.iter_frames(decode=True))

    result.bag_meta = _merge_metas(bag_metas) if bag_metas else None
    result.blf_meta = _merge_metas(blf_metas) if blf_metas else None

    # P1.1: MF4 measurement data
    mf4_metas: list[dict] = []
    mf4_available = check_mf4_dependency()
    for mf in case_dir.glob("*.mf4"):
        if not mf4_available:
            status("parse", f"MF4 {mf.name} found but asammdf/mffparser not installed — skipping")
            break
        status("parse", f"Parsing {mf.name} (MF4 measurement data)...")
        parser = Mf4Parser(mf)
        mf4_metas.append(parser.get_metadata())
        parser.write_to_store(result.store)

    result.mf4_meta = _merge_metas(mf4_metas) if mf4_metas else None

    if result.bag_meta and result.blf_meta:
        blf_start = blf_end = None
        if result.blf_meta.get("start_time"):
            blf_start = datetime.datetime.fromisoformat(result.blf_meta["start_time"]).timestamp()
        if result.blf_meta.get("end_time"):
            blf_end = datetime.datetime.fromisoformat(result.blf_meta["end_time"]).timestamp()
        result.sync = TimeSync(
            bag_start_ns=result.bag_meta.get("start_ns"),
            bag_end_ns=result.bag_meta.get("end_ns"),
            blf_start_sec=blf_start,
            blf_end_sec=blf_end,
        )
        status("parse", f"TimeSync offset={result.sync.offset_sec:.3f}s")

    # Build warning events from radar_objects
    _build_warning_events(result.store, status)

    return result


def _build_warning_events(store: FrameStore, status_fn) -> None:
    """Detect warning flag edges in radar_objects with gap-based segmentation."""
    _GAP_NS = int(0.5 * 1e9)  # 500ms gap → new event segment
    events: list[dict] = []

    for func_name, col in _FLAG_COL_MAP.items():
        rows = store.conn.execute(
            f"SELECT timestamp_ns, radar_id, obj_id, {col}, dist_x, ttc "
            f"FROM radar_objects WHERE {col} != 0 "
            f"ORDER BY radar_id, obj_id, timestamp_ns"
        ).fetchall()
        if not rows:
            continue

        # Group by (radar_id, obj_id), detect segments with gap threshold
        cur_key: tuple = (None, None)
        seg_start = 0
        seg_last = 0
        seg_min_dist = 999.0
        seg_max_ttc: float | None = None

        def _flush_segment():
            if cur_key[0] is None:
                return
            events.append({
                "func_name": func_name,
                "direction": None,
                "radar_id": cur_key[0],
                "start_ns": seg_start,
                "end_ns": seg_last,
                "trigger_source": "obj_flag",
                "associated_obj_id": cur_key[1],
                "max_ttc": seg_max_ttc,
                "min_dist": seg_min_dist if seg_min_dist < 999 else None,
            })

        for r in rows:
            ts, rid, oid = r[0], r[1], r[2]
            key = (rid, oid)

            if key != cur_key or (ts - seg_last) > _GAP_NS:
                _flush_segment()
                cur_key = key
                seg_start = ts
                seg_last = ts
                seg_min_dist = abs(r[4]) if r[4] is not None else 999.0
                seg_max_ttc = r[5]
            else:
                seg_last = ts
                if r[4] is not None:
                    seg_min_dist = min(seg_min_dist, abs(r[4]))
                if r[5] is not None and (seg_max_ttc is None or r[5] > seg_max_ttc):
                    seg_max_ttc = r[5]

        _flush_segment()

    if events:
        status_fn("parse", f"Built {len(events)} warning events")
        store.insert_warning_events(events)


def _merge_metas(metas: list[dict]) -> dict:
    """Merge metadata dicts from multiple BAG or BLF files."""
    if len(metas) == 1:
        return metas[0]
    merged: dict = {}
    total_msgs = 0
    files = []
    for m in metas:
        files.append(m.get("file", "?"))
        total_msgs += m.get("message_count", 0)
        for k, v in m.items():
            if k in ("file", "message_count"):
                continue
            if k == "topics" and isinstance(v, dict):
                merged.setdefault("topics", {})
                for tk, tv in v.items():
                    if tk not in merged["topics"]:
                        merged["topics"][tk] = tv
                    else:
                        merged["topics"][tk]["msg_count"] = (
                            merged["topics"][tk].get("msg_count", 0)
                            + tv.get("msg_count", 0)
                        )
            elif k in ("start_ns", "start_time"):
                if k not in merged or v < merged[k]:
                    merged[k] = v
            elif k in ("end_ns", "end_time"):
                if k not in merged or v > merged[k]:
                    merged[k] = v
            elif k == "duration_sec":
                merged[k] = merged.get(k, 0) + (v or 0)
            elif k == "unique_can_ids":
                merged[k] = max(merged.get(k, 0), v or 0)
            elif k not in merged:
                merged[k] = v
    merged["file"] = " + ".join(files)
    merged["message_count"] = total_msgs
    return merged
