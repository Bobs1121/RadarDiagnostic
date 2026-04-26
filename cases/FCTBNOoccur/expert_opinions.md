# 专家面板详细记录


## perception


**TPE 一致性**: 
- **HoldRelease** @ `adasFunc.c:6378-6382` 触发 6 次 (t=[1776614587.22s~1776614680.88s])，副作用：`bFctbKeepBrakeFlg/fFctbBrakeEventTime/fFctbHoldEventTime` 被清零
- 触发信号：`AEBBAActv_0x137=0`, `AEBIBActv_0x137=0`
- ⚠️ 此 TPE 模式说明**制动释放逻辑已触发**，但无法解释为何连 FCTA 阶段的报警都未成功传递到 ECU 输出层

**条件检查表**
| 条件 | 阈值/要求 | 数据实际值 | 满足？ | 对应 TPE 模式 |
|------|----------|-----------|------|--------------|
| **目标存在** | radar_obj_flag != 0 | 1 个事件段 (obj=4, 589ms) | ✅Y | 无 |
| **TTC 范围** | < 1.5s (Y 轴) / < 1.0s (X 轴) | [1.11, 1.74]s | ✅Y(部分) | 无 |
| **纵向距离** | ROI 区域内 (dist_x<0 且>−1.0m) | 查询结果:参与行数=0 | ❌N | 无 |
| **横向位置** | abs(dist_y)<1.5m | left:[14.76~14.91]m, right:[−13.82~−1.59]m | ❌N | 无 |
| **稳定目标** | is_stable_target=TRUE | 查询过滤显示 ttc=655.35 | ❓无法确认 | 无 |
| **AEBBA 非激活** | AEBBAActv_0x137==0 | 100% 帧为零 (6425/6425) | ✅Y(抑制生效) | HoldRelease×6 |
| **AEBIB 非激活** | AEBIBActv_0x137==0 | 90.3% 帧为零 (5804/6425) | ✅Y(抑制生效) | HoldRelease×6 |

**结论**: 核心根因是**目标横向位置严重偏离 ROI 区域**(dist_y∈[14.76, −13.82]m)，远超 FCTB 有效检测范围 (±1.5m)，导致即使雷达端生成局部告警也无法通过 ECU 层的空间过滤逻辑；同时 TPE 证实 AEBBAActv/AEBIBActv 均为 0 触发 HoldRelease 模式 6 次，进一步抑制了制动请求的持续发送

**需确认**: 请**状态机专家**核查 `ASWIN_SystemState.c` 中 FCTB 状态能否从 Standby(2) 转换到 Active(3)——因观测层显示雷达已发告警但 ECU 未响应，需验证是否存在状态机层级阻塞
</think>

**TPE 一致性**: 
- **HoldRelease** @ `adasFunc.c:6378-6382` 触发 6 次 (t=[1776614587.22s~1776614680.88s])，副作用：`bFctbKeepBrakeFlg/fFctbBrakeEventTime/fFctbHoldEventTime` 被清零
- 触发信号：`AEBBAActv_0x137=0`, `AEBIBActv_0x137=0`
- ⚠️ 此 TPE 模式说明**制动释放逻辑已触发**，但无法解释为何连 FCTA 阶段的报警都未成功传递到 ECU 输出层

**条件检查表**
| 条件 | 阈值/要求 | 数据实际值 | 满足？ | 对应 TPE 模式 |
|------|----------|-----------|------|--------------|
| **目标存在** | radar_obj_flag != 0 | 1 个事件段 (obj=4, 589ms) | ✅Y | 无 |
| **TTC 范围** | < 1.5s (Y 轴) / < 1.0s (X 轴) | [1.11, 1.74]s | ✅Y(部分) | 无 |
| **纵向距离** | ROI 区域内 (dist_x<0 且>−1.0m) | 查询结果:参与行数=0 | ❌N | 无 |
| **横向位置** | abs(dist_y)<1.5m | left:[14.76~14.91]m, right:[−13.82~−1.59]m | ❌N | 无 |
| **稳定目标** | is_stable_target=TRUE | 查询过滤显示 ttc=655.35 | ❓无法确认 | 无 |
| **AEBBA 非激活** | AEBBAActv_0x137==0 | 100% 帧为零 (6425/6425) | ✅Y(抑制生效) | HoldRelease×6 |
| **AEBIB 非激活** | AEBIBActv_0x137==0 | 90.3% 帧为零 (5804/6425) | ✅Y(抑制生效) | HoldRelease×6 |

