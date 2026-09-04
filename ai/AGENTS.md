# ai/ 模块实现说明

> 用于「需求 ↔ 实现」review。AI 编辑 ai/ 目录文件时参考本文档。

> **Stage 3 迁移说明**：确定性引擎已从 `ai/` 移入 `engines/`（无 LLM 依赖，可独立测试）。下文 `## engines/xxx.py` 章节描述 `engines/` 包内的模块；`ai/` 通过 PEP 562 惰性 `__getattr__` 向后兼容 `from ai import signal_mapper` 等。引擎禁止 import `ai.orchestrator`。详见 `engines/__init__.py` 与根 `AGENTS.md`。

---

## 模块概览

| 文件 | 定位 | AI 调用 |
|------|------|---------|
| `orchestrator.py` | 诊断管线总编排 (8 步)，含 IdentityContext / 材料摘要注入 | complex × 1, chat × 2 |
| `engines/frame_analyzer.py` | 帧级证据提取 (状态跳变/警告时间线/目标速度) | 无 |
| `engines/test_window_detector.py` | 纯规则窗口检测 | 无 |
| `engines/temporal_analyzer.py` | 信号时间线 → 边/段/统计/模式标签 | 无 |
| `engines/parameter_analyzer.py` | 阈值扫描 + 敏感性 + what-if | 无 |
| `engines/data_probe.py` | FrameStore SQLite 探针 (asteval + numpy) | 无 |
| `agent_loop.py` | PR5 最小离线 Agent/ReAct 执行核心：顺序执行 plan、复用 `BaseTool.safe_execute`、支持 `ask_human` 边界 | 无 |
| `agent/` (react_planner.py) | **Stage 5 真 ReAct Agent**：`ReActPlanner` 用 ModelRouter 将 objective 分解为 `AgentToolCall` 子步骤，`AgentLoop` 确定性执行；`run_react()` 便捷入口 | ✅ LLM 规划 |
| `modules/react_agent.py` | **Stage 5** `ReActModule`（`agent-repl` CLI 子命令）：包装 `ReActPlanner`，支持 `--objective`/`--context`/`--tool-call`(确定性 fallback)/`--no-llm` | 可选 LLM |
| `agent_tool_registry.py` | PR6 workspace-aware tool registry builder：从 config/workspace/case 上下文解析真实 deterministic tool instances | 无 |
| `capability/module_bridge.py` | V4：把 `BaseModule` 能力转换成受控 `BaseTool`，默认自动发现全部已注册叶子能力；排除 `pi`/`agent-repl`/`agent-loop` 防递归 | 无 |
| `modules/agent_loop.py` | V3 standalone wrapper：把离线 AgentLoop 暴露为 `agent-loop` CLI 子命令，支持注入 tool registry，并被 `tools/run_agent_loop_smoke.py` 用真实 tool instance 做离线冒烟 | 无 |
| `modules/project_init.py` | PR6-F 最小输入项目接入：生成 `config.local.yaml` 与 `.workspaces/<variant>/` 隔离沙盒，推断 build/关键源码/variant 路径 | 无 |
| `modules/cr60_intake.py` | V4 CR60 材料优先数据/软件/车型/COEM/分支绑定 | 无 |
| `modules/cr60_precheck.py` | V4 CR60 通过窄 provider 调用 sibling harness 的 Sprint1 预检查 | 无 |
| `modules/public_topic_plan.py` / `public_evidence_audit.py` | V4 CR60 无 GDB 公共逐帧证据规划/审计 | 无 |
| `modules/code_gdb_plan.py` | V4 CR60 从当前 code index 生成 source-bound GDB 指令，不内置功能断点 | 无 |
| `modules/gdb_service.py` | V4 CR60 通用 headless GDB 服务，审批后才执行命令 | 无 |
| `modules/ros_topic_inventory.py` | V4 CR60 只读 ROS topic/type/publisher/subscriber 盘点 | 无 |
| `tools/data_tools.py` | Agent-callable 数据工具包装：DataProbe 查询 / TPE / 延迟绘图意图 | 无 |
| `problem_classifier.py` | 任务分类: diagnose/tune/verify/query | simple × 1 |
| `engines/signal_mapper.py` | CAN ↔ 内部变量映射 (纯正则) | 无 |
| `tools/__init__.py` | PR3 工具包入口与 `TOOL_REGISTRY`，按工具 `name` 暴露 Agent-callable 工具类 | 无 |
| `tools/base.py` | Agent 可调用工具基础契约：参数 schema + JSON 结果包装 | 无 |
| `tools/code_tools.py` | PR3 Agent 工具包装：CodeGraph 定义/依赖查询 + Requirement trace，支持 fake backend 注入 | 无 |
| `modules/signal_bridge.py` | M2 standalone bridge：CAN ↔ 内部变量/输出信号解析封装 | 无 |
| `condition_extractor.py` | AI 提取条件树 + 确定性后处理 | complex × 1 |
| `engines/causal_aligner.py` | 代码模式 ↔ 数据时序对齐 (纯规则) | 无 |
| `variable_query_planner.py` | AI 规划 DataProbe 查询 | chat(complex) × 1 |
| `expert_panel.py` | 多专家 3 轮研讨 | complex × 多次 |
| `data_query_engine.py` | 自然语言查数 (query 模式) | complex × 2 |
| `investigation_engine.py` | Query 模式确定性工程调查层：代码条件 ↔ 实测数据 ↔ ConditionCheck | 无 |
| `code_learner.py` | 源码增量学习 → L6 JSON | complex × 多次 |
| `modules/diagnosis_panel.py` | M6 独立诊断包装：先分类，再按可用性调用专家面板 | simple × 1 + 可选 complex × 多次 |
| `modules/code_review.py` | M7 离线 code review 骨架：diff/file 安全启发式 + 可选语法检查 hook | 无 |
| `engines/tpe.py` | 时序模式引擎门面 | 无 |
| `engines/pattern_extractor.py` | C 源码行为模式提取 (纯正则) | 无 |
| `visualizer.py` | Plotly HTML 报告生成 | 无 |
| `requirements/` | M3 结构化需求加载 + traceability；M8 review | 可选 complex × 1 |
| `model_router.py` | local/remote 模型选路 | — |
| `context_budget.py` | 字符级 prompt 预算管理 | — |
| `utils.py` | parse_json_from_llm, get_func_fields, ALL_FUNCTIONS 等 | — |

