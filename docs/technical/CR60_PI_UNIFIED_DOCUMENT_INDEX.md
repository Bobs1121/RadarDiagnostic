# CR60 Pi Unified Platform 文档索引

版本：`docu-dev-index.v1.7`  
日期：`2026-09-03`  
状态：当前设计文档入口

## 1. 阅读顺序

1. [PRD](../CR60_PI_UNIFIED_PRD.md)：为什么做、给谁用、输入输出和验收；
2. [DDD 用户故事与验收基线](CR60_PI_DDD_REQUIREMENTS_AND_ACCEPTANCE.md)：需求、用户故事、验收、追踪矩阵和 DDD 门；
3. [架构复盘与演进设计](CR60_PI_UNIFIED_ARCHITECTURE_REVIEW_2026-08-30.md)：当前设计评估、阶段性分析、Workbench、效率/准确性和 Gen6 适配；
4. [调研报告](../CR60_PI_UNIFIED_RESEARCH_REPORT_2026-08-26.md)：仓库、skill、arbe source 和当前事实；
5. [系统设计](CR60_PI_UNIFIED_SYSTEM_DESIGN.md)：系统拓扑、控制/证据/分析状态/解释面和生命周期；
6. [模块设计](CR60_PI_UNIFIED_MODULE_DESIGN.md)：工具、Provider、AnalysisLedger、FeaturePlugin 和边界；
7. [软件设计](CR60_PI_UNIFIED_SOFTWARE_DESIGN.md)：接口、schema、ledger、GDB 和几何实现约束；
8. [实施方案](CR60_PI_UNIFIED_IMPLEMENTATION_PLAN.md)：工作包、依赖、部署、风险和回退；
9. [Sprint 规划](CR60_PI_UNIFIED_SPRINT_PLAN.md)：按 Sprint 的目标、任务和验收；
10. [架构决策](CR60_PI_UNIFIED_DECISIONS.md)：关键取舍、约束和开放决策；
11. [Handoff 模板](CR60_PI_UNIFIED_HANDOFF_TEMPLATE.md)：阶段交接、artifact、事实和下一步；
12. [arbe 核心能力复用调研](CR60_PI_UNIFIED_ARBE_REUSE_ASSESSMENT.md)：实际服务器源码复用边界和适配策略；
13. [真实用户流程确认表](CR60_PI_UNIFIED_USER_WORKFLOW_QUESTIONNAIRE.md)：必须由真实用户确认的流程、权限和验收问题；
14. [输入 handoff schema](../../contracts/cr60-analysis-intake.v1.schema.json)：上游数据准备到下游 Sprint1 的机器契约；
15. 原子契约：[CR60 data prep verification](../../contracts/cr60-data-prep-verification.v1.schema.json)、[CR60 data transfer session](../../contracts/cr60-data-transfer-session.v1.schema.json)、[ROS inventory](../../contracts/ros-topic-inventory.v1.schema.json)、[public topic](../../contracts/public-topic-plan.v1.schema.json)、[public evidence](../../contracts/public-evidence-audit.v1.schema.json)、[code→GDB](../../contracts/code-gdb-plan.v1.schema.json)、[GDB session](../../contracts/gdb-session.v1.schema.json)、[runtime evidence](../../contracts/runtime-evidence.v1.schema.json)、[runtime merge](../../contracts/runtime-evidence-merge.v1.schema.json)、[runtime debug plan](../../contracts/runtime-debug-plan.v1.schema.json)、[arbe source resolution](../../contracts/arbe-source-resolution.v1.schema.json)、[arbe CUDA resolution](../../contracts/arbe-cuda-resolution.v1.schema.json)、[arbe patch plan](../../contracts/arbe-patch-plan.v1.schema.json)、[arbe start session](../../contracts/arbe-start-session.v1.schema.json)、[arbe stop session](../../contracts/arbe-stop-session.v1.schema.json)、[Pi composition](../../contracts/agent-composition.v1.schema.json)、[PiRunContext](../../contracts/pi-orchestration-context.v1.schema.json)；
16. 阶段性分析契约：[AnalysisRun](../../contracts/analysis-run.v1.schema.json)、[AnalysisStep](../../contracts/analysis-step.v1.schema.json)、[Claim](../../contracts/claim.v1.schema.json)、[Hypothesis](../../contracts/hypothesis.v1.schema.json)、[DebugExperiment](../../contracts/debug-experiment.v1.schema.json)、[User observation](../../contracts/user-observation.v1.schema.json)、[Ledger event](../../contracts/analysis-ledger-event.v1.schema.json)、[Code context](../../contracts/code-context.v1.schema.json)、[Code index](../../contracts/code-index.v1.schema.json)；
16a. `project-capability-manifest.v1`：Gen6 项目 capability categories、unsupported、freshness 和 fingerprint 契约；
16b. 三出口新增契约：[evidence-query.v1](../../contracts/evidence-query.v1.schema.json)、[diagnostic-report.v1](../../contracts/diagnostic-report.v1.schema.json)、[diagnostic-narrative.v1](../../contracts/diagnostic-narrative.v1.schema.json)、[condition-trace.v1](../../contracts/condition-trace.v1.schema.json)、[memory-recall.v1](../../contracts/memory-recall.v1.schema.json)、[alert-timeline.v1](../../contracts/alert-timeline.v1.schema.json)、[arbe-replay-result.v1](../../contracts/arbe-replay-result.v1.schema.json)；
17. [原子工具首版 handoff](CR60_PI_UNIFIED_HANDOFF_2026-08-26_ATOMIC_TOOLS.md)：本轮实现、真实环境验证和 S3 前置确认；
18. [FCTB runtime 验收 handoff](CR60_PI_UNIFIED_HANDOFF_2026-08-27_FCTB_RUNTIME.md)：真实 bag 的隔离 GDB、几何、预热敏感性和通用化修正；
19. [Runtime plan/GDB marker handoff](CR60_PI_UNIFIED_HANDOFF_2026-08-28_RUNTIME_PLAN.md)：source-driven debug plan、`$N` 错配修复、真实计划回放和局部降级；
20. [上游 source/CUDA 只读绑定 handoff](CR60_PI_UNIFIED_HANDOFF_2026-08-30_ARBE_SOURCE_CUDA_READONLY.md)：当前 source/ref、CUDA/config 解析、真实服务器证据和下一步写入门禁；
21. [架构复盘 handoff](CR60_PI_UNIFIED_HANDOFF_2026-08-30_ARCHITECTURE_REVIEW.md)：AnalysisRun/Workbench/Gen6 演进、arbe 新鲜调研和下一开发切片；
22. [Analysis Ledger MVP handoff](CR60_PI_UNIFIED_HANDOFF_2026-08-31_ANALYSIS_LEDGER_MVP.md)：run/step/claim 持久化、准确性门禁和 CRGVI-1829 恢复 smoke；
23. Code Context 实现切片：`code-context-refresh` / `code-context-read`、`code-context.v1`、`code-index.v1`；
24. Public Runtime 实现切片：`sim-verify --mode remote_public`、`public-runtime-normalize`、`runtime-snapshot-with-frame.v1`、`arbe-public-replay-session.v1`；包含 strict 与 source-proven publication_order 关联；
25. [Code Context/Public Runtime handoff](CR60_PI_UNIFIED_HANDOFF_2026-08-31_CODE_CONTEXT_PUBLIC_RUNTIME.md)：真实 16 文件 source mirror、事件代码路径和公共快照归一化验证；
26. 三出口实现 handoff：[CR60_PI_UNIFIED_HANDOFF_2026-09-01_THREE_PRODUCT_CAPABILITIES.md](CR60_PI_UNIFIED_HANDOFF_2026-09-01_THREE_PRODUCT_CAPABILITIES.md)；
27. S1D 条件证据和场景化报告：`condition-trace.v1` + `diagnosis-report` HTML；实现记录在本轮 handoff；
28. S1E 跨证据报警时间线和结论发布门：[DDD 缺口审查](CR60_PI_UNIFIED_DDD_GAP_REVIEW_2026-09-01.md)；`alert-timeline.v1` + `diagnostic-report.v1.conclusion`；
29. [DDD 缺口审查实现 handoff](CR60_PI_UNIFIED_HANDOFF_2026-09-01_DDD_GAP_REVIEW.md)：本轮文档、代码、测试、实际报告和未闭环项；
30. [S2B 协同 Debug MVP 设计](CR60_PI_UNIFIED_S2B_MVP_DESIGN_2026-09-01.md)：Hypothesis、DebugExperiment、用户观察和报告投影边界；
31. 已完成 Sprint 的 handoff：写在对应项目的 `docs/` 或 `handoff/`，并链接回本索引。
32. [产品化收口 handoff](CR60_PI_UNIFIED_HANDOFF_2026-09-03_PRODUCTIZATION.md) 与
    [产品化 TODO](CR60_PI_UNIFIED_TODO_2026-09-03_PRODUCTIZATION.md)：第一阶段盘点结果、
    当前真实证据、提交/清理边界和后续执行清单。

