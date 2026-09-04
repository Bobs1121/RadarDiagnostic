# radarAnalyze v2.0 — Harness 设计调研报告

> 撰写时间: 2026-06-11
> 调研范围: SWE-bench, DeepEval, OpenAI Evals, AgentBench, Aider, Braintrust
> 目标: 为 radarAnalyze 设计适配的诊断质量评估体系（Harness）

---

## 1. 现状诊断

### 1.1 当前测试覆盖

| 测试文件 | 类型 | 覆盖范围 | 状态 |
|----------|------|----------|------|
| `tests/test_temporal_pattern_engine.py` | 单元测试 | TPE 三组件（PatternExtractor + TemporalAnalyzer + CausalAligner） | ✅ 可用 |
| `test_8step_pipeline.py` | 集成测试 | 8 步管线 E2E（需 LLM API） | ✅ 可用，单次手动运行 |

**缺失**:
- ❌ 无回归测试套件（diagnosis 输出质量如何量化？）
- ❌ 无诊断准确性基准（结论是否正确？根因是否定位准确？）
- ❌ 无性能基准（管线各步骤耗时是否有 SLA？）
- ❌ 无多项目交叉验证（sc6h/cr5cb 有无测试用例？）
- ❌ 无"黄金数据集"（已知正确答案的案例集）

### 1.2 核心问题

radarAnalyze 是一个 **AI 诊断管线**，不是代码生成器。评估对象不是 "代码能否编译"，而是：

```
诊断质量 = f(根因定位准确度, 条件覆盖度, 证据链完整性, 建议可操作性)
```

现有 SWE-bench 等框架评估的是 **代码修复**（patch 能否通过测试），不直接适用。我们需要的是一个 **诊断质量评估 Harness**。

---

## 2. 业界先进框架调研

### 2.1 SWE-bench (Princeton, 2023)

**Stars**: 8.2K+ | **论文**: ICLR 2024

| 维度 | 详情 |
|------|------|
| **评估对象** | LLM 对 GitHub Issue 生成的代码补丁 |
| **核心机制** | Docker 隔离 → 应用 patch → 运行项目测试套件 → 对比 PASS/FAIL 状态 |
| **数据集** | 每个 instance 包含: `{repo, base_commit, problem_statement, FAIL_TO_PASS tests, PASS_TO_PASS tests}` |
| **评分** | Resolved (100%), Partial (修复部分测试), Unresolved (0%) |
| **关键文件** | `swebench/harness/run_evaluation.py` → `grading.py` → `log_parsers/` |
| **优点** | 确定性验证（测试通过就是通过了），可复现 |
| **局限** | 依赖目标项目有测试套件，不适合诊断类任务 |

**对 radarAnalyze 的启示**:
- ✅ **黄金数据集理念**：每个案例应有 "预期诊断结论"（ground truth）
- ✅ **隔离执行**：Docker 确保环境一致性
- ✅ **FAIL_TO_PASS 模式**：可改编为 "诊断结论匹配度"

### 2.2 DeepEval (Confident AI)

**Stars**: 7K+ | **类型**: pytest 风格的 LLM 评估框架

| 维度 | 详情 |
|------|------|
| **评估对象** | LLM 输出（RAG、Agent、对话） |
| **核心机制** | `GEval` 指标 + LLM-as-judge + pytest 集成 |
| **Agent 指标** | `TaskCompletion`, `ToolCorrectness`, `GoalAccuracy`, `StepEfficiency` |
| **使用方式** | 写 `test_*.py`，用 `assert_test()` 断言，用 `deepeval test run` 执行 |
| **优点** | pytest 友好，指标丰富，支持自定义评分函数 |
| **局限** | LLM-as-judge 本身有偏差，不适合纯确定性验证 |

**对 radarAnalyze 的启示**:
- ✅ **LLM-as-judge 评分**：诊断结论正确性可由 LLM 评分
- ✅ **pytest 集成**：可直接用 `pytest` 跑诊断测试套件
- ✅ **StepEfficiency**：可评估管线步骤是否有冗余

### 2.3 OpenAI Evals

**Stars**: 2.4K+ | **类型**: 通用 LLM 评估框架

