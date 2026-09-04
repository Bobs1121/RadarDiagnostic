# CR60 Pi Unified Platform：DDD 需求与验收基线

版本：`ddd-requirements.v2.3`  
日期：2026-09-01  
状态：`baseline-under-review`（新增跨证据报警时间线、结论发布门和上下文记忆绑定）  
适用范围：`radarAnalyze`、`cr60-debug-harness`、`bosch-data-transfert`、`cr60light-arbe-build` 的统一 Pi 编排层

> 本文是本项目的需求开发基线，不是实现说明。实现、测试和 handoff 必须能够回链到本文的用户故事（US）、功能需求（FR）和验收场景（AC）。本文与 [CR60 Pi Unified PRD](../CR60_PI_UNIFIED_PRD.md) 配套：PRD 描述产品全貌，本文把产品需求收敛为可执行的 Document-driven development（DDD）条目。

## 1. 目标与非目标

### 1.1 产品目标

为毫米波雷达算法工程师提供一个以 Pi 为唯一用户入口的诊断 Harness：

```text
用户问题 / 数据目录 / 材料
        ↓
Pi 识别意图、补齐上下文、编排原子工具
        ↓
确定性数据/源码/ROS/GDB 工具产生证据
        ↓
Pi 汇总证据，生成下一步验证和解释
        ↓
per-data HTML + machine-readable bundle + handoff
```

核心输出不是“AI 猜一个根因”，而是让用户可以快速回答：

- 哪个功能、哪一侧、哪个目标、哪一次报警以及对应的 `frameID/frame_counter`；
- 自车、目标、ROI、坐标变换和参数来自哪里，哪些是 observed、derived、not_available；
- 哪个真实源码函数、变量、数组下标和条件可以直接用于 VSCode 条件断点；
- 公共 ROS 信号已经足够还是需要 runtime/GDB；
- 如果进入 GDB，暂停点、调用栈、局部变量和表达式值如何回到同一数据帧；
- 结论的证据缺口、冲突和下一步验证是什么。

### 1.2 明确非目标

- 不在 `radarAnalyze` 中复制 arbe 算法实现；arbe 仍是可视化/回放正式实现，平台通过 adapter、公共 ROS 通道和受控 GDB 复用能力。
- 不用固定 FCTA/FCTB 规则代替当前代码分析；功能、参数、ROI、变量和调用链必须绑定当前 source context。
- 不把路径名称、历史缓存或 AI 推断当作车型、COEM、branch、tag 或目标身份的权威证据。
- 不把没有同帧 runtime polygon/ROI 的几何图强行标为“进入/未进入”或“碰撞/不碰撞”。
- 不把 Pi 的自然语言回答作为原始数据真值；Pi 只能解释工具产出的证据。
- 不在未批准时切分支、改 CUDA、编译、启动 arbe、附加正式 PID 或影响其他用户的 ROS master。

## 2. 角色与真实工作任务

| 角色 | 主要任务 | 成功结果 |
|---|---|---|
| USR-ALG：雷达算法工程师 | 从报警数据定位功能/帧/目标/条件/变量 | 能直接复制真实源码 token 到 VSCode 断点并继续人工或自动 debug |
| USR-PER：感知/跟踪工程师 | 判断目标是否出现、目标属性/跟踪/目标身份是否可靠 | 看到同帧对象证据、索引映射和缺口，不把 perception 缺口误判为 FCT |
| USR-SIM：仿真工程师 | 准备数据、代码、车型、COEM、CUDA，运行 arbe 回放 | 关键副作用一次确认，过程可审计，可停止，可回退 |
| USR-OWNER：问题单/客户负责人 | 批量查看多条数据和多次报警 | 每条数据独立报告，汇总索引能定位失败原因和验证状态 |
| ADM：平台维护者 | 增加项目、车型、数据格式、功能 adapter 或 Pi tool | 新增能力进入 Pi catalog，不修改核心编排器，不串项目缓存 |

## 3. 领域对象与不变量

### 3.1 领域对象

| 对象 | 说明 | 权威来源 |
|---|---|---|
| `AnalysisIntake` | 数据、材料、车型、COEM、软件版本、服务器和源码绑定 | `cr60-analysis-intake.v1`；材料/用户确认 |
| `SourceContext` | outer arbe、algo_source、branch/tag/commit、COEM、CUDA、配置和 binary | 当前仓库探测、用户确认、构建产物 |
| `Case` | 一条 bag/数据目录及其 provenance | 数据文件 hash、ROS bag 元数据 |
| `AlarmEvent` | 某功能一次输出位 0→非零的事件，允许同一数据多功能/多次事件 | CAN/公共 ROS 输出与 frame domain |
| `FrameEvidence` | 事件帧及前后窗口的自车、目标、信号、代码映射 | bag/BLF/MF4/ROS/runtime |
| `RuntimeTrace` | GDB 或 runtime bridge 取得的同帧局部变量、表达式、栈和停点 | GDB transcript、binary/source fingerprint |
| `PiRunContext` | Pi 本次编排所使用的不可变上下文摘要和 artifact 引用 | `pi-orchestration-context.v1` |
| `EvidenceBundle` | 机器可读证据、来源、状态、冲突、缺口和报告入口 | 各版本 JSON schema |
| `AnalysisRun` | 一次可恢复的工程调查，不等同于一次模型对话 | `analysis-run.v1` |
| `AnalysisStep` | 一个阶段的工具调用、发现、缺口、耗时和下一步 | `analysis-step.v1` |
| `Claim` | 可被证据支持、反驳或标记缺失的工程陈述 | `claim.v1` |
| `Hypothesis` | 候选根因、支持/反证、所需证据和实验状态 | `hypothesis.v1` |
| `DebugExperiment` | 用最小成本区分候选原因的静态/runtime/人工实验 | `debug-experiment.v1` |
| `ProjectCapabilityManifest` | 当前 Gen6 项目/source 可用的数据、功能、代码、回放、runtime 和展示能力 | `project-capability-manifest.v1` |
| `AlertTimeline` | 将 raw/replay/public/GDB/CAN 报警事件按统一 FrameKey 投影并比较 | `alert-timeline.v1` |
| `DiagnosticConclusion` | 报告当前已确认事实、未证明事项、缺口和结论等级 | `diagnostic-report.v1.conclusion` |

### 3.2 不变量

1. `Case`、`SourceContext`、`RuntimeTrace` 的 provenance 必须保留；不允许用另一项目的缓存静默回退。
2. 同一数据可能含多个功能和多次事件；事件检测必须返回集合，不得只保留一个“主报警”。
3. “报警第一帧”默认以 **arbe 可视化工具报警灯对应的算法最终输出从 0 上升到非零的 `frameID`** 为诊断终点；CAN 只在用户明确要求时作为下游辅助证据。
4. `frameID` 是算法周期主域；`frame_counter`、player event index、bag message index 必须显式记录映射，不能混写。
5. 目标展示必须同时保留真实源 token（例如 `objInfo->trcOutData[i].objID`、`objPoly`、`yawAng`）；展示别名不能替代源码 token。
6. 没有同帧真实 polygon/ROI 时，几何结论只能是 `not_evaluated`；推导值必须标为 `derived` 并记录公式、输入和坐标系。
7. SGU/LGU 目标注入与 point-cloud 回放使用不同预热策略：默认 SGU/LGU `3–5` 帧（当前 profile 为 `5`），point-cloud `150–200` 帧；混合或无法识别时必须确认。
8. 任何远程/进程副作用必须先产生计划，获得批准后执行，并记录命令、目标、操作者、时间、返回码和清理结果。
9. Pi 是正式用户入口和总体编排器；确定性引擎、BaseTool、BaseModule 是被 Pi 调度的实现层。直接 CLI、AgentLoop、ReAct 仅是开发/离线/故障兜底入口。
10. 每个 AnalysisStep 必须留下可见的发现、证据、假设、缺口和下一步；最终报告不得隐藏
    或重新发明中间结论。
