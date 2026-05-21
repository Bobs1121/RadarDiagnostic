# CodeGraph 开发 Handoff

> 执行此文档中的任务，接续 codegraph 重构开发。
> 完整设计方案见 `docs/technical/codegraph-design.md`。

---

## 前置知识

### 环境

```bash
# Python 必须用 py -3.11，不要用 python（Windows Store 占位符，exit code 49）
py -3.11 --version  # Python 3.11.8

# 工作目录
cd /d/RamboStar/idea/radarAnalyze

# 源码根目录（被分析的目标）
D:\cr60_light

# 分支
git branch  # refactor/codegraph
```

### 项目结构

```
radarAnalyze/
├── ai/
│   ├── code_learner.py       # 现有 LLM 驱动的代码学习引擎（参考用）
│   ├── model_router.py       # AI 模型路由
│   ├── utils.py              # 工具函数，含 FUNC_KEYWORDS、ALL_FUNCTIONS 等
│   └── ...
├── cli.py                    # CLI 入口
├── config.yaml               # 配置文件
├── memory/
│   ├── code_knowledge/       # 现有 LLM 生成的知识 JSON（保持不变）
│   └── ...
└── docs/technical/
    └── codegraph-design.md   # 完整设计方案
```

### 关键常量（从 ai/utils.py 导入）

```python
FUNC_KEYWORDS = {
    "FCTB": ["fctb", "Fctb", "FCTB", "fctbSystemState", "FctbBrake", ...],
    "FCTA": ["fcta", "Fcta", "FCTA", "fctaSystemState", ...],
    # ... 共 8 个功能模块
}
ALL_FUNCTIONS = ["BSD", "LCA", "DOW", "RCW", "RCTA", "RCTB", "FCTA", "FCTB"]
```

这些在 `ai/code_learner.py` 的 FUNC_KEYWORDS 中定义，也可从 config.yaml 的 `functions` 段获取。

---

## 任务 1: 创建 codegraph_builder.py

**文件**: `ai/codegraph_builder.py`

### 1.1 SQLite Schema

```python
import sqlite3
import hashlib
from pathlib import Path

SCHEMA_VERSION = 1

INIT_SQL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS nodes (
    id          TEXT PRIMARY KEY,
    type        TEXT NOT NULL,
    name        TEXT NOT NULL,
    display_name TEXT,
    file_id     TEXT,
    start_line  INTEGER,
    end_line    INTEGER,
    return_type TEXT,
    params      TEXT,
    is_static   INTEGER DEFAULT 0,
    scope       TEXT,
    data_type   TEXT,
    defined_in  TEXT,
    line        INTEGER,
    direction   TEXT,
    can_name    TEXT,
    message_id  TEXT,
    rte_function TEXT,
    state_id    INTEGER,
    state_name  TEXT,
    keywords    TEXT,
    source_hash TEXT,
    created_at  TEXT DEFAULT (datetime('now')),
    updated_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS edges (
    id          TEXT PRIMARY KEY,
    source      TEXT NOT NULL,
    target      TEXT NOT NULL,
    type        TEXT NOT NULL,
    line        INTEGER,
    column      INTEGER,
    condition   TEXT,
    source_hash TEXT,
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS file_hashes (
    file_path   TEXT PRIMARY KEY,
    hash        TEXT NOT NULL,
    analyzed_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS build_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    build_time  TEXT DEFAULT (datetime('now')),
    files_added INTEGER DEFAULT 0,
    files_changed INTEGER DEFAULT 0,
    nodes_added INTEGER DEFAULT 0,
    edges_added INTEGER DEFAULT 0,
    summary     TEXT
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source);
CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target);
CREATE INDEX IF NOT EXISTS idx_edges_type ON edges(type);
CREATE INDEX IF NOT EXISTS idx_edges_source_type ON edges(source, type);
CREATE INDEX IF NOT EXISTS idx_edges_target_type ON edges(target, type);
CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes(type);
CREATE INDEX IF NOT EXISTS idx_nodes_name ON nodes(name);
CREATE INDEX IF NOT EXISTS idx_nodes_file ON nodes(file_id);
"""
```

### 1.2 CodeGraphBuilder 类骨架

