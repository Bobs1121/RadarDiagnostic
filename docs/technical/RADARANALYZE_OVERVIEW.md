<!-- 文档由 radarAnalyze 项目内嵌 SVG 生成，请在支持内联 SVG 的 Markdown 渲染器中查看（VS Code / Typora / GitHub）。 -->

# Corner Radar AI 诊断工具 — 架构 / 功能 / 技术栈全景

> **radarAnalyze**：面向 ADAS 角雷达（BSD / LCA / DOW / RCW / RCTA / RCTB / FCTA / FCTB）的 **AI 诊断 Harness**。
> 它以**代码为唯一事实源**，将录制数据（BLF / BAG / MF4）与源码调用链、参数边界、需求约束交叉对齐，
> 用确定性引擎产出可追溯证据，再由 LLM 专家面板完成根因推理与 Top-3 排序。

---

## 1. 项目定位与设计原则

radarAnalyze 不是"规则诊断器"，而是一套 **AI 诊断 Harness**，核心链路固定为：

1. 用户疑问 → 检索相关功能、源码调用链、参数边界和需求约束
2. 数据管线只筛选并预处理最相关的信号、对象和时间窗口，控制上下文规模
3. 将实际数据值按确定的 CAN/内部变量转换**回填到代码条件与调用链**
4. Harness 输出可追溯证据、冲突和缺口；**条件检查是证据标注，不是诊断硬门槛**
5. AI 负责跨代码、数据、需求和案例知识做根因推理、Top-3 排序和下一步验证建议
6. Auto Dream 按 variant / customer / branch 隔离固化可复用知识，通过 freshness 机制更新

**知识新鲜度硬约束**：variant 运行中，freshness 缺失、不可用或输入签名不匹配的学习产物**不得进入 AI prompt**；
确定性、自带源文件 hash 的产物（signal_mapping / codegraph 等）可以先重建后使用。

---

## 2. 总体架构

<div align="center">

