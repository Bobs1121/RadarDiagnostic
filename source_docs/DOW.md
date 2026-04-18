# DOW 功能分析

## 1. 功能概述
DOW (Door Open Warning，开门预警) 功能旨在防止驾驶员或乘客在车辆停驻或低速状态下打开车门时，与后方或侧后方接近的车辆、行人或障碍物发生碰撞。
该功能主要依赖角雷达（Corner Radar）检测车辆侧后方的动态目标。当检测到有目标进入预设的**感兴趣区域 (ROI)**，且满足特定的**速度**、**角度**及**碰撞时间 (TTC)** 条件时，系统会触发声光报警。

根据代码分析，该功能具备以下特点：
*   **左右独立检测**：通过 `LineDOW` 系列参数定义了左侧和右侧独立的 ROI 区域。
*   **动态 ROI**：ROI 的边界与自车宽度 (`EGOCARWIDTH`) 及雷达安装位置 (`DISTANCEREAR`, `DISTANCEDRIVER`) 动态关联。
*   **迟滞控制**：报警触发与取消（De-warning）采用了不同的阈值（如 TTC、速度、角度），防止报警状态频繁跳变。
*   **特殊模式支持**：支持拖车模式 (`TrailerSts`) 下的功能抑制（进入 Passive 状态）。
*   **电源管理**：具备特定的断电延时逻辑（185s），确保熄火后一段时间内功能仍可用。

## 2. 状态机
虽然源码片段未直接展示状态转换的 `switch-case` 逻辑，但根据 `adasFunc.h` 中的定义及 `ASWIN_SystemState.c` 中的逻辑，DOW 状态机定义如下：

*   **状态定义 (uint8_t)**:
    *   `0`: **None** (未初始化/未定义)
    *   `1`: **Init** (初始化中)
    *   `2`: **Standby** (就绪，系统正常但条件未满足)
    *   `3`: **Active** (激活，满足报警条件，输出报警信号)
    *   `4`: **Off** (关闭，用户关闭或功能禁用)
    *   `5`: **Failure** (故障，雷达或系统报错)
    *   `6`: **Passive** (被动/抑制，如拖车模式)

*   **状态转换逻辑推断**:
    1.  **Init -> Standby**: 系统初始化完成，无故障，且 `bDOWEnable` 为真。
    2.  **Standby -> Active**: 检测到目标进入 ROI，且满足 `fDowObjWarningSpd`, `fDowObjWarningYawAngle`, `fDowObjWarningTTC` 等触发条件。
    3.  **Active -> Standby**: 目标离开 ROI 或不再满足触发条件（需满足 De-warning 阈值，如 TTC > `fDowObjDeWarningTTC`）。
    4.  **Any -> Off**: 用户通过 `DOWSwtReq` 关闭功能，或系统速度超过阈值（通常 DOW 在高速下不工作，虽代码未显式给出上限，但 `fDowObjWarningUpperSpd` 设为 200km/h 暗示了极宽范围，实际逻辑可能在其他文件限制车速）。
    5.  **Any -> Passive**: 检测到拖车模式 (`TrailerSts == 1`) 且系统状态正常。
    6.  **Any -> Failure**: 雷达硬件故障或通信错误 (`ErrSts()` 返回真)。

## 3. 报警/制动逻辑
DOW 功能主要输出**报警请求**，通常不直接控制制动（制动通常由 AEB 或 RCTB 等更高级功能接管，DOW 侧重于警示）。

*   **触发报警条件 (Active)**:
    1.  **系统状态**: `dowSystemState == 3` (Active)。
    2.  **目标位置**: 目标位于 DOW ROI 区域内。
        *   ROI 由 `LineDOWA` ~ `LineDOWL` 定义，基于自车宽度和雷达安装位置计算。
    3.  **目标速度**: `ObjSpeed` 在 `[fDowObjWarningSpd, fDowObjWarningUpperSpd]` 范围内 (5.0 ~ 200.0 km/h)。
    4.  **目标角度**: 目标绝对偏航角 `|YawAngle| <= fDowObjWarningYawAngle` (45.0 度)。
    5.  **碰撞时间**: `TTC <= fDowObjWarningTTC` (3.5 秒)。

*   **取消报警条件 (De-warning)**:
    1.  **目标位置**: 目标离开 ROI 区域（需考虑迟滞边界 `fDowObjDeWarning...OffSet`）。
    2.  **目标速度**: `ObjSpeed < fDowObjDeWarningSpd` (5.0 km/h) 或 `> fDowObjDeWarningUpperSpd` (200.0 km/h)。
    3.  **目标角度**: `|YawAngle| > fDowObjDeWarningYawAngle` (50.0 度)。
    4.  **碰撞时间**: `TTC > fDowObjDeWarningTTC` (4.0 秒)。
    5.  **路缘抑制**: 如果 `bDowCurbDewarningEnable` 为真，且目标被判定为静止路缘，可能不报警或快速取消报警。

