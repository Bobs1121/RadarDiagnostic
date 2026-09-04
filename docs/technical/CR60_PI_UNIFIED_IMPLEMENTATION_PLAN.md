# CR60 统一平台实施方案

版本：`implementation-plan.v2.3`  
日期：`2026-09-01`  
状态：现有静态/runtime/Pi 基础保留；完成三出口纵向切片并进入现场长链路验收  
前置：[调研报告](../CR60_PI_UNIFIED_RESEARCH_REPORT_2026-08-26.md) · [PRD](../CR60_PI_UNIFIED_PRD.md) · [系统设计](CR60_PI_UNIFIED_SYSTEM_DESIGN.md)

## 1. 实施原则

1. 先建立契约和只读适配器，再做远程副作用；
2. 先接现有能力，再补缺失能力；
3. 先单数据、单 radar、单目标，再批量和多 radar；
4. 先 SGU/HILMODEL=2（按 `frameID` 预热 3–5 帧），再点云 150–200 帧回放；
5. 先 runtime evidence，再 AI 根因解释；
6. 不在 `radarAnalyze` 复制 `cr60-debug-harness` 的 bag/HTML 实现；
7. 不在统一平台复制两个前置 skill 的数据拷贝、切分支和编译脚本；
8. 每个阶段可单独验收，失败保留 artifact，不阻塞其他 ready case；
9. 外部副作用必须有审批、日志、回退和 teardown；
10. 设计文档是交互主线，代码修改必须引用对应设计和验收项。

## 2. 复用资产和改造边界

| 现有资产 | 复用方式 | 不做的事情 |
|---|---|---|
| `radarAnalyze` Pi/AgentLoop/ReAct | 统一规划和工具调用 | 不再创建第二套 Pi |
| `MODULE_REGISTRY/TOOL_REGISTRY` | 新工具自动注册 | 不用 prompt 硬编码工具目录 |
| `BaseModule/ModuleResult` | JSON 结果和 fail-soft | 不跨模块共享可变全局状态 |
| `ArtifactRegistry` | 中间产物索引 | 不把大 payload 塞入内存 registry |
| `project_context/freshness` | 多项目和代码新鲜度 | 不跨 variant 回退旧知识 |
| `cr60-debug-harness` | Sprint1 静态解析和 HTML | 不复制 parser/viewer |
| `bosch-data-transfert` | 数据准备和上游 handoff | 不重写复制器 |
| `cr60light-arbe-build` | workspace/version/CUDA/build/start | 不让 Pi 直接调用任意 shell |
| `engines/arbe/sim-verify` | trace/KPI 解析 | 不承担 GDB 全生命周期 |
| 当前 arbe source | 实际运行被测系统 | 不把测试补丁当正式算法改动 |

## 3. 交付包和目录

### 3.1 radarAnalyze 新增

```text
ai/modules/cr60_precheck.py
ai/modules/cr60_runtime_debug.py
ai/modules/arbe_control.py
ai/modules/geometry_evidence.py
ai/modules/evidence_merge.py

ai/tools/cr60_tools.py
ai/tools/arbe_tools.py
ai/tools/runtime_debug_tools.py
ai/tools/evidence_tools.py

ai/orchestration/run.py
ai/orchestration/state_machine.py
ai/orchestration/checkpoints.py
ai/orchestration/approval.py
ai/orchestration/recovery.py

ai/providers/cr60_harness_adapter.py
ai/providers/remote_arbe.py
ai/providers/ros_replay.py
ai/providers/gdb_mi.py

contracts/cr60-analysis-intake.v1.schema.json
contracts/analysis-context.v1.schema.json
contracts/runtime-debug-plan.v1.schema.json
contracts/runtime-trace.v1.schema.json
contracts/orchestration-run.v1.schema.json
```

### 3.2 不立即新增到 arbe

第一阶段不改 `algo_source` 功能逻辑。只有当运行时证明需要低侵入的公共结构 ring buffer 时，才在用户明确批准的 arbe feature branch 中增加默认关闭的 `debug_probe`。

## 4. 工作包

### WP-00：文档与契约基线

交付：

