"""
HarnessRunner — 诊断质量评估统一入口

执行诊断 → 收集产物 → 运行各层级评估 → 输出汇总报告
"""

import json
import sys
from pathlib import Path
from typing import Optional
from datetime import datetime

from harness.structural_evaluator import StructuralEvaluator, StructuralEvaluationResult

HARNESS_DIR = Path(__file__).parent
BASE_DIR = HARNESS_DIR.parent
GOLDEN_TRUTHS_DIR = HARNESS_DIR / "golden_truths"


class HarnessResult:
    """完整的评估结果"""
    
    def __init__(self, case_id: str):
        self.case_id = case_id
        self.timestamp = datetime.now().isoformat()
        self.l0_result: Optional[StructuralEvaluationResult] = None
        self.overall_score: float = 0.0
        self.passed: bool = False
        self.errors: list[str] = []
    
    @property
    def passing_score(self) -> float:
        """及格线 —— L0 要求 ≥0.90"""
        return 0.90
    
    def compute_overall(self):
        """计算综合分数（当前只有 L0）"""
        if self.l0_result is None:
            self.overall_score = 0.0
            self.passed = False
            return
        
        # 当前只有 L0，直接取 L0 分数
        self.overall_score = self.l0_result.score
        self.passed = self.l0_result.score >= self.passing_score
    
    def to_dict(self) -> dict:
        from harness.structural_evaluator import StructuralEvaluator
        evaluator = StructuralEvaluator()
        
        result = {
            "case_id": self.case_id,
            "timestamp": self.timestamp,
            "overall_score": round(self.overall_score, 4),
            "passed": self.passed,
            "passing_threshold": self.passing_score,
            "l0_structural": None,
            "errors": self.errors,
        }
        
        if self.l0_result is not None:
            result["l0_structural"] = evaluator.to_json(self.l0_result)
        
        return result
    
    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)


class HarnessRunner:
    """
    评估运行器 —— 加载诊断报告，对照黄金答案运行评估。
    
    Usage:
        runner = HarnessRunner()
        result = runner.run_case("FCTA001", report_path="cases/FCTA001/report.md")
        print(result.to_json())
    """
    
    def __init__(self):
        self.structural_eval = StructuralEvaluator()
    
    def run_case(
        self,
        case_id: str,
        report_path: Optional[str | Path] = None,
        golden_truth_path: Optional[str | Path] = None,
    ) -> HarnessResult:
        """
        运行单个案例的评估。
        
        Args:
            case_id: 案例 ID（如 "FCTA001"）
            report_path: 诊断报告路径，默认 cases/{case_id}/report.md
            golden_truth_path: 黄金答案路径，默认 harness/golden_truths/{case_id}_ground_truth.json
            
        Returns:
            HarnessResult with scores and details
        """
        result = HarnessResult(case_id)
        
        # 解析路径
        if report_path is None:
            report_path = BASE_DIR / "cases" / case_id / "report.md"
        report_path = Path(report_path)
        
        if golden_truth_path is None:
            golden_truth_path = GOLDEN_TRUTHS_DIR / f"{case_id}_ground_truth.json"
        golden_truth_path = Path(golden_truth_path)
        
        # 1. 加载诊断报告
        if not report_path.exists():
            result.errors.append(f"诊断报告不存在: {report_path}")
            result.compute_overall()
            return result
        
        report_text = report_path.read_text(encoding="utf-8")
        
        # 2. 加载黄金答案
        if not golden_truth_path.exists():
            result.errors.append(f"黄金答案不存在: {golden_truth_path}")
            result.errors.append("（无黄金答案时仍可做 L0 结构评估）")
        
        # 3. 运行 L0 结构性评估
        try:
            l0 = self.structural_eval.evaluate(report_text)
            result.l0_result = l0
        except Exception as e:
            result.errors.append(f"L0 评估异常: {e!s}")
        
        # 4. 计算综合分数
        result.compute_overall()
        
        return result
    
    def run_all_cases(self, cases: Optional[list[str]] = None) -> list[HarnessResult]:
        """
        批量运行所有案例评估。
        
        Args:
            cases: 案例 ID 列表。None 表示扫描 harness/golden_truths/ 下所有黄金答案。
            
        Returns:
            每个案例的评估结果列表
        """
        if cases is None:
            # 自动发现：从黄金答案文件名推断
            cases = []
            for gt in GOLDEN_TRUTHS_DIR.glob("*_ground_truth.json"):
                case_id = gt.stem.replace("_ground_truth", "")
                cases.append(case_id)
        
        results = []
        for case_id in cases:
            print(f"[Harness] Running case: {case_id}")
            result = self.run_case(case_id)
            results.append(result)
            status = "PASS" if result.passed else "FAIL"
            print(f"  → {status} (score={result.overall_score:.2f})")
        
        return results


def main():
    """CLI 入口"""
    import argparse
    
    parser = argparse.ArgumentParser(description="radarAnalyze Harness Runner")
    parser.add_argument("case_id", nargs="?", default=None, help="Case ID to evaluate")
    parser.add_argument("--report", help="Path to report.md (optional)")
    parser.add_argument("--golden-truth", help="Path to ground_truth.json (optional)")
    parser.add_argument("--all", action="store_true", help="Run all available cases")
    parser.add_argument("--json", action="store_true", help="Output JSON format")
    
    args = parser.parse_args()
    runner = HarnessRunner()
    
    if args.all or args.case_id is None:
        results = runner.run_all_cases()
        
        # 汇总
        total = len(results)
        passed = sum(1 for r in results if r.passed)
        avg_score = sum(r.overall_score for r in results) / total if total else 0
        
        print(f"\n{'='*60}")
        print(f"Harness 汇总: {passed}/{total} 通过, 平均分 {avg_score:.2f}")
        
        if args.json:
            output = [r.to_dict() for r in results]
            output.append({
                "summary": {
                    "total": total,
                    "passed": passed,
                    "avg_score": round(avg_score, 4),
                }
            })
            print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        result = runner.run_case(
            args.case_id,
            report_path=args.report,
            golden_truth_path=args.golden_truth,
        )
        
        if args.json:
            print(result.to_json())
        else:
            print(result.to_json())
            
            # 退出码
            sys.exit(0 if result.passed else 1)


if __name__ == "__main__":
    main()
