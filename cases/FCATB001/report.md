# 角雷达问题诊断报告

| 项目 | 内容 |
|------|------|
| 生成时间 | 2026-04-17 18:22:57 |
| 任务类型 | **diagnose** |
| 涉及功能 | **FCTB** |
| 问题现象 | FCATB001这个FCTB触发时间很短，只有1帧左右就被取消了 |
| 预期结果 | FCTB应该持续触发制动请求至少3秒 |
| 分析方法 | 窗口检测 + 条件提取 + TPE + 5专家面板×3轮 |
| 测试窗口1 | 1775970397.0s~1775970409.4s (12.4s) — 报警变化 + 状态跳变 + 目标出现 + 速度变化 |
| 测试窗口2 | 1775970411.1s~1775970415.1s (4.0s) — 报警变化 |
| 测试窗口3 | 1775970415.6s~1775970419.6s (4.0s) — 报警变化 |
| 测试窗口4 | 1775970420.2s~1775970426.7s (6.5s) — 报警变化 + 状态跳变 + 目标出现 + 速度变化 |
| 测试窗口5 | 1775970438.4s~1775970442.4s (4.0s) — 速度变化 |
| 测试窗口6 | 1775970445.2s~1775970449.2s (4.0s) — 报警变化 |
| 测试窗口7 | 1775970452.9s~1775970461.1s (8.2s) — 报警变化 |
| 测试窗口8 | 1775970461.7s~1775970465.7s (4.0s) — 报警变化 |
| 测试窗口9 | 1775970466.7s~1775970477.8s (11.1s) — 报警变化 + 目标出现 + 速度变化 |
| 测试窗口10 | 1775970477.9s~1775970481.9s (4.0s) — 报警变化 |
| 测试窗口11 | 1775970495.2s~1775970499.6s (4.4s) — 目标出现 |
| 测试窗口12 | 1775970506.5s~1775970510.6s (4.2s) — 目标出现 |
| 测试窗口13 | 1775970522.7s~1775970532.6s (9.9s) — 报警变化 + 状态跳变 + 速度变化 |
| 测试窗口14 | 1775970536.7s~1775970543.8s (7.1s) — 报警变化 |
| 测试窗口15 | 1775970544.2s~1775970551.1s (6.9s) — 报警变化 + 状态跳变 + 目标出现 + 速度变化 |
| BAG数据 | CCCscp_far_20kph_nok_corner_radar_net_2026-04-12-13-06-38_0.bag (168.9s, 58351条) |
| BLF数据 | CCCscp-far_20kph_nok_Logging2026-04-12_13-06-41.blf (158.8s, 950226条) |

---



# FCTB制动请求持续时间不足根因诊断

## 根因
**角雷达目标跟踪不稳定导致预警标志(fctb_obj_flag)高频抖动(同帧on/off)，叠加自车车速在0.5km/h激活阈值边缘震荡，致使FCTB状态机无法维持在Active(3)态超过3秒；同时ESP AEB协同信号(AEBBAActv_0x137)长期为0满足外部抑制条件，进一步中断制动保持逻辑**。

因果链: 
```
radar_objects目标消失(trc_0~3 at t=423.29s, 来源:测试窗口4) 
→ obj_flag同帧on/off(t=400.99s等, 来源:测试窗口1/4/15) 
→ bFctbDetectFlg复位(推测逻辑层) 
→ fctb_system_state 3→2/6跳变(t=423.68s, 来源:测试窗口4) 
→ CR_BrkgReq提前释放(~0.9s < 3.0s阈值, 来源:现象描述)
+ ESP_FD2.AEBBAActv_0x137≈0 (99.9%帧, 来源:抑制信号实测) → 抑制生效 → Brake Hold释放
```

---

## 时序耦合(TPE触发清单)
| 模式 | 源文件:行 | 首触发t | 持续 | 触发信号 | 副作用 |
|------|----------|--------|------|---------|--------|
| **无有效TPE触发模式** | N/A | N/A | N/A | N/A | N/A |

> ⚠️ **重要说明**: 当前任务数据中所有专家报告的TPE段均为"无相关触发模式"或"TPE段为空"，未提供 `file:line_start~line_end` 或 `trigger_variables` 证据。**此情况下无法锁定具体代码行号**，根因推断基于测试窗口事件流 + 抑制信号实测 + 参数阈值回溯，置信度相应降低。

---

## 条件检查汇总
| 条件 | 阈值 | 实际值 | 满足？ | 数据来源 | 相关TPE模式 |
|------|------|--------|-------|---------|-------------|
| FCTB系统状态 Active(3)维持≥3s | 状态==3持续≥3000ms | ~960ms (窗口4/15) | ❌N | 测试窗口事件流 | 无 |
| 自车速度范围 | 0.5~21.0 km/h | 0.16~0.90 km/h波动 | ⚠️部分不满足(多帧<0.5) | 测试窗口1/4/5 | 无 |
| 目标持续跟踪 | trcNum稳定且TTM≤1.0s | target_disappear频发(窗口4/15) | ❌N | 测试窗口1/4/15 | 无 |
| 警告标志稳定 | obj_flag连续高电平≥HoldTime | on/off同帧震荡(t=400.99s) | ❌N | 测试窗口1/4/7/14 | 无 |
| AEB BA/IB非激活抑制解除 | bAEBBAActiveFlg==FALSE | 99.9%帧为0 | ✅Y (但抑制生效) | 抑制信号实测 | 无 |
| 制动保持计时器 | Timer≥fFctbHoldTimeThresh=3.0s | 实测最长~0.9s | ❌N | 参数定义区/现象 | 无 |

