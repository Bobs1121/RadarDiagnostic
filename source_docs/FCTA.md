# FCTA 功能分析

## 1. 功能概述
**FCTA (Front Cross Traffic Alert)** 即前方交叉交通警报。该功能主要应用于车辆低速行驶或静止状态（如从停车位驶出、通过狭窄路口或环岛时），利用前左（Front Left）和前右（Front Right）角雷达探测横向穿过的车辆或行人。当检测到有目标以一定速度横向穿过本车前方路径，且存在碰撞风险时，系统向驾驶员发出视觉或听觉警告，提示潜在危险。

根据代码定义，FCTA 属于 ADAS 功能模型之一 (`AdasModelFCTA = 6U`)，其核心逻辑依赖于对目标在 FCTA 感兴趣区域（ROI）内的轨迹预测、相对速度判断以及时间阈值（TTC/TTM）的计算。

## 2. 状态机
根据 `adasWarningStruct` 中的定义，FCTA 系统状态遵循标准的 ADAS 状态机模型：

*   **状态定义**:
    *   `0`: **None** (未定义/初始)
    *   `1`: **Init** (初始化中，雷达自检或参数加载)
    *   `2`: **Standby** (待机，功能使能但条件不满足，如车速过高或传感器受限)
    *   `3`: **Active** (激活，功能正常工作，持续监测 ROI 区域)
    *   `4`: **Off** (关闭，用户手动关闭或系统强制关闭)
    *   `5`: **Failure** (故障，雷达硬件或软件错误)
    *   `6`: **Passive** (被动/降级，部分功能受限但仍运行)

*   **状态转换条件 (推断)**:
    *   `None/Init` -> `Standby`: 系统自检通过，`bFCTAEnable` 为真。
    *   `Standby` -> `Active`: 满足激活条件（通常包括：车速低于阈值如 30-40km/h，挡位为 D/R/P，无严重故障，雷达视野无遮挡）。
    *   `Active` -> `Standby`: 不满足激活条件（如车速升高超过阈值，或进入隧道等干扰环境）。
    *   `Active/Standby` -> `Failure`: 检测到内部错误（如 `InCalibState` 异常，信号丢失）。
    *   `Any` -> `Off`: 用户通过 HMI 关闭 `bFCTAEnable`。

## 3. 报警/制动逻辑
FCTA 仅提供警报（Alert），不涉及自动制动（制动由 FCTB 负责，但两者逻辑紧密相关）。

*   **触发报警条件**:
    1.  **功能使能**: `bFCTAEnable` 为 `true`。
    2.  **系统状态**: `fctaSystemState` 为 `Active` (3)。
    3.  **目标有效性**: 在 `leftFctaRoi` 或 `rightFctaRoi` 内检测到有效目标。
    4.  **运动特征**: 目标具有显著的横向速度（`velY` 或 `velAbsY`），表明其正在横向穿越。
    5.  **风险判断**:
        *   目标的预测轨迹与本车路径相交。
        *   时间阈值满足报警条件：通常基于 `fTTM` (Time To Merge/Cross) 或 `fTTC` (Time To Collision)。代码中定义了 `fTTM` 和 `fDDCI` (Distance to Decision Critical Intersection) 作为关键判断参数。
        *   目标处于 ROI 范围内且距离小于安全阈值。
    6.  **滤波/迟滞**: 使用 `KEEPWARNINGFRM` (3帧) 或 `LOWSPEEDKEEPWARNINGFRM` (6帧) 进行防抖处理，确保持续 N 帧满足条件才置位报警标志。

*   **取消报警条件**:
    1.  目标移出 ROI 区域。
    2.  目标速度变为 0 或方向改变（不再构成横向穿越威胁）。
    3.  本车启动并加速离开潜在碰撞区域。
    4.  连续 N 帧不满足报警条件（迟滞解除）。
    5.  系统状态变为 `Standby`, `Off`, 或 `Failure`。

*   **报警标志输出**:
    *   `bLeftFctaWarning`: 左侧 FCTA 报警状态 (0: Normal, 1: First Warning, 2: Second Warning - *注：FCTA通常只有单一警告级别，但结构体预留了分级字段，具体取决于标定策略，通常 FCTA 为单一视觉/声音警告*)。
    *   `bRightFctaWarning`: 右侧 FCTA 报警状态。

## 4. 关键阈值
基于 `paraDefine.h` 和 `perception_public_def.h` 的分析：

*   **ROI 定义**:
    *   `leftFctaRoi`, `rightFctaRoi`: 多边形区域 (`polygonLargerStruct`)，定义了前方左右侧的探测范围。
*   **时间/距离阈值**:
    *   `fTTM` (Time To Merge/Cross): 目标到达交叉点所需时间。若 `fTTM` 小于设定阈值（如 1.5s - 2.5s，具体值未在宏中直接给出，但存在于 `objOutEDRStruct` 中），触发报警。
    *   `fDDCI` (Distance to Decision Critical Intersection): 目标距离关键交叉点的距离。
    *   `fInterX`, `fInterY`: 预测的交叉点坐标。
