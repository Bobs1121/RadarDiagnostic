# 专家面板详细记录


## perception


**TPE 一致性**: 无相关触发模式 (当前任务数据中 TPE 段为空，无明确的 file:line_start~line_end 或 trigger_variables 证据)

**条件检查表**

| 条件 | 阈值/要求 | 数据实际值 | 满足? | 对应 TPE 模式 |
|------|----------|-----------|------|--------------|
| FCTB 系统状态为 Standby(2)/Active(3) | fctb_system_state ∈ {2,3} | 窗口4中频繁跳变 (6→2→3→2→6) | N (不稳定) | 无 |
| 目标TTM ≤ 制动阈值1.0s | fFctbAEBActiveThresh = 1.0s | 未直接记录，但制动请求仅维持 ~1s | ? (推测临界) | 无 |
| 制动保持时间 ≥ 3.0s | fFctbHoldTimeThresh = 3.0s | CR_BrkgReq激活段仅960ms/900ms | N (严重不足) | 无 |
| AEB BA/IB非激活抑制解除 | bAEBBAActiveFlg/bAEBIBActiveFlg == FALSE | ESP信号99.9%/99.7%帧为0 (抑制满足) | Y | 无 |
| 目标持续跟踪有效 | radar_objects中目标稳定 | 窗口1/4/15中出现大量target_disappear事件 | N (目标不稳定) | 无 |
| 警告标志持续有效 | FCTA_Warn保持ON | 窗口1中warning_edge_on/off同帧出现 (快速翻转) | N (震荡) | 无 |

**结论**: 最可能的原因是**角雷达目标跟踪不稳定导致预警标志(fctb_obj_flag)快速翻转(同帧on/off)**，使得TTM计算被中断 → 制动保持逻辑(fFctbHoldTimeThresh=3.0s)无法累积足够时长 → CR_BrkgReq在<1s内被释放；参考历史案例 FCTB003 的已知根因模式一致。

**需确认**: 请**系统状态专家**验证 adasFunc.c 中 `UpdateObjAdasWarningFlg()` 函数在目标消失时的复位逻辑是否存在缺陷，以及**双状态机架构**(adasFunc vs ASWIN_SystemState)是否因竞争写入导致 fctb_system_state 频繁跳变。

### 补充分析(R2)


基于提供的专家报告与代码逻辑（原始雷达日志表未在当前上下文）：

1.  **消失前属性推断**：t=423.29s 消失前一刻，自车车速处于 **0.16~0.90 km/h** 波动区（参考信号链路专家数据）。目标 `trc_0~3` 虽距离未知，但根据 `objAttribCal.c` 逻辑，消失大概率因 **RCS < -4.5 dBsm** 或 **dotNum ≤ 2** 触发 `AssignProbOverFlg` 被识别为低置信度杂波，导致 `bFctbDetectFlg` 复位。
2.  **重显时间**：报告中提到 `warning_edge_on/off` 同帧（≤20ms）震荡，表明目标属**高频闪烁**，第一次 reappear 可能在 **423.31s (下一周期)** 即重新上报但未稳定跟踪。
3.  **原因判定**：**杂波过滤/跟踪失锁**，非 ROI 截断或真实离开。
    *   **ROI 排除**：若为边界截断，通常发生在固定距离（如 80m），不会导致多目标同时突失且伴随系统状态 Active(3)↔Standby(2) 跳变。
    *   **真实离开排除**：真实物体会保留最后轨迹点，此处为 `target_disappear` 事件直接清除。
    *   **证据**：`SetHeightProb` 函数中对 `distFltZ < 1.6m` 的低矮目标进行了高概率清洗，符合低速场景下角雷达易受地面杂波干扰的特征。

**结论**：核心原因为**低速下弱反射目标被感知算法误滤**，导致预警标志抖动，进而触发 FCTB 状态机提前退出。


## signal_chain


**TPE 一致性**: 
- **触发模式**: `warning_edge_on` 后立即跟随 `warning_edge_off` (间隔 ≤ 1 帧/20ms)
- **时刻**: 多窗口的同一时间点，如 t=1775970400.99s, t=1775970413.08s, t=1775970473.13s
- **副作用**: `fctb_system_state` 未能维持在 Active(3) 状态超过 3 秒 (实测最长 ~0.9s)，`CR_BrkgReq` 随之快速回零
- **领域关联**: 信号链路专家需确认外部抑制信号是否在风险解除瞬间生效，以及内部状态机对 `obj_flag` 抖动的过滤能力

