# LCA 功能分析

## 1. 功能概述
LCA (Lane Change Assist，变道辅助) 是角雷达 ADAS 系统中的核心功能之一。其核心逻辑在于监测车辆侧后方盲区及延伸区域（LCA ROI）内的目标车辆。当本车驾驶员打转向灯（意图变道）且侧后方存在目标车辆时，LCA 功能会触发视觉或听觉报警，提醒驾驶员当前变道不安全。

根据提供的源码片段，LCA 功能依赖于高精度的目标跟踪（Tracking）、ROI（感兴趣区域）判定以及车辆状态（如航向角速度、车速）的实时监测。代码中体现了对大转弯工况下的特殊处理逻辑，以及基于标定参数（Calibration）的坐标修正。

## 2. 状态机
虽然提供的代码片段未直接展示完整的 LCA 状态机转换图，但根据 `perception_public_def.h` 中的定义和通用 ADAS 逻辑，可以推断出 LCA 的状态机结构：

*   **状态定义**:
    *   `0`: None (未定义/初始)
    *   `1`: Init (初始化)
    *   `2`: Standby (待机，功能使能但条件不满足)
    *   `3`: Active (激活，满足报警条件，正在报警)
    *   `4`: Off (关闭，功能被禁用或故障)
    *   `5`: Failure (故障)
    *   `6`: Passive (被动/抑制，如车速过低或过高，或标定未完成)

*   **状态转换条件推断**:
    *   **Standby -> Active**:
        1.  `g_adasEnable.bLCAEnable` 为 True。
        2.  系统状态正常 (`lcaSystemState` 非 Failure/Off)。
        3.  检测到目标在 LCA ROI 内 (`leftLcaFlag` 或 `rightLcaFlag` 为 True)。
        4.  驾驶员打转向灯（通常由 CAN 信号输入，虽未在片段中直接显示，但为 LCA 触发必要条件）。
        5.  满足持续帧数要求 (`KEEPWARNINGFRM` 或 `LOWSPEEDKEEPWARNINGFRM`)。
    *   **Active -> Standby**:
        1.  目标离开 LCA ROI。
        2.  驾驶员关闭转向灯。
        3.  报警持续时间结束或目标消失。
    *   **Any -> Failure/Off**:
        1.  雷达硬件故障。
        2.  标定失败 (`finalCalibState` 异常)。
        3.  用户手动关闭功能。

## 3. 报警/制动逻辑

### 3.1 报警触发逻辑
1.  **ROI 判定**: 目标必须位于 `leftLcaRoi` 或 `rightLcaRoi` 定义的多边形区域内。
2.  **目标有效性**: 目标必须是有效跟踪轨迹 (`objStruct`)，且非鬼影 (`ghostProb` 低)，非静态干扰物。
3.  **动态属性**: 目标通常需为运动目标 (`isMoveFlg == 1`)，或者在特定低速场景下静态目标也可能被考虑（取决于具体配置，但 LCA 主要关注运动车辆）。
4.  **航向角速度补偿**: 在大转弯工况下 (`g_egoCarInfo.yaw_rate > TRACK_BigTurnYawRateL`)，算法会动态调整跟踪门限（Gate），以确保持续跟踪目标，防止因本车急转导致目标丢失或误判。
5.  **去抖处理**: 报警信号需持续一定帧数 (`KEEPWARNINGFRM` = 3 帧 或 `LOWSPEEDKEEPWARNINGFRM` = 6 帧) 才会最终输出 `bLeftLcaWarning` 或 `bRightLcaWarning`。

### 3.2 报警取消逻辑
1.  **目标离开**: 目标移出 LCA ROI 区域。
2.  **目标消失**: 跟踪轨迹丢失或目标被标记为无效。
3.  **转向灯关闭**: 驾驶员取消变道意图。
4.  **超时**: 报警持续超过最大允许时间（防止误报持续骚扰）。

### 3.3 制动逻辑
*   **注意**: LCA 功能通常**不包含**自动制动请求。制动请求主要由 AEB (自动紧急制动) 或 RCTB (后方交叉交通制动) 等功能负责。
*   在提供的代码中，`fBrakeValue` 和 `fBrakeEventTime` 存在于 `adasWarningStruct` 中，但 LCA 的标志位 (`bLeftLcaWarning`) 仅用于报警，不直接驱动制动。

## 4. 关键阈值

| 阈值名称 | 定义/来源 | 数值/含义 | 用途 |
| :--- | :--- | :--- | :--- |
| `TRACK_BigTurnYawRateL` | `track.c` | 未直接给出数值，但用于比较 `g_egoCarInfo.yaw_rate` | 判断本车是否处于大转弯状态，触发特殊的跟踪门限调整逻辑。 |
| `KEEPWARNINGFRM` | `paraDefine.h` | `3U` | 正常速度下，LCA 报警信号需持续 3 帧才确认为有效报警。 |
| `LOWSPEEDKEEPWARNINGFRM` | `paraDefine.h` | `6U` | 低速工况下，LCA 报警信号需持续 6 帧才确认为有效报警（增加稳定性）。 |
| `MthCluster_RxGateMax` | `track.c` | 未直接给出数值 | 跟踪门限 X 轴（纵向）的最大限制值。 |
| `MthCluster_RyGateMax` | `track.c` | 未直接给出数值 | 跟踪门限 Y 轴（横向）的最大限制值。 |
| `MthCluster_SmallCarCrossRyGateMax` | `track.c` | 未直接给出数值 | 针对小型车或交叉交通目标的横向跟踪门限最大值。 |
| `2.5f` | `track.c` | `2.5` 米 | 大转弯工况下，跟踪门限的最小保底值（X 和 Y 方向），确保在剧烈运动下不丢失目标。 |
| `0.1` | `postProcess.c` | `0.1` 弧度/度 | 判断雷达安装偏航角是否接近零，用于选择默认的方位角偏移量 (`dotCalib_aziShiftDefaultRR` 或 `180.0f + angle`)。 |

