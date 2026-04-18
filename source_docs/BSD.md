# BSD 功能分析

## 1. 功能概述
本模块实现了基于角雷达（Corner Radar）的**盲区检测（Blind Spot Detection, BSD）**功能。
该功能主要用于监测车辆侧后方盲区内的动态障碍物（如车辆、摩托车等）。当检测到目标车辆进入预设的盲区区域（ROI）并满足特定的速度和相对速度条件时，系统会触发报警（通常通过仪表盘指示灯或后视镜 LED 闪烁），提醒驾驶员变道存在风险。
代码逻辑涵盖了从系统激活条件判断、ROI 区域定义、目标筛选、报警触发与解除（迟滞逻辑）以及状态机管理的全过程。BSD 功能与 LCA（变道辅助）共享部分 ROI 定义和传感器资源，但在报警逻辑和状态管理上独立。

## 2. 状态机
根据 `ASWIN_SystemState.h` 中的注释和 `ASWIN_SystemState.c` 中的逻辑，BSD 功能的状态机定义如下：

*   **状态定义 (uint8_t)**:
    *   `0`: **None** (未定义/未初始化)
    *   `1`: **Init** (初始化中)
    *   `2`: **Standby** (就绪/待机) - 系统已激活，满足运行条件，但未检测到报警目标。
    *   `3`: **Active** (激活/报警中) - 系统处于 Standby 状态，且检测到满足报警条件的目标，正在输出报警信号。
    *   `4`: **Off** (关闭) - 用户关闭或系统不满足运行条件（如车速过低/过高）。
    *   `5`: **Failure** (故障) - 雷达传感器故障或通信故障。
    *   `6`: **Passive** (被动/抑制) - 如拖车模式（Trailer Mode）激活时，功能被抑制。

*   **状态转换逻辑**:
    *   **Standby (2) -> Active (3)**:
        *   条件：系统处于 Standby 状态 (`bsdSystemState == 2`) 且检测到左侧或右侧有有效的 BSD 报警请求 (`PEROutput.adasWarning.bLeftBsdWarning != 0` 或 `bRightBsdWarning != 0`)。
        *   代码位置：`ASWIN_SystemState.c` L689-L692。
    *   **Active (3) -> Standby (2)**:
        *   条件：报警条件不再满足（目标离开 ROI 或相对速度不满足），报警请求信号复位为 0。
        *   注：代码片段未直接展示复位逻辑，通常由 `adasFunc.c` 中的报警清除逻辑控制，当 `bLeftBsdWarning` 和 `bRightBsdWarning` 归零时，状态机逻辑（未在片段中完全展示，但隐含在 `AdasEnable` 和状态更新函数中）会将状态切回 Standby。
    *   **Standby/Active -> Off (4)**:
        *   条件：车速低于 `fBsdDeactiveSpd` (10 km/h) 或高于 `fBsdDeactiveUpperSpd` (151 km/h)，或曲率半径小于 `fBsdDeactiveCurbRadius` (75m)。
    *   **Standby/Active -> Passive (6)**:
        *   条件：检测到拖车模式 (`AdasStM.TrailerSts == 1`) 且当前状态为 6 (Passive) 或其他特定抑制条件。见 `ASWIN_SystemState.c` L390。
    *   **Standby/Active -> Failure (5)**:
        *   条件：雷达传感器报告故障 (`ErrSts() == TRUE`) 或 DTC 激活。

## 3. 报警/制动逻辑
BSD 功能仅输出**报警请求**，不涉及制动请求（制动请求属于 RCTB/FCTB 等功能）。

*   **报警触发条件 (Trigger)**:
    1.  **系统状态**: 必须处于 `Standby` (2) 或 `Active` (3) 状态。
    2.  **ROI 区域**: 目标必须位于 BSD 定义的 ROI 区域内（见关键阈值部分）。
    3.  **目标速度**: 目标绝对速度 `v_obj` 需满足 `fBsdObjWarningSpd` (7.2 km/h) 以上。
    4.  **相对速度**: 目标相对于自车的纵向速度 `v_rel` 需满足 `fBsdObjWarningRelVx` (-15.0 km/h) 条件（通常指目标正在快速接近或相对静止但处于危险区）。
    5.  **迟滞处理**: 报警触发可能包含时间延迟 (`fBsdWarnDelay`) 或速度延迟逻辑，防止误报。

