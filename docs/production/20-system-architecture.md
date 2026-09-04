# radarAnalyze 生产级设计体系 · 20 · 系统架构设计

> **版本**: PROD-1.0 · 2026-08-13
> **本篇定位**: 广视野系统架构 —— 逻辑/物理/运行/部署全视图，核心是**插件化横切架构**（5 大 SPI）与多项目隔离沙盒。

---

## 1. 设计目标

| 目标 | 说明 |
|---|---|
| **多代码仓** | 一套系统适配多个客户代码仓（Gen6/Gen5/未来），零改核心 |
| **多数据格式** | .bag/.blf/.mf4 + 未来格式，统一入 FrameStore |
| **多平台适配** | 平台定制（func_keywords/解析规则/符号规则）可插拔 |
| **多项目隔离** | 各 variant 的代码/数据/知识/记忆严格隔离，杜绝串味 |
| **生产可靠** | fail-closed、可观性、优雅降级 |

---

## 2. 逻辑架构（分层全景）

```
┌─────────────────────────────────────────────────────────────────┐
│ 接入层  CLI (cli.py) │ MODULE_REGISTRY │ TOOL_REGISTRY          │
├─────────────────────────────────────────────────────────────────┤
│ 数据解析层  Parser SPI → case_loader → FrameStore(SQLite 5表)   │
│            [.bag/.blf/.mf4 插件] + DbcLoader + TimeSync          │
├─────────────────────────────────────────────────────────────────┤
│ 知识引擎层  CodeGraph(骨骼, tree-sitter+SQLite)                 │
│            + LLI Wiki(血肉, MD) + signal_mapping + conditions    │
├─────────────────────────────────────────────────────────────────┤
│ 诊断推理层  Orchestrator │ ExpertPanel │ EngineeringInvestigator │
│            │ TPE │ CausalAligner │ DataProbe │ ParameterAnalyzer │
├─────────────────────────────────────────────────────────────────┤
│ 记忆层  MemorySystem(L1-L6) + SemanticMemory + freshness guard   │
├─────────────────────────────────────────────────────────────────┤
│ 交付层  Visualizer(Plotly) │ DiagnosisBundle │ 报告落盘          │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. 插件化横切架构（核心）

### 3.1 需要分发的插件字段（修 P0-2 / FR-9）

当前 `PlatformFamily` 声明了但未分发（`core/identity.py:51-54`）。目标态应真正驱动：

| 插件字段 | 驱动对象 | 目标态分发点 |
|---|---|---|
| `codegraph_plugin` | CodeGraph 构建器 | `ai/codegraph/builder.py` |
| `parser_plugin` | 数据解析 | `parsers/case_loader.py` |
| `symbol_ruleset` | 符号提取规则 | `ai/signal_mapper.py` + codegraph |
| `default_pipeline_profile` | 管线配置 | `config.py` |

### 3.2 统一插件注册表模型

```
PluginRegistry (统一注册表)
 ├─ ParserRegistry        key=extension (.bag/.blf/.mf4)
 ├─ PlatformAdapterRegistry  key=platform_id (gen6_c_radar/...)
 │    ├─ CodeLearnerAdapter
 │    ├─ ConditionExtractorAdapter
 │    └─ SignalMapperAdapter
 ├─ CodeGraphBackendRegistry key=backend (sqlite/...)
 └─ MemoryBackendRegistry    key=backend (json/lancedb/...)
```

**发现机制**：装饰器注册 + 自动扫包（`importlib` 遍历 `parsers/plugins/`、`platform_adapters/`），替换现有硬编码导入列表（`factory.py:53-61`）。

### 3.3 关键 SPI 一览（详见 31-software-architecture）

| SPI | 职责 | 现有雏形 |
|---|---|---|
| `ParserPlugin` | 解析指定格式→FrameStore | parsers/*.py |
| `PlatformAdapter` | 平台定制知识 | platform_adapters/* |
| `SignalMapper` | CAN↔变量映射 | signal_mapper.py |
| `CodeGraphBackend` | 图存储/查询 | codegraph/* |
| `MemoryBackend` | 记忆持久化 | memory/* |

---

## 4. 数据流（Req→Code→Data 三角对齐）

```
用户问题 ──┐
          ├─► ReadReq: 需求YAML + 语义记忆 ──► 期望行为
          │                                       │
          ├─► CodeGraphQuery: 信号→函数/变量 ────► 代码条件/参数
          │                                       │
          └─► DataQuery: 变量→CAN→FrameStore ────► 实际取值
                                                       │
              TriageConclusion: 根因 = 数据层断裂的第一环 ◄─┘
