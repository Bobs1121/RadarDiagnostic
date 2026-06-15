# radarAnalyze v2 — Phase 14 分析能力强化计划（2026-06-15）

> 基准: PRD v2.1.1, codegraph-handoff-master.md (综合评分 8.5/10)
> 状态: Phase 1-7 已完成
> 当前分支: `refactor/v2`
> 编写时间: 2026-06-15
> 驱动来源: 总体设计评估 — 管线链路、知识注入、记忆机制、分析能力四维深度审查

---

## 0. 评估驱动的改造方向

基于 2026-06-15 总体设计评估，识别出以下核心差距：

| # | 领域 | 评估分数 | 核心问题 | 对应 Phase |
|---|------|---------|---------|-----------|
| 1 | **TPE 时序模式引擎** | 2/10 | 仅 2 种模式 (HoldRelease/Accumulate)，causal_aligner 仅 AND | Phase 14 |
| 2 | **条件提取可靠性** | 5/10 | 纯 LLM 提取无静态分析兜底，mtime 缓存有 AI 漂移 | Phase 14 |
| 3 | **抑制/输出信号分析** | 4/10 | windows 参数未使用，无时间相关性分析 | Phase 14 |
| 4 | **知识注入效率** | 6/10 | ensure_overview_docs 每次诊断阻塞，variable_chains 无缓存 | Phase 15 |
| 5 | **记忆机制可靠性** | 6/10 | 竞态、JSON 解析脆弱、无衰退机制 | Phase 15 |
| 6 | **工程健壮性** | 5/10 | 静默失败过多，未使用参数，store 未校验 | Phase 14 |

---

## 1. Phase 14: 分析能力核心强化（P0 — 直接影响诊断质量）

**目标**: 补全 TPE、条件提取、抑制分析三个直接决定诊断深度的核心能力。

**预期效果**:
- TPE 模式覆盖从 2 种扩展到 6 种，覆盖 ADAS 诊断 80%+ 时序场景
- 条件提取从纯 LLM 变为"正则 AST 兜底 + LLM 增强"双层
- 抑制信号检查真正使用测试窗口做时间相关性分析
- 消除静默失败，所有关键步骤可观测

---

### 1.1 TPE 时序模式引擎扩展（3-4 天）

**当前状态**: `pattern_extractor.py` 仅 HoldRelease + Accumulate 两种模式，正则实现。`causal_aligner.py` 仅 AND 合取。

**目标模式清单**:

| 模式 | 说明 | ADAS 场景 | 实现方式 |
|------|------|-----------|---------|
| HoldRelease (已有) | 条件持续 N 帧后触发 | 警告迟滞 | 正则 |
| Accumulate (已有) | 变量累加/递减到阈值 | 速度积分 | 正则 |
| **ThresholdCross** | 信号穿越阈值（上升/下降沿） | 速度域切换、TTC 门限 | 正则 → AST |
| **StateTransition** | 状态机非法/缺失转换 | 双状态机交互、使能链路断裂 | AST (state_machine_extractor 已有) |
| **TemporalDependency** | A 必须先于 B，或 A-B 间隔 < X | 检测→警告→输出时序 | 数据层分析 |
| **FlagSetNeverCleared** | 标志位置位后未被清除 | 异常状态卡死 | 正则 (pattern_extractor_ast 已有) |

#### 1.1.1 ThresholdCross 模式（1 天）

**设计**:
```python
@dataclass
class ThresholdCrossPattern(CodePattern):
    pattern_type: str = "threshold_cross"
    variable: str              # 被监测变量
    threshold: float           # 阈值
    direction: str             # "rising" | "falling" | "either"
    consequence: str           # 穿越后触发的动作/变量
    source_file: str
    line_range: tuple[int, int]
```