*   **报警取消条件 (De-trigger)**:
    1.  **目标离开**: 目标离开 ROI 区域。
    2.  **速度不满足**: 目标速度低于 `fBsdObjDeWarningSpd` (3.6 km/h)。
    3.  **相对速度不满足**: 相对速度高于 `fBsdObjDeWarningRelVx` (-20.0 km/h，即相对远离或接近速度变小)。
    4.  **边界偏移 (Hysteresis)**: 为了防止目标在边界处报警闪烁，取消报警时 ROI 边界会向内收缩（Offset）：
        *   左侧：X 轴偏移 `fBsdObjDeWarningLeftTopOffSetX` (0.5m) 和 `fBsdObjDeWarningLeftBottomOffSetX` (-0.5m)，Y 轴偏移 `fBsdObjDeWarningLeftOuterOffSetY` (0.3m) 等。
        *   右侧：类似逻辑，使用右侧对应的 Offset 变量。
    5.  **系统状态变化**: 系统进入 Off 或 Failure 状态。

*   **报警输出**:
    *   左侧报警：`PEROutput.adasWarning.bLeftBsdWarning` (值 > 0 表示报警，可能区分一级/二级报警)。
    *   右侧报警：`PEROutput.adasWarning.bRightBsdWarning`。
    *   最终通过 CAN 总线发送 `RR_BsdLca_Warning` 或 `RL_BsdLca_Warning` 信号。

## 4. 关键阈值
以下阈值直接决定了功能的激活范围和报警灵敏度：

| 参数名称 | 变量名 | 默认值 | 单位 | 含义 |
| :--- | :--- | :--- | :--- :--- |
| **系统激活车速** | `fBsdActiveSpd` | 12.0 | km/h | 车速高于此值系统进入 Standby |
| **系统关闭车速** | `fBsdDeactiveSpd` | 10.0 | km/h | 车速低于此值系统退出 (迟滞) |
| **系统激活上限车速** | `fBsdActiveUpperSpd` | 146.0 | km/h | 车速高于此值系统关闭 |
| **系统关闭上限车速** | `fBsdDeactiveUpperSpd` | 151.0 | km/h | 车速低于此值系统恢复 (迟滞) |
| **系统激活曲率半径** | `fBsdActiveCurbRadius` | 125.0 | m | 转弯半径大于此值系统激活 |
| **系统关闭曲率半径** | `fBsdDeactiveCurbRadius` | 75.0 | m | 转弯半径小于此值系统关闭 |
| **目标报警速度** | `fBsdObjWarningSpd` | 7.2 | km/h | 目标速度需大于此值才报警 |
| **目标取消报警速度** | `fBsdObjDeWarningSpd` | 3.6 | km/h | 目标速度低于此值取消报警 |
| **目标报警相对速度** | `fBsdObjWarningRelVx` | -15.0 | km/h | 相对速度阈值 (负值表示接近) |
| **目标取消报警相对速度** | `fBsdObjDeWarningRelVx` | -20.0 | km/h | 相对速度阈值 (迟滞) |
| **BSD ROI 纵向起点** | `LineBSDC` | `DISTANCEDRIVER` | m | 盲区前界 (驾驶员位置) |
| **BSD ROI 纵向终点** | `LineBSDB` | `-5.0 - DISTANCEREAR` | m | 盲区后界 (车尾后 5 米) |
| **BSD ROI 横向宽度** | `LineBSDLCAG` / `LineBSDLCAL` | `3.3 + Width/2` | m | 盲区侧向边界 (车宽 + 3.3m) |

## 5. 关键变量

| 变量名 | 类型 | 来源 | 含义 |
| :--- | :--- | :--- | :--- |
| `bsdSystemState` | `uint8` | `ASWIN_SystemState.c` | BSD 功能当前状态机状态 (0-6) |
| `bLeftBsdWarning` | `bool`/`uint8` | `adasFunc.c` (计算) | 左侧 BSD 报警请求标志 |
| `bRightBsdWarning` | `bool`/`uint8` | `adasFunc.c` (计算) | 右侧 BSD 报警请求标志 |
| `fBsdActiveSpd` | `float` | `adasFunc.c` | 系统激活车速阈值 |
| `LineBSDC` | `float` | `adasFunc.c` | BSD ROI 纵向起始坐标 |
| `LineBSDB` | `float` | `adasFunc.c` | BSD ROI 纵向结束坐标 |
| `LineBSDLCAG` | `float` | `adasFunc.c` | 左侧 BSD ROI 横向边界 |
| `LineBSDLCAL` | `float` | `adasFunc.c` | 右侧 BSD ROI 横向边界 |
| `bBsdCurbDewarningEnable` | `bool` | `adasFunc.c` | 弯道报警抑制开关 |
| `PERInputUpdate.adasEnable.bBSDEnable` | `bool` | `RteComMapping.c` | 用户/系统使能信号输入 |
| `g_egoCarAddInfo.carSpd` | `float` | `GlobalVar` | 自车当前车速 |
| `g_egoCarAddInfo.yawRate` | `float` | `GlobalVar` | 自车横摆角速度 (用于计算曲率) |

