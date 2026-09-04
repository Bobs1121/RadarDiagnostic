# radarAnalyze 项目架构与 CodeGraph 改造计划

> 分支: `refactor/codegraph`
> 状态: Architecture Deep-Dive & Refactoring Plan
> 更新时间: 2026-05-22

---

## 1. 项目全貌

### 1.1 一句话定位

radarAnalyze 是一个 **ADAS 角雷达诊断工具**，对录制的 ROS Bag + CAN BLF 数据进行自动化根因分析，覆盖 8 个 ADAS 功能（BSD/LCA/DOW/RCW/RCTA/RCTB/FCTA/FCTB）。

### 1.2 技术栈

- **语言**: Python 3.11
- **硬件**: TI AWR2E44P 角雷达 (CR60Light)
- **数据源**: ROS1 Bag (雷达点迹/对象/诊断) + Vector CAN BLF + DBC (信号定义)
- **AI 模型**: OpenAI 兼容接口 (本地 Ollama + 远端 Qwen3.5-27B)
- **存储**: SQLite (运行时内存 DB + 持久化记忆 JSON)
- **部署环境**: Windows 11 (Python 必须用 `py -3.11`，`python` 是 Windows Store 占位符)

### 1.3 项目目录结构

```
radarAnalyze/
  cli.py                    # 统一 CLI 入口 (diagnosis/query/dream 三种模式)
  config.yaml               # 模型/路径/功能/学习 配置
  requirements.txt          # 依赖列表
  *.dbc                     # 3 个 DBC 文件 (CAN 信号定义)
  IMPLEMENTATION.md         # 完整实现文档 (~210KB，归档/全文搜索用)
  AGENTS.md                 # 项目级上下文 (管线步骤、目录结构、跨模块依赖)
  |
  ai/                       # AI 分析模块 (20+ 个 .py 文件)
    AGENTS.md               # ai/ 模块实现说明
    orchestrator.py         # 诊断管线总编排 (69KB，15+ 步骤)
    expert_panel.py         # 多专家 3 轮研讨面板
    code_learner.py         # 源码增量学习引擎 → L6 JSON (47KB)
    signal_mapper.py        # CAN ↔ 内部变量映射 (纯正则，32KB)
    pattern_extractor.py    # C 源码行为模式提取 (纯正则)
    condition_extractor.py  # AI 提取条件树 + 确定性后处理
    frame_analyzer.py       # 帧级证据提取 (26KB)
    test_window_detector.py # 纯规则窗口检测
    temporal_analyzer.py    # 信号时间线 → 边/段/统计
    causal_aligner.py       # 代码模式 ↔ 数据时序对齐
    tpe.py                  # 时序模式引擎门面
    variable_query_planner.py # AI 规划 DataProbe 查询
    data_probe.py           # FrameStore SQLite 探针 (asteval + numpy)
    problem_classifier.py   # 任务分类 (diagnose/tune/verify/query)
    parameter_analyzer.py   # 阈值扫描 + 敏感性分析
    model_router.py         # local/remote 模型选路
    context_budget.py       # 字符级 prompt 预算管理
    visualizer.py           # Plotly HTML 报告生成 (52KB)
    data_query_engine.py    # 自然语言查数 (query 模式)
    utils.py                # 共享工具 (parse_json_from_llm, FUNC_FIELD_MAP, ALL_FUNCTIONS)
  |
  parsers/                  # 数据解析层
    AGENTS.md               # parsers/ 模块实现说明
    __init__.py             # 聚合导出
    bag_parser.py           # ROS Bag v1 + 手工反序列化 (24KB)
    blf_parser.py           # BLF 读取 + DBC 解码 (5KB)
    dbc_loader.py           # cantools 加载多 DBC
    frame_store.py          # SQLite 内存数据库 (6 张表)
    case_loader.py          # 一键加载案例目录 → FrameStore + 元数据
    time_sync.py            # BAG (ns) ↔ BLF (epoch sec) 时间对齐
  |
  memory/                   # 记忆系统
    AGENTS.md               # memory/ 模块实现说明
    memory_system.py        # 6 层记忆 (L1-L6) 统一读写
    auto_dream.py           # 记忆整合引擎 (Phase 0-4)
    code_knowledge/         # L6: 代码知识 (8 个功能 JSON + constants.json + learning_state.json)
    functions/              # L2: 功能级记忆
    sessions/               # L4: 会话记录 (~40 条)
    patterns.json           # L3: 诊断模式库
    project.md              # L1: 项目级记忆
    dream_log.json          # dream 执行日志
  |
  source_docs/              # 缓存的知识文档
    AGENTS.md               # 文件 Schema 与缓存规则
    {FUNC}.md (×8)          # 功能概览 (AI 生成)
    {FUNC}_conditions.json (×8) # 激活条件 (AI 提取)
    signal_mapping.json     # CAN ↔ 内部变量映射 (正则，40KB)
    output_mapping.json     # 输出信号映射 (正则，57KB)
    variable_chains.json    # 变量链路追踪 (正则)
    code_patterns.json      # 代码行为模式 (正则，56KB)
    parameters.json         # 参数灵敏度 (正则，83KB)
    variables.json          # 变量清单 (AI 生成)
    radar_knowledge.json    # 手工维护
    .overview_hashes.json   # 概览文档 hash
    signal_chain.md         # 信号链路摘要
  |
  cases/                    # 案例数据
    FCATB001/               # FCTB 未触发案例 (~250MB)
    FCTA001/                # FCTA 未触发案例
    FCTA002/                # FCTA 边界案例
    BSDLCA001/              # BSD/LCA 案例
    ... (11 个案例)
  |
  msg_defs/                 # ROS 消息定义
    canfd_sgu_pub.py        # CAN-FD XCP 读 ECU 内存 → 发布 egoCarInfo
    egoCarInfo.msg          # ROS msg 定义 (69 字段)
  |
  cr60_light_arbe/          # ROS 雷达驱动 (参考用)
  cr60_light_convert_radar_dataset/ # 数据集转换工具 (参考用)
  |
  scripts/                  # 冒烟测试
  tools/                    # 辅助工具 (render_report, run_tpe_smoke)
  tests/                    # 测试 (test_temporal_pattern_engine)
  docs/technical/           # 技术文档
  .cursor/rules/            # Cursor AI 规则
```