- 本调研报告；
- PRD；
- 系统/模块/软件设计；
- schema 初版；
- 决策和开放问题清单。

验收：所有关键事实均能回到仓库、skill、source snapshot 或明确的 runtime_required 项。

### WP-01：Pi 工具注册和 RunSupervisor

内容：

- 已完成统一 CR60 模块的 catalog/`BaseTool` 受控桥：`cr60-intake`、`arbe-preflight`、`cr60-precheck`；
- 增加 run_id/session_id；
- stage 状态机；
- checkpoint/artifact/event log；
- 工具 risk/approval/timeout/retry 元信息；
- `ModuleResult` 与 tool result 之间的桥；
- Pi 只能调用注册工具。

验收：fake tools 能按依赖顺序执行、暂停、恢复、失败和重试。

### WP-02：前置能力 adapter

内容：

- `bosch_data_prepare` adapter；
- `cr60-data-prep-verify`（当前只读实现）；
- `cr60-data-transfer`（当前 approval-gated 上游脚本 adapter）；
- `arbe_context_probe`；
- `arbe_version_resolve`（当前只读实现：`arbe-source-resolve`）；
- `arbe_cuda_resolve`（当前只读实现：`arbe-cuda-resolve`）；
- `arbe_patch_plan`（当前只读实现：`arbe-patch-plan`）；
- 将 skill 输出转换为 `cr60-analysis-intake.v1`/`analysis-context.v1`。

用户确认的执行顺序是数据传输优先：数据进入 Linux 后，先解析数据绑定的软件版本、COEM 和车型，再解析子仓 tag/branch、CUDA 表和配置。不能先按服务器默认配置编译，再用数据去适配。

验收：只读模式不修改远程；缺失 host/workspace/tag/model 时返回 blocked；用户确认信息进入 artifact。

当前增量验收证据：

- `tests/test_arbe_source_resolve.py`、`tests/test_arbe_cuda_resolve.py`：计划态、正常扫描、
  缺输入、ref 冲突、dirty 和 Pi catalog/registerTool 注册；
- `tests/test_cr60_data_prep_verify.py`：Linux/UNC/Windows 路径边界、源/目标 size/hash
  对比、重复 case 的 entry identity、blocked intake 和 Pi catalog 注册；
- `outputs/arbe_source_resolution_current_20260830.json`：
  `10.190.171.44` 当前 `algo_source` 的 HEAD 为
  `a81b08a38f316a3d25bfcbcad6dcfc822d24b990`，exact tag 与材料派生的
  `BYD_UKE_BL03RC02.7` 一致，local/remote tag 均存在，但 source dirty，状态为 `partial`；
- `outputs/arbe_cuda_resolution_current_20260830.json`：当前 `BYD_UKE` 只有一个真实 CUDA
  候选，sha256 为 `a555d8a5a86e7a26c6671f9eb8838d6f4e360d803219a7b6fad71360ea315856`，
  YAML `xlsx_path/xlsx_sheet/type` 与候选及 `03_QZH` 对齐，状态为 `ready`。
- `outputs/arbe_patch_plan_current_20260830_v4.json`：当前 outer/algo 均 dirty；
  `BUILDMODEL=2`、`HILMODEL=2` 和文件存在，但 GUI 调用没有真实
  `taskTime, taskTime`，因此状态为 `needs_action`；可选 SGU define 也未发现，均未被
  自动修改。
- `outputs/cr60_data_prep_verify_CRGVI1829_20260830.json`：用户给出的真实 bag 在
  `10.190.171.44` 可达，size/hash 已记录；未设置 destination，因此没有把“可读”误报成
  “已完成传输”。
- `outputs/cr60_data_prep_verify_CRGVI1829_folder_20260830.json`：同一数据目录实际发现
  5 个 `.bag`，目录扫描和逐文件 hash 均通过；仍未执行复制或目标目录校验。

### WP-03：Sprint1 adapter

内容：

- `cr60_sprint1_precheck`；
- `cr60_report_refresh`；
- 调用独立 harness CLI；
- 直接消费 bundle/model，不解析 HTML；
- 将 event/frame/target/index/breakpoint pack 交给 runtime plan。

