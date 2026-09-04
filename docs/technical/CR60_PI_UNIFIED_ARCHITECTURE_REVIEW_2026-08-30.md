# CR60 / Gen6 AI 诊断平台架构复盘与演进设计

版本：`architecture-review.v2`  
日期：2026-08-30  
状态：`proposed-baseline`  
关联：`US-001..US-014`，本轮新增建议 `US-015..US-022`

## 1. 结论先行

当前“Pi 作为唯一入口、原子工具负责确定性能力、arbe 作为正式算法回放宿主、
cr60-debug-harness 负责静态预检查和 HTML”的总体方向是正确的，值得继续演进；不建议
推倒重来，也不建议把 arbe、radarAnalyze 和 debug-harness 合并成一个大仓。

但当前设计还不能充分满足长期、持续的问题分析。主要缺陷不是工具数量不够，而是：

1. **分析过程没有成为一级产品对象**。现在主要产物是工具 JSON、最终 bundle 和 HTML；
   中间观察、冲突、假设、用户判断和下一步实验没有统一、可持续的状态模型。
2. **Pi 有编排能力，但缺少稳定的诊断方法骨架**。架构复盘开始时 Pi 可调用 42 个工具，
   S1A Ledger MVP 后为 47 个，加入 Code Context/EventCodePath/Public Runtime normalizer 后原始目录为 51 个；收敛历史重复入口并加入唯一 ProjectCapabilityManifest 后，Pi 正式目录为 49 个（45 modules + 4 tools）；但如果没有
   明确的阶段目标、停止条件、证据覆盖、假设状态和用户检查点；工具越多，调度成本和
   上下文噪声越大。
3. **静态、公共 runtime、仿真、GDB 和人工 VSCode debug 尚未形成一条连续工作台**。
   它们目前能通过 artifact 连接，但用户看到的仍容易是分散报告，而不是一步步推进的
   工程调查。
4. **准确性门禁已具备基础，但证据关联仍有关键缺口**。例如当前 arbe 的
   `/wf/objectlist_<radar>` 有丰富目标属性，却不携带算法 `frameID`；其 header stamp 是
   发布时 `ros::Time::now()`。若仅按时间邻近关联 `warning_status_with_frame`，不能宣称
   绝对同帧。
5. **多项目抽象有接口，但缺少“项目能力清单”作为运行时主键**。不同 Gen6 项目的数据、
   输出信号、source layout、feature、回放方式和 runtime 可观测字段都不同，不能依赖一套
   CR60 Light 路径/函数/消息假设。

本轮建议把产品主线从“最终诊断报告”调整为：

```text
一次可恢复的 AnalysisRun
  → 逐阶段产出可查看的 AnalysisStep
  → 每个结论是 Claim + Evidence + Assumption + Gap
  → 每个候选根因是 Hypothesis + RequiredEvidence + Experiment + Status
  → 用户和 Pi 共同选择下一步
  → 最终报告只是 AnalysisRun 的一个投影视图
```

产品价值不应只用“是否给出最终根因”衡量，还要用“多久给出第一条有效线索、减少多少
人工搜索、是否能直接进入下一次断点、是否保留了可复用调查过程”衡量。

## 2. 用户价值重新定义

### 2.1 用户真正需要的不是一次答案，而是调查推进

对算法工程师有价值的中间结果包括：

- 数据是否完整、回放链路是否可信；
- 一条数据中有哪些功能、多少次报警、哪一侧、哪个雷达；
- “报警第一帧”当前属于 raw、algorithm output、with-frame 还是 CAN Tx；
- 当前事件选中的目标、对象索引、身份是否稳定；
- 自车、目标、ROI、动态参数、抑制条件在事件前后如何变化；
- 代码调用链、输出链、参数依赖链和实际可见变量；
- 哪些条件已有数据证据，哪些只能通过 runtime/GDB 观察；
- 当前更像 data/replay/perception/tracking/situation/function/config/output 哪一层问题；
- 下一步最小成本实验是什么，做完后能排除什么；
- 用户在 VSCode 中应该打哪个真实断点、复制哪个条件、看哪些变量；
- 实验结果支持、削弱还是推翻了哪个候选原因。

因此，系统必须支持“边分析边呈现、边呈现边选择、边 debug 边回填”，不能把所有推理
隐藏在一次 AI 调用里，最后只给一个结论或代码修改方案。

