# ai/ 模块实现说明

> 用于「需求 ↔ 实现」review。AI 编辑 ai/ 目录文件时参考本文档。

---

## 模块概览

| 文件 | 定位 | AI 调用 |
|------|------|---------|
| `orchestrator.py` | 诊断管线总编排 (15+ 步) | complex × 1, chat × 2 |
| `frame_analyzer.py` | 帧级证据提取 (状态跳变/警告时间线/目标速度) | 无 |
| `test_window_detector.py` | 纯规则窗口检测 | 无 |
| `temporal_analyzer.py` | 信号时间线 → 边/段/统计/模式标签 | 无 |
| `parameter_analyzer.py` | 阈值扫描 + 敏感性 + what-if | 无 |
| `data_probe.py` | FrameStore SQLite 探针 (asteval + numpy) | 无 |
| `problem_classifier.py` | 任务分类: diagnose/tune/verify/query | simple × 1 |
| `signal_mapper.py` | CAN ↔ 内部变量映射 (纯正则) | 无 |
| `condition_extractor.py` | AI 提取条件树 + 确定性后处理 | complex × 1 |
| `causal_aligner.py` | 代码模式 ↔ 数据时序对齐 (纯规则) | 无 |
| `variable_query_planner.py` | AI 规划 DataProbe 查询 | chat(complex) × 1 |
| `expert_panel.py` | 多专家 3 轮研讨 | complex × 多次 |
| `data_query_engine.py` | 自然语言查数 (query 模式) | complex × 2 |
| `code_learner.py` | 源码增量学习 → L6 JSON | complex × 多次 |
| `tpe.py` | 时序模式引擎门面 | 无 |
| `pattern_extractor.py` | C 源码行为模式提取 (纯正则) | 无 |
| `visualizer.py` | Plotly HTML 报告生成 | 无 |
| `model_router.py` | local/remote 模型选路 | — |
| `context_budget.py` | 字符级 prompt 预算管理 | — |
| `utils.py` | parse_json_from_llm, get_func_fields, ALL_FUNCTIONS 等 | — |

---

## orchestrator.py — 诊断编排器

### 公开接口

```
class Orchestrator:
    def __init__(self, config: dict, project_root: Path)          # 69-77
    def run_diagnosis(self, case_dir, problem, expected,
                      on_status=None) -> str                      # 79-85
```

成员: `self.config`, `self.project_root`, `self.router` (ModelRouter), `self.memory` (MemorySystem 延迟导入), `self._last_tpe_result`

### run_diagnosis 管线步骤

| Step | status key | 动作 | 输出 |
|------|-----------|------|------|
| 1 | `init` | `_ensure_source_docs` → CodeLearner + signal_mapping | source_docs 文件 |
| 2 | `understand` | `_understand_problem` (LLM complex) | `func_info` dict |
| 3 | `classify` | ProblemClassifier.classify | `classification`, 可能覆盖 func_name |
| 4 | `parse` | case_loader.load_case_data | store, bag_meta, blf_meta, sync |
| 5 | `detect_window` | TestWindowDetector.detect | `windows` list |
| 6 | `analyze` | FrameAnalyzer.extract_evidence | `evidence` dict, `frame_analysis` str |
| 7 | `conditions` | ConditionExtractor.extract (LLM) | `conditions` dict |
| 8 | `tpe` | TemporalPatternEngine.run | tpe_text, tpe_report |
| 9 | `probe` | VariableQueryPlanner + DataProbe (LLM) | probe_section str |
| 10 | `suppression` | `_check_suppression_signals` | suppression_text |
| 11 | `output_signals` | `_analyze_output_signals` | output_signal_text |
| 12 | — | `_load_threshold_reference` | threshold_ref (≤4000 chars) |
| 13 | `params` | parameter_analyzer (仅 tune/verify) | param_section_md |
| 14 | `diagnose` / `panel_prompt` | ExpertPanel.run_panel (LLM 3 轮) | panel_result dict |
| 15 | `report` | `_save_report` + `_save_expert_appendix` | report.md, expert_opinions.md |
| 16 | `visualize` | build_html_report | report.html |
| 17 | `done` | `_update_memories` + complete_session | memory 写入 |

