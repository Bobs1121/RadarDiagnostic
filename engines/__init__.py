# -*- coding: utf-8 -*-
"""
Deterministic engines package.

Pure rule/calculation engines with **no LLM dependency**. These are the
"deterministic evidence" layer of radarAnalyze — unit-testable, reproducible,
and reusable across the diagnosis / query / agent paths.

Engine modules may depend on each other (e.g. ``tpe`` composes
``causal_aligner`` + ``pattern_extractor`` + ``temporal_analyzer``) and on the
shared ``ai.utils`` helpers, but never on ``ai.orchestrator`` or the LLM stack.
"""

from __future__ import annotations

from .analysis_ledger import AnalysisLedger
from .code_context import (
    CodeContextError,
    SourceChangedDuringBuild,
    build_code_context,
    build_source_manifest,
    discover_source_files,
    export_code_index,
    load_code_context,
    query_code_context,
)
from .event_code_path import (
    EventCodePathError,
    build_event_code_path,
    load_code_index as load_event_code_index,
)
from .evidence_query import build_evidence_query
from .diagnostic_report import build_diagnostic_report, write_diagnostic_report
from .condition_trace import build_condition_trace
from .memory_recall import recall_memory

__all__ = [
    "AnalysisLedger",
    "CodeContextError",
    "SourceChangedDuringBuild",
    "build_code_context",
    "build_source_manifest",
    "discover_source_files",
    "export_code_index",
    "load_code_context",
    "query_code_context",
    "EventCodePathError",
    "build_event_code_path",
    "load_event_code_index",
    "build_evidence_query",
    "build_diagnostic_report",
    "write_diagnostic_report",
    "build_condition_trace",
    "recall_memory",
]
