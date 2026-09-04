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
from dataclasses import dataclass
from pathlib import Path
from .model_router import ModelRouter
from .code_learner import CodeLearner
from engines.frame_analyzer import FrameAnalyzer
from .expert_panel_langgraph import ExpertPanel
from engines.test_window_detector import TestWindowDetector, format_windows
from .condition_extractor import ConditionExtractor, format_conditions
from .problem_classifier import ProblemClassifier, ClassificationResult
from engines.parameter_analyzer import (
    analyze_sensitivity, render_sensitivity_markdown,
    render_what_if_markdown, what_if,
)
from .visualizer import build_report as build_html_report
from .utils import parse_json_from_llm, ALL_FUNCTIONS
from .context_budget import ContextBudget, compute_budget
from engines.data_probe import DataProbe
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


_REPORT_BOLD_SECTION_LINE_RE = _re.compile(r"^[ \t]*\*\*(?P<title>.+?)\*\*[ \t]*$")
_REPORT_SECTION_HEADING_PREFIXES = (
    "根因",
    "时序耦合",
    "条件检查",
    "关键证据链",
    "数据链路",
    "测试窗口",
    "场景差异分析",
    "关键链路信号审计",
    "修复建议",
    "置信度",
)


def _normalize_report_section_headings(text: str) -> str:
    """Promote common bold-only panel section labels into Markdown headings."""
    if not text:
        return text

    normalized_lines: list[str] = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("###"):
            normalized_lines.append(line)
            continue

        match = _REPORT_BOLD_SECTION_LINE_RE.match(line)
        if not match:
            normalized_lines.append(line)
            continue

        title = match.group("title").strip()
        if title.startswith(_REPORT_SECTION_HEADING_PREFIXES):
            normalized_lines.append(f"### {title}")
            continue

        normalized_lines.append(line)

    normalized = "\n".join(normalized_lines)
    if text.endswith("\n"):
        normalized += "\n"
    return normalized


ORCHESTRATOR_SYSTEM = """你是角雷达(Corner Radar)问题分析系统的任务调度器。
你的职责是理解用户报告的问题，规划分析步骤，调度子任务，并整合最终诊断报告。

你管理的ADAS功能: BSD, LCA, DOW, RCW, RCTA, RCTB, FCTA, FCTB

系统架构知识:
- 两套并行状态机: 感知侧核心文件(感知侧) + 平台侧状态文件(平台侧)
- 两者共享全局状态变量(*SystemState), 调度顺序决定最终值
- 左右雷达从属: 右雷达(RR/FR)为公CAN出口, 左雷达(RL/FL)经私CAN向右侧传送
- 信号链路: 公CAN→RteComMapping→内部变量→算法核心/平台状态→输出计算→输出

┌──── project_intake variants ───────────────────────────────────┐
│ 1. gen6 (BYD/GWM CR60Light/S6H):  DBC-based CAN analysis        │
│    源码: coem/<Customer>/components/AswPerception/func/adasFunc  │
│ 2. gen5 (pl-xpeng RCC1010):       DDDY RPC-based embedded code   │
│    源码: reco_fw/component/{sit,sit,fct,per}/...                │
│    架构: Flux组件模型 + DDDY RPC + PDM持久化                      │
│    信号: MF4(雷达原始输出+PublicCAN) + DBC(CAN信号)               │
└────────────────────────────────────────────────────────────────┘

任务复杂度判断规则:
- simple(交给Gemma4): 单信号查询、数据格式化、简单摘要、变量值查找
- complex(自己处理/专家面板): 多变量关联分析、状态机推理、根因诊断、因果链推断

输出使用中文，技术术语保留英文。"""


@dataclass(frozen=True)
class IdentityContext:
    """Resolved identity metadata used by the diagnosis pipeline.

    This is intentionally thin: it centralizes current variant/project paths
    without changing the public CLI or migrating existing directories.
    """

    variant_id: str = ""
    project_key: str = ""
    package_profile_id: str = ""
    snapshot_id: str = ""
    display_name: str = ""
    source_code: str = ""
    source_docs_dir: Path | None = None
    memory_dir: Path | None = None


def _resolve_identity_context(config: dict, project_root: Path) -> IdentityContext:
    """Resolve variant/package/project metadata with legacy fallbacks."""
    from config import (
        get_package_profile,
        get_project,
        get_variant,
        resolve_memory_dir,
        resolve_source_docs_dir,
        resolve_variant_id,
    )

    ident = config.get("identity") or {}
    variant_id = ident.get("variant_id") or ""
    project_key = ident.get("project_key") or ""
    package_profile_id = ident.get("package_profile_id") or ""
    snapshot_id = ident.get("snapshot_id") or ""
    display_name = ""
    source_code = ""

    try:
        variant_id = resolve_variant_id(config, variant_id or project_key or None)
        variant, codebase, _ = get_variant(config, variant_id)
        project_key = project_key or getattr(variant, "compat_project_key", "") or ""
        display_name = getattr(variant, "display_name", "") or variant_id
        source_code = str(getattr(codebase, "root_path", "") or "")
        if not package_profile_id:
            package_profile_id = getattr(variant, "default_package_profile", "") or ""
        if package_profile_id:
            try:
                package_profile = get_package_profile(config, package_profile_id)
                package_profile_id = getattr(
                    package_profile, "package_profile_id", package_profile_id
                )
            except Exception:
                pass
    except Exception:
        project_cfg = config.get("project") or {}
        if not project_key:
            project_key = (
                project_cfg.get("_project_key")
                or ident.get("project_key")
                or config.get("default_project", "")
            )
        try:
            project_cfg = get_project(config, project_key)
        except Exception:
            pass
        variant_id = variant_id or project_cfg.get("_variant_id", "")
        display_name = project_cfg.get("display_name", "") or project_key
        source_code = project_cfg.get("source_code", "")

    return IdentityContext(
        variant_id=variant_id,
        project_key=project_key,
        package_profile_id=package_profile_id,
        snapshot_id=snapshot_id,
        display_name=display_name,
        source_code=source_code,
        source_docs_dir=resolve_source_docs_dir(config, project_root, variant_id=variant_id or None),
        memory_dir=resolve_memory_dir(config, project_root, variant_id=variant_id or None),
    )


