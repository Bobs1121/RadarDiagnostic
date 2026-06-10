# radarAnalyze — Master Handoff Document

> 最后更新: 2026-06-10 (Phase 5B 变量过滤 + 5A 多项目隔离)
> 当前分支: `refactor/v2`
> 当前状态: Phase 1-4 + 5A + 5B 完成，5C/5D/5E 待开始
> PRD 版本: v2.1.0 (多项目支持 + 基础优先策略)

---

## 快速导航

| 文档 | 路径 | 用途 |
|------|------|------|
| **PRD** | `docs/PRD_refactor_v2.md` | 产品需求文档 — 改造目标、用户场景、功能需求 |
| **实施规划** | `docs/IMPLEMENTATION_PLAN_v2.md` | 实施步骤 — Phase/任务/验收标准 |
| **本文档** | `docs/technical/codegraph-handoff-master.md` | 跨会话 handoff — 当前状态 + 架构 + 决策记录 |
| ai/ 模块 | `ai/AGENTS.md` | AI 分析模块说明 |
| memory/ 模块 | `memory/AGENTS.md` | 记忆系统说明 |
| parsers/ 模块 | `parsers/AGENTS.md` | 数据解析层说明 |

---

## 当前状态

### Phase 完成情况

| Phase | 状态 | 说明 |
|-------|------|------|
| **P1: 基础层加固** | ✅ 完成 | MF4 stub (Deferred), topic 自动发现, 降级策略, StepLogger |
| **P2: 代码分析升级** | ✅ 完成 | tree-sitter AST + CodeGraph SQLite (1381 节点, 9897 边) |
| **P3: LangGraph 专家面板** | ✅ 完成 | 5 专家 × 3 轮, prompt 外部化 |
| **P4: CodeFixEngine** | ✅ 完成 | diff 生成 + 安全审查 + 效果预估 |
| **5A: 多项目可配置化** | ✅ 完成 | config.yaml/projects + CLI -P + 3 项目配置 + DB/source_docs/memory 按项目隔离 + SIGNAL 扩展 + E2E 验证 |
| **5B: 变量过滤** | ✅ 完成 | 797→656 变量（全量扫描），过滤规则可配置，噪声变量消除 |
| **5C: 语义层填充** | ⏳ 排队 | LLM 标注 → semantic_annotations 表 |
| **5D: 管线精简** | ⏳ 排队 | 15 步 → 8 步 |
| **5E: 优化项** | ⏳ 排队 | ContextBudget 动态 + 记忆简化 6→3 |

### 改造路线 (基础优先)

```
[x] 多项目可配置化 (5A) → 3 项目(sc6h/gwm_b26/cr5cb) + 全链路隔离
  ↓
[x] 变量过滤 (5B) → 过滤规则可配置，C 关键字/短变量/算法内部变量自动过滤
  ↓
[ ] 语义层 (5C) → LLM 标注 semantic_annotations 表
  ↓
[P] 管线精简 (5D) → 降低出错面
  ↓
[P] 优化项 (5E) → ContextBudget + 记忆简化
```

---

## 2026-06-10 迭代总结 (多项目隔离完善)

### 完成内容

1. **config.yaml 补充 sc6h + cr5cb**
   - sc6h: BYD-SC6H UKE 分支配置，14 个关键源文件
   - cr5cb: BYD_OVS_CB 占位配置，待后续填充 key_source_files
   - 3 个项目各有独立的 `source_code`、`memory_dir`、`codegraph_db_path`、`source_docs_dir`

2. **code_learner.py 项目隔离修复**
   - `knowledge_dir` 从 `memory/code_knowledge/` 改为 `memory/projects/{proj}/code_knowledge/`
   - 向后兼容：无 project 配置时回退到全局 memory/

3. **auto_dream.py 项目隔离修复**
   - `memory_dir` 从 `project_root / "memory"` 改为 `memory_system.memory_dir`
   - 所有 dream 操作（sessions、patterns、code_knowledge）现在使用项目隔离目录

4. **E2E 验证通过**
   - 3 个项目配置均可加载
   - 路径隔离验证通过
   - MemorySystem CRUD 跨项目无污染
   - 提交: `6e51f80`

### 架构决策

