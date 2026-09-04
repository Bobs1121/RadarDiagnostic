# V4 · 需求与决策上下文（设计参考基线，勿遗漏）

> **版本**: 4.0 · **日期**: 2026-08-21 · **状态**: 持续维护
> **用途**: 记录与用户的历次讨论、需求、已确认决策、实战教训、待办与待调研项。
> **规则**: 做任何 V4 设计与方案前，先读本文件，确保不遗漏已确认项；每次新增需求/决策/结论，追加到本文件对应章节。

---

## 0. 本文件的维护规则

- 任何影响架构/技术选型/能力范围的讨论结论，都必须落到本文件。
- 已确认决策用 `[D]` 标记，待确认用 `[TBD]`，待调研用 `[R]`。
- 修改设计文档（`V4_PI_DRIVEN_ARCHITECTURE.md` / `V4_DEVELOPMENT_PLAN.md`）时，先核对本文件。

---

## 1. 问题背景（起点）

**初始任务**：下载 BYD QZH 车型 RCTB 误触发数据，用 radarAnalyze 分析。

- 数据源（网络路径）：
  `\\abtvdfs2.de.bosch.com\ismdfs\loc\szh\Isilon2\TestackData\Driving_APP\08_BYD\47_CR60light\02_QZH\06_RCTB\1`
- 下载产物：`corner_radar_net_2026-08-13-16-03-09_1.bag`（1.12 GB，600 s，193,588 条）
- 本地案例目录：`cases/byd_qzh_rctb/`

**技术要点（UNC 访问）**：Git Bash 会吞 UNC 路径的 `\\`，须用 `.ps1` 脚本文件 + `MSYS_NO_PATHCONV=1` 方式访问网络路径；`powershell -Command` 内嵌路径仍会被转换，`-File` 方式可靠。

---

## 2. QZH 分析实战教训（数据准确性问题的根因）

**结论：bag 里的 CAN 输出信号（`/front/signals`、`/rear/signals`）是无效占位数据，不是真实证据。**

| 项 | 发现 |
|----|------|
| 信号来源 | bag 内 `/front/signals`、`/rear/signals` 由 `common_can_signal_publisher` 发布（用 DBC 生成信号字典 + 读真实 CAN 通道） |
| 占位机制 | bag 回放（无真实 CAN 硬件）时 publisher 收不到帧，信号停留在默认值：float=nan、int=0，`signal_valid=0` |
| 现象 | `veh_spd=281.53 m/s` 恒定、`braking_req=1` 恒定、`gear=1` 恒定——物理不可能且全程不变 |
| 诊断误判 | 诊断管线把这些占位值当真实证据，得出"RCTB 误触发"错误结论（置信度 40/100） |
| 真实情况 | 雷达内部（lgu_data wfAutosarData）从未触发 RCTB；RCTA_L 在 t≈270s 是**正确报警**（真实横穿目标 class=4，TTC 3.29→2.93s） |
| 雷达内部数据 | 动态真实：车速 5.27→0 m/s 变化、档位出现过 7/R、yaw 25 种值、对象级 rctb_flag 全程 0 |

**根因**：数据模型层（FrameStore）没有 provenance（来源溯源）和 signal_valid（信号有效性），消费端无法区分"真实信号"与"占位信号"。

**教训沉淀**：
- [D] 数据必须带 provenance + signal_valid；无效/占位/恒定数据不得参与判定。
- [D] 判定前必须过数据质量审计（恒定值 / 物理不可能值 → 标记 invalid）。
- [D] 诊断报告的"数据来源"必须来自真实数据标注，不能让 LLM 编造（如"用户现象描述"）。

---

## 3. 能力愿景（用户多轮描述汇总）

### 3.1 数据源（L0）

用户输入可能包括（独立或组合）：
- 代码仓（含项目文件夹、分支信息）
- BLF 数据（真实 CAN）
- ROS bag 数据（雷达内部 / 点云 / warning）
- MF4 数据
- DBC 文件
- 客户需求文档
- Linux 上的 arbe 仿真（10.190.171.44）

### 3.2 需要的能力（L2）

- 数据抽取（signal-extract）：模糊抽取 + 曲线绘制
- 数据分析（data-analyze）：统计 / 分布 / 窗口 / TPE
- 问题诊断（diag）
- 代码修复（code-fix）
- 仿真验证（sim-verify）
- 代码学习 / 代码分析（code-learn / code-analyze）
- 需求分析（req-analyze，未来扩展）
- 记忆（memory）

### 3.3 期望输出