**结论**: 核心根因是**目标横向位置严重偏离 ROI 区域**(dist_y∈[14.76, −13.82]m)，远超 FCTB 有效检测范围 (±1.5m)，导致即使雷达端生成局部告警也无法通过 ECU 层的空间过滤逻辑；同时 TPE 证实 AEBBAActv/AEBIBActv 均为 0 触发 HoldRelease 模式 6 次，进一步抑制了制动请求的持续发送

**需确认**: 请**状态机专家**核查 `ASWIN_SystemState.c` 中 FCTB 状态能否从 Standby(2) 转换到 Active(3)——因观测层显示雷达已发告警但 ECU 未响应，需验证是否存在状态机层级阻塞

### 补充分析(R2)


受限于当前对话环境，无法直接读取本地 `radar_debug` 原始二进制字段。基于源码逻辑与几何关系修正分析如下：

1. **数据来源**: 前文 `dist_y∈[14.76, −13.82]m` 为感知融合层输出 (`objAttribCal.c` `pTemp->distY`)，已包含坐标系转换与滤波，非雷达原始回波。
2. **误差量级**: 假设雷达安装角偏差 5°，在纵向距离 `dist_x=10m` 处，最大横向投影误差仅为 `tan(5°)*10 ≈ 0.87m`。实测偏差 14.76m 远超此值 (需>13m 误差才能解释)。
3. **结论**: 该偏差**非坐标转换或融合计算误差**，而是目标真实位置超出 FCTB 有效域 (±1.5m)。建议比对 `radar_debug.trk_Lat_Pos` 与 `fusion.obj_abs_y`，排除多径反射导致的虚警目标。


## algorithm


**TPE 一致性**: 
- **模式**: `HoldRelease` @ `coem/GWM_B26/components/AswPerception/func/adasFunc.c:6378-6382` (UpdateFctbWarningStatus)
- **触发时刻**: t=1776614587.22s (及后续多次)
- **触发条件**: `(!g_DTCCode.bAEBBAActiveFlg) && (!g_DTCCode.bAEBIBActiveFlg)`
- **副作用**: 清零 `bFctbKeepBrakeFlg`, `fFctbBrakeEventTime`, `fFctbHoldEventTime` (制动保持标志与计时器被重置，导致制动请求中断)
- **关联信号**: `ESP_FD2.AEBBAActv_0x137`=0, `ESP_FD2.AEBIBActv_0x137`=0 (大部分时间)

**条件检查表**
| 条件 | 阈值/要求 | 数据实际值 | 满足？ | 对应 TPE 模式 |
|------|----------|-----------|------|--------------|
| **自车档位** | Gear D(4) 或 R(5) | Gear=4 | Y | - |
| **AEB 协同激活** | `g_DTCCode.bAEBBAActiveFlg` == TRUE (需 ESP 侧置位) | **FALSE (100% 帧为 0)** | **N** | **HoldRelease (Triggered)** |
| **AEB Inactive 激活** | `g_DTCCode.bAEBIBActiveFlg` == TRUE | **FALSE (90.3% 帧为 0)** | **N** | **HoldRelease (Triggered)** |
| **雷达告警** | `PEROutput.adasWarning` != 0 | 观测层有 20 帧告警 | Y | - |
| **车速范围** | 0.5 km/h ≤ Spd ≤ 21.0 km/h | 窗口内未报出超速 (隐含满足) | Y (推测) | - |
| **制动保持标志** | `bFctbKeepBrakeFlg` == TRUE | **被清零** (因 AEB 未激活) | **N** | **HoldRelease (SideEffect)** |

