# RCTA 功能分析

## 1. 功能概述
**RCTA (Rear Cross Traffic Alert)** 即后方交叉交通警报功能。该功能主要利用车辆后角雷达（Corner Radar）监测车辆后方两侧（左侧和右侧）的交通状况。当车辆处于倒车状态（通常挂入 R 挡）且车速较低时，若检测到有横向车辆或障碍物从后方接近，且存在碰撞风险，系统将触发声光报警（Warning），提醒驾驶员注意避让。

根据代码片段，RCTA 与 RCTB (Rear Cross Traffic Braking) 共享部分系统状态机逻辑，但 RCTA 侧重于警报，而 RCTB 在更紧急情况下可能触发制动。代码中明确区分了 RCTA 的激活速度、检测角度、时间阈值（TTM）以及报警/消警的迟滞逻辑。

## 2. 状态机
根据 `adasFunc.h` 和 `ASWIN_SystemState.c` 中的定义，RCTA 系统状态机包含以下状态（`uint8_t rctaSystemState`）：

*   **0 - None**: 未初始化或功能未启用。
*   **1 - Init**: 初始化状态，系统正在加载参数或自检。
*   **2 - Standby (Ready)**: 待机状态。系统功能正常，但当前条件（如车速、挡位）不满足激活条件，随时准备进入 Active。
*   **3 - Active**: 激活状态。系统满足所有激活条件（如 R 挡、车速 < 15km/h），正在实时监测目标并可能触发报警。
*   **4 - Off**: 功能关闭。用户通过开关关闭或系统逻辑强制关闭。
*   **5 - Failure**: 故障状态。检测到传感器故障、通信错误或 DTC 激活。
*   **6 - Passive**: 被动/抑制状态。系统功能正常，但因外部条件（如牵引模式、ESP 激活、车门打开等）暂时抑制报警或制动输出。

**状态转换关键逻辑：**
*   **Standby -> Active**:
    *   车速满足条件：`fRctaActiveLowSpd` (0.0 km/h) <= `VehSpd` <= `fRctaActiveUpSpd` (15.0 km/h)。
    *   无故障：`GWM_RCTA_FaultEna() == 0`。
    *   无抑制条件：ESP 未激活 (`ESPFUN == 0`)，无牵引模式 (`TrailerSts == 0`)，车门关闭等。
*   **Active -> Standby**:
    *   车速超出范围：`VehSpd` > `fRctaDeactiveUpSpd` (17.0 km/h)。
    *   检测到故障或抑制条件触发。
*   **Active/Standby -> Failure**:
    *   `CheckAnyDtcActive()` 返回真，或传感器数据无效。
*   **Active -> Passive**:
    *   在牵引模式 (`TrailerSts == 1`) 下，系统状态可能进入 Passive 以抑制报警（见 `DIDTrailerSts` 函数）。

## 3. 报警/制动逻辑

### 3.1 报警触发条件 (Warning)
当系统处于 **Active** 状态时，若检测到目标满足以下所有条件，触发 RCTA 报警：
1.  **目标速度**: `fRctaObjWarningSpd` (0.0 km/h) <= `ObjSpd` <= `fRctaObjWarningUpSpd` (200.0 km/h)。
2.  **目标角度 (Yaw Angle)**: 目标相对于自车的绝对偏航角在 `fRctaObjWarningLowYawAngle` (45.0°) 到 `fRctaObjWarningUpYawAngle` (135.0°) 之间。这确保了目标是从侧后方横向接近。
3.  **距离/碰撞时间 (TTM)**: 目标到达自车路径的时间 `TTM` <= `fRctaObjWarningTTM` (4.2s)。
4.  **横向距离 (DDCI/C-DDCI)**:
    *   目标预测的横向距离偏移量需满足：
        *   `fRctaObjWarningLowerCDDCIOffSet` (0.0m) <= `C-DDCI` <= `fRctaObjWarningUpCDDCIOffSet` (0.0m)。
        *   `fRctaObjWarningLowerDDCIOffSet` (-0.0m) <= `DDCI` <= `fRctaObjWarningUpDDCIOffSet` (2.0m)。
    *   注：代码中 C-DDCI 和 DDCI 的阈值设置非常严格（接近 0），表明系统只报警那些预测轨迹与自车路径有显著重叠的目标。
5.  **ROI (Region of Interest)**: 目标需位于 RCTA 的感兴趣区域内（Y 轴偏移 `fRctaRoiOffSetY` = 0.3m）。

### 3.2 报警取消条件 (De-warning)
为防止报警闪烁，采用迟滞逻辑（Hysteresis）：
1.  **目标速度**: `ObjSpd` < `fRctaObjDeWarningSpd` (0.0 km/h) 或 `ObjSpd` > `fRctaObjDeWarningUpSpd` (200.0 km/h)。
2.  **目标角度**: 绝对偏航角 < `fRctaObjDeWarningLowYawAngle` (43.0°) 或 > `fRctaObjDeWarningUpYawAngle` (137.0°)。
    *   *分析*: 消警角度范围比报警范围更宽（43-137 vs 45-135），增加了稳定性。
