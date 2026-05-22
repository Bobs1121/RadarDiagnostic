# CodeGraph 改造 Handoff

> 分支: `refactor/codegraph`
> 创建: 2026-05-22
> 目标: 构建确定性代码知识图谱 (SQLite)，让 LLM 快速定位问题相关代码和结构化数据，作为确定性输入用于数据分析

---

## 1. 改造目标 (一句话)

**让 LLM 在诊断时能快速找到问题相关的代码位置和相关结构化数据，不再依赖关键字模糊搜索。**

具体:
- 函数调用链: "谁调用了 FctaFctbUpdateStatus → 它又调了谁" — 一行 SQL
- 变量反向追踪: "哪些功能用了 fFctbActiveUpSpd" — 一行 SQL
- 信号链路: "FCTB 读写了哪些 CAN 信号" — 一行 SQL
- 跨模块共享: "FCTB 和 FCTA 共用了哪些函数" — 一行 SQL
- 自动增量: 源码变了自动检测，只重建受影响子图
- LLM 注入: 把 CodeGraph 查询结果直接渲染成 prompt 片段，替代现在散落在各处的 JSON/MD 文件

---

## 2. 现状数据 (已调研确认)

### 2.1 源码规模

| 范围 | 文件数 | 总行数 | 函数定义数 |
|------|--------|--------|-----------|
| 15 个 key_source_files | 15 | 41,451 | 748 |
| coem/GWM_B26/components/ 全部 .c | 152 | 64,474 | — |

最大文件: `track.c` (15,659 行, 386 函数), `adasFunc.c` (11,456 行, 111 函数)

### 2.2 现有代码知识的消费方 (完整引用点)

**orchestrator.py (23 处引用):**
| 方法 | 消费了什么 | 用途 |
|------|-----------|------|
| `_ensure_source_docs` | CodeLearner + signal_mapping | Step 1 生成缓存 |
| `_understand_problem` | `source_docs/{fn}.md` | 注入问题理解 prompt |
| `_run_tpe` | signal_mapping + variable_chains + output_mapping + code_knowledge aliases | TPE 引擎输入 |
| `_check_suppression_signals` | signal_mapping + variable_chains | 抑制信号解析 |
| `_analyze_output_signals` | output_mapping | 输出信号分析 |
| `_load_threshold_reference` | `source_docs/{fn}.md` | 权威阈值参考 |
| `_collect_speed_thresholds` | `source_docs/{fn}_conditions.json` | 速度阈值 |

**expert_panel.py (7 处引用):**
- 5 个专家定义引用了源码文件路径 (system_state, algorithm, signal_chain, perception, architecture)
- `_load_expert_sources` 直接读取原始 C 源码注入专家 prompt (有缓存)
- `_moderator_synthesize` 引用 source_docs 阈值参考

**variable_query_planner.py (5 处引用):**
- `_render_code_knowledge`: 通过 `memory.render_code_knowledge_for_context(func_name, max_chars=4000)` 获取 L6 JSON
- `_render_constants`: 通过 `memory.render_constants_for_context(func_name)` 获取数值常量
- prompt 模板注入 `{code_knowledge}` 块

**condition_extractor.py (8 处引用):**
- `_extract_with_ai`: 从 `source_domains` 读取 C 源码，按关键词过滤注入 prompt
- `_backfill_can_signals`: 用 signal_mapping + variable_chains 解析 Unknown 信号名
- 缓存失效检查基于 `source_domains` 文件 mtime

**data_query_engine.py (10 处引用):**
- `_build_knowledge_context`: 综合读取 signal_mapping.json + radar_knowledge.json + `{fn}_conditions.json` + `{fn}.md` + L6 code_knowledge
- `_get_transform_note`: 读取 signal_mapping.json 查找信号转换

**data_probe.py: 零引用** (纯 SQLite 查询执行器)

### 2.3 现有确定性分析模块

| 模块 | 输入 | 输出 | 缓存 | 方法 |
|------|------|------|------|------|
| signal_mapper | RteComMapping.c | signal_mapping.json (40KB) | SHA256 前 16 位 | 纯正则 |
| signal_mapper | ASWOUT_OutCalc.c | output_mapping.json (57KB) | SHA256 前 16 位 | 纯正则 |
| signal_mapper | 多文件 | variable_chains.json (2KB) | 无缓存，每次重写 | 纯正则 |
| pattern_extractor | 关键文件 | code_patterns.json (56KB) | 源码目录 hash | 纯正则，仅 2/6 模式 |
| parameter_analyzer | 关键文件 | parameters.json (83KB) | SHA1 | 纯正则 |