11. AI 的工程解释以 Claim/Evidence/Assumption/Gap/Experiment 表达，不存储或展示不可
    验证的模型原始思维链。
12. Pi 只能从当前 ProjectCapabilityManifest 和 freshness 通过的 capability pack 选择
    工具；不支持的项目/功能显式 unsupported。
13. 报告生成成功只表示 read model 可生成；`facts_only`、`supported_hypothesis`、`confirmed`
    和 `blocked` 必须独立表示证据成熟度，不能用 `report.status=ready` 代替诊断结论。
14. raw/replay/runtime/GDB/CAN 报警时间线只能通过 `AlertTimeline` 比较，不得从不同层的
    时间近邻、publish time 或 GUI 显示推导 exact same-frame。

## 4. 用户故事与验收标准

状态含义：

- `specified`：需求和验收已明确，尚无实现证据；
- `implemented`：代码和确定性测试已具备；
- `partially-verified`：已有隔离/局部/真实只读证据，但仍缺正式工作区或用户确认；
- `accepted`：满足本文发布门禁；
- `blocked`：明确缺少外部输入或权限，不允许猜测。

### US-001：以材料优先建立一次分析上下文

**作为**算法工程师，**我希望**给出数据、问题单/交接材料和可选的车型/服务器信息，**以便**工具先读取现有材料，缺失时只向我询问必要字段，并形成可审计绑定。

前置条件：数据路径可访问，材料可以是 handoff、表格、目录或对话补充。  
验收（Given/When/Then）：

- Given 材料中存在唯一的车型、COEM、代码版本和数据路径，When 调用 `cr60-intake`，Then 返回 `cr60-analysis-intake.v1`，每个选中字段含 `source/locator/method/authoritative`。
- Given 同一字段存在冲突候选，When 生成 intake，Then 状态为 `blocked` 或 `needs_confirmation`，不得选择一个候选继续运行。
- Given 缺少影响分析正确性的字段，When Pi 规划下一步，Then 输出缺失字段、影响和问题，不伪造默认值。

关联：`FR-01/FR-02/FR-13`；工具 `cr60-intake`、`cr60-data-prep-verify`；测试
`test_cr60_intake.py`、`test_cr60_data_prep_verify.py`；证据 `outputs/*intake*`、
`outputs/cr60_data_prep_verify_*.json`。  
当前状态：`implemented`（材料-first、fail-closed 和 Linux 数据只读校验已测）；完整业务
字段映射 `partially-verified`。

### US-001A：只询问用户能判断的问题

**作为**真实使用者，**我希望**工具把代码、帧、ROI、雷达、GDB 和变量等技术细节自动从材料、当前仓库和运行环境中探测出来，**以便**我只需要回答业务目标、证据偏好和是否允许受控运行，不需要理解内部实现。

验收：

- Given 缺少技术字段，When Pi 规划下一步，Then 优先调用确定性探测工具；不得把
  `frameID`、`objInfo`、ROI 点、PID、GDB 表达式等作为默认的用户提问。
- Given 技术探测得到多个冲突候选，When 需要用户确认，Then 用业务语言说明“会影响
  哪个结果”和可选后果；问题不得要求用户解释候选的内部代码含义。
- Given 用户只提供“分析这条数据/确认是否误报/找出原因”等业务目标，When 当前输入
  足以继续，Then Pi 自动生成技术 plan，并把技术缺口写入报告而不是反复追问用户。
- Given 用户不确定答案，When 该答案不影响安全边界，Then 工具可以先生成静态/隔离
  结果并明确局限；涉及正式工作区写入、编译、启动、attach 或 GDB 扰动时才单独请求
  用户确认。

关联：`FR-01/FR-13/FR-14`；Pi 入口与 `PiRunContext`；测试应覆盖技术缺口、冲突候选和
用户级确认文案。  
当前状态：`specified`（已纳入产品基线，后续每个交互能力必须遵守）。

### US-002：准备并校验匹配的 arbe/source context

**作为**仿真工程师，**我希望**系统在远程 Linux 上只读校验 arbe、algo_source、COEM/CUDA、HILMODEL、binary、GDB 和运行目标，**以便**我确认代码和数据版本确实匹配。

验收：

- Given 已确认服务器和 arbe 路径，When 调用 `arbe-preflight`，Then 返回 outer/algo commit、branch/detached/dirty、COEM、CUDA、`HILMODEL`、binary、GDB、ptrace 和 radar PID 状态。
- Given source context 缺失或 dirty/版本冲突，When Pi 规划写操作，Then 先进入 `blocked`/`needs_confirmation`，不得自动 checkout、fetch、pull 或覆盖修改。
- Given preflight 只读执行，Then 正式 workspace、已有 PID 和正式 ROS master 不被改变。

关联：`FR-03/FR-04/FR-12`；工具 `arbe-preflight`；测试 `test_arbe_preflight.py`；证据 `outputs/arbe_preflight_20260827.json`。  
当前状态：`partially-verified`（10.190.171.44 只读 preflight 已通过；正式构建授权未闭环）。

### US-003：按数据目录批量生成独立报告

**作为**问题单负责人，**我希望**直接交给 Pi 一个数据文件夹，**以便**每条 bag 得到独立 HTML、JSON bundle、CSV 和报告，同时索引汇总成功/失败原因。

验收：

- Given 一个目录含多个 bag，When 调用 `cr60-precheck(mode=folder)`，Then 自动发现全部支持的数据，生成“一条数据一个报告”，不因单个 case 失败而丢失其他 case。
- Then batch index 能打开每个完整数据名称、状态、事件数、报告入口和失败分类。
- Then 输出保留输入路径/hash/profile/source context，能够从报告回到原始数据。

关联：`FR-05/FR-10/FR-14`；工具 `cr60-precheck`；测试 `test_cr60_precheck.py`；真实证据 `actual_folder_CRGVI1829_20260827`（5 bags/149 events/5 ready）。  
当前状态：`partially-verified`（真实文件夹批量已通过；广泛车型/格式矩阵待补）。

### US-004：发现一条数据中的全部功能和全部事件

**作为**算法工程师，**我希望**一条数据中的多个功能报警和同一功能多次报警都被独立探测，**以便**选择任意一次事件继续查看，而不是只看到 FCTA/FCTB 或一个事件。

验收：

