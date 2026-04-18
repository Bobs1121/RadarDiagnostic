# RCTB 功能分析

## 1. 功能概述
**RCTB (Rear Cross Traffic Braking)** 即后方交叉交通制动功能。该功能在车辆倒车时（通常处于 R 档），利用角雷达监测车辆后方横向移动的交通参与者（如车辆、行人）。当检测到存在碰撞风险且驾驶员未采取制动措施时，系统会先发出警报（通常与 RCTA 联动），若风险进一步升级，则自动请求 ESP/ABS 系统进行制动干预，以防止或减轻碰撞。

从代码分析来看，RCTB 是 RCTA 的延伸功能，两者共享部分状态机和检测逻辑，但 RCTB 增加了制动请求（Brake Request）和制动保持（Hold）逻辑。

## 2. 状态机
根据 `adasFunc.c` (L780) 和 `ASWIN_SystemState.h` (L52) 的定义，RCTB 系统状态机包含以下状态：

| 状态值 | 状态名称 | 含义 |
| :--- | :--- | :--- |
| 0 | **None** | 未初始化/未定义 |
| 1 | **Init** | 初始化中 |
| 2 | **Standby** | 待机/就绪 (Ready)，系统自检通过，等待激活条件 |
| 3 | **Active** | 激活 (Active)，功能正在运行，可检测并触发报警/制动 |
| 4 | **Off** | 关闭 (Off)，功能被用户关闭或配置禁用 |
| 5 | **Failure** | 故障 (Failure)，传感器或系统内部故障 |
| 6 | **Passive** | 被动/降级 (Passive)，部分功能受限 |

**状态转换逻辑推断：**
*   **Standby -> Active**: 当车速在激活范围内 (`fRctbActiveLowSpd` ~ `fRctbActiveUpSpd`，即 0-9 km/h)，且档位为 R 档，功能开关开启 (`bRCTBEnable`)，且无故障时。
*   **Active -> Standby/Off**: 当车速超过 `fRctbDeactiveUpSpd` (10 km/h) 或低于 `fRctbDeactiveLowSpd` (0 km/h)，或驾驶员踩下刹车/油门超过阈值，或功能被禁用。
*   **Active -> Failure**: 当雷达信号丢失、通信故障或系统诊断报错时。
*   **制动保持逻辑 (Hold)**: 在 `Active` 状态下触发制动后，系统进入制动保持阶段。若满足 `RCTBHoldThree` (3秒) 或驾驶员干预（踩油门、急打方向等），则结束制动保持。

## 3. 报警/制动逻辑

### 3.1 报警触发 (Warning)
虽然 RCTB 主要关注制动，但其报警逻辑通常与 RCTA 共享或作为前置条件。
*   **触发条件**:
    1.  系统状态为 `Active`。
    2.  检测到目标物体位于后方交叉区域。
    3.  **TTM (Time To Merge/Impact)** 小于警告阈值 `fRctbObjWarningTTM` (1.6s)。
    4.  **DDCI (Distance to Collision Intersection)** 满足条件：`DDCI < fRctbObjWarningLowerDDCIOffSet` (-2.0m)。
    5.  **C-DDCI** 满足条件：`C-DDCI < fRctbObjWarningLowerCDDCIOffSet` (-4.0m)。
*   **报警保持**: 使用 `bRctbLeftKeepFlag` / `bRctbRightKeepFlag` 及缓冲区 `bRctbLeftBuffer` 进行报警状态的平滑处理，防止抖动。

### 3.2 制动触发 (Braking)
*   **触发条件**:
    1.  报警条件已满足（或 TTM 进一步恶化）。
    2.  **AEB 激活阈值**: 碰撞风险达到 `fRctbAEBActiveThresh` (1.0s，推测为 TTM 或 TTC 的临界值)。
    3.  驾驶员未进行有效的制动或转向规避操作。
*   **制动请求值**:
    *   标准制动请求：`fRctbBrakeValue` (-4.0 m/s²)。
    *   高速制动请求：`fRctbHighSpeedBrakeValue` (-6.0 m/s²)。
    *   保持制动请求：`fRctbHoldValue` (-2.0 m/s²)。

