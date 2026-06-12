# RCW 功能分析

## 1. 功能概述
RCW (Rear Cross Traffic Warning，后方交叉交通预警) 是角雷达（Corner Radar）ADAS 系统中的核心安全功能之一。其目的是在车辆倒车（Reverse Gear）时，检测车辆后方左右两侧横向移动的车辆或行人，并在发生潜在碰撞风险时向驾驶员发出视觉/听觉报警。

根据提供的源码片段，RCW 功能依赖于特定的 ROI（感兴趣区域）`rcwRoi` 进行目标过滤，并通过状态机管理功能的激活与报警输出。该功能通常与 RCTA（后方交叉交通警报，通常指静态或低速场景）和 RCTB（后方交叉交通制动，涉及自动刹车）在逻辑上有所区分，但在本代码结构中，`bRCWEnable` 和 `rcwSystemState` 独立存在，表明 RCW 主要侧重于**预警（Warning）**而非直接制动（Brake），制动请求可能由 RCTB 模块或上层融合模块处理，但 RCW 的状态会作为输入参考。

## 2. 状态机
根据 `adasWarningStruct` 中的定义，RCW 功能遵循标准的 ADAS 状态机模型：

*   **状态定义** (`uint8_t rcwSystemState`):
    *   `0` - **None**: 未定义或初始空状态。
    *   `1` - **Init**: 初始化状态，系统正在加载参数或自检。
    *   `2` - **Standby**: 待机状态。功能已使能 (`bRCWEnable == true`)，但尚未满足激活条件（如车速、档位等）。
    *   `3` - **Active**: 激活状态。功能正在运行，实时监测 `rcwRoi` 内的目标，并可能触发报警。
    *   `4` - **Off**: 关闭状态。用户手动关闭或系统配置禁用。
    *   `5` - **Failure**: 故障状态。雷达硬件故障、信号丢失或算法异常。
    *   `6` - **Passive**: 被动状态。通常指功能因某些条件（如车速过高、传感器被遮挡）暂时抑制，但系统仍在工作。

*   **状态转换逻辑推断**:
    1.  **None/Off -> Init**: 系统上电或复位。
    2.  **Init -> Standby**: 初始化完成，检查 `bRCWEnable`。
    3.  **Standby -> Active**: 满足激活条件（例如：档位为 R，车速低于阈值，雷达信号正常）。
    4.  **Active -> Standby**: 不满足激活条件（例如：挂入 D 档，车速超过阈值）。
    5.  **Any -> Failure**: 检测到硬件或通信错误。
    6.  **Failure -> Init/Standby**: 故障恢复后重新进入初始化或待机。

## 3. 报警/制动逻辑

### 3.1 报警触发条件
虽然具体的算法判断代码未完全展示，但根据结构体定义和通用 ADAS 逻辑，RCW 报警触发需满足以下条件：

1.  **功能状态**: `rcwSystemState` 必须为 `Active` (3)。
2.  **目标存在**: 在 `rcwRoi` (后方交叉区域) 内检测到有效目标 (`objStruct`)。
3.  **目标属性**:
    *   目标类型 (`objType`) 通常为车辆 (4) 或行人/非机动车 (1, 2, 3)。
    *   目标具有横向相对速度，且轨迹预测与自车路径相交。
    *   目标未被标记为干扰 (`stState` 正常) 或鬼影 (`ghostProb` 低)。
4.  **时间/距离阈值**:
    *   目标进入报警阈值范围（通常基于 TTC - Time To Collision 或距离 `distY`/纵向距离）。
    *   报警标志 `objRcwWarningFlag` 被置位。
5.  **迟滞逻辑**:
    *   使用 `KEEPWARNINGFRM` (3帧) 或 `LOWSPEEDKEEPWARNINGFRM` (6帧) 进行滤波，防止误报。只有当报警条件持续满足一定帧数后，`bRcwWarning` 才会置位。

