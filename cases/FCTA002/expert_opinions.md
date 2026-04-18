# 专家面板详细记录


## architecture


**条件检查表**
| 条件 | 阈值/要求 | 数据实际值 | 满足? |
|------|----------|-----------|------|
| 系统保持时间 (fFctbHoldTimeThresh) | ≥ 3.0 s | 0.91 s (980ms) | **N** |
| FCTB 警告信号值校验 (合并逻辑) | == 1/2 (active_side 判定) | FL 侧无有效记录，仅 radar=2(FR)有目标 | **N** |
| AEB Brake Active (bAEBBAActiveFlg) | == TRUE (正常值) | FALSE 占 99.7% 帧 (1497/1501) | **N** |
| 车门关闭状态 (Door Status) | All Doors Closed | 信号未在 BLF 中找到 → 无法确认 | **?** |
| 自车速度范围 | 0.5~21.0 km/h | 4.95~5.01 km/h | Y |

**结论**: FCTB 制动请求被提前释放的核心原因是激活时长(0.91s)远低于保持阈值(3.0s)，叠加 AEB Brake Active 信号为 FALSE 导致保压逻辑强制释放，且仅单侧(Rad=2/FR)有目标检测，左右雷达合并逻辑未完整执行。

**需确认**: 请系统专家确认车门关闭状态的实际 CAN 信号来源及极性；请算法专家确认为何目标出现后 TTC 快速增大导致风险解除(0.91s < 3.0s 保持时间)。


## algorithm



## signal_chain



## perception



## system_state



## 主持人审查



### 遗漏
- Parsing failed