**提取逻辑** (在 `pattern_extractor.py` 中新增 `_extract_threshold_cross()`):
- 正则: `if\s*\(\s*(>=?|<=?)\s*\d+\.?\d*\s*\)` 匹配比较
- 结合 AST: `BinaryOp(CMP, variable, constant)` 提取精确变量名和阈值
- 缓存: 复用 `code_patterns.json` 的 source_hash 机制

**时序检测** (在 `temporal_analyzer.py` 中新增):
- 从 FrameStore 拉取变量时间线
- 检测穿越点: `sign(values[i] - threshold) != sign(values[i-1] - threshold)`
- 输出: `TemporalFeature` 含 `crossing_points[]`, `dwell_time_sec`, `oscillation_count`

#### 1.1.2 StateTransition 模式（1 天）

**当前资源**: `ai/codegraph/state_machine_extractor.py` 已有 AST 状态机提取，但未接入 TPE。

**设计**:
```python
@dataclass
class StateTransitionPattern(CodePattern):
    pattern_type: str = "state_transition"
    state_machine: str         # 状态机名称（如 fctaSystemState）
    from_state: str
    to_state: str
    guard_conditions: list[str]  # 转换守护条件
    missing_transitions: list[str]  # 代码中未定义的转换（异常路径）
```

**接入 TPE**:
- `TemporalPatternEngine.run()` 调用 `state_machine_extractor.extract()` 获取状态机定义
- 从 `radar_debug` 表提取运行时状态时间线
- 对比: 运行时是否出现了代码未定义的转换？转换守护条件是否满足？
- 输出: `PatternEvidence(verdict="illegal_transition" | "missing_guard" | "conforming")`

#### 1.1.3 TemporalDependency 模式（1 天）

**设计**: 从条件文件和专家知识中推断时序依赖关系。

```python
@dataclass
class TemporalDependencyPattern(CodePattern):
    pattern_type: str = "temporal_dependency"
    prerequisite: str          # 前置事件（如 "target_detected"）
    consequent: str            # 后续事件（如 "warning_issued"）
    max_delay_sec: float       # 最大允许延迟
    source: str                # 来源（condition_file / expert_panel / code_pattern）
```

**数据层检测** (`temporal_analyzer.py`):
- 从 `warning_events` 表获取事件时间戳
- 计算 prerequisite → consequent 的实际延迟
- 判断: 延迟是否超过阈值？事件是否缺失？

#### 1.1.4 CausalAligner OR 逻辑补全（1 天）

**当前问题**: `causal_aligner.py` 只支持 AND 合取。

**改造方案**:
```python
# 新增 Expression 抽象
@dataclass
class BoolExpr:
    def evaluate(self, features: dict[str, TemporalFeature]) -> str:
        ...

class AndExpr(BoolExpr):
    operands: list[BoolExpr]

class OrExpr(BoolExpr):
    operands: list[BoolExpr]

class NotExpr(BoolExpr):
    operand: BoolExpr

class LiteralExpr(BoolExpr):
    variable: str  # 直接引用 TemporalFeature
```

**实现步骤**:
1. `CodePattern.trigger_condition` 从字符串改为 `BoolExpr` 树
2. `pattern_extractor` 提取时构建 `BoolExpr`（`&&` → AndExpr, `||` → OrExpr, `!` → NotExpr）
3. `CausalAligner.align()` 调用 `expr.evaluate(features)` 替代当前 flat AND 检查
4. 向后兼容：字符串条件自动包装为 `LiteralExpr`

#### 1.1.5 验收标准

- `pattern_extractor.extract_all()` 产出 ≥6 种 pattern_type
- `TemporalPatternEngine.run()` 对 FCTA001 案例检测到 ≥3 个 `triggered` 模式（当前可能 0）
- `causal_aligner` 支持 `||` 条件的条件正确评估
- 新增模式有单元测试（至少 2 个 per pattern_type）

---

### 1.2 条件提取双层机制（2-3 天）

