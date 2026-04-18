

# FCTA 功能分析

## 1. 功能概述
**FCTA (Front Cross Traffic Alert，前方交叉交通警报)** 功能主要用于在车辆低速向前行驶（如从停车场驶出、通过狭窄路口）时，检测前方横向穿越的车辆或障碍物。当检测到潜在碰撞风险时，系统通过声音或视觉信号向驾驶员发出警报，提醒驾驶员注意前方横向交通流，避免发生碰撞。该功能通常与 FCTB (Front Cross Traffic Brake) 共享检测逻辑，但 FCTA 侧重于预警，FCTB 侧重于自动制动。

## 2. 状态机
根据源码注释定义，FCTA 系统状态机包含以下 7 种状态（`uint8_t fctaSystemState`）：

| 状态值 | 状态名称 | 含义 | 转换条件推断 |
| :--- | :--- | :--- | :--- |
| 0 | None | 未初始化 | 系统上电初始状态 |
| 1 | Init | 初始化 | 系统启动，参数加载完成 |
| 2 | Standby | 待机 (Ready) | 车速在检测范围内 (`fFctaDetectLowSpd` ~ `fFctaDetectUpSpd`)，但可能未满足完全激活条件或等待使能 |
| 3 | Active | 激活 | 车速在激活范围内 (`fFctaActiveLowSpd` ~ `fFctaActiveUpSpd`)，功能使能 (`bFCTAEnable`)，无故障 |
| 4 | Off | 关闭 | 车速超出范围或功能被手动关闭 |
| 5 | Failure | 故障 | 传感器数据异常或内部逻辑错误 |
| 6 | Passive | 被动 | 系统处于非主动干预状态（如仅监测不报警） |

**状态转换逻辑推断：**
*   **进入 Active/Standby:** 当自车速度 `carSpd` 满足 `fFctaDetectLowSpd` (0.5 km/h) 至 `fFctaDetectUpSpd` (22.0 km/h) 且功能使能时。
*   **退出 Active:** 当自车速度超过 `fFctaDeactiveUpSpd` (22.0 km/h) 或低于 `fFctaDeactiveLowSpd` (0.0 km/h) 时。
*   **报警允许:** 仅当状态为 **Standby (2)** 或 **Active (3)** 时，允许设置报警标志位（参考 `UpdateObjAdasWarningFlg` 逻辑）。

## 3. 报警/制动逻辑

### 3.1 报警触发条件
1.  **系统状态:** `fctaSystemState` 必须为 2 (Standby) 或 3 (Active)。
2.  **功能使能:** `adasEnable->bFCTAEnable` 为 `true`。
3.  **目标筛选:**
    *   **速度:** 目标物体速度在 `fFctaObjWarningSpd` (4.0 km/h) 至 `fFctaObjWarningUpSpd` (70.0 km/h) 之间。
    *   **角度:** 目标物体绝对偏航角 (Yaw Angle) 在 `fFctaObjWarningLowYawAngle` (38.0°) 至 `fFctaObjWarningUpYawAngle` (127.0°) 之间。
    *   **区域 (ROI):** 目标物体位于 FCTA 定义的感兴趣区域 (ROI) 内，涉及 DDCI (Distance to Collision Intersection) 和 C-DDCI 计算。
    *   **时间 (TTM):** 碰撞时间 (Time to Impact) 满足阈值：
        *   X 轴 TTM: `fFctaObjWarningBaseTTMX` (2.0s) + Offset。
        *   Y 轴 TTM: 在 `fFctaObjWarningLowTTMY` (0.4s) 至 `fFctaObjWarningUpTTMY` (2.5s) 之间。
4.  **路沿检测 (Curb Check):** 调用 `SitFctxLeftWarnFlgByCurv` 或 `SitFctxRightWarnFlgByCurv`，结合路沿数据 (`curbDBSCAN`) 过滤误报。
5.  **保持逻辑:** 报警触发后，通过 `fctaKeepWarningCount` 和 `fctaKeepWarnFrm` 进行帧保持，防止闪烁。

### 3.2 报警取消条件
1.  **系统状态:** 状态变为 Off (4)、Failure (5) 或 None (0)。
2.  **目标消失:** 目标物体速度低于 `fFctaObjDeWarningSpd` (2.2 km/h) 或超出角度/速度范围。
3.  **TTM 增加:** 碰撞时间超过取消阈值 (`fFctaObjDeWarningTTMXOffSet` 等)。
4.  **功能关闭:** `bFCTAEnable` 变为 `false`。
5.  **复位:** 调用复位函数（如 `ResetAdasWarning`）时，所有标志位清零。

### 3.3 制动逻辑
*   **FCTA 本身:** 根据参数表，FCTA 主要配置了报警阈值，未配置制动压力值（制动参数在 FCTB 部分定义）。
*   **FCTB 关联:** 代码中存在 `FrontCrossTrafficAlertAndBrake` 函数，表明 FCTA 和 FCTB 共用检测核心。若 FCTB 功能使能且满足更严格的制动条件（如 `fFctbObjWarningBaseTTMX` = 1.0s），则可能触发制动请求，但 FCTA 输出主要为报警。

## 4. 关键阈值

