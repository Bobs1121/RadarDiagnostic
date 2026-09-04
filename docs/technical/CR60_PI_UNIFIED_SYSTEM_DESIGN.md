# CR60 统一平台系统设计

版本：`system-design.v2.2`  
日期：`2026-09-01`  
前置：[调研报告](../CR60_PI_UNIFIED_RESEARCH_REPORT_2026-08-26.md)  
关联：[PRD](../CR60_PI_UNIFIED_PRD.md) · [模块设计](CR60_PI_UNIFIED_MODULE_DESIGN.md)

## 1. 系统定位

系统由四个运行域组成：

```text
Pi 交互/编排域
    radarAnalyze 的 pi、工具目录、任务状态机、人工确认

确定性证据域
    cr60-debug-harness 的 bag/BLF/source/geometry/report 能力

远程运行域
    Linux arbe、ROS、播放器/回放、算法进程、GDB

解释和知识域
    Pi/AI、历史案例、variant 隔离记忆、报告摘要
```

当前优先 system under test 是 `cr60_light_arbe`；其他 Gen6 项目通过
`ProjectCapabilityManifest` 和 adapter 接入。统一平台不能把任一被测仓库实现复制到核心。

## 2. 总体拓扑

```text
┌─────────────────────────────────────────────────────────────┐
│ L4 交互层                                                   │
│ 用户 ↔ radarAnalyze/pi                                      │
│ 意图理解、计划、工具选择、人工确认、解释                    │
└──────────────────────────┬──────────────────────────────────┘
                           │ structured tool calls
┌──────────────────────────▼──────────────────────────────────┐
│ L3 编排层                                                   │
│ AnalysisRun / RunSupervisor / AnalysisLedger / Recovery     │
│ MODULE_REGISTRY + TOOL_REGISTRY + CapabilityRegistry        │
└────────────┬─────────────────┬──────────────────┬───────────┘
             │                 │                  │
┌────────────▼───────┐ ┌───────▼────────┐ ┌───────▼──────────┐
│ 静态证据 Provider  │ │ 运行控制       │ │ 解释/交付         │
│ Sprint1 harness    │ │ arbe/ROS/GDB   │ │ merge/report/AI  │
│ source/code/geom   │ │ replay/debug   │ │ memory           │
└────────────┬───────┘ └───────┬────────┘ └───────┬──────────┘
             │                 │                  │
┌────────────▼─────────────────▼──────────────────▼───────────┐
│ L1 统一契约层                                               │
│ intake / analysis-context / diagnosis-bundle / runtime-trace │
│ provenance / evidence status / artifact references           │
└──────────────────────────┬──────────────────────────────────┘
                           │ SSH / process / files / ROS
┌──────────────────────────▼──────────────────────────────────┐
│ L0 外部资源                                                 │
│ Excel/UNC/SMB · bag/BLF · source repo · Linux arbe · GDB     │
└─────────────────────────────────────────────────────────────┘
```

## 3. 四个平面

### 3.1 控制面

控制面负责：

- 解析用户意图；
- 规划工具调用顺序；
- 校验输入和权限；
- 创建 `run_id/session_id`；
- 启动、暂停、继续、停止和恢复任务；
- 管理远程命令和进程生命周期；
- 记录每一步状态、命令、时间和结果。

控制面不直接解码 raw object，也不直接计算报警结论。

### 3.2 数据/证据面

证据面负责：

- bag topic/type/msgdef；
- warning 样本和帧；
- LGU/SGU/objectlist；
- 当前 source functions/conditions/parameters；
- geometry contract；
- GDB args/locals/backtrace/trace；
- camera/media provenance。

证据面不能被 Pi 的自然语言回答覆盖。

### 3.3 解释面

解释面可以使用 Pi/AI：

- 解释调用链；
- 排序 perception/situation/FCT 假设；
- 比较多个数据；
- 给出下一步验证建议；
- 生成面向用户的总结。

解释面不能创建不存在的证据，不能把 `unknown` 当作 `pass`。

### 3.4 分析状态与协同面

该平面持久化用户真正关心的调查过程：

