# -*- coding: utf-8 -*-
"""
Gen6 Symmetry Adapter — 适配 GAC/BYD CR60Light Symmetry 架构。

这是现有 code_learner / condition_extractor / signal_mapper 中硬编码的
Gen6 特定逻辑（adasFunc.c, RteComMapping.c, paraDefine.h 等）提取
到统一接口之后的实现。
"""
from __future__ import annotations

import json
import re
import hashlib
from pathlib import Path
from typing import Optional

from .base import (
    BaseCodeLearnerAdapter,
    BaseConditionExtractorAdapter,
    BaseSignalMapperAdapter,
)
from .factory import register_code_learner, register_condition_extractor, register_signal_mapper


# ====================================================================
# Gen6 Constants (from code_learner.py)
# ====================================================================

_CONSTANTS_SOURCE_FILES: list[str] = [
    r"adas\symmetry\perception\include\paraDefine.h",
    r"coem\GWM_B26\components\AswPerception\calib\dotCalibDefine.h",
    r"adas\symmetry\perception\include\globalVarDefine.h",
    r"adas\symmetry\perception\include\perception_public_def.h",
    r"coem\GWM_B26\components\AswPerception\func\adasFunc.c",
]

FOCUS_FILES_GEN6: dict[str, list[str]] = {
    "alarm_logic": [
        r"coem\GWM_B26\components\AswPerception\func\adasFunc.c",
        r"coem\GWM_B26\components\AswPerception\func\adasFunc.h",
        r"adas\symmetry\perception\include\paraDefine.h",
    ],
    "calculation_chain": [
        r"coem\GWM_B26\components\AswPerception\func\adasFunc.c",
        r"adas\symmetry\perception\src\objAttribCal.c",
        r"adas\symmetry\perception\src\postProcess.c",
        r"adas\symmetry\perception\src\track.c",
        r"adas\symmetry\perception\include\paraDefine.h",
        r"adas\symmetry\perception\include\structDefine.h",
    ],
    "output_chain": [
        r"coem\GWM_B26\components\AswPerception\func\adasFunc.c",
        r"coem\GWM_B26\components\AswIf\ASW_OUT\ASWOUT_OutCalc.c",
        r"coem\GWM_B26\components\AswIf\ASW_IN\RteComMapping.c",
    ],
    "state_machine": [
        r"coem\GWM_B26\components\AswPerception\func\adasFunc.c",
        r"coem\GWM_B26\components\AswIf\ASW_IN\ASWIN_SystemState.c",
        r"coem\GWM_B26\components\AswIf\ASW_IN\ASWIN_SystemState.h",
    ],
}

FUNC_KEYWORDS_GEN6: dict[str, list[str]] = {
    "BSD":  ["bsd", "Bsd", "BSD", "bLeftBsd", "bRightBsd", "bsdSystemState", "BSD_LCA_warning"],
    "LCA":  ["lca", "Lca", "LCA", "bLeftLca", "bRightLca", "lcaSystemState"],
    "DOW":  ["dow", "Dow", "DOW", "bLeftDow", "bRightDow", "dowSystemState", "DOW_warning"],
    "RCW":  ["rcw", "Rcw", "RCW", "bRcw", "rcwSystemState", "RSDS_RCW"],
    "RCTA": ["rcta", "Rcta", "RCTA", "bLeftRcta", "bRightRcta", "rctaSystemState", "RCTA_warning"],
    "RCTB": ["rctb", "Rctb", "RCTB", "rctbSystemState", "RctbBrake",
             "RSDS_Brkg", "RSDS_RCTABrk", "RCTB_FUNC_GAP"],
    "FCTA": ["fcta", "Fcta", "FCTA", "bLeftFcta", "bRightFcta", "fctaSystemState", "FCTA_Warn"],
    "FCTB": ["fctb", "Fctb", "FCTB", "fctbSystemState", "FctbBrake", "FctbKeepBrake",
             "CR_BrkgReq", "FCTB_FUNC_GAP", "FctbDetect", "FctbUpdateSystemStatus"],
}

