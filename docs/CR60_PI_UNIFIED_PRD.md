# CR60 统一诊断与运行时调试平台 PRD

版本：prd.v2.5  
日期：2026-09-01  
状态：DDD 需求基线；三出口纵向切片进入实现验收  
产品代号：CR60 Pi Unified Diagnostic Platform

关联文档：

- [统一文档索引](technical/CR60_PI_UNIFIED_DOCUMENT_INDEX.md)
- [统一调研报告](CR60_PI_UNIFIED_RESEARCH_REPORT_2026-08-26.md)
- [arbe 核心能力复用调研](technical/CR60_PI_UNIFIED_ARBE_REUSE_ASSESSMENT.md)
- [真实用户流程确认表](technical/CR60_PI_UNIFIED_USER_WORKFLOW_QUESTIONNAIRE.md)
- [系统设计](technical/CR60_PI_UNIFIED_SYSTEM_DESIGN.md)
- [模块设计](technical/CR60_PI_UNIFIED_MODULE_DESIGN.md)
- [软件设计](technical/CR60_PI_UNIFIED_SOFTWARE_DESIGN.md)
- [实施方案](technical/CR60_PI_UNIFIED_IMPLEMENTATION_PLAN.md)
- [Sprint 规划](technical/CR60_PI_UNIFIED_SPRINT_PLAN.md)
- [架构决策记录](technical/CR60_PI_UNIFIED_DECISIONS.md)
- [DDD 用户故事与验收基线](technical/CR60_PI_DDD_REQUIREMENTS_AND_ACCEPTANCE.md)
- [架构复盘与演进设计](technical/CR60_PI_UNIFIED_ARCHITECTURE_REVIEW_2026-08-30.md)

## 0. 本版本解决什么问题

本 PRD 将产品从“批量生成静态 HTML 报告”扩展为一个可逐步升级的工程诊断平台，明确四条边界：

1. Sprint1 是确定性数据预检查和证据整理，不把静态推导冒充运行时事实。
2. runtime debug 是对当前 source context、当前 binary、当前 replay 状态的受控观测，优先 SGU 目标注入，再支持 point-cloud。
3. Pi 是统一入口和任务编排者，确定性工具负责解码、索引、映射、回放和证据收集，AI 负责意图理解、代码解释、证据串联和候选原因排序。
4. 分析过程本身是产品能力；用户必须能逐步查看观察、条件、缺口、冲突、候选原因和
   Debug 实验，而不是只收到一次最终结论或代码方案。

本产品的长期价值不是再造一个 arbe GUI，而是把“数据、代码、环境、回放、调试、证据、解释、验证”串成可复现的工程流程。

## 1. 产品定位和产品契约

### 1.1 产品定位

面向 Corner Radar/CR60 ADAS 工程师的数据诊断与运行时调试 Harness。

用户可以提供一条数据、一个问题单目录或一个批量数据目录，并指定或确认：

- 数据和材料；
- arbe workspace；
- src/algo_source 代码版本；
- 车型、COEM、CUDA/配置；
- 回放模式；
- 是否允许编译、启动、attach 和导出 runtime trace；
- 关注的功能、侧别、目标和时间范围。

产品输出可追溯的证据包、每条数据的 HTML、批量索引、代码链路、真实变量断点和可选 runtime trace，帮助工程师回答：

- 哪些功能真的输出了报警；
- 报警从哪一个信号、哪一帧、哪一个目标或内部状态开始；
- 当前对象是否进入了算法实际使用的 ROI；
- 自车、雷达、目标、坐标和参数是否在同一语义下；
- 问题更接近 perception、situation、功能逻辑、配置、回放还是数据质量；
- 下一步在 VSCode/GDB 中应该在哪个真实代码位置观察什么变量；
- 调参或代码修改后，如何在同一输入和同一版本下复现、比较和验证。

### 1.2 产品不是哪些东西

本产品不是：

- 一个替代 arbe 的完整可视化 GUI；
- 一个固定写死 FCTA/FCTB 参数的规则引擎；
- 一个仅靠 rosbag 就能获得全部 C/C++ 局部变量的离线解析器；
- 一个把任何数据都自动判定为正报或误报的黑盒分类器；
- 一个自动修改用户工作区、切分支、提交代码或发布软件的机器人；
- 一个把当前 10.190.171.44、一个车型或一个 COEM 当成全平台默认值的脚本；
- 一个通过近时间 objectlist 候选补齐缺失 runtime 目标的推断器。

### 1.3 产品核心原则

| 原则 | 产品行为 |
|---|---|
| 证据优先 | 每个字段都记录 source、frame、artifact 和 freshness |
| 版本绑定 | 数据、外层仓、子仓、COEM、配置、binary 必须形成 source context |
| 动态 schema | 每次切换代码、车型或 COEM 都重新探测结构、参数和调用链 |
| 事实分层 | observed_bag、observed_runtime、derived_from_active_source、not_available 分开显示 |
| 失败闭环 | 版本、frame、坐标、目标身份或 GDB 条件不满足时显式阻断 |
| 复用优先 | 通过 adapter 复用 arbe 的播放器、消息和 ACK，不复制核心算法 |
| AI 有边界 | AI 不修改原始数值，不替代确定性解码，不把猜测写成事实 |
| 可插拔 | 新功能、新项目、新服务器、新回放方式通过 provider/plugin 接入 |
| 可复现 | 相同输入、代码、binary 和 profile 应得到可比较结果 |
| 最小副作用 | 读分析优先；任何远程写、编译、启动、attach、停止都要受控和可审计 |
| 过程可见 | 每个阶段输出可查看的 step、claim、gap、hypothesis 和 next experiment |
| 人机协同 | 自动 headless 与人工 VSCode debug 共享同一事件、断点、变量和证据账本 |
| 报告是投影 | HTML/总结由 AnalysisRun 状态生成，不在展示层重新猜测事实 |

### 1.4 证据等级和结论措辞

| 状态 | 含义 | 允许的结论 |
|---|---|---|
| observed_bag | 当前 bag 直接解码的字段 | 可作为录制数据事实 |
| observed_runtime | 当前 binary 当前进程当前 frame 被 GDB/bridge 读到 | 可作为运行时事实 |
| derived_from_active_source | 用当前源码和已知输入计算 | 可作为源码推导，不能称算法实际值 |
| derived_runtime_mapping | 根据 index、时间或调用关系映射 | 必须标明映射依据和置信度 |
| not_logged | 当前数据/输出没有这个字段 | 不得用默认值补齐 |
| runtime_probe_required | 只有运行时才能确认 | 必须给出下一步 probe |
| optimized_out | GDB 因优化无法获得 | 不得把邻近变量或历史值代替 |
| source_mismatch | 当前源码和预期不一致 | 阻断代码解释 |
| binary_source_mismatch | binary 与 source context 不一致 | 阻断 runtime 结论 |
| frame_mismatch | 时间接近但不是同一 frame | 不得合并对象和报警证据 |
| coordinate_contract_missing | 原点、轴向、角度或单位没有证据 | 不得输出正式 geometry/collision 结论 |
| conflict | 多个来源互相矛盾 | 展示冲突及来源，交由工程师确认 |

## 2. 目标用户、用户任务和责任边界

### 2.1 用户角色

| 角色 | 主要任务 | 产品交付 |
|---|---|---|
| 雷达算法工程师 | 分析报警是否符合功能条件、查看变量和调用链 | 事件证据、runtime 变量、条件断点、代码链路 |
| 感知/跟踪工程师 | 观察点迹、聚类、目标生命周期和对象属性 | 连续帧 trace、目标身份、point/filter/cluster/track 证据 |
| 仿真工程师 | 准备 arbe、回放数据、复现版本和运行状态 | 环境 fingerprint、replay plan、回放日志 |
| 测试工程师 | 批量预检查、统计报警、核对期望和实际 | batch index、事件清单、报告和缺口 |
| 问题单负责人 | 汇总证据、形成下一步行动 | 可分享 HTML、机器可读 bundle、结论确认状态 |
| 平台维护者 | 接入新仓、新车型、新消息和新功能 | provider/plugin、schema、测试和文档 |

### 2.2 用户与工具的责任分工

用户负责确认：

- 真实工程流程和业务定义；
- 哪个 workspace 可以操作；
- 数据与代码版本的权威绑定；
- 允许的远程副作用；
- 报警第一帧和事件拆分口径；
- runtime 结论的人工确认。

工具负责：

- 发现和校验仓库、数据、配置和 binary；
- 从当前代码生成 schema、参数、调用链和 breakpoint 候选；
- 以确定性方式解码和对齐数据；
- 调度既有 replay/provider；
- 采集并保存 runtime 证据；
- 展示缺口、冲突和复现条件；
- 让 Pi 可以按结构化能力调用上述模块。

## 3. 端到端使用流程

### 3.1 标准流程

~~~text
1. intake
   用户给出 bag/目录 + arbe/source context + 运行权限
2. preflight
   探测服务器、workspace、代码、COEM、配置、binary、ROS 能力
3. source learn
   当前代码生成 feature/schema/parameter/call-chain 索引
4. data precheck
   解析 topic、报警、frame、ego、对象、视频和数据缺口
