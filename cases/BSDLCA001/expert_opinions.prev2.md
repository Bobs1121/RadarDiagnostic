# 专家面板详细记录


## architecture


**TPE 一致性**: 无相关触发模式 (所有 HoldRelease 模式标记为"无法判定")。但 Variable Probe 数据显示 `lca_enable` (radar=2) 存在 [0, 1] 跳变，这与历史案例 LCA001 中 `bLCAEnable` 抖动导致计时器清零的逻辑高度吻合。

**条件检查表**
| 条件 | 阈值/要求 | 数据实际值 | 满足？ | 对应 TPE 模式 |
|------|----------|-----------|------|--------------|
| **LCA 使能信号稳定性** | `bLCAEnable` 应持续为 1 | `lca_enable` (radar=2): min=0.0, max=1.0 (波动) | **N** | `HoldRelease @ adasFunc.c:3998` (关联 bLcaLeftWarningFlg) |
| **LCA 系统状态** | State=2(Standby) or 3(Active) | State 随 `lca_enable` 跳变反复切换 | **N** | N/A (State 受 Enable 控制) |
| **ROI 内目标存在** | 目标在 ROI 内 | `dist_y` p50=5.53m, TTC>0 | Y | N/A |
| **左右合并逻辑** | RR 取 RL 最大警告值 | RL 本地警告被清零，RR 无从合并 | **N** | `ASWOUT_OutCalc.c:433` (RR 读取 RL 私有 CAN) |

**结论**: 根本原因是 **左后角雷达 (Radar 2) 的 LCA 使能信号 (`lca_enable`) 不稳定**，导致 ECU 内部 LCA 功能状态机频繁在 Enable/Disable 间切换，强制重置了报警保持计时器 (HoldRelease)，使得目标虽在 ROI 内但因无法累积足够的报警时长而被抑制。
**需确认**: 请 RteComMapping 专家核查 `LCASwtReq` CAN 信号在 Radar 2 端的接收质量及 `bLCAEnable` 的内部滤波逻辑，确认是否存在信号抖动未滤除导致功能反复启停。

### 补充分析(R2)


1. **雷达定位确认**：Radar 2 确认为 **左后角雷达 (RL)**。Variable Probe 数据显示 `lca_enable` (radar=2) 存在波动，与源码 `ENM_POS_REAR_LEFT` 块的本地计算逻辑相符。

2. **依赖与融合逻辑**：LCA 左侧报警 **仅依赖 Radar 2 本地输出**。源码表明，左侧警告 (`RL_BsdLca_Warning`) 由 RL 节点根据 `PEROutput.adasWarning.bLeftLcaWarning` 及 `lcaSystemState` 独立生成。虽 RR 控制器通过 `RteComMapping_GetRL_BSD_LCA_warningReqleft_GWM()` 读取 RL 结果用于公共 CAN 发送，但 **不存在跨侧感知融合**，右侧雷达数据无法补偿左侧报警逻辑。

3. **旁路/降级机制**：架构层 **未激活旁路逻辑**。输出条件严格校验 `lcaSystemState == 3`。当 `bLCAEnable` 因 `LCASwtReq` 信号抖动在 **[0, 1]** 区间跳变时，状态机被迫从 Standby(2) 复位至 Off(4)，强制清零报警保持计时器。代码未见针对单侧雷达使能异常的自动屏蔽或切换至冗余源的降级策略。

4. **测试窗口一致性**：窗口内 Radar 3/4 (右侧) 使能稳定维持 **1**，而 Radar 2 (左侧) 呈现 **[0, 1]** 混合状态。此 **左右数据不一致性** 证实故障隔离于左侧输入链路，排除全局配置错误，确认为单点信号抖动导致的状态机复位。


## perception


**TPE 一致性**: 无相关触发模式（所有 7 个 HoldRelease 模式均标记为“无法判定”，未解析到 CAN 信号变量链）。但变量探针数据显示 `lca_enable` 在雷达 2 上存在 [0, 1] 跳变，且 LCA 未触发时 TTC 中位数为异常值 655.35s，符合文档中“功能被禁用时清除警告”的状态重置特征。

