# -*- coding: utf-8 -*-
"""数据质量审计（V4 P2）。

对 FrameStore 中每个可观测信号检测三类"不可信"特征，产出 data_quality
记录供下游（investigation / data_probe / signal_audit / 报告）过滤：

- **占位（placeholder）**：signal_valid 为 0，或该信号来自 bag 回放时
  CAN 占位发布（如 PublicCan 恒定 nan/默认值）。
- **恒定（constant）**：全程只有 1 个不同值（物理上极可疑，但不是绝对
  无效，仍尽力保留 verdict）。
- **物理不可能（physically_impossible）**：取值超出该物理量合理范围
  （如车速 281.53 m/s ≈ 1013 km/h）。

设计为确定性、无 LLM，可在 bag-only / blf-only 下独立运行。
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Optional


#: 常见物理量合理上限（超出即判 physically_impossible）
#: 单位示意：spd(m/s)、gear(档位枚举)、角度、加速度。保守放大即可。
_PHYSICAL_LIMITS: dict[str, float] = {
    "veh_spd": 120.0,        # m/s，约 432 km/h 上限
    "veh_speed": 120.0,
    "car_spd": 120.0,
    "actual_spd": 120.0,
    "yaw_rate": 10.0,        # rad/s
    "lat_accel": 25.0,       # m/s^2
    "long_accel": 25.0,
    "steer_angle": 720.0,    # 度（可选）
    "fl_whl_spd": 120.0,
    "fr_whl_spd": 120.0,
    "rl_whl_spd": 120.0,
    "rr_whl_spd": 120.0,
    "rctbtargetdecel": 30.0, # m/s^2 减速度
    "ttc": 100.0,
    "ddci": 100.0,
    "dist_x": 500.0,
    "dist_y": 500.0,
}

#: 恒定判定阈值：一个信号若 distinct 值数 ≤ 1 视为恒定。
_CONSTANT_MAX_DISTINCT = 1

#: 参与数据质量采样的最大行数（控制扫描内存）。
_MAX_SAMPLE_ROWS = 200000


@dataclass
class SignalQuality:
    """单个信号的数据质量结论。"""

    signal_name: str
    source_kind: str = ""           # bag / blf / internal / radar_debug
    can_id: Optional[int] = None
    sample_count: int = 0
    distinct_count: int = 0
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    mean: Optional[float] = None
    is_constant: bool = False
    is_placeholder: bool = False
    is_physically_impossible: bool = False
    verdict: str = "ok"             # ok / placeholder / constant / impossible
    note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class DataQualityAuditor:
    """对 FrameStore 做数据质量审计，产出 list[SignalQuality]。"""

    def __init__(self, store: Any):
        self.store = store

    # ── 主入口 ──────────────────────────────────────────────────────

    def audit(self, source_kind: str = "can", limit: int = 1000) -> list[SignalQuality]:
        """扫描 store 的信号目录，返回每条信号的质量审计。

        Args:
            source_kind: 限定数据来源（can / radar_debug / bag），用于可否
                分类。默认 can。
            limit: 最多审计多少条信号（防御超大目录）。
        """
        out: list[SignalQuality] = []
        for signal_name in self._iter_signal_names(limit):
            samples = self._collect_samples(signal_name)
            q = self._audit_single(signal_name, source_kind, samples)
            out.append(q)
        return out

    def audit_one(self, signal_name: str, source_kind: str = "can") -> SignalQuality:
        samples = self._collect_samples(signal_name)
        return self._audit_single(signal_name, source_kind, samples)

    # ------------------------------------------------------------------
    # 实现细节
    # ------------------------------------------------------------------

    def _iter_signal_names(self, limit: int):
        """fetch 可用信号名集合（can 的 signals + radar_debug 数据列）。"""
        # 明确排除的元数据/主键列（不是真实信号）
        _META = {
            "id", "timestamp", "timestamp_ns", "timestamp_sec",
            "datetime_str", "channel", "can_id", "can_id_hex", "dlc",
            "message_name", "raw_hex", "radar_id", "frame_id", "signals_json",
        }
        names: list[str] = []
        try:
            rows = self.store.conn.execute(
                "SELECT DISTINCT signals_json FROM can_frames LIMIT 200"
            ).fetchall()
            import json as _json
            for row in rows:
                try:
                    sigs = _json.loads(row[0])
                except Exception:
                    continue
                if isinstance(sigs, dict):
                    for name in sigs.keys():
                        if name and name not in names:
                            names.append(str(name))
        except Exception:
            pass
        try:
            cols = self.store.conn.execute(
                "PRAGMA table_info(radar_debug)"
            ).fetchall()
            for row in cols:
                name = str(row[1])
                if name and name not in _META and name not in names:
                    names.append(name)
        except Exception:
            pass
        return names[:limit]

    def _collect_samples(self, signal_name: str) -> list[float]:
        """从 can_frames / radar_debug 收集采样值（容错，不 raise）。"""
        samples: list[float] = []
        # 1) 尝试从 can_frames 的 signals 表按信号名收（最通用）
        try:
            rows = self.store.conn.execute(
                "SELECT signals_json FROM can_frames "
                "WHERE signals_json LIKE ? LIMIT ?",
                (f"%{signal_name}%", _MAX_SAMPLE_ROWS),
            ).fetchall()
            for row in rows:
                import json as _json
                try:
                    sigs = _json.loads(row[0])
                except Exception:
                    continue
                val = sigs.get(signal_name)
                if isinstance(val, (int, float)) and not isinstance(val, bool):
                    samples.append(float(val))
        except Exception:
            pass
        return samples

    def _audit_single(
        self, signal_name: str, source_kind: str, samples: list[float]
    ) -> SignalQuality:
        if not samples:
            return SignalQuality(
                signal_name=signal_name,
                source_kind=source_kind,
                sample_count=0,
                verdict="n/a",
                note="no samples",
            )

        distinct = sorted(set(round(s, 4) for s in samples))
        distinct_count = len(distinct)
        is_constant = distinct_count <= _CONSTANT_MAX_DISTINCT
        low = min(samples)
        high = max(samples)

        is_impossible = False
        limit_key = self._match_limit_key(signal_name)
        if limit_key and (high > _PHYSICAL_LIMITS[limit_key] or low < -_PHYSICAL_LIMITS[limit_key]):
            is_impossible = True

        # 占位判定：恒定值高度疑似占位（尤其物理不可能者）
        is_placeholder = is_constant or is_impossible

        if is_placeholder and is_impossible:
            verdict = "impossible"
        elif is_placeholder and is_constant:
            verdict = "placeholder"
        else:
            verdict = "ok"

        note = ""
        if is_impossible:
            note = f"out of physical range ({low:g}..{high:g})"
        elif is_constant:
            note = "constant value (possible placeholder)"

        return SignalQuality(
            signal_name=signal_name,
            source_kind=source_kind,
            sample_count=len(samples),
            distinct_count=distinct_count,
            minimum=low,
            maximum=high,
            is_constant=is_constant,
            is_placeholder=is_placeholder,
            is_physically_impossible=is_impossible,
            verdict=verdict,
            note=note,
        )

    @staticmethod
    def _match_limit_key(name: str) -> Optional[str]:
        """把信号名匹配到物理量上限表的下划线字段名。"""
        lower = name.lower()
        for key in _PHYSICAL_LIMITS:
            if key in lower:
                return key
        return None


def audit_inventory(
    store: Any, source_kind: str = "can", limit: int = 1000
) -> list[dict]:
    """便捷函数：返回数据质量审计的 dict 列表（供报告/pi 用）。"""
    auditor = DataQualityAuditor(store)
    return [q.to_dict() for q in auditor.audit(source_kind=source_kind, limit=limit)]


__all__ = [
    "DataQualityAuditor",
    "SignalQuality",
    "audit_inventory",
]