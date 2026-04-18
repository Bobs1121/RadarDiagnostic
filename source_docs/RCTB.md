

# RCTB 功能分析

## 1. 功能概述
**RCTB (Rear Cross Traffic Braking)** 即后方交叉交通制动功能。该功能主要在车辆倒车（Reverse Gear）且低速行驶时激活，通过角雷达监测车辆后方左右两侧的横向移动物体（如车辆、行人）。当检测到存在碰撞风险且驾驶员未及时制动时，系统会发出报警并自动施加制动，以防止后方交叉碰撞事故。

## 2. 状态机
RCTB 系统状态由 `rctbSystemState` 变量管理，状态定义及转换逻辑主要位于 `RctaRctbUpdateStatus` 函数中。

| 状态值 | 状态名称 | 含义 | 转换条件 |
| :--- | :--- | :--- | :--- |
| **0** | **None** | 未初始化 | 系统自检标志 `selfInspFlg` 为 false 时进入。 |
| **1** | **Init** | 初始化 | `selfInspFlg` 为 true 且当前状态为 0 时进入。 |
| **2** | **Standby** | 待机 (Ready) | 功能使能 (`bRCTBEnable`)，无故障，无标定，档位为 6/7 (R 档)，制动就绪，车速在 **0.0 ~ 9.0 km/h** 之间。 |
| **3** | **Active** | 激活 (警告/制动) | 代码片段未显式设置此状态，通常由 Standby 状态检测到威胁对象 (`bRctbDetectFlg`) 后进入，用于区分待机与正在报警/制动。 |
| **4** | **Off** | 关闭 | 功能未使能 (`!bRCTBEnable`) 或 系统正在标定 (`calibratingFlg`)。 |
| **5** | **Failure** | 故障 | 系统检测到故障 (`failureFlg`)。 |
| **6** | **Passive** | 被动 | 功能使能但条件不满足（如车速超出范围 >10km/h 或 <0km/h，或档位/制动不满足条件）。 |

**状态转换逻辑摘要：**
1.  **自检失败/未开始** -> **None (0)**
2.  **自检通过** -> **Init (1)**
3.  **Init -> Off (4)**: 功能关闭或标定中。
4.  **Init -> Failure (5)**: 检测到故障。
5.  **Init -> Standby (2)**: 满足倒车、低速、制动就绪条件。
6.  **Standby/Active -> Passive (6)**: 车速超出激活范围（>10km/h 或 <0km/h）。
7.  **Passive -> Standby (2)**: 车速回到激活范围。
8.  **任意状态 -> Off (4)**: 功能开关关闭或标定中。
9.  **任意状态 -> Failure (5)**: 故障标志置位。

## 3. 报警/制动逻辑

### 3.1 触发条件
*   **系统状态**: 必须处于 **Standby (2)** 或 **Active (3)** 状态。
*   **对象检测**: 角雷达检测到后方左右侧 ROI 区域内的目标 (`bRctbDetectFlg` 为 true)。
*   **时间阈值**: 目标与自车的碰撞时间 (TTM) 小于警告阈值 `fRctbObjWarningTTM` (1.6s)。
*   **距离阈值**: 目标距离满足 DDCI (Distance to Collision Intersection) 条件，涉及 `fRctbObjWarningLowerDDCIOffSet` (-2.0m) 和 `fRctbObjWarningLowerCDDCIOffSet` (-4.0m)。
*   **制动就绪**: `!g_DTCCode.bBrakeNotReadyFlg`。

### 3.2 取消条件 (De-warning)
*   **系统状态**: 状态变为 Off, Failure, Passive 或 None。
*   **时间阈值**: TTM 大于取消警告阈值 `fRctbObjDeWarningTTM` (2.0s)。
*   **功能开关**: `adasEnable->bRCTBEnable` 变为 false。
*   **对象消失**: 目标离开 ROI 区域或不再满足威胁条件。

### 3.3 制动控制逻辑
*   **制动请求值 (`fRctbBrakeReqVal`)**: 默认初始化为 -4.0 (对应 `fRctbBrakeValue`)。
*   **保持制动 (`bRctbKeepBrakeFlg`)**: 当满足特定条件时进入保持状态，防止车辆完全停止前过早释放。
*   **保持时间阈值 (`fRctbHoldTimeThresh`)**: 3.0 秒。
*   **停止速度 (`fRctbStopSpd`)**: 1.0 km/h (转换为 m/s)。
*   **高速制动值 (`fRctbHighSpeedBrakeValue`)**: -6.0 (用于更紧急的情况)。
*   **保持制动值 (`fRctbHoldValue`)**: -2.0 (用于维持停车状态)。
*   **AEB 激活阈值 (`fRctbAEBActiveThresh`)**: 1.0 (可能用于判断是否触发 AEB 级别制动)。

## 4. 关键阈值
以下参数定义于 `adasFunc.c` (lines 401-481) 及 `adasFunc.h`。

