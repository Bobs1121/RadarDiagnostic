# radarAnalyze v2 — 后续开发计划（2026-06-14）

> 基准: PRD v2.1.1, codegraph-handoff-master.md (综合评分 8.5/10)
> 状态: Phase 1-6D + Harness Phase 1-3 + ADR-018~020 已完成
> 当前分支: `refactor/v2`
> 编写时间: 2026-06-14

---

## 0. 现状快照

### 已完成的

| 领域 | 完成项 |
|------|--------|
| 基础架构 | 8 步管线、变量过滤 (797→656)、SIGNAL 100% (301/301) |
| 多项目 | config.yaml identity hierarchy、CodeGraph/memory/source_docs 按项目隔离 |
| CLI | --variant/--package-profile/--snapshot 参数上线 |
| 核心模型 | DiagnosisBundle (561 行)、identity.py (551 行)、materials.py (441 行)、snapshot_store.py (87 行) |
| 专家面板 | LangGraph 5 专家 x 3 轮、prompt 外部化、project_key 透传 |
| 语义层 | SemanticAnnotator 框架 + cold_start (12 annotations) + cache |
| Harness | L0 (16 项) + L1 (证据链) + L2 (baseline + LLM judge 可选)、6 个 GT、聚合报告 |
| 记忆 | 6 层 CRUD、L4 读写闭环、诊断→L6 知识沉淀闭环 |
| 优化 | ContextBudget 动态计算、依赖分档 (base/llm/panel/harness)、记忆简化 6→3 (兼容层) |
| 测试 | 153 个 (42 passed, 1 skipped, 2 xfailed) |
| 文档 | PRD + 实施计划 + handoff (1660 行) + ADR x20 + 各模块 AGENTS.md |

### 核心缺口（按影响排序）

| # | 缺口 | 影响 | 优先级 |
|---|------|------|--------|
| 1 | **sc6h/cr5cb 无真实诊断案例** | Harness 6 案例中 5 个来自 gwm_b26，sc6h 仅 1 个（还 FAIL），cr5cb 为零 | **P0** |
| 2 | **专家面板 prompt 仍硬编码文件路径** | `adasFunc.c`、`ASWIN_SystemState.c`、`coem/GWM_B26` 等写死在 expert_panel_langgraph.py 和 prompt 中 | **P0** |
| 3 | **项目级 prompt 覆写目录为空** | gwm_b26/sc6h/cr5cb 目录已创建但无任何 .md 文件 | **P0** |
| 4 | **identity 模型未贯穿管线** | DiagnosisBundle/snapshot/materials 已集成 orchestrator，但 orchestrator 主线仍用 project_key，未用 Variant/PackageProfile | **P1** |
| 5 | **5C 语义层 LLM 全量标注 BLOCKED** | SemanticAnnotator 就绪，但需要 LLM API 配额 | **P1 (BLOCKED)** |
| 6 | **Materials 材料接入未实现** | MaterialRegistry/StructuredRequirementSet schema 已定义，但未接入诊断管线 | **P1** |
| 7 | **CodeGraph sc6h/cr5cb 未构建** | 只有 gwm_b26 有完整 CG；sc6h/cr5cb 首次诊断才现场构建 | **P1** |
| 8 | **Harness GT 样本不足** | 6 个 GT 但覆盖不均（gwm_b26:5, sc6h:1, cr5cb:0）；缺少 DOW/LCA 功能 | **P1** |
| 9 | **Memory 数据量稀少** | gwm_b26 仅 2 session + 1 function + 1 patterns.json | **P2** |
| 10 | **MF4 parser 仍为 stub** | asammdf 内网不可安装 | **Deferred** |

---

## 1. Phase 7: 真实端到端打通（P0 — 最关键）

**目标**: 在 sc6h 和 cr5cb 项目上各跑通至少 2 个真实诊断案例，产出完整报告。

**为什么优先**: 所有代码写得再好，没有真实案例验证就是空中楼阁。当前 Harness 6 案例中 5/6 来自同一项目，sc6h 的 1 个还 FAIL 了。

### 7.1 sc6h 项目诊断打通（2-3 天）