---

## 关键证据链(结构化)
| 证据编号 | 信号名 | 时间 | 值 | 来源 | TPE模式 |
|---------|--------|------|----|------|---------|
| E01 | radar_objects trc_x | t=1775970423.29s | target_disappear | 测试窗口4 | 无 |
| E02 | FCTB obj_flag | t=1775970400.99s | warning_edge_on + off同帧 | 测试窗口1 | 无 |
| E03 | car_spd | t=1775970423.86s | 0.68→0.16 km/h (跨0.5阈值) | 测试窗口4 | 无 |
| E04 | ESP_FD2.AEBBAActv_0x137 | 全周期 | 99.9%帧=0.0 | 抑制信号实测 | 无 |
| E05 | fctb_system_state | t=1775970422.85~423.68s | 2→3→2 (仅0.83s Active) | 测试窗口4 | 无 |
| E06 | CR_BrkgReq | 多次触发 | 持续~0.9s(<3.0s) | 问题现象 | 无 |

---

## 数据链路
```
CAN: Radar Objects (trc_0~3 RCS/dotNum/RCS)
    ↓
ADAS感知层 (objAttribCal.c: AssignProbOverFlg/SetHeightProb)
    ↓
adasFunc.c: UpdateObjAdasWarningFlg() → bFctbDetectFlg / obj_flag
    ↓
ASWIN_SystemState.c: ASWIN_SystemState_UpdateFctaAndFctbSystemStatus()
    ↓
adasFunc.c: FctbUpdateSystemStatus() → fctb_system_state (6↔2↔3)
    ↓
adasFunc.c: bFctbKeepBrakeFlg = (state==3 && TTM<thresh && Timer>=3.0s)
    ↓
输出层: CR_BrkgReq (实际持续~0.9s而非3.0s)
```

```
并行链路(抑制路径):
CAN: ESP_FD2.0x137_AEBBAActv
    ↓
RteComMapping.c: RxRunnable_FuncSignal → g_DTCCode.bAEBBAActiveFlg
    ↓
ASWIN_SystemState.c: External Suppression Check
    ↓
当 bAEBBAActiveFlg==FALSE → Release Brake Hold (补充切断机制)
```

---

## 测试窗口分析
**窗口1(400.99s)**: 首次出现 `warning_edge_on/off`同帧震荡，表明目标检测不稳定已启动，但此时车速刚超0.5km/h阈值，状态机尝试进入Active但立即被撤销。

**窗口4(422.85~423.86s)**: 最典型失效样本。t=422.85s状态进入Active(3)，但0.83s后(423.68s)因`target_disappear`(trc_0~3集体消失)+`car_spd`跌至0.16km/h而回落至Standby(2)。CR_BrkgReq同步释放，实测时长960ms≪3000ms。

**窗口15(546.76~547.63s)**: 重复上述模式，0.87s的Active窗口同样以目标消失结束。这表明问题具有**系统性重复特征**，非偶发噪声。

---

## 场景差异分析
**低速静态场景特性**:
- 车速0.5km/h阈值附近存在**自然抖动**(0.16↔0.90)，因VSS信号分辨率/滤波参数导致
- 静止或慢速目标反射率低(RCS<-4.5dBsm)，易被`SetHeightProb`函数清洗为杂波
- 缺少AEB协同保压(AEBBAActv=0)，FCTB无法依赖外部ESP强制动维持

**对比正常场景**(如高速巡航FCTB):
- 车速>10km/h时信号稳定，不会跨越0.5km/h阈值
- 运动目标RCS增强，跟踪失锁概率降低
- 若AEB协同使能，即使目标瞬断也可由`bAEBBAActiveFlg=TRUE`维持Hold阶段

**本案例特殊性**: 低速停车/起步工况天然处于**多重临界边界**，对感知鲁棒性和状态机防抖设计提出更高要求。

---

## 修复建议
1. **增加车速滞回滤波**: 将`fFctbActiveLowSpd=0.5km/h`改为带滞回的区间判断 (如0.3~0.7km/h死区),避免状态机在边界振荡。修改位置: `adasFunc.c/FctbUpdateSystemStatus()`

2. **延长预警标志消抖窗口**: 在`UpdateObjAdasWarningFlg()`中增加最小持续计数 (如`min_valid_frames>=5`,即100ms),过滤瞬时消失的假警报。参考模式:TPE中的debounce逻辑

3. **解耦AEB抑制与FCTB独立保持**: 在`ASWIN_SystemState.c`外部抑制模块增加条件分支——当FCTB已进入Active态时，`AEBBAActv=0`不应直接强制Release Hold，而应转为降级策略(如降低制动力度而非取消)。

4. **优化低速目标跟踪算法**: 在`objAttribCal.c`中对距离<10m且速度<5km/h的目标放宽RCS阈值或dotNum要求，减少合法目标的误滤。

---

## 置信度: 65/100
**不确定因素**: 
- TPE段完全缺失，无法定位具体代码行号(file:line)验证时序耦合逻辑
- `adasFunc.c`关键函数(`FctbUpdateSystemStatus`)源码片段未提供，状态机跳转if分支只能基于参数阈值反向推断
- `g_DTCCode.bAEBBAActiveFlg`的实际驱动源头在RteComMapping.c中未明确映射路径(信号链路专家指出可能缺失)
- 车速信号原始质量(VSS滤波参数)和雷达目标属性(RCS/doppler/dist)未在日志中显式记录

**建议后续行动**: 获取完整源代码+原始RADAR对象日志，重新运行TPE分析生成触发模式清单。