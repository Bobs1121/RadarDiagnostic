# RCTA 功能分析

## 1. 功能概述
**RCTA (Rear Cross Traffic Alert)**，即后方交叉交通警报，是角雷达（Corner Radar）在低速泊车或倒车场景下的核心安全功能。其目的是检测车辆后方左右两侧横向穿过的动态目标（如车辆、行人、自行车），并在潜在碰撞风险发生时向驾驶员发出警报。

根据提供的源码片段，该功能主要涉及以下逻辑模块：
1.  **目标筛选与属性判断**：通过 `AssignThinFlg` 函数，结合自车速度、目标运动状态、场景标志（如拥堵、交叉场景）来过滤无效目标或调整目标置信度。
2.  **轨迹关联与评分**：在 `track.c` 中，通过计算预测位置与聚类中心的位置偏差（`RxDif`, `RyDif`），结合门限（Gate）判断是否将当前聚类关联到现有轨迹。
3.  **特殊场景处理**：针对栅栏（Fence）、静止大车（Truck）、拥堵（Jam）等场景有专门的逻辑分支，以防止误报或漏报。
4.  **警告标志输出**：最终通过 `objRctaWarningFlag` 和 `adasWarningStruct` 中的 `bLeft/RightRctaWarning` 输出报警状态。

## 2. 状态机
虽然提供的代码片段主要集中在感知层（Perception）的目标跟踪和属性赋值，未直接展示完整的 RCTA 应用层状态机，但结合 `perception_public_def.h` 中的定义，可以推断 RCTA 的系统状态机如下：

*   **状态定义**:
    *   `0`: None (未定义/空闲)
    *   `1`: Init (初始化)
    *   `2`: Standby (待机，功能启用但条件不满足)
    *   `3`: Active (激活，正在监测)
    *   `4`: Off (关闭)
    *   `5`: Failure (故障)
    *   `6`: Passive (被动/降级模式)

*   **状态转换逻辑 (推断)**:
    *   **Init -> Standby**: 系统自检通过，`g_adasEnable.bRCTAEnable` 为 true。
    *   **Standby -> Active**: 自车速度低于阈值（`TRACK_MaxRCTAEgoCarV`，通常为 6m/s 或更低），且档位为 R 档（倒车）或 P 档（停车），且无系统故障。
    *   **Active -> Standby**: 自车速度超过阈值，或档位切换至 D/N 档，或功能被手动关闭。
    *   **Active -> Failure**: 雷达硬件故障、校准失效或信号干扰严重（参考 `algoExtraStruct` 中的干扰状态）。
    *   **Active -> Off**: 用户手动禁用 RCTA 功能。

## 3. 报警/制动逻辑
*注意：RCTA 通常仅包含警报（Alert），制动（Brake）属于 RCTB (Rear Cross Traffic Braking)。但在感知层，两者共用目标检测逻辑。*

### 3.1 目标有效性判断 (AssignThinFlg 逻辑)
在 `track.c` L1290-L1348 中，`AssignThinFlg` 函数决定了目标是否被“稀释”（Thin，即降低置信度或标记为不可靠），这直接影响后续是否触发报警。

*   **触发“稀释”（降低报警优先级/忽略）的条件**:
    1.  **高速大转弯**: 自车速度 $\ge$ `TRACK_MaxRCTAEgoCarV` (6.0 m/s) 且横摆角速度 < `TRACK_BigTurnYawRate` (5.0 rad/s)，且聚类运动标志与目标运动标志不一致。此时标记 `velThinFlg` 和 `distThinFlg` 为 true。
    2.  **低速非交叉场景下的特定静止/慢速目标**:
        *   自车速度 < 6.0 m/s。
        *   非交叉场景 (`g_crossSceneFlg == 0`)。
        *   目标被标记为移动 (`isMoveFlg == 1`) 但动态属性非交叉 (`dynFlg != Crossing`)。
        *   且目标不是“长时间静止且低速”的特殊情况。
        *   若聚类本身是静止的 (`clusterInfo->clusterData[cluCt].isMoveFlg == 0`)，则标记距离稀释 (`distThinFlg = true`)。
        *   若存在路沿 (`curbFlg != 0`) 或拥堵场景 (`JamScene_JamStopped`)，则同时标记速度稀释 (`velThinFlg = true`)。
    3.  **拥堵场景下的静止目标**:
        *   自车速度 < 6.0 m/s。
        *   目标为静止 (`Stationary` 或 `Stopped`)。
        *   场景为拥堵停止 (`JamScene_JamStopped`)。
        *   聚类被标记为移动。
        *   结果：标记距离稀释 (`distThinFlg = true`)。
    4.  **静止卡车**: 若目标类型为卡车 (`ObjType_Truck`) 且状态为停止 (`DynProp_Stopped`)，标记距离稀释。