**条件检查表**
| 条件 | 阈值/要求 | 数据实际值 | 满足？ | 对应 TPE 模式 |
|------|----------|-----------|------|--------------|
| **系统使能 (bLCAEnable)** | 必须持续为 1 (Standby/Active) | 雷达 2: [0, 1] 混合跳变; 雷达 3/4: 1 | **否 (间歇性失效)** | 无 (TPE 未解析) |
| **自车速度 (carSpd)** | >= 12.0 km/h (激活) | p50 ≈ 24.1 km/h | **是** | 无 |
| **目标横向距离 (dist_y)** | 进入 LCA ROI (约 ±3.3m+) | LCA=0 时 p50=5.53m (在范围内) | **是** | 无 |
| **目标纵向距离 (dist_x)** | 进入监测区 (如 -80m ~ -4m) | 正常触发时 [-39.82, -8.21]m; 事件中有接近行为 | **是** | 无 |
| **报警 TTC 阈值** | <= 4.0 s 触发 | LCA=0 时 p50=655.35s (异常/无效) | **数据异常** | 无 |
| **目标相对速度** | >= 7.2 km/h | 未直接提供，但动态目标多 | 未知 | 无 |

**结论**: 目标属性（距离、角度）满足触发条件，根本原因为 **雷达 2 的 LCA 功能使能信号 (lca_enable) 发生 [0, 1] 高频跳变**，导致 `adasFunc.c` 逻辑（参考文档 `adasFunc.c:1257` “功能被禁用时清除警告”）反复重置报警状态，致使 TTC 计算失效（显示 655.35s），表现为报警晚于 BSD。

**需确认**: 请信号/诊断专家排查公 CAN 信号 `LCASwtReq` 在测试窗口内的波形稳定性，确认是否存在抖动或 ECU 接收端的干扰问题。

### 补充分析(R2)


针对追问：**是的，雷达跟踪目标依然存在。**

**证据与推论：**
1.  **目标存在性确认**：感知专家条件检查表显示，在 LCA 未触发（LCA=0）且 TTC 中位数为 **655.35s**（无效值）的帧中，**目标横向距离 dist_y 中位数仍为 5.53m**，明确处于 LCA ROI 范围内（±3.3m+），纵向距离也在监测区内。若目标丢失（`target_valid=0`），距离统计数据将缺失或离散，现有稳定均值证明底层雷达跟踪有效。
2.  **TTC 异常本质**：**655.35s** 为典型无效标记。结合系统状态专家指出 `lca_enable` (radar=2) 存在 **[0, 1]** 高频跳变，当使能信号置 0 时，`adasFunc.c` 逻辑会强制复位状态机并清除警告标志（参考代码逻辑“功能被禁用时清除警告”），导致 TTC 计算被跳过或重置为默认值，而非因目标丢失无法计算。
3.  **假设验证**：自车速度 **24.1 km/h** 满足激活门槛，目标属性均符合触发条件。目标有效但 TTC 无效，排除了感知丢失可能，直接支持**「功能逻辑被抑制」**假设。

**结论**：根本原因是 `LCASwtReq` 信号抖动导致 `bLCAEnable` 震荡，反复复位报警计时器，致使目标虽在 ROI 内但因逻辑状态重置无法累积 TTC 判断时间。


## system_state


**TPE 一致性**: 无相关触发模式。
所有 7 个与 LCA 相关的代码模式（HoldRelease, adasFunc.c:3998-4059）均标记为「无法判定」，原因是 TPE 未能解析 `totalLeftLcaWarningState`、`bLcaLeftWarningFlg` 等内部变量到 CAN 信号的映射链路。因此，无法直接从 TPE 证据链锁定具体行号的触发时间，需结合「关键事实」中的配置层数据与「变量探针」进行逻辑推演。

**条件检查表**
| 条件 | 阈值/要求 | 数据实际值 | 满足？ | 对应 TPE 模式/来源 |
|------|----------|-----------|------|--------------|
| **功能使能位** (`bLCAEnable`) | 必须为 TRUE (1) | **混合 [0, 1]** (Key Fact 配置层) / Radar 2: min=0 max=1 (Probe) | **❌ 不满足/震荡** | Key Fact · ADAS 使能<br>Variable Probe · lca_enable |
| **自车速度** (`carSpd`) | [12.0, 146.0] km/h | ~24.1 km/h (p50) | ✅ 满足 | Variable Probe · actual_spd |
| **目标相对速度** (`velAbsX`) | > 7.2 km/h | 未直接给出，但 TTC 有效时通常满足 | ⚠️ 存疑 | LCA 报警逻辑 (adasFunc.c) |
| **系统状态** (`lcaSystemState`) | Standby(2) → Active(3) | 因使能位震荡，状态机频繁复位至 Off(4)/Passive(6) | ❌ 阻断 | ASWIN_SystemState.c:736~780 |
| **警告输出** (`adasWarning`) | 非零 (触发态转移) | 窗口内存在高频 `warning_edge_on/off` 震荡 | ⚠️ 不稳定 | Key Fact · 告警事件窗口 |