```python
class CodeGraphBuilder:
    def __init__(self, source_root: Path, db_path: Path):
        self.source_root = source_root.resolve()
        self.db_path = db_path
        self.conn = None
        self.changed_files = []  # 本次需要重新分析的文件
        self.stats = {
            'files_scanned': 0,
            'files_changed': 0,
            'nodes_added': 0,
            'edges_added': 0,
        }
    
    def connect(self):
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._ensure_schema()
    
    def _ensure_schema(self):
        version = self._get_schema_version()
        if version != SCHEMA_VERSION:
            # 首次或需要迁移
            self.conn.executescript(INIT_SQL)
            self._set_schema_version(SCHEMA_VERSION)
    
    def build(self, key_files: list[str] = None, force: bool = False) -> dict:
        """
        主入口：构建/增量更新 CodeGraph。
        
        Args:
            key_files: 要分析的源文件列表（相对 source_root）。
                       如果为 None，使用 config.yaml 中的 key_source_files。
            force: 是否忽略 hash 缓存，全量重建。
        """
        self.connect()
        
        try:
            # Phase 1: File Index
            self._phase1_file_index(key_files, force)
            
            # 如果有变化的文件，继续分析
            if self.changed_files or force:
                if force:
                    # 全量重建：清除所有节点和边
                    self._clear_graph()
                    self.changed_files = [n[0] for n in self.conn.execute(
                        "SELECT file_path FROM file_hashes"
                    ).fetchall()]
                
                # Phase 2: Function Extraction
                self._phase2_functions()
                
                # Phase 3: Call Graph
                self._phase3_calls()
                
                # Phase 4: Variable Access
                self._phase4_variables()
                
                # Phase 5: Signal Interface
                self._phase5_signals()
            
            # 记录构建日志
            self._log_build()
            
            return dict(self.stats)
        finally:
            self.conn.close()
            self.conn = None
```

### 1.3 Phase 1: File Index

```python
def _phase1_file_index(self, key_files: list[str], force: bool):
    """扫描源文件，建立文件节点，检测变化"""
    if force:
        # 强制模式下所有已知文件都标记为变化
        existing = self.conn.execute(
            "SELECT file_path FROM file_hashes"
        ).fetchall()
        for (fp,) in existing:
            self.changed_files.append(fp)
    
    for rel_path in key_files:
        full_path = self.source_root / rel_path
        if not full_path.exists():
            continue
        
        self.stats['files_scanned'] += 1
        
        # 计算 hash
        content = full_path.read_text(encoding='utf-8', errors='replace')
        file_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
        
        # 检查是否变化
        prev = self.conn.execute(
            "SELECT hash FROM file_hashes WHERE file_path = ?",
            (rel_path,)
        ).fetchone()
        
        is_new = prev is None
        is_changed = prev is not None and prev[0] != file_hash
        
        if is_new or is_changed:
            self.changed_files.append(rel_path)
            self.stats['files_changed'] += 1
        
        # 更新 hash 记录
        self.conn.execute(
            """INSERT OR REPLACE INTO file_hashes (file_path, hash, analyzed_at)
               VALUES (?, ?, datetime('now'))""",
            (rel_path, file_hash)
        )
        
        # 创建文件节点
        node_id = f"FILE:{rel_path.replace('\\', '/').replace('/', '_')}"
        self.conn.execute(
            """INSERT OR IGNORE INTO nodes (id, type, name, defined_in)
               VALUES (?, 'FILE', ?, ?)""",
            (node_id, rel_path, rel_path)
        )
    
    self.conn.commit()
```

### 1.4 Phase 2: Function Extraction

这是最核心的部分。需要实现：

```python
def _phase2_functions(self):
    """从变化的文件提取函数定义"""
    import re
    
    # 函数定义正则：支持 static/inline 修饰符
    # 匹配: [static inline] return_type function_name(params) {
    func_def_pattern = re.compile(
        r'^(?:(?:static|inline|CONST)\s+)*'
        r'(?P<ret>\w+(?:_t)?(?:\s*(?:Const|Ref))?)\s+'
        r'(?P<name>\w+)\s*'
        r'\((?P<params>[^)]*)\)'
        r'\s*$'
    )
    
    for rel_path in self.changed_files:
        full_path = self.source_root / rel_path
        if not full_path.exists():
            continue
        
        content = full_path.read_text(encoding='utf-8', errors='replace')
        lines = content.splitlines()
        
        file_node_id = f"FILE:{rel_path.replace('\\', '/').replace('/', '_')}"
        
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            
            # 跳过预处理指令、注释、空行
            if not line or line.startswith('#') or line.startswith('//') or line.startswith('/*'):
                i += 1
                continue
            
            # 尝试匹配函数定义
            m = func_def_pattern.match(line)
            if m and '{' in lines[min(i + 1, len(lines) - 1)]:
                func_name = m.group('name')
                ret_type = m.group('ret').strip()
                params = m.group('params').strip()
                start_line = i + 1  # 1-indexed
                
                # 跳过非函数匹配（struct/enum/typedef/if/while/for/switch）
                if func_name in ('if', 'else', 'while', 'for', 'switch', 'do', 'return',
                                 'typedef', 'struct', 'enum', 'union'):
                    i += 1
                    continue
                
                # 找到函数体结束位置
                end_line = self._find_function_end(lines, i)
                
                # 创建节点
                node_id = f"FUNCTION:{func_name}"
                is_static = 1 if 'static' in line.lower() else 0
                
                self.conn.execute(
                    """INSERT OR REPLACE INTO nodes 
                       (id, type, name, file_id, start_line, end_line, 
                        return_type, params, is_static, updated_at)
                       VALUES (?, 'FUNCTION', ?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
                    (node_id, func_name, file_node_id, start_line, end_line,
                     ret_type, params, is_static)
                )
                
                self.stats['nodes_added'] += 1
                i = end_line + 1
                continue
            
            i += 1
    
    self.conn.commit()
```

### 1.5 辅助函数

