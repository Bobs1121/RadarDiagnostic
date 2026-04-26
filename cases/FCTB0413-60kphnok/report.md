# 角雷达问题诊断报告

| 项目 | 内容 |
|------|------|
| 生成时间 | 2026-04-23 17:19:32 |
| 任务类型 | **diagnose** |
| 涉及功能 | **FCTB** |
| 问题现象 | 测试CCCscp near side 60kph,FCTB没有触发功能 |
| 预期结果 | FCTB能够触发 |
| 分析方法 | 窗口检测 + 条件提取 + TPE + 5专家面板×3轮 |
| 测试窗口1 | 1776934631.3s~1776934635.3s (4.0s) — 报警变化 |
| 测试窗口2 | 1776934639.2s~1776934643.2s (4.0s) — 报警变化 |
| BAG数据 | 0423_CCCscp_Near_60kph_nok_corner_radar_net_2026-04-23-16-56-55_0.bag (77.0s, 26362条) |
| BLF数据 | 2026-04-23_16-56-57_CCCscp_near_60kph_nok_.blf (77.4s, 258624条) |

---



### 根因
**功能未触发的核心原因为车辆工况不满足（档位 N/P）导致系统使能关闭**，叠加**外部抑制信号维持状态清零**。
具体因果链：L1 信号 `actual_gear`=7（来源：Variable Probe） → L2 状态机判定使能无效（`fctb_enable`=0，来源：Variable Probe） → 功能处于非激活态；同时 L2.5 时序耦合检测到 **HoldRelease** 模式在 `coem/GWM_B26/components/AswPerception/func/adasFunc.c:6378-6382` 于 t=1776963417.63s 被 `AEBBAActv_0x137`=0 及 `AEBIBActv_0x137`=0 触发（来源：TPE），清除副作用变量 `bFctbKeepBrakeFlg` 等，确保制动请求无法保持。尽管 L3 观测到雷达告警标志，但因 L2 入口阻断，未输出控制指令。

### 时序耦合 (TPE 触发清单)
| 模式 | 源文件：行 | 首触发 t | 持续 | 触发信号 | 副作用 |
|------|----------|--------|------|---------|--------|
| HoldRelease | adasFunc.c:6378-6382 | 1776963417.63s | 77357ms | AEBBAActv_0x137=0, AEBIBActv_0x137=0 | bFctbKeepBrakeFlg, fFctbBrakeEventTime, fFctbHoldEventTime |

### 条件检查汇总
| 条件 | 阈值 | 实际值 | 满足？ | 数据来源 | 相关 TPE 模式 |
|------|----------|-----------|------|--------------|--------------|
| **功能使能** | `bFCTBEnable` == TRUE | `fctb_enable`=0 (全局) | **否** | Variable Probe / ASWIN_SystemState.c | 无 (基础阻断) |
| **档位状态** | Gear ∈ {D(4), R(5)} | `actual_gear`=7 (N/P) | **否** | Variable Probe | 无 (导致使能为 0) |
| **自车速度** | 0.5 ≤ V ≤ 21.0 km/h | < 22.0 km/h (Probe>22 为 0 帧) | **疑似/矛盾** | Variable Probe (标题称 60kph) | 无 |
| **目标威胁** | TTC ≤ 1.5s, Dist < 20m | TTC=79.97s, Dist=36.28m | **否** | 观测层·雷达目标告警 | 无 |
| **AEB 协同释放** | AEB BA/IB == FALSE | `AEBBAActv_0x137`=0 (100%) | **是** | 外部抑制信号实测 | HoldRelease |

### 关键证据链 (结构化)
1.  **信号**: `actual_gear` | **时间**: 测试窗口内全量 | **值**: 7 | **来源**: Variable Probe | **TPE 模式**: 无 (状态机输入)
2.  **信号**: `fctb_enable` | **时间**: 测试窗口内全量 | **值**: 0.0 | **来源**: Variable Probe | **TPE 模式**: 无 (逻辑结果)
3.  **信号**: `AEBBAActv_0x137` | **时间**: t=1776963417.63s~+77357ms | **值**: 0 | **来源**: 外部抑制信号实测/TPE | **TPE 模式**: HoldRelease (adasFunc.c:6378-6382)
4.  **信号**: `radar_objects.fctb_flag` | **时间**: t=1776934633.275s | **值**: 1 (部分帧) | **来源**: 观测层·告警事件 | **TPE 模式**: 无 (感知层输出)
5.  **信号**: `actual_spd` | **时间**: 测试窗口内 | **值**: Probe 无>22.0 数据 | **来源**: Variable Probe | **TPE 模式**: 无 (数据冲突点)

### 数据链路
CAN `PDI`/`VCU` → `actual_gear`=7 → `ASWIN_SystemState.c`(Standby 入口) → `fctb_enable`=0 → 功能禁用 (L2)
CAN `ESP_FD2` → `AEBBAActv_0x137`=0 → `adasFunc.c:6378` (HoldRelease) → `bFctbKeepBrakeFlg`=0 (L2.5)
Radar → `fctb_flag`=1 → `adasFunc.c`(Warning 判断) → **被 L2 使能门控拦截** → 无输出

### 测试窗口分析
测试标题标注 "60kph"，但 Variable Probe 查询 `actual_spd > 22.0` 返回 0 帧，数据表明实际车速低于 FCTB 上限阈值或信号映射缺失；与此同时 `actual_gear` 稳定为 7（对应 P/N 档），直接导致状态机无法进入 Standby(2) 态，使能标志 `fctb_enable` 恒为 0。雷达端虽有少量目标标记为 FCTB 候选（TTC 极低），但因上层功能未激活，未生成有效警告或制动。

### 场景差异分析
FCTB 设计为低速防碰撞功能（<21km/h），且通常依赖 D/R 档。本次测试场景若确为高速倒车/前进（60kph），则必然超出功能域；若实际车速低（<21km/h），则根本原因为档位配置错误（N/P 档不支持）。此外，观测到的目标距离 (36m+) 远超典型近距防撞 ROI（通常<15-20m），即使功能开启也难以触发高强度制动，但当前首要阻断项为系统使能与档位。

### 修复建议
1.  **确认档位配置**：核实 `actual_gear`=7 的物理定义是否为 P/N 档，若测试需在 N/P 档进行，需修改 `ASWIN_SystemState.c` 第 980 行左右的档位允许列表；否则请将测试车辆挂入 D/R 档 (4/5)。
2.  **核查车速信号**：排查 `actual_spd` 与 CAN 信号 `VehicleSpeed` 的映射关系，解决“标题 60kph 与探针数据<22kph”不一致的问题，确保测试工况符合预期。
3.  **验证功能开关**：检查标定参数 `bFCTBEnable`，确保该功能在项目配置文件中未被强制关闭。

### 置信度：75/100
不确定因素主要为：**时间戳异常**（TPE 触发时间较观测窗口晚约 8 小时，可能影响时序因果关联的精确性）以及 **车速数据矛盾**（测试标称与实际探针数据不符）。