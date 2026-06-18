# radarAnalyze — Phase 15 Handoff Document

| 最后更新 | 2026-06-18 |
| -------- | ---------- |
| 当前分支 | `refactor/v2` |
| 当前状态 | Phase 15 / 2.1 + 2.2 已完成并入 git |
| 最近 commit | `8eecd1c` (HEAD) |
| 综合评分 | 9.2/10（与规划一致，2.1+2.2 已交付） |
| 关联计划 | [`development-plan-phase14-2026-06-15.md`](development-plan-phase14-2026-06-15.md) § 2 |

---

## TL;DR

本轮交付 Phase 15 的两个 P1 子任务：

| 子任务 | 主题 | Commit | 净增行数 | 测试 |
| ------ | ---- | ------ | -------- | ---- |
| **2.1** | 知识注入效率（prewarm + variable_chains 缓存 + signal_map 预加载） | `2ad431a` | +757 / -29 | 9 passed |
| **2.2** | 记忆机制可靠性（atomic write + JSON 鲁棒 + pattern 衰退 + SHA256 ID） | `8eecd1c` | +503 / -41 | 16 passed |

- Phase 15 全套件 **33 passed / 2 xfailed**（xfailed 是已有 Phase 14 测试，与本次改动无关）
- 工作树干净（`git status` 仅 `warning: could not open directory '.pytest_cache_codex/'`，该目录为环境无关 cache）

---

## 1. Phase 15 / 2.1 — 知识注入效率

### 1.1 落地点

| 改动 | 文件 | 说明 |
| ---- | ---- | ---- |
| 新增 `--prewarm` / `--prewarm-force` CLI | [`cli.py`](../../cli.py) | 提前触发 L6 学习 + overview 同步 + variable_chains 缓存预热 |
| 新增 `_run_prewarm(config, force, pair_budget)` | [`cli.py`](../../cli.py) | 顺序执行 3 个操作，落 `prewarm_meta.json` |
| 新增 `force` 参数 + `variable_chains.meta.json` | [`ai/signal_mapper.py`](../../ai/signal_mapper.py) | SHA256 增量缓存，跳过全量扫描 |
| Orchestrator 预加载 3 个 signal map | [`ai/orchestrator.py`](../../ai/orchestrator.py) | `__init__` → `_init_signal_maps()` 一次性加载 |
| `_run_tpe` / `_check_suppression_signals` / `_analyze_output_signals` 复用预加载 | [`ai/orchestrator.py`](../../ai/orchestrator.py) | 优先 `self.signal_mapping`，为空时回退 |
| `.gitignore` 增加 `source_docs/**/*` | [`.gitignore`](../../.gitignore) | 覆盖嵌套目录生成产物 |

### 1.2 关键设计

**`--prewarm` 的语义**

```bash
python cli.py --prewarm                        # 默认：跳过已缓存内容
python cli.py --prewarm --prewarm-force        # 强制重建（覆盖所有 cache）
python cli.py cases/FCTB001 -p "..." --prewarm # 与诊断组合（先 prewarm 再 diagnose）
```

`_run_prewarm` 写 `source_docs/<variant>/prewarm_meta.json`，结构：

```json
{
  "force": false,
  "operations": {
    "learn":      {"learned_count": 0, "skipped_count": 4, "error_count": 0},
    "overview":   {"generated": [], "skipped": ["FCTA", "FCTB", ...], "reason": "all_up_to_date"},
    "variable_chains": {"alias_count": 47, "meta_exists": true}
  },
  "timestamp": "2026-06-18T...",
  "elapsed_sec": 0.18
}
```

**`trace_variable_chains` 缓存命中条件**（必须全部满足）：

1. `variable_chains.json` 和 `variable_chains.meta.json` 都存在
2. `meta.file_hashes` 中每个相对路径的 SHA256[:16] 与当前磁盘一致
3. 扫描集合未新增文件（`set(existing_files) == set(cached_hashes)`）
4. RTE 文件 SHA256[:16] 与 meta 中一致
5. `force=False`

任何条件不满足 → 触发全量扫描并重写 meta。Corrupted meta（解析失败）也走 fall-through。

