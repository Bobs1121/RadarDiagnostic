# -*- coding: utf-8 -*-
"""Offline unit tests for the ``ai.requirements`` engine (M3 + M8).

These run without network, Ollama, a real CodeGraph DB, or pydantic installed.
All external dependencies are stubbed/injected.
"""
from __future__ import annotations

import textwrap

from ai.requirements import (
    RequirementLoader,
    RequirementModule,
    RequirementReviewer,
    RequirementTracer,
)
from core.materials import RequirementSpec, StructuredRequirementSet


# ── sample YAML ────────────────────────────────────────────────────────

SINGLE_REQ = """\
req_id: REQ-BSM-ACT-001
feature: BSM_Activation
description: BSD activates when ego speed is between 30 and 150 kph.
preconditions:
  - signal_alias: EGO_GEAR
    operator: "=="
    value: DRIVE
activation_conditions:
  - signal_alias: EGO_SPEED_KPH
    operator: ">="
    value: 30
  - signal_alias: EGO_SPEED_KPH
    operator: "<="
    value: 150
expected_output_signal: BSM_SYSTEM_STATE
"""

LIST_REQ = """\
- req_id: REQ-DOW-001
  feature: DOW
  description: Door open warning.
  activation_conditions:
    - signal_alias: DOOR_ZONE_OCCUPIED
      operator: "=="
      value: true
  expected_output_signal: DOW_STATE
- req_id: REQ-RCW-001
  feature: RCW
  description: Rear collision warning.
  activation_conditions:
    - signal_alias: REAR_TTC
      operator: "<"
      value: 2.0
  expected_output_signal: RCW_STATE
"""

SIGNAL_MAPPING = {
    "can_to_internal": {
        "EGO_SPEED_KPH": ["egoSpeed"],
        "EGO_GEAR": ["egoGear"],
        "BSM_SYSTEM_STATE": ["bsmState"],
        "DOOR_ZONE_OCCUPIED": ["doorZone"],
        "DOW_STATE": ["dowState"],
        "REAR_TTC": ["rearTtc"],
        "RCW_STATE": ["rcwState"],
    }
}


def _write(tmp_path, name, content):
    p = tmp_path / name
    p.write_text(textwrap.dedent(content), encoding="utf-8")
    return p


class FakeCodeGraph:
    """Minimal stub exposing only the method the tracer needs."""

    def __init__(self, mapping):
        self._mapping = mapping

    def get_functions_using_signal(self, signal_name):
        return list(self._mapping.get(signal_name, []))


# ── loader ─────────────────────────────────────────────────────────────

def test_loader_parses_single_and_list(tmp_path):
    _write(tmp_path, "single.yaml", SINGLE_REQ)
    _write(tmp_path, "many.yaml", LIST_REQ)

    req_set = RequirementLoader().load_yaml_dir(tmp_path, variant_id="gwm_b26")

    assert isinstance(req_set, StructuredRequirementSet)
    assert req_set.variant_id == "gwm_b26"
    assert set(req_set.requirements) == {
        "REQ-BSM-ACT-001",
        "REQ-DOW-001",
        "REQ-RCW-001",
    }

    bsm = req_set.get("REQ-BSM-ACT-001")
    # signals harvested from conditions + expected_output_signal
    assert "EGO_SPEED_KPH" in bsm.linked_signals
    assert "EGO_GEAR" in bsm.linked_signals
    assert "BSM_SYSTEM_STATE" in bsm.linked_signals
    # structured conditions preserved for downstream trace/review
    assert bsm.metadata["activation_conditions"][0]["signal_alias"] == "EGO_SPEED_KPH"


def test_loader_single_file_returns_list(tmp_path):
    path = _write(tmp_path, "many.yaml", LIST_REQ)
    specs = RequirementLoader().load_yaml_file(path, variant_id="v")
    assert isinstance(specs, list)
    assert [s.requirement_id for s in specs] == ["REQ-DOW-001", "REQ-RCW-001"]
    assert all(s.variant_id == "v" for s in specs)


def test_validate_structure_flags_missing_id_and_bad_operator():
    bad = {
        "activation_conditions": [
            {"signal_alias": "EGO_SPEED_KPH", "operator": "=>", "value": 5}
        ]
    }
    problems = RequirementLoader().validate_structure(bad)
    assert any("missing req_id" in p for p in problems)
    assert any("operator" in p and "=>" in p for p in problems)


def test_validate_structure_accepts_good_requirement():
    import yaml

    good = yaml.safe_load(textwrap.dedent(SINGLE_REQ))
    problems = RequirementLoader().validate_structure(good)
    assert problems == []


def test_loader_preserves_schema_validation_problems_for_review(tmp_path):
    _write(
        tmp_path,
        "bad.yaml",
        """\
        req_id: REQ-BAD-OP
        feature: BSM
        description: Invalid operator should be reviewable.
        activation_conditions:
          - signal_alias: EGO_SPEED_KPH
            operator: "=>"
            value: 5
        expected_output_signal: BSM_SYSTEM_STATE
        """,
    )

    req_set = RequirementLoader().load_yaml_dir(tmp_path)
    spec = req_set.get("REQ-BAD-OP")

    assert spec.metadata["schema_problems"] == [
        "activation_conditions[0] invalid operator '=>'"
    ]

    result = RequirementReviewer().review(req_set)
    assert any(
        i["req_id"] == "REQ-BAD-OP"
        and i["category"] == "schema-validation"
        and "=>" in i["message"]
        for i in result["issues"]
    )


# ── tracer ─────────────────────────────────────────────────────────────