_FUNC_OUTPUT_SIGNALS_GEN6: dict[str, list[str]] = {
    "FCTB": ["CR_BrkgReq", "CR_BrkgReqVal", "FCTBTrig", "FCTA_Warn", "FCTA_B_FuncSts",
             "CR_FCTB_Resp", "CR_FCTA_Resp", "CR_ErrSts"],
    "FCTA": ["FCTA_Warn", "FCTA_B_FuncSts", "CR_FCTA_Resp", "CR_FCTB_Resp",
             "CR_ErrSts", "CR_BliSts"],
    "RCTB": ["RSDS_BrkgReq", "RSDS_BrkgReqVal", "RSDS_BrkgTrig", "RCTB_State",
             "RSDS_RCTABrkResp", "RCTA_warningReqRight", "RCTA_warningReqLeft",
             "RSDS_ErrSts"],
    "RCTA": ["RCTA_warningReqRight", "RCTA_warningReqLeft", "RCTA_State", "RCTA_B_TTC",
             "RSDS_RCTAResp", "RSDS_CTA_Actv", "RSDS_RCTABrkResp", "RSDS_ErrSts"],
    "BSD":  ["BSD_LCA_warningReqRight", "BSD_LCA_warningReqleft", "BSD_State", "RSDS_ErrSts"],
    "LCA":  ["BSD_LCA_warningReqRight", "BSD_LCA_warningReqleft", "LCA_State", "RSDS_ErrSts"],
    "DOW":  ["DOW_warningReqRight", "DOW_warningReqleft", "DOW_State", "RSDS_ErrSts"],
    "RCW":  ["RSDS_RCW_Trigger", "RCW_State", "RSDS_RCWResp", "RCW_TTC", "RSDS_ErrSts"],
}


# ====================================================================
# Gen6 Prompt Templates (from code_learner.py / condition_extractor.py)
# ====================================================================

_CONSTANTS_SYSTEM_PROMPT = """你是汽车 ADAS 源码的**数值常量抽取专家**。
你的唯一任务：从给定的 C 源码中**把所有能确定数值的常量解析出来**，
并把带符号变量的推导式**代入数值**得到最终数字。

严格要求：
1. 只抽**数值**常量 —— 忽略布尔宏、字符串宏、无值的 enum、类型定义
2. 对 `#define A 1.976f` 这种直接赋值 → 输出 `value=1.976`
3. 对 `float LineBSDLCAL = -3.3f - (float)EGOCARWIDTH/2.0f;` 这种派生式：
   - 在 `vehicle_config` 中找到 `EGOCARWIDTH` 的数值
   - **自己计算**出 `computed_value`（如 -4.288）
   - 把原始式放到 `formula` 字段，不要省略
4. 严格输出 JSON，不要带任何解释文字；禁止 Markdown 代码块包裹"""

_CONSTANTS_USER_PROMPT = """请把下列源码中的所有**数值**常量抽取成 JSON。

源码片段（含 `#define` 和 `float LineXxx = ...` 等全局变量赋值）：
{snippets}

输出格式（严格 JSON，不要 ``` 包裹）：
{{
  "vehicle_config": {{"EGOCARWIDTH": {{"value": 1.976, "unit": "m", "description": "自车宽度"}}}},
  "function_thresholds": {{"fLcaObjWarningTTC": {{"value": 4.0, "unit": "s", "used_by": ["LCA"], "role": "LCA 预警 TTC 阈值"}}}},
  "roi_derived": {{"LineBSDLCAL": {{"formula": "-3.3 - EGOCARWIDTH/2", "computed_value": -4.288, "unit": "m", "used_by": ["BSD", "LCA"], "description": "LCA/BSD 左侧横向 ROI 边界"}}}}
}}

分类规则:
- `vehicle_config`: 基础物理常量 (Width, DistanceRear, etc.)
- `function_thresholds`: 带 f 前缀的按功能命名单值阈值
- `roi_derived`: 用 vehicle_config 推导出的 ROI 边界数值
"""

