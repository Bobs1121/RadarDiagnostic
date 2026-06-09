# radarAnalyze — 改造实施规划 v2.1

> 版本: 2.1.0
> 日期: 2026-06-09
> 分支: `refactor/v2`
> 关联 PRD: `docs/PRD_refactor_v2.md` (v2.1.0)

---

## 总览

**目标**: 将 radarAnalyze 从 v1 (手写管线 + 正则代码分析) 升级到 v2.1 (多项目支持 + tree-sitter 代码分析 + LangGraph 专家面板 + CodeFixEngine)。

**改造顺序**: 基础优先 — 先打牢可配置化 + 变量过滤 + 语义层，再优化管线效率。

**原则**:
- 渐进式替换，不做全量重写
- 每个 Phase 完成后都能独立验证
- 所有改动在 `refactor/v2` 分支，master 不动
- 配置驱动，代码不变 — 新增项目只需改 config.yaml

---

## Phase 1-4: 已完成状态

| Phase | 状态 | 说明 |
|-------|------|------|
| **P1: 基础层** | ✅ 完成 | MF4 stub (Deferred), topic 自动发现, 降级策略, StepLogger |
| **P2: 代码分析** | ✅ 完成 | tree-sitter AST 解析 + builder, CodeGraph SQLite (1381 节点, 9897 边) |
| **P3: 专家面板** | ✅ 完成 | LangGraph 5 专家 × 3 轮, prompt 外部化到 `prompts/expert_panel/*.md` |
| **P4: CodeFixEngine** | ✅ 完成 | diff 生成 + 安全审查 + 效果预估, qwen3-coder:30b |

---

## Phase 5A: 多项目可配置化 (P0 — 3 天)

### 5A.1: config.yaml 重构为 projects 配置 (1 天)

**目标**: 支持 `-P <project_key>` 切换项目，config.yaml 改为 projects 分层。

```
修改文件:
  config.yaml           — 新增 projects.* 结构，保留全局配置
  cli.py                — 新增 -P/--project 参数，项目配置解析
  ai/orchestrator.py    — 构造函数接收 project_key，传入各子模块
```

**config.yaml 新结构**:

```yaml
# 全局配置（所有项目共享）
default_project: "sc6h"

ai:
  local: ...
  remote: ...
  coder: ...
  thinking: "full"
  variable_probe: ...

functions:
  rear:  [BSD, LCA, DOW, RCW, RCTA, RCTB]
  front: [FCTA, FCTB]

auto_dream: ...

# 项目配置（按项目隔离）
projects:
  sc6h:
    display_name: "BYD-SC6H-cr60light (6代角雷达)"
    source_code: "D:\\BYD-SC6H-cr60light\\cr60_light"
    dbc_files:
      - "CR_DBC_V3.2_20260331.dbc"
    key_source_files:
      - "coem\\GWM_B26\\components\\AswPerception\\func\\adasFunc.c"
      - "coem\\GWM_B26\\components\\AswPerception\\func\\adasFunc.h"
      - "coem\\GWM_B26\\components\\AswIf\\ASW_IN\\ASWIN_SystemState.c"
      - "coem\\GWM_B26\\components\\AswIf\\ASW_IN\\ASWIN_SystemState.h"
      - "coem\\GWM_B26\\components\\AswIf\\ASW_IN\\RteComMapping.c"
      - "coem\\GWM_B26\\components\\AswIf\\ASW_IN\\RteComMapping.h"
      - "coem\\GWM_B26\\components\\AswIf\\ASW_OUT\\ASWOUT_OutCalc.c"
      - "coem\\GWM_B26\\components\\AswIfSchedule\\AswIfSchedule.c"
      - "adas\\symmetry\\perception\\src\\objAttribCal.c"
      - "adas\\symmetry\\perception\\src\\track.c"
      - "adas\\symmetry\\perception\\src\\postProcess.c"
      - "adas\\symmetry\\perception\\include\\perception_public_def.h"
      - "adas\\symmetry\\perception\\include\\structDefine.h"
      - "adas\\symmetry\\perception\\include\\paraDefine.h"
      - "adas\\symmetry\\perception\\include\\globalVarDefine.h"
      - "coem\\GWM_B26\\components\\com\\AutoGen\\PriCan\\rteLite_PriCan.h"
    source_domains:
      system_state:
        - "coem\\GWM_B26\\components\\AswIf\\ASW_IN\\ASWIN_SystemState.c"
        - "coem\\GWM_B26\\components\\AswIf\\ASW_IN\\ASWIN_SystemState.h"
      algorithm:
        - "coem\\GWM_B26\\components\\AswPerception\\func\\adasFunc.c"
        - "coem\\GWM_B26\\components\\AswPerception\\func\\adasFunc.h"
        - "adas\\symmetry\\perception\\include\\paraDefine.h"
      signal_chain:
        - "coem\\GWM_B26\\components\\AswIf\\ASW_IN\\RteComMapping.c"
      perception:
        - "adas\\symmetry\\perception\\src\\objAttribCal.c"
        - "adas\\symmetry\\perception\\src\\track.c"
        - "adas\\symmetry\\perception\\src\\postProcess.c"
      output:
        - "coem\\GWM_B26\\components\\AswIf\\ASW_OUT\\ASWOUT_OutCalc.c"

  cr5cb:
    display_name: "BYD_OVS_CB (5代角雷达)"
    source_code: "C:\\BYD_OVS_CB"
    dbc_files:
      - "PLACEHOLDER.dbc"
    key_source_files:
      - "PLACEHOLDER.c"
    source_domains:
      PLACEHOLDER:
        - "PLACEHOLDER.c"
```

