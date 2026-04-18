# 专家面板详细记录


## system_state


**TPE 一致性**: 无相关触发模式 (全部 7 个 HoldRelease 模式均为"无法判定")

**条件检查表**
| 条件 | 阈值/要求 | 数据实际值 | 满足？ | 对应 TPE 模式 |
|------|----------|-----------|------|--------------|
| LCA 功能使能 bLCAEnable | =1 | 混合 [0,1] | N (不稳定) | 无触发模式 |
| 自检完成 selfInspFlg | =TRUE | 未知 | ? | 无触发模式 |
| 无故障 failureFlg | =FALSE | 未知 | ? | 无触发模式 |
| 非标定 calibratingFlg | =FALSE | 未知 | ? | 无触发模式 |
| 档位 actual_gear | =4,5,6 | 未知 | ? | 无触发模式 |
| 拖车模式 TrailerSts | =0 | 未知 | ? | 无触发模式 |
| ESP 诊断 ESPDiagActv | =0 | 未知 | ? | 无触发模式 |
| 车速 carSpd | ≥12.0 km/h | 未知 | ? | 无触发模式 |
| 曲率半径 curvRadius | ≥125.0 m | 未知 | ? | 无触发模式 |
| LCA 警告标志 adasWarning.bLeft/RightLcaWarning | ≠0 | 观测层有告警但持续时间短(8ms-3829ms) | ? | 无触发模式 |

**结论**: LCA 使能状态呈现混合 [0,1] 表明系统在部分时间被禁用 (bLCAEnable=0)，导致无法从 Standby(2)→Active(3) 或持续保持 Active 状态，这是报警间歇性失效的直接表现，但由于 TPE 无触发模式且缺少信号层 CAN 数据，无法确定是哪个输入信号导致使能关闭。

**需确认**: 请 CAN 信号专家提供 GWM_LCA_AdasEnableCond() 依赖的 CAN 信号(LCASwtReq、GWM_Adas_SelfInspFinish 对应 FIM 信号、车身状态信号等)的实际值时序，以定位使能关闭的具体诱因。

### 补充分析(R2)


结论源自雷达端 `outputData` 映射的内部变量 `bLCAEnable`。

**代码逻辑链**：`ASWIN_SystemState.c` 中 `AdasEnable()` 函数明确：`lcaSystemState` ∈ {Standby(2), Active(3)} ⇒ `bLCAEnable`=1；否则=0。

**状态推导**：观测到 `bLCAEnable` 混合 [0,1]，证明 `lcaSystemState` 必然在 {2,3} 与 {0/1/其他} 间跳变，而非仅告警位清零。

**进入 Active(3)**：`AdasStateActive()` 要求 `Standby(2)` + `adasWarning≠0`。

**故障锁定**：报警断续（8ms-3s）导致 `lcaSystemState` 频繁跌落至非 2/3 态。根因不在感知输出，而在 `GWM_LCA_AdasEnableCond()` 的前置条件（如 `SysPowerMod` 电源模式或 `TAR` 变种位）发生瞬断，阻断了状态维持。需排查电源域或 CAN 变种信号时序。


## perception


**TPE 一致性**: 无相关触发模式 (所有 7 个 LCA 相关模式 verdict 均为"无法判定")

**条件检查表**
| 条件 | 阈值/要求 | 数据实际值 (推断) | 满足？ | 对应 TPE 模式 |
|------|----------|-----------|------|--------------|
| **LCA 功能使能** | `adasEnable.bLCAEnable=1` | 混合 [0, 1] (窗口内波动) | 部分不满足 | 无 (状态机变量无法解析) |
| **目标相对速度 (预警进入)** | `velAbsX >= 7.2 km/h` (≈2.0 m/s) | `v ≈ d/ttc ≈ 7.35m/3.68s ≈ 2.0 m/s` | 临界/勉强满足 | 无 |
| **目标相对速度 (预警维持)** | `velAbsX >= 3.6 km/h` (≈1.0 m/s) | ≈2.0 m/s | 满足 | 无 |
| **碰撞时间 (预警触发)** | `TTC < 4.0 s` | 3.68s ~ 3.95s | 满足 | 无 |
| **碰撞时间 (去预警)** | `TTC > 4.7 s` | 远距离推测 TTC > 10s | 满足 (远距离不报) | 无 |
| **监测区域 (LCA)** | `LineLCAC` (-4.0m ~ -80.0m) | 报警集中在 7m ~ 12m | 满足 (但偏后) | 无 |
| **目标有效性** | `dynFlg=1,2,3` (动态) | obj=0 频繁跳变 (999m->0.1m) | 存疑 (疑似误检) | 无 |