5. event resolve
   生成多功能、多次报警的独立 event 及候选目标/index
6. evidence report
   生成每条数据的 bundle、HTML、断点建议和下一步 probe
7. runtime plan
   用户选择人工辅助、SGU headless 或 point-cloud runtime
8. replay/debug
   受控回放、条件断点、runtime snapshot、GDB transcript
9. evidence merge
   静态 bundle 与 runtime overlay 合并，不覆盖原始证据
10. explain/verify
   Pi 串联代码、数据、需求和历史案例，输出候选原因、验证步骤和回退方案
~~~

### 3.2 当前已确认的真实用户流程

用户已确认的当前工程流程是：

1. 先将数据传到 Linux 服务器；
2. 根据数据绑定的软件版本切换 `src/algo_source` 子仓分支/tag；
3. 数据同时唯一确定所属 COEM 和具体车型；
4. 在 arbe 中更新对应 CUDA 表、车型配置和其他配置参数；
5. 编译 arbe 外层主仓；
6. 执行 `bash start` 启动仿真工具；
7. 在工具中导入数据并播放；
8. 在 VSCode 中使用 `ROS: Attach`，等待进程出现后选择 `arbe_visualization_engine` 以及对应的 radar1/2/3/4 进程；
9. 首版优先由 headless GDB 自动获取中间变量，并将 runtime 结果直接写入 HTML。

自动化原则：上述流程原则上全部由工具执行；在数据/版本/车型/COEM/CUDA 解析确认、原 workspace 写入确认、编译启动确认、GDB attach 确认等关键边界进行一次性审批，不要求用户确认每一条内部命令。

SGU 目标注入模式的前置策略：`HILMODEL=2` 是当前模式的必要条件；默认在目标事件前按实际 `frameID` 预热 3–5 帧，不套用 point-cloud 的 150–200 帧规则。

报警第一帧口径：以算法向 CAN 信号输出报警位的 0→非零上升沿为准。UI 首次显示、内部条件满足和其他消费侧时间仅作为辅助证据，不替代该口径。

### 3.3 生命周期状态

| 状态 | 进入条件 | 可执行动作 | 失败后 |
|---|---|---|---|
| CREATED | 收到用户输入 | 生成 run_id | 缺输入则 BLOCKED_INPUT |
| INTAKE_VALIDATED | 输入字段通过 | 读取数据/仓库元信息 | 标记缺失字段 |
| SOURCE_READY | source context 可验证 | 生成 schema/代码索引 | SOURCE_MISMATCH |
| DATA_READY | 数据可解析 | 事件/目标/frame 分析 | DATA_UNSUPPORTED |
| REPORT_READY | Sprint1 bundle 完成 | 查看 HTML/断点 | 允许人工调试 |
| RUNTIME_APPROVED | 用户确认副作用 | runtime preflight | PERMISSION_BLOCKED |
| REPLAY_READY | replay plan 和环境通过 | SGU/point-cloud replay | REPLAY_BLOCKED |
| PROBING | GDB/bridge 正在采集 | continue、采样、停止 | PROBE_TIMEOUT |
| RUNTIME_READY | trace 完整并校验 | merge/explain/compare | TRACE_INCOMPLETE |
| VERIFIED | 用户确认结果 | 保存反馈/生成验证计划 | 可进入 code-fix/sim-verify |
| FAILED/BLOCKED | 不可安全继续 | 只读报告和修复建议 | 不允许假结论 |

### 3.4 四种用户运行模式

| 模式 | 用户动作 | 工具动作 | 适用阶段 |
|---|---|---|---|
| A 静态预检查 | 给数据和代码上下文 | 只读解析、生成报告 | Sprint1 默认 |
| B 人工辅助 debug | 用户在 VSCode 选择 ROS: attach | 工具提供真实断点、frame、target、变量清单 | headless 失败时的可视化兜底 |
| C headless runtime | 用户确认远程权限和运行策略 | Supervisor 调度 replay/GDB，生成 trace | SGU MVP 首选 |
| D point-cloud runtime | 用户确认 warm-up profile | 预热状态后采集感知到功能链 | 后续 Sprint |

### 3.5 默认分析节奏

默认不是“一次性运行到最终根因”，而是自动推进到下一条有业务价值的检查点：

```text
输入绑定
  → Event Map
  → 事件场景/目标身份
  → 当前代码链路
  → 静态条件回填
  → 初步 hypothesis board
  → 最小成本 runtime/public evidence
  → headless 或 VSCode DebugExperiment
  → 根因收敛与修复/调参复验
```

每个阶段都显示：发现、证据、假设、冲突、关键缺口、下一步能排除什么。用户可以暂停、
切换事件、质疑结论、选择下一实验或转入人工 debug。Pi 自动模式只在身份冲突、关键证据
选择和副作用审批前中断；精细模式可以在每个 AnalysisStep 后停下。

## 4. 产品输入契约

### 4.1 输入分层

输入分为四层，不允许把其中一层的缺失用另一层的猜测代替。

| 层 | 内容 | 典型来源 |
|---|---|---|
| Data | bag、目录、视频、CSV、日志、截图、标注 | 用户/上游数据准备 skill |
| Source | outer arbe、algo_source、branch/tag/commit、COEM | 用户/仓库探针 |
| Runtime | server、workspace、binary、ROS master、GDB 权限 | 用户/环境探针 |
| Semantics | 报警口径、warm-up、side mapping、ground truth | 真实用户确认 |

### 4.2 最小 intake

概念 schema：cr60-analysis-intake.v1。

~~~yaml
run:
  request_id: optional
  user: optional
  mode: static_precheck | assisted_debug | sgu_runtime | point_cloud_runtime
  output_root: required

data:
  path: required
  kind: bag | folder | handoff
  recursive: true
  software_version: required_or_discovered
  coem_project: required_or_discovered
  vehicle_project: required_or_discovered
  related_video: optional
  related_csv: optional
  issue_materials: optional

source_context:
  arbe_root: required_for_runtime
  algo_source_root: required_for_runtime
  outer_branch_or_commit: required_for_runtime
  algo_branch_or_commit: required_for_runtime
  coem_project: required_when_ambiguous
  vehicle_project: required_when_ambiguous
  config_profile: optional
  mismatch_policy: block

server:
  host: required_for_runtime
  user: required_for_runtime
  connection_profile: required
  workspace_policy: isolated_copy | confirmed_original | read_only

runtime:
  replay_strategy: auto | sgu_injection | point_cloud
  radar_id: optional
  radar_pos: optional
  target_event_id: optional
  target_frame: optional
  target_obj_id: optional
  warmup_frames: optional
  allow_build: false
  allow_start: false
  allow_attach: false
  allow_stop: false
~~~

上面是接口形状，不是所有项目的固定字段表。实际字段、功能和参数由当前 source context 生成并写入 schema artifact。

### 4.3 必填、可探测、必须阻断

| 输入 | 可否自动探测 | 规则 |
|---|---|---|
| bag/目录 | 可探测路径内容 | 路径不可读或无支持文件则阻断 |
| outer arbe 根目录 | 可探测候选 | 多候选且用户未确认则阻断 |
| algo_source 版本 | 可读 Git 状态 | 与数据绑定冲突则阻断 |
| COEM/车型 | 可读配置和目录 | 多候选或缺失且影响编译则阻断 |
| radar_id | 从 topic/配置/运行时获得 | 多来源冲突则保留冲突，不能猜 |
| 功能和报警侧 | 可从信号候选发现 | 业务权威不明确时标记待确认 |
| GDB target | 可从进程/launch 探测 | 不唯一或无符号则阻断 runtime |
| warm-up | 可从 profile 建议 | 未验证时必须标记 derived/profile，不称通用真值 |
| 目标 objID | 可从数据/runtime 发现 | 不稳定时输出候选集合和置信度 |

### 4.4 版本和配置来源优先级

默认优先级由用户确认后冻结为项目 profile：

当前用户已确认的业务规则是：数据先被认为属于一个确定的软件版本、一个 COEM 和一个具体车型；这个绑定关系决定后续子仓分支、CUDA 表和配置。工具必须找到该绑定的实际载体（数据元数据、上游 handoff、问题单字段或目录约定），不能只根据文件名猜测。

~~~text
数据中可验证的软件版本/车型/COEM 元数据
  > 用户确认的 source/branch/commit 与数据绑定
  > 上游 handoff 中的绑定字段
  > 问题单/Excel 版本字段
  > 仓库当前 HEAD
  > 工具推导候选
~~~

任何自动推导都必须写入：

~~~text
value
source
source_fingerprint
inference_rule
confidence
conflict
~~~

工具不得在版本缺失时偷偷使用服务器默认 branch。

### 4.5 输入完整性结果

输入校验必须返回结构化结果：

~~~json
{
  "status": "ready | blocked_missing_input | conflict | unsupported",
  "missing": [],
  "conflicts": [],
  "warnings": [],
  "resolved": [],
  "provenance": []
}
~~~

### 4.6 材料优先、对话补齐的 intake

用户不需要预先掌握固定表格格式。每次 run 按以下方式收集上下文：

