# memory/ 模块实现说明

> 用于「需求 ↔ 实现」review。AI 编辑 memory/ 目录文件时参考本文档。

---

## 模块概览

| 文件 | 定位 |
|------|------|
| `__init__.py` | 导出 MemorySystem, AutoDream |
| `memory_system.py` | 6 层记忆统一读写 + 诊断上下文拼装 + SemanticMemory 索引桥接 |
| `auto_dream.py` | 记忆整合引擎 (Phase 0-4)，门控 + 锁 + AI 整合 + 变化驱动能力模块刷新 |
| `semantic_memory.py` | M5 语义记忆：LanceDB 可选后端 + fallback 向量召回 |

Pi 读取边界：`engines/memory_recall.py` / `ai/modules/memory_recall.py` 复用本目录的
`MemorySystem`，通过 Pi 的 `memory-recall` 原子工具只读输出 L1-L6/semantic 的分层值、
freshness 状态和 provenance；不复制记忆库、不在 recall 中写入当前 case。

---

## semantic_memory.py — SemanticMemory

### 定位与后端

`SemanticMemory` 是 M5 语义召回层，不替换 `MemorySystem` 的 L1-L6 JSON 精确记忆。

| 后端 | 行为 |
|------|------|
| `lancedb` | `lancedb` 可导入且初始化成功时启用，表名默认 `triage_history` |
| `fallback` | 无 `lancedb` 或初始化失败时启用，落盘到 `fallback_vectors.json` |

默认 embedder 是离线 feature-hashing；也可通过 `embedder: Callable[[str], list[float]]` 注入本地 embedding。

### 路径与隔离

| API | 行为 |
|-----|------|
| `SemanticMemory(store_dir, embedder=None, dim=256, table="triage_history")` | 使用调用方传入目录，创建语义索引 |
| `SemanticMemory.store_dir_for_variant(project_root, variant)` | 返回 `.workspaces/<sanitized-variant>/memory/lancedb` |
| `SemanticMemory.for_variant(project_root, variant, ...)` | 使用 V3 Workspace 兼容路径创建 store |

`variant` 可为 `core.identity.Variant` 风格对象（读取 `.variant_id`）或字符串；路径命名规则与 `core.workspace.Workspace.from_variant()` 一致，将 `/`、`\` 替换为 `_`。

### 记录与召回 API

| 方法 | 行为 |
|------|------|
| `add(symptom, signal="", code_line="", conclusion="", metadata=None) -> str` | 将 `[症状, 异常信号, 代码行, 结论]` compose 后向量化；内容 SHA1 前 12 位作为去重 id |
| `search(query, k=5, min_score=0.0) -> list[dict]` | 返回 `{id, score, symptom, signal, code_line, conclusion, metadata}`；按 `score desc, id asc` 稳定排序 |
| `MemorySystem.search_semantic_cases(func_name, problem, case_dir=None, max_results=3)` | `MemoryRecall` 使用的只读公共 semantic recall wrapper，内部复用既有筛选逻辑 |
| `count() -> int` | 当前 distinct record 数 |
| `clear()` | 清空当前后端记录并持久化 |

fallback JSON schema: `{ "dim": int, "records": [ { "id", "vector", "symptom", "signal", "code_line", "conclusion", "metadata" } ] }`

## Auto Dream Freshness 发布

- 代码漂移时刷新现有功能条件模块、增量 CodeGraph、变量链、L6 和 overview；没有既有条件文件时不盲目扫描全部功能
- `_run_dream_cycle()` 返回 `_code_learning` / `_variable_chains` / `_conditions` / `_codegraph` 独立结果
- CLI 只把成功结果发布到 `knowledge_manifest.json`；失败模块保留 stale，其他成功 scope 可独立使用
- `MemorySystem.read_code_knowledge()` / `read_constants()` 在 stale 时返回空对象，variant 模式禁止回退到全局 legacy L6

---

## memory_system.py — MemorySystem

### 构造与路径约定

`__init__(self, project_root: Path, memory_dir=None, config=None)` — 近期开口

| 成员 | 含义 |
|------|------|
| `self.root` | 项目根目录 |
| `self.memory_dir` | `project_root / "memory"`，自动创建 |
| `self._ctx_cache` | 诊断上下文缓存，键 = `(func_upper, problem[:240], case_dir_str)` |

自动创建子目录: `functions/`, `sessions/`, `code_knowledge/` (47-49)。**不**自动创建 `patterns.json` 或 `project.md`。
`SemanticMemory` 为**懒初始化**：仅在 `memory.semantic_index.enabled` 打开且首次 add/search 时创建 `memory_dir/semantic/`；初始化或查询失败只记日志，不影响主诊断。

### L1 — project.md

| 方法 | 行为 | 行号 |
|------|------|------|
| `read_project_memory() -> str` | 存在则读 UTF-8，否则 `""` | 61-66 |
| `write_project_memory(content: str)` | 整体覆盖 | 68-70 |
| `append_project_memory(entry: str)` | 文末追加 `## [YYYY-MM-DD HH:MM]\n{entry}` | 72-78 |

