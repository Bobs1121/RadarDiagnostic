# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
from pathlib import Path

from ai.modules.base import BaseModule, ModuleResult
from ai.modules.diagnosis_panel import DiagnosisPanelModule


class _ClassifierStub:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def classify(self, problem: str, expected: str = "", memory_hint: str = ""):
        self.calls.append({
            "problem": problem,
            "expected": expected,
            "memory_hint": memory_hint,
        })
        return self.result


class _PanelStub:
    def __init__(self, result=None):
        self.result = result or {"final_verdict": "root cause", "rounds": 3}
        self.calls = []

    def run_panel(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


class _BrokenPanelStub:
    def run_panel(self, **kwargs):
        raise RuntimeError("panel crashed")


def _raising_panel_factory(*_args):
    raise ImportError("langgraph missing")


def test_diagnosis_panel_is_base_subclass_with_name():
    assert issubclass(DiagnosisPanelModule, BaseModule)
    assert DiagnosisPanelModule.name == "diagnosis-panel"


def test_diagnosis_panel_classify_mode_returns_structured_payload():
    classifier = _ClassifierStub({
        "task_type": "verify",
        "confidence": 0.917,
        "target_function": "fcta",
        "focus_parameters": ["TTC", "TTC"],
        "focus_signals": "car_spd",
        "reasoning": "explicit proposal",
    })
    mod = DiagnosisPanelModule(classifier=classifier)

    res = mod.safe_run(
        problem="FCTA threshold change",
        expected="warn sooner",
        mode="classify",
        memory_context="recent similar case",
    )

    assert isinstance(res, ModuleResult)
    assert res.ok is True
    assert res.module == "diagnosis-panel"
    payload = res.data
    assert payload["requested_mode"] == "classify"
    assert payload["effective_mode"] == "classify"
    assert payload["panel_result"] is None
    assert payload["panel_status"] == "not_requested"
    assert payload["classification"]["task_type"] == "verify"
    assert payload["classification"]["confidence"] == 0.92
    assert payload["classification"]["target_function"] == "FCTA"
    assert payload["classification"]["focus_parameters"] == ["TTC"]
    assert payload["classification"]["focus_signals"] == ["car_spd"]
    assert classifier.calls[0]["memory_hint"] == "recent similar case"


def test_diagnosis_panel_panel_mode_runs_injected_panel():
    classifier = _ClassifierStub({
        "task_type": "diagnose",
        "confidence": 0.85,
        "target_function": "RCTA",
        "reasoning": "miss trigger",
    })
    panel = _PanelStub({
        "expert_opinions": {"algorithm": "check TTC gate"},
        "final_verdict": "Signal suppressed upstream.",
        "rounds": 3,
    })
    mod = DiagnosisPanelModule(classifier=classifier, panel=panel)

    res = mod.safe_run(
        problem="RCTA missed warning",
        expected="warn when target approaches",
        mode="panel",
        data_summary="key facts here",
        memory_context="historical hint",
        fail_type="FN",
    )

    assert res.ok is True
    payload = res.data
    assert payload["effective_mode"] == "panel"
    assert payload["panel_status"] == "completed"
    assert payload["classification"]["target_function"] == "RCTA"
    assert payload["panel_result"]["final_verdict"] == "Signal suppressed upstream."
    assert panel.calls[0]["func_name"] == "RCTA"
    assert panel.calls[0]["task_type"] == "diagnose"
    assert panel.calls[0]["fail_type"] == "FN"
    assert panel.calls[0]["data_summary"] == "key facts here"


def test_diagnosis_panel_panel_mode_degrades_when_panel_is_unavailable():
    classifier = _ClassifierStub({
        "task_type": "diagnose",
        "confidence": 0.8,
        "target_function": "FCTB",
    })
    mod = DiagnosisPanelModule(
        classifier=classifier,
        panel_factory=_raising_panel_factory,
        router=object(),
        config={"paths": {"source_code": "D:\\dummy"}},
        project_root=Path("D:\\RamboStar\\idea\\radarAnalyze"),
    )

    res = mod.safe_run(problem="FCTB issue", mode="panel")

    assert res.ok is True
    payload = res.data
    assert payload["effective_mode"] == "classify"
    assert payload["panel_result"] is None
    assert payload["panel_status"] == "unavailable"
    assert "ImportError: langgraph missing" in payload["panel_error"]


def test_diagnosis_panel_panel_failure_returns_failed_result_with_classification():
    classifier = _ClassifierStub({
        "task_type": "diagnose",
        "confidence": 0.8,
        "target_function": "BSD",
    })
    mod = DiagnosisPanelModule(classifier=classifier, panel=_BrokenPanelStub())

    res = mod.safe_run(problem="BSD missed warning", mode="panel")

    assert res.ok is False
    assert "panel run failed: RuntimeError: panel crashed" == res.message
    assert res.data["classification"]["target_function"] == "BSD"
    assert res.data["panel_status"] == "failed"


def test_diagnosis_panel_cli_wiring():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers()
    DiagnosisPanelModule.register_cli(sub)
    args = parser.parse_args([
        "diagnosis-panel",
        "--problem", "FCTA missed warning",
        "--mode", "panel",
        "--fail-type", "FN",
    ])

    assert args.problem == "FCTA missed warning"
    assert args.mode == "panel"
    assert args.fail_type == "FN"
    assert args._module_cls is DiagnosisPanelModule
    mod = DiagnosisPanelModule.from_cli_args(args)
    assert isinstance(mod, DiagnosisPanelModule)
