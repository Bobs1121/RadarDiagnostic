# ROS 实际环境 Debug 工具探索记录

> 日期：2026-08-24
> 分支：`codex/ros-debug-autonomous`
> 状态：`[R]` 探索中；尚未形成最终设计，也未对远程 `cr60_light_arbe` 执行 checkout、编译、启动、播放或 GDB attach。

> 范围修正：本文件中的 `CRGVI-1829` 只作为探索和验证链路的样本附录；通用产品框架、数据契约、预热、雷达/目标选择和鲁棒性规则见 [ROS_DEBUG_DIAGNOSTIC_TOOL_FRAMEWORK.md](ROS_DEBUG_DIAGNOSTIC_TOOL_FRAMEWORK.md)。

> 参考输入：读取并交叉核对了 `C:\Users\HOZ2WX\.zcode\workspace\default\cr60_handoff_FCTAFCTB.md`。hand-off 中未被当前远程环境验证的数字或结论均按 `[TBD]` 处理。

## 1. 用户给出的目标与操作边界

目标是为 CR60 Light 的实际 ROS debug 建立可自主执行的工具，能够围绕真实 rosbag：

1. 识别问题单、车型、代码版本和 bag；
2. 在 `10.190.171.44` 的 `~/CR60LIGHT/cr60_light_arbe` 中使用用户配置好的子仓分支；
3. 执行 `catkin_make`、`bash start`，启动 RViz/arbe 可视化回放环境；
4. 通过 VS Code 的 `ROS: Attach`，选择 C++、`arbe_visualizat...` 和 `radar1/2/3/4` 目标；
5. 在报警帧停住，查看 FCTA/FCTB 条件、对象、ego、状态、参数和调用链；
6. 判断正报/误报，给出有证据的原因和优化方向。

用户给出的样例：

```text
问题单：CRGVI-1829
数据：/home/hoz2wx/CR60LIGHT/data/qzh/CRGVI-1829/corner_radar_net_2026-07-19-11-56-15_11.bag
现象：FCTA/FCTB 报警，客户认为是误报警
```

### 已确认的安全边界

- 本地 `radarAnalyze` 工作区原有大量未提交改动，已从 `feature/production-refactor` 创建新分支；未清理、未回退、未提交这些改动。
- 远程 `cr60_light_arbe` 当前也有大量用户临时改动和正在运行的 ROS/GUI 进程；探索期间仅执行只读命令，未触碰 live session。
- 在远程实际播放、改变 GUI 当前 bag、停止/启动进程、attach 正在运行的 PID、切换子仓或编译前，需要用户确认当前环境可用于受控实验，或者由工具采用单独的隔离 session。

## 2. 本地 radarAnalyze 现状

已有能力不是空白：

| 能力 | 当前状态 | 证据 |
|---|---|---|
| bag 解析 | 已有 `BagParser` / `BagProvider`，支持 `wfAutosarData`、`wfObjectMsg`、warning topic 和 debug tail | `parsers/bag_parser.py`、`parsers/providers/bag_provider.py` |
| 数据质量 | 已有 `signal_valid`、provenance、placeholder 审计方向 | `parsers/providers/bag_provider.py`、`engines/data_quality.py` |
| 代码学习/调用链 | 已有 CodeGraph、`code-learn`、`code-analyze` | `ai/codegraph`、`ai/modules/code_learn.py`、`ai/modules/code_analyze.py` |
| 回放结果解析 | 已有 `ArbeReplayProvider`、`LocalArbeReplayProvider`，解析 `*_algo_warning_trace.csv` | `engines/arbe/replay_provider.py` |
| 远程回放 | 只有 SSH 骨架，默认 fail-soft，不会真实执行 SSH | `engines/arbe/remote_replay.py` |
| `sim-verify` | 当前仅支持 `--mode local`，远程接线尚未完成 | `ai/modules/sim_verify.py` |
| arbe 资产 | 已从服务器保存部分源码、脚本和操作指南 | `tools/arbe/`、`tools/arbe/FCTB_Batch_Replay_Operation_Guide.md` |

因此新能力的核心缺口不是“再写一个 bag parser”，而是把远程工作区的生命周期、GUI 播放器控制、ROS 帧同步、debug target/PID、GDB 证据采集和现有代码/数据分析能力接成可观测闭环。

## 3. 远程环境实测快照

### 3.1 主机与运行时

```text
host: WX-C-001QM
user: hoz2wx (uid=550187743)
OS: Ubuntu 22.04.5 LTS
kernel: 6.8.0-107-generic x86_64
ROS: Noetic
ROS_MASTER_URI: http://localhost:11311
catkin_make: /opt/ros/noetic/bin/catkin_make
gdb: /usr/bin/gdb
workspace: /home/hoz2wx/CR60LIGHT/cr60_light_arbe
data root: /home/hoz2wx/CR60LIGHT/data
DISPLAY (running process): :10.0
```

当前 ROS master 正在运行，当前发现的主要节点：

```text
/arbe_gui
/radar1_visualization_engine/arbe_visualization_engine
/radar2_visualization_engine/arbe_visualization_engine
/radar3_visualization_engine/arbe_visualization_engine
/radar4_visualization_engine/arbe_visualization_engine
/rviz
/multi_camera_launcher
/qt_image_viewer_node
```

四个算法进程的 executable 都是：

```text
/home/hoz2wx/CR60LIGHT/cr60_light_arbe/devel/lib/arbe_phoenix_radar_driver/arbe_visualization_engine
```

它们通过 ROS namespace 和 private parameters 区分雷达；实测参数包含 `Radar_ID=1..4`、`radar_pos=1..4`。当前启动命令行显示：

```text
radar1: Front_Left
radar2: Front_Right
radar3: Rear_Left
radar4: Rear_Right
```

### 3.2 外仓/子仓状态（重要：当前不是干净基线）

外仓当前：

```text
branch: develop_LGU_Simulation
upstream: origin/develop_LGU_Simulation
```

外仓存在未提交修改：

- `.vscode/settings.json`
- `src/algo_source` submodule
- `src/arbe_phoenix_radar_driver-master/arbe_gui/Config/launch_config_4radars.yaml`
- `src/arbe_phoenix_radar_driver-master/arbe_gui/addons/arbe_api_common_build.ver`
- `src/arbe_phoenix_radar_driver-master/arbe_gui/addons/arbe_msgs_build.ver`
- `src/arbe_phoenix_radar_driver-master/arbe_gui/src/arbe_visualization_engine/visualization_node.cpp`
- `SIMULATION_FIX_SUMMARY.md` 以及 CUDA xlsx/LibreOffice lock 文件为未跟踪产物。

子仓当前为 detached HEAD：

```text
commit: a81b08a38f316a3d25bfcbcad6dcfc822d24b990
describe: BYD_UKE_BL02RC05-1374-ga81b08a38
```

子仓未提交修改包含：

- `paraDefine.h`：`BUILDMODEL 0 -> 2`、`HILMODEL 0 -> 2`；
- `coem/BYD_UKE/components/AswPerception/func/adasFunc.c`：删除多处 `ADAS_STATE_EXTERNAL_MODE` 条件编译分支，使 ROS/外部车辆参数路径被直接使用；这会影响 ROI 和几何条件，不能把当前工作区当作干净算法基线；
- `tools/ADAS_Tools` submodule 指针变化。

外仓 `visualization_node.cpp` 还把 `xcp_info_callback()` 中更新全局 disable flags 的代码全部注释掉。当前 source 与 `SIMULATION_FIX_SUMMARY.md` 的描述并不完全一致；实际 source、运行时 `rosnode info` 和二进制行为优先于 summary 文档。

### 3.3 编译与启动

`.vscode/tasks.json` 中已有：

```text
catkin_make -DCMAKE_BUILD_TYPE=Debug
catkin_make -DCMAKE_BUILD_TYPE=Release
catkin_make clean
```

但当前 `build/CMakeCache.txt` 的 `CMAKE_BUILD_TYPE` 为空。当前 executable `file` 输出包含 `with debug_info, not stripped`，因此可以 GDB 按符号定位；不过要把“可靠断点和变量可见性”作为验收条件，后续仍需在用户确认的目标版本上显式用 Debug 配置重新编译并记录 commit/hash、编译命令和产物 BuildID。

