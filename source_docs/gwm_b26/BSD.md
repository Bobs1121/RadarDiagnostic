# BSD 功能分析

## 1. 功能概述
BSD (Blind Spot Detection，盲区检测) 是角雷达（Corner Radar）的核心功能之一，旨在监测车辆侧后方盲区内是否存在其他车辆或障碍物。
根据提供的源码片段，BSD 功能主要依赖于**感知层（Perception）**的目标跟踪（Track）和聚类（Cluster）处理。
- **核心机制**：通过 `g_adasRoi.leftBsdRoi` 和 `g_adasRoi.rightBsdRoi` 定义左右盲区感兴趣区域（ROI）。
- **状态管理**：系统维护 `bsdSystemState`，包含 None/Init/Standby/Active/Off/Failure/Passive 等状态。
- **报警分级**：支持两级报警（First Warning / Second Warning），通过 `objBsdWarningFlag` 和 `bLeftBsdWarning`/`bRightBsdWarning` 输出。
- **去重与融合**：在 `track.c` 中通过距离、速度、角度阈值进行 Cluster 去重（Data Association），确保同一目标不被重复跟踪，并优化跟踪门（Tracking Gate）以适应不同运动状态。

## 2. 状态机
根据 `perception_public_def.h` 中的定义，BSD 系统状态由 `bsdSystemState` (`uint8_t`) 管理。

| 状态值 | 状态名称 | 说明 |
| :--- | :--- | :--- |
| 0 | None | 初始未定义状态 |
| 1 | Init | 初始化状态，雷达自检、参数加载 |
| 2 | Standby | 待机状态，传感器就绪但功能未激活（如车速过低或开关关闭） |
| 3 | Active | **激活状态**，功能正常工作，监测盲区并可能触发报警 |
| 4 | Off | 关闭状态，功能被用户或系统强制关闭 |
| 5 | Failure | 故障状态，传感器或算法异常 |
| 6 | Passive | 被动状态，可能指降级运行或仅记录不报警 |

**状态转换逻辑推断**：
- **Init -> Active**: 当 `g_adasEnable.bBSDEnable == true` 且车速满足激活条件（通常 > 10-15 km/h，具体阈值未在片段中直接显示，但 `SetTrcGateVel` 中涉及车速判断）且无故障时。
- **Active -> Standby/Off**: 当车速低于阈值、开关关闭或进入故障状态时。
- **Any -> Failure**: 当检测到内部错误、校准失败 (`InCalibState_Failed`) 或信号丢失时。

## 3. 报警/制动逻辑
BSD 主要输出报警信号，不涉及制动（制动通常由 AEB 或 LCA 接管，但 BSD 是 LCA 的前置条件）。

### 3.1 报警触发条件
1. **ROI 判定**：目标必须位于 `leftBsdRoi` 或 `rightBsdRoi` 定义的多边形区域内。
2. **目标有效性**：
   - 目标状态需为有效跟踪（`ClusterStatus_Init` 或稳定跟踪状态）。
   - 排除静止干扰物（通过 `dynFlg` 和速度阈值判断，见 `SetTrcGateVel` 中的 `MthCluster_VelGateStacEnv`）。
   - 排除 FOV 边缘噪声（`isFOVBoard` 处理）。
3. **持续计数**：
   - 使用 `KEEPWARNINGFRM` (3帧) 或 `LOWSPEEDKEEPWARNINGFRM` (6帧) 进行滤波，防止误报。
   - 只有当目标在 ROI 内持续存在超过指定帧数，且满足速度/距离条件时，才置位 `objBsdWarningFlag`。

### 3.2 报警取消条件
1. **目标离开 ROI**：目标移出 `bsdRoi` 区域。
2. **目标消失**：跟踪丢失（Track Lost）。
3. **持续无目标**：在 ROI 内连续多帧未检测到有效目标。

