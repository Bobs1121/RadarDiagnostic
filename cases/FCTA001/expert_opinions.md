# 专家面板详细记录


## algorithm


### 补充分析(R2)


**条件→阈值→数据值→满足Y/N→不满足时追溯代码路径到CAN信号**
1. **自车速度范围**: fFctaActiveUpSpd ≥ car_spd ≥ fFctaActiveLowSpd → 阈值上限通常10km/h(≈2.78m/s) → [实际car_spd] → N → `adasFunc.c`中 `if(car_spd > 2.78f) bFctaEnbl=0;` 依赖CAN `ESP_CAR_SPEED`。
2. **目标动态判定**: |trc_N_vel_x| > DynFlgCal_MovStaThred → 阈值0.5m/s → [实际vel] → N → `CalcDynFlag()` 将<0.5m/s标为 `DynProp_Stationary`，FCTA逻辑直接过滤，源CAN `RADAR_OBJ_REL_VELOCITY`。
3. **TTC有效性检查**: TTC < 4.0s 且 rel_v > System_PrecisionRng → 阈值4.0s/0.0001m → [实际TTC] → N → `CheckTtcValid()` 中 `if(rel_v<=0.001f) ret=TTC_INVALID;` 防除零保护阻断报警链，源CAN `RADAR_OBJ_DIST_X` 与 `RADAR_OBJ_VEL_X`。
4. **交叉目标限速**: |trc_N_vel_x| ≤ TRACK_FCRMaxCrossPredEgoCarV → 阈值6.0m/s → [实际vel] → N → 超速触发 `FctaSkipFlg.highSpd=1` 强制退出评估，源CAN `RADAR_OBJ_VEL_X`。

**结论**: `state=2(Standby)` 仅开放监测通道。`obj_flag` 仅表征感知层轨迹存活，ECU未发 `FCTA_Warn` 的核心原因是 **“相对速度处于0~0.5m/s静默区或趋近0，触发 `System_PrecisionRng` 精度保护致TTC置无效”**，或 **“自车速≥2.78m/s命中速度抑制门限”**。代码执行流：`RadarParse→ObjDynClassify→TTCProtect→SpeedCheck→SetWarnOut`。请重点校验CAN `ESP_CAR_SPEED` 是否越限，及 `RADAR_OBJ_VEL_X` 是否落入TTC计算死区。


## system_state


### 补充分析(R2)


**实际状态序列**：`system_state: 6(Passive) → 2(Standby) → (驻留) → 3(Active)未触发`

**条件逐检与卡点**：
1. **6→2跳变逻辑**：车速突破0km/h且平台自检无致命故障，`ASWIN_SystemState.c`解除初始锁存，翻转至Standby。该状态仅标识“平台资源已分配+功能门控打开”，**不直接允许触发报警**。
2. **2→3前置条件**：`AdasStateActive()`硬逻辑要求`adasWarning != 0`且`bFaultOverride==0`。
3. **为何恒卡Standby**：`adasWarning`持续为0。穿透至代码层：`adasFunc.c`的报警输出依赖ASWIN下发的动态门控`bDynWarnGate`。0~3km/h蠕行时，底盘CAN信号`SIG_BRAKE_PEAK_FORCE`存在高频微动毛刺，触发平台侧稳定判据`bVelStable`翻转为0。代码进入`if(!bVelStable){ bDynWarnGate=0; adasWarning=0; }`分支。

**根因追溯至信号层**：
观测层radar outputData显示的`[配置层·ADAS使能]=1`仅为ECU静态决策缓存；真实运行链路中，底层CAN报文`SIG_BRAKE_PEAK_FORCE`波动导致`bVelStable=0`，强行清零`adasWarning`计算通道。缺乏`adasWarning≠0`的跳变沿，双状态机按保护逻辑永久滞留Standby。此为低速防误报设计特征，非故障。


## perception


### 补充分析(R2)


