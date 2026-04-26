# 角雷达问题诊断报告

| 项目 | 内容 |
|------|------|
| 生成时间 | 2026-04-20 15:14:40 |
| 任务类型 | **diagnose** |
| 涉及功能 | **FCTB** |
| 问题现象 | FCTB没有发生 |
| 预期结果 | FCTB应该会发生 |
| 分析方法 | 窗口检测 + 条件提取 + TPE + 5专家面板×3轮 |
| 测试窗口1 | 1776585870.3s~1776585874.9s (4.6s) — 报警变化 |
| BAG数据 | 015_FCTB-not_occur.bag (125.8s, 34603条) |
| BLF数据 | 015-FCTB_not-occur.blf (128.5s, 109771条) |

---



### 根因
**L1/L2.5 耦合导致的状态清零是直接的软件原因**：**ESP 侧 AEB 协同信号（`AEBBAActv_0x137`/`AEBIBActv_0x137`）持续为 0**，在 **t=1776614587.22s** 首次触发 **`HoldRelease`** 模式（`adasFunc.c:6378-6382`），副作用变量 **`bFctbKeepBrakeFlg`** 被清零，阻断了制动请求维持；同时 **目标横向距离（`dist_y`≈15m）严重超出 ROI 阈值（±1.5m）**（来源：Variable Probe），导致感知层未生成有效激活目标，双重因素共同导致 FCTB 未发生。

### 时序耦合(TPE 触发清单)
| 模式 | 源文件：行 | 首触发 t | 持续 | 触发信号 | 副作用 |
|------|----------|--------|------|---------|-------|
| **HoldRelease** | `adasFunc.c:6378-6382` | `1776614587.224s` | `2240ms` (首次) / `36540ms` (最长) | `AEBBAActv`=0, `AEBIBActv`=0 | `bFctbKeepBrakeFlg`清零, `fFctbBrakeEventTime`清零 |

### 条件检查汇总
| 条件 | 阈值 | 实际值 | 满足？ | 数据来源 | 相关 TPE 模式 |
|------|---|---|---|---|---|
| **AEB Brake Active** | `== TRUE` (非零) | `0` (100% 帧) | ❌ N | 抑制信号实测 | `HoldRelease` |
| **AEB Inactive Brake** | `== TRUE` (非零) | `0` (90.3% 帧) | ❌ N | 抑制信号实测 | `HoldRelease` |
| **目标横向位置** | `abs(dist_y) < 1.5m` | `Left: 14.76~14.91m`, `Right: -13.82~-1.59m` | ❌ N | Variable Probe / `dist_y` 查询 | N/A |
| **目标纵向位置** | `-1.0m < dist_x < 0m` | `参与行数=0` (无匹配) | ❌ N | Variable Probe / `dist_x` 查询 | N/A |
| **自车档位** | `D(4)` 或 `R(5)` | `Gear=4` | ✅ Y | Variable Probe / `actual_gear` | N/A |
| **车速范围** | `0.5 ~ 21.0 km/h` | 窗口内隐含正常 (探测到目标) | ⚠️ ? | Variable Probe (报错但逻辑推断满足) | N/A |

### 关键证据链 (结构化)
1. **信号**: `ESP_FD2.AEBBAActv_0x137` | **时间**: `1776614587.224s` | **值**: `0` | **来源**: `抑制信号实测` | **TPE 模式**: `HoldRelease`@`6378-6382`
2. **信号**: `ESP_FD2.AEBIBActv_0x137` | **时间**: `1776614587.224s` | **值**: `0` | **来源**: `抑制信号实测` | **TPE 模式**: `HoldRelease`@`6378-6382`
3. **状态**: `bFctbKeepBrakeFlg` | **时间**: `t>1776614587.224s` | **值**: `被清零` | **来源**: `TPE 副作用` | **TPE 模式**: `HoldRelease`
4. **坐标**: `obj.dist_y` | **时间**: `全窗口` | **值**: `14.76m` (Left) / `-13.82m` (Right) | **来源**: `Variable Probe` (`dist_y` 查询) | 无直接 TPE (空间过滤前置)

### 数据链路
CAN(`AEB*Actv_0x137`=0) → RteComMapping(`g_DTCCode.b*ActiveFlg`=0) → adasFunc.c:6378(`!AEBBA&& !AEBIB`) → HoldRelease 执行 → `bFctbKeepBrakeFlg`=0 (制动释放)
CAN(`Target_Pos`) → Fusion(`dist_y`≈15m) → adasFunc.c(`abs(dist_y)<1.5m`?) → Filter Fail → `PEROutput.adasWarning`=0 (无预警)

### 测试窗口分析
在 `1776614587.22s` 至 `1776614680.88s` 期间，`AEBBAActv` 与 `AEBIBActv` 信号持续为 0，代码中的 `HoldRelease` 保护逻辑被周期性触发（共 6 次），导致内部制动保持标志 `bFctbKeepBrakeFlg` 反复重置；与此同时，融合目标横向坐标始终偏离 ROI 区域（>1.5m），导致系统未能产生有效的 FCTB 触发信号，两者叠加确保功能未激活。

### 场景差异分析
预期场景中，目标应位于自车前方近距离（`dist_y`<1.5m）且 ESP 协同就绪。本次实测中，**物理空间偏差**（目标真实位置或标定误差导致 15m 偏移）使系统判定为无效目标；**通信逻辑依赖**（FCTB 制动维持强关联 AEB 信号）使即便存在潜在风险也无法发送制动请求。若仅修复标定仍保留 AEB=0 状态，制动逻辑依然会被软件清除。

### 修复建议
1. **标定优先**：核查角雷达安装角度及坐标系转换参数，解释为何 `dist_y` 偏差达 15m，确保目标进入 ±1.5m ROI 有效区。
2. **配置修复**：解除 `RteComMapping` 中对 `AEBBAActv_0x137` 等信号的注释（见架构专家 R2），确认 ESP 侧是否应在 FCTB 触发时置位该信号。
3. **逻辑解耦**：评估 `HoldRelease` 条件（6378 行）是否应依赖 `AEB` 状态，还是应基于 FCTB 自身状态机独立管理制动释放。

### 置信度：85/100
不确定因素主要在于 `dist_y` 的 15m 偏差是物理位置错误还是坐标系计算异常（如雷达原点对齐问题）；若 ROI 过滤在前端已完成，则 TPE 触发的 `HoldRelease` 可能是对无效状态的清理而非主因，但在当前日志中必须视为生效的代码路径。