_OVERVIEW_SYSTEM_PROMPT = """你是一名资深的汽车ADAS软件工程师，专门分析角雷达（Corner Radar）的功能代码。
你需要分析C语言源码，提取以下信息：
1. **功能状态机**: 状态定义（None/Init/Standby/Active/Off/Failure/Passive）、状态转换条件
2. **关键阈值**: 距离、速度、TTC、角度等判断阈值
3. **报警逻辑**: 触发报警和取消报警的条件
4. **关键变量**: 影响功能行为的核心变量，标注其类型和来源
5. **输入输出**: 功能接收的输入信号和输出的报警/制动请求
关注的功能: BSD, LCA, DOW, RCW, RCTA, RCTB, FCTA, FCTB
输出使用中文，技术术语保留英文。"""

_OVERVIEW_PROMPT = """请分析角雷达中 **{func}** 功能的完整逻辑。

以下是相关的源码片段：

{snippets}

请输出以下结构的Markdown文档：

# {func} 功能分析

## 1. 功能概述
## 2. 状态机
## 3. 报警/制动逻辑
## 4. 关键阈值
## 5. 关键变量
## 6. 输入信号
## 7. 输出信号
## 8. 与其他功能的交互
"""

_FOCUS_PROMPTS_GEN6: dict[str, tuple[str, str]] = {
    "alarm_logic": (
        "你是汽车 ADAS 资深工程师，精于从 C 源码中精确提取报警/制动触发与退出逻辑。",
        """请提取 **{func}** 功能的**报警/制动逻辑**细节。聚焦：
1. **触发条件**（多个 if 条件组合，逐条列出 C 表达式）
2. **取消/退出条件**（含迟滞、延时、保压计时器）
3. **外部抑制**（AEB/ESP 等通过什么变量如何抑制本功能）

已知源码片段：
{snippets}

请输出 JSON（每条 item 的 id 使用 `trig-1`、`cancel-1` 等稳定命名）。""",
    ),
    "calculation_chain": (
        "你是汽车 ADAS 算法工程师，擅长追踪变量计算链路（从原始感知信号到最终判断量）。",
        """请提取 **{func}** 功能的**关键变量计算流程**。聚焦：
1. 每个关键变量是怎么算出来的（公式/依赖输入）
2. 计算数据链：**原始信号 → 中间变量 → 最终判断量**

已知源码片段：
{snippets}

请输出 JSON，包含 key_variables, derivation_chain, thresholds_used。""",
    ),
    "output_chain": (
        "你是汽车 ADAS 接口工程师，精通信号从内部变量到 CAN 总线的完整外发链路。",
        """请提取 **{func}** 功能的**外发链路**。聚焦：
1. 内部输出变量（如 `bFctbKeepBrakeFlg`）
2. 从内部变量 → ASWOUT_OutCalc 左右合并 → RteComMapping → CAN 信号
3. 下游消费者（ESP/VCU/HMI）
4. 外发条件门控

已知源码片段：
{snippets}

请输出 JSON，包含 outputs[], merge_strategy, external_gating[].""",
    ),
    "state_machine": (
        "你是汽车 ADAS 状态机专家，擅长整理状态定义、转换条件、entry/exit 动作与双状态机交互。",
        """请提取 **{func}** 功能的**状态机**细节。聚焦：
1. 状态定义（0-None, 1-Init, 2-Standby, 3-Active, 4-Off, 5-Failure, 6-Passive）
2. 所有状态转换的条件与动作（entry/exit 动作）
3. 双状态机交互：adasFunc（感知侧）vs ASWIN_SystemState（平台侧）

已知源码片段：
{snippets}

请输出 JSON，包含 states{}, transitions[], entry_functions[], dual_state_interaction[].""",
    ),
}

