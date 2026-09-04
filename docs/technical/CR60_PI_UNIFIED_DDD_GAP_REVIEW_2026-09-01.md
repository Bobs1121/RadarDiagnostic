# CR60 / radarAnalyze 统一诊断平台 DDD 缺口审查与补足设计

> 文档状态：Draft for implementation / 2026-09-01  
> 审查对象：`radarAnalyze`、独立 `cr60-debug-harness`、正式 `cr60_light_arbe`、Pi capability bridge  以及已生成的 CRGVI-1829 实际产物  
> 文档用途：作为本轮 DDD 纠偏、实现切片、验收和后续 handoff 的基线。它不是某一条数据的诊断结论。

## 1. 审查结论

当前方向是正确的：`Pi` 作为唯一用户入口，外围能力以可注册的原子工具存在，独立
`cr60-debug-harness` 负责确定性 bag/帧/对象/ROI/HTML 能力，`arbe` 负责正式回放和公开
运行态，GDB 只补充公共通道无法提供的局部变量和调用栈，AI 负责解释、假设和下一步实验。

但当前系统仍是“能力底座 + 报告投影 MVP”，还不是闭环产品。主要原因不是缺少更多
功能规则，而是以下领域对象还没有统一落地：

1. **报警时间线没有统一投影**：原始报警、算法回放报警、`runtime_with_frame`、GDB
   观测和最终 CAN Tx 仍分散在不同 artifact，详细报告没有用同一组
   `function/side/radar/frame/object/source-layer` 显示比较结果。
2. **报告状态和诊断状态没有完全分离**：报告能生成不等于“报警首帧已证明”或“根因已确认”。
3. **条件追踪目前主要是静态回填**：对当前源代码可安全求值的条件可以展示，但运行时
   局部变量、状态机计数器、动态 ROI、最终 CAN 输出还没有统一 overlay 入口。
4. **Pi 上下文虽可持久化，但长链路 recipe、阶段门和恢复语义仍主要存在于文档**；
   单个工具可用不等于“数据准备→构建→启动→预检查→详细报告→debug→复验”可恢复。
5. **正式 arbe 的 frame 绑定存在客观边界**：`warning_status_with_frame` 和 `radar_info`
   有算法帧；当前 `objectlist` 消息没有算法 frameID，只有严格同帧、源码证明的发布顺序
   或 runtime bridge/GDB 才能升级对象关联等级。
6. **Gen6 适配边界已经设计，但 capability manifest、feature adapter、replay strategy、
   geometry provider 的 SPI 尚未完成跨项目验收。

 因此本轮的实施原则是：先补通用领域投影和证据契约，再补运行态采集；不新增
 FCTA/FCTB 专用规则，也不把当前样例的字段、参数或代码行固化成全局逻辑。

## 2. DDD 范围与上下文地图

### 2.1 战略设计：Bounded Context

```text
                         ┌────────────────────────────┐
                         │ Pi Orchestration Context   │
                         │ 意图、recipe、审批、恢复、对话 │
                         └──────────────┬─────────────┘
                                        │ typed tool calls / ledger refs
       ┌────────────────────────────────┼────────────────────────────────┐
       │                                │                                │
┌──────▼────────┐  ┌────────────────────▼────────┐  ┌─────────────────────▼──────┐
│ Intake &      │  │ Static Evidence Context     │  │ Source Knowledge Context    │
│ Identity      │  │ bag/frame/object/signal/ROI │  │ current source/code graph   │
│ 数据/版本/车型  │  │ sibling harness ACL          │  │ conditions/params/call path │
└──────┬────────┘  └────────────────────┬────────┘  └─────────────────────┬──────┘
       │                                │                                  │
       └────────────────────────────────┼──────────────────────────────────┘
                                        │ immutable evidence artifacts
                         ┌──────────────▼─────────────┐
                         │ Runtime Execution Context   │
                         │ arbe replay/public/GDB/CAN │
                         │ SGU 与 point-cloud 分策略   │
                         └──────────────┬─────────────┘
                                        │ additive overlay only
                         ┌──────────────▼─────────────┐
                         │ Diagnosis & Ledger Context  │
                         │ step/claim/hypothesis/exp  │
                         └──────────────┬─────────────┘
                                        │ read model
                         ┌──────────────▼─────────────┐
                         │ Report / Workbench Context  │
                         │ HTML、Markdown、Pi 摘要、UI │
                         └────────────────────────────┘

  Upstream ACL:
    bosch-data-transfert / cr60light-arbe-build → Intake & Environment
    cr60-debug-harness → Static Evidence
    arbe source / ROS public topics → Runtime Execution
    Auto Dream / memory → supporting knowledge only
```