### 关键数据结构

**func_info** (来自 _understand_problem): `function`, `confidence`, `reasoning`, `fail_type`, `key_variables`, `related_functions`

**evidence** (来自 FrameAnalyzer): `KEY_FACTS`, `timeline`, `state_transitions`, `warning_states`, `ego_*`, `radar_objects_warned`, `warning_events`, `can_summary`, `tpe_block`, `tpe_report`

**panel_result** (来自 ExpertPanel): `expert_opinions`, `moderator_challenges`, `final_verdict`, `rounds`

### AI 调用点 (本文件内)

| 行号 | 调用 | 用途 |
|------|------|------|
| 1318 | `router.complex(prompt, system=ORCHESTRATOR_SYSTEM)` | 问题理解 → func_info JSON |
| 1346-1350 | `router.chat(..., complexity="simple", max_tokens=1024)` | 帧分析中文短摘要 |
| 1514-1518 | `router.chat(..., complexity="simple", max_tokens=1024)` | 诊断 → pattern JSON |

### ContextBudget 配置 (460-476)

`total_chars=60_000`，各块按 priority/min_chars 裁剪:
- key_facts: priority=100
- timeline: priority=80
- conditions_text: priority=70
- tpe_section, suppression, output: priority=60
- evidence_text: priority=40

### Review 关注点

1. `func_name` 双源融合: _understand_problem + ProblemClassifier，覆盖阈值在 128-131
2. `tpe_section` 因 evidence.pop 顺序通常为空，TPE 叙述在 KEY_FACTS 中
3. `_run_tpe`/`_check_suppression_signals`/`_analyze_output_signals` 签名含 windows 但**未使用**
4. `_update_memories` 静默失败 (except: pass)
5. `store.close()` 未校验 store 非空

---

## frame_analyzer.py

### 公开接口

| 签名 | 行号 |
|------|------|
| `__init__(self, router, variables_path=None)` | 23-29 |
| `extract_evidence(self, store, func_name, windows=None) -> dict` | 103-180 |
| `append_tpe_block(evidence, tpe_block, tpe_report)` (static) | 183-194 |
| `format_timeline(timeline, max_lines=200, func_name="")` (static) | 575-615 |

**不调用 AI** (router 仅保存未使用)。

### 抽样阈值

- 无窗口: ego `step = max(1, len//50)`，最多 50 帧 (342-343)
- warning_states 超 60 再抽到 60 (400-402)
- 雷达对象最多 200 条快照，warned 最多 100 (210-223)
- warning_events 最多 50 (299)
- can_summary 前 15 条 (168)
- KEY_FACTS 跳变最多 20 条 (453)

---

## test_window_detector.py

### 公开接口

| 签名 | 行号 |
|------|------|
| `TestWindowDetector.detect(store, func_name, speed_thresholds=None) -> list[TestWindow]` | 50-99 |
| `format_windows(windows) -> str` (static) | 388-403 |

**不调用 AI**。事件检测 → ±2s padding → 区间合并 → 回退 (无事件时取最活跃点 ±5s)。

### 事件类型

- `target_appear/disappear`: |vel| > 0.5 或 |dist| > 0.3，连续 ≥3 帧
- `state_change`: 系统状态跳变
- `warning_on/off`: 警告字段变化
- `speed_up/down`: 速度穿越阈值
- `warning_edge_on/off`: 从 warning_events 表
- `object_approach`: 目标距离减半

### 阈值

`_PADDING_SEC=2.0`, `_MIN_TARGET_FRAMES=3`, `_TARGET_VEL_THRESH=0.5`, `_TARGET_DIST_THRESH=0.3`, `_FALLBACK_WINDOW_SEC=10.0`, `_GENERIC_SPEED_THRESHOLDS=[0.5, 5.0, 10.0, 21.0]`

**Review**: `car_spd` 单位 (m/s) 与详情字符串中写的 km/h 可能不一致。

---

## signal_mapper.py

### 公开接口

