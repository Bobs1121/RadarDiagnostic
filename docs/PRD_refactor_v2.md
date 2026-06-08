# radarAnalyze — 第一性原理改造 PRD

> 版本: 2.0.0
> 日期: 2026-06-08
> 作者: AI Agent (基于 GitHub 调研 + 架构审计)
> 状态: Draft — 等待用户确认

---

## 1. 文档基础信息

| 项 | 值 |
|---|---|
| 产品名称 | radarAnalyze — 角雷达 ADAS AI 诊断系统 |
| 版本 | 2.0.0 (架构重构版) |
| 修订历史 | v2.0.0: 第一性原理重构规划 (2026-06-08) |
| 干系人 | 用户=产品经理+诊断工程师; Agent=PM+架构师+开发者 |
| 术语表 | **BAG**: ROS1 录制数据; **BLF**: Vector CAN 日志; **MF4**: ASAM MCDF 测量数据; **TPE**: 时序模式引擎; **CodeGraph**: C 源码静态分析图谱; **FrameStore**: SQLite 内存数据库 |

---

## 2. 项目背景与目标

### 2.1 第一性原理：用户需要什么？

回到最本质问题：**用户在干什么？**

用户是一名 ADAS 诊断工程师，面对的是"功能不工作"的 bug 报告。他需要回答一个问题：

> **"为什么这个功能在特定场景下没有按预期工作？"**

回答这个问题的**最小必要动作**是：

1. **看懂数据** — 回放数据里发生了什么（信号值、目标状态、自车状态）
2. **理解代码** — 代码期望什么条件才能激活/退出功能
3. **找到差距** — 实际数据和代码期望之间的差异就是根因
4. **给出方案** — 怎么改代码或参数可以解决问题

**当前系统已经在做这件事**，但存在结构性问题。

### 2.2 当前系统的核心矛盾

| 矛盾 | 说明 |
|------|------|
| **LLM 链路过长** | 5+ 串行 LLM 调用，任何一环失败/降级都影响最终结果 |
| **正则解析 C 代码** | `pattern_extractor.py` 靠正则提取代码模式，覆盖率有限且脆弱 |
| **管线步骤过多** | 15+ 步，每步都增加出错面和调试复杂度 |
| **专家面板手写编排** | `expert_panel.py` 自己管理 5 专家 3 轮对话，等于手写了一个 agent framework |
| **数据解析手写** | BAG parser 手写反序列化，BLF 解析虽有 cantools 但 BLF 文件读取是手写 |
| **无代码修改能力** | 只能给出文字建议，不能生成 diff |
| **ContextBudget 被动截断** | 60K 字符硬上限，超了就截，无智能优先级策略 |
| **无 MF4 支持** | 大量测量数据无法使用 |

### 2.3 产品愿景

```
输入: 问题描述 + 案例数据 (BAG/BLF/MF4)
  ↓
自动诊断 (确定性的数据解析 + LLM 推理 + 代码分析)
  ↓
输出:
  1. 根因诊断 (专家面板 → 结构化结论)
  2. 代码修改方案 (diff + 效果预估)
  3. 可视化报告 (交互式时间线)
```

### 2.4 成功指标

| 指标 | 当前 | 目标 |
|------|------|------|
| 诊断准确率 | ~70% (估算) | >85% |
| 端到端耗时 | 5-10 min | <5 min |
| LLM 调用次数 | 8-12 次 | 5-7 次 |
| 数据解析覆盖率 | BAG+BLF (2/3 格式) | BAG+BLF+MF4 (3/3) |
| 代码修改能力 | 仅文字建议 | 结构化 diff + 效果模拟 |

### 2.5 范围界定

| In Scope | Out of Scope |
|----------|-------------|
| 诊断管线重构 | Web UI (CLI 模式不变) |
| 代码解析层升级 (tree-sitter) | 多平台代码库支持 (先做好 GWM_B26) |
| 专家面板迁移到成熟框架 | 实时在线诊断 (仅离线分析) |
| CodeFixEngine (diff 生成) | 自动提交/PR |
| MF4 Parser | 视频/图像辅助诊断 |
| 记忆系统简化 | 多语言支持 (仅中文) |

---

## 3. 用户画像与场景

### 3.1 目标用户

| 角色 | 描述 | 核心诉求 |
|------|------|---------|
| **诊断工程师** | ADAS SW 工程师，日常分析功能 bug | 快速定位根因，减少看 BLF 波形和 C 代码的时间 |
| **产品经理** | 评估功能表现，推动问题闭环 | 结构化报告，可转给其他 AI/团队继续处理 |

