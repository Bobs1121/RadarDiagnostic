

# RCTA 功能分析

## 1. 功能概述
RCTA (Rear Cross Traffic Alert，后方交叉交通警报) 功能主要用于车辆在倒车过程中，监测车辆后方左右两侧是否有横向行驶的车辆或障碍物。当检测到潜在碰撞风险时，系统通过声光报警提醒驾驶员，防止倒车碰撞事故。该功能依赖于角雷达对后方目标的探测、跟踪以及车辆自身运动状态（速度、档位、横摆角速度）的综合判断。

## 2. 状态机
根据 `RctaRctbUpdateStatus` 函数逻辑，RCTA 系统状态机定义如下：

| 状态值 | 状态名称 | 转换条件 |
| :--- | :--- | :--- |
| **0** | **None** | 默认状态，当 `g_DTCCode.selfInspFlg` 为 false 时进入。 |
| **1** | **Init** | 当 `g_DTCCode.selfInspFlg` 为 true 且当前状态为 None 时进入。 |
| **2** | **Standby** | 功能使能 (`bRCTAEnable`) + 无故障 + 无标定 + 档位为倒档 (7) + 车速在 0~15 km/h 之间。 |
| **3** | **Active** | 代码片段未显式展示进入逻辑，但警告逻辑中检查此状态。通常由 Standby 状态检测到目标后进入。 |
| **4** | **Off** | 功能未使能 (`!bRCTAEnable`) 或 系统正在标定 (`calibratingFlg`)。 |
| **5** | **Failure** | 系统自检故障 (`failureFlg`)。 |
| **6** | **Passive** | 原处于 Standby/Active 状态，但车速超过 17 km/h 或 档位非倒档。 |

## 3. 报警/制动逻辑

### 3.1 报警触发条件
1.  **系统状态**: `rctaSystemState` 必须为 **Standby (2)** 或 **Active (3)**。
2.  **功能使能**: `adasEnable->bRCTAEnable` 为 true。
3.  **目标检测**: `bRctaDetectFlg` 为 true (表示检测到有效目标)。
4.  **ROI 区域**: 目标位于计算出的左侧或右侧 ROI (Region of Interest) 多边形内。
5.  **时间阈值**: 目标与车辆的碰撞时间 (TTM) 小于警告阈值 (`fRctaObjWarningTTM` = 4.2s)。
6.  **角度阈值**: 目标相对车辆的偏航角 (Yaw Angle) 在警告范围内 (45° ~ 135°)。
7.  **距离阈值**: 目标的 DDCI (Distance to Collision Intersection) 在警告范围内 (Base DDCI -5.0m ~ 0.0m)。

### 3.2 报警取消条件
1.  **系统状态**: 系统状态变为 Off (4), Failure (5), Passive (6) 或 None (0)。
2.  **功能关闭**: `adasEnable->bRCTAEnable` 为 false。
3.  **目标消失**: `bRctaDetectFlg` 为 false。
4.  **安全阈值**: 目标 TTM 大于取消阈值 (`fRctaObjDeWarningTTM` = 5.2s)。
5.  **角度/距离**: 目标偏航角超出取消范围 (43° ~ 137°) 或 DDCI 超出取消范围。
6.  **保持逻辑超时**: 报警保持计数器 (`rctaKeepWarningCount`) 超过 `KEEPWARNINGFRM` 帧数且无新目标触发。

### 3.3 报警保持 (Hysteresis)
为了防止报警闪烁，系统设计了保持逻辑：
*   使用 `bRctaLeftKeepFlag` / `bRctaRightKeepFlag` 标记保持状态。
*   使用 `rctaLeftFrmCount` / `rctaRightFrmCount` 记录保持帧数。
*   使用 `bRctaLeftBuffer` / `bRctaRightBuffer` 存储历史状态。
*   当报警条件满足时，启动保持计时；当条件不满足时，若保持帧数未耗尽，报警继续维持。

## 4. 关键阈值

| 参数变量名 | 默认值 | 单位 | 含义 |
| :--- | :--- | :--- | :--- |
| `fRctaActiveUpSpd` | 15.0 | km/h | 系统激活最高车速 |
| `fRctaActiveLowSpd` | 0.0 | km/h | 系统激活最低车速 |
| `fRctaDeactiveUpSpd` | 17.0 | km/h | 系统去激活最高车速 (迟滞) |
| `fRctaObjWarningTTM` | 4.2 | s | 目标警告碰撞时间阈值 |
| `fRctaObjDeWarningTTM` | 5.2 | s | 目标取消报警碰撞时间阈值 |
| `fRctaObjWarningLowYawAngle` | 45.0 | deg | 目标警告最小偏航角 |
| `fRctaObjWarningUpYawAngle` | 135.0 | deg | 目标警告最大偏航角 |
| `fRctaObjDeWarningLowYawAngle` | 43.0 | deg | 目标取消报警最小偏航角 |
| `fRctaObjDeWarningUpYawAngle` | 137.0 | deg | 目标取消报警最大偏航角 |
| `fRctaObjWarningLowBaseDDCI` | -5.0 | m | 目标警告基础 DDCI 下限 |
| `fRctaObjWarningUpBaseDDCI` | 0.0 | m | 目标警告基础 DDCI 上限 |
| `fRctaObjWarningUpSpd` | 200.0 | km/h | 目标警告最高速度 |
| `fRctaRoiOffSetY` | 0.3 | m | ROI Y 轴偏移量 |

