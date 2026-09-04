# CR60 统一平台 Sprint 规划

版本：`sprint-plan.v2.3`  
日期：`2026-09-01`  
前置：[PRD](../CR60_PI_UNIFIED_PRD.md) · [调研报告](../CR60_PI_UNIFIED_RESEARCH_REPORT_2026-08-26.md) · [实施方案](CR60_PI_UNIFIED_IMPLEMENTATION_PLAN.md)

## 1. 规划原则

- 每个 Sprint 都能独立验收；
- 先读、后写；先静态、后 runtime；先单数据、后批量；数据传输是每次环境准备的第一步；
- 先打通 contract，再增加能力；
- SGU/HILMODEL=2 与 point-cloud/150–200 帧为不同 Sprint 路线；
- Pi 负责编排，工具负责确定性执行；
- 任何未验证的 runtime 能力都必须显式标记；
- Sprint 完成必须有文档、代码、测试、artifact 和 handoff。

## 2. Sprint 总览

| Sprint | 名称 | 目标 | 主要交付 |
|---|---|---|---|
| S0 | Docu Dev 基线 | 固化需求、调研、架构和开放项 | PRD、调研、系统/模块/软件设计 |
| S1 | Pi + Sprint1 接入 | Pi 可调用独立 harness 做静态预检查并逐帧浏览公共证据 | `cr60_sprint1_precheck`、bundle/model/report |
| S2 | Geometry Evidence | 修正坐标和几何证据层 | ego/target/ROI contract、collision gate |
| S3 | SGU Runtime MVP | HILMODEL=2 下自动捕获功能运行时变量 | GDB/MI2、runtime trace、runtime HTML |
| S4 | Point Cloud Runtime | 支持 150–200 帧点云预热和 tracking | warm-up/replay/track trace |
| S5 | Batch Runtime | 多数据、多功能、多次报警、多 radar | batch runtime orchestration |
| S6 | Pi Diagnosis Loop | 运行时证据驱动的解释、排序和反馈 | compare/hypothesis/memory |
| S7 | Replay Parity | 正式 GUI/player 与自动回放一致性 | replay shim、ACK/scene parity |

## 3. S0：Docu Dev 基线

### 目标

建立需求→调研→方案→实施→验收→handoff 的文档主线。

### 任务

- [x] 记录两个前置 skill 的职责和边界；
- [x] 记录 `radarAnalyze` 当前 Pi/能力注册基础；
- [x] 记录 `cr60-debug-harness` Sprint1；
- [x] 记录 HILMODEL=2/SGU/point-cloud 差异；
- [x] 记录当前几何证据缺口；
- [x] 记录用户确认的“数据传输→切子仓→车型/COEM/CUDA→编译→bash start→导入播放→headless GDB”流程；
- [ ] 评审本文件和开放问题；
- [ ] 形成首个实施 handoff。

### Gate

没有评审通过前，不修改远程 arbe，不做 GDB attach。

## 4. S1：Pi + Sprint1 接入

### 目标

让 `radarAnalyze/pi` 能调用独立 `cr60-debug-harness`，不重复实现 bag 解析和 HTML。

### 任务

- [x] 实现材料/环境前置输入 contract：`cr60-analysis-intake.v1`、`arbe-preflight.v1`；
- [x] 实现数据传输前只读校验：`cr60-data-prep-verify`（路径映射、文件 size/hash、可选目标对比）；
- [x] 增加 `cr60-data-transfer` approval-gated 上游脚本 adapter（未批准不执行）；
- [x] 增加当前 source/CUDA 和仿真适配的只读解析原子能力：`arbe-source-resolve`、
  `arbe-cuda-resolve`、`arbe-patch-plan`；
- [x] 实现 `Cr60HarnessProvider` CLI adapter；
- [x] 增加 `cr60-precheck` BaseModule；
- [x] 增加 input/output schema 校验；
- [ ] 将 `diagnosis-bundle.v1` 注册为 artifact；
- [x] 传递 event/frame/target/index/breakpoint pack；
- [x] 支持单条和批量；
- [ ] 支持 report refresh；
- [x] fake subprocess/contract 测试；
- [x] Pi 工具目录自动发现。