### L2 — memory/functions/{FUNC}.json

| 方法 | 行为 | 行号 |
|------|------|------|
| `read_function_knowledge(func_name) -> dict` | 读 JSON，不存在返回 `{}` | 82-87 |
| `write_function_knowledge(func_name, knowledge)` | 写入前设 `_updated` | 89-93 |
| `get_all_function_names() -> list[str]` | `functions/*.json` stem 列表 | 95-99 |
| `has_function_knowledge(func_name) -> bool` | 文件是否存在 | 101-102 |

schema 示例: `function`, `diagnosis_count`, `known_issues[]`, `description`, `state_machine`, `_updated`

### L3 — memory/patterns.json

| 方法 | 行为 | 行号 |
|------|------|------|
| `read_patterns() -> list[dict]` | 读 JSON 数组，不存在返回 `[]` | 106-111 |
| `add_pattern(pattern: dict)` | MD5 前 8 位 `_id` 去重，追加写入 | 113-132 |
| `find_similar_patterns(func_name, symptom_keywords) -> list[dict]` | function 匹配 + keywords 交集，带 `_match_score` | 135-147 |

schema: `function`, `symptom`, `root_cause`, `keywords[]`, `fix_hint`, `_learned_at`, `_id`

### L4 — memory/sessions/{session_id}.json

| 方法 | 行为 | 行号 |
|------|------|------|
| `create_session(case_id, problem, expected) -> str` | 生成 `{case_id}_{YYYYMMDD_HHMMSS}`，写入初始 dict | 151-165 |
| `log_step(session_id, step_name, detail)` | 追加到 `steps[]` | 167-176 |
| `log_finding(session_id, finding: dict)` | 追加到 `findings[]` | 178-184 |
| `complete_session(session_id, result_summary)` | status="completed", 写 completed_at | 186-193 |

schema: `session_id`, `case_id`, `problem`, `expected`, `created_at`, `status`, `steps[]`, `findings[]`, `completed_at`, `result_summary`

### L5 — cases/{CASE}/memory.json

| 方法 | 行为 | 行号 |
|------|------|------|
| `read_case_memory(case_dir) -> dict` | 读 JSON，不存在 `{}` | 207-212 |
| `write_case_memory(case_dir, memory)` | 写入前设 `_updated`；同时写 L3 pattern，并 best-effort 写入 `memory_dir/semantic/` 语义索引（JSON 仍是真实来源） | 214+ |

### L6 — memory/code_knowledge/

