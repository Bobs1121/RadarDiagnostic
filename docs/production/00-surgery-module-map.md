# radarAnalyze 生产级设计体系 · 00 · 外科手术式模块图谱

> **版本**: PROD-1.0 · 2026-08-13
> **性质**: 本系列文档（`docs/production/`）为早期生产校准记录。当前产品主线以
> `docs/CR60_PI_UNIFIED_PRD.md`、`docs/technical/CR60_PI_UNIFIED_SYSTEM_DESIGN.md`
> 和 `docs/technical/CR60_PI_UNIFIED_DOCUMENT_INDEX.md` 为准。
> **本篇定位**: 细胞级拆解 —— 对全量 Python 模块逐一拆解，标注职责、调用关系、成熟度、LLM 依赖、断层状态，形成依赖热力图。

---

## 0. 阅读指引

- **成熟度分级**：
  - 🟢 **生产**：被 `ai/orchestrator.py` 诊断主链路或 `cli.py` 高频入口直接调用。
  - 🟡 **实验**：可通过 CLI 子命令触达，但**不在** orchestrator 生产路径内。
  - ⚪ **孤儿/测试**：仅被测试或独立脚本引用，生产链路不可达。
- **LLM 依赖**：`✅LLM` = 直接调用 `model_router`；`—` = 确定性，无 LLM。
- **断层**：`🔴死代码` / `⚠️半成品` / `🟡未分发` / `✅正常`。

---

## 1. 模块总览统计

| 维度 | 数量 |
|---|---|
| Python 模块（排除 workspace/参考物料/缓存） | ~120 个 |
| 其中生产链路可达 | ~40 个 |
| 其中实验/CLI-only | ~30 个 |
| 其中孤儿/测试-only | ~50 个（大量 `scripts/*.py`） |
| 总代码量 | ~7.9 万行 Python |

**核心结论**：真正的「生产心脏」集中在 `ai/orchestrator.py`(2658行) + `cli.py`(1721行) + `parsers/` + `core/` + `memory/`。其余大量模块（`ai/modules/*`、`ai/tools/*`、`ai/requirements/*`、`ai/agent_loop.py`、`ai/investigation_engine.py`、`harness/*`、`platforms/gen5_selena/*`、`plugins/rule_engine.py`）是**并行/实验系统**，未接入诊断主路径。

---

## 2. 模块手术图谱（按依赖方向分簇）

### 簇 A · 生产心脏（orchestrator 直接 import）

`ai/orchestrator.py:13-31` 的 import 列表是「生产心脏」的权威边界：

| 模块 | 公开类/函数（行号） | 职责 | LLM | 成熟度 | 断层 |
|---|---|---|---|---|---|
| `ai/orchestrator.py` | `Orchestrator.run_diagnosis`(316) | 8 步诊断管线总编排 | ✅ | 🟢 | ⚠️ `codegraph_db_path` 死代码(270-274) |
| `ai/model_router.py` | `ModelRouter.chat/complex`(59) | 三模型选路+回退 | ✅ | 🟢 | ✅ |
| `ai/code_learner.py` | `CodeLearner.learn`(334) | 源码→L6 JSON | ✅ | 🟢 | ✅ |
| `ai/frame_analyzer.py` | `FrameAnalyzer.extract_evidence`(103) | 帧级证据 | — | 🟢 | ✅ |
| `ai/expert_panel_langgraph.py` | `ExpertPanel.run_panel`(225) | 5专家×3轮研讨 | ✅ | 🟢 | ✅ |
| `ai/test_window_detector.py` | `TestWindowDetector.detect`(50) | 规则窗口检测 | — | 🟢 | ✅ |
| `ai/condition_extractor.py` | `ConditionExtractor.extract`(149) | AI 条件树提取 | ✅ | 🟢 | ✅ |
| `ai/rule_condition_extractor.py` | `RuleConditionExtractor`(106) | 确定性条件提取 | — | 🟢 | ✅ |
| `ai/problem_classifier.py` | `ProblemClassifier.classify`(159) | 任务分类 | ✅ | 🟢 | ✅ |
| `ai/parameter_analyzer.py` | `analyze_sensitivity`(555) | 参数灵敏度 | — | 🟢 | ✅ |
| `ai/visualizer.py` | `build_report`(136) | Plotly 报告 | — | 🟢 | ✅ |
| `ai/utils.py` | `parse_json_from_llm`(17) | JSON/utils | — | 🟢 | ✅ |
| `ai/context_budget.py` | `compute_budget`(674) | 动态预算 | — | 🟢 | ✅ |
| `ai/data_probe.py` | `DataProbe.query`(276) | SQLite 探针 | — | 🟢 | ✅ |
| `ai/variable_query_planner.py` | `VariableQueryPlanner.plan`(187) | AI 规划查询 | ✅ | 🟢 | ✅ |
| `ai/fallback.py` | `safe_llm_call`(151) | LLM 安全回退 | ✅ | 🟢 | ⚠️ `fallback_*` 未全用 |
| `ai/observability.py` | `StepLogger/TokenTracker`(17/87) | 可观测性 | — | 🟢 | ✅ |

