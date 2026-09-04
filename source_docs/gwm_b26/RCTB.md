# RCTB 功能分析

## 1. 功能概述
**RCTB (Rear Cross Traffic Braking)**，即后方交叉交通制动，是 ADAS 系统中的一项主动安全功能。当车辆处于倒车状态（Reverse Gear）且车速较低时，若检测到车辆后方左右两侧存在横向移动的障碍物（如车辆、行人、自行车等），系统首先通过 RCTA（警报）进行提示；若驾驶员未采取制动措施且碰撞风险极高，RCTB 功能将介入，通过 ESP/ABS 系统施加紧急制动，以避免或减轻碰撞事故。

根据提供的源码片段，RCTB 与 RCTA 紧密耦合，共享目标检测逻辑，但在报警等级和执行动作上有所区分。

## 2. 状态机
根据 `adasWarningStruct` 中的定义，RCTB 功能拥有独立的状态机 `rctbSystemState`。

**状态定义 (`uint8_t rctbSystemState`):**
*   **0 - None**: 功能未初始化或未激活。
*   **1 - Init**: 初始化阶段，系统正在加载参数或进行自检。
*   **2 - Standby**: 待机状态。功能已就绪，但当前驾驶场景不满足激活条件（例如：未挂倒挡、车速过高、传感器受限）。
*   **3 - Active**: 激活状态。满足所有前置条件（倒挡、低速、传感器正常），系统正在实时监测后方交叉目标。
*   **4 - Off**: 功能关闭。用户手动关闭或系统配置禁用。
*   **5 - Failure**: 故障状态。传感器故障、通信错误或内部逻辑错误。
*   **6 - Passive**: 被动状态。通常指系统检测到潜在风险但因某些限制条件（如驾驶员强干预）而未执行主动制动，或处于降级运行模式。

**状态转换逻辑推断:**
*   **None -> Init**: 上电初始化。
*   **Init -> Standby**: 初始化完成，等待驾驶场景。
*   **Standby <-> Active**:
    *   **Standby -> Active**: 挂入倒挡 (Gear=R) 且 车速 < 阈值 (通常 < 10-15 km/h) 且 `bRCTBEnable` 为真。
    *   **Active -> Standby**: 退出倒挡 或 车速 > 阈值 或 功能被禁用。
*   **Active -> Failure**: 检测到传感器故障 (`stLvl` 干扰过高或 `ghostProb` 异常等)。
*   **Active -> Off**: 用户通过 HMI 关闭功能 (`bRCTBEnable = false`)。

## 3. 报警/制动逻辑

### 3.1 目标筛选与预警 (RCTA 阶段)
在 RCTB 介入前，通常先触发 RCTA 报警。
*   **触发条件**:
    1.  系统状态为 `Active`。
    2.  检测到后方交叉目标 (`objType` 有效，`referPt` 指向后方角落)。
    3.  目标满足 RCTA 的几何和运动学阈值（距离、角度、相对速度）。
    4.  `objRctaWarningFlag` 变为 `WarningFlag_Warning (1)`。
    5.  输出 `bLeftRctaWarning` / `bRightRctaWarning`。

### 3.2 制动介入 (RCTB 阶段)
当 RCTA 报警持续且风险升级时，RCTB 逻辑介入。
*   **触发条件**:
    1.  RCTA 报警已激活 (`bLeftRctaWarning` 或 `bRightRctaWarning` 非 0)。
    2.  目标满足更严格的 RCTB 阈值（更短的距离、更小的 TTC 或 TTM）。
    3.  驾驶员未踩下制动踏板（或制动力度不足，需结合未提供的踏板信号判断，但源码中有 `fBrakeValue` 输出）。
    4.  `objRctbWarningFlag` 变为 `WarningFlag_Warning (1)`。
    5.  系统状态允许制动执行。
*   **执行动作**:
    *   设置 `bLeftRctbWarning` / `bRightRctbWarning` 为警告状态。
    *   输出制动请求 `fBrakeValue` (制动压力/力度) 和 `fBrakeEventTime` (制动触发时间/持续时间)。

### 3.3 报警取消
*   **条件**:
    1.  目标离开检测区域 (`isFOVCrossing` 状态变化或目标消失)。
    2.  目标距离变远，不再满足报警阈值。
    3.  车辆退出倒挡或车速升高，功能状态切换为 `Standby` 或 `Off`。
    4.  `objRctbWarningFlag` 重置为 `WarningFlag_Normal (0)` 或 `WarningFlag_AlwaysNormal (-1)`。

## 4. 关键阈值
虽然源码片段中未直接给出具体的数值常量，但根据结构体定义和 ADAS 通用标准，RCTB 依赖以下关键阈值变量：

1.  **fTTM (Time To Maximum / Time To Merge)**: `objOutEDRStruct` 中的 `fTTM`。这是 RCTA/RCTB 的核心判断依据。
    *   *RCTA 阈值*: 通常 TTM < 3.0s ~ 4.0s。
    *   *RCTB 阈值*: 通常 TTM < 1.5s ~ 2.0s (更紧急)。
2.  **fDDCI (Distance To Collision Intersection)**: `objOutEDRStruct` 中的 `fDDCI`。预测碰撞点到本车的距离。
    *   RCTB 通常要求 fDDCI 小于车辆长度的一定比例或固定安全距离（如 < 2.0m）。
