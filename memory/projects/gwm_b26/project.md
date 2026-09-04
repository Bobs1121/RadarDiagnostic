# 角雷达问题分析系统记忆 (project.md)

## 1. 系统概述
角雷达 (Corner Radar) 问题分析系统，基于 AI 驱动的自动化诊断平台。
目标平台：TI AWR2E44P，覆盖 8 大 ADAS 功能：

| 分组 | 功能 | 全称 |
|------|------|------|
| 后角雷达 | BSD | Blind Spot Detection |
| | LCA | Lane Change Assist |
| | DOW | Door Open Warning |
| | RCW | Rear Collision Warning |
| | RCTA | Rear Cross Traffic Alert |
| | RCTB | Rear Cross Traffic Braking |
| 前角雷达 | FCTA | Front Cross Traffic Alert |
| | FCTB | Front Cross Traffic Braking |

## 2. 代码知识库学习进度
- **状态**: 已完成基础学习 (warmup_done=True)
- **已覆盖功能**: BSD, DOW, FCTA, FCTB, LCA, RCTA, RCTB, RCW
- **核心关注点**: alarm_logic, calculation_chain, output_chain, state_machine
- **最新同步**: 2026-06-11

## 3. 固定信息与映射
- **车速信号**: CAN Signal `CarSpd` -> Internal `egoSpeed` (需校验单位转换，常见 km/h vs m/s)
- **FCTA 关键阈值**: 
  - TTC 触发阈值: <= 2.0s
  - 目标准入速度阈值: >= 4.0 km/h (低于此值视为静止/无效目标)
  - 相对速度除零保护: 当 `rel_vel_x` 接近 0 时，TTC 返回 inf

## 4. 用户偏好与分析习惯
- **诊断深度**: 倾向于深入代码层 (`adasFunc.c`) 追踪状态机变量和标志位。
- **数据验证**: 重视 Variable Probe 实测数据与 BLF 日志的一致性。
- **根因描述**: 偏好“一句话根因 + 因果链”的结构化总结。

## 5. 已知高频问题模式
- **FCTA**: 低速工况下因相对速度趋零导致 TTC 计算发散，或因目标速度低于准入阈值导致未触发。
- **FCTB**: 常因档位信号 (GearPos) 或外部抑制信号 (ESP协同) 导致使能关闭。
- **RCTA**: 常因关键外部信号缺失或 TTM 计算不满足条件导致未触发。