# BSD 功能分析

## 1. 功能概述
BSD (Blind Spot Detection，盲区检测) 是角雷达（Corner Radar）的核心功能之一，主要用于监测车辆侧后方的盲区区域。当检测到有目标车辆或物体处于本车侧后方盲区，且与本车存在相对运动风险时，系统会向驾驶员发出警告（通常通过仪表盘指示灯或声音）。

根据提供的源码片段，BSD 功能主要涉及以下逻辑层面：
1.  **感知层 (Perception)**：在 `track.c` 中进行点云聚类、轨迹跟踪、目标分类及干扰抑制。特别是针对低速、静止目标以及近距离目标的特殊处理逻辑。
2.  **功能层 (Function)**：定义 BSD 的 ROI (Region of Interest) 区域，判断目标是否进入盲区，并根据目标状态（速度、距离、相对位置）决定报警等级。
3.  **状态管理**：维护 BSD 系统的运行状态（Init/Active/Off 等）。

## 2. 状态机
根据 `perception_public_def.h` 中的定义，BSD 系统状态机包含以下状态：

*   **状态定义**:
    *   `0`: None (未定义/初始)
    *   `1`: Init (初始化)
    *   `2`: Standby (待机)
    *   `3`: Active (激活/工作中)
    *   `4`: Off (关闭)
    *   `5`: Failure (故障)
    *   `6`: Passive (被动/降级模式)

*   **状态转换逻辑推断**:
    *   **Init -> Active**: 当系统自检通过、校准完成 (`InCalibState_Succeed`)、且 `g_adasEnable.bBSDEnable` 为 `true` 时，进入 Active 状态。
    *   **Active -> Off**: 当用户手动关闭功能或 `g_adasEnable.bBSDEnable` 变为 `false` 时。
    *   **Active -> Failure**: 当雷达硬件故障、数据异常或校准失败 (`InCalibState_Failed`) 时。
    *   **Active -> Standby**: 可能发生在车速过低（如 < 10km/h，具体阈值未在片段中明确，但通常 BSD 在极低速下抑制）或系统资源受限暂时挂起时。
    *   **Failure -> Active**: 故障恢复后重新初始化。

*   **关键变量**: `g_adasWarning.bsdSystemState` (uint8_t)

## 3. 报警/制动逻辑
BSD 本身通常只产生**视觉/听觉报警**，不直接触发制动（制动通常由 AEB 或 RCTB 处理，但 BSD 是 RCTB 的前置感知基础）。

*   **报警触发条件**:
    1.  **ROI 判定**: 目标必须位于 `g_adasRoi.leftBsdRoi` 或 `g_adasRoi.rightBsdRoi` 定义的多边形区域内。
    2.  **目标有效性**: 目标必须是通过跟踪算法确认的有效轨迹 (`ClusterStatus_Init` 或更高状态)，且非幽灵目标 (`ghostProb` 低)。
    3.  **相对运动**: 目标与本车存在相对速度，且未处于“超越缓冲区” (`overTakeBuffer` 状态)。
    4.  **持续帧数**: 报警通常需要持续一定帧数（`KEEPWARNINGFRM` 或 `LOWSPEEDKEEPWARNINGFRM`）以抑制误报。

*   **报警等级**:
    *   `0`: Normal (无报警)
    *   `1`: First Warning (一级报警，通常闪烁或低音量)
    *   `2`: Second Warning (二级报警，通常常亮或高音量，可能伴随 LCA 触发时的紧急提示)

*   **报警取消条件**:
    *   目标离开 BSD ROI 区域。
    *   目标被判定为静止且无碰撞风险（如路边固定物体）。
    *   目标完成超越，进入 `overTakeBuffer` 状态并驶离。
    *   系统状态切换至 Off 或 Failure。

*   **关键代码逻辑参考**:
    *   `objOutDataStruct` 中的 `objBsdWarningFlag` 存储单个目标的报警标志。
    *   `adasWarningStruct` 中的 `bLeftBsdWarning` / `bRightBsdWarning` 存储系统级报警状态。

## 4. 关键阈值
从 `track.c` 和 `paraDefine.h` 中提取的关键阈值：

| 阈值名称 | 值/宏定义 | 含义 | 来源文件 |
| :--- | :--- | :--- | :--- |
| `MthCluster_VelGateStacEnv` | 未显示具体值 | 静止环境速度门限，用于判断目标是否绝对静止 | `track.c` L500, L505 |
| `MthCluster_VelGateEnd` | 未显示具体值 | 末端速度门限，用于低速目标跟踪 | `track.c` L505, L512 |
| `MthCluster_VelGate` | 未显示具体值 | 常规速度门限 | `track.c` L518, L538 |
| `MthCluster_VelGateSlow` | 未显示具体值 | 低速速度门限，用于低速移动目标 | `track.c` L520 |
| `MthCluster_VelGateTurn` | 未显示具体值 | 转弯/近距离速度门限 | `track.c` L526 |
| `MthCluster_VelGateMax` | 未显示具体值 | 最大速度门限 | `track.c` L542 |
| `CandToObj_NearDistXDelTwice` | 未显示具体值 | 近距离纵向距离阈值，用于区分近场/远场处理逻辑 | `track.c` L518 |
| `1.5f` | 1.5 米 | 极近距离纵向距离，触发特殊速度门限 (`MthCluster_VelGateTurn`) | `track.c` L524 |
| `2.0f` | 2.0 米 | 低速近场横向/纵向距离阈值，触发特殊跟踪门限 | `track.c` L677 |
| `25.0f` | 25 米 | 大型车辆（Truck）远距离长度补偿阈值 | `track.c` L671 |
| `10.0f` | 10 米 | 大型车辆长度阈值，用于判断是否为卡车 | `track.c` L671 |
| `3.0f` | 3.0 米 | FOV 边缘目标的最小跟踪门限 X 方向 | `track.c` L663, L818 |
| `2.5f` | 2.5 米 | 某些条件下的最小跟踪门限 Y 方向 | `track.c` L654 |
| `KEEPWARNINGFRM` | 3 | 常规报警保持帧数 | `paraDefine.h` L143 |
| `LOWSPEEDKEEPWARNINGFRM` | 6 | 低速报警保持帧数（更严格，防误报） | `paraDefine.h` L144 |
| `YAWRATETHERESHOLD` | 3.0f | 航向角变化率阈值，用于判断目标转向意图 | `paraDefine.h` L145 |
| `MthCluster_CluDiffX/Y/Vel` | 未显示具体值 | 聚类合并的距离和速度差异阈值 | `track.c` L180-L182 |

