# FCTA 功能分析

## 1. 功能概述
**FCTA (Front Cross Traffic Alert)** 即前方交叉交通警报功能。该功能主要利用车辆前角雷达（Front Corner Radar），在车辆低速行驶（如从停车位驶出、通过路口）时，检测横向穿越的障碍物（车辆、行人等）。当系统判断存在碰撞风险时，通过仪表盘、HUD 或声音向驾驶员发出警报，提示驾驶员注意横向来车，避免碰撞。

根据代码分析，FCTA 是角雷达系统（Corner Radar）的核心功能之一，与 FCTB（前方交叉交通制动）紧密关联，通常 FCTA 作为 FCTB 的前置预警阶段。

## 2. 状态机
根据 `ASWIN_SystemState.c` 和 `adasFunc.c` 中的逻辑，FCTA 的状态机主要包含以下状态及转换逻辑：

*   **状态定义 (推测映射)**:
    *   `0`: **Off/None** (功能关闭或未激活)
    *   `1`: **Init/Standby** (系统初始化或待机，满足车速条件但未检测到风险)
    *   `2`: **Active/Standby** (系统激活，正在监测，未报警)
    *   `3`: **Warning/Active** (系统激活且正在报警)
    *   *(注：代码中 `fctaSystemState` 取值为 2 或 3 时，`bFCTAEnable` 为 TRUE)*

*   **状态转换条件**:
    1.  **进入 Active (State 2)**:
        *   系统上电且无故障 (`AdasStM.SysPowerMod == SYS_POWER_ON`)。
        *   功能开关开启 (`PERInputUpdate.adasEnable.bFCTAEnable == 1`)。
        *   车速在激活范围内：`fFctaActiveLowSpd` (0.5 km/h) <= 车速 <= `fFctaActiveUpSpd` (21.0 km/h)。
        *   无 DTC 故障 (`CheckAnyDtcActive` 为 false)。
    2.  **进入 Warning (State 3)**:
        *   当前状态为 `2` (Active)。
        *   检测到左侧或右侧存在危险目标：`bLeftFctaWarning != 0` 或 `bRightFctaWarning != 0`。
        *   代码逻辑：`if ((fctaSystemState == 2) && ((PEROutput.adasWarning.bLeftFctaWarning !=0) || (PEROutput.adasWarning.bRightFctaWarning !=0))) { fctaSystemState=3; }`
    3.  **退出/复位 (State 2 -> 0 或 1)**:
        *   车速超出范围：车速 > `fFctaDeactiveUpSpd` (22.0 km/h) 或 车速 < `fFctaDeactiveLowSpd` (0.0 km/h)。
        *   功能开关关闭。
        *   检测到系统故障。
        *   报警条件消失且经过迟滞时间（De-warning logic）。

## 3. 报警/制动逻辑
FCTA 仅负责**报警**，不直接控制制动（制动由 FCTB 负责，但两者共享检测逻辑）。

*   **报警触发条件 (Warning Trigger)**:
    当检测到目标满足以下**所有**条件时，触发报警 (`bLeftFctaWarning` 或 `bRightFctaWarning` 置位)：
    1.  **目标速度**: `fFctaObjWarningSpd` (4.0 km/h) <= 目标相对速度 <= `fFctaObjWarningUpSpd` (70.0 km/h)。
    2.  **目标角度 (Yaw Angle)**: 目标相对于雷达的绝对偏航角在 `fFctaObjWarningLowYawAngle` (38.0°) 到 `fFctaObjWarningUpYawAngle` (127.0°) 之间。这定义了横向穿越的 ROI 区域。
    3.  **碰撞时间 (TTM)**:
        *   X 轴方向 (纵向接近): `TTM_x` <= `fFctaObjWarningBaseTTMX` (2.0s) + `fFctaObjWarningTTMXOffSet` (0.0s)。
        *   Y 轴方向 (横向穿越): `TTM_y` 在 `fFctaObjWarningLowTTMY` (0.4s) 到 `fFctaObjWarningUpTTMY` (2.5s) 之间。
    4.  **距离/位置 (DDCI/C-DDCI)**:
        *   目标在雷达坐标系下的位置需满足特定的 DDCI (Distance to Collision Impact) 偏移量范围，确保目标处于车头前方的有效预警区域。
        *   `fFctaObjWarningLowerDDCIOffSet` (-1.0m) <= DDCI <= `fFctaObjWarningUpBaseDDCI` (2.8m)。