### 3.2 典型使用场景

**场景 1: 新 bug 诊断**
```
用户: "FCTA 在低速场景没有触发预警"
操作: python cli.py cases/FCTA_NEW -p "低速 FCTA 无预警" -e "应该触发 FCTA 预警"
期望: 5 分钟内得到根因分析报告 + 代码修改建议
```

**场景 2: 数据快查**
```
用户: "FCTB 触发时 AEBIB 信号是什么值"
操作: python cli.py cases/FCTA001 -q "FCTB 触发时 AEBIB 信号值"
期望: 30 秒内返回信号时间线和统计
```

**场景 3: 批量复盘**
```
用户: 一周积累了 5 个 FCTA 漏报案例
操作: 逐个运行诊断 → 自动写入记忆 → AutoDream 整合
期望: 形成跨案例的模式库，越用越准
```

---

## 4. 功能需求详述

### 4.1 改造核心原则

**原则 1: 确定性层和 LLM 层分离**
- 数据解析、时间同步、信号映射、CodeGraph 构建 → 纯确定性代码
- 问题理解、条件提取、专家面板 → LLM 推理
- 原则：确定性层出错率应接近 0%，LLM 层负责模糊推理

**原则 2: LLM 调用最小化**
- 当前 8-12 次串行 LLM 调用 → 目标 5-7 次
- 合并可合并的步骤（如 问题理解 + 任务分类 可合并为一次调用）
- 能用确定性代码解决的不用 LLM

**原则 3: 可观测性**
- 每个管线步骤必须记录输入/输出摘要、耗时、状态
- LLM 调用必须记录 prompt 大小、token 消耗、响应时间
- 失败必须有明确的降级策略

### 4.2 模块级改造需求

#### FR-001: 数据解析层重构

**目标**: 用成熟库替代手写解析，减少维护负担。

| 子项 | 当前方案 | 改造方案 | 优先级 |
|------|---------|---------|--------|
| BAG 解析 | 手写 ROS1 bag 反序列化 | 保持现状 (ROS bag 格式稳定，手写已足够) | P2 |
| BLF 解析 | cantools + 手写 BLF reader | 评估 `blf-reader` 库 (如有)，否则保持 | P2 |
| DBC 加载 | cantools | 保持 (cantools 已成熟) | — |
| MF4 解析 | 缺失 | 新增 `Mf4Parser` (mffparser 库) | P1 |
| topic 发现 | 硬编码 topic 路径 | 自动扫描 bag 的 topics，按关键词匹配 | P1 |

#### FR-002: 代码分析层升级 — Tree-sitter

**目标**: 用 tree-sitter 替代正则表达式提取 C 代码结构。

**当前问题**:
- `pattern_extractor.py` 用正则匹配 `HoldRelease`/`Accumulate` 等模式
- 覆盖率和精确度受限，代码格式变化就失效
- 无法提取函数调用链、变量作用域等深层信息

**改造方案**:
```
tree-sitter parse (C grammar)
  → AST traversal
    → 函数声明/调用关系
    → 全局变量读写关系
    → 状态机模式 (switch-case + goto)
    → 条件判断树 (if-else/ternary)
    → 行为模式 (HoldRelease, Accumulate, Hysteresis)
  → 写入 CodeGraph (SQLite)
```

**借鉴项目**: `tree-sitter/tree-sitter` (25.7k star)

**优先级**: P1 — 这是诊断准确率提升的关键

#### FR-003: 专家面板迁移到 LangGraph

**目标**: 用 LangGraph 替代手写专家面板编排。

**当前问题**:
- `expert_panel.py` (686 行) 自己管理 5 专家 prompt、3 轮对话、并行执行
- 无法复用成熟的 agent 编排能力（状态管理、循环、条件分支）
- prompt 硬编码在模块中，难以维护和扩展

**改造方案**:
```python
# LangGraph 图定义
graph = StateGraph(DiagnosisState)

# 5 个专家节点
graph.add_node("signal_chain", signal_chain_agent)
graph.add_node("algorithm", algorithm_agent)
graph.add_node("system_state", system_state_agent)
graph.add_node("perception", perception_agent)
graph.add_node("architecture", architecture_agent)

# 并行执行 Round 1
graph.add_edge("__start__", "signal_chain")
graph.add_edge("__start__", "algorithm")
# ...

# 主持人挑战 (Round 2) — 条件分支
graph.add_conditional_edges("round1_parallel", route_to_challenge)

# 收敛 (Round 3)
graph.add_edge("round2_challenge", "moderator_synthesize")
```