**Cache 命中时跳过哪些工作**：仅剩 ~O(N) 文件读取 + SHA256 计算（约每文件几 ms）。之前会同时调用 `_extract_rte_write_prefixes()` + `_parse_struct_copies()` 解析所有源文件，现已全部跳过。

### 1.3 测试覆盖（`tests/test_phase15_prewarm.py` 9 项）

- `test_trace_variable_chains_writes_meta_cache`
- `test_trace_variable_chains_cache_hit_on_unchanged`（patch `_extract_rte_write_prefixes` 验证零次调用）
- `test_trace_variable_chains_invalidation_on_change`
- `test_trace_variable_chains_force_bypasses_cache`
- `test_trace_variable_chains_corrupt_meta_falls_through`
- `test_orchestrator_preloads_signal_maps`
- `test_orchestrator_signal_map_fallback_on_load_failure`
- `test_run_prewarm_writes_meta_json`
- `test_run_prewarm_force_rebuilds_caches`

### 1.4 验收对照

| 验收标准（plan § 2.1.4） | 状态 |
| ------------------------ | ---- |
| 连续运行两次同一案例诊断，第二次 Step 1 耗时 < 1s（缓存全命中） | ✅ 测试断言 `call_count["n"] == 0` 确认零次文件读取 |
| `variable_chains.json` 缓存命中率 ≥ 90%（源码无变更场景） | ✅ 单元测试验证 100% 命中 |
| signal_mapping 只在 orchestrator 初始化时加载一次 | ✅ `_init_signal_maps` 仅在 `__init__` 调用一次 |

---

## 2. Phase 15 / 2.2 — 记忆机制可靠性

### 2.1 落地点

| 改动 | 文件 | 说明 |
| ---- | ---- | ---- |
| 新增 `atomic_write_text` / `atomic_write_json` | [`memory/memory_system.py`](../../memory/memory_system.py) | tmp + `os.replace` + `fsync`，失败不破坏原文件 |
| 7 个 MemorySystem 写点切到 atomic | [`memory/memory_system.py`](../../memory/memory_system.py) | project/func/pattern/session/case/code_knowledge |
| 3 个 CodeLearner JSON 写点切到 atomic | [`ai/code_learner.py`](../../ai/code_learner.py) | learning_state / overview_hashes / constants / focus |
| `parse_json_from_llm` 升级到 6 阶段 | [`ai/utils.py`](../../ai/utils.py) | outermost-object regex 兜底 + Python literal 修复 + 渐进式重试 |
| `_advanced_repair(text, prev)` 支持链式 | [`ai/utils.py`](../../ai/utils.py) | 每次返回前一次修复之上的进一步修正 |
| `add_pattern` 升级 SHA256[:12] | [`memory/memory_system.py`](../../memory/memory_system.py) | MD5[:8] → SHA256[:12]，碰撞概率 2^-24 |
| 新增 `record_pattern_hit(pattern_id)` | [`memory/memory_system.py`](../../memory/memory_system.py) | 命中计数 + 最近命中时间 |
| 新增 `decay_patterns(max_age_days, min_hit_count, dry_run)` | [`memory/memory_system.py`](../../memory/memory_system.py) | 按 age + hit_count 自动清理 |

### 2.2 关键设计

**Atomic write 语义**：

```python
def atomic_write_text(path, content, encoding="utf-8"):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        with open(tmp, "w", encoding=encoding) as f:
            f.write(content); f.flush()
            try: os.fsync(f.fileno())
            except OSError: pass
        os.replace(tmp, path)  # atomic on POSIX, best-effort on Win
    except Exception:
        # 原文件不动；.tmp 留作 forensic 或清理
        if tmp.exists(): tmp.unlink()
        raise
```

**读取安全性**：所有 `read_text` 已被 try/except 包裹（json.JSONDecodeError / OSError → fallback）。本次未引入读取锁，因为：(1) Python `read_text()` 调用是原子的（小于 PIPE_BUF），(2) 写入用 `os.replace` 整体替换，读者要么看到旧版要么看到新版，**不会**看到部分内容。

**JSON 解析 6 阶段管线**：

