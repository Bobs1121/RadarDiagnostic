# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path

from ai.capability.registry import capability_catalog
from ai.modules import MODULE_REGISTRY
from ai.modules.pi_context import PiContextModule
from ai.modules.pi import discover_case_artifacts
from engines.pi_context import build_pi_orchestration_context


def _resolved(value, field):
    return {
        "status": "resolved",
        "value": value,
        "selected_from": {
            "field": field,
            "source": "test-material",
            "locator": f"material.{field}",
        },
    }


def _intake():
    return {
        "schema_version": "cr60-analysis-intake.v1",
        "status": "ready",
        "intake_status": "ready",
        "data": {
            "root": "/data/case-1",
            "paths": [{"path": "/data/case-1/a.bag"}],
            "cases": [{"case_id": "case-1", "bag_paths": ["/data/case-1/a.bag"]}],
        },
        "identity": {
            "vehicle": _resolved("SC6H", "vehicle"),
            "customer": _resolved("BYD", "customer"),
            "coem": _resolved("BYD_UKE", "coem"),
            "software_version": _resolved("v1", "software_version"),
            "code_branch": _resolved("feature/v1", "code_branch"),
        },
        "source_context": {
            "server_host": _resolved("10.0.0.1", "server_host"),
            "server_user": _resolved("tester", "server_user"),
            "arbe_root": _resolved("/opt/arbe", "arbe_root"),
            "algo_source_root": _resolved("/opt/arbe/src/algo_source", "algo_source_root"),
        },
        "missing": [],
        "conflicts": [],
    }


def _preflight():
    return {
        "schema_version": "arbe-preflight.v1",
        "status": "ready",
        "workspace": {
            "arbe_root": "/opt/arbe",
            "algo_source_root": "/opt/arbe/src/algo_source",
            "outer": {"head": "outer-hash", "status_ok": True},
            "algo_source": {"head": "algo-hash", "status_ok": True},
        },
        "configuration": {"resolved": {"coem_name": "BYD_UKE", "radar_ids": ["1", "2", "3", "4"]}},
        "build": {"macros": {"HILMODEL": "2"}, "binary_candidates": ["/opt/arbe/bin/engine"]},
        "runtime": {"status": "ready", "processes": [{"pid": 42, "radar_id": 2}]},
        "gdb": {"available": True, "path": "/usr/bin/gdb"},
    }


def test_context_binds_upstream_artifacts_without_guessing():
    payload = build_pi_orchestration_context(
        intake=_intake(),
        preflight=_preflight(),
        project_id="byd-sc6h",
        variant_id="cr60/byd/sc6h",
        replay_strategy="sgu_injection",
        radar_id="2",
    )
    assert payload["schema_version"] == "pi-orchestration-context.v1"
    assert payload["status"] == "ready"
    assert len(payload["context_fingerprint"]) == 64
    assert payload["project"]["vehicle"] == "SC6H"
    assert payload["project"]["variant_id"] == "cr60/byd/sc6h"
    assert payload["source"]["algo_source_head"] == "algo-hash"
    assert payload["source"]["source_context_fingerprint"]
    assert payload["data"]["data_fingerprint"]
    assert payload["runtime"]["strategy"] == "sgu_injection"
    assert payload["runtime"]["radar_id_source"] == "explicit_input"
    json.dumps(payload, ensure_ascii=False)


def test_context_binds_project_capability_manifest_as_a_bounded_summary():
    manifest = {
        "schema_version": "project-capability-manifest.v1",
        "status": "ready",
        "manifest_fingerprint": "manifest-1",
        "code_capabilities": [{"id": "code-index", "status": "available"}],
        "runtime_capabilities": [{"id": "public-runtime-snapshot", "status": "available"}],
        "data_capabilities": [],
        "feature_capabilities": [],
        "replay_capabilities": [],
        "presentation_capabilities": [],
        "unsupported": [{"id": "point-cloud-runtime", "reason": "not supplied"}],
        "freshness": {"status": "fresh", "source_snapshot_hash": "source-1"},
    }
    payload = build_pi_orchestration_context(
        intake=_intake(),
        preflight=_preflight(),
        capability_manifest=manifest,
    )
    assert payload["status"] == "ready"
    assert payload["capabilities"]["status"] == "ready"
    assert payload["capabilities"]["manifest_fingerprint"] == "manifest-1"
    assert payload["capabilities"]["available"]["code_capabilities"] == [
        {"id": "code-index", "status": "available"}
    ]
    assert payload["capabilities"]["unsupported"][0]["id"] == "point-cloud-runtime"
    assert any(ref.get("kind") == "capability_manifest" for ref in payload["artifacts"])


