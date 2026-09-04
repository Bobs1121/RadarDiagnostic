# -*- coding: utf-8 -*-
"""
SQLite-based frame store for structured bag/blf data.
Supports fast queries by time range, variable name, and topic/CAN ID.
"""
import json
import sqlite3
from pathlib import Path
from typing import Optional


class FrameStore:
    """Persist parsed frames to SQLite for fast querying."""

    def __init__(self, db_path: str | Path = ":memory:"):
        self.db_path = str(db_path)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_tables()

    def _init_tables(self):
        c = self.conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS bag_frames (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp_ns INTEGER NOT NULL,
                timestamp_sec REAL NOT NULL,
                topic TEXT NOT NULL,
                msg_type TEXT,
                data_size INTEGER,
                fields_json TEXT
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS can_frames (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                datetime_str TEXT,
                channel INTEGER,
                can_id INTEGER NOT NULL,
                can_id_hex TEXT,
                dlc INTEGER,
                message_name TEXT,
                raw_hex TEXT,
                signals_json TEXT
            )
        """)
        # P1-1: per-object per-frame per-radar table
        c.execute("""
            CREATE TABLE IF NOT EXISTS radar_objects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp_ns INTEGER NOT NULL,
                radar_id INTEGER NOT NULL,
                frame_id INTEGER,
                obj_id INTEGER NOT NULL,
                obj_class INTEGER,
                life_cycle INTEGER,
                dist_x REAL,
                dist_y REAL,
                vel_x REAL,
                vel_y REAL,
                vel_abs_x REAL,
                vel_abs_y REAL,
                ttc REAL,
                ddci REAL,
                bsd_flag INTEGER DEFAULT 0,
                lca_flag INTEGER DEFAULT 0,
                dow_flag INTEGER DEFAULT 0,
                rcw_flag INTEGER DEFAULT 0,
                rcta_flag INTEGER DEFAULT 0,
                rctb_flag INTEGER DEFAULT 0,
                fcta_flag INTEGER DEFAULT 0,
                fctb_flag INTEGER DEFAULT 0,
                source TEXT DEFAULT 'wfa'
            )
        """)
        # P1-2: per-frame per-radar debug snapshot
        c.execute("""
            CREATE TABLE IF NOT EXISTS radar_debug (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp_ns INTEGER NOT NULL,
                radar_id INTEGER NOT NULL,
                frame_id INTEGER,
                actual_spd REAL,
                yaw_rate REAL,
                lat_accel REAL,
                long_accel REAL,
                steer_angle REAL,
                actual_gear INTEGER,
                fl_whl_spd REAL,
                fr_whl_spd REAL,
                rl_whl_spd REAL,
                rr_whl_spd REAL,
                bsd_enable INTEGER,
                lca_enable INTEGER,
                dow_enable INTEGER,
                rcw_enable INTEGER,
                rcta_enable INTEGER,
                rctb_enable INTEGER,
                fcta_enable INTEGER,
                fctb_enable INTEGER,
                bld_warning_flag INTEGER,
                bld_percent INTEGER,
                bld_score INTEGER
            )
        """)
        # P1-3: warning edge events
        c.execute("""
            CREATE TABLE IF NOT EXISTS warning_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                func_name TEXT NOT NULL,
                direction TEXT,
                radar_id INTEGER,
                start_ns INTEGER NOT NULL,
                end_ns INTEGER,
                duration_ms REAL,
                trigger_source TEXT,
                associated_obj_id INTEGER,
                max_ttc REAL,
                min_dist REAL
            )
        """)

        # --- Indices ---
        c.execute("CREATE INDEX IF NOT EXISTS idx_bag_ts ON bag_frames(timestamp_ns)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_bag_topic ON bag_frames(topic)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_can_ts ON can_frames(timestamp)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_can_id ON can_frames(can_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_can_name ON can_frames(message_name)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_can_id_ts ON can_frames(can_id, timestamp)")
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_bag_dedup ON bag_frames(timestamp_ns, topic)")
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_can_dedup ON can_frames(timestamp, can_id, channel)")
        # radar_objects indices
        c.execute("CREATE INDEX IF NOT EXISTS idx_ro_ts ON radar_objects(timestamp_ns)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_ro_radar_ts ON radar_objects(radar_id, timestamp_ns)")
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_ro_dedup ON radar_objects(timestamp_ns, radar_id, obj_id, source)")
        # radar_debug indices
        c.execute("CREATE INDEX IF NOT EXISTS idx_rd_ts ON radar_debug(timestamp_ns)")
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_rd_dedup ON radar_debug(timestamp_ns, radar_id)")
        # warning_events indices
        c.execute("CREATE INDEX IF NOT EXISTS idx_we_func ON warning_events(func_name)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_we_ts ON warning_events(start_ns)")
        # V4 P2: 信号目录 + 数据质量审计（向后兼容，新表不影响既有查询）
        c.execute("""
            CREATE TABLE IF NOT EXISTS signal_catalog (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_name TEXT NOT NULL,
                source_kind TEXT DEFAULT '',
                can_id INTEGER,
                message_name TEXT,
                valid_ratio REAL DEFAULT 0.0,
                is_placeholder INTEGER DEFAULT 0,
                UNIQUE(signal_name, source_kind)
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS data_quality (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_name TEXT NOT NULL,
                source_kind TEXT DEFAULT '',
                sample_count INTEGER DEFAULT 0,
                distinct_count INTEGER DEFAULT 0,
                minimum REAL,
                maximum REAL,
                is_constant INTEGER DEFAULT 0,
                is_placeholder INTEGER DEFAULT 0,
                verdict TEXT DEFAULT 'ok',
                note TEXT DEFAULT ''
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_sigcat_name ON signal_catalog(signal_name)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_dq_name ON data_quality(signal_name)")
        self.conn.commit()

    def insert_bag_frame(self, frame) -> None:
        self.conn.execute(
            "INSERT INTO bag_frames (timestamp_ns, timestamp_sec, topic, msg_type, data_size, fields_json) VALUES (?,?,?,?,?,?)",
            (
                frame.timestamp_ns,
                frame.timestamp_ns / 1e9,
                frame.topic,
                frame.msg_type,
                frame.data_size,
                json.dumps(frame.fields, default=str),
            ),
        )

    def insert_can_frame(self, frame) -> None:
        self.conn.execute(
            "INSERT INTO can_frames (timestamp, datetime_str, channel, can_id, can_id_hex, dlc, message_name, raw_hex, signals_json) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                frame.timestamp,
                frame.datetime_str,
                frame.channel,
                frame.can_id,
                frame.can_id_hex,
                frame.dlc,
                frame.message_name,
                frame.raw_hex,
                json.dumps(frame.signals, default=str),
            ),
        )

    def bulk_insert_bag(self, frames, batch_size: int = 1000) -> int:
        """Insert bag frames in batches, skipping duplicates. Returns total count."""
        count = 0
        batch = []
        sql = "INSERT OR IGNORE INTO bag_frames (timestamp_ns, timestamp_sec, topic, msg_type, data_size, fields_json) VALUES (?,?,?,?,?,?)"
        for f in frames:
            batch.append((
                f.timestamp_ns, f.timestamp_ns / 1e9, f.topic,
                f.msg_type, f.data_size, json.dumps(f.fields, default=str),
            ))
            count += 1
            if len(batch) >= batch_size:
                self.conn.executemany(sql, batch)
                batch.clear()
        if batch:
            self.conn.executemany(sql, batch)
        self.conn.commit()
        return count

    def bulk_insert_can(self, frames, batch_size: int = 1000) -> int:
        """Insert CAN frames in batches, skipping duplicates. Returns total count."""
        count = 0
        batch = []
        sql = "INSERT OR IGNORE INTO can_frames (timestamp, datetime_str, channel, can_id, can_id_hex, dlc, message_name, raw_hex, signals_json) VALUES (?,?,?,?,?,?,?,?,?)"
        for f in frames:
            batch.append((
                f.timestamp, f.datetime_str, f.channel, f.can_id,
                f.can_id_hex, f.dlc, f.message_name, f.raw_hex,
                json.dumps(f.signals, default=str),
            ))
            count += 1
            if len(batch) >= batch_size:
                self.conn.executemany(sql, batch)
                batch.clear()
        if batch:
            self.conn.executemany(sql, batch)
        self.conn.commit()
        return count

    def bulk_insert_can_from_dict(self, frames: list[dict], batch_size: int = 1000) -> int:
        """Insert CAN frames from dict list (used by Mf4Parser). Returns total count."""
        count = 0
        batch = []
        sql = "INSERT OR IGNORE INTO can_frames (timestamp, datetime_str, channel, can_id, can_id_hex, dlc, message_name, raw_hex, signals_json) VALUES (?,?,?,?,?,?,?,?,?)"
        for f in frames:
            batch.append((
                f["timestamp"], f.get("datetime_str", ""), f.get("channel", 0),
                f.get("can_id", 0), f.get("can_id_hex", "0x000"),
                f.get("dlc", 0), f.get("message_name", ""),
                f.get("raw_hex", ""),
                json.dumps(f.get("signals", {}), default=str),
            ))
            count += 1
            if len(batch) >= batch_size:
                self.conn.executemany(sql, batch)
                batch.clear()
        if batch:
            self.conn.executemany(sql, batch)
        self.conn.commit()
        return count

    # ---- radar_objects bulk insert & query ----

    def bulk_insert_radar_objects(self, objects: list[dict], batch_size: int = 500) -> int:
        sql = """INSERT OR IGNORE INTO radar_objects
            (timestamp_ns, radar_id, frame_id, obj_id, obj_class, life_cycle,
             dist_x, dist_y, vel_x, vel_y, vel_abs_x, vel_abs_y,
             ttc, ddci, bsd_flag, lca_flag, dow_flag, rcw_flag,
             rcta_flag, rctb_flag, fcta_flag, fctb_flag, source)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""
        batch = []
        count = 0
        for o in objects:
            batch.append((
                o["timestamp_ns"], o["radar_id"], o.get("frame_id", 0),
                o["obj_id"], o.get("obj_class", 0), o.get("life_cycle", 0),
                o.get("dist_x"), o.get("dist_y"),
                o.get("vel_x"), o.get("vel_y"),
                o.get("vel_abs_x"), o.get("vel_abs_y"),
                o.get("ttc"), o.get("ddci"),
                o.get("bsd_flag", 0), o.get("lca_flag", 0),
                o.get("dow_flag", 0), o.get("rcw_flag", 0),
                o.get("rcta_flag", 0), o.get("rctb_flag", 0),
                o.get("fcta_flag", 0), o.get("fctb_flag", 0),
                o.get("source", "wfa"),
            ))
            count += 1
            if len(batch) >= batch_size:
                self.conn.executemany(sql, batch)
                batch.clear()
        if batch:
            self.conn.executemany(sql, batch)
        self.conn.commit()
        return count

    def query_objects_in_window(
        self, time_start_ns: int, time_end_ns: int,
        radar_id: Optional[int] = None,
    ) -> list[dict]:
        sql = "SELECT * FROM radar_objects WHERE timestamp_ns >= ? AND timestamp_ns <= ?"
        params: list = [time_start_ns, time_end_ns]
        if radar_id is not None:
            sql += " AND radar_id = ?"
            params.append(radar_id)
        sql += " ORDER BY timestamp_ns, radar_id, obj_id"
        return [dict(r) for r in self.conn.execute(sql, params).fetchall()]

    def query_objects_with_warning(self, func_name: str) -> list[dict]:
        """Return objects where the specified ADAS function warning flag is non-zero."""
        col_map = {
            "BSD": "bsd_flag", "LCA": "lca_flag", "DOW": "dow_flag",
            "RCW": "rcw_flag", "RCTA": "rcta_flag", "RCTB": "rctb_flag",
            "FCTA": "fcta_flag", "FCTB": "fctb_flag",
        }
        col = col_map.get(func_name.upper())
        if not col:
            return []
        sql = f"SELECT * FROM radar_objects WHERE {col} != 0 ORDER BY timestamp_ns"
        return [dict(r) for r in self.conn.execute(sql).fetchall()]

    def get_object_trajectory(self, obj_id: int, radar_id: int) -> list[dict]:
        sql = ("SELECT * FROM radar_objects WHERE obj_id = ? AND radar_id = ? "
               "ORDER BY timestamp_ns")
        return [dict(r) for r in self.conn.execute(sql, (obj_id, radar_id)).fetchall()]

    # ---- radar_debug bulk insert & query ----

    def bulk_insert_radar_debug(self, records: list[dict], batch_size: int = 500) -> int:
        sql = """INSERT OR IGNORE INTO radar_debug
            (timestamp_ns, radar_id, frame_id,
             actual_spd, yaw_rate, lat_accel, long_accel,
             steer_angle, actual_gear,
             fl_whl_spd, fr_whl_spd, rl_whl_spd, rr_whl_spd,
             bsd_enable, lca_enable, dow_enable, rcw_enable,
             rcta_enable, rctb_enable, fcta_enable, fctb_enable,
             bld_warning_flag, bld_percent, bld_score)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""
        batch = []
        count = 0
        for r in records:
            ego = r.get("ego", {})
            adas = r.get("adas_enables", {})
            bld = r.get("bld", {})
            batch.append((
                r["timestamp_ns"], r["radar_id"], r.get("frame_id", 0),
                ego.get("actual_spd"), ego.get("yaw_rate"),
                ego.get("lat_accel"), ego.get("long_accel"),
                ego.get("steer_angle"), ego.get("actual_gear"),
                ego.get("fl_whl_spd"), ego.get("fr_whl_spd"),
                ego.get("rl_whl_spd"), ego.get("rr_whl_spd"),
                int(adas.get("bsd", False)), int(adas.get("lca", False)),
                int(adas.get("dow", False)), int(adas.get("rcw", False)),
                int(adas.get("rcta", False)), int(adas.get("rctb", False)),
                int(adas.get("fcta", False)), int(adas.get("fctb", False)),
                bld.get("bld_warning_flag"), bld.get("bld_percent"),
                bld.get("bld_score"),
            ))
            count += 1
            if len(batch) >= batch_size:
                self.conn.executemany(sql, batch)
                batch.clear()
        if batch:
            self.conn.executemany(sql, batch)
        self.conn.commit()
        return count

    def query_debug_in_window(
        self, time_start_ns: int, time_end_ns: int,
        radar_id: Optional[int] = None,
    ) -> list[dict]:
        sql = "SELECT * FROM radar_debug WHERE timestamp_ns >= ? AND timestamp_ns <= ?"
        params: list = [time_start_ns, time_end_ns]
        if radar_id is not None:
            sql += " AND radar_id = ?"
            params.append(radar_id)
        sql += " ORDER BY timestamp_ns"
        return [dict(r) for r in self.conn.execute(sql, params).fetchall()]

    # ---- warning_events insert & query ----

    def insert_warning_events(self, events: list[dict]) -> int:
        sql = """INSERT INTO warning_events
            (func_name, direction, radar_id, start_ns, end_ns, duration_ms,
             trigger_source, associated_obj_id, max_ttc, min_dist)
            VALUES (?,?,?,?,?,?,?,?,?,?)"""
        batch = []
        for e in events:
            dur = (e["end_ns"] - e["start_ns"]) / 1e6 if e.get("end_ns") else None
            batch.append((
                e["func_name"], e.get("direction"), e.get("radar_id"),
                e["start_ns"], e.get("end_ns"), dur,
                e.get("trigger_source"), e.get("associated_obj_id"),
                e.get("max_ttc"), e.get("min_dist"),
            ))
        if batch:
            self.conn.executemany(sql, batch)
            self.conn.commit()
        return len(batch)

    def query_warning_events(self, func_name: Optional[str] = None) -> list[dict]:
        if func_name:
            rows = self.conn.execute(
                "SELECT * FROM warning_events WHERE func_name = ? ORDER BY start_ns",
                (func_name,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM warning_events ORDER BY start_ns"
            ).fetchall()
        return [dict(r) for r in rows]

    def query_bag_by_topic(
        self, topic: str, time_start_ns: Optional[int] = None, time_end_ns: Optional[int] = None,
    ) -> list[dict]:
        sql = "SELECT * FROM bag_frames WHERE topic = ?"
        params: list = [topic]
        if time_start_ns is not None:
            sql += " AND timestamp_ns >= ?"
            params.append(time_start_ns)
        if time_end_ns is not None:
            sql += " AND timestamp_ns <= ?"
            params.append(time_end_ns)
        sql += " ORDER BY timestamp_ns"
        rows = self.conn.execute(sql, params).fetchall()
        return [self._row_to_dict(r, parse_json="fields_json") for r in rows]

    def query_can_by_id(
        self, can_id: int, time_start: Optional[float] = None, time_end: Optional[float] = None,
    ) -> list[dict]:
        sql = "SELECT * FROM can_frames WHERE can_id = ?"
        params: list = [can_id]
        if time_start is not None:
            sql += " AND timestamp >= ?"
            params.append(time_start)
        if time_end is not None:
            sql += " AND timestamp <= ?"
            params.append(time_end)
        sql += " ORDER BY timestamp"
        rows = self.conn.execute(sql, params).fetchall()
        return [self._row_to_dict(r, parse_json="signals_json") for r in rows]

    def query_can_by_name(self, message_name: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM can_frames WHERE message_name = ? ORDER BY timestamp",
            (message_name,),
        ).fetchall()
        return [self._row_to_dict(r, parse_json="signals_json") for r in rows]

    def query_signal_timeline(self, can_id: int, signal_name: str) -> list[dict]:
        """Extract a single signal's values over time from stored CAN frames."""
        rows = self.conn.execute(
            "SELECT timestamp, datetime_str, signals_json FROM can_frames WHERE can_id = ? ORDER BY timestamp",
            (can_id,),
        ).fetchall()
        timeline = []
        for r in rows:
            signals = json.loads(r["signals_json"]) if r["signals_json"] else {}
            if signal_name in signals:
                timeline.append({
                    "timestamp": r["timestamp"],
                    "datetime": r["datetime_str"],
                    "value": signals[signal_name],
                })
        return timeline

    def get_bag_topics(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT topic, msg_type, COUNT(*) as count FROM bag_frames GROUP BY topic ORDER BY count DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_can_ids(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT can_id, can_id_hex, message_name, COUNT(*) as count FROM can_frames GROUP BY can_id ORDER BY count DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_signal_inventory(self, sample_per_id: int = 3) -> list[dict]:
        """
        Discover all available CAN message names and their signal names
        by sampling a few frames per CAN ID.
        """
        ids_info = self.get_can_ids()
        inventory = []
        for info in ids_info:
            can_id = info["can_id"]
            rows = self.conn.execute(
                "SELECT signals_json FROM can_frames WHERE can_id = ? LIMIT ?",
                (can_id, sample_per_id),
            ).fetchall()
            signal_names = set()
            for r in rows:
                if r["signals_json"]:
                    try:
                        sigs = json.loads(r["signals_json"])
                        signal_names.update(sigs.keys())
                    except json.JSONDecodeError:
                        pass
            if signal_names:
                inventory.append({
                    "can_id": can_id,
                    "can_id_hex": info["can_id_hex"],
                    "message_name": info.get("message_name") or "?",
                    "frame_count": info["count"],
                    "signals": sorted(signal_names),
                })
        return inventory

    def get_time_range(self) -> dict:
        bag_range = self.conn.execute(
            "SELECT MIN(timestamp_sec) as min_t, MAX(timestamp_sec) as max_t FROM bag_frames"
        ).fetchone()
        can_range = self.conn.execute(
            "SELECT MIN(timestamp) as min_t, MAX(timestamp) as max_t FROM can_frames"
        ).fetchone()
        return {
            "bag": {"start": bag_range["min_t"], "end": bag_range["max_t"]} if bag_range["min_t"] else None,
            "can": {"start": can_range["min_t"], "end": can_range["max_t"]} if can_range["min_t"] else None,
        }

    def _row_to_dict(self, row, parse_json: Optional[str] = None) -> dict:
        d = dict(row)
        if parse_json and parse_json in d and d[parse_json]:
            try:
                d[parse_json.replace("_json", "")] = json.loads(d[parse_json])
            except json.JSONDecodeError:
                pass
            del d[parse_json]
        return d

    def close(self):
        self.conn.close()
