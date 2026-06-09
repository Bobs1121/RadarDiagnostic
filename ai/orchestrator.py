# -*- coding: utf-8 -*-
"""
Qwen3.5-driven task orchestrator.
The AI brain that plans, dispatches, and coordinates all analysis work.
Users only provide: problem + expected result. Everything else is automatic.

V2: Window detection + condition extraction pipeline.
"""
import json
import datetime
import re as _re
from pathlib import Path
from .model_router import ModelRouter
from .code_learner import CodeLearner
from .frame_analyzer import FrameAnalyzer
from .expert_panel_langgraph import ExpertPanel
from .test_window_detector import TestWindowDetector, format_windows
from .condition_extractor import ConditionExtractor, format_conditions
from .problem_classifier import ProblemClassifier, ClassificationResult
from .parameter_analyzer import (
    analyze_sensitivity, render_sensitivity_markdown,
    render_what_if_markdown, what_if,
)
from .visualizer import build_report as build_html_report
from .utils import parse_json_from_llm, ALL_FUNCTIONS
from .context_budget import ContextBudget
from .data_probe import DataProbe
from .variable_query_planner import VariableQueryPlanner, render_probe_results_for_prompt
from .fallback import safe_llm_call, fallback_understand, fallback_expert_panel
from .observability import StepLogger, TokenTracker, ObservableStatus


def _signal_overlap_ok(hint: str, candidate: str, min_ratio: float = 0.45) -> bool:
    """Verify fuzzy match shares enough semantic tokens with the original hint."""
    def _tokens(s: str) -> set[str]:
        parts = _re.findall(r'[A-Z][a-z]+|[A-Z]+(?=[A-Z][a-z])|[a-z]+|[A-Z]+', s)
        parts += s.replace("_", " ").split()
        return {p.lower() for p in parts if len(p) >= 2}

    h_tok = _tokens(hint)
    c_tok = _tokens(candidate)
    if not h_tok or not c_tok:
        return False
    overlap = len(h_tok & c_tok)
    return overlap / max(len(h_tok), len(c_tok)) >= min_ratio

ORCHESTRATOR_SYSTEM = """你是角雷达(Corner Radar)问题分析系统的任务调度器。
你的职责是理解用户报告的问题，规划分析步骤，调度子任务，并整合最终诊断报告。

你管理的ADAS功能: BSD, LCA, DOW, RCW, RCTA, RCTB, FCTA, FCTB

系统架构知识:
- 两套并行状态机: adasFunc.c(感知侧) + ASWIN_SystemState.c(平台侧)
- 两者共享全局状态变量(*SystemState), 调度顺序决定最终值
- 左右雷达从属: 右雷达(RR/FR)为公CAN出口, 左雷达(RL/FL)经私CAN向右侧传送
- 信号链路: 公CAN→RteComMapping→内部变量→adasFunc/ASWIN_SystemState→ASWOUT_OutCalc→输出

任务复杂度判断规则:
- simple(交给Gemma4): 单信号查询、数据格式化、简单摘要、变量值查找
- complex(自己处理/专家面板): 多变量关联分析、状态机推理、根因诊断、因果链推断

输出使用中文，技术术语保留英文。"""