### 3.3 报警等级
- **Level 1 (First Warning)**: 目标进入盲区，满足基本报警条件。
- **Level 2 (Second Warning)**: 通常用于 LCA 场景（打转向灯时），但在纯 BSD 中可能表现为更强烈的视觉/听觉提示，或者当目标距离更近、相对速度更大时触发。代码中 `bLeftBsdWarning` 定义为 `0-normal, 1-first warning, 2-second warning`。

## 4. 关键阈值
以下阈值从 `track.c` 和 `paraDefine.h` 中提取，直接影响 BSD 的目标关联和跟踪稳定性：

| 阈值名称 | 值/定义 | 含义 | 来源文件 |
| :--- | :--- | :--- | :--- |
| `MthCluster_CluDiffX` | 未显式定义，但用于 `absDistXUse` 比较 | Cluster 关联的纵向距离容差 | track.c L180 |
| `MthCluster_CluDiffY` | 未显式定义，但用于 `absDistYUse` 比较 | Cluster 关联的横向距离容差 | track.c L181 |
| `MthCluster_CluDiffVel` | 未显式定义，但用于 `absVelX` 比较 | Cluster 关联的速度容差 | track.c L182 |
| `MthCluster_VelGateStacEnv` | 浮点阈值 | 静止环境速度门限，用于区分静止目标和噪声 | track.c L500, L505 |
| `MthCluster_VelGateEnd` | 浮点阈值 | 末端速度门限 | track.c L505, L512 |
| `MthCluster_VelGate` | 浮点阈值 | 常规速度跟踪门限 | track.c L518, L538 |
| `MthCluster_VelGateSlow` | 浮点阈值 | 低速跟踪门限 (x2.0) | track.c L520 |
| `MthCluster_VelGateTurn` | 浮点阈值 | 转弯场景速度门限 | track.c L526 |
| `MthCluster_VelGateMax` | 浮点阈值 | 最大速度跟踪门限 | track.c L542 |
| `System_LaneWidth` | 浮点阈值 | 车道宽度，用于判断目标是否在同一车道或相邻车道 | track.c L502 |
| `CandToObj_NearDistXDelTwice` | 浮点阈值 | 近距删除距离的两倍，用于低速目标处理 | track.c L518 |
| `KEEPWARNINGFRM` | 3U | 正常速度下报警保持帧数 | paraDefine.h L143 |
| `LOWSPEEDKEEPWARNINGFRM` | 6U | 低速下报警保持帧数 | paraDefine.h L144 |
| `TRACK_ValidEleAng` | 浮点阈值 | 有效俯仰角，用于过滤非地面目标 | track.c L192 |
| `MthCluster_RxGateAmplify` | 浮点阈值 | 横向跟踪门限放大系数 | track.c L508, L679 |
| `MthCluster_RyGateAmplify` | 浮点阈值 | 纵向跟踪门限放大系数 | track.c L674, L679 |
| `MthCluster_RxGateMaxTrunk` | 整数阈值 | 最大横向跟踪门限（针对卡车） | track.c L686 |

## 5. 关键变量

| 变量名 | 类型 | 来源 | 含义 |
| :--- | :--- | :--- | :--- |
| `g_adasEnable.bBSDEnable` | `bool` | `globalVarDefine.h` | BSD 功能使能标志，由上层应用或用户设置 |
| `g_adasRoi.leftBsdRoi` | `polygonStruct` | `globalVarDefine.h` | 左侧盲区 ROI 多边形定义 |
| `g_adasRoi.rightBsdRoi` | `polygonStruct` | `globalVarDefine.h` | 右侧盲区 ROI 多边形定义 |
| `g_adasWarning.bLeftBsdWarning` | `uint8_t` | `globalVarDefine.h` | 左侧 BSD 报警状态 (0:正常, 1:一级, 2:二级) |
| `g_adasWarning.bRightBsdWarning` | `uint8_t` | `globalVarDefine.h` | 右侧 BSD 报警状态 (0:正常, 1:一级, 2:二级) |
| `g_adasWarning.bsdSystemState` | `uint8_t` | `globalVarDefine.h` | BSD 系统当前状态机状态 |
| `objBsdWarningFlag` | `int8_t` | `structDefine.h` | 单个目标的 BSD 报警标志，用于内部逻辑判断 |
| `leftBsdFlag` / `rightBsdFlag` | `bool` | `perception_public_def.h` | 目标是否位于左侧/右侧 BSD 区域的标志 |
| `g_egoCarAddInfo.carSpd` | `float` | 全局变量 | 自车速度，用于决定跟踪门限和报警逻辑 |
| `clusterInfo->clusterData[i]` | `struct` | `track.c` | 当前帧的聚类数据，包含距离、速度、角度等 |
| `pThClu` | `objStruct*` | `track.c` | 当前跟踪的目标轨迹结构体 |