3.  **TTM**: `TTM` > `fRctaObjDeWarningTTM` (5.2s)。
    *   *分析*: 消警时间阈值比报警阈值大 1.0s，提供缓冲。
4.  **横向距离**:
    *   `C-DDCI` < `fRctaObjDeWarningLowerCDDCIOffSet` (-0.5m) 或 > `fRctaObjDeWarningUpCDDCIOffSet` (0.5m)。
    *   `DDCI` < `fRctaObjDeWarningLowerDDCIOffSet` (-1.5m) 或 > `fRctaObjDeWarningUpDDCIOffSet` (3.5m)。
    *   *分析*: 消警的横向距离容差比报警大得多，意味着目标稍微偏离路径即可停止报警。

### 3.3 制动逻辑 (RCTB 关联)
虽然主要分析 RCTA，但代码显示 RCTA 和 RCTB 共享开关逻辑（`RCTASwtReq` 和 `RCTABrkSwtReq`）。若 RCTB 功能开启且满足更严格的制动阈值（如更短的 TTM 或更近的距离），系统会输出制动请求 (`RSDS_BrkgReq`)。RCTA 本身通常仅输出警告信号 (`RCTA_warningReqLeft/Right`)。

## 4. 关键阈值

| 参数名称 | 变量名 | 值 | 单位 | 说明 |
| :--- | :--- | :--- | :--- :--- |
| **系统激活上限速度** | `fRctaActiveUpSpd` | 15.0 | km/h | 车速低于此值且大于下限才激活 |
| **系统激活下限速度** | `fRctaActiveLowSpd` | 0.0 | km/h | |
| **系统去激活上限速度** | `fRctaDeactiveUpSpd` | 17.0 | km/h | 车速高于此值退出 Active 状态 (迟滞) |
| **报警目标速度上限** | `fRctaObjWarningUpSpd` | 200.0 | km/h | 目标速度阈值 |
| **报警偏航角下限** | `fRctaObjWarningLowYawAngle` | 45.0 | degree | 目标角度范围 (侧后方) |
| **报警偏航角上限** | `fRctaObjWarningUpYawAngle` | 135.0 | degree | |
| **消警偏航角下限** | `fRctaObjDeWarningLowYawAngle` | 43.0 | degree | 迟滞范围 |
| **消警偏航角上限** | `fRctaObjDeWarningUpYawAngle` | 137.0 | degree | |
| **报警 TTM (Time to Merge)** | `fRctaObjWarningTTM` | 4.2 | s | 碰撞时间阈值 |
| **消警 TTM** | `fRctaObjDeWarningTTM` | 5.2 | s | 迟滞阈值 |
| **报警 C-DDCI 偏移** | `fRctaObjWarningLowerCDDCIOffSet` | 0.0 | m | 横向距离预测偏移 (报警) |
| **报警 C-DDCI 偏移** | `fRctaObjWarningUpCDDCIOffSet` | 0.0 | m | |
| **消警 C-DDCI 偏移** | `fRctaObjDeWarningLowerCDDCIOffSet` | -0.5 | m | 横向距离预测偏移 (消警) |
| **消警 C-DDCI 偏移** | `fRctaObjDeWarningUpCDDCIOffSet` | 0.5 | m | |
| **报警 DDCI 偏移** | `fRctaObjWarningLowerDDCIOffSet` | 0.0 | m | 当前横向距离偏移 (报警) |
| **报警 DDCI 偏移** | `fRctaObjWarningUpDDCIOffSet` | 2.0 | m | |
| **消警 DDCI 偏移** | `fRctaObjDeWarningLowerDDCIOffSet` | -1.5 | m | 当前横向距离偏移 (消警) |
| **消警 DDCI 偏移** | `fRctaObjDeWarningUpDDCIOffSet` | 3.5 | m | |
| **ROI Y 轴偏移** | `fRctaRoiOffSetY` | 0.3 | m | 感兴趣区域纵向偏移 |

## 5. 关键变量

