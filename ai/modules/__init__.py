# -*- coding: utf-8 -*-
"""
ai.modules — standalone, composable capability modules (V3 vertical axis).

Each capability (M1..M8) is a :class:`~ai.modules.base.BaseModule` subclass that
can run independently (CLI + Python API) and be composed by the orchestrator.

The foundation contract (:class:`BaseModule`, :class:`ModuleResult`) and the
concrete standalone modules are exported here. Concrete-module imports are
guarded so that a missing optional dependency in one module never breaks the
whole package import.
"""
from .base import BaseModule, ModuleResult

__all__ = ["BaseModule", "ModuleResult", "MODULE_REGISTRY"]

#: Registry of CLI-exposable standalone modules, keyed by their ``name``.
MODULE_REGISTRY: dict[str, type[BaseModule]] = {}

try:  # V4 S1A · durable progressive-analysis ledger primitives
    from .analysis_ledger import (
        AnalysisClaimAppendModule,
        AnalysisRunCreateModule,
        AnalysisRunReadModule,
        AnalysisRunUpdateModule,
        AnalysisStepRecordModule,
    )
    for _module_cls in (
        AnalysisRunCreateModule,
        AnalysisRunReadModule,
        AnalysisRunUpdateModule,
        AnalysisStepRecordModule,
        AnalysisClaimAppendModule,
    ):
        MODULE_REGISTRY[_module_cls.name] = _module_cls
        __all__.append(_module_cls.__name__)
except Exception:  # noqa: BLE001
    pass

try:  # V4 S2B · hypothesis / experiment / manual observation ledger primitives
    from .analysis_collaboration import (
        AnalysisHypothesisRecordModule,
        AnalysisUserObservationModule,
        DebugExperimentRecordModule,
    )
    for _module_cls in (
        AnalysisHypothesisRecordModule,
        DebugExperimentRecordModule,
        AnalysisUserObservationModule,
    ):
        MODULE_REGISTRY[_module_cls.name] = _module_cls
        __all__.append(_module_cls.__name__)
except Exception:  # noqa: BLE001 - optional collaboration slice must not break import
    pass

try:  # PR5 · offline deterministic agent loop wrapper
    from .agent_loop import AgentLoopModule
    MODULE_REGISTRY[AgentLoopModule.name] = AgentLoopModule
    __all__.append("AgentLoopModule")
except Exception:  # noqa: BLE001 - optional module, never break package import
    pass

try:  # Stage 5 · real ReAct agent (LLM plans, tools execute)
    from .react_agent import ReActModule
    MODULE_REGISTRY[ReActModule.name] = ReActModule
    __all__.append("ReActModule")
except Exception:  # noqa: BLE001 - optional module, never break package import
    pass

try:  # M1 · code structure (no data)
    from .code_structure import CodeStructureModule
    MODULE_REGISTRY[CodeStructureModule.name] = CodeStructureModule
    __all__.append("CodeStructureModule")
except Exception:  # noqa: BLE001 - optional module, never break package import
    pass

try:  # M4 · data diagnostics (no code)
    from .data_diagnostics import DataDiagnosticsModule
    MODULE_REGISTRY[DataDiagnosticsModule.name] = DataDiagnosticsModule
    __all__.append("DataDiagnosticsModule")
except Exception:  # noqa: BLE001
    pass

try:  # M3/M8 · requirements review & trace
    from ai.requirements.module import RequirementModule
    MODULE_REGISTRY[RequirementModule.name] = RequirementModule
    __all__.append("RequirementModule")
except Exception:  # noqa: BLE001
    pass

try:  # M2 · signal bridge (code/data signal mapping)
    from .signal_bridge import SignalBridgeModule
    MODULE_REGISTRY[SignalBridgeModule.name] = SignalBridgeModule
    __all__.append("SignalBridgeModule")
except Exception:  # noqa: BLE001
    pass

try:  # M6 · diagnosis panel wrapper
    from .diagnosis_panel import DiagnosisPanelModule
    MODULE_REGISTRY[DiagnosisPanelModule.name] = DiagnosisPanelModule
    __all__.append("DiagnosisPanelModule")
except Exception:  # noqa: BLE001
    pass