`start` 脚本的实际内容是：

1. `sudo chmod` 四个 `/dev/ttyUSB*`；
2. 写 `/sys/bus/usb/devices/1-11/bConfigurationValue`；
3. `source devel/setup.bash`；
4. `roslaunch arbe_phoenix_radar_driver arbe.launch`。

`arbe.launch` 默认 `start_rviz_bag=false`，但 `arbe_gui` 的 `mainwindow.cpp` 会通过：

```text
roslaunch my_rviz_plugin player.launch&
```

单独启动 RViz bag player；实测 player 服务挂在 `/rviz` 节点上。`DISPLAY=:10.0` 存在于正在运行的 GUI 进程环境中，非交互 SSH shell 默认看不到该变量，自动化工具必须显式处理 X/desktop session 的环境继承。

### 3.4 VS Code 与 ROS attach

当前 `.vscode/launch.json`：

- `ROS: Attach`：`type=ros`、`request=attach`，没有进一步的 target 配置；
- `ROS: Launch` 的 target 仍是旧路径：`/home/radar/CornerRadar/CornerRadar_Ti_flip_udp_1212/src/arbe_phoenix_radar_driver-master/arbe_gui/launch/arbe.launch`，与当前 workspace 不一致。

当前 `.vscode/c_cpp_properties.json` 仍包含 `/opt/ros/melodic`、`/home/radar/catkin_ws_2p83` 等旧环境；`.vscode/settings.json` 主要配置 Noetic，但有未提交的 `ROS2.distro: noetic` 异常项。

因此用户描述的“选择 C++ → `arbe_visualizat...` → `radar1/2/3/4`”实际依赖 ROS VS Code 扩展通过 ROS master 发现 node/PID，而不是当前 `launch.json` 中的固定 C++ 配置。工具需要把以下映射显式化：

```text
radar1 -> /radar1_visualization_engine/arbe_visualization_engine -> PID -> same ELF + Radar_ID=1
radar2 -> /radar2_visualization_engine/arbe_visualization_engine -> PID -> same ELF + Radar_ID=2
radar3 -> /radar3_visualization_engine/arbe_visualization_engine -> PID -> same ELF + Radar_ID=3
radar4 -> /radar4_visualization_engine/arbe_visualization_engine -> PID -> same ELF + Radar_ID=4
```

## 4. ROS 回放与控制面

### 4.1 算法输入/输出

`arbe_visualization_engine` 的 CMake target 是 `arbe_visualization_engine`，源文件包含：

```text
src/arbe_visualization_engine/visualization_node.cpp
src/arbe_visualization_engine/Slam_color.cpp
src/arbe_visualization_engine/Pointcloud_coloring.cpp
src/arbe_visualization_engine/vis_utils.cpp
${PERCEPTION_ALL_SOURCES}
```

关键订阅/发布：

```text
输入：/wf/corner_radar/lgu_data_1..4
输入类型（运行时）：arbe_msgs_rvizbag/wfAutosarData
输出对象：/wf/objectlist_1..4  (arbe_msgs/wfObjectMsg)
输出 warning：/corner_radar/warning_status (std_msgs/UInt8MultiArray)
输出带帧号 warning：/corner_radar/warning_status_with_frame (std_msgs/UInt32MultiArray)
```

`wfAutosarData` 的 ROS 字段是：

```text
header, frameID, LGUNum, SGUNum, bytelength, uintData[], floatData[], outputData[]
```

`visualization_node.cpp` 将 `outputData` 强制解释为 `PERInfoOutStruct*`，在 `HILMODEL != 0` 时把其中的 `objTrans[]` 拷贝为 ADAS 输入对象，并从 `egoCarInfoTrans`、`ADASInfoTrans`、`BLDInfoTrans` 等字段构造后处理输入。

warning 数组的运行时映射由 `visualization_node.cpp` 明确写出：

```text
data[0]  = radar_id
data[1]  = BSD_L
data[2]  = BSD_R
data[3]  = LCA_L
data[4]  = LCA_R
data[5]  = DOW_L
data[6]  = DOW_R
data[7]  = RCW
data[8]  = RCTA_L
data[9]  = RCTA_R
data[10] = RCTB_L
data[11] = RCTB_R
data[12] = FCTA_L
data[13] = FCTA_R
data[14] = FCTB_L
data[15] = FCTB_R
```

### 4.2 播放器不是普通 `rosbag play`

`my_rviz_plugin` 的 UI 控件包括 `Select Folder`、`Select`、`Read`、`Play`、`Stop`、逐帧按钮和 scene mode。`BagReader::readBagFile()` 会把选定 bag 的指定 topic 全部缓存；`BagReader::playBag()` 启动播放线程。

播放器只读取这些主要 topic：

- `/wf/corner_radar/lgu_data_0..4`
- 摄像头 compressed image
- `/wf/car_id6/parsed2`
- `/corner_radar/warning_status_raw`
- `/front/signals`、`/rear/signals`
- `/wf/xcp_signals/front_left/right/rear_left/rear_right/parsed`

算法 callback 每收到一帧后，会调用 `/play_single_frame_<radar>` 服务两次确认：

```text
request: uint8 radar_pos, uint16 frame_id, uint8 status
status=0: 收到该帧
status=1: 算法处理完成
response: bool success
```

`my_rviz_plugin` 在 `/play_single_frame_0..4` 上提供服务；scene mode 会等待当前帧所有雷达 callback 完成。因此“自动停在某帧”不能只调用 `rosbag play --pause` 来假设行为一致：要么控制 GUI player 的 `Read/Play/scene`，要么增加明确的 ROS 控制 API，或者构造独立的帧发布/ack 调度器。

目前已发现的可编程控制面只有：

- `/play_single_frame_0..4` 服务（用于算法向播放器回报，不是加载/播放命令）；
- `/kpi/current_bag_path`、`/kpi/bag_switch_epoch` 参数（播放器内部使用，不等于公开控制 API）。

是否允许在 arbe 外仓给 `my_rviz_plugin` 增加 `load/read/play/stop/seek` ROS service 或 action，是后续设计必须确认的产品边界。

### 4.3 连续回灌预热（通用能力，不是样例特例）

用户补充并经源码核对：实际 debug 时，算法是实时连续回灌，通常要在目标报警帧之前先播放约 `100–200` 帧，才能让跟踪、目标生命周期、ego/系统状态和 FCTA/FCTB 的跨帧计数接近实车状态。

源码证据：

- `BagReader::jumpToFrame()` / `jumpToSceneFrame()` 只向 callback 发布被选中的一帧，不会自动补发此前帧；
- `BagReader::playLoop()` 才会按事件时间顺序连续发送 LGU，并等待 per-radar ack；
- `DataProcInit(isFirstFrame)` 会清理 cluster、curb、objInfo、runtime 和全局变量；
- `RosbagTimeStamp==0`、时间回退或相邻时间间隔 `>1 s` 会设置 `algo_InitFlg=1`；
- `reSetCarData()` 会清零 ego 状态；FCTA/FCTB 的 `lastAdasWarning`、keep flag、counter、FCTB brake timing 会在初始化/关闭逻辑中重置。

样例 radar2 的静态索引核对：目标 frame `47872`，约提前 100 个 radar2 event 为 frame `47772`（relative `512.434 s`），约提前 200 个 event 为 frame `47672`（relative `505.812 s`）；目标 relative `519.051 s`。该换算不能直接用 `frame_id - N` 替代，因为样例存在跳帧。

框架规则：每个目标事件生成 `warmup window`、`target window`、`post window`；默认 `warmup_frames=150`，允许 `100..200` 配置；预热必须与目标使用同一 session、同一 binary/config、同一 event/scene mode，并记录实际 event 数、frame gap、时间 gap、reset、ack timeout 和 readiness。详见 `ROS_DEBUG_DIAGNOSTIC_TOOL_FRAMEWORK.md` §7。

## 5. 样例 bag 实测证据

### 5.1 bag 元数据

```text
path: /home/hoz2wx/CR60LIGHT/data/qzh/CRGVI-1829/corner_radar_net_2026-07-19-11-56-15_11.bag
size: 1.0 GB (ls -lh: 1.1G)
duration: 599 s
start: 1784433375.40
end: 1784433975.39
messages: 194563
```

