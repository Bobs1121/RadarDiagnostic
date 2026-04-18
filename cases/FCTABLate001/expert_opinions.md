# 专家面板详细记录


## perception


**条件检查表**
| 条件 | 阈值/要求 | 数据实际值 | 满足？ |
|------|----------|-----------|------|
| [AEB] AEB Brake Active (BA) NOT active → Release Brake Hold | bAEBBAActiveFlg == TRUE (正常), == FALSE (抑制) | ESP_FD2.AEBBAActv_0x137 = 0 (100% 帧), 即 **bAEBBAActiveFlg=FALSE** | ⚠️ **抑制满足** |
| [AEB] AEB Inactive Brake (IB) NOT active → Release Brake Hold | bAEBIBActiveFlg == TRUE (正常), == FALSE (抑制) | ESP_FD2.AEBIBActv_0x137 = 0 (98.3% 帧), 间歇性=1 | ⚠️ **抑制满足** |
| [Driver] Accelerator pedal > 80 → Prevent Standby to Active | AccPedPosDiag <= 80 (正常) | max=30.3149 | ✅ 不抑制 |
| [Driver] Steering wheel angle > 350 → Prevent Standby to Active | steer_angle <= 350 (正常) | max=136.7 | ✅ 不抑制 |
| [Driver] Steering wheel speed > 250 → Prevent Standby to Active | SteerWheelSpd <= 250 (正常) | max=347.6 (仅 0.1% 帧超阈值) | ⚠️ **偶尔抑制** |
| 制动保持时长 >= fFctbHoldTimeThresh | 保压 >= 3.0s | 实测保压 ≈ 2.7-2.84s (< 3.0s) | ❌ **不满足** |
| 目标 TTC 变化 | 目标穿越后 TTC→Inf (风险解除) | 未提供 TTC 时序数据，需补充 | 🔄 **待确认** |
| CR_BrkgReq 激活次数 | 连续触发保压逻辑 | 共 3 次独立触发，每次独立计时 | ⚠️ **无法累积** |

---

**结论**: FCTB 制动退出的根本原因是**外部抑制信号 AEBBAActv=0 持续满足抑制条件（bAEBBAActiveFlg=FALSE）**，同时**单次制动时长 2.7-2.84s < 保持阈值 3.0s**，导致状态机提前退出保压阶段，而非"TTC 变为 inf 后才退出"。

**需确认**: 请功能专家验证① `bAEBBAActiveFlg` 极性与代码中 `Release Brake Hold` 逻辑的实际关联；② TTC 在制动结束前的具体时序，确认是否先于 AEB 抑制触发风险解除。


## system_state


## FCTB 系统状态分析

**条件检查表**

| 条件 | 阈值/要求 | 数据实际值 | 满足？|
|------|----------|-----------|------|
| [AEB] AEB Brake Active (BA) is NOT active → Release Brake Hold | g_DTCCode.bAEBBAActiveFlg == TRUE | **ESP_FD2.AEBBAActv_0x137: 100% 帧为 0** | ❌ **抑制条件满足（应保持制动）** |
| [AEB] AEB Inactive Brake (IB) is NOT active → Release Brake Hold | g_DTCCode.bAEBIBActiveFlg == TRUE | **ESP_FD2.AEBIBActv_0x137: 98.3% 帧为 0** | ❌ **抑制条件满足（应保持制动）** |
| AdasStM.AccPedPosDiag > 30 → Prevent Keep Brake | ≤ 30 | max=30.3149, mean=0.1054 | ✅ 基本满足 |
| FCTBHoldThree() >= 3.0s | ≥ 3000ms | **实测保持时长: 2700-2840ms** | ⚠️ **提前释放** |
| StWhAng() > 360 | ≤ 360 | max=347.6, mean=2.46 | ✅ 满足 |
| fctbSystemState == 3 (Active) | State=3 | **窗口内状态频繁跳变 (4147 次)，未见稳定 Active** | ❌ **状态不稳定** |
| bFCTBEnable == 1 (使能持续) | PERInputUpdate.adasEnable.bFCTBEnable == TRUE | **CR_FCTA_Resp: 恒定 0** → FCTA/FCTB 均使能失败 | ❌ **使能异常** |
| TTC <= fFctbAEBActiveThresh(1.0s) | TTM ≤ 1.0s | **无 TTC 数据可验证** | ⚠️ 无法确认 |
| CR_FCTB_Resp == 1 (响应正常) | Output=1 | **100% 帧为 1** | ✅ 满足 |

