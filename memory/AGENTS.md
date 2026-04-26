# memory/ 模块实现说明

> 用于「需求 ↔ 实现」review。AI 编辑 memory/ 目录文件时参考本文档。

---

## 模块概览

| 文件 | 定位 |
|------|------|
| `__init__.py` | 导出 MemorySystem, AutoDream |
| `memory_system.py` | 6 层记忆统一读写 + 诊断上下文拼装 |
| `auto_dream.py` | 记忆整合引擎 (Phase 0-4)，门控 + 锁 + AI 整合 |

---

## memory_system.py — MemorySystem

### 构造与路径约定

`__init__(self, project_root: Path)` — 44-57

| 成员 | 含义 |
|------|------|
| `self.root` | 项目根目录 |
| `self.memory_dir` | `project_root / "memory"`，自动创建 |
| `self._ctx_cache` | 诊断上下文缓存，键 = `(func_upper, problem[:240], case_dir_str)` |

自动创建子目录: `functions/`, `sessions/`, `code_knowledge/` (47-49)。**不**自动创建 `patterns.json` 或 `project.md`。

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
| `write_case_memory(case_dir, memory)` | 写入前设 `_updated` | 214-219 |

### L6 — memory/code_knowledge/

| 方法 | 行为 | 行号 |
|------|------|------|
| `read_code_knowledge(func_name) -> dict` | 读 `{FUNC}.json` | 223-231 |
| `list_code_knowledge_funcs() -> list[str]` | 仅 stem 全大写的 `.json` | 233-238 |
| `read_code_learning_state() -> dict` | 读 `learning_state.json` | 240-248 |
| `render_code_knowledge_for_context(func_name, max_chars=6000) -> str` | 按 focus 渲染 Markdown | 250-312 |

`FUNC.json` schema: `_meta` (function, last_updated, learned_focuses, source_hashes) + 各 focus 下结构化块 (alarm_logic, calculation_chain, output_chain, state_machine)

`learning_state.json`: `cursor`, `warmup_done`, `pair_hashes`, `learned_pairs`, `total_learned_pairs`, `last_learn_at`

### 上下文拼装

`build_context_for_diagnosis(func_name, problem, case_dir=None) -> str` — 316-375

组合: L1 (截断 2000) + L2 JSON (截断 3000) + L6 render + L3 similar (最多 3 条) + L5 (截断 1500)

结果写入 `_ctx_cache`。`invalidate_context_cache()` 清空。

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

`try_dream(self, on_status=None, force=False) -> Optional[dict]` — 102-145

流程:
1. `force=False` 时检查 `_is_gate_open()`，不满足返回 None
2. 检查 `_is_locked()`，已锁返回 None
3. `_acquire_lock()` → `_run_dream_cycle(status)` → `_apply_dream_result` → `_record_dream` → `_release_lock()`

### 门控条件

| 条件 | 默认值 | 行号 |
|------|--------|------|
| 距上次 dream ≥ `DREAM_INTERVAL_HOURS` | 4 小时 | 26, 149-159 |
| 新会话数 ≥ `MIN_NEW_SESSIONS` | 2 个 | 27, 171-188 |

新会话 = `created_at` 严格晚于上次 dream 日志最后一条 `timestamp` 的 session

### dream-lock

- 锁文件存在且 mtime 在 1 小时内 → 锁定 (192-203)
- 超时 1 小时 → 自动释放
- `_acquire_lock` 写入当前 PID (205-206)

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

每条: `timestamp`, `summary`, `conflicts`, `patterns_added`, `patterns_removed`，可选 `code_pairs_learned`, `code_pairs_skipped`, `code_warmup_done`。日志最长 100 条 (565-567)。

### Review 关注点

- 门控依赖 dream_log 最后一条 timestamp 与 session created_at 比较，时钟回拨可能异常
- 做梦持锁期间不阻止 orchestrator 直接写 L2/L3/L5
- AI 输出仅靠首尾 `{}` 切片解析 JSON，多 JSON 或夹杂文字易失败
- `add_pattern` 与 `patterns_to_remove` 的 `_id` 一致性
- Phase 编号注释为 5 阶段 (0-4)，与用户口头「四阶段」并存易混淆
- `_code_learning` 字段契约需与 CodeLearner.learn 返回值同步
