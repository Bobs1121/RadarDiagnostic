# FCTB 功能分析

## 1. 功能概述
**FCTB (Front Cross Traffic Braking)** 即前方交叉交通制动功能。该功能主要应用于车辆低速（如倒车出库、在路口起步）场景下，利用前角雷达（Front Corner Radar）监测车辆前方横向（Y 轴）或斜向（X 轴）运动的障碍物（车辆、行人等）。

当检测到障碍物即将与自车发生碰撞，且时间到碰撞（TTM）低于设定阈值时，系统首先触发声光报警（FCTA 阶段），若驾驶员未采取制动措施且 TTM 进一步降低，系统将自动施加制动（FCTB 阶段），以避免或减轻碰撞。

根据代码分析，该功能具备完整的状态管理、多阶段报警逻辑以及自动制动控制逻辑，并包含防误触的保持时间（Hold Time）和冷却时间（Func Gap）机制。

## 2. 状态机
FCTB 功能的状态机定义在 `adasFunc.c` 中，通过 `fctbSystemState` 变量管理。

### 状态定义
| 状态值 | 状态名称 | 含义 |
| :--- | :--- | :--- |
| 0 | **None** | 未初始化/未定义 |
| 1 | **Init** | 初始化状态 |
| 2 | **Standby** | 待机状态（系统就绪，等待激活条件） |
| 3 | **Active** | 激活状态（正在监测，可触发报警或制动） |
| 4 | **Off** | 关闭状态（功能被用户关闭或条件不满足） |
| 5 | **Failure** | 故障状态（雷达故障、信号丢失等） |
| 6 | **Passive** | 被动状态（功能降级或等待恢复） |

### 状态转换逻辑推断
基于代码中的阈值变量和状态机通用逻辑：
1.  **Standby -> Active**:
    *   车速在激活范围内：`fFctbActiveLowSpd` (0.5 km/h) <= 车速 <= `fFctbActiveUpSpd` (21.0 km/h)。
    *   功能使能：`bFCTBEnable` 为 TRUE。
    *   无系统故障。
2.  **Active -> Off**:
    *   车速超出范围：车速 > `fFctbDeactiveUpSpd` (22.0 km/h) 或 车速 < `fFctbDeactiveLowSpd` (0.0 km/h)。
    *   用户手动关闭功能。
3.  **Active -> Failure**:
    *   检测到雷达硬件故障、通信超时或关键信号（如车速、转向角）不可信。
4.  **Failure -> Standby/Init**:
    *   故障清除，系统重新初始化。

## 3. 报警/制动逻辑

### 报警触发与取消 (Warning Logic)
FCTB 的报警逻辑通常与 FCTA 共享部分阈值，但 FCTB 侧重于更紧急的制动前预警。
*   **触发条件 (Warning On)**:
    *   系统处于 `Active` 状态。
    *   检测到目标物体在 ROI 区域内。
    *   **Y 轴 TTM (横向)**: `TTM_Y` <= `fFctbObjWarningUpTTMY` (1.5s)。
    *   **X 轴 TTM (纵向/斜向)**: `TTM_X` <= `fFctbObjWarningBaseTTMX` (1.0s) + `fFctbObjWarningTTMXOffSet` (0.0s)。
    *   目标物体需持续存在一定帧数（防抖，代码中隐含在 `KeepFlag` 逻辑中）。
*   **取消条件 (Warning Off)**:
    *   目标物体离开 ROI 或消失。
    *   **Y 轴 TTM**: `TTM_Y` > `fFctbObjDeWarningUpTTMY` (1.6s) (存在迟滞)。
    *   **X 轴 TTM**: `TTM_X` > `fFctbObjWarningBaseTTMX` + `fFctbObjDeWarningTTMXOffSet` (0.1s)。

### 制动触发逻辑 (Braking Logic)
当报警触发后，若 TTM 进一步恶化，系统将请求制动。
*   **制动请求条件**:
    *   报警已激活 (`bFctbLeftWarningFlg` 或 `bFctbRightWarningFlg` 为真)。
    *   **TTC/TTM 阈值**: 目标 TTM 低于 `fFctbAEBActiveThresh` (1.0s)。
    *   **驾驶员未干预**: 驾驶员未踩下制动踏板（需结合 `BrkPedalSts` 信号判断，代码片段中未直接展示但为逻辑必然）。
    *   **保持时间**: 若触发制动，需满足 `fFctbHoldTimeThresh` (3.0s) 的保持逻辑，或 `FCTB_HOLD` (3000ms) 的定时器逻辑。
