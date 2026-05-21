# CodeGraph 重构方案

> 分支: `refactor/codegraph`
> 状态: Design & Handoff
> 创建时间: 2026-05-21

---

## 1. 背景与问题

### 1.1 当前 code_knowledge 体系

当前代码知识存储在 `memory/code_knowledge/` 目录下，8 个功能模块各一个 JSON 文件，加一个全局常量文件。

**文件清单:**

| 文件 | 行数 | 大小 |
|------|------|------|
| FCTB.json | 778 | ~29KB |
| FCTA.json | 844 | ~32KB |
| RCTA.json | 752 | ~28KB |
| RCTB.json | 580 | ~20KB |
| BSD.json | 696 | ~24KB |
| LCA.json | 509 | ~18KB |
| DOW.json | 480 | ~16KB |
| RCW.json | 477 | ~15KB |
| constants.json | 558 | ~14KB |
| learning_state.json | 65 | ~2KB |

**每个功能 JSON 的固定结构 (4 个 focus 维度):**

```
{
  "_meta": { "learned_focuses": [...], "source_hashes": {...} },
  "alarm_logic": { "trigger_conditions": [...], "cancel_conditions": [...], ... },
  "calculation_chain": { "key_variables": {...}, "derivation_chain": [...], ... },
  "output_chain": { "outputs": [...], "merge_strategy": "...", ... },
  "state_machine": { "states": {...}, "transitions": [...], ... }
}
```

### 1.2 code_knowledge 的构建过程

由 `ai/code_learner.py` 的 `CodeLearner` 类驱动，核心流程：

```
1. 读取 learning_state.json 的 cursor 游标
2. 按 (focus × function) 轮转序列，取出下一个待学对
3. 根据 focus 查找 FOCUS_FILES[focus] 得到相关源码文件列表
4. 读取这些文件，计算聚合 hash → 与 learning_state.json 的 pair_hashes 比对
   → hash 未变则跳过（增量机制）
5. 用 FUNC_KEYWORDS[func] 作为关键字，从源码中抽取相关代码片段（_extract_snippets）
   → 基于正则匹配含关键字的行 + 12 行上下文
6. 将片段拼接为 prompt，调用 LLM 抽取结构化 JSON
7. 将 LLM 返回的 JSON 合并到 memory/code_knowledge/<FUNC>.json
   → 按 id 去重合并，新条目追加，已有条目内容变更时更新
8. 更新 cursor 和 pair_hashes
```

**为什么这样构建：**

- **LLM 驱动** — 核心抽取逻辑交给 LLM，因为 C 代码的控制流分析（条件组合、变量含义、业务语义）是 NLP 任务
- **焦点分离** — 4 个 focus 各有不同的 prompt 模板和系统提示，让 LLM 每次只关注一个维度，提高质量
- **关键字过滤** — 整个源码库太大，无法全部送入 LLM，用关键字做粗糙但有效的过滤
- **Hash 缓存** — 源码未改动就跳过，节省 token 和时间
- **增量合并** — 新条目追加、旧条目按 id 更新，保证知识只增不减

### 1.3 现有体系的痛点

| 问题 | 具体表现 |
|------|----------|
| **函数调用关系丢失** | 只能记录单个 `caller` 字段，无法追踪调用链。例如 `FctaFctbUpdateStatus` 被谁调用、它又调用了哪些函数，需要重新读源码 |
| **变量依赖没有显式连接** | `fFctbActiveUpSpd` 这个变量在 alarm_logic、calculation_chain 中散落出现，但无法回答"哪些功能都用到了这个变量" |
| **状态机转换是静态文本** | `from: "Any"`、`to: 2` 这种字符串，无法做图遍历（BFS/DFS） |
| **跨模块关系不可见** | FCTB 和 FCTA 共享 `FctaFctbUpdateStatus` 函数，但没有显式记录这种交叉依赖 |
| **反向查询不可能** | "谁写了 `CR_BrkgReq`？"、"修改 `adasFunc.c` 第 2600 行会影响哪些功能？" —— 无法回答 |
| **重复数据** | 8 个功能的 alarm_logic 结构完全一致（trig-1~trig-5 的字段名相同），只是内容不同 |
| **数据粒度粗** | LLM 抽取的是"语义块"级别，不是代码级别的精确 AST 节点 |

---

## 2. CodeGraph 设计目标

### 2.1 核心目标

构建一个**从源码静态分析自动生成**的代码知识图谱，解决上述问题：