def test_context_blocks_capability_manifest_source_snapshot_conflict():
    manifest = {
        "schema_version": "project-capability-manifest.v1",
        "status": "ready",
        "manifest_fingerprint": "manifest-conflict",
        "identity": {"project_id": "byd-sc6h"},
        "data_capabilities": [],
        "feature_capabilities": [],
        "code_capabilities": [],
        "replay_capabilities": [],
        "runtime_capabilities": [],
        "presentation_capabilities": [],
        "unsupported": [],
        "freshness": {"status": "fresh", "source_snapshot_hash": "different-source"},
    }
    preflight = _preflight()
    bundle = {
        "schema_version": "diagnosis-bundle.v1",
        "case": {"case_id": "case-conflict", "bag": "/data/case-conflict.bag"},
        "provenance": {
            "bag_path": "/data/case-conflict.bag",
            "source_context_id": "ctx",
            "source_snapshot_hash": "context-source",
        },
        "source_context": {
            "source_context_id": "ctx",
            "source_snapshot_hash": "context-source",
        },
        "alarm_events": [],
    }
    payload = build_pi_orchestration_context(
        intake=_intake(),
        preflight=preflight,
        diagnosis_bundle=bundle,
        capability_manifest=manifest,
    )
    assert payload["status"] == "blocked"
    assert "capability_manifest_source_snapshot_conflict" in payload["diagnostics"]
    assert any(
        item["reason"] == "capability_manifest_source_snapshot_mismatch"
        for item in payload["conflicts"]
    )


def test_context_is_partial_when_source_or_identity_needs_confirmation():
    intake = _intake()
    intake["intake_status"] = "needs_confirmation"
    intake["missing"] = ["code_branch_or_version_to_branch_mapping"]
    intake["conflicts"] = [{"field": "coem", "candidates": ["A", "B"]}]
    payload = build_pi_orchestration_context(intake=intake, case_dir="/data/case-1")
    assert payload["status"] == "partial"
    assert "code_branch_or_version_to_branch_mapping" in payload["missing"]
    assert payload["conflicts"][0]["field"] == "coem"
    assert "source_context_fingerprint" in payload["source"]


def test_context_without_case_is_blocked():
    payload = build_pi_orchestration_context(project_id="only-project")
    assert payload["status"] == "blocked"
    assert "data.case_or_intake" in payload["missing"]


def test_pi_context_is_registered_and_exposed_as_leaf_capability():
    assert MODULE_REGISTRY["pi-context"] is PiContextModule
    entry = next(item for item in capability_catalog() if item["name"] == "pi-context")
    assert entry["expose_to_pi"] is True
    assert "context" in entry["tags"]


def test_pi_context_module_can_write_a_context_artifact(tmp_path):
    output = tmp_path / "context.json"
    result = PiContextModule().safe_run(
        intake=_intake(),
        project_id="demo",
        case_dir="/data/case-1",
        output=str(output),
    )
    assert result.ok is True
    assert output.exists()
    assert json.loads(output.read_text(encoding="utf-8"))["schema_version"] == "pi-orchestration-context.v1"


def test_pi_context_exposes_runtime_evidence_as_deterministic_input():
    runtime = {
        "schema_version": "runtime-case-evidence.v1",
        "status": "ready",
        "run": {
            "run_id": "gdb-1",
            "data_fingerprint": "data-1",
            "source_context_id": "ctx-1",
            "source_snapshot_hash": "source-1",
            "bag": "/data/case-1/a.bag",
        },
        "evidence_layers": [{
            "id": "gdb",
            "kind": "gdb_observation",
            "authority": "headless-gdb",
            "status": "observed",
        }],
        "observations": [{
            "observation_id": "hit-1",
            "layer": "gdb_observation",
            "identity": {"radar_id": 2, "frame_id": 100, "object_id": 44},
            "fields": [{"token": "objInfo->trcOutData[i].flag", "value": 5, "status": "observed"}],
        }],
    }
    bundle = {
        "schema_version": "diagnosis-bundle.v1",
        "case": {"case_id": "case-1", "bag": "/data/case-1/a.bag"},
        "provenance": {"bag_path": "/data/case-1/a.bag", "source_context_id": "ctx-1", "source_snapshot_hash": "source-1"},
        "alarm_events": [],
    }
    debug_plan = {
        "schema_version": "runtime-debug-plan.v1",
        "status": "partial",
        "execution_status": "approval_required",
        "event": {"event_id": "event-1", "target_frame": 100},
        "replay": {"strategy": "sgu_injection"},
        "target": {"obj_id": 44},
        "breakpoints": [{"function": "CurrentFn", "condition": "frame_counter == 100"}],
        "gdb_commands": ["break current.c:1 if frame_counter == 100"],
        "capture_fields": [{"token": "frame_counter"}],
        "readiness": {"status": "partial", "blocking_gates": [], "warning_gates": ["approval"], "gates": []},
    }
    payload = build_pi_orchestration_context(
        intake=_intake(),
        preflight=_preflight(),
        case_dir="/data/case-1",
        runtime_evidence=runtime,
        diagnosis_bundle=bundle,
        runtime_debug_plan=debug_plan,
    )
    assert payload["runtime"]["evidence_status"] == "partial"  # ELF identity is absent from the bundle
    assert payload["runtime"]["evidence"]["observations"][0]["fields"][0]["token"] == "objInfo->trcOutData[i].flag"
    assert payload["runtime"]["evidence_binding"]["status"] == "partial"
    assert payload["runtime"]["evidence"]["merge"]["status"] == "partial"
    assert payload["runtime"]["debug_plan_status"] == "partial"
    assert payload["runtime"]["debug_plan"]["gdb_commands"] == ["break current.c:1 if frame_counter == 100"]
    json.dumps(payload, ensure_ascii=False)


