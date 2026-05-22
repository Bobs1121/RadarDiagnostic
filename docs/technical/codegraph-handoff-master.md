# radarAnalyze — Master Handoff

> 更新: 2026-05-22 (信号链补全完成 + CodeFixEngine 设计待启动)
> 分支: `refactor/codegraph`
> 状态: 信号链 READS_SIGNAL/WRITES_SIGNAL 边从 0 → 463，CodeGraph 基础设���完备

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

### 🔧 进行中 / 待优化

| 项目 | 优先级 | 说明 |
|------|--------|------|
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

### ADR-004: Regex 而非 AST 解析器

**决策**: 初始阶段用正则表达式提取 C 代码模式，不用 Clang/GCC AST。

**理由**:
- 速度快（18 文件 6 秒 vs AST 可能几分钟）
- 量产代码结构相对规范，正则有足够覆盖率
- 后续可逐步加 AST 精化

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
| `data-flow-and-architecture-assessment.md` | **数据流完整分析 + 鲁棒性评估 + 实施路线图** |
| `codegraph-phase2-handoff.md` | CodeGraph Phase 2 交付 |
| `codegraph-phase1-handoff.md` | CodeGraph Phase 1 交付 |
| `codegraph-handoff-v2.md` | CodeGraph 完整设计 (schema/query/render) |
| `00-总览.md` ~ `09-记忆系统.md` | 各模块架构文档 |

---

## 下次对话从这里开始

1. 读这个 handoff 了解当前状态
2. 读 `docs/technical/data-flow-and-architecture-assessment.md` 了解数据流分析和架构评估
3. 读 `docs/technical/codegraph-phase2-handoff.md` 了解 Phase 2 细节
4. 根据需求池决定下一步工作
5. 工作完成后更新本 handoff 的"当前状态"和"Git 提交历史"

**下一步工作**:
- CodeFixEngine 设计 + 实现 (ai/codefix_engine.py) — 将专家面板的文字"修复建议"转化为结构化 diff
- CodeGraph Phase 3: 专家面板注入 CodeGraph 数据（call chain + var deps + signal mapping）
- MF4 Parser (parsers/mf4_parser.py)
- 交互追问模式

**重要**: 每次对话结束前，更新本文件的"当前状态"和"需求池"。这是跨会话协作的唯一可靠通道。
