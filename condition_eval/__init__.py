# -*- coding: utf-8 -*-
"""
condition_eval — 条件评估引擎，用于将代码提取的条件与 MF4 实测帧对齐。

模块结构
────────
models.py        — 数据模型 (ConditionDef / ConditionResult / ConditionReport)
evaluator.py     — ConditionEvaluator 主引擎
report.py        — ConditionCoverageReport 输出渲染
default_conditions.py  — 预置 BSD 条件集（用于测试）
"""
from __future__ import annotations

from .evaluator import ConditionEvaluator
from .models import ConditionDef, ConditionReport, ConditionResult
from .report import ConditionCoverageReport

__all__ = [
    "ConditionDef",
    "ConditionResult",
    "ConditionReport",
    "ConditionEvaluator",
    "ConditionCoverageReport",
]