| 签名 | 行号 |
|------|------|
| `extract_signal_mapping(source_root, output_dir, rte_file=...) -> dict` | 131 |
| `extract_output_signal_mapping(source_root, output_dir, rte_file=...) -> dict` | 221 |
| `resolve_internal_to_can(var_name, mapping, chains=None) -> list[str]` | 267 |
| `resolve_can_to_internal(can_signal, mapping) -> list[str]` | 333 |
| `trace_variable_chains(source_root, output_dir, ...) -> dict` | 576 |
| `load_variable_chains(output_dir) -> dict` | 694 |

**不调用 AI**。纯正则解析 `RteComMapping.c` 建立 CAN ↔ 内部变量映射。

### resolve_internal_to_can 优先级

1. `internal_to_can` 精确
2. `fullpath_to_can` 精确
3. 点路径最后一段
4. struct_aliases (variable_chains) 前缀展开
5. 大小写不敏感
6. 核心子串 (≥5 字符) 双向 in 匹配

### 缓存

- signal_mapping.json: SHA256 前 16 位
- output_mapping.json: 同上
- variable_chains.json: **无缓存**，每次重写

---

## condition_extractor.py

### 公开接口

| 签名 | 行号 |
|------|------|
| `ConditionExtractor.__init__(self, router, project_root, config)` | 141 |
| `ConditionExtractor.extract(func_name, force=False) -> dict` | 149 |
| `format_conditions(conditions) -> str` (static) | 288 |

**AI 提取**: `router.complex(prompt, max_tokens=16384)`，输出 JSON 条件树。

### 缓存失效

- 缓存路径: `source_docs/{FUNC}_conditions.json`
- 失效: 任一域内源码文件 `mtime > cache_mtime`
- `force=True` 跳过缓存

### 极性规则 (prompt 34-135)

`suppression_trigger` 必须对应「导致退出/抑制/回退」为真时的条件。`normal_value` 为不抑制时的典型相反描述。强调 "Active" 在变量名里不代表 TRUE 即抑制。

---

## causal_aligner.py

### 公开接口

| 签名 | 行号 |
|------|------|
| `CausalAligner.__init__(self, signal_mapping=None, variable_chains=None)` | 134 |
| `CausalAligner.align(patterns, features, state_timeline=None, func_name_filter=None) -> list[PatternEvidence]` | 142 |

**不调用 AI**。将代码侧 CodePattern 与数据侧 TemporalFeature 做时间区间交集对齐。

verdict: `triggered` / `not_triggered` / `insufficient_data` / `unknown`

只支持 AND 合取；OR/括号嵌套未完整建模。

---

## variable_query_planner.py

### 公开接口

| 签名 | 行号 |
|------|------|
| `VariableQueryPlanner.__init__(self, router, memory_system, project_root)` | 180 |
| `VariableQueryPlanner.plan(problem, expected, func_name, fail_type, focus_params, store, *, max_queries=6, use_thinking=False) -> list[QueryPlan]` | 187 |
| `render_probe_results_for_prompt(plans, results, max_chars=6000) -> str` (static) | 358 |

**AI 规划**: `router.chat(..., complexity="complex", temperature=0.2, max_tokens=1800)`

LLM 失败时 `_fallback_plan` 提供基础查询 (dist_y + side, ttc 等)。

---

## expert_panel.py

### 公开接口

| 签名 | 行号 |
|------|------|
| `ExpertPanel.__init__(self, router, config, project_root)` | 209 |
| `ExpertPanel.select_experts(fail_type="OTHER") -> dict` (static) | 219-223 |
| `ExpertPanel.run_panel(problem, expected, func_name, data_summary, memory_context="", on_status=None, fail_type="OTHER", task_type="diagnose") -> dict` | 225-235 |

### 5 位专家

| expert_id | 角色 | 职责 |
|-----------|------|------|
| `signal_chain` | 信号链路专家 | CAN → RteComMapping → 内部变量 → 条件 |
| `algorithm` | 算法逻辑专家 | adasFunc.c 条件与阈值 |
| `system_state` | 系统状态专家 | 双状态机与使能 |
| `perception` | 感知与目标专家 | 目标属性与过滤 |
| `architecture` | 架构专家 | 左右雷达与输出合并 |

按 `fail_type` 子集选专家: FP/FN/DELAY/STATE 各 3 人，OTHER 才 5 人全上。

### 3 轮迭代

