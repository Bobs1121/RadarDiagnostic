# -*- coding: utf-8 -*-
"""数据可用性分类与降级（V4 P2，US7）。

对一次案例加载结果做数据可用性分类，明确"数据不足"并给出可用能力子集，
供顶层 banner / 专家面板 DATA_AVAILABILITY 提示 / 能力降级矩阵使用。
US7 硬约束：数据不全必须优雅降级，**不得抛错终止**。

分类维度：
- has_bag           —— 有 .bag 数据（雷达内部/对象）
- has_can          —— 有可解码 CAN 信号（BLF 或 bag 内真实 CAN）
- has_dbc          —— 有 DBC（能做 CAN 解码/审计）
- has_radar_objects—— 有雷达目标对象（wfAutosarData / objectlist）
- has_source       —— 有源码（代码分析用）
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Optional


@dataclass
class DataAvailability:
    has_bag: bool = False
    has_can: bool = False
    has_dbc: bool = False
    has_radar_objects: bool = False
    has_source: bool = False

    @property
    def any_data(self) -> bool:
        return any(
            (self.has_bag, self.has_can, self.has_radar_objects)
        )

    @property
    def is_complete(self) -> bool:
        """核心分析所需数据是否齐备（bag + CAN + DBC）。"""
        return self.has_bag and (self.has_can or self.has_radar_objects)

    @property
    def missing(self) -> list[str]:
        """缺失的顶层数据源名（供报告 data_gaps 段）。"""
        gaps: list[str] = []
        if not self.has_bag:
            gaps.append("BAG")
        if not self.has_can and not self.has_radar_objects:
            gaps.append("CAN/雷达对象")
        if not self.has_dbc:
            gaps.append("DBC")
        if not self.has_source:
            gaps.append("源码")
        return gaps

    @property
    def available_capabilities(self) -> list[str]:
        """当前数据可用能力子集（降级矩阵）。"""
        caps: list[str] = []
        if self.has_bag or self.has_radar_objects:
            caps.append("signal-extract(内部/对象)")
            caps.append("data-analyze")
        if self.has_can:
            caps.append("signal-extract(CAN)")
            caps.append("signal-audit")
        if self.has_dbc:
            caps.append("CAN 解码/审计")
        if self.has_source:
            caps.append("code-learn/code-analyze/diag")
        if self.any_data:
            caps.append("diag(受限)")
        return caps

    @property
    def banner(self) -> str:
        """顶层"数据不足"banner（HITL/auto 均显示）。"""
        if self.is_complete:
            return ""
        if not self.any_data:
            return "⚠ 数据不足：未检测到 BAG / CAN / 雷达对象数据，分析结果可能为空。"
        gaps = "、".join(self.missing)
        return f"⚠ 数据部分缺失（缺 {gaps}）：仅对可用能力子集分析。"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["is_complete"] = self.is_complete
        d["any_data"] = self.any_data
        d["missing"] = self.missing
        d["available_capabilities"] = self.available_capabilities
        d["banner"] = self.banner
        return d


def classify_availability(
    store: Any,
    bag_meta: Optional[dict] = None,
    dbc: Any = None,
    source_root: Optional[str] = None,
) -> DataAvailability:
    """从 CaseLoadResult（store/bag_meta/dbc）计算数据可用性分类。

    Args:
        store: FrameStore 或 None。
        bag_meta: load_case_data 返回的 bag_meta（dict 或 None）。
        dbc: DbcLoader 或 None。
        source_root: 源码根路径字符串或 None。

    任何入参为空/异常都安全降级（不 raise）——满足 US7。
    """
    has_bag = bool(bag_meta)
    has_source = bool(source_root)

    has_can = False
    has_dbc = bool(dbc)
    has_radar_objects = False

    if store is not None:
        try:
            can_ids = store.get_can_ids() if hasattr(store, "get_can_ids") else []
            has_can = bool(can_ids)
        except Exception:
            pass  # fail-soft
        try:
            n = store.conn.execute(
                "SELECT COUNT(*) FROM radar_objects"
            ).fetchone()
            has_radar_objects = bool(n and n[0] > 0)
        except Exception:
            pass

    return DataAvailability(
        has_bag=has_bag,
        has_can=has_can,
        has_dbc=has_dbc,
        has_radar_objects=has_radar_objects,
        has_source=has_source,
    )


def availability_from_case_load(result: Any) -> DataAvailability:
    """从 CaseLoadResult 对象便捷计算（兼容现有 load_case_data 返回）。"""
    store = getattr(result, "store", None)
    bag_meta = getattr(result, "bag_meta", None)
    dbc = getattr(result, "dbc", None)
    return classify_availability(store, bag_meta=bag_meta, dbc=dbc)


__all__ = [
    "DataAvailability",
    "classify_availability",
    "availability_from_case_load",
]