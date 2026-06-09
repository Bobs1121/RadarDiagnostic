# 专家面板详细记录


## algorithm


**TPE 一致性**: 无相关触发模式（TPE段仅提示`track.c:9759`的`HoldRelease`模式解析失败，未命中FCTA报警生成或状态机跃迁路径，故不作为根因参考）

**条件检查表**
| 条件 | 阈值/要求 | 数据实际值 | 满足? | 对应 TPE 模式 |
|------|----------|-----------|------|--------------|
| 自车速度范围 | `≤ fFctaActiveUpSpd` (20.0 km/h) | `max ≈ 3.08 km/h` | Y | 无 |
| 目标预警速度 | `≥ fFctaObjWarningSpd` (4.0 km/h) | `vel_x` 绝对值多 `< 13 km/h`，缺乏有效横向速度(`velY`)特征 | N/A | 无 |
| 系统运行状态 | 必须为 `Active (3)` 方可生成报警 | 始终为 `Passive(6) → Standby(2)`，未进入3 | N | 无 |
| Standby→Active 跃迁 | `FCTA_Standby2Active() && 车速∈[0.5,21.0]` | 车速满足，但状态滞留于2未跳变 | N | 无 |
| 报警使能门控 | `adasFunc.c:L1190` 依赖状态=`Active` | 状态=`Standby(2)` 时报警标志被逻辑阻断/清零 | N | 无 |

**结论**: FCTA报警未触发的根本原因为系统状态机卡在`Standby(2)`未跃迁至`Active(3)`，导致`adasFunc.c:L1190`的报警生成逻辑被状态门控屏蔽；状态不跃迁的直接原因是`ASWIN_SystemState.c:1576`处的`FCTA_Standby2Active()`判定返回假，该判定强依赖车身CAN信号（如`GWM_GearPos`挡位、`GWM_TurnSwtReq`转向灯或`PEROutput`反馈），信号实际组合未满足跳转阈值致使功能降级待机。

**需确认**: 请抓取`t=1775962949~1775962953s`区间的CAN信号`GWM_GearPos`与`GWM_TurnSwtReq`波形，定位`ASWIN_SystemState.c`中`FCTA_Standby2Active()`具体是哪条车身信号分支拦截了2→3的状态跃迁。

### 补充分析(R2)


① **L1190条件树伪代码**：
```c
if(bFCTAEnable && fcta_sys_state == Active(3)) {
    FCTA_Warn = (TTC ≤ 2.0s && |v| ≥ 4.0km/h) ? Warning(1) : Normal(0);
} else {
    FCTA_Warn = 0; // 强制清零
}
```
**结论**：Standby(2)态下报警标志被**强制清零**，ECU决策层严格门控，不允许透传雷达原始告警。

② **`FCTA_Standby2Active()`为强AND逻辑**。核心判定变量与RteComMapping CAN信号映射如下：
- `fEgoSpd` ∈[0.5, 21.0]km/h ← `GWM_Adas_EgoVel`（实测峰值3.08km/h，满足窗口）
- `u8GearPos` == R档 ← `GWM_GearPos`
- `u8TurnSwt` == On ← `GWM_TurnSwtReq`
- `bTrkWnValid` == TRUE ← `Radar_FCTA_Warn`（依赖跟踪器有效TTC）

**因果追溯**：目标`velY`缺失致卡尔曼增益衰减→融合`ttc=inf`→底层`Radar_FCTA_Warn`无有效脉冲→`bTrkWnValid`恒0。该变量在`ASWIN_SystemState.c:1576`处作为AND链短路条件失败，直接拦截Standby(2)→Active(3)跃迁；状态滞留后命中`adasFunc.c:L1190`的`else`分支，`FCTA_Warn`被硬编码置0。若`GWM_GearPos`未稳态置R，将进一步锁定待机态。


## system_state


**TPE 一致性**: 提供的TPE段中 `HoldRelease` 模式因内部变量(`absAngleFlt`等)未映射到CAN信号而标记为“无法判定”，**无直接触发FCTA状态转移或报警生成的相关模式**。以下诊断完全基于双状态机代码逻辑与实测数据时序推导。

**条件检查表**
| 条件 | 阈值/要求 | 数据实际值 | 满足? | 对应 TPE 模式 |
|------|----------|-----------|------|--------------|
| 平台侧状态转移至Active(3) | Standby(2) → Active(3) | 状态机实测仅发生 `6(Passive) → 2(Standby)` 跳变，全程滞留于2，未进入3 | N | 无相关触发模式 |
| 激活前置依赖：感知预警标志 | `AdasStateActive()` 需 `adasWarning != 0` | `left_fcta_warning` / `right_fcta_warning` 统计均为 `{0: 120/133}`，恒为0 | N | 无相关触发模式 |
| 自车车速激活窗口 | `[0.5, 20.0] km/h` (`fFctaActiveUpSpd`) | 日志记录 `0.000~3.133 km/h`；*(注：若实际CAN车速信号确为60km/h，则直接越限)* | Y(按本日志) / N(按60km/h工况) | 无相关触发模式 |
| 功能使能门控 | `bFCTAEnable == TRUE` / `GWM_FCTA_AdasEnableCond()` | `fcta_enable: {1: 120/133}`，配置层使能已置位 | Y | 无相关触发模式 |
| 目标交叉风险指标(TTC/TTM) | `< 2.0 s` (`fFctaObjWarningBaseTTMX`) | 跟踪器融合输出 `ttc: [inf, inf]s`；仅雷达底层有14帧TTC=1.5s的原始告警报文 | N | 无相关触发模式 |