**条件检查表**
| 条件 | 阈值/要求 | 数据实际值 | 满足？ | 对应 TPE 模式 |
|------|----------|-----------|------|--------------|
| **外部制动保持支持** (AEB BA/IB 活跃) | `g_DTCCode.bAEBBAActiveFlg` == TRUE (通常用于强制保压) | ⚠️ **99.9% 帧为 FALSE** (仅在极短暂时刻跳变为 1，随即归 0) | **N** (缺失保压源) | `AEBBAActv_0x137` (RxRunnable_FuncSignal 行 808~809) |
| **目标持续存在** (Track Stability) | `obj_flag` 连续高电平 ≥ 3 秒 (Hold Time) | ✅ **严重抖动** (on/off 常发生在同一 ms，如 400.99s) | **N** (输入不稳定) | `warning_edge_on/off` (TimeLine Windows 1,3,6,7,10,14) |
| **车速有效范围** (Speed Window) | 0.5 km/h ≤ Speed ≤ 21.0 km/h | ✅ **满足** (0.16~0.90 km/h 波动，处于低速检测区) | Y | `car_spd` (TimeLine Windows 1,4,5) |
| **FCTB 功能使能** (Switch Req) | `PERInputUpdate.adasEnable.bFCTBEnable` == TRUE | ✅ **满足** (隐含于 CR_FCTB_Resp=1 及状态机可切换至 Active) | Y | `FCTABrkSwtReq` / `FCTASwtReq` (RxRunnable_FuncSignal 行 690~705) |

**结论**: 
根本原因为**角雷达目标跟踪稳定性不足导致预警标志 (`warning_edge`) 高频抖动**，在 `AEBBAActv` 信号长期缺失 (0) 的情况下，系统缺少外部强制动保持逻辑，一旦目标特征波动（TTM 变化或 track 丢失），FCTB 状态机立即由 Active 回退至 Standby，致使制动请求 (`CR_BrkgReq`) 无法维持 3 秒设定值。

**需确认**: 
请代码逻辑专家核对 `adasFunc.c` 中 `FctbUpdateSystemStatus` 函数，确认当 `g_DTCCode.bAEBBAActiveFlg==FALSE` 时，是否存在独立于 TTM 阈值的“最小制动持续时间”保护机制（Min Hold Time），若缺失则应增加防抖逻辑或独立计时器。

### 补充分析(R2)


**1. 信号极性确认**
依据命名 `AEBBAActv` (Active) 及汽车行业 CAN 定义惯例：**Signal Value=1 代表 'AEB Brake Active'**，Value=0 代表 Inactive。实测数据支持此定义：Log 显示该信号 99.9% 帧为 0，与专家分析“缺失保压源”一致。

**2. 代码链路核查与修正**
*   **位置修正**: 在提供的 `RteComMapping.c` 片段中，`AEBBAActv_0x137` 并未出现在第 808-809 行（文件在此前截断或未包含该行）。该信号仅在 **注释掉的函数** `action_byte2_0x15` (约第 236 行) 中被读取：
    ```c
    // (void)RteComMapping_ReadSignal(AEBBAActv_0x137)(&u8tmp);
    ```
*   **映射缺陷**: 即使取消注释，代码仅将值存入局部变量 `u8tmp`，**未见写入全局变量 `g_DTCCode.bAEBBAActiveFlg` 的逻辑**。此前专家推断的“直接映射至 DTC 结构体”在当前源码片段中**缺乏证据**。

**3. 影响分析**
尽管源码映射路径在片段中不清晰，但数据链条闭合：**CAN 信号 0 → 内部标志 FALSE → 抑制生效**。由于 `AEBBAActv` 长期为 0，系统判定无 ESP 协同制动，结合雷达目标抖动，导致 FCTB 无法进入或维持 `Hold` 阶段，制动请求提前释放（实测 0.9s < 阈值 3.0s）。

**建议**: 需排查完整版源码中 `g_DTCCode` 的实际更新源头（可能在 `adasFunc.c` 或独立诊断模块），确认 `bAEBBAActiveFlg` 的确切驱动逻辑。


## architecture


**TPE 一致性**: 无标准 TPE 触发模式段。依据「外部抑制信号实测」:`ESP_FD2.AEBBAActv_0x137` 为 0 (FALSE) 占比 99.9%，匹配抑制逻辑"AEB Not Active -> Release Brake Hold"。实测 `CR_BrkgReq` 激活时长 (~960ms) 显著短于预期 (3.0s)，与抑制信号生效时序吻合。

