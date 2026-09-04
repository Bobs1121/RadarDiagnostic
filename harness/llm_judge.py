# -*- coding: utf-8 -*-
"""
LLM-as-judge 评估器 — 为 Harness L2 结论评估提供语义级因果匹配能力。

设计原则：
  1. 默认关闭（enable_llm_judge=false），L2 baseline 仍然是"可复现下限"
  2. LLM judge 输出与 baseline 取 max：final = max(baseline_score, llm_score)
  3. 失败降级：LLM 调用失败时回退到 baseline 分数
  4. 所有 LLM judge 结果都记录 reasoning，方便审计

接口：
  LLMJudge(router, config) -> judge(report_text, ground_truth, category) -> LLMJudgeResult
"""

import json
import re
import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class LLMJudgeResult:
    """单次 LLM judge 结果"""
    category: str          # "classification" / "localization" / "causal"
    score: float           # 0.0 - 1.0
    reasoning: str         # LLM 给出的评分理由
    baseline_score: float  # 原始 baseline 分数（用于对比）
    used_llm: bool         # 是否实际使用了 LLM（True=用了，False=降级）
    llm_error: Optional[str] = None  # LLM 调用错误信息

    def final_score(self) -> float:
        """取 baseline 和 LLM 分数的最大值"""
        if not self.used_llm:
            return self.baseline_score
        return max(self.baseline_score, self.score)


# ── 固化评分 rubric ──────────────────────────────────────────────────────

CLASSIFICATION_RUBRIC = """你是一个雷达 ADAS 诊断质量评估专家。请根据以下标准评估诊断报告的功能分类是否正确。

## 评分标准
- **1.0 分**：诊断报告识别的功能与黄金答案完全一致
- **0.7 分**：诊断报告识别的功能与黄金答案属于同一子系统（如都是 FCT 系列），或有合理的语义等价
- **0.3 分**：诊断报告识别的功能与黄金答案有部分关联（如相关功能但不同）
- **0.0 分**：诊断报告识别的功能与黄金答案完全不相关

请以 JSON 格式返回：
{
    "score": 0.0-1.0,
    "reasoning": "评分理由（50字以内）"
}
"""

LOCALIZATION_RUBRIC = """你是一个雷达 ADAS 诊断质量评估专家。请评估诊断报告的根因定位准确度。

## 评分标准
- **1.0 分**：诊断定位到与黄金答案相同的根本原因（可以是同一原因的不同表述，核心机制一致）
- **0.7 分**：诊断定位到了相关层级的原因，与黄金答案有直接因果关联（如黄金答案是"信号映射断裂"，诊断说是"RTE 接口失效"）
- **0.4 分**：诊断定位到了现象层级或次要原因，与黄金答案间接相关
- **0.0 分**：诊断定位与黄金答案毫无关联，或定位错误

请以 JSON 格式返回：
{
    "score": 0.0-1.0,
    "reasoning": "评分理由（50字以内）"
}
"""

CAUSAL_RUBRIC = """你是一个雷达 ADAS 诊断质量评估专家。请评估诊断报告的因果解释质量。

## 评分标准
- **1.0 分**：诊断报告提供了完整的因果链，从根因到症状的逻辑链条完整，与黄金答案的因果解释一致
- **0.7 分**：诊断报告提供了部分因果链，关键环节正确但缺少部分中间步骤
- **0.4 分**：诊断报告提到了根因但缺乏因果推导过程，或因果链有明显断裂
- **0.0 分**：诊断报告的因果解释与黄金答案矛盾，或完全没有因果分析

请以 JSON 格式返回：
{
    "score": 0.0-1.0,
    "reasoning": "评分理由（50字以内）"
}
"""

RUBRIC_MAP = {
    "classification": CLASSIFICATION_RUBRIC,
    "localization": LOCALIZATION_RUBRIC,
    "causal": CAUSAL_RUBRIC,
}


