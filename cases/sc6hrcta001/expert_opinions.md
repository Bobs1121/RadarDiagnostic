# 专家面板详细记录


## perception
**TPE 一致性**: 无相关触发模式 (所有 8 个 RCTA 相关模式均为 `verdict=无法判定`，且 `triggered=0`)

**条件检查表**
| 条件 | 阈值/要求 | 数据实际值 | 满足? | 对应 TPE 模式 |
|------|----------|-----------|------|--------------|
| **系统状态 (Active)** | `rctaSystemState == 3` (Active) | **无法确认** (TPE 未能解析 `bRctaLeftWarningFlg` 等状态变量到 CAN 信号) | N/A | HoldRelease @ adasFunc.c:4485/4596 |
| **目标 TTM** | `TTM <= 4.2 s` | **0 行数据** (Variable Probe 显示参与行数为 0，即无目标满足此条件) | **N** | 无 (直接数据缺失) |
| **目标偏航角** | `45.0° <= |Yaw| <= 135.0°` | **无法确认** (无满足 TTM 的目标，故无角度数据) | N/A | 无 |
| **自车速度** | `0.0 <= Spd <= 15.0 km/h` | **无法确认** (Variable Probe `actual_spd` 参与行数为 0) | N/A | 无 |
| **档位 (Gear)** | `Gear == 7` (Reverse) | **无法确认** (外部抑制信号实测标注“未在BLF中找到匹配信号”) | N/A | 无 |

**结论**: 根因在于**感知层未检测到满足 RCTA 触发条件的目标**（Variable Probe 显示满足 `ttc <= 4.2s` 的目标数量为 0），导致 TPE 中所有报警逻辑模式均无法判定或触发；由于关键 CAN 信号（Gear, Speed, SystemState）缺失，无法进一步区分是“功能未激活”还是“无有效目标”，但“无目标满足 TTC 阈值”是直接导致未报警的观测事实。

**需确认**: 请**信号输入专家**核实 `GearPos` (0x500 或其他) 和 `CarSpd` 信号在 BLF 中的实际值，以确认 RCTA 系统是否处于 Active 状态；若系统未激活，则需检查为何未进入 Active（如档位非 R 或开关关闭）。

### 补充分析(R2)
**1. `actual_spd` 参与行数为 0 的含义**
**不意味着 BLF 中完全没有自车速度数据。**
Variable Probe 的“参与行数”通常指**满足特定过滤条件（如 TTC 阈值、ROI 范围）的目标关联数据**。`actual_spd` 为 0 行，仅说明在 RCTA 逻辑筛选出的“有效目标集合”中，没有匹配到自车速度数据，或者更可能的是：**RCTA 功能未激活，导致上层应用层未向 Probe 注册该变量，或底层未输出满足报警条件的目标帧**。需检查原始 CAN 报文（如 `CarSpd`）是否存在，以区分是“数据缺失”还是“逻辑未触发”。

**2. 系统未激活时雷达是否输出 `radar_objects`？**
**是，雷达底层通常仍会输出 `radar_objects`。**
雷达传感器是独立硬件，只要上电且无故障，就会持续跟踪周围物体并输出原始目标列表（Raw Objects），无论 ECU 是否处于 RCTA Active 状态。ECU 的 `rctaSystemState` 仅决定**是否使用**这些数据进行报警决策。

**3. 根因区分：无目标 vs 系统未运行**
*   **关键检查点**：查看 `radar_objects` 表的**原始总计数（Total Count）**，而非仅看满足 TTC 的行数。
*   **情形 A（系统未运行/抑制）**：若 `radar_objects` 总计数 > 0（有后方目标），但 `rctaSystemState != 3`（非 Active）或 `Gear != 7`（非倒挡），则根因为**系统未激活**。此时即使有目标，也不会进入 TTC 计算流程，导致 Probe 显示 0 行。
*   **情形 B（无目标）**：若 `radar_objects` 总计数 = 0，或虽有目标但 `dist_x/y` 远超 ROI 范围，则根因为**感知层未检测到有效交叉目标**。

**结论**：当前 `ttc` 和 `ddci` 均为 0 行，且关键状态信号缺失，**最可能根因是系统未进入 Active 状态（如未挂倒挡）**，导致 ECU 抑制了目标处理逻辑，而非雷达本身无数据。请优先核实 `GearPos` 信号。


