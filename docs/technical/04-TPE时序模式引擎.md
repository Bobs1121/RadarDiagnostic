# 时序模式引擎 (TPE) — 系统核心创新

## 职责

TPE 是 radarAnalyze 最核心的分析方法论创新：将 **C 源码中的时序行为模式** 与 **CAN 数据中的实际信号时序** 做因果对齐，自动判断"代码中的 Hold-Release / Accumulate 等行为模式在本次录制的哪些时刻被触发"。

这是纯规则模块，不调用 AI。

## 架构

```
┌─────────────────────────────────────────────────────┐
│                   TemporalPatternEngine              │
│                    (facade / 门面)                    │
│                                                     │
│  ┌───────────────┐    ┌──────────────────┐          │
│  │ PatternExtractor│    │ TemporalAnalyzer │          │
│  │   (代码侧)      │    │   (数据侧)        │          │
│  │ 正则扫描 C 源码  │    │ 信号时序特征提取  │          │
│  └───────┬───────┘    └────────┬─────────┘          │
│          │                     │                     │
│          ▼                     ▼                     │
│  ┌──────────────────────────────────────┐            │
│  │         CausalAligner                │            │
│  │     (因果对齐 / 胶水层)               │            │
│  │ 区间求交 → 判定触发 → 关联状态跳变    │            │
│  └──────────────────────────────────────┘            │
└─────────────────────────────────────────────────────┘
```

## 入口 — TemporalPatternEngine.run()

```python
class TemporalPatternEngine:
    def __init__(
        self,
        source_root: Path,          # cr60_light 源码根目录
        cache_dir: Path,            # source_docs/ 缓存目录
        signal_mapping: dict,       # signal_mapping.json
        variable_chains: dict,      # variable_chains.json
        output_mapping: dict,       # output_mapping.json
        output_aliases: dict,       # L6 学到的输出链别名
    ):
        self.pattern_extractor = PatternExtractor(source_root, cache_dir)
        self.temporal_analyzer = TemporalAnalyzer()
        self.aligner = CausalAligner(signal_mapping, variable_chains)

    def run(
        self,
        store: FrameStore,
        func_name: Optional[str] = None,    # 过滤 ADAS 功能
        time_window: Optional[tuple] = None, # 时间窗口
        state_transitions: list[dict] = None, # 状态跳变
    ) -> TPEResult:
        """
        端到端执行流程：
        1. 提取代码模式 (PatternExtractor)
        2. 过滤目标功能
        3. 收集所需变量
        4. 解析为 CAN 信号名
        5. 加载时序特征 (TemporalAnalyzer)
        6. 因果对齐 (CausalAligner)
        7. 返回 TPEResult
        """
```

### 执行步骤详解

#### Step 1: 提取代码模式

```python
patterns = self.pattern_extractor.extract_all(use_cache=True)
```

从 4 个目标 C 文件中提取时序行为模式。使用 Hash 缓存，源码未变更时直接读取缓存。

#### Step 2: 过滤功能

```python
filtered = self._filter_patterns(patterns, func_name)
```

如果指定了 `func_name`（如 "RCTA"），只保留与该功能相关的模式。

#### Step 3-4: 变量 → CAN 信号解析

```python
required_vars = self._collect_required_variables(filtered)
resolved_signals, unresolved, internal_only = \
    self._resolve_required_can_signals(required_vars)
```

三层分类：
- `resolved_signals`: 成功映射到 CAN 信号的变量
- `unresolved`: 无法映射的变量（需要补充 signal_mapping）
- `internal_only`: 纯内部变量（FIFO buffer、counter 等），不报告

#### Step 5: 加载时序特征

```python
features, missing = self._load_features(
    store, resolved_signals, time_window=time_window,
)
```

对每个 CAN 信号，从 FrameStore 中提取时间序列，交给 TemporalAnalyzer 分析。

#### Step 6: 因果对齐