try:  # M7 · deterministic code review
    from .code_review import CodeReviewModule
    MODULE_REGISTRY[CodeReviewModule.name] = CodeReviewModule
    __all__.append("CodeReviewModule")
except Exception:  # noqa: BLE001
    pass

try:  # PR6-F · minimal-input project onboarding
    from .project_init import ProjectInitModule
    MODULE_REGISTRY[ProjectInitModule.name] = ProjectInitModule
    __all__.append("ProjectInitModule")
except Exception:  # noqa: BLE001
    pass

try:  # M9 · BSD signal matching + condition cross-validation
    from .bsd_data_bridge import BSDDataBridgeModule
    MODULE_REGISTRY[BSDDataBridgeModule.name] = BSDDataBridgeModule
    __all__.append("BSDDataBridgeModule")
except Exception:  # noqa: BLE001
    pass

try:  # M10 · BLF key-signal extraction + contract audit (deterministic)
    from .signal_audit import SignalAuditModule
    MODULE_REGISTRY[SignalAuditModule.name] = SignalAuditModule
    __all__.append("SignalAuditModule")
except Exception:  # noqa: BLE001
    pass

try:  # V4 P3 · signal-extract (fuzzy signal extraction + plot)
    from .signal_extract import SignalExtractModule
    MODULE_REGISTRY[SignalExtractModule.name] = SignalExtractModule
    __all__.append("SignalExtractModule")
except Exception:  # noqa: BLE001
    pass

try:  # V4 P1 · pi (unified dialogue entry / orchestration hub)
    from .pi import PiModule
    MODULE_REGISTRY[PiModule.name] = PiModule
    __all__.append("PiModule")
except Exception:  # noqa: BLE001
    pass

try:  # V4 · immutable Pi orchestration context binder
    from .pi_context import PiContextModule
    MODULE_REGISTRY[PiContextModule.name] = PiContextModule
    __all__.append("PiContextModule")
except Exception:  # noqa: BLE001
    pass

try:  # V4 · deterministic Gen6 project capability manifest
    from .project_capability import ProjectCapabilityManifestModule
    MODULE_REGISTRY[ProjectCapabilityManifestModule.name] = ProjectCapabilityManifestModule
    __all__.append("ProjectCapabilityManifestModule")
except Exception:  # noqa: BLE001
    pass

try:  # V4 · generic evidence artifact query for detailed reports/conversation
    from .evidence_query import EvidenceQueryModule
    MODULE_REGISTRY[EvidenceQueryModule.name] = EvidenceQueryModule
    __all__.append("EvidenceQueryModule")
except Exception:  # noqa: BLE001
    pass

try:  # V4 · deterministic detailed diagnostic report projection
    from .diagnostic_report import DiagnosticReportModule
    MODULE_REGISTRY[DiagnosticReportModule.name] = DiagnosticReportModule
    __all__.append("DiagnosticReportModule")
except Exception:  # noqa: BLE001
    pass

try:  # V4 S1D · source condition evidence trace
    from .condition_trace import ConditionTraceModule
    MODULE_REGISTRY[ConditionTraceModule.name] = ConditionTraceModule
    __all__.append("ConditionTraceModule")
except Exception:  # noqa: BLE001
    pass

try:  # V4 · read-only project/variant memory recall
    from .memory_recall import MemoryRecallModule
    MODULE_REGISTRY[MemoryRecallModule.name] = MemoryRecallModule
    __all__.append("MemoryRecallModule")
except Exception:  # noqa: BLE001
    pass

try:  # V4 · evidence-layer neutral alarm timeline/comparison projection
    from .alert_timeline import AlertTimelineModule
    MODULE_REGISTRY[AlertTimelineModule.name] = AlertTimelineModule
    __all__.append("AlertTimelineModule")
except Exception:  # noqa: BLE001
    pass

try:  # V4 P4 · sim-verify (arbe replay / warning trace)
    from .sim_verify import SimVerifyModule
    MODULE_REGISTRY[SimVerifyModule.name] = SimVerifyModule
    __all__.append("SimVerifyModule")
except Exception:  # noqa: BLE001
    pass

try:  # V4 CR60 · read-only arbe/source/runtime preflight
    from .arbe_preflight import ArbePreflightModule
    MODULE_REGISTRY[ArbePreflightModule.name] = ArbePreflightModule
    __all__.append("ArbePreflightModule")