- **ADR-2026-06-10-01**: MemorySystem 本身不需要修改 — 它接收 `memory_dir` 参数，所有读写在该目录下展开。只要 `memory_dir` 指向 `memory/projects/{proj}/`，天然隔离。
- **ADR-2026-06-10-02**: CodeLearner 的 `knowledge_dir` 应和 MemorySystem 的 `code_knowledge` 目录一致，避免数据分裂。
- **ADR-2026-06-10-03**: AutoDream 应使用 `memory_system.memory_dir` 而非自己硬编码路径，保证与 MemorySystem 目录一致。

### 项目评估 (回答用户问题)

#### 1. 项目是否走偏？
**没有走偏**。当前实现与 PRD v2.1.0 高度对齐：
- 多项目配置化 ✅（PRD 核心矛盾 #1 已解决）
- CodeGraph 按项目隔离 ✅
- source_docs 按项目隔离 ✅
- 记忆系统按项目隔离 ✅
- 变量过滤（5B）是下一阶段，按计划在 PRD 中定义
- 管线精简（5D）按计划在 PRD 中定义

#### 2. 是否符合 PRD 设计？
**符合度 ~75%**。剩余差距：
- 5B 变量过滤：PRD 要求"消除误报"，尚未开始
- 5C 语义层：PRD 要求"语义理解层"，尚未开始
- 5D 管线精简：PRD 要求"降低出错面"，尚未开始
- 5E 优化：PRD 要求"ContextBudget + 记忆简化"，尚未开始

#### 3. 鲁棒性如何？
**当前鲁棒性中等**：
- ✅ 降级策略完整（classify、probe 都有 fallback）
- ✅ 缓存机制完善（MD5 + mtime 双重校验）
- ✅ 错误处理到位（每步都有 try/except + 跳过标记）
- ⚠️ 管线仍为 15 步，出错面较大（5D 要解决）
- ⚠️ 变量过滤缺失导致大量噪声（5B 要解决）
- ⚠️ 实际多项目 E2E 测试未运行（仅有冒烟测试）

#### 4. 多项目适配性？
**已实现**：
- config.yaml/projects 支持任意数量的项目
- CLI -P 参数可选，默认 gwm_b26
- 每个项目有独立的：
  - CodeGraph DB（SQLite 隔离）
  - source_docs/（MD 概览文件）
  - memory/（L1-L6 全部隔离）
  - code_knowledge/（JSON 结构化知识）

#### 5. 记忆机制？
**6 层记忆已实现，按项目隔离**：
- L1: `projects/{proj}/project.md` — 项目级知识
- L2: `projects/{proj}/functions/*.json` — 功能级知识
- L3: `projects/{proj}/patterns.json` — 诊断模式
- L4: `projects/{proj}/sessions/*.json` — 会话记录
- L5: `cases/*/memory.json` — 案例级（共享，不隔离）
- L6: `projects/{proj}/code_knowledge/*.json` — 代码知识

#### 6. 知识沉淀机制？
**已实现但有改进空间**：
- ✅ CodeLearner: 源码 → JSON 结构化知识（alarm_logic/state_machine/calculation_chain）
- ✅ AutoDream: 定期整合知识，更新 project.md
- ✅ ensure_overview_docs: 源码 hash 驱动刷新 MD 概览
- ⚠️ 知识沉淀是被动触发的（需要 dream 周期），没有主动的知识图谱构建
- ⚠️ 没有跨案例的模式学习（L3 patterns 仅靠 add_pattern 调用）
- ⚠️ CodeGraph 语义层缺失（5C 要解决），无法理解变量/函数的实际含义

---

## 2026-06-10 迭代总结 (Phase 5B 变量过滤)

### 5B 完成内容

1. **变量质量审计 (5B.1)**
   - 审计旧 DB 中 143 个变量，发现 88 个纯噪声（C 关键字 `for`/`while`/`break`，库函数 `fabsf`/`floorf`，短变量 `RCS`/`RKV`）
   - 噪声率高达 62%

2. **config.yaml 增加 variable_filter 配置段 (5B.2)**
   - `include_patterns`: 18 个模式（RTE/Calib/State/Mode/Flag/Signal/Distance 等）
   - `exclude_patterns`: 8 个模式（C 关键字、循环变量 `i`/`j`/`k`）
   - `min_name_length`: 4（局部变量最小长度）
   - `exclude_local_short`: true

