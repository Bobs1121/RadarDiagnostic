# V3 架构实施计划 (Implementation Plan)

本计划指导系统如何从 V2 的瀑布流式架构演进为 V3 Agentic Tool-Driven 架构。我们采用渐进式演进策略，保证在任何一个阶段，现有系统的基础诊断能力都不被破坏。

## Phase 1: 基础设施迁移与项目沙盒化 (Foundation)
**目标：** 实现项目的强隔离配置（工作区概念）并完成底层解析器的加固（如 AST 与 MF4）。

1. **工作区重构 (Workspace Isolation)**
   - 编写迁移脚手架，将现有的全局 `memory/`、`source_docs/`、`dbc/` 根据 `Variant` 规范迁移到 `workspaces/<variant_name>/` 下。
   - 修改 `config.py` 和 `cli.py`，使引擎启动时优先读取项目本地的配置（如 `.radar_workspace/config.yaml`）。
2. **彻底切断正则依赖 (AST Transition)**
   - 依据 `docs/technical/ast_transition_plan.md`，将 `RuleConditionExtractor` 完全替换为 `ASTRuleConditionExtractor`。
   - 补齐 `pattern_extractor_ast.py`，并弃用遗留的 Regex 版。

## Phase 2: 工具化与包装 (Toolification)
**目标：** 将现有的、耦合在 `Orchestrator` 中的各个功能步骤，抽取包装为符合 OpenAI/Claude Function Calling Schema 的标准化 Tools。

1. **抽取数据分析工具**
   - 包装 `plot_signals` 为 `render_signal_plot_tool(signals: list[str])`。
   - 包装 `FrameStore` 查询能力为 `query_signal_data_tool(signal_name: str, time_window: list[float])`。
   - 包装 TPE 引擎为 `detect_time_pattern_tool(...)`。
2. **抽取静态分析工具**
   - 包装 CodeGraph 为 `find_code_definition_tool(symbol: str)`。
3. **引入 HITL 工具**
   - 新增 `ask_human_tool(question: str, options: list[str])`，允许模型主动在终端发起提问。

## Phase 3: 重构引擎大脑 (The Agent Loop)
**目标：** 用基于大模型规划的智能循环替代现有的静态管线。

1. **废弃 V2 Orchestrator**
   - 编写全新的 `AgentOrchestrator (ai/agent_loop.py)`。
   - 核心循环逻辑（Pseudocode）：
     ```python
     history = [{"role": "user", "content": "客户说 FCTA 在 2s 内没触发，请诊断。"}]
     while True:
         response = llm.chat(history, tools=AVAILABLE_TOOLS)
         if response.wants_to_call_tool:
             result = execute_tool(response.tool_call)
             history.append({"role": "tool", "content": result})
         elif response.wants_to_ask_human:
             answer = prompt_user(response.question)
             history.append({"role": "user", "content": answer})
         else:
             generate_final_report(response.content)
             break
     ```
2. **动态 Context 摘要机制**
   - 当 `execute_tool` 返回巨大的 CAN 数据流时，注入中间摘要层（Summarizer），提取关键跳变点再交给 Agent 主脑，防止 Token 爆炸。

## Phase 4: CLI 交互革命 (Interactive UX)
**目标：** 提供对标 Claude Code / Cursor 的终端使用体验。

1. **Rich Console 流式输出**
   - 引入流式（Streaming）渲染，在终端实时打印大模型当前的思考过程（Thought: 正在查找 FCTA 的触发阈值...）。
2. **交互式会话**
   - 将单纯的 `python cli.py` 改造为支持上下文延续的 REPL（交互式命令行）。
   - 例如，出具报告后，用户可以继续敲入：“把报告里提到的车速信号那张图放大一下。” 引擎带着上下文直接触发绘图模块。

## 验收标准 (Definition of Done)
- **解耦验收**：可以直接在终端调起绘图和查询工具，不依赖主控分析逻辑（已部分完成）。
- **容错验收**：切断某一个文件的代码时，引擎不会崩溃报错，而是会在终端打出：`[Agent] 发现缺少 FCTCtrl.c 代码，我将跳过条件分析直接检查信号。`
- **隔离验收**：多开两个终端同时跑不同的项目（如长城、比亚迪），双方的配置、记忆与输出完全不干扰。