---

## 2. 诊断管线 (Diagnosis Pipeline)

### 2.1 管线步骤全览

```
cli.py --mode diagnosis
  └── Orchestrator.run_diagnosis()
        │
        ├── Step  1  [init + source_docs]  CodeLearner.ensure_overview_docs()
        │                                  signal_mapper.extract_signal_mapping()
        │                                  → 生成/刷新 source_docs/ 缓存
        │
        ├── Step  2  [understand]          LLM complex: 问题理解 → func_info dict
        │                                  {function, confidence, reasoning, fail_type,
        │                                   key_variables, related_functions}
        │
        ├── Step  3  [classify]            ProblemClassifier.classify()
        │                                  → ClassificationResult (可能覆盖 func_name)
        │
        ├── Step  4  [parse]               case_loader.load_case_data()
        │                                  → FrameStore (SQLite), bag_meta, blf_meta, TimeSync
        │
        ├── Step  5  [detect_window]       TestWindowDetector.detect()
        │                                  → list[TestWindow] (事件检测 ±2s padding)
        │
        ├── Step  6  [analyze]             FrameAnalyzer.extract_evidence()
        │                                  → evidence dict (KEY_FACTS, timeline, state_transitions,
        │                                    warning_states, radar_objects, warning_events, can_summary)
        │
        ├── Step  7  [conditions]          ConditionExtractor.extract() (LLM complex)
        │                                  → {FUNC}_conditions.json
        │
        ├── Step  8  [tpe]                 TemporalPatternEngine.run()
        │                                  → tpe_text, tpe_report
        │
        ├── Step  9  [probe]               VariableQueryPlanner.plan() (LLM chat)
        │                                  → list[QueryPlan]
        │                                  DataProbe.execute()
        │                                  → ProbeResult dict (注入 Expert Panel)
        │
        ├── Step 10  [suppression]         _check_suppression_signals()
        │                                  → suppression_text
        │
        ├── Step 11  [output_signals]      _analyze_output_signals()
        │                                  → output_signal_text
        │
        ├── Step 12  [params]              parameter_analyzer (仅 tune/verify 模式)
        │                                  → SensitivityReport, WhatIfEntry
        │
        ├── Step 13  [panel_prompt]        ContextBudget.truncate_to_budget()
        │                                  → 截断后 prompt (≤60KB)
        │
        ├── Step 14  [diagnose]            ExpertPanel.run_panel() (LLM complex × 多轮)
        │                                  → panel_result {expert_opinions, moderator_challenges,
        │                                    final_verdict, rounds}
        │
        ├── Step 15  [report]              _save_report() + _save_expert_appendix()
        │                                  → report.md, expert_opinions.md
        │
        ├── Step 16  [visualize]           Visualizer.build_report()
        │                                  → report.html (Plotly 交互式图表)
        │
        └── Step 17  [done]                _update_memories()
                                          → L1-L5 写入 + complete_session
```

### 2.2 AI 调用统计

| 模块 | 调用次数 | 复杂度 | 用途 |
|------|---------|--------|------|
| orchestrator | 1 | complex | 问题理解 → func_info |
| orchestrator | 2 | simple | 帧分析摘要, 诊断模式 JSON |
| problem_classifier | 1 | simple | 任务分类 |
| condition_extractor | 1 | complex | 条件树提取 |
| variable_query_planner | 1 | complex | 查询规划 |
| expert_panel | 多次 | complex | 3 轮专家研讨 |
| data_query_engine | 2 | complex | 自然语言查数 |
| code_learner | N | complex | 代码学习 (N = func × focus) |
| auto_dream | 1 | complex | 记忆整合 |

### 2.3 跨模块数据流

```
parsers/case_loader ──CaseLoadResult──> orchestrator._parse_case_data
  (store, bag_meta, blf_meta, sync)

signal_mapper ──signal_mapping dict──> orchestrator._run_tpe, _check_suppression_signals
variable_chains dict

condition_extractor ──conditions dict──> orchestrator (conditions step)
  → {FUNC}_conditions.json

frame_analyzer ──evidence dict──> orchestrator (analyze step)
  → frame_analysis str

test_window_detector ──list[TestWindow]──> orchestrator, frame_analyzer, data_probe

pattern_extractor ──list[CodePattern]──> tpe.TemporalPatternEngine

temporal_analyzer ──dict[TemporalFeature]──> tpe, causal_aligner

causal_aligner ──list[PatternEvidence]──> tpe.TemporalPatternEngine

tpe ──TPEResult──> orchestrator._run_tpe

problem_classifier ──ClassificationResult──> orchestrator (classify step)

variable_query_planner ──list[QueryPlan]──> orchestrator (probe step)

data_probe ──ProbeResult dict──> orchestrator (probe step)

expert_panel ──panel_result dict──> orchestrator (diagnose step)

context_budget ──truncated prompt str──> orchestrator (panel_prompt)

visualizer ──VisualizerResult──> orchestrator (visualize step)

memory_system ──L1-L6 读写──> orchestrator, auto_dream, data_query_engine

code_learner ──L6 JSON, overview MD──> auto_dream Phase 0, orchestrator._ensure_source_docs
```

---

## 3. 数据解析层 (parsers/)

### 3.1 数据源架构