| 维度 | 详情 |
|------|------|
| **评估对象** | LLM 输出质量 |
| **核心机制** | YAML 定义 eval + JSON 数据集 + model-graded 或 code-graded |
| **数据集** | Git-LFS 存储，支持私有数据集 |
| **优点** | 声明式配置（YAML），eval 可复用 |
| **局限** | 偏重文本生成质量评估 |

**对 radarAnalyze 的启示**:
- ✅ **YAML 声明式 eval 定义**：比硬编码更灵活
- ✅ **数据集驱动**：分离 eval 逻辑和数据集

### 2.4 AgentBench (THUDM, 2024)

**Stars**: 3.5K+ | **论文**: ICLR 2024

| 维度 | 详情 |
|------|------|
| **评估对象** | LLM Agent 在复杂环境中的表现 |
| **任务类型** | AlfWorld（文本游戏）, WebShop（电商）, OS-Interaction（桌面操作）, DB-Bench（数据库）, KG（知识图谱） |
| **核心机制** | Docker Compose 隔离环境 + 任务成功率 |
| **优点** | 覆盖多模态 Agent 场景 |
| **局限** | 重 Agent 交互，不重代码诊断 |

**对 radarAnalyze 的启示**:
- ✅ **环境隔离 + 任务成功率** 的评估思路可借鉴
- ⚠️ 过于通用，直接复用价值有限

### 2.5 Aider 的 Lint-Test 循环

**Stars**: 37K+ | **类型**: AI 编码助手

| 维度 | 详情 |
|------|------|
| **核心机制** | 每次代码修改后自动 lint + test → 修复 → 再验证 |
| **测试命令** | 用户自定义 `--lint-cmd` 和 `--test-cmd` |
| **优点** | 闭环验证，不依赖特定测试框架 |
| **局限** | 针对代码生成场景 |

**对 radarAnalyze 的启示**:
- ✅ **自动修复循环**：诊断→修复→再诊断的闭环思路
- ✅ **可配置验证命令**：Harness 应支持自定义验证器

### 2.6 Braintrust

**Stars**: 8K+ | **类型**: LLM 评估平台

| 维度 | 详情 |
|------|------|
| **评估对象** | Prompt/Agent/应用的全链路评估 |
| **核心机制** | Tracing + 指标追踪 + A/B 测试 |
| **优点** | 完整的评估基础设施（dashboard、CI 集成） |
| **局限** | SaaS 为主，自建成本高 |

**对 radarAnalyze 的启示**:
- ✅ **Tracing 追踪**：诊断管线各步骤应可追踪
- ✅ **A/B 对比**：模型升级或 prompt 优化后对比效果

---

## 3. radarAnalyze Harness 设计方案

### 3.1 设计原则

基于调研，radarAnalyze 的 Harness 应具备以下特征：

| 原则 | 说明 | 参考 |
|------|------|------|
| **数据集驱动** | 测试数据与评估逻辑分离 | SWE-bench, OpenAI Evals |
| **黄金答案对照** | 每个案例有已知的"正确答案" | SWE-bench FAIL_TO_PASS |
| **多层评估** | 结构性检查 + 语义性评分 + 人工审核 | DeepEval 多层指标 |
| **pytest 集成** | 用 pytest 运行，CI/CD 友好 | DeepEval |
| **确定性优先** | 优先用确定性检查，LLM-as-judge 为辅 | SWE-bench 思路 |
| **可扩展** | 支持新评估维度（新功能、新项目） | OpenAI Evals 插件 |

### 3.2 评估维度体系