| 参数类别 | 变量名 | 默认值 | 单位 | 说明 |
| :--- | :--- | :--- | :--- | :--- |
| **自车速度** | `fFctaActiveLowSpd` | 0.5 | km/h | 系统激活最低车速 |
| | `fFctaActiveUpSpd` | 21.0 | km/h | 系统激活最高车速 |
| | `fFctaDetectLowSpd` | 0.5 | km/h | 系统检测最低车速 |
| | `fFctaDetectUpSpd` | 22.0 | km/h | 系统检测最高车速 |
| **目标速度** | `fFctaObjWarningSpd` | 4.0 | km/h | 目标报警最低速度 |
| | `fFctaObjWarningUpSpd` | 70.0 | km/h | 目标报警最高速度 |
| | `fFctaObjDeWarningSpd` | 2.2 | km/h | 目标取消报警速度 |
| **角度** | `fFctaObjWarningLowYawAngle` | 38.0 | deg | 目标报警最小偏航角 |
| | `fFctaObjWarningUpYawAngle` | 127.0 | deg | 目标报警最大偏航角 |
| **TTM (时间)** | `fFctaObjWarningBaseTTMX` | 2.0 | s | X 轴基础碰撞时间 |
| | `fFctaObjWarningUpTTMY` | 2.5 | s | Y 轴最大碰撞时间 |
| | `fFctaObjWarningLowTTMY` | 0.4 | s | Y 轴最小碰撞时间 |
| **几何/距离** | `fFctaRoiOffSetY` | 0.3 | m | ROI Y 轴偏移 |
| | `fFctaObjWarningUpBaseDDCI` | 2.8 | m | DDCI 基础距离上限 |
| | `fFctaObjWarningLowerDDCIOffSet` | -1.0 | m | DDCI 下限偏移 |

## 5. 关键变量

| 变量名 | 类型 | 来源/作用域 | 含义 |
| :--- | :--- | :--- | :--- |
| `fctaSystemState` | `uint8_t` | 全局/文件静态 | FCTA 系统当前状态机状态 (0-6) |
| `bFctaDetectFlg` | `bool` | 静态 | FCTA 检测功能是否正在运行标志 |
| `bFctaLeftWarningFlg` | `bool` | 静态 | 左侧 FCTA 报警标志位 |
| `bFctaRightWarningFlg` | `bool` | 静态 | 右侧 FCTA 报警标志位 |
| `bFctaLeftKeepFlag` | `bool` | 静态 | 左侧报警保持标志 |
| `fctaKeepWarningCount` | `uint8_t` | 静态 | 报警保持计数，用于防抖 |
| `lastFctaKeepWarningObjIdx` | `int8_t` | 静态 | 上一次保持报警的目标索引 |
| `bFCTAEnable` | `bool` | `adasEnableStruct` | FCTA 功能使能开关 |
| `fFctaObjWarningBaseTTMX` | `float` | 全局参数 | X 轴报警基础 TTM 阈值 |
| `fFctaObjWarningLowYawAngle` | `float` | 全局参数 | 报警角度下限阈值 |

## 6. 输入信号
1.  **自车状态:**
    *   车速 (`carSpd`)
    *   曲率半径 (`curvature_radius`)
    *   转向角/偏航率 (隐含在 ROI 计算中)
2.  **感知数据:**
    *   目标列表 (`objOutStruct* objInfo`, `trcNum`, `trcOutData`)
    *   目标属性：速度、位置 (X, Y)、偏航角、ID
3.  **环境数据:**
    *   路沿数据 (`curbDBSCANOutput* curbDBSCAN`)
4.  **配置/使能:**
    *   功能使能标志 (`adasEnableStruct* adasEnable`, `bFCTAEnable`)
    *   系统参数 (速度阈值、角度阈值、TTM 阈值等)

## 7. 输出信号
1.  **报警标志:**
    *   `lastAdasWarning.bLeftFctaWarning` (左侧报警)
    *   `lastAdasWarning.bRightFctaWarning` (右侧报警)
2.  **目标状态:**
    *   `objOutDataStruct.objFctaWarningFlag` (单个目标的报警状态)
3.  **EDR 数据:**
    *   `objOutEDRStruct* objEDRInfo` (用于事件数据记录，包含触发报警的目标信息)
4.  **系统状态:**
    *   `fctaSystemState` (供上层或诊断使用)

## 8. 与其他功能的交互
1.  **FCTB (前方交叉交通制动):**
    *   **共享逻辑:** 两者共用 `FctaFctbUpdateStatus` 更新状态，共用 `ResetFctaRoi` 重置 ROI。
    *   **检测共用:** `FrontCrossTrafficAlertAndBrake` 函数同时处理报警和制动逻辑。FCTA 负责预警，FCTB 在 FCTA 检测到风险且满足更严苛条件（如更短 TTM）时介入制动。
    *   **参数区分:** FCTA 使用 `fFcta...` 参数，FCTB 使用 `fFctb...` 参数（如制动压力值）。
2.  **Curb Detection (路沿检测):**
    *   通过 `SitFctxLeftWarnFlgByCurv` 和 `SitFctxRightWarnFlgByCurv` 函数，FCTA 逻辑会结合路沿数据来优化报警区域，避免在靠近路沿时产生误报。
3.  **EDR (Event Data Recorder):**
    *   通过 `SelectEDRObjects` 和 `FrontCrossTrafficAlertAndBrake` 接口，将触发报警的目标信息记录到 EDR 中，用于事故分析。
4.  **状态机同步:**
    *   在 `UpdateObjAdasWarningFlg` 中，FCTA 的状态 (`fctaSystemState`) 直接控制目标报警标志位的清除。如果系统非 Active/Standby 状态，即使目标满足条件，报警标志也会被强制置为 Normal。