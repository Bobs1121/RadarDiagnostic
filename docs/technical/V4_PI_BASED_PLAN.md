# V4 · 基于 Pi 的详细方案设计与实施计划

> **版本**: 4.2 · **日期**: 2026-08-27
> **前置**: `V4_PI_DRIVEN_ARCHITECTURE.md`（顶层架构）· `V4_DESIGN_CONTEXT_AND_DECISIONS.md`（需求基线）
> **本文件定位**: 在顶层设计之上，**基于 Pi（https://pi.dev/，earendil-works/pi）落地为可实施、可验证的详细方案**——明确 pi 与 radarAnalyze 的接线方式、能力封装机制、分片实施与验收。

---

## 1. Pi 是什么（调研实证结论）

> **实证**: 本机已装 `pi 0.84.2`（`/d/RamboStar/idea/claudecode/npm/pi`），node v24 / npm 11 可用；`pi --mode rpc` 已在本机冒烟验证通过（进程启动、接受 prompt、返回带 id 的 response、流式事件）。

**Pi = "minimal agent harness"（Earendil Inc.）**——一个自可扩展的编码 Agent，提供：

| 能力 | 说明 |
|------|------|
| **四模式** | 交互 TUI / `pi -p "query"` 脚本 / `--mode json` 事件流 / `--mode rpc` JSON-over-stdio（非 Node 集成） |
| **统一 LLM API** | 15+ provider、数百模型（anthropic/openai/google/ollama…），可中途切换 |
| **Skills** | Agent Skills 标准能力包（`SKILL.md` + scripts/references/assets），按需加载、渐进披露 |
| **Extensions** | TypeScript 模块：`pi.registerTool()` 注册自定义工具（LLM 可调用）、`pi.registerCommand()`、事件拦截、`ctx.ui` 交互、session 持久化 |
| **SDK** | `@earendil-works/pi-coding-agent` 的 `AgentSession`（Node.js 嵌入）；RPC 供非 Node 集成 |
| **会话树** | rewind / branch / bookmark / export HTML / share |
| **上下文工程** | AGENTS.md 项目指令 + SYSTEM.md 覆盖 + 自定义 compaction + 动态上下文注入 |
| **无内置权限** | 强调容器化边界（Gondolin / Docker / OpenShell） |

**架构包**（monorepo `earendil-works/pi`）：
- `@earendil-works/pi-ai` — 统一多 provider LLM API
- `@earendil-works/pi-agent-core` — agent 运行时 + 工具调用 + 状态管理
- `@earendil-works/pi-coding-agent` — 交互编码 Agent CLI（含 RPC/JSON/扩展）
- `@earendil-works/pi-tui` — 终端 UI 库
- `@earendil-works/pi-telemetry` — 厂商中立遥测

---

## 2. Pi 与 radarAnalyze 的接线设计（核心决策）

### 2.1 分工

| 层 | 归属 | 职责 |
|----|------|------|
| **对话中枢 / AI 调度** | **Pi**（`--mode rpc`） | 统一对话入口、意图理解、ReAct 规划、多轮会话、模型路由 |
| **确定性能力引擎** | **radarAnalyze**（现有 engines/ + 新能力模块） | 数据解析、信号抽取、诊断、代码分析、仿真验证——全部确定性、可复现、带 provenance |
| **接线层** | **新增 pi-bridge**（Python + TS 薄壳） | 让 pi 的 LLM 能调用 radarAnalyze 能力模块，并让 radarAnalyze 能驱动 pi |

### 2.1b pi 中心架构（D-PI-9：pi = 唯一入口 + 整体调度中枢）

> **用户明确**："如果要用 pi 重构，那就要用 pi 做入口，做整体调度。" 据此，pi 不是"第二入口"，而是**唯一对话入口与整体调度中枢**。

```
                    ┌──────────────────────────────────────┐
                    │  用户（唯一对话入口）                  │
                    └──────────────────┬───────────────────┘
                                       │
                    ┌──────────────────▼───────────────────┐
                    │  Pi（入口 + 整体调度中枢）             │
                    │  · 意图理解 → 规划 → 调度 → 多轮综合   │
                    │  · 会话树 / 流式 / 模型路由            │
                    │  · 注册的工具 = radarAnalyze 全部能力  │
                    └──────────────────┬───────────────────┘
                                       │ registerTool（tool-as-capability）
                    ┌──────────────────▼───────────────────┐
                    │  tool-bridge（JSON 契约，单一来源 BaseTool）│
                    └──────────────────┬───────────────────┘
                                       │
        ┌──────────────────────────────┼──────────────────────────────┐
        │                              │                              │
┌───────▼──────┐  ┌────────────────────▼─────┐  ┌─────────────────────┐
│ signal-extract│  │ data-analyze · code-learn│  │ diag(8步管线) ·      │
│ data-probe   │  │ code-analyze · code-fix  │  │ sim-verify ·         │
│ (BaseTool)   │  │ req-analyze · memory     │  │ memory               │
└──────────────┘  └──────────────────────────┘  └─────────────────────┘
        │              （全部经 BaseTool 注册，共享 DataStore）
        └────────────── DataStore（provenance/signal_valid/多项目隔离/记忆分层）
```

**架构要点**：
- **pi = 唯一入口 + 整体调度**：用户只跟 pi 对话；pi 负责意图理解、规划、按序调用工具、多轮追问、综合输出。
- **能力即工具（tool-as-capability）**：radarAnalyze 的每个能力注册为 `BaseTool` → pi `registerTool`；pi 的 LLM 直接调度它们。能力层保持确定性、可复现、带 provenance。
- **`ReActPlanner`/`AgentLoop` 退役**：不再作为并行入口；仅在 pi 不可用/离线/无网络时作**本地兜底**（保持可用但不作为主架构）。
- **8 步管线 = `diag` 工具**：`Orchestrator.run_diagnosis` 包装为一个 pi 可调用的工具，pi 按需调用（用户说"完整诊断"时），也可只调子能力。
- **多项目/记忆/隔离**：pi 会话树 + `--session-dir <workspace>/sessions/<project>` 绑定项目；记忆/知识/索引隔离沿用 §14。

