# V4 · 开发计划（分片实施 · 结合现状可落地）

> **配套**: `V4_PI_DRIVEN_ARCHITECTURE.md`（顶层架构设计）· `V4_DESIGN_CONTEXT_AND_DECISIONS.md`（需求与决策上下文）
> **原则**: 每个 Slice 独立可验收、可中断；**最大化复用现有代码资产**（调研确认：AST 层已存在但休眠、agent 骨架已就绪、variant/workspace/knowledge_guard 已成熟），不做重复造轮子。
> **质量属性**: 每个 Slice 满足 Q1 开放 / Q2 灵活 / Q3 可靠 / Q4 鲁棒 / Q5 可插拔 / Q6 AI 驱动 / Q7 可观测（详见架构文档 §8）。

---

## 复用资产映射（先认清家底，再动手）

| 现有资产 | 位置 | V4 复用为 |
|----------|------|-----------|
| ReActPlanner + AgentLoop | `ai/agent/react_planner.py` + `ai/agent_loop.py` | Pi 不可用时的离线/开发 fallback |
| agent 工具注册 | `ai/agent_tool_registry.py` | pi 工具目录（扩展自动注册能力模块） |
| 模块注册 | `ai/modules/__init__.py`（MODULE_REGISTRY）+ `ai/modules/base.py`（BaseModule/ModuleResult） | 能力 SDK 基座 |
| tree-sitter AST（休眠） | `ai/codegraph/ast_parser.py` + `ast_builder.py` + `state_machine_extractor.py` + `pattern_extractor_ast.py` | code-learn 确定性提取层（激活 use_ast=True） |
| CodeGraph SQLite | `ai/codegraph/`（schema v3，nodes/edges/semantics） | 结构索引层（补 STATE/SIGNAL 边） |
| case_loader + FrameStore | `parsers/case_loader.py` + `parsers/frame_store.py` | DataProvider 基座 + DataStore 扩展 |
| DBC/信号映射 | `parsers/dbc_loader.py` + `engines/signal_mapper.py` + 已拉取 `tools/arbe/src/.../generated_signal_map.py` | signal-extract 信号字典 |
| 绘图 | `ai/tools/data_tools.py`（PlotSignalTool）+ `tools/plot_signals.py` | signal-extract 曲线 |
| 记忆/语义 | `memory/memory_system.py` + LanceDB | 记忆机制与分层 |
| 变体/workspace | `config.yaml` variants + `.workspaces/<variant>/` + `config.local.yaml` | 多项目适配与隔离 |
| freshness | `core/knowledge_guard.py` + `core/freshness.py` | 知识失效/多项目隔离门禁 |
| arbe 资产 | `tools/arbe/`（已拉取）+ skill `cr60light-arbe-build` + 服务器 10.190.171.44 | sim-verify / arbe-replay |
| 需求 | `core/materials.py`（需求 Schema + requirement_trace） | req-analyze |
| 诊断管线 | `ai/orchestrator.py`（run_diagnosis 8 步） | `diag` 能力（保留） |

---

## Slice 0 · 设计文档 + AGENTS.md 更新（当前）

**范围**：
- [x] `docs/technical/V4_PI_DRIVEN_ARCHITECTURE.md` — 顶层架构设计（含质量属性/能力边界/交互/多项目/记忆分层/隔离）
- [x] `docs/technical/V4_DEVELOPMENT_PLAN.md` — 本文件
- [x] `docs/technical/V4_DESIGN_CONTEXT_AND_DECISIONS.md` — 需求与决策上下文（防遗漏基线）
- [x] 根 `AGENTS.md`：新增 V4 架构说明 + pi 入口 + 能力模块目录速查 + 复用资产映射
- [x] `ai/modules/AGENTS.md`：BaseModule/Pi tool 规范 + 模块编号 C1-C9
- [ ] `tools/AGENTS.md`：arbe 资产说明 + KPI/回放脚本用途

**验收**：V4 文档齐全；AGENTS.md 反映 pi 驱动架构 + 复用资产清单。

---

## Slice 1 · pi 调度中枢（复用 agent 骨架强化）

