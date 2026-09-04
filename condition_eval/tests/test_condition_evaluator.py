# -*- coding: utf-8 -*-
"""
条件评估引擎单元测试。

测试覆盖：
1. 简单公式求值（条件命中 / 未命中）
2. 缺失信号处理（信号不在帧中时不崩溃，标记为 MISSING）
3. 覆盖率报告生成（命中统计、缺失信号列表）

运行方式::

    pytest condition_eval/tests/test_condition_evaluator.py -v
"""
from __future__ import annotations

import json
import sys
import os

# 确保项目根目录在 sys.path 中
_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import pytest

from condition_eval.evaluator import ConditionEvaluator, _extract_identifiers   # noqa: E402
from condition_eval.models import ConditionDef, ConditionResult                 # noqa: E402
from condition_eval.report import ConditionCoverageReport                      # noqa: E402


# ── 辅助函数 ───────────────────────────────────────────────────────────────


def _mock_condition(**kwargs) -> ConditionDef:
    """构建一个最小化测试用 ConditionDef。"""
    return ConditionDef(
        step=kwargs.get("step", 1),
        name=kwargs.get("name", "test_condition"),
        category=kwargs.get("category", "object_selector"),
        formula_str=kwargs.get("formula_str", "vx >= 0"),
        signal_names=kwargs.get("signal_names", ["vx"]),
        pad_params=kwargs.get("pad_params", {}),
        pad_sources=kwargs.get("pad_sources", []),
        code_files=kwargs.get("code_files", []),
        expected_outcome=kwargs.get("expected_outcome", "pass"),
        description=kwargs.get("description", ""),
    )


def _mock_frame(**kwargs) -> dict:
    """构建一个最小化测试用帧。"""
    return {
        "vx": kwargs.get("vx", 5.0),
        "vy": kwargs.get("vy", 0.0),
        "dist_x": kwargs.get("dist_x", 50.0),
        "dist_y": kwargs.get("dist_y", 1.0),
        "dy": kwargs.get("dy", 0.5),
        "dx": kwargs.get("dx", 30.0),
        "existProb": kwargs.get("existProb", 0.8),
        "obj_width": kwargs.get("obj_width", 2.0),
        "ttc": kwargs.get("ttc", 3.0),
        "ttc_valid": kwargs.get("ttc_valid", 1),
        "decel_req": kwargs.get("decel_req", 0.5),
        "vx_self": kwargs.get("vx_self", 15.0),
        "bsd_warning": kwargs.get("bsd_warning", 0),
        **kwargs.get("extra", {}),
    }


# ── 测试 1: 简单公式求值 ──────────────────────────────────────────────────


