# BSD 功能分析

## 1. 功能概述
基于提供的源码片段，BSD (Blind Spot Detection，盲区检测) 功能主要依赖于角雷达（Corner Radar）的感知层（Perception）数据。该功能的核心逻辑包括：
1.  **目标跟踪与聚类**：通过 `track.c` 中的逻辑对雷达点云进行聚类，筛选出有效的动态或静态目标。
2.  **ROI 判定**：根据车辆速度、目标相对位置（distX, distY）和速度，判断目标是否进入 BSD 的感兴趣区域（ROI）。
3.  **状态管理**：维护 BSD 系统的运行状态（Init, Standby, Active 等）。
4.  **报警触发**：当有效目标位于盲区且满足持续时间和速度条件时，触发左侧或右侧报警。

*注意：提供的代码主要集中在感知层的目标跟踪（Track）、门限计算（Gate）和数据结构定义上，具体的 BSD 业务逻辑（如具体的 ROI 多边形判断、报警计时器逻辑）可能在未提供的 `adas_bsd.c` 或类似文件中，但可以从变量定义和跟踪逻辑中推断出其依赖条件。*

## 2. 状态机
根据 `perception_public_def.h` 中的定义，BSD 系统状态机包含以下状态：

*   **状态定义**:
    *   `0`: None (未定义/初始)
    *   `1`: Init (初始化)
    *   `2`: Standby (待机 - 通常指车速过低或传感器未就绪，功能不可用)
    *   `3`: Active (激活 - 功能正常工作，可报警)
    *   `4`: Off (关闭 - 用户手动关闭或系统故障)
    *   `5`: Failure (故障)
    *   `6`: Passive (被动/降级模式)

*   **状态转换条件推断**:
    *   **None -> Init**: 系统上电，初始化完成。
    *   **Init -> Standby/Active**: 取决于车速 (`g_egoCarAddInfo.carSpd`) 和传感器健康状态。通常车速低于阈值（如 10-15 km/h）进入 Standby，高于阈值进入 Active。
    *   **Active -> Standby**: 车速降低至阈值以下。
    *   **Active -> Failure**: 检测到雷达内部故障或数据无效。
    *   **Active -> Off**: 用户通过 HMI 关闭功能。
    *   **Standby/Active -> Passive**: 可能由于信号干扰或校准问题，功能受限运行。

*关键变量*: `g_adasWarning.bsdSystemState` (uint8_t)

## 3. 报警/制动逻辑

### 报警触发条件 (Trigger)
虽然具体的 ROI 判断代码未在片段中完整展示，但根据 `track.c` 和结构体定义，触发 BSD 报警需满足以下条件：
1.  **目标有效性**: 目标必须通过跟踪滤波，`clusterStat` 有效，且非幽灵目标 (`ghostProb` 低)。
2.  **位置判定**: 目标位于左侧或右侧 BSD ROI 内 (`leftBsdRoi` / `rightBsdRoi`)。
    *   通常 BSD ROI 位于车辆侧后方，纵向距离 `distX` 在 -10m 到 +5m 左右（具体取决于标定），横向距离 `distY` 在 2m 到 4m 左右。
3.  **速度判定**:
    *   目标相对速度需在一定范围内。代码中 `SetTrcGateVel` 显示了对低速目标 (`MthCluster_VelGateSlow`) 和高速目标的不同处理。
    *   如果目标静止 (`dynFlg == DynProp_Stationary`) 且位于特定区域，可能被忽略或特殊处理（见 L502-L509）。
4.  **持续计数**: 目标必须在 ROI 内持续存在一定帧数。
    *   宏定义 `KEEPWARNINGFRM 3U` 和 `LOWSPEEDKEEPWARNINGFRM 6U` 暗示了报警保持的帧数要求。低速时可能需要更长的确认时间以防误报。

### 报警取消条件 (Cancel)
1.  **目标离开 ROI**: 目标移出 `leftBsdRoi` 或 `rightBsdRoi`。
2.  **目标消失**: 跟踪目标丢失 (`clusterStat` 变为无效)。
3.  **状态变更**: BSD 系统状态从 `Active` 变为 `Standby` 或 `Off`。
4.  **超时**: 如果目标短暂进入又离开，报警计数器清零。