| # | 任务 | 产出 | 工时 |
|---|------|------|------|
| 7.1.1 | 确认 sc6h CodeGraph 构建 | `memory/codegraph/codegraph_sc6h.db`，变量过滤后节点数 | 0.5 天 |
| 7.1.2 | 准备 2-3 个 sc6h 案例数据 | cases/sc6h_fcta_*/（BLF + 问题描述） | 0.5 天（需用户提供数据） |
| 7.1.3 | 编写 sc6h 专家面板 prompt | `prompts/expert_panel/experts/sc6h/*.md` 覆写 | 0.5 天 |
| 7.1.4 | 运行完整诊断 | `python cli.py --variant gen6/sc6h cases/sc6h_fcta_001` | 0.5 天 |
| 7.1.5 | Harness GT 编写 + 评估 | `harness/golden_truths/sc6hfcta001_gt.json` | 0.5 天 |
| 7.1.6 | 修复诊断中的 bug | 根据 7.1.4 发现的问题修复 | 0.5 天 |

**验收标准**:
- sc6h 项目 2 个案例诊断成功，报告结构完整
- Harness 评估 L0 >= 0.90
- sc6h 专家面板 prompt 覆写到位（不引用 gwm_b26 路径）

### 7.2 cr5cb 项目诊断打通（3-4 天）

| # | 任务 | 产出 | 工时 |
|---|------|------|------|
| 7.2.1 | 确认 cr5cb CodeGraph 构建 | `memory/codegraph/codegraph_cr5cb.db` | 0.5 天 |
| 7.2.2 | 确认 cr5cb 关键源文件配置 | config.yaml variants/cr5cb scope 正确 | 0.5 天 |
| 7.2.3 | 准备 2 个 cr5cb 案例数据 | cases/cr5cb_fcta_*/（BLF + 问题描述） | 0.5 天（需用户提供数据） |
| 7.2.4 | 编写 cr5cb 专家面板 prompt | `prompts/expert_panel/experts/cr5cb/*.md` 覆写 | 0.5 天 |
| 7.2.5 | 运行完整诊断 | `python cli.py --variant gen5/cr5cb cases/cr5cb_fcta_001` | 0.5 天 |
| 7.2.6 | Harness GT 编写 + 评估 | `harness/golden_truths/cr5cbfcta001_gt.json` | 0.5 天 |
| 7.2.7 | 跨项目对比分析 | gwm_b26 vs sc6h vs cr5cb 同功能诊断差异 | 0.5 天 |

**验收标准**:
- cr5cb 项目 2 个案例诊断成功
- Harness 评估 L0 >= 0.90
- 3 项目各至少 2 个 GT 案例

### 7.3 专家面板 prompt 去硬编码（1 天）

**当前问题**: `expert_panel_langgraph.py` 中多处硬编码：
- `adasFunc.c`（line 206, 338）
- `ASWIN_SystemState.c`（line 238）
- `coem\GWM_B26\components\...`（line 208, 242）
- `orchestrator.py` 中（line 53, 566）

**改造方案**:
1. expert_panel_langgraph.py 中的专家定义改为从 `config + CodeGraph` 动态读取
2. 专家 domain 描述通过 `{{architecture_desc}}` 占位符注入
3. 关键文件列表从 `variant.file_hints.key_source_files` 读取
4. orchestrator.py 中的架构描述改为动态生成

| # | 任务 | 产出 | 工时 |
|---|---|------|------|
| 7.3.1 | expert_panel_langgraph.py 专家定义动态化 | 从 config/CodeGraph 读取 expert 配置 | 0.5 天 |
| 7.3.2 | orchestrator.py 架构描述动态化 | 不再硬编码文件路径 | 0.5 天 |

**验收标准**:
- expert_panel_langgraph.py 中不含 `adasFunc.c`、`ASWIN_SystemState.c`、`GWM_B26` 等硬编码字符串
- 任一 project_key 下不需要修改 prompt 文件即可运行

---

## 2. Phase 8: Identity 模型深度集成（P1 — 架构完整性）

**目标**: 让 variant/package_profile/snapshot 身份模型贯穿整个诊断管线，取代 legacy project_key。

### 8.1 Orchestrator 身份升级（1-2 天）

**当前状态**: orchestrator 接收 `project_key`，但核心模块已支持 identity。需要桥接。

| # | 任务 | 产出 | 工时 |
|---|---|------|------|
| 8.1.1 | orchestrator 接收 Variant 对象 | `_run_diagnosis()` 参数从 project_key 变为 Variant | 0.5 天 |
| 8.1.2 | snapshot 自动创建 | diagnosis 开始时自动生成 snapshot_id | 0.5 天 |
| 8.1.3 | DiagnosisBundle 绑定 snapshot | bundle.snapshot_id 可追溯 | 0.5 天 |
| 8.1.4 | 向后兼容层 | -P project_key 仍可用，自动映射到 variant | 0.5 天 |

### 8.2 Memory 目录迁移（1 天）