### 2.2 接线方式（两条互补通道）

```
┌─────────────────────────────────────────────────────────┐
│  Pi（对话中枢，--mode rpc，JSON-over-stdio）              │
│  · 用户问题 → 意图 → 规划 → 调度工具 → 综合回答           │
│  · 注册的 tool = radarAnalyze 能力模块                    │
└──────────────────────────┬──────────────────────────────┘
                           │
             ① RPC 驱动（radarAnalyze→pi）
             subprocess: pi --mode rpc
             Python 发 prompt / 收事件流
                           │
             ② Extension tools（pi→radarAnalyze）
             TS 扩展 registerTool("signal_extract", ...)
             execute → 调 Python CLI / 桥接服务
                           │
┌──────────────────────────▼──────────────────────────────┐
│  radarAnalyze（确定性能力层）                             │
│  MODULE_REGISTRY：signal-extract / data-analyze /        │
│  code-learn / code-analyze / diag / code-fix /           │
│  sim-verify / req-analyze / memory                       │
│  DataStore（provenance + signal_valid）+ engines/         │
└──────────────────────────────────────────────────────────┘
```

### 2.3 为什么用 Pi 做中枢（而非自研/现有 ReActPlanner）

| 对比项 | 现有 ReActPlanner | Pi（0.84.2） |
|--------|------------------|--------------|
| 成熟度 | 项目内单文件 | 社区成熟 monorepo，15+ provider |
| 对话体验 | 无 TUI/会话树 | TUI + 会话树（rewind/branch/bookmark/export） |
| 扩展机制 | 手写 agent_tool_registry | 官方 `registerTool()` + Skills 标准 |
| 多轮/流式 | 手动 | 内建 streaming/steering/follow_up |
| 维护成本 | 自维护 | 社区维护 + `pi update` |

**决策 [D-PI-1]**：**Pi 作为统一对话中枢与 AI 调度器**（`--mode rpc` 由 radarAnalyze 驱动）；radarAnalyze 保留全部确定性能力并暴露为 pi 工具。现有 `ReActPlanner` 保留为**离线/无 pi 环境的降级路径**（不删除）。

**决策 [D-PI-2]**：radarAnalyze 的能力模块**以 pi Extension tool 的形式**暴露给 pi（TS 薄壳 → 调 Python 能力模块），同时保留**独立 CLI 直连**（不经过 pi）。

---

## 2.5 设计自审修正（2026-08-21 结合代码现状核查）

> **结论**：初版设计在"能力封装"上有**另起炉灶的风险**——计划新增的 `CapabilityModule` 与项目已有的 `BaseTool` 契约高度重叠。核查现状后修正为**复用现有三件套**，彻底重构而非新增平行体系。

**代码现状核查**：

| 现有资产 | 位置 | 状态 |
|----------|------|------|
| `BaseTool`（统一 JSON 契约 `{status,message,data,artifacts}` + `safe_execute` + `parameters_schema` JSON-schema 校验） | `ai/tools/base.py` | ✅ 已有，正是 agent/pi 工具契约 |
| 确定性工具（`QueryCanDataTool`/`PlotSignalTool`/`DetectTimePatternTool`） | `ai/tools/data_tools.py` | ✅ 已有，signal-extract 应复用/增强 |
| 代码工具（`FindCodeDefinitionTool`/`ExtractASTDependencyTool`/`TraceRequirementTool`） | `ai/tools/code_tools.py` | ✅ 已有 |
| `AgentLoop` 调工具（`tool.safe_execute()`） | `ai/agent_loop.py` | ✅ 已有，pi 可复用同一契约 |
| `BaseModule`/`ModuleResult`（CLI/独立运行壳） | `ai/modules/base.py` | ✅ 已有 |
| `MODULE_REGISTRY`（11 个模块：agent-loop/react-agent/code-structure/signal-bridge/diagnosis-panel/bsd-data-bridge/signal-audit 等） | `ai/modules/__init__.py` | ✅ 已有 |
| `engines/*`（确定性实现） | `engines/` | ✅ 已有 |
| 能力模块范式（`SignalBridgeModule` = BaseModule 包装 `engines/signal_mapper`） | `ai/modules/signal_bridge.py` | ✅ 已有，是正确范式 |

**修正决策 [D-PI-6]（能力封装三件套，取代"另起 CapabilityModule"）**：

```
新能力 = engines/<name>.py（确定性实现）
       + ai/tools/<name>_tool.py（BaseTool 子类：agent/pi 可调用）
       + ai/modules/<name>.py（BaseModule 子类：独立 CLI / safe_run）
       + 注册 MODULE_REGISTRY（能力清单 → pi 工具目录自动发现）
```

- **能力 → pi 工具**：Pi 的 `registerTool` 是产品入口，字段来自统一 catalog；生成的 TS 壳不承载业务逻辑，只把 `params` 作为独立 JSON 参数转发到 `ai.capability.pi_tool_bridge`，再由 bridge 调 `BaseTool.safe_execute()` 或 `BaseModule` adapter。这样不会因 shell 引号/路径空格丢参，也不会产生第二套业务协议。
- **`signal-extract` 不做全新实现**：基于现有 `PlotSignalTool` + `QueryCanDataTool` + `engines/signal_mapper` 增强（加模糊匹配/跨源对齐），包装为 `BaseModule` 暴露 CLI。
- **现有 11 个 MODULE_REGISTRY 模块**映射到能力目录：`signal-bridge`→code-learn 部分、`data-explore`→data-analyze、`diagnosis-panel`→diag、`signal-audit`→data-analyze 审计子集等。**不删除**，作为能力实现继续存在；pi 工具目录 = MODULE_REGISTRY 扫描结果。
- **`gen_pi_extension.py` 改为扫描 `BaseTool` + `BaseModule` 注册表**生成 registerTool 块（不再是新 CapabilityModule）。

