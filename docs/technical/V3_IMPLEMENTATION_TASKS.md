# V3 软件实施方案与开发任务拆解 (Software Implementation Tasks)

本路线图指导开发者如何一步步安全、平滑地从 V2 的瀑布流架构迁移到 V3 的 Agentic 工具化架构。

## Phase 1: 物理隔离与 Workspace 基建 (Foundation)
**目标：** 实现项目上下文的物理隔离，消灭全局的 `memory/` 与 `source_docs/`。

- [ ] **任务 1.1: 创建 Workspace 基础数据结构**
  - **路径**: `core/workspace.py`
  - **实现**: 创建 `class Workspace`，内部包含加载本地 `config.yaml`，读取项目专有 DBC (`get_dbc_files()`)，以及挂载对应的记忆库 (`get_memory_dir()`) 的逻辑。
- [ ] **任务 1.2: 迁移脚手架脚本**
  - **路径**: `scripts/migrate_to_workspaces.py`
  - **实现**: 遍历当前的 `memory/projects/`，为每个已知 Variant 创建 `workspaces/<variant>`，并将对应的资源（代码图谱DB，需求文档，DBC等）移动过去。
- [ ] **任务 1.3: 解析层兼容改造**
  - **路径**: `parsers/case_loader.py`
  - **实现**: 修改 `load_case_data`，不再从全局的 `config` 读取 DBC，而是直接接收一个 `Workspace` 实例，从工作区内直接挂载专属 DBC。

## Phase 2: AST 彻底改造与工具化封装 (Toolification)
**目标：** 切断正则依赖，并将现有的分析逻辑标准化为大模型可调用的 Function Calling Tools。

- [ ] **任务 2.1: AST 条件提取器**
  - **路径**: `ai/codegraph/ast_rule_extractor.py`
  - **实现**: 编写基于 CParser 的规则提取器，全面替换现有的 `ai/rule_condition_extractor.py`。
- [ ] **任务 2.2: 基础数据工具包装 (DataTools)**
  - **路径**: `ai/tools/data_tools.py`
  - **实现**: 编写 `PlotSignalTool`, `QueryCanDataTool`, `DetectTimePatternTool`。继承一个标准的 `BaseTool` 类，对外暴露 `execute(params)` 方法和 `parameters_schema` (JSON Schema)。
- [ ] **任务 2.3: 基础静态代码工具包装 (CodeTools)**
  - **路径**: `ai/tools/code_tools.py`
  - **实现**: 编写 `FindCodeDefinitionTool`, `ExtractASTDependencyTool`。让它们直接读取 Workspace 内的 `codegraph.db`。

## Phase 3: Agentic 主脑循环 (Agent Loop)
**目标：** 引入 LangGraph 或自研的 ReAct 循环，废弃掉 15 步串行脚本。

- [ ] **任务 3.1: 状态机定义**
  - **路径**: `ai/agent_loop.py`
  - **实现**: 定义 `AgentState` (包含历史对话 `messages`，当前激活的 `workspace`，和工具执行状态 `tool_outputs`)。
- [ ] **任务 3.2: 主脑引擎实现 (AgentOrchestrator)**
  - **路径**: `ai/agent_orchestrator.py`
  - **实现**: 实现 `run_diagnosis`，通过 `while True` 循环调用大模型。捕获模型的 `tool_calls`。
- [ ] **任务 3.3: 容错与降级机制 (Try-Catch-Fallback)**
  - **路径**: `ai/tools/base.py` -> `safe_execute()`
  - **实现**: 在执行工具的基类上加装饰器，一旦 `execute()` 抛出异常，不再终止程序，而是返回格式化的 `{ "status": "error", "message": str(e) }` 给大模型，强迫大模型更换思路或求助。

## Phase 4: CLI 革命性升级与 REPL (User Experience)
**目标：** 提供带有 HITL (Human-in-the-loop) 交互的全新控制台界面。

- [ ] **任务 4.1: 新增交互工具 (AskHuman)**
  - **路径**: `ai/tools/interaction_tools.py`
  - **实现**: 编写 `AskHumanTool`，当大模型发现证据冲突时（如：缺少 DBC，不知道该用哪个车速信号），主动向用户提问。
- [ ] **任务 4.2: 终端流式 UI**
  - **路径**: `ai/repl.py`
  - **实现**: 引入 `prompt_toolkit`，建立一个持续会话环境。
- [ ] **任务 4.3: 入口切换**
  - **路径**: `cli.py`
  - **实现**: 接入 `ai.repl.RadarAnalyzeREPL`。保留传统的 `-p` 单次执行模式，新增无参直接输入 `python cli.py --workspace gen6_gwm_b26` 即进入长连接对话模式。

## 提交与审查策略 (PR Strategy)
由于改动巨大，禁止采用一个 Big Bang PR。按照以下顺序合并：
1. **PR 1**: `feat(v3/core): Introduce Workspace isolation and migration script.`
2. **PR 2**: `feat(v3/ast): Replace Regex with Tree-Sitter AST in condition extraction.`
3. **PR 3**: `feat(v3/tools): Wrap core engine capabilities into OpenAI compatible Tools.`
4. **PR 4**: `feat(v3/agent): Implement ReAct loop and interactive CLI REPL.`