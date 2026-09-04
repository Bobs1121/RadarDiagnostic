# radarAnalyze 生产级设计体系 · 31 · 软件架构设计（目标态）

> **版本**: PROD-1.0 · 2026-08-13
> **本篇定位**: 目标态软件架构，最细粒度。定义包结构、插件 SPI 接口、数据结构 schema、错误处理、可观测性、测试策略与命名/分层规范。

---

## 1. 目标态包结构

```
radarAnalyze/
  cli.py                    # 统一入口（诊断/query/dream/模块子命令）
  config.py                 # 配置加载 + project_intake 展开
  core/
    identity.py             # 五层身份（含插件字段，目标态真正分发）
    plugin.py               # ★ 统一 PluginRegistry / 注册/发现机制
    workspace.py            # Core/COEM 隔离
    freshness.py            # 指纹
    knowledge_guard.py      # fail-closed 门
    materials.py            # 材料/需求
    diagnosis_bundle.py     # 结构化产物
  parsers/
    plugins/                # ★ Parser SPI
      base.py               #   ParserPlugin 抽象
      registry.py           #   ParserRegistry
      bag_plugin.py         #   .bag 实现
      blf_plugin.py         #   .blf 实现
      mf4_plugin.py         #   .mf4 实现
    case_loader.py          # 查注册表分发（含旧 glob fallback）
    frame_store.py          # SQLite 5表
    dbc_loader.py
    time_sync.py
  engines/                  # ★ 确定性引擎收纳（from ai/）
    temporal_analyzer.py
    tpe.py
    pattern_extractor.py
    causal_aligner.py
    data_probe.py
    parameter_analyzer.py
    test_window_detector.py
    frame_analyzer.py
  ai/
    orchestrator.py         # 8步管线（复用 engines + investigation）
    investigation_engine.py # 确定性调查（接入诊断）
    code_learner.py
    condition_extractor.py
    signal_mapper.py        # 经 PlatformAdapter 分发
    model_router.py
    context_budget.py
    fallback.py
    observability.py
    visualizer.py
    modules/                # M1-M8 模块（可被 orchestrator 组合）
    tools/                  # Agent 工具（决定去留）
    requirements/           # 需求层
    platform_adapters/      # PlatformAdapter SPI 实现
    codegraph/              # CodeGraph
  memory/
    memory_system.py
    auto_dream.py
    semantic_memory.py
  harness/                  # 回归门
```

---

## 2. 插件 SPI 接口定义

### 2.1 `core/plugin.py` — 统一注册表

```python
class PluginRegistry:
    """统一插件注册表：装饰器注册 + 自动发现。"""
    _registry: dict[str, type] = {}

    @classmethod
    def register(cls, kind: str, key: str):
        def deco(plugin_cls):
            cls._registry[f"{kind}:{key}"] = plugin_cls
            return plugin_cls
        return deco

    @classmethod
    def get(cls, kind: str, key: str) -> type | None:
        return cls._registry.get(f"{kind}:{key}")

    @classmethod
    def discover(cls, package: str):
        """importlib 遍历包内模块，触发装饰器。替换硬编码导入。"""
        import pkgutil, importlib
        for m in pkgutil.iter_modules(importlib.import_module(package).__path__):
            importlib.import_module(f"{package}.{m.name}")
```

### 2.2 `parsers/plugins/base.py` — ParserPlugin SPI

```python
class ParserPlugin(ABC):
    """数据格式解析插件。每个实现对应一种格式。"""
    extension: str            # ".bag" / ".blf" / ".mf4"
    @abstractmethod
    def parse(self, path: Path, store: FrameStore, dbc: DbcLoader | None) -> None:
        """流式解析 path 并写入 store。"""
    @abstractmethod
    def meta(self, path: Path) -> dict:
        """返回格式元数据（源、时间范围等）。"""
```

**注册示例**：
```python
@PluginRegistry.register("parser", ".bag")
class BagParserPlugin(ParserPlugin):
    extension = ".bag"
    def parse(self, path, store, dbc): ...
```