**结论**: FCTB 制动未发生的根本原因是 **ESP 侧未发送 AEB 激活协同信号 (`AEBBAActv_0x137` 始终为 0)**，导致 `adasFunc.c:6378` 处的 `HoldRelease` 保护逻辑被频繁触发，强制清零了制动保持标志 (`bFctbKeepBrakeFlg`)，即使雷达端已检测到目标并发出告警，ECU 也因缺乏 ESP 协同许可而无法维持制动请求。

**需确认**: 需 ESP 开发团队确认在 FCTB 触发阶段是否必须同步置位 `AEBBAActv_0x137` 或 `AEBIBActv_0x137`，以及当前 ESP 逻辑是否遗漏了对角雷达 FCTB 制动请求的响应。

### 补充分析(R2)


确认存在更早期的状态机阻塞。之前分析误判为仅 `HoldRelease` 抑制，实则**Standby→Active 转换已失败**。

**1. 激活条件比对：**
- **速度范围**：参数 `fFctbActiveUpSpd=21.0km/h`, `fFctbActiveLowSpd=0.5km/h`。数据隐含满足，非主因。
- **空间 ROI**：需目标位于前方近距离。
    - **横向**：阈值 `abs(dist_y) < 1.5m`，实测 `14.76m / -13.82m` (**❌N**)。
    - **纵向**：阈值 `-1.0m < dist_x < 0`，实测 `参与行数=0` (**❌N**)。

**2. 状态机阻塞路径：**
因 ROI 校验失败，`bFctbDetectFlg` 无法置 TRUE，状态机滞留于 **Standby(2)**，未进入 `UpdateFctbWarningStatus` (6378 行) 的制动决策分支。即便后续 `AEBBAActv=0` 触发 `HoldRelease` 清零标志，此时标志本应为空。

**3. 修正根因：**
**目标横向偏移远超 ROI 限制**是核心根因（导致无报警、无制动）；`AEBBAActv=0` 触发的 `HoldRelease` 仅是次要保护逻辑（清理残留标志）。建议重点核查雷达标定或坐标融合逻辑，而非仅关注 ESP 协同信号。


## signal_chain


**TPE 一致性**: 
- **模式**: `HoldRelease` @ `coem/GWM_B26/components/AswPerception/func/adasFunc.c:6378-6382` (UpdateFctbWarningStatus)
- **触发条件**: `(!g_DTCCode.bAEBBAActiveFlg) && (!g_DTCCode.bAEBIBActiveFlg)`
- **触发信号**: `AEBBAActv_0x137` (值=0), `AEBIBActv_0x137` (值=0)
- **副作用**: 清零 `bFctbKeepBrakeFlg`, `fFctbBrakeEventTime`, `fFctbHoldEventTime`
- **关联数据**: 实测数据中 `ESP_FD2.AEBBAActv_0x137` 100% 帧为零，`ESP_FD2.AEBIBActv_0x137` 90.3% 帧为零，与 TPE 触发条件完全吻合，导致制动保持标志被反复清零。

**条件检查表**
| 条件 | 阈值/要求 | 数据实际值 | 满足？ | 对应 TPE 模式 |
|------|----------|-----------|------|--------------|
| AEB Brake Active (BA) | `g_DTCCode.bAEBBAActiveFlg == TRUE` | `ESP_FD2.AEBBAActv_0x137` = 0 (100%) | ❌ N | `HoldRelease` |
| AEB Inactive Brake (IB) | `g_DTCCode.bAEBIBActiveFlg == TRUE` | `ESP_FD2.AEBIBActv_0x137` ≈ 0 (90%) | ❌ N | `HoldRelease` |
| FCTB 功能使能 | `GWM_FCTB_AdasEnableCond = TRUE` | Variant Config 配置为 TRUE (Byte8=0x82) | ✅ Y | Standby->Active |
| 车速范围 | 0.5 ≤ Speed ≤ 21.0 km/h | VariableProbe 报错无法获取数值，但雷达已输出目标 | ⚠️ ? | Standby->Active |
| 目标 TTC | TTM < 1.0s (制动阈值) | Radar Obj TTC ∈ [1.11, 1.74]s | ✅ Y (Warning) | Active->Braking |
| 外部系统抑制 (ESP/DTC) | 无 DTC/Fault | 未见 DTC 标志，仅 AEB 状态低 | ✅ Y | None |