*   **输出逻辑**:
    *   当状态为 Active 时，`PEROutput.adasWarning.bRightDowWarning` (或左侧对应信号) 置为 1。
    *   在 `ASWOUT_OutCalc.c` 中，该信号被映射到 `g_ASWOUT_RadarWarnSigStrct.RR_Dow_Warning` 或 `RL_Dow_Warning` 发送给车身控制器 (BCM) 或仪表盘。

## 4. 关键阈值

| 参数名称 | 变量名 | 值 | 单位 | 说明 |
| :--- | :--- | :--- | :--- :--- |
| **系统激活速度** | `fDowActiveSpd` | 0.7 | km/h | 系统进入 Active 状态的最小车速 |
| **系统去激活速度** | `fDowDeactiveSpd` | 1.0 | km/h | 系统退出 Active 状态的车速迟滞 |
| **目标报警速度下限** | `fDowObjWarningSpd` | 5.0 | km/h | 目标触发报警的最小速度 |
| **目标去报警速度下限** | `fDowObjDeWarningSpd` | 5.0 | km/h | 目标取消报警的速度阈值 |
| **目标报警速度上限** | `fDowObjWarningUpperSpd` | 200.0 | km/h | 目标触发报警的最大速度 |
| **目标去报警速度上限** | `fDowObjDeWarningUpperSpd` | 200.0 | km/h | 目标取消报警的最大速度 |
| **目标报警偏航角** | `fDowObjWarningYawAngle` | 45.0 | deg | 目标相对自车的最大偏航角 |
| **目标去报警偏航角** | `fDowObjDeWarningYawAngle` | 50.0 | deg | 目标取消报警的偏航角迟滞 |
| **目标报警 TTC** | `fDowObjWarningTTC` | 3.5 | s | 触发报警的碰撞时间阈值 |
| **目标去报警 TTC** | `fDowObjDeWarningTTC` | 4.0 | s | 取消报警的碰撞时间迟滞 |
| **断电延时时间** | `DOW_POWERDOWN_TIME` | 185000 | ms | 熄火后功能保持激活的时间 (185s) |
| **左侧 ROI 外边界偏移** | `fDowObjDeWarningLeftOuterOffSetY` | 1.0 | m | 左侧 ROI 外边界去报警偏移 |
| **右侧 ROI 外边界偏移** | `fDowObjDeWarningRightOuterOffSetY` | -1.0 | m | 右侧 ROI 外边界去报警偏移 |

*注：ROI 的具体坐标 (`LineDOWA` ~ `LineDOWL`) 是动态计算的，依赖于 `DISTANCEREAR` (雷达距车尾距离), `DISTANCEDRIVER` (雷达距驾驶员距离), `EGOCARWIDTH` (自车宽度)。*

## 5. 关键变量

| 变量名 | 类型 | 来源 | 含义 |
| :--- | :--- | :--- | :--- |
| `dowSystemState` | `uint8_t` | `adasFunc.c` (全局) | DOW 功能当前状态机状态 (0-6) |
| `bDowEnable` | `bool` | `RteComMapping.c` (CAN 输入) | DOW 功能使能开关 (来自 `DOWSwtReq`) |
| `LineDOWA` ~ `LineDOWL` | `float` | `adasFunc.c` (计算) | DOW ROI 区域的顶点坐标 (X, Y) |
| `fDowObjWarningTTC` | `float` | `adasFunc.c` (配置) | 报警 TTC 阈值 |
| `fDowObjDeWarningTTC` | `float` | `adasFunc.c` (配置) | 去报警 TTC 阈值 |
| `bDowCurbDewarningEnable` | `bool` | `adasFunc.c` (配置) | 路缘去报警功能开关 |
| `TrailerSts` | `uint8_t` | `ASWIN_SystemState.c` (CAN 输入) | 拖车状态标志，用于进入 Passive 模式 |
| `bRightDowWarning` | `bool` | `PEROutput` (内部计算) | 右侧 DOW 报警输出标志 |
| `bLeftDowWarning` | `bool` | `PEROutput` (内部计算) | 左侧 DOW 报警输出标志 |
| `DOW_POWERDOWN_TIME` | `uint32_t` | `ASWIN_SystemState.h` (宏定义) | 熄火后功能保持时间 |