### Freshness Guard

- `DataQueryEngine` 在构造 AI context 前分别校验 source docs、功能条件、DBC knowledge 和 L6；stale 内容只报告被排除原因，不读取正文
- `EngineeringInvestigator` 独立校验 `conditions:<FUNC>`、`variable_chains`、`codegraph`；确定性 signal mapping 可按源码 hash 重建后使用
- Diagnosis 刷新成功后按 scope 发布 `source_docs:<FUNC>`、`conditions:<FUNC>` 和 `codegraph`；条件在检测到代码/常量/identity 漂移时强制重建，禁止 mtime 缓存误命中

---

## orchestrator.py — 诊断编排器

### 公开接口

```
class Orchestrator:
    def __init__(self, config: dict, project_root: Path)
    def run_diagnosis(self, case_dir, problem, expected,
                      on_status=None) -> str
```

成员: `self.config`, `self.project_root`, `self.identity` (`IdentityContext`), `self.router` (ModelRouter), `self.memory`, `self._last_tpe_result`。

`IdentityContext` 由 `_resolve_identity_context(config, project_root)` 生成，集中保存 `variant_id`、`project_key`、`package_profile_id`、`snapshot_id`、`source_docs_dir`、`memory_dir` 等元数据。它不迁移目录，只统一 Orchestrator 内部读取方式；legacy `project_key` 仍兼容。

### run_diagnosis 管线步骤

| Step | status key | 动作 | 输出 |
|------|-----------|------|------|
| 1 | `init` | `_ensure_source_docs` + CodeGraph/source docs | source_docs / codegraph |
| 2 | `classify` | `_understand_problem` + ProblemClassifier | `func_info`, `classification` |
| 3 | `extract` | `case_loader.load_case_data` + TestWindowDetector | store, meta, windows |
| 4 | `evidence` | FrameAnalyzer + conditions + TPE + probe | evidence, conditions, TPE/probe sections |
| 5 | `signals` | suppression/output signals + params for tune/verify | signal sections, param report |
| 6 | `diagnose` | ContextBudget + ExpertPanel | panel_result dict |
| 7 | `fix` | CodeFixEngine best-effort diff suggestion | fix_report_md |
| 8 | `deliver` | report + visualize + memory + DiagnosisBundle | report.md, report.html, bundle |

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

### ContextBudget 配置 (orchestrator ~571)

