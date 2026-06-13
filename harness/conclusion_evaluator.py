"""
L2 Conclusion Evaluator — 结论评估

检查诊断报告的结论是否与黄金答案的根因分析一致。
包含确定性规则（关键词/模式匹配）和可选 LLM 语义评分模式。

评估维度：
  1. Function Classification — 报告是否识别了正确的功能
  2. Root Cause Localization — 是否定位到正确的函数/文件
  3. Causal Keyword Match — 根因描述的关键概念是否一致
  4. Fix Recommendation Overlap — 修复建议与黄金答案的重叠度
  5. Confidence Alignment — 置信度声明是否合理
"""

import re
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class ConclusionCheck:
    """单条结论检查结果"""
    category: str       # classification / localization / causal / fix / confidence
    name: str
    passed: bool
    score: float        # 0.0 - 1.0 (partial credit)
    description: str
    detail: str = ""
    weight: float = 1.0


@dataclass
class ConclusionEvaluationResult:
    """L2 结论评估结果"""
    score: float  # 0.0 - 1.0
    checks: list[ConclusionCheck] = field(default_factory=list)
    summary: str = ""

    @property
    def passed(self) -> bool:
        return self.score >= 0.60

    @property
    def classification_score(self) -> float:
        cls_checks = [c for c in self.checks if c.category == "classification"]
        if not cls_checks:
            return 0.0
        return sum(c.score * c.weight for c in cls_checks) / sum(c.weight for c in cls_checks)

    @property
    def localization_score(self) -> float:
        loc_checks = [c for c in self.checks if c.category == "localization"]
        if not loc_checks:
            return 0.0
        return sum(c.score * c.weight for c in loc_checks) / sum(c.weight for c in loc_checks)

    @property
    def causal_score(self) -> float:
        causal_checks = [c for c in self.checks if c.category == "causal"]
        if not causal_checks:
            return 0.0
        return sum(c.score * c.weight for c in causal_checks) / sum(c.weight for c in causal_checks)