*   **速度/角度阈值**:
    *   `YAWRATETHERESHOLD` (3.0f): 可能用于判断目标或本车的航向角变化率，排除静止或直线行驶的非威胁目标。
    *   `velAbsY` / `velY`: 横向速度必须大于最小阈值（通常为 2-5 km/h），以区分静止障碍物和移动威胁。
*   **报警保持帧数**:
    *   `KEEPWARNINGFRM`: 3 帧 (正常速度下报警保持/触发迟滞)。
    *   `LOWSPEEDKEEPWARNINGFRM`: 6 帧 (低速下更长的迟滞，防止误报)。

## 5. 关键变量

| 变量名 | 类型 | 来源 | 含义 |
| :--- | :--- | :--- | :--- |
| `bFCTAEnable` | `bool` | `adasEnableStruct` | FCTA 功能使能开关，由 HMI 或系统配置控制。 |
| `fctaSystemState` | `uint8_t` | `adasWarningStruct` | FCTA 系统当前状态 (0-6)，决定功能是否处于 Active。 |
| `leftFctaRoi` / `rightFctaRoi` | `polygonLargerStruct` | `adasROIStruct` | 左侧/右侧 FCTA 感兴趣区域的多边形顶点坐标。 |
| `bLeftFctaWarning` / `bRightFctaWarning` | `uint8_t` | `adasWarningStruct` | 左/右侧 FCTA 报警输出标志 (0:无, 1:报警)。 |
| `objFctaWarningFlag` | `int8_t` | `objOutEDRStruct` | 单个目标的 FCTA 报警标志 (-1:始终正常, 0:正常, 1:报警)。 |
| `fTTM` | `float` | `objOutEDRStruct` | Time To Merge/Cross，目标到达交叉点的时间，核心风险指标。 |
| `fDDCI` | `float` | `objOutEDRStruct` | Distance to Decision Critical Intersection，目标距交叉点距离。 |
| `velY` / `velAbsY` | `float` | `objOutEDRStruct` | 目标的横向速度分量，用于判断是否为横向穿越目标。 |
| `fInterX` / `fInterY` | `float` | `objOutEDRStruct` | 预测的本车与目标轨迹交叉点坐标。 |
| `AdasModelFCTA` | `enum` | `paraDefine.h` | FCTA 功能模型枚举值 (6U)，用于功能路由。 |

## 6. 输入信号
1.  **车辆状态**:
    *   车速 (`egoVel`)：FCTA 通常在低速（< 30-40 km/h）激活。
    *   挡位信息：通常在 D 挡或 R 挡（若支持前方倒车辅助）激活。
    *   转向角/航向角 (`yawAng`)：用于坐标变换和 ROI 动态调整。
2.  **雷达感知数据**:
    *   目标列表 (`objOutEDRStruct`)：包含距离 (`distX`, `distY`)、速度 (`velX`, `velY`)、航向角、ID、生命周期 (`lifeCycle`)。
    *   雷达位置信息 (`RadarPos_FrontLeft`, `RadarPos_FrontRight`)。
3.  **功能配置**:
    *   `bFCTAEnable`：功能使能信号。
    *   ROI 参数：`leftFctaRoi`, `rightFctaRoi` 的几何定义。

## 7. 输出信号
1.  **报警标志**:
    *   `bLeftFctaWarning`：左侧前方交叉交通报警信号。
    *   `bRightFctaWarning`：右侧前方交叉交通报警信号。
2.  **系统状态**:
    *   `fctaSystemState`：反馈给 HMI 显示功能状态（Active/Standby/Fail）。
3.  **诊断/调试信息**:
    *   `objFctaWarningFlag`：每个目标的报警状态，用于调试和 EDR 记录。
    *   `fTTM`, `fDDCI`：关键风险参数，用于监控和标定。

## 8. 与其他功能的交互
*   **FCTB (Front Cross Traffic Braking)**:
    *   FCTA 和 FCTB 共享相同的感知输入和 ROI 定义。
    *   FCTA 是 FCTB 的前置阶段。通常逻辑为：先触发 FCTA 报警，若驾驶员无反应且风险进一步升级（TTC 更短），则触发 FCTB 制动。
    *   代码中 `bLeftFctbWarning` 和 `bLeftFctaWarning` 并行存在，表明两者可能独立判断，但 FCTB 的触发阈值通常比 FCTA 更严格。
*   **BSD/LCA**:
    *   虽然 BSD/LCA 主要关注侧后方，但在某些实现中，前角雷达的数据也可能用于辅助判断车辆周围的完整态势，但 FCTA 有独立的 ROI (`leftFctaRoi`)，与 BSD ROI (`leftBsdRoi`) 在空间上是分离的。
*   **RCTA/RCTB**:
    *   逻辑对称，RCTA 关注后方交叉交通，FCTA 关注前方。两者共用类似的算法框架（ROI 判断、TTM 计算），但雷达源不同（后角雷达 vs 前角雷达）。
*   **TGU (Traffic Guide Unit / Lane Assist)**:
    *   `TGUValid` 标志可能影响 ROI 的动态调整。如果车道线识别有效，FCTA 的 ROI 可能会根据车道边界进行微调，以提高准确性。