### 簇 B · 数据解析层（parsers/）

| 模块 | 公开类/函数 | 职责 | LLM | 格式 | 断层 |
|---|---|---|---|---|---|
| `parsers/case_loader.py` | `load_case_data`(59) | 按扩展名分发解析 | — | 全 | 🔴 硬编码 glob(59-238) |
| `parsers/bag_parser.py` | `BagParser` | ROS bag 流式解析 | — | .bag | ✅ |
| `parsers/blf_parser.py` | `BlfParser` | python-can BLF | — | .blf | ✅ |
| `parsers/mf4_parser.py` | `Mf4Parser` | asammdf MF4 | — | .mf4 | ✅ |
| `parsers/dbc_loader.py` | `DbcLoader` | DBC/CAN 矩阵 | — | .dbc | ✅ |
| `parsers/frame_store.py` | `FrameStore`(21) | SQLite 5表存储 | — | 统一 | ✅ |
| `parsers/time_sync.py` | `TimeSync` | bag/blf 时间对齐 | — | 混合 | ⚠️ 手动 offset |

### 簇 C · 平台适配层（ai/platform_adapters/）

| 模块 | 内容 | LLM | 断层 |
|---|---|---|---|
| `platform_adapters/factory.py` | 3 个装饰器注册表 + 惰性导入(53-61) | — | 🔴 硬编码导入列表；orchestrator 用错 key |
| `platform_adapters/base.py` | 3 个 ABC 接口(41/106/133) | — | ✅ |
| `platform_adapters/gen6_symmetry.py` | Gen6 实现(注册于 353/430/472) | — | ✅ |
| `platform_adapters/gen5_reco_pl.py` | Gen5 ReCo 实现(注册于 24/257/335) | — | ✅ |
| `platform_adapters/gen5_gen.py` | **占位 stub**（写占位文件） | — | ⚠️ 非真 adapter |

### 簇 D · 身份/工作区/知识（core/）

| 模块 | 公开类/函数 | 职责 | 断层 |
|---|---|---|---|
| `core/identity.py` | 五层身份模型(36-...) | PlatformFamily/Codebase/Variant/... | 🟡 `codegraph_plugin/parser_plugin/symbol_ruleset` 未分发(51-54) |
| `core/workspace.py` | `Workspace`(34) | Core/COEM 级联继承 | ✅ |
| `core/freshness.py` | `compute_variant_fingerprint`(29) | freshness 指纹 | ✅ |
| `core/knowledge_guard.py` | `KnowledgeFreshnessGuard`(63) | fail-closed 知识门 | ⚠️ legacy 模式放行(117-118) |
| `core/materials.py` | `MaterialRegistry` | 材料/需求注册 | ✅ |
| `core/diagnosis_bundle.py` | `DiagnosisBundle`(155) | 结构化诊断产物 | ✅ |
| `core/snapshot_store.py` | `SnapshotStore`(27) | 快照存储 | ✅ |
| `core/models.py` | dataclasses(16-175) | SimConfig/LogEntry 等 | ⚠️ 仅 gen5/rule_engine 用 |