### 报警等级
*   `objOutDataStruct` 和 `objOutEDRStruct` 中定义了 `objBsdWarningFlag` 和 `bLeftBsdWarning`/`bRightBsdWarning`。
*   报警等级通常为：
    *   `0`: Normal (无报警)
    *   `1`: First Warning (一级报警，通常为视觉提示)
    *   `2`: Second Warning (二级报警，可能伴随声音或更强的视觉提示，通常用于 LCA 变道辅助，但 BSD 也可能有分级)

## 4. 关键阈值

| 阈值名称 | 代码位置/宏定义 | 数值/描述 | 用途 |
| :--- | :--- | :--- | :--- |
| `MthCluster_CluDiffX` | L180 | 未给出具体值 | 聚类合并时，纵向距离差异阈值 |
| `MthCluster_CluDiffY` | L181 | 未给出具体值 | 聚类合并时，横向距离差异阈值 |
| `MthCluster_CluDiffVel` | L182 | 未给出具体值 | 聚类合并时，速度差异阈值 |
| `MthCluster_VelGateStacEnv` | L500, L505 | 未给出具体值 | 静止环境速度门限，用于判断目标是否绝对静止 |
| `MthCluster_VelGateEnd` | L505, L512 | 未给出具体值 | 纵向速度门限 |
| `MthCluster_VelGateSlow` | L520 | 未给出具体值 | 低速目标速度门限 |
| `MthCluster_VelGate` | L518, L538 | 未给出具体值 | 常规速度门限 |
| `MthCluster_VelGateMax` | L542, L551 | 未给出具体值 | 最大速度门限 |
| `MthCluster_VelGateTurn` | L526 | 未给出具体值 | 转弯场景速度门限 |
| `CandToObj_NearDistXDelTwice` | L518 | 未给出具体值 | 近距纵向距离判断 |
| `System_LaneWidth` | L502 | 未给出具体值 | 车道宽度，用于判断目标是否在车道内 |
| `KEEPWARNINGFRM` | paraDefine.h L143 | 3 帧 | 报警保持帧数（常规速度） |
| `LOWSPEEDKEEPWARNINGFRM` | paraDefine.h L144 | 6 帧 | 报警保持帧数（低速） |
| `TRACK_ValidEleAng` | L192 | 未给出具体值 | 有效俯仰角阈值，用于抑制多径反射 |
| `1.5f` | L524 | 1.5 米 | 近距离纵向距离阈值，用于特殊速度门限切换 |
| `2.0f` | L677 | 2.0 米 | 低速近距离横向距离阈值 |
| `5.0f` | L677 | 5.0 km/h | 低速判断阈值 |
| `3.0f` | L663, L818 | 3.0 米 | 跟踪门限 X 方向最小值或 FOV 边界扩展 |
| `2.5f` | L654 | 2.5 米 | 跟踪门限 Y 方向最小值 |
| `3.5` | L825 | 3.5 m/s | 静止车辆附近目标速度阈值 |

## 5. 关键变量

| 变量名 | 类型 | 来源 | 含义 |
| :--- | :--- | :--- | :--- |
| `g_adasEnable.bBSDEnable` | bool | `perception_public_def.h` | BSD 功能使能标志，由 HMI 或系统配置设置 |
| `g_adasWarning.bsdSystemState` | uint8_t | `perception_public_def.h` | BSD 系统当前状态 (0-6) |
| `g_adasWarning.bLeftBsdWarning` | uint8_t | `perception_public_def.h` | 左侧 BSD 报警状态 (0:无, 1:一级, 2:二级) |
| `g_adasWarning.bRightBsdWarning` | uint8_t | `perception_public_def.h` | 右侧 BSD 报警状态 (0:无, 1:一级, 2:二级) |
| `g_adasRoi.leftBsdRoi` | polygonStruct | `structDefine.h` | 左侧 BSD 感兴趣区域多边形定义 |
| `g_adasRoi.rightBsdRoi` | polygonStruct | `structDefine.h` | 右侧 BSD 感兴趣区域多边形定义 |
| `objBsdWarningFlag` | int8_t | `structDefine.h` / `perception_public_def.h` | 单个目标的 BSD 报警标志，用于关联具体目标 |
| `leftBsdFlag` / `rightBsdFlag` | bool | `perception_public_def.h` | 目标是否位于左侧/右侧 BSD 区域的标志 |
| `g_egoCarAddInfo.carSpd` | float | 全局变量 | 自车速度，用于状态切换和 ROI 调整 |
| `clusterInfo->clusterData[i]` | struct | `track.c` | 当前帧的聚类数据，包含距离、速度、动态属性等 |
| `pThClu` | objStruct* | `track.c` | 当前跟踪的目标轨迹结构体指针 |
| `dynFlg` | uint8_t | `perception_public_def.h` | 目标动态属性 (Stationary, Moving, Stopped 等) |
| `isFOVBoard` | uint8_t | `track.c` | 目标是否在视场边缘，用于抑制边缘误检 |

