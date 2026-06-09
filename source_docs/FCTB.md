# FCTB 功能分析

## 1. 功能概述
**FCTB (Front Cross Traffic Braking)**，即前方交叉交通制动辅助。该功能主要应用于车辆从停车位（如侧方停车或垂直停车）向前起步时，检测前方横向道路是否有来车（包括车辆、行人、自行车等）。当检测到潜在碰撞风险且驾驶员未采取制动措施时，系统会先发出警报（FCTA），若风险进一步加剧，则主动施加制动请求（FCTB）以避免或减轻碰撞。

根据提供的源码片段，FCTB 是 ADAS 套件中的一个独立功能模块，拥有独立的状态机、使能标志和报警/制动输出接口。

## 2. 状态机
根据 `perception_public_def.h` 中的定义，FCTB 功能遵循标准的 ADAS 功能状态机模型。

**状态定义 (`fctbSystemState`)**:
*   `0`: **None** (未定义/初始未激活)
*   `1`: **Init** (初始化中，正在进行传感器校准或系统自检)
*   `2`: **Standby** (待机，系统正常但未满足激活条件，如车速过低或挡位不对)
*   `3`: **Active** (激活，系统正在监控前方交叉交通，随时准备报警或制动)
*   `4`: **Off** (关闭，用户手动关闭或功能被禁用)
*   `5`: **Failure** (故障，传感器或算法异常)
*   `6`: **Passive** (被动模式，可能指仅报警不制动，或降级模式)

**状态转换逻辑推断**:
虽然源码未直接给出状态转换函数，但基于 ADAS 通用逻辑及变量定义：
1.  **None -> Init**: 系统上电，`bFCTBEnable` 为真，开始初始化。
2.  **Init -> Standby/Active**: 初始化完成。若满足激活条件（如挡位 D/R，车速 < 阈值），进入 Active；否则进入 Standby。
3.  **Standby <-> Active**: 根据车速、挡位、转向角等实时条件切换。
4.  **Active -> Off**: 用户通过 UI 关闭功能 (`bFCTBEnable` 变为 false)。
5.  **Any -> Failure**: 检测到雷达故障、通信超时或数据无效。

## 3. 报警/制动逻辑

### 3.1 触发条件
FCTB 的触发依赖于对前方交叉目标（Object）的感知和预测。

1.  **目标筛选**:
    *   目标必须位于前方交叉区域（由 `referPt` 或角度范围决定，通常对应 `Corner Front Left/Right` 雷达视角）。
    *   目标类型需为有效障碍物（车辆、行人等）。
    *   目标具有横向相对速度，且预测轨迹与本车路径相交。

2.  **报警阶段 (FCTA Warning)**:
    *   当预测的碰撞时间 (**TTC**) 小于报警阈值，或 **DDCI** (Distance to Collision Index) 超过阈值时。
    *   设置 `objFctaWarningFlag` 和 `objFctbWarningFlag` 为 `WarningFlag_Warning` (1)。
    *   输出 `bLeftFctaWarning` / `bRightFctaWarning` 为 1 (First Warning) 或 2 (Second Warning)。

3.  **制动阶段 (FCTB Braking)**:
    *   在报警基础上，若 TTC 进一步减小至制动阈值，或 DDCI 超过制动阈值。
    *   且驾驶员未踩下制动踏板（需结合制动踏板信号，源码中未直接显示，但为 FCTB 必要条件）。
    *   设置 `objFctbWarningFlag` 为 `WarningFlag_Warning`。
    *   输出 `bLeftFctbWarning` / `bRightFctbWarning` 为 1 或 2。
    *   计算并输出 `fBrakeValue` (制动压力/请求) 和 `fBrakeEventTime`。

### 3.2 取消条件
*   目标消失或移出危险区域。
*   TTC 增大至安全范围。
*   驾驶员介入（踩刹车或打方向）。
*   系统状态变为 Off 或 Failure。

## 4. 关键阈值
源码中未直接给出具体数值，但定义了用于判断的关键物理量变量，阈值通常配置在参数表中：

1.  **TTC (Time to Collision)**:
    *   `fTTC` (float): 碰撞时间。
    *   *推断*: 存在 `TTC_Alarm_Thresh` 和 `TTC_Brake_Thresh`。通常报警 TTC > 制动 TTC。
2.  **DDCI (Distance to Collision Index)**:
    *   `fDDCI` (float): 碰撞距离指数，综合了距离和速度的风险指标。
    *   *推断*: 存在 `DDCI_Alarm_Thresh` 和 `DDCI_Brake_Thresh`。
3.  **速度阈值**:
    *   `beginEgoVel` (int8_t): 自车起始速度阈值。FCTB 通常在自车低速（如 < 10-15 km/h）时激活。
    *   `velX`, `velY`: 目标的纵向和横向速度，用于计算 TTC 和轨迹预测。
4.  **距离阈值**:
    *   `minRange`, `maxRange`: 有效检测范围。
    *   `distX`, `distY`: 目标相对于自车的纵向和横向距离。