| 方法 | 行为 | 行号 |
|------|------|------|
| `read_code_knowledge(func_name) -> dict` | 读 `{FUNC}.json`（freshness 门控，stale 返回空） | 223-231 |
| `read_code_knowledge_raw(func_name) -> dict` | 读 `{FUNC}.json` **原始内容**（不受门控，仅供合并/审计） | 新增 |
| `merge_code_knowledge(func_name, updates) -> dict` | **单一 L6 写入口**：在原始基座上按 focus/id 增量合并，保留 CodeLearner 数据 | 新增 |
| `write_code_knowledge(func_name, data) -> dict` | **整文件覆盖**写入（全量重建时用） | 233-238 |
| `list_code_knowledge_funcs() -> list[str]` | 仅 stem 全大写的 `.json` | 233-238 |
| `read_code_learning_state() -> dict` | 读 `learning_state.json` | 240-248 |
| `render_code_knowledge_for_context(func_name, max_chars=6000) -> str` | 按 focus 渲染 Markdown | 250-312 |

`FUNC.json` schema: `_meta` (function, last_updated, learned_focuses, source_hashes) + 各 focus 下结构化块 (alarm_logic, calculation_chain, output_chain, state_machine)

`learning_state.json`: `cursor`, `warmup_done`, `pair_hashes`, `learned_pairs`, `total_learned_pairs`, `last_learn_at`

> **单一 L6 写入者约定（Stage 6）**：CodeLearner（auto-dream）与 orchestrator `_precipitate_knowledge` 是 L6 的两个来源，二者 id 前缀不同（learner 无前缀 vs `diag-`）。为防互相覆盖，**跨来源写入必须走 `merge_code_knowledge`**（读原始底 + 按 id 幂等合并），不要用「`read_code_knowledge()`（门控）+ `write_code_knowledge()`（覆盖）」模式——那会在 stale 时读到空而清掉另一来源数据。

`FUNC.json` schema: `_meta` (function, last_updated, learned_focuses, source_hashes) + 各 focus 下结构化块 (alarm_logic, calculation_chain, output_chain, state_machine)

`learning_state.json`: `cursor`, `warmup_done`, `pair_hashes`, `learned_pairs`, `total_learned_pairs`, `last_learn_at`

### 上下文拼装

`build_context_for_diagnosis(func_name, problem, case_dir=None) -> str` — 316-375

组合: L1 (截断 2000) + L2 JSON (截断 3000) + L6 render + L3 similar (最多 3 条) + L4 sessions + SemanticMemory 语义召回（最多 `memory.semantic_index.max_hits`，带 case/report provenance、明确标注为非确定性） + L5 (截断 1500)

**Freshness 门控（Stage 6）**：当代码/常量/identity 漂移（`freshness.code_changed/constants_changed/identity_changed`）时，代码派生的学习层 **L3 相似历史 + 语义记忆 + L6** 从上下文剔除（标注「代码已漂移，学习产物暂不注入」），避免污染当前分析；用户/运维笔记（L1/L2/L4/L5）不受影响。此规则由 `MemorySystem._code_learning_stale()` 统一判定。

结果写入 `_ctx_cache`。`invalidate_context_cache()` 清空。

### SemanticMemory 配置门控

```yaml
memory:
  semantic_index:
    enabled: true   # 缺省开启；不可用时自动降级
    max_hits: 3
```

语义召回层只做**索引/召回**，不得替代 L1-L6 JSON 真值；所有命中都必须保留 `case_id`、`case_memory_path`、可选 `report.md` 等 provenance。

### 并发与原子性

- MemorySystem **不使用锁**，一律 `Path.write_text` / `read_text` 直接写盘
- 多进程同时写同一文件存在**竞态**风险
- 并发控制仅在 AutoDream 层通过 `.dream-lock` 协调

---

## auto_dream.py — AutoDream

### 构造

`__init__(self, memory_system, router, project_root, config=None)` — 91-98

| 成员 | 含义 |
|------|------|
| `self.lock_path` | `memory/ .dream-lock` |
| `self.log_path` | `memory/dream_log.json` |

### 入口: try_dream

`try_dream(self, on_status=None, force=False, reason=None) -> Optional[dict]` — 102-145

