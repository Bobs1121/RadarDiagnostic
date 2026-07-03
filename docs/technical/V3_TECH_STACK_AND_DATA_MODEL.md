# V3 技术选型与数据模型设计规范 (Tech Stack & Data Models)

> **文档目标**: 回答并固化 V3 架构中关于需求管理、DBC映射、代码链路、记忆系统以及底层代码结构化（CodeGraph vs LLI Wiki）的技术选型与存储结构。

---

## 1. 需求管理 (Requirements Management)
**痛点**: 需求通常是散乱的 Word/PDF，LLM 难以直接进行逻辑判定。
**技术选型**: **YAML + 动态 JSON Schema**
* **存储方式**: 在 `.workspace/<project>/requirements/` 下，按功能域（如 `FCTA.yaml`, `RCTB.yaml`）存储结构化规范。
* **数据结构**: 提取需求中的硬性标准（Acceptance Criteria），如触发阈值、延时限制。
  ```yaml
  function: FCTA
  activation_conditions:
    - variable: "Ego_Speed"
      operator: "<"
      value: 30
      unit: "km/h"
  performance:
    max_latency_ms: 200
  ```
* **运转机制**: Agent 启动诊断前，先加载对应功能的 YAML，将其转化为 JSON Schema，强制作为此次诊断的 Ground Truth 进行比对。

## 2. DBC 管理与继承机制 (DBC Management)
**痛点**: Core 和 COEM 共存，且 DBC 经常更新，重复解析极慢。
**技术选型**: **原始文件 + SQLite 本地缓存预编译 (Pre-compiled Cache)**
* **存储结构**:
  - `base_core/dbc/*.dbc` (基线公共)
  - `gen6_gwm/dbc/*.dbc` (长城定制)
* **运转机制**: 系统初始化时，按照 `Core -> COEM` 顺序加载（COEM 可覆盖 Core）。使用 `cantools` 库解析后，将合并后的“最终矩阵”序列化存入 `workspace/.../dbc_cache.db` (SQLite)。
* **优势**: Agent 需要反推信号时，通过 SQL 极速查询 `SELECT signal_name FROM signals WHERE node='VCU' AND comment LIKE '%steering%'`，远快于每次读文本文件。

## 3. 代码链路组织：实时推理 vs 预编译拓扑图
**决策**: **绝对不能实时读取整条链路！必须采用“预计算拓扑图 (Pre-computed Topology)”方案。**
**原因**: 实时让 LLM 去海量 C 文件里跳转追溯链路，会迅速耗尽 100K 以上的 Context Window，且大概率会因 Token 截断导致逻辑链断裂。

**技术选型**: **有向无环图 (DAG) + SQLite 关系型存储**
* **图结构**:
  - **Nodes**: 函数 (Functions), 变量 (Variables), 状态 (States)
  - **Edges**: `CALLS` (调用), `READS` (读取), `WRITES` (修改)
* **存储媒介**: 放弃纯 JSON，使用 SQLite (即现有的 `codegraph.db`)。
* **运转机制**: 
  1. 系统在挂载项目时（或“休眠 Dream”时），通过 AST 解析器**一次性跑通全量代码**，生成静态拓扑数据库。
  2. Agent 在诊断时，只需执行轻量级 SQL/图查询：“返回 `FCTA_Warn` 变量的上游所有写入节点路径”，数据库秒级返回极简的链路名单，Agent 再去按图索骥提取对应的少量源码片段。

## 4. 记忆系统设计 (Memory System)
**技术选型**: **分层存储 (Layered Memory) + 向量化混合检索 (Hybrid RAG)**
将记忆拆分为三种介质，实现长期演进：
1. **短时记忆 (Session Memory)**: 纯 JSON，保存在本次诊断任务文件夹中，记录大模型本次多轮对话的思考流和执行快照。
2. **长期事实记忆 (Fact Base)**: SQLite，记录确定性的项目常量（Constants）、网络接口定义等。
3. **经验库 (Experience Vector DB)**: 引入轻量级向量库（如 `ChromaDB` 或 `SQLite-VSS`）。每次成功的诊断结束后，将 Bug 症状和修复方案编码为 Vector 存入。下次遇到类似工况，大模型通过语义相似度瞬间召回。

## 5. 代码结构化选型：CodeGraph 还是 LLI Wiki？
**用户疑问**: 代码结构化选择 CodeGraph（基于底层 AST）还是 LLI Wiki（语言大模型生成的知识百科）？
**决策**: **CodeGraph 作“骨”，LLI Wiki 作“肉”。两者混合（Hybrid Architecture）。**

* **CodeGraph (AST)**: 
  * **属性**: 确定性、绝对精准、人类不可读。
  * **作用**: 负责骨架构建。大模型绝不能自己去“猜”依赖关系，必须通过 AST 工具查询 `if` 嵌套里到底有没有某变量。
* **LLI Wiki (Language Logic Interface)**:
  * **属性**: 语义化、高度概括、大模型极度友好。
  * **作用**: 负责意图解释。复杂的跟踪滤波算法或状态机（FSM）转换，如果只看 AST，LLM 可能会迷失在指针中。
* **协同运转流程**:
  在离线模式（Auto-Dream）下，系统通过 `CodeGraph` 找出关键控制流代码段，然后丢给 LLM 生成一段人类语言的总结描述，将其存入 `LLI Wiki`（如：*“FCTCtrl.c 中的状态机主要处理这四个阶段...”*）。
  当线上出现 Bug 时，Agent 首先阅读 `LLI Wiki` 快速获得系统架构的直觉，确定嫌疑方向后，再用 `CodeGraph` 的 SQL 接口发起手术刀级别的精准排查。这兼顾了“效率”与“准确性”。