| # | 任务 | 产出 | 工时 |
|---|---|------|------|
| 8.2.1 | memory/projects/{key}/ → memory/variants/{variant_id}/ | 迁移脚本 + 代码更新 | 0.5 天 |
| 8.2.2 | source_docs/{key}/ → source_docs/variants/{variant_id}/ | 迁移脚本 + 代码更新 | 0.5 天 |

### 8.3 CLI 身份默认化（0.5 天）

| # | 任务 | 产出 | 工时 |
|---|---|------|------|
| 8.3.1 | --variant 成为首选入口 | help 文案更新，default_variant 驱动 | 0.3 天 |
| 8.3.2 | -P 标记为 [LEGACY] | deprecation warning | 0.2 天 |

**验收标准**:
- 新诊断默认使用 variant_id，不依赖 project_key
- 旧 `-P` 调用仍可运行（deprecation warning）
- 每次诊断产出 DiagnosisBundle 绑定 snapshot_id

---

## 3. Phase 9: Materials 材料接入（P1 — 诊断质量提升）

**目标**: 客户需求材料（DBC、功能说明、状态机、阈值表）结构化后注入诊断管线。

### 9.1 DBC 解析与信号约束提取（1-2 天）

**当前状态**: `parsers/dbc_parser.py` 已有基础，`cantools` 已安装。

| # | 任务 | 产出 | 工时 |
|---|---|------|------|
| 9.1.1 | DBC → SignalConstraint 结构化 | 信号名、范围、单位、物理含义 | 0.5 天 |
| 9.1.2 | DBC 注册到 MaterialRegistry | material_id + hash | 0.5 天 |
| 9.1.3 | SignalConstraint 注入 expert panel prompt | 诊断时可参考信号约束 | 0.5 天 |

### 9.2 功能说明文档接入（1-2 天）

| # | 任务 | 产出 | 工时 |
|---|---|------|------|
| 9.2.1 | PDF/MD → RequirementSpec 解析 | `core/materials.py` 扩展解析器 | 0.5 天 |
| 9.2.2 | 状态机描述 → StateMachineConstraint | 从文档中提取状态机定义 | 0.5 天 |
| 9.2.3 | 阈值表 → ThresholdRule | Excel/YAML → 结构化规则 | 0.5 天 |
| 9.2.4 | 材料注入 diagnose step | prompt 中包含权威材料约束 | 0.5 天 |

### 9.3 Material Registry 完善（0.5 天）

| # | 任务 | 产出 | 工时 |
|---|---|------|------|
| 9.3.1 | MaterialRegistry CLI 命令 | `rsim material add/list/remove` | 0.3 天 |
| 9.3.2 | version/hash 追踪 | material 变更自动触发 snapshot 更新 | 0.2 天 |

**验收标准**:
- 支持 DBC/MD/PDF 材料导入
- 材料结构化后可在诊断中引用
- 材料变更可追溯（hash + version）

---

## 4. Phase 10: Harness 评估体系扩展（P1 — 质量量化）

**目标**: 从 6 个 GT（gwm_b26 5 个）扩展到 12+ 个 GT，覆盖 3 项目 x 4 功能。

### 10.1 GT 目标矩阵

| 项目 | FCTA | FCTB | BSD/LCA | DOW | RCTA/RCTB | 小计 |
|------|------|------|---------|-----|-----------|------|
| gwm_b26 | ✅2 | ✅2 | ✅1 | 0 | 0 | 5 (已有) |
| sc6h | 2 | 1 | 0 | 0 | 1 | 4 (新增) |
| cr5cb | 1 | 1 | 1 | 1 | 0 | 4 (新增) |
| **合计** | **5** | **4** | **2** | **1** | **2** | **14** |

### 10.2 L2 语义一致性提升（1 天）

**当前问题**: L2 baseline（关键词重叠）天花板 0.7-0.85。LLM judge 已实现但 LLM API 可能 BLOCKED。

| # | 任务 | 产出 | 工时 |
|---|---|------|------|
| 10.2.1 | 改进 L2 baseline 算法 | 引入语义嵌入相似度（sentence-transformers） | 0.5 天 |
| 10.2.2 | LLM judge 增强 | 优化 rubric，fine-tune 评分维度 | 0.5 天 |

### 10.3 Harness 回归对比（0.5 天）

| # | 任务 | 产出 | 工时 |
|---|---|------|------|
| 10.3.1 | 跨版本聚合报告对比 | 每次提交后自动跑 Harness，输出 diff | 0.5 天 |

**验收标准**:
- 14 个 GT 案例，3 项目 x 多功能覆盖
- L2 平均分 >= 0.75（当前 0.76）
- 每次代码变更后 Harness 回归可自动运行