- Given 输出通道包含多个功能或多个上升沿，When 运行事件探测，Then 返回 `AlarmEvent[]`，每项至少有 `function`、`side`、`signal`、`frame_domain`、`start_frame`、`end_frame`、`edge_type`、`evidence_ref`。
- Given 当前代码没有可证明的功能映射，Then 返回 `unknown`/`not_available` 和来源，不把功能名硬编码为 FCTA/FCTB。
- Then 同一功能相邻帧持续为非零只形成一次上升沿事件，复位后再次上升形成下一事件。

关联：`FR-05/FR-06`；工具 `data-analyze`/harness adapter；测试 `test_cr60_precheck.py`、事件探测测试；真实证据 5 个 case 共 149 events。  
当前状态：`partially-verified`（事件集合和批量覆盖已验证；所有功能的权威输出映射仍需版本化代码/信号资料）。

### US-005：显示事件帧的真实自车、目标和索引属性

**作为**算法工程师，**我希望**选择一条事件后看到同一算法帧的自车属性、目标属性、雷达 ID、容器索引 `i` 和目标 ID，**以便**回到源码核对完全相同的对象。

验收：

- Then 每个字段有 `observed/derived/not_available`、来源 topic/message/CSV 列/源码 token、单位和 frame domain。
- Then 目标属性显示源码真实 token，例如 `objInfo->trcOutData[i].objID`，同时显示 `i`；如果 `i` 不能由静态数据唯一确定，必须显示 `unknown` 并给出 runtime/GDB 建议。
- Then 不同雷达坐标系不混画；radar1/2/3/4 的映射来自当前代码/配置或明确标注未确认。
- Then 事件窗口内的每个已解码 `frameID` 都可被选择，页面同步刷新该帧的自车字段、全部目标集合和报警状态；不能只显示报警首帧。
- Given 某帧没有目标或目标 ID 发生变化，Then 该帧明确显示 `no target`/`identity changed`，不得沿用上一帧目标属性冒充当前帧。
- Then 连续帧数据与事件/目标帧分层保存，用户可以从选中帧回到原始 topic、message index、源码 token 和条件断点。

关联：`FR-06/FR-07/FR-09`；harness viewer/model、`public-evidence-audit`；测试 `test_public_evidence.py`、viewer tests。  
当前状态：`partially-verified`（静态 bundle 保存连续帧，viewer-model 提供逐帧投影，
`alert-timeline.v1` 已投影播放帧；runtime 派生字段仍按缺口标记，正式 player parity 未闭环）。

### US-006：几何、yaw 和 ROI 只基于真实坐标契约绘制

**作为**感知/跟踪工程师，**我希望**图中自车和目标的矩形角点、朝向、雷达坐标、ROI 和相对位置可核对，**以便**区分目标未进 ROI、ROI/坐标错误和功能条件未成立。

验收：

- Given runtime `objPoly` 或同帧四角可用，Then 按实际角点绘制目标矩形，方向箭头与真实 `yawAng`/坐标定义一致，并显示原始角点。
- Given 只有 `distX/distY/length/width/yawAng`，Then 只能生成 `derived` 四角，并显示公式、轴方向、旋转原点和单位。
- Given 真实 ROI/参数不可得，Then ROI 显示 `not_evaluated`，不能输出“目标在 ROI 内/外”的确定结论。
- Then 视图必须随 radar/功能选择切换对应 ROI；不把 radar2 的目标强行套到左侧或别的功能 ROI。

关联：`FR-07/FR-08`；`cr60-debug-harness` viewer；测试 `test_geometry*`；当前截图中的几何问题作为回归样例。  
当前状态：`partially-verified`（缺数据时不假判已实现；真实坐标/ROI 全版本契约未闭环）。

### US-007：从当前源码生成可直接复制的条件断点

**作为**算法工程师，**我希望** HTML 给出真实源码函数、文件、行号、变量和数组下标构成的 VSCode/GDB 条件断点，**以便**不需要把工具自定义的别名翻译回代码。

验收：

- Given 当前 source code-index 与事件帧/目标 ID，Then 生成真实 source ref 和条件，例如 `frame_counter >= 47872 && frame_counter <= 47877 && sObj->objID == 44`，不得生成不存在的 `target_id` 等别名。
- Then 断点计划列出 scope/初始化风险；局部变量未进入作用域时不得宣称可用。
- Then 条件表达式、源码路径/行号、watch variables 和 GDB 命令同时进入 JSON/HTML。
- Given function 在当前代码不存在，Then 计划状态为 `blocked`，不退回另一个项目缓存或旧代码。

关联：`FR-09`；工具 `code-analyze`→`code-gdb-plan`；测试 `test_code_gdb_plan.py`；Pi composition evidence `pi_runtime_original_acceptance_20260827.json`。  
当前状态：`implemented`（source-index、typed ref、条件断点计划和真实 GDB 命令已验证）。

### US-008：按回放链路选择正确预热策略

**作为**仿真工程师，**我希望**系统根据当前数据中的输入链路选择预热帧数，**以便**SGU 目标注入不会被误套 150–200 帧点云策略，点云回放也不会只预热 3–5 帧。

验收：

- Given LGU/SGU 目标注入数据，Then profile 默认 `strategy=sgu_injection`、`requested=5`（允许 3–5 配置）。
- Given point-cloud 输入，Then profile 默认 `strategy=point_cloud`、范围 `150–200`。
- Given 混合或无法识别，Then 状态 `needs_confirmation`，不静默选择策略。
- Then 所有事件报告写入 `strategy`、`strategy_source`、`warmup_frames`、`target_frame` 和 frame domain。

关联：`FR-04/FR-06/FR-12`；harness replay profile；测试 `test_replay_strategy*`；真实 SGU/LGU 34-event case 已通过 5/5。  
当前状态：`implemented`（两类策略和混合门禁已实现；point-cloud 现场样例待补）。

### US-009：先利用公共 ROS/arbe 信号，再进入 GDB

**作为**算法工程师，**我希望**先查看 arbe 已公开发布的逐帧 topic 和 warning 输出，**以便**只有公共证据无法回答的问题才使用 GDB。

验收：

- Then `ros-topic-inventory` 区分 publisher 存在和实际一条消息可观测；`publisher_present=true` 不能直接等价于数据正在流动。
- Then `public-topic-plan`/`public-evidence-audit` 给出 topic、message type、字段、来源、缺口和回放状态。
- Given 公共数据足以回答目标问题，Then Pi 不自动执行 GDB；Given 不足，Then 生成 source-bound GDB plan。

关联：`FR-06/FR-09/FR-12`；工具 `ros-topic-inventory`、`public-topic-plan`、`public-evidence-audit`；测试 `test_ros_inventory.py`、`test_public_evidence.py`；真实 sampled inventory。  
当前状态：`implemented`（静态/采样区分和现场只读盘点已验证）。

### US-010：受控 headless GDB 获取 runtime 真值

**作为**算法工程师，**我希望**系统可以在确认后静默执行 GDB，停在目标帧读取局部变量/表达式/调用栈，并将结果回写报告，**以便**查看静态数据无法得到的 runtime 状态。

验收：

