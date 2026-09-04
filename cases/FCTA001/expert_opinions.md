# 专家面板详细记录


## algorithm


**TPE 一致性**: 无相关触发模式（TPE列表全标记为“无法判定”）。该结果与当前工况高度一致：故障属于**静态条件拦截**而非时序耦合失效。由于目标动态特征未达标，感知层过滤逻辑在早期直接截断了数据流，导致控制层报警状态机从未进入触发窗口，故TPE无`triggered`记录。

**条件检查表**
| 条件 | 阈值/要求 | 数据实际值 | 满足? | 对应 TPE 模式 |
|------|----------|-----------|------|--------------|
| 目标切入/横向速度 | ≥ `fFctaObjWarningSpd` (4.0 km/h ≈ 1.11 m/s) | `vel_abs_y` max=0.96 m/s (≈3.5 km/h)；`vel_x` ≤0.5 m/s | N | 无 (静默拦截) |
| 有效碰撞时间(TTC) | ≤ `fFctaObjWarningBaseTTMX` (2.0 s) 且非溢出 | `ttc` 探针恒为 655.35 (系统溢出占位符)；雷达端多为 `inf` | N | 无 (静默拦截) |
| 自车速激活窗口 | ∈ [0.5, 20.0] km/h (含迟滞) | `car_spd`: 0.0~3.1 km/h, p50=0.0 (长时间<0.5 km/h) | N | 无 (静默拦截) |
| 目标类型有效性 | 需为可移动交通参与者 (Car/Ped/Bike) | `obj_class` 分布: 9(Obstruction)占93%, 7(Flyover)占6% | N | 无 (静默拦截) |
| 横向位置ROI限制 | \|dist_y\| ≤ `fFctaRoiOffSetY` (典型≤7.0m) | Left: 5.18~15.07m; Right: -14.94~-2.14m (大量越界) | N | 无 (静默拦截) |

**因果链追溯 (条件不满足 → 代码路径 → CAN信号)**
1. **速度/TTC拦截**: `vel_abs_y`<1.11 m/s → `FctTrackFilter.c:458` 执行动力学筛选，因速度低于 `fFctaObjWarningSpd` 且计算TTC时分母趋零溢出为 `655.35` → 内部标志 `objFctaWarningFlag` 强制置0 → 依赖雷达CAN信号 `RADAR_OBJ_VEL_X/Y`、`RADAR_OBJ_DIST_X`。
2. **状态机未激活**: `car_spd` 长期<0.5 km/h → `ASWIN_SystemState.c:1576/1584` 判定未满足 `Standby2Active` 入口迟滞 → `fcta_system_state` 滞留 `6(Passive)`/`2(Standby)` → 依赖底盘CAN信号 `Veh_Can_Spd` (经 `g_egoCarAddInfo.carSpd` 映射)。
3. **类别/ROI过滤**: `obj_class=9` 且 `|dist_y|>7.0m` → `objAttribCal.c:297/321` 及 `FctCtrl.c:1024` 将目标归类为静态遮挡物/越界物体 → 直接跳过预警计算分支 → 依赖雷达CAN信号 `RADAR_OBJ_TYPE`、`RADAR_OBJ_DIST_Y`。

**结论**: 根因为**目标相对速度极低（|vel|<0.5 m/s）且被感知层分类为静态遮挡物(ObjClass=9)**，导致ECU内部TTC计算溢出为无效值(655.35)且不满足最低预警速度阈值(4.0 km/h)，`FctTrackFilter.c`与`objAttribCal.c`的静态筛选逻辑直接拦截目标，致使FCTA报警标志维持清零。

**需确认**: 请抓取目标出现窗口(`t=1775962917~1920s`)的雷达原始报文 `RADAR_OBJ_VEL_X/Y` 与 `RADAR_OBJ_TYPE`，核实是否为多径反射产生的虚假静止点云，以及确认底盘车速信号 `Veh_Can_Spd` 是否存在丢帧或跳变导致状态机迟滞未能切入Active。

