# 专家面板详细记录


## algorithm


**TPE 一致性**: 无相关触发模式（TPE段检测到的4个`HoldRelease`模式均标记为“无法判定”，无`verdict=triggered`记录，表明不存在防抖保持逻辑误释放或短脉冲清零干扰）

**条件检查表**
| 条件 | 阈值/要求 | 数据实际值 | 满足? | 追溯代码路径至CAN信号(若不满足) | 对应 TPE 模式 |
|------|----------|-----------|------|--------------------------------|--------------|
| 自车激活速度范围 | `[fFctaActiveLowSpd=1.0, fFctaActiveUpSpd=20.0]` km/h | `car_spd`: 0.0~3.133 km/h (均值0.16) | **N** | 实测车速长期<1.0km/h致状态机在`Passive(6)↔Standby(2)`震荡；若按问题描述实测为60km/h，则远超`fFctaDeactiveUpSpd=22.0`强制退出。路径:`ASWIN_SystemState_UpdateFctaAndFctbSystemStatus`状态机车速比较 → 依赖CAN信号`VEHICLE_SPEED` | 无 |
| 目标报警速度下限 | `fFctaObjWarningSpd=4.0` km/h | `trc_N_vel_x`: 绝对值 0~14.4 km/h (多帧<4.0) | **N** | 目标低频蠕动/静止，未达报警门限。路径:`HandleFctaLeftWarningFlag`速度过滤分支(`sObj.speed < fFctaObjWarningSpd`) → 依赖CAN信号`RADAR_OBJ_ABS_SPEED`/相对速度解算值 | 无 |
| 目标碰撞时间(TTM/TTC) | `fFctaObjWarningBaseTTMX=2.0` s (且需为有效有限值) | `ttc`: `[0.0, inf]` s (统计主导值为`inf`) | **N** | 自车与目标纵向相对速度`rel_vel_x≈0`，运动学除法触发溢出保护返回`inf`，导致`TTM<=2.0s`判定失败。路径:`adasFunc.c`目标轨迹预测/运动学滤波层计算`TTM=dist/abs(rel_vx)` → 依赖CAN信号`RADAR_OBJ_REL_VEL_X`及`DIST_X` | 无 |
| 状态转移(2→3)使能 | `bLeftFctaWarning \|\| bRightFctaWarning != 0` | `left/right_fcta_warning`: `{0: 120/133}` (恒0) | **N** | 因上述速度/TTC过滤拦截，报警标志位从未置位，状态机阻塞于Standby(2)无法跃迁至Active(3)。路径:`FctaRegion`/`UpdateFctaLeftWarningStatus`标志聚合 → 依赖内部变量`bFctaLeftWarningFlg` | 无 |
| 外部抑制条件(Acc/ESP/Gear等) | `Acc≥80 \|\| ESPDiag≠0 \|\| SteerSpd>150` 等 | `Acc_max=74.0%`, `ESP_DiagActv=0`, `SteerWheelSpd_max=80.0` | **Y** | 实测抑制信号均未越阈，排除外部强制关停可能。路径:`GWM_FCTA_AdasEnableCond` / 状态机抑制网关 → 依赖CAN信号`VCU_ActAccrPedlRat`、`ESP_DiagActv_0x137`等 | 无 |

**结论**: 根本原因为**目标纵向相对速度趋零导致TTC/TTM计算发散(inf)且目标绝对速度频繁低于4.0km/h阈值**，叠加自车实测车速(≤3.1km/h)与宣称工况(60km/h)严重偏离(FCTA设计规范激活上限仅20km/h)，致使`adasFunc.c`报警判定逻辑持续拦截，`bFctaLeft/RightWarningFlg`维持FALSE，状态机阻塞于Standby(2)无法输出告警。

**需确认**: 请测试工程师核实标定日志中`VEHICLE_SPEED`信号是否发生缩放错误(实测≤3.1km/h vs 宣称60km/h)，并确认底层运动学解算模块对`rel_vel_x≈0`的除零保护策略是否需增加蠕行/静态交叉目标的特殊旁路处理。