## 6. 输入信号
功能正常运行所需的输入信号：

1.  **自车状态**:
    *   车速 (`carSpd`)
    *   横摆角速度 (`yawRate`) -> 用于计算曲率半径
    *   档位 (`actual_gear`)
    *   转向角/方向盘状态 (隐含在曲率计算或 LCA 交互中)
2.  **传感器数据**:
    *   雷达目标列表 (Object List): 包含目标的距离、方位角、相对速度、绝对速度、RCS 等。
    *   雷达状态 (PowerOn, Fault, Calibration Status)。
3.  **系统配置/开关**:
    *   BSD 功能开关 (`bBSDEnable`): 来自用户设置或 CAN 信号 (`LCASwtReq` 或专用开关)。
    *   拖车模式状态 (`TrailerSts`)。
    *   故障状态 (DTC)。
4.  **车辆参数**:
    *   车宽 (`EGOCARWIDTH`)
    *   驾驶员位置 (`DISTANCEDRIVER`)
    *   车尾距离 (`DISTANCEREAR`)

## 7. 输出信号
功能产生的输出信号：

1.  **报警信号**:
    *   `bLeftBsdWarning` / `bRightBsdWarning`: 内部报警标志。
    *   `RR_BsdLca_Warning` / `RL_BsdLca_Warning`: 通过 CAN 总线发送给网关或仪表的报警等级信号 (0: 无，1: 一级，2: 二级)。
2.  **状态信号**:
    *   `bsdSystemState`: 功能当前状态 (Standby/Active/Off 等)。
    *   `RSDS_BliSts` (Blind Spot Status): 盲区状态指示。
    *   `RSDS_BSDState`: 发送给外部系统的 BSD 状态字。
3.  **诊断信号**:
    *   `RR_Fault_Err` / `RL_Fault_Err`: 故障标志。

## 8. 与其他功能的交互

*   **LCA (Lane Change Assist)**:
    *   **资源共享**: 共享相同的雷达传感器和大部分 ROI 定义 (`LineBSDLCAG`, `LineBSDLCAL` 等)。
    *   **优先级**: 在输出信号 `RR_BsdLca_Warning` 中，如果 BSD 和 LCA 同时报警，代码逻辑 (L164-L170) 取两者中的**较大值**作为最终输出，确保高优先级报警被传达。
    *   **状态联动**: `AdasStateActive` 函数中，BSD 和 LCA 的状态更新逻辑相似，但独立判断。

*   **RCTA/RCTB (Rear Cross Traffic Alert/Brake)**:
    *   **传感器复用**: 使用相同的后角雷达。
    *   **ROI 区分**: RCTA 通常关注车辆后方横向穿行的车辆，而 BSD 关注侧后方同向/对向车辆。两者在目标筛选逻辑上会有不同的 ROI 和速度/角度阈值。
    *   **状态抑制**: 当 RCTA 处于激活状态时，可能会影响 BSD 的某些逻辑（代码片段未直接展示，但通常有互斥或优先级逻辑）。

*   **DOW (Door Opening Warning)**:
    *   共享后角雷达数据，但 DOW 关注的是车辆静止或低速时的后方来车，而 BSD 关注行驶中的侧方盲区。
    *   在 `BliStsenable` 函数中，DOW 的使能状态与 BSD 一起作为系统整体使能的一部分。

*   **Trailer Mode (拖车模式)**:
    *   当检测到拖车模式 (`AdasStM.TrailerSts == 1`) 时，BSD 状态会被强制置为 `Passive` (6)，功能被抑制，防止误报。

*   **ELK (Electronic Lane Keep / 电子防碰撞)**:
    *   代码片段 L821 注释显示，ELK 的使能依赖于 BSD、LCA、DOW 等多个功能的使能状态，表明 ELK 可能是一个上层综合功能或系统健康状态指示。