```

**可追溯链**：需求 → 代码行 → CAN 信号 → 数据探针。每环可回溯。

---

## 5. 隔离沙盒（多项目隔离）

### 5.1 解析链

```
case 目录 ──(metadata/--variant)──► variant_id
   └─► codebase_id ──► platform_id ──► PlatformAdapter
```

### 5.2 目录隔离

```
.workspaces/<variant>/
  ├─ source_docs/       # 条件/映射/overview
  ├─ memory/codegraph/  # CodeGraph DB
  ├─ memory/snapshots/  # 快照
  ├─ memory/semantic/   # 语义索引
  ├─ memory/            # L1-L6
  ├─ dbc/               # DBC 引用
  └─ requirements/      # 需求 YAML
```

### 5.3 Core/COEM 继承

`core/workspace.py` 递归级联：`get_config/get_source_paths/get_dbc_files/get_requirements_schema` 均 base→local 叠加，local 覆盖。**不变更**现有机制，仅确保插件字段也纳入 variant 解析。

---

## 6. 运行时视图

```
cli.py
 ├─ _run_diagnosis  → Orchestrator.run_diagnosis (8步, LLM+确定性)
 │      └─ [ReAct 自主循环] ReActPlanner(LLM) → AgentLoop → 确定性工具
 ├─ _run_query      → DataQueryEngine.run_query (7步, investigator+LLM)
 ├─ _run_dream      → AutoDream (Phase0-4)
 └─ MODULE_REGISTRY → 10 个子命令 (agent-loop/code-query/...)
```

---

## 7. 部署视图（零后台离线）

```
[Windows 本地]
  radarAnalyze CLI (Python)
     ├─ SQLite (FrameStore + CodeGraph)   ← 已装
     ├─ tree-sitter                       ← 已装
     ├─ ModelRouter → local Ollama / remote Qwen / coder
     └─ [LanceDB 语义记忆]                ← 决策后装
```

无后台服务、纯本地、Windows 友好。

---

## 8. 技术选型矩阵

| 技术 | 状态 | 决策 |
|---|---|---|
| tree-sitter-c + SQLite CodeGraph | ✅ 保留 | 生产 |
| SQLite FrameStore + asteval + TPE | ✅ 保留 | 生产 |
| cantools + JSON 映射 | ✅ 保留 | 生产 |
| ModelRouter 三模型 | ✅ 保留 | 生产 |
| L1-L6 JSON 记忆 | ✅ 保留 | 生产 |
| 5专家×3round + clang | ✅ 保留 | 生产 |
| **LanceDB 语义记忆** | ✅ **已确认启用** | 统一路径 `.workspaces/<variant>/memory/semantic/` |
| Pydantic 需求层 | 🆕 推进 | 修 P1-1 |
| **真 ReAct Agent** | 🆕 **已确认** | 包在固定管线外，行动调确定性工具 |
| KùzuDB / DuckDB / LangGraph | 🔬 门槛触发 | 不主动引入 |

---

## 9. 关键架构决策（ADR 摘要）

| # | 决策 | 理由 |
|---|---|---|
| ADR-1 | 插件化用注册表+自动发现，不用 entry_point | 离线、无包管理依赖 |
| ADR-2 | 确定性取证优先，LLM 只做推理/补查 | 可复现、可回归 |
| ADR-3 | 保持固定 8 步管线为主路径 | 稳定、可测 |
| ADR-4 | 插件字段必须真正分发 | 修 P0-2，实现 FR-9 |
| ADR-5 | 不引入新 DB，除非基准门槛触发 | 最小依赖 |
| ADR-6 | **启用 LanceDB 语义记忆**（2026-08-13 确认） | 语义召回需求明确；统一路径 |
| ADR-7 | **Agent = 真 ReAct 自主循环**，包在固定管线之外（2026-08-13 确认） | 每行动仍调确定性工具，不颠覆取证 |

---

> **下一篇** → `30-scheme-design.md`：方案设计（迁移路线图 + 方案对比）。