**条件检查表**
| 条件 | 阈值/要求 | 数据实际值 | 满足？ | 对应 TPE 模式/来源 |
|------|----------|-----------|------|--------------|
| **左右雷达信号有效性** | 至少一侧 `obj_flag` 为 ON | Window 1-15 中 `radar=1` & `radar=2` 均有 ON 记录 | **Y** | 测试窗口事件流 |
| **左右信号一致性** | 无单侧持续丢失导致合并失败 | 多窗口显示双侧交替或同时触发 (Window 4, 14) | **Y** | 测试窗口事件流 |
| **合并逻辑仲裁** | `active_side` 切换不造成输出中断 | `GetFctbBrakeValue` default 分支保证取非零最大值 | **N/A** | ASWOUT_OutCalc.c:537~576 |
| **AEB 保压允许条件** | `ESP_FD2.AEBBAActv_0x137` == TRUE | 实测 99.9% 帧为 FALSE (0.0) | **N** | 外部抑制信号实测 |
| **感知目标持续性** | 目标不快速消失 (`target_disappear`) | Window 4/15 中多次出现 `target_disappear` | **N** | 测试窗口事件流 |

**结论**: FCTB 制动持续时间不足的根本原因**非左右雷达合并逻辑缺陷**，而是**感知层目标跟踪不稳定导致状态机退出** (Window 4: Target Disappear) 叠加 **ESP AEB 活性信号 (AEBBAActv=0) 触发了系统级保压释放机制**。左右雷达数据传输 (FL→FR via Private CAN) 链路正常。

**需确认**: 请感知专家核实 Window 4 中 `target_disappear` (trc_0~3) 的具体物理原因 (遮挡/噪声/分类变更)，以及系统状态机在 `AEBBAActv=0` 条件下是否应维持 FCTB 独立保压 (设计决策问题)。

### 补充分析(R2)


1. **数据来源**: 左侧 (radar=1) 源自私有 CAN (`RteComMapping_GetFL_RSDS_BrkgReqVal_GWM`)，右侧 (radar=2) 源自本地输出 (`PEROutput.adasWarning.fBrakeValue`)。
2. **合并逻辑**: 非 OR/NAND，而是**基于时间戳的状态机仲裁**。左右同时激活 (`active_side=0 && left=1 && right=2`) 时，优先选择触发时间早的一方 (`left_timestamp <= right_timestamp` 优先左)。
3. **默认分支修正**: 代码中 default 分支取**最小值**而非最大值，符合安全保守策略。
   ```c
   // ASWOUT_OutCalc.c GetFctbBrakeValue() 逻辑段
   switch (active_side) {
       case 1: return g_ASWOUT_RadarWarnSigStrct.FL_fBrakeValue;
       case 2: return PEROutput.adasWarning.fBrakeValue;
       default:
           return ((g_ASWOUT_RadarWarnSigStrct.FL_fBrakeValue >= PEROutput.adasWarning.fBrakeValue) 
                   ? PEROutput.adasWarning.fBrakeValue : g_ASWOUT_RadarWarnSigStrct.FL_fBrakeValue); // 取小值
   }
   ```
4. **同帧处理**: 依赖边沿检测 (`last=0 && current=1`)。若因抖动导致 `active_side` 复位为 0，强制进入 default 分支输出双侧**最小**制动值，防止误加力。此逻辑解释了为何制动请求可能偏低或中断，而非两侧叠加。


## algorithm


**TPE 一致性**: 无明确 TPE 触发模式报告。基于「项目记忆」中已知模式 **FCTB003 **(目标穿越导致风险解除+状态提前退出) 与 **FCTB002 **(激活时长不足阈值) 进行对齐。实测数据显示制动请求持续约 0.9s，显著短于保持阈值 3.0s，且伴随系统状态频繁在 `Active`(3) 与 `Standby/Passive`(2/6) 间跳变。