> 这一修正让"能力"与"现有工具/模块"统一：**新增能力 = 现有三件套各加一个文件 + 注册**，彻底复用，无平行体系。

---

## 2.6 能力不退步 + 提速（D-PI-11 硬约束）

> **用户明确**："用 pi 组织起来，我原来的核心能力和更新后的各种要求，能力不能退步，速度也要提升。现有能力可以用 pi 的机制重构起来，重构的更灵活和独立。"
>
> 这是重构的**验收红线**：pi 重构后，现有能力一个不丢、行为不降级；同时整体更快。

### 2.6.1 现有能力全量盘点 → pi skill/tool 映射（保证不退步）

**pi 的两种能力重构机制**：
- **Skill**（`SKILL.md` + scripts）＝ 独立能力包（工作流/指令/参考），渐进披露、按需加载——适合**能力独立化、更灵活**
- **Tool**（`registerTool`，来源 `BaseTool`）＝ LLM 可直接调用的确定性工具——适合**可组合的原子能力**

**现有能力 → pi 机制映射**（逐项核对，一个不落）：

| 现有能力 | 位置 | pi 机制 | 说明 |
|----------|------|---------|------|
| **8 步诊断管线**（init→classify→extract→evidence→signals→diagnose→fix→deliver） | `ai/orchestrator.py` `run_diagnosis` | **Tool `diag`** | 完整诊断保留为 pi 可调用工具；内部可再拆子步骤为工具 |
| **signal-bridge**（CAN↔内部变量映射） | `ai/modules/signal_bridge.py` + `engines/signal_mapper.py` | **Tool `signal_bridge`** | 确定性，保留 |
| **data-explore**（数据探针） | `ai/modules/data_diagnostics.py` + `engines/data_probe.py` | **Tool `data_probe`** | 保留 |
| **diagnosis-panel**（独立诊断面板） | `ai/modules/diagnosis_panel.py` | **Tool `diagnose`** | 保留 |
| **signal-audit**（信号契约审计） | `ai/modules/signal_audit.py` + `engines/signal_audit.py` | **Tool `signal_audit`** | 保留 |
| **bsd-data-bridge**（BSD 条件验证） | `ai/modules/bsd_data_bridge.py` | **Tool `bsd_data_bridge`** | 保留 |
| **code-structure**（代码结构化） | `ai/modules/code_structure.py` + `ai/codegraph/` | **Tool `code_analyze`** | 保留，AST 激活增强 |
| **code-review**（代码 review） | `ai/modules/code_review.py` | **Tool `code_review`** | 保留 |
| **req-review**（需求审查） | `ai/requirements/` + `core/materials.py` | **Skill `req_review` + Tool** | 保留，未来 req-analyze 增强 |
| **project-init**（项目接入） | `ai/modules/project_init.py` | **Skill `project_init`** | 保留 |
| **agent-loop / react-agent**（ReAct 工具循环） | `ai/agent_loop.py` + `ai/agent/react_planner.py` | **退役为本地兜底** | 不再作为主入口；pi 不可用时兜底 |
| **QueryCanData/PlotSignal/DetectTimePattern/FindCodeDefinition/ExtractASTDependency/TraceRequirement** | `ai/tools/*.py` | **Tool（直接 registerTool）** | 全部保留 |
| **memory 系统**（L1-L6 + 语义） | `memory/` | **Skill `memory`** | 保留，多项目隔离 |
| **Auto Dream / code learning**（知识沉淀） | `memory/auto_dream.py` + `ai/code_learner.py` | **Skill `auto_dream` + Tool** | 保留 |

> **验收红线（P7）**：`pytest tests/` 全绿 + `tools/run_harness_gate.py` 通过 + 每个既有模块仍可独立 CLI 调用——证明"能力不退步"。

### 2.6.2 速度提升策略

**现状速度瓶颈**（重构前）：
- 8 步管线**串行**跑多个 LLM 调用（classify 1 + conditions 1 + probe 1 + expert panel 3 轮 + fix 1 ≈ 7+ 次 LLM）
- 每次诊断 `_ensure_source_docs` 可能重建 codegraph（regex 慢且信号/状态机边缺失）
- 无并行、无缓存复用

**pi 重构提速点**：

| 提速策略 | 机制 | 预期收益 |
|----------|------|---------|
| **并行工具调度** | pi 的 AgentLoop/ReAct 可并行执行独立工具（如 conditions + TPE + probe 并行，现有 Step 4 已是 ThreadPool 可保留） | 减少串行等待 |
| **激活 tree-sitter AST** | codegraph `use_ast=True`（信号/状态机边真正产出），替换 regex 低效路径 | 建图更快 + 能力更强 |
| **pi 会话复用** | pi 会话树/rewind：同一项目多问题复用上下文，不重复建码/加载 | 多轮提速 |
| **tool-bridge 直连** | BaseTool 直接调用（不落盘、不经 CLI 解析） | 工具调用开销↓ |
| **按需检索** | 专家面板只给紧凑符号图 + 针对性查询（社区 repo-map 模式），不整篇贴文档 | 上下文↓ → 生成↓ → 更快 |
| **模型直连** | PiBridge 使用显式/环境配置的 provider/model；未指定 provider 时只读执行 `pi --list-models` 按精确 model 选择当前可用 Bosch entry | 不引入固定 provider 假设 |
| **缓存/增量** | codegraph/conditions/signal_mapping 增量重建 + freshness 命中跳过 | 首访慢、复访快 |

