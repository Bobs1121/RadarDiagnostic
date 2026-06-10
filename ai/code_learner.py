# -*- coding: utf-8 -*-
"""
CodeLearner: 代码学习引擎 — 项目中**唯一**负责"读源码、抽知识"的模块。

两个公共入口（对应两个互补的使用场景）：

  1. ``learn(pairs_budget=None)``
     增量式、结构化 JSON 学习。由 auto-dream Phase 0 调用。
     按"功能 × 焦点"二维网格轮转，结果写入 ``memory/code_knowledge/<FUNC>.json``。

  2. ``ensure_overview_docs(funcs=None)``
     一次性、人类可读 Markdown 概览。由 orchestrator 启动时调用（MD 缺失才跑）。
     结果写入 ``source_docs/<FUNC>.md``，供问题理解阶段作上下文素材。

四大学习焦点 (focus)，仅用于结构化 JSON 学习：
  - alarm_logic        报警触发/取消/退出条件、迟滞、延时、抑制
  - calculation_chain  关键变量计算流程（TTC/TTM/距离/速度/ROI 派生）
  - output_chain       外发链路（内部变量 → RteComMapping → CAN 信号 → 下游）
  - state_machine      状态流转、入口/出口动作、双状态机交互

核心机制：
  1. **Hash 缓存**：源码未变动则跳过已学 (func, focus) 对
  2. **焦点轮转**：按 learning_state.json 记录的游标推进
  3. **增量合并**：新条目按 id 去重，内容变更时新覆盖旧
  4. **冷启动自适应**：warmup_done=False 时自动学满首轮；热启动仅学 pairs_per_dream
"""
from __future__ import annotations

import datetime
import hashlib
import json
import re
from pathlib import Path
from typing import Callable, Optional

from .model_router import ModelRouter
from .utils import ALL_FUNCTIONS, parse_json_from_llm, extract_relevant_sections

# ── 常量 ────────────────────────────────────────────────────────────────

FOCUSES: list[str] = [
    "alarm_logic",
    "calculation_chain",
    "output_chain",
    "state_machine",
]

# ── Constants learning (global, cross-function) ─────────────────────────
# 常量学习是一个**全局**的、一次性的任务，不按 function × focus 轮转。
# 学一次结果写到 ``memory/code_knowledge/constants.json``，所有功能共享。
# 源头：paraDefine.h / dotCalibDefine.h / globalVarDefine.h /
# perception_public_def.h —— 这些文件里定义了自车宽度、ROI 横向边界等
# 真正的数值常量。Hash 未变 → 零 token 跳过；变了才重新学。
_CONSTANTS_SOURCE_FILES: list[str] = [
    r"adas\symmetry\perception\include\paraDefine.h",
    r"coem\GWM_B26\components\AswPerception\calib\dotCalibDefine.h",
    r"adas\symmetry\perception\include\globalVarDefine.h",
    r"adas\symmetry\perception\include\perception_public_def.h",
    r"coem\GWM_B26\components\AswPerception\func\adasFunc.c",
]

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
4. 如果源码里某个符号找不到数值定义（比如只是声明而没赋值）→ **不要瞎猜**
5. 对条件编译 `#ifdef`：选择看起来是"默认/主打"的分支（通常是 `#if 0` 外的那个），
   并在 `notes` 里标注"依赖编译开关 XXX"
6. 严格输出 JSON，不要带任何解释文字；禁止 Markdown 代码块包裹"""

_CONSTANTS_USER_PROMPT = """请把下列源码中的所有**数值**常量抽取成 JSON。

源码片段（含 `#define` 和 `float LineXxx = ...` 等全局变量赋值）：
{snippets}

输出格式（严格 JSON）：
{{
  "vehicle_config": {{
    "EGOCARWIDTH": {{
      "value": 1.976,
      "unit": "m",
      "description": "自车宽度",
      "source": "dotCalibDefine.h:8"
    }}
  }},
  "function_thresholds": {{
    "fLcaObjWarningTTC": {{
      "value": 4.0,
      "unit": "s",
      "used_by": ["LCA"],
      "role": "LCA 预警 TTC 阈值",
      "source": "adasFunc.c:157"
    }}
  }},
  "roi_derived": {{
    "LineBSDLCAL": {{
      "formula": "-3.3 - EGOCARWIDTH/2",
      "computed_value": -4.288,
      "unit": "m",
      "used_by": ["LCA", "BSD"],
      "description": "LCA/BSD 左侧横向 ROI 边界（近车道侧）",
      "source": "adasFunc.c:33"
    }},
    "LineLCAC": {{
      "formula": "-4.0 - DISTANCEREAR",
      "computed_value": -5.143,
      "unit": "m",
      "used_by": ["LCA"],
      "description": "LCA 纵向 ROI 近点（后保险杠后方）",
      "source": "adasFunc.c:18"
    }}
  }}
}}

重要提示：
- `vehicle_config`：**基础物理常量**（Width、DistanceRear、DistanceFront、DistanceDriver 等）
- `function_thresholds`：带 `f` 前缀的**按功能命名**的单值阈值（如 `fLcaObjWarningTTC`、`fFctbBrakeTime`）
- `roi_derived`：用 `vehicle_config` 推导出的**ROI 边界数值**（如 `LineBSDLCAL`、`LineDOWG`、`LineRCWC`）
  必须同时给 `formula`（原始 C 表达式）和 `computed_value`（**你自己算出的数字**）
