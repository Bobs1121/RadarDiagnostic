# CR60 Pi Unified Platform 架构决策记录

版本：`adr.v1.2`  
日期：`2026-08-30`  
状态：DDD 基线，等待用户确认 P0 运行边界

## ADR-001：radarAnalyze/pi 作为统一编排入口

状态：`accepted-for-implementation`

决策：用户从 `radarAnalyze/pi` 发起问题分析、预检查、运行时调试和报告交付。Pi 负责意图、规划、工具调用、审批交互和解释；确定性 Provider 负责事实。`python cli.py <module>`、AgentLoop 和 ReAct 只保留为开发/离线/故障兜底入口，不是并列产品入口。

原因：radarAnalyze 已有 Pi、ReAct、AgentLoop、工具注册、项目隔离和 freshness 基础。继续扩展现有底座比再建一个 Agent 更稳。

不意味着：Pi 可以直接执行任意远程 shell、直接读 GDB 或覆盖证据。

## ADR-002：cr60-debug-harness 保持独立

状态：`accepted-for-implementation`

决策：Sprint1 bag/BLF/source/HTML 能力继续在 `cr60-debug-harness` 中维护，radarAnalyze 通过 CLI/JSON adapter 调用。

原因：降低依赖冲突，允许 harness 作为 Agent skill/CLI 独立使用，也防止 radarAnalyze 的 AI 变化影响确定性解析。

共享边界：版本化 JSON/JSONL contract、artifact reference 和 source/data fingerprint。

## ADR-003：复用前置 skill，不复制执行逻辑

状态：`accepted-for-implementation`

决策：`bosch-data-transfert` 和 `cr60light-arbe-build` 作为 Provider 的执行来源，统一平台只负责参数校验、审批、状态和结果归一。

原因：两个 skill 已包含实际数据准备、版本/tag、车型/CUDA、补丁、编译和启动规则。复制会形成两个容易漂移的实现。

## ADR-004：SGU/HILMODEL=2 和点云回放是两套策略

状态：`accepted-for-implementation`

决策：运行时调试显式选择 `sgu_injection` 或 `point_cloud`。SGU 按实际 `frameID` 默认预热 3–5 帧，不使用 150–200 帧点云预热；点云默认使用按代码周期和 `frameID` 定义的 150–200 帧策略且可配置。

原因：SGU 已绕过点云/聚类/跟踪，点云预热与功能状态预热不是同一概念。

## ADR-005：几何结果必须有证据等级

状态：`accepted-for-implementation`

决策：runtime `objPoly`/`adasRoi` 优先；source formula 重建只能标记 `source_derived_*`；有
同一事件的源码推导 polygon/ROI 时可以给出几何关系，但没有同帧同坐标 runtime polygon/ROI 时，
不得把它升级为 observed collision 或功能报警结论；完全没有可比 polygon/ROI 时才是
`not_evaluated`。

原因：当前 HTML 的自车锚点、目标 runtime polygon 和 ROI 证据不完整，视觉重叠不能替代算法几何条件。

## ADR-006：标准 arbe 流程上的 headless GDB attach 优先

状态：`accepted-for-implementation`

决策：GDB 策略以 headless GDB 为主，优先 attach 到用户标准 `bash start` 已启动、并已通过 readiness probe 的真实 `arbe_visualization_engine` 进程；明确批准的 launch-under-GDB 作为 existing PID attach 受限或需要隔离复现时的备用；VS Code handoff 作为 headless 失败或人工复核时的兜底。VS Code 默认入口仍保留用户确认的 `ROS: Attach`，目标使用 namespace、`Radar_ID`、`radar_pos` 和 binary 联合校验。

原因：用户明确要求先按 `bash start` 运行，再对已出现的 radar1/2/3/4 算法进程进行 debug；headless attach 必须和用户手工 `ROS: Attach` 观察到的是同一进程和同一回放状态。launch-under-GDB 对隔离复现更可控，但会改变启动链和进程生命周期，因此不能作为默认路径。

