

# DOW 功能分析

## 1. 功能概述
DOW (Door Open Warning，开门预警) 功能旨在防止驾驶员或乘客在车辆静止或低速状态下打开车门时，与后方接近的车辆、自行车或行人发生碰撞。该功能通过角雷达监测车辆侧后方的盲区区域（ROI），当检测到有目标物体以特定速度和角度接近，且满足 TTC（碰撞时间）阈值时，系统会触发报警信号，提醒人员不要开门。

## 2. 状态机
根据源码注释及 `DOWUpdateSystemStatus` 函数逻辑，DOW 系统状态定义及转换条件如下：

| 状态值 | 状态名称 | 含义 | 转换条件/进入条件 |
| :--- | :--- | :--- | :--- |
| **0** | **None** | 未初始化 | `g_DTCCode.selfInspFlg` 为 false (自检未完成) |
| **1** | **Init** | 初始化 | `selfInspFlg` 为 true 且当前状态为 0 |
| **2** | **Standby** | 待机 (Ready) | 功能开启 (`bDOWEnable`)、非拖车模式、非标定中、无故障、车速 <= `fDowActiveSpd` |
| **3** | **Active** | 激活 | 注释中定义，代码片段中未显示明确进入逻辑，但作为允许报警的有效状态之一 |
| **4** | **Off** | 关闭 | 功能关闭 (`!bDOWEnable`)、拖车模式 (`bTrailerModelFlg`) 或 标定中 (`calibratingFlg`) |
| **5** | **Failure** | 故障 | 系统自检故障 (`g_DTCCode.failureFlg`) |
| **6** | **Passive** | 被动 | 当前为 Standby/Active 状态，且车速 > `fDowDeactiveSpd` |

**状态转换逻辑摘要 (`DOWUpdateSystemStatus`):**
1.  若自检未完成 (`!selfInspFlg`) -> **None (0)**。
2.  若自检完成且状态为 0 -> **Init (1)**。
3.  若功能开启且非拖车模式：
    *   若标定中 -> **Off (4)**。
    *   若故障 -> **Failure (5)**。
    *   若车速 <= `fDowActiveSpd` -> **Standby (2)**。
    *   若车速 > `fDowDeactiveSpd` (且原状态为 2 或 3) -> **Passive (6)**。
4.  若功能关闭或拖车模式 -> **Off (4)**。

## 3. 报警/制动逻辑
DOW 功能主要输出报警信号，不涉及制动请求（制动通常由 RCTB/FCTB 负责）。

*   **报警触发条件 (Trigger):**
    1.  **系统状态**: `dowSystemState` 为 **Standby (2)** 或 **Active (3)**。
    2.  **功能使能**: `adasEnable->bDOWEnable` 为 true。
    3.  **目标检测**: 目标物体位于 DOW ROI 区域内（由 `LineDOWA` ~ `LineDOWL` 定义）。
    4.  **速度阈值**: 目标相对速度 > `fDowObjWarningSpd` (5.0 km/h)。
    5.  **TTC 阈值**: 碰撞时间 < `fDowObjWarningTTC` (3.5 s)。
    6.  **角度阈值**: 目标绝对偏航角 < `fDowObjWarningYawAngle` (45.0 deg)。
    7.  **去抖动**: 报警需持续一定帧数 (`dowKeepWarnFrm`) 或通过 `bDowLeftKeepFlag` / `bDowRightKeepFlag` 逻辑保持。

*   **报警取消条件 (De-warning):**
    1.  **系统状态**: 状态变为 Off (4), Failure (5), Passive (6), None (0) 或 Init (1)。
    2.  **功能使能**: `adasEnable->bDOWEnable` 为 false。
    3.  **目标离开**: 目标离开 ROI 区域（考虑去报警偏移量 `fDowObjDeWarning...OffSet...`）。
    4.  **速度阈值**: 目标相对速度 < `fDowObjDeWarningSpd` (5.0 km/h)。
    5.  **TTC 阈值**: 碰撞时间 > `fDowObjDeWarningTTC` (4.0 s)。
    6.  **角度阈值**: 目标绝对偏航角 > `fDowObjDeWarningYawAngle` (50.0 deg)。
    7.  **路沿去报警**: 若 `bDowCurbDewarningEnable` 为 true，检测到路沿时可能取消报警。

*   **报警保持逻辑:**
    *   使用 `dowLeftBuffer` / `dowRightBuffer` 和 `dowLeftFrmCount` / `dowRightFrmCount` 记录历史报警状态。
    *   通过 `dowKeepWarnFrm` 定义报警保持帧数，防止目标短暂丢失导致报警闪烁。

## 4. 关键阈值
以下参数定义了 DOW 功能的敏感度和触发边界：

| 变量名 | 默认值 | 单位 | 含义 |
| :--- | :--- | :--- | :--- |
| `fDowActiveSpd` | 0.7 | km/h | 系统进入 Standby 状态的车速阈值 |
| `fDowDeactiveSpd` | 1.0 | km/h | 系统进入 Passive 状态的车速阈值 |
| `fDowObjWarningSpd` | 5.0 | km/h | 目标触发报警的最小速度 |
| `fDowObjDeWarningSpd` | 5.0 | km/h | 目标取消报警的最大速度 |
| `fDowObjWarningUpperSpd` | 200.0 | km/h | 目标报警速度上限 |
| `fDowObjDeWarningUpperSpd` | 200.0 | km/h | 目标去报警速度上限 |
| `fDowObjWarningTTC` | 3.5 | s | 触发报警的 TTC 阈值 |
| `fDowObjDeWarningTTC` | 4.0 | s | 取消报警的 TTC 阈值 |
| `fDowObjWarningYawAngle` | 45.0 | deg | 触发报警的目标偏航角阈值 |
| `fDowObjDeWarningYawAngle` | 50.0 | deg | 取消报警的目标偏航角阈值 |
| `fDowObjDeWarningLeft/Right...OffSet` | 0.3/-0.3 | m | 去报警时的 ROI 边界偏移量 (迟滞区) |
| `LineDOWA` ~ `LineDOWL` | 动态计算 | m | DOW ROI 区域的顶点坐标 (基于车身宽度和前后距离) |