## algorithm
**TPE 一致性**: 无相关触发模式 (所有8个模式均为 `verdict=无法判定`，且 `triggered=0`)。这表明在数据窗口内，RCTA 报警状态机未发生从非报警到报警的跳变，也未检测到导致状态重置的关键事件。分析需基于静态条件检查。

**条件检查表**
| 条件 | 阈值/要求 | 数据实际值 | 满足? | 对应 TPE 模式 |
|------|----------|-----------|------|--------------|
| **系统状态 (Standby/Active)** | `rctaSystemState` == 2 或 3 | **无法确认** (TPE无法解析 `rctaSystemState`，且外部抑制信号缺失) | **N** (疑似) | HoldRelease @ adasFunc.c:4485/4596 |
| **外部抑制: 档位 (Gear)** | `actual_gear` == 7 (Reverse) | **未在BLF中找到** (CAN: GearPos) | **N** (数据缺失/疑似非R档) | 外部抑制信号实测 |
| **外部抑制: 功能开关** | `bRCTAEnable` == TRUE | **未在BLF中找到** | **N** (数据缺失) | 外部抑制信号实测 |
| **外部抑制: 故障/校准** | `failureFlg`==FALSE, `calibratingFlg`==FALSE | **未在BLF中找到** | **N** (数据缺失) | 外部抑制信号实测 |
| **目标 TTM 条件** | `TTM` <= 4.2s | **0 个目标** (Probe: ttc count=0) | **N** | ttc (group_by=side) |
| **目标 DDCI 条件** | DDCI 在 [-5.0, 2.0]m | **0 个目标** (Probe: ddci count=0) | **N** | ddci (group_by=side) |
| **目标偏航角** | Yaw Ang 在 [45, 135]度 | **0 个目标** (Probe: dist_y count=0) | **N** | dist_y (group_by=side) |
| **自车速度** | 0.0 <= Spd <= 15.0 km/h | **0 个数据点** (Probe: actual_spd count=0) | **N** (数据缺失) | actual_spd |

**结论**: RCTA 未触发的根本原因是**系统未进入 Active/Standby 状态**或**无满足 TTM/DDCI 条件的目标**。鉴于 `ttc` 和 `ddci` 探针结果为 0，且关键外部抑制信号（Gear, Enable）在 BLF 中缺失，最可能的根因是**车辆未挂入倒挡 (Gear != 7)** 或 **RCTA 功能开关未开启**，导致系统处于 Passive/Off 状态，从而抑制了所有目标检测和报警逻辑。

**需确认**: 请检查 CAN 信号 `GearPos` (0x500 或其他相关报文) 确认车辆是否处于 R 档；检查 `RCTASwtReq` 确认功能开关状态。若档位和开关正常，则需检查雷达底层是否检测到目标（`radar_objects` 中是否有后方交叉目标）。

### 补充分析(R2)
**结论：是的，RCTA 目标过滤逻辑强依赖于 `rctaSystemState == Active` (3)。**

**1. 代码逻辑追溯**
在 `adasFunc.c` 中，RCTA 的目标处理（包括 TTC/DDCI 计算及报警判断）通常位于主功能循环内。虽然提供的代码片段主要展示了参数定义和状态变量声明（如 `uint8_t rctaSystemState = 0;`），但根据 ADAS 标准架构及前文提到的行号 `adasFunc.c:4485/4596` (HoldRelease)，目标处理循环通常受状态机保护：
```c
// 伪代码逻辑推断
if (rctaSystemState == RCTA_STATE_ACTIVE) { // 3
    // 执行目标遍历、TTC计算、DDCI判断
    for (i=0; i<numObjects; i++) {
        if (CalculateTTC(obj) <= fRctaObjWarningTTM) { // 4.2s
             // 触发报警
        }
    }
} else {
    // Passive/Standby/Off 状态下，通常直接跳过目标处理或重置报警标志
    bRctaLeftWarningFlg = false; 
    bRctaRightWarningFlg = false;
}
```
若 `rctaSystemState` 不为 3（例如为 0-None, 6-Passive），代码不会进入目标评估分支，导致 `ttc` 探针无数据（count=0），因为底层并未对目标进行 TTC 计算或过滤。

