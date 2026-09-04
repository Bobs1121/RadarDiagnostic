
# CR60 Pi Unified Platform：arbe 核心能力复用调研

版本：arbe-reuse-research.v2

日期：2026-08-30

状态：已完成一次实际服务器只读调研，待用户确认真实操作后进入接口评审

## 1. 调研范围和证据边界

本次通过 SSH 只读检查了服务器 10.190.171.44 上的：

    /home/hoz2wx/CR60LIGHT/cr60_light_arbe

外层仓当前 HEAD：

    4c171298b2c3583509ea9e3da222b90ba0a9e513
    branch: develop_LGU_Simulation...origin/develop_LGU_Simulation

src/algo_source 子仓当前 HEAD：

    a81b08a38f316a3d25bfcbcad6dcfc822d24b990
    detached HEAD: BYD_UKE_BL02RC05-1374-ga81b08a38

外层和子仓都有未提交改动。外层状态包含 .vscode/launch.json、launch_config_4radars.yaml、visualization_node.cpp、CUDA 配置文件等改动；子仓状态包含 paraDefine.h、adasFunc.c 和 tools/ADAS_Tools 改动。本次没有修改、checkout、编译、启动或停止任何远程进程。

证据来源包括：

- src/arbe_phoenix_radar_driver-master/arbe_gui/CMakeLists.txt
- src/arbe_phoenix_radar_driver-master/arbe_gui/src/arbe_visualization_engine/visualization_node.cpp
- src/rviz_bag_2e44lc_AtoSar_LGU_Folder/src/my_rviz_plugin/src/bag_reader.cpp
- src/rviz_bag_2e44lc_AtoSar_LGU_Folder/src/my_rviz_plugin/src/my_rviz_plugin.cpp
- src/rviz_bag_2e44lc_AtoSar_LGU_Folder/src/my_rviz_plugin/include/my_rviz_plugin/bag_reader.h
- src/algo_source/adas/symmetry/perception/include/perception_public_api.h
- src/algo_source/adas/symmetry/perception/include/perception_public_def.h
- src/algo_source/adas/symmetry/perception/include/structDefine.h
- src/algo_source/adas/symmetry/perception/src/postProcess.c
- src/algo_source/adas/symmetry/perception/src/debugOutput.c
- src/algo_source/coem/BYD_UKE/components/AswPerception/func/adasFunc.c
- src/rviz_bag_2e44lc_AtoSar_LGU_Folder/src/my_rviz_plugin/docs/frame_player_operation_guide_cn.md

## 2. 结论先行

arbe 的核心代码可以成为统一工具的一部分，但复用方式应是“复用能力，通过适配器隔离实现”，不是把 arbe 源码整体拷贝进 radarAnalyze，也不是让 Pi 直接操作任意 shell。

建议拆成四层：

1. radarAnalyze 保持独立，拥有输入契约、任务编排、证据合并、代码分析、AI 解释和 HTML 交付。
2. arbe adapter 复用现有 BagReader、ROS message、frame-sync 语义和 launch/config 约定，通过受控接口提供回放能力。
3. arbe runtime bridge 作为可选的 arbe feature 模块，提供稳定的输入/输出/运行时快照接口；不改变默认算法行为。
4. GDB runtime provider 作为外部进程能力，读取无法通过 ROS topic 暴露的局部变量、静态状态和调用栈。

这样既不重复造已有的 bag 播放轮子，也不把 Qt/RViz、固定 topic 和某一版算法的内部全局变量变成统一平台的硬依赖。

## 3. arbe 的实际核心分层

### 3.1 构建和算法宿主：arbe_visualization_engine

arbe_gui/CMakeLists.txt 当前直接把两类代码编译进同一个 arbe_visualization_engine 可执行文件：

