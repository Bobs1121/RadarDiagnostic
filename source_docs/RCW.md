# RCW 功能分析

## 1. 功能概述
**RCW (Rear Cross Traffic Warning)**，即后方交叉交通预警功能。该功能主要利用角雷达（通常是左后和右后角雷达）检测车辆后方侧向（交叉方向）的障碍物（如车辆、行人、自行车等）。当驾驶员在倒车或低速行驶过程中，系统检测到后方有横向移动或静止的障碍物进入危险区域时，向驾驶员发出视觉或听觉报警，以防止碰撞事故。

根据提供的源码片段，RCW 是 ADAS 套件中的一个独立功能模块，拥有独立的状态机、ROI（感兴趣区域）定义和报警标志位。

## 2. 状态机
根据 `adasWarningStruct` 中的 `rcwSystemState` 定义，RCW 功能遵循标准的 ADAS 状态机模型。

**状态定义 (`uint8_t rcwSystemState`):**
*   **0 - None**: 未定义或初始未激活状态。
*   **1 - Init**: 初始化状态。系统正在进行自检、传感器校准或参数加载。
*   **2 - Standby**: 待机状态。系统已就绪，但当前条件不满足功能激活（例如车速过高、雷达被遮挡、未挂倒挡等）。
*   **3 - Active**: 激活状态。系统正在实时监控 ROI 区域内的目标，具备报警能力。
*   **4 - Off**: 关闭状态。用户手动关闭了 RCW 功能 (`bRCWEnable = false`)。
*   **5 - Failure**: 故障状态。雷达硬件故障、通信中断或算法内部错误，功能不可用。
*   **6 - Passive**: 被动状态。通常指系统处于某种受限模式，可能仅记录数据或不发出主动报警，具体取决于整车策略。

**状态转换条件推断:**
*   **None -> Init**: 上电或系统复位。
*   **Init -> Standby/Active/Failure**: 初始化完成，根据自检结果进入相应状态。
*   **Standby <-> Active**:
    *   *Standby -> Active*: 满足激活条件（如车速 < 阈值，挂入 R 挡，`bRCWEnable` 为真，雷达数据有效）。
    *   *Active -> Standby*: 不满足激活条件（如车速超过阈值，退出 R 挡，`bRCWEnable` 变为假）。
*   **Any -> Off**: 用户通过 HMI 关闭功能。
*   **Any -> Failure**: 检测到硬件或通信故障。
*   **Failure -> Init/Standby**: 故障恢复后重新初始化。

## 3. 报警/制动逻辑

### 3.1 报警触发逻辑
1.  **目标检测与跟踪**: 雷达检测到 ROI (`rcwRoi`) 内的目标，并建立跟踪轨迹。
2.  **有效性过滤**:
    *   目标必须在 `rcwRoi` 多边形区域内。
    *   目标类型 (`objType`) 需为有效目标（车、人、非机动车等）。
    *   目标置信度/鬼影概率 (`ghostProb`) 需低于阈值。
    *   目标动态属性 (`dynFlg`) 需符合运动特征。
3.  **报警判断**:
    *   当有效目标进入 `rcwRoi` 且满足特定的距离、角度或 TTC (Time To Collision) 条件时，设置目标级别的报警标志 `objRcwWarningFlag`。
    *   根据 `KEEPWARNINGFRM` (3帧) 或 `LOWSPEEDKEEPWARNINGFRM` (6帧) 进行迟滞处理，防止误报。即报警信号需持续一定帧数才确认为有效报警。
4.  **系统级报警输出**:
    *   若任一目标触发有效报警，则设置系统级标志 `rcwFlag = true` 和 `bRcwWarning`。
    *   `bRcwWarning` 可能包含分级报警逻辑（参考 DOW 的 `0-normal, 1-first warning, 2-second warning`，虽然 RCW 字段为 `uint8_t`，具体分级需看实现，但通常 RCW 为单级或两级报警）。

### 3.2 报警取消逻辑
1.  **目标离开**: 目标移出 `rcwRoi` 区域。
2.  **目标消失**: 目标跟踪丢失或置信度低于阈值。
3.  **条件不满足**: 车辆状态变化导致功能退出 Active 状态（如车速升高）。
4.  **迟滞清除**: 报警条件消失后，需经过一定的帧数（`KEEPWARNINGFRM`）确认无新目标进入，才清除 `bRcwWarning`。

### 3.3 制动逻辑
*   **注意**: 提供的源码片段中，RCW 仅定义了 `bRcwWarning` 和 `rcwFlag`，**未直接包含制动请求变量**（如 `fBrakeValue` 通常与 AEB 或 RCTB 关联）。
*   RCW 通常仅为**预警功能**（Warning），不直接控制制动。
*   若需自动制动，通常由 **RCTB (Rear Cross Traffic Braking)** 功能处理，其标志为 `leftRctbFlag` / `rightRctbFlag` 和 `bLeftRctbWarning` / `bRightRctbWarning`。RCW 与 RCTB 可能共享部分感知数据，但逻辑独立。

## 4. 关键阈值

