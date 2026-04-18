# LCA 功能分析

## 1. 功能概述
LCA (Lane Change Assist，变道辅助) 是角雷达系统的一项核心功能，旨在监测车辆侧后方盲区内的动态障碍物。当驾驶员在特定车速和转向条件下尝试变道，且侧后方存在可能引发碰撞的车辆时，系统会发出警告（通过指示灯或声音），提醒驾驶员取消变道操作。

根据提供的源码，LCA 功能主要运行在 **20ms** 的任务周期中 (`asw_coem_Mainfunctin_20ms`)，与 BSD (盲区检测) 共享部分 ROI (感兴趣区域) 定义和传感器数据，但拥有独立的激活阈值、状态机逻辑和报警判定条件。系统支持左右两侧独立工作，并通过公共 CAN 总线输出警告状态。

## 2. 状态机
LCA 功能的状态机定义在 `ASWIN_SystemState.h` 注释中，状态流转逻辑主要分布在 `ASWIN_SystemState.c` 的 `AdasEnable` 和 `AdasStateActive` 函数中。

### 状态定义
*   **0 - None**: 未初始化/未定义
*   **1 - Init**: 初始化中
*   **2 - Standby (Ready)**: 系统就绪，满足激活条件，正在监测但尚未触发报警。
*   **3 - Active**: 系统激活，已检测到危险目标并触发报警。
*   **4 - Off**: 系统关闭（通常由开关或故障导致）。
*   **5 - Failure**: 系统故障。
*   **6 - Passive**: 被动模式（通常用于拖车模式或特定抑制场景）。

### 状态转换逻辑
1.  **Standby (2) $\to$ Active (3)**:
    *   **条件**: 当前状态为 `Standby` (`lcaSystemState == 2`) **且** 检测到报警信号 (`PEROutput.adasWarning.bLeftLcaWarning != 0` 或 `PEROutput.adasWarning.bRightLcaWarning != 0`)。
    *   **代码位置**: `ASWIN_SystemState.c` L694-L697。
    *   **逻辑**: 一旦感知算法判定存在碰撞风险并输出非零警告等级，系统立即进入 Active 状态，点亮仪表盘或后视镜指示灯。

2.  **Active (3) $\to$ Standby (2)**:
    *   **条件**: 虽然源码片段未直接展示从 Active 回退的 `if` 语句，但根据 `AdasEnable` 函数逻辑 (L608-L615)，当不再满足激活条件（如车速过低、开关关闭、或报警信号消失导致 `bLCAEnable` 变为 FALSE）时，状态机通常会回退。
    *   **隐含逻辑**: 在 `AdasStateActive` 中，如果报警信号消失，`lcaSystemState` 不会被强制保持为 3，结合 `AdasEnable` 的逻辑，状态将回退至 Standby 或 Off。

3.  **Standby/Active $\to$ Off/Failure**:
    *   **条件**: 功能开关关闭 (`bLCAEnable == FALSE`) 或 系统检测到故障 (`ErrSts()` 返回 true)。
    *   **代码位置**: `ASWIN_SystemState.c` L608-L615 (Enable 逻辑)，L260-L264 (Error 逻辑)。

4.  **Standby/Active $\to$ Passive (6)**:
    *   **条件**: 拖车模式激活 (`AdasStM.TrailerSts == 1`) 且系统处于特定状态。
    *   **代码位置**: `ASWIN_SystemState.c` L390-L391。

## 3. 报警/制动逻辑
LCA 功能目前主要提供**报警**（Warning），未包含自动制动（Braking）逻辑（制动通常由 RCTB/FCTB 负责）。

### 报警触发条件
1.  **系统就绪**: 系统状态必须为 `Standby` 或 `Active`。
2.  **目标检测**:
    *   目标位于 LCA 的 ROI 区域内（由 `LineLCAC`, `LineLCAA`, `LineBSDLCAG` 等定义）。
    *   目标满足相对速度阈值 (`fLcaObjWarningSpd`)。
    *   目标满足 TTC (Time To Collision) 阈值 (`fLcaObjWarningTTC`)。
