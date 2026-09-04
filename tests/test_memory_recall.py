# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from ai.capability.pi_tool_bridge import available_capabilities
from ai.modules import MODULE_REGISTRY
from ai.modules.memory_recall import MemoryRecallModule
from engines.memory_recall import recall_memory


def test_memory_recall_reads_explicit_layers_with_provenance(tmp_path: Path):
    memory = tmp_path / "memory"
    (memory / "functions").mkdir(parents=True)
    (memory / "code_knowledge").mkdir(parents=True)
    (memory / "project.md").write_text("project note", encoding="utf-8")
    (memory / "functions" / "FCTA.json").write_text(json.dumps({"state": "active"}), encoding="utf-8")
    (memory / "code_knowledge" / "constants.json").write_text(json.dumps({"function_thresholds": {"X": {"value": 1}}}), encoding="utf-8")
    payload = recall_memory(
        project_root=str(tmp_path), memory_dir=str(memory), function="FCTA",
        query="报警", layers=["project", "function", "constants"],
    )
    assert payload["status"] == "ready"
    assert {item["layer"] for item in payload["items"]} == {"project", "function", "constants"}
    assert all(item["provenance"]["memory_dir"] == str(memory.resolve()) for item in payload["items"])
    Draft202012Validator(
        json.loads(Path("contracts/memory-recall.v1.schema.json").read_text(encoding="utf-8"))
    ).validate(payload)


def test_memory_recall_blocks_code_derived_layers_without_variant_freshness(tmp_path: Path):
    memory = tmp_path / "memory"
    (memory / "code_knowledge").mkdir(parents=True)
    (memory / "code_knowledge" / "constants.json").write_text(json.dumps({"X": 1}), encoding="utf-8")
    payload = recall_memory(
        project_root=str(tmp_path), memory_dir=str(memory), variant_id="gen6/demo",
        function="FCTA", query="报警", layers=["patterns", "code_knowledge", "constants", "semantic"],
    )
    assert payload["status"] == "partial"
    assert all(item["status"] == "blocked_stale" for item in payload["items"])


def test_memory_recall_module_is_registered_and_pi_visible(tmp_path: Path):
    assert MODULE_REGISTRY["memory-recall"] is MemoryRecallModule
    assert "memory-recall" in available_capabilities()
    result = MemoryRecallModule().safe_run(
        project_root=str(tmp_path), layers=["project"],
    )
    assert result.ok
    assert result.data["schema_version"] == "memory-recall.v1"


def test_memory_recall_can_take_variant_scope_from_orchestration_context(tmp_path: Path):
    memory = tmp_path / "scoped-memory"
    (memory / "code_knowledge").mkdir(parents=True)
    (memory / "code_knowledge" / "constants.json").write_text(json.dumps({"X": 1}), encoding="utf-8")
    payload = recall_memory(
        project_root=str(tmp_path),
        context={
            "schema_version": "pi-orchestration-context.v1",
            "project": {"variant_id": "gen6/demo"},
            "memory_dir": str(memory),
        },
        layers=["code_knowledge"],
    )
    assert payload["scope"]["variant_id"] == "gen6/demo"
    assert payload["items"][0]["status"] == "blocked_stale"
    assert payload["items"][0]["provenance"]["source"] == "orchestration_context"
