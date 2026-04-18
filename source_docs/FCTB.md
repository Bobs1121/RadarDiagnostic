

# FCTB 功能分析

## 1. 功能概述
**FCTB (Front Cross Traffic Braking)** 即前方交叉交通制动功能。该功能主要用于车辆在低速向前行驶场景（如从停车场、车库驶出时），通过角雷达检测前方横向穿越的障碍物（车辆、行人等）。当检测到碰撞风险且时间紧迫时，系统会先发出报警（FCTA），若风险进一步加剧，则自动触发制动请求以避免或减轻碰撞。

## 2. 状态机
根据源码注释 `0-None,1-Init,2-Standby(Ready),3-Active,4-Off,5-Failure,6-Passive` 及速度阈值参数，FCTB 状态机逻辑推断如下：

| 状态值 | 状态名称 | 含义 | 转换条件 (推断) |
| :--- | :--- | :--- | :--- |
| **0** | **None** | 未初始化 | 系统上电初始状态 |
| **1** | **Init** | 初始化 | 系统启动，等待雷达数据就绪 |
| **2** | **Standby** | 待机/就绪 | 功能使能 (`bFCTBEnable`)，但车速不在检测范围内或系统自检中 |
| **3** | **Active** | 激活 | 功能使能 + 车速在检测范围内 (`fFctbDetectLowSpd` ~ `fFctbDetectUpSpd`) + 无故障 |
| **4** | **Off** | 关闭 | 功能被用户关闭或车速超出上限 (`> fFctbDeactiveUpSpd`) |
| **5** | **Failure** | 故障 | 雷达数据异常、传感器故障或系统内部错误 |
| **6** | **Passive** | 被动 | 可能指制动请求被抑制或处于特定降级模式 |

**状态转换关键速度阈值：**
*   **激活 (Active):** 车速在 `0.5 km/h` (`fFctbActiveLowSpd`) 至 `21.0 km/h` (`fFctbActiveUpSpd`) 之间。
*   **去激活 (Deactive):** 车速超过 `22.0 km/h` (`fFctbDeactiveUpSpd`) 或低于 `0.0 km/h` (`fFctbDeactiveLowSpd`)。
*   **检测 (Detect):** 车速在 `0.5 km/h` (`fFctbDetectLowSpd`) 至 `22.0 km/h` (`fFctbDetectUpSpd`) 之间时开启目标检测逻辑。

## 3. 报警/制动逻辑

### 3.1 报警逻辑 (Warning)
*   **触发条件:**
    1.  系统状态为 `Standby` (2) 或 `Active` (3)。
    2.  检测标志 `bFctbDetectFlg` 为真。
    3.  目标物体进入 ROI 区域，且计算出的 TTM (Time To Merge/Intersection) 低于警告阈值。
    4.  X 轴 TTM 判断：`TTMX <= fFctbObjWarningBaseTTMX + fFctbObjWarningTTMXOffSet`。
    5.  Y 轴 TTM 判断：`TTMY <= fFctbObjWarningUpTTMY` 且 `TTMY >= fFctbObjWarningLowTTMY`。
*   **取消条件 (De-warning):**
    1.  系统状态非 `Standby`/`Active` 或 `bFctbDetectFlg` 为假。
    2.  TTM 高于去警告阈值（含迟滞）：`TTMX > fFctbObjWarningBaseTTMX + fFctbObjDeWarningTTMXOffSet`。
    3.  目标离开 ROI 区域。
    4.  通过 `UpdateObjAdasWarningFlg` 函数强制复位警告标志。

### 3.2 制动逻辑 (Braking)
*   **触发条件:**
    1.  报警条件已满足。
    2.  TTM 进一步降低至制动阈值：`TTM <= fFctbAEBActiveThresh` (1.0s)。
    3.  设置制动标志 `bFctbKeepBrakeFlg` 为真。
    4.  记录制动事件时间 `fFctbBrakeEventTime`。
*   **保持逻辑:**
    1.  若制动保持时间超过 `fFctbHoldTimeThresh` (3.0s)，可能切换制动策略（如从 `-4.0` 降至 `-2.0`）。
    2.  若车速低于 `fFctbStopSpd` (1.0 m/s)，可能停止制动请求。
*   **取消条件:**
    1.  风险解除（TTM 增大）。
    2.  驾驶员介入（如踩油门，代码未直接显示但通常逻辑如此）。
    3.  系统状态退出 Active。

## 4. 关键阈值