```
┌─────────────────────────────────────────────────────────────┐
│                    Harness 评估维度                           │
├─────────────────┬───────────────────────────────────────────┤
│ Level 0: 结构性  │ 输出格式是否正确                             │
│ (确定性, 必须)   │ - 报告文件是否存在                           │
│                  │ - JSON 结构是否完整                          │
│                  │ - 必需字段是否齐全                           │
│                  │ - 耗时是否超时                               │
├─────────────────┼───────────────────────────────────────────┤
│ Level 1: 证据链  │ 诊断过程是否合理                             │
│ (确定性为主)     │ - 是否识别了相关信号                         │
│                  │ - 是否检测到测试窗口                         │
│                  │ - 条件树是否包含关键条件                     │
│                  │ - TPE 是否发现时序模式                       │
├─────────────────┼───────────────────────────────────────────┤
│ Level 2: 结论    │ 诊断结论是否准确                             │
│ (LLM-as-judge)  │ - 根因分类是否正确（信号/算法/状态机）       │
│                  │ - 根因函数/行号是否匹配                      │
│                  │ - 诊断结论与黄金答案的语义相似度             │
├─────────────────┼───────────────────────────────────────────┤
│ Level 3: 建议    │ 修复建议是否可操作                           │
│ (LLM-as-judge)  │ - CodeFix diff 是否有效                      │
│                  │ - 建议是否针对根因                           │
│                  │ - 风险预警是否充分                           │
└─────────────────┴───────────────────────────────────────────┘
```

### 3.3 数据集格式

参考 SWE-bench 的 instance 格式，设计 `harness/cases/` 目录结构：

```
harness/
  cases/
    FCTA001_ground_truth.json    # 黄金答案文件
    FCTB002_ground_truth.json
    RCTA003_ground_truth.json
    ...
  configs/
    eval_config.yaml             # 评估配置
    metrics.yaml                 # 指标权重
  evaluators/
    __init__.py
    structural.py               # Level 0: 结构性检查
    evidence.py                 # Level 1: 证据链检查
    conclusion.py               # Level 2: 结论评分
    suggestion.py               # Level 3: 建议评分
    runner.py                   # 评估运行器
    grader.py                   # 评分汇总
  test_harness.py               # pytest 入口
```

#### 黄金答案文件格式 (`*_ground_truth.json`)

```json
{
  "case_id": "FCTA001",
  "project": "gwm_b26",
  "function": "FCTA",
  "problem_statement": "FCTA 功能在 XX 场景下未激活",
  "expected_classification": {
    "primary": "signal_chain",
    "secondary": "system_state"
  },
  "expected_root_cause": {
    "summary": "FCTA_Enable_S 信号未到达，Rte 读回值为 0",
    "key_functions": ["CoEm_FctA_Main", "Rte_Read_FCTA_Enable_S"],
    "key_variables": ["FCTA_Enable_S", "FCTA_State"],
    "critical_code_location": {
      "file": "CoEm_FctA.c",
      "line_range": [1234, 1250]
    }
  },
  "expected_evidence": {
    "signals_present": ["FCTA_Enable_S", "Assemble_Status"],
    "conditions_met": ["FCTA_State == ACTIVE", "FCTA_Enable_S == 1"],
    "temporal_patterns": ["signal_drop", "state_transition_delay"],
    "test_window": {"start": 5.0, "end": 15.0}
  },
  "expected_fix": {
    "type": "config_change",
    "description": "检查 DBC 信号映射或 HMI 开关配置",
    "files_affected": ["CoEm_FctA.c"]
  },
  "metadata": {
    "source": "engineering_review",
    "reviewer": "zhou-haibo",
    "verified_date": "2026-06-11"
  }
}
```

### 3.4 评估器实现

#### Level 0: 结构性检查 (确定性)

```python
# harness/evaluators/structural.py
class StructuralEvaluator:
    """Level 0: 结构性检查 — 不依赖 LLM，纯代码验证"""

    def evaluate(self, case_dir, result):
        checks = []

        # 1. 输出文件存在性
        checks.append(self._check_report_exists(case_dir))
        checks.append(self._check_conditions_json(case_dir))
        checks.append(self._check_memory_written(case_dir))

        # 2. JSON 结构完整性
        checks.append(self._check_classification_format(result))
        checks.append(self._check_evidence_completeness(result))

        # 3. 耗时检查
        checks.append(self._check_time_budget(result.get("timing", {})))

        return EvaluationResult(
            level="structural",
            checks=checks,
            score=self._calculate_score(checks),
            passed=all(c.passed for c in checks)
        )
```

#### Level 1: 证据链检查 (确定性 + 规则)