**速度验收**（P7）：
- 单次"抽信号+绘图"：pi 调度 `signal_extract` 完成时间 ≤ 现有手动流程
- 单次完整诊断：pi 调度 `diag` 不比现有 `run_diagnosis` 慢（目标持平或更快）
- 二次访问（缓存命中）：显著快于首访

### 2.6.3 pi provider 实证（复用现有模型，能力不退步）

- 当前机器 2026-08-27 的 `pi --list-models` 显示 **`bosch-qwen3_6 / Qwen3.5-27B-FP16`**；旧记录中的 `bosch-qwen35` 不是当前有效 provider 名称。
- PiBridge 优先使用构造参数或 `CR60_PI_PROVIDER`/`CR60_PI_MODEL`；未指定 provider 时只读探测 `pi --list-models`，按精确 model 选择 Bosch entry。
- 其他用户/服务器必须通过配置或环境变量绑定 provider/model；如果本机 Pi 没有匹配项，返回结构化错误或由外层选择已批准的 fallback。
- 本机 ollama（deepseek-r1:8b）作为**离线兜底**。

---

## 2.7 用户故事驱动的交互与降级设计（US1-US7）

> **用户明确**：之前设计未先收集/确认用户故事与业务需求。本节将 §3.4（上下文文档）的用户故事落到交互模式、中间产物呈现与数据降级设计。详见上下文文档 §3.4/§3.5 调研结论。

### 2.7.1 两种工作模式（HITL / autonomous）

```
人在环中（HITL，默认）：          人在环外（autonomous，可切换）：
用户说"先初步分析"               用户说"你自己干活，给最终结论"
  → pi 跑有界子计划                  → pi 跑完整任务（诊断→仿真→报告）
  → 呈现中间产物（信号图/初步诊断）   → 不中途打断
  → 暂停，等用户决定下一步            → 一次性交付最终报告
  → 用户 steer → 继续
```

- 由 pi 的 RPC **steer** 实现 HITL（运行时注入用户决定）；`PiBridge.steer()` 是载体。
- **autonomous** = 保留现有 `-p -e` 全自动路径 + pi `--batch`/no-steering 标志。
- 两种模式**可切换**（用户可随时从自动切回交互）。

### 2.7.2 中间产物一等公民（per-step artifact）

现状缺陷（调研）：所有中间产物（信号/窗口/TPE/证据）只在最后 report 呈现，中途仅文本状态行。

**设计**：
- 每个能力 `ModuleResult.artifacts` 即中间产物（信号曲线 PNG/HTML、初步诊断摘要、报警时刻属性表、调用链图、仿真 trace）。
- pi 每跑完一个工具，把 `artifacts` 呈现给用户（对话中展示路径/摘要/预览）。
- 新增 per-step artifact 输出通道（结构化，非仅状态文本）。

### 2.7.3 用户故事 → 能力 + 中间产物 + 模式映射

| US | 用户故事 | 能力 | 中间产物 | 模式 |
|----|---------|------|----------|------|
| US1 | 先做初步分析 | classify + signal-extract + 初步 diag | 关键信号曲线 + 初步诊断摘要 | HITL |
| US2 | 加日志去仿真抓信息 | sim-verify（埋点→arbe 回放→warning trace） | 仿真日志 + trace CSV | HITL/auto |
| US3 | 自己干活给最终结论 | diag（8步） + code-fix | 最终报告 | auto |
| US4 | 只做原始信号+绘图 | signal-extract | 信号曲线 + CSV | HITL |
| US5 | 展示代码调用逻辑 | code-analyze | 调用链图/文本 | HITL |
| US6 | 查看报警时刻属性 | 报警时刻对象/信号/状态快照（新能力） | 报警时刻属性表 | HITL |
| US7 | 数据不全兜底 | 全局降级（见 2.7.4） | 可用子集 + "数据不足"标注 | 任意 |

### 2.7.4 数据不全优雅降级（US7）

**现状**（调研）：现有管线对 bag-only/blf-only/无DBC/无源码**已优雅降级不崩溃**，但**静默**——产出"看似正常"的空报告，无顶层标识。

**设计（补齐）**：
1. 解析后立即 `data_availability` 分类：`has_bag / has_can / has_dbc / has_radar_objects / has_source`。
2. 顶层 banner + 注入专家面板 `DATA_AVAILABILITY` 提示（防 LLM 基于空表过度断言）。
3. 报告头 `data_gaps` 段（缺失 BAG/BLF/DBC/source）。
4. 能力降级矩阵：

| 数据 | 可分析能力 | 不可用能力 |
|------|-----------|-----------|
| bag-only | signal-extract(雷达内部/对象)、data-analyze、diag(受限) | CAN 相关（signal_audit/suppression/CAN 抽取） |
| blf-only | signal-extract(CAN)、data-analyze、diag(受限) | 雷达内部/对象分析 |
| 无 DBC | 雷达内部分析 | CAN 解码/审计 |
| 无源码 | 数据抽取/分析 | code-learn/code-analyze/diag 代码部分 |

5. **绝不以"数据不足"为由抛错终止**（现状已满足，设计显式声明）。

### 2.7.5 调研发现的关键 bug / 缺口（须修复）

| # | 项 | 位置 | 处理 |
|---|----|------|------|
| B1 | `probe_results` 未赋值 | `orchestrator.py:1144` | 修 → `probe_results_list`（bundle 真正保存） |
| B2 | `_run_frame_analysis_with` router.chat 未包装 | `orchestrator.py:2330` | 包装 try/except，LLM 失败降级不中止 |
| G1 | 无顶层 data_availability | 解析后 | 加 data_gaps（见 2.7.4） |
| G2 | 无 per-step artifact 通道 | 全管线 | 加 per-step artifact（见 2.7.2） |
| G3 | AskHumanTool 未注册/无恢复 | `ai/tools/` | 实现 AskHumanTool + 恢复路径 |
| G4 | plot 仅支持 CAN | `tools/plot_signals.py` | 扩展 radar_objects/radar_debug 绘图（bag-only 可用） |
| G5 | tree-sitter 不在 requirements.txt | `requirements.txt` | 补依赖（否则新机器 import 崩溃） |