<!-- SVG 1: 分层架构总览 -->
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 640" width="960" height="640" font-family="Microsoft YaHei, Segoe UI, sans-serif">
  <defs>
    <marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto">
      <path d="M0,0 L7,3 L0,6 Z" fill="#555"/>
    </marker>
    <linearGradient id="gTop" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#2b6cb0"/><stop offset="1" stop-color="#1a3a6b"/>
    </linearGradient>
    <linearGradient id="gPanel" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#805ad5"/><stop offset="1" stop-color="#553c9a"/>
    </linearGradient>
  </defs>

  <!-- 背景 -->
  <rect x="0" y="0" width="960" height="640" fill="#f7f9fc" rx="8"/>

  <!-- Layer 1: 数据接入层 -->
  <rect x="20" y="14" width="920" height="96" fill="#fff" stroke="#2b6cb0" stroke-width="1.5" rx="6"/>
  <text x="40" y="40" font-size="15" font-weight="bold" fill="#2b6cb0">L0 · 数据接入层</text>
  <rect x="40" y="52" width="120" height="44" fill="#ebf4ff" stroke="#2b6cb0" rx="4"/>
  <text x="72" y="79" font-size="13" fill="#1a3a6b">BLF 解析</text>
  <rect x="180" y="52" width="120" height="44" fill="#ebf4ff" stroke="#2b6cb0" rx="4"/>
  <text x="212" y="79" font-size="13" fill="#1a3a6b">BAG 解析</text>
  <rect x="320" y="52" width="120" height="44" fill="#ebf4ff" stroke="#2b6cb0" rx="4"/>
  <text x="360" y="79" font-size="13" fill="#1a3a6b">MF4 解析</text>
  <rect x="460" y="52" width="150" height="44" fill="#ebf4ff" stroke="#2b6cb0" rx="4"/>
  <text x="480" y="79" font-size="13" fill="#1a3a6b">DBC 信号解码</text>
  <rect x="630" y="52" width="150" height="44" fill="#ebf4ff" stroke="#2b6cb0" rx="4"/>
  <text x="655" y="79" font-size="13" fill="#1a3a6b">FrameStore (SQLite)</text>

  <!-- Layer 2: 确定性引擎 -->
  <rect x="20" y="130" width="920" height="170" fill="#fff" stroke="#38a169" stroke-width="1.5" rx="6"/>
  <text x="40" y="156" font-size="15" font-weight="bold" fill="#2f855a">L1 · 确定性引擎（engines/，无 LLM，可独立测试）</text>
  <g font-size="12" fill="#22543d">
    <rect x="40" y="168" width="118" height="40" fill="#f0fff4" stroke="#38a169" rx="4"/><text x="58" y="192">signal_mapper</text>
    <rect x="170" y="168" width="118" height="40" fill="#f0fff4" stroke="#38a169" rx="4"/><text x="188" y="192">signal_audit</text>
    <rect x="300" y="168" width="118" height="40" fill="#f0fff4" stroke="#38a169" rx="4"/><text x="318" y="192">frame_analyzer</text>
    <rect x="430" y="168" width="118" height="40" fill="#f0fff4" stroke="#38a169" rx="4"/><text x="448" y="192">test_window</text>
    <rect x="560" y="168" width="118" height="40" fill="#f0fff4" stroke="#38a169" rx="4"/><text x="578" y="192">temporal_analyzer</text>
    <rect x="690" y="168" width="118" height="40" fill="#f0fff4" stroke="#38a169" rx="4"/><text x="708" y="192">pattern_extractor</text>
    <rect x="820" y="168" width="100" height="40" fill="#f0fff4" stroke="#38a169" rx="4"/><text x="838" y="192">causal_aligner</text>

    <rect x="40" y="218" width="118" height="40" fill="#f0fff4" stroke="#38a169" rx="4"/><text x="58" y="242">TPE 时序引擎</text>
    <rect x="170" y="218" width="118" height="40" fill="#f0fff4" stroke="#38a169" rx="4"/><text x="180" y="242">data_probe</text>
    <rect x="300" y="218" width="118" height="40" fill="#f0fff4" stroke="#38a169" rx="4"/><text x="318" y="242">parameter_analyzer</text>
    <rect x="430" y="218" width="118" height="40" fill="#f0fff4" stroke="#38a169" rx="4"/><text x="442" y="242">condition_extractor</text>
    <rect x="560" y="218" width="118" height="40" fill="#f0fff4" stroke="#38a169" rx="4"/><text x="572" y="242">rule_condition_extractor</text>
    <rect x="690" y="218" width="118" height="40" fill="#f0fff4" stroke="#38a169" rx="4"/><text x="712" y="242">investigation_engine</text>
    <rect x="820" y="218" width="100" height="40" fill="#f0fff4" stroke="#38a169" rx="4"/><text x="830" y="242">problem_classifier</text>
  </g>

  <!-- Layer 3: AI / 编排 -->
  <rect x="20" y="320" width="920" height="150" fill="#fff" stroke="#805ad5" stroke-width="1.5" rx="6"/>
  <text x="40" y="346" font-size="15" font-weight="bold" fill="#553c9a">L2 · AI 编排层（ai/，LLM 推理 + 编排）</text>
  <rect x="40" y="358" width="200" height="44" fill="#faf5ff" stroke="#805ad5" rx="4"/>
  <text x="90" y="383" font-size="13" fill="#44337a">Orchestrator（8 步管线）</text>
  <rect x="260" y="358" width="170" height="44" fill="#faf5ff" stroke="#805ad5" rx="4"/>
  <text x="300" y="383" font-size="13" fill="#44337a">ExpertPanel (LangGraph)</text>
  <rect x="450" y="358" width="150" height="44" fill="#faf5ff" stroke="#805ad5" rx="4"/>
  <text x="480" y="383" font-size="13" fill="#44337a">CodeLearner / L6</text>
  <rect x="620" y="358" width="150" height="44" fill="#faf5ff" stroke="#805ad5" rx="4"/>
  <text x="648" y="383" font-size="13" fill="#44337a">ModelRouter（路由）</text>
  <rect x="790" y="358" width="130" height="44" fill="#faf5ff" stroke="#805ad5" rx="4"/>
  <text x="812" y="383" font-size="13" fill="#44337a">DataQueryEngine</text>

  <rect x="40" y="412" width="200" height="44" fill="#faf5ff" stroke="#805ad5" rx="4"/>
  <text x="70" y="437" font-size="13" fill="#44337a">Auto Dream（记忆固化）</text>
  <rect x="260" y="412" width="170" height="44" fill="#faf5ff" stroke="#805ad5" rx="4"/>
  <text x="300" y="437" font-size="13" fill="#44337a">CodeGraph（AST 索引）</text>
  <rect x="450" y="412" width="150" height="44" fill="#faf5ff" stroke="#805ad5" rx="4"/>
  <text x="470" y="437" font-size="13" fill="#44337a">Visualizer（报告）</text>
  <rect x="620" y="412" width="150" height="44" fill="#faf5ff" stroke="#805ad5" rx="4"/>
  <text x="650" y="437" font-size="13" fill="#44337a">CodeFixEngine</text>
  <rect x="790" y="412" width="130" height="44" fill="#faf5ff" stroke="#805ad5" rx="4"/>
  <text x="806" y="437" font-size="13" fill="#44337a">V3 Modules (M1-M10)</text>

  <!-- Layer 4: 知识 / 记忆 -->
  <rect x="20" y="490" width="920" height="120" fill="#fff" stroke="#c05621" stroke-width="1.5" rx="6"/>
  <text x="40" y="516" font-size="15" font-weight="bold" fill="#9c4221">L3 · 知识 / 记忆层（memory/ + source_docs/ + core/）</text>
  <g font-size="12" fill="#7b341e">
    <rect x="40" y="528" width="140" height="66" fill="#fffaf0" stroke="#c05621" rx="4"/>
    <text x="70" y="550" font-size="13" font-weight="bold">L1-L6 记忆</text>
    <text x="70" y="570" font-size="11">project/functions</text>
    <text x="70" y="585" font-size="11">patterns/sessions/code</text>
    <rect x="200" y="528" width="140" height="66" fill="#fffaf0" stroke="#c05621" rx="4"/>
    <text x="230" y="550" font-size="13" font-weight="bold">source_docs</text>
    <text x="230" y="570" font-size="11">conditions.json</text>
    <text x="230" y="585" font-size="11">signal_mapping.json</text>
    <rect x="360" y="528" width="140" height="66" fill="#fffaf0" stroke="#c05621" rx="4"/>
    <text x="380" y="550" font-size="13" font-weight="bold">Semantic Memory</text>
    <text x="380" y="570" font-size="11">LanceDB 向量召回</text>
    <text x="380" y="585" font-size="11">或余弦回退</text>
    <rect x="520" y="528" width="140" height="66" fill="#fffaf0" stroke="#c05621" rx="4"/>
    <text x="540" y="550" font-size="13" font-weight="bold">Freshness</text>
    <text x="540" y="570" font-size="11">fingerprint 指纹</text>
    <text x="540" y="585" font-size="11">knowledge_manifest</text>
    <rect x="680" y="528" width="140" height="66" fill="#fffaf0" stroke="#c05621" rx="4"/>
    <text x="700" y="550" font-size="13" font-weight="bold">Variant 隔离</text>
    <text x="700" y="570" font-size="11">.workspaces/&lt;variant&gt;/</text>
    <text x="700" y="585" font-size="11">config.local.yaml</text>
    <rect x="840" y="528" width="80" height="66" fill="#fffaf0" stroke="#c05621" rx="4"/>
    <text x="852" y="550" font-size="12" font-weight="bold">Bundle</text>
    <text x="852" y="570" font-size="11">诊断包</text>
    <text x="852" y="585" font-size="11">快照</text>
  </g>
