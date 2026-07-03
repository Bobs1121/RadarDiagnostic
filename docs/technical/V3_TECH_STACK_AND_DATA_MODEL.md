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
**场景**: 绝不能实时读取全量代码。需要无数据时也能当代码助手。处理庞大的 C/C++ AST 依赖树（数万个节点）。
* **底层骨架选型**: **AST (tree-sitter) + KùzuDB (嵌入式图数据库)**
  * **机制**: 弃用纯 Python 的 `NetworkX`（在万级节点以上内存占用高且慢）。引入 `KùzuDB`，它是一个类似 SQLite 但专为图结构设计的嵌入式本地图数据库，支持 **Cypher** 查询语言。在预编译时，AST 解析出的 `[函数, 变量, 状态]` 及它们之间的 `CALLS, READS, WRITES` 关系将存入本地的 KùzuDB。
  * **提问时**: 大模型非常擅长写 Cypher（如 `MATCH (c:Condition)-[:AFFECTS]->(s:Signal) RETURN s`）。Agent 通过执行 Cypher 语句，实现出核（Out-of-Core）的极速追踪，无需将庞大图谱读入内存。
* **表层血肉选型**: **LLI Wiki (Markdown 语义总结)**
  * **机制**: 大模型基于上述生成的图，为每个子系统（如 RCTB 状态机）离线生成一篇结构化的 Markdown 总结。
  * **结合**: Agent 先读 Markdown 理解总体业务（大模型对自然语言的理解度远高于 C 语言指针），再查 KùzuDB 精确定位。

## 4. 记忆系统选型 (Memory System)
**场景**: 沉淀不同项目的 Bug 规律和排查流程经验，支持模糊语义检索。
* **技术选型**: **LanceDB (Serverless 本地向量库)**
  * **设计**: 弃用 `SQLite FTS5`（仅能全文本字面匹配）和 `ChromaDB`（需复杂后台依赖）。`LanceDB` 是专为 Arrow 优化的轻量级本地向量库，`pip install lancedb` 即可。
  * 每次诊断结束，把 `[症状, 异常信号, 对应代码行, 结论]` 转化为 Vector 存入。大模型下次排查时通过计算语义相似度（Semantic Search）召回历史相似案例。

## 5. 异构数据解析选型 (Data Extraction)
**场景**: 离线极速吞吐 GB 级 bag/blf/mf4，提取信号并画图。
* **技术选型**: **DuckDB + Apache Arrow**
  * `cantools` / `asammdf` 负责将底层的 BLF/MF4 解码为时序数据。
  * 抛弃缓慢的 `pandas.DataFrame` 拼接，直接将解析后的数据转为 `.parquet` 或 Arrow 流，推入 **DuckDB (嵌入式列式数据库)** 的内存视图。
  * 当 AI 说“查出车速大于 60 且 FCTA 没有报警的时刻”，背后将直接转换为 DuckDB 的极限 SQL 查询，避免企业笔记本 OOM (内存溢出)。

## 6. 内容调度与主脑框架 (Agentic Triage Loop)
**场景**: 调度上述所有结构化内容，导通“需求->代码->数据”的链路。
* **技术选型**: **LangGraph (状态机路由) + Pydantic Tool Calling**
* **结构化调度流程**:
  1. **State 定义 (状态池)**: 利用 LangGraph 的 **Checkpointer** 机制，支持将会话状态保存到本地磁盘（即使关机，下次也能恢复 Triage 会话）。
  2. **Node 1: 意图与需求对齐**: LLM 读 YAML 拿需求，由 Pydantic Schema 强校验。
  3. **Node 2: 代码拓扑推演**: 大模型编写 Cypher 语句调用 `KùzuDB`，查到 C 代码变量绑定的 CAN 信号。
  4. **Node 3: 数据实证**: 拿着 CAN 信号名，大模型写 SQL 调用 `DuckDB` 查询波形。
  5. **Node 4: 综合判决**: 对比需求与数据，输出 Triage 结论。