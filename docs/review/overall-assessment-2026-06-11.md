# radarAnalyze v2.0 全局评审报告

**评审日期**: 2026-06-11  
**评审人**: Hermes Agent  
**基于代码状态**: `be94446` (feat: Phase 5B) + 未提交的 5D 管线重构

---

## 一、评审总览

| 维度 | 分数 (10分制) | 状态 |
|------|:---:|------|
| PRD 一致性 | 8.5/10 | ✅ 核心功能已实现，部分 PRD 项未落地 |
| 鲁棒性 | 7.5/10 | ⚠️ 错误处理到位，但存在边界条件风险 |
| 多项目适配 | 5/10 | 🔴 配置就绪但运行时有缓存 bug，CodeGraph 未适配 |
| 记忆机制 | 6/10 | 🔴 L4 Session Memory 未接入，知识消费不完整 |
| 知识沉淀 | 7/10 | ⚠️ auto-dream + CodeGraph 已实现，SIGNAL 映射为零 |

---

## 二、PRD 一致性检查

### 已实现 ✅

| PRD 要求 | 实现状态 | 说明 |
|----------|---------|------|
| 8步管线 | ✅ 完成 | Phase 5D 已重构 run_diagnosis 从 15→8 步 |
| 并行证据提取 | ✅ 完成 | Conditions + TPE 通过 ThreadPoolExecutor 并行 |
| 专家面板 (3轮) | ✅ 完成 | expert_panel.py 多专家辩论系统 |
| 多项目配置 | ⚠️ 部分 | config.yaml 有 projects 节，get_project 实现完整 |
| CLI -P 项目切换 | ✅ 完成 | cli.py line 106, 128 正确处理 |
| 变量过滤 (5B) | ✅ 完成 | should_include_variable + get_variable_filter |
| CodeGraph 语义标注 | ✅ 部分 | 255/1398 节点 (cold start)，剩余等 LLM |
| Context Budget | ✅ 完成 | orchestrator 中优先级排序 (semantics 73 > codegraph 72) |
| auto-dream 知识固化 | ✅ 完成 | auto_dream.py Phase 0-4 完整 |
| 时序模式引擎 (TPE) | ✅ 完成 | TemporalPatternEngine 完整实现 |
| 测试窗口检测 | ✅ 完成 | TestWindowDetector 多阈值支持 |
| 帧级分析 | ✅ 完成 | FrameAnalyzer extract_evidence |
| 变量探测 | ✅ 完成 | variable_query_planner + data_probe |
| 记忆系统 L1-L6 | ⚠️ 部分 | L4 缺失，见下文 |
| 抑制信号检查 | ✅ 完成 | _check_suppression_signals |
| 输出信号分析 | ✅ 完成 | _analyze_output_signals |

### 未实现 🔴

| PRD 要求 | 差距 | 优先级 |
|----------|------|--------|
| **SIGNAL→internal_var 映射** | **0/301 SIGNAL 有 internal_var** — 诊断硬伤 | **P0** |
| **L4 Session Memory 消费** | build_context_for_diagnosis 跳过 L4，60+ session 数据闲置 | **P0** |
| **CodeGraph 多项目隔离** | resolve_ 函数走 config["project"]，但 CodeGraph builder 只建了 gwm_b26，sc6h/cr5cb 无 DB | **P1** |
| **5C.5 LLM 语义标注** | 剩余 1143 节点等 API 密钥 | **P2** |
| **测试覆盖** | 仅 1 个测试文件 (test_temporal_pattern_engine.py) | **P2** |

---

## 三、多项目适配深度分析

### 3.1 架构设计 ✅ 合理

```
config.yaml:
  default_project: gwm_b26
  projects:
    gwm_b26: source_code, key_source_files(16), dbc_files(3)
    sc6h:    source_code, key_source_files(14), dbc_files(3)
    cr5cb:   source_code, key_source_files(0), dbc_files(0) ← 未配置

config.py:
  get_project() → 解析 source_docs_dir, memory_dir, codegraph_db_path
  resolve_codegraph_db() → config["project"]["codegraph_db_path"]
  resolve_source_docs_dir() → config["paths"]["source_docs"]
  resolve_memory_dir() → config["project"]["memory_dir"]
```

