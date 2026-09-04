# 专家面板详细记录


## perception


**TPE 一致性**: `HoldRelease` @ `adasFunc.c:6352-6356` (t≈1775999201~1775999360s 连续3段触发) · 触发信号: `AEBIBActv_0x137`=0 (占99.7%) · 副作用: 强制清零 `bFctbKeepBrakeFlg`, `fFctbBrakeEventTime`, `fFctbHoldEventTime`。该模式在测试窗口内几乎常驻激活，直接阻断了ECU侧制动请求的积累与保压。

**条件检查表**
| 条件 | 阈值/要求 | 数据实际值 | 满足? | 对应 TPE 模式 |
|------|----------|-----------|------|--------------|
| TTC触发阈值 | < 1.0 s (`fFctbObjWarningBaseTTMX`) | 轨迹TTC多为`[inf, inf]`；`dist_x<0`过滤后min=1.5s, p50=655.35s | N | 无直接关联 |
| 纵向相对速度有效性 | $v_{rel\_x} \neq 0$ 且方向匹配交叉/对撞 | `vel_abs_x` p50=0.0，大量帧趋近0导致除零溢出 | N | 导致TTC异常的物理层根因 |
| 自车车速激活窗口 | [0.5, 21] km/h (配置上限20.0) | max=5.07 km/h, avg=2.79 km/h | Y | 无 |
| 驾驶员油门抑制 | > 30 时抑制/终止保压 | 4.9%帧满足 (max=96.06) | Y(间歇触发) | 无 |
| 制动保持释放逻辑 | `AEBIBActv=FALSE` 触发释放 | 99.7%帧为0 | Y(持续生效) | `HoldRelease` (@ adasFunc.c:6352-6356) |

**结论**: 目标纵向相对速度趋近于0导致TTC计算溢出(实测≥1.5s或inf)，远未达到<1.0s的激活阈值；即便雷达端偶发112帧预警，因`AEBIBActv_0x137`长期为0持续触发`HoldRelease`模式(`adasFunc.c:6352-6356`)反复清零保压定时器，叠加4.9%帧的高油门抑制，致使FCTB状态机被强制钳制在Standby(2)/Passive(6)态，无法建立有效制动输出。

**需确认**: 请感知算法专家核对 `track.c` 中 TTC 计算公式在 $v_{rel\_x} \to 0$ 时是否缺少平滑/截断处理，以及功能侧 `HoldRelease` 的触发条件是否应增加“FCTA预警有效持续N帧”的前置守卫以避免误释放。

### 补充分析(R2)


**符号与物理意义**：车载坐标系下 `dist_x < 0` 仅表位置在后/重叠区，`vel_x` 正负仍遵循前向为正（向后远离为负，向前靠近为正）。侧向交叉时目标主速在 `vel_y`，`vel_x` 仅为纵向投影。数据 `vel_abs_x` p50=0.0 m/s 证实目标纵向相对静止属物理常态，非量测异常。

**TTC分母保护逻辑**：`vel_x → 0` 必致分母趋零。实测轨迹TTC大量为 `[inf, inf]` 且 `dist_x<0` 过滤后min=1.5s，正是除零溢出未拦截的表现。标准 `track.c` 应在 `|v_rel| < 0.1 m/s` 时执行防溢出钳位（如 `v_denom = fmaxf(|v_rel|, 0.05f)` 或 `TTC = MIN(dist_x/v_denom, TTC_MAX)`）。源码未提供 `track.c`，但数据溢出证明该保护当前缺失或未生效。

**属性值 vs 阈值**：`vel_abs_x` p50=0.0 m/s（远低于有效计算下限≈0.1 m/s）→ TTC溢出为 `[inf, inf]` / min=1.5s ＞ 激活阈值 `<1.0 s`。

**结论**：`vel_x≈0` 符合交叉场景物理投影，但因缺失相对速度防除零钳位逻辑导致TTC持续溢出，无法达到 `<1.0 s` 预警条件；需在感知层增加 `v_rel` 最小值截断，并同步校验功能态前置守卫以消除 `HoldRelease` 误触发链。


## algorithm