## 6. 输入信号

1.  **雷达原始数据**:
    *   点云数据 (Cluster Data): 距离 (`distX`, `distY`, `distZ`)，速度 (`velX`, `velY`, `radialVel`)，功率 (`power`)，角度 (`angEle`, `azi`)。
    *   聚类状态 (`clusterStat`)。
2.  **车辆总线信号 (CAN/LIN)**:
    *   `g_egoCarAddInfo.carSpd`: 自车车速。
    *   `g_egoCarAddInfo.carSpd < 0.5f`: 静止判断。
    *   `g_egoCarAddInfo.carSpd < 5.0f`: 低速判断。
    *   转向信号 (Turn Signal): 虽然代码片段未直接显示，但 BSD/LCA 通常依赖转向信号来区分 BSD 和 LCA。
    *   档位信息 (Gear): 用于判断是否处于倒车或行驶状态。
3.  **系统配置**:
    *   `g_adasEnable.bBSDEnable`: 功能开关。
    *   `g_adasRoi`: 预定义的 ROI 多边形参数。
4.  **校准数据**:
    *   `g_AziShift`, `g_EleCompensated`: 雷达安装角度补偿。

## 7. 输出信号

1.  **报警状态**:
    *   `g_adasWarning.bLeftBsdWarning`: 左侧盲区报警等级。
    *   `g_adasWarning.bRightBsdWarning`: 右侧盲区报警等级。
2.  **目标级信息**:
    *   `objOutDataStruct.objBsdWarningFlag`: 每个跟踪目标的 BSD 报警关联标志。
    *   `objOutDataStruct.leftBsdFlag` / `rightBsdFlag`: 目标位置标志。
3.  **系统状态**:
    *   `g_adasWarning.bsdSystemState`: 当前 BSD 功能状态，用于 HMI 显示（如功能不可用提示）。
4.  **诊断信息**:
    *   潜在的故障码或警告标志（未在片段中明确列出，但通常包含在 `algoExtraStruct` 或诊断模块中）。

## 8. 与其他功能的交互

1.  **LCA (Lane Change Assist)**:
    *   **共享 ROI**: BSD 和 LCA 使用相似的侧后方 ROI，但 LCA 通常要求更严格的条件（如自车打转向灯）。
    *   **共享目标**: 同一个目标可能同时触发 BSD 和 LCA 标志。代码中 `leftLcaFlag` 和 `leftBsdFlag` 并存。
    *   **优先级**: 通常 LCA 报警优先级高于 BSD，或者在打转向灯时 BSD 报警被抑制或转换为 LCA 报警。
2.  **DOW (Door Open Warning)**:
    *   **共享 ROI**: DOW 的 ROI 通常比 BSD 更远，覆盖侧后方更大范围。
    *   **条件差异**: DOW 仅在车辆静止或极低速且车门解锁/打开时激活。代码中 `bDOWEnable` 独立控制。
3.  **RCTA (Rear Cross Traffic Alert)**:
    *   **共享 ROI**: RCTA 关注正后方横向移动的目标，与 BSD 的侧向目标有重叠但逻辑不同。
    *   **条件差异**: RCTA 仅在倒车时激活。
4.  **Perception 层内部**:
    *   **Track 模块**: BSD 逻辑依赖于 `track.c` 输出的稳定目标轨迹。`SetTrcGateVel` 等函数优化了跟踪性能，直接影响 BSD 的检测灵敏度和稳定性。
    *   **Cluster 合并**: `track.c` 中的聚类合并逻辑（L160-L190）确保多个点云被正确合并为一个目标，避免 BSD 对同一车辆产生多次报警或漏报。
    *   **Ghost 抑制**: `ghostProb` 和 `isFOVBoard` 等标志用于过滤多径反射和边缘噪声，减少 BSD 误报。