_EXTRACT_CONDITION_PROMPT_GEN6 = """你是嵌入式 ADAS 代码分析专家。请从以下源码中精确提取 **{func_name}** 功能的所有激活条件。

## 源码

{source_code}

---

请严格输出以下 JSON 结构（不要输出任何其他文字）:

```json
{{
  "function": "{func_name}",
  "system_state": {{
    "state_values": {{"0": "None", "1": "Init", "2": "Standby", "3": "Active", "4": "Off", "5": "Failure", "6": "Passive"}},
    "transitions": [{{"from": "2", "to": "3", "conditions": [{{"condition": "描述", "variable": "变量名", "threshold": "阈值"}}]}}]
  }},
  "target_filter": {{"skip_function": "", "conditions": []}},
  "detect_enable": {{"flag": "", "conditions": []}},
  "ego_speed_ranges": {{"active": {{"low": "", "high": "", "unit": "km/h"}}, "deactive": {{"low": "", "high": "", "unit": "km/h"}}}},
  "target_speed_ranges": {{"warning_enter": {{"low": "", "high": "", "unit": "km/h"}}, "warning_exit": {{"low": "", "high": "", "unit": "km/h"}}}},
  "external_suppression": [
    {{"source_system": "AEB/ESP/ACC/驾驶员/其他", "condition": "抑制条件描述", "variable": "C变量名", "can_signal": "CAN信号名", "suppression_trigger": "== 0 / != 0 / > 80", "normal_value": "!", "effect": "抑制"}}
  ],
  "other_conditions": []
}}
```

要求:
1. 所有阈值必须给出具体数值
2. 变量名必须与代码完全一致
3. external_suppression 必须包含 AEB/ESP/ACC/TCS/车门/档位 等所有外部抑制
4. suppression_trigger 必须严格按照 if 语句判定条件填写"""


# ====================================================================
# Condition Output Formatting (from condition_extractor.py)
# ====================================================================


def _format_conditions_gen6(conditions: dict) -> str:
    if not conditions or "error" in conditions:
        return f"(条件提取失败: {conditions.get('error', '?')})"
    parts = []
    func = conditions.get("function", "?")
    parts.append(f"### {func} 激活条件")
    spd = conditions.get("ego_speed_ranges", {})
    if spd:
        parts.append("\n**自车速度范围:**")
        for mode, vals in spd.items():
            if isinstance(vals, dict):
                parts.append(f"  {mode}: [{vals.get('low','?')}, {vals.get('high','?')}] {vals.get('unit','')}")
    tspd = conditions.get("target_speed_ranges", {})
    if tspd:
        parts.append("\n**目标速度范围:**")
        for mode, vals in tspd.items():
            if isinstance(vals, dict):
                parts.append(f"  {mode}: ({vals.get('low','?')}, {vals.get('high','?')}) {vals.get('unit','')}")
    st = conditions.get("system_state", {})
    transitions = st.get("transitions", [])
    if transitions:
        parts.append("\n**状态转移条件:**")
        for tr in transitions:
            parts.append(f"  {tr.get('from','?')} → {tr.get('to','?')}:")
            for c in tr.get("conditions", []):
                parts.append(f"    - {c.get('condition','')} [{c.get('variable','')}={c.get('threshold','')}]")
    tf = conditions.get("target_filter", {})
    tf_conds = tf.get("conditions", [])
    if tf_conds:
        parts.append(f"\n**目标过滤 ({tf.get('skip_function','?')}):**")
        for c in tf_conds:
            parts.append(f"  - {c.get('condition','')} [{c.get('variable','')}={c.get('threshold','')}] ({c.get('note','')})")
    de = conditions.get("detect_enable", {})
    de_conds = de.get("conditions", [])
    if de_conds:
        parts.append(f"\n**检测使能 ({de.get('flag','?')}):**")
        for c in de_conds:
            parts.append(f"  - {c.get('condition','')} [{c.get('variable','')}={c.get('threshold','')}]")
    es = conditions.get("external_suppression", [])
    if es:
        parts.append("\n**★ 外部抑制条件(必查) ★:**")
        for s in es:
            src = s.get("source_system", "?")
            cond = s.get("condition", "?")
            var = s.get("variable", "?")
            can = s.get("can_signal", "")
            eff = s.get("effect", "抑制")
            thr = s.get("suppression_trigger") or s.get("threshold", "?")
            normal = s.get("normal_value", "")
            can_info = f" CAN={can}" if can else ""
            normal_info = f", 正常值={normal}" if normal else ""
            parts.append(f"  - [{src}] {cond} [{var}: 抑制当{thr}{normal_info}]{can_info} → {eff}")
    return "\n".join(parts)


