

# RCW 功能分析

## 1. 功能概述
**RCW (Rear Collision Warning，后方碰撞预警)** 功能主要用于监测车辆后方高速接近的目标物体。当检测到后方存在高风险碰撞目标（如高速追尾车辆）时，系统会向驾驶员发出报警，提示潜在的后方碰撞风险。该功能通常在车辆静止或低速行驶，且后方有高速来车时触发，旨在防止或减轻后方碰撞事故。

## 2. 状态机
RCW 功能的状态机定义了系统从初始化到运行、待机、关闭及故障的完整生命周期。状态定义如下（基于代码注释及 `RCWUpdateSystemStatus` 逻辑）：

| 状态值 | 状态名称 | 含义 | 转换条件/说明 |
| :--- | :--- | :--- | :--- |
| **0** | **None** | 未初始化 | 默认状态，或 `g_DTCCode.selfInspFlg` 为 false 时进入。 |
| **1** | **Init** | 初始化 | 当 `g_DTCCode.selfInspFlg` 为 true 且当前状态为 0 时进入。 |
| **2** | **Standby** | 待机 (Ready) | 系统使能 (`bRCWEnable`)、无故障、未标定、车速 <= 120 km/h (`fRcwActiveSpd`)。 |
| **3** | **Active** | 激活 | 代码片段中未直接显示进入 3 的逻辑，但状态检查逻辑 (`3U != ... && 2U != ...`) 表明此状态允许报警。通常指系统完全就绪或报警激活态。 |
| **4** | **Off** | 关闭 | 系统未使能、正在标定 (`calibratingFlg`)、或挂接拖车模式 (`bTrailerModelFlg`)。 |
| **5** | **Failure** | 故障 | 系统自检通过但检测到故障 (`g_DTCCode.failureFlg`)。 |
| **6** | **Passive** | 被动/抑制 | 车速过高，超过 125 km/h (`fRcwDeactiveSpd`)。 |

**状态转换逻辑摘要 (`RCWUpdateSystemStatus`):**
*   **None -> Init:** 自检标志位 `selfInspFlg` 置位。
*   **Init -> Failure:** 检测到故障 `failureFlg`。
*   **Init -> Standby:** 功能使能、无故障、未标定、车速 <= 120 km/h。
*   **Standby/Active -> Passive:** 车速 > 125 km/h (`fRcwDeactiveSpd`)。
*   **Standby/Active -> Standby:** 车速 <= 125 km/h (滞回逻辑)。
*   **Any -> Off:** 功能禁用、标定中、拖车模式。
*   **Any -> None:** 自检标志位 `selfInspFlg` 清除。

## 3. 报警/制动逻辑
RCW 主要输出报警信号，代码中未显示直接制动请求（制动通常由 RCTB 或 AEB 负责，RCW 侧重预警）。

*   **触发报警条件 (Warning):**
    1.  **系统状态:** 必须处于 `Standby` (2) 或 `Active` (3) 状态。
    2.  **功能使能:** `adasEnable->bRCWEnable` 为 true。
    3.  **目标筛选:** 目标物体位于 RCW ROI 区域内。
    4.  **运动学阈值:**
        *   目标相对速度 > `fRcwObjWarningSpd` (10.8 km/h)。
        *   TTC (Time To Collision) < `fRcwObjWarningTTC` (1.4 s)。
        *   目标偏航角绝对值 < `fRcwObjWarningYawAngle` (30.0 deg)。
        *   重叠率 (Overlap Ratio) > `fRcwObjWarningRatio` (0.85)。
        *   目标减速度 > `fRcwObjWarningDeAcc` (2.0 m/s²)。
    5.  **持续帧数:** 报警需持续 `rcwKeepWarnFrm` (KEEPWARNINGFRM) 帧数，通过 `rcwFrmCount` 计数确认。