主要 topic：

```text
/corner_radar/warning_status_raw             48000
/front/signals                               29999
/rear/signals                                30002
/wf/corner_radar/lgu_data_1..4               9075/9080/9082/9077
/wf/objectlist_1..4                          9075/9080/9083/9078
```

### 5.2 原始 warning topic

解析 `/corner_radar/warning_status_raw` 得到：

```text
total messages: 48000
any warning active: 1142
FCTA/FCTB slice data[12:16] active: 92
groups:
  radar_id=1, (FCTA_L,FCTA_R,FCTB_L,FCTB_R)=(0,0,1,0): 73 frames, t=519.327..522.926 s
  radar_id=2, (0,1,0,0): 19 frames, t=519.377..520.275 s
```

这只说明录制的 raw warning topic 中存在这些字节，不等同于当前算法重跑的 `/corner_radar/warning_status` 输出；两者必须在相同帧、相同 radar、相同时间基准下对齐后才能判断回放一致性。

### 5.3 录制对象输出

`/wf/objectlist_2` 在相同窗口有 8 帧对象 warning：

```text
object ID=44
obj_class in ROS object message=0（该字段与 outputData 中的 obj_type 不一致，需注意）
position x=5.93..6.15 m
position y=-5.57..-4.12 m
velocity x_dot=-1.71..0.29 m/s
velocity y_dot=3.53..4.44 m/s
fTTC=1.08..1.00 s
fDDCI=8.64..8.29
objFctaWarningFlag=1..5
objFctbWarningFlag=1..5
```

源码 `emWarningFlag` 表明 object flag 的基础语义是 `0=Normal, 1=Warning`；`SelfIncreFctxWarnCount()` 会将计数递增到 `MAXWARNINGSTATEBUFFERSIZEPLUS=5`，`HandleFcta/Fctb*WarningFlag()` 在 `>=5` 时才增加功能 warning 数。因此 `2/3/4/5` 是跨帧状态计数，不是四种告警等级。

### 5.4 `wfAutosarData.outputData` 的实际算法输入

对 `/wf/corner_radar/lgu_data_2` 的 `outputData` 按当前仓库的结构布局解码，窗口 `518.847..519.700 s` 得到：

```text
ADASInfoTrans: fcta=1, fctb=1
ego speed: approximately 4.40 m/s (窗口后段约 3.67..3.77 m/s)
ego gear: 4
ego yaw rate: approximately 0.12..0.36 (unit follows source payload)
obj ID=44, type=4, dyn=2
input dist=(5.93,-5.57) -> (6.15,-4.12) m
input velocity=(velX,velY) roughly (-1.71,3.53) -> (0.29,4.44) m/s
input abs velocity roughly (2.68,3.54) -> (4.71,4.47) m/s
input fTTC=1.08 -> 1.00 s; fDDCI=8.64 -> 8.29
object fcta/fctb counter: frame 47872..47876, 1 -> 5; then it decays/clears
```

输入 debug tail 中 `FCTA/FCTB enable=1`，与算法 `FrontRadarAdas()` 的功能使能入口一致。当前证据更像“一个动态横穿目标快速接近 ego 前方，算法条件逐帧满足并达到计数阈值”，但还不能替代实际视频/场景真值。

### 5.5 PublicCan 信号

bag 内嵌 message definition 与当前 `common_can_signal_publisher_rvizbag` 生成类并不完全相同；用 bag 自身的 dynamic class 解码后发现：

```text
/front/signals: 29999 messages, signal_valid 长度 535, 每帧 invalid count=176
/rear/signals: 30002 messages, signal_valid 长度 562, 每帧 invalid count=179
```

前方信号中相关字段在报警窗口出现有效变化，且对应的 `signal_valid` 为 `1`：

```text
relative t≈519.388 s:
  FCTA/FCTB system status: 1 -> 2
  front FCTA warning field: 0 -> 1（方向字段需结合 DBC/雷达侧定义核对）
  FCTB brake request: 1
  target deceleration: -4.0（后续约 -2.0）
```

这与“完全由无效占位 CAN 值造成的报警”不一致；但公共 CAN topic、raw warning topic、算法内部 output 三者的方向/来源存在差异，工具必须保留 provenance 和 message definition/md5，不能只按字段名合并。

当前 hand-off 提到 `CR60Light.A2L` 中有大量 FCTA/FCTB measurement。远程只读核对到文件：

```text
/home/hoz2wx/CR60LIGHT/cr60_light_arbe/src/common_xcp_info_publisher/config/CR60Light.A2L
```

文本级统计为 `fFcta` 68 次、`fFctb` 42 次；这不能直接证明 hand-off 中提到的“1694 个 measurement”，需要后续按 A2L `MEASUREMENT` 结构解析、去重并确认地址/单位/访问权限。

## 6. FCTA/FCTB 当前源码调用链与关键条件

### 6.1 调用链

```text
ROS /wf/corner_radar/lgu_data_<radar>
  -> corner_radar_post_process_data_callback()
  -> mAlgoPerOutputPtr = (PERInfoOutStruct*)msg->outputData.data()
  -> HILMODEL != 0: objTrans/egoCarInfoTrans/ADASInfoTrans -> algo inputs
  -> PostProcessMainTI(..., &algo_adasWarning, ...)
  -> AdasFunc()
  -> FrontRadarAdas()
  -> FctaFctbUpdateStatus()
  -> ResetFctaRoi()
  -> FrontCrossTrafficAlertAndBrake()
  -> UpdateFctaLeft/RightWarningStatus()
  -> UpdateFctbWarningStatus()
  -> algo_adasWarning -> /corner_radar/warning_status
```

关键源码位置（当前远程工作区）：

```text
visualization_node.cpp:
  callback: ~3577
  PostProcessMainTI call: ~3823
  warning array mapping: ~4062..4078
  main(): ~4459
adasFunc.c:
  FctaFctbUpdateStatus(): ~2521
  ResetFctaRoi(): ~2695
  UpdateFcta/RightWarningStatus(): ~6042/~6131
  FctaDirectRunning(): ~6360
  FctaTurning(): ~7316
  HandleFcta/Fctb flags + FctaSkipFlg(): ~7705..7881
  SelfIncre/SelfDecreFctxWarnCount(): ~9827..9882
  FrontCrossTrafficAlertAndBrake(): ~9889
  FrontRadarAdas(): ~10718
  AdasFunc(): ~11063
```

### 6.2 需要逐帧记录的条件

1. **System/enable**：`g_DTCCode.selfInspFlg`、`calibratingFlg`、`failureFlg`、`bBrakeNotReadyFlg`、`adasEnable->bFCTAEnable`、`adasEnable->bFCTBEnable`。
2. **Ego gate**：FCTA/FCTB active/detect speed（当前源码为 0..20 km/h active、10..20 km/h detect）、gear 必须为 `4/5`；FCTB 还要求 brake ready。
3. **Target gate**：`dynFlg` 必须为 1..3，FOV 检查，HIL 输入时重新计算 absolute velocity，`FctaSkipFlg()` 的目标速度范围。
4. **Geometry**：radar position、yaw、vehicle width/bumper distance、target yaw/length/width、FCTA ROI 与 target polygon 的 intersection、直行/转弯路径。
5. **Collision metrics**：`fTTMX`、`fTTMXObj`、`fTTMY`、`fDDCI`、`fIntAng`、`fInterX/Y`。
6. **Thresholds**：FCTA base `TTMX=2.0 s`、FCTB base `TTMX=1.0 s`，FCTA/FCTB `TTMY` upper `2.5/1.5 s`，lower `0.4 s`，已有 warning 后 lower threshold 可到 `0.0 s`；速度相关 `UpdateFctaParams()` 动态调整 base TTMX/DDCI。
7. **Temporal state**：object counter、`bFctaDetectFlg`、`bFctbDetectFlg`、keep/de-warning flags、`fFctbBrakeEventTime`、`bFctbKeepBrakeFlg`、最终 system state/warning state。

### 6.3 当前代码下的 debug 断点候选

