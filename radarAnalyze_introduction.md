# radarAnalyze — 角雷达 ADAS 自动化诊断分析系统

> 对汽车角雷达 ADAS 功能的录制数据做**自动化根因分析**，定位报警不触发/误触发/退出异常等问题。

---

## 目录

1. [系统概览](#一系统概览)
2. [目标平台与覆盖功能](#二目标平台与覆盖功能)
3. [输入数据](#三输入数据)
4. [整体架构](#四整体架构)
5. [数据解析层 — parsers/](#五数据解析层)
6. [知识缓存层 — source_docs/](#六知识缓存层)
7. [记忆系统 — memory/](#七记忆系统)
8. [核心分析引擎 — ai/](#八核心分析引擎)
9. [诊断管线 — 15 步全流程](#九诊断管线)
10. [专家面板 — 5 专家 3 轮研讨](#十专家面板)
11. [时序模式引擎 — TPE](#十一时序模式引擎)
12. [动态变量探测](#十二动态变量探测)
13. [上下文预算管理 — ContextBudget](#十三上下文预算管理)
14. [代码学习引擎 — CodeLearner](#十四代码学习引擎)
15. [模型路由 — ModelRouter](#十五模型路由)
16. [可视化报告 — Visualizer](#十六可视化报告)
17. [AutoDream — 自进化机制](#十七autodream自进化机制)
18. [三种运行模式](#十八三种运行模式)
19. [技术栈](#十九技术栈)
20. [核心创新点](#二十核心创新点)

---

## 一、系统概览

radarAnalyze 是一个 **AI 驱动的角雷达问题分析系统**。

用户只需提供：
- **录制数据**（`.bag` / `.blf` 文件）
- **问题描述**（例如："RCTA 没有触发"）
- **期望行为**（例如："应该触发 RCTA 报警"）

系统自动完成从数据解析、源码分析、信号追踪到根因定位的**全链路诊断**，最终输出结构化报告（Markdown + HTML 交互式图表）。

整个流程无需人工干预 —— 从 CAN 信号到代码逻辑、从感知数据到状态机判断，全部自动化追溯。

---

## 二、目标平台与覆盖功能

**硬件平台**：TI AWR2E44P 角雷达
**软件平台**：cr60_light (GWM_B26 COEM 定制层)
**代码仓**：`D:\cr60_light`

**覆盖 8 大 ADAS 功能**：

| 类别 | 功能 | 说明 |
|------|------|------|
| 后角 | BSD | 盲区检测 |
| 后角 | LCA | 变道辅助 |
| 后角 | DOW | 开门预警 |
| 后角 | RCW | 后方碰撞预警 |
| 后角 | RCTA | 后方交叉交通警报 |
| 后角 | RCTB | 后方交叉交通制动 |
| 前角 | FCTA | 前方交叉交通警报 |
| 前角 | FCTB | 前方交叉交通制动 |

**统一状态机**：所有功能共享 7 态状态机
- `0=None, 1=Init, 2=Standby, 3=Active, 4=Off, 5=Failure, 6=Passive`

---

## 三、输入数据

### 1. ROS Bag 文件 (`.bag`)

录制自 ROS1 节点，包含以下消息类型：

| Topic | 消息类型 | 内容 |
|-------|----------|------|
| `/wf/corner_radar/lgu_data_{1-4}` | `wfAutosarData` | 4 路角雷达 AUTOSAR 数据（目标 + 调试信息） |
| `/wf/objectlist_{1-4}` | `wfObjectMsg` | 4 路目标列表 |
| `/wf/ego_car_info/front_left|right/parsed` | `egoCarInfo` | 自车信息（速度/档位/加速度/航向角等 69 个字段） |
| `/corner_radar/warning_status_raw` | `UInt8MultiArray` | 报警状态原始数据（15 字节 = 8 功能 × 左右） |

### 2. CAN 日志文件 (`.blf`)

Vector CAN 录制格式，包含所有 CAN 总线信号。配合 DBC 文件解码。

### 3. DBC 文件

| 文件 | 用途 |
|------|------|
| `CR_DBC_V3.2_20260331.dbc` | 主 DBC |
| `GAC_CR_FR&FL_Private_CAN_V1.3.dbc` | 前角私有 CAN |
| `GWM_RearCorner_Pri_V3.0 (1).dbc` | 后角私有 CAN |

---

## 四、整体架构

```
+---------------------------------------------------------------------+
|                        cli.py (统一入口)                             |
|   3 种模式: diagnosis / query / dream                               |
+---------------------------------------------------------------------+
                                 |
+---------------------------------------------------------------------+
|                   orchestrator.py (诊断管线总编排)                    |
|   15+ 步串联执行，ContextBudget 管理 60K 字符预算                     |
+---------------------------------------------------------------------+
        |               |                |                |
+-------+-------+--+---+--------+--+----+---------+--+---+--------+
| 纯规则模块    |  AI 驱动模块  | 基础设施模块  |  输出模块  |
|              |               |               |            |
| frame_       | problem_      | model_        | visualizer |
| analyzer     | classifier    | router        | (Plotly)   |
|              |               |               |            |
| test_window_ | condition_    | context_      |            |
| detector     | extractor     | budget        |            |
|              |               |               |            |
| temporal_    | variable_     | utils         |            |
| analyzer     | query_planner |               |            |
|              |               |               |            |
| signal_      | expert_panel  |               |            |
| mapper       | data_query_   |               |            |
|              | engine        |               |            |
| pattern_     | code_learner  |               |            |
| extractor    |               |               |            |
|              |               |               |            |
| causal_      |               |               |            |
| aligner      |               |               |            |
|              |               |               |            |
| parameter_   |               |               |            |
| analyzer     |               |               |            |
|              |               |               |            |
| data_probe   |               |               |            |
|              |               |               |            |
+--------------+---------------+---------------+------------+
        |               |                |
+-------+---------------+----------------+------------------+
|           memory/ (6 层记忆系统)     source_docs/ (缓存)   |
|  L1: project.md                      功能概述 MD           |
|  L2: functions/{FUNC}.json           信号映射 JSON         |
|  L3: patterns.json                   条件树 JSON           |
|  L4: sessions/                       代码模式 JSON         |
|  L5: cases/*/memory.json             参数表 JSON           |
|  L6: code_knowledge/                 变量链 JSON           |
+-------------------------------------+---------------------+
        |
+-------+-----------------------------------------------+
|           parsers/ (数据解析层)                        |
|  bag_parser / blf_parser / dbc_loader /               |
|  frame_store (SQLite) / time_sync / case_loader       |
+-------------------------------------------------------+
```

---

## 五、数据解析层

### 5.1 BagParser — ROS Bag 解析器

**核心能力**：读取 ROS1 Bag，对 4 种消息类型进行**手工反序列化**：

| 消息类型 | 解析内容 | 结构大小 |
|----------|---------|---------|
| `wfAutosarData` | outputData 中的目标数组（36 字节/目标）+ 调试信息（144 字节尾部） | 固定 728 字节 |
| `wfObjectMsg` | 目标数组（185 字节/目标） | 变长 |
| `egoCarInfo` | 69 个字段（Header + 自车状态 + 4 组轨迹输出） | 固定 |
| `UInt8MultiArray` | 报警状态原始字节（16 字节：radar_id + 8 功能 × 2 方向） | ≥ 16 字节 |

**关键设计**：
- 解码失败时**静默降级**为 `raw_hex` 预览，不中断流程
- 对象过滤：仅保留距离 > 50cm、有警告标志、或生命周期 > 3 的目标
- 支持按 topic 过滤和跳过图像数据（性能优化）

### 5.2 BlfParser — CAN 日志解析器

**核心能力**：
- 使用 `python-can` 的 `BLFReader` 遍历帧
- 可选 `DbcLoader` 按 CAN ID 解码信号
- 产出 `CanFrame` 迭代器或按信号时间线

### 5.3 DbcLoader — 多 DBC 管理器

**核心能力**：
- 使用 `cantools` 加载多个 DBC 文件
- **同 frame_id 先到者优先**，冲突记录到 `conflicts` 列表
- 解码失败时自动截断到 `msg.length` 再试

### 5.4 FrameStore — SQLite 内存数据库

**核心能力**：将所有数据统一存储为 5 张表，支持 SQL 查询：

| 表名 | 内容 | 关键索引 |
|------|------|---------|
| `bag_frames` | ROS 消息帧（含 JSON 字段） | timestamp_ns + topic 去重 |
| `can_frames` | CAN 帧（含解码信号 JSON） | timestamp + can_id 去重 |
| `radar_objects` | 雷达目标（含 8 功能警告标志） | timestamp + radar_id + obj_id 去重 |
| `radar_debug` | 调试快照（自车状态 + 使能标志） | timestamp + radar_id 去重 |
| `warning_events` | 预计算的报警事件（按 500ms 间隙切分） | func_name + timestamp |

**公开查询接口**：按时间窗口查目标/调试数据、按 CAN ID 查信号、查目标轨迹、查信号时间线等。

### 5.5 TimeSync — 时间对齐

BAG（纳秒时间戳）与 BLF（Unix 秒时间戳）的对齐：
- 优先使用手动偏移 `manual_offset_sec`
- 否则对齐首帧：`offset = blf_start - bag_start/1e9`
- 默认偏移为 0

### 5.6 CaseLoader — 一键加载

串联所有解析器，从案例目录自动发现 `.bag` 和 `.blf` 文件，产出统一的 `CaseLoadResult`：
- `store`: FrameStore（SQLite）
- `bag_meta`: Bag 元数据
- `blf_meta`: BLF 元数据
- `sync`: TimeSync 对象
- `dbc`: DBC 加载器

---

## 六、知识缓存层

`source_docs/` 目录存放从源码提取和 AI 生成的缓存知识。所有缓存都有**失效机制**，源码变更后自动刷新。

### 缓存文件一览

| 文件 | 生成方式 | 缓存失效机制 |
|------|---------|-------------|
| `{FUNC}.md` (×8) | AI 生成 | 源码片段 hash 变更 |
| `signal_mapping.json` | 正则解析 | SHA256 前 16 位 |
| `output_mapping.json` | 正则解析 | SHA256 前 16 位 |
| `variable_chains.json` | 正则解析 | **无缓存**，每次重写 |
| `{FUNC}_conditions.json` (×8) | AI 提取 | 源码文件 mtime 比较 |
| `code_patterns.json` | 正则提取 | 源码目录 hash |
| `parameters.json` | 正则提取 | 源码 SHA1 |
| `signal_chain.md` | 确定性生成 | 随 signal_mapping 重建 |

### 信号映射 (signal_mapping.json)

从 `RteComMapping.c` 中用纯正则提取 CAN <-> 内部变量双向映射，91+ 条映射关系。支持：
- `internal_to_can`: 内部变量名 → CAN 信号名
- `can_to_internal`: CAN 信号名 → 内部变量名
- `fullpath_to_can`: 完整路径 → CAN 信号名

### 条件树 ({FUNC}_conditions.json)

AI 从源码提取的结构化条件树，包含：
- 状态机状态值与转移条件
- 目标筛选条件
- 使能条件
- 自车/目标速度范围
- **外部抑制信号**（含极性：抑制触发条件 vs 正常值）
- 其他条件

---

## 七、记忆系统

### 6 层记忆架构

| 层级 | 存储 | 内容 | 用途 |
|------|------|------|------|
| **L1** | `project.md` | 项目全局记忆 | 架构知识、通用规则、重大发现 |
| **L2** | `functions/{FUNC}.json` | 各功能知识 | 已知问题、状态机定义、故障模式 |
| **L3** | `patterns.json` | 故障模式库 | 跨功能的根因模式（MD5 去重） |
| **L4** | `sessions/` | 诊断会话记录 | 每次诊断的完整步骤和发现 |
| **L5** | `cases/*/memory.json` | 案例级记忆 | 每个案例的诊断结论 |
| **L6** | `code_knowledge/` | 源码学习结果 | 结构化代码知识（4 维度 × 8 功能） |

### L6 代码知识 — 核心知识库

L6 是根因分析的"黄金标准"，包含 4 个维度的结构化知识：

| 维度 | 内容 |
|------|------|
| `alarm_logic` | 报警触发/取消/退出条件、迟滞、延时、抑制逻辑 |
| `calculation_chain` | 关键变量计算流程（TTC/TTM/距离/速度/ROI 派生） |
| `output_chain` | 外发链路（内部变量 → RteComMapping → CAN 信号 → 下游） |
| `state_machine` | 状态流转、入口/出口动作、双状态机交互 |

### 上下文拼装

`build_context_for_diagnosis()` 将 L1-L6 记忆组合为诊断上下文：
- L1（截断 2000 字符）+ L2（截断 3000 字符）+ L6 渲染 + L3 相似模式（最多 3 条）+ L5（截断 1500 字符）
- 结果缓存于 `_ctx_cache`，避免重复拼装

---

## 八、核心分析引擎

### 8.1 Orchestrator — 诊断编排器

**定位**：整个诊断管线的"大脑"，串联 15+ 步骤，协调所有子模块。

**关键成员**：
- `self.router`: ModelRouter（模型路由）
- `self.memory`: MemorySystem（记忆系统）
- `self.config`: 全局配置

**核心方法**：
```python
def run_diagnosis(case_dir, problem, expected, on_status=None) -> str:
    """完整诊断管线，返回报告路径"""
```

### 8.2 FrameAnalyzer — 帧级证据提取

**定位**：纯规则模块，从 FrameStore 中提取结构化证据，不调用 AI。

**提取内容**：
- `KEY_FACTS`: 关键事实（状态分布、警告状态、自车速度等）
- `timeline`: 数据时间线（最多 200 行）
- `state_transitions`: 状态跳变（最多 20 条）
- `warning_states`: 警告状态快照（最多 60 条）
- `ego_*`: 自车速度统计
- `radar_objects_warned`: 触发警告的目标（最多 100 条）
- `can_summary`: CAN 信号摘要（前 15 条）

**抽样策略**：无窗口时按 50 帧抽样，有窗口时只提取窗口内数据。

### 8.3 TestWindowDetector — 测试窗口检测

**定位**：纯规则模块，从长录制中自动定位测试活跃时段。

**6 种事件检测**：
- `target_appear/disappear`: 目标出现/消失（速度 > 0.5m/s 或距离 > 0.3m，连续 ≥ 3 帧）
- `state_change`: 系统状态跳变
- `warning_on/off`: 警告字段变化
- `speed_up/down`: 速度穿越阈值
- `warning_edge_on/off`: 从 warning_events 表
- `object_approach`: 目标快速接近（距离减半）

**流程**：事件检测 → ±2s padding → 区间合并 → 回退（无事件时取最活跃点 ± 5s）

### 8.4 SignalMapper — 信号映射器

**定位**：纯正则解析 `RteComMapping.c`，建立 CAN <-> 内部变量双向映射。

**6 级优先级解析**：
1. `internal_to_can` 精确匹配
2. `fullpath_to_can` 精确匹配
3. 点路径最后一段
4. struct_aliases 前缀展开
5. 大小写不敏感
6. 核心子串（≥ 5 字符）双向 in 匹配

### 8.5 ConditionExtractor — 条件提取器

**定位**：AI 驱动模块，从源码提取结构化条件树。

**工作流程**：
1. 读取相关源码文件
2. 调用 `router.complex()` 生成条件树 JSON
3. 确定性后处理（极性修正、CAN 信号解析）

**输出**：`{FUNC}_conditions.json`，含状态机、目标筛选、速度范围、外部抑制信号等。

### 8.6 ProblemClassifier — 任务分类器

**定位**：AI 驱动模块，将用户问题分类为 4 种任务类型。

| 类型 | 说明 | 额外步骤 |
|------|------|---------|
| `diagnose` | 问题诊断 | 专家面板 |
| `tune` | 参数调优 | 参数敏感性 + what-if |
| `verify` | 验证确认 | 参数敏感性 + what-if |
| `query` | 数据查询 | 轻量查询引擎 |

### 8.7 ParameterAnalyzer — 参数分析器

**定位**：纯规则模块，做阈值扫描和敏感性分析。

**能力**：
- 扫描源码中的阈值参数
- 敏感性分析：假设某个参数变化 X%，看是否影响诊断结果
- what-if 模拟：修改参数值后重新评估条件

### 8.8 DataProbe — 数据探针

**定位**：纯规则模块，无业务知识的通用数据查询引擎。

**核心能力**：
- 支持算术表达式（`dist_y + 0.25 * obj_length`）
- 支持过滤（`in_window and dist_x < 0`）
- 支持分组统计（按 `side` 分组）
- 返回统计指标：count/min/max/mean/std/p10/p50/p90

**安全表达式求值**：使用 `asteval`（非 Python `eval`），仅允许表列名和内置语义字段。

### 8.9 VariableQueryPlanner — 变量查询规划器

**定位**：AI 驱动模块，根据问题动态规划需要查询哪些变量。

**核心思想**：不硬编码统计逻辑，而是让 AI 基于：
- 用户问题描述
- L6 代码知识
- 功能条件树

自动生成查询计划（最多 6 条），再由 `DataProbe` 执行。这是"按需证据采集"的核心机制。

### 8.10 Visualizer — 可视化报告

**定位**：生成独立的 HTML 交互式报告。

**图表类型**：
- 自车速度曲线
- 输出信号时间线
- 状态机状态变化
- TPE 触发事件标记
- 参数敏感性热力图（tune/verify 模式）
- what-if 对比图（tune/verify 模式）
- 目标轨迹散点图

**设计目标**：
- 离线可用（plotly.js 内联，无需网络）
- 数据优先（即使 AI 结论有误，用户也能从图表反推）
- 通用模板（不针对特定功能硬编码）

---

## 九、诊断管线

完整的 15 步诊断流程：

```
Step 1  ─ init            ─ 确保 source_docs 存在 (CodeLearner + signal_mapping)
Step 2  ─ understand      ─ 问题理解 (LLM complex) → func_info
Step 3  ─ classify        ─ 任务分类 (LLM simple) → diagnosis/tune/verify/query
Step 4  ─ parse           ─ 数据解析 (case_loader) → FrameStore + 元数据
Step 5  ─ detect_window   ─ 窗口检测 (纯规则) → 测试活跃时段
Step 6  ─ analyze         ─ 帧级分析 (纯规则) → 结构化证据
Step 7  ─ conditions      ─ 条件提取 (LLM complex) → 条件树 JSON
Step 8  ─ tpe             ─ 时序模式引擎 (纯规则) → 因果对齐证据
Step 9  ─ probe           ─ 变量探测 (LLM chat + DataProbe) → 按需统计
Step 10 ─ suppression     ─ 抑制信号检查 (纯规则) → 外部抑制分析
Step 11 ─ output_signals  ─ 输出信号分析 (纯规则) → 输出链路追溯
Step 12 ─ (内部)          ─ 加载阈值参考 (≤ 4000 字符)
Step 13 ─ params          ─ 参数敏感性 (仅 tune/verify) → 敏感性报告
Step 14 ─ diagnose        ─ 专家面板 (LLM complex × 3 轮) → 最终诊断
Step 15 ─ report          ─ 生成 Markdown 报告 + 专家附录
Step 16 ─ visualize       ─ 生成 HTML 交互式报告
Step 17 ─ done            ─ 更新记忆 (L1-L6) + 完成会话
```

**纯规则 vs AI 调用比例**：
- 纯规则步骤：7 步（解析、窗口、分析、TPE、抑制、输出、报告）
- AI 驱动步骤：5 步（理解、条件、探测、专家面板 × 3 轮）
- 总计约 10-15 次 AI 调用（取决于 fail_type 和专家数量）

---

## 十、专家面板

### 架构

5 位领域专家，3 轮研讨，主持人仲裁：

| 专家 | 领域 | 核心文件 |
|------|------|---------|
| 🔗 信号链路专家 | CAN 信号 → 内部变量映射 | RteComMapping.c/h |
| ⚙️ 算法逻辑专家 | adasFunc.c 报警条件与阈值 | adasFunc.c/h, paraDefine.h |
| 🔄 系统状态专家 | 双状态机与功能使能 | ASWIN_SystemState.c/h |
| 👁️ 感知与目标专家 | 目标属性与过滤 | objAttribCal.c, track.c, postProcess.c |
| 📡 架构专家 | 左右雷达与输出合并 | ASWOUT_OutCalc.c |

### 3 轮研讨流程

**Round 1：独立分析（并发）**
- 每位专家独立分析相同的数据
- 使用线程池并发执行（最多 5 线程）
- 基于结构化条件表 + 数据时间线 + 关键事实

**Round 2：交叉审查 + 主持人质疑**
- 主持人（Moderator）阅读所有专家意见
- 提出质疑问题（针对矛盾点、证据不足处）
- 被质疑的专家并发回应

**Round 3：收敛 → 最终结论**
- 主持人综合所有意见
- 输出最终判决（final_verdict）

### 智能专家选择 (V3)

根据 `fail_type` 自动选择相关专家子集，减少 AI 调用：

| 故障类型 | 选择专家 |
|----------|---------|
| FP（误报） | 信号链路 + 算法逻辑 + 感知 |
| FN（漏报） | 算法逻辑 + 系统状态 + 感知 |
| DELAY（延迟） | 算法逻辑 + 感知 + 架构 |
| STATE（状态异常） | 系统状态 + 信号链路 + 算法逻辑 |
| OTHER（其他） | 全部 5 位 |

### 因果链五层模型

主持人使用的追溯框架：

```
L4  外部表现 → 告警未触发/误触发（用户看到的问题）
    ↓
L3  雷达观测 → radar_objects 中的告警标志、ADAS 使能状态
    ↓
L2.5 时序耦合 → 代码中的"保持-释放/累积-清零/防抖/滞回"等行为模式
    ↓
L2  ECU 逻辑 → adasFunc.c 中的条件判断、状态机跳变
    ↓
L1  信号输入 → CAN 信号值 → RteComMapping → 内部变量
```

根因 = L1 信号 × L2.5 时序耦合点 × L2 代码分支

---

## 十一、时序模式引擎 (TPE)

### 定位

TPE 是系统的**核心创新** —— 将代码中的行为模式与数据中的时序信号做因果对齐。

### 三模块架构

```
PatternExtractor (代码侧)    ──→ CodePattern
        │                              │
        └────→ CausalAligner ←────┘    │
                     │                 │
TemporalAnalyzer (数据侧)  ──→ TemporalFeature
```

### 1. PatternExtractor — 代码行为模式提取

从 C 源码中正则提取 4 类行为模式：

| 模式类型 | 说明 | 示例 |
|---------|------|------|
| `hold-release` | 保持-释放计时器 | HoldRelease 计数器 + 清零条件 |
| `accumulate-reset` | 累积-清零 | 连续计数 + 归零条件 |
| `debounce` | 防抖 | 边沿检测 + 延迟确认 |
| `hysteresis` | 滞回 | 不同上下阈值 |

每个模式包含：触发条件、触发变量、后果变量、代码位置。

### 2. TemporalAnalyzer — 数据时序分析

对 CAN 信号时间线计算时序特征：

| 特征 | 说明 |
|------|------|
| 边沿检测 | 信号从 0→1 或 1→0 的跳变点 |
| 段分析 | 连续高/低电平的时间段 |
| 统计 | 均值、占比、持续时间 |
| 模式标签 | 脉冲、持续、间歇等 |

### 3. CausalAligner — 因果对齐

将代码模式与数据特征做时间区间交集对齐：

| 裁决 | 说明 |
|------|------|
| `triggered` | 数据时序与代码模式匹配 |
| `not_triggered` | 数据时序不匹配 |
| `insufficient_data` | 数据不足以判断 |
| `unknown` | 变量无法映射到 CAN 信号 |

### 输出

`TPEResult` 包含：
- 触发/未触发的模式证据列表
- 时序特征（每个参与信号的统计）
- 未解析变量（无法映射到 CAN 的内部变量）
- 缺失 CAN 信号（映射到了但数据中不存在的信号）

---

## 十二、动态变量探测

### 设计理念

**"禁止单点硬编码统计，必须使用动态变量探测"** —— 这是系统的核心原则。

传统方案：在 `FrameAnalyzer` 中硬编码每个功能的统计逻辑（如 FCTB 需要查 `ttc < 2.0` 的帧数）。

本系统方案：让 AI 根据具体问题**动态规划查询**，再由 `DataProbe` 执行统计。

### 工作流程

```
用户问题 + L6 代码知识 + 条件树
         │
         ▼
  VariableQueryPlanner (AI)
         │
         ▼
  QueryPlan × N (最多 6 条)
         │
         ▼
  DataProbe (执行)
         │
         ▼
  ProbeResult (统计结果)
         │
         ▼
  注入 Expert Panel prompt
```

### 示例查询计划

```python
# AI 规划的查询
{
    "question": "测试窗口内 TTC < 2.0s 的帧占比",
    "table": "radar_objects",
    "field": "ttc",
    "filter": "in_window and ttc > 0 and ttc < 2.0",
    "group_by": None,
    "stats": ["count", "min", "p50", "max"]
}
```

---

## 十三、上下文预算管理 (ContextBudget)

### 解决的问题

专家面板和 problem-understanding 需要组合大量证据（记忆上下文、数据摘要、时间线、TPE 结果、抑制分析等）。如果没有全局预算控制，prompt 可能膨胀到 80KB+，导致：
- 模型注意力被稀释
- Token 成本线性增加
- 超出远端模型上下文窗口

### 设计

- **总预算**：60,000 字符（软上限）
- **优先级系统**：每个证据块有 priority（0-100）和 min_chars 保底
- **贪婪裁剪**：超出预算时，先裁剪低优先级块

### 优先级表

| 优先级 | 内容 | 保底 |
|--------|------|------|
| 100 | KEY_FACTS / timeline | 8000 |
| 80 | TPE 结果 / 抑制 / 输出信号 | 各 2000 |
| 70 | 记忆上下文 (L1-L6) | 3000 |
| 60 | 阈值参考 | 1500 |
| 40 | 条件文本 | 1000 |
| 20 | 参数分析 | 500 |

---

## 十四、代码学习引擎 (CodeLearner)

### 定位

项目中**唯一**负责"读源码、抽知识"的模块。

### 两个公共入口

| 入口 | 场景 | 输出 |
|------|------|------|
| `learn(pairs_budget)` | 增量学习，由 auto-dream 调用 | `memory/code_knowledge/{FUNC}.json` |
| `ensure_overview_docs(funcs)` | 一次性概览，由 orchestrator 启动时调用 | `source_docs/{FUNC}.md` |

### 四大学习焦点

| 焦点 | 内容 |
|------|------|
| `alarm_logic` | 报警触发/取消/退出条件、迟滞、延时、抑制 |
| `calculation_chain` | 关键变量计算流程（TTC/TTM/距离/速度/ROI 派生） |
| `output_chain` | 外发链路（内部变量 → RteComMapping → CAN 信号 → 下游） |
| `state_machine` | 状态流转、入口/出口动作、双状态机交互 |

### 学习机制

1. **Hash 缓存**：源码未变动则跳过已学的 (func, focus) 对
2. **焦点轮转**：按 `learning_state.json` 游标推进
3. **增量合并**：新条目按 id 去重，内容变更时覆盖旧值
4. **冷启动自适应**：首次学满 8 对，后续每次学 2 对

### 常量学习

全局数值常量抽取（自车宽度、ROI 边界、功能阈值）：
- 源头：`paraDefine.h` / `dotCalibDefine.h` / `globalVarDefine.h` / `perception_public_def.h`
- Hash 未变 → 零 token 跳过
- 输出：`memory/code_knowledge/constants.json`

---

## 十五、模型路由 (ModelRouter)

### 双模型架构

| 模型 | 用途 | API |
|------|------|-----|
| **本地** (Ollama + qwen3-coder) | 简单任务（格式化、摘要、变量查找） | `http://localhost:11434/v1` |
| **远端** (Qwen3.5-27B-FP16) | 复杂分析（诊断、推理、因果链） | `http://10.190.179.61:11999/qwen3_5/v1` |

### Thinking 模式

Qwen3.5 专属能力，三档可调：

| 模式 | 说明 | 适用场景 |
|------|------|---------|
| `off` | 全部关闭 | 日常诊断（推荐） |
| `synth` | 仅 Round 3 综合收敛开启 | 平衡质量与速度 |
| `full` | 所有 complex 调用开启 | 深度分析（慢 3-5 倍） |

### 复杂度自动判断

`complexity="auto"` 时根据消息长度和是否有 tools 自动选择简单/复杂模型。

---

## 十六、可视化报告 (Visualizer)

### 输出

单文件 HTML 报告（`report.html`），内联 plotly.js，无需网络连接。

### 图表类型

| 图表 | 数据源 | 说明 |
|------|--------|------|
| 自车速度曲线 | `radar_debug.car_spd` | 叠加测试窗口高亮 |
| 输出信号时间线 | `can_frames` | 解码后的 CAN 信号时序 |
| 状态机状态变化 | `radar_debug.*_state` | 7 态状态变化阶梯图 |
| TPE 触发事件 | `TPEResult.evidence` | 在时间线上标记触发点 |
| 参数敏感性 | `SensitivityReport` | 热力图（仅 tune/verify） |
| what-if 对比 | `WhatIfEntry` | 修改前后的对比柱状图 |
| 目标轨迹 | `radar_objects` | 散点图 + 速度矢量 |

### 设计原则

- **数据优先**：即使用户不完全相信 AI 结论，也能从图表中自行验证
- **通用模板**：同一套 HTML 模板服务于所有 8 功能和 4 种任务类型
- **专业排版**：蓝灰色系、卡片式布局、粘性目录

---

## 十七、AutoDream 自进化机制

### 触发条件

满足以下任一条件时自动触发：
- 距上次 dream ≥ 4 小时
- 积累 ≥ 2 个新会话

### 5 阶段流程

| 阶段 | 名称 | 内容 |
|------|------|------|
| Phase 0 | Study | 代码学习：增量学习源码 → L6 JSON |
| Phase 1 | Orient | 定向：刷新变量链、收集全部记忆上下文 |
| Phase 2 | Gather | 收集：获取最近 10 条会话 |
| Phase 3 | Consolidate | 整合：AI 统一分析，输出知识更新 |
| Phase 4 | Apply | 应用：写入 L1/L2/L3 记忆 |

### 并发控制

- `.dream-lock` 锁文件，1 小时超时自动释放
- dream 期间不阻止 orchestrator 直接写 L2/L3/L5

### 知识进化

每次 dream 后，系统会：
- 更新 `project.md`（L1 项目记忆）
- 更新各功能的 `known_issues`（L2）
- 添加/删除故障模式（L3）
- 合并冲突发现

---

## 十八、三种运行模式

### 1. Diagnosis 模式（完整诊断）

```bash
py -3.11 cli.py cases/sc6hrcta001 -p "RCTA没有触发" -e "应该触发"
```

执行完整的 15 步管线，输出：
- `report.md` — Markdown 诊断报告
- `report.html` — HTML 交互式图表
- `expert_opinions.md` — 专家意见附录

### 2. Query 模式（轻量查询）

```bash
py -3.11 cli.py cases/sc6hrcta001 -q "FCTB触发时AEBIB是否激活"
```

轻量数据查询管线：
- 解析数据 → 扫描信号 → AI 理解问题 → 提取数据 → AI 回答

### 3. Dream 模式（记忆整合）

```bash
py -3.11 cli.py --dream
```

强制触发 AutoDream，整合最近的诊断经验到知识库。

---

## 十九、技术栈

### 核心依赖

| 包 | 用途 |
|----|------|
| `rosbags` | ROS Bag v1 读取 |
| `python-can` | CAN/BLF 读取 |
| `cantools` | DBC 解码 |
| `openai` | AI 模型调用（兼容 API） |
| `pandas` | 数据处理 |
| `sqlite3` | 内置数据库 |
| `plotly` | HTML 交互式图表 |
| `rich` | 终端美化输出 |
| `asteval` | 安全表达式求值 |
| `pyyaml` | 配置文件解析 |
| `python-dotenv` | 环境变量管理 |

### AI 模型

| 模型 | 供应商 | 上下文 | 并发 |
|------|--------|--------|------|
| Qwen3.5-27B-FP16 | 远端 vLLM | 131K tokens | 24 |
| qwen3-coder | 本地 Ollama | 取决于配置 | 1 |

---

## 二十、核心创新点

### 1. 全链路闭环追溯

CAN 信号 → 内部变量 → 条件判断 → 状态机 → 输出信号，每一步都可追溯。

### 2. 时序模式引擎 (TPE)

代码行为模式（hold-release、debounce 等）与 CAN 信号时序做因果对齐，自动检测时序耦合点。

### 3. 动态变量探测

AI 根据问题动态规划查询，而非硬编码统计逻辑。

### 4. 五层因果链模型

从外部表现到信号输入的 5 层追溯框架，确保根因不停在观测层。

### 5. 5 专家 3 轮研讨

多专家独立分析 + 交叉审查 + 收敛判决，模拟人类专家组诊断流程。

### 6. 六层记忆系统

L1-L6 分层记忆，AutoDream 自动整合，系统越用越聪明。

### 7. 上下文预算管理

60K 字符全局预算 + 优先级裁剪，确保 AI prompt 高质量且不超限。

### 8. 代码知识自动化

4 维度 × 8 功能的结构化代码知识，源码变更后自动增量学习。

---

*文档生成日期：2026-05-21*
*基于代码实现文档 IMPLEMENTATION.md 及各模块 AGENTS.md*