*   **取消报警条件 (De-warning):**
    1.  **系统状态:** 状态变为 Off (4), Failure (5), Passive (6) 或 None (0)。
    2.  **功能禁用:** `adasEnable->bRCWEnable` 为 false。
    3.  **阈值不满足:**
        *   目标速度 < `fRcwObjDeWarningSpd` (9.0 km/h)。
        *   TTC > `fRcwObjDeWarningTTC` (1.7 s)。
        *   偏航角 > `fRcwObjDeWarningYawAngle` (35.0 deg)。
        *   重叠率 < `fRcwObjDeWarningRatio` (0.65)。
        *   减速度 < `fRcwObjDeWarningDeAcc` (1.8 m/s²)。
    4.  **ROI 边界:** 目标移出 ROI 区域（考虑了 `fRcwObjDeWarningTopOffSetX` 等偏移量）。

*   **报警保持 (Keep Warning):**
    *   使用 `bRcwKeepFlag` 和 `rcwFrmCount` 进行滤波，防止报警闪烁。
    *   当报警条件满足时，`rcwFrmCount` 增加；不满足时重置。
    *   若 `rcwFrmCount` 达到 `rcwKeepWarnFrm`，则置位 `bRcwWarningFlg`。

## 4. 关键阈值
以下参数定义了 RCW 功能的敏感度和触发边界：

| 变量名 | 默认值 | 单位 | 含义 |
| :--- | :--- | :--- | :--- |
| `fRcwActiveSpd` | 120.0 | km/h | 系统激活车速阈值 (<= 此值进入 Standby) |
| `fRcwDeactiveSpd` | 125.0 | km/h | 系统去激活车速阈值 (> 此值进入 Passive) |
| `fRcwObjWarningSpd` | 10.8 | km/h | 目标报警速度阈值 |
| `fRcwObjDeWarningSpd` | 9.0 | km/h | 目标取消报警速度阈值 |
| `fRcwObjWarningTTC` | 1.4 | s | 目标报警 TTC 阈值 |
| `fRcwObjDeWarningTTC` | 1.7 | s | 目标取消报警 TTC 阈值 |
| `fRcwObjWarningYawAngle` | 30.0 | deg | 目标报警偏航角阈值 |
| `fRcwObjDeWarningYawAngle` | 35.0 | deg | 目标取消报警偏航角阈值 |
| `fRcwObjWarningDeAcc` | 2.0 | m/s² | 目标报警减速度阈值 |
| `fRcwObjDeWarningDeAcc` | 1.8 | m/s² | 目标取消报警减速度阈值 |
| `fRcwObjWarningRatio` | 0.85 | - | 目标报警重叠率阈值 |
| `fRcwObjDeWarningRatio` | 0.65 | - | 目标取消报警重叠率阈值 |
| `fRcwObjKeySpd` | 30.0 | km/h | 目标关键速度 (用于动态 TTC 计算) |
| `LineRCWA` | -40.0 - DISTANCEREAR | m | ROI 垂直结束点 (后方探测距离) |
| `LineRCWB` | -DISTANCEREAR | m | ROI 垂直起始点 (后保险杠位置) |
| `LineRCWC` | EGOCARWIDTH / 2.0 | m | ROI 水平起始点 (右侧边界) |
| `LineRCWD` | -EGOCARWIDTH / 2.0 | m | ROI 水平结束点 (左侧边界) |

## 5. 关键变量

| 变量名 | 类型 | 来源 | 含义 |
| :--- | :--- | :--- | :--- |
| `rcwSystemState` | `uint8_t` | `adasFunc.c` | RCW 系统当前状态机状态 (0-6) |
| `bRcwWarningFlg` | `bool` | `adasFunc.c` | RCW 报警标志位 (内部逻辑) |
| `bRcwKeepFlag` | `bool` | `adasFunc.c` | RCW 报警保持标志位 |
| `rcwFrmCount` | `uint8_t` | `adasFunc.c` | RCW 报警持续帧计数器 |
| `bRcwUseLoc` | `int8_t` | `adasFunc.c` | 报警缓冲区使用位置索引 |
| `bRcwBuffer` | `uint8_t[]` | `adasFunc.c` | 报警状态缓存缓冲区 |
| `bInitRcwRoiFlag` | `bool` | `adasFunc.c` | RCW ROI 初始化标志 |
| `adasWarning->bRcwWarning` | `uint8_t` | `adasWarningStruct` | 输出给上层/仪表的 RCW 报警状态 |
| `sObj.objRcwWarningFlag` | `int8_t` | `objOutDataStruct` | 单个目标对象的 RCW 报警标志 |
| `g_DTCCode.selfInspFlg` | `bool` | `DTC` | 系统自检完成标志 |
| `g_DTCCode.failureFlg` | `bool` | `DTC` | 系统故障标志 |
| `g_egoCarAddInfo.carSpd` | `float` | `EgoCar` | 自车当前速度 |

