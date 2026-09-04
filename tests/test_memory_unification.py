# -*- coding: utf-8 -*-
"""Stage 6 tests: memory unification.

Covers:
- single L6 writer: merge_code_knowledge preserves CodeLearner + precipitate data
- freshness gate extends to L3 patterns + semantic hits (code-derived learning)
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def _make_memory(tmp_path, freshness: dict | None = None):
    from memory.memory_system import MemorySystem

    config = {"identity": {"variant_id": "gen6/gwm_b26"}}
    if freshness is not None:
        config["identity"]["freshness"] = freshness
    return MemorySystem(tmp_path, config=config)


# ── Single L6 writer: merge_code_knowledge ─────────────────────────────────

class TestMergeCodeKnowledge:
    def test_preserves_both_sources(self, tmp_path: Path):
        ms = _make_memory(tmp_path)
        # CodeLearner-style seed
        ms.write_code_knowledge("FCTA", {
            "_meta": {"function": "FCTA", "learned_focuses": ["alarm_logic"]},
            "alarm_logic": {"trigger_conditions": [
                {"id": "CL-1", "description": "learner-sourced"},
            ]},
        })
        # Precipitate-style update
        ms.merge_code_knowledge("FCTA", {"alarm_logic": {"trigger_conditions": [
            {"id": "diag-1", "description": "diag-sourced", "_precipitated": True},
        ]}})
        data = ms.read_code_knowledge_raw("FCTA")
        ids = {i.get("id") for i in data["alarm_logic"]["trigger_conditions"]}
        assert {"CL-1", "diag-1"} == ids

    def test_idempotent_merge_replaces_same_id(self, tmp_path: Path):
        ms = _make_memory(tmp_path)
        ms.write_code_knowledge("RCTA", {
            "_meta": {"function": "RCTA"},
            "state_machine": {"transitions": [
                {"id": "diag-TR-1", "from": "A", "to": "B"},
            ]},
        })
        ms.merge_code_knowledge("RCTA", {"state_machine": {"transitions": [
            {"id": "diag-TR-1", "from": "A", "to": "C", "_precipitated": True},
        ]}})
        data = ms.read_code_knowledge_raw("RCTA")
        transitions = data["state_machine"]["transitions"]
        assert len(transitions) == 1
        assert transitions[0]["to"] == "C"

    def test_merge_preserves_meta(self, tmp_path: Path):
        ms = _make_memory(tmp_path)
        ms.merge_code_knowledge("DOW", {"alarm_logic": {"trigger_conditions": [
            {"id": "x", "description": "d"},
        ]}})
        data = ms.read_code_knowledge_raw("DOW")
        assert "alarm_logic" in data["_meta"]["learned_focuses"]


# ── Freshness gate on code-derived learning layers ─────────────────────────

class TestFreshnessGatingL1L5:
    def test_stale_code_withholds_l3_patterns(self, tmp_path: Path):
        ms = _make_memory(tmp_path, freshness={"code_changed": True})
        ms.add_pattern({
            "symptom": "FCTA no warn", "root_cause": "threshold",
            "function": "FCTA", "case_id": "c1", "detail": "x",
            "keywords": ["FCTA", "warn"],
        })
        ctx = ms.build_context_for_diagnosis("FCTA", "FCTA no warn", case_dir=tmp_path)
        assert "代码已漂移" in ctx
        assert "Auto-Dream 学习产物暂不注入" in ctx

    def test_fresh_code_includes_l3_patterns(self, tmp_path: Path):
        ms = _make_memory(tmp_path, freshness={"code_changed": False})
        ms.add_pattern({
            "symptom": "FCTA no warn", "root_cause": "threshold",
            "function": "FCTA", "case_id": "c1", "detail": "x",
            "keywords": ["FCTA", "warn"],
        })
        ctx = ms.build_context_for_diagnosis("FCTA", "FCTA no warn", case_dir=tmp_path)
        assert "相似历史案例" in ctx
        assert "FCTA no warn" in ctx