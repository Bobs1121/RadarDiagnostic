# radarAnalyze — 改造实施规划 v2.0

> 版本: 2.0.0
> 日期: 2026-06-08
> 分支: `refactor/v2`
> 关联 PRD: `docs/PRD_refactor_v2.md`

---

## 总览

**目标**: 将 radarAnalyze 从 v1 (手写管线 + 正则代码分析) 升级到 v2 (tree-sitter 代码分析 + LangGraph 专家面板 + CodeFixEngine)。

**原则**:
- 渐进式替换，不做全量重写
- 每个 Phase 完成后都能独立验证
- 所有改动在 `refactor/v2` 分支，master 不动

---

## Phase 1: 基础层加固 (5 天)

### P1.1: MF4 Parser (2 天)

**目标**: 新增 MF4 文件解析能力，写入 FrameStore。

```
新增文件:
  parsers/mf4_parser.py    — MF4 解析核心
  parsers/mf4_schema.py    — MF4 信号 schema 定义

修改文件:
  parsers/case_loader.py   — load_case_data 增加 mf4_files 参数
  cli.py                   — case 文件扫描增加 *.mf4
```

**关键实现**:
```python
# parsers/mf4_parser.py
class Mf4Parser:
    def parse(self, mf4_path: Path, store: FrameStore) -> Mf4Meta:
        """Parse MF4 file and write to FrameStore."""
        import mffparser
        mff = mffparser.load(mf4_path)
        # Extract channels, align timestamps, write to can_frames table
        # Signal names map to DBC signals when possible
```

**验收**: `python cli.py cases/MF4_TEST -q "测试 MF4 数据"` 返回数据。

### P1.2: BAG topic 自动发现 (1 天)

**目标**: 不再硬编码 topic 路径。

```
修改文件:
  parsers/bag_parser.py — _discover_topics() 替代硬编码
```

**实现思路**:
```python
def _discover_topics(bag):
    """Auto-discover radar-related topics from bag."""
    radar_keywords = ["wf", "radar", "corner", "object", "target"]
    return [t for t in bag.topics if any(k in t.lower() for k in radar_keywords)]
```

**验收**: 不修改代码可识别新车型的 bag topic。

### P1.3: 异常降级策略 (1 天)

**目标**: 所有 LLM 步骤有明确的 fallback。

```
修改文件:
  ai/model_router.py      — add try_catch wrapper with fallback
  ai/orchestrator.py      — each LLM step wrapped with fallback
  ai/utils.py             — new: fallback_diagnose(), fallback_classify()
```

**降级表**:

| 步骤 | Fallback |
|------|----------|
| classify | 默认 `diagnose` + 全 5 专家 |
| conditions | 使用缓存的 `{FUNC}_conditions.json` |
| probe | 跳过，`probe_results = {}` |
| expert_panel | 单专家直接输出 (无辩论) |
| codefix | 返回文字修复建议 |

### P1.4: 可观测性层 (1 天)

**目标**: 每步记录输入/输出/耗时/token。

```
新增文件:
  ai/observability.py — StepLogger, TokenTracker

修改文件:
  ai/orchestrator.py — wrap each step with logger
```

```python
class StepLogger:
    def __init__(self, session_id: str):
        self.log = []

    def start(self, step: str, input_summary: str):
        self.log.append({"step": step, "input": input_summary, "started_at": time.time()})

    def end(self, output_summary: str, tokens: int = 0):
        last = self.log[-1]
        last["output"] = output_summary
        last["tokens"] = tokens
        last["duration"] = time.time() - last["started_at"]

    def save(self, path: Path):
        path.write_text(json.dumps(self.log, indent=2))
```

---

## Phase 2: 代码分析升级 — Tree-sitter (10 天)

### P2.1: tree-sitter 集成 (2 天)

**目标**: C 文件可解析为 AST。

```
新增文件:
  ai/codegraph/ast_parser.py — tree-sitter wrapper

安装:
  pip install tree-sitter tree-sitter-c
```

```python
# ai/codegraph/ast_parser.py
import tree_sitter_c as ts_c
from tree_sitter import Parser

class CParser:
    def __init__(self):
        self.parser = Parser(ts_c.language())

    def parse_file(self, path: Path) -> tuple:
        """Return (tree, source_code)."""
        source = path.read_bytes()
        tree = self.parser.parse(source)
        return tree, source.decode("utf-8", errors="replace")

    def walk_nodes(self, tree, node_type=None):
        """Yield (node_type, node_text, row, col, path_from_root)."""
        cursor = tree.walk()
        # DFS traversal, yield matching nodes
```

**验收**: `python -c "from ai.codegraph.ast_parser import CParser; p=CParser(); print(p.parse_file(Path('adas/symmetry/perception/src/track.c'))[0])"` 输出 AST。

### P2.2: AST → CodeGraph 构建器 (3 天)

**目标**: 从 AST 提取函数/变量/信号/关系边，写入 SQLite。

