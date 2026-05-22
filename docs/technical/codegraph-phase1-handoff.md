# CodeGraph Phase 1 — Handoff

> 分支: `refactor/codegraph`
> 完成: 2026-05-22
> 下一步: Phase 2 — 在 LLM prompt 中开始消费 CodeGraph 数据

---

## 本阶段完成内容

### 新文件 (ai/codegraph/)

| 文件 | 行数 | 功能 |
|------|------|------|
| `__init__.py` | 10 | 包入口，导出 CodeGraphBuilder/CodeGraph/CodeGraphRenderer |
| `schema.py` | 142 | SQLite schema (7 节点表 + 12 边类型 + node_semantics + build_log + 索引) |
| `analyzer.py` | 560 | 静态分析引擎：10 个 Phase 的 regex-based C 代码分析 |
| `builder.py` | 616 | CodeGraphBuilder：增量构建、hash 比对、DB 持久化 |
| `query.py` | 567 | CodeGraph：查询 API（模块/函数/变量/信号/调用链/反向查询/自然语言搜索） |
| `render.py` | 360 | CodeGraphRenderer：4 种 prompt 渲染方法 |

### 修改文件

| 文件 | 改动 |
|------|------|
| `ai/orchestrator.py` | `_ensure_source_docs` 末尾调用 `_build_codegraph(status)`；新增 `_build_codegraph` 方法 |
| `cli.py` | 新增 `--codegraph-stats` 参数 + `_show_codegraph_stats()` 函数 |

### 构建结果

```
首次构建: 18 文件 → 1238 节点 (15 FILE + 320 FUNCTION + 797 VARIABLE + 98 CALIB_PARAM + 8 MODULE)
          9897 边 (396 CALLS + 7696 READS_VAR + 1341 WRITES_VAR + 144 BELONGS_TO + 320 FILE_INcludes)
          耗时: 5.4s
增量构建: 0 文件变化 → 跳过，耗时 0.015s
```

### 用户无感设计

- **不新增诊断命令** — CodeGraph 在 orchestrator Step 1 自动构建
- **错误完全静默** — 构建失败只记 debug log，不影响诊断流程
- **零行为变更** — 现有诊断输出完全一致，CodeGraph 数据尚未注入 LLM prompt

---

## 架构概览

```
orchestrator._ensure_source_docs()
    → CodeLearner.ensure_overview_docs()     # 原有: source_docs/{FUNC}.md
    → signal_mapper.extract_signal_mapping()  # 原有: signal_mapping.json
    → CodeGraphBuilder.build()                # 新增: memory/codegraph.db (静默)
```

Builder 流程:
1. Phase 1: 文件 hash 比对 → 确定 changed files
2. 如果无变化: 直接返回 skip (15ms)
3. 如果变化: purge changed files 的旧数据
4. Phase 2-10: 重新分析所有文件 (不仅 changed，因为 cross-reference 需要完整上下文)
5. 写入 SQLite + 更新 build_log

---

## 当前实现的 Phase

| Phase | 状态 | 说明 |
|-------|------|------|
| 1. File Index | ✅ | SHA-256 hash 比对，增量跳过 |
| 2. Function Extract | ✅ | 320 个函数，带行号/签名/返回值 |
| 3. Call Graph | ✅ | 396 条调用边 |
| 4. Variable Access | ✅ | 7696 读 + 1341 写变量边 |
| 5. Signal Interface | ✅ | Rte_Read/Write + ReadSignal/WriteSignal (本次构建为 0 条 — 因 RteComMapping.c 的函数未被提取为 FUNCTION) |
| 6. State Machine | ⚠️ | 正则已实现，但实际未捕获到状态转换 (可能 regex 需要调优) |
| 7. Module Binding | ✅ | 144 条 BELONGS_TO 边 |
| 8. Cross-Module | ⚠️ | query.py 已实现 get_shared_functions/signals，但无显式节点 |
| 9. Calibration Params | ✅ | 98 个参数从 paraDefine.h 等提取 |
| 10. Behaviour Patterns | ⚠️ | regex 已实现 (HoldRelease/Accumulate/EdgeTrigger)，但命中率低 |

---

## 已知问题 / 待优化

### 1. 信号边为 0

RteComMapping.c 中的函数可能没被正确提取。原因:
- `RteComMapping.c` 里的函数定义格式可能和现有 regex 不匹配
- 需要在 Phase 2 的函数提取 regex 上增加 AUTOSAR 风格的匹配

### 2. 状态转换未捕获

`_STATE_ASSIGN_RE` 和 `_STATE_SWITCH_RE` 可能太严格。实际代码中的状态赋值可能是:
```c
fctbSystemState = ACTIVE;
// 或
pFctbData->systemState = 2;
```
需要检查实际代码格式后调整 regex。

### 3. 行为模式命中率低

HoldRelease/Accumulate/EdgeTrigger 的正则在单行级别工作，但实际代码可能跨越多行。需要 multi-line regex 或 AST 级别分析。

### 4. 函数提取 false negatives

部分函数可能因返回值类型复杂（如 `T_Asw_Status`）未被匹配。需要扩展 `_looks_like_function` 的白名单。

### 5. 变量提取可能有 false positives

`_extract_all_var_accesses` 使用 `[fbn]\w+` 模式，会匹配到很多非关键变量。Phase 2 应该聚焦于：
- 信号相关变量（从 Rte 接口反推）
- 状态变量 (*SystemState)
- 关键标志位 (bFctb*, bRctb*, etc.)

---

## 下一步: Phase 2 — 让 LLM 消费 CodeGraph 数据

### 2.1 在 orchestrator 中注入 CodeGraph prompt

修改 `orchestrator._understand_problem()`:
```python
# 现有: 注入 source_docs/{FUNC}.md
# 新增: 注入 CodeGraph 结构化数据
from .codegraph import CodeGraph, CodeGraphRenderer
cg = CodeGraph(self.project_root / "memory" / "codegraph.db")
renderer = CodeGraphRenderer(cg)
codegraph_md = renderer.render_for_problem(module, problem)
# 注入到 prompt 中
```

### 2.2 在 probe phase 使用 CodeGraph

修改 `variable_query_planner._render_code_knowledge()`:
```python
# 优先从 CodeGraph 查精确的函数/变量关系
# fallback 到旧 JSON 文件
```

### 2.3 在 condition extraction 使用 CodeGraph

修改 `condition_extractor`:
```python
# 用 CodeGraph 精确找到相关代码行号范围
# 替代现有的 keyword 模糊过滤
```

### 2.4 修复 Phase 5 (Signal Interface)

调查 RteComMapping.c 的函数提取失败原因，修复后重新构建。

### 2.5 修复 Phase 6 (State Machine)

检查实际代码中的状态赋值格式，调整 regex。

---

## 文件清单

```
ai/codegraph/
  __init__.py          (10 lines)
  schema.py            (142 lines)
  analyzer.py          (560 lines)
  builder.py           (616 lines)
  query.py             (567 lines)
  render.py            (360 lines)

Modified:
  ai/orchestrator.py   (+44 lines: _build_codegraph method)
  cli.py               (+17 lines: --codegraph-stats)

Data:
  memory/codegraph.db  (~120KB SQLite, 1238 nodes, 9897 edges)
```
