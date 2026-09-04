# CR60 Pi Unified：S2B 协同 Debug MVP 设计

版本：`s2b-mvp-design.v1`  
日期：`2026-09-01`  
状态：`design-before-implementation`

## 1. 目标

S2B 解决一个明确的产品缺口：静态报告、公共 runtime 或 GDB 给出线索后，用户能够在同一
`AnalysisRun` 中提出候选原因、安排一个最小区分实验、接手 VSCode/GDB，并把结果交还 Pi
继续分析。报告要保留过程，而不是只留下最终一句“疑似根因”。

本切片只实现确定性的账本能力和报告投影，不实现自动根因判定、不修改算法代码、不直接
执行远程副作用。

## 2. 领域边界

```text
Pi
 ├─ analysis-hypothesis-record       候选原因的创建/更新/状态历史
 ├─ debug-experiment-record          实验计划/执行结果/扰动/结论变化
 └─ analysis-user-observation        用户从 VSCode/GDB/截图/备注回填的观察
             ↓
       AnalysisLedger（append-only event + 原子 JSON entity）
             ↓
       diagnostic-report（Hypothesis Board / Next Experiments read model）
```

以上是三个不同的业务动作，不合并成一个“诊断大工具”：

- `analysis-hypothesis-record` 只管理候选原因和状态历史；
- `debug-experiment-record` 只管理“要回答什么、怎么验证、结果改变了什么”；
- `analysis-user-observation` 只记录用户提供的事实/附件，不能直接覆盖自动 runtime evidence。

## 3. 输入和输出契约

### 3.1 Hypothesis

输入：`run_id`、类别、候选陈述、可选 rank/confidence、支持/反证 claim refs、所需证据和
实验 refs。更新必须提供当前 `hypothesis_id`，不删除历史。

输出：`hypothesis.v1`，包含：

- 当前 `status`：`open/testing/supported/weakened/rejected/confirmed_by_user`；
- `supporting_claim_refs`、`contradicting_claim_refs`、`required_evidence`、`experiment_refs`；
- `history[]`：前状态、后状态、actor、原因、证据 refs 和时间。

状态门禁：只有 `created_by=user` 才能写入 `confirmed_by_user`；Pi/AI 只能写
`open/testing/supported/weakened/rejected`，并且不能把 `inferred` 变成 `observed`。

### 3.2 DebugExperiment

输入：`run_id`、问题、方法、目标事件/雷达/frame/object/source/binary、计划引用、watch group、
期望区分、approval/session、观察、扰动和结论变化。

输出：`debug-experiment.v1`，状态为 `planned/approval_required/running/completed/partial/blocked/failed`。

状态门禁：工具只记录计划和回填；`approval_required` 不执行任何命令；GDB/ROS 的实际结果
必须通过已有 `runtime-evidence-normalize` 转成 runtime artifact 后才能作为 runtime 证据消费。

### 3.3 User observation

输入：`run_id`、观察类型（`manual_vscode/gdb_transcript/screenshot/note`）、用户描述、可选
文件/截图/artifact refs、目标 scope 和实验/假设 refs。

输出：`user-observation.v1`。它是“用户报告的观察”，不是 `gdb_observation`，不能直接进入
`condition-trace` 的同帧绑定；若内容是 GDB transcript，必须另行调用
`runtime-evidence-normalize` 并通过 source/data/frame identity gate。

## 4. 报告投影

`diagnostic-report.v1.analysis_trace` 增加有界的：

- Hypothesis Board：候选、当前状态、rank、confidence、支持/反证数量、关键缺口；
- Next Experiments：问题、方法、目标 frame/object、approval 状态、预期区分；
- User observations：类型、摘要、关联实验和 artifact refs。

页面默认展示摘要和状态；完整历史和附件只在折叠区展开。无账本实体时显示
`not_provided`，不能猜测“根因候选”。

## 5. 与现有能力的关系

- 复用已有 `analysis-run/step/claim` 和 `diagnostic-report`，不创建第二套 run；
- 复用 `code-gdb-plan` 输出的真实 source/condition/watch，不在 S2B 固化 FCTA/FCTB 变量；
- 复用当前 source 的 `RteComMapping_WriteSignal` 映射作为输出层线索，不把静态 signal 候选当 CAN Tx 事实；
- 复用 `runtime-debug-plan/run` 的 approval 和 `gdb-session.v1`，实验记录不执行 shell；
- Pi 通过 registry → generated `registerTool` → `pi_tool_bridge` 调度；直接 CLI 仅为 fallback；
- `analysis-run-read` 在交互短名单中，追问可以读取同一 run 的状态和历史。

## 6. MVP 验收

1. 同一 run 可创建并更新一个 hypothesis，状态变化和证据 refs 可追溯；
2. 同一 run 可先记录实验计划，再记录 partial/completed 结果，不能绕过计划直接伪造完成；
3. 用户可把 VSCode/GDB 文本或截图作为 user observation 回填，报告不把它当作 runtime 真值；
4. Pi catalog 自动出现三个原子能力，`runtime-debug-run` 的执行审批不受影响；
5. 详细 HTML/JSON 能看到过程卡片，且静态事实、runtime 事实、用户观察和 AI inference 分层；
6. 当前 CRGVI-1829 仍不会因为有 Hypothesis/Experiment 就被写成正报、误报或根因确认。

## 7. 非目标与后续

本切片不实现：自动假设生成、自动实验选择、Live Workbench 拖拽、跨用户协作、直接从截图
识别变量、自动修改 arbe。下一阶段再接入：`HypothesisManager` 的 evidence coverage 排名、
最小成本实验推荐、用户 accept/question/irrelevant decision 和 runtime artifact 自动回填。
