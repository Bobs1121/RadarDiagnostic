# FCTB 功能分析

## 1. 功能概述
**FCTB (Front Cross Traffic Braking)**，即前方交叉交通制动辅助。该功能主要应用于车辆从停车位（如侧方停车或垂直停车位）向前驶出时。当角雷达（通常是前左或前右雷达）检测到前方横向道路上有车辆、行人或其他障碍物以较高速度接近，且存在碰撞风险时，系统会首先发出警报（FCTA），若驾驶员未采取制动措施且碰撞不可避免，系统将主动施加制动请求，以避免或减轻碰撞。

在提供的代码结构中，FCTB 是 ADAS 模型的一部分 (`AdasModelFCTB = 7U`)，其状态独立管理，并与 FCTA（警报）紧密耦合。

## 2. 状态机
根据 `adasWarningStruct` 中的定义，FCTB 拥有独立的状态机 `fctbSystemState`。

**状态定义:**
*   **0 - None**: 未初始化或未启用。
*   **1 - Init**: 初始化阶段，正在加载参数或等待传感器就绪。
*   **2 - Standby**: 待机状态。功能已启用，但当前工况不满足激活条件（例如：车辆未挂倒挡/前进挡，或车速过高/过低，或雷达信号质量不足）。
*   **3 - Active**: 激活状态。功能正在运行，持续监测前方交叉交通目标。
*   **4 - Off**: 功能关闭。用户手动关闭或系统强制关闭。
*   **5 - Failure**: 故障状态。雷达硬件故障、信号丢失或算法内部错误。
*   **6 - Passive**: 被动状态。可能指传感器受限（如脏污、遮挡）或处于降级模式，功能受限但仍部分工作。

**状态转换条件 (推断):**
*   **None -> Init**: 上电或 EOL 测试开始。
*   **Init -> Standby**: 初始化完成，等待使能信号 (`bFCTBEnable`)。
*   **Standby -> Active**:
    *   `bFCTBEnable` 为 True。
    *   车辆状态满足激活条件（通常：车速 < 阈值，如 10-15 km/h；档位为 R 或 D/P 且准备驶出；方向盘转角或转向信号指示驶出意图）。
    *   雷达数据有效。
*   **Active -> Standby**:
    *   车速超过阈值。
    *   驾驶员干预（如大幅转动方向盘或踩油门）。
    *   功能超时或目标丢失。
*   **Any -> Failure**: 检测到内部错误码或通信故障。
*   **Failure -> None/Init**: 故障清除或重启。

## 3. 报警/制动逻辑

FCTB 的逻辑通常分为两个阶段：**预警 (FCTA)** 和 **制动 (FCTB)**。

### 3.1 预警阶段 (FCTA Trigger)
虽然 FCTB 是制动功能，但它依赖于 FCTA 的预警逻辑。
*   **触发条件**:
    1.  系统处于 `Active` 状态。
    2.  检测到有效目标 (`objOutEDRStruct`)。
    3.  目标位于前方交叉区域（角度和距离在有效范围内）。
    4.  **TTC (Time To Collision)** 小于预警阈值 (`fTTC` 或相关配置参数)。
    5.  **DDCI (Dynamic Distance Collision Index)** 或相对速度满足碰撞风险条件。
    6.  目标被标记为 `objFctaWarningFlag = WarningFlag_Warning (1)`。
*   **输出**: 设置 `bLeftFctaWarning` 或 `bRightFctaWarning` 为 1 (First Warning) 或 2 (Second Warning)。

### 3.2 制动阶段 (FCTB Trigger)
*   **触发条件**:
    1.  FCTA 预警已激活（通常需持续一定时间或达到更高危险等级）。
    2.  **TTC** 进一步减小，低于制动触发阈值。
    3.  驾驶员未采取制动措施（制动踏板信号为 False）。
    4.  碰撞概率高，且制动可以有效避免碰撞。
    5.  目标被标记为 `objFctbWarningFlag = WarningFlag_Warning (1)`。