class Orchestrator:
    """
    The AI orchestrator that automates the full diagnosis pipeline.
    Users only need to provide problem description and expected result.
    """

    def __init__(self, config: dict, project_root: Path):
        self.config = config
        self.project_root = project_root
        self.router = ModelRouter(config)

        from memory.memory_system import MemorySystem
        self.memory = MemorySystem(project_root)

        self._last_tpe_result = None

    def run_diagnosis(
        self,
        case_dir: Path,
        problem: str,
        expected: str,
        on_status=None,
    ) -> str:
        """
        Full automated diagnosis pipeline. Returns path to report.

        Pipeline:
          Phase 0   — Ensure source docs
          Phase 1   — Understand problem
          Phase 2   — Parse data
          Phase 2.5 — Detect test windows
          Phase 3   — Extract evidence (window-aware)
          Phase 3.5 — Extract conditions from source code
          Phase 3.55 — Temporal Pattern Engine (TPE) causal alignment  [NEW]
          Phase 3.57 — Variable Query Probe (LLM plans, DataProbe executes)
          Phase 3.6 — External suppression signal check
          Phase 3.7 — Output signal analysis
          Phase 4   — Expert panel diagnosis
          Phase 4.5 — CodeFixEngine: generate unified diffs for fixes     [NEW]
          Phase 5   — Report + memory
        """
        def status(step, detail=""):
            if on_status:
                on_status(step, detail)

        # P1.4: Observability — wrap status with step logging
        step_logger = StepLogger()
        token_tracker = TokenTracker()
        obs_status = ObservableStatus(on_status, step_logger)

        # ── Phase 0: Ensure prerequisites ────────────────────────────────
        status("init", "Checking prerequisites...")
        self._ensure_source_docs(status)

        # ── Phase 1: Understand the problem ──────────────────────────────
        status("understand", "AI is understanding the problem...")
        session_id = self.memory.create_session(case_dir.name, problem, expected)
        func_info = safe_llm_call(
            "understand",
            lambda **kw: self._understand_problem(kw.get("problem", ""), kw.get("expected", ""), kw.get("case_dir")),
            fallback_kwargs={},
            problem=problem,
            expected=expected,
            case_dir=case_dir,
        )
        func_name = func_info.get("function", "UNKNOWN")
        self.memory.log_step(session_id, "understand", func_info)
        status("understand", f"Identified function: {func_name}")

        # ── Phase 1.5: Classify task type (diagnose / tune / verify / query)
        status("classify", "Classifying task type...")
        classifier = ProblemClassifier(router=self.router)
        classification = classifier.classify(
            problem=problem, expected=expected,
            memory_hint=self.memory.build_context_for_diagnosis(
                func_name, problem, case_dir,
            ),
        )
        if classification.target_function and classification.target_function != "UNKNOWN":
            if func_name == "UNKNOWN" or classification.confidence >= 0.8:
                func_name = classification.target_function
        task_type = classification.task_type
        status(
            "classify",
            f"task_type={task_type} func={func_name} "
            f"focus={','.join(classification.focus_parameters) or '-'} "
            f"(conf={classification.confidence:.2f})",
        )
        self.memory.log_step(session_id, "classify", classification.to_dict())

        # ── Phase 2: Parse data ──────────────────────────────────────────
        status("parse", "Parsing data files...")
        store, bag_meta, blf_meta, sync = self._parse_case_data(case_dir, status)
        parse_summary = {
            "bag_frames": bag_meta.get("message_count") if bag_meta else 0,
            "can_frames": blf_meta.get("message_count") if blf_meta else 0,
        }
        self.memory.log_step(session_id, "parse", parse_summary)

        # ── Phase 2.5: Detect test windows ───────────────────────────────
        status("detect_window", "Detecting test-active time windows...")
        detector = TestWindowDetector()
        speed_thresholds = self._collect_speed_thresholds(func_name)
        # de-duplicate for pretty-printing; the detector already dedupes internally
        unique_thresholds = sorted({round(float(v), 3) for v in speed_thresholds}) if speed_thresholds else []
        if unique_thresholds:
            status("detect_window",
                   f"Using per-func speed thresholds for {func_name}: "
                   f"{', '.join(f'{t:g}' for t in unique_thresholds)} km/h")
        windows = detector.detect(store, func_name,
                                  speed_thresholds=speed_thresholds or None)
        if windows:
            window_desc = "; ".join(
                f"[{w.t_start:.1f}s~{w.t_end:.1f}s] {w.trigger_reason}"
                for w in windows
            )
            status("detect_window", f"Found {len(windows)} window(s): {window_desc}")
        else:
            status("detect_window", "No windows detected, using full data")
        self.memory.log_step(session_id, "windows", {
            "count": len(windows),
            "windows": [
                {"t_start": w.t_start, "t_end": w.t_end, "reason": w.trigger_reason}
                for w in windows
            ],
        })

        # ── Phase 3: Data evidence extraction (window-aware) ─────────────
        status("analyze", f"Extracting evidence for {func_name} within windows...")
        var_path = self.project_root / "source_docs" / "variables.json"
        analyzer = FrameAnalyzer(self.router, var_path if var_path.exists() else None)
        frame_analysis = self._run_frame_analysis_with(analyzer, store, func_name, func_info, status)

        status("analyze", "Extracting target speeds, CAN values, ego speed (windowed)...")
        evidence = analyzer.extract_evidence(store, func_name, windows=windows or None)
        self.memory.log_step(session_id, "evidence", {
            "keys": list(evidence.keys()),
            "key_facts": evidence.get("KEY_FACTS", "")[:500],
            "window_count": len(windows),
            "transition_count": len(evidence.get("state_transitions", [])),
        })

        # ── Phase 3.5: Extract activation conditions from source ─────────
        status("conditions", f"Extracting {func_name} activation conditions from code...")
        cond_extractor = ConditionExtractor(self.router, self.project_root, self.config)
        conditions = cond_extractor.extract(func_name)
        conditions_text = format_conditions(conditions)
        if "error" not in conditions:
            status("conditions", f"Extracted conditions (cached to source_docs/{func_name}_conditions.json)")
        else:
            status("conditions", f"Condition extraction: {conditions.get('error', '?')}")
        self.memory.log_step(session_id, "conditions", {
            "has_conditions": "error" not in conditions,
            "preview": conditions_text[:300],
        })

        # ── Phase 3.55: Temporal Pattern Engine causal alignment ─────────
        status("tpe", "Running Temporal Pattern Engine...")
        tpe_text, tpe_report = self._run_tpe(
            store, evidence, func_name, windows, status,
        )
        if tpe_report:
            FrameAnalyzer.append_tpe_block(evidence, tpe_text, tpe_report)
            self.memory.log_step(session_id, "tpe", {
                "pattern_count": tpe_report.get("pattern_count", 0),
                "triggered_count": tpe_report.get("triggered_count", 0),
                "unresolved_variables": tpe_report.get("unresolved_count", 0),
                "missing_can_signals": tpe_report.get("missing_can_count", 0),
                "has_triggers": tpe_report.get("triggered_count", 0) > 0,
            })

        # ── Phase 3.56: Numeric constants table (global, cross-function) ──
        # 把 auto-dream 学到的 `EGOCARWIDTH=1.976`、`LineBSDLCAL=-4.288` 这类
        # 具体数字加进 Expert Panel 的可见上下文，让专家不再用"约 ±3.3m" 这种
        # 猜测阈值，而是能做真数值对比。Planner 也会用这张表（见 Phase 3.57）。
        constants_section = ""
        try:
            constants_section = self.memory.render_constants_for_context(
                func_name, max_chars=2000,
            )
        except Exception as e:  # noqa: BLE001
            status("constants", f"Load constants failed: {e}")
        if not constants_section:
            # 友好提示：告诉专家"没学过就不给，别乱猜"
            constants_section = (
                "## 已学数值常量（全局）\n"
                "_暂无常量表 — 请运行 `python cli.py --learn-constants`。_\n"
                "_在此之前，遇到 ROI/阈值相关判定时请明确标注"
                "'阈值未知、不做数值判断'，不要用经验值猜。_"
            )

        # ── Phase 3.57: Variable Query Probe (dynamic evidence gathering) ──
        # Let the LLM decide which variables/expressions to probe for *this*
        # specific problem, then run those queries over the SQLite store. This
        # breaks the "we only see what we hard-coded" trap: e.g. when a case
        # is actually caused by `objectRightCutIn = dist_y + 0.25 * width`
        # exceeding an ROI threshold, the planner can ask for that exact
        # derived statistic without anyone wiring it in.
        probe_section = ""
        probe_plans: list = []
        probe_results: list = []
        probe_cfg = (self.config.get("ai", {}) or {}).get("variable_probe", {}) or {}
        probe_enabled = probe_cfg.get("enabled", True)
        if probe_enabled and store is not None:
            try:
                status("probe", "Planning variable queries based on problem + L6 knowledge...")
                planner = VariableQueryPlanner(self.router, self.memory, self.project_root)
                probe_plans = planner.plan(
                    problem=problem,
                    expected=expected,
                    func_name=func_name,
                    fail_type=func_info.get("fail_type", "OTHER"),
                    focus_params=list(classification.focus_parameters or []),
                    store=store,
                    max_queries=int(probe_cfg.get("max_queries", 6)),
                    use_thinking=bool(probe_cfg.get("use_thinking", False)),
                )
                if probe_plans:
                    status("probe", f"Executing {len(probe_plans)} probe queries...")
                    probe = DataProbe(store, windows=windows or [])
                    for qp in probe_plans:
                        try:
                            probe_results.append(probe.query(**qp.to_query_args()))
                        except Exception as e:
                            probe_results.append({
                                "field": qp.field, "table": qp.table,
                                "row_count": 0, "error": f"probe exec error: {e}",
                            })
                    probe_section = render_probe_results_for_prompt(
                        probe_plans, probe_results,
                        max_chars=int(probe_cfg.get("max_chars", 6000)),
                    )
                    self.memory.log_step(session_id, "variable_probe", {
                        "plan_count": len(probe_plans),
                        "plans": [p.to_dict() for p in probe_plans],
                        "result_preview": probe_section[:500],
                    })
            except Exception as e:
                status("probe", f"Variable probe skipped: {e}")

        # ── Phase 3.6: External suppression signal check ─────────────────
        suppression_text = ""
        suppression_signals = conditions.get("external_suppression", [])
        if suppression_signals and store.get_can_ids():
            status("suppression", f"Checking {len(suppression_signals)} external suppression signals in CAN data...")
            suppression_text = self._check_suppression_signals(
                store, suppression_signals, windows, func_name, status,
            )
            self.memory.log_step(session_id, "suppression_check", {
                "signal_count": len(suppression_signals),
                "result_preview": suppression_text[:500],
            })
        elif suppression_signals:
            status("suppression", "No CAN data available for suppression check")

        # ── Phase 3.7: Output signal analysis (brake/warning/TTC on CAN) ──
        output_signal_text = ""
        if store.get_can_ids():
            status("output_signals", f"Analyzing output signals for {func_name} from BLF...")
            output_signal_text = self._analyze_output_signals(
                store, func_name, windows, status,
            )
            if output_signal_text:
                self.memory.log_step(session_id, "output_signal_analysis", {
                    "result_preview": output_signal_text[:500],
                })

        # ── Phase 3.8: Load authoritative threshold reference ────────────
        threshold_ref = self._load_threshold_reference(func_name)

        # ── Phase 3.9: Parameter sensitivity (tune/verify path) ────────────
        param_section_md = ""
        param_report_obj = None
        whatif_entries: list = []
        if task_type in ("tune", "verify"):
            try:
                status("params", "Scanning ADAS thresholds and running sensitivity analysis...")
                param_report_obj = analyze_sensitivity(
                    source_root=Path(self.config["paths"]["source_code"]),
                    cache_dir=self.project_root / "source_docs",
                    store=store,
                    func_name=func_name,
                    focus_categories=classification.focus_parameters or None,
                )
                param_section_md = render_sensitivity_markdown(param_report_obj)
                status(
                    "params",
                    f"Parameters scanned: {param_report_obj.total_parameters}, "
                    f"observable: {param_report_obj.parameters_analyzed}",
                )
                self.memory.log_step(session_id, "param_sensitivity", {
                    "func": param_report_obj.func,
                    "total": param_report_obj.total_parameters,
                    "analyzed": param_report_obj.parameters_analyzed,
                })

                proposals = self._parse_proposals(problem, expected, param_report_obj)
                if proposals:
                    whatif_entries = what_if(
                        param_report_obj, proposals=proposals, store=store,
                    )
                    if whatif_entries:
                        status(
                            "params",
                            f"What-if evaluation: {len(whatif_entries)} proposal(s) evaluated",
                        )
                        self.memory.log_step(session_id, "param_whatif", {
                            "count": len(whatif_entries),
                            "items": [w.to_dict() for w in whatif_entries[:20]],
                        })
            except Exception as exc:
                status("params", f"Parameter analysis failed: {exc}")
                param_section_md = ""

        # ── CodeGraph: inject structured code context into expert panel ──
        # render_for_expert_panel 已经包含：模块函数/信号/调用链 + 校准参数 +
        # 跨模块共享函数/信号 + 构建信息。注入到 ContextBudget 让所有专家可见。
        codegraph_section = ""
        try:
            from .codegraph import CodeGraph, CodeGraphRenderer
            cg_path = self.project_root / "memory" / "codegraph.db"
            if cg_path.exists():
                cg = CodeGraph(cg_path)
                renderer = CodeGraphRenderer(cg)
                cg_md = renderer.render_for_expert_panel(
                    module=func_name,
                    problem_desc=problem,
                    max_chars=10000,
                )
                if cg_md:
                    codegraph_section = f"""## ★★ 代码结构知识图谱(CodeGraph) ★★
{cg_md}

**CodeGraph 使用说明**: 以上为系统从 C 源码静态分析提取的结构化代码知识，
包括函数调用链、信号依赖、变量读写、状态转换等行为模式。分析根因时请结合
TPE 证据段与 CodeGraph 结构数据交叉验证。
"""
                cg.close()
        except Exception:
            pass  # silent fallback — CodeGraph is optional enhancement

        # ── Phase 4: Expert Panel Diagnosis ──────────────────────────────
        n_experts = len(ExpertPanel.select_experts(func_info.get("fail_type", "OTHER")))
        status("diagnose", f"Launching expert panel ({n_experts} experts, 3 rounds)...")
        memory_context = self.memory.build_context_for_diagnosis(func_name, problem, case_dir)
        data_summary = self._build_data_summary(store, bag_meta, blf_meta, sync)

        key_facts = evidence.pop("KEY_FACTS", "")
        timeline = evidence.pop("timeline", [])
        transitions = evidence.pop("state_transitions", [])
        evidence.pop("tpe_block", None)
        evidence.pop("tpe_report", None)

        evidence_text = json.dumps(evidence, ensure_ascii=False, default=str, indent=1)
        if len(evidence_text) > 20000:
            evidence_text = evidence_text[:20000] + "\n... (truncated)"

        timeline_text = FrameAnalyzer.format_timeline(timeline, max_lines=300, func_name=func_name)
        windows_text = format_windows(windows)

        transitions_text = ""
        if transitions:
            lines = [f"  t={tr['t']}s {tr['side']} {tr['field']}: {tr['from']}→{tr['to']}"
                     for tr in transitions[:30]]
            transitions_text = "\n".join(lines)
        else:
            transitions_text = "(无状态跳变)"

        tpe_section = ""
        tpe_block = evidence.get("tpe_block") or ""
        if tpe_block:
            tpe_section = f"""
## ★★★ 代码模式 × 数据时序 因果对齐 (TPE,最高优先级) ★★★
{tpe_block}

**TPE 规则**: 以上证据由系统从 C 源码自动抽取的行为模式 (HoldRelease/
Accumulate/Hysteresis/Debounce/EdgeTrigger 等) 与实际 BAG/BLF 信号的
时序特征 (边沿/段/短脉冲/持续时长) 进行因果对齐得出。
分析根因时请优先参考 TPE 证据段:
1. **已触发模式** — 代码中存在会导致当前现象的行为，且 BAG/BLF 中确实
   记录到了触发窗口；这是"时序耦合"类 Bug 最可能的根因。
2. **未触发模式** — 模式存在于代码，但数据中未满足触发条件；可作为
   反向证据排除某些假设。
3. **无法判定** — 变量未能映射到 CAN 信号，需补充 signal_mapping 或
   variable_chains，**不得**把"无法判定"当成"未触发"。
专家禁止在没有阅读 TPE 段的情况下输出根因结论。
"""

        suppression_section = ""
        if suppression_text:
            suppression_section = f"""
## ★★★ 外部抑制信号实测(最高优先级) ★★★
{suppression_text}

**数据溯源规则**: 以上为系统从BLF/BAG中实际提取并验证的抑制信号状态。
专家分析时**必须以上述实测数据为准**，不得自行从其他数据源推断抑制信号状态。
如某信号标注"未在BLF中找到"，结论应为"无法确认"而非自行查找替代信号。
"""
        output_section = ""
        if output_signal_text:
            has_brake = func_name.upper() in {"FCTB", "RCTB"}
            if has_brake:
                note_line = (
                    "**说明**: 以上为CAN总线上实际输出信号的时间序列分析，直接反映系统的"
                    "制动请求、警告状态和TTC计算结果。分析**制动是否执行、保压时长、"
                    "制动幅值**等问题时**必须参考此数据**。"
                )
                header = "## ★★ 输出信号实测(制动/警告/TTC) ★★"
            else:
                note_line = (
                    "**说明**: 以上为CAN总线上实际输出信号的时间序列分析，反映**报警"
                    "触发、状态跳变、TTC**等信息。本功能无制动输出，分析报警是否触发、"
                    "触发时机/时长等问题时**必须参考此数据**。"
                )
                header = "## ★★ 输出信号实测(报警/状态/TTC) ★★"
            output_section = f"""
{header}
{output_signal_text}

{note_line}
"""

        threshold_section = ""
        if threshold_ref:
            threshold_section = f"""
## ★★ 权威阈值参考(来自source_docs/{func_name}.md) ★★
{threshold_ref}

**规则**: 报告中引用的所有阈值必须与上述文档一致。禁止使用"预估"阈值。
"""

        params_section = ""
        if param_section_md:
            whatif_md = render_what_if_markdown(whatif_entries) if whatif_entries else ""
            params_section = f"""
## ★★ 参数敏感性分析(tune/verify 专属) ★★
任务类型: **{task_type}** — 分析目标不是根因，而是参数调整后的量化影响。
{param_section_md}

{whatif_md}

**规则**: 本节所有数值均为系统从源码+本次录制直接计算得到。
建议调优时必须基于上表中"穿越次数"、"min |Δ|"、"超阈值帧数"几列做判断，
禁止仅凭直觉给方向；若提出新的阈值值，需指明该值在本次录制中的新穿越次数。
"""

        # ── Expert Panel prompt assembly with global budget ────────────────
        # Assemble pieces into a ContextBudget so the total prompt stays
        # bounded even when individual sections are all near their limits.
        methodology_block = """## ★★★ 因果链分析方法论(最高优先级) ★★★
分析时必须区分数据的因果层次:
- **观测层**(雷达端radar_objects/radar_debug): 仅说明「发生了什么」，是ECU决策的**结果**
- **代码逻辑层**(adasFunc.c/ASWIN_SystemState.c): 说明「为什么发生」
- **信号输入层**(RteComMapping.c→CAN信号): 说明「什么触发了代码逻辑」
根因 = 信号输入层或代码逻辑层的具体问题。**禁止将观测层的状态直接作为根因。**
追溯方法: 看到异常状态 → 查代码中哪行赋值了此状态 → 该赋值依赖哪个变量/条件 → 该变量来自哪个CAN信号 → CAN信号实际值是什么"""

        budget = ContextBudget(total_chars=60_000)
        # Priorities: higher = keep more of it when we need to trim.
        budget.add("methodology",   methodology_block, priority=100, min_chars=400)
        budget.add("key_facts",     f"## ★ 关键事实(必读) ★\n{key_facts}", priority=100, min_chars=2000)
        budget.add("tpe",           tpe_section,       priority=95,  min_chars=2000)
        budget.add("constants",     constants_section, priority=94,  min_chars=800)
        budget.add("probe",         probe_section,     priority=93,  min_chars=1500)
        budget.add("suppression",   suppression_section, priority=92, min_chars=1000)
        budget.add("output",        output_section,    priority=90,  min_chars=1500)
        budget.add("windows",       f"## ★ 测试窗口(必读) ★\n{windows_text}", priority=90, min_chars=400)
        budget.add("transitions",   f"## 状态跳变\n{transitions_text}", priority=85, min_chars=600)
        budget.add("conditions",    f"## ★ 条件检查表(代码提取) ★\n{conditions_text}", priority=80, min_chars=1500)
        budget.add("threshold",     threshold_section, priority=75,  min_chars=1000)
        budget.add("params",        params_section,    priority=70,  min_chars=1000)
        budget.add("codegraph",     codegraph_section, priority=72,  min_chars=800)
        budget.add("timeline",      f"## 窗口内数据时间线\n{timeline_text[:10000]}", priority=60, min_chars=2000)
        budget.add("frame_anal",    f"## 帧分析\n{frame_analysis[:6000]}", priority=55, min_chars=1500)
        budget.add("evidence",      f"## 数据取证\n{evidence_text}", priority=55, min_chars=3000)
        budget.add("data_summary",  f"## 数据概览\n{data_summary[:5000]}", priority=40, min_chars=1000)

        combined_data = budget.concat()
        status("panel_prompt", budget.format_report())

        panel = ExpertPanel(self.router, self.config, self.project_root)
        panel_result = safe_llm_call(
            "expert_panel",
            lambda **kw: panel.run_panel(
                problem=kw["problem"],
                expected=kw["expected"],
                func_name=kw["func_name"],
                data_summary=kw["data_summary"],
                memory_context=kw["memory_context"],
                on_status=kw["on_status"],
                fail_type=kw["fail_type"],
                task_type=kw["task_type"],
            ),
            problem=problem,
            expected=expected,
            func_name=func_name,
            evidence=key_facts[:2000],
            data_summary=combined_data,
            memory_context=memory_context,
            on_status=on_status,
            fail_type=func_info.get("fail_type", "OTHER"),
            task_type=task_type,
        )
        diagnosis = panel_result.get("final_verdict", "Diagnosis failed.")
        self.memory.log_step(session_id, "expert_panel", {
            "rounds": panel_result.get("rounds", 0),
            "contradictions": panel_result.get("moderator_challenges", {}).get("contradictions", []),
            "verdict_preview": diagnosis[:500],
        })

        whatif_md = (
            render_what_if_markdown(whatif_entries) if whatif_entries else ""
        )

        # ── Phase 4.5: CodeFixEngine — generate actionable code diffs ───
        fix_report_md = ""
        try:
            status("code_fix", "Generating code fix suggestions...")
            fix_report_md = self._generate_code_fix(
                problem=problem,
                diagnosis=diagnosis,
                func_name=func_name,
                status=status,
            )
            if fix_report_md:
                status("code_fix", "Code fix generated successfully")
            else:
                status("code_fix", "No actionable code fix generated")
        except Exception as exc:
            status("code_fix", f"Code fix generation failed: {exc}")

        # ── Phase 5: Generate report & update memory ─────────────────────
        status("report", "Generating report...")
        report_path = self._save_report(
            case_dir, diagnosis, problem, expected,
            func_name, bag_meta, blf_meta, windows,
            task_type=task_type,
            param_report_md=param_section_md,
            whatif_md=whatif_md,
            fix_report_md=fix_report_md,
        )

        expert_appendix_path = case_dir / "expert_opinions.md"
        self._save_expert_appendix(expert_appendix_path, panel_result)

        try:
            status("visualize", "Rendering HTML visualization...")
            viz = build_html_report(
                case_dir=case_dir,
                func_name=func_name,
                task_type=task_type,
                problem=problem,
                expected=expected,
                diagnosis=diagnosis,
                store=store,
                windows=windows,
                tpe_result=self._last_tpe_result,
                param_report=param_report_obj,
                whatif_entries=whatif_entries,
                bag_meta=bag_meta,
                blf_meta=blf_meta,
            )
            status(
                "visualize",
                f"HTML report: {viz.html_path} (charts={viz.charts_built})",
            )
            self.memory.log_step(session_id, "visualize", viz.to_dict())
        except Exception as exc:
            status("visualize", f"Visualization failed: {exc}")

        try:
            self._update_memories(session_id, case_dir, func_name, func_info, diagnosis, problem)
        except Exception:
            pass
        self.memory.complete_session(session_id, f"Report saved to {report_path}")
        status("done", report_path)

        store.close()

        # P1.4: Save observability log
        try:
            obs_log_path = case_dir / "observability_log.json"
            step_logger.save(obs_log_path)
            status("observability", f"Step log saved: {obs_log_path}")
        except Exception:
            pass

        return report_path

    # ── Temporal Pattern Engine runner ─────────────────────────────────

    def _run_tpe(
        self, store, evidence: dict, func_name: str, windows, status,
    ) -> tuple[str, dict]:
        """
        Run the Temporal Pattern Engine over the current case.

        Returns a ``(narration, structured_report)`` tuple. The narration
        is human-readable markdown suitable for the expert prompt; the
        structured report carries counts/summaries for the memory log.

        The live ``TPEResult`` object is also cached on ``self._last_tpe_result``
        so downstream consumers (e.g. the HTML visualizer) can draw real
        pattern-hit intervals instead of re-parsing the summary dict.

        On any failure we swallow the exception and return empty — TPE is
        an enhancement, never a blocker for the rest of the pipeline.
        """
        self._last_tpe_result = None
        try:
            from .tpe import TemporalPatternEngine
            from .signal_mapper import (
                extract_signal_mapping, trace_variable_chains,
                load_variable_chains, extract_output_signal_mapping,
                build_expr_to_can_index, load_output_chain_aliases,
            )
        except Exception as exc:
            status("tpe", f"TPE modules unavailable: {exc}")
            return "", {}

        source_root = Path(self.config["paths"]["source_code"])
        docs_dir = self.project_root / "source_docs"
        knowledge_dir = self.project_root / "memory" / "code_knowledge"

        try:
            sig_mapping = extract_signal_mapping(source_root, docs_dir)
        except Exception as exc:
            status("tpe", f"Signal mapping failed: {exc}")
            sig_mapping = {}

        try:
            chains = load_variable_chains(docs_dir)
            if not chains.get("struct_aliases"):
                chains = trace_variable_chains(source_root, docs_dir)
        except Exception:
            chains = {}

        # WriteSignal-side data for resolving output variables that never
        # appear in the ReadSignal mapping (e.g. bLcaLeftWarningFlg).
        try:
            out_mapping = extract_output_signal_mapping(source_root, docs_dir)
            build_expr_to_can_index(out_mapping)  # caches into out_mapping
        except Exception as exc:
            status("tpe", f"Output mapping failed: {exc}")
            out_mapping = {}
        try:
            out_aliases = load_output_chain_aliases(knowledge_dir)
        except Exception:
            out_aliases = {}

        try:
            engine = TemporalPatternEngine(
                source_root=source_root,
                cache_dir=docs_dir,
                signal_mapping=sig_mapping,
                variable_chains=chains,
                output_mapping=out_mapping,
                output_aliases=out_aliases,
            )
            result = engine.run(
                store=store, func_name=func_name,
                state_transitions=evidence.get("state_transitions", []),
                time_window=None,
            )
        except Exception as exc:
            status("tpe", f"TPE run failed: {exc}")
            return "", {}

        narration = result.to_expert_block()
        structured = {
            "pattern_count": len(result.patterns),
            "triggered_count": result.triggered_count,
            "unresolved_count": len(result.unresolved_variables),
            "internal_only_count": len(result.internal_only_variables),
            "missing_can_count": len(result.missing_can_signals),
            "notes": result.notes,
            "pattern_summary": [
                {
                    "type": p.pattern_type,
                    "file": p.file,
                    "line_start": p.line_start,
                    "line_end": p.line_end,
                    "function": p.function,
                    "adas_function": p.adas_function,
                    "trigger_condition": p.trigger_condition,
                    "trigger_variables": list(p.trigger_variables),
                    "consequence_variables": list(p.consequence_variables),
                }
                for p in result.patterns[:40]
            ],
            "evidence_summary": [
                {
                    "pattern_type": e.pattern.pattern_type,
                    "line_start": e.pattern.line_start,
                    "adas_function": e.pattern.adas_function,
                    "verdict": e.verdict,
                    "hit_count": len(e.hits),
                    "first_hit_t": (e.hits[0].interval.t_start
                                     if e.hits else None),
                    "first_hit_duration": (e.hits[0].interval.duration
                                            if e.hits else None),
                    "summary": e.summary,
                    "unresolved_signals": list(e.unresolved_signals),
                    "missing_signals": list(e.missing_signals),
                }
                for e in result.evidence
            ],
        }
        status("tpe", (
            f"TPE: {structured['pattern_count']} patterns, "
            f"{structured['triggered_count']} triggered, "
            f"{structured['unresolved_count']} unresolved vars "
            f"({structured['internal_only_count']} internal-only filtered), "
            f"{structured['missing_can_count']} missing CAN signals"
        ))
        self._last_tpe_result = result
        return narration, structured

    # ── Output signal analyzer (brake/warning/TTC from CAN output) ─────

    def _analyze_output_signals(
        self, store, func_name: str, windows, status,
    ) -> str:
        """Analyze CAN output signals for the given ADAS function.

        Pulls per-function output signals from the mapping table
        (brake/warning/state/TTC — varies by function) and reports
        active periods, value statistics and transition events for each.
        """
        from .signal_mapper import (
            extract_output_signal_mapping, get_output_signals_for_function,
        )

        out_mapping = extract_output_signal_mapping(
            Path(self.config["paths"]["source_code"]),
            self.project_root / "source_docs",
        )
        target_signals = get_output_signals_for_function(func_name)
        if not target_signals:
            return ""

        status("output_signals", f"Target output signals: {', '.join(target_signals)}")
        sig_to_expr = out_mapping.get("signal_to_expr", {})

        inventory = store.get_signal_inventory() or []
        available: dict[str, dict] = {}
        for item in inventory:
            for sig in item.get("signals", []):
                available[sig] = {
                    "can_id": item["can_id"],
                    "message_name": item["message_name"],
                }

        results: list[str] = []
        for target in target_signals:
            matched_sig = None
            if target in available:
                matched_sig = target
            else:
                for avail_name in available:
                    if target.lower() == avail_name.lower():
                        matched_sig = avail_name
                        break

            if not matched_sig:
                continue

            info = available[matched_sig]
            msg_name = info["message_name"]
            frames = store.query_can_by_name(msg_name)
            if not frames:
                results.append(f"### {matched_sig} ({msg_name})\n  无数据帧")
                continue

            timeline = []
            for f in frames:
                val = f.get("signals", {}).get(matched_sig)
                if val is not None:
                    timeline.append((f["timestamp"], val))

            if not timeline:
                results.append(f"### {matched_sig} ({msg_name})\n  信号字段不存在")
                continue

            values = [v for _, v in timeline if isinstance(v, (int, float))]
            if not values:
                continue

            v_min, v_max = min(values), max(values)
            v_mean = sum(values) / len(values)
            nonzero = sum(1 for v in values if v != 0)
            nz_pct = nonzero / len(values) * 100

            changes = []
            prev_val = None
            for t, v in timeline:
                if prev_val is not None and v != prev_val:
                    changes.append({"t": round(t, 3), "from": prev_val, "to": v})
                prev_val = v

            active_start = None
            active_periods: list[dict] = []
            for t, v in timeline:
                is_active = (v != 0) if isinstance(v, (int, float)) else False
                if is_active and active_start is None:
                    active_start = t
                elif not is_active and active_start is not None:
                    active_periods.append({
                        "start": round(active_start, 3),
                        "end": round(t, 3),
                        "duration_ms": round((t - active_start) * 1000, 1),
                    })
                    active_start = None
            if active_start is not None:
                last_t = timeline[-1][0]
                active_periods.append({
                    "start": round(active_start, 3),
                    "end": round(last_t, 3),
                    "duration_ms": round((last_t - active_start) * 1000, 1),
                })

            expr_list = sig_to_expr.get(target, ["?"])
            expr_display = " | ".join(expr_list) if isinstance(expr_list, list) else str(expr_list)
            header = f"### {matched_sig} ({msg_name})"
            lines = [header]
            lines.append(f"  源表达式: `{expr_display}`")
            lines.append(f"  统计: min={v_min}, max={v_max}, mean={v_mean:.4f}, "
                         f"非零帧={nonzero}/{len(values)} ({nz_pct:.1f}%)")

            if active_periods:
                lines.append(f"  **激活段 ({len(active_periods)}个)**:")
                for ap in active_periods[:10]:
                    lines.append(f"    {ap['start']}s ~ {ap['end']}s "
                                 f"(持续 {ap['duration_ms']:.0f}ms)")
                if len(active_periods) > 10:
                    lines.append(f"    ...+{len(active_periods) - 10}段")

            if changes:
                shown = changes[:15]
                lines.append(f"  跳变 ({len(changes)}次, 前{len(shown)}条):")
                for ch in shown:
                    lines.append(f"    t={ch['t']}s: {ch['from']}→{ch['to']}")
            else:
                lines.append(f"  跳变: 无 (恒定值={values[0]})")

            results.append("\n".join(lines))

        if not results:
            return ""
        return "\n\n".join(results)

    # ── Suppression signal checker ─────────────────────────────────────

    def _check_suppression_signals(
        self, store, suppression_signals: list[dict],
        windows, func_name: str, status,
    ) -> str:
        """
        Check CAN data for active suppression signals identified by the
        condition extractor.  Uses signal_mapping.json (from RteComMapping.c)
        to resolve internal variable names -> DBC CAN signal names.

        Key features:
        - Threshold-aware evaluation: parses threshold field to determine
          whether suppression condition is met (not just nonzero check)
        - Semantic fallback: when variable is a macro/function/compound expr,
          uses signal_chain categories to find related signals
        """
        from difflib import get_close_matches
        from .signal_mapper import (
            extract_signal_mapping, resolve_internal_to_can, _extract_core_keyword,
            trace_variable_chains, load_variable_chains,
        )

        sig_mapping = extract_signal_mapping(
            Path(self.config["paths"]["source_code"]),
            self.project_root / "source_docs",
        )
        chains = load_variable_chains(self.project_root / "source_docs")
        if not chains.get("struct_aliases"):
            chains = trace_variable_chains(
                Path(self.config["paths"]["source_code"]),
                self.project_root / "source_docs",
            )
        alias_count = len(chains.get("struct_aliases", {}))
        status("suppression", f"Signal mapping loaded: {sig_mapping.get('mapping_count', 0)} entries, {alias_count} struct aliases")

        inventory = store.get_signal_inventory() or []
        all_signals: dict[str, dict] = {}
        for item in inventory:
            for sig in item.get("signals", []):
                all_signals[sig] = {
                    "can_id": item["can_id"],
                    "message_name": item["message_name"],
                }

        all_signal_names = list(all_signals.keys())
        results: list[str] = []

        for sup in suppression_signals:
            can_hint = sup.get("can_signal", "") or ""
            var_name = sup.get("variable", "") or ""
            system = sup.get("source_system", "?")
            condition = sup.get("condition", "?")
            effect = sup.get("effect", "抑制")
            threshold = sup.get("suppression_trigger") or sup.get("threshold", "")

            candidates = self._resolve_can_signal(
                can_hint, var_name, all_signals, all_signal_names,
                sig_mapping, get_close_matches, _extract_core_keyword,
                chains,
            )

            is_unresolvable = not candidates and (
                "(" in var_name or "||" in var_name or "&&" in var_name
            )
            fallback_note = ""
            if not candidates and is_unresolvable:
                candidates, fallback_note = self._semantic_fallback(
                    condition, system, all_signals, all_signal_names,
                    sig_mapping,
                )

            if not candidates:
                results.append(
                    f"### [{system}] {condition}\n"
                    f"  变量: {var_name}, CAN: {can_hint or '?'}\n"
                    f"  **未在BLF中找到匹配信号，无法确认** → 效果: {effect}"
                )
                continue

            header = (
                f"### [{system}] {condition} → {effect}\n"
                f"  变量: {var_name}, 阈值: {threshold}"
            )
            if fallback_note:
                header += f"\n  ⚠ {fallback_note}"
            sub_results: list[str] = [header]

            for sig_name in candidates:
                info = all_signals[sig_name]
                msg_name = info["message_name"]
                frames = store.query_can_by_name(msg_name)
                if not frames:
                    sub_results.append(f"  {msg_name}.{sig_name}: 无数据帧")
                    continue

                timeline = []
                for f in frames:
                    val = f.get("signals", {}).get(sig_name)
                    if val is not None:
                        timeline.append((f["timestamp"], val))

                if not timeline:
                    sub_results.append(f"  {msg_name}.{sig_name}: 信号字段不存在")
                    continue

                values = [v for _, v in timeline if isinstance(v, (int, float))]
                if not values:
                    sub_results.append(f"  {msg_name}.{sig_name}: 无数值数据")
                    continue

                changes = []
                prev = None
                for t, v in timeline:
                    if prev is not None and v != prev:
                        changes.append({"t": round(t, 3), "from": prev, "to": v})
                    prev = v

                eval_result = self._evaluate_threshold(values, threshold)
                met_pct = eval_result["met_pct"]
                met = met_pct > 1.0
                marker = "⚠️ **抑制条件满足**" if met else "✅ 抑制条件不满足"

                v_min, v_max = min(values), max(values)
                v_mean = sum(values) / len(values)
                nonzero = sum(1 for v in values if v != 0)
                nz_pct = nonzero / len(values) * 100

                polarity_warning = ""
                inv_thr = self._invert_threshold(threshold)
                if inv_thr:
                    inv_eval = self._evaluate_threshold(values, inv_thr)
                    inv_met = inv_eval["met_pct"] > 1.0
                    if met != inv_met:
                        dominant = "原始" if met else "反向"
                        polarity_warning = (
                            f"\n    ⚠ 极性交叉检查: 反向阈值'{inv_thr}'→{inv_eval['description']}"
                            f"\n      {'原始' if met else '反向'}判定为抑制满足，请专家结合代码逻辑确认极性"
                        )

                sub_results.append(
                    f"  **{msg_name}.{sig_name}**: {marker}\n"
                    f"    判定: {eval_result['description']}\n"
                    f"    原始统计: min={v_min:.4f}, max={v_max:.4f}, "
                    f"mean={v_mean:.4f}, 非零帧={nz_pct:.1f}%\n"
                    f"    帧数: {len(timeline)}, 变化: {len(changes)}次"
                    f"{polarity_warning}"
                )
                if changes:
                    for c in changes[:8]:
                        sub_results.append(f"      t={c['t']}s: {c['from']} → {c['to']}")
                    if len(changes) > 8:
                        sub_results.append(f"      ... +{len(changes)-8} more")

                status("suppression", f"  {sig_name}: {marker}")

            results.append("\n".join(sub_results))

        return "\n\n".join(results) if results else "(无外部抑制信号数据)"

    @staticmethod
    def _evaluate_threshold(values: list, threshold_str: str) -> dict:
        """
        Parse a threshold expression and evaluate what percentage of data
        values satisfy the suppression condition.

        Supported formats: TRUE, FALSE, ==0, !=0, >80, >=250, <30, <=N,
                          and compound like '>= 0.8'.
        Returns: {"met_pct": float, "description": str}
        """
        import re
        n = len(values)
        if n == 0:
            return {"met_pct": 0.0, "description": "无数据"}

        thr = threshold_str.strip().upper() if threshold_str else ""
        thr_normalized = thr.replace(" ", "")

        if thr_normalized in ("TRUE", "!=0", "==TRUE", "==1"):
            cnt = sum(1 for v in values if v != 0)
            pct = cnt / n * 100
            return {"met_pct": pct, "description": f"阈值={threshold_str}: {pct:.1f}%帧非零 ({cnt}/{n})"}

        if thr_normalized in ("FALSE", "==0", "==FALSE", "!=TRUE"):
            cnt = sum(1 for v in values if v == 0)
            pct = cnt / n * 100
            return {"met_pct": pct, "description": f"阈值={threshold_str}: {pct:.1f}%帧为零 ({cnt}/{n})"}

        m = re.match(r'^(>=?|<=?|==|!=)\s*([-\d.]+)', thr)
        if m:
            op, val_s = m.group(1), float(m.group(2))
            ops = {
                ">": lambda v: v > val_s,
                ">=": lambda v: v >= val_s,
                "<": lambda v: v < val_s,
                "<=": lambda v: v <= val_s,
                "==": lambda v: v == val_s,
                "!=": lambda v: v != val_s,
            }
            func = ops.get(op, lambda v: v != 0)
            cnt = sum(1 for v in values if func(v))
            pct = cnt / n * 100
            return {"met_pct": pct, "description": f"阈值{op}{val_s}: {pct:.1f}%帧满足 ({cnt}/{n}), max={max(values):.4f}"}

        nonzero = sum(1 for v in values if v != 0)
        pct = nonzero / n * 100
        return {"met_pct": pct, "description": f"阈值'{threshold_str}'(未解析,默认非零): {pct:.1f}%帧非零 ({nonzero}/{n})"}

    @staticmethod
    def _invert_threshold(threshold_str: str) -> str:
        """Return the logical inverse of a boolean-like threshold for cross-check."""
        if not threshold_str:
            return ""
        t = threshold_str.strip().upper().replace(" ", "")
        _inv = {
            "TRUE": "== FALSE", "==TRUE": "== FALSE", "==1": "== 0",
            "!=0": "== 0", "FALSE": "== TRUE", "==FALSE": "== TRUE",
            "==0": "!= 0", "!=TRUE": "== TRUE",
        }
        return _inv.get(t, "")

    def _semantic_fallback(
        self, condition: str, system: str,
        all_signals: dict, all_signal_names: list[str],
        sig_mapping: dict,
    ) -> tuple[list[str], str]:
        """
        When _resolve_can_signal fails for a macro/function/compound variable,
        extract semantic keywords from the condition description and search
        for related signals in the signal_mapping categories.

        Returns: (candidate_signal_names, fallback_description_note)
        """
        import re
        keywords = re.findall(r'[A-Z][a-z]+', condition)
        keywords += [w for w in system.split() if len(w) >= 3]
        keywords = list(dict.fromkeys(kw.lower() for kw in keywords if len(kw) >= 3))

        if not keywords:
            return [], ""

        found: list[str] = []
        for kw in keywords:
            for sig in all_signal_names:
                if kw in sig.lower() and sig not in found:
                    found.append(sig)

        if not found:
            i2c = sig_mapping.get("internal_to_can", {})
            for var, can_list in i2c.items():
                if any(kw in var.lower() for kw in keywords):
                    for cs in can_list:
                        if cs in all_signals and cs not in found:
                            found.append(cs)
                        for real in all_signal_names:
                            core = real.split("_0x")[0].lower()
                            if cs.lower().split("_0x")[0] == core and real not in found:
                                found.append(real)

        if found:
            note = (
                f"原始变量无法解析，启用语义搜索"
                f"(关键词: {', '.join(keywords[:5])}, "
                f"匹配{len(found)}个信号)"
            )
            return found[:8], note

        return [], ""

    @staticmethod
    def _resolve_can_signal(
        can_hint: str,
        var_name: str,
        all_signals: dict,
        all_signal_names: list[str],
        sig_mapping: dict,
        get_close_matches,
        extract_core,
        chains: dict | None = None,
    ) -> list[str]:
        """
        Mapping-first resolution: internal variable → DBC CAN signal.

        Priority:
          1. Exact match in BLF inventory (can_hint / var_name)
          2. signal_mapping.json + variable_chains.json lookup via
             resolve_internal_to_can (handles dotted paths, struct aliases,
             full_path index). Then match against BLF with _0x suffix tolerance
          3. Strict fallback: only if mapping returned nothing AND hint is
             a simple signal-like name (no dots/parens), try difflib with
             high cutoff + semantic overlap validation
        """
        from .signal_mapper import resolve_internal_to_can

        for hint in [can_hint, var_name]:
            if hint and hint in all_signals:
                return [hint]

        for hint in [var_name, can_hint]:
            if not hint:
                continue
            mapped = resolve_internal_to_can(hint, sig_mapping, chains)
            for ms in mapped:
                if ms in all_signals:
                    return [ms]
                core_ms = ms.split("_0x")[0].lower() if "_0x" in ms else ms.lower()
                for real in all_signal_names:
                    real_core = real.split("_0x")[0].lower() if "_0x" in real else real.lower()
                    if core_ms == real_core:
                        return [real]

        for hint in [can_hint, var_name]:
            if not hint or "." in hint or "(" in hint:
                continue
            matches = get_close_matches(hint, all_signal_names, n=2, cutoff=0.7)
            if matches:
                best = matches[0]
                if _signal_overlap_ok(hint, best):
                    return [best]

        return []

    # ── Threshold reference loader ─────────────────────────────────────

    def _load_threshold_reference(self, func_name: str) -> str:
        """Load authoritative thresholds from source_docs/{func}.md for cross-validation."""
        doc_path = self.project_root / "source_docs" / f"{func_name}.md"
        if not doc_path.exists():
            return ""
        try:
            content = doc_path.read_text(encoding="utf-8")
            return content[:4000]
        except Exception:
            return ""

    # ── Proposal parser (tune/verify branch) ──────────────────────────

    @staticmethod
    def _parse_proposals(
        problem: str, expected: str, param_report,
    ) -> dict[str, float]:
        """Extract ``{param_name: new_value}`` pairs from the user prompt.

        Recognises patterns like:
          * ``fBsdActiveSpd 从 12 改到 15``
          * ``把 fFctbObjWarningBaseTTMX 改为 1.5``
          * ``set fRctbHoldTimeThresh = 5``
          * ``TTC 调到 1.5s`` (category-level, picks the matching param)
        """
        text = (problem or "") + "\n" + (expected or "")
        proposals: dict[str, float] = {}

        verbs = (
            r"改到|改成|改为|设为|设定为|调到|调至|"
            r"调整到|调优到|调为|到|至|→|->|to"
        )

        name_set = {p.parameter.name for p in param_report.entries}
        for name in name_set:
            pat1 = _re.compile(
                rf"\b{_re.escape(name)}\b\s*"
                rf"(?:从|from)\s*[-+]?\d+(?:\.\d+)?"
                rf"[^0-9\-+]{{0,6}}?"
                rf"(?:{verbs})\s*"
                rf"([-+]?\d+(?:\.\d+)?)",
                _re.IGNORECASE,
            )
            m = pat1.search(text)
            if m:
                try:
                    proposals[name] = float(m.group(1))
                    continue
                except ValueError:
                    pass

            pat2 = _re.compile(
                rf"\b{_re.escape(name)}\b[^0-9\-+]{{0,30}}?"
                rf"(?:{verbs})\s*"
                rf"([-+]?\d+(?:\.\d+)?)",
                _re.IGNORECASE,
            )
            m2 = pat2.search(text)
            if m2:
                try:
                    proposals[name] = float(m2.group(1))
                except ValueError:
                    continue

        return proposals

    # ── Per-function speed threshold extraction ────────────────────────

    def _collect_speed_thresholds(self, func_name: str) -> list[float]:
        """Pull activation/deactivation speeds from ``{FUNC}_conditions.json``.

        This makes the test-window detector reflect **this** function's
        activation band instead of the generic FCT-centric list. Rear
        functions (BSD/LCA/DOW/RCW/RCTA/RCTB) have very different speed
        ranges than front ones, so a shared threshold list loses signal.
        """
        docs_dir = self.project_root / "source_docs"
        cond_path = docs_dir / f"{func_name.upper()}_conditions.json"
        if not cond_path.exists():
            return []
        try:
            data = json.loads(cond_path.read_text(encoding="utf-8"))
        except Exception:
            return []

        thresholds: list[float] = []

        ranges = data.get("ego_speed_ranges") or {}
        for band in ranges.values():
            if not isinstance(band, dict):
                continue
            for key in ("low", "high"):
                v = self._parse_speed_value(band.get(key))
                if v is not None:
                    thresholds.append(v)

        tgt_ranges = data.get("target_speed_ranges") or {}
        for band in tgt_ranges.values():
            if not isinstance(band, dict):
                continue
            for key in ("low", "high"):
                v = self._parse_speed_value(band.get(key))
                if v is not None:
                    thresholds.append(v)

        return thresholds

    @staticmethod
    def _parse_speed_value(raw) -> float | None:
        """Extract the numeric part from entries like 'fBsdActiveSpd=12.0'."""
        if raw is None:
            return None
        if isinstance(raw, (int, float)):
            return float(raw)
        if not isinstance(raw, str):
            return None
        text = raw.strip()
        if not text:
            return None
        m = _re.search(r'([-+]?\d+(?:\.\d+)?)', text)
        if not m:
            return None
        try:
            return float(m.group(1))
        except ValueError:
            return None

    # ── Phase implementations ───────────────────────────────────────────

    def _ensure_source_docs(self, status):
        docs_dir = self.project_root / "source_docs"
        learner = CodeLearner(self.router, self.config, self.project_root)
        result = learner.ensure_overview_docs(
            funcs=ALL_FUNCTIONS,
            status_cb=lambda step, msg: status("source_docs", msg),
        )
        if result.get("generated"):
            status("source_docs", f"Generated: {', '.join(result['generated'])}")
        for failed in result.get("failed") or []:
            status("source_docs", f"[WARN] {failed['func']} failed: {failed['error']}")

        sig_map_path = docs_dir / "signal_mapping.json"
        if not sig_map_path.exists():
            status("source_docs", "Building CAN signal ↔ internal variable mapping...")
            from .signal_mapper import extract_signal_mapping
            result = extract_signal_mapping(
                Path(self.config["paths"]["source_code"]), docs_dir,
            )
            status("source_docs", f"Signal mapping: {result.get('mapping_count', 0)} entries")

        # CodeGraph: silent incremental build (user-transparent)
        self._build_codegraph(status)

    def _build_codegraph(self, status):
        """Silently build/increment CodeGraph DB. Falls back gracefully on error."""
        try:
            from .codegraph import CodeGraphBuilder
            from .code_learner import FUNC_KEYWORDS

            source_root = Path(self.config["paths"]["source_code"])
            key_files = self.config.get("paths", {}).get("key_source_files", [])

            # calib_source_files: header files with calibration params
            calib_files = [
                p for p in key_files
                if "paraDefine" in p or "structDefine" in p or "globalVarDefine" in p
            ]

            db_path = self.project_root / "memory" / "codegraph.db"

            builder = CodeGraphBuilder(
                db_path=db_path,
                source_root=source_root,
                key_files=key_files,
                func_keywords=FUNC_KEYWORDS,
                calib_files=calib_files,
            )
            result = builder.build()

            if result.build_type == "skip":
                status("codegraph", "CodeGraph: no changes (skipped)")
            elif result.success:
                status("codegraph",
                       f"CodeGraph: {result.build_type} "
                       f"(+{result.nodes_added} nodes, +{result.edges_added} edges, "
                       f"{result.duration_sec:.1f}s)")
            else:
                status("codegraph", f"CodeGraph: build failed ({result.error})")

        except Exception as e:
            # Completely silent on error — user should never see this
            import logging
            logging.getLogger(__name__).debug("CodeGraph build error (non-fatal): %s", e)

    def _generate_code_fix(self, problem, diagnosis, func_name, status):
        """
        Phase 4.5 — CodeFixEngine: generate actionable unified diffs
        from expert panel verdict.

        Returns markdown string for report appendix (empty on failure).
        """
        try:
            from .code_fix_engine import generate_fix, render_fix_report_markdown
        except ImportError as e:
            status("code_fix", f"CodeFixEngine unavailable: {e}")
            return ""

        cg_path = self.project_root / "memory" / "codegraph.db"
        if not cg_path.exists():
            status("code_fix", "CodeGraph DB not found; skipping code fix generation")
            return ""

        source_root = self.config.get("paths", {}).get("source_code", "")
        if not source_root:
            status("code_fix", "source_code path not configured; skipping")
            return ""

        fix_result = generate_fix(
            problem=problem,
            diagnosis=diagnosis,
            func_name=func_name,
            codegraph_db_path=cg_path,
            source_root=source_root,
            router=self.router,
            on_status=status,
        )

        return render_fix_report_markdown(fix_result)

    def _understand_problem(self, problem: str, expected: str, case_dir: Path) -> dict:
        memory_context = self.memory.build_context_for_diagnosis("UNKNOWN", problem, case_dir)

        # 关键字预筛选：只加载问题/预期里提到的功能 MD；
        # 没匹配到则降级为 top-3 常见功能兜底，而不是全量 8 个。
        query_text = f"{problem}\n{expected}".upper()
        matched_funcs = [f for f in ALL_FUNCTIONS if f in query_text]
        if not matched_funcs:
            matched_funcs = ["FCTB", "FCTA", "RCTB"]
            prefilter_note = "（问题中未识别到功能名，加载 top-3 常见功能兜底）"
        else:
            prefilter_note = f"（问题中识别到: {', '.join(matched_funcs)}）"

        source_summaries = ""
        docs_dir = self.project_root / "source_docs"
        for fn in matched_funcs:
            md = docs_dir / f"{fn}.md"
            if not md.exists():
                continue
            try:
                content = md.read_text(encoding="utf-8")
                source_summaries += f"\n### {fn}\n{content[:2000]}\n"
            except Exception:
                pass

        # CodeGraph: inject structured code context
        codegraph_md = ""
        try:
            from .codegraph import CodeGraph, CodeGraphRenderer
            cg_path = self.project_root / "memory" / "codegraph.db"
            if cg_path.exists():
                cg = CodeGraph(cg_path)
                renderer = CodeGraphRenderer(cg)
                for fn in matched_funcs:
                    md_text = renderer.render_for_problem(fn, problem, max_chars=3000)
                    if md_text:
                        codegraph_md += f"\n{md_text}\n"
                cg.close()
        except Exception:
            pass  # silent fallback

        prompt = f"""分析以下问题，制定诊断计划。

## 问题现象
{problem}

## 预期结果
{expected}

## 历史记忆
{memory_context}

## 功能文档概要 {prefilter_note}
{source_summaries if source_summaries else "(功能文档将自动生成)"}

## 代码结构 (CodeGraph)
{codegraph_md if codegraph_md else "(代码知识图谱构建中，将在后续步骤可用)"}

请输出JSON:
{{
  "function": "最可能涉及的功能(BSD/LCA/DOW/RCW/RCTA/RCTB/FCTA/FCTB)",
  "confidence": 0.0-1.0,
  "reasoning": "判断理由",
  "fail_type": "误报FP/漏报FN/延迟DELAY/状态异常STATE/其他OTHER",
  "key_variables": ["需关注的关键变量"],
  "related_functions": ["可能相关的其他功能"]
}}
只输出JSON。"""

        result = self.router.complex(prompt, system=ORCHESTRATOR_SYSTEM)
        return parse_json_from_llm(result.get("content", ""), fallback={
            "function": "UNKNOWN",
            "confidence": 0.0,
            "fail_type": "OTHER",
            "key_variables": [],
        })

    def _parse_case_data(self, case_dir: Path, status):
        from parsers.case_loader import load_case_data
        r = load_case_data(case_dir, self.config, self.project_root, on_status=status)
        return r.store, r.bag_meta, r.blf_meta, r.sync

    def _run_frame_analysis_with(self, analyzer, store, func_name: str, func_info: dict, status) -> str:
        status("analyze", "Extracting warning timeline...")
        warning_analysis = analyzer.analyze_bag_timeline(
            store, "/corner_radar/warning_status_raw", func_name,
        )

        key_vars = func_info.get("key_variables", [])
        prompt = f"""简洁总结以下数据(不超过200字):
- 报警帧数: {warning_analysis.get('frame_count', 0)}
- 变化次数: {warning_analysis.get('change_count', 0)}
- 前15条变化: {json.dumps(warning_analysis.get('changes', [])[:15], default=str, ensure_ascii=False)[:2000]}
- 关注变量: {', '.join(key_vars) if key_vars else 'AI判断'}

输出: 状态变化模式 + 关键时刻 + 异常点"""

        result = self.router.chat(
            [{"role": "user", "content": prompt}],
            complexity="simple",
            max_tokens=1024,
        )
        return result.get("content", json.dumps(warning_analysis, default=str, ensure_ascii=False)[:2000])

    def _build_data_summary(self, store, bag_meta, blf_meta, sync) -> str:
        parts = []
        if bag_meta:
            parts.append(f"### BAG: {bag_meta['file']} ({bag_meta['duration_sec']:.1f}s, {bag_meta['message_count']}条)")
            for name, info in bag_meta.get("topics", {}).items():
                parts.append(f"  - {name}: {info['msg_count']}条 ({info['msg_type']})")

        if blf_meta:
            parts.append(f"\n### BLF: {blf_meta['file']} ({blf_meta['duration_sec']:.1f}s, {blf_meta['message_count']}条)")
            parts.append(f"  CAN IDs: {blf_meta['unique_can_ids']}")

        if sync:
            parts.append(f"\n### 时间偏移: {sync.offset_sec:.3f}s")

        warnings = store.query_bag_by_topic("/corner_radar/warning_status_raw")
        if warnings:
            parts.append(f"\n### 报警状态 ({len(warnings)}帧)")
            sampled = warnings[::max(1, len(warnings) // 15)]
            for w in sampled:
                fields = w.get("fields", {})
                parts.append(f"  t={w['timestamp_sec']:.3f} {json.dumps(fields, default=str)[:120]}")

        can_ids = store.get_can_ids()
        if can_ids:
            parts.append(f"\n### CAN ({len(can_ids)}种)")
            for c in can_ids[:12]:
                parts.append(f"  {c['can_id_hex']} {c.get('message_name') or '?'}: {c['count']}")

        return "\n".join(parts)

    def _save_report(self, case_dir, diagnosis, problem, expected,
                     func_name, bag_meta, blf_meta, windows,
                     task_type: str = "diagnose",
                     param_report_md: str = "",
                     whatif_md: str = "",
                     fix_report_md: str = "") -> str:
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        title_map = {
            "diagnose": "角雷达问题诊断报告",
            "tune":     "角雷达参数调优分析报告",
            "verify":   "角雷达参数变更验证报告",
            "query":    "角雷达信息检索报告",
        }
        method_map = {
            "diagnose": "窗口检测 + 条件提取 + TPE + 5专家面板×3轮",
            "tune":     "参数扫描 + 敏感性分析(穿越次数/裕度) + 专家建议",
            "verify":   "参数敏感性对比 + What-if 评估",
            "query":    "知识检索 + 文档汇总",
        }
        title = title_map.get(task_type, title_map["diagnose"])
        method_label = method_map.get(task_type, method_map["diagnose"])

        header = f"""# {title}

| 项目 | 内容 |
|------|------|
| 生成时间 | {now} |
| 任务类型 | **{task_type}** |
| 涉及功能 | **{func_name}** |
| 问题现象 | {problem} |
| 预期结果 | {expected} |
| 分析方法 | {method_label} |
"""
        if windows:
            for i, w in enumerate(windows):
                header += f"| 测试窗口{i+1} | {w.t_start:.1f}s~{w.t_end:.1f}s ({w.duration:.1f}s) — {w.trigger_reason} |\n"
        if bag_meta:
            header += f"| BAG数据 | {bag_meta['file']} ({bag_meta['duration_sec']:.1f}s, {bag_meta['message_count']}条) |\n"
        if blf_meta:
            header += f"| BLF数据 | {blf_meta['file']} ({blf_meta['duration_sec']:.1f}s, {blf_meta['message_count']}条) |\n"

        trailer = ""
        if param_report_md or whatif_md:
            trailer = "\n---\n\n## 附录 A — 参数敏感性(系统直接计算)\n\n"
            if param_report_md:
                trailer += param_report_md + "\n\n"
            if whatif_md:
                trailer += "## 附录 B — What-if 评估(与输入提案一一对应)\n\n" + whatif_md + "\n"

        if fix_report_md:
            trailer += "\n---\n\n" + fix_report_md + "\n"

        report_path = case_dir / "report.md"
        report_path.write_text(
            f"{header}\n---\n\n{diagnosis}{trailer}",
            encoding="utf-8",
        )
        return str(report_path)

    def _save_expert_appendix(self, path: Path, panel_result: dict) -> None:
        parts = ["# 专家面板详细记录\n"]
        for expert_id, analysis in panel_result.get("expert_opinions", {}).items():
            parts.append(f"## {expert_id}\n{analysis}\n")

        challenges = panel_result.get("moderator_challenges", {})
        if challenges:
            parts.append("## 主持人审查\n")
            if challenges.get("contradictions"):
                parts.append("### 矛盾点\n" + "\n".join(f"- {c}" for c in challenges["contradictions"]))
            if challenges.get("gaps"):
                parts.append("\n### 遗漏\n" + "\n".join(f"- {g}" for g in challenges["gaps"]))
            if challenges.get("key_dispute"):
                parts.append(f"\n### 关键争议\n{challenges['key_dispute']}")

        path.write_text("\n\n".join(parts), encoding="utf-8")

    def _update_memories(self, session_id, case_dir, func_name, func_info, diagnosis, problem):
        self.memory.write_case_memory(case_dir, {
            "session_id": session_id,
            "function": func_name,
            "problem": problem,
            "diagnosis_summary": diagnosis[:500],
        })

        try:
            pattern_prompt = f"""从以下诊断结果中提取可复用的诊断模式。

功能: {func_name}
问题: {problem}
诊断: {diagnosis[:2000]}

输出JSON:
{{"function": "{func_name}", "symptom": "一句话症状", "root_cause": "一句话根因", "keywords": ["关键词1", "关键词2"], "fix_hint": "修复方向"}}
只输出JSON。"""
            result = self.router.chat(
                [{"role": "user", "content": pattern_prompt}],
                complexity="simple",
                max_tokens=1024,
            )
            pattern = parse_json_from_llm(
                result.get("content", ""),
                context="update_memories.pattern",
            )
            if pattern:
                self.memory.add_pattern(pattern)
        except Exception:
            pass

        existing = self.memory.read_function_knowledge(func_name)
        if not existing:
            existing = {"function": func_name, "diagnosis_count": 0, "known_issues": []}
        existing["diagnosis_count"] = existing.get("diagnosis_count", 0) + 1
        existing.setdefault("known_issues", []).append({
            "problem": problem,
            "session": session_id,
            "date": datetime.datetime.now().strftime("%Y-%m-%d"),
        })
        if len(existing["known_issues"]) > 50:
            existing["known_issues"] = existing["known_issues"][-50:]
        self.memory.write_function_knowledge(func_name, existing)