`total_chars` 由 `compute_budget()` 动态计算（base 40K + CG 节点 + 窗口数 + 时长，上限 model_context * 0.5 * 0.8，硬底 30K/硬顶 120K）。

各块按 priority/min_chars 裁剪:
- methodology, key_facts: priority=100
- tpe: priority=95, constants: priority=94, probe: priority=93, suppression: priority=92
- output, windows: priority=90, transitions: priority=85, conditions: priority=80
- threshold: priority=75, materials: priority=74, codegraph: priority=72, semantics: priority=73
- params: priority=70, timeline: priority=60, frame_anal: priority=55, evidence: priority=55, data_summary: priority=40

### 材料摘要注入

`core.materials.render_material_summary(project_root, variant_id, ...)` 生成确定性、限长的材料/结构化需求摘要。空 registry 只返回计数，`prompt_text=""`，不会污染专家 prompt；存在材料或需求时以 `materials` 块加入 ContextBudget，并记录 memory step `materials`。

### 报告落盘规范化

`_save_report()` 在写入 `report.md` 前会调用私有辅助 `_normalize_report_section_headings(text)`：把专家面板输出里常见的整行 `**根因**` / `**条件检查汇总**` / `**置信度: 92/100**` 等粗体章节标签提升为 `###` 标题，便于 harness `StructuralEvaluator` 识别；段落内联粗体（如 `1. **信号**: ...`）保持不变。

### Review 关注点

1. `func_name` 双源融合: _understand_problem + ProblemClassifier，需保持 override 逻辑可解释
2. `IdentityContext` 是内部薄层，不应顺手迁移 `memory/` 或 `source_docs/` 目录结构
3. 材料摘要必须限长、确定性、无 LLM 依赖；空 registry 不应进入专家 prompt
4. `_update_memories` / deliver 后处理是 best-effort，不得中断主诊断

---

## engines/frame_analyzer.py — 帧级证据提取 (Stage 3 迁移自 ai/)

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

## engines/test_window_detector.py — 纯规则窗口检测

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

## engines/signal_mapper.py — CAN ↔ 内部变量映射

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

## engines/causal_aligner.py — 代码模式 ↔ 数据时序对齐

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
| `ExpertPanel.__init__(self, router, config, project_root)` | 385 | 从 config 提取 project_key 用于 prompt 多项目适配 |
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

### langgraph 依赖

- ExpertPanel 基于 LangGraph StateGraph 构建，需安装 `langgraph`
- 未安装时 `__init__` 抛出 ImportError（含安装指引），诊断降级为 procedural panel
- prompt 外部化：通过 `prompts/expert_panel/loader.py` 加载，支持项目级覆写（`experts/<project_key>/`）

### prompt 多项目适配

- `load_expert_system(expert_id, project_key)` 先查 `prompts/expert_panel/experts/<project_key>/<id>.md`，不存在回退默认
- `ExpertPanel` 从 `config.get("project_key")` 或 `config["identity"]["project_key"]` 提取 project_key
- 项目覆写目录：sc6h/ gwm_b26/ cr5cb/

---

## data_query_engine.py

### 公开接口

| 签名 | 行号 |
|------|------|
| `DataQueryEngine.__init__(self, router, config, project_root)` | 105 |
| `DataQueryEngine.run_query(case_dir, question, on_status=None) -> str` | 122-127 |

流程: parse → inventory → plan (AI) → validate → extract → investigate (确定性) → answer (AI) → 返回 Markdown

**仅使用** `router.complex` 两次，`data_text` 截断 12000 字符。第一次规划 JSON 在原有
`can_signals` / `bag_fields` 基础上增加 `functions` / `code_symbols` /
`need_code_analysis`；即使模型漏填，问题文本中的 ADAS 功能名也会确定性补入。

`run_query()` 使用 `try/finally` 关闭 FrameStore。最终回答 prompt 同时接收传统
`data_text` 和 `InvestigationResult.to_prompt_text()`；`condition_checks.result=unknown`
只表示未观测、未映射或表达式暂不支持，prompt 明确禁止把 unknown 写成条件不满足。

---

## investigation_engine.py

### 公开接口