---

## 5. Phase 11: 5C 语义层全量标注（P1 — BLOCKED 需 LLM API）

**目标**: 用 LLM 为 CodeGraph 核心文件生成完整语义标注。

**解锁条件**: LLM API 可用（Bosch Model Farm 或远端服务器）

### 11.1 标注范围与优先级

| 优先级 | 文件 | 原因 |
|--------|------|------|
| P0 | adasFunc.c (或各项目的等价核心文件) | 报警条件、阈值、状态机核心 |
| P0 | ASWIN_SystemState.c (或各项目的等价文件) | 系统状态使能逻辑 |
| P1 | RteComMapping.c | 信号→变量映射 |
| P1 | paraDefine.h / dotCalibDefine.h | 参数定义 |
| P2 | 其他关键源文件 | 按 variant 配置 |

### 11.2 执行计划（解锁后 2-3 天）

| # | 任务 | 产出 | 工时 |
|---|---|------|------|
| 11.2.1 | 验证 LLM API 连通性 | SemanticAnnotator 全量模式测试 | 0.5 天 |
| 11.2.2 | gwm_b26 核心文件标注 | semantic_annotations 表填充 | 0.5 天 |
| 11.2.3 | sc6h 核心文件标注 | semantic_annotations 表填充 | 0.5 天 |
| 11.2.4 | 质量检查 + 人工审核 | 抽样 50 条标注，准确率 >= 90% | 0.5 天 |
| 11.2.5 | Expert Panel 注入语义标注 | prompt 中引用语义描述 | 0.5 天 |

**验收标准**:
- 核心文件 100% 标注覆盖
- 标注准确率 >= 90%（人工抽样）
- 语义标注在 expert panel prompt 中可见

---

## 6. Phase 12: 记忆系统完善（P2 — 越用越准）

**目标**: 让记忆系统真正积累有价值的知识。

### 12.1 记忆数据积累（随诊断自动增长）

**当前问题**: gwm_b26 仅 2 session + 1 function + 1 patterns.json。

| # | 任务 | 产出 | 工时 |
|---|---|------|------|
| 12.1.1 | 增强 _precipitate_knowledge | 从 expert_panel 提取更多知识模式 | 0.5 天 |
| 12.1.2 | 诊断后自动更新 function knowledge | `{FUNC}_knowledge.json` 增量更新 | 0.5 天 |

### 12.2 AutoDream 改进（1 天）

**当前问题**: AutoDream 被动触发（4h + 2 session），实际很少触发。

| # | 任务 | 产出 | 工时 |
|---|---|------|------|
| 12.2.1 | CLI 强制触发 + 定时任务 | `python cli.py --dream` 已实现；新增 cron 方案 | 0.5 天 |
| 12.2.2 | Dream 触发条件优化 | 诊断 N 次后自动触发（而非时间驱动） | 0.5 天 |

### 12.3 记忆老化机制（0.5 天）

| # | 任务 | 产出 | 工时 |
|---|---|------|------|
| 12.3.1 | session 自动清理 | L4 sessions > 20 条时 prune oldest | 0.5 天 |

**验收标准**:
- 每完成 1 次诊断，记忆增量可见（patterns/functions/code_knowledge）
- session 自动清理上限 20 条

---

## 7. Phase 13: 测试覆盖提升（P2 — 代码质量保障）

**当前**: 153 个测试，但仅 42 passed（其他在 radar-sim 项目中）。radarAnalyze 测试覆盖率不足。

### 13.1 新增测试

| 模块 | 当前测试 | 目标测试 | 新增 |
|------|----------|----------|------|
| orchestrator (8 步管线) | 0 | 10 | +10 |
| expert_panel (LangGraph) | 0 | 8 | +8 |
| codegraph builder | 0 | 10 | +10 |
| semantic_annotator | 0 | 6 | +6 |
| signal_mapper | 0 | 8 | +8 |
| identity/snapshot | 0 | 6 | +6 |
| memory_system | 0 | 8 | +8 |
| config resolve | 0 | 6 | +6 |
| materials registry | 0 | 6 | +6 |
| **合计** | **42** | **110** | **+68** |

### 13.2 测试策略

- 单元测试：纯逻辑函数（config resolve, budget compute, signal filter）
- 集成测试：管线步骤串联（orchestrator run_diagnosis mock）
- Harness 回归：作为 E2E 测试（已在用）

**验收标准**: pytest 110 个测试全通过

---

## 8. Deferred 待改造项