**借鉴项目**: `langchain-ai/langgraph` (34.1k star)

**优先级**: P1

#### FR-004: CodeFixEngine — 代码修改方案生成

**目标**: 将专家面板的"文字修复建议"转化为可执行的 unified diff。

**流程**:
```
专家面板结论 (根因 + 修复建议)
  → CodeFixEngine
    1. CodeGraph 定位精确代码位置 (file:line)
    2. 提取上下文 (前后 N 行)
    3. coder LLM 生成 diff (qwen3-coder:30b, max_tokens=2000)
    4. embedded-c-runtime-safety 安全审查
    5. 语法验证 (clang -fsyntax-only 或等价检查)
  → 输出: cases/{case}/fix.patch + fix_report.md
```

**借鉴项目**: 内部 `embedded-c-runtime-safety` skill + 现有 coder LLM 路由

**优先级**: P1

#### FR-005: 管线步骤合并与精简

**目标**: 15+ 步 → 8 步核心管线。

| 合并前 | 合并后 | 理由 |
|--------|--------|------|
| understand + classify | `classify` (1 次 LLM 同时完成) | 两个步骤都在用 LLM 理解问题，合并减少 1 次调用 |
| parse + detect_window + analyze | `extract` (确定性层合并) | 都是确定性操作，不需要 LLM，合并减少 I/O 开销 |
| conditions + tpe + probe | `evidence` (并行执行) | conditions 和 tpe 可并行，probe 依赖两者完成 |
| suppression + output_signals | `signals` (合并) | 都是 CAN 信号查询 |
| diagnose (专家面板) | `diagnose` (LangGraph 面板) | 保持不变，内部迁移框架 |
| report + visualize + done | `deliver` (合并) | 报告+可视化+记忆更新，一次性完成 |

**目标管线 (8 步)**:
```
1. init      → source_docs 保障 + CodeGraph 构建
2. classify  → 问题理解 + 任务分类 (1 LLM)
3. extract   → 数据解析 + 窗口检测 + 帧级分析 (确定性)
4. evidence  → 条件提取 + TPE + 变量探测 (2 LLM, 可并行)
5. signals   → 抑制信号 + 输出信号 (确定性)
6. diagnose  → 专家面板 (1-2 LLM, LangGraph)
7. fix       → CodeFixEngine 生成 diff (1 LLM, 仅在 diagnose 模式)
8. deliver   → 报告 + 可视化 + 记忆更新
```

#### FR-006: ContextBudget 智能优化

**目标**: 从被动截断变为智能优先级管理。

**当前**: 60K 字符硬上限，按固定 priority 排序截断。
**改造**:
- 引入 token 预算反馈：记录每次 LLM 调用实际的 token 消耗
- 动态调整：根据历史数据预估需要的 context 大小
- 分级策略：关键证据 > 时序数据 > 背景信息 > 补充数据
- 截断告警：截断超过 15% 时标记，专家面板中可见

#### FR-007: 记忆系统简化

**目标**: 6 层 → 3 层核心记忆。