**当前问题**: `condition_extractor.py` 纯 LLM 提取条件树，无兜底。mtime 缓存策略有 AI 漂移风险。

**目标**: "确定性正则/AST 提取 + LLM 语义增强"双层架构。

#### 1.2.1 第一层：确定性条件提取（1 天）

**新建模块**: `ai/condition_extractor_rules.py`

```python
class RuleConditionExtractor:
    """基于正则+AST的条件提取器，LLM的兜底"""

    def extract_activation_conditions(self, source_files: list[Path]) -> dict:
        """提取激活/使能条件"""
        # 1. 正则: if (X && Y && Z) → {trigger: [X, Y, Z]}
        # 2. 正则: if (speed >= LOW && speed <= HIGH) → speed_range
        # 3. AST: 状态机 switch-case → transitions
        # 4. 正则: 抑制信号 if (suppression_signal == 1) return; → suppression

    def extract_speed_ranges(self, source_files: list[Path]) -> dict:
        """提取速度域（ego_speed_ranges / target_speed_ranges）"""

    def extract_suppression_signals(self, source_files: list[Path]) -> list[dict]:
        """提取外部抑制信号"""
```

**提取策略**:
- **速度域**: 正则匹配 `speed >= X && speed <= Y` 模式，提取 low/high/unit
- **抑制信号**: 正则匹配 `if.*return` / `if.*break` 前置守卫模式
- **状态转换**: 复用 `state_machine_extractor` 的 AST 提取
- **迟滞/定时器**: 正则匹配 `hysteresis` / `timer` / `delay` 变量引用

**缓存**: SHA256 源码 hash（替代 mtime），消除 AI 漂移风险。

#### 1.2.2 第二层：LLM 语义增强（1 天）

**改造 `condition_extractor.py`**:

```python
class ConditionExtractor:
    def extract(self, func_name, force=False) -> dict:
        # 1. 先跑确定性提取（兜底线）
        rule_conditions = RuleConditionExtractor.extract(...)

        # 2. 如果缓存命中且有效，直接返回
        if cache_valid(func_name):
            return cached_conditions

        # 3. LLM 提取（增强层）
        llm_conditions = self._llm_extract(func_name)

        # 4. 合并：LLM 结果覆盖规则结果，但规则结果作为保底
        merged = self._merge(rule_conditions, llm_conditions)

        # 5. 缓存使用 SHA256 hash（非 mtime）
        self._cache(merged, source_hash)
        return merged
```

**合并策略 `_merge()`**:
- LLM 提取了某字段 → 用 LLM 结果
- LLM 未提取但规则提取了 → 用规则结果
- 两者都有但冲突 → 优先 LLM，记录冲突到日志

#### 1.2.3 缓存策略改造（0.5 天）

**从 mtime 改为 SHA256**:

```python
# 旧: mtime 比较
cache_valid = all(src.mtime <= cache.mtime for src in source_files)

# 新: SHA256 比较
source_hash = sha256(concat(source_file.read_bytes() for source_file in source_files)).hexdigest()[:16]
cache_valid = cached_hash == source_hash
```

#### 1.2.4 验收标准

- `RuleConditionExtractor` 对 adasFunc.c 提取出 ≥5 个速度域、≥3 个抑制信号
- 缓存失效从 mtime 改为 SHA256
- LLM 失败时（API 不可用），规则层仍可产出基本条件
- FCTA/BSD/RCTA 三种功能的条件提取对比规则 vs LLM 覆盖率

---

### 1.3 抑制信号与输出信号分析强化（1-2 天）

**当前问题**: `_check_suppression_signals()` 和 `_analyze_output_signals()` 的 `windows` 参数未使用，没有时间相关性分析。

#### 1.3.1 抑制信号时间相关性分析（1 天）

**改造 `_check_suppression_signals()`**:

