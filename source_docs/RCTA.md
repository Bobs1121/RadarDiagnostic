# RCTA 功能分析

## 1. 功能概述
**RCTA (Rear Cross Traffic Alert)**，即后方交叉交通警报，是角雷达（Corner Radar）ADAS功能中的核心安全功能之一。
根据提供的源码片段，该功能主要运行在车辆低速或静止状态（通常倒车场景），用于检测车辆后方左右两侧视野盲区内的横向移动目标（如行人、车辆、自行车等）。
代码逻辑主要集中在**目标跟踪（Tracking）**和**数据关联（Data Association）**阶段，通过计算预测位置与测量位置的偏差（RxDif, RyDif），结合场景标志（如拥堵、静止、移动），对目标进行有效性过滤（Thinning）和门限判断（Gating），最终输出警告标志。

## 2. 状态机
虽然提供的代码片段主要涉及感知层（Perception）的跟踪逻辑，未直接展示完整的系统级状态机（如 Init/Active/Off 的切换），但可以从变量定义和逻辑中推断出以下隐含状态逻辑：

*   **系统使能状态 (`g_adasEnable.bRCTAEnable`)**:
    *   **Disable**: 功能关闭，不执行相关逻辑。
    *   **Enable**: 功能开启，进入感知处理流程。
*   **跟踪状态 (Track State)**:
    *   **Init/Standby**: 目标未建立稳定跟踪，`lifeCycle` 较短。
    *   **Active**: 目标稳定跟踪，`lifeCycle` 超过阈值（如 `TRACK_delayLifeCycle`），且通过关联门限。
    *   **Lost/Deleted**: 目标丢失或超出ROI，跟踪终止。
*   **报警状态 (Warning State)**:
    *   **Normal (0)**: 无危险。
    *   **Warning (1)**: 触发一级警告（视觉/听觉）。
    *   **Critical (2)**: 触发二级警告或制动请求（通常关联 RCTB，但在 RCTA 逻辑中可能作为严重等级体现）。
    *   *注：`adasWarningStruct` 中定义了 `bLeftRctaWarning` 和 `bRightRctaWarning`，类型为 `uint8_t`，通常 0=Normal, 1=First Warning, 2=Second Warning。*

## 3. 报警/制动逻辑
由于代码片段侧重于**感知滤波与关联**，而非最终的报警决策机（Decision Module），以下是基于代码推导的**报警触发前置条件**：

### 3.1 目标有效性过滤 (Thinning Logic)
在 `AssignThinFlg` 函数中，系统对目标进行“变薄”处理，即排除非威胁或干扰目标：
1.  **高速大转弯排除**:
    *   若自车速度 `carSpd >= TRACK_MaxRCTAEgoCarV` (6.0 m/s) 且横摆角速度 `yaw_rate < TRACK_BigTurnYawRate` (5.0 rad/s)，且目标移动状态与聚类不一致，则标记为无效（`velThinFlg = true`, `distThinFlg = true`）。
2.  **低速静止/拥堵场景排除**:
    *   若自车速度 `< 6.0 m/s`，且非交叉场景 (`g_crossSceneFlg == 0`)，且目标被判定为静止 (`DynProp_Stationary`) 或停止 (`DynProp_Stopped`)，但在拥堵场景 (`JamScene_JamStopped`) 下聚类显示为移动，则标记距离滤波 (`distThinFlg = true`)。
    *   若目标为静止/停止，且生命周期 `> 30`，偏航角判断通过，且绝对速度 `< 0.6 m/s`，则视为静态背景，可能被过滤。
3.  **特定物体排除**:
    *   静止的卡车 (`DynProp_Stopped` && `ObjType_Truck`) 会被标记距离滤波。

### 3.2 数据关联与门限判断 (Gating Logic)
在 `AssignGateThd` (隐含在后续代码) 中，计算预测与测量的偏差：
1.  **横向偏差 (RxDif)**:
    *   计算预测 `distX` 与聚类 `distXUse` 的差值。
    *   若目标参考点变化 (`isRefPtChange`) 或为大卡车且高速移动，使用最小距离 (`minDistX`) 进行更严格的关联。
2.  **纵向偏差 (RyDif)**:
    *   计算预测 `distY` 与聚类 `distYUse` 的差值。
3.  **关联门限 (Gate)**:
    *   若 `RyDifHoz` (横向相对速度/位置偏差) 在 `[-gateYMinRatio * RyGate, gateYMaxRxatio * RyGate]` 范围内。
    *   且 `RxDifHozAbs` (纵向偏差) 在 `[gateXMin, gateXMax]` 范围内，或目标在聚类距离范围内。
    *   则 `ifMarkRAll = true`，表示关联成功，目标有效。