```
原始数据                                               中间格式
┌──────────────┐                              ┌──────────────────┐
│ .bag 文件     │  BagParser (手工反序列化)      │  bag_frames      │
│ (ROS1)       │─────────────────────────────>│  radar_objects    │
│              │  消息类型:                     │  radar_debug      │
│  wfAutosar   │  - wfAutosarData  (36B obj)  │  warning_events  │
│  wfObjectMsg │  - wfObjectMsg    (185B obj) │                  │
│  egoCarInfo  │  - egoCarInfo     (69 fields)│                  │
│  UInt8Multi  │  - UInt8MultiArray (warning) │                  │
└──────────────┘                              └──────────────────┘
┌──────────────┐                              ┌──────────────────┐
│ .blf 文件     │  BlfParser (+ DBC 解码)      │  can_frames       │
│ (Vector)     │─────────────────────────────>│                  │
│              │  DbcLoader (cantools)        │                  │
└──────────────┘                              └──────────────────┘
┌──────────────┐
│ .dbc 文件 (×3)│  DbcLoader 加载              │  known_ids,       │
│              │─────────────────────────────>│  message/signal   │
└──────────────┘                              │  定义表            │
                                              └──────────────────┘
                                                       │
                                              ┌────────▼──────────┐
                                              │   FrameStore       │
                                              │   (SQLite 内存 DB) │
                                              └──────────────────┘
```

### 3.2 FrameStore SQLite 表结构

| 表 | 核心字段 | 用途 |
|----|---------|------|
| `bag_frames` | timestamp_ns, topic, msg_type, fields_json | ROS 原始帧 |
| `can_frames` | timestamp, can_id, message_name, signals_json | CAN 原始帧 |
| `radar_objects` | timestamp_ns, radar_id, obj_id, dist_x/y, vel_x/y, ttc, *flags | 雷达目标 |
| `radar_debug` | timestamp_ns, radar_id, ego 字段, *enable, bld 字段 | 诊断数据 |
| `warning_events` | func_name, direction, start_ns, end_ns, duration_ms, min_dist | 警告事件 |

**唯一索引**: bag_dedup, can_dedup, ro_dedup, rd_dedup
**普通索引**: bag_ts, bag_topic, can_ts, can_id, can_name, ro_ts, rd_ts, we_func, we_ts

### 3.3 关键解析细节

- **bag 解析**: 手工 struct 反序列化 (struct.unpack)，不是 rospy。格式字符串硬编码在 `_OBJ_STRUCT_FMT` / `_WFSOBJ_FMT`
- **wfa 距离单位**: 厘米 (÷100 转为米); **wfObjectMsg**: 已是 float 米
- **对象过滤**: `abs(dist) > 50cm` 或 `warning != 0` 或 `life_cycle > 3`
- **warning_events 构造**: 500ms 间隙切分，按 `(radar_id, obj_id, timestamp_ns)` 排序
- **时间对齐**: BAG (ns) ↔ BLF (epoch sec)，通过 `TimeSync.offset_sec`
- **DBC 路由**: 同 `frame_id` 先加载者优先

---

## 4. 记忆系统 (Memory L1-L6)

### 4.1 层级架构

```
L1 ─ project.md                 (项目级记忆，手工追加)
L2 ─ memory/functions/{FUNC}.json  (功能级记忆，AI 更新)
L3 ─ memory/patterns.json       (诊断模式库，MD5 去重)
L4 ─ memory/sessions/{session}.json  (诊断会话记录)
L5 ─ cases/{CASE}/memory.json   (案例级记忆)
L6 ─ memory/code_knowledge/     (代码知识 — 本次改造重点)
     ├── {FUNC}.json (×8)      (功能 × 焦点的结构化 JSON)
     ├── constants.json         (全局数值常量)
     └── learning_state.json    (学习游标 + hash 缓存)
```

### 4.2 上下文拼装 (build_context_for_diagnosis)

诊断时 MemorySystem 自动拼装上下文注入 Expert Panel:

```
L1 (截断 2000 chars)
+
L2 JSON (截断 3000 chars)
+
L6 render (按 focus 渲染 Markdown, 各 focus 截断)
+
L3 similar (最多 3 条匹配模式)
+
L5 (截断 1500 chars)
─────────────────────
= Expert Panel system prompt 的 "prior knowledge" 部分
```

### 4.3 缓存机制

- MemorySystem 有 `_ctx_cache`，键 = `(func_upper, problem[:240], case_dir_str)`
- 不自动创建 `patterns.json` 或 `project.md`
- **无锁设计**，多进程并发写有竞态风险 (AutoDream 层用 `.dream-lock` 协调)

---

## 5. 代码知识体系 (本次改造重点)

### 5.1 现有 code_knowledge 结构

#### 5.1.1 文件清单

| 文件 | 行数 | 大小 | 学习状态 |
|------|------|------|---------|
| FCTB.json | 778 | ~29KB | 4 focus 全学 |
| FCTA.json | 844 | ~32KB | 4 focus 全学 (state_machine 已学) |
| RCTA.json | 752 | ~28KB | alarm_logic + calc 已学 |
| RCTB.json | 580 | ~20KB | alarm_logic + calc 已学 |
| BSD.json | 696 | ~24KB | alarm_logic + calc + output 已学 |
| LCA.json | 509 | ~18KB | alarm_logic + calc 已学 |
| DOW.json | 480 | ~16KB | alarm_logic + calc 已学 |
| RCW.json | 477 | ~15KB | alarm_logic + calc 已学 |
| constants.json | 558 | ~14KB | 全局常量 (一次性) |
| learning_state.json | 65 | ~2KB | 游标=26, 已学 26/32 对 |

#### 5.1.2 每个功能 JSON 的固定结构