### 2.2 Context Map 规则

| 上下文 | 类型 | 对外发布 | 不允许承担的职责 |
|---|---|---|---|
| Intake & Identity | upstream + ACL | `cr60-analysis-intake.v1`、source/data/binary identity | 不猜车型、分支、版本；不自动 checkout |
| Static Evidence | upstream sibling + ACL | `diagnosis_bundle.v1`、`viewer-model`、`event/frame/object` evidence | 不反向解析 HTML；不推断 runtime 局部变量 |
| Source Knowledge | core supporting | code index、`event-code-path.v1`、condition/parameter facts | 不把旧 index 当当前 source；不替代 GDB |
| Runtime Execution | core supporting | `runtime-case-evidence.v1`、`runtime-snapshot-with-frame.v1`、`gdb-session.v1` | 不将时间近邻对象升级为同帧；不覆盖静态事实 |
| Diagnosis & Ledger | core domain | `analysis-run/step/claim/hypothesis/experiment` | 不执行 bag 解码、GDB 或 LLM |
| Report / Workbench | read model | `diagnostic-report.v1`、HTML、阶段卡片 | 不自行重算报警规则；不把 inference 写成 observed |
| Pi Orchestration | application | `registerTool`、recipe/approval | 不直接访问文件/SSH/GDB bypass tool bridge |

其中 `cr60-debug-harness`、`bosch-data-transfert` 和正式 `arbe` 都视为外部系统；通过
窄 adapter 接入，不把其内部类、Qt widget 或脚本实现泄漏到领域核心。

## 3. 领域语言与核心模型

### 3.1 统一术语

| 术语 | 精确定义 |
|---|---|
| Data Case | 一条 bag/录制数据及其唯一 `data_fingerprint` |
| Source Context | 当前 arbe 主仓、algo_source 子仓、COEM、车型、配置和 commit 的组合 |
| Alarm Event | 某一 source layer 下一个功能/侧别/radar 的一段报警区间 |
| Alarm Frame | 具备明确语义的帧候选；必须标注是 output candidate、algorithm frame 还是 CAN Tx rising edge |
| Frame Key | `(data_fingerprint, source_context_id, radar_id, frame_id)`，不能只用时间戳 |
| Target Identity | `(objID, raw_sgu_index=i, algorithm_object_index=k, objectlist_index)` 四个可分离字段 |
| Evidence Layer | `recorded_raw`、`replay_algorithm`、`runtime_with_frame`、`gdb_observation`、`can_tx_observation` 等 |
| Runtime Overlay | 只附加运行态事实，不改写静态 bundle/viewer 的值 |
| Condition Trace | 当前 source 条件、变量绑定、代入表达式、求值状态和缺口 |
| Supported Hypothesis | 证据支持但尚未达到根因确认门的 AI/工程假设 |
| Confirmed Root Cause | 满足发布门、替代假设被削弱并有 runtime/复验或用户确认的结论 |

### 3.2 Aggregate 与 Value Object

#### `AnalysisRun`（聚合根）

一个用户问题或一次批量调查对应一个 `AnalysisRun`。它拥有：

- `goal`：业务问题和期望输出，不要求用户填写技术字段；
- `binding`：data/source/binary/vehicle/radar/function 的 provenance；
- `steps`：可恢复的阶段记录；
- `claims`：带 evidence refs 的 observed/derived/inferred 声明；
- `hypotheses`：候选根因及支持/反证引用；
- `experiments`：public replay、SGU GDB、point-cloud replay、参数扰动等；
- `artifacts`：文件路径、schema、hash 和生产者；
- `policy`：只读、审批和副作用授权。

聚合不保存大 bag 或完整代码，而保存引用和摘要；大数据通过 artifact ref 读取。

#### `EvidenceArtifact`