3.  **驾驶员意图**: 虽然源码片段未直接展示转向灯逻辑，但 LCA 通常结合转向灯信号 (`LCASwtReq`) 判断变道意图。在 `RteComMapping.c` 中读取了 `LCASwtReq` 信号。
4.  **动作**: 当上述条件满足时，`PEROutput.adasWarning.bLeftLcaWarning` 或 `bRightLcaWarning` 被置为非零值（通常 1 为一级警告，2 为二级警告），进而触发状态机进入 `Active`。

### 报警取消条件 (De-warning)
1.  **目标离开 ROI**: 目标移出 LCA 监测区域。
2.  **相对速度降低**: 目标相对速度低于去警告阈值 (`fLcaObjDeWarningSpd`)。
3.  **TTC 增加**: 碰撞时间大于去警告阈值 (`fLcaObjDeWarningTTC`)。
4.  **边界偏移**: 目标位置超出设定的去警告边界偏移量 (如 `fLcaObjDeWarningLeftTopOffSetX` 等参数)。
5.  **系统状态**: 车速低于激活阈值或高于上限阈值。

## 4. 关键阈值
根据 `adasFunc.c` 中的参数定义：

| 参数名称 | 变量名 | 数值 | 单位 | 含义 |
| :--- | :--- | :--- | :--- | :--- |
| **系统激活车速** | `fLcaActiveSpd` | 12.0 | km/h | 车辆速度高于此值，系统进入 Standby |
| **系统去激活车速** | `fLcaDeactiveSpd` | 10.0 | km/h | 车辆速度低于此值，系统退出 (迟滞) |
| **系统激活上限车速** | `fLcaActiveUpperSpd` | 146.0 | km/h | 超过此速度系统可能限制功能 |
| **系统去激活上限车速** | `fLcaDeactiveUpperSpd` | 151.0 | km/h | 超过此速度系统退出 (迟滞) |
| **激活曲率半径** | `fLcaActiveCurbRadius` | 125.0 | m | 车辆转弯半径大于此值才激活 |
| **去激活曲率半径** | `fLcaDeactiveCurbRadius` | 75.0 | m | 转弯半径小于此值退出 (迟滞) |
| **目标报警相对速度** | `fLcaObjWarningSpd` | 7.2 | km/h | 目标相对速度大于此值触发报警 |
| **目标去报警相对速度** | `fLcaObjDeWarningSpd` | 3.6 | km/h | 目标相对速度小于此值取消报警 |
| **目标报警 TTC** | `fLcaObjWarningTTC` | 4.0 | s | 碰撞时间小于此值触发报警 |
| **目标去报警 TTC** | `fLcaObjDeWarningTTC` | 4.7 | s | 碰撞时间大于此值取消报警 (迟滞) |
| **LCA ROI 纵向起点** | `LineLCAC` | -4.0 - `DISTANCEREAR` | m | 侧后方监测区域起始点 |
| **LCA ROI 纵向终点** | `LineLCAA` | -80.0 - `DISTANCEREAR` | m | 侧后方监测区域结束点 |
| **LCA ROI 横向边界** | `LineBSDLCAG` / `LineBSDLCAL` | ±3.3 + `EGOCARWIDTH`/2 | m | 侧方监测宽度边界 |

*注：ROI 参数中的 `DISTANCEREAR` 和 `EGOCARWIDTH` 为车辆配置参数，具体数值需查阅 `paraDefine.h`。*

## 5. 关键变量

| 变量名 | 类型 | 来源 | 含义 |
| :--- | :--- | :--- | :--- |
| `lcaSystemState` | `uint8` | `ASWIN_SystemState.c` | LCA 功能当前状态机状态 (0-6) |
| `bLCAEnable` | `bool` | `RteComMapping.c` / `ASWIN_SystemState.c` | LCA 功能使能标志，由开关请求和系统状态决定 |
| `bLeftLcaWarning` | `uint8` | `ADAS` 感知算法输出 | 左侧 LCA 警告等级 (0:无，1:一级，2:二级) |
| `bRightLcaWarning` | `uint8` | `ADAS` 感知算法输出 | 右侧 LCA 警告等级 |
| `LCASwtReq` | `uint8` | `RteComMapping.c` (CAN) | 驾驶员变道开关请求信号 (转向灯) |
| `fLcaActiveSpd` | `float` | `adasFunc.c` | LCA 激活车速阈值 |
| `fLcaObjWarningTTC` | `float` | `adasFunc.c` | LCA 目标报警 TTC 阈值 |
| `LineLCAC` / `LineLCAA` | `float` | `adasFunc.c` | LCA 监测区域纵向边界坐标 |
| `AdasStM.LCAState` | `uint8` | `AswIfSchedule.c` | 全局状态机结构体中的 LCA 状态副本 |

