# -*- coding: utf-8 -*-
"""
Multi-Expert Panel: 5 domain experts debate to produce accurate diagnosis.

V2: Experts receive structured condition tables and windowed timelines
    instead of raw truncated text.

Architecture:
  R1: Independent analysis (condition table + data comparison)
  R2: Cross-review + moderator challenge
  R3: Convergence → final verdict
"""
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from .model_router import ModelRouter
from .utils import parse_json_from_llm

# ── Expert Definitions ──────────────────────────────────────────────────

EXPERTS = {
    "signal_chain": {
        "name": "信号链路专家",
        "emoji": "🔗",
        "domain": "CAN信号→内部变量映射",
        "source_files": [
            "coem\\GWM_B26\\components\\AswIf\\ASW_IN\\RteComMapping.c",
            "coem\\GWM_B26\\components\\AswIf\\ASW_IN\\RteComMapping.h",
        ],
        "system": """你是**信号链路专家**。你的任务:
1. 查看「条件检查表」中涉及的CAN信号(功能开关/使能/外部系统标志/DTC)
2. 在「数据时间线」和「关键事实」中找到这些信号的实际值
3. 追溯链路: CAN信号名 → RteComMapping宏 → 内部变量 → 哪个条件用了它
4. 逐条检查信号是否正常

通用规则(不限定某个功能):
- 所有 `*SwtReq` 类信号 → 通过 RteComMapping 写入 `b*Enable`（按当前分析功能前缀查找）
- 所有 `AEB*/ESP*/ACC*/TCS*/DTC*` 外部系统标志 → 读取为 `g_DTCCode.b*ActiveFlg` 或同结构体字段
- 车型变体: `g_GWMSpecificVariant.bits`
- 私 CAN: `g_RteComMapping_*WarnSig`（左右雷达互传）

禁止把其他功能（如 FCTA、BSD）的专属映射当作当前功能的真实链路。必须基于
当前分析功能与 RteComMapping.c 中实际出现的行来判断。

输出: 只输出有数据支撑的发现。""",
    },

    "algorithm": {
        "name": "算法逻辑专家",
        "emoji": "⚙️",
        "domain": "adasFunc.c报警条件与阈值",
        "source_files": [
            "coem\\GWM_B26\\components\\AswPerception\\func\\adasFunc.c",
            "coem\\GWM_B26\\components\\AswPerception\\func\\adasFunc.h",
            "adas\\symmetry\\perception\\include\\paraDefine.h",
        ],
        "system": """你是**算法逻辑专家**。你的任务:
1. 查看「条件检查表」中列出的所有激活条件和阈值
2. 在「关键事实」和「数据时间线」中找到对应的实际值
3. **逐条比对**: 条件是否满足?

必须检查(变量名根据当前分析功能替换Xxx):
- 自车速度范围: fXxxActiveUpSpd/fXxxActiveLowSpd vs 数据中 car_spd
- 目标速度范围: fXxxObjWarningSpd/UpSpd vs 数据中 trc_N_vel_x
- 目标角度/距离/TTC vs 阈值
- XxxSkipFlg中的dynFlg条件(如存在)
- bXxxDetectFlg的使能条件(如存在)
- 条件检查表中列出的功能专属标志位和外部抑制条件

**关键 — 因果链追溯（重要！）**:
当发现「条件不满足」时，不要停止。继续追溯:
  条件不满足 → 代码中哪行做了此判断？ → 判断依赖哪个变量？ → 该变量来自哪个CAN信号？
追溯时必须基于当前分析功能(Xxx)的实际代码逻辑，不要套用其他功能的模式。
每个功能有不同的激活/退出条件和代码路径，必须逐一分析当前功能涉及的代码分支。

输出要求: 条件→阈值→数据值→满足Y/N→**不满足时追溯代码路径到CAN信号**。""",
    },

    "system_state": {
        "name": "系统状态专家",
        "emoji": "🔄",
        "domain": "双状态机与功能使能",
        "source_files": [
            "coem\\GWM_B26\\components\\AswIf\\ASW_IN\\ASWIN_SystemState.c",
            "coem\\GWM_B26\\components\\AswIf\\ASW_IN\\ASWIN_SystemState.h",
        ],
        "system": """你是**系统状态专家**。你的任务:
1. 从「关键事实」读取状态机的实际值分布(system_state=?)
2. 从「状态跳变」看是否有状态转移
3. 从「条件检查表」找到进入Active(3)和Standby(2)的所有前置条件
4. 逐条检查哪个条件阻止了预期的状态转移

双状态机:
- adasFunc.c: 感知侧写 *SystemState (基于速度/故障)
- ASWIN_SystemState.c: 平台侧写同一 *SystemState (基于自检/使能/速度)
- AdasStateActive(): Standby(2)→Active(3) 需要 adasWarning 非零

**关键 — 区分观测层与代码层**:
- 「关键事实」中的[配置层·ADAS使能]数据来自雷达端outputData，是ECU内部决策的**结果**
- 如果看到某功能enable=0，必须追溯: ASWIN_SystemState.c中哪个条件导致使能关闭？
  → bXxxEnable的赋值依赖哪些CAN信号？→ 这些信号的实际值是什么？
- 不要直接说"<某功能>使能被关闭所以不工作"——要说明**为什么被关闭**

输出: 实际状态序列 + 每个条件是否满足 + 卡在哪 + **根因追溯到信号层**。""",
    },

    "perception": {
        "name": "感知与目标专家",
        "emoji": "👁️",
        "domain": "目标属性与过滤",
        "source_files": [
            "adas\\symmetry\\perception\\src\\objAttribCal.c",
            "adas\\symmetry\\perception\\src\\track.c",
            "adas\\symmetry\\perception\\src\\postProcess.c",
            "adas\\symmetry\\perception\\include\\structDefine.h",
        ],
        "system": """你是**感知与目标专家**。你的任务:
1. 从「关键事实」和「数据时间线」读取目标属性(vel_x, dist_x/y, ttc)
2. 从「条件检查表」读取目标筛选条件(速度范围、类型、角度)
3. 逐条比对: 目标是否满足触发条件?
4. 当"A类目标触发但B类不触发"时，比较两者数值差异

**关键**: 数据中 trc_N_vel_x 单位是 m/s，代码阈值单位是 km/h (×3.6换算)。
objAbsV = sqrt(velAbsX² + velAbsY²)，而数据中 vel_x 是单轴速度。

**关于目标级告警标志(int8)**:
`radar_objects` 中的每个功能都有独立的 `*_flag` 列（如 bsd_flag / lca_flag / dow_flag /
rcw_flag / rcta_flag / rctb_flag / fcta_flag / fctb_flag），均为 int8（-128~127），
非零值表示告警激活但具体含义是状态码/bitfield，需结合该功能的代码理解。
这些标志是雷达端的**观测输出**，不是ECU决策的输入。分析时请只关注当前
问题涉及的那一列，不要串到其他功能的 flag 上。

输出: 目标属性值 vs 阈值 + 一句话结论。""",
    },

    "architecture": {
        "name": "架构专家",
        "emoji": "📡",
        "domain": "左右雷达与输出合并",
        "source_files": [
            "coem\\GWM_B26\\components\\AswIf\\ASW_OUT\\ASWOUT_OutCalc.c",
        ],
        "system": """你是**架构专家**。你的任务:
1. 确认数据来自哪个角雷达(front_left/front_right)
2. 检查「测试窗口」中左右数据是否一致
3. 仅在问题涉及左右差异或合并逻辑时深入分析

输出: 简洁，只报告与问题相关的架构因素。""",
    },
}