- Given `code-gdb-plan` 输出 source-bound commands，When 未批准调用 `gdb-service`，Then 只返回 plan，不接触进程。
- Given 目标 binary/source/debug symbols 与 PID 或 launch-under-GDB 已确认，When supervisor 批准执行，Then transcript 包含 stop、stack、args、locals、expressions、diagnostics 和 evidence status。
- Then `<optimized out>`、`No symbol`、`Cannot access memory` 保留为证据状态，不被转换成空值或 0。
- Then GDB 的 frame、函数、变量、binary hash、source hash 可回链到 HTML 事件；runtime 失败只降级，不覆盖 Sprint1 静态 bundle。

关联：`FR-09/FR-11/FR-12`；工具 `gdb-service`；测试 `test_gdb_service.py`；真实 isolated launch-under-GDB 证据 `runtime_smoke_evidence_20260827.json`。  
当前状态：`partially-verified`（真实隔离 launch-under-GDB 已命中 `frame=47877/radar=2/objID=44/i=0`；runtime normalize/validate/merge、HTML overlay 和 Pi deterministic context 已通过；正式 `bash start` 的已有节点保护和 node/PID/executable 定位已验证，但当前 `ptrace_scope=1` 下 existing-PID attach 被准确阻断，尚无正式 attach runtime 变量；binary fingerprint 和最终 CAN Tx 仍未闭环）。

### US-011：Pi 以原子工具组合一次诊断

**作为**用户，**我希望**只与 Pi 对话，由 Pi 组合 intake、preflight、precheck、代码分析、公共证据和 GDB 工具，**以便**不需要记住内部脚本顺序，同时每一步都可审计、可重跑。

验收：

- Then Pi 的扩展工具由当前注册表自动生成；新增 leaf tool/module 后无需修改总编排器。
- Then工具之间使用 typed artifact reference（如 `steps[0].result.data.gdb_commands`），引用缺失/越界时 fail closed。
- Then Pi 的每次运行都有 `PiRunContext`，包含 variant/project、case、source/binary、权限策略、输入 artifact 和 freshness 状态；工具不能跨项目取缓存。
- Then `AgentLoop`/`ReAct`/直接 CLI 只能作为开发或 Pi 不可用时的明确 fallback，不与 Pi 并列为产品用户入口。

关联：`FR-01/FR-02/FR-09/FR-13`；`pi`、`module_bridge`、`agent_loop`、Pi extension generator；测试 `test_agent_loop.py`、`test_cr60_precheck.py` 和本文件对应 Pi bridge tests。  
当前状态：`partially-verified`（typed composition、runtime/formal lifecycle leaf module 的 catalog/registerTool 生成、参数透传和 `pi-context` runtime 输入已通过；完整 Pi coordinator 的长链路恢复/审批运行仍需后续验收）。

### US-012：Pi 执行前展示计划并处理审批

**作为**仿真工程师，**我希望**所有切分支、数据传输、CUDA/配置写入、编译、启动、GDB attach 和远程进程操作在执行前集中确认，**以便**自动化不会误伤他人工作区。

验收：

- Then side-effect tool 先返回目标、命令、预期改动、风险、回退和清理计划。
- Then未批准执行返回 `approval_required`，不启动子进程、不修改远程文件、不 attach 正式 PID。
- Then批准后所有操作有 audit artifact；单 case 失败不吞掉远程返回码和 stderr。
- Then当前 workspace dirty、algo detached/dirty、版本绑定不完整时，不自动 checkout 或覆盖。

关联：`FR-03/FR-04/FR-12/FR-13`；`bosch-data-transfert`/`cr60light-arbe-build` adapter、
`arbe-source-resolve`、`arbe-cuda-resolve`、`gdb-service`；现有 approval tests。  
当前状态：`partially-verified`（当前 source/ref、CUDA/config 和数据传输前校验已实现并在
10.190.171.44 实测；传输 adapter 的 approval gate 已测；正式工作区副作用流程待用户
指定目标版本、远端脚本和目标目录）。

### US-013：多项目、多服务器、多版本隔离

**作为**平台维护者，**我希望**更换服务器、arbe 路径、algo_source branch、COEM、车型或用户后仍能运行，**以便**平台长期复用而不产生隐含默认和缓存串线。

验收：

- Then 所有 run artifact 携带 `project_id/variant_id/source_context_fingerprint/data_fingerprint`。
- Then workspace、source docs、codegraph、memory、Pi session 按 variant/project 隔离。
- Given 当前 source/binary/data fingerprint 不匹配，Then runtime 结论为 blocked 或 partial，不消费旧知识。
- Then服务器参数全部由 intake/context 传递，不在 tool 内硬编码 `10.190.171.44`、固定车型或固定功能。

关联：`FR-02/FR-03/FR-13`；`ProjectContext`、freshness/knowledge guard；测试 `test_project_isolation.py`、`test_freshness.py`。  
当前状态：`implemented`（隔离路径和 freshness 基础已测）；跨用户服务器权限模型 `specified`。

### US-014：以证据优先解释和反馈闭环

**作为**算法工程师或问题单负责人，**我希望**Pi 将证据、冲突、缺口、候选原因和验证建议分开，**以便**我能判断正报/误报而不是被一个未经证明的结论误导。

验收：

- Then AI 解释中每个事实都能链接到数据、源码、需求或 runtime artifact；推理结论标记为 `inference`。
- Then `perception`、`tracking`、`situation`、`function`、`config`、`replay` 只能作为候选分类，不能在证据不足时自动升级为最终根因。
- Then用户确认/否定的结果形成带 variant/source/data provenance 的反馈，不污染其他项目知识。

关联：`FR-10/FR-13/FR-14`；expert panel、knowledge guard、memory；测试 `test_knowledge_guard.py` 等。  
当前状态：`partially-verified`（runtime 已作为确定性输入进入 Pi context；跨代码/需求/案例的 AI 根因解释、反馈和知识发布闭环仍未完成）。

### US-015：逐步呈现分析过程，而不是只给最终答案

**作为**算法工程师，**我希望**每个分析阶段都显示发现、证据、冲突、缺口和下一步，
**以便**即使最终根因尚未确认，中间线索也能直接帮助我 debug。

验收：

- Given 用户提交一条数据，When 完成 intake/event/scene/code/runtime 任一阶段，Then 生成
  `AnalysisStep`，包含输入/输出 artifact、observations、claims、gaps、conflicts、耗时和
  next action；不能只更新一条最终文本。
- Then 用户可以查看、接受、质疑、标记无关或选择下一实验；该决定进入 ledger，后续 Pi
  不重复询问或遗忘。
- Then HTML/Workbench 展示的是结构化工程理由和 evidence ref，不展示不可验证的原始
  模型思维链。
- Given 分析被中断，When 重新打开 run，Then 从 checkpoint/ledger 继续，不从头重新解释。

关联：`FR-13/FR-14`；新增 `analysis-run/step/claim` 契约。  
当前状态：`partially-verified`（run create/read/update、step begin/complete、claim append、
Pi dialogue/tool-end step、Analysis Trail 投影、原子写/事件审计/并发锁和真实 artifact 恢复
smoke 已完成；用户 decision、Workbench 和 hypothesis/experiment 自动编排仍未实现）。