- 问题诊断报告
- 指定的数据抽取报告（含曲线）
- 仿真后数据 / 仿真后结果
- 代码修改建议
- 需求-代码 gap 分析（未来）

### 3.4 用户故事与业务需求（用户明确 · 设计必须覆盖）

> **用户指出**：之前设计未先收集/确认用户故事、使用场景、具体业务需求。以下为用户明确列举的真实业务需求，**是模块拆分与交互设计的驱动**，任何设计不得遗漏。

#### 3.4.1 两种工作模式（人在环中 / 人在环外）

| 模式 | 含义 | 示例 |
|------|------|------|
| **人在环中（HITL，默认）** | 系统先做初步诊断 → 呈现关键数据/关键信息/中间产物 → **与用户交互** → 用户决定下一步动作 | "先做初步分析"，看完关键信号图后再决定是否深入 |
| **人在环外（autonomous，可切换）** | 用户下发完整指令 → 系统一直工作到结束（诊断/仿真/出报告） | "你自己干活，给最终结论" |

- 两种模式可切换（用户可随时从自动切回交互，或指定"这步自动完成"）。
- **中间产物呈现**必须设计：每步产出（信号图/初步诊断/仿真 trace/代码调用链）都能被用户查看和确认，而不是只给最终报告。

#### 3.4.2 用户故事清单（用户列举的具体场景）

| # | 用户故事（用户原话/语义） | 期望能力 | 中间产物 | 模式 |
|---|--------------------------|----------|----------|------|
| US1 | "我描述问题，要求先做初步分析" | 初步诊断（问题分类 + 关键信号 + 初步判断） | 关键信号曲线 + 初步诊断摘要 | HITL |
| US2 | "要求加一些日志，去仿真抓日志信息" | 埋点/加日志 → 提交 arbe 仿真 → 抓日志/warning trace | 仿真日志 + warning trace CSV | HITL/auto |
| US3 | "要求你自己干活，给最终结论" | 全自动诊断到最终结论（含代码建议） | 最终报告 | auto |
| US4 | "只做原始信号获取，绘制信号图表" | signal-extract（模糊抽取 + 绘图） | 信号曲线 + CSV | HITL |
| US5 | "分析展示代码调用逻辑" | code-analyze（调用链/依赖/语义） | 调用链图/文本 | HITL |
| US6 | "查看触发报警时刻的各种属性信息" | 报警时刻对象/信号/状态全属性快照 | 报警时刻属性表 | HITL |
| US7 | **数据不全兜底**（只有 bag 或只有 blf） | 数据不足时降级分析，**不得抛错终止进程** | 可用子集 + 明确"数据不足"提示 | 任意 |

#### 3.4.3 设计含义（模块拆分与交互的驱动）

1. **能力必须可独立工作**（US4/US5/US6 只调一个能力就能出结果）——印证模块化拆分方向。
2. **能力必须可编排成不同深度的任务**：初步分析（浅）→ 完整诊断（深）→ 仿真验证（加日志）→ 最终报告——pi 按用户指令组合。
3. **中间产物是一等公民**：每步输出可查看/确认/续作，不只在最后给报告。
4. **HITL/auto 是可配置的交互策略**，不是两种系统——pi 对话层实现。
5. **数据不全必须优雅降级**：bag-only（无 CAN）仍可分析雷达内部；blf-only（无雷达内部）仍可分析 CAN；缺 DBC/代码/需求各自降级为"可用能力子集"，并明确标注"数据不足"。

### 3.5 用户故事调研结论（2026-08-21 对现有代码的支撑度核查）

> 针对 §3.4 用户故事，核查现有代码支撑度，找出 pi 重构必须补齐的缺口。

#### 3.5.1 数据不全降级（US7）—— 现有代码已优雅降级，但缺顶层标识

**结论：现有管线对 bag-only/blf-only/无DBC/无源码 均不崩溃、优雅降级**（load_case_data 从不因缺文件 raise；test_window_detector/data_probe/signal_audit/suppression 对空 store 均降级；codegraph/conditions 对缺源码静默跳过）。**但降级是"静默"的**——bag-only 会产出 CAN 段全空的"看似正常"报告，无统一"数据不足"标识。

**须补**：
- 解析后立即做 `data_availability` 分类（has_bag/has_can/has_dbc/has_radar_objects/has_source）→ 顶层 banner + 注入专家面板 `DATA_AVAILABILITY` 提示（防止 LLM 基于空表过度断言）。
- 报告头加 `data_gaps` 段（缺失 BAG/BLF/DBC/source）。
- **修复 bug**：`orchestrator.py:1144` 引用未赋值 `probe_results`（应为 `probe_results_list`），导致 `diagnosis_bundle.json` 从未真正保存。