```text
corner_radar_post_process_data_callback
PostProcessMainTI
AdasFunc
FrontRadarAdas
FctaFctbUpdateStatus
FrontCrossTrafficAlertAndBrake
FctaDirectRunning
FctaTurning
SelfIncreFctxWarnCount
HandleFctaRightWarningFlag / HandleFctbRightWarningFlag
UpdateFctaRightWarningStatus
UpdateFctbWarningStatus
```

由于四个 radar 进程共享同一 ELF，断点必须绑定目标 PID/namespace；如果对所有同名进程下断点，调试输出会混在一起。

## 7. 当前结论、缺口与设计约束

### 已确认结论 `[R-confirmed]`

- 远程控制面可以通过 SSH、ROS master、ROS CLI、进程表、日志和 GDB 符号信息观察；运行时 GUI 使用 `DISPLAY=:10.0`。
- 算法 debug target 的真实 executable 是 `arbe_visualization_engine`，实际 node 名带 `radarN_visualization_engine` namespace。
- 当前播放器是 GUI 内缓存/按帧发布/ack 的同步播放器，不是简单的 `rosbag play`。
- 样例 FCTA/FCTB 触发可在原始 bag 的内部算法输入中追溯到对象、ego、enable、跨帧 counter 和公共 CAN 输出。
- 当前远程 worktree/submodule 有行为改变型未提交修改；任何重跑报告必须记录外仓 HEAD、子仓 HEAD、diff hash、配置 hash、binary BuildID 和编译模式。

### 尚未验证 `[TBD]`

- 在用户指定的最终子仓分支/tag 和最终 CUDA 配置下，重跑是否仍在相同帧输出 FCTA/FCTB。
- `/corner_radar/warning_status` 重跑输出与 bag 内 `/corner_radar/warning_status_raw`、`/front/signals` 的时间/方向是否一致。
- `radar 1` raw FCTB_L 与 `radar 2` FCTA_R 的方向关系，是否是发布器/通道语义而非算法左右语义。
- 当前工作区 `adasFunc.c` 删除 `ADAS_STATE_EXTERNAL_MODE` 分支是否是用户刻意的仿真适配，还是临时调试改动。
- `visualization_node.cpp` 中 `PostProcessMainTI(..., 3,3)` 的 task time 是否应固定为 3，是否与目标版本/用户期望一致。
- 是否有对应的摄像头/人工真值/客户复现描述，能够确认目标 `ID=44` 是应被保护的横穿车辆，还是静态障碍、误跟踪或方向错配。

### 设计硬约束 `[R]`

1. **先快照、再控制**：先采集版本、diff、config、binary、ROS graph、bag metadata，再允许启动/播放/debug。
2. **控制与分析分离**：远程 job/session manager 只负责环境和回放控制；确定性分析层负责信号/对象/条件/调用链；AI 只做跨证据推理和下一步建议。
3. **帧级证据包**：每一个结论必须能回到 bag 时间、ROS topic、radar、frameID、代码 commit/line、输入变量和输出 warning。
4. **状态机而不是 bit 判断**：必须记录 warning counter、system state、enable gate、ROI/碰撞量和状态保持，不能把 `flag=1` 直接解释为最终报警。
5. **缺数据/版本不一致 fail closed**：缺少目标分支、msgdef、signal_valid、编译 debug symbols 或当前 diff 未确认时，报告应标记“无法定性”，不输出确定性误报结论。
6. **不污染用户 session**：默认不杀进程、不清 build/devel、不改用户子仓；自动任务应使用显式 session/job ID 和可回收的独立输出目录。
7. **人机协同可暂停**：自动工具可以定位报警帧并准备 attach 参数，但实际修改源码、加日志、切版本、覆盖临时改动、提交 PR 必须单独确认。
8. **连续预热优先于随机跳帧**：目标帧若没有同一 session 的 100–200 帧连续预热，工具不得把单帧输出当作实车等价结果；发生时间回退、>1 s gap、bag switch 或 node 重启时重新判定 warm-up readiness。

## 8. 待向用户补问的信息

以下问题会决定最终设计和第一轮受控实测，当前不猜测：

1. `CRGVI-1829` 对应的准确车型/版本 tag 或分支是什么？当前远程 submodule 的 `BYD_UKE_BL02RC05-1374...` 是否只是临时状态？
2. 当前远程 `cr60_light_arbe` 的未提交改动（尤其 `adasFunc.c`、`paraDefine.h`、`visualization_node.cpp`）哪些必须保留，哪些可以由工具备份后恢复？
3. 是否允许工具在 `10.190.171.44` 创建独立 debug session/worktree（例如 `~/CR60LIGHT/debug_sessions/<id>`），还是必须复用你当前打开的 `~/CR60LIGHT/cr60_light_arbe`？
4. 第一次受控回放是否可以使用这条样例 bag，并允许工具控制 GUI 的 `Read/Play/Stop/seek`；当前 10.190.171.44 上正在运行的 session 是否属于你、可否暂停/重启？
5. 你希望自动化到哪一级：A) 自动准备环境并定位帧，B) 自动 attach 并采集 GDB 变量，还是 C) 允许自动修改代码/加日志/重新编译/重跑？
6. VS Code 是通过 Remote-SSH 连接服务器，还是本机 VS Code + 远程 ROS master？`ROS: Attach` 使用的扩展名称/版本是否可以提供？
7. 你通常希望停在：第一个功能 warning、warning counter 达到 5、FCTA/FCTB 输出 bit 变化，还是用户指定的 GUI 时间/帧号？
8. 客户认为误报的依据是什么：摄像头画面、人工标注、驾驶员主观描述、FCTA/FCTB 需求阈值，还是“当时目标不应触发”的复现结论？是否有对应视频或图片？
9. 目标版本下是否允许在 `visualization_node.cpp` /算法内部添加结构化 debug trace（例如 JSONL/CSV），还是只能使用现有 ROS topic、GDB 和 ROS log？
10. 输出报告的首要使用者是你本人做算法定位，还是还要给客户/项目团队看？需要中文报告、CSV/曲线、HTML、源码行号和可复现命令到什么程度？
11. 预热策略是否统一默认 `150` 个同一 radar 的有效 LGU event，并允许按车型/功能/回放模式配置 `100..200`？遇到丢帧或时间 gap 时，是自动扩大窗口，还是直接要求人工确认？

## 9. 下一轮行动（等待补充信息后）

1. 根据用户确认锁定版本、diff 和 session 隔离策略；
2. 对最终版本做一次只读 preflight 和 bag-only 静态抽取；
3. 获得受控实验许可后，验证 GUI player 控制和单帧 ack；
4. 验证 ROS attach target/PID 映射与 Debug binary；
5. 产出设计方案：session manager、replay controller、frame evidence collector、debug adapter、code/condition analyzer、report/bundle、pi/CLI 入口和验收标准；
6. 设计确认后再进入实现，不把本记录中的 `[TBD]` 自动变成产品决策。

## 10. 脚手架可行性审计与控制决定

本项目的通用目标是：`radarAnalyze` 做脚手架、控制面、数据/代码分析和证据汇总；`cr60_light_arbe` 作为可插拔被测运行时。当前不需要把诊断逻辑、AI prompt、证据模型或项目记忆写进 arbe。

### 已验证可行

- bag 静态抽取、ROS dynamic msgdef、signal validity、LGU/outputData、objectlist、warning、frameID/时间对齐：可在脚手架侧完成；
- 代码调用链、宏路径、FCTA/FCTB 条件、阈值和 A2L 文件发现：可在脚手架侧完成；
- SSH preflight、git/diff/config/binary 快照、ROS graph、topic/service/param、node/PID/ELF/`Radar_ID` 映射：可行；
- 同一 radar 的 100–200 event 连续预热规划、gap/reset/ack 健康检查：可行；
- 当前 executable 的 DWARF、`visualization_node.cpp`、`adasFunc.c`、`postProcess.c` 源路径和符号解析：可行。

### 需要适配才能完全自动化

- 当前 GUI player 没有公开的 bag load/read/play/stop/seek service；`/play_single_frame_<radar>` 只是算法回报播放器的 ack；
- 当前系统 `ptrace_scope=1`，没有 `gdbserver`，core dump limit 为 `0`；因此符号解析可行，但任意既有 PID 的无权限自动 attach 不能直接宣称可行；
- 当前未发现 `xdotool/wmctrl`，不能把桌面点击自动化当作稳定控制面。