# ── Moderator Prompt ────────────────────────────────────────────────────

MODERATOR_SYSTEM = """你是角雷达问题分析的**研讨主持人**。

## 核心原则: **沿因果链追溯，区分观测、时序耦合与根因**

### 因果链五层模型（从表象到根因）:
  L4 外部表现:   告警未触发/误触发（用户看到的问题）
  L3 雷达观测:   radar_objects中的告警标志、ADAS使能状态（雷达端的观测值）
  L2.5 时序耦合: 代码中的"保持-释放/累积-清零/防抖/滞回/边沿"等行为模式在
                 数据时序上是否被触发(由TPE段自动分析)
  L2 ECU逻辑:    adasFunc.c中的条件判断、状态机跳变、hold/release逻辑
  L1 信号输入:   CAN信号值 → RteComMapping → 内部变量（最底层触发源）

### 分析方法:
1. 先确认L4现象（什么功能没工作）
2. 在L3找到观测证据（哪个标志/状态异常）
3. **读TPE段判断L2.5** — 如果 TPE 已经定位到"已触发模式"，
   说明代码中存在一处对 L1 信号时序敏感的行为，它是 L3 观测的直接成因
4. 在L2追溯代码路径（哪段代码逻辑导致了L3的状态）
5. 在L1找到触发源（哪个CAN信号的值触发了L2/L2.5的逻辑）
6. 根因 = L1信号 × L2.5时序耦合点 × L2代码分支

### 关键规则:
- **L3的观测值是"结果"不是"原因"** — 看到异常状态必须追问"代码中哪里产生了这个状态"
- **TPE 已触发模式必须反映在根因** — 如果 TPE 段给出了 `verdict=triggered`
  的模式，且该模式的"清零副作用"正是 L3 观测到的异常状态，
  则根因描述**必须**包含：触发模式名 + 关键时刻 t=X.XXXs +
  触发信号的短脉冲/持续时长 + 因此导致的副作用变量。
- **TPE 未触发模式是反向证据** — 如果某个模式被 TPE 标为 `not_triggered`，
  则不能把对应的条件写成根因。
- **条件检查表中的条件不满足时** → 追溯到代码：哪行代码做了这个判断？输入变量来自哪个CAN信号？
- **不要停在观测层** — 必须追溯到L2代码逻辑或L1信号输入
- **不要套用其他case的模式** — 每个问题有独立的代码路径，必须基于当前功能的代码逻辑分析
- 先简单后复杂，先数据后推测
- 没有数据支撑的假设禁止输出"""


