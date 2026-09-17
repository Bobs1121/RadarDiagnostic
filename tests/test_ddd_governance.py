from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

from tools.check_ddd import check, validate_state
from tools.release_gate import evaluate_manifest

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "docs/technical/gen6_execution_state.v1.json"
ACS = {f"G6-AC{i:02}" for i in range(1, 17)}


def test_active_docs_archive_and_task_graph_are_consistent():
    result = check(ROOT)
    assert result["status"] == "documents_valid", result["errors"]
    assert result["release_acceptance"] == "not_evaluated"


def test_dependency_cycle_and_evidenceless_completion_are_rejected():
    state = deepcopy(json.loads(STATE.read_text(encoding="utf-8")))
    state["tasks"][0]["depends_on"] = [state["tasks"][-1]["id"]]
    state["tasks"][0]["status"] = "done"
    state["tasks"][0]["evidence"] = []  # force the evidenceless-done condition regardless of live task state
    errors = validate_state(state, ACS)
    assert any(error.startswith("dependency_cycle:") for error in errors)
    assert "T00:done_without_evidence" in errors
    assert any("dependency_not_done" in error for error in errors)


def test_local_command_cannot_replace_required_runtime_evidence(tmp_path):
    evidence = tmp_path / "unit.txt"
    evidence.write_text("unit success", encoding="utf-8")
    payload = {"schema_version": "release-acceptance.v1", "entries": [{
        "id": "G6-AC04", "status": "accepted", "required_for_release": True,
        "required_test_levels": ["real-replay/GDB"], "command": ["python", "-c", "pass"],
        "evidence": [{"path": "unit.txt", "test_level": "unit/contract",
                      "sha256": hashlib.sha256(evidence.read_bytes()).hexdigest()}],
    }]}
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    report = evaluate_manifest(manifest, project_root=tmp_path, run_checks=True)
    assert report["status"] == "blocked"
    assert any("test_level_evidence_missing:real-replay/GDB" in e for e in report["errors"])


def test_empty_command_and_evidence_cannot_accept_release(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"schema_version": "release-acceptance.v1", "entries": [{
        "id": "G6-AC01", "required_for_release": True, "status": "accepted", "command": [], "evidence": [],
    }]}), encoding="utf-8")
    report = evaluate_manifest(manifest, project_root=tmp_path, run_checks=True)
    assert report["status"] == "blocked"
    assert any("command_missing" in e for e in report["errors"])
    assert any("evidence_missing" in e for e in report["errors"])