S1 前置绑定增量验收：版本/ref、CUDA/config 和仿真适配检查均从当前远程 source 读取；
只读扫描已在 `10.190.171.44:/home/hoz2wx/CR60LIGHT/cr60_light_arbe` 实测，未执行
checkout、fetch、cp、YAML 写入或编译。source/workspace dirty 和缺失的真实
`taskTime, taskTime` 调用被保留为 `partial`/`needs_action`，不能被误报成“可以安全编译”。

S1 前置绑定增量验收：版本/ref 和 CUDA/config 解析均从当前远程 source 读取；只读扫描
已在 `10.190.171.44:/home/hoz2wx/CR60LIGHT/cr60_light_arbe` 实测，未执行 checkout、
fetch、cp、YAML 写入或编译。source dirty 作为 `partial`/后续 approval gate 保留，不能
被误报成“可以安全切换”。

### 验收

```text
pi → cr60-precheck → harness CLI → bundle/model/report
```

必须验证：

- HTML 不被反向解析；
- ready/blocked/unsupported 分开；
- source/data provenance 未丢失；
- harness 独立 CLI 无回归；
- 参数和 path 不依赖 Windows 特定路径；
- 新增工具自动进入 `CapabilityRegistry`。

## 5. S2：Geometry Evidence

### 目标

先把当前 HTML 的几何语义修正，再接 runtime geometry。

### 任务

- [ ] 解析/确认 ego coordinate origin；
- [ ] 使用 `bumper2RearAxle_dist` 定义自车边界；
- [ ] 分离 `radar_id` 和 `radar_pos`；
- [ ] 统一 target `adasObjPloyCal` contract；
- [ ] 统一 ROI point order/num/side；
- [ ] 增加 transform chain；
- [ ] 增加 source-derived 标记；
- [ ] 增加 `not_evaluated` collision gate；
- [ ] geometry unit tests/golden fixtures。

### 验收

- 自车框与当前源代码坐标原点一致；
- 目标 yaw 与四角顺序一致；
- source-only ROI 不显示为已碰撞；
- 缺少 runtime geometry 时页面明确展示缺口；
- `radar_id/radar_pos` 不再互相替代。

## 6. S3：SGU Runtime MVP

### 目标

优先实现按实际算法 `frameID` 预热 3–5 帧、不依赖 150–200 帧点云预热的 SGU 目标注入运行时调试；headless GDB 是首选，VSCode ROS: Attach 作为人工兜底。

### 任务

- [x] `arbe_context_probe` 的只读首版 `arbe-preflight`；
- [ ] `HILMODEL=2` source/build/binary 校验；
- [ ] 验证 `PF_BUILD_FUNTEST_SGU_INJECTION`；
- [ ] 标准 `bash start` 后的 headless GDB/MI2 attach；launch-under-GDB 作为 existing PID attach 受限时的备用；
- [x] `runtime-debug-attach` formal existing-PID 原子 runner：node/PID/executable 校验、GDB
  symbols 加载、attach failure fail-closed 和不回放保护；
- [ ] 在当前服务器权限策略下形成正式 PID 的 runtime 变量证据（本轮已验证为
  `ptrace_scope=1` 阻断，不能以 blocked 结果替代成功）；
- [x] 隔离 ROS master 下的 launch-under-GDB + 真实 bag 单数据 smoke（作为正式 attach 的安全 fallback 验收）；
- [x] 通用 GDB service 的 plan/approval 边界；真实 MI2 session 仍在本 Sprint 后半段；
- [ ] 单 radar/单数据/单 event；
- [x] capture `frame_counter`/`frameID`；
- [x] capture raw SGU index/algorithm index/feature index（当前真实样例已捕获 `i=0`；无唯一映射时仍保留缺口）；
- [x] capture `sObj`/`objInfo->trcOutData[i]`；
- [x] capture `g_egoCarInfo`/`g_egoCarAddInfo`；
- [x] capture `objPoly`/`adasRoi`/FCTA variables（当前隔离 GDB 样例）；
- [x] compare short/standard warm-up and record derived-state drift；
- [x] preserve `recorded_raw`/`replay_algorithm`/`runtime_with_frame`/`gdb_observation` layers；
- [ ] generate functions, expressions, side mapping and output-field mapping from current schema；
- [x] runtime evidence normalize/validate/merge；
- [x] `runtime-debug-plan.v1`：事件/source/preflight readiness gates、真实断点、capture fields、GDB commands 和 VS Code handoff；
- [x] `runtime-debug-run` approval-gated adapter：按 plan 调用 sibling 隔离 GDB runner，并生成 `gdb-session.v1`；
- [x] HTML runtime badge、同帧 fields/geometry/call-chain 和 Pi deterministic values；