### US-016：为选中事件准备完整而渐进的代码调查链

**作为**算法工程师，**我希望**选择事件后看到 output→feature→situation→target→input 的
当前源码链路，**以便**快速进入真正相关的函数、参数和变量，而不是全仓搜索。

验收：

- Then 生成 `event-code-path.v1`，绑定 event/source fingerprint，包含函数、source ref、
  真实 token、读写位置、参数依赖、可静态验证条件、runtime-required 变量和 breakpoint
  group；同时生成按当前调用关系和源码行号排列的 `condition_chain`，覆盖可发现的上游
  gate/状态机、event root 和相关 helper/callee。
- Then 代码面板按五层渐进展开，默认只展示当前层和关键缺口，不堆叠完整调用图。
- Given 函数/字段在当前版本不存在，Then 对应层 blocked/unsupported，不回退旧项目知识。
- Then 用户可以从任一代码节点执行“查看源码、复制断点、加入下一次采集”。
- Then 条件链只能作为当前 source 的候选执行路径；每一项必须保留 `chain_relation`，不能把
  不同 caller/callee 或不同分支拼成一个无条件 AND 链。

关联：`US-007/FR-09`；`code-learn`、`code-analyze`、`code-gdb-plan`。  
当前状态：`partially-verified`（事件级 `event-code-path.v1`、真实 token、断点和条件
trace 已可生成；动态 caller/helper 条件链、五层渐进代码面板和跨项目 AST 准确率尚未验收）。

### 约束：Pi 的代码分析能力与当前 source 取证边界（2026-09-03）

Pi 可以做通用代码阅读、逻辑解释、条件比较、假设排序和下一步规划，但不能把模型自身的
代码常识当作本次项目的代码事实。每次代码分析必须先使用当前 `code-context`、`code-learn`、
`code-analyze` 或 `event-code-path` 获取真实入口、caller/callee、源码条件、参数、变量和
输出；Pi 只能在这些结果之上组织自然语言。

条件链由当前 source 动态决定，不得固化为“所有功能都先状态机、再车速、再 dynFlg”的模板。
报告可以按当前调用关系和源码行号展示“状态机/gate → 自车 → 目标 → ROI/预测 → 保持计数 →
输出”等实际存在的阶段；某阶段在当前 source 未发现时必须写明未发现，不能拿其他功能、其他
车型或旧分支补齐。条件值必须来自同一 `data/source/binary/config/replay` 身份下的同帧公共运行
态或 GDB；缺值是 `not_evaluable`，不是 false。

Pi 默认关闭内置任意工作区文件工具，通过注册的 source-bound 工具取代码，防止绕过
`PiRunContext` 的 identity/freshness 门。若后续允许内置读文件，也必须限制在当前 source context
并记录 provenance。最终用户输出固定先给总结结论，再给报警帧数据表、工况图和按当前源码顺序的
条件命中叙述；模型推理只能形成 inference/hypothesis，不能创建 observed runtime 事实。

### US-017：Pi 与用户协同完成 DebugExperiment

**作为**算法工程师，**我希望**自动 headless 和人工 VSCode debug 使用同一事件、断点、
变量和假设上下文，**以便**我可以在工具不足时接手，并把结果继续交给 Pi 分析。

验收：

- Then 每个 DebugExperiment 说明要回答的问题、方法、预期区分的候选、断点/watch、目标
  frame/radar/object、扰动风险和结果回填方式。
- Given headless 可执行，Then 用户批准后自动采集并更新 claims/hypotheses。
- Given headless blocked，Then 生成可复制的 VSCode handoff，并明确“看到 A/B 分别支持
  哪个候选”。
- Given 用户回填变量/栈/截图/备注，Then 保存为 `user_observation` evidence layer，并重新
  计算候选状态；不要求用户重复描述数据和代码上下文。

关联：`US-007/US-010/US-011`。  
当前状态：`partially-verified`（已具备 DebugExperiment/user-observation ledger 原子模块、
状态门禁和报告摘要投影；headless/VSCode 实验自动回填、用户决策和 Live Workbench 仍未实现）。

### US-018：以假设和实验逐步收敛根因

**作为**算法工程师，**我希望**系统将 data、replay、perception、tracking、situation、
function、config、output 和 integration 作为可验证候选，**以便**每一步都能排除或缩小范围，
而不是一次 AI 分类后直接给修复代码。

验收：

- Then 每个 hypothesis 有支持、反证、关键缺口、required evidence、next experiments 和
  `open/testing/supported/weakened/rejected/confirmed_by_user` 状态。
- Then Pi 优先选择最小成本、区分度最高的 experiment；公共 runtime 足够时不执行 GDB。
- Given 新证据出现，Then 记录 rank/status 变化和具体 evidence，不静默重写历史结论。
- 最终 `root_cause_confirmed` 必须满足数据/source/binary/event 身份一致、关键链路证据覆盖、
  主要替代假设被削弱/排除，并由用户确认或明确验收规则确认。

关联：`US-014/FR-14`。  
当前状态：`partially-verified`（Hypothesis 状态/历史/支持与反证引用已有持久化能力；自动
候选生成、区分实验选择和根因发布门仍未实现）。

### US-019：通过 ProjectCapabilityManifest 适配不同 Gen6 项目

**作为**平台维护者，**我希望**每个项目动态声明数据、功能、代码、回放、runtime 和展示
能力，**以便**接入不同 Gen6 项目时不复用错误的 CR60 Light 假设。

验收：

- Then manifest 绑定 project/vehicle/coem/source fingerprint，声明 parser、frame domain、
  output mapping、FeaturePlugin、ReplayStrategy、RuntimeProvider、GeometryProvider 和 panel。
- Given manifest 未声明某功能或 provider，Then Pi 显示 unsupported/not_available，不调用
  其他项目的工具或知识。
- Then 新项目至少通过无报警、已知报警、runtime、缺输入和版本变化五类验收。
- Then capability pack 只从 manifest/freshness 通过的原子工具生成。

关联：`US-013`。  
当前状态：`specified`（variant/workspace/freshness 基础已实现）。

### US-020：以第一条线索、Debug-ready 和证据覆盖衡量效率

**作为**实际使用者，**我希望**工具尽快给出可行动线索并减少重复解析/搜索/回放，
**以便**即使复杂问题尚未结束，也能持续提升我的调试效率。

验收：

- 每个 run 记录 Time to First Useful Clue、Time to Debug-ready、bag full-read count、代码索引
  命中/刷新、GDB/replay 次数、用户干预次数和关键 evidence coverage。
- 相同 data/source fingerprint 重复分析不重复完整解析；报告刷新不重解 bag。
- Pi 每阶段使用 capability shortlist 和 artifact 摘要，不把全部大 payload 放入 prompt。
- 真实问题单建立人工 baseline 后再设效率目标，不预先承诺固定节省百分比。

当前状态：`specified`。

### US-021：复用 arbe ObjectList 方式获取逐帧目标属性

**作为**算法工程师，**我希望** Pi 能像 arbe 的 `enableobjectlist Disp` 一样按 radar/frame
查看目标属性，并与自车和报警上下文联动，**以便**我不用先打开 GUI 才能判断目标是否进入
算法处理链。

