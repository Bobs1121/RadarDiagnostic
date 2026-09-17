from __future__ import annotations

import json
from pathlib import Path

from tools.release_gate import evaluate_manifest


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs" / "archive" / "2026-09-17" / "technical" / "release_acceptance.v1.json"
ACTIVE_MANIFEST = ROOT / "docs" / "technical" / "release_acceptance.v1.json"


def test_release_manifest_has_unique_required_entries_and_known_baseline():
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    entries = payload["entries"]
    ids = [entry["id"] for entry in entries]
    assert payload["schema_version"] == "release-acceptance.v1"
    assert len(ids) == len(set(ids))
    assert all(entry["phase"] in {"M0", "M1", "M2", "M3", "M4"} for entry in entries)
    assert all(entry["status"] for entry in entries)


def test_release_manifest_tracks_all_point_cloud_acceptance_ids_without_overclaiming():
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    point_cloud = {entry["id"]: entry for entry in payload["entries"] if entry["id"].startswith("PC-AC-")}
    assert set(point_cloud) == {f"PC-AC-{index:02d}" for index in range(1, 13)}
    assert point_cloud["PC-AC-01"]["status"] == "accepted"
    assert point_cloud["PC-AC-09"]["status"] == "accepted"
    assert point_cloud["PC-AC-10"]["status"] == "accepted"
    for ac_id in ("PC-AC-02", "PC-AC-03", "PC-AC-04", "PC-AC-05", "PC-AC-06", "PC-AC-07", "PC-AC-08", "PC-AC-11", "PC-AC-12"):
        assert point_cloud[ac_id]["required_for_release"] is False
        assert point_cloud[ac_id]["status"] == "partially-verified"


def test_release_gate_plan_mode_checks_evidence_and_required_commands():
    report = evaluate_manifest(MANIFEST, project_root=ROOT, run_checks=False)
    assert report["status"] == "blocked"  # plan mode must not claim release acceptance
    assert "checks_not_run" in " ".join(report["errors"])


def test_release_gate_accepts_required_local_contract_when_checks_run():
    report = evaluate_manifest(MANIFEST, project_root=ROOT, run_checks=True)
    assert report["status"] == "accepted", report["errors"]
    assert report["passed_required"] == report["required_entries"]


def test_new_gen6_scope_is_not_accepted_by_historical_local_checks():
    payload = json.loads(ACTIVE_MANIFEST.read_text(encoding="utf-8"))
    assert payload["release_id"] == "gen6-ai-first-release"
    assert {entry["id"] for entry in payload["entries"]} == {
        f"G6-AC{index:02}" for index in range(1, 17)
    }
    assert all(entry["required_for_release"] for entry in payload["entries"])
    report = evaluate_manifest(ACTIVE_MANIFEST, project_root=ROOT, run_checks=False)
    assert report["status"] == "blocked"