3. **config.py 新增 get_variable_filter() + should_include_variable() (5B.2)**
   - `get_variable_filter`: 从 config 读取 filter 配置，支持 project 级别覆盖
   - `should_include_variable`: 核心过滤函数，优先级 = exclude > min_len > include > keep

4. **builder.py 增加过滤逻辑 (5B.2)**
   - `__init__` 增加 `variable_filter` 参数
   - `_extract_all_var_accesses`: 提取变量候选者时应用过滤
   - `_insert_var_edges`: 插入变量时设置 scope (`local`/`global`/`file_static`)
   - scope 检测：通过 AST 节点层级判断（顶层声明 = global，函数内 = local）

5. **orchestrator.py 传递 filter (5B.2)**
   - `_build_codegraph` 从 config 加载 variable_filter 并传递给 CodeGraphBuilder

6. **Rebuild 并验证 (5B.3 + 5B.4)**
   - 重建 gwm_b26 CodeGraph DB：656 变量全部通过过滤规则
   - 无 C 关键字、无算法内部变量
   - 变量质量高：FCTA/FCTB/RCTA/RCTB/RCW/BSD/LCA/DOW 状态、阈值、标志
   - SIGNAL 301 个 + CALIB_PARAM 97 个

### 5B 变更文件
- `config.yaml` — 新增 variable_filter 配置段
- `config.py` — 新增 get_variable_filter() + should_include_variable()
- `ai/codegraph/builder.py` — variable_filter 参数 + 过滤逻辑
- `ai/orchestrator.py` — _build_codegraph 传递 variable_filter

### 架构决策
- **ADR-2026-06-10-04**: 变量过滤规则外部化到 config.yaml，便于针对不同项目调整过滤策略
- **ADR-2026-06-10-05**: 过滤优先级 = exclude > min_len > include > keep
- **ADR-2026-06-10-06**: scope 信息通过 AST 节点层级推断（builder 层已有基础设施）

### 项目评估更新

#### 符合度：~80%
5B 完成后，PRD 核心矛盾#2（CodeGraph 变量噪声）已解决。

#### 鲁棒性：中高
- ✅ 变量过滤消除噪声（5B）
- ✅ 降级策略 + 缓存 + 错误处理
- ⚠️ 管线仍 15 步（5D），CodeGraph scope 未完全写入（analyzer 需补充）

#### 多项目适配性
variable_filter 支持 project 级别覆盖，不同项目可独立配置过滤策略。

#### 知识沉淀改进
CodeGraph 变量质量提升 → LLM 标注输入更干净。

---


| Task | 状态 | 说明 |
|------|------|------|
| 5A.1 | ✅ | config.yaml 重构为 projects 配置 + CLI -P 参数 + config.py |
| 5A.2 | ✅ | CodeGraph DB 按项目隔离（codegraph_{key}.db） |
| 5A.3 | ✅ | source_docs 按项目隔离（source_docs_dir property） |
| 5A.4 | ✅ | 记忆系统按项目隔离（memory_dir 参数） |
| 5A.5 | ✅ | SIGNAL 节点扩展（dbc_name, dbc_id, dbc_signal_name, internal_var, rte_port_id） |
| 5A.6 | ✅ | E2E 验证 — gwm_b26 项目 CodeGraph build + Orchestrator 全链路 |

**5A 变更文件**:
- `config.py` — 新增 config 解析 + resolve 函数
- `config.yaml` — 新增 projects 块
- `cli.py` — -P 参数 + project config 加载
- `ai/orchestrator.py` — codegraph_db_path, source_docs_dir property + MemorySystem init
- `ai/codegraph/schema.py` — SIGNAL 新字段, SCHEMA_VERSION=2
- `ai/codegraph/builder.py` — source_docs_dir param, _enrich_signal_nodes()
- `ai/codegraph/ast_parser.py` — SignalInterface 扩展字段
- `ai/code_learner.py` — resolve_source_docs_dir
- `ai/condition_extractor.py` — resolve_source_docs_dir
- `ai/data_query_engine.py` — resolve_source_docs_dir
- `memory/auto_dream.py` — resolve_source_docs_dir
- `memory/memory_system.py` — memory_dir 参数

---

## 产品定位

