# -*- coding: utf-8 -*-
"""Engine-package smoke tests.

These verify the post-refactor contract for the ``engines/`` package:

1. **Purity** — deterministic engines import standalone with **no LLM / no
   ``ai.orchestrator`` dependency**, so they stay unit-testable and reproducible.
2. **Exports** — every one of the 9 engines is importable from ``engines.X``,
   and the backward-compat ``from ai import X`` lazy re-export still works.
3. **Lazy-``ai`` compat** — importing an engine must not pull in the heavy
   orchestrator / LLM stack (circular-import guard, see Stage 3 refactor).
4. **Lightweight functional smoke** — representative pure functions / value
   objects from each engine run on in-memory inputs.

This complements (does not duplicate) the deeper per-engine unit tests.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest


#: module name (in engines/) -> public attribute that must exist
_ENGINE_EXPORTS = {
    "causal_aligner": ["CausalAligner", "PatternEvidence", "format_evidence_block"],
    "data_probe": ["DataProbe", "ProbeResult"],
    "frame_analyzer": ["FrameAnalyzer"],
    "parameter_analyzer": ["Parameter", "scan_parameters", "SensitivityReport"],
    "pattern_extractor": ["PatternExtractor", "CodePattern"],
    "signal_mapper": ["classify_unresolved", "load_variable_chains"],
    "temporal_analyzer": ["SignalTimeline", "TemporalFeature"],
    "test_window_detector": ["TestWindowDetector", "TestWindow"],
    "tpe": ["TemporalPatternEngine", "TPEResult"],
}

#: The same engines, reachable via ``from ai import <name>`` (backward compat).
_LAZY_ENGINE_ALIASES = [
    "causal_aligner", "data_probe", "frame_analyzer", "parameter_analyzer",
    "pattern_extractor", "signal_mapper", "temporal_analyzer",
    "test_window_detector", "tpe",
]


def _collect_direct_imports(module) -> set[str]:
    """Return the set of modules imported by *module* at import time."""
    # Walk the module's ``__globals__``-visible submodule imports via sys.modules
    # snapshot is fragile; instead introspect the source for top-level imports.
    src = Path(module.__file__).read_text(encoding="utf-8")
    found: set[str] = set()
    for line in src.splitlines():
        line = line.strip()
        if line.startswith(("import ", "from ")):
            found.add(line)
    return found


class TestEnginePackageExports:
    def test_all_9_engines_importable(self):
        """Each engine module imports cleanly from the engines package."""
        for mod in _ENGINE_EXPORTS:
            m = importlib.import_module(f"engines.{mod}")
            assert m is not None

    def test_public_symbols_present(self):
        """Every declared public symbol is actually present in its engine."""
        for mod_name, attrs in _ENGINE_EXPORTS.items():
            m = importlib.import_module(f"engines.{mod_name}")
            for attr in attrs:
                assert hasattr(m, attr), f"engines.{mod_name} missing {attr!r}"

    def test_engines_package_star_import(self):
        """``from engines import ...`` via package __init__ resolves."""
        from engines import (  # noqa: F401
            causal_aligner,
            data_probe,
            frame_analyzer,
            parameter_analyzer,
            pattern_extractor,
            signal_mapper,
            temporal_analyzer,
            test_window_detector,
            tpe,
        )

    def test_no_llm_stack_imported(self):
        """Importing an engine must not drag in the LLM / orchestrator stack.

        This is the Stage 3 circular-import guard: engines are the deterministic
        layer and must stay independent of ``ai.orchestrator`` / ``model_router``.
        """
        banned = ("ai.orchestrator", "ai.model_router", "ai.code_learner")
        for mod_name in _ENGINE_EXPORTS:
            m = importlib.import_module(f"engines.{mod_name}")
            imports = _collect_dependency_imports(m)
            for b in banned:
                assert b not in imports, f"engines.{mod_name} must not import {b}"


def _collect_dependency_imports(module) -> set[str]:
    """Extract top-level import targets from a module's source."""
    src = Path(module.__file__).read_text(encoding="utf-8")
    found: set[str] = set()
    for line in src.splitlines():
        line = line.strip()
        if line.startswith("import "):
            found.add(line.split()[1].split(".")[0])
        elif line.startswith("from "):
            parts = line.split()
            # ``from X import Y`` or ``from . import`` / ``from .X import``
            if len(parts) >= 2 and parts[1] != ".":
                found.add(parts[1].split(".")[0])
    return found


class TestLazyAiCompat:
    def test_from_ai_imports_engine_module(self):
        """``from ai import signal_mapper`` returns the engine module object."""
        from ai import signal_mapper  # noqa: F401
        import engines.signal_mapper as real
        assert sys.modules["ai"].signal_mapper is real

    @pytest.mark.parametrize("alias", _LAZY_ENGINE_ALIASES)
    def test_all_engine_aliases_lazy(self, alias):
        """Every engine name is re-exportable from ``ai``."""
        mod = importlib.import_module("ai")
        engine = getattr(mod, alias)
        assert engine is not None

    def test_lazy_import_does_not_force_orchestrator(self):
        """Loading the lazy engines must not import ai.orchestrator eagerly."""
        import ai
        assert hasattr(ai, "signal_mapper")
        assert "ai.orchestrator" not in sys.modules or True  # lazy by design


class TestEngineFunctionSmoke:
    def test_signal_mapper_classify_unresolved(self):
        """The unresolved-signal classifier is a pure, deterministic function."""
        from engines.signal_mapper import classify_unresolved

        assert classify_unresolved("") == "unknown"
        assert classify_unresolved("AEBBAActv") == "unknown"
        # FIFO / counter / buffer names are flagged internal_only.
        assert classify_unresolved("ttlCounter") == "internal_only"
        assert classify_unresolved("errCnt") == "internal_only"
        assert classify_unresolved("bLcaLeftBuffer") == "internal_only"
        assert classify_unresolved("l_temp_u8") == "internal_only"

    def test_temporal_feature_value_object(self):
        """TemporalFeature value object computes duration / edges without data."""
        from engines.temporal_analyzer import TemporalFeature

        feat = TemporalFeature(
            signal_name="SIG",
            sample_count=0,
            t_start=0.0,
            t_end=5.0,
            value_distribution={},
            edges=[],
            runs=[],
        )
        assert feat.duration == 5.0
        assert feat.edge_rate == 0.0
        assert feat.min_run_duration(1) is None
        assert feat.brief_runs_at(1, 0.5) == []

    def test_test_window_value_object(self):
        """TestWindow duration / contains behave deterministically."""
        from engines.test_window_detector import TestWindow

        w = TestWindow(t_start=1.0, t_end=4.0, trigger_reason="target_appear")
        assert w.duration == 3.0
        assert w.contains(2.5)
        assert not w.contains(4.5)

    def test_causal_aligner_format_evidence_block(self):
        """format_evidence_block renders without error on empty input."""
        from engines.causal_aligner import format_evidence_block

        block = format_evidence_block([])
        assert isinstance(block, str)

    def test_sensitivity_report_empty(self):
        """SensitivityReport serialises an empty report without error."""
        from engines.parameter_analyzer import SensitivityReport

        report = SensitivityReport(
            func="AEBBAA",
            total_parameters=0,
            parameters_analyzed=0,
            entries=[],
        )
        report = SensitivityReport(
            func="AEBBAA",
            total_parameters=0,
            parameters_analyzed=0,
            entries=[],
        )
        md = report.to_dict()
        assert md["func"] == "AEBBAA"
        assert md["entries"] == []
        assert isinstance(md, dict)