### 2.2 显示的是工程推理摘要，不是隐藏思维链

平台应展示可审计的工程理由：

```text
Claim：radar2 的算法输出在 frameID=47875 首次变为非零
Evidence：warning_status_with_frame + runtime observation
Assumption：该 topic 是 algorithm proxy，不等同 CAN Tx
Conflict：raw warning 的时间对齐帧为 47877
Gap：当前 host 未观测到最终 RteLite_Write_<signal>
Next experiment：在当前 source 生成 CAN Tx probe
```

不需要、也不应存储模型不可验证的原始“思维过程”。AI 的每一步解释必须转化为上述
结构化、可引用、可被用户反驳的工程记录。

## 3. 当前架构评估

### 3.1 保留的正确设计

| 当前设计 | 评估 | 原因 |
|---|---|---|
| Pi 作为唯一产品入口 | 保留 | 用户不需要记住 CLI；适合根据问题动态组合能力 |
| Engine/BaseModule/Tool 原子能力 | 保留 | 易测试、易替换、能控制副作用 |
| cr60-debug-harness 独立 | 保留 | 静态解析和 HTML 不受 AI/主项目依赖变化影响 |
| arbe 作为正式回放/算法宿主 | 保留 | 已有 BagReader、算法编译宿主、ROS 输出和 GUI 观察能力 |
| runtime evidence additive overlay | 保留 | 不覆盖静态事实，允许比较多次回放/GDB |
| source/data/binary fingerprint | 保留并加强 | 是跨版本、跨项目准确性的硬门禁 |
| SGU 与 point-cloud 分策略 | 保留 | 两条链路的状态建立和可回答问题不同 |
| public evidence 优先、GDB 补缺 | 保留 | 效率和扰动优于“所有变量都用 GDB” |

### 3.2 必须补强的设计

| 缺口 | 当前风险 | 演进方向 |
|---|---|---|
| 没有 AnalysisRun/AnalysisStep | 中间结果散落，Pi 重启后难继续 | 持久化分析账本和 checkpoint |
| 没有统一 Claim/Hypothesis 模型 | AI 结论与证据状态容易混写 | 结构化 claim、gap、conflict、hypothesis |
| 49 个 Pi-visible 工具平铺（重复入口收敛后） | 工具选择噪声、token/规划成本增加 | capability pack + 动态短名单，底层仍原子化 |
| HTML 主要是最终快照 | 用户无法在同一界面推进调查 | live workbench + snapshot report 双形态 |
| public objectlist 无 frameID | 目标与 warning 不能直接宣称消息级同帧 | 严格模式保留缺口；经当前 source 证明的 publication-order capture 可做 derived 关联，最终 exact 仍用 stamped bridge/GDB |
| 代码检索与事件未形成统一视图 | 用户仍需手工在多个文件间跳转 | EventCodePath artifact + code panel |
| 根因分类无验证状态机 | 容易“一次 AI 判断根因” | hypothesis board + experiment loop |
| Gen6 项目差异只靠配置分散表达 | 易复用错误 parser/feature/参数 | ProjectCapabilityManifest + Adapter SPI |

## 4. 目标系统拓扑

```text
用户 / Pi 对话
      │
      ▼
Pi Coordinator
  - 理解业务问题
  - 选择当前阶段和 capability pack
  - 生成下一步计划/请求审批
      │
      ▼
Run Supervisor  ────────────── Analysis Ledger
  - session/checkpoint          - steps/claims/gaps/conflicts
  - approval/timeout/retry      - hypotheses/experiments/decisions
  - workspace/process lock      - user annotations/feedback
      │                                  │
      ├──────────────┬───────────────────┤
      ▼              ▼                   ▼
Static Evidence   Runtime/Replay      Code/Requirement
  bag/MF4/BLF       arbe/ROS/GDB        current source/index
  event/frame        public snapshot     call/condition/param graph
  media              optional bridge     requirement/variant knowledge
      │              │                   │
      └──────────────┴───────────────────┘
                     │
                     ▼
Evidence Store / Artifact Registry
                     │
             ┌───────┴────────┐
             ▼                ▼
Analysis Workbench       Snapshot HTML/Bundle
实时推进、协同 debug       可分享、可归档、可复现
```

关键原则：