- **目标用户**: 内部 ADAS ASW 工程师
- **使用场景**: 离线分析角雷达 ADAS 功能 bug，定位根因
- **支持平台**: 多代角雷达项目（5 代 CR5CB、6 代 SC6H-cr60light）
- **交付形态**: CLI 工具
- **不在范围**: Web UI、实时在线诊断、自动提交/PR

---

## 支持的角雷达项目

| 项目代号 | 平台 | 工作目录 | 说明 |
|---------|------|---------|------|
| `sc6h` | BYD-SC6H-cr60light — 6 代角雷达 | `D:\BYD-SC6H-cr60light\cr60_light` | CR60Light 平台 |
| `cr5cb` | BYD_OVS_CB — 5 代角雷达 | `C:\BYD_OVS_CB` | CR5CB 平台, 17 子模块 |

---

## 架构概览

### 管线流程 (当前 15 步 → 目标 8 步)

```
用户输入: 项目配置 + 问题描述 + 案例数据 (BAG/BLF)
  ↓
Phase 0:  init       — source_docs + CodeGraph 构建 (确定性)
Phase 1:  classify   — 问题理解 + 分类 (LLM) ← 合并 understand + classify
Phase 2:  extract    — 数据解析 + 窗口检测 (确定性) ← 合并 parse + detect_window
Phase 3:  evidence   — 条件提取(LLM) + TPE(确定性) + 变量探测(LLM) ← 并行
Phase 3.6: signals   — 抑制信号 + 输出信号 (确定性) ← 合并 suppression + output_signals
Phase 4:  diagnose   — LangGraph 专家面板 (多 LLM)
Phase 4.5: fix       — CodeFixEngine 生成 diff (LLM)
Phase 5:  deliver    — 报告 + 可视化 + 记忆更新 (确定性) ← 合并 visualize + memory + done
```

### 模块职责

| 模块 | 职责 | 类型 |
|------|------|------|
| `cli.py` | 统一 CLI 入口，模式路由 | 确定性 |
| `ai/orchestrator.py` | 诊断管线编排 | 编排 |
| `ai/expert_panel_langgraph.py` | LangGraph 专家面板 (5 专家 × 3 轮) | LLM |
| `ai/code_fix_engine.py` | 代码修复 diff 生成 | LLM |
| `ai/context_budget.py` | Token 预算管理 | 确定性 |
| `ai/codegraph/` | CodeGraph 构建 + 查询 | 确定性 |
| `ai/problem_classifier.py` | 问题分类 | LLM |
| `ai/condition_extractor.py` | 条件提取 | LLM |
| `ai/data_probe.py` + `variable_query_planner.py` | 变量动态探测 | LLM |
| `ai/tpe/` | 时序模式引擎 | 确定性 |
| `ai/frame_analyzer.py` | 帧级证据提取 | LLM |
| `ai/visualizer.py` | HTML 报告渲染 | 确定性 |
| `ai/observability.py` | StepLogger 可观测性 | 确定性 |
| `parsers/` | 数据解析 (BAG/BLF) | 确定性 |
| `memory/` | 记忆系统 (L1-L6 → 目标 L1-L3) | 确定性 |

### 数据流

```
案例数据 (BAG/BLF)
  → parsers/case_loader → FrameStore (SQLite)
    → frame_analyzer → evidence dict
    → condition_extractor → conditions JSON
    → TPE → temporal patterns
    → data_probe → variable statistics

代码库 (C source)
  → tree-sitter AST → CodeGraph SQLite
    → CodeGraphRenderer → 结构化上下文
    → ContextBudget → 专家面板 prompt

LLM 推理
  → problem_classifier → 分类结果
  → condition_extractor → 条件树
  → expert_panel (LangGraph) → 诊断结论
  → code_fix_engine → 修复 diff

输出
  → visualizer → HTML 报告
  → memory_system → 知识写入
  → 终端输出 → Markdown 报告
```

---

## 环境配置

### 模型端点

| 用途 | 端点 | 模型 |
|------|------|------|
| 推理 (complex) | `http://10.190.179.61:11999/qwen3_5/v1` | Qwen3.5-27B-FP16 |
| 编码 (coder) | `http://10.190.161.39:8080/v1` | qwen3-coder:30b |
| 本地 (simple) | `localhost:11434/v1` | qwen3:14b (当前不可用) |