</svg>

</div>

**分层职责**：

| 层 | 目录 | 职责 | 是否含 LLM |
|----|------|------|-----------|
| L0 数据接入 | `parsers/` | 解析 BLF/BAG/MF4，用 DBC 解码信号，存入 SQLite FrameStore | 否 |
| L1 确定性引擎 | `engines/` | 信号映射、信号审计、帧分析、测试窗口、TPE、探针、参数分析 | 否 |
| L2 AI 编排 | `ai/` | Orchestrator 8 步管线、专家面板、代码学习、查询引擎、报告 | 是 |
| L3 知识/记忆 | `memory/` `core/` `source_docs/` | L1-L6 记忆、语义召回、新鲜度门控、variant 隔离 | 混合 |
| 能力模块 | `ai/modules/` | M1-M10 独立 V3 模块（CLI 子命令 + Python API） | 混合 |

---

## 3. 诊断管线（8 步）

<div align="center">

<!-- SVG 2: 诊断管线 8 步流程 -->
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 560" width="960" height="560" font-family="Microsoft YaHei, Segoe UI, sans-serif">
  <defs>
    <marker id="a2" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto">
      <path d="M0,0 L7,3 L0,6 Z" fill="#2b6cb0"/>
    </marker>
  </defs>
  <rect x="0" y="0" width="960" height="560" fill="#fbfdff" rx="8"/>
  <text x="30" y="36" font-size="17" font-weight="bold" fill="#2b6cb0">诊断管线 — Orchestrator.run_diagnosis()</text>

  <!-- 步骤 1-4 横排 -->
  <g>
    <rect x="30" y="70" width="205" height="90" fill="#ebf8ff" stroke="#3182ce" rx="6"/>
    <text x="45" y="96" font-size="14" font-weight="bold" fill="#2b6cb0">① INIT</text>
    <text x="45" y="118" font-size="12" fill="#2c5282">source_docs / CodeGraph 保障</text>
    <text x="45" y="136" font-size="11" fill="#4a5568">_ensure_source_docs</text>

    <rect x="265" y="70" width="205" height="90" fill="#ebf8ff" stroke="#3182ce" rx="6"/>
    <text x="280" y="96" font-size="14" font-weight="bold" fill="#2b6cb0">② CLASSIFY</text>
    <text x="280" y="118" font-size="12" fill="#2c5282">理解 + 分类</text>
    <text x="280" y="136" font-size="11" fill="#4a5568">_understand_problem + classifier</text>

    <rect x="500" y="70" width="205" height="90" fill="#ebf8ff" stroke="#3182ce" rx="6"/>
    <text x="515" y="96" font-size="14" font-weight="bold" fill="#2b6cb0">③ EXTRACT</text>
    <text x="515" y="118" font-size="12" fill="#2c5282">数据解析 + 窗口检测</text>
    <text x="515" y="136" font-size="11" fill="#4a5568">load_case_data + test_window</text>

    <rect x="735" y="70" width="195" height="90" fill="#ebf8ff" stroke="#3182ce" rx="6"/>
    <text x="750" y="96" font-size="14" font-weight="bold" fill="#2b6cb0">④ EVIDENCE</text>
    <text x="750" y="118" font-size="12" fill="#2c5282">帧证据 + 条件 + TPE + 探针</text>
    <text x="750" y="136" font-size="11" fill="#4a5568">frame_analyzer / tpe / probe</text>
  </g>
  <g stroke="#2b6cb0" stroke-width="1.6" marker-end="url(#a2)">
    <line x1="235" y1="115" x2="262" y2="115"/>
    <line x1="470" y1="115" x2="497" y2="115"/>
    <line x1="705" y1="115" x2="732" y2="115"/>
  </g>

  <!-- 步骤 5-8 横排 -->
  <g>
    <rect x="30" y="200" width="205" height="90" fill="#f0fff4" stroke="#38a169" rx="6"/>
    <text x="45" y="226" font-size="14" font-weight="bold" fill="#2f855a">⑤ SIGNALS</text>
    <text x="45" y="248" font-size="12" fill="#276749">抑制/输出/参数/信号审计</text>
    <text x="45" y="266" font-size="11" fill="#4a5568">suppression + output + audit</text>

    <rect x="265" y="200" width="205" height="90" fill="#faf5ff" stroke="#805ad5" rx="6"/>
    <text x="280" y="226" font-size="14" font-weight="bold" fill="#553c9a">⑥ DIAGNOSE</text>
    <text x="280" y="248" font-size="12" fill="#44337a">专家面板（5 专家 × 3 轮）</text>
    <text x="280" y="266" font-size="11" fill="#4a5568">expert_panel.run_panel</text>

    <rect x="500" y="200" width="205" height="90" fill="#fffaf0" stroke="#c05621" rx="6"/>
    <text x="515" y="226" font-size="14" font-weight="bold" fill="#9c4221">⑦ FIX</text>
    <text x="515" y="248" font-size="12" fill="#7b341e">修复建议</text>
    <text x="515" y="266" font-size="11" fill="#4a5568">code_fix_engine</text>

    <rect x="735" y="200" width="195" height="90" fill="#fff5f5" stroke="#e53e3e" rx="6"/>
    <text x="750" y="226" font-size="14" font-weight="bold" fill="#c53030">⑧ DELIVER</text>
    <text x="750" y="248" font-size="12" fill="#9b2c2c">报告/可视化/记忆/Bundle</text>
    <text x="750" y="266" font-size="11" fill="#4a5568">visualizer + memory + bundle</text>
  </g>
  <g stroke="#2b6cb0" stroke-width="1.6" marker-end="url(#a2)">
    <line x1="235" y1="245" x2="262" y2="245"/>
    <line x1="470" y1="245" x2="497" y2="245"/>
    <line x1="705" y1="245" x2="732" y2="245"/>
  </g>
  <line x1="132" y1="290" x2="132" y2="320" stroke="#2b6cb0" stroke-width="1.6" marker-end="url(#a2)"/>

  <!-- 证据链回填 -->
  <rect x="30" y="330" width="900" height="200" fill="#fff" stroke="#2b6cb0" stroke-dasharray="5 4" rx="8"/>
  <text x="50" y="360" font-size="15" font-weight="bold" fill="#2b6cb0">贯穿全链路的证据 → 代码回填（CodeIndex 确定性投影）</text>

  <rect x="50" y="378" width="180" height="54" fill="#ebf8ff" stroke="#3182ce" rx="5"/>
  <text x="78" y="400" font-size="13" fill="#2c5282">CAN 信号</text>
  <text x="78" y="420" font-size="11" fill="#4a5568">BLF 解码值 / DBC 枚举</text>
  <line x1="230" y1="405" x2="262" y2="405" stroke="#3182ce" stroke-width="1.5" marker-end="url(#a2)"/>

  <rect x="265" y="378" width="180" height="54" fill="#ebf8ff" stroke="#3182ce" rx="5"/>
  <text x="290" y="400" font-size="13" fill="#2c5282">signal_mapper</text>
  <text x="290" y="420" font-size="11" fill="#4a5568">RteComMapping 双向映射</text>
  <line x1="445" y1="405" x2="477" y2="405" stroke="#3182ce" stroke-width="1.5" marker-end="url(#a2)"/>

  <rect x="480" y="378" width="180" height="54" fill="#f0fff4" stroke="#38a169" rx="5"/>
  <text x="505" y="400" font-size="13" fill="#276749">内部变量</text>
  <text x="505" y="420" font-size="11" fill="#4a5568">g_ADAS_Output / AdasStM</text>
  <line x1="660" y1="405" x2="692" y2="405" stroke="#3182ce" stroke-width="1.5" marker-end="url(#a2)"/>

  <rect x="695" y="378" width="215" height="54" fill="#faf5ff" stroke="#805ad5" rx="5"/>
  <text x="720" y="400" font-size="13" fill="#44337a">CodeGraph AST 调用链</text>
  <text x="720" y="420" font-size="11" fill="#4a5568">函数 / 状态机 / 使能条件</text>

  <rect x="50" y="450" width="860" height="62" fill="#fffaf0" stroke="#c05621" rx="5"/>
  <text x="70" y="474" font-size="13" font-weight="bold" fill="#9c4221">输出：可追溯证据链</text>
  <text x="70" y="496" font-size="12" fill="#7b341e">信号 → 变量 → 函数 → 条件 → 状态机，每一条证据标注「时间 / 值 / 来源」，作为专家面板的事实底座</text>
