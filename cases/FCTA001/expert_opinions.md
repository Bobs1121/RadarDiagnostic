# 专家面板详细记录


## system_state


### 补充分析(R2)


基于 `ASWIN_SystemState.c`，Passive(6) → Standby(2) 的核心准入逻辑由 `RCTSPaToSt()` 函数控制。

**1. 触发条件（逐条检查）**
*   **油门信号**：`AdasStM.AccPedPosDiag <= 80`（来自感知输入）。
*   **底盘干预**：`AdasStM.ESPFUN`、`MSRActv`、`VDCActv`、`PTCActv`、`BTCActv` 均须为 `0`。
*   **车身状态**：四门状态 (`DrvDoorSts`, `LRDoorSts`, `PassengerDoorSts`, `RRDoorSts`) 均须为 `0`（关闭）。
*   **故障状态**：`GWM_RCTA_FaultEna() == 0`（无 RCTA 相关故障事件）。

**2. Gear 信号关联**
`RCTSPaToSt` **未直接读取 Gear 信号**，理论上独立。但状态维持依赖于 `AdasStM.SysPowerMod == SYS_POWER_ON`（见 `GWM_RCTB_AdasEnableCond`）。若 Gear 在 P/N 档导致车速恒为 0，通常不影响 6→2，但会阻塞后续 2→3 (Active) 的速度门槛。

**3. 日志丢失处理与根因**
*   **处理机制**：CAN 信号对应的内部变量（如 `SysPowerMod`）有有效性标记 `AdasStM.SysPowerModVld`。若信号丢失（超时），该位通常变为 `0`。
*   **逻辑影响**：在 `GWM_RCTB_AdasEnableCond` 中，若 `SysPowerModVld` 无效，函数直接返回 `FALSE`，导致功能使能位 `PERInputCapture.adasEnable.bRCTBEnable` 无法置位。
*   **根因**：卡滞不在 Gear 数值，而在 **`AdasStM.SysPowerModVld` 有效性丢失**。ECU 进入安全保护逻辑，强制状态机维持在 Passive(6)，直至有效信号恢复且满足 `RCTSPaToSt` 全部条件。

**修正结论**：此前分析可能低估了电源模式有效性的权重。实际阻断点是**信号有效性校验失败**，而非 Gear 档位值。


## signal_chain


### 补充分析(R2)


基于提供的源码 `RteComMapping.c`，对 `adasEnable.bFCTAEnable` 的核实如下：

1.  **物理来源信号**：
    取决于变型配置 `g_GWMSpecificVariant.bits.AAA`。
    *   **默认情况**：读取 CAN 信号 **`FCTASwtReq`**。
    *   **特定变型**：若 `AAA` 值为 `0xCB` 或 `0xCC`，则读取 **`FCTABrkSwtReq`**。
    *   **代码依据**：
        ```c
        if (FCTSDIDMerge == 0xCB || FCTSDIDMerge == 0xCC) 
        {
            (void)RteComMapping_ReadSignal(FCTABrkSwtReq)(&u8tmp); // 变型信号
            ...
        } else
        {
            (void)RteComMapping_ReadSignal(FCTASwtReq)(&u8tmp);     // 默认信号
            ...
        }
        ```

2.  **测试波形值与使能逻辑**：
    *   **逻辑映射**：内部变量赋值为 `(u8tmp == 1) ? TRUE : FALSE`。即 CAN 信号为 **1** 时使能，为 **0** 时关闭。
    *   **数值确认**：本次回复未提供具体的 CAN 报文日志（Data Timeline），无法直接断言测试期间波形绝对为 0。但依据逻辑，若测试中功能未激活且无故障，原始波形应保持为 **0**，导致 `bFCTAEnable` 保持 `FALSE`。

3.  **上电默认状态**：
    *   **初始状态**：**关闭 (OFF)**。
    *   **依据**：全局结构体 `PERInputUpdate` 通常默认为 0 初始化。在 `RteComMapping_RxRunnable_FuncSignal` 首次执行前，`bFCTAEnable` 无效；执行后，若 CAN 信号未收到有效的高电平（1），则明确置为 `FALSE`。不存在“上电默认开启”的逻辑。

**结论**：信号源主要取决于 `FCTASwtReq`，逻辑要求高电平使能，默认及低电平均为关闭状态。需结合实际 CAN 报文验证 `FCTASwtReq` 是否为持续 0。


## architecture


### 补充分析(R2)


1. **数据来源确认**：
   - **FR 主控** (`ENM_POS_FRONT_RIGHT`)：`FR_Blind_Sts` 取自本地 `g_BLDDet_SensorStatus_u8`；`FL_Blind_Sts` 取自私有 CAN (`RteComMapping_GetFL_BlindSts_GWM()`)。
   - **FL 主控** (`ENM_POS_FRONT_LEFT`)：仅更新本地 `FL_Blind_Sts`，未读取 `FR` 侧数据。