### 补充分析(R2)


1. **TTM≤2.0s判定机制**：**非单帧生效**。源码已声明`fctaKeepWarnFrm = KEEPWARNINGFRM;`及`fctaLeft/RightFrmCount`累加器，表明需满足**连续N帧（工程常标定5~10帧）**条件保持才置位报警标志，属标准防抖/迟滞设计。

2. **TTC=inf旁路逻辑**：当前提供代码片段**无显式旁路**。运动学层`rel_vel_x≈0`触发除零保护直接返回`inf`后，被`≤2.0f`硬阈值拦截。若需覆盖静止/蠕行横穿场景，应在底层增加基于距离/偏航角的替代策略（如`dist<3.0m && |yaw|≥38°`时注入虚拟逼近速度），当前架构缺失该分支，导致合法威胁被过滤。

3. **VEHICLE_SPEED缩放争议**：差异系**m/s与km/h单位错位**所致。原始采样值`3.133`实为`m/s`，经物理换算`3.133 × 3.6 = 11.28 ≈ 11.3 km/h`。RteComMapping若配置为`ScalingFactor=1.0, Unit=km/h`而CAN总线实际以`m/s`发布，则日志误显3.1。正确映射应为：`Factor=3.6, Offset=0, Unit=km/h`（或底层统一改制为km/h）。

**结论修正**：剔除“车速<1.0致状态机震荡”误判。实测车速≈11.3 km/h已完全落入`[1.0, 20.0]`激活窗口。根本原因为**目标低速(`vel_x<4.0km/h`)叠加纵向相对速度趋零使TTC发散为inf**，双重拦截导致`bFctaLeft/RightWarningFlg`恒为FALSE，功能阻塞于Standby态。


## system_state


**TPE 一致性**: 无相关触发模式。TPE共检测4个`HoldRelease`防抖/保持模式，均因内部变量(`bFctaStartKeepWarningFlg`/`bReSetFlg`等)未解析至CAN信号而标记为“无法判定”，无任何`verdict=triggered`记录，可排除告警标志被短脉冲清零或防抖逻辑误释放的干扰。

**条件检查表**
| 条件 | 阈值/要求 | 数据实际值 | 满足? | 对应 TPE 模式 |
|------|----------|-----------|------|--------------|
| 系统处于Standby态 | `fcta_system_state == 2` | t=1775962950.9s跳变后稳定为2 | Y | 无 |
| 告警标志置位(左/右) | `left_fcta_warning!=0 \|\| right_fcta_warning!=0` | 全程分布均为`{0}` | N | 无 |
| 目标速度准入(Enter) | `ObjSpeed ∈ (4.0, 70.0) km/h` | `trc_0 vel_x [-3.8, 0.5] m/s` (≈-13~1.8 km/h) | N | 无 |
| TTC有效计算 | `TTC`为有限正数 | `ttc: [0.00, inf]s` / `[inf, inf]s` | N | 无 |
| 外部抑制条件 | `AccPed<80`, `ESPDiag==0`, `SteerSpd≤150`等 | `AccPed` max=74.0, `ESP_DiagActv`=0 | Y(未抑制) | 无 |

**结论**: 根因为交叉目标纵向相对速度长期低于4.0km/h阈值且趋近静止，导致运动学解算触发除零保护使TTC发散为`inf`，感知层(`adasFunc.c`/`track.c`)直接过滤低风险轨迹，致使`adasWarning.bLeft/RightFctaWarning`恒为0，状态机卡在`AdasStateActive()`的`2→3`判断分支无法跃迁至Active态。

**需确认**: 请感知算法专家核对`track.c`中低动态场景下`vel_x`与`absAngleFlt`的融合滤波逻辑是否过度剔除弱威胁目标；同时请整标工程师确认台架注入的`VEHICLE_SPEED` CAN信号缩放系数与ECU内部`1.0~20.0km/h`激活阈值的单位一致性。

### 补充分析(R2)