## 6. 输入信号
RCW 功能依赖以下输入信号进行决策：

1.  **自车状态:**
    *   `g_egoCarAddInfo.carSpd`: 自车速度。
    *   `g_egoCarFixPara.rear_bumper_distX`: 后保险杠距离 (用于 ROI 计算)。
    *   `curvRadius`: 曲率半径 (用于 ROI 动态调整，见 `ResetRcwRoi` 调用)。
2.  **系统状态:**
    *   `adasEnable->bRCWEnable`: 功能开关。
    *   `g_DTCCode.selfInspFlg`: 自检状态。
    *   `g_DTCCode.failureFlg`: 故障状态。
    *   `g_DTCCode.calibratingFlg`: 标定状态。
    *   `g_DTCCode.bTrailerModelFlg`: 拖车模式。
3.  **感知目标:**
    *   `objInfo->trcOutData[i]`: 目标列表，包含距离、速度、角度、ID 等。
    *   `curbDBSCAN`: 路沿检测信息 (用于辅助 ROI 或过滤，虽然 RCW 主要看后方，但代码结构中包含)。
4.  **配置参数:**
    *   所有 `fRcw...` 开头的阈值参数。

## 7. 输出信号
RCW 功能主要输出报警状态，不直接输出制动请求（制动由 RCTB/AEB 处理）：

1.  **系统级报警:**
    *   `adasWarning->bRcwWarning`: 发送给仪表或 HMI 的 RCW 报警信号 (0/1)。
    *   `adasWarning->rcwSystemState`: 发送给诊断或监控的系统状态。
2.  **目标级报警:**
    *   `objInfo->trcOutData[i].objRcwWarningFlag`: 标记具体哪个目标触发了报警 (WarningFlag_Warning / WarningFlag_Normal)。
    *   `g_pMthObj[sObj.objID].objRcwWarningFlag`: 内部目标管理结构中的报警标志。
3.  **历史状态:**
    *   `lastAdasWarning.bRcwWarning`: 上一帧的报警状态，用于 EDR 记录或状态保持。

## 8. 与其他功能的交互
1.  **状态机共享:** RCW 与 BSD, LCA, DOW, RCTA, RCTB, FCTA, FCTB 共享相同的状态机定义 (0-6) 和状态更新逻辑结构 (`UpdateSystemStatus` 模式)。
2.  **报警互斥/清除:**
    *   在 `adasFunc.c` (lines 1210-1252) 中，如果 RCW 系统状态不是 Standby (2) 或 Active (3)，则强制清除目标对象的 `objRcwWarningFlag`。
    *   如果 `adasEnable->bRCWEnable` 为 false，同样清除报警标志。
3.  **ROI 计算:** `ResetRcwRoi` 函数根据自车固定参数 (`rear_bumper_distX`) 动态计算 ROI，这与 BSD/LCA 的 ROI 计算逻辑类似，但区域定义不同（RCW 专注于正后方）。
4.  **EDR 记录:** `lastAdasWarning` 结构体用于记录报警历史，可能用于 EDR (Event Data Recorder) 事件触发。
5.  **依赖关系:** RCW 不直接依赖 RCTA/RCTB 的状态，但它们共用感知输入 (`objInfo`) 和系统使能结构 (`adasEnable`)。如果系统进入 Failure 状态，所有相关功能 (RCW, RCTA 等) 都会进入 Failure 或 Off 状态。