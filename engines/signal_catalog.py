# -*- coding: utf-8 -*-
"""信号目录与模糊查找（V4 P3，signal-extract）。

把分散的信号名来源收口为一个可查询目录，供 SignalExtractor 做三级匹配：
1. 精确 / 别名
2. 语义（tokenize + 相似度打分）
3. 跨源对齐（同一物理量在 CAN / 雷达内部 / radar_debug 间的候选）

信号名来源：
- CAN: FrameStore 的 get_signal_inventory() / get_can_ids()
- 雷达内部: radar_debug 表的实际数据列
- DBC/risidual 字典: tools/arbe 的 generated_signal_map.py（含中文/别名注释）
- 已有映射: source_docs/signal_mapping.json（内部变量 ↔ CAN）

无 LLM，纯确定性。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


#: 中文物理量别名 → 常见英文 token（用于语义匹配）
_CN_ALIASES: dict[str, list[str]] = {
    "车速": ["speed", "spd", "velocity", "veh_spd", "car_spd", "actual_spd", "vehicle_speed"],
    "速度": ["speed", "spd", "velocity", "veh_spd", "car_spd"],
    "油门": ["accel", "accelerator", "pedal", "accpdl", "throttle"],
    "刹车": ["brake", "brk", "pedal", "decel"],
    "转向": ["steer", "steering", "wheel_angle", "yaw"],
    "档位": ["gear", "gearpos", "shift"],
    "横摆": ["yaw", "yaw_rate"],
    "加速度": ["accel", "acc", "lat_accel", "long_accel"],
    "报警": ["warn", "warning", "alert", "flag"],
    "目标": ["obj", "object", "target", "dist_x", "dist_y"],
    "距离": ["dist", "range", "dist_x", "dist_y"],
    "时间": ["time", "ttc", "ddci", "timestamp"],
    "盲区": ["bsd", "blind", "lcw"],
    "变道": ["lca", "lane", "change"],
    "开门": ["dow", "door"],
    "后碰": ["rcw", "rcw"],
    "后交叉": ["rcta", "rctb", "going"],
    "前碰": ["fcta", "fctb"],
}


@dataclass
class CatalogEntry:
    """一条目录项：一个信号名 + 其来源与别名。"""

    name: str
    source: str = ""            # can / radar_debug / get_signal_inventory / dbc_dict
    aliases: list[str] = field(default_factory=list)
    can_id: Optional[int] = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "source": self.source,
            "aliases": self.aliases,
            "can_id": self.can_id,
        }


class SignalCatalog:
    """构建并查询信号目录。"""

    def __init__(self, store: Any = None, source_root: Optional[str] = None):
        self.store = store
        self.source_root = source_root
        self._entries: list[CatalogEntry] = []
        self._index: dict[str, int] = {}   # name.lower() -> index

    def build(self) -> "SignalCatalog":
        self._entries = []
        self._index = {}
        self._collect_from_store()
        self._collect_from_dbc_dict()
        return self

    # ── 目录构建 ────────────────────────────────────────────────────

    def _add(self, name: str, source: str, aliases: Optional[list[str]] = None,
             can_id: Optional[int] = None) -> None:
        if not name:
            return
        key = name.lower()
        if key in self._index:
            return
        self._index[key] = len(self._entries)
        self._entries.append(CatalogEntry(
            name=name, source=source,
            aliases=aliases or [], can_id=can_id,
        ))

    def _collect_from_store(self) -> None:
        if self.store is None:
            return
        try:
            # CAN 信号：按 can_id 分组
            if hasattr(self.store, "get_can_ids"):
                for info in self.store.get_can_ids():
                    can_id = info.get("can_id")
                    # 拿该 can_id 的采样信号名
                    rows = self.store.conn.execute(
                        "SELECT signals_json FROM can_frames WHERE can_id=? LIMIT 6",
                        (can_id,),
                    ).fetchall()
                    names: set[str] = set()
                    for row in rows:
                        try:
                            sigs = json.loads(row[0])
                        except Exception:
                            continue
                        if isinstance(sigs, dict):
                            names.update(sigs.keys())
                    for name in sorted(names):
                        self._add(name, "can", can_id=can_id)
        except Exception:
            pass
        try:
            # radar_debug 数据列
            cols = self.store.conn.execute("PRAGMA table_info(radar_debug)").fetchall()
        except Exception:
            cols = []
        _META = {"id", "timestamp_ns", "radar_id", "frame_id"}
        for col in cols:
            name = str(col[1])
            if name not in _META:
                self._add(name, "radar_debug")

    def _collect_from_dbc_dict(self) -> None:
        """读 tools/arbe generated_signal_map.py（若存在）拿 DBC 信号字典。"""
        candidates = [
            Path(self.source_root) if self.source_root else None,
        ]
        # 尝试相对本文件的项目路径
        proj_root = Path(__file__).resolve().parents[2]
        for cand in [proj_root / "tools" / "arbe" / "src" / "common_can_signal_publisher"
                     / "scripts" / "generated_signal_map.py"]:
            if cand.exists():
                try:
                    import importlib.util
                    spec = importlib.util.spec_from_file_location("gsm", cand)
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                    for row in getattr(mod, "SIGNALS", []):
                        # row: (frame_id, msg, sig_name, field_name, ros_type, index)
                        if len(row) >= 3:
                            self._add(str(row[2]), "dbc_dict",
                                      aliases=[str(row[3])] if len(row) > 3 else [])
                except Exception:
                    pass
                break

    # ── 查询 ────────────────────────────────────────────────────────

    def fuzzy_lookup(self, query: str, top_k: int = 8) -> list[CatalogEntry]:
        """三级匹配：精确/别名 → tokenize 语义 → 打分排序。"""
        if not query:
            return []
        q = query.strip()
        q_lower = q.lower()

        # 1) 精确
        exact = self._entries[self._index[q_lower]] if q_lower in self._index else None
        # 2) 子串 / 别名
        alias_hits: list[CatalogEntry] = []
        for e in self._entries:
            if e.name.lower() == q_lower or q_lower in e.name.lower():
                alias_hits.append(e)
            elif any(a.lower() == q_lower for a in e.aliases):
                alias_hits.append(e)

        # 3) token 语义打分（含英文同义词/缩写归一）
        tokens = _tokens(q)
        aliases = _expand_aliases(q)     # 中文词 → 英文候选
        en_synonyms = _english_synonyms(tokens)   # speed→spd, velocity→spd ...
        scored: list[tuple[float, CatalogEntry]] = []
        for e in self._entries:
            enc = e.name.lower()
            score = 0.0
            if q_lower in enc:
                score += 5.0
            for t in tokens:
                if t and t in enc:
                    score += 2.0
            for s in en_synonyms:
                if s and s in enc:
                    score += 2.5
            for al in aliases:
                if al and al in enc:
                    score += 3.0
            for a in e.aliases:
                if a.lower() == q_lower:
                    score += 4.0
            if score > 0:
                scored.append((score, e))

        # 合并：精确/别名命中优先，其余按分排序
        dedup: dict[str, CatalogEntry] = {}
        for entry in alias_hits:
            dedup.setdefault(entry.name, entry)
        for score, entry in sorted(scored, key=lambda x: -x[0]):
            dedup.setdefault(entry.name, entry)
        result = list(dedup.values())
        if exact and exact.name not in [e.name for e in result]:
            result.insert(0, exact)
        return result[:top_k]

    def lookup_exact(self, name: str) -> Optional[CatalogEntry]:
        return self._entries[self._index[name.lower()]] if name.lower() in self._index else None

    def all_names(self) -> list[str]:
        return [e.name for e in self._entries]


def _tokens(s: str) -> list[str]:
    """切出字母数字 token（去掉下划线/空格）。"""
    return [t for t in re.findall(r"[a-z0-9]+", s.lower()) if len(t) >= 2]


def _english_synonyms(tokens: list[str]) -> list[str]:
    """把查询词的英文同义词/缩写展开，便于对信号名打分。

    例：speed→spd、accelerator→accel、brake→brk、warning→warn。
    """
    _SIN: dict[str, tuple[str, ...]] = {
        "speed": ("spd", "velocity", "vel"),
        "velocity": ("spd", "speed", "vel"),
        "vel": ("spd", "speed"),
        "accelerator": ("accel", "acc", "pedal"),
        "pedal": ("accel", "acc"),
        "brake": ("brk", "decel"),
        "decel": ("brk",),
        "warning": ("warn",),
        "alert": ("warn",),
        "steer": ("steering",),
        "target": ("obj", "object"),
        "time": ("ttc", "ddci"),
        "distance": ("dist", "range"),
    }
    out: list[str] = []
    for t in tokens:
        aliases = _SIN.get(t)
        if aliases:
            out.extend(aliases)
    return out


def _expand_aliases(query: str) -> list[str]:
    """把中文词展开成英文候选，便于对英文信号名打分。"""
    out: list[str] = []
    for cn, en_terms in _CN_ALIASES.items():
        if cn in query:
            out.extend(en_terms)
    return out


__all__ = ["SignalCatalog", "CatalogEntry"]