# LCA 功能分析

## 1. 功能概述
LCA (Lane Change Assist，变道辅助) 是角雷达（Corner Radar）ADAS 系统中的核心功能之一。其主要目的是在驾驶员准备变道时，监测车辆侧后方盲区及邻近车道内的目标车辆。当检测到有车辆进入 LCA 的特定感兴趣区域（ROI, Region of Interest）且满足一定的距离、速度或相对运动条件时，系统会向 HMI（人机交互界面）发送警告信号，提示驾驶员当前变道存在风险。

根据提供的源码片段，LCA 功能与 BSD（盲区检测）共享部分感知底层逻辑（如 ROI 定义、目标跟踪），但在报警触发条件上通常更为敏感或具有特定的逻辑（例如结合转向灯信号，虽然代码片段中未直接展示转向灯输入，但 `bLCAEnable` 标志位表明其独立控制）。

## 2. 状态机
根据 `perception_public_def.h` 中的定义，LCA 系统状态遵循标准的 ADAS 状态机模型：

*   **状态定义 (`lcaSystemState`)**:
    *   `0`: **None** - 未初始化或未定义。
    *   `1`: **Init** - 初始化阶段，系统正在加载参数或等待传感器数据稳定。
    *   `2`: **Standby** - 待机状态。系统已就绪，但可能因车速过低、传感器故障或功能被禁用而未激活。
    *   `3`: **Active** - 激活状态。系统正在实时监测目标，并根据逻辑判断是否触发报警。
    *   `4`: **Off** - 关闭状态。用户手动关闭或系统强制关闭。
    *   `5`: **Failure** - 故障状态。检测到内部错误、传感器失效或校准失败。
    *   `6`: **Passive** - 被动状态。通常指功能受限运行，例如在特定模式下仅监测但不报警，或等待校准完成。

*   **状态转换条件 (推断)**:
    *   **Init -> Active/Standby**: 当 `calibUpdateInfo->finalCalibState` 为 `Success` (7) 且 `bLCAEnable` 为 `true` 时，进入 Active 或 Standby（取决于车速等前置条件）。
    *   **Active -> Failure**: 当 `failureCode` 非零或 `finalCalibState` 变为错误状态（如 `RadarError`, `OutOfRangeError`）时。
    *   **Active -> Off**: 当 `bLCAEnable` 变为 `false` 时。
    *   **Standby -> Active**: 当车速满足激活阈值（代码中未明确给出具体车速阈值，但通常与 `egoCarInfo->actual_spd` 相关）且无故障时。

## 3. 报警/制动逻辑

### 报警触发条件
虽然提供的代码片段主要涉及底层跟踪和 ROI 定义，未包含完整的 LCA 报警判断逻辑（通常位于 `logic.c` 或 `warning.c`），但可以从结构和变量中推断出核心逻辑：

1.  **ROI 判断**: 目标必须位于 `g_adasRoi.leftLcaRoi` 或 `g_adasRoi.rightLcaRoi` 定义的区域内。
2.  **目标有效性**: 目标必须是有效的动态目标 (`pTemp->isMoveFlg == 1U`)，且通过鬼影过滤 (`ghostProb`) 和干扰抑制。
3.  **警告标志设置**:
    *   当满足上述条件时，目标对象结构体中的 `objLcaWarningFlag` 会被置位。
    *   全局警告结构体 `g_adasWarning` 中的 `bLeftLcaWarning` 或 `bRightLcaWarning` 会被更新。
    *   警告等级分为：`0` (Normal), `1` (First Warning/初级警告), `2` (Second Warning/高级警告)。通常 LCA 只有初级警告，或者根据 TTC/距离分为两级。
4.  **保持逻辑**:
    *   代码中定义了 `KEEPWARNINGFRM 3U` 和 `LOWSPEEDKEEPWARNINGFRM 6U`。这意味着即使目标暂时离开 ROI 或信号丢失，警告状态也会保持 3 帧（正常速度）或 6 帧（低速），以防止警告闪烁。

### 报警取消条件
1.  目标离开 LCA ROI 区域。
2.  目标不再被跟踪（Track 丢失）。
3.  警告保持帧数计数结束。
4.  功能进入 Standby、Off 或 Failure 状态。

### 制动请求
LCA 功能通常**不直接输出制动请求**（Brake Request）。制动请求通常由 AEB (Automatic Emergency Braking) 或 RCTB/FCTB 功能处理。LCA 仅输出视觉/听觉警告。代码中 `fBrakeValue` 和 `fBrakeEventTime` 存在于 `objOutEDRStruct` 中，但通常对应 RCTB/FCTB 或 AEB，而非 LCA。

## 4. 关键阈值

从 `paraDefine.h` 和 `track.c` 中提取的关键阈值：

| 阈值名称 | 值/定义 | 含义/用途 |
| :--- | :--- | :--- |
| `KEEPWARNINGFRM` | `3U` | 正常速度下，LCA 警告保持的最小帧数。 |
| `LOWSPEEDKEEPWARNINGFRM` | `6U` | 低速状态下，LCA 警告保持的最小帧数。 |
| `YAWRATETHERESHOLD` | `3.0f` | 自车横摆角速度阈值。在 `HorizontalJudgmentisnot` 中用于判断大转弯，可能影响 ROI 膨胀或目标过滤。 |
| `EXPENDRATIO` | `0.05f` | ROI 膨胀比例。用于在动态条件下（如大转弯）扩大监测区域。 |
| `TRACK_BigTurnYawRateL` | (未定义具体值，但在代码中使用) | 大转弯横摆角速度阈值。若 `g_egoCarInfo.yaw_rate > TRACK_BigTurnYawRateL`，则触发特殊的门限调整逻辑。 |
| `MthCluster_RxGateMax` | (未定义具体值) | 纵向距离门限最大值。用于限制跟踪关联的范围。 |
| `MthCluster_RyGateMax` | (未定义具体值) | 横向距离门限最大值。 |
| `MthCluster_SmallCarCrossRyGateMax` | (未定义具体值) | 针对小型车或交叉目标的横向门限最大值。 |
| `2.5f` | `2.5f` | 在大转弯且目标移动时，强制的最小关联门限（X 和 Y 方向）。 |

