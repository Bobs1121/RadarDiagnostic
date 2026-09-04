# CR60 / radarAnalyze / arbe / Pi 统一平台调研报告

版本：`research.v1`  
日期：`2026-08-26`  
状态：设计输入基线，未授权远程执行  
适用范围：CR60/BYD 角雷达数据分析、arbe 回放、SGU 目标注入、点云仿真、GDB 运行时调试和 Pi 编排

> 本文件采用 docu dev 模式维护。后续 PRD、系统设计、软件设计、实施方案、Sprint 计划和 handoff 都必须以此为依据；新仓、分支、车型或服务器产生新事实时，应追加新的调研版本，不覆盖历史结论。

## 1. 证据等级

| 标记 | 含义 |
|---|---|
| `observed` | 从当前仓库、source snapshot、脚本、报告或运行输出中直接看到 |
| `derived` | 根据已观察的代码/数据关系推导，但不是运行时直接采集 |
| `runtime_required` | 必须启动实际 arbe/ROS/GDB 才能确认 |
| `open` | 当前信息不足，必须由用户或运行环境补充 |

硬约束：`derived` 和 `runtime_required` 不能被写成 `observed_runtime`。所有结果都要保留来源、source hash、binary hash、frame 来源、映射关系和缺口。

## 2. 调研范围和仓库关系