**`case_loader` 分发改造**：
```python
def load_case_data(case_dir, ...):
    for p in case_dir.glob("*"):
        if p.suffix in PARSER_REGISTRY:   # 注册表优先
            plugin = PluginRegistry.get("parser", p.suffix)()
            plugin.parse(p, store, dbc)
        else:                              # 旧 glob fallback
            _legacy_dispatch(p, store, dbc)
```

### 2.3 PlatformAdapter SPI（修分发 key）

`factory.py` 改为经统一注册表按 `platform_id` 分发，orchestrator 用 `self.platform_id`：

```python
@PluginRegistry.register("code_learner", "gen6_c_radar")
class Gen6SymmetryCodeLearner(BaseCodeLearnerAdapter): ...
```

### 2.4 CodeGraphBackend SPI（分发 `codegraph_plugin`）

```python
class CodeGraphBackend(ABC):
    plugin_name: str
    @abstractmethod
    def build(self, source_root, filters) -> Path: ...
    @abstractmethod
    def query(self, db_path, kind, pattern) -> list: ...
```

`codegraph/builder.py` 按 `PlatformFamily.codegraph_plugin` 查注册表。

### 2.5 MemoryBackend SPI（分发语义记忆）

```python
class MemoryBackend(ABC):
    backend_name: str
    @abstractmethod
    def add(self, doc: dict): ...
    @abstractmethod
    def search(self, query: dict, top_k: int) -> list: ...
```

`semantic_memory.py` 按 `variant` 配置选择 `json-fallback` / `lancedb`，统一路径 `.workspaces/<variant>/memory/semantic/`。

### 2.6 目标态类级接口目录（细粒度）

每个核心类给出**公开方法签名 + 职责 + 确定性/LLM**，作为实现验收基准。

#### 2.6.1 身份 / 配置 / 工作区

| 类 | 公开方法 | 职责 | 确定性 |
|---|---|---|---|
| `core.identity.PlatformFamily` | `to_dict/from_dict` | 插件字段宿主 | — |
| `core.identity.Variant` | `to_dict/from_dict` | 项目隔离锚点 | — |
| `core.plugin.PluginRegistry` | `register/get/discover` | 统一插件注册/发现 | — |
| `core.workspace.Workspace` | `get_config/get_source_paths/get_dbc_files/get_requirements_schema/from_variant` | Core/COEM 级联 | — |
| `config.load_config` | `() -> dict` | project_intake 展开 | — |

#### 2.6.2 数据解析（Parser SPI）

| 类 | 公开方法 | 职责 | 确定性 |
|---|---|---|---|
| `parsers.plugins.base.ParserPlugin` | `parse(path, store, dbc)/meta(path)` | 抽象解析 | — |
| `parsers.plugins.bag_plugin` | 实现 `.bag` | ROS 流式 | — |
| `parsers.plugins.blf_plugin` | 实现 `.blf` | CAN 流式 | — |
| `parsers.plugins.mf4_plugin` | 实现 `.mf4` | asammdf 流式 | — |
| `parsers.case_loader.load_case_data` | `(case_dir,...) -> CaseLoadResult` | 查注册表分发 | — |
| `parsers.frame_store.FrameStore` | `insert_*/query_signal_timeline` | SQLite 5表 | — |

#### 2.6.3 确定性引擎（engines/）

| 类 | 公开方法 | 职责 | 确定性 |
|---|---|---|---|
| `engines.tpe.TemporalPatternEngine` | `run(store,func_name,...)` | 时序模式门面 | — |
| `engines.temporal_analyzer.TemporalAnalyzer` | `analyze(store,can_id,field)` | 边/段/统计 | — |
| `engines.causal_aligner.CausalAligner` | `alignCodePattern/alignDataFeature` | 模式↔数据对齐 | — |
| `engines.data_probe.DataProbe` | `query(field,table,filter,stats)` | SQLite 探针 | — |
| `engines.parameter_analyzer` | `scan/analyze_sensitivity/what_if` | 参数灵敏度 | — |
| `engines.test_window_detector` | `detect(store,func_name)` | 规则窗口 | — |
| `engines.frame_analyzer.FrameAnalyzer` | `extract_evidence(store,func_name,windows)` | 帧级证据 | — |

