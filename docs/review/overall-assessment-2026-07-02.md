# radarAnalyze 角雷达 AI 诊断系统 - 架构与设计评估报告

> **评估日期**: 2026-07-02
> **评估人**: AI Agent (架构师视角)
> **评估目标**: 从架构设计、功能性、多项目适配性以及可靠性四个维度对当前系统进行全面审查，并为后续改进提供指导建议。

---

## 1. 架构设计 (Architecture Design)

**✅ 优势与亮点：**
* **高度模块化与分层设计**：系统清晰地划分了数据解析层（`parsers`）、AI 分析与管线编排层（`ai.orchestrator` / `expert_panel`）、记忆与知识图谱层（`memory` / `ai.codegraph`）以及评估测试层（`harness`）。
* **Pipeline 管线模式**：Orchestrator 采用多阶段（Phase）流式处理，从问题分类、测试窗口检测、条件提取、TPE 时序模式引擎，最终到专家面板，符合复杂诊断任务的最佳实践。
* **双模型路由（Model Router）**：能够根据任务复杂度自动在不同规模的 LLM 之间路由（如 `complex` 走大模型，`simple` 走小模型），有效平衡了成本与智力。

**⚠️ 改进空间：**
* **源码提取的脆弱性**：目前的条件提取（`rule_condition_extractor`）和模式挖掘（`pattern_extractor`）仍高度依赖正则表达式（Regex）。在面对 C 语言复杂的宏定义、嵌套结构体和指针跳转时，容易出现提取失败或匹配错误。虽然已经引入了 `CodeGraph` (AST)，但并未完全替代 Regex。
* **管线耦合度较高**：Orchestrator 中的多步证据收集过程耦合较紧。例如，某个中间步骤（如提取特定函数的控制流）如果抛出异常，容易导致整个耗时 5 分钟的管线崩溃。需要引入更好的“优雅降级（Graceful Degradation）”机制。

## 2. 功能性 (Functionality)

**✅ 优势与亮点：**
* **端到端闭环诊断**：业界罕见地实现了从 Raw Data (`.bag` / `.blf` / `.mf4`) 到最终代码级修复建议的完全自动化，极大缩短了 ADAS ASW 工程师排查 Bug 的时间。
* **多模态查询与可视化**：新增的独立信号绘图模块（`plot_signals.py`）和 `DataQueryEngine`，允许工程师直接用自然语言（“提取 FCTA 报警未触发的相关信号”）实现秒级离线图表渲染，工具的灵活性和实用性极高。
* **记忆巩固机制 (Auto-Dream)**：通过离线的休眠学习（Dream），系统能主动阅读 C 源码提取常量（Constants）、变量链路和逻辑片段，构建长期项目记忆（L6 Code Knowledge），非常具有前瞻性。

**⚠️ 改进空间：**
* **执行耗时与 Context 预算限制**：完整诊断耗时较长。提取的海量证据（Timeline, Code Snippets, Parameters）容易爆掉 LLM 的 Context Token 预算，现有的 `ContextBudget` 虽然会做 Truncate，但粗暴截断可能丢失关键诊断线索。
* **UI 交互单一**：目前完全基于 CLI + 输出 HTML 报告的形式。对于诊断过程中的交互（如 AI 询问工程师是否补充提供某段 CAN 报文），尚缺乏易用的交互界面支持。

## 3. 多项目适配 (Multi-project Adaptability)

**✅ 优势与亮点：**
* **V2 身份引擎（Identity System）设计卓越**：系统正在从硬编码的单项目模式向 `Variant`（项目变体，如 `gen6/gwm_b26`）和 `Package Profile`（软件包配置）演进。通过配置文件和 `Variant` 定义分离，系统可以轻松支持不同的车型和雷达配置。
* **DBC 数据驱动**：将项目特有的 CAN 信号映射交给对应车型的 DBC 文件和 `DbcLoader` 处理，AI 引擎本身保持通用逻辑（只认抽象的 FCTA / BSD 业务语义）。

**⚠️ 改进空间：**
* **遗留代码债务**：`cli.py` 和底层逻辑中仍残留部分对旧版 `-P project` 的兼容处理。
* **信号映射的泛化性**：不同主机厂（OEM）对于雷达状态和报错的命名习惯差异极大。即使有 DBC，AI 从自然语言问题（如“系统状态异常”）到具体物理 CAN 信号（如 `EPS_SteerWheelAg`）的映射准度，依然高度依赖于 prompt 中的字典枚举，跨项目迁移时可能存在映射断层。

## 4. 可靠性与稳定性 (Reliability)

**✅ 优势与亮点：**
* **Harness 量化评估系统**：这是 V2 重构中最亮眼的基础设施。通过 L0（结构完整性）、L1（证据覆盖率）、L2（结论正确性）的自动化打分，结合 Golden Truths（黄金标准），将非确定性的 LLM 输出转化为可 CI/CD 拦截的定量指标。
* **Snapshot 快照系统**：在每次诊断时保存代码、DBC 和物料 Hash，保证了如果昨天跑过的 Case 今天跑结果不一样，可以溯源是不是源码发生了改变。

**⚠️ 改进空间：**
* **数据解析的边界 Case**：实车路测数据（尤其是 MF4 / Bag）体积庞大且包含复杂的嵌套类型（如 VLSD 变长数据块）。之前 `pandas` / `asammdf` 全量解析会导致内存 OOM 或运行崩溃。目前采用了白名单/按需提取机制缓解，但长期看需要流式解析底层支撑。
* **大模型解析 JSON 的不确定性**：在 `DataQueryEngine` 等地方，如果 LLM 返回的 JSON 格式错误或含有 Markdown 代码块包裹，现有的 fallback 逻辑可能会漏捕获，从而阻断分析。

---

## 5. 下一步改进建议 (Recommendations for Action)

基于以上评估，建议接下来的改进工作围绕以下 **三个优先级** 展开：

### P0：加固管线可靠性与容错能力 (Robustness)
1. **沙盒化管线执行**：在 `Orchestrator` 中引入全局 Try-Catch-Fallback 机制。如果 `pattern_extractor` 崩溃，应当允许系统带着“缺失 TPE 特征”的不完整证据链继续请求专家面板，而不是直接退出进程。
2. **强化 LLM 输出解析器**：引入 Pydantic / LangChain 的 StructuredOutputParser，配合 Retry 机制（JSON Decode Error 时自动带错误信息要求模型重试生成），杜绝解析异常。

### P1：代码理解引擎的 AST 化 (AST Transition)
1. **弃用正则表达式提取**：全面启用已有的 `ai/codegraph/ast_parser.py`。基于树结构的语法分析能够 100% 准确地捕捉跨行 `if` 条件、函数依赖和变量作用域，彻底消除正则漏配问题。
2. **过滤局部噪音**：执行 PRD (FR-002) 中提到的局部变量过滤，减少无意义控制变量（如 `i`, `temp`）进入上下文，节约 Token 预算。

### P2：可视化与多项目系统清理 (Cleanup & Visualization)
1. **彻底移除 V1 遗留配置**：清理所有 Legacy 的 `-P` 项目处理逻辑，强制全系统使用 `Variant` 身份验证，减少多项目适配时的逻辑分支维护成本。
2. **交互式微调图表**：为今天新增的 `plot_signals.html` 增强数据导出和基准线（Baseline）对比功能，方便开发人员直接截取带有问题的信号波形贴入 JIRA 工单中。