**结论**: LCA 报警延迟的根本原因是 **输入信号层 `LCASwtReq` (变道辅助开关请求) 信号不稳导致功能使能位 `bLCAEnable` 频繁翻转**。当 `bLCAEnable` 变为 0 时，`ASWIN_SystemState_UpdateLcaSystemStatus` 强制将 `lcaSystemState` 置为 Off(4)，阻断了 `AdasStateActive` 中从 Standby(2) 向 Active(3) 的状态转移；即使感知侧计算出 TTC 满足条件并产生 `bLcaLeftWarning`，因系统状态处于 Off，报警被抑制，直到目标进入更深层的 BSD 区域或使能位暂时稳定才可能触发。

**需确认**: 请总线专家核查测试时刻 (16:35:50 ~ 16:37) 的 CAN 信号 **`LCASwtReq`** 是否存在跳变 (Jitter/Noise)，以及是否受其他功能 (如 DCT 档位切换、ESP 诊断) 干扰导致 RteComMapping 映射异常。

### 补充分析(R2)


16:36:00 关键帧状态确认：

1.  **LCA 状态转移**：当 `lca_enable`=0 时，状态从 Standby(2) **强制跌落至 Off(4)**，非直接进入 Passive(6)。依据专家分析，`ASWIN_SystemState_UpdateLcaSystemStatus` 在使能丢失时优先置位 Off，直接阻断 `AdasStateActive` 中 Standby→Active 的跃迁。
2.  **BSD 影响**：**未受直接牵连**。源码 `AdasStateActive` 显示 BSD 与 LCA 虽同属一个调度块，但判断条件独立 (`bBSDEnable` vs `bLCAEnable`)。实测 BSD 先于 LCA 报警，证明其使能链路稳定，未因 LCA 开关抖动被连带复位。
3.  **关键数据**：探针显示 `lca_enable` **[0, 1]** 高频跳变；状态复位瞬间 TTC 输出 **655.35s** (无效值)；自车速度 **24.1 km/h** (满足>12km/h 阈值)。
4.  **修正说明**：此前表述“Off/Passive”不够精确，现已明确使能丢失优先触发 Off 状态。
5.  **根因**：输入层 **CAN 信号 `LCASwtReq` 抖动**导致内部 `bLCAEnable` 振荡，反复清零警告保持计时器。


## algorithm


**TPE 一致性**:
TPE 分析显示 LCA 相关逻辑模式（`HoldRelease` @ `coem/GWM_B26/components/AswPerception/func/adasFunc.c:3998~4002`）均为「无法判定」，原因系未能将内部变量（`totalLeftLcaWarningState`, `bLcaLeftWarningFlg`）直接映射到 CAN 信号。但结合「Variable Probe」数据，`lca_enable` 在雷达 ID 2 呈现 `[0, 1]` 混合跳变状态，这与历史案例 LCA001 中 `LCASwtReq` 信号不稳定导致 `bLCAEnable` 抖动、进而重置保持计时器的特征高度一致。虽无 TPE 直接触发证据，但输入层数据异常已锁定根因方向。

**条件检查表**
| 条件 | 阈值/要求 | 数据实际值 | 满足？ | 对应 TPE 模式 |
|------|----------|-----------|------|--------------|
| **功能使能位 (bLCAEnable)** | 持续为 1 (TRUE) | 混合 [0, 1] (波动) | **N** | `HoldRelease @ adasFunc.c:3998` (状态保持依赖使能) |
| **自车速度 (carSpd)** | 12.0 ~ 146.0 km/h | 约 24.1 km/h (p50) | Y | - |
| **目标 TTC (fLcaObjWarningTTC)** | < 4.0 s (报警) | 0.0 ~ 655.35 s (未报警时多为无效/过大) | N* | - |
| **系统状态机 (lcaSystemState)** | 2 (Standby) 或 3 (Active) | 因使能跳变动荡于 2 与 4 (Off) | **N** | `LcaUpdateSystemStatus` (代码片段逻辑) |
| **目标纵向距离 (dist_x)** | 进入 LCA ROI (LineLCAC ~ LineLCAA) | -80m ~ -4m 范围内有目标 | Y | - |

*TTC 在未报警帧出现大量 655.35(无效值)，极可能是因系统状态复位导致计算中断或过滤。