## ADR-007：运行时任务由 RunSupervisor 持久化

状态：`accepted-for-implementation`

决策：Pi 不持有长时间的 GDB/ROS 过程。`RunSupervisor` 负责 session、checkpoint、poll、resume、retry 和 teardown。

原因：Pi prompt 生命周期和 runtime session 生命周期不同；需要在 Pi 重启或模型超时后继续查询/清理。

## ADR-008：证据不可被 AI 覆盖

状态：`accepted-for-implementation`

决策：AI 只能消费 deterministic artifact，输出 inference/hypothesis/next action，并引用 evidence refs。原始 bag/source/runtime 值不可被 AI 修改。

原因：数据准确性和可审计性优先于自然语言完整性。


## ADR-009：复用 arbe 核心能力，但不复制算法源码

状态：accepted-for-implementation

决策：统一平台通过 adapter 复用 arbe 的 BagReader 回放语义、ROS message/ACK、arbe_visualization_engine 运行时宿主和当前源结构；不把 arbe C/C++ 算法源码复制到 radarAnalyze，也不把 Qt/RViz widget 当成统一 API。

原因：实际服务器调研证明，arbe 已经拥有按 LGU 时间线回放、多 radar 辅助对齐、Scene/Event 模式、处理完成闭环和真实算法输入输出结构。与此同时，这些能力当前耦合在 ROS/Qt/RViz 进程中，PlaySingleFrame 也只是完成确认，不能直接满足独立平台的 headless 控制。

影响：

- 短期增加 ArbeWorkspaceAdapter、ArbeReplayAdapter、GdbRuntimeProvider；
- 只有现有 replay 控制面不足时，才在 arbe 建默认关闭的最小 feature bridge；
- source schema、参数、geometry 和 runtime trace 必须以当前 source/binary 为准；
- 具体复用边界见 CR60_PI_UNIFIED_ARBE_REUSE_ASSESSMENT.md。

## ADR-010：真实用户流程是生产化门禁

状态：accepted-for-implementation

决策：在用户确认从数据、版本、COEM、编译、启动、回放到 VSCode/GDB 的真实步骤之前，只交付 read-only 调研、Sprint1 预检查和接口设计；不把未确认的操作流程编排成自动化生产能力。

原因：仓库结构可以证明代码事实，但不能证明用户实际如何切换环境、定义报警首帧、配置 warm-up、选择 target 和判断正误报。错误的流程假设会导致工具在正确代码上执行错误回放。

验收：真实用户流程确认表中的 P0 问题闭环，至少一条 SGU 和一条 point-cloud 样例可以按文档复现。




## ADR-011：数据优先确定代码和车型上下文

状态：accepted-for-implementation

决策：当前用户流程以数据先传入 Linux 为起点；数据绑定的软件版本、COEM 和具体车型决定 src/algo_source 分支/tag、CUDA 表和配置。工具先读取和验证该绑定，再执行切仓、配置和编译。

材料策略：有 Excel、handoff、目录、日志或源码材料就先读取；材料不足时由 Pi 以对话方式补齐，不要求用户预先准备固定格式。

实现要求：

- 不根据文件名单独猜版本和车型；
- 探测数据身份的实际载体：数据元数据、目录规则、上游 handoff、问题单字段或其他可验证材料；
- 版本到实际 tag/branch 的映射必须写入 provenance；
- 多个来源冲突时阻断并请求确认；
- 完成 source context 后才生成当前代码 schema、参数和 GDB plan。

原因：用户确认数据在工程上与软件版本、COEM 和具体车型唯一绑定。统一工具应把这个绑定作为前置主键，而不是事后再猜测。

## ADR-012：允许操作原 arbe，但每次运行前重新适配接口

状态：accepted-for-implementation

