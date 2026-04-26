# radarAnalyze — Corner Radar AI 诊断工具

> 面向角雷达 ADAS 录制数据的端到端 AI 根因分析系统：自动加载 BAG/BLF → 解码信号 → 检测测试窗口 → 提取条件树 → 时序模式对齐 → 多专家面板研讨 → 输出可视化报告。

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-Internal-lightgrey.svg)](#)
[![Status](https://img.shields.io/badge/status-active-success.svg)](#)
[![ADAS Functions](https://img.shields.io/badge/ADAS-BSD%20%7C%20LCA%20%7C%20DOW%20%7C%20RCW%20%7C%20RCTA%20%7C%20RCTB%20%7C%20FCTA%20%7C%20FCTB-blue)](#)

---

## 目录

- [项目背景](#项目背景)
- [核心特性](#核心特性)
- [系统架构](#系统架构)
- [运行模式](#运行模式)
- [诊断管线](#诊断管线15-步)
- [六层记忆系统](#六层记忆系统)
- [快速开始](#快速开始)
- [使用示例](#使用示例)
- [配置说明](#配置说明)
- [项目结构](#项目结构)
- [依赖](#依赖)
- [输出报告](#输出报告)
- [开发者指南](#开发者指南)
- [常见问题](#常见问题-faq)
- [贡献与维护](#贡献与维护)

---

## 项目背景

`radarAnalyze` 是一套面向**角雷达（Corner Radar）** ADAS 功能的自动化诊断工具，专门解决以下场景中的根因定位难题：

- **目标平台**：TI AWR2E44P（项目代码 `cr60_light`，对应 GWM_B26 COEM 工程）
- **8 个 ADAS 功能**：
  - **后角（Rear）**：`BSD` 盲区检测、`LCA` 变道辅助、`DOW` 开门预警、`RCW` 后方碰撞预警、`RCTA` 后方交叉交通警报、`RCTB` 后方交叉交通制动
  - **前角（Front）**：`FCTA` 前方交叉交通警报、`FCTB` 前方交叉交通制动
- **典型问题**：误报（FP）、漏报（FN）、报警延迟（DELAY）、状态异常（STATE）等
- **数据来源**：ROS Bag（雷达内部信号）+ Vector BLF（CAN 总线信号）

传统人工分析需要工程师手动对齐多源时序数据、通读上千行 C 源码、反复推演状态机跳变。本工具通过 **AI 编排 + 时序模式引擎 + 多专家面板** 的方式，将 30~60 分钟的诊断工作自动化为分钟级流程，并以结构化报告输出根因、证据链与修复建议。

---

## 核心特性

### 智能化分析

- **15+ 步自动化诊断管线**：从问题理解到 HTML 可视化报告，端到端自动化
- **5 位 AI 专家 × 3 轮研讨**：信号链路 / 算法逻辑 / 系统状态 / 感知目标 / 架构 五位专家独立分析 → 主持人交叉质疑 → 综合收敛
- **时序模式引擎（TPE）**：从 C 源码自动抽取 `HoldRelease`/`Accumulate` 等模式，并与录制数据时序做因果对齐
- **动态变量探测（Variable Probe）**：AI 根据问题动态规划 SQL 查询，避免硬编码统计逻辑

### 数据处理

- **BAG/BLF 双模解析**：手工反序列化 `wfAutosarData` / `wfObjectMsg` / `egoCarInfo` / `UInt8MultiArray`，DBC 解码 CAN 帧
- **统一 SQLite 存储**：5 张表（bag_frames / can_frames / radar_objects / radar_debug / warning_events）+ 完整索引
- **时间同步**：BAG（ns 级）↔ BLF（epoch 秒）自动对齐
- **多 DBC 路由**：先到者优先 + 冲突记录

### 知识管理

- **6 层记忆体系**：项目知识 / 功能知识 / 模式库 / 会话日志 / 案例记忆 / 代码知识
- **代码学习系统**：8 功能 × 4 焦点 = 32 个 (func, focus) 槽位增量学习，源码 hash 跳过
- **Auto-Dream 整合**：定时把会话经验回写到长期记忆，形成知识闭环

### 工程化

- **本地/远程双模型路由**：简单任务走本地 Ollama，复杂任务走远端 Qwen3.5
- **字符级 ContextBudget**：60K 字符软上限，按 priority 自动裁剪
- **多级缓存**：SHA256 / mtime / 片段 hash 三种失效策略

---

## 系统架构

```
┌──────────────────────────────────────────────────────────────────┐
│                          cli.py (入口)                            │
│        diagnosis  │  query  │  dream  │  learn-constants         │
└────────┬───────────┬─────────────┬──────────────┬───────────────┘
         │           │             │              │
         ▼           ▼             ▼              ▼
┌──────────────┐ ┌─────────────┐ ┌──────────┐ ┌──────────────┐
│ Orchestrator │ │ DataQuery   │ │ AutoDream │ │ CodeLearner │
│  (15+ 步)    │ │  Engine     │ │ (Phase0-4)│ │ (常量学习)  │
└──────┬───────┘ └──────┬──────┘ └─────┬────┘ └──────┬──────┘
       │                │              │              │
       └────────────────┼──────────────┼──────────────┘
                        ▼              ▼
        ┌────────────────────────────────────────┐
        │      ai/ — 18 个分析模块                 │
        │  TPE / FrameAnalyzer / ExpertPanel ... │
        └──────────┬─────────────────────────────┘
                   │
       ┌───────────┼────────────┬──────────────┐
       ▼           ▼            ▼              ▼
  ┌─────────┐ ┌────────┐  ┌──────────┐  ┌────────────┐
  │parsers/ │ │memory/ │  │source_   │  │ 模型路由   │
  │BAG/BLF  │ │L1~L6   │  │docs/缓存 │  │ Local/Remote│
  └────┬────┘ └────────┘  └──────────┘  └────────────┘
       ▼
  ┌─────────────┐
  │ FrameStore  │  SQLite 内存数据库
  │ 5 张表+索引 │
  └─────────────┘
```

### 核心分层

| 层 | 目录 | 职责 |
|---|------|------|
| **入口层** | `cli.py` | 统一 CLI，解析参数 → 路由到三种模式 |
| **AI 编排层** | `ai/` | 诊断管线、专家面板、TPE、变量探测、可视化 |
| **数据层** | `parsers/` | BAG/BLF 解析、DBC 解码、SQLite 存储、时间对齐 |
| **记忆层** | `memory/` | 6 层记忆系统 + AutoDream 整合 |
| **知识缓存** | `source_docs/` | AI 提取的条件树、信号映射、参数表、模式库 |

---

## 运行模式

| 模式 | 入口 | 用途 | 核心模块 |
|------|------|------|----------|
| **Diagnosis 诊断** | `cli.py <case> -p "问题" -e "预期"` | 完整根因分析 | `ai/orchestrator.py` |
| **Query 查询** | `cli.py <case> -q "自然语言问题"` | 数据快查（轻量级） | `ai/data_query_engine.py` |
| **Dream 整合** | `cli.py --dream` | 强制记忆整合 + 代码学习 | `memory/auto_dream.py` |
| **Learn Constants** | `cli.py --learn-constants` | 重新学习数值常量表 | `ai/code_learner.py` |

---

## 诊断管线（15+ 步）

| Step | 名称 | 模块 | AI 调用 |
|------|------|------|---------|
| 1 | `init` + source_docs 保障 | `code_learner.ensure_overview_docs` | — |
| 2 | `understand` 问题理解 | `orchestrator._understand_problem` | complex × 1 |
| 3 | `classify` 任务分类 | `problem_classifier.classify` | simple × 1 |
| 4 | `parse` 数据解析 | `parsers/case_loader.load_case_data` | — |
| 5 | `detect_window` 窗口检测 | `test_window_detector.detect` | — |
| 6 | `analyze` 帧级分析 | `frame_analyzer.extract_evidence` | — |
| 7 | `conditions` 条件提取 | `condition_extractor.extract` | complex × 1 |
| 8 | `tpe` 时序模式引擎 | `tpe.TemporalPatternEngine.run` | — |
| 9 | `probe` 变量探测 | `variable_query_planner` + `data_probe` | complex × 1 |
| 10 | `suppression` 抑制检查 | `orchestrator._check_suppression_signals` | — |
| 11 | `output_signals` 输出信号 | `orchestrator._analyze_output_signals` | — |
| 12 | `params` 参数敏感性 | `parameter_analyzer`（仅 tune/verify 任务） | — |
| 13 | `diagnose` 专家面板 | `expert_panel.run_panel`（5 专家 × 3 轮） | complex × 多次 |
| 14 | `report` + `visualize` | `visualizer.build_report` → HTML | — |
| 15 | `done` 记忆更新 | `memory_system` L1~L5 写入 | — |

### 时序模式引擎（TPE）

`ai/tpe.py` 实现的 TPE 完成「**代码侧模式 ↔ 数据侧时序**」的因果对齐：

1. **代码模式提取**（`pattern_extractor.py`）：从 C 源码识别 `HoldRelease`、`Accumulate` 等行为模式
2. **时序特征分析**（`temporal_analyzer.py`）：把信号时间线归类为 `stable` / `oscillating` / `brief_pulses` / `edge_dominated`
3. **因果对齐**（`causal_aligner.py`）：用区间交集判断模式是否被触发，verdict ∈ `triggered` / `not_triggered` / `insufficient_data`

### 5 位专家面板

| Expert ID | 角色 | 关注点 |
|-----------|------|--------|
| `signal_chain` | 信号链路专家 | CAN → RteComMapping → 内部变量 → 条件 |
| `algorithm` | 算法逻辑专家 | `adasFunc.c` 触发/退出条件与阈值 |
| `system_state` | 系统状态专家 | 双状态机交互（adasFunc / ASWIN_SystemState） |
| `perception` | 感知与目标专家 | 目标分类、跟踪稳定性、ROI 过滤 |
| `architecture` | 架构专家 | 左右雷达通信、ASWOUT 输出合并 |

按 `fail_type` 智能选专家：FP / FN / DELAY / STATE 各 3 人，OTHER 全 5 人。

---

## 六层记忆系统

| 层 | 路径 | 内容 | 写入方 |
|----|------|------|--------|
| **L1** | `memory/project.md` | 项目级总览、双状态机架构、用户偏好 | `AutoDream` |
| **L2** | `memory/functions/{FUNC}.json` | 功能级 known_issues、状态机定义 | `AutoDream` |
| **L3** | `memory/patterns.json` | 跨功能模式库（症状 → 根因） | `AutoDream` |
| **L4** | `memory/sessions/{id}.json` | 单次诊断会话日志 | `Orchestrator` |
| **L5** | `cases/{CASE}/memory.json` | 案例级累积经验 | `Orchestrator` |
| **L6** | `memory/code_knowledge/{FUNC}.json` | 源码级结构化知识（4 focus × 8 functions） | `CodeLearner` |

**L6 学习焦点**：
- `alarm_logic`：触发/取消/退出/迟滞/延时/抑制
- `calculation_chain`：变量计算/数据链/阈值
- `output_chain`：内部变量 → ASWOUT → RteComMapping → CAN
- `state_machine`：状态编号/转换/双状态机交互

**Auto-Dream 5 阶段**（每 4 小时 + 累计 ≥ 2 个新会话才触发）：

```
Phase 0  Study      → CodeLearner.learn() 增量学习源码
Phase 1  Orient     → 拼接全部记忆上下文
Phase 2  Gather     → 收集最近 10 条 session
Phase 3  Consolidate → AI 整合 → 输出 JSON {project_memory_update, function_updates, ...}
Phase 4  Apply      → 写回 L1/L2/L3
```

---

## 快速开始

### 前置条件

- **Python** ≥ 3.10
- **Git**（用于克隆仓库）
- **本地 Ollama**（可选，用于简单任务，加速并降低成本）
- **远程模型服务**（必需，用于复杂任务，例如 `Qwen3.5-27B-FP16`）

### 1. 克隆仓库

```bash
git clone https://github.com/Bobs1121/RadarDiagnostic.git
cd RadarDiagnostic
```

### 2. 安装依赖

```bash
# 推荐使用虚拟环境
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux / macOS
source .venv/bin/activate

pip install -r requirements.txt
```

### 3. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env`：

```bash
# 本地 Ollama (可选，简单任务加速)
LOCAL_BASE_URL=http://localhost:11434/v1
LOCAL_API_KEY=ollama

# 远程模型服务器 (必需)
REMOTE_BASE_URL=http://your-server:port/model/v1
REMOTE_API_KEY=your-api-key-here
```

### 4. 配置源码路径

编辑 `config.yaml`，把 `paths.source_code` 指向你本地的 `cr60_light` 源码目录：

```yaml
paths:
  source_code: "D:\\cr60_light"   # ← 改成你的路径
  cases_dir: "./cases"
```

> 不需要源码也能运行 `query` 模式做轻量数据查询；但 `diagnose` 模式依赖源码做条件提取与代码学习。

### 5. 准备测试数据

把录制好的 BAG/BLF 文件放到 `cases/<CASE_NAME>/` 目录下，例如：

```
cases/
└── FCTB001/
    ├── BL02RC01_015.bag       (~ 几十 ~ 几百 MB)
    └── 2026-04-13_xxx.blf     (~ 几十 MB)
```

### 6. 验证安装

```bash
python cli.py --help
```

如果看到帮助文本即说明环境就绪。

---

## 使用示例

### A. 完整诊断（最常用）

```bash
python cli.py cases/FCTB001 \
    -p "FCTB 60kph 场景没有触发，目标已进入 ROI" \
    -e "应该在 TTC<1.5s 时正常触发制动请求"
```

执行流程：

1. （可选）自动 Auto-Dream 巩固记忆
2. 解析 BAG/BLF → SQLite
3. 识别问题 → 分类为 `diagnose`，目标功能 `FCTB`，失败类型 `FN`
4. 检测测试窗口（约 5~12 个）
5. 提取证据 + AI 抽取条件树 + 跑 TPE
6. 5 专家 × 3 轮研讨
7. 生成 `cases/FCTB001/report.md` + `report.html` + `expert_opinions.md`

### B. 数据快查

```bash
python cli.py cases/FCTB001 -q "FCTB 触发时 AEBIB 是否激活？"
```

输出 Markdown 格式的简短回答，不跑完整诊断管线。适合快速验证假设。

### C. 强制记忆整合

```bash
python cli.py --dream
```

立即触发 Auto-Dream（绕过门控），重新学习源码 + 整合最近会话 + 更新 L1/L2/L3。

### D. 重新学习数值常量

```bash
python cli.py --learn-constants
```

仅重新解析 `paraDefine.h` / `dotCalibDefine.h` / `globalVarDefine.h` / `adasFunc.c` 中的数值常量（约 1 次 AI 调用，~15 秒）。源码未变更时自动跳过。

### E. 交互模式

不指定 `-p` 或 `-q` 时进入交互菜单：

```bash
python cli.py cases/FCTB001
# Select mode:
#   1 Data query
#   2 Diagnosis
# Choice (1/2): _
```

---

## 配置说明

`config.yaml` 关键字段：

```yaml
ai:
  local:                                # 本地 Ollama
    base_url: "${LOCAL_BASE_URL:-http://localhost:11434/v1}"
    model: "qwen3:14b"
  remote:                               # 远端服务
    base_url: "${REMOTE_BASE_URL}"
    model: "Qwen3.5-27B-FP16"
  thinking: "full"                      # off | synth | full

  variable_probe:                       # 动态变量探测
    enabled: true
    max_queries: 6
    max_chars: 6000
    use_thinking: false

paths:
  source_code: "D:\\cr60_light"
  dbc_files:
    - "CR_DBC_V3.2_20260331.dbc"
    - "GAC_CR_FR&FL_Private_CAN_V1.3.dbc"
    - "GWM_RearCorner_Pri_V3.0 (1).dbc"
  cases_dir: "./cases"
  key_source_files: [...]               # 关键源码文件清单

functions:
  rear:  [BSD, LCA, DOW, RCW, RCTA, RCTB]
  front: [FCTA, FCTB]

auto_dream:
  code_learning:
    enabled: true
    warmup_pairs: 8                     # 首次冷启动学习对数
    pairs_per_dream: 2                  # 常规每轮学习对数
    rotation_focuses:
      - alarm_logic
      - calculation_chain
      - output_chain
      - state_machine
    priority_functions: [FCTB, FCTA, RCTB, RCTA, BSD, LCA, DOW, RCW]
    max_snippet_chars: 40000
    use_thinking: true
```

### Thinking 模式

| 取值 | 行为 | 适用场景 |
|------|------|----------|
| `off` | 全部关闭 | 日常诊断（最快） |
| `synth` | 仅 R3 综合开启 | 平衡（质量 ↑，耗时略增） |
| `full` | 所有 complex 调用开启 | 深度分析（最慢，token 3-5x） |

### 模型路由规则

| complexity | 路由 | 默认模型 |
|-----------|------|----------|
| `"simple"` | local Ollama | `qwen3:14b` |
| `"complex"` | remote 服务 | `Qwen3.5-27B-FP16` |
| `"auto"` | tools 非空 / 总长 > 3000 / 关键词命中 → complex，否则 → simple | — |

---

## 项目结构

```
radarAnalyze/
├── cli.py                      # 统一 CLI 入口
├── config.yaml                 # 模型/路径/功能/学习配置
├── requirements.txt
├── .env.example                # 环境变量模板
├── README.md                   # 本文件
├── AGENTS.md                   # 架构总览（开发者必读）
├── IMPLEMENTATION.md           # 完整实现归档（3000+ 行）
│
├── ai/                         # AI 分析模块（18 个文件）
│   ├── AGENTS.md
│   ├── orchestrator.py         # 诊断编排器（15+ 步管线）
│   ├── expert_panel.py         # 5 专家 × 3 轮研讨
│   ├── frame_analyzer.py       # 帧级证据提取
│   ├── test_window_detector.py # 纯规则窗口检测
│   ├── condition_extractor.py  # AI 条件树提取
│   ├── tpe.py                  # 时序模式引擎门面
│   ├── pattern_extractor.py    # C 源码模式抽取
│   ├── temporal_analyzer.py    # 时间线 → 模式标签
│   ├── causal_aligner.py       # 代码模式 ↔ 数据时序对齐
│   ├── data_probe.py           # SQLite 探针
│   ├── variable_query_planner.py # AI 规划查询
│   ├── data_query_engine.py    # 自然语言查数
│   ├── problem_classifier.py   # 任务分类
│   ├── signal_mapper.py        # CAN ↔ 内部变量映射
│   ├── code_learner.py         # 源码增量学习
│   ├── parameter_analyzer.py   # 阈值扫描 + what-if
│   ├── visualizer.py           # Plotly HTML 报告
│   ├── model_router.py         # local/remote 模型路由
│   ├── context_budget.py       # 字符级 prompt 预算
│   └── utils.py                # 共享工具
│
├── parsers/                    # 数据解析层
│   ├── AGENTS.md
│   ├── bag_parser.py           # ROS Bag v1 + 手工反序列化
│   ├── blf_parser.py           # BLF + DBC 解码
│   ├── dbc_loader.py           # 多 DBC 路由
│   ├── frame_store.py          # SQLite 5 张表
│   ├── time_sync.py            # BAG ↔ BLF 时间对齐
│   ├── case_loader.py          # 一键加载入口
│   └── msg_defs/               # ROS 消息定义
│
├── memory/                     # 记忆系统
│   ├── AGENTS.md
│   ├── memory_system.py        # 6 层记忆 API
│   ├── auto_dream.py           # 5 阶段整合引擎
│   ├── project.md              # L1
│   ├── patterns.json           # L3
│   ├── functions/              # L2 (8 个 JSON)
│   ├── sessions/               # L4 (会话日志)
│   ├── code_knowledge/         # L6 (8 个 JSON + learning_state.json)
│   └── dream_log.json
│
├── source_docs/                # 知识缓存
│   ├── AGENTS.md
│   ├── {FUNC}.md (×8)          # AI 生成的功能概览
│   ├── {FUNC}_conditions.json  # AI 提取的条件树
│   ├── signal_mapping.json     # CAN ↔ 内部变量
│   ├── output_mapping.json     # 输出表达式
│   ├── variable_chains.json    # 变量链路追踪
│   ├── code_patterns.json      # TPE 模式库
│   ├── parameters.json         # 数值参数表
│   ├── radar_knowledge.json    # 手工维护的雷达知识
│   ├── signal_chain.md
│   └── SYSTEM_GUIDE.md
│
├── cases/                      # 案例数据
│   └── {CASE}/
│       ├── *.bag               # 录制的雷达 BAG（gitignore）
│       ├── *.blf               # 录制的 CAN BLF（gitignore）
│       ├── report.md           # 诊断报告 Markdown
│       ├── report.html         # 可视化报告 (Plotly)
│       ├── expert_opinions.md  # 专家详细意见
│       └── memory.json         # L5 案例记忆
│
├── scripts/                    # 冒烟测试
│   └── smoke_test_learner.py
│
├── tools/                      # 辅助工具
│   ├── render_report_from_md.py
│   └── run_tpe_smoke.py
│
└── tests/
    └── test_temporal_pattern_engine.py
```

---

## 依赖

```text
rosbags >= 0.9.0       # ROS Bag v1 解析
python-can >= 4.0.0    # BLF 读取
cantools >= 39.0.0     # DBC 加载与解码
openai >= 1.0.0        # 模型客户端（兼容 Ollama / 远程服务）
pandas >= 2.0.0        # 数据处理
pyyaml >= 6.0          # 配置解析
python-dotenv >= 1.0.0 # 环境变量
rich >= 13.0.0         # CLI 美化
plotly >= 5.20.0       # 报告可视化
markdown >= 3.5        # MD → HTML 渲染
asteval >= 1.0.0       # DataProbe 安全表达式求值
```

---

## 输出报告

每次诊断在 `cases/<CASE>/` 目录下生成：

### `report.md` — Markdown 报告

包含以下章节（**强制结构**）：

1. **元信息表**：任务类型、涉及功能、问题描述、测试窗口、数据元数据
2. **数据溯源规则**
3. **根因**：核心结论（一段精炼描述）
4. **时序耦合（TPE 触发清单）**：模式名 / 源文件:行 / 首触发 t / 持续 / 触发信号 / 副作用
5. **条件检查汇总**：阈值 vs 实际值 vs 满足状态 vs 数据来源 vs 相关 TPE 模式
6. **关键证据链（结构化）**：信号 / 时间 / 值 / 来源 / TPE 模式
7. **数据链路**：从 CAN 信号到最终输出的完整路径
8. **测试窗口分析**
9. **场景差异分析**
10. **修复建议**
11. **置信度**（0~100）

### `report.html` — 交互式可视化

内联 plotly.js 单文件，包含：
- ego-speed 时间线
- output-signals 时间线
- state-timeline 状态机跳变
- tpe-triggers 模式触发标注
- param-sensitivity（仅 tune/verify 任务）
- whatif 假设分析

### `expert_opinions.md` — 专家详细意见

5 位专家在 R1/R2/R3 三轮中的完整发言，含主持人交叉质疑与综合收敛。

### `memory.json` — L5 案例记忆

```json
{
  "case_id": "FCTB001",
  "function": "FCTB",
  "diagnoses": [
    {
      "problem": "...",
      "verdict": "...",
      "key_findings": [...],
      "_at": "2026-04-25T..."
    }
  ],
  "_updated": "..."
}
```

---

## 开发者指南

### 关键约定（来自 `.cursor/rules/radarAnalyze-overview.mdc`）

1. **函数名大写表示 ADAS 功能**（如 `FCTB`、`BSD`），与 `ALL_FUNCTIONS` 列表对齐
2. **AI 调用统一经 `ModelRouter`**：
   - `simple()` → 本地模型
   - `complex()` → 远程模型
3. **缓存失效策略**：
   - `signal_mapping` 用 SHA256 前 16 位
   - `conditions` 用 mtime
   - `overview.md` 用片段 hash
4. **Prompt 语言**：以中文为主，JSON 输出统一通过 `parse_json_from_llm` 解析
5. **不直接拼接 Prompt**：必须经过 `ContextBudget`，避免超长

### 文档体系

- 根 `AGENTS.md`：架构总览 + 跨模块依赖速查表
- 各子目录 `AGENTS.md`：该目录内部的实现说明
- `IMPLEMENTATION.md`：完整归档（3000+ 行，仅供全文搜索）

> **AI 编辑代码时**会自动参考 `AGENTS.md` 进行需求 ↔ 实现的 review。

### 跨模块依赖速查（精简版）

| 生产方 | 消费方 | 数据 |
|--------|--------|------|
| `parsers/case_loader` | `orchestrator._parse_case_data` | `CaseLoadResult` |
| `signal_mapper` | `orchestrator._run_tpe` | signal_mapping / variable_chains |
| `condition_extractor` | `orchestrator` (conditions step) | `{FUNC}_conditions.json` |
| `frame_analyzer` | `orchestrator` (analyze step) | evidence dict |
| `test_window_detector` | `orchestrator`, `frame_analyzer`, `data_probe` | `list[TestWindow]` |
| `tpe.TemporalPatternEngine` | `orchestrator._run_tpe` | `TPEResult` |
| `expert_panel` | `orchestrator` (diagnose step) | `panel_result` dict |
| `memory_system` | `orchestrator`, `auto_dream`, `data_query_engine` | L1~L6 读写 |
| `model_router` | 几乎所有 AI 模块 | chat/simple/complex 统一接口 |

完整版见 [`AGENTS.md`](./AGENTS.md)。

### 添加新 ADAS 功能

1. 在 `config.yaml` 的 `functions.rear` 或 `functions.front` 列表中加入功能名
2. 在 `ai/utils.py` 的 `ALL_FUNCTIONS` / `FUNC_FIELD_MAP` 中注册
3. 在 `parsers/bag_parser.py` 的 `WARNING_SIGNAL_MAP` 中加入对应字节索引
4. 在 `parsers/frame_store.py` 的 `radar_objects.{func}_flag` 中加列
5. 触发 Auto-Dream，让 `CodeLearner` 学习对应的源码
6. 手动维护一份 `source_docs/{FUNC}.md` 作为兜底

### 测试

```bash
# 时序模式引擎单元测试
python -m pytest tests/test_temporal_pattern_engine.py

# 代码学习冒烟
python scripts/smoke_test_learner.py

# TPE 端到端冒烟
python tools/run_tpe_smoke.py
```

### 离线渲染报告

```bash
python tools/render_report_from_md.py cases/FCTB001/report.md
# → cases/FCTB001/report.html
```

---

## 常见问题 (FAQ)

<details>
<summary><b>Q1：为什么 BAG/BLF 数据文件不在仓库里？</b></summary>

录制数据通常几十 ~ 几百 MB，远超 GitHub 单文件限制。已在 `.gitignore` 排除：

```text
cases/**/*.bag
cases/**/*.blf
```

请联系项目管理员获取完整测试数据集。

</details>

<details>
<summary><b>Q2：远程模型服务挂了怎么办？</b></summary>

`ModelRouter` 在 local 失败时会**自动回退 remote**（反之则不会，因为复杂任务本地模型答不出来）。

如果 remote 服务长时间不可用：
1. 临时把 `config.yaml` 的 `ai.thinking` 改为 `"off"` 减少调用
2. 或单独跑 `query` 模式（更轻量）
3. 检查 `.env` 中 `REMOTE_BASE_URL` 是否正确

</details>

<details>
<summary><b>Q3：第一次运行很慢，正常吗？</b></summary>

正常。首次会触发：
- **Auto-Dream Phase 0**：学习 8 个 (func, focus) 对（warmup_pairs=8），约 5~10 分钟
- **`source_docs` 生成**：8 个 FUNC.md + 8 个 conditions.json + signal_mapping，约 3~5 分钟
- **常量学习**：约 15 秒

之后命中缓存，单次诊断通常 1~3 分钟。

</details>

<details>
<summary><b>Q4：怎么调整专家面板的 thinking 深度？</b></summary>

修改 `config.yaml`：

```yaml
ai:
  thinking: "synth"   # 推荐折中：仅 R3 综合开 thinking
```

| 取值 | 单次诊断耗时（参考） | 质量 |
|------|---------------------|------|
| `off` | 1~2 min | ★★★ |
| `synth` | 2~4 min | ★★★★ |
| `full` | 6~12 min | ★★★★★ |

</details>

<details>
<summary><b>Q5：如何强制重新学习某个功能的源码？</b></summary>

删除对应缓存：

```bash
# 删 L6 知识 + overview hash
rm memory/code_knowledge/FCTB.json
rm source_docs/.overview_hashes.json   # 或仅删 FCTB 那项

# 强制 Auto-Dream
python cli.py --dream
```

</details>

<details>
<summary><b>Q6：报告里 TPE 表格为空怎么办？</b></summary>

可能原因：
1. 该功能源码未学习到 `HoldRelease`/`Accumulate` 模式 → 跑 `--dream` 重新学
2. `signal_mapping.json` 找不到对应内部变量 → 检查 `RteComMapping.c` 路径与命名
3. 录制数据不含目标信号 → 检查 BAG topics 与 BLF DBC 解码情况

详见 `cases/<CASE>/expert_opinions.md` 中信号链路专家的诊断。

</details>

<details>
<summary><b>Q7：能不能在 Linux/macOS 上跑？</b></summary>

可以。CLI 与所有解析模块都是跨平台的。注意：
- `config.yaml` 中 Windows 路径分隔符 `\\` 需改成 `/`
- `paths.source_code` 改成你本地的实际路径
- 部分 BAG 文件如果是 Windows 端录制的，路径与字符编码需保持一致

</details>

---

## 贡献与维护

### 文档维护规则

发生以下变更时，请更新对应目录的 `AGENTS.md`：

1. 新增 / 删除 / 重命名 `.py` 模块或公开类、函数
2. 修改公开 API 签名（参数、类型、默认值）
3. 修改 AI prompt 内容（system / user prompt、JSON schema）
4. 修改缓存 / 失效策略（hash、mtime、路径）
5. 修改阈值 / 魔数（如 `total_chars=60000`、`_PADDING_SEC=2.0`）
6. 修改数据结构 schema（FrameStore 表、JSON 文件、evidence dict）
7. 修改管线步骤顺序或新增步骤
8. 修改专家面板配置或记忆层级 API

### Review Checklist

- [ ] 公开接口签名与代码一致
- [ ] 数据结构字段与代码一致（含 JSON schema）
- [ ] AI prompt 内容与代码字符串常量一致
- [ ] 缓存失效条件与代码逻辑一致
- [ ] 阈值 / 魔数与代码值一致
- [ ] 处理流程步骤顺序与代码执行顺序一致
- [ ] 依赖关系正确

### Git 提交约定

- **不**提交 `.env`、`*.bag`、`*.blf`（已在 `.gitignore` 排除）
- 新功能 / 修复 → 提交消息以动词开头：`Add ...`、`Update ...`、`Fix ...`
- 文档 / 配置 → `Docs: ...` / `Config: ...`

---

## 路线图

- [x] BAG/BLF 双模解析 + SQLite 统一存储
- [x] 5 专家面板 × 3 轮研讨
- [x] 时序模式引擎（TPE）
- [x] 6 层记忆系统 + Auto-Dream
- [x] 动态变量探测（Variable Probe）
- [x] 数值常量学习（Constants Learning）
- [x] 字符级 ContextBudget
- [ ] 更多 TPE 模式（OR/嵌套支持）
- [ ] 多案例对比分析
- [ ] CI 自动跑回归案例
- [ ] Web UI 仪表盘

---

## 相关文档

- [`AGENTS.md`](./AGENTS.md) — 架构总览 + 跨模块依赖速查
- [`IMPLEMENTATION.md`](./IMPLEMENTATION.md) — 完整实现归档（3000+ 行）
- [`ai/AGENTS.md`](./ai/AGENTS.md) — AI 模块实现说明
- [`parsers/AGENTS.md`](./parsers/AGENTS.md) — 数据解析层说明
- [`memory/AGENTS.md`](./memory/AGENTS.md) — 记忆系统说明
- [`source_docs/AGENTS.md`](./source_docs/AGENTS.md) — 缓存文件 schema

---

## License

内部工具，未公开授权。仅供项目内部使用。

---

<p align="center">
  <sub>Built with ❤ for Corner Radar diagnostics — automating what used to take hours into minutes.</sub>
</p>