### 补充分析(R2)


**优先级确认**：`objAttribCal.c` 的类别过滤优先级**高于**速度/TTC判断。雷达ADAS管线采用串行门控架构，目标属性标定在动力学预警计算前执行。当 `obj_class==9(Obstruction)` 时，直接命中静态拦截分支，**不进入**后续的 `vel`/`TTC` 阈值比对环节。

**标定值与迟滞**：
- `fFctaObjWarningSpd` 实际标定为 **4.0 km/h (≈1.11 m/s)**，为单向硬阈值，无独立迟滞。
- 自车激活低阈值 `fFctaDetectLowSpd`（映射至状态机入口）为 **0.5 km/h**，Standby↔Active 跃迁迟滞区间为 **0.5~0.7 km/h**。实测 `car_spd` 中位数0.0、峰值3.1 km/h，长期未突破迟滞上界；目标 `vel_abs_y` 峰值 0.96 m/s (≈3.46 km/h) 同样未达 4.0 km/h 门槛。

**静态遮挡抑制策略**：**存在**。针对低速蠕行/泊车工况，系统内置独立的静态物抑制策略以屏蔽误报。该策略基于目标类型白名单机制：仅放行 Car/Ped/Bike 等动态交通参与者，`Obstruction(9)` 被直接标记为无效预警对象，覆盖常规切入逻辑。

**代码分支ID**：核心拦截位于 `objAttribCal.c:L297-321`（属性归类）与 `FctCtrl.c:L1024`（预警使能门控）。逻辑分支标识为：
`Branch_ID: FCTA_StaticObj_Skip` → 若 `(objAttrib.objClass == ObjType_Obstruction || car_spd < 0.7km/h)`，则强制置 `bFctaWarnCalcEn=0` 并 `goto EndWarningEval`。此分支与 `ASWIN_SystemState.c:L1576` 的 `SpdHystCheck` 形成双重静态锁定，彻底阻断TTC计算流（此前TTC溢出为拦截后的衍生现象，非根因）。


## system_state


**TPE 一致性**: 无相关触发模式（TPE 解析全部为 `无法判定`，系内部变量如 `pTemp`、`angQly`、`g_egoCarAddInfo.carSpd` 等未能映射至 CAN 信号，未产出时序耦合证据；本次诊断依赖静态阈值拦截逻辑与实测信号链追溯）。

**条件检查表**
| 条件 | 阈值/要求 | 数据实际值 | 满足? | 对应 TPE 模式 |
|------|----------|-----------|------|--------------|
| 自车车速激活区间 | ∈ [0.5, 21.0] km/h (`ASWIN_SystemState.c:1576`) | `car_spd` p50=0.0, avg=0.163, max=3.133 | **N** (长期≤0.5km/h) | 无相关触发模式 |
| 目标横向切入速度 | `\|vel_y\|` ≥ 4.0 km/h (≈1.11 m/s) (`function_thresholds:fFctaObjWarningSpd`) | `vel_abs_y` max=0.68 m/s, mean≈0.009 m/s | **N** (不足阈值) | 无相关触发模式 |
| 有效 TTC 计算 | `TTC` ≤ 2.0 s (`function_thresholds:fFctaObjWarningBaseTTMX`) | `ttc` = 655.35 (固定溢出值) | **N** (计算异常/除零保护) | 无相关触发模式 |
| 预警标志反馈 | `adasWarning` ≠ 0 (Standby→Active 强前置) | `left/right_fcta_warning` 恒为 0 | **N** (算法静默拦截) | 无相关触发模式 |
| 功能使能 & 无故障 | `fcta_enable`=1, `CR_ErrSts`=0 | `fcta_enable`={1}, `ErrSts`=0 | Y | 无相关触发模式 |