验收：

- Given 当前 arbe/source/runtime capability 声明了 ObjectList，When 选择某个报警事件和
  frame，Then 能按 radar1/2/3/4 展示当前可用的 `wfSObj` 字段；字段目录来自当前 msg
  定义，不在平台内复制固定结构。
- Then 至少保留 `ID`、`objID`、位置、尺寸、yaw、速度、RCS、TTC、DDCI、生命周期/年龄和
  各功能 object flag，并显示 `RAW_SGU/ALGO` 来源。
- Then ego、warning、radar_info 与目标属性分别保留来源和 frame association status；
  objectlist 没有 algorithm frameID 时不得伪造 exact same-frame。
- Then 能从目标属性跳转到代码链、条件和下一次 DebugExperiment。

关联：`FR-07/FR-10/FR-15`；`PublicRuntimeCollector`、`ArbeReplayAdapter`。  
当前状态：`partially-verified`（arbe GUI/public topic 已确认；统一 collector 和 stamped
snapshot 尚未实现）。

### US-022：一次性生成当前代码的功能上下文

**作为**算法工程师，**我希望**代码仓在数据分析前先生成一次当前版本的功能/逻辑/调度
指引，**以便**后续分析直接查询相关链路，不反复大范围搜索整个仓库。

验收：

- Given 当前 source context 已确认，When 执行 code context refresh，Then 生成绑定当前
  source fingerprint 的 feature/output/input/parameter/geometry/condition/breakpoint 索引。
- Then 同一 source fingerprint 的多条数据复用索引；source 变化时只增量刷新受影响文件，
  旧上下文不得进入当前 Pi prompt。
- Then 事件查询返回 output→feature→situation→target→input 的最小链路、真实 source ref、
  变量 scope 和 runtime-required gap，不返回未经证明的固定模板。
- Then Pi 可按问题和事件检索最小代码包，AI 只负责解释和组织，不负责替代源码索引。

关联：`FR-03/FR-08/FR-16`；`code-learn`、`code-analyze`、`EventCodePathBuilder`。  
当前状态：`partially-verified`（CodeGraph/source learn、context refresh/read 和
event-code-path 已统一；动态 helper/runtime local 和跨 Gen6 验收仍缺）。

### US-023：三个出口共享同一个可恢复分析运行

**作为**真实算法工程师，**我希望**批量预检查、单事件详细报告和后续 Pi 对话共享同一个数据/源码/runtime
上下文，**以便**我可以先拿到低成本线索，再逐步补充精细证据，而不需要重复说明数据和问题。

验收：

- Given 一个可访问的数据目录，When 用户请求批量预检查，Then Pi 自动调用现有 cr60-precheck，
  输出每条数据一个独立 bundle/viewer/HTML 和 batch index，并把输入、source fingerprint、事件数、
  失败原因写入一个 AnalysisStep。
- Given 某条数据的 bundle/viewer，When 用户请求详细报警诊断，Then Pi 可以通过通用 evidence-query
  选择功能/侧别/radar/事件/帧，返回真实 ego/target/索引/代码/断点字段；不存在的字段返回
  not_available，不以相邻帧或模型常识补齐。
- Given 事件证据和当前代码链已准备，When 用户请求详细报告，Then diagnosis-report 生成
  diagnostic-report.v1、Markdown/HTML companion，并保留静态事实、公共 runtime、GDB 和 AI
  解释的独立来源；AI 未运行时报告仍可交付证据版。
- Given 用户在同一 Pi 会话中追加问题，When 问题只涉及已有 artifact，Then Pi 优先调用查询/代码
  原子能力，不重新解析 bag 或全仓扫描；回答包含引用的 artifact/字段路径，并追加一个可见的
  AnalysisStep。
- Given 对话被中断，When 用户用同一分析运行继续，Then Pi 使用 analysis-run-read 和同一
  session/run context 恢复；不得创建一个无来源的新结论或串用另一 variant 的缓存。
- Given 详细诊断尚缺公共/runtime/GDB 证据，Then 报告输出 pending/partial、缺口和下一实验，
  不把“正报/误报”或“根因已确认”写成确定事实。

关联：FR-10/FR-13/FR-14/FR-16；cr60-precheck、evidence-query、diagnosis-panel、
diagnosis-report、analysis-run-*；定向测试和真实 CRGVI-1829 artifact smoke。  
当前状态：partially-verified（批量/HTML/ledger/runtime 基础、查询/报告投影和真实 Pi 连续追问已通过；
Pi 自动执行批量和带 AI 面板的详细报告长链路仍需现场验收）。

### US-024：脱离 ChatGPT 后使用 Pi 完成全流程

**作为**独立使用本产品的算法工程师，**我希望**只通过 Pi 交互入口完成数据传输、arbe 环境准备、
补丁、编译、启动、预检查、详细诊断、最终报告和问答式 Debug，**以便**产品可以独立工作，且我不需要
记住工具顺序。

验收：

- Given 用户提供数据/材料/服务器/arbe/source context，When 进入 Pi，Then Pi 创建一个绑定当前
  project/data/source/binary 的 AnalysisRun，并从 live catalog 选择原子工具；
- Given 需要数据传输、checkout、写配置、补丁、编译、启动或 GDB，When Pi 规划动作，Then 先输出
  目标、命令、影响和确认点，未确认不产生副作用；
- Given 静态、public runtime、GDB 或记忆 artifact 已产生，When 用户继续追问，Then Pi 复用同一
  run/context/artifact，不重新扫描无关仓库，不丢失阶段性结论；
- Given Pi provider 不能稳定从全量 catalog 选择工具，Then 产品按当前意图提供 bounded allowlist，
  但不改变原子 registry 或新增平行编排器。

关联：`FR-10/FR-13/FR-14/FR-16`；`pi`、`PiBridge`、`pi_tool_bridge`、Analysis Ledger。
当前状态：`partially-verified`（真实单数据 Pi tool call、manifest companion discovery 和 ledger
已通过；带副作用的全流程及 AI 长链仍需现场验收）。

### US-025：报警条件逐项代入和场景化呈现

**作为**算法工程师，**我希望**详细报告基于当前代码和报警时刻的真实字段，逐项呈现报警条件如何满足，
并用自车/目标/ROI/朝向示意图展示状态，**以便**我可以区分 perception、situation、功能条件和输出
保持逻辑，而不是只得到最终结论。

验收：

- Given 当前事件、source code index 和选中分析帧，When 生成详细报告，Then 报告输出
  `condition-trace.v1`，每项含原始 C 表达式、源码位置、实际 bindings、求值状态和原因；
- Given 表达式所需字段来自不同帧、不同雷达或不存在，Then 不进行跨帧/跨雷达补值，状态为
  `not_evaluable` 并保留缺口；
- Given 条件可用安全子集求值，Then 只使用当前 source 参数和同一帧值，输出 substituted expression
  和 `satisfied`/`not_satisfied`，不把求值结果冒充 runtime GDB 真值；