# ====================================================================
# Gen6 Signal Mapper Default Adapter
# ====================================================================


class _SignalMapperDefault(BaseSignalMapperAdapter):
    """Gen5 ReCo 平台没有 RteComMapping.c，此适配器返回空结果。

    Gen5 的信号映射需要新的方法：
      - 方案1: 从 DBC 文件提取（已知信号名已知）
      - 方案2: 从 DADDY channel 定义文件提取
      - 方案3: 从 MF4 信号名反向推断
    留作后续实现，当前对 Gen5 返回空映射。
    """

    def __init__(self, source_root: Path, output_dir: Path,
                 config: dict, project_root: Path):
        self.source_root = source_root
        self.output_dir = output_dir
        self.config = config

    def extract_signal_mapping(self, source_root: Path,
                               output_dir: Path) -> dict:
        # Gen5 ReCo has no RteComMapping.c
        return {"mappings": [], "internal_to_can": {}, "can_to_internal": {}}

    def extract_output_mapping(self, source_root: Path,
                               output_dir: Path) -> dict:
        return {"mappings": [], "signal_to_expr": {}}

    def resolve_internal_to_can(self, var_name: str, mapping: dict,
                                extra: Optional[dict] = None) -> list[str]:
        return []

    def resolve_can_to_internal(self, can_signal: str,
                                mapping: dict) -> list[str]:
        return []

    def get_output_signals_for_function(self, func_name: str) -> list[str]:
        # Gen5 outputs are DADDY channels, not CAN signals directly.
        # Return placeholder map.
        return []


# ====================================================================
# Gen6 CodeLearner Adapter
# ====================================================================