## 5. 关键变量

| 变量名 | 类型 | 来源 | 含义 |
| :--- | :--- | :--- | :--- |
| `g_adasEnable.bBSDEnable` | bool | `globalVarDefine.h` | BSD 功能使能标志，由上层应用或用户设置 |
| `g_adasRoi.leftBsdRoi` | polygonStruct | `globalVarDefine.h` | 左侧盲区检测感兴趣区域 (ROI) 定义 |
| `g_adasRoi.rightBsdRoi` | polygonStruct | `globalVarDefine.h` | 右侧盲区检测感兴趣区域 (ROI) 定义 |
| `g_adasWarning.bLeftBsdWarning` | uint8_t | `globalVarDefine.h` | 左侧 BSD 报警状态 (0:正常, 1:一级, 2:二级) |
| `g_adasWarning.bRightBsdWarning` | uint8_t | `globalVarDefine.h` | 右侧 BSD 报警状态 (0:正常, 1:一级, 2:二级) |
| `g_adasWarning.bsdSystemState` | uint8_t | `globalVarDefine.h` | BSD 系统运行状态机当前状态 |
| `objStruct.objBsdWarningFlag` | int8_t | `structDefine.h` | 单个目标对象的 BSD 报警标志，用于底层跟踪结果上传 |
| `objStruct.overTakeBuffer` | uint8_t | `structDefine.h` | 超越缓冲区标志，防止对已超越车辆重复报警 |
| `objStruct.isFOVCrossing` | uint8_t | `structDefine.h` | FOV 穿越标志，用于处理进出视场的目标 |
| `g_egoCarAddInfo.carSpd` | float | 全局变量 | 本车车速，用于区分低速/高速逻辑及静止判断 |
| `pTemp->dynFlg` | uint8_t | `track.c` | 目标动态属性标志 (Stationary/Stopped/Moving) |

## 6. 输入信号
1.  **雷达原始数据**: 点云数据 (Clusters)，包含距离、角度、速度、功率等。
2.  **本车状态**:
    *   `g_egoCarAddInfo.carSpd`: 本车车速。
    *   本车航向角、横摆角速度 (用于坐标转换和 ROI 计算)。
3.  **功能使能信号**: `g_adasEnable.bBSDEnable`。
4.  **校准数据**: `g_mfTrackCalibData`，用于雷达安装角度补偿。
5.  **环境信息**: 车道线信息 (可选，用于动态调整 ROI 宽度)。

## 7. 输出信号
1.  **报警状态**:
    *   `g_adasWarning.bLeftBsdWarning`: 左侧盲区报警等级。
    *   `g_adasWarning.bRightBsdWarning`: 右侧盲区报警等级。
2.  **目标列表**:
    *   `objOutDataStruct` 数组，包含每个有效目标的 `objBsdWarningFlag`、`distX`、`distY`、`velX`、`velY` 等信息。
3.  **系统状态**:
    *   `g_adasWarning.bsdSystemState`: 当前 BSD 功能状态。

## 8. 与其他功能的交互
1.  **LCA (Lane Change Assist)**:
    *   **依赖关系**: LCA 是 BSD 的增强功能。当 BSD 检测到盲区有目标，且驾驶员打转向灯时，LCA 会触发更强烈的报警（二级报警）。
    *   **代码体现**: `objOutDataStruct` 中同时存在 `objBsdWarningFlag` 和 `objLcaWarningFlag`。`g_adasRoi` 中定义了 `leftLcaRoi`，通常比 BSD ROI 更靠前或更宽。
2.  **RCTA/RCTB (Rear Cross Traffic Alert/Brake)**:
    *   **依赖关系**: RCTA 在倒车时激活，检测后方横向来车。BSD 的感知算法（特别是低速、静止目标处理）与 RCTA 共享底层跟踪逻辑。
    *   **代码体现**: `track.c` 中的低速逻辑 (`MthCluster_VelGateSlow`) 对 RCTA 至关重要。`g_adasRoi` 中包含 `leftRctaRoi`。
3.  **DOW (Door Open Warning)**:
    *   **依赖关系**: DOW 检测侧后方接近的车辆，防止开门碰撞。与 BSD 共享侧后方感知能力。
    *   **代码体现**: `g_adasRoi` 中包含 `leftDowRoi`。
4.  **RCW (Rear Cross Warning / Rear Collision Warning)**:
    *   **依赖关系**: 检测正后方追尾风险。虽然方向不同，但共享后向雷达的感知资源。
5.  **跟踪算法 (Track)**:
    *   **核心交互**: BSD 功能完全依赖于 `track.c` 中的目标跟踪质量。`track.c` 中的聚类合并 (`ClusterStatus_NoUsedNear`)、速度门限调整 (`SetTrcGateVel`) 直接影响 BSD 的检测率和误报率。例如，L500-L545 的逻辑确保了在静止或低速环境下，雷达能正确区分路边静止物体和移动车辆，这对 BSD 的准确性至关重要。