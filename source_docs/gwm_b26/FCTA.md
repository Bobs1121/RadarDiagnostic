# FCTA 功能分析

## 1. 功能概述
**FCTA (Front Cross Traffic Alert)** 即前方交叉交通警报，是 ADAS 系统中用于在车辆低速行驶（如从停车位驶出、通过狭窄路口或环岛）时，检测前方横向移动目标（车辆、行人、自行车等）并提前向驾驶员发出警告的功能。

根据提供的源码片段，FCTA 主要依赖角雷达（Corner Radar，特别是前左和前右雷达）感知前方交叉区域的动态目标。其核心逻辑包括：
1.  **ROI 定义**：通过 `leftFctaRoi` 和 `rightFctaRoi` 定义前方左右两侧的感兴趣区域。
2.  **目标筛选**：基于距离、速度、角度及 TTC（Time To Collision）等参数筛选潜在威胁目标。
3.  **状态管理**：维护 `fctaSystemState` 以反映功能可用性。
4.  **报警输出**：通过 `bLeftFctaWarning` 和 `bRightFctaWarning` 输出报警信号，并可能联动 FCTB（前方交叉交通制动）。

## 2. 状态机
根据 `adasWarningStruct` 中的定义，FCTA 功能具有标准的 ADAS 状态机结构：

*   **状态定义** (`fctaSystemState`):
    *   `0` - **None**: 未初始化或无效状态。
    *   `1` - **Init**: 初始化中。
    *   `2` - **Standby**: 待机状态，功能已就绪但条件未满足（如车速过高或过低，传感器受限）。
    *   `3` - **Active**: 激活状态，功能正在运行并监测目标。
    *   `4` - **Off**: 关闭状态，用户手动关闭或系统强制关闭。
    *   `5` - **Failure**: 故障状态，传感器或算法异常。
    *   `6` - **Passive**: 被动状态（通常指降级模式或仅监控不报警）。

*   **状态转换条件** (推断自通用 ADAS 逻辑及变量 `bFCTAEnable`):
    *   **None -> Init**: 系统上电，EOL 测试通过 (`startFlag`)。
    *   **Init -> Standby/Active**: 初始化完成，检查使能标志 `bFCTAEnable`。若使能且车速在有效范围内，进入 Active；否则进入 Standby。
    *   **Standby <-> Active**: 取决于车速、雷达数据有效性、ROI 内是否有有效目标跟踪等条件。
    *   **Active -> Off**: 用户通过 HMI 关闭功能 (`bFCTAEnable = false`)。
    *   **Any -> Failure**: 检测到雷达硬件故障、通信错误或算法内部错误。
    *   **Failure -> Init/Standby**: 故障清除后重启或恢复。

## 3. 报警/制动逻辑

### 3.1 报警触发逻辑
报警由左右两侧独立判断，最终汇总到 `adasWarningStruct`。

1.  **目标检测与筛选**:
    *   在 `leftFctaRoi` 或 `rightFctaRoi` 区域内检测到目标。
    *   目标必须满足运动学特征（如横向速度 `velY` 显著，纵向速度 `velX` 较小或为负，表示横向穿越）。
    *   计算 **TTC (Time To Collision)** 或 **DDCI (Distance to Collision Index)**。源码中 `objOutEDRStruct` 包含 `fTTC` 和 `fDDCI`，这些是判断碰撞风险的核心指标。
    *   检查 `objFctaWarningFlag` (在 `objOutEDRStruct` 和 `structDefine.h` 中均有定义)。当该标志位变为 `WarningFlag_Warning (1)` 时，表示该目标触发报警。

2.  **报警确认与迟滞**:
    *   使用 `KEEPWARNINGFRM` (3帧) 或 `LOWSPEEDKEEPWARNINGFRM` (6帧) 进行报警保持，防止因目标短暂消失或误检导致报警闪烁。
    *   低速场景下使用更长的保持帧数 (`LOWSPEEDKEEPWARNINGFRM`)，因为低速时相对速度小，碰撞风险变化慢，需要更稳定的判断。

3.  **最终报警输出**:
    *   如果左侧 ROI 内存在触发报警的目标，且经过帧计数确认，则 `bLeftFctaWarning` 置位。
    *   同理，右侧对应 `bRightFctaWarning`。
    *   报警级别可能分为 `0-normal`, `1-first warning`, `2-second warning`（参考 BSD/LCA 的定义，FCTA 可能类似，但源码中 FCTA 标志为 `uint8_t`，具体分级需看实现代码，通常 FCTA 为单级视觉/听觉报警）。

### 3.2 制动联动 (FCTB)
*   FCTA 通常作为 FCTB 的前置报警。
*   当 FCTA 报警持续且 TTC 进一步缩短至制动阈值时，可能触发 `bFCTBEnable` 相关的逻辑，输出 `bLeftFctbWarning` / `bRightFctbWarning`，并最终产生 `fBrakeValue` 制动请求。
*   源码中 `objFctbWarningFlag` 和 `bLeftFctbWarning` 的存在证实了这种联动关系。

## 4. 关键阈值
虽然具体数值未在头文件中硬编码为宏（可能存储在标定文件或配置表中），但以下参数定义了判断逻辑：

1.  **ROI 边界**:
    *   `leftFctaRoi` / `rightFctaRoi`: 定义前方交叉区域的几何边界（距离、角度）。通常覆盖车头前方 5-20 米，左右各 30-60 度范围。
