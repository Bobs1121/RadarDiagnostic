

# LCA 功能分析

## 1. 功能概述
LCA (Lane Change Assist，变道辅助) 功能旨在监测车辆侧后方盲区及相邻车道内的动态目标。当系统处于激活状态且检测到有车辆或障碍物进入预设的 ROI (Region of Interest) 区域，并满足特定的相对速度或 TTC (Time To Collision) 条件时，系统会触发报警（通常通过仪表盘或后视镜指示灯），提醒驾驶员变道存在风险。该功能与 BSD (Blind Spot Detection) 共享部分 ROI 定义，但具有独立的激活阈值和报警逻辑。

## 2. 状态机
根据源码 `LcaUpdateSystemStatus` 函数及全局变量定义，LCA 系统状态机包含以下状态及转换逻辑：

| 状态值 | 状态名称 | 含义 | 转换条件 (基于 `LcaUpdateSystemStatus`) |
| :--- | :--- | :--- | :--- |
| **0** | **None** | 未初始化 | 系统自检标志 `g_DTCCode.selfInspFlg` 为假。 |
| **1** | **Init** | 初始化 | 自检标志为真，且当前状态为 0。 |
| **2** | **Standby** | 待机/就绪 | 功能使能 (`bLCAEnable`) 且无故障/标定/拖车模式，档位为 4/5/6，车速在激活范围内，曲率半径满足要求。 |
| **3** | **Active** | 激活 | 代码片段中未显式设置此状态，但报警逻辑允许此状态下输出报警。通常由 Standby 进入。 |
| **4** | **Off** | 关闭 | 功能未使能 (`!bLCAEnable`) 或 拖车模式 (`bTrailerModelFlg`) 或 标定中 (`calibratingFlg`)。 |
| **5** | **Failure** | 故障 | 系统自检标志为真，且存在故障标志 (`failureFlg`)。 |
| **6** | **Passive** | 被动/降级 | 原处于 Standby/Active 状态，但车速低于/高于阈值，或曲率半径过小，或档位不符合要求。 |

**状态转换逻辑摘要：**
1.  **进入 Standby (2)**: `Enable` && `!Trailer` && `!Calib` && `!Failure` && `Gear(4,5,6)` && `Speed >= 12km/h` && `Speed <= 146km/h` && `Radius >= 125m`。
2.  **进入 Passive (6)**: 从 2 或 3 状态，若 `Speed < 10km/h` 或 `Speed > 151km/h` 或 `Radius < 75m` 或 档位不符。
3.  **进入 Off (4)**: 功能开关关闭或硬件/模式限制。
4.  **进入 Failure (5)**: 检测到系统故障。

## 3. 报警/制动逻辑
*注：源码片段主要展示了状态管理和报警标志的清除逻辑，具体的目标过滤算法（如 TTC 计算）未完全展示，但参数已定义。*

*   **报警触发条件 (推断)**:
    1.  系统状态为 **Standby (2)** 或 **Active (3)**。
    2.  目标物体位于 LCA ROI 区域内 (由 `ResetLcaRoi` 定义)。
    3.  目标相对速度满足 `fLcaObjWarningSpd` (7.2 km/h)。
    4.  目标 TTC 满足 `fLcaObjWarningTTC` (4.0 s)。
    5.  功能使能 `adasEnable->bLCAEnable` 为真。
*   **报警取消条件**:
    1.  系统状态变为 **Off (4)**, **Failure (5)**, **Passive (6)**, **None (0)**, **Init (1)**。
    2.  功能开关 `adasEnable->bLCAEnable` 关闭。
    3.  目标离开 ROI 区域（需满足 De-warning 偏移量条件）。
    4.  目标相对速度低于 `fLcaObjDeWarningSpd` (3.6 km/h)。
    5.  目标 TTC 大于 `fLcaObjDeWarningTTC` (4.7 s)。
*   **报警保持 (Keep Warning)**:
    *   使用 `bLcaLeftKeepFlag` / `bLcaRightKeepFlag` 和帧计数器 `lcaLeftFrmCount` / `lcaRightFrmCount`。
    *   报警状态存储在环形缓冲区 `bLcaLeftBuffer` / `bLcaRightBuffer` 中，持续帧数由 `lcaKeepWarnFrm` 控制，防止报警闪烁。
*   **去抖动/迟滞**:
    *   使用 De-warning Offset 参数（如 `fLcaObjDeWarningLeftTopOffSetX`）扩大 ROI 退出边界，确保目标真正离开危险区才取消报警。

## 4. 关键阈值
以下参数定义了 LCA 功能的激活、报警及 ROI 边界：