---

## 3. 能力封装机制（pi Extension ↔ radarAnalyze 能力）

### 3.1 radarAnalyze 侧：能力三件套（复用现有 BaseModule/BaseTool）

```python
# Engine: deterministic facts and providers
# BaseTool: canonical Pi/Agent JSON-in/JSON-out contract
# BaseModule: optional standalone CLI/API wrapper around an engine/tool
```

**核心约定 [D-PI-3]**：Pi Extension 的 `registerTool.execute` 统一调用
`python -m ai.capability.pi_tool_bridge --name <name> --params <json>`；bridge 再调用
`BaseTool.safe_execute()` 或 `BaseModule` adapter，返回确定性结果和证据链。Extension
不复制业务逻辑，也不为每个 module 维护一套 CLI 参数协议。

### 3.2 Pi 侧：Extension（TypeScript 薄壳）

```typescript
// .pi/extensions/radar-capabilities.ts（新增，示例）
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { execFileSync } from "node:child_process";
const pythonExecutable = process.env.CR60_RADAR_ANALYZE_PYTHON ?? "python";

export default function (pi: ExtensionAPI) {
  // 从 radarAnalyze 的 MODULE_REGISTRY 自动生成的清单注册工具
  pi.registerTool({
    name: "signal_extract",
    label: "Signal Extract",
    description: "从 bag/blf 抽取信号并绘图。用法：查询'车速'等。",
    parameters: Type.Object({
      query: Type.String({ description: "信号名或自然语言" }),
      case_dir: Type.String({ description: "数据目录" }),
      plot: Type.Optional(Type.Boolean({ default: true })),
    }),
    async execute(toolCallId, params, signal, onUpdate, ctx) {
      const out = execFileSync(pythonExecutable, [
        "-m", "ai.capability.pi_tool_bridge", "--name", "signal-extract",
        "--params", JSON.stringify(params ?? {}),
      ], { encoding: "utf-8" });
      const r = JSON.parse(out);
      return { content: [{ type: "text", text: JSON.stringify(r) }], details: r };
    },
  });
  // ... 每个 Pi-visible capability 生成一个 registerTool 块（自动生成，见 §5）
}
```

> 更优做法：写一个**生成器** `scripts/gen_pi_extension.py`，扫描 **MODULE_REGISTRY + ai/tools 的 BaseTool 注册表**，为每个能力生成对应 `registerTool` 块（name/description/parameters_schema 直接取自 `BaseTool`）——新增能力零手工接线。
>
> **接线修正（对齐 §2.5 三件套）**：`registerTool.execute` 不写死每个模块的 CLI 参数，统一调用 `python -m ai.capability.pi_tool_bridge --name <name> --params <json>`。工具契约仍来自 `BaseTool.parameters_schema`/`BaseModule.input_schema`，Pi、bridge 和离线 AgentLoop 共用同一套能力目录。

### 3.3 备用通道：RPC 直接驱动 + bash 工具

Pi 本身支持 `bash`/`read`/`write`，也可以通过 `bash` 调用 CLI；这只作为开发/故障排查兜底。正式业务能力必须走生成的 TS `registerTool` → `pi_tool_bridge`，默认关闭 Pi 内置工具，避免绕过统一审批和证据 envelope。

---

## 4. pi-bridge（Python 侧中枢封装）

### 4.1 职责

`ai/pi_bridge.py`（新增）——radarAnalyze 侧驱动 pi 的统一封装：

```python
class PiBridge:
    """驱动 pi --mode rpc 的 Python 客户端（参考官方 Python 示例）。"""
    def __init__(self, provider="", model="Qwen3.5-27B-FP16",
                 session_dir=None, no_session=True,
                 system_prompt=None, tools=None):
        # provider 默认复用现有 Bosch 模型端点（与 config.yaml ai.remote 同一模型，能力不退步）
        self.proc = subprocess.Popen(
            ["pi", "--mode", "rpc"] + self._flags(),
            stdin=PIPE, stdout=PIPE, text=True)

    def prompt(self, message, *, steer=False, images=None) -> str:
        """发送 prompt，消费事件流直到 agent_settled，返回综合答案。"""
        ...
    def steer(self, message): ...
    def get_messages(self) -> list: ...
    def set_model(self, model): ...
    def close(self): ...
```

> **provider 落地核查（2026-08-21 实证）**：
> - 当前机器 2026-08-27 的 `pi --list-models` 显示 `bosch-qwen3_6 / Qwen3.5-27B-FP16`；provider 名称可能随 Pi 配置变化。
> - PiBridge 默认 provider 为空，由显式参数、`CR60_PI_PROVIDER` 或只读 `pi --list-models` 解析；model 默认为配置兼容的 `Qwen3.5-27B-FP16`，也可由 `CR60_PI_MODEL` 覆盖。
> - 其他用户必须显式绑定其 provider/model；不能把本机 provider 名当成平台契约。
> - 外部 provider（google/anthropic）与本地 ollama（deepseek-r1:8b）作为**可选/离线兜底**。

**关键实现点**：
- **事件消费**：逐行读 stdout JSON，遇 `message_update` 流式显示，遇 `agent_settled` 结束；`tool_execution_start/update/end` 用于回显"pi 正在调用哪个 radar 能力"。
- **超时/崩溃保护**：LLM 不可用 → 返回结构化错误；必要时由外层显式切换到 `ReActPlanner`/`AgentLoop` 离线兜底，不把兜底入口伪装成 Pi 主流程。
- **会话管理**：`--session-dir <workspace>/sessions/<project>`，支持 rewind/branch。
- **扩展绑定**：默认生成并显式传入当前项目 `.pi/extensions/radar-capabilities.ts`，不依赖未确认的 project trust；生成物随 catalog 更新。
- **编排上下文**：通过 `pi-context` 生成 `pi-orchestration-context.v1`，以只读摘要进入 Pi prompt，完整 artifact 仍由工具按引用读取。