2.  **速度阈值**:
    *   **Ego Velocity**: FCTA 通常在低速下激活（如 < 30 km/h 或 < 50 km/h）。
    *   **Target Velocity**: 目标需具有显著的横向速度分量 (`velY`)，以区分静止障碍物和交叉交通。
3.  **TTC/DDCI 阈值**:
    *   `fTTC`: 碰撞时间阈值。例如，TTC < 2.0s 触发报警。
    *   `fDDCI`: 距离碰撞指数，结合距离和速度综合判断。
4.  **报警保持帧数**:
    *   `KEEPWARNINGFRM`: 3 帧 (约 100-150ms，取决于雷达帧率)。
    *   `LOWSPEEDKEEPWARNINGFRM`: 6 帧 (用于低速更稳定的判断)。
5.  **角度阈值**:
    *   `YAWRATETHERESHOLD`: 3.0f (可能用于目标航向角变化率过滤，排除噪声)。

## 5. 关键变量

| 变量名 | 类型 | 来源 | 含义 |
| :--- | :--- | :--- | :--- |
| `bFCTAEnable` | `bool` | `adasEnableStruct` | FCTA 功能全局使能标志，由用户或系统设置。 |
| `fctaSystemState` | `uint8_t` | `adasWarningStruct` | FCTA 功能当前状态 (None/Init/Standby/Active/Off/Failure/Passive)。 |
| `leftFctaRoi` / `rightFctaRoi` | `polygonLargerStruct` | `adasROIStruct` | 前方左右交叉交通检测的感兴趣区域多边形定义。 |
| `objFctaWarningFlag` | `int8_t` | `objOutEDRStruct` / `structDefine.h` | 单个目标的 FCTA 报警标志 (-1: 正常, 0: 无, 1: 报警)。 |
| `bLeftFctaWarning` / `bRightFctaWarning` | `uint8_t` | `adasWarningStruct` | 系统级左右侧 FCTA 报警输出标志 (0: 正常, 1: 一级报警, 2: 二级报警)。 |
| `fTTC` | `float` | `objOutEDRStruct` | 目标与自车的预计碰撞时间，核心风险指标。 |
| `fDDCI` | `float` | `objOutEDRStruct` | 距离碰撞指数，辅助判断碰撞风险。 |
| `velX` / `velY` | `float` | `objOutEDRStruct` | 目标在自车坐标系下的纵向和横向速度，用于判断交叉运动。 |
| `KEEPWARNINGFRM` | `#define` | `paraDefine.h` | 报警保持帧数 (3)，用于滤波和确认。 |
| `LOWSPEEDKEEPWARNINGFRM` | `#define` | `paraDefine.h` | 低速报警保持帧数 (6)，用于低速场景稳定判断。 |

## 6. 输入信号
1.  **雷达原始数据/目标列表**: 包含目标的距离、角度、速度 (`velX`, `velY`)、ID、生命周期 (`lifeCycle`) 等。
2.  **自车状态**:
    *   车速 (Ego Velocity): 用于判断是否进入 FCTA 有效车速范围。
    *   转向角/航向角 (Yaw Rate): 用于坐标变换和 ROI 动态调整。
3.  **功能使能信号**: `bFCTAEnable`。
4.  **ROI 配置**: `leftFctaRoi`, `rightFctaRoi` 的几何参数。
5.  **其他 ADAS 状态**: 如 BSD、RCTA 的状态，可能用于功能优先级仲裁或状态互斥。

## 7. 输出信号
1.  **报警标志**:
    *   `bLeftFctaWarning`: 左侧前方交叉交通报警。
    *   `bRightFctaWarning`: 右侧前方交叉交通报警。
2.  **系统状态**: `fctaSystemState`，供 HMI 显示功能可用性。
3.  **目标级报警信息**: `objFctaWarningFlag`，用于调试或高级应用。
4.  **联动制动请求** (间接): 通过 `bLeftFctbWarning` / `bRightFctbWarning` 和 `fBrakeValue` 传递给制动系统（如果 FCTB 使能且条件满足）。

## 8. 与其他功能的交互
1.  **FCTB (Front Cross Traffic Braking)**:
    *   FCTA 是 FCTB 的前置报警。FCTA 报警后，若风险进一步升级（TTC 更短），则触发 FCTB。
    *   共享 ROI (`leftFctaRoi`/`rightFctaRoi`) 和目标检测逻辑。
    *   通过 `bFCTBEnable` 和 `objFctbWarningFlag` 进行逻辑衔接。
2.  **RCTA/RCTB (Rear Cross Traffic)**:
    *   逻辑对称，但作用于后方。通常不会同时激活（除非车辆极短或特殊场景），系统可能根据车速和方向选择激活前方或后方交叉交通功能。
3.  **BSD/LCA**:
    *   共享部分目标跟踪和 ROI 管理基础设施。
    *   在变道场景下，BSD/LCA 优先级可能高于 FCTA，或者 FCTA 在车辆完全静止或极低速起步时激活，而 BSD/LCA 在行驶中激活。
4.  **TGU (Turn Guard Assist)**:
    *   如果车辆配备 TGU，FCTA 可能与 TGU 有重叠。TGU 通常针对转弯场景，而 FCTA 针对直行或起步场景。系统需根据转向信号和车速区分功能。