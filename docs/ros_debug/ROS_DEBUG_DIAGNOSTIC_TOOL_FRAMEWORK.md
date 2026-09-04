# CR60 Light 实际 ROS / rosbag 数据诊断工具：框架基线

> 状态：探索阶段的框架基线，不是最终实现设计。
> 更新时间：2026-08-24
> 适用范围：CR60 Light 多车型、多客户、多版本的实际 ROS 回灌、可视化、C++ attach、数据证据与算法诊断。
> 关联记录：[EXPLORATION_NOTES_2026-08-24.md](EXPLORATION_NOTES_2026-08-24.md)

这份文档描述工具应该稳定具备的能力和数据契约，不把能力绑定到 `CRGVI-1829`、FCTA/FCTB 或某一个分支。具体问题单只是输入案例，不能成为架构假设。

## 1. 产品定位

工具是“实际 ROS/rosbag 数据诊断 Harness”，不是：

- 只统计 warning bit 的脚本；
- 只打开 RViz 的启动器；
- 只给源码搜索结果的代码问答工具；
- 只在某一个 bag 上硬编码时间、雷达和对象 ID 的分析脚本；
- 自动修改算法参数并直接提交代码的黑盒优化器。

工具的目标是把一次真实问题转换成可复现、可追踪、可逐层验证的诊断会话：

```text
问题描述 / TR / bag / 车型 / 版本
        ↓
案例身份与资产快照
        ↓
bag 静态抽取 + 数据质量 + 报警候选事件
        ↓
雷达 / 帧 / 目标选择 + 预热窗口规划
        ↓
ROS arbe session 构建 + 连续回灌 + 可视化 / replay
        ↓
C++ debug target / PID / GDB 采样
        ↓
代码调用链 + 条件变量 + 参数边界 + 输出对齐
        ↓
证据包、冲突、缺口、根因假设、敏感度和下一步验证
```

最终结论必须区分：

1. **录制事实**：bag 原始 topic 中实际存在什么；
2. **回放事实**：当前代码/配置/编译产物重跑后输出什么；
3. **代码条件证据**：某一帧的输入是否满足某一条件；
4. **调试观察**：GDB/日志/ROS runtime 观察到什么；
5. **诊断推理**：基于上述证据的根因排序；
6. **确认结论**：只有通过需求/真值/受控重跑/对照实验后才可以提升置信度。

## 2. 运行模式

工具应从低风险、低成本模式逐步升级，不要求每个案例都启动完整 GUI。

| 模式 | 作用 | 是否修改远程环境 | 典型产物 |
|---|---|---:|---|
| `static` | 只读 bag、源码、配置、版本和现有产物 | 否 | metadata、topic/schema、报警候选、数据质量 |
| `guided` | 工具准备命令和目标，用户确认后执行回放/attach | 最小 | session manifest、帧定位、GDB 参数 |
| `controlled-replay` | 在隔离 session 中自动编译/启动/预热/回放/收集 | 仅隔离目录/进程 | replay trace、输出 topic、帧证据 |
| `interactive-debug` | 用户在 VS Code 中 attach，工具同步提供目标和变量采集方案 | 可能暂停进程 | debug transcript、变量快照 |
| `tuning-analysis` | 参数扫描/标定读取/what-if/对照重跑 | 必须显式授权 | 敏感度曲线、对照报告 |

默认从 `static` 开始。工作区复用、切 branch、编译、启动、停止进程、修改源码、修改 A2L/XCP 参数都必须是显式能力和显式授权，不从普通对话意图中推断。

## 3. 系统拓扑与职责边界

```text
┌────────────────────── 用户 / pi / CLI ──────────────────────┐
│ 问题理解、能力编排、确认点、结论解释                         │
└───────────────┬────────────────────────────────────────────┘
                │ CaseSpec / RunPlan / EvidenceBundle
┌───────────────▼─────────────────────┐
│ 1. Intake & Identity                 │ TR、车型、版本、bag、需求、真值
│ 2. Snapshot & Preflight              │ git/diff/config/ROS/build/display
└───────────────┬─────────────────────┘
                │ immutable snapshot
┌───────────────▼─────────────────────┐
│ 3. Static Data Plane                 │ rosbag、msgdef、DBC、A2L、signals
│ 4. Event/Frame/Target Planner         │ 报警段、雷达、帧、预热、目标
│ 5. Code/Condition/Parameter Plane     │ CodeGraph、调用链、条件、标定
└───────────────┬─────────────────────┘
                │ ReplayPlan / DebugPlan
┌───────────────▼─────────────────────┐
│ 6. ROS Session & Replay Adapter       │ SSH、catkin、start、GUI player、ack
│ 7. Debug Adapter                     │ ROS node → PID → ELF → GDB probes
└───────────────┬─────────────────────┘
                │ runtime evidence
┌───────────────▼─────────────────────┐
│ 8. Evidence Store & Diagnosis        │ 时序对齐、冲突、缺口、报告、记忆
└──────────────────────────────────────┘
```

### 职责边界

- **Intake** 只确认案例身份和用户意图，不决定算法结论。
- **Static Data Plane** 只解析和标注数据，不把数据值直接判为正报/误报。
- **Replay Adapter** 只负责可靠地让目标版本接收到数据，并报告实际回灌状态，不解释算法。
- **Debug Adapter** 只负责 target、PID、断点、变量和日志证据，不替用户改代码。
- **Condition Engine** 只判断“条件在当前证据下满足/不满足/未知”，未知不能伪装成失败。
- **AI/Diagnosis** 负责跨代码、数据、需求、真值和案例知识排序根因，并明确不确定性。
- **Tuning** 负责可复现的参数 what-if 和敏感度，不等于自动批准优化方案。