### 4.2 PiModule（统一对话入口，替代手写对话循环）

```python
# ai/modules/pi.py（新增）
class PiModule(BaseModule):
    name = "pi"
    description = "统一对话入口：按用户问题调度 radarAnalyze 能力（通过 Pi）"
    def run(self, *, question="", case_dir=None, interactive=False,
            batch=None, **kw) -> ModuleResult:
        bridge = PiBridge(...)
        if batch:   # 批量问题
            for q in batch: bridge.prompt(q)
        elif interactive: # TUI 对话
            ...
        else:
            answer = bridge.prompt(question)
        return ModuleResult.success(message=answer, ...)
```

---

## 5. 详细实施计划（分片 · 可验证）

> 每个 Slice 给出：目标 / 文件清单（新增·修改）/ 验收标准 / 复用资产。顺序保证**每片独立可验证、可组合**。

### Slice P0 · 能力契约统一 + Pi 环境验证（已部分完成）

**目标**：确认 pi 可用；把"能力"统一为三件套（engines + BaseTool + BaseModule），并打通“能力 → Pi registerTool → canonical bridge → 结果 artifact”契约。
**复用**：已装的 `pi 0.84.2`、`ai/modules/base.py`、`ai/tools/base.py`（BaseTool）、`MODULE_REGISTRY`。
**文件**：
- [x] 实证 `pi --mode rpc` 可用（本机冒烟通过）
- 新增 `ai/capability/registry.py` — 扫描 **MODULE_REGISTRY + ai/tools 的 BaseTool 注册表** → 能力清单（name/description/parameters_schema/tags）
- 新增 `ai/capability/pi_tool_bridge.py` — Pi 唯一 JSON bridge：`python -m ai.capability.pi_tool_bridge --name <name> --params <json>` → BaseTool/BaseModule adapter
- 新增 `engines/pi_context.py` + `ai/modules/pi_context.py` — 生成 `pi-orchestration-context.v1`
- 新增 `scripts/gen_pi_extension.py` — 从能力清单生成 `pi` 扩展 TS（registerTool 块，字段取自 BaseTool）
- 新增 `scripts/pi_rpc_smoke.py` — RPC 冒烟（prompt→PONG，参考官方 Python 示例）

> **对齐 D-PI-6**：不另起 `CapabilityModule`；能力 = 现有三件套（engines 实现 + BaseTool 工具 + BaseModule CLI）。

**验收**：
- `python scripts/pi_rpc_smoke.py` 通过（RPC 往返）
- `python scripts/gen_pi_extension.py` 生成含全部 Pi-visible leaf 能力的扩展 TS；生成代码包含 `JSON.stringify(params ?? {})`，不丢参数且排除编排根
- 能力清单 JSON（name/description/schema）可打印
- `tool-bridge` 能调现有 `PlotSignalTool`/`QueryCanDataTool` 并返回 `{status,message,data,artifacts}`

### Slice P1 · pi 入口 + 整体调度（pi-bridge + tool-bridge + PiModule）

**目标**：Pi 作为**唯一产品入口 + 整体调度中枢**能驱动对话并调用全部 leaf 能力工具；`ReActPlanner`/`AgentLoop` 只作本地兜底和确定性回归。
**复用**：`PiBridge`（§4）、`ReActPlanner`（仅兜底）、`BaseTool`（工具契约，能力单一来源）、`pi_tool_bridge`（P0）。
**文件**：
- 新增 `ai/pi_bridge.py` — PiBridge（provider/model 可配置，未指定 provider 时本机只读探测；prompt/steer/事件流消费/超时边界）
- 新增 `ai/modules/pi.py` — PiModule（对话/批量/交互三形态）
- 保留 `ai/capability/tool_bridge.py` — legacy BaseTool JSON bridge；Pi 正式扩展使用 `ai/capability/pi_tool_bridge.py`
- 修改 `scripts/gen_pi_extension.py` — 从 catalog 生成 Pi-visible `registerTool`，统一调用 `pi_tool_bridge` 并透传 params
- 修改 `ai/pi_bridge.py` — 自动刷新当前项目 extension，显式 `--extension` 加载，默认 `--no-builtin-tools`
- 修改 `ai/modules/__init__.py` — 注册 `pi`
- 修改 `cli.py` — `pi` 为主入口；`react/query/diag` 保留为底层/兜底命令

**验收**：
- `cli.py pi "帮我抽取车速信号" --case-dir ...` 由 pi 规划并调用 `signal_extract` 工具（端到端）
- pi 的工具目录 = 全部注册 BaseTool（与 MODULE_REGISTRY 单一来源）
- pi 不可用（provider 未就绪）时 `cli.py pi` 降级到 `ReActPlanner` 兜底并明确提示
- `diag`（8 步管线）作为 pi 可调用工具存在
- `pi-context` 能把 intake/preflight/source/data/policy 绑定成一个 context artifact，typed composition 可引用该上下文

### Slice P2 · 数据统一（provenance + signal_valid + data_quality + 降级）—— 不依赖 pi，先行