class Orchestrator:
    """
    The AI orchestrator that automates the full diagnosis pipeline.
    Users only need to provide problem description and expected result.
    """

    def __init__(self, config: dict, project_root: Path):
        self.config = config
        self.project_root = project_root
        self.identity = _resolve_identity_context(config, project_root)
        self.router = ModelRouter(config)

        from memory.memory_system import MemorySystem
        self.memory = MemorySystem(
            project_root,
            memory_dir=self.identity.memory_dir or (project_root / "memory"),
            config=config,
        )

        self._last_tpe_result = None

        # ── Phase 15 (2.1.3): pre-load signal maps ────────────────────
        # ReadSignal mapping, WriteSignal mapping, and variable_chains
        # are deterministic and only change when source files change.
        # Loading once in __init__ lets _run_tpe / _check_suppression_signals
        # / _analyze_output_signals reuse the same instances instead of
        # re-reading source files three times per diagnosis.
        self.signal_mapping: dict = {}
        self.variable_chains: dict = {}
        self.output_signal_mapping: dict = {}
        self._case_dbc = None  # DBC loader from the current case (Step-5 signal audit)
        self._init_signal_maps()

    def _resolve_signal_mapping_source(self) -> str:
        """定位信号映射源文件（RteComMapping.c）的相对路径。

        六代不同项目（GWM_B26 / BYD_SC6H 的 ``ASW_ComMapping``）的
        RteComMapping 位于不同目录。优先从 ``paths.key_source_files``
        （CLI 按 variant 注入的正确值）中挑选含 ``RteComMapping`` 的文件，
        避免回退到只对 GWM_B26 有效的默认路径导致映射重建为空。
        """
        ksf = (self.config.get("paths") or {}).get("key_source_files") or []
        for rel in ksf:
            leaf = str(rel).replace("\\", "/")
            if "/RteComMapping" in leaf or leaf.startswith("RteComMapping"):
                return str(rel)
        # Fallback to the engine default (works for GWM-style layouts).
        return r"coem\GWM_B26\components\AswIf\ASW_IN\RteComMapping.c"

    def _init_signal_maps(self) -> None:
        """Phase 15 (2.1.3): Load signal_mapping + variable_chains + output_mapping once.

        Best-effort: a failure here is logged but does not prevent
        Orchestrator initialization. Sub-methods fall back to per-call
        loading if any of the pre-loaded maps are empty.
        """
        try:
            from engines.signal_mapper import (
                extract_signal_mapping,
                trace_variable_chains,
                extract_output_signal_mapping,
            )
            source_root = Path(self.config["paths"]["source_code"])
            docs_dir = self.source_docs_dir
            rte_file = self._resolve_signal_mapping_source()
            self.signal_mapping = extract_signal_mapping(
                source_root, docs_dir, rte_file=rte_file,
            )
            self.variable_chains = trace_variable_chains(source_root, docs_dir)
            self.output_signal_mapping = extract_output_signal_mapping(
                source_root, docs_dir, rte_file=rte_file,
            )
        except Exception as exc:  # noqa: BLE001
            import logging
            logging.getLogger(__name__).warning(
                "Phase 15 / 2.1.3: signal map pre-load failed (%s); "
                "sub-methods will load on demand", exc,
            )

    @property
    def platform_id(self) -> str:
        """Resolve platform_id from the current variant's codebase."""
        try:
            from config import get_variant
            variant_id = self.identity.variant_id or ""
            variant, _codebase, _platform = get_variant(self.config, variant_id)
            return _codebase.platform_id or "gen6_c_radar"
        except Exception:
            return "gen6_c_radar"  # default fallback

    @property
    def codegraph_db_path(self) -> Path:
        """Path to the per-project CodeGraph database."""
        from config import resolve_codegraph_db
        return resolve_codegraph_db(
            self.config, self.project_root, variant_id=self.identity.variant_id or None
        )

    @property
    def source_docs_dir(self) -> Path:
        """Path to the per-project source_docs directory."""
        return self.identity.source_docs_dir or (self.project_root / "source_docs")

    # ── Adapter loading (lazy, once per orchestrator) ──────────────────

    _code_learner_adapter = None
    _condition_extractor_adapter = None

    def _get_code_learner_adapter(self):
        """Return the platform CodeLearner adapter (lazy, cached)."""
        if self._code_learner_adapter is not None:
            return self._code_learner_adapter
        try:
            from ai.platform_adapters.factory import get_code_learner_adapter
            pid = self.platform_id
            source_root = Path(self.config["paths"]["source_code"])
            self._code_learner_adapter = get_code_learner_adapter(
                pid, source_root, self.config, self.project_root,
            )
        except Exception:
            self._code_learner_adapter = None
        return self._code_learner_adapter

    def _get_condition_extractor_adapter(self):
        """Return the platform ConditionExtractor adapter (lazy, cached)."""
        if self._condition_extractor_adapter is not None:
            return self._condition_extractor_adapter
        try:
            from ai.platform_adapters.factory import get_condition_extractor_adapter
            pid = self.platform_id
            source_root = Path(self.config["paths"]["source_code"])
            self._condition_extractor_adapter = get_condition_extractor_adapter(
                pid, source_root, self.config, self.project_root,
            )
        except Exception:
            self._condition_extractor_adapter = None
        return self._condition_extractor_adapter

    def run_diagnosis(
        self,
        case_dir: Path,
        problem: str,
        expected: str,
        on_status=None,
    ) -> str:
        """
        Full automated diagnosis pipeline (V2 — 8-step consolidated).
        Returns path to report.

        Pipeline:
          1. init      — Ensure source docs + CodeGraph (deterministic)
          2. classify  — Understand problem + classify task (1 LLM)
          3. extract   — Parse data + detect windows (deterministic)
          4. evidence  — Conditions(LLM) + TPE(det) + probe(LLM) — parallel
          5. signals   — Suppression + output signals (deterministic)
          6. diagnose  — Expert panel (LangGraph, multi-LLM)
          7. fix       — CodeFixEngine diff generation (1 LLM)
          8. deliver   — Report + visualize + memory (deterministic)
        """
        from concurrent.futures import ThreadPoolExecutor

        # Ensure case_dir is a Path object (caller may pass str)
        case_dir = Path(case_dir)

        def status(step, detail=""):
            if on_status:
                on_status(step, detail)

        # Observability wrapper
        step_logger = StepLogger()
        token_tracker = TokenTracker()
        obs_status = ObservableStatus(on_status, step_logger)

        # ═══════════════════════════════════════════════════════════════════
        # Step 1: INIT — Ensure prerequisites
        # ═══════════════════════════════════════════════════════════════════
        status("init", "Checking prerequisites...")
        self._ensure_source_docs(status)

        # ═══════════════════════════════════════════════════════════════════
        # Step 2: CLASSIFY — Understand + classify (merged, 1 LLM call)
        # ═══════════════════════════════════════════════════════════════════
        status("classify", "Understanding problem and classifying task...")
        session_id = self.memory.create_session(case_dir.name, problem, expected)

        # Understand problem (LLM)
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

        # Classify task type (LLM)
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

        # ═══════════════════════════════════════════════════════════════════
        # Step 3: EXTRACT — Parse data + detect windows (deterministic)
        # ═══════════════════════════════════════════════════════════════════
        status("extract", "Parsing data files...")
        store, bag_meta, blf_meta, sync = self._parse_case_data(case_dir, status)
        parse_summary = {
            "bag_frames": bag_meta.get("message_count") if bag_meta else 0,
            "can_frames": blf_meta.get("message_count") if blf_meta else 0,
        }
        self.memory.log_step(session_id, "parse", parse_summary)

        # Detect test windows
        status("extract", "Detecting test-active time windows...")
        detector = TestWindowDetector()
        speed_thresholds = self._collect_speed_thresholds(func_name)
        unique_thresholds = sorted({round(float(v), 3) for v in speed_thresholds}) if speed_thresholds else []
        if unique_thresholds:
            status("extract",
                   f"Speed thresholds for {func_name}: "
                   f"{', '.join(f'{t:g}' for t in unique_thresholds)} km/h")
        windows = detector.detect(store, func_name,
                                  speed_thresholds=speed_thresholds or None)
        if windows:
            window_desc = "; ".join(
                f"[{w.t_start:.1f}s~{w.t_end:.1f}s] {w.trigger_reason}"
                for w in windows
            )
            status("extract", f"Found {len(windows)} window(s): {window_desc}")
        else:
            status("extract", "No windows detected, using full data")
        self.memory.log_step(session_id, "windows", {
            "count": len(windows),
            "windows": [
                {"t_start": w.t_start, "t_end": w.t_end, "reason": w.trigger_reason}
                for w in windows
            ],
        })

        # Frame analysis + evidence extraction
        status("extract", f"Extracting evidence for {func_name}...")
        var_path = self.source_docs_dir / "variables.json"
        analyzer = FrameAnalyzer(self.router, var_path if var_path.exists() else None)
        frame_analysis = self._run_frame_analysis_with(analyzer, store, func_name, func_info, status)
        evidence = analyzer.extract_evidence(store, func_name, windows=windows or None)
        self.memory.log_step(session_id, "evidence", {
            "keys": list(evidence.keys()),
            "key_facts": evidence.get("KEY_FACTS", "")[:500],
            "window_count": len(windows),
            "transition_count": len(evidence.get("state_transitions", [])),
        })

        # ═══════════════════════════════════════════════════════════════════
        # Step 4: EVIDENCE — conditions + TPE + probe (parallel)
        # ═══════════════════════════════════════════════════════════════════
        status("evidence", "Gathering evidence: conditions + TPE + probe...")

        # Load numeric constants (used by both evidence and probe)
        constants_section = ""
        try:
            constants_section = self.memory.render_constants_for_context(
                func_name, max_chars=2000,
            )
        except Exception:
            import logging
            logging.getLogger(__name__).warning('Operation failed (silent failure caught)')
            pass
        if not constants_section:
            constants_section = (
                "## 已学数值常量（全局）\n"
                "_暂无常量表 — 请运行 `python cli.py --learn-constants`。_\n"
                "_在此之前，遇到 ROI/阈值相关判定时请明确标注\n"
                "'阈值未知、不做数值判断'，不要用经验值猜。_"
            )

        # --- Parallel phase: conditions (LLM) + TPE (deterministic) ---
        evidence_results = {}

        def _extract_conditions():
            status("evidence", f"Extracting {func_name} conditions from code...")
            cond_extractor = ConditionExtractor(self.router, self.project_root, self.config)
            freshness = self.config.get("identity", {}).get("freshness", {})
            force_refresh = bool(
                freshness.get("code_changed")
                or freshness.get("constants_changed")
                or freshness.get("identity_changed")
            )
            conditions = cond_extractor.extract(func_name, force=force_refresh)
            # Use adapter-format_conditions when available, else fallback to default
            adapter = self._get_condition_extractor_adapter()
            if adapter and hasattr(adapter, "format_conditions"):
                conditions_text = adapter.format_conditions(conditions)
            else:
                conditions_text = format_conditions(conditions)
            if "error" not in conditions:
                status("evidence", f"Conditions extracted (cached to source_docs/{func_name}_conditions.json)")
                try:
                    from core.knowledge_guard import publish_knowledge_categories

                    publish_knowledge_categories(
                        self.config,
                        [f"conditions:{func_name.upper()}"],
                        producer="diagnosis.conditions",
                    )
                except Exception as exc:
                    status("evidence", f"Conditions freshness not published: {exc}")
            else:
                status("evidence", f"Condition extraction: {conditions.get('error', '?')}")
            return {"conditions": conditions, "conditions_text": conditions_text}

        def _run_tpe_parallel():
            status("evidence", "Running Temporal Pattern Engine...")
            tpe_text, tpe_report = self._run_tpe(
                store, evidence, func_name, windows, status,
            )
            if tpe_report:
                FrameAnalyzer.append_tpe_block(evidence, tpe_text, tpe_report)
            return {"tpe_text": tpe_text or "", "tpe_report": tpe_report}

        with ThreadPoolExecutor(max_workers=2) as executor:
            conditions_future = executor.submit(_extract_conditions)
            tpe_future = executor.submit(_run_tpe_parallel)

            try:
                evidence_results["conditions"] = conditions_future.result()
            except Exception as e:
                status("evidence", f"Conditions extraction failed: {e}")
                logging.getLogger(__name__).error("Conditions extraction failed", exc_info=True)
                evidence_results["conditions"] = {
                    "conditions": {"error": f"Failed to extract conditions: {e}"},
                    "conditions_text": f"Error extracting conditions: {e}"
                }

            try:
                evidence_results["tpe"] = tpe_future.result()
            except Exception as e:
                status("evidence", f"TPE execution failed: {e}")
                logging.getLogger(__name__).error("TPE execution failed", exc_info=True)
                evidence_results["tpe"] = {
                    "tpe_text": f"Error running Temporal Pattern Engine: {e}",
                    "tpe_report": {"error": f"Failed to run TPE: {e}"}
                }

        # Log parallel results
        conditions = evidence_results["conditions"]["conditions"]
        conditions_text = evidence_results["conditions"]["conditions_text"]
        tpe_report = evidence_results["tpe"]["tpe_report"]
        if tpe_report:
            self.memory.log_step(session_id, "tpe", {
                "pattern_count": tpe_report.get("pattern_count", 0),
                "triggered_count": tpe_report.get("triggered_count", 0),
                "unresolved_variables": tpe_report.get("unresolved_count", 0),
                "missing_can_signals": tpe_report.get("missing_can_count", 0),
                "has_triggers": tpe_report.get("triggered_count", 0) > 0,
            })
        self.memory.log_step(session_id, "conditions", {
            "has_conditions": "error" not in conditions,
            "preview": conditions_text[:300],
        })

        # --- Sequential phase: probe (depends on conditions + TPE) ---
        probe_section = ""
        probe_plans: list = []
        probe_results_list: list = []
        probe_cfg = (self.config.get("ai", {}) or {}).get("variable_probe", {}) or {}
        probe_enabled = probe_cfg.get("enabled", True)
        if probe_enabled and store is not None:
            try:
                status("evidence", "Planning variable queries...")
                planner = VariableQueryPlanner(self.router, self.memory, self.project_root, self.config)
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
                    status("evidence", f"Executing {len(probe_plans)} probe queries...")
                    probe = DataProbe(store, windows=windows or [])
                    for qp in probe_plans:
                        try:
                            probe_results_list.append(probe.query(**qp.to_query_args()))
                        except Exception as e:
                            probe_results_list.append({
                                "field": qp.field, "table": qp.table,
                                "row_count": 0, "error": f"probe exec error: {e}",
                            })
                    probe_section = render_probe_results_for_prompt(
                        probe_plans, probe_results_list,
                        max_chars=int(probe_cfg.get("max_chars", 6000)),
                    )
                    self.memory.log_step(session_id, "variable_probe", {
                        "plan_count": len(probe_plans),
                        "plans": [p.to_dict() for p in probe_plans],
                        "result_preview": probe_section[:500],
                    })
            except Exception as e:
                status("evidence", f"Variable probe skipped: {e}")

        # --- Deterministic investigation: join code conditions with data ---
        # EngineeringInvestigator produces bounded ConditionCheck[] evidence
        # WITHOUT an LLM — feeds the panel as advisory, traceable facts.
        investigation_section = ""
        investigation_checks = 0
        try:
            if store is not None:
                from .investigation_engine import EngineeringInvestigator

                inventory = store.get_signal_inventory() or []
                signal_lookup: dict[str, dict] = {}
                for item in inventory:
                    msg = item.get("message_name", "")
                    can_hex = item.get("can_id_hex", "")
                    can_id = item.get("can_id", "")
                    for sig in item.get("signals", []) or []:
                        signal_lookup[str(sig)] = {
                            "can_id": can_id,
                            "can_id_hex": can_hex,
                            "message_name": msg,
                        }
                plan = {
                    "functions": [func_name],
                    "code_symbols": list(func_info.get("key_variables", []) or []),
                    "can_signals": list(classification.focus_signals or []),
                    "query_type": "diagnosis",
                    "need_code_analysis": True,
                }
                investigation = EngineeringInvestigator(
                    self.config, self.project_root,
                ).investigate(store, problem or "", plan, signal_lookup)
                investigation_checks = len(investigation.condition_checks)
                investigation_section = investigation.to_prompt_text(
                    max_chars=int((self.config.get("ai", {}) or {}).get(
                        "investigation_max_chars", 10000,
                    )),
                )
                if investigation_checks:
                    status(
                        "evidence",
                        f"Deterministic investigation: {investigation_checks} condition checks",
                    )
                    self.memory.log_step(session_id, "investigation", {
                        "condition_checks": investigation_checks,
                        "deterministic_conclusion": getattr(
                            investigation, "deterministic_conclusion_available", False,
                        ),
                    })
        except Exception as e:
            status("evidence", f"Deterministic investigation skipped: {e}")
            investigation_section = ""

        # ═══════════════════════════════════════════════════════════════════
        # Step 5: SIGNALS — suppression + output signals (deterministic)
        # ═══════════════════════════════════════════════════════════════════
        status("signals", "Analyzing CAN signals...")

        # Suppression signals
        suppression_text = ""
        suppression_signals = conditions.get("external_suppression", [])
        if suppression_signals and store.get_can_ids():
            status("signals", f"Checking {len(suppression_signals)} suppression signals...")
            suppression_text = self._check_suppression_signals(
                store, suppression_signals, windows, func_name, status,
            )
            self.memory.log_step(session_id, "suppression_check", {
                "signal_count": len(suppression_signals),
                "result_preview": suppression_text[:500],
            })
        elif suppression_signals:
            status("signals", "No CAN data for suppression check")

        # Output signals
        output_signal_text = ""
        if store.get_can_ids():
            status("signals", f"Analyzing output signals for {func_name}...")
            output_signal_text = self._analyze_output_signals(
                store, func_name, windows, status,
            )
            if output_signal_text:
                self.memory.log_step(session_id, "output_signal_analysis", {
                    "result_preview": output_signal_text[:500],
                })

        # Key-chain signal audit (enum validity + UI-mode echo contract)
        signal_audit_text = ""
        if store.get_can_ids():
            status("signals", "Auditing key-chain signals (enum/contract)...")
            signal_audit_text = self._run_signal_audit(store, status)
            if signal_audit_text:
                self.memory.log_step(session_id, "signal_audit", {
                    "result_preview": signal_audit_text[:500],
                })

        # Threshold reference
        threshold_ref = self._load_threshold_reference(func_name)

        # Parameter sensitivity (tune/verify only)
        param_section_md = ""
        param_report_obj = None
        whatif_entries: list = []
        if task_type in ("tune", "verify"):
            try:
                status("signals", "Running parameter sensitivity analysis...")
                param_report_obj = analyze_sensitivity(
                    source_root=Path(self.config["paths"]["source_code"]),
                    cache_dir=self.source_docs_dir,
                    store=store,
                    func_name=func_name,
                    focus_categories=classification.focus_parameters or None,
                )
                param_section_md = render_sensitivity_markdown(param_report_obj)
                status("signals",
                    f"Parameters: {param_report_obj.total_parameters} scanned, "
                    f"{param_report_obj.parameters_analyzed} observable")
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
                        status("signals", f"What-if: {len(whatif_entries)} proposal(s)")
                        self.memory.log_step(session_id, "param_whatif", {
                            "count": len(whatif_entries),
                            "items": [w.to_dict() for w in whatif_entries[:20]],
                        })
            except Exception as exc:
                status("signals", f"Parameter analysis failed: {exc}")
                param_section_md = ""

        # ═══════════════════════════════════════════════════════════════════
        # Step 6: DIAGNOSE — Expert Panel (LangGraph, multi-LLM)
        # ═══════════════════════════════════════════════════════════════════
        status("diagnose", "Building expert panel context...")

        # Load CodeGraph context
        codegraph_section = ""
        semantics_section = ""
        # Deterministic index products (codegraph/conditions) are rebuildable,
        # so fail-open when there is no freshness baseline yet; only block when
        # the baseline exists and says the code has drifted (stale index).
        try:
            from core.knowledge_guard import runtime_knowledge_decision
            _freshness = (self.config.get("identity") or {}).get("freshness") or {}
            _cg_decision = runtime_knowledge_decision(self.config, "codegraph")
            if _freshness.get("previous_state_available"):
                cg_allowed = bool(_cg_decision.allowed)
            else:
                cg_allowed = True
        except Exception:
            cg_allowed = True
        try:
            from .codegraph import CodeGraph, CodeGraphRenderer
            cg_path = self.codegraph_db_path
            if cg_path.exists() and cg_allowed:
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
                sem_md = renderer.render_semantics_for_panel(
                    module=func_name,
                    max_chars=5000,
                )
                if sem_md:
                    semantics_section = f"""## ★★ 语义标注层(Semantic Annotations) ★★
{sem_md}

**语义标注使用说明**: 以上为系统通过 LLM 对 C 源码进行的语义分析结果，
包含告警逻辑、计算链路、状态机、输出链路等维度的深度理解。
与 CodeGraph 结构数据配合使用：CodeGraph 告诉你「代码怎么写的」，
语义标注告诉你「代码在做什么」。
"""
                cg.close()
        except Exception:
            import logging
            logging.getLogger(__name__).warning('Operation failed (silent failure caught)')
            pass  # silent fallback — CodeGraph is optional enhancement

        # Build data summary
        memory_context = self.memory.build_context_for_diagnosis(func_name, problem, case_dir)
        data_summary = self._build_data_summary(store, bag_meta, blf_meta, sync)
        material_section = ""
        material_summary = {}
        if self.identity.variant_id:
            try:
                from core.materials import render_material_summary
                material_summary = render_material_summary(
                    self.project_root,
                    self.identity.variant_id,
                    max_chars=4000,
                )
                material_section = material_summary.get("prompt_text", "")
                if material_summary:
                    self.memory.log_step(session_id, "materials", {
                        k: v for k, v in material_summary.items() if k != "prompt_text"
                    })
            except Exception as exc:
                status("diagnose", f"Material summary skipped: {exc}")

        # Pop evidence components
        key_facts = evidence.pop("KEY_FACTS", "")
        timeline = evidence.pop("timeline", [])
        transitions = evidence.pop("state_transitions", [])
        tpe_block = evidence.pop("tpe_block", "") or ""
        tpe_report_data = evidence.pop("tpe_report", None)

        evidence_text = json.dumps(evidence, ensure_ascii=False, default=str, indent=1)
        if len(evidence_text) > 20000:
            evidence_text = evidence_text[:20000] + "\n... (truncated)"

        timeline_text = FrameAnalyzer.format_timeline(timeline, max_lines=300, func_name=func_name)
        windows_text = format_windows(windows)

        transitions_text = ""
        if transitions:
            t_lines = [f"  t={tr['t']}s {tr['side']} {tr['field']}: {tr['from']}→{tr['to']}"
                       for tr in transitions[:30]]
            transitions_text = "\n".join(t_lines)
        else:
            transitions_text = "(无状态跳变)"

        # Build TPE section — use the saved tpe_block from pop above
        tpe_section = ""
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

        # Build suppression section
        suppression_section = ""
        if suppression_text:
            suppression_section = f"""
## ★★★ 外部抑制信号实测(最高优先级) ★★★
{suppression_text}

**数据溯源规则**: 以上为系统从BLF/BAG中实际提取并验证的抑制信号状态。
专家分析时**必须以上述实测数据为准**，不得自行从其他数据源推断抑制信号状态。
如某信号标注"未在BLF中找到"，结论应为"无法确认"而非自行查找替代信号。
"""

        # Build output section
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

        # Build threshold section
        threshold_section = ""
        if threshold_ref:
            threshold_section = f"""
## ★★ 权威阈值参考(来自source_docs/{func_name}.md) ★★
{threshold_ref}

**规则**: 报告中引用的所有阈值必须与上述文档一致。禁止使用"预估"阈值。
"""

        # Build params section
        params_section = ""
        if param_section_md:
            whatif_md_section = render_what_if_markdown(whatif_entries) if whatif_entries else ""
            params_section = f"""
## ★★ 参数敏感性分析(tune/verify 专属) ★★
任务类型: **{task_type}** — 分析目标不是根因，而是参数调整后的量化影响。
{param_section_md}

{whatif_md_section}

**规则**: 本节所有数值均为系统从源码+本次录制直接计算得到。
建议调优时必须基于上表中"穿越次数"、"min |Δ|"、"超阈值帧数"几列做判断，
禁止仅凭直觉给方向；若提出新的阈值值，需指明该值在本次录制中的新穿越次数。
"""

        # ContextBudget assembly
        methodology_block = """## ★★★ 因果链分析方法论(最高优先级) ★★★
分析时必须区分数据的因果层次:
- **观测层**(雷达端radar_objects/radar_debug): 仅说明「发生了什么」，是ECU决策的**结果**
- **代码逻辑层**(算法核心/平台状态文件): 说明「为什么发生」
- **信号输入层**(信号映射→CAN信号): 说明「什么触发了代码逻辑」
根因 = 信号输入层或代码逻辑层的具体问题。**禁止将观测层的状态直接作为根因。**
追溯方法: 看到异常状态 → 查代码中哪行赋值了此状态 → 该赋值依赖哪个变量/条件 → 该变量来自哪个CAN信号 → CAN信号实际值是什么"""

        # Dynamic ContextBudget — scales with case complexity
        # Estimate case duration from store time range
        _case_duration = 0.0
        if store is not None:
            try:
                _tr = store.get_time_range()
                if _tr:
                    _case_duration = (_tr[1] - _tr[0]).total_seconds() if hasattr(_tr[1], 'total_seconds') else float(_tr[1] - _tr[0])
            except Exception:
                import logging
                logging.getLogger(__name__).warning('Operation failed (silent failure caught)')
                pass
        _cg_nodes = 0
        try:
            _cg_db = self.codegraph_db_path
            if _cg_db.exists():
                import sqlite3 as _sql
                _conn = _sql.connect(str(_cg_db))
                _cg_nodes = _conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
                _conn.close()
        except Exception:
            import logging
            logging.getLogger(__name__).warning('Operation failed (silent failure caught)')
            pass
        _budget_total = compute_budget(
            codegraph_nodes=_cg_nodes,
            test_window_count=len(windows) if windows else 0,
            case_duration_sec=_case_duration,
        )

        budget = ContextBudget(total_chars=_budget_total)
        budget.add("methodology",   methodology_block, priority=100, min_chars=400)
        budget.add("key_facts",     f"## ★ 关键事实(必读) ★\n{key_facts}", priority=100, min_chars=2000)
        budget.add("tpe",           tpe_section,       priority=95,  min_chars=2000)
        budget.add("constants",     constants_section, priority=94,  min_chars=800)
        budget.add("probe",         probe_section,     priority=93,  min_chars=1500)
        budget.add("investigation", investigation_section, priority=92, min_chars=1000)
        budget.add("suppression",   suppression_section, priority=92, min_chars=1000)
        budget.add("output",        output_section,    priority=90,  min_chars=1500)
        if signal_audit_text:
            budget.add("signal_audit",  f"## ★ 关键链路信号审计(确定性枚举/契约校验) ★\n{signal_audit_text}", priority=92, min_chars=800)
        budget.add("windows",       f"## ★ 测试窗口(必读) ★\n{windows_text}", priority=90, min_chars=400)
        budget.add("transitions",   f"## 状态跳变\n{transitions_text}", priority=85, min_chars=600)
        budget.add("conditions",    f"## ★ 条件检查表(代码提取) ★\n{conditions_text}", priority=80, min_chars=1500)
        budget.add("threshold",     threshold_section, priority=75,  min_chars=1000)
        budget.add("materials",     material_section,  priority=74,  min_chars=700)
        budget.add("params",        params_section,    priority=70,  min_chars=1000)
        budget.add("codegraph",     codegraph_section, priority=72,  min_chars=800)
        budget.add("semantics",     semantics_section, priority=73,  min_chars=600)
        budget.add("timeline",      f"## 窗口内数据时间线\n{timeline_text[:10000]}", priority=60, min_chars=2000)
        budget.add("frame_anal",    f"## 帧分析\n{frame_analysis[:6000]}", priority=55, min_chars=1500)
        budget.add("evidence",      f"## 数据取证\n{evidence_text}", priority=55, min_chars=3000)
        budget.add("data_summary",  f"## 数据概览\n{data_summary[:5000]}", priority=40, min_chars=1000)

        combined_data = budget.concat()
        status("diagnose", budget.format_report())

        # Run expert panel
        n_experts = len(ExpertPanel.select_experts(func_info.get("fail_type", "OTHER")))
        status("diagnose", f"Launching expert panel ({n_experts} experts, 3 rounds)...")
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

        # ═══════════════════════════════════════════════════════════════════
        # Step 7: FIX — CodeFixEngine diff generation (1 LLM)
        # ═══════════════════════════════════════════════════════════════════
        fix_report_md = ""
        try:
            status("fix", "Generating code fix suggestions...")
            fix_report_md = self._generate_code_fix(
                problem=problem,
                diagnosis=diagnosis,
                func_name=func_name,
                status=status,
            )
            if fix_report_md:
                status("fix", "Code fix generated successfully")
            else:
                status("fix", "No actionable code fix generated")
        except Exception as exc:
            status("fix", f"Code fix generation failed: {exc}")

        # ═══════════════════════════════════════════════════════════════════
        # Step 8: DELIVER — Report + visualize + memory (deterministic)
        # ═══════════════════════════════════════════════════════════════════
        status("deliver", "Generating report...")
        report_path = self._save_report(
            case_dir, diagnosis, problem, expected,
            func_name, bag_meta, blf_meta, windows,
            task_type=task_type,
            param_report_md=param_section_md,
            whatif_md=whatif_md,
            fix_report_md=fix_report_md,
            snapshot_id=self.identity.snapshot_id,
        )

        expert_appendix_path = case_dir / "expert_opinions.md"
        self._save_expert_appendix(expert_appendix_path, panel_result)

        # Visualization
        try:
            status("deliver", "Rendering HTML visualization...")
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
            status("deliver", f"HTML report: {viz.html_path} (charts={viz.charts_built})")
            self.memory.log_step(session_id, "visualize", viz.to_dict())
        except Exception as exc:
            status("deliver", f"Visualization failed: {exc}")

        # Memory update
        try:
            self._update_memories(session_id, case_dir, func_name, func_info, diagnosis, problem)
        except Exception:
            import logging
            logging.getLogger(__name__).warning('Operation failed (silent failure caught)')
            pass

        # L6 code knowledge precipitation from diagnosis
        try:
            status("deliver", "Precipitating code knowledge to L6...")
            self._precipitate_knowledge(
                func_name=func_name,
                panel_result=panel_result,
                conditions=conditions,
                evidence=evidence,
            )
            status("deliver", "L6 knowledge precipitation done")
        except Exception:
            import logging
            logging.getLogger(__name__).warning('Operation failed (silent failure caught)')
            pass
        self.memory.complete_session(session_id, f"Report saved to {report_path}")
        status("deliver", f"Diagnosis complete: {report_path}")

        if store:
            store.close()

        # ══ Save DiagnosisBundle (structured output) ════════════════
        try:
            status("deliver", "Saving DiagnosisBundle...")
            bundle_path = self._save_diagnosis_bundle(
                case_dir=case_dir,
                problem=problem,
                expected=expected,
                func_name=func_name,
                task_type=task_type,
                classification=classification.to_dict(),
                panel_result=panel_result,
                conditions=conditions,
                evidence=evidence,
                probe_results=probe_results_list,
                windows=windows,
                bag_meta=bag_meta,
                blf_meta=blf_meta,
                tpe_result=self._last_tpe_result,
                param_report=param_report_obj,
                whatif_entries=whatif_entries,
                fix_report=fix_report_md,
                step_logger=step_logger,
                token_tracker=token_tracker,
            )
            status("deliver", f"DiagnosisBundle saved: {bundle_path}")
        except Exception as exc:
            status("deliver", f"DiagnosisBundle save failed: {exc}")

        # Save observability log
        try:
            obs_log_path = case_dir / "observability_log.json"
            step_logger.save(obs_log_path)
            status("deliver", f"Step log saved: {obs_log_path}")
        except Exception:
            import logging
            logging.getLogger(__name__).warning('Operation failed (silent failure caught)')
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
            from engines.tpe import TemporalPatternEngine
            from engines.signal_mapper import (
                extract_signal_mapping, trace_variable_chains,
                load_variable_chains, extract_output_signal_mapping,
                build_expr_to_can_index, load_output_chain_aliases,
            )
        except Exception as exc:
            status("tpe", f"TPE modules unavailable: {exc}")
            return "", {}

        source_root = Path(self.config["paths"]["source_code"])
        docs_dir = self.source_docs_dir
        knowledge_dir = self.memory.memory_dir / "code_knowledge"

        # Phase 15 (2.1.3): reuse pre-loaded maps; fall back to per-call load
        # if pre-load failed or returned empty.
        sig_mapping = self.signal_mapping
        if not sig_mapping:
            try:
                sig_mapping = extract_signal_mapping(source_root, docs_dir)
            except Exception as exc:
                status("tpe", f"Signal mapping failed: {exc}")
                sig_mapping = {}

        chains = self.variable_chains
        if not chains.get("struct_aliases"):
            try:
                chains = load_variable_chains(docs_dir)
                if not chains.get("struct_aliases"):
                    chains = trace_variable_chains(source_root, docs_dir)
            except Exception:
                chains = {}

        # WriteSignal-side data for resolving output variables that never
        # appear in the ReadSignal mapping (e.g. bLcaLeftWarningFlg).
        out_mapping = self.output_signal_mapping
        if not out_mapping:
            try:
                out_mapping = extract_output_signal_mapping(source_root, docs_dir)
            except Exception as exc:
                status("tpe", f"Output mapping failed: {exc}")
                out_mapping = {}
        try:
            build_expr_to_can_index(out_mapping)  # caches into out_mapping
        except Exception:
            pass
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
        from engines.signal_mapper import (
            extract_output_signal_mapping, get_output_signals_for_function,
        )

        # Phase 15 (2.1.3): reuse pre-loaded output mapping if available.
        out_mapping = self.output_signal_mapping
        if not out_mapping:
            out_mapping = extract_output_signal_mapping(
                Path(self.config["paths"]["source_code"]),
                self.source_docs_dir,
                rte_file=self._resolve_signal_mapping_source(),
            )
        # Variant-truth output signals: prefer signals actually written by
        # this variant's RteComMapping_Tx*.c and present in the DBC/BLF over
        # the legacy GWM-era hardcoded table.
        inventory = store.get_signal_inventory() or []
        dbc_signals: set[str] = set()
        for item in inventory:
            dbc_signals.update(item.get("signals", []))
        tx_signals = out_mapping.get("signal_to_expr", {})
        target_signals = get_output_signals_for_function(
            func_name,
            tx_signals=tx_signals,
            dbc_signals=dbc_signals,
            internal_to_can=self.signal_mapping.get("internal_to_can"),
        )
        if not target_signals:
            return ""

        status("output_signals", f"Target output signals: {', '.join(target_signals)}")
        sig_to_expr = out_mapping.get("signal_to_expr", {})

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

            # Window-based analysis for output signals
            if windows and len(windows) > 0:
                win_eval = self._evaluate_output_in_windows(timeline, windows)
                act_ratio = win_eval["activation_ratio"]
                win_total = win_eval["window_total"]
                win_label = "窗口内持续输出" if act_ratio > 0.8 else "窗口内间歇输出" if act_ratio > 0.3 else "窗口内无输出"
                lines.append(
                    f"  📊 **窗口分析**: {win_label} — "
                    f"{act_ratio*100:.0f}% 窗口帧有输出 ({win_eval['window_active']}/{win_total})"
                )

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

    # ── Key-chain signal audit (enum validity + contract) ─────────────

    def _run_signal_audit(self, store, status) -> str:
        """Run the deterministic key-chain signal audit (M10 engine).

        Checks the switch send/receive chain signals against the contract
        table: presence, value distribution, DBC enum validity and
        cross-signal contracts (e.g. old UI does not echo the FCTA/FCTB
        status). Returns markdown for the panel context; empty when the
        case carries no CAN data or no DBC loader is available.
        """
        if not store.get_can_ids() or self._case_dbc is None:
            return ""
        try:
            from engines.signal_audit import SignalAuditEngine
            engine = SignalAuditEngine()
            result = engine.audit(store, self._case_dbc)
            parts = [result["markdown"]]
            if result["contract_note"]:
                parts.append(result["contract_note"])
            return "\n\n".join(parts)
        except Exception as exc:  # noqa: BLE001 - audit must never break diagnosis
            status("signals", f"Signal audit skipped: {exc}")
            return ""

    # ── Suppression signal checker ─────────────────────────────────────

    def _check_suppression_signals(
        self, store, suppression_signals: list[dict],
        windows, func_name: str, status,
    ) -> str:
        """
        Check CAN data for active suppression signals identified by the
        condition extractor.  Uses signal_mapping.json (from project-specific
        signal mapping) to resolve internal variable names -> DBC CAN signal names.

        Key features:
        - Threshold-aware evaluation: parses threshold field to determine
          whether suppression condition is met (not just nonzero check)
        - Semantic fallback: when variable is a macro/function/compound expr,
          uses signal_chain categories to find related signals
        """
        from difflib import get_close_matches
        from engines.signal_mapper import (
            extract_signal_mapping, resolve_internal_to_can, _extract_core_keyword,
            trace_variable_chains, load_variable_chains,
        )

        # Phase 15 (2.1.3): reuse pre-loaded maps when available.
        sig_mapping = self.signal_mapping
        if not sig_mapping:
            sig_mapping = extract_signal_mapping(
                Path(self.config["paths"]["source_code"]),
                self.source_docs_dir,
            )
        chains = self.variable_chains
        if not chains.get("struct_aliases"):
            chains = load_variable_chains(self.source_docs_dir)
            if not chains.get("struct_aliases"):
                chains = trace_variable_chains(
                    Path(self.config["paths"]["source_code"]),
                    self.source_docs_dir,
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

                # Window-based time correlation analysis
                window_eval = None
                if windows and len(windows) > 0:
                    window_eval = self._evaluate_in_windows(timeline, windows, threshold)

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
                if window_eval:
                    sup_ratio = window_eval["suppression_ratio"]
                    win_count = window_eval["window_count"]
                    win_total = window_eval["window_total"]
                    win_label = "全程抑制" if sup_ratio > 0.8 else "间歇抑制" if sup_ratio > 0.3 else "窗口内未抑制"
                    sub_results.append(
                        f"    📊 **窗口分析**: {win_label} — "
                        f"{sup_ratio*100:.0f}% 窗口帧触发抑制 ({win_count}/{win_total})"
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

    def _evaluate_in_windows(self, timeline: list[tuple[float, any]], windows, threshold: str) -> dict:
        """Evaluate suppression condition within test windows.

        Args:
            timeline: List of (timestamp, value) tuples.
            windows: List of TestWindow or dict with start_t / end_t.
            threshold: Threshold string (same format as _evaluate_threshold).

        Returns:
            {"suppression_ratio": float, "window_count": int, "window_total": int}
        """
        if not timeline or not windows:
            return {"suppression_ratio": 0.0, "window_count": 0, "window_total": 0}

        # Build window time ranges
        window_ranges: list[tuple[float, float]] = []
        for w in windows:
            if hasattr(w, 'start_t'):
                window_ranges.append((w.start_t, w.end_t))
            elif isinstance(w, dict):
                start = w.get("start_t", w.get("t_start", 0))
                end = w.get("end_t", w.get("t_end", 0))
                window_ranges.append((start, end))

        if not window_ranges:
            return {"suppression_ratio": 0.0, "window_count": 0, "window_total": 0}

        # Count window frames that match suppression condition
        window_total = 0
        window_met = 0
        for t, v in timeline:
            if not isinstance(v, (int, float)):
                continue
            for ws, we in window_ranges:
                if ws <= t <= we:
                    window_total += 1
                    # Use threshold evaluation
                    met = self._single_value_matches_threshold(v, threshold)
                    if met:
                        window_met += 1
                    break

        ratio = (window_met / window_total) if window_total > 0 else 0.0
        return {
            "suppression_ratio": ratio,
            "window_count": window_met,
            "window_total": window_total,
        }

    @staticmethod
    def _single_value_matches_threshold(value: float, threshold: str) -> bool:
        """Check if a single value matches the suppression threshold."""
        import re
        thr = threshold.strip().upper().replace(" ", "")

        if thr in ("TRUE", "!=0", "==TRUE", "==1"):
            return value != 0
        if thr in ("FALSE", "==0", "==FALSE", "!=TRUE"):
            return value == 0

        m = re.match(r'^(>=?|<=?|==|!=)([-\d.]+)$', thr)
        if m:
            op, val_s = m.group(1), float(m.group(2))
            ops = {
                ">": lambda v: v > val_s, ">=": lambda v: v >= val_s,
                "<": lambda v: v < val_s, "<=": lambda v: v <= val_s,
                "==": lambda v: v == val_s, "!=": lambda v: v != val_s,
            }
            fn = ops.get(op)
            if fn:
                return fn(value)

        return value != 0

    @staticmethod
    def _evaluate_output_in_windows(timeline: list[tuple[float, any]], windows) -> dict:
        """Evaluate output signal activation within test windows."""
        if not timeline or not windows:
            return {"activation_ratio": 0.0, "window_active": 0, "window_total": 0}

        window_ranges: list[tuple[float, float]] = []
        for w in windows:
            if hasattr(w, 'start_t'):
                window_ranges.append((w.start_t, w.end_t))
            elif isinstance(w, dict):
                window_ranges.append((w.get("start_t", 0), w.get("end_t", 0)))

        if not window_ranges:
            return {"activation_ratio": 0.0, "window_active": 0, "window_total": 0}

        window_total = 0
        window_active = 0
        for t, v in timeline:
            if not isinstance(v, (int, float)):
                continue
            for ws, we in window_ranges:
                if ws <= t <= we:
                    window_total += 1
                    if v != 0:
                        window_active += 1
                    break

        ratio = (window_active / window_total) if window_total > 0 else 0.0
        return {
            "activation_ratio": ratio,
            "window_active": window_active,
            "window_total": window_total,
        }

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
        from engines.signal_mapper import resolve_internal_to_can

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
        doc_path = self.source_docs_dir / f"{func_name}.md"
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
        docs_dir = self.source_docs_dir
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
        docs_dir = self.source_docs_dir
        adapter = self._get_code_learner_adapter()
        learner = CodeLearner(self.router, self.config, self.project_root,
                              platform_adapter=adapter or None)
        result = learner.ensure_overview_docs(
            funcs=ALL_FUNCTIONS,
            status_cb=lambda step, msg: status("source_docs", msg),
        )
        if result.get("generated"):
            status("source_docs", f"Generated: {', '.join(result['generated'])}")
        for failed in result.get("failed") or []:
            status("source_docs", f"[WARN] {failed['func']} failed: {failed['error']}")
        if not result.get("failed") and not result.get("error"):
            try:
                from core.knowledge_guard import publish_knowledge_categories

                publish_knowledge_categories(
                    self.config,
                    [
                        f"source_docs:{str(function).upper()}"
                        for function in (
                            result.get("generated", []) + result.get("skipped", [])
                        )
                    ],
                    producer="diagnosis.source_docs",
                )
            except Exception as exc:
                status("source_docs", f"Freshness not published: {exc}")

        sig_map_path = docs_dir / "signal_mapping.json"
        if not sig_map_path.exists():
            status("source_docs", "Building CAN signal ↔ internal variable mapping...")
            from engines.signal_mapper import extract_signal_mapping
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
            from config import get_variable_filter

            source_root = Path(self.config["paths"]["source_code"])
            key_files = self.config.get("paths", {}).get("key_source_files", [])

            db_path = self.codegraph_db_path
            db_path.parent.mkdir(parents=True, exist_ok=True)
            calib_files = [
                p for p in key_files
                if "paraDefine" in p or "structDefine" in p or "globalVarDefine" in p
            ]

            # Phase 5B: variable filter
            variable_filter = get_variable_filter(self.config)

            # Use adapter-supplied func_keywords when available
            adapter = self._get_code_learner_adapter()
            if adapter:
                _funcs = adapter.get_priority_functions()
                _adapter_kw: dict = {}
                for _f in _funcs:
                    _adapter_kw[_f] = adapter.get_func_keywords(_f)
            else:
                _adapter_kw = {}

            # ✨ Gen5: pass platform_id for full scan support
            pid = self.platform_id

            # Merge adapter keywords into base FUNC_KEYWORDS when adapter available
            func_keywords = {**FUNC_KEYWORDS, **_adapter_kw}

            builder = CodeGraphBuilder(
                db_path=db_path,
                source_root=source_root,
                key_files=key_files,
                func_keywords=func_keywords,
                calib_files=calib_files,
                source_docs_dir=self.source_docs_dir,
                variable_filter=variable_filter,
                platform_id=pid if pid and pid.startswith("gen5") else None,
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
            if result.build_type == "skip" or result.success:
                try:
                    from core.knowledge_guard import publish_knowledge_categories

                    publish_knowledge_categories(
                        self.config, ["codegraph"], producer="diagnosis.codegraph",
                    )
                except Exception as exc:
                    status("codegraph", f"Freshness not published: {exc}")

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

        cg_path = self.codegraph_db_path
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
        docs_dir = self.source_docs_dir
        for fn in matched_funcs:
            md = docs_dir / f"{fn}.md"
            if not md.exists():
                continue
            try:
                content = md.read_text(encoding="utf-8")
                source_summaries += f"\n### {fn}\n{content[:2000]}\n"
            except Exception:
                import logging
                logging.getLogger(__name__).warning('Operation failed (silent failure caught)')
                pass

        # CodeGraph: inject structured code context
        codegraph_md = ""
        try:
            from .codegraph import CodeGraph, CodeGraphRenderer
            cg_path = self.codegraph_db_path
            if cg_path.exists():
                cg = CodeGraph(cg_path)
                renderer = CodeGraphRenderer(cg)
                for fn in matched_funcs:
                    md_text = renderer.render_for_problem(fn, problem, max_chars=3000)
                    if md_text:
                        codegraph_md += f"\n{md_text}\n"
                cg.close()
        except Exception:
            import logging
            logging.getLogger(__name__).warning('Operation failed (silent failure caught)')
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
        # Keep the DBC loader for the Step-5 signal audit (enum validity checks).
        self._case_dbc = r.dbc
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

        try:
            result = self.router.chat(
                [{"role": "user", "content": prompt}],
                complexity="simple",
                max_tokens=1024,
            )
            content = result.get("content") if isinstance(result, dict) else None
            if content:
                return content
            status("analyze", "Frame analysis LLM returned empty; falling back to raw warning summary.")
        except Exception as exc:  # noqa: BLE001 - degrade, never abort diagnosis
            status("analyze", f"Frame analysis LLM failed ({type(exc).__name__}: {exc}); using deterministic fallback.")
        return json.dumps(warning_analysis, default=str, ensure_ascii=False)[:2000]

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
                     fix_report_md: str = "",
                     snapshot_id: str = "") -> str:
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        diagnosis = _normalize_report_section_headings(diagnosis)

        title_map = {
            "diagnose": "角雷达问题诊断报告",
            "tune":     "角雷达参数调优分析报告",
            "verify":   "角雷达参数变更验证报告",
            "query":    "角雷达信息检索报告",
        }
        method_map = {
            "diagnose": "窗口检测 + 条件提取 + TPE + 5专家面板\u00d73轮",
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
        if self.identity.variant_id:
            header += f"| Variant | `{self.identity.variant_id}` |\n"
        if self.identity.package_profile_id:
            header += f"| Package | `{self.identity.package_profile_id}` |\n"
        if self.identity.project_key:
            header += f"| Project | `{self.identity.project_key}` |\n"
        if snapshot_id:
            header += f"| 快照ID | `{snapshot_id}` |\n"
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
            import logging
            logging.getLogger(__name__).warning('Operation failed (silent failure caught)')
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

    def _precipitate_knowledge(
        self,
        func_name: str,
        panel_result: dict,
        conditions: dict,
        evidence: dict,
    ):
        """从诊断结果中提取可沉淀的代码知识，增量合并到 L6 code_knowledge。

        从 expert_panel 的 expert_opinions / final_verdict 中提取：
        - **alarm_logic**: 报警触发/取消条件（从专家分析中的条件检查表）
        - **state_machine**: 状态机流转（从状态转移描述）
        - **calculation_chain**: 关键变量/阈值（从数据链路和计算链）

        所有条目带 ``_precipitated`` 标记和 ``code_ref``，便于与 CodeLearner 来源区分。
        幂等：相同 id 的条目用新内容覆盖旧内容。
        """
        import re

        precipitate_prompt = f"""你是代码知识沉淀专家。请从以下诊断结果中提取结构化代码知识，写入 L6 code_knowledge。

功能: {func_name}

## 专家结论
{panel_result.get("final_verdict", "")[:3000]}

## 各专家分析
{json.dumps(panel_result.get("expert_opinions", {}), ensure_ascii=False, indent=2)[:5000]}

## 条件检查
{json.dumps(conditions, ensure_ascii=False, indent=2)[:3000]}

## 关键证据
{json.dumps(evidence, ensure_ascii=False, indent=2)[:3000]}

请输出 JSON（只输出 JSON）：
{{
  "alarm_logic": {{
    "trigger_conditions": [
      {{"id": "diag-TRIG-1", "description": "一句话描述", "threshold": "阈值", "c_expression": "代码条件", "variables": ["变量1"], "code_ref": {{"file": "文件名", "line": 行号}}}}
    ],
    "cancel_conditions": [...],
    "block_conditions": [
      {{"id": "diag-BLOCK-1", "description": "导致功能不触发的拦截条件", "threshold": "阈值", "actual_value": "实测值", "c_expression": "拦截条件", "variables": ["变量1"], "code_ref": {{"file": "文件名", "line": 行号}}}}
    ]
  }},
  "state_machine": {{
    "transitions": [
      {{"id": "diag-TR-1", "from": "状态A", "to": "状态B", "condition": "转移条件", "action": "转移动作", "code_ref": {{"file": "文件名", "line": 行号}}}}
    ],
    "blocked_transitions": [
      {{"id": "diag-BTR-1", "from": "当前状态", "expected_to": "期望状态", "blocked_by": "阻塞原因", "code_ref": {{"file": "文件名", "line": 行号}}}}
    ]
  }},
  "calculation_chain": {{
    "key_variables": {{
      "变量名": {{"description": "变量描述", "formula": "计算公式", "inputs": ["输入变量"], "actual_value": "实测值", "code_ref": {{"file": "文件名", "line": 行号}}}}
    }},
    "thresholds_used": [
      {{"name": "阈值名", "value": "阈值", "role": "用途", "id": "diag-TH-1"}}
    ],
    "derivation_chain": [
      {{"step": 1, "from": "输入", "to": "输出", "in_file": "文件", "transform": "转换描述"}}
    ]
  }},
  "output_chain": {{
    "blocked_outputs": [
      {{"id": "diag-BO-1", "internal_var": "内部变量", "expected_output": "期望输出", "actual_output": "实际输出", "blocked_by": "阻塞原因", "code_ref": {{"file": "文件名", "line": 行号}}}}
    ]
  }}
}}

要求:
1. 只提取诊断中明确提到的知识，不要编造
2. 所有 id 以 "diag-" 开头，避免与 CodeLearner 冲突
3. code_ref 必须来自诊断中提到的具体文件/行号
4. 如果某个焦点没有新发现，留空数组/对象
5. block_conditions / blocked_transitions / blocked_outputs 是新的知识类型，记录"导致功能不触发的原因"
"""
        try:
            result = self.router.complex(
                [{"role": "user", "content": precipitate_prompt}],
                max_tokens=8192,
            )
            precipitated = parse_json_from_llm(
                result.get("content", ""),
                context="precipitate_knowledge",
            )
            if not precipitated:
                return

            # Build the updates dict (with _precipitated provenance markers) and
            # delegate to the single L6 writer (merge_code_knowledge), which
            # merges into the raw base so CodeLearner data is never clobbered
            # when freshness is stale.
            now = datetime.datetime.now().isoformat()
            updates: dict = {}
            for focus in ["alarm_logic", "state_machine", "calculation_chain", "output_chain"]:
                new_data = precipitated.get(focus)
                if not isinstance(new_data, dict) or not new_data:
                    continue
                focus_update: dict = {}
                for key, new_items in new_data.items():
                    if isinstance(new_items, list):
                        focus_update[key] = []
                        for item in new_items:
                            if not isinstance(item, dict):
                                continue
                            item["_precipitated"] = True
                            item["_precipitated_at"] = now
                            focus_update[key].append(item)
                    elif isinstance(new_items, dict):
                        focus_update[key] = {}
                        for var_name, var_info in new_items.items():
                            if isinstance(var_info, dict):
                                var_info["_precipitated"] = True
                                var_info["_precipitated_at"] = now
                                focus_update[key][var_name] = var_info
                            else:
                                focus_update[key][var_name] = var_info
                if focus_update:
                    updates[focus] = focus_update

            if updates:
                self.memory.merge_code_knowledge(func_name, updates)

        except Exception:
            import logging
            logging.getLogger(__name__).warning('Operation failed (silent failure caught)')
            pass

    def _save_diagnosis_bundle(
        self,
        case_dir: Path,
        problem: str,
        expected: str,
        func_name: str,
        task_type: str,
        classification: dict,
        panel_result: dict,
        conditions: dict,
        evidence: dict,
        probe_results: dict,
        windows: list,
        bag_meta: dict,
        blf_meta: dict,
        tpe_result,
        param_report,
        whatif_entries,
        fix_report: str,
        step_logger,
        token_tracker,
    ) -> Path:
        """Save a structured DiagnosisBundle alongside report.md.

        The bundle captures all diagnosis artifacts with consistent
        variant_id / snapshot_id / case_id for audit and replay.
        """
        from core.diagnosis_bundle import DiagnosisBundle, Evidence, CodeLocation
        from core.materials import MaterialRegistry, StructuredRequirementSet

        variant_id = self.identity.variant_id
        snapshot_id = self.identity.snapshot_id
        case_id = case_dir.name

        bundle = DiagnosisBundle.for_case(
            project_root=self.project_root,
            case_id=case_id,
            variant_id=variant_id,
            problem=problem,
            expected=expected,
        )
        bundle.snapshot_id = snapshot_id
        bundle.classification = classification.get("task_type", "")

        # ── Evidence chain ──────────────────────────────────────────
        # Convert evidence dict to Evidence objects
        if evidence:
            for key, val in evidence.items():
                ev = Evidence(
                    evidence_id=f"ev-{key}",
                    source="analysis",
                    description=str(val)[:500] if not isinstance(val, str) else val[:500],
                    confidence=0.7,
                )
                bundle.add_evidence(ev)

        # ── Conditions as evidence ──────────────────────────────────
        if conditions:
            for cond_key, cond_val in conditions.items():
                if isinstance(cond_val, dict):
                    desc = f"{cond_key}: " + json.dumps(cond_val, ensure_ascii=False)[:300]
                else:
                    desc = f"{cond_key}: {str(cond_val)[:300]}"
                bundle.add_evidence(Evidence(
                    evidence_id=f"cond-{cond_key}",
                    source="condition",
                    description=desc,
                    confidence=0.8,
                ))

        # ── Root cause from panel ───────────────────────────────────
        if panel_result:
            opinions = panel_result.get("expert_opinions", {})
            summary = panel_result.get("moderator_summary", "")
            if summary:
                bundle.root_cause = summary[:1000]
                bundle.root_cause_confidence = 0.6

                # Extract code locations from panel findings
                import re
                code_refs = re.findall(r'([a-zA-Z_][\w/]*/[\w.]+\.\w*)\s*:?(\d+)?', summary)
                for fp, line in code_refs:
                    bundle.code_localization.append(CodeLocation(
                        file_path=fp,
                        line_start=int(line) if line else 0,
                    ))

        # Upgrade conclusion level based on evidence
        if bundle.evidence_chain:
            bundle.upgrade_to_candidate()
        if bundle.code_localization and bundle.evidence_chain:
            bundle.upgrade_to_confirmed()

        # ── Requirement trace (discover materials for variant) ──────
        if variant_id:
            try:
                registry = MaterialRegistry.for_variant(self.project_root, variant_id)
                materials = registry.list_by_variant(variant_id)
                req_set = StructuredRequirementSet.for_variant(self.project_root, variant_id)

                bundle.requirement_trace = {
                    "variant_id": variant_id,
                    "snapshot_id": snapshot_id,
                    "material_ids": [m.material_id for m in materials],
                    "material_count": len(materials),
                    "authoritative_count": len(registry.list_authoritative(variant_id)),
                    "requirement_ids": list(req_set.requirements.keys()),
                    "requirement_count": len(req_set.requirements),
                }
            except Exception:
                bundle.requirement_trace = {
                    "variant_id": variant_id,
                    "snapshot_id": snapshot_id,
                    "error": "failed to load materials/requirements",
                }

        # ── Signal analysis ─────────────────────────────────────────
        if probe_results:
            bundle.signal_analysis["probe"] = probe_results
        if tpe_result:
            bundle.signal_analysis["tpe"] = (
                tpe_result.to_dict() if hasattr(tpe_result, "to_dict") else str(tpe_result)[:500]
            )

        # ── Metadata ────────────────────────────────────────────────
        bundle.metadata.update({
            "task_type": task_type,
            "function": func_name,
            "identity": {
                "variant_id": self.identity.variant_id,
                "project_key": self.identity.project_key,
                "package_profile_id": self.identity.package_profile_id,
                "snapshot_id": self.identity.snapshot_id,
                "display_name": self.identity.display_name,
                "source_docs_dir": str(self.identity.source_docs_dir or ""),
                "memory_dir": str(self.identity.memory_dir or ""),
            },
            "windows": [{"start": w.t_start, "end": w.t_end, "trigger": w.trigger_reason}
                        for w in windows] if windows else [],
            "bag_meta": bag_meta,
            "blf_meta": blf_meta,
            "step_log": step_logger.to_dict() if hasattr(step_logger, "to_dict") else {},
            "token_usage": token_tracker.to_dict() if hasattr(token_tracker, "to_dict") else {},
            "has_fix_report": bool(fix_report),
        })

        # Save to case directory
        bundle_path = case_dir / "diagnosis_bundle.json"
        bundle.save(bundle_path)
        return bundle_path