路径隔离已实现：
- `source_docs/gwm_b26/` — 15 个文件 ✅
- `memory/projects/gwm_b26/sessions/` — 有 session 数据 ✅
- `memory/codegraph/codegraph_gwm_b26.db` — 1398 节点 ✅
- `memory/projects/sc6h/project.md` — 仅 26 bytes ⚠️

### 3.2 运行时 Bug 🔴 _config_cache 缓存问题

**问题**: `cli.py` line 32-63 使用全局 `_config_cache`：

```python
_config_cache: dict | None = None

def load_config(project_key: str | None = None) -> dict:
    global _config_cache
    if _config_cache is None:   # ← 只检查 None，不检查 project_key 是否匹配
        ...
        _config_cache = cfg
    return _config_cache         # ← 返回缓存，忽略传入的 project_key
```

**影响**: 如果同一个进程先执行 `-P gwm_b26` 再执行 `-P sc6h`，第二次会错误返回 gwm_b26 的配置。

**严重程度**: 中等 — 正常使用是每次调用独立进程，但 batch 脚本或 cron job 可能触发。

**修复**: 缓存键应包含 `project_key`：
```python
_config_cache: dict[str, dict] = {}  # project_key -> config
def load_config(project_key: str | None = None) -> dict:
    from config import get_project, load_config as _load_base
    effective_key = get_project({}, project_key).get("_project_key", "")
    if effective_key not in _config_cache:
        cfg = _load_base(PROJECT_ROOT / "config.yaml")
        proj = get_project(cfg, project_key)
        # ... same injection logic ...
        _config_cache[effective_key] = cfg
    return _config_cache[effective_key]
```

### 3.3 CodeGraph 多项目差距

| 项目 | CodeGraph DB | source_docs | 语义标注 |
|------|-------------|-------------|---------|
| gwm_b26 | ✅ 1398 节点 | ✅ 15 文件 | ✅ 255 行 |
| sc6h | ❌ 无 DB | ❌ 无目录 | ❌ 无 |
| cr5cb | ❌ 无 DB | ❌ 无目录 | ❌ 无 |

CodeGraph builder (`code_learner.py`) 只跑了 gwm_b26。sc6h 和 cr5cb 需要分别执行构建流程。

### 3.4 sc6h 配置不完整

- `memory/projects/sc6h/project.md` 仅 26 bytes — 几乎为空
- cr5cb 的 `key_source_files` 和 `dbc_files` 都是 0 — 完全未配置

---

## 四、记忆机制评估

### 4.1 记忆层级架构