*   **报警取消条件 (De-warning)**:
    当报警触发后，若以下条件满足，则取消报警：
    1.  **目标速度**: 目标速度 < `fFctaObjDeWarningSpd` (2.2 km/h) 或 > `fFctaObjDeWarningUpSpd` (73.6 km/h)。
    2.  **目标角度**: 角度超出 `fFctaObjDeWarningLowYawAngle` (33.0°) 到 `fFctaObjDeWarningUpYawAngle` (135.0°) 范围（注意：取消范围比触发范围略宽，形成迟滞）。
    3.  **碰撞时间 (TTM)**:
        *   X 轴 TTM > `fFctaObjWarningBaseTTMX` (2.0s) + `fFctaObjDeWarningTTMXOffSet` (0.3s) = 2.3s。
        *   Y 轴 TTM > `fFctaObjDeWarningUpTTMY` (2.8s)。
    4.  **位置**: DDCI 超出预警区域。

## 4. 关键阈值
| 参数名 | 变量名 | 数值 | 单位 | 含义 |
| :--- | :--- | :--- | :--- | :--- |
| **系统激活上限车速** | `fFctaActiveUpSpd` | 21.0 | km/h | 车辆速度超过此值，FCTA 功能退出激活状态 |
| **系统激活下限车速** | `fFctaActiveLowSpd` | 0.5 | km/h | 车辆速度低于此值，FCTA 功能不激活 |
| **系统退出上限车速** | `fFctaDeactiveUpSpd` | 22.0 | km/h | 迟滞阈值，防止在临界速度频繁跳变 |
| **目标预警速度下限** | `fFctaObjWarningSpd` | 4.0 | km/h | 低于此速度的目标不视为威胁（如静止物体） |
| **目标预警速度上限** | `fFctaObjWarningUpSpd` | 70.0 | km/h | 高于此速度的目标可能超出雷达处理范围或逻辑判定 |
| **预警角度下限** | `fFctaObjWarningLowYawAngle` | 38.0 | deg | 目标横向穿越的最小角度 |
| **预警角度上限** | `fFctaObjWarningUpYawAngle` | 127.0 | deg | 目标横向穿越的最大角度 |
| **X 轴基础 TTM** | `fFctaObjWarningBaseTTMX` | 2.0 | s | 纵向碰撞时间阈值 |
| **Y 轴 TTM 范围** | `fFctaObjWarningLowTTMY` / `UpTTMY` | 0.4 / 2.5 | s | 横向穿越碰撞时间窗口 |
| **ROI Y 轴偏移** | `fFctaRoiOffSetY` | 0.3 | m | 检测区域在 Y 轴上的偏移量 |

## 5. 关键变量

| 变量名 | 类型 | 来源 | 含义 |
| :--- | :--- | :--- | :--- |
| `fctaSystemState` | `uint8_t` | `ASWIN_SystemState.c` | FCTA 功能当前状态机状态 (0:Off, 2:Active, 3:Warning) |
| `bFCTAEnable` | `bool` | `RteComMapping.c` / `adasFunc.c` | FCTA 功能使能标志位，由用户开关或配置决定 |
| `bLeftFctaWarning` | `uint8_t` | `adasFunc.c` (内部计算) | 左侧 FCTA 报警状态 (0:无, 1:一级, 2:二级) |
| `bRightFctaWarning` | `uint8_t` | `adasFunc.c` (内部计算) | 右侧 FCTA 报警状态 (0:无, 1:一级, 2:二级) |
| `fFctaActiveUpSpd` | `float` | `adasFunc.c` | 系统激活的上限车速阈值 |
| `fFctaObjWarningBaseTTMX` | `float` | `adasFunc.c` | 触发报警的基础 X 轴碰撞时间阈值 |
| `AdasStM.FCTAState` | `uint8_t` | `ASWIN_SystemState.h` | 全局状态机结构体中的 FCTA 状态副本 |
| `PERInputUpdate.adasEnable.bFCTAEnable` | `bool` | `RteComMapping.c` | 从 CAN 总线接收的用户开关信号 |