**目标**：把 Pi 作为统一产品入口；能力由 generated `registerTool` 自动进入 Pi，
`ReActPlanner`/`AgentLoop` 仅保留为 fallback 和确定性回归。

**复用**：`ReActPlanner`/`AgentLoop`/`agent_tool_registry`/`MODULE_REGISTRY`/`BaseModule`。
**文件清单**：
- 新增 `ai/capability/registry.py` — `CapabilityRegistry`：扫描 MODULE_REGISTRY/TOOL_REGISTRY，收集能力元信息 → Pi catalog
- 新增 `ai/capability/pi_tool_bridge.py` — Pi Extension 的唯一 JSON dispatch boundary
- 新增 `engines/pi_context.py`/`ai/modules/pi_context.py` — `pi-orchestration-context.v1`
- 修改 `ai/agent_tool_registry.py` — `build_agent_tool_registry` 遍历能力注册表自动生成工具
- 修改 `ai/agent/react_planner.py` — 工具描述加载能力目录；意图→规划→调度→综合；失败降级（Q4）
- 新增 `ai/modules/pi.py` — `PiModule`：对话入口（交互 + 单轮 + `--batch`）
- 修改 `cli.py` — 注册 `pi` 子命令（自动经 MODULE_REGISTRY）
- `ai/pi_bridge.py` — 显式加载 project extension、provider 探测、上下文摘要和有界 RPC 读取

**验收**：
- `cli.py pi "帮我抽取车速信号" --case-dir cases/byd_qzh_rctb/` 识别意图并调度 signal-extract
- 能力模块自动出现在 pi 工具目录（description/input_schema/tags）
- 单模块失败不中断整任务（返回 ModuleResult.fail + 降级）
- `diag` 能力保留，固定 8 步管线无回归
- `python cli.py pi` 能通过 generated Extension 实际调用 leaf tool；参数必须透传，递归根不进入目录

**依赖**：无（复用现有 agent 骨架）。

> **实现校正（2026-08-27）**：本计划早期使用 `CapabilityModule` 作为概念名，实际
> 实施不新增该协议，统一复用 `Engine + BaseTool + BaseModule`。Pi 产品工具链为
> `registerTool → pi_tool_bridge → BaseTool/BaseModule adapter`；当前的
> `pi-context`、参数透传、显式 extension、provider 只读探测和 timeout/进程清理
> 已由 DDD 基线及专项/现场 smoke 验证。详见
> `CR60_PI_DDD_REQUIREMENTS_AND_ACCEPTANCE.md`。

---

## Slice 2 · DataProvider + DataStore 数据统一 + 激活 AST（基座 + 数据准确性）

**目标**：根治"无效占位数据当真实证据"（QZH 教训）+ 激活休眠的 tree-sitter AST（社区调研最高杠杆）。

**复用**：`case_loader`/`frame_store`/`dbc_loader`/`signal_mapper`/`ai/codegraph/*`。
**文件清单**：
- 新增 `parsers/providers/base.py` — `DataProvider` SPI（source_kind/load/provenance）
- 新增 `parsers/providers/bag_provider.py` — BagProvider：强化 bag 分支
  - deep-parse 保留；**新增解码 `/front/signals`、`/rear/signals`（PublicCan，用 bag 内嵌 msgdef + rosbags typestore，复用 scripts/_decode_publiccan.py 已验证逻辑）**
  - 回放占位信号（signal_valid=0 / 恒定）打 invalid
- 新增 `parsers/providers/blf_provider.py` / `mf4_provider.py` / `dbc_provider.py` / `code_repo_provider.py`
- 修改 `parsers/frame_store.py` — 新增 `signal_catalog`、`data_quality` 表 + 兼容列
- 新增 `engines/data_quality.py` — `DataQualityAuditor`：恒定/物理不可能值检测
- 修改 `ai/investigation_engine.py`、`engines/data_probe.py`、`engines/signal_audit.py` — 只在 valid 且非占位时取值
- 修改 `parsers/case_loader.py` — 接入 DataProvider 统一加载 + provenance/signal_valid
- **修改 `ai/codegraph/builder.py` 接入点 + orchestrator/auto_dream** — `use_ast=True` 激活 tree-sitter AST 提取（信号/状态机/模式）