| 参数变量名 | 默认值 | 单位 | 含义 |
| :--- | :--- | :--- | :--- |
| `fFctbActiveUpSpd` | 21.0 | km/h | 系统激活上限速度 |
| `fFctbActiveMidSpd` | 10.0 | km/h | 系统激活中间速度 (可能用于分级策略) |
| `fFctbActiveLowSpd` | 0.5 | km/h | 系统激活下限速度 |
| `fFctbDeactiveUpSpd` | 22.0 | km/h | 系统去激活上限速度 (迟滞) |
| `fFctbDetectUpSpd` | 22.0 | km/h | 目标检测上限速度 |
| `fFctbDetectLowSpd` | 0.5 | km/h | 目标检测下限速度 |
| `fFctbObjWarningBaseTTMX` | 1.0 | s | X 轴 (纵向) 基础警告 TTM |
| `fFctbObjWarningTTMXOffSet` | 0.0 | s | X 轴警告 TTM 偏移量 |
| `fFctbObjDeWarningTTMXOffSet` | 0.1 | s | X 轴去警告 TTM 偏移量 (迟滞) |
| `fFctbObjWarningUpTTMY` | 1.5 | s | Y 轴 (横向) 警告上限 TTM |
| `fFctbObjDeWarningUpTTMY` | 1.6 | s | Y 轴去警告上限 TTM (迟滞) |
| `fFctbObjWarningLowTTMY` | 0.4 | s | Y 轴警告下限 TTM |
| `fFctbObjWarningSecLowTTMY` | 0.0 | s | Y 轴二级警告下限 TTM |
| `fFctbBrakeValue` | -4.0 | m/s² | 制动请求减速度值 (负值表示减速) |
| `fFctbHoldValue` | -2.0 | m/s² | 制动保持减速度值 |
| `fFctbAEBActiveThresh` | 1.0 | s | 触发 AEB 制动的 TTM 阈值 |
| `fFctbHoldTimeThresh` | 3.0 | s | 制动保持时间阈值 |
| `fFctbStopSpd` | 1.0 | m/s | 停止制动请求的车速阈值 |

## 5. 关键变量

| 变量名 | 类型 | 来源/作用域 | 含义 |
| :--- | :--- | :--- | :--- |
| `fctbSystemState` | `uint8_t` | 全局变量 | FCTB 功能状态机当前状态 (0-6) |
| `bFctbDetectFlg` | `bool` | 静态变量 | 目标检测使能标志，受车速范围控制 |
| `bFctbLeftWarningFlg` | `bool` | 静态变量 | 左侧 FCTB 警告标志 |
| `bFctbRightWarningFlg` | `bool` | 静态变量 | 右侧 FCTB 警告标志 |
| `bFctbKeepBrakeFlg` | `bool` | 全局变量 | 保持制动请求标志 |
| `fFctbBrakeEventTime` | `float` | 全局变量 | 制动事件发生时间戳 |
| `fFctbHoldEventTime` | `float` | 全局变量 | 制动保持事件时间戳 |
| `objFctbWarningFlag` | `int8_t` | 对象结构体 | 单个目标的 FCTB 警告状态 (Normal/Warning) |
| `bLeftFctbWarning` | `uint8_t` | 警告结构体 | 左侧 FCTB 系统级警告输出 |
| `bRightFctbWarning` | `uint8_t` | 警告结构体 | 右侧 FCTB 系统级警告输出 |

## 6. 输入信号
该功能依赖以下输入信号进行决策：
1.  **车辆状态:**
    *   自车速度 (`carSpd`)：用于状态机跳转和检测使能。
    *   曲率半径 (`curvature_radius`)：用于 ROI 计算和路径预测。
    *   转向角/转向信号 (隐含)：用于判断行驶意图。
2.  **雷达感知数据 (`objOutStruct`):**
    *   目标列表 (`trcNum`, `trcOutData`)。
    *   目标位置 (`distXRefer`, `distYRefer`)。
    *   目标速度 (`velX`, `velY`)。
    *   目标类型/概率 (`objTypeProp`, `obstProbability`)。
3.  **功能配置 (`adasEnableStruct`):**
    *   `bFCTBEnable`：功能开关。
    *   `bFCTAEnable`：通常 FCTB 依赖 FCTA 的报警逻辑。
4.  **环境信息:**
    *   路沿信息 (`curbDBSCANOutput`)：用于 ROI 边界修正。

## 7. 输出信号
1.  **报警信号:**
    *   `bLeftFctbWarning` / `bRightFctbWarning`：发送给 HMI 或仪表盘，提示驾驶员前方有交叉交通风险。
    *   `objFctbWarningFlag`：标记具体危险目标。
2.  **制动请求:**
    *   `bFctbKeepBrakeFlg`：制动保持标志。
    *   减速度请求值：基于 `fFctbBrakeValue` 或 `fFctbHoldValue` 计算得出，发送给底盘制动控制器。
3.  **EDR 数据:**
    *   `objOutEDRStruct`：记录事故前的关键目标信息，用于事件数据记录。

## 8. 与其他功能的交互
1.  **FCTA (Front Cross Traffic Alert):**
    *   **强依赖:** FCTB 通常复用 FCTA 的 ROI 计算和目标筛选逻辑。代码中函数 `FrontCrossTrafficAlertAndBrake` 同时处理 Alert 和 Brake。
    *   **状态同步:** FCTB 的警告标志 (`bFctbLeftWarningFlg`) 往往在 FCTA 报警之后或同时触发。
2.  **TGU (Traffic Guidance Unit):**
    *   代码中定义了 TGU 相关参数和 ROI (`fTGURearX`, `fTGUFrontX` 等)，虽然 FCTB 主要关注前方，但在路口场景下，TGU 可能提供车道线信息辅助 FCTB 的 ROI 构建。
3.  **BSD/LCA:**
    *   在 `UpdateObjAdasWarningFlg` 函数中，FCTB 与其他功能（BSD, LCA, RCTA 等）共享对象警告标志复位逻辑，确保当功能不激活时，对象不会被错误标记。
4.  **EDR (Event Data Recorder):**
    *   通过 `SelectEDRObjects` 函数，FCTB 触发时会筛选关键目标记录到 EDR 中，用于事故分析。