- Pi 不持有长期真值，Analysis Ledger 和 artifact 是真值；
- Pi 不把一次自然语言推理覆盖确定性 evidence；
- 工具仍保持原子化，但 Pi 每个阶段只加载相关 capability pack；
- 用户可以在任意阶段暂停、回退、重跑或转入人工 VSCode debug；
- 最终报告由 ledger 投影生成，不重新推断事实。

## 5. 新的核心领域模型

### 5.1 `AnalysisRun`

一次用户问题对应一个可恢复的运行：

```text
run_id
user_goal / customer_claim / expected_behavior
project_id / variant_id / source_context_id
data_refs / case_refs / selected_event_refs
strategy / permission_policy
current_stage / status / created_at / updated_at
artifact_refs / step_refs / hypothesis_refs
```

`AnalysisRun` 不是一条 LLM conversation。对话可以断开，但 run 必须能从 artifact 和
checkpoint 继续。

### 5.2 `AnalysisStep`

每个阶段都产生独立结果：

```text
step_id / stage / tool_calls / start/end/status
input_artifact_refs / output_artifact_refs
observations / claims / gaps / conflicts
user_visible_summary / next_action_candidates
cost: wall_time / bag_reads / gdb_stops / model_calls
```

用户页面可以逐步查看：做了什么、发现了什么、为什么下一步建议做某个实验。

### 5.3 `Claim`

```text
claim_id
scope: data/frame/target/code/runtime/root-cause
statement
status: observed / derived / inferred / contradicted / not_available
evidence_refs[]
assumptions[]
conflicts[]
valid_for: data/source/binary/frame/object
```

### 5.4 `Hypothesis`

```text
hypothesis_id
category: data/replay/perception/tracking/situation/function/config/output/integration
statement
rank / confidence_band
supporting_claims[] / contradicting_claims[]
required_evidence[]
next_experiments[]
status: open / testing / supported / weakened / rejected / confirmed_by_user
```

置信度只表达当前证据覆盖，不替代最终工程确认。

### 5.5 `DebugExperiment`

```text
experiment_id
question_to_answer
method: static_query/public_runtime/replay/gdb/manual_vscode/parameter_what_if
expected_discrimination: 可排除哪些假设
plan_artifact / approval / session_artifact
observations / conclusion_delta / disturbance
```

## 6. 分阶段分析流程

### Stage 0：输入与身份绑定

用户看到：数据、车型、项目、代码版本、服务器、权限状态，以及哪些字段来自材料、哪些
需要确认。

产物：`cr60-analysis-intake.v1`、`pi-orchestration-context.v1`。

停止条件：身份冲突、数据/代码版本不明确、涉及副作用但没有授权。

### Stage 1：数据健康与事件地图

只读扫描所有数据，输出：

- topic/message/时间范围/缺失区间；
- 所有功能、侧别、报警区间和上升沿候选；
- raw、algorithm proxy、CAN Tx 的证据层级；
- 数据质量和回放可用性；
- 每个事件的第一批线索。

页面不是直接跳到“误报”，而是先给一个 Event Map。用户可以选择某个事件继续，也可以
让 Pi 按客户问题和证据覆盖排序。

### Stage 2：事件场景和目标身份

围绕选中事件构建连续帧窗口：

- ego state；
- 全部目标和选中目标；
- raw index、algorithm index、objID/objUnqID；
- warning/ROI/参数状态；
- 几何、媒体和身份稳定性；
- 目标出现、消失、ID 变化和属性突变。

输出第一轮分层判断：目标是否存在、跟踪是否稳定、当前功能前置数据是否可用。不能把
这些判断直接升级为最终根因。

### Stage 3：当前代码链路准备

按当前 source fingerprint 动态生成：

```text
输出位/CAN Tx
  ← warning handler
  ← feature state / situation
  ← target selection / ROI / TTC / suppression
  ← tracking/perception object
  ← input/replay mapping
```

产物 `event-code-path.v1` 至少包含：

- 函数、文件、行号、调用者/被调用者；
- 真实变量 token、读写位置和 scope；
- 参数来源、动态依赖公式和当前帧输入；
- 可由静态数据验证的条件；
- 只能 runtime 验证的条件；
- 推荐断点、条件和 watch group。

用户可以在代码面板按链路逐层展开，不需要阅读一次性长文本。