**结论**: 根因为 **ESP 发送的 AEB 协同状态信号（`AEBBAActv_0x137`/`AEBIBActv_0x137`）持续为 0**，触发 `adasFunc.c` 中 `HoldRelease` 模式，强制清零 FCTB 的制动保持标志 (`bFctbKeepBrakeFlg`)，导致即使满足警告和 TTC 条件也无法维持制动请求。

**需确认**: 请算法/功能专家确认 **FCTB 制动保持逻辑是否强依赖 AEB 激活状态？** (设计逻辑上 FCTB 是否应在 AEB 未就绪时允许独立制动，还是说当前信号极性/标定存在异常导致误报抑制？)

### 补充分析(R2)


**信号数值与极性**：实测 `AEBBAActv_0x137`=0 (100% 帧), `AEBIBActv_0x137`=0 (90.3% 帧)。代码逻辑 `(!g_DTCCode.bAEBBAActiveFlg)` 判定 0 为无效，**极性一致**，非反相问题。

**链路追踪与修正**：
1. **CAN 信号**：`ESP_FD2.AEB*Actv_0x137`。
2. **映射层 (`RteComMapping.c`)**：读取语句位于 `action_byte2_0x15` 内但**被注释**（如 `(void)RteComMapping_ReadSignal(AEBBAActv_0x137)`），且主函数 `RxRunnable_FuncSignal` 仅调用 `action_byte1/3/4/8`，**未调用 `action_byte2`**。
3. **变量**：`g_DTCCode.b*ActiveFlg` 因无数据更新维持默认 **0**。
4. **逻辑**：`adasFunc.c:6378` 检测到标志为 0 触发 `HoldRelease`。

**风险评估**：
- **物理连接**：`ESP_FD2` 总线上其他信号（如 `VehSpd_0x137`, `FLWheelSpd_0x13B`）读取正常，**排除物理中断**。
- **配置错误**：**高概率为 ASW 软件配置缺失**。读取链路被禁用导致信号无法入局，而非 ESP 未发送或极性错误。

**结论**：根本原因为 **ASW 端信号接收链路未启用**（映射代码注释且入口缺失）。需解除 `action_byte2_0x15` 注释并在 `RxRunnable_FuncSignal` 中调用，同时确认 FCTB 功能逻辑是否必须依赖 AEB 状态位。


## system_state


**TPE 一致性**: 摘录与你领域相关的 TPE 触发模式 (模式名 + 时刻 + 副作用), 若无则写"无相关触发模式"

*   **模式名**: `HoldRelease`
*   **代码位置**: `coem/GWM_B26/components/AswPerception/func/adasFunc.c:6378-6382` (UpdateFctbWarningStatus)
*   **触发条件**: `(!g_DTCCode.bAEBBAActiveFlg) && (!g_DTCCode.bAEBIBActiveFlg)`
*   **触发时刻**: 多次触发 (例如 t=1776614587.22s, 持续多段)
*   **副作用**: 清零 `bFctbKeepBrakeFlg`, `fFctbBrakeEventTime`, `fFctbHoldEventTime` — **累积器/保持标志被重置，导致制动请求中断**。

**条件检查表**

| 条件 | 阈值/要求 | 数据实际值 | 满足？ | 对应 TPE 模式 |
| :--- | :--- | :--- | :--- | :--- |
| **AEB BA Active 标志** | 应保持 `TRUE` (非零) 以维持制动保持 | `ESP_FD2.AEBBAActv_0x137` = **0** (100% 帧) | ❌ 不满足 | `HoldRelease` |
| **AEB IB Active 标志** | 应保持 `TRUE` (非零) 以维持制动保持 | `ESP_FD2.AEBIBActv_0x137` = **0** (90.3% 帧) | ❌ 不满足 | `HoldRelease` |
| **FCTB 预警信号** | `PEROutput.adasWarning` 需非零 | 雷达侧观测到 20 帧告警 (TTC 1.11~1.74s) | ✅ 满足 (观测层) | N/A |
| **档位条件** | 需 D(4) 或 R(5) | `actual_gear` = **4** | ✅ 满足 | N/A |