| 变量名 | 类型 | 来源 | 含义 |
| :--- | :--- | :--- | :--- |
| `rctaSystemState` | `uint8_t` | `adasFunc.c` / `ASWIN_SystemState.c` | RCTA 系统当前状态机状态 (0-6) |
| `bRCTAEnable` | `bool` | `RteComMapping.c` | 用户/系统使能标志，来自 CAN 信号 `RCTASwtReq` |
| `fRctaObjWarningTTM` | `float` | `adasFunc.c` | 报警触发时间阈值 (4.2s) |
| `fRctaObjWarningLowYawAngle` | `float` | `adasFunc.c` | 报警触发角度下限 (45°) |
| `PERInputUpdate.adasEnable.bRCTAEnable` | `bool` | `RteComMapping.c` | 输入信号映射后的功能使能标志 |
| `g_RteComMapping_RLWarnSig.RCTAState` | `uint8_t` | `RteComMapping.c` | 发送给网关/仪表的 RCTA 状态 |
| `RCTA_warningReqLeft` / `Right` | `uint8_t` | `RteComMapping.c` | 左/右侧报警请求等级 (0:无, 1:一级, 2:二级) |
| `AdasStM.RCTAState` | `uint8_t` | `ASWIN_SystemState.c` | 状态机结构体中的 RCTA 状态副本 |
| `fRctaRoiOffSetY` | `float` | `adasFunc.c` | RCTA 检测区域的 Y 轴偏移量 |

## 6. 输入信号
1.  **车辆状态信号**:
    *   `VehSpd`: 车辆速度 (km/h)。
    *   `GearPos`: 挡位信息 (需为 R 挡，虽代码未直接显示变量名，但逻辑隐含在 Active 条件中)。
    *   `SteerWheelSpd`: 方向盘转角速度 (可能用于辅助判断)。
2.  **功能使能信号 (CAN)**:
    *   `RCTASwtReq`: 用户开关请求 (来自 `RteComMapping_ReadSignal`)。
    *   `RCTABrkSwtReq`: 制动功能开关请求 (若配置为合并模式)。
3.  **系统状态/故障信号**:
    *   `ESPFUN`: ESP 功能状态 (0: 未激活)。
    *   `TrailerSts`: 牵引模式状态 (0: 无牵引)。
    *   `DoorSts`: 车门状态 (需关闭)。
    *   `DTC`: 故障码状态 (`CheckAnyDtcActive`)。
    *   `MSRActv`, `VDCActv`, `PTCActv`, `BTCActv`: 其他底盘控制系统状态。
4.  **雷达感知数据**:
    *   目标列表 (Track List): 包含目标的距离、速度、角度、加速度、RCS 等。
    *   自车位置/姿态信息。

## 7. 输出信号
1.  **报警请求**:
    *   `RCTA_warningReqLeft` / `RCTA_warningReqRight`: 发送给仪表或网关的报警等级信号 (0/1/2)。
    *   `RR_Rcta_Warning` / `RL_Rcta_Warning`: 输出到雷达控制器或网关的布尔报警标志。
2.  **系统状态**:
    *   `RCTAState`: 系统当前状态 (Standby/Active/Failure 等)，通过 `RSDS_RCTAResp` 信号反馈。
    *   `RSDS_RCTAResp`: 功能响应信号 (1: 功能正常/激活，0: 关闭/故障)。
3.  **制动请求 (若 RCTB 联动)**:
    *   `RSDS_BrkgReq`: 制动请求标志。
    *   `RSDS_BrkgReqVal`: 制动压力/减速度请求值。

## 8. 与其他功能的交互
1.  **RCTB (Rear Cross Traffic Braking)**:
    *   **强耦合**: 代码中 `RCTASwtReq` 和 `RCTABrkSwtReq` 的处理逻辑紧密相关。如果 RCTA 关闭，RCTB 通常也会关闭（见 `RteComMapping.c` 第 766 行）。
    *   **状态共享**: 两者共用 `rctaSystemState` 和 `rctbSystemState` 的部分状态机逻辑（如 Standby/Active 的转换条件）。
2.  **BSD (Blind Spot Detection) & LCA (Lane Change Assist)**:
    *   **硬件共享**: 使用相同的后角雷达硬件。
    *   **ROI 竞争**: RCTA 和 BSD/LCA 可能共享雷达的 ROI 资源，但在不同车速下激活（BSD/LCA 通常在较高车速，RCTA 在倒车低速）。
3.  **ESP/Chassis Systems**:
    *   **抑制逻辑**: 当 ESP (`ESPFUN`), MSR, VDC, PTC, BTC 等底盘稳定系统激活时，RCTA 会进入 **Passive** 状态或抑制报警，避免干扰驾驶员的紧急操控。
4.  **Trailer Mode (牵引模式)**:
    *   当检测到牵引模式 (`TrailerSts == 1`) 时，RCTA 功能会被抑制（进入 Passive），因为牵引车的尾部几何形状和雷达视场会发生巨大变化，导致误报。
5.  **DOW (Door Open Warning)**:
    *   虽然独立，但共享后角雷达数据。在 `BliStsenable` 函数中，RCTA 和 DOW 的使能状态共同决定了雷达的唤醒/保持策略。
6.  **FCTA/FCTB**:
    *   逻辑对称，但由前角雷达处理。代码中 `AswIfSchedule.c` 根据雷达位置（前/后）分别调用更新函数。