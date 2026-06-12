# FCTB 功能分析

## 1. 功能概述
**FCTB (Front Cross Traffic Braking)** 即前方交叉交通制动功能。该功能主要部署在车辆前左（FL）和前右（FR）角雷达上。当车辆处于低速行驶或静止状态（如从停车场驶出、通过狭窄路口）时，若检测到前方横向有来车存在碰撞风险，系统首先通过 FCTA 发出警报；若驾驶员未采取制动措施且碰撞风险进一步加剧，FCTB 将接管制动系统，执行自动紧急制动（AEB）以避免或减轻碰撞。

从代码结构看，FCTB 与 FCTA 紧密耦合，共享大部分感知对象和 ROI（感兴趣区域），但 FCTB 拥有独立的系统状态机、更严格的触发阈值以及直接的制动输出逻辑。

## 2. 状态机
FCTB 的系统状态由变量 `fctbSystemState` 定义，共 7 种状态：
- **0 - None**: 未初始化或无效状态。
- **1 - Init**: 初始化状态。
- **2 - Standby (Ready)**: 待机/就绪状态。系统已准备就绪，但尚未满足激活条件（如车速过高或功能未使能）。
- **3 - Active**: 激活状态。系统正在监测前方交叉交通，具备报警和制动能力。
- **4 - Off**: 关闭状态。功能被手动关闭或条件不满足。
- **5 - Failure**: 故障状态。传感器或系统内部错误。
- **6 - Passive**: 被动状态（通常指功能受限或降级）。

**状态转换关键逻辑推断：**
- **Standby -> Active**:
  - 车速低于激活上限 (`fFctbActiveUpSpd` = 20 km/h)。
  - 功能使能 (`bFCTBEnable` = TRUE)。
  - 无故障 (`GWM_FCTB_FaultEna` 为 FALSE)。
  - 满足特定的启动条件（如 `FCTB_Standby2Active` 函数返回真，可能涉及挂挡、方向盘角度等）。
- **Active -> Standby/Off**:
  - 车速超过去活上限 (`fFctbDeactiveUpSpd` = 21 km/h)。
  - 车速低于去活下限 (`fFctbDeactiveLowSpd` = 0 km/h，即完全静止过久或熄火)。
  - 功能被手动关闭。
  - 出现故障。
- **Active -> Failure**:
  - 检测到雷达故障或通信错误。

## 3. 报警/制动逻辑

### 3.1 报警逻辑 (FCTA 联动)
虽然 FCTB 是制动功能，但其触发通常伴随 FCTA 报警。代码中定义了左右侧的报警标志 `bFctbLeftWarningFlg` 和 `bFctbRightWarningFlg`。
- **触发条件**:
  - 系统处于 Active 状态。
  - 检测到目标物体在 ROI 内。
  - 目标的 TTM (Time To Merge/Intersection) 满足报警阈值：
    - Y轴（横向）TTM 小于 `fFctbObjWarningUpTTMY` (1.5s) 且大于 `fFctbObjWarningLowTTMY` (0.4s)。
    - X轴（纵向）TTM 满足 `fFctbObjWarningBaseTTMX` + Offset 条件。
- **取消条件**:
  - TTM 大于去活阈值 `fFctbObjDeWarningUpTTMY` (1.6s) 或 `fFctbObjDeWarningTTMXOffSet` (0.1s) 相关的逻辑。
  - 目标离开 ROI。

### 3.2 制动逻辑 (FCTB 核心)
当报警持续且风险升级时，FCTB 介入制动。
- **制动触发**:
  - 系统处于 Active 状态。
  - 存在有效威胁目标。
  - 制动事件计时器 `fFctbBrakeEventTime` 达到阈值 `fFctbAEBActiveThresh` (1.0s)。这意味着报警或高风险状态持续了 1 秒以上。
  - 保持制动标志 `bFctbKeepBrakeFlg` 被置位。
- **制动保持**:
  - 使用 `FCTBHoldThree()` 函数判断制动保持时间。
  - 最大保持时间阈值 `FCTB_HOLD` = 3000ms (3秒)。
  - 如果车速降至 `fFctbStopSpd` (1.0 km/h) 以下，可能进入保持或释放逻辑。
- **制动释放**:
  - 风险解除（目标离开或 TTM 变大）。
  - 制动保持时间超过 3 秒 (`FCTBHoldThree` 返回 true)。
  - 驾驶员干预（如踩油门，虽代码片段未直接显示油门信号，但通常 AEB 逻辑包含此抑制条件）。
  - 功能进入非 Active 状态。