验收：单条和批量都能从 Pi 调用；ready/blocked/unsupported 分开；harness 仍可独立运行。

### WP-04：几何 evidence contract

内容：

- 修正 ego axis/origin/`bumper2RearAxle_dist` 语义；
- 分离 `radar_id`/`radar_pos`；
- `objPoly`、`adasRoi`、`fInter*` 字段定义；
- source-derived 与 runtime-observed 两套表示；
- collision gate。

验收：无 runtime polygon/ROI 时页面显示 `not_evaluated`，不会输出假碰撞；source ref/坐标/单位完整。

### WP-05：SGU/HILMODEL=2 runtime MVP

内容：

- `runtime_mode=sgu_injection`；
- 按实际算法 `frameID` 在目标事件前预热 3–5 帧；
- HILMODEL/source/binary/build macro preflight；
- 等待标准 `bash start` 产生的 `arbe_gui` 和 radar1/2/3/4 visualization_engine ready，完成目标数据导入后再 headless GDB/MI2 attach 和断点设置；launch-under-GDB 仅作为 existing PID attach 受限时的备用；
- 单 radar/单事件；
- 捕获 `frame_counter`、`frameID`、objID、SGU index、algorithm index；
- 捕获 `sObj`、`objInfo->trcOutData[i]`、`g_egoCarAddInfo`、ROI 和报警输出；
- 探测并尝试捕获用户定义的 CAN 输出链：`RteComMapping_TxRunnable_FuncSignal`、宏展开后的 `RteLite_Write_<signal_token>`、`Com_SendSignal` 和实际 signal token；
- 写入 runtime trace 并更新 HTML。

报警 event 的 selected first frame 默认要求观测算法内部 CAN Tx 链路的输出位上升沿；`/corner_radar/warning_status_with_frame` 只作为前级算法输出代理；`/corner_radar/warning_status` 是无显式 frame 的算法侧回退；`/corner_radar/warning_status_raw` 单独作为 CAN/ECU 侧证据，不与算法 event 混合。若当前 visualization host 没有执行 CAN Tx 调度，报告必须标记 `can_tx_unobserved`。

用户确认首版 runtime 以标准 `bash start` 后的 headless GDB attach 为主；当前 VSCode `ROS: Attach` 和 radar1/2/3/4 target 作为同一运行链的人工兜底。只有 existing PID attach 受限时，才切换到 launch-under-GDB。

验收：同一 source/binary/data 下，runtime 断点和 HTML 中的 frame/function/variable/stack 一致；GDB 失败时保留 Sprint1 结果。

### WP-06：点云 runtime

内容：

- `runtime_mode=point_cloud`；
- 150–200 帧可配置预热；
- warm-up gaps/reset/ACK 检查；
- dot/filter/cluster/track 采样；
- 报警前后连续帧；
- 记录 GDB 扰动。

验收：工具不会把 SGU 的 3–5 帧策略套到点云；能够区分 perception、tracking、situation 和 FCT 缺口。

### WP-07：运行时批量和多 radar

内容：

- 每条数据独立 session；
- 同一数据多功能/多次报警；
- 多 radar 依赖和 `radar_pos` 校验；
- 失败 case 隔离；
- batch report/index。

验收：单个 case 失败不阻塞其他 case；所有 runtime artifact 可回到对应数据和 source context。

### WP-08：Pi 解释和知识闭环

内容：

- runtime/bag/source 对比；
- 根因假设排序；
- 下一步断点建议；
- 反馈和 memory publish；
- freshness 门禁。

验收：AI 只解释已存在 evidence；过期 knowledge 不进入 prompt；冲突不被覆盖。

## 5. 依赖关系

```text
WP-00
  ↓
WP-01 ── WP-02 ── WP-03
                    ↓
                  WP-04
                    ↓
                  WP-05
                    ↓
                  WP-06
                    ↓
                  WP-07 ── WP-08
```

WP-03 之前不实现 GDB；WP-04 之前不把几何碰撞结论写入 HTML；WP-05 之前不声称“运行时变量已获得”。

## 6. 远程部署策略

