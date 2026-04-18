

# BSD 功能分析

## 1. 功能概述
BSD (Blind Spot Detection，盲区检测) 功能主要用于监测车辆两侧后方的盲区区域。当系统处于激活状态且检测到盲区内有目标车辆时，通过仪表盘或后视镜指示灯向驾驶员发出报警，防止变道时发生碰撞。该功能依赖于角雷达（Corner Radar）的目标跟踪数据，结合自车速度、档位、曲率半径等状态信息进行逻辑判断。

## 2. 状态机
BSD 系统状态由 `bsdSystemState` 变量管理，定义在 `adasFunc.c` 中。状态转换逻辑主要在 `BsdUpdateSystemStatus` 函数中实现。

| 状态值 | 状态名称 | 含义 | 转换/保持条件 |
| :--- | :--- | :--- | :--- |
| **0** | **None** | 未初始化 | 自诊断标志 `g_DTCCode.selfInspFlg` 为 false。 |
| **1** | **Init** | 初始化 | 自诊断标志为 true，且当前状态为 0。 |
| **2** | **Standby** | 待机/就绪 | 功能使能 (`bBSDEnable`)，非挂车模式，非标定中，无故障，档位为 4/5/6，速度在 12-146 km/h，曲率半径 > 125m。 |
| **3** | **Active** | 激活 | 代码片段中未直接显示进入此状态的逻辑，但 `UpdateObjAdasWarningFlg` 中检查状态 2 或 3 时允许报警。通常指系统就绪且满足报警条件。 |
| **4** | **Off** | 关闭 | 功能未使能，或处于标定中 (`calibratingFlg`)，或处于挂车模式 (`bTrailerModelFlg`)。 |
| **5** | **Failure** | 故障 | 自诊断标志为 true，且存在故障标志 (`failureFlg`)。 |
| **6** | **Passive** | 被动/抑制 | 系统曾处于 Standby/Active，但当前不满足激活条件（如速度过低/过高、曲率半径过小），或档位不符合要求。 |

## 3. 报警/制动逻辑
BSD 功能主要输出报警信号，不涉及制动请求（制动通常由 LCA 或 AEB 负责，但 BSD 是基础输入）。

*   **触发报警条件**:
    1.  **系统状态**: `bsdSystemState` 为 2 (Standby) 或 3 (Active)。
    2.  **功能使能**: `adasEnable->bBSDEnable` 为 true。
    3.  **目标位置**: 目标物体位于 BSD ROI (Region of Interest) 多边形区域内。
    4.  **目标速度**: 目标绝对速度 `> fBsdObjWarningSpd` (7.2 km/h)。
    5.  **相对速度**: 目标相对自车纵向速度 `< fBsdObjWarningRelVx` (-15.0 km/h，即目标比自车快或接近)。
    6.  **报警延时**: 满足上述条件后，需经过 `fBsdWarnDelay` (当前配置为 0.0s) 或帧数计数确认。

*   **取消报警条件**:
    1.  **系统状态**: 系统状态变为 Off, Failure, Passive 或 None。
    2.  **目标离开**: 目标离开 ROI 区域，且满足去报警迟滞条件（使用 `fBsdObjDeWarning...OffSet` 参数扩大 ROI 边界进行判断，防止抖动）。
    3.  **目标速度**: 目标速度 `< fBsdObjDeWarningSpd` (3.6 km/h)。
    4.  **相对速度**: 目标相对速度 `> fBsdObjDeWarningRelVx` (-20.0 km/h)。
    5.  **保持计数**: 报警保持帧数 `bsdKeepWarnFrm` 计数结束。

*   **特殊逻辑**:
    *   **弯道去报警**: 若 `bBsdCurbDewarningEnable` 为 true，在特定曲率下可能抑制报警。
    *   **超车保持**: 存在 `bBsdLeftOverTakeFlag` 等逻辑，用于处理超车场景下的报警保持。

## 4. 关键阈值
以下参数定义在 `adasFunc.c` 和 `adasFunc.h` 中，单位为 km/h 或 m，除非另有说明。

| 参数变量名 | 默认值 | 含义 |
| :--- | :--- | :--- |
| `fBsdActiveSpd` | 12.0 km/h | 系统激活最低速度 |
| `fBsdDeactiveSpd` | 10.0 km/h | 系统去激活最低速度 (迟滞) |
| `fBsdActiveUpperSpd` | 146.0 km/h | 系统激活最高速度 |
| `fBsdDeactiveUpperSpd` | 151.0 km/h | 系统去激活最高速度 (迟滞) |
| `fBsdActiveCurbRadius` | 125.0 m | 系统激活最小曲率半径 |
| `fBsdDeactiveCurbRadius` | 75.0 m | 系统去激活最小曲率半径 (迟滞) |
| `fBsdObjWarningSpd` | 7.2 km/h | 目标触发报警的绝对速度阈值 |
| `fBsdObjDeWarningSpd` | 3.6 km/h | 目标取消报警的绝对速度阈值 |
| `fBsdObjWarningRelVx` | -15.0 km/h | 目标触发报警的相对纵向速度阈值 |
| `fBsdObjDeWarningRelVx` | -20.0 km/h | 目标取消报警的相对纵向速度阈值 |
| `fBsdWarnDelay` | 0.0 s | 报警触发延时时间 |
| `LineBSDC` | `DISTANCEDRIVER` | BSD ROI 纵向起点 (车头方向) |
| `LineBSDB` | -5.0 - `DISTANCEREAR` | BSD ROI 纵向终点 (车尾方向) |
| `LineBSDLCAG` | 3.3 + `EGOCARWIDTH`/2 | BSD ROI 左侧横向边界 |
| `LineBSDLCAL` | -3.3 - `EGOCARWIDTH`/2 | BSD ROI 右侧横向边界 |