#### 2.6.4 调查/推理层（ai/）

| 类 | 公开方法 | 职责 | 确定性 |
|---|---|---|---|
| `ai.investigation_engine.EngineeringInvestigator` | `investigate(store,question,plan,signal_lookup)` | 确定性调查 | — |
| `ai.signal_mapper` | `resolve_internal_to_can/resolve_can_to_internal` | CAN↔变量 | — |
| `ai.condition_extractor.ConditionExtractor` | `extract(func_name,force)` | AI 条件树 | ✅ |
| `ai.variable_query_planner` | `plan(...)` | AI 规划 probe | ✅ |
| `ai.expert_panel.ExpertPanel` | `run_panel(...)` | 5专家×3轮 | ✅ |
| `ai.model_router.ModelRouter` | `chat/complex` | 三模型选路 | ✅ |
| `ai.context_budget` | `compute_budget` | 动态预算 | — |
| `ai.orchestrator.Orchestrator` | `run_diagnosis` | 8步编排 | 混合 |

#### 2.6.5 Agent（目标态真 ReAct）

| 类 | 公开方法 | 职责 | 确定性 |
|---|---|---|---|
| `ai.agent.ReActPlanner` | `plan(state) -> list[AgentAction]` | LLM 规划子步骤 | ✅ |
| `ai.agent.AgentLoop` | `run(state)` | 顺序执行 + 循环 | — |
| `ai.tools.base.BaseTool` | `execute/safe_execute` | 工具包装 | — |
| `ai.tools.data_tools` | query_can_data/detect_time_pattern/plot_signal | 数据工具 | — |
| `ai.tools.code_tools` | find_code_def/extract_dep/trace_requirement | 代码工具 | — |

#### 2.6.6 记忆层（memory/）

| 类 | 公开方法 | 职责 | 确定性 |
|---|---|---|---|
| `memory.memory_system.MemorySystem` | `build_context_for_diagnosis` | L1-L6 组装 | — |
| `memory.auto_dream.AutoDream` | `try_dream` | Phase0-4 固化 | ✅ |
| `memory.semantic_memory.SemanticMemory` | `add/search` | 向量召回 | — |

#### 2.6.7 粒度数据流（代码↔数据 ↔ 证据）

```
用户问题 ──► Keyboardify/分类 ──► CodeGraphQuery(variable→CAN)
    │                                    │
    └──► DataQuery(store) ──► 时间线 ──► 窗口(Enable>0) ──► 采样
                                           │
        ConditionCheck ◄── 触发判定 ◄── transform(enum/scale)
                                           │
    └──► SignalCodeTrace(证据) ──► Top-3 候选 + source_refs
```

---

## 3. 关键数据结构 Schema

### 3.1 五层身份（复用，插件字段真正生效）

```python
PlatformFamily(platform_id, language, build_system,
               codegraph_plugin, parser_plugin, symbol_ruleset, default_pipeline_profile)
  └─ Codebase(codebase_id, root_path, repo_url, branch, commit, platform_id)
       └─ Variant(variant_id, codebase_id, scope, dbc_files, key_source_files, source_domains)
            └─ PackageProfile(...) └─ Snapshot(...)
```

### 3.2 FrameStore 5 表

| 表 | 内容 | 来源 |
|---|---|---|
| `bag_frames` | 原始 ROS bag 帧 | BagParser |
| `can_frames` | CAN 帧（can_id/message/signals_json） | BLF+MF4 |
| `radar_objects` | 每对象每帧，8 ADAS 警告标志 | BagParser 深解析 |
| `radar_debug` | 每帧 ego/ADAS-enable/BLD 快照 | BagParser |
| `warning_events` | 派生的边沿事件 | `_build_warning_events` |

### 3.3 InvestigationResult

```python
InvestigationResult:
  plan: InvestigationPlan
  analysis_windows: list
  code_facts: list[CodeFact]
  data_facts: list[DataFact]
  condition_checks: list[ConditionCheck]
  limitations: list[str]
  diagnostic_posture: {ai_reasoning_required: True,
                       deterministic_checks_are_advisory: True}
```

### 3.4 ConditionCheck