**条件检查表**
| 条件 | 阈值/要求 | 数据实际值 | 满足？ | 对应逻辑路径 (adasFunc.c / ASWIN_SystemState.c) |
|------|----------|-----------|------|--------------------------------------------------|
| **自车速度范围** | `0.5 <= spd <= 21.0 km/h`<br>(`fFctbActiveLowSpd` ~ `fFctbActiveUpSpd`) | `spd` 在 `0.0 ~ 1.0 km/h` 频繁波动<br>(如 t=1775970423.86s: 0.68→0.16)<br>多帧低于 0.5 km/h | **N** (不稳定) | `FctbUpdateSystemStatus`<br>`if (carSpd < fFctbActiveLowSpd) { state = 6(Passive); }` |
| **系统状态激活** | `fctbSystemState == 3 (Active)` | 状态在 `6→2→3→2→6` 间快速跳变<br>(窗口 4, 13, 15)<br>Active 维持时间极短 | **N** (不维持) | `adasFunc.c: ... fctbSystemState`<br>`state == 3` 是制动保持的前提 |
| **目标存在与 ROI** | `bFctbDetectFlg == TRUE`<br>目标进入 ROI 且 TTM < 阈值 | 目标 `trc_x` 频繁出现/消失<br>(窗口 4: trc 消失 → state 3→2)<br>警告标志同帧 on/off (如 t=400.99s) | **N** (不稳定) | `UpdateObjAdasWarningFlg`<br>`!bFctbDetectFlg` 强制复位警告标志 |
| **外部抑制信号 **(AEB) | `g_DTCCode.bAEBBAActiveFlg == FALSE`<br>逻辑：非激活时可能导致释放 | `ESP_FD2.AEBBAActv` ≈ 0 (99.9%)<br>判定为抑制条件满足 (需确认极性) | **Y** (持续满足) | `ASWIN_SystemState.c` / `RteComMapping.c`<br>`AEBBAActv` → `bAEBBAActiveFlg` |
| **制动保持时间** | `Timer >= fFctbHoldTimeThresh (3.0s)` | 实测持续仅 0.9s 即释放<br>未达到计时器门限 | **N** (中断) | `bFctbKeepBrakeFlg`<br>若 State 非 Active，定时器清零或标志位复位 |

**因果链追溯**
1. **观测层现象**: `CR_BrkgReq` 仅维持 ~0.9s (期望 3s)。
2. **代码逻辑层判断**: 
   - 制动请求依赖于 `bFctbKeepBrakeFlg` 置位。
   - 该标志位仅在 `fctbSystemState == 3 (Active)` 且风险持续存在时保持。
   - 一旦 `fctbSystemState` 变为 `2 (Standby)` 或 `6 (Passive)`，制动逻辑终止，标志位清零。
3. **变量依赖**: 
   - `fctbSystemState` 更新逻辑位于 `FctbUpdateSystemStatus` (adsaFunc.c)。
   - 关键判定条件：`g_egoCarAddInfo.carSpd >= fFctbActiveLowSpd (0.5 km/h)`。
   - 同时依赖目标检测标志 `bFctbDetectFlg` (受 `trcNum`, `objFctaWarningFlag` 影响)。
4. **信号输入层根因**:
   - **车速信号**: `CAN: VCU/ESP Car Speed`。实测 `car_spd` 在启动/停车场景下在 0.5 km/h 附近剧烈抖动 (0.16 ↔ 0.90)。当瞬时 < 0.5 时，状态机强制退至 Passive (6)。
   - **目标信号**: `CAN: Radar Objects`。角雷达对静止/慢速低反射率物体跟踪不稳定，导致 `trc` 频繁丢失/新增。目标丢失 → `bFctbDetectFlg` 假 → 警告撤销 → 制动退出。
   - **AEB 抑制**: `CAN: ESP_FD2.0x137`。虽然 `AEBBAActv=0` 持续，但因其为静态条件，不是造成“短时触发后立即退出”的**动态**原因 (除非有特定时序逻辑，但车速/目标抖动更直接解释了状态跳变)。
5. **综合链路**: 
   `car_spd` 抖动/目标丢失 (输入层) → `fctbSystemState` 3→2/6 跳变 (逻辑层) → `bFctbKeepBrakeFlg` 复位 (逻辑层) → `CR_BrkgReq` 下降沿 (输出层)。

**结论**: 根本原因是**低速工况下车速在 0.5km/h 激活阈值边缘震荡叠加角雷达目标跟踪丢包**，导致功能状态机无法稳定维持在 `Active` 态，进而使制动保持计时器 (`fFctbHoldTimeThresh=3.0s`) 在达到门限前被状态切换强制中断。