| 参数变量名 | 默认值 | 单位 | 含义 |
| :--- | :--- | :--- | :--- |
| `fLcaActiveSpd` | 12.0 | km/h | 系统激活最低车速 |
| `fLcaDeactiveSpd` | 10.0 | km/h | 系统退出激活最低车速 (迟滞) |
| `fLcaActiveUpperSpd` | 146.0 | km/h | 系统激活最高车速 |
| `fLcaDeactiveUpperSpd` | 151.0 | km/h | 系统退出激活最高车速 (迟滞) |
| `fLcaActiveCurbRadius` | 125.0 | m | 系统激活最小曲率半径 (直线/大弯) |
| `fLcaDeactiveCurbRadius` | 75.0 | m | 系统退出激活最小曲率半径 (迟滞) |
| `fLcaObjWarningSpd` | 7.2 | km/h | 目标触发报警的相对速度阈值 |
| `fLcaObjDeWarningSpd` | 3.6 | km/h | 目标取消报警的相对速度阈值 |
| `fLcaObjWarningTTC` | 4.0 | s | 目标触发报警的 TTC 阈值 |
| `fLcaObjDeWarningTTC` | 4.7 | s | 目标取消报警的 TTC 阈值 (迟滞) |
| `LineLCAC` | -4.0 - Rear | m | LCA ROI 纵向起始点 (近端) |
| `LineLCAA` | -80.0 - Rear | m | LCA ROI 纵向结束点 (远端) |
| `LineBSDLCAG` | 3.3 + Width/2 | m | LCA ROI 横向外侧边界 (左侧) |
| `LineBSDLCAF` | 0.0 + Width/2 | m | LCA ROI 横向内侧边界 (左侧) |

## 5. 关键变量

| 变量名 | 类型 | 来源/作用域 | 含义 |
| :--- | :--- | :--- | :--- |
| `lcaSystemState` | `uint8_t` | 全局/静态 | LCA 系统当前状态机状态 (0-6) |
| `bLcaLeftWarningFlg` | `bool` | 静态 | 左侧 LCA 报警标志位 |
| `bLcaRightWarningFlg` | `bool` | 静态 | 右侧 LCA 报警标志位 |
| `bLcaLeftKeepFlag` | `bool` | 静态 | 左侧报警保持标志 |
| `lcaLeftFrmCount` | `uint8_t` | 静态 | 左侧报警保持帧计数 |
| `bLcaLeftBuffer` | `uint8_t[]` | 静态 | 左侧报警状态环形缓冲区 |
| `adasWarning->bLeftLcaWarning` | `uint8_t` | 结构体输出 | 发送给上层/仪表的左侧报警信号 |
| `adasWarning->bRightLcaWarning` | `uint8_t` | 结构体输出 | 发送给上层/仪表的右侧报警信号 |
| `adasWarning->lcaSystemState` | `uint8_t` | 结构体输出 | 发送给上层的系统状态 |
| `g_egoCarAddInfo.carSpd` | `float` | 全局输入 | 自车当前车速 |
| `g_egoCarAddInfo.actual_gear` | `uint8_t` | 全局输入 | 自车当前档位 |
| `curvRadius` | `float` | 函数输入 | 当前道路曲率半径 |

## 6. 输入信号
LCA 功能依赖以下输入信号进行状态判断和目标过滤：
1.  **车辆状态**:
    *   `carSpd`: 自车速度 (km/h 或 m/s，代码中涉及 `System_Kmh2ms` 转换)。
    *   `actual_gear`: 自车档位 (需为 4, 5, 6 档)。
    *   `curvRadius`: 道路曲率半径 (m)。
    *   `vehicle_width`: 自车宽度 (用于计算 ROI 横向边界)。
    *   `rear_bumper_distX`: 后保险杠距离 (用于计算 ROI 纵向边界)。
2.  **系统状态**:
    *   `bLCAEnable`: LCA 功能开关。
    *   `selfInspFlg`: 自检标志。
    *   `failureFlg`: 故障标志。
    *   `calibratingFlg`: 标定标志。
    *   `bTrailerModelFlg`: 拖车模式标志。
3.  **感知数据**:
    *   目标物体列表 (`objInfo`): 包含目标位置、速度、TTC 等信息 (用于 `UpdateObjAdasWarningFlg` 逻辑)。

## 7. 输出信号
1.  **报警信号**:
    *   `bLeftLcaWarning`: 左侧变道辅助报警 (0/1)。
    *   `bRightLcaWarning`: 右侧变道辅助报警 (0/1)。
2.  **状态信号**:
    *   `lcaSystemState`: 系统当前状态 (0-6)。
3.  **对象属性**:
    *   `objLcaWarningFlag`: 单个目标对象的 LCA 报警标志 (Normal/Warning)。

## 8. 与其他功能的交互
1.  **BSD (盲区检测)**:
    *   **ROI 共享**: LCA 与 BSD 共享横向 ROI 边界定义 (`LineBSDLCAG`, `LineBSDLCAF` 等)，但纵向范围不同 (LCA 更远，-80m vs BSD -5m)。
    *   **状态互斥**: 在 `UpdateObjAdasWarningFlg` 中，如果系统状态不满足 (非 Standby/Active)，会强制清除 BSD 和 LCA 的报警标志。
2.  **DOW (开门预警)**:
    *   代码中 DOW 和 LCA 的状态机定义一致，且复位逻辑 (`CloseLcaFunc`, `CloseDowFunc`) 结构相似，共享部分全局变量管理方式。
3.  **ELK (紧急车道保持)**:
    *   在 `UpdateObjAdasWarningFlg` 中，检查 `!adasEnable->bLCAEnable && !adasEnable->bELKEnable` 时清除 LCA 报警，暗示 LCA 可能与 ELK 功能存在互斥或共用开关逻辑。
4.  **DTC (诊断)**:
    *   系统状态强依赖于 `g_DTCCode` 中的自检、故障、标定标志。