</svg>

</div>

**管线步骤速查**：

| Step | 名称 | 模块 | 输入 | 输出 |
|------|------|------|------|------|
| 1 | init | `_ensure_source_docs` | 源码 / 配置 | source_docs、CodeGraph 就绪 |
| 2 | classify | `_understand_problem` + `problem_classifier` | 问题描述 | 功能、失败类型、关注参数/信号 |
| 3 | extract | `case_loader` + `test_window_detector` | 案例目录 | store、元信息、测试窗口、evidence |
| 4 | evidence | `frame_analyzer` / `condition_extractor` / `tpe` / `data_probe` / `investigation_engine` | store + 窗口 | 帧证据、条件表、TPE 结果、探针 |
| 5 | signals | `_check_suppression_signals` / `_analyze_output_signals` / `_run_signal_audit` | 条件 + store | 抑制/输出/审计 markdown |
| 6 | diagnose | `expert_panel.run_panel`（LangGraph，3 轮） | 全部上下文 | panel_result（final_verdict） |
| 7 | fix | `code_fix_engine` | 根因 | 修复 diff / 建议 |
| 8 | deliver | `visualizer` + `memory_system` + `DiagnosisBundle` | 全结果 | report.md/html、记忆、Bundle |

---

## 4. 数据流（BLF → 分析 → 报告）

<div align="center">

