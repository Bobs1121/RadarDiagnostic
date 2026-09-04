# radarAnalyze 生产级设计体系 · 01 · 链路级外科拆解

> **版本**: PROD-1.0 · 2026-08-13
> **本篇定位**: 将三条真实运行链路逐行拆解，标注每步的输入/输出/确定性、异常处理、是否被静默吞掉；并深入插件化断层专题。

---

## 1. 三条真实运行链路总览

| 链路 | 入口 | 编排核心 | 性质 |
|---|---|---|---|
| **L1 诊断** | `cli.py -p/-e` | `orchestrator.run_diagnosis` | 8步固定管线，**生产主路径** |
| **L2 查询** | `cli.py -q` | `data_query_engine.run_query` | 7步 NL→查数，**生产 query 路径** |
| **L3 Agent** | `cli.py agent-loop` | `AgentLoopModule` | 离线顺序执行器，**实验** |

---

## 2. L1 · 诊断管线逐行拆解（`orchestrator.run_diagnosis` :316-1067）

### 2.1 步骤表

| # | 步骤 | 代码区间 | 输入 | 输出 | 确定性/LLM | 异常处理 |
|---|---|---|---|---|---|---|
| 1 | INIT | 354-355 | case_dir, config | source_docs/codegraph | 混合 | try/except 静默 |
| 2 | CLASSIFY | 358-393 | problem, expected | func_info, classification | ✅LLM×2 | `safe_llm_call` |
| 3 | EXTRACT | 396-444 | store | windows, evidence | —（除1处chat） | try/except |
| 4 | EVIDENCE | 447-595 | evidence候选 | conditions, TPE, probe | 混合（并行） | 每分支 try/except |
| 5 | SIGNALS | 598-668 | — | suppression/output/params | — | try/except |
| 6 | DIAGNOSE | 670-940 | ContextBudget | panel_result | ✅LLM×多 | `safe_llm_call` |
| 7 | FIX | 944-959 | diagnosis | fix_report_md | ✅LLM×1 | try/except🔴 |
| 8 | DELIVER | 962-1067 | 全部 | report/html/bundle/memory | — | best-effort |

### 2.2 关键步骤细节

**Step 4 EVIDENCE（447-595）**：`ThreadPoolExecutor(max_workers=2)` 并行跑「条件提取(LLM) ∥ TPE(确定性)」，每分支独立 try/except —— 一个失败不影响另一个。随后串行 probe 阶段（`VariableQueryPlanner` LLM + `DataProbe`）。

**Step 6 DIAGNOSE（670-940）**：先构建 `ContextBudget`（18 个内容块，优先级 100→40），再调 `ExpertPanel.run_panel()`（LangGraph，5专家×3轮，实际 ThreadPoolExecutor 并行）。**CodeGraph 语义上下文注入在 680 行 `self.codegraph_db_path` —— 触发 AttributeError 被吞，该块实际为空**（见下）。

**Step 7 FIX（944-959）**：调 `_generate_code_fix`(2052)。其中 2065 行 `cg_path = self.codegraph_db_path` **在 try 之外**，必然抛 `AttributeError`，外层(944-954)捕获 → **fix 永远输出空**。

### 2.3 静默失败专题

`orchestrator.py` 有 ≥10 处 `except Exception: logging.warning(...); pass` 模式。最严重的是 `codegraph_db_path`（见 `02-surgery-defects.md` P0-1）：

```
680:  cg_path = self.codegraph_db_path   → AttributeError（被 try 吞）→ CodeGraph 上下文恒为空
865:  _cg_db  = self.codegraph_db_path   → AttributeError（被 try 吞）→ CG 节点统计恒为 0
1990: db_path = self.codegraph_db_path  → AttributeError（被 try 吞）→ CodeGraph 构建失败
2065: cg_path = self.codegraph_db_path  → AttributeError（try 之外）→ 代码修复恒失败
2118: cg_path = self.codegraph_db_path  → AttributeError（被 try 吞）→ renderer 失败
```

**后果**：诊断成功跑完，但「CodeGraph 上下文」「代码修复建议」两个核心输出恒为空/坏，**用户无感知**。

---

## 3. L2 · 查询管线逐行拆解（`data_query_engine.run_query` :139）

| # | 步骤 | 代码区间 | 确定性/LLM | 说明 |
|---|---|---|---|---|
| 1 | parse | 203 | — | case_loader 解析 |
| 2 | inventory | 211 | — | 信号清单 |
| 3 | plan | 380 | ✅LLM | `_plan_query` 生成 JSON 计划 |
| 4 | validate | 413 | — | `_validate_plan` 模糊纠错信号名 |
| 5 | extract | 475 | — | `_extract_data` 按计划取数 |
| 6 | **investigate** | 180-184 | **—** | **`EngineeringInvestigator`（确定性调查层）** |
| 7 | answer | 688 | ✅LLM | `_answer_question` 生成答案 |

**重点**：L2 是唯一把 `investigation_engine`（确定性条件↔数据调查）接入生产的地方。它复用 `conditions:<FUNC>`、`signal_mapping`、`variable_chains`，产出 `InvestigationResult`（含 `ConditionCheck[]`、`analysis_windows`、`limitations`），feed 给 LLM 生成最终答案。

### 3.1 EngineeringInvestigator 内部拆解