### 控制策略决定 `[R]`

1. `radarAnalyze` 定义 `RuntimeAdapter`、`ReplayAdapter`、`DebugAdapter` 接口，默认外部 SSH/ROS 控制；
2. 先做静态事件/帧/目标/条件分析，再生成预热和 debug plan；
3. 优先使用“隔离 session + Debug build + launch-under-debugger”，而不是自动附加用户已有进程；
4. 当前 GUI 仅作为可插拔 `GuiPlayerAdapter`；若需要可靠无人值守控制，后续只在 arbe feature branch 增加窄的 `ArbeControlShim`，不把诊断逻辑放入 arbe；
5. 如果不允许改 arbe，再评估 direct frame replay，但必须证明消息选择、辅助 topic、时间匹配和 ack 与 GUI player 一致；
6. 第一阶段不创建 arbe feature branch，因为脚手架侧已经可以完成数据定位、代码解读、变量计划、预热计划和 debug handoff。

完整矩阵和创建 feature branch 的触发条件见 `ROS_DEBUG_DIAGNOSTIC_TOOL_FRAMEWORK.md` §16。

## 11. 对当前 radarAnalyze 的独立评估

当前 radarAnalyze 对新目标有价值，但建议作为可选分析后端，而不是新 debug 脚手架的宿主。

### 可直接复用的部分

- `parsers/bag_parser.py` / `BagProvider`：ROS bag、`wfAutosarData`、`wfObjectMsg`、warning、debug tail 和 provenance；
- `engines/data_quality.py`：signal validity、占位值和质量审计方向；
- `engines/arbe/replay_provider.py`：warning trace/KPI 的基础契约和 parser；
- `ai/codegraph` / `CodeAnalyzeModule`：函数、调用者、被调用者、调用链、变量读写、标定参数查询；
- `signal_mapper` 和项目的变量链；
- `PiBridge` / pi tools：作为可选 coordinator。

### 不应直接耦合的部分

- 当前 `config.py` 的项目/variant/memory schema；
- 当前 `orchestrator` 的固定诊断管线；
- 当前默认带 LLM enrichment 的 `ConditionExtractor`；
- 当前 `RemoteArbeReplayProvider`，它仍是 SSH 骨架，不是真实控制实现；
- 当前工作区的 dirty cache、variant memory 和历史案例产物。

### 代码链路预构建判断

现有 CodeGraph 查询能力足以作为原型基础，但不能直接当成“已经准备好的完整 debug 链路”。已有审计显示 regex codegraph 可能缺少 `STATE/TRANSITION`、`READS_SIGNAL/WRITES_SIGNAL` 和 node semantics；AST 路径存在但未稳定成为生产默认。因此新脚手架应构建自己的 `CodeIndexProfile` 和 `code_evidence` 契约，优先做确定性 AST/规则索引，LLM 只解释已经选定的代码片段。

建议的代码准备结果：

```text
entrypoint
→ forward/reverse call closure
→ variable read/write closure
→ condition groups
→ macro/compile profile
→ threshold/A2L/config source
→ ROS topic/field binding
→ breakpoint/debug plan
```

详细边界、独立项目结构和模块契约见 `ROS_DEBUG_DIAGNOSTIC_TOOL_FRAMEWORK.md` §17–§19。

## 12. 独立脚手架第一里程碑实测

已在独立项目 `D:\RamboStar\idea\cr60-debug-harness` 开始实现，分支为 `codex/ros-debug-scaffold`。当前不修改 `cr60_light_arbe`。

已验证：

- 9 个离线 pytest 用例通过；
- 真实 `rosbag info` fixture 可解析 duration、message count、topics/type/count；
- `preflight --execute` 通过 SSH 读取到远程 Noetic、`ROS_MASTER_URI=http://localhost:11311`、当前 nodes 和 `/play_single_frame_0..4` services；
- Windows → SSH 的 UTF-8 和 `bash -lc` 调用边界已修复；
- source snapshot 通过单次远程 tar/stream 读取 focus files，不执行 checkout/fetch/pull，也不写远程；
- 当前 source snapshot 的 outer HEAD 为 `4c171298b2c3583509ea3e3da222b90ba0a9e513`，algo submodule HEAD 为 `a81b08a38f316a3d25bfcbcad6dcfc822d24b990`，dirty 状态已进入 manifest；
- snapshot scope 包含正式 arbe 的 `visualization_node.cpp`、`postProcess.c`、`adasFunc.c`、`perception_public_def.h`、`paraDefine.h`；
- 本地 code-index 已发现 `corner_radar_post_process_data_callback`、`PostProcessMainTI`、`FrontCrossTrafficAlertAndBrake`，为后续条件/变量/debug plan 提供输入。

这证明“读取 formal arbe → 本地确定性代码准备 → 生成 debug plan”的松耦合链路可行。当前仍未执行编译、GUI 回放、GDB attach 或自动修改 arbe。

### 12.1 远程 bag targeted extraction 实测

独立项目的 `remote-bag` 入口已在真实 Linux/arbe 环境运行，使用 bag 内实际 message definition，不复制原始 1GB bag：

```text
summary schema: remote-bag-summary.v1
raw warning samples: 92
object candidates: 8
event-window LGU frames: 1263
alarm events: 2
replay plans: 2
```

生成的两个 replay plan：

```text
FCTB_L / radar1: target frame=47840, warmup=47690..47840, actual=150, ready=true
FCTA_R / radar2: target frame=47877, warmup=47727..47877, actual=150, ready=true
```

对象关联结果：

- `FCTA_R/radar2` 关联到 object `44`，保留多个候选并按 TTC 排序；
- `FCTB_L/radar1` 没有同时间、同 radar 的 object candidate，工具保留为证据缺口，不借用 radar2 的 object 代替。

这验证了“远程 formal arbe 数据抽取 → 本地 event/frame/warmup/target 规划”的第一条实际使用链路；它仍然不是算法正误结论，因为 replay output 和 runtime/GDB 采集尚未接入。

### 12.2 Runtime target gate 实测

`preflight --execute` 现在会逐个调用 formal arbe node 的 `rosnode info`，解析 PID，再用进程命令行和 `file` 检查 executable/debug symbols。当前一次快照结果：

```text
radar1: PID=853297, executable_matches=true, symbol_status=debug-ready
radar2: node found, PID unresolved, executable_matches=false, symbol_status=needs-runtime-check
radar3: PID=853334, executable_matches=true, symbol_status=debug-ready
radar4: PID=853356, executable_matches=true, symbol_status=debug-ready
```

该 gate 会阻止对 radar2 自动生成可 attach 结论，说明脚手架能发现 runtime node/进程不一致，而不是默认填入一个 PID。

### 12.3 `wfAutosarData.outputData` 真实解码

`remote-bag` 已按 formal arbe 的 `PERInfoOutStruct` debug layout 增加静态解码，并在 `CRGVI-1829` 上验证：

```text
lgu_debug_frames: 1263
decode_failures: 0
radars: 1,2,3,4
radar2 speed range in event windows: approximately 0..4.42 m/s
radar2 gear values: 4
radar2 object IDs: 44
radar2 max FCTA counter: 5
radar2 max FCTB counter: 5
```

这一步已经把“报警事件 → LGU frame → ego/ADAS enable → object counter”串成静态输入证据；它仍不代表算法重跑输出，runtime replay/debug adapter 仍是下一阶段。
### 12.5 session/debug plan 实际测试

基于真实 `CRGVI-1829` remote-bag 结果生成：

```text
session-plan schema: session-plan.v1
mutation_policy: explicit-only
replay state: blocked_no_public_control_api
missing control API: load_bag/read_bag/play/stop/seek
debug-plan: radar1, PID=853297, symbol_status=debug-ready, handoff mode
breakpoints: corner_radar_post_process_data_callback,
             FrontCrossTrafficAlertAndBrake,
             SelfIncreFctxWarnCount
```

本轮验证没有执行 build/start/GUI replay/GDB attach；session plan 正确把这些步骤标记为需要确认或需要控制适配器。

### 12.6 隔离 direct replay 实际测试

在不触碰正式 `ROS_MASTER_URI=http://localhost:11311` 会话的前提下，独立脚手架启动：