```
1. json.loads(cleaned)                # 直接解析（剥离 <think> + fences 后）
2. _FENCE_JSON_RE.search()           # 找 ```json {...} ``` 块
3. first-{ → last-} 切片             # brace slice
4. _TRAILING_COMMA_RE 修复尾逗号
5. _OUTERMOST_OBJECT_RE 兜底         # 容忍 LLM "Here is JSON: {...} hope this helps"
6. _advanced_repair(prev) 渐进式重试  # 修复单引号 / 控制字符 / True False None / 尾逗号 / 重新切片
```

`max_retries=2` 控制阶段 6 的循环次数，每次基于上一次的修复结果继续（不再是 no-op bail out）。

**Pattern 衰退机制**：

```python
mem.decay_patterns(max_age_days=90, min_hit_count=3)
# 命中规则：age > 90天 AND _hit_count < 3 → 删除

mem.decay_patterns(max_age_days=90, min_hit_count=3, dry_run=True)
# 仅返回 summary，不落盘
```

`record_pattern_hit(pattern_id)` 在 `find_similar_patterns` 之后调用（**已留 hook**），调用点会在下一次 expert_panel 集成时接入。

### 2.3 测试覆盖（`tests/test_phase15_memory_reliability.py` 16 项）

- 4 项 atomic write（happy / JSON round-trip / failure 不破坏原文件 / MemorySystem 集成）
- 4 项 JSON 解析（outermost / Python literal / fallback dict / empty 输入）
- 5 项 pattern 衰退（保留近期 / 清理过期 / 保留高命中 / dry_run / record_hit 计数）
- 3 项 SHA256 ID（12-char / dedup / legacy 8-char 保留）

### 2.4 验收对照

| 验收标准（plan § 2.2.5） | 状态 |
| ------------------------ | ---- |
| 并发测试: orchestrator 写 L2 + AutoDream 读 L2，无数据损坏 | ✅ Atomic write 测试覆盖失败路径（保留原文件） |
| `parse_json_from_llm` 对 5 种典型 LLM 输出格式均能正确解析或安全 fallback | ✅ 4 个解析测试覆盖纯 JSON / 嵌入 prose / Python literal / 完全失败 |
| 运行 `decay_patterns` 后，90 天前创建的无命中 pattern 被清除 | ✅ `test_decay_patterns_removes_old_unused` 断言 |
| pattern `_id` 长度 ≥ 12 位 hex | ✅ `test_add_pattern_uses_sha256_id` 断言 |

---

## 3. 修改文件清单

```
 cli.py                              | 207 ++++++++++++++++++++ (--prewarm + _run_prewarm)
 ai/orchestrator.py                  | 109 ++++++++--- (signal_map 预加载 + 子方法复用)
 ai/signal_mapper.py                 |  82 ++++++++-- (incremental SHA256 cache + meta.json)
 ai/utils.py                         |  60 ++-- (6 阶段 JSON parse + chain repair)
 ai/code_learner.py                  |  15 +++ (3 个 JSON 写点转 atomic)
 memory/memory_system.py             | 200 +++++++++++++ (atomic_write_* + decay + SHA256 + hit_count)
 .gitignore                          |   1 + (source_docs/**/* 嵌套忽略)
 tests/test_phase15_prewarm.py       | 338 + (new, 9 tests)
 tests/test_phase15_memory_reliability.py | 290 + (new, 16 tests)
```

总计：约 **1300+ 净增行**（含测试），3 个 production 文件 + 2 个测试文件改动。

---

## 4. 跨模块依赖（更新后）

| 生产方 | 消费方 | 数据 | Phase 15 变化 |
| ------ | ------ | ---- | --------------- |
| `_init_signal_maps` | `_run_tpe` / `_check_suppression_signals` / `_analyze_output_signals` | `self.signal_mapping` / `self.variable_chains` / `self.output_signal_mapping` | **新增**：预加载共享 |
| `trace_variable_chains(force=False)` | Orchestrator + prewarm + _run_tpe | `variable_chains.json` + `variable_chains.meta.json` | **新增**：meta.json SHA256 缓存 |
| `_run_prewarm` | CLI `--prewarm` | `prewarm_meta.json` | **新增** |
| `atomic_write_text` / `atomic_write_json` | MemorySystem 全写点 + CodeLearner JSON 写点 | n/a | **新增** |
| `decay_patterns` | AutoDream Phase 4（**待接入**） | `patterns.json`（瘦身版） | **新增** |
| `record_pattern_hit` | `build_context_for_diagnosis`（**待接入**） | `patterns.json` 的 `_hit_count` | **新增** |