## 4. 统一数据契约

每个对象都要带 `provenance`、`validity` 和 `identity`，否则不同 topic、不同版本和不同回放结果会被错误合并。

### 4.1 `CaseSpec`

```json
{
  "case_id": "CRGVI-1829",
  "vehicle_project": "BYD_UKE",
  "vehicle_variant": "QZH",
  "branch_or_tag": "...",
  "bag_paths": ["..."],
  "requested_functions": ["FCTA", "FCTB"],
  "symptom": "客户认为误报警",
  "ground_truth": {"kind": "unknown", "source": null},
  "user_constraints": {}
}
```

### 4.2 `EnvironmentSnapshot`

必须记录：

- SSH host/user、OS、kernel、ROS distro、ROS master、DISPLAY；
- 外仓 branch/HEAD/dirty diff；
- 每个 submodule 的 HEAD、branch/detached 状态、dirty diff；
- 配置文件 hash、CUDA xlsx 名称/sheet、DBC/requirements/A2L hash；
- `CMAKE_BUILD_TYPE`、编译命令、binary absolute path、`file`/BuildID/debug symbol 状态；
- ROS nodes/topics/services/params、启动命令、session PID、日志路径；
- 环境快照生成时间和命令输出。

任何 replay/debug 报告没有完整 snapshot，都只能是非复现性观察。

### 4.3 `SignalObservation`

```json
{
  "topic": "/front/signals",
  "message_type": "common_can_signal_publisher/PublicCanFrontSignals",
  "md5": "...",
  "bag_time": 1784433894.8,
  "header_time": 1784433894.8,
  "radar_id": null,
  "field": "m_2ca_..._fctbbrkreq_s",
  "value": 1,
  "unit": "request",
  "signal_valid": 1,
  "source_kind": "recorded_can_message",
  "provenance": {"bag": "...", "connection_id": "...", "msgdef_hash": "..."},
  "quality": "valid"
}
```

必须支持：

- ROS header time、bag connection time、算法 frameID 三种时间；
- `signal_valid`、默认值/NaN、恒定值、物理范围、消息定义版本；
- 同名字段的不同 package/type/md5，不得仅按字符串字段名合并；
- 原始字节保留或可定位，便于发现当前生成类与 bag 内嵌 msgdef 不一致。

### 4.4 `AlarmEvent`

报警事件不是一帧 bit，而是一段带边沿和状态的事件：

```json
{
  "event_id": "...",
  "function": "FCTB_R",
  "source": "recorded_raw|replay_algo|public_can|user_report",
  "radar_ids": [2],
  "start_time": 0.0,
  "end_time": 0.0,
  "first_on_frame": 0,
  "threshold_crossing_frame": 0,
  "last_on_frame": 0,
  "edge_kind": "rising|level|release|unknown",
  "confidence": "observed|correlated|inferred",
  "evidence_refs": []
}
```

事件分段要保留：连续 active frames、短暂中断、同一事件的多来源输出、相邻 radar 的时间偏差。

### 4.5 `FrameCandidate` 与 `TargetCandidate`

`FrameCandidate` 至少包含：`radar_id`、topic、`frame_id`、bag/header time、event role（预警/首次计数/达到阈值/最终输出/释放）、上下文窗口和是否存在 gap。

`TargetCandidate` 至少包含：`objID/objUnqID`、`obj_class/type`、`dynFlg`、位置、速度、尺寸、yaw、TTC/TTM、DDCI、lifeCycle/historyMovDist、各功能 object flags、来源和淘汰原因。

### 4.6 `EvidenceBundle`

证据包必须能独立复现，不依赖当前用户工作区的隐式状态：

```text
manifest.json
environment_snapshot.json
case_spec.json
bag_catalog.json
message_definitions/
raw_event_timeline.csv
replay_event_timeline.csv
frame_evidence.jsonl
target_candidates.jsonl
condition_evidence.jsonl
debug_transcript/
source_snapshot/
plots/
diagnosis.md
reproduction_commands.sh
```

## 5. 数据抽取框架

### 5.1 Stage A：bag inventory

先做低成本清单，不启动 ROS：

1. 文件存在性、大小、mtime、rosbag version、duration、start/end、message count；
2. topic/type/md5/count/frequency；
3. topic 内嵌 `msg_def` hash；
4. 是否存在 LGU、objectlist、warning、with_frame、PublicCan、ego、camera、IMU、GT/label；
5. 各 radar 的帧数量、frameID 单调性、跳帧和时间间隔；
6. 计算 signal validity、NaN/零值占比、恒定值和物理范围异常。

Stage A 必须可在没有 `/roscore`、没有 GUI、没有 C++ 编译产物时运行。

### 5.2 Stage B：语义抽取

按能力/用户问题最小化上下文，不把整 bag 全部塞给 AI：

- warning：`warning_status_raw`、`warning_status_with_frame`、PublicCan warning fields、重跑算法 warning；
- ego：speed、gear、yaw、accel、brake/ready、system state、enable、disable/failure；
- target：LGU `outputData`、`wfObjectMsg`、object flags、track lifecycle、class、geometry、velocity；
- calibration/config：radar position、yaw/pitch/roll、offset、vehicle dimensions、sheet、effective parameter；
- scene：camera index、image time、manual tag、GT label；
- source：调用链、条件表达式、参数声明、A2L/XCP measurement、编译宏。

抽取结果要区分：

```text
recorded_input       原始录制输入
recorded_output      原车/录制时已有输出
replay_input         回放真正喂给算法的输入
replay_output        当前代码重跑结果
runtime_debug        GDB/ROS/log 运行时观察
```

### 5.3 Stage C：时间与帧对齐

对齐优先级：