决策：用户允许工具操作原始 arbe workspace，但仓库由其他人维护，后续版本可能发生内部接口变化。假设一次运行从编译前到 runtime 期间代码不变；工具不依赖上一次运行的固定适配结果，而是在每次运行前重新读取当前 source、头文件、COEM、launch/config、编译参数和 binary，重新生成 schema、replay adapter compatibility 和 GDB plan。

最低保护：

- 操作前记录 outer HEAD、algo_source HEAD、dirty diff、配置 hash 和 binary inventory；
- 配置/临时 patch 只写入用户明确授权的目标；
- 不删除旧 CUDA 文件，不覆盖未知 dirty 修改；
- 编译完成后将 source/config/binary fingerprint 固化到当前 run；
- 如果运行中意外发现 fingerprint 变化，标记 source_changed/conflict 并停止生成正式 runtime 结论，但不把它设计成常规并发更新流程；
- 对接口变化优先重新 source learn、重新编译和重新生成 adapter，不能复用旧字段偏移、旧函数签名或旧断点；
- 所有恢复动作写入审计 artifact。

原因：原仓可以减少环境准备成本，但不同版本的内部接口、结构体和调用链可能变化。安全目标不是禁止使用原仓，而是每次运行前重新适配并通过 source/binary/runtime 校验，避免借用 arbe 核心代码时被旧接口假设拖坏。

## ADR-013：报警首帧以 CAN Tx 输出链为最终语义

状态：accepted-for-implementation

决策：本产品默认以 arbe 可视化工具报警灯对应的算法最终输出的 0→非零上升沿作为报警帧口径。工具按当前 source context 动态解析报警灯输入、warning topic/with-frame topic 和算法输出状态；CAN Tx 仅在用户明确要求时作为下游辅助证据。

PEROutput.adasWarning、`/corner_radar/warning_status`、`warning_status_with_frame` 和 UI 状态属于本产品默认的算法报警灯输出链，必须保留各自的来源和 frame 关系。CAN mapping/Tx 仍单独保存，不能把它混入算法输出链或反过来替代算法报警灯状态。

原因：用户实际使用 arbe 报警灯和 `warning_status_with_frame` 定位算法报警帧；完整 CAN mapping 由其他调度链路负责，可能不在同一 host 或同一周期。默认把 CAN 设为必需项会掩盖已有的算法报警事实。

影响：

- event schema 同时保留 algorithm_output_frame、can_tx_frame、selected_first_alarm_frame 和 observation status；
- headless GDB 需要探测实际 RteLite_Write 符号，而不是对 C 宏设置断点；
- 每个代码版本和 COEM 都要重新生成 signal token 和 call chain；
- 默认 HTML 首屏不强调 CAN 是否存在；只有用户明确要求 CAN 侧核验时才显示 CAN 缺口或 CAN 结论。

## ADR-014：Pi 工具以 registerTool 为唯一产品工具契约

状态：`accepted-for-implementation`

决策：每个可由 Pi 调度的能力必须通过 Pi Extension 的 `registerTool` 暴露。工具名称、描述、JSON Schema 和审批元数据由 radarAnalyze catalog 生成；Extension 的执行只经过一个 `pi_tool_bridge`，再委托现有 `BaseTool.safe_execute()` 或 `BaseModule` adapter。不能在 TS Extension 中复制业务逻辑，也不能为 Pi 维护一套与 Python registry 不一致的参数协议。

直接 CLI 仍用于开发/测试和 bridge 的进程边界，但不作为用户必须掌握的编排接口。新能力的完成条件包含：注册表发现、Pi extension 生成、参数转发测试和失败 envelope 测试。

## ADR-015：Pi 编排上下文是不可变 artifact

状态：`accepted-for-implementation`

决策：每次 Pi run 以 `pi-orchestration-context.v1` 绑定 project/variant、case、source/binary、runtime、policy、artifact 引用和 freshness。Pi 可以追加上游工具产生的 artifact 引用，但不能覆盖权威 identity 或 source fingerprint。缺失/冲突进入 `needs_confirmation` 或 `blocked`。