*   **制动强度**:
    *   最大减速度请求：`fFctbBrakeValue` (-4.0 m/s²)。
    *   保持/维持减速度：`fFctbHoldValue` (-2.0 m/s²)。
    *   停止速度阈值：`fFctbStopSpd` (1.0 km/h)。

### 特殊逻辑：Hold 与 Gap
*   **Hold (保持)**: 制动触发后，系统会维持制动请求至少 `FCTB_HOLD` (3000ms)，防止因目标短暂丢失导致制动过早释放。由 `FCTBHoldThree()` 函数管理。
*   **Gap (冷却)**: 制动事件结束后，需等待 `FCTB_FUNC_GAP` (10000ms) 才能再次触发新的制动事件，防止连续频繁制动。

## 4. 关键阈值

| 参数名称 | 变量名 | 数值 | 单位 | 说明 |
| :--- | :--- | :--- | :--- | :--- |
| **激活上限车速** | `fFctbActiveUpSpd` | 21.0 | km/h | 超过此速度功能不激活 |
| **激活下限车速** | `fFctbActiveLowSpd` | 0.5 | km/h | 低于此速度功能不激活 |
| **去激活上限车速** | `fFctbDeactiveUpSpd` | 22.0 | km/h | 迟滞阈值，防止状态抖动 |
| **检测上限车速** | `fFctbDetectUpSpd` | 22.0 | km/h | 监测有效速度上限 |
| **X 轴报警基础 TTM** | `fFctbObjWarningBaseTTMX` | 1.0 | s | 纵向/斜向碰撞时间阈值 |
| **X 轴报警偏移** | `fFctbObjWarningTTMXOffSet` | 0.0 | s | X 轴阈值修正 |
| **X 轴取消偏移** | `fFctbObjDeWarningTTMXOffSet` | 0.1 | s | X 轴取消迟滞 |
| **Y 轴报警上限 TTM** | `fFctbObjWarningUpTTMY` | 1.5 | s | 横向碰撞时间阈值 (报警) |
| **Y 轴取消上限 TTM** | `fFctbObjDeWarningUpTTMY` | 1.6 | s | 横向取消迟滞 |
| **Y 轴报警下限 TTM** | `fFctbObjWarningLowTTMY` | 0.4 | s | 可能用于分级报警或制动触发 |
| **AEB 激活阈值** | `fFctbAEBActiveThresh` | 1.0 | s | 触发自动制动的 TTM 阈值 |
| **最大制动减速度** | `fFctbBrakeValue` | -4.0 | m/s² | 紧急制动请求值 |
| **保持减速度** | `fFctbHoldValue` | -2.0 | m/s² | 维持制动请求值 |
| **制动保持时间** | `fFctbHoldTimeThresh` | 3.0 | s | 制动请求最小持续时间 |
| **停止速度** | `fFctbStopSpd` | 1.0 | km/h | 车辆接近停止时的速度阈值 |
| **制动冷却时间** | `FCTB_FUNC_GAP` | 10000 | ms | 两次制动事件的最小间隔 |
| **制动保持时长** | `FCTB_HOLD` | 3000 | ms | 制动触发后的强制保持时间 |

## 5. 关键变量

| 变量名 | 类型 | 来源 | 含义 |
| :--- | :--- | :--- | :--- |
| `fctbSystemState` | `uint8_t` | `adasFunc.c` | FCTB 功能当前状态机状态 |
| `bFctbLeftWarningFlg` | `bool` | `adasFunc.c` | 左侧 FCTB 报警标志位 |
| `bFctbRightWarningFlg` | `bool` | `adasFunc.c` | 右侧 FCTB 报警标志位 |
| `bFctbKeepBrakeFlg` | `bool` | `adasFunc.c` | 制动保持标志位，指示是否处于制动保持阶段 |
| `fFctbBrakeEventTime` | `float` | `adasFunc.c` | 制动事件开始的时间戳 |
| `fFctbHoldEventTime` | `float` | `adasFunc.c` | 制动保持阶段开始的时间戳 |
| `bFCTBEnable` | `bool` | `RteComMapping` | 用户/系统使能 FCTB 功能的开关 |
| `fFctbObjWarningUpTTMY` | `float` | `adasFunc.c` | Y 轴报警 TTM 阈值 (1.5s) |
| `fFctbAEBActiveThresh` | `float` | `adasFunc.c` | 触发 AEB 的 TTM 阈值 (1.0s) |
| `fFctbBrakeValue` | `float` | `adasFunc.c` | 请求的制动减速度值 (-4.0) |
| `fctbTimerActive` | `bool` | `ASWIN_SystemState.c` | 内部制动保持定时器激活标志 |

