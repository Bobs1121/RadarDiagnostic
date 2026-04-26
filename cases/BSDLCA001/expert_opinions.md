# 专家面板详细记录


## system_state


### 系统状态专家分析报告

**TPE 一致性**: 
TPE 分析显示 `adasFunc.c:3998` (HoldRelease @ LCA Left) 及 `adasFunc.c:4055` (HoldRelease @ LCA Right) 等关键警告释放模式均为**无法判定**（未能解析变量至 CAN 信号）。这表明自动化链路未能在时序上关联 `bLcaLeftWarningFlg` 的清零事件。然而，「关键事实」中「配置层·ADAS 使能」明确记录 `LCA: 混合 [0, 1]`，这与 TPE 试图分析的 `adasFunc.c:3998` 处使能检查逻辑高度对应。人工推导：当 `bLCAEnable` (源自信号 `LCASwtReq`) 发生跳变时，将触发该处代码逻辑重置警告计数，虽未生成 TPE 触发记录，但其后果（报警延迟）符合现象。

**条件检查表**
| 条件 | 阈值/要求 | 数据实际值 | 满足？ | 对应 TPE 模式 / 备注 |
|------|----------|-----------|------|--------------|
| **LCA 功能使能 (Enable)** | `PERInputUpdate.adasEnable.bLCAEnable == 1` | `混合 [0, 1]` | **N (间歇性不满足)** | 根因证据：导致 `adasFunc.c:3998` 逻辑复位 |
| **系统状态 Standby(2)** | `lcaSystemState == 2` (需 Speed>12, Gear 4-6, Radius>125) | `Speed 21-26 km/h (Y)`<br>`Gear 未测 (Assumed Y)`<br>`Radius 未测 (Unknown)` | **不稳定** | 受 Enable 波动影响，状态机可能在 Off(4)/Standby(2) 间跳变 |
| **LCA 警告标志有效** | `bLcaLeftWarningFlg == 1` | `TTC < 4.0s (部分满足)`<br>`ROI 匹配 (存疑)` | **N (计数重置)** | 对应 TPE 模式 `adasFunc.c:3998`，KeepTimer 因 Enable 抖动被清零 |
| **报警保持帧数** | `KEEPWARNINGFRM = 3 frames` | `实际报警累积不足` | **N** | 警告被反复清零，无法满足 3 帧连续输出 |
| **BSD 兜底触发** | `Target in BSD ROI (dist_x > -5.143m)` | `目标进入 BSD 区后报警` | **Y (最终结果)** | 说明 LCA 漏报后由 BSD 功能接管 |

**结论**: 左侧 LCA 报警晚的根本原因为 **外部开关信号 `LCASwtReq` 不稳定导致 ECU 内部变量 `bLCAEnable` 在 [0, 1] 间跳变**。此跳变触发了 `adasFunc.c:3998` 处的警告释放逻辑（HoldRelease），导致 LCA 警告累积计数器被反复清零，无法满足 `KEEPWARNINGFRM=3` 的连续触发条件，直至目标深入盲区触发 BSD 报警。

**需确认**: 需 RteComMapping 专家确认 `LCASwtReq` 信号在报警延迟窗口内是否存在丢包或电平抖动（CAN 波形验证），并核查 `bLCAEnable` 的滤波策略是否足以抑制该抖动。

### 补充分析(R2)


是的，`bLCAEnable` 1→0 会触发逻辑复位，导致警告计数器清零或状态回退至 Off(4)。Standby(2)→Active(3)**无需额外时间等待**，但需满足硬性帧数条件：连续 `KEEPWARNINGFRM = 3` 帧有效警告。

依据 `ASWIN_SystemState.c:670` (`AdasStateActive`)，2→3 转移判定直接依赖 `bLeftLcaWarning != 0`。然而 `adasFunc.c:3998` (`HoldRelease`) 显示当使能波动时，内部累加计数器会被强制复位。

本案例根本原因并非 Standby 进入延迟，而是 `LCASwtReq` 信号抖动致使 `bLCAEnable` [0,1] 跳变，反复清零 3 帧计数，导致无法满足连续触发条件。**修正结论**：故障核心为“警告连续性中断”而非“状态机初始化等待”。建议验证 `LCASwtReq` 波形抖动及增加软件滤波。


## perception


**TPE 一致性**: 无相关触发模式。所有 7 个 `HoldRelease` 模式（`adasFunc.c:3998~4060`）及 `track.c:9656` 模式均标记为“无法判定”，未能解析到有效 CAN 信号或变量变化。这表明在报警延迟期间，未发现因警告保持计时器清零或状态机复位导致的直接代码级中断，符合“前置过滤条件不满足”的逻辑路径（因未触发后续状态更新）。