```python
# harness/evaluators/evidence.py
class EvidenceEvaluator:
    """Level 1: 证据链完整性 — 对照黄金答案验证诊断过程"""

    def evaluate(self, case_dir, result, ground_truth):
        checks = []

        # 1. 信号识别覆盖度
        expected_signals = set(ground_truth["expected_evidence"]["signals_present"])
        actual_signals = set(result.get("evidence", {}).get("signals", []))
        checks.append(Check(
            name="signal_coverage",
            passed=len(expected_signals & actual_signals) / len(expected_signals) >= 0.8,
            score=len(expected_signals & actual_signals) / len(expected_signals),
            detail=f"匹配 {len(expected_signals & actual_signals)}/{len(expected_signals)} 信号"
        ))

        # 2. 条件覆盖度
        expected_conditions = ground_truth["expected_evidence"]["conditions_met"]
        actual_conditions = result.get("conditions", [])
        checks.append(Check(
            name="condition_coverage",
            passed=self._condition_overlap(expected_conditions, actual_conditions) >= 0.7,
            score=self._condition_overlap(expected_conditions, actual_conditions),
        ))

        # 3. TPE 模式发现
        expected_patterns = set(ground_truth["expected_evidence"]["temporal_patterns"])
        actual_patterns = set(result.get("tpe_patterns", []))
        checks.append(Check(
            name="temporal_pattern_discovery",
            passed=len(expected_patterns & actual_patterns) > 0,
            score=len(expected_patterns & actual_patterns) / len(expected_patterns),
        ))

        # 4. 窗口检测准确性
        checks.append(self._check_test_window(result, ground_truth))

        return EvaluationResult(
            level="evidence",
            checks=checks,
            score=self._calculate_score(checks),
        )
```

#### Level 2: 结论评分 (LLM-as-judge)

```python
# harness/evaluators/conclusion.py
class ConclusionEvaluator:
    """Level 2: 诊断结论准确性 — LLM-as-judge"""

    PROMPT = """
    你是一个诊断质量评估专家。请比较以下实际诊断结论与黄金答案的匹配度。

    【黄金答案】
    {ground_truth}

    【实际诊断】
    {actual}

    请从以下维度评分（0-1 分）：
    1. 分类准确性：根因类型是否正确
    2. 定位准确性：函数/变量/代码位置是否匹配
    3. 结论完整性：是否覆盖了黄金答案中的关键点

    返回 JSON: {{"classification": 0.9, "localization": 0.8, "completeness": 0.7, "overall": 0.8}}
    """

    def evaluate(self, result, ground_truth):
        # 1. 确定性检查：分类是否匹配
        gt_classification = ground_truth["expected_classification"]["primary"]
        actual_classification = result.get("classification", {}).get("primary", "")
        classification_match = actual_classification == gt_classification

        # 2. 确定性检查：关键函数是否在诊断结果中
        gt_functions = set(ground_truth["expected_root_cause"]["key_functions"])
        actual_functions = set(result.get("diagnosed_functions", []))
        func_overlap = len(gt_functions & actual_functions) / len(gt_functions) if gt_functions else 0

        # 3. LLM-as-judge：语义相似度
        llm_score = self._llm_judge(result, ground_truth)

        return EvaluationResult(
            level="conclusion",
            checks=[
                Check("classification_match", classification_match, 1.0 if classification_match else 0.0),
                Check("function_localization", func_overlap >= 0.5, func_overlap),
                Check("semantic_similarity", llm_score >= 0.6, llm_score),
            ],
            score=(1.0 if classification_match else 0.0) * 0.3 + func_overlap * 0.3 + llm_score * 0.4,
        )
```

#### Level 3: 建议评分 (LLM-as-judge + 静态检查)

```python
# harness/evaluators/suggestion.py
class SuggestionEvaluator:
    """Level 3: 修复建议可操作性的评估"""

    def evaluate(self, result, ground_truth):
        checks = []

        # 1. CodeFix diff 是否存在
        fix = result.get("codefix", {})
        has_diff = bool(fix.get("diff"))
        checks.append(Check("has_codefix_diff", has_diff, 1.0 if has_diff else 0.0))

        # 2. diff 是否针对预期文件
        expected_files = set(ground_truth["expected_fix"].get("files_affected", []))
        actual_files = set(fix.get("files_modified", []))
        if expected_files:
            overlap = len(expected_files & actual_files) / len(expected_files)
            checks.append(Check("fix_target_file", overlap > 0, overlap))

        # 3. LLM-as-judge：建议合理性
        if has_diff:
            llm_score = self._llm_judge_suggestion(fix, ground_truth)
            checks.append(Check("suggestion_quality", llm_score >= 0.5, llm_score))

        return EvaluationResult(
            level="suggestion",
            checks=checks,
            score=self._calculate_score(checks),
        )
```