```text
artifact_id
schema_version
producer              # harness / arbe / gdb / source-index / ai
layer                 # evidence layer
identity              # data/source/binary/radar/frame/object/function
status                # observed / derived / partial / conflict / not_available
path_or_uri
sha256
created_at
```

#### 关键 Value Object

- `IdentityBinding`：data/source/binary 三者签名；冲突时 overlay 不可消费；
- `FrameReference`：`frame_id`、`frame_source`、`timestamp_sec`、`sequence_index`、置信度；
- `ObjectIndexMapping`：`raw_sgu_index`、`algorithm_object_index`、`objectlist_index`，每项独立 status；
- `SourceRef`：文件、行、函数、commit/source snapshot hash；
- `FieldFact`：真实 code token、value、unit、status、source ref、phase；
- `ConditionEvaluation`：raw expression、substituted expression、bindings、status、reason；
- `AlarmTransition`：signal/function、0→nonzero、frame/time、layer、是否 CAN Tx；
- `CapabilityAvailability`：supported / unavailable / blocked / stale。

### 3.3 聚合不变量

1. `data_fingerprint + source_context_id + binary_fingerprint` 不一致，禁止合并为同一运行态事实。
2. 时间相近不是同帧；没有 `frame_id` 或可证明的 callback/publication 关系时必须是 `unbound`。
3. `i`、`k`、`objectlist_index` 永远分字段；推导也要保留 `derived` 和依据。
4. `not_available`、`optimized_out`、`not_found` 不能转成 `false`；条件缺值只能是
   `not_evaluable`。
5. `recorded_raw`、`replay_algorithm`、`runtime_with_frame`、`gdb_observation`、
   `can_tx_observation` 不互相覆盖，只能形成 compare/overlay。
6. `warning_status_with_frame` 的算法帧不是 CAN Tx 上升沿；最终报警首帧只有明确的
   CAN Tx 观测才能标记为 `can_tx_rising_edge`。
7. `HILMODEL=2` 代表 SGU/目标级注入路径；点云路径必须使用独立 150–200 帧预热策略，
   不能用 3–5 帧策略代替。
8. 报告 `status=ready` 只表示投影成功；`diagnosis.status` 单独表示证据是否足够。
9. AI 只能新增 inference/claim suggestion；不能创建 observed claim，也不能覆盖工具值。
10. 任何远程写入、checkout、patch、build、start、GDB attach/execute 都必须有明确的
    plan、权限和审批记录。

## 4. 用户需求审查与验收矩阵

| 用户结果 | 需求/验收 | 当前状态（2026-09-01） | 缺口/补足 |
|---|---|---|---|
| 给文件夹即可批量预检查 | `US-001/AC-001` | 已验证 | 保留 sibling harness 作为唯一 bag parser |
| 看到一条数据的所有功能/多次报警 | `US-002/AC-002` | 部分验证 | 需跨数据格式和动态 warning mapping 验收 |
| 看到原始与仿真报警 | `US-003/AC-003` | 部分 | 增加 `alert-timeline.v1` compare 投影；无数据不伪造 |
| 看到报警功能、侧别、radar、播放帧 | `US-004/AC-004` | 部分 | 统一 playback frame map；区分算法帧和 CAN 帧 |
| 看到真实 ego/target 属性与 `i/k` | `US-005/AC-005` | 静态部分已验证 | runtime exact frame 与对象 bridge 未闭环 |
| ROI/四角/yaw/碰撞可解释 | `US-006/AC-006` | 静态派生部分 | 当前 source geometry provider、runtime polygon、碰撞状态需补齐 |
| 参数来自当前代码/车型并随帧联动 | `US-007/AC-007` | 静态 source 参数部分 | 动态 helper/runtime local 仍需 probe；禁止 index 全表当参数 |
| 真实代码调用链和可复制断点 | `US-008/AC-008` | 已可生成 | AST/宏/函数入口的跨项目准确率需验收 |
| 只用 GDB 补不可公开的临时变量 | `US-009/AC-009` | 计划/隔离 smoke | 正式 attach 受 `ptrace_scope=1` 阻断；CAN Tx 采集未完成 |
| 3–5 帧 SGU、150–200 帧点云 | `US-010/AC-010` | 策略已定义 | 两策略 runtime parity 未闭环 |
| 用户从 Pi 独立使用 | `US-024/AC-024` | Pi RPC 已实测 | 一键 recipe、resume、长链路实际验收仍缺 |
| 阶段性过程而非只给结论 | `US-011/AC-011` | Ledger MVP 已落地 | 工具调用自动落 step、claim/hypothesis/experiment 尚未全接入 |
| AI 可对话追问并调用原子能力 | `US-012/AC-012` | 基础 bridge 已有 | capability pack/shortlist 和上下文注入需补 |
| 适配不同 Gen6 项目 | `US-013/AC-013` | manifest 基础存在 | SPI 与两个异构项目验收缺失 |
| 报告不把未知当失败 | `US-014/AC-014` | condition trace 已满足 | runtime overlay 和 compare 需沿用同一状态机 |
| memory 可复用但不污染当前项目 | `US-015/AC-015` | recall fail-closed 已有 | Pi 从 context 自动注入 variant/memory scope 需补 |

