# -*- coding: utf-8 -*-
"""信号抽取引擎（V4 P3，signal-extract，确定性无 LLM）。

对查询做三级匹配（精确/别名 → 语义 → 跨源对齐），从 FrameStore 抽取
信号时间线，产出结构化结果（含 CSV 路径与可选 plot HTML 路径）。

跨源对齐：同一物理量在不同来源（can 信号、radar_debug 列）的候选，
统一用 "物理量语义 token" 聚合，供调用方合并成同一时间轴曲线。
"""
from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from .signal_catalog import CatalogEntry, SignalCatalog


@dataclass
class ExtractedSignal:
    """一条已抽取的信号时间线。"""

    name: str
    source: str = "can"          # can / radar_debug
    can_id: Optional[int] = None
    matched: bool = False
    matched_by: str = ""         # exact / alias / semantic
    samples: list[dict] = field(default_factory=list)

    def to_dict(self, preview: int = 5) -> dict:
        return {
            "name": self.name,
            "source": self.source,
            "can_id": self.can_id,
            "matched": self.matched,
            "matched_by": self.matched_by,
            "sample_count": len(self.samples),
            "preview": self.samples[:preview],
        }


@dataclass
class SignalExtractResult:
    query: str
    signals: list[ExtractedSignal] = field(default_factory=list)
    csv_path: str = ""
    plot_path: str = ""
    cross_source_aligned: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "signals": [s.to_dict() for s in self.signals],
            "csv_path": self.csv_path,
            "plot_path": self.plot_path,
            "cross_source_aligned": self.cross_source_aligned,
        }


class SignalExtractor:
    """从 FrameStore 抽取信号。"""

    def __init__(self, store: Any, catalog: Optional[SignalCatalog] = None):
        self.store = store
        self.catalog = catalog if catalog is not None else SignalCatalog(store).build()

    # ── 主入口 ──────────────────────────────────────────────────────

    def extract(
        self,
        query: str,
        *,
        time_window: Optional[tuple[float, float]] = None,
        output_dir: Optional[Path] = None,
        write_csv: bool = True,
    ) -> SignalExtractResult:
        result = SignalExtractResult(query=query)

        entries = self.catalog.fuzzy_lookup(query, top_k=10)
        if not entries:
            return result

        for entry in entries:
            matched_by = self._classify_match(query, entry)
            samples = self._extract_timeline(entry)
            result.signals.append(ExtractedSignal(
                name=entry.name,
                source=entry.source,
                can_id=entry.can_id,
                matched=len(samples) > 0,
                matched_by=matched_by,
                samples=samples,
            ))

        # 跨源对齐：按物理量 token 聚合（仅示：key -> [source 名]）
        result.cross_source_aligned = self._align_cross_source(result)

        if output_dir is not None:
            if write_csv and result.signals:
                result.csv_path = self._write_csv(result, output_dir)
        return result

    # ── 实现 ────────────────────────────────────────────────────────

    def _classify_match(self, query: str, entry: CatalogEntry) -> str:
        q = query.strip().lower()
        if q == entry.name.lower():
            return "exact"
        # 子串或别名命中 → alias；否则若不是精确则不细究（近似 semantic）
        if q in entry.name.lower() or any(a.lower() == q for a in entry.aliases):
            return "alias"
        return "semantic"

    def _extract_timeline(self, entry: CatalogEntry) -> list[dict]:
        """按 entry.source 抽取时间线。"""
        if entry.source == "radar_debug":
            try:
                rows = self.store.conn.execute(
                    f'SELECT timestamp_ns, "{entry.name}" FROM radar_debug '
                    f'WHERE "{entry.name}" IS NOT NULL ORDER BY timestamp_ns LIMIT 200000'
                ).fetchall()
                return [
                    {"t": float(r[0]) / 1e9, "value": r[1]}
                    for r in rows
                ]
            except Exception:
                return []
        # can：经 query_signal_timeline（需 can_id）或扫 signals_json
        if entry.can_id is not None and hasattr(self.store, "query_signal_timeline"):
            try:
                tl = self.store.query_signal_timeline(entry.can_id, entry.name)
                return [
                    {
                        "t": float(r.get("timestamp", 0.0)),
                        "value": r.get("value"),
                        "datetime": r.get("datetime", ""),
                    }
                    for r in tl
                ]
            except Exception:
                pass
        # 无 can_id：全表扫 signals_json
        try:
            rows = self.store.conn.execute(
                "SELECT timestamp, signals_json FROM can_frames LIMIT 200000"
            ).fetchall()
            out: list[dict] = []
            for r in rows:
                try:
                    sigs = json.loads(r[1])
                except Exception:
                    continue
                if entry.name in sigs:
                    out.append({"t": r[0], "value": sigs[entry.name]})
            return out
        except Exception:
            return []

    def _align_cross_source(self, result: SignalExtractResult) -> list[dict]:
        """把同物理量的不同来源候选聚成组（仅做标签，不作融合推导）。"""
        groups: dict[str, list[str]] = {}
        for s in result.signals:
            if not s.matched:
                continue
            # 用去下划线的叶子名 + 中文同义词簇归组
            leaf = s.name.lower().replace("_", "")
            for cn, terms in _CN_ALIASES_FLAT:
                if any(t.replace("_", "") in leaf for t in terms):
                    groups.setdefault(cn, []).append(s.name)
                    break
            else:
                groups.setdefault(s.name, []).append(s.name)
        return [{"physical": k, "sources": v} for k, v in groups.items()]

    def _write_csv(self, result: SignalExtractResult, output_dir: Path) -> str:
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            safe_name = _sanitize(result.query)
            path = output_dir / f"signal_extract_{safe_name}.csv"
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["signal", "source", "t", "value"])
                for s in result.signals:
                    for sample in s.samples:
                        writer.writerow([s.name, s.source, sample.get("t"), sample.get("value")])
            return str(path)
        except Exception:
            return ""


#: (物理量族, 英文 token 集合) 用于跨源聚合
_CN_SYNONYMS: list[tuple[str, list[str]]] = [
    ("车速", ["speed", "spd", "veh_spd", "car_spd", "actual_spd", "vehicle_speed"]),
    ("加速度", ["accel", "lat_accel", "long_accel", "acc"]),
    ("横摆", ["yaw"]),
    ("转向", ["steer", "steering"]),
    ("档位", ["gear", "gearpos"]),
    ("制动", ["brake", "decel", "brk"]),
    ("距离", ["dist", "range"]),
]
_CN_ALIASES_FLAT = _CN_SYNONYMS


def _sanitize(name: str) -> str:
    import re
    return re.sub(r"[^A-Za-z0-9_]", "_", name)[:60] or "signal"


__all__ = ["SignalExtractor", "SignalExtractResult", "ExtractedSignal"]