### 验收

```text
同一 source/binary/data 下：
Sprint1 event → runtime plan → GDB hit → runtime trace → HTML
```

必须能回答：

- 实际命中哪一帧；
- 哪个函数产生/消费报警；
- 哪个 radar、`radar_pos`、`i/k` 和 objID；
- FOV/ROI/TTC/DDCI 哪个条件实际满足；
- runtime 变量是否 `<optimized out>`；
- GDB 是否影响回放；
- 是否完成 teardown。

## 7. S4：Point Cloud Runtime

### 目标

验证点云、过滤、聚类、跟踪到 ADAS 的完整运行链路。

### 任务

- [ ] `PointCloudReplayStrategy`；
- [ ] configurable 150–200 frame warm-up；
- [ ] warm-up readiness/gap/reset/ACK；
- [ ] dot/filter/cluster/track probe；
- [ ] target lifecycle and ID change；
- [ ] alarm pre/post window；
- [ ] runtime geometry；
- [ ] performance/perturbation record。

### 验收

- 不把 SGU 的 3–5 帧策略误用于点云；
- 预热不足明确 blocked/not-ready；
- 可以区分 perception/tracking/situation/FCT 证据；
- 输出连续帧 runtime trace。

## 8. S5：Batch Runtime

### 目标

批量处理文件夹内所有数据，并对每条数据隔离 runtime session。

### 任务

- [ ] 每数据独立 `run_id/session_id`；
- [ ] 每数据独立 radar/mode/source/binary identity；
- [ ] 多功能、多次报警队列；
- [ ] runtime job poll/retry/resume；
- [ ] blocked case 不影响 ready case；
- [ ] batch HTML index；
- [ ] 静态/runtime 差异摘要。

### 验收

- 一个数据失败不会停止整个批次；
- 每个 runtime 值能追溯到具体数据和事件；
- 运行失败仍保留 Sprint1 报告；
- 不串用另一条数据的 GDB 状态。

## 9. S6：Pi Diagnosis Loop

### 目标

让 Pi 使用 runtime evidence 做解释和后续动作建议。

### 任务

- [ ] 静态/runtime compare；
- [ ] hypothesis ranking；
- [ ] next action tool；
- [ ] 人工反馈；
- [ ] variant/source freshness；
- [ ] 运行时知识发布；
- [ ] 失败和冲突解释。

### 验收

- AI 不能覆盖 deterministic evidence；
- 过期知识不进 prompt；
- 每条假设引用 evidence refs；
- 结论能区分 observation、inference 和 next verification。

## 10. S7：Replay Parity

### 目标

在自动 direct replay 与正式 GUI player 之间建立一致性验证。

### 前置

- 正式播放器 load/play/seek 控制面；
- 算法 frame ACK 语义；
- 多 radar scene mode；
- camera/warning/CAN 辅助消息同步。

### 验收

- 相同输入、相同 source/binary 时，frame/target/warning 结果可对齐；
- ACK、时间轴、reset 和辅助消息状态可解释；
- direct rosbag play 的差异不会被隐藏。

## 11. 每个 Sprint 的 handoff 模板

```text
目标：
已完成：
未完成：
代码/文档：
输入契约：
输出 artifact：
测试结果：
现场验证结果：
已知缺口：
风险：
下一 Sprint 前置：
用户需要确认：
```

## 12. 2026-08-27 实际验收门

- S1 文件夹批量已验证：远程 `CRGVI-1829` 自动发现 5 条 bag，149 个 event，5/5 ready；
- `replay.strategy=auto` 已根据 `lgu_streams` 选择 SGU/LGU 5 帧，点云仍保持 150–200 帧；
- 公共 direct replay 已验证 `PLAY_RC=0`、`warning_status_with_frame` 真实非零输出；
- 隔离 launch-under-GDB 已验证 `PLAY_RC=0`、`GDB_HIT_COUNT=1`，并分别支持
  `radar1/frame47840` 与 `radar2/frame47875` 的真实对象循环 `i/objID`；
- `radar2/frame47875` 已捕获 `objID=44/i=0`、对象 flag 4→5、真实 `objPoly`、`adasRoi`、
  `fTTC/fDDCI/fInterX/fInterY` 和下游 handler；