```text
ROS master: http://127.0.0.1:11321
launch: arbe_phoenix_radar_driver/arbe_radar_vis.launch
radar: 2 / Front_Right
input: /wf/corner_radar/lgu_data_2
GUI: enable_gui=false
bag window: -s 504 -u 22
PLAY_RC: 0
```

正式算法节点 `/radar2_visualization_engine/arbe_visualization_engine` 成功注册并发布 `/corner_radar/warning_status_with_frame`。实测 warning CSV 有 331 个数据行，算法输出的 active frame 为 `47875..47889`，在 radar2 上表现为：

```text
FCTA_R=2
FCTB_R=2
```

本次远程临时输出前缀为 `/tmp/cr60_harness_smoke_1787569615`。

这与同一 bag 的 recorded raw warning（`FCTB_L/radar1`、`FCTA_R/radar2`）存在差异。当前工具应输出：

```text
recorded_warning
replay_warning
replay_delta
```

不能把 direct replay 的差异直接归因于算法错误；原因可能来自 formal GUI player 的辅助 topic、时间/帧同步、radar1 未同时回放、运行时配置或算法状态初始化。该实测只证明“真实 bag → 正式算法节点 → ROS warning output”链路可运行。

### 12.7 隔离 launch-under-GDB 实际测试

在独立 `ROS master=11322` 下，使用正式 ELF：

```text
/home/hoz2wx/CR60LIGHT/cr60_light_arbe/devel/lib/arbe_phoenix_radar_driver/arbe_visualization_engine
```

以 radar2 参数启动，GDB 条件断点如下：

```text
break FrontCrossTrafficAlertAndBrake
source: adasFunc.c:9890
condition: frame_counter == 47877
```

实测结果：

```text
GDB_HIT_COUNT=1
DEBUG_HIT frame=47877 radar=2
PLAY_RC=0
formal node registered: yes
```

本次远程临时输出前缀为 `/tmp/cr60_harness_gdb_smoke_1787570340`。

在该真实目标帧读取到：

```text
g_egoCarAddInfo.carSpd = 4.42844534
g_egoCarAddInfo.actual_gear = 4
bFctaDetectFlg = true
bFctbDetectFlg = true
fFctaObjWarningBaseTTMX = 2.26308894
fFctbObjWarningBaseTTMX = 1.24952006
objInfo->trcNum = 16
objInfo->trcOutData[0].objID = 44
objInfo->trcOutData[0].distX = 5.98999977
objInfo->trcOutData[0].distY = -4.71000004
adasWarning->bRightFctaWarning = 2
adasWarning->bRightFctbWarning = 2
```

这里验证的是正式二进制中的真实函数和局部变量可采集，不是对报警正误的结论。后续诊断包必须保存 GDB command、源码 snapshot hash、target frame、radar id、运行参数、录制输入和 output warning，才能复现并比较。

### 12.8 隔离测试清理核验

两次隔离 runtime 测试后执行远程只读核验：

```text
temporary master 11321/11322: no nodes
formal master 11311: 4 existing radar algorithm nodes remain
temporary smoke/gdb process: no residue found
```

因此当前测试没有停止或重启用户原有正式会话，也没有对 `cr60_light_arbe` 工作区执行 checkout、build、写文件或 feature branch 修改。

## 13. rosbag 视角的 FCT / situation / perception 归因能力审计

### 13.1 三类问题的操作定义

为了避免把不同层次的问题混在一起，本工具暂按以下定义分类：

```text
perception:
  radar 输入或跟踪输出本身异常，例如 object ID 跳变、位置/速度不连续、
  dyn/type/validity 错误、TTC/DDCI 与轨迹明显矛盾、目标方向或侧别错误。

situation:
  场景事实或场景解释与功能期望不一致，例如目标不是相关横穿交通参与者、
  实际轨迹不进入 ego 碰撞路径、车辆状态/道路运动状态不满足需求，或 camera
  真值与 radar 目标关联不一致。

FCT:
  FCTA/FCTB 功能逻辑、阈值、状态机、计数、抑制、侧别映射或输出链路异常；
  前提是已经确认输入 perception 和 situation 证据有效。
```

### 13.2 仅凭 rosbag 能确定什么

```text
报警定位：可以，高可信
  warning topic -> timestamp -> radar -> 近邻 LGU frame -> object/camera/CAN window

输入质量筛查：可以，中到高可信
  object continuity、ID/life cycle、位置/速度、TTC/DDCI、ego、enable、CAN validity

软件条件的静态映射：可以，但需要同版本源码/参数
  将 bag 字段映射到 FCTA/FCTB 的 enable、ego gate、target gate、geometry、
  TTMX/TTMY/DDCI、counter 和 output 状态。

FCT 逻辑最终定性：仅 rosbag 通常不够
  bag 通常没有 ROI intersection、内部 fTTMX/fTTMY、brakeEnable、DTC/故障状态、
  keep/de-warning 状态等全部中间变量；需要 replay trace、GDB 或结构化 debug trace。

situation 最终真值：取决于 bag 是否有 camera/标注/校准
  有 camera 可以做人工或视觉辅助核验；没有 camera/标注时，只能判断“算法输入
  看起来是否像风险场景”，不能证明客户所说的误报警。
```

因此准确回答是：

```text
能定位关键报警信息：能。
能做 FCT/situation/perception 的初步归因：能做证据筛查和候选排序。
能只靠 rosbag 自动、确定地判定三者之一：不能普遍做到。
```

### 13.3 `CRGVI-1829` 样例的实际证据

#### 报警定位

`/corner_radar/warning_status_raw` 中：

```text
FCTB_L / radar1: 519.327431..522.925759 s, 73 samples
FCTA_R / radar2: 519.376635..520.275256 s, 19 samples
```

raw warning 本身没有可靠的 `frameID`，当前目标 frame 是通过同一 bag 的时间轴与 LGU 对齐得到的：

```text
FCTB_L / radar1 -> frame 47840
FCTA_R / radar2 -> frame 47877
```

所以报警时间和 radar 归属是高可信的，raw warning 到精确算法 frame 仍应保留 `time_alignment` provenance。

#### perception 初筛

在 radar2 的 FCTA/FCTB 窗口，`object ID=44` 具备以下连续性：

```text
object ID: 44（未跳变）
dyn_flg: 2（满足当前 FctaSkipFlg 的 1..3 动态目标范围）
position: x 约 6.32 -> 6.30 m, y -6.27 -> -3.13 m
velocity: velY 约 3.53 -> 4.55 m/s
fTTC: 1.25 -> 0.72 s
fDDCI: 9.37 -> 6.60
FCTA/FCTB counter: 0 -> 5，随后清零
```

同时：

```text
FCTA/FCTB enable: true
gear: 4
ego speed: 3.67..4.42 m/s
wheel validity: 四个轮速均为 1
outputData actual_spd_valid: 0（数据质量警告，不能忽略）
```

这组数据没有表现出明显的 ID 跳变或运动学断裂，因此当前证据不支持“纯粹的 object 跟踪数据损坏”这一解释。但 `actual_spd_valid=0` 表示 ego speed 的有效性契约需要单独核对；它可能是仿真/回灌字段语义，也可能影响算法输入，不能在工具中默认为有效。

#### situation 初筛

bag 实际包含：

```text
/cv_camera_0/image_raw/compressed: 1025 messages
/cv_camera_2/image_raw/compressed: 4235 messages
/cv_camera_4/image_raw/compressed: 4234 messages
/cv_camera_6/image_raw/compressed: 4438 messages
```

在 FCTA_R 目标时刻 `519.376635 s` 附近取到的最近图像时间差约为：

```text
camera_2: 0.039 s
camera_4: 0.024 s
camera_6: 0.056 s
```

连续图像中可以看到真实路口和横向交通：`cv_camera_4` 中白色车辆在连续帧中横穿/离开画面，`cv_camera_2` 和 `cv_camera_6` 也有横向车辆。由此可以排除“目标时刻完全没有交通参与者”的简单假设，并说明 situation 具备进一步核验的素材。

但当前仍缺：

```text
camera_id -> radar_id/object_id 的录制时映射
camera 标定与 radar 坐标投影
人工标注或客户确认的目标身份/危险性
```

