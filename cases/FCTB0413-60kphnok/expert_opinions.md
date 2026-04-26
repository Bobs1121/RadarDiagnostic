# 专家面板详细记录


## perception


**TPE 一致性**: `HoldRelease` 模式在 `coem/GWM_B26/components/AswPerception/func/adasFunc.c:6378-6382` 被触发 (信号: `AEBBAActv_0x137`=0, `AEBIBActv_0x137`=0)。该模式副作用为清零 `bFctbKeepBrakeFlg`。这表明制动保持逻辑的释放条件已满足，但功能未进入激活状态导致无制动请求输出。数据中 AEB 信号全零，符合抑制条件。

**条件检查表**
| 条件 | 阈值/要求 | 数据实际值 | 满足？ | 对应 TPE 模式/代码位置 |
|------|----------|-----------|------|--------------|
| **功能使能** | `bFCTBEnable` == TRUE | `fctb_enable` = 0 (Global) | **No** | `ASWIN_SystemState.c` / GWM_EnableCond |
| **自车速度** | 0.5 ≤ V_ego ≤ 21.0 km/h | 标题 60kph (推测); Probe 无>22 记录 | **No** (场景冲突) | `fFctbActiveUpSpd` (21.0) |
| **档位状态** | Gear ∈ {D(4), R(5)} | `actual_gear` = 7 (N/P) | **No** | `GWM_FCTB_AdasEnableCond` |
| **目标 TTC** | TTM ≤ 1.5s (Warning) | 最小 79.97s (Max 655.35s) | **No** | `fFctbObjWarningBaseTTMX` |
| **目标距离** | ROI 内 (通常<20m) | 最小 36.28m (Max 257.0m) | **No** | `dist_x` / `dist_y` Filter |
| **外部抑制** | AEB BA/IB != 0 | `AEBBAActv_0x137` = 0 (100%) | **Yes** (抑制生效) | `adasFunc.c:6378` HoldRelease |

**结论**: 根本原因为**系统级功能禁用** (`fctb_enable`=0) 叠加 **车辆工况不满足** (档位 P/N、速度超限)，且雷达检测到的**目标威胁过低** (TTC 79s 远超 1.5s 阈值)，导致功能无法进入 Active 态及触发制动。

**需确认**: 测试脚本是否错误将 60kph 高速场景用于低速 FCTB 测试，或 `fctb_enable` 标定开关在测试前未被激活？

### 补充分析(R2)


**结论：此为雷达端原始数据虚警，非功能触发。**

1. **属性对比**：实测目标 **TTC=79.97s** 远超警告阈值 **1.5s**，距离 **36.28m** 超出 FCTB 典型作用域（<20m）。物理上无碰撞威胁。
2. **标志定义**：`radar_objects` 中 `fctb_flag` 为**雷达端观测输出**，代表“该目标具备被识别特征”，而非 ECU 制动指令。即使置位，也仅代表雷达算法内部状态。
3. **抑制逻辑**：主机端因 `fctb_enable`=0（系统关闭）及 `actual_gear`=7（非 D/R 档），在状态机入口即阻断，未读取该标志进行制动计算。
4. **修正说明**：此前分析正确指出功能未激活原因为档位与开关。补充确认：日志中的 flag 置位是雷达独立计算的候选标记，不反映最终控制意图，无需视为标定错误。


## algorithm


**TPE 一致性**
- **模式名**: `HoldRelease`
- **时刻**: t=1776963417.63s (持续 77357ms)
- **文件行号**: `coem/GWM_B26/components/AswPerception/func/adasFunc.c:6378-6382`
- **副作用**: 清零 `bFctbKeepBrakeFlg`, `fFctbBrakeEventTime`, `fFctbHoldEventTime`
- **触发信号**: `ESP_FD2.AEBBAActv_0x137` (值=0), `ESP_FD2.AEBIBActv_0x137` (值=0)
- **一致性分析**: TPE 显示在测试窗口期间，由于 AEB 制动标志位为 0（未激活），触发了 FCTB 保压释放逻辑。这解释了为何即使有报警意图，制动请求也无法保持。但根本原因在于系统从未进入可触发制动的状态（`fctb_enable` 恒为 0）。