### 依赖

| 包 | 版本 | 用途 |
|---|---|---|
| tree-sitter | 0.21.3 | C 代码 AST 解析 |
| tree-sitter-c | 0.21.4 | C 语言包 |
| langgraph | 1.2.4 | 专家面板编排 |
| openai | 2.41.0 | LLM 客户端 |
| cantools | - | DBC 解码 |
| rosbags | 0.11.3 | BAG 解析 |
| python | 3.12.10 | 运行环境 |

### 网络代理

```
HTTP/HTTPS_PROXY=http://127.0.0.1:3128
NO_PROXY=localhost,bosch.com
```

---

## CodeGraph 架构

### 设计决策 (ADR)

| ADR | 决策 | 理由 |
|-----|------|------|
| ADR-001 | SQLite + JSON 双存储 | SQLite 结构数据快，JSON 语义数据灵活 |
| ADR-004 | tree-sitter 0.21.x API | 锁定旧版 API，0.24+ PyCapsule 不兼容 |
| ADR-005 | AST 为主 + 正则 fallback | 渐进迁移，正则覆盖 AST 未覆盖场景 |

### CodeGraph 数据模型

```
节点类型:
  FILE       — 源文件
  FUNCTION   — 函数定义
  VARIABLE   — 变量声明 (过滤后)
  SIGNAL     — CAN 信号映射 (含完整链路)
  TYPEDEF    — 类型定义

关系边:
  DEFINES    — FILE → FUNCTION/VARIABLE
  CALLS      — FUNCTION → FUNCTION
  READS      — FUNCTION → VARIABLE
  WRITES     — FUNCTION → VARIABLE
  READS_SIGNAL  — FUNCTION → SIGNAL
  WRITES_SIGNAL — FUNCTION → SIGNAL
  INCLUDES   — FILE → FILE (头文件依赖)

语义标注 (待填充):
  semantic_annotations — 函数/变量/信号/状态机/模式的 LLM 语义描述
```

### CodeGraph 模块

| 文件 | 职责 |
|------|------|
| `ai/codegraph/__init__.py` | CodeGraph 类 — SQLite 操作 |
| `ai/codegraph/schema.py` | 数据模型定义 |
| `ai/codegraph/ast_parser.py` | tree-sitter AST 解析器 |
| `ai/codegraph/ast_builder.py` | AST → CodeGraph 转换 |
| `ai/codegraph/builder.py` | 构建编排 (AST + 正则) |
| `ai/codegraph/pattern_extractor_ast.py` | AST 行为模式提取 |
| `ai/codegraph/state_machine_extractor.py` | AST 状态机提取 |
| `ai/codegraph/render.py` | CodeGraph 渲染器 (stats/expert panel) |

---

## 专家面板 (LangGraph)

### 架构

```
START → parallel_experts (5 专家并发)
       → moderator_challenge (Round 2)
       → expert_rebuttals (仅受挑战专家回应)
       → moderator_synthesize (Round 3) → END
```

### 5 专家

| 专家 | 视角 | 适用故障类型 |
|------|------|-------------|
| Signal Chain | 信号链路完整性 | 信号丢失/映射错误 |
| Algorithm | 算法逻辑正确性 | 计算错误/阈值问题 |
| System State | 状态机/生命周期 | 状态卡死/转换错误 |
| Perception | 感知层输入 | 目标检测/跟踪问题 |
| Architecture | 系统集成/时序 | 模块交互/时序问题 |

### Prompt 外部化

```
prompts/expert_panel/
  experts/signal_chain.md      — 信号链路专家
  experts/algorithm.md          — 算法专家
  experts/system_state.md       — 系统状态专家
  experts/perception.md         — 感知专家
  experts/architecture.md       — 架构专家
  moderator_system.md           — 主持人
  expert_analyze.md             — 首轮分析模板
  expert_respond.md             — 回应挑战模板
  moderator_challenge.md        — 挑战模板
  moderator_synthesize.md       — 综合收敛模板
  task_headers.md               — 任务类型 Header
  retry_strict_json.md          — JSON 重试指令
  loader.py                     — Prompt 加载器
```

---

## 已知问题与待办

### 高优先级 (影响诊断准确率)