#### 3.5.2 HITL 交互（US1/US2/US4/US5/US6）—— 现有无人在环机制，pi steer 可支撑

**现状**：
- 管线内**无 input()/prompt**；`ask_human` 是**半成品暂停原语**（`AgentLoop` 遇 `ask_human` 暂停记录 `pending_input`、`ReActPlanner` 传播 `input_required`，但**无提示、无恢复、未注册 AskHumanTool**）。
- 中间产物**只在最后 report.md/html 呈现**，中途仅文本状态行（on_status）。
- **autonomous 已完整支持**（`-p -e` 一次跑完 8 步）。

**pi 支撑**：pi RPC 的 **steer**（运行时注入用户决定）天然支撑 HITL；当前 `PiBridge`/`PiModule` 已实现基础 prompt、batch、interactive 和事件流，审批/长时 runtime 仍由后续 RunSupervisor 接管。

**须补**：
- **分步交互循环**：跑有界子计划 → 产出中间产物 → 暂停等用户决定 → 继续（pi steer + ask-user 工具 + 恢复路径）。
- **每步产物通道**：per-step artifact 发射（结构化 ModuleResult/artifacts 呈现给用户，而非仅状态文本）。
- **AskHumanTool**：注册真实工具（用 pi 的 steer/`ctx.ui` 或 CLI input 实现提示+恢复）。
- **autonomous 保真**：保留无交互路径（pi --batch 或 no-steering 标志）；8 步 `diag` 保持可调用工具（能力不退步）。

#### 3.5.3 关键 bug 与缺口清单（pi 重构必须修/补）

| # | 项 | 位置 | 影响 |
|---|----|------|------|
| B1 | `probe_results` 未赋值 | `orchestrator.py:1144` | `diagnosis_bundle.json` 从不保存（被 try/except 吞） |
| B2 | `_run_frame_analysis_with` 的 router.chat 未包装 | `orchestrator.py:2330` | LLM 失败会中止整个诊断（唯一未包装 LLM 调用） |
| G1 | 无顶层 data_availability 标识 | 解析后 | 数据不足时产出"看似正常"空报告 |
| G2 | 无 per-step artifact 通道 | 全管线 | 中间产物无法在最终报告前呈现 |
| G3 | AskHumanTool 未注册/无恢复 | `ai/tools/` | HITL 无法真正实现 |
| G4 | plot 仅支持 CAN | `tools/plot_signals.py` | bag-only（无 CAN）时无法画雷达内部/对象曲线 |
| G5 | tree-sitter 不在 requirements.txt | `requirements.txt` | 新机器（Linux/CI）无法安装，codegraph import 崩溃 |

---

## 4. 架构决策记录

### 4.1 已确认决策 [D]

| # | 决策 | 内容 |
|---|------|------|
| D1 | pi = 统一对话入口与调度中枢 | 用户自然语言 → 意图理解 → 规划 → 组合调度各能力模块 → 综合输出；基于现有 ReActPlanner + AgentLoop + agent_tool_registry 强化 |
| D2 | 能力模块插件化 | 每个能力是独立 `BaseModule`（独立 CLI + run()→ModuleResult + 注册为 pi 工具），可独立运行，可被 pi 组合 |
| D3 | Pi 用 Extension/registerTool 封装能力 | Pi tool 使用原生 `registerTool`；Python 侧复用 `Engine + BaseTool + BaseModule`，通过 catalog 和 `pi_tool_bridge` 接入，不新增平行 CapabilityModule 协议，也不硬编码功能 |
| D4 | 固定 8 步诊断管线保留为能力之一 | `diag` 模块包装 Orchestrator.run_diagnosis；不再是唯一入口 |
| D5 | 数据准确性硬原则 | DataStore 带 provenance + signal_valid；无效占位数据不参与判定（见 §2 教训） |
| D6 | 知识仅定位，不判定 | 缓存知识（L6/manifest/记忆）用于快速定位排查范围；判定看**最新代码** + **准确数据**；证据分级 localization_hint vs deterministic_evidence |
| D7 | arbe 先抽象接口，远程后接 | 先定义 ArbeReplayProvider 接口 + 本地解析 trace CSV；SSH 远程执行后续实现 |
| D8 | 分层架构 | L4 pi 交互中枢 / L3 编排 / L2 能力模块 / L1 数据统一 / L0 数据源（见 V4_PI_DRIVEN_ARCHITECTURE.md §2） |

### 4.2 待确认 [TBD]

- （暂无）

### 4.3 待调研 [R]

