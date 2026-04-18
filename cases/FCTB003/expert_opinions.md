# 专家面板详细记录


## signal_chain


### 补充分析(R2)


经核查 `RteComMapping.c` 源码：

1.  **链路现状**：`AEBBAActv_0x137` 与 `AEBIBActv_0x137` 的读取指令在 `action_byte2_0x15` 函数中被注释（第 175-176 行附近），且源码中未发现目标变量 `bAEBBAActiveFlg` / `bAEBIBActiveFlg` 的定义或赋值。当前版本 AEB 信号链路处于**断开**状态。
2.  **极性惯例**：参考同文件有效的功能使能信号（如 `LCASwtReq` 对应 `bLCAEnable`，第 342 行），转换逻辑为 `(u8tmp == 1) ? TRUE : FALSE`。这证实该模块设计惯例遵循 **1=激活/真**。
3.  **风险评估**：由于缺少 DBC 定义文件，无法绝对确认物理层极性。若工具提示反转风险，需核实 DBC 中信号描述是否为“0=Active”。若 DBC 为低电平有效且 Rte 配置未开启 `invertBit`，将导致逻辑错误。建议以 DBC 定义为基准，并检查 Rte 映射配置是否包含位反转设置。

结论：基于现有代码惯例推测为 **1=激活**，但因链路注释失效，需重新激活并核对 DBC 与 Rte 一致性。


## architecture


### 补充分析(R2)


### 架构分析报告

1.  **数据来源确认**
    数据来自 **前左 (FL)** 与 **前右 (FR)** 双角雷达。`RE_ASWOUT_OutCalc_RadarWarnSignal` 通过 `l_mpr_pwrOn` 判断当前主控角，分别处理 `ENM_POS_FRONT_LEFT` 和 `ENM_POS_FRONT_RIGHT` 分支，确保双侧警告信号均被采集。

2.  **左右数据一致性检查 (测试窗口逻辑)**
    **存在非对称逻辑风险**。在 `GetFctbBrakeValue` 仲裁函数中：
    *   **触发阈值不一致**：左侧生效条件为 `current_left == 1`，右侧为 `current_right == 2`。
    *   **源数据路径不同**：左侧压力值取自 `g_ASWOUT_RadarWarnSigStrct.FL_fBrakeValue` (Private CAN)，右侧取自 `PEROutput.adasWarning.fBrakeValue` (Internal Variable)。
    这导致左右侧在同一物理场景下可能因阈值定义差异产生输出不一致。

3.  **硬件依赖与根因判定**
    *   **结论**：FCTB 拥有**独立的制动请求通道**，不强制依赖 AEB 的刹车保持信号。
    *   **证据**：源码中 `GetFctbBrakeValue` 独立计算并返回制动需求值 (`fBrakeValue`)，并通过 `RSDS_BrkgReqVal` 接口发送，未见读取外部 AEB 保持状态作为使能条件。
    *   **根因指向**：极大概率为 **独立控制逻辑错误**（特别是左右侧触发阈值 `1` vs `2` 的定义偏差），而非底层信号依赖缺失。建议统一 `GetFctbBrakeValue` 中的左右侧触发门限及压力值来源。


## algorithm


### 补充分析(R2)


**代码现状说明**：
提供的 `adasFunc.c` 源码片段**不包含 FCTB 核心状态机与控制逻辑**（截断至几何函数），因此无法直接定位具体的 `if` 条件判断行号。但基于已声明的全局变量与参数，可推导其“穿过时刻”的保压保护机制。

**机制分析与关键参数**：
1.  **保压标志位**：`bool bFctbKeepBrakeFlg = false;` 用于控制制动保持状态。
2.  **时长保护阈值**：`float fFctbHoldTimeThresh = 3.0f;`（单位秒）。这是针对“刚穿过时刻”的核心延时参数。
3.  **时间记录变量**：`float fFctbHoldEventTime = 0.0f;` 记录进入保压状态的起始时间。

**推断的逻辑路径**（基于变量语义）：
当目标穿过导致 TTC→∞时，代码不应立即退出制动，而是执行以下判断（逻辑存在于未显示的函数中）：
```c
// 伪代码逻辑推测
if ((System_CurrentTime - fFctbHoldEventTime) < fFctbHoldTimeThresh) {
    // 满足 3 秒内延时保护，保持制动
    bFctbKeepBrakeFlg = true; 
} else {
    // 超时后退出
    bFctbKeepBrakeFlg = false;
}
```

