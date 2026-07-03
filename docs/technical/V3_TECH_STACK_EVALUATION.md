# V3 技术选型重估与最终决定 (Tech Stack Re-evaluation 2026)

> **文档目标**: 重新审视 V3 架构中的技术选型。之前的选型（如 SQLite 存所有数据、ChromaDB 作向量库）偏向于云端 SaaS 思维。结合本项目作为 **“离线、桌面级、处理海量高频车载数据（GB级）、内网安全隔离”** 的 CLI 工具定位，进行去伪存真的重新选型。

---

## 1. 异构时序数据引擎 (Time-Series Data Engine)
**场景**: 需要吃入 BAG/BLF/MF4 数据。MF4 或 BAG 文件动辄几个 GB，包含上百万行的毫秒级高频信号帧。
* ❌ **被否决的选型**: **SQLite** (当前的 `FrameStore` 底层)。SQLite 是行式数据库（Row-based），在执行百万级数据的批量 `INSERT` 时极其缓慢，且针对时间窗口的聚合查询（如“提取过去 10 秒的车速平均值”）性能极差，会导致内存和磁盘 IO 双重爆炸。
* ✅ **最终选型**: **DuckDB + Apache Arrow (Parquet)**
  * **原因**: DuckDB 是目前业界最火的“轻量级嵌入式列式分析数据库（OLAP）”。它专为处理百万/千万级数据而生，查询速度比 SQLite 快 10-100 倍。
  * **契合点**: `asammdf`（我们刚集成的 MF4 解析库）天然输出 Pandas/Arrow 格式。DuckDB 可以**零拷贝（Zero-Copy）**直接用 SQL 查询 Pandas DataFrame！这意味着我们甚至不需要把 MF4 落盘到数据库里，直接在内存里就可以极速完成 TPE 时序模式挖掘。

## 2. 向量检索与记忆系统 (Vector Database for Memory)
**场景**: 需要将 Bug 案例、需求文档进行 Embedding 向量化，以便大模型进行语义检索（RAG）。
* ❌ **被否决的选型**: **ChromaDB / Milvus / Pinecone**。这些主流向量库过于庞大，依赖 C++ 编译环境、gRPC 或大量后台服务，极其不适合在博世（Bosch）等企业内网 Windows 笔记本上进行免安装部署。`SQLite-VSS` 在 Windows 上的编译也常常失败。
* ✅ **最终选型**: **LanceDB** 或 **纯 Numpy/FAISS**
  * **原因**: LanceDB 是一个极轻量级的 Serverless 向量库，底层基于 Rust 和 Arrow，`pip install lancedb` 即可用，不需要起后台服务，极其适合本地 CLI 工具。对于早期的极简记忆系统，甚至可以直接用 `Numpy` 计算余弦相似度，实现“零额外依赖”。

## 3. 代码图谱的存储与计算 (CodeGraph Storage)
**场景**: 存储 AST 解析出的函数调用链和变量依赖网，并支持“查找某变量的上游修改节点”。
* ❌ **被否决的选型**: **SQLite 关系型表**。在关系型数据库中做图遍历（Graph Traversal）需要写复杂的递归 CTE（Recursive CTE），性能差且极难维护。
* ✅ **最终选型**: **NetworkX + JSON/GraphML 本地序列化**
  * **原因**: 我们目前的 `requirements.txt` 中已经因为 `langgraph` 间接引入了 `networkx`。NetworkX 是 Python 生态最强的纯内存图计算库。系统在离线时把代码解析为 NetworkX DAG 图，保存为 `.graphml` 或 `.pickle` 放在 workspace。运行时秒加载，自带的 `nx.ancestors()` 可以一键找出所有上游依赖，无需写任何 SQL。

## 4. 智能体编排框架 (Agent Framework)
**场景**: 构建 Agent Loop，调度大模型和工具。
* ❌ **需要警惕的选型**: **重度依赖 LangChain**。LangChain 虽然出名，但封装过重，容易导致 Prompt 黑盒，极难针对车载专有协议进行底层优化。
* ✅ **最终选型**: **轻量级原生 ReAct / Pydantic-AI / 轻度使用 LangGraph**
  * **原因**: 目前代码库已经引入了 `langgraph>=0.2.0`。我们将仅使用 LangGraph 的**状态机路由（State Graph）**能力来控制流转（如：`提取数据 -> 专家质询 -> 人工审核(HITL) -> 输出报告`），而底层的数据校验和 Tool Schema 生成全面使用 **Pydantic**。保证代码类型安全，且易于调试。

## 5. DBC 矩阵与基础字典缓存
* ❌ **被否决的选型**: 预编译存入 SQLite。DBC 是复杂的 Python 对象（包含各类换算公式），存入 SQLite 还需要来回解析序列化。
* ✅ **最终选型**: **Pickle / Joblib**
  * **原因**: 把 `cantools.database` 对象加载融合（Core+COEM）后，直接 `pickle.dump` 到 workspace 下。下次启动 `pickle.load`，只需几毫秒就能恢复完整的 Python 对象内存状态，直接调用 `.decode_message()`，效率远超数据库方案。

---

## 结论 (Summary)

真正的企业级桌面 CLI 工具，应当追求**“零依赖地狱、零后台服务、极致的单机本地性能”**。
通过引入 **DuckDB (时序数据)**、**NetworkX (代码图谱)**、**LanceDB/Numpy (本地记忆)**，我们不仅能彻底解决 V2 中 `pandas` 动辄 OOM 的性能毒瘤，还能让工具像 Git 一样轻便，随意在工程师的内网电脑间拷备运行。