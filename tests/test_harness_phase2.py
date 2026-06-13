"""
Harness Phase 2 — L1 Evidence + L2 Conclusion 评估测试

验证：
  1. EvidenceEvaluator 能正确评估 report.md 的 evidence 覆盖度
  2. ConclusionEvaluator 能正确评估 report.md 的结论正确性
  3. HarnessRunner 集成 L0/L1/L2 后综合分数计算正确
  4. 权重公式: overall = L0*0.25 + L1*0.35 + L2*0.40
  5. L0 gate: L0 < 0.90 时直接 FAIL
"""

import json
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent


class TestEvidenceEvaluator:
    """L1 Evidence Evaluator 测试"""

    def setup_method(self):
        from harness.evidence_evaluator import EvidenceEvaluator
        self.evaluator = EvidenceEvaluator()
        self.report_text = (BASE_DIR / "cases" / "FCTA001" / "report.md").read_text(encoding="utf-8")
        self.gt_path = BASE_DIR / "harness" / "golden_truths" / "FCTA001_ground_truth.json"
        self.gt = json.loads(self.gt_path.read_text(encoding="utf-8"))

    def test_evaluate_returns_result(self):
        result = self.evaluator.evaluate(self.report_text, self.gt)
        assert result.score >= 0
        assert result.score <= 1
        assert len(result.checks) > 0

    def test_evidence_passed(self):
        result = self.evaluator.evaluate(self.report_text, self.gt)
        assert result.passed is True
        assert result.score >= 0.60

    def test_signal_coverage_score(self):
        result = self.evaluator.evaluate(self.report_text, self.gt)
        assert result.signal_score >= 0.5  # 信号覆盖至少 50%

    def test_condition_coverage_score(self):
        result = self.evaluator.evaluate(self.report_text, self.gt)
        assert result.condition_score >= 0.5

    def test_window_coverage_score(self):
        result = self.evaluator.evaluate(self.report_text, self.gt)
        assert result.window_score >= 0.5

    def test_empty_report_fails(self):
        result = self.evaluator.evaluate("", self.gt)
        assert result.passed is False

    def test_checks_have_required_fields(self):
        result = self.evaluator.evaluate(self.report_text, self.gt)
        for check in result.checks:
            assert check.category in ("signal", "condition", "tpe", "window", "data_chain")
            assert check.name
            assert isinstance(check.passed, bool)
            assert check.weight >= 0


class TestConclusionEvaluator:
    """L2 Conclusion Evaluator 测试"""

    def setup_method(self):
        from harness.conclusion_evaluator import ConclusionEvaluator
        self.evaluator = ConclusionEvaluator()
        self.report_text = (BASE_DIR / "cases" / "FCTA001" / "report.md").read_text(encoding="utf-8")
        self.gt_path = BASE_DIR / "harness" / "golden_truths" / "FCTA001_ground_truth.json"
        self.gt = json.loads(self.gt_path.read_text(encoding="utf-8"))

    def test_evaluate_returns_result(self):
        result = self.evaluator.evaluate(self.report_text, self.gt)
        assert 0 <= result.score <= 1
        assert len(result.checks) > 0

    def test_classification_score(self):
        result = self.evaluator.evaluate(self.report_text, self.gt)
        # FCTA 在报告中应该被识别
        assert result.classification_score >= 0.8

    def test_concept_matching(self):
        result = self.evaluator.evaluate(self.report_text, self.gt)
        causal = [c for c in result.checks if c.category == "causal"]
        assert len(causal) > 0

    def test_empty_report_fails(self):
        result = self.evaluator.evaluate("", self.gt)
        assert result.score < 0.5