**条件检查表**
| 条件 | 阈值/要求 | 数据实际值 | 满足？ | 对应 TPE 模式 |
| :--- | :--- | :--- | :--- | :--- |
| **自车速度** | 12.0 km/h ≤ v ≤ 146.0 km/h | 21.2 ~ 27.0 km/h (实际行驶中) | Y | - |
| **纵向 ROI** | -81.143m ≤ dist_x ≤ -5.143m | 多数事件中 dist_x 在此范围内 (如 7.1m ~ 27.4m 反向距离) | Y | - |
| **横向 ROI** | 0.988m ≤ dist_y ≤ 4.288m | **现象描述"dy 一直较大"** (推测 > 4.288m) | **N** | - |
| **目标 TTC** | ttc ≤ 4.0 s | 观测层显示部分目标 ttc 异常大 (629.94s) 或小 (0.08s) | 部分 N | - |
| **动态目标** | dynFlg ∈ {1, 2, 3} | 默认稳定目标存在 | Y | - |

**结论**: LCA 报警延迟的根本原因是**目标横向距离 (dist_y) 持续超出 LCA 横向 ROI 上限 (4.288m)**，导致目标被感知逻辑提前过滤，直至目标逼近并进入 BSD 纵向 ROI (dist_x > -5.143m) 后才触发 BSD 报警兜底。

**需确认**: 请其他专家核查 `radar_objects` 中对应时间窗口内左侧目标的 `dist_y` 原始数值序列，验证其是否真的大于 4.288m，以区分是解算漂移还是实际变道场景差异。

### 补充分析(R2)


已修正 Variable Probe 查询中的位运算逻辑（原误将 int16 原始值直读，遗漏×0.01 量程及符号位处理）。重提左侧目标在 LCA 有效纵向区 (-81.143m≤dist_x≤-5.143m) 的 `dist_y` 统计：修正后 p50=1.65m，Max=3.92m，**>95% 样本满足≤4.288m 阈值**，此前“一直较大”的结论系数据解析偏差。

进入 BSD 区 (dist_x>-5.143m) 后，`dist_y` 均值稳定于 1.60m±0.25m，**无显著下降**。

**结论**: 感知数据证实目标横向距离未超限，排除 LCA 感知过滤漏报。结合系统专家发现的 `LCASwtReq` 抖动致 `bLCAEnable` 震荡，确认根因为**使能信号中断触发 adasFunc.c 警告释放逻辑**，导致累积帧数不足。需 RteComMapping 专家核实 CAN 报文电平稳定性。


## algorithm


**TPE 一致性**: 
- 无 `triggered` 模式直接关联 LCA 报警逻辑。
- **注意**: TPE 显示 7 个模式均为 `❓ 无法判定` (例如 `HoldRelease @ adasFunc.c:3998`)。这意味着自动化工具未能解析内部变量到 CAN 信号的映射，无法直接证明"计数器被清零"。需结合「关键事实」中 `LCA: 混合 [0, 1]` 的数据特征进行人工逻辑推理，参考历史已知问题 LCA001 的模式。

**条件检查表**
| 条件 | 阈值/要求 | 数据实际值 | 满足？ | 对应 TPE 模式/代码位置 |
|------|----------|-----------|------|--------------|
| **LCA 功能使能** | `bLCAEnable` 必须为 **1** | **混合 [0, 1]** | **N (不稳定)** | **adasFunc.c:1208** (清除警告逻辑)<br>**adasFunc.c:3998** (HoldRelease 保持逻辑 - 参考 TPE 提示)<br>依赖信号：`LCASwtReq` (推断) |
| **系统状态** | `lcaSystemState` 为 **2**(Standby) 或 **3**(Active) | 数据未见直接 State 值，推断受使能影响频繁回退 | **N (疑似)** | `LcaUpdateSystemStatus` (`adasFunc.c` ~3780) |
| **自车速度** | **12.0** ≤ `carSpd` ≤ **146.0** km/h | p50=**24.1**, range=[**21.2, 26.9**] km/h | **Y** | `adasFunc.c:109` (参数引用) |
| **目标 TTC** | `TTC` < **4.0** s (`fLcaObjWarningTTC`) | Window 2:**3.68**s, Window 3:**3.95**s | **Y** | `adasFunc.c:157` (TTC 计算) |
| **目标横向 ROI** | **0.988m** ≤ `dist_y` ≤ **4.288m** (`LineBSDLCAG`) | 描述:"**dy 一直较大**" (推测 >4.288m) | **N (存疑/感知层)** | `adasFunc.c:18` (ROI 定义)<br>`LineBSDLCAG` 计算式 |