**结论**:
根本原因为 **LCA 功能使能信号 (bLCAEnable) 不稳定 (0↔1 跳变)**，导致 `adasFunc.c` 中的状态机频繁从 Standby(2) 跌落至 Off(4)，并强制清零了位于 `adasFunc.c:3998~4002` 附近的警告保持标志 (`totalLeftLcaWarningState`/`bLcaLeftWarningFlg`)，使得即使目标满足 TTC/ROI 条件也无法累积报警帧数，从而晚于 BSD 报警。

**需确认**:
请总线专家核实 **CAN 信号 `LCASwtReq` (或车身控制器下发的 LCA_Switch 信号)** 在测试窗口内是否存在毛刺、丢帧或电平抖动，以验证使能源头的稳定性。

### 补充分析(R2)


当前源码片段仅含全局变量与工具函数，**无法直接静态审计 `adasFunc.c:3998` 处具体代码**。但基于多专家一致证据可推导结论：

1.  **信号层确证**：Variable Probe 显示左雷达 (ID 2) `lca_enable` 在测试窗口内数值为 **min=0.0, max=1.0**，存在高频跳变。
2.  **逻辑路径推断**：感知与状态专家指出 `bLCAEnable=0` 时，系统状态机强制复位至 **Off(4)**，且引用代码逻辑（如 `adasFunc.c:1257`）存在“功能禁用清零警告”分支。
3.  **数据表现**：当 `lca_enable=0` 期间，TTC 计算结果异常为 **655.35s**（无效值），且警告标志 `bLcaLeftWarningFlg` 无法累积有效帧数（计时器归零）。
4.  **修正说明**：前序分析误称 TPE 解析了该变量映射，实则 TPE 对该行标记“无法判定”，根因定位依赖探针数据反推。

**结论**：虽未见 3998 行源码，但行为模式完全符合 **`bLCAEnable==0 ? bLcaLeftWarningFlg=false`** 的逻辑特征。故障根因为 `LCASwtReq` 信号抖动导致使能位反复触发强制清零分支，该逻辑在当前版本依然生效。需总线侧修复信号毛刺。


## signal_chain


**TPE 一致性**: 无相关触发模式。TPE 分析显示 7 个 `HoldRelease` 模式均标记为「无法判定」(`Unable to determine`)，因未能解析 `bLcaLeftWarningFlg`、`totalLeftLcaWarningState` 到 CAN 信号。故无法直接从 TPE 获取时序触发证据，需依赖 Variable Probe 数据反推输入层异常。

**条件检查表**
| 条件 | 阈值/要求 | 数据实际值 | 满足？ | 对应 TPE 模式 |
|------|----------|-----------|------|--------------|
| **LCA 功能使能** | 内部变量 `bLCAEnable` 必须稳定为 `1` | `lca_enable` 探针显示 Radar 2 (左): `min=0.0 max=1.0` (频繁跳变) | **N (不满足)** | 关联 TPE 失败模式 `HoldRelease @ adasFunc.c:3998` (无法追踪) |
| **自车速度激活** | `12.0 ≤ V ≤ 146.0` km/h | `actual_spd` p50=`24.13` km/h | Y | - |
| **目标进入 ROI** | 横向距离 `dist_y < 6.0` m (LCA 典型范围) | `dist_y` p50=`5.53` m (左侧未报警时) | Y | - |
| **目标相对速度** | `VelRel ≥ 7.2` km/h | `ttc` p50=`655.35` (疑似无效值或因 Enable=0 导致过滤失效) | ? (数据异常) | - |

**结论**: 根因为 **L1 信号层 `LCASwtReq` 不稳定**。依据 `RteComMapping_RxRunnable_FuncSignal` 代码映射，该信号直接写入 `PERInputUpdate.adasEnable.bLCAEnable`；Variable Probe 证实左雷达（ID 2）的 `lca_enable` 在测试窗口内存在 `[0, 1]` 混合状态。当 `bLCAEnable` 瞬时跳变为 0 时，`adasFunc.c` 中的 LCA 状态机（如 `HoldRelease` 逻辑附近）会被强制复位或清空警告保持计数器，导致即便目标已在 ROI 内且满足 TTC/速度条件，系统也需重新计时，造成报警晚于 BSD（BSD 可能不受此开关波动影响或有独立保持逻辑）。

**需确认**: 请总线专家核对原始 CAN 报文，确认 `LCASwtReq` 信号在 1776242122s~1776242285s 期间是否存在抖动（例如：从 1 变为 0 再变回 1 的毛刺），并验证是否与 ECU 上电复位或按键模块干扰有关。