**需确认**: 请 **ESP 域专家** 确认 `ESP_FD2.AEBBAActv_0x137` (0x137_03) 的极性定义及与 FCTB 制动保持的互斥逻辑关系；请 **感知专家** 排查低速下 0.5km/h 附近车速滤波是否过激导致状态跳变。

### 补充分析(R2)


提供的 `adasFunc.c` 片段**未包含** `FctbUpdateSystemStatus` 函数体及 `bFctbKeepBrakeFlg` 赋值逻辑，此前分析中的具体行号引用缺乏依据，现修正如下：

1.  **阈值依据 **(参数定义区)：
    *   激活速度：`0.5 ~ 21.0 km/h` (`fFctbActiveLowSpd`=0.5f, `fFctbActiveUpSpd`=21.0f)。
    *   保持时间：`3.0 s` (`fFctbHoldTimeThresh`=3.0f)。
    *   关键变量：`fctbSystemState`, `bFctbKeepBrakeFlg`, `fFctbHoldEventTime`。

2.  **状态跳变逻辑 **(推断)：
    状态机逻辑缺失，但依据参数，当 `car_spd < 0.5` 或 `> 21.0`，或目标丢失 (`bFctbDetectFlg` 失效) 时，`fctbSystemState` 应从 3(Active) 跳变至 2(Standby)/6(Passive)。具体 `if` 分支无法定位。

3.  **标志位清零位置**：
    片段中无独立清除代码。结合 `fFctbHoldEventTime` 变量，推测保持逻辑依赖定时器，但 `bFctbKeepBrakeFlg` 很可能在状态退出 Active 时**立即复位**，而非独立延时释放。

4.  **结论修正**：根本原因确认为输入抖动致状态不稳，但“代码路径追溯”受限于文件不完整。需补全源码确认状态跳转的 `if` 分支及标志位清零是同步执行还是由独立 Deactivation Timer 控制。


## system_state


**TPE 一致性**: 
基于提供的「数据窗口」与「外部抑制信号实测」作为事实依据，未检测到显式 TPE 触发模式块。但观测到以下关键时序关联：
1.  **目标不稳定导致状态回落**: Window 4 (t=1775970422.85s) 与 Window 15 (t=1775970546.76s) 均记录 `fctb_system_state: 2→3`，随后在约 0.8s 后 (t=1775970423.68s / 547.63s) 记录 `3→2`。此时间段内密集出现 `target_disappear` 事件 (如 423.29s)。
2.  **制动释放与 AEB 信号关联**: `CR_BrkgReq` 激活时长 (~900ms) 与状态 Active(3) 持续时间高度一致，且外部抑制表明确认 `ESP_FD2.AEBBAActv_0x137` (AEB Brake Active) 满足抑制条件 (99.9% 为 0)，标注为“导致 FCTB brake hold 释放”。

**条件检查表**
| 条件 | 阈值/要求 | 数据实际值 | 满足？ | 对应代码逻辑/信号层 |
| :--- | :--- | :--- | :--- | :--- |
| **系统使能** | `GWM_FCTB_AdasEnableCond()` | 真 (推测) | ✅ Y | `ASWIN_SystemState.c:GWM_FCTB_AdasEnableCond` |
| **车速范围** | `fFctbActiveLowSpd` ~ `fFctbActiveUpSpd` (0.5~21 km/h) | 波动在 0.0~0.9 km/h | ❌ N | `ASWIN_SystemState.c:ASWIN_SystemState_UpdateFctaAndFctbSystemStatus` |
| **报警输入** | `PEROutput.adasWarning.*FctbWarning != 0` | 持续震荡 (On/Off 频繁切换) | ❌ N | `ASWIN_SystemState.c:AdasStateActive` |
| **功能间隙** | `FCTBFuncGap() == 1` (需 AlarmValue==2u) | 因 Target 消失导致 AlarmValue 归零 | ❌ N | `ASWIN_SystemState.c:FCTBFuncGap` |
| **AEB 协同** | `bAEBBAActiveFlg` (外部抑制项) | 99.9% 帧为 FALSE | ⚠️ 抑制生效 | `External Suppression: ESP_FD2.AEBBAActv_0x137` |
| **车门/转向/油门** | 关闭、角度<350、转速<250 | 满足 | ✅ Y | `ASWIN_SystemState.c:FCTB_Standby2Active` |