### Stage 4：静态条件回填与初步假设

把事件窗口的真实值回填到当前代码条件：

- 条件状态：`observed_true`、`observed_false`、`derived`、`not_logged`、
  `runtime_required`、`conflict`；
- 显示条件表达式、值、单位、来源帧和 source ref；
- 生成 Top-N 假设，但每个假设必须显示支持、反证、缺口和可区分实验。

这是用户第一次获得“更像哪一层问题”的结果，但仍是候选，不是最终答案。

### Stage 5：最小成本 runtime 证据

Pi 按成本排序：

1. 使用 bag 中已有 with-frame/public 信号；
2. 使用 arbe 已公开的 `/corner_radar/radar_info`、
   `/corner_radar/warning_status_with_frame`、`/wf/objectlist_<radar>`；
3. 复用 BagReader 做目标窗口闭环回放；
4. 使用可选 stamped runtime snapshot bridge；
5. 只有缺失局部变量/调用栈时才使用 GDB。

每一步结束都更新 hypothesis board，不应固定“先跑完整 GDB 再看结果”。

### Stage 6：协同 Debug

支持两条并行方式：

#### 自动 headless

Pi 展示计划和断点 → 用户批准 → supervisor 回放/attach → 自动采集 → 回填 ledger。

#### 用户 VSCode

工具给出可直接复制的：

- radar/namespace/process；
- source path + line；
- condition breakpoint；
- watch group；
- 目标前后帧和预期命中顺序；
- “观察到什么分别支持哪个假设”。

用户在 VSCode 看到的值可以通过页面表单、JSON paste 或后续轻量 VSCode bridge 回填。
回填后，Pi 重新计算证据覆盖和下一步，不要求用户重新解释整个上下文。

### Stage 7：根因收敛和修复/调参实验

只有当关键链路证据足够时，才给出：

- 根因层级和具体代码/参数位置；
- 为什么不是其他候选；
- 修复、参数调整或数据补采建议；
- 预期副作用和回归范围；
- 仿真复验计划。

代码方案是最终阶段的产物，不应遮蔽之前的调查过程。

## 7. 根因定位框架

根因分类只做导航，不是规则引擎的最终判定：

| 层级 | 典型问题 | 关键证据 |
|---|---|---|
| Data/Acquisition | topic 缺失、时间断层、信号无效 | bag inventory、validity、同步质量 |
| Replay/Parity | 预热不足、输入路径不同、状态未建立 | strategy、warmup comparison、output transition |
| Perception | 点/目标没有产生或属性错误 | point/cluster/object input，point-cloud runtime |
| Tracking | ID 跳变、速度/yaw/lifeCycle 不稳定 | 连续帧同目标、raw i→algorithm k、track state |
| Situation | 目标存在但 FOV/ROI/TTM/交点/场景不成立 | situation variables、dynamic ROI、ego state |
| Feature/FCT | situation 成立但 feature 状态机/计数/保持异常 | handler locals、counters、warning flags |
| Config/Parameter | 车型、CUDA、阈值、动态参数不匹配 | source/config fingerprint、parameter dependency |
| Output/CAN | algorithm warning 有、最终输出位没有 | handler→Rte mapping→RteLite_Write/ComSend |
| Integration/UI | 算法正确但显示/映射/雷达侧错误 | topic contract、radar mapping、viewer transform |

推荐的路由逻辑示例：

```text
目标输入不存在
  → 优先调查 data/perception/replay
目标存在但 ID/属性不稳定
  → 优先调查 tracking/input mapping
目标稳定但 situation 条件不成立
  → 优先调查 scene/ROI/dynamic parameter
situation 成立但 feature warning 未输出
  → 优先调查 feature/FCT state machine
algorithm warning 已输出但 CAN Tx 未输出
  → 优先调查 output mapping/config/integration
```

这只决定下一步证据采集，不自动宣布最终根因。

## 8. 静态分析设计

### 8.1 一次解析，多次切片

相同 `data_fingerprint` 只解析一次，形成 event/frame/signal/object 索引。选择不同功能、
目标或窗口时，从索引切片，不重复遍历 GB 级 bag。

建议缓存：

```text
data-index/<data-fingerprint>/
  bag_inventory.json
  frame_index.parquet 或 sqlite
  event_index.json
  object_tracks.parquet
  signal_series/
  media_index.json
```

