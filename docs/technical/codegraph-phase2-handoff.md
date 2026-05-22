# CodeGraph Phase 2 — Handoff

> 分支: `refactor/codegraph`
> 完成: 2026-05-22
> 下一步: Phase 3 — 优化信号链追踪 + 专家面板集成

---

## 本阶段完成内容

### 1. _understand_problem 注入 CodeGraph

**文件**: `ai/orchestrator.py`

在 `_understand_problem` 方法中，source_summaries 之后注入 CodeGraph 渲染的 Markdown：

```python
codegraph_md = renderer.render_for_problem(func_name, problem, max_chars=3000)
```

Prompt 新增 `## 代码结构 (CodeGraph)` 段。失败静默 fallback。

**效果**: prompt tokens 从 ~2000 增至 4173，LLM 正确识别功能 + 关键变量。

### 2. variable_query_planner 优先查 CodeGraph

**文件**: `ai/variable_query_planner.py`

`_render_code_knowledge` 优先级：CodeGraph > L6 JSON。
- 先查 CodeGraph 获取 probe context + module-level 结构
- 回退到 legacy L6 JSON

### 3. condition_extractor 精确定位代码

**文件**: `ai/condition_extractor.py`

`_extract_with_ai` 改为双策略：
1. **CodeGraph 引导** — `_extract_with_codegraph(func_name)`:
   - 查 CodeGraph 定位该模块所有函数
   - 读取函数体（start/end line + context）
   - 包含 upstream callers（前 3 函数 x 2 callers）
2. **关键字匹配** — legacy `_extract_relevant_sections` 作为补充

### 4. 修复 Signal Interface (Phase 5)

**文件**: `ai/codegraph/analyzer.py`, `ai/codegraph/builder.py`, `config.yaml`

- 新增 `RteLite_Read_` / `RteLite_Write_` 正则（GWM_B26 格式）
- 头文件 (.h) 扫描整个文件提取信号声明
- `rteLite_PriCan.h` 加入 key_source_files
- `_insert_signal_edges` 修复外键约束 (func_name=None 不建 edge)

**效果**: 信号节点从 0 → 240

---

## 构建数据 (Phase 2)

| 指标 | Phase 1 | Phase 2 | 变化 |
|------|---------|---------|------|
| 文件 | 18 | 19 (+rteLite) | +1 |
| 总节点 | 1238 | 1381 | +143 |
| FUNCTION | 320 | 320 | - |
| SIGNAL | 0 | 240 | **+240** |
| VARIABLE | 797 | 797 | - |
| 总边 | 9897 | 9897 | - |
| 首次构建 | 5.4s | 6s | +0.6s |
| 增量跳过 | 15ms | 15ms | - |

---

## 端到端验证

测试命令：`Orchestrator(config, Path('.'))._understand_problem('FCTB没有触发', ...)`

**结果**:
- Function: FCTB (confidence 0.95)
- Fail type: 漏报 FN
- Key vars: fctbSystemState, fFctbActiveUpSpd, fFctbDetectLowSpd...
- Prompt tokens: 4173 (含 CodeGraph context)
- 用时: 56s (remote model)

---

## 已知问题

1. **READS_SIGNAL/WRITES_SIGNAL 边为 0** — RteComMapping.c 中信号调用被注释，头文件声明无 function 关联。需跟踪 RteLite_Read_Xxx 的实际调用者（在 .c 文件中展开宏后调用）。
2. **State Machine (Phase 6) 未捕获** — 正则需要适配实际代码格式。
3. **变量提取 false positives** — 797 个变量中包含普通局部变量，需过滤。

---

## Phase 3 计划

1. **专家面板集成** — `_expert_panel` prompt 注入 CodeGraph call chain + variable dependencies
2. **信号链追踪** — 从 BLF signal → RteLite declaration → C code usage 的完整链路
3. **variable_query_planner 用 CodeGraph 找变量** — 不再依赖 LLM 猜变量名，直接用 CodeGraph 返回该函数读写的所有变量
4. **优化 prompt token 预算** — CodeGraph context 目前 3000 chars，需根据总预算动态调整