- 短 SGU/LGU 预热已重现功能输出，但发现派生 `radius` 漂移，新增 `warmup_sensitive`
  作为通用 runtime 证据状态；
- `runtime-debug-plan` 已在真实 `FCTA_R/radar2` 事件上生成 16 个 breakpoint（其中 source-condition
  8 个）、45 条 GDB command、66 个 capture fields，并将 `target_identity`、nearest-LGU 首帧、dirty source、binary
  fingerprint 和 approval 分别呈现为 readiness gates；
- plan-bound GDB expression 已改为逐表达式可恢复 probe：真实回放中 9 个作用域不可见
  watch 被标为 `not_found`，但后续 handler 仍命中并得到 `i=0/objID=44`；每次回放的
  `RESULT_PREFIX` 进入 session `run_id`，支持同一 plan 多次执行比较；
- `pi-context` 已支持从已校验 merged diagnosis bundle 继续编排，自动保留 bundle 的
  data/source provenance，不要求重复构造 intake；
- 正式 runtime 现场验证：`arbe-formal-start` 检测到 9 个外部已有节点并返回
  `already_running/ownership=external`；`runtime-debug-attach` 定位 radar2 PID
  `3662064`、executable match，但因 `ptrace_scope=1` 返回 `blocked`，没有回放/变量误报；
- 录制 raw warning、算法 with-frame 输出和 GDB 观测已按证据层分开记录；
- 以上不等于正式 workspace 的 `catkin_make`、`bash start`、existing-PID attach 或 GUI
  player parity；这些仍需独立审批和 runtime Sprint 验收。

## 13. DDD/Pi-first gate（2026-08-27）

Sprint 任务必须引用
[DDD 用户故事与验收基线](CR60_PI_DDD_REQUIREMENTS_AND_ACCEPTANCE.md)中的 `US/AC`。
Pi 是唯一产品入口；新增能力必须从 catalog 生成 Pi `registerTool`，通过
`pi_tool_bridge` 执行，并有 deterministic test。直接 CLI、AgentLoop、ReAct 只作为
开发/离线 fallback。

当前已补齐的前置门：

- `US-011` 的 typed artifact composition 与 `pi-context` 上下文契约；
- Extension 参数透传、显式加载和 Windows 进程清理；
- 实际 Pi RPC 以及实际 `pi-context` tool invocation。

当前仍是 `partially-verified` 的门：正式 arbe workspace 的 build/start/attach、
public replay 与 GUI player parity、point-cloud runtime，以及由当前 source/runtime schema
自动生成所有功能的 capture expressions。runtime HTML merge 的 CRGVI-1829 样例已通过，
但不能替代正式 GUI player parity 或最终 CAN Tx 验收。

## 14. 2026-08-30 架构纠偏后的优先级

现有 S0–S7 继续保留为能力路线，但下一阶段不优先增加更多散装工具，也不直接跳到最终 AI
根因/代码修复。先把已有静态、代码、runtime 和报告能力组织成可见、可恢复的调查流程。

### S1A：Analysis Ledger 与阶段性结果

目标：用户从第一条有效线索开始持续获得价值。

- [x] `analysis-run.v1`、`analysis-step.v1`、`claim.v1`；
- [x] `analysis-ledger-event.v1` 及 planned `hypothesis.v1` / `debug-experiment.v1` 契约；
- [x] append-only ledger、原子 checkpoint、ID/lifecycle/accuracy gate；
- [x] Pi `registerTool` 暴露 run/read/update、step begin/complete、claim append；
- [x] 使用 CRGVI-1829 已有 artifact 恢复一条可读 AnalysisRun；
- [x] Pi tool-end 对现有 intake/precheck/code/runtime 调用落可见 step；
- [ ] claim/gap/conflict 引用现有 artifact；
- [ ] 用户 accept/question/irrelevant decision；
- [x] 基础中断后 resume：复用 `analysis_run_id` / Pi session，并把 `analysis-run-read` 纳入交互短名单；
- [x] HTML 增加 Analysis Trail：显示结构化阶段摘要、observations、gaps 和 next actions，不显示隐藏思维链。

验收：任何阶段失败仍能看到此前发现；最终报告能回链到每个 step，不重新推断事实。

### S1B：EventCodePath 与 Debug-ready

目标：从一个事件直接形成 output→feature→situation→target→input 调查链。