### 4.1 结论发布门

报告必须按以下等级之一输出：

```text
facts_only
  已有事实和缺口，但没有足够条件评价

supported_hypothesis
  静态/runtime 证据支持一个或多个假设，但关键替代假设未排除

confirmed
  identity 无冲突；关键链路有 observed/runtime/can_tx 证据；
  至少一个替代假设被削弱；复验或用户确认完成

blocked
  输入、source、binary、运行态或对象/frame 绑定冲突，不能继续消费
```

`diagnostic-report.v1.status=ready` 不得直接等价于 `confirmed`。

## 5. 运行证据设计补足

### 5.1 统一报警时间线 `alert-timeline.v1`

本领域对象把各来源投影成相同的行，但保留证据层：

```json
{
  "schema_version": "alert-timeline.v1",
  "status": "ready|partial|blocked",
  "scope": {
    "data_fingerprint": "...",
    "source_context_id": "...",
    "event_id": "...",
    "function": "source-derived-or-empty",
    "side": "source-derived-or-empty",
    "radar_id": 2
  },
  "sources": [
    {"id": "recorded", "layer": "recorded_raw", "authority": "bag", "status": "observed"},
    {"id": "replay", "layer": "replay_algorithm", "authority": "arbe", "status": "not_available"},
    {"id": "public", "layer": "runtime_with_frame", "authority": "warning_status_with_frame", "status": "partial"},
    {"id": "gdb", "layer": "gdb_observation", "authority": "headless-gdb", "status": "not_available"},
    {"id": "can", "layer": "can_tx_observation", "authority": "CAN trace", "status": "not_available"}
  ],
  "rows": [
    {
      "source_id": "recorded",
      "layer": "recorded_raw",
      "function": "...",
      "side": "...",
      "radar_id": 2,
      "frame_id": null,
      "frame_status": "not_available|observed|derived",
      "time_sec": 519.376635,
      "transition": "rising|active|falling",
      "value": 1,
      "object_id": 44,
      "indices": {"raw_sgu_index": 0, "algorithm_object_index": 0, "objectlist_index": 1},
      "evidence_refs": []
    }
  ],
  "playback_frame_map": [
    {"frame_id": 47872, "time_sec": 519.0506, "state": "warmup"},
    {"frame_id": 47877, "time_sec": 519.3754, "state": "selected_analysis_frame"}
  ],
  "comparisons": [
    {"left": "recorded_raw", "right": "replay_algorithm", "status": "not_evaluated", "reason": "replay artifact absent"}
  ],
  "diagnostics": []
}
```

它是功能无关的；功能名、侧别、warning 名称和 CAN mapping 必须由当前 source/schema
提供。`radarAnalyze` 只做 transition、identity、frame 和 compare 投影，不实现 FCTA/FCTB
规则。

### 5.2 Runtime overlay 的输入优先级

```text
CAN Tx with explicit frame/timestamp
  > GDB observation at source frame + output call
  > runtime_with_frame warning/radar_info
  > replay_algorithm trace
  > recorded_raw warning nearest frame candidate
  > time-near candidate（只能展示为 candidate，不得绑定）
```

这是证据优先级，不是覆盖关系。较高优先级只能让比较结果更精确，不能删除低层来源。

### 5.3 条件 Trace 的两阶段模型

