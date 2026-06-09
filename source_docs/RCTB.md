# RCTB 功能分析

## 1. 功能概述
**RCTB (Rear Cross Traffic Braking)** 即后方交叉交通制动功能。该功能主要在车辆倒车时，检测车辆后方左右两侧横向移动的目标（如车辆、行人、自行车等）。当系统判断本车与横向目标存在碰撞风险且满足制动条件时，系统会首先触发报警（通常关联 RCTA），若驾驶员未采取制动措施且碰撞风险进一步加剧，系统将请求自动紧急制动（AEB）以减轻或避免碰撞。

从源码结构来看，RCTB 是 ADAS 套件中独立的一个功能模块（`AdasModelRCTB`），拥有独立的状态机、使能标志和报警/制动输出接口。

## 2. 状态机
根据 `adasWarningStruct` 中的定义，RCTB 功能遵循标准的 ADAS 状态机模型。

**状态定义 (`rctbSystemState`):**
*   **0 - None**: 未定义或初始未配置状态。
*   **1 - Init**: 初始化状态，系统正在加载参数或进行自检。
*   **2 - Standby**: 待机状态，系统已就绪，但当前驾驶场景不满足激活条件（例如车速过高、未挂倒挡、功能被手动关闭）。
*   **3 - Active**: 激活状态，系统正在实时监测后方交叉交通，具备触发报警和制动的能力。
*   **4 - Off**: 关闭状态，用户通过 HMI 手动关闭了该功能。
*   **5 - Failure**: 故障状态，传感器故障、数据异常或系统内部错误，功能不可用。
*   **6 - Passive**: 被动状态，可能指系统处于降级模式或等待特定条件恢复。

**状态转换逻辑推断:**
*   **None -> Init**: 系统上电或复位。
*   **Init -> Standby/Active/Failure**: 初始化完成后，根据使能标志 `bRCTBEnable` 和传感器健康状态决定进入待机、激活或故障。
*   **Standby <-> Active**:
    *   **Standby -> Active**: 满足激活条件（如：`bRCTBEnable == true`，挂入 R 挡，车速低于阈值，雷达视野正常）。
    *   **Active -> Standby**: 不满足激活条件（如：车速超过阈值，退出 R 挡，功能被临时抑制）。
*   **Active -> Off**: 用户手动关闭 `bRCTBEnable`。
*   **Any -> Failure**: 检测到传感器故障或严重数据异常。

## 3. 报警/制动逻辑
RCTB 的逻辑通常分为两个阶段：**预警 (Warning)** 和 **制动 (Braking)**。虽然源码片段主要展示了结构体定义，但结合变量命名和通用 ADAS 逻辑，推导如下：

1.  **目标筛选**:
    *   系统从感知层获取目标列表。
    *   筛选出位于后方交叉区域（FOV Crossing）的目标，参考变量 `isFOVCrossing`。
    *   排除静态障碍物或低速静止物体（除非特定配置），重点关注横向运动目标。

2.  **风险评估 (TTC/TTM 计算)**:
    *   计算本车与目标的碰撞时间 (TTC) 或到达时间 (TTM, `fTTM`)。
    *   计算交点位置 (`fInterX`, `fInterY`)，判断目标轨迹是否与本车倒车轨迹相交。

3.  **报警触发 (RCTA 联动)**:
    *   当 TTC 小于报警阈值时，设置 `objRctbWarningFlag` 或 `bLeft/RightRctbWarning`。
    *   通常 RCTB 的报警阶段会复用或触发 RCTA (Rear Cross Traffic Alert) 的报警信号 (`leftRctaFlag`/`rightRctaFlag`)，通过声音或视觉提示驾驶员。

4.  **制动触发 (RCTB 执行)**:
    *   在报警持续期间，若 TTC 进一步减小至制动阈值，且驾驶员未踩刹车（需结合制动踏板信号，虽未在片段中直接显示，但为必要输入）。
    *   设置制动请求标志。
    *   输出制动强度 `fBrakeValue` 和制动事件时间 `fBrakeEventTime`。
    *   更新 `bLeft/RightRctbWarning` 状态，可能区分“预警”和“制动请求”等级。

5.  **报警/制动取消**:
    *   目标移出危险区域（TTC 增大或目标离开 FOV）。
    *   驾驶员主动制动或转向避让。
    *   车辆退出倒挡或车速超过限制。

## 4. 关键阈值
虽然具体的数值未在头文件中直接给出（通常位于参数配置文件或 `.c` 文件中），但根据结构体中的变量，关键阈值包括：

*   **fTTM (Time To Meeting)**: 到达交点的时间阈值。
    *   `TTM_warn`: 触发报警的 TTM 阈值（例如 1.5s - 2.0s）。
    *   `TTM_brake`: 触发制动的 TTM 阈值（例如 0.8s - 1.2s）。
*   **fInterX / fInterY**: 预测交点的纵向和横向距离阈值，用于判断交点是否在本车可影响的范围内。
*   **Speed Thresholds**:
    *   `beginEgoVel`: 功能激活的最大本车速度（倒车速度通常 < 15 km/h）。
    *   目标速度阈值：忽略静止或极低速目标。