- Given 有目标 polygon/ego polygon/ROI 坐标证据，Then HTML 按当前坐标契约绘制朝向和区域；缺少
  runtime polygon/ROI 时显示来源和 `not_evaluated`，不绘制伪造的 PASS/FAIL；
- Given AI 参与解释，Then AI 只能消费 condition trace 和 evidence，不得创建或覆盖 observed/derived
  字段。
- Then 详细结论必须按当前 source 实际提供的链路顺序组织：状态机/系统 gate（若存在）→
  自车运动/速度（若存在）→目标 dyn/track/属性筛选（若存在）→ROI/几何→预测/阈值→
  保持/计数→报警灯输出；若当前版本没有某个阶段，显示“当前 source 未发现”，不得套用其他
  功能或版本的固定顺序。

关联：`FR-07/FR-08/FR-09/FR-10`；`condition-trace`、`diagnosis-report`、`event-code-path`。
当前状态：`partially-verified`（CRGVI-1829 已生成条件 trace、场景 SVG、播放帧图和
结论/缺口；动态 caller/helper 条件链的真实跨版本验收和正式复验仍缺）。

### US-026：跨证据层报警时间线和播放帧比较

**作为**算法工程师，**我希望**在同一份详细报告中看到原始报警、算法回放、公共运行态、GDB
和 CAN Tx 的独立时间线，**以便**区分“录制里有报警”“仿真复现”“算法输出”和“最终 CAN 输出”。

验收：

- Given 任一 source/context 下的 bundle、viewer 或 runtime artifact，When 生成 timeline，Then
  以 `function/side/radar/frame/status/layer` 投影所有可用报警行；不认识的功能也能作为结构化 token 展示；
- Then 显示播放帧、预热帧、选定帧及该帧可绑定的报警信号；帧来源和 association status 可见；
- Given 某证据层缺失，Then 该层显示 `not_available`，raw/replay compare 显示 `not_evaluated`，
  不生成伪造仿真结果；
- Given 两层均有 observed exact frame，Then 才允许输出 `same/different`；没有 exact frame 时为
  `not_comparable`；
- Given data/source/binary identity 冲突，Then timeline 和详细报告 blocked，运行态不可进入 selected event。

关联：`US-003/US-004/US-005/US-009/US-010/US-025`；`alert-timeline`、`diagnosis-report`、
`runtime-evidence`。  
当前状态：`partially-verified`（通用 engine/module、schema、报告投影和当前 CRGVI-1829
缺层显示已通过定向测试和实际报告；replay/public/GDB/CAN 联合实测尚未完成）。

## 5. Pi-first 的产品边界

### 5.1 正式入口

| 层 | 正式职责 | 用户可见入口 | 状态 |
|---|---|---|---|
| L4 | 意图理解、计划、工具组合、审批交互、结果解释 | `python cli.py pi ...` 驱动 `pi --mode rpc` | 主入口 |
| L3 | Pi 运行上下文、typed composition、artifact 聚合、权限门 | Pi extension + `ai/capability/*` | 本轮补强 |
| L2 | 原子能力：intake、preflight、extract、analyze、public evidence、GDB、报告 | Pi `registerTool` | 主能力 |
| L1 | parser、FrameStore、code index、ROS/GDB transcript、adapter | Python engines/providers | 确定性实现 |
| L0 | bag/BLF/MF4/DBC、当前源码、arbe/ROS、远程 Linux | 外部环境 | 输入/执行边界 |

`python cli.py <module>` 是开发、测试和故障排查入口；它不是与 Pi 并列的产品流程。`AgentLoop` 和 `ReActPlanner` 仍保留为离线 fallback/回归执行器，但不得让用户必须理解它们才能使用平台。

### 5.2 原子工具原则

1. Pi 的可调用工具必须在 `registerTool` 中注册，描述和 JSON Schema 来自唯一 catalog。
2. 工具执行委托给 `pi_tool_bridge`，桥接到现有 `BaseTool.safe_execute()` 或 `BaseModule` adapter；不能为 Pi 再写一套业务逻辑。
   历史模块若没有声明 `input_schema`，catalog 从其真实 `run()` 签名和 argparse 声明生成保守 schema，并复用 `from_cli_args` 的构造映射；不能退化成“无参数但实际需要参数”的假工具。
3. 原子工具只做一个可验证动作：读材料、探测环境、解析事件、查源码、生成 GDB 计划、执行已批准 GDB、审计公共证据等。
4. 工具返回统一 envelope，并包含 `status`、`message`、`data`、`artifacts`、`evidence_status`（适用时）和 provenance。
5. 编排关系只在 Pi/typed composition 层表达，不能把 FCTA/FCTB、固定 radar、固定参数写死在通用 tool bridge。

### 5.3 PiRunContext

Pi 每次处理数据前应得到一个不可变的 `pi-orchestration-context.v1`（实现前可由 `cr60-intake`、`arbe-preflight` 和 `project-context` 共同生成）：

```text
PiRunContext
├── run_id / context_fingerprint / created_at / operator
├── project: project_id / variant_id / customer / vehicle / coem
├── data: case_id / paths / hashes / bag metadata
├── source: arbe / algo_source / branch / tag / commits / dirty state
├── build: CUDA / HILMODEL / binary / build-id / debug-symbol state
├── runtime: ROS master / radar mapping / PID candidates / replay strategy
├── policy: read-only / approval required / allowed side effects / timeout
├── artifacts: intake / preflight / code-index / public-evidence / reports
└── freshness: input signatures / knowledge manifest / mismatch state
```

上下文是编排输入，不是让 LLM 自由改写的 prompt 文本。Pi 可以根据工具结果扩展上下文引用，但不能覆盖权威字段；冲突只能进入确认或 blocked。

## 6. DDD 工作流与交付门

### 6.1 文档主线

```text
用户问题/材料
  → 用户故事与验收（本文）
  → 调研事实（research report）
  → 架构决策（ADR/decisions）
  → 模块/软件设计（interfaces/schema）
  → 实施工作包（implementation plan）
  → Sprint task
  → code + deterministic tests
  → runtime/batch evidence
  → handoff + 文档回写
```

### 6.2 Definition of Ready（进入开发前）

- US 有角色、目标、前置条件、Given/When/Then 验收和优先级；
- 需要的数据、source context、权限和用户确认字段已列明；
- 已区分 observed/derived/not_available，未把推断写成事实；
- 有对应的 schema、模块边界和回退策略；
- 影响范围和不改变的系统（尤其正式 arbe workspace）已声明。
- 已定义本 story 会产生哪些 AnalysisStep/Claim/Gap/Hypothesis，以及用户在哪个检查点可见；
- 已说明对效率和准确性的影响：缓存/fingerprint、预计重复读取、runtime 扰动和证据门。

### 6.3 Definition of Done（一个故事完成）

- 实现只覆盖已批准的 story scope，且通过对应确定性测试；
- JSON schema、API、`AGENTS.md`、模块设计和目录索引同步；
- 至少有一个可复现命令和输出 artifact；
- 有正常、缺输入、冲突、权限/执行失败和降级证据；
- 真实环境结论注明 host、path、commit/hash、时间和是否隔离；
- handoff 说明完成项、未完成项、用户需要确认的下一步；
- 未满足 release gate 的故事只能标 `partially-verified`，不得写成 production-ready。
- Analysis Ledger 中可从输入 artifact 追到 step、claim、experiment 和最终报告；
- 中断/失败仍保留阶段性线索，最终 UI 不隐藏关键 gap/conflict。