1. **精确的调用关系** — 函数 A 调用函数 B，有行号级别精度
2. **变量读写依赖** — 函数 F 读/写了哪些全局变量
3. **信号链路追踪** — ReadSignal/WriteSignal 调用到 CAN 信号的完整链
4. **跨模块依赖发现** — 功能 X 和功能 Y 共享哪些函数/变量
5. **反向查询能力** — "修改文件 F 第 L 行会影响谁"
6. **增量更新** — 源码变更后只 diff 变化的子图

### 2.2 非目标

- **不替代 LLM 语义抽取** — CodeGraph 做结构化关系，LLM 做的业务语义（"这个条件表示车速在范围内"）仍然保留在 code_knowledge 中
- **不做完整类型推导** — C 的宏展开和头文件依赖链太长，只做实际使用层面的分析

---

## 3. 技术方案

### 3.1 总体架构

```
┌─────────────┐     ┌──────────────┐     ┌───────────────┐
│  C Source   │────>│ Static       │────>│ CodeGraph     │
│  Files (.c  │     │ Analyzer     │     │ SQLite DB     │
│   .h)       │     │ (Regex +     │     │               │
└─────────────┘     │  AST-lite)   │     └───────┬───────┘
                    └──────────────┘             │
                                              ┌───────┐
                                              │ Query │
                                              │ API   │
                                              └───────┘
```

### 3.2 为什么用正则/轻量解析而不是完整 C AST

- **libclang/cxxfilt** 需要编译数据库 (compile_commands.json) 和完整的头文件依赖链。嵌入式 AUTOSAR 项目有数百个头文件、条件编译宏，构建完整编译环境不现实
- **正则 + 手动括号匹配** 对于我们的目标（函数定义、调用、变量访问、RTE 信号接口）已经够用。C 代码虽然有宏，但核心逻辑的调用和变量访问模式是固定的
- 我们的目标不是编译器级别的精确，而是**分析级别的可用性**（90%+ 准确率即可，剩余靠 LLM 补全）

### 3.3 节点类型 (Node Types)

```sql
CREATE TABLE nodes (
    id          TEXT PRIMARY KEY,   -- 全局唯一，格式: <type>:<name>
    type        TEXT NOT NULL,      -- FUNCTION / VARIABLE / SIGNAL / STATE / FILE / MODULE / CALIB_PARAM
    name        TEXT NOT NULL,      -- 显示名称
    display_name TEXT,              -- 人类可读名称（去前缀等）
    
    -- FUNCTION 特有
    file_id     TEXT,              -- 所属文件节点 id
    start_line  INTEGER,           -- 起始行号
    end_line    INTEGER,           -- 结束行号
    return_type TEXT,              -- 返回值类型
    params      TEXT,              -- 参数字符串（原始签名）
    is_static   INTEGER DEFAULT 0, -- 是否 static
    
    -- VARIABLE 特有
    scope       TEXT,              -- global / static_global / local / struct_field
    data_type   TEXT,              -- uint8_t / float / struct 等
    defined_in  TEXT,              -- 文件路径（相对 source_root）
    line        INTEGER,           -- 定义行号
    
    -- SIGNAL 特有
    direction   TEXT,              -- Rx / Tx
    can_name    TEXT,              -- CAN 信号名（DBC 名）
    message_id  TEXT,              -- CAN ID
    rte_function TEXT,             -- Rte_Read/Write 函数名
    
    -- STATE 特有
    state_id    INTEGER,           -- 状态编号 0-6
    state_name  TEXT,              -- None/Init/Standy/Active/Off/Failure/Passive
    
    -- MODULE 特有
    keywords    TEXT,              -- JSON 数组，FUNC_KEYWORDS 中的关键字
    
    -- 通用
    source_hash TEXT,              -- 该节点涉及的源码 hash（用于增量更新）
    created_at  TEXT DEFAULT (datetime('now')),
    updated_at  TEXT DEFAULT (datetime('now'))
);
```

### 3.4 边类型 (Edge Types)