| 项 | 说明 | 触发条件 |
|---|------|----------|
| MF4 Parser | asammdf 依赖不可安装 | 内网安装 asammdf 或 mffparser |
| Web UI | 不在 PRD 范围内 | 产品方向调整 |
| 多平台 CodeGraph 合并查询 | 跨平台对比分析 | 用户明确提出需求 |

---

## 9. 执行路线图

### 推荐执行顺序

```
Phase 7: 真实端到端打通 (sc6h + cr5cb)        ← 先做这个，5 天
    ├── 7.1 sc6h 打通 (2.5 天)
    ├── 7.2 cr5cb 打通 (3.5 天)
    └── 7.3 prompt 去硬编码 (1 天) — 可与 7.1/7.2 并行
        ↓
Phase 8: Identity 深度集成                     ← 架构完整性，3 天
    ├── 8.1 orchestrator 升级 (2 天)
    ├── 8.2 memory/source_docs 迁移 (1 天)
    └── 8.3 CLI 默认化 (0.5 天)
        ↓
Phase 9: Materials 材料接入                     ← 诊断质量，3.5 天
    ├── 9.1 DBC 解析 (1.5 天)
    ├── 9.2 功能说明接入 (2 天)
    └── 9.3 Material Registry (0.5 天)
        ↓
Phase 10: Harness 扩展                          ← 质量量化，3 天
    ├── 10.1 GT 扩充 (随 Phase 7 进行)
    ├── 10.2 L2 提升 (1 天)
    └── 10.3 回归对比 (0.5 天)
        ↓
Phase 11: 5C 语义层全量标注                     ← BLOCKED 需 LLM API，2.5 天
Phase 12: 记忆系统完善                          ← 越用越准，2 天
Phase 13: 测试覆盖提升                          ← 代码质量，2 天
```

### 总工时估算

| Phase | 工时 | 依赖 |
|-------|------|------|
| 7: 真实端到端打通 | **5 天** | 需要用户提供 sc6h/cr5cb 案例数据 |
| 8: Identity 深度集成 | **3.5 天** | 依赖 Phase 7 |
| 9: Materials 材料接入 | **3.5 天** | 可与 Phase 8 并行 |
| 10: Harness 扩展 | **3 天** | 随 Phase 7 进行 |
| 11: 5C 语义层标注 | **2.5 天** | BLOCKED 需 LLM API |
| 12: 记忆系统完善 | **2 天** | 可在任何阶段穿插 |
| 13: 测试覆盖 | **2 天** | 可在任何阶段穿插 |
| **可并行总计** | **~12 天** | 串行 ~21 天 |

### 关键依赖

| 依赖 | 说明 | 谁提供 |
|------|------|--------|
| sc6h/cr5cb 案例数据 | BLF 文件 + 问题描述 + 期望行为 | **用户** |
| cr5cb 代码索引 | BYD_OVS_CB CodeGraph 已建 (24,186 文件) | 已有 |
| LLM API 配额 | Bosch Model Farm 或远端服务器 | **用户确认** |
| 客户需求材料 | DBC/功能说明/状态机文档 | **用户** |

---

## 10. 风险与缓解

| 风险 | 可能性 | 影响 | 缓解 |
|------|--------|------|------|
| sc6h/cr5cb 案例数据不到位 | 高 | 高 | 先跑 gwm_b26 新案例补足 |
| LLM API 始终不可用 | 中 | 中 | cold_start 标注已够用，语义层标注降为 P2 |
| 专家面板 prompt 项目差异大 | 中 | 中 | 7.3 去硬编码后解决 |
| cr5cb CodeGraph 过大 (24K 文件) | 中 | 中 | 限制 scope 到关键模块 |
| Memory 数据爆炸 | 低 | 低 | L4 上限 20 条 + 自动 prune |

---

## 11. 成功指标（Phase 7-13 完成后）

| 指标 | 当前 | 目标 |
|------|------|------|
| Harness GT 案例 | 6 (gwm_b26:5, sc6h:1) | 14 (gwm_b26:5, sc6h:4, cr5cb:4) |
| Harness 通过率 | 5/6 (83%) | >= 12/14 (85%) |
| Harness 平均分 | 0.76 | >= 0.80 |
| 真实诊断案例 | 6 | 14+ |
| 项目覆盖 | 2 (gwm_b26, sc6h) | 3 (+ cr5cb) |
| 功能覆盖 | FCTA/FCTB/BSD/RCTA | + DOW/LCA |
| 测试数 | 42 passed | 110+ passed |
| 专家面板 prompt 硬编码 | 多处 | 0 处 |
| 诊断准确率 | ~70% (估算) | >= 85% |
| 综合评分 | 8.5/10 | 9.0/10 |