*   **正常处理（不稀释）的条件**:
    *   目标被正确识别为交叉交通 (`DynProp_Crossing`)。
    *   目标为行人、自行车等高风险目标，且在有效 ROI 内。

### 3.2 轨迹关联与报警触发
在 L1768-L1788 中，展示了轨迹关联的门限判断：
*   **关联条件**:
    *   横向偏差 `RyDifHoz` 在门限范围内 (`-gateYMinRatio * RyGate` 到 `gateYMaxRxatio * RyGate`)。
    *   纵向偏差 `RxDifHozAbs` 在门限范围内 (`gateXMin` 到 `gateXMax`) **或者** 目标在预测的纵向范围内。
*   **栅栏场景过滤 (L1780-L1788)**:
    *   如果自车速度 < 6.0 m/s，聚类为静止，且目标被标记为横向 (`hozCanFlg == 1`)。
    *   若聚类点数少 (`dotNum <= 2`) 且位置关系符合栅栏特征，则取消关联 (`ifMarkRAll = false`)，防止将栅栏误判为交叉目标。

### 3.3 报警输出
*   一旦目标被成功关联并确认为 RCTA 相关目标，`objRctaWarningFlag` 将被置位。
*   在 `adasWarningStruct` 中，`bLeftRctaWarning` 或 `bRightRctaWarning` 会根据目标位于左侧或右侧 ROI (`leftRctaRoi` / `rightRctaRoi`) 而置位。
*   报警级别通常分为：
    *   `0`: Normal (无报警)
    *   `1`: First Warning (一级报警，视觉/声音提示)
    *   `2`: Second Warning (二级报警，更强烈的提示，可能伴随制动请求前兆，若集成 RCTB)

## 4. 关键阈值
| 阈值名称 | 定义位置 | 值 | 含义 |
| :--- | :--- | :--- | :--- |
| `TRACK_MaxRCTAEgoCarV` | `paraDefine.h` L111 | `6.0f` (m/s) | RCTA 功能生效的最大自车速度。超过此速度，RCTA 逻辑可能降级或关闭。 |
| `TRACK_BigTurnYawRate` | `paraDefine.h` L114 | `5.0f` (rad/s) | 大转弯横摆角速度阈值。用于判断是否处于急转弯状态，影响目标筛选。 |
| `TRACK_BigTurnYawRateL` | `paraDefine.h` L115 | `8.0f` (rad/s) | 更大转弯阈值，可能用于更严格的过滤。 |
| `System_LaneWidth` | 代码中引用 | 未定义具体值 | 车道宽度，用于判断目标是否在同一车道或相邻车道，以及栅栏场景判断。 |
| `gateXMin/gateXMax` | 代码中引用 | 未定义具体值 | 纵向关联门限，用于判断聚类是否属于当前轨迹。 |
| `gateYMinRatio/gateYMaxRxatio` | 代码中引用 | 未定义具体值 | 横向关联门限比例，用于判断横向偏差是否可接受。 |
| `TRACK_delayLifeCycle` | `paraDefine.h` L119 | `15` | 轨迹延迟生命周期，可能用于报警迟滞或目标消失后的保持时间。 |
| `KEEPWARNINGFRM` | `paraDefine.h` L143 | `3U` | 保持报警的帧数，用于防止报警闪烁。 |
| `LOWSPEEDKEEPWARNINGFRM` | `paraDefine.h` L144 | `6U` | 低速下保持报警的帧数。 |