- `AnalysisRun` 和阶段 checkpoint；
- `AnalysisStep` 的工具调用、发现、耗时和下一步；
- `Claim` 的 evidence/assumption/conflict/gap；
- `Hypothesis` 的支持、反证、required evidence 和状态变化；
- `DebugExperiment` 的计划、结果、扰动和结论变化；
- 用户接受、质疑、标记无关和人工 debug 回填。

Pi 对话可以中断或更换模型，但该平面不能丢失。HTML、Workbench 和最终总结均消费这里
的结构化状态，不在展示层重新推断。

## 4. 统一生命周期

```text
CREATED
  → INTAKE_VALIDATED
  → SOURCE_CONTEXT_READY
  → SPRINT1_READY
  → MODE_SELECTED
  → ARBE_PREFLIGHTED
  → ARBE_READY
  → DEBUG_PLAN_READY
  → APPROVAL_PENDING
  → SESSION_RUNNING
  → RUNTIME_CAPTURED
  → EVIDENCE_MERGED
  → REPORT_READY
  → COMPLETED
```

可恢复状态：

```text
INTAKE_VALIDATED
SOURCE_CONTEXT_READY
SPRINT1_READY
MODE_SELECTED
ARBE_PREFLIGHTED
DEBUG_PLAN_READY
RUNTIME_CAPTURED
EVIDENCE_MERGED
```

不可自动跳过的门：

- 数据身份缺失；
- source/binary 不匹配；
- 车型或 tag 未确认；
- workspace dirty 且可能被覆盖；
- GDB symbols 不可用；
- HILMODEL=2 未通过当前 source/build/binary 校验；
- runtime attach 权限未确认；
- replay mode 不明确。

## 5. 两种回放系统设计

### 5.1 SGU Injection Strategy

```text
Sprint1 event/frame/index
    → 检查 HILMODEL=2
    → 检查 SGU input topic/outputData layout
    → 检查目标 radar_id/radar_pos
    → 生成运行时断点和 watch set
    → 目标注入/回放
    → GDB 采集 objTrans/trcOutData/ADAS/ROI
    → runtime trace
```

默认：

```text
sgu_frame_warmup = 3~5 frameID
point_cloud_warmup_frames = not_applicable
```

SGU 模式按用户确认的实际算法 frameID 在目标事件前预热 3–5 帧；如果要分析 hold/keep/counter，仍可扩大独立的 feature state window，但不重新施加 150–200 帧点云预热。3–5 只是当前默认 profile，若代码版本或功能要求不同，必须由运行时验证覆盖。

### 5.2 Point Cloud Replay Strategy

```text
Sprint1 event/frame
    → 检查点云 topic 和算法输入
    → 设置 point_cloud_warmup_frames=150~200
    → 连续回放同一 radar
    → 检查 gaps/reset/ACK
    → 采集 dot/filter/cluster/track/trcOutData
    → 采集 ADAS/ROI/runtime geometry
    → runtime trace
```

两种 strategy 必须在报告中明确写出：

- 使用了哪条链路；
- 哪些链路被绕过；
- warm-up 的含义和实际帧数；
- 是否存在 reset/gap；
- 是否使用正式 GUI player 或 direct rosbag play。

## 6. HILMODEL=2 系统设计

`HILMODEL` 是编译期宏，不是普通运行时开关。系统必须按照以下顺序处理：

```text
读取当前 paraDefine.h
    → 读取构建参数/编译日志
    → 识别最终二进制中的 source/build identity
    → 确认 HILMODEL=2
    → 才允许 SGU runtime strategy
```

当前 source snapshot 中已看到 `HILMODEL=2`，但这个事实只能适用于该 snapshot。每个新 branch/tag 必须重新验证。

用户已确认当前 SGU 目标注入流程使用 `HILMODEL=2`；这属于运行策略确认，不等于当前 binary 已证明采用该宏。每次运行仍需用 active `paraDefine.h`、编译参数/日志和 binary/runtime preflight 三者校验。

如果需要修改：

```text
生成 patch plan
    → 展示 diff
    → 用户确认
    → 应用最小变更
    → catkin_make
    → 记录 before/after hash
```

不能由 Pi 直接在后台改 `paraDefine.h` 后假装运行环境已经切换。

## 7. 远程执行边界

