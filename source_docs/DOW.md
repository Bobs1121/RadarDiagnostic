# DOW 功能分析

## 1. 功能概述
DOW (Door Open Warning，开门预警) 功能旨在当车辆静止或低速行驶时，监测车辆侧后方盲区内的动态目标（如行人、骑行者、车辆）。当检测到有碰撞风险的目标接近车门区域时，系统通过视觉或听觉报警提醒驾驶员，防止因贸然开门导致交通事故。

从提供的源码片段来看，DOW 的核心逻辑依赖于高精度的**目标分类（Object Classification）**和**目标跟踪（Tracking）**。代码主要展示了感知层（Perception）如何根据目标的距离、速度、运动状态（Crossing）以及历史类型置信度，来维持或更新目标的类型（Pedestrian, MotoBike, Car, Truck 等），这是 DOW 判断是否触发报警的基础前提。

## 2. 状态机
根据 `perception_public_def.h` 中的定义，DOW 功能具有标准的 ADAS 功能状态机：

*   **状态定义**:
    *   `0`: None (未定义/初始)
    *   `1`: Init (初始化中)
    *   `2`: Standby (待机，功能可用但未激活)
    *   `3`: Active (激活，正在监测并可能报警)
    *   `4`: Off (关闭)
    *   `5`: Failure (故障)
    *   `6`: Passive (被动模式，通常指受限模式)

*   **状态转换条件** (基于通用 ADAS 逻辑推断，源码中主要体现 `bDOWEnable` 和 `dowSystemState`):
    *   **Init -> Standby**: 系统自检通过，雷达数据正常，车辆状态满足基本条件（如车速 < 阈值，通常为 0-5 km/h）。
    *   **Standby -> Active**: 驾驶员未关闭功能，且车辆处于静止或极低速状态（`g_egoCarAddInfo.carSpd < 0.05f` 在代码 L1262 中暗示了静止检测的重要性）。
    *   **Active -> Standby/Off**: 车速超过阈值（如 > 10-15 km/h），或驾驶员手动关闭，或检测到故障。
    *   **Any -> Failure**: 雷达硬件故障、信号干扰严重、校准失败。

## 3. 报警/制动逻辑
虽然提供的代码片段主要集中在**目标属性计算（objAttribCal）**而非最终的报警触发逻辑，但可以从变量定义和分类逻辑中推导出 DOW 的报警核心机制：

1.  **目标有效性判断**:
    *   目标必须位于 DOW 的 ROI 区域内 (`leftDowRoi`, `rightDowRoi`)。
    *   目标类型必须被确认为潜在威胁（行人、自行车、摩托车、汽车、卡车）。代码 L1262 特别关注 `ObjType_Pedestrian` 在静止场景下的处理。
    *   目标必须是动态的或正在穿越（`DynProp_Crossing`），静态护栏或固定物体通常被过滤（通过 `curbNum` 等逻辑）。

2.  **报警触发条件 (推断)**:
    *   **距离阈值**: 目标进入车门开启范围（通常横向距离 `distY` 在 1.5m - 3.0m 以内，纵向距离 `distX` 在车身后方一定范围内）。
    *   **相对速度**: 目标具有向车辆侧方接近的速度分量。
    *   **类型置信度**: 目标类型分类稳定（`typeUpNum` 和 `typeDownNum` 计数达到阈值，确保不是误检）。
    *   **状态保持**: 报警通常有防抖逻辑，如 `KEEPWARNINGFRM` (3帧) 或 `LOWSPEEDKEEPWARNINGFRM` (6帧) 来确保持续存在。

3.  **报警取消条件**:
    *   目标离开 ROI 区域。
    *   目标消失（跟踪丢失）。
    *   车辆开始行驶（车速超过 DOW 工作阈值）。
    *   报警持续时间超过最大限制。

4.  **制动请求**:
    *   DOW 通常**不直接控制制动**，而是通过 HMI 报警。但在某些高级集成系统中，如果 DOW 检测到极高碰撞风险且驾驶员无反应，可能会联动 AEB 或发出强烈警告。源码中 `fBrakeValue` 和 `fBrakeEventTime` 存在，但 DOW 本身主要输出 `bLeftDowWarning` / `bRightDowWarning`。

## 4. 关键阈值
从 `objAttribCal.c` 和 `paraDefine.h` 中提取的关键阈值：

| 参数 | 值 | 单位 | 说明 |
| :--- | :--- | :--- | :--- |
| `carSpd` (静止判断) | `< 0.05` | m/s (约 0.18 km/h) | L1262: 用于判断车辆是否静止，影响行人分类逻辑 |
| `distX` (纵向距离) | `<= 5.0` | m | L1261, L1362: 近距离判断，用于行人/近距离目标分类保持 |
| `distX` (中距离) | `<= 20.0` | m | L1264: 中距离目标分类保持逻辑 |
| `distY` (横向距离) | `> 25.0` | m | L1259: 远距离条件1 |
| `distY` (横向距离) | `<= 60.0` | m | L1260: 远距离条件2 |
| `distY` (横向距离) | `<= 20.0` | m | L1345, L1467: 交叉交通/近距离分类降级逻辑 |
| `distY` (横向距离) | `> 60.0` | m | L1461: 远距离交叉目标保持 |
| `distY` (横向距离) | `<= 3.0` | m | L1363: 极近距离条件，用于类型升级判断 |
| `lifeCycle` | `>= 30` | frames | L1486, L1496: 目标生命周期阈值，用于遮挡/FOV变化时的类型保持 |
| `KEEPWARNINGFRM` | `3` | frames | L143: 报警保持最小帧数 |
| `LOWSPEEDKEEPWARNINGFRM` | `6` | frames | L144: 低速报警保持帧数 |