### 3.3 取消报警/制动 (De-warning/De-braking)
*   **取消报警**:
    *   TTM 大于去报警阈值 `fRctbObjDeWarningTTM` (2.0s)。
    *   目标物体离开检测区域。
    *   系统状态退出 `Active`。
*   **取消制动 (Hold Finish)**:
    根据 `ASWIN_SystemState.c` (L166-L176) 的 `RctbSetHoldfinish` 函数，制动保持结束条件（满足任一即可）：
    1.  功能被禁用 (`bRCTBEnable == 0`)。
    2.  驾驶员踩下刹车踏板持续时间超过阈值 (`Check_Brake_Pedal_Pressed_Duration`)。
    3.  系统故障 (`GWM_RCTB_FaultEna`)。
    4.  驾驶员深踩油门 (`AdasStM.AccPedPosDiag >= 5`)。
    5.  方向盘转动过快 (`AdasStM.SteerWheelSpd > 100`)。
    6.  制动保持时间达到 `RCTB_HOLD` (3000ms)。
    7.  方向盘转角过大 (`StWhAng() > 90` 度)。
    8.  车速极低 (< 0.7 km/h) 且满足上述任一条件。

## 4. 关键阈值

| 参数名称 | 变量名 | 值 | 单位 | 说明 |
| :--- | :--- | :--- | :--- | :--- |
| **系统激活上限速度** | `fRctbActiveUpSpd` | 9.0 | km/h | 倒车速度超过此值功能退出 Active |
| **系统激活下限速度** | `fRctbActiveLowSpd` | 0.0 | km/h | |
| **系统退出上限速度** | `fRctbDeactiveUpSpd` | 10.0 | km/h | 滞回区间，防止在 9-10km/h 频繁跳变 |
| **检测下限速度** | `fRctbDetectLowSpd` | 0.7 | km/h | 低于此速度可能停止检测或进入保持结束逻辑 |
| **检测上限速度** | `fRctbDetectUpSpd` | 9.0 | km/h | |
| **警告 TTM** | `fRctbObjWarningTTM` | 1.6 | s | 时间到碰撞/交汇，触发报警 |
| **去报警 TTM** | `fRctbObjDeWarningTTM` | 2.0 | s | 时间大于此值，取消报警 |
| **警告 DDCI 偏移** | `fRctbObjWarningLowerDDCIOffSet` | -2.0 | m | 距离碰撞点纵向距离阈值 |
| **警告 C-DDCI 偏移** | `fRctbObjWarningLowerCDDCIOffSet` | -4.0 | m | 距离碰撞点横向/综合距离阈值 |
| **AEB 激活阈值** | `fRctbAEBActiveThresh` | 1.0 | s | 触发自动制动的临界时间 |
| **标准制动减速度** | `fRctbBrakeValue` | -4.0 | m/s² | 常规制动请求 |
| **高速制动减速度** | `fRctbHighSpeedBrakeValue` | -6.0 | m/s² | 高风险制动请求 |
| **保持制动减速度** | `fRctbHoldValue` | -2.0 | m/s² | 车辆停止后的保持力 |
| **停止速度阈值** | `fRctbStopSpd` | 1.0 | km/h | 判定车辆停止的速度 |
| **制动保持时长** | `RCTB_HOLD` | 3000 | ms | 自动制动保持的最大持续时间 |
| **功能间隔** | `RCTB_FUNC_GAP` | 10000 | ms | 两次触发之间的冷却时间 |

## 5. 关键变量

| 变量名 | 类型 | 来源 | 含义 |
| :--- | :--- | :--- | :--- |
| `rctbSystemState` | `uint8_t` | `adasFunc.c` | RCTB 系统当前状态机状态 (0-6) |
| `bRctbDetectFlg` | `bool` | `adasFunc.c` | 是否检测到有效威胁目标 |
| `bRctbLeftWarningFlg` | `bool` | `adasFunc.c` | 左侧是否触发报警/制动 |
| `bRctbRightWarningFlg` | `bool` | `adasFunc.c` | 右侧是否触发报警/制动 |
| `bRctbKeepBrakeFlg` | `bool` | `adasFunc.c` | 制动保持标志位，用于维持制动请求 |
| `fRctbBrakeReqVal` | `float` | `adasFunc.c` | 当前输出的制动请求减速度值 |
| `fRctbBrakeEventTime` | `float` | `adasFunc.c` | 制动事件开始的时间戳 |
| `fRctbHoldEventTime` | `float` | `adasFunc.c` | 制动保持阶段开始的时间戳 |
| `bRCTBEnable` | `bool` | `RteComMapping.c` | RCTB 功能使能开关 (用户配置/开关) |
| `rctbTimerActive` | `bool` | `ASWIN_SystemState.c` | 制动保持计时器激活标志 |
| `AdasStM.RCTBState` | `uint8_t` | `ASWIN_SystemState.c` | 全局 ADAS 状态机中的 RCTB 状态副本 |