| 签名/类型 | 职责 |
|-----------|------|
| `EngineeringInvestigator(config, project_root, max_conditions=15, codegraph_factory=None)` | 构建有限、确定性的代码-数据联合证据 |
| `investigate(store, question, plan, signal_lookup) -> InvestigationResult` | 加载当前 variant 条件/映射/CodeGraph 并执行条件检查 |
| `InvestigationResult.to_prompt_text(max_chars=10000) -> str` | 输出有效、限长的 JSON 证据块 |
| `InvestigationPlan` | 功能、代码符号、CAN 信号、问题类型和是否查代码 |
| `CodeFact` | 条件源码引用、所在函数、有限 callers/callees |
| `DataFact` | 信号/字段的样本数、范围、时段和有限离散值 |
| `ConditionCheck` | `expression/code_ref/variables/signals/observation/result/evidence_refs` |

### 证据规则

- 静态知识只从 `resolve_source_docs_dir()` 命中的当前 variant workspace 读取：
  `{FUNC}_conditions.json`、可选 `signal_mapping.json` / `variable_chains.json`
- `signal_mapping.json` 缺失或为空时，调查层从内部项目配置的 `source_domains.signal_chain`
  自动生成；`extract_signal_mapping()` 会同时解析配置的 `RteComMapping.c` 和同目录
  `RteComMapping_Rx*.c`，联合文件哈希任一变化都会使缓存失效，不增加用户配置项
- 条件按问题、代码符号和已选信号相关度排序，默认最多 15 条，避免把完整条件库塞入 prompt
- 规划信号中存在 `Enable` / `Switch` / `Swt` 时，Harness 从其 `value > 0` 连续区间生成
  `analysis_windows`；候选按当前功能名、`primary` role 和 Enable 名称排序，非数值采样不关闭窗口。
  条件数据只在有效窗口内聚合；异步状态信号窗口内无采样时回填窗口开始前最后有效值并记录
  `carry_forward_count`，无可靠窗口时保留全量数据并显式不标 windowed
- 映射优先级：条件显式 `can_signal` → `resolve_internal_to_can()` →
  `radar_debug` 表中真实存在且同名的字段；不做语义猜测
- 只计算单一数值比较 `== != < <= > >=`；复合/符号表达式保持 `unknown`
- 聚合全部原始数值样本：全部通过=`satisfied`、全部失败=`violated`、同时出现=`mixed`、
  无可靠样本/映射=`unknown`
- `passthrough` / `1:1` 映射可直接用原始 CAN 值比较内部代码阈值；紧邻 ReadSignal 的
  简单 `switch(temp)` 单字段枚举会固化为 `enum_map` 并先转换后判断；布尔、缩放和其他
  复杂转换标记为 `transformed_signal_mapping` 并保持 `unknown`，避免单位或枚举误判
- 枚举表未覆盖全部观测值且无 `default` 时标记 `partial_enum_mapping`，即使已覆盖子集全部
  通过也只能返回 `unknown`，不得以部分样本得出满足结论
- CodeGraph 缺失或源码行无法定位仅写入 `limitations`，不阻断数据查询；打开的 CodeGraph
  必须在 `finally` 中关闭
- `check_summary` 汇总四种结果；仅存在 `unknown` 时
  `deterministic_conclusion_available=false`。该字段只是证据强度标记：AI 仍应继续诊断、输出
  最可能候选和置信度，但必须区分推断与已证实事实
- `diagnostic_posture` 明确 Harness 只做筛选、预处理和证据组织；`CodeFact.snippet`、
  `mapping_evidence`、原始/转换后值域和调用关系一起交给 AI，确定性检查不得充当诊断硬门槛

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

## engines/tpe.py — 时序模式引擎门面

### 公开接口

| 签名 | 行号 |
|------|------|
| `TPEResult` dataclass | 38-89 |
| `TemporalPatternEngine.__init__(self, source_root, cache_dir=None, signal_mapping=None, variable_chains=None)` | 95-113 |
| `TemporalPatternEngine.run(store, func_name=None, extra_patterns=None, state_transitions=None, time_window=None) -> TPEResult` | 117-183 |

**不调用 LLM**。组装 PatternExtractor + TemporalAnalyzer + CausalAligner。

流程: extract_all → func 过滤 → 变量解析 → load_can_signal → temporal analyze → causal align

---

## engines/pattern_extractor.py — C 源码行为模式提取

### 公开接口

| 签名 | 行号 |
|------|------|
| `PatternExtractor.__init__(self, source_root, cache_dir=None, target_files=None)` | 144-152 |
| `PatternExtractor.extract_all(use_cache=True) -> list[CodePattern]` | 154-174 |
| `load_patterns(cache_dir) -> list[CodePattern]` | 484-493 |