| 阈值名称 | 定义/来源 | 数值/说明 |
| :--- | :--- | :--- |
| **ROI 区域** | `polygonStruct rcwRoi` | 定义后方交叉交通的检测几何区域，通常位于车辆后方左右两侧。 |
| **报警保持帧数** | `KEEPWARNINGFRM` | `3U` 帧。正常速度下，报警需持续 3 帧才输出。 |
| **低速报警保持帧数** | `LOWSPEEDKEEPWARNINGFRM` | `6U` 帧。低速时延长保持时间，提高稳定性。 |
| **航向角变化阈值** | `YAWRATETHERESHOLD` | `3.0f`。用于判断目标或自车航向角变化率，过滤异常目标。 |
| **膨胀比例** | `EXPENDRATIO` | `0.05f`。可能用于 ROI 边界的动态膨胀，以适应车辆姿态变化。 |
| **最大报警状态缓冲** | `MAXWARNINGSTATEBUFFERSIZE` | `3`。用于存储历史报警状态，辅助迟滞逻辑。 |
| **目标类型** | `objType` | 1-Pedestrian, 2-Cyclist, 3-Motorbike, 4-Car, 5-Truck。RCW 通常对所有类型都敏感。 |

## 5. 关键变量

| 变量名 | 类型 | 来源 | 含义 |
| :--- | :--- | :--- | :--- |
| `bRCWEnable` | `bool` | `adasEnableStruct` | RCW 功能使能标志，由用户或系统设置。 |
| `rcwSystemState` | `uint8_t` | `adasWarningStruct` | RCW 功能当前状态 (0-6)。 |
| `rcwRoi` | `polygonStruct` | `adasROIStruct` | RCW 功能的感兴趣区域多边形定义。 |
| `objRcwWarningFlag` | `int8_t` | `objStruct` | 单个目标的 RCW 报警标志。 |
| `rcwFlag` | `bool` | `objStruct` (全局/聚合) | 系统级 RCW 报警标志，任一目标报警则为真。 |
| `bRcwWarning` | `uint8_t` | `adasWarningStruct` | 最终输出的 RCW 报警状态，发送给 HMI 或整车控制器。 |
| `ghostProb` | `uint8_t` | `objStruct` | 目标鬼影概率，用于过滤虚假目标。 |
| `dynFlg` | `uint8_t` | `objStruct` | 目标动态标志，区分静止/运动目标。 |
| `objType` | `uint8_t` | `objStruct` | 目标分类，影响报警策略。 |

## 6. 输入信号

1.  **雷达感知数据**:
    *   目标列表 (`objStruct*`): 包含位置 (`distY`, `length`, `width`), 速度, 航向角 (`yawAng`), 类型 (`objType`), 置信度 (`ghostProb`) 等。
    *   雷达状态: 健康状态、校准状态 (`InCalibState`)。
2.  **车辆状态信号**:
    *   车速 (Ego Velocity): 用于判断是否处于 RCW 激活速度范围（通常 < 10-15 km/h）。
    *   挡位 (Gear Position): 通常为 R (Reverse) 挡激活。
    *   转向角/航向角: 用于 ROI 的动态调整。
3.  **功能使能信号**:
    *   `bRCWEnable`: 用户开关状态。
4.  **ROI 配置**:
    *   `rcwRoi`: 预定义的检测区域几何参数。

## 7. 输出信号

1.  **报警状态**:
    *   `bRcwWarning`: 发送给 HMI 的报警等级/状态，触发仪表盘图标或声音报警。
    *   `rcwFlag`: 内部标志，用于系统监控或日志记录。
2.  **目标信息**:
    *   `objRcwWarningFlag`: 标记哪些具体目标触发了报警，可用于可视化显示。
3.  **系统状态**:
    *   `rcwSystemState`: 反映功能当前工作状态，用于诊断和用户提示。

## 8. 与其他功能的交互

1.  **与 RCTA/RCTB 的关系**:
    *   **共享感知**: RCW、RCTA、RCTB 通常使用相同的后方角雷达数据和目标跟踪结果。
    *   **逻辑独立**: RCW 仅负责预警，RCTB 负责制动。源码中分别定义了 `rcwFlag` 和 `leftRctbFlag`/`rightRctbFlag`，表明它们是独立的功能模块。
    *   **ROI 差异**: `rcwRoi` 和 `leftRctaRoi`/`rightRctaRoi` 可能不同，RCTA 可能覆盖更宽或更远的区域，或者对运动目标有更严格的要求。
2.  **与 BSD/LCA 的关系**:
    *   **空间区分**: BSD/LCA 关注侧后方平行车道，RCW 关注后方交叉方向。ROI 不重叠或极少重叠。
    *   **目标复用**: 同一目标可能被多个功能评估，但根据其在不同 ROI 中的位置决定触发哪个报警。
3.  **与 DOW 的关系**:
    *   **场景互补**: DOW (Door Open Warning) 通常在车辆静止时检测侧后方来车，RCW 在倒车时检测后方交叉来车。两者可能在低速静止或缓慢移动场景下有重叠，但触发条件（挡位、车速）不同。
4.  **与 TGU 的关系**:
    *   **车道信息**: TGU (Traffic Guide Unit) 提供车道线信息，可能用于动态调整 RCW ROI 的边界，特别是在弯道或复杂路况下。`TGUValid` 标志可能影响 RCW 的 ROI 计算。