**目标**：根治"无效占位数据当真实证据"（QZH 教训）+ **数据不全优雅降级（US7）**，这是所有能力正确性的前提。
**复用**：`case_loader`/`frame_store`/`dbc_loader`/`signal_mapper`/`ai/codegraph/*`（含休眠 tree-sitter AST）。
**文件**：
- 新增 `parsers/providers/*.py`（DataProvider SPI：bag/blf/mf4/dbc/code_repo）
- 修改 `parsers/frame_store.py` — `signal_catalog` + `data_quality` 表 + 兼容列
- 新增 `engines/data_quality.py` — `DataQualityAuditor`（恒定/物理不可能值检测）
- 修改 `bag_provider` — 解码 front/rear signals（复用已验证的 `_decode_publiccan` 逻辑），占位标 invalid
- 修改 `investigation_engine`/`data_probe`/`signal_audit` — 只在 valid 时取值
- 修改 `ai/codegraph/builder.py` 调用点 — `use_ast=True` 激活 tree-sitter（orchestrator + auto_dream）
- 新增 `engines/data_availability.py` — `classify_availability(case_load_result) -> {has_bag/has_can/has_dbc/has_radar_objects/has_source}`（G1）
- 修改 `case_loader.py` + `orchestrator._parse_case_data` — 解析后产出 data_availability + 顶层 banner + 报告头 `data_gaps` 段
- 修改 `requirements.txt` — **补 `tree-sitter` + `tree-sitter-c`（G5）**

**验收**：
- QZH bag：`veh_spd=281.53`、`braking_req=1` 判 placeholder/invalid；诊断不再出现"用户现象描述"当数据来源
- AST 激活后 codegraph DB 出现 STATE/TRANSITION/READS_SIGNAL 边（现状 0）
- bag-only / blf-only 独立加载；data_availability 正确分类；报告头有 data_gaps
- `pip install -r requirements.txt` 新机器可装 tree-sitter

### Slice P2b · 关键 bug 修复 + HITL 交互基座（不依赖 pi，先行）

**目标**：修 B1/B2 真实 bug + 建立 HITL 交互原语（AskHumanTool + per-step artifact）。
**复用**：`ai/agent_loop.py`（input_required 暂停原语）、`ai/observability.py`（StepLogger）、`ModuleResult.artifacts`。
**文件**：
- 修 `orchestrator.py:1144` — `probe_results` → `probe_results_list`（B1，bundle 真正保存）
- 修 `orchestrator.py:2330` — `_run_frame_analysis_with` 的 router.chat 包 try/except（B2，LLM 失败降级）
- 新增 `ai/tools/ask_user.py` — `AskHumanTool`（BaseTool：暂停→提示→恢复，G3）
- 修改 `ai/agent_tool_registry.py` — 注册 AskHumanTool + 恢复路径（pending_input → 回答续跑）
- 新增 `ai/capability/artifacts.py` — per-step artifact 通道（结构化呈现中间产物，G2）
- 扩展 `tools/plot_signals.py` + `PlotSignalTool` — 支持 radar_objects/radar_debug 绘图（G4，bag-only 可用）

**验收**：
- `diagnosis_bundle.json` 真正生成（B1 修复验证）
- LLM 故障时诊断不中止（B2 修复验证）
- `AskHumanTool` 能暂停并恢复（HITL 原语）
- bag-only 案例能画雷达内部/对象曲线（G4）

### Slice P3 · signal-extract 能力（首个端到端：能力 → pi 工具 → 曲线）

**目标**：用户最关心的"抽信号 + 绘图"，并验证"能力→pi 工具→对话调用"全链路。
**复用**：`PlotSignalTool`、`tools/plot_signals.py`、`generated_signal_map.py`（已拉取）、`engines/signal_mapper.py`。
**文件**：
- 新增 `engines/signal_catalog.py` + `engines/signal_extract.py`（三级模糊匹配：精确/别名→语义→跨源对齐）
- 新增 `ai/modules/signal_extract.py` — `SignalExtractModule`
- 注册 + 生成 pi 扩展工具 `signal_extract`

**验收**：
- `cli.py signal-extract "车速" cases/byd_qzh_rctb/ --plot` 输出信号 + 曲线
- pi 对话中调用 `signal_extract` 工具成功（TS 壳 → Python 模块 → 曲线路径回传）

### Slice P4 · arbe-replay / sim-verify（仿真能力）

**目标**：bag → Linux arbe 回放 → warning trace → DataStore，供 pi 调度验证。
**复用**：`tools/arbe/`（已拉取）、`cr60light-arbe-build` skill、服务器 10.190.171.44。
**文件**：
- 新增 `engines/arbe/replay_provider.py`（抽象）+ `local_replay.py`（解析 `_algo_warning_trace.csv`）+ `remote_replay.py`（SSH 骨架）
- 新增 `ai/modules/sim_verify.py` — `SimVerifyModule`
- 注册 + 生成 pi 扩展工具 `sim_verify`

**验收**：
- 本地解析 trace → DataStore（warning_events/signal_catalog）
- `cli.py sim-verify --mode local` 输出 trace/KPI 摘要
- Remote 接口就绪，文档说明 SSH 流程

### Slice P5 · code-learn / code-analyze（代码能力，基于 AST 激活）

**目标**：激活 AST 后的代码索引 + 按需检索，供 pi 调度做代码分析/定位。
**复用**：`ai/codegraph/`（AST 层）、`engines/signal_mapper.py`。
**文件**：
- 新增 `ai/modules/code_learn.py` — `CodeLearnModule`（AST→索引→按需检索）
- 新增 `ai/modules/code_analyze.py` — `CodeAnalyzeModule`（调用链/依赖/语义）
- 注册 + 生成 pi 扩展工具

**验收**：
- `code-learn` 激活 AST 后索引含信号/状态机边
- pi 对话中调用 `code_analyze` 能查调用链

### Slice P6 · 记忆分层 + 多项目隔离

**目标**：多项目记忆/数据隔离，防串扰；pi 会话绑定项目。
**复用**：`variant`/`.workspaces/`/`knowledge_guard`/`memory_system`。
**文件**：
- 新增 `ai/capability/project_context.py`（variant → 代码/数据/记忆/workspace）
- 修改 `ai/pi_bridge.py` — 会话绑定项目（`--session-dir <workspace>/sessions/<project>`）
- 修改 `memory/memory_system.py` — 语义记忆命名空间（LanceDB 按项目隔离，如需要）
- 新增 `tests/test_project_isolation.py`

