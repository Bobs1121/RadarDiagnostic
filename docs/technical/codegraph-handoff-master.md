# radarAnalyze — Master Handoff

> 更新: 2026-06-08 (v2.0 Phase 2 P2.1+P2.2 完成 — tree-sitter AST 解析器 + AST Builder)
> 分支: `refactor/codegraph` (v1), `refactor/v2` (v2 改造 — Phase 1+2 部分完成)
> 状态: v2 Phase 1 完成; Phase 2 AST 基础设施完成，待集成 CodeGraph Builder

---

## 项目定位

AI 驱动的角雷达 ADAS 诊断系统。输入：问题描述 + 案例数据 (BAG + BLF + MF4)。输出：根因诊断 + 可执行的源码修改方案 (diff)。

**核心价值**: 把"人看 BLF 波形 + 看 C 代码"这个过程自动化 → 自动诊断根因 → 自动给出代码修改方案。

### 产品目标 vs 当前状态

| 需求 | 状态 | 说明 |
|------|------|------|
| 输入 BAG | ✅ | 已实现 |
| 输入 BLF | ✅ | 已实现 |
| 输入 MF4 | ❌ | 缺失 (Phase A) |
| 诊断根因 | ✅ | 5 专家 × 3 轮辩论 |
| 给出代码修改方案 | ⚠️ | 仅有文字建议，无 diff (Phase B) |
| 修改效果预估 | ⚠️ | 仅参数级支持 (Phase C) |
| 交互追问 | ❌ | 缺失 (Phase D) |

---

## 当前状态

### ✅ 已完成

| 项目 | 状态 | 说明 |
|------|------|------|
| 基础管线 15 步 | ✅ | 诊断/Query/Dream 三种模式 |
| 数据解析层 | ✅ | BAG/BLF/DBC → SQLite FrameStore |
| TPE 时序模式引擎 | ✅ | 6 类行为模式 + 因果对齐 |
| 专家面板 | ✅ | 5 专家 × 3 轮辩论 |
| 6 层记忆系统 | ✅ | L1-L6 跨会话知识持久化 |
| CodeGraph Phase 1 | ✅ | SQLite 图谱 (1381 节点, 9897 边) |
| CodeGraph Phase 2 | ✅ | LLM 消费 CodeGraph 数据 |
| Coder 模型路由 | ✅ | qwen3-coder:30b @ 10.190.161.39:8080 |
| **v2 Phase 1: MF4 Parser** | ✅ | 框架 + stub (asammdf 不可用) |
| **v2 Phase 1: Topic 自动发现** | ✅ | `discover_radar_topics()` |
| **v2 Phase 1: 降级策略** | ✅ | `safe_llm_call` + 6 个 fallback |
| **v2 Phase 1: 可观测性** | ✅ | `StepLogger` + `observability_log.json` |
| **v2 Phase 2: AST Parser** | ✅ | `ast_parser.py` — tree-sitter C 解析 wrapper (0.21.3) |
| **v2 Phase 2: AST Builder** | ✅ | `ast_builder.py` — AST → CodeGraph 节点/边转换器 |

### 🔧 进行中 / 待优化

| 项目 | 优先级 | 说明 |
|------|--------|------|
| AST Parser → CodeGraph 集成 | P1 | `ast_builder.py` 已写好但尚未替换 `builder.py` 中的正则分析器 |
| CodeGraph Phase 3 | P1 | 专家面板注入 + 信号链追踪 |
| 信号链边 (READS/WRITES) | ✅ | RteComMapping 正则补全, 边 0→463 |
| State Machine (Phase 6) | P2 | 状态转换正则未匹配 |
| 变量 false positives | P2 | 797 变量含普通局部变量 |
| 专家面板 CodeGraph 集成 | P1 | prompt 注入 call chain + var deps |
| CodeGraph prompt token 预算 | P2 | 动态调整 3000 chars |

---

## 需求池

### 高优先级 (用户直接反馈)

1. ~~**信号链追踪**: BLF signal → RteLite declaration → C code usage 完整链路。~~ **✅ 已修复** — 新增 `_RTE_MAPPING_READ_RE` / `_RTE_MAPPING_WRITE_RE` 正则匹配 `RteComMapping_ReadSignal/WriteSignal` 宏调用。SIGNAL 节点 240 → 426, READS_SIGNAL 0 → 140, WRITES_SIGNAL 0 → 323。

2. **专家面板用 CodeGraph**: 目前 5 个专家只看 textual evidence。需要注入结构化代码关系（函数调用链、变量依赖、信号映射），让根因分析更精确。

3. **Prompt token 优化**: CodeGraph context 目前固定 3000 chars，需要按总预算动态调整（context_budget 已有但没和 CodeGraph 联动）。