```sql
CREATE TABLE edges (
    id              TEXT PRIMARY KEY,
    source          TEXT NOT NULL REFERENCES nodes(id),
    target          TEXT NOT NULL REFERENCES nodes(id),
    type            TEXT NOT NULL,  -- 见下方枚举
    line            INTEGER,       -- 边发生的行号
    column          INTEGER,
    condition       TEXT,          -- 条件上下文（如 if 条件字符串）
    source_hash     TEXT,          -- 增量更新用
    created_at      TEXT DEFAULT (datetime('now'))
);

-- 边类型枚举:
-- CALLS:          函数 A 调用函数 B
-- READS_VAR:      函数 F 读变量 V
-- WRITES_VAR:     函数 F 写变量 V
-- READS_SIGNAL:   函数 F 通过 Rte_Read 读信号 S
-- WRITES_SIGNAL:  函数 F 通过 Rte_Write 写信号 S
-- CALLS_AT:       函数 A 在第 L 行调用函数 B（带精确位置的 CALLS）
-- BELONGS_TO:     函数/变量/状态 属于 模块 M
-- DEFINED_IN:     函数/变量 定义在 文件 F
-- FILE_IN:        文件 F 在项目中的路径层级
-- TRANSITION:     状态 A → 状态 B（带 condition 字段）
-- SHARES:         模块 M1 和 M2 共享某个实体（自动推导）
-- PARAM_FOR:      变量 V 是模块 M 的校准参数
```

### 3.5 索引设计

```sql
-- 核心查询索引
CREATE INDEX idx_edges_source ON edges(source);
CREATE INDEX idx_edges_target ON edges(target);
CREATE INDEX idx_edges_type ON edges(type);
CREATE INDEX idx_edges_source_type ON edges(source, type);
CREATE INDEX idx_edges_target_type ON edges(target, type);
CREATE INDEX idx_nodes_type ON nodes(type);
CREATE INDEX idx_nodes_name ON nodes(name);
CREATE INDEX idx_nodes_file ON nodes(file_id);
```

### 3.6 SQLite 存储

- **理由**: 嵌入式、零配置、单文件、支持 FTS5、支持复杂查询（JOIN、子查询、递归 CTE）
- **文件位置**: `memory/codegraph.db`
- **版本管理**: 在 DB 中维护 `schema_version` 表，支持未来 schema 迁移

---

## 4. 静态分析器设计

### 4.1 分析阶段