def test_pi_case_artifact_discovery_is_explicit_and_local_only(tmp_path):
    (tmp_path / "diagnosis_bundle.json").write_text("{}", encoding="utf-8")
    (tmp_path / "viewer-model.json").write_text("{}", encoding="utf-8")
    (tmp_path / "runtime_evidence.json").write_text("{}", encoding="utf-8")
    (tmp_path / "runtime_debug_plan.json").write_text("{}", encoding="utf-8")
    (tmp_path / "diagnostic-report.json").write_text("{}", encoding="utf-8")
    (tmp_path / "evidence-query.json").write_text("{}", encoding="utf-8")
    discovered = discover_case_artifacts(str(tmp_path))
    assert set(discovered) == {
        "diagnosis_bundle_path", "viewer_model_path", "runtime_evidence_path", "runtime_debug_plan_path",
        "diagnostic_report_path", "evidence_query_path",
    }
    assert all(Path(value).is_absolute() for value in discovered.values())
    assert discover_case_artifacts(str(tmp_path / "not-a-case")) == {}


def test_pi_context_extracts_runtime_evidence_embedded_in_merged_bundle():
    bundle = {
        "schema_version": "diagnosis-bundle.v1",
        "case": {"case_id": "case-embedded", "bag": "/data/embedded.bag"},
        "provenance": {"bag_path": "/data/embedded.bag", "source_context_id": "ctx", "source_snapshot_hash": "src"},
        "runtime_evidence": {
            "schema_version": "runtime-case-evidence.v1",
            "status": "partial",
            "run": {"run_id": "run", "data_fingerprint": "data", "source_context_id": "ctx", "source_snapshot_hash": "src", "bag": "/data/embedded.bag"},
            "evidence_layers": [{"id": "gdb", "kind": "gdb_observation", "authority": "gdb", "status": "observed"}],
            "observations": [{"observation_id": "obs", "layer": "gdb_observation", "identity": {"frame_id": 1}, "fields": [{"token": "frame_counter", "value": 1, "status": "observed"}]}],
        },
        "alarm_events": [],
    }
    payload = build_pi_orchestration_context(diagnosis_bundle=bundle, case_dir="/data/embedded")
    assert payload["runtime"]["evidence_status"] == "partial"
    assert payload["runtime"]["evidence_ref"]["source"] == "embedded_in_diagnosis_bundle"
    assert payload["runtime"]["evidence"]["observations"][0]["fields"][0]["token"] == "frame_counter"


def test_pi_context_can_continue_from_bundle_without_reconstructing_intake():
    bundle = {
        "schema_version": "diagnosis-bundle.v1",
        "status": "ready",
        "case": {
            "case_id": "case-bundle-only",
            "bag": "/remote/data/case-bundle-only.bag",
            "functions": ["UNKNOWN_R"],
            "vehicle": {"length_m": 5.0, "width_m": 2.0},
        },
        "provenance": {
            "project": "cr60-light-arbe",
            "bag_path": "/remote/data/case-bundle-only.bag",
            "source_context_id": "ctx-bundle",
            "source_snapshot_hash": "snapshot-bundle",
        },
        "source_context": {
            "source_context_id": "ctx-bundle",
            "code_index_hash": "index-bundle",
            "identity": {
                "remote_host": "10.0.0.8",
                "remote_workspace": "/opt/arbe",
                "outer_head": "outer-bundle",
                "algo_head": "algo-bundle",
                "source_snapshot_hash": "snapshot-bundle",
            },
        },
        "alarm_events": [],
    }
    plan = {
        "schema_version": "runtime-debug-plan.v1",
        "status": "partial",
        "execution_status": "approval_required",
        "event": {"event_id": "event-bundle", "radar_id": 2, "target_frame": 100},
        "replay": {"strategy": "sgu_injection"},
        "target": {"obj_id": 44},
        "breakpoints": [],
        "gdb_commands": [],
        "capture_fields": [],
        "readiness": {"status": "partial", "blocking_gates": [], "warning_gates": [], "gates": []},
    }
    payload = build_pi_orchestration_context(
        diagnosis_bundle=bundle,
        runtime_debug_plan=plan,
    )
    assert payload["status"] != "blocked"
    assert payload["data"]["cases"][0]["case_id"] == "case-bundle-only"
    assert payload["data"]["paths"][0]["path"] == "/remote/data/case-bundle-only.bag"
    assert payload["project"]["project_id"] == "cr60-light-arbe"
    assert payload["project"]["case_id"] == "case-bundle-only"
    assert payload["source"]["server_host"] == "10.0.0.8"
    assert payload["runtime"]["strategy"] == "sgu_injection"
    assert payload["runtime"]["radar_id"] == "2"
    assert payload["runtime"]["radar_id_source"] == "runtime_debug_plan"