## 6. 输入信号
1.  **雷达感知数据**:
    *   目标列表 (Object List): 包含距离 (`distX`, `distY`)、速度 (`velX`, `velY`)、TTC/TTM (`fTTC`, `fDDCI`)。
    *   目标分类：车辆、行人等。
2.  **车辆状态信号**:
    *   车速 (`VehicleSpeed`): 用于判断激活/去激活条件。
    *   档位 (`Gear`): 通常需处于 R 档或低速 D 档（代码中 `actual_gear == 7` 可能对应特定档位逻辑，需结合具体定义）。
    *   转向角 (`SteerAngle`): 用于判断车辆行驶方向及 ROI 计算。
    *   制动踏板状态 (`BrkPedalSts`): 判断驾驶员是否已介入。
3.  **功能使能信号**:
    *   `FCTASwtReq` / `FCTABrkSwtReq`: 用户通过车机或开关请求开启/关闭 FCTA/FCTB。
    *   `VariantConfig`: 车辆配置是否包含 FCTB 功能。
4.  **系统状态**:
    *   雷达故障状态 (`Fault_Err`)。
    *   校准状态 (`SDASts`)。

## 7. 输出信号
1.  **报警信号**:
    *   `FR_Fctb_Warning` / `FL_Fctb_Warning`: 发送给仪表盘或 HMI 的报警请求（声光提示）。
    *   `bLeftFctbWarning` / `bRightFctbWarning`: 内部逻辑标志，指示左右侧报警状态。
2.  **制动控制信号**:
    *   `fBrakeValue`: 发送给底盘控制单元 (ESP/VCU) 的制动减速度请求值 (范围 -4.0 ~ -2.0 m/s²)。
    *   `FL_fBrakeValue` / `FR_fBrakeValue`: 具体到左前/右前雷达的制动请求输出。
3.  **状态反馈信号**:
    *   `CR_FCTB_Resp`: 功能激活状态反馈给网关或车身控制器。
    *   `FCTBState`: 当前功能状态机状态。
4.  **故障信号**:
    *   `FR_Fault_Err` / `FL_Fault_Err`: 雷达或功能故障指示。

## 8. 与其他功能的交互
1.  **FCTA (Front Cross Traffic Alert)**:
    *   **强耦合**: FCTB 是 FCTA 的升级功能。通常先触发 FCTA 报警，若 TTM 继续恶化且无驾驶员干预，则升级为 FCTB 制动。
    *   代码中 `bFctaEnable` 和 `bFctbEnable` 往往联动，FCTA 开启是 FCTB 开启的前提（见 `RteComMapping.c` 逻辑）。
2.  **AEB (Autonomous Emergency Braking)**:
    *   FCTB 本质上是低速场景下的 AEB 变种。在代码中 `fFctbBrakeValue` 直接作为制动请求输出，可能直接调用 AEB 的底层制动接口。
3.  **ESP/VCU (底盘控制)**:
    *   FCTB 输出的 `fBrakeValue` 需发送给 ESP 执行器进行实际制动。需确保与 ESP 的常规制动请求（如驾驶员踩刹车）进行优先级仲裁。
4.  **DTC (Diagnostic Trouble Code)**:
    *   若雷达故障或功能不可用，会触发 DTC 并上报给诊断系统，同时状态机进入 `Failure` 状态。
5.  **TGU (Turn Guard)**:
    *   代码中同时定义了 TGU 参数，两者在低速转弯场景下可能存在 ROI 重叠或逻辑互斥，需根据具体场景（直行出库 vs 转弯）进行功能切换。