```python
timeline = state_timeline_from_transitions(state_transitions)
evidence = self.aligner.align(
    patterns=filtered, features=features,
    state_timeline=timeline, func_name_filter=None,
)
```

## 核心组件详解

### 1. PatternExtractor — 代码侧模式提取

#### 6 类行为模式

| 模式 | C 代码特征 | 含义 |
|------|-----------|------|
| HoldRelease | `if (cond) { flag = false; time = 0 }` | 保持失效 |
| HoldEntry | `if (cond) { flag = true; ... }` | 保持进入 |
| Accumulate | `time += dt` 配合 `time = 0` | 时间累积器 |
| Hysteresis | enter_thresh != exit_thresh | 阈值迟滞 |
| Debounce | `cnt++ / if (cnt >= N)` | 防抖计数 |
| EdgeTrigger | `prev == 0 && cur != 0` | 边沿触发 |

#### HoldRelease 检测算法（最高精度）

```python
def _scan_hold_release(self, rel_path: str, lines: list[str]) -> list[CodePattern]:
    """
    逐行扫描，查找 if(...) { flag=false; time=0; ... } 模式。
    
    算法：
    1. 匹配 if(EXPR) 行 → 提取条件表达式
    2. 扫描后续 20 行 (MAX_BODY_SCAN)，检查 body
    3. 在 body 中寻找：
       - 赋值 false/0 的变量 (consequence_variables)
       - 赋值 0 的计时器变量
    4. 如果找到赋值 + 计时器清零 → HoldRelease 模式
    5. 从条件表达式提取触发变量 (trigger_variables)
    6. 推断 ADAS 功能 (通过 _FUNC_KEYWORDS 匹配)
    """
```

正则表达式：
```python
_IF_RE = re.compile(r'^\s*if\s*\((.+?)\)\s*\{?\s*$')
_ASSIGN_ZERO_RE = re.compile(
    r'^\s*(\w+(?:\.\w+)?(?:->\w+)?)\s*=\s*(?:\(?\s*bool\s*\)?)?(?:false|0|FALSE)\s*;?\s*$',
    re.IGNORECASE,
)
_ASSIGN_TRUE_RE = re.compile(
    r'^\s*(\w+(?:\.\w+)?(?:->\w+)?)\s*=\s*(?:\(?\s*bool\s*\)?)?(?:true|TRUE|1)\s*;?\s*$',
)
_ACCUMULATE_RE = re.compile(
    r'^\s*(\w+(?:\.\w+)?)\s*\+=\s*[\w.\->]+\s*;?\s*$',
)
```

#### 输出 — CodePattern

```python
@dataclass
class CodePattern:
    pattern_type: str              # "HoldRelease" / "Accumulate" / ...
    file: str                      # 源文件路径
    line_start: int                # 起始行号
    line_end: int                  # 结束行号
    function: str                  # 所在 C 函数名
    trigger_condition: str         # if 条件表达式
    trigger_variables: list[str]   # 触发变量列表
    consequence_variables: list[str] # 后果变量列表
    adas_function: str             # 关联的 ADAS 功能
    snippet: str                   # 代码片段
    notes: str                     # 注释
```

### 2. TemporalAnalyzer — 数据侧时序分析

#### 核心数据类型

```python
@dataclass
class Edge:
    """信号跳变：(时间, 从值, 到值)"""
    t: float
    from_val: object
    to_val: object

@dataclass
class Run:
    """连续段：(值, 开始时间, 结束时间)"""
    value: object
    t_start: float
    t_end: float
    @property
    def duration(self) -> float:
        return self.t_end - self.t_start

@dataclass
class TemporalFeature:
    """完整时序特征"""
    signal_name: str
    sample_count: int
    t_start: float
    t_end: float
    value_distribution: dict       # 值分布
    edges: list[Edge]              # 所有跳变
    runs: list[Run]                # 连续段
    runs_by_value: dict            # 按值分组的 runs
    stats: dict                    # 统计量
    pattern_tag: str               # "stable" / "brief_pulses" / "oscillating"
```