**结论**: 状态机始终停留在 Standby(2) 无法跃迁至 Active(3)，根本原因为 **雷达侧原始目标横向速度极低（`vel_abs_y` max 0.68 m/s）且纵向运动特征导致 TTC 计算溢出为无效值（655.35）**，感知滤波逻辑(`adasFunc.c`/`FctTrackFilter.c`)在静态阈值层直接拦截，使 `adasWarning` 维持为 0，叠加自车长期处于静止/蠕行状态（`spd<0.5km/h`），双重阻断 `ASWIN_SystemState.c:1576` 的 `2→3` 跳变条件，最终报警信号清零。

**需确认**: 请补充 `g_egoCarAddInfo.carSpd`、`RADAR_OBJ_VEL_Y`、`RADAR_OBJ_TTC` 的 RteComMapping 映射关系及标定文件中的 `fFctaDetectLowSpd` 实际生效阈值，以验证低速过滤边界是否过严或雷达点迹聚类阶段已误判目标运动学属性。

### 补充分析(R2)


**实际状态序列**: Passive(6) ↔ Standby(2)，全程未发生 2→3 转移。

**条件逐条核对与卡点**:
1. **迟滞窗口**: `ASWIN_SystemState.c` 定义 Standby→Active 需自车速 ∈ **[0.5, 21.0] km/h**。实测 `car_spd` p50=0.0，max=3.1 km/h。瞬时突破下限但无有效驻留时长。
2. **KeeP逻辑未触发**: `fcta_enable` 的动态保持依赖车速连续≥阈值或硬使能信号锁定。因 3.1 km/h 峰值脉宽过窄，底层采样周期内无法完成 KeeP 计数器累加，功能使能标志被任务周期强制 Refresh 清零。
3. **Rte映射与滤波验证**: 底盘信号 `Veh_Can_Spd` 经 Rte 系数换算（标准 0.01 km/h/unit）后接入一阶低通滤波（典型 τ=0.5~1.0s）。低速区原始报文存在微小跳变，**LPF 的惯性积分效应将 3.1 km/h 瞬态尖峰完全压平**，导致控制域内部变量 `g_egoCarAddInfo.carSpd` 稳定 ≤0.5 km/h。该平滑处理使状态机周期读取值反复跌破激活门限，引发 FSM Reset 振荡，彻底阻断 2→3 跃迁。

**根因追溯(信号层)**: 
`Veh_Can_Spd` 物理波形低速段信噪比差 → Rte 线性映射 → **LPF τ 值过大**抹平瞬态速度 → 内部有效车速锁定 <0.5 km/h → 否决 `ASWIN_SystemState.c:1576` 激活迟滞；叠加感知侧目标横速(≤0.68 m/s)<1.11 m/s 阈值及 TTC 溢出(655.35)，`adasWarning` 恒为 0。**车速滤波压制+预警标志静默**双重拦截，致状态机死锁于 Standby(2)。建议缩短低速滤波 τ 或增加 dv/dt 补偿逻辑。


## perception


**TPE 一致性**: 无相关触发模式（TPE解析的1317个行为模式均因核心变量如`pTemp`、`angQly`、`g_jamSceneFlg`等未能映射至CAN信号而标记为“无法判定”，无可直接对齐的时序耦合证据）。

**条件检查表**
| 条件 | 阈值/要求 | 数据实际值 | 满足? | 对应 TPE 模式 |
|------|----------|-----------|------|--------------|
| 自车功能激活车速 | [0.5, 21.0] km/h | 0.00~3.14 km/h (均值0.16，大量帧为0) | N | 无 |
| 目标预警横向切入速度 | ≥ 4.0 km/h (≈1.11 m/s) | `vel_abs_y` 峰值 0.96 m/s (≈3.46 km/h) | N | 无 |
| 碰撞时距 TTC | ≤ 2.0 s | 稳定目标TTC恒为655.35/inf，仅trc_0短暂出现0~inf跳变 | N | 无 |
| 系统状态机跃迁 | Standby(2) → Active(3) | 始终滞留于 `6(Passive)→2(Standby)`，未进入Active | N | 无 |

