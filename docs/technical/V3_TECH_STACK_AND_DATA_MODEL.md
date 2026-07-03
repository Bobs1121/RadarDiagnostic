# V3 核心技术选型与调度设计 (AI Triage Tech Stack)

> **定位**: 专注于实车数据分诊 (AI Triage)，导通“需求 -> 代码 -> 数据”关联链路，支持 Core+COEM 架构的离线桌面级系统。
> **原则**: 零后台服务、极简依赖、纯本地极速计算。

---

## 1. 代码仓与项目化管理 (Code Repo & Project Management)
**场景**: 同一个 Git 仓内包含公共基础代码（Core/Common）和分散在 `coem/***` 目录下的多客户定制代码。
* **隔离管理选型**: **Workspace (配置沙盒) + 动态 Path 路由**
  * 在系统内建立 `.workspaces/<variant_name>` 沙盒。
  * **配置文件** (`config.yaml`) 采用 YAML 继承机制。
* **代码加载策略**: 
  * 引擎不硬编码路径。当指定客户为 `BYD-SC6H` 时，`Workspace` 模块会生成一个解析优先级列表：`["cr60_light/coem/BYD", "cr60_light/common"]`。
  * AST 在生成拓扑图时，按照该优先级抓取 C/C++ 文件。同名函数或同名宏定义，`coem` 目录下的实现将直接覆盖 `common` 目录的默认实现。

## 2. 需求管理结构化 (Requirements Management)
**场景**: 客户给定的验收标准（比如 FCTA 车速必须 < 30km/h，迟滞 200ms）需要被 AI 严谨执行。
* **技术选型**: **YAML + Pydantic (动态 JSON Schema)**
* **存储**: 放在 `.workspaces/<variant>/requirements/` 下。
* **机制**: 将文本需求转录为结构化的 YAML。在 Agent 运行时，利用 `Pydantic` 库将 YAML 动态加载为 Python Object，并生成严格的验证规则。诊断结果必须通过 Pydantic 的 `model_validate()`，避免大模型“胡编乱造”结论。

## 3. 代码结构化选型 (Code Topology & Logic)
**场景**: 绝不能实时读取全量代码。需要无数据时也能当代码助手。
* **底层骨架选型**: **AST (tree-sitter) + NetworkX (纯内存图计算)**
  * **机制**: 在初始化时（预编译），AST 遍历 `coem`+`common` 代码，抽取控制流和变量流，构建为 `NetworkX` 的有向无环图 (DAG)。并将其序列化存盘。
  * **提问时**: 比如查 `VehSpd` 的去向，直接调 `nx.descendants()` 毫秒级返回下游关联的 5 个函数名。
* **表层血肉选型**: **LLI Wiki (Markdown 语义总结)**
  * **机制**: 大模型基于上述生成的 NetworkX 图，为每个子系统（如 RCTB 状态机）离线生成一篇结构化的 Markdown 总结。
  * **结合**: Agent 先读 Markdown 理解总体业务（大模型对自然语言的理解度远高于 C 语言指针），再查 NetworkX 精确定位。

## 4. 记忆系统选型 (Memory System)
**场景**: 沉淀不同项目的 Bug 规律和排查流程经验。
* **技术选型**: **SQLite FTS5 (全文本检索) + JSON 混合架构** (放弃沉重的 ChromaDB/向量库)
* **设计**:
  1. **Triage History (诊断历史)**: 存入 SQLite。每次诊断结束，把 `[症状, 异常信号, 对应代码行, 结论]` 存为一条记录。
  2. **检索机制**: 利用 SQLite 原生的 FTS5 (Full-Text Search) 插件实现极速的关键词检索，足够应对单机数十万条的报错特征库，无需引入任何 C++ 编译的向量模型库，做到开箱即用。

## 5. 异构数据解析选型 (Data Extraction)
**场景**: 离线极速吞吐 GB 级 bag/blf/mf4，提取信号并画图。
* **技术选型**: **DuckDB + Apache Arrow**
  * `cantools` / `asammdf` 负责将底层的 BLF/MF4 解码为时序数据。
  * 抛弃缓慢的 `pandas.DataFrame` 拼接，直接将解析后的数据推入 **DuckDB (嵌入式列式数据库)** 的内存视图。
  * 当 AI 说“查出车速大于 60 且 FCTA 没有报警的时刻”，背后将直接转换为 DuckDB 的极限 SQL 查询，性能较传统方式提升数十倍，彻底解决 OOM 问题。

## 6. 内容调度与主脑框架 (Agentic Triage Loop)
**场景**: 调度上述所有结构化内容，导通“需求->代码->数据”的链路。
* **技术选型**: **LangGraph (状态机路由) + Tool Calling**
* **结构化调度流程**:
  1. **State 定义 (状态池)**: 包含 `current_req` (当前需求), `topology_evidence` (代码证据), `data_evidence` (数据证据)。
  2. **Node 1: 意图与需求对齐**: LLM 查看用户的提问，去 YAML 库加载对应的需求指标，定下破案基调。
  3. **Node 2: 代码拓扑推演 (代码助手)**: 调用 `CodeGraph Tool` 和 `DBC Tool`，找到实现该需求的 C 语言变量和其绑定的物理 CAN 信号。
  4. **Node 3: 数据实证 (数据助手)**: 拿着拿到的 CAN 信号名，去 `DuckDB` 执行查询和画图。
  5. **Node 4: Triage 合成**: 对比 Node 1(需求) 与 Node 3(实际数据)。如果冲突，根因定位在 Node 2(代码逻辑)。输出诊断报告。