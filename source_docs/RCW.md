# RCW 功能分析

## 1. 功能概述
**RCW (Rear Cross Traffic Warning)** 即后方交叉交通预警功能。该功能主要利用车辆后方的角雷达（Corner Radar）监测车辆后方横向或斜向移动的物体（如车辆、行人）。当系统检测到有碰撞风险的物体进入预设的 ROI（感兴趣区域）且满足特定的速度、角度及 TTC（碰撞时间）条件时，系统会向驾驶员发出声光报警，提示后方有来车，防止在倒车或低速行驶中发生碰撞。

根据代码分析，该功能主要运行在后方雷达（RR/RL）控制器中，通过公共 CAN 总线发送报警信号。

## 2. 状态机
虽然源码片段未直接展示 `switch-case` 状态机代码，但根据 `adasFunc.h` 中的注释定义及 `ASWIN_SystemState.c` 中的逻辑，RCW 系统状态遵循标准 ADAS 状态机定义：

*   **状态定义 (uint8_t rcwSystemState)**:
    *   `0`: **None** (未初始化/未定义)
    *   `1`: **Init** (初始化中)
    *   `2`: **Standby** (待机/Ready，系统已激活但未满足触发条件)
    *   `3`: **Active** (激活，功能正常且可能正在报警)
    *   `4`: **Off** (关闭，用户开关关闭或功能不可用)
    *   `5`: **Failure** (故障，传感器或系统报错)
    *   `6`: **Passive** (被动模式，如拖车模式 Trailer Mode)

*   **状态转换逻辑推断**:
    *   **Standby -> Active**: 车辆速度在激活范围内 (`fRcwActiveSpd` 至 `fRcwActiveUpperSpd`)，且曲率半径满足条件 (`fRcwActiveCurbRadius`)，无系统故障。
    *   **Active -> Off**: 车速超出上限 (`fRcwDeactiveUpperSpd`) 或低于下限，或用户关闭开关 (`RCWSwtReq` = 0)。
    *   **Active -> Passive**: 检测到拖车模式 (`TrailerSts` = 1)。
    *   **Active -> Failure**: 检测到雷达故障或通信错误 (`ErrSts` = TRUE)。

## 3. 报警/制动逻辑

### 报警触发条件 (Warning Trigger)
系统需同时满足以下条件才会触发报警 (`bRcwWarning > 0`)：
1.  **系统状态**: `rcwSystemState` 为 `Active` (3)。
2.  **目标筛选**:
    *   目标位于 RCW ROI 区域内（由 `LineRCWA` 到 `LineRCWB` 的纵向距离，及 `LineRCWC` 到 `LineRCWD` 的横向宽度定义）。
    *   **速度**: 目标相对速度或绝对速度在阈值范围内 (`fRcwObjWarningSpd` ~ `fRcwObjWarningUpSpd`)。
    *   **角度**: 目标绝对航向角 (Yaw Angle) 小于 `fRcwObjWarningYawAngle` (30 度)，确保是横向或斜向接近。
    *   **TTC (Time To Collision)**: 碰撞时间小于 `fRcwObjWarningTTC` (1.4s)。
    *   **减速度**: 目标减速度小于 `fRcwObjWarningDeAcc` (2.0 m/s²)，排除正在急刹车的目标。
    *   **重叠率**: 目标与自车预测路径的重叠率大于 `fRcwObjWarningRatio` (0.85)。
3.  **报警持续时间**:
    *   一旦触发，报警信号需持续至少 `RCW_MIN_DURATION_MS` (800ms)。
    *   若持续报警超过 `RCW_DELAY_TIME` (2900ms)，可能触发更高级别的逻辑或进入特定保持状态 (`isOverThreshold`)。

### 报警取消条件 (De-warning)
满足以下任一条件，报警解除：
1.  **TTC 恢复**: 目标 TTC 大于 `fRcwObjDeWarningTTC` (1.7s)。
2.  **速度变化**: 目标速度低于 `fRcwObjDeWarningSpd` (9.0 km/h) 或高于 `fRcwObjDeWarningUpSpd` (73.8 km/h)。
3.  **角度变化**: 目标航向角大于 `fRcwObjDeWarningYawAngle` (35 度)。
4.  **位置离开**: 目标移出 ROI 区域（考虑了 `fRcwObjDeWarningTopOffSetX` 等偏移量，防止抖动）。
5.  **重叠率降低**: 重叠率小于 `fRcwObjDeWarningRatio` (0.65)。
6.  **系统状态**: 系统进入 Off, Failure 或 Passive 状态。