## 2. 文档主线

```text
需求
  → 调研事实
  → 架构决策
  → 工具/模块设计
  → 软件/schema 设计
  → 实施工作包
  → Sprint 验收
  → handoff
```

## 3. 当前项目关系

```text
bosch-data-transfert
    → cr60-analysis-intake.v1
        ↓
    → `cr60-data-prep-verify` (read-only source/destination checksum gate)
        ↓
    → `cr60-data-transfer` (approval-gated upstream executor)
        ↓
cr60light-arbe-build
    → prepared arbe/source/binary context
        ↓
    → `arbe-source-resolve` + `arbe-cuda-resolve` (read-only current-source binding)
        ↓
    → `arbe-patch-plan` (read-only simulation-adaptation/diff gate)
        ↓
cr60-debug-harness Sprint1
    → diagnosis-bundle.v1 / viewer-model.v1 / report
        ↓
radarAnalyze Pi orchestration
    → public-topic-plan.v1 / public-evidence-audit.v1
    → code-gdb-plan.v1
    → runtime-debug-plan.v1
    → runtime-debug-run (approval gated, isolated fallback)
    → arbe-formal-start (approval gated, owned process group)
    → runtime-debug-attach (approval gated, existing PID + executable gate)
    → gdb-session.v1 (approval gated)
        ↓
arbe + ROS + GDB
    → runtime-trace.v1
        ↓
evidence merge / HTML / Pi explanation
```

