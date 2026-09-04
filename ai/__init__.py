"""radarAnalyze AI analysis package.

The deterministic engines live in ``engines/`` (no LLM dependency); the LLM
reasoning / orchestration layer lives here in ``ai/``.

To avoid circular imports (``ai.utils`` → ``ai`` → ``ai.orchestrator`` →
``engines.frame_analyzer`` → ``ai.utils``), heavy modules and engine re-exports
are lazily loaded via PEP 562 ``__getattr__``. ``from ai import Orchestrator``,
``from ai import signal_mapper`` etc. still work.
"""
from __future__ import annotations

from .model_router import ModelRouter
from .fallback import safe_llm_call, get_fallback, register_fallback
from .observability import StepLogger, TokenTracker, ObservableStatus

# Re-exported engine symbols (backward-compat) resolved lazily in __getattr__.
_ENGINE_MODULES = {
    "causal_aligner": "engines.causal_aligner",
    "data_probe": "engines.data_probe",
    "frame_analyzer": "engines.frame_analyzer",
    "parameter_analyzer": "engines.parameter_analyzer",
    "pattern_extractor": "engines.pattern_extractor",
    "signal_mapper": "engines.signal_mapper",
    "temporal_analyzer": "engines.temporal_analyzer",
    "test_window_detector": "engines.test_window_detector",
    "tpe": "engines.tpe",
    "FrameAnalyzer": "engines.frame_analyzer",
}

_LAZY_ATTRS = {
    "Orchestrator": "ai.orchestrator",
    "CodeLearner": "ai.code_learner",
}


def __getattr__(name: str):
    if name in _ENGINE_MODULES:
        import importlib
        mod = importlib.import_module(_ENGINE_MODULES[name])
        value = getattr(mod, name) if name == "FrameAnalyzer" else mod
        globals()[name] = value
        return value
    if name in _LAZY_ATTRS:
        import importlib
        mod = importlib.import_module(_LAZY_ATTRS[name])
        value = getattr(mod, name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "ModelRouter",
    "safe_llm_call", "get_fallback", "register_fallback",
    "StepLogger", "TokenTracker", "ObservableStatus",
    "Orchestrator", "CodeLearner", "FrameAnalyzer",
]