@register_code_learner("gen6_c_radar")
@register_code_learner("gen5_cpp_radar")
class Gen6SymmetryCodeLearnerAdapter(BaseCodeLearnerAdapter):
    """适配 Gen6 Symmetry 和 Gen5 C++ 单体架构（使用相同的源码结构和 Prompt）。"""

    def __init__(self, source_root: Path, config: dict, project_root: Path):
        self.source_root = source_root
        self.config = config
        self.project_root = project_root
        self._variant_candidates: dict[str, str] | None = None

    def _variant_file_map(self) -> dict[str, str]:
        """Map basename -> existing variant file (basename-based redirect).

        The FOCUS file lists below are GWM_B26-era hardcoded paths. For other
        variants (BYD_UKE / BYD_SC6H / ...) the same logical files live under
        ``coem/<variant>``; we resolve them once by scanning the variant's
        key_source_files + source_domains and matching on file basename.
        """
        if self._variant_candidates is not None:
            return self._variant_candidates
        mapping: dict[str, str] = {}
        candidates: list[str] = []
        variants = (self.config or {}).get("variants", {})
        identity = (self.config or {}).get("identity", {})
        variant_id = identity.get("variant_id") if isinstance(identity, dict) else None
        if variant_id and variant_id in variants:
            variant = variants[variant_id]
            if isinstance(variant, dict):
                candidates.extend(variant.get("key_source_files", []) or [])
                domains = variant.get("source_domains", {}) or {}
                for files in domains.values():
                    candidates.extend(files or [])
        for rel in candidates:
            rel_posix = str(rel).replace("\\", "/")
            base = Path(rel_posix).name
            if base and base not in mapping:
                mapping[base] = rel_posix
        self._variant_candidates = mapping
        return mapping

    def _resolve_focus_file(self, rel: str) -> str:
        """Redirect a GWM-era focus path to the active variant's equivalent."""
        full = self.source_root / rel
        if full.exists():
            return rel
        base = Path(str(rel).replace("\\", "/")).name
        replacement = self._variant_file_map().get(base)
        if replacement and (self.source_root / replacement).exists():
            return replacement
        # Semantic aliases: same role, different name/path in some variants.
        aliases = {
            "ASWIN_SystemState.c": [
                "coem/BYD_UKE/components/AswIf/ASW_ADAS/ASWIN_AdasState.c",
            ],
            "ASWIN_SystemState.h": [
                "coem/BYD_UKE/components/AswIf/ASW_ADAS/ASWIN_AdasState.h",
            ],
            "paraDefine.h": [
                "build/inc/paraDefine.h",
                "coem/BYD_UKE/components/AswPerception/calib/dotCalibDefine.h",
            ],
            "dotCalibDefine.h": [
                "coem/BYD_UKE/components/AswPerception/calib/dotCalibDefine.h",
                "build/inc/dotCalibDefine.h",
            ],
            "RteComMapping.c": [
                "coem/BYD_UKE/components/AswIf/ASW_ComMapping/RteComMapping_Rx.c",
                "coem/BYD_UKE/components/AswIf/ASW_ComMapping/RteComMapping_Tx.c",
            ],
        }
        for candidate in aliases.get(base, []):
            if (self.source_root / candidate).exists():
                return candidate
        return rel

    def get_key_source_files(self) -> list[str]:
        return [
            self._resolve_focus_file(p) for p in (
                _CONSTANTS_SOURCE_FILES
                + [
                    r"adas\symmetry\perception\include\globalVarDefine.h",
                    r"coem\GWM_B26\components\AswPerception\calib\dotCalibDefine.h",
                    r"coem\GWM_B26\components\AswIf\ASW_OUT\ASWOUT_OutCalc.c",
                    r"coem\GWM_B26\components\AswIf\ASW_IN\RteComMapping.c",
                    r"coem\GWM_B26\components\AswIf\ASW_IN\ASWIN_SystemState.c",
                    r"coem\GWM_B26\components\AswIfSchedule\AswIfSchedule.c",
                ]
            )
        ]

    def get_focus_files(self, focus: str) -> list[str]:
        return [
            self._resolve_focus_file(p)
            for p in FOCUS_FILES_GEN6.get(focus, [])
        ]

    def get_source_domains(self) -> dict[str, list[str]]:
        return {
            "system_state": [
                r"coem\GWM_B26\components\AswIf\ASW_IN\ASWIN_SystemState.c",
                r"coem\GWM_B26\components\AswIf\ASW_IN\ASWIN_SystemState.h",
            ],
            "algorithm": [
                r"coem\GWM_B26\components\AswPerception\func\adasFunc.c",
                r"coem\GWM_B26\components\AswPerception\func\adasFunc.h",
                r"adas\symmetry\perception\include\paraDefine.h",
            ],
            "signal_chain": [
                r"coem\GWM_B26\components\AswIf\ASW_IN\RteComMapping.c",
            ],
            "perception": [
                r"adas\symmetry\perception\src\objAttribCal.c",
                r"adas\symmetry\perception\src\track.c",
                r"adas\symmetry\perception\src\postProcess.c",
            ],
            "output": [
                r"coem\GWM_B26\components\AswIf\ASW_OUT\ASWOUT_OutCalc.c",
            ],
        }

    def get_func_keywords(self, func: str) -> list[str]:
        return FUNC_KEYWORDS_GEN6.get(func, [func.lower(), func])

    def get_constants_source_files(self) -> list[str]:
        return _CONSTANTS_SOURCE_FILES

    def build_prompt_template(self, focus: str) -> dict[str, str]:
        system, template = _FOCUS_PROMPTS_GEN6.get(focus, (
            "你是汽车 ADAS 代码分析专家。",
            """请分析 **{func}** 源码片段：
{snippets}
输出结构化知识 JSON。""",
        ))
        return {"system": system, "user_template": template}

    def build_overview_prompt(self) -> tuple[str, str]:
        return _OVERVIEW_SYSTEM_PROMPT, _OVERVIEW_PROMPT

    def get_priority_functions(self) -> list[str]:
        return ["FCTB", "FCTA", "RCTB", "RCTA", "BSD", "LCA", "DOW", "RCW"]

    def get_focuses(self) -> list[str]:
        return ["alarm_logic", "calculation_chain", "output_chain", "state_machine"]