## 6. 输入信号
DOW 功能依赖以下输入信号进行逻辑判断：

1.  **车辆状态信号**:
    *   `DOWSwtReq`: 驾驶员/乘客开启/关闭 DOW 功能的请求 (CAN 信号)。
    *   `SysPowerMod`: 系统电源模式 (ON/OFF)，用于判断是否进入断电延时逻辑。
    *   `TrailerSts`: 拖车状态，用于抑制功能。
    *   `VehcleInfoUpdate.actual_gear`: 当前档位 (虽 DOW 主要在 R/N 档工作，但代码中未显式过滤，可能由上层逻辑处理)。
    *   `VehcleInfoUpdate.turn_light_left/right`: 转向灯状态 (可能用于辅助判断变道意图，但在 DOW 中主要用于区分场景)。
    *   `PassengerDoorSts` / `DrvDoorSts`: 车门开启状态 (部分逻辑可能结合车门开启瞬间触发，但核心逻辑是预警，即车门未开但即将开时报警)。

2.  **感知数据 (来自雷达)**:
    *   `ObjPos` (X, Y): 目标相对于雷达的位置。
    *   `ObjVel`: 目标相对速度。
    *   `ObjYaw`: 目标偏航角。
    *   `ObjTTC`: 目标碰撞时间。

3.  **车辆参数 (Calibration/Config)**:
    *   `EGOCARWIDTH`: 自车宽度。
    *   `DISTANCEREAR`: 雷达安装位置距车尾距离。
    *   `DISTANCEDRIVER`: 雷达安装位置距驾驶员距离。

## 7. 输出信号
DOW 功能计算完成后，输出以下信号：

1.  **报警请求**:
    *   `DOW_warningReqleft` / `DOW_warningReqright`: 左侧/右侧报警请求等级 (0: 无，1: 一级，2: 二级)。
    *   `RSDS_DOWResp`: DOW 功能响应状态 (1: 激活，0: 未激活)，用于反馈给网关或车身控制器。
    *   `RR_Dow_Warning` / `RL_Dow_Warning`: 发送给车身控制器 (BCM) 的具体报警信号，用于控制后视镜灯闪烁或蜂鸣器。

2.  **状态信号**:
    *   `DOWState`: 当前系统状态 (0-6)，用于仪表盘显示功能状态。
    *   `Fault_Err`: 故障标志位。

3.  **内部状态**:
    *   `dowSystemState`: 内部状态机变量，供其他模块读取。

## 8. 与其他功能的交互

1.  **与 BSD (盲区检测) / LCA (变道辅助)**:
    *   **共用 ROI 逻辑**: 代码中 `LineDOW` 与 `LineLCA` 定义方式类似，都基于自车宽度和雷达位置，但 DOW 的 ROI 更靠近车门区域，且角度阈值更宽。
    *   **信号复用**: 在 `ASWOUT_OutCalc.c` 中，DOW 报警信号与 BSD/LCA 信号分别映射，但在某些硬件实现中可能共用同一套报警灯逻辑（需根据具体车型配置）。

2.  **与 RCW (后方碰撞预警)**:
    *   **场景区分**: RCW 主要针对车辆后方直线接近的目标，DOW 针对侧后方。两者在 ROI 定义上有重叠但侧重不同。
    *   **状态互斥**: 在 `BliStsenable` 函数中，DOW 与 BSD, LCA, RCW 等并列，只要任一功能开启，系统即进入工作状态。

3.  **与 RCTA/RCTB (后方交叉交通)**:
    *   **逻辑互补**: RCTA 在倒车时检测横向来车，DOW 在停车开门时检测侧向来车。两者都依赖侧向雷达。
    *   **拖车模式联动**: 在 `DIDTrailerSts` 函数中，DOW 与 BSD, LCA, RCW, RCTA, RCTB 的状态被统一检查。当 `TrailerSts == 1` 时，所有这些功能都会进入 `Passive` (6) 状态，防止误报。

4.  **与电源管理 (Power Management)**:
    *   **独立延时**: DOW 拥有独立的 `Check_DOW_PowerDown_Delay` 逻辑。即使车辆熄火 (`SYS_POWER_OFF`)，只要 `bDOWEnable` 为真，功能会保持激活 185 秒 (`DOW_POWERDOWN_TIME`)，确保驾驶员熄火后开门的安全。

5.  **与通信映射 (RteComMapping)**:
    *   DOW 的使能状态 (`bDOWEnable`) 和报警输出 (`DOW_warningReqleft`) 通过 CAN 总线与车身域控制器 (BCM) 和仪表进行交互，实现声光报警。