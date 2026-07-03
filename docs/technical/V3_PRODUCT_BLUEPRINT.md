# radarAnalyze V3 终极产品蓝图与模块化全景图 (Product Blueprint)

> **版本**: 3.0.0-Product-Blueprint
> **角色**: 产品经理 (PM) & 首席架构师 (Chief Architect)
> **目标**: 跳出“脚本工具”的思维局限，以“企业级 ADAS AI 研发中台”的视角，重新审视并定义系统所需的全部生命周期模块。

---

## 1. 宏观产品愿景 (Product Vision)
**“打造 ADAS 软件工程师的 AI 协同操作系统”**
不仅仅是事后排查 Bug，而是要贯穿 **需求定义 -> 代码编写 -> 数据验证 -> 持续回归** 的全生命周期。系统必须具备极高的可扩展性，适应不同主机厂（OEM）的强隔离安全要求。

---

## 2. 模块化全景图：六大核心支柱 (The 6 Pillars)

经过头脑风暴与企业级系统架构推演，一个真正完善的 V3 系统应当包含以下 **6 大核心子系统（Pillars）**。之前我们讨论的 4 个模块主要集中在中间两层，现对其进行完整补全：

### 支柱 1: 数据与资产基座 (Data & Asset Foundation)
**职责**: 解决“食粮”问题。处理极其繁杂的多源异构文件和配置。
* **1.1 Workspace Manager (工作区引擎)**: 核心。处理 Core+COEM 继承，提供多租户沙盒。
* **1.2 Data Ingestion Pipeline (数据流管线)**: 支持本地文件（BAG/BLF/MF4）极速解析、时间戳对齐 (TimeSync)、流式降采样处理（防止 OOM）。
* **1.3 DBC & Matrix Compiler (字典预编译器)**: 将 CAN/ETH 矩阵预编译为高性能 SQLite 索引，供 LLM 极速反推信号。

### 支柱 2: 语义代码引擎 (Semantic Code Engine)
**职责**: 解决“懂系统”的问题。将 C/C++ 转换为 AI 能懂的语言。
* **2.1 AST CodeGraph (确定性语法图谱)**: 提取函数调用、变量依赖、宏定义替换。这是“骨骼”。
* **2.2 LLI Wiki Generator (语义百科引擎)**: Auto-Dream 模块的核心。用大模型把 AST 转成人类/AI 友好的逻辑解释文档。这是“血肉”。
* **2.3 Requirements Parser (需求结构化器)**: 把 OEM 的 PDF 需求文档转化为可验证的 JSON Schema。

### 支柱 3: 智能体中枢 (Agentic Core)
**职责**: 解决“思考与调度”的问题。代替过去的硬编码脚本。
* **3.1 ReAct Orchestrator (主脑路网)**: 根据用户输入，动态规划思考路径，分发工具（Tools）。
* **3.2 Context & Token Budgeter (上下文管理器)**: 极其重要。动态截断超长 CAN 帧、提取摘要，防止 LLM 被巨量上下文挤爆（Context Window Overflow）。
* **3.3 Tool Registry (功能插件库)**: 标准化的工具注册表，包含 `plot_signals`, `run_tpe`, `query_ast` 等。

### 支柱 4: 持续验证与评估 (Continuous Validation & Harness)
**职责**: 解决“AI 究竟准不准”以及“代码是否退化”的问题。（这一块目前有基础，但需要拔高）
* **4.1 Golden Truth Engine (黄金测试库)**: 管理已知的经典 Bug 案例。
* **4.2 L0-L2 Scoring Matrix (量化评分器)**: 自动化打分机制。
* **4.3 CI/CD Adapter (流水线适配器)**: **(缺失的拼图)** 允许系统在 GitLab CI / Jenkins 中以 Headless 模式运行。每次有新人提交代码，自动拉取历史边界数据跑一遍，出具《代码变更影响雷达诊断报告》。

### 4. 支柱 5: 体验与协同界面 (Experience & Interfaces)
**职责**: 解决“人机交互”问题。
* **5.1 Interactive REPL CLI (流式终端)**: 面向硬核开发者的多轮对话命令行。
* **5.2 VSCode / Cursor Extension (IDE 插件)**: **(核心发力点)** 把 Data Explorer 的数据帧注入到 IDE 中，实现“拿着实车路测数据跑本地断点 Debug”。
* **5.3 Standalone Web Report (富文本报告)**: 包含可交互 Plotly 图表、拓扑图节点点击高亮的 HTML。

### 支柱 6: 合规与安全边界 (Governance & Security)
**职责**: 解决“数据出不了厂”和“商业机密泄露”的问题。
* **6.1 PII & IP Scrubber (脱敏器)**: **(严重缺失)** 在把报错代码和 CAN 信号发给远端大模型（如 GPT-4 / Qwen）前，自动替换掉车架号（VIN）、绝密算法参数名等敏感资产。
* **6.2 Local Model Fallback (纯内网模式)**: 配合 Ollama 或 vLLM，在彻底断网的保密研发室，切换到量化小模型（如 Llama-3-8B）只做简单匹配。

---

## 3. 架构师与产品经理的综合评估

**当前的优势 (Where we are strong):**
我们目前的系统在 **支柱 1 (数据解析)** 和 **支柱 4 (Harness 评估)** 的基础打得非常扎实。尤其是新加的 MF4 解析和 L0-L2 评分系统，在行业内是很超前的。

**当前的盲区 (What we missed & Need to add to V3):**
1. **脱敏与安全 (Pillar 6)**: 车企对于源码和数据的安全性要求极高。目前的系统会把大段 C 代码直接发送出去。我们需要在 Agent Tool 之前加一层 **Scrubber (数据清洗器)** 模块。
2. **Context 管理机制 (Pillar 3.2)**: 目前简单粗暴地拼接证据容易超长，必须引入专门的中间件对长文本做 Map-Reduce 压缩。
3. **CI/CD 适配 (Pillar 4.3)**: 系统不能只在个人电脑上跑，它必须能作为守护进程运行在服务器上。

## 4. 实施策略修正

基于以上蓝图，我们的实施路线图 (Implementation Plan) 需要扩充：
* 在 Phase 2 (工具化) 阶段，引入 **Context Manager** 和 **Security Scrubber** 基类。
* 在未来的 Phase 5 (超越 CLI)，正式立项研发 VSCode Extension 协议接口。