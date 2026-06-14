"""
HarnessRunner — 诊断质量评估统一入口

执行诊断 → 收集产物 → 运行各层级评估 → 输出汇总报告

评估层级：
  L0: StructuralEvaluator  — 结构完整性（MVP, V1, V2 检查项）
  L1: EvidenceEvaluator    — 证据链覆盖度（确定性规则）
  L2: ConclusionEvaluator  — 结论正确性（分类/定位/因果匹配）
"""

import json
import re
import sys
from pathlib import Path
from typing import Optional
from datetime import datetime

from harness.structural_evaluator import StructuralEvaluator, StructuralEvaluationResult
from harness.evidence_evaluator import EvidenceEvaluator, EvidenceEvaluationResult
from harness.conclusion_evaluator import ConclusionEvaluator, ConclusionEvaluationResult
from harness.llm_judge import LLMJudge

HARNESS_DIR = Path(__file__).parent
BASE_DIR = HARNESS_DIR.parent
GOLDEN_TRUTHS_DIR = HARNESS_DIR / "golden_truths"


# 层级权重 — 用于计算综合分数
L0_WEIGHT = 0.25    # 结构完整性
L1_WEIGHT = 0.35    # 证据覆盖度（最重要）
L2_WEIGHT = 0.40    # 结论正确性


class HarnessResult:
    """完整的评估结果（L0 + L1 + L2）"""

    def __init__(self, case_id: str):
        self.case_id = case_id
        self.timestamp = datetime.now().isoformat()
        self.l0_result: Optional[StructuralEvaluationResult] = None
        self.l1_result: Optional[EvidenceEvaluationResult] = None
        self.l2_result: Optional[ConclusionEvaluationResult] = None
        self.overall_score: float = 0.0
        self.passed: bool = False
        self.errors: list[str] = []
        # ── Bundle/Snapshot metadata (audit linkage) ────────────────
        self.bundle_id: str = ""
        self.snapshot_id: str = ""
        self.variant_id: str = ""
        self.bundle_path: str = ""

    @property
    def passing_score(self) -> float:
        """及格线 —— 综合 ≥0.60，L0 ≥0.90"""
        return 0.60

    def compute_overall(self):
        """
        计算综合分数（L0 + L1 + L2 加权平均）。

        加权公式：
          overall = L0 * 0.25 + L1 * 0.35 + L2 * 0.40

        约束：L0 必须 ≥0.90，否则直接 FAIL（结构不合格，不配评分）。
        """
        if self.l0_result is None:
            self.overall_score = 0.0
            self.passed = False
            return

        # L0 gate: 结构不合格直接 FAIL
        if self.l0_result.score < 0.90:
            self.overall_score = self.l0_result.score * L0_WEIGHT
            self.passed = False
            self.errors.append(f"L0 结构分 {self.l0_result.score:.2f} < 0.90，不满足评估前提")
            return

        # 收集各层分数（缺失层按 0 处理，但不一定 FAIL）
        l0 = self.l0_result.score
        l1 = self.l1_result.score if self.l1_result else 0.0
        l2 = self.l2_result.score if self.l2_result else 0.0

        # 加权平均
        self.overall_score = l0 * L0_WEIGHT + l1 * L1_WEIGHT + l2 * L2_WEIGHT
        self.passed = self.overall_score >= self.passing_score

    def to_dict(self) -> dict:
        from harness.structural_evaluator import StructuralEvaluator
        evaluator = StructuralEvaluator()

        result = {
            "case_id": self.case_id,
            "timestamp": self.timestamp,
            "overall_score": round(self.overall_score, 4),
            "passed": self.passed,
            "passing_threshold": self.passing_score,
            # ── Audit metadata ────────────────────────────────────
            "bundle_id": self.bundle_id,
            "snapshot_id": self.snapshot_id,
            "variant_id": self.variant_id,
            **({"bundle_path": self.bundle_path} if self.bundle_path else {}),
            "l0_structural": None,
            "l1_evidence": None,
            "l2_conclusion": None,
            "errors": self.errors,
        }

        if self.l0_result is not None:
            result["l0_structural"] = evaluator.to_json(self.l0_result)
        if self.l1_result is not None:
            result["l1_evidence"] = {
                "score": round(self.l1_result.score, 4),
                "passed": self.l1_result.passed,
                "signal_score": round(self.l1_result.signal_score, 4),
                "condition_score": round(self.l1_result.condition_score, 4),
                "window_score": round(self.l1_result.window_score, 4),
                "checks": [
                    {
                        "category": c.category,
                        "name": c.name,
                        "passed": c.passed,
                        "description": c.description,
                        "detail": c.detail,
                        "weight": c.weight,
                    }
                    for c in self.l1_result.checks
                ],
            }
        if self.l2_result is not None:
            result["l2_conclusion"] = {
                "score": round(self.l2_result.score, 4),
                "passed": self.l2_result.passed,
                "classification_score": round(self.l2_result.classification_score, 4),
                "localization_score": round(self.l2_result.localization_score, 4),
                "causal_score": round(self.l2_result.causal_score, 4),
                "checks": [
                    {
                        "category": c.category,
                        "name": c.name,
                        "passed": c.passed,
                        "score": round(c.score, 4),
                        "description": c.description,
                        "detail": c.detail,
                        "weight": c.weight,
                    }
                    for c in self.l2_result.checks
                ],
            }

        return result

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)


