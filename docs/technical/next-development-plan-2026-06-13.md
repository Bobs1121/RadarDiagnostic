# radarAnalyze v2 — 后续开发计划（2026-06-13）

> 范围: 规划与设计，部分已实施（见下方 ✅ 标记）
> 基准文档: `docs/PRD_refactor_v2.md`（v2.1.0）、`docs/technical/codegraph-handoff-master.md`
> 更新: 2026-06-14 — P0-2/P0-3/P1-1/P1-3 已实施，P1-2 延期

---

## 0. 现状与目标

**现状**（来自 handoff master）:
- Phase 1-6D 已完成；Harness Phase 2（L0/L1/L2 baseline）已可运行
- 当前主要短板：评估样本太少、L2 语义一致性不足、依赖分档不清晰、专家面板 prompt 多项目化不足

**下一阶段目标**:
1. 固化 `variant/package_profile/snapshot` 身份模型与客户材料接入边界
2. 建立可审计诊断产物（`DiagnosisBundle`）与知识沉淀主模型（`RootCausePattern` / `FixPlaybook`）
3. 建立可用的评估基线（3-5 个 ground truth + 聚合统计）
4. 在不牺牲可复现性的前提下，提高 L2 语义一致性（可选 LLM judge）
5. 让依赖与运行能力边界清晰（base/llm/panel/harness 分档 + 降级路径）
6. 真正兑现“多项目支持”（prompt/架构描述不写死，按 variant + package_profile 运转）

---

## 0.1) P0-0 — 架构底座：Variant / Package / Snapshot / Material（1-2 天）

**交付物**:
- `variant_id` / `package_profile_id` / `snapshot_id` 身份模型设计落地
- `Material Registry` 与 `StructuredRequirementSet` schema
- `DiagnosisBundle`、`RootCausePattern`、`FixPlaybook` schema

**关键约束**:
- `variant` 是客户项目级边界，例如 `coem/GWM_B26`、`apl/byd`
- `package_profile` 承载构建参数组合，决定软件包差异
- `snapshot` 绑定代码/DBC/材料/config/model hash，保证审计可复现

**验收标准**:
- 所有诊断、知识沉淀、Harness 评估都能引用同一 `snapshot_id`
- 客户需求材料能以结构化对象而非原文 prompt 的方式接入

---

## 1) P0-1 — Harness Phase 3：扩充 Ground Truth（2 天）

**交付物**:
- 新增 2-4 个 `harness/golden_truths/*_ground_truth.json`
- 对应案例目录中补齐“问题描述/期望/关键证据”素材（如 issue 报告、说明 md）
- 一份聚合输出（按功能/案例统计 overall、L0/L1/L2 分布）

**建议案例选择原则**:
- 覆盖 rear/front 各至少 1 个功能（例如 BSD + FCTB）
- 覆盖不同根因类别：algorithm / logic / signal_chain / param
- 覆盖不同数据特征：短脉冲、状态机卡死、阈值边界、抑制信号门控

**验收标准**:
- `N>=3` 个 ground truth 可被 HarnessRunner 批量评估
- 任一案例的 L0/L1 不依赖 LLM（可离线运行）
- 聚合报告能输出：平均分、最差分、top 差距项（例如 causal 低于阈值的案例列表）

---

## 2) P0-2 — Harness Phase 3：LLM-as-judge 增强 L2 ✅ 已实施 (95/100)

**状态**: `harness/llm_judge.py` 已实现 LLMJudge + ConclusionEvaluator 集成，config 已配。验证通过。

**设计原则**:
- 默认仍以 L2 baseline（概念命中 + 关键词重叠）作为“可复现下限”
- LLM judge 只作为可选增强：`final = max(baseline, llm_judge)`

**接口设计建议**:
- `enable_llm_judge: bool`（配置开关）
- `judge_model_profile: simple|complex`（沿用 model_router）
- `judge_rubric` 固化评分维度（分类、定位、因果、建议）与分值映射

**验收标准**:
- 在相同 ground truth 下，开启 LLM judge 后 L2 causal 可提升（目标：FCTA001 从 ~0.57 到 0.7+）
- LLM judge 失败/缺失依赖时不影响 baseline 跑通（只降级，不中断）

---

## 3) P0-3 — Engineering：依赖分档治理 ✅ 已实施 (90/100)

**状态**: requirements.txt 已分 base/llm/panel/harness 四档。langgraph 未安装时报友好错误。pandas 清理。

**实施记录** (ADR-019):

**目标**: 让“装什么能跑什么”一目了然，并避免 import-time 崩溃。

**依赖档位定义**（建议）:
- `base`: 数据解析/窗口检测/TPE/报告生成（确定性链路）
- `llm`: 需要调用模型的步骤（understand/conditions/probe/diagnose/fix）
- `panel`: 专家面板编排（LangGraph）
- `harness`: 评估体系（pytest + harness runner）

**验收标准**:
- 文档化安装矩阵（base/llm/panel/harness）与对应可运行命令
- 缺失可选依赖时，错误提示包含“如何安装/如何降级”的明确指引

---

## 4) P1-1 — 5E.1：ContextBudget 动态总预算 ✅ 已实施 (90/100)

**状态**: `compute_budget()` 已实现并集成 orchestrator。因子：CG 节点 + 窗口数 + 时长 + 模型上下文。

**实施记录** (ADR-020):

**设计点**:
- 输入信号：CodeGraph 规模、case 时长/窗口数量、信号数量、是否启用专家面板
- 输出：`total_chars` 的动态上限 + 每块 budget 分配策略

**验收标准**:
- 同一案例重复运行预算稳定（可复现）
- 复杂案例预算上调、简单案例预算下调，且不会超出安全上限

---

## 5) P1-2 — 5E.2：记忆系统简化 6→3 层 ⏸️ 延期

**延期原因**: 10+ 调用方依赖各独立层，合并风险 > 当前收益。等 P0 项目稳定后再评估。

**建议简化方向**:
- 保留：项目级知识（L1）、会话（L4）、统一知识库（合并 L2/L3/L5/L6）
- 关键在于：迁移策略与向后兼容 API

**验收标准**:
- 旧 API 调用不报错（向后兼容层）
- 有迁移脚本/自动迁移策略（至少支持“读旧写新”过渡）

---

## 6) P1-3 — 5E.3：专家面板 prompt 多项目适配 ✅ 已实施 (88/100)

**状态**: `load_expert_system(expert_id, project_key)` 支持项目级覆写。ExpertPanel 透传 project_key。已创建 sc6h/gwm_b26/cr5cb 覆写目录。

**实施记录**:

**设计点**:
- prompt 模板用占位符（如 `{{architecture_desc}}`、`{{key_source_files}}`）
- 填充来源：config + CodeGraph 查询结果（模块/调用链/信号链路摘要）

**验收标准**:
- 任意 project_key 下不需要修改 prompt 文件即可运行
- prompt 中不出现写死的项目文件路径（除非来自配置注入）

---

## 7) P2 — 5C.5：LLM 全量语义标注（BLOCKED）

**解锁条件**:
- 可用的 LLM API key/配额（或 Bosch Model Farm 资源）
- 明确标注预算与可回滚策略（避免一次性全量失败）