**验收**：
- QZH bag：`veh_spd`（281.53 恒定）、`braking_req`（恒定）判为 placeholder/invalid；诊断不再出现"用户现象描述"作为数据来源
- bag-only / blf-only 独立加载
- AST 模式：codegraph DB 出现 STATE/TRANSITION/READS_SIGNAL/WRITES_SIGNAL 边（现状为 0）
- 回归：`use_ast=False` 路径仍可用（兼容回退）

**依赖**：无。

---

## Slice 3 · signal-extract 模块（数据抽取 + 绘图）

**目标**：支持"帮我抽取某某信号"，模糊抽取 + 跨源对齐 + 曲线。

**复用**：`PlotSignalTool`（ai/tools/data_tools.py）+ `tools/plot_signals.py` + 已拉取 `generated_signal_map.py` + `engines/signal_mapper.py`。
**文件清单**：
- 新增 `engines/signal_catalog.py` — 信号目录（DBC + msgdef + signal_mapping + generated_signal_map 字典 + 中文/别名）
- 新增 `engines/signal_extract.py` — `SignalExtractor`：三级匹配（精确/别名 → 语义 → 跨源对齐）
- 新增 `ai/modules/signal_extract.py` — `SignalExtractModule`：查询 → 抽取 → CSV + 曲线
- 注册到 MODULE_REGISTRY

**验收**：
- `cli.py signal-extract "车速" cases/byd_qzh_rctb/ --plot` 输出正确信号 + 曲线
- 模糊查询（"车速"/"vehicle speed"/"rctb"）命中合理信号
- 抽取结果带 provenance/signal_valid（无效信号明确标注）

**依赖**：Slice 2。

---

## Slice 4 · arbe-replay 模块（仿真接口 + 本地 trace 解析）

**目标**：先抽象接口 + 本地解析 arbe 产出；SSH 远程后续接。

**复用**：`tools/arbe/`（已拉取：bag_csv_kpi_*.py、FCTB_Batch_Replay_Operation_Guide.md）+ skill `cr60light-arbe-build` + 服务器 10.190.171.44。
**文件清单**：
- 新增 `engines/arbe/replay_provider.py` — `ArbeReplayProvider` 抽象（submit/poll/fetch_trace/fetch_kpi）
- 新增 `engines/arbe/local_replay.py` — `LocalArbeReplayProvider`：解析 `_algo_warning_trace.csv`（event_sec, radar_id, w1..w15）+ `batch_fctb_trigger_report.csv` → DataStore
- 新增 `ai/modules/sim_verify.py` — `SimVerifyModule`
- 新增 `engines/arbe/remote_replay.py` — `RemoteArbeReplayProvider` 骨架（SSH，接口就绪，实现后置）
- 注册到 MODULE_REGISTRY

**验收**：
- 本地解析 `tools/arbe/` 示例 trace → DataStore（warning_events/signal_catalog）
- `cli.py sim-verify --case-dir ... --mode local` 输出 trace/KPI 摘要
- Remote 接口定义完整 + 文档说明 SSH 流程

**依赖**：Slice 2。

---

## Slice 5 · req-analyze 扩展示例（验证 pi 可扩展性）

**目标**：客户需求文档 → 需求-代码 gap 分析；验证 pi 可扩展性。

**复用**：`core/materials`（需求 Schema + requirement_trace）+ code-analyze + LLM gap 推理。
**文件清单**：
- 新增 `ai/modules/req_analyze.py` — `ReqAnalyzeModule`
- 注册到 MODULE_REGISTRY
- 更新 pi 能力目录（自动）

**验收**：
- 输入需求 + 代码仓 + 分支 → gap 报告（violations + requirement_trace）
- 新增模块后 pi 工具目录自动出现 req-analyze，无需改 pi 核心（验证 Q5 可插拔）

**依赖**：Slice 1。

---