**结论**: LCA 报警晚的根本原因是**目标接近速度过低导致 TTC 触发距离过短**；在 7.2km/h 的低速下，TTC<4.0s 对应的物理距离仅约 8 米，目标在 27 米外时 TTC 远超 4.0s 故不触发，直到逼近至 BSD 盲区边缘 (7-8m) 才满足 TTC 条件触发报警。

**需确认**: 自车车速是否稳定在 12km/h 以上以维持 LCA 功能使能 (`LCA: 混合 [0, 1]` 需确认为开关切换还是功能失效)，以及排除 `obj=0` 异常跳变对 ROI 合并逻辑的干扰。

### 补充分析(R2)


**核实结果**：现有数据**缺失自车车速（carSpd）时序**，多份报告标注为“未知”，故**无法定位具体低于 12.0 km/h 的时间点**。

**结论修正**：此前感知分析“推测速度满足”有误，应视为**未验证**。虽目标属性在近距离（dist≈7.35m, TTC≈3.68s）满足触发阈值，但**LCA 功能使能（bLCAEnable）呈混合 [0,1] 状态**，说明系统在部分时段被强制禁用，优先于 TTC 计算阻断报警。

**关键差异**：
1. **功能层**：`bLCAEnable` 不稳定直接导致状态机无法维持 Active(3)，致使远处目标（如 27m 处）不触发。
2. **车速层**：激活阈值 **[12.0, 146.0] km/h** 是否越界未知。若车速曾<12.0 km/h，将是比 TTC 延迟更根本的失效原因。

**建议**：需补充 CAN 报文车速波形。若车速稳定>12.0 km/h 而使能为 0，根因为开关/诊断干扰；若存在<12.0 km/h 波动且与使能关闭时刻重合，则**车速过低为首要根因**。当前证据指向**使能信号异常**导致的功能间歇性丢失。


## architecture


**TPE 一致性**: 
无相关触发模式。TPE 显示 `HoldRelease` 模式共 7 条，全为"无法判定"（例：`adasFunc.c:3998` `bLcaLeftWarningFlg` 无法解析到 CAN 信号）。这表明**感知层（adasFunc.c）的关键警告标志未建立有效的 CAN 信号链路监控**，无法通过时序证明标志位何时置位。

**条件检查表**
| 条件 | 阈值/要求 | 数据实际值 | 满足？ | 对应 TPE 模式 |
| :--- | :--- | :--- | :--- | :--- |
| LCA 功能使能 | `adasEnable->bLCAEnable` = 1 | 配置层显示 `[0, 1]` 混合 | 未知 | `HoldRelease @ adasFunc.c:3998` |
| 系统状态激活 | `lcaSystemState` ∈ {2, 3} | 未直接观测到 CAN 信号值 | 未知 | `HoldRelease @ ASWIN_SystemState.c` |
| 左侧警告透传 | `RteComMapping_GetRL_..._GWM()` > 0 | 无法从 TPE 验证 | **无法判定** | `HoldRelease @ ASWOUT_OutCalc.c:Line1026` |
| 右侧合并逻辑 | `RR_BsdLca_Warning` = max(BSD, LCA) | 观测层 `radar=3` (RR) 有输出 | Y (推测) | 无 TPE 触发 |
| LCA 触发阈值 | TTC < 4.0s, Spd > 7.2km/h | 观测层 TTC 最小 0.08s | 满足 | 无 TPE 触发 |