def test_tracer_coverage_classification():
    codegraph = FakeCodeGraph(
        {
            "SIG_A": [{"func_name": "FnA", "file_id": "FILE:a.c"}],
            "SIG_B": [{"func_name": "FnB", "file_id": "FILE:b.c"}],
        }
    )
    tracer = RequirementTracer(
        codegraph=codegraph,
        signal_mapping={"can_to_internal": {"SIG_A": ["a"], "SIG_B": ["b"]}},
    )

    spec_full = RequirementSpec(
        requirement_id="R1", statement="full", linked_signals=["SIG_A", "SIG_B"]
    )
    spec_partial = RequirementSpec(
        requirement_id="R2", statement="partial", linked_signals=["SIG_A", "SIG_MISSING"]
    )
    spec_none = RequirementSpec(
        requirement_id="R3", statement="none", linked_signals=["SIG_MISSING"]
    )

    assert tracer.trace(spec_full)["coverage"] == "full"

    partial = tracer.trace(spec_partial)
    assert partial["coverage"] == "partial"
    assert any("SIG_MISSING" in g for g in partial["gaps"])

    assert tracer.trace(spec_none)["coverage"] == "none"

    # per-signal linkage populated + FILE: prefix stripped
    entry = tracer.trace(spec_full)["signals"][0]
    assert entry["name"] == "SIG_A"
    assert entry["functions"] == ["FnA"]
    assert entry["files"] == ["a.c"]
    assert entry["in_dbc"] is True


def test_tracer_handles_no_codegraph_and_empty():
    tracer = RequirementTracer(codegraph=None)
    spec = RequirementSpec(requirement_id="R", linked_signals=["X"])
    result = tracer.trace(spec)
    assert result["coverage"] == "none"
    assert result["signals"][0]["functions"] == []
    # None / empty inputs are graceful
    assert tracer.trace(None)["coverage"] == "none"
    assert tracer.trace_set(None) == []


def test_tracer_trace_set_over_requirement_set(tmp_path):
    _write(tmp_path, "single.yaml", SINGLE_REQ)
    req_set = RequirementLoader().load_yaml_dir(tmp_path)
    tracer = RequirementTracer(signal_mapping=SIGNAL_MAPPING)
    traces = tracer.trace_set(req_set)
    assert len(traces) == 1
    assert traces[0]["req_id"] == "REQ-BSM-ACT-001"


# ── reviewer ───────────────────────────────────────────────────────────

def test_reviewer_flags_contradiction_and_missing_dbc():
    req_set = StructuredRequirementSet(variant_id="v")
    req_set.add(
        RequirementSpec(
            requirement_id="REQ-CONTRA",
            statement="bad range",
            linked_signals=["EGO_SPEED_KPH"],
            metadata={
                "activation_conditions": [
                    {"signal_alias": "EGO_SPEED_KPH", "operator": ">=", "value": 150},
                    {"signal_alias": "EGO_SPEED_KPH", "operator": "<=", "value": 30},
                ]
            },
        )
    )
    req_set.add(
        RequirementSpec(
            requirement_id="REQ-GHOST",
            statement="ghost signal",
            linked_signals=["GHOST_SIGNAL"],
            metadata={
                "activation_conditions": [
                    {"signal_alias": "GHOST_SIGNAL", "operator": ">", "value": 1}
                ]
            },
        )
    )

    result = RequirementReviewer(router=None, signal_mapping=SIGNAL_MAPPING).review(req_set)

    cats = {(i["req_id"], i["category"]) for i in result["issues"]}
    assert ("REQ-CONTRA", "contradiction") in cats
    assert ("REQ-GHOST", "dbc-observability") in cats
    assert result["summary"]["n_reqs"] == 2
    assert result["summary"]["by_severity"]["error"] >= 2


def test_reviewer_runs_without_router_or_mapping():
    req_set = StructuredRequirementSet(variant_id="v")
    req_set.add(
        RequirementSpec(
            requirement_id="R1",
            statement="ok",
            linked_signals=["EGO_SPEED_KPH"],
            metadata={
                "activation_conditions": [
                    {"signal_alias": "EGO_SPEED_KPH", "operator": ">=", "value": 30}
                ]
            },
        )
    )
    result = RequirementReviewer().review(req_set)  # no router, no mapping
    assert result["summary"]["n_reqs"] == 1
    assert "issues" in result
    # without a mapping, dbc-observability is skipped entirely
    assert all(i["category"] != "dbc-observability" for i in result["issues"])


def test_reviewer_flags_untestable_requirement():
    req_set = StructuredRequirementSet()
    req_set.add(RequirementSpec(requirement_id="R-NOTEST", statement="prose only"))
    result = RequirementReviewer().review(req_set)
    assert any(i["category"] == "testability" for i in result["issues"])


# ── module ─────────────────────────────────────────────────────────────

def test_module_safe_run_all_mode(tmp_path):
    _write(tmp_path, "single.yaml", SINGLE_REQ)
    _write(tmp_path, "many.yaml", LIST_REQ)

    module = RequirementModule(
        codegraph=FakeCodeGraph({}), signal_mapping=SIGNAL_MAPPING
    )
    result = module.safe_run(req_dir=str(tmp_path), mode="all", variant_id="gwm_b26")

    assert result.ok is True
    assert result.module == "req-review"
    assert result.data["n_reqs"] == 3
    assert "traces" in result.data
    assert "review" in result.data
    assert result.data["review"]["summary"]["n_reqs"] == 3


def test_module_fails_without_input():
    result = RequirementModule().safe_run(mode="review")
    assert result.ok is False
    assert "no requirements" in result.message.lower()


def test_module_rejects_unknown_mode(tmp_path):
    _write(tmp_path, "single.yaml", SINGLE_REQ)
    result = RequirementModule().safe_run(req_dir=str(tmp_path), mode="bogus")
    assert result.ok is False
    assert "unknown mode" in result.message.lower()