- **R1 (独立分析)**: ThreadPoolExecutor 并行，MAX_PARALLEL=5。要求先读 TPE、填条件表、标明行号。
- **R2 (交叉质疑)**: 主持人 `_moderator_challenge` → JSON (contradictions, gaps, questions)；专家仅回应非空追问，≤500 字。
- **R3 (综合收敛)**: 主持人 `_moderator_synthesize` → `final_verdict` (Markdown)。强制章节: 数据溯源规则/根因/TPE表/条件汇总/证据链/修复建议/置信度。

### thinking 控制

- R1/R2 专家 + R2 主持人: `thinking_mode == "full"` 时 `thinking=True`
- R3 综合: `thinking_mode in ("synth", "full")` 时 `thinking=True`
- 本文件**仅使用** `router.complex`

---

## data_query_engine.py

### 公开接口

| 签名 | 行号 |
|------|------|
| `DataQueryEngine.__init__(self, router, config, project_root)` | 105 |
| `DataQueryEngine.run_query(case_dir, question, on_status=None) -> str` | 122-127 |

流程: parse → inventory → plan (AI) → validate → extract → answer (AI) → 返回 Markdown

**仅使用** `router.complex`，`data_text` 截断 12000 字符。

---

## problem_classifier.py

### 公开接口

| 签名 | 行号 |
|------|------|
| `ProblemClassifier.__init__(self, router=None)` | 154-155 |
| `ProblemClassifier.classify(problem, expected="", memory_hint="") -> ClassificationResult` | 159-187 |

ClassificationResult: `task_type`, `confidence`, `target_function`, `focus_parameters`, `focus_signals`, `reasoning`

**先规则后 LLM**: verify (0.92/0.85) > tune (0.88/0.8) > query (0.75) > diagnose (0.85)。无 router 时默认 diagnose(0.3)。

---

## code_learner.py

### 公开接口

| 签名 | 行号 |
|------|------|
| `CodeLearner.__init__(self, router, config, project_root)` | 303-330 |
| `CodeLearner.learn(status_cb=None, force_pairs=None) -> dict` | 334-431 |
| `CodeLearner.ensure_overview_docs(funcs=None, force=False, status_cb=None) -> dict` | 433-511 |

### 4 个 focus

| focus | 提取目标 | JSON 结构 |
|-------|---------|----------|
| `alarm_logic` | 触发/取消/退出/迟滞/延时/抑制 | trigger/cancel/exit_conditions, hysteresis, timers, suppression |
| `calculation_chain` | 变量计算/数据链/阈值 | key_variables, derivation_chain, thresholds_used |
| `output_chain` | 内部→ASWOUT→RteComMapping→CAN | outputs, merge_strategy, external_gating |
| `state_machine` | 状态编号/转换/双状态机交互 | states, transitions, entry_functions, dual_state_interaction |

学习单元: 4 focus × 8 functions = 32 个 (func, focus) 槽位。源码 hash 跳过已学过且未变更的。

输出: `memory/code_knowledge/{FUNC}.json`，`learning_state.json`，`source_docs/.overview_hashes.json`

### 预算

- `warmup_pairs` (默认 8) / `pairs_per_dream` (默认 2)
- `max_snippet_chars` 默认 40000

---

## tpe.py — 时序模式引擎

### 公开接口

| 签名 | 行号 |
|------|------|
| `TPEResult` dataclass | 38-89 |
| `TemporalPatternEngine.__init__(self, source_root, cache_dir=None, signal_mapping=None, variable_chains=None)` | 95-113 |
| `TemporalPatternEngine.run(store, func_name=None, extra_patterns=None, state_transitions=None, time_window=None) -> TPEResult` | 117-183 |

**不调用 LLM**。组装 PatternExtractor + TemporalAnalyzer + CausalAligner。

流程: extract_all → func 过滤 → 变量解析 → load_can_signal → temporal analyze → causal align

---

## pattern_extractor.py

### 公开接口

| 签名 | 行号 |
|------|------|
| `PatternExtractor.__init__(self, source_root, cache_dir=None, target_files=None)` | 144-152 |
| `PatternExtractor.extract_all(use_cache=True) -> list[CodePattern]` | 154-174 |
| `load_patterns(cache_dir) -> list[CodePattern]` | 484-493 |