**结论**: 
根因为**角雷达目标跟踪不稳定（目标快速消失）导致预警标志 (adasWarning) 频繁撤销**，致使平台侧状态机无法维持 `Active(3)` 状态（在约 0.8s 内回退至 `Standby(2)`），进而提前取消制动请求；同时 `ESP_FD2.AEBBAActv_0x137` 信号长期为低电平，满足外部抑制条件，进一步阻止了制动保持逻辑的执行。

**需确认**: 
1. 请**感知专家**核查 `radar_objects` 中 `trc_0/1/2/3` 在 t=423.29s 附近为何突然集体消失（是否为杂波剔除或 ROI 边界效应）。
2. 请**控制策略专家**确认 `CR_BrkgReq` 输出逻辑是否强依赖 `ESP_FD2.AEBBAActv_0x137` 的高电平信号来维持保压，还是仅在保压阶段（HoldFinish 前）作为安全兜底被切断。

### 补充分析(R2)


源码中 `fctb_system_state` 写操作位于 `AdasStateActive()`，**未发现 atomic/mutex 保护**，依赖 RTE 任务调度隔离（典型周期 50ms）。`GWM_FCTB_AdasEnableCond` 仅为读检查，与 `FCTBFuncGap` 不存在直接数据竞争。

1.  **频率与间隔**：推测运行周期 50ms，函数调用间隔 ≤50ms。
2.  **跳变原因**：非并发竞态，乃**输入信号抖动致逻辑条件失效**。实测 `carSpd` 在 0.16~0.90 km/h 震荡（阈值 0.5 km/h），导致状态在 6(Passive)↔3(Active) 间跳变。
3.  **根因定位**：
    *   **雷达层**：`target_disappear` 频发导致 `adasWarning` 同帧翻转，中断 `FCTBFuncGap` 计时。
    *   **输出层**：状态无法维持 Active，致 `CR_BrkgReq` 仅持续 960ms（期望 3000ms）。
    *   **抑制层**：`ESP_FD2.AEBBAActv`=0 缺失外部保压兜底。

结论：问题本质为信号质量不足，非代码同步缺陷。建议优化低速车速滤波及目标跟踪稳定性。


## 主持人审查


### 矛盾点
- 车速判定标准不一致：信号链路专家认为 0.16~0.90 km/h'处于低速检测区'标记为满足(Y)，而算法/系统状态专家认为 0.5 km/h阈值下多帧低于该值标记为不满足(N)。关键是fFctbActiveLowSpd=0.5km/h是否为硬性门槛。
- AEBBAActv=0的角色定义冲突：算法专家称其为'静态条件非动态原因'，而信号链路/架构/系统状态专家都认为它是'导致制动释放的直接因素'。需澄清这是设计逻辑还是异常状态。
- 根因权重分配不明确：感知专家认为'目标跟踪不稳定'是唯一主因，算法专家认为'车速抖动+目标丢失'是复合主因，系统状态专家认为是'目标不稳定+AEB抑制'组合。三方对主导因素的排序不同。


### 遗漏
- L2.5时序耦合层完全缺失：没有专家追溯代码中哪段'hld/releasel/accumulator/clear/debounce/hysteresis'逻辑被时序触发。TPE段虽显示'无触发模式'，但可能因为格式未规范解析，需确认是否有file:line_start~line_end证据被忽略。
- CAN信号极性未验证：ESP_FD2.AEBBAActv_0x137的'1=激活/0=非激活'定义未经原始文档确认，仅凭统计推断。若极性反用，整个抑制逻辑分析方向错误。
- 双状态机竞争条件未深挖：adasFunc.c与ASWIN_SystemState.c两套状态机的更新频率、写保护、互斥机制无人验证。fctb_system_state被反复改写(6→2→3→2→6)是否由并发导致？
- 制动请求输出路径未闭环：CR_BrkgReq是从bFctbKeepBrakeFlg直接赋值，还是经过优先级仲裁模块？输出周期与时钟源是什么？
- 目标消失物理特征未量化：trc_0~3集体消失时的distance/speed/doppler/RCS特征、消失位置(RoI边界?)、重连延迟无数据分析。


### 关键争议
最关键的争议点是：AEBBAActv=0是FCTB制动释放的'必要原因'还是'伴随现象'? 如果设计本意就是'AEB不工作时FCTB可独立保压'，那么根因应落在车速阈值(0.5km/h)过低+目标跟踪不稳定；如果设计是'FCTB依赖AEB协同保压'，那么AEBBAActv=0才是真正的阻断条件。这需要查阅系统需求规格书(SRS)才能定性。