---

## 状态时序分析

| 时间点 | 事件 | 分析 |
|--------|------|------|
| 1776011070.41s | CR_BrkgReq: 0→1 | 制动触发 |
| 1776011070.49s | FCTA_Warn: 0→1 | 报警触发 (制动前 80ms) |
| 1776011073.25s | CR_BrkgReq: 1→0 | **制动释放 (2840ms)** |
| - | 预期保压 3000ms | **提前 160ms 释放** |

---

## **结论**

FCTB 制动提前释放的根本原因是：**AEB 相关 CAN 信号 (AEBBAActv/AEBIBActv) 在 ESP 侧全程为 FALSE，不满足 FCTB 制动保持的外部使能条件，导致 `FctbSetHoldfinish()` 中 `bHoldFinishFlg` 被置位，提前终止了保压计时器**。此外，**状态机在窗口内发生 4147 次跳变且 CR_FCTA_Resp 恒为 0**，表明 FCTB 功能使能层存在系统性异常，进一步加剧了状态不稳定。

---

## **需确认**

1. **请确认 ESP_FD2.AEBBAActv_0x137 的极性定义** - 是否应为"非零表示 AEB 激活"？当前数据 100% 为零与正常 FCTB 工作矛盾。
2. **追溯 PERInputUpdate.adasEnable.bFCTBEnable 的来源** - 该信号在 ASWIN_SystemState.c 中由 `AdasEnable()` 回灌生成，需确认 `fctbSystemState==2/3` 的条件是否持续满足，为何状态机频繁跳变。


## signal_chain


**条件检查表**
| 条件 | 阈值/要求 | 数据实际值 | 满足? |
|------|----------|-----------|------|
| [AEB] AEB Brake Active (BA) NOT active → Release Brake Hold | bAEBBAActiveFlg == TRUE | ESP_FD2.AEBBAActv_0x137 = 0 (100%帧为零) | ❌ **不满足 - 会强制释放制动** |
| [AEB] AEB Inactive Brake (IB) NOT active → Release Brake Hold | bAEBIBActiveFlg == TRUE | ESP_FD2.AEBIBActv_0x137 ≈ 0 (98.3%帧为零) | ⚠️ **基本不满足** |
| [Driver] Acc pedal pos too high → Prevent Standby to Active | AccPedPosDiag <= 80 | VCU_ActAccrPedlRat max=30.3 | ✅ 满足 |
| [Driver] Steering angle too large → Prevent Standby to Active | steer_angle <= 350 | CSA2.SteerWheelAng max=136.7 | ✅ 满足 |
| [Driver] Steering speed too high → Prevent Standby to Active | SteerWheelSpd <= 250 | CSA2.SteerWheelSpd max=347.6 | ✅ 满足 |
| [ESP] ESP function OFF → Prevent Standby to Active | ESPFUN == 0 | ESPFuncOffSts_0x137 = 0 (100%帧为零) | ⚠️ **需确认极性** |
| FCTB制动请求输出 | CR_BrkgReq = 1 | 激活3次，每次持续2700-2840ms | ✅ 有输出 |
| FCTB减速度值 | BRK_VAL=-4.0/-2.0 | CR_BrkgReqVal在-4.0~-2.0间切换 | ✅ 正常 |
| 制动保持时长 | >= 3.0s (fFctbHoldTimeThresh) | 实际2700-2840ms < 3.0s | ❌ **不足** |

---

**结论**: AEB相关抑制信号(AEBBAActv/AEBIBActv)在全测试周期内几乎均为0，触发了**"Release Brake Hold"**抑制逻辑，本应更早释放制动；但实测制动仍持续~2.7s，说明存在额外的**制动保持锁定机制或TTC判断异常**。客户感知"退出晚"可能是因为：(1) 系统仍在执行某段固定延时保压；(2) TTC在目标穿越后未正确更新为inf；(3) 左右雷达制动请求合并逻辑中存在冗余触发。

**需确认**: 
1. 请算法专家核实**目标穿越后TTC是否变成inf**（影响Active状态保持）
2. 请代码专家确认是否存在独立于AEB抑制信号的**低速锁定计时器**逻辑


## architecture



## algorithm



## 主持人审查



### 遗漏
- Parsing failed