1. 先扫描用户提供的文件夹、handoff、Excel、日志、源码路径和已有报告；
2. 能从材料确定的字段自动解析，并回显值、来源和置信度；
3. 缺少影响版本、车型、COEM、功能、回放或 GDB 的字段时，Pi 只提出针对缺口的问题；
4. 用户在对话中补充路径、配置、版本或语义后，更新同一个 intake，不要求重新描述已经识别的内容；
5. 直到字段齐全、冲突解决或用户明确选择只做部分静态分析，再进入对应阶段。

因此，材料来源可以是 Excel、问题单 handoff、数据目录约定、单个 bag、源码仓库、已有报告或对话补充；这些来源统一归一到 data/source/runtime/semantics 四层，并写入 provenance。

### 4.7 用户交互语言边界

工具面向真实使用者时，不能把内部实现知识当作输入前提。以下内容由工具自动探测或
由 source/runtime schema 生成，不作为默认提问：`frameID`、`radar_id`、`objInfo`、
`objInfo->trcOutData[i]`、ROI 点、PID、GDB 命令、函数行号、消息数组下标和变量名。

只有当候选冲突会改变结果或执行动作会产生副作用时，Pi 才向用户提出确认，并使用
业务语言说明影响，例如“按录制报警还是按当前代码回放结果生成报告”“是否允许在隔离
环境自动复现”“最终报告主要用于代码定位还是客户解释”。用户无法判断技术候选时，
工具应先完成不产生副作用的静态/隔离分析，并把缺口、影响和下一步写入 handoff，不能
要求用户解释自己不熟悉的实现细节。

## 5. 产品输出契约

### 5.0 独立产品入口

用户脱离 ChatGPT 后，使用 Pi 交互入口完成整个问题分析流程。Pi 是唯一产品入口，负责理解
业务问题、选择当前可用原子能力、呈现阶段性结果和等待关键确认；数据解码、源码索引、条件
求值、远程环境操作、回放、GDB 和报告生成仍由独立工具完成。用户不需要记忆内部 CLI 顺序，
但每个副作用动作（数据传输、补丁、checkout、CUDA/config 写入、编译、启动、GDB attach/execute）
都必须在 Pi 中展示计划后确认。

### 5.0.1 报告必须回答的三个问题

每个选中的报警事件，报告至少要分别呈现：

1. 当时发生了什么：功能、侧别、雷达、事件 ID、报警时间/算法帧、目标 ID/index、自车和目标的
   实际字段，以及各字段的 observed/derived/not_available 状态；
2. 代码为什么可能触发：从当前 source index 读取真实条件、参数、调用链和输出信号，对每个条件
   给出满足、未满足、无法求值或不支持的状态，并列出代入的实际值和源码位置；
3. 还缺什么：运行时临时变量、精确 CAN Tx 上升沿、ROI/目标多边形或其他缺失证据，以及下一步
   public runtime/GDB/人工确认动作。

条件求值是证据投影，不是固定功能规则。只有表达式中所有操作数均能从同一选中帧、当前代码
参数或显式运行时 artifact 获得时，才允许输出 `satisfied`/`not_satisfied`；否则输出
`not_evaluable`/`unsupported`，不能把缺值当成条件不成立。

### 5.0.2 报警时间线和结论等级

每个详细事件必须把以下来源分层呈现，而不是合成一条“报警帧”：

| 来源 | 能证明什么 | 不能证明什么 |
|---|---|---|
| `recorded_raw` | 原始录制中某报警位/功能区间存在 | 当前代码回放是否复现、CAN Tx 是否同帧 |
| `replay_algorithm` | arbe/仿真算法输出的功能和帧 | 录制 raw 是否一致、最终 CAN 是否发送 |
| `runtime_with_frame` | 公共 runtime topic 的算法帧和字段 | 没有 stamped object/callback 时对象一定同帧 |
| `gdb_observation` | 当前 binary/source 下停点的局部变量、栈和表达式 | 无扰动实车真值、其他未采集变量 |
| `can_tx_observation` | 对应 CAN signal 的实际上升沿和帧绑定 | 算法内部哪条条件导致它，除非同时有代码链 |

统一投影契约为 `alert-timeline.v1`。只有两侧均为 observed exact frame 时，比较结果才允许
为 `same/different`；时间对齐、publication order 或 nearest-LGU 只能是 derived，结果为
`not_comparable`。未提供的层必须显示 `not_available/not_evaluated`。

报告结论分为 `facts_only`、`supported_hypothesis`、`confirmed`、`blocked`。`report.status=ready`
只代表 HTML/JSON 投影生成成功，不代表“正报/误报”或“根因已确认”。`confirmed` 还必须经过
data/source/binary identity、关键条件/runtime/CAN 证据、替代假设削弱和人工确认发布门。

报告还必须提供 `diagnostic_narrative` 和 `should_alert`：文字逐条说明真实代码条件的源码位置、
代入值、求值结果或缺失运行时量；`yes_observed` 只表示精确 CAN Tx 上升沿已观测，
`supported_yes` 只表示算法输出/条件层支持，`indeterminate` 表示证据不足。任何一种状态都
必须保留对应 evidence refs，不能由 AI 单独生成。

### 5.1 每次 run 的目录

建议产物布局：

~~~text
run_<run_id>/
  run_manifest.json
  intake.normalized.json
  environment_probe.json
  source_context.json
  source_schema.json
  data_inventory.json
  feature_catalog.json
  parameter_catalog.json
  ledger/
    analysis-run.json
    steps.jsonl
    claims.jsonl
    hypotheses.json
    experiments.jsonl
    user-decisions.jsonl
  code_graph/
  static/
    events.json
    frame_index.json
    target_candidates.json
    geometry_derived.json
    breakpoints.vscode.json
    breakpoints.gdb
    diagnosis_bundle.json
    viewer-model.json
    report.html
  runtime/
    runtime-debug-plan.json
    runtime-trace.jsonl
    gdb/
      transcript.txt
      stops.jsonl
      backtraces.jsonl
    bridge/
      snapshots.jsonl
    replay/
      commands.jsonl
      acknowledgements.jsonl
      process_inventory.json
  merge/
    evidence_overlay.json
    report_runtime.html
  handoff.md
~~~

### 5.2 单条数据的 HTML

页面必须做到“场景优先、渐进展开”，默认展示：

- 完整数据名称和来源；
- 本条数据的功能事件总览；
- 每个事件的功能、侧别、radar_id、radar_pos、首帧/末帧；
- 当前选择帧的自车和目标场景；
- 真实变量名、值、单位、source；
- geometry 状态和缺口；
- 可复制的 VSCode 条件断点；
- static/runtime/derived 状态标识。
- `recorded_raw`/`replay_algorithm`/`runtime_with_frame`/`gdb_observation`/`can_tx_observation`
  分层报警时间线、播放帧 map 和同帧报警信号。

交互要求：

- 左侧数据列表与报警事件列表为父子层级，各自独立滚动；
- 中间场景支持缩放、平移和 reset；
- 点击自车显示/隐藏自车属性；
- 点击目标显示/隐藏目标属性；
- 右侧属性面板内部滚动，不改变主图区滚动位置；
- 事件切换自动切换目标/ego 选中状态；
- 数据切换使用完整 bag 名称和完整路径；
- 不默认把所有字段堆在页面上，提供按 source、feature、frame、runtime 状态筛选；
- 几何图只绘制当前功能有效 ROI；未知或缺少 runtime ROI 时显示状态，不绘制伪造区域；
- 视频/截图如果没有同 frame 证据，显示时间近似和差异，不声称同帧。

### 5.3 Analysis Trail 与 Live Workbench

页面必须把中间过程作为一级视图：

- Analysis Trail：每个 step 的输入、工具、耗时、发现、缺口和下一步；
- Claim cards：`observed/derived/inferred/contradicted/not_available`，可展开 evidence ref；
- Hypothesis Board：data/replay/perception/tracking/situation/function/config/output/integration
  候选及其支持、反证、待采证据和状态；
- DebugExperiment：问题、方法、断点/watch、期望区分、结果和扰动；
- 用户操作：接受、质疑、标记无关、选择实验、粘贴人工 debug 结果。

Live Workbench 负责运行中更新，Snapshot HTML 负责冻结、分享和归档；两者消费相同的
Analysis Ledger/Viewer Model，不维护两套分析逻辑。工程推理展示为
`Claim + Evidence + Assumption + Gap + NextExperiment`，不输出不可核验的模型原始思维链。

### 5.4 批量索引

批量 index 至少显示：

- 数据完整名、相对路径和 hash；
- source context 指纹；
- 状态 ready/blocked/unsupported/conflict；
- 功能和 event 数量；
- runtime 是否执行；
- 证据缺口；
- HTML、JSON、trace 的链接；
- 可按功能、侧别、失败态、版本和是否有 runtime 筛选。

### 5.5 三个用户交付出口（本轮产品化目标）

本平台不是把三套互相独立的程序交给用户，而是同一个 `AnalysisRun` 的三个投影：