## 4. 文档维护规则

### 4.1 需求变更

先更新 PRD，再更新调研/决策和实施计划；不直接从聊天内容改代码。

### 4.2 新事实

新服务器、workspace、branch、tag、车型、COEM、CUDA、消息定义、函数或变量都写入新的调研记录，并绑定 source/data/binary fingerprint。

### 4.3 新工具

同步更新：

- 模块设计；
- 软件接口/schema；
- 风险和权限；
- Sprint 任务；
- 工具 catalog；
- `AGENTS.md`（若公开模块/API/schema 发生变化）。

### 4.4 新 runtime 结果

runtime 结果不得覆盖原始 Sprint1 bundle。使用 overlay/merge artifact，保留静态值、runtime 值、差异和来源。

## 5. 当前设计状态

| 项目 | 状态 |
|---|---|
| 调研报告 | 已补充 10.190.171.44 的 arbe 只读源码调研、可视化公共信号路径、preflight 和隔离 runtime 事实 |
| 架构复盘 | 已明确 AnalysisRun/Step、阶段性线索、Hypothesis/Experiment、Workbench、效率/准确性和 Gen6 manifest |
| arbe 复用调研 | 已刷新 BagReader 时间线/ACK、public runtime、GUI 属性表和 objectlist frame 缺口；采用 adapter 复用 |
| 用户流程确认表 | 第一轮 P0 已确认；新增 P1 Workbench 节奏、人工回填、多人协作和根因签字问题 |
| PRD | 已升级为 prd.v2.5；独立 Pi 入口、条件证据、跨证据时间线和结论发布门已纳入产品主线 |
| DDD 用户故事/验收 | 已建立 US-001..US-026、Given/When/Then、追踪矩阵和 DoR/DoD |
| 系统设计 | v2：四个平面、Analysis Ledger、capability pack、public snapshot、Gen6 manifest |
| 模块设计 | v2.3：新增 Ledger/EventCodePath/Hypothesis/PublicRuntime/AlertTimeline/Workbench 模块边界 |
| 软件设计 | v2.3：新增 run/step/claim/hypothesis/experiment/manifest/timeline/conclusion 契约 |
| 实施方案 | v2.3：增加 S1E timeline/conclusion/runtime condition/memory context 补足，优先组织已有能力再扩大 runtime/AI |
| Sprint 规划 | v2.3：增加 S1A/S1B/S1C/S1D/S1E/S2A/S2B/S3A/S3B |
| radarAnalyze 接入代码 | 已实现 intake、arbe-preflight、arbe-source-resolve、arbe-cuda-resolve、arbe-patch-plan、cr60-data-prep/transfer、Analysis Ledger MVP、Sprint1 adapter、公共证据审计、code→GDB plan、GDB service、runtime evidence normalize/validate/merge、formal start/stop/attach、CodeContext、EventCodePath、public runtime normalizer、ConditionTrace、MemoryRecall、AlertTimeline |
| SGU/HILMODEL=2 GDB | 隔离 launch-under-GDB 已验证；正式 workspace node/PID/executable 定位已验证，当前 `ptrace_scope=1` 下 attach 已准确 blocked |
| runtime HTML/Pi overlay | 已实现 additive merged bundle、逐帧 runtime geometry/fields、source/runtime collision projection、blocked attempt 展示和 `pi-context` deterministic evidence 输入；run5 已用 sibling build_html_reports.py 生成并验证 viewer model，正式 GUI parity/CAN Tx 仍未确认 |
| 三个用户出口 | `cr60-precheck` 批量、`evidence-query` 事件/帧/字段查询、`alert-timeline` 跨层时间线、`condition-trace` 条件证据、`memory-recall` 历史线索、`diagnosis-report` JSON/MD/HTML 投影、Pi session/AnalysisRun 对话 step、Pi `evidence_anchor` 和报告自动交付已实现并做真实单数据入口验收；远程联合 runtime/CAN 与长链现场仍需验收 |
| 远程公共仿真/目标属性 | 已在 10.190.171.44 真实验证既有 `sim-verify` remote_public：warning/radar_info/objectlist 采集、消息序号和 publication_correlated 逐帧关联；默认 strict，不能替代 GDB/CAN Tx |
| Gen6 项目能力清单 | 已实现 `project-capability-manifest`：从显式 intake/preflight/code-context/runtime/bundle 生成 capability categories、unsupported、freshness 和 fingerprint；当前 CRGVI-1829 混合 artifact 因 source snapshot 不一致验证为 blocked |
| 点云 150–200 帧 runtime | 尚未实施；当前只记录策略和 warm-up sensitivity |
| 跨证据报警时间线/结论门 | `alert-timeline.v1` 已实现并接入详细报告；当前 CRGVI-1829 已验证 raw/playback/missing-layer，联合 runtime/CAN 仍待现场验收 |

## 6. 首个实施入口

当前已从 S0/S1 的基础控制面进入原子证据/代码→GDB/runtime overlay 链；正式 runtime session 已完成隔离路径和 formal lifecycle 的局部验收：

```text
radarAnalyze/ai/modules/cr60_intake.py
    → arbe-preflight / data-prep adapters
    → radarAnalyze/ai/modules/cr60_precheck.py
    → cr60-debug-harness CLI adapter
    → diagnosis-bundle.v1 / viewer-model.v1
    → public-evidence-audit
    → code-analyze / code-gdb-plan
    → gdb-service
    → runtime-evidence-normalize / validate / merge
    → viewer HTML + pi-context
    → arbe-formal-start / runtime-debug-attach / runtime evidence attempt
```

正式 start/attach 仍由 approval gate 控制；当前服务器的 existing-PID attach 因
`ptrace_scope=1` 被 blocked，后续需在用户确认权限策略后再进行可消费 runtime 变量验收。