## 5. 关键变量

| 变量名 | 类型 | 来源 | 含义 |
| :--- | :--- | :--- | :--- |
| `bsdSystemState` | `uint8_t` | `adasFunc.c` | BSD 系统当前状态机状态 (0-6) |
| `bBsdLeftWarningFlg` | `bool` | `adasFunc.c` | 左侧 BSD 报警标志位 |
| `bBsdRightWarningFlg` | `bool` | `adasFunc.c` | 右侧 BSD 报警标志位 |
| `bBsdLeftKeepFlag` | `bool` | `adasFunc.c` | 左侧报警保持标志，用于防抖 |
| `bsdLeftFrmCount` | `uint8_t` | `adasFunc.c` | 左侧报警保持帧计数 |
| `bBsdLeftOverTakeFlag` | `bool` | `adasFunc.c` | 左侧超车场景标志 |
| `g_egoCarAddInfo.carSpd` | `float` | 全局变量 | 自车当前速度 (m/s) |
| `g_egoCarAddInfo.actual_gear` | `uint8_t` | 全局变量 | 自车当前档位 (4/5/6 有效) |
| `curvRadius` | `float` | 函数参数 | 当前道路曲率半径 (m) |
| `g_DTCCode.failureFlg` | `bool` | 全局变量 | 系统故障标志 |
| `adasEnable->bBSDEnable` | `bool` | 输入结构体 | BSD 功能使能开关 |
| `objInfo->trcOutData[i]` | `struct` | 输入结构体 | 雷达跟踪目标数据 (位置、速度等) |

## 6. 输入信号
BSD 功能逻辑依赖以下输入信号：

1.  **自车状态**:
    *   `carSpd`: 自车速度。
    *   `actual_gear`: 自车档位。
    *   `curvRadius`: 道路曲率半径。
    *   `pillar_b_distX`, `rear_bumper_distX`, `vehicle_width`: 车辆固定参数 (用于计算 ROI)。
2.  **系统状态**:
    *   `selfInspFlg`: 自诊断标志。
    *   `failureFlg`: 故障标志。
    *   `calibratingFlg`: 标定标志。
    *   `bTrailerModelFlg`: 挂车模式标志。
3.  **功能配置**:
    *   `bBSDEnable`: 功能开关。
    *   `bBsdCurbDewarningEnable`: 弯道去报警开关。
4.  **感知数据**:
    *   `trcNum`: 跟踪目标数量。
    *   `trcOutData`: 目标列表 (包含位置 x/y, 速度 vx/vy, 目标 ID 等)。

## 7. 输出信号
BSD 功能主要输出报警状态，不直接输出制动请求：

1.  **报警标志**:
    *   `adasWarning->bLeftBsdWarning`: 左侧 BSD 报警输出 (0/1)。
    *   `adasWarning->bRightBsdWarning`: 右侧 BSD 报警输出 (0/1)。
    *   `lastAdasWarning.bLeftBsdWarning`: 上一帧报警状态 (用于状态保持)。
2.  **目标属性**:
    *   `objInfo->trcOutData[i].objBsdWarningFlag`: 单个目标的 BSD 报警标记 (Normal/Warning)。
3.  **系统状态**:
    *   `adasWarning->bsdSystemState`: 当前系统状态机状态。

## 8. 与其他功能的交互
1.  **LCA (Lane Change Assist)**:
    *   **共享 ROI 参数**: BSD 和 LCA 共享部分横向边界定义 (`LineBSDLCAG`, `LineBSDLCAF` 等)，但纵向范围不同 (LCA 更远，`LineLCAA` = -80m)。
    *   **状态互斥/依赖**: 在 `UpdateObjAdasWarningFlg` 中，如果 `!adasEnable->bBSDEnable && !adasEnable->bELKEnable`，会清除 BSD 报警标志。ELK (Emergency Lane Keeping) 可能与 BSD/LCA 有联动。
2.  **DOW (Door Open Warning)**:
    *   共享状态机结构 (`dowSystemState`) 和报警保持逻辑 (`bDowLeftKeepFlag`)。
    *   在 `ResetAdasSystemStatusPara` 中，BSD 和 DOW 的复位逻辑并行执行。
3.  **RCTA/RCTB**:
    *   虽然代码片段中主要展示 BSD，但 `UpdateObjAdasWarningFlg` 显示所有功能 (RCTA, RCTB, FCTA, FCTB) 共享同一个目标遍历循环来更新各自的报警标志。
    *   如果系统状态不满足 (非 Standby/Active)，对应功能的对象报警标志会被强制置为 `WarningFlag_Normal`。
4.  **DTC (Diagnostic Trouble Code)**:
    *   BSD 状态机强依赖 `g_DTCCode` 中的 `selfInspFlg`, `failureFlg`, `calibratingFlg`。一旦进入 Failure 状态，BSD 功能立即关闭。