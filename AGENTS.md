# radarAnalyze

Corner Radar AI 诊断工具：对 ADAS 功能（BSD/LCA/DOW/RCW/RCTA/RCTB/FCTA/FCTB）的录制数据做自动化根因分析。

## 运行模式

| 模式 | CLI 入口 | 核心模块 |
|------|----------|----------|
| **Diagnosis** | `cli.py --mode diagnosis` | `ai/orchestrator.py` → 10+ 步管线 |
| **Query** | `cli.py --mode query` | `ai/data_query_engine.py` |
| **Dream** | `cli.py --mode dream` | `memory/auto_dream.py` → Phase 0-4 |

## 诊断管线步骤概览

| Step | 名称 | 模块 |
|------|------|------|
| 1 | init + source_docs 保障 | `code_learner.ensure_overview_docs` |
| 2 | understand — 问题理解 | `orchestrator._understand_problem` (LLM) |
| 3 | classify — 任务分类 | `problem_classifier.classify` |
| 4 | parse — 数据解析 | `parsers/case_loader.load_case_data` |
| 5 | detect_window — 窗口检测 | `test_window_detector.detect` |
| 6 | analyze — 帧级分析 | `frame_analyzer.extract_evidence` |
| 7 | conditions — 条件提取 | `condition_extractor.extract` (LLM) |
| 8 | tpe — 时序模式引擎 | `tpe.TemporalPatternEngine.run` |
| 9 | probe — 变量探测 | `variable_query_planner` + `data_probe` (LLM) |
| 10 | suppression — 抑制检查 | `orchestrator._check_suppression_signals` |
| 11 | output_signals — 输出信号 | `orchestrator._analyze_output_signals` |
| 12 | params — 参数敏感性 | `parameter_analyzer` (仅 tune/verify) |
| 13 | diagnose — 专家面板 | `expert_panel.run_panel` (LLM, 3 轮) |
| 14 | report + visualize | `visualizer.build_report` → HTML |
| 15 | memory update + done | `memory_system` L1-L5 写入 |

## 目录结构与文档导航

```
radarAnalyze/
  cli.py                  # 统一 CLI 入口
  config.yaml             # 模型/路径/功能/学习 配置
  ai/                     # AI 分析模块 → 详见 ai/AGENTS.md
  parsers/                # 数据解析层  → 详见 parsers/AGENTS.md
  memory/                 # 记忆系统    → 详见 memory/AGENTS.md
  source_docs/            # 缓存知识    → 详见 source_docs/AGENTS.md
  cases/                  # 案例数据（.bag/.blf + 报告产物）
  scripts/                # 冒烟测试脚本
  tools/                  # 辅助工具（render_report, run_tpe_smoke）
  tests/                  # 测试（test_temporal_pattern_engine）
  IMPLEMENTATION.md       # 完整实现文档（归档/全文搜索用）
```

## 跨模块依赖速查

| 生产方 | 消费方 | 数据 |
|--------|--------|------|
| parsers/case_loader | orchestrator._parse_case_data | CaseLoadResult (store, bag_meta, blf_meta, sync) |
| signal_mapper | orchestrator._run_tpe, _check_suppression_signals | signal_mapping dict, variable_chains dict |
| condition_extractor | orchestrator (conditions step) | {FUNC}_conditions.json |
| frame_analyzer | orchestrator (analyze step) | evidence dict, frame_analysis str |
| test_window_detector | orchestrator, frame_analyzer, data_probe | list[TestWindow] |
| pattern_extractor | tpe.TemporalPatternEngine | list[CodePattern] |
| temporal_analyzer | tpe, causal_aligner | dict[str, TemporalFeature] |
| causal_aligner | tpe.TemporalPatternEngine | list[PatternEvidence] |
| tpe | orchestrator._run_tpe | TPEResult |
| problem_classifier | orchestrator (classify step) | ClassificationResult |
| variable_query_planner | orchestrator (probe step) | list[QueryPlan] |
| data_probe | orchestrator (probe step) | ProbeResult dict |
| expert_panel | orchestrator (diagnose step) | panel_result dict |
| parameter_analyzer | orchestrator (params, tune/verify) | SensitivityReport, WhatIfEntry |
| context_budget | orchestrator (panel_prompt) | truncated prompt str |
| visualizer | orchestrator (visualize step) | VisualizerResult |
| memory_system | orchestrator, auto_dream, data_query_engine | L1-L6 读写 |
| code_learner | auto_dream Phase 0, orchestrator._ensure_source_docs | L6 JSON, overview MD |
| model_router | 几乎所有 AI 模块 | chat/simple/complex 统一接口 |

## 文档维护规则

### 何时更新

以下变更发生时，更新对应目录的 `AGENTS.md`：

1. 新增/删除/重命名 `.py` 模块或公开类/函数
2. 修改公开 API 签名（参数、类型、默认值）
3. 修改 AI prompt 内容（system/user prompt、JSON schema）
4. 修改缓存/失效策略（hash、mtime、路径）
5. 修改阈值/魔数（如 `total_chars=60000`、`_PADDING_SEC=2.0`）
6. 修改数据结构 schema（FrameStore 表、JSON 文件、evidence dict）
7. 修改管线步骤顺序或新增步骤
8. 修改专家面板配置或记忆层级 API

### 更新方法

1. 定位变更所属目录 → 更新该目录的 `AGENTS.md`
2. 若涉及跨模块交互 → 两侧 AGENTS.md 都更新
3. 若影响管线步骤或依赖关系 → 同步更新本文件的速查表

### Review Checklist

- [ ] 公开接口签名与代码一致
- [ ] 数据结构字段与代码一致（含 JSON schema）
- [ ] AI prompt 内容与代码字符串常量一致
- [ ] 缓存失效条件与代码逻辑一致
- [ ] 阈值/魔数与代码值一致
- [ ] 处理流程步骤顺序与代码执行顺序一致
- [ ] 依赖关系正确