| 仓库/材料 | 位置 | 结论性职责 |
|---|---|---|
| `radarAnalyze` | `D:/RamboStar/idea/radarAnalyze` | Pi 入口、能力注册、确定性分析、代码图、记忆和统一编排 |
| `cr60-debug-harness` | `D:/RamboStar/idea/cr60-debug-harness` | Sprint1 bag/BLF 预检查、source schema、事件/目标/index、viewer-model、HTML |
| `cr60_light_arbe` | 用户指定的 Linux workspace | 正式可视化、ROS 回放、算法运行和被测系统 |
| `src/algo_source` | `cr60_light_arbe` 子仓 | 数据版本对应的算法/COEM/车型源码 |
| `bosch-data-transfert` | [GitHub skill](https://github.com/Bobs1121/skillForJob/tree/main/skills/bosch-data-transfert) | 数据解析、TR/版本/车型确认、服务器落盘和下游 handoff |
| `cr60light-arbe-build` | [GitHub skill](https://github.com/Bobs1121/skillForJob/tree/main/skills/cr60light-arbe-build) | algo_source 切 tag、CUDA/车型配置、仿真补丁、编译和启动 |

已检查的设计材料包括两个前置 skill 的 `SKILL.md`、`references/environment.md`、profile 模板和脚本，以及两个项目的架构、控制/数据面、运行时 Debug、Pi 边界、Sprint1、Sprint roadmap 和 V4 文档。

## 3. 前置 skill 调研

### 3.1 `bosch-data-transfert`

已覆盖流程：数据源（Excel/UNC/本地/清单）→解析 TR、路径、版本→Linux 目录准备→拷贝/重试/大小校验→版本/tag 候选→交给 arbe build。

Excel 默认字段为：B 列 TR 号、J 列数据路径、G 列版本。脚本支持 UNC 到 `/mnt/cluster` 映射、目录批量发现 `.bag/.blf`、缺扩展名尝试、同尺寸幂等跳过和失败统计。

必须保留的行为：

- 服务器、车型、tag、CUDA、落盘目录不明确时停止并询问；
- AI 只能提出候选及依据，影响编译和结果的候选必须经用户确认；
- 数据源不可达、文件缺失、版本映射失败都进入结构化缺口；
- 不重复实现数据复制器。

统一平台应注册 `bosch_data_prepare`，调用或复用该 skill 的执行实现，输出 `cr60-analysis-intake.v1`。handoff 至少包含 TR、原始/远程路径、文件格式、size/hash、版本和车型候选、用户确认、数据可达性及下游 harness profile。

### 3.2 `cr60light-arbe-build`

已覆盖流程：确认 arbe workspace→algo_source checkout tag/branch→在目标 tag 中读取实际 CUDA→更新 `launch_config_4radars.yaml`→核对/应用仿真补丁→`catkin_make`→`bash start`。

关键配置通常位于：`xlsx_path` 第 53 行、`xlsx_sheet` 第 54 行、`car.type` 第 75 行。

不能固化：workspace 路径、目标 tag、checkout 后 CUDA 文件名、COEM/sheet、`visualization_node.cpp` 接口、`BUILDMODEL/HILMODEL`、是否已有 replay 补丁以及 dirty 状态。

特别是 `taskTime` 补丁，必须先检查当前仓是否已经适配，不能无条件再次修改。

统一平台将它拆成风险不同的工具：`arbe_context_probe`、`arbe_version_resolve`、`arbe_cuda_resolve`、`arbe_patch_plan`、`arbe_apply_patch`、`arbe_build`、`arbe_start`。其中后四者要有副作用标记和人工确认门。

## 4. cr60-debug-harness Sprint1 调研

### 4.1 已有能力

Sprint1 已经形成确定性预检查链路：topic/type inventory→warning event extraction→radar/frame/time mapping→target candidate selection→source snapshot/code index/runtime schema→parameter/ROI projection→breakpoint pack→`diagnosis-bundle.v1`→`viewer-model.v1`→独立 HTML 和 batch index。

已保留的关键身份：warning topic index、LGU message index、`wfAutosarData.frameID`、raw SGU index、algorithm object index、objectlist index、function/side/radar ID 和 target object ID。

已支持一条数据多个功能报警以及同一功能多次报警。

### 4.2 硬边界

Sprint1 不负责远程 checkout、车型/CUDA 修改、编译、启动、GUI 操作、`rosbag play`、GDB attach、运行时局部变量采集，也不把静态推导冒充算法实际输出。

即使由 Pi 调用，也必须保持 Sprint1 只读；运行时动作只能进入独立的 DebugSession。

### 4.3 当前几何缺口

当前 HTML 图存在真实的几何证据缺口：

1. 自车框简单从 `x=0` 画到 `vehicle_length`，没有使用后轴中心原点和 `bumper2RearAxle_dist`；
2. 目标框虽复现 `adasObjPloyCal()` 的旋转矩形公式，但不是运行时实际 `objPoly`；
3. ROI 是 source-derived/参数投影，不是运行时 `adasRoi->leftFctaRoi/rightFctaRoi`；
4. `fIntAng`、`fInterX`、`fInterY`、`fTTMX`、`fTTMXObj`、`fTTMY`、`fDDCI` 没有统一 runtime 快照；
5. `radar_id`、`radar_pos`、安装偏角和坐标系没有在图中形成完整证据链；
6. 缺少运行时矩形和 ROI 时，正式碰撞结论必须为 `not_evaluated`。

截至 2026-09-01 的实现状态：同帧 GDB polygon/ROI 已可计算并标记
`observed_intersects/observed_disjoint`；无 runtime polygon 时，source-derived polygon/ROI
可计算但只标记 `source_derived_intersects/source_derived_disjoint`，并在图中标出来源和四角，
不升级为功能报警 verdict。上述第 4/5 项的 runtime 字段和坐标身份缺口仍然存在。

## 5. radarAnalyze 调研

### 5.1 可复用底座

当前已有 `PiModule/PiBridge`、`ReActPlanner/AgentLoop`、`MODULE_REGISTRY/TOOL_REGISTRY`、`CapabilityRegistry`、`BaseModule/ModuleResult`、`ArtifactRegistry`、project/variant 隔离、freshness/knowledge guard、DataProvider 方向、CodeGraph/AST/regex、signal-extract、data-analyze、code-analyze、diag、sim-verify 和 req-analyze。

统一平台不应另起 Pi、会话、工具注册、记忆或 freshness 体系。

### 5.2 当前限制

Pi RPC 适合意图、规划和工具调用；长时间的 ROS/GDB 任务不能塞进一次 prompt。必须增加持久化 `OrchestrationRun/RunSupervisor`，管理 GDB/ROS 生命周期、人工确认、轮询、重试、恢复和 teardown。

`sim-verify` 应继续负责 trace/KPI 解析和验证；远程构建、启动、回放、GDB 应由独立 Provider 负责。

## 6. 当前 arbe source snapshot 事实

以下事实来自当前 source snapshot，换 branch/tag/COEM 后必须重新生成 `analysis-context.v1`。

### 6.1 HILMODEL=2 / SGU

当前 `paraDefine.h` 中存在 `#define BUILDMODEL 2` 和 `#define HILMODEL 2`。

`visualization_node.cpp` 中，回调先把 `frame_counter` 赋为 `msg->frameID`，再把 `msg->outputData` 转为 `PERInfoOutStruct`。HIL 路径遍历 `mAlgoPerOutputPtr->objTrans[i]`，跳过空 SGU，按非空顺序写入 `algo_objInfo.trcOutData[k]`，随后调用 `PostProcessMainTI(..., frame_counter, ..., &algo_objInfo, ...)`。

因此必须分别保留 `raw_sgu_index=i` 和 `algorithm_object_index=k`。

当前 `adasFunc.c` 多个功能在 `HILMODEL == 2` 下执行 `JudgeIsOutFOVEgloAxis()`，在 `HILMODEL != 0` 下重算 `sObj.velAbsX/velAbsY`。SGU 注入不是无条件直接报警，仍会经过 FOV、目标筛选、ROI、TTC/DDCI、计数器和保持逻辑。

### 6.2 FCTA 几何链

当前代码关系为：`ResetFctaRoi`（`adasFunc.c:2695`）→`adasObjPloyCal`（`commonTool.c:6063`）→`FrontCrossTrafficAlertAndBrake`（`adasFunc.c:9889`）→`FctaDirectRunning`/`FctaTurning`→FCTA/FCTB handler。

`ResetFctaRoi()` 消费 `g_egoCarAddInfo.carSpd`、`g_egoCarAddInfo.yawRate`、`g_egoCarFixPara.bumper2RearAxle_dist`、`g_egoCarFixPara.vehicle_width` 和 `g_curvature_radius`。它的直行 ROI 纵向位置使用前保险杠到后轴的距离。

`adasObjPloyCal()` 使用 `distX/distY/length/width/yawAng` 生成目标四角。要证明当前算法真正使用的矩形，应在运行时采集 `objPoly.points[0..3]`。

### 6.3 播放器同步

`PlaySingleFrame.srv` 是算法对播放器的处理确认，包含 `radar_pos`、`frame_id` 和 `status`；`status=0` 表示收到输入，`status=1` 表示当前帧处理完成。它不是通用 load/play/seek API。

正式 GUI 没有稳定的外部 load/play/seek 控制面，但用户确认的实际运行链是 `bash start` 后使用 `ROS: Attach`。运行时 MVP 应优先复用这条标准启动链并对就绪的 visualization_engine 做 headless attach；仅在 existing PID attach 受限时，才使用隔离 ROS master、launch-under-GDB 和 direct rosbag play。

## 7. 统一证据和状态结论

统一平台至少需要支持这些状态：`observed_bag`、`observed_runtime`、`derived_from_active_source`、`derived_runtime_mapping`、`not_logged`、`runtime_probe_required`、`optimized_out`、`source_mismatch`、`binary_source_mismatch`、`frame_mismatch`、`coordinate_contract_missing`。

语义如下：

- `observed_bag`：从 bag/BLF 直接解码，可以作为数据事实；
- `observed_runtime`：当前进程在当前帧、当前二进制中被 GDB/探针直接观察到；
- `derived_from_active_source`：用当前源码和输入计算，不是运行时快照；
- `derived_runtime_mapping`：由 index/调用关系推导，不是独立信号；
- `not_logged`：代码可能存在，但当前数据层没有这个值；
- `optimized_out`：编译优化后 GDB 无法获得，相关结论必须阻塞；
- `source_mismatch`/`binary_source_mismatch`：代码和运行实体不一致，不能静默降级；
- `frame_mismatch`：数据时间接近但不是同一个算法 frame；
- `coordinate_contract_missing`：坐标原点、轴向、安装偏角或单位没有证据。

## 8. 已识别的架构风险

| 风险 | 现象 | 设计对策 |
|---|---|---|
| skill 和统一工具重复实现 | 前置流程分叉，修复不一致 | skill 作为 Provider/适配器的执行来源 |
| Pi 直接执行任意 shell | 误切分支、误编译、误停进程 | allowlist、参数 schema、风险等级、人工确认 |
| Sprint1 和 runtime 混合 | 静态值被误标成 runtime | bundle 和 runtime trace 分离 |
| `radar_id` 与 `radar_pos` 混淆 | 左右、安装位置和 FOV 错误 | 两个字段独立记录和校验 |
| 只画矩形不采算法 ROI | 视觉重叠被误判为碰撞 | 采 `objPoly`、`adasRoi` 和 `fInter*` |
| 用 time-near objectlist 补 runtime | 目标和帧跨层混合 | same-frame/same-layer gate |
| 标准进程 attach 失败 | ptrace 或父子进程权限限制 | preflight 后由用户确认 launch-under-GDB |
| GDB 停顿改变实时行为 | 回放时序受扰动 | tracepoint/轻量采样并记录扰动 |
| 代码/二进制不匹配 | 行号和变量含义错误 | source hash + binary hash 门禁 |
| 多项目旧知识串扰 | 旧参数/ROI 被复用 | variant、commit、freshness fail-closed |

## 9. 仍需现场验证的开放项

以下内容不能用当前本地 snapshot 代替实际服务器验证：

- 实际 Linux 服务器和 arbe workspace；
- outer arbe 与 `src/algo_source` 当前 branch/commit/dirty；
- 实际二进制路径、PID、debug symbols、strip 状态；
- `ptrace_scope` 和 attach 权限；
- `HILMODEL=2` 是否进入最终编译产物；
- `PF_BUILD_FUNTEST_SGU_INJECTION` 是否启用；
- GUI 是否已有可用 replay shim；
- runtime `adasRoi`、`objPoly` 和算法输出结构的真实值；
- GDB 停顿对回放时序的影响；
- 不同车型的自车原点、车身边界和 ROI 坐标契约。

这些开放项必须由 `runtime_preflight` 输出，不能由设计文档默认填充。

## 10. 调研后的架构决策

1. `radarAnalyze/pi` 是统一入口和任务编排中枢；
2. `cr60-debug-harness` 保持独立，作为 Sprint1 确定性分析 Provider；
3. `bosch-data-transfert` 和 `cr60light-arbe-build` 作为受控前置能力复用，不复制脚本实现；
4. `sim-verify` 只消费和验证 trace/KPI，不拥有全部远程执行生命周期；
5. SGU/HILMODEL=2 与 point-cloud replay 是两套独立 Replay Strategy；
6. geometry 是独立 evidence capability，不能继续只放在前端临时公式中；
7. runtime GDB 由 `RunSupervisor` 管理，Pi 只负责计划、确认和调度；
8. 跨仓通过 JSON/JSONL artifact contract，不直接共享可变内部对象；
9. AI 只做意图、调度、解释和假设排序；
10. 新项目/新分支/新车型必须刷新 source schema、参数、几何契约和运行时策略。

## 11. 文档维护规则

- 新发现事实：追加到本报告的“现场验证记录”或新版本报告，不修改历史事实；
- 新架构决策：写入 ADR/决策章节，同时更新 PRD 和软件设计；
- 新工具接口：同步更新模块设计、软件设计和 schema；
- 新远程副作用：更新风险、权限和审批说明；
- 新 Sprint 验收：更新 Sprint 计划和 handoff；
- 运行时结果必须保留 `run_id`、source/binary/data fingerprint 和 artifact 路径。


## 12. 2026-08-26 实际服务器 arbe 核心调研补充

本次通过 SSH 只读检查了服务器 10.190.171.44 的 /home/hoz2wx/CR60LIGHT/cr60_light_arbe。外层 HEAD 为 4c171298b2c3583509ea9e3da222b90ba0a9e513，src/algo_source 子仓 HEAD 为 a81b08a38f316a3d25bfcbcad6dcfc822d24b990。两层均存在未提交改动；本次没有执行 checkout、编译、启动、停止或写入。

### 12.1 可以复用的三个核心能力

1. arbe_gui/CMakeLists.txt 把 visualization_node.cpp、对称 perception 算法源码和当前 COEM 源码编译进同一个 arbe_visualization_engine。COEM_NAME 从 launch_config_4radars.yaml 的 car.type 解析，当前 target 设置 BUILDMODEL=2。这使 arbe_visualization_engine 成为实际算法宿主，不只是 UI。
2. my_rviz_plugin::BagReader 已经实现 LGU 时间线、单事件回放、Scene Mode、多雷达辅助数据匹配、按 bag 时间节拍和 PlaySingleFrame 完成等待。
3. PERInfoOutStruct、objOutDataStruct、adasROIStruct 和 PostProcessMainTI 形成了真实算法输入/输出边界，可作为每次 source context 动态生成 schema 的依据。

### 12.2 关键限制

- BagReader API 目前只存在于 Qt/RViz plugin 内部，不是独立 headless RPC。
- PlaySingleFrame.srv 只表达 radar_pos + frame_id + status 的处理确认，不是 load/play/seek/pause API。
- HIL 路径将 objTrans[i] 非空项压缩写到 trcOutData[k]，所以 raw_sgu_index=i 和 algorithm_object_index=k 必须分开记录。
- HILMODEL=2 下 point/filter/cluster/track 分支被绕过，但 AdasFunc 仍执行目标 FOV、筛选、ROI、TTC/DDCI、计数器和报警状态逻辑。
- debugOutput.c 的 CSV 可补充 tracking、point、object、ego、ADAS、calibration、BLD、CFAR、RD，但有固定历史路径、全局开关和条件编译限制，不能替代局部 runtime 变量。
- 现有播放器和 warning 映射包含固定 topic、slot 和 15 路报警布局，适合做当前 arbe adapter profile，不适合上升为统一平台的全局业务规则。

### 12.3 复用决策

统一工具采用“独立 radarAnalyze + arbe 适配器 + 可选 runtime bridge + 外部 GDB provider”：

- 不复制 arbe C/C++ 算法源码到 radarAnalyze；
- 不在 Python 中复制固定 C struct；
- 通过 adapter 复用播放器、消息和 ACK 语义；
- 通过 GDB 获取 ROS 无法暴露的局部变量、静态状态和调用栈；
- 只有现有控制面不足时，才在 arbe 建最小 feature branch bridge；
- runtime overlay 不覆盖 Sprint1 静态 bundle。

详细证据和复用表见 [arbe 核心能力复用调研](technical/CR60_PI_UNIFIED_ARBE_REUSE_ASSESSMENT.md)。

## 13. 真实用户流程仍需确认

本节保留首轮提出的问题清单；用户已经给出的主流程答案和新增代码证据见第 14–16 节，未确认的实现细节仍然有效。

为了避免从仓库结构反推错误的工程流程，已新增 [真实用户流程确认表](technical/CR60_PI_UNIFIED_USER_WORKFLOW_QUESTIONNAIRE.md)。首轮必须确认：

- 从数据到 branch/COEM/编译/启动/播放/debug 的实际顺序；
- SGU/HILMODEL=2 和 point-cloud 150–200 帧 warm-up 的实际操作；
- 报警第一帧、多功能、多次报警和侧别的业务定义；
- VSCode ROS: attach 的真实 target、进程、权限和 source mapping；
- frameID、frame_counter、objID、i/k 的实际对应关系；
- ego 原点、雷达坐标、ROI 及运行时参数的工程真值；
- 未来用户的输入、自动化审批点、服务器隔离和验收样例。


## 14. 用户确认的实际主流程（2026-08-26）

用户已确认当前主流程不是先打开 GUI 再人工寻找数据，而是：

1. 先把数据传到 Linux 服务器；
2. 根据数据绑定的软件版本切换 src/algo_source 子仓分支/tag；
3. 数据唯一确定所属 COEM 和具体车型；
4. 在 arbe 中更新对应 CUDA 表、车型配置和其他参数；
5. 编译外层主仓；
6. 执行 bash start；
7. 导入数据并播放；
8. 使用 VSCode 的 ROS: Attach，等待 arbe_visualization_engine 进程出现后选择对应 radar1/2/3/4；
9. 优先由 headless GDB 获取中间变量并写入 HTML。

新增的用户语义约束：

- 有材料先读取材料；没有材料时采用对话补齐，最终将相关内容归一到同一个 intake；
- 原则上上述操作全部自动化，关键阶段一次性确认；
- SGU/HILMODEL=2 模式按实际算法 frameID 预热 3–5 帧；
- point-cloud 仍使用按代码周期和 frameID 定义的 150–200 帧预热策略；
- 报警第一帧定义为算法向 CAN 信号输出报警位的 0→非零上升沿；
- 原始 arbe workspace 可以被工具操作，但仓库由其他人维护，后续运行之间可能发生接口变化；每次运行前重新适配，运行期间默认不变。

### 14.1 VSCode 和 radar 进程事实

服务器当前 .vscode/launch.json 的默认入口包括：

- ROS: Attach：type=ros、request=attach；
- ROS: Launch：目标为 .../arbe_gui/launch/rviz-arbe.launch；
- 运行程序为 devel/lib/arbe_phoenix_radar_driver/arbe_visualization_engine；
- 进程选择使用 command:pickProcess。

arbe_radar_vis.launch 将算法节点放在类似以下 namespace 中：

~~~text
/radar1_visualization_engine/arbe_visualization_engine
/radar2_visualization_engine/arbe_visualization_engine
/radar3_visualization_engine/arbe_visualization_engine
/radar4_visualization_engine/arbe_visualization_engine
~~~

因此 runtime provider 必须以 namespace + Radar_ID + radar_pos + binary path 联合选择目标，不能只按进程 basename 选择。

### 14.2 仍需确认

用户已经确认了业务操作顺序，但以下内容仍需工具从数据/仓库和首个实际 case 中验证：

- 数据软件版本、COEM、车型身份具体位于数据目录、元数据、问题单还是上游 handoff；
- 软件版本映射到子仓 branch/tag 的精确规则；
- 当前 CAN 输出位与 adasWarningStruct/ROS warning 的字段对应；
- 3–5 帧是否对所有 SGU 功能、车型和 radar 相同；
- 不同运行之间接口变化时，重新 source learn、重新编译和重新生成 plan 的具体策略；
- headless GDB 对当前 arbe_visualization_engine 的权限、符号、优化和时序扰动。


## 15. 报警输出信号链和首帧口径补充

本次从当前服务器源代码确认了两条不同的报警来源：

### 15.1 仿真算法侧

arbe_visualization_engine/visualization_node.cpp 在同一帧后处理流程中：

1. 从 algo_adasWarning 组装 /corner_radar/warning_status；
2. 将 radar_id、frame_counter 和 15 路 warning 状态组装成 /corner_radar/warning_status_with_frame；
3. 继续发布 radar_info 和 PlaySingleFrame 完成 ACK。

当前 with-frame 数据布局为：

    data[0]  = radar_id
    data[1]  = frame_counter
    data[2]  = bLeftBsdWarning
    ...
    data[13] = bLeftFctaWarning
    data[14] = bRightFctaWarning
    data[15] = bLeftFctbWarning
    data[16] = bRightFctbWarning

因此，对于 arbe 仿真中的“算法输出第一帧”，首选：

    /corner_radar/warning_status_with_frame

事件检测规则是同一 radar、同一 warning field 在相邻算法 frame 中从 0 变为非零；event 的第一帧直接使用 data[1] 的 frame_counter，不通过 bag 时间近似反推。

### 15.2 真实 CAN 解码侧

common_can_warning_publisher/scripts/canfd_publisher_node.py 是另一条链路：

    Kvaser CAN-FD → DBC decode → warning_topic

当前脚本默认的 warning_topic 是：

    /corner_radar/warning_status_raw

它将真实 ECU CAN 报文解码成 radar_id + 15 路 warning。该节点不是算法推理节点，不能用于证明 PostProcessMainTI 内部条件已经满足。

### 15.3 统一工具的来源优先级

| 任务 | 首选来源 | 辅助来源 | 不能混用 |
|---|---|---|---|
| arbe 仿真算法首帧 | /corner_radar/warning_status_with_frame | /corner_radar/warning_status + 同帧映射 | 不能用 raw CAN 代替算法 frame |
| 实车/录制 CAN 首帧 | /corner_radar/warning_status_raw 或当前数据中的 CAN 解码 | 算法侧 warning（若存在） | 不能把 ECU 输入写成算法输出 |
| 算法与 ECU 差异 | 两条链分别建 event，再按 radar/frame/time 做 correlation | handoff/人工标注 | 不能写入同一个 source 字段 |

如果 with-frame 话题不存在，工具可以使用 warning_status 与当前 LGU frame 的映射，但必须降级为 derived_runtime_mapping；如果只能获得 raw CAN，则只生成 CAN-side event，不声称算法内部首帧已确认。

## 16. 算法报警到 CAN Tx 的实际链路补充

本次继续检查了当前 BYD_UKE source：

    dataFilterMain.c::perception_run
        → perception_run_internal
        → PostProcessMainTI
        → PEROutput.adasWarning

完整 ASW/CAN 调度链在另一个调度入口：

    OsTask_MMW.c
        → Algo_Perception
        → ASWOUT_OutCalc_RadarWarnSignal
        → RteComMapping_TxRunnable
        → RteComMapping_TxRunnable_FuncSignal
        → RteComMapping_WriteSignal(...)
        → Com_SendSignal / CAN Tx

当前可视化回灌入口 visualization_node.cpp 的 corner_radar_post_process_data_callback() 直接调用 PostProcessMainTI，随后将 algo_adasWarning 打包发布为：

    /corner_radar/warning_status
    /corner_radar/warning_status_with_frame

在该可视化回调中没有发现 ADAS_Core_Process 或 RteComMapping_TxRunnable 的调用。因此，当前 arbe visualization host 默认能证明的是“算法输出结构/ROS 仿真代理在该 frame 变化”，不能仅凭该 topic 证明最终物理 CAN Tx 已发送。

### 16.1 首帧证据策略

统一工具按以下优先级处理用户所说的“CAN 输出报警第一帧”：

1. 当前运行时能命中真实 CAN Tx 映射函数，或 bag 中存在可对齐的实际 CAN Tx 报文：使用 CAN Tx 信号的 0→非零上升沿；
2. 当前 arbe visualization host 只能观测到 PEROutput.adasWarning / warning_status_with_frame：使用算法输出上升沿，但标记 can_tx_unobserved；
3. 只有无 frame 的 warning_status：结合 LGU frame 映射，标记 derived_runtime_mapping；
4. 只有近似时间的 UI/对象列表：不能生成最终 CAN 首帧。

报告要同时保存：

    algorithm_output_frame
    can_tx_frame
    hmi_or_ros_frame
    selected_first_alarm_frame
    first_alarm_definition
    can_tx_observation_status

其中 selected_first_alarm_frame 只有在 CAN Tx evidence 存在时才称为 CAN 首帧；否则明确称为 algorithm proxy frame。

### 16.2 对 runtime provider 的影响

GDB 计划必须先探测当前 binary 是否真正包含并执行：

    RteComMapping_TxRunnable_FuncSignal
    RteComMapping_WriteSignal
    RteLite_Write_<actual_signal_token>
    Com_SendSignal

`RteComMapping_WriteSignal(signal_name)` 在当前头文件中是宏，会展开为 `RteLite_Write_<signal_name>`。因此 GDB 断点生成器必须从当前源码解析实际 signal token，不能直接把宏名作为函数断点。

如果实际 `RteLite_Write_<actual_signal_token>`/`Com_SendSignal` 断点从未命中，工具不能把 warning_status_with_frame 改名为 CAN Tx；应在 HTML 中给出：

    CAN Tx not observed in current arbe visualization host.
    Algorithm output frame is available as a proxy.

这条差异必须随代码版本重新探测，因为不同 COEM、构建方式和 host 可能包含不同的 ASW/BSW 调度。



## 17. 数据版本/车型绑定的新增证据

在服务器 `~/CR60LIGHT/data/BYD_CR60LT_功能问题清单.xlsx` 中实际读取到：

- B 列：Ticket No.；
- C 列：触发功能；
- E 列：车型；
- G 列：问题触发版本；
- J 列：数据路径或数据说明。

例如 `CRGVI-1829` 的样例行包含车型 `QZHCX`、版本 `BL03RC02.7_S` 以及对应 corner radar bag 路径；服务器落盘目录为 `data/qzh/CRGVI-1829/`。这证明当前数据准备流程存在“问题单/数据路径 → 车型/软件版本 → 子仓 tag → CUDA/config”的上游绑定材料。

但不能据此假设所有未来用户的数据都带同样的 Excel。工具应支持 Excel、handoff、目录元数据和用户确认四种来源，并把实际来源写入 data_binding_source；没有可验证载体时阻断自动切仓。

另外，服务器 handoff 中把 `PlaySingleFrame` 说明为可控制 frame player 的接口，与当前 `BagReader`/`MyRvizPlugin` 源码证据不一致。统一设计以当前 active source 为准，并将 handoff 作为历史材料记录 conflict。

## 18. 首个真实远程预检与输入绑定实现证据

### 18.1 只读远程预检

2026-08-26 在本地 `radarAnalyze` 中通过 SSH 对 `10.190.171.44` 的
`/home/hoz2wx/CR60LIGHT/cr60_light_arbe` 执行了 `arbe-preflight.v1`。本次没有
checkout、copy、配置写入、编译、`bash start`、GDB attach 或进程停止；服务器当时
已有运行中的 arbe，因此只验证了“已启动状态下的发现能力”。结果 artifact：

    outputs/arbe_preflight_20260826.json

关键结果：

| 项目 | 观测值 |
|---|---|
| outer HEAD | `4c171298b2c3583509ea9e3da222b90ba0a9e513` |
| `src/algo_source` HEAD | `a81b08a38f316a3d25bfcbcad6dcfc822d24b990` |
| COEM | `BYD_UKE` |
| CUDA 表 | `CUDA_BYD_UKE_Bundle_V2.0.xlsx` |
| CUDA sheet | `03_QZH` |
| build macros | `BUILDMODEL=2`, `HILMODEL=2` |
| visualization targets | `radar1..4`，PID `3662013/3662064/3662071/3662012`（PID 可能随运行变化） |
| GDB | `/usr/bin/gdb`，`ptrace_scope=1` |
| binary candidates | 1 个 `arbe_visualization_engine` |
| CAN source candidates | 110 个信号 token/源码链路候选 |

进程命令行有时不包含 ROS namespace，当前实现增加了从 rosout 日志名
`radarN_visualization_engine-...` 的发现回退；这只用于选中目标 PID，不能替代
`Radar_ID`/`radar_pos` 的坐标语义校验。

### 18.2 材料优先输入绑定

新增确定性能力 `cr60-intake`，输出 `cr60-analysis-intake.v1`：

- 输入可以是数据路径、材料文件/目录和显式确认字段；
- XLSX 识别当前问题清单 B/C/E/G/J 契约，优先按真实表头识别；
- 多行问题清单必须按 `--match`、Ticket 或数据文件名选行，不能把整表误当一条数据；
- 每个值保留来源、locator、解析方法、优先级和 authoritative 标记，材料保留 SHA-256；
- 车型、COEM、软件版本或分支冲突时返回 `needs_confirmation`，不选择“看起来最像”的值；
- `/home/...` 或 UNC 路径在本地只标记 `remote_unverified`，存在性和 checksum 留给数据传输 adapter；
- 不含数据路径时返回 `blocked_missing_input`；缺少安全绑定字段时返回 `needs_confirmation`；
- 该能力不执行任何远程副作用，后续工具只能消费用户确认后的 intake artifact。

实现位置：`engines/arbe/intake.py`、`ai/modules/cr60_intake.py`；契约位置：
`contracts/cr60-analysis-intake.v1.schema.json`；本地测试覆盖 JSON/XLSX、冲突、远程
路径、CLI 和 artifact 写出。

## 19. 逐帧自车/目标信号的真实可视化来源（新增探测）

### 19.1 `wfAutosarData` 是最可靠的无 GDB 帧锚点

当前 `visualization_node.cpp::corner_radar_post_process_data_callback()` 直接接收：

    /wf/corner_radar/lgu_data_<radar_id>
    type: arbe_msgs/wfAutosarData

该消息自身包含 `frameID`、`LGUNum`、`SGUNum`、`uintData[]`、`floatData[]` 和
`outputData[]`。回调将 `outputData` 转成当前源代码版本的 `PERInfoOutStruct`：

    mAlgoPerOutputPtr->egoCarInfoTrans
    mAlgoPerOutputPtr->objTrans[i]
    mAlgoPerOutputPtr->ADASInfoTrans
    mAlgoPerOutputPtr->calibInfoTrans

随后 HIL 路径将 `objTrans[i]` 映射为 `algo_objInfo.trcOutData[k]`；`i` 是 raw SGU
数组索引，`k` 是算法对象数组索引，二者不能合并。只要当前 bag、消息定义和 source
layout 一致，读取这条消息不需要 GDB，且 `frameID` 是真实回灌帧号。这是“公共逐帧
证据”原子工具的首选来源。

### 19.2 可视化节点发布了哪些逐帧公共输出

当前远程源代码确认：

| Topic | 类型/载荷 | 可确认内容 | 关键缺口 |
|---|---|---|---|
| `/wf/objectlist_<id>` | `arbe_msgs/wfObjectMsg` | 算法对象的 ID、`objID`、位置、尺寸、yaw、速度、RCS、TTC/DDCI、8 类对象报警 flag | 消息没有 `frameID`；字段是 `objInfo->trcOutData[i]` 的显示子集 |
| `/wf/rviz/objects_<id>` | `visualization_msgs/MarkerArray` | GUI 当前绘制的算法目标框、yaw 姿态和标签 | 纯显示层，不是完整算法对象；Marker 时间是 `ros::Time::now()` |
| `/corner_radar/radar_info` | `Float32MultiArray[9]` | `data[0..8]`=radar ID、`algo_EgoCarInfo.actual_spd`、yaw rate、detections、`frame_counter`、frame interval、BLD flag/percent、mileage | 只有摘要；`wfObjectMsg` 需通过回调顺序/时间与 frame 间接配对 |
| `/corner_radar/warning_status_with_frame` | `UInt32MultiArray[17]` | radar ID、`frame_counter`、15 路算法 warning 位 | 证明的是 visualization host 的算法输出；若 CAN Tx 未执行，不能改称最终 CAN 首帧 |
| `/corner_radar/rviz/*Area_<id>` | `MarkerArray` | 当前 `algo_adasRoi` 的 ROI marker | 仅轮廓点；需保存 source/runtime 来源和单位，不能把 marker 当完整 ROI 结构 |

当前源还新增了独立 RAW SGU 显示：`update_raw_sgu_display_cache()` 只读取
`objTrans[i]` 的一组字段，`publish_raw_sgu_object_list()` 以
`ID=1000000+raw_obj_id` 追加到显示消息，并用 `wf_radar_<id>_raw_sgu` marker namespace
绘制。它不会写入 `algo_objInfo`，因此适合作为输入/输出对照，但不能当成算法内部
`trcOutData[k]`。

### 19.3 GUI 中“自车信号表”的实际来源并不等同于 bag 回放

当前 `viewpanel.cpp` 的 Ego Info 表订阅：

    /wf/xcp_signals/front_left/parsed
    /wf/xcp_signals/front_right/parsed

表格使用的是 `arbe_msgs::egoCarInfo`，包含 `actual_gear`、`car_spd`、`yaw_rate`、
功能状态/使能、ESP/车门、4 个 `trc_*` 对象字段等很多字段。其配套的
`common_xcp_info_publisher/scripts/canfd_sgu_pub.py` 通过 A2L + Kvaser CAN-FD XCP
读取 `g_egoCarAddInfo.*`、`PEROutput.adasWarning` 和 `PEROutput.objInfo.trcOutData`
的地址，默认按 50 Hz 发布。这个路径是 live XCP 内存采集，不携带算法 `frameID`，
`header.stamp` 是采集主机的 `ros::Time::now()`；没有验证关联时不能声称它就是某个
bag 回放帧的自车/目标真值。

另一路 `rviz_bag` 的 `my_rviz_plugin.cpp` 从 bag 读取
`/wf/xcp_signals/*/parsed`，但当前消息类型是
`common_xcp_info_publisher_rvizbag/XcpEgoInfo`，实际定义只有：

    g_bsd_disable_flg
    g_rct_disable_flg
    g_area_static_dot_over_flg

远程当前 master 实测：该 topic 类型为 `XcpEgoInfo` 且当时 `Publishers: None`；
`arbe_msgs/egoCarInfo` 与它的 ROS MD5 也不同。因此 GUI 的完整 Ego Info 表不能被
自动当作 bag 播放时的逐帧完整自车信号；必须记录 topic type、publisher、source 和
frame correlation，缺失时明确 `not_available`。

同一次 `ros-topic-inventory` 对当前运行态的完整盘点还显示：4 条
`/wf/corner_radar/lgu_data_1..4` 都是 `arbe_msgs/wfAutosarData`，但当时 publisher
为 0（播放器未在该瞬间发布）；4 条 `/wf/objectlist_1..4` 均由对应
`radarN_visualization_engine` 发布；`/corner_radar/warning_status_with_frame` 有
4 个 visualization publisher；`/corner_radar/rviz/FctaArea_2` 有 radar2 publisher；
4 条 XCP parsed topic 均无 publisher。由此可见，topic 注册存在、GUI 能订阅和当前
确实有逐帧数据是三个不同状态，工具必须分别输出 `publisher_count` 与
`data_observable`。

当前实现的 `ros-topic-inventory` 是只读盘点，`public-topic-plan` 是证据通道计划，
`public-evidence-audit` 是对已有 bundle 的审计；尚未实现持续的 live `rosbag record`
或 ROS subscriber collector。因此 `data_observable=true` 只能证明当前存在 publisher，
不能被解释为工具已经保存了对应回放的逐帧运行输出。

### 19.4 无 GDB 与 GDB 的分工结论

不通过 GDB 可以可靠获得：

1. bag 中每帧的 `wfAutosarData.frameID`；
2. 当前 source layout 能解码的 `egoCarInfoTrans`、raw `objTrans[i]`、ADAS enable、
   calibration/BLD 输入；
3. visualization callback 发布的算法对象显示子集、ROI marker、算法 warning 和
   `radar_info` 摘要；
4. 若 bag 确实包含并能解码，公共 XCP/CAN/车辆状态消息的原始值。

仍需 GDB 或显式 `debug_probe` 才能可靠获得：

1. `g_egoCarAddInfo` 经 `CalEgoCarAddInfo_CR()` 后的派生值；
2. `sObj`、`objPoly`、`fInterX/Y`、`fTTMX`、计数器、局部 gate 和真实 `i` 作用域；
3. 只有运行时产生、没有写入 ROS/CSV 的中间状态；
4. 当前 visualization host 是否真正执行 `RteComMapping_TxRunnable` → `RteLite_Write_*`
   → `Com_SendSignal` 的最终 CAN Tx。

`debugOutput.c` 虽有 `_out/_Ego/_Adas/_Calib` 等输出设计，但当前代码扫描到
`g_flgSaveToFile` 默认关闭、历史固定目录和版本相关字段；它只能作为一个独立的
`debug_csv_provider`，不能在公共证据工具中默认打开或把旧 CSV 当当前 runtime 真值。

### 19.5 原子工具的直接设计输入

上述事实形成四个互不绑定的原子工具：

    ros-topic-inventory
      → 只读获取 topic/type/publisher/subscriber/frame-key
    lgu_frame_decoder
      → 按当前 source/message layout 解码 wfAutosarData，保留 frameID/i/k
    public-evidence-audit
      → 采集/解析 objectlist、radar_info、warning_with_frame、ROI/Marker
    gdb_session
      → 只提供通用 attach/break/continue/snapshot/stack/detach 服务

代码分析工具另行生成 `code-evidence` 和 GDB 命令建议；GDB 工具不认识 FCTA/FCTB，
也不内置任何固定断点。Pi 只根据上一个工具的 artifact 选择下一个工具，并在
`public` 与 `runtime_gdb` 两种 evidence layer 之间保留 provenance/冲突。

## 20. 原子工具首版实现与验证记录

2026-08-26 已在 `radarAnalyze` 落地以下能力：

| 工具 | 实现 | 本次验证 |
|---|---|---|
| `public-topic-plan` | `engines/arbe/public_evidence.py` + `ai/modules/public_topic_plan.py` | 使用当前 harness TOML、远程 preflight、runtime schema，生成 4 radar 的 LGU/object/warning/ROI 通道计划 |
| `public-evidence-audit` | `audit_public_bundle()` + `ai/modules/public_evidence_audit.py` | 对真实 `CRGVI-1829_ALT_2026-07-18` bundle 得到 9173 条逐帧行、9173 个显式 `wfAutosarData.frameID`、23 个回灌 ego 字段，并保持 CAN Tx 未观测 |
| `code-gdb-plan` | `engines/code_gdb_plan.py` + `ai/modules/code_gdb_plan.py` | 从当前 code index 解析 `FrontCrossTrafficAlertAndBrake` 的真实文件/行号/条件；用显式 `line=10094` 保证 `objInfo->trcOutData[i]`、`fTTMX/fDDCI` 位于目标作用域附近，函数入口风险仍被记录 |
| `gdb-service` | `engines/gdb_service.py` + `ai/modules/gdb_service.py` | 消费上一工具生成的 10 条 commands，生成远程 `/usr/bin/gdb` SSH argv；只做计划，`execute=false`，未 attach |
| `ros-topic-inventory` | `engines/arbe/ros_inventory.py` + `ai/modules/ros_topic_inventory.py` | 对当前运行 ROS master 只读采集 topic/type/publisher/subscriber；验证 4 条 LGU 当时无 publisher、4 条 objectlist 有对应 publisher、`warning_status_with_frame` 有 4 个 visualization publisher、4 条 live/bag XCP topic 当时无 publisher |

验证 artifact：

    outputs/public_topic_plan_20260826.json
    outputs/public_evidence_audit_CRGVI1829_ALT_20260826_v3.json
    outputs/code_gdb_plan_CRGVI1829.json
    outputs/gdb_session_plan_CRGVI1829.json
    outputs/ros_topic_inventory_full_20260826.json

截至 2026-08-26 的专项测试为 `72 passed`（前置、输入、harness adapter、公共证据、代码→GDB、GDB 审批
和 AgentLoop 桥）。该历史节点尚未执行真实 GDB attach；这是有意保留的边界，执行需在
`bash start`、PID/binary/source identity 校验和用户确认后由 supervisor 放行。

随后对同一 `CRGVI-1829_ALT_2026-07-18` 重新生成了 harness 输出目录
`pi_adapter_acceptance_CRGVI1829_ALT_20260826_v2`，验证 decoder v2 的 counter 修复：仍为
`ready`、34 个事件；FCTA/FCTB 报警 flag 仍在 `warning_flags`，但
`frame_precheck.debug_frame_range` 现在是
`status=not_available, reason=internal_warning_counter_not_present_in_public_object`，
不再把 flag=5 伪造为内部 counter transition。该修复在 `cr60-debug-harness` 的全量
测试中通过。

进一步按 `perception_public_api.h` 修正了 `objOutStrunct` 的字段布局（恢复
`historyMovDist`，使 velocity/TTC/DDCI 不再错位），decoder 升级为 v3；随后同一数据
使用新代码重跑，后续以 v3 产物为准。v2 目录仍保留作为中间修复证据。

v3 真实 bundle 的 `decoder_contract` 为
`arbe_PERInfoOutStruct_debug_tail_v3`、`object_size=36`、`max_sgu=16`；审计得到的
逐帧 ego 字段从 12 个扩展为 23 个（含转向灯、四门、validity、轮速有效性、方向符号、
雨刷和 mileage）。这类扩展来自当前 C 结构布局，不是 HTML 层自定义字段。

随后又把 decoder contract 接到 `BatchAnalyzer`：`schema_builder` 从当前
`runtime_schema/code_index` 校验 25 个 compressed object 字段、29 个 ego 字段和
`LGU_OUT_NUM_SGU`；只有 `status=source_resolved` 才把 format/offset 作为参数传入
远端 `REMOTE_ANALYZER`。当前 source mismatch 会在读取 bag 前阻断，不再静默用旧布局。
真实 v4 验收目录为
`pi_adapter_acceptance_CRGVI1829_ALT_20260826_v4`，bundle 中确认
`decoder_status=source_resolved`、`source_snapshot_hash` 与 code context 一致。

## 21. 2026-08-27 真实执行验收

在不修改正式 arbe workspace、不切换子仓、不执行 `catkin_make`/`bash start` 的前提下，
完成了当前环境的只读和隔离 runtime 验收。

### 21.1 当前正式环境 preflight

- server：`10.190.171.44`，workspace：`/home/hoz2wx/CR60LIGHT/cr60_light_arbe`；
- outer HEAD：`4c171298b2c3583509ea9e3da222b90ba0a9e513`；algo HEAD：
  `a81b08a38f316a3d25bfcbcad6dcfc822d24b990`；两者均保持 dirty/detached 事实；
- `COEM=BYD_UKE`、`xlsx=CUDA_BYD_UKE_Bundle_V2.0.xlsx`、sheet=`03_QZH`、
  `BUILDMODEL=2`、`HILMODEL=2`；
- 当前 binary 含 debug sections、未 strip，SHA-256 为
  `93a8f2b2c11a6d8ba1abadbc7eb480e8867352f261a71c4bb5023f4c4ef80890`；
- 正式 master `11311` 的 radar1..4 visualization 进程仍在；本次隔离测试没有复用或
  attach 它们。

Artifact：[arbe_preflight_20260827.json](../outputs/arbe_preflight_20260827.json) ·
[arbe_runtime_identity_20260827.json](../outputs/arbe_runtime_identity_20260827.json)

### 21.2 公共无 GDB 路径

`ros-topic-inventory --sample-once` 对 `lgu_data_2`、`objectlist_2`、`radar_info`、
`warning_status`、`warning_status_with_frame` 和 XCP parsed topic 执行了有界单消息采样。
结果是部分 topic 存在 publisher，但 2 秒采样窗口都没有收到消息；这证明当前正式
`bash start` 环境处于等待回放状态，不能把 publisher 存在当成数据已流动。

随后在独立 ROS master `11321` 上执行无 GDB direct replay，真实 bag 为：

`/home/hoz2wx/CR60LIGHT/data/qzh/CRGVI-1829/corner_radar_net_2026-07-19-11-56-15_11.bag`

结果：`PLAY_RC=0`，公共 `/corner_radar/warning_status_with_frame` 捕获
`WARNING_NONZERO_COUNT=15`，非零 warning 行覆盖 `frame 47875..47886`，远程临时日志
自动清理。完整日志：[public_isolated_smoke_20260827_v3.log](../outputs/public_isolated_smoke_20260827_v3.log)。

### 21.3 GDB 精细路径

在独立 ROS master `11322` 上用正式 ELF 做 launch-under-GDB，目标同一 bag、`radar2`、
`frame 47877`，结果：

- `PLAY_RC=0`；`GDB_HIT_COUNT=1`；
- `DEBUG_HIT frame=47877 radar=2`；
- 命中函数：`FrontCrossTrafficAlertAndBrake`、`FctaDirectRunning`、
  `HandleFctaRightWarningFlag`、`HandleFctbRightWarningFlag`；
- `g_egoCarAddInfo.carSpd=4.42844534`、`actual_gear=4`、
  `bFctaDetectFlg=true`、`bFctbDetectFlg=true`；
- `objID=44`、`distX=5.98999977`、`distY=-4.71000004`、
  `length=4.75`、`width=1.84000003`、`yawAng=53.0400009`；
- `fTTC=1.01999998`、`fDDCI=8.38000011`、`fInterX=8.34897423`、
  `fInterY=0`；`objPoly.num=4`，四角由 GDB 直接读出；
- `objInfo->trcOutData` 中目标 `i=0`，右 FCTA/FCTB 状态为 2，目标 warning flags 为 5；
- 远程隔离 master、算法和 GDB 进程已清理，正式 `11311` 的 4 个节点保持不变。

完整日志：[gdb_isolated_smoke_20260827_v2.log](../outputs/gdb_isolated_smoke_20260827_v2.log)。
合并摘要：[runtime_smoke_evidence_20260827.json](../outputs/runtime_smoke_evidence_20260827.json)。

### 21.4 发现和未完成项

- 当前 bag 含 LGU stream，`replay.strategy=auto` 已修正为 `sgu_injection`，静态 bundle
  的 34 个事件均使用 `5/5` 帧 warm-up；点云输入才使用 `150..200` 帧；
- raw warning topic 没有 frame 字段，因此静态 bundle 的 `28905/47877` 等 frame 仍要
  按证据标为时间对齐或 runtime 精确命中，不能混称；
- 隔离 launch-under-GDB 已证明实际 runtime 链可运行，但它是当前 smoke adapter；正式
  通用 DebugSession/连续 MI2/runtime HTML 仍未完成；
- `ros-topic-inventory` 当前已能做单消息采样，但持续 live collector/`rosbag record`
  尚未实现；
- 正式 workspace dirty，且本次没有进行 branch/tag checkout、CUDA 写入、编译、`bash start`
  或正式 PID attach；这些动作仍需输入确认和审批门。

### 21.5 文件夹批量验收

对 `/home/hoz2wx/CR60LIGHT/data/qzh/CRGVI-1829` 执行 `folder-analyze`，工具自动发现
5 条 bag，逐条生成独立 bundle、viewer-model、HTML、CSV 和 VS Code handoff：

```text
case_count=5
ready_count=5
failed_count=0
unsupported_count=0
blocked_count=0
total_event_count=149
```

5 条数据均检测到 LGU stream，自动选择 `sgu_injection`，每个事件均为 `5/5` warm-up。
该结果证明文件夹批量和每数据隔离输出链路可用，但不证明这些数据的软件版本一定相同；
若上游材料显示版本/车型/COEM 不同，必须先拆分 context 再分析。

## 22. 2026-08-27 DDD 与 Pi tool 机制复核

### 22.1 复核结论

本次自审确认：原有材料已经有 PRD、调研、ADR、模块/软件设计、实施和 Sprint
文档，但缺少一份正式的“用户故事 → Given/When/Then → 实现 → 测试 → 现场证据”
基线。已新增
[CR60_PI_DDD_REQUIREMENTS_AND_ACCEPTANCE.md](technical/CR60_PI_DDD_REQUIREMENTS_AND_ACCEPTANCE.md)，
形成 `US-001..US-014`，并明确 `specified`、`implemented`、`partially-verified`、
`accepted`、`blocked` 的含义。

结论不是“所有需求已经完成”：当前 PRD/DDD 仍是可执行基线，正式 arbe 工作区的
checkout/CUDA/build/start/existing-PID attach、point-cloud runtime、live collector
和 runtime HTML merge 仍需单独验收。没有用户确认的目标 branch/tag/车型绑定时，不能
把隔离 smoke 说成正式生产流程。

### 22.2 Pi 入口和工具链实际纠偏

发现并修正了两项会影响 Pi 真实使用的实现问题：

1. 旧 `gen_pi_extension.py` 生成的 `registerTool.execute` 没有把 `params` 传入
   subprocess，实际工具可能收到空参数；现改为独立 JSON argv：
   `--name <name> --params JSON.stringify(params ?? {})`。
2. 旧 generator 让 module/tool 各自调用不同 CLI，且 `PiBridge` 没有显式加载当前
   project extension；现统一为 `registerTool → pi_tool_bridge → BaseTool.safe_execute /
   BaseModule adapter`，PiBridge 自动刷新并显式 `--extension` 加载当前项目生成物，
   默认关闭 Pi 内置工具，避免绕过统一审批 envelope。

新增 `pi-orchestration-context.v1` 和 `pi-context`：把 intake/preflight、project/
variant、case、source/binary、runtime、policy、freshness 和 artifact refs 绑定为
不可由 LLM 覆盖的上下文。上下文不从路径名称猜测车型、COEM、branch、雷达或 runtime
值；缺失/冲突输出 partial/blocked。

复核发现部分历史 `BaseModule` 没有显式 `input_schema`，这会造成 Pi 工具“可注册但
参数为空”。现由 catalog 从真实 `run()` 签名和 `register_cli()` 声明生成保守 schema，
并由 `ModuleToolAdapter` 复用已有 `from_cli_args`，因此 BSD 的 MF4 路径、signal-audit
的 BLF 路径、code-learn 的 source/db 路径等构造期输入不会被 Pi 丢掉；新模块仍必须
显式声明 schema。

### 22.3 实际 Pi 验收

- 本机 `pi --list-models` 当前有效的精确条目是
  `bosch-qwen3_6 / Qwen3.5-27B-FP16`；旧材料中的 `bosch-qwen35` 别名已失效。
- `python scripts/pi_rpc_smoke.py --timeout 20`：通过，返回
  `status=success/evidence=agent_settled`，Pi RPC 事件数 15。
- Pi tool 真实调用：通过 `PiBridge` + 当前生成 extension + Bosch provider，模型实际
 产生 `tool_execution_start/end`，工具名为 `pi-context`，返回 `TOOL_CALLED`，
  `status=ok`，事件数 32；说明不是只有 catalog 文件存在，而是参数可以穿过 Pi
  Extension/bridge 并执行。
- Windows 进程清理：改为直接启动 Node entry，并验证 smoke 后没有遗留本次
  `pi-coding-agent --mode rpc --extension radar-capabilities.ts` 或
  `computer-use bridge` 子进程。

对应代码：`ai/pi_bridge.py`、`scripts/gen_pi_extension.py`、
`ai/capability/pi_tool_bridge.py`、`engines/pi_context.py`、
`ai/modules/pi_context.py`；对应测试：`tests/test_pi_context.py`、
`tests/test_pi_tool_bridge.py`。

### 22.4 Pi 的长期边界

Pi 是产品入口和总体编排器，但不是确定性真值层。正式链路固定为：

```text
Pi registerTool
  → pi_tool_bridge
    → BaseTool/BaseModule adapter
      → deterministic engine/provider
        → bag/source/ROS/GDB/arbe
```

`AgentLoop`/`ReActPlanner`/直接 module CLI 保留用于开发、离线和故障兜底；它们不再
被设计成与 Pi 并列的用户产品流程。任何 side effect 仍需 supervisor approval，
Pi extension 不携带 `--allow-execution`。

### 22.5 入口/超时回归补充

- 直接执行 `python cli.py pi --question ... --case-dir cases/FCTA001
  --provider bosch-qwen3_6 --model Qwen3.5-27B-FP16`，返回
  `ok / pi: agent_settled / FINAL_SCHEMA_PI_TOOL_CALLED`，最新一次事件数 31；该结果覆盖了
  `PiModule → PiBridge → generated Extension → pi-context → pi_tool_bridge` 的正式
  用户入口，而不只是直接调用 Python bridge。
- PiBridge 已将 RPC stdout 读取改为 daemon reader + bounded queue，timeout 不再被
  阻塞式 `readline()` 失效；无输出专测通过，50 ms timeout 实际小于 1 s。
- 入口测试结束后检查没有遗留本次 Pi RPC 或 `computer-use bridge` 进程。

## 23. 2026-08-27 指定 FCTB bag 的 radarAnalyze 实际分析

### 23.1 输入和当前 source context

输入 bag：

```text
/home/hoz2wx/CR60LIGHT/data/qzh/CRGVI-1829/corner_radar_net_2026-07-19-11-56-15_11.bag
```

通过 `radarAnalyze/ai/modules/cr60_precheck.py` 调用 sibling
`cr60-debug-harness`，使用当前重新生成的 context：

```text
source_context_id: 0762176290744b4bf189d50238b0962bc093ca6c58f70fbaf5f1ce5b38f22660
source_snapshot_hash: d75fd296200dd1ab1e3713509f6f4506ff742bfc232b2cb327e10289eee37c8e
outer: develop_LGU_Simulation / dirty
algo_source: detached HEAD / dirty
COEM: BYD_UKE
CUDA sheet: 03_QZH
HILMODEL: 2
```

此次没有 checkout、CUDA 写入、`catkin_make`、`bash start` 或正式 PID attach；dirty
状态保留在 bundle 中，因此这是当前代码快照下的静态预检查，不是 clean build 结论。

### 23.2 数据发现结果

结果为 `status=ready`、`case_count=1`、`event_count=28`，报告并没有只解析 FCTB：

```text
BSD_L: 7
LCA_L: 7
BSD_R: 6
LCA_R: 6
FCTB_L / radar1: 1
FCTA_R / radar2: 1
```

当前 bag 的 raw warning topic 是 `/corner_radar/warning_status_raw`，没有携带显式
frame ID。因此所有静态“首帧”都是 `first_observed_warning_nearest_lgu`，置信度
`time_aligned_not_frame_exact`，不能称作已经从 CAN Tx 上升沿精确观测到的算法首帧。

### 23.3 与 FCTB 直接相关的两条事实链

#### FCTB_L / radar1

```text
event: recorded_raw:FCTB_L:radar1:519.327431
raw warning time: 519.327431..522.925759 s
same-radar LGU frame: 47840
LGU message index: 7853
time delta: 0.019704 s
target source: no selected target
same-radar object candidate count: 0
debug frame range: not_available / no_selected_numeric_object
```

在 `frame_evidence` 的 `frameID=47840` 及其临近帧中，能读到自车输入：速度约
`4.43 m/s`、挡位 `4`、方向盘角约 `2.9°`，并且 `fcta/fctb enable=true`；但该
FCTB_L 事件对应的 radar1 公共对象帧没有可用于绑定 FCTB 的目标对象。不能把
radar2 的 `objID=44` 作为 radar1 的 FCTB 目标。

为人工 debug 生成的当前源码条件包括：

```text
postProcess.c:170   frameID == 47840
adasFunc.c:9987     frame_counter == 47840
commonTool.c:6063   frame_counter == 47840
adasFunc.c:6360     frame_counter == 47840   # objID 未由静态证据确定
adasFunc.c:7773     frame_counter == 47840
```

由于没有同帧数字对象 ID，工具没有伪造 `sObj->objID == 44`；实际报告中的
`HandleFctbLeftWarningFlag` watch 包含真实源码变量 `i`、`warningNum`、
`objInfo->trcOutData[i].objFctbWarningFlag` 和 `leftFctbFlag`，需要 runtime/GDB
才能确定真正的 `i`。

#### FCTA_R / radar2 中的 objID=44

这是一条独立的 radar2 事件，不是 FCTB_L/radar1 的目标替代品：

```text
event: recorded_raw:FCTA_R:radar2:519.376635
same-radar LGU frame: 47877
LGU message index: 7858
time delta: 0.001172 s
objectlist message index: 7860
trc_index_i: 1
objID/objUnqID: 44/44
position: (6.15, -4.12)
velocity: (0.29, 4.44)
length/width: 4.75 / 1.84
yaw_angle: 51.17 deg
TTC/DDCI: 1.00 / 8.29
objFctaWarningFlag/objFctbWarningFlag: 5 / 5
functions on object: FCTA, FCTB
```

这条链说明 radar2 公共对象中确实存在同时带 FCTA/FCTB flag 的 `objID=44`；它支持
后续对 radar2 的 FCTA/FCTB runtime 分析，但不能证明 radar1 的 FCTB_L 事件由同一个
目标触发。

### 23.4 当前判断边界

目前可以确定：

1. bag 中确实存在 `FCTB_L/radar1` raw warning 事件；
2. bag 中也存在独立的 `FCTA_R/radar2` 事件，且 radar2 对象 `44` 的公共属性同时有
   FCTA/FCTB warning flag；
3. 隔离 launch-under-GDB 已能按当前 profile 正确切换 radar1/radar2，并在 radar1 的
   `frame_counter=47840` 读取到 `i=0/1/2`、`objID=39/30/16`；这三个对象的
   `objFctbWarningFlag` 都没有进入正报警状态，因此不能用它们替代 raw `FCTB_L` 事件的
   目标；
4. 对 radar2 的 runtime replay，在 `frameID=47875` 观测到 `HandleFctbRightWarningFlag`
   的 `i=0` 为 `objID=44`，并出现 `objFctbWarningFlag` 从拷贝快照 4 到
   `objInfo->trcOutData[i]` 5 的更新；同一窗口的 `warning_status_with_frame` 从
   `frameID=47875` 开始出现 `bRightFctaWarning=2`、`bRightFctbWarning=2`；
5. 报警 raw topic 无 frame ID，47840/47877 仍是 nearest-LGU 时间对齐帧，不是已证明的
   CAN Tx 上升沿帧；`47875` 是当前隔离 replay 的算法输出上升沿候选，需与真实 CAN Tx
   映射继续分层；
6. 当前 bundle 仍不能下“正报/误报”或“FCTB/perception/situation 根因”的最终结论，
   但已经从静态证据推进到当前 ELF/当前回放的 runtime 事实和冲突证据。

### 23.5 runtime 几何与预热验证

在 `radar2/frame47875`，GDB 读取到当前代码实际使用的 ROI 与目标多边形：

```text
rightFctaRoi.num = 10
rightFctaRoi: x=3.86919975..8.64912415, y=-1.0855..0
objID=44 polygon:
  (6.50448799,-2.61333227)
  (3.73940563,-6.47556210)
  (5.23551178,-7.54666758)
  (8.00059414,-3.68443775)
target yawAng=54.4000015 deg
fInterX=8.44471264, fInterY=0, fTTC=1.02, fDDCI=8.38
```

目标当前四角并不落在 `rightFctaRoi` 的即时矩形内；但是当前代码在
`FrontCrossTrafficAlertAndBrake` 中把 `rightFlag` 设为 `rightFctaRoi->num > 0`，随后由
`FctaDirectRunning` 通过目标朝向、目标多边形边界、预测交点和 TTM/DDCI 继续判断。因而
“当前框未覆盖 ROI”不能直接判定为绘图错误或误报；viewer 必须区分“当前几何包含”和
“预测轨迹交点”，不能只绘制一个 ROI 矩形给人做结论。

同一目标用两种回放窗口复现：长窗口 `start_sec=516` 与短窗口 `start_sec=518.9`
（目标前约 5 帧）。两次均 `PLAY_RC=0`、`warning_status_with_frame` 非零 15 次，均
命中 `objID=44/i=0`、输出对象 flag 4→5；但 `FrontCrossTrafficAlertAndBrake` 的
`radius` 分别为 `884.086304` 和 `1149.37061`。这证明 SGU/LGU 默认 3–5 帧可以作为
回放策略，却不能无条件当作 runtime 派生状态等价；工具必须执行 warm-up sensitivity
检查并保留状态漂移，而不是把点云的 150–200 帧规则套到 SGU。

### 23.6 对通用工具框架的修正

本次发现不作为 `CRGVI-1829` 特例固化，转化为以下跨功能设计规则：

1. runtime provider 接受 `radar_id`、当前 source/runtime schema、输入策略和输出信号
   契约，不在代码中固定 FCTA/FCTB 或固定雷达；
2. 事件模型至少保留 `recorded_raw`、`replay_algorithm`、`runtime_with_frame`、
   `gdb_observation` 四个 evidence layer，所有层按 data/source/binary/frame provenance
   关联但不互相覆盖；
3. 输出上升沿优先从当前代码实际发布的 with-frame/最终 Tx 观察，raw 无 frame 时只能
   做时间对齐；algorithm object flag、warning counter 和 CAN Tx 必须是不同字段；
4. GDB trace 必须记录对象循环的 `i`，并在存在拷贝/回写时同时记录 snapshot 与 array
   字段；禁止因为 `sObj` 是旧快照而丢失状态转换；
5. 几何 provider 输出当前 polygon/ROI、坐标系、即时 containment、预测交点和公式，
   不把 `ROI.num > 0` 解释成目标已经在 ROI 内；
6. warm-up provider 依据当前数据输入类型选择 SGU/LGU 或 point-cloud 策略，支持多窗口
   对比、漂移诊断和可审计回退；
7. Pi 只编排和解释结构化证据；代码、数据、版本、权限和副作用由确定性 provider 与
   supervisor 管理，用户交互只询问业务目标、证据偏好和是否允许受控运行，不询问用户
   不熟悉的 frame/ROI/GDB 技术细节。

详细机器证据：[runtime_fctb_case_evidence_20260827.json](../outputs/runtime_fctb_case_evidence_20260827.json)。

### 23.7 本次报告入口

统一平台生成的独立报告：

```text
D:/RamboStar/idea/radarAnalyze/outputs/radar_project_fctb_CRGVI1829_20260827/data/CRGVI-1829/report.html
```

机器证据：

```text
D:/RamboStar/idea/radarAnalyze/outputs/radar_project_fctb_CRGVI1829_20260827/cases/CRGVI-1829/diagnosis_bundle.json
D:/RamboStar/idea/radarAnalyze/outputs/radar_project_fctb_CRGVI1829_20260827/cases/CRGVI-1829/alarm_events.csv
D:/RamboStar/idea/radarAnalyze/outputs/radar_project_fctb_CRGVI1829_20260827/cases/CRGVI-1829/vscode_handoff.json
D:/RamboStar/idea/radarAnalyze/outputs/radar_project_fctb_CRGVI1829_20260827/cases/CRGVI-1829/runtime_schema.json
D:/RamboStar/idea/radarAnalyze/outputs/runtime_fctb_case_evidence_20260827.json
D:/RamboStar/idea/radarAnalyze/outputs/gdb_fctb_radar1_20260827_v2.log
D:/RamboStar/idea/radarAnalyze/outputs/gdb_fctb_radar2_frame47875_final_20260827.log
D:/RamboStar/idea/radarAnalyze/outputs/gdb_fctb_radar2_frame47875_warmup5_20260827.log
```

### 23.8 静态逐帧 viewer 实现验收

基于本次 bundle，`viewer-model.v1` 已增加事件窗口内的 `timeline.frames`：

```text
all event-window frames: 2634
FCTB_L/radar1: 90 frames, ego 90/90, objects 0
FCTA_R/radar2: 50 frames, ego 50/50, objects 20
FCTA_R selected frame: 47877, object 44
```

每个静态 frame 都保留实际 `wfAutosarData.frameID`、时间、topic、ego 字段值、当前帧全部
目标、`objID`/索引、yaw/四角、目标运动值和当前帧 ROI 投影。代码 token、源码行号和大体量
调用链改为事件级/根级复用，frame 只保存轻量值数组和必要的 token override，避免逐帧复制
source metadata。真实模型约 53 MB，模型投影约 21 秒，报告刷新约 30 秒。

页面新增 frame slider、前后帧按钮和当前 frame/目标数显示；切换 frame 会同时更新中间
几何图、ego 属性、事件目标属性和 ROI。目标在当前帧缺失时显示 `No target in this frame`，
不会沿用上一帧。Vite build、sibling harness 全量测试（39 项）和 viewer model 单元测试
均通过；当前浏览器自动 DOM 验收受本地 `file://` 页面安全策略阻止，需用户在打开报告后
手工拖动 slider 做最终视觉确认。

该能力属于 Sprint1 静态证据展示，不等于 runtime GDB 变量。静态 frame 中的
`g_egoCarAddInfo`、内部 counter、运行时 `objPoly/adasRoi` 仍按
`runtime_probe_required` 或 `not_available` 标记；它们由后续 runtime overlay 补齐。

### 23.9 2026-08-30 上游 source/CUDA 只读解析验证

为避免把上游 `bosch-data-transfert` / `cr60light-arbe-build` 的流程复制成另一套
容易漂移的脚本，本轮把“当前 source/ref”和“当前车型 CUDA/config”拆成两个 Pi 原子
只读能力。详细交接见
[CR60_PI_UNIFIED_HANDOFF_2026-08-30_ARBE_SOURCE_CUDA_READONLY.md](technical/CR60_PI_UNIFIED_HANDOFF_2026-08-30_ARBE_SOURCE_CUDA_READONLY.md)。

真实验证目标仍是：

```text
10.190.171.44
/home/hoz2wx/CR60LIGHT/cr60_light_arbe
/home/hoz2wx/CR60LIGHT/cr60_light_arbe/src/algo_source
```

`arbe-source-resolve` 使用显式映射
`software_version=BL03RC02.7_S`、`ref_prefix=BYD_UKE_`、
`version_suffix_strip=_S` 得到 `BYD_UKE_BL03RC02.7`。远端当前 source 为
`a81b08a38f316a3d25bfcbcad6dcfc822d24b990`，exact tag、local tag、remote tag 均与该
ref 对齐；但 `dirty=yes`，因此结果是 `partial`，工具没有 checkout/fetch。

`arbe-cuda-resolve` 从当前 source 的
`coem/BYD_UKE/tools/container_input/08_CustData` 扫描到
`CUDA_BYD_UKE_Bundle_V2.0.xlsx`，size=`52295`，sha256=
`a555d8a5a86e7a26c6671f9eb8838d6f4e360d803219a7b6fad71360ea315856`。当前 YAML 第
53/54/75 行分别是该 xlsx、`03_QZH`、`BYD_UKE`，alignment=`aligned`，结果 `ready`。

新增的通用约束：

1. 版本到 ref 的映射必须由当前输入/项目 profile 显式提供，工具不内置某个车型前缀；
2. source dirty、intake blocked、ref 冲突和未找到候选必须结构化返回，不能默默继续写入；
3. CUDA 候选必须来自当前 source 扫描并带完整路径、mtime、size、sha256；
4. 只读解析的 `selected` 不是写入授权，后续 checkout、复制 CUDA、更新 YAML、编译和
   `bash start` 必须在同一 PiRunContext 中重新校验并走独立 approval。

### 23.10 2026-08-30 仿真补丁计划的现场校验

新增 `arbe-patch-plan` 后，对同一远程工作区执行了默认上游检查。第一次“分别查找
`PostProcessMainTI` 和 `taskTime`”的判断被现场源代码证伪：
`visualization_node.cpp` 中虽然存在 `uint8_t taskTime = 1U`，但实际
`PostProcessMainTI(...)` 调用尾部仍为 `3,3`。因此默认规则已收紧为必须同时发现真实
`taskTime, taskTime` 调用参数；单独存在函数名或局部变量不能通过。

现场结果写入 `outputs/arbe_patch_plan_current_20260830_v4.json`：

- outer HEAD=`4c171298b2c3583509ea9e3da222b90ba0a9e513`，branch=`develop_LGU_Simulation`，
  dirty=`yes`；
- algo HEAD=`a81b08a38f316a3d25bfcbcad6dcfc822d24b990`，detached，dirty=`yes`；
- `BUILDMODEL=2`、`HILMODEL=2` 的当前行存在，但它们位于 dirty diff 中；
- GUI `taskTime, taskTime` required check=`missing`；
- `PF_BUILD_FUNTEST_SGU_INJECTION` 在当前文件中只有 `#ifdef` 引用，没有被识别为已定义；
- 总体状态=`needs_action`，工具没有修改任何远程文件。

这个结果强化了通用设计原则：补丁检查必须验证“实际调用/定义语义”，不能只用关键词
命中；所有 dirty diff 都必须进入下一步 approval gate。后续如果某个代码版本改变了文件
路径或函数签名，Pi 应传入新的 `checks` 配置，或者把检查标为不适用，而不是复用旧规则。

### 23.11 2026-08-30 数据传输前只读校验

为保持“数据先进入 Linux，再绑定代码/车型”的顺序，新增
`cr60-data-prep-verify`。它复用 `bosch-data-transfert` 的路径语义，但不复制作业脚本的
复制动作：Linux absolute 路径原样检查，UNC 路径必须由显式 `source_prefix` 映射，
Windows 盘符、relative path 或缺少 mount 都进入 `needs_confirmation`。每条数据记录
原始路径、映射规则、case/entry index、文件名、size、mtime 和 SHA-256；可选比较目标
目录的同名文件 size/hash。

针对当前 CRGVI-1829 bag 的实际验证结果为 `ready`：远程文件存在，size=
`1087066183` bytes，sha256=`241e732ada70dd809894d3bed5f3f6603358c0ea5cd45f6204ab11628d11e18c`。
该结果只证明 Linux source file 可读且内容身份已固化，不等于已经完成传输。真正的
copy/rsync 仍属于上游 skill adapter 的 approval-gated 副作用能力。

随后将 `/home/hoz2wx/CR60LIGHT/data/qzh/CRGVI-1829` 作为目录输入验证目录分支，实际
发现 5 个 `.bag` 并全部读取 size/mtime/SHA-256，结果为 `ready`。因此该能力不只支持
单文件，也能为后续“一个目录→多条数据→逐条报告”的流程提供传输前清单；目标目录
校验和真正复制仍保持独立步骤。

在此基础上新增 `cr60-data-transfer`。它不是第二个复制器，而是一个受审批的远端脚本
adapter：Pi/用户必须提供已部署的 `data_transfert.py` 路径、远端输入清单或 XLSX、目标
目录和 source type；工具先返回完整命令与副作用说明，只有 `execute=true + approved=true`
才通过 SSH 调用上游脚本。执行结束仍强制建议 `cr60-data-prep-verify` 做目标 hash 校验。
本轮没有在真实服务器执行传输，原因是当前需求只提供了已落盘 bag 和现有 arbe 工作区，
没有给出本次要写入的目标目录及远端脚本部署路径；工具不自行猜测。

### 23.12 2026-08-30 产品架构复盘结论

结合当前 radarAnalyze/debug-harness 实现、用户工作方式和最新 arbe 源码，当前 Pi + 原子
工具 + 独立 harness + arbe adapter 的方向保持不变；主要缺口从“工具能力”转为“调查过程
产品化”。正式建议见
[CR60_PI_UNIFIED_ARCHITECTURE_REVIEW_2026-08-30.md](technical/CR60_PI_UNIFIED_ARCHITECTURE_REVIEW_2026-08-30.md)。

本轮新鲜源码事实：BagReader 的 event/scene 时间线、辅助消息 max-age/max-diff、逐 radar
pending barrier、bag 尾部完成等待都仍存在；GUI Object Table 已区分 RAW_SGU/ALGO 并
显示目标运动、TTC/DDCI 和各功能 object flag；`warning_status_with_frame` 与 `radar_info`
都携带 frame，但 `wfObjectMsg` 没有 algorithm frameID，header stamp 是 publish-now。

因此长期架构新增四个重点：

1. AnalysisRun/Step/Claim/Hypothesis/DebugExperiment 持久化中间过程；
2. EventCodePath 把当前事件的数据条件与五层代码链连接；
3. Public Runtime Collector 优先复用 arbe 公共字段，精确帧缺口用 stamped snapshot 补强；
4. ProjectCapabilityManifest 和 capability pack 适配不同 Gen6 项目并控制 Pi 工具噪声。

最终 HTML 改为 AnalysisRun 的 snapshot；运行时使用 Live Workbench。AI 的价值是组织证据、
候选原因和区分实验，不是隐藏中间步骤后直接给一个最终代码方案。

### 23.13 2026-08-31 Analysis Ledger MVP 实施校验

按照 DDD 的第一条实现切片，新增 `engines/analysis_ledger.py` 和 5 个 Pi 原子能力：
`analysis-run-create`、`analysis-run-read`、`analysis-run-update`、`analysis-step-record`、
`analysis-claim-append`。它们只负责持久化调查状态，不解码 bag、不推断根因、不把 AI 结论
冒充 observed。run 文件保存摘要和引用，详细 step/claim 分文件保存，事件以 append-only
JSONL 留痕；`os.replace` 和目录锁用于避免中断或并发写坏 checkpoint。

Ledger 的准确性门禁已通过 8 个定向测试，并用 CRGVI-1829 已有 artifact 恢复出 3 个 step、
9 个 claim 的 `partial/debug-ready` 运行。恢复结果明确保留：数据/source/binary 身份、
28 个静态事件、`FCTA_R/radar2/frameID=47877/objID=44` 的 derived 关联、isolated GDB 的
`i=0/objID=44` 观察，以及正式 PID attach 受 `ptrace_scope=1` 阻断等缺口。这个 smoke 证明
“中间过程可恢复”，不证明正式 GUI/CAN parity 已完成。

### 23.14 Code Context Snapshot 的实施边界

下一切片不再要求 Pi 每次分析都重新扫全仓。`code-context-refresh` 将对调用方给定的当前
source root 做只读 git/source fingerprint，复用现有 `CodeGraphBuilder` 生成图，再导出
`code-context.v1` 和 `code-index.v1`。导出内容来自当前 SQLite graph：源码文件、函数定义和
行号、CALLS、变量读写、信号、条件、状态迁移、标定参数及各自 source hash；不把 FCTA/FCTB
写死为唯一功能。后续 `code-context-read`/`code-analyze`/`code-gdb-plan` 只消费同一 snapshot，
代码 hash 变化时重建或 fail-closed，避免不同车型、COEM、branch 的知识串用。

该能力默认不调用 LLM。若未来追加功能语义摘要，必须作为同一 source hash 下的可选 enrichment，
并在 artifact 中区分 deterministic index 与 AI-derived knowledge；这符合“数据尽量规则准确，
代码解释由 Pi 组织”的长期边界。

### 23.15 2026-08-31 公共 runtime 快照归一化切片

新增 `engines/arbe/public_runtime.py` 和 `public-runtime-normalize`，把当前 arbe 的三类
公共行统一成 `runtime-snapshot-with-frame.v1`。warning 行按 `data[0]=radar_id`、
`data[1]=frame_counter` 读取；radar_info 按 `data[0]`、`data[4]` 关联并保留 ego speed、
yaw rate、detections 和周期；objectlist 行保留原始字段和 object index。

当前接口默认严格模式：对象带算法 frame 为 frame_verified，带可匹配 callback 为
callback_correlated，只有 header timestamp 或没有帧/回调为 unbound。当当前 source 分析
证明 objectlist 先于 warning_status_with_frame 的同周期发布顺序，且 collector 保存消息序号时，
可显式选择 publication_order，对象进入对应帧并标记为 publication_correlated，同时保留
message sequence 和 derived basis；它不是消息自带 frame，不能冒充 frame_verified。该模块仍不
直接订阅 ROS 或播放 BagReader，远程回放由既有 sim-verify 调度，归一化职责不重复。

### 23.16 2026-08-31 arbe View / Debug_Warning 截图逐项源码核对

本节对应用户提供的 arbe 截图，结论来自当前服务器源码，不把界面像素当作唯一事实。

#### 23.16.1 三种报警来源必须分开

| 界面/通道 | 当前源码位置 | 消息布局 | 含义 |
|---|---|---|---|
| `Adas Warning` | `viewpanel.cpp::AdasWarningDisplay`，订阅 `/corner_radar/warning_status` | `UInt8MultiArray`：`data[0]=radar_id`，`data[1..15]=15 路状态` | visualization host 的算法输出，灯状态直接来自 `algo_adasWarning`，不携带 frame |
| `Adas Warning Raw` | `viewpanel.cpp::AdasWarningDisplay_raw`，订阅 `/corner_radar/warning_status_raw` | `UInt8MultiArray`：`data[0]=radar_id`，`data[1..15]=15 路状态` | bag/ECU/CAN 侧 raw warning；可被 `IgnoreAdasWarningRaw` 忽略，不等于算法内部条件 |
| KPI/trace 算法报警 | `my_rviz_plugin.cpp::onAlgoWarningWithFrameForKpi`，订阅 `/corner_radar/warning_status_with_frame` | `UInt32MultiArray`：`data[0]=radar_id`，`data[1]=frame_counter`，`data[2..16]=15 路状态` | visualization host 算法输出的带帧代理，供 trace CSV/KPI 使用；当前不是左侧灯窗口的直接输入 |

`visualization_node.cpp` 在 `PostProcessMainTI` 后按以下真实字段组装算法报警：

```text
data[1]  = algo_adasWarning.bLeftBsdWarning
data[2]  = algo_adasWarning.bRightBsdWarning
data[3]  = algo_adasWarning.bLeftLcaWarning
data[4]  = algo_adasWarning.bRightLcaWarning
data[5]  = algo_adasWarning.bLeftDowWarning
data[6]  = algo_adasWarning.bRightDowWarning
data[7]  = algo_adasWarning.bRcwWarning
data[8]  = algo_adasWarning.bLeftRctaWarning
data[9]  = algo_adasWarning.bRightRctaWarning
data[10] = algo_adasWarning.bLeftRctbWarning
data[11] = algo_adasWarning.bRightRctbWarning
data[12] = algo_adasWarning.bLeftFctaWarning
data[13] = algo_adasWarning.bRightFctaWarning
data[14] = algo_adasWarning.bLeftFctbWarning
data[15] = algo_adasWarning.bRightFctbWarning
```

with-frame 版本把同一组状态右移一位，并在 `data[1]` 插入 `frame_counter`。因此报告必须
分别保存 `raw_warning`、`algorithm_warning`、`algorithm_warning_with_frame`，不能把三个
数组合成一个“报警状态”。

#### 23.16.2 灯的颜色和四雷达分工

`viewpanel.cpp::updateLight` 的实际颜色含义是：状态 `0` 或其他值为绿色，状态 `1` 为
黄色，状态 `2` 为红色。截图中 raw 窗口 BSD 左侧黄色、算法窗口全绿，只能说明两路
当前显示值不同；因为 raw 无 frame、算法窗口也无 frame，截图本身不能证明两路同一时刻
发生了算法误报。

当前灯数组的真实顺序是：

```text
0 BSD_L   1 BSD_R   2 LCA_L   3 LCA_R   4 DOW_L
5 DOW_R   6 RCW     7 RCTA_L  8 RCTA_R  9 RCTB_L
10 RCTB_R 11 FCTA_L 12 FCTA_R 13 FCTB_L 14 FCTB_R
```

当前 `AdasWarningDisplay` 的 radar 汇聚逻辑不是“每个雷达都刷新全部功能”：

```text
radar1 / front_left  → FCTA_L、FCTB_L
radar2 / front_right → FCTA_R、FCTB_R
radar3 / rear_left   → BSD_L、LCA_L、DOW_L、RCTA_L、RCTB_L
radar4 / rear_right  → BSD_R、LCA_R、DOW_R、RCTA_R、RCTB_R
RCW                  → radar3/radar4 对应状态取较大值
```

`radarPosName()` 同时确认了 `1=front_left`、`2=front_right`、`3=rear_left`、
`4=rear_right`。这些是当前项目的 source-derived mapping，不能写成所有 Gen6 项目的平台
常量；统一工具应从当前代码/manifest 生成并保留 source ref。

#### 23.16.3 ObjectList 目标属性和真实索引

`View → enableobjectlist Disp` 实际订阅四个 topic：

```text
/wf/objectlist_1
/wf/objectlist_2
/wf/objectlist_3
/wf/objectlist_4
```

类型为 `arbe_msgs/wfObjectMsg`：`std_msgs/Header header` + `wfSObj[] ObjectsBuffer`。
`wfSObj` 当前字段包括：

```text
ID, obj_conf, obj_class, class_conf,
position, velocity, bounding_box,
azimuth, elevation, power, rcs, age, last_frame_update,
RxReal, RyReal, RzReal, Spd, Ang, Rng, Vx, Vy, Vz,
objID, distX, distY, velAbsX, velAbsY, fTTC, fDDCI,
objBsdWarningFlag, objLcaWarningFlag, objDowWarningFlag,
objRcwWarningFlag, objRctaWarningFlag, objRctbWarningFlag,
objFctaWarningFlag, objFctbWarningFlag
```

GUI 表当前显示的是其中的 `Radar/Source/ID/objID/Power/Rcs/length/width/height/`
`RxReal/RyReal/RzReal/distX/distY/Ang/Vx/Vy/Vz/velAbsX/velAbsY/fTTC/fDDCI` 和
8 类 object warning flag。算法对象在 `visualization_node.cpp::wf_object_display_handler`
中由真实 `algo_objInfo.trcOutData[i]` 映射到 `wfSObj`：`ID=objUnqID`，`objID=objID`，
`Ang=yawAng`，位置/尺寸/速度/TTC/DDCI/flags 均直接取对应字段。

但 GUI 目前没有直接输出 `trcOutData` 的 `i`：

- 算法显示循环的 `i` 是算法对象数组位置；
- `ObjectListMsg_global.ObjectsBuffer[i]` 保留了这个位置关系，但消息没有 `i` 字段；
- `ObjectListDispByRadar` 的表格行使用 `valid_rows`，跳过 `obj.ID < 0` 后会重新编号；
- 表格的 `ID` 是 `objUnqID`，不是 `trcOutData[i]`；
- 原始 SGU 目标使用 `ID=1000000 + raw_obj_id`，并标记 `Source=RAW_SGU`，不写回算法
  `algo_objInfo`。

因此 Pi 工具要显示 `i`，不能从表格行号倒推，必须由同一 callback 的 stamped snapshot、
运行时 probe 或 GDB 直接采集 `trc_index_i`，并同时保存 `objectlist_message_index`、
`raw_sgu_index`、`algorithm_object_index`、`objID`、`objUnqID` 和 radar/frame provenance。

#### 23.16.4 目标框朝向和界面几何的实际差异

算法目标列表中的 `Ang` 确实来自 `trcOutData[i].yawAng`。Marker 绘制也在动态目标满足
`dynFlg` 条件时使用 `yawAng * System_D2R` 生成四元数；静态目标或关闭对应显示时，Marker
方向可能被置为零四元数，且动态车辆/卡车 mesh 还会对显示 scale 做二次缩放。故：

1. `wfSObj.Ang` 是目标算法字段；
2. RViz Marker 是显示层，可能受动态/静态开关和 mesh scale 影响；
3. 仅凭截图里的框不能替代 `trcOutData[i]` 的真实 polygon；
4. 统一 HTML 要把“算法对象属性”“Marker 显示几何”“GDB 的 objPoly”分栏，并显示各自
   evidence status。

#### 23.16.5 截图中的 Frame Count、Scene Frame、报警区间不是同一帧域

当前源码把多个整数都显示成 frame 相关文字，但它们含义不同：

| 界面字段 | 实际来源 | 正确解释 |
|---|---|---|
| `Frame Count: Radar(1-LT)...` | `frame_count1..4 = pointcloud_msgs1..4.size()` | 每个 LGU topic 的消息数量，不是算法 `frameID` |
| `LGU Event Index` | `lgu_playback_timeline_` 的位置 | 按所有 LGU bag time 排序后的播放事件序号 |
| `Scene Frame Index` | main radar scene index | scene mode 的主雷达索引，不是算法 `frameID` |
| `LGU FrameID -> R1..R4` | 当前 `wfAutosarData.frameID` | 真正的输入算法周期帧号 |
| `Warning Topic: BSD_L: 871-939...` | `buildWarningSummary()` 对 raw warning 时间调用 `findClosestFrameConst()` | 映射到 main radar 消息 vector 的索引区间；当前没有 raw frameID，不能直接称算法帧 |

所以截图中右侧报警摘要的 `871-939` 一类数字，当前代码语义是“nearest main radar
message index interval”，不是 `frame_counter`。之前若把这类数字在报告里直接标为算法
frame，需要改成带 frame-domain 的字段。只有 `/corner_radar/warning_status_with_frame`
的 `data[1]` 或 `wfAutosarData.frameID` 才能直接进入算法 frame 证据。

#### 23.16.6 播放工具怎样产生阶段性数据

当前 `MyRvizPlugin`/`BagReader` 的链路是：

```text
Read bag
  → 按固定 topic 集合分类：LGU、camera、car、raw warning、CAN、XCP
  → 构建 radar0..4 的 time-ordered LGU playback timeline
  → Event mode 每次选择一个 radar/frame；Scene mode 以主雷达索引组场景
  → publishClosestMessages()
  → 发布 LGU / car / camera / XCP / raw warning
  → visualization_node::corner_radar_post_process_data_callback()
  → PostProcessMainTI
  → objectlist / ROI marker / warning / warning_with_frame / radar_info
  → PlaySingleFrame ACK
```

`playLoop()` 会等待上一帧算法回调完成，并在慢回调时调整 wall-clock baseline；
`PlaySingleFrame` 是处理完成 ACK，不是外部 seek API。该流程应由未来 `ArbeReplayAdapter`
复用，而不是在 Python 里重写一个“近似播放器”。

本次核对的远程源码证据位置（服务器 `10.190.171.44`，当前工作区）为：

```text
arbe_gui/src/arbe_gui_main/viewpanel.cpp: 450-498, 512-563, 902-1000,
  2276-2386, 4854-4879
rviz_bag_2e44lc_AtoSar_LGU_Folder/src/my_rviz_plugin/src/bag_reader.cpp:
  24-69, 323-455, 1290-1412
rviz_bag_2e44lc_AtoSar_LGU_Folder/src/my_rviz_plugin/src/my_rviz_plugin.cpp:
  236-295, 392-403, 552-569, 875-1045, 1592-2073, 2914-2919
arbe_gui/src/arbe_visualization_engine/visualization_node.cpp:
  600-740, 1420-1540, 4058-4087, 4163-4177, 4578-4600
arbe_msgs/msg/wfSObj.msg: 1-37
arbe_msgs/msg/wfObjectMsg.msg: 1-2
```

这些行号属于当前 source snapshot；切换子仓分支后必须重新定位，不能把行号作为跨版本
永久契约。

### 23.17 当前能力盘点：已搞清楚与尚未闭合

| 能力 | 当前状态 | 说明 |
|---|---|---|
| raw/algorithm/with-frame 报警信号来源 | 已搞清楚 | topic、消息类型、字段位置、15 路 mapping、灯颜色和雷达汇聚逻辑已核对 |
| arbe ObjectList 字段 | 已搞清楚 | `wfSObj` 全字段、GUI 显示字段、ALGO/RAW_SGU 生成方式已核对 |
| GUI 表格行与 `trcOutData[i]` | 边界已搞清楚 | GUI 不输出 `i`，不能用行号代替；需要 runtime/stamped/GDB |
| Frame Count/Scene/Event/LGU frame | 已纠正 | 已记录各自 frame domain，报警摘要区间不能直接当算法 frame |
| 代码索引构建/更新 | 已实现首版 | `code-context-refresh` → `code-index.v1`；按内容 hash 复用/重建，条件已加入源码索引 |
| Event→代码链/GDB 计划 | 已实现首版 | `event-code-path`；当前真实函数可生成真实文件/行/条件/变量 plan |
| Pi 注册/调度 | 已实现基础链 | `MODULE_REGISTRY` → `gen_pi_extension.py` → `.pi/extensions` → `pi_tool_bridge`；历史重复 code-query 入口已从正式 Pi catalog 收敛，capability pack 和自动 ledger 接入仍在后续 |
| 阶段性分析数据 | 已有底座 | AnalysisRun/Step/Claim 已可恢复；provider 自动落 step、Workbench 投影仍未完成 |
| 真实 ROS 播放/采集 | 未闭合 | 当前有 BagReader/ROS topic 事实、normalizer 和 replay/GDB 能力，但独立 headless collector 尚未完成 |
| 最终 CAN Tx 首帧 | 未闭合 | 当前 visualization callback 主要是算法输出代理；必须继续探测实际 Tx 调度/信号 |

因此，回答“是否都调研清楚”：**当前 arbe View 的信号来源、目标属性、索引语义、
代码索引和 Pi 编排基础已经清楚并已记录；但真实 ROS/BagReader collector、ObjectList
精确同帧绑定、最终 CAN Tx 首帧和完整 HTML/Workbench 展示还没有完成，不能宣称整套能力
已经闭环。**

### 23.18 2026-08-31 SSH 真实回放与公共输出采集

在当前远程 ROS master（`http://localhost:11311`）上，使用 SSH 做了一次短窗口实际回放：

```text
input bag: /home/hoz2wx/CR60LIGHT/data/qzh/CRGVI-1829/corner_radar_net_2026-07-19-11-56-15_11.bag
replay: rosbag play --clock --start 518.9 --duration 4
input topics: /wf/corner_radar/lgu_data_1..4
output topics: warning/status/with_frame, radar_info, objectlist_1..4, FctaArea_1..4
PLAY_RC=0
captured messages=1205
```

远程输出 bag 已拉回本地，sha256=`0c56705ca4d8deae648455a944b456396eba5c837716db16405297b9ea3b34a7`：

[remote capture bag](../outputs/remote_public_capture_20260831/cr60_public_capture_20260831.bag)  
[capture observation](../outputs/remote_public_capture_20260831/observation.json)  
[normalized snapshot](../outputs/remote_public_capture_20260831/runtime-snapshot-with-frame.json)

#### 23.18.1 算法输出与自车

带帧算法输出共 241 条。该窗口中首次 0→非零上升沿为：

```text
radar2 / FCTA_R → frame_id=47876, value=2
radar2 / FCTB_R → frame_id=47876, value=2
radar3 / LCA_L  → frame_id=47874, value=1
```

在 `radar2/frame_id=47876` 的 `radar_info` 中，实际回灌值为：

```text
ego_speed=4.4284453392
yaw_rate=0.2395757139
detections=274
cycle_ms=67.9702759
```

这证明用 `warning_status_with_frame` 和 `radar_info` 可以得到可靠的算法 frame 和逐帧
自车摘要，不需要通过 GUI 像素读取。

#### 23.18.2 ObjectList、目标属性和同帧缺口

同一发布时序附近，`/wf/objectlist_2` 读到 `objID=44`：

```text
ID=0
objID=44
objectlist_message_index=0
distX=5.9200000763
distY=-4.9099998474
Ang=54.0099983215
Vx=-1.0900000334
Vy=3.7699999809
fTTC=1.0115679502
fDDCI=8.3489742279
objFctaWarningFlag=5
objFctbWarningFlag=5
```

该对象消息记录时间与 `warning_status_with_frame(frame=47876)` 相差约 `0.013 ms`，
与 `radar_info(frame=47876)` 相差约 `0.112 ms`；FCTA ROI marker 与 warning 记录时间
相差约 `0.076 ms`，其点范围约为 `x=3.8692..8.6491`、`y=-1.0855..0`、
`z=0.809655`。这些是很强的“同一 callback 发布时序”证据，但 `wfObjectMsg` 自身
仍没有 frameID，因此归一化工具按约定把该对象放入 `unbound_objects`，不挂入
`frame_id=47876` 的 verified objects。

同时观察到 `objFctaWarningFlag/objFctbWarningFlag` 从 1、2、3、4、5 变化，而全局
`FCTA_R/FCTB_R` 从 0 变为 2；两者不是同一个数值域，不能把 object flag=5 直接当作
全局报警值 5，也不能用 object flag 的变化单独定义算法报警首帧。

#### 23.18.3 raw 与仿真输出的差异

对原始输入 bag 同窗口的 raw warning 做了独立统计：

```text
radar1 / FCTB_L raw first rise → nearest LGU frame=47840, delta=-19.704 ms
radar2 / FCTA_R raw first rise → nearest LGU frame=47877, delta=1.172 ms
radar3 / BSD_L raw first rise  → nearest LGU frame=47825, delta=-23.003 ms
radar3 / LCA_L raw first rise  → nearest LGU frame=47825, delta=-23.003 ms
```

raw warning 是约 20 Hz 的独立 CAN/ECU 记录，没有算法 frame；上面的 LGU frame 仍是
时间近邻映射。它和本次重跑算法的 `radar2/FCTA_R/FCTB_R frame=47876` 不能直接合成
一条“同一首帧”。工具必须让用户同时看到 raw 首次上升、仿真算法首次上升和（若可得）
CAN Tx 首次上升。

#### 23.18.4 回放控制的工程问题

当前已证明可以通过 SSH 在已有 arbe ROS master 上短窗口灌入 LGU 并记录公共输出；但
本次用 `kill -INT` 停止 `rosbag record` 时遇到 ROS Noetic 自带 Python handler 的
`TypeError: 'Handlers' object is not callable`，封口后的 bag 仍可被 `rosbag info` 正常
读取。后续正式 collector 应改用明确的 recorder stop/finalize 方式并把 stop 状态记录
到 artifact，不能把这个退出异常误判为算法回放失败。

### 23.19 2026-08-31 远程 sim-verify 与目标逐帧关联验收

在补充消息序号和显式关联模式后，使用既有 sim-verify --mode remote_public 在同一
服务器、同一 arbe 运行态和同一 bag 上再次执行单雷达短窗口回放；没有 checkout、编译、
配置写入或修改远端工作区。执行参数保留在：

sim-verify session run5：../outputs/remote_public_capture_20260831/sim-verify-session-run5.json
public capture run5：../outputs/remote_public_capture_20260831/sim_verify_capture_run5.json

结果：

status=completed
play_rc=0
record_rc=0
extract_rc=0
radar=2
with_frame snapshots=60
object snapshots=60
object records=716
unbound_objects=0

在当前源码已经证明 wf_object_display_handler() 的同周期发布顺序后，本次显式使用
object_association_mode=publication_order。报警上升沿仍来自带帧公共输出：

FCTA_R → frame_id=47876, value=2, source=warning_status_with_frame
FCTB_R → frame_id=47876, value=2, source=warning_status_with_frame

objID=44 在 frame_id=47872..47877 的逐帧记录均存在，示例字段如下：

frame=47872: object_index=0, ID=0, objID=44, distX=5.9300, distY=-5.5700, Ang=55.4800, object FCTA/FCTB=1/1
frame=47873: object_index=0, ID=0, objID=44, distX=5.8800, distY=-5.3800, Ang=55.2000, object FCTA/FCTB=2/2
frame=47874: object_index=0, ID=0, objID=44, distX=5.8800, distY=-5.2300, Ang=54.7900, object FCTA/FCTB=3/3
frame=47875: object_index=0, ID=0, objID=44, distX=5.8700, distY=-5.0800, Ang=54.4000, object FCTA/FCTB=4/4
frame=47876: object_index=0, ID=0, objID=44, distX=5.9200, distY=-4.9100, Ang=54.0100, object FCTA/FCTB=5/5
frame=47877: object_index=0, ID=0, objID=44, distX=5.9900, distY=-4.7100, Ang=53.0400, object FCTA/FCTB=5/5

这些对象绑定的状态是 publication_correlated，关联证据为同雷达 objectlist 消息在
相邻带帧报警消息之间的唯一发布序列；它不是 wfObjectMsg 自带的 frame 字段，也不是
单纯按 timestamp 近邻匹配。若采集不完整、顺序出现多个候选 objectlist 或当前 source
无法证明该发布契约，工具必须回退为 unbound/strict，不能沿用本次模式。

这次验收确认了三个可复用结论：

1. 现有 Pi 原子能力足以串起“远程公共回放 → capture → 逐帧归一化”，不需要新建
   public replay 或 object collector 工具；
2. 公共输出能可靠提供算法 frameID、报警上升沿和自车 radar_info，当前 source
   的 objectlist 也能在有源码发布契约时得到可追溯的 derived 同周期目标属性；
3. object_index 是发布消息 ObjectsBuffer 下标，不等于源码循环变量 i；源码
   objInfo->trcOutData[i] 仍需 Code Context/GDB 才能拿到，工具必须同时展示两者的
  来源差异，不把 object_index 改名成 i。

### 23.25 现有 viewer 的 canonical runtime 集成 smoke

sibling cr60-debug-harness 已有 build_html_reports.py 会把 diagnosis_bundle、runtime_evidence
和 viewer-model 组装为 batch index/单数据 report；因此 radarAnalyze 不新增 HTML 渲染器。
用真实 CRGVI-1829 FCTA event-slice merged bundle 和 public canonical evidence 生成：

outputs/remote_public_capture_20260831/viewer_batch_run5/index.html
outputs/remote_public_capture_20260831/viewer_batch_run5/data/CRGVI-1829/report.html

viewer model smoke 结果：feature=FCTA，event_id=recorded_raw:FCTA_R:radar2:519.376635，
runtime_status=matched，observation_count=70，fields=183；其中 159 个字段 token 来自
wfObjectMsg.ObjectsBuffer[0].*。这证明公共 runtime/canonical evidence 可以进入现有
Runtime panel；正式 UI 仍需继续补充 publication_correlated/unbound 的显示标签和帧选择器。

### 23.23 Public Runtime → canonical evidence 与事件 scope

现有 runtime-evidence-normalize 已扩展为同时接受 GDB session/transcript 和
runtime-snapshot-with-frame.v1。公共 warning/radar_info 被投影为 runtime_with_frame
observations；对象按 frame_verified/callback_correlated 使用 runtime_with_frame，
publication_correlated/unbound 使用 objectlist_candidate，并保留真实 topic/ObjectsBuffer
字段 token、frame/object/index 和来源。

现有 runtime-evidence-merge 增加可选 event/frame/object scope。对当前 FCTA_R 事件按
event_id 物化后，公共 observation 从 775 条缩到 70 条，merge 结果 74 条匹配、
event overlay=matched；完整 19 MB public evidence 仍独立保存。未给 scope 时保持 full
merge 兼容行为。这个 scope 是性能和上下文控制机制，不是证据删减机制。

### 23.22 Gen6 ProjectCapabilityManifest 首版

为避免不同六代项目共用错误的功能、参数或 replay 假设，新增唯一 Pi 能力
project-capability-manifest。它读取显式 intake/preflight/code-context/runtime snapshot/
diagnosis bundle，不读取 HTML、不调用 LLM、不从路径名猜车型或功能，生成按 data、feature、
code、replay、runtime、presentation 分类的 capability entries，以及 unsupported、
artifact schema/hash/path provenance、source freshness 和 manifest fingerprint。

在当前 CRGVI-1829 相关 artifact 上实测：code-context mirror 的 source snapshot=52a…，
diagnosis bundle 的 source snapshot=d75…，manifest status=blocked，并把冲突放入 conflicts
和 source-consistency unsupported；这阻止 Pi 把不一致的 code index 与静态 bundle 混用。
如果只提供同一 source snapshot 的 artifact，显式 identity 可以替代缺失 intake 并标记为
explicit_identity；本次冲突不是由缺少 intake 文件造成。
该清单只负责 Pi 的当前能力发现/短名单前置，不能替代 Pi-context 的 run binding，也不
新增第二套编排器。

### 23.24 Pi-context 能力清单绑定与上下文体积

现有 pi-context 已接收 project-capability-manifest，并只嵌入 schema/status、能力 ID 状态、
unsupported、freshness、manifest fingerprint 和 artifact ref；不会复制完整 code-index 或
逐帧 runtime evidence。它会比较 project/variant/source_snapshot_hash，冲突直接 blocked，
manifest partial 则 context partial。

用当前实际 artifact 验证时，manifest 的 project/variant/source snapshot 与静态 bundle 不同，
pi-context 正确返回 blocked；runtime evidence 总 observation=775，但 Pi 摘要只返回 24 条
样本并标记 sampled=true。完整数据仍从 canonical evidence artifact 读取。

### 23.21 wfSObj 占位行的 source-aware 处理

当前 GUI 的 ObjectListDispByRadar() 对 obj.ID < 0 直接跳过；因此 public-runtime-normalize
增加 object_validity_policy。默认 preserve，原始 capture 不删除任何行；在当前 arbe 的
wfSObj 消息契约已确认时选择 arbe_wf_sobj，把 ID=-1 sentinel 放入 ignored_objects。
run5 capture 经过该策略后得到 snapshots=60、真实 object records=715、ignored_objects=1、
unbound_objects=0；objID=44 在 47872..47877 的 publication_correlated 绑定不受影响。
该策略不应跨项目默认启用，Pi 应依据当前 ROS 消息定义/GUI 源码证据选择。

### 23.20 远端 recorder 顺序稳定性复验：publication_order 不是绝对同帧

随后使用相同服务器、代码、bag、radar2 和 4 秒窗口，以同一 sim-verify 入口再次回放，
但采集结果出现不同的跨 topic 写入顺序：warning_status_with_frame(frame=47874) 先于
objectlist 消息写入。严格的唯一序列关联因此拒绝 32 条对象行；objID=44 在 47874/47875
没有被错误挂接，其他可证明的帧仍被绑定。

run6 结果为：

status=completed, play_rc=0, record_rc=0, extract_rc=0
observed algorithm rises: FCTA_R/FCTB_R → frameID=47876
snapshots=60, object_snapshots=57, object_records=683, ignored_objects=1, unbound_objects=32

这次复验把能力边界明确为：源码发布顺序是必要条件，但 rosbag recorder 的跨 topic 写入
顺序不是充分条件；publication_correlated 只能是“可验证时的 derived 线索”，不能作为用户
所要求的绝对同帧真值。要让 HTML 稳定呈现报警帧的真实目标属性，下一步应优先实现
同一算法 callback 内的 stamped snapshot/collector，或者对目标属性使用 headless GDB 在
frame_counter 停止点直接读取；run6 的拒绝行为保留为回归样例。

### 23.26 arbe GUI 对应机制的源码结论

当前 GUI 的对应不是 wfObjectMsg 自带 frameID，而是由“单帧/场景播放 + 算法回调 + 发布顺序 + ACK 节流”形成的时序对应：

1. MyRvizPlugin::publishClosestMessages() 从当前 LGU 消息读取 wfAutosarData.frameID，
   保存 radar/frame/timestamp，并将 frame 放入 pending_event_frame_ids_。
2. visualization_node 在同一回调中调用 PostProcessMainTI(..., frame_counter, ...)，
   调用 wf_object_display_handler() 把 algo_objInfo.trcOutData[i] 拷贝到 wfSObj，
   然后发布 warning_status、warning_status_with_frame 和 radar_info，最后通过
   /play_single_frame_<radar> 返回 status=1。播放器收到 ACK 后才推进下一帧。
3. viewpanel::ObjectListDispByRadar() 只缓存每个 radar 的最新 objectlist，并用 valid_rows
   重新填表；RadarInfoDisp() 只更新最新 radar_frame_record/radar_info_record。GUI 没有
   将 objectlist row 和 radar_frame_record 持久化 join。

所以 GUI 单步播放时看到的目标、报警灯和自车属性通常来自同一轮处理，但它依赖运行时节拍，
不是可独立验证的消息级关联。rosbag 外部 recorder 可能改变跨 topic 写入顺序；run6 已证明
同一源码发布顺序不足以保证 recorder 顺序稳定。工具必须把算法报警 frame（with-frame.data[1]）、
自车 radar_info.data[4]、目标 objectlist、LGU message index、warning index 和 objectlist
index 分开保存；目标要达到绝对同帧，必须使用 callback 内 stamped snapshot 或 exact-frame GDB。

### 23.27 三个用户出口的真实实现验收（2026-09-01）

在不重新回放 1GB bag 的前提下，复用已完成的 CRGVI-1829 真实产物验证了三条链路：

1. 之前的 batch index：5 条数据、149 个事件，作为批量预检查输入；
2. 含 runtime overlay 的 `FCTA_R/radar2/frame=47877` bundle/viewer：通过
   `evidence-query` 命中 `objID=44`、`raw_sgu_index=0`、`algorithm_object_index=0`、
   `objectlist_index=1`、ego/target/frame/code 字段；
3. `diagnosis-report` 生成 JSON、Markdown、HTML companion，诊断状态保持 `partial`，
   并保留 `alarm_first_frame_not_exact`；
4. 同一 AnalysisRun 写入 `batch-precheck`、`detailed-report`、`dialogue-query` 三个 step，
   schema 验证通过，产物在 `outputs/three_output_acceptance_CRGVI1829_20260901/`；
5. 本地 Pi provider `bosch-qwen3_6/Qwen3.5-27B-FP16` 实际调用生成的 registerTool，
   完成事件查询和详细报告生成；使用同一 `analysis_run_id` 继续追问时，ledger step 从 1 增加到 2。

本次实现还发现并修复了两个通用问题：Windows 命令行不能承载大 context，改为 Pi
`--append-system-prompt` 临时文件；case 目录需要同时暴露 bundle 和 viewer-model 路径，
否则目标/自车属性会退化为 bundle 缺口。普通对话查询默认有界返回，完整报告内容只落 artifact。

当前仍未宣称完成的部分：Pi 自动执行需要审批的批量 precheck 长链、
`diagnosis-panel` AI inference 与报告的长链组合、Analysis Trail 在 sibling viewer 内的交互投影、
正式 CAN Tx 首帧和 point-cloud runtime。上述缺口均不是用静态数据或 AI 猜测填补。

### 23.28 单数据真实入口复验（2026-09-01）

对用户指定的 `/home/hoz2wx/CR60LIGHT/data/qzh/CRGVI-1829/corner_radar_net_2026-07-19-11-56-15_11.bag`
重新执行了 `cr60-precheck --mode manifest --execute`：1 个 case、28 个报警事件、返回 `ready`，
功能/雷达分布为 `BSD_L/radar3=7`、`LCA_L/radar3=7`、`BSD_R/radar4=6`、`LCA_R/radar4=6`、
`FCTB_L/radar1=1`、`FCTA_R/radar2=1`。这证明单条数据也保留一条数据中的多功能事件集合，
没有把实现固化为 FCTA/FCTB。

选中 `recorded_raw:FCTA_R:radar2:519.376635` 后，`viewer-model.v1` 在同一目标分析帧提供：
`frameID=47877`、`objID=44`、raw SGU/算法对象下标 `i=0`、`objectlist_index=1`；目标
`distX=5.99`、`distY=-4.71`、`yawAng=53.04`、`fTTC=1.02`、`fDDCI=8.38`，自车
`actual_spd=4.400768...`、`actual_gear=4`、`yaw_rate=0.361754...`。矩形四角由当前代码
`adasObjPloyCal` 合同按 yaw 推导；`fInterX/fInterY` 与 `objInfo->trcOutData[i]` 运行时快照
仍明确为 `not_available`。

`event-code-path.v1` 以当前 sibling harness 的 legacy `code_index.json` 做内存兼容适配，
解析到真实 `FrontCrossTrafficAlertAndBrake`，生成 8 组断点；主条件为
`(frame_counter >= 47877 && frame_counter <= 47877) && (sObj->objID == 44)`。输出保留
`adapter=cr60-debug-harness-code-index-compat.v1`，不改写上游 code index。

最后用 `python cli.py pi --question ... --case-dir ...` 真实启动 Pi，当前 provider 发出
`evidence-query` 的 `tool_execution_start/end`，并在 Analysis Run `run-20260901T060752-8a061b93da`
中记录工具事件；case→batch manifest→viewer-model→evidence-query→Pi ledger 链路成立。该次
报告仍把 `alarm_first_frame_not_exact` 和 `runtime_not_supplied` 保留为缺口，因此 `47877`
是有界 selected analysis frame，不被宣称为最终 CAN Tx 上升沿。

### 23.29 报告条件证据和场景投影复验（2026-09-01）

新增 `condition-trace.v1` 原子工具，并将其接入 `diagnosis-report`。它不复制 BSD/FCTA 等功能
规则，而是读取当前 `event-code-path` 的源条件、active source 参数投影和同一选中事件的 field
facts，使用受限安全表达式子集输出 `satisfied`、`not_satisfied`、`not_evaluable` 或
`unsupported`，同时保留原始 C 表达式、源码行、bindings、代入表达式和缺失 token。

在上述真实 FCTA_R 事件上，代码索引的 22 条条件均被保留；由于 `g_egoCarAddInfo.carSpd`、
`System_Kmh2ms`、`fTTMX/fTTMY`、`fInterX/fInterY`、计数器和部分局部 flag 没有以同帧运行时
事实进入输入，结果为 `22 not_evaluable`，没有被转换成 `not_satisfied`。这正是后续 GDB
需要补采的变量清单，而不是报警误判结论。

详细 HTML 已增加：

1. selected frame 的 ego/target code-token 摘要表；
2. 当前坐标契约下的自车、目标矩形、目标 yaw heading 和 FCTA ROI SVG；
3. 条件状态/源码/代入式/缺口表，完整内容仍可展开查看 JSON。

本轮条件/场景相关测试和原有 Pi/ledger/precheck 组合测试共 `74 passed`。真实产物位于
`outputs/single_case_actual_CRGVI1829_20260901/`，其中 `condition-trace-FCTA_R.json`、
`detailed-report-FCTA_R/diagnostic-report.html` 和 `acceptance-summary.json` 可作为验收样本。

### 23.30 独立 Pi 入口和记忆召回复验（2026-09-01）

为验证产品脱离当前 ChatGPT 后仍可独立工作，使用 `python cli.py pi --question ... --case-dir ...`
真实执行了两类 Pi 回合：

1. 只查询字段时，Pi 实际调用 `evidence-query` 并将 `tool_execution_start/end` 写入 Analysis Run；
2. 请求证据版详细报告时，Pi 实际调用 `diagnosis-report`，生成 JSON/Markdown/HTML 三件套，
   报告自动从 bundle 的 `code_evidence` 绑定当前函数条件，包含 22 条 `not_evaluable` 条件和
   ego/target/ROI/heading 场景 SVG。

当前 generated extension 共 53 个 Pi 能力（49 modules + 4 tools），Pi 入口按问题从 live catalog
生成 bounded allowlist：环境/传输/补丁/编译/启动/GDB 工具仍在目录中，副作用继续由各自 approval
gate 控制。

新增 `memory-recall.v1` 复用已有 `MemorySystem`，未绑定 variant 或显式 memory_dir 时不会选用
config.default_variant 的代码型记忆；本次实际召回结果为 project/function/session 可读，patterns、
code_knowledge、constants、semantic 标记 `blocked_stale`。这证明记忆能力已能被 Pi 调度，同时
避免把其他车型或旧 source 的知识混入当前诊断。

本轮相关定向测试更新为 `77 passed`；这仍不是正式 arbe/CAN Tx/GDB runtime 完整验收。

### 23.31 DDD 缺口审查与领域补足（2026-09-01）

本轮按“需求→领域对象→上下文边界→契约→实现→证据→验收”复审，新增基线文档
`docs/technical/CR60_PI_UNIFIED_DDD_GAP_REVIEW_2026-09-01.md`。审查结论是：Pi-first、
原子工具、sibling harness/arbe 复用和 evidence ledger 的方向成立，但详细报告此前缺少
跨证据报警时间线和结论发布门，因此容易把“报告已生成”误解为“报警首帧/正误报已确认”。

审查固定了以下领域不变量：

1. data/source/binary identity 不一致时 runtime overlay blocked；
2. `recorded_raw`、`replay_algorithm`、`runtime_with_frame`、`gdb_observation`、
   `can_tx_observation` 不互相覆盖；
3. `i`、`k`、`objectlist_index` 独立保存；时间近邻不等于同帧；
4. 缺失值是 `not_available/not_evaluable`，不能转成 false；
5. `report.status=ready` 与 `conclusion.level=confirmed` 完全分离；
6. SGU 3–5 帧和 point-cloud 150–200 帧是不同 replay strategy；
7. Pi 只负责意图、recipe、审批、恢复和解释，确定性工具负责事实，HTML 是 read model。

### 23.32 `alert-timeline.v1` 和实际单数据报告补足（2026-09-01）

新增功能无关的 `engines/alert_timeline.py` 与 `ai/modules/alert_timeline.py`，并自动注册到
generated Pi extension。它消费已有 bundle/viewer/runtime artifact，输出：

- 五类证据层的报警行、function/side/radar/frame/status/transition；
- warm-up、selected analysis frame、context frame 的 `playback_frame_map`；
- 每个播放帧可绑定的 alarm signals；
- raw/replay/public/GDB/CAN 的 `same/different/not_comparable/not_evaluated` compare；
- data/source/binary identity conflict。

`diagnosis-report` 已复用该 projection，并新增 `conclusion`：无 runtime/CAN 时输出
`facts_only/partial`，明确当前可以确认的事件和仍不能确认的事项。对用户指定的真实 bag
重新生成的报告是：

`outputs/single_case_actual_CRGVI1829_20260901/ddd-audit-report-FCTA_R/diagnostic-report.html`

实际结果：

- `recorded_raw`：`FCTA_R/radar2`，selected analysis frame `47877`，frame status 为
  `derived`（nearest-LGU/time-aligned），不是 CAN Tx 上升沿；
- 当前 sibling bundle 没有独立 `data_fingerprint`，timeline 因此将 data identity 保留为
  `partial`；没有用 JSON artifact hash 冒充 bag hash；
- `replay_algorithm`、`runtime_with_frame`、`gdb_observation`、`can_tx_observation`：当前
  该报告输入未提供，均显示 `not_available`；相应 compare 为 `not_evaluated`；
- 播放帧 map 显示 `47872..47876` 为 warm-up，`47877` 为 selected，后续为 context，并带
  时间和同帧报警信号列；
- `conclusion.level=facts_only`、`conclusion.status=partial`，报告没有给出正报/误报或根因
  已确认结论。

报告同时生成 `diagnostic_narrative`：逐条按真实源码行、原始表达式、代入表达式和求值状态
输出中文命中过程，并给出 `should_alert`。静态版报告结果为 `indeterminate`，原因是只有 raw
报警和时间对齐帧，缺少同帧算法输出、运行时局部变量和 CAN Tx；这不是“应该不报警”的结论。

随后复用已保存的 arbe public runtime run5 artifact，生成
`outputs/single_case_actual_CRGVI1829_20260901/ddd-audit-report-FCTA_R-runtime-run5/diagnostic-report.html`。
该版本识别到 `runtime_with_frame=observed`，FCTA_R 在 `frame=47876` 出现运行态上升线索，
在 `47877` 仍为非零，因此 `should_alert=supported_yes`；但 raw/runtime compare 仍是
`not_comparable`，没有 CAN Tx 观测，故 `conclusion.level` 仍为 `facts_only`。
同一报告在 selected frame 保留了 `objectlist_candidate` 的 objID=44 目标属性，关联为
`publication_order_derived`；由于当前 `objectlist` 没有算法 frameID，它没有被升级为 exact
runtime polygon/同帧算法目标。

同时扩展 `condition-trace`：当 `runtime_observations` 具备 selected exact frame 时，真实
runtime field 会以 `runtime_<layer>` provenance 回填同一源表达式并重新求值；同功能时间窗口
或时间近邻观察不会被绑定。`memory-recall` 支持从显式 `pi-orchestration-context.v1`
读取 variant/memory scope，避免 standalone Pi 误读默认车型代码记忆。

本轮扩展定向组合为 `84 passed`（alert timeline、diagnostic narrative、condition trace、memory recall、replay mapping、runtime contract、report/Pi、Pi capability catalog 组合），
并完成 py_compile 和 Pi extension 重生成（当前 54 个 Pi 能力：50 modules + 4 tools）。联合
public replay、GDB、CAN Tx 和正式 GUI player parity 仍留在后续 runtime sprint，未被静态报告
冒充完成。

### 23.33 warning trace 语义映射的通用化纠偏（2026-09-01）

补查发现旧 `engines/arbe/replay_provider.py` 曾把 `w1..w15` 默认映射为 CR60 的固定功能名。
这对当前 arbe 合同可以工作，但不满足不同 Gen6 项目/不同 warning contract 的通用化要求。
现已改为：`parse_warning_trace_csv()` 只有在调用方或当前 case 的 `runtime_schema.warning_contract`
提供映射时才赋予功能名；否则保留 `wN` 并标记 `warning_mapping_source=not_provided`。旧
`WARNING_BITS` 仅保留为兼容导出，不参与默认解析。`sim-verify` 本地模式会优先读取当前 case
runtime schema 的 mapping。

该纠偏不改变当前 `cr60_light_arbe` 的静态报警事件，也不把功能名硬编码进入 timeline；它把
“位位置事实”和“当前项目语义映射”分离，避免跨项目误标。新增 mapping 定向测试已纳入本轮验证。

### 23.34 Pi 工具调用的阶段性账本补足（2026-09-01）

此前 Pi 只把整轮对话作为一个 `dialogue` step，虽然可追溯，但在长链路中不够直观。现已在
`PiModule._on_event()` 对 `tool_execution_end` 等完成事件追加一个以工具名为阶段的子
`AnalysisStep`，只记录工具名、状态、artifact refs 和简短观察，不记录模型隐藏思维链；
对话结束时仍保留一个 dialogue step。这样用户可看到每个原子能力的成功、阻断、失败和产物，
同时不把 Pi 变成第二套调度器。该能力有 ledger fixture 覆盖，真实 Pi provider 长链路仍需
现场验收。

### 23.35 诊断报告改为文字结论优先（2026-09-01）

针对“不要大量无意义数据，直接说明报警工况和代码如何命中”的使用反馈，详细报告的默认
read model 已调整为：

- `executive_summary` 先描述功能/侧别/radar/frame/objID、自车关键状态和目标关键状态；
- `alarm_assessment` 单独说明原始报警、算法/公共运行态输出、算法上升沿线索和 CAN Tx 证据；
- `condition_items` 默认只显示 10 条当前功能最相关的真实源码条件，保留文件、行号、原始表达式、代入表达式、求值状态和缺口；
- `condition_digest` 说明完整候选条件总数、已显示数、省略数以及必须从同帧 runtime/GDB 获取的关键量；
- 页面默认只显示关键 ego/target/runtime facts 和选中帧附近 timeline，完整对象列表、条件、运行态
  observation 和 transcript 仍在折叠区/JSON，不会丢失。

真实 `CRGVI-1829` 三个报告已重新生成。public runtime 版本可确认 `FCTA_R` 在 `47876`
出现算法/公共输出的 0→非零线索、`47877` 仍为非零，`should_alert=supported_yes`；GDB 版本
可在 `47877/objID=44` 同帧代入 5 条完整候选条件（其中 FCTA/R scope 为 3 条），仍有 17 条完整候选条件无法求值且存在 `disturbance=suspected`，
所以当前没有把任何版本写成 CAN 首帧或根因确认。

### 23.36 几何关系投影补足（2026-09-01）

此前 scene SVG 能绘制 polygon/ROI，但 `geometry_projection.collision_status` 固定为
`not_evaluated`，导致图形和文字不能回答目标是否进入当前功能 ROI。现已增加通用 polygon
edge/containment 关系计算：GDB 同帧的 `objPoly` 与 `rightRoi` 输出为
`observed_disjoint`；没有 runtime polygon 时，FCTA/R 的源码推导几何输出为
`source_derived_disjoint`。报告不把该几何结果升级为功能报警结论，仍要求同帧
`fInterX/fInterY`、warning flag、状态机计数和 CAN Tx。SVG 增加目标四角标注、几何来源和
containment 状态，新增报告 fixture 验证。 

### 23.37 Pi 事实锚点与报告交付验收（2026-09-01）

实际运行 `python cli.py pi` 时发现，同一 case 的多事件选择不能因为重复记录而回退到第一个
功能；同时仅把报告规则写在 system prompt 中，也不能保证模型主动生成 HTML。现已在 Pi root
增加确定性 `evidence_anchor`：从当前 bundle/viewer/runtime artifact 解析显式 function/side/
frame/radar，复用 `diagnostic-report` engine 生成摘要；明确要求报告时自动落盘 JSON/Markdown/HTML，
并把输入和输出 refs 记录到 `evidence-anchor` AnalysisStep。实际 Pi 回合在显式挂载
`runtime-evidence-public-run5.json` 后正确输出 FCTA_R/R，而不是错误的 BSD_R。对应的历史验收报告
已在 2026-09-03 清理，结论收敛到当前有效报告
`outputs/single_case_actual_CRGVI1829_20260903_final/diagnostic-report.html`。Pi timeout 现在
返回 `ok=false`，但不删除已生成的报告。

### 23.38 GDB 结构体字段与条件回填补足（2026-09-01）

旧版 canonical runtime artifact 的 `objInfo->trcOutData[i]` 可能只有一条 GDB struct 字符串，
而字段切片又会把后续解析结果截掉。现已在 canonical 读取时复用 GDB struct parser，提取
`objFctaWarningFlag`、`rightFctaFlag`、`fInterX/fInterY`、`fIntAng`、位置/速度等真实 token，
并用头部 + 高价值字段 + 尾部的方式做有界查询；重复 normalize 不会无限追加字段。当前 source
中的多行 enum 也能解析，例如 `WarningFlag_Normal=0U`，所以 GDB 报告可将
`objInfo->trcOutData[i].objFctaWarningFlag > WarningFlag_Normal` 求值为 true。相近但不同的
`sObj.obj...` 与 `sObj->...` 仍只生成 alias hint，不强行绑定。

### 23.39 Pi 能力目录入口一致性修复（2026-09-01）

复核实际命令时发现文档中的 `python cli.py capabilities --json` 原先会落入旧版
case-dir argparse 而失败。已在 `cli.py` 增加只读 `capabilities` / `capability-catalog`
入口：目录直接取 `CapabilityRegistry`，只输出可暴露给 Pi 的叶子能力，过滤 `pi`、
`agent-loop` 等编排根，不实例化也不执行能力；支持 `--kind module/tool`。当前实测
基础切片时 Python registry、bridge `--list` 和生成的 `.pi/extensions/radar-capabilities.ts`
均为 54 个能力，且 `diagnosis-report`、`condition-trace`、`evidence-query`、
`runtime-debug-plan`、`runtime-debug-run`、`analysis-step-record`、
`analysis-claim-append` 均可见，`runtime-debug-run` 的审批元数据也保留。
新增 `tests/test_cli_capabilities.py`，与本轮定向组合合计 `84 passed`；该命令仅用于
操作员/CI 检查，不改变 Pi 的唯一编排入口。

### 23.40 旧 GDB 字段的数值规范化（2026-09-01）

继续核对真实 GDB artifact 时发现，旧 producer 已保存的 `g_egoCarAddInfo.actual_gear`
可能仍是 GDB 原文 `4 '\\004'`，新 transcript 路径虽然能解析为整数，但 canonical artifact
读取路径没有统一处理。现已在 `runtime_evidence` 的 canonical GDB 读入阶段规范化已有标量，
同时保留 `raw_value`；因此报告和 condition binder 使用 `actual_gear=4`，原始 GDB 文本仍
可追溯，结构体 dump 继续由专用 parser 处理。该修复是通用的旧 artifact 兼容，不绑定
FCTA/FCTB，新增 runtime evidence 回归断言并重新生成 GDB 报告。

### 23.42 S2B 协同 Debug 账本 MVP（2026-09-01）

为支持“报告给线索、用户接手 debug、再把结果交回 Pi”的交互闭环，新增
`analysis-hypothesis-record`、`debug-experiment-record` 和 `analysis-user-observation`
三个叶子模块，底层复用同一个 `AnalysisLedger`。Hypothesis 保留状态历史并禁止非用户
写入 `confirmed_by_user`；Experiment 必须先 `planned` 再记录结果；用户从 VSCode/GDB/
截图/备注回填时形成独立 `user-observation.v1`，固定 `runtime_eligible=false`，不会直接
覆盖自动 runtime 或 condition binding。`diagnostic-report` 读取这些实体的有界摘要，
显示 Analysis Trail、Hypothesis Board、Next Experiments 和 User Observations，完整历史
仍通过 artifact ref 保留。当前 Pi catalog 实测为 57 个叶子能力（53 modules + 4 tools），
三项新能力均已进入生成的 `registerTool`；S2B 定向验证组合当前为 `97 passed`，本切片
不声称自动根因确认或自动执行实验。

### 23.43 远程 arbe 只读状态刷新（2026-09-01）

对用户确认的 `10.190.171.44:/home/hoz2wx/CR60LIGHT/cr60_light_arbe` 再次执行只读
`arbe-preflight`，得到 `status=ready`，但工作区仍然是 dirty，不能把 ready 理解为可
安全覆盖或可直接发布的 build 状态。当前实测事实为：outer HEAD
`4c171298b2c3583509ea9e3da222b90ba0a9e513`、algo_source HEAD
`a81b08a38f316a3d25bfcbcad6dcfc822d24b990`（detached）；COEM=`BYD_UKE`、CUDA
`CUDA_BYD_UKE_Bundle_V2.0.xlsx`、sheet=`03_QZH`；`BUILDMODEL=2`、`HILMODEL=2`；
binary fingerprint=`93a8f2b2c11a6d8ba1abadbc7eb480e8867352f261a71c4bb5023f4c4ef80890`；
当前 radar1/2/3/4 visualization_engine PID 分别为 `3570403/3570363/3570364/3570445`；
GDB `ptrace_scope=1`，CAN 目前只有源码候选（110 个 token），没有 runtime Tx 观测。
远程证据保存为 `outputs/arbe_preflight_refresh_20260901.json`。outer/algo 的 dirty 文件、
现有进程和权限仍作为后续正式 build/attach 的审批门，不自动修改。

### 23.41 Analysis Trail 的报告投影（2026-09-01）

复核三出口流程时发现，`AnalysisRun` 虽然已经记录 `evidence-anchor`、工具调用和 dialogue
step，但详细报告此前只显示 step 数量，用户无法在同一 HTML 中看到阶段性发现。现已让
`diagnostic-report` 从 `analysis-run.json` 的 step ref 只读加载对应 step，并投影有限的
`user_visible_summary`、observations、gaps、conflicts、claim 数量和 next actions；不展开
隐藏思维链或完整 ledger payload。Pi 自动生成报告时绑定当前 run，因此“静态预检查→公共
证据/GDB→报告→追问”的阶段线索可以留在同一份报告中；没有 AnalysisRun 时仍明确显示
`not_provided`，不伪造过程。该投影新增 Pi anchor/报告测试，并保持报告 JSON/HTML 为同一
read model。

### 23.44 当前 source 的输出链和公共帧关联证明（2026-09-02）

继续对用户确认的远端 arbe 工作区执行只读 SSH 探索，发现旧版 preflight 使用跨所有 COEM 的
递归 grep 并以 `head -n 320` 截断，虽然当前 `BYD_UKE` 恰好没有漏掉主要 Tx 行，但对其他
车型/项目不可靠。现已改为先从当前 `launch_config_4radars.yaml` 读取 `coem_name`，再只扫描
`algo_source/coem/<coem>` 下的 `RteComMapping*.c` 和 `components/com/AutoGen/*.c`，并排除
注释行。输出不再把其他 COEM 的同名 signal 混入当前 source。

对当前远端 `BYD_UKE` 的重新实测结果：有效的
`RteComMapping_WriteSignal` 为 `191` 条，`RteLite_Write_*`/`Com_SendSignal` transport
候选为 `762` 条；产物为
`outputs/arbe_preflight_refresh_20260902_full.json`。其中 FCTA_R/R 报告可以从真实 source
筛出：

```text
RteComMapping_WriteSignal(RRadar_FCTA_Warning_Right_S)
  <- (AdasStM.Frontright_FCTA == 2) ? 1u:0u       RteComMapping_Tx.c:147
  -> RteLite_Write_RRadar_FCTA_Warning_Right_S  rteLite_PubCan_FCRonly.c:171
  -> Com_SendSignal                                rteLite_PubCan_FCRonly.c:177
```

这只是源码候选链，不是该帧已经完成 CAN Tx 的证明；报告仍要求独立
`can_tx_observation` 或 GDB 命中。

同一远端 source 的 `visualization_node.cpp` 已被静态确认：
`corner_radar_post_process_data_callback` 在同一 callback 中先调用
`wf_object_display_handler()`，后发布 `wf_adas_warn_status_with_frame_pub`。preflight 现保存
`public_evidence.objectlist_frame_contract=source_verified` 及四个源码 marker。公共回放工具
新增 `object_association_mode=auto`：带该证明且 capture 保留 per-topic message sequence 时
才选择 `publication_order`；否则回退 `strict`，不按 timestamp 把 objectlist 当同帧。

### 23.45 运行时 token 与源码局部别名的证据绑定（2026-09-02）

在当前 `FrontCrossTrafficAlertAndBrake` 源码中确认：循环内先执行
`objOutDataStruct sObj = objInfo->trcOutData[i];`，随后用 `sObj` 计算条件；GDB/public
证据常保留的是 `objInfo->trcOutData[i].<field>`。`condition_trace` 现会读取当前 source
条件行之前的局部 copy assignment，仅对声明后未再次赋值的具体 field 建立
`source_alias_bindings`，保留 declaration 行、原始 token 和 `source_alias_proven` provenance。
它不是通用 C 解释器：跨函数、无附近赋值、或字段在之后被修改时仍保持
`not_evaluable`。

以真实 `CRGVI-1829 / FCTA_R / radar2 / frameID=47877 / objID=44 / i=0` 重建的报告为：

`outputs/single_case_actual_CRGVI1829_20260902/diagnostic-report-final/diagnostic-report.html`

当前确定性摘要是：同帧 GDB 目标级
`objInfo->trcOutData[i].objFctaWarningFlag=4`、`rightFctaFlag=true`；源码条件 trace
共 `22` 条，其中 `6 satisfied`、`0 not_satisfied`、`16 not_evaluable`。报告明确把它写为
`object_warning_observed`，而不是最终 CAN/功能报警确认；同时显示自车/目标 token、几何关系、
源码输出候选和 `RteLite → Com_SendSignal` 位置。缺失的 `fTTMX/fTTMY`、ROI 数量、状态机
计数和最终 CAN Tx 仍是下一次 runtime/GDB 实验的真实缺口。

### 23.46 当前源码身份与真实 GDB 证据收口（2026-09-02）

对上一节的历史摘要做校正：本轮不是复用旧的 GDB 结果，而是从远端
`10.190.171.44:/home/hoz2wx/CR60LIGHT/cr60_light_arbe` 的工具自建隔离回放日志
`/tmp/cr60_harness_gdb_smoke_1788323168_gdb.log` 重新导入并规范化。运行身份已与本次
source snapshot、bag 和 ELF fingerprint 对齐；工具自建的 11324 GDB/ROS 进程已清理，
没有触碰正式 `bash start` 的四个 visualization engine 进程。

最终报告：

`outputs/single_case_actual_CRGVI1829_20260902/diagnostic-report-final/diagnostic-report.html`

当前报告的关键证据链为：

- `frameID=47877`、`g_egoCarAddInfo.carSpd=4.42844534`、`actual_gear=4`、
  `objInfo->trcNum=16`；算法循环索引 `i=0`，目标 `objInfo->trcOutData[i].objID=44`；
- GDB 的 `sObj`/`objInfo->trcOutData[i]` 给出 `distX=5.98999977`、`distY=-4.71000004`、
  `length=4.75`、`width=1.84000003`、`yawAng=53.0400009`、`velX=-0.569999993`、
  `velY=3.98000002`、`velAbsX=3.81999993`、`fTTC=1.01999998`、`fDDCI=8.38000011`、
  `objFctaWarningFlag=5`、`rightFctaFlag=true`；
- 运行态局部条件值包括 `bFctaDetectFlg=true`、`fTTMX=1.01918888`、
  `fFctaTTMXThresh=2.56308889`、`fTTMXObj=0`、`fFctaTTMYThresh=2.79999995`、
  `fTTMY=0.564559579`；`adasWarning->bRightFctaWarning=2` 和
  `bFctaRightWarningFlg=true` 在 `UpdateFctaRightWarningStatus` 观察到；
- `adasFunc.c:9908` 速度门为 true，`adasFunc.c:9998` 的 `rightFctaRoi->num` 为
  `10 > 0`，`adasFunc.c:10094` 的完整 FCTA 条件代入后为 true，目标 flag 分支
  `objInfo->trcOutData[i].objFctaWarningFlag > WarningFlag_Normal` 也为 true；
- GDB 同帧 `objPoly` 与 `rightRoi` 的几何关系为 `observed_disjoint`。这不是矛盾：当前
  FCTA 主判定使用 `fTTMX/fTTMY/fTTMXObj`、预测交点和分支状态，不能用简单 polygon
  相交替代完整功能逻辑；
- 公共运行态仍观察到 `FCTA_R=2` 在 `frame=47876` 出现 0→非零线索，`47877` 保持 active；
  这证明算法/公共输出层，不证明 CAN Tx 上升沿。源码候选链继续显示
  `RRadar_FCTA_Warning_Right_S <- (AdasStM.Frontright_FCTA == 2) ? 1u:0u`
  → `RteLite_Write_RRadar_FCTA_Warning_Right_S` → `Com_SendSignal`，但没有把静态候选
  冒充 runtime CAN 观测。

报告的完整 source condition trace 为 `38 total / 11 satisfied / 3 not_satisfied /
22 not_evaluable / 2 unsupported`；在 FCTA/R scope 为 `28 / 9 / 1 / 16 / 2`。因此报告
可以对主 FCTA 条件给出“当前观测值满足”的文字解释，但不会因为其他状态机/后处理条件缺少
精确 stop-location 就给出无依据的“最终正报/误报”结论。跨多个 GDB stop 的 `info locals`
只作为运行态展示，未带 source-line binding 时不参与条件真值，避免把 handler 更新前的
`rightFctaWarningNum=0` 误用于后续 `adasFunc.c:10255`。

本轮还修正了三个通用性问题：

1. `event-code-path` 从 `code-context` 派生时继承 enclosing context 的 source identity；
2. source snapshot 比较优先使用真正的 `source_snapshot_hash/snapshot_hash`，再回退 legacy
   `source_index_hash/code_index_hash`；
3. runtime query 的有界切片优先保留同帧 GDB、selected object 和公共 frame；单纯
   `No symbol` 只产生字段缺口，不自动宣称回放受到扰动。

Pi catalog 已重新生成：`58` 个可暴露能力（`54 modules + 4 tools`），其中
`runtime-evidence-compose` 用于组合公共 runtime 与 GDB producer，仍不改变 Pi 的唯一
编排入口。验证结果：radarAnalyze 相关定向组合 `120 passed`，sibling SSH/GDB runner
定向测试 `8 passed`，schema validation 覆盖 diagnostic report、narrative、runtime
evidence、preflight、event-code-path、code-context、runtime-debug-plan 均通过；没有做
全量回归。
Pi RPC 冒烟在默认 provider 探测（本机列表探测较慢）下 30 秒超时；显式指定当前可用的
`bosch-qwen3_6 / Qwen3.5-27B-FP16` 后返回 `PONG`、`agent_settled`。`scripts/pi_rpc_smoke.py`
现支持 `--provider/--model`，并在 Windows legacy console code page 下强制 UTF-8 输出。一次
带完整证据的 Pi 详细问题回合在模型响应阶段超时，但 deterministic anchor 已生成并保留；该次
历史报告产物已在 2026-09-03 清理，当前复核入口为
`outputs/single_case_actual_CRGVI1829_20260903_final/diagnostic-report.html`。Pi 返回
`ok=false` 且产物保留，未把超时伪装成成功。

随后用同一 evidence anchor、显式 `case_dir` 和当前 provider 执行短交互验收，Pi 返回
`ok=true / agent_settled`，创建并完成 `AnalysisRun=run-20260902T055424-ce7520198c`，
回答中明确列出已满足的 `adasFunc.c:9908/9962/9973/9998/10040/10094/10141` 条件、
CAN/后处理缺口；该次短验收报告已在 2026-09-03 清理，保留的当前报告入口仍为
`outputs/single_case_actual_CRGVI1829_20260903_final/diagnostic-report.html`。

### 23.47 几何图与 FCTA 真实判定语义校正（2026-09-02）

针对报告截图中“目标没有进入 ROI”的疑问，重新对当前 `BYD_UKE` 的
`adasFunc.c` 做了源码级核对。结论不是把图形强行画成相交，而是将三种不同语义拆开：

1. **当前时刻的几何关系**：GDB 在 `frameID=47877` 观察到的 `objPoly` 与
   `rightRoi` 进行同坐标系多边形关系计算。目标四角约为
   `(6.683,-2.259) / (3.827,-6.055) / (5.297,-7.161) / (8.153,-3.365)`，
   `rightRoi` 的横向范围为 `y=0 ... -1.0855`，因此当前关系确实是
   `observed_disjoint`。图形计算与坐标语义 `x-forward,y-positive-left` 一致；目标
   `yawAng=53.0400009` 也用于生成旋转后的四角，不能用轴对齐框替代。
2. **源码的 ROI 可用性分支**：FCTA 当前实现中，`adasFunc.c` 约 `9998` 行的
   `rightFctaRoi->num > 0U` 只表示右侧 ROI 已生成，随后约 `10000` 行
   `rightFlag = true`。该代码路径并没有在此处调用 `IsRectangleIntersect(objPoly,
   rightFctaRoi)` 来设置 `rightFlag`；文件中的“Determine whether two polygons intersect”注释
   与实际语句不一致，不能把 `rightFlag=true` 解读为“目标当前已侵入 ROI”。
3. **FCTA 的预测穿越判定**：`FctaDirectRunning` 和后续条件使用目标速度、目标 yaw、
   `fInterX/fInterY`、`fTTMX/fTTMY/fTTMXObj` 等预测量判断未来是否会穿越车辆路径。当前
   GDB 观察到 `fInterX≈8.38272381`（结构体 token `sObj->fInterX≈8.34897423`）、
   `fInterY=0`、`fTTMY≈0.564559579s`。因此预测点在右 ROI 的边界/中心线附近，不能被画成
   当前目标多边形已经进入 ROI；正确的图应同时显示目标实线多边形、当前 ROI、从目标中心
   指向预测点的虚线和预测点标记。

本轮报告投影已按上述语义更新：`instantaneous=observed_disjoint`、源码 gate 单独展示、
`fInterX/fInterY/fTTMY` 作为 runtime prediction 单独展示。以后不同功能也必须先从当前
source 条件和 runtime token 推导“几何关系/可用性 gate/预测关系”，禁止在通用渲染器中把
“ROI flag”固化为“polygon containment”。

### 23.48 无 CAN 输入时的报警端点策略（2026-09-02）

rosbag 不含 CAN 数据时，诊断不再把 CAN Tx 当作强制前置条件。报告先探测 CAN 数据状态：
`present / absent / not_detected / unknown`，然后由 `output_policy` 选择终点。没有可证明
CAN 数据时，终点为算法最终输出（例如本例公共运行态 `FCTA_R=2`），并在文字中明确这是
“算法输出层观察到的报警”，不声称 CAN 上升沿；只有实际存在 CAN 观测时，才把 CAN Tx
作为更下游的独立证据。该策略不改变 source output chain，只避免因输入缺少 CAN 而掩盖已经
能够确认的算法输出和条件链。

### 23.49 结构化数据到自然语言诊断流程的产品要求（2026-09-02）

用户提供的 BSD 结构化对象分析示例明确了详细报告应有的阅读顺序：

```text
输入对象/自车属性
  → 单位和坐标语义确认
  → 当前 source 中的参数/阈值与真实值绑定
  → 按 source 顺序逐条判断 if/else 分支
  → ROI/几何或预测关系单独核对
  → 算法最终输出/Can Tx 端点
  → “为什么报警、哪些条件满足、哪些条件未满足或无法证明”的结论
```

因此 `diagnostic_narrative` 新增 `diagnostic-analysis-flow.v1`。它不是第二套规则引擎，
而是把已有 `condition-trace` 的 `expression`、`substituted_expression`、真实
`bindings`、`missing_tokens` 和 source ref 编排成四个可追溯步骤。HTML 以流程卡片展示：

- 输入工况卡：显示当前功能/侧别/雷达/frame/objID，以及真实自车和目标 token；
- 条件代入卡：显示当前 source 条件、参数值、代入表达式和 `satisfied/not_satisfied/
  not_evaluable/unsupported`，不把不同分支伪装成一个 AND 链；
- 几何/预测卡：显示当前 polygon/ROI 关系、源码 ROI 可用性 gate 和 runtime 预测点；
- 输出结论卡：显示算法或 CAN 端点、`should_alert`、支持结论的源码行和剩余缺口。

该读模型不绑定 BSD、FCTA 或固定变量名。当前 BSD 示例中的
`fBsdObjWarningSpd/fBsdObjWarningRelVx` 等参数，若能从当前 source/index 和同帧数据绑定，
会以真实 token 进入条件卡；若无法绑定，报告必须指出缺口，不能照抄用户假设的
`bsdSystemState==2` 或自行补齐自车状态。AI 可以对这个流程做自然语言解释和根因排序，但
确定性层负责事实、单位、条件代入和证据 provenance。

### 23.50 详细报告的信息架构与可读性约束（2026-09-02）

用户进一步确认：详细报告不能把参数、图形、自然语言和原始 JSON 混在一个长页面中。
当前采用固定但功能无关的阅读层级：

```text
结论摘要
  → Parameters / operating point（结构化表格）
  → Scene / selected frame（当前 polygon、ROI、朝向、预测图层）
  → Diagnostic reasoning flow（自然语言和条件代入）
  → Alarm evidence timeline
  → 可折叠的完整证据、runtime/GDB、代码链和调试入口
```

参数表的每行至少保留：分组、业务角色、真实 code token、值、单位、证据状态、来源/frame。
自车输入、目标输入、源码参数/条件、runtime 中间量、几何预测不能因为值相同而静默合并。
表格采用容器内滚动，预测字段和关键源码参数在有限首屏预算内优先出现；完整值仍在
`diagnosis-report.json`/selected event artifact 中。

文字流程和图形流程必须共享同一个确定性 read model：
`diagnostic-analysis-flow.v1`。图中的实线目标/ROI只表示当前几何，虚线和预测点只表示
runtime/code 给出的未来关系；文字必须明确这个区别。UI 重排不得改变
`condition_trace`、`geometry_projection`、`runtime evidence` 中的值、状态或 provenance。

本次实际报告验证了该布局：参数表 73 行（容器内滚动，72 条事实行加表头）、4 个诊断流程步骤、
10 个关键条件卡；HTML 结构解析无未闭合标签，`diagnostic-report.v1` 和
`diagnostic-narrative.v1` schema validation 通过。

### 23.51 GDB 生效判定与 arbe 报警灯真实来源（2026-09-02）

针对“GDB 是否真的生效、报警灯参考什么”的现场核验结果如下：

- GDB 隔离 runner 返回 `returncode=0`，`gdb-session.v1.status=succeeded`，transcript
  已被归一化为 `runtime-case-evidence.v1`；GDB 证据层状态为 `observed`；
- 同一 GDB observation 的身份为 `radar_id=2、frame_id=47877、object_id=44、
  algorithm_index=0`，source location 为当前 `adasFunc.c:10093`，与报告选定事件一致；
- 该次 GDB 读取到 `adasWarning->bRightFctaWarning=2`、
  `bFctaRightWarningFlg=true`、`objInfo->trcOutData[i].objFctaWarningFlag=5`、
  `objInfo->trcOutData[i].rightFctaFlag=true`、`i=0`、`frameID=47877`，以及
  `fTTMX/fTTMY/fInterX/fInterY` 和自车/目标属性；
- 共有 `173` 个已解析运行时字段，另有 `10` 个探针在某些 stop 上不可用。不可用探针只
  形成缺口，不推翻已命中的 GDB 事实；跨 stop 的 `rightFctaWarningNum=0` 不能替代
  `adasWarning->bRightFctaWarning=2`，报告会把两者保留为不同的程序阶段。

通过 SSH 只读检查当前 arbe source 后确认报警灯链路：

```text
algo_adasWarning
  → visualization_node.cpp:4063-4078 填充 /corner_radar/warning_status
  → visualization_node.cpp:4080-4087 复制同一数组并加 frame_counter，发布
    /corner_radar/warning_status_with_frame
  → viewpanel.cpp:2276-2291 消费 warning_status 并按 radar_id 映射显示灯
```

发布消息 `/corner_radar/warning_status` 的数组中，`data[0]` 是 `radar_id`，`data[1..15]`
依次对应 `bLeftBsdWarning` 到 `bRightFctbWarning`，所以 `data[13]` 是 `FCTA_R`、
`data[15]` 是 `FCTB_R`。GUI 回调先用 `adas_warning_status[radar_id][i] = msg->data[i+1]`
去掉第 0 位；当 `radar_id=2` 时，`viewpanel.cpp:2288-2291` 读取存储位 `[12]` 和 `[14]`，
分别更新 `adas_light_label[12]=fctaRight` 和 `adas_light_label[14]=fctbRight`。
因此本例 `FCTA_R` 的 GUI 灯参考的是 `algo_adasWarning.bRightFctaWarning`，经
`/corner_radar/warning_status` 的发布数组第 `13` 位进入显示；不是目标 flag，也不是 CAN。
`warning_status_with_frame` 只是把同一算法数组加上 `frame_counter`，本例的 `FCTA_R` 位为
`data[14]`，用于逐帧定位，不是 GUI 另一个独立报警源。当前 rosbag 无 CAN 时，报告以这条
算法输出链为最终诊断终点，不要求 CAN 信号。

本次运行方式也被固化到报告：输入是录制 bag，算法在 arbe 工作区回放，`HILMODEL=2`，
策略为 `sgu_injection`（SGU 目标级注入），在目标分析帧前使用 5 帧预热；这与点云级仿真
是不同执行模式。未来切换模式必须由当前 plan/preflight 明确声明，不从数据文件名猜测。

报告的 GDB 入口现支持可选 `gdb_session_path`。它把 `gdb-session.v1` 的 runner 成功状态、
transcript 是否已归一化、GDB observation 是否与 frame/radar/objID 对齐分开记录，避免把
“GDB 命令执行成功”误写成“所有变量都准确”。

本例还明确记录了报警沿与 GDB 帧的关系：算法输出 `FCTA_R=2` 的 0→非零上升沿为
`frame=47876`，本次 GDB 选定并成功命中的 `frame=47877` 是上升沿后的 1 帧。因此当前报告
可以确认“报警后的活动帧内部状态”，但不能把它误写成“GDB 已在精确上升沿停住”；若要
分析上升沿瞬间，Pi 应复用同一 source/binary/SGU plan，将 target frame 改为 `47876` 后
再次执行 GDB，并在报告中对比两帧。
### 23.52 报告首屏结论与报警帧数据表（2026-09-02）

用户验收口径进一步收敛：详细报告首屏必须先给出一句可直接使用的总结性结论，随后用表格
呈现这句结论所依据的报警帧数据；不能让用户在大量内部层级、缺失项或 JSON 中自行拼接答案。

因此 HTML 读模型固定为：

```text
总结性分析结论
  → 报警帧关键数据表（自车、目标、源码条件、runtime 中间量、输出）
  → 报警工况图
  → 报警命中流程（自然语言 + 可展开真实源码表达式）
```

报告的主结论使用 arbe 可视化工具报警灯对应的算法输出作为默认终点。CAN 只保留为可选的
下游辅助证据，不因为输入中没有 CAN 而在主结论重复提示，也不要求用户关心 CAN 是否存在。
当当前目标矩形与 ROI 瞬时不相交时，报告必须同时展示：瞬时几何关系、源码是否真的使用
polygon/ROI 相交、运行态预测交点/到达时间以及最终输出。不能用图形相交与否直接替代代码条件。

本例的总结结论应能直接表达：`FCTA_R` 在 `frameID=47877` 的 arbe 报警灯对应算法输出
已经报警；`objID=44`（`i=0`）的 FCTA 代码条件已经命中。当前目标矩形与 `rightFctaRoi`
瞬时不相交并不否定报警，因为当前 source 的 `FrontCrossTrafficAlertAndBrake` 先用
`rightFctaRoi->num > 0U` 使右侧路径生效，再使用 `fInterX/fInterY/fTTMX/fTTMXObj/fTTMY`
等运动预测结果和阈值判断；本例预测点落在自车横向轴上，`fTTMY` 为可接受的未来到达时间。
因此就当前代码而言属于“算法输出与代码路径一致”，而不是“当前矩形必须已经压入 ROI”。

### 23.53 Pi 代码分析能力和动态条件链约束（2026-09-03）

Pi 本身可以完成通用的代码阅读、逻辑解释、条件比较、假设排序和下一步规划，但不能把模型
常识当作当前项目的源码事实。正式分析必须先由当前 source context 生成/读取 code index，
再通过 `code-context`、`code-analyze`、`event-code-path` 获取真实 entry/caller/callee、
条件、参数、变量和输出，Pi 只负责在这些 evidence 之上组织解释。

新增 `event-code-path.v1.resolution.condition_chain` 作为动态条件链：它从当前 code index 的
caller→helper→event root→callee 候选关系收集条件，给每行保留 `chain_relation`、函数顺序和
源码行顺序。它不把所有函数或分支拼成一个无条件 AND；运行时没有命中的分支仍只能标为候选，
同帧变量缺失则为 `not_evaluable`。这使状态机、车速、目标 `dynFlg`、ROI、预测、保持/计数和
输出的顺序随项目代码变化，而不是固化为 FCTA/FCTB 模板。

Pi 的独立使用结论：当前已有可用的 `python cli.py pi` 产品入口、Pi RPC、自动生成的
`registerTool`、`pi_tool_bridge`、AnalysisRun/AnalysisStep 和 54 个可暴露原子能力；
但尚未形成安装后零配置的一键发行包。独立运行仍需安装 Python 依赖、Node/Pi、LLM provider
配置、项目/source context 和相应的远程 arbe profile。副作用动作继续采用“计划→确认→执行”，
静态预检查和报告可在无模型时独立生成，Pi/AI 只做调度和解释。

### 23.54 动态条件链与独立 CLI 验证（2026-09-03）

当前 CRGVI-1829 的 source index 重新生成了 `condition_chain`：共 162 条候选源码条件，
覆盖 `FctaFctbUpdateStatus`、`ResetFctaRoi`、`FrontRadarAdas`、
`FrontCrossTrafficAlertAndBrake`、`FctaSkipFlg`、目标处理 helper 和
`UpdateFctaRightWarningStatus`。其中 `FctaSkipFlg` 的 `sObj->dynFlg < 1U || sObj->dynFlg >3U`
已进入报警条件链，当前同帧值 `sObj->dynFlg=2`，代入为 `2 < 1 or 2 >3`，结果为 false，
表示该目标没有在此处被跳过。

动态 GDB 计划由当前链路自动选取 source-condition probes，当前计划会覆盖 event root 的
预测条件、状态机 helper、`FrontRadarAdas` 系统状态 gate 和 `FctaSkipFlg` dyn gate；动态计划的
一次性中间产物已在 2026-09-03 清理，当前保留的可复核计划为
`outputs/single_case_actual_CRGVI1829_20260902/runtime-debug-plan-source-condition.json`。
一次真实隔离 runner 调用返回成功，但远端 `rosnode info` 报告节点通信失败，生成的 session
没有有效 GDB observation，因此该次结果没有覆盖既有的 `gdb_confirmation=confirmed` 报告事实。
这说明独立工具链已能生成动态计划，但“任意远端环境都稳定产出 runtime observation”仍需
作为运行环境适配问题继续验收，不能把 runner 返回码单独当作 GDB 取证成功。

直接 CLI 报告冒烟已通过：`python cli.py diagnosis-report ... --gdb-session ...` 返回
`ok=true/status=ready`，`response_mode=summary` 仅返回有界摘要和 artifact ref，不再把完整
condition trace 重复塞给 Pi；完整报告仍落盘到 HTML/JSON/Markdown。

### 23.55 用户可见结论与代码证据分离（2026-09-03）

用户验收明确要求：HTML 不能把大片 C/C++ 表达式罗列当作分析结论，必须像工程师阅读数据
和代码后的说明一样，先讲清楚工况、关键变量、命中条件和最终判断；真实源码表达式仍要保留，
但放到可展开的源码证据中。

当前报告读模型已调整为：

```text
一句总结结论
  → 自然语言条件链表（步骤、源码函数/位置、判断说明、关键同帧值、结果）
  → 报警帧变量表（真实 code token、值、单位、来源、frame）
  → 工况图
  → 条件卡和“查看源码表达式”详情
```

自然语言条件链仍由当前 `condition_chain` 的真实条件和 bindings 生成，不由模板虚构。当前
FCTA 示例会说明“状态机 gate 是否取得、自车速度是否通过、`sObj->dynFlg=2` 是否触发跳过、
ROI 是否可用、预测/到达条件是否成立、报警灯输出是否置位”；源码表达式和 substituted expression
只在对应行展开。表格保留真实变量，文字不再重复整段代码。

### 23.56 报警输出之后的 FCT/ASW 对外映射（2026-09-03）

用户进一步要求诊断叙事不能停在 `adasWarning`，还要继续说明算法报警值如何进入 FCT/ASW
内部最终信号和对外映射。为避免把某个版本的 FCTA 行号固化成规则，本次采用两段式
实时源码扫描：

1. `arbe-preflight` 继续从当前 YAML 选中的 COEM 扫描 `WriteSignal`/RteLite；
2. 对表达式中的真实 C/C++ member path，在当前 COEM 源码中扫描有效赋值、注释赋值和
   生产函数引用，生成 `arbe-source-output-chain.v1`；报告再把同帧 runtime/GDB 值与这些
   source rows 合成为 `diagnostic-output-chain.v1`。

这次通过 SSH 对 `10.190.171.44:/home/hoz2wx/CR60LIGHT/cr60_light_arbe` 的当前源码做了
只读刷新，当前 `BYD_UKE` 的 FCTA_R 输出链证据为：

```text
adasWarning->bRightFctaWarning = 2                 [GDB, frameID=47877, observed]
  -> AdasStM.Frontright_FCTA =
     ADAS_Warn_Process_FrontRight_FCTA(PEROutput.adasWarning.bRightFctaWarning)
     [ADAS_HMI.c:3623, source_active]
  -> RRadar_FCTA_Warning_Right_S =
     (AdasStM.Frontright_FCTA == 2) ? 1u:0u
     [RteComMapping_Tx.c:147, source_candidate]
  -> RteLite_Write_RRadar_FCTA_Warning_Right_S
  -> Com_SendSignal [rteLite_PubCan_FCRonly.c:177, source_candidate]
```

`ADAS_HMI.c:3091` 还能确认 `ADAS_Warn_Process_FrontRight_FCTA` 的函数定义。当前 GDB
停点在算法 `adasFunc.c:10093`，并没有在 ASW 映射调用点同帧取到
`AdasStM.Frontright_FCTA`，所以报告的结论是“算法报警已观察；下游内部值和对外信号路径
已找到但尚未 runtime 证实”，而不是声称对外 signal 已发送。之后若 GDB 在映射函数处抓到
内部值，报告将同一 `diagnostic-output-chain.v1` 步骤升级为 `runtime_observed`，不改动前面
的算法事实。

HTML 的“报警命中流程”现按以下叙述顺序呈现：同帧工况和代码条件 → 算法输出报警 →
FCT/ASW 内部赋值 → 对外 signal 条件 → transport 调用。源码表达式仍可折叠查看，首屏
自然语言只保留关键值和结论；映射表保留真实 token、源码位置和证据状态。

本次实际产物：

- preflight：`outputs/arbe_preflight_refresh_20260903_output_chain_v3.json`
- 报告：`outputs/single_case_actual_CRGVI1829_20260903_final/diagnostic-report.html`
- 新契约：`contracts/diagnostic-output-chain.v1.schema.json`

这项能力仍是跨功能的输出链投影，不包含 FCTA/FCTB 固定判断；不同项目/代码版本只要
preflight 能读到当前源码，便重新生成自己的内部/对外链路。