### 2.4 现有 LLM 代码知识

| 文件 | 大小 | 生成方式 |
|------|------|---------|
| `{FUNC}.json` (×8) | 15-32KB 每个 | CodeLearner + LLM |
| constants.json | 14KB | CodeLearner + LLM |
| `source_docs/{FUNC}.md` (×8) | 9-12KB 每个 | CodeLearner + LLM |
| `source_docs/{FUNC}_conditions.json` (×8) | 7-12KB 每个 | condition_extractor + LLM |

---

## 3. 架构设计

### 3.1 分层模型

```
┌───────────────────────────────────────────────┐
│         消费层 (不变 — 接口兼容)                │
│  orchestrator / expert_panel /                 │
│  variable_query_planner / data_query_engine    │
│  condition_extractor / data_probe              │
├───────────────────────────────────────────────┤
│         适配层 (新建 — 桥接旧接口)              │
│  ai/codegraph/adapters.py                      │
│  - signal_mapping() → 查 edges WHERE           │
│  - variable_chains() → 查 READS/WRITE_VAR      │
│  - code_patterns() → 查 behaviour_pattern 边   │
│  - parameters() → 查 CALIB_PARAM 节点          │
├───────────────────────────────────────────────┤
│         CodeGraph 核心层 (新建)                 │
│  ai/codegraph/builder.py    — 构建器           │
│  ai/codegraph/analyzer.py   — 静态分析器        │
│  ai/codegraph/schema.py     — SQLite schema    │
│  ai/codegraph/query.py      — 查询 API         │
│  ai/codegraph/render.py     — 图 → prompt 渲染  │
├───────────────────────────────────────────────┤
│         存储层                                 │
│  memory/codegraph.db (SQLite)                  │
└───────────────────────────────────────────────┘
```

### 3.2 节点类型 (7 种)

| type | id 格式 | 核心属性 |
|------|---------|---------|
| FILE | `FILE:adasFunc` | file_path, hash, line_count |
| FUNCTION | `FUNCTION:FctaFctbUpdateStatus` | file_id, start_line, end_line, return_type, params, is_static |
| VARIABLE | `VARIABLE:fFctbActiveUpSpd` | scope (global/static_global/local/struct_field), data_type, defined_in, line, struct_owner |
| SIGNAL | `SIGNAL:FCTB_Enable_S` | direction (Rx/Tx), can_name, can_id, rte_read_fn, rte_write_fn |
| STATE | `STATE:FCTB.Active` | func, state_id (0-6), state_name |
| MODULE | `MODULE:FCTB` | keywords (from FUNC_KEYWORDS), side (front/rear) |
| CALIB_PARAM | `CALIB_PARAM:fFctbBrakeTime` | value, unit, category, formula, computed_value |

### 3.3 边类型 (12 种)