```python
def _find_function_end(self, lines: list[str], start: int) -> int:
    """从函数定义行开始，找到函数体的结束 }"""
    depth = 0
    found_open = False
    for i in range(start, len(lines)):
        clean = self._strip_strings_and_comments(lines[i])
        for ch in clean:
            if ch == '{':
                depth += 1
                found_open = True
            elif ch == '}':
                depth -= 1
                if found_open and depth == 0:
                    return i + 1  # 1-indexed
    return len(lines)

def _strip_strings_and_comments(self, line: str) -> str:
    """移除字符串和注释中的假阳性字符"""
    import re
    line = re.sub(r'//.*$', '', line)
    line = re.sub(r'/\*.*?\*/', '', line)
    line = re.sub(r'"[^"]*"', '""', line)
    line = re.sub(r"'[^']*'", "''", line)
    return line

def _clear_graph(self):
    """全量重建时清除所有节点和边"""
    self.conn.execute("DELETE FROM edges")
    self.conn.execute("DELETE FROM nodes WHERE type != 'FILE'")
    # 保留 FILE 节点（它们在 phase 1 中重建）
    self.conn.execute("DELETE FROM nodes WHERE type = 'FILE'")
    self.conn.commit()

def _log_build(self):
    """记录构建日志"""
    self.conn.execute(
        """INSERT INTO build_log (files_added, files_changed, nodes_added, edges_added, summary)
           VALUES (?, ?, ?, ?, ?)""",
        (self.stats['files_scanned'], self.stats['files_changed'],
         self.stats['nodes_added'], self.stats['edges_added'],
         f"Build: {self.stats['files_changed']} changed, {self.stats['nodes_added']} nodes, {self.stats['edges_added']} edges")
    )
    self.conn.commit()
```

---

## 任务 2: CLI 集成

在 `cli.py` 中添加:

```python
# 新增子命令
parser.add_argument('command', choices=[..., 'build-codegraph', 'query-codegraph', 'codegraph-stats'])
parser.add_argument('--force', action='store_true', help='Force full rebuild')
parser.add_argument('--query', '-q', type=str, help='SQL query for codegraph')
```

```python
if args.command == 'build-codegraph':
    from ai.codegraph_builder import CodeGraphBuilder
    db_path = PROJECT_ROOT / 'memory' / 'codegraph.db'
    builder = CodeGraphBuilder(
        source_root=Path(config['paths']['source_code']),
        db_path=db_path,
    )
    result = builder.build(
        key_files=config.get('paths', {}).get('key_source_files', []),
        force=args.force,
    )
    print(json.dumps(result, indent=2))

elif args.command == 'codegraph-stats':
    # 连接 DB 并输出统计
    ...

elif args.command == 'query-codegraph':
    # 执行用户 SQL 查询
    ...
```

---

## 任务 3: Phase 3-5 实现

Phase 3 (Call Graph), Phase 4 (Variable Access), Phase 5 (Signal Interface) 的详细实现在设计文档中有正则模式和算法描述。核心思路：

1. 对每个已提取的函数体，逐行扫描
2. 用正则匹配函数调用、变量访问、信号接口
3. 建立对应的边

---

## 验证方法

### 验证 1: 基本统计

```bash
py -3.11 cli.py build-codegraph
py -3.11 cli.py codegraph-stats
# 预期: 扫描 14 个文件，提取数百个函数
```

### 验证 2: 手动验证关键函数

```sql
-- FctaFctbUpdateStatus 应该存在
SELECT * FROM nodes WHERE name = 'FctaFctbUpdateStatus';

-- 它应该在 adasFunc.c 中
SELECT n.*, f.name as file_name 
FROM nodes n 
JOIN nodes f ON n.file_id = f.id 
WHERE n.name = 'FctaFctbUpdateStatus';
```

### 验证 3: 调用链验证

```sql
-- 谁调用了 FctaFctbUpdateStatus?
SELECT n.name, n.start_line
FROM edges e
JOIN nodes n ON e.source = n.id
WHERE e.type = 'CALLS' 
  AND e.target = 'FUNCTION:FctaFctbUpdateStatus';
```

### 验证 4: 与 code_knowledge 交叉验证

```python
# code_knowledge 中记录的 code_ref 应该能在 codegraph 中找到对应函数
import json
fctb = json.load(open('memory/code_knowledge/FCTB.json'))
for trig in fctb['alarm_logic']['trigger_conditions']:
    ref = trig['code_ref']
    # 检查 codegraph 中是否存在该文件 + 行号范围内的函数
```

---

## 注意事项

1. **Windows 路径** — 源码路径含反斜杠，存储和比较时需统一处理（建议统一为正斜杠）
2. **大文件处理** — `adasFunc.c` 可能超过 80000 字符，逐行处理不要一次全量加载
3. **编码** — 使用 `utf-8` + `errors='replace'` 读取源码
4. **括号匹配** — 多行宏定义可能导致 `{` `}` 计数错误，加日志记录无法匹配的函数
5. **增量构建** — 第一个版本可以先只做全量构建，增量在第二轮优化