### 中优先级 (架构优化)

4. **变量过滤**: 797 个变量中大量是局部循环变量 (i, j, tmp...)。需要过滤出有意义的变量（全局变量、静态变量、RTE 读写变量）。

5. **State Machine 提取**: Phase 6 正则未匹配实际代码格式。需要看 GWM_B26 的实际状态机写法后调正则。

6. **CodeGraph 语义层**: 目前语义表 (`semantic_annotations`) 是空的。这是 Phase 4 的计划 — 让 LLM 给关键函数/变量写语义标注，存入 DB。

### 低优先级 (锦上添花)

7. **多平台支持**: 目前只分析 GWM_B26。BYD_SC6H / BYD_UKE 的 CodeGraph 共享 schema 但数据不同。需要 platform_tag 隔离。

8. **CodeGraph Web UI**: 交互式图谱浏览（D3 / cytoscape）。

9. **自动测试覆盖**: CodeGraph analyzer 的 10 个 phase 都需要单元测试。

---

## 架构决策记录

### ADR-001: CodeGraph 作为 Underlay 而非 Replacement

**决策**: CodeGraph 存储精确的结构关系（SQLite），现有 JSON 文件 (code_knowledge, signal_mapping 等) 作为上层视图保留。

**理由**: 
- 渐进式替换风险低
- JSON 文件含 LLM 提取的语义信息，不能丢
- SQLite 做精确查询，JSON 做语义补充

### ADR-002: 用户无感设计

**决策**: 不新增 CLI 命令，CodeGraph 在 orchestrator Step 1 静默构建。

**理由**: 
- 用户只关心诊断结果
- 静默失败不影响现有流程
- 调试用 `--codegraph-stats` 就够了

### ADR-003: 双模型路由 + Coder 专用

**决策**: Qwen3.5-27B 负责推理/规划，qwen3-coder:30b 负责编码。严格限制 coder 的 max_tokens ≤ 2000。

**理由**:
- 单 GPU 跑满，KV cache 宝贵
- coder 响应慢 (13 tok/s)，需要控制 token 量
- 编码任务不需要 thinking 模式

### ADR-004: tree-sitter AST 替代正则 (原 Regex 而非 AST)

**决策**: v2.0 阶段使用 tree-sitter (0.21.3) + tree-sitter-c (0.21.4) 解析 C 代码，替代正则表达式。
`ast_parser.py` + `ast_builder.py` 提供 AST → CodeGraph 节点的完整转换链路。

**理由**:
- 正则在复杂嵌套括号、多层指针声明、宏调用场景下准确率不足
- tree-sitter 提供精确的语法树，函数/结构体/调用/宏展开均可准确定位
- 速度可接受（单个文件 < 10ms）
- tree-sitter 0.24+ PyCapsule 与 Python 绑定不兼容，0.21.3 + 0.21.4 是唯一稳定组合

**实现**:
- `ai/codegraph/ast_parser.py`: CParser 类 — 9 个提取器 (functions, includes, structs, macros, variables, calls, signals, states, var_writes)
- `ai/codegraph/ast_builder.py`: ASTBuilder 类 — 将 AST 结果转换为 CodeGraph 节点/边 dict
- 两个模块完全独立于现有 `analyzer.py`，可随时开关

**注意事项**:
- `ai/__init__.py` 导入链依赖 `openai.OpenAI`，测试时需 mock
- `_walk_subtree` 使用 `node.walk()` API (0.21.x)，与 0.24+ 的 `TreeCursor` 不兼容
- `function_declarator` 类型在 0.21.x 中独立于 `declarator`，需要分别处理

---

## Git 提交历史 (refactor/codegraph)

```
0667f3d fix(codegraph): 补全信号链边 - RteComMapping ReadSignal/WriteSignal
14575ad docs: 数据流分析 + 架构评估 + master handoff 更新
1cf9947 feat: 产品开发 skill + master handoff
441ed4f docs: CodeGraph Phase 2 handoff
fab3481 feat: CodeGraph Phase 2 - LLM 消费代码知识图谱
94c3367 feat: 添加 coder 模型路由 (qwen3-coder:30b)
001ae34 chore: .gitignore - 排除构建产物和缓存文件
6132312 feat: CodeGraph Phase 1 - 确定性代码知识图谱基础设施
```

---

## 相关文档索引

| 文档 | 说明 |
|------|------|
| `PRD_refactor_v2.md` | **v2.0 改造 PRD** — 第一性原理架构重构规划 |
| `IMPLEMENTATION_PLAN_v2.md` | **v2.0 实施规划** — 5 Phase / 30 天实施路线 |
| `data-flow-and-architecture-assessment.md` | 数据流完整分析 + 鲁棒性评估 + 实施路线图 (v1) |
| `codegraph-phase2-handoff.md` | CodeGraph Phase 2 交付 |
| `codegraph-phase1-handoff.md` | CodeGraph Phase 1 交付 |
| `codegraph-handoff-v2.md` | CodeGraph 完整设计 (schema/query/render) |
| `00-总览.md` ~ `09-记忆系统.md` | 各模块架构文档 |