```text
Stage A source trace:
  current source expression + source_ref + static macro/config + same-frame recorded values
  → satisfied / not_satisfied / not_evaluable / unsupported

Stage B runtime overlay:
  exact frame GDB/public observation + local scope + code token
  → fill bindings, re-evaluate same raw expression, retain both before/after result
```

禁止把 `Stage A not_evaluable` 改写成 `Stage B satisfied` 而不保留 runtime source；也禁止
把 runtime 某个相邻帧的值用于当前表达式。

## 6. Pi 应用层与原子能力设计

### 6.1 Pi 的职责

Pi 只做：

1. 将用户话语映射为业务目标（例如“找出所有报警，先给我首帧和目标属性”）；
2. 从 `pi-orchestration-context.v1` 获取当前项目/数据/运行状态；
3. 根据阶段选择 5–12 个原子工具的短名单；
4. 生成 typed call，检查 schema、freshness 和 approval gate；
5. 每次调用记录 `AnalysisStep`，把 artifact ref、观察、缺口和下一步写入 ledger；
6. 汇总确定性结果，交给 AI 进行受证据约束的解释；
7. 根据用户追问只读取所需 artifact slice，不重新全仓搜索。

Pi 不直接实现 bag parser、ROI 算法、GDB 解析、SSH shell 或 HTML 业务逻辑。

### 6.2 原子工具分组与 recipe

原子工具保持单一职责；recipe 是 Pi 的应用层编排描述，不是新的大工具：

| Recipe | 默认阶段 | 原子能力 |
|---|---|---|
| `intake-and-prepare` | 数据准备 | `cr60-intake` → `cr60-data-prep-verify` → 受审批 `cr60-data-transfer` |
| `arbe-ready` | 环境准备 | `arbe-preflight` → `arbe-source-resolve` → `arbe-cuda-resolve` → `arbe-patch-plan` → 审批 `arbe-build` → 审批 `arbe-formal-start` |
| `static-precheck` | 初诊断 | `cr60-precheck` → `evidence-query` → `alert-timeline` → `analysis-step-record` |
| `code-ready` | 代码准备 | `code-context-refresh/read` → `event-code-path` → `condition-trace` → `code-gdb-plan` |
| `runtime-public-first` | 运行态 | `public-topic-plan` → `sim-verify` → `runtime-evidence-normalize/validate/merge` |
| `runtime-gdb` | 精细 debug | `runtime-debug-plan` → 审批 `runtime-debug-run/attach` → normalize/merge |
| `diagnostic-report` | 交付 | `alert-timeline` → `diagnosis-report` → `analysis-claim-append` |
| `dialogue-follow-up` | 追问 | `evidence-query` / `memory-recall` / `code-analyze` / `condition-trace`，只取问题所需字段 |

Pi 需要在阶段间停下的只有业务上会改变结论或产生副作用的事项，例如：版本冲突、
脏工作区是否允许编译、是否启动正式进程、是否执行 GDB。普通技术字段由工具自动发现。

### 6.3 失效/恢复语义

- 每个工具输出 artifact 或明确 `blocked`，不以异常文本作为唯一状态；
- 一个数据的 runtime 失败不得删除或阻塞该数据的静态报告；
- `AnalysisRun` 保存当前阶段、输入 artifact refs、已完成 steps、缺口和 approval 状态；
- 重启 Pi 后从 run/context/artifact refs 恢复，禁止用默认 variant 或旧 memory 偷换上下文；
- 重新运行相同 fingerprint 的确定性步骤可复用索引，runtime session 必须新建；
- 旧 source/binary/context 的知识只能显示为 stale，不能进入 AI prompt。

## 7. 报告与 Workbench 设计

### 7.1 `diagnostic-report.v1` 读模型补足

报告最少包含以下互相独立的区块：

```text
identity
  case/data/source/binary/vehicle/coem/HILMODEL/provenance
overview
  all event count / function / side / radar / layer coverage
selected_event
  alarm interval / frame semantics / ego / target / i-k mapping / ROI / media
alert_timeline
  raw vs replay vs runtime vs GDB vs CAN rows + playback frame map + compare
geometry_projection
  runtime/source polygon and ROI source/status; same-frame geometry may be observed/derived, while missing coordinate/runtime contract stays not_evaluated
condition_trace
  raw code condition / real bindings / substituted expression / status / source ref
diagnostic_narrative
  逐条条件文字解释 + should_alert（yes_observed/supported_yes/indeterminate）
diagnosis
  facts_only / supported_hypothesis / confirmed / blocked + gaps + alternatives
analysis_trace
  step cards / observations / user decisions / next actions
evidence_layers / conflicts / input_refs / artifact_refs
```