1. 同一 LGU topic 的 `header.stamp + frameID`；
2. `warning_status_with_frame=[radar_id, frame_id, w1..w15]`；
3. 同一 radar 的最近 header/bag time；
4. 跨 topic 的时间容差匹配；
5. 只有无法更强对齐时才做时间插值或 nearest-neighbor，并在报告中标记。

不能把不同 radar 的 frameID 当作全局 frameID，也不能用 wall-clock 代替 bag time。跨 radar scene 要保留每颗 radar 的原始时间和对齐偏差。

## 6. Radar ID 选择策略

### 6.1 选择优先级

1. 用户明确指定的 radar/function；
2. 带 frame 的 warning 输出中的 `radar_id`；
3. 功能/代码可行性：FCTA/FCTB 由前角 radar 1/2 的 `FrontRadarAdas()` 处理，rear radar 不能作为同一功能的默认目标；
4. 同一事件中对象 warning、LGU frame、output warning 的时间关联；
5. 运行时 node namespace/private `Radar_ID`、launch 参数、YAML installation 对照；
6. ROS topic suffix 仅作为候选，不作为最终事实。

### 6.2 多 radar 事件

- 多颗 radar 同时报警时不合并成一个“主 radar”而丢掉其他证据；按 `radar_id` 分支建立子事件，再生成跨 radar 关联事件。
- 当前 executable 同名，必须用 node namespace → PID → command line `Radar_ID` 三重确认。
- 用户选择 radar2 时，工具可以同时展示 radar1/3/4 的同窗数据，但断点/变量采集只绑定一个明确 PID，避免同名进程输出串线。
- 目标方向、左右含义必须由 radar position、orientation、source mapping 和输出数组共同确认；不能从 `front/rear` topic 名直接推断左/右。

### 6.3 选择失败处理

如果 radar ID 只能由弱证据推断，工具应输出候选列表和证据强度，进入 `input_required`，不能默认选择 radar1 或“第一个有数据的 radar”。

## 7. 预热与连续回灌契约

### 7.1 为什么必须预热

实际算法不是纯函数 `output = f(current_frame)`。连续回灌会影响：

- DataProcInit/first-frame 初始化；
- 点迹/目标跟踪与 Kalman/cluster 状态；
- object lifecycle/history movement；
- FCTA/FCTB `objFctaWarningFlag/objFctbWarningFlag` 计数；
- `lastAdasWarning`、keep/de-warning flags；
- FCTB brake hold/event time；
- system state、calibration、runtime timing；
- GUI player 和各 radar 的 ack/back-pressure 顺序。

当前远程代码证据：

- `jumpToFrame()` / `jumpToSceneFrame()` 只发布被选中的事件/scene frame；
- `playLoop()` 才是连续、按 bag 时间排序并等待 radar ack 的回灌路径；
- `RosbagTimeStamp==0`、时间回退或间隔大于 1 秒会设置 `algo_InitFlg=1`；
- `DataProcInit(isFirstFrame)` 会清理 cluster、curb、objInfo、runtime 和全局变量；
- `reSetCarData()` 会清零 ego 状态；
- FCTA/FCTB 全局 warning/keep/counter 由 `ResetAllGlobVar()` / `CloseFctaFunc()` / `CloseFctbFunc()` 等管理。

### 7.2 标准 replay window

任何需要判断当前报警行为的任务都应生成三个窗口：

```text
warmup window   [target_frame - N, target_frame - 1]
target window   [target_frame 或 event 起止]
post window     [target_end + M]
```

默认策略不是硬编码一个值，而是：

```text
warmup_frames = 150        # 默认落在用户经验的 100..200 帧中
min_warmup_frames = 100
max_warmup_frames = 200
```

工具根据以下条件调整 N：

- 目标 radar 的实际 LGU 频率和 frameID 连续性；
- 是否使用 `HILMODEL`/recorded object injection；
- 目标是否已有稳定 `lifeCycle/historyMovDist`；
- 是否跨 bag、时间回退、>1 s 间隔或明显丢帧；
- 是否需要观察 FCTB brake hold/release 等长状态；
- replay mode 是 event mode 还是 scene mode。

若用户给定“提前 100–200 帧”，工具必须以**同一 radar 的真实 LGU event/frame 序列**计算，而不是简单 `frame_id - 150`；存在跳帧时要以序列索引和真实时间同时报告。例如样例 radar2 的目标 frame `47872`：

```text
约提前 100 个 radar2 event：frame 47772，relative t≈512.434 s
约提前 200 个 radar2 event：frame 47672，relative t≈505.812 s
目标：frame 47872，relative t≈519.051 s
```

### 7.3 预热执行规则

1. 预热和目标必须在同一 replay session、同一 binary/config、同一 event/scene mode 中执行；
2. 预热必须连续发送，不能每帧 seek；
3. 预热期间仍要等待算法 ack，记录 dropped/timeout/late frame；
4. 预热期间可以降低 UI 采集和图片处理，但不能跳过算法输入帧；
5. 从目标前窗口开始时应明确触发一次“session initial reset”，不能继承上一个 bag/上一个目标的状态；
6. 预热中发生时间回退、>1 s gap、bag switch 或 ROS node 重启时，必须重新计算预热起点或标记当前 target 无效；
7. 到达目标前要验证 readiness：已消费 N 个有效 event、frameID/时间单调、无未完成 ack、node alive、没有 reset 事件；
8. 如果需要在 GUI 中停住，目标帧发出后才 pause/stop；在目标前 pause 不得破坏 algorithm state；
9. 若用户选择了目标后再点击 GUI `jumpToFrame`，工具应警告这不是 warm-up replay，除非目标前连续回灌已经在同一 session 完成。

### 7.4 预热证据