### 本地 radarAnalyze 环境

需要：

- Python 依赖；
- Pi provider；
- harness root 配置；
- SSH client/credential reference；
- 本地输出目录。

### Linux arbe 环境

由用户指定，不假定只有 `10.190.171.44`：

- ROS/Noetic 或 profile 指定 distro；
- arbe workspace；
- `gdb`，可选 `gdbserver`；
- `debug_info` 和未 strip 的目标二进制；
- 当前 source/COEM/车型/CUDA；
- X/GUI 只在使用正式 GUI 时需要；
- 运行用户和 ptrace 权限。

服务器上不要求安装 radarAnalyze 全部代码，除非选用远程执行 harness；通常由本地控制器通过 SSH 调用已有 skill/脚本或 remote command。

用户已允许操作原始 arbe workspace，但该仓由其他人维护，后续运行之间可能发生内部接口变化。实现时必须在每次运行的数据传输、切仓、配置、编译、启动和 runtime 前后记录 outer/algo HEAD、dirty 状态、关键配置 hash 和 binary fingerprint；每次运行重新 source learn、重新检查接口兼容性和重新生成 GDB plan，不复用旧的字段偏移或函数签名。运行中默认代码不变，若意外变化则停止生成正式 runtime 结论，不自动 reset、revert 或覆盖他人改动。

## 7. 风险和停止条件

必须停止并返回文档化 blocker 的情况：

- 输入缺少服务器、workspace、代码版本或车型；
- 数据未能验证其软件版本、COEM 和具体车型绑定；
- tag/branch 有多个候选；
- dirty workspace 可能被覆盖；
- source/binary mismatch；
- HILMODEL 与 runtime plan 不一致；
- GDB symbols 缺失；
- ptrace 被拒绝；
- ROS node/PID 不能证明对应 radar；
- replay ACK/帧出现 gap；
- target 只能通过 time-near objectlist 推断；
- geometry 坐标原点或单位不确定。

## 8. 发布和回退

每个阶段产生独立 artifact，代码版本和 schema 版本同时发布：

```text
radarAnalyze release
cr60-debug-harness release
contracts version
skill version
runtime profile version
```

回退优先级：

1. 停止 runtime session；
2. 回退统一平台 adapter；
3. 保留并继续使用独立 Sprint1；
4. 不自动回退用户 arbe workspace；
5. 对已应用的远程 patch 使用记录中的逆向 patch 或备份恢复。

## 9. 当前实施记录（2026-08-26）

- 已实现 `engines/arbe/preflight.py` + `ai/modules/arbe_preflight.py`：只读 SSH
  预检、outer/algo HEAD、COEM/CUDA/config、`HILMODEL`、binary、GDB、ptrace、
  visualization PID/namespace/radar ID、显式 ROS setup/master、CAN Tx 源码候选；
- 已实现 `engines/arbe/intake.py` + `ai/modules/cr60_intake.py`：材料优先输入绑定、
  XLSX B/C/E/G/J 兼容、按 Ticket/数据文件名选行、候选 provenance、冲突/缺口
  fail-closed；
- 已新增 `contracts/cr60-analysis-intake.v1.schema.json`；
- 已实现无 GDB 公共证据原子能力 `public-topic-plan`/`public-evidence-audit`，以及
  `code-gdb-plan` → `gdb-service` 的解耦链；
- 截至 2026-08-28 radarAnalyze 全量回归为 `610 passed, 1 skipped, 2 xfailed`；真实服务器
  当前 preflight artifact 为 `outputs/arbe_preflight_current_20260828_v3.json`；
- 已实现 `arbe-formal-start`/`arbe-formal-stop`/`runtime-debug-attach` 的 plan/approval
  边界；正式 start 已验证已有节点保护，正式 attach 已验证 node/PID/executable 定位，
  但当前 `ptrace_scope=1` 阻断 runtime attach，不能标为成功。

## 10. 2026-08-27 实际验收增量

本次没有越过正式 workspace 的写入门，而是完成了可复现的实际验证链：