**条件检查表**
| 条件 | 阈值/要求 | 数据实际值 | 满足？ | 对应 TPE 模式 |
|------|----------|-----------|------|--------------|
| **功能使能** | `bFCTBEnable` == TRUE (1) | `fctb_enable` 全量 0.0 | **N** | 无 (基础门控失败) |
| **档位条件** | Gear == 4 (D) or 5 (R) | `actual_gear` = 7 (N/P) | **N** | 导致 `bFCTBEnable` 失效 |
| **自车速度** | 0.5 km/h <= Speed <= 21.0 km/h | `actual_spd` (>22km/h 段 0 帧，需确认 60kph 含义) | **N** (疑似) | - |
| **AEB 抑制释放** | `bAEBBAActiveFlg` == FALSE | `AEBBAActv_0x137` = 0 | **Y** | `HoldRelease` |
| **AEB 抑制释放** | `bAEBIBActiveFlg` == FALSE | `AEBIBActv_0x137` = 0 | **Y** | `HoldRelease` |
| **外部抑制 (MSR)** | `MSRActv` == 0 | `MSRActv_0x137` 偶发 1.2% | **N** (偶发) | - |

**结论**: FCTB 未触发的根本原因是**档位信号为 7 (N/P 档)，不满足功能激活所需的 D/R 档 (4/5)**，导致 `fctb_enable` 始终为 0；叠加测试场景车速可能超过 21km/h 限制，致使功能无法从 Init 状态转移至 Standby/Active 状态，后续 TPE 检测到的 `HoldRelease` 仅针对已激活后的保压逻辑，属于次要现象。

**需确认**: 请核对测试用例定义中"60kph"是指自车车速还是目标车速，并确认 `actual_gear=7` 是否确认为 P/N 档映射（部分车型定义可能不同）。

### 补充分析(R2)


1. **时序不一致**: TPE 触发时间 (1776963417s) 与报警窗口 (1776934631s) 相差约 7.8 小时，**确认为日志分段或时间戳对齐错误**。但逻辑结论不受影响：无论何时，只要 `fctb_enable=0` (全局禁止) 且 `gear=7` (N/P 档)，功能均无法激活。TPE 记录的 `HoldRelease` 仅为功能处于非激活态时的状态清理行为。

2. **`actual_spd` 为 0 问题**: 
   - **变量映射**: `actual_spd` 若对应底层速度信号，值为 0 导致 `0.5 ≤ V_ego` 条件**不满足**。
   - **替代信号**: 建议核查 Rte 接口中的 `VehicleStatus_VehicleSpeed` 或 `CarInfo_CarSpd` (通常位于 `Coem` 层或整车通讯域)。
   - **根因修正**: 即便速度有效，**档位 `actual_gear=7`** (代码 `ASWIN_SystemState.c:980`) 直接导致 `bFCTBEnable` 强制置 0，这是比速度超限更优先的阻断条件。

**结论**: 功能未触发主因为**档位不支持**(Gear=7)叠加**功能开关关闭**(`fctb_enable=0`)；速度与时间戳异常为次要现象或配置问题。请优先核实档位标定与功能开启配置。


## system_state


**TPE 一致性**: 
模式 `HoldRelease` @ `adasFunc.c:6378-6382` 在 t=1776963417.63s 触发，条件为 `AEBBAActv_0x137=0` 且 `AEBIBActv_0x137=0`。该模式副作用清零了保压标志 (`bFctbKeepBrakeFlg`)，证实制动释放逻辑正常响应外部 AEB 信号。**但这解释的是“为何释放”，而非“为何未进入激活”**。针对“未触发”问题，需回溯至状态机入口条件检查。

**条件检查表**
| 条件 | 阈值/要求 | 数据实际值 | 满足？ | 对应代码/逻辑位置 |
| :--- | :--- | :--- | :--- | :--- |
| **档位允许性** | `actual_gear != 7 && != 8` | `7` (483 帧稳定) | **否 (N)** | `ASWIN_SystemState.c` 第 980 行 (Standby 入口判断) |
| **车速范围** | `0.5 <= carSpd <= 21.0 km/h` | `< 22.0` (Probe 显示无>22 帧) | 是 (Y) | `ASWIN_SystemState.c` 第 981 行 |
| **系统自检** | `selfInspFlg == TRUE` | - | 默认 Y | `ASWIN_SystemState.c` 第 852 行 |
| **功能开关** | `bFCTBEnable == TRUE` | `FALSE` (配置层) | **否 (N)** | `ASWIN_SystemState.c` 第 776 行 (`AdasEnable`) |
| **AEB 协同** | `bAEBBAActiveFlg` / `IB` | `0` (TPE 实测) | N/A (影响保持而非激活) | `adasFunc.c` 第 6378 行 |

