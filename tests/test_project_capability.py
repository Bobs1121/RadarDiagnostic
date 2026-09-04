# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from ai.capability.registry import capability_catalog
from ai.modules.project_capability import ProjectCapabilityManifestModule
from engines.project_capability import build_project_capability_manifest


def _inputs() -> dict:
    return {
        "identity": {"project_id": "gen6/byd_sc6h"},
        "intake": {
            "schema_version": "cr60-analysis-intake.v1",
            "identity": {
                "function": {"status": "resolved", "value": "FCTB"},
                "vehicle": {"status": "resolved", "value": "BYD_UKE"},
            },
            "data": {
                "path": {"status": "resolved", "value": "/data/example.bag"},
            },
        },
        "preflight": {
            "schema_version": "arbe-preflight.v1",
            "status": "ready",
            "workspace": {"path": "/work/arbe", "exists": True},
            "gdb": {"available": True},
        },
        "code_context": {
            "schema_version": "code-context.v1",
            "status": "ready",
            "source_context": {
                "coem": "BYD_UKE",
                "source_snapshot_hash": "source-hash",
            },
            "summary": {"functions": 10, "conditions": 5},
        },
        "runtime_snapshot": {
            "schema_version": "runtime-snapshot-with-frame.v1",
            "status": "ready",
        },
        "diagnosis_bundle": {
            "schema_version": "diagnosis-bundle.v1",
            "case": {"case_id": "CASE001"},
        },
    }


def test_manifest_is_source_and_artifact_bound_without_feature_hardcoding():
    payload = build_project_capability_manifest(**_inputs(), variant_id="byd_sc6h")

    assert payload["schema_version"] == "project-capability-manifest.v1"
    assert payload["status"] == "ready"
    assert payload["identity"]["function"] == "FCTB"
    assert payload["identity"]["coem"] == "BYD_UKE"
    assert {item["id"] for item in payload["code_capabilities"]} >= {
        "source-context", "code-index", "code-analyze", "code-gdb-plan"
    }
    assert payload["runtime_capabilities"][0]["id"] == "public-runtime-snapshot"
    assert {item["id"] for item in payload["replay_capabilities"]} == {"arbe-workspace"}
    assert not any("FCTA" in json.dumps(item) for item in payload["feature_capabilities"])
    assert any(item["id"] == "sprint1-report" for item in payload["presentation_capabilities"])
    assert any(item["id"] == "detailed-diagnostic-report" for item in payload["presentation_capabilities"])
    assert payload["freshness"]["source_snapshot_hash"] == "source-hash"
    assert payload["manifest_fingerprint"]


def test_manifest_preserves_missing_capabilities_as_unsupported():
    payload = build_project_capability_manifest()

    assert payload["status"] == "partial"
    unsupported = {item["id"] for item in payload["unsupported"]}
    assert {"intake-binding", "code-index", "public-runtime-snapshot", "headless-gdb"} <= unsupported


def test_manifest_blocks_mixed_source_snapshots_before_pi_consumes_it():
    inputs = _inputs()
    inputs["diagnosis_bundle"]["provenance"] = {"source_snapshot_hash": "other-source"}
    payload = build_project_capability_manifest(**inputs)

    assert payload["status"] == "blocked"
    assert payload["freshness"]["status"] == "conflict"
    assert payload["conflicts"][0]["field"] == "source_snapshot_hash"
    assert "source-consistency" in {item["id"] for item in payload["unsupported"]}


def test_manifest_module_writes_and_validates_contract(tmp_path: Path):
    output = tmp_path / "project-capability-manifest.json"
    result = ProjectCapabilityManifestModule().safe_run(**_inputs(), output=str(output))

    assert result.ok
    assert output.exists()
    payload = json.loads(output.read_text(encoding="utf-8"))
    schema = json.loads(
        Path("contracts/project-capability-manifest.v1.schema.json").read_text(encoding="utf-8")
    )
    Draft202012Validator(schema).validate(payload)
    assert result.data["artifact_path"] == str(output.resolve())


def test_manifest_is_one_pi_visible_capability():
    catalog = {item["name"]: item for item in capability_catalog()}
    assert catalog["project-capability-manifest"]["expose_to_pi"] is True