```
Phase 1: File Index
  → 扫描所有 .c/.h 文件，建立文件节点
  
Phase 2: Function Extraction
  → 正则匹配函数定义，建立 FUNCTION 节点
  → 提取返回类型、参数、行号范围
  
Phase 3: Call Graph
  → 对每个函数体，匹配 `function_name(` 模式
  → 建立 CALLS 边
  
Phase 4: Variable Access
  → 匹配全局变量访问（通过 globalVarDefine.h 中的变量名列表）
  → 区分读/写（= 赋值左边 vs 其他位置）
  → 建立 READS_VAR / WRITES_VAR 边
  
Phase 5: Signal Interface
  → 匹配 Rte_*_Read_* 和 Rte_*_Write_* 调用
  → 匹配 ReadSignal()/WriteSignal() AUTOSAR 接口
  → 建立 SIGNAL 节点和 READS_SIGNAL / WRITES_SIGNAL 边
  
Phase 6: State Machine
  → 匹配 .systemState = N 赋值
  → 匹配 switch(state) / if(state == N)
  → 建立 STATE 节点和 TRANSITION 边
  
Phase 7: Module Binding
  → 基于 FUNC_KEYWORDS 将函数/变量绑定到功能模块
  → 建立 BELONGS_TO 边
  
Phase 8: Cross-Module Dependencies
  → 自动发现: 如果函数 F 属于模块 M1，但被模块 M2 的函数调用
  → 建立 SHARES 边
```

### 4.2 正则表达式核心模式

```python
# 函数定义 (支持 static, inline, 返回值类型, 函数名, 参数列表)
FUNC_DEF_RE = re.compile(
    r'^(?:(?:static|inline|const)\s+)*'           # 修饰符
    r'(?P<return_type>\w+(?:_t|Struct)?(?:\s*[\*\?])?)\s+'  # 返回类型
    r'(?P<name>\w+)\s*\('                          # 函数名
    r'\s*(?P<params>[^)]*)'                        # 参数
)

# 函数调用
FUNC_CALL_RE = re.compile(
    r'(?P<name>\w+)\s*\('                          # 函数名 + 左括号
)

# Rte Read/Write
RTE_READ_RE = re.compile(
    r'Rte_Read_(?P<module>\w+)_(?P<signal>\w+)\s*\('
)
RTE_WRITE_RE = re.compile(
    r'Rte_Write_(?P<module>\w+)_(?P<signal>\w+)\s*\('
)

# ReadSignal / WriteSignal (AUTOSAR P2S/S2P)
READ_SIGNAL_RE = re.compile(
    r'ReadSignal\s*\(\s*(?P<signal>\w+)\s*\)'
)
WRITE_SIGNAL_RE = re.compile(
    r'WriteSignal\s*\(\s*(?P<signal>\w+)\s*,\s*(?P<var>\w+)\s*\)'
)

# 全局变量赋值 (写)
VAR_WRITE_RE = re.compile(
    r'(?P<var>\w+)\s*=[^=]'                       # var = ... (不是 ==)
)
# 结构体字段访问
STRUCT_ACCESS_RE = re.compile(
    r'(?P<struct>\w+)(?:->|\.)(?P<field>\w+)'
)

# 状态机赋值
STATE_ASSIGN_RE = re.compile(
    r'(?P<var>\w+)\.?(?P<state_var>\w*SystemState\w*)\s*=\s*(?P<value>\w+)'
)
```

### 4.3 增量更新策略

```
1. 每次构建前，读取每个文件的 SHA-256 hash
2. 与 codegraph.db 中的 file_hashes 表比对
3. 未变化的文件 → 跳过该文件的所有分析阶段
4. 变化的文件 → 只重新分析该文件，并清除受影响的边
   → 清除: 该文件中定义的函数产生的所有边
   → 重建: 重新运行 Phase 2-8
5. 跨文件影响: 如果文件 A 的函数签名变了，所有调用该函数的边需要更新
```

```sql
CREATE TABLE file_hashes (
    file_path   TEXT PRIMARY KEY,
    hash        TEXT NOT NULL,
    analyzed_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE build_log (
    id          INTEGER PRIMARY KEY,
    build_time  TEXT DEFAULT (datetime('now')),
    files_added INTEGER,
    files_changed INTEGER,
    nodes_added INTEGER,
    edges_added INTEGER,
    summary     TEXT
);
```

---

## 5. 数据流与集成

### 5.1 构建入口

```python
# ai/codegraph_builder.py
class CodeGraphBuilder:
    def build(self, source_root: Path, force: bool = False) -> BuildResult:
        """全量/增量构建 CodeGraph"""
        
    def query(self, query_str: str, params: dict = None) -> list[dict]:
        """直接 SQL 查询"""
```

### 5.2 CLI 集成

在现有 `cli.py` 中新增命令：

```bash
# 构建/更新 codegraph
py -3.11 cli.py build-codegraph [--force]

# 查询 codegraph
py -3.11 cli.py query-codegraph "哪些函数调用了 FctaFctbUpdateStatus?"
py -3.11 cli.py query-codegraph "FCTB 模块用了哪些全局变量?"
py -3.11 cli.py query-codegraph "谁写了 CR_BrkgReq 信号?"

# 查看 codegraph 统计
py -3.11 cli.py codegraph-stats
```

### 5.3 与现有 CodeLearner 的关系

```
┌─────────────────────────────────────────────┐
│           代码知识体系 (重构后)               │
├─────────────────────┬───────────────────────┤
│   CodeGraph         │   code_knowledge/     │
│   (静态分析)         │   (LLM 语义抽取)       │
├─────────────────────┼───────────────────────┤
│ ✓ 函数调用图         │ ✓ 报警触发语义         │
│ ✓ 变量读写依赖       │ ✓ 业务含义解释         │
│ ✓ 信号链路           │ ✓ 阈值/参数值          │
│ ✓ 跨模块依赖         │ ✓ 状态机业务含义       │
│ ✓ 反向查询           │ ✓ 迟滞/定时器语义      │
│ ✓ 增量更新           │ ✓ 抑制/门控条件        │
└─────────────────────┴───────────────────────┘
              ↘                ↙
         在 Expert Panel / DataProbe 中联合使用
         CodeGraph 提供结构，code_knowledge 提供语义
```

**关键设计决策**: CodeGraph 和 code_knowledge **互补共存**，不互相替代：
- CodeGraph: "FctaFctbUpdateStatus 调用了 FctbCheckTargets"（精确关系）
- code_knowledge: "FctbCheckTargets 在 TTMX < 1.0s 时触发警告"（业务语义）

### 5.4 查询 API 示例

```python
# "哪些函数调用了 FctaFctbUpdateStatus?"
SELECT n.name, n.file_id, e.line
FROM edges e
JOIN nodes n ON e.source = n.id
WHERE e.type = 'CALLS' 
  AND e.target = 'FUNCTION:FctaFctbUpdateStatus'

# "FCTB 模块的所有函数"
SELECT n.name, n.start_line, n.end_line
FROM nodes n
WHERE n.type = 'FUNCTION'
  AND n.id IN (
    SELECT e.source FROM edges e
    WHERE e.type = 'BELONGS_TO' AND e.target = 'MODULE:FCTB'
  )

# "FCTB 和 FCTA 共享的函数"
SELECT n.name
FROM nodes n
WHERE n.type = 'FUNCTION'
  AND n.id IN (SELECT e.source FROM edges e WHERE e.type = 'BELONGS_TO' AND e.target = 'MODULE:FCTB')
  AND n.id IN (SELECT e.source FROM edges e WHERE e.type = 'BELONGS_TO' AND e.target = 'MODULE:FCTA')

# "修改 adasFunc.c 第 2600 行可能影响的模块"
SELECT DISTINCT m.name
FROM edges e1
JOIN nodes m ON e1.target = m.id
WHERE e1.type = 'BELONGS_TO' AND m.type = 'MODULE'
  AND e1.source IN (
    SELECT e2.source FROM edges e2
    WHERE e2.type = 'CALLS' AND e2.target IN (
      SELECT n.id FROM nodes n
      WHERE n.type = 'FUNCTION' AND n.file_id = 'FILE:adasFunc.c'
        AND 2600 BETWEEN n.start_line AND n.end_line
    )
  )
```

---

## 6. 实现计划

### Phase 1: 基础框架 (本次 Handoff 的首要任务)

- [x] 创建开发分支 `refactor/codegraph`
- [x] 调研现有 code_knowledge 构建过程
- [x] 编写本设计文档
- [ ] 创建 `ai/codegraph_builder.py` — 骨架代码
- [ ] 创建 SQLite schema 初始化脚本
- [ ] 实现 Phase 1-2: File Index + Function Extraction
- [ ] 实现增量 hash 机制

### Phase 2: 关系抽取

- [ ] Phase 3: Call Graph
- [ ] Phase 4: Variable Access
- [ ] Phase 5: Signal Interface

### Phase 3: 高级分析

- [ ] Phase 6: State Machine
- [ ] Phase 7: Module Binding
- [ ] Phase 8: Cross-Module Dependencies

### Phase 4: 集成

- [ ] CLI 命令集成 (`build-codegraph`, `query-codegraph`, `codegraph-stats`)
- [ ] 在 orchestrator 启动时自动增量构建
- [ ] DataProbe 集成 — 允许 VariableQueryPlanner 查询 codegraph
- [ ] 可视化 — 简单 HTML 调用图

### Phase 5: 质量验证

- [ ] 与现有 code_knowledge 交叉验证 — codegraph 发现的函数调用关系是否与 LLM 抽取的 code_ref 一致
- [ ] 准确率评估 — 抽样检查 20 个函数调用关系是否正确
- [ ] 性能测试 — 全量构建时间 < 30s

---

## 7. 技术细节补充

### 7.1 括号匹配 (函数体边界检测)

C 语言函数体的 `{` `}` 嵌套需要正确匹配。使用简单栈算法：

```python
def find_function_body_end(lines: list[str], start_line: int) -> int:
    """从函数定义行开始，找到函数体结束的 }"""
    brace_depth = 0
    found_open = False
    for i in range(start_line, len(lines)):
        line = lines[i]
        # 跳过字符串和注释中的括号
        clean = remove_strings_and_comments(line)
        for ch in clean:
            if ch == '{':
                brace_depth += 1
                found_open = True
            elif ch == '}':
                brace_depth -= 1
                if found_open and brace_depth == 0:
                    return i
    return len(lines) - 1  # 未找到匹配则返回文件末尾
```

### 7.2 字符串/注释中的假阳性过滤

```python
def remove_strings_and_comments(line: str) -> str:
    """移除 C 字符串字面和注释，避免 "function_name(" 在字符串中被误匹配"""
    # 移除 // 行尾注释
    line = re.sub(r'//.*$', '', line)
    # 移除 /* ... */ 块注释（单行）
    line = re.sub(r'/\*.*?\*/', '', line)
    # 移除 "字符串"
    line = re.sub(r'"[^"]*"', '""', line)
    # 移除 '字符'
    line = re.sub(r"'[^']*'", "''", line)
    return line
```

### 7.3 读/写区分

变量访问的读写区分是一个难点。简化策略：

```python
# 简化规则:
# 1. var = ...  → 写（排除 == 和 !=）
# 2. var++ / ++var / var-- / --var → 写
# 3. &var → 可疑写（指针传递，标记为 READS_VAR 但加 note）
# 4. 其他 → 读
# 5. func(var) → 读
# 6. func(&var) → 可疑读写（标记为 READS_VAR）

def classify_var_access(line: str, var_name: str) -> str:
    """返回 'read', 'write', 或 'unknown'"""
    clean = remove_strings_and_comments(line)
    
    # 写模式
    write_patterns = [
        rf'{var_name}\s*=[^=]',      # var = ...
        rf'{var_name}\+\+',           # var++
        rf'\+\+{var_name}',           # ++var
        rf'{var_name}\-\-',           # var--
        rf'\-\-{var_name}',           # --var
        rf'=>\s*{var_name}\s*=',      # struct->var = ...
        rf'\.\s*{var_name}\s*=',      # struct.var = ...
    ]
    for pat in write_patterns:
        if re.search(pat, clean):
            return 'write'
    
    return 'read'
```

### 7.4 已知局限

1. **宏调用无法识别** — `#define CALL_FCTB() FctaFctbUpdateStatus()` 这种宏展开后的调用不会被发现
2. **函数指针调用无法识别** — `func_ptr()` 无法追踪到实际函数
3. **内联汇编/特殊语法** — 不影响我们关注的代码区域
4. **头文件中的内联函数** — 只分析 .c 文件中的定义，.h 中的 inline 函数可能遗漏
5. **条件编译** — `#ifdef` 分支内的代码会被分析，不管编译时是否启用

这些局限不影响 90%+ 的核心逻辑追踪，剩余的可以通过 LLM 补全。

---

## 8. 与现有系统的兼容性

### 8.1 不破坏现有功能

- CodeGraph 是**增量添加**，不修改 `ai/code_learner.py` 的行为
- `memory/code_knowledge/` 目录保持不变
- orchestrator 和 Expert Panel 的现有流程不受影响

### 8.2 未来集成点

- **DataProbe**: VariableQueryPlanner 可以生成针对 codegraph.db 的 SQL 查询，获取变量依赖信息
- **Expert Panel**: Round 1 框架分析时，可以从 codegraph 获取精确的调用链，替代现在的 LLM 推测
- **CodeLearner**: 学习前先从 codegraph 获取相关函数的调用上下文，提高 snippets 质量

---

## 9. Handoff Checklist

### 下一步开发任务 (按优先级)

1. **[P0] 创建 `ai/codegraph_builder.py` 骨架**
   - SQLite schema 初始化
   - File Index + Function Extraction (Phase 1-2)
   - 增量 hash 机制

2. **[P0] 在 cli.py 中添加 `build-codegraph` 命令**
   - 支持 `--force` 全量重建
   - 输出构建统计

3. **[P1] 实现 Call Graph (Phase 3)**
   - 函数调用关系提取
   - 这是最有价值的关系类型

4. **[P1] 实现 Signal Interface (Phase 5)**
   - Rte_Read/Rte_Write/ReadSignal/WriteSignal
   - 与现有 signal_mapping.json 交叉验证

5. **[P2] 实现 Variable Access (Phase 4)**
   - 全局变量读写依赖

6. **[P2] 实现 Module Binding (Phase 7)**
   - 基于 FUNC_KEYWORDS 绑定
   - 与现有 code_knowledge 交叉验证

### 开发环境

- Python 3.11，使用 `py -3.11` 执行（`python` 命令指向 Windows Store 占位符）
- 工作目录: `D:\RamboStar\idea\radarAnalyze`
- 源码根目录: `D:\cr60_light` (config.yaml 中的 `paths.source_code`)
- 分支: `refactor/codegraph`

### 关键文件

| 文件 | 作用 |
|------|------|
| `ai/code_learner.py` | 现有 CodeLearner — 理解现有构建流程的参考 |
| `ai/codegraph_builder.py` | **新建** — CodeGraph 构建器 |
| `ai/codegraph_query.py` | **新建** — CodeGraph 查询 API |
| `cli.py` | 需要新增 codegraph 相关命令 |
| `memory/codegraph.db` | **新建** — SQLite 数据库（构建后生成） |