缓存必须携带 parser/DBC/profile/source mapping 版本；身份不匹配时 fail closed。

### 8.2 事件优先而不是信号全量展开

默认先生成低成本 Event Map，再只对用户选择或 Pi 排序靠前的事件展开连续帧、目标和
代码条件。批量预检查保留全事件，但不为每个事件预先生成重型图表和完整代码链。

### 8.3 参数依赖图

每个功能的 ROI、阈值和抑制条件不能是固定 schema。当前 source 学习应生成：

```text
parameter token
  → definition/config location
  → formula/helper/call chain
  → runtime dependencies
  → current-frame evaluator capability
  → status observed/derived/runtime_required
```

简单表达式确定性求值；复杂 helper 生成 runtime probe，不让 AI 猜计算值。

## 9. 仿真与 arbe 复用设计

### 9.1 当前源码验证到的可复用方法

本轮在 `10.190.171.44` 的当前 arbe 源码重新确认：

1. `BagReader::buildLguPlaybackTimeline()` 将 radar0..4 的 LGU 消息按 bag time 稳定排序；
2. event mode 每次只发布一个 LGU event，scene mode 以主雷达为锚点匹配其他雷达；
3. warning/car/XCP/public CAN 使用 `findLatestAtOrBefore`，相机和副雷达使用
   `findClosestWithin`，并有 max-age/max-diff；
4. `playLoop()` 对每个 radar 保持最多一帧在途，等待
   `event_radar_pending_count_[radar]` 清零；慢算法不会导致逾期帧突发；
5. `/play_single_frame_<radar>` 的 `status=0/1` 是接收/完成 ACK，不是外部 seek API；
6. 当前 `visualization_node.cpp` 发布：
   - `/corner_radar/warning_status_with_frame`：radar id + frame_counter + 15 路 warning；
   - `/corner_radar/radar_info`：radar、ego speed、yaw rate、detections、frame、周期等；
   - `/wf/objectlist_<radar>`：目标位置、尺寸、yaw、速度、TTC/DDCI、各功能 object flag；
7. 当前 GUI 的 Object Table 已区分 `RAW_SGU` 与 `ALGO`，并逐目标显示上述属性；
8. 当前 objectlist 消息本身没有算法 frameID，且 header stamp 使用发布时 `ros::Time::now()`。

这些事实支持“优先复用 arbe 现有回放和公开字段”，也证明需要一个精确帧绑定补强。

### 9.2 推荐复用层次

#### 立即复用

- BagReader 时间线、辅助消息匹配和闭环 ACK；
- warning_status_with_frame、radar_info、objectlist；
- 现有 source/config/build/launch 语义；
- arbe_visualization_engine 作为算法宿主。

#### 薄适配

- `ArbeReplayAdapter`：load/select/jump/play/stop/status 的结构化控制面；
- `PublicRuntimeCollector`：按 radar/frame 聚合 warning/radar_info/objectlist；
- `ArbeProcessResolver`：namespace + radar + executable + binary fingerprint；
- `ReplayParityEvaluator`：输入、预热、输出转移和扰动比较。

#### 必要时增加 arbe feature bridge

建议新增默认关闭的 `runtime_snapshot_with_frame`：

```text
frame_id / bag_stamp / radar_id / radar_pos
raw_sgu_index → algorithm_index
ego / objects / warning / ROI
source/binary/config fingerprint
```

它解决 objectlist 无 frameID 的准确关联问题，也可以显著减少 GDB 次数。bridge 只导出
已有状态，不改变算法决策；局部变量、栈和临时状态仍由 GDB 或 feature-specific probe 获取。

### 9.3 不建议复用

- Qt widget 作为平台 API；
- RViz marker 作为几何真值；
- 固定 15 warning 位作为跨项目全局常量；
- objectlist 的 `ros::Time::now()` 作为算法帧时间；
- `PlaySingleFrame` ACK 作为播放器 seek/control service。

## 10. 代码查询与事件代码路径

代码能力应从“回答一个函数是什么”升级为“为一个事件准备可执行调查链”。

### 10.1 `event-code-path.v1`

```text
event/function/side/source fingerprint
output_chain
situation_chain
target_selection_chain
parameter_dependency_chain
input_mapping_chain
symbols and source refs
static condition evaluation
runtime-required variables
breakpoint groups
```