class LLMJudge:
    """
    LLM-as-judge 评估器。

    Args:
        router: ModelRouter 实例（用于调用 LLM）
        judge_config: config.yaml 中的 harness.llm_judge 配置段
    """

    def __init__(self, router, judge_config: dict):
        self.router = router
        self.enabled = judge_config.get("enabled", False)
        self.model_profile = judge_config.get("model_profile", "simple")

    def judge(
        self,
        report_text: str,
        ground_truth: dict,
        category: str,
        baseline_score: float,
    ) -> LLMJudgeResult:
        """
        对单个评估维度运行 LLM judge。

        Args:
            report_text: 诊断报告全文
            ground_truth: 黄金答案 JSON
            category: 评估维度 ("classification" / "localization" / "causal")
            baseline_score: 当前 baseline 分数

        Returns:
            LLMJudgeResult with score, reasoning, and metadata
        """
        result = LLMJudgeResult(
            category=category,
            score=baseline_score,
            reasoning="LLM judge 未启用",
            baseline_score=baseline_score,
            used_llm=False,
        )

        if not self.enabled:
            return result

        rubric = RUBRIC_MAP.get(category)
        if not rubric:
            result.reasoning = f"未知评估类别: {category}"
            return result

        # 构建 prompt
        prompt = self._build_prompt(report_text, ground_truth, category, rubric)

        try:
            llm_score, reasoning = self._call_llm(prompt)
            result.score = llm_score
            result.reasoning = reasoning
            result.used_llm = True
        except Exception as e:
            result.llm_error = str(e)
            result.reasoning = f"LLM 调用失败，使用 baseline 分数: {e}"
            result.score = baseline_score
            result.used_llm = False

        return result

    def _build_prompt(self, report_text: str, ground_truth: dict, category: str, rubric: str) -> str:
        """构建 LLM judge prompt"""
        # 提取黄金答案中的关键信息 — 对齐实际 ground_truth schema
        gt_problem = ground_truth.get("problem_statement", {})
        gt_func = gt_problem.get("function", "N/A")
        gt_root_cause = ground_truth.get("ground_truth_root_cause", {})
        gt_primary = gt_root_cause.get("primary_cause", "N/A")

        # 根据类别构建对比信息
        if category == "classification":
            comparison = f"黄金答案功能: {gt_func}"
        elif category == "localization":
            comparison = f"黄金答案根因: {gt_primary}"
            # Also include causal chain for context
            causal_chain = gt_root_cause.get("causal_chain", [])
            if causal_chain:
                comparison += "\n因果链:\n" + "\n".join(f"  - {step}" for step in causal_chain)
        elif category == "causal":
            comparison = f"黄金答案根因: {gt_primary}"
            fixes = ground_truth.get("key_fix_recommendations", [])
            if fixes:
                comparison += "\n修复建议:\n" + "\n".join(f"  - {f}" for f in fixes)
        else:
            comparison = "N/A"

        # 截断报告文本（控制 token 消耗）
        report_excerpt = report_text[:8000]
        if len(report_text) > 8000:
            report_excerpt += f"\n\n[报告内容截断，全文 {len(report_text)} 字符]"

        user_prompt = f"""{rubric}

## 黄金答案信息
{comparison}

## 诊断报告（节选）
---
{report_excerpt}
---

请评估并返回 JSON 结果。"""

        system_prompt = "你是一个专业的雷达 ADAS 诊断质量评估员。严格根据评分标准进行客观评分，不要放水。"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        return messages

    def _call_llm(self, messages: list[dict]) -> tuple[float, str]:
        """
        调用 LLM 获取评分。

        Returns:
            (score, reasoning) 元组
        """
        start = time.time()

        response = self.router.chat(
            messages=messages,
            complexity=self.model_profile,
            temperature=0.0,
            max_tokens=512,
        )

        content = response.get("content", "")
        elapsed = time.time() - start

        # 从 LLM 响应中解析 JSON
        parsed = self._parse_json_from_response(content)

        if parsed:
            score = float(parsed.get("score", 0.0))
            reasoning = parsed.get("reasoning", "未提供评分理由")
        else:
            # 解析失败，给 0 分
            score = 0.0
            reasoning = f"JSON 解析失败，原始响应: {content[:200]}"

        # 确保 score 在 [0, 1] 范围内
        score = max(0.0, min(1.0, score))

        return score, reasoning

    @staticmethod
    def _parse_json_from_response(content: str) -> Optional[dict]:
        """从 LLM 响应中提取 JSON"""
        # 尝试直接解析
        content = content.strip()
        if content.startswith("{"):
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                pass

        # 尝试从 markdown code block 中提取
        json_match = re.search(r'```(?:json)?\s*\n(.*?)\n```', content, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1).strip())
            except json.JSONDecodeError:
                pass

        # 尝试找第一个 { 到最后一个 }
        first_brace = content.find("{")
        last_brace = content.rfind("}")
        if first_brace >= 0 and last_brace > first_brace:
            try:
                return json.loads(content[first_brace:last_brace + 1])
            except json.JSONDecodeError:
                pass

        return None