class ConclusionEvaluator:
    """
    L2 结论评估器 —— 确定性规则 + 可选 LLM 语义评分。

    输入：诊断 report.md 文本 + ground_truth JSON
    输出：score (0-1) + 各检查项明细

    核心逻辑：从 ground_truth 中提取预期结论，检查报告结论的一致性。
    """

    # 子维度权重
    WEIGHT_CLASSIFICATION = 2.0   # 功能分类最重要
    WEIGHT_LOCALIZATION = 1.5    # 函数定位
    WEIGHT_CAUSAL = 2.5          # 因果关键词匹配
    WEIGHT_FIX = 1.0             # 修复建议
    WEIGHT_CONFIDENCE = 0.5      # 置信度对齐

    # 根因常见概念映射（中文 <-> 英文）
    ROOT_CAUSE_CONCEPTS = {
        # TTC / 碰撞时间相关
        "ttc": ["ttc", "碰撞时间", "time to collision", "TTM", "TTC发散", "TTC溢出", "TTC=inf"],
        "velocity": ["vel_x", "纵向速度", "相对速度", "velocity", "speed", "低速", "速度趋零"],
        "threshold": ["阈值", "门槛", "门限", "threshold", "准入", "条件不满足"],
        "filter": ["过滤", "filter", "拦截", "筛选", "排除"],
        "state_machine": ["状态机", "state machine", "Standby", "Passive", "状态", "state"],
        "warning_flag": ["告警标志", "warning", "warnFlag", "bWarn", "告警标志", "警告"],
        "radar": ["雷达", "radar", "感知", "目标检测"],
        "doppler": ["多普勒", "doppler", "多普勒效应", "多普勒分量"],
        "scaling": ["缩放", "scaling", "因子", "factor", "系数"],
    }

    def __init__(self):
        self.checks: list[ConclusionCheck] = []

    def evaluate(
        self,
        report_text: str,
        golden_truth: dict,
    ) -> ConclusionEvaluationResult:
        """
        评估诊断报告的结论正确性。

        Args:
            report_text: 诊断报告 Markdown 文本
            golden_truth: 黄金答案 JSON dict

        Returns:
            ConclusionEvaluationResult with score and detailed checks
        """
        self.checks = []

        # 1. Function classification
        gt_func = golden_truth.get("problem_statement", {}).get("function", "")
        self._check_classification(report_text, gt_func)

        # 2. Root cause localization (functions/files mentioned)
        gt_causal_chain = golden_truth.get("ground_truth_root_cause", {}).get("causal_chain", [])
        gt_primary = golden_truth.get("ground_truth_root_cause", {}).get("primary_cause", "")
        self._check_localization(report_text, gt_causal_chain, gt_primary)

        # 3. Causal keyword/concept matching
        self._check_causal_keywords(report_text, gt_primary, gt_causal_chain)

        # 4. Fix recommendation overlap
        gt_fixes = golden_truth.get("key_fix_recommendations", [])
        self._check_fix_overlap(report_text, gt_fixes)

        # 5. Confidence alignment
        gt_confidence = golden_truth.get("confidence", {})
        self._check_confidence_alignment(report_text, gt_confidence)

        # Compute weighted score
        score = self._compute_score()

        passed = sum(1 for c in self.checks if c.passed)
        total = len(self.checks)
        summary = f"L2 结论评估: {score:.2f} ({passed}/{total} 项通过)"

        result = ConclusionEvaluationResult(
            score=score,
            checks=self.checks,
            summary=summary,
        )

        return result

    # ---- Check methods ----

    def _check_classification(
        self,
        report_text: str,
        gt_function: str,
    ):
        """检查报告是否识别了正确的功能"""
        if not gt_function:
            self.checks.append(ConclusionCheck(
                category="classification",
                name="function",
                passed=True,
                score=1.0,
                description="功能分类",
                detail="黄金答案未指定功能，跳过",
                weight=self.WEIGHT_CLASSIFICATION,
            ))
            return

        report_lower = report_text.lower()
        func_lower = gt_function.lower()

        # Check if function name appears in report
        matched = func_lower in report_lower

        self.checks.append(ConclusionCheck(
            category="classification",
            name="function",
            passed=matched,
            score=1.0 if matched else 0.0,
            description=f"功能分类: {gt_function}",
            detail=f"{'在报告中找到' if matched else '未在报告中找到'}功能 '{gt_function}'",
            weight=self.WEIGHT_CLASSIFICATION,
        ))

    def _check_localization(
        self,
        report_text: str,
        gt_causal_chain: list[str],
        gt_primary: str,
    ):
        """
        检查是否定位到正确的函数/文件。

        从因果链和主因中提取 .c/.h 文件引用，检查是否在报告中出现。
        """
        report_lower = report_text.lower()

        # Extract file references (e.g. "adasFunc.c", "track.c")
        # Only match English/ASCII identifiers — skip Chinese prefixes like "触发adasFunc"
        gt_files = set()
        for text in [gt_primary] + gt_causal_chain:
            files = re.findall(r'([a-zA-Z_]\w*(?:\.\w+)?)\.(?:c|h|cpp|h|hpp)', text)
            gt_files.update(files)

        for gt_file in gt_files:
            # Check if file reference appears in report
            file_lower = gt_file.lower()
            matched = file_lower in report_lower

            self.checks.append(ConclusionCheck(
                category="localization",
                name=f"file:{gt_file}",
                passed=matched,
                score=1.0 if matched else 0.0,
                description=f"文件定位: {gt_file}",
                detail=f"{'在报告中找到' if matched else '未在报告中找到'}文件 '{gt_file}'",
                weight=self.WEIGHT_LOCALIZATION,
            ))

        if not gt_files:
            self.checks.append(ConclusionCheck(
                category="localization",
                name="none",
                passed=True,
                score=1.0,
                description="文件定位",
                detail="黄金答案未定义文件引用，跳过",
                weight=0.0,
            ))

    def _check_causal_keywords(
        self,
        report_text: str,
        gt_primary: str,
        gt_causal_chain: list[str],
    ):
        """
        检查根因描述的关键概念是否一致。

        策略：从 ROOT_CAUSE_CONCEPTS 中找出黄金答案涉及的概念，
        检查报告中是否也有对应概念的提及。
        """
        report_lower = report_text.lower()
        gt_text = (gt_primary + " " + " ".join(gt_causal_chain)).lower()

        matched_concepts = []
        missing_concepts = []

        for concept, keywords in self.ROOT_CAUSE_CONCEPTS.items():
            # Check if this concept is present in golden truth
            gt_has = any(kw.lower() in gt_text for kw in keywords)
            if not gt_has:
                continue  # Concept not in golden truth, skip

            # Check if this concept is present in report
            report_has = any(kw.lower() in report_lower for kw in keywords)
            if report_has:
                matched_concepts.append(concept)
            else:
                missing_concepts.append(concept)

        total_concepts = len(matched_concepts) + len(missing_concepts)

        if total_concepts == 0:
            self.checks.append(ConclusionCheck(
                category="causal",
                name="concepts",
                passed=True,
                score=1.0,
                description="因果概念匹配",
                detail="未识别到标准概念，跳过",
                weight=self.WEIGHT_CAUSAL,
            ))
            return

        # Partial credit: proportion of matched concepts
        match_ratio = len(matched_concepts) / total_concepts
        passed = match_ratio >= 0.5  # Pass if at least 50% concepts matched

        self.checks.append(ConclusionCheck(
            category="causal",
            name="concepts",
            passed=passed,
            score=match_ratio,
            description=f"因果概念匹配: {len(matched_concepts)}/{total_concepts} 概念一致",
            detail=f"匹配: {', '.join(matched_concepts)}; 缺失: {', '.join(missing_concepts)}" if missing_concepts else f"全部 {len(matched_concepts)} 个概念匹配",
            weight=self.WEIGHT_CAUSAL,
        ))

        # Additional: check primary cause keyword overlap (TF-based)
        if gt_primary:
            gt_words = set(re.findall(r'[\u4e00-\u9fff]+|[a-zA-Z_]{3,}', gt_primary))
            report_root_cause = re.search(
                r'(?:###\s*根因|root[_\s]*cause).*?(?=###|\Z)',
                report_text,
                re.IGNORECASE | re.DOTALL,
            )
            if report_root_cause:
                report_words = set(re.findall(r'[\u4e00-\u9fff]+|[a-zA-Z_]{3,}', report_root_cause.group()))
                # Jaccard-like overlap (intersection / union)
                intersection = gt_words & report_words
                union = gt_words | report_words
                overlap = len(intersection) / max(len(union), 1)
                passed_kw = overlap >= 0.2  # 20% overlap threshold

                self.checks.append(ConclusionCheck(
                    category="causal",
                    name="primary_cause_keywords",
                    passed=passed_kw,
                    score=min(overlap / 0.5, 1.0),  # Normalize: 0.5 overlap = full score
                    description=f"主因关键词重叠: {overlap:.2f}",
                    detail=f"黄金答案关键词: {', '.join(sorted(gt_words)[:10])}; 重叠: {', '.join(sorted(intersection)[:5])}" if intersection else "无明显关键词重叠",
                    weight=self.WEIGHT_CAUSAL,
                ))
            else:
                self.checks.append(ConclusionCheck(
                    category="causal",
                    name="primary_cause_keywords",
                    passed=False,
                    score=0.0,
                    description="主因关键词重叠",
                    detail="未找到报告根因章节",
                    weight=self.WEIGHT_CAUSAL,
                ))

    def _check_fix_overlap(
        self,
        report_text: str,
        gt_fixes: list[str],
    ):
        """
        检查修复建议与黄金答案的重叠度。

        策略：从黄金答案的修复建议中提取关键词，检查报告中是否提及。
        """
        if not gt_fixes:
            self.checks.append(ConclusionCheck(
                category="fix",
                name="recommendations",
                passed=True,
                score=1.0,
                description="修复建议重叠",
                detail="黄金答案未定义修复建议，跳过",
                weight=self.WEIGHT_FIX,
            ))
            return

        report_lower = report_text.lower()

        matched_fixes = 0
        fix_details = []

        for fix in gt_fixes:
            fix_lower = fix.lower()
            # Extract key terms from fix recommendation
            key_terms = re.findall(r'[\u4e00-\u9fff]{2,}|[a-zA-Z_]{3,}', fix_lower)
            matched_terms = sum(1 for t in key_terms if t in report_lower)
            # Consider a fix "matched" if at least 50% of key terms found
            if key_terms and matched_terms / len(key_terms) >= 0.5:
                matched_fixes += 1

            fix_details.append(f"建议{matched_terms}/{len(key_terms)}关键词匹配")

        match_ratio = matched_fixes / max(len(gt_fixes), 1)
        passed = match_ratio >= 0.3  # Pass if at least 30% of fixes have some overlap

        self.checks.append(ConclusionCheck(
            category="fix",
            name="recommendations",
            passed=passed,
            score=match_ratio,
            description=f"修复建议重叠: {matched_fixes}/{len(gt_fixes)} 建议部分匹配",
            detail="; ".join(fix_details),
            weight=self.WEIGHT_FIX,
        ))

    def _check_confidence_alignment(
        self,
        report_text: str,
        gt_confidence: dict,
    ):
        """
        检查置信度声明是否合理。

        策略：
        - 提取报告中置信度数值
        - 提取黄金答案中置信度数值
        - 检查两者是否在合理范围内接近（±15）
        """
        # Extract confidence from report (NN/100 format)
        report_conf = None
        m = re.search(r'(\d{2,3})/100', report_text)
        if m:
            report_conf = int(m.group(1))

        # Extract confidence from golden truth
        gt_conf = gt_confidence.get("value")

        if report_conf is None:
            self.checks.append(ConclusionCheck(
                category="confidence",
                name="value",
                passed=False,
                score=0.0,
                description="置信度对齐",
                detail="报告中未找到置信度声明",
                weight=self.WEIGHT_CONFIDENCE,
            ))
            return

        if gt_conf is None:
            self.checks.append(ConclusionCheck(
                category="confidence",
                name="value",
                passed=True,
                score=1.0,
                description="置信度声明",
                detail=f"报告置信度: {report_conf}/100（黄金答案未指定）",
                weight=self.WEIGHT_CONFIDENCE,
            ))
            return

        diff = abs(report_conf - gt_conf)
        within_range = diff <= 15  # Acceptable deviation

        self.checks.append(ConclusionCheck(
            category="confidence",
            name="value",
            passed=within_range,
            score=max(0.0, 1.0 - diff / 30.0),  # Linear decay: 0 diff = 1.0, 30+ diff = 0.0
            description=f"置信度对齐: 报告={report_conf}/100, 黄金={gt_conf}/100, 差值={diff}",
            detail=f"{'在合理范围内' if within_range else '超出合理范围(±15)'}",
            weight=self.WEIGHT_CONFIDENCE,
        ))

    def _compute_score(self) -> float:
        """加权平均计算总分"""
        if not self.checks:
            return 0.0

        total_weight = sum(c.weight for c in self.checks)
        if total_weight == 0:
            return 0.0

        weighted_score = sum(c.score * c.weight for c in self.checks)
        return weighted_score / total_weight


def main():
    """CLI 入口"""
    import sys

    evaluator = ConclusionEvaluator()

    report_path = r"cases/FCTA001/report.md"
    truth_path = r"harness/golden_truths/FCTA001_ground_truth.json"

    if len(sys.argv) > 1:
        report_path = sys.argv[1]
    if len(sys.argv) > 2:
        truth_path = sys.argv[2]

    report_text = Path(report_path).read_text(encoding="utf-8")
    golden_truth = json.loads(Path(truth_path).read_text(encoding="utf-8"))

    result = evaluator.evaluate(report_text, golden_truth)

    print(json.dumps({
        "score": result.score,
        "passed": result.passed,
        "summary": result.summary,
        "classification_score": round(result.classification_score, 4),
        "localization_score": round(result.localization_score, 4),
        "causal_score": round(result.causal_score, 4),
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
            for c in result.checks
        ],
    }, ensure_ascii=False, indent=2))

    print(f"\nScore: {result.score:.2f}, Passed: {result.passed}")


if __name__ == "__main__":
    main()