### 制动逻辑
*   **RCW 仅支持报警 (Warning)**：根据代码 `RteComMapping_RLWarnSigStrct` 定义，RCW 输出信号为 `RSDS_RCW_Trigger` (0:无报警, 1:Level1, 2:Level2)。
*   **无主动制动**: 代码中未包含 RCW 触发自动制动 (`RSDS_BrkgReq`) 的逻辑。制动请求通常由 RCTB (Rear Cross Traffic Braking) 功能负责。

## 4. 关键阈值

| 参数名称 | 变量名 | 数值 | 单位 | 说明 |
| :--- | :--- | :--- | :--- :--- |
| **系统激活车速** | `fRcwActiveSpd` | 120.0 | km/h | 系统激活的上限速度（通常指功能可用上限，实际触发可能更低，此处配置较高可能为全局限制） |
| **系统去激活车速** | `fRcwDeactiveSpd` | 125.0 | km/h | 系统关闭的速度阈值 |
| **系统激活曲率半径** | `fRcwActiveCurbRadius` | 175.0 | m | 车辆转弯半径阈值，防止急弯误报 |
| **目标报警速度下限** | `fRcwObjWarningSpd` | 10.8 | km/h | 目标相对速度低于此值不报警 |
| **目标报警速度上限** | `fRcwObjWarningUpSpd` | 72.0 | km/h | 目标相对速度高于此值不报警 |
| **目标去报警速度** | `fRcwObjDeWarningSpd` | 9.0 | km/h | 目标速度低于此值取消报警 |
| **目标报警 TTC** | `fRcwObjWarningTTC` | 1.4 | s | 碰撞时间小于此值触发报警 |
| **目标去报警 TTC** | `fRcwObjDeWarningTTC` | 1.7 | s | 碰撞时间大于此值取消报警 |
| **目标报警航向角** | `fRcwObjWarningYawAngle` | 30.0 | deg | 目标绝对航向角阈值 |
| **目标去报警航向角** | `fRcwObjDeWarningYawAngle` | 35.0 | deg | 目标绝对航向角阈值 |
| **目标报警减速度** | `fRcwObjWarningDeAcc` | 2.0 | m/s² | 目标减速度阈值 |
| **目标报警重叠率** | `fRcwObjWarningRatio` | 0.85 | - | 目标与自车路径重叠比例 |
| **报警最小持续时间** | `RCW_MIN_DURATION_MS` | 800 | ms | 报警信号保持的最小时间 |
| **报警最大持续时间** | `RCW_MAX_DURATION_MS` | 2900 | ms | 报警信号保持的最大时间阈值 |

## 5. 关键变量

| 变量名 | 类型 | 来源 | 含义 |
| :--- | :--- | :--- | :--- |
| `rcwSystemState` | `uint8_t` | `adasFunc.c` / `ASWIN_SystemState.c` | RCW 系统当前状态机状态 (0-6) |
| `bRcwWarning` | `uint8_t` / `bool` | `PEROutput.adasWarning` | RCW 报警标志位 (0:无, 1:Level1, 2:Level2) |
| `inAlarmPeriod_rcw` | `boolean` | `ASWIN_SystemState.c` | 标记当前是否处于 RCW 报警周期内 |
| `isActive_rcw` | `boolean` | `ASWIN_SystemState.c` | 标记 RCW 功能是否处于激活状态 |
| `isOverThreshold` | `boolean` | `ASWIN_SystemState.c` | 标记报警是否超过 2900ms 阈值 |
| `PERInputUpdate.adasEnable.bRCWEnable` | `bool` | `RteComMapping.c` | 用户开关请求信号 (RCWSwtReq) |
| `g_RteComMapping_RLWarnSig.RSDS_RCW_Trigger` | `uint8_t` | `RteComMapping.c` | 发送给 CAN 总线的 RCW 触发信号 |
| `LineRCWA`, `LineRCWB` | `float` | `adasFunc.c` | RCW 感兴趣区域 (ROI) 的纵向边界坐标 |
| `LineRCWC`, `LineRCWD` | `float` | `adasFunc.c` | RCW 感兴趣区域 (ROI) 的横向边界坐标 |