1. 新鲜 `arbe-preflight`：确认 server/workspace/source/COEM/CUDA/HILMODEL/binary/PID/GDB；
2. `cr60-precheck` 单数据：真实远程 bag → source-resolved decoder → bundle/HTML，
   `1 case / 34 events / ready`；
3. 数据模式判断：当前 bag 的 `lgu_streams` 证据使 `replay.strategy=auto` 选择
   `sgu_injection`，每事件 `5/5` 帧；点云输入保持 `150..200` 帧策略；
4. 公共 runtime：`ros-topic-inventory --sample-once` 区分 publisher 与实际消息；隔离
   direct replay 捕获 15 个非零 `warning_status_with_frame` 行；
5. 精细 runtime：隔离 launch-under-GDB 命中 `frame=47877/radar=2`，采集目标、ROI、
   FCTA/FCTB 和下游 handler，teardown 后正式 master 不受影响；
6. 代码能力：`code-analyze` 直接读取当前 source `code_index.json`，查询真实函数、
   28 个条件、75 个读取变量和 36 个写入变量；Pi typed ref 组合
   `code-gdb-plan → gdb-service(plan)` 已通过真实 source index 验证。

文件夹批量实际验收：对远程 `CRGVI-1829` 目录自动发现 5 条 bag，逐条生成报告，合计
149 个 event，全部 `ready`；各数据独立保存 bundle/viewer/HTML/CSV/handoff，不共享
运行时状态。当前 profile 的 `strategy=auto` 对这 5 条数据均根据 LGU 证据选择
`sgu_injection 5/5`。

新增实际 artifact：

```text
outputs/arbe_preflight_20260827.json
outputs/arbe_runtime_identity_20260827.json
outputs/code_analyze_actual_20260827.json
outputs/code_gdb_plan_actual_20260827.json
outputs/gdb_session_actual_20260827.json
outputs/pi_runtime_plan_acceptance_20260827.json
outputs/ros_topic_inventory_20260827_sampled.json
outputs/public_evidence_audit_actual_20260827.json
outputs/runtime_smoke_evidence_20260827.json
outputs/arbe_preflight_current_20260828_v3.json
outputs/arbe_start_session_formal_existing_20260828.json
outputs/gdb_session_formal_attach_CRGVI1829_FCTA_R_20260828_v7.json
outputs/runtime_fctb_formal_attach_blocked_normalized_20260828.json
outputs/radar_project_fctb_CRGVI1829_20260828_runtime_final_v2/
```

当前尚未完成且不能以本次隔离 smoke 代替的部分仍是：正式 `catkin_make` 自动控制、正式
GUI player parity、在权限允许后的 existing-PID runtime 变量采集、持续 MI2/runtime trace、
live collector、最终 CAN Tx 采集和 point-cloud runtime。runtime HTML additive merge 已在
CRGVI-1829 独立输出目录通过；正式 workspace dirty，执行其他动作前必须重新确认
target branch/车型/CUDA/仿真模式并通过审批。

本轮新增 runtime 交付：

- `engines/runtime_evidence.py`：GDB session/transcript/canonical artifact 的统一规范化、
  source/data/binary/event identity gate、同帧对象匹配和 additive merge；
- `ai/modules/runtime_evidence.py`：`runtime-evidence-normalize`、`runtime-evidence-validate`、
  `runtime-evidence-compose`、`runtime-evidence-merge` 四个 Pi 原子模块；
- `cr60-debug-harness/viewer_model.py` + web Runtime 面板：在精确 frame 上显示真实 GDB
  token/value/phase、调用栈、动态 ego/target、runtime `objPoly`/ROI；无同帧值不继承；
- `pi-context`：相同 runtime artifact 进入 `runtime.evidence` deterministic summary；
- 真实产物：`outputs/radar_project_fctb_CRGVI1829_20260827_runtime/`，merge `partial` 的
  唯一当前缺口是静态 bundle 未提供 binary fingerprint，以及 data fingerprint 表示不同。

## 11. 2026-08-27 DDD/Pi-first implementation gate