```python
ConditionCheck:
  expression / code_ref / variables / signals
  observation / result("satisfied"|"violated"|"mixed"|"unknown") / evidence_refs
```

### 3.5 SignalCodeTrace（双向追溯）

```python
SignalCodeTrace:
  case_id / variant_id
  data_signal: {message, signal, time_window, value}
  observation: {...}           # unknown 时含 unknown_reason/required_signal
  code_variable / code_logic: {condition, parameter, function, call_chain}
  source_refs / evidence_status("observed"|"inferred"|"unknown")
```

### 3.6 knowledge_manifest.json

```json
{ "scopes": {
    "conditions:RCTA": {"input_signature": "sha256:...", "published_at": "..."},
    "source_docs:RCTA": {"input_signature": "...", "published_at": "..."}
  }
}
```

---

## 4. 错误处理与 fail-closed 策略

| 层 | 策略 |
|---|---|
| LLM 调用 | `safe_llm_call` + 显式 fallback |
| 确定性引擎 | 优雅降级，**但静默失败必须 logging.error + observability 事件** |
| freshness 门 | fail-closed：缺失/过期/签名不匹配 → 禁止进 prompt |
| 插件缺失 | 显式告警 + 明确 degraded 状态，不静默 |
| 数据不足 | 输出 unknown + 补采建议，不强制结论 |

**原则**：杜绝「被 try/except 吞掉的静默失败」（修 P0-1 后），所有 `except Exception: pass` 改为记录结构化事件。

---

## 5. 可观测性

- `StepLogger`：每诊断步骤开始/结束/耗时。
- `TokenTracker`：累计 token 消耗，按调用点归类。
- `ObservabilityEvent`：结构化事件（含 error/warning/degraded 级别）。
- 诊断结束产出 `observability.json`，供审计与 KPI 度量。

---

## 6. 测试策略

| 层 | 覆盖 | 工具 |
|---|---|---|
| 单元 | 各引擎纯函数 | pytest |
| 插件 | 各 SPI 实现 + 注册 | pytest |
| 集成 | 诊断/query 管线 | pytest + 真实 case |
| 回归门 | 真实案例 Top-3 / 证据 | `tools/run_harness_gate.py` |

**P0-1 修复必配测试**：断言 `platform_id` 与 `codegraph_db_path` 独立、代码修复不再为空。

---

## 7. 命名/分层规范

- **确定性引擎**统一入 `engines/`，无 LLM，纯函数式 → 易测易复用。
- **插件**统一 `PluginRegistry` 注册，公共接口放 `core/plugin.py`。
- **LLM 调用**只允许在 `ai/` 推理层，引擎层不感知 LLM。
- **配置驱动**：新插件/新格式/新平台通过 config + 注册即可，零改核心。

---

## 8. 与缺陷的对应关系

| 目标态设计 | 解决的缺陷 |
|---|---|
| 独立 `codegraph_db_path` property | P0-1 |
| 统一注册表 + 正确分发 key | P0-2 |
| 三套系统收敛 | P1-1 |
| 单一 L6 writer | P1-2 |
| freshness 门控扩展 L1-L5 | P1-3 |
| MemoryBackend SPI + 统一路径 | P1-4 |
| 信号映射置信度 | P1-5 |
| AGENTS.md 同步 + 清理 | P2-x |

---

## 9. 结语

本设计把「现状拆解 → 插件化目标态」打通：**代码↔数据对应、多格式/多平台/多项目插件化管理**成为一等公民，并与现有成熟确定性引擎无缝衔接。实现路径见 `30-scheme-design.md`。

---

## 附 · 文档导航

| # | 文档 | 内容 |
|---|---|---|
| 00 | surgery-module-map | 模块图谱 + 依赖热力图 |
| 01 | surgery-pipelines | 三条链路 + 插件断层 |
| 02 | surgery-defects | 缺陷清单与根因 |
| 10 | prd | 生产级产品需求 |
| 20 | system-architecture | 系统架构（广视野） |
| 30 | scheme-design | 迁移路线图 + 方案对比 |
| 31 | software-architecture | 软件架构（目标态，最细） |