- src/arbe_visualization_engine/visualization_node.cpp
- src/algo_source/adas/symmetry/perception/src/*.c
- src/algo_source/coem/<COEM_NAME>/components/AswPerception/*.c

COEM_NAME 从 Config/launch_config_4radars.yaml 的 car.type 动态解析；不存在算法目录或 COEM 源文件会在 CMake 阶段失败。当前 CMake 为 arbe_visualization_engine 设置 BUILDMODEL=2。

这说明它实际上是“回灌输入 + 算法源代码 + 显示/ROS 输出”的运行时宿主，而不只是 UI。它是最有价值的复用边界，但应以进程/ROS 接口复用，不应把它作为 Python 包导入。

### 3.2 输入回灌和显示：visualization_node.cpp

关键回调 corner_radar_post_process_data_callback() 的实际链路为：

    /wf/corner_radar/lgu_data_<radar_id>
        → msg->frameID / msg->header.stamp
        → PERInfoOutStruct* mAlgoPerOutputPtr
        → dotTrans → point cloud display/input
        → HILMODEL != 0 时 objTrans[i] → algo_objInfo.trcOutData[k]
        → PostProcessMainTI(...)
        → warning / ROI / object / radar_info / PlaySingleFrame ACK

在 HIL 路径中，源 objTrans[i] 经过空 SGU 跳过后写入 trcOutData[k]，所以 i 和 k 不是同一个索引，工具必须同时记录：

    raw_sgu_index = i
    algorithm_object_index = k
    objInfo->trcOutData[k].objID

当前 PostProcessMainTI 调用位于 visualization_node.cpp，其调用前后是天然的输入/输出快照点；但 FCTA/FCTB 的 fTTMX、fTTMY、fDDCI、fInterX、fInterY、fIntAng 等局部变量只在 adasFunc.c 内部出现，不能仅靠外部 ROS 订阅获得。

### 3.3 结构化算法 API 和真实运行字段

perception_public_api.h 的 PERInfoOutStruct 定义了压缩后的输入输出边界：

    frameID, LGUNum, SGUNum
    objTrans[LGU_OUT_NUM_SGU]
    egoCarInfoTrans
    calibInfoTrans
    ADASInfoTrans
    BLDInfoTrans
    dotTrans[MAX_DOT_OUT_NUM]

perception_public_def.h 的 objOutDataStruct 定义了算法对象输出字段，包括：

    distX, distY, length, width, yawAng
    objID, objType, dynFlg, referPt, lifeCycle
    velX, velY, velAbsX, velAbsY
    fTTC, fDDCI, fPredTTC
    distZ, height, distXRefer, distYRefer
    meaState, objTypeProp, existProb, yawRate
    fIntAng, fInterX, fInterY
    left/right Bsd/Lca/Dow/Rcta/Rctb/Fcta/Fctb flags
    variance, acceleration, lost, roadMap, roadMapFit

这是一个非常好的运行时 schema 来源，但字段布局、压缩比例和条件编译受当前子仓版本影响。因此工具应在每次 source context 变化时重新探测结构，不在 radarAnalyze 中复制一份固定 C struct。

### 3.4 算法阶段和 HIL/SGU 语义

postProcess.c 的当前流程为：

    DataProcInit
      → VarGlobal
      → CalEgoCarAddInfo_CR
      → HILMODEL == 0 时 point/filter/cluster/track/calibration
      → PF_BUILD_FUNTEST_SGU_INJECTION 时 replace_objInfo_with_injection
      → AdasFunc

当前 HILMODEL=2 时，point-cloud 的内部感知链路会被条件编译分支绕开，但 AdasFunc 仍会消费目标输入并执行 FOV、筛选、ROI、TTC/DDCI、计数器、保持和输出状态逻辑。因而：

- SGU 运行时调试可以定位功能层和 situation 层；
- 它不能证明 point-cloud perception 已产生了该目标；
- 报告必须显示被绕过的感知阶段；
- point-cloud 模式必须使用独立的前置状态建立策略。

当前 BYD_UKE 还存在独立的 ASW/CAN 调度链：`OsTask_MMW.c` 在 `Algo_Perception` 后调用 `ASWOUT_OutCalc_RadarWarnSignal`、`RteComMapping_TxRunnable` 和 `RteComMapping_TxSguRunable`；`RteComMapping_TxRunnable_FuncSignal` 再根据 `PEROutput.adasWarning`、`AdasStM` 和控制器位置调用宏 `RteComMapping_WriteSignal`，该宏展开为 `RteLite_Write_<signal_token>`。这条链是用户所说“算法内部向 CAN 输出”的真实候选落点，必须按当前 COEM/host 动态探测，不能用 visualization_node 的 ROS topic 代替。

### 3.5 现有播放器：BagReader

BagReader 是当前最值得复用的回放实现。它已经具备：

- 读取 /wf/corner_radar/lgu_data_0..4、相机、车辆、warning、XCP、公 CAN、manual tag；
- 按所有 LGU 消息的 bag 时间构造 lgu_playback_timeline_；
- jumpToFrame：按时间排序后的单 LGU event；
- jumpToSceneFrame：以一个主雷达为锚点，按时间差补齐其他雷达；
- findLatestAtOrBefore：对车辆/XCP/CAN/warning 使用不晚于当前时刻的最新消息；
- findClosestWithin：对相机和场景副雷达使用最近消息；
- playBag(scene_mode, respect_bag_timing)：实时节拍或加速播放；
- PlaySingleFrame 的 status=0/1 闭环完成确认；
- 同一路 radar 最多一帧在途，避免慢算法时乱序；
- 到 bag 末尾等待未完成的 algorithm callback。

这些逻辑不应在统一工具中重新实现一套“近似播放器”。

但它不是现成的通用服务：它依赖 ROS/Qt/RViz message instance，API 只在 my_rviz_plugin 内部，topic 列表和 slot 数量是固定的，且 PlaySingleFrame 不是 load/play/seek API。因此第一步应做 arbe_replay_adapter，第二步再考虑把回放核心抽成 arbe_replay_core 或提供 headless service。

### 3.6 现有 my_rviz_plugin 的控制面

MyRvizPlugin 将 BagReader 的消息回调发布为 ROS 消息：

    pointcloud_pub0..4       → /wf/corner_radar/lgu_data_0..4
    warning_pub_             → /corner_radar/warning_status_raw
    car_pub_                 → /wf/car_id6/parsed2
    XCP publishers           → /wf/xcp_signals/<side>/parsed
    public CAN publishers    → /front/signals, /rear/signals
    camera publishers        → /cv_camera_<n>/image_raw/compressed

它还提供 /play_single_frame_0..4 服务。该服务的真实用途是算法节点回告：

    status=0: 算法收到当前 radar_pos/frame_id
    status=1: 算法处理完当前 radar_pos/frame_id

它不是外部客户端用于加载 bag、seek、pause、resume 的公共控制接口。统一工具不能把它误用成播放器 RPC。

### 3.7 VSCode 默认入口和 radar 进程选择

用户提供的默认 `.vscode/launch.json` 入口是：

~~~json
{
  "name": "ROS: Attach",
  "type": "ros",
  "request": "attach"
}
~~~

服务器当前文件还包含一个 ROS Launch 配置，target 为：

~~~text
/home/hoz2wx/CR60LIGHT/cr60_light_arbe/src/arbe_phoenix_radar_driver-master/arbe_gui/launch/rviz-arbe.launch
~~~

实际运行进程使用：

~~~text
devel/lib/arbe_phoenix_radar_driver/arbe_visualization_engine
processId: ${command:pickProcess}
~~~

`arbe_radar_vis.launch` 会把同一个可执行文件放到 radar namespace，例如：

~~~text
/radar1_visualization_engine/arbe_visualization_engine
/radar2_visualization_engine/arbe_visualization_engine
/radar3_visualization_engine/arbe_visualization_engine
/radar4_visualization_engine/arbe_visualization_engine
~~~

因此工具不能只用 executable basename 或 PID 猜目标，必须联合核对 namespace、`Radar_ID`、`radar_pos`、launch 参数和 binary/source fingerprint。这也是 headless GDB 与 VSCode attach 必须共享的 target resolver。

当前服务器 launch.json 还存在一个针对单个样例的配置：`radar2 FCTA/FCTB id44`，条件断点固定到了 `adasFunc.c:7765`、`adasFunc.c:7833` 和 `objID == 44`。它证明当前团队已经在用“按 radar + 功能 + objID 生成断点”的方式，但它不能作为统一工具的默认模板。统一工具只能把它当作历史样例，必须按当前 source context、事件、frame、目标和真实 scope 重新生成。

### 3.8 现有算法 debug 输出

debugOutput.c 已有 CSV 输出能力：

    _kf.csv          mature/candidate tracking 状态
    _cluAndQly.csv   cluster/quality
    _pt.csv          点迹及过滤/聚类字段
    _out.csv         objOutDataStruct 的大量输出字段
    _Ego.csv         g_egoCarAddInfo 和场景状态
    _Adas.csv        ADAS warning 状态
    _Calib.csv       calibration
    _BLD_time.csv    BLD
    _cfar.csv        CFAR 汇总
    _RD.csv          RD 调试数据

它可以作为离线证据或性能调试的补充，但当前存在三个限制：

1. 输出路径、文件生命周期和开关依赖算法全局变量，存在固定历史路径如 /home/weifu/...；
2. 对称 perception 的 KfFile() 调用在 #if 0 == HILMODEL 分支，HILMODEL=2 下不能默认假设这些文件会生成；
3. CSV 是算法主动选择的字段，不等于所有局部 runtime 变量，也没有统一 provenance/Frame domain contract。

因此复用定位为 optional debug-output collector，不能替代 GDB runtime provider。

### 3.9 服务器 handoff 和旧脚本的可信度分层

服务器 `~/CR60LIGHT/data/tool_handoff/handoff_FCTAFCTB.md` 和 `fcta_fctb_analyze.py` 是很有价值的工程材料，但应作为历史流程/候选实现，而不是当前平台的真值源。

已确认的可复用信息：

- 问题清单 Excel 的 B 列是 Ticket No.，C 列是触发功能，E 列是车型，G 列是问题触发版本，J 列是数据路径或数据说明；
- 当前 `CRGVI-1829` 样例行显示车型 `QZHCX`、版本 `BL03RC02.7_S` 和对应 bag 路径；
- 这支持“先传数据，再由数据绑定版本/车型准备 arbe”的用户流程；
- handoff 中记录的 FCTA/FCTB 调参、warning topic、frame_id 和 XCP 信息可以作为 schema 探索线索。

需要纠正的边界：

- 旧 handoff 把 `/play_single_frame_<n>` 描述为可命令 frame player 跳帧的接口；当前 `BagReader`/`MyRvizPlugin` 源码证明它主要是算法处理 `status=0/1` 的完成 ACK，不是外部 load/play/seek RPC；
- `fcta_fctb_analyze.py` 固化了 FCTA/FCTB、warning 位和一套阈值公式，只能作为专项历史脚本，不能覆盖所有功能、代码版本和动态参数；
- 旧脚本读取时间近似的 `objectlist` 作为触发目标候选，统一工具必须继续遵守 same-frame/same-identity gate。

因此，handoff 的数据字段和操作经验进入 `source/material provenance`，其中与当前仓库源码冲突的部分以当前 active source 和 runtime 证据为准，并在报告中记录 conflict。

## 4. 能否作为统一工具模块：复用决策表

| arbe 能力 | 是否复用 | 复用方式 | 不应做的事 |
|---|---|---|---|
| BagReader 的时间线、辅助数据匹配、播放节拍和完成等待 | 是 | 通过 arbe_replay_adapter 调用，后续抽成 headless core/service | 在 radarAnalyze 重写第二套时间线 |
| MyRvizPlugin 的 ROS 发布和完成服务 | 是，短期 | 作为现有播放器运行时的 adapter endpoint | 将 Qt/RViz widget 当作统一平台 API |
| wfAutosarData、PlaySingleFrame、PERInfoOutStruct 消息/结构定义 | 是 | 每次 source context 探测并生成 schema/provenance | 在 Python 中复制固定 struct 并假定永远不变 |
| arbe_visualization_engine 算法宿主 | 是 | launch/attach 到实际可执行文件；必要时加可选 bridge | 将 C/C++ 源码直接 import/link 到 radarAnalyze |
| debugOutput.c CSV | 部分复用 | 作为可选采集器和离线对比证据 | 把历史 CSV 当作 runtime 全量真值 |
| mainwindow/viewpanel Qt UI | 不直接复用 | 只复用其 topic/config/操作语义 | 在 HTML 中模拟全部 UI 控制并声称等价 |
| PlaySingleFrame.srv | 只复用 ACK 语义 | replay adapter 的完成回调 | 当作 load/play/seek 服务 |
| 固定 15 路 warning index | 仅在 adapter profile 内复用 | 从 active source/消息定义生成映射 | 把 FCTA/FCTB 固化为全平台规则 |
| start、arbe.launch、launch_config_4radars.yaml | 是 | 通过 build/runtime provider 使用 | 默认修改原 workspace 或隐式切分支 |

## 5. 推荐的独立模块

### 5.1 ArbeWorkspaceAdapter

职责：只负责已确认 workspace 的环境探针和构建/启动前置。

输入：

    server_profile
    arbe_root
    source_context
    vehicle/coem
    cuda profile
    build policy

输出：

    workspace_fingerprint
    outer_head/status
    submodule_heads/status
    launch_config_snapshot
    binary inventory
    debug symbol report
    preflight result

数据准备和构建实现复用 bosch-data-transfert、cr60light-arbe-build 的工作流，不复制脚本逻辑。

### 5.2 ArbeReplayAdapter

职责：将 cr60-debug-harness 的目标事件转换为 arbe 可执行回放计划。

两种 strategy：

    sgu_injection:
      HILMODEL / SGU precondition → event frame → limited feature warm-up → GDB/probe

    point_cloud:
      point-cloud input → 150–200 frame warm-up profile → target frame → tracking/perception probe

它只调用已经存在的 BagReader/播放器接口或一个由 arbe feature branch 提供的 headless replay service，不持有算法业务规则。

### 5.3 ArbeRuntimeBridge

建议作为 arbe 中可选构建 target，而不是修改默认算法。

最小能力：

- 每次 PostProcessMainTI 调用的 input/output snapshot；
- frameID、ROS header time、radar id/pos；
- raw_sgu_index 到 algorithm_object_index 的映射；
- ego、object、ADAS warning、adasRoi；
- source/binary/build fingerprint；
- 可配置字段白名单、采样帧范围和输出路径；
- JSONL/CSV 追加写入和 flush/close 结果。

如果必须拿到函数局部变量，继续使用 GDB 或在 source context 中启用 feature-specific trace hook；不要让 bridge 伪造局部变量。

### 5.4 GdbRuntimeProvider

职责：按结构化 runtime-debug-plan.v1 连接到实际 arbe_visualization_engine，执行：

preflight → bash start readiness → headless attach（优先）/launch-under-gdb（备用） → condition breakpoint
    → capture stop/backtrace/locals/expressions → continue
    → teardown → validate trace provenance

Pi 只生成计划并调度，不能直接拼接任意 GDB/shell 字符串。GDB 的对象表达式必须来自 active source context，例如：

    frame_counter >= <start> && frame_counter <= <end> && sObj->objID == <obj_id>

在存在 i 的循环作用域时，才追加：

    i == <algorithm_object_index>

如果当前停靠位置没有 i 或 sObj，工具应换到真实作用域或报告 breakpoint_expression_unavailable，不能输出看似可复制但实际不能编译的条件。

## 6. 推荐的集成形态

    Pi / radarAnalyze
        │  task plan + typed artifacts
        ▼
    RunSupervisor（Linux / SSH / workspace isolation / audit）
        ├── ArbeWorkspaceAdapter
        │       └── source + COEM + CUDA + build + launch preflight
        ├── ArbeReplayAdapter
        │       └── existing BagReader / headless replay endpoint
        ├── GdbRuntimeProvider
        │       └── arbe_visualization_engine process
        └── ArtifactCollector
                └── runtime trace / logs / screenshots / provenance

ROS data plane:
BagReader → /wf/corner_radar/lgu_data_<n>
           → arbe_visualization_engine
           → warning / radar_info / object / ROI topics

runtime evidence plane:
GDB / optional bridge → runtime-trace.v1
                       → evidence merge → HTML + Pi explanation

## 7. 不应直接复用的实现边界

以下做法会使统一平台变脆，应明确禁止：

1. 把 arbe 的 C 文件复制到 radarAnalyze，然后自己维护 ABI/宏/COEM 分支。
2. 在 radarAnalyze 中把 HILMODEL=2、15 个 warning 位、四个 radar topic 写成全局业务真值。
3. 让 Pi 自己拼接 ssh、gdb、roslaunch、pkill，绕过 allowlist、锁、审计和人工确认。
4. 将 PlaySingleFrame 的 ACK 当成可寻址的播放器控制面。
5. 用 debugOutput.c 的历史 CSV 补全当前没有 runtime 证据的局部变量。
6. 让 GUI 显示层的矩形/ROI 计算替代算法内部 objPoly/adasRoi。

## 8. 实施优先级

### R0：只读适配和 schema 探针

- 通过 SSH 读取 workspace/source/binary/config 状态；
- 解析当前消息和结构体；
- 生成 source context、replay capability 和 debug capability report；
- 不修改远程仓库。

### R1：复用现有播放器完成 SGU runtime MVP

- HILMODEL=2/SGU preflight；
- 复用现有 BagReader 的事件回放和 ACK；
- 生成真实作用域条件断点；
- GDB 采集 frameID、i/k、objInfo->trcOutData[]、ego、warning、ROI；
- 与 Sprint1 bundle 合并为 overlay。

### R2：arbe feature branch 的可选 bridge

- 增加 runtime snapshot/JSONL sink；
- 增加 headless replay control service；
- GDB 只负责局部变量和调用栈；
- 通过 feature flag 回退到原始 arbe。

### R3：point-cloud 状态回放

- 以真实 frame domain 定义 150–200 帧 warm-up；
- 捕获 point → filter → cluster → track → ADAS 的连续链路；
- 记录回放扰动和 reset boundary。

## 9. 现场验证后才可冻结的事项

- BagReader 是否允许从统一工具以 headless 方式启动，还是必须启动 RViz plugin；
- HILMODEL=2、PF_BUILD_FUNTEST_SGU_INJECTION 是否存在于最终 binary；
- GDB attach 权限、编译优化、debug symbols 和 source path mapping；
- 当前实际 frame_counter 和 wfAutosarData.frameID 的对应关系；
- SGU 模式的最小状态预热；
- point-cloud 150–200 帧是否按每个 radar/功能单独定义；
- runtime bridge 是否允许以 feature branch 形式改 arbe；
- 多用户同时使用同一 Linux server 时的 workspace/process/port 隔离。

## 10. 调研结论

这次调研证明：arbe 不是只能被当作“外部 GUI 黑箱”，其中已有三个可复用的核心能力：

1. 具备完成确认和时间对齐语义的 BagReader 回放器；
2. 在 arbe_visualization_engine 中把实际算法源码编译成可运行宿主的构建方式；
3. 具有真实算法输入输出结构、对象属性、ADAS 状态和 ROI 的运行时边界。

统一工具应围绕这三点做薄适配和证据采集，保留 radarAnalyze 的独立性；只有当现有 ROS/GUI 控制面不能满足 headless GDB 时，才在 arbe 建一个最小 feature bridge。

## 11. 2026-08-30 当前源码刷新结论

本轮再次对 `10.190.171.44` 当前工作区做只读源码核对，旧调研的 BagReader/ACK 结论仍
成立，并补充了对“逐步呈现”和公共 runtime 准确性的关键事实。

### 11.1 BagReader 已具备可复用的诊断回放方法

- `buildLguPlaybackTimeline()` 将 radar0..4 全部 LGU 按 bag time 稳定排序；
- event mode 每步只选择一个 LGU event；scene mode 以 main radar 为锚，其他 radar 使用
  `findClosestWithin`；
- warning/car/XCP/public CAN 使用 `findLatestAtOrBefore`，相机使用 `findClosestWithin`，
  均有 max-age/max-diff；
- `playLoop()` 对每个 radar 维护 pending count，上一帧未完成时不会发送下一帧；慢算法
  callback 会调整 wall-clock baseline，不突发补帧；
- bag 末尾等待所有 radar pending frame 完成后才结束；
- 手工 jump 会重新发布上下文，自动播放可抑制重复辅助消息。

这些方法适合直接成为 ReplayAdapter 的语义基础，也是我们做准确回放、性能测量和逐步
debug 的核心价值；不应在 Python 中重写近似时间线。

### 11.2 arbe 已经实现了“中间属性可见”的交互思路

当前 GUI Object Table 区分 `RAW_SGU` 和 `ALGO`，逐目标显示：ID/objID、位置、尺寸、yaw、
速度、TTC、DDCI 以及 BSD/LCA/DOW/RCW/RCTA/RCTB/FCTA/FCTB object flag。Radar Info
显示 ego speed、yaw rate、各雷达 frame、detections、周期和 BLD 信息。

这证明用户提出的“不要只给最终结论，要看中间线索”与正式工具的工程实践一致。统一
Workbench 应复用这些 public 字段和逐帧切换方法，同时增加：source token、evidence 状态、
代码链、claim/gap/hypothesis 和 debug experiment。

### 11.3 公共 topic 可以减少 GDB，但存在精确帧缺口

当前可用：

```text
/corner_radar/warning_status_with_frame
  data[0]=radar_id, data[1]=frame_counter, data[2..16]=warning

/corner_radar/radar_info
  radar_id, ego speed, yaw rate, detections, frame_counter, period, BLD, mileage

/wf/objectlist_<radar>
  object geometry, motion, TTC/DDCI and feature object flags
```

但 `wfObjectMsg` 只有 ROS Header + `wfSObj[]`，没有 algorithm frameID；发布代码把 header
stamp 设置为 `ros::Time::now()`。因此 objectlist 与 warning/radar_info 的时间近邻只能是
partial evidence。若需要绝对同帧目标属性，推荐在同一 algorithm callback 内增加默认关闭
的 stamped snapshot，或由 collector 通过 callback barrier 建立可证明关联。不能用时间
接近直接宣称准确同帧。

### 11.4 对架构的直接影响

1. 静态预检查后优先尝试 public runtime collector，再按 hypothesis 缺口选择 GDB；
2. `PlaySingleFrame` 继续只作为 status=0/1 ACK，不设计成外部 seek RPC；
3. ReplayAdapter 复用 BagReader 的时间线、同步和 pending barrier；
4. 可选 bridge 优先解决 frame/object/ego/warning/ROI 的 stamped snapshot，不先增加大量
   feature-specific debug 字段；
5. GDB 只负责公共 snapshot 无法回答的局部变量、临时状态、调用栈和最终 Tx 链；
6. Workbench 复用 arbe 的逐帧属性展示思想，但事实来源是 ledger/evidence，不是 RViz marker。

### 11.5 2026-08-31 View / Debug_Warning 截图对应的实现事实

用户截图中的两个报警窗口不是同一个来源：`Adas Warning` 对应
`/corner_radar/warning_status`，`Adas Warning Raw` 对应
`/corner_radar/warning_status_raw`，二者都是 `UInt8MultiArray`，载荷为
`radar_id + 15 路 warning`，都没有算法 frame。`/corner_radar/warning_status_with_frame`
是 `visualization_node.cpp` 在 `PostProcessMainTI` 后生成的 `UInt32MultiArray`，额外带
`frame_counter`，当前主要由 KPI trace 订阅。

当前 15 路 source mapping 为：

```text
1 BSD_L, 2 BSD_R, 3 LCA_L, 4 LCA_R, 5 DOW_L, 6 DOW_R, 7 RCW,
8 RCTA_L, 9 RCTA_R, 10 RCTB_L, 11 RCTB_R, 12 FCTA_L, 13 FCTA_R,
14 FCTB_L, 15 FCTB_R
```

GUI 颜色为 0/其它绿色、1 黄色、2 红色；`AdasWarningDisplay` 按当前四雷达安装语义
把 radar1/2 用于 FCTA/FCTB 左右，radar3/4 用于 BSD/LCA/DOW/RCTA/RCTB，RCW 取后
两雷达较大值。这是当前 source 的事实，不应直接抽成跨项目固定配置。

截图右侧的 `Frame Count` 是各 `pointcloud_msgs`/LGU 消息数量；`Scene Frame Index` 和
`LGU Event Index` 是播放器索引；`LGU FrameID` 才是消息中的算法周期号。`buildWarningSummary`
对 raw warning 只按 bag time 找 main radar message 的最近索引，所以 `871-939` 这类区间
是 message index，不是算法 `frame_counter`。这一区分必须进入复用 adapter 的输出 schema。

ObjectList 方面，GUI 订阅 `/wf/objectlist_1..4`，`wfSObj` 显示目标位置、尺寸、yaw、
速度、TTC/DDCI、RCS 和 8 类 object flag；算法对象由 `algo_objInfo.trcOutData[i]` 映射而来，
但消息不携带 `i`。GUI `valid_rows` 又会跳过无效 ID 后重新编号，不能将表格行号作为 GDB
的 `i`。原始 SGU 使用 `ID=1000000+raw_obj_id`、`Source=RAW_SGU`，与算法 ALGO 对象分开。

因此复用 arbe 的正确方式是：复用 topic/message/BagReader/ACK 和显示字段语义；Pi 自己的
证据模型还必须额外携带 frame domain、source layer、`trc_index_i`、对象索引映射和
association status。不能抓取 GUI 像素，也不能把当前灯窗口或 Marker 当作 CAN/算法真值。
