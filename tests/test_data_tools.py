# -*- coding: utf-8 -*-
from __future__ import annotations

from engines.causal_aligner import Interval, PatternEvidence, PatternHit
from engines.pattern_extractor import CodePattern
from engines.temporal_analyzer import Edge, Run, TemporalFeature
from engines.test_window_detector import TestWindow as _TestWindow
from ai.tools.data_tools import (
    DetectTimePatternTool,
    PlotSignalTool,
    QueryCanDataTool,
)
from engines.tpe import TPEResult


class _ProbeStub:
    def __init__(self, *, result=None, error: Exception | None = None) -> None:
        self.result = result or {
            "field": "dist_x",
            "table": "radar_objects",
            "row_count": 3,
            "global": {"count": 3, "min": -5.0, "max": 2.0},
        }
        self.error = error
        self.calls = []

    def query(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.result


class _ProbeFactory:
    def __init__(self, probe: _ProbeStub) -> None:
        self.probe = probe
        self.calls = []

    def __call__(self, store, windows):
        self.calls.append({"store": store, "windows": windows})
        return self.probe


class _EngineStub:
    def __init__(self, result=None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls = []

    def run(self, store, **kwargs):
        self.calls.append({"store": store, **kwargs})
        if self.error is not None:
            raise self.error
        return self.result


class _PlotStore:
    def query_can_by_name(self, message_name: str):
        assert message_name == "ADASWarnMsg"
        return [
            {"timestamp": 1.0, "signals": {"WarnCAN": 0, "Other": 2}},
            {"timestamp": 1.5, "signals": {"WarnCAN": 1, "Other": 3}},
        ]


def _build_tpe_result() -> TPEResult:
    pattern = CodePattern(
        pattern_type="HoldRelease",
        file="coem\\demo\\adasFunc.c",
        line_start=10,
        line_end=13,
        function="FctaAlarmProcess",
        trigger_condition="WarnCAN == 0",
        trigger_variables=["WarnCAN"],
        consequence_variables=["FCTA_Warn"],
        adas_function="FCTA",
    )
    extra_pattern = CodePattern(
        pattern_type="Accumulate",
        file="coem\\demo\\adasFunc.c",
        line_start=22,
        line_end=28,
        function="FctaTimerUpdate",
        trigger_condition="TimerCond",
        trigger_variables=["TimerCond"],
        adas_function="FCTA",
    )
    first_run = Run(value=1, t_start=0.0, t_end=0.4)
    second_run = Run(value=0, t_start=0.4, t_end=1.0)
    feature = TemporalFeature(
        signal_name="WarnCAN",
        sample_count=3,
        t_start=0.0,
        t_end=1.0,
        value_distribution={1: 1, 0: 2},
        edges=[Edge(t=0.4, from_val=1, to_val=0)],
        runs=[first_run, second_run],
        runs_by_value={1: [first_run], 0: [second_run]},
        stats={"min": 0, "max": 1},
        pattern_tag="edge_dominated",
    )
    hit = PatternHit(
        interval=Interval(0.4, 0.65),
        signals_at_start={"WarnCAN": 0},
        nearby_state_changes=[{
            "t": 0.5,
            "field": "fcta_state",
            "from": 1,
            "to": 0,
            "dt_ms": 100.0,
        }],
    )
    evidence = PatternEvidence(
        pattern=pattern,
        resolution={"WarnCAN": "WarnCAN"},
        verdict="triggered",
        hits=[hit],
        summary="Hold release fired once.",
    )
    return TPEResult(
        patterns=[pattern, extra_pattern],
        features={"WarnCAN": feature},
        evidence=[evidence],
        unresolved_variables={"LocalOnlyVar"},
        internal_only_variables={"counter_u8"},
        missing_can_signals={"MissingSig"},
        notes=["pattern_total=2, used=2, triggered=1"],
    )


def test_query_can_data_tool_builds_probe_from_injected_store_and_windows():
    store = object()
    windows = [_TestWindow(1.0, 2.0, "warning edge")]
    probe = _ProbeStub()
    factory = _ProbeFactory(probe)
    tool = QueryCanDataTool(store=store, windows=windows, probe_factory=factory)

    result = tool.safe_execute({
        "field": "dist_x",
        "table": "radar_objects",
        "group_by": "side",
        "filter": "dist_x < 0",
        "stats": "count,min,max",
        "max_rows": 1000,
    })
    assert result["status"] == "ok"
    assert result["status"] == "ok"
    assert result["data"]["probe_source"] == "factory"
    assert result["data"]["window_count"] == 1
    assert result["data"]["result"]["global"]["count"] == 3
    assert factory.calls[0]["store"] is store
    assert factory.calls[0]["windows"] == windows
    assert probe.calls[0]["stats"] == ["count", "min", "max"]
    assert probe.calls[0]["group_by"] == "side"
    assert probe.calls[0]["filter"] == "dist_x < 0"


def test_query_can_data_tool_returns_structured_probe_error():
    probe = _ProbeStub(result={
        "field": "dist_x",
        "table": "unknown",
        "row_count": 0,
        "error": "unsupported table 'unknown'",
    })
    tool = QueryCanDataTool(probe=probe)

    result = tool.safe_execute({"field": "dist_x", "table": "unknown"})
    assert result["status"] == "error"
    assert result["status"] == "error"
    assert result["message"] == "unsupported table 'unknown'"
    assert result["data"]["result"]["error"] == "unsupported table 'unknown'"


def test_query_can_data_tool_safe_execute_catches_probe_exceptions():
    tool = QueryCanDataTool(probe=_ProbeStub(error=RuntimeError("probe crashed")))

    result = tool.safe_execute({"field": "dist_x"})
    assert result["status"] == "error"
    assert result["status"] == "error"
    assert "RuntimeError: probe crashed" in result["message"]


def test_detect_time_pattern_tool_serializes_tpe_result_and_normalizes_patterns():
    engine = _EngineStub(result=_build_tpe_result())
    tool = DetectTimePatternTool(store=object(), engine=engine)

    result = tool.safe_execute({
        "func_name": "FCTA",
        "extra_patterns": [{
            "pattern_type": "ThresholdCross",
            "file": "coem\\demo\\adasFunc.c",
            "line_start": 40,
            "line_end": 42,
            "function": "FctaCheckThreshold",
            "trigger_condition": "WarnCAN >= 1",
            "trigger_variables": ["WarnCAN"],
            "adas_function": "FCTA",
        }],
        "state_transitions": [{"t": 0.5, "field": "fcta_state", "from": 1, "to": 0}],
        "time_window": [0.0, 2.0],
    })
    assert result["status"] == "ok"
    assert result["status"] == "ok"
    assert result["data"]["engine_source"] == "injected"
    assert result["data"]["input"]["extra_pattern_count"] == 1
    assert result["data"]["result"]["triggered_count"] == 1
    assert result["data"]["result"]["has_triggers"] is True
    assert result["data"]["result"]["features"]["WarnCAN"]["pattern_tag"] == "edge_dominated"
    assert result["data"]["result"]["evidence"][0]["verdict"] == "triggered"
    assert result["data"]["result"]["unresolved_variables"] == ["LocalOnlyVar"]
    assert "代码模式" in result["data"]["result"]["expert_block"]

    engine_call = engine.calls[0]
    assert isinstance(engine_call["extra_patterns"][0], CodePattern)
    assert engine_call["func_name"] == "FCTA"
    assert engine_call["time_window"] == (0.0, 2.0)


def test_detect_time_pattern_tool_requires_store_or_engine_source():
    tool = DetectTimePatternTool()

    result = tool.safe_execute({"func_name": "FCTA"})
    assert result["status"] == "error"
    assert result["status"] == "error"
    assert result["message"] == "no data store available; inject store=..."


def test_plot_signal_tool_returns_deferred_artifact_with_preview():
    tool = PlotSignalTool(store=_PlotStore())

    result = tool.safe_execute({
        "message_name": "ADASWarnMsg",
        "signal_name": "WarnCAN",
        "time_window": [0.0, 3.0],
        "preview_limit": 1,
        "output_path": "cases\\demo\\warncan.html",
    })
    assert result["status"] == "ok"
    assert result["status"] == "ok"
    assert result["data"]["artifact"]["backend"] == "deferred"
    assert result["data"]["artifact"]["series"]["signal_name"] == "WarnCAN"
    assert result["data"]["preview_status"] == "available"
    assert result["data"]["preview"]["point_count"] == 1
    assert result["data"]["preview"]["points"][0]["value"] == 0