### 7.2 页面布局

采用场景优先的三栏布局，三栏独立滚动；中间 Scene/Timeline/Code/Debug/Media 固定工作区。

- 左：项目 → 数据 → 功能 → 报警事件 → AnalysisStep；另有原始/仿真图例；
- 中：可缩放 scene、连续帧时间线、报警比较条、曲线、代码链路、媒体；
- 右：当前帧事实、ego/target/source/runtime、条件 trace、claim/gap、下一步；控件内滚动；
- 详细属性默认折叠，点击 ego/target 展开，不长条堆叠；
- `not_available`、`not_evaluable`、`unbound` 必须用状态标签和原因展示；
- 点击帧时所有面板切换到同一 `FrameKey`，不允许目标属性来自时间近邻候选而不提示。

### 7.3 阶段性分析卡片

每个 step 显示：

```text
发现：...
依据：artifact/path/frame/object/source ref
已确认：observed/derived facts
仍未知：critical gaps
影响：能否进入下一阶段/能否下结论
下一步：tool + expected discrimination
```

用户看到的是调查过程；最终报告只是同一 ledger 的快照投影，不隐藏中间失败和冲突。

## 8. 当前实现与关键补足计划

### 8.1 本轮必须补的 P0/P1

| ID | 补足 | 实现边界 | 退出标准 |
|---|---|---|---|
| P0-1 | `alert-timeline.v1` | 从 bundle/runtime/snapshot/trace 构造统一 timeline，不解析 bag | 单元 fixture 能得到 raw/replay/runtime/CAN 缺失状态和 frame map |
| P0-2 | 报告接入 timeline + conclusion/narrative | 只投影，不诊断规则；report status、diagnosis level 和 should_alert 分离 | 当前 CRGVI-1829 报告明确显示 raw 有、replay/runtime/CAN 无，不误报完成 |
| P0-3 | source/binary/runtime identity gate | report 和 timeline 都列 conflict | 不同 source snapshot 的 overlay 不能进入 selected event |
| P1-1 | runtime condition binding | 用同一 frame 的 runtime field facts 回填 condition trace | runtime 值可重新求值并带 `gdb_observation` provenance |
| P1-2 | Pi context→memory scope | `memory-recall` 只消费显式 context 的 variant/memory dir | 不传 variant 时 code knowledge 仍 blocked_stale |
| P1-3 | DDD 文档/矩阵校正 | 更新需求、Sprint、文档索引、handoff | 每项状态与实际证据一致 |
| P1-4 | warning 位语义映射 | trace parser 优先消费当前 runtime/source schema；无映射保留 `wN` | 不同 Gen6 项目不会被 CR60 的 15 位默认表误标 |
| P1-5 | Pi 原子调用可见性 | tool-end 事件追加 child AnalysisStep，dialogue step 保留回合摘要 | 长链路可看到每个工具的状态/产物，且不记录隐藏思维链 |

### 8.2 后续 P1/P2

- `runtime_snapshot_with_frame` 最小 bridge：在现有 `wf_object_display_handler` 公开路径
  输出 frame/callback/raw→algorithm mapping，不改变算法决策；
- formal arbe lifecycle + `ptrace_scope` 可行性探测；
- Hypothesis/Experiment 由 Pi 自动创建并回填 evidence；
- capability pack/manifest SPI 与第二个 Gen6 项目；
- point-cloud 150–200 帧连续 perception/tracking runtime trace；
- Live Workbench 与静态 HTML 共用 read model；
- 参数 what-if/replay parity 和最终修复复验。

## 9. 实际证据基线

本轮审查使用的当前产物（作为设计证据，不作为长期固定路径）：