| 出口 | 用户给出的业务目标 | Pi 的编排动作 | 用户拿到的结果 |
|---|---|---|---|
| 批量预检查 | “分析这个文件夹里的数据” | 建立上下文 → 调用 `cr60-precheck` → 记录批量 step | batch index、每条数据的 JSON/HTML、事件清单、缺口和后续入口 |
| 详细诊断报告 | “分析这次报警为什么发生/是不是误报” | 选事件 → 查询事件证据 → 查当前代码链 → 优先公共 runtime → 必要时 GDB → 调用 `diagnosis-panel` → 生成 `diagnosis-report` | 报警时刻的 ego/target/索引/ROI/参数、真实代码链路、断点、证据分层、候选根因和下一实验 |
| 对话式分析 | “只看 FCTB 报警时的目标速度/继续查这个变量” | 复用同一 `AnalysisRun`/artifact，上下文感知地调用 `evidence-query`、`code-context-read`、`event-code-path`、信号/runtime 工具 | 简洁回答 + 证据引用 + 新增 AnalysisStep；不重新扫全仓、不丢失前面结论 |

三者的边界是：批量预检查只做低成本、确定性事实整理；详细报告负责把一个事件的事实、当前代码和
诊断解释汇总；对话式分析不重新定义数据真值，而是按用户意图从已有 artifact 中切片或继续采证。
`diagnosis-report` 是报告投影能力，不是另一套业务诊断器；`evidence-query` 是 artifact 查询能力，
不替代 `data-explore` 的 FrameStore 数值探针。

每个出口都必须返回 `artifact_refs` 和 `analysis_run_ref`。因此用户可以从批量 index 进入一条数据，
从数据进入某次报警，再从报警进入代码/断点或在 Pi 中继续追问；任何阶段失败都保留已经完成的材料。

### 5.5 runtime trace

runtime trace 每条样本至少包含：

~~~json
{
  "run_id": "…",
  "data_id": "…",
  "sequence": 12,
  "wall_time": "…",
  "bag_time": "…",
  "ros_time": "…",
  "frame_domains": {
    "lgu_frame_id": 47877,
    "algorithm_frame_id": 47877,
    "player_event_index": 1142
  },
  "radar": {
    "radar_id": 2,
    "radar_pos": "FrontRight"
  },
  "scope": {
    "function": "FrontCrossTrafficAlertAndBrake",
    "file": "adasFunc.c",
    "line": 9889,
    "expression": "objInfo->trcOutData[i]"
  },
  "object": {
    "raw_sgu_index": 3,
    "algorithm_object_index": 1,
    "objID": 44
  },
  "can_output": {
    "signal_token": "<resolved from active source>",
    "mapping_function": "<resolved from active source>",
    "observed": false,
    "observation_status": "can_tx_unobserved"
  },
  "values": [],
  "backtrace": [],
  "source_context": {},
  "binary_context": {},
  "disturbance": {}
}
~~~

这是统一外层 schema；values 的真实字段名和类型从当前源码/GDB/bridge 返回，不能由平台预先写死。

## 6. 核心功能需求

优先级：P0 必须首版可用；P1 需要真实 runtime 链路；P2 是后续增强。

### FR-01 输入接入与身份

P0：

- 支持单 bag、目录递归、上游 handoff；
- 为每条数据生成稳定 data_id；
- 保留完整原始路径、文件名、大小、mtime、hash；
- 把数据与 source/runtime/semantic context 绑定；
- 缺失输入输出结构化状态。

验收：

- 同一数据在不同输出目录生成相同 data_id；
- 文件名不被截断；
- 两条同名但不同路径数据不能覆盖。

### FR-02 环境探针和 source context

P0：

- 读取 outer arbe、algo_source、COEM、配置、branch、commit、dirty；
- 记录探针命令、返回码、输出摘要和时间；
- 检查 source/binary/launch configuration 的一致性；
- 不自动 checkout/fetch/pull。

P1：

- 识别可用 binary、debug symbol、source path mapping；
- 识别 ROS、GDB、launch、workspace 和权限能力；
- 为每类环境生成 adapter capability。

验收：

- 版本冲突时阻断 runtime；
- dirty workspace 不被工具静默覆盖；
- 新服务器路径不需要修改核心代码。

### FR-03 当前代码实时分析

P0：

- 从当前 source context 生成 feature catalog；
- 识别公开输入输出结构、功能函数、参数变量、全局状态和调用链；
- 识别源代码中的实际表达式、编译宏和条件编译；
- 生成 source schema 和 source fingerprint。

P1：

- 生成围绕事件的最小调用链；
- 生成变量消费关系和参数依赖；
- 支持 C/C++ 局部作用域可见性分析。

验收：

- 切换子仓 commit 后旧 schema 不进入当前 Pi prompt；
- 新增/删除功能不要求修改核心枚举；
- 解析不到的结构必须显示缺口。

### FR-04 数据 topic 和信号解码

P0：

- 列出 bag topic、消息类型、消息数量、时间范围；
- 对功能信号、LGU、ego、XCP/CAN、camera、objectlist 做可用性审计；
- 保存原始 field path、消息 index、bag time、message stamp；
- 不把近似时间匹配当作同 frame。

P1：

- 支持可插拔 bag/BLF/MF4/provider；
- 支持从当前消息定义动态生成字段目录；
- 支持视频时间基准和帧差标识。

### FR-05 全功能和全事件发现

P0：

- 不只检测 FCTA/FCTB；
- 以当前 source/schema 和实际输出信号发现 BSD、LCA、DOW、RCW、RCTA、RCTB、FCTA、FCTB 及新功能；
- 同一数据内多个功能报警全部独立记录；
- 同一功能多个时间区间全部独立记录；
- 默认采用上升沿/持续区间模型，但业务定义可配置；
- 记录 raw signal、算法输出、UI/HMI/标注的差异。

P1：

- 支持功能插件注册自己的 event detector；
- 支持项目自定义状态机和多级 warning 状态；
- 支持对报警、解除、保持、抑制、de-warning 区间分别建模。

### FR-06 frame 和首帧定位

P0：

- 同时保留 bag time、message header time、LGU frameID、algorithm frame、player event index；
- 给出映射和差异；
- 报警第一帧注明定义和证据来源；
- 对 warning_status_with_frame、raw warning、algorithm output 分别建 source；
- 无法确定首帧时输出候选和原因。

P1：

- 支持跨 radar 的场景时间线；
- 支持 replay event 与算法完成 ACK 的闭环记录；
- 支持回放 seek/reset/loop 对事件的边界隔离。

### FR-07 目标和索引解析

P0：

- 同时记录 radar_id、radar_pos、raw SGU index、algorithm object index、objID、objUnqID；
- 发现 HIL 路径中 objTrans[i] 到 trcOutData[k] 的压缩映射；
- 每个事件提供目标候选及依据；
- 不能用时间近似 objectlist 自动替代 runtime object；
- ID 重排、复用、丢失时报告 identity conflict。
- 静态事件窗口内支持逐 `frameID` 查看自车、全部目标和 warning 状态；

P1：

- 跨连续帧跟踪目标身份；
- 输出目标生命周期、lost、lifeCycle、historyMovDist 等实际字段；
- 根据事件函数作用域生成可命中的 i/k 条件。

### FR-08 参数和代码条件

P0：

- 参数来自当前代码、COEM、车型配置、YAML/Excel/NvM/ROS/runtime 的实际来源；
- 区分静态参数、动态计算参数和 runtime state；
- 记录参数使用功能和消费函数；
- 计算动态参数时列出依赖变量和公式；
- 未能读取的参数标记 runtime_probe_required。

P1：

- 支持每帧 parameter snapshot；
- 支持参数 what-if 但不直接修改生产代码；
- 支持敏感性排序和验证计划。

### FR-09 几何、坐标和 ROI

P0：

- 探测 ego 原点、长宽、保险杠/后轴偏移、radar 安装位姿、轴向、角度单位；
- 目标优先使用算法 runtime objPoly 四角；
- ROI 优先使用算法 runtime adasRoi；
- 仅在 source、frame、coordinate、binary 证据一致时执行 collision/intersection；
- source-derived polygon 必须明显标识；
- geometry 缺口时显示 not_evaluated，不输出 PASS/FAIL。

P1：

- 支持不同功能不同 ROI 类型；
- 支持弧形、分段、polygonLargerStruct 和动态 ROI；
- 输出 polygon corner、yaw orientation、coordinate transform 和误差来源；
- 支持几何结果与源函数行号互链。

### FR-10 HTML 报告

P0：

- 场景优先、渐进披露、控件内滚动；
- 左侧数据/事件树独立滚动；
- 中央图可缩放/平移；
- 事件窗口内支持按实际 `frameID` 拖动/键盘切换，并显示当前帧与窗口总帧数；
- 显示 warm-up、selected analysis frame、算法输出候选帧和 CAN Tx rising-edge（若已观测）的
  不同语义；不把它们合并成一个首帧。
- ego/target 属性点击显示和隐藏；
- 属性字段保留真实代码变量名；
- 断点条件可以直接复制；
- 显示 evidence status 和 source refs。

P1：

- 连续帧时间轴和变量曲线；
- runtime/static 对比；
- 调用链和条件树联动；
- 截图/视频按时间差标注；
- 导出工程师 handoff；
- 提供与 arbe `enableobjectlist Disp` 对齐的 Radar1/2/3/4 目标属性检查视图；
- 显示 `Source=RAW_SGU/ALGO`、`ID`、`objID` 和全部动态目标字段，支持字段筛选和控件内滚动；
- 从目标字段直接跳转到 event-code-path、断点和下一次 DebugExperiment。