```json
{
  "_meta": {
    "function": "FCTB",
    "last_updated": "2026-04-20T15:00:19...",
    "learned_focuses": ["alarm_logic", "calculation_chain", "output_chain", "state_machine"],
    "source_hashes": {
      "alarm_logic": "5b8b9159e79e3dee",
      "calculation_chain": "a564f1bdfacce99d",
      "output_chain": "a0fcddb880fd37e7",
      "state_machine": "18a6ebe36eb76711"
    }
  },
  "alarm_logic": {
    "trigger_conditions": [
      {
        "id": "trig-1",
        "description": "系统自检通过，允许进入初始化状态",
        "c_expression": "if (g_DTCCode.selfInspFlg)",
        "variables": ["g_DTCCode.selfInspFlg"],
        "thresholds": {},
        "code_ref": {
          "file": "coem\\GWM_B26\\components\\AswPerception\\func\\adasFunc.c",
          "line": 2547,
          "function": "FctaFctbUpdateStatus"
        },
        "confidence": 0.95,
        "_learned_at": "2026-04-18T17:19:40..."
      }
    ],
    "cancel_conditions": [...],
    "external_suppression": [...]
  },
  "calculation_chain": {
    "key_variables": {...},
    "derivation_chain": [...],
    "computed_values": [...]
  },
  "output_chain": {
    "outputs": [...],
    "merge_strategy": "...",
    "rte_writes": [...]
  },
  "state_machine": {
    "states": {...},
    "transitions": [...]
  }
}
```

#### 5.1.3 构建过程 (CodeLearner)

```
1. 读取 learning_state.json 的 cursor 游标
2. 按 (focus × function) 轮转序列，取出下一个待学对
3. 根据 focus 查找 FOCUS_FILES[focus] 得到相关源码文件列表
4. 读取这些文件，计算聚合 hash → 与 learning_state.json 的 pair_hashes 比对
   → hash 未变则跳过 (增量机制)
5. 用 FUNC_KEYWORDS[func] 作为关键字，从源码中抽取相关代码片段
   → 基于正则匹配含关键字的行 + 12 行上下文 (extract_relevant_sections)
6. 将片段拼接为 prompt，调用 LLM 抽取结构化 JSON
7. 将 LLM 返回的 JSON 合并到 memory/code_knowledge/<FUNC>.json
   → 按 id 去重合并，新条目追加，已有条目内容变更时更新
8. 更新 cursor 和 pair_hashes
```

**设计特点:**
- **LLM 驱动** — 核心抽取逻辑交给 LLM，因为 C 代码的控制流分析是 NLP 任务
- **焦点分离** — 4 个 focus 各有不同的 prompt 模板和系统提示
- **关键字过滤** — 整个源码库太大，无法全部送入 LLM，用关键字做粗糙但有效的过滤
- **Hash 缓存** — 源码未改动就跳过，节省 token 和时间
- **增量合并** — 新条目追加、旧条目按 id 更新，保证知识只增不减

#### 5.1.4 constants.json 全局常量

```json
{
  "vehicle_config": {
    "EGOCARWIDTH": {"value": 1.976, "unit": "m", ...}
  },
  "function_thresholds": {
    "fFctbActiveUpSpd": {"value": 21.0, "unit": "km/h", "used_by": ["FCTB"], ...}
  },
  "roi_derived": {
    "LineBSDLCAL": {"formula": "-3.3 - EGOCARWIDTH/2", "computed_value": -4.288, ...}
  }
}
```

### 5.2 现有 source_docs/ 中的确定性分析产物

这些是**纯正则解析**产生的，不经过 LLM:

| 文件 | 生成模块 | 大小 | 核心内容 |
|------|---------|------|---------|
| `signal_mapping.json` | `signal_mapper.extract_signal_mapping` | 40KB | CAN ↔ 内部变量双向映射，从 RteComMapping.c 解析 |
| `output_mapping.json` | `signal_mapper.extract_output_signal_mapping` | 57KB | 输出信号 → C 表达式映射 |
| `variable_chains.json` | `signal_mapper.trace_variable_chains` | 2KB | struct_aliases, raw_copies, rte_write_prefixes |
| `code_patterns.json` | `pattern_extractor.extract_all` | 56KB | HoldRelease/Accumulate 等 6 种行为模式 |
| `parameters.json` | `parameter_analyzer.scan_parameters` | 83KB | 阈值参数清单 (name, value, file, line, func, category) |

### 5.3 FUNC_KEYWORDS 与 FOCUS_FILES