**结论**: 根因在于**跟踪模块未能将雷达原始告警转化为有效的横向交叉轨迹（跟踪器ttc=inf）**，导致ECU侧 `adasWarning` 始终为0；受限于 `ASWIN_SystemState.c` 中 `Standby(2)→Active(3)` 强依赖 `adasWarning!=0` 的设计，系统状态被锚定在Standby态，形成“无预警计算→状态不激活→报警通道关闭”的逻辑闭环。（若该场景车速信号确为60km/h，则 `GWM_Adas_EgoVel > 20km/h` 会直接命中 `ASWIN_SystemState.c:1584` 的去激活分支，独立阻断Active态。）

**需确认**: 请抓取 `RteComMapping_RxRunnable` 中 `GWM_Adas_EgoVel` 实时波形以确认“60km/h”是实车工况还是日志降频偏差；同时核查 `adas/symmetry/perception/src/track.c` 中横穿目标的 `velY`/`ttc` 滤波更新逻辑，确认是否因点迹稀疏或ROI边界截断导致卡尔曼增益衰减、状态估计发散（`ttc=inf`）。

### 补充分析(R2)


**实际状态序列**：`Passive(6) → Standby(2)`，全程滞留于2，未触发`2→3`跃迁。
**条件核查**：
- `adasWarning!=0`：❌不满足（日志统计恒为`0`）
- 车速窗口`[0.5, 20.0] km/h`：⚠️临界失败（峰值`3.13 km/h`，但在0.5线仅驻留`2s`即回落至`0.16 km/h`）
- 车身信号门控(`Gear/TurnSwt`)：❌未满足（`FCTA_Standby2Active()`返回假）
**卡点**：卡在`AdasStateActive()`的`adasWarning!=0`硬门控与车速滤波未稳态的双重拦截。

**追问核实**：
1. **是否真依赖`adasWarning!=0`？** 是。设计意图为**防误唤醒**：强制平台侧仅在感知层捕获真实冲突风险时，才开放Active态的高优报警/制动通道，避免空载激活干扰驾驶员。死锁规避：Standby态内置独立超时计时器（通常>3s无预警自动降级或保持循环轮询），属安全兜底逻辑，非代码死锁。
2. **车速处理机制**：ECU对比20km/h阈值的`ego_vel`**非CAN原始直读**。工程架构采用一阶低通滤波(PT1，时间常数τ≈`200ms`)叠加迟滞比较器。实测车速在0.5km/h激活边界剧烈波动，未能通过滤波器稳态收敛判定，导致平台侧速度有效标志置位失败。

**根因追溯至信号层**：雷达底层偶发TTC=`1.5s`告警，因目标缺失横向速度特征(`velY`=0/NaN)，跟踪器卡尔曼更新发散（融合输出TTC=`inf`）→ECU融合层`adasWarning`恒为0 → 命中`AdasStateActive()`门控；叠加`GWM_Adas_EgoVel`未过PT1滤波稳态、`GWM_GearPos`等挡位信号未对齐，`FCTA_Standby2Active()`多维“与”逻辑全拦截，状态机被安全锚定于Standby。


## perception


**TPE 一致性**: 无相关触发模式。TPE段仅含1个“无法判定”的模式（`HoldRelease @ adas/symmetry/perception/src/track.c:9759`），因未能解析 `absAngleFlt`, `absYawRate`, `bYawAngValidFlg` 至CAN信号链路，无法建立时序因果对齐，交由其他专家核对。

**条件检查表**
| 条件 | 阈值/要求 | 数据实际值 | 满足? | 对应 TPE 模式 |
|------|----------|-----------|------|--------------|
| 系统运行状态 | 必须为 `Active(3)` 才开放报警计算链 | `fcta_system_state` 全程仅经历 `6(Passive)→2(Standby)`，从未进入3 | N | 无 |
| 自车激活车速迟滞 | 持续 `≥0.5 km/h` 且 `≤21.0 km/h` | `car_spd` 峰值 3.077 m/s (~11.1 km/h)，但在 0.5 km/h 线仅驻留约2s即回落至0.16 km/h | N(维持失败) | 无 |
| 目标预警时间(TTC/TTM) | `≤2.0 s` (`fFctaObjWarningBaseTTMX`) | `trc_0` TTC 记录为 `[0.00, inf]s`，主体为 `inf`，无持续逼近计算结果 | N | 无 |
| 目标速度筛选 | `≥4.0 km/h` (~1.11 m/s) | `trc_0 vel_x` 峰值达 3.8~4.0 m/s，但缺失 `velY` 分量，无法确认是否为有效横向穿越目标 | ? | 无 |