## 5. 关键变量

| 变量名 | 类型 | 来源 | 含义 |
| :--- | :--- | :--- | :--- |
| `rctaSystemState` | `uint8_t` | 内部状态机 | RCTA 系统当前状态 (0-6) |
| `bRctaDetectFlg` | `bool` | 检测逻辑 | 是否检测到有效 RCTA 目标 |
| `bRctaLeftWarningFlg` | `bool` | 内部逻辑 | 左侧 RCTA 报警内部标志 |
| `bRctaRightWarningFlg` | `bool` | 内部逻辑 | 右侧 RCTA 报警内部标志 |
| `adasWarning->bLeftRctaWarning` | `uint8_t` | 输出结构体 | 发送给仪表/报警器的左侧报警信号 |
| `adasWarning->bRightRctaWarning` | `uint8_t` | 输出结构体 | 发送给仪表/报警器的右侧报警信号 |
| `rctaKeepWarningCount` | `uint8_t` | 内部逻辑 | 报警保持计数器 |
| `fRctaObjWarningTTM` | `float` | 外部参数 | 警告 TTM 阈值 |
| `g_egoCarAddInfo.carSpd` | `float` | 车辆总线 | 自车车速 |
| `g_egoCarAddInfo.actual_gear` | `uint8_t` | 车辆总线 | 自车档位 (7=Reverse) |
| `g_egoCarAddInfo.yawRate` | `float` | 车辆总线 | 自车横摆角速度 (用于 ROI 计算) |

## 6. 输入信号
该功能依赖以下输入信号进行决策：
1.  **车辆状态**:
    *   车速 (`g_egoCarAddInfo.carSpd`)
    *   档位 (`g_egoCarAddInfo.actual_gear`)
    *   横摆角速度 (`g_egoCarAddInfo.yawRate`)
    *   车辆宽度 (`g_egoCarFixPara.vehicle_width`)
    *   后保险杠距离 (`g_egoCarFixPara.rear_bumper_distX` 或 `DISTANCEREAR`)
2.  **系统状态**:
    *   功能使能开关 (`adasEnable->bRCTAEnable`)
    *   自检标志 (`g_DTCCode.selfInspFlg`)
    *   故障标志 (`g_DTCCode.failureFlg`)
    *   标定标志 (`g_DTCCode.calibratingFlg`)
3.  **感知数据**:
    *   目标列表 (Object List，包含距离、速度、角度等，用于计算 TTM 和 ROI 判断)

## 7. 输出信号
1.  **报警信号**:
    *   `adasWarning->bLeftRctaWarning`: 左侧后方交叉交通报警 (0/1)。
    *   `adasWarning->bRightRctaWarning`: 右侧后方交叉交通报警 (0/1)。
2.  **系统状态**:
    *   `adasWarning->rctaSystemState`: 当前系统状态 (0-6)。
3.  **对象属性**:
    *   `objInfo->trcOutData[i].objRctaWarningFlag`: 单个目标的报警状态标志。

## 8. 与其他功能的交互
1.  **RCTB (Rear Cross Traffic Braking)**:
    *   **状态共享**: RCTA 和 RCTB 共用 `RctaRctbUpdateStatus` 函数更新系统状态，逻辑高度相似（档位、车速阈值略有不同）。
    *   **ROI 计算**: 两者使用类似的 ROI 计算逻辑 (`ResetRctaRoi` 和 `GetRctaArcPoint`)，根据车辆曲率动态调整探测区域。
    *   **依赖关系**: RCTB 通常作为 RCTA 的升级功能，当 RCTA 报警且满足更严格的制动条件时，RCTB 介入。代码中 `CloseRctbFunc` 和 `CloseRctaFunc` 结构相似，表明两者在复位逻辑上解耦但并行。
2.  **RCW (Rear Collision Warning)**:
    *   代码中 RCW 和 RCTA 的报警取消逻辑类似（检查系统状态和检测标志），但 RCW 关注正后方追尾，RCTA 关注侧后方交叉。
3.  **DOW (Door Open Warning)**:
    *   共用部分 ROI 计算变量和复位逻辑 (`CloseDowFunc` 与 `CloseRctaFunc` 结构一致)，但 DOW 关注静态或低速开门场景，RCTA 关注倒车动态场景。
4.  **感知层**:
    *   依赖感知层 (`AswPerception`) 提供的目标跟踪数据 (`g_pMthObj`)，功能层 (`adasFunc`) 仅负责逻辑判断和报警输出。