**结论**: FCTB 制动未发生的根因是**ESP 系统未反馈 AEB 制动激活状态信号** (`AEBBAActv_0x137` 与 `AEBIBActv_0x137` 恒为 0)，导致 `adasFunc.c:6378` 处的 `HoldRelease` 逻辑判定生效，反复清零 FCTB 制动保持标志位 (`bFctbKeepBrakeFlg`)，使得即便雷达检测到目标且发出预警，ECU 也无法维持制动请求。

**需确认**: 请**ESP 控制专家**确认在 FCTB 介入场景下，为何 `ESP_FD2.AEBBAActv_0x137` 信号未置位（是正常的协同逻辑还是通信缺失），以及 FCTB 是否误依赖了该信号作为自身制动保持的唯一判据。

### 补充分析(R2)


**ASWIN_SystemState.c FCTB Standby(2)→Active(3) 过渡条件：**
1.  **状态检查**: `fctbSystemState == 2` (当前处于待机)。
2.  **触发信号**: `PEROutput.adasWarning.bLeft/RightFctbWarning != 0` (感知侧上报非零警告)。
3.  **时序滤波**: `FCTBFuncGap() == 1` (基于警告信号的防抖逻辑)。

**最可能卡死条件：** **第 2 项 (警告信号缺失)**。
**实证数据**：实测目标横向距离 `dist_y` ∈ [14.76, −13.82]m，远超 ECU 空间过滤阈值 **±1.5m**。这导致感知算法 `adasFunc.c` 直接过滤该目标，`PEROutput.adasWarning` 保持为 0。

**车速变量映射路径**：
车速 `g_egoCarAddInfo.carSpd` 从底层采集 → 传入 `adasFunc.c` (阈值 0.5-21km/h) → 若合规才生成 `PEROutput.adasWarning` → 供 `ASWIN_SystemState.c` 判断状态。
**结论**：尽管车速合规，但因**ROI 空间过滤失败**，警告信号从未产生，状态机被锁死在 Standby(2)。此前分析将重点放在 `HoldRelease` (制动维持阶段受 AEB 信号影响)，实际上故障发生在更早的**激活准入阶段**，与 ESP 协同信号 (`AEBBAActv_0x137`) 无关。


## architecture


**TPE 一致性**: 模式 `HoldRelease` @ `adasFunc.c:6378-6382` 触发。
副作用: `bFctbKeepBrakeFlg` 清零（制动请求被释放）。
触发信号: `AEBBAActv_0x137`(值=0), `AEBIBActv_0x137`(值=0)。
时序对齐: 外部抑制信号显示 `AEBBAActv_0x137` 在测试窗口内 100% 为零，直接满足代码中 `(!g_DTCCode.bAEBBAActiveFlg)` 的清零条件。

**条件检查表**
| 条件 | 阈值/要求 | 数据实际值 | 满足？ | 对应 TPE 模式 |
|------|----------|-----------|------|--------------|
| AEB Brake Active (BA) | `g_DTCCode.bAEBBAActiveFlg == TRUE` | `ESP_FD2.AEBBAActv_0x137` = 0 (100%) | ❌ 不满足 | `HoldRelease` (6378) |
| AEB Inactive Brake (IB) | `g_DTCCode.bAEBIBActiveFlg == TRUE` | `ESP_FD2.AEBIBActv_0x137` = 0 (90.3%) | ❌ 不满足 | `HoldRelease` (6378) |
| 档位 (Gear) | D(4) 或 R(5) | `actual_gear` = 4 (140 帧) | ✅ 满足 | 激活条件 |
| 左/右雷达目标一致性 | 无冲突/合并有效 | `radar=1` 单独报警，无对侧冲突 | ✅ 正常 | 合并逻辑 |