**CLI 新增参数**:

```python
parser.add_argument(
    "--project", "-P",
    default=None,
    help="Project key (e.g., 'sc6h', 'cr5cb'). Default from config.yaml."
)
```

**配置解析流程**:

```python
def load_config(project_key: str = None) -> dict:
    """Load config, merge global + project-specific settings."""
    cfg = yaml.safe_load(config_yaml)
    cfg = _resolve_env(cfg)

    # 确定项目 key
    if project_key is None:
        project_key = cfg.get("default_project", "sc6h")

    # 获取项目配置
    project_cfg = cfg["projects"].get(project_key)
    if project_cfg is None:
        raise ValueError(f"Project '{project_key}' not found in config.yaml")

    # 合并: project_cfg 覆盖全局 paths
    merged = dict(cfg)
    merged["project"] = project_key
    merged["paths"] = {
        "project_root": str(PROJECT_ROOT),
        "source_code": project_cfg["source_code"],
        "dbc_files": project_cfg["dbc_files"],
        "cases_dir": cfg.get("paths", {}).get("cases_dir", "./cases"),
        "source_docs": str(PROJECT_ROOT / "source_docs" / project_key),
        "key_source_files": project_cfg.get("key_source_files", []),
    }
    merged["source_domains"] = project_cfg.get("source_domains", {})

    return merged
```

**验收标准**:
- `python cli.py cases/FCTA001 -P sc6h` 加载 sc6h 项目配置
- `python cli.py cases/FCTA001 -P cr5cb` 加载 cr5cb 项目配置
- 省略 `-P` 时使用 `default_project`
- 不存在的项目 key 报清晰错误

### 5A.2: CodeGraph DB 按项目隔离 (0.5 天)

**目标**: 每个项目使用独立的 CodeGraph SQLite 数据库。

```
修改文件:
  ai/codegraph/__init__.py — db_path 加入 project_key
  ai/orchestrator.py       — 传入 project_key
```

**路径规则**:

```python
def codegraph_db_path(project_root: Path, project_key: str) -> Path:
    return project_root / "memory" / f"codegraph_{project_key}.db"
```

**变更点**:
1. `Orchestrator.__init__` 保存 `self.project_key`
2. CodeGraph 初始化时使用 `codegraph_db_path(project_root, project_key)`
3. CodeGraph 构建时增量更新只针对当前项目的 DB
4. `cli.py` 的 `--codegraph-stats` 命令支持 `-P` 参数

**验收标准**:
- `memory/codegraph_sc6h.db` 和 `memory/codegraph_cr5cb.db` 各自独立
- 切换项目不影响另一个项目的 CodeGraph

### 5A.3: source_docs 按项目隔离 (0.5 天)

**目标**: 每个项目的 source_docs 独立存放。