<!-- SVG 3: 数据流 -->
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 940 300" width="940" height="300" font-family="Microsoft YaHei, Segoe UI, sans-serif">
  <defs>
    <marker id="a3" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto">
      <path d="M0,0 L7,3 L0,6 Z" fill="#555"/>
    </marker>
  </defs>
  <rect x="0" y="0" width="940" height="300" fill="#fcfdfe" rx="8"/>
  <g font-size="12" fill="#333">
    <rect x="20" y="50" width="150" height="70" fill="#ebf8ff" stroke="#3182ce" rx="6"/>
    <text x="42" y="76" font-size="13" font-weight="bold" fill="#2b6cb0">录制数据</text>
    <text x="42" y="96" fill="#4a5568">.bag / .blf / .mf4</text>
    <text x="42" y="112" fill="#4a5568">+ DBC 文件</text>

    <rect x="210" y="50" width="160" height="70" fill="#ebf8ff" stroke="#3182ce" rx="6"/>
    <text x="230" y="76" font-size="13" font-weight="bold" fill="#2b6cb0">case_loader</text>
    <text x="230" y="96" fill="#4a5568">ParserRegistry 分发</text>
    <text x="230" y="112" fill="#4a5568">DBC 解码为物理值</text>

    <rect x="410" y="50" width="160" height="70" fill="#f0fff4" stroke="#38a169" rx="6"/>
    <text x="430" y="76" font-size="13" font-weight="bold" fill="#2f855a">FrameStore</text>
    <text x="430" y="96" fill="#4a5568">SQLite 持久化</text>
    <text x="430" y="112" fill="#4a5568">can/bag/radar_objects</text>

    <rect x="610" y="50" width="150" height="70" fill="#faf5ff" stroke="#805ad5" rx="6"/>
    <text x="630" y="76" font-size="13" font-weight="bold" fill="#553c9a">分析引擎</text>
    <text x="630" y="96" fill="#4a5568">TPE / 审计 / 探针</text>
    <text x="630" y="112" fill="#4a5568">窗口 + 时间线</text>

    <rect x="800" y="50" width="120" height="70" fill="#fffaf0" stroke="#c05621" rx="6"/>
    <text x="818" y="76" font-size="13" font-weight="bold" fill="#9c4221">报告</text>
    <text x="818" y="96" fill="#7b341e">report.md</text>
    <text x="818" y="112" fill="#7b341e">report.html</text>
  </g>
  <g stroke="#555" stroke-width="1.6" marker-end="url(#a3)">
    <line x1="170" y1="85" x2="207" y2="85"/>
    <line x1="370" y1="85" x2="407" y2="85"/>
    <line x1="570" y1="85" x2="607" y2="85"/>
    <line x1="760" y1="85" x2="797" y2="85"/>
  </g>
  <text x="20" y="210" font-size="14" font-weight="bold" fill="#2b6cb0">查询 / 绘图 快速通道</text>
  <g font-size="12" fill="#333">
    <rect x="20" y="225" width="200" height="50" fill="#ebf8ff" stroke="#3182ce" rx="6"/>
    <text x="38" y="255" fill="#2c5282">--plot-signals / --plot-query（信号绘图）</text>
    <rect x="250" y="225" width="200" height="50" fill="#ebf8ff" stroke="#3182ce" rx="6"/>
    <text x="268" y="255" fill="#2c5282">--query（自然语言数据问答）</text>
    <rect x="480" y="225" width="200" height="50" fill="#faf5ff" stroke="#805ad5" rx="6"/>
    <text x="498" y="255" fill="#44337a">cli.py signal-audit（关键信号审计）</text>
  </g>
</svg>

</div>

### 信号 → 代码回填链路（第一性原理核心）

```
BLF 信号（DBC 名）
  │  signal_mapper.extract_signal_mapping（Rx.c + Tx.c，支持 &Struct.Member 点号目标）
  ▼
内部变量（g_ADAS_Output_st.* / AdasStM.*）
  │  CodeGraph AST 索引（READS_SIGNAL / WRITES_SIGNAL / CALLS / READS_VAR）
  ▼
代码调用链（RteComMapping → 使能条件 → 状态机 → 输出计算）
  │  condition_extractor + investigation_engine
  ▼
可追溯证据（时间 / 值 / 来源 / 契约判定）
```

> 该链路是 2026-08 重构的核心成果：修复了 RX 点号目标漏解析（88→108 mappings）、TX 方向缺失（0→191）、
> 输出信号名与 DBC 脱节（`FCTA_Warn` → `Sts_FCTA_S`）、`get_call_chain` 插值 bug 等，
> 使 AI 在分析数据时能快速、正确索引到代码。

---

## 5. 功能矩阵

### 5.1 CLI 运行模式

| 模式 | 命令 | 用途 |
|------|------|------|
| **Diagnosis** | `python cli.py cases/FCTB001/ -p "..." -e "..."` | 8 步管线根因诊断 |
| **Query** | `python cli.py --mode query -q "..."`（或 `-q`） | 自然语言数据问答 |
| **Dream** | `python cli.py --dream` | 强制记忆固化（冷启动自动深学源码） |
| **Auto Dream** | `python cli.py --auto-dream` | 诊断前一次门控记忆固化 |
| **Prewarm** | `python cli.py --prewarm` | 预热 source_docs + L6 + variable_chains |
| **Plot** | `python cli.py --plot-signals A,B` / `--plot-query "..."` | 信号时序绘图 |
| **Project Init** | `python cli.py project-init --name ... --code-root ... --dbc ...` | 变体接入引导 |
| **Learn Constants** | `python cli.py --learn-constants` | 重学全局数值常量表 |
| **CodeGraph Stats** | `python cli.py --codegraph-stats` | CodeGraph 统计（调试） |
| **Harness Gate** | `python tools/run_harness_gate.py` | 聚合回归门禁 |
| **BSD Validate** | `python cli.py bsd-data-bridge --mode validate --mf4-path ...` | BSD 条件交叉验证 |

### 5.2 V3 独立能力模块（M1–M10）