*   **输出**:
    1.  设置 `bLeftFctbWarning` 或 `bRightFctbWarning` 为 1。
    2.  输出制动请求值 `fBrakeValue`。
    3.  记录制动事件时间 `fBrakeEventTime`。

### 3.3 取消逻辑 (Reset)
*   **条件**:
    1.  目标消失 (`lifeCycle` 结束或信号丢失)。
    2.  目标移出危险区域（距离变远或角度偏离）。
    3.  TTC 大于安全阈值。
    4.  驾驶员主动制动或转向避让。
    5.  系统状态退出 `Active`。
*   **动作**:
    1.  `objFctaWarningFlag` 和 `objFctbWarningFlag` 重置为 `WarningFlag_Normal (0)` 或 `WarningFlag_AlwaysNormal (-1)`。
    2.  `bLeft/RightFctaWarning` 和 `bLeft/RightFctbWarning` 重置为 0。
    3.  `fBrakeValue` 归零。

## 4. 关键阈值
*注意：具体数值通常在标定文件（.csv/.bin）中，源码中仅定义了变量名。以下是基于变量名的逻辑阈值分析。*

| 阈值类型 | 变量名 | 说明 |
| :--- | :--- | :--- |
| **TTC (碰撞时间)** | `fTTC` | 触发 FCTA 和 FCTB 的核心指标。通常 FCTA TTC > FCTB TTC。 |
| **DDCI (动态距离碰撞指数)** | `fDDCI` | 综合距离和速度的碰撞风险指标。 |
| **纵向距离** | `distX`, `minRange`, `maxRange` | 目标在雷达坐标系下的纵向距离。用于过滤过近或过远的目标。 |
| **横向距离** | `distY`, `fInterY` | 目标在雷达坐标系下的横向距离。用于判断是否在同车道或相邻车道。 |
| **纵向速度** | `velX`, `velAbsX` | 目标相对于自车的纵向速度。用于计算 TTC。 |
| **横向速度** | `velY`, `velAbsY` | 目标相对于自车的横向速度。用于判断交叉交通特性。 |
| **角度** | `fIntAng` | 目标入射角度。FCTB 通常关注接近 90 度的横向目标。 |
| **TTM (Time To Max)** | `fTTM` | 可能指达到最大接近距离的时间，用于预测轨迹。 |
| **自车速度** | `beginEgoVel` / `beginVel` | 激活 FCTB 的自车速度上限（通常 < 15 km/h）。 |

## 5. 关键变量

| 变量名 | 类型 | 来源 | 含义 |
| :--- | :--- | :--- | :--- |
| `bFCTBEnable` | `bool` | `adasEnableStruct` | FCTB 功能使能标志。由用户设置或系统自动管理。 |
| `fctbSystemState` | `uint8_t` | `adasWarningStruct` | FCTB 功能当前状态机状态 (0-6)。 |
| `objFctbWarningFlag` | `int8_t` | `objOutEDRStruct` | 单个目标的 FCTB 报警标志。-1: 正常, 0: 无报警, 1: 报警。 |
| `objFctaWarningFlag` | `int8_t` | `objOutEDRStruct` | 单个目标的 FCTA 报警标志。FCTB 的前置条件。 |
| `bLeftFctbWarning` | `uint8_t` | `adasWarningStruct` | 左侧 FCTB 系统级报警标志。0: 正常, 1: 一级报警, 2: 二级报警/制动。 |
| `bRightFctbWarning` | `uint8_t` | `adasWarningStruct` | 右侧 FCTB 系统级报警标志。 |
| `fBrakeValue` | `float` | `adasWarningStruct` | 制动请求值。0 表示无制动，正值表示制动强度。 |
| `fBrakeEventTime` | `float` | `adasWarningStruct` | 制动事件发生的时间戳或持续时间。 |
| `fTTC` | `float` | `objOutEDRStruct` | 目标与自车的碰撞时间。核心决策变量。 |
| `fDDCI` | `float` | `objOutEDRStruct` | 动态距离碰撞指数。辅助决策变量。 |
| `velX`, `velY` | `float` | `objOutEDRStruct` | 目标在雷达坐标系下的纵向和横向速度。 |
| `distX`, `distY` | `float` | `objOutEDRStruct` | 目标在雷达坐标系下的纵向和横向距离。 |
| `referPt` | `uint8_t` | `objOutEDRStruct` | 雷达参考点位置。1/2: 前左/前右, 7/8: 后左/后右。FCTB 主要关注 1, 2。 |