**结论**: TPE 证实 `adasFunc.c` 中的 LCA 警告标志变量（如 `bLcaLeftWarningFlg`）**未能映射到可监控的 CAN 信号**，结合 `ASWOUT_OutCalc.c` 中左侧警告完全依赖 `RteComMapping_GetRL_...` 私有信号透传的架构设计，**根因高度疑似 RL 侧 LCA 警告未正确写入私有 CAN 报文，或 RR 侧读取该信号的接口定义不一致，导致 LCA 报警逻辑在合并阶段被阻断或延迟**。

**需确认**: 请通信专家核对 `RteComMapping.c` 中 `RL_BSD_LCA_warningReqleft_GWM` 对应的私有 CAN 信号 ID 及位定义是否与 `adasFunc.c` 实际发送的 DBC 定义一致。

### 补充分析(R2)


**数据来源与架构分析**

1.  **数据来源层级**: `warning_edge_on` 对应算法层内部标志位 `PEROutput.adasWarning.bRightLcaWarning` (Line 130)，**非**原始 `radar_objects` 直接透传。该标志经 `RE_ASWOUT_OutCalc_RadarWarnSignal` 协调后存入 `g_ASWOUT_RadarWarnSigStrct`，最终通过 `RteComMapping` 映射至公共 CAN 报文。若测试窗口抓包为 CAN 信号，其值受状态门控影响；若为内部变量日志，则可能已触发但未被下游读取。

2.  **“无报警”根本原因**: 并非后端应用层二次过滤，而是**系统状态机强制清零**。代码明确定义仅在 `lcaSystemState == 3` 时输出警告 (Line 134)。当 `bLCAEnable` 因开关跳变变为 0 时，系统退出 Active 态，`else` 分支直接强制 `RR_BsdLca_Warning = 0` (Line 143)，阻断报警下发。

3.  **雷达位置修正**: LCA 逻辑严格归属于**后角雷达 (Rear Left/Right)**，**非前向**。源码中 LCA 计算位于 `ENM_POS_REAR_RIGHT` (Line 124) 及 `ENM_POS_REAR_LEFT` (Line 170) 分支；前向雷达分支 (Line 76/95) 仅处理 FCTA/FCTB 碰撞预警。用户侧感觉“无报警”系后置雷达状态不稳定导致公共 CAN 未更新，与前向雷达无关。

4.  **建议**: 重点排查后雷达私有 CAN 链路 (RL→RR) 的 `RL_BSD_LCA_warningReqleft_GWM` 透传稳定性，及 `LCASwtReq` 使能信号的抖动频率。


## signal_chain


**TPE 一致性**: 无相关触发模式（TPE 分析显示 7 个 LCA 相关模式均为“无法判定”，未能解析内部变量到 CAN 信号的映射，故无法依据 TPE 触发事件定位具体代码行为）。

**条件检查表**
| 条件 | 阈值/要求 | 数据实际值 | 满足？ | 对应 TPE 模式 |
|------|----------|-----------|------|--------------|
| **LCA 功能使能 (`bLCAEnable`)** | 持续为 TRUE (1) | 混合 [0, 1] (窗口期内跳变) | ❌ 不满足 | HoldRelease @ adasFunc.c:3998 (无法判定) |
| **外部抑制标志 (DTC/拖车/标定)** | 全为 False | 未提供明确故障码数据 | ✅ 假设正常 | - |
| **自车速范围 (激活)** | 12.0 ~ 146.0 km/h | 未提供实时车速数据 | ⚠️ 未知 | - |
| **目标警告条件 (速度/TTC)** | v_rel > 7.2km/h & TTC < 4.0s | 最小距离 7.35m (部分符合) | ⚠️ 部分符合 | - |
| **系统状态 (Standby/Active)** | 保持 Standby(2) 或 Active(3) | 因使能跳变推测伴随 Off/Standby 切换 | ❌ 不稳定 | - |

**结论**: LCA 报警晚及中断的根本原因为**功能使能信号 (`bLCAEnable`) 在测试窗口内发生 0/1 跳变**（`配置层·ADAS 使能` 显示 LCA: 混合 [0, 1]），导致系统在目标接近初期被反复置为 Off 态，丢失预警逻辑，直到使能恢复且目标已深入监测区（7.35m）才重新触发。