## 4. 关键阈值

| 参数名称 | 变量名 | 值 | 单位 | 说明 |
| :--- | :--- | :--- | :--- | :--- |
| **系统激活车速上限** | `fFctbActiveUpSpd` | 20.0 | km/h | 车速低于此值才可能进入 Active |
| **系统激活车速中限** | `fFctbActiveMidSpd` | 10.0 | km/h | 用于状态机内部逻辑判断 |
| **系统激活车速下限** | `fFctbActiveLowSpd` | 1.0 | km/h | 车速低于此值可能视为静止 |
| **系统去活车速上限** | `fFctbDeactiveUpSpd` | 21.0 | km/h | 车速高于此值退出 Active (迟滞) |
| **系统去活车速下限** | `fFctbDeactiveLowSpd` | 0.0 | km/h | |
| **检测车速上限** | `fFctbDetectUpSpd` | 20.0 | km/h | 允许进行目标检测的车速上限 |
| **检测车速下限** | `fFctbDetectLowSpd` | 1.0 | km/h | 允许进行目标检测的车速下限 |
| **X轴基础报警TTM** | `fFctbObjWarningBaseTTMX` | 1.0 | s | 纵向时间阈值 |
| **X轴报警TTM偏移** | `fFctbObjWarningTTMXOffSet` | 0.0 | s | |
| **X轴去活TTM偏移** | `fFctbObjDeWarningTTMXOffSet` | 0.1 | s | 迟滞量 |
| **Y轴报警TTM上限** | `fFctbObjWarningUpTTMY` | 1.5 | s | 横向时间阈值上限 |
| **Y轴去活TTM上限** | `fFctbObjDeWarningUpTTMY` | 1.6 | s | 横向时间阈值去活上限 |
| **Y轴报警TTM下限** | `fFctbObjWarningLowTTMY` | 0.4 | s | 横向时间阈值下限 |
| **Y轴二次报警TTM下限**| `fFctbObjWarningSecLowTTMY`| 0.0 | s | |
| **制动请求值** | `fFctbBrakeValue` | -4.0 | m/s² | 紧急制动减速度请求 |
| **保持制动请求值** | `fFctbHoldValue` | -2.0 | m/s² | 停车保持减速度请求 |
| **AEB激活时间阈值** | `fFctbAEBActiveThresh` | 1.0 | s | 报警/风险持续1秒后触发制动 |
| **制动保持时间阈值** | `FCTB_HOLD` | 3000 | ms | 最大自动制动持续时间 |
| **停止车速阈值** | `fFctbStopSpd` | 1.0 | km/h | 视为车辆停止的车速 |

## 5. 关键变量

| 变量名 | 类型 | 来源 | 含义 |
| :--- | :--- | :--- | :--- |
| `fctbSystemState` | `uint8_t` | `adasFunc.c` | FCTB 系统当前状态机状态 |
| `bFctbKeepBrakeFlg` | `bool` | `adasFunc.c` | 是否保持制动请求的标志位 |
| `fFctbBrakeEventTime` | `float` | `adasFunc.c` | 制动事件持续时间计时器 |
| `fFctbHoldEventTime` | `float` | `adasFunc.c` | 制动保持阶段计时器 |
| `bFctbLeftWarningFlg` | `bool` | `adasFunc.c` | 左侧 FCTB 报警标志 |
| `bFctbRightWarningFlg` | `bool` | `adasFunc.c` | 右侧 FCTB 报警标志 |
| `bFCTBEnable` | `bool` | `RteComMapping.c` | FCTB 功能使能信号 (来自网关/车身控制器) |
| `fctbTimerActive` | `bool` | `ASWIN_SystemState.c` | FCTB 计时器激活标志，用于计算保持时间 |
| `fBrakeValue` | `float` | `perception_public_def.h` | 最终输出的制动减速度值 |
| `bLeftFctbWarning` | `uint8_t` | `perception_public_def.h` | 左侧 FCTB 警告输出信号 (0/1/2) |
| `bRightFctbWarning` | `uint8_t` | `perception_public_def.h` | 右侧 FCTB 警告输出信号 (0/1/2) |

## 6. 输入信号