#### 分析算法

```python
class TemporalAnalyzer:
    BRIEF_PULSE_THRESHOLD_SEC = 0.5  # 短脉冲阈值
    HIGH_EDGE_RATE_HZ = 2.0           # 高频振荡阈值

    def analyze(self, timeline: SignalTimeline) -> TemporalFeature:
        """
        分析流程：
        1. 按时间排序 samples
        2. 提取 runs（连续段）和 edges（跳变）
        3. 计算 runs_by_value（按值分组）
        4. 计算统计量：
           - min/max run duration
           - total time at each value
           - edge rate
           - brief runs count
        5. 打标签：
           - "stable": 95%+ 时间在一个值上
           - "brief_pulses": 存在 < 0.5s 的短脉冲
           - "oscillating": 跳变率 > 2 Hz
           - "edge_dominated": 跳变频繁但非振荡
        """
```

#### 模式标签规则

```python
def _classify_pattern(runs, runs_by_value, stats, span):
    """
    1. stable: 主导值占比 > 95%
    2. brief_pulses: 存在 < 0.5s 的短暂段，且主导值占比 > 90%
    3. oscillating: edge_rate > 2 Hz 且主导值占比 < 70%
    4. edge_dominated: edge_rate > 0.5 Hz
    5. 否则: mixed
    """
```

### 3. CausalAligner — 因果对齐

#### 核心算法：区间求交

```python
class CausalAligner:
    NEARBY_WINDOW_SEC = 0.5     # 附近状态跳变窗口
    MIN_TRIGGER_DURATION_SEC = 0.0  # 最小触发持续时间

    def align(self, patterns, features, state_timeline) -> list[PatternEvidence]:
        """对每个模式做因果对齐"""

    def _align_one(self, pattern, features, state_timeline) -> PatternEvidence:
        """
        单个模式的因果对齐流程：
        
        1. 解析触发条件 → [(var, trigger_value), ...]
           例: "!A && !B" → [("A", 0), ("B", 0)]
        
        2. 将 C 变量解析为 CAN 信号
           - 精确匹配 features 字典
           - 通过 signal_mapping 解析
           - 通过 variable_chains 解析
           - 返回: resolved / unresolved / missing
        
        3. 对每个变量，找到满足触发条件的 runs
           例: 变量 A 的 trigger_value=0 → 找到 A 所有值为 0 的 runs
        
        4. 对所有变量的 runs 做区间求交
           使用 sweep-line 算法，两两相交
           结果 = 所有变量同时满足触发条件的时间段
        
        5. 对每个交点区间，记录：
           - 区间起止时间
           - 所有变量在区间开始时的值
           - ±0.5s 内的状态跳变（关联证据）
        
        6. 裁决：
           - triggered: 有 hits
           - not_triggered: 无 hits
           - insufficient_data: 有 unresolved/missing 变量
        """
```

#### 条件解析

```python
def _parse_condition_terms(self, cond: str) -> list[tuple[str, object]]:
    """
    将 C 布尔表达式转化为 [(变量, 触发值)]。
    
    示例：
    "!A && !B"              → [("A", 0), ("B", 0)]
    "A == 0 && B == FALSE"  → [("A", 0), ("B", 0)]
    "flag"                  → [("flag", "truthy")]
    "X != 1"                → [("X", ("!=", 1))]
    """
```

正则表达式：
```python
_NOT_RE = re.compile(r'!\s*(?!=)\s*([A-Za-z_][\w.]*)')
_EQ_RE  = re.compile(r'([A-Za-z_][\w.]*)\s*==\s*([A-Za-z_0-9.]+)')
_NEQ_RE = re.compile(r'([A-Za-z_][\w.]*)\s*!=\s*([A-Za-z_0-9.]+)')
```

#### 区间求交算法