| # | 待调研项 | 状态 |
|---|---------|------|
| R1 | **代码学习技术栈**：相比"预生成 md + json 结构化内容"，是否有更好方式？需参考社区方案（tree-sitter AST、代码图谱、按需检索、embeddings 等） | ✅ 已完成调研，结论见 §5.2/§5.3 |
| R2 | **pi 具体含义/SDK** | ✅ **已确认：pi = https://pi.dev/（earendil-works/pi），Earendil 的 minimal agent harness**。本机已装 pi 0.84.2。详见 §5.4 与 `V4_PI_BASED_PLAN.md` |

### 4.4 pi 相关决策 [D-PI]

| # | 决策 | 内容 |
|---|------|------|
| D-PI-1 | **Pi 作为统一对话中枢与 AI 调度器** | `pi --mode rpc`（JSON-over-stdio）由 radarAnalyze 驱动；radarAnalyze 保留全部确定性能力并暴露为 pi 工具。现有 ReActPlanner 保留为离线/无 pi 环境的降级路径（不删除）。 |
| D-PI-2 | **Pi Extension tool 是产品工具契约** | 可被 Pi 编排的能力通过 TS Extension 的 `registerTool` 暴露；Python `BaseTool`/`BaseModule` 是实现层，独立 CLI 只用于开发、测试和 bridge 进程边界，不是并列的用户编排入口。 |
| D-PI-3 | **能力天然 JSON-in/JSON-out** | 所有 Pi tool 通过统一 `ai.capability.pi_tool_bridge` 调用 `BaseTool.safe_execute()` 或 `BaseModule` adapter，返回统一 envelope；Extension 不复制业务逻辑，也不依赖每个模块各自的 CLI 参数。 |
| D-PI-4 | **扩展自动生成且显式绑定当前项目** | `scripts/gen_pi_extension.py` 扫描 registry 生成 `registerTool`；`PiBridge` 显式加载当前项目生成物并把 params JSON 转发给 bridge。新增 leaf 能力无需修改总编排器。 |
| D-PI-5 | **pi 会话绑定项目** | `--session-dir <workspace>/sessions/<project>`，支撑多项目隔离（D16）。 |
| D-PI-6 | **能力封装三件套（修正，复用现有）** | 新能力的确定性实现放在 `engines/<name>.py`；需要被 Agent/Pi 直接消费时实现/适配 `BaseTool`；需要独立 CLI 或较大工作流时保留 `BaseModule`。不另起一套 CapabilityModule 协议。 |
| D-PI-7 | **provider/model 可配置，默认遵循已验证的 Bosch 配置** | PiBridge 支持显式 provider/model；默认值由当前已验证的 Bosch Pi 配置提供，无法使用时按策略返回结构化错误/进入离线 fallback，不把本地模型可用性假设成事实。 |
| D-PI-8 | **pi 工具单一来源 = BaseTool** | pi `registerTool` 的 name/description/parameters_schema 直接取自现有 `BaseTool`；radarAnalyze 提供本地 `tool-bridge`（`python -m ai.tools.bridge --tool <name> --json <params>` → `BaseTool.safe_execute()`），TS 壳统一调它。pi 与现有 AgentLoop 用同一套工具。 |
| D-PI-9 | **pi 中心架构：pi = 唯一入口 + 整体调度中枢** | **用户明确纠正**："如果要用 pi 重构，那就要用 pi 做入口，做整体调度。" 因此 Pi 作为唯一产品入口，全部业务能力注册为 Pi tools；`ReActPlanner`/`AgentLoop` 仅保留为 Pi 不可用、离线和确定性回归的 fallback，不作为并行产品流程。固定 8 步诊断管线 = `diag` tool，内部仍走 orchestrator。 |
| D-PI-10 | **能力即工具（tool-as-capability）** | 每个能力以 `BaseTool` 注册（`registerTool`），pi 的 LLM 直接调用；`tool-bridge` 让 pi 扩展与 Python 能力层对接。pi 的工具目录 = radarAnalyze `MODULE_REGISTRY` + `ai/tools` 的 BaseTool 注册表（单一来源）。 |
| D-PI-11 | **能力不退步 + 提速（重构验收红线）** | 用户明确："用 pi 组织起来，原来的核心能力和更新后的要求，能力不能退步，速度也要提升。现有能力可以用 pi 的机制重构起来，重构的更灵活和独立。" → ①现有能力全量映射到 pi skill/tool（11 模块 + 6 工具 + 8 步管线逐一核对，一个不落）；②提速：并行调度/激活 AST/会话复用/tool-bridge 直连/按需检索/缓存增量；③验收：`pytest` 全绿 + harness gate 通过 + 既有模块独立 CLI 可用 = 能力不退步；单次诊断不慢于现有（目标持平或更快）。 |
| D-PI-12 | **pi 使用已验证/可配置的模型端点** | 当前机器在 2026-08-27 的 `pi --list-models` 显示 `bosch-qwen3_6 / Qwen3.5-27B-FP16`（旧文档中的 `bosch-qwen35` 别名已失效）。PiBridge 优先使用显式参数或 `CR60_PI_PROVIDER`/`CR60_PI_MODEL`，未指定 provider 时只读探测 `pi --list-models` 选择精确 model；不能把 provider 名称硬编码成跨用户契约。 |
| D-PI-13 | **PiRunContext 作为编排上下文** | 每次 Pi run 绑定 `pi-orchestration-context.v1`，承载 project/variant、case、source/binary、runtime、policy、artifact refs 和 freshness；工具只能追加 artifact，不得覆盖权威身份和 fingerprint。 |
| D-PI-14 | **DDD 文档先于实现** | 用户故事、FR、AC 和追踪矩阵是代码变更的前置；无测试/证据的条目只能标记 `specified` 或 `partially-verified`。详见 `CR60_PI_DDD_REQUIREMENTS_AND_ACCEPTANCE.md`。 |