```json
{
  "warmup": {
    "requested_frames": 150,
    "actual_events": 150,
    "radar_id": 2,
    "start_frame": 47722,
    "target_frame": 47872,
    "start_time": 0.0,
    "target_time": 0.0,
    "mode": "event|scene",
    "resets": [],
    "gaps": [],
    "ack_timeouts": [],
    "ready": true
  }
}
```

## 8. 目标对象选择策略

工具必须同时回答“哪个目标导致报警”和“为什么其他目标没有被选中”。

### 8.1 选择优先级

1. 用户指定 object ID/track ID；
2. 具备功能 object warning flag 且与报警 radar/frame 同步的目标；
3. 代码输出的代表对象索引（例如 `objOutGMWIdxStruct.fctabObjNum/fctabObjIdx`，若当前版本实际发布/可采集）；
4. 在有效功能候选中按最小 `fTTC/TTMX`、有效 geometry、稳定 track ID 排序；
5. 只有没有上述证据时，才按位置/距离等弱启发式排序。

### 8.2 目标候选必须保留淘汰原因

每个目标都记录：

- `dynFlg` 是否在功能允许范围；
- FOV 是否通过；
- object type/class 是否被功能排除；
- ROI polygon 是否相交；
- TTMX/TTMY/DDCI 是否落入阈值；
- warning counter 是否达到门限；
- 是否被 `FctaSkipFlg`、`SitFctxWarnFlgByObjProp`、curvature suppression 等过滤；
- 是否因时间/消息缺失无法判断。

输出至少为 `selected_target` + `rejected_targets[]`，而不是只给一个 `objID=44`。

### 8.3 目标跟踪关联

- `objID`、`objUnqID`、`lifeCycle/historyMovDist` 和 frameID 需要联合使用；ID 改变时要做 track continuity 检查。
- 多目标同时满足时，保留 Top-N 和每个候选的条件向量；不要只保留最小距离目标。
- `wfObjectMsg.obj_class` 与 `outputData.obj_type` 可能不一致，必须保留两份原始值并标记 schema/source conflict。

## 9. 条件、变量、代码和 GDB 证据

### 9.1 条件 trace

代码检索先找调用链，再提取条件；条件输出采用四态或五态：

```text
true       有可靠数据，表达式成立
false      有可靠数据，表达式不成立
unknown    缺数据/单位/schema/宏路径不明
not_eval   本帧未走到该分支
conflict   不同来源值或版本结论冲突
```

每个条件包含源码 commit/hash、文件/行号、宏配置、原始变量、单位转换、有效性和结果。例如 FCTA/FCTB 通用条件组：

```text
system/enable
ego speed/gear/brake-ready
target dyn/FOV/type
ROI intersection
TTMX/TTMY/DDCI/fIntAng/fInterX/fInterY
object counter
warning/system state
brake hold/release
```

### 9.2 参数来源

对每个参数记录实际来源和优先级：

```text
compile-time macro
source literal/global variable
vehicle config/YAML/CUDA sheet
A2L/XCP calibration
runtime ROS parameter
frame payload/calibration
```

当前 handoff 提到 `CR60Light.A2L` 中存在大量 FCTA/FCTB measurement；远程实测文件为：

```text
/home/hoz2wx/CR60LIGHT/cr60_light_arbe/src/common_xcp_info_publisher/config/CR60Light.A2L
```

当前只完成文本级核对：该文件出现 `fFcta` 68 次、`fFctb` 42 次；这不等于已经确认“1694 个 measurement”。工具需要使用 A2L parser 按 `MEASUREMENT`/record layout 解析并报告实际可标定变量、地址、类型、单位和访问权限。

### 9.3 GDB 适配

Debug target 选择流程：

```text
ROS node name
  -> node URI / rosnode info
  -> PID
  -> /proc/<pid>/exe + command line + Radar_ID
  -> ELF/source/build snapshot
  -> breakpoint plan
  -> GDB attach or VS Code attach handoff
```

断点计划应按“事件角色”生成，而不是对所有同名函数无条件停住：

- first input frame / first target candidate；
- FOV/skip gate；
- ROI intersection；
- collision metric computed；
- counter increment/reach threshold；
- final `adasWarning` assignment；
- FCTB brake hold/release。

工具默认采集非侵入式 `gdb -batch`/日志/ROS topic；真正 attach、暂停进程和条件断点属于受控动作，需要记录暂停时长和副作用。

## 10. Replay/session manager 框架

### 10.1 Session 状态机

```text
NEW
  -> PREFLIGHTED
  -> SNAPSHOTTED
  -> WORKSPACE_READY
  -> BUILT_DEBUG
  -> ROS_STARTED
  -> PLAYER_READY
  -> WARMING_UP
  -> AT_TARGET
  -> COLLECTING
  -> PAUSED/WAITING_USER
  -> FINISHED
  -> FAILED_WITH_ARTIFACTS
```

每次状态变化写入 event log；失败也要保留 snapshot、命令、stdout/stderr、ROS graph 和已有证据。

### 10.2 两种 Replay Adapter

1. **GUIPlayerAdapter**：操作 `my_rviz_plugin` 的 Read/Play/Stop/scene/seek。当前已知服务 `/play_single_frame_<radar>` 是算法向播放器的 ack，不是加载/播放命令；如果要完全自动化，优先增加明确的 ROS service/action 控制面，或在 GUI 内提供 job API。
2. **DirectFrameReplayAdapter**：按 bag 时间/scene 规则直接发布 LGU/辅助 topic，并实现 ack/back-pressure。它不能未经验证地替代 GUI，因为 GUI 还负责辅助消息、时间匹配、状态和相机。