**不调用 AI**。仅实现 HoldRelease + Accumulate 两种模式检测。缓存: `code_patterns.json` (源码 hash)。

---

## engines/temporal_analyzer.py — 信号时间线 → 边/段/统计

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

## engines/parameter_analyzer.py — 阈值扫描 + 敏感性 + what-if

### 公开接口

| 签名 | 行号 |
|------|------|
| `scan_parameters(source_root, cache_dir=None, force=False) -> ParameterScanResult` | 277-392 |
| `analyze_sensitivity(source_root, cache_dir, store, func_name, focus_categories=None) -> SensitivityReport` | 555-622 |
| `what_if(sensitivity, proposals, store=None) -> list[WhatIfEntry]` | 644-685 |

**不调用 AI**。扫描 `adasFunc.c/h` + `paraDefine.h`，缓存 `parameters.json` (SHA1)。

SPEED 用 `car_spd * 3.6` 得 km/h 与代码阈值对齐。

---

## engines/data_probe.py — FrameStore SQLite 探针

### 公开接口

| 签名 | 行号 |
|------|------|
| `DataProbe.__init__(self, store, windows=None)` | 235-245 |
| `DataProbe.query(field, table="radar_objects", group_by=None, filter=None, stats=None, max_rows=500_000) -> dict` | 276-443 |

**不调用 AI**。仅支持 3 个表: `radar_objects`, `radar_debug`, `warning_events`。

语义字段: `side` (由 dist_y 正负), `in_window` (时间戳在窗口内)。

---

## agent_loop.py

### 公开接口

| 签名/类 | 职责 |
|---------|------|
| `AgentToolCall(tool_name, params={})` | JSON 可序列化的计划工具调用 |
| `AgentStep(index, tool_name, params, step_status, result, resolved_params)` | 单步执行结果快照；保留原始 plan 参数和 artifact 引用解析后的 typed 参数 |
| `AgentState(plan, status='pending', ...)` | 完整执行态：`steps` / `next_step_index` / `last_result` / `artifacts` / `pending_input` |
| `AgentLoop(tool_registry, ask_human_tool_name='ask_human')` | 离线顺序执行器 |
| `AgentLoop.run(plan) -> AgentState` | 按既定 plan 依次执行，**不调用 LLM** |

### 运行约定

- `tool_registry` 可传 `dict[str, BaseTool | type[BaseTool]]`，类会按需无参实例化。
- 普通工具调用统一走 `BaseTool.safe_execute()`；未知工具、非法 registry entry、初始化失败都会折叠为结构化 `status='error'` step，而不是抛异常。
- 工具间 typed 传递使用 `{"$ref":"steps[N].result.data.field"}`；执行前由 `resolve_agent_references()` 解析，缺失/越界引用直接进入 error，不做字符串插值或自然语言猜测。
- 特殊计划动作 `ask_human` 不读取 stdin；它写入 `pending_input`，把 state 标记为 `status='input_required'`，并在该步后停止，等待外层驱动恢复。
- 默认在首个 `error` 或 `input_required` 停止；全部成功时 `state.status='completed'`。不接入 legacy diagnosis pipeline，供离线/模块化 Agent 包装复用。
- `tools/run_agent_loop_smoke.py` 提供 PR5 的确定性真实工具冒烟：注入内存 `FrameStore`、`StructuredRequirementSet`、假 `CodeGraph`，串起 `trace-requirement` → `find-code-definition` → `query_can_data` → `plot_signal`，且不读取真实 bag/blf、不调用 LLM。

---

## agent_tool_registry.py

`AgentToolContext` 封装 `project_root/config/workspace/store/codegraph/...` 等可选上下文；`resolve_agent_tool_context(...)` 会确定性解析 `codegraph_db_path`、`requirement_dir`、`source_root`、`cache_dir`，并在需求目录存在时用 `RequirementLoader.load_yaml_dir()` 预载 `req_set`。`build_agent_tool_registry(context)` 只在上下文足够时注册对应真实工具：数据侧 `query_can_data` / `plot_signal` / `detect_time_pattern`，代码侧 `find-code-definition` / `extract-ast-dependency` / `trace-requirement`。缺少可选资产时应静默省略，而不是抛异常或触发 LLM。`capability.module_bridge.build_module_tool_registry()` 另外把所有已注册、非递归 `BaseModule` 自动适配为 AgentLoop/ReAct 的 `BaseTool`；新模块注册后无需再修改桥。默认只允许生成计划，`cr60-precheck`/`gdb-service` 的 `execute=true` 以及 `project-init` 的写操作必须由审批后的 supervisor 以 `allow_execution=True` 构造桥。