因此不能仅凭当前图像说白色车辆就是 radar object 44，也不能据此直接判定报警正报。

#### FCT 逻辑初筛

当前正式 ELF 的 GDB 实测在 `frame=47877, radar=2` 得到：

```text
bFctaDetectFlg = true
bFctbDetectFlg = true
brakeEnable = true
g_egoCarAddInfo.actual_gear = 4
g_egoCarAddInfo.carSpd = 4.42844534
objInfo->trcOutData[0].objID = 44
fFctaObjWarningBaseTTMX = 2.26308894
fFctbObjWarningBaseTTMX = 1.24952006
adasWarning->bRightFctaWarning = 2
adasWarning->bRightFctbWarning = 2
```

从“代码是否进入功能、enable/ego gate 是否满足、object counter 是否达到 5、输出是否形成”的角度，当前证据是内部一致的，没有直接显示 FCT 函数漏报或状态机断裂。

但 direct replay 只回放 radar2 后得到 `FCTA_R=2, FCTB_R=2`，而 recorded raw 中包含 `FCTB_L/radar1`。这首先是 `replay_delta`/多 radar 同步/侧别映射问题，不能直接归因于 FCT 逻辑错误。

### 13.4 当前样例的诚实结论

```text
可以确定：
  1. 关键报警时间、radar、近邻 frame 可以定位；
  2. radar2 的 object 44、ego、enable、TTC/DDCI、counter 可以串起来；
  3. 当前正式 FCT 代码在目标 frame 确实执行，且相关输出状态为 active；
  4. camera 中存在与报警时刻接近的横向交通场景。

不能确定：
  1. camera 中哪一辆车就是 object 44；
  2. 客户认为的“危险性/应不应该报警”是否成立；
  3. raw warning 与 replay warning 的侧别差异究竟来自播放器、配置、同步还是算法；
  4. 仅凭 bag 是否应把问题归为 FCT、situation 或 perception。
```

对这个样例，目前不能诚实地说“已经证明是 FCT 问题”或“已经证明是 perception 问题”。较强的当前判断是：

```text
FCT 输入链和状态变化看起来自洽；没有直接 FCT bug 证据。
perception 没有明显轨迹损坏，但 ego speed validity=0 是待核查风险。
situation 具备真实 camera 证据，不能按空场景误报处理；目标关联和需求真值仍缺。
```

### 13.5 工具应输出的归因等级

后续报告不应只输出一个分类，而应输出分层结果：

```text
confirmed:
  由同一 frame、同一 topic、同一源码版本和可复现变量直接证明。

strong-suspect:
  多个独立信号一致，但缺少 ground truth 或一个关键中间变量。

screened-out:
  在当前数据范围内未发现该类问题的必要证据；不是绝对排除。

blocked:
  缺 camera mapping、版本、validity、内部 trace 或客户真值，不能分类。
```

## 14. 通过服务器地址控制 arbe debug 的实际能力审计（实测：2026-08-25）

### 14.1 launch-under-GDB：已验证可行

独立脚手架通过 SSH 登录 `10.190.171.44`，在独立 ROS master `11322` 下直接启动正式 ELF：

```text
/home/hoz2wx/CR60LIGHT/cr60_light_arbe/devel/lib/arbe_phoenix_radar_driver/arbe_visualization_engine
```

真实命令行为：

```text
gdb -q -batch --args arbe_visualization_engine ...
break FrontCrossTrafficAlertAndBrake
condition frame_counter == 47877
run
```

实际结果：

```text
GDB_HIT_COUNT=1
DEBUG_HIT frame=47877 radar=2
PLAY_RC=0
```

断点在正式源文件中解析成功：

```text
adasFunc.c:9890 FrontCrossTrafficAlertAndBrake
adasFunc.c:6364 FctaDirectRunning
adasFunc.c:7741 HandleFctaRightWarningFlag
adasFunc.c:7809 HandleFctbRightWarningFlag
```

### 14.2 断点处读取变量：已验证可行

在目标 frame 的 `FrontCrossTrafficAlertAndBrake` 停止点可以读取：

```text
function arguments:
  brakeEnable=true
  radius=861.970459
  objInfo/adasWarning/ROI pointers

algorithm variables:
  g_egoCarAddInfo.carSpd=4.42844534
  g_egoCarAddInfo.actual_gear=4
  bFctaDetectFlg=true
  bFctbDetectFlg=true
  fFctaObjWarningBaseTTMX=2.26308894
  fFctbObjWarningBaseTTMX=1.24952006

object:
  objID=44
  distX=5.98999977
  distY=-4.71000004
  velX=-0.569999993
  velY=3.98000002
  fTTC=1.01999998
  fDDCI=8.38000011
  objFctaWarningFlag=5
  objFctbWarningFlag=5
  rightFctaFlag=true

geometry:
  objPoly.num=4
  polygon points are readable from objPoly
```

因此不仅能看到函数是否命中，还能把目标对象、阈值输入、几何 polygon、计数和 warning 状态放在同一停止点分析。

注意：在函数入口 `adasFunc.c:9890` 立即执行 `info locals` 时，尚未初始化的局部变量可能显示 `NaN` 或未定义值，例如本次 `carSpdAbs`/`yawRateAbs` 的入口值不可用。工具不能把函数入口的未初始化 local 当作证据；应在初始化之后的源码行、下游函数入口或条件判断前设置断点。

### 14.3 调用流程分析：已验证可行

目标 frame 的实际 GDB backtrace：

```text
corner_radar_post_process_data_callback
  -> PostProcessMainTI(frameID=47877)
    -> AdasFunc
      -> FrontRadarAdas
        -> FrontCrossTrafficAlertAndBrake
```

继续执行后，实际停到：

```text
FrontCrossTrafficAlertAndBrake
  -> FctaDirectRunning
  -> HandleFctaRightWarningFlag
  -> HandleFctbRightWarningFlag
```

这说明工具可以通过“目标 frame 条件断点 + continue + 下游函数断点 + bt/info args”还原实际执行路径，而不是只能静态猜测调用链。本次 flow 测试临时输出前缀：

```text
/tmp/cr60_harness_gdb_smoke_1787626338
```

### 14.4 已运行 PID attach：当前服务器策略下不可行

为了不影响正式会话，测试先在独立 ROS master `11323` 正常启动正式 arbe 节点，再取得 PID：

```text
node: /radar2_visualization_engine/arbe_visualization_engine
PID: 3542530
```

随后通过 SSH 执行：

```text
gdb -q -batch -p 3542530
```

实际结果：

```text
ATTACH_HIT_COUNT=0
ptrace: Operation not permitted / 对设备不适当的 ioctl 操作
日志要求检查 /proc/sys/kernel/yama/ptrace_scope
ptrace_scope=1
```

测试结束后：

```text
temporary master 11323: 0 nodes
formal master 11311: 4 original algorithm nodes remain
temporary attach process: no residue
```

因此当前不能把“通过服务器地址自动 attach 已由 `bash start` 启动的普通 arbe PID”作为可用能力。没有修改 `ptrace_scope`、没有使用 root、也没有尝试 attach 用户当前正式 PID。

### 14.5 当前 debug 控制结论

```text
SSH 登录服务器：confirmed
发现 ROS node/PID/Radar_ID/ELF：confirmed
启动正式 arbe ELF under GDB：confirmed
目标 frame 条件断点：confirmed
断点停止后读取参数/变量/对象/几何：confirmed
backtrace 和下游函数流程分析：confirmed
continue 到后续函数断点：confirmed
attach 普通已运行 PID：blocked by ptrace_scope=1
自动控制用户当前正式 session：not attempted / requires explicit authorization
```

当前推荐的控制策略是：

```text
优先：隔离 session + launch-under-GDB + 目标 frame 条件断点
其次：若必须调试既有 PID，先由用户/管理员确认 ptrace 权限和进程归属
不做：未经确认修改 ptrace_scope、sudo attach、停止用户正式 session
```

后续产品化时，`DebugSession` 至少应记录：服务器、ROS master、启动命令、PID、ELF BuildID、源码 hash、断点表达式、命中 frame、backtrace、变量采集命令、继续/停止事件和清理结果。

## 15. 分阶段产品路线记录（2026-08-25）

独立项目新增路线文档：