```
路径规则:
  source_docs/sc6h/overview.md
  source_docs/sc6h/modules/...
  source_docs/cr5cb/overview.md
  source_docs/cr5cb/modules/...
```

**变更点**:
1. `config.yaml` 中 `paths.source_docs` 包含 `{project}` 后缀
2. `CodeLearner.ensure_overview_docs()` 使用项目隔离路径
3. `cli.py` 启动时自动创建项目级 source_docs 目录

### 5A.4: 记忆系统按项目隔离 (0.5 天)

**目标**: 项目级知识隔离。

```
路径规则:
  memory/projects/sc6h/
    project.md
    knowledge/
      FCTA.json
      FCTB.json
      patterns.json
  memory/projects/cr5cb/
    project.md
    knowledge/
      ...
```

**变更点**:
1. `MemorySystem.__init__` 接收 `project_key`
2. L1 (project.md), L2 (functions/*.json), L3 (patterns.json), L6 (code_knowledge/) 路径加入 `{project}/` 前缀
3. L4 (sessions/) 暂不隔离（全局共享便于调试）
4. `_update_memories` 写入时按项目隔离
5. `_understand_problem` 读取时只读取当前项目的记忆

**API 兼容**: 外部调用不变，`MemorySystem` 内部处理路径拼接。

### 5A.5: SIGNAL 节点扩展 — 数据-变量映射字段 (0.5 天)

**目标**: CodeGraph SIGNAL 节点存储完整链路信息。

```
修改文件:
  ai/codegraph/schema.py    — SIGNAL 节点增加字段
  ai/codegraph/builder.py   — 构建 SIGNAL 时填充链路信息
  ai/codegraph/ast_builder.py — 从 RteComMapping AST 提取完整映射
```

**SIGNAL 节点扩展字段**:

```python
class SignalNode:
    name: str                    # 信号名
    can_signal_name: str | None  # BLF/DBC 中的信号名
    dbc_message: str | None      # DBC Message
    can_id: int | None           # CAN ID
    rte_mapping_file: str | None # RteComMapping.c 路径
    rte_mapping_line: int | None # 宏调用行号
    internal_var_name: str | None # 映射的内部变量名
    direction: str               # READ / WRITE
    platform: str                # 项目代号
    file_path: str               # 所在文件
    line: int                    # 行号
```

**构建流程**:
1. 从 DBC 文件读取 signal → message → can_id 映射
2. 从 RteComMapping AST 提取 ReadSignal/WriteSignal 宏调用
3. 匹配 DBC signal name 和 C 变量名
4. 写入 SIGNAL 节点，填充所有链路字段

**验收标准**: SIGNAL 节点可查询完整链路：CAN signal → DBC → RteComMapping → C 变量。

### 5A.6: E2E 验证 — 两个项目各跑一次 (0.5 天)

**测试步骤**:
1. 配置 `cr5cb` 项目的 key_source_files 和 source_domains（占位）
2. `python cli.py cases/FCTA001 -P sc6h -q "FCTA 当前状态"` — 验证 sc6h 项目
3. `python cli.py cases/FCTA001 -P cr5cb -q "FCTA 当前状态"` — 验证 cr5cb 项目
4. 确认两个项目使用不同的 CodeGraph DB 和 source_docs 目录

---

## Phase 5B: 变量过滤 (P1 — 2 天)

### 5B.1: ast_parser.py 增加变量过滤规则 (1 天)

**目标**: CodeGraph 变量节点只保留对诊断有意义的变量。

```
修改文件:
  ai/codegraph/ast_parser.py — extract_variables / extract_var_writes 增加过滤
```

**过滤逻辑**:

```python
def _should_include_variable(node, context) -> bool:
    """Decide whether to include a variable in CodeGraph."""
    name = node.text.decode("utf-8")

    # 1. 过滤短名局部变量 (i, j, k, x, y, tmp, idx, cnt 等)
    if len(name) <= 3 and context == "local":
        return False

    # 2. 保留全局变量 (file_scope + non-static)
    if context == "global":
        return True

    # 3. 保留静态全局变量 (static at file scope)
    if context == "file_static":
        return True

    # 4. 保留 RTE 变量 (Rte_* 前缀)
    if name.startswith("Rte_"):
        return True

    # 5. 保留枚举/状态变量 (*State*, *Mode*)
    if any(kw in name for kw in ["State", "Mode", "Status", "Flag"]):
        return True

    # 6. 保留校准参数 (Calib_ 前缀)
    if name.startswith("Calib_"):
        return True

    # 7. 默认过滤局部变量
    if context == "local":
        return False

    return True
```

**上下文判定**:
- `global`: 文件作用域，无 static 修饰
- `file_static`: 文件作用域，有 static 修饰
- `local`: 函数内部声明
- `parameter`: 函数参数（直接过滤）

### 5B.2: 过滤规则可配置 (0.5 天)

```yaml
# config.yaml 全局配置
variable_filter:
  exclude_patterns: ["^i$", "^j$", "^k$", "^tmp", "^idx$", "^cnt$", "^p_"]
  include_patterns: ["^Rte_", ".*State.*", ".*Mode.*", ".*Flag.*", "^Calib_"]
  min_name_length: 4       # 局部变量最短名称
  exclude_local: true      # 默认过滤局部变量
```

### 5B.3: CodeGraph 重建 + 验证 (0.5 天)

1. 清空现有 CodeGraph DB
2. 使用新过滤规则重建
3. 验证变量数 <200
4. 抽样检查保留变量是否为诊断相关

---

## Phase 5C: CodeGraph 语义层填充 (P1 — 3 天)

### 5C.1: 设计 semantic_annotations 表结构 (0.5 天)

```sql
CREATE TABLE semantic_annotations (
  id INTEGER PRIMARY KEY,
  node_type TEXT NOT NULL CHECK (node_type IN ('FUNCTION', 'VARIABLE', 'SIGNAL', 'STATE_MACHINE', 'PATTERN')),
  node_id INTEGER NOT NULL,    -- 引用 functions/variables/signals 表的 id
  description TEXT,             -- 功能/语义描述
  input_desc TEXT,              -- 输入说明 (FUNCTION)
  output_desc TEXT,             -- 输出说明 (FUNCTION)
  physical_meaning TEXT,        -- 物理含义 (SIGNAL)
  value_range TEXT,             -- 取值范围 (SIGNAL/VARIABLE)
  state_transitions TEXT,       -- 状态转换描述 (STATE_MACHINE)
  behavior_desc TEXT,           -- 行为模式描述 (PATTERN)
  confidence REAL,              -- LLM 标注置信度
  platform TEXT,                -- 项目代号
  source_hash TEXT,             -- 源码 hash，用于增量更新
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 5C.2: 实现 LLM 语义标注 pipeline (1.5 天)

```
新增文件:
  ai/codegraph/semantic_annotator.py — LLM 语义标注引擎
```

**标注流程**:

```python
class SemanticAnnotator:
    def annotate_file(self, file_path: Path, codegraph: CodeGraph) -> list[Annotation]:
        """对单个源文件进行语义标注."""
        # 1. 读取 AST 结构 + 源码片段
        ast_data = self._extract_ast_context(file_path, codegraph)
        source_snippet = file_path.read_text(encoding="utf-8", errors="replace")

        # 2. 构建 prompt — 请求 LLM 标注
        prompt = f"""
        请为以下 C 代码的关键元素提供语义标注：
        {ast_data}
        {source_snippet[:40000]}

        请标注以下内容：
        1. 每个函数: 功能描述、输入输出
        2. 每个全局/静态变量: 语义角色、取值范围
        3. 每个信号: 物理含义、映射关系
        4. 状态机: 状态转换语义
        """

        # 3. LLM 调用
        response = self.router.complex(prompt, system=SYSTEM_SEMANTIC_ANNOTATION)

        # 4. 解析 JSON 响应
        annotations = self._parse_annotations(response)

        # 5. 写入 semantic_annotations 表
        self._save_annotations(codegraph, annotations)

        return annotations
```

**标注时机**:
- AutoDream Phase 0: 首次构建 CodeGraph 后自动触发
- `--reannotate` CLI 参数: 手动触发重新标注
- 源码 hash 变化时: 增量标注变更部分

### 5C.3: 缓存 + hash 校验机制 (0.5 天)

```python
def should_reannotate(file_path: Path, codegraph: CodeGraph) -> bool:
    """检查是否需要重新标注."""
    current_hash = sha256(file_path.read_bytes()).hexdigest()
    cached_hash = codegraph.get_annotation_hash(file_path.name)
    return current_hash != cached_hash
```

### 5C.4: 专家面板注入语义标注 (0.5 天)

```
修改文件:
  ai/orchestrator.py — ContextBudget 组装区注入语义标注
  ai/codegraph/render.py — 新增 render_semantic_annotations()
```

**注入方式**:
1. CodeGraphRenderer 新增 `render_semantic_annotations()` 方法
2. ContextBudget 新增 semantic section，priority=75（仅次于 conditions）
3. 专家面板 prompt 中显示关键函数的语义描述

### 5C.5: 核心文件首次标注 + 质量检查 (0.5 天)

1. 对 adasFunc.c、ASWIN_SystemState.c、RteComMapping.c 运行首次标注
2. 人工抽样检查标注质量
3. 标注置信度 <0.7 的标记为 "需人工审核"

---

## Phase 5D: 管线精简 — 15→8 步 (P2 — 2 天)

### 5D.1: orchestrator.py 重构为 8 步 (1 天)

**目标**: 合并步骤，降低出错面和调试复杂度。

```
修改文件:
  ai/orchestrator.py — 重构 run_diagnosis
```

**新管线结构**:

```python
def run_diagnosis(self, case_dir, problem, expected, on_status=None):
    """Simplified 8-step diagnosis pipeline."""

    # Step 1: init — 项目配置 + source_docs + CodeGraph
    self._step_init(case_dir, on_status)

    # Step 2: classify — 问题理解 + 分类 (1 LLM)
    classification = self._step_classify(problem, expected, on_status)

    # Step 3: extract — 数据解析 + 窗口检测 (确定性)
    extraction = self._step_extract(case_dir, classification, on_status)

    # Step 4: evidence — 条件提取(LLM) + TPE(确定性) + 变量探测(LLM) — 并行
    evidence = self._step_evidence(extraction, classification, on_status)

    # Step 5: signals — 抑制信号 + 输出信号 (确定性)
    signals = self._step_signals(extraction, classification, on_status)

    # Step 6: diagnose — LangGraph 专家面板 (多 LLM)
    diagnosis = self._step_diagnose(evidence, signals, classification, on_status)

    # Step 7: fix — CodeFixEngine 生成 diff (1 LLM)
    fix = self._step_fix(diagnosis, on_status)

    # Step 8: deliver — 报告 + 可视化 + 记忆更新 (确定性)
    return self._step_deliver(case_dir, diagnosis, fix, classification, on_status)
```

**关键合并逻辑**:

1. **classify**: 合并 `_understand_problem` + `problem_classifier.classify`
   - 一次 LLM 调用同时完成理解 + 分类
   - prompt 合并两个步骤的 prompt

2. **extract**: 合并 `parse_case_data` + `detect_windows`
   - 都是确定性步骤，无 LLM
   - 数据解析完成后立即检测窗口

3. **evidence**: conditions + TPE + probe
   - conditions (LLM) 和 TPE (确定性) 并行
   - probe 依赖两者完成后执行
   - 使用 `ThreadPoolExecutor` 并行

4. **signals**: 合并 `_check_suppression_signals` + `_analyze_output_signals`
   - 都是 CAN 信号查询，合并为统一的 signals 分析

5. **deliver**: 合并 `visualize` + `memory_update` + `done`
   - 报告生成 → 可视化 → 记忆写入 → 完成

### 5D.2: evidence 步骤并行化 (0.5 天)

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

def _step_evidence(self, extraction, classification, on_status):
    """Gather evidence: conditions (LLM) + TPE (deterministic) + probe (LLM)."""

    results = {}

    # 第一阶段: conditions + TPE 并行
    with ThreadPoolExecutor(max_workers=2) as executor:
        conditions_future = executor.submit(self._extract_conditions, extraction, classification)
        tpe_future = executor.submit(self._run_tpe, extraction)

        results["conditions"] = conditions_future.result()
        results["tpe"] = tpe_future.result()

    # 第二阶段: probe 依赖前两者
    if classification.task_type in ("diagnose", "tune", "verify"):
        results["probe"] = self._run_probe(extraction, results["conditions"], results["tpe"])

    return results
```

### 5D.3: 回归测试 (0.5 天)

**测试方案**:
1. 使用 FCTA001 案例运行重构后的管线
2. 对比重构前后的诊断结论（根因、置信度、修复建议应一致）
3. 验证并行执行不影响结果正确性
4. 验证 `-P sc6h` 和 `-P cr5cb` 两个项目均正常工作

---

## Phase 5E: 优化项 (P2-3 — 2 天)

### 5E.1: ContextBudget 动态总预算 (0.5 天)

```
修改文件:
  ai/context_budget.py — 新增 dynamic_budget() 方法
```

**实现**:

```python
class ContextBudget:
    def __init__(self, codegraph_size=0, case_complexity="normal"):
        self.total_chars = self._dynamic_budget(codegraph_size, case_complexity)
        self.remaining = self.total_chars
        # ... existing sections ...

    @staticmethod
    def _dynamic_budget(codegraph_size: int, case_complexity: str) -> int:
        base = 50_000
        cg_bonus = min(codegraph_size // 100, 20_000)
        complexity_mult = {"simple": 0.8, "normal": 1.0, "complex": 1.3}[case_complexity]
        return int((base + cg_bonus) * complexity_mult)
```

**调用点**: `orchestrator.py` 创建 ContextBudget 时传入 CodeGraph 大小。

### 5E.2: 记忆系统简化 6→3 层 (1 天)

```
修改文件:
  memory/memory_system.py — 精简层级，保持 API 兼容
```

**目录结构变化**:

```
Before:
  memory/
    project.md                    # L1
    functions/*.json              # L2
    patterns.json                 # L3
    sessions/*.json               # L4
    cases/*/memory.json           # L5
    code_knowledge/*.json         # L6

After:
  memory/
    projects/{project}/
      project.md                  # L1 — 项目级
      knowledge/
        patterns.json             # L3 → 统一知识库
        code/*.json               # L6 → 代码知识
        {FUNC}.json               # L2 → 功能知识
    sessions/                     # L4 — 最近 20 条（全局共享）
```

**变更**:
1. L5 (case memory) 合并到 L3 (patterns.json)
2. 所有项目级知识移到 `projects/{project}/` 下
3. L4 (sessions) 加 TTL 机制，只保留最近 20 条
4. API 兼容: `write_case_memory()` 内部转发到 patterns

### 5E.3: 端到端回归测试 (0.5 天)

**完整测试矩阵**:

| 项目 | 案例 | 模式 | 验证项 |
|------|------|------|--------|
| sc6h | FCTA001 | diagnose | 诊断结论正确 |
| sc6h | FCTA001 | query | 数据查询正确 |
| cr5cb | FCTA001 | diagnose | 使用 cr5cb 配置 |
| cr5cb | FCTA001 | query | 使用 cr5cb 配置 |

---

## Deferred: 待改造项

| 项 | 说明 | 触发条件 |
|---|------|---------|
| MF4 Parser | asammdf 依赖不可用，已有 stub | 内网安装 asammdf 或 mffparser |
| 多平台 CodeGraph 合并查询 | 跨平台对比分析 | 用户明确提出需求 |
| Web UI | 前端可视化 | 产品方向调整 |
| 视频辅助诊断 | 同步分析录像 | 用户需求确认 |

---

## 时间线

```
Week 1:  Phase 5A (多项目可配置化)     — config 重构 + 项目隔离 + SIGNAL 扩展 — 3 天
Week 2:  Phase 5B (变量过滤) + 5C (语义层) — 变量过滤 2 天 + 语义层 3 天 — 5 天
Week 3:  Phase 5D (管线精简) + 5E (优化项) — 管线精简 2 天 + 优化 2 天 — 4 天
```

**Phase 5 总工期: 12 天**

---

## 每次会话工作流

```
1. 读 handoff master → 了解当前状态
2. 读 PRD_refactor_v2.md → 了解改造目标 (v2.1)
3. 读 IMPLEMENTATION_PLAN_v2.md → 了解实施步骤
4. 执行一个 Phase 内的若干任务
5. 完成后更新 handoff + Git 提交
6. 更新本文件 (完成的任务标记为 done)
```