---

## tools/data_tools.py

`QueryCanDataTool.execute(params)` 包装 `DataProbe.query`；`DetectTimePatternTool.execute(params)` 包装 `TemporalPatternEngine.run`；`PlotSignalTool.execute(params)` 返回安全的绘图意图/预览结构。工具输出必须保持 JSON 可序列化，并通过 `safe_execute()` 将异常折叠为 `{status: "error"}`。

---

## tools/__init__.py — PR3 tool registry

`TOOL_REGISTRY` 以工具 `name` 为 key，注册 `QueryCanDataTool`、
`DetectTimePatternTool`、`PlotSignalTool`、`FindCodeDefinitionTool`、
`ExtractASTDependencyTool`、`TraceRequirementTool`。各工具组导入使用
guarded import，单个可选依赖失败不应破坏 `BaseTool` 或其他工具导出。

---

## modules/agent_loop.py — V3 standalone agent-loop

`AgentLoopModule(name="agent-loop")` 是 `ai.agent_loop.AgentLoop` 的薄包装，
默认运行时使用 `ai.tools.TOOL_REGISTRY` 加上 `capability.module_bridge` 暴露的
统一 CR60 模块工具，也允许测试注入 fake registry。

### 公开接口

| 签名 | 说明 |
|------|------|
| `AgentLoopModule(tool_registry=None, ask_human_tool_name="ask_human")` | 默认绑定真实 deterministic tools；测试可注入假的 registry |
| `run(objective="", tool_calls=None, **kwargs) -> ModuleResult` | `tool_calls` 接收 dict 或 JSON string 列表，返回 `objective` + `state.to_dict()` |
| `register_cli(...)` | 注册 `--objective TEXT` 与可重复的 `--tool-call JSON` |

### 状态约定

- `state.status in {"completed", "input_required"}` → `ModuleResult.ok=True`
- `state.status == "error"` 或 `--tool-call` JSON 解析失败 → `ModuleResult.ok=False`
- CLI 示例：`python cli.py agent-loop --objective "preview warn" --tool-call "{\"tool\":\"plot_signal\",\"params\":{\"message_name\":\"ADASWarnMsg\",\"signal_name\":\"WarnCAN\"}}"`
- PR5 真实冒烟证据：`tests/test_agent_loop_smoke.py` 通过 `tools/run_agent_loop_smoke.py` 复用真实 `TraceRequirementTool`、`FindCodeDefinitionTool`、`QueryCanDataTool`、`PlotSignalTool`，断言 `ModuleResult.ok=True` 且 `state.status="completed"`。

---

## agent/ — 真 ReAct Agent（Stage 5）

`ai/agent/react_planner.py` 提供真正的 ReAct 循环：**LLM 规划子步骤，确定性工具执行**。

### 公开接口

| 类/函数 | 职责 |
|---|---|
| `ReActPlanner(router, tool_registry, max_steps=8, max_rounds=3)` | LLM 规划 + AgentLoop 执行 + 观察后重规划 |
| `ReActPlanner.run(objective, context, fallback_plan=None) -> ReActTrace` | 执行 ReAct 循环 |
| `run_react(router, registry, objective, ...)` | 便捷入口 |
| `ReActTrace` / `ReActStep` | 可序列化轨迹快照 |

### 运行约定

- 每轮：LLM 返回 `{"reasoning", "steps": [{tool, params}], "done", "answer"}` JSON → 转 `AgentToolCall` → `AgentLoop` 执行 → 结果回填 trace → 若 `done` 则终止。
- `fallback_plan`（`{"tool":..., "params":...}` 列表）提供**确定性降级**：LLM 不可用时仍可执行。
- `input_required`（`ask_human`）在工具层触发，trace 置 `input_required`。
- **包在固定 8 步诊断管线之外**（ADR-7），每个行动仍调确定性工具，不颠覆取证。

### modules/react_agent.py — ReActModule（CLI）

`ReActModule(name="agent-repl")` 注册于 `MODULE_REGISTRY`，CLI：

```bash
# 确定性 fallback（无 LLM）
python cli.py agent-repl --objective "..." --no-llm --tool-call '{"tool":"query_can_data","params":{...}}'
# LLM 规划
python cli.py agent-repl --objective "检查 FCTA 为何未触发" --context "case: xxx"
```