```python
# 关键字表 (ai/utils.py / ai/code_learner.py)
FUNC_KEYWORDS = {
    "BSD":  ["bsd", "Bsd", "BSD", "bLeftBsd", "bRightBsd", "bsdSystemState", "BSD_LCA_warning"],
    "LCA":  ["lca", "Lca", "LCA", "bLeftLca", "bRightLca", "lcaSystemState"],
    "DOW":  ["dow", "Dow", "DOW", "bLeftDow", "bRightDow", "dowSystemState", "DOW_warning"],
    "RCW":  ["rcw", "Rcw", "RCW", "bRcw", "rcwSystemState", "RSDS_RCW"],
    "RCTA": ["rcta", "Rcta", "RCTA", "bLeftRcta", "bRightRcta", "rctaSystemState", "RCTA_warning"],
    "RCTB": ["rctb", "Rctb", "RCTB", "rctbSystemState", "RctbBrake", "RSDS_Brkg", ...],
    "FCTA": ["fcta", "Fcta", "FCTA", "bLeftFcta", "bRightFcta", "fctaSystemState", "FCTA_Warn"],
    "FCTB": ["fctb", "Fctb", "FCTB", "fctbSystemState", "FctbBrake", "FctbKeepBrake", ...],
}

# 焦点文件 (ai/code_learner.py)
FOCUS_FILES = {
    "alarm_logic": [
        "coem\\GWM_B26\\components\\AswPerception\\func\\adasFunc.c",
        "coem\\GWM_B26\\components\\AswPerception\\func\\adasFunc.h",
        "adas\\symmetry\\perception\\include\\paraDefine.h",
    ],
    "calculation_chain": [
        "coem\\GWM_B26\\components\\AswPerception\\func\\adasFunc.c",
        "adas\\symmetry\\perception\\src\\objAttribCal.c",
        "adas\\symmetry\\perception\\src\\postProcess.c",
        "adas\\symmetry\\perception\\src\\track.c",
        "adas\\symmetry\\perception\\include\\paraDefine.h",
        "adas\\symmetry\\perception\\include\\structDefine.h",
    ],
    "output_chain": [
        "coem\\GWM_B26\\components\\AswPerception\\func\\adasFunc.c",
        "coem\\GWM_B26\\components\\AswIf\\ASW_OUT\\ASWOUT_OutCalc.c",
        "coem\\GWM_B26\\components\\AswIf\\ASW_IN\\RteComMapping.c",
    ],
    "state_machine": [
        "coem\\GWM_B26\\components\\AswPerception\\func\\adasFunc.c",
        "coem\\GWM_B26\\components\\AswIf\\ASW_IN\\ASWIN_SystemState.c",
        "coem\\GWM_B26\\components\\AswIf\\ASW_IN\\ASWIN_SystemState.h",
    ],
}

# config.yaml 中的 key_source_files (14 个文件)
key_source_files:
  # 算法层 - 报警判断
  - "coem\\GWM_B26\\components\\AswPerception\\func\\adasFunc.c"
  - "coem\\GWM_B26\\components\\AswPerception\\func\\adasFunc.h"
  # 平台状态机
  - "coem\\GWM_B26\\components\\AswIf\\ASW_IN\\ASWIN_SystemState.c"
  - "coem\\GWM_B26\\components\\AswIf\\ASW_IN\\ASWIN_SystemState.h"
  # 信号链路
  - "coem\\GWM_B26\\components\\AswIf\\ASW_IN\\RteComMapping.c"
  - "coem\\GWM_B26\\components\\AswIf\\ASW_IN\\RteComMapping.h"
  # 输出协调
  - "coem\\GWM_B26\\components\\AswIf\\ASW_OUT\\ASWOUT_OutCalc.c"
  # 调度入口
  - "coem\\GWM_B26\\components\\AswIfSchedule\\AswIfSchedule.c"
  # 感知层
  - "adas\\symmetry\\perception\\src\\objAttribCal.c"
  - "adas\\symmetry\\perception\\src\\track.c"
  - "adas\\symmetry\\perception\\src\\postProcess.c"
  # 定义文件
  - "adas\\symmetry\\perception\\include\\perception_public_def.h"
  - "adas\\symmetry\\perception\\include\\structDefine.h"
  - "adas\\symmetry\\perception\\include\\paraDefine.h"
  - "adas\\symmetry\\perception\\include\\globalVarDefine.h"

# source_domains (config.yaml) 按领域分组
source_domains:
  system_state: [ASWIN_SystemState.c, ASWIN_SystemState.h]
  algorithm:    [adasFunc.c, adasFunc.h, paraDefine.h]
  signal_chain: [RteComMapping.c]
  perception:   [objAttribCal.c, track.c, postProcess.c]
  output:       [ASWOUT_OutCalc.c]
```

### 5.4 现有代码知识体系的痛点

| 问题 | 具体表现 |
|------|----------|
| **函数调用关系丢失** | 只能记录单个 `caller` 字段，无法追踪调用链 |
| **变量依赖没有显式连接** | `fFctbActiveUpSpd` 在 alarm_logic、calculation_chain 中散落出现 |
| **状态机转换是静态文本** | `from: "Any"`, `to: 2` 字符串，无法做图遍历 |
| **跨模块关系不可见** | FCTB 和 FCTA 共享 `FctaFctbUpdateStatus`，无显式记录 |
| **反向查询不可能** | "谁写了 `CR_BrkgReq`?" — 无法回答 |
| **重复数据** | 8 个功能的 alarm_logic 结构完全一致，只是内容不同 |
| **数据粒度粗** | LLM 抽取的是"语义块"级别，不是代码级别的精确 AST 节点 |
| **关键字过滤不可靠** | `FUNC_KEYWORDS` 基于字符串匹配，漏匹配/误匹配 |
| **code_patterns.json 模式有限** | 仅 HoldRelease + Accumulate 2 种，Hysteresis/Debounce/EdgeTrigger 未实现 |

### 5.5 确定性分析 vs LLM 语义抽取 分工

```
┌─────────────────────────────────────────────┐
│           代码知识体系 (现状)                 │
├─────────────────────┬───────────────────────┤
│   确定性正则分析     │   LLM 语义抽取         │
│   (已有模块)         │   (CodeLearner)        │
├─────────────────────┼───────────────────────┤
│ signal_mapping      │ alarm_logic 语义       │
│ output_mapping      │ calculation_chain 语义  │
│ variable_chains     │ output_chain 语义      │
│ code_patterns       │ state_machine 语义      │
│ parameters          │ constants 数值推导      │
├─────────────────────┴───────────────────────┤
│   共同消费方: orchestrator / Expert Panel /   │
│   DataProbe / condition_extractor            │
└─────────────────────────────────────────────┘
```

---

## 6. 源码分析相关模块详细分析

### 6.1 signal_mapper.py — CAN 信号映射器

**定位**: 纯正则解析 `RteComMapping.c` 建立 CAN ↔ 内部变量双向映射

**核心流程**:
1. 读取 RteComMapping.c
2. 正则匹配 `Rte_*_Read_*` / `Rte_*_Write_*` 调用
3. 建立 `mappings[]` 数组 (含 can_signal, internal_var, transform, scaling, data_type)
4. 构建 `internal_to_can` / `can_to_internal` / `fullpath_to_can` 反向索引
5. SHA256 前 16 位缓存到 signal_mapping.json

**resolve_internal_to_can 优先级** (6 层降级):
1. `internal_to_can` 精确匹配
2. `fullpath_to_can` 精确匹配
3. 点路径最后一段
4. struct_aliases (variable_chains) 前缀展开
5. 大小写不敏感
6. 核心子串 (≥5 字符) 双向 in 匹配

**trace_variable_chains**: 追踪 `g_前缀` 全局变量 → `RTE_前缀` 参数的复制链路，识别 struct field alias