### 10.2 代码面板

用户点击事件后，代码面板默认显示五层：

1. 最终输出/CAN；
2. warning handler/state machine；
3. situation/ROI/TTC；
4. target selection/tracking；
5. input/replay/perception。

每层显示已观测变量、缺失变量和“查看源码/复制断点/加入下一次采集”操作，而不是一次性
堆叠完整调用图。

## 11. Analysis Workbench 设计

### 11.1 页面结构

```text
┌──────────────┬────────────────────────────────┬──────────────────────┐
│ 数据/事件/步骤 │ 场景、时间线、曲线、代码、媒体       │ 证据、属性、假设、下一步       │
│ 独立滚动       │ 固定主工作区，支持缩放/帧切换         │ 独立滚动、可折叠、可回填       │
└──────────────┴────────────────────────────────┴──────────────────────┘
```

左侧层级：项目 → 数据 → 功能 → 事件 → AnalysisStep。数据和报警事件不能处于同一层级。

中间主区按当前任务切换：

- Scene：ego/target/ROI/轨迹/坐标；
- Timeline：warning、ego、object、parameter、runtime stop；
- Code：事件代码路径和条件；
- Debug：断点、watch、栈、变量对比；
- Media：目标时刻或连续帧截图。

右侧不是长属性列表，而是可折叠、控件内滚动：

- Current frame facts；
- Ego/target/source/runtime；
- Claims and gaps；
- Hypothesis board；
- Next experiments；
- User notes/decision。

### 11.2 中间过程呈现

每完成一步，页面追加一张 step card：

```text
发现：radar2 的 FCTA_R 有 1 次上升沿候选
依据：warning_status_with_frame frame=...
仍未知：CAN Tx 是否同帧
影响：当前只能定位 algorithm output，不可称最终报警首帧
建议：先查当前代码输出链；如 host 可执行，再加 CAN Tx probe
```

用户可以：接受、质疑、标记无关、选择下一实验或进入 VSCode。Pi 将用户动作写入 ledger，
不在下一轮遗忘。

### 11.3 Snapshot HTML 与 Live Workbench

- Snapshot HTML：离线、可分享、可归档；展示某个 AnalysisRun 的冻结状态；
- Live Workbench：Pi/工具运行时更新 step、hypothesis、debug session；
- 两者消费同一 viewer model/ledger，不维护两套业务逻辑。

## 12. AI 与确定性工具边界

### AI/Pi 负责

- 理解用户业务问题和预期；
- 选择分析阶段、事件和 capability pack；
- 把数据值、代码、需求和 runtime evidence 组织成 claim；
- 生成多个候选假设和区分实验；
- 解释代码、差异、风险和下一步；
- 根据用户反馈重排计划。

### 确定性工具负责

- 文件、bag、DBC、ROS message 和 frame 解码；
- 事件、索引、目标、时间窗和几何计算；
- source/commit/config/binary/freshness；
- 参数表达式和明确公式求值；
- 回放、GDB、断点执行和变量采集；
- artifact、hash、schema、权限和审计。

### AI 不得

- 伪造缺失信号或 runtime 变量；
- 根据文件名猜车型/版本/雷达/目标；
- 把代码缓存当当前 source 真值；
- 把相邻时间对象冒充同帧目标；
- 在证据不足时把候选分类升级为最终根因；
- 绕过 approval 直接操作远程 shell/GDB/process。

## 13. Pi 工具编排优化

49 个 Pi-visible 工具已经证明插件化方向可行，但继续增长会降低工具选择效率。建议保留
原子 registry，同时增加 capability pack 和两级发现：

```text
用户问题
  → capability-search / current-stage policy
  → shortlist: 5–12 个工具
  → Pi 规划 typed calls
  → 原子工具执行
```

建议 pack：

- `intake-pack`：材料、数据、项目、freshness；
- `static-pack`：event/frame/object/signal/geometry；
- `code-pack`：source learn、call/condition/parameter/output chain；
- `runtime-pack`：preflight、replay/public evidence/bridge/GDB；
- `report-pack`：ledger projection、HTML、export；
- `maintenance-pack`：transfer/source/config/build/start/stop。

Pi 每个阶段只消费必要 schema 和 artifact 摘要，大 payload 始终通过 artifact ref 访问。

## 14. 效率设计与指标