## 5. 关键变量

| 变量名 | 类型 | 来源/作用域 | 含义 |
| :--- | :--- | :--- | :--- |
| `dowSystemState` | `uint8_t` | 全局 (`adasFunc.c`) | DOW 系统当前状态机状态 |
| `bDowLeftWarningFlg` | `bool` | 静态 (`adasFunc.c`) | 左侧 DOW 报警内部标志位 |
| `bDowRightWarningFlg` | `bool` | 静态 (`adasFunc.c`) | 右侧 DOW 报警内部标志位 |
| `bDowLeftKeepFlag` | `bool` | 静态 (`adasFunc.c`) | 左侧报警保持标志位 |
| `bDowRightKeepFlag` | `bool` | 静态 (`adasFunc.c`) | 右侧报警保持标志位 |
| `dowKeepWarnFrm` | `uint8_t` | 静态 (`adasFunc.c`) | 报警保持帧数配置 |
| `bInitDowRoiFlag` | `bool` | 静态 (`adasFunc.c`) | DOW ROI 初始化标志 |
| `bDowCurbDewarningEnable` | `bool` | 全局 (`adasFunc.c`) | 路沿去报警功能开关 |
| `g_DTCCode` | `struct` | 全局 | DTC 诊断状态 (自检、故障、标定等) |
| `g_egoCarAddInfo` | `struct` | 全局 | 自车动态信息 (车速、横摆角速度等) |
| `g_egoCarFixPara` | `struct` | 全局 | 自车固定参数 (车宽、前后保险杠距离等) |
| `adasEnable` | `struct` | 输入参数 | ADAS 功能使能配置 (bDOWEnable) |
| `adasWarning` | `struct` | 输入/输出 | ADAS 报警输出结构体 |

## 6. 输入信号
DOW 功能依赖以下输入信号进行决策：

1.  **车辆状态**:
    *   `g_egoCarAddInfo.carSpd`: 自车车速 (用于状态机切换)。
    *   `g_egoCarAddInfo.yawRate`: 自车横摆角速度 (用于 ROI 动态调整，虽 DOW 主要静态，但代码中有相关引用)。
2.  **诊断与配置**:
    *   `g_DTCCode.selfInspFlg`: 自检完成标志。
    *   `g_DTCCode.failureFlg`: 系统故障标志。
    *   `g_DTCCode.calibratingFlg`: 标定中标志。
    *   `g_DTCCode.bTrailerModelFlg`: 拖车模式标志。
    *   `adasEnable->bDOWEnable`: DOW 功能用户开关。
3.  **感知数据**:
    *   `objOutStruct`: 目标对象列表 (包含位置、速度、TTC、角度等，虽未直接显示结构体定义，但 `DoorOpenAlert` 函数接收此参数)。
    *   `curbDBSCANOutput`: 路沿检测数据 (用于 `bDowCurbDewarningEnable` 逻辑)。
4.  **车辆参数**:
    *   `g_egoCarFixPara.vehicle_width`: 车宽。
    *   `g_egoCarFixPara.rear_bumper_distX`: 后保险杠距离。
    *   `g_egoCarFixPara.pillar_b_distX`: B 柱距离。

## 7. 输出信号
DOW 功能主要输出报警状态给 HMI 或车身控制器：

1.  **系统状态**:
    *   `adasWarning->dowSystemState`: 当前 DOW 系统状态 (0-6)。
2.  **报警请求**:
    *   `adasWarning->bLeftDowWarning`: 左侧开门预警报警请求 (0/1)。
    *   `adasWarning->bRightDowWarning`: 右侧开门预警报警请求 (0/1)。
3.  **对象级标志**:
    *   `objInfo->trcOutData[i].objDowWarningFlag`: 单个目标的 DOW 报警标志 (Normal/Warning)。
    *   `g_pMthObj[sObj.objID].objDowWarningFlag`: 匹配对象中的 DOW 报警标志。

## 8. 与其他功能的交互
1.  **DTC 诊断系统**: DOW 状态机强依赖 `g_DTCCode`。若自检未完成、标定中或发生故障，DOW 会进入 None/Off/Failure 状态，禁止报警。
2.  **拖车模式**: 若 `bTrailerModelFlg` 为 true，DOW 强制进入 Off 状态，防止误报。
3.  **ROI 共享**: DOW 的 ROI 定义 (`LineDOW...`) 与 BSD/LCA 类似，但范围更靠近车身侧后方（X 轴范围约 1.0m 到 -30.0m），与 BSD 区域有部分重叠但更侧重车门开启区域。
4.  **报警抑制**: 在 `adasFunc.c` 的清理逻辑中，如果系统状态不是 Standby/Active，或者功能被禁用 (`!bDOWEnable`)，会强制将对象报警标志 (`objDowWarningFlag`) 重置为 Normal，确保输出信号的一致性。
5.  **路沿检测**: 通过 `curbDBSCANOutput` 输入，若开启 `bDowCurbDewarningEnable`，路沿检测可用于优化去报警逻辑，避免将路沿误判为障碍物。