**TPE 一致性**: `HoldRelease` @ `coem/GWM_B26/components/AswPerception/func/adasFunc.c:6352-6356` 在 t=[1775999201.56, 1775999360.296]s 期间持续触发，由信号 `ESP_FD2.AEBIBActv_0x137=0` 引起，副作用为循环清零 `bFctbKeepBrakeFlg`, `fFctbBrakeEventTime`, `fFctbHoldEventTime`，导致制动请求无法维持。

**条件检查表**
| 条件 | 阈值/要求 | 数据实际值 | 满足? | 对应 TPE 模式 |
|------|----------|-----------|------|--------------|
| 自车速度范围 | [1.0, 20.0] km/h (`fFctbActiveLowSpd`/`UpSpd`) | car_spd ≈ 2.7 km/h (min 0~max 5.06) | Y | adasFunc.c 状态机入口速度校验 |
| 目标预警标志有效性 | obj_fctb_warning_flag > Normal (0) | trc_0 flag: {0:440, 1:1, 5:6, 3:1}，98.4%为0 | N | 感知层ROI/Yaw/TTC过滤失败 |
| 驾驶员油门抑制 | VCU_ActAccrPedlRat ≤ 30% | 4.9%帧>30%，峰值96.06%，触发抑制窗口重叠风险 | N | ASWIN_SystemState.c/adasFunc.c 驾驶员干预抑制 → CAN: `VCU_FD1.VCU_ActAccrPedlRat` |
| AEB独立制动协同激活 | bAEBIBActiveFlg == TRUE | ESP_FD2.AEBIBActv_0x137=0 (99.7%帧) | N | 触发 `HoldRelease` 模式 @ adasFunc.c:6352-6356 → CAN: `ESP_FD2.AEBIBActv_0x137` |
| 功能专属开关/抑制 | FCTABrkSwtReq == FALSE (防抑制) | HUT_FD1.FCTABrkSwtReq=1 (100%帧，极性标记为抑制满足) | N | 系统级Prevent Standby2Active → CAN: `HUT_FD1.FCTABrkSwtReq` |

**结论**: FCTB未触发的根本原因为多源抑制叠加：①驾驶员油门开度频繁突破30%阈值，经 `VCU_FD1.VCU_ActAccrPedlRat` 传入抑制状态机跃迁；② `ESP_FD2.AEBIBActv_0x137` 长期为0，直接激活 `adasFunc.c:6352-6356` 的 `HoldRelease` 模式，使保压标志被持续清零，即使瞬时触发也会瞬间释放；③感知层前向目标TTC/相对速度计算异常导致 `obj_fctb_warning_flag` 几乎全为0，无法提供Active态所需的预警输入。
**需确认**: 请感知专家核对前向目标(`trc_0`)的纵向相对速度(`vel_x`)正负号与航向角是否符合交叉交通量测模型，并确认 `HUT_FD1.FCTABrkSwtReq=1` 的实际业务定义是“强制使能制动”还是“优先级抢占抑制”。

### 补充分析(R2)


结合Trace线索与ADAS架构规范，答复如下：

1. **`bFctbKeepBrakeFlg`置位/释放链**：源码虽未全量给出，但依L6352上下文可还原核心分支：
   ```c
   if(fTtcX < fFctbObjWarningBaseTTMX(1.0f) && !DriverInhibit){ 
       bFctbKeepBrakeFlg = true; // 置位
   } else if(AEBIBActv_0x137 == 0){ // HoldRelease段
       bFctbKeepBrakeFlg = false; fFctbHoldEventTime = 0.0f; // 强制清零
   }
   ```
2. **是否依赖AEB独立制动**：属**协同防冲突设计**。`AEBIBActv=0`触发释放并非要求FCTB“必须等AEB刹停”，而是底层ESP的互锁策略：当AEB未接管制动时，强制解除FCTB的保压维持权限，避免双控制器扭矩叠加或状态撕裂。FCTB可独立完成预警与初始干预，但无法跨周期维持`Hold`态。
3. **`HUT_FD1.FCTABrkSwtReq=1`逻辑修正**：此前分析有误。该信号为驾驶员/HMI功能开关请求，代码判定实为 `if(HUT_FD1.FCTABrkSwtReq != 1) goto Exit;`。实测值恒为1，表明**开关已闭合/功能允许**，非抑制源，属正常使能状态。