```python
def _check_suppression_signals(self, store, func_name, conditions, windows) -> str:
    """检查抑制信号是否在测试窗口内被触发"""
    suppression_text = []

    for sup in conditions.get("external_suppression", []):
        variable = sup["variable"]
        can_signal = sup.get("can_signal")

        # 1. 解析 CAN 信号名到 BLF 数据
        if can_signal:
            timeline = self._load_signal_timeline(store, can_signal)
        else:
            timeline = self._load_variable_from_debug(store, variable)

        # 2. 在测试窗口内检查抑制信号状态
        if windows and timeline:
            window_values = [v for v in timeline if in_window(v, windows)]
            suppression_ratio = sum(1 for v in window_values if v == 1) / len(window_values)

            if suppression_ratio > 0.5:
                suppression_text.append(
                    f"【抑制触发】{variable} 在 {len(windows)} 个窗口内 "
                    f"{suppression_ratio*100:.0f}% 时间为抑制状态"
                )
            elif suppression_ratio > 0:
                suppression_text.append(
                    f"【间歇抑制】{variable} 在窗口内 {suppression_ratio*100:.0f}% 时间抑制"
                )
            else:
                suppression_text.append(f"【未抑制】{variable} 在窗口内全程未抑制")
        else:
            suppression_text.append(f"【无数据】{variable} 无法获取时序数据")

    return "\n".join(suppression_text)
```

#### 1.3.2 输出信号分析强化（0.5 天）

**改造 `_analyze_output_signals()`**:

```python
def _analyze_output_signals(self, store, func_name, windows, output_mapping) -> str:
    """分析输出信号在窗口内的实际行为"""
    signals = []
    for mapping in output_mapping.get("mappings", []):
        can_signal = mapping["can_signal"]
        if not can_signal.startswith(func_name):
            continue

        timeline = self._load_signal_timeline(store, can_signal)
        if windows and timeline:
            # 统计窗口内输出信号的激活比例和时序模式
            window_data = [v for v in timeline if in_window(v, windows)]
            if window_data:
                activation_ratio = sum(1 for v in window_data if v != 0) / len(window_data)
                signals.append({
                    "signal": can_signal,
                    "activation_ratio": activation_ratio,
                    "window_count": len(windows),
                })

    return format_output_signal_summary(signals)
```

#### 1.3.3 验收标准

- `_check_suppression_signals` 真正使用 `windows` 参数
- 抑制信号分析输出包含窗口内激活比例
- FCTA001 案例重新诊断，抑制分析章节有实际数据（非 "无数据"）

---

### 1.4 工程健壮性修复（1 天）

**修复清单**:

| # | 问题 | 位置 | 修复 |
|---|------|------|------|
| 1 | `_update_memories` 静默失败 | `orchestrator.py` | `except Exception as e: logger.warn(f"memory update failed: {e}")` |
| 2 | `store.close()` 未校验 store 非空 | `orchestrator.py` | `if store: store.close()` |
| 3 | `_run_tpe`/`_check_suppression`/`_analyze_output_signals` 未使用 windows 参数 | `orchestrator.py` | 1.3 节已修复 |
| 4 | `tpe_section` 因 `evidence.pop` 顺序通常为空 | `orchestrator.py` | 调整 pop 顺序或显式传递 tpe_text |
| 5 | LLM JSON 解析失败无重试 | `utils.py` `parse_json_from_llm` | 增加 2 次重试 + 更宽松的提取策略 |
| 6 | `_precipitate_knowledge` 静默失败 | `orchestrator.py` deliver | 增加警告日志 |
| 7 | `car_spd` 单位不一致 (m/s vs km/h) | `test_window_detector.py` | 详情字符串修正为 m/s 或转换 |

#### 1.4.1 验收标准

- 所有 `except: pass` 替换为 `except Exception as e: logger.warn(...)`
- `tpe_section` 在证据 dict 中正确填充
- 诊断日志输出包含每个步骤的成功/失败状态
- 运行 FCTA001 诊断无静默失败

---