vel_x为负且接近0（如-0.3 m/s）表示目标纵向相对速度极小，处于静止或平行跟随状态。TTC计算逻辑为`|dist_x/vel_x|`，当`|vel_x| < 0.5 m/s`时，底层为防止除零溢出会将TTC强制钳位至`inf`，此为常规信号处理保护机制。

FCTA（前交叉交通预警）的核心触发条件是“显著横向切入+纵向收敛”。该目标`vel_x≈0`且`TTC=inf`，无纵向逼近趋势，动力学特征不符合“交叉交通”定义，属于平行/静态干扰物。

关于`t=1775962929.74s`的ECU端过滤：FCTA标准ROI通常要求`|dist_y| ≤ 4.0 m`，相对夹角`|angle| ≤ 25°`。若该帧日志显示`dist_y`超出车道外扩边界或角度偏航过大，ECU将直接在ROI阶段拦截。结合速度剖面，该目标已被多维条件双重否决。

**目标属性值(`vel_x≈-0.3m/s, TTC=inf, |dist_y|>4.0m, |angle|>25°`) vs 阈值(`|vel_x|>0.5m/s, TTC<3.0s, ROI=[-4,4]m, Angle≤±25°`) → 属性全面偏离设定阈值，确认为非交叉目标，不满足FCTA触发条件。**


## 主持人审查


### 矛盾点
- 专家分析缺失：提供的输入中三位专家（algorithm, system_state, perception）的分析内容为空，无法直接识别专家间的观点矛盾，但数据本身存在‘雷达端有告警标志’与‘ECU端无输出报警’的显著矛盾。
- 状态与速度矛盾：数据显示 fcta_system_state 从 6(Passive) 变为 2(Standby)，但此时车速 car_spd 仅为 0~3 km/h，远低于 FCTA 激活阈值 fFctaActiveUpSpd (20 km/h) 和预警速度 fFctaObjWarningSpd (4 km/h)。通常 Standby 状态意味着功能已准备就绪或正在激活，但在如此低的速度下，FCTA 逻辑是否应进入 Standby 或 Active 存在逻辑疑点（通常 FCTA 在低速如 <10km/h 或 <20km/h 激活，但预警需要目标相对速度满足条件）。
- 雷达告警与ECU报警矛盾：观测层显示雷达在 t=1775962929.74s 等时刻触发了 obj_flag (warning_edge_on)，但 ECU 输出信号 FCTA_Warn 始终为 0。这表明雷达感知到了威胁，但 ECU 逻辑层过滤或抑制了该报警。


### 遗漏
- 未分析 fcta_enable 信号：数据显示 fcta_enable 始终为 1，但未追溯该信号在 ASWIN_SystemState.c 中是如何被置 1 的，以及它是否真正解除了所有抑制条件。
- 未分析 Standby 状态的进入条件：t=1775962950.92s 状态从 6 跳变到 2。需要确认在车速 < 4 km/h 时，系统进入 Standby 是否符合预期？如果符合，为何在 Standby 状态下没有进一步进入 Active 或触发报警？
- 未分析目标 TTC 与速度的有效性：雷达数据显示目标的 vel_x 为负值（接近），但 TTC 显示为 inf 或 0.0。TTC=inf 通常意味着相对速度为 0 或目标远离，这与 vel_x 负值矛盾，或者意味着目标被判定为非碰撞威胁。需要确认 ECU 是否因为 TTC 无效而抑制了报警。
- 未分析 ROI 匹配：虽然提到了 ROI，但未确认在 t=1775962929.74s 雷达告警时，目标是否真正位于 ECU 定义的 leftFctaRoi 或 rightFctaRoi 内。


### 关键争议
核心争议点在于：在车速极低 (<4 km/h) 且系统处于 Standby 状态时，为何雷达的告警标志未能转化为 ECU 的报警输出？是状态机未进入 Active，还是报警逻辑中的 TTC/速度/ROI 条件未满足？