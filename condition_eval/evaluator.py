# -*- coding: utf-8 -*-
"""
ConditionEvaluator — 条件评估主引擎。

职责
────
1. 从 JSON 加载 ConditionDef 列表
2. 对每一帧 MF4 数据求值所有条件
3. 汇总覆盖率报告

安全求值
────────
使用 ``asteval`` 库（minimal + use_numpy 模式），禁止 import 和文件操作。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from asteval import Interpreter

from .models import ConditionDef, ConditionReport, ConditionResult


@dataclass
class _EvalStats:
    """单条件跨帧的统计数据。"""
    name: str
    step: int
    category: str
    formula_str: str
    total: int = 0
    hit: int = 0
    miss: int = 0
    missing_signal: int = 0
    missing_signals_set: set = field(default_factory=set)
    reason_samples: dict = field(default_factory=dict)  # reason -> count

    @property
    def hit_rate(self) -> float:
        """已求值帧中的命中比例（不含 MISSING SIGNAL）。"""
        evaluated = self.hit + self.miss
        if evaluated == 0:
            return 0.0
        return self.hit / evaluated


class _SafeEvaluator:
    """asteval 薄封装，用于单点标量求值。"""

    def __init__(self) -> None:
        self.aeval = Interpreter(
            minimal=True,
            use_numpy=False,
            max_statement_length=500,
        )
        # 允许的安全内置函数
        for _fn in ("abs", "max", "min", "round", "int", "float"):
            if hasattr(__builtins__, _fn):
                self.aeval.symtable[_fn] = getattr(__builtins__, _fn)
        # True/False 在 asteval minimal 模式中默认已内置，但显式声明更稳妥
        self.aeval.symtable["True"] = True
        self.aeval.symtable["False"] = False

    def eval_formula(self, formula: str, symbols: dict) -> tuple[bool | None, str, dict]:
        """安全求值公式。

        Returns:
            (result, reason, used_values)
            result 为 None 表示因信号缺失无法求值。
        """
        # 清理符号表：先清除旧数据只保留白名单
        known = {"True", "False"}
        for _fn in ("abs", "max", "min", "round", "int", "float"):
            known.add(_fn)
        for k in list(self.aeval.symtable.keys()):
            if k not in known:
                del self.aeval.symtable[k]

        missing: list[str] = []
        used_values: dict = {}

        for sym_name, sym_val in symbols.items():
            self.aeval.symtable[sym_name] = sym_val
            used_values[sym_name] = sym_val

        # 收集公式中引用但符号表中不存在的变量名
        refs = _extract_identifiers(formula)
        for ref in refs:
            if ref not in self.aeval.symtable and ref not in known:
                missing.append(ref)

        if missing:
            self.aeval.error = []

        reason = ""
        if missing:
            reason = f"missing signals: {', '.join(sorted(missing))}"
            result = None
        else:
            try:
                self.aeval.error = []
                raw = self.aeval.eval(formula, show_errors=False)
                # 清空错误列表供下次调用
                self.aeval.error = []
                if self.aeval.error:
                    msgs = "; ".join(
                        str(getattr(e, "msg", "?")) for e in self.aeval.error
                    )
                    reason = f"eval error: {msgs}"
                    result = None
                else:
                    result = bool(raw)
                    reason = (
                        "formula passed" if result
                        else "formula failed"
                    )
                    # 补充未参与求值的信号值
                    for sig in symbols:
                        if sig not in used_values:
                            needed = _find_in_formula(formula, sig)
                            if needed:
                                used_values[sig] = symbols[sig]
            except Exception as exc:
                reason = f"eval error: {exc}"
                result = None

        return result, reason, used_values


# ── Token helpers ─────────────────────────────────────────────────────────


def _extract_identifiers(expr: str) -> set[str]:
    """提取表达式中的 Python 标识符。"""
    tokens = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", expr))
    _SKIP = {
        "and", "or", "not", "True", "False", "None",
        "if", "else", "in", "is",
        "abs", "max", "min", "round", "int", "float", "sqrt",
        "where", "clip", "minimum", "maximum", "isfinite",
    }
    return tokens - _SKIP


def _find_in_formula(formula: str, name: str) -> bool:
    """检查标识符名是否在公式中使用（精确匹配）。"""
    tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", formula)
    return name in tokens


# ── Public API ────────────────────────────────────────────────────────────


class ConditionEvaluator:
    """条件评估引擎。

    用法示例::

        evaluator = ConditionEvaluator()
        evaluator.load_conditions(json_string)
        result = evaluator.evaluate_frame({"vx": 5.0, "dy": -1.2})
        all_results = evaluator.evaluate_all_frames(frames)
        report = evaluator.generate_coverage_report()
    """

    def __init__(self) -> None:
        self._conditions: list[ConditionDef] = []
        self._results: list[dict[str, ConditionResult]] = []  # per-frame results
        self._evaluator = _SafeEvaluator()

    @property
    def conditions(self) -> list[ConditionDef]:
        """当前加载的条件列表。"""
        return self._conditions

    # ── 加载 ────────────────────────────────────────────────────────────

    def load_conditions(self, condition_json: str) -> None:
        """从 JSON 字符串加载条件定义。

        Args:
            condition_json: JSON 字符串，格式为 { "conditions": [...] }
                或纯数组 [...，每个元素为 ConditionDef 字典。
        """
        data = json.loads(condition_json)
        items: list[dict] = []
        if isinstance(data, dict):
            items = data.get("conditions", [])
        elif isinstance(data, list):
            items = data
        self._conditions = [ConditionDef.from_dict(d) for d in items]

    def load_conditions_list(self, conditions: list[dict]) -> None:
        """从字典列表加载。"""
        self._conditions = [ConditionDef.from_dict(d) for d in conditions]

    # ── 单帧评估 ────────────────────────────────────────────────────────

    def evaluate_frame(self, frame: dict[str, Any]) -> dict[str, ConditionResult]:
        """对一帧数据评估所有条件。

        Args:
            frame: 信号名 → 信号值的字典。

        Returns:
            {condition_name: ConditionResult}
        """
        results: dict[str, ConditionResult] = {}
        for cond in self._conditions:
            result = self._eval_one_condition(cond, frame)
            results[cond.name] = result
        return results

    def _eval_one_condition(
        self, cond: ConditionDef, frame: dict[str, Any]
    ) -> ConditionResult:
        """评估单个条件对一帧的匹配结果。"""
        # 构建符号表
        symbols = {}
        missing: list[str] = []
        for sig in cond.signal_names:
            if sig in frame:
                val = frame[sig]
                # 兼容 numpy 标量
                if hasattr(val, "item"):
                    val = val.item()
                symbols[sig] = val
            else:
                missing.append(sig)

        if missing and len(missing) == len(cond.signal_names):
            # 所有信号都缺失
            return ConditionResult(
                condition_name=cond.name,
                step=cond.step,
                reason=f"all signals missing: {', '.join(missing)}",
                missing_signals=missing,
            )

        # 部分缺失：只传入已有的信号
        if missing:
            return ConditionResult(
                condition_name=cond.name,
                step=cond.step,
                hit=None,
                reason=f"partial signals missing: {', '.join(missing)}",
                values=symbols,
                missing_signals=missing,
            )

        # 全部信号存在，进行公式求值
        result, reason, values = self._evaluator.eval_formula(cond.formula_str, symbols)
        hit = result if result is not None else None
        return ConditionResult(
            condition_name=cond.name,
            step=cond.step,
            hit=hit,
            reason=reason,
            values=values,
            missing_signals=[],
        )

    # ── 全量评估 ────────────────────────────────────────────────────────

    def evaluate_all_frames(
        self, frames: list[dict[str, Any]]
    ) -> list[dict[str, ConditionResult]]:
        """对所有帧评估所有条件。

        Args:
            frames: 帧列表，每个帧为信号名→信号值字典。

        Returns:
            按帧排列的结果列表。
        """
        self._results = []
        for frame in frames:
            self._results.append(self.evaluate_frame(frame))
        return self._results

    # ── 覆盖率报告 ──────────────────────────────────────────────────────

    def generate_coverage_report(
        self,
        case_name: str = "",
        duration_sec: float = 0.0,
    ) -> ConditionReport:
        """生成覆盖率报告。

        必须先调用 evaluate_all_frames。

        Args:
            case_name:    用例名称。
            duration_sec: 用例记录时长（秒）。

        Returns:
            ConditionReport 实例。
        """
        if not self._results:
            return ConditionReport(
                case_name=case_name,
                total_conditions=0,
            )

        total_frames = len(self._results)
        stats: list[_EvalStats] = []

        all_referenced_signals: set[str] = set()
        for cond in self._conditions:
            all_referenced_signals.update(cond.signal_names)

        # 收集所有帧中出现过的信号名
        all_found_signals: set[str] = set()
        for frame_result in self._results:
            for cr in frame_result.values():
                all_found_signals.update(cr.values.keys())

        for cond in self._conditions:
            es = _EvalStats(
                name=cond.name,
                step=cond.step,
                category=cond.category,
                formula_str=cond.formula_str,
            )

            for frame_result in self._results:
                res = frame_result.get(cond.name)
                if res is None:
                    continue
                es.total += 1
                if res.hit is True:
                    es.hit += 1
                elif res.hit is False:
                    es.miss += 1
                else:
                    es.missing_signal += 1
                    es.missing_signals_set.update(res.missing_signals)
                    # 记录原因样本
                    if res.reason and res.reason not in es.reason_samples:
                        # 只缓存前几个样本
                        if len(es.reason_samples) < 3:
                            es.reason_samples[res.reason] = 0
                        es.reason_samples[res.reason] = es.reason_samples.get(res.reason, 0) + 1
            stats.append(es)

        # 缺失信号：被条件引用但从未在任何帧的 values 中出现
        signal_missing = []
        for sig in sorted(all_referenced_signals):
            if sig not in all_found_signals:
                signal_missing.append(sig)

        # 条件统计
        condition_stats = []
        for es in stats:
            per_case_info = {
                "name": es.name,
                "step": es.step,
                "category": es.category,
                "hit_rate": round(es.hit_rate * 100, 1),
                "total": es.total,
                "hit": es.hit,
                "miss": es.miss,
                "missing_signal": es.missing_signal,
                "expected_outcome": next(
                    (c.expected_outcome for c in self._conditions
                     if c.name == es.name),
                    "pass",
                ),
                "failure_reasons": dict(es.reason_samples),
            }
            condition_stats.append(per_case_info)

        # 条件覆盖率分类
        fully_covered = sum(
            1 for s in stats if len(s.missing_signals_set) == 0 and s.total > 0
        )
        partially_covered = sum(
            1 for s in stats if 0 < len(s.missing_signals_set) <= 2 and s.total > 0
        )
        fully_missing = sum(
            1 for s in stats if len(s.missing_signals_set) >= 3 and s.total > 0
        )

        all_hits_zero = [
            s.name for s in stats if s.hit == 0 and s.total > 0
        ]
        all_hits_total = [
            s.name for s in stats if s.hit == s.total and s.total > 0
        ]

        # 所有在 values 中出现的信号
        signals_found_anywhere: set[str] = set()
        for frame_result in self._results:
            for cr in frame_result.values():
                signals_found_anywhere.update(cr.values.keys())

        report = ConditionReport(
            case_name=case_name,
            duration_sec=duration_sec,
            total_frames=total_frames,
            total_conditions=len(self._conditions),
            signal_coverage={
                "referenced": sorted(all_referenced_signals),
                "found": sorted(signals_found_anywhere),
                "missing": signal_missing,
                "referenced_count": len(all_referenced_signals),
                "found_count": len(signals_found_anywhere),
                "missing_count": len(signal_missing),
            },
            condition_stats=condition_stats,
        )

        # 扩展报告元信息
        report._missing_signals_detail = [
            {"signal": sig, "referenced_by": [
                c.name for c in self._conditions if sig in c.signal_names
            ]}
            for sig in signal_missing
        ]
        report._always_zero = all_hits_zero
        report._always_100 = all_hits_total
        report._fully_covered = fully_covered
        report._partially_covered = partially_covered
        report._fully_missing_count = fully_missing

        return report

    def reset(self) -> None:
        """清空所有状态，重新开始。"""
        self._conditions.clear()
        self._results.clear()