## 6. 输入信号
LCA 功能依赖以下输入信号进行决策：
1.  **车辆状态信号**:
    *   车速 (Vehicle Speed)
    *   方向盘转角/曲率半径 (Steering Angle / Curb Radius)
    *   档位 (Gear) - 虽未直接显示在 LCA 逻辑中，但通常作为前置条件
2.  **驾驶员意图信号**:
    *   转向灯请求 (`LCASwtReq`) - 通过 `RteComMapping_ReadSignal` 读取。
3.  **环境感知信号**:
    *   角雷达检测到的目标列表 (位置、速度、加速度、RCS 等)。
    *   目标是否在 LCA ROI 内。
4.  **系统配置/开关**:
    *   LCA 功能开关状态 (`bLCAEnable` 来源)。
    *   车辆配置参数 (车宽 `EGOCARWIDTH`, 雷达安装位置等)。
5.  **故障信号**:
    *   雷达自身故障状态 (`ErrSts`)。
    *   拖车模式状态 (`TrailerSts`)。

## 7. 输出信号
1.  **警告信号**:
    *   `bLeftLcaWarning` / `bRightLcaWarning`: 发送给仪表或后视镜的警告等级信号。
    *   `RSDS_LCAResp`: 通过 CAN 总线发送的 LCA 响应状态 (Enable/Disable)。
2.  **状态信号**:
    *   `LCAState`: 发送给网关或诊断系统的当前功能状态 (Standby/Active/Failure 等)。
    *   `Blind_Sts`: 盲区状态标志。
3.  **协调信号**:
    *   在 `ASWOUT_OutCalc.c` 中，LCA 警告信号会与 BSD 警告信号进行优先级仲裁 (`if(bRightBsdWarning > bRightLcaWarning)`)，最终输出 `RR_BsdLca_Warning` 信号。

## 8. 与其他功能的交互
1.  **与 BSD (Blind Spot Detection) 的交互**:
    *   **ROI 共享**: LCA 和 BSD 共享横向边界定义 (`LineBSDLCAG`, `LineBSDLCAL` 等)，但纵向范围不同 (BSD 更近，LCA 更远)。
    *   **输出仲裁**: 在输出阶段 (`ASWOUT_OutCalc.c` L164-L170)，如果 BSD 和 LCA 同时报警，系统会比较两者的警告等级，输出等级较高的警告信号，避免冲突或重复提示。
    *   **状态联动**: 两者共用 `AdasEnable` 逻辑，若任一功能激活，可能影响整体系统供电或状态。

2.  **与 RCTA/RCTB 的交互**:
    *   虽然逻辑独立，但它们共用后角雷达的感知数据。RCTA 关注倒车时的横向交通，LCA 关注行驶时的侧后方交通。
    *   在 `ASWIN_SystemState.c` 的 `DIDTrailerSts` 函数中，LCA 与 RCTA/RCTB 等功能的 `Passive` 状态被统一检查，用于拖车模式抑制。

3.  **与系统状态机 (System State Machine) 的交互**:
    *   LCA 的状态 (`lcaSystemState`) 直接控制 `PERInputCapture.adasEnable.bLCAEnable` 的赋值。
    *   LCA 的报警输出直接驱动 `AdasStateActive` 中的状态转换 (Standby -> Active)。

4.  **与通信层 (RteComMapping) 的交互**:
    *   通过 `RteComMapping_ReadSignal` 获取驾驶员开关请求。
    *   通过 `RteComMapping_WriteSignal` 将 LCA 状态和警告等级发送至 CAN 总线 (如 `RSDS_LCAResp`, `RSDS_CTA_Actv` 等信号)。