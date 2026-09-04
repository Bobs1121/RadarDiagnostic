"""
L1 Evidence Evaluator — 证据链评估

检查诊断报告是否覆盖了黄金答案中定义的关键证据要素。
纯确定性规则，不依赖 LLM。

评估维度：
  1. Signal Coverage — 黄金答案中的关键信号是否在报告中出现
  2. Condition Coverage — 黄金答案中的条件检查是否在报告中覆盖
  3. TPE Pattern Coverage — 报告中 TPE 分析与黄金答案的一致性
  4. Window Coverage — 测试窗口是否在报告中出现
  5. Data Chain Coverage — 数据链路是否在报告中描述
"""

import re
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class EvidenceCheck:
    """单条证据检查结果"""
    category: str       # signal / condition / tpe / window / data_chain
    name: str
    passed: bool
    description: str
    detail: str = ""
    weight: float = 1.0


@dataclass
class EvidenceEvaluationResult:
    """L1 证据评估结果"""
    score: float  # 0.0 - 1.0
    checks: list[EvidenceCheck] = field(default_factory=list)
    summary: str = ""

    @property
    def passed(self) -> bool:
        return self.score >= 0.60

    @property
    def signal_score(self) -> float:
        signal_checks = [c for c in self.checks if c.category == "signal"]
        if not signal_checks:
            return 0.0
        total_w = sum(c.weight for c in signal_checks)
        if total_w == 0:
            return 0.0
        return sum(c.weight for c in signal_checks if c.passed) / total_w

    @property
    def condition_score(self) -> float:
        cond_checks = [c for c in self.checks if c.category == "condition"]
        if not cond_checks:
            return 0.0
        total_w = sum(c.weight for c in cond_checks)
        if total_w == 0:
            return 0.0
        return sum(c.weight for c in cond_checks if c.passed) / total_w

    @property
    def window_score(self) -> float:
        win_checks = [c for c in self.checks if c.category == "window"]
        if not win_checks:
            return 0.0
        total_w = sum(c.weight for c in win_checks)
        if total_w == 0:
            return 0.0
        return sum(c.weight for c in win_checks if c.passed) / total_w