### FR-11 VSCode/GDB 辅助

P0：

- 根据实际 active source 生成函数、文件、行号、表达式和 frame window；
- 输出可复制的条件断点，例如：

      frame_counter >= 47872 && frame_counter <= 47877 && sObj->objID == 44

- 只有在目标作用域中确实存在 i/sObj 时，才生成：

      i == <algorithm_object_index>

- 同时显示断点所在代码链路、变量取值清单和预期命中原因；
- 对用户定义的 CAN 首帧，优先把 `RteComMapping_TxRunnable_FuncSignal`、对应 `RteComMapping_WriteSignal` 和实际 signal token 纳入断点链路；
- 断点不可用时说明是 scope、symbol、优化、source mapping 还是 target 问题。

P1：

- 生成人工辅助的 launch/attach handoff，作为 headless 失败时的兜底；
- 支持 headless GDB MI/CLI，并作为 SGU runtime 的首选路径；
- capture backtrace、locals、表达式、静态变量和 stop reason；
- 支持断点命中次数、超时、detach 和 teardown 审计。

### FR-12 replay 控制

P0：

- 复用 arbe 现有播放器或经过验证的 adapter；
- 记录 play mode、play rate、当前事件、radar 和 ACK；
- 不把 PlaySingleFrame ACK 当成 load/play/seek API；
- 单事件模式和 Scene Mode 语义分开。

P1：

- SGU mode 使用 HILMODEL/注入前置校验，按实际 `frameID` 默认预热 3–5 帧，不继承 point-cloud 的 150–200 帧规则；
- point-cloud mode 按 profile 记录 warm-up 帧数、起止 frame、速率和 reset；
- 任何后台自动 replay 要有可停止和超时机制。

### FR-13 Pi 编排

P0：

- 能从 Pi 发现并调用 static precheck、source learn、code analyze、report；
- 每个工具输入输出为结构化 artifact；
- Pi 不直接拼任意远程 shell；
- AI 解释引用 evidence refs。
- 每次分析创建/恢复 `AnalysisRun`，每个阶段落 `AnalysisStep`、Claim、Gap、Conflict 和
  next action；最终 HTML 是其投影，不是唯一产物。

P1：

- Pi 根据用户目标选择 SGU/point-cloud strategy；
- 先执行 read-only preflight，再请求需要副作用的步骤；
- 任务失败时保留中间 artifact 并支持从 checkpoint 恢复。
- 支持 capability pack 根据当前阶段、项目能力和 freshness 生成工具短名单；完整原子
  registry 仍保留用于能力发现和测试。

### FR-14 对比、调参和验证

P2：

- 同一数据、同一 source context 下比较两个 binary/commit；
- 输出 warning、变量、ROI、performance 的差异；
- 给出候选调参变量和影响链；
- 通过 sim-verify 重新运行验证；
- 代码修改需另走 code-fix/PR 流程，不在诊断任务中隐式修改。

### FR-15 arbe 公共逐帧目标检查

P0：

- 提供与 arbe `View → enableobjectlist Disp` 同等的信息能力，但不抓取 GUI 像素；
- 复用当前 source/runtime schema 动态解析 `/wf/objectlist_1..4` 和 `wfSObj` 字段；
- 支持按 radar1/2/3/4、event、frame 选择并展示目标属性；
- 至少覆盖当前 `wfSObj` 中的 `ID`、`objID`、位置、尺寸、yaw、速度、RCS、TTC、DDCI、
  生命周期/年龄和 BSD/LCA/DOW/RCW/RCTA/RCTB/FCTA/FCTB object flag；
- 同时获取同一回放上下文的 ego、frame、warning 和 radar info；
- 对 objectlist 无算法 frameID 的情况显示 `callback_correlated`、`time_aligned_partial`
  或 `unbound`，不能默认写成同帧事实。

P1：

- 复用 arbe BagReader 的 event/scene、主雷达、逐帧跳转和 ACK 语义；
- 通过 `runtime_snapshot_with_frame` bridge 提供 frame/radar/ego/object/index/warning/ROI
  的精确快照；
- 支持目标属性时间序列、目标身份变化、RAW_SGU/ALGO 来源切换和与代码链路联动。

验收：用户可以从报警事件进入指定 frame，看到与 arbe object list 语义一致的四个角雷达
目标属性；每个字段显示真实 source token、来源和关联质量；不能把近时间目标当成同帧目标。

### FR-16 一次性代码上下文准备与快速查询

P0：

- 对当前 `project/variant/source fingerprint` 一次性生成代码能力上下文；
- 提供功能目录、输入/输出信号、调用链、参数/ROI/坐标、结构体/message、条件和断点索引；
- 数据分析时优先检索该上下文的事件切片，不要求 AI 每次从全仓搜索；
- 任何代码上下文结果携带 source path、commit/hash、行号、符号和生成时间；
- source fingerprint 变化时增量刷新并禁止旧上下文进入当前 Pi prompt；
- 未解析或不支持的函数/表达式进入 gap，不用近似文本补齐。

P1：

- 生成 `event-code-path.v1`，把 output→feature→situation→target→input 五层链路绑定到
  事件；
- 支持按问题目标检索最小相关代码包、参数消费点和 GDB watch group；
- 支持不同 Gen6 项目的 source adapter/FeaturePlugin，不增加核心枚举。

验收：同一 source fingerprint 的多条数据复用代码上下文，不重复全仓扫描；用户能从事件
直接跳到真实函数/变量/断点，并看到哪些条件已由数据验证、哪些需要 runtime。

## 7. 功能事件模型

### 7.1 event 必备字段

~~~text
event_id
data_id
feature_id
feature_display_name
side
radar_id
radar_pos
alarm_signal_ref
alarm_signal_value
event_start
event_end
first_frame_definition
frame_domains
algorithm_output_frame
can_tx_frame
selected_first_alarm_frame
can_tx_observation_status
target_candidates
selected_target
selected_index_mapping
ego_snapshot_ref
parameter_snapshot_ref
geometry_ref
condition_refs
call_chain_refs
breakpoint_refs
evidence_status
confidence
conflicts
next_action
~~~

### 7.2 event 的拆分规则

默认规则：

1. 对同一功能、同一 side、同一 radar 的有效输出，按激活到解除形成区间。
2. 激活状态再次从 0 变为非零，形成新的 event。
3. 不同 warning level 的变化记录为 event transition，不强行拆成不同功能。
4. 不同功能即使同一 frame 同一目标，也生成不同 event，并共享 frame/object refs。
5. 同一功能由不同 radar 输出时保留不同 radar event，另建 cross-radar correlation。
6. 只有时间接近、没有 frame/ID 证据的记录标记 frame_mismatch 或 identity_uncertain。

拆分规则必须由项目 profile 覆盖，事件 detector 版本随 bundle 保存。

### 7.3 首帧三种口径

报告必须同时允许：

- output first frame：指定算法输出位第一次为非零；
- UI/HMI first frame：显示或消费侧第一次变化；
- condition first frame：功能内部满足触发条件的第一帧。

默认不得用 UI 时间代替算法 frame。若只能得到一种，页面必须显示口径和缺失的其他口径。

### 7.4 报警来源优先级

当前 arbe 仿真中，算法侧同时存在两类输出：

- `/corner_radar/warning_status_with_frame`：包含 `radar_id`、算法 `frame_counter` 和 15 路 warning，是当前 visualization host 可观测的算法输出代理；只有确认 CAN Tx 映射链实际执行时，才可作为 CAN 首帧的关联证据；
- `/corner_radar/warning_status`：包含 `radar_id` 和 15 路 warning，但没有显式 frame，需要结合当前 LGU frame 映射；
- `/corner_radar/warning_status_raw`：由 `common_can_warning_publisher` 从真实 CAN/DBC 解码得到，是 ECU/CAN 侧证据，不等同于 `PostProcessMainTI` 内部算法输出。

用户定义的 selected first alarm frame 是“算法内部向 CAN 输出报警信号的那一帧”。实现上优先在当前 runtime 中观测 `RteComMapping_TxRunnable_FuncSignal`、宏展开后的 `RteLite_Write_<actual_signal_token>` 和最终 `Com_SendSignal` 的对应信号，在同一 signal 的 0→非零上升沿取 frame。`PEROutput.adasWarning` 和 `warning_status_with_frame.data[1]` 是更前级的算法输出 frame，必须单独保存。

当前 visualization host 如果只执行 `PostProcessMainTI` 并发布 `warning_status_with_frame`，没有执行完整 ASW/CAN Tx 调度，则使用算法输出上升沿作为可用代理，但标记 `can_tx_unobserved`，不能在报告中称为最终 CAN 首帧。如果没有 with-frame topic，才降级为 `warning_status` 加 frame 映射并标记 `derived_runtime_mapping`；只有 raw CAN 时，只生成 CAN-side event。

如果当前源码中只有 `RteComMapping_WriteSignal(signal_name)` 宏，断点生成器必须先解析为真实的 `RteLite_Write_<signal_name>` 符号；若符号不存在、被内联或未执行，则记录 `can_tx_observation_status`，不能生成看似可复制但不会命中的断点。