## 5. 关键变量

| 变量名 | 类型 | 来源 | 含义 |
| :--- | :--- | :--- | :--- |
| `bFCTBEnable` | bool | `adasEnableStruct` | FCTB 功能使能标志，由用户设置或系统逻辑控制。 |
| `fctbSystemState` | uint8_t | `adasWarningStruct` | FCTB 功能当前状态 (0-6)。 |
| `objFctbWarningFlag` | int8_t | `objOutEDRStruct` / `structDefine.h` | 单个目标的 FCTB 报警标志 (-1: 正常, 0: 无, 1: 报警)。 |
| `bLeftFctbWarning` | uint8_t | `adasWarningStruct` | 左侧 FCTB 报警输出 (0: 正常, 1: 一级报警, 2: 二级报警/制动)。 |
| `bRightFctbWarning` | uint8_t | `adasWarningStruct` | 右侧 FCTB 报警输出 (0: 正常, 1: 一级报警, 2: 二级报警/制动)。 |
| `fBrakeValue` | float | `adasWarningStruct` | 制动请求值，用于控制 ESP/ABS 执行器。 |
| `fBrakeEventTime` | float | `adasWarningStruct` | 制动事件发生的时间戳或持续时间。 |
| `fTTC` | float | `objOutEDRStruct` | 目标与本车的预计碰撞时间。 |
| `fDDCI` | float | `objOutEDRStruct` | 目标与本车的碰撞距离指数。 |
| `velX`, `velY` | float | `objOutEDRStruct` | 目标的纵向和横向速度，用于运动学预测。 |
| `beginEgoVel` | int8_t | `structDefine.h` | 自车触发 FCTB 的起始速度阈值。 |
| `referPt` | uint8_t | `objOutEDRStruct` | 参考点，用于确定目标相对于车辆的位置（如 3=右前, 7=左后等，FCTB 主要关注前角雷达）。 |

## 6. 输入信号

1.  **系统配置**:
    *   `bFCTBEnable`: 功能使能。
    *   `beginEgoVel`: 自车速度阈值配置。
2.  **自车状态** (隐含，需从其他模块获取):
    *   自车速度 (`EgoVel`)。
    *   自车挡位 (`Gear`)。
    *   自车转向角 (`SteeringAngle`)。
    *   制动踏板状态 (`BrakePedal`)。
3.  **感知数据** (`objOutEDRStruct`):
    *   `referPt`: 目标位置区域。
    *   `velX`, `velY`: 目标速度。
    *   `distX`, `distY`: 目标距离。
    *   `fTTC`, `fDDCI`: 风险指标。
    *   `lifeCycle`: 目标生命周期，用于过滤瞬时杂波。

## 7. 输出信号

1.  **状态输出**:
    *   `fctbSystemState`: 功能状态，用于 HMI 显示。
2.  **报警输出**:
    *   `bLeftFctaWarning`, `bRightFctaWarning`: 前方交叉交通警报 (FCTA) 标志。
    *   `bLeftFctbWarning`, `bRightFctbWarning`: 前方交叉交通制动 (FCTB) 标志。
3.  **控制输出**:
    *   `fBrakeValue`: 制动压力请求，发送给底盘控制器 (ESP/ABS)。
    *   `fBrakeEventTime`: 制动事件时间信息。

## 8. 与其他功能的交互

1.  **FCTA (Front Cross Traffic Alert)**:
    *   FCTB 是 FCTA 的升级功能。通常先触发 FCTA 报警 (`bLeftFctaWarning`)，若风险持续增加且无驾驶员干预，则触发 FCTB 制动 (`bLeftFctbWarning`)。
    *   两者共享相同的感知目标和风险计算逻辑 (`fTTC`, `fDDCI`)。

2.  **BSD/LCA (Blind Spot Detection / Lane Change Assist)**:
    *   虽然 BSD/LCA 主要关注侧后方，但部分系统可能在低速泊车场景下复用角雷达数据。
    *   状态机独立 (`bsdSystemState` vs `fctbSystemState`)，但可能共享雷达底层数据 (`algoExtraStruct`)。

3.  **RCTA/RCTB (Rear Cross Traffic Alert/Braking)**:
    *   逻辑对称，但方向相反。RCTA/RCTB 关注后方交叉交通，FCTA/FCTB 关注前方。
    *   在代码结构中，它们有独立的使能标志 (`bRCTAEnable`, `bFCTAEnable`) 和输出标志 (`bLeftRctaWarning`, `bLeftFctaWarning`)。

4.  **DOW (Door Open Warning)**:
    *   当车辆停稳且车门打开时，DOW 激活。FCTB 通常在车辆起步阶段激活。两者在时间上可能互斥或互补，取决于具体场景定义。

5.  **RCW (Rear Cross Warning)**:
    *   RCW 通常指后方横向预警，与 FCTB 方向不同，但可能共享部分雷达硬件资源。