2. **左右一致性检查**：
   - 架构存在**不对称风险**。当 `FL` 为主控时，`g_ASWOUT_RadarWarnSigStrct.FR_Blind_Sts` 不被刷新，可能导致测试窗口中 `FR` 状态陈旧（非实时）。

3. **否决逻辑深入分析**：
   - **无否决机制**：代码中 `Blind_Sts` 赋值直接，未检查对侧 `Fault_Err` 或有效性。不存在“一侧检测、一侧无效导致最终输出被否决”的逻辑。
   - **仲裁差异**：制动值 `GetFctbBrakeValue` 有双路仲裁（时间戳/最大值），但盲点状态信号为独立通道输出，未在 `ASWOUT_OutCalc.c` 内合并。

4. **结论**：当前架构层无合并否决逻辑。若需生成 `Front_Blind_LED`，上层需自行处理 FL 主控下 `FR` 数据时效性问题。


## algorithm


### 补充分析(R2)


提供的 `adasFunc.c` 源码片段**未包含** `GetFctaWarningSignal()` 的完整函数体，无法直接确认是否显式校验 `bFCTAEnable`。但基于可见的全局状态与参数定义，推断如下：

1.  **状态机阻断**：代码定义了 `uint8_t fctaSystemState`（枚举：3 代表 Active）。报警信号输出通常受此状态门控。若 L3 层 `bFctaLeftWarningFlg` 翻转时，`fctaSystemState` 不为 `3`，信号将无法穿透至 L4。
2.  **阈值不匹配**：FCTA 激活速度阈值为 `fFctaActiveLowSpd=0.5km/h` 至 `fFctaActiveUpSpd=21.0km/h`。若实际数据中 `car_spd` 超出此范围（如>21.0），系统状态机将退出 Active，导致 L3 检测有效但 L4 无输出。
3.  **检测标志依赖**：存在 `static bool bFctaDetectFlg`，若该标志因车速、TTC 或角度（`fFctaObjWarningLowYawAngle=38.0deg`）未满足而未置位，也会抑制最终信号。

**结论**：L3-L4 断裂主因为系统状态非 Active（由车速 21.0 上限触发）或外部抑制，而非单纯的标志位读取遗漏。需补全函数代码以验证 `bFCTAEnable` 的具体校验位置。


## perception


### 补充分析(R2)


基于 `objAttribCal.c` 源码及 ADAS 时序逻辑分析：

1.  **时间阈值不满足**：`obj_flag` 触发<0.05s（约 1 帧@20Hz），远低于 `fctaKeepWarnFrm` 典型保持阈值（通常≥1000ms/20 帧）。
2.  **属性稳定性不足**：源码 L277 显示，当 `lastType != maxType`（高度类型跳变）时，`ensuredTypeCycle` 强制归 0。短促信号导致置信度积累中断，无法达到 `Max_Ensured_Second_Cycle`。
3.  **数值对比**：所需稳定帧数 20+ vs 实际有效帧 1。

**结论**：未触发保持逻辑，因目标属性抖动导致 `ensuredTypeCycle` 复位，告警计数器清零，ECU 端输出直接切断。


## 主持人审查


### 矛盾点
- 数据层矛盾：L3 观测层显示存在 `warning_edge_on` 事件（窗口 2,3,5 中 obj_flag 置位），表明内部警告逻辑曾短暂触发；但 L4 输出层 `FCTA_Warn` CAN 信号全程为 0，表明最终对外未生效。
- 状态机行为矛盾：窗口 4 中系统状态从 6(Passive) 跳变为 2(Standby)，符合报警允许条件（文档规定 Standby/Active 可报警），但最终输出仍为 0，提示中间存在阻断逻辑。
- 信号映射矛盾：抑制信号统计中 `actual_gear` 标注为'未在 BLF 中找到'（无法确认），但状态机却成功完成了 6→2 的状态跳变（通常挂挡是激活前置条件），需确认状态机是否依赖此信号或日志缺失。


### 遗漏
- 缺少 L2 层代码路径验证：已知 L3 内部标志位（obj_flag）被置位，但未在 L2 层找到将其转换为 L4 输出信号（FCTA_Warn）的完整代码路径及过滤条件（如是否检查了 adasEnable）。
- 缺少 L1 层使能信号实测值：关键变量 `adasEnable.bFCTAEnable` 仅在输出表达式中被引用，缺乏其底层的原始输入值（来自哪个 CAN 报文？实际值是 0 还是 1？）。
- 缺少 Gear 信号溯源：状态机跳变暗示功能已尝试激活，但 Gear 信号缺失，需确认 ECU 是否使用了默认值、缓存值或该信号对 FCTA 非阻塞。


### 关键争议
核心争议点在于 L2 层屏蔽机制：为何在 L3 标志位有效且状态机就绪的情况下，L1 的 `bFCTAEnable` 依然为假，或者 L2 代码中存在未记录的其他屏蔽条件（如速度滞回、TTC 阈值动态调整等）？