### 3.2 报警取消条件
1.  目标离开 `rcwRoi`。
2.  目标不再构成碰撞风险（TTC 变大或距离增加）。
3.  报警条件不再满足，且经过一定的“去抖动”帧数（通常与触发帧数相同或略短）。
4.  功能状态退出 `Active`。

### 3.3 制动逻辑
*   **注意**: 在提供的代码中，`bRcwWarning` 是 `uint8_t` 类型，而 `fBrakeValue` 和 `fBrakeEventTime` 位于 `adasWarningStruct` 中。
*   RCW 本身通常**不直接输出制动请求**，而是输出预警信号 (`bRcwWarning`)。
*   如果车辆配备 RCTB (Rear Cross Traffic Braking)，RCTB 模块会接收 RCW 的检测目标或预警信号，并结合更严格的阈值（更短的 TTC）来生成 `fBrakeValue`。
*   在本代码结构中，`bRctbWarning` 和 `bRcwWarning` 是分开的，暗示 RCW 仅负责预警，制动由 RCTB 负责。

## 4. 关键阈值

根据 `paraDefine.h` 和通用 ADAS 标准，以下是影响 RCW 的关键阈值：

| 阈值名称 | 定义/宏 | 值/说明 | 作用 |
| :--- | :--- | :--- | :--- |
| **报警保持帧数** | `KEEPWARNINGFRM` | 3 | 正常速度下，报警条件需持续 3 帧才触发报警，用于滤波。 |
| **低速报警保持帧数** | `LOWSPEEDKEEPWARNINGFRM` | 6 | 低速时（如倒车），由于相对速度慢，需要更长的确认时间（6帧）以避免误报。 |
| **ROI 定义** | `rcwRoi` | `polygonStruct` | 定义后方交叉检测的几何区域。通常覆盖车辆后方左右两侧各一定角度和距离（如 0-50米，角度 ±45° 至 ±90°）。 |
| **YAW 角率阈值** | `YAWRATETHERESHOLD` | 3.0f | 可能用于判断自车或目标的转向剧烈程度，过滤掉自车快速转向导致的误检。 |
| **最大警告状态缓冲** | `MAXWARNINGSTATEBUFFERSIZE` | 3 | 用于存储历史报警状态，辅助迟滞逻辑。 |

*注：具体的距离阈值（如 50m）、速度阈值（如 10km/h）未在宏定义中直接显示，通常存储在非易失性存储器或标定文件中，通过 `rcwRoi` 的顶点坐标间接体现。*

## 5. 关键变量

| 变量名 | 类型 | 来源 | 含义 |
| :--- | :--- | :--- | :--- |
| `bRCWEnable` | `bool` | `adasEnableStruct` | RCW 功能使能标志。由用户设置或系统配置决定。 |
| `rcwSystemState` | `uint8_t` | `adasWarningStruct` | RCW 功能当前状态机状态 (0-6)。 |
| `rcwRoi` | `polygonStruct` | `adasROIStruct` | RCW 的感兴趣区域多边形定义。用于过滤目标。 |
| `objRcwWarningFlag` | `int8_t` | `objStruct` | 单个目标的 RCW 报警标志。-1: 始终正常, 0: 正常, 其他值可能表示报警等级。 |
| `bRcwWarning` | `uint8_t` | `adasWarningStruct` | 系统级 RCW 报警输出标志。0: 无报警, 1: 报警中。 |
| `fBrakeValue` | `float` | `adasWarningStruct` | 制动请求值。虽然属于 ADAS 结构体，但通常由 RCTB 模块写入，RCW 模块可能只读或忽略。 |
| `distY` | `float` | `objStruct` | 目标的横向距离。用于判断目标是否在车道内或接近自车。 |
| `yawAng` | `float` | `objStruct` | 目标的航向角。用于判断目标运动方向是否与自车路径交叉。 |
| `objType` | `uint8_t` | `objStruct` | 目标类型。RCW 通常关注车辆 (4) 和行人 (1)。 |