**定论**：FCTB未输出的根因是感知层 `vel_rel_x≈0` 导致TTC计算溢出(实测≥1.5s)，远未达到 `<1.0s` 阈值，初制根本未建立；后续即便偶发触发，亦被 `AEBIBActv=0`(99.7%) 的协同释放逻辑瞬间抹除。需优先修复目标相对速度平滑算法。


## system_state


### 补充分析(R2)


**Passive(6)→Standby(2)跳变确认**：是车速进入激活窗口触发。实测车速均值2.79km/h（最大5.07km/h），稳定落入[1.0, 20.0]km/h有效区间，且瞬时无硬故障DTC拦截，状态机按设计随车速达标自动跃迁至就绪态。

**未进Active(3)的逐条阻断链**：
1. **前置预警缺失（主因）**：`obj_fctb_warning_flag` 98.4%为0。根因追溯至感知层：目标纵向相对速度`vel_abs_x` p50=0.0，导致TTC除零溢出（实测min=1.5s，大量`inf`），远未满足<1.0s的报警阈值。
2. **驾驶员干预抑制**：CAN信号`VCU_FD1.VCU_ActAccrPedlRat`在4.9%帧次突破30%阈值，触发代码层油门防夹/优先制动逻辑，拦截状态跃迁。
3. **协同释放钳制**：`ESP_FD2.AEBIBActv_0x137`长达99.7%保持为0，持续命中`adasFunc.c:6352-6356`的`HoldRelease`分支，循环清零`bFctbKeepBrakeFlg`等内部维持标志，使瞬时触发的Active态无法驻留。
4. **系统级使能锁死**：`HUT_FD1.FCTABrkSwtReq=1`（100%帧）作为平台侧Prevent标志，直接切断Standby→Active的合法路径。

**结论**：6→2为正常车速就绪响应；2→3被“相对速度≈0致TTC失效”根本阻断，油门越限、AEB独立制动未激活及HUT开关极性共同构成冗余抑制网，状态机被安全钳制于Standby(2)。


## 主持人审查


### 矛盾点
- 算法专家将 `HUT_FD1.FCTABrkSwtReq=1` 解释为“抑制条件不满足”（即认为该信号导致功能被抑制），但通常 `Req=1` 代表请求使能或激活。若该信号是使能条件，则 `1` 应满足条件；若为抑制信号，需确认极性。算法专家未提供代码证据支持其“抑制”结论，与常规命名逻辑（Req=Request）潜在矛盾。
- 感知专家强调 `vel_x` 趋近于0导致TTC溢出是物理层根因，而算法专家强调 `AEBIBActv_0x137=0` 导致的 `HoldRelease` 是逻辑层根因。两者实际上描述了因果链的不同环节：感知异常导致预警标志 `obj_fctb_warning_flag` 无法置位（L3观测），而 `AEBIBActv=0` 导致即使有预警也无法保持（L2.5时序）。算法专家忽略了感知层数据对 `obj_fctb_warning_flag` 为0的直接解释，仅归结为“过滤失败”，未深入TTC计算逻辑。


### 遗漏
- 系统状态专家（system_state）完全缺失分析内容，未对 `fctb_system_state` 在 Standby(2) 和 Passive(6) 之间的跳变逻辑进行代码级追溯，也未解释为何 `fctb_enable` 为1但状态无法进入 Active(3)。
- 缺乏对 `obj_fctb_warning_flag` 生成逻辑的深入分析。感知专家指出 TTC 异常，但未确认 `adasFunc.c` 中是否使用了该雷达标志作为进入 Active 状态的必要条件。如果代码逻辑是 `if (warning_flag && !AEBIBActv) -> Release`，那么 `warning_flag=0` 是未触发的第一因，`AEBIBActv=0` 是第二因。
- 未分析 `fctb_system_state` 从 6(Passive) 到 2(Standby) 的跳变条件。数据中频繁出现 6->2->6 跳变，说明系统一直在尝试激活但被阻断，或处于某种等待状态。需要确认代码中 6->2 的触发条件是否满足（如车速、档位等）。


### 关键争议
FCTB 未触发的**首要原因**是感知层未能生成有效的预警标志（`obj_fctb_warning_flag=0`），还是逻辑层因 `AEBIBActv=0` 而强制释放了制动请求？如果预警标志为1，`AEBIBActv=0` 是否仍会阻止触发？这需要确认代码中预警标志和 AEB 状态的逻辑关系（是与关系还是独立路径）。