except Exception:  # noqa: BLE001
    pass

try:  # V4 CR60 · approval-gated formal arbe start/stop lifecycle
    from .arbe_formal_start import ArbeFormalStartModule
    from .arbe_formal_stop import ArbeFormalStopModule
    for _module_cls in (ArbeFormalStartModule, ArbeFormalStopModule):
        MODULE_REGISTRY[_module_cls.name] = _module_cls
        __all__.append(_module_cls.__name__)
except Exception:  # noqa: BLE001
    pass

try:  # V4 CR60 · approval-gated explicit catkin_make build
    from .arbe_build import ArbeBuildModule
    MODULE_REGISTRY[ArbeBuildModule.name] = ArbeBuildModule
    __all__.append("ArbeBuildModule")
except Exception:  # noqa: BLE001
    pass

try:  # V4 CR60 · read-only current-source CUDA/config resolution
    from .arbe_cuda_resolve import ArbeCudaResolveModule
    MODULE_REGISTRY[ArbeCudaResolveModule.name] = ArbeCudaResolveModule
    __all__.append("ArbeCudaResolveModule")
except Exception:  # noqa: BLE001
    pass

try:  # V4 CR60 · read-only algo_source branch/tag resolution
    from .arbe_source_resolve import ArbeSourceResolveModule
    MODULE_REGISTRY[ArbeSourceResolveModule.name] = ArbeSourceResolveModule
    __all__.append("ArbeSourceResolveModule")
except Exception:  # noqa: BLE001
    pass

try:  # V4 CR60 · read-only configurable simulation adaptation checks
    from .arbe_patch_plan import ArbePatchPlanModule
    MODULE_REGISTRY[ArbePatchPlanModule.name] = ArbePatchPlanModule
    __all__.append("ArbePatchPlanModule")
except Exception:  # noqa: BLE001
    pass

try:  # V4 CR60 · read-only prepared-data verification before transfer/replay
    from .cr60_data_prep_verify import CR60DataPrepVerifyModule
    MODULE_REGISTRY[CR60DataPrepVerifyModule.name] = CR60DataPrepVerifyModule
    __all__.append("CR60DataPrepVerifyModule")
except Exception:  # noqa: BLE001
    pass

try:  # V4 CR60 · approval-gated upstream data transfer adapter
    from .cr60_data_transfer import CR60DataTransferModule
    MODULE_REGISTRY[CR60DataTransferModule.name] = CR60DataTransferModule
    __all__.append("CR60DataTransferModule")
except Exception:  # noqa: BLE001
    pass

try:  # V4 CR60 · material-first data/software/source intake
    from .cr60_intake import CR60IntakeModule
    MODULE_REGISTRY[CR60IntakeModule.name] = CR60IntakeModule
    __all__.append("CR60IntakeModule")
except Exception:  # noqa: BLE001
    pass

try:  # V4 CR60 · one-time deterministic current-source context snapshot
    from .code_context import CodeContextReadModule, CodeContextRefreshModule
    for _module_cls in (CodeContextRefreshModule, CodeContextReadModule):
        MODULE_REGISTRY[_module_cls.name] = _module_cls
        __all__.append(_module_cls.__name__)
except Exception:  # noqa: BLE001
    pass

try:  # V4 CR60 · generic event-to-current-source path and GDB planning
    from .event_code_path import EventCodePathModule
    MODULE_REGISTRY[EventCodePathModule.name] = EventCodePathModule
    __all__.append("EventCodePathModule")
except Exception:  # noqa: BLE001
    pass

try:  # V4 CR60 · public arbe runtime row normalization
    from .public_runtime import PublicRuntimeNormalizeModule
    MODULE_REGISTRY[PublicRuntimeNormalizeModule.name] = PublicRuntimeNormalizeModule
    __all__.append("PublicRuntimeNormalizeModule")
except Exception:  # noqa: BLE001
    pass

try:  # V4 CR60 · Sprint1 harness adapter
    from .cr60_precheck import CR60PrecheckModule
    MODULE_REGISTRY[CR60PrecheckModule.name] = CR60PrecheckModule
    __all__.append("CR60PrecheckModule")
