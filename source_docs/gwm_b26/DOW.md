# DOW 功能分析

## 1. 功能概述
DOW (Door Open Warning，开门预警) 是角雷达 ADAS 功能的一部分，旨在防止驾驶员或乘客在车辆静止或低速状态下打开车门时，与后方或侧后方接近的车辆、摩托车或行人发生碰撞。

根据提供的源码片段，DOW 功能主要依赖于**目标分类（Object Classification）**和**目标属性跟踪**。虽然提供的代码主要集中在 `objAttribCal.c`（目标属性计算，如类型升级/降级、保持逻辑），但通过结构体定义可以推断出 DOW 的完整逻辑框架：
1.  **ROI 定义**：通过 `leftDowRoi` 和 `rightDowRoi` 定义左右两侧的监测区域。
2.  **目标筛选**：在 ROI 内检测到的目标，经过 `objAttribCal` 处理后的类型（Car, MotoBike, Pedestrian 等）和动态属性（Crossing, Moving 等）被用于判断是否触发报警。
3.  **状态管理**：通过 `dowSystemState` 管理功能状态（Init, Standby, Active, Off 等）。
4.  **报警输出**：通过 `bLeftDowWarning` / `bRightDowWarning` 输出分级报警信号。

## 2. 状态机
根据 `adasWarningStruct` 中的定义，DOW 功能的状态机包含以下状态：

| 状态值 | 状态名称 | 含义 |
| :--- | :--- | :--- |
| 0 | None | 未定义/初始状态 |
| 1 | Init | 初始化状态，系统自检或参数加载 |
| 2 | Standby | 待机状态，功能已使能但条件未满足（如车速过高） |
| 3 | Active | 激活状态，功能正常工作，监测 ROI 内目标 |
| 4 | Off | 关闭状态，用户手动关闭或系统禁用 |
| 5 | Failure | 故障状态，传感器或算法异常 |
| 6 | Passive | 被动状态，可能指降级运行或仅记录不报警 |

**状态转换条件推断：**
*   **Init -> Active**: 当 `bDOWEnable` 为真，且车辆处于静止或极低速度（通常 DOW 在车速 < 5km/h 或 0km/h 时激活），且雷达自检通过。
*   **Active -> Standby/Off**: 当车速超过阈值（例如 > 10km/h，具体阈值未在片段中直接给出，但 DOW 通常只在停车时工作），或用户关闭功能。
*   **Active -> Failure**: 当雷达检测到内部错误、信号丢失或目标跟踪失效时。

## 3. 报警/制动逻辑
DOW 是预警功能，**不涉及制动请求**（制动由 AEB 或 RCTB 等功能负责）。其报警逻辑基于目标在 DOW ROI 内的存在、类型及相对运动。

### 触发报警条件 (Trigger)
1.  **ROI 检测**：目标位于 `leftDowRoi` 或 `rightDowRoi` 定义的区域内。
2.  **目标有效性**：目标必须被成功跟踪，且 `objType` 为有效类型（Car, MotoBike, Pedestrian, Cyclist）。
    *   代码中 `ObjType_Car` (4), `ObjType_MotoBike` (3), `ObjType_Pedestrian` (1) 等被重点处理。
3.  **动态属性**：
    *   目标具有横向运动趋势或接近趋势。
    *   代码中 `DynProp_Crossing` (交叉交通) 和 `radialVelMeas > 0.0f` (径向速度，表示接近) 是关键判断依据。
4.  **类型保持/确认**：
    *   通过 `TypeKeepCountUpdate` 和 `ObjTypeHold` 确保目标类型识别的稳定性，避免误报。
    *   例如：对于 `DynProp_Crossing` 的目标，如果 `distY > 60.0f`，则强制保持类型 (`isKeep_far = true`)，防止因距离远导致分类跳变。

### 取消报警条件 (Cancel)
1.  **目标离开 ROI**：目标移出 `leftDowRoi` / `rightDowRoi`。
2.  **目标消失**：目标跟踪丢失 (`lifeCycle` 结束或 `objID` 失效)。
3.  **类型降级**：如果目标被重新分类为非危险类型（如静态物体、护栏），且通过 `ObjTypeDownGrade` 逻辑确认。
4.  **时间滤波**：报警通常有去抖逻辑（如 `KEEPWARNINGFRM` 或 `LOWSPEEDKEEPWARNINGFRM`），需持续满足条件一定帧数才报警，反之亦然。

## 4. 关键阈值
以下阈值来自 `objAttribCal.c` 和 `paraDefine.h`，直接影响 DOW 的目标识别和报警稳定性：

| 阈值名称 | 值 | 单位 | 说明 |
| :--- | :--- | :--- | :--- |
| `distY` (Far) | 60.0 | m | 远距离边界。在 `ObjTypeHold` 中，若 `distY > 60.0f` 且为 Crossing 目标，强制保持类型。 |
| `distY` (Mid) | 20.0 | m | 中距离边界。在 `TypeKeepCountUpdate` 和 `ObjTypeHold` 中用于判断是否覆盖或调整降级阈值。 |
| `distY` (Near) | 25.0 | m | 近场边界。在 `TypeKeepCountUpdate` 中，`distY > 25.0f` 是某些计数更新的前提。 |
| `distX` (Longitudinal) | 5.0 | m | 纵向距离阈值。在 `TypeKeepCountUpdate` 中，`distX <= 5.0f` 且 `carSpd < 0.05f` 时，对行人有特殊处理。 |
| `distX` (Longitudinal) | 20.0 | m | 纵向距离阈值。在 `TypeKeepCountUpdate` 中，`distX <= 20.0f` 且 `distY <= 60.0f` 时，判断是否被覆盖 (`JudgeCovered`)。 |
| `carSpd` (Ego Speed) | 0.05 | m/s | 自车静止阈值。用于判断车辆是否真正静止，影响行人检测逻辑。 |
| `lifeCycle` | 30 | frames | 目标生命周期阈值。在 `ObjTypeHold` 中，`lifeCycle >= 30U` 是触发类型保持或覆盖逻辑的条件。 |
| `KEEPWARNINGFRM` | 3 | frames | 报警保持帧数。用于报警去抖，确保报警稳定。 |
| `LOWSPEEDKEEPWARNINGFRM` | 6 | frames | 低速报警保持帧数。低速下可能需要更长的确认时间。 |
| `Type_Down_Thred` | (未直接给出数值，但在代码中引用) | - | 类型降级阈值。用于控制目标类型从高级别（如 Car）降为低级别的灵敏度。 |