## 5. 关键变量
| 变量名 | 类型 | 来源 | 含义 |
| :--- | :--- | :--- | :--- |
| `g_egoCarAddInfo.carSpd` | `float` | 全局变量/自车信息 | 自车当前速度，是 RCTA 激活和目标筛选的核心条件。 |
| `g_egoCarInfo.yaw_rate` | `float` | 全局变量/自车信息 | 自车横摆角速度，用于判断转弯状态。 |
| `g_crossSceneFlg` | `uint8_t` | 全局变量/场景识别 | 交叉场景标志。0 表示非交叉场景，影响目标稀释逻辑。 |
| `g_jamSceneFlg` | `uint8_t` | 全局变量/场景识别 | 拥堵场景标志。`JamScene_JamStopped` 表示拥堵停止，影响静止目标处理。 |
| `pTemp->dynFlg` | `uint8_t` | 目标结构体 `objStruct` | 目标动态属性。关键值：`DynProp_Crossing` (交叉), `DynProp_Stationary` (静止), `DynProp_Stopped` (停止)。 |
| `pTemp->isMoveFlg` | `uint8_t` | 目标结构体 `objStruct` | 目标移动标志。1 表示移动，0 表示静止。 |
| `pTemp->hozCanFlg` | `uint8_t` | 目标结构体 `objStruct` | 横向候选标志。1 表示目标被识别为横向运动，是 RCTA 的关键特征。 |
| `clusterInfo->clusterData[cluCt].isMoveFlg` | `uint8_t` | 聚类结构体 | 当前帧聚类的移动标志，用于与轨迹目标状态比对。 |
| `clusterInfo->clusterData[cluCt].curbFlg` | `uint8_t` | 聚类结构体 | 路沿标志。用于识别路沿附近的静止目标，防止误报。 |
| `objRctaWarningFlag` | `int8_t` | 目标输出结构体 | 单个目标的 RCTA 报警标志。 |
| `bLeftRctaWarning` / `bRightRctaWarning` | `uint8_t` | `adasWarningStruct` | 系统级左右侧 RCTA 报警状态输出。 |
| `g_adasEnable.bRCTAEnable` | `bool` | `adasEnableStruct` | RCTA 功能使能标志。 |
| `leftRctaRoi` / `rightRctaRoi` | `polygonLargerStruct` | `adasROIStruct` | RCTA 左右侧感兴趣区域（ROI）定义，用于限制检测范围。 |

## 6. 输入信号
1.  **自车状态**:
    *   车速 (`carSpd`)
    *   横摆角速度 (`yaw_rate`)
    *   档位 (隐含在场景判断中，通常 RCTA 仅在 R/P 档激活)
2.  **雷达感知数据**:
    *   聚类信息 (`clusterInfo`): 包括位置 (`distX`, `distY`)、速度、运动标志 (`isMoveFlg`)、路沿标志 (`curbFlg`)、点数 (`dotNum`)。
    *   目标轨迹信息 (`objStruct`): 包括预测位置、动态属性 (`dynFlg`)、类型 (`objType`)、横向标志 (`hozCanFlg`)。
3.  **场景标志**:
    *   `g_crossSceneFlg`: 交叉场景标志。
    *   `g_jamSceneFlg`: 拥堵场景标志。
4.  **配置参数**:
    *   `g_adasEnable.bRCTAEnable`: 功能开关。
    *   `g_adasRoi`: ROI 多边形定义。

## 7. 输出信号
1.  **报警标志**:
    *   `objRctaWarningFlag`: 每个目标的报警状态。
    *   `bLeftRctaWarning` / `bRightRctaWarning`: 系统级左右报警状态（0: 正常, 1: 一级报警, 2: 二级报警）。
2.  **目标属性更新**:
    *   `velThinFlg` / `distThinFlg`: 用于内部逻辑的目标置信度稀释标志。
    *   `ifMarkRAll`: 轨迹关联成功标志。
3.  **调试/记录数据**:
    *   `objOutEDRStruct` 中的 `objRctaWarningFlag` 用于事件数据记录。

## 8. 与其他功能的交互
1.  **RCTB (Rear Cross Traffic Braking)**:
    *   RCTA 是 RCTB 的前置条件。RCTA 检测到目标并报警后，若距离进一步缩短且满足制动条件，RCTB 将介入。
    *   两者共用相同的感知输入和目标筛选逻辑（如 `AssignThinFlg`）。
    *   `g_adasEnable` 结构中同时包含 `bRCTAEnable` 和 `bRCTBEnable`，表明它们可独立配置，但逻辑紧密耦合。
2.  **BSD (Blind Spot Detection) / LCA (Lane Change Assist)**:
    *   在低速泊车场景（RCTA 激活时），BSD/LCA 通常被抑制或降级，因为 ROI 和逻辑重点转移到后方横向。
    *   `g_adasRoi` 中定义了独立的 `leftBsdRoi` 和 `leftRctaRoi`，表明它们在空间上是分离的，避免冲突。
3.  **DOW (Door Open Warning)**:
    *   DOW 也关注后方目标，但侧重于静止或慢速接近的目标，且通常在车辆停稳后激活。
    *   RCTA 侧重于横向穿越的动态目标。
    *   两者可能共享部分目标检测资源，但报警逻辑独立。
4.  **场景识别模块**:
    *   依赖 `g_crossSceneFlg` 和 `g_jamSceneFlg` 等全局标志，这些标志由更高层的场景识别算法提供，用于优化 RCTA 在不同环境下的表现。