| 参数变量名 | 默认值 | 单位 | 含义 |
| :--- | :--- | :--- | :--- |
| `fRctbActiveUpSpd` | 9.0 | km/h | 系统激活最高车速 |
| `fRctbActiveLowSpd` | 0.0 | km/h | 系统激活最低车速 |
| `fRctbDeactiveUpSpd` | 10.0 | km/h | 系统去激活最高车速 (迟滞) |
| `fRctbDeactiveLowSpd` | 0.0 | km/h | 系统去激活最低车速 |
| `fRctbDetectUpSpd` | 9.0 | km/h | 目标检测最高车速 |
| `fRctbDetectLowSpd` | 0.7 | km/h | 目标检测最低车速 |
| `fRctbObjWarningTTM` | 1.6 | s | 对象警告 TTM 阈值 |
| `fRctbObjDeWarningTTM` | 2.0 | s | 对象取消警告 TTM 阈值 |
| `fRctbObjWarningLowerDDCIOffSet` | -2.0 | m | 对象警告 DDCI 下限偏移 |
| `fRctbObjWarningLowerCDDCIOffSet` | -4.0 | m | 对象警告 C-DDCI 下限偏移 |
| `fRctbBrakeValue` | -4.0 | - | 标准制动请求值 |
| `fRctbHighSpeedBrakeValue` | -6.0 | - | 高速制动请求值 |
| `fRctbHoldValue` | -2.0 | - | 保持制动请求值 |
| `fRctbHoldTimeThresh` | 3.0 | s | 制动保持时间阈值 |
| `fRctbStopSpd` | 1.0 | km/h | 停止速度阈值 |
| `fRctbAEBActiveThresh` | 1.0 | - | AEB 激活阈值 |

## 5. 关键变量

| 变量名 | 类型 | 来源 | 含义 |
| :--- | :--- | :--- | :--- |
| `rctbSystemState` | `uint8_t` | `adasFunc.c` | RCTB 系统状态机当前状态 (0-6) |
| `bRctbDetectFlg` | `bool` | `adasFunc.c` | RCTB 目标检测标志，表示是否检测到威胁目标 |
| `bRctbLeftWarningFlg` | `bool` | `adasFunc.c` | 左侧 RCTB 报警标志 |
| `bRctbRightWarningFlg` | `bool` | `adasFunc.c` | 右侧 RCTB 报警标志 |
| `bRctbKeepBrakeFlg` | `bool` | `adasFunc.c` | 制动保持标志，用于控制制动释放逻辑 |
| `fRctbBrakeReqVal` | `float` | `adasFunc.c` | 当前制动请求值，输出给底盘 |
| `fRctbBrakeEventTime` | `float` | `adasFunc.c` | 制动事件发生时间，用于计时 |
| `fRctbHoldEventTime` | `float` | `adasFunc.c` | 制动保持事件时间 |
| `bRctbLeftKeepFlag` | `bool` | `adasFunc.c` | 左侧报警保持标志 (用于防抖动) |
| `bRctbRightKeepFlag` | `bool` | `adasFunc.c` | 右侧报警保持标志 (用于防抖动) |
| `bRctbLeftBuffer` | `uint8_t[]` | `adasFunc.c` | 左侧报警状态缓冲队列 |
| `bRctbRightBuffer` | `uint8_t[]` | `adasFunc.c` | 右侧报警状态缓冲队列 |

## 6. 输入信号
RCTB 功能依赖以下输入信号进行状态判断和威胁评估：

1.  **车辆状态**:
    *   `g_egoCarAddInfo.carSpd`: 自车车速 (km/h)。
    *   `g_egoCarAddInfo.actual_gear`: 当前档位 (6 或 7 代表 R 档)。
    *   `g_DTCCode.bBrakeNotReadyFlg`: 制动系统就绪状态。
2.  **系统配置与故障**:
    *   `adasEnable->bRCTBEnable`: RCTB 功能开关。
    *   `g_DTCCode.selfInspFlg`: 自检标志。
    *   `g_DTCCode.calibratingFlg`: 标定标志。
    *   `g_DTCCode.failureFlg`: 故障标志。
3.  **感知数据**:
    *   `objInfo->trcOutData`: 雷达跟踪目标列表 (位置、速度、ID 等)。
    *   `polygonLargerStruct* leftRctaRoi`, `rightRctaRoi`: 后方交叉交通感兴趣区域 (ROI) 多边形数据 (RCTB 复用 RCTA ROI 逻辑)。
4.  **时间**:
    *   系统运行时间 (用于 TTM 计算和保持时间计时)。

## 7. 输出信号
RCTB 功能向外部系统输出以下信号：

1.  **报警信号**:
    *   `adasWarning->bLeftRctbWarning`: 左侧 RCTB 报警 (0/1)。
    *   `adasWarning->bRightRctbWarning`: 右侧 RCTB 报警 (0/1)。
    *   `objInfo->trcOutData[i].objRctbWarningFlag`: 单个目标的 RCTB 报警标志。
2.  **制动控制信号**:
    *   `adasWarning->fBrakeValue`: 制动请求值 (负值表示制动)。
    *   `adasWarning->fBrakeEventTime`: 制动事件时间戳。
3.  **状态信号**:
    *   `adasWarning->rctbSystemState`: 当前系统状态 (0-6)。

## 8. 与其他功能的交互
1.  **RCTA (Rear Cross Traffic Alert)**:
    *   **状态机共享**: RCTA 和 RCTB 共用 `RctaRctbUpdateStatus` 函数进行系统状态更新，逻辑高度耦合。
    *   **ROI 复用**: `RearCrossTrafficAlertAndBrake` 函数参数中包含 `leftRctaRoi` 和 `rightRctaRoi`，表明 RCTB 直接使用 RCTA 计算出的感兴趣区域进行威胁判断。
    *   **报警联动**: 代码中存在 `bRctaLastWarningFlg` 等变量，暗示 RCTA 报警可能作为 RCTB 的前置条件或参考。
2.  **DTC (Diagnostic Trouble Code)**:
    *   依赖 DTC 模块提供的故障标志 (`failureFlg`)、标定标志 (`calibratingFlg`) 和自检标志 (`selfInspFlg`) 来决定功能是否可用。
3.  **底盘制动系统**:
    *   通过 `fRctbBrakeReqVal` 输出制动请求，依赖 `bBrakeNotReadyFlg` 确认制动系统可用性。
4.  **感知模块 (Perception)**:
    *   依赖 `objInfo` 获取雷达目标数据，并更新目标的 `objRctbWarningFlag` 属性。