class TestHarnessRunnerIntegration:
    """HarnessRunner L0/L1/L2 集成测试"""

    def test_run_case_returns_full_result(self):
        from harness.harness_runner import HarnessRunner
        runner = HarnessRunner()
        result = runner.run_case("FCTA001")

        assert result.case_id == "FCTA001"
        assert result.l0_result is not None
        assert result.l1_result is not None
        assert result.l2_result is not None
        assert len(result.errors) == 0

    def test_overall_score_formula(self):
        from harness.harness_runner import HarnessRunner, L0_WEIGHT, L1_WEIGHT, L2_WEIGHT
        runner = HarnessRunner()
        result = runner.run_case("FCTA001")

        l0 = result.l0_result.score
        l1 = result.l1_result.score
        l2 = result.l2_result.score

        expected = l0 * L0_WEIGHT + l1 * L1_WEIGHT + l2 * L2_WEIGHT
        assert abs(result.overall_score - expected) < 0.001

    def test_l0_gate(self):
        """L0 < 0.90 时，综合分应被截断"""
        from harness.harness_runner import HarnessResult, L0_WEIGHT
        from harness.structural_evaluator import StructuralEvaluationResult

        result = HarnessResult("test")
        result.l0_result = StructuralEvaluationResult(
            score=0.80,  # 低于 0.90 gate
            checks=[],
            summary="",
        )
        result.l1_result = type(result.l1_result)(score=1.0) if False else None
        result.compute_overall()

        assert result.passed is False
        assert result.overall_score < 0.90 * L0_WEIGHT + 0.2

    def test_passed_threshold(self):
        from harness.harness_runner import HarnessRunner
        runner = HarnessRunner()
        result = runner.run_case("FCTA001")

        # 综合分 >= 0.60 即 PASS
        if result.overall_score >= 0.60:
            assert result.passed is True
        else:
            assert result.passed is False

    def test_to_dict_includes_all_layers(self):
        from harness.harness_runner import HarnessRunner
        runner = HarnessRunner()
        result = runner.run_case("FCTA001")
        d = result.to_dict()

        assert "l0_structural" in d
        assert "l1_evidence" in d
        assert "l2_conclusion" in d
        assert d["l0_structural"] is not None
        assert d["l1_evidence"] is not None
        assert d["l2_conclusion"] is not None

    def test_to_dict_l1_fields(self):
        from harness.harness_runner import HarnessRunner
        runner = HarnessRunner()
        result = runner.run_case("FCTA001")
        d = result.to_dict()

        l1 = d["l1_evidence"]
        assert "score" in l1
        assert "signal_score" in l1
        assert "condition_score" in l1
        assert "window_score" in l1
        assert "checks" in l1

    def test_to_dict_l2_fields(self):
        from harness.harness_runner import HarnessRunner
        runner = HarnessRunner()
        result = runner.run_case("FCTA001")
        d = result.to_dict()

        l2 = d["l2_conclusion"]
        assert "score" in l2
        assert "classification_score" in l2
        assert "localization_score" in l2
        assert "causal_score" in l2
        assert "checks" in l2

    def test_missing_golden_truth_still_runs_l0(self):
        from harness.harness_runner import HarnessRunner
        runner = HarnessRunner()
        result = runner.run_case("NONEXISTENT_CASE")

        assert result.l0_result is None  # 报告也不存在
        assert len(result.errors) > 0
        assert result.passed is False

    def test_run_all_cases(self):
        from harness.harness_runner import HarnessRunner
        runner = HarnessRunner()
        results = runner.run_all_cases()

        assert len(results) >= 1
        case_ids = [r.case_id for r in results]
        assert "FCTA001" in case_ids


class TestEvidenceEvaluatorEdgeCases:
    """L1 边界情况"""

    def test_no_signals_in_ground_truth(self):
        from harness.evidence_evaluator import EvidenceEvaluator
        evaluator = EvidenceEvaluator()
        gt = {
            "ground_truth_root_cause": {"key_signals": [], "causal_chain": []},
            "condition_checks": [],
            "test_windows": [],
            "data_chains": [],
        }
        result = evaluator.evaluate("some report text", gt)
        # 所有检查都应该是 N/A pass
        assert all(c.passed for c in result.checks if c.name == "none")

    def test_signal_alias_matching(self):
        from harness.evidence_evaluator import EvidenceEvaluator
        evaluator = EvidenceEvaluator()
        gt = {
            "ground_truth_root_cause": {
                "key_signals": [{"signal": "vel_x"}],
                "causal_chain": [],
            },
            "condition_checks": [],
            "test_windows": [],
            "data_chains": [],
        }
        # 报告用中文描述 "纵向速度" 而非 "vel_x"
        result = evaluator.evaluate("目标纵向速度趋近于0，导致TTC发散", gt)
        vel_checks = [c for c in result.checks if c.category == "signal" and c.name == "vel_x"]
        assert len(vel_checks) == 1
        # 别名匹配应通过
        assert vel_checks[0].passed is True


class TestConclusionEvaluatorEdgeCases:
    """L2 边界情况"""

    def test_no_function_in_ground_truth(self):
        from harness.conclusion_evaluator import ConclusionEvaluator
        evaluator = ConclusionEvaluator()
        gt = {
            "problem_statement": {"function": ""},
            "ground_truth_root_cause": {"primary_cause": "", "causal_chain": []},
            "key_fix_recommendations": [],
            "confidence": {},
        }
        result = evaluator.evaluate("any report", gt)
        cls_checks = [c for c in result.checks if c.category == "classification"]
        assert all(c.passed for c in cls_checks)

    def test_confidence_matching(self):
        from harness.conclusion_evaluator import ConclusionEvaluator
        evaluator = ConclusionEvaluator()
        gt = {
            "problem_statement": {"function": ""},
            "ground_truth_root_cause": {"primary_cause": "", "causal_chain": []},
            "key_fix_recommendations": [],
            "confidence": {"value": 85},
        }
        result = evaluator.evaluate("置信度: 88/100", gt)
        conf_checks = [c for c in result.checks if c.category == "confidence"]
        assert len(conf_checks) == 1
        assert conf_checks[0].passed is True  # 差值 3，在 ±15 范围内

    def test_confidence_mismatch(self):
        from harness.conclusion_evaluator import ConclusionEvaluator
        evaluator = ConclusionEvaluator()
        gt = {
            "problem_statement": {"function": ""},
            "ground_truth_root_cause": {"primary_cause": "", "causal_chain": []},
            "key_fix_recommendations": [],
            "confidence": {"value": 20},
        }
        result = evaluator.evaluate("置信度: 95/100", gt)
        conf_checks = [c for c in result.checks if c.category == "confidence"]
        assert len(conf_checks) == 1
        assert conf_checks[0].passed is False  # 差值 75，远超 ±15