```text
D:/RamboStar/idea/cr60-debug-harness/docs/SPRINT_ROADMAP.md
```

路线决策：

```text
Sprint1：批量解析和证据包，用户自己在 VS Code 执行断点
Sprint2：隔离 launch-under-GDB，工具自动回放、停断点、采集变量和调用流
Sprint3：formal player / replay parity / 多 radar / camera-object 对齐
Sprint4：FCT/situation/perception 分层归因、what-if 和参数敏感性
Sprint5：批量问题单、历史案例和 pi 编排
```

当前 Sprint1 已具备大部分底层能力，但缺少 `batch-analyze` 聚合层和统一 `diagnosis-bundle.v1`；当前 Sprint2 的 launch-under-GDB 已在真实服务器验证，普通 PID attach 被 `ptrace_scope=1` 阻塞。后续实现应优先完成 Sprint1 的用户交付包，而不是先扩大 AI 或修改 arbe。

### Sprint1 真实 batch 结果补充

已在 `10.190.171.44` 的真实 bag 上运行：

```text
command: cr60-debug batch-analyze
case: CRGVI-1829
events: 2
ready: 1
failed: 0
camera samples in event windows: 482（只保存时间/格式/字节数，不把图片 bytes 塞入 JSON）
code condition groups:
  system_enable=23
  ego_gate=17
  target_gate=12
  geometry_collision=71
  counter_state=104
  output_side=106
```

事件级初筛已进入 bundle：

```text
FCTB_L/radar1:
  perception=blocked_no_same_radar_object
  situation=camera_near_event_available_manual_mapping_required
  fct=requires_runtime_trace_or_manual_debug

FCTA_R/radar2:
  object=44
  track=track_continuity_observed
  perception=screened_no_gross_track_break
  situation=camera_near_event_available_manual_mapping_required
  fct=requires_runtime_trace_or_manual_debug
```

Sprint1 输出目录：

```text
D:/RamboStar/idea/cr60-debug-harness/outputs/batch_CRGVI-1829_sprint1/cases/CRGVI-1829/
```

包含 `diagnosis_bundle.json`、`report.md`、`alarm_events.csv`、`frame_evidence.jsonl`、`code_evidence.json`、`breakpoints_1.gdb`、`breakpoints_2.gdb` 和 `vscode_handoff.json`。这些初筛标签不是最终正误结论，仍保留 camera/object mapping、source/binary match 和 runtime trace 缺口。

## 16. Sprint1 HTML 诊断工作台方案（2026-08-25）

页面方案已记录到：

```text
D:/RamboStar/idea/cr60-debug-harness/docs/SPRINT1_HTML_VIEWER_PLAN.md
```

关键决策：

```text
diagnosis_bundle.v1 作为证据真值
viewer-model.v1 作为 HTML 渲染投影
Carbon 风格技术 cockpit，不把 HTML 变成第二个诊断引擎
场景图使用 ego/target/ROI/坐标元数据绘制
ROI 区分 observed_runtime / derived_from_code / not_available
camera 只显示真实截图、时间差和映射状态，不自动冒充 object ID 真值
Sprint1 页面只提供阅读、筛选和复制断点，不执行远程 debug
Sprint2 再把同一 breakpoint pack 接入 DebugSession
输入可以由上游 manifest 传递 code_root、coem、车型、variant、branch/tag、server、DBC、requirements 和 camera mapping；缺失必要输入时输出 blocked_missing_input
```

首版页面默认假设为文件夹批处理，生成批次索引和每条数据独立 HTML，通过本地 HTTP 服务打开；后续可增加 VS Code webview/远程网页适配器。

用户新增硬约束：HTML 属性必须展示真实代码 token，不得只展示工具自定义别名。当前页面方案将以以下真实路径作为字段主键：

```text
g_egoCarAddInfo.carSpd
g_egoCarAddInfo.actual_gear
adasEnable->bFCTAEnable / adasEnable->bFCTBEnable
objInfo->trcOutData[i].objID
objInfo->trcOutData[i].fTTC / fDDCI
objInfo->trcOutData[i].objFctaWarningFlag / objFctbWarningFlag
bFctaDetectFlg / bFctbDetectFlg / brakeEnable
fFctaObjWarningBaseTTMX / fFctbObjWarningBaseTTMX
fTTMX / fTTMXObj / fTTMY / fDDCI / fInterX / fInterY
```

真实代码别名只作为辅助中文说明，页面必须同时显示 token、结构路径、源码文件/行号、值、来源和 hash。

真实批量输入盘点：

```text
/home/hoz2wx/CR60LIGHT/data/qzh
6 个 CRGVI 目录
12 个 bag
约 12.20 GB
1 个 BLF
```

因此 HTML 必须有 Batch -> problem directory -> bag -> alarm event -> scene detail 的导航层级，不能按单个 case 写死。

## 17. 全功能 adapter 与实时 schema 结论（2026-08-25）

用户明确要求：不同算法代码仓、功能、车型和分支的参数、ROI、函数链路及消费逻辑不能硬编码，必须基于当前代码实时分析。当前实现已调整为：

```text
active source snapshot + message definitions + vehicle/coem profile
  -> code-index
  -> runtime-schema.v1
  -> data/ROI/breakpoint/viewer/Pi consumers
```

已经注册同一接口的功能：

```text
BSD / LCA / DOW / RCW / RCTA / RCTB / FCTA / FCTB
```

每个功能从当前 source index 获取自己的 entry function、Reset...Roi function、geometry functions、handler/status functions、parameter values、conditions、call edges 和 source lines。

当前远端 source snapshot v4 已补齐 commonTool.c、perception_public_api.h 等文件，code_index_v4.json 验证 8 个功能全部 source_resolved。roi_provider.py 已对当前代码中的简单/直行 ROI 表达式进行 source-driven 计算；不支持的 helper/弯道/缺失车型输入返回缺口，不复用 FCTA 固定 ROI。

新增产物和接口：

```text
cr60_debug_harness/schema_builder.py
runtime-schema.v1
cr60_debug_harness/ai_bridge.py
pi-context.v1
cr60-debug schema-build
cr60-debug pi-context
```

AI/Pi 默认不参与真值提取。Pi 只能消费当前 bundle/schema，解释调用链、归纳条件、排序 perception/situation/FCT 假设和生成下一步 debug；所有假设必须引用 source/data evidence，不能将 unknown 补成 false 或伪造参数/ROI/i。

属性 HTML 已改成 panel 内滚动和字段分组折叠；条件断点现在输出真实 File、Line、Condition、Watch 可复制块。objInfo->trcOutData[i] 的 i 与 objectlist/input index 分开显示：静态 bag 未证明时保持 runtime-only unavailable。

## 18. 多代码版本/多事件架构审计（2026-08-25）

用户进一步明确实际工作流：arbe 是独立仓，src/algo_source 是会随数据版本切分支的子仓；同一条数据可能多功能、多次报警；同一批数据的代码版本可能不一致。因此之前的“一个 batch 共用一个 profile/code-index”只能作为单版本验证样例，不能作为长期工具架构。

新的设计基线已写入：

```text
D:/RamboStar/idea/cr60-debug-harness/docs/DYNAMIC_SOURCE_CONTEXT_ARCHITECTURE.md
```

核心改变：

```text
每条数据独立 DataIdentity
每条数据绑定 SourceContext
每个 SourceContext 独立 source snapshot/code-index/runtime-schema
每次报警独立 AlarmEvent
所有 decoder/ROI/breakpoint/viewer/Pi 消费 event 对应的 schema
```

在 M1/M2 完成前不能继续扩大全局 batch/viewer 的功能逻辑。缺失 source context、submodule branch/commit 不匹配、dirty workspace、message layout 不匹配时必须阻塞或明确降级，不能使用当前工作区“碰巧”的代码版本。

对 qzh 下 12 个 bag 的 metadata 只读盘点还确认：所有 bag 都有 raw warning、radar1..4 的 LGU/objectlist、front/rear CAN；camera topic 数量存在 3 路和 4 路两种形态；大多数时长约 600 s，至少一个约 119 s。批量 intake 必须用 canonical path、size 和 bag fingerprint 去重，UI 必须按 dataset 的 camera availability 动态显示，不能假设所有数据都有 `cv_camera_6`。