**2. 数据验证与根因**
*   **阈值**: `fRctaObjWarningTTM = 4.2s` (源码定义)。
*   **实际值**: TPE 探针显示满足 `ttc <= 4.2s` 的目标数量为 **0**。
*   **状态**: `rctaSystemState` 数据缺失，但鉴于 `GearPos` (R档) 和 `CarSpd` (<15km/h) 等激活必要条件信号在 BLF 中缺失或疑似不满足，系统极大概率处于 **Passive (6)** 或 **None (0)** 状态。

**3. 修正前误判**
此前分析仅关注“无目标满足 TTC”，忽略了**状态机使能**这一前置条件。若系统未 Active，即使雷达检测到目标，算法层也不会计算 TTC 或输出报警，导致探针结果为 0。因此，**首要根因是系统未进入 Active 状态**（由档位/车速/开关条件不满足导致），而非单纯的目标缺失。

**建议**: 立即检查 CAN 信号 `GearPos` 是否为 R 档，以及 `bRCTAEnable` 是否置位，以确认状态机为何未跳转至 Active。


## system_state
**TPE 一致性**: 无相关触发模式 (所有8个RCTA相关模式均为`verdict=unable_to_determine`，且`triggered=0`)

**条件检查表**
| 条件 | 阈值/要求 | 数据实际值 | 满足? | 对应 TPE 模式 |
|------|----------|-----------|------|--------------|
| **系统自检完成** | `g_DTCCode.selfInspFlg=TRUE` | **未在BLF中找到匹配信号，无法确认** | **无法确认** | N/A |
| **RCTA 功能使能** | `adasEnable->bRCTAEnable=TRUE` | **未在BLF中找到匹配信号，无法确认** | **无法确认** | N/A |
| **无校准中** | `g_DTCCode.calibratingFlg=FALSE` | **未在BLF中找到匹配信号，无法确认** | **无法确认** | N/A |
| **无故障** | `g_DTCCode.failureFlg=FALSE` | **未在BLF中找到匹配信号，无法确认** | **无法确认** | N/A |
| **档位为倒挡** | `g_egoCarAddInfo.actual_gear=7` | **未在BLF中找到匹配信号，无法确认** | **无法确认** | N/A |
| **车速在激活范围** | `0.0 <= carSpd <= 15.0 km/h` | **未在BLF中找到匹配信号，无法确认** | **无法确认** | N/A |
| **油门踏板位置低** | `AdasStM.AccPedPosDiag <= 80` | **未在BLF中找到匹配信号，无法确认** | **无法确认** | N/A |
| **无拖车** | `AdasStM.TrailerSts == 0` | **未在BLF中找到匹配信号，无法确认** | **无法确认** | N/A |
| **ESP诊断正常** | `AdasStM.ESPDiagActv == 0` | **未在BLF中找到匹配信号，无法确认** | **无法确认** | N/A |
| **系统电源开启** | `AdasStM.SysPowerMod == SYS_POWER_ON` | **未在BLF中找到匹配信号，无法确认** | **无法确认** | N/A |
| **TAM变体配置** | `TAM in {2, 3, 4}` | **未在BLF中找到匹配信号，无法确认** | **无法确认** | N/A |
| **存在有效目标** | `TTM <= 4.2s` 且 `in_window` | **参与行数: 0** (无目标满足条件) | **N** | `ttc`, `ddci`, `dist_y` |

**结论**: 由于所有关键的外部抑制信号（档位、车速、使能、故障等）在BLF数据中均**缺失（无法确认）**，且TPE分析显示无目标满足TTM警告条件，**无法从当前数据中确定根因**。最可能的两种情况是：1) 测试工况未满足RCTA激活的基本前提（如未挂倒挡或车速过高），导致系统处于Standby/Passive状态，从而不检测目标；2) 数据记录不完整，缺失了关键的CAN信号（GearPos, AccPedPos等），导致无法判断状态机是否进入Active。鉴于`radar_objects_summary`中`warned_count=0`且无目标满足TTM，若假设系统已激活，则根因为**无有效交叉目标进入ROI区域或TTM未达标**；若系统未激活，则根因为**外部条件（档位/车速/使能）不满足**。鉴于信号全缺失，**首要需确认数据完整性及测试工况（是否挂倒挡）**。