测试：`tests/test_react_agent.py`（fake router + 真实 tool registry，无 live LLM）。

---

## modules/project_init.py — PR6-F minimal onboarding

`ProjectInitModule(name="project-init")` 接收 `--name`、`--code-root`、可重复 `--dbc`，以及可选的 `--customer` / `--vehicle-project` / `--coem-project` / 可重复 `--requirements` / `--expected-branch`，推断 `variant_id` / `codebase_id` / `build_entry` / `scope` / `key_source_files` / `source_domains`，并生成仅写本地 `config.local.yaml` 的 overlay。

### 关键约定

- CR60 Light 优先路径以 `code_root/coem/<customer_project>` 作为单一客户代码集；**不**单独拆 SIT/FCT 维度，也不新增 package-profile 选项
- 默认 `codebase_id = <repo-root>`（下划线规范化），`variant_id = gen6/<customer>_<vehicle>`；缺省时也可退回 `coem/<dir>` 推导
- `variants.<variant_id>` 额外写入 `customer`、`vehicle_project`、`coem_project_dir`、`requirement_overlays`、`knowledge_policy`
- `variants.<variant_id>.source_context` 写入 `source_root`、`code_branch` 以及 `workspace_dir/source_docs_dir/memory_dir/codegraph_db_path/snapshots_dir/semantic_index_dir`
- DBC 与 requirements 默认保留绝对源路径，并在 `workspace/dbc/sources.yaml`、`workspace/requirements/sources.yaml`、`workspace/manifest.yaml` 记录 provenance/hash；**不复制** 源文件
- 非 `--dry-run` 时创建 workspace 子目录：`source_docs/`, `memory/codegraph/`, `memory/snapshots/`, `memory/semantic/`, `dbc/`, `requirements/`

### Review 关注点

1. 只更新当前 `codebases.<id>` / `variants.<id>` / `package_profiles.<id>`，不得覆盖其他本地项目条目
2. Knowledge isolation 以 `variant_id` 为边界；新 onboarding 的默认缓存路径必须落在 `.workspaces/<variant>/`
3. `project-init` 只读目标源码 repo 的 git 状态，禁止 checkout/fetch/pull；`expected_branch/current_branch/current_commit` 仅作校验元数据

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

## requirements/ — M3 需求层切片

### 公开接口

| 文件 | 签名/类 | 职责 |
|------|---------|------|
| `requirements.loader` | `RequirementLoader.load_yaml_dir(req_dir, variant_id="") -> StructuredRequirementSet` | 加载 `*.yaml` / `*.yml`，支持单条、列表和 `requirements:` wrapper |
| `requirements.loader` | `RequirementLoader.validate_structure(raw) -> list[str]` | 校验 `req_id`、条件列表、`signal_alias`、operator、value |
| `requirements.tracer` | `RequirementTracer.trace(spec) -> dict` / `trace_set(req_set) -> list[dict]` | 基于 CodeGraph + signal_mapping 输出 req→signal→function/file trace |
| `requirements.reviewer` | `RequirementReviewer.review(req_set) -> dict` | 输出 `{summary, issues}`，含 completeness、schema-validation、duplicate、contradiction、testability、dbc-observability |
| `requirements.module` | `RequirementModule.safe_run(req_dir=..., mode="trace|review|all")` | BaseModule 包装，离线可运行 |

### 数据结构约定

Loader 不丢弃结构异常的 YAML 记录；它将 `validate_structure()` 结果写入 `RequirementSpec.metadata["schema_problems"]`，由 reviewer 结构化输出为 `category="schema-validation"` 的 issue。这样坏需求仍可进入 trace/review 报告，但不会被静默当成有效需求。

---

## tools/base.py — Agent tool foundation

`BaseTool.execute(params: dict) -> dict` 是 Agent 工具的基础契约；`safe_execute(params)` 永不抛异常，统一返回 JSON 可序列化 envelope：`{status, message, data, artifacts}`。当前只做轻量 schema 检查：`params` 必须是 dict，`parameters_schema` 必须是 JSON-schema-like object，并校验 `required` / 基础 `type` / `additionalProperties=False`。结果中的 dataclass、`Path`、容器和简单对象会被递归序列化。

---

## tools/code_tools.py — PR3 code/trace wrappers