- `outputs/single_case_actual_CRGVI1829_20260901/batch/.../diagnosis_bundle.json`
- `outputs/single_case_actual_CRGVI1829_20260901/batch/.../viewer-model.json`
- `outputs/single_case_actual_CRGVI1829_20260901/detailed-report-FCTA_R/diagnostic-report.json`
- `outputs/single_case_actual_CRGVI1829_20260901/ddd-audit-report-FCTA_R-runtime-run5/diagnostic-report.json`
- `outputs/single_case_actual_CRGVI1829_20260901/analysis_runs_final_pi/.../analysis-run.json`
- 远程工作区：`10.190.171.44:/home/hoz2wx/CR60LIGHT/cr60_light_arbe`

已确认的事实：

1. 当前单条数据静态预检查可发现多功能事件和多 radar；
2. `FCTA_R/radar2/frame=47877` 可拿到真实 token 的 ego/target 字段、`objID=44`，并区分
   `raw_sgu_index=0`、`algorithm_object_index=0`、`objectlist_index=1`；
3. `frame=47877` 当前是 nearest-LGU/time-aligned candidate，不是已证明的 CAN Tx 上升沿；
4. source-derived condition trace 当前有若干 `not_evaluable`，这是正确的缺口表达，不是条件失败；
5. 正式 `objectlist` 无算法 frameID，不能仅凭 GUI 时间或 ROS publish time 宣称同帧；
6. Pi 已能调用 `evidence-query`/`diagnosis-report` 并生成 ledger，但长链路自动 resume 和最终
   runtime/CAN 证据还未闭环；
7. 正式 PID attach 受服务器 `ptrace_scope=1` 影响；isolated launch-under-GDB 是可用的安全路径，
   但不能冒充正式 GUI player parity。
8. 当前 sibling bundle 没有携带独立 `data_fingerprint`，因此本轮 timeline 的 data identity 标为
   `partial`；不能用 artifact 文件 hash 冒充 bag hash，后续应由上游 bundle/数据准备契约补齐。
9. 复用已保存的 public runtime run5 artifact 后，`runtime_with_frame` 可进入详细报告并提供
   60 条同 radar/frame 的报警字段；由于 raw 首帧仍是 derived、CAN Tx 未观测，报告只升级
   `should_alert=supported_yes`，不升级 `conclusion.level`。

### 9.1 报告呈现策略：先解释，后展开

本轮根据实际使用反馈收敛了详细报告的默认信息密度。报告首页不再把所有字段、对象列表和候选
条件当作结论堆叠，而是按以下顺序呈现：

1. `executive_summary`：标出功能/侧别/radar/frame/objID，并概括自车和目标的关键真实 token；
2. `alarm_assessment`：区分原始录制、算法/公共运行态输出和 CAN Tx，不把算法输出冒充 CAN 首帧；
3. `condition_items`：只显示最多 10 条当前功能相关、已求值或最影响判断的条件，保留源码路径、行号、原始表达式、代入表达式和原因；
4. `condition_digest`：给出总数、已展示数、被省略数和仍缺失的关键运行时量；
5. 选中帧场景、关键 ego/target/runtime facts 和报警转换行；
6. 完整 `condition-trace.v1`、`alert-timeline.v1`、selected event 和 runtime transcript 仍在折叠区及 JSON
   artifact 中可展开，数据没有被删除。

场景图还输出 `geometry_projection.collision_status`：当目标 polygon 和当前功能 ROI 来自同一帧
runtime observation 时计算 `observed_intersects/observed_disjoint`；只有当前代码推导的目标角点
和 ROI 时计算 `source_derived_intersects/source_derived_disjoint`。图中同时标出几何来源、目标四角
和 containment 状态。该结果只回答几何关系，仍不替代 `fInterX/fInterY`、目标 warning flag、
状态机计数和 CAN Tx 等功能链路条件。

### 9.2 Pi 事实锚点与交互入口

实际 Pi 回合验证暴露出一个领域不变量：同一 case 存在多次事件时，用户明确写出的功能/侧别必须
先锁定 scope，不能因为事件重复而退回 case 中的第一个功能。`ai/modules/pi.py` 现在从输入
artifact 中解析显式 function/side/frame/radar，生成 `evidence_anchor`，并将显式 runtime、
viewer、code path 和生成的 report refs 绑定到 `AnalysisRun`。Pi 只解释 anchor，不能把旧
`report.md`、模型常识或静态字段改成 runtime/CAN observed。