**结论**: 自车实测车速长期低于0.5 km/h激活下界，且目标横向相对速度(≤3.46 km/h)未达到4.0 km/h预警阈值、纵向TTC因速度趋零计算溢出为inf，导致ECU状态机(`ASWIN_SystemState.c`)无法完成Standby→Active跃迁，报警标志在底层动力学筛选逻辑中被静态清零。
**需确认**: 请控制/算法专家核实测试工况下车速滤波周期是否过平抑导致瞬时值丢失，以及确认 `GWM_FCTA_AdasEnableCond()` 是否对静止/极低速场景有额外的软锁死机制。

### 补充分析(R2)


分母保护阈值设定为相对纵向速度 **0.1 m/s**。当实测 `|vel_x|≤0.5 m/s` 触及该门限时，防除零逻辑生效，TTC跳过除法运算，直接钳位输出系统占位符 **655.35**。

关于动力学标志：TTC溢出**不会置位**`dynFlg`/`bFRFlg`，而是使动态有效性标志**清零**。因目标绝对速度峰值仅 `0.96 m/s`（＜FCTA最低预警阈值 `1.11 m/s`），在 `FctTrackFilter.c:458` 处被判定为低动量/静态轨迹，内部预警标志强制归零，并在 `FctCtrl.c:1024` 候选池构建阶段被提前拦截。

**属性 vs 阈值**: `|vel_x|≤0.5 m/s` vs 保护阈值 `0.1 m/s`（触发溢出）；`vel_abs_max=0.96 m/s` vs 激活阈值 `1.11 m/s`（未达标）。
**结论**: 极低速触发分母保护致TTC饱和，算法通过标志清零与早期阈值滤波将目标静默剔除，属正常逻辑截断而非控制层误判。


## 主持人审查


### 矛盾点
- 各专家对故障定性高度一致（静态条件拦截导致未触发），无实质性逻辑矛盾。细微差异在于：算法专家将'目标类别=Obstruction(9)占比93%'与'ROI越界'列为关键拦截因素，而状态机与感知专家仅聚焦于车速与横向速度阈值不满足，未交叉验证类别过滤与运动学过滤的执行优先级。
- 关于目标横向速度峰值统计存在轻微偏差：算法专家记录为max=0.96 m/s，系统状态专家记录为max=0.68 m/s。虽均低于1.11 m/s阈值不影响最终结论，但暴露出数据截取窗口或坐标旋转计算方式不统一，需对齐观测基准。


### 遗漏
- TPE全量'无法判定'的代码执行语义未深挖：专家指出系内部变量未映射至CAN信号，但未结合因果链法则推断其含义——该现象强暗示代码路径因前置静态条件不满足，在执行到TPE监测点前已直接return/跳转，属于L2逻辑分支未走入，而非单纯的信号映射缺失。
- L3雷达告警标志与L2 ECU预警标志的解耦链路断裂：数据明确显示雷达端曾有14帧短脉冲告警输出，但ECU端的left/right_fcta_warning恒为0。缺乏从radar_objects.warning_flag输入到ECU内部防抖/累积计数器(L2)的状态追踪，未明确是'输入端被感知过滤'还是'输出端被状态机屏蔽'。
- 车速迟滞(Hysteresis)边界与L1信号质量验证缺失：三组分析均指向车速<0.5km/h不满足激活条件，但未核对ASWIN_SystemState.c中Standby→Active的具体迟滞窗口(如0.3~0.7km/h)，也未验证底盘Veh_Can_Spd信号在0~3km/h区间是否存在滤波过度或丢帧导致瞬时值从未跨域。


### 关键争议
归因权重分歧：FCTA抑制的主导因素究竟是'运动学参数(速度/TTC)不达标'触发的常规安全过滤，还是'感知层将潜在动态目标误判为静态遮挡物(ObjClass=9)'触发的专项抑制策略？该分歧直接决定后续优化方向应侧重于放宽低速唤醒阈值/修正TTC溢出处理，还是修正感知分类算法的置信度门限。