## 5. 关键变量

| 变量名 | 类型 | 来源 | 含义 |
| :--- | :--- | :--- | :--- |
| `bDOWEnable` | `bool` | `adasEnableStruct` | DOW 功能使能标志。 |
| `dowSystemState` | `uint8_t` | `adasWarningStruct` | DOW 功能当前状态机状态 (0-6)。 |
| `leftDowRoi` / `rightDowRoi` | `polygonLargerStruct` | `adasROIStruct` | 左右 DOW 监测区域的几何定义。 |
| `leftDowFlag` / `rightDowFlag` | `bool` | `objStruct` (perception output) | 当前帧左侧/右侧 DOW 报警标志（底层感知层输出）。 |
| `bLeftDowWarning` / `bRightDowWarning` | `uint8_t` | `adasWarningStruct` | 最终输出的 DOW 报警等级 (0:正常, 1:一级报警, 2:二级报警)。 |
| `objDowWarningFlag` | `int8_t` | `objStruct` | 单个目标的 DOW 报警标志，关联到具体目标 ID。 |
| `objType` | `uint8_t` | `objStruct` | 目标类型 (1:Ped, 2:Cyclist, 3:Moto, 4:Car, 5:Truck)。 |
| `dynFlg` | `uint8_t` | `objStruct` | 目标动态属性 (如 `DynProp_Crossing`)。 |
| `distX` / `distY` | `float` | `objStruct` | 目标相对于自车的纵向和横向距离。 |
| `radialVelMeas` | `float` | `objStruct` | 目标径向速度，用于判断接近/远离。 |
| `isCovered` | `bool` | `JudgeCovered()` | 目标是否被其他目标遮挡，影响类型保持逻辑。 |
| `typeDownNum` / `typeUpNum` | `uint8_t` | `objClassAttrib` | 类型降级/升级计数器，用于平滑目标类型变化。 |

## 6. 输入信号
1.  **雷达原始数据/跟踪目标**：
    *   目标 ID (`objID`)
    *   位置 (`distX`, `distY`)
    *   速度 (`radialVelMeas`, `velY`)
    *   尺寸 (`length`, `width`)
    *   初始分类 (`ObjType`)
2.  **自车状态**：
    *   车速 (`g_egoCarAddInfo.carSpd`)：用于判断是否处于 DOW 激活车速范围。
    *   转向角/航向角 (`yawAng`)：用于 ROI 投影和坐标系转换。
3.  **功能配置**：
    *   `bDOWEnable`：用户或系统使能信号。
    *   `adasROIStruct`：DOW 监测区域的多边形顶点坐标。
4.  **环境标志**：
    *   `g_jamSceneFlg`：拥堵场景标志，影响目标遮挡判断逻辑。

## 7. 输出信号
1.  **报警等级**：
    *   `bLeftDowWarning`：左侧开门预警等级 (0/1/2)。
    *   `bRightDowWarning`：右侧开门预警等级 (0/1/2)。
2.  **目标级报警标志**：
    *   `objDowWarningFlag`：每个跟踪目标是否触发 DOW 报警。
3.  **系统状态**：
    *   `dowSystemState`：当前功能状态，用于 HMI 显示或故障诊断。

## 8. 与其他功能的交互
1.  **BSD (Blind Spot Detection)**：
    *   **共享 ROI 逻辑**：DOW 和 BSD 都监测侧后方区域，但 DOW 更关注近距离、低速/静止场景，且 ROI 可能更靠近车门。
    *   **目标共享**：两者共用 `objStruct` 中的目标跟踪数据。BSD 通常在车速 > 10km/h 时激活，DOW 在车速 < 5km/h 时激活，两者在时间上互补。
2.  **RCTA (Rear Cross Traffic Alert)**：
    *   **逻辑相似性**：RCTA 监测倒车时的交叉交通，DOW 监测停车时的侧后方交通。代码中 `DynProp_Crossing` 的处理逻辑在两者中可能通用。
    *   **ROI 重叠**：`leftRctaRoi` / `rightRctaRoi` 与 `leftDowRoi` / `rightDowRoi` 在空间上可能有重叠，但触发条件不同（RCTA 需倒车挡位，DOW 需停车挡位或手刹拉起）。
3.  **目标分类模块 (`objAttribCal`)**：
    *   DOW 严重依赖 `objAttribCal` 输出的稳定 `objType`。代码中的 `TypeKeepCountUpdate` 和 `ObjTypeHold` 逻辑确保了在 DOW 关键区域（如 `distY < 20m`）内，目标类型不会因短暂测量误差而跳变，从而避免误报警。
4.  **HMI (Human Machine Interface)**：
    *   `bLeftDowWarning` / `bRightDowWarning` 直接驱动后视镜指示灯或仪表盘提示音。