两个 adapter 必须输出相同的 `ReplayEvent`、`FrameAck`、`ReplayHealth` 契约，才能让上层诊断与具体播放实现解耦。

### 10.3 环境安全

- 默认不使用用户正在工作的 workspace；优先创建隔离 session/worktree 或显式复制必要资产；
- 如果只能复用现有 workspace，执行前必须保存 git status/diff/config，禁止自动 clean/reset；
- 不因为 `start` 脚本中存在 `sudo`/USB 操作就默认执行硬件动作；仿真模式必须有显式启动 profile；
- `catkin_make`、启动和 replay 都带 session ID、超时、日志路径和 kill scope；
- 不把远程 SSH key、token、X11 cookie 或 CAN credentials 写进报告。

## 11. 诊断与调参框架

### 11.1 正报/误报不是单一规则

工具输出三类判断：

1. **Algorithm reproduced**：相同版本/配置/输入连续回放产生相同输出；
2. **Requirement/scene consistency**：输入目标和工况是否满足需求/场景定义；
3. **Root-cause hypothesis**：差异来自目标误检、跟踪漂移、几何/标定、ego 信号、enable/state、阈值/滞回、时序/回放或发布链路。

没有真值时，只能说“算法行为可复现/不一致”或“与某条件冲突”，不能自动下客户责任结论。

### 11.2 参数敏感度

参数 what-if 的层级：

1. 不改代码的离线条件重算（适合纯阈值/边界）；
2. A2L/XCP 读取和受控标定修改；
3. 隔离副本修改源码/配置后 Debug rebuild/replay；
4. 多案例回归、误报/漏报/延迟/持续时间比较。

每次 sweep 必须保留参数 manifest、代码/二进制 hash、预热策略、相同目标事件和结果差异，避免只画一条无法复现的曲线。

## 12. 鲁棒性与失败处理

| 失败/不确定性 | 工具行为 |
|---|---|
| bag 缺 topic/schema/msgdef | 标记 data gap；只运行可用子集；不伪造字段 |
| message md5 与当前生成类不同 | 使用 bag 内嵌 msgdef/dynamic decoder；保留两套 schema |
| `signal_valid=0`/默认值/NaN | 不参与确定性条件；报告占位比例 |
| frameID 跳变/时间回退/>1s gap | 断开事件或重新预热；标记 reset boundary |
| radar ID 不唯一 | 输出候选和证据强度，要求确认 |
| object ID 不稳定/多个目标 | 输出 Top-N 和淘汰原因，不强选一个 |
| 当前 worktree dirty | snapshot + fail-closed；未经确认不宣称版本结论 |
| binary 无 debug symbols | 只能静态/ROS 诊断；不能声称完成 GDB debug |
| ROS master/GUI/DISPLAY 不可用 | 降级静态分析或准备命令，不循环重启用户进程 |
| replay ack timeout | 停止该 session，保存已完成帧和健康指标 |
| 参数来源冲突 | 标记 effective-value conflict，等待选择优先级 |
| AI 无法证明根因 | 输出缺口和下一步验证，不强行生成确定结论 |

## 13. 与当前 radarAnalyze 的映射

第一版工具应尽量复用现有资产：

| 框架能力 | 当前复用点 | 需要补齐 |
|---|---|---|
| Case/variant identity | `config.py`、`core/workspace.py`、`ProjectContext` | CR60 Light remote/session identity |
| bag inventory/parse | `parsers/bag_parser.py`、`BagProvider` | ROS dynamic msgdef、warmup/event index |
| data quality | `engines/data_quality.py`、provenance | per-field source/schema/validity |
| warning/event | `engines/arbe/replay_provider.py`、现有 tools | raw/replay/with_frame 多源对齐 |
| code graph/conditions | `ai/codegraph`、condition extractor | FCTA/FCTB condition vector 和宏/参数有效值 |
| remote replay | `engines/arbe/remote_replay.py` skeleton | 真 SSH/session/replay adapter，需安全授权 |
| diagnosis | `ai/modules/diag`、orchestrator、pi tools | runtime evidence、uncertainty、tuning output |
| report/bundle | `core.materials`、visualizer、DiagnosisBundle | debug transcript/reproduction manifest |

新增模块要保持：

- 远程控制不侵入确定性 parser；
- parser 不直接决定诊断结论；
- `run()` fail-soft，返回结构化 `ModuleResult`；
- 所有生成知识按 variant/customer/branch/source hash 隔离并 freshness fail-closed；
- 任何影响 `AGENTS.md` 公开接口、schema、阈值和流程的实现都同步更新文档。

## 14. 框架验收标准

在最终实现前，至少满足：

1. 对任意新 bag，可生成 topic/schema/msgdef/quality catalog，不依赖 FCTA/FCTB 专用硬编码；
2. 对任意功能，可从用户意图发现候选 warning/source/output topic，并报告缺口；
3. Radar ID、frame、object 选择有证据和回退策略，错误时不静默默认；
4. 每个目标事件都能构造 100–200 帧 configurable warm-up，并检测 reset/gap/ack health；
5. GUI scene/event 两种模式的行为差异显式记录；
6. 能从 ROS node 可靠映射到唯一 PID/ELF/Radar_ID，并确认 Debug symbol；
7. 条件结果支持 true/false/unknown/not-evaluated/conflict；
8. 报告能区分录制输出、回放输出、CAN 输出、算法输出和 GDB 观察；
9. 在远程工作区 dirty、bag 不完整、msgdef 不同、ROS 不可用时安全降级；
10. 相同 snapshot + replay plan 可复现相同事件/输出，差异能定位到版本、配置、时序或运行时。

## 15. 待确认的产品决策

这些问题会决定实现边界，暂不擅自决定：