**验收**：
- 两 variant 并行诊断，记忆/索引不串扰；跨项目禁止回退
- pi 会话绑定项目，隔离正确

### Slice P7 · req-analyze（扩展示例）+ 组合编排 + 回归

**目标**：验证 pi 可扩展性 + 全链路组合 + 全量回归。
**文件**：
- 新增 `ai/modules/req_analyze.py` — `ReqAnalyzeModule`（复用 `core/materials`）
- 新增 smoke 测试（pi_dispatch/signal_extract/data_quality/arbe_local/project_isolation）
- 回归：`tools/run_harness_gate.py` + `pytest tests/`

**验收**：
- 新增 req-analyze 后 pi 工具目录自动出现，无需改核心（验证可插拔）
- 组合场景：`pi "抽取 RCTB 制动请求信号并诊断是否误触发"` → signal-extract → diag → code-fix（含证据链）
- harness gate 通过 + 新增 smoke 全绿

---

## 6. 分片依赖与顺序

| Slice | 内容 | 依赖 | 复用 | 前置验证 |
|-------|------|------|------|---------|
| P0 | 能力契约统一（三件套）+ pi 环境 | - | pi 0.84.2 + BaseTool + BaseModule + MODULE_REGISTRY | ✅ RPC 已冒烟 |
| P1 | **pi 入口 + 整体调度**（tool-bridge + PiModule + HITL steer） | P0 | BaseTool + ReActPlanner(兜底) + AskHumanTool | - |
| P2 | 数据统一 + AST 激活 + 数据不全降级（US7） | - | case_loader/codegraph | - |
| P2b | **关键 bug 修复（B1/B2）+ HITL 交互基座（AskHumanTool + per-step artifact + plot 扩展）** | - | agent_loop(input_required)/observability/PlotSignalTool | - |
| P3 | signal-extract 能力 → pi 工具（端到端，US4） | P1 + P2 | PlotSignalTool/generated_signal_map | - |
| P4 | arbe-replay/sim-verify（US2：加日志→仿真→抓 trace） | P2 | tools/arbe/ + skill | - |
| P5 | code-learn/code-analyze（US5：代码调用逻辑） | P2 | ai/codegraph(AST) | - |
| P6 | 记忆分层 + 多项目隔离（pi 会话绑定项目） | P1 + P2 | variant/knowledge_guard | - |
| P7 | req-analyze + 组合编排（US1/3/6）+ 回归 + 兜底验证 | P1-6 | core/materials/harness | - |

> **建议顺序（用户故事驱动）**：P0 → **P2**（数据准确性 + 降级，US7 基座）→ **P2b**（修 bug + HITL 原语，US1/US4 前提）→ **P1**（pi 入口 + steer 调度）→ **P3**（US4 signal-extract 端到端）→ **P4**（US2 仿真）→ **P5**（US5 代码调用）→ **P6**（多项目隔离）→ **P7**（US1/3/6 组合 + 回归）。
> **关键验证点**：
> - **P2b**：`diagnosis_bundle.json` 真正保存（B1）、LLM 故障不中止（B2）、AskHumanTool 能暂停恢复（HITL 原语）、bag-only 可画雷达内部曲线（G4）。
> - **P3**：`pi "抽取车速信号"` 由 pi 规划并调用 `signal_extract` 工具成功 = **pi 整体调度 + HITL 呈现中间产物端到端成立**。
> - **P7**：组合场景 US1/3/6 跑通 + harness gate 通过 + ReActPlanner 兜底。

---

## 7. 与现有设计的映射

| 既有设计项 | 落地方式 |
|-----------|----------|
| 对话入口 + 整体调度 | **Pi**（唯一入口 + 整体调度中枢）；PiBridge + PiModule + tool-bridge（D-PI-9） |
| 能力模块 C1-C9（插件化） | **三件套**：engines + ai/tools/BaseTool + ai/modules/BaseModule + MODULE_REGISTRY（D-PI-6） |
| 能力即工具 | 每个能力注册为 `BaseTool` → pi `registerTool`（D-PI-10）；工具目录单一来源 |
| 原 ReActPlanner/AgentLoop | **退役**为本地兜底（pi 不可用/离线时），不再是并行主入口 |
| 固定 8 步管线 | 包装为 `diag` 工具（内部仍走 orchestrator），pi 按需调用 |
| pi 工具目录（自动发现） | `gen_pi_extension.py` 扫描 BaseTool 注册表生成 registerTool |
| 工具契约（单一来源） | `BaseTool.parameters_schema` → pi registerTool 与兜底 AgentLoop 共用 |
| 数据准确性（P1/QZH） | Slice P2（DataProvider + data_quality + AST 激活） |
| 知识仅定位（P2） | 能力返回确定性证据；pi 的 LLM/记忆只作定位提示 |
| 多项目隔离（D16） | Slice P6（pi 会话绑定项目 + 命名空间 + manifest） |
| arbe 先抽象后远程 | Slice P4（ArbeReplayProvider 接口 + 本地解析） |
| 质量属性 Q1-Q7 | 每个 Slice 验收含对应质量属性检查 |

---

## 8. 风险与缓解

| 风险 | 缓解 |
|------|------|
| pi provider 认证/网络不可用 | PiBridge 超时降级到 ReActPlanner；`--no-session` 无状态模式 |
| pi 版本演进 API 变动 | 锁定 pi 版本（npm shrinkwrap）；PiBridge 隔离在单模块 |
| TS 扩展维护成本 | `gen_pi_extension.py` 自动生成，新增能力零手工接线 |
| 能力模块 JSON 契约漂移 | `to_tool_spec()` 从 input_schema 生成，单一来源 |
| AST 激活重建慢/失败 | 保留 `use_ast=False` 回退；增量重建 + freshness |
| 多项目记忆串扰 | 命名空间强制 + manifest 绑定项目 + 隔离测试（P6） |