| 模块 | CLI 子命令 | 定位 | AI 调用 |
|------|-----------|------|---------|
| M1 `code-structure` | `code-query` | 源码静态结构分析（无数据） | 无 |
| M2 `signal-bridge` | `signal-bridge` | CAN ↔ 内部变量/输出信号映射 | 无 |
| M3/M8 `req-review` | `req-review` | 需求审查 + 追溯 | 无 |
| M4 `data-diagnostics` | `data-explore` | 车辆数据探针（无代码假设） | 无 |
| M6 `diagnosis-panel` | `diagnosis-panel` | 独立诊断面板（分类 + 专家） | 是 |
| M7 `code-review` | `code-review` | 离线确定性代码审查 | 无 |
| M9 `bsd-data-bridge` | `bsd-data-bridge` | BSD 信号匹配 + 条件交叉验证 | 无 |
| **M10 `signal-audit`** | **`signal-audit`** | **BLF 关键链路信号抽取 + 契约审计** | **无** |
| PR5 `agent-loop` | `agent-loop` | 确定性离线 AgentLoop | 无 |
| PR6-F `project-init` | `project-init` | 最小输入项目接入 | 无 |

> **M10 signal-audit**（2026-08 新增）：用户可直接 `python cli.py signal-audit --blf-path x.blf --mode audit`
> 查看关键链路信号（ADCMode_UI_Status / FCTA_Enable_S / FCTA_FCTB_Status_S 等）的枚举合法性、
> 存在性与 UI 模式回传契约，不必走完整诊断。

### 5.3 诊断能力覆盖的功能

| 功能 | 英文 | 说明 |
|------|------|------|
| BSD | Blind Spot Detection | 盲区检测 |
| LCA | Lane Change Assist | 变道辅助 |
| DOW | Door Open Warning | 开门预警 |
| RCW | Rear Collision Warning | 后碰预警 |
| RCTA | Rear Cross Traffic Alert | 后向横穿预警 |
| RCTB | Rear Cross Traffic Brake | 后向横穿制动 |
| FCTA | Front Cross Traffic Alert | 前向横穿预警 |
| FCTB | Front Cross Traffic Brake | 前向横穿制动 |

---

## 6. 记忆系统（L1–L6）与 Auto Dream

<div align="center">

<!-- SVG 4: 记忆层级 -->
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 860 400" width="860" height="400" font-family="Microsoft YaHei, Segoe UI, sans-serif">
  <rect x="0" y="0" width="860" height="400" fill="#fcfdfe" rx="8"/>
  <text x="30" y="34" font-size="16" font-weight="bold" fill="#9c4221">记忆层级 L1–L6（memory/）</text>
  <g font-size="12" fill="#333">
    <rect x="30" y="52" width="780" height="46" fill="#fffaf0" stroke="#c05621" rx="5"/>
    <text x="50" y="72" font-size="13" font-weight="bold" fill="#9c4221">L1 · Project Memory</text>
    <text x="50" y="90" fill="#7b341e">project.md — 项目约定 / 架构 / 已知怪癖</text>

    <rect x="30" y="106" width="780" height="46" fill="#fffaf0" stroke="#c05621" rx="5"/>
    <text x="50" y="126" font-size="13" font-weight="bold" fill="#9c4221">L2 · Function Knowledge</text>
    <text x="50" y="144" fill="#7b341e">functions/&lt;FUNC&gt;.json — 状态机 / 阈值 / 关键变量</text>

    <rect x="30" y="160" width="780" height="46" fill="#fffaf0" stroke="#c05621" rx="5"/>
    <text x="50" y="180" font-size="13" font-weight="bold" fill="#9c4221">L3 · Pattern Memory</text>
    <text x="50" y="198" fill="#7b341e">patterns.json — 症状 → 根因 → 修复建议（含衰减）</text>

    <rect x="30" y="214" width="780" height="46" fill="#fffaf0" stroke="#c05621" rx="5"/>
    <text x="50" y="234" font-size="13" font-weight="bold" fill="#9c4221">L4 · Session Memory</text>
    <text x="50" y="252" fill="#7b341e">sessions/&lt;id&gt;.json — 单次诊断过程</text>

    <rect x="30" y="268" width="780" height="46" fill="#fffaf0" stroke="#c05621" rx="5"/>
    <text x="50" y="288" font-size="13" font-weight="bold" fill="#9c4221">L5 · Case Memory</text>
    <text x="50" y="306" fill="#7b341e">cases/&lt;case&gt;/memory.json — 与案例数据共存</text>

    <rect x="30" y="322" width="780" height="46" fill="#fffaf0" stroke="#c05621" rx="5"/>
    <text x="50" y="342" font-size="13" font-weight="bold" fill="#9c4221">L6 · Code Knowledge</text>
    <text x="50" y="360" fill="#7b341e">code_knowledge/&lt;FUNC&gt;.json — CodeLearner 沉淀（alarm_logic / calculation_chain / output_chain / state_machine）</text>
  </g>
  <text x="30" y="392" font-size="12" fill="#718096">+ SemanticMemory（LanceDB 向量召回）| Freshness 指纹门控 | Auto Dream 跨会话模式沉淀</text>
</svg>

</div>

### Auto Dream 生命周期

```
诊断会话积累（≥2 新 session 且距上次 ≥4h）
  → Phase 0 Study：确定性索引刷新（signal_mapping / output_mapping / codegraph / conditions）+ CodeLearner 增量学习
  → Phase 1 Orient：审视 L1-L6 各层记忆
  → Phase 2 Gather：收集近期会话
  → Phase 3 Consolidate：LLM 合并 / 去重 / 解决冲突（症状→根因→修复 patterns）
  → Phase 4 Prune：应用变更 + 模式衰减（90 天 / 3 命中）
  → publish_knowledge_categories → knowledge_manifest.json（fresh 门控）
```