## 5. 关键变量

| 变量名 | 类型 | 来源 | 含义 |
| :--- | :--- | :--- | :--- |
| `g_adasEnable.bLCAEnable` | `bool` | `globalVarDefine.h` / 配置 | LCA 功能使能标志。 |
| `g_adasRoi.leftLcaRoi` | `polygonStruct` | `globalVarDefine.h` | 左侧 LCA 感兴趣区域多边形定义。 |
| `g_adasRoi.rightLcaRoi` | `polygonStruct` | `globalVarDefine.h` | 右侧 LCA 感兴趣区域多边形定义。 |
| `g_adasWarning.bLeftLcaWarning` | `uint8_t` | `globalVarDefine.h` | 左侧 LCA 报警状态 (0:正常, 1:一级报警, 2:二级报警)。 |
| `g_adasWarning.bRightLcaWarning` | `uint8_t` | `globalVarDefine.h` | 右侧 LCA 报警状态 (0:正常, 1:一级报警, 2:二级报警)。 |
| `g_egoCarInfo.yaw_rate` | `float` | `track.c` / 车辆总线 | 本车航向角速度，用于判断大转弯工况。 |
| `pTemp->isMoveFlg` | `uint8_t` | `track.c` | 目标是否为运动目标标志。 |
| `pTemp->hozCanFlg` | `uint8_t` | `track.c` | 目标是否被标记为横向交叉/候选目标标志。 |
| `trcGateX`, `trcGateY` | `float` | `track.c` | 动态计算的跟踪门限（纵向和横向），用于关联点迹与轨迹。 |
| `g_radarPos.m_mountingPosition.radar_yaw_angle` | `float` | `postProcess.c` | 雷达安装偏航角，用于坐标系统一和 ROI 映射。 |
| `calibUpdateInfo.egoCarSpdCoef` | `float` | `postProcess.c` | 车速系数，用于修正雷达测速或里程计误差。 |

## 6. 输入信号

1.  **雷达原始点迹/聚类数据**: 用于生成和更新目标轨迹 (`objStruct`)。
2.  **车辆状态信号**:
    *   `g_egoCarInfo.yaw_rate`: 航向角速度。
    *   `egoCarInfo->actual_spd`: 本车实际车速（经过 `egoCarSpdCoef` 修正）。
    *   `g_radarPos.m_mountingPosition`: 雷达安装位置及角度（Yaw, Pitch）。
3.  **驾驶员意图信号**:
    *   左/右转向灯状态（虽未在代码片段中显式出现，但 LCA 触发逻辑隐含此输入，通常通过 CAN 信号读取并映射到 `g_adasEnable` 或内部标志位）。
4.  **标定参数**:
    *   `dotCalib_aziShiftDefaultRR`: 默认方位角偏移。
    *   `calibUpdateInfo`: 在线标定更新信息。

## 7. 输出信号

1.  **报警标志**:
    *   `g_adasWarning.bLeftLcaWarning`: 左侧变道辅助报警等级。
    *   `g_adasWarning.bRightLcaWarning`: 右侧变道辅助报警等级。
2.  **目标级报警标志**:
    *   `objStruct->objLcaWarningFlag`: 标记特定目标是否触发了 LCA 报警，用于调试和 EDR 记录。
3.  **系统状态**:
    *   `g_adasWarning.lcaSystemState`: LCA 功能当前状态机状态。
4.  **EDR 记录数据**:
    *   `objOutEDRStruct->objLcaWarningFlag`: 用于事故数据记录。

## 8. 与其他功能的交互

1.  **与 BSD (盲区检测) 的交互**:
    *   **ROI 重叠**: LCA ROI 通常比 BSD ROI 更远或更长，以覆盖变道路径。两者共享底层的目标跟踪算法 (`track.c`)。
    *   **逻辑互斥/优先级**: 当目标同时在 BSD 和 LCA 区域时，通常 BSD 报警优先级更高或两者同时报警。代码中 `bBSDEnable` 和 `bLCAEnable` 独立控制，但目标属性 (`objBsdWarningFlag`, `objLcaWarningFlag`) 独立计算。
2.  **与 Tracking (目标跟踪) 的交互**:
    *   **动态门限**: `HorizontalJudgmentisnot` 函数展示了 LCA/Tracking 模块如何根据本车大转弯 (`yaw_rate`) 动态调整跟踪门限 (`trcGateX/Y`)，以确保在剧烈机动下不丢失侧后方目标，这对 LCA 的连续性至关重要。
3.  **与 Calibration (标定) 的交互**:
    *   **坐标修正**: `postProcess.c` 中的代码显示，雷达安装角度 (`radar_yaw_angle`) 和车速系数 (`egoCarSpdCoef`) 直接影响目标坐标的解算精度。如果标定失败 (`finalCalibState` 异常)，LCA 功能可能进入 `Failure` 或 `Passive` 状态，停止报警。
4.  **与 DOW/RCW 的交互**:
    *   虽然逻辑独立，但它们共享 `adasROIStruct` 和 `adasWarningStruct`。在系统资源受限或目标密集时，跟踪算法可能需要平衡各功能的 ROI 处理优先级。