## 5. 关键变量

| 变量名 | 类型 | 来源 | 含义 |
| :--- | :--- | :--- | :--- |
| `bDOWEnable` | `bool` | `adasEnableStruct` | DOW 功能使能标志，由上层应用或用户设置 |
| `dowSystemState` | `uint8_t` | `adasWarningStruct` | DOW 功能当前状态机状态 (0-6) |
| `bLeftDowWarning` | `uint8_t` | `adasWarningStruct` | 左侧 DOW 报警级别 (0:正常, 1:一级报警, 2:二级报警) |
| `bRightDowWarning` | `uint8_t` | `adasWarningStruct` | 右侧 DOW 报警级别 |
| `leftDowFlag` | `bool` | `adasWarningStruct` | 左侧 DOW 报警触发标志 |
| `rightDowFlag` | `bool` | `adasWarningStruct` | 右侧 DOW 报警触发标志 |
| `objDowWarningFlag` | `int8_t` | `objStruct` | 单个目标对象的 DOW 报警标志，用于关联具体目标 |
| `objType` | `uint8_t` | `objStruct` | 目标类型 (1:Ped, 2:Cyclist, 3:Moto, 4:Car, 5:Truck) |
| `dynFlg` | `uint8_t` | `objStruct` | 目标动态属性 (如 `DynProp_Crossing` 表示交叉穿越) |
| `distX` | `float` | `objStruct` | 目标相对于自车的纵向距离 (米) |
| `distY` | `float` | `objStruct` | 目标相对于自车的横向距离 (米) |
| `typeUpNum` | `uint8_t` | `objClassAttrib` | 目标类型升级计数，用于提高分类置信度 |
| `typeDownNum` | `uint8_t` | `objClassAttrib` | 目标类型降级计数，用于降低分类置信度 |
| `isKeep_far/near` | `bool` | `objHisTypeInf` | 目标类型在远/近处是否保持不变的标志，防止频繁跳变 |
| `g_egoCarAddInfo.carSpd` | `float` | Global | 自车当前速度，DOW 仅在低速/静止时有效 |

## 6. 输入信号
1.  **雷达原始数据/跟踪目标**:
    *   目标 ID (`objID`)
    *   位置 (`distX`, `distY`)
    *   速度 (`radialVelMeas`, `velX`, `velY`)
    *   尺寸 (`length`, `width`)
    *   航向角 (`yawAng`)
2.  **自车状态**:
    *   车速 (`carSpd`)
    *   转向角 (间接影响 ROI 计算)
    *   档位 (P/R/N/D，DOW 通常在 P/R 档激活)
3.  **功能配置**:
    *   `bDOWEnable`: 功能开关
    *   `adasROIStruct`: DOW 感兴趣区域 (ROI) 的多边形顶点定义

## 7. 输出信号
1.  **报警状态**:
    *   `bLeftDowWarning` / `bRightDowWarning`: 左右侧报警等级。
    *   `leftDowFlag` / `rightDowFlag`: 报警布尔标志。
2.  **目标关联信息**:
    *   `objDowWarningFlag`: 标识哪个具体目标触发了报警，用于 HMI 显示目标位置。
3.  **系统状态**:
    *   `dowSystemState`: 当前功能状态，用于诊断和 HMI 显示功能可用性。

## 8. 与其他功能的交互
1.  **BSD (Blind Spot Detection)**:
    *   **共享感知数据**: DOW 和 BSD 共享相同的角雷达感知目标列表和 ROI 定义（`leftBsdRoi` vs `leftDowRoi`）。
    *   **逻辑差异**: BSD 关注行驶中的侧后方目标，DOW 关注静止/低速下的侧后方目标。两者在目标分类（`objType`）和动态属性（`dynFlg`）的判断逻辑上高度复用。
2.  **LCA (Lane Change Assist)**:
    *   LCA 是 BSD 的延伸，通常在打转向灯时激活。DOW 与 LCA 在低速下可能存在逻辑互斥或优先级判断，例如在停车开门时，LCA 通常不工作，而 DOW 工作。
3.  **RCTA/RCTB (Rear Cross Traffic Alert/Brake)**:
    *   **场景重叠**: RCTA 主要关注倒车时的后方交叉交通。DOW 关注静止停车时的侧方交通。
    *   **目标分类复用**: 代码中 `DynProp_Crossing` 的处理逻辑（L1330, L1346, L1459）同时服务于 RCTA 和 DOW，确保交叉穿越目标被正确识别和保持。
4.  **HMI (Human Machine Interface)**:
    *   DOW 的报警输出直接驱动外后视镜上的指示灯闪烁或仪表盘上的图形提示。
5.  **标定系统 (Calibration)**:
    *   DOW 的 ROI 依赖于雷达安装角度的标定结果。如果 `InCalibState` 为 `Failed`，DOW 将进入 `Failure` 状态。