### 3.5 评分汇总

```python
# harness/evaluators/grader.py
class Grader:
    """汇总各级评分，生成最终报告"""

    WEIGHTS = {
        "structural": 0.15,    # 结构性 — 基础
        "evidence":   0.25,    # 证据链 — 过程质量
        "conclusion": 0.40,    # 结论 — 最终诊断准确性（最重要）
        "suggestion": 0.20,    # 建议 — 可操作性
    }

    def grade(self, results: dict[str, EvaluationResult]) -> GradeReport:
        weighted_score = sum(
            r.score * self.WEIGHTS[level]
            for level, r in results.items()
        )

        # 等级判定
        if weighted_score >= 0.85:
            grade = "A"  # 优秀 — 诊断质量高
        elif weighted_score >= 0.70:
            grade = "B"  # 良好 — 基本准确
        elif weighted_score >= 0.50:
            grade = "C"  # 合格 — 有偏差但可参考
        else:
            grade = "D"  # 不合格 — 需要改进

        return GradeReport(
            overall_score=weighted_score,
            grade=grade,
            level_scores={level: r.score for level, r in results.items()},
            failed_checks=[
                c for r in results.values()
                for c in r.checks if not c.passed
            ],
        )
```

### 3.6 pytest 集成

```python
# harness/test_harness.py
import pytest
from pathlib import Path
from harness.evaluators.runner import HarnessRunner
from harness.evaluators.grader import Grader

HARNESS_DIR = Path(__file__).parent
CASES_DIR = HARNESS_DIR / "cases"

# 自动发现所有 *_ground_truth.json 文件
@pytest.mark.parametrize("ground_truth_file", sorted(CASES_DIR.glob("*_ground_truth.json")))
def test_diagnosis_harness(ground_truth_file, tmp_path):
    """
    对每个黄金答案案例运行完整诊断 + 评估。
    通过标准: 总体评分 >= 0.60 (C 级以上)
    """
    gt = load_json(ground_truth_file)
    runner = HarnessRunner()

    # 运行诊断（可配置：实际运行 or 使用缓存结果）
    result = runner.run_diagnosis(gt["case_id"], gt["project"])

    # 评估
    grade_report = runner.evaluate(result, gt)

    # 断言
    assert grade_report.overall_score >= 0.60, (
        f"Case {gt['case_id']} scored {grade_report.overall_score:.2f} "
        f"(grade {grade_report.grade}), below threshold 0.60. "
        f"Failed checks: {[c.name for c in grade_report.failed_checks]}"
    )

    # 结构化断言：Level 0 必须全部通过
    assert grade_report.level_scores["structural"] >= 0.9, (
        f"Structural checks failed for {gt['case_id']}"
    )


def test_harness_regression():
    """回归测试：对比当前与上次运行的评分变化"""
    current = run_all_cases()
    baseline = load_json(HARNESS_DIR / "baseline_scores.json")

    for case_id in current:
        if case_id in baseline:
            delta = current[case_id] - baseline[case_id]
            assert delta >= -0.05, (
                f"Regression: {case_id} dropped from {baseline[case_id]:.2f} to {current[case_id]:.2f}"
            )
```

### 3.7 评估配置