---

## 5. 技术栈原则（社区参考，不闭门造车）

**用户明确要求**：技术栈选择要参考社区成熟项目，不要闭门造车。特别点名：

> "代码学习部分，相比于做 md 文件和 json 结构化内容，是否有更好的方式？"

**原则**：
- [D] 技术选型前先调研社区方案（Sourcegraph/SCIP、CodeQL、tree-sitter、ast-grep、Semgrep、aider repo-map、repomix、embeddings RAG、图数据库等）。
- [D] 不因"已有 md/json 实现"而固守旧方案；若社区有更优范式（如 AST → 图/DB + 按需查询），重新设计 code-learn。
- [R] 待调研完成后，更新 V4 设计中 code-learn 模块（C3）的技术选型章节。

### 5.2 现状审计结论（2026-08-21 调研）

**项目已有 tree-sitter AST 基础，但生产路径未启用。**

| 机制 | 文件 | 状态 |
|------|------|------|
| LLM 提取 | `ai/code_learner.py`（L6 JSON + MD）、`ai/condition_extractor.py`（conditions JSON） | 生产在用（LLM + keyword 切片） |
| 确定性 regex | `ai/rule_condition_extractor.py`、`engines/signal_mapper.py`、`ai/codegraph/analyzer.py` | 生产在用（纯 regex） |
| **tree-sitter AST** | `ai/codegraph/ast_parser.py` + `ast_builder.py` + `state_machine_extractor.py` + `pattern_extractor_ast.py` | **休眠**：`use_ast` 默认 False，生产调用方（orchestrator._build_codegraph、auto_dream._refresh_codegraph）都不传 use_ast=True；AST 模式只在 `scripts/benchmark_ast_vs_regex.py` 跑 |

**关键证据**：regex 建的 codegraph DB（`.workspaces/gen6_byd_sc6h/memory/codegraph/codegraph.db`）只有 FILE/FUNCTION/VARIABLE/CALIB_PARAM/MODULE，**STATE/TRANSITION 边 0 条、READS_SIGNAL/WRITES_SIGNAL 边 0 条、node_semantics 0 行**——信号接口和状态机提取在 regex 下实际产出为空。

**最高杠杆改动**：把 `CodeGraphBuilder(use_ast=True)` 接入生产（或让 AST 成为默认），激活已有的 tree-sitter 信号/状态机/模式提取。切换需验证 tree-sitter + tree-sitter-c 依赖已装、C++ 平台（gen5）需 tree-sitter-cpp。

### 5.3 社区方案调研结论（2026-08-21）

**结论：分层架构优于"预生成 md + json"。**

| 层 | 方案 | 定位 |
|----|------|------|
| **确定性提取层** | tree-sitter / ast-grep / Semgrep 查询 C 源码 | 提取条件/阈值/信号使用/函数签名，**带 file:line provenance + content hash**；可证明穷尽 |
| **索引层** | SQLite + FTS5（如 Continue.dev 模式）或嵌入式图（Kùzu/Cypher） | 存 AST 派生的 nodes/edges；md/json 降为**渲染视图**（从索引再生成，非源） |
| **模糊召回层** | embeddings（sqlite-vec / LanceDB） | 语义查找候选（"哪个函数门控 BSD 报警"）→ 再经结构索引确定性验证 |
| **按需检索** | aider repo-map 式 / Claude Code 式 | 专家面板只给紧凑符号图 + 针对性查询，不整篇贴预生成文档 |