4.  **栅栏/静态干扰排除**:
    *   若自车低速 (`< 6.0 m/s`)，聚类为静止，且目标为横向移动 (`hozCanFlg`)，若聚类点数少 (`dotNum <= 2`) 且位置在目标后方特定区域，则取消关联 (`ifMarkRAll = false`)，防止将栅栏误判为穿越目标。

### 3.3 报警触发 (推断)
虽然代码未直接显示 `if (danger) setWarning()`，但逻辑流向为：
1.  目标通过 `AssignThinFlg` 未被过滤。
2.  目标通过 `AssignGateThd` 成功关联。
3.  目标位于 `g_adasRoi.leftRctaRoi` 或 `rightRctaRoi` 区域内。
4.  目标具有横向速度 (`isMoveFlg`) 且 TTC (Time To Collision) 或距离小于安全阈值。
5.  设置 `objRctaWarningFlag` 为 `WarningFlag_Warning`。
6.  更新 `g_adasWarning.bLeftRctaWarning` 或 `bRightRctaWarning`。

## 4. 关键阈值
| 阈值名称 | 值 | 单位 | 含义 |
| :--- | :--- | :--- | :--- |
| `TRACK_MaxRCTAEgoCarV` | 6.0 | m/s | RCTA 功能有效的自车最大速度。超过此速度可能退出 RCTA 或切换逻辑。 |
| `TRACK_BigTurnYawRate` | 5.0 | rad/s | 大转弯横摆角速度阈值。用于判断是否为大转弯场景，影响目标过滤。 |
| `TRACK_BigTurnYawRateL` | 8.0 | rad/s | 更大转弯阈值，可能用于更严格的过滤。 |
| `0.6` | 0.6 | m/s | 静止目标速度阈值。低于此速度且生命周期长，视为静态背景。 |
| `1.5` | 1.5 | m | 距离阈值 (代码注释中提及 `distX > 1.5f`)，可能用于近距离过滤。 |
| `1.0` | 1.0 | m | 距离阈值 (代码注释中提及 `fabsf(pTemp->distX) < 1.0f`)。 |
| `0.5` | 0.5 | m/s | 极低速度阈值，用于特定场景（如 `probRxDiff > 900.0f` 时的特殊处理）。 |
| `30.0` | 30.0 | - | 纵向距离上限 (`absDistYBeginYCal < 30.0f`)。 |
| `System_LaneWidth` | - | m | 车道宽度，用于计算横向位置比例 (`0.6f * System_LaneWidth`)。 |
| `TRACK_delayLifeCycle` | 15 | frames | 跟踪生命周期阈值，用于确认目标有效性。 |
| `TRACK_delayLifeCycleLong` | 30 | frames | 长生命周期阈值，用于静态背景判断。 |

## 5. 关键变量
| 变量名 | 类型 | 来源 | 含义 |
| :--- | :--- | :--- | :--- |
| `g_adasEnable.bRCTAEnable` | `bool` | `adasEnableStruct` | RCTA 功能使能标志。 |
| `g_egoCarAddInfo.carSpd` | `float` | 车辆总线/传感器 | 自车当前速度。 |
| `g_egoCarInfo.yaw_rate` | `float` | 车辆总线/IMU | 自车横摆角速度。 |
| `g_crossSceneFlg` | `uint8_t` | 场景识别模块 | 交叉场景标志 (0: 非交叉, 其他: 交叉)。 |
| `g_jamSceneFlg` | `uint8_t` | 场景识别模块 | 拥堵场景标志 (`JamScene_NotJamScene`, `JamScene_JamStopped`)。 |
| `pTemp->dynFlg` | `uint8_t` | 目标跟踪模块 | 目标动态属性 (`DynProp_Crossing`, `DynProp_Stationary`, `DynProp_Stopped`, `DynProp_Oncoming`)。 |
| `pTemp->isMoveFlg` | `uint8_t` | 目标跟踪模块 | 目标移动标志 (0: 静止, 1: 移动)。 |
| `pTemp->hozCanFlg` | `uint8_t` | 目标跟踪模块 | 横向穿越标志，表示目标是否正在横向穿越车道。 |
| `pTemp->objType` | `uint8_t` | 目标分类模块 | 目标类型 (Pedestrian, Bike, Car, Truck 等)。 |
| `pTemp->distX` / `distY` | `float` | 目标跟踪模块 | 目标相对于自车的纵向/横向距离。 |
| `pTemp->yawAngFilterMoved` | `float` | 目标跟踪模块 | 目标偏航角滤波值。 |
| `clusterInfo->clusterData[cluCt].isMoveFlg` | `uint8_t` | 聚类模块 | 聚类数据的移动标志。 |
| `clusterInfo->clusterData[cluCt].curbFlg` | `uint8_t` | 聚类模块 | 路沿标志，用于排除路边静态物体。 |
| `g_adasWarning.bLeftRctaWarning` | `uint8_t` | 报警输出结构 | 左侧 RCTA 警告状态 (0: Normal, 1: Warning, 2: Critical)。 |
| `g_adasWarning.bRightRctaWarning` | `uint8_t` | 报警输出结构 | 右侧 RCTA 警告状态。 |
| `objRctaWarningFlag` | `int8_t` | 目标输出结构 | 单个目标的 RCTA 警告标志。 |