## 6. 输入信号
1.  **车辆状态**:
    *   车速 (Vehicle Speed): 用于判断功能激活/退出。
    *   档位 (Gear): 通常需处于非 P 档（代码中虽未直接显示，但通常逻辑如此）。
    *   电源模式 (SysPowerMod): `SYS_POWER_ON`。
2.  **用户输入**:
    *   FCTA 功能开关 (`FCTASwtReq` 或 `FCTABrkSwtReq`): 通过 CAN 信号 `FCTASwtReq` 或 `FCTABrkSwtReq` 读取。
    *   变体配置 (`g_GWMSpecificVariant`): 决定信号映射逻辑 (DID Merge)。
3.  **雷达感知数据**:
    *   目标列表 (Object List): 包含目标的距离、速度、角度 (Yaw)、相对速度等。
    *   雷达自身状态：故障状态 (`ErrSts`)、校准状态 (`inCalibState`)。
4.  **系统状态**:
    *   DTC 故障标志 (`CheckAnyDtcActive`)。

## 7. 输出信号
1.  **报警请求**:
    *   `bLeftFctaWarning` / `bRightFctaWarning`: 发送给 HMI 或仪表盘，用于点亮图标或发出声音。
    *   `FCTA_warningReqLeft`: 通过 `RteComMapping` 映射到 CAN 信号 (如 `RSDS_FCTA_Warning` 等)。
2.  **系统状态**:
    *   `fctaSystemState`: 输出当前功能状态 (Active/Warning)。
    *   `RSDS_CTA_Actv`: 当 FCTA/FCTB 激活时，可能输出此标志位 (代码中 `RSDS_CTA_Actv` 逻辑主要关联 RCTB，但 FCTA 状态也会更新到 `AdasStM` 并可能映射到总线)。
    *   `CR_FCTA_Resp`: 功能响应信号，告知上层系统功能是否可用。
3.  **故障信息**:
    *   `FR_Fault_Err` / `FL_Fault_Err`: 雷达故障状态。

## 8. 与其他功能的交互
1.  **FCTB (Front Cross Traffic Braking)**:
    *   **强依赖**: FCTA 是 FCTB 的前置阶段。代码中 `fctaSystemState` 和 `fctbSystemState` 逻辑相似。
    *   **逻辑复用**: 两者共享大部分阈值参数（如角度、速度范围），但 FCTB 的 TTM 阈值更严格，且 FCTB 会输出制动请求 (`fBrakeValue`)。
    *   **状态联动**: 当 FCTA 报警 (`State 3`) 且风险进一步升级（TTM 更短）时，可能触发 FCTB 介入。
2.  **RCTA/RCTB (Rear Cross Traffic)**:
    *   **架构对称**: 代码结构高度相似，但 RCTA 由后角雷达处理，FCTA 由前角雷达处理。
    *   **资源调度**: 在 `AswIfSchedule.c` 中，前雷达和后雷达的状态更新函数是分开调用的 (`UpdateFctaAndFctbSystemStatus` vs `UpdateRctaAndRctbSystemStatus`)。
3.  **HMI/仪表盘**:
    *   通过 `RteComMapping` 将 `bLeftFctaWarning` 等信号转换为 CAN 报文发送给仪表，控制图标闪烁或声音报警。
4.  **诊断系统**:
    *   通过 `CheckAnyDtcActive` 读取故障码，若存在故障则强制关闭 FCTA 功能并输出故障状态。