**关键社区参考**：
- aider repo-map：tree-sitter 符号图，按需生成，token 预算切片
- Continue.dev：SQLite FTS5 + LanceDB，tree-sitter 按函数/类分块
- CodeQL / Joern：深度语义查询（数据流/污点），当前场景可能过度，仅在有跨函数数据流需求时引入
- ast-grep / Semgrep：AST 模式匹配，C/C++ 支持，规则可维护可测试

**落地建议**（对应 V4 code-learn 模块）：
1. 激活休眠的 tree-sitter AST（`use_ast=True`），用 AST 查询替代 regex 提取条件/阈值/信号/状态机，带 file:line + hash。
2. 结构索引留在 SQLite（已有 codegraph.db），补 STATE/TRANSITION/SIGNAL 边；md/json 只作报告渲染。
3. 加 embeddings 模糊层（sqlite-vec/LanceDB，复用已有语义记忆基础设施），只作候选召回不作证据源。
4. 专家面板改按需检索（紧凑符号图 + 针对性查询），不整篇贴文档。

> **对齐用户原则**：确定性判定用 AST + 准确数据（可证明），语义/知识只作定位提示（embeddings 召回候选），md/json 仅渲染——完美契合"知识仅定位，不判定"。

### 5.4 pi 调研结论（2026-08-21，实证）

**pi = https://pi.dev/，Earendil 的 "minimal agent harness"（`earendil-works/pi` monorepo）**。

**实证**：本机已装 `pi 0.84.2`（`/d/RamboStar/idea/claudecode/npm/pi`），node v24 / npm 11 可用；`pi --mode rpc` 冒烟通过（进程启动、接受 prompt、返回带 id 的 response、流式事件 agent_start/turn_start/message_start）。

**关键能力**（来自官网 + GitHub 源码 `packages/coding-agent/docs/{rpc,skills,extensions}.md`）：
- **四模式**：交互 TUI / `pi -p "query"` / `--mode json` / **`--mode rpc`（JSON-over-stdio，官方 Python 示例：subprocess.Popen + 逐行 JSON）**
- **Skills**：Agent Skills 标准（`SKILL.md` + scripts/references/assets），按需加载、渐进披露
- **Extensions**：TypeScript 模块，`pi.registerTool()` 注册自定义工具（LLM 可调用）、`pi.registerCommand()`、事件拦截、`ctx.ui` 交互、session 持久化；可热重载（`/reload`）
- **SDK**：`@earendil-works/pi-coding-agent` 的 `AgentSession`（Node.js 嵌入）
- **会话树**：rewind / branch / bookmark / export
- **无内置权限**：强调容器化（Gondolin / Docker / OpenShell）
- **包**：`pi-ai`（统一 LLM API，15+ provider）/ `pi-agent-core`（agent 运行时+工具+状态）/ `pi-coding-agent`（CLI+RPC+扩展）/ `pi-tui` / `pi-telemetry`

**对 radarAnalyze 的意义**：pi 提供成熟对话中枢 + 官方扩展机制（registerTool），radarAnalyze 能力模块以 TS 薄壳注册为 pi 工具；radarAnalyze 用 RPC 驱动 pi。完整方案见 **`V4_PI_BASED_PLAN.md`**（P0-P7 分片，P3 为 pi↔能力接线的端到端里程碑）。

---

## 6. 五层架构（V4 主线）

```
L4 pi 交互中枢  统一对话入口 · 意图理解 · 规划调度 · 综合输出(报告/曲线/建议)
L3 编排         调度引擎(能力注册+执行+聚合) · Orchestrator 8步管线(作为 diag 能力)
L2 能力模块     插件化：signal-extract · data-analyze · code-learn · code-analyze ·
                diag · code-fix · sim-verify · req-analyze(未来) · memory
L1 数据统一     DataProvider SPI + DataStore(provenance/signal_valid/time_sync)
L0 数据源       BLF · ROS bag · MF4 · DBC · 代码仓(项目+分支) · arbe仿真(Linux 10.190.171.44)
```

详见 `V4_PI_DRIVEN_ARCHITECTURE.md`。

---

## 7. 已有产物（截至 2026-08-21）

### 7.1 文档