## ADR-016：需求、实现和证据必须可追踪

状态：`accepted-for-implementation`

决策：以 [DDD 用户故事与验收基线](CR60_PI_DDD_REQUIREMENTS_AND_ACCEPTANCE.md) 为开发入口。每次代码或 schema 变更必须关联 US/FR/AC，补充确定性测试和 artifact 证据，并同步更新 Sprint/handoff/AGENTS（适用时）。没有证据的条目只能标记 `specified` 或 `partially-verified`。

## ADR-017：分析过程是一级产品对象

状态：`accepted-for-design`

决策：新增持久化 `AnalysisRun`、`AnalysisStep`、`Claim`、`Hypothesis` 和
`DebugExperiment`。最终 HTML、Pi 总结和 handoff 都是该分析账本的投影，不再把“最终
报告生成成功”视为唯一主流程。

原因：用户明确需要逐步看到数据、代码、条件、缺口、候选原因和实验结果；一次性最终
结论在模型尚未充分校准时既不可靠，也无法帮助人工 debug。

## ADR-018：展示结构化工程理由，不隐藏中间线索

状态：`accepted-for-design`

决策：每条分析结论以 `Claim + Evidence + Assumption + Conflict + Gap + NextExperiment`
表达。平台不展示不可验证的模型原始思维链，但必须显示可被用户核对、质疑和回填的工程
推理摘要。候选根因在 hypothesis board 中经历 open/testing/supported/weakened/rejected，
未满足发布门不得自动升级为最终根因。

## ADR-019：Pi 原子工具使用 capability pack 动态短名单

状态：`accepted-for-design`

决策：保留完整原子 registry 和 `registerTool` 契约，但每个 AnalysisStep 只向 Pi 提供
当前阶段相关的 capability pack、工具摘要和 artifact refs。工具不会重新合并成一个大
诊断器；短名单只是规划层的效率和准确性优化。

原因：Pi-visible 工具已达到 42 个，继续平铺会增加选择噪声、参数错误和上下文成本。

## ADR-020：优先复用 arbe 公共字段，精确帧缺口由 stamped snapshot 补强

状态：`accepted-for-design`

决策：runtime 先消费 arbe 当前已有的 `warning_status_with_frame`、`radar_info` 和
`objectlist`，再按缺口决定 GDB。当前 objectlist 没有算法 frameID，header stamp 是发布
时 `ros::Time::now()`，因此不能只按时间邻近宣称同帧；若该缺口影响结论，优先设计默认
关闭的 `runtime_snapshot_with_frame` bridge，将 frame/radar/ego/object/warning/ROI 和
fingerprint 一次发布。GDB 保留给局部变量、临时状态和调用栈。

## ADR-021：Gen6 项目适配以 ProjectCapabilityManifest 为门禁

状态：`accepted-for-design`

决策：每个项目/车型/source fingerprint 生成 `ProjectCapabilityManifest`，声明数据格式、
功能、输出映射、代码根、参数 provider、回放策略、runtime provider 和展示插件。Pi 只能
消费 manifest 中存在且 freshness 匹配的能力；不允许静默回退到 CR60 Light/FCTA/FCTB
默认。

## ADR-022：一次性 Code Context 与事件路径分离

状态：`accepted-for-implementation`

决策：把当前源码的一次性确定性索引（`code-context-refresh/read`）与某次数据事件的
`event-code-path` 分成两个可组合能力。前者按 source content fingerprint 生成
`code-context.v1`/`code-index.v1`，后者只读取该 snapshot 并绑定事件；两者都不把功能、ROI、
参数或函数名固化在核心代码中。

原因：同一 source/branch 下会分析多条数据，重复全仓扫描既浪费时间又容易造成上下文漂移；
而事件路径需要依赖当前数据选择，不能被一次性代码学习误当成所有数据的结论。source
fingerprint 或项目/variant identity 不匹配时，必须重建/阻断，而不是跨项目复用。

