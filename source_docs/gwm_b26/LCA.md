# LCA 功能分析

## 1. 功能概述
LCA (Lane Change Assist，变道辅助) 是角雷达（Corner Radar）ADAS系统中的核心功能之一。其主要目的是在驾驶员意图变道时（通常通过转向灯信号触发），监测车辆侧后方盲区及邻近车道是否有目标车辆接近。如果检测到潜在碰撞风险或目标车辆处于危险距离内，系统将通过视觉（仪表盘图标）或听觉（蜂鸣器）方式向驾驶员发出警告，防止因盲区存在车辆而导致的变道碰撞事故。

根据提供的源码片段，LCA功能与BSD（盲区检测）共享大量的底层感知逻辑（如ROI定义、目标跟踪、状态机管理），但在触发条件上依赖于转向灯信号（Turn Signal），且拥有独立的使能标志和警告标志。

## 2. 状态机
虽然提供的代码片段主要展示了感知层（Perception）和后处理（PostProcess）的部分逻辑，未直接展示LCA应用层的状态机转换代码，但根据 `perception_public_def.h` 中的定义和通用ADAS架构，可以推断LCA的状态机结构如下：

**状态定义 (参考 `perception_public_def.h` L777):**
*   **0 - None**: 功能未初始化或未使能。
*   **1 - Init**: 初始化阶段，等待传感器数据稳定或校准完成。
*   **2 - Standby**: 待机状态。功能已激活，但当前不满足触发条件（例如：转向灯未打开，或车速低于最低工作车速）。
*   **3 - Active**: 激活状态。转向灯已打开，系统正在监测LCA ROI区域，若发现目标则可能触发报警。
*   **4 - Off**: 功能关闭（用户手动关闭或系统故障）。
*   **5 - Failure**: 故障状态（雷达故障、校准失败等）。
*   **6 - Passive**: 被动状态（可能指传感器数据不可用但功能逻辑仍在运行，或等待恢复）。

**状态转换条件推断:**
*   **Init -> Standby**: 雷达校准成功 (`finalCalibState == Success`)，且系统自检通过。
*   **Standby -> Active**: `bLCAEnable` 为真，且检测到转向灯信号 (Turn Signal Left/Right) 激活，且车速满足工作范围。
*   **Active -> Standby**: 转向灯关闭，或目标离开ROI区域且无报警。
*   **Any -> Failure**: 检测到雷达硬件故障、通信丢失或校准错误 (`failureCode` 非零)。

## 3. 报警/制动逻辑
LCA通常只涉及**报警**，不涉及制动（制动属于LCA的扩展功能或与其他功能如AEB融合，但在标准LCA中仅为警告）。

**触发报警条件:**
1.  **功能使能**: `g_adasEnable.bLCAEnable` 为 `true`。
2.  **系统状态**: `lcaSystemState` 为 `Active` (3)。
3.  **目标存在**: 在左侧 (`leftLcaRoi`) 或右侧 (`rightLcaRoi`) 的LCA感兴趣区域（ROI）内检测到有效目标轨迹。
4.  **目标有效性**:
    *   目标必须是动态的 (`isMoveFlg == 1`)。
    *   目标类型通常为车辆 (`objType` 为 Car/Truck/Motorbike等，排除行人/自行车，具体取决于配置，但LCA主要针对车辆)。
    *   目标角度和速度符合变道冲突模型。
5.  **警告标志置位**:
    *   若左侧有威胁，`objLcaWarningFlag` 或 `leftLcaFlag` 置位。
    *   最终输出 `bLeftLcaWarning` 或 `bRightLcaWarning`。
    *   警告级别可能分为 `1-first warning` (视觉) 和 `2-second warning` (听觉/紧急)，具体取决于目标距离和相对速度。

**取消报警条件:**
1.  目标离开LCA ROI区域。
2.  目标被确认为静止或非威胁目标。
3.  转向灯关闭。
4.  满足 `KEEPWARNINGFRM` (3帧) 或 `LOWSPEEDKEEPWARNINGFRM` (6帧) 的消抖条件后，清除警告标志。

## 4. 关键阈值
根据 `paraDefine.h` 和 `track.c` 中的代码片段，提取以下关键阈值：

| 阈值名称 | 值 | 含义/用途 |
| :--- | :--- | :--- |
| `TRACK_BigTurnYawRateL` | (未定义具体数值，但在 `track.c` L704 使用) | 大转弯横摆角速度阈值。用于判断车辆是否处于大转弯状态，从而调整跟踪门限。 |
| `2.5f` | 2.5 米 | `track.c` L714-715: 在大转弯且目标移动时，跟踪门限（Gate）的最小扩展值，确保不丢失目标。 |
| `MthCluster_RxGateMax` | (宏定义，未显示值) | `track.c` L718: 纵向跟踪门限的最大值。 |
| `MthCluster_RyGateMax` | (宏定义，未显示值) | `track.c` L725: 横向跟踪门限的最大值。 |
| `MthCluster_SmallCarCrossRyGateMax` | (宏定义，未显示值) | `track.c` L712/722: 小车辆交叉时的横向门限最大值，用于处理快速接近的小目标。 |
| `KEEPWARNINGFRM` | 3 帧 | `paraDefine.h` L143: 保持警告的最少帧数，用于防止误报闪烁。 |
| `LOWSPEEDKEEPWARNINGFRM` | 6 帧 | `paraDefine.h` L144: 低速时保持警告的帧数，低速下目标运动变化慢，需要更长的确认时间。 |
| `YAWRATETHERESHOLD` | 3.0f | `paraDefine.h` L145: 横摆角速度阈值，可能用于判断车辆是否处于剧烈转向状态，影响ROI或跟踪逻辑。 |
| `EXPENDRATIO` | 0.05f | `paraDefine.h` L146: ROI或门限的膨胀比例，用于增加检测鲁棒性。 |