- `used_by` 数组：根据命名前缀推断功能（Bsd→BSD, Lca→LCA, Dow→DOW, Rcw→RCW,
  Rcta→RCTA, Rctb→RCTB, Fcta→FCTA, Fctb→FCTB；`LineBSDLCAx` 类同时归 BSD 和 LCA）
- 如果某个类别没有内容，该字段给空对象 `{{}}`（不要省略 key）

请只输出 JSON（不要 ``` 包裹）。"""




# 每个焦点关心的源码文件（相对 source_root，顺序 = 权重）
FOCUS_FILES: dict[str, list[str]] = {
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

# ── 关键字表：用于从源码抽取某功能相关片段 ──────────────────────────────

FUNC_KEYWORDS: dict[str, list[str]] = {
    "BSD":  ["bsd", "Bsd", "BSD", "bLeftBsd", "bRightBsd", "bsdSystemState", "BSD_LCA_warning"],
    "LCA":  ["lca", "Lca", "LCA", "bLeftLca", "bRightLca", "lcaSystemState"],
    "DOW":  ["dow", "Dow", "DOW", "bLeftDow", "bRightDow", "dowSystemState", "DOW_warning"],
    "RCW":  ["rcw", "Rcw", "RCW", "bRcw", "rcwSystemState", "RSDS_RCW"],
    "RCTA": ["rcta", "Rcta", "RCTA", "bLeftRcta", "bRightRcta", "rctaSystemState", "RCTA_warning"],
    "RCTB": ["rctb", "Rctb", "RCTB", "rctbSystemState", "RctbBrake",
             "RSDS_Brkg", "RSDS_RCTABrk", "RCTB_FUNC_GAP"],
    "FCTA": ["fcta", "Fcta", "FCTA", "bLeftFcta", "bRightFcta", "fctaSystemState", "FCTA_Warn"],
    "FCTB": ["fctb", "Fctb", "FCTB", "fctbSystemState", "FctbBrake", "FctbKeepBrake",
             "CR_BrkgReq", "FCTB_FUNC_GAP", "FctbDetect"],
}


# ── Overview 生成（Markdown 概览，替代原 CodeAnalyzer） ─────────────────

_OVERVIEW_SYSTEM_PROMPT = """你是一名资深的汽车ADAS软件工程师，专门分析角雷达（Corner Radar）的功能代码。
你需要分析C语言源码，提取以下信息：

1. **功能状态机**: 状态定义（None/Init/Standby/Active/Off/Failure/Passive）、状态转换条件
2. **关键阈值**: 距离、速度、TTC、角度等判断阈值
3. **报警逻辑**: 触发报警和取消报警的条件
4. **关键变量**: 影响功能行为的核心变量，标注其类型和来源
5. **输入输出**: 功能接收的输入信号和输出的报警/制动请求

关注的功能: BSD(盲区检测), LCA(变道辅助), DOW(开门预警), RCW(后方碰撞预警),
RCTA(后方交叉交通警报), RCTB(后方交叉交通制动), FCTA(前方交叉交通警报), FCTB(前方交叉交通制动)

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
| 变量名 | 类型 | 来源 | 含义 |
## 6. 输入信号
## 7. 输出信号
## 8. 与其他功能的交互
"""


# ── 每个焦点的学习 Prompt 模板 ──────────────────────────────────────────

_FOCUS_PROMPT_TEMPLATES: dict[str, str] = {
    "alarm_logic": """\
请提取 **{func}** 功能的**报警/制动逻辑**细节。聚焦：
1. **触发条件**（多个 if 条件组合，逐条列出 C 表达式）
2. **取消/退出条件**（含迟滞、延时、保压计时器）
3. **外部抑制**（AEB/ESP 等通过什么变量如何抑制本功能）

已知源码片段：
{snippets}

请输出以下 JSON（每条 item 的 id 使用 `trig-1`、`cancel-1` 等稳定命名）：
{{
  "trigger_conditions": [
    {{
      "id": "trig-1",
      "description": "简明描述该触发条件在什么场景下触发",
      "c_expression": "对应的 C 代码表达式（尽量原样复制）",
      "variables": ["involved_var_1", "involved_var_2"],
      "thresholds": {{"threshold_name": "默认值 + 单位"}},
      "code_ref": {{"file": "adasFunc.c", "line": 6200, "function": "FctbUpdateSystemStatus"}},
      "confidence": 0.9
    }}
  ],
  "cancel_conditions": [...],
  "exit_conditions": [...],
  "hysteresis": [
    {{"name": "TTMX 迟滞", "enter": "X 阈值", "exit": "X+offset 阈值", "purpose": "..."}}
  ],
  "timers": [
    {{"name": "fFctbBrakeEventTime", "duration": "3.0s", "purpose": "制动保压时间"}}
  ],
  "suppression": [
    {{"suppressor": "AEBBAActv", "how": "为 1 时抑制 FCTB 制动输出", "code_ref": {{...}}}}
  ]
}}""",

    "calculation_chain": """\
请提取 **{func}** 功能的**关键变量计算流程**。聚焦：
1. 每个关键变量是怎么算出来的（公式/依赖输入）
2. 计算数据链：**原始信号 → 中间变量 → 最终判断量**
3. 计算中使用到的阈值/参数

已知源码片段：
{snippets}

请输出以下 JSON：
{{
  "key_variables": {{
    "fFctbTTMX": {{
      "description": "FCTB X 轴碰撞时间",
      "formula": "distXRefer / velX（有符号保护）",
      "inputs": ["objOutStruct[i].distXRefer", "objOutStruct[i].velX"],
      "data_source": "感知层 objOutStruct（来自 postProcess）",
      "output_usage": "与 fFctbObjWarningBaseTTMX 比较触发报警",
      "code_ref": {{"file": "adasFunc.c", "line": 5830, "function": "FctbCheckTargets"}},
      "confidence": 0.9
    }}
  }},
  "derivation_chain": [
    {{
      "step": 1,
      "from": "radar_targets (postProcess 输出)",
      "to": "objOutStruct[i].distXRefer/velX/velY",
      "in_file": "postProcess.c",
      "transform": "滤波+坐标变换"
    }},
    {{
      "step": 2,
      "from": "objOutStruct",
      "to": "fFctbTTMX/fFctbTTMY",
      "in_file": "adasFunc.c",
      "transform": "除法得到 Time-To-Merge"
    }}
  ],
  "thresholds_used": [
    {{"name": "fFctbObjWarningBaseTTMX", "value": "1.0s", "role": "警告基础阈值"}}
  ]
}}""",

    "output_chain": """\
请提取 **{func}** 功能的**外发链路**（功能输出如何写到 CAN 总线）。聚焦：
1. 内部输出变量（如 `bFctbKeepBrakeFlg`）
2. 从内部变量 → ASWOUT_OutCalc 左右合并 → RteComMapping 的 WriteSignal → CAN 信号
3. 下游消费者（ESP/VCU/HMI/…）
4. 外发条件门控（功能 Active 才外发？状态机特定值才外发？）

已知源码片段：
{snippets}

请输出以下 JSON：
{{
  "outputs": [
    {{
      "id": "out-1",
      "internal_var": "bFctbKeepBrakeFlg",
      "description": "FCTB 保持制动请求标志",
      "set_location": {{"file": "adasFunc.c", "line": 6400, "function": "FctbUpdateBrake"}},
      "merge_logic": "ASWOUT_OutCalc.c 对左右雷达取 max",
      "merge_location": {{"file": "ASWOUT_OutCalc.c", "line": 123}},
      "can_signal": "CR_BrkgReq",
      "rte_write_location": {{"file": "RteComMapping.c", "line": 1234}},
      "transform": "uint8 透传 / 布尔 *1",
      "message_id": "0x??? (若源码可见)",
      "downstream": ["ESP (制动)", "仪表 HMI"],
      "gating_conditions": ["fctbSystemState == 3 (Active)", "无 AEB 抑制"]
    }}
  ],
  "merge_strategy": "描述左右雷达合并策略（max / or / 优先级 / 时间窗）",
  "external_gating": [
    {{"source": "AEBBAActv_0x137", "effect": "为 1 时 CR_BrkgReq 被抑制"}}
  ]
}}""",

    "state_machine": """\
请提取 **{func}** 功能的**状态机**细节。聚焦：
1. 状态定义（0-None, 1-Init, 2-Standby, 3-Active, 4-Off, 5-Failure, 6-Passive）
2. 所有状态转换的条件与动作（entry/exit 动作）
3. 双状态机交互：adasFunc.c（感知侧）vs ASWIN_SystemState.c（平台侧）共享的 `fctbSystemState` 等变量
4. 状态机入口函数调用链

已知源码片段：
{snippets}

请输出以下 JSON：
{{
  "states": {{
    "0": {{"name": "None", "meaning": "未初始化", "typical_entry": "上电"}},
    "2": {{"name": "Standby", "meaning": "待机", "typical_entry": "使能且车速在范围"}}
  }},
  "transitions": [
    {{
      "id": "tr-1",
      "from": 2,
      "to": 3,
      "condition": "bFCTBEnable && vehSpd in [0.5, 21.0] && !failure",
      "action": "清空保压计时器；设置 fctbSystemState=3",
      "code_ref": {{"file": "adasFunc.c", "line": 6150}},
      "confidence": 0.9
    }}
  ],
  "entry_functions": [
    {{"name": "FctbUpdateSystemStatus", "file": "adasFunc.c", "line": 6100, "caller": "AdasFunctionCalc"}}
  ],
  "dual_state_interaction": [
    {{
      "aspect": "共享变量",
      "description": "fctbSystemState 同时被 adasFunc 与 ASWIN_SystemState 写入，调度顺序决定最终值",
      "risk": "两者在同帧内不一致可能导致状态震荡"
    }}
  ]
}}""",
}


_FOCUS_SYSTEMS: dict[str, str] = {
    "alarm_logic": "你是汽车 ADAS 资深工程师，精于从 C 源码中精确提取报警/制动触发与退出逻辑。",
    "calculation_chain": "你是汽车 ADAS 算法工程师，擅长追踪变量计算链路（从原始感知信号到最终判断量）。",
    "output_chain": "你是汽车 ADAS 接口工程师，精通信号从内部变量到 CAN 总线的完整外发链路。",
    "state_machine": "你是汽车 ADAS 状态机专家，擅长整理状态定义、转换条件、entry/exit 动作与双状态机交互。",
}


# ── CodeLearner ─────────────────────────────────────────────────────────

class CodeLearner:
    """代码学习引擎 — 项目唯一的"读源码 + 抽知识"入口。

    公共 API:
      - ``learn()``                 增量 JSON 学习（auto-dream 调用）
      - ``ensure_overview_docs()``  生成 MD 概览（orchestrator 启动时调用）
    """

    def __init__(self, router: ModelRouter, config: dict, project_root: Path):
        from config import resolve_source_docs_dir
        self.router = router
        self.config = config
        self.project_root = project_root

        ad_cfg = (config.get("auto_dream") or {}).get("code_learning", {}) or {}
        self.enabled: bool = bool(ad_cfg.get("enabled", True))
        self.warmup_pairs: int = int(ad_cfg.get("warmup_pairs", 8))
        self.pairs_per_dream: int = int(ad_cfg.get("pairs_per_dream", 2))
        self.rotation_focuses: list[str] = list(
            ad_cfg.get("rotation_focuses", FOCUSES)
        )
        self.priority_functions: list[str] = list(
            ad_cfg.get("priority_functions",
                       ["FCTB", "FCTA", "RCTB", "RCTA", "BSD", "LCA", "DOW", "RCW"])
        )
        self.max_snippet_chars: int = int(ad_cfg.get("max_snippet_chars", 40000))
        self.use_thinking: bool = bool(ad_cfg.get("use_thinking", False))

        self.source_root = Path(config["paths"]["source_code"])
        self.key_source_files: list[str] = list(
            config.get("paths", {}).get("key_source_files", [])
        )
        # Per-project knowledge dir (falls back to legacy global for backward compat)
        proj = config.get("project", {})
        memory_dir = proj.get("memory_dir", project_root / "memory")
        self.knowledge_dir = Path(memory_dir) / "code_knowledge"
        self.knowledge_dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.knowledge_dir / "learning_state.json"
        self.overview_dir = resolve_source_docs_dir(config, project_root)
        self.overview_dir.mkdir(parents=True, exist_ok=True)

    # ── Public API ──────────────────────────────────────────────────────

    def learn(
        self,
        status_cb: Optional[Callable[[str, str], None]] = None,
        force_pairs: Optional[int] = None,
        force_constants: bool = False,
    ) -> dict:
        """执行一次代码学习。

        Args:
            status_cb: 进度回调 (step, detail)
            force_pairs: 强制学习的对数（覆盖 warmup/pairs_per_dream）
            force_constants: 强制重新学习数值常量（忽略 hash 短路）

        Returns:
            delta 摘要 dict
        """
        def status(msg: str) -> None:
            if status_cb:
                status_cb("code_learning", msg)

        if not self.enabled:
            status("代码学习已禁用 (auto_dream.code_learning.enabled=false)")
            return {"skipped": True, "reason": "disabled"}

        if not self.source_root.exists():
            status(f"源码路径不存在: {self.source_root}")
            return {"skipped": True, "reason": "source_root_missing"}

        state = self._read_state()

        constants_delta = self._learn_constants_if_needed(status, force=force_constants)

        is_warmup = state.get("warmup_done", False) is False
        pair_budget = force_pairs if force_pairs is not None else (
            self.warmup_pairs if is_warmup else self.pairs_per_dream
        )

        status(f"本次预算 {pair_budget} 对；冷启动={is_warmup}")

        # 生成所有 (func, focus) 组合的轮转序列
        all_pairs = [
            (fn, fc)
            for fc in self.rotation_focuses
            for fn in self.priority_functions
        ]
        cursor = int(state.get("cursor", 0))

        learned: list[dict] = []
        skipped: list[dict] = []
        errors: list[dict] = []

        attempts = 0
        max_attempts = pair_budget * 3  # 允许最多跳过 2/3 的对
        while len(learned) < pair_budget and attempts < max_attempts:
            func, focus = all_pairs[cursor % len(all_pairs)]
            cursor = (cursor + 1) % len(all_pairs)
            attempts += 1

            try:
                res = self._learn_one(func, focus, state, status)
            except Exception as e:  # noqa: BLE001
                errors.append({"func": func, "focus": focus, "error": str(e)[:300]})
                status(f"[{func}/{focus}] 失败: {e}")
                continue

            if res.get("skipped"):
                skipped.append({
                    "func": func, "focus": focus,
                    "reason": res.get("reason", ""),
                })
                # hash 未变跳过，不消耗 budget
                continue

            learned.append({
                "func": func,
                "focus": focus,
                "items_added": res.get("items_added", 0),
                "items_updated": res.get("items_updated", 0),
            })
            status(
                f"[{func}/{focus}] 新增 {res.get('items_added', 0)} 条 / "
                f"更新 {res.get('items_updated', 0)} 条"
            )

        # 更新游标
        state["cursor"] = cursor
        if is_warmup and len(learned) >= min(pair_budget, len(all_pairs)):
            # 若实际学到的数量 ≥ warmup 预算，标记 warmup 完成
            state["warmup_done"] = True
        state["last_learn_at"] = datetime.datetime.now().isoformat()
        state["total_learned_pairs"] = int(state.get("total_learned_pairs", 0)) + len(learned)
        self._write_state(state)

        return {
            "learned_count": len(learned),
            "skipped_count": len(skipped),
            "error_count": len(errors),
            "learned": learned,
            "skipped": skipped,
            "errors": errors,
            "warmup_done": state.get("warmup_done", False),
            "cursor": cursor,
            "constants": constants_delta,
        }

    def ensure_overview_docs(
        self,
        funcs: Optional[list[str]] = None,
        force: bool = False,
        status_cb: Optional[Callable[[str, str], None]] = None,
    ) -> dict:
        """确保 ``source_docs/<FUNC>.md`` 与源码**同步**。

        更新策略（per-function hash 驱动）：
          - 为每个功能计算 *其相关片段* 的 hash（基于 FUNC_KEYWORDS 抽取的 snippets）
          - hash 与 ``source_docs/.overview_hashes.json`` 记录不一致 → 重生成 MD
          - MD 文件缺失 → 生成
          - hash 一致且 MD 存在 → 跳过

        这样 FCTA 源码改动只会刷新 FCTA.md，不会误触发其他功能。

        Args:
            funcs: 要确保的功能列表；None 表示使用 ALL_FUNCTIONS。
            force: True 时无论 hash 是否一致都重新生成。
            status_cb: 进度回调 (step, detail)。
        """
        def status(msg: str) -> None:
            if status_cb:
                status_cb("overview", msg)

        targets = [f.upper() for f in (funcs or ALL_FUNCTIONS)]

        if not self.source_root.exists():
            status(f"源码路径不存在: {self.source_root}")
            return {"generated": [], "skipped": targets, "reason": "source_root_missing"}

        file_contents = self._read_key_source_files()
        if not file_contents:
            return {"generated": [], "skipped": targets, "reason": "no_source_files"}

        hash_store = self._read_overview_hashes()

        need_update: list[tuple[str, str, str]] = []  # (func, snippets, new_hash)
        skipped: list[str] = []
        for func in targets:
            keywords = FUNC_KEYWORDS.get(func, [func.lower(), func])
            snippets = self._extract_snippets(file_contents, keywords)
            new_hash = hashlib.sha256(snippets.encode("utf-8", "ignore")).hexdigest()[:16]
            md_path = self.overview_dir / f"{func}.md"

            if not force and md_path.exists() and hash_store.get(func) == new_hash:
                skipped.append(func)
                continue

            reason = "missing" if not md_path.exists() else (
                "forced" if force else "source_changed"
            )
            status(f"{func}: will regenerate ({reason})")
            need_update.append((func, snippets, new_hash))

        if not need_update:
            return {"generated": [], "skipped": skipped, "reason": "all_up_to_date"}

        generated: list[str] = []
        failed: list[dict] = []
        for func, snippets, new_hash in need_update:
            try:
                status(f"Generating overview for {func}...")
                md = self._generate_overview_from_snippets(func, snippets)
                (self.overview_dir / f"{func}.md").write_text(md, encoding="utf-8")
                hash_store[func] = new_hash
                generated.append(func)
            except Exception as e:  # noqa: BLE001
                failed.append({"func": func, "error": str(e)[:200]})
                status(f"[WARN] {func} failed: {e}")

        hash_store["_updated_at"] = datetime.datetime.now().isoformat()
        self._write_overview_hashes(hash_store)

        return {
            "generated": generated,
            "failed": failed,
            "skipped": skipped,
        }

    def _read_overview_hashes(self) -> dict:
        """读取 source_docs/.overview_hashes.json，记录每个功能的 snippets hash。"""
        path = self.overview_dir / ".overview_hashes.json"
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def _write_overview_hashes(self, data: dict) -> None:
        path = self.overview_dir / ".overview_hashes.json"
        try:
            path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError:
            pass

    # ── Overview 生成 ───────────────────────────────────────────────────

    def _read_key_source_files(self) -> dict[str, str]:
        """读取 config.paths.key_source_files 中列出的全部源码文件。"""
        contents: dict[str, str] = {}
        for rel in self.key_source_files:
            full = self.source_root / rel
            if not full.exists():
                continue
            try:
                text = full.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            # 单文件过大时截断
            if len(text) > 80000:
                text = text[:80000] + "\n\n// ... [TRUNCATED] ..."
            contents[rel] = text
        return contents

    def _generate_overview_from_snippets(self, func: str, snippets: str) -> str:
        """基于已抽取的 snippets 为单个功能生成 MD 概览。"""
        if not snippets:
            return f"# {func}\n\n(No relevant code found)\n"

        if len(snippets) > 30000:
            snippets = snippets[:30000] + "\n\n// ... [TRUNCATED] ..."

        prompt = _OVERVIEW_PROMPT.format(func=func, snippets=snippets)
        result = self.router.complex(
            prompt,
            system=_OVERVIEW_SYSTEM_PROMPT,
            max_tokens=8192,
            thinking=False,
        )
        content = result.get("content", "") if isinstance(result, dict) else ""
        return content or f"# {func}\n\n(Analysis failed)\n"

    # ── 数值常量学习（全局、一次性、hash 驱动） ──────────────────────────

    def _learn_constants_if_needed(
        self,
        status_cb: Callable[[str], None],
        force: bool = False,
    ) -> dict:
        """读 ``_CONSTANTS_SOURCE_FILES``，抽取数值常量到
        ``memory/code_knowledge/constants.json``。

        流程：
          1. 读取所有源文件，计算聚合 hash
          2. 与 ``constants.json._meta.aggregate_hash`` 对比 → 未变则跳过
          3. 构造截取过的 snippets（仅保留 `#define` 行和 `float LineXxx = ...`
             全局变量赋值）——降低 token 开销
          4. 一次 LLM 调用拿 JSON，写入 ``constants.json``

        参数 ``force``：忽略 hash 对比强制重学（CLI ``--learn-constants`` 场景）。
        """
        out_path = self.knowledge_dir / "constants.json"

        file_contents: dict[str, str] = {}
        hash_inputs: list[str] = []
        for rel in _CONSTANTS_SOURCE_FILES:
            full = self.source_root / rel
            if not full.exists():
                continue
            try:
                txt = full.read_text(encoding="utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                continue
            file_contents[rel] = txt
            hash_inputs.append(hashlib.sha256(txt.encode()).hexdigest()[:16])

        if not file_contents:
            status_cb("[constants] 常量源文件都读不到，跳过")
            return {"skipped": True, "reason": "no_source_files"}

        aggregate_hash = hashlib.sha256(
            "|".join(sorted(hash_inputs)).encode()
        ).hexdigest()[:16]

        if not force and out_path.exists():
            try:
                prev = json.loads(out_path.read_text(encoding="utf-8"))
                prev_hash = (prev.get("_meta") or {}).get("aggregate_hash")
                if prev_hash == aggregate_hash:
                    return {
                        "skipped": True,
                        "reason": "source_unchanged",
                        "aggregate_hash": aggregate_hash,
                    }
            except (json.JSONDecodeError, OSError):
                pass

        status_cb("[constants] 抽取数值常量（全局，一次性）...")
        snippets = self._extract_constant_snippets(file_contents)
        if not snippets.strip():
            status_cb("[constants] 没抽到有效片段，跳过")
            return {"skipped": True, "reason": "empty_snippets"}

        if len(snippets) > self.max_snippet_chars:
            snippets = snippets[: self.max_snippet_chars] + "\n... [TRUNCATED] ..."

        status_cb(f"[constants] 向 AI 发送 {len(snippets):,} 字符片段...")
        try:
            result = self.router.complex(
                _CONSTANTS_USER_PROMPT.format(snippets=snippets),
                system=_CONSTANTS_SYSTEM_PROMPT,
                max_tokens=12000,
                thinking=self.use_thinking,
            )
        except Exception as e:  # noqa: BLE001
            status_cb(f"[constants] AI 调用失败: {e}")
            return {"skipped": True, "reason": f"router_error: {e}"}

        content = result.get("content", "") if isinstance(result, dict) else ""
        parsed = parse_json_from_llm(content) if content else None
        if not parsed or not isinstance(parsed, dict):
            status_cb("[constants] 解析 AI 输出失败")
            return {"skipped": True, "reason": "parse_failed"}

        # 规整化：确保三个一级 key 存在
        for k in ("vehicle_config", "function_thresholds", "roi_derived"):
            if not isinstance(parsed.get(k), dict):
                parsed[k] = {}

        parsed["_meta"] = {
            "last_updated": datetime.datetime.now().isoformat(),
            "aggregate_hash": aggregate_hash,
            "source_files": sorted(file_contents.keys()),
        }

        out_path.write_text(
            json.dumps(parsed, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        counts = {
            k: len(parsed.get(k, {}))
            for k in ("vehicle_config", "function_thresholds", "roi_derived")
        }
        status_cb(
            f"[constants] 新学 "
            f"vehicle={counts['vehicle_config']}, "
            f"thresholds={counts['function_thresholds']}, "
            f"roi_derived={counts['roi_derived']}"
        )
        return {
            "skipped": False,
            "counts": counts,
            "aggregate_hash": aggregate_hash,
        }

    def _extract_constant_snippets(self, file_contents: dict[str, str]) -> str:
        """抽取与"数值常量"相关的行：``#define``、``float Xxx = ...``、
        ``const ... = ...``。附带 2 行上下文以便 LLM 理解作用域。

        这样可以把 paraDefine.h (~400 行) + dotCalibDefine.h (~150 行) +
        adasFunc.c 开头的全局变量赋值块 (~250 行) 压缩到 ~30KB。
        """
        parts: list[str] = []
        for rel, text in file_contents.items():
            lines = text.splitlines()
            kept: set[int] = set()
            for i, ln in enumerate(lines):
                stripped = ln.strip()
                # 直接命中的行：#define + 数值、float 全局赋值、const 赋值
                if (
                    stripped.startswith("#define ")
                    and any(ch.isdigit() for ch in stripped[7:])
                ) or (
                    "= " in stripped
                    and any(stripped.startswith(p) for p in (
                        "float ", "double ", "const float ",
                        "const double ", "static float ", "static const float ",
                        "static const double ", "int ", "const int ",
                        "uint8_t ", "uint16_t ", "uint32_t ",
                        "static uint8_t ", "static uint16_t ", "static uint32_t ",
                    ))
                ):
                    kept.add(i)
                # LineBSDxxx / LineLCAxxx / LineDOWxxx / LineRCWxxx 模式
                elif "Line" in stripped and "=" in stripped and ";" in stripped:
                    if any(tok in stripped for tok in (
                        "LineBSD", "LineLCA", "LineDOW", "LineRCW",
                        "LineFCT", "LineRCT",
                    )):
                        kept.add(i)

            if not kept:
                continue

            # 为每个命中行附带 1 行上下文（前 1 后 1），有助于 LLM
            # 识别注释里的单位/用途
            expanded = set()
            for i in kept:
                expanded.update(range(max(0, i - 1), min(len(lines), i + 2)))

            ordered = sorted(expanded)
            # 按连续段组织，不连续处用 "..." 占位
            grouped: list[str] = []
            prev = -2
            buf: list[str] = []
            for i in ordered:
                if i != prev + 1 and buf:
                    grouped.append("\n".join(buf))
                    buf = []
                buf.append(f"{i + 1:5d}| {lines[i]}")
                prev = i
            if buf:
                grouped.append("\n".join(buf))

            section = "\n    ...\n".join(grouped)
            parts.append(f"### File: {rel}\n```c\n{section}\n```")
        return "\n\n".join(parts)

    # ── 单次学习 ────────────────────────────────────────────────────────

    def _learn_one(
        self,
        func: str,
        focus: str,
        state: dict,
        status_cb: Callable[[str], None],
    ) -> dict:
        """学习单个 (func, focus) 对。"""
        files = FOCUS_FILES.get(focus, [])
        if not files:
            return {"skipped": True, "reason": "no_focus_files"}

        # 读取源码并计算聚合 hash
        file_contents: dict[str, str] = {}
        hash_inputs: list[str] = []
        for rel in files:
            full = self.source_root / rel
            if not full.exists():
                continue
            try:
                txt = full.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            file_contents[rel] = txt
            hash_inputs.append(hashlib.sha256(txt.encode()).hexdigest()[:16])

        if not file_contents:
            return {"skipped": True, "reason": "source_files_missing"}

        combined_hash = hashlib.sha256(
            "|".join(sorted(hash_inputs)).encode()
        ).hexdigest()[:16]

        pair_key = f"{func}/{focus}"
        prev = (state.get("pair_hashes") or {}).get(pair_key)
        if prev == combined_hash:
            return {"skipped": True, "reason": "source_unchanged"}

        # 抽取 func 相关片段
        keywords = FUNC_KEYWORDS.get(func, [func.lower(), func])
        snippets = self._extract_snippets(file_contents, keywords)
        if not snippets.strip():
            return {"skipped": True, "reason": "no_relevant_snippets"}

        if len(snippets) > self.max_snippet_chars:
            snippets = snippets[: self.max_snippet_chars] + "\n... [TRUNCATED] ..."

        status_cb(f"[{func}/{focus}] 向 AI 发送 {len(snippets):,} 字符片段...")

        # 调用 AI 提取结构化知识
        extracted = self._invoke_ai(func, focus, snippets)
        if not extracted:
            return {"skipped": True, "reason": "empty_ai_response"}

        # 合并到 knowledge 文件
        stats = self._merge_knowledge(func, focus, extracted, combined_hash)

        # 更新 state
        state.setdefault("pair_hashes", {})[pair_key] = combined_hash
        state.setdefault("learned_pairs", [])
        if pair_key not in state["learned_pairs"]:
            state["learned_pairs"].append(pair_key)

        return {
            "skipped": False,
            "items_added": stats.get("added", 0),
            "items_updated": stats.get("updated", 0),
        }

    # ── 代码片段抽取 ────────────────────────────────────────────────────

    def _extract_snippets(
        self,
        file_contents: dict[str, str],
        keywords: list[str],
    ) -> str:
        """按关键字从每个文件抽取相关代码片段，带 L<行号> 前缀。"""
        parts: list[str] = []
        per_file_budget = max(4000, self.max_snippet_chars // max(1, len(file_contents)))
        for rel, text in file_contents.items():
            sections = extract_relevant_sections(
                text, keywords, context_lines=12, max_chunks=20,
            )
            if not sections:
                continue
            if len(sections) > per_file_budget:
                sections = sections[:per_file_budget] + "\n... [file-truncated] ..."
            parts.append(f"### File: {rel}\n```c\n{sections}\n```")
        return "\n\n".join(parts)

    # ── AI 调用 ──────────────────────────────────────────────────────────

    def _invoke_ai(self, func: str, focus: str, snippets: str) -> Optional[dict]:
        """用专门 prompt 抽取结构化知识。"""
        prompt = _FOCUS_PROMPT_TEMPLATES[focus].format(func=func, snippets=snippets)
        system = _FOCUS_SYSTEMS[focus]
        try:
            result = self.router.complex(
                prompt,
                system=system,
                max_tokens=12000,
                thinking=self.use_thinking,
            )
        except Exception:
            return None
        content = result.get("content", "") if isinstance(result, dict) else ""
        if not content:
            return None
        parsed = parse_json_from_llm(content)
        return parsed if parsed else None

    # ── Knowledge Merge ─────────────────────────────────────────────────

    def _merge_knowledge(
        self,
        func: str,
        focus: str,
        extracted: dict,
        source_hash: str,
    ) -> dict:
        """将抽取结果合并到 memory/code_knowledge/<FUNC>.json。

        Merge 策略：
        - 顶层 focus 下的每个 key：
          * 若值是 list 且每项有 `id` → 按 id 去重；新 id 追加，已有 id 在内容变化时更新
          * 若值是 dict → 深合并（key 级别）
          * 否则覆盖
        - _meta.source_hashes[focus] = source_hash
        - _meta.learned_focuses 追加当前 focus
        """
        path = self.knowledge_dir / f"{func.upper()}.json"
        existing: dict = {}
        if path.exists():
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                existing = {}

        meta = existing.get("_meta", {}) or {}
        meta["function"] = func.upper()
        meta["last_updated"] = datetime.datetime.now().isoformat()
        learned = set(meta.get("learned_focuses", []))
        learned.add(focus)
        meta["learned_focuses"] = sorted(learned)
        src_hashes = meta.get("source_hashes", {}) or {}
        src_hashes[focus] = source_hash
        meta["source_hashes"] = src_hashes
        existing["_meta"] = meta

        focus_section = existing.get(focus, {}) or {}
        added, updated = 0, 0

        for key, value in extracted.items():
            if isinstance(value, list):
                prev_list = focus_section.get(key) if isinstance(focus_section.get(key), list) else []
                merged_list, a, u = _merge_list_by_id(prev_list, value)
                focus_section[key] = merged_list
                added += a
                updated += u
            elif isinstance(value, dict):
                prev_dict = focus_section.get(key) if isinstance(focus_section.get(key), dict) else {}
                merged_dict, a, u = _merge_dict_entries(prev_dict, value)
                focus_section[key] = merged_dict
                added += a
                updated += u
            else:
                if focus_section.get(key) != value:
                    if key in focus_section:
                        updated += 1
                    else:
                        added += 1
                focus_section[key] = value

        existing[focus] = focus_section

        path.write_text(
            json.dumps(existing, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return {"added": added, "updated": updated}

    # ── State I/O ───────────────────────────────────────────────────────

    def _read_state(self) -> dict:
        if self.state_path.exists():
            try:
                return json.loads(self.state_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
        return {
            "cursor": 0,
            "warmup_done": False,
            "pair_hashes": {},
            "learned_pairs": [],
            "total_learned_pairs": 0,
        }

    def _write_state(self, state: dict) -> None:
        self.state_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


# ── 辅助：按 id 合并列表 / 按 key 合并 dict ─────────────────────────────

def _merge_list_by_id(prev: list, new: list) -> tuple[list, int, int]:
    """将 new 合并到 prev（按每项的 `id` 字段去重），返回 (merged, added, updated)。

    若某项没有 `id`，会根据其内容生成稳定 hash 作为 id。
    """
    added, updated = 0, 0
    by_id: dict[str, dict] = {}
    for it in prev:
        if not isinstance(it, dict):
            continue
        iid = it.get("id") or _auto_id(it)
        it["id"] = iid
        by_id[iid] = it

    for it in new:
        if not isinstance(it, dict):
            continue
        iid = it.get("id") or _auto_id(it)
        it["id"] = iid
        it["_learned_at"] = datetime.datetime.now().isoformat()
        if iid in by_id:
            prev_json = json.dumps(by_id[iid], sort_keys=True, default=str, ensure_ascii=False)
            new_json = json.dumps(it, sort_keys=True, default=str, ensure_ascii=False)
            if prev_json != new_json:
                by_id[iid].update(it)
                updated += 1
        else:
            by_id[iid] = it
            added += 1

    return list(by_id.values()), added, updated


def _merge_dict_entries(prev: dict, new: dict) -> tuple[dict, int, int]:
    """将 new 合并到 prev（字典浅合并，值为 dict 时继续深合并），返回统计。"""
    added, updated = 0, 0
    result = dict(prev)
    for k, v in new.items():
        if k not in result:
            if isinstance(v, dict):
                v = {**v, "_learned_at": datetime.datetime.now().isoformat()}
            result[k] = v
            added += 1
            continue
        if isinstance(v, dict) and isinstance(result[k], dict):
            prev_json = json.dumps(result[k], sort_keys=True, default=str, ensure_ascii=False)
            merged = {**result[k], **v, "_learned_at": datetime.datetime.now().isoformat()}
            new_json = json.dumps(merged, sort_keys=True, default=str, ensure_ascii=False)
            if prev_json != new_json:
                result[k] = merged
                updated += 1
        else:
            if result[k] != v:
                result[k] = v
                updated += 1
    return result, added, updated


_ID_RE = re.compile(r"[^a-z0-9]+")


def _auto_id(item: dict) -> str:
    """为没有 id 的条目生成稳定 hash id（基于除 _ 开头字段外的内容）。"""
    canon = {k: v for k, v in item.items() if not k.startswith("_") and k != "id"}
    h = hashlib.md5(
        json.dumps(canon, sort_keys=True, default=str, ensure_ascii=False).encode()
    ).hexdigest()[:8]
    # 尝试从 description 提取可读前缀
    desc = str(item.get("description", "") or item.get("name", "") or "item")
    slug = _ID_RE.sub("-", desc.lower())[:24].strip("-") or "item"
    return f"{slug}-{h}"