| type | source → target | 属性 |
|------|----------------|------|
| CALLS | FUNCTION → FUNCTION | line, column |
| CALLS_MACRO | FUNCTION → FUNCTION | line, macro_name (宏间接调用) |
| READS_VAR | FUNCTION → VARIABLE | line |
| WRITES_VAR | FUNCTION → VARIABLE | line |
| READS_SIGNAL | FUNCTION → SIGNAL | line, rte_call |
| WRITES_SIGNAL | FUNCTION → SIGNAL | line, rte_call |
| ACCESSES_FIELD | FUNCTION → VARIABLE | line, struct_name, field_name (struct→field 访问) |
| BELONGS_TO | FUNCTION/VARIABLE/SIGNAL → MODULE | binding_method (keyword/call_graph/manual) |
| DEFINED_IN | FUNCTION/VARIABLE → FILE | line |
| FILE_INcludes | FILE → FILE | line (#include) |
| TRANSITION | STATE → STATE | condition_str, from_func, line |
| PARAM_FOR | CALIB_PARAM → MODULE | category, role |

### 3.4 行为模式 (在边上标记)

| pattern_type | 检测方式 | 存储 |
|-------------|---------|------|
| HoldRelease | 正则: `if(cond){flag=false; time=0}` | 边属性 `pattern='HoldRelease'` |
| HoldEntry | 正则: `if(cond){flag=true; time=0}` | 边属性 `pattern='HoldEntry'` |
| Accumulate | 正则: `time+=dt` + `time=0` in else | 边属性 `pattern='Accumulate'` |
| Hysteresis | 同变量不同阈值 enter/exit | 边属性 `pattern='Hysteresis'` |
| Debounce | `cnt++` + `cnt>=N` latch | 边属性 `pattern='Debounce'` |
| EdgeTrigger | `prev==0 && cur!=0` | 边属性 `pattern='EdgeTrigger'` |

### 3.5 LLM 语义层 (存在 CodeGraph DB 中)

```sql
CREATE TABLE node_semantics (
    node_id TEXT PRIMARY KEY REFERENCES nodes(id),
    focus TEXT NOT NULL,          -- alarm_logic / calculation_chain / output_chain / state_machine
    semantic_json TEXT NOT NULL,  -- LLM 抽取的业务语义 (原有 code_knowledge JSON 的内容)
    source_hash TEXT,
    learned_at TEXT DEFAULT (datetime('now')),
    UNIQUE(node_id, focus)
);
```

CodeLearner 改造后: 先查 CodeGraph 拿到精确范围 → 拼 prompt → LLM 输出语义 → 写入 `node_semantics`。

### 3.6 增量构建策略

```
每次诊断启动 / dream 时:
1. 扫描 key_source_files，计算 SHA-256
2. 对比 codegraph.db 中 file_hashes 表
3. 未变文件 → 跳过
4. 变化文件 → 清除该文件相关的节点和边 → 重新分析
5. 级联更新: 如果函数 F 的签名变了，所有 CALLS → F 的边需要更新调用方的 line 号
```

---

## 4. SQLite Schema

```sql
-- 版本管理
CREATE TABLE schema_version (
    version INTEGER PRIMARY KEY DEFAULT 1,
    applied_at TEXT DEFAULT (datetime('now'))
);

-- 文件 hash (增量用)
CREATE TABLE file_hashes (
    file_path TEXT PRIMARY KEY,       -- 相对 source_root 的路径
    hash TEXT NOT NULL,               -- SHA-256 前 16 位
    line_count INTEGER,
    analyzed_at TEXT DEFAULT (datetime('now'))
);

-- 节点
CREATE TABLE nodes (
    id TEXT PRIMARY KEY,              -- 格式: <TYPE>:<name>
    type TEXT NOT NULL,               -- FILE/FUNCTION/VARIABLE/SIGNAL/STATE/MODULE/CALIB_PARAM

    -- 通用
    name TEXT NOT NULL,
    display_name TEXT,

    -- FILE
    file_path TEXT,

    -- FUNCTION
    file_id TEXT REFERENCES nodes(id),
    start_line INTEGER,
    end_line INTEGER,
    return_type TEXT,
    params TEXT,
    is_static INTEGER DEFAULT 0,

    -- VARIABLE
    scope TEXT,                       -- global/static_global/local/struct_field
    data_type TEXT,
    defined_in TEXT,                  -- 文件路径
    line INTEGER,
    struct_owner TEXT,                -- 如果是 struct field

    -- SIGNAL
    direction TEXT,                   -- Rx/Tx
    can_name TEXT,
    can_id TEXT,
    rte_read_fn TEXT,
    rte_write_fn TEXT,

    -- STATE
    state_id INTEGER,
    state_name TEXT,
    func TEXT,

    -- MODULE
    keywords TEXT,                    -- JSON array
    side TEXT,                        -- front/rear

    -- CALIB_PARAM
    value REAL,
    unit TEXT,
    category TEXT,                    -- vehicle_config/function_thresholds/roi_derived
    formula TEXT,
    computed_value REAL,

    source_hash TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

-- 边
CREATE TABLE edges (
    id TEXT PRIMARY KEY,              -- 格式: <source>-><target>:<type>:<line>
    source TEXT NOT NULL REFERENCES nodes(id),
    target TEXT NOT NULL REFERENCES nodes(id),
    type TEXT NOT NULL,               -- CALLS/READS_VAR/WRITES_VAR/READS_SIGNAL/...
    line INTEGER,
    column INTEGER,
    condition TEXT,                   -- 条件上下文 (if 条件字符串)
    pattern TEXT,                     -- 行为模式标签
    macro_name TEXT,                  -- 如果是宏间接调用
    struct_name TEXT,                 -- struct 访问时
    field_name TEXT,                  -- struct field 访问时
    rte_call TEXT,                    -- Rte_Read/Write 的完整调用字符串
    binding_method TEXT,              -- BELONGS_TO 的绑定方式
    source_hash TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

-- LLM 语义层 (code_knowledge 的新存法)
CREATE TABLE node_semantics (
    node_id TEXT PRIMARY KEY REFERENCES nodes(id),
    focus TEXT NOT NULL,
    semantic_json TEXT NOT NULL,
    source_hash TEXT,
    learned_at TEXT DEFAULT (datetime('now')),
    UNIQUE(node_id, focus)
);

-- 构建日志
CREATE TABLE build_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    build_time TEXT DEFAULT (datetime('now')),
    build_type TEXT,                  -- incremental/full
    files_scanned INTEGER DEFAULT 0,
    files_changed INTEGER DEFAULT 0,
    nodes_added INTEGER DEFAULT 0,
    edges_added INTEGER DEFAULT 0,
    nodes_removed INTEGER DEFAULT 0,
    edges_removed INTEGER DEFAULT 0,
    duration_sec REAL,
    summary TEXT
);

-- 索引
CREATE INDEX idx_edges_source ON edges(source);
CREATE INDEX idx_edges_target ON edges(target);
CREATE INDEX idx_edges_type ON edges(type);
CREATE INDEX idx_edges_source_type ON edges(source, type);
CREATE INDEX idx_edges_target_type ON edges(target, type);
CREATE INDEX idx_edges_source_target_type ON edges(source, target, type);
CREATE INDEX idx_nodes_type ON nodes(type);
CREATE INDEX idx_nodes_name ON nodes(name);
CREATE INDEX idx_nodes_file ON nodes(file_id);
CREATE INDEX idx_nodes_type_name ON nodes(type, name);
CREATE INDEX idx_semantics_focus ON node_semantics(focus);
```

---

## 5. 包结构

```
ai/codegraph/
  __init__.py            # 导出 CodeGraph, CodeGraphBuilder
  schema.py              # SCHEMA_VERSION, INIT_SQL
  builder.py             # CodeGraphBuilder 类 — 主入口
  analyzer.py            # 静态分析器: 函数提取、调用图、变量访问、信号接口、状态机、模式检测
  query.py               # 查询 API: 常用查询的 SQL 封装 + 自然语言 → SQL
  render.py              # 图 → prompt 渲染: 渲染调用链、变量依赖、信号链路为 Markdown
  adapters.py            # 兼容层: signal_mapping() / variable_chains() / code_patterns() 等旧接口
```

---

## 6. 实现计划

### Phase 1: 基础设施 (本次 Handoff 首要任务)

**产出: 能跑 `py -3.11 cli.py --build-codegraph`，扫描 15 个文件，建立 FILE + FUNCTION 节点**

1. 创建 `ai/codegraph/` 包
2. `schema.py` — 完整 SQL schema (见第 4 节)
3. `builder.py` — `CodeGraphBuilder.build(key_files, force)` 入口
4. `analyzer.py` — Phase 1 (File Index) + Phase 2 (Function Extraction)
5. CLI 集成: `--build-codegraph` + `--codegraph-stats`

**文件提取算法要点:**
```python
# 函数定义正则 (支持 static/inline/CONST 修饰符)
FUNC_DEF_RE = re.compile(
    r'^(?:(?:static|inline|CONST)\s+)*'
    r'(?P<ret>\w+(?:_t)?(?:\s*(?:Const|Ref))?)\s+'
    r'(?P<name>\w+)\s*'
    r'\((?P<params>[^)]*)\)'
    r'\s*$'
)

# 跳过关键字: if/else/while/for/switch/do/return/typedef/struct/enum/union

# 函数体边界: 栈匹配 { } (先 strip 字符串和注释)

# 大文件处理: 逐行处理，不一次性全量加载 (track.c 15K 行)
```

**验证:**
```bash
py -3.11 cli.py --build-codegraph
# 预期输出:
# files_scanned: 15
# files_changed: 15 (首次)
# nodes_added: ~750 (FUNCTION) + 15 (FILE) + 8 (MODULE)
# edges_added: ~30 (DEFINED_IN) + ~80 (BELONGS_TO)

py -3.11 cli.py --codegraph-stats
# 预期输出:
# nodes: FILE=15, FUNCTION=748, MODULE=8, VARIABLE=0, SIGNAL=0, STATE=0, CALIB_PARAM=0
# edges: DEFINED_IN=748, BELONGS_TO=80
```

### Phase 2: 关系抽取 (最有价值的部分)

**产出: CALLS 边 + READS/WRITE_VAR 边 + READS/WRITE_SIGNAL 边**

1. `analyzer.py` — Phase 3 (Call Graph): 对每个函数体，匹配 `function_name(` 模式
2. `analyzer.py` — Phase 4 (Variable Access): 匹配全局变量访问，区分读/写
3. `analyzer.py` — Phase 5 (Signal Interface): 匹配 `Rte_*_Read_*` / `Rte_*_Write_*` / `ReadSignal()` / `WriteSignal()`

**核心正则:**
```python
# 函数调用
FUNC_CALL_RE = re.compile(r'\b(?P<name>\w+)\s*\(')

# Rte Read/Write
RTE_READ_RE  = re.compile(r'Rte_(?:\w+_)?Read_(?P<module>\w+)_(?P<signal>\w+)\s*\(')
RTE_WRITE_RE = re.compile(r'Rte_(?:\w+_)?Write_(?P<module>\w+)_(?P<signal>\w+)\s*\(')

# AUTOSAR P2S/S2P
READ_SIGNAL_RE  = re.compile(r'ReadSignal\s*\(\s*(?P<signal>\w+)\s*\)')
WRITE_SIGNAL_RE = re.compile(r'WriteSignal\s*\(\s*(?P<signal>\w+)\s*,\s*(?P<var>\w+)\s*\)')

# 变量写 (排除 == 和 !=)
VAR_WRITE_RE = re.compile(r'(?P<var>\w+)\s*=[^=]')
VAR_WRITE_INC_RE = re.compile(r'(?P<var>\w+)(?:\+\+|--)|(?:\+\+|--)(?P<var2>\w+)')

# struct field 写
STRUCT_FIELD_WRITE_RE = re.compile(r'(?P<struct>\w+)(?:->|\.)\s*(?P<field>\w+)\s*=[^=]')
```

**读/写区分规则:**
- `var = ...` → write (排除 `==`, `!=`)
- `var++`, `++var`, `var--`, `--var` → write
- `->field =`, `.field =` → write (struct field)
- `&var` → read (标记可疑)
- 其他出现 → read

**验证:**
```bash
py -3.11 cli.py --build-codegraph
# 增量: 第二次运行 files_changed=0, 零耗时

# 手动验证
sqlite3 memory/codegraph.db "
  SELECT n.name FROM edges e
  JOIN nodes n ON e.source = n.id
  WHERE e.type = 'CALLS'
    AND e.target = 'FUNCTION:FctaFctbUpdateStatus'"
# 应该返回调用 FctaFctbUpdateStatus 的函数列表

# 与现有 signal_mapping.json 交叉验证
# CodeGraph 的 READS_SIGNAL 边数量 ≈ signal_mapping.json 的 mapping_count
```

### Phase 3: 高级分析

1. Phase 6 (State Machine): 匹配 `.systemState = N` + `switch(state)` + `if(state == N)`
2. Phase 7 (Module Binding): 基于 FUNC_KEYWORDS 绑定
3. Phase 8 (Cross-Module): 自动发现跨模块共享
4. Phase 9 (Calibration Params): 从 paraDefine.h 提取
5. Phase 10 (Behaviour Patterns): 6 种模式全量实现

### Phase 4: 适配层 + 集成

1. `adapters.py` — 实现旧接口兼容:
   - `get_signal_mapping(func)` → SQL 查 edges WHERE type IN ('READS_SIGNAL', 'WRITES_SIGNAL') AND source BELONGS_TO func
   - `get_variable_chains(func)` → SQL 查 READS_VAR/WRITES_VAR
   - `get_code_patterns(func)` → SQL 查 edges WHERE pattern IS NOT NULL
   - `get_parameters(func)` → SQL 查 CALIB_PARAM nodes
2. 改造 orchestrator: 逐步替换 source_docs JSON 读取为 CodeGraph 查询
3. 改造 variable_query_planner: prompt 注入 CodeGraph 渲染结果
4. 改造 condition_extractor: 从 CodeGraph 获取精确行号范围
5. 改造 CodeLearner: 先查 CodeGraph → 拼 prompt → 写 node_semantics

### Phase 5: 增量优化 + CLI 查询

1. 增量构建: file_hash 对比 + 级联更新
2. `--query-codegraph "自然语言问题"`: LLM 生成 SQL 查询
3. `--export-codegraph`: 导出 HTML 调用图

---

## 7. 查询 API 设计 (query.py)

```python
class CodeGraph:
    """CodeGraph 查询 API — 面向消费方的常用查询封装。"""

    def __init__(self, db_path: Path):
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row

    # ── 基础查询 ──

    def get_function(self, name: str) -> dict | None:
        """获取函数节点详情 (文件、行号、返回值、参数)。"""
        # SELECT * FROM nodes WHERE id = 'FUNCTION:{name}'

    def get_callers(self, func_name: str) -> list[dict]:
        """谁调用了这个函数?"""
        # SELECT n.name, n.start_line, e.line as call_line
        # FROM edges e JOIN nodes n ON e.source = n.id
        # WHERE e.type = 'CALLS' AND e.target = 'FUNCTION:{func_name}'

    def get_callees(self, func_name: str) -> list[dict]:
        """这个函数调用了谁?"""
        # SELECT n.name, e.line as call_line
        # FROM edges e JOIN nodes n ON e.target = n.id
        # WHERE e.type = 'CALLS' AND e.source = 'FUNCTION:{func_name}'

    def get_call_chain(self, func_name: str, depth: int = 3) -> list[dict]:
        """调用链 (递归 CTE)"""
        # WITH RECURSIVE chain AS (...) SELECT * FROM chain

    def get_variables_read_by(self, func_name: str) -> list[dict]:
        """这个函数读了哪些变量?"""
        # SELECT n.name, n.data_type, n.scope, e.line
        # FROM edges e JOIN nodes n ON e.target = n.id
        # WHERE e.type = 'READS_VAR' AND e.source = 'FUNCTION:{func_name}'

    def get_variables_written_by(self, func_name: str) -> list[dict]:
        """这个函数写了哪些变量?"""

    def who_reads_variable(self, var_name: str) -> list[dict]:
        """哪些函数读了这个变量? (反向查询 — 现有 JSON 做不到的)"""
        # SELECT n.name, e.line
        # FROM edges e JOIN nodes n ON e.source = n.id
        # WHERE e.type = 'READS_VAR' AND e.target = 'VARIABLE:{var_name}'

    def who_writes_variable(self, var_name: str) -> list[dict]:
        """哪些函数写了这个变量?"""

    def get_signals_for_module(self, module_name: str) -> list[dict]:
        """某个功能模块读/写了哪些信号?"""
        # SELECT s.can_name, s.direction, e.type, e.line
        # FROM edges e JOIN nodes s ON e.target = s.id
        # WHERE e.type IN ('READS_SIGNAL', 'WRITES_SIGNAL')
        #   AND e.source IN (SELECT source FROM edges WHERE type='BELONGS_TO' AND target='MODULE:{module_name}')

    def get_shared_entities(self, mod1: str, mod2: str) -> list[dict]:
        """两个功能模块共享了哪些函数/变量? (现有 JSON 做不到的)"""
        # SELECT n.name, n.type
        # FROM nodes n
        # WHERE n.id IN (SELECT source FROM edges WHERE type='BELONGS_TO' AND target='MODULE:{mod1}')
        #   AND n.id IN (SELECT source FROM edges WHERE type='BELONGS_TO' AND target='MODULE:{mod2}')

    def get_state_transitions(self, func_name: str) -> list[dict]:
        """状态机转换图"""
        # SELECT s1.state_name as from_state, s2.state_name as to_state, e.condition
        # FROM edges e
        # JOIN nodes s1 ON e.source = s1.id
        # JOIN nodes s2 ON e.target = s2.id
        # WHERE e.type = 'TRANSITION' AND s1.func = '{func_name}'

    def get_params_for_module(self, module_name: str) -> list[dict]:
        """某个功能模块的校准参数"""

    def get_patterns_for_module(self, module_name: str, pattern_type: str = None) -> list[dict]:
        """某个功能模块的行为模式"""

    # ── 自然语言查询 ──

    def query_nl(self, question: str, router) -> str:
        """自然语言 → SQL → 结果 (由 LLM 生成 SQL)。"""
```

---

## 8. Prompt 渲染设计 (render.py)

```python
class CodeGraphRenderer:
    """将 CodeGraph 查询结果渲染为 Markdown，注入 LLM prompt。"""

    def render_for_problem(self, graph: CodeGraph, func_name: str, problem: str) -> str:
        """为诊断问题渲染相关代码知识。

        替代现有:
        - memory_system.render_code_knowledge_for_context(func_name, max_chars=6000)
        - source_docs/{fn}.md 前 2000 字符

        输出格式:
        ## 代码结构
        ### {func_name} 的核心函数
        - FctaFctbUpdateStatus (adasFunc.c:2540-2800) — 被 X 个函数调用
        - FctbCheckTargets (adasFunc.c:2900-3100) — 调用了 Y 个函数

        ### 关键变量
        - fFctbActiveUpSpd (float, global) — 被 N 个函数读取, M 个函数写入
        - fctbSystemState (uint8, global) — 状态变量

        ### 信号链路
        - 输入: FCTB_Enable_S (Rx) → Rte_Read → adasFunc.c:2612
        - 输出: CR_BrkgReq (Tx) → Rte_Write → ASWOUT_OutCalc.c:XXX

        ### 调用链
        AswIfSchedule → FctaFctbUpdateStatus → FctbCheckTargets → ...
        """

    def render_for_probe(self, graph: CodeGraph, var_name: str) -> str:
        """为 DataProbe 渲染变量的完整依赖链。

        替代现有 variable_query_planner 注入的 code_knowledge 片段。
        """

    def render_for_condition(self, graph: CodeGraph, func_name: str) -> str:
        """为 condition_extractor 渲染精确的函数体范围。

        不再用 FUNC_KEYWORDS 模糊搜索，直接给出:
        "FctaFctbUpdateStatus 定义在 adasFunc.c:2540-2800，包含以下 if 条件块..."
        """

    def render_for_expert_panel(self, graph: CodeGraph, func_name: str) -> str:
        """为 Expert Panel 渲染代码知识摘要。"""
```

---

## 9. 适配层设计 (adapters.py)

保持现有接口不变，内部走 CodeGraph:

```python
def extract_signal_mapping(source_root, output_dir, *, use_codegraph=False) -> dict:
    """兼容 signal_mapper.extract_signal_mapping 的输出格式。

    use_codegraph=True 时从 CodeGraph DB 读取，返回相同结构的 dict:
    {source_hash, mappings[], internal_to_can{}, can_to_internal{}, fullpath_to_can{}}
    """

def load_variable_chains(output_dir, *, use_codegraph=False) -> dict:
    """兼容 signal_mapper.load_variable_chains。"""

def load_patterns(output_dir, *, use_codegraph=False) -> dict:
    """兼容 pattern_extractor 输出格式。"""

def scan_parameters(source_root, output_dir, *, use_codegraph=False) -> dict:
    """兼容 parameter_analyzer.scan_parameters。"""
```

**迁移策略**: 所有适配层默认 `use_codegraph=False` (读旧 JSON)。CodeGraph 就绪后翻 switch。

---

## 10. CLI 集成

```python
# cli.py 新增:

parser.add_argument("--build-codegraph", action="store_true",
                    help="Build/update CodeGraph from source code")
parser.add_argument("--codegraph-stats", action="store_true",
                    help="Show CodeGraph statistics")
parser.add_argument("--query-codegraph", type=str,
                    help="Query CodeGraph (natural language or SQL)")
parser.add_argument("--force", action="store_true",
                    help="Force full rebuild (for --build-codegraph)")
```

```bash
# 构建/增量更新
py -3.11 cli.py --build-codegraph
py -3.11 cli.py --build-codegraph --force

# 统计
py -3.11 cli.py --codegraph-stats

# 查询 (自然语言)
py -3.11 cli.py --query-codegraph "FCTB 的调用链是什么"
py -3.11 cli.py --query-codegraph "谁写了 CR_BrkgReq"
py -3.11 cli.py --query-codegraph "FCTB 和 FCTA 共享哪些函数"

# 查询 (SQL)
py -3.11 cli.py --query-codegraph "SELECT * FROM nodes WHERE type='FUNCTION' AND name LIKE '%Fctb%'"
```

---

## 11. 增量构建自动触发

在 orchestrator 的 Step 1 (`_ensure_source_docs`) 中新增:

```python
def _ensure_codegraph(self, status):
    """增量构建/更新 CodeGraph。"""
    from ai.codegraph.builder import CodeGraphBuilder

    status("codegraph", "Checking source changes...")
    builder = CodeGraphBuilder(
        source_root=Path(self.config["paths"]["source_code"]),
        db_path=self.project_root / "memory" / "codegraph.db",
    )
    result = builder.build(
        key_files=self.config["paths"].get("key_source_files", []),
        force=False,  # 增量
    )
    if result["files_changed"] > 0:
        status("codegraph", f"Updated: {result['files_changed']} files changed, "
               f"+{result['nodes_added']} nodes, +{result['edges_added']} edges")
    else:
        status("codegraph", "No source changes, skipped")
    return result
```

---

## 12. 环境信息

- **Python**: `py -3.11` (不要用 `python`)
- **工作目录**: `D:\RamboStar\idea\radarAnalyze`
- **源码根目录**: `D:\cr60_light` (config.yaml `paths.source_code`)
- **分支**: `refactor/codegraph`
- **Windows 路径**: 源码路径含反斜杠，存储时统一为正斜杠

---

## 13. 关键文件清单

| 文件 | 作用 | 改造方式 |
|------|------|---------|
| `ai/codegraph/` (新建) | CodeGraph 核心 | 新增 |
| `ai/code_learner.py` | 现有 LLM 代码学习 | 改造: 先查 CodeGraph 再送 LLM |
| `ai/signal_mapper.py` | 现有信号映射 | 保留，通过 adapters.py 桥接 |
| `ai/pattern_extractor.py` | 现有行为模式 | 保留，被 CodeGraph Phase 10 替代 |
| `ai/parameter_analyzer.py` | 现有参数分析 | 保留，被 CodeGraph Phase 9 替代 |
| `ai/orchestrator.py` | 诊断管线 | 新增 `_ensure_codegraph` 步骤 |
| `ai/expert_panel.py` | 专家面板 | prompt 注入改为 CodeGraph render |
| `ai/variable_query_planner.py` | 查询规划 | 注入改为 CodeGraph render |
| `ai/condition_extractor.py` | 条件提取 | 源码范围从 CodeGraph 获取 |
| `ai/data_query_engine.py` | 自然语言查数 | knowledge context 从 CodeGraph 获取 |
| `cli.py` | CLI 入口 | 新增 3 个 codegraph 命令 |
| `memory/codegraph.db` | SQLite 数据库 | 构建后生成 |
| `memory/code_knowledge/*.json` | 现有 LLM 知识 | 保留，逐步迁移到 node_semantics |

---

## 14. 下一步 (Priority Order)

1. **[P0]** 创建 `ai/codegraph/` 包 + schema + builder 骨架
2. **[P0]** 实现 Phase 1-2: File Index + Function Extraction
3. **[P0]** CLI `--build-codegraph` + `--codegraph-stats`
4. **[P1]** 实现 Phase 3: Call Graph (最有价值)
5. **[P1]** 实现 Phase 5: Signal Interface (与 signal_mapping.json 交叉验证)
6. **[P1]** 实现 query.py 基础查询 API
7. **[P2]** 实现 Phase 4: Variable Access
8. **[P2]** 实现 render.py: `render_for_problem()`
9. **[P2]** 适配层: `adapters.py` 实现 `get_signal_mapping(use_codegraph=True)`
10. **[P3]** Phase 6-10: 状态机 + 模块绑定 + 跨模块 + 参数 + 行为模式
11. **[P3]** orchestrator 集成
12. **[P4]** 逐步替换消费方的旧 JSON 引用为 CodeGraph 查询