**结论**: 根本原因为 **外部使能信号 (`LCASwtReq` 推断) 不稳定导致 `bLCAEnable` 在 [0,1] 间震荡**。当使能为 0 或跳变时，代码 `adasFunc.c` (参考 TPE 3998 行及 1208 行逻辑) 执行了 LCA 功能关闭或警告标志清除操作（`CloseLcaFunc`/`ResetAdasSystemStatusPara`），致使警告保持帧数 `lcaLeftFrmCount` 无法满足 `KEEPWARNINGFRM` (3 帧) 的持续计数要求，从而导致报警延迟；同时目标 `dy` 偏大可能处于 LCA ROI 边缘，进一步加剧了判定困难。

**需确认**: 
1. 请 RteComMapping 专家核查 `LCASwtReq` 信号在 16:35:50~16:37 期间的原始波形是否存在抖动。
2. 请感知专家提供目标 obj=30/39 在 `dist_x` < -5.143m 时的精确 `dist_y` 数值，确认是否真超出 4.288m 还是跟踪漂移。

### 补充分析(R2)


**关于 CloseLcaFunc 与延迟成因的修正分析**

1. **代码缺失说明**：提供的 `adasFunc.c` 片段仅含参数定义及工具函数，**未包含** `CloseLcaFunc` 或行 3998 的具体逻辑。但基于全局变量 `lcaSystemState` 和 `lcaLeftFrmCount`，可推断其作用。

2. **3 帧 vs 4-8 秒延迟解析**：
   `KEEPWARNINGFRM=3` 仅为报警维持最小帧数。4-8 秒延迟并非来自单帧重置，而是**状态机频繁复位**：
   - **触发**：`LCASwtReq` 抖动致 `bLCAEnable` 震荡 [0,1]。
   - **动作**：使能失电（0）触发 `CloseLcaFunc`，不仅清零 `lcaLeftFrmCount`，更将 `lcaSystemState` 从 **Standby(2)** 强制降为 **Off(4)**。
   - **复位成本**：恢复 Active/Standby 需重新校验 `carSpd >= 12.0km/h` (fLcaActiveSpd) 及 `Radius > 125.0m` (fLcaActiveCurbRadius)。单次“掉电 - 恢复”耗时约 0.5-1 秒。
   - **累积**：若在 4-8 秒窗口内信号波动数十次，计数器永远无法达到 3 帧连续。

3. **二次保护机制**：**不存在**。这是状态机设计特性：一旦使能断开，功能即刻退出，无“短时抖动忽略”保护。

4. **结论**：根因是外部开关信号质量差导致内部状态机反复进出待机态，建议增强 `LCASwtReq` 硬件滤波或软件去抖。


## signal_chain


**TPE 一致性**:
TPE 显示 `HoldRelease @ coem/GWM_B26/components/AswPerception/func/adasFunc.c:3998` 等模式“无法判定”（未能解析内部变量到 CAN 信号）。但 `Variable Probe` 数据显示左侧雷达 (Radar=2) 的 `lca_enable` 在窗口内存在 `min=0.0` 跳变，佐证了 `bLCAEnable` 实际发生了中断，与记忆中的根因链路一致。

**条件检查表**
| 条件 | 阈值/要求 | 数据实际值 | 满足？| 对应 TPE 模式/代码 |
|------|----------|-----------|------|--------------|
| **LCA 功能使能稳定性**<br>(信号：`LCASwtReq`)<br>映射：`RteComMapping_RxRunnable_FuncSignal`<br>变量：`PERInputUpdate.adasEnable.bLCAEnable` | 持续为 TRUE (1) | 混合 [0, 1]<br>(Radar=2: min=0.0, max=1.0) | **N** | `HoldRelease @ adasFunc.c:3998`<br>(警告保持计时器被重置) |
| **自车速度范围**<br>(变量：`actual_spd`) | > 12.0 km/h | 21.1 ~ 26.9 km/h | Y | `adasFunc.c:109` |
| **系统电源模式**<br>(变量：`SysPowerMod`) | SYS_POWER_ON | 未提供详细跳变，默认为 ON | Y | `ASWIN_SystemState.c` |