class TestSimpleFormulaEvaluation:
    """验证公式求值引擎能正确识别命中和未命中。"""

    def test_pass_when_condition_true(self):
        """条件满足时返回 hit=True。"""
        evaluator = ConditionEvaluator()
        cond = _mock_condition(
            name="vx_positive",
            formula_str="vx >= 0",
            signal_names=["vx"],
        )
        evaluator._conditions = [cond]

        result = evaluator.evaluate_frame({"vx": 5.0})

        assert "vx_positive" in result
        assert result["vx_positive"].hit is True
        assert result["vx_positive"].reason == "formula passed"

    def test_fail_when_condition_false(self):
        """条件不满足时返回 hit=False。"""
        evaluator = ConditionEvaluator()
        cond = _mock_condition(
            name="vx_positive",
            formula_str="vx >= 0",
            signal_names=["vx"],
        )
        evaluator._conditions = [cond]

        result = evaluator.evaluate_frame({"vx": -2.0})

        assert "vx_positive" in result
        assert result["vx_positive"].hit is False
        assert result["vx_positive"].reason == "formula failed"

    def test_complex_formula_with_abs(self):
        """包含 abs() 等函数的复杂公式。"""
        evaluator = ConditionEvaluator()
        cond = _mock_condition(
            name="lateral_check",
            formula_str="abs(dist_y) < 4.12 and existProb >= 0.6",
            signal_names=["dist_y", "existProb"],
        )
        evaluator._conditions = [cond]

        # 命中
        result = evaluator.evaluate_frame({"dist_y": 1.0, "existProb": 0.8})
        assert result["lateral_check"].hit is True

        # 未命中 - dist_y 太大
        result = evaluator.evaluate_frame({"dist_y": 5.0, "existProb": 0.8})
        assert result["lateral_check"].hit is False

        # 未命中 - existProb 太低
        result = evaluator.evaluate_frame({"dist_y": 1.0, "existProb": 0.3})
        assert result["lateral_check"].hit is False

    def test_and_operator(self):
        """and 连接多个条件。"""
        evaluator = ConditionEvaluator()
        cond = _mock_condition(
            name="multi_check",
            formula_str="vx >= -4.0 and dist_x > 0 and abs(dy) < 2.0",
            signal_names=["vx", "dist_x", "dy"],
        )
        evaluator._conditions = [cond]

        # 全部满足
        result = evaluator.evaluate_frame({"vx": 0.0, "dist_x": 50.0, "dy": 1.0})
        assert result["multi_check"].hit is True

        # vx 太低
        result = evaluator.evaluate_frame({"vx": -5.0, "dist_x": 50.0, "dy": 1.0})
        assert result["multi_check"].hit is False

    def test_or_operator(self):
        """or 连接多个条件。"""
        evaluator = ConditionEvaluator()
        cond = _mock_condition(
            name="ttc_check",
            formula_str="ttc < 0 or ttc > 6.0",
            signal_names=["ttc"],
        )
        evaluator._conditions = [cond]

        # ttc < 0
        result = evaluator.evaluate_frame({"ttc": -1.0})
        assert result["ttc_check"].hit is True

        # ttc > 6.0
        result = evaluator.evaluate_frame({"ttc": 8.0})
        assert result["ttc_check"].hit is True

        # 0 <= ttc <= 6.0
        result = evaluator.evaluate_frame({"ttc": 3.0})
        assert result["ttc_check"].hit is False

    def test_round_function(self):
        """round() 函数可用。"""
        evaluator = ConditionEvaluator()
        cond = _mock_condition(
            name="round_check",
            formula_str="round(vx, 1) == 5.0",
            signal_names=["vx"],
        )
        evaluator._conditions = [cond]

        result = evaluator.evaluate_frame({"vx": 5.04})
        assert result["round_check"].hit is True

    def test_load_from_json_string(self):
        """从 JSON 字符串加载条件。"""
        evaluator = ConditionEvaluator()
        json_str = json.dumps({
            "conditions": [
                {
                    "step": 1,
                    "name": "vx_check",
                    "category": "test",
                    "formula_str": "vx > 0",
                    "signal_names": ["vx"],
                }
            ]
        })

        evaluator.load_conditions(json_str)

        assert len(evaluator.conditions) == 1
        assert evaluator.conditions[0].name == "vx_check"

    def test_load_from_list(self):
        """从字典列表加载条件。"""
        evaluator = ConditionEvaluator()
        conditions = [
            {
                "step": 1,
                "name": "vx_check",
                "category": "test",
                "formula_str": "vx > 0",
                "signal_names": ["vx"],
            },
            {
                "step": 2,
                "name": "vy_check",
                "category": "test",
                "formula_str": "abs(vy) < 1.0",
                "signal_names": ["vy"],
            },
        ]
        evaluator.load_conditions_list(conditions)

        assert len(evaluator.conditions) == 2
        assert evaluator.conditions[0].expected_outcome == "pass"  # default


# ── 测试 2: 缺失信号处理 ──────────────────────────────────────────────────


