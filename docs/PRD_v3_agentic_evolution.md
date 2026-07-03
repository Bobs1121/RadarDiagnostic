# radarAnalyze V3 架构演进 PRD：Agentic 化与深度模块化

> **版本**: 3.0.0 (Draft)
> **日期**: 2026-07-02
> **理念来源**: Claude Code (CLI-first Autonomous Agent), Cursor (AST-based Semantic Context)

## 1. 演进背景与核心痛点
当前 V2 系统实现了端到端的自动化诊断，但在向生产级工具演进时，遇到了传统“瀑布流管线（Linear Pipeline）”的瓶颈：
1. **死板的执行流**：Orchestrator 是串行硬编码的（抓代码 -> 跑TPE -> 查信号 -> 专家组）。如果某个环节不需要（例如客户只想查个信号），或者某个环节失败，系统缺乏像人类一样的“变通能力”。
2. **交互性缺失（无 HITL）**：诊断全黑盒，耗时 5 分钟后才出 HTML 报告。如果在第 1 分钟 AI 发现缺失 DBC 文件，它无法主动停下来询问工程师，只能硬着头皮报错或瞎猜。
3. **上下文低效**：传统的 RAG 暴力塞入整个代码段，消耗大量 Token。

## 2. 核心设计理念 (The Philosophy)

我们参考 Claude Code 和 Cursor，引入以下核心理念重塑 `radarAnalyze`：

### 2.1 Agentic Loop (自主智能体循环) 代替 Linear Pipeline
放弃写死的 15 步诊断管线。将系统升级为 **Tool-Augmented Agent (工具增强型智能体)**。
系统给 LLM 提供一个工具箱（Tools），LLM 根据用户的自然语言输入，自主决定调用什么工具、按照什么顺序调用。
* **工具箱例子**：`search_code(ast_query)`, `plot_signals(signals)`, `run_tpe(rule)`, `ask_user(question)`。
* **行为模式**：`观察(Observation)` -> `思考(Thought)` -> `行动(Action/Tool)` -> `观察`... 直到得出结论。

### 2.2 Local Workspace (局部工作区与记忆)
借鉴 Cursor/Claude Code 的 `.cursorrules` / `.claude` 思想，全面落实**“项目模块化与隔离”**：
所有和特定车型/项目相关的配置、DBC、历史经验，不再作为全局配置，而是下放到项目根目录的专属隐藏文件夹（如 `.radar_workspace`）或 `workspaces/<project>` 目录下。系统启动时就地读取，实现强隔离的多租户机制。

### 2.3 Human-in-the-loop (HITL) 与流式 CLI (Streaming UX)
CLI 不再是一个只接收参数的启动器，而是一个交互式 REPL（Read-Eval-Print Loop）。
当 Agent 遇到模棱两可的情况（例如：“我发现了两个车速信号 `VehSpd` 和 `EgoSpd`，请问该用哪个？”），它会通过 `ask_user` 工具暂停并等待工程师输入，而不是盲目猜测。

---

## 3. 功能模块定义 (Modular Features)

### 3.1 核心驱动模块 (The Brain)
- **`AgentOrchestrator`**: 基于 LangGraph 或 ReAct 框架的智能体循环。维护对话历史和工具调用状态。
- **`ContextManager`**: 负责 Token 预算的动态管理，根据 LLM 的 Context Window 自动对返回的长数据（如巨量 CAN 帧）进行截断或摘要（Summarize）。

### 3.2 独立工具库 (The Toolset) - 可单点使用也可被 Agent 调用
- **`DataTools`**:
  - `query_can_signal(signal_name, time_range)`
  - `detect_temporal_pattern(pattern_type, signals)` (原 TPE 引擎)
  - `render_signal_plot(signals)` (今日刚实现的独立绘图)
- **`CodeTools` (AST 化)**:
  - `find_function_definition(func_name)`
  - `extract_ast_dependencies(var_name)` (原 CodeGraph)
- **`MemoryTools`**:
  - `read_project_requirements()`
  - `search_past_diagnoses(keyword)`

---

## 4. 非功能性需求
1. **可靠性**：任何 Tool 的崩溃（如解析异常）都会被封装为报错字符串返回给 LLM（`{"error": "..."}`），LLM 将决定是重试、换个工具还是求助人类。
2. **多模态**：生成的最终结果不仅包含 HTML 报告，诊断过程的思维链（Thought Chain）要在终端流式输出。