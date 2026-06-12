# FCTA 功能分析

## 1. 功能概述
**FCTA (Front Cross Traffic Alert)** 即前方交叉交通警报。该功能主要应用于车辆从停车位（如倒车出库或侧方停车出库）向前移动时，检测前方横向穿过道路的车辆或障碍物，并向驾驶员发出视觉/听觉警报，以防止碰撞。

根据源码分析，FCTA 是角雷达（Corner Radar）前端模块（FL/FR）的核心功能之一，通常与 FCTB（前方交叉交通制动）配合使用。FCTA 负责预警，FCTB 负责在紧急情况下请求制动。

## 2. 状态机
虽然提供的代码片段未直接展示完整的 `switch-case` 状态机实现，但通过参数定义和状态更新函数 `ASWIN_SystemState_UpdateFctaAndFctbSystemStatus` 以及输出逻辑，可以推断出 FCTA 的典型状态机结构：

*   **Off (关闭)**:
    *   条件: `PERInputUpdate.adasEnable.bFCTAEnable == FALSE`。
    *   行为: 不处理目标，不输出报警。
*   **Standby (待机)**:
    *   条件: 功能开启，但车速不在检测范围内，或传感器未就绪（如校准中、故障）。
    *   行为: 系统准备就绪，但不激活报警逻辑。
*   **Active (激活/检测中)**:
    *   条件:
        1.  `bFCTAEnable == TRUE`
        2.  车速在激活范围内: `fFctaActiveLowSpd (1.0 km/h) <= Speed <= fFctaActiveUpSpd (20.0 km/h)`。
        3.  无故障 (`GWM_FCTA_FaultEna() == FALSE`)。
        4.  传感器状态正常 (`g_BLDDet_SensorStatus_u8 == 0`)。
    *   行为: 开始扫描 ROI 区域，计算 TTC/TTM，判断是否触发报警。
*   **Warning (报警中)**:
    *   条件: 在 Active 状态下，检测到目标满足报警阈值（速度、角度、DDCI、TTM）。
    *   行为: 输出 `FCTA_warningReq` 信号。
*   **De-warning (取消报警)**:
    *   条件: 目标不再满足报警阈值（如目标驶离、速度过低、角度超出范围），或进入迟滞区间。
    *   行为: 清除报警信号。
*   **Failure (故障)**:
    *   条件: 传感器故障、通信故障或 DTC 激活。
    *   行为: 功能禁用，上报故障状态。

**状态转换关键点**:
*   **Standby -> Active**: 车速进入 `[1.0, 20.0] km/h` 且无故障。
*   **Active -> Standby**: 车速超过 `22.0 km/h` (`fFctaDeactiveUpSpd`) 或低于 `0.0 km/h` (`fFctaDeactiveLowSpd`)，或出现故障。
*   **Active -> Warning**: 目标满足报警逻辑。

## 3. 报警/制动逻辑

### 3.1 报警触发条件 (Warning)
当系统处于 **Active** 状态时，若检测到目标满足以下**所有**条件，则触发 FCTA 报警：

1.  **目标速度**:
    *   `ObjSpeed >= fFctaObjWarningSpd (4.0 km/h)`
    *   `ObjSpeed <= fFctaObjWarningUpSpd (70.0 km/h)`
2.  **目标角度 (Yaw Angle)**:
    *   绝对值在 `[38.0°, 127.0°]` 之间 (`fFctaObjWarningLowYawAngle` ~ `fFctaObjWarningUpYawAngle`)。这确保目标主要是横向运动。
3.  **纵向距离/碰撞风险 (DDCI - Dynamic Distance to Collision Impact)**:
    *   DDCI 在 `[0.0 m, 2.8 m]` 之间 (`fFctaObjWarningLowBaseDDCI` ~ `fFctaObjWarningUpBaseDDCI`)。
    *   结合 Offset 调整后的 DDCI 需在允许范围内。
4.  **时间指标 (TTM - Time to Maximal/Minimum)**:
    *   **X轴 (纵向)**: `TTMX <= fFctaObjWarningBaseTTMX (2.0s) + fFctaObjWarningTTMXOffSet (0.0s)`。即 TTMX <= 2.0s。
    *   **Y轴 (横向)**: `TTMY` 需在特定范围内。源码定义了 `fFctaObjWarningUpTTMY (2.5s)` 和 `fFctaObjWarningLowTTMY (0.4s)`。通常逻辑是目标即将穿过车道，TTMY 较小。