class TestMissingSignalHandling:
    """验证缺失信号不会导致崩溃，并能正确标记。"""

    def test_missing_signal_no_crash(self):
        """信号缺失时不抛异常。"""
        evaluator = ConditionEvaluator()
        cond = _mock_condition(
            name="needs_missing",
            formula_str="vx > 0 and missing_sig > 10",
            signal_names=["vx", "missing_sig"],
        )
        evaluator._conditions = [cond]

        # 不传 missing_sig
        result = evaluator.evaluate_frame({"vx": 5.0})

        assert "needs_missing" in result
        assert result["needs_missing"].hit is None
        assert "missing_sig" in result["needs_missing"].missing_signals

    def test_partial_missing_signals(self):
        """部分信号缺失时，返回 partial_missing 状态。"""
        evaluator = ConditionEvaluator()
        cond = _mock_condition(
            name="partial_check",
            formula_str="vx > 0 and dist_x < 100",
            signal_names=["vx", "dist_x"],
        )
        evaluator._conditions = [cond]

        # 传 vx，但不传 dist_x
        result = evaluator.evaluate_frame({"vx": 5.0})

        assert result["partial_check"].hit is None
        assert "dist_x" in result["partial_check"].missing_signals
        assert "dist_x" in result["partial_check"].reason

    def test_all_signals_missing(self):
        """所有信号均缺失时的处理。"""
        evaluator = ConditionEvaluator()
        cond = _mock_condition(
            name="all_missing",
            formula_str="vx >= 0",
            signal_names=["vx", "vy"],
        )
        evaluator._conditions = [cond]

        # 一个信号都不传
        result = evaluator.evaluate_frame({})

        assert result["all_missing"].hit is None
        assert "vx" in result["all_missing"].missing_signals
        assert "vy" in result["all_missing"].missing_signals

    def test_none_json_format(self):
        """从 JSON 数组格式加载（非 {"conditions": ...} 对象格式）。"""
        evaluator = ConditionEvaluator()
        json_str = json.dumps([
            {
                "step": 1,
                "name": "vx_check",
                "category": "test",
                "formula_str": "vx > 0",
                "signal_names": ["vx"],
            }
        ])

        evaluator.load_conditions(json_str)

        assert len(evaluator.conditions) == 1

    def test_empty_frame(self):
        """空帧处理。"""
        evaluator = ConditionEvaluator()
        cond = _mock_condition(
            name="vx_check",
            formula_str="vx > 0",
            signal_names=["vx"],
        )
        evaluator._conditions = [cond]

        result = evaluator.evaluate_frame({})

        assert result["vx_check"].hit is None
        assert "vx" in result["vx_check"].missing_signals


# ── 测试 3: 覆盖率报告生成 ────────────────────────────────────────────────