## 6. 输入信号
1.  **车辆状态信号**:
    *   自车速度 (`carSpd`)
    *   自车横摆角速度 (`yaw_rate`)
    *   自车位置/姿态 (用于坐标转换)
2.  **雷达原始数据/聚类数据**:
    *   聚类中心位置 (`distX`, `distY`)
    *   聚类速度 (`velX`, `velY`)
    *   聚类移动/静止标志 (`isMoveFlg`)
    *   聚类点数 (`dotNum`)
    *   聚类路沿标志 (`curbFlg`)
3.  **目标跟踪数据**:
    *   目标 ID (`objID`)
    *   目标类型 (`objType`)
    *   目标动态属性 (`dynFlg`)
    *   目标生命周期 (`lifeCycle`)
    *   目标预测位置 (`predictData.distX`, `predictData.distY`)
4.  **场景识别标志**:
    *   交叉场景标志 (`g_crossSceneFlg`)
    *   拥堵场景标志 (`g_jamSceneFlg`)
5.  **系统配置**:
    *   RCTA 使能标志 (`bRCTAEnable`)
    *   ROI 区域定义 (`leftRctaRoi`, `rightRctaRoi`)

## 7. 输出信号
1.  **报警标志**:
    *   `g_adasWarning.bLeftRctaWarning`: 左侧后方交叉交通警告等级。
    *   `g_adasWarning.bRightRctaWarning`: 右侧后方交叉交通警告等级。
2.  **目标级警告**:
    *   `objRctaWarningFlag`: 每个跟踪目标的警告状态，用于调试或上层应用。
3.  **跟踪状态**:
    *   更新后的目标跟踪状态 (`ifMarkRAll` 等内部标志)，影响后续帧的跟踪连续性。

## 8. 与其他功能的交互
1.  **RCTB (Rear Cross Traffic Braking)**:
    *   RCTA 是 RCTB 的前置感知模块。RCTA 检测到的危险目标若满足更严格的 TTC 或距离条件，将触发 RCTB 进行自动制动。
    *   代码中 `bRCTBEnable` 和 `objRctbWarningFlag` 的存在表明两者紧密耦合，共享相同的感知结果和 ROI。
2.  **BSD (Blind Spot Detection)**:
    *   BSD 和 RCTA 共享部分感知逻辑（如目标跟踪、ROI 定义）。
    *   在低速倒车时，BSD 通常退出或降级，RCTA 接管后方侧向监控。
    *   代码中 `bBSDEnable` 和 `bRCTAEnable` 是独立的使能标志，但可能由上层管理器根据车速和档位协调。
3.  **LCA (Lane Change Assist)**:
    *   LCA 在变道时提供警告，与 RCTA 在低速倒车时提供警告，场景不同但感知对象类似（侧后方目标）。
    *   通常车速高于 RCTA 阈值（如 > 10 km/h）时，LCA 激活，RCTA 退出。
4.  **DOW (Door Open Warning)**:
    *   DOW 检测后方接近车辆以警告开门。
    *   RCTA 和 DOW 都关注后方侧向目标，但 DOW 更关注纵向接近速度，RCTA 更关注横向穿越。
    *   两者可能共享 `leftRctaRoi` / `rightRctaRoi` 或类似的 ROI 定义。
5.  **场景识别模块**:
    *   依赖 `g_crossSceneFlg` 和 `g_jamSceneFlg` 来优化目标过滤逻辑，避免在拥堵或复杂路口产生误报。