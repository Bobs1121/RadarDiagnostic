# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path

from harness.harness_runner import HarnessResult
from tools.run_harness_gate import run_gate


class _FakeRunner:
    def __init__(self, results: list[HarnessResult]):
        self.results = results
        self.requested_cases = None

    def run_all_cases(self, cases=None):
        self.requested_cases = cases
        return self.results

    def generate_aggregate_report(self, results):
        return {
            "report_type": "harness_aggregate",
            "total_cases": len(results),
            "passed": sum(1 for r in results if r.passed),
        }


def _result(case_id: str, passed: bool) -> HarnessResult:
    result = HarnessResult(case_id)
    result.passed = passed
    result.overall_score = 0.9 if passed else 0.2
    return result


def test_harness_gate_passes_when_all_cases_pass(tmp_path: Path) -> None:
    output = tmp_path / "gate.json"
    runner = _FakeRunner([_result("FCTA001", True), _result("FCTB003", True)])

    exit_code, report = run_gate(output=output, runner=runner)

    assert exit_code == 0
    assert report["blocking_failures"] == []
    assert output.exists()
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert saved["passed"] == 2


def test_harness_gate_allows_known_edge_case(tmp_path: Path) -> None:
    output = tmp_path / "gate.json"
    runner = _FakeRunner([_result("FCTA001", True), _result("sc6hrcta001", False)])

    exit_code, report = run_gate(
        output=output,
        runner=runner,
        allow_known_edge=True,
    )

    assert exit_code == 0
    assert report["allowed_edge_cases"] == ["sc6hrcta001"]
    assert report["blocking_failures"] == []


def test_harness_gate_blocks_unknown_failure(tmp_path: Path) -> None:
    output = tmp_path / "gate.json"
    runner = _FakeRunner([_result("FCTA001", True), _result("NEWCASE", False)])

    exit_code, report = run_gate(output=output, runner=runner, cases=["NEWCASE"])

    assert exit_code == 1
    assert report["blocking_failures"] == ["NEWCASE"]
    assert runner.requested_cases == ["NEWCASE"]