> **2026-08 重构要点**：Phase 0 改为"先确定性索引刷新、再 LLM 学习"；FOCUS 文件按 variant 动态解析
> （不再硬编码 GWM_B26），learn 从 0 对提升到 8 对，L6 知识真正进入诊断上下文。

---

## 7. CodeIndex：确定性代码索引

<div align="center">

<!-- SVG 5: CodeIndex 架构 -->
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 360" width="900" height="360" font-family="Microsoft YaHei, Segoe UI, sans-serif">
  <defs>
    <marker id="a5" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto">
      <path d="M0,0 L7,3 L0,6 Z" fill="#2f855a"/>
    </marker>
  </defs>
  <rect x="0" y="0" width="900" height="360" fill="#fcfdfe" rx="8"/>
  <text x="30" y="34" font-size="16" font-weight="bold" fill="#2f855a">CodeIndex — 代码是唯一事实源，知识是代码的确定性投影</text>

  <g font-size="12" fill="#333">
    <rect x="30" y="56" width="260" height="100" fill="#f0fff4" stroke="#38a169" rx="6"/>
    <text x="48" y="80" font-size="13" font-weight="bold" fill="#2f855a">CodeGraph（AST 图）</text>
    <text x="48" y="102" fill="#276749">FILE / FUNCTION / VARIABLE / SIGNAL</text>
    <text x="48" y="120" fill="#276749">CALLS / READS / WRITES / READS_SIGNAL</text>
    <text x="48" y="138" fill="#276749">WRITES_SIGNAL / SIGNAL↔VARIABLE 边</text>

    <rect x="320" y="56" width="260" height="100" fill="#f0fff4" stroke="#38a169" rx="6"/>
    <text x="338" y="80" font-size="13" font-weight="bold" fill="#2f855a">SignalMap（双向映射）</text>
    <text x="338" y="102" fill="#276749">RteComMapping Rx.c / Tx.c</text>
    <text x="338" y="120" fill="#276749">点号目标 + 输出信号动态解析</text>
    <text x="338" y="138" fill="#276749">output_mapping.json</text>

    <rect x="610" y="56" width="260" height="100" fill="#f0fff4" stroke="#38a169" rx="6"/>
    <text x="628" y="80" font-size="13" font-weight="bold" fill="#2f855a">ConditionTable</text>
    <text x="628" y="102" fill="#276749">规则层提取 + LLM 摘要（带 source hash）</text>
    <text x="628" y="120" fill="#276749">阈值 / 状态机 / 抑制条件</text>
    <text x="628" y="138" fill="#276749">{FUNC}_conditions.json</text>
  </g>

  <g stroke="#2f855a" stroke-width="1.6" marker-end="url(#a5)">
    <line x1="160" y1="156" x2="160" y2="190"/>
    <line x1="450" y1="156" x2="450" y2="190"/>
    <line x1="740" y1="156" x2="740" y2="190"/>
  </g>

  <rect x="30" y="196" width="840" height="60" fill="#ebf8ff" stroke="#3182ce" rx="6"/>
  <text x="50" y="222" font-size="13" font-weight="bold" fill="#2b6cb0">Freshness 闭环</text>
  <text x="50" y="244" font-size="12" fill="#2c5282">fingerprint（source hash / commit / dbc hash / scope）→ freshness_state.json 基线 → knowledge_manifest 按能力模块发布 → 消费端 fail-closed 门控</text>

  <g stroke="#2f855a" stroke-width="1.6" marker-end="url(#a5)">
    <line x1="160" y1="256" x2="160" y2="290"/>
  </g>
  <rect x="30" y="296" width="840" height="48" fill="#faf5ff" stroke="#805ad5" rx="6"/>
  <text x="50" y="324" font-size="13" font-weight="bold" fill="#553c9a">LLM 摘要层（绑定 source hash，失效即弃）— 供专家面板消费</text>
</svg>

</div>

---

## 8. 技术栈

### 8.1 运行时依赖

| 依赖 | 版本 | 用途 | 层级 |
|------|------|------|------|
| python-can | ≥4.0.0 | BLF 总线数据解析 | L0 |
| cantools | ≥39.0.0 | DBC 数据库解析 / 信号解码 | L0 |
| rosbags | ≥0.9.0 | ROS bag 解析 | L0 |
| asammdf | ≥8.0.0 | MF4 测量文件解析 | L0 |
| asteval | ≥1.0.0 | 条件表达式安全求值 | L1 |
| openai | ≥1.0.0 | OpenAI-compatible API 客户端 | L2 |
| langgraph | ≥0.2.0 | 专家面板状态机（多 LLM 3 轮） | L2 |
| lancedb | ≥0.5.0 | 语义记忆向量库（可降级余弦回退） | L3 |
| pydantic | ≥2.0 | 需求结构化强校验 | L3 |
| plotly | ≥5.20.0 | HTML 报告图表 | L8 |
| markdown | ≥3.5 | Markdown 渲染 | L8 |
| pyyaml | ≥6.0 | 配置文件解析 | 全部 |
| python-dotenv | ≥1.0.0 | 环境变量加载 | 全部 |
| rich | ≥13.0.0 | CLI 输出渲染 | CLI |
| pytest | ≥7.0 | 单元测试 | 测试 |

### 8.2 技术选型要点