算法侧和 CAN 侧 event 必须分开保存，再建立 correlation，不能将两条来源混写成一个报警事实。

## 8. 对象、索引和断点规则

### 8.1 映射模型

统一保存以下关系：

~~~text
raw message slot
  → raw SGU object index i
  → algorithm object index k
  → objInfo->trcOutData[k]
  → objID / objUnqID
  → function loop index / local sObj scope
~~~

工具禁止把 i、k、objID 互相替换。

### 8.2 断点生成策略

断点生成器按以下顺序工作：

1. 选择 feature event；
2. 获取 event 的 frame domain；
3. 从 active code graph 找到消费目标的函数和循环；
4. 验证表达式中的变量在该源码 scope 可见；
5. 用实际 frame、objID、i/k 生成条件；
6. 运行 syntax/source mapping preflight；
7. 输出 VSCode 条件、GDB 条件和不可用原因。

示例仅用于说明格式：

~~~cpp
frame_counter >= 47872 && frame_counter <= 47877 && sObj->objID == 44
~~~

如果该循环实际是 objInfo->trcOutData[i]，工具才可以输出：

~~~cpp
frame_counter == 47877 && i == 1 && objInfo->trcOutData[i].objID == 44
~~~

如果 frame_counter 在该函数不可见，必须切换到真正可见的函数参数/全局变量，或标记 breakpoint_expression_unavailable。

## 9. 几何和参数产品规则

### 9.1 几何证据优先级

~~~text
同一 frame 的 runtime objPoly/adasRoi
  > 同一 frame 的 runtime 输入 + active source 计算
  > active source + bag 输入的 derived polygon/ROI
  > profile 静态默认值
  > 不可用
~~~

最后一项不能作为正式碰撞判断依据。

### 9.2 自车矩形

自车矩形必须明确：

- reference origin；
- front/rear/left/right 方向；
- vehicle_length、vehicle_width；
- bumper/axle offset；
- radar-to-ego transform；
- 当前功能使用的是 ego frame、radar frame 还是其他 frame。

报告同时显示“显示矩形”和“算法内部矩形”是否同源；不一致时显示 coordinate conflict。

### 9.3 目标矩形

目标矩形必须明确：

- center field；
- length、width、height；
- yawAng 轴向和单位；
- reference point；
- 四角顺序；
- 是否经过 FOV/坐标转换；
- runtime 是否直接提供 objPoly。

绘图箭头表示目标行驶/朝向，不能只画无方向框。

### 9.4 ROI 和动态参数

ROI 记录：

~~~text
feature
roi_name
roi_type
points
coordinate_frame
source_function
source_line
static_inputs
dynamic_inputs
runtime_snapshot
evaluation_status
~~~

动态参数必须记录依赖，例如车速、yaw rate、curvature、bumper2RearAxle_dist、vehicle_width、calibration compensation 等；页面不能只显示最终数值而隐藏公式和消费函数。

## 10. AI、Pi 与确定性能力的职责

### 10.1 确定性层

下列行为必须由确定性代码完成：

- bag/BLF/MF4 解码；
- frame、time、topic、field path 记录；
- source/binary/data fingerprint；
- 代码 AST/index/call graph；
- 参数来源和静态表达式；
- event rising edge 和区间；
- object/index mapping；
- geometry 计算；
- GDB command/transcript capture；
- bundle schema validation；
- freshness/mismatch gate。

### 10.2 AI 层

Pi/AI 可以：

- 理解用户问题并选择能力；
- 根据当前 code graph 规划检索；
- 把数据、代码、需求和历史案例组织起来；
- 解释变量和调用链；
- 对候选原因做 Top-N 排序；
- 生成下一步断点/probe/验证建议；
- 将工具结果整理为用户可读 handoff。
- 将每个阶段结果整理为结构化 Claim/Gap/Conflict/Hypothesis/DebugExperiment；
- 根据新证据支持、削弱或拒绝候选原因，并明确变化依据；
- 为用户 VSCode debug 解释“看见什么分别意味着什么”，并消费用户回填结果。

AI 不可以：

- 改写原始数据；
- 把不存在的字段补成真实值；
- 以固定参数替代当前代码参数；
- 在 freshness 不满足时使用旧知识；
- 绕过权限审批；
- 用概率语言掩盖 source/binary/frame/coordinate 冲突。
- 隐藏中间证据，只给一个无法复核的最终根因或代码方案；
- 把 objectlist 的发布时刻或近时间对象直接当成算法同帧身份。

### 10.3 Pi 工具调用最小契约

每个能力必须返回：

~~~json
{
  "status": "ok | blocked | partial | failed",
  "artifact_refs": [],
  "evidence_refs": [],
  "missing_inputs": [],
  "conflicts": [],
  "next_actions": [],
  "metrics": {}
}
~~~

Pi 的 prompt 只消费通过 variant/source freshness 门禁的知识和本次 run artifact。

### 10.4 Pi 工具发现与 capability pack

底层能力继续保持原子化，但 Pi 每个 AnalysisStep 只加载当前阶段的工具短名单和 artifact
摘要。建议 pack：`intake`、`static`、`code`、`runtime`、`report`、`maintenance`。
完整 registry 用于发现和测试，不要求模型在每次规划时同时比较全部 Pi 原子工具；当前
目录规模变化时由 capability pack 动态生成阶段短名单。

### 10.5 根因候选和实验循环

AI 根因定位必须是循环，而不是单次分类：

```text
evidence → hypothesis candidates → minimum-cost experiment
         → new evidence → rank/status update → user decision
```

候选分类包括 data、replay、perception、tracking、situation、function/FCT、config/parameter、
output/CAN 和 integration/UI。分类只决定下一步调查方向；只有关键链路证据闭环、主要替代
假设被削弱/排除并经用户确认后，才能标记根因确认。

## 11. arbe 集成产品边界

### 11.1 复用原则

根据实际服务器调研，arbe 现有能力分为：

| 能力 | 产品定位 |
|---|---|
| BagReader 时间线、辅助匹配、节拍、ACK 等待 | arbe replay adapter 的复用实现 |
| MyRvizPlugin ROS 发布和完成服务 | 现有运行时 endpoint，短期复用 |
| wfAutosarData、PERInfoOutStruct、objOutDataStruct、adasROIStruct | 动态 schema 的事实来源 |
| arbe_visualization_engine | runtime host，供 launch/attach/GDB 使用 |
| debugOutput.c CSV | 可选离线 collector，不是 runtime 全量真值 |
| Qt/RViz UI | 不作为统一平台 API |
| PlaySingleFrame.srv | 只复用处理完成语义 |
| start/launch/config/CUDA 流程 | 通过 workspace/build adapter 复用 |

当前源码进一步确认，arbe 已经逐帧公开了三组高价值信息：

- `/corner_radar/warning_status_with_frame`：radar + `frame_counter` + warning；
- `/corner_radar/radar_info`：自车速度、yaw rate、检测数、frame、周期等；
- `/wf/objectlist_<radar>`：目标位置、尺寸、yaw、速度、TTC/DDCI 和功能 object flag。

GUI Object Table 已区分 `RAW_SGU` 和 `ALGO`，说明“输入目标→算法目标→功能输出”的逐层
展示方法应被 Workbench 借鉴。但当前 objectlist 没有算法 `frameID`，header stamp 使用
发布时 `ros::Time::now()`；因此它适合公共 runtime 观察，不足以单独证明与 warning 的
绝对同帧关系。需要时通过 callback 同步采集或可选 `runtime_snapshot_with_frame` bridge
补强，GDB 只采集局部变量和调用栈。

### 11.2 不直接复制的内容

禁止：

- 将 arbe C/C++ 算法源码复制到 radarAnalyze；
- 在 Python 中复制固定 C struct；
- 将固定 15 路 warning 映射上升为全平台规则；
- 把 GUI widget 当成 load/play/seek RPC；
- 让 Pi 自己拼接任意 ssh/gdb/roslaunch/pkill；
- 用现有 CSV 补全未采集的局部 runtime 变量。

### 11.3 必要的 arbe feature branch

只有以下情况才允许创建用户确认的 arbe feature branch：

- 现有播放器不能提供 headless load/play/seek/stop；
- 需要在 PostProcessMainTI 边界发布统一 runtime snapshot；
- 需要稳定暴露 raw SGU index 到 algorithm index；
- 需要可配置的 runtime trace sink；
- 需要与默认生产行为可编译隔离和一键回退。

feature bridge 必须满足：

- 独立编译开关；
- 默认关闭或不改变原行为；
- 不改变算法接口语义；
- 输出 source/binary/config fingerprint；
- schema version；
- 可配置采样范围和字段白名单；
- 超时、flush、关闭和异常处理；
- 失败时可回到原始 arbe。

## 12. GDB 产品要求

### 12.1 运行前置校验

必须检查：

- 目标进程/节点/可执行文件；
- PID 或 launch-under-GDB 方式；
- -g 和优化级别；
- source path mapping；
- source/binary commit/hash；
- ptrace/权限；
- ROS master、topic/service；
- replay strategy；
- 是否允许暂停和自动恢复；
- 目标 frame 和事件窗口。

### 12.2 当前 VSCode 默认入口和进程定位

用户提供的默认入口为：