1. 默认使用隔离 worktree/session，还是复用用户当前 `~/CR60LIGHT/cr60_light_arbe`？
2. 工具是否允许给 `my_rviz_plugin` 增加 `load/read/play/stop/seek` ROS API？
3. 工具是否允许自动 GDB attach/暂停进程，还是只生成 VS Code attach target 和 GDB command file？
4. 预热默认 150 帧是否可接受；不同项目是否要由 `warmup_policy.yaml` 配置？
5. 目标选择是否要求始终输出 Top-N 候选和 rejection reasons？
6. A2L/XCP 是只读分析，还是允许在隔离 session 中做标定 what-if？
7. 是否允许自动加入结构化 debug trace 并重编译，还是只使用现有 topic/log/GDB？
8. 最终交付是本人算法工作台，还是要面向团队/客户的可视化报告平台？

## 16. 当前可行性结论与控制策略

### 16.1 能力可行性矩阵

| 能力 | 当前可行性 | 当前证据/限制 | 结论 |
|---|---|---|---|
| bag 静态 inventory、msgdef、topic、字段和质量 | 高 | 已有 bag parser；远程 bag 可用 bag 内嵌 dynamic message class | 第一版完全放在脚手架侧，不依赖 arbe 运行 |
| 报警事件、帧、雷达和目标定位 | 高 | 已验证 warning、LGU、objectlist、`outputData`、frameID 和时间对齐 | 做成通用数据索引，不绑定 FCTA/FCTB |
| 代码调用链、条件和参数抽取 | 高 | CodeGraph、源码/宏/结构体/A2L 文件可读 | 先做静态条件证据，再接 runtime 值 |
| Linux 环境 preflight、版本快照、ROS graph | 高 | SSH、ROS Noetic、rosnode/rostopic/rosparam 可用 | 由 `radarAnalyze` 的 session manager 控制 |
| 进程 → node → PID → radar ID 映射 | 高 | 四个同 ELF 进程可通过 namespace、command line、`Radar_ID` 三重确认 | 不需要修改 arbe |
| 生成 Debug build/启动命令 | 高但需授权 | `catkin_make`、`bash start` 可用；当前 workspace dirty | 默认只生成/执行受控 session 命令 |
| 连续 100–200 帧预热 | 高 | `playLoop()`、ack、frameID 和 reset 规则已确认 | 作为 replay contract，不由 GUI seek 替代 |
| 读取 GUI 当前状态/观察 ROS 输出 | 中高 | ROS topic/service/params 可观察 | 可作为现有环境的 read-only adapter |
| 自动加载/播放/seek GUI bag | 中 | 目前只有 Qt 控件和内部 ack service，没有公开控制 API | 需要 GUI adapter 或后续最小控制 shim |
| 自动 attach 已运行 PID | 中、有 OS 条件 | ELF 有 DWARF/source path；`ptrace_scope=1`，无 `gdbserver` | 优先 VS Code handoff/launch-under-debug；attach 需权限验证 |
| 自动采集局部 GDB 变量 | 中高 | 符号、静态函数、源文件路径均可解析 | Debug build + 断点策略稳定后可做 |
| A2L/XCP 只读映射 | 中高 | `CR60Light.A2L` 存在；需结构化解析 | 可先做 read-only catalog |
| A2L/XCP 写入和在线调参 | 条件可行 | 涉及 CAN/XCP 权限、目标 ECU 和副作用 | 隔离 session + 显式授权后再做 |

### 16.2 我决定的松耦合控制方案

`radarAnalyze` 不直接依赖 arbe 的 C++ 类、私有全局变量或 GUI 源码实现，而定义稳定的 adapter 接口：

```text
CaseProvider
  -> BagAnalyzer
  -> SourceAnalyzer
  -> RuntimeAdapter
       ├─ ReadOnlyRosAdapter
       ├─ GuiPlayerAdapter
       ├─ DirectFrameReplayAdapter
       └─ ArbeControlShimAdapter (可选)
  -> DebugAdapter
       ├─ VsCodeHandoffAdapter
       ├─ LaunchUnderGdbAdapter
       └─ ExistingPidAttachAdapter (权限满足时)
  -> EvidenceStore / Diagnosis
```

控制策略分三层：

1. **默认层：脚手架外部控制**
   - SSH session executor 管理命令、日志、超时和 PID scope；
   - 通过 ROS CLI 读取 graph、topic、service、params；
   - 静态 bag 分析和代码分析不要求启动 arbe；
   - 生成可复制的 VS Code/GDB target，而不是偷偷 attach 用户进程。

2. **回放层：优先复用现有 arbe player，必要时增加最小 shim**
   - 先通过静态分析给出目标 event、预热起点、目标帧和 post window；
   - 如果用户允许控制当前 GUI，使用现有 player 完成回放并观察 ack/输出；
   - 如果需要无人值守的可靠 `load/read/play/stop/seek`，只在 arbe 的 feature branch 增加一个窄接口 `ArbeControlShim`，负责控制 player，不承载诊断、AI、数据模型或算法逻辑；
   - 如果不允许改 arbe，则使用 `DirectFrameReplayAdapter`，但必须先验证其消息选择、辅助 topic 和 ack 语义与 GUI player 一致。

3. **Debug 层：优先“启动即受控”，再考虑“附加既有进程”**
   - 隔离 session 中可以使用 Debug build + launch prefix/调试器启动目标；
   - 已运行用户进程默认只做 node/PID/source/symbol 识别和 VS Code attach handoff；
   - 只有 `ptrace` 权限、暂停副作用和恢复策略确认后，才允许自动 attach；
   - 不通过修改全局 `ptrace_scope` 或杀掉用户进程来追求“自动化成功”。

### 16.3 为什么暂时不创建 arbe feature 分支