**不调用 AI**。仅实现 HoldRelease + Accumulate 两种模式检测。缓存: `code_patterns.json` (源码 hash)。

---

## temporal_analyzer.py

### 公开接口

| 签名 | 行号 |
|------|------|
| `TemporalAnalyzer.analyze(timeline) -> Optional[TemporalFeature]` | 168-199 |
| `load_can_signal(store, message_name, signal_name) -> SignalTimeline` | 290-298 |
| `load_bag_field(store, topic, field_name, ...) -> SignalTimeline` | 301-313 |
| `analyze_many(timelines) -> dict[str, TemporalFeature]` | 315-324 |

**不调用 AI**。pattern_tag: `stable` / `oscillating` / `brief_pulses` / `edge_dominated`

阈值: `BRIEF_PULSE_THRESHOLD_SEC=0.5`, `HIGH_EDGE_RATE_HZ=2.0`

---

## parameter_analyzer.py

### 公开接口

| 签名 | 行号 |
|------|------|
| `scan_parameters(source_root, cache_dir=None, force=False) -> ParameterScanResult` | 277-392 |
| `analyze_sensitivity(source_root, cache_dir, store, func_name, focus_categories=None) -> SensitivityReport` | 555-622 |
| `what_if(sensitivity, proposals, store=None) -> list[WhatIfEntry]` | 644-685 |

**不调用 AI**。扫描 `adasFunc.c/h` + `paraDefine.h`，缓存 `parameters.json` (SHA1)。

SPEED 用 `car_spd * 3.6` 得 km/h 与代码阈值对齐。

---

## data_probe.py

### 公开接口

| 签名 | 行号 |
|------|------|
| `DataProbe.__init__(self, store, windows=None)` | 235-245 |
| `DataProbe.query(field, table="radar_objects", group_by=None, filter=None, stats=None, max_rows=500_000) -> dict` | 276-443 |

**不调用 AI**。仅支持 3 个表: `radar_objects`, `radar_debug`, `warning_events`。

语义字段: `side` (由 dist_y 正负), `in_window` (时间戳在窗口内)。

---

## visualizer.py

### 公开接口

```
def build_report(*, case_dir, func_name, task_type, problem, expected,
                 diagnosis, store, windows, tpe_result=None,
                 param_report=None, whatif_entries=None,
                 bag_meta=None, blf_meta=None) -> VisualizerResult   # 136-219
```

图表: ego-speed, output-signals, state-timeline, tpe-triggers, param-sensitivity (tune/verify), whatif。内联 plotly.js 单文件。

---

## model_router.py

### 选路规则

| complexity | 客户端 | 默认模型 |
|-----------|--------|---------|
| `"simple"` | local (Ollama) | `qwen3:14b` |
| `"complex"` | remote | `Qwen3.5-27B-FP16` |
| `"auto"` | 按规则: tools非空→complex, 总长>3000→complex, 关键词命中→complex, 否则→simple | — |

`thinking` 参数仅在 remote 分支生效: `enable_thinking: True` → `presence_penalty=1.5, temperature=1.0, top_p=0.95`

local 失败时自动回退 remote (119-138)。

`thinking_mode` (off/synth/full) 存储在 router 但**不在路由层使用**，由调用方 (expert_panel 等) 读取并传入 `thinking=bool`。

---

## context_budget.py

`ContextBudget(total_chars=60_000)` — 字符级软上限，按 priority 降序分配，超预算先压缩低优先级块，每块保留 ≥ min_chars。

---

## utils.py

| 函数 | 行号 | 职责 |
|------|------|------|
| `parse_json_from_llm(content, fallback=None)` | 17-31 | 首末 `{}` 截取 JSON |
| `extract_relevant_sections(text, keywords, context_lines=15, max_chunks=30)` | 36-73 | 关键词匹配源码片段 |
| `build_keyword_variants(func_name)` | 76-80 | ADAS 功能名 C 标识符变体 |
| `get_func_fields(func_name) -> dict` | 219-227 | FUNC_FIELD_MAP 查表 |
| `ALL_FUNCTIONS` | 85 | `["BSD","LCA","DOW","RCW","RCTA","RCTB","FCTA","FCTB"]` |