在继续扩大实现前，需求基线改为
[CR60_PI_DDD_REQUIREMENTS_AND_ACCEPTANCE.md](CR60_PI_DDD_REQUIREMENTS_AND_ACCEPTANCE.md)。
本轮实现必须先满足对应 US/AC，再进入下一个 Sprint；没有测试和现场 artifact 的条目
只允许标记 `specified` 或 `partially-verified`。

已完成的 Pi 基座收敛：

- `pi-context` / `pi-orchestration-context.v1`：显式绑定 intake/preflight/project/data/source/runtime/policy/freshness；
- `runtime-debug-plan.v1`：从当前 bundle/preflight 生成 source/data-bound readiness gates、断点、capture fields、GDB commands 和 VS Code handoff；
- `runtime-debug-run`：approval-gated adapter 按 plan 调用 sibling 隔离 ROS/GDB runner，自动产出 `gdb-session.v1`；
- `runtime-debug-attach`：approval-gated formal existing-PID adapter，重新发现 ROS node/PID、
  校验 `/proc/<pid>/exe`，ptrace 失败时产出 blocked session；
- `arbe-formal-start` / `arbe-formal-stop`：owned process-group lifecycle；已有外部节点不重复启动，
  stop 只接受 ownership 可证明的 session；
- `arbe-build`：approval-gated explicit `catkin_make` primitive，产出
  `arbe-build-session.v1`；不把 source/CUDA/start 逻辑耦合进 build；
- GDB expression marker：`CR60_GDB_EXPR` 解决多 stop 场景 `$N` 错配，未标记多 stop transcript fail-closed；
- resilient GDB probe：单个 `No symbol` 只降级对应字段，不中断后续 `i`/handler；重复运行
  通过 `RESULT_PREFIX` 形成独立 `run_id`；blocked runtime attempt 不污染已有有效 evidence；
- `pi-context`：仅提供 merged diagnosis bundle + debug plan 时可恢复显式 case/data/source/strategy/radar；
- runtime debug plan 已在 `CRGVI-1829/FCTA_R/radar2` 实际生成 16 个 breakpoint（其中 source-condition 8 个）、
  45 条 GDB command 和 66 个 capture fields；
- `pi_tool_bridge`：Pi Extension 的唯一 JSON 边界，统一分派 BaseTool/Module adapter；
- generator：从 catalog 生成 `registerTool`，真实透传 params，排除递归编排根；
- catalog：历史模块缺少 schema 时，从真实 run/argparse 契约推导参数，并复用 from_cli_args 构造映射；
- PiBridge：自动刷新并显式加载 extension，provider 未指定时只读发现当前 Pi model entry，Windows 进程树可清理；
- 测试：Pi bridge/context 单测 + 实际 `pi_rpc_smoke` + 实际 `pi-context` tool invocation。
- 入口：直接 `cli.py pi` 实测调用 `pi-context`，返回 `agent_settled`；无输出 timeout 为有界返回。

下一门不是继续增加静态规则，而是用户确认目标 source/tag/车型/CUDA 后，按
`US-002 → US-008 → US-010` 验证正式 arbe build/start/attach；再将 runtime trace
作为 overlay 合入 Sprint1 HTML。

## 12. 2026-08-30 实施优先级调整

架构复盘后，正式 build/start/attach 仍是必要现场验收，但不再作为唯一下一门。已有能力
如果没有 Analysis Ledger、EventCodePath 和协同 Workbench，继续增加 runtime 工具会提高
复杂度，却不一定提高用户价值。

### WP-10：Analysis Ledger MVP

关联：`US-015`。

- 定义 `analysis-run/step/claim/hypothesis/debug-experiment` schema；
- append-only 本地 ledger + checkpoint；
- 将现有 intake/precheck/code/runtime artifact 转换为 step/claim/gap；
- 用户 decision 和 resume；
- Snapshot HTML 增加 Analysis Trail。

当前进度：Ledger engine、5 个 Pi 原子模块、6 个契约文件、CRGVI-1829 artifact 恢复 smoke、
Pi tool-end → child AnalysisStep、`analysis-run-read` 交互短名单和详细报告 Analysis Trail
投影已完成；基础 `analysis_run_id`/Pi session resume 已有测试。用户 decision、Workbench
交互和 hypothesis/experiment 执行仍未完成。