### 7.1 推荐模式

用户确认自动化目标为全流程自动；在一次性审批通过后，优先复用用户实际使用的标准 arbe 启动链：

```text
数据传输/切版本/配置/编译
    → bash start
    → 等待 arbe_gui 和 radar1/2/3/4 visualization_engine ready
    → 导入目标数据
    → headless GDB attach 到真实目标进程并设置断点
    → 回放 3–5 个 SGU 前置 frameID 或 point-cloud warm-up
    → GDB trace/capture
    → session teardown
```

如果标准进程 attach 受 ptrace、权限、时序或符号限制，再由用户确认切换为隔离 ROS master + launch-under-GDB。正式 GUI 当前的 `PlaySingleFrame.srv` 是算法处理 ACK，不是完整 playback API；headless GDB 仍是首选 runtime 采集方式。

### 7.2 两类 GDB

| 模式 | 用途 | 优先级 |
|---|---|---:|
| existing PID attach | 连接 `bash start` 后已就绪的真实进程 | 1 |
| launch-under-GDB | 用户确认后隔离启动目标进程并控制整个生命周期 | 2 |
| VS Code handoff | 自动化受限时交给用户 | 3 |

所有 GDB 模式都记录：

- PID/node/executable；
- binary hash；
- symbol 状态；
- source context；
- breakpoint set；
- stop 次数和超时；
- detach/teardown 结果。

### 7.3 原始 arbe workspace 的版本/接口变化保护

用户允许工具操作原始 arbe workspace，但该仓由其他人维护，后续版本可能改变内部接口。当前用户流程假设一次运行从编译前到 runtime 期间代码不变；控制器在每次运行的数据传输、切子仓、修改配置、编译、启动和 runtime 前后都保存 outer/algo HEAD、dirty 状态、关键配置 hash 和 binary inventory。

每次新运行发现 source/config/binary fingerprint 与上一 run 不同，不复用旧的接口适配、字段偏移和断点；先重新 source learn、重新编译/确认 binary，再生成 runtime plan。如果运行中意外发现 fingerprint 变化，标记 `source_changed`/`conflict` 并停止生成正式 runtime 结论，但不把并发更新设计成常规流程。

## 8. 证据合并

合并器必须保留多来源，而不是覆盖字段：

```text
field: fTTC
  bag_input: 1.02
  objectlist_candidate: 1.00
  runtime_output: 0.98
  source_ref: perception_public_api.h:99
  runtime_ref: adasFunc.c / FrontCrossTrafficAlertAndBrake
```

如果来源冲突，输出：

```text
conflict=true
resolution=not_auto_resolved
```

目标关联必须满足：

```text
same data
same radar
same frame
same coordinate contract
same target identity
```

否则只能作为 candidate，不能成为 runtime target truth。

## 9. 几何系统设计

### 9.1 坐标契约

几何模型至少包含：

```text
coordinate_frame = algorithm_ego_axis
x_positive = forward
y_positive = left
origin = source-defined ego reference
unit = m
radar_id
radar_pos
radar_x_offset
radar_y_offset
radar_yaw_angle
orientation
```

当前源码注释表明车辆安装参数以“后轴中心”为纵向参考，并有 `bumper2RearAxle_dist`。自车矩形不能从 `x=0` 盲画。

### 9.2 几何来源优先级

```text
runtime objPoly / runtime adasRoi
    > runtime parameters + source formula
    > source formula + static profile
    > generic fallback
```

generic fallback 只能显示为 unavailable/illustrative，不能用于报警碰撞判定。

### 9.3 geometry evidence

```text
ego_geometry
target_geometry
roi_geometry
transform_chain
collision_inputs
collision_result
evidence_level
```

`collision_result` 只能是：

```text
evaluated_true
evaluated_false
not_evaluated
frame_mismatch
coordinate_mismatch
runtime_geometry_missing
```

### 9.4 几何与状态转换的通用不变量

当前一个真实源版本的 runtime 验证表明，功能侧别 flag 可能只是“对应 ROI 已启用”，
而目标是否会进入风险区域还要由目标多边形、运动方向、预测交点和 TTM/DDCI 共同判断。
因此系统不能把任何单一字段（例如 `ROI.num`、目标中心点或对象 warning flag）直接解释
为碰撞成立。几何 provider 必须返回：