### 簇 E · 记忆层（memory/）

| 模块 | 公开类/函数 | 职责 | LLM | 断层 |
|---|---|---|---|---|
| `memory/memory_system.py` | `MemorySystem`(1133) | L1-L6 JSON | — | ⚠️ L5 已并入 L3；文档过时 |
| `memory/auto_dream.py` | `AutoDream`(749) | Phase0-4 固化 | ✅ | ⚠️ `_refresh_variable_chains` 空操作 |
| `memory/semantic_memory.py` | `SemanticMemory`(506) | LanceDB/fallback 向量 | — | 🔴 LanceDB 休眠；路径不一致 |
| `memory/__init__.py` | 导出 | — | ✅ | ✅ |

### 簇 F · 查询/调查层（query 模式）

| 模块 | 公开类/函数 | 职责 | LLM | 成熟度 | 断层 |
|---|---|---|---|---|---|
| `ai/data_query_engine.py` | `DataQueryEngine.run_query`(139) | NL→查数 | ✅ | 🟢(query) | ✅ |
| `ai/investigation_engine.py` | `EngineeringInvestigator.investigate`(160) | 确定性调查 | — | 🟢(query) | ⚠️ 仅支持单比较 |
| `ai/signal_mapper.py` | `resolve_internal_to_can`(267) | CAN↔变量映射 | — | 🟢 | ⚠️ 模糊启发式(429-497) |
| `ai/temporal_analyzer.py` | `TemporalAnalyzer.analyze`(168) | 时序特征 | — | 🟢 | ✅ |
| `ai/tpe.py` | `TemporalPatternEngine.run`(117) | 时序模式门面 | — | 🟢 | ✅ |
| `ai/causal_aligner.py` | `CausalAligner.align`(142) | 模式↔数据对齐 | — | 🟢 | ⚠️ 仅 AND |
| `ai/pattern_extractor.py` | `PatternExtractor.extract_all`(154) | 代码模式 | — | 🟢 | ⚠️ 仅 Hold/Accumulate |

### 簇 G · 并行/实验系统（未接入 orchestrator）

| 模块 | 内容 | LLM | 成熟度 | 断层 |
|---|---|---|---|---|
| `ai/agent_loop.py` | `AgentLoop`(108) 顺序执行器 | — | 🟡 | ⚠️ 无 LLM 规划器，非真 ReAct |
| `ai/agent_tool_registry.py` | `build_agent_tool_registry`(301) | — | 🟡 | ⚠️ 无生产调用方 |
| `ai/tools/base.py` | `BaseTool`(161) | — | 🟡 | ✅ |
| `ai/tools/data_tools.py` | 3 数据工具 | — | 🟡 | ⚠️ 重复 BaseTool/序列化 |
| `ai/tools/code_tools.py` | 3 代码工具 | — | 🟡 | ⚠️ 重复 BaseTool/序列化 |
| `ai/modules/base.py` | `BaseModule/ModuleResult`(85) | — | 🟡 | ✅ |
| `ai/modules/__init__.py` | `MODULE_REGISTRY`(18) 10 项 | — | 🟡 | ⚠️ orchestrator 未用 |
| `ai/modules/agent_loop.py` | `AgentLoopModule` | — | 🟡 | ⚠️ 需手写 tool-call |
| `ai/modules/code_structure.py` | `CodeStructureModule`(M1) | — | 🟡 | ✅ wrapper |
| `ai/modules/signal_bridge.py` | `SignalBridgeModule`(M2) | — | 🟡 | ✅ wrapper |
| `ai/modules/data_diagnostics.py` | `DataDiagnosticsModule`(M4) | — | 🟡 | ✅ wrapper |
| `ai/modules/diagnosis_panel.py` | `DiagnosisPanelModule`(M6) | ✅ | 🟡 | ✅ wrapper 同 ExpertPanel |
| `ai/modules/code_review.py` | `CodeReviewModule`(M7) | — | 🟡 | ✅ wrapper |
| `ai/modules/bsd_data_bridge.py` | `BSDDataBridgeModule`(M9) | — | 🟡 | ✅ |
| `ai/modules/project_init.py` | `ProjectInitModule`(552) | — | 🟡 | ✅ |
| `ai/requirements/*.py` | loader/tracer/reviewer/module | ✅(reviewer) | 🟡 | ⚠️ orchestrator 不用，用 core.materials |
| `harness/*.py` | 5 个评估器 | ✅(judge) | 🟡 | ⚠️ 仅 tools/run_harness_gate.py 用 |