`FindCodeDefinitionTool`、`ExtractASTDependencyTool`、`TraceRequirementTool`
为 Agent 提供稳定 JSON 边界。输入优先走可注入 `codegraph` /
`CodeStructureModule` / `SignalBridgeModule` / `RequirementTracer`；缺失
CodeGraph 或请求项时要返回结构化 `status="error"`，而不是抛异常。

---

## modules/diagnosis_panel.py — M6 诊断面板切片

`DiagnosisPanelModule.safe_run(problem, expected="", mode="classify|panel|auto", ...)`
总是返回 `classification`；只有在 panel 实际运行成功时才填充
`panel_result`。当 LangGraph/Router/Panel 依赖不可用时，模块退化为
classification-only 成功结果，并通过 `panel_status` / `panel_error`
显式暴露降级原因。

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

`compute_budget()` — 动态计算总预算字符数。因子：base 40K + 5K/500 CG 节点 + 2K/测试窗口 + 1K/100s 时长。上限 model_context_tokens * 0.5 * 0.8。硬底 30K，硬顶 120K。

`ContextBudget(total_chars=N)` — 字符级软上限，按 priority 降序分配，超预算先压缩低优先级块，每块保留 >= min_chars。

| 公开 API | 说明 |
|----------|------|
| `compute_budget(codegraph_nodes, test_window_count, case_duration_sec, model_context_tokens) -> int` | 动态预算计算 |
| `ContextBudget(total_chars).add(name, content, priority, min_chars)` | 注册内容块 |
| `ContextBudget.render() -> list[(name, truncated_text)]` | 按预算渲染 |
| `ContextBudget.format_report() -> str` | 人类可读预算使用统计 |
| `ContextBudget.concat(joiner) -> str` | 合并为单字符串 |

---

## utils.py

| 函数 | 行号 | 职责 |
|------|------|------|
| `parse_json_from_llm(content, fallback=None)` | 17-31 | 首末 `{}` 截取 JSON |
| `extract_relevant_sections(text, keywords, context_lines=15, max_chunks=30)` | 36-73 | 关键词匹配源码片段 |
| `build_keyword_variants(func_name)` | 76-80 | ADAS 功能名 C 标识符变体 |
| `get_func_fields(func_name) -> dict` | 219-227 | FUNC_FIELD_MAP 查表 |
| `ALL_FUNCTIONS` | 85 | `["BSD","LCA","DOW","RCW","RCTA","RCTB","FCTA","FCTB"]` |

---

## Pi-first 调度补充（2026-08-27）

`ai/pi_bridge.py` 是外部 Pi RPC 的唯一 Python 驱动边界。它在启动前刷新当前
项目的 `.pi/extensions/radar-capabilities.ts`，显式以 `--extension` 加载；Windows
优先直接启动 Pi 的 Node entry，并在关闭时回收本次进程树。provider/model 由构造
参数或 `CR60_PI_PROVIDER`/`CR60_PI_MODEL` 指定；未指定 provider 时只读探测当前
`pi --list-models`，不把某个机器的 provider 别名写死。

Pi 的系统提示词要求每次任务先绑定 data、arbe/source、COEM/车型、branch/commit、
binary/config 和 replay mode；identity fingerprint 冲突时禁止跨 artifact 合并。代码
解释必须从本次 `code-context`/`code-analyze`/`event-code-path` 动态获取真实
entry/caller/callee/condition/parameter/output，并按调用关系与源码行号组织条件链；不得
套用固定功能模板或固定条件顺序。当前 source 未发现的阶段只能标为未发现，不能补齐。
详细报警回答先给总结结论，再按实际链路呈现同帧值和条件结果；默认报警终点是 arbe
报警灯对应的算法输出，CAN 只在用户明确要求时作为辅助证据。

`ai/capability/pi_tool_bridge.py` 是生成 extension 的唯一 JSON-in/JSON-out 后端：
按 name 分派 leaf `BaseModule` adapter 或现有 `BaseTool`，默认不开放副作用；
`--allow-execution` 只允许已批准的 supervisor 使用，生成的 Pi extension 不传此开关。

`engines/pi_context.py` / `ai/modules/pi_context.py` 生成
`pi-orchestration-context.v1`。Pi prompt 只接收该上下文的紧凑只读摘要，完整数据
通过 artifact refs 和后续 tool 查询；身份、source/binary fingerprint、freshness
和 policy 不得被模型覆盖。正式用户故事、Given/When/Then 和追踪矩阵见
`docs/technical/CR60_PI_DDD_REQUIREMENTS_AND_ACCEPTANCE.md`。