~~~json
{
  "name": "ROS: Attach",
  "type": "ros",
  "request": "attach"
}
~~~

当前服务器 `.vscode/launch.json` 还包含：

~~~text
ROS: Launch
target: /home/hoz2wx/CR60LIGHT/cr60_light_arbe/src/arbe_phoenix_radar_driver-master/arbe_gui/launch/rviz-arbe.launch

runtime program:
${workspaceFolder}/devel/lib/arbe_phoenix_radar_driver/arbe_visualization_engine
processId: ${command:pickProcess}
~~~

实际运行时，`arbe_gui` 会启动多个命名空间下的同名算法节点，进程/节点形式类似：

~~~text
/radar1_visualization_engine/arbe_visualization_engine
/radar2_visualization_engine/arbe_visualization_engine
/radar3_visualization_engine/arbe_visualization_engine
/radar4_visualization_engine/arbe_visualization_engine
~~~

因此工具不能只按可执行文件名选择进程，必须同时校验 namespace、`Radar_ID`、`radar_pos`、启动参数和 binary path。HTML 中应给出用户可以复制的目标选择信息，并在 headless GDB 中使用同一映射。

当前 launch 配置中还存在一个针对单个样例的 `radar2 FCTA/FCTB id44` 断点配置。它只能作为“真实条件断点格式”的历史样例，不能作为全局默认；每次 run 必须根据当前代码、event、frame、目标和作用域重新生成。

### 12.3 采集分级

| 级别 | 内容 | 适用 |
|---|---|---|
| G0 | 生成 VSCode 条件断点和变量清单 | Sprint1/人工辅助 |
| G1 | GDB attach，命中后读取 frame/对象/输出/调用栈 | SGU MVP |
| G2 | 连续 GDB stop/tracepoint 或 bridge snapshot | runtime 增强 |
| G3 | point/filter/cluster/track/ADAS 连续链路和性能 | 后续 point-cloud |
| G4 | 性能调参、what-if、双版本对比 | 后续验证 |

### 12.4 时序扰动

GDB stop 会改变实时回放行为，产品必须记录：

~~~text
pause_duration
continue_time
replay_rate
missed_frames
queue_backlog
algorithm_ack_delay
reset_or_restart
~~~

runtime 结果必须带 disturbance 字段。不能声称“GDB 后结果就是无扰动实车真值”。

## 13. UI/HTML 产品规范

### 13.1 信息架构

~~~text
顶部：数据完整名 / run 状态 / source context / evidence level
左栏：数据列表
      └── 报警 event 列表
中栏：场景图 / 连续帧 / 时间轴 / 当前功能 ROI
右栏：选中对象属性 / ego 属性 / 参数 / 代码链路 / 断点
底部：frame domain、缺口、冲突、runtime 状态
~~~

### 13.2 视觉和交互规则

- 功能颜色只表示状态，不用颜色替代文字字段；
- runtime、bag、derived 使用稳定且可访问的状态标签；
- 选中目标显示方向箭头、四角标签和来源；
- ROI 的绘制名称来自当前代码变量或结构字段；
- 不同功能使用不同 ROI 图层，避免叠加造成误读；
- 所有长列表在容器内滚动；
- 事件列表和属性面板滚动互不影响主图；
- 支持键盘左右帧切换、event 跳转、reset view；
- 代码 token 保留原样，显示完整 file path 和 line；
- 复制按钮复制纯文本条件，不复制解释性前缀；
- 缺失值显示原因和建议动作。

详细诊断报告的默认视图必须“先文字解释、后证据展开”：`executive_summary` 直接描述功能/侧别/
radar/frame/objID、自车关键状态、目标关键状态和当前报警输出层；随后显示 `should_alert`、关键
条件的原始/代入表达式以及尚未确认的缺口。首屏只显示有限的相关条件和 runtime facts，完整
`condition-trace`、对象列表、连续帧和 GDB transcript 放入折叠区与 JSON artifact，不删除真实数据。
条件选择可以依据当前事件的功能提示优先相关代码，但候选条件不能自动拼成完整 AND 链，避免无
上下文的数值堆叠被误读成诊断结论。

## 14. 多项目、多服务器、多用户

### 14.1 Profile 模型

每次运行由 profile 组合：

~~~text
server profile
workspace profile
source profile
vehicle/COEM profile
replay profile
feature plugin profile
report profile
security policy
~~~

核心工具只消费接口，不读取固定路径。

### 14.2 隔离要求

- 每个 run 有独立 run_id 和 output root；
- 每个 variant 有独立 source_docs、codegraph、memory、snapshot；
- workspace 变更使用锁；
- process、ROS master、端口和临时目录隔离；
- 不把用户 A 的代码知识、参数和案例注入用户 B；
- 结果访问遵守服务器和数据权限；
- secret 不进入 manifest、prompt 和 HTML。

### 14.3 共享 workspace

若必须使用原始 workspace：

- 先读取 dirty 状态；
- 需要用户明确确认；
- 禁止并发切 branch；
- 编译/启动/attach 前后保存 fingerprint；
- 失败时只报告，不自动 reset/revert；
- 优先建议隔离副本。

## 15. 失败态和用户可见提示

| 失败态 | 例子 | 用户看到的动作 |
|---|---|---|
| blocked_missing_input | 缺车型、COEM、代码绑定 | 列出缺失字段和填写方式 |
| source_mismatch | branch/commit 不符 | 不能继续代码解释，建议确认版本 |
| binary_source_mismatch | binary 非当前 source | 不能生成 runtime 结论 |
| data_unsupported | bag 没有支持 topic | 列 topic 清单和可用替代 |
| frame_mismatch | warning 与 LGU 无同帧对应 | 展示时间差，不合并 |
| identity_uncertain | objID 重排/候选多个 | 输出候选，不生成唯一断点 |
| coordinate_contract_missing | 雷达坐标/原点未知 | 只展示原始值，geometry not evaluated |
| breakpoint_expression_unavailable | 变量不在 scope | 给出实际可见的替代表达式或人工位置 |
| optimized_out | GDB 变量被优化 | 建议 debug build/低优化/bridge |
| permission_blocked | ptrace/远程权限不足 | 不提权绕过，提示用户配置 |
| replay_timeout | 无 ACK/无新 frame | 保存 transcript，允许重试或手工 |
| disturbance_high | GDB 停顿过大/丢帧 | runtime 结果降级，建议 tracepoint/bridge |
| artifact_incomplete | 中途断开 | 保留 checkpoint，禁止标记 verified |

## 16. 安全和副作用策略

### 16.1 风险级别

| 级别 | 操作 | 默认 |
|---|---|---|
| R0 | 读文件、Git status/log、topic inventory、静态分析 | 自动允许 |
| R1 | 读取 binary/symbol/process/ROS 状态 | 自动允许或按 profile |
| R2 | 启动隔离 replay、生成临时目录 | 用户确认 |
| R3 | 编译、修改配置、启动 GUI/ROS、attach GDB | 明确确认 |
| R4 | 停止进程、修改原仓、切 branch、写算法代码 | 禁止默认自动 |

### 16.2 审计

所有 R2 以上动作记录：

~~~text
actor
run_id
server
workspace
command template id
normalized arguments
approval
start/end
exit code
stdout/stderr artifact
side effects
rollback status
~~~

不记录 secret 原文，不在最终 HTML 暴露凭据。

## 17. 性能、容量和可观测性

首版目标需通过真实数据测量后冻结，建议先记录而不是硬编码：

- 静态单 bag 预检查耗时；
- 单目录 N 条数据吞吐；
- bag 读取内存；
- HTML 产物大小；
- source schema/call graph 生成耗时；
- GDB 首次命中耗时；
- runtime trace 每帧开销；
- replay backlog 和 ACK 延迟；
- 并发 run 数；
- 磁盘回收和缓存命中率。

所有模块返回 metrics，批量 index 汇总 metrics。若 runtime 对时序影响超过 profile 阈值，自动降级为 partial/blocked。

## 18. 验收矩阵

### 18.1 数据类验收

| Case | 预期 |
|---|---|
| A SGU 单功能单次报警 | event、首帧、radar、objID、i/k、断点完整 |
| B SGU 多功能多次报警 | 所有功能和区间独立列出，不只 FCTA/FCTB |
| C point-cloud 报警 | warm-up 起点和 150–200 帧事实可追溯，不能套 SGU 策略 |
| D 无报警 | 无伪 event，报告显示无报警证据 |
| E topic 缺失 | blocked/partial，列出缺失和替代 |
| F frame 冲突 | 不合并近似消息，显示 frame_mismatch |
| G target 重排 | 不给唯一 i，输出候选和 identity uncertainty |

### 18.2 代码/runtime 验收

| Case | 预期 |
|---|---|
| H source commit 切换 | schema、参数、调用链、断点随 source 更新 |
| I no debug symbol | 静态报告可用，runtime 阻断且说明原因 |
| J SGU GDB | 命中真实函数，读取 frame/objID/i/输出/ROI/ego |
| K GDB optimized out | 标记 optimized_out，不伪造变量 |
| L source/binary mismatch | runtime 阻断 |
| M runtime overlay | 不覆盖静态 bundle，可比较差异 |
| N GDB disturbance | 保存停顿/丢帧/ACK 指标并降级结论 |