| 方法 | 行号 | 职责 | 限制 |
|---|---|---|---|
| `investigate` | 160 | 加载条件/映射/CodeGraph 并执行 | freshness 门控 |
| `_select_conditions` | 378 | 关键词相关度排序，限 15 条 | 无 LLM |
| `_parse_comparison` | 817 | 解析 `变量 op 阈值` | 跳过 `&&`/`\|\|` |
| `_resolve_signals` | 544 | 变量→CAN 信号 | 无语义猜测 |
| `_query_data_fact` | 672 | 查时间线+窗口过滤 | carry-forward |
| `_apply_mapping_transform` | 608 | 枚举/缩放转换 | 仅 passthrough/1:1/enum，其余 unknown |
| `_evaluate` | 839 | 阈值求值 | 仅单数值比较；复合→unknown |
| `_derive_analysis_windows` | 480 | 由 Enable>0 推导有效窗 | 简单活跃启发式 |

**确定性承诺**：`InvestigationResult.to_dict` 硬编码 `deterministic_checks_are_advisory=True` —— 明确「确定性检查是咨询性证据，不是硬结论」。

---

## 4. L3 · Agent 链路拆解（`ai/agent_loop.py`）

| 组件 | 行号 | 职责 |
|---|---|---|
| `AgentLoop.run` | 108 | 顺序执行预置 plan，**无 LLM** |
| `_resolve_tool` | 151 | plan 步骤→BaseTool |
| `safe_execute` | — | 异常折叠为 `status=error` |
| `ask_human` | 175 | 仅写 `pending_input`，置 `input_required` |

**核心缺陷**：`AgentLoop` 是「脚本执行器」不是「ReAct Agent」——plan 由调用方手写（CLI `--tool-call` JSON），**没有 LLM 生成 plan**。`build_agent_tool_registry` / `TOOL_REGISTRY` 无任何生产调用方，仅 `tools/run_agent_loop_smoke.py` 和测试使用。

---

## 5. 插件化断层专题（本系列核心）

### 5.1 PlatformFamily 插件字段「声明未实现」

`core/identity.py:51-54` 声明了 4 个插件字段：

```python
codegraph_plugin: Optional[str] = None
parser_plugin:     Optional[str] = None
symbol_ruleset:    Optional[str] = None
default_pipeline_profile: Optional[str] = None
```

**已核实**：这 4 个字段**仅有** `identity.py` 自身引用（to_dict/from_dict），**全仓库无任何分发代码**。即：
- `parser_plugin` 从未被 `parsers/case_loader.py` 查询；
- `codegraph_plugin` 从未被 `ai/codegraph/builder.py` 查询；
- `symbol_ruleset` 从未被任何符号提取逻辑查询。

**结论**：插件化是设计意图，未落地。这是「代码↔数据对应、插件化管理」目标的核心断层。

### 5.2 Parser 分发：硬编码扩展名 glob

`parsers/case_loader.py:59-238`：

```python
for p in case_dir.glob("*.bag"):  → BagParser  → insert_bag_frame
for p in case_dir.glob("*.blf"):  → BlfParser  → bulk_insert_can
for p in case_dir.glob("*.mf4"):  → Mf4Parser  → bulk_insert_can_from_dict
```

**问题**：
1. **无注册表**：新格式（如 `.asc`/`.xlsx`/自定义）需改 `case_loader.py` 加 glob 块 + 加 `CaseLoadResult` 字段（46-57）。
2. **无插件发现**：解析逻辑与分发逻辑耦合在单一函数。
3. `PlatformFamily.parser_plugin` 字段存在但未驱动此分发。

### 5.3 PlatformAdapter 分发 bug

`ai/orchestrator.py:286-314`：

```python
def _get_code_learner_adapter(self):
    ...
    adapter_factory.get_code_learner_adapter(
        self.identity.variant_id,   # ← BUG: 传 variant_id 而非 self.platform_id
        ...
    )
```

- 注册表按 `platform_id`（`gen6_c_radar`、`gen5_reco_pl`）key。
- 传入的却是 `variant_id`（如 `gen6/gwm_b26`）→ 查不到 → `except` 吞掉 → `adapter=None`。
- `factory.py:106-108` 对 signal_mapper 有 `_SignalMapperDefault` fallback，但 code_learner/condition_extractor **没有 fallback**，直接 `KeyError` 被吞。

**后果**：platform 适配器实际上**从未工作**（除 codegraph 扫描路径 2011 行正确用 `self.platform_id`）。

### 5.4 未分发总表

| 插件字段 | 声明处 | 分发处 | 状态 |
|---|---|---|---|
| `codegraph_plugin` | identity.py:51 | — | 🔴 未分发 |
| `parser_plugin` | identity.py:52 | — | 🔴 未分发 |
| `symbol_ruleset` | identity.py:53 | — | 🔴 未分发 |
| `default_pipeline_profile` | identity.py:54 | — | 🔴 未分发 |
| PlatformAdapter 注册表 | factory.py:22-45 | orchestrator.py:286-314 | 🔴 用错 key |
| Parser 分发 | — | case_loader.py:59-238 | 🔴 硬编码 glob |

---

## 6. 关键结论

1. **L1 诊断管线成熟但被静默失败腐蚀**：`codegraph_db_path` 让 CodeGraph 和代码修复两个核心能力实际失效。
2. **L2 查询管线是「确定性调查」的唯一生产落地**：`investigation_engine` 在这里发光，但未接入诊断。
3. **L3 Agent 是半成品**：无 LLM 规划器的脚本执行器，无生产价值。
4. **插件化目标态与现状落差巨大**：4 个插件字段 + 2 个注册表全部未正确落地 —— 这是生产级设计要解决的核心。

> **下一篇** → `02-surgery-defects.md`：缺陷清单与根因。