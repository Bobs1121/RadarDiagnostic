# -*- coding: utf-8 -*-
"""Smoke tests for modules that previously had zero direct coverage.

Protects the production refactor (feature/production-refactor) when these
modules are moved into the new ``engines/`` package.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ── parameter_analyzer ─────────────────────────────────────────────────────

class TestParameterAnalyzerSmoke:
    def test_scan_parameters_missing_source_returns_empty(self, tmp_path: Path):
        from engines.parameter_analyzer import scan_parameters

        # No adasFunc.c/paraDefine.h present → empty scan, no crash.
        result = scan_parameters(tmp_path, cache_dir=tmp_path / "cache")
        assert result is not None
        assert hasattr(result, "parameters")

    def test_what_if_empty_proposals(self):
        from engines.parameter_analyzer import SensitivityReport, what_if

        report = SensitivityReport(
            func="FCTA", total_parameters=0, parameters_analyzed=0, entries=[],
        )
        entries = what_if(report, proposals={}, store=None)
        assert entries == []

    def test_render_sensitivity_markdown_empty(self):
        from engines.parameter_analyzer import SensitivityReport, render_sensitivity_markdown

        report = SensitivityReport(
            func="FCTA", total_parameters=0, parameters_analyzed=0, entries=[],
        )
        md = render_sensitivity_markdown(report)
        assert isinstance(md, str)


# ── frame_analyzer ─────────────────────────────────────────────────────────

class TestFrameAnalyzerSmoke:
    def test_analyze_bag_timeline_no_frames(self):
        from engines.frame_analyzer import FrameAnalyzer

        class _EmptyStore:
            def query_bag_by_topic(self, topic):
                return []

        fa = FrameAnalyzer(router=None)
        out = fa.analyze_bag_timeline(_EmptyStore(), topic="some_topic")
        assert "error" in out

    def test_get_variables_for_function_empty(self):
        from engines.frame_analyzer import FrameAnalyzer

        fa = FrameAnalyzer(router=None, variables_path=None)
        assert fa.get_variables_for_function("FCTA") == []

    def test_static_append_tpe_block(self):
        from engines.frame_analyzer import FrameAnalyzer

        evidence = {}
        FrameAnalyzer.append_tpe_block(evidence, tpe_block="TPE_BLOCK", tpe_report="TPE_REPORT")
        assert evidence.get("tpe_block") == "TPE_BLOCK"
        assert evidence.get("tpe_report") == "TPE_REPORT"


# ── platform_adapters ──────────────────────────────────────────────────────

class TestPlatformAdaptersSmoke:
    def test_registry_after_lazy_load(self):
        from ai.platform_adapters import factory
        from core.plugin import PluginRegistry

        factory._ensure_adapters_loaded()
        cls = PluginRegistry.get(factory._KIND_CL, "gen6_c_radar")
        assert cls is not None
        cls5 = PluginRegistry.get(factory._KIND_CL, "gen5_reco_pl")
        assert cls5 is not None
        # gen5_cpp_radar shares the Gen6 implementation.
        assert PluginRegistry.get(factory._KIND_CL, "gen5_cpp_radar") is not None

    def test_gen6_func_keywords_nonempty(self):
        from ai.platform_adapters.gen6_symmetry import FUNC_KEYWORDS_GEN6

        assert "BSD" in FUNC_KEYWORDS_GEN6
        assert len(FUNC_KEYWORDS_GEN6["BSD"]) > 0

    def test_default_signal_mapper_fallback(self, tmp_path: Path):
        from ai.platform_adapters import factory

        # Unknown platform → falls back to _SignalMapperDefault, no crash.
        adapter = factory.get_signal_mapper_adapter(
            "gen9_unknown", tmp_path, tmp_path, {}, tmp_path,
        )
        assert adapter is not None

    def test_base_adapters_are_abstract(self):
        from ai.platform_adapters.base import (
            BaseCodeLearnerAdapter,
            BaseConditionExtractorAdapter,
            BaseSignalMapperAdapter,
        )

        for base in (BaseCodeLearnerAdapter, BaseConditionExtractorAdapter, BaseSignalMapperAdapter):
            with pytest.raises(TypeError):
                base()  # abstract → cannot instantiate