- [x] `event-code-path.v1` 的 generic engine/module 和 schema；
- [x] 参数依赖和当前事件静态条件引用；
- [x] runtime-required token/gap 投影；
- [x] 一次性 `code-context-refresh/read` 作为当前 source index 输入；
- [ ] 五层代码面板；
- [x] root breakpoint/watch group 计划（仍未执行 GDB）；
- [ ] Time to Debug-ready 指标。

验收：用户无需全仓搜索即可复制真实断点，并理解每组变量能排除什么。

### S1C：三个用户出口纵向切片（2026-09-01）

目标：把已完成的静态、代码、runtime 和账本能力交付成一条可用的 Pi 工作流，而不是继续
增加平铺工具。

- [x] 批量预检查沿用 `cr60-precheck`，保留每条数据一个 bundle/viewer/HTML 和 batch index；
- [x] `evidence-query`：按功能、侧别、radar、event、frame 和真实字段路径做有界查询，缺失字段
  返回 `not_available`；
- [x] `diagnosis-report`：将 bundle/viewer/runtime/code/AI 结果投影为
  `diagnostic-report.v1`、Markdown 和 HTML companion；
- [x] Pi catalog/registerTool 自动暴露 bounded leaf capabilities，不修改总编排器；
- [x] Pi 单轮/交互轮次自动写入 Analysis Ledger，持久 session 使用同一 run/session ID；
- [ ] Pi 真实模型长链路在现场自动完成“批量→选事件→详细报告→追问”验收；
- [ ] 现有 sibling viewer 增加 Analysis Trail 的交互投影（当前已先交付独立 companion）。

验收：用当前 CRGVI-1829 artifact 能生成 batch 入口、FCTA/FCTB 等任意事件的详细报告，
可以查询目标/自车/代码字段；未提供 runtime 或无法证明同帧时报告只显示缺口，不升级为最终根因。
Pi 对话中断后使用同一 `analysis_run_id` 能继续读取历史步骤。

### S1D：条件证据和场景化详细报告（2026-09-01）

目标：让详细报告回答“报警时刻有哪些事实、当前代码条件如何代入、哪些条件仍缺证据”，并以
当前坐标契约绘制自车、目标朝向和有效 ROI。该切片不为任何功能增加固定规则。

- [x] `condition-trace.v1` safe evaluator + Pi atomic tool；
- [x] `diagnosis-report` 自动消费 condition trace；
- [x] 条件状态表（satisfied/not_satisfied/not_evaluable/unsupported）和 source/binding；
- [x] ego/target/heading/ROI scene SVG，缺 runtime 几何时明确 not_evaluated；
- [x] CRGVI-1829 单数据条件/HTML 验收；
- [x] 证据缺口和下一步可转 public runtime/GDB 计划。
- [x] `memory-recall` 接入既有 MemorySystem，代码型记忆 freshness 不满足时 fail closed。
- [x] `memory-recall` 可从显式 `pi-orchestration-context.v1` 读取 variant/memory scope，不读取隐式默认车型记忆。

完成条件：报告不依赖固定 FCTA/FCTB 字段，所有可见数值有 token/source/status，缺值不被判为
条件失败；AI 只能解释 condition trace。

### S1E：跨证据报警时间线和结论发布门（2026-09-01）

目标：把原始报警、播放帧、回放、公共运行态、GDB 和 CAN 的事实投影到同一份详细报告，
同时明确“报告可生成”和“根因/正误报已确认”不是同一个状态。

- [x] `alert-timeline.v1` 通用 engine/module/schema；
- [x] `recorded_raw`、`replay_algorithm`、`runtime_with_frame`、`gdb_observation`、
  `can_tx_observation` 五层独立显示，缺层不伪造；
- [x] `playback_frame_map` 显示 warm-up、selected/context frame 及同帧可绑定报警信号；
- [x] 对同一证据层的逐帧 warning value 做 0→非零/非零→0 transition 投影；首个采样为 active 时不伪造 rising；
- [x] 只有两侧均有 observed exact frame 才输出 `same/different`，否则 `not_evaluated` 或
  `not_comparable`；
- [x] data/source/binary identity conflict gate 接入 timeline/report；
- [x] `diagnostic-report.v1.conclusion` 输出 `facts_only`、`supported_hypothesis`、
  `confirmed`、`blocked` 的结论等级；当前无 runtime/CAN 时保持 `facts_only`；