class TestCoverageReportGeneration:
    """验证覆盖率报告正确生成。"""

    def test_basic_report_structure(self):
        """报告包含基本信息。"""
        evaluator = ConditionEvaluator()
        cond = _mock_condition(
            name="vx_positive",
            formula_str="vx >= 0",
            signal_names=["vx"],
        )
        evaluator._conditions = [cond]

        frames = [{"vx": 5.0} for _ in range(10)]
        evaluator.evaluate_all_frames(frames)

        report = evaluator.generate_coverage_report(case_name="test_case")

        assert report.case_name == "test_case"
        assert report.total_frames == 10
        assert report.total_conditions == 1
        assert len(report.condition_stats) == 1
        assert report.condition_stats[0]["hit"] == 10
        assert report.condition_stats[0]["hit_rate"] == 100.0

    def test_miss_reporting(self):
        """未命中统计正确。"""
        evaluator = ConditionEvaluator()
        cond = _mock_condition(
            name="vx_positive",
            formula_str="vx >= 0",
            signal_names=["vx"],
        )
        evaluator._conditions = [cond]

        frames = [
            {"vx": v} for v in [5.0, -1.0, 3.0, -2.0, 0.0, -0.5, 10.0, -5.0, 1.0, -3.0]
        ]
        evaluator.evaluate_all_frames(frames)

        report = evaluator.generate_coverage_report()

        stats = report.condition_stats[0]
        assert stats["hit"] == 5    # 5.0, 3.0, 0.0, 10.0, 1.0
        assert stats["miss"] == 5   # -1.0, -2.0, -0.5, -5.0, -3.0
        assert stats["hit_rate"] == 50.0  # 5 / (5+5) = 0.5 → 50%

    def test_hit_rate_calculation(self):
        """命中率计算精确。"""
        evaluator = ConditionEvaluator()
        cond = _mock_condition(
            name="test",
            formula_str="vx >= 0",
            signal_names=["vx"],
        )
        evaluator._conditions = [cond]

        half = [{"vx": 5.0} for _ in range(5)]
        half += [{"vx": -1.0} for _ in range(5)]
        evaluator.evaluate_all_frames(half)

        report = evaluator.generate_coverage_report()
        assert report.condition_stats[0]["hit_rate"] == 50.0

    def test_missing_signal_reporting(self):
        """缺失信号的统计正确。"""
        evaluator = ConditionEvaluator()
        cond = _mock_condition(
            name="needs_missing",
            formula_str="vx > 0 and missing_sig > 10",
            signal_names=["vx", "missing_sig"],
        )
        evaluator._conditions = [cond]

        all_frames = [{"vx": 5.0}]  # 永远不传 missing_sig
        evaluator.evaluate_all_frames(all_frames)

        report = evaluator.generate_coverage_report()

        stats = report.condition_stats[0]
        assert stats["hit"] == 0
        assert stats["missing_signal"] == 1
        # missing 信号应该在报告中列出
        assert "missing_sig" in report.signal_coverage["missing"]

    def test_report_empty_conditions(self):
        """无条件时报告正确。"""
        evaluator = ConditionEvaluator()
        evaluator.load_conditions_list([])
        report = evaluator.generate_coverage_report()

        assert report.total_conditions == 0
        assert len(report.condition_stats) == 0

    def test_report_with_multiple_conditions(self):
        """多条件混合场景。"""
        evaluator = ConditionEvaluator()
        conditions = [
            _mock_condition(
                step=1, name="vx_positive", formula_str="vx >= 0",
                signal_names=["vx"],
            ),
            _mock_condition(
                step=2, name="abs_check", formula_str="abs(dist_y) < 4.12",
                signal_names=["dist_y"],
            ),
            _mock_condition(
                step=3, name="missing_req", formula_str="vx > 0 and ghost > 0",
                signal_names=["vx", "ghost"],
            ),
        ]
        evaluator._conditions = conditions

        frames = [
            {"vx": 5.0, "dist_y": 1.0},
            {"vx": -1.0, "dist_y": 1.0},
            {"vx": 3.0, "dist_y": 5.0},
            {"vx": 0.0, "dist_y": 0.0},
            {"vx": 2.0, "dist_y": 2.0},
        ]
        evaluator.evaluate_all_frames(frames)

        report = evaluator.generate_coverage_report(case_name="multi_test", duration_sec=4.5)

        assert report.case_name == "multi_test"
        assert report.duration_sec == 4.5
        assert report.total_frames == 5
        assert report.total_conditions == 3

        # vx_positive: 5.0✓, -1.0✗, 3.0✓, 0.0✓, 2.0✓ = 4 HIT
        vx_stats = report.condition_stats[0]
        assert vx_stats["hit"] == 4

        # abs_check: 1.0✓, 1.0✓, 5.0✗, 0.0✓, 2.0✓ = 4 HIT
        abs_stats = report.condition_stats[1]
        assert abs_stats["hit"] == 4

        # missing_req: 所有帧都缺 ghost = 5 missing_signal
        miss_stats = report.condition_stats[2]
        assert miss_stats["missing_signal"] == 5

    def test_condition_evaluator_reset(self):
        """reset() 清空所有状态。"""
        evaluator = ConditionEvaluator()
        evaluator.load_conditions_list([{
            "step": 1, "name": "test", "category": "test",
            "formula_str": "vx > 0", "signal_names": ["vx"],
        }])
        evaluator.evaluate_all_frames([{"vx": 5.0}])

        evaluator.reset()

        assert len(evaluator.conditions) == 0
        assert len(evaluator._results) == 0

    def test_generate_coverage_report(self):
        """report.py 渲染器基本可用。"""
        evaluator = ConditionEvaluator()
        cond = _mock_condition(
            name="vx_positive",
            formula_str="vx >= 0",
            signal_names=["vx"],
        )
        evaluator._conditions = [cond]
        frames = [{"vx": v} for v in [5.0, -1.0, 3.0]]
        evaluator.evaluate_all_frames(frames)

        report = evaluator.generate_coverage_report(case_name="renderer_test")
        renderer = ConditionCoverageReport(report)

        txt = renderer.render_txt()
        md = renderer.render_md()

        assert "Condition Hits" in txt
        assert "vx_positive" in txt
        assert "## Condition Hits" in md
        assert "vx_positive" in md

        # 确保有文本内容
        assert len(txt) > 50
        assert len(md) > 50

    def test_signal_identifier_extraction(self):
        """标识符提取函数正确识别变量名。"""
        # 基本标识符
        assert _extract_identifiers("vx >= 0") == {"vx"}

        # 多个标识符
        result = _extract_identifiers("abs(dy) < 4.12 and existProb >= 0.6")
        assert "dy" in result
        assert "existProb" in result

        # 关键字应该被排除
        result = _extract_identifiers("vx and abs(dy) >= 0.0")
        assert "and" not in result
        assert "abs" not in result
        assert "vx" in result
        assert "dy" in result
        assert "0" not in result  # 数字被排除