### 6.4 需求追踪矩阵（当前主线）

| 领域 | 用户故事 | 主要实现 | 机器契约/产物 | 当前证据 | 状态 |
|---|---|---|---|---|---|
| Intake | US-001 | `cr60_intake` + `cr60-data-prep-verify` + `cr60-data-transfer` + `engines/arbe/intake/data_prep/transfer` | `cr60-analysis-intake.v1` / `cr60-data-prep-verification.v1` / `cr60-data-transfer-session.v1` | intake 单测/CRGVI-1829 Linux hash verify/approval tests | implemented |
| Source/Build | US-002/US-012 | `arbe_preflight` + `arbe-source-resolve` + `arbe-cuda-resolve` + `arbe-patch-plan` + transfer/build adapter | preflight/source/CUDA/patch/approval artifacts | 10.190.171.44 只读 preflight/source/CUDA/patch | partial |
| Batch | US-003/US-004/US-023 | cr60_precheck + harness | diagnosis bundle / report / batch index | 5 bags/149 events | partial |
| Frame/Geometry | US-005/US-006 | harness viewer + public evidence | viewer model / evidence audit | 同帧 runtime 局部证据 | partial |
| Code/GDB plan | US-007 | `code_analyze` + `code_gdb_plan` | `code-gdb-plan.v1` | real source index + typed composition | implemented |
| Public ROS | US-009 | `ros_topic_inventory` + public audit | ROS inventory/public evidence | live inventory + sampled no-message | implemented |
| Runtime GDB | US-010 | `gdb_service` | `gdb-session.v1` | isolated launch-under-GDB | partial |
| Pi orchestration | US-011/US-023 | Pi extension + bridge + context + session ledger | composition/context/AnalysisRun | typed composition + session work in progress | partial |
| Isolation | US-013 | `ProjectContext` + freshness guard | fingerprints/manifest | isolation tests | partial |
| Explain/feedback | US-014 | expert panel/memory/knowledge guard | diagnosis bundle | existing unit coverage | specified |
| Analysis trail | US-015 | AnalysisLedger + Pi dialogue/tool step + diagnostic-report Analysis Trail | analysis-run/step/claim | ledger recovery + tool-end step + HTML projection | partially-verified |
| Event code path | US-016 | code index + event-code-path builder | `event-code-path.v1` | generic engine/module + fixture tests | partial |
| Collaborative debug | US-017 | DebugExperiment + GDB/VSCode bridge + ledger modules | experiment/user-observation | handoff/GDB primitives + persistence/report fixture | partial |
| Root-cause loop | US-018 | hypothesis board + experiment planner | `hypothesis.v1` | hypothesis state/history + report projection | partial |
| Gen6 adaptation | US-019 | ProjectCapabilityManifest + plugin SPI | capability manifest | variant/freshness foundation | specified |
| Efficiency | US-020 | run metrics + incremental indexes + capability packs | metrics/step cost | partial timing evidence | specified |
| Arbe ObjectList | US-021 | PublicRuntimeCollector + `public-runtime-normalize` + ArbeReplayAdapter | `runtime-snapshot-with-frame.v1` / collector artifact | normalizer tests + SSH replay capture + current arbe topic/table evidence | partial |
| Code context | US-022 | code-context-refresh/read + EventCodePathBuilder + capability manifest | `code-context.v1` / `code-index.v1` / `event-code-path.v1` | real 16-file source mirror + condition index + fixture tests | partial |
| Evidence query/report | US-023 | evidence-query + diagnosis-report + existing viewer | evidence-query.v1 / diagnostic-report.v1 | current CRGVI-1829 artifacts + Pi bridge | partially-verified |
| Standalone Pi entry | US-024 | `PiModule` + `PiBridge` + generated registerTool + ledger | PiRunContext / AnalysisRun | real single-data Pi tool call | partially-verified |
| Condition/scene report | US-025 | condition-trace engine + diagnosis-report HTML | `condition-trace.v1` / diagnostic-report.v1 | CRGVI-1829 real FCTA_R: 22 source conditions, scene SVG, 77-test slice | partially-verified |
| Alert timeline/compare | US-026 | `alert-timeline` + diagnosis-report projection | `alert-timeline.v1` | raw/playback/missing-layer actual report + 6 alert-timeline tests | partially-verified |

## 7. 本轮开发顺序（文档优先）

1. 本文与 PRD/ADR 对齐，冻结 Pi-first 边界和用户故事编号；
2. 定义 `pi-orchestration-context.v1`，把上下文作为 artifact/typed input，而不是散落在 prompt 中；
3. 让 Pi extension 只通过一个 bridge 调用模块/工具，并实际传递 `params`；显式加载当前项目 extension；
4. 为生成器、bridge、context 和审批边界补确定性测试；
5. 重新生成 extension，做 Pi 工具目录/参数传递 smoke；
6. 重新跑 radarAnalyze/harness 回归，更新真实证据、Sprint、research 和 handoff；
7. 正式 arbe workspace 的切分支、更新 CUDA、编译、`bash start` 和 existing PID attach，等待用户确认目标版本和副作用授权后单独验收。

## 8. 当前必须向用户确认的 P0 问题

这些问题不能从当前仓库和 bag 唯一推出，工具必须停在确认点：

1. 正式工作区验收是否允许使用当前 `/home/hoz2wx/CR60LIGHT/cr60_light_arbe`？当前外层 `develop_LGU_Simulation`，algo_source 为 detached/dirty；是否指定一个可切换的目标 tag/branch 或要求先建立隔离副本？
2. 对 `CRGVI-1829` 这 5 条数据，`03_QZH`、`BYD_UKE`、`HILMODEL=2` 是否就是本次正式 runtime 验收绑定，而不是仅作为当前只读现场探测结果？
3. GDB 的正式验收标准是“隔离 launch-under-GDB 可以接受”为第一阶段，还是必须执行标准 `bash start` 后对 `arbe_visualization_engine` 的现有 radar PID 做 attach？后者会暂停正式进程，需要明确窗口和批准。
4. Pi 运行时是否统一使用当前已安装的外部 `pi` CLI；本机当前 `pi --list-models` 暴露的是 `bosch-qwen3_6 / Qwen3.5-27B-FP16`，是否为其他用户统一采用环境变量/配置传入的 provider/model 与离线 fallback 策略？

在这些问题确认前，本项目可以继续做 read-only、隔离 runtime、schema、Pi bridge 和批量预检查，但不能把正式 workspace runtime 标记为完成。

## 9. 变更规则

任何以下变化必须先修改本文中的 US/AC 和状态，再修改实现：

- 新增功能、报警输出、side、frame domain 或事件语义；
- 新增车型、COEM、CUDA、坐标系、雷达映射或 ROI 来源；
- Pi tool schema、审批范围、context 字段或 fallback 行为；
- report HTML 的证据显示方式；
- GDB target、变量、暂停策略和权限模型。