| 当前 | 改造 | 理由 |
|------|------|------|
| L1: project.md | 保留 → `project.md` | 项目级知识，有价值 |
| L2: functions/*.json | 保留 → 合并到 `knowledge/` | 功能级知识，有价值 |
| L3: patterns.json | 保留 → 合并到 `knowledge/` | 模式库，有价值 |
| L4: sessions/*.json | **降级** → 仅最近 10 条 | 会话日志太多，90% 不会被消费 |
| L5: cases/*/memory.json | **合并到 L3** | 案例记忆本质上就是模式 |
| L6: code_knowledge/*.json | 保留 → `knowledge/code/` | 代码知识是诊断核心 |

**简化后**:
```
memory/
  project.md           # 项目级总览 (AutoDream 写入)
  knowledge/
    patterns.json      # 跨功能模式库
    code/              # 代码结构化知识 (CodeLearner 写入)
    {FUNC}.json        # 功能级知识
  sessions/            # 仅保留最近 N 条会话
```

#### FR-008: 异常处理与降级策略

**目标**: 每个 LLM 调用都有明确的降级策略。

| 步骤 | 降级策略 |
|------|---------|
| classify | 降级为默认 diagnose 模式 + 通用专家配置 |
| evidence (conditions) | 使用缓存的 source_docs，跳过 LLM 提取 |
| evidence (probe) | 跳过变量探测，不影响主线 |
| diagnose (专家面板) | 降级为单专家模式，直接输出结论 |
| fix (CodeFixEngine) | 降级为文字修复建议 (当前行为) |

---

## 5. 数据模型

### 5.1 核心实体关系

```
Case (案例)
  ├── BAG/BLF/MF4 Files (数据源)
  ├── FrameStore (SQLite)
  │     ├── bag_frames
  │     ├── can_frames
  │     ├── radar_objects
  │     ├── radar_debug
  │     └── warning_events
  ├── DiagnosisResult (诊断结果)
  │     ├── classification
  │     ├── evidence
  │     ├── expert_verdict
  │     └── code_fix (NEW)
  └── Reports (报告产物)
        ├── report.md
        ├── report.html
        ├── expert_opinions.md
        └── fix.patch (NEW)

CodeGraph (代码图谱) — SQLite
  ├── functions (函数节点)
  ├── variables (变量节点)
  ├── signals (信号节点)
  ├── files (文件节点)
  ├── edges (关系边: CALLS, READS, WRITES, READS_SIGNAL, WRITES_SIGNAL)
  └── patterns (行为模式: HoldRelease, Accumulate...)

Memory (记忆系统)
  ├── project.md (项目级)
  ├── knowledge/ (功能级 + 代码级 + 模式库)
  └── sessions/ (会话日志)
```

---

## 6. 非功能需求

### 6.1 性能

| 指标 | 当前 | 目标 |
|------|------|------|
| 单次诊断总耗时 | 5-10 min | <5 min |
| LLM 调用总次数 | 8-12 | 5-7 |
| 数据解析耗时 | 10-30s | <15s |
| CodeGraph 构建 | 首次 6s, 增量 <1s | 首次 <5s (tree-sitter) |
| HTML 报告生成 | <5s | <5s |

### 6.2 可靠性

- 确定性步骤（数据解析、CodeGraph）不依赖 LLM，成功率 >99%
- LLM 步骤有降级策略，最坏情况仍能产出基础报告
- 所有中间结果缓存，支持断点续跑

### 6.3 可维护性

- 管线步骤从 15+ 减到 8，代码量减少 30%+
- 专家面板迁移到 LangGraph，prompt 管理从代码中分离
- 代码解析从正则迁移到 tree-sitter，维护成本降低

---

## 7. 假设、约束与依赖

### 7.1 技术约束

- 模型: Qwen3.5-27B-FP16 (远端) + qwen3-coder:30b (编码)
- 单 GPU (RTX A2000 12GB)，KV cache 有限
- 内网环境，部分外部库可能无法直接安装

### 7.2 外部依赖

| 依赖 | 用途 | 风险 |
|------|------|------|
| tree-sitter + tree-sitter-c | C 代码 AST 解析 | 需编译 C 扩展 |
| mffparser | MF4 解析 | 需安装 C 依赖 |
| langgraph | 专家面板编排 | pip 安装，低风险 |
| cantools | DBC 解码 | 已在用，低风险 |

### 7.3 风险与应对

| 风险 | 可能性 | 影响 | 应对措施 |
|------|--------|------|---------|
| tree-sitter 编译失败 | 中 | 高 | fallback 到现有正则解析 |
| LangGraph 迁移破坏现有面板 | 中 | 中 | 并行运行新旧面板，对比输出 |
| mffparser 安装失败 | 中 | 中 | fallback 到 mf4-converter CLI |
| 管线合并导致调试困难 | 低 | 高 | 每个步骤保留独立日志输出 |

---

## 8. 里程碑与发布计划

### Phase 1: 基础层加固 (1-2 周)

| # | 任务 | 工时 | 验收标准 |
|---|------|------|---------|
| 1.1 | MF4 Parser 实现 + case_loader 集成 | 2 天 | MF4 文件可解析写入 FrameStore |
| 1.2 | BAG topic 自动发现 | 1 天 | 不修改代码可识别新 topic |
| 1.3 | 异常降级策略实现 | 1 天 | 所有 LLM 步骤有 fallback |
| 1.4 | 可观测性层 (步骤日志 + token 统计) | 1 天 | 每步记录输入/输出/耗时 |

### Phase 2: 代码分析升级 (2-3 周)

| # | 任务 | 工时 | 验收标准 |
|---|------|------|---------|
| 2.1 | tree-sitter 集成 + C grammar | 2 天 | C 文件可解析为 AST |
| 2.2 | AST → CodeGraph 构建器 | 3 天 | 函数/变量/信号/边关系完整 |
| 2.3 | 行为模式提取 (HoldRelease 等) | 2 天 | 等价或优于现有正则提取 |
| 2.4 | 状态机提取 | 2 天 | switch-case/goto 状态机可识别 |
| 2.5 | CodeGraph 增量更新 | 1 天 | mtime/hash 检测变化 |

### Phase 3: 专家面板重构 (2 周)

| # | 任务 | 工时 | 验收标准 |
|---|------|------|---------|
| 3.1 | LangGraph 状态图定义 | 1 天 | 图可编译 |
| 3.2 | 5 专家节点迁移 | 2 天 | 输出等价于现有面板 |
| 3.3 | 主持人挑战 + 收敛逻辑 | 1 天 | 3 轮对话完整 |
| 3.4 | prompt 外部化管理 | 1 天 | prompt 从代码分离 |

### Phase 4: 代码修复引擎 (1-2 周)

| # | 任务 | 工时 | 验收标准 |
|---|------|------|---------|
| 4.1 | CodeFixEngine 架构设计 | 1 天 | 设计文档通过评审 |
| 4.2 | CodeGraph → 代码定位 | 1 天 | 可从结论中提取 file:line |
| 4.3 | coder LLM diff 生成 | 1 天 | 输出 valid unified diff |
| 4.4 | 安全审查集成 | 1 天 | embedded-c-runtime-safety 检查通过 |
| 4.5 | 效果预估 (what-if 扩展) | 1 天 | 可模拟逻辑修改效果 |

### Phase 5: 管线精简 + 记忆简化 (1 周)

| # | 任务 | 工时 | 验收标准 |
|---|------|------|---------|
| 5.1 | 管线步骤合并 (15→8) | 2 天 | 等价输出，步骤减少 |
| 5.2 | ContextBudget 智能优化 | 1 天 | 截断率降低 |
| 5.3 | 记忆系统简化 (6→3 层) | 1 天 | API 向后兼容 |
| 5.4 | 端到端回归测试 | 1 天 | 现有案例诊断结果一致 |

---

## 9. 总工作量估算

| Phase | 工时 | 依赖 |
|-------|------|------|
| Phase 1: 基础层加固 | 5 天 | 无 |
| Phase 2: 代码分析升级 | 10 天 | Phase 1 |
| Phase 3: 专家面板重构 | 5 天 | 无 (可与 Phase 2 并行) |
| Phase 4: 代码修复引擎 | 5 天 | Phase 2 |
| Phase 5: 管线精简 | 5 天 | Phase 1-4 |
| **合计** | **30 天** | — |

---

## 10. 附录

### A. 调研项目汇总

详见 GitHub 调研部分（对话中已输出）。

### B. 现有文档索引

| 文档 | 路径 |
|------|------|
| Master Handoff | `docs/technical/codegraph-handoff-master.md` |
| 数据流与架构评估 | `docs/technical/data-flow-and-architecture-assessment.md` |
| CodeGraph Phase 1 | `docs/technical/codegraph-phase1-handoff.md` |
| CodeGraph Phase 2 | `docs/technical/codegraph-phase2-handoff.md` |
| ai/ 模块说明 | `ai/AGENTS.md` |
| memory/ 模块说明 | `memory/AGENTS.md` |
| parsers/ 模块说明 | `parsers/AGENTS.md` |

### C. 待确认项

| 编号 | 问题 | 建议 |
|------|------|------|
| Q1 | LangGraph vs AutoGen: 专家面板用哪个框架？ | 推荐 LangGraph（图化编排，更适合 3 轮辩论流程） |
| Q2 | tree-sitter 编译环境是否可用？(需要 C compiler) | 需要确认 Windows MSYS 环境是否支持 |
| Q3 | MF4 数据是否有真实测试用例？ | 需要用户提供至少 1 个 MF4 文件用于开发 |
| Q4 | CodeFixEngine 生成的 diff 是否需要自动化验证？ | 建议先用 `clang -fsyntax-only` 做语法检查 |
| Q5 | 记忆系统简化是否会影响 AutoDream？ | 需要评估 Phase 3-4 的整合逻辑 |