_FAIL_TYPE_EXPERTS: dict[str, list[str]] = {
    "FP": ["signal_chain", "algorithm", "perception"],
    "FN": ["algorithm", "system_state", "perception"],
    "DELAY": ["algorithm", "perception", "architecture"],
    "STATE": ["system_state", "signal_chain", "algorithm"],
    "OTHER": ["signal_chain", "algorithm", "system_state", "perception", "architecture"],
}


class ExpertPanel:
    """
    Multi-expert debate system.
    V2: Structured condition tables and windowed timelines.
    V3: Expert selection based on fail_type to reduce LLM cost.
    """

    ROUND_COUNT = 3

    def __init__(self, router: ModelRouter, config: dict, project_root: Path):
        self.router = router
        self.config = config
        self.project_root = project_root
        self.source_root = Path(config["paths"]["source_code"])
        self._source_cache = {}
        self._thinking = router.thinking_mode

    MAX_PARALLEL = 5

    @staticmethod
    def select_experts(fail_type: str = "OTHER") -> dict[str, dict]:
        """Select a subset of experts based on fail_type."""
        expert_ids = _FAIL_TYPE_EXPERTS.get(fail_type.upper(), _FAIL_TYPE_EXPERTS["OTHER"])
        return {eid: EXPERTS[eid] for eid in expert_ids if eid in EXPERTS}

    def run_panel(
        self,
        problem: str,
        expected: str,
        func_name: str,
        data_summary: str,
        memory_context: str = "",
        on_status=None,
        fail_type: str = "OTHER",
        task_type: str = "diagnose",
    ) -> dict:
        def status(msg):
            if on_status:
                on_status("expert_panel", msg)

        case_context = self._build_case_context(
            problem, expected, func_name, data_summary, memory_context,
            task_type=task_type,
        )

        selected_experts = self.select_experts(fail_type)

        for expert_def in selected_experts.values():
            self._load_expert_sources(expert_def)

        n_experts = len(selected_experts)
        # ── Round 1: Independent Analysis (parallel) ───────────────────
        status(f"Round 1/3: {n_experts}位专家并发分析 (fail_type={fail_type})...")
        t0 = time.perf_counter()
        opinions = self._parallel_expert_analyze(case_context, status, selected_experts)
        r1_time = time.perf_counter() - t0
        status(f"Round 1/3: 完成 ({r1_time:.1f}s, {n_experts}位专家并发)")

        # ── Round 2: Cross-Review + Moderator Challenge ─────────────────
        status("Round 2/3: 交叉审查与质疑...")
        all_opinions_text = self._format_all_opinions(opinions)
        challenges = self._moderator_challenge(case_context, all_opinions_text)

        # Experts respond to challenges (parallel)
        questioned = {
            eid: challenges["questions"][eid]
            for eid in challenges.get("questions", {})
            if eid in EXPERTS
        }
        if questioned:
            status(f"Round 2/3: {len(questioned)}位专家并发回应质疑...")
            t1 = time.perf_counter()
            responses = self._parallel_expert_respond(
                questioned, case_context, opinions, all_opinions_text,
            )
            for eid, resp in responses.items():
                opinions[eid] += f"\n\n### 补充分析(R2)\n{resp}"
            r2_time = time.perf_counter() - t1
            status(f"Round 2/3: 回应完成 ({r2_time:.1f}s)")

        # ── Round 3: Convergence ────────────────────────────────────────
        status("Round 3/3: 综合收敛，形成最终诊断...")
        all_opinions_text = self._format_all_opinions(opinions)
        final_verdict = self._moderator_synthesize(
            case_context, all_opinions_text, challenges,
        )

        return {
            "expert_opinions": opinions,
            "moderator_challenges": challenges,
            "final_verdict": final_verdict,
            "rounds": self.ROUND_COUNT,
        }

    # ── Parallel dispatch ────────────────────────────────────────────────

    def _parallel_expert_analyze(
        self, case_context: str, status,
        selected_experts: dict[str, dict] | None = None,
    ) -> dict:
        """Run selected experts' Round 1 analysis concurrently."""
        experts = selected_experts or EXPERTS
        opinions: dict[str, str] = {}

        def _run_one(expert_id: str, expert_def: dict) -> tuple[str, str]:
            source_code = self._load_expert_sources(expert_def)
            result = self._expert_analyze(
                expert_id, expert_def, case_context, source_code, round_num=1,
            )
            return expert_id, result

        with ThreadPoolExecutor(max_workers=self.MAX_PARALLEL) as pool:
            futures = {
                pool.submit(_run_one, eid, edef): edef
                for eid, edef in experts.items()
            }
            for future in as_completed(futures):
                edef = futures[future]
                try:
                    eid, analysis = future.result()
                    opinions[eid] = analysis
                    status(f"  {edef['emoji']} {edef['name']} 完成")
                except Exception as e:
                    opinions[eid] = f"(分析失败: {e})"

        return opinions

    def _parallel_expert_respond(
        self,
        questioned: dict[str, str],
        case_context: str,
        opinions: dict[str, str],
        all_opinions_text: str,
    ) -> dict[str, str]:
        """Run questioned experts' Round 2 responses concurrently."""
        responses: dict[str, str] = {}

        def _respond_one(expert_id: str, question: str) -> tuple[str, str]:
            expert_def = EXPERTS[expert_id]
            source_code = self._load_expert_sources(expert_def)
            result = self._expert_respond(
                expert_id, expert_def, case_context, source_code,
                opinions[expert_id], question, all_opinions_text,
            )
            return expert_id, result

        with ThreadPoolExecutor(max_workers=self.MAX_PARALLEL) as pool:
            futures = {
                pool.submit(_respond_one, eid, q): eid
                for eid, q in questioned.items()
            }
            for future in as_completed(futures):
                eid = futures[future]
                try:
                    _, resp = future.result()
                    responses[eid] = resp
                except Exception as e:
                    responses[eid] = f"(回应失败: {e})"

        return responses

    # ── Expert Operations ───────────────────────────────────────────────

    MAX_SOURCE_CHARS_R1 = 60_000
    MAX_SOURCE_CHARS_R2 = 30_000

    def _expert_analyze(
        self, expert_id: str, expert_def: dict,
        case_context: str, source_code: str, round_num: int,
    ) -> str:
        """Single expert's independent analysis — structured, data-driven."""
        src = source_code[:self.MAX_SOURCE_CHARS_R1]
        prompt = f"""## 问题与数据
{case_context}

## 源码
{src}

---

用你的专业（{expert_def['domain']}）分析。

**分析方法**: 你已收到「条件检查表」、「关键事实」，以及最重要的「TPE 因果对齐」。
1. **先读 TPE 段**: 检查是否有 `verdict=triggered` 的模式与你领域相关。
   若有，则其"触发信号/短脉冲/清零副作用"就是你领域需要解释的直接成因。
2. 在「条件检查表」中找到你负责领域的条件
3. 在「关键事实」和「数据时间线」中找到实际值
4. 逐条比对，标记满足(Y)/不满足(N)
5. 将 TPE 触发事件与你列出的条件做**时序一致性检查**:
   - 若 TPE 显示某模式在 t=T 触发且导致 `varX` 被清零,
     那么你看到的 `varX == 0` 的条件应该在 t≥T 时才开始"不满足"
   - 若时序对不上，需指出其他可能的原因
6. 不满足的条件就是问题所在

**硬约束（不可违反）**:
- 如果 TPE 段给出了 `file:line_start~line_end`，在你的结论里引用代码位置时
  **必须沿用相同的文件名与行号**，禁止替换成你脑中的其他函数（如把
  `adasFunc.c:6378` 改成 `ASWIN_SystemState.c` 的某函数）。
- 如果 TPE 段给出了 `trigger_variables`（如短脉冲信号名），必须将这些
  信号名原样写进因果链。
- 如果 TPE 段显示 `verdict=not_triggered`，不得把对应条件直接作为根因。
- 出现你无法解释的 TPE 证据时，显式写 "我的领域无法判定该证据，交由
  ${{其他专家}} 核对"，而不是回避或覆盖。

输出格式(严格遵循，不要废话):
**TPE 一致性**: 摘录与你领域相关的 TPE 触发模式 (模式名 + 时刻 + 副作用), 若无则写"无相关触发模式"

**条件检查表**
| 条件 | 阈值/要求 | 数据实际值 | 满足? | 对应 TPE 模式 |
|------|----------|-----------|------|--------------|

**结论**: 一句话指出最可能的原因 (必须体现 TPE 触发或未触发的含义)
**需确认**: 需要其他专家验证的点(一句话)"""

        think = self._thinking == "full"
        result = self.router.complex(prompt, system=expert_def["system"], thinking=think)
        return result.get("content", f"({expert_def['name']} 分析失败)")

    def _expert_respond(
        self, expert_id: str, expert_def: dict,
        case_context: str, source_code: str,
        my_analysis: str, question: str, all_opinions: str,
    ) -> str:
        prompt = f"""## 追问
{question}

## 其他专家发现
{all_opinions[:12000]}

## 你之前的分析
{my_analysis[:6000]}

## 源码
{source_code[:self.MAX_SOURCE_CHARS_R2]}

---
简洁回答追问，修正之前的错误(如有)。必须引用具体数值。不超过500字。"""

        think = self._thinking == "full"
        result = self.router.complex(prompt, system=expert_def["system"], thinking=think)
        return result.get("content", "(回应失败)")

    # ── Moderator Operations ────────────────────────────────────────────

    def _moderator_challenge(self, case_context: str, all_opinions: str) -> dict:
        prompt = f"""## 问题
{case_context[:8000]}

## 5位专家的独立分析
{all_opinions}

---

作为研讨主持人，请:

1. 找出各专家分析中的**矛盾点**
2. 找出**遗漏的分析角度**（特别是: 是否有专家忽略了「条件检查表」中的某个条件?）
3. 对需要深入分析的专家提出**具体追问**

输出JSON:
{{
  "contradictions": ["矛盾1描述", ...],
  "gaps": ["遗漏1描述", ...],
  "questions": {{
    "signal_chain": "追问内容(空字符串表示无追问)",
    "algorithm": "...",
    "system_state": "...",
    "perception": "...",
    "architecture": "..."
  }},
  "preliminary_consensus": "目前各专家的共识点",
  "key_dispute": "最关键的争议点"
}}"""

        think = self._thinking == "full"
        result = self.router.complex(prompt, system=MODERATOR_SYSTEM, thinking=think)
        parsed = parse_json_from_llm(result.get("content", ""), fallback={
            "contradictions": [],
            "gaps": ["Parsing failed"],
            "questions": {},
            "preliminary_consensus": "",
            "key_dispute": "",
        })
        questions = parsed.get("questions", {})
        parsed["questions"] = {k: v for k, v in questions.items() if v and v.strip()}
        return parsed

    def _moderator_synthesize(
        self, case_context: str, all_opinions: str, challenges: dict,
    ) -> str:
        prompt = f"""## 问题
{case_context[:8000]}

## 全部专家分析
{all_opinions[:30000]}

## 审查结果
矛盾: {json.dumps(challenges.get('contradictions', []), ensure_ascii=False)}
遗漏: {json.dumps(challenges.get('gaps', []), ensure_ascii=False)}

---

综合诊断，严格遵循以下格式(每节控制在3-5行以内):

**数据溯源规则**: 每个结论的"实际值"和"来源"必须注明出处:
"TPE 因果对齐"/"抑制信号实测"/"条件检查表"/"帧分析数据"/"BAG数据"/"权威阈值参考"。
**禁止**引用系统未提供的信号名或自行推断的数据值。如果"抑制信号实测"中标注为"抑制条件不满足"，则不得在结论中将该条件列为根因。
**阈值必须**与"权威阈值参考"(来自source_docs)中的值一致，禁止使用"预估"阈值。
**TPE 规则**: 如果 TPE 段中有 `verdict=triggered` 的模式与本问题相关(触发信号/副作用出现在现象中)，
则根因**必须**以该模式为核心描述；忽略 TPE 触发证据的诊断视为不完整。
**TPE 文件与行号锁定（硬约束）**:
- 最终"根因"段落中提到的代码位置，**必须**使用 TPE 段里给出的
  `file:line_start~line_end`。不允许把 `adasFunc.c:6378-6382` 改写成
  `ASWIN_SystemState.c` 或其他无关函数。
- 如果 TPE 段中含多个 triggered 模式，应全部在"时序耦合"表格中呈现；
  **不得**让其他专家的主观描述覆盖 TPE 给出的行号证据。
- 若你（主持人）认为 TPE 定位有误，必须先写明"TPE 定位: <文件:行>"，
  再单独开一节"主持人补充判断"说明你不采纳的理由，不得直接覆盖。

### 根因
一句话根因 + 因果链: 变量A(实际值X, 来源Y) → 条件B(阈值Z, 满足/不满足) → 结果C
必须显式标明:
- 哪条 TPE 模式触发(模式类型 + 源文件:行号 + 首次触发时刻 + 最短触发持续)
- 该模式的副作用变量如何在数据中反映为现象

### 时序耦合(TPE触发清单)
| 模式 | 源文件:行 | 首触发t | 持续 | 触发信号 | 副作用 |
|------|----------|--------|------|---------|--------|
(摘录所有 `verdict=triggered` 的模式；无触发时明确写"无")

### 条件检查汇总
| 条件 | 阈值 | 实际值 | 满足? | 数据来源 | 相关 TPE 模式 |
(合并所有专家的检查表，去重。"实际值"必须有数据出处，不得编造。"阈值"须与权威阈值参考一致)

### 关键证据链(结构化)
每条证据格式: **信号**: `信号名` | **时间**: `t=X.XXXs` | **值**: `实际值` | **来源**: `数据出处` | **TPE 模式**: `模式名/行号`
(列出支撑根因的3-5条关键证据, TPE 触发相关证据必须入选)

### 数据链路
CAN信号→内部变量→判断条件→结果 (一条链路一行)

### 测试窗口分析
窗口内关键数据变化的时序描述(2-3行)

### 场景差异分析
结合功能特性和测试场景，分析现象差异的原因(用数值说明)

### 修复建议
1. xxx
2. xxx

### 置信度: X/100
一句话说明不确定因素"""

        think = self._thinking in ("synth", "full")
        result = self.router.complex(prompt, system=MODERATOR_SYSTEM, thinking=think)
        return result.get("content", "Final synthesis failed.")

    # ── Helpers ──────────────────────────────────────────────────────────

    def _build_case_context(
        self, problem, expected, func_name, data_summary, memory_context,
        task_type: str = "diagnose",
    ) -> str:
        task_type = (task_type or "diagnose").lower()
        task_header_map = {
            "diagnose": (
                "## 任务类型: diagnose (根因诊断)\n"
                "目标: 找出**已发生的异常**的根本原因，输出可复现的因果链。"
            ),
            "tune": (
                "## 任务类型: tune (参数调优)\n"
                "目标: 基于**参数敏感性**给出调优方向与数值建议，"
                "**不要**去分析任何\"根因\"。讨论必须围绕参数→观测信号的穿越关系展开。"
                "禁止把\"问题现象\"当故障；它只是优化需求。"
            ),
            "verify": (
                "## 任务类型: verify (参数变更验证)\n"
                "目标: 判断用户提出的新阈值在本次录制下的量化效果，"
                "对比调整前/调整后的穿越次数、裕度、超阈帧数。"
                "禁止输出与变更无关的根因结论。"
            ),
            "query": (
                "## 任务类型: query (信息检索)\n"
                "目标: 用文档/代码里的事实回答用户问题，不要虚构根因，"
                "无数据时直接说明\"未检索到\"。"
            ),
        }
        parts = [
            task_header_map.get(task_type, task_header_map["diagnose"]),
            f"## 问题现象\n{problem}",
            f"## 预期结果\n{expected}",
            f"## 涉及功能: {func_name}",
        ]
        if data_summary:
            parts.append(f"## 数据与条件\n{data_summary[:20000]}")
        if memory_context:
            parts.append(f"## 历史记忆\n{memory_context[:5000]}")
        return "\n\n".join(parts)

    def _load_expert_sources(self, expert_def: dict) -> str:
        parts = []
        for rel_path in expert_def.get("source_files", []):
            if rel_path in self._source_cache:
                parts.append(self._source_cache[rel_path])
                continue
            full_path = self.source_root / rel_path
            if full_path.exists():
                try:
                    text = full_path.read_text(encoding="utf-8", errors="replace")
                    if len(text) > 80000:
                        text = text[:80000] + "\n// ... [TRUNCATED]"
                    entry = f"### {rel_path}\n```c\n{text}\n```"
                    self._source_cache[rel_path] = entry
                    parts.append(entry)
                except Exception:
                    pass
        return "\n\n".join(parts) if parts else "(源码不可用)"

    def _format_all_opinions(self, opinions: dict) -> str:
        parts = []
        for expert_id, analysis in opinions.items():
            expert_def = EXPERTS[expert_id]
            parts.append(f"## {expert_def['emoji']} {expert_def['name']} ({expert_def['domain']})\n{analysis}")
        return "\n\n---\n\n".join(parts)