## 6. 输入信号

1.  **雷达感知数据**:
    *   目标列表 (Object List): 包含距离 (Range)、相对速度 (RelVel)、方位角 (Azimuth)、TTC/TTM 计算值。
    *   目标属性: 类型 (车辆/行人)、尺寸 (Width/Length)。
2.  **车辆状态信号**:
    *   `carSpd`: 自车速度 (km/h)。
    *   `actual_gear`: 当前档位 (需为 R 档)。
    *   `SteerWheelAng`: 方向盘转角。
    *   `SteerWheelSpd`: 方向盘转角速度。
    *   `AccPedPosDiag`: 油门踏板位置/开度。
    *   `BrkPedalSts`: 刹车踏板状态。
3.  **功能配置与开关**:
    *   `bRCTBEnable`: 用户通过 UI 或配置开启/关闭 RCTB。
    *   `RCTABrkSwtReq`: 制动功能开关请求信号。
4.  **系统状态**:
    *   传感器故障状态 (DTC)。
    *   系统初始化状态。

## 7. 输出信号

1.  **制动请求**:
    *   `RSDS_BrkgReq` / `RSDS_BrkgReqVal`: 发送给 ESP/ABS 的制动请求标志及减速度值 (m/s²)。
    *   `RSDS_RCWResp`: 响应信号。
2.  **报警指示**:
    *   `RR_Rctb_Warning` / `RL_Rctb_Warning`: 发送给仪表盘或 HUD 的报警状态 (通常与 RCTA 报警共用或分级显示)。
    *   `RCTABrkResp`: 制动功能响应信号 (告知 HMI 制动已激活)。
3.  **状态指示**:
    *   `RCTBState`: 系统当前状态 (Active, Standby, Failure 等)。
    *   `Fault_Err`: 故障状态码。
    *   `SDASts`: 系统诊断/激活状态。

## 8. 与其他功能的交互

*   **与 RCTA (Rear Cross Traffic Alert) 的交互**:
    *   **逻辑依赖**: RCTB 通常依赖于 RCTA 的检测逻辑。代码中 `bRctaLeftWarningFlg` 和 `bRctaRightWarningFlg` 与 RCTB 的报警标志紧密相关。RCTA 负责报警，RCTB 在报警基础上增加制动。
    *   **开关联动**: 在 `RteComMapping.c` 中，如果 RCTA 被禁用 (`bRCTAEnable == 0`)，RCTB 通常也会被强制关闭 (`bRCTBEnable = FALSE`)，因为制动功能依赖于准确的交叉交通检测。
*   **与 ESP/ABS 的交互**:
    *   RCTB 通过 `RteComMapping` 输出制动请求值 (`fBrakeValue`) 给底盘控制单元。
    *   接收底盘的反馈信号（如实际减速度、刹车踏板状态）以判断是否取消制动。
*   **与 DOW (Door Open Warning) 的交互**:
    *   两者都涉及后方安全，但在逻辑上是独立的。DOW 关注开门瞬间，RCTB 关注倒车过程中的横向交通。
*   **与 BSD/LCA 的交互**:
    *   共享角雷达的原始感知数据（目标跟踪列表）。
    *   共享部分系统状态机架构（Standby/Active/Failure）。
*   **与 HMI (人机交互) 的交互**:
    *   通过 `RCTABrkResp` 和 `RCTAWarning` 信号控制仪表盘图标闪烁、声音报警或语音提示。
    *   通过 `bRCTBEnable` 读取用户开关状态。