```text
instantaneous_containment
predicted_intersection
prediction_inputs
prediction_formula/source_ref
```

同理，算法对象常在处理过程中经历“输入快照→局部计算→数组回写→功能输出”的状态转换。
runtime collector 必须支持同一 `frameID + algorithm index + object identity` 的多阶段
样本，保存字段的 `before/after`、函数作用域和 source line，不能只保留最后一个值。
这些是跨功能、跨版本的证据不变量；具体函数、字段、侧别、数组布局仍必须从当前
source/runtime schema 生成。

### 9.5 回放策略不是事实等价声明

`sgu_injection` 的 3–5 帧和 `point_cloud` 的 150–200 帧是输入策略，不是所有 runtime
派生状态的等价证明。每个 runtime session 记录：

```text
strategy / strategy_source
requested_frames / actual_frames
reset_or_gap
derived_state_fingerprint
output_transition_fingerprint
warmup_sensitivity
```

当输出一致但派生状态发生漂移时，session 可以继续作为“输出可复现、状态敏感”的证据，
但不能升级为完整 replay parity。这样既不把点云预热套到 SGU，也不隐藏短预热带来的
参数/状态差异。

## 10. 多服务器、多项目和会话隔离

一次 `OrchestrationRun` 绑定：

```text
user/owner
project_id
variant_id
profile_id
server_id
arbe_workspace
outer_arbe_commit
algo_source_commit
coem
vehicle
data_fingerprint
source_fingerprint
binary_fingerprint
output_root
```

不同项目必须隔离：

- source snapshot；
- codegraph；
- source_docs；
- memory；
- Pi session；
- runtime trace；
- HTML 输出。

## 11. 系统失败策略

单个数据失败不拖垮批次：

```text
ready case     → 继续生成报告
blocked case   → 保留 blocker 和输入缺口
unsupported    → 保留格式/解析原因
runtime failed → 保留 Sprint1 静态结果和 runtime failure
```

Pi 可以重新规划，但不能绕过硬门禁。每个失败都必须有机器可读状态和下一步建议。

## 12. AnalysisRun 与阶段状态机

生命周期不再只有环境/产物状态，还要记录调查阶段：

```text
INTAKE
  → EVENT_MAP
  → SCENE_AND_TARGET
  → EVENT_CODE_PATH
  → STATIC_CONDITION_FILL
  → HYPOTHESIS_FORMED
  → PUBLIC_RUNTIME
  → DEBUG_EXPERIMENT
  → HYPOTHESIS_UPDATED
  → FIX_OR_TUNING_PLAN
  → REPLAY_VERIFIED
  → USER_CONFIRMED
```

每个阶段都可以 `ready/partial/blocked/failed/skipped`，并单独保存输入、输出、claim、gap、
conflict、metrics 和 next action。runtime 失败不删除静态步骤；用户人工 debug 可以作为新的
experiment 插入，而不是另起一次无上下文分析。

## 13. Pi capability pack 和动态短名单

底层 registry 保持原子化。控制面根据 `current_stage + ProjectCapabilityManifest + policy +
freshness` 生成工具短名单：

```text
INTAKE            → intake-pack / maintenance-readonly
EVENT_MAP         → static-pack
EVENT_CODE_PATH   → code-pack
PUBLIC_RUNTIME    → runtime-public-pack
DEBUG_EXPERIMENT  → runtime-gdb-pack / manual-debug-pack
DELIVER           → report-pack
```

Pi 不需要在每个 turn 同时比较全部 54 个工具；大数据通过 artifact ref 访问。短名单只影响
规划，不改变原子工具的独立测试和直接调用能力。

## 14. arbe 公共 runtime 与 stamped snapshot

当前源码证明以下公共字段可以低成本复用：

| 通道 | 可获得信息 | 当前限制 |
|---|---|---|
| `warning_status_with_frame` | radar、frame_counter、功能 warning | algorithm proxy，不一定是 CAN Tx |
| `radar_info` | ego speed/yaw、detections、frame、周期、BLD | positional array，需要当前源码 schema |
| `objectlist_<radar>` | 目标位置/尺寸/yaw/速度/TTC/DDCI/object flags | 无 algorithm frameID；stamp 是 publish-now |
| BagReader ACK | 每雷达接收/完成、闭环时序 | 不是外部 seek/load API |