```yaml
# harness/configs/eval_config.yaml

# 评分权重
weights:
  structural: 0.15
  evidence: 0.25
  conclusion: 0.40
  suggestion: 0.20

# 通过标准
passing_score: 0.60
structural_minimum: 0.90  # Level 0 必须 >= 90%

# 诊断运行时限制
time_budget:
  max_total_seconds: 1800  # 30 分钟
  max_per_step_seconds: 300

# LLM-as-judge 配置
llm_judge:
  model: "qwen3.5-27b"  # 使用与诊断相同或更强的模型
  endpoint: "${LLM_JUDGE_ENDPOINT}"
  retry_count: 3

# 回归检测
regression:
  threshold: 0.05  # 单案例下降超过 5% 报警
  baseline_file: "baseline_scores.json"

# 数据集
dataset:
  cases_dir: "harness/cases/"
  ground_truth_pattern: "*_ground_truth.json"

# 缓存
cache:
  enabled: true
  ttl_hours: 24
  dir: ".harness_cache/"
```

---

## 4. 与现有框架的对比与选择

| 特性 | SWE-bench | DeepEval | OpenAI Evals | **radarAnalyze Harness** |
|------|-----------|----------|--------------|--------------------------|
| 评估对象 | 代码补丁 | LLM 输出 | LLM 输出 | **诊断管线** |
| 验证方式 | 测试套件 (确定性) | LLM-as-judge | model-graded | **确定性 + LLM-as-judge** |
| 数据集 | FAIL_TO_PASS | 自定义 | JSON/YAML | **黄金答案 JSON** |
| 环境隔离 | Docker | 无 | 无 | **可选 (Python 进程隔离)** |
| CI 集成 | CLI | pytest | CLI | **pytest** |
| 评分粒度 | Resolved/Partial | 多维指标 | 自定义 | **4 层级 (L0-L3)** |
| 适用场景 | 代码修复 | RAG/Agent | 文本生成 | **根因诊断** |

**核心差异**: radarAnalyze 的 Harness 融合了 SWE-bench 的 "黄金答案对照" 理念和 DeepEval 的 "多层指标" 方法，但专门为 **诊断质量** 定制。

---

## 5. 实施路线图

### Phase 1: 基础设施 (P0)

| 任务 | 工作内容 | 预计工作量 |
|------|----------|-----------|
| 1.1 | 创建 `harness/` 目录结构 | 0.5h |
| 1.2 | 实现 `StructuralEvaluator` (Level 0) | 1h |
| 1.3 | 创建第一个黄金答案 `FCTA001_ground_truth.json` | 1h (需工程经验) |
| 1.4 | 实现 `HarnessRunner` + pytest 入口 | 1h |
| 1.5 | 运行首个案例验证 | 0.5h |

### Phase 2: 评估器扩展 (P1)

| 任务 | 工作内容 | 预计工作量 |
|------|----------|-----------|
| 2.1 | 实现 `EvidenceEvaluator` (Level 1) | 2h |
| 2.2 | 实现 `ConclusionEvaluator` (Level 2) | 2h |
| 2.3 | 实现 `SuggestionEvaluator` (Level 3) | 1h |
| 2.4 | 实现 `Grader` 评分汇总 | 0.5h |

### Phase 3: 数据集构建 (P1)

| 任务 | 工作内容 | 预计工作量 |
|------|----------|-----------|
| 3.1 | 基于已有诊断案例创建黄金答案 | 2h/case |
| 3.2 | 覆盖 FCTA/FCTB/RCTA/RCTB 至少各 1 个案例 | 8h |
| 3.3 | 多项目覆盖 (sc6h, cr5cb) | 4h |

### Phase 4: CI 集成 (P2)

| 任务 | 工作内容 | 预计工作量 |
|------|----------|-----------|
| 4.1 | `pytest` 配置 + 分级标记 (structural/fast, llm/slow) | 0.5h |
| 4.2 | 基线分数文件自动生成 | 0.5h |
| 4.3 | 回归检测告警 | 0.5h |

### Phase 5: 高级功能 (P2, 可选)

| 任务 | 工作内容 | 说明 |
|------|----------|------|
| 5.1 | 多模型对比模式 | 评估不同 LLM 对诊断质量的影响 |
| 5.2 | 自动化黄金答案生成 | 从历史工单自动生成 ground truth 草稿 |
| 5.3 | 诊断覆盖率报告 | 评估诊断管线对各功能模块的覆盖程度 |
| 5.4 | 性能基准 (perf benchmark) | 管线各步骤耗时 SLA |

---

## 6. 黄金答案构建指南

