# -*- coding: utf-8 -*-
"""
数据模型 — ConditionDef / ConditionResult / ConditionReport。

所有类型均为无状态的纯数据容器，可安全地序列化为 JSON。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ── ConditionDef ──────────────────────────────────────────────────────────


@dataclass
class ConditionDef:
    """描述一个独立的条件检查点（如速度阈值、存在概率过滤等）。

    Attributes:
        step:             链路步骤编号，用于人类排序和分组。
        name:             人类可读的条件名称。
        category:         条件类别，例如 ``"fct_suppression"``。
        formula_str:      Python 表达式字符串，由 asteval 安全求值。
        signal_names:     本条件所需的 MF4 信号名列表。
        pad_params:       从代码中抽取的 PAD 参数字典。
        pad_sources:      定义这些 PAD 参数的头文件路径列表。
        code_files:       实现该检查的 .cpp/.hpp 文件列表。
        expected_outcome: 期望结果，``"pass"`` 或 ``"fail"``。
        description:      条件的自然语言说明。
    """

    step: int
    name: str
    category: str
    formula_str: str
    signal_names: list[str] = field(default_factory=list)
    pad_params: dict = field(default_factory=dict)
    pad_sources: list[str] = field(default_factory=list)
    code_files: list[str] = field(default_factory=list)
    expected_outcome: str = "pass"
    description: str = ""

    def to_dict(self) -> dict:
        """序列化为字典。"""
        return {
            "step": self.step,
            "name": self.name,
            "category": self.category,
            "formula_str": self.formula_str,
            "signal_names": self.signal_names,
            "pad_params": self.pad_params,
            "pad_sources": self.pad_sources,
            "code_files": self.code_files,
            "expected_outcome": self.expected_outcome,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ConditionDef:
        """从字典反序列化。"""
        return cls(
            step=data["step"],
            name=data["name"],
            category=data["category"],
            formula_str=data["formula_str"],
            signal_names=data.get("signal_names", []),
            pad_params=data.get("pad_params", {}),
            pad_sources=data.get("pad_sources", []),
            code_files=data.get("code_files", []),
            expected_outcome=data.get("expected_outcome", "pass"),
            description=data.get("description", ""),
        )


# ── ConditionResult ───────────────────────────────────────────────────────


@dataclass
class ConditionResult:
    """单次条件求值的结果。

    Attributes:
        condition_name:   条件名称。
        step:             所属步骤编号。
        hit:              条件是否满足（formula 求值为 True）。
        reason:           判定原因摘要。
        values:           求值时用到的信号值字典。
        missing_signals:  求值失败的信号名列表。
    """

    condition_name: str
    step: int
    hit: Optional[bool] = None
    reason: str = ""
    values: dict = field(default_factory=dict)
    missing_signals: list[str] = field(default_factory=list)


# ── ConditionReport ───────────────────────────────────────────────────────


@dataclass
class ConditionReport:
    """条件覆盖率汇总报告。

    Attributes:
        case_name:              测试用例名称。
        duration_sec:           记录时长。
        total_frames:           总帧数。
        total_conditions:       条件总数。
        signal_coverage:        信号覆盖率数据。
        condition_stats:        每个条件的统计数据。
        per_case:               多 case 时按用例聚合。
    """

    case_name: str = ""
    duration_sec: float = 0.0
    total_frames: int = 0
    total_conditions: int = 0
    signal_coverage: dict = field(default_factory=dict)
    condition_stats: list[dict] = field(default_factory=list)
    per_case: list["ConditionReport"] = field(default_factory=list)