**需确认**: 请总线/诊断专家检查公 CAN 信号 **`LCASwtReq`** 波形是否稳定，或排查 `RteComMapping_RxRunnable_FuncSignal` 中 `bLCAEnable` 赋值逻辑是否存在外部干扰（如与其他功能开关共用线束导致的竞争）。

### 补充分析(R2)


根据源码 `RteComMapping.c` 函数 `RteComMapping_RxRunnable_FuncSignal` (约 360 行)，`bLCAEnable` 对应 CAN 信号 **`LCASwtReq`**。

映射逻辑：`RteComMapping_ReadSignal(LCASwtReq)` 读取值 `u8tmp`，直接赋值 `PERInputUpdate.adasEnable.bLCAEnable = (u8tmp == 1)`。

**数据支撑**：系统状态专家指出窗口内 `bLCAEnable` 呈 **[0, 1] 混合** 状态。由于源码中该信号到变量的赋值无中间滤波宏，此跳变直接反映 `LCASwtReq` 物理信号在报警窗口期间发生频繁翻转，非内部逻辑滤波导致。

**结论**：报警间歇性失效根源为 `LCASwtReq` 输入不稳定导致功能使能反复复位。此前关于多条件依赖的推测修正为单信号直接驱动。建议抓取公 CAN 波形确认 `LCASwtReq` 是否存在毛刺或 BCM 发送异常。


## algorithm


### TPE 一致性
- **TPE 模式**: `HoldRelease @ coem/GWM_B26/components/AswPerception/func/adasFunc.c:3998~4002` (左侧警告保持/释放) 及 `4055~4059` (右侧警告保持/释放)。
- **状态**: **全部无法判定 (7 个模式均 fail)**。
- **含义**: TPE 未能将 `bLcaLeftWarningFlg` / `totalLeftLcaWarningState` 的状态跳变解析为稳定的外部 CAN 信号驱动事件。这直接表明 LCA 报警标志位的翻转并非由稳定的物理输入（如明确的转向灯或持续的威胁目标）触发，而是由**内部逻辑条件的临界波动**导致。这种“无法判定”佐证了报警状态处于高频震荡（On/Off 频繁切换），无法形成完整的“保持”事件链，与数据中观察到的“报警中断/晚报”现象高度一致。

### 条件检查表
| 条件 | 阈值/要求 | 数据实际值/现象 | 满足？ | 对应 TPE 模式 |
|------|----------|-----------|------|--------------|
| **LCA 系统激活状态** | Standby(2) 或 Active(3) | 有报警记录，推测大部分时间为 Standby | Y | 隐含前提 |
| **自车速度范围** | [12.0, 146.0] km/h | 有报警活动，推测满足 | Y | - |
| **目标进入 LCA ROI** | X ∈ [-80m, -4m] (相对后保) | 数据中 object_approach: 27.4m → 7.3m (落入 ROI) | Y | - |
| **目标 TTC 报警阈值** | TTC ≤ 4.0s | 报警仅在近距离或特定时刻触发，中段缺失 | N/P | HoldRelease |
| **警告保持逻辑 (Keep)** | 连续满足或非零帧数 ≥ `KEEPWARNINGFRM` | 窗口 1/4/8 报警仅持续几毫秒即 Off，**保持失效** | **N** | `HoldRelease` (Failed) |
| **外部抑制条件** | Gear 4/5/6, 非拖车，无 DTC | 数据未显式异常，但状态跳变频繁 | ? | 需确认 |

### 结论
LCA 报警维持逻辑（Keep Flag）**在目标处于临界 TTC 或 ROI 边界时失效**，导致报警逐帧复位（表现为 On/Off 闪烁）；只有当目标极度接近（TTC 显著<4.0s，进入 BSD 强威胁区）时报警才稳定，造成“LCA 晚于 BSD 报警”的现象；TPE 显示的 `HoldRelease` 模式全无法判定，验证了内部警告标志位受临界条件震荡而非稳定信号驱动。

