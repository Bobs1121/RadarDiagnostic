# radarAnalyze V3 顶层架构与系统设计白皮书

> **版本**: 3.0.0-Master-Design
> **日期**: 2026-07-02
> **核心导向**: “设计先行”。打造一个横向极度隔离、纵向高度内聚、全链路可追溯，且面向未来调试生态的企业级智能诊断与辅助开发平台。

---

## 1. 总体架构哲学：矩阵式设计 (The Matrix Architecture)

系统将采用**矩阵式架构（Matrix Architecture）**。
* **X轴（横向）：Core + COEM 工作区继承与隔离 (Project Inheritance & Isolation)**
  针对车载软件开发中普遍存在的 **Platform (公共基线) + COEM (客户定制)** 模式（例如：底层跟踪滤波等为公共代码，而 CAN 矩阵、特殊报警条件位于 `coem/BYD/` 下），系统的 Workspace 将采用**继承制 (Inheritance)** 设计。
  创建一个 `base_core` 工作区存放通用配置和基础知识图谱；针对具体的客户项目（如 `gen6_byd_sc6h`），其工作区配置只需声明重载（Override）的部分：指定专有的 DBC、补充 `coem/***` 的源码搜索路径。这保证了客户项目的工作区足够“小”且轻量，最大程度复用公共部分。
* **Y轴（纵向）：模块的独立生命力 (Vertical Modular Value)**
  每个核心子系统被设计为“独立的产品（Standalone Product）”。它们可以脱离主循环单独运行，提供直接的用户价值。

---

## 2. 纵向模块化：四大独立子系统定义

为了实现“没有数据也能做代码助手，没有代码也能做数据助手”的目标，系统被垂直切割为四个具有独立商业价值的子模块。

### 模块 A: 智能代码与需求助手 (The Code & Logic Assistant)
**场景**：**无数据模式**。开发人员处于开发阶段，或接手旧项目。
* **独立功能**：
  - **需求拆解**：解析 PDF/Word/MD 需求，拆解为结构化的验收标准（Acceptance Criteria）。
  - **代码图谱 (AST CodeGraph)**：基于 C/C++ 源码生成精确的控制流和依赖图谱。
  - **DBC 解析与反推**：查阅 DBC 矩阵，反推代码中缺失的信号定义。
* **用户交互**：“帮我查一下，根据当前代码，RCTB 功能在什么车速下会抑制触发？并在 DBC 里找出对应的抑制信号。”

### 模块 B: 异构数据探索器 (The Data Matrix Explorer)
**场景**：**无代码/无项目模式**。测试人员拿来一份裸数据（Bag/BLF/MF4）求助。
* **独立功能**：
  - **多模态数据对齐**：自动对齐 ROS Bag、CAN BLF 和 MF4 的时间轴。
  - **信号抽取与可视化**：直接通过自然语言找信号，生成交互式 HTML 图表。
  - **时序特征挖掘 (TPE)**：发现数据里的尖峰、毛刺、异常跳变、信号丢失等底层数据质量问题。
* **用户交互**：“导入这份未知车型的 MF4，把里面波动频率超过 10Hz 的信号全部帮我挑出来并画图。”

### 模块 C: 全链路诊断溯源引擎 (The Full-Link Diagnostic Agent)
**场景**：**完全体模式**。拿到测试提的 Bug 单、数据包和对应的车型代码库。
* **独立功能**：实现 **“需求 -> 代码 -> 数据”** 的三角对齐与溯源。
  - *Link 1 (Req -> Code)*：需求说“迟滞200ms”，代码库里通过 AST 查到 `timer > 10` (假设 20ms/frame，正好 200ms)，建立映射。
  - *Link 2 (Code -> Data)*：代码里查到阈值变量 `VehSpd`，在 DBC 里映射为 `VehSpd_0x137`，去 Data 模块提取该信号。
  - *Link 3 (Data -> Req)*：TPE 引擎发现 `VehSpd_0x137` 从 0 跳到 60 耗时 50ms（数据毛刺），打破了需求规定的前提，得出诊断结论。