- [x] exact runtime observation 回填 condition trace，跨帧/时间近邻仍不绑定；
- [x] CRGVI-1829 实际单数据报告重新生成并验证 timeline/结论区块；定向测试通过；
- [ ] replay/public/GDB/CAN 五层联合现场验收；
- [ ] 用户可在 Workbench 中对 timeline 行/claim/hypothesis 做确认或质疑。

验收：静态报告必须把当前数据已知事实和未提供层明确展示；不允许把
`report.status=ready` 解释为最终正报/误报或根因确认。

### S2A：arbe Public Runtime Collector

目标：复用正式工具逐帧公开信息，减少 GDB。

- [ ] BagReader event/scene/ACK adapter；
- [ ] `warning_status_with_frame` schema；
- [ ] `radar_info` positional schema；
- [x] 公共 runtime 行归一化原子能力和 `runtime-snapshot-with-frame.v1`；
- [x] 明确 `frame_verified` / `callback_correlated` / `publication_correlated` / `unbound` association quality；
- [x] 将该 SSH replay/capture 收敛进既有 `sim-verify` remote mode（不新增 Pi tool）；
- [x] `objectlist` 公共输出已随 remote capture 采集，并保留 message sequence；
- [x] 通过既有 `runtime-evidence-normalize` 接入 `runtime-snapshot-with-frame.v1`；
- [x] preflight 按当前 COEM 全量扫描 source Tx mapping，并输出 `RteComMapping → RteLite → Com_SendSignal` 候选；
- [x] preflight 静态证明 objectlist handler 在 `warning_status_with_frame` 之前发布，`auto` 关联模式无证明时退回 strict；
- [x] `runtime-evidence-compose` 合并公共 runtime 与 GDB producer，保留多 producer provenance；
- [x] 通过既有 `runtime-evidence-merge` 支持 event/frame/object scope，避免全量快照 merge；
- [ ] 评审 `runtime_snapshot_with_frame` 最小 bridge。

验收：warning/radar_info 使用消息自带 `frameID`；objectlist 默认严格不绑定，只有当前 source
证明同周期发布顺序且显式选择 `publication_order` 时，才输出 derived `publication_correlated`，
并保留 message sequence/依据；不做时间近邻假绑定。run5 已验证可消费的 derived 目标属性，
run6 已证明 recorder 顺序不稳定，因此该阶段仍不能宣称 object 与报警 frame 的绝对同帧；
必须完成 callback/stamped collector 或 GDB 精确读取后，S2A 才达到 exact-frame 验收。

### S2B：Hypothesis Board 与协同 Debug

目标：AI 和用户共同用实验收敛根因。

- [x] `hypothesis.v1` / `debug-experiment.v1` 持久化原子能力；
- [x] `user-observation.v1` 用户 VSCode/GDB/截图/备注回填能力；
- [ ] public/runtime/GDB/VSCode experiment；
- [x] 支持/反证引用、缺口和 Hypothesis 状态历史；
- [x] 人工 debug 回填进入独立 user-observation 层，不覆盖 runtime；
- [ ] Live Workbench 三栏布局；
- [x] Snapshot HTML 同模型投影（Analysis Trail / Hypothesis Board / Next Experiments）。

验收：新证据会可见地改变候选状态；工具不会只给最终代码方案。

### S3A：ProjectCapabilityManifest 与 Gen6 接入

目标：统一骨架适配不同六代项目，不共享错误业务假设。

- [x] manifest builder（唯一入口 `project-capability-manifest`，不替代 `pi-context`）；
- [ ] parser/source/feature/replay/runtime/geometry/panel SPI；
- [ ] capability pack 动态短名单；
- [ ] 至少两个不同 Gen6 项目；
- [ ] 无报警/报警/runtime/缺输入/版本变化验收矩阵。

### S3B：根因、调参和修复复验

前置：S1A/S1B/S2A/S2B 完成。

- [ ] 根因发布门；
- [ ] 参数 what-if 和真实动态依赖；
- [ ] 修复副作用/回归范围；
- [ ] replay comparison；
- [ ] 用户确认与 freshness-bound knowledge。

### 新增跨 Sprint 指标

```text
Time to First Useful Clue
Time to Debug-ready
Evidence Coverage
Unresolved Critical Gaps
Bag Full-read Count
Replay/GDB Attempts
User Intervention Count
Hypothesis Reduction per Experiment
```