## 6. 输入信号
1. **雷达原始数据**：点云（Point Cloud）或聚类（Cluster）数据，包含 `distX`, `distY`, `velX`, `velY`, `power`, `angEle` 等。
2. **自车状态**：
   - `g_egoCarAddInfo.carSpd`: 自车速度。
   - 自车加速度、转向角（隐含在 ROI 动态调整中）。
3. **功能配置**：
   - `g_adasEnable.bBSDEnable`: 功能开关。
   - `g_adasRoi`: 动态或静态的 ROI 多边形顶点坐标。
4. **校准数据**：
   - `g_mfTrackCalibData`: 多帧跟踪校准数据，用于补偿安装误差。

## 7. 输出信号
1. **报警状态**：
   - `g_adasWarning.bLeftBsdWarning`: 左侧盲区报警等级。
   - `g_adasWarning.bRightBsdWarning`: 右侧盲区报警等级。
2. **目标信息**：
   - `objOutDataStruct` 中的 `objBsdWarningFlag`: 每个有效目标的报警标志。
   - `leftBsdFlag` / `rightBsdFlag`: 目标所属区域标志。
3. **系统状态**：
   - `g_adasWarning.bsdSystemState`: 当前功能状态，用于诊断和 HMI 显示。
4. **EDR 数据**：
   - `objOutEDRStruct` 中的相关标志，用于事故数据记录。

## 8. 与其他功能的交互
1. **LCA (Lane Change Assist)**:
   - **依赖关系**：LCA 是 BSD 的扩展。当驾驶员打转向灯时，LCA 会检查 BSD 报警标志 (`bLeftBsdWarning`/`bRightBsdWarning`)。如果 BSD 已报警，LCA 会触发更强烈的警告（如闪烁频率加快或声音报警）。
   - **代码体现**：`objOutDataStruct` 中同时包含 `objBsdWarningFlag` 和 `objLcaWarningFlag`，且 `g_adasEnable` 中分别有 `bBSDEnable` 和 `bLCAEnable`。
2. **DOW (Door Open Warning)**:
   - **依赖关系**：DOW 通常在车辆静止或低速时工作，监测侧后方接近车辆。BSD 的 ROI 和跟踪算法为 DOW 提供基础目标检测能力。
   - **代码体现**：`g_adasRoi` 中定义了 `leftDowRoi` 和 `rightDowRoi`，与 BSD ROI 类似但范围可能不同（DOW 通常更远或更宽）。
3. **RCTA (Rear Cross Traffic Alert)**:
   - **依赖关系**：RCTA 监测倒车时的侧后方交叉交通。BSD 的侧向目标跟踪算法被复用，但 ROI 和触发条件（倒车档、低速）不同。
   - **代码体现**：`g_adasEnable` 中有 `bRCTAEnable`，`g_adasWarning` 中有 `bLeftRctaWarning`。
4. **Track/Cluster 算法**:
   - **基础支撑**：BSD 功能完全依赖于 `track.c` 中的目标跟踪和聚类去重逻辑。`SetTrcGateVel` 函数动态调整跟踪门限，确保 BSD 目标在不同车速下的跟踪稳定性，直接影响 BSD 的误报率和漏报率。