class EvidenceEvaluator:
    """
    L1 证据链评估器 —— 确定性规则，不依赖 LLM。

    输入：诊断 report.md 文本 + ground_truth JSON
    输出：score (0-1) + 各检查项明细

    核心逻辑：从 ground_truth 中提取预期证据，检查报告中是否覆盖。
    """

    # 子维度权重
    WEIGHT_SIGNAL = 2.0      # 关键信号覆盖最重要
    WEIGHT_CONDITION = 2.0   # 条件覆盖同样重要
    WEIGHT_TPE = 1.0         # TPE 分析
    WEIGHT_WINDOW = 1.0      # 测试窗口
    WEIGHT_DATA_CHAIN = 1.5  # 数据链路

    def __init__(self):
        self.checks: list[EvidenceCheck] = []

    def evaluate(
        self,
        report_text: str,
        golden_truth: dict,
    ) -> EvidenceEvaluationResult:
        """
        评估诊断报告的证据覆盖度。

        Args:
            report_text: 诊断报告 Markdown 文本
            golden_truth: 黄金答案 JSON dict

        Returns:
            EvidenceEvaluationResult with score and detailed checks
        """
        self.checks = []

        # 1. Signal coverage
        gt_signals = golden_truth.get("ground_truth_root_cause", {}).get("key_signals", [])
        gt_causal_chain = golden_truth.get("ground_truth_root_cause", {}).get("causal_chain", [])
        self._check_signal_coverage(report_text, gt_signals, gt_causal_chain)

        # 2. Condition coverage
        gt_conditions = golden_truth.get("condition_checks", [])
        self._check_condition_coverage(report_text, gt_conditions)

        # 3. TPE pattern coverage
        self._check_tpe_coverage(report_text, golden_truth)

        # 4. Test window coverage
        gt_windows = golden_truth.get("test_windows", [])
        self._check_window_coverage(report_text, gt_windows)

        # 5. Data chain coverage
        gt_chains = golden_truth.get("data_chains", [])
        self._check_data_chain_coverage(report_text, gt_chains)

        # Compute weighted score
        score = self._compute_score()

        passed = sum(1 for c in self.checks if c.passed)
        total = len(self.checks)
        summary = f"L1 证据评估: {score:.2f} ({passed}/{total} 项通过)"

        result = EvidenceEvaluationResult(
            score=score,
            checks=self.checks,
            summary=summary,
        )

        return result

    # ---- Check methods ----

    def _check_signal_coverage(
        self,
        report_text: str,
        gt_signals: list[dict],
        gt_causal_chain: list[str],
    ):
        """
        检查黄金答案中的关键信号是否在报告中出现。

        策略：
        - 对每个 key_signal 的 signal 字段，检查报告是否包含该信号名
        - 对 causal_chain 中的信号引用，也做覆盖检查
        """
        # Extract all signal names from golden truth
        gt_signal_names = set()
        for s in gt_signals:
            sig = s.get("signal", "")
            if sig:
                gt_signal_names.add(sig)

        # Also extract signals mentioned in causal chain — only grab
        # backtick-quoted identifiers (e.g. `rel_vel_x`, `trc_N.vel_x`)
        # to avoid picking up Chinese descriptive text as signal names.
        for step in gt_causal_chain:
            # Backtick-quoted identifiers (high confidence)
            sigs = re.findall(r'`([a-zA-Z_][\w.]*)`', step)
            for sig in sigs:
                gt_signal_names.add(sig)

        # Normalize report text for matching
        report_lower = report_text.lower()

        for sig_name in gt_signal_names:
            # Try multiple matching strategies
            sig_lower = sig_name.lower()

            # Strategy 1: exact match (with word boundary)
            matched = bool(re.search(rf'\b{re.escape(sig_lower)}\b', report_lower))

            # Strategy 2: partial match (signal names often appear truncated, e.g. trc_0 vs trc_N)
            if not matched:
                # Handle trc_N vs trc_0/trc_1 pattern
                base = re.sub(r'\d+', '', sig_lower)
                if base and len(base) > 3:
                    pattern = rf'{re.escape(base)}\d*'
                    matched = bool(re.search(pattern, report_lower))

            # Strategy 3: check for alias/synonym (e.g. vel_x vs 纵向速度)
            if not matched:
                # Common signal aliases
                aliases = self._get_signal_aliases(sig_name)
                for alias in aliases:
                    if alias.lower() in report_lower:
                        matched = True
                        break

            self.checks.append(EvidenceCheck(
                category="signal",
                name=sig_name,
                passed=matched,
                description=f"关键信号: {sig_name}",
                detail=f"{'在报告中找到' if matched else '未在报告中找到'}",
                weight=self.WEIGHT_SIGNAL,
            ))

        # If no signals in golden truth, mark as N/A (pass)
        if not gt_signal_names:
            self.checks.append(EvidenceCheck(
                category="signal",
                name="none",
                passed=True,
                description="黄金答案未定义关键信号",
                detail="N/A",
                weight=0.0,
            ))

    def _check_condition_coverage(
        self,
        report_text: str,
        gt_conditions: list[dict],
    ):
        """
        检查黄金答案中的条件检查是否在报告中覆盖。

        策略：检查每个 condition 的描述是否出现在报告中。
        """
        report_lower = report_text.lower()

        for cond in gt_conditions:
            cond_name = cond.get("condition", "")
            threshold = cond.get("threshold", "")
            actual = cond.get("actual", "")

            if not cond_name:
                continue

            cond_lower = cond_name.lower()

            matched = False
            match_detail = ""

            # Strategy 1: direct condition name match
            if cond_lower in report_lower:
                matched = True
                match_detail = f"直接匹配条件名 '{cond_name}'"

            # Strategy 2: threshold value match (e.g. "≤20.0 km/h", ">4.0")
            if not matched and threshold:
                # Extract numeric parts from threshold
                nums = re.findall(r'[\d.]+', threshold)
                for num in nums:
                    if num in report_lower:
                        matched = True
                        match_detail = f"通过阈值数值 '{num}' 匹配"
                        break

            # Strategy 3: keyword aliases
            if not matched:
                aliases = self._get_condition_aliases(cond_name)
                for alias in aliases:
                    if alias.lower() in report_lower:
                        matched = True
                        match_detail = f"通过别名 '{alias}' 匹配"
                        break

            self.checks.append(EvidenceCheck(
                category="condition",
                name=cond_name,
                passed=matched,
                description=f"条件检查: {cond_name}",
                detail=match_detail if matched else "未在报告中找到匹配",
                weight=self.WEIGHT_CONDITION,
            ))

        if not gt_conditions:
            self.checks.append(EvidenceCheck(
                category="condition",
                name="none",
                passed=True,
                description="黄金答案未定义条件检查",
                detail="N/A",
                weight=0.0,
            ))

    def _check_tpe_coverage(
        self,
        report_text: str,
        golden_truth: dict,
    ):
        """
        检查 TPE 分析覆盖度。

        策略：
        - 检查报告是否有 TPE 相关章节
        - 如果黄金答案定义了 TPE 模式，检查是否覆盖
        """
        # Check if report has TPE section (already checked in L0, but verify content)
        tpe_section_match = re.search(
            r'(?:###\s*时序耦合|tpe|TPE触发清单)',
            report_text,
            re.IGNORECASE,
        )

        if tpe_section_match:
            # Report has TPE section
            # Check if golden truth expects specific TPE patterns
            # For now, just verify TPE section exists with content
            self.checks.append(EvidenceCheck(
                category="tpe",
                name="tpe_section",
                passed=True,
                description="TPE分析章节",
                detail=f"找到TPE章节: {tpe_section_match.group()}",
                weight=self.WEIGHT_TPE,
            ))
        else:
            self.checks.append(EvidenceCheck(
                category="tpe",
                name="tpe_section",
                passed=False,
                description="TPE分析章节",
                detail="未找到TPE分析内容",
                weight=self.WEIGHT_TPE,
            ))

    def _check_window_coverage(
        self,
        report_text: str,
        gt_windows: list[dict],
    ):
        """
        检查测试窗口是否在报告中出现。

        策略：从黄金答案中提取窗口时间戳，检查报告是否包含这些时间戳。
        """
        report_lower = report_text.lower()

        for win in gt_windows:
            win_id = win.get("id", "?")
            start = win.get("start", 0)
            end = win.get("end", 0)
            event = win.get("event", "")

            matched = False
            match_detail = ""

            # Strategy 1: timestamp match (truncate to integer part)
            start_str = str(int(start))
            if start_str in report_lower:
                matched = True
                match_detail = f"通过起始时间戳 '{start_str}' 匹配"

            # Strategy 2: floating point partial match
            if not matched:
                start_float = f"{start:.1f}"
                if start_float in report_text:
                    matched = True
                    match_detail = f"通过浮点时间戳 '{start_float}' 匹配"

            # Strategy 3: event description match
            if not matched and event:
                event_lower = event.lower()
                if event_lower in report_lower:
                    matched = True
                    match_detail = f"通过事件描述 '{event}' 匹配"

            self.checks.append(EvidenceCheck(
                category="window",
                name=f"window_{win_id}",
                passed=matched,
                description=f"测试窗口 {win_id}: {event}",
                detail=match_detail if matched else "未匹配到该窗口",
                weight=self.WEIGHT_WINDOW,
            ))

        if not gt_windows:
            self.checks.append(EvidenceCheck(
                category="window",
                name="none",
                passed=True,
                description="黄金答案未定义测试窗口",
                detail="N/A",
                weight=0.0,
            ))

    def _check_data_chain_coverage(
        self,
        report_text: str,
        gt_chains: list[dict],
    ):
        """
        检查数据链路是否在报告中描述。

        策略：从黄金答案的 data_chains 中提取关键词，检查是否出现在报告中。
        """
        for i, chain in enumerate(gt_chains):
            chain_text = chain.get("chain", "")
            description = chain.get("description", "")

            if not chain_text:
                continue

            matched = False
            match_detail = ""

            # Extract key terms from chain (signals, functions, variables)
            key_terms = re.findall(r'[A-Z_]{3,}|\w+\.c|\w+\.\w+', chain_text)

            matches = 0
            for term in key_terms[:5]:  # Check up to 5 key terms
                if term.lower() in report_text.lower():
                    matches += 1

            # Match if at least 50% of key terms found
            if key_terms and matches / max(len(key_terms), 1) >= 0.5:
                matched = True
                match_detail = f"{matches}/{len(key_terms)} 关键词匹配"

            # Also check description
            if not matched and description:
                desc_terms = re.findall(r'\w+', description)
                desc_matches = sum(1 for t in desc_terms if len(t) > 2 and t.lower() in report_text.lower())
                if desc_matches >= 3:
                    matched = True
                    match_detail = f"描述中有 {desc_matches} 个词匹配"

            self.checks.append(EvidenceCheck(
                category="data_chain",
                name=f"chain_{i}",
                passed=matched,
                description=f"数据链路 {i+1}: {description[:50]}..." if description else f"数据链路 {i+1}",
                detail=match_detail if matched else "未在报告中找到匹配的链路描述",
                weight=self.WEIGHT_DATA_CHAIN,
            ))

        if not gt_chains:
            self.checks.append(EvidenceCheck(
                category="data_chain",
                name="none",
                passed=True,
                description="黄金答案未定义数据链路",
                detail="N/A",
                weight=0.0,
            ))

    # ---- Helper methods ----

    def _get_signal_aliases(self, signal_name: str) -> list[str]:
        """获取信号的常见别名/中文描述"""
        aliases = {}
        # Common signal name to Chinese descriptions
        if "vel_x" in signal_name.lower():
            aliases = ["纵向速度", "相对速度", "纵向相对速度", "vel_x"]
        elif "ttc" in signal_name.lower():
            aliases = ["TTC", "碰撞时间", "TTM"]
        elif "fcta_system_state" in signal_name.lower():
            aliases = ["fcta_system_state", "系统状态", "状态机"]
        elif "warning" in signal_name.lower():
            aliases = ["告警", "warning", "warn"]
        elif "vehicle_speed" in signal_name.lower() or "car_spd" in signal_name.lower():
            aliases = ["车速", "vehicle_speed", "car_spd"]
        elif "dist" in signal_name.lower():
            aliases = ["距离", "dist"]

        return list(aliases)

    def _get_condition_aliases(self, condition_name: str) -> list[str]:
        """获取条件的常见别名"""
        aliases = []
        name_lower = condition_name.lower()

        if "速度" in name_lower or "speed" in name_lower:
            aliases = ["速度", "speed", "km/h", "m/s"]
        elif "ttc" in name_lower or "碰撞" in name_lower:
            aliases = ["TTC", "碰撞时间", "ttc"]
        elif "抑制" in name_lower or "suppress" in name_lower:
            aliases = ["抑制", "suppress", "Acc", "ESP"]
        elif "roi" in name_lower or "角度" in name_lower:
            aliases = ["ROI", "角度", "角度收敛", "roi"]

        return aliases

    def _compute_score(self) -> float:
        """加权平均计算总分"""
        if not self.checks:
            return 0.0

        total_weight = sum(c.weight for c in self.checks)
        if total_weight == 0:
            return 0.0

        weighted_pass = sum(c.weight for c in self.checks if c.passed)
        return weighted_pass / total_weight


def main():
    """CLI 入口"""
    import sys

    evaluator = EvidenceEvaluator()

    # Default paths
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
        "signal_score": round(result.signal_score, 4),
        "condition_score": round(result.condition_score, 4),
        "window_score": round(result.window_score, 4),
        "checks": [
            {
                "category": c.category,
                "name": c.name,
                "passed": c.passed,
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