验收：从 CRGVI-1829 已有 artifact 重建一个完整 run；不重解 bag、不重跑 GDB；每个最终
显示项可以回到原始 artifact。

### WP-10A：一次性 Code Context Snapshot

关联：`US-022`，为 `WP-11` 提供稳定输入。

- 复用现有 `CodeGraphBuilder`，对显式 source snapshot 做只读指纹；
- 输出 `code-context.v1` + 可供 `code-analyze`/`code-gdb-plan` 消费的 `code-index.v1`；
- 代码未变化时复用产物，变化时按 snapshot hash 重建，不混用其它 variant；
- 不在该确定性步骤调用 LLM；语义学习作为后续可选 enrichment，必须绑定同一 source hash。

验收：给定任意可读 C/C++ source root，能够一次生成函数、调用、变量、信号、条件、参数和
源码文件指纹；随后 Pi 查询不需要重新扫描全仓，source hash 变化会 fail-closed 或重建。

### WP-11：EventCodePath 与条件回填

关联：`US-016`。

- output→feature→situation→target→input 五层路径；
- 参数依赖和 current-frame evaluator；
- runtime-required gap；
- breakpoint/watch group；
- Debug-ready metric。

验收：现有 FCTA_R/FCTB_L 事件只作为测试 fixture；实现不能出现功能专属硬编码。

### WP-12：Public Runtime Collector / arbe adapter

关联：`US-009/US-017`。

- 迭代既有 `sim-verify` / `RemoteArbeReplayProvider`，不新增平行 remote replay tool；
- 通过 SSH 复用当前 ROS/arbe 会话做短窗口 LGU replay + public output capture；
- 采集 warning_status_with_frame/radar_info/objectlist；
- 明确 objectlist 无 frameID 的 association status；
- 将 capture JSON 交给既有 `public-runtime-normalize`，不在 replay provider 内复制归一化逻辑；
- 评审最小 stamped snapshot bridge；
- GDB 只针对 public gap。

验收：`sim-verify --mode remote_public` 能实际返回远程 capture artifact；
`public-runtime-normalize` 能检测带帧 warning 上升沿，并在默认 strict 模式把无 frame 的 objectlist 分离；
当前 source 证明同周期发布顺序且显式选择 `publication_order` 时，目标行可输出 `publication_correlated`、
message sequence 和 derived basis；若 recorder 顺序歧义则保留 unbound，不放宽为时间近邻匹配。
公共字段足够时不启动 GDB；只有 callback/stamped collector 或 GDB 精确读取才可满足 exact-frame。

补充：public runtime 已可经现有 runtime-evidence-normalize 投影为 canonical evidence；
runtime-evidence-merge 支持 event/frame/object scope，Pi 对大快照应只物化当前事件窗口，
完整 capture 作为独立 artifact 保留。

### WP-13：Hypothesis Board 与协同 Debug

关联：`US-017/US-018`。

- hypothesis state/history；
- minimum-cost experiment planner；
- headless + VSCode handoff + user observation；
- Workbench 三栏布局、独立滚动、渐进展开；
- 新证据更新 rank/status 和 next action。

### WP-14：Gen6 Capability Manifest

关联：`US-019`。

- [x] manifest builder（唯一入口 `project-capability-manifest`，不替代 `pi-context`）；
- parser/source/feature/replay/runtime/geometry/presentation SPI；
- capability pack router；
- 两项目隔离验收矩阵；
- source 变化 freshness fail closed。

### WP-15：效率和准确性基线

关联：`US-020`。

- Time to First Useful Clue / Debug-ready；
- data/source index 命中和 full-read count；
- evidence coverage / critical gaps；
- replay/GDB/user intervention；
- 与人工现行流程做真实问题单 baseline。

实施顺序：`WP-10 → WP-11 → WP-12 → WP-13 → WP-14`；正式 arbe write/runtime 验收在
WP-12 中按审批并行推进。根因/调参自动化在 ledger 和 hypothesis loop 可用后再扩大。

### 验证节奏约定