当前静态数据分析、目标定位、代码解释、预热规划、ROS graph/进程识别和 VS Code/GDB 参数生成均可在 `radarAnalyze` 完成。立即修改 arbe 会扩大耦合面，也会把当前 dirty worktree 的问题和脚手架问题混在一起。

只有出现以下任一事实，才创建最小 arbe feature 分支：

- 现有 GUI player 无法被稳定控制，且 direct frame replay 无法复现 GUI 的辅助 topic/ack/时间语义；
- 需要在算法函数内部自动输出 `fTTMX/fTTMY/fDDCI/ROI/counter` 等当前 ROS topic 没有的中间变量；
- VS Code/GDB attach 只能通过 launch-time shim 稳定实现；
- 需要建立长期维护的结构化 debug trace，而不是一次性临时日志。

分支中的修改必须是“控制/观测适配层”，例如：

```text
arbe_debug_control.srv/action
arbe_debug_trace.msg/jsonl
frame_player control/status API
optional structured probe hook
```

不得把 `radarAnalyze` 的诊断策略、AI prompt、证据 schema 或项目记忆写进 arbe 仓。

### 16.4 针对性数据分析的最小闭环

即使不修改 arbe，脚手架也可以完成以下闭环：

```text
1. 读取 bag inventory + msgdef + signal quality
2. 发现所有 warning event 和 source provenance
3. 将 event 映射到 radar/frame/time
4. 计算同一 radar 的 warmup start（默认 150 event）
5. 选择 Top-N target，并保存 rejected reasons
6. 从源码提取对应函数、条件、阈值和宏路径
7. 从 replay/recorded topics 对齐输入与输出
8. 生成 VS Code/GDB breakpoint/condition plan
9. 用户确认后执行受控 replay/debug
10. 合并 static + replay + runtime evidence
11. 输出复现性、冲突、根因候选、性能/调参建议
```

其中第 1–8 步不需要修改 arbe；第 9 步是否完全自动化由 adapter 可用性决定；第 10–11 步仍由脚手架统一完成。

### 16.5 当前远程 debug 限制记录

当前 `10.190.171.44` 实测：

```text
ptrace_scope: 1
gdb: /usr/bin/gdb (12.1)
gdbserver: 未发现
core dump limit: 0
GUI control utilities: 仅发现 xprop/xwininfo，未发现 xdotool/wmctrl
ROS playback controls: /play_single_frame_0..4 以及 RViz config services
```

因此“能解析符号”与“能无权限附加任意正在运行的 PID”是两个不同结论。工具必须把 `attach_permission_check`、`debug_build_check`、`player_control_check` 作为 preflight 的独立 gate。

## 17. 独立项目与现有 radarAnalyze 的边界

### 17.1 价值判断

当前 `radarAnalyze` 对目标有价值，但不适合作为整个 Linux debug 脚手架的宿主：

| 当前能力 | 对新工具的价值 | 处理方式 |
|---|---|---|
| `BagParser` / `BagProvider` / data quality / provenance | 高 | 抽取为稳定 provider 或通过 JSON/JSONL 接口复用 |
| `engines.arbe` 的 replay provider/trace schema | 高 | 复用接口思想和 trace parser；远程实现重新设计 |
| CodeGraph 查询、函数/调用者/被调用者、变量读写、标定节点 | 高 | 作为可选 `RadarAnalyzeCodeProvider`；先固定契约 |
| `signal_mapper`、CAN/内部变量链 | 高 | 作为确定性映射 provider，按项目 profile 运行 |
| `ConditionExtractor` | 中 | 只复用 deterministic rule 层；AI enrichment 不进入数据真值链 |
| 当前 `config.py` 的 variant/memory/freshness | 中 | 借鉴隔离原则，不直接依赖当前配置 schema |
| 当前 `orchestrator` 固定诊断管线 | 低到中 | 不作为 remote debug 控制核心；通过 artifact/CLI 适配 |
| 当前 `PiBridge` / pi tools | 高但可选 | 作为外部编排层，不让数据模块依赖 pi |
| 当前 `RemoteArbeReplayProvider` | 中 | 只作为接口草稿，不能当作可用远程控制实现 |

### 17.2 架构决策

建议把实际实现放到独立项目，例如：

```text
cr60-debug-harness/
```

职责分配：

```text
cr60-debug-harness
  ├─ case/intake
  ├─ environment/session/ssh
  ├─ bag/static-data
  ├─ event/frame/target planner
  ├─ code-index/condition evidence
  ├─ replay/debug adapters
  ├─ evidence bundle/report
  └─ optional pi orchestrator

radarAnalyze
  └─ optional deterministic analysis provider
      (CLI/JSON contract first; private Python imports later再评估)

cr60_light_arbe
  └─ 被测运行时 / GUI player / algorithm binary
```

这样做的原因：

1. Linux host、arbe workspace、ROS distro、车型和数据路径会变化，debug harness 必须先适应变化；
2. 当前 `radarAnalyze` 正在进行 V4/模块化重构，直接嵌入 remote control 会把未稳定的项目配置和远程副作用混在一起；
3. 静态数据分析和 runtime debug 的生命周期、权限、失败策略不同，应该独立测试、独立降级；
4. 未来仍可以把成熟的 deterministic provider 以 package、CLI 或 plugin 方式接回 `radarAnalyze`，不丢掉已有投入。

### 17.3 松耦合协议

两项目之间优先使用文件/CLI/API 契约，不直接依赖私有类：

```text
radarAnalyze -> analysis_result.jsonl
radarAnalyze -> code_evidence.jsonl
radarAnalyze -> signal_mapping.json
debug-harness -> case_spec.json
debug-harness -> replay_plan.json
debug-harness -> debug_plan.json
debug-harness -> evidence_bundle/
```