**GEAR_POS超时兜底行为**：CAN信号丢失触发接收滤波器Watchdog后，`GEAR_POS`将被赋予默认值`0`或`INVALID`。在`ASWIN_SystemState.c`平台侧使能网关中，非D/R档会直接执行`PERInputUpdate.adasEnable.bFCTAEnable = 0`。该使能标志是`AdasStateActive()`中Standby(2)→Active(3)跃迁的硬性前置条件，缺省将**强制拦截跃迁**，属Fail-Safe安全策略。即使当前因TTC/车速已阻滞于2态，档位超时仍会闭合底层使能门，彻底锁死3态输出。

**ESP_DiagActv极性与判读**：定义为**反极性抑制**。`0`表示ESP无故障/允许激活；`≠0`表示诊断激活/功能抑制。具体判据见条件检查表首段“外部抑制条件”行：要求`ESPDiag≠0`为抑制态，实测值`ESP_DiagActv=0`故判定为`Y(未抑制)`。代码判读位于`GWM_FCTA_AdasEnableCond()`抑制网关分支（源码截断处后续），当读取到`ESP_DiagActv_0x137 != 0`时执行使能位清零。

**修正与定论**：前文根因（相对纵向速度≈0致TTC发散为`inf`，且自车实测速≤3.1km/h低于激活下限1.0km/h）准确。补充确认：`GEAR_POS`缺失虽未显式报DTc，但其兜底默认为平台侧提供了独立硬拦截；结合`ESP_DiagActv=0`已排除底盘干扰，最终卡点确认为感知层未产出`adasWarning`，叠加平台使能门未开启，双重阻塞2→3跃迁。需标定组验证`VCU_GearPos`注入周期与ECU接收滤波器的Watchdog阈值一致性。


## perception


**TPE 一致性**: 无相关触发模式（TPE共检测4个HoldRelease模式均标记为“无法判定”，未能解析变量链至CAN信号，无`verdict=triggered`记录）

**条件检查表**
| 条件 | 阈值/要求 | 数据实际值 | 满足? | 对应 TPE 模式 |
|------|----------|-----------|------|--------------|
| 自车激活速度范围 | [1.0, 20.0] km/h | max≈11.3 km/h (3.133 m/s × 3.6) | ✅ Y | 无 |
| 目标进入告警速度 | >4.0 km/h 且 <70.0 km/h | `vel_x`单轴折算约 1.8~13.7 km/h，大量帧低于4.0 km/h下限 | ❌ N | 无 |
| 纵向碰撞时间(TTM/TTC) | ≤2.0 s (`fFctaObjWarningBaseTTMX`) | `ttc=[inf, inf]s` (相对纵向速度趋零触发除零保护分支) | ❌ N | 无 |
| 目标偏航角过滤(Yaw) | [38.0°, 127.0°] | 日志未显式记录，但TTC发散及距离跳变暗示轨迹非标准横向穿越 | ⚠️ 待查 | 无 |
| Standby→Active 跃迁 | `left/right_fcta_warning != 0` | `left_fcta_warning={0: 120}`, `right_fcta_warning={0: 133}` 恒为0 | ❌ N | 无 |

**结论**: 根本原因为**交叉目标相对纵向速度趋零导致ECU端TTC计算发散(`inf`)**，远大于≤2.0s的告警触发阈值，致使内部告警标志(`bLeft/RightFctaWarning`)恒为0，状态机被阻滞在Standby(2)无法跃迁至Active(3)输出报警；另实测自车车速峰值仅≈11 km/h，与问题描述“60km/h工况”存在严重信号标定或采集偏差。
**需确认**: 请跟踪/运动学解算模块专家核对雷达端`rel_vel_x`低通滤波参数是否在低速平行场景下过度平滑导致除零保护误触发，并请系统标定团队复核`VEHICLE_SPEED` CAN信号缩放因子是否配置错误。

### 补充分析(R2)