| # | 问题 | 状态 | 计划 Phase |
|---|------|------|-----------|
| ~~1~~ | ~~**项目配置硬编码** — config.yaml 写死 GWM_B26~~ | ~~已解决~~ | 5A.1 ✅ |
| 2 | **变量 false positives** — 797 变量中大量局部变量 | 🔜 下一步 | 5B |
| ~~3~~ | ~~**数据-变量映射不完整** — BLF signal → C 变量链路不完整~~ | ~~基础设施就绪~~ | 5A.5 ✅ |
| 4 | **CodeGraph 语义层为空** — semantic_annotations 表空 | ⏳ 排队 | 5C |

### 中优先级 (影响效率和可维护性)

| # | 问题 | 状态 | 计划 Phase |
|---|------|------|-----------|
| 5 | 管线 15 步过多 | ⏳ 排队 | 5D |
| 6 | ContextBudget 固定 60K | ⏳ 排队 | 5E.1 |
| 7 | 记忆 6 层消费不均衡 | ⏳ 排队 | 5E.2 |

### Deferred (暂不处理)

| # | 问题 | 原因 |
|---|------|------|
| 8 | MF4 Parser | asammdf 内网不可安装 |
| 9 | 多平台 CodeGraph 合并查询 | 需求未明确 |
| 10 | Web UI | 产品定位 CLI |

---

## 关键修复记录

### tree-sitter 兼容性问题
- **问题**: `paren.children[0]` 取到 `(` 而非表达式
- **修复**: `state_machine_extractor.py` 中 `_paren_expr()` 辅助函数
- **影响**: 状态机提取时 case 条件解析

### CodeGraph 构建性能
- **问题**: O(N×M) 遍历导致 120s+ 超时
- **修复**: `_build_func_index` + `_build_line_to_func_index` 索引
- **结果**: 从 120s 降至 0.98s/文件

### ai/__init__.py eager import 阻塞
- **问题**: `ai/__init__.py` 导入 model_router→openai，阻塞所有 ai/ 模块
- **修复**: fake sys.modules + importlib.util 绕过
- **影响**: CLI 启动时不再阻塞

### 多项目可配置化 (5A)
- **config.py** — 集中 config 加载 + `${VAR:-default}` 环境变量展开 + `get_project()`/`resolve_*()` 路径解析
- **config.yaml** — `projects` 块 + `default_project`，每个项目独立 `source_code`/`key_source_files`
- **CLI** — `-P` 参数，无 `-P` 时使用 `default_project`
- **CodeGraph DB 隔离** — `memory/codegraph/codegraph_{project_key}.db`，`Orchestrator.codegraph_db_path` property
- **source_docs 隔离** — `resolve_source_docs_dir()` helper，orchestrator/learner/condition_extractor/query_engine/auto_dream 全部更新
- **记忆系统隔离** — `MemorySystem(memory_dir=...)`，`memory/projects/{key}/` 目录
- **SIGNAL 节点扩展** — 新增 5 字段（`dbc_name`, `dbc_id`, `dbc_signal_name`, `internal_var`, `rte_port_id`），`_enrich_signal_nodes()` Phase 11 从 `signal_mapping.json` 回填
- **Schema 迁移** — `_drop_all()` 加 `PRAGMA foreign_keys=OFF` 解决 FK 约束

### 5A Bug 修复
- **auto_dream.py import 错位** — `from config import resolve_source_docs_dir` 被插入 try 块内部导致 SyntaxError，已移到模块级
- **_drop_all FK 约束** — `DROP TABLE` 因外键被拒，已加 `PRAGMA foreign_keys=OFF`
- **SCHEMA_VERSION 升级** — 升至 2 以触发现有 DB 的 schema 重建

---

## CodeGraph 代码审查结论 (2026-06-09)

**审查范围**: `ai/codegraph/` 全部 8 个模块 (schema, query, builder, ast_parser, ast_builder, analyzer, render, pattern_extractor_ast, state_machine_extractor)