### 3.2 报警取消条件 (De-warning)
当报警激活后，若目标状态变化满足以下**任一**条件，则取消报警（具有迟滞，防止闪烁）：

1.  **目标速度**:
    *   `ObjSpeed < fFctaObjDeWarningSpd (2.2 km/h)` 或 `ObjSpeed > fFctaObjDeWarningUpSpd (73.6 km/h)`。
2.  **目标角度**:
    *   绝对值 `< 33.0°` (`fFctaObjDeWarningLowYawAngle`) 或 `> 135.0°` (`fFctaObjDeWarningUpYawAngle`)。
3.  **时间指标**:
    *   `TTMX > fFctaObjWarningBaseTTMX + fFctaObjDeWarningTTMXOffSet (2.0 + 0.3 = 2.3s)`。
    *   `TTMY > fFctaObjDeWarningUpTTMY (2.8s)`。
4.  **其他**:
    *   目标丢失或进入盲区。
    *   系统退出 Active 状态（如车速过高）。

### 3.3 与 FCTB 的交互
*   FCTA 仅负责**警报**。
*   如果危险程度进一步加剧（通常由 FCTB 逻辑判断，基于更严格的 TTM/DDCI 阈值），系统会触发 FCTB 请求制动。
*   在输出层，`g_ASWOUT_RadarWarnSigStrct.FR_Fcta_Warning` 仅当 `fctaSystemState == 3` (Active) 时才输出 `bRightFctaWarning`。

## 4. 关键阈值

| 参数名 | 值 | 单位 | 含义 |
| :--- | :--- | :--- | :--- |
| **系统激活速度** | | | |
| `fFctaActiveLowSpd` | 1.0 | km/h | 系统激活最低车速 |
| `fFctaActiveUpSpd` | 20.0 | km/h | 系统激活最高车速 |
| `fFctaDeactiveUpSpd` | 22.0 | km/h | 系统退出最高车速 (迟滞) |
| `fFctaDeactiveLowSpd` | 0.0 | km/h | 系统退出最低车速 |
| **目标检测速度** | | | |
| `fFctaObjWarningSpd` | 4.0 | km/h | 触发报警的目标最低速度 |
| `fFctaObjDeWarningSpd` | 2.2 | km/h | 取消报警的目标最低速度 |
| `fFctaObjWarningUpSpd` | 70.0 | km/h | 触发报警的目标最高速度 |
| `fFctaObjDeWarningUpSpd` | 73.6 | km/h | 取消报警的目标最高速度 |
| **目标角度 (Yaw)** | | | |
| `fFctaObjWarningLowYawAngle` | 38.0 | deg | 触发报警的最小绝对偏航角 |
| `fFctaObjWarningUpYawAngle` | 127.0 | deg | 触发报警的最大绝对偏航角 |
| `fFctaObjDeWarningLowYawAngle` | 33.0 | deg | 取消报警的最小绝对偏航角 |
| `fFctaObjDeWarningUpYawAngle` | 135.0 | deg | 取消报警的最大绝对偏航角 |
| **时间指标 (TTM)** | | | |
| `fFctaObjWarningBaseTTMX` | 2.0 | s | X轴触发报警基准 TTM |
| `fFctaObjDeWarningTTMXOffSet` | 0.3 | s | X轴取消报警 TTM 迟滞偏移 |
| `fFctaObjWarningUpTTMY` | 2.5 | s | Y轴触发报警最大 TTM |
| `fFctaObjDeWarningUpTTMY` | 2.8 | s | Y轴取消报警最大 TTM |
| `fFctaObjWarningLowTTMY` | 0.4 | s | Y轴触发报警最小 TTM |
| **距离指标 (DDCI)** | | | |
| `fFctaObjWarningLowBaseDDCI` | 0.0 | m | 触发报警最小基础 DDCI |
| `fFctaObjWarningUpBaseDDCI` | 2.8 | m | 触发报警最大基础 DDCI |

## 5. 关键变量