PublicRuntimeCollector 可以先消费这些通道，但 objectlist 与 warning 的绑定必须区分
frame_verified/callback_correlated/publication_correlated/unbound；其中 publication_correlated
是经当前 source 证明且录制顺序无歧义时的 derived 关联，不是消息级真值。如果结论依赖绝对同帧，
增加默认关闭的 runtime_snapshot_with_frame：在同一算法 callback 内发布 frame/radar/ego/object/
warning/ROI/fingerprint。该 bridge 是精确关联和降低 GDB 成本的补强，不改变算法决策。

### 14.1 AlertTimeline 与报告结论读模型

`AlertTimeline` 位于证据面和报告面之间，不属于算法功能上下文：

```text
recorded bundle ─┐
replay trace ────┼─> alert-timeline.v1 ─> diagnosis-report / Workbench / Pi
public snapshot ┤       │
GDB/CAN rows ────┘       ├─ playback_frame_map
                         ├─ layer comparisons
                         └─ identity conflicts
```

它只比较同一 `function/side/radar/frame` 的已有行。缺层显示 `not_available`，没有 observed
exact frame 的比较显示 `not_evaluated/not_comparable`，data/source/binary 冲突为 blocked。
详细报告再从同一读模型生成 `conclusion.level`：无 runtime/CAN 时为 `facts_only`，不能因
HTML 生成成功而升级为 `confirmed`。这样 Pi 的解释、离线 HTML 和未来 Live Workbench 不会
各自发明一套报警首帧或 raw/仿真映射。

## 15. Gen6 ProjectCapabilityManifest

一次 run 在工具规划前生成当前项目能力清单：

```text
identity: project/customer/vehicle/coem/source/binary
data: parsers/topics/frame domains/media/DBC
features: names/sides/output mapping/plugins
code: roots/index/parameter/output-chain providers
replay: strategies/player/ACK/warmup
runtime: public topics/bridge/GDB/debug symbols
presentation: scene/property/media panels
```

manifest 是多项目适配门禁：未声明的功能、消息或 runtime provider 不进入 Pi 短名单；
source fingerprint 变化时重新生成。这样可以共享 AnalysisRun/Workbench/ledger，而不共享
错误的 CR60 Light 业务假设。

## 16. 效率和准确性控制

### 效率

- data fingerprint 下只做一次完整解析，事件/目标/信号按需切片；
- source fingerprint 下只做一次 code index 和参数依赖图；
- 先 Event Map 和公共 runtime，再选择重型几何/GDB；
- 同一 replay session 合并相近 experiment；
- report refresh 不重解 bag；
- step 记录 wall time、bag reads、model calls、replay/GDB stops。

### 准确性

- data/source/binary/replay/reasoning 四个维度独立评估；
- `recorded_raw/aligned/source_derived/replay/runtime/gdb/can_tx/user/ai` 不互相覆盖；
- object/frame/side/radar 关联必须有明确 gate；
- 最终根因需要关键链路证据、替代假设处理和人工确认；
- UI 视觉重叠、时间接近或 AI 高置信度都不能替代证据门。

## 17. 三个用户出口的运行拓扑

```text
用户给数据目录 ──> Pi ──> intake/context ──> cr60-precheck ──> batch index + per-data HTML
                                      │
                                      └─> AnalysisRun / AnalysisStep

用户选事件 ──────> Pi ──> evidence-query ──> code-context/event-code-path
                                      ├─> public runtime / GDB（按缺口和审批）
                                      ├─> diagnosis-panel（可选 inference）
                                      └─> diagnosis-report ──> JSON/MD/HTML companion

用户继续追问 ────> 同一 Pi session/run ──> 查询/代码/信号/runtime 原子能力 ──> 新 step/claim
```

批量、详细和对话共用 artifact identity 与 ledger；它们不各自维护事件解析、代码索引或根因规则。
Pi 负责意图和顺序，确定性工具负责事实，报告负责投影，AI 负责解释。