## 6. 输入信号

1.  **雷达感知数据**:
    *   `objStruct` 链表：包含目标的 ID、距离、速度、角度、航向角、类型、鬼影概率等。
    *   `rcwRoi`：当前有效的检测区域多边形。
2.  **车辆状态信号**:
    *   **档位 (Gear)**: 必须为 R (Reverse) 档才能激活 RCW。
    *   **车速 (Ego Velocity)**: 通常要求车速较低（如 < 10-15 km/h）。
    *   **转向角/角速度**: 用于补偿自车运动对目标相对速度的影响。
3.  **功能配置**:
    *   `bRCWEnable`: 功能开关。
    *   `adasEnableStruct`: 其他相关功能的使能状态（可能用于互斥或优先级判断）。

## 7. 输出信号

1.  **报警信号**:
    *   `bRcwWarning` (`uint8_t`): 发送给 HMI (仪表盘/中控屏) 和声音提示模块。
        *   `0`: 正常
        *   `1`: 报警 (Visual/Audible Warning)
    *   `rcwFlag` (`bool`): 在 `objStruct` 或全局标志中，表示当前帧是否有 RCW 相关目标。
2.  **状态信号**:
    *   `rcwSystemState`: 发送给诊断系统或 HMI 显示功能状态（Active/Standby/Fail）。
3.  **目标信息**:
    *   `objRcwWarningFlag`: 标记具体哪个目标触发了报警，用于可视化显示（如在屏幕上高亮显示危险车辆）。

## 8. 与其他功能的交互

1.  **与 RCTA (Rear Cross Traffic Alert) 的关系**:
    *   在许多系统中，RCW 和 RCTA 是同一功能的不同称呼或不同阶段。
    *   在本代码中，`bRCTAEnable` 和 `bRCWEnable` 分开，`rcwRoi` 和 `leftRctaRoi`/`rightRctaRoi` 分开。
    *   **推测**: RCTA 可能侧重于静态或极低速的“后方交叉交通警报”（如停车时），而 RCW 侧重于倒车时的动态预警。或者 RCTA 是 RCW 的子集/前级检测。
    *   两者共享目标检测算法，但 ROI 和阈值可能不同。

2.  **与 RCTB (Rear Cross Traffic Braking) 的关系**:
    *   RCW 提供预警，RCTB 提供制动。
    *   RCTB 模块会监控 RCW 检测到的目标。如果目标的 TTC 进一步缩短至制动阈值，RCTB 将触发 `fBrakeValue`。
    *   `bRctbWarning` 和 `bRcwWarning` 可能同时置位，但 RCTB 的报警可能更紧急或伴随制动动作。

3.  **与 BSD (Blind Spot Detection) 的关系**:
    *   BSD 检测侧后方盲区，RCW 检测正后方交叉区域。
    *   两者 ROI 在空间上可能有重叠（如侧后方角落）。
    *   系统需要进行**目标去重**和**优先级仲裁**。如果一个目标同时位于 BSD 和 RCW ROI，通常根据当前车速和档位决定哪个功能主导报警。倒车时 RCW 优先级高于 BSD。

4.  **与 DOW (Door Open Warning) 的关系**:
    *   DOW 检测开门风险，RCW 检测倒车风险。
    *   两者都关注后方交通。在停车开门时，DOW 激活；在倒车时，RCW 激活。
    *   两者可能共享后方目标检测数据，但 ROI 和触发逻辑不同。

5.  **与 TGU (Traffic Guide Unit / Lane Keeping) 的关系**:
    *   `TGUValid` 标志可能用于判断车道线是否有效。
    *   在 RCW 中，车道线信息可能用于更精确地定义 `rcwRoi` 或判断目标是否在同向/对向车道，从而优化误报率。