### 14.1 工程效率策略

1. 数据和代码按 fingerprint 增量索引；
2. 先 Event Map，后事件切片；
3. 公共 runtime 优先，GDB 只补缺；
4. GDB watch 按 hypothesis 选择，不全量打印 locals；
5. 同一 replay session 支持多个相近 experiment，减少反复启动；
6. HTML 增量刷新，不因 UI 更新重解 bag；
7. Pi 使用 artifact 摘要和 capability shortlist 控制上下文；
8. 用户确认写入 ledger，后续不重复询问已确认事实。

### 14.2 需要测量的指标

| 指标 | 含义 |
|---|---|
| Time to First Useful Clue | 从输入到第一条可行动线索 |
| Time to Debug-ready | 到生成可复制断点/变量清单的时间 |
| Evidence Coverage | 关键条件已有证据的比例 |
| Unresolved Critical Gaps | 阻止根因判断的关键缺口数 |
| Bag Read Count | 同一数据被完整解析次数 |
| Replay/GDB Attempts | 回放和 GDB 次数及成功率 |
| User Intervention Count | 需要用户回答/操作的次数 |
| Hypothesis Reduction | 每次 experiment 排除/削弱的候选数 |
| Reproducibility | 相同 data/source/binary 是否得到相同 evidence |

不预设“节省 80%”等数字，先用真实问题单建立人工 baseline。

## 15. 准确性设计

### 15.1 四个独立准确性维度

1. Data accuracy：信号、帧、对象、单位和有效性；
2. Source accuracy：当前 branch/commit/config/parameter；
3. Replay accuracy：输入链、预热、状态、ACK、扰动和输出转移；
4. Reasoning accuracy：claim 是否被 evidence 支撑，假设是否区分事实和推断。

### 15.2 不允许合并的证据层

```text
recorded_raw
aligned_recorded
source_derived
replay_algorithm
runtime_with_frame
gdb_observation
can_tx_observation
user_observation
ai_inference
```

合并只生成引用和比较，不能覆盖前一层值。

### 15.3 发布门

最终“根因已确认”至少需要：

- 数据、source、binary 和事件身份无冲突；
- 根因链关键节点有 observed/runtime 或用户确认；
- 至少一个主要替代假设被证据削弱/排除；
- 修复/调参方案说明副作用和验证范围；
- 复验结果与原问题目标一致。

否则输出 `supported_hypothesis`、`partial` 或 `blocked`，不输出确定结论。

## 16. Gen6 多项目适配

### 16.1 `ProjectCapabilityManifest`

每个项目/车型/source fingerprint 在运行前生成：

```text
identity
  project/customer/vehicle/coem/source/binary
data_capabilities
  formats/topics/frame domains/media/dbc
feature_capabilities
  functions/output signals/sides/plugins
code_capabilities
  roots/build/source indexing/parameter providers
replay_capabilities
  sgu/point-cloud/player/ack/warmup
runtime_capabilities
  public topics/snapshot bridge/gdb/symbols
presentation_capabilities
  scene renderer/property groups/media panels
```

Pi 只能调用 manifest 声明且 freshness 匹配的能力。没有声明的功能显示 unsupported，不
回退到 CR60 Light 的 FCTA/FCTB 规则。

### 16.2 可插拔接口

- `DataParserPlugin`：bag/BLF/MF4/其他；
- `ProjectSourceAdapter`：仓库布局、COEM、构建和参数；
- `FeaturePlugin`：输出映射、代码入口、语义和 renderer hint；
- `ReplayStrategy`：SGU/point-cloud/项目专用；
- `RuntimeProvider`：public snapshot/bridge/GDB/CSV；
- `GeometryProvider`：坐标、安装位、ROI、polygon；
- `ReportPanelPlugin`：项目/功能专属可视化。

这些插件提供元数据和确定性能力，不各自实现一套 Pi 或完整页面。

### 16.3 接入新项目的验收

新项目不以“代码能 import”为接入完成，而要通过：

- 一个无报警数据：确认不产生假事件；
- 一个已知报警数据：确认功能/侧别/事件集合；
- 一个 runtime case：确认 frame/object/source/binary 绑定；
- 一个缺输入 case：确认 fail closed；
- 一个版本变化 case：确认旧 schema/knowledge 不被消费。

## 17. 推荐实施顺序

