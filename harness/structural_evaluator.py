"""
L0 Structural Evaluator — 结构性评估

检查诊断报告的结构完整性，不依赖 LLM，纯规则匹配。
评估维度：
  1. 必备章节是否存在（根因、条件检查、证据链、建议）
  2. 关键数据字段是否填充（功能、现象、窗口）
  3. 证据链质量（信号名、时间戳、值）
  4. 置信度声明
"""

import re
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class StructuralCheck:
    """单条结构性检查结果"""
    name: str
    passed: bool
    description: str
    detail: str = ""
    weight: float = 1.0


@dataclass
class StructuralEvaluationResult:
    """结构性评估结果"""
    score: float  # 0.0 - 1.0
    checks: list[StructuralCheck] = field(default_factory=list)
    summary: str = ""
    
    @property
    def passed(self) -> bool:
        return self.score >= 0.90


class StructuralEvaluator:
    """
    L0 结构性评估器 —— 确定性规则，不依赖 LLM。
    
    输入：诊断 report.md 文本（或路径）
    输出：score (0-1) + 各检查项明细
    """
    
    # 必备章节及其正则匹配
    REQUIRED_SECTIONS = {
        "root_cause": {
            "patterns": [r"###\s*根因", r"root[_\s]*cause", r"###\s*Root"],
            "weight": 2.0,
            "description": "根因分析章节",
        },
        "condition_check": {
            "patterns": [r"###\s*条件检查", r"condition[_\s]*(check|summary)", r"准入门限"],
            "weight": 1.5,
            "description": "条件检查汇总",
        },
        "evidence_chain": {
            "patterns": [r"###\s*关键证据链", r"evidence[_\s]*chain", r"\*\*信号\*\*"],
            "weight": 1.5,
            "description": "关键证据链",
        },
        "fix_recommendation": {
            "patterns": [r"###\s*修复建议", r"fix[_\s]*(recommendation|suggestion)", r"修复方案"],
            "weight": 1.5,
            "description": "修复建议",
        },
        "confidence": {
            "patterns": [r"###\s*置信度", r"confidence", r"\d{2,3}/100"],
            "weight": 1.0,
            "description": "置信度声明",
        },
        "test_window": {
            "patterns": [r"###\s*测试窗口", r"test[_\s]*window", r"测试窗口\d"],
            "weight": 1.0,
            "description": "测试窗口分析",
        },
        "data_chain": {
            "patterns": [r"###\s*数据链路", r"data[_\s]*chain", r"→.*→.*→"],
            "weight": 1.0,
            "description": "数据链路分析",
        },
        "tpe_section": {
            "patterns": [r"###\s*时序耦合", r"tpe", r"TPE触发清单", r"模式.*源文件"],
            "weight": 0.5,
            "description": "TPE时序模式分析",
        },
    }
    
    # 关键元数据字段
    REQUIRED_METADATA = {
        "function": {
            "patterns": [r"[涉及][功功][能能]\s*\|\s*\*\*\w+", r"function.*?FCTA|BSD|LCA|DOW|RCTA|RCTB|RCW|FCTB", r"\| \w+ \|"],
            "weight": 1.0,
            "description": "涉及功能标识",
        },
        "problem_description": {
            "patterns": [r"[问题现][象象]", r"problem", r"没有触发|未触发|失效"],
            "weight": 1.0,
            "description": "问题现象描述",
        },
        "expected_behavior": {
            "patterns": [r"预期", r"expected", r"应该|应当|期望"],
            "weight": 0.5,
            "description": "预期行为描述",
        },
    }
    
    # 证据链要素
    EVIDENCE_REQUIREMENTS = {
        "signal_name": {
            "patterns": [r"\*\*信号\*\*:\s*\S+", r"signal.*?=`\w+`"],
            "weight": 1.5,
            "description": "信号名称",
        },
        "timestamp": {
            "patterns": [r"\*\*时间\*\*:.*?\d{10,}", r"t\s*≈?\s*\d+", r"time.*?\d{10,}"],
            "weight": 1.5,
            "description": "时间戳",
        },
        "signal_value": {
            "patterns": [r"\*\*值\*\*:", r"value.*?[0-9]+"],
            "weight": 1.5,
            "description": "信号数值",
        },
        "data_source": {
            "patterns": [r"\*\*来源\*\*:", r"source.*?[来源源]", r"帧分析|观测层|配置层"],
            "weight": 1.0,
            "description": "数据来源",
        },
    }
    
    def __init__(self):
        self.checks: list[StructuralCheck] = []
    
    def evaluate(self, report_text: str) -> StructuralEvaluationResult:
        """
        评估诊断报告的结构性完整性。
        
        Args:
            report_text: 诊断报告 Markdown 文本
            
        Returns:
            StructuralEvaluationResult with score and detailed checks
        """
        self.checks = []
        
        # 1. 检查必备章节
        self._check_sections(report_text)
        
        # 2. 检查关键元数据
        self._check_metadata(report_text)
        
        # 3. 检查证据链质量
        self._check_evidence(report_text)
        
        # 4. 检查置信度格式
        self._check_confidence_format(report_text)
        
        # 5. 计算加权分数
        score = self._compute_score()
        
        # 6. 生成摘要
        passed = sum(1 for c in self.checks if c.passed)
        total = len(self.checks)
        summary = f"L0 结构评估: {score:.2f} ({passed}/{total} 项通过)"
        
        return StructuralEvaluationResult(
            score=score,
            checks=self.checks,
            summary=summary,
        )
    
    def evaluate_file(self, report_path: str | Path) -> StructuralEvaluationResult:
        """从文件路径加载并评估"""
        path = Path(report_path)
        text = path.read_text(encoding="utf-8")
        return self.evaluate(text)
    
    def to_json(self, result: StructuralEvaluationResult) -> dict:
        """序列化为 JSON 可用的字典"""
        return {
            "score": result.score,
            "passed": result.passed,
            "summary": result.summary,
            "checks": [
                {
                    "name": c.name,
                    "passed": c.passed,
                    "description": c.description,
                    "detail": c.detail,
                    "weight": c.weight,
                }
                for c in result.checks
            ],
        }
    
    # ---- Internal check methods ----
    
    def _check_sections(self, text: str):
        """检查必备章节"""
        for key, cfg in self.REQUIRED_SECTIONS.items():
            matched = False
            detail_parts = []
            for pattern in cfg["patterns"]:
                if re.search(pattern, text, re.IGNORECASE):
                    matched = True
                    detail_parts.append(f"匹配: {pattern}")
                    break
                else:
                    detail_parts.append(f"未匹配: {pattern}")
            
            self.checks.append(StructuralCheck(
                name=f"section.{key}",
                passed=matched,
                description=cfg["description"],
                detail="; ".join(detail_parts),
                weight=cfg["weight"],
            ))
    
    def _check_metadata(self, text: str):
        """检查关键元数据字段"""
        for key, cfg in self.REQUIRED_METADATA.items():
            matched = False
            match_detail = ""
            for pattern in cfg["patterns"]:
                m = re.search(pattern, text, re.IGNORECASE)
                if m:
                    matched = True
                    match_detail = f"匹配 '{pattern}' at: {m.group()[:50]}"
                    break
            
            self.checks.append(StructuralCheck(
                name=f"metadata.{key}",
                passed=matched,
                description=cfg["description"],
                detail=match_detail,
                weight=cfg["weight"],
            ))
    
    def _check_evidence(self, text: str):
        """检查证据链质量"""
        for key, cfg in self.EVIDENCE_REQUIREMENTS.items():
            matched = False
            match_count = 0
            for pattern in cfg["patterns"]:
                matches = re.findall(pattern, text, re.IGNORECASE)
                match_count += len(matches)
                if matches:
                    matched = True
                    break
            
            self.checks.append(StructuralCheck(
                name=f"evidence.{key}",
                passed=matched,
                description=f"证据链-{cfg['description']}",
                detail=f"匹配 {match_count} 处",
                weight=cfg["weight"],
            ))
    
    def _check_confidence_format(self, text: str):
        """检查置信度格式（数字/100）"""
        m = re.search(r"(\d{2,3})/100", text)
        if m:
            val = int(m.group(1))
            valid = 0 <= val <= 100
            detail = f"置信度值: {val}/100"
        else:
            valid = False
            detail = "未找到置信度数字格式"
        
        self.checks.append(StructuralCheck(
            name="confidence.format",
            passed=valid,
            description="置信度数值格式",
            detail=detail,
            weight=1.0,
        ))
    
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
    """CLI 入口 —— 快速测试"""
    import sys
    evaluator = StructuralEvaluator()
    
    report_path = sys.argv[1] if len(sys.argv) > 1 else r"cases/FCTA001/report.md"
    result = evaluator.evaluate_file(report_path)
    
    print(json.dumps(evaluator.to_json(result), ensure_ascii=False, indent=2))
    print(f"\nScore: {result.score:.2f}, Passed: {result.passed}")


if __name__ == "__main__":
    main()