小切片只运行变更模块的定向单测和最小 smoke；跨模块契约或 Pi catalog 变化时运行相关
集成测试；全量回归只在 Sprint 收口、公共基础契约变化或发布前执行。跨进程/远程副作用、
源码身份和证据 provenance 保留必要门禁，其余不以穷举式防御替代真实验收。

## 13. 2026-09-01 三出口纵向实现切片

本切片对应 DDD `US-023`，以现有能力组装为目标，不新增固定功能规则。

### 13.1 批量预检查

入口仍为 `cr60-precheck`，由 Pi 在得到 intake/context 后调用 sibling harness。其输出是
批量 index 和每条数据独立的 `diagnosis_bundle`、`viewer-model`、HTML 以及缺口；Pi 只记录
artifact ref 和 step，不复制 harness 的解析/render 实现。

### 13.2 详细报告

新增的 `evidence-query` 负责有界 artifact 查询；新增的 `diagnosis-report` 负责确定性报告
投影。两者都通过 registry → generated registerTool → pi_tool_bridge 暴露。报告可以没有 AI，
也可以接收 `diagnosis-panel` 的结构化结果；AI 结果只进入 inference 区域。

### 13.5 报警条件和场景投影

对应 DDD `US-025`：增加 `condition-trace` 确定性原子能力，并由 `diagnosis-report` 复用。实现
顺序为：当前 event-code-path 条件/参数 → 选中事件同帧 field facts → 安全 C 表达式子集 → 条件
状态与 bindings → HTML 条件表和场景 SVG。任何缺失、跨帧或跨 radar 的操作数都只能产生
`not_evaluable`/`unsupported`；不得把 AI 解释或静态几何推导写成 runtime 真值。

### 13.3 对话恢复

`PiModule` 为有 case/context 的任务创建或恢复 `AnalysisRun`，将每轮对话作为可见 dialogue
step 写入 ledger，并使用 run ID 作为 Pi session ID。PiBridge 在有 session ID 时不再附加
`--no-session`，后续轮次可以使用同一 session/run context。对话事件只记录工具调用摘要和
artifact refs，不记录模型隐藏思维链。

### 13.4 本切片的非目标

- 不自动替用户确认 remote workspace 的 checkout/config/build/start/attach；
- 不把 `recorded_raw`、算法 proxy、CAN Tx 和 GDB 观察合并成一个首帧；
- 不将 `publication_correlated` 或 selected analysis frame 写成绝对同帧；
- 不把“正报/误报/根因已确认”作为没有充分证据时的默认输出；
- 不让新的报告模块绕过当前 source/data/runtime identity gate。

### 13.6 S1E 跨证据报警时间线与结论门

对应 DDD `US-026`。`alert-timeline` 是报告和 Pi 都可以调用的独立 projection，不复制
bag parser、arbe replay 或功能规则：

1. 从 bundle/viewer 事件形成 `recorded_raw` 行；
2. 从 `runtime-snapshot-with-frame.v1` / `runtime-case-evidence.v1` 形成 public/GDB/CAN
   运行态行；带显式 layer 的 replay trace 形成 `replay_algorithm` 行；
3. 以同一 `function/side/radar/frame` 作为比较 scope，输出 playback frame map 和
   `same/different/not_comparable/not_evaluated`；
4. 比较 data/source/binary identity，冲突时 timeline/report blocked；
5. `diagnosis-report` 投影 `conclusion.level`，默认无 runtime/CAN 时为 `facts_only`，不把
   报告生成成功写成正报/误报或根因确认；
6. runtime observation 若绑定到 selected exact frame，则回填同一 `condition-trace`；
   same-function window 或时间近邻仍然只显示为候选。
7. replay trace 的 `wN` 语义优先从当前 runtime/source schema 或显式调用方映射读取；没有映射时保留
   `wN`，不套用 CR60 legacy warning table。

本切片退出条件：当前 CRGVI-1829 单数据报告可以同时显示 5 个证据层状态、播放帧、原始
事件、条件 trace 和结论缺口；单元测试覆盖 layer、compare、identity conflict、runtime
condition binding；联合 replay/public/GDB/CAN 现场验收留到 runtime sprint。