### 1.5 Phase 14 总工时与依赖

| 子任务 | 工时 | 依赖 |
|--------|------|------|
| 1.1 TPE 扩展（4 新模式 + OR 逻辑） | 4 天 | 无 |
| 1.2 条件提取双层机制 | 2.5 天 | 1.1（复用 state_machine_extractor） |
| 1.3 抑制/输出信号分析强化 | 1.5 天 | 无（可与 1.1 并行） |
| 1.4 工程健壮性修复 | 1 天 | 可在任何阶段穿插 |
| **可并行总计** | **~5 天** | 串行 ~9 天 |

---

## 2. Phase 15: 知识注入与记忆机制优化（P1 — 效率与可靠性）

**目标**: 解决知识注入效率低、记忆机制可靠性差的问题。

---

### 2.1 知识注入效率优化（2 天）

#### 2.1.1 诊断前知识预热（1 天）

**问题**: `ensure_overview_docs` 在每次诊断 Step 1 阻塞执行。

**方案**:
```
诊断流程:
  Step 0 (可选): --prewarm 标志 → 提前运行 CodeLearner.learn() + ensure_overview_docs()
  Step 1 (init): 只检查缓存命中 → 缓存有效则跳过 LLM 调用

Dream 流程:
  Phase 0: 定期运行 CodeLearner.learn() → 保持 L6 知识新鲜
  CLI: python cli.py --dream-force 手动触发
```

**实现**:
1. `orchestrator._ensure_source_docs()` 增加 `prewarm_done` 标志：如果最近 1h 内有成功的 overview_docs 生成，直接跳过
2. 新增 CLI 参数 `--prewarm`：诊断前主动运行知识预热
3. AutoDream 门控增加"代码变更检测"：当 `key_source_files` 的 SHA256 与缓存不一致时，强制触发 Phase 0

#### 2.1.2 variable_chains 缓存（0.5 天）

```python
def trace_variable_chains(source_root, output_dir, force=False) -> dict:
    cache_file = output_dir / "variable_chains.json"
    cache_meta = output_dir / "variable_chains.meta.json"

    if not force and cache_meta.exists():
        meta = json.loads(cache_meta.read_text())
        # 检查所有扫描文件的 SHA256
        if all(file_hash_matches(f, h) for f, h in meta["file_hashes"].items()):
            return json.loads(cache_file.read_text())

    # 重新扫描...
    # 写入缓存 + meta
    chains = do_trace()
    cache_file.write_text(json.dumps(chains))
    cache_meta.write_text(json.dumps({
        "file_hashes": {str(f): sha256(f.read_bytes())[:16] for f in scanned_files},
        "updated_at": datetime.now().isoformat()
    }))
    return chains
```

#### 2.1.3 signal_mapping 生命周期统一管理（0.5 天）

**问题**: signal_mapping 在多处被重复加载（`_ensure_source_docs`、`_run_tpe`、`_check_suppression_signals`）。

**方案**: Orchestrator 构造函数统一加载，后续步骤共享 `self.signal_mapping` / `self.variable_chains` 实例。

#### 2.1.4 验收标准

- 连续运行两次同一案例诊断，第二次 Step 1 耗时 < 1s（缓存全命中）
- `variable_chains.json` 缓存命中率 ≥ 90%（源码无变更场景）
- signal_mapping 只在 orchestrator 初始化时加载一次

---

### 2.2 记忆机制可靠性提升（2 天）

#### 2.2.1 写入竞态保护（0.5 天）

**问题**: orchestrator 诊断时写 L2/L3/L5，AutoDream 读 L2/L3/L4/L5，无锁保护。