# ====================================================================
# Gen6 ConditionExtractor Adapter
# ====================================================================


@register_condition_extractor("gen6_c_radar")
@register_condition_extractor("gen5_cpp_radar")
class Gen6SymmetryConditionExtractorAdapter(BaseConditionExtractorAdapter):

    def __init__(self, source_root: Path, config: dict, project_root: Path):
        self.source_root = source_root

    def get_source_domains(self) -> dict[str, list[str]]:
        return {
            "system_state": [
                r"coem\GWM_B26\components\AswIf\ASW_IN\ASWIN_SystemState.c",
                r"coem\GWM_B26\components\AswIf\ASW_IN\ASWIN_SystemState.h",
            ],
            "algorithm": [
                r"coem\GWM_B26\components\AswPerception\func\adasFunc.c",
                r"coem\GWM_B26\components\AswPerception\func\adasFunc.h",
                r"adas\symmetry\perception\include\paraDefine.h",
            ],
            "signal_chain": [
                r"coem\GWM_B26\components\AswIf\ASW_IN\RteComMapping.c",
            ],
        }

    def get_extraction_prompt(self, func_name: str) -> tuple[str, str]:
        system = "你是嵌入式 ADAS 代码分析专家。"
        user = _EXTRACT_CONDITION_PROMPT_GEN6.format(
            func_name=func_name, source_code="{source_code}"
        )
        return system, user

    def get_func_keywords(self, func: str) -> list[str]:
        return FUNC_KEYWORDS_GEN6.get(func, [func.lower(), func])

    def format_conditions(self, conditions: dict) -> str:
        return _format_conditions_gen6(conditions)


# ====================================================================
# Gen6 SignalMapper Adapter (wraps existing signal_mapper module)
# ====================================================================


@register_signal_mapper("gen6_c_radar")
@register_signal_mapper("gen5_cpp_radar")
class Gen6SymmetrySignalMapperAdapter(BaseSignalMapperAdapter):
    """Gen5 ReCo 平台信号映射（占位，实际使用 SignalMapperDefault）。

    Gen6 Symmetry 的信号映射依赖 RteComMapping.c，这部分的逻辑
    保留了原有的 signal_mapper.py 模块中，此 adapter 只是包装器。
    """

    def __init__(self, source_root: Path, output_dir: Path,
                 config: dict, project_root: Path):
        self.source_root = source_root
        self.output_dir = output_dir
        self.config = config
        self._mapping_cache: Optional[dict] = None

    def _get_mapping(self) -> dict:
        if self._mapping_cache is not None:
            return self._mapping_cache
        from engines import signal_mapper
        self._mapping_cache = signal_mapper.extract_signal_mapping(
            self.source_root, self.output_dir
        )
        return self._mapping_cache

    def extract_signal_mapping(self, source_root: Path,
                               output_dir: Path) -> dict:
        from engines import signal_mapper
        return signal_mapper.extract_signal_mapping(source_root, output_dir)

    def extract_output_mapping(self, source_root: Path,
                               output_dir: Path) -> dict:
        from engines import signal_mapper
        return signal_mapper.extract_output_signal_mapping(source_root, output_dir)

    def resolve_internal_to_can(self, var_name: str, mapping: dict,
                                extra: Optional[dict] = None) -> list[str]:
        from engines import signal_mapper
        chains = extra.get("variable_chains") if extra else None
        output_mapping = extra.get("output_mapping") if extra else None
        return signal_mapper.resolve_internal_to_can(
            var_name, mapping, chains, output_mapping
        )

    def resolve_can_to_internal(self, can_signal: str,
                                mapping: dict) -> list[str]:
        from engines import signal_mapper
        return signal_mapper.resolve_can_to_internal(can_signal, mapping)

    def get_output_signals_for_function(self, func_name: str) -> list[str]:
        return _FUNC_OUTPUT_SIGNALS_GEN6.get(func_name.upper(), [])


# ====================================================================
# Gen5 ReCo Adapter (see gen5_reco_pl.py for implementation)
# ====================================================================

# Will be registered by gen5_reco_pl.py module