## 5. 关键变量

| 变量名 | 类型 | 来源 | 含义 |
| :--- | :--- | :--- | :--- |
| `bLCAEnable` | `bool` | `g_adasEnable` (Global) | LCA功能使能标志，由用户设置或系统状态决定。 |
| `lcaSystemState` | `uint8_t` | `g_adasWarning` (Global) | LCA系统当前状态 (0-6)。 |
| `leftLcaRoi` / `rightLcaRoi` | `polygonStruct` | `g_adasRoi` (Global) | 左侧/右侧LCA的感兴趣区域多边形定义，用于判断目标是否在监测范围内。 |
| `leftLcaFlag` / `rightLcaFlag` | `bool` | `objOutEDRStruct` (Per Object) | 单个目标是否触发左侧/右侧LCA警告的标志。 |
| `bLeftLcaWarning` / `bRightLcaWarning` | `uint8_t` | `g_adasWarning` (Global) | 系统级LCA警告输出。0:正常, 1:一级警告, 2:二级警告。 |
| `objLcaWarningFlag` | `int8_t` | `objStruct` (Per Object) | 目标对象内部的LCA警告标志，用于中间状态传递。 |
| `isMoveFlg` | `uint8_t` | `objStruct` (Per Object) | 目标移动标志，1表示移动目标，LCA通常只关注移动目标。 |
| `hozCanFlg` | `uint8_t` | `objStruct` (Per Object) | 水平方向候选标志，用于跟踪算法中的门限调整。 |
| `yaw_rate` | `float` | `g_egoCarInfo` (Global) | 自车横摆角速度，用于判断自车是否在大转弯，影响跟踪门限。 |
| `dispLen` | `float` | `objStruct` (Per Object) | 目标的显示长度或距离相关参数，用于动态调整跟踪门限。 |

## 6. 输入信号
1.  **雷达原始点云/聚类数据**: 用于生成目标轨迹。
2.  **自车状态**:
    *   `g_egoCarInfo.yaw_rate`: 横摆角速度。
    *   `g_egoCarInfo.actual_spd`: 自车实际速度。
    *   `g_egoCarInfo.fl_whl_spd` 等: 轮速，用于速度校准。
3.  **功能使能信号**:
    *   `g_adasEnable.bLCAEnable`: LCA开关。
    *   (隐含) 转向灯信号: 虽然代码片段未直接显示转向灯变量，但LCA逻辑必然依赖转向灯信号来进入 `Active` 状态。
4.  **校准参数**:
    *   `g_radarPos.m_mountingPosition.radar_yaw_angle`: 雷达安装偏航角，用于坐标转换。
    *   `calibUpdateInfo.egoCarSpdCoef`: 速度系数，用于修正自车速度。
5.  **ROI定义**:
    *   `g_adasRoi.leftLcaRoi` / `rightLcaRoi`: 动态或静态计算的LCA监测区域。

## 7. 输出信号
1.  **LCA警告标志**:
    *   `g_adasWarning.bLeftLcaWarning`: 左侧LCA警告 (0/1/2)。
    *   `g_adasWarning.bRightLcaWarning`: 右侧LCA警告 (0/1/2)。
2.  **系统状态**:
    *   `g_adasWarning.lcaSystemState`: LCA功能当前状态。
3.  **目标级信息** (用于调试或与其他模块交互):
    *   `objOutEDRStruct.leftLcaFlag` / `rightLcaFlag`: 每个目标是否触发LCA。
    *   `objOutEDRStruct.objLcaWarningFlag`: 目标LCA警告标志。

## 8. 与其他功能的交互
1.  **与BSD (Blind Spot Detection) 的交互**:
    *   **共享ROI**: LCA和BSD通常共享类似的侧后方监测区域，但LCA的ROI可能更侧重于邻近车道的延伸部分，而BSD侧重于紧邻盲区的区域。代码中 `leftBsdRoi` 和 `leftLcaRoi` 分别定义，说明它们是独立计算或配置的。
    *   **共享跟踪逻辑**: `track.c` 中的 `HorizontalJudgmentisnot` 和 `GetTrcGate` 函数被BSD和LCA共同使用，用于目标跟踪和门限管理。
    *   **状态互斥/协同**: 通常BSD是常开的（只要车速达标），而LCA是事件触发的（转向灯）。当LCA激活时，BSD的警告可能会被抑制或合并，以避免重复报警。
2.  **与校准模块 (Calibration) 的交互**:
    *   LCA功能依赖于准确的雷达安装角度校准 (`radar_yaw_angle`, `radar_pitch_angle`)。如果校准状态 (`finalCalibState`) 不是 `Success`，LCA可能无法进入 `Active` 状态或输出不可靠。
    *   `postProcess.c` 中的速度校准 (`egoCarSpdCoef`) 直接影响目标相对速度的计算，进而影响LCA的TTC（碰撞时间）判断和警告触发。
3.  **与感知层 (Perception) 的交互**:
    *   LCA依赖于感知层输出的目标列表 (`objStruct`)，包括目标的距离、速度、角度、类型和移动状态。
    *   感知层中的 `hozCanFlg` (水平候选标志) 和 `isMoveFlg` (移动标志) 直接决定目标是否被LCA逻辑进一步处理。