每份 artifact 带：`schema_version`、`producer`、`source_snapshot_hash`、`config_hash`、`created_at`、`provenance` 和 `quality`。第一阶段可以通过子进程调用现有 `radarAnalyze` CLI，等契约稳定后再决定是否抽取共享 Python package。

## 18. 静态数据模块与 debug 模块

### 18.1 StaticDataModule

完全确定性、无需 AI、无需 ROS master、无需编译产物即可运行：

```text
bag inventory
→ msgdef/schema decoder
→ signal validity/data quality
→ alarm event segmentation
→ radar/frame alignment
→ target candidates + rejection reasons
→ warmup/target/post replay plan
```

输出不回答“是不是误报”，只输出“数据中观察到什么、哪些条件可计算、哪些缺口存在”。

### 18.2 DebugRuntimeModule

只处理受控 Linux/ROS 运行时：

```text
preflight snapshot
→ workspace/build/start
→ node/PID/radar binding
→ replay adapter
→ continuous warmup
→ target pause/debug probe
→ runtime evidence
→ teardown/health report
```

它消费 `StaticDataModule` 的 `ReplayPlan` 和 `DebugPlan`，不重新解析整 bag，也不自行推断目标。

### 18.3 Coordinator / optional pi

两模块可以独立运行：

```text
static-data --case ...
debug-runtime --plan replay_plan.json
```

需要自然语言、多轮确认、动态选择工具时，再使用 pi 作为 coordinator：

- pi 负责理解用户意图、选择模块、组织步骤、请求人工确认；
- pi 不解析原始 ROS bytes，不计算真值条件，不覆盖确定性结果；
- 所有数据模块返回结构化 artifact，pi 只编排和解释；
- pi 不可用时，CLI 仍可完成完整静态分析和受控 debug。

## 19. 代码链路预构建与快速辅助 debug

### 19.1 不能只依赖现有 code-learn

当前 radarAnalyze 已有 CodeGraphBuilder 和 CodeAnalyzeModule，支持函数、调用者/被调用者、调用链、变量读写和标定参数查询；但现状审计表明：

- regex codegraph 可能只有 FILE/FUNCTION/VARIABLE/CALIB_PARAM/MODULE；
- `STATE/TRANSITION`、`READS_SIGNAL/WRITES_SIGNAL` 和 node semantics 可能为空；
- AST 能力存在但此前未稳定成为生产默认路径；
- `ConditionExtractor.extract()` 会先做确定性规则，再默认尝试 LLM enrichment。

因此新工具要把代码准备分成“确定性索引”和“语义解释”两层，不能把 LLM 生成的 JSON 当作唯一代码事实。

### 19.2 CodeIndexProfile

每个项目/车型/分支提供 profile：

```yaml
source:
  remote_root: /home/hoz2wx/CR60LIGHT/cr60_light_arbe
  source_roots:
    - src/arbe_phoenix_radar_driver-master/arbe_gui
    - src/algo_source/adas/symmetry/perception
    - src/algo_source/coem/BYD_UKE/components/AswPerception
  compile_definitions: [GUI_BUILD_TXLGU, BUILDMODEL=2, HILMODEL=2]
entrypoints:
  - corner_radar_post_process_data_callback
  - PostProcessMainTI
  - AdasFunc
feature_keywords:
  - FCTA
  - FCTB
  - warning_status
  - fTTMX
  - fTTMY
  - fDDCI
  - objFctaWarningFlag
  - objFctbWarningFlag
files:
  focus: []
  parameter_files: []
```

profile 只是索引范围和编译语境，不把具体函数写死在 Python 代码中。

### 19.3 预构建流程

```text
1. 获取 remote source snapshot（源码文件 + HEAD + dirty diff + macros）
2. 以 entrypoint/feature keyword 找候选文件
3. AST/C/C++ parser 建 FILE/FUNCTION/CALL/READ/WRITE/CONDITION/STATE/PARAM 节点
4. 计算目标函数的 forward callees 和 reverse callers 闭包
5. 计算关键变量/结构体/字段/全局变量的读写闭包
6. 把宏、编译条件、单位和参数来源附着到条件节点
7. 生成 feature-specific `code_evidence.jsonl` 和 SQLite index
8. 只把紧凑 DebugPlan 交给 runtime/debug module
```

关键结果示例：

```text
debug_entrypoint
  -> condition groups
  -> variables read
  -> variables written
  -> threshold parameters
  -> source lines
  -> related ROS fields/topics
  -> candidate breakpoint locations
```

### 19.4 代码分析的速度策略

- 以 `source_snapshot_hash + compile_profile_hash` 缓存，而不是每次对话重新扫描；
- 先构建目标功能闭包，后台再补全全仓索引；
- AST/规则提取为证据源，FTS/embedding 只用于候选召回；
- AI 只对已经确定的函数/条件片段做解释和排序；
- 如果 AST 不可用，regex 结果标记低置信度并显式报告缺少的边，不伪装成完整调用链；
- 只有代码 snapshot、宏配置、参数文件 hash 都匹配时，才允许复用已有 code evidence。

### 19.5 面向 debug 的输出

代码模块不需要把整仓源码交给 runtime。它只输出：

```json
{
  "feature": "FCTA/FCTB",
  "entrypoints": [],
  "call_chain": [],
  "condition_groups": [],
  "variables": [],
  "parameters": [],
  "ros_bindings": [],
  "breakpoints": [],
  "source_snapshot_hash": "...",
  "confidence": "ast|rule|partial"
}
```

这样可以快速辅助 debug，又不会让 Linux runtime 控制模块依赖某个具体的代码实现。