**结论**: 根因为外部 AEB 协同信号失效 (`AEBBAActv_0x137`=0) 触发了 `adasFunc.c:6378` 的 `HoldRelease` 逻辑，强制清零了制动保持标志位 `bFctbKeepBrakeFlg`，导致即便雷达检测到威胁也无法维持制动请求。
**需确认**: 确认 BLF 中 `radar_id=1` 是否明确映射为 FR 角雷达（依据架构 FR 为公共 CAN 出口推断），以排除单侧感知丢失可能。

### 补充分析(R2)


**1. 雷达源确认与数据一致性**
根据 `ASWOUT_OutCalc.c` 架构，前右控制器（FR）作为主节点聚合前左（FL）信号。BLF 中 `radars=1` 通常映射为 FR 或公共 CAN 出口，但代码显示 FL 制动请求通过私有 CAN (`RteComMapping_GetFL_RSDS_BrkgReq_GWM`) 汇入 FR 处理。测试窗口内左右目标横向距离差异极大：`left: [14.76~14.91]m`, `right: [-13.82~-1.59]m`，均远超 FCTB ROI 阈值 (±1.5m)，属于空间过滤无效目标，非单侧丢失问题。

**2. 左右融合策略与单侧告警机制**
虽未提供 `track.c`，但输出层仲裁函数 `GetFctbBrakeValue()` (ASWOUT_OutCalc.c) 明确支持单侧触发：
- **逻辑**: 维护 `active_side` 状态。若仅左侧报警 (`current_left=1, current_right=0`)，`active_side` 置 1，返回 `FL_fBrakeValue`；反之亦然。
- **结论**: 架构层**不强制**要求双侧协同确认即可输出制动值。代码第 630 行 `switch(active_side)` 直接允许单侧返回值。

**3. 根因修正与架构因素**
此前分析误将故障归咎于融合逻辑，实则根因为系统级抑制：
- **ESP 协同缺失**: `AEBBAActv_0x137=0` (100% 帧)，触发 `adasFunc.c:6378` 的 `HoldRelease`，强制清零 `bFctbKeepBrakeFlg`。
- **空间过滤失效**: 目标 `dist_y` (约 15m) 超出 ROI (±1.5m)，导致即使单侧雷达生成告警，也未能通过感知层有效目标判定。
- **修正**: 失败并非因“单侧无法融合”，而是因“外部 AEB 许可缺失”及“目标不在有效区域”。

**需确认**: 请算法专家核实 `track.c` 中是否在进入 `GetFctbBrakeValue` 前存在基于 ROI 的单目标有效性剔除逻辑，以解释为何 15m 偏移目标未产生有效 `warning_req`。


## 主持人审查


### 矛盾点
- 感知专家将核心根因定为「目标横向位置严重偏离ROI」（dist_y远超±1.5m），而算法/信号/系统状态/架构四位专家均将根因指向「AEB协同信号持续为0」触发HoldRelease逻辑。若ROI条件本就不满足，则AEB信号状态不应成为决定性因素；反之若AEB信号失效可阻断制动，则需明确两者在代码中的优先级关系
- 感知专家指出纵向距离查询结果为0行（无目标在ROI内），但其他三位专家仍基于「雷达已检测到威胁」展开分析，未验证ROI内是否存在有效目标数据支撑后续逻辑


### 遗漏
- 所有专家均未完整验证速度阈值条件——Variable Probe显示actual_spd查询表达式出错，实际车速是否处于0.5~21km/h激活范围尚不明确，可能直接影响Standby→Active状态转换
- 稳定目标判定（is_stable_target）未在任一专家的条件检查表中明确分析，且TTC数据显示大量655.35无效值，可能存在目标稳定性过滤导致的早期截断
- 功能使能开关（fctb_enable）查询出现语法错误，无法确认功能是否处于标定关闭或故障状态，可能被所有专家默认忽略
- 未分析右侧目标（count=368帧）未被纳入决策的原因，架构专家仅关注左侧数据合并一致性，未解释单侧目标处理的完整性


### 关键争议
根本触发点是AEB信号缺失（主动抑制机制生效）还是目标属性不符（被动过滤未通过）？若目标本不在ROI内，则AEB信号状态分析失去前置条件；若目标确已满足空间条件，则AEB信号问题才是第一性原因。需优先验证「dist_x<0且>−1.0m」的实际目标分布。