class HarnessRunner:
    """
    评估运行器 —— 加载诊断报告，对照黄金答案运行 L0/L1/L2 评估。

    Usage:
        runner = HarnessRunner()
        result = runner.run_case("FCTA001")
        print(result.to_json())
    """

    def __init__(self, config: Optional[dict] = None, router=None):
        self.config = config or {}
        self.router = router
        self.structural_eval = StructuralEvaluator()
        self.evidence_eval = EvidenceEvaluator()

        # 初始化 LLM judge（可选）
        llm_judge = None
        if router is not None:
            harness_cfg = self.config.get("harness", {})
            llm_judge_cfg = harness_cfg.get("llm_judge", {})
            if llm_judge_cfg.get("enabled", False):
                llm_judge = LLMJudge(router, llm_judge_cfg)

        self.conclusion_eval = ConclusionEvaluator(llm_judge=llm_judge)

    def run_case(
        self,
        case_id: str,
        report_path: Optional[str | Path] = None,
        golden_truth_path: Optional[str | Path] = None,
    ) -> HarnessResult:
        """
        运行单个案例的 L0/L1/L2 评估。

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

        # ── Auto-load DiagnosisBundle for audit linkage ────────────
        case_dir = report_path.parent
        bundle_path = case_dir / "diagnosis_bundle.json"
        if bundle_path.exists():
            try:
                bundle_data = json.loads(bundle_path.read_text(encoding="utf-8"))
                result.bundle_id = bundle_data.get("bundle_id", "")
                result.snapshot_id = bundle_data.get("snapshot_id", "")
                result.variant_id = bundle_data.get("variant_id", "")
                result.bundle_path = str(bundle_path)
            except Exception:
                pass  # Bundle is optional; harness still works without it

        # 2. 加载黄金答案
        golden_truth = None
        if not golden_truth_path.exists():
            result.errors.append(f"黄金答案不存在: {golden_truth_path}")
            result.errors.append("（无黄金答案时仍可做 L0 结构评估）")
        else:
            golden_truth = json.loads(golden_truth_path.read_text(encoding="utf-8"))

        # 3. 运行 L0 结构性评估（不依赖黄金答案）
        try:
            l0 = self.structural_eval.evaluate(report_text)
            result.l0_result = l0
        except Exception as e:
            result.errors.append(f"L0 评估异常: {e!s}")

        # 4. 运行 L1 证据评估（需要黄金答案）
        if golden_truth is not None:
            try:
                l1 = self.evidence_eval.evaluate(report_text, golden_truth)
                result.l1_result = l1
            except Exception as e:
                result.errors.append(f"L1 评估异常: {e!s}")

        # 5. 运行 L2 结论评估（需要黄金答案）
        if golden_truth is not None:
            try:
                l2 = self.conclusion_eval.evaluate(report_text, golden_truth)
                result.l2_result = l2
            except Exception as e:
                result.errors.append(f"L2 评估异常: {e!s}")

        # 6. 计算综合分数
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

    def generate_aggregate_report(self, results: list[HarnessResult]) -> dict:
        """
        生成多案例聚合统计报告。

        包含:
        - 总体统计: 总案例数、通过率、平均分
        - 分层统计: L0/L1/L2 各层平均分、最差案例
        - 维度分析: L2 下 classification/localization/causal 维度分析
        - 差距项排行: 得分最低的检查项 TOP 5
        - 回归对比: 与基准线对比（如果提供了 baseline 路径）

        Returns:
            聚合报告 dict
        """
        if not results:
            return {"error": "No results to aggregate"}

        total = len(results)
        passed = sum(1 for r in results if r.passed)
        failed = total - passed
        scores = [r.overall_score for r in results]
        avg_score = sum(scores) / total
        min_score = min(scores)
        max_score = max(scores)
        min_case = results[scores.index(min_score)].case_id
        max_case = results[scores.index(max_score)].case_id

        # ── 分层统计 ─────────────────────────────────────
        l0_scores = [r.l0_result.score for r in results if r.l0_result]
        l1_scores = [r.l1_result.score for r in results if r.l1_result]
        l2_scores = [r.l2_result.score for r in results if r.l2_result]

        layer_stats = {
            "l0_structural": {
                "count": len(l0_scores),
                "avg": round(sum(l0_scores) / len(l0_scores), 4) if l0_scores else 0,
                "min": round(min(l0_scores), 4) if l0_scores else 0,
                "max": round(max(l0_scores), 4) if l0_scores else 0,
            },
            "l1_evidence": {
                "count": len(l1_scores),
                "avg": round(sum(l1_scores) / len(l1_scores), 4) if l1_scores else 0,
                "min": round(min(l1_scores), 4) if l1_scores else 0,
                "max": round(max(l1_scores), 4) if l1_scores else 0,
            },
            "l2_conclusion": {
                "count": len(l2_scores),
                "avg": round(sum(l2_scores) / len(l2_scores), 4) if l2_scores else 0,
                "min": round(min(l2_scores), 4) if l2_scores else 0,
                "max": round(max(l2_scores), 4) if l2_scores else 0,
            },
        }

        # ── 最差案例 ─────────────────────────────────────
        worst_cases = sorted(results, key=lambda r: r.overall_score)[:3]
        worst_by_case = []
        for wc in worst_cases:
            reasons = []
            if wc.l0_result and wc.l0_result.score < 0.90:
                reasons.append(f"L0={wc.l0_result.score:.2f} (结构不合格)")
            if wc.l1_result and wc.l1_result.score < 0.60:
                reasons.append(f"L1={wc.l1_result.score:.2f} (证据不足)")
            if wc.l2_result and wc.l2_result.score < 0.60:
                reasons.append(f"L2={wc.l2_result.score:.2f} (结论偏差)")
            if wc.errors:
                reasons.append(f"Errors: {', '.join(wc.errors[:2])}")
            worst_by_case.append({
                "case_id": wc.case_id,
                "score": round(wc.overall_score, 4),
                "passed": wc.passed,
                "reasons": reasons if reasons else ["综合分数偏低"],
            })

        # ── L2 维度分析 ─────────────────────────────────
        dim_stats = {
            "classification": {"scores": [], "cases": []},
            "localization": {"scores": [], "cases": []},
            "causal": {"scores": [], "cases": []},
        }
        for r in results:
            if r.l2_result:
                dim_stats["classification"]["scores"].append(r.l2_result.classification_score)
                dim_stats["classification"]["cases"].append(r.case_id)
                dim_stats["localization"]["scores"].append(r.l2_result.localization_score)
                dim_stats["localization"]["cases"].append(r.case_id)
                dim_stats["causal"]["scores"].append(r.l2_result.causal_score)
                dim_stats["causal"]["cases"].append(r.case_id)

        dimension_analysis = {}
        for dim, data in dim_stats.items():
            if data["scores"]:
                avg = sum(data["scores"]) / len(data["scores"])
                worst = min(data["scores"])
                worst_idx = data["scores"].index(worst)
                dimension_analysis[dim] = {
                    "avg": round(avg, 4),
                    "min": round(worst, 4),
                    "worst_case": data["cases"][worst_idx] if worst_idx < len(data["cases"]) else "",
                    "count": len(data["scores"]),
                }

        # ── 差距项 TOP 5 (所有 FAIL 检查项中平均得分最低的) ──
        check_scores: dict[str, list[float]] = {}
        for r in results:
            all_checks = []
            if r.l1_result:
                for c in r.l1_result.checks:
                    all_checks.append((f"L1/{c.category}/{c.name}", float(c.passed), c.weight))
            if r.l2_result:
                for c in r.l2_result.checks:
                    all_checks.append((f"L2/{c.category}/{c.name}", c.score, c.weight))
            for name, score, weight in all_checks:
                check_scores.setdefault(name, []).append(score)

        gap_items = []
        for name, scores_list in check_scores.items():
            avg = sum(scores_list) / len(scores_list)
            gap_items.append({
                "check": name,
                "avg_score": round(avg, 4),
                "cases_evaluated": len(scores_list),
            })
        gap_items.sort(key=lambda x: x["avg_score"])
        top_gaps = gap_items[:5]

        # ── 每案例明细 ──────────────────────────────────
        case_details = []
        for r in results:
            detail = {
                "case_id": r.case_id,
                "overall": round(r.overall_score, 4),
                "passed": r.passed,
                "l0": round(r.l0_result.score, 4) if r.l0_result else None,
                "l1": round(r.l1_result.score, 4) if r.l1_result else None,
                "l2": round(r.l2_result.score, 4) if r.l2_result else None,
                "errors": r.errors,
            }
            # 审计元数据
            if r.bundle_id:
                detail["bundle_id"] = r.bundle_id
            if r.snapshot_id:
                detail["snapshot_id"] = r.snapshot_id
            if r.variant_id:
                detail["variant_id"] = r.variant_id
            case_details.append(detail)

        report = {
            "report_type": "harness_aggregate",
            "generated_at": datetime.now().isoformat(),
            "total_cases": total,
            "passed": passed,
            "failed": failed,
            "pass_rate": round(passed / total, 4) if total else 0,
            "avg_overall_score": round(avg_score, 4),
            "min_overall_score": round(min_score, 4),
            "max_overall_score": round(max_score, 4),
            "min_score_case": min_case,
            "max_score_case": max_case,
            "layer_stats": layer_stats,
            "dimension_analysis": dimension_analysis,
            "worst_cases": worst_by_case,
            "top_gap_items": top_gaps,
            "case_details": case_details,
        }

        return report

    def save_aggregate_report(self, results: list[HarnessResult],
                              output_path: Optional[str | Path] = None) -> Path:
        """生成聚合报告并写入文件。"""
        report = self.generate_aggregate_report(results)
        if output_path is None:
            output_path = BASE_DIR / "reports" / f"harness_aggregate_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return output_path


def main():
    """CLI 入口"""
    import argparse

    parser = argparse.ArgumentParser(description="radarAnalyze Harness Runner")
    parser.add_argument("case_id", nargs="?", default=None, help="Case ID to evaluate")
    parser.add_argument("--report", help="Path to report.md (optional)")
    parser.add_argument("--golden-truth", help="Path to ground_truth.json (optional)")
    parser.add_argument("--all", action="store_true", help="Run all available cases")
    parser.add_argument("--json", action="store_true", help="Output JSON format")
    parser.add_argument("--enable-llm-judge", action="store_true",
                        help="Enable LLM-as-judge enhancement for L2 evaluation")
    parser.add_argument("--aggregate-report", type=str, default=None,
                        help="Path to save aggregate report JSON (auto-generated if --all)")
    parser.add_argument("--no-aggregate", action="store_true",
                        help="Skip automatic aggregate report generation")

    args = parser.parse_args()

    # 加载配置和 router（如果需要 LLM judge）
    config = {}
    router = None
    if args.enable_llm_judge:
        import yaml
        config_path = BASE_DIR / "config.yaml"
        if config_path.exists():
            raw_config = config_path.read_text(encoding="utf-8")
            # 简单环境变量替换
            import os
            for match_obj in re.finditer(r'\$\{(\w+)(?::-([^}]*))?}', raw_config):
                env_var = match_obj.group(1)
                default_val = match_obj.group(2) or ""
                raw_config = raw_config.replace(match_obj.group(0), os.environ.get(env_var, default_val))
            config = yaml.safe_load(raw_config)

        # 开启 LLM judge 配置
        if "harness" not in config:
            config["harness"] = {}
        config["harness"]["llm_judge"] = {
            "enabled": True,
            "model_profile": config["harness"].get("llm_judge", {}).get("model_profile", "simple"),
        }

        # 初始化 router
        from ai.model_router import ModelRouter
        router = ModelRouter(config)

    runner = HarnessRunner(config=config, router=router)

    if args.all or args.case_id is None:
        results = runner.run_all_cases()

        # 汇总
        total = len(results)
        passed = sum(1 for r in results if r.passed)
        avg_score = sum(r.overall_score for r in results) / total if total else 0

        print(f"\n{'='*60}")
        print(f"Harness 汇总: {passed}/{total} 通过, 平均分 {avg_score:.2f}")

        # ── 聚合报告 ─────────────────────────────────────
        if not args.no_aggregate:
            report_path = runner.save_aggregate_report(
                results, output_path=args.aggregate_report
            )
            print(f"聚合报告已保存: {report_path}")
            agg = runner.generate_aggregate_report(results)
            print(f"  分层统计 — L0 avg={agg['layer_stats']['l0_structural']['avg']:.2f}, "
                  f"L1 avg={agg['layer_stats']['l1_evidence']['avg']:.2f}, "
                  f"L2 avg={agg['layer_stats']['l2_conclusion']['avg']:.2f}")
            if agg.get("top_gap_items"):
                print(f"  差距项 TOP 3:")
                for g in agg["top_gap_items"][:3]:
                    print(f"    {g['check']}: {g['avg_score']:.2f} ({g['cases_evaluated']} cases)")

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