except Exception:  # noqa: BLE001
    pass

try:  # V4 CR60 · public ROS/bag evidence plan and audit
    from .public_topic_plan import PublicTopicPlanModule
    from .public_evidence_audit import PublicEvidenceAuditModule
    for _module_cls in (PublicTopicPlanModule, PublicEvidenceAuditModule):
        MODULE_REGISTRY[_module_cls.name] = _module_cls
        __all__.append(_module_cls.__name__)
except Exception:  # noqa: BLE001
    pass

try:  # V4 CR60 · source-bound code to GDB instruction generation
    from .code_gdb_plan import CodeGdbPlanModule
    MODULE_REGISTRY[CodeGdbPlanModule.name] = CodeGdbPlanModule
    __all__.append("CodeGdbPlanModule")
except Exception:  # noqa: BLE001
    pass

try:  # V4 CR60 · generic approval-gated headless GDB service
    from .gdb_service import GdbServiceModule
    MODULE_REGISTRY[GdbServiceModule.name] = GdbServiceModule
    __all__.append("GdbServiceModule")
except Exception:  # noqa: BLE001
    pass

try:  # V4 CR60 · source/data-bound runtime debug planning
    from .runtime_debug_plan import RuntimeDebugPlanModule
    MODULE_REGISTRY[RuntimeDebugPlanModule.name] = RuntimeDebugPlanModule
    __all__.append("RuntimeDebugPlanModule")
except Exception:  # noqa: BLE001
    pass

try:  # V4 CR60 · approval-gated plan-bound isolated GDB runner
    from .runtime_debug_run import RuntimeDebugRunModule
    MODULE_REGISTRY[RuntimeDebugRunModule.name] = RuntimeDebugRunModule
    __all__.append("RuntimeDebugRunModule")
except Exception:  # noqa: BLE001
    pass

try:  # V4 CR60 · approval-gated formal existing-PID GDB attach
    from .runtime_debug_attach import RuntimeDebugAttachModule
    MODULE_REGISTRY[RuntimeDebugAttachModule.name] = RuntimeDebugAttachModule
    __all__.append("RuntimeDebugAttachModule")
except Exception:  # noqa: BLE001
    pass

try:  # V4 CR60 · runtime evidence producer/validator/merge consumers
    from .runtime_evidence import (
        RuntimeEvidenceComposeModule,
        RuntimeEvidenceMergeModule,
        RuntimeEvidenceNormalizeModule,
        RuntimeEvidenceValidateModule,
    )
    for _module_cls in (
        RuntimeEvidenceNormalizeModule,
        RuntimeEvidenceValidateModule,
        RuntimeEvidenceComposeModule,
        RuntimeEvidenceMergeModule,
    ):
        MODULE_REGISTRY[_module_cls.name] = _module_cls
        __all__.append(_module_cls.__name__)
except Exception:  # noqa: BLE001
    pass

try:  # V4 CR60 · read-only ROS topic inventory
    from .ros_topic_inventory import RosTopicInventoryModule
    MODULE_REGISTRY[RosTopicInventoryModule.name] = RosTopicInventoryModule
    __all__.append("RosTopicInventoryModule")
except Exception:  # noqa: BLE001
    pass

try:  # V4 P5 · code-learn (AST build / reindex codegraph)
    from .code_learn import CodeLearnModule
    MODULE_REGISTRY[CodeLearnModule.name] = CodeLearnModule
    __all__.append("CodeLearnModule")
except Exception:  # noqa: BLE001
    pass

try:  # V4 P5 · code-analyze (call chain / deps / semantics query)
    from .code_analyze import CodeAnalyzeModule
    MODULE_REGISTRY[CodeAnalyzeModule.name] = CodeAnalyzeModule
    __all__.append("CodeAnalyzeModule")
except Exception:  # noqa: BLE001
    pass

try:  # V4 P7 · req-analyze (requirement→code gap + trace, reuse core/materials)
    from .req_analyze import ReqAnalyzeModule
    MODULE_REGISTRY[ReqAnalyzeModule.name] = ReqAnalyzeModule
    __all__.append("ReqAnalyzeModule")
except Exception:  # noqa: BLE001
    pass