| 层级 | 名称 | 存储 | 写入 | 读取 | 状态 |
|------|------|------|------|------|------|
| L1 | 项目记忆 | memory/project.md | ✅ auto-dream | ✅ build_context | ✅ |
| L2 | 功能知识 | memory/functions/*.json | ✅ 诊断后 | ✅ build_context | ✅ |
| L3 | 模式知识 | memory/patterns.json | ✅ 诊断后 | ✅ find_similar_patterns | ✅ |
| L4 | Session 记忆 | memory/sessions/*.json | ✅ 每步 log | ❌ 未读取 | 🔴 |
| L5 | 案例记忆 | cases/*/memory.json | ✅ 诊断后 | ✅ read_case_memory | ✅ |
| L6 | 代码知识 | memory/code_knowledge/*.json | ✅ auto-dream | ✅ render_code_knowledge | ✅ |

### 4.2 L4 Session Memory 未消费 🔴

**事实**: `build_context_for_diagnosis` 收集了 L1、L2、L3、L5、L6，但 **L4 完全跳过**。

**数据量**: memory/sessions/ 下有 **60+ JSON 文件**，总计 ~500KB，包含完整的诊断步骤日志（understand → classify → parse → windows → evidence → conditions → tpe → probe → diagnose → report）。

**缺失价值**:
- 同一案例的多次诊断历史（FCTA001 有 18 次诊断记录）
- 不同案例间的模式对比（FCTB 有 15 次诊断记录）
- 诊断质量趋势分析

**建议修复**: 在 `build_context_for_diagnosis` 中添加 L4 检索：
```python
# L4 — Session Memory: 同一功能的历史诊断
sessions = self.find_sessions_for_function(func_name, limit=3)
if sessions:
    parts.append(f"## 历史诊断 ({len(sessions)} 次)")
    for s in sessions:
        root_cause = s.get("diagnose", {}).get("root_cause", "?")
        parts.append(f"- {s['created_at']}: {root_cause[:200]}")
```

### 4.3 find_similar_patterns 实际效果

L3 的 `find_similar_patterns` 基于 keywords 匹配 patterns.json（6.6KB），实际模式数量有限。patterns.json 中的条目质量取决于历史诊断的沉淀质量。建议配合 L4 session 数据做更丰富的相似度检索。

---

## 五、知识沉淀机制评估

### 5.1 CodeGraph — 已实现，但有硬伤

**优势**:
- 节点类型丰富：321 functions + 656 variables + 301 signals + 97 calibrations
- 边关系完整：4490 edges
- 语义标注 255 行（cold start 完成）
- 过滤机制有效：`should_include_variable` 排除 noise

**核心缺陷**:
1. **SIGNAL→internal_var 映射为 0/301** — 这是诊断的硬伤。TPE 需要 SIGNAL 对应 C 变量名才能做差距分析，当前完全无法关联。
2. **Legacy codegraph.db 未清理** — memory/codegraph.db (5.4MB) 是旧版本，与 codegraph_gwm_b26.db 并存但不再使用。

### 5.2 source_docs 结构

**多项目**: gwm_b26 有 15 个文件的独立 source_docs，包括完整的 function overview、signal_mapping、output_mapping。

**全局 source_docs**: 根目录下有 22 个通用文件（SC6H 时代的产物），与 gwm_b26 的内容大量重复。建议清理或标记为 deprecated。

### 5.3 auto-dream 知识固化

Phase 0-4 完整实现：
- Phase 0: Code scanning + AST 分析
- Phase 1: Function knowledge 更新
- Phase 2: Pattern 提取
- Phase 3: Constants 学习
- Phase 4: 代码知识固化到 L6

`dream_log.json` 显示已运行过。code_knowledge/ 下有 7 个功能的完整知识文件（FCTA 34KB 最大）。

---

## 六、鲁棒性评估

### 6.1 错误处理 ✅

- `safe_llm_call` 包装器 — LLM 调用有 fallback
- ThreadPoolExecutor — 并行任务隔离，单个失败不影响整体
- TPE 有 try/except — `_run_tpe` 不会因异常中断管线
- 窗口检测 fallback — 无窗口时使用完整数据

### 6.2 边界条件 ⚠️

| 风险 | 严重度 | 说明 |
|------|--------|------|
| LLM API 不可用 | 高 | `_understand_problem`、`condition_extractor`、`expert_panel` 都需要 LLM，无 LLM 时管线退化到什么程度？ |
| 数据文件缺失 | 中 | `.bag` 或 `.blf` 缺失时的优雅降级？ |
| CodeGraph DB 不存在 | 中 | resolve_codegraph_db 返回路径但不检查文件存在 |
| Config cache 冲突 | 中 | 见 3.2 |
| 8步管线步骤名不匹配 | 低 | CLI steps_display 仍包含旧步骤名（suppression、probe 等），与 8 步不一致 |

### 6.3 测试覆盖 🔴

**当前状态**: 仅 1 个测试文件 `test_temporal_pattern_engine.py`。

**缺失测试**:
- orchestrator 8 步管线集成测试
- 多项目配置解析测试
- 记忆系统读写测试
- CodeGraph schema 迁移测试
- CLI -P 参数测试

---

## 七、管线 8 步重构评估

### 7.1 重构质量 ✅

- 从 15 步合并为 8 步：init → classify → extract → evidence → signals → diagnose → fix → deliver
- 并行化：Conditions + TPE 在 evidence 步并行执行
- 代码结构清晰：每个步骤有明确注释和 status 调用
- 保持了向后兼容：旧 helper 方法（`_run_tpe`、`_check_suppression_signals` 等）复用

### 7.2 回归测试状态 ✅

FCTA001 回归测试于 2026-06-11 完成（耗时 888s）。Report 5561 bytes（baseline 6251 bytes），差异 -690 bytes 在合理范围内。所有 8 步管线步骤都成功执行，包括 fix 步骤（CodeFixEngine 正常集成）。

### 7.3 CLI steps_display 不一致 ⚠️

`cli.py` line 406-421 的 `steps_display` 仍包含旧步骤名（`suppression`、`probe`、`output_signals`、`expert_panel`），与新 8 步管线不匹配。虽然不影响功能（只是显示层），但会误导用户看到不存在的步骤状态。

---

## 八、优先级排序与行动建议

### P0 — 阻塞诊断质量

| # | 问题 | 工作量 | 说明 |
|---|------|--------|------|
| 1 | **SIGNAL→internal_var 映射 0/301** | 2-3h | 需要从 C 代码中追踪 Rte_Read/Rte_Write 调用，填充 SIGNAL 节点的 internal_var 字段 |
| 2 | **L4 Session Memory 未消费** | 30min | 在 build_context_for_diagnosis 中添加 L4 检索逻辑 |
| 3 | **config.yaml _config_cache bug** | 15min | 缓存键改为 project_key |

### P1 — 影响可用性和可靠性

| # | 问题 | 工作量 | 说明 |
|---|------|--------|------|
| 4 | **CodeGraph 多项目构建** | 1-2h | 为 sc6h 和 cr5cb 运行 codegraph builder |
| 5 | **cr5cb 配置补全** | 30min | 填入 key_source_files 和 dbc_files |
| 6 | **CLI steps_display 更新** | 10min | 对齐 8 步管线 |
| 7 | **Legacy codegraph.db 清理** | 5min | 删除或标记 deprecated |
| 8 | **全局 source_docs 去重** | 30min | 清理或标记 gwm_b26 之外的旧文件 |

### P2 — 质量提升

| # | 问题 | 工作量 | 说明 |
|---|------|--------|------|
| 9 | **5C.5 LLM 语义标注** | 等 API 密钥 | 剩余 1143 节点 |
| 10 | **测试覆盖** | 2-3h | orchestrator 集成测试、多项目测试 |
| 11 | **LLM 不可用时的降级模式** | 1h | 明确无 LLM 时的管线行为 |

---

## 九、项目是否走偏的判断

### 结论：没有明显走偏，核心方向正确

1. **诊断管线设计合理** — 8 步管线覆盖从数据解析到报告生成的完整流程，并行化优化也到位。
2. **多项目架构正确** — `projects:` 配置 + `get_project()` + resolve 函数的设计是合理的，只是运行时缓存和多项目构建还没跟上。
3. **记忆系统方向对** — L1-L6 分层设计合理，但 L4 的缺失是一个编码疏漏，不是设计问题。
4. **CodeGraph 有价值但有硬伤** — SIGNAL 映射为零是当前最大短板，直接导致差距分析无法做。
5. **知识沉淀机制完善** — auto-dream + code_learner 形成了学习→固化的闭环。

### 主要风险

- **SIGNAL 映射为零**是 P0 级问题，不解决这个，诊断质量天花板很低。
- **LLM API 依赖过重** — understand、classify、conditions、probe、expert_panel 5 个步骤需要 LLM，API 不可用时管线基本瘫痪。需要一个明确的降级策略。
- **测试覆盖不足** — 当前仅 1 个测试文件，重构后缺乏安全网。

---

## 十、评分汇总

| 维度 | 评分 | 趋势 | 说明 |
|------|:---:|:---:|------|
| PRD 一致性 | 8.5/10 | ↗️ | 核心功能实现，L4 和 SIGNAL 映射是缺口 |
| 鲁棒性 | 7.5/10 | → | 错误处理到位，LLM 降级缺失 |
| 多项目适配 | 5/10 | ↗️ | 架构正确，运行时和构建待完善 |
| 记忆机制 | 6/10 | ↓ | L4 缺失是退步，应修复 |
| 知识沉淀 | 7/10 | → | CodeGraph 有价值，SIGNAL 映射为零拉低分数 |
| **综合** | **6.8/10** | ↗️ | 方向正确，P0 项解决后可达 8+ |

---

## 十一、2026-06-11 深度验证补充（第二次评审）

> 基于代码级源码审查，验证评审报告中的每一项结论是否准确。

### 11.1 SIGNAL 映射验证 — 确认 P0 严重性

**验证结果**: 301 个 SIGNAL 节点，`internal_var` 全部为 `'None'`（字符串，不是 SQL NULL），`rte_read_fn` / `rte_write_fn` 全为 `None`。

**影响分析**:
- 诊断管线中的 "差距分析" 需要 BLF signal → C 变量的映射链路
- 当前无法从 CAN signal 值追溯到代码中的变量，也无法从代码条件反查 BLF 数据
- **这是诊断质量的天花板问题** — 即使 Expert Panel 推理再强，缺少这条链路就无法做"数据 vs 代码期望"的对比

### 11.2 _config_cache 验证 — 确认多项目切换有 bug

**发现**: `cli.py` 的 `load_config(project_key)` 使用全局 `_config_cache`，第一次调用后所有后续调用（即使不同 project_key）都返回缓存的 config。

**影响**: 在同一个 Python 进程中运行不同项目的诊断会混用配置。CLI 每次启动是新进程所以不受影响，但如果未来有 Web API 或长驻进程，这是隐患。

### 11.3 Expert Panel — 确认三轮辩论已实现

**验证**: `expert_panel.py` 有 `ROUND_COUNT = 3`，实现了：
- Round 1: 专家并发独立分析
- Round 2: 交叉审查 + 质疑
- Round 3: 综合收敛
- 使用 `ThreadPoolExecutor` 并行化，`MAX_PARALLEL = 5`

**结论**: 专家面板实现完整，之前的评估 "single round" 是误判（grep 关键词不匹配）。

### 11.4 CodeFixEngine — 存在但未集成到管线

**发现**: `ai/code_fix_engine.py` 存在，orchestrator 的 `fix` 步骤调用了它。
**验证**: orchestrator L636-648 有 `status("fix", ...)` 调用，说明 CodeFixEngine 已集成。

### 11.5 resolve_* 函数多项目支持 — 确认部分可用

**验证结果**:
- `get_project(config, project_key)` ✅ 完整实现，返回 per-project 配置
- `resolve_codegraph_db(config, project_root)` ⚠️ 读取 `config.get("project", {})`，依赖 `cli.py` 的 `load_config` 注入
- `resolve_source_docs_dir(config, project_root)` ⚠️ 读取 `config.get("paths", {}).get("source_docs")`，依赖注入
- `resolve_memory_dir(config, project_root)` ⚠️ 同上

**结论**: resolve 函数本身没有问题，问题是它们依赖 `cli.py` 的 `load_config` 先把 project 数据注入 `config` dict。这意味着 orchestrator 必须通过 cli.py 创建，不能直接用 config 模块创建。当前架构可行但不优雅。

### 11.6 8 步管线 — CLI steps_display 不一致

**确认**: `cli.py` L406-421 的 `steps_display` 字典包含 15 个旧步骤名，而 orchestrator 只输出 8 个新步骤名。用户看到的 status 输出仍然是新步骤名（来自 orchestrator），只是部分步骤在 `steps_display` 中找不到映射，会直接显示原始步骤名。**实际影响很低**。

### 11.7 测试覆盖 — 确实只有 1 个测试文件

**验证**: `tests/test_temporal_pattern_engine.py` 是唯一测试。`test_8step_pipeline.py` 是临时回归脚本，不在正式测试目录中。

### 11.8 PRD 合规度逐项核对

| PRD 需求 | 状态 | 备注 |
|----------|------|------|
| FR-001: 多项目配置化 | ✅ 80% | 架构正确，sc6h/cr5cb 缺 CodeGraph 构建 |
| FR-002: 变量过滤 | ✅ 完成 | 656 变量，过滤逻辑已实现 |
| FR-003: 语义层填充 | ✅ 50% | 冷启动 255 行，LLM 标注等 API 密钥 |
| FR-004: 管线精简 15→8 | ✅ 完成 | 8 步全部实现，并行化到位 |
| FR-005: ContextBudget 动态 | ⬜ 未开始 | 仍为固定 60K |
| FR-006: 记忆 6→3 简化 | ⬜ 未开始 | 仍为 6 层 |
| FR-007: 降级策略 | ⚠️ 部分 | 有 fallback 但无系统性降级文档 |
| FR-008: MF4 Parser | ⏸️ Deferred | asammdf 不可用，推迟合理 |
| SIGNAL 映射链路 | 🔴 0% | P0 — 301/301 信号未映射 |
| L4 Session Memory 消费 | 🔴 0% | P1 — 写入正常，读取缺失 |

### 11.9 最终判断

**项目没有走偏**，核心设计符合 PRD。主要问题是：

1. **SIGNAL 映射是硬伤** — 这是诊断管线的基础设施，不补上就无法做差距分析
2. **P1 项堆积** — 记忆简化、动态 ContextBudget、CLI 显示更新都是低工作量但影响用户体验的项
3. **测试安全网缺失** — 重构后没有回归测试保护，下次改管线可能引入回归

**建议下一步**: 先攻克 P0（SIGNAL 映射），然后批量清理 P1。PRD 一致性从 8.5 提升到 9.0+ 不需要大改，只需补这几个缺口。