3.  **fIntAng (Intersection Angle)**: `objOutEDRStruct` 中的 `fIntAng`。目标与本车路径的夹角，用于判断是否为“交叉”交通。
4.  **fInterX / fInterY**: 预测碰撞点的纵向和横向坐标，用于确认碰撞点是否在本车车身范围内。
5.  **车速阈值**: 虽然未在结构体中直接体现为阈值变量，但 `beginEgoVel` 和系统状态机隐含了倒车速度限制（通常 < 10 km/h 或 < 15 km/h）。

## 5. 关键变量

| 变量名 | 类型 | 来源 | 含义 |
| :--- | :--- | :--- | :--- |
| `bRCTBEnable` | `bool` | `adasEnableStruct` | RCTB 功能使能标志，由用户设置或系统配置决定。 |
| `rctbSystemState` | `uint8_t` | `adasWarningStruct` | RCTB 功能当前状态机状态 (0-6)。 |
| `objRctbWarningFlag` | `int8_t` | `objOutEDRStruct` / `structDefine` | 单个目标的 RCTB 报警标志。-1: 始终正常, 0: 正常, 1: 报警。 |
| `bLeftRctbWarning` | `uint8_t` | `adasWarningStruct` | 左侧 RCTB 系统级报警输出。0: 正常, 1: 一级报警, 2: 二级报警/制动。 |
| `bRightRctbWarning` | `uint8_t` | `adasWarningStruct` | 右侧 RCTB 系统级报警输出。0: 正常, 1: 一级报警, 2: 二级报警/制动。 |
| `fBrakeValue` | `float` | `adasWarningStruct` | 制动请求值，发送给底盘执行机构的制动压力或减速度请求。 |
| `fBrakeEventTime` | `float` | `adasWarningStruct` | 制动事件的时间戳或持续时间，用于记录或同步。 |
| `fTTM` | `float` | `objOutEDRStruct` | Time To Maximum/Intersection，预测到达最大接近距离或碰撞点的时间，核心触发阈值。 |
| `fDDCI` | `float` | `objOutEDRStruct` | Distance To Collision Intersection，预测碰撞距离。 |
| `isFOVCrossing` | `uint8_t` | `structDefine` | 目标视野穿越状态，用于判断目标是否正在进入或离开雷达视野，辅助过滤误报。 |
| `referPt` | `uint8_t` | `perception_public_def` | 参考点，5/7 分别代表右后角和左后角，用于确定目标相对于本车的位置。 |

## 6. 输入信号
1.  **功能使能信号**: `bRCTBEnable` (来自 HMI 或配置)。
2.  **车辆状态信号** (隐含，通过状态机判断):
    *   挡位信号 (Gear Signal): 必须为 Reverse (R)。
    *   车速信号 (Ego Velocity): 用于判断是否处于低速倒车状态。
    *   制动踏板状态 (Brake Pedal): 用于判断驾驶员是否已主动制动（防冲突）。
3.  **感知目标数据** (`objOutEDRStruct` 或类似结构):
    *   `objType`: 目标类型 (车、人、非机动车)。
    *   `referPt`: 目标参考点位置。
    *   `fTTM`, `fDDCI`, `fIntAng`: 预测碰撞参数。
    *   `objRctaWarningFlag`: 上游 RCTA 的报警状态，通常 RCTB 在 RCTA 之后触发。
    *   `isFOVCrossing`: 目标运动轨迹状态。
    *   `ghostProb`: 鬼影概率，用于过滤虚假目标。

## 7. 输出信号
1.  **系统状态**: `rctbSystemState` (供诊断或 HMI 显示功能状态)。
2.  **报警标志**:
    *   `bLeftRctbWarning`: 左侧 RCTB 报警等级。
    *   `bRightRctbWarning`: 右侧 RCTB 报警等级。
3.  **制动请求**:
    *   `fBrakeValue`: 具体的制动控制指令值。
    *   `fBrakeEventTime`: 制动事件时间信息。
4.  **EDR 记录数据**: `objRctbWarningFlag` 等变量会被记录到 EDR (Event Data Recorder) 中，用于事故回溯。

## 8. 与其他功能的交互
1.  **与 RCTA (Rear Cross Traffic Alert) 的交互**:
    *   **层级关系**: RCTA 是 RCTB 的前置条件。通常逻辑为：先触发 RCTA 声光报警 -> 若风险继续增加且驾驶员无反应 -> 触发 RCTB 制动。
    *   **数据共享**: 两者共享 `objRctaWarningFlag` 和 `objRctbWarningFlag` 的目标级判断逻辑，以及 `fTTM`, `fDDCI` 等预测参数。
2.  **与 BSD (Blind Spot Detection) 的交互**:
    *   **场景区分**: BSD 主要在行车时工作，RCTB 在倒车时工作。两者在后侧方区域有重叠，但通过挡位和车速信号进行逻辑隔离。
    *   **目标融合**: 底层感知层可能共用同一套目标跟踪列表，但 ADAS 功能层根据 `referPt` 和车速进行分流处理。
3.  **与 RCW (Rear Cross Warning / Rear Collision Warning) 的交互**:
    *   **方向区分**: RCW 通常指后方同向追尾预警（纵向），而 RCTB 指后方横向交叉预警（横向）。两者通过目标的相对速度矢量和角度 (`fIntAng`) 进行区分。
4.  **与 AEB (Autonomous Emergency Braking) 的交互**:
    *   **优先级**: RCTB 可视为倒车场景下的 AEB。若系统同时支持倒车 AEB 和 RCTB，需定义优先级，通常 RCTB 是倒车 AEB 的一种特定实现或子集。
5.  **与 ESP/ABS 底盘系统的交互**:
    *   RCTB 输出的 `fBrakeValue` 最终通过 CAN/LIN 总线发送给底盘域控制器，由 ESP 执行实际制动。