- `docs/technical/V4_PI_DRIVEN_ARCHITECTURE.md` — 顶层架构设计（已创建）
- `docs/technical/V4_DEVELOPMENT_PLAN.md` — 分片开发计划 S0-S7（已创建，作为拆分参考）
- `docs/technical/V4_PI_BASED_PLAN.md` — **基于 pi 的详细方案设计与实施计划（P0-P7，实施主线）**
- `docs/technical/V4_DESIGN_CONTEXT_AND_DECISIONS.md` — 本文件（需求与决策上下文）

### 7.2 待办

| 项 | 状态 |
|----|------|
| 根 `AGENTS.md` 更新（V4 架构 + pi 入口 + 能力目录） | 已更新 |
| `ai/modules/AGENTS.md` 更新（BaseModule / Pi tool 规范） | 已更新 |
| `ai/capability/AGENTS.md` / `engines/AGENTS.md` | 已创建 |
| `tools/AGENTS.md` 更新（arbe 资产说明） | 待做 |
| **社区技术栈调研（代码学习）** | 已完成第一轮，持续按需验证 |
| code-learn 技术选型更新到 V4 设计 | 待做 |

### 7.3 已拉取资产

- `tools/arbe/` — 从 10.190.171.44 拉取的 arbe 工具链资产（generated_signal_map.py、public_can_signal_publisher.py、visualization_node.cpp、my_rviz_plugin、bag_csv_kpi_*.py、find_triggered_warning_bags.py、FCTB_Batch_Replay_Operation_Guide.md 等）
- 分析脚本：`scripts/_decode_publiccan.py`、`scripts/_scan_rctb*.py`、`scripts/_scan_ctx*.py`、`scripts/_validate_fields.py`、`scripts/_scan_internal.py`、`scripts/_msgdef_{rear,front}_signals.txt`

---

## 8. arbe 工具链理解（供 sim-verify 模块参考）

**关键事实**（来自 10.190.171.44 调研 + `tools/arbe/`）：

| 组件 | 作用 |
|------|------|
| `common_can_signal_publisher` | 从 DBC 生成 PublicCan 信号字典（`generated_signal_map.py` + bag 内嵌 msgdef），读真实 CAN 发布 front/rear signals；**bag 回放时输出占位值** |
| `visualization_node.cpp` | 订阅 lgu_data → 离线重跑算法 → 发布 warning_status（16 数组）；`corner_radar_post_process_data_callback` 是关键 |
| `my_rviz_plugin` / `bag_reader.cpp` | bag 回放插件（读 bag、按帧发布 lgu_data/camera/car/ego） |
| `bag_csv_kpi_framesync.py` / `bag_csv_kpi_batch.py` | KPI 统计 + warning trace 抽取 |
| `find_triggered_warning_bags.py` | 找触发警告的 bag |
| bag-only 回灌模式 | 不需要真值 CSV，批量回放每个 bag 产出 `_algo_warning_trace.csv`（event_sec, radar_id, w1..w15，w14=LeftFctb, w15=RightFctb）+ `batch_fctb_trigger_report.csv` |
| 操作 | `FCTB_Batch_Replay_Operation_Guide.md`：Select Folder → 取消 KPI Batch Mode → Start KPI Batch → 输出 fctb_reports_*/batch_fctb_trigger_report.csv |

**环境**：Linux 10.190.171.44，工作区 `~/CR60LIGHT/cr60_light_arbe/`，SSH 免密；`bash start` 启动 GUI（RViz + arbe GUI）。skill `cr60light-arbe-build` 覆盖切分支/编译/启动流程。

**对设计的启示**：sim-verify / arbe-replay 模块可解析 `_algo_warning_trace.csv` 归一进 DataStore；远程执行走 SSH（后续实现）。

---

## 9. 开放问题 / 待澄清（与用户）

1. [TBD] "使用 pi 的 SDK 和扩展能力做模块重构" —— pi 具体指什么 SDK？是否指现有 `ai/agent/`（ReActPlanner + AgentLoop + agent_tool_registry）作为基础设施，还是外部某个 pi 平台/产品？需与用户确认，避免设计错位。
2. [TBD] 代码学习技术栈调研结论落地（见 R1），是否用 AST/图/按需检索取代 md+json。

## 9.1 设计必须覆盖的维度（用户 2026-08-21 补充）

用户明确要求 V4 设计必须覆盖以下维度，做任何设计/方案时逐项检查，避免遗漏：