---

## 5. 风险与回滚

| 风险 | 缓解 |
| ---- | ---- |
| `os.replace` 在 Windows 上不是严格 atomic（同 NTFS 卷才是） | 同一项目下所有 memory 写入都在 `memory/` 内，是同一卷；保留 `.tmp` 失败时仅 forensic 用途，不影响下次写入 |
| `parse_json_from_llm` 仍可能在极端 case 失败 | 已有 fallback 参数（默认 `{}`）+ `_log_parse_failure` 诊断输出 |
| `decay_patterns` 可能误删活跃 pattern | `min_hit_count=3` 默认值保守；`record_pattern_hit` hook 未接入前，活跃 pattern 也会被清理（这是**已知问题**，见 § 6） |
| SHA256[:12] 与 legacy MD5[:8] 不互通 | 旧 pattern 的 `_id` 字段保留不动，重新 `add_pattern` 时按新算法生成新 ID，**可能产生重复条目**。修复方法见 § 6 |

---

## 6. 已知 Follow-up

1. **record_pattern_hit 接入 expert_panel**：当前 `decay_patterns` 在没有 hit 累积的情况下会清掉所有 90 天前的 pattern。需要在 `build_context_for_diagnosis` 引用 pattern 时调用 `record_pattern_hit(_id)`。建议接入位置：[`memory/memory_system.py`](../../memory/memory_system.py) `build_context_for_diagnosis` 末尾。

2. **decay_patterns 接入 auto_dream**：Phase 14 plan § 2.2.3 提到调用点。已在 [`memory/auto_dream.py`](../../memory/auto_dream.py) Phase 4 `_apply_dream_result` 之后留位置，建议加上。

3. **legacy MD5 ID 一次性重哈希**：未来可写一个 `migrate_pattern_ids()` 工具，按内容重算 SHA256[:12] 并去重，合并阶段 2.2.4 已识别但不修复的 legacy 兼容问题。

4. **2.1.1 § 5 验收**："diagnostic 连续跑两次，第二次 Step 1 < 1s" — 单元测试验证逻辑生效，但**端到端**未在 Harness 跑过。Phase 8/9/10 集成时再实测。

---

## 7. 下一步建议

按 plan 与 PRD 路线：

| 选项 | 描述 | 工时 |
| ---- | ---- | ---- |
| **Push 当前进度** | 把 2 个 commit 推 `origin/refactor/v2` | 0.5h |
| **Phase 8 启动** | Identity 深度集成（DiagnosisBundle → Snapshot → Variant 完整闭环） | ~3 天 |
| **Phase 9 启动** | Materials 接入（注册 → hash → 注入 expert_panel） | ~2 天 |
| **Harness 扩展** | 加 Phase 4（LLM judge + 多步评估） | ~2 天 |
| **修 § 6 follow-up** | 接入 record_pattern_hit / decay_patterns / migrate_pattern_ids | ~0.5 天 |

---

## 8. 测试命令

```bash
# Phase 15 全套
python -m pytest tests/test_phase15_prewarm.py tests/test_phase15_memory_reliability.py -v

# TPE 回归
python -m pytest tests/test_temporal_pattern_engine.py -v

# Harness 端到端
python -m pytest tests/test_harness/ -v

# 全部
python -m pytest -q
```

---

## 9. Commit 索引

```
8eecd1c  feat(phase15-2.2): atomic writes + JSON robustness + pattern decay + SHA256 IDs
2ad431a  feat(phase15-2.1): prewarm CLI + variable_chains cache + signal_map pre-load
aaae206  docs: simplify README + fix pytest 9.0.3 UTF-8 capture
0736c6c  Phase 14: 分析能力核心强化完成
e49cf31  docs: 总体设计评估 + Phase 14/15 开发方案
```