1.  **车辆信号**:
    *   `VehcleInfoUpdate.steer_angle`: 方向盘角度，用于判断车辆意图及 ROI 调整。
    *   `VehcleInfoUpdate.actual_gear`: 实际档位，用于判断是否处于行驶或倒车状态（FCTB 通常在 D 档或 N 档低速时工作）。
    *   `VehcleInfoUpdate.speed`: 当前车速，用于状态机转换和阈值判断。
2.  **功能使能信号**:
    *   `FCTABrkSwtReq` / `FCTASwtReq`: 来自网关或车身控制器的 FCTB/FCTA 开关请求信号。
    *   `bFCTBEnable`: 内部处理后的 FCTB 使能标志。
3.  **感知数据**:
    *   前方交叉交通目标列表 (Object List): 包含目标的距离 (X, Y)、速度 (Vx, Vy)、TTM、DDCI 等。
    *   ROI 定义: 基于车道宽度的前方交叉区域 (`fTGURearX`, `fTGUFrontX` 等，虽然变量名带 TGU，但 FCTB 复用或类似定义)。
4.  **故障信号**:
    *   `ASWOUT_OutCalc_Get_RR_Fault_Err()` / `ASWOUT_OutCalc_Get_RL_Fault_Err()`: 雷达故障状态。

## 7. 输出信号

1.  **制动请求**:
    *   `RSDS_BrkgReq`: 制动请求标志 (Boolean)。
    *   `RSDS_BrkgReqVal`: 制动请求值 (Float, m/s²)，通常为 `fFctbBrakeValue` (-4.0) 或 `fFctbHoldValue` (-2.0)。
    *   具体 CAN 信号: `FL_fBrakeValue`, `FR_Fctb_Warning` (在某些架构中 Warning 信号也用于触发制动)。
2.  **状态与警告**:
    *   `fctbSystemState`: 系统状态，用于仪表显示或诊断。
    *   `bLeftFctbWarning` / `bRightFctbWarning`: 左右侧警告状态，用于 HMI 提示。
    *   `CR_FCTB_Resp`: 向网关回传的功能响应信号，确认功能已使能或状态。
3.  **诊断信号**:
    *   `FL_Fault_Err` / `FR_Fault_Err`: 故障报错信号。

## 8. 与其他功能的交互

1.  **FCTA (Front Cross Traffic Alert)**:
    *   **强耦合**: FCTB 是 FCTA 的后续执行层。FCTA 负责预警，FCTB 负责制动。
    *   **共享逻辑**: 两者共享大部分阈值参数（如 TTM 阈值在代码中非常接近，甚至部分变量名相似，如 `fFctaObjWarningUpTTMY` 与 `fFctbObjWarningUpTTMY` 数值不同但逻辑一致）。
    *   **状态依赖**: 通常 FCTB 的 Active 状态依赖于 FCTA 的 Active 状态或相同的使能条件。代码中 `FCTB_Standby2Active` 可能与 FCTA 状态联动。

2.  **RCTB (Rear Cross Traffic Braking)**:
    *   **对称功能**: RCTB 是后方交叉交通制动，逻辑与 FCTB 高度对称，但部署在后角雷达。
    *   **资源隔离**: 代码中明确区分了 `fctbTimerActive` 和 `rctbTimerActive`，以及各自的保持时间函数 `FCTBHoldThree` 和 `RCTBHoldThree`。
    *   **调度分离**: 在 `AswIfSchedule.c` 中，前雷达（FL/FR）调用 `UpdateFctaAndFctbSystemStatus`，后雷达（RL/RR）调用 `UpdateRctaAndRctbSystemStatus`，确保处理逻辑的物理隔离。

3.  **AEB (Autonomous Emergency Braking)**:
    *   FCTB 本质上是一种特定场景（低速交叉交通）下的 AEB 应用。它使用相同的制动执行器接口 (`RSDS_BrkgReq`)。

4.  **TGU (Turn Guard / 转弯辅助)**:
    *   代码中定义了 TGU 的 ROI 参数 (`fTGURearX` 等)，虽然 FCTB 有独立的参数，但在某些实现中，FCTB 的 ROI 可能参考 TGU 的几何定义，或者两者在低速转弯场景下有重叠。代码注释显示 TGU 部分被注释掉或未完全启用，但参数存在。

5.  **网关 (Gateway)**:
    *   通过 `RteComMapping` 与网关通信，接收使能信号 (`FCTABrkSwtReq`) 并发送状态响应 (`CR_FCTB_Resp`)。网关负责协调不同域控制器之间的功能开关。