## 5. 关键变量

| 变量名 | 类型 | 来源 | 含义 |
| :--- | :--- | :--- | :--- |
| `bLCAEnable` | `bool` | `g_adasEnable` | LCA 功能使能标志。由上层应用或用户设置。 |
| `lcaSystemState` | `uint8_t` | `g_adasWarning` | LCA 系统当前状态机状态 (0-6)。 |
| `bLeftLcaWarning` | `uint8_t` | `g_adasWarning` | 左侧 LCA 警告状态 (0:无, 1:一级, 2:二级)。 |
| `bRightLcaWarning` | `uint8_t` | `g_adasWarning` | 右侧 LCA 警告状态 (0:无, 1:一级, 2:二级)。 |
| `leftLcaRoi` | `polygonStruct` | `g_adasRoi` | 左侧 LCA 感兴趣区域的多边形定义。 |
| `rightLcaRoi` | `polygonStruct` | `g_adasRoi` | 右侧 LCA 感兴趣区域的多边形定义。 |
| `objLcaWarningFlag` | `int8_t` | `objStruct` / `objOutEDRStruct` | 单个目标对象的 LCA 警告标志。用于底层跟踪到上层逻辑的传递。 |
| `yaw_rate` | `float` | `g_egoCarInfo` | 自车横摆角速度。用于判断自车是否在大转弯，进而调整跟踪门限。 |
| `isMoveFlg` | `uint8_t` | `objStruct` | 目标移动标志。LCA 通常只关注移动目标。 |
| `hozCanFlg` | `uint8_t` | `objStruct` | 水平取消/交叉标志。用于区分平行行驶目标和交叉目标，影响门限选择。 |

## 6. 输入信号

1.  **自车状态**:
    *   `egoCarInfo->actual_spd`: 自车实际速度。
    *   `egoCarInfo->yaw_rate`: 自车横摆角速度。
    *   `egoCarInfo->fl_whl_spd`, `fr_whl_spd` 等: 轮速，用于校准和速度计算。
2.  **雷达感知数据**:
    *   `objStruct`: 跟踪目标列表，包含距离 (`dispLen`, `distX`, `distY`)、速度、角度、ID、类型 (`objType`)、移动标志 (`isMoveFlg`) 等。
3.  **系统配置**:
    *   `g_adasEnable.bLCAEnable`: 功能开关。
    *   `g_radarPos.m_mountingPosition`: 雷达安装位置参数（偏航角、俯仰角），用于坐标转换和 ROI 生成。
4.  **校准状态**:
    *   `calibUpdateInfo->finalCalibState`: 校准结果，决定系统是否可激活。

## 7. 输出信号

1.  **警告状态**:
    *   `g_adasWarning.bLeftLcaWarning`: 左侧变道辅助警告等级。
    *   `g_adasWarning.bRightLcaWarning`: 右侧变道辅助警告等级。
2.  **系统状态**:
    *   `g_adasWarning.lcaSystemState`: 当前 LCA 功能状态机状态。
3.  **目标级信息 (可选)**:
    *   `objOutEDRStruct.objLcaWarningFlag`: 输出给上层或记录日志的单个目标警告标志。
4.  **诊断信息**:
    *   `failureCode`: 如果 LCA 因故障退出，输出相应的故障码。

## 8. 与其他功能的交互

1.  **与 BSD (盲区检测) 的交互**:
    *   **共享 ROI**: 代码中 `adasROIStruct` 同时包含 `leftBsdRoi` 和 `leftLcaRoi`。通常 LCA ROI 是 BSD ROI 的扩展或子集，或者两者在空间上重叠但逻辑不同。
    *   **共享跟踪**: 两者都依赖 `objStruct` 中的同一套跟踪目标。`objBsdWarningFlag` 和 `objLcaWarningFlag` 是独立的，但可能基于相同的 ROI 判断逻辑。
    *   **优先级**: 在某些实现中，如果 BSD 和 LCA 同时触发，LCA 警告可能具有更高的优先级或不同的提示音/灯，因为 LCA 通常与转向灯联动，暗示驾驶员即将变道。

2.  **与 RCTA/FCTA (交叉交通警报) 的交互**:
    *   **目标分类**: `hozCanFlg` (水平取消标志) 和 `isFOVCrossing` 用于区分平行目标（BSD/LCA）和交叉目标（RCTA/FCTA）。
    *   **ROI 分离**: `leftRctaRoi` 和 `leftLcaRoi` 是独立的多边形，分别针对后方交叉和侧方变道场景。

3.  **与校准模块 (Calibration) 的交互**:
    *   LCA 功能激活依赖于 `finalCalibState` 为 `Success`。
    *   在线校准 (`OA_temp`) 和静态校准 (`EOL`) 的结果直接影响 `g_aziShiftDefault` 和 `g_eleShiftDefault`，进而影响目标在自车坐标系下的位置计算，确保 ROI 判断的准确性。

4.  **与 HMI 的交互**:
    *   `bLeftLcaWarning` 和 `bRightLcaWarning` 直接映射到仪表盘上的盲区指示灯或变道辅助图标。