| # | 维度 | 要点 | 对应 V4 文档章节 |
|---|------|------|-----------------|
| D9 | **顶层框架设计** | 整体架构骨架、分层、数据流主线 | §2 五层架构 |
| D10 | **模块化设计** | 能力模块插件化、独立可运行、可组合 | §4 能力 SDK + §5 模块目录 |
| D11 | **能力边界** | 每个能力模块的职责边界、输入/输出契约、与其他模块的依赖与隔离；防止职责重叠 | §7 核心模块详设 + 新增"能力边界" |
| D12 | **交互** | pi 对话交互、CLI、模块间数据流、人机交互界面（报告/曲线/建议）、多轮对话状态 | §3 pi 中枢 + §9 交互层 + 新增"交互设计" |
| D13 | **多项目适配** | 多车型/多客户项目适配：variant 体系、项目配置、数据源/代码仓/需求切换 | 新增"多项目适配" |
| D14 | **记忆机制** | 记忆如何写入/读取/更新/失效；与 pi 调度结合；知识沉淀与 freshness | 新增"记忆机制" |
| D15 | **记忆分层** | 记忆分层（L1-L6 已有）+ 能力平台的记忆分层设计；知识与数据分层 | 新增"记忆分层" |
| D16 | **多项目记忆/数据隔离** | 不同项目的记忆、数据、知识必须隔离防串扰；workspace 隔离机制 | 新增"多项目隔离" |

> **检查规则**：完成任何 V4 设计/方案后，对照上表逐项核对，未覆盖的维度必须补上。

---

## 10. 变更日志

| 日期 | 变更 |
|------|------|
| 2026-08-21 | 初始版本：记录问题背景、QZH 教训、能力愿景、架构决策、技术栈原则、产物清单、arbe 理解、开放问题 |
| 2026-08-21 | 追加 §5.2 现状审计结论 + §5.3 社区调研结论（code-learn 技术选型）；追加 §9.1 设计必须覆盖的维度（D9-D16） |
| 2026-08-21 | **pi 调研实证**：确认 pi = pi.dev（earendil-works/pi），本机 0.84.2，RPC 冒烟通过；新增 §4.4 pi 决策（D-PI-1..5）、§5.4 pi 调研结论；新增 `V4_PI_BASED_PLAN.md`（P0-P7 实施主线） |
| 2026-08-21 | **设计自审修正**：结合代码现状核查发现初版 `CapabilityModule` 与现有 `BaseTool` 契约重叠（另起炉灶风险）；新增 D-PI-6 三件套复用（engines+BaseTool+BaseModule）、D-PI-7 ollama provider、D-PI-8 BaseTool 单一来源；`V4_PI_BASED_PLAN.md` §2.5 记入修正 |
| 2026-08-21 | **架构定稿（pi 中心）**：用户纠正"若用 pi 重构，pi 应做入口 + 整体调度"。D-PI-9 从"双线并存"改为 **pi = 唯一入口 + 整体调度中枢**，能力即工具（D-PI-10）；ReActPlanner 退役为本地兜底；8 步管线 = `diag` 工具。`V4_PI_BASED_PLAN.md` §2.1b/§6/§7 同步更新 |
| 2026-08-21 | **能力不退步 + 提速红线**：D-PI-11（能力全量映射到 pi skill/tool + 提速策略 + 验收红线）、D-PI-12（当时记录的 Bosch Qwen 模型端点实证；provider 名称后续以当前 Pi 配置探测为准）。`V4_PI_BASED_PLAN.md` 新增 §2.6 能力映射与提速、§4.1 provider 实证 |
| 2026-08-21 | **用户故事驱动的设计补齐（用户指出未先收集需求）**：§3.4 用户故事（US1-US7：初步分析/加日志仿真/自主结论/原始信号绘图/代码调用逻辑/报警时刻属性/数据不全兜底）+ 两种工作模式（HITL/autonomous）；§3.5 调研结论（数据降级已优雅但静默、HITL 半成品、bug B1/B2、缺口 G1-G5）。`V4_PI_BASED_PLAN.md` 新增 §2.7 交互与降级设计 + 分片 P2b（修 bug + HITL 基座）+ §6 顺序更新 |
| 2026-08-24 | [R] 实际 ROS/rosbag 诊断工具框架探索：补充远程 session/replay/debug adapter、bag/msgdef/provenance、radar/target/frame 选择、100-200 帧连续预热契约、GDB target/PID 映射、条件证据五态、A2L/XCP 调参边界和失败降级规则；具体记录见 `docs/ros_debug/ROS_DEBUG_DIAGNOSTIC_TOOL_FRAMEWORK.md` 与样例探索附录。 |
| 2026-08-24 | [R] 独立项目边界评估：`radarAnalyze` 作为可选 deterministic analysis/pi provider，实际 Linux/ROS debug 脚手架独立维护；代码链路采用 source snapshot + compile profile + AST/规则索引，LLM 仅做解释，不作为数据真值。 |