## Slice 6 · 多项目适配 + 记忆隔离强化

**目标**：验证多项目（多 variant）下能力调度、记忆/数据隔离正确，防串扰。

**复用**：`config.local.yaml` variant 体系 + `.workspaces/<variant>/` + `core/knowledge_guard` + `memory_system`。
**文件清单**：
- 新增 `ai/capability/project_context.py` — 项目上下文解析（variant → 代码/数据/记忆/workspace）
- 修改 `ai/capability/session.py` — 会话绑定项目；跨项目禁止复用记忆/证据
- 新增 `tests/test_project_isolation.py` — 多项目记忆/数据隔离测试
- 修改 `memory/memory_system.py` 语义记忆命名空间（如需要）— LanceDB 按项目隔离

**验收**：
- 两个不同 variant 并行诊断，记忆/知识/索引不串扰
- 跨项目禁止回退到其他项目知识（fail closed）
- 会话绑定项目，隔离正确

**依赖**：Slice 1 + Slice 2。

---

## Slice 7 · 组合编排 + 回归

**目标**：端到端验证 pi 组合调度 + 全量回归。

**范围**：
- 组合场景：`pi "抽取 RCTB 制动请求信号并诊断是否误触发"` → signal-extract → diag → code-fix 建议（含证据链）
- 新增 smoke：`tests/test_pi_dispatch.py`、`tests/test_signal_extract.py`、`tests/test_data_quality.py`、`tests/test_arbe_local.py`、`tests/test_project_isolation.py`
- 回归：`tools/run_harness_gate.py` 通过；`pytest tests/` 相关用例全绿
- 更新 `AGENTS.md` 运行模式表（pi 入口 + 各能力命令）

**验收**：
- 组合调度端到端跑通，输出含证据链 + 可观测 trace
- harness gate 通过 + 新增 smoke 全绿
- 无既有用例回归

**依赖**：Slice 1-6。

---

## 风险与缓解

| 风险 | 缓解 |
|------|------|
| 激活 AST 导致 codegraph 重建慢/失败 | 保留 `use_ast=False` 回退；AST 作为默认后按需切换；增量重建 + freshness |
| pi 自由调度导致结果不可复现 | 能力模块是确定性工具；ReActTrace 记录规划；证据分级标注 |
| DataStore schema 扩展破坏现有查询 | 新列默认值向后兼容；先加表后加列；回归验证 |
| arbe 远程执行依赖服务器状态 | 本地解析 + 接口抽象（P6）；远程可选后端 |
| 多项目隔离遗漏导致串扰 | 命名空间强制 + manifest 绑定项目 + 会话隔离测试（Slice 6） |
| LLM 记忆/需求推理质量 | 记忆只作定位（P2）；需求分析复用 materials 结构化 + 证据标注 |

---

## 里程碑总览

| Slice | 内容 | 依赖 | 复用资产 | 预估 |
|-------|------|------|----------|------|
| 0 | 设计文档 + AGENTS.md | - | docs | 当前 |
| 1 | pi 调度中枢 | - | ReActPlanner/AgentLoop/agent_tool_registry | 高 |
| 2 | 数据统一 + 激活 AST | - | case_loader/frame_store/codegraph(ast_parser) | 高 |
| 3 | signal-extract | S2 | PlotSignalTool/plot_signals/generated_signal_map | 高 |
| 4 | arbe-replay 接口 + 本地解析 | S2 | tools/arbe/ + cr60light-arbe-build skill | 中 |
| 5 | req-analyze 扩展示例 | S1 | core/materials + code-analyze | 中 |
| 6 | 多项目适配 + 记忆隔离 | S1+S2 | variant/.workspaces/knowledge_guard/memory | 中 |
| 7 | 组合编排 + 回归 | S1-6 | run_harness_gate + pytest | 中 |

> **建议实施顺序**：S0 → S2（数据准确性 + AST，先根治误判）→ S3（signal-extract，用户核心诉求）→ S1（pi 中枢）→ S4（arbe）→ S5（req-analyze）→ S6（多项目隔离）→ S7（回归）。