**结论**: 
根因在于 **档位信号异常**。实测 `actual_gear=7` 触发了 `ASWIN_SystemState.c` 第 980 行的互斥逻辑 (`!= 7 && != 8`)，导致状态机无法从 Init/Passive 跳转至 Standby(2)，进而通过 `AdasEnable()` 强制关闭 `bFCTBEnable`，使得感知侧即便有雷达告警也无法进入 Active(3) 触发制动；TPE 中的 `HoldRelease` 触发仅为后续的状态清理行为，非主因。

**需确认**: 
请整车标定团队确认 `actual_gear=7` 对应的物理档位定义（通常为 N 或 R），并评估 FCTB 功能是否应支持该档位下的激活（当前代码逻辑明确禁止）。

### 补充分析(R2)


是的，`ASWIN_SystemState.c` 中存在其他初始化流程会阻止 `fctbSystemState` 进入 Standby(2)，进而导致 `bFCTBEnable` 恒为 0。除档位外，主要门禁包括：

1. **点火电源**：`GWM_FCTB_AdasEnableCond` 要求 `AdasStM.SysPowerMod == SYS_POWER_ON`。若信号为 ACC/Off，功能直接禁用。
2. **自检完成**：`GWM_Adas_SelfInspFinish` 检查 `ASWIN_FIM_GetSelfCheckStatusReq()`。仅当返回 `ASWIN_FIM_SELFCHECK_PASS` 时状态机才允许激活，否则锁定在 Init/Passive。
3. **故障状态**：`ADAS_GetFCTBFaultErrorStatus` 遍历 `ADASSys_FCTB_Warning_OFF_Fault_EVENT_NUM`。若检测到任何 DEM Event 处于 `FAILED` 或 `PREFAILED`，强制拉低使能。

**逻辑链路**：上述任一条件不满足 → `fctbSystemState` 无法从 Init 跳转至 Standby(2) → `AdasEnable()` 函数内将 `PERInputCapture.adasEnable.bFCTBEnable` 置为 `FALSE` → 感知侧无制动请求权限。

**当前根因**：数据中 `actual_gear=7` 已构成致命阻断（需 D/R 档）。虽然自检/电源也是潜在原因，但实测中档位不匹配优先级更高且证据确凿（483 帧稳定）。若无故障码报告，可排除自检/故障因素。修正前次分析中的行号引用，以函数逻辑为准。


## 主持人审查


### 矛盾点
- 车速数据矛盾：问题标题注明'60kph'测试场景，但 Variable Probe 查询实际车速 `actual_spd > 22.0` 返回 0 行数据，且系统状态专家判定车速满足条件（<21km/h）。需确认是测试标称错误、信号映射错误还是实际车速确实低于阈值。
- 时序窗口不匹配：观测层报警事件发生在 t=1776934631s 附近，而 TPE 触发的 `HoldRelease` 模式时间在 t=1776963417s（相差约 8 小时），两者不在同一时间段，导致无法确认 TPE 分析是否针对了本次故障的同一时刻。
- 根因优先级分歧：感知专家认为‘威胁过低’也是原因之一；算法与状态专家认为‘使能关闭’是决定性因素，威胁参数在使能为 0 时无关紧要。虽逻辑正确，但需明确雷达为何在如此低威胁下仍输出告警标志。


### 遗漏
- 缺失信号映射验证：`actual_spd` 信号在 60kph 测试下无有效数据（Probe 为 0），未确认该变量是否对应正确的 CAN 信号名或采样率，可能导致车速判断依据不足。
- 缺少雷达告警逻辑溯源：观测层显示 `radar_objects` 有告警标志，但 TTC(79s)/距离(36m+) 远超常规 FCTB 阈值，未分析雷达端为何将此类远距离目标标记为 FCTB 威胁。
- 时间戳同步性未验证：TPE 触发时间与观测窗口时间存在巨大偏差，未排除日志拼接错误或多片段分析导致的结论错位风险。


### 关键争议
测试场景描述（60kph）与实际数据分析（无超速记录）及硬件状态（档位 P/N）的一致性存疑，需优先厘清是车速超标抑制、档位错误抑制，还是测试脚本/数据采集本身的配置错误。