### 模块 D: 性能与资源分析器 (The Performance Profiler) - *New*
**场景**：功能正常，但在特定工况下雷达 CPU 负载过高或发消息延迟（Latency）。
* **独立功能**：
  - **耗时/延迟计算**：从目标出现（Bag 中的 Obj 记录）到 CAN 总线发出报警（BLF 中的 Warn 信号）的端到端时延统计。
  - **执行流热点分析**：推测代码中长循环或复杂计算导致的卡顿。

---

## 3. 全链路关联设计：本体模型 (The Traceability Ontology)

要在需求、代码、数据之间建立关联，我们引入一套中间表示语言（IR），基于知识图谱的思想：

```mermaid
[需求节点: 激活车速限制] --(约束)--> [代码 AST 节点: speed > 10.0]
[代码 AST 节点: speed > 10.0] --(映射)--> [物理信号: CAN_ID_0x137.VehSpd]
[物理信号: CAN_ID_0x137.VehSpd] --(实例化)--> [数据探针: FrameStore时序序列]
```

**实施方案**：
1. `CodeGraph` 不再只是记录函数调用，而是增加**Semantic Tags (语义标签)**。
2. 当 LLM 在分析 Bug 时，第一步是实例化上述“三角映射关系表”。一旦某条关系链在数据层发生断裂（例如：代码写了，但数据里该信号一直是 0），根本原因就找到了。

---

## 4. 面向未来的生态接入：Linux & VSCode 逐帧调试体系

我们不能把系统做成一个封闭的 CLI 脚本。为了后续支持 Linux 环境下 VSCode 的逐帧 Debug，V3 必须具备**服务化与协议化**能力。

### 4.1 核心设计：Debug Adapter Protocol (DAP) 就绪
将 `radarAnalyze` 的内核剥离，提供一套标准的本地 API 或 RPC 接口。
* **逐帧复现 (Frame-by-Frame Replay)**：
  Data Explorer 模块可以充当一个“虚拟雷达输入源”。它可以按照微秒级精度，将 BAG/BLF 中的数据帧转换为 C 代码可以接收的 `struct`，通过 GDB 脚本或 Socket 喂给运行在 Linux 中的雷达算法可执行文件。
* **VSCode 插件整合**：
  未来可以编写一个 VSCode Extension。当开发者在 VSCode 中点击某行代码时，插件通过 API 请求 `radarAnalyze`：“把导致这一行被触发的那一帧路测数据给我调出来，我要在这里下断点”。
* **双向穿透**：
  从图表到代码：在 HTML 报告中点击某个信号的跳变点，自动通过 VSCode 唤起对应 C 语言源码文件并高亮处理该信号的函数。

---

## 5. 架构师实施箴言

1. **“Everything is an API”**：`cli.py` 只是本系统的一个客户端实现。内部的 `CodeAssistant`、`DataExplorer` 必须被封装为 `class`，暴露整洁的 Python API，以便未来轻松包入 FastAPI 供 Web 端或 VSCode 调用。
2. **“Agent 是一层壳”**：大模型的 Agent Loop 只负责“理解意图和编排工具”，绝对不要让 LLM 直接处理原始数据块。底层脏活累活必须由 Python 坚实的 AST 树和 DataFrame 矩阵完成。
3. **延迟决断 (Lazy Evaluation)**：不到最后一刻不要加载全量数据。MF4 和 AST 树的规模极大，必须依托按需查询（Lazy Query）机制。

## 6. V3 第一阶段目标重设 (Redefining Phase 1)
根据本设计白皮书，第一阶段的动作将不是改功能，而是**重塑物理边界**：
1. 建立 `Workspaces` 横向隔离机制。
2. 剥离并重构 `CodeAssistant`（基于 AST）为独立可导入的包。
3. 剥离并重构 `DataExplorer` 为独立可导入的包，赋予它“无配置盲吃数据”的探索能力。