| 变量名 | 类型 | 来源 | 含义 |
| :--- | :--- | :--- | :--- |
| `bFCTAEnable` | bool | `PERInputUpdate.adasEnable` | FCTA 功能使能标志，由用户开关或配置决定 |
| `fFctaActiveUpSpd` | float | `adasFunc.c` | 系统激活上限速度阈值 |
| `fFctaActiveLowSpd` | float | `adasFunc.c` | 系统激活下限速度阈值 |
| `fFctaObjWarningSpd` | float | `adasFunc.c` | 目标触发报警的速度阈值 |
| `fFctaObjWarningLowYawAngle` | float | `adasFunc.c` | 目标触发报警的最小偏航角 |
| `fFctaObjWarningBaseTTMX` | float | `adasFunc.c` | 目标触发报警的 X 轴 TTM 阈值 |
| `fFctaRoiOffSetY` | float | `adasFunc.c` | FCTA 感兴趣区域 (ROI) 的 Y 轴偏移量，用于定义检测区域 |
| `bRightFctaWarning` | bool | `PEROutput.adasWarning` | 右侧 FCTA 报警请求标志 |
| `bLeftFctaWarning` | bool | `PEROutput.adasWarning` | 左侧 FCTA 报警请求标志 |
| `fctaSystemState` | uint8 | `PEROutput.adasWarning` | FCTA 系统当前状态 (0:Off, 1:Standby, 2:Init, 3:Active, etc.) |
| `FCTA_warningReqLeft` | uint8 | `RteComMapping_RLWarnSigStrct_t` | 发送给网关/仪表的左侧 FCTA 报警请求信号 |

## 6. 输入信号

1.  **车辆状态**:
    *   `Vehicle Speed`: 当前车速，用于判断系统激活/退出。
    *   `Gear`: 档位（虽然 FCTA 主要看速度，但通常与 R 档或 N 档起步相关，源码中未直接显示 Gear 对 FCTA 的限制，但 FCTB 逻辑中可能有）。
    *   `Steering Wheel Angle`: 可能用于辅助判断车辆运动趋势（源码中 `StWhAng` 存在，但未直接在 FCTA 参数中体现，可能在感知层融合）。
2.  **用户配置**:
    *   `FCTASwtReq` / `FCTABrkSwtReq`: 来自 HMI 的 FCTA/FCTB 开关请求。
    *   `Variant Config`: 车型配置，决定 FCTA 是否默认开启。
3.  **传感器数据**:
    *   `Object List`: 来自雷达感知层的目标列表，包含距离、速度、角度、TTM、DDCI 等。
    *   `Sensor Status`: 传感器健康状态、校准状态 (`inCalibState`)。
4.  **故障状态**:
    *   `DTC Status`: 相关故障码状态，用于判断是否进入 Failure 状态。

## 7. 输出信号

1.  **报警请求**:
    *   `FCTA_warningReqLeft` / `FCTA_warningReqRight`: 发送给网关或仪表的报警信号，用于触发声音或灯光提示。
    *   `FR_Fcta_Warning` / `FL_Fcta_Warning`: 雷达控制器内部输出的报警标志，映射到 CAN 信号 `RSDS_FCTA_Warning` (推测)。
2.  **系统状态**:
    *   `FCTAState`: 系统当前状态机状态，用于诊断或监控。
3.  **故障信息**:
    *   `FR_Fault_Err` / `FL_Fault_Err`: 雷达故障状态。
    *   `FR_Blind_Sts` / `FL_Blind_Sts`: 雷达盲区/遮挡状态。

## 8. 与其他功能的交互

1.  **FCTB (Front Cross Traffic Braking)**:
    *   **紧密耦合**: FCTA 和 FCTB 共享大部分感知数据和系统状态机。
    *   **逻辑递进**: FCTA 是预警，FCTB 是制动。通常 FCTB 的触发阈值比 FCTA 更严格（更短的 TTM，更小的 DDCI）。
    *   **开关联动**: 在 `RteComMapping.c` 中可以看到，FCTA 和 FCTB 的开关逻辑是联动的。如果 FCTA 关闭，FCTB 通常也会被关闭或受限。
2.  **BSD/LCA/DOW/RCW/RCTA**:
    *   **独立但共存**: 这些是其他角雷达功能。FCTA 主要关注**前方**横向交通，而 BSD/LCA 关注**侧方**，RCTA 关注**后方**。
    *   **资源竞争**: 它们共享雷达硬件资源。在 `AswIfSchedule.c` 中，前雷达（FL/FR）和后雷达（RL/RR）的状态更新是分开的。FCTA 由前雷达处理。
3.  **网关 (Gateway)**:
    *   FCTA 的报警信号通过 `RteComMapping` 映射到 CAN 总线，发送给网关，再由网关转发给仪表、HUD 或声音报警模块。
4.  **制动系统 (ESP/VCU)**:
    *   FCTA **不直接**请求制动。如果发生碰撞风险，由 FCTB 功能通过 `RSDS_BrkgReq` 信号请求 ESP 进行制动。FCTA 仅作为驾驶员辅助。