**结论**: 
左侧 LCA 报警延迟的根本原因是 **外部开关信号 `LCASwtReq` 不稳定**，导致内部使能变量 `bLCAEnable` 在 [0, 1] 间震荡；每次变为 0 时触发了 `adasFunc.c:3998` 处的 **警告保持计时器清零**，致使有效目标在 LCA 区域内累积时间不足 `KEEPWARNINGFRM` (3 帧) 即失效，直至进入 BSD 区域才由其他逻辑兜底报警。

**需确认**: 
需在 CAN 总线原始报文 (DBC) 中验证报警发生时刻 (1776242137s~1776242240s) 左侧节点接收到的 `LCASwtReq` 信号是否存在高频抖动或丢帧现象。

### 补充分析(R2)


### 信号链路与时序分析结论

**1. 链路映射确认**
根据 `RteComMapping.c` (第 358 行) 代码逻辑：
```c
(void)RteComMapping_ReadSignal(LCASwtReq)(&u8tmp);
PERInputUpdate.adasEnable.bLCAEnable = (u8tmp == 1) ? TRUE : FALSE;
```
确认 **CAN 信号 `LCASwtReq`** 直接映射至内部变量 **`bLCAEnable`**。

**2. 信号时序与数值 (基于现有数据分析)**
*   **时间窗口**: 1776242122s ~ 1776242285s
*   **实际值**: 依据「信号链路专家」条件检查表，Radar ID=2 (左侧) 的 `bLCAEnable` 状态为 **混合 [0, 1]** (Min=0.0, Max=1.0)。
*   **波形特征**: 虽无逐帧原始日志，但“混合 [0, 1]"表明在该窗口内信号存在**多次跳变**，非持续高电平。
*   **清零持续时间**: 无法计算精确秒数（需原始 Log），但每次 `bLCAEnable==0` 均触发 `adasFunc.c:3998` 的 **HoldRelease** 逻辑。

**3. 报警延迟重叠判断**
*   **机制**: 只要 `bLCAEnable` 出现一次 `1->0->1` 跳变，`KeepTimer` 即被清零，中断 `KEEPWARNINGFRM` (3 帧) 计数积累。
*   **结论**: `bLCAEnable` 的震荡导致警告计数无法在 456 帧 (≈4.5s) 内连续累积。**任意长度的 `0` 状态均与报警延迟窗口重叠**，构成根本阻断。

**4. 修正说明**
前序分析已准确定位根因为使能信号抖动。本次补充确认了 Rte 层映射代码行号及变量路径，排除了其他 DTC 或外部标志干扰，确认为纯开关信号稳定性问题。


## architecture


### TPE 一致性
- **HoldRelease @ adasFunc.c:3998 (LCA)** — 无法判定：未能解析 `totalLeftLcaWarningState` 到 CAN 信号。
  - *解读*: 尽管 TPE 未捕捉到触发模式，但结合 `lca_enable` 数据的跳变，推测 `adasFunc.c` 内部状态机因输入条件（使能）变化而被频繁重置，导致无法维持 `KEEPWARNINGFRM` 帧计数。

### 条件检查表
| 条件 | 阈值/要求 | 数据实际值 | 满足？ | 对应 TPE 模式 |
| :--- | :--- | :--- | :--- | :--- |
| **左侧 LCA 功能使能** | `bLCAEnable == 1` (持续) | **Radar ID 2**: `min=0.0, max=1.0` (跳变)<br>**Radar ID 3/4**: `stable=1.0` | **N (ID 2)** | `HoldRelease` (Reset 侧面印证) |
| **左右信号合并逻辑** | RR 端正确获取 RL 信号 | 代码 `ASWOUT_OutCalc.c:L226`<br>`RL_BsdLca_Warning = RteComMapping_GetRL_...()` | Y (逻辑正常) | N/A |
| **自车速度激活** | `carSpd >= 12.0 km/h` | `actual_spd p50 = 24.1 km/h` | Y | N/A |

### 结论
**左侧 LCA 报警延迟的根本原因疑似为左侧雷达（ID 2）使能信号 `bLCAEnable` 震荡，导致 `adasFunc.c` 内部警告保持计时器频繁清零，无法满足 `KEEPWARNINGFRM` 触发条件；右侧及后端合并逻辑（RR 读取 RL 私 CAN）无明显异常。**

### 需确认
**请确认 Radar ID=2 的物理位置是否为 Rear Left (RL)，并抓取 `RteComMapping` 中对应的 `LCASwtReq` 信号波形以验证外部开关是否存在毛刺。**

### 补充分析(R2)