## 6. 输入信号

1.  **使能信号**:
    *   `bFCTBEnable`: 功能开关。
    *   `bFCTAEnable`: 通常 FCTB 依赖 FCTA 的使能。
2.  **车辆状态信号** (隐含在激活逻辑中，虽未在片段直接显示，但为 ADAS 标准输入):
    *   自车速度 (`egoVel`)。
    *   档位信息 (Gear: P, R, N, D)。
    *   制动踏板状态 (Brake Pedal)。
    *   转向信号 (Turn Signal)。
    *   方向盘转角 (Steering Angle)。
3.  **感知数据** (`objOutEDRStruct`):
    *   目标列表：每个目标的 `distX`, `distY`, `velX`, `velY`, `fTTC`, `fDDCI`, `referPt`。
    *   目标有效性：`lifeCycle`, `isCoveredFlg`。
4.  **环境/校准数据**:
    *   `InCalibState`: 雷达校准状态。
    *   `minRange`, `maxRange`: 有效检测范围。

## 7. 输出信号

1.  **报警输出**:
    *   `bLeftFctaWarning`, `bRightFctaWarning`: 前方交叉交通警报 (视觉/听觉)。
    *   `bLeftFctbWarning`, `bRightFctbWarning`: 前方交叉交通制动警报 (通常伴随更强烈的提示)。
2.  **制动请求**:
    *   `fBrakeValue`: 发送给底盘控制器 (ESP/ABS) 的制动压力或减速度请求。
    *   `fBrakeEventTime`: 制动事件的时间信息，用于日志和诊断。
3.  **状态输出**:
    *   `fctbSystemState`: 当前功能状态，用于 HMI 显示 (如 "FCTB Ready", "FCTB Off", "FCTB Fault")。
4.  **目标级标志**:
    *   `objFctbWarningFlag`: 用于调试和高级算法融合，标识哪个具体目标触发了制动。

## 8. 与其他功能的交互

1.  **FCTA (Front Cross Traffic Alert)**:
    *   **强依赖**: FCTB 是 FCTA 的升级功能。通常先触发 FCTA 报警，若危险升级且驾驶员无反应，再触发 FCTB 制动。
    *   **共享数据**: 两者使用相同的感知目标数据 (`objOutEDRStruct`) 和阈值计算逻辑 (`fTTC`, `fDDCI`)。
2.  **RCTA/RCTB (Rear Cross Traffic)**:
    *   **对称性**: 逻辑类似，但针对后方雷达。FCTB 关注前左/前右雷达，RCTB 关注后左/后右雷达。
    *   **互斥/优先级**: 在某些系统中，如果同时检测到前后交叉交通，可能需要优先级仲裁，但通常 FCTB 和 RCTB 不会同时激活，因为车辆不能同时向前和向后运动。
3.  **AEB (Autonomous Emergency Braking)**:
    *   **区分**: FCTB 是 AEB 的一种特殊场景（交叉交通）。如果系统有通用的 AEB 模块，FCTB 的制动请求可能会汇入 AEB 的主制动请求通道，或者 FCTB 是独立于纵向 AEB 的专用功能。
4.  **BSD/LCA**:
    *   **无直接交互**: BSD/LCA 主要关注侧方盲区，而 FCTB 关注前方横向。但在数据融合层面，它们可能共享目标跟踪算法。
5.  **DOW (Door Open Warning)**:
    *   **场景互补**: DOW 在车辆静止开门时工作，FCTB 在车辆驶出停车位时工作。两者都涉及交叉交通，但触发时机不同。

**总结**: FCTB 是一个基于雷达感知、结合车辆状态和驾驶员行为的主动安全功能。其核心在于通过 `fTTC` 和 `fDDCI` 精确判断碰撞风险，并在适当时机从预警过渡到主动制动，以保护车辆和行人。