## ADR-023：Pi 正式目录只保留 canonical code-query 能力

状态：`accepted-for-implementation`

决策：`code-analyze` 是 Pi 正式目录中唯一的代码定义/调用/变量/信号查询入口。
历史 `code-query`、`find-code-definition` 和 `extract-ast-dependency` 继续保留给旧 CLI、
AgentLoop 和已有测试，但设置 `expose_to_pi=false`，不再生成 Pi `registerTool`。源码快照
准备（`code-context-refresh/read`）和事件代码路径（`event-code-path`）仍保留，因为它们
分别负责“构建一次 source snapshot”和“绑定一次数据事件/生成 GDB 计划”，不是普通代码查询。

原因：Pi 需要原子能力，但不需要把同一查询能力以多个旧接口重复暴露。兼容入口与正式
产品入口分离，减少工具选择噪声，同时不破坏既有 AgentLoop/CLI。

## ADR-024：远程公共回放迭代既有 sim-verify，不新增平行工具

状态：`accepted-for-implementation`

决策：SSH 短窗口 LGU 回放、公共输出录制和 capture artifact 归入既有
`sim-verify`/`RemoteArbeReplayProvider`；warning/object/frame 的确定性归一化继续由既有
`public-runtime-normalize` 完成。Pi 不新增一个语义重复的 `public-runtime-capture`。

原因：回放属于仿真验证生命周期，归一化属于证据处理；两者可以组合但职责不同。这样
Pi catalog 不继续膨胀，已有 `sim-verify` 的 local trace 模式也保持兼容。

## ADR-025：三种用户出口共享 artifact，不新增总编排器

状态：`accepted-for-implementation`

决策：批量预检查继续由 `cr60-precheck` 负责；事件/帧/字段查询由新增的
`evidence-query` 负责；详细报告由新增的 `diagnosis-report` 负责确定性投影；对话由 Pi
通过这些 leaf capability 组合。报告和对话复用同一 `AnalysisRun`、source/data/runtime
provenance，不再创建一个与 Pi 平行的“万能诊断工具”。

原因：三个用户目标的输入和成本不同，但事实来源必须相同。把查询和报告做成原子能力可以
支持“批量 → 选事件 → 详细报告 → 继续追问”，同时避免把整个大 bundle 或完整 code index
重复塞入 Pi 上下文；AI 诊断结果只作为 inference 输入报告。

实现约束：Pi 普通查询使用有界响应，完整详情落 artifact；source snapshot 不一致时报告
blocked；Pi session 使用 AnalysisRun ID 恢复，tool 调用摘要进入 ledger，不保存隐藏思维链。

## 3. 开放决策

| 编号 | 问题 | 当前建议 | 需要谁确认 |
|---|---|---|---|
| O-01 | 共享 contract 是否单独建第三仓 | 初期 JSON 文件，稳定后再抽 `cr60-contracts` | 维护者 |
| O-02 | runtime GDB 是本地控制器还是 Linux worker | 初期本地 Pi/控制器经 SSH，复杂后 Linux worker | 系统负责人 |
| O-03 | 是否允许直接改远程 arbe | 用户已允许；仍需阶段性 approval、workspace lock 和 fingerprint 变化检测 | 用户/维护者 |
| O-04 | `HILMODEL=2` 与 SGU macro 的最终判据 | source + compile log + binary/runtime preflight 三者 | 仿真负责人 |
| O-05 | 正式 GUI replay 是否提供 API | 无 API 时先 direct rosbag/launch-under-GDB | arbe 维护者 |
| O-06 | runtime probe 是否进入 arbe feature branch | headless GDB 优先；GDB 采样不足时再加默认关闭 bridge | 用户/仓维护者 |
| O-07 | geometry 的车型原点是否统一 | 每 variant 从 source/profile/runtime 校验 | 算法负责人 |