### Sprint A：Analysis Ledger 与阶段性结果

- `analysis-run.v1`、`analysis-step.v1`、`claim.v1`、`hypothesis.v1`、
  `debug-experiment.v1`；
- Pi 每次工具调用落 step 和 artifact ref；
- 现有 Sprint1/runtime 结果投影为 claim/gap；
- HTML 增加 Analysis Trail 和 Hypothesis Board。

### Sprint B：EventCodePath 与静态条件回填

- 事件到 output/situation/target/input 五层代码路径；
- 参数依赖图；
- 条件值和 runtime-required gap；
- 直接生成 VSCode debug handoff。

### Sprint C：arbe Public Runtime Collector

- [x] 复用现有 public topics，并通过既有 sim-verify remote_public 做 SSH 短窗口采集；
- [x] 记录 warning/radar_info/objectlist 的关联质量和 capture message sequence；
- [x] 默认 strict；当前 source 证明同周期发布顺序时支持 publication_correlated derived 关联；
- [ ] 接入 BagReader event/scene/ACK 的正式 collector；
- 评估最小 stamped snapshot bridge。

### Sprint D：协同 Debug Workbench

- live step、变量、断点、调用栈和用户回填；
- headless/VSCode 两条路径；
- experiment 结果更新 hypothesis。

### Sprint E：Gen6 ProjectCapabilityManifest

- 从 current source/config/data 自动生成 manifest；
- capability pack 动态短名单；
- 至少两个不同 Gen6 项目做隔离验收。

### Sprint F：根因收敛与调参闭环

- hypothesis ranking；
- parameter what-if 和 replay comparison；
- 修复建议、回归范围、复验和用户确认；
- freshness-bound reusable knowledge。

## 18. 当前成熟度判断

| 能力 | 当前成熟度 | 判断 |
|---|---|---|
| 输入/source/CUDA/preflight | 可用的工程基础 | 已有真实服务器和 fail-closed 证据 |
| Sprint1 静态批量 | 可用但需继续提高跨项目覆盖 | 已有多事件/多 bag/HTML |
| 逐帧场景/属性 | 部分可用 | 静态和 public 字段可用，精确 runtime frame 仍有缺口 |
| 代码查询/断点 | 工程可用 | 已有 current-source 断点和 GDB plan；事件代码路径需产品化 |
| SGU runtime/GDB | 部分可用 | isolated 证据已通过；formal attach 和 parity 未闭环 |
| point-cloud runtime | 设计阶段 | 需要 150–200 帧与 perception/tracking 连续证据 |
| Pi 原子工具 | 技术基础可用 | 47 工具已注册；Ledger MVP 已落地，仍需要 pack/阶段策略 |
| AI 根因定位 | 原型阶段 | 有 expert panel/证据输入，但缺 hypothesis/experiment 闭环 |
| 协同 Debug UI | 未形成完整产品 | 当前 HTML 是快照，不是 live workbench |
| Gen6 多项目 | 基础设施部分具备 | 需要 capability manifest 和跨项目验收矩阵 |

因此，当前平台是一个有价值的工程底座，但还不是“可以稳定替代工程师调查过程”的成熟
产品。下一轮不应优先继续增加散装工具，而应先实现 Analysis Ledger、EventCodePath 和
阶段性 Workbench，把已有能力组织成可用流程。

## 19. 待真实用户确认的产品问题

这些问题不会阻塞文档和只读开发，但会影响 Workbench 的默认交互：

1. 默认节奏是“每个阶段停下来让用户选择”，还是“自动跑到 Debug-ready，仅在关键冲突/
   副作用前停下”？当前建议后者，并允许用户切换精细模式。
2. 用户手工 VSCode debug 后，最可接受的回填方式是页面表单/粘贴 GDB 输出，还是希望
   后续增加轻量 VSCode bridge 自动回传？
3. 多个 Gen6 项目是否希望保持统一的三栏 Workbench，但允许每个功能提供专属 Scene/
   属性 panel？当前建议统一骨架 + 插件面板。
4. 团队协作是否需要同一个 AnalysisRun 被多人查看、批注和接力，还是第一阶段只服务
   单用户本地运行？
5. 对“根因确认”的最终签字者是算法工程师本人、问题单负责人，还是工具在复验通过后可
   自动标记？当前建议必须由人确认。