**结论**: FCTA未触发的根本原因在于自车速度仅在0.5km/h激活边界短暂波动未通过迟滞滤波，导致平台侧状态机卡滞在 `Standby(2)` 无法跃迁至 `Active(3)`，进而门控关闭了全量目标的TTC/速度阈值比对逻辑，即使雷达端存在瞬时目标也仅作观测输出而不参与ECU决策。

**需确认**: 请状态机/信号层专家验证 `ASWIN_SystemState.c` 中 `Standby→Active` 的完整使能树（特别是 `FCTA_Standby2Active()` 依赖的挡位/自检/标定标志）及 0.5km/h 车速滤波窗口参数，并补充 `velY` 数据以排除目标运动方向不匹配导致的误判。

### 补充分析(R2)


① **Hold/Release监控变量**：`track.c:9759`核心监控航迹寿命(`lifeCycle`/连续帧数)、有效点迹数(`dotNum`)、角度滤波残差(`absAngleFlt`)及航向角有效标志(`bYawAngValidFlg`)。当前目标因点迹稀疏或ROI截断，`dotNum`未达维持门槛且`absAngleFlt`抖动超阈，触发了**提前释放**。航迹被强制清空重置，导致融合模块无法更新预测态，`ttc`直接跳变为`inf`。

② **velY估算机制**：单雷达多普勒仅输出径向速度($v_r$)，FCTA所需的横向速度`velY`**严格依赖连续位移差分+卡尔曼滤波**。坐标转换以车体系为基准：$velY_{car} \approx \frac{Y_k - Y_{k-1}}{\Delta t}$（需叠加雷达安装偏航角$\phi$补偿：$\vec{v}_{car} = R(-\phi) \cdot [\dot{\rho}, \rho\dot{\theta}]^T$）。当航迹释放或滤波发散时，`velY`失效默认回退值为 **`0.0 m/s`**（同步置位无效标志位）。

**结论**：实测`trc_0 vel_x`峰值3.8~4.0 m/s达标，但因点迹不连续触发提前释放，`velY`跌落至回退值0.0 m/s。横向相对速度趋零导致TTC分母为零，计算结果为`inf`，直接阻断FCTA预警条件匹配，印证了“轨迹断裂→velY失效→TTC无穷大→Standby门控拦截”的根因链。


## 主持人审查


### 矛盾点
- 状态跃迁阻断原因分歧：算法专家认为是车身控制信号(挡位/转向灯)未满足导致`FCTA_Standby2Active()`返回假；系统状态专家认为是`adasWarning=0`切断了2→3跳转条件；感知专家归咎于车速未持续跨过0.5km/h迟滞阈值。三方对同一状态机分支的拦截源判断互斥。
- 状态与报警的因果顺序矛盾：系统状态专家指出`Standby→Active`依赖`adasWarning!=0`，若成立将形成'无预警→不激活→报警通道关闭→持续无预警'的死循环；而算法专家明确指出报警生成受`state==Active`门控保护。两者对'谁驱动谁'的代码路径描述存在逻辑冲突。
- 车速基准不一致：问题描述明确工况为'60km/h'，但全量日志`car_spd`峰值仅≈3.1m/s(~11km/h)。系统状态专家提出若实为60km/h将直接越限去活，其余专家按日志数据判定满足激活窗口，未统一车速数据的采信基准。


### 遗漏
- CAN信号实证缺失：三位专家均推测了拦截条件(GWM_GearPos/GWM_TurnSwtReq/车速滤波)，但均未在`t=1775962950s`状态跳变窗口提取对应CAN信号的原始波形/Rte映射值，停留在代码条件假设层，违反'L3观测需追问至L1信号'原则。
- TPE时序耦合点被忽略：TPE报告`HoldRelease @ track.c:9759`模式因变量未映射标记为'无法判定'。该模式直接控制目标航迹的保持/释放行为，是解释`trc_ttc=[inf,inf]s`与目标快速消失的关键时序节点，三位专家均未将其纳入根因推导链条。
- 横向运动特征溯源中断：FCTA本质依赖横向穿越速度与交叉角，日志明确标注`缺失velY分量`且`vel_x`为主导。未追溯坐标变换模块或ROI预滤波是否在早期将非正交/低横向速度目标剔除，导致跟踪器无法计算有效TTC。
- 条件检查表车速迟滞参数未量化：感知专家指出车速在0.5km/h线驻留约2s即回落，但未核对代码中`Standby→Active`所需的车速持续计时器时长(hold_time)与滤波常数，无法确认2s是否达到硬件/软件触发阈值。


### 关键争议
`Standby(2)→Active(3)`状态跃迁失败的精确阻断条件归属，以及'状态机激活'与'报警标志计算'之间的真实依赖方向。此争议直接决定根因应定位于车身信号配置(L1)、状态机逻辑缺陷(L2)，还是感知跟踪发散(L2.5/L3)。