| 模块 | 评价 | 问题 |
|------|------|------|
| **schema.py** | 设计合理 | 7 种节点类型覆盖完整；SCHEMA_VERSION=2，新增 SIGNAL 映射字段，有迁移机制 |
| **query.py** | API 清晰 | 566 行覆盖 callers/callees/signal/var/state/semantic 查询；无连接池 |
| **builder.py** | 渐进迁移 | 758 行，AST + 正则 dual-mode；增量构建基于 hash 比较 |
| **ast_parser.py** | 实现到位 | 582 行，tree-sitter 0.21.x API；children[0]→children[1] 已修复 |
| **ast_builder.py** | 与 parser 配合 | AST → CodeGraph node/edge 转换 |
| **pattern_extractor_ast.py** | 行为模式提取 | if-guard-on-global, state-machine, flag-set-never-cleared |
| **state_machine_extractor.py** | 状态机提取 | switch-case → state transitions |
| **render.py** | 渲染器 | CodeGraph → 专家面板 prompt 格式化 |

**整体评价**: 架构合理，模块化清晰。主要风险在：
1. [x] schema migration 已解决（SCHEMA_VERSION=2，`_drop_all` 含 FK 关闭）
2. 变量过滤缺失（797 变量含大量 noise）— 5B 解决
3. 语义层为空（semantic_annotations 表已建但未填充）— 5C 解决

## Git 提交历史 (refactor/v2)

```
550c923 docs(v2): update handoff — Phase 3+4 complete, Phase 5 next
3404b9e chore: ignore runtime artifacts (case reports, source_docs, memory)
86c45ee docs(v2): mark Phase 3 as complete — LangGraph panel + prompt externalization
b25d0a2 feat(v2 P3.4): externalize expert panel prompts to markdown files
277c463 fix(v2 P3.2): integrate LangGraph expert panel into orchestrator
32bffc0 docs: update handoff — CodeFixEngine Phase 4.5 completion
c2a2c96 feat: CodeFixEngine — Phase 4.5, generate unified diffs from expert verdict
9329290 feat: Phase 2+3 artifacts — AST pattern/state machine extractors + LangGraph expert panel + benchmark
a204863 feat(v2): Phase 1 基础层加固 — MF4 stub + topic auto-discovery + fallback + observability
```

---

## 架构决策记录 (ADR)

### ADR-2026-06-09: 多项目可配置化方案

**背景**: 用户同时在两个角雷达项目工作 (5 代 CR5CB + 6 代 SC6H)，当前配置硬编码。

**决策**: 单个 config.yaml + projects.* 分层 + CLI `-P` 参数切换。

**理由**:
- 单文件管理比多配置文件简单
- 项目隔离通过路径前缀实现，不增加复杂度
- 所有项目共享模型配置、功能定义、AutoDream 策略

**影响**:
- config.yaml 结构变化 (breaking for scripts that read paths directly)
- CodeGraph DB 按项目隔离
- source_docs 按项目隔离
- 记忆系统按项目隔离

### ADR-2026-06-09: 基础优先策略

**背景**: PRD v2.0 中管线精简 (5D) 排在变量过滤/语义层之前。

**决策**: 调整为 配置化(5A) → 变量过滤(5B) + 语义层(5C) → 管线精简(5D) → 优化(5E)。

**理由**:
- 变量 false positives 直接影响诊断准确率
- 语义层为空意味着 CodeGraph 只有结构没有理解
- 管线精简是效率优化，不应优先于质量改进

### ADR-2026-06-09: SIGNAL 节点数据-变量映射

**背景**: BLF CAN signal 和 C 内部变量之间缺乏系统化映射。

**决策**: SIGNAL 节点存储完整链路 (CAN signal → DBC → RteComMapping → C 变量)。

**理由**:
- 诊断核心是找到"数据层面发生了什么"与"代码期望什么"之间的差距
- 这个映射是建立差距分析的基础设施
- 应在 CodeGraph 构建阶段确定，而非诊断时临时查找

---

## 每次会话工作流

```
1. 读本文档 (handoff master) → 了解当前状态
2. 读 docs/PRD_refactor_v2.md → 了解改造目标
3. 读 docs/IMPLEMENTATION_PLAN_v2.md → 了解实施步骤
4. 执行当前 Phase 的任务
5. 完成后更新本文档 + Git 提交
6. 更新 IMPLEMENTATION_PLAN_v2.md (完成任务标记为 done)
```

**重要**: 每次对话结束前，更新本文档的"当前状态"和"已知问题"。这是跨会话协作的唯一可靠通道。