## 6. 输入信号
RCW 功能依赖以下输入信号进行决策：

1.  **车辆状态信号**:
    *   `VehcleInfoUpdate.actual_gear`: 档位信息 (通常 RCW 在 R 档或低速 D 档工作)。
    *   `VehcleInfoUpdate.speed`: 自车速度。
    *   `SteeringAngle`: 方向盘角度 (用于计算曲率半径)。
    *   `YawRate`: 横摆角速度。
2.  **感知对象数据 (Perception Objects)**:
    *   `ObjectList`: 包含后方检测到的所有目标的距离、速度、角度、ID 等。
3.  **用户/系统配置**:
    *   `RCWSwtReq`: 用户开关请求 (来自 `RteComMapping_ReadSignal`)。
    *   `TrailerSts`: 拖车模式状态 (来自 `g_GWMSpecificVariant` 或 `AdasStM`)。
    *   `Fault_Err`: 系统故障标志。
4.  **时间戳**:
    *   用于计算 TTC 和报警持续时间 (`activeStartTime`, `elapsed_time`)。

## 7. 输出信号
RCW 功能通过 CAN 总线输出以下信号：

1.  **报警信号**:
    *   `RSDS_RCW_Trigger` (via `g_ASWOUT_RadarWarnSigStrct.Rcw_Warning`):
        *   `0`: 无报警
        *   `1`: RCW Level 1 (初级报警，如单声提示)
        *   `2`: RCW Level 2 (严重报警，如连续提示或双声)
    *   该信号由 `RteComMapping_GetRL_RSDS_RCW_Trigger_GWM()` 获取并写入 CAN 报文。
2.  **系统状态信号**:
    *   `RSDS_RCWResp`: 功能响应状态 (Enable/Disable)。
    *   `RCWState`: 系统状态机当前值 (0-6)，用于仪表盘显示。
3.  **故障信号**:
    *   `Fault_Err`: 故障标志位，若系统故障则置位。

## 8. 与其他功能的交互

*   **与 RCTA/RCTB 的交互**:
    *   **互斥/优先级**: RCW 和 RCTA/RCTB 都监测后方交叉交通。通常 RCTA/RCTB 在倒车 (R 档) 且速度极低时工作，而 RCW 可能在更宽的速度范围或特定场景下工作。代码中 `RCTSDIDMerge` 逻辑显示 RCTA/RCTB 的开关可能与 RCW 独立或合并配置。
    *   **信号协调**: 在 `ASWOUT_OutCalc.c` 中，`Rcw_Warning` 信号是独立计算的，但与其他报警信号（如 BSD, LCA）在同一 CAN 报文结构体中传输。
*   **与 BSD/LCA 的交互**:
    *   **ROI 重叠**: BSD 和 LCA 监测侧后方，RCW 监测正后方交叉区域。ROI 定义 (`LineRCW...`) 与 BSD/LCA 的 ROI 可能有重叠，但在逻辑上通过角度和速度阈值进行区分。
    *   **报警仲裁**: 在 `RE_ASWOUT_OutCalc_RadarWarnSignal` 中，如果 BSD 和 LCA 同时报警，系统会取优先级较高的报警值 (`bRightBsdWarning` vs `bRightLcaWarning`)。RCW 报警逻辑相对独立，但在输出时若与其他功能冲突，需遵循特定的仲裁策略（代码中 RCW 似乎直接输出，未显示与 BSD 的复杂仲裁，但 `Rcw_Warning` 变量本身可能包含内部仲裁结果）。
*   **与 DOW (开门预警) 的交互**:
    *   两者都监测后方物体，但 DOW 关注的是开门瞬间的碰撞风险，RCW 关注的是行驶中的交叉风险。代码中 `DOW` 和 `RCW` 的参数定义是分开的，状态机也是独立的。
*   **拖车模式 (Trailer Mode)**:
    *   当 `TrailerSts` 为 1 时，RCW 状态机强制进入 `Passive` (6) 状态，停止报警，防止拖车时误报。