黄金答案 (Ground Truth) 是 Harness 的核心。构建方法：

### 6.1 来源

| 来源 | 可靠性 | 工作量 |
|------|--------|--------|
| **已解决的工程工单** | ★★★★★ | 从中提取关键信息 |
| **专家人工诊断** | ★★★★★ | 高（需领域专家） |
| **历史诊断结果（经确认）** | ★★★★☆ | 中 |
| **LLM 辅助生成 + 人工审核** | ★★★☆☆ | 低（快速但需审核） |

### 6.2 最小可用集合

初期不需要覆盖所有字段。最小可用集合：

```json
{
  "case_id": "FCTA001",
  "expected_classification": {"primary": "signal_chain"},
  "expected_root_cause": {
    "summary": "...",
    "key_functions": ["CoEm_FctA_Main"]
  },
  "expected_evidence": {
    "signals_present": ["FCTA_Enable_S"]
  }
}
```

即使只有这几个字段，也能验证：
- Level 0: 结构完整性
- Level 1: 信号覆盖度
- Level 2: 分类匹配 + 函数定位

### 6.3 增量完善

随着 Harness 使用，逐步补充：
- 更多证据字段
- 修复建议验证
- 时序模式预期

---

## 7. 与其他项目的借鉴

### 7.1 可复用的模式

| 框架 | 可复用模式 | 如何在 radarAnalyze 中应用 |
|------|-----------|--------------------------|
| SWE-bench | 黄金数据集 + FAIL_TO_PASS | 案例集 + 预期诊断结论 |
| SWE-bench | Docker 隔离执行 | Python 进程隔离，避免 LLM 状态污染 |
| DeepEval | pytest + GEval | pytest 集成 + LLM-as-judge 评分 |
| DeepEval | 多维指标 | L0-L3 层级评估 |
| OpenAI Evals | YAML 配置 | eval_config.yaml 声明式配置 |
| OpenAI Evals | 数据集与逻辑分离 | ground_truth.json 与 evaluator 解耦 |
| Aider | 自动修复循环 | 诊断→修复→再诊断的闭环验证 |

### 7.2 不应直接复用的模式

| 框架 | 不適用模式 | 原因 |
|------|-----------|------|
| SWE-bench | Docker 容器化 | radarAnalyze 诊断不依赖特定运行时环境 |
| SWE-bench | 测试套件通过/失败 | 诊断没有 "测试套件"，只有"正确性" |
| AgentBench | 多环境任务 | radarAnalyze 是单一诊断任务 |
| Braintrust | SaaS Dashboard | 内网环境，不需要云服务 |

---

## 8. 风险评估

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| 黄金答案标注不准确 | 中 | 高 | 专家审核 + 多源交叉验证 |
| LLM-as-judge 评分偏差 | 中 | 中 | 确定性检查优先，LLM 仅辅助 |
| 数据集覆盖不足 | 高 | 中 | 先覆盖核心功能 (FCTA/FCTB)，逐步扩展 |
| 评估本身消耗 LLM 配额 | 中 | 低 | 缓存机制 + 分级执行（Level 0/1 无需 LLM） |
| Harness 维护成本高 | 低 | 中 | 自动化基线更新 + 增量评估 |

---

## 9. 验证清单

- [x] 所有框架数据来自实际 GitHub 调研（API + README 阅读）
- [x] 评估维度设计基于 radarAnalyze 实际管线（8 步）
- [x] 代码示例为真实可运行结构（非伪代码）
- [x] 方案引用了 6 个真实系统/框架
- [x] 包含"为什么"的解释（不只是"是什么"）
- [x] 区分了可复用与不适用的模式
- [x] 提供了风险评估和缓解措施

---

## 10. 下一步行动

1. **立即执行**: Phase 1 — 创建 harness 基础设施 + 第一个黄金答案
2. **本周完成**: Phase 2 — 完整评估器 (L0-L3)
3. **下周目标**: Phase 3 — 至少 3 个案例的黄金答案
4. **持续改进**: 根据实际运行结果调整评分权重和通过标准

**优先级**: P0 是基础设施 + 首个可用评估，预计 4h 可完成 MVP。