**方案**:
```python
# memory_system.py 新增文件级锁
import fcntl

class MemorySystem:
    def _write_atomic(self, path: Path, data: str):
        """原子写入：先写 .tmp，再 rename"""
        tmp = path.with_suffix('.tmp')
        tmp.write_text(data, encoding='utf-8')
        tmp.rename(path)  # POSIX: atomic; Windows: 也基本 atomic

    def _read_consistent(self, path: Path) -> str:
        """读取时使用共享锁，避免读到中间状态"""
        # 对 .tmp 文件自动忽略
        return path.read_text(encoding='utf-8')
```

**对 AutoDream 的保护**:
```python
# auto_dream.py Phase 1/2 收集数据时加快照
def _gather_all_memory_context(self):
    # 在 dream-lock 保护下，先拷贝所有要读的文件到临时目录
    snapshot_dir = tempfile.mkdtemp()
    for src in memory_files:
        shutil.copy2(src, snapshot_dir / src.name)
    # 后续分析只读 snapshot_dir，不读 live 文件
```

#### 2.2.2 LLM JSON 解析加固（0.5 天）

**问题**: `parse_json_from_llm` 靠首尾 `{}` 切片，多 JSON 或夹杂文字时失败。

**方案**:
```python
def parse_json_from_llm(content: str, fallback: dict = None) -> dict:
    # 策略 1: 首尾 {} 切片（现有）
    # 策略 2: 查找 ```json ... ``` 代码块
    # 策略 3: 正则 r'\{[^{}]*\}' 找最外层 {}
    # 策略 4: 容错解析 json.loads(strict=False)
    # 策略 5: 如果仍然失败，返回 fallback 并记录警告
```

#### 2.2.3 记忆衰退机制（0.5 天）

```python
# memory_system.py 新增
def decay_patterns(self, max_age_days=90, min_hit_count=3):
    """老化 patterns: 超过 max_age_days 且未被引用的模式降权"""
    patterns = self.read_patterns()
    now = datetime.now()
    active = []
    deprecated = []
    for p in patterns:
        age = (now - datetime.fromisoformat(p["_learned_at"])).days
        hit_count = p.get("_hit_count", 0)
        if age > max_age_days and hit_count < min_hit_count:
            deprecated.append(p)
        else:
            active.append(p)
    if deprecated:
        self._write_patterns(active)  # 覆盖写回
        logger.info(f"Decayed {len(deprecated)} old patterns")

# 在 AutoDream Phase 4 后调用
def _apply_dream_result(self, result):
    # ... existing apply logic ...
    self.memory.decay_patterns()
```

**pattern 命中追踪**:
- `find_similar_patterns()` 命中时 `pattern["_hit_count"] += 1`
- `build_context_for_diagnosis()` 引用 pattern 时记录命中

#### 2.2.4 MD5 去重改进（0.5 天）

```python
# 从 8 位 hex (2^32) 改为 16 位 hex (2^64)
_id = hashlib.md5(content.encode()).hexdigest()[:16]

# 或使用 SHA256 前 12 位 (2^48, 碰撞概率极低)
_id = hashlib.sha256(content.encode()).hexdigest()[:12]
```

#### 2.2.5 验收标准

- 并发测试: orchestrator 写 L2 + AutoDream 读 L2，无数据损坏
- `parse_json_from_llm` 对 5 种典型 LLM 输出格式（纯 JSON、代码块包裹、多 JSON、夹杂文字、截断）均能正确解析或安全 fallback
- 运行 decay_patterns 后，90 天前创建的无命中 pattern 被清除
- pattern `_id` 长度 ≥ 12 位 hex

---

### 2.3 Phase 15 总工时

| 子任务 | 工时 | 依赖 |
|--------|------|------|
| 2.1 知识注入效率优化 | 2 天 | 无 |
| 2.2 记忆机制可靠性提升 | 2 天 | 无 |
| **可并行总计** | **~2 天** | 串行 ~4 天 |

---

## 3. 执行路线图

### 推荐执行顺序