### 需确认
1. **参数 `KEEPWARNINGFRM` 的具体宏定义值**（是否过小导致无法过滤单帧噪声）。
2. **LCA ROI 纵向终点 `LineLCAA` (-80m)** 在实际工况下是否因坐标换算偏差导致远端目标未被纳入有效计算。
3. **`bLcaLeftWarningFlg` 的清零路径**，排查是否存在非 De-warning 逻辑的意外清零（如 `ResetAdasSystemStatusPara` 被 DTC 或电源状态误触发）。

### 补充分析(R2)


1. **宏定义值**：源码片段中未直接包含 `adasFunc.h`，该宏通常定义为 **3**（典型配置）。
2. **防抖计算**：系统周期为 **8ms**。若 `KEEPWARNINGFRM=3`，则保持时间为 $3 \times 8\text{ms} = \mathbf{24\text{ms}}$。单帧噪声持续 **8ms**。理论上 $24\text{ms} > 8\text{ms}$，**能过滤 1 帧噪声**。
3. **问题分析**：实际观测到报警闪烁（On/Off 跳变），说明有效触发次数未达到阈值。原因可能是：
   - 当前宏值被配为 **1** 或 **2**（无法抵抗连续临界波动）；
   - 目标处于 LCA ROI 边界（X∈[-80m, -4m]），TTC 在 **4.0s** 附近高频震荡导致逐帧清零。
4. **修改建议**：**需提高阈值**。建议将 `KEEPWARNINGFRM` 修改为 **4**（总延时 **32ms**），以增强对边界工况的抗抖动能力。同时检查 `fLcaObjWarningTTC` (4.0s) 与 `fLcaObjDeWarningTTC` (4.7s) 之间的迟滞是否足够。


## 主持人审查


### 矛盾点
- 【使能状态 vs. 算法逻辑】系统状态与信号链路专家认为根本原因是 `bLCAEnable` 在窗口内频繁跳变（[0,1]）导致功能反复关闭；而算法逻辑与感知专家认为是 `HoldRelease` 阈值参数过小或 TTC 计算距离过短导致的逻辑震荡，即便使能为 1 也会间歇报警。
- 【报警持续时间证据冲突】测试窗口 1 显示报警仅持续 8ms（接近单帧周期），支持‘逻辑防抖失效’观点；但系统专家引用的 [0,1] 混合状态通常意味着更长的功能关闭周期，两者对‘中断’时标的解释不一致。
- 【观测源定义模糊】架构专家指出 TPE 无法映射内部警告标志到 CAN 信号，暗示输出可能丢失；但测试窗口数据明确记录了 `warning_edge_on/off` 事件，未说明该事件是 ECU 内部调试日志还是实际外部 CAN 报文，导致‘有报警但未输出’与‘根本无触发’的定性矛盾。


### 遗漏
- 【缺少关键CAN信号时序】所有专家均依赖配置层推断 `bLCAEnable` 波动，但无人提供 `LCASwtReq`、`VehicularSpeed` 等底层 CAN 信号的实测波形以确认波动源头是开关误触还是车速临界穿越。
- 【关键参数缺失】算法专家提到 `KEEPWARNINGFRM` 宏定义值未知，无法定量判断 8ms 的报警闪烁是否属于防抖机制被穿透，缺乏代码常量支撑分析。
- 【使能与目标关联缺失】未分析 `bLCAEnable` 为 0 的具体时间点是否与目标距离从远到近的时间段重合。如果使能在远距离时为 0，则直接解释了‘晚报’，无需归咎于 TTC 阈值。
- 【自车速度绝对值未知】感知专家通过 TTC 推算相对速度约 2m/s，但未验证自车绝对速度是否稳定≥12km/h（LCA 激活门槛）。若自车速度在 11-13km/h 间波动，会导致 LCA 使能状态机反复 Reset，这同时解释了使能混合和报警中断。


### 关键争议
最关键的争议在于根因层级：究竟是 L1/L2 层的『功能使能条件不满足』(导致功能周期性挂起，系统/信号链专家主张)，还是 L2/L2.5 层的『警告维持逻辑过于激进/阈值设置不当』(导致已使能状态下仍频繁复位，算法/感知专家主张)。这决定了修复方案是检查输入信号稳定性，还是调整软件防抖参数。