### 18.3 UI/交互验收

| Case | 预期 |
|---|---|
| O 批量数据切换 | 显示完整数据名，切换后属性、事件和图形不串数据 |
| P 属性展开 | ego/target 独立显示，属性面板内部滚动 |
| Q 场景图 | ego、target、yaw、ROI 和来源正确；缩放平移不影响侧栏 |
| R 断点复制 | 复制内容是可直接粘贴的真实表达式 |
| S runtime 缺口 | 页面明确标注 not available/runtime required |
| T 三出口连续使用 | 批量 index → 单事件详细报告 → Pi 业务追问共享同一 artifact/run；中断后可恢复，缺口不丢失 |

## 19. Sprint 规划

### Sprint 0：流程和契约冻结

目标：

- 回填真实用户流程确认表；
- 冻结 intake、evidence、event、frame、target、geometry、breakpoint 契约；
- 完成服务器和 workspace read-only preflight。

不做：

- 不改 arbe；
- 不后台 attach；
- 不自动切分支。

完成条件：

- Q-P0 问题闭环；
- 至少一条 SGU 和一条 point-cloud 验收数据确定；
- 文档、schema、决策记录一致。

### Sprint 1：确定性数据预检查

目标：

- 全功能、多事件、多 frame；
- 真实 source schema、参数、调用链；
- target/index 候选；
- geometry derived 明确标记；
- HTML、batch index、VSCode 断点 handoff。

完成条件：

- A/B/D/E/F/G/O/P/Q/R/S 通过；
- 输出可以直接指导人工 VSCode debug；
- 没有固定 FCTA/FCTB-only 逻辑。

### Sprint 2：SGU runtime debug MVP

目标：

- HILMODEL/SGU preflight；
- 复用 arbe replay adapter；
- GDB G0/G1；
- runtime ego、target、ADAS、ROI、函数局部变量；
- static/runtime overlay。

完成条件：

- J/K/L/M/N 通过；
- 至少一个真实 SGU case 从回放到 GDB 命中可复现；
- runtime trace 有完整 source/binary/data provenance。

### Sprint 3：arbe 可选 runtime bridge

目标：

- PostProcessMainTI boundary snapshot；
- raw SGU index 到 algorithm index 统一输出；
- 可配置 JSONL sink；
- headless replay control service；
- 保持默认 arbe 行为不变。

完成条件：

- bridge 开关、回退、schema、flush、异常测试通过；
- 外部 GDB 只补局部变量和调用栈。

### Sprint 4：point-cloud runtime

目标：

- 真实 warm-up profile；
- point/filter/cluster/track/ADAS 连续 trace；
- reset、丢帧、性能和时序扰动分析。

完成条件：

- C/N 通过；
- 不把 SGU 的目标注入结论推广到 perception；
- 能解释“目标没出现、目标出现但 situation 不成立、功能条件不成立”的证据链。

### Sprint 5：诊断解释和验证闭环

目标：

- Pi 跨数据/代码/需求/案例组织证据；
- perception/situation/function/config/replay 分类候选；
- 双版本对比、参数敏感性和 sim-verify；
- 人工确认反馈和知识 freshness。

完成条件：

- 不自动把候选原因标为最终根因；
- 每个建议都有验证步骤和复现条件；
- variant 隔离和 freshness gate 通过。

## 20. 成功指标

| 指标 | 首版目标 |
|---|---|
| 静态重复性 | 相同输入/source context 结果可重复 |
| 报告完整性 | ready 数据都有 JSON bundle、HTML 和索引 |
| 事件覆盖 | 多功能、多次报警不遗漏 |
| 断点有效性 | 生成的表达式与真实 scope/source mapping 一致 |
| 几何可信度 | 缺少同 frame runtime polygon/ROI 时不输出 PASS/FAIL |
| 版本安全 | source/binary mismatch 不进入 runtime 结论 |
| 失败可解释率 | 缺输入、权限、符号、frame、坐标、回放分别分类 |
| 复用率 | 前置数据准备/arbe build/player 能力通过 adapter 调用 |
| Pi 可扩展性 | 新模块注册后进入 catalog，无需改核心 orchestrator |
| 工程节省 | 以用户实际 baseline 测量人工定位时间下降，不先假设固定百分比 |
| 第一条有效线索 | 记录 Time to First Useful Clue，不等待最终报告才产生价值 |
| Debug-ready 时间 | 从输入到可复制断点、watch 和目标帧的时间 |
| 证据覆盖 | 关键代码条件有 observed/derived/runtime evidence 的比例 |
| 假设收敛 | 每次 DebugExperiment 支持/削弱/排除的候选数量 |
| 重复工作 | 同一 data/source fingerprint 的完整 bag 读取和代码学习次数 |
| 用户协同成本 | 用户被询问、手工操作和重复解释上下文的次数 |

## 21. 发布门禁

一个版本只有同时满足以下条件才能称为可投入使用：

1. P0 输入契约、source context、event/frame/target/geometry 规则通过用户评审；
2. 至少四类验收数据通过；
3. report 和机器 artifact 可互相校验；
4. 未验证字段和冲突在 UI 明确可见；
5. 没有隐含服务器、车型、COEM、branch 或功能默认；
6. 任意远程副作用都有审批、审计和停止/回退路径；
7. Pi 只消费新鲜且与当前 variant 匹配的知识；
8. runtime 结果能回到数据 frame、源码、binary、命令和 trace；
9. 文档、schema、AGENTS、handoff 和实现保持同步。

## 22. 待真实用户确认的 P0 决策

### 22.1 用户已确认的流程事实（2026-08-26）

| 事项 | 已确认内容 | 仍需工具探测的细节 |
|---|---|---|
| 数据准备顺序 | 先传数据到 Linux 服务器，再准备对应代码和 arbe | 数据的软件版本/车型身份具体存放在哪个 metadata、目录或上游字段 |
| 版本绑定 | 数据唯一对应一个软件版本、一个 COEM 和一个具体车型 | 版本到实际子仓 branch/tag 的映射规则和冲突处理 |
| 构建顺序 | 切子仓 → 更新 CUDA/配置 → 编译外层主仓 → `bash start` → 导入数据 | 每个车型实际 CUDA 文件、sheet 和配置来源 |
| 自动化 | 原则上全部自动，关键步骤一次性确认 | 需要把审批合并为 plan approval，不逐命令打断用户 |
| 材料不足 | 有材料先读，没有材料通过对话补齐，最终总会形成完整上下文 | 缺口字段、来源和用户确认记录 |
| SGU 预热 | `HILMODEL=2`；按代码 `frameID` 做 3–5 帧前置预热 | 具体版本是否存在例外，以及 3–5 的 profile 默认值 |
| point-cloud 预热 | 继续按代码运行周期和 `frameID` 规划 150–200 帧策略 | 各功能/车型/雷达是否需要不同值 |
| 报警第一帧 | 算法向 CAN 输出报警位的 0→非零上升沿 | CAN 信号字段与算法内部 warning 位的逐帧映射 |
| VSCode 入口 | 默认使用 `ROS: Attach`；启动后选择 `arbe_visualization_engine` 和 radar1/2/3/4 | namespace、PID、binary、source mapping 的自动校验 |
| runtime 方式 | 优先 headless GDB，获取中间变量并直接进入 HTML | GDB 权限、符号、优化级别和暂停容忍度 |
| 原 workspace | 允许操作；运行前重新编译，运行中默认不发生更新；不同版本之间内部接口可能变化 | 每次运行前重新 source learn、检查 adapter compatibility 和生成 GDB plan |

### 22.2 仍未冻结的实现细节

本 PRD 不替用户决定以下事项，问题已集中记录在 [真实用户流程确认表](technical/CR60_PI_UNIFIED_USER_WORKFLOW_QUESTIONNAIRE.md)：

- 从一条新数据到 VSCode attach 的真实操作顺序；
- SGU/HILMODEL=2 的版本适用范围和最小前置状态；
- point-cloud 150–200 帧的 frame domain、起点和速率；
- 报警第一帧及多次报警的业务定义；
- warning/function/side 的权威输出；
- frame_counter、frameID、player event index 的对应关系；
- objTrans[i]、trcOutData[k]、objID 的工程语义；
- ego 原点、雷达坐标、yaw 和 ROI 的真实契约；
- GDB 权限、进程 target、debug symbols 和暂停容忍度；
- 原始 workspace、隔离副本、服务器共享和多用户权限；
- 结果最终由工具给候选还是由用户确认正报/误报。

在这些 P0 决策未闭环前，产品可以继续做 read-only 调研和 Sprint1 contract 实现，但不能把 headless runtime 标记为 production-ready。

## 23. 变更控制

任何以下变更都必须先更新本 PRD，再更新调研、ADR、模块/软件设计和 Sprint：

- 新功能、功能名称、warning state 或 side 语义；
- 新消息字段、frame domain、对象身份规则；
- 新车型、COEM、参数来源或坐标契约；
- 新服务器控制方式、GDB 策略或远程权限；
- 新的 HTML 交互和 artifact schema；
- 新的 AI prompt、工具 catalog 或 freshness 策略；
- 自动化副作用范围扩大。