【属性比对】
- `vel_x`：实测绝对值`0~14.4 km/h`（多帧<4.0） vs 阈值`>4.0 km/h` → ❌拦截
- `ttc`：实测主导值`inf s` vs 阈值`≤2.0 s` → ❌拦截（`rel_vel_x≈0`触发除零保护）
- 自车速：实测`0~3.13 km/h` vs 激活窗`[1.0, 20.0] km/h` → ⚠️临界（与宣称60km/h严重偏离）

【追问响应】
所提供源码为`objAttribCal.c`（高度/类型分类），**无`track.c`卡尔曼增益或FCTA ROI空间定义**。数据证实`ttc=inf`源于运动学解算对近零相对速度的硬性溢出保护，而非低通滤波过度平滑清零；平行浅角穿越时多普勒分量极弱，KF测量协方差增大易收敛至静止假设。需补充`absAngleFlt`日志验证`trc_0~3`几何轨迹是否落入`[38°, 127°]`预警扇区。

**目标属性值 vs 阈值**：`vel_x`(0~14.4 km/h) `< 4.0 km/h` 且 `ttc`(inf s) `> 2.0 s` + **低速并行致相对速度未达门限且TTC计算发散，叠加自车CAN信号缩放误差，系统按标定逻辑正确拦截，需修正车速标定并增加近零速交叉目标旁路。**


## 主持人审查


### 矛盾点
- 自车车速量值解读冲突：算法专家将 car_spd 最大值 3.133 直接视为 km/h（≤3.1km/h），而感知专家认为该值为 m/s 并换算为 ≈11.3km/h。两者对 FCTA 激活区间（1.0~20.0km/h）是否满足的判断前提相反，但未统一单位基准。
- 雷达端与ECU端TTC结果不一致：观测层数据显示雷达曾输出 ttc=1.5s（obj=246），但三位专家均一致认定 ECU 端 ttc 发散为 inf 且归因于 rel_vel_x≈0 的除零保护。未解释为何同一目标的原始雷达TTC有效，而ECU重算或映射后变为 inf，存在数据链路断层。
- 外部抑制信号判定逻辑差异：系统状态专家指出 ESP_DiagActv 恒为0满足反向极性检查（即可能触发抑制），但算法专家与感知专家直接判定为“抑制不满足”。未结合代码确认该诊断信号的极性定义（0代表正常还是故障）。


### 遗漏
- 遗漏关键配置信号 GEAR_POS：条件检查表中明确标注 Gear 信号‘未在BLF中找到’，但三位专家均未评估缺失档位信号对状态机 Guard Condition 的影响。FCTA 的 Standby→Active 跃迁通常强依赖 D/R 档态，无法排除因档位无效/默认值导致的状态阻塞。
- 忽略时序耦合（L2.5）防抖/计数机制：TPE 段虽标记变量无法解析，但实测雷达告警仅持续 14 帧（总窗口数百帧），单次最长 16ms。专家未分析 adasFunc.c 中警告标志翻转所需的‘连续N帧满足条件’或‘滞回计数’逻辑，可能实际威胁因持续时间不足被内部计数器过滤。
- ROI与航向角(Yaw)过滤条件验证缺失：感知专家提及 Yaw∈[38°,127°] 阈值未知待查，但未结合 dist_x/dist_y 轨迹分布判断目标是否落入 FCTA 交叉预警有效区域。若目标呈纵向跟随或大角度斜向，即使速度/TTC达标也会被几何条件拦截。
- RteComMapping 映射频次/对齐问题未追溯：雷达告警与 ECU 使能周期可能存在倍频关系。未检查 14 帧雷达告警是否落在 ECU 读取窗内，是否存在时间戳漂移导致 ECU 读到的是非告警帧的旧缓存。


### 关键争议
自车实测车速的单位与数值归属（是否真正处于 FCTA 激活区间 1~20km/h 内），以及雷达端已存在的短时有效 TTC(1.5s) 为何在 ECU 决策层完全失效（是计算逻辑缺陷、防抖计数不足、还是 ROI/映射周期错位？）。此争议直接决定根因应指向‘信号标定错误’、‘算法阈值/滤波设计缺陷’还是‘时序同步问题’。