**output_signal_mapping**: 解析 `ASWOUT_OutCalc.c` 中的 CAN 输出表达式

### 6.2 pattern_extractor.py — 行为模式提取器

**定位**: 从 C 源码中正则挖掘 6 种时序行为模式

**6 种模式类型**:
| 类型 | 模式 | 是否已实现 |
|------|------|-----------|
| HoldRelease | `if (cond) { flag = false; time = 0 }` | ✓ |
| HoldEntry | `if (cond) { flag = true; time = 0 }` | 声明未实现 |
| Accumulate | `time += dt` + `time = 0` in else | ✓ (轻量启发) |
| Hysteresis | 不对称进入/退出阈值 | 声明未实现 |
| Debounce | `cnt++ / if (cnt >= N)` latch | 声明未实现 |
| EdgeTrigger | `prev == 0 && cur != 0` | 声明未实现 |

**输出**: `source_docs/code_patterns.json` (56KB)，缓存策略 = 源码目录 hash

### 6.3 condition_extractor.py — 条件提取器

**定位**: LLM 提取结构化条件树 + 确定性后处理

**流程**:
1. 检查缓存 (`{FUNC}_conditions.json`)，失效条件 = 任一域内源码 `mtime > cache_mtime`
2. 读取 `source_domains` 中相关文件的源码
3. 用 FUNC_KEYWORDS 过滤相关片段
4. 拼接 prompt，调用 `router.complex()` 提取 JSON 条件树
5. 确定性后处理: 解析输出，校验极性规则

**输出 schema**: `system_state`, `target_filter`, `detect_enable`, `ego_speed_ranges`, `target_speed_ranges`, `external_suppression`, `other_conditions`

### 6.4 code_learner.py — 代码学习引擎

**定位**: 项目中**唯一**负责"读源码、抽知识"的模块，LLM 驱动

**两个公共入口**:

```python
learn(pairs_budget=None)
  → 增量式、结构化 JSON 学习
  → 按 "功能 × 焦点" 二维网格轮转
  → 结果写入 memory/code_knowledge/<FUNC>.json

ensure_overview_docs(funcs=None)
  → 一次性、人类可读 Markdown 概览
  → 结果写入 source_docs/<FUNC>.md
```

**四个学习焦点**:
- `alarm_logic`: 报警触发/取消/退出条件、迟滞、延时、抑制
- `calculation_chain`: 关键变量计算流程 (TTC/TTM/距离/速度/ROI 派生)
- `output_chain`: 外发链路 (内部变量 → RteComMapping → CAN 信号 → 下游)
- `state_machine`: 状态流转、入口/出口动作、双状态机交互

**常量学习** (全局、一次性):
- 源文件: `paraDefine.h`, `dotCalibDefine.h`, `globalVarDefine.h`, `perception_public_def.h`, `adasFunc.c`
- 输出: `memory/code_knowledge/constants.json`
- 三类: `vehicle_config`, `function_thresholds`, `roi_derived`
- 要求 LLM 自己计算派生值 (如 `computed_value = -3.3 - 1.976/2 = -4.288`)

**学习轮转序列**:
```
priority_functions: [FCTB, FCTA, RCTB, RCTA, BSD, LCA, DOW, RCW]
rotation_focuses:   [alarm_logic, calculation_chain, output_chain, state_machine]
→ 8 × 4 = 32 个 (func, focus) 对
→ warmup 学 8 个，常规每次学 2 个
→ 当前 cursor=26，已学 26/32
```

### 6.5 FUNC_FIELD_MAP — 功能字段映射

**定义位置**: `ai/utils.py`

**用途**: 将功能名映射到 bag 数据中的字段名 (state, enable, warnings, error_status, obj_warning_flag, side_prefix, ego_topics)

**示例 (FCTB)**:
```python
{
    "state": "fctb_system_state",
    "enable": "fctb_enable",
    "enable_cap": "fctb_enable_capture",
    "warnings": [],
    "error_status": "get_rdafctb_error_status",
    "obj_warning_flag": "obj_fctb_warning_flag",
    "side_prefix": "front",
    "ego_topics": ["/wf/ego_car_info/front_left/parsed", "/wf/ego_car_info/front_right/parsed"],
}
```

---

## 7. CodeGraph 改造目标

### 7.1 改造范围

CodeGraph 改造聚焦于 **代码知识体系 (L6 + source_docs 确定性分析部分)** 的增强，具体:

**改造对象**:
1. `memory/code_knowledge/` — LLM 生成的结构化 JSON (8 功能 + constants)
2. `source_docs/` 中的确定性分析产物 (signal_mapping, code_patterns, parameters 等)
3. `ai/code_learner.py` — 代码学习引擎
4. `ai/signal_mapper.py` — 信号映射器
5. `ai/pattern_extractor.py` — 行为模式提取器

**不改的部分**:
- 数据解析层 (parsers/)
- 诊断管线编排 (orchestrator.py) — 接口不变
- 帧级分析 (frame_analyzer.py)
- 记忆系统 L1-L5
- Expert Panel / DataProbe / Visualizer
- CLI 入口 (仅新增 codegraph 相关命令)

### 7.2 核心痛点与 CodeGraph 解法

| 痛点 | CodeGraph 解法 |
|------|---------------|
| 函数调用关系丢失 | CALLS 边 + 行号精度 |
| 变量依赖不可追溯 | READS_VAR / WRITES_VAR 边 |
| 信号链路断裂 | READS_SIGNAL / WRITES_SIGNAL 边 (Rte_Read/Write + ReadSignal/WriteSignal) |
| 跨模块关系不可见 | BELONGS_TO + SHARES 自动推导 |
| 反向查询不可能 | edges (source/target) 双向索引 + SQL JOIN |
| 关键字过滤不可靠 | 静态分析精确提取函数定义/调用/变量访问 |
| 状态机不可遍历 | STATE 节点 + TRANSITION 边 (支持 BFS/DFS) |
| code_patterns 不完整 | 统一在 CodeGraph 中分析，支持 6 种模式全量实现 |
| signal_mapper 和 code_knowledge 割裂 | 统一图谱，signal_mapping 数据作为边属性而非独立 JSON |
| parameters 散落在 JSON | PARAM_FOR 边直接关联校准参数 → 功能模块 |