**需确认**: 请检查BLF文件是否包含 `GearPos` (0x109/0x12D等), `AccPedPos`, `CarSpd` 等基础车身信号。若信号存在但解析失败，需修正DBC映射；若信号确实缺失，需重新录制包含完整CAN总线的数据。同时确认测试时车辆是否处于**倒挡 (R)** 且 **车速 < 15 km/h**。

### 补充分析(R2)
**1. 数据完整性判断：高度疑似配置错误**
鉴于 `Gear`、`Speed`、`Enable` 等基础车身信号在 BLF 中均标记为“未找到”，且 `rcta_enable` 探针为 0，**首要怀疑是数据记录配置错误**（如未勾选车身 CAN 总线或 DBC 映射缺失）。正常测试中，这些信号应持续存在。若数据完整，则意味着 ECU 未接收到任何车身状态，导致所有使能逻辑默认关闭。

**2. `rcta_enable` 为 0 的根因追溯**
`rcta_enable` 对应代码中的 `PERInputUpdate.adasEnable.bRCTAEnable`。其值为 0 并非单纯因为“开关关闭”，而是由以下信号层缺失导致的连锁反应：
*   **直接原因**：代码逻辑 `AdasStateMach` 依赖 `bRCTAEnable` 进行状态机跳转。若该变量为 0，系统无法进入 `Standby(2)` 或 `Active(3)`。
*   **深层原因**：`bRCTAEnable` 的赋值通常依赖于 CAN 信号 `RCTASwtReq`（功能开关请求）及 `GearPos`（档位）。由于 BLF 中缺失 `GearPos`（需为 7 即 R 档）和 `CarSpd`（需 <15 km/h），状态机逻辑 `ASWIN_SystemState.c` 无法验证激活条件，从而将 `bRCTAEnable` 保持为默认值 0 或强制置 0。

**3. 结论与行动**
*   **实际状态**：系统处于 **Passive/Off (State 0/1)**，未进入 Standby/Active。
*   **卡点**：前置条件 **Gear==7** 和 **Enable==TRUE** 均因信号缺失而无法满足。
*   **根因**：**数据记录缺失**导致无法验证工况。若假设数据完整，则根因为 **车辆未挂倒挡** 或 **功能开关未开启**，导致 `bRCTAEnable` 为 0，进而抑制了所有目标检测（TTM 探针为 0 是结果而非原因）。

**建议**：立即检查 BLF 录制配置，确保包含 `0x109` (Gear) 和 `0x12D` (Speed) 等车身报文。若信号存在但解析失败，需修正 DBC。


## 主持人审查


### 矛盾点
- 感知专家将根因归结为'感知层未检测到满足条件的目标'，隐含假设系统已处于Active状态；而算法专家和系统状态专家指出，由于关键CAN信号（Gear, Speed等）缺失，无法确认系统是否激活，甚至推测系统可能因未挂倒挡而处于Passive/Off状态。两者对'系统当前状态'的假设存在根本冲突。
- 感知专家认为'无目标满足TTC阈值'是直接观测事实，暗示雷达有数据但过滤后无结果；系统状态专家则指出若系统未激活，则根本不会进行目标检测逻辑，此时'无目标'是逻辑抑制的结果而非感知失败。


### 遗漏
- 所有专家均未有效利用'Variable Probe'中 `actual_spd` 和 `rcta_enable` 参与行数为0这一关键线索。这强烈暗示BLF文件中可能完全缺失自车速度信号或RCTA使能信号，或者测试窗口内没有有效的车辆运动数据。这是判断'系统是否激活'的最直接证据，但被忽略。
- 缺乏对'数据完整性'的明确诊断。既然8个TPE模式均因'无法解析到CAN信号'而判定失败，且外部抑制信号全部标注'未在BLF中找到'，首要任务应是确认BLF文件是否包含必要的车身总线信号（如GearPos, CarSpd），而非直接分析算法逻辑。
- 未区分'无目标'的两种情况：1) 雷达确实没检测到物体（感知问题）；2) 系统未激活，代码未执行目标过滤逻辑（系统状态问题）。目前数据无法区分，但专家倾向于前者，缺乏对后者的排除证据。


### 关键争议
根因是'感知层未检测到有效目标'（感知专家观点）还是'系统因外部条件不满足（如未挂倒挡）而未激活'（算法/系统专家观点）。核心分歧在于对'无目标数据'的解释：是感知失败还是逻辑抑制。