当用户要求生成报告或提供 `output_dir` 时，Pi 入口使用同一 `diagnostic-report` engine 生成
HTML/Markdown/JSON；因此模型没有主动调用 `diagnosis-report` 时，交付物仍然存在。anchor 还会
记录为 `evidence-anchor` AnalysisStep，和后续 dialogue/tool steps 一起构成可恢复的交互轨迹。
Pi 超时返回 `ok=false`，但保留已经生成的 report artifact 和部分回答，不能伪装成成功。

本次真实 artifact 还发现并纳入通用质量检查：事件 scope 为 `radar=2`，但事件内部的
`frame.gui_main_mapping` 指向 `radar_id=3`、`/wf/corner_radar/lgu_data_3`。报告现在输出
`frame_radar_mapping_conflict`，继续使用事件自己的 `radar=2` 和 `frame.source_ref`，并禁止
把冲突 GUI 映射用于目标/报警结论。这类检查按字段和 provenance 实现，不针对某个 case 写特判。

这是展示层读模型约束，不是新的功能规则。选择条件时根据当前事件的功能提示（例如 FCTA/FCTB）
优先当前功能表达式，同时保留公共/状态机条件；候选条件不自动构成完整 AND 链。这样 Pi 或用户
看到的是“目前能证明什么、不能证明什么、下一步该取哪个真实运行时量”，而不是无上下文的数值表。

## 10. 本轮验收命令与结果记录

本轮实现完成后仅运行定向检查：

```powershell
python -m pytest -q tests/test_alert_timeline.py tests/test_condition_trace.py tests/test_memory_recall.py tests/test_product_capabilities.py tests/test_replay_provider_mapping.py tests/test_arbe_remote_replay.py tests/test_pi_tool_bridge.py
python cli.py capabilities --json
python -m py_compile engines/alert_timeline.py engines/diagnostic_report.py ai/modules/alert_timeline.py
```

本轮上述扩展定向组合实际结果为 `97 passed`；另完成 `sim-verify` 动态 warning mapping、
Pi bridge 和 py_compile 检查。

报告呈现收敛后的新增定向检查：`test_diagnostic_narrative.py` 增加 compact selection、
`executive_summary`、`condition_digest` 和真实 token 保留断言；报告重新生成了静态、public runtime
和 GDB 三个真实输入版本。

实际运行的单数据报告必须满足：

- HTML/JSON 出现 `alert_timeline`、`playback_frame_map`、`condition_trace`；
- raw 有报警但没有 replay/runtime/CAN artifact 时，compare 为 `not_evaluated/not_available`；
- 报告可以生成，但 diagnosis level 不得写成 `confirmed`；
- 所有技术值保留 token、来源、frame semantics 和 status；
- 不修改远程 arbe，不执行全量回归。

## 11. 开放问题（只问用户业务选择）

以下不阻塞本轮确定性实现，后续进入 Workbench 时再确认：

1. 默认是否自动从静态预检查跑到 `debug-ready`，只在远程写入/启动/GDB 前暂停？建议是。
2. 用户手工 VSCode debug 后，第一版采用页面粘贴 GDB 输出回填，还是直接做 VSCode bridge？
3. 多用户是否需要同一 `AnalysisRun` 协作批注，还是先单用户本地运行？
4. “confirmed” 是否必须由问题单负责人/算法工程师人工确认？建议必须人工确认。

## 12. 版本决策

- D-20260901-01：`alert-timeline` 是独立、功能无关的投影能力；不把它塞进某个 FCTA/FCTB
  handler，也不重复 sibling harness 的 bag parser。
- D-20260901-02：详细报告展示“可确认事实 + 缺口 + 候选”，不在缺少 runtime/CAN 时自动生成
  正误报结论。
- D-20260901-03：public runtime 优先于 GDB；GDB 只补 public 不可见的局部变量、栈和精确
  output/CAN 链路。
- D-20260901-04：Pi 的 recipe 是应用编排，不新增一个包办所有事情的超级工具；所有动作仍
  通过 registry/bridge 进入 ledger 和 approval gate。
- D-20260901-05：`memory-recall` 必须绑定当前 `pi-orchestration-context.v1` 的 variant/source
  freshness，不得隐式使用 config default variant。