# ── 集成测试 ──────────────────────────────────────────────────────────────


class TestIntegration:
    """端到端集成测试。"""

    def test_full_bsd_workflow(self):
        """完整 BSD 条件链工作流。"""
        from condition_eval.default_conditions import get_bsd_condition_json  # noqa: E402

        evaluator = ConditionEvaluator()

        # 1. 加载条件
        evaluator.load_conditions(get_bsd_condition_json())
        assert len(evaluator.conditions) > 0

        # 2. 构造一帧合理的 BSD 目标
        frame = {
            "vx_self": 20.0,         # 本车速度 20 m/s
            "bsd_warning": 0,         # 无警告
            "dist_y": 2.0,           # 横向距离 2 米
            "dy": 0.5,               # 横向偏移
            "dx": 30.0,              # 纵向偏移
            "dist_x": 50.0,          # 纵向距离 50 米
            "vx": -5.0,              # 目标相对本车慢 5 m/s
            "existProb": 0.9,        # 存在概率
            "obj_width": 2.0,        # 宽度
            "ttc": 10.0,             # TTC
            "ttc_valid": 1,          # 有效
            "decel_req": 0.5,        # 需要减速
        }

        result = evaluator.evaluate_frame(frame)

        # 3. 检查关键条件
        vx_check = [
            r for r in result.values()
            if "Speed Check" in r.condition_name
        ]
        if vx_check:
            assert vx_check[0].hit is True

        ldist_check = [
            r for r in result.values()
            if "Lateral" in r.condition_name
        ]
        if ldist_check:
            assert ldist_check[0].hit is True

    def test_end_to_end_with_report_files(self, tmp_path):
        """端到端测试：生成条件、评估帧、输出报告文件。"""
        evaluator = ConditionEvaluator()
        evaluator.load_conditions_list([
            {
                "step": 1,
                "name": "simple_test",
                "category": "test",
                "formula_str": "vx >= 0",
                "signal_names": ["vx"],
            },
        ])

        frames = [{"vx": v} for v in [1.0, 2.0, -1.0]]
        evaluator.evaluate_all_frames(frames)

        report = evaluator.generate_coverage_report(case_name="e2e")
        renderer = ConditionCoverageReport(report)

        txt_path, md_path = renderer.write_reports(str(tmp_path), "e2e")

        import os
        assert os.path.exists(txt_path)
        assert os.path.exists(md_path)

        txt_content = open(txt_path, encoding="utf-8").read()
        assert "simple_test" in txt_content

        md_content = open(md_path, encoding="utf-8").read()
        assert "simple_test" in md_content