- **确定性优先，LLM 补缺**：`engines/` 全部无 LLM、可独立测试；LLM 只负责理解、编排、摘要。
- **SQLite 统一存储**：FrameStore（数据帧）与 CodeGraph（AST 图）均用 SQLite，无外部服务、离线可跑。
- **LangGraph 专家面板**：5 位专家（signal_chain / algorithm / system_state / perception / architecture）× 3 轮（平行分析 → 主持人挑战 → 合成），按 fail_type 选专家。
- **插件化平台适配**：`ai/platform_adapters/` 按 platform_id 注册（gen6_c_radar / gen5_cpp_radar 等），V3 模块走统一 `BaseModule` 契约。
- **Variant 隔离**：每个 variant 的 source_docs / memory / codegraph / semantic 索引隔离在 `.workspaces/<variant>/`，互不混用。
- **Freshness 门控**：`core/knowledge_guard.py` 对代码知识 / 语义记忆 / L6 做 fail-closed 门控，防止陈旧知识进入 AI prompt。

### 8.3 目录速览

```
radarAnalyze/
  cli.py                  # 统一 CLI（诊断/查询/绘图/模块分发）
  config.yaml / config.local.yaml   # 模型 / 路径 / 功能 / 变体配置
  engines/                # L1 确定性引擎（signal_mapper / signal_audit / tpe / ...）
  ai/                     # L2 AI 层（orchestrator / expert_panel / code_learner / codegraph / modules / ...）
  core/                   # 身份 / 材料 / 诊断包 / 插件 / freshness / workspace
  parsers/                # L0 数据解析（bag / blf / mf4 / dbc / frame_store / case_loader）
  memory/                 # L3 记忆（memory_system / auto_dream / semantic_memory）
  source_docs/            # 缓存知识（conditions / signal_mapping / code_patterns）
  cases/                  # 案例数据（.bag/.blf + 报告产物）
  ai/modules/             # V3 能力模块（M1-M10）
  prompts/                # 专家面板 prompt 模板
  tools/                  # 工具（harness gate / 绘图 / prewarm 计时）
  tests/                  # 单元测试
  docs/technical/         # 技术文档
```

---

## 9. 配置与变体接入

### 9.1 变体模型

```yaml
variants:
  gen6/byd_uke_em2e_index_8:   # variant_id
    codebase_id: cr60_light
    display_name: "BYD_UKE EM2E_INDEX_8 (CR60Light)"
    coem_project_dir: coem/BYD_UKE
    scope: { include: ["coem/BYD_UKE/**"] }
    key_source_files: [ ...ASW_ADAS / RteComMapping_Rx.c / ASWOUT_OutCalc.c ... ]
    source_domains: { algorithm: [...], signal_chain: [...], output: [...] }
    dbc_sets: { default: { files: [...PublicCAN DBCs...] } }
    source_context:
      source_root: D:\BYD-SC6H-cr60light\cr60_light
      allow_branch_mismatch: true     # detached HEAD 场景
      workspace_dir: .workspaces/gen6_byd_uke_em2e_index_8
```

### 9.2 接入新车型（project-init）

```bash
python cli.py project-init \
  --name "CR60 Light BYD SC6H" \
  --code-root D:\cr60_light \
  --customer BYD --vehicle-project SC6H \
  --coem-project BYD_SC6H \
  --dbc D:\dbc\primary.dbc \
  --requirements D:\cr60_light\coem\BYD_SC6H\requirements \
  --expected-branch master --case-dir D:\cases\CASE001
```

---

## 10. 运行示例

```bash
# 1. 诊断（日常主路径）
python cli.py cases/FCTA001 -p "FCTA没有触发" -e "应该触发"

# 2. 带预热的诊断
python cli.py cases/EM2E_FCTAFCTB_SwitchAutoOn \
  -p "FCTA/FCTB功能开关关闭后会自动打开" -e "关闭后应保持关闭" \
  --variant gen6/byd_uke_em2e_index_8 --prewarm

# 3. 数据问答
python cli.py cases/FCTA001 -q "FCTB触发时AEBIB是否激活"

# 4. 信号绘图
python cli.py cases/FCTA001 --plot-signals "VehSpd_0x137,FCTA_Warn"

# 5. 关键信号审计（直接查 BLF）
python cli.py signal-audit --blf-path x.blf --mode audit --dbc publiccan.dbc

# 6. 记忆固化
python cli.py --dream

# 7. 聚合回归门禁
python tools/run_harness_gate.py --allow-known-edge
```

---

## 11. 测试与质量

- **单元测试**：`tests/`，覆盖信号映射、信号审计、TPE、codegraph、freshness、CLI 分发、memory 等
- **聚合回归**：`tools/run_harness_gate.py` 对既有案例（BSDLCA001 / FCTA001 / FCTB003 / sc6hrcta001 等）跑分门禁
- **确定性引擎可独立测试**：`tools/run_tpe_smoke.py`、`tests/test_signal_mapper_tx.py` 等
- **新增用例**（2026-08）：`tests/test_signal_audit.py`（M10 契约审计）、`tests/test_signal_mapper_tx.py`（TX 方向 + 点号目标）、`tests/test_codegraph_tx.py`（调用链 + variant 隔离）

---

## 12. 已知边界与后续方向

- **报告根因由 LLM 撰写**：确定性证据链已建扎实，但报告"不幻觉、只讲证据"仍需 L6 知识与专家 prompt 进一步对齐。
- **感知层源码覆盖**：部分 variant 的感知源码（track.c / objAttribCal.c）未在源码树中，相关 focus 会跳过。
- **Auto Dream 模式沉淀**：代码学习已打通，跨会话"症状→根因"模式归纳仍在演进。
- **MF4 / BSD 专项**：M9 bsd-data-bridge 独立运行，未来可接入诊断管线 Step 5。