---

## v2.0 改造概览 (2026-06-08)

**触发原因**: 第一性原理审计 + GitHub 开源项目调研 (15 个项目)，发现以下结构性问题:

1. **LLM 链路过长**: 8-12 次串行调用 → 目标 5-7 次
2. **正则解析 C 代码**: 覆盖率有限 → 迁移到 tree-sitter AST 解析
3. **手写专家面板**: 686 行代码编排 5 专家 3 轮 → 迁移到 LangGraph
4. **管线步骤过多**: 15+ 步 → 精简到 8 步
5. **无代码修改能力**: 只能文字建议 → 新增 CodeFixEngine 生成 diff
6. **无 MF4 支持**: 大量测量数据不可用 → 新增 Mf4Parser

**核心改造方向**:

| 方向 | 技术方案 | 借鉴项目 |
|------|---------|---------|
| 代码分析升级 | tree-sitter AST 解析 | tree-sitter/tree-sitter (25.7k star) |
| 专家面板重构 | LangGraph 状态图编排 | langchain-ai/langgraph (34.1k star) |
| 数据解析加固 | mffparser (MF4) + topic 自动发现 | — |
| 代码修复引擎 | coder LLM + CodeGraph 定位 + diff 生成 | — |
| 时序异常检测 | 可选引入 pyod/adtk | pyod (9.9k star), adtk (1.2k star) |
| 可视化增强 | 参考 CANviz 交互波形图 | CANviz (260 star) |

**实施路线 (5 Phase / 30 天)**:
- Phase 1: 基础层加固 (MF4 + topic 发现 + 降级 + 可观测) — 5 天
- Phase 2: tree-sitter 代码分析 (AST 解析 + CodeGraph + 模式提取) — 10 天
- Phase 3: LangGraph 专家面板 (状态图 + 节点迁移 + prompt 外部化) — 5 天
- Phase 4: CodeFixEngine (diff 生成 + 安全审查 + 效果预估) — 5 天
- Phase 5: 管线精简 (15→8 步) + 记忆简化 (6→3 层) + 回归测试 — 5 天

详见 `docs/PRD_refactor_v2.md` 和 `docs/IMPLEMENTATION_PLAN_v2.md`。

---

## Git 提交历史 (refactor/v2)

```
f949baa feat(codegraph): integrate tree-sitter AST builder into builder.py (Plan A)
a204863 feat(v2): Phase 1 基础层加固 — MF4 stub + topic auto-discovery + fallback + observability
```

(基于 refactor/codegraph: 0667f3d)

---

## 相关文档索引

1. 读这个 handoff 了解当前状态
2. 读 `docs/PRD_refactor_v2.md` 了解 v2 改造规划
3. 读 `docs/IMPLEMENTATION_PLAN_v2.md` 了解实施步骤
4. 根据需求池/v2 规划决定下一步工作
5. 工作完成后更新本 handoff 的"当前状态"和"Git 提交历史"

**下一步工作**:
- **P2.4**: 在真实项目 (BYD_OVS_CB / GWM_B26) 上对比 AST vs 正则的准确率
- 或继续 v1 迭代 (CodeGraph Phase 3 / CodeFixEngine 设计)

**Phase 1 遗留问题**:
- MF4 Parser 需要 asammdf 或 mffparser 依赖库 (当前网络环境不可用)
- 安装依赖后需要补全 _parse_mf4_metadata / _parse_mf4_frames 实现
- observability 的 TokenTracker 已在 orchestrator 创建但未注入 model_router，后续需联动

**Phase 2 进度更新**:
- P2.1 ✓ tree-sitter C 语言包安装 + 路径解决
- P2.2 ✓ ast_parser.py (9 个提取器) + ast_builder.py (AST → CodeGraph 转换) + 单元测试
- P2.3 ✓ builder.py 集成 ASTBuilder，use_ast=True/False 开关式迁移
  - AST 分支已覆盖: Phase 2-3, 5-7, 9
  - 仍用正则: Phase 4 (variable access on known vars), Phase 10 (behaviour patterns)
  - AST 结果通过 self._ast_results_by_file 共享给各 extract 方法
- tree-sitter 0.24+ 版本 (PyCapsule) 与 0.21.x (Language 对象) API 不兼容，已锁定 0.21.3 + 0.21.4

**重要**: 每次对话结束前，更新本文件的"当前状态"和"需求池"。这是跨会话协作的唯一可靠通道。