```python
@staticmethod
def _intersect_two(a: list[Interval], b: list[Interval]) -> list[Interval]:
    """
    经典 sweep-line 区间求交。
    
    两个已排序的区间列表，找出重叠部分。
    时间复杂度: O(len(a) + len(b))
    """
    out = []
    i = j = 0
    while i < len(a) and j < len(b):
        s = max(a[i].t_start, b[j].t_start)
        e = min(a[i].t_end, b[j].t_end)
        if e > s:
            out.append(Interval(s, e))
        if a[i].t_end < b[j].t_end:
            i += 1
        else:
            j += 1
    return out
```

### 4. TPEResult — 结果结构

```python
@dataclass
class TPEResult:
    patterns: list[CodePattern]          # 所有模式
    features: dict[str, TemporalFeature] # 所有信号的时序特征
    evidence: list[PatternEvidence]       # 因果对齐结果
    unresolved_variables: set[str]        # 未解析变量
    internal_only_variables: set[str]     # 纯内部变量（不报告）
    missing_can_signals: set[str]         # CAN 信号缺失
    notes: list[str]                      # 备注

    @property
    def triggered_count(self) -> int:
        return sum(1 for e in self.evidence if e.verdict == "triggered")

    def to_expert_block(self) -> str:
        """生成 Markdown 块，注入专家面板 prompt"""
```

## 数据流图

```
C 源码
    │
    ▼
┌─ PatternExtractor ───────────────┐
│ 正则扫描 4 个目标文件              │
│ 提取 6 类行为模式                 │
│ Hash 缓存 (source_docs/)         │
└──────────┬───────────────────────┘
           │
           ▼
┌─ CodePattern x N ────────────────┐
│ file, line_start, line_end       │
│ trigger_condition, trigger_vars  │
│ consequence_vars, adas_function  │
└──────────┬───────────────────────┘
           │
           ▼
┌─ 变量 → CAN 信号解析 ────────────┐
│ signal_mapping.json              │
│ variable_chains.json             │
│ output_mapping.json              │
│ 6 级降级解析                      │
└──────────┬───────────────────────┘
           │
           ▼
┌─ FrameStore 查询 CAN 信号 ───────┐
│ 按 CAN 信号名查询时间序列          │
│ 可选时间窗口裁剪                   │
└──────────┬───────────────────────┘
           │
           ▼
┌─ TemporalAnalyzer ───────────────┐
│ 对每个信号做时序分析               │
│ 提取: edges, runs, stats         │
│ 打标签: stable/brief_pulses/...  │
└──────────┬───────────────────────┘
           │
           ▼
┌─ CausalAligner ──────────────────┐
│ 条件解析 → 变量解析 → runs 求交   │
│ → 关联状态跳变 → 裁决             │
└──────────┬───────────────────────┘
           │
           ▼
┌─ TPEResult ──────────────────────┐
│ patterns, features, evidence     │
│ unresolved, missing, notes       │
│ triggered_count, has_triggers    │
└──────────────────────────────────┘
```

## 裁决规则

| 裁决 | 含义 | 对专家的影响 |
|------|------|-------------|
| `triggered` | 数据时序与代码模式匹配 | 这是"时序耦合"类 Bug 最可能的根因 |
| `not_triggered` | 数据时序不匹配 | 反向证据，排除某些假设 |
| `insufficient_data` | 变量无法映射到 CAN 信号 | 不得把"无法判定"当成"未触发" |
| `unknown` | 条件无法解析 | 需补充 signal_mapping |

## 性能

- 首次提取: ~200ms（正则扫描 4 个文件）
- 缓存命中: < 1ms
- 时序分析: ~100ms/信号
- 因果对齐: ~50ms/模式
- 典型案例: 20 个模式 x 5 个信号 ≈ 1s

## 错误处理

- PatternExtractor 失败: 返回空模式列表
- 变量无法解析: 标记 unresolved，不阻塞
- CAN 信号缺失: 标记 missing，不阻塞
- TemporalAnalyzer 失败: 跳过该信号
- CausalAligner 失败: 返回 `insufficient_data` 裁决