流程:
1. `force=False` 时检查 `_is_gate_open()`，不满足返回 None
2. 检查 `_is_locked()`，已锁返回 None
3. `force=True` 且 `reason` 非空时，先记录强制原因（如 freshness drift）
4. `_acquire_lock()` → `_run_dream_cycle(status)` → `_apply_dream_result` → `_record_dream` → `_release_lock()`

### 门控条件

| 条件 | 默认值 | 行号 |
|------|--------|------|
| 距上次 dream ≥ `DREAM_INTERVAL_HOURS` | 4 小时 | 26, 149-159 |
| 新会话数 ≥ `MIN_NEW_SESSIONS` | 2 个 | 27, 171-188 |

新会话 = `created_at` 严格晚于上次 dream 日志最后一条 `timestamp` 的 session

### dream-lock

- `_acquire_lock` 写入当前 PID
- 锁文件包含 PID 且该 PID 仍存活 → 立即视为锁定
- 锁文件包含 PID 但进程已不存在 → 立即释放，不等待 1 小时
- 非 PID / 无法确认进程状态时，仍按 mtime < 1 小时锁定、> 1 小时自动释放

### 5 阶段流程

**Phase 0 — Study (代码学习)** `_run_code_learning` (227-271)
- `CodeLearner.learn()` → 写 L6 JSON
- `CodeLearner.ensure_overview_docs()` → 刷新 `source_docs/*.md`
- 不使用 CONSOLIDATION_PROMPT

**Phase 1 — Orient (定向)** (288-290)
- `_refresh_variable_chains()`: 刷新 `variable_chains.json`
- `_gather_all_memory_context()`: 拼接 L1 + 各 L2 + patterns 摘要 + source_docs/*.md 前 500 字 + signal_mapping 抽样 + 最近 5 个 L5 case memory + L6 摘要

**Phase 2 — Gather (收集)** (292-293)
- `_gather_recent_sessions()`: 按 mtime 逆序取最近 10 条 session

**Phase 3 — Consolidate (整合)** (295-298)
- `_build_prompt(context, recent, code_delta)` → `router.complex(prompt, system=CONSOLIDATION_PROMPT)`
- CONSOLIDATION_PROMPT (33-81) 要求输出 JSON: `project_memory_update`, `function_updates`, `patterns_to_remove`, `patterns_to_add`, `conflicts_found`, `summary`

**Phase 4 — Apply (应用)** `_apply_dream_result` (507-537)
- `project_memory_update` → `memory.write_project_memory`
- `function_updates` → 逐功能 read + update + write
- `patterns_to_remove` → 按 `_id` 过滤后写回
- `patterns_to_add` → 逐条 `memory.add_pattern`
- `conflicts_found` → 仅 status 计数，不单独落盘

### dream_log.json

每条: `timestamp`, `summary`, `conflicts`, `patterns_added`, `patterns_removed`，可选 `code_pairs_learned`, `code_pairs_skipped`, `code_warmup_done`, `freshness_any_changed`, `freshness_changed_keys`, `force_reason`。日志最长 100 条 (565-567)。

### freshness 联动

- CLI 会在 `config["identity"]["freshness"]` 放入当前 variant 的 drift 摘要
- `try_dream(..., reason=...)` 会把 freshness drift/强制原因写入 result 与 `dream_log.json`
- freshness drift 只负责**放宽门控并记录 provenance**；Phase 0 实际学哪些源码仍由 `CodeLearner.learn()` 的 hash/预算策略控制

### Review 关注点

- 门控依赖 dream_log 最后一条 timestamp 与 session created_at 比较，时钟回拨可能异常
- 做梦持锁期间不阻止 orchestrator 直接写 L2/L3/L5
- AI 输出仅靠首尾 `{}` 切片解析 JSON，多 JSON 或夹杂文字易失败
- `add_pattern` 与 `patterns_to_remove` 的 `_id` 一致性
- Phase 编号注释为 5 阶段 (0-4)，与用户口头「四阶段」并存易混淆
- `_code_learning` 字段契约需与 CodeLearner.learn 返回值同步