### 7.3 与现有系统的关系

```
┌──────────────────────────────────────────────────────┐
│              改造后的代码知识体系                       │
├──────────────┬───────────────┬───────────────────────┤
│   CodeGraph  │  code_knowl.  │   source_docs/        │
│   (静态分析)  │  (LLM 语义)   │   (确定性分析产物)     │
├──────────────┼───────────────┼───────────────────────┤
│ ✓ 函数调用图  │ ✓ 报警触发语义 │ ✓ signal_mapping     │
│ ✓ 变量读写依赖│ ✓ 业务含义解释 │ ✓ output_mapping     │
│ ✓ 信号链路    │ ✓ 阈值/参数值  │ ✓ variable_chains    │
│ ✓ 跨模块依赖  │ ✓ 状态机业务含义│ ✓ code_patterns     │
│ ✓ 反向查询    │ ✓ 迟滞/定时器语义│ ✓ parameters        │
│ ✓ 6 种行为模式│ ✓ 抑制/门控条件 │                       │
│ ✓ 状态机遍历  │               │                       │
│ ✓ 增量更新    │               │                       │
└──────────────┴───────────────┴───────────────────────┘
         ↘            ↘              ↘
         在 Expert Panel / DataProbe / orchestrator 中联合使用
         CodeGraph 提供结构 (关系)，code_knowledge 提供语义 (业务含义)
```

**关键设计决策**:
- CodeGraph 和 code_knowledge **互补共存**，不互相替代
- CodeGraph 回答 "谁调用了谁"、"谁读写了什么变量" (精确关系)
- code_knowledge 回答 "这个条件表示车速在范围内"、"迟滞 0.5s 后才退出" (业务语义)
- source_docs/ 中的确定性分析产物逐渐 **迁移到 CodeGraph 中统一管理**，对外接口保持不变

### 7.4 CodeGraph 技术方案

#### 7.4.1 存储

- **SQLite 单文件**: `memory/codegraph.db`
- **理由**: 嵌入式、零配置、支持 FTS5、支持复杂查询 (JOIN, 子查询, 递归 CTE)
- **版本管理**: `schema_version` 表

#### 7.4.2 节点类型 (Node Types)

| 类型 | 示例 | 特有属性 |
|------|------|---------|
| FILE | `adasFunc.c` | file_path, hash |
| FUNCTION | `FctaFctbUpdateStatus` | file_id, start/end_line, return_type, params, is_static |
| VARIABLE | `fFctbActiveUpSpd` | scope (global/static/local), data_type, defined_in, line |
| SIGNAL | `FCTB_REQ_BK` | direction (Rx/Tx), can_name, message_id, rte_function |
| STATE | `FCTB.Active` | state_id (0-6), state_name, func |
| MODULE | `FCTB` | keywords (FUNC_KEYWORDS) |
| CALIB_PARAM | `fFctbBrakeTime` | value, unit, category |

#### 7.4.3 边类型 (Edge Types)

| 类型 | 含义 | 示例 |
|------|------|------|
| CALLS | 函数 A 调用函数 B | FctaFctbUpdateStatus → FctbCheckTargets |
| READS_VAR | 函数 F 读变量 V | FctaFctbUpdateStatus 读 fFctbActiveUpSpd |
| WRITES_VAR | 函数 F 写变量 V | FctaFctbUpdateStatus 写 fctbSystemState |
| READS_SIGNAL | 函数通过 Rte_Read 读信号 S | FctaFctbUpdateStatus 读 FCTB_Enable_S |
| WRITES_SIGNAL | 函数通过 Rte_Write 写信号 S | ASWOUT_OutCalc 写 CR_BrkgReq |
| BELONGS_TO | 实体属于模块 M | FctaFctbUpdateStatus → FCTB |
| DEFINED_IN | 函数/变量定义在文件 F | FctaFctbUpdateStatus → adasFunc.c |
| TRANSITION | 状态 A → 状态 B | Standby → Active (condition: "车速在范围内") |
| SHARES | 模块 M1 和 M2 共享实体 | FCTB ↔ FCTA 共享 FctaFctbUpdateStatus |
| PARAM_FOR | 变量 V 是模块 M 的校准参数 | fFctbBrakeTime → FCTB |

#### 7.4.4 分析阶段

```
Phase 1: File Index           扫描所有 .c/.h 文件，建立文件节点
Phase 2: Function Extraction  正则匹配函数定义，建立 FUNCTION 节点 + 行号范围
Phase 3: Call Graph           对每个函数体，匹配 function_name( 建立 CALLS 边
Phase 4: Variable Access      匹配全局变量访问，区分读/写
Phase 5: Signal Interface     匹配 Rte_Read/Rte_Write/ReadSignal/WriteSignal
Phase 6: State Machine        匹配 .systemState = N 赋值 + switch/if(state)
Phase 7: Module Binding       基于 FUNC_KEYWORDS 将函数/变量绑定到功能模块
Phase 8: Cross-Module         自动发现跨模块共享实体
Phase 9: Calibration Params   从 paraDefine.h 提取校准参数，建立 PARAM_FOR 边
Phase 10: Behaviour Patterns  实现 6 种行为模式检测 (替代 pattern_extractor.py)
```

#### 7.4.5 增量更新策略

```
1. 每次构建前，读取每个文件的 SHA-256 hash
2. 与 codegraph.db 中的 file_hashes 表比对
3. 未变化的文件 → 跳过该文件的所有分析阶段
4. 变化的文件 → 只重新分析该文件，清除受影响的边
5. 跨文件影响: 函数签名变化 → 更新所有调用该函数的边
```