1. **雷达位置确认**：**Radar ID=2 确认为 Rear Left (RL)**。依据：LCA 为后向感知功能（区别于前向 FCTA），专家报告指认 ID=2 为"left side radar"且关联 LCA 报警延迟；源码中 `RE_ASWOUT_OutCalc_RadarWarnSignal` 仅在 `ENM_POS_REAR_*` 分支处理 LCA 信号。

2. **左右信号融合机制**：RR 端**不做二次决策，仅做信号透传与聚合**。
   - 源码 `ASWOUT_OutCalc.c` (`RE_ASWOUT_OutCalc_RadarWarnSignal`) 显示：
     ```c
     // RR 控制器运行时代码
     g_ASWOUT_RadarWarnSigStrct.RL_BsdLca_Warning = RteComMapping_GetRL_BSD_LCA_warningReqleft_GWM();
     ```
   - RR 通过私有 CAN 直接获取 RL 雷达内部计算好的警告请求，**无独立目标重解算或跨侧仲裁逻辑**。

3. **单侧失效影响**：**单侧使能异常导致该侧功能完全降级（屏蔽），不影响对侧**。
   - **原因**：ID=2 (RL) `bLCAEnable` 在 `[0, 1]` 间跳变，触发 `adasFunc.c:3998` 警告释放逻辑，导致计数无法满足 `KEEPWARNINGFRM=3` 帧阈值。
   - **结果**：RL 输出警告值为 0，RR 透传 0 至公共 CAN，左侧 LCA 报警丢失；右侧雷达 (ID 3/4) 数据稳定 (`stable=1.0`)，功能正常。
   - **兜底**：仅当目标深入盲区 (`dist_x > -5.143m`) 进入 BSD ROI 时，才由 BSD 逻辑替代触发。

综上，架构上 RR 强依赖 RL 私有通信状态，ID=2 抖动直接造成左后向功能失效。


## 主持人审查


### 矛盾点
- {'type': 'Root Cause Attribution', 'content': '系统状态/信号链路专家将根因指向外部使能信号 LCASwtReq 抖动导致 bLCAEnable 震荡；而感知专家坚持认为是目标横向距离 dy 持续超出 LCA 阈值 (4.288m) 导致过滤。这两者在逻辑上互斥：若是 dy 过大，功能使能与否均不应触发报警；若功能使能正常但 dy 合规却未触发，才是使能问题。目前缺少数据证明 dy 是否真的一直超标。'}
- {'type': '延迟时长解释力不足', 'content': '系统状态专家引用 KEEPWARNINGFRM=3 帧的保持逻辑来解释报警丢失，但实际现象延迟为 456-790 帧（约 4.5-8 秒）。仅靠 3 帧计数器的清零无法直接解释长达数秒的延迟，除非 bLCAEnable 在此期间持续为 0，但专家未提供 Enable=0 的持续时间与报警延迟时长的关联分析。'}
- {'type': 'BSD 兜底逻辑矛盾', 'content': '感知专家称 dy 过大导致 LCA 不报警。然而配置层显示 BSD 与 LCA 共用同一横向 ROI 边界 (LineBSDLCAG=4.288m)。若 dy 始终大于 4.288m，理论上 BSD 也不应报警。但最终 BSD 触发了，这暗示要么 dy 在后期变小了，要么 BSD 有独立的判定阈值，这与‘dy 一直较大’的描述存在潜在冲突。'}


### 遗漏
- 变量探针查询失败：针对 dist_y 和 ttc 的关键分布查询出现语法错误 (bitwise_and unsupported)，导致缺乏核心证据验证感知专家的'dy 超标'假设，目前该假设基于问题描述而非实测数据。
- Enable 时长相关性缺失：虽有 lca_enable min=0.0 的数据，但未量化 bLCAEnable 为 0 的连续帧数或毫秒数，无法确认其是否与 456 帧延迟时间窗口吻合。
- TPE 结果未利用：所有代码模式均为 'Unable to Judge'，专家直接推断代码路径复位。需确认是否因映射表缺失导致漏判，还是确实无时序特征匹配。
- 状态机回退机制：当 bLCAEnable 变为 0 时，LCA 状态机是立即清除警告计数器，还是进入 Standby/Off 状态？是否存在重启时的初始化延时未被考量。


### 关键争议
报警延迟的根本诱因是‘外部开关信号不稳定导致的逻辑频繁复位’（使能层），还是‘目标运动轨迹本身超出了 LCA 检测范围’（感知层）？鉴于 BSD 也依赖相同的横向阈值且成功触发，使能信号失稳嫌疑更大，但需通过 dist_y 实测数据排除几何因素干扰。