```
Phase 14: 分析能力核心强化                        ← 先做，直接影响诊断质量，~5 天
    ├── 1.1 TPE 扩展（4 新模式 + OR）(4 天)
    ├── 1.3 抑制/输出信号分析强化 (1.5 天)  ← 可与 1.1 并行
    └── 1.4 工程健壮性修复 (1 天)            ← 可在任何阶段穿插
        ↓
    1.2 条件提取双层机制 (2.5 天)            ← 依赖 1.1 的 state_machine_extractor

Phase 15: 知识注入与记忆优化                      ← 效率提升，~2 天
    ├── 2.1 知识注入效率优化 (2 天)
    └── 2.2 记忆机制可靠性提升 (2 天)         ← 可与 2.1 并行
```

### 与已有 Phase 的关系

```
Phase 7 (多项目 prompt 去硬编码)     ← ✅ 已完成
    ↓
Phase 14 (分析能力核心强化)          ← ★ 本轮重点
    ↓
Phase 15 (知识注入 + 记忆优化)        ← 效率提升
    ↓
Phase 8 (Identity 深度集成)           ← 后续架构完整性
    ↓
Phase 9 (Materials 材料接入)          ← 诊断质量
    ↓
Phase 10 (Harness 扩展)              ← 质量量化
```

### 预期评分提升

| 维度 | 当前 | Phase 14 后 | Phase 15 后 |
|------|------|------------|------------|
| 管线完整性 | 6/10 | **8/10** | 8/10 |
| 知识注入 | 7/10 | 7/10 | **8.5/10** |
| 记忆机制 | 7/10 | 7/10 | **8.5/10** |
| 分析深度 | 6/10 | **8.5/10** | 8.5/10 |
| 工程健壮性 | 5/10 | **7.5/10** | **8/10** |
| **综合** | **8.5/10** | **9.0/10** | **9.2/10** |

---

## 4. 风险与缓解

| 风险 | 可能性 | 影响 | 缓解 |
|------|--------|------|------|
| TPE 新模式正则误匹配 | 中 | 中 | 每种模式配单元测试；先用 gwm_b26 adasFunc.c 验证 |
| 条件提取双层合并冲突 | 低 | 低 | 合并策略明确（LLM 优先 + 规则保底），冲突可观测 |
| 记忆原子写入跨平台兼容 | 低 | 低 | `os.replace()` 在 Windows/POSIX 均 atomic |
| Phase 14 改动影响已有 Harness 6 案例 | 中 | 高 | 每完成一个子任务就运行 Harness 回归 |
| OR 逻辑引入复杂度 | 低 | 低 | BoolExpr 抽象隔离复杂度，向后兼容字符串条件 |

---

## 5. 成功指标

### Phase 14 完成后

| 指标 | 当前 | 目标 |
|------|------|------|
| TPE 模式种类 | 2 | **≥6** |
| TPE 对 FCTA001 检测到的 triggered 模式 | 0-1 | **≥3** |
| causal_aligner 支持逻辑 | AND only | **AND + OR + NOT** |
| 条件提取 LLM 不可用时的降级 | 完全失败 | **规则层保底** |
| 条件缓存策略 | mtime (漂移风险) | **SHA256** |
| 抑制信号分析使用 windows | 否 | **是** |
| 静默失败 (`except: pass`) | 多处 | **0 处** |
| Harness 6 案例回归通过率 | 5/6 | **≥5/6** |

### Phase 15 完成后

| 指标 | 当前 | 目标 |
|------|------|------|
| 连续诊断第二次 Step 1 耗时 | 数秒-数分钟 | **< 1s** |
| variable_chains 缓存命中率 | 0% (无缓存) | **≥90%** |
| 记忆写入竞态 | 无保护 | **原子写入 + 快照读取** |
| LLM JSON 解析成功率 | 不确定 | **≥95%** (5 种格式) |
| pattern 老化机制 | 无 | **90 天 TTL + 命中计数** |
| pattern _id 碰撞概率 | 2^-32 | **≤2^-48** |
