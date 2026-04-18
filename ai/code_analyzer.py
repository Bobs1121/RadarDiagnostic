# -*- coding: utf-8 -*-
"""
Source code analyzer: reads C source files and uses AI to extract
function logic, state machines, thresholds, and key variables.
"""
import json
from pathlib import Path
from typing import Optional
from .model_router import ModelRouter
from .utils import ALL_FUNCTIONS as _ALL_FUNCTIONS

SYSTEM_PROMPT = """你是一名资深的汽车ADAS软件工程师，专门分析角雷达（Corner Radar）的功能代码。
你需要分析C语言源码，提取以下信息：

1. **功能状态机**: 状态定义（None/Init/Standby/Active/Off/Failure/Passive）、状态转换条件
2. **关键阈值**: 距离、速度、TTC、角度等判断阈值
3. **报警逻辑**: 触发报警和取消报警的条件
4. **关键变量**: 影响功能行为的核心变量，标注其类型和来源
5. **输入输出**: 功能接收的输入信号和输出的报警/制动请求

关注的功能: BSD(盲区检测), LCA(变道辅助), DOW(开门预警), RCW(后方碰撞预警),
RCTA(后方交叉交通警报), RCTB(后方交叉交通制动), FCTA(前方交叉交通警报), FCTB(前方交叉交通制动)

输出使用中文，技术术语保留英文。"""


class CodeAnalyzer:
    """Analyze corner radar source code and generate function documentation."""

    FUNCTIONS = _ALL_FUNCTIONS

    def __init__(self, router: ModelRouter, config: dict):
        self.router = router
        self.source_root = Path(config["paths"]["source_code"])
        self.key_files = config["paths"].get("key_source_files", [])
        self.output_dir = Path(config["paths"].get("source_docs", "./source_docs"))
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def analyze_function(self, func_name: str) -> str:
        """Analyze a single function and save documentation."""
        file_contents = self._read_source_files()
        doc = self._analyze_function(func_name, file_contents)
        doc_path = self.output_dir / f"{func_name}.md"
        doc_path.write_text(doc, encoding="utf-8")
        return doc

    def _read_source_files(self) -> dict[str, str]:
        """Read all key source files into memory."""
        contents = {}
        for rel_path in self.key_files:
            full_path = self.source_root / rel_path
            if full_path.exists():
                try:
                    text = full_path.read_text(encoding="utf-8", errors="replace")
                    # Truncate very large files to fit context window
                    if len(text) > 80000:
                        text = text[:80000] + "\n\n// ... [TRUNCATED] ..."
                    contents[rel_path] = text
                except Exception as e:
                    contents[rel_path] = f"// Error reading file: {e}"
            else:
                contents[rel_path] = "// File not found"
        return contents

    def _analyze_function(self, func_name: str, file_contents: dict) -> str:
        """Use Qwen to analyze a specific ADAS function across all source files."""
        relevant_code = self._extract_relevant_code(func_name, file_contents)

        prompt = f"""请分析角雷达中 **{func_name}** 功能的完整逻辑。

以下是相关的源码片段：

{relevant_code}

请输出以下结构的Markdown文档：

# {func_name} 功能分析

## 1. 功能概述
（一段话描述该功能的作用和触发场景）

## 2. 状态机
（列出所有状态及转换条件，用表格或列表）

## 3. 报警/制动逻辑
（触发条件、取消条件、延时等）

## 4. 关键阈值
（距离、速度、TTC、角度等阈值参数，标注变量名和默认值）

## 5. 关键变量
| 变量名 | 类型 | 来源 | 含义 |
（列出影响该功能的所有关键变量）

## 6. 输入信号
（该功能依赖的输入信号列表）

## 7. 输出信号
（该功能输出的报警/制动信号列表）

## 8. 与其他功能的交互
（如RCTB依赖RCTA的状态等）
"""
        result = self.router.complex(prompt, system=SYSTEM_PROMPT)
        return result.get("content", f"# {func_name}\n\nAnalysis failed.")

    def _extract_relevant_code(self, func_name: str, file_contents: dict) -> str:
        """Extract code sections relevant to a specific function using regex matching."""
        import re

        keywords_map = {
            "BSD": ["bsd", "BSD", r"bLeft\w*Bsd", r"bRight\w*Bsd", "bsdSystemState"],
            "LCA": ["lca", "LCA", r"bLeft\w*Lca", r"bRight\w*Lca", "lcaSystemState"],
            "DOW": ["dow", "DOW", r"bLeft\w*Dow", r"bRight\w*Dow", "dowSystemState"],
            "RCW": ["rcw", "RCW", "bRcw", "rcwSystemState", "RCW_TTC", "RCW_DELAY"],
            "RCTA": ["rcta", "RCTA", r"bLeft\w*Rcta", r"bRight\w*Rcta", "rctaSystemState"],
            "RCTB": ["rctb", "RCTB", "Rctb", "rctbSystemState",
                     "RCTB_FUNC_GAP", "RctbBrake", "RSDS_Brkg", "RSDS_RCTABrk"],
            "FCTA": ["fcta", "FCTA", r"bLeft\w*Fcta", r"bRight\w*Fcta", "fctaSystemState"],
            "FCTB": ["fctb", "FCTB", "Fctb", "fctbSystemState",
                     "FCTB_FUNC_GAP", "FctbBrake", "CR_BrkgReq", "CR_FCTB"],
        }
        keywords = keywords_map.get(func_name, [func_name.lower()])
        compiled = [re.compile(kw, re.IGNORECASE) for kw in keywords]

        sections = []
        for file_path, content in file_contents.items():
            lines = content.split("\n")
            relevant_ranges = []
            for i, line in enumerate(lines):
                if any(pat.search(line) for pat in compiled):
                    start = max(0, i - 10)
                    end = min(len(lines), i + 30)
                    relevant_ranges.append((start, end))

            if relevant_ranges:
                merged = self._merge_ranges(relevant_ranges)
                for start, end in merged:
                    snippet = "\n".join(lines[start:end])
                    sections.append(f"### File: {file_path} (lines {start+1}-{end})\n```c\n{snippet}\n```")

        if not sections:
            return "(No relevant code found for this function)"

        combined = "\n\n".join(sections)
        if len(combined) > 30000:
            combined = combined[:30000] + "\n\n// ... [TRUNCATED for context limit] ..."
        return combined

    @staticmethod
    def _merge_ranges(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
        """Merge overlapping line ranges."""
        if not ranges:
            return []
        sorted_ranges = sorted(ranges)
        merged = [sorted_ranges[0]]
        for start, end in sorted_ranges[1:]:
            if start <= merged[-1][1] + 5:  # Allow small gap
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))
        return merged