### 簇 H · 孤儿/测试-only

| 模块 | 说明 | 断层 |
|---|---|---|
| `platforms/gen5_selena/*.py` | Gen5 模拟引擎(4文件)，仅测试引用 | ⚠️ 独立并行系统 |
| `plugins/analysis/rule_engine.py` | 规则引擎，仅 test_rule_engine 用 | ⚠️ 死代码 |
| `scripts/*.py` | ~50 个一次性 BSD/MF4 脚本 | ⚠️ 大量临时脚本 |
| `condition_eval/` | 条件求值器（独立包） | ⚠️ 未接入生产 |

---

## 3. 依赖热力图（扇入/扇出）

### 3.1 高扇入节点（被多人依赖 = 稳定基座）

| 模块 | 扇入 | 说明 |
|---|---|---|
| `ai/model_router.py` | 高 | 几乎所有 LLM 模块依赖 |
| `core/models.py` | 中 | gen5/rule_engine 共享 dataclass |
| `ai/utils.py` | 中 | parse_json_from_llm 被广泛引用 |
| `ai/signal_mapper.py` | 中 | tpe/investigation/condition 共用 |
| `core/identity.py` | 中 | config/orchestrator/workspace 共用 |

### 3.2 高扇出节点（依赖多人 = 需更多关注）

| 模块 | 扇出 | 说明 |
|---|---|---|
| `ai/investigation_engine.py` | 高 | 依赖 condition/signal_mapper/variable_chains/CodeGraph/conditions |
| `ai/orchestrator.py` | 高 | 依赖 15+ 模块 |
| `ai/condition_extractor.py` | 高 | 依赖 rule提取+LLM+signal 回填 |

### 3.3 依赖断层（关键发现）

```
                    ┌─────────────────────────────┐
                    │  ai/orchestrator.py (生产心脏) │
                    └──────────────┬──────────────┘
                                   │ 只 import 簇 A
        ┌──────────────────────────┼──────────────────────────┐
        │                          │                          │
   （不 import）              （不 import）              （不 import）
        ▼                          ▼                          ▼
 ai/modules/*            ai/agent_loop.py           ai/investigation_engine.py
 ai/tools/*              ai/agent_tool_registry.py  ai/requirements/*
 harness/*  platforms/*  plugins/*
```

**结论**：本文记录的是早期 orchestrator 与旧模块化设计的差距；当前实现状态请以统一
Pi/Capability 文档和产品化 handoff 为准，不再引用已清理的旧 V3 文件。

---

## 4. 关键结论

1. **生产心脏干净但孤立**：`run_diagnosis` 是成熟、可回归、可复现的 8 步管线，但被大量实验性模块环绕而未被复用。
2. **插件化是「声明未实现」**：`PlatformFamily` 的插件字段（`codegraph_plugin/parser_plugin/symbol_ruleset`）仅存在于 `core/identity.py:51-54`，从未有任何分发代码。
3. **三套并行系统**：诊断管线 / query引擎+investigation / agent+tool 模块 — 各自为政。
4. **孤儿代码占比高**：~50 个 `scripts/*.py` + gen5_selena + rule_engine 为一次性/测试代码，拉低可维护性。

> **下一篇** → `01-surgery-pipelines.md`：三条真实链路逐行拆解 + 插件化断层专题。