### 7.5 与现有模块的集成点

#### 7.5.1 替代/增强现有确定性分析

| 现有模块 | CodeGraph 替代部分 |
|---------|-------------------|
| `signal_mapper.extract_signal_mapping` | Phase 5 (Signal Interface) + BELONGS_TO 边 |
| `signal_mapper.trace_variable_chains` | Phase 4 (Variable Access) + struct field 解析 |
| `pattern_extractor.extract_all` | Phase 10 (Behaviour Patterns) — 全量 6 种模式 |
| `parameter_analyzer.scan_parameters` | Phase 9 (Calibration Params) |

**过渡策略**: 不立即删除旧模块，新增 `--use-codegraph` 标志启用新路径，验证稳定后再迁移。

#### 7.5.2 CLI 新增命令

```bash
# 构建/更新 codegraph
py -3.11 cli.py --build-codegraph [--force]

# 查询 codegraph (自然语言 → SQL)
py -3.11 cli.py --query-codegraph "哪些函数调用了 FctaFctbUpdateStatus?"

# 查看 codegraph 统计
py -3.11 cli.py --codegraph-stats

# 导出 codegraph 为可视化的 HTML 调用图
py -3.11 cli.py --export-codegraph
```

#### 7.5.3 与 orchestrator 的集成

```
Step 1 (init): 触发 codegraph 增量构建 (新增)
Step 7 (conditions): 可从 codegraph 获取精确的状态机转换 (增强)
Step 8 (tpe): 可从 codegraph 获取调用链证据 (增强)
Step 9 (probe): VariableQueryPlanner 可生成 codegraph SQL 查询 (增强)
Step 14 (diagnose): Expert Panel 注入 codegraph 查询结果 (增强)
```

#### 7.5.4 与 code_learner 的协同

```
改造前: CodeLearner 读源码 → 关键字过滤 → LLM 抽取 → 写 JSON
改造后: CodeGraph 提供精确结构 → CodeLearner 只需对"语义块"做 LLM 抽取
        → CodeLearner 的 prompt 中可以注入 codegraph 查询结果
        → 提高 LLM 抽取的准确性 (已知精确的行号范围、调用关系)
```

---

## 8. 实施计划 (待确认)

### Phase A: 基础设施

- [ ] 创建 `ai/codegraph/` 包 (builder.py, schema.py, analyzer.py, query.py)
- [ ] SQLite schema 定义 + 初始化
- [ ] 增量 hash 机制
- [ ] CLI 命令集成 (`--build-codegraph`, `--codegraph-stats`)

### Phase B: 核心分析 (Phase 1-5)

- [ ] File Index + Function Extraction (Phase 1-2)
- [ ] Call Graph (Phase 3) — 最有价值的关系类型
- [ ] Variable Access (Phase 4)
- [ ] Signal Interface (Phase 5) — 与现有 signal_mapping.json 交叉验证

### Phase C: 高级分析 (Phase 6-10)

- [ ] State Machine (Phase 6)
- [ ] Module Binding (Phase 7)
- [ ] Cross-Module Dependencies (Phase 8)
- [ ] Calibration Params (Phase 9)
- [ ] Behaviour Patterns (Phase 10) — 替代 pattern_extractor

### Phase D: 集成与验证

- [ ] orchestrator 集成 (Step 1 增量构建)
- [ ] VariableQueryPlanner 集成 (codegraph SQL 查询)
- [ ] Expert Panel 注入 codegraph 结果
- [ ] 与现有 code_knowledge 交叉验证
- [ ] 准确率评估 (抽样检查 20+ 函数调用关系)
- [ ] 性能测试 (全量构建时间 < 30s)

### Phase E: 清理与迁移

- [ ] 旧确定性分析模块迁移到 CodeGraph
- [ ] signal_mapping.json / code_patterns.json / parameters.json 接口兼容层
- [ ] 更新 AGENTS.md 文档

---

## 9. 待调研事项

在确认改造计划前，需要进一步调研以下问题:

### 9.1 源码规模

- `adasFunc.c` 实际行数? 最大的几个文件各多少行?
- 总共有多少个 `.c` 和 `.h` 文件在 `key_source_files` 中?
- 函数定义总数大约多少?

### 9.2 正则 vs AST 精度

- 当前 `signal_mapper` 的正则准确率如何? 有无已知误匹配?
- `pattern_extractor` 的 HoldRelease 检测准确率?
- 宏调用 (`#define CALL_FCTB() FctaFctbUpdateStatus()`) 的影响程度?

### 9.3 查询需求

- 诊断管线中最常用的代码查询是什么? (调用链? 变量依赖? 信号链路?)
- Expert Panel 的 prompt 中引用代码知识的频率?
- DataProbe 是否已有查询 code_knowledge 的逻辑?

### 9.4 性能预算

- 全量构建是否需要在诊断启动时完成? (如果是，<5s 是硬约束)
- 还是可以在 dream 中异步构建，诊断时只读已构建的 DB?

### 9.5 与 BYD_UKE / GWM_B26 的差异

- 当前源码是针对 GWM_B26 平台的
- BYD_UKE 平台的路径和文件结构不同，CodeGraph 是否需要支持多平台?

---

## 10. 参考资料

- 原始设计文档: `docs/technical/codegraph-design.md`
- 当前开发 handoff: `docs/technical/CR60_PI_UNIFIED_HANDOFF_2026-09-03_PRODUCTIZATION.md`
- 项目 AGENTS.md: 根目录 `AGENTS.md`
- ai/ 模块说明: `ai/AGENTS.md`
- parsers/ 模块说明: `parsers/AGENTS.md`
- memory/ 模块说明: `memory/AGENTS.md`
- source_docs/ 说明: `source_docs/AGENTS.md`
- 完整实现文档: `IMPLEMENTATION.md` (~210KB)