*   **Angle Thresholds**: 目标相对本车的角度范围，定义“交叉交通”的扇区。

## 5. 关键变量

| 变量名 | 类型 | 来源 | 含义 |
| :--- | :--- | :--- | :--- |
| `bRCTBEnable` | `bool` | `adasEnableStruct` | RCTB 功能使能标志，由 HMI 或系统配置控制。 |
| `rctbSystemState` | `uint8_t` | `adasWarningStruct` | RCTB 功能当前状态机状态 (0-6)。 |
| `bLeftRctbWarning` | `uint8_t` | `adasWarningStruct` | 左侧 RCTB 报警/制动状态 (0:正常, 1:预警, 2:制动请求/严重预警)。 |
| `bRightRctbWarning` | `uint8_t` | `adasWarningStruct` | 右侧 RCTB 报警/制动状态。 |
| `objRctbWarningFlag` | `int8_t` | `objOutEDRStruct` / `structDefine.h` | 单个目标对象的 RCTB 报警标志 (-1:始终正常, 0:正常, 1:报警)。 |
| `fBrakeValue` | `float` | `adasWarningStruct` | 请求的制动压力或减速度值，用于执行 AEB。 |
| `fBrakeEventTime` | `float` | `adasWarningStruct` | 制动事件发生的时间戳或持续时间。 |
| `fTTM` | `float` | `objOutEDRStruct` | 目标到达预测交点的时间 (Time To Meeting)，核心风险指标。 |
| `fInterX` | `float` | `objOutEDRStruct` | 预测交点的纵向距离。 |
| `fInterY` | `float` | `objOutEDRStruct` | 预测交点的横向距离。 |
| `isFOVCrossing` | `uint8_t` | `structDefine.h` | 目标是否处于视场角交叉区域，用于初步筛选潜在危险目标。 |
| `leftRctbFlag` / `rightRctbFlag` | `bool` | `perception_public_def.h` (L588-589) | 感知层输出的左右侧 RCTB 危险目标存在标志。 |

## 6. 输入信号
*   **车辆信号**:
    *   挡位信号 (Gear Position): 判断是否处于 R 挡。
    *   车速 (Ego Velocity): `beginEgoVel` 相关，判断是否在低速倒车范围。
    *   制动踏板状态 (Brake Pedal): 判断驾驶员是否已介入（虽未在头文件显式列出，但为制动逻辑必需）。
    *   转向角/转向信号: 辅助判断车辆运动趋势。
*   **感知信号**:
    *   目标列表 (Object List): 包含位置 (X, Y)、速度 (Vx, Vy)、类型 (`objType`)、ID (`objID`)。
    *   目标属性: `isFOVCrossing`, `ghostProb` (鬼影概率，用于过滤误检)。
    *   雷达状态: 干扰等级 (`stLvl`)，用于判断数据可靠性。
*   **配置信号**:
    *   `bRCTBEnable`: 功能开关。
    *   标定参数: 阈值配置。

## 7. 输出信号
*   **报警信号**:
    *   `bLeftRctbWarning` / `bRightRctbWarning`: 发送给 HMI 或声音报警模块，触发视觉/听觉警告。
    *   `leftRctaFlag` / `rightRctaFlag`: 可能同时激活 RCTA 报警，因为 RCTB 通常包含 RCTA 功能。
*   **制动请求信号**:
    *   `fBrakeValue`: 发送给底盘控制模块 (Chassis Control) 的制动请求值。
    *   `fBrakeEventTime`: 制动事件的时间信息。
*   **状态信号**:
    *   `rctbSystemState`: 发送给诊断系统或 HMI，显示功能状态。
*   **数据记录**:
    *   `objOutEDRStruct`: 包含 `objRctbWarningFlag` 等字段，用于 EDR (Event Data Recorder) 黑匣子记录事故前的关键数据。

## 8. 与其他功能的交互
*   **RCTA (Rear Cross Traffic Alert)**:
    *   **强耦合**: RCTB 通常建立在 RCTA 之上。当检测到风险时，先触发 RCTA 报警。如果驾驶员无反应且风险升级，再触发 RCTB 制动。
    *   变量 `leftRctaFlag`/`rightRctaFlag` 和 `leftRctbFlag`/`rightRctbFlag` 同时存在，表明两者可能并行运行或 RCTB 复用 RCTA 的检测结果。
*   **RCW (Rear Cross Warning / Rear Collision Warning)**:
    *   **区分**: RCW 通常指后方同向碰撞预警（如倒车时后方有车靠近），而 RCTB 指横向交叉。两者在目标筛选逻辑上互斥或互补。`bRCWEnable` 和 `bRCTBEnable` 是独立的。
*   **BSD/LCA**:
    *   **数据共享**: 使用相同的角雷达感知数据。BSD/LCA 关注侧方盲区，RCTB 关注后方交叉。在目标分类和跟踪算法上可能有共用模块。
*   **AEB (Autonomous Emergency Braking)**:
    *   **执行层**: RCTB 的制动请求最终由 AEB 系统执行。`fBrakeValue` 是 RCTB 与 AEB 执行器之间的接口。
*   **HMI (Human Machine Interface)**:
    *   接收 `rctbSystemState` 和报警标志，向驾驶员显示功能状态和警告信息。