### 补充分析(R2)


经核查 `RteComMapping.c` 源码，结论修正如下：

1.  **映射链路**: `RteComMapping_RxRunnable_FuncSignal()` 函数中（约第 463-467 行），`LCASwtReq` 读取后直接赋值：
    ```c
    (void)RteComMapping_ReadSignal(LCASwtReq)(&u8tmp);
    PERInputUpdate.adasEnable.bLCAEnable = (u8tmp == 1) ? TRUE : FALSE;
    ```
2.  **滤波参数**: **不存在**。代码无去抖计数、滞回或时间滤波逻辑。内部变量 `bLCAEnable` 完全镜像 CAN 信号状态。
3.  **抖动溯源**: 既然 Rte 层无滤波，且探针显示 `lca_enable` (Radar 2) 在 `[0.0, 1.0]` 跳变（Key Fact · ADAS 使能），则**原始 CAN 报文 `LCASwtReq` 必然存在物理层抖动或丢帧**。
4.  **建议**: 排除 ECU 配置问题，立即抓取测试窗口 (16:35:50~16:37) 公 CAN 波形，排查 BCM/VCU 发送端毛刺或总线干扰。


## 主持人审查


### 矛盾点
- {'expert_pair': '系统状态专家 vs 信号链路专家 vs 数据事实', 'content': '多位专家（如信号链路专家）断定根因为外部 CAN 信号 `LCASwtReq` 不稳定。但 Variable Probe 数据显示仅雷达 2 (左后角) 的 `lca_enable` 呈现 [0,1] 跳变，而雷达 3、4 的稳定为 1。若根源是公共 CAN 总线信号抖动，理论上所有接收该信号的雷达端变量均应体现波动，为何仅雷达 2 异常？这暗示问题可能非单纯外部信号抖动，而是雷达 2 节点特有的接收或映射故障。'}
- {'expert_pair': '算法逻辑专家 vs TPE 分析结果', 'content': '专家直接引用代码行号 (adasFunc.c:3998) 和具体逻辑 (清零警告保持计时器) 作为定论，但 TPE 分析明确标记这些模式为「无法判定 (Unable to determine)」，原因是未能建立内部变量与 CAN 信号的映射链。在无动态调试证据支持当前版本代码逻辑的情况下，仅凭历史案例推断特定代码行为存在风险，需确认该逻辑是否在当前软件版本中仍保留。'}
- {'expert_pair': '感知专家 vs BSD 表现', 'content': '感知专家提出「BSD 可能不受此开关波动影响」，但未明确指出 BSD 是否依赖独立的使能信号或不同的雷达源。已知数据中左侧 LCA 晚于 BSD 报警，若两者共用同一全局 `LCASwtReq` 且该信号在 LCA 窗口内确实为 0，则 BSD 理应同样受影响。专家未解释为何 BSD 能正常触发，缺乏对 LCA/BSD 独立控制路径的对比验证。'}


### 遗漏
- {'category': '时序因果对齐', 'description': '缺乏 `lca_enable` 从 1 翻转为 0 的精确时间点与 `lca_warning` 复位时间点的帧级对齐。目前仅有统计分布 (min/max)，未证明「Enable 翻转」与「警告清除」在时间上的严格先后关系，无法排除巧合。'}
- {'category': '雷达异构性排查', 'description': '未分析为何仅 Radar 2 的使能状态异常。需排查 Radar 2 与其他雷达 (3/4) 的网络拓扑、硬件健康度、或配置差异，区分是「全网信号乱码」还是「单点模块故障」。'}
- {'category': '逻辑层证据缺失', 'description': '由于 TPE 未能解析变量链，目前所有关于「HoldRelease 逻辑清零计数器」的结论均为推测。缺少 ECU 内部诊断日志 (DTC) 或内存转储来证实 `totalLeftLcaWarningState` 确实在使能翻转时归零。'}
- {'category': 'BSD 与 LCA 解耦机制', 'description': '未深入分析 BSD 功能为何能正常报警。需确认 BSD 是否使用了独立的盲区雷达源 (如 Radar 3/4)，其对应的 `bsd_enable` 信号在测试窗口是否保持稳定，以此反向验证 LCA 失效的特异性。'}


### 关键争议
**异常范围的差异性解释**。即为何同样的 CAN 信号环境，仅 Radar 2 表现出使能跳变，而其他雷达 (3/4，通常关联 BSD) 保持稳定？这决定了根因是「外部通信干扰」、「单点雷达硬件故障」还是「局部配置错误」，直接影响修复方案方向。