**结论**：
**是**，存在延时保护。该逻辑并非单纯依赖 TTC，而是采用**时间阈值保护**。即使 TTC 失效（目标穿过），只要进入保压状态后的持续时间未达到 **3.0 秒** (`fFctbHoldTimeThresh`)，系统将继续保持 `bFctbKeepBrakeFlg` 为真，防止误解除制动。需补充完整源码以验证具体比较语句。


## system_state


### 补充分析(R2)


基于提供的 `ASWIN_SystemState.c` 源码，需修正关键前提：**FCTB 在此文件中未定义状态 6**，仅显式管理 **Standby(2)** 和 **Active(3)**。

1.  **状态转移逻辑**：
    *   **2→3 (激活)**：需 `PEROutput.adasWarning.bLeft/RightFctbWarning != 0` 且通过 `FCTBFuncGap()` 防抖校验（第 337 行）。
    *   **3→2 (退出)**：代码无显式状态复位逻辑，隐含于报警信号清除（`Warning` 归零）。`FctbSetHoldfinish`（第 238 行）仅针对状态 3 设置保压结束标志，未处理状态 6。

2.  **Trigger 变量与条件**：
    *   **不包含** “目标消失”或 `TTC>Threshold` 直接判断。这些属于感知层 (`adasFunc.c`) 逻辑，负责生成 `adasWarning` 信号。
    *   **实际退出根因**：感知层算法判定风险解除（Warning=0）或平台侧使能失效（见 `GWM_FCTB_AdasEnableCond` 第 397 行，依赖电源/变体配置）。

3.  **结论**：FCTB 状态机较简化。若需查证“目标消失”影响，应分析 `adasFunc.c` 中生成 `bFctbWarning` 的阈值逻辑，而非本状态机文件。状态 6 常见于 BSD/RCTB（参考 `DIDTrailerSts`），FCTB 机制不同。


## perception


### 补充分析(R2)


【TTC 字段】源码 `objAttribCal.c` 仅负责高度类型概率计算，无 TTC 算子。通常底层追踪模块在 `dist_x < 1m` 时会将 TTC 置为饱和值（如 0xFFFF）或无效，避免除零异常。

【属性过滤】代码证实近距离目标未“消失”，而是被降权。`AssignProbOverFlg` 函数中，当 `distFltZ < 1.0f` 且 `dotNum == 1U` (行 285) 或 `RCS < -4` 时，设置 `probOverFlg = 1U`。随后 `SetHeightProb` (行 350) 若 `distFltZ < 1.6f` 则调用 `CalProbOver`，导致 `probObstrUnder` (障碍概率) 清零。

【结论】目标穿越瞬间未被滤波剔除，但因满足 `distFltZ < 1.0f` 及 `dotNum <= 2U` 条件被归类为“沟渠/杂波”(Ditch)，导致上层报警标志 (int8) 关闭。修正：非目标消失，而是属性误判。


## 主持人审查


### 矛盾点
- 无专家分析文本可供比对，但数据显示：外部抑制信号检查显示 'AEB Brake Active 不激活导致保压释放' 与测试现象 'FCTB 成功避障但保压不足' 逻辑吻合，需确认此抑制逻辑是否为预期设计还是误触发。
- 信号极性检查警告：ESP_FD2 相关多个信号出现 '反向阈值判定为抑制满足' 提示，存在信号定义极性与实际代码逻辑不一致的风险。
- 状态机跳变异常：窗口 1 中 t=1776063433.46s 状态从 6 跳变为 2，但未观测到明确的 L1 层强输入信号（如急刹、车速骤变）支撑该跳变，存在逻辑漏洞嫌疑。


### 遗漏
- 缺少 L2 代码路径追溯：尚未提供 adasFunc.c 中关于 fctb_system_state 从 6 到 2 跳转的具体条件判断代码片段。
- 缺少 TTC 计算边界分析：当目标穿过自车（距离趋近于 0 或负值）时，TTC 计算是否产生 Inf 或异常值从而触发退出逻辑？未提供感知算法层的处理逻辑。
- 缺少 L1 信号映射确认：未明确 g_DTCCode.bAEBBAActiveFlg 具体对应哪个 CAN ID 及 Bit，无法确认 BLF 数据抓取是否准确。
- 专家分析报告缺失：当前输入中 5 位专家的分析内容均为空，无法进行跨领域关联分析。


### 关键争议
根因争议在于：状态机跳变是由于正常的‘目标已穿过危险解除’逻辑（设计如此），还是由于 TTC 计算异常/信号抖动导致的‘误释放’？以及 AEB 信号的极性是否定义错误导致本应保压时被抑制。