```
新增文件:
  ai/codegraph/ast_builder.py — AST traversal → CodeGraph nodes/edges

修改文件:
  ai/codegraph/builder.py   — 重构，树替代正则
  ai/codegraph/schema.py    — 新增 AST-derived 节点类型
```

**提取内容**:
```
函数节点:
  - 从 function_definition 节点提取
  - 记录签名、参数、返回值、行号
  - 记录文件归属

变量节点:
  - 从 typedef + struct + global declaration 提取
  - 区分全局/静态/局部
  - 只保留有意义的（过滤 i, j, tmp 等）

信号节点:
  - 从 RteComMapping 宏调用提取 (替代正则)
  - ReadSignal/WriteSignal 宏的参数提取

关系边:
  - CALLS: 函数调用 (call_expression → function ref)
  - READS/WRITES: 变量读写 (identifier in expression statement)
  - READS_SIGNAL/WRITES_SIGNAL: 信号映射 (从 RteComMapping AST)
  - DEFINES: 文件包含函数/变量
```

**验收**: CodeGraph 节点数 ~1381, 边数 >10000 (比 v1 更完整)。

### P2.3: 行为模式提取 (2 天)

**目标**: AST 级别识别 HoldRelease/Accumulate/Hysteresis 等模式。

```
新增文件:
  ai/codegraph/pattern_extractor_ast.py

替代文件:
  ai/pattern_extractor.py — 迁移到 AST 版本
```

**模式提取规则 (AST)**:
```
HoldRelease:
  - 变量 A 在条件 X 下赋值 1
  - 变量 A 在条件 Y 下赋值 0
  - 变量 A 在赋值之间保持原值 (无中间修改)

Accumulate:
  - 变量 A 在条件 X 下递增/递减
  - 变量 A 在条件 Y 下重置
  - 变量 A 与阈值比较触发事件

Hysteresis:
  - 变量 A > THRESH_UP 时触发 ON
  - 变量 A < THRESH_DOWN 时触发 OFF
  - THRESH_UP > THRESH_DOWN (滞回区间)

Debounce:
  - 计数器在条件满足时递增
  - 计数器在条件不满足时重置
  - 计数器超过阈值触发事件
```

**验收**: 提取的模式数量和类型 >= 现有正则版本。

### P2.4: 状态机提取 (2 天)

**目标**: 从 switch-case/goto 提取状态机定义。

```
新增文件:
  ai/codegraph/state_machine_extractor.py
```

**提取逻辑**:
```python
# From AST: find switch statements on state variable
# For each case: extract guard condition + next state
# Build: state -> [(condition, next_state), ...]

def extract_state_machine(func_node, state_var_name):
    """Extract FSM from switch-case or if-elif chain."""
    states = {}
    for case in func_node.children:
        if case.type == "case_statement":
            current_state = case.child[0].text.decode()
            # Extract transition conditions and next state assignments
            ...
    return states
```

**验收**: 可提取 `ASWIN_SystemState.c` 和 `adasFunc.c` 中的状态机。

### P2.5: CodeGraph 增量更新 (1 天)

**目标**: 只在源文件变化时重新构建。

```
修改文件:
  ai/codegraph/builder.py — 增加 mtime + content hash 缓存
```

```python
def build_incremental(source_root, db_path):
    """Only rebuild changed files."""
    file_hashes = load_cached_hashes(db_path)
    for f in source_files:
        current_hash = sha256(f.read_bytes())
        if current_hash != file_hashes.get(f.name):
            rebuild_file(f, db_path)
    save_cached_hashes(db_path, file_hashes)
```

---

## Phase 3: 专家面板重构 — LangGraph (5 天)

### P3.1: LangGraph 状态图定义 (1 天)

**目标**: 定义 DiagnosisState + 图结构。

```
新增文件:
  ai/expert_panel_langgraph.py

依赖:
  pip install langgraph
```

```python
from langgraph.graph import StateGraph, END
from typing import TypedDict, Annotated
import operator

class DiagnosisState(TypedDict):
    problem: str
    expected: str
    func_name: str
    evidence: str           # 阶段 4-5 的产物
    conditions: str         # 条件树
    tpe_result: str         # TPE 结果
    suppression: str        # 抑制信号
    probe_results: str      # 变量探测

    # Expert opinions
    signal_chain_opinion: str
    algorithm_opinion: str
    system_state_opinion: str
    perception_opinion: str
    architecture_opinion: str

    # Challenge results
    moderator_challenges: list[str]

    # Final verdict
    final_verdict: str
    confidence: float
```

### P3.2: 5 专家节点迁移 (2 天)

**目标**: 将现有 expert 逻辑迁移为 LangGraph 节点。

```python
def signal_chain_agent(state: DiagnosisState, config) -> dict:
    """信号链路专家 — Round 1 独立分析."""
    prompt = build_signal_chain_prompt(state)
    response = router.complex(prompt, system=SYSTEM_SIGNAL_CHAIN)
    return {"signal_chain_opinion": response}

# Similar for algorithm, system_state, perception, architecture
```

### P3.3: 主持人挑战 + 收敛 (1 天)

**目标**: Round 2 交叉审查 + Round 3 收敛。

```python
def moderator_challenge(state: DiagnosisState, config) -> dict:
    """主持人发现矛盾点，生成挑战问题."""
    opinions = [state[f"{k}_opinion"] for k in EXPERT_KEYS]
    prompt = f"以下是 5 位专家的意见，找出矛盾点:\n{''.join(opinions)}"
    challenges = router.complex(prompt, system=MODERATOR_SYSTEM)
    return {"moderator_challenges": parse_challenges(challenges)}

def expert_round2(state: DiagnosisState, config) -> dict:
    """专家回应挑战，修正意见."""
    # Each expert receives challenges and revises
    ...

def moderator_synthesize(state: DiagnosisState, config) -> dict:
    """Round 3: 综合收敛，输出最终裁决."""
    prompt = build_synthesis_prompt(state)
    verdict = router.complex(prompt, system=SYNTHESIS_SYSTEM)
    return {"final_verdict": verdict}
```

### P3.4: prompt 外部化管理 (1 天)

**目标**: 所有 prompt 从代码分离到文件。

```
新增文件:
  prompts/expert_panel/
    signal_chain.md
    algorithm.md
    system_state.md
    perception.md
    architecture.md
    moderator_challenge.md
    moderator_synthesis.md
```

```python
def load_prompt(name: str) -> str:
    prompt_path = PROMPTS_DIR / f"{name}.md"
    return prompt_path.read_text(encoding="utf-8")
```

---

## Phase 4: CodeFixEngine (5 天)

### P4.1: 架构设计 (1 天)

```
新增文件:
  ai/codefix_engine.py
```

**设计**:
```
class CodeFixEngine:
    def generate_fix(self, verdict: dict, codegraph: CodeGraph) -> CodeFixResult:
        """
        Input:  expert_panel final_verdict (包含根因 + 修复建议)
        Process:
          1. Parse verdict to extract fix_suggestions
          2. For each suggestion:
             a. CodeGraph.locate(code_file, line, context)
             b. Extract surrounding code (N lines before/after)
             c. Send to coder LLM with fix instruction
             d. Parse response as unified diff
             e. Validate diff (syntax check)
             f. Run embedded-c-runtime-safety checks
          3. Return CodeFixResult(diffs, safety_report, confidence)
        """
```

### P4.2-P4.5: 实现 (4 天)

见 PRD FR-004 详细描述。

---

## Phase 5: 管线精简 + 记忆简化 (5 天)

### P5.1: 管线步骤合并 (2 天)

**目标**: 15 步 → 8 步。

```
修改文件:
  ai/orchestrator.py — 重构 run_diagnosis 管线
```

新管线:
```python
def run_diagnosis(self, case_dir, problem, expected, on_status=None):
    # Step 1: init
    self._ensure_source_docs(on_status)

    # Step 2: classify (合并 understand + classify)
    classification = self._classify_problem(problem, expected, on_status)

    # Step 3: extract (合并 parse + window + analyze)
    extraction = self._extract_all(case_dir, classification, on_status)

    # Step 4: evidence (conditions + tpe + probe, 可并行)
    evidence = self._gather_evidence(extraction, classification, on_status)

    # Step 5: signals (合并 suppression + output_signals)
    signals = self._analyze_signals(extraction, classification, on_status)

    # Step 6: diagnose (LangGraph 专家面板)
    diagnosis = self._run_expert_panel(evidence, signals, classification, on_status)

    # Step 7: fix (CodeFixEngine)
    fix = self._generate_fix(diagnosis, on_status)

    # Step 8: deliver (report + visualize + memory)
    self._deliver_all(case_dir, diagnosis, fix, on_status)
```

### P5.2: ContextBudget 优化 (1 天)

### P5.3: 记忆系统简化 (1 天)

### P5.4: 端到端回归测试 (1 天)

**测试方案**:
```
使用现有 cases/ 中的案例:
  1. 用 v1 管线跑一遍 → 保存 report.md 作为 baseline
  2. 用 v2 管线跑一遍 → 对比 report.md
  3. 核心结论 (根因、置信度、修复建议) 应一致
  4. 差异部分记录为 "已知差异"
```

---

## 时间线

```
Week 1:  Phase 1 (基础层加固) — MF4 + topic 发现 + 降级 + 可观测
Week 2-3: Phase 2 (tree-sitter 代码分析)
Week 4:   Phase 3 (LangGraph 专家面板) — 可与 Phase 2 后半并行
Week 5:   Phase 4 (CodeFixEngine)
Week 6:   Phase 5 (管线精简 + 回归测试)
```

**总工期: 6 周 / 30 天**

---

## 每次会话工作流

```
1. 读 handoff master → 了解当前状态
2. 读 PRD_refactor_v2.md → 了解改造目标
3. 读 IMPLEMENTATION_PLAN_v2.md → 了解实施步骤
4. 执行一个 Phase 内的若干任务
5. 完成后更新 handoff + handoff 的 Git 提交历史
6. 更新本文件 (完成的任务标记为 done)
```
