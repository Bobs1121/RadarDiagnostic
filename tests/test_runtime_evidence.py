# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from copy import deepcopy

from ai.capability.registry import capability_catalog
from ai.modules import MODULE_REGISTRY
from ai.modules.runtime_evidence import (
    RuntimeEvidenceComposeModule,
    RuntimeEvidenceMergeModule,
    RuntimeEvidenceNormalizeModule,
    RuntimeEvidenceValidateModule,
)
from engines.runtime_evidence import (
    compose_runtime_evidence,
    merge_runtime_evidence,
    normalize_runtime_evidence,
    parse_runtime_markers,
    runtime_summary,
    validate_runtime_binding,
)


def _bundle(*, context: str = "ctx-1") -> dict:
    return {
        "schema_version": "diagnosis-bundle.v1",
        "case": {"case_id": "C1", "bag": "/data/C1/a.bag"},
        "provenance": {
            "bag_path": "/data/C1/a.bag",
            "source_context_id": context,
            "source_snapshot_hash": "source-1",
        },
        "source_context": {
            "source_context_id": context,
            "source_snapshot_hash": "source-1",
            "identity": {"source_snapshot_hash": "source-1"},
        },
        "alarm_events": [
            {
                "event_id": "event-1",
                "function": "UNKNOWN_R",
                "radar_id": 2,
                "selected_target": {"obj_id": 44},
                "replay_plan": {"target_frame_id": 100},
                "frame_evidence": [{"frame_id": 99}, {"frame_id": 100}],
                "static_fact": "must-remain",
            }
        ],
    }


def _evidence(*, context: str = "ctx-1") -> dict:
    return normalize_runtime_evidence(
        transcript=(
            "CR60_RUNTIME observation_id=hit-1 layer=gdb_observation frame_id=100 "
            "radar_id=2 object_id=44 function=CurrentFn field_token=i field_value=0 "
            "phase=during\n"
            "CR60_RUNTIME observation_id=hit-1 layer=gdb_observation frame_id=100 "
            "radar_id=2 object_id=44 field_token=objInfo->trcOutData[i].flag "
            "field_value=5 phase=after\n"
        ),
        run={
            "run_id": "run-1",
            "data_fingerprint": "data-1",
            "source_context_id": context,
            "source_snapshot_hash": "source-1",
            "bag": "/data/C1/a.bag",
        },
    )


def test_runtime_marker_parser_preserves_unknown_tokens_and_source_tokens():
    rows = parse_runtime_markers(
        'CR60_RUNTIME observation_id=x field_token="sObj->objID" field_value=44\n'
    )
    assert rows[0]["fields"]["field_token"] == "sObj->objID"
    assert rows[0]["fields"]["field_value"] == 44


def test_runtime_summary_is_bounded_but_keeps_total_count():
    evidence = {
        "schema_version": "runtime-case-evidence.v1",
        "status": "ready",
        "run": {"run_id": "r"},
        "observations": [
            {"observation_id": str(index), "identity": {}, "fields": []}
            for index in range(40)
        ],
    }
    summary = runtime_summary(evidence)
    assert summary["observation_count"] == 40
    assert len(summary["observations"]) == 24
    assert summary["observation_sampled"] is True
    assert summary["observations"][0]["observation_id"] == "0"
    assert summary["observations"][-1]["observation_id"] == "39"


def test_runtime_normalizer_builds_structured_observation():
    evidence = _evidence()
    assert evidence["schema_version"] == "runtime-case-evidence.v1"
    assert evidence["observations"][0]["observation_id"] == "hit-1"
    assert [field["token"] for field in evidence["observations"][0]["fields"]] == [
        "i",
        "objInfo->trcOutData[i].flag",
    ]
    assert evidence["observations"][0]["identity"]["frame_id"] == 100


def test_runtime_normalizer_consumes_generic_gdb_session_without_feature_assumptions():
    evidence = normalize_runtime_evidence(
        {
            "schema_version": "gdb-session.v1",
            "target": {"radar_id": 3, "frame_id": 7, "object_id": 9},
            "commands": ["bt 2", "p frame_counter", "p missing_value"],
            "stdout": "Breakpoint 1, Gate() at gate.c:9\n#0 Gate() at gate.c:9\n$1 = 7\n$2 = <optimized out>\n",
        },
        run={"run_id": "gdb-run", "data_fingerprint": "d", "source_context_id": "c"},
    )
    assert evidence["observations"]
    generic = evidence["observations"][0]
    assert generic["identity"]["radar_id"] == 3
    assert generic["fields"][0]["token"] == "frame_counter"
    assert generic["fields"][1]["status"] == "optimized_out"


def test_runtime_normalizer_projects_public_snapshot_without_losing_association_quality():
    snapshot = {
        "schema_version": "runtime-snapshot-with-frame.v1",
        "status": "partial",
        "source_context": {"source_snapshot_hash": "source-1", "bag": "/data/C1/a.bag"},
        "snapshots": [
            {
                "radar_id": 2,
                "frame_id": 100,
                "warning": {
                    "source": "warning_status_with_frame",
                    "data": [2, 100, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 2, 0, 2, 0],
                    "warnings": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 1, 0],
                    "message_seq": 3,
                },
                "radar_info": {
                    "data": [2.0, 3.2, 0.1, 12.0, 100.0, 6.0],
                    "message_seq": 4,
                },
                "objects": [
                    {
                        "association_status": "publication_correlated",
                        "object_index": 0,
                        "fields": {
                            "ID": 0,
                            "objID": 44,
                            "distX": 5.0,
                            "position": {"x": 5.0, "y": -2.0},
                            "objFctbWarningFlag": 5,
                            "object_message_seq": 1,
                        },
                    }
                ],
            }
        ],
        "unbound_objects": [
            {
                "radar_id": 2,
                "object_index": 1,
                "fields": {"ID": 0, "objID": 19, "distX": 20.0},
            }
        ],
        "ignored_objects": [],
        "diagnostics": [],
    }
    evidence = normalize_runtime_evidence(
        snapshot,
        run={"run_id": "public-run", "data_fingerprint": "data-1", "source_context_id": "ctx-1"},
        public_warning_names=["FCTA_R", "FCTB_R"],
    )
    assert evidence["schema_version"] == "runtime-case-evidence.v1"
    assert evidence["status"] == "partial"
    assert {item["kind"] for item in evidence["evidence_layers"]} == {
        "runtime_with_frame", "objectlist_candidate"
    }
    target = next(item for item in evidence["observations"] if item["identity"].get("object_id") == 44)
    assert target["identity"]["frame_id"] == 100
    assert target["identity"]["frame_source"] == "publication_order_derived"
    tokens = {item["token"] for item in target["fields"]}
    assert "wfObjectMsg.ObjectsBuffer[0].distX" in tokens
    assert "wfObjectMsg.ObjectsBuffer[0].position.x" in tokens
    assert any(item["identity"].get("frame_source") == "not_available" for item in evidence["observations"])


def test_runtime_normalizer_keeps_resilient_gdb_errors_on_expression_fields():
    evidence = normalize_runtime_evidence(
        {
            "schema_version": "gdb-session.v1",
            "target": {"radar_id": 2, "frame_id": 100},
            "commands": ["python", "end"],
            "stdout": (
                'CR60_GDB_EXPR token="i" phase="during" scope="Handler"\n'
                "$1 = 0\n"
                'CR60_GDB_EXPR token="missing_local" phase="during" scope="Handler"\n'
                'CR60_GDB_ERROR token="missing_local" error=No symbol "missing_local" in current context.\n'
            ),
        },
        run={"run_id": "gdb-resilient", "data_fingerprint": "d", "source_context_id": "c"},
    )
    assert len(evidence["observations"]) == 1
    fields = {field["token"]: field for field in evidence["observations"][0]["fields"]}
    assert fields["i"]["value"] == 0
    assert fields["missing_local"]["status"] == "not_found"


def test_runtime_normalizer_extracts_gdb_struct_geometry_without_feature_rules():
    evidence = normalize_runtime_evidence(
        {
            "schema_version": "gdb-session.v1",
            "target": {"radar_id": 2, "frame_id": 100},
            "commands": ["p objInfo->trcOutData[i]", "p *rightRoi"],
            "stdout": (
                'CR60_GDB_EXPR token="objInfo->trcOutData[i]" phase="during"\n'
                "$1 = {distX = 5.0, distY = -2.0, length = 4.0, width = 1.8, yawAng = 40.0, objID = 44, fTTC = 1.2, objFctaWarningFlag = 4, rightFctaFlag = true, fInterX = 8.3, fInterY = 0}\n"
                'CR60_GDB_EXPR token="*rightRoi" phase="during"\n'
                "$2 = {num = 4, points = {{x = 3.0, y = 0}, {x = 5.0, y = 0}, {x = 5.0, y = -2.0}, {x = 3.0, y = -2.0}}}\n"
            ),
        },
        run={"run_id": "gdb-struct", "data_fingerprint": "d", "source_context_id": "c"},
    )
    observation = evidence["observations"][0]
    tokens = {item["token"]: item["value"] for item in observation["fields"]}
    assert observation["identity"]["object_id"] == 44
    assert tokens["objInfo->trcOutData[i].distX"] == 5.0
    assert tokens["objInfo->trcOutData[i].objFctaWarningFlag"] == 4
    assert tokens["objInfo->trcOutData[i].rightFctaFlag"] is True
    assert tokens["objInfo->trcOutData[i].fInterX"] == 8.3
    assert "runtime_target_polygon" not in observation["geometry"]
    assert observation["geometry"]["runtime_roi"]["rightRoi"]["num"] == 4
    assert len(observation["geometry"]["runtime_roi"]["rightRoi"]["points"]) == 4


def test_runtime_normalizer_enriches_older_canonical_gdb_artifact():
    evidence = normalize_runtime_evidence({
        "schema_version": "runtime-case-evidence.v1",
        "status": "partial",
        "run": {"run_id": "canonical-gdb", "data_fingerprint": "d", "source_context_id": "c"},
        "evidence_layers": [],
        "observations": [{
            "layer": "gdb_observation",
            "identity": {"radar_id": 2, "frame_id": 100, "object_id": 44},
            "fields": [{
                "token": "objInfo->trcOutData[i]",
                "value": "{objID = 44, objFctaWarningFlag = 4, rightFctaFlag = true, fInterX = 8.3, fInterY = 0}",
                "status": "observed",
            }, {
                "token": "g_egoCarAddInfo.actual_gear",
                "value": "4 '\\\\004'",
                "status": "observed",
            }],
        }],
    })
    fields = {item["token"]: item["value"] for item in evidence["observations"][0]["fields"]}
    assert fields["objInfo->trcOutData[i].objFctaWarningFlag"] == 4
    assert fields["objInfo->trcOutData[i].rightFctaFlag"] is True
    assert fields["objInfo->trcOutData[i].fInterX"] == 8.3
    assert fields["g_egoCarAddInfo.actual_gear"] == 4
    gear_field = next(item for item in evidence["observations"][0]["fields"] if item["token"] == "g_egoCarAddInfo.actual_gear")
    assert gear_field["raw_value"] == "4 '\\\\004'"
    repeated = normalize_runtime_evidence(evidence)
    assert len(repeated["observations"][0]["fields"]) == len(evidence["observations"][0]["fields"])


def test_runtime_normalizer_records_runner_disturbance_metrics():
    evidence = normalize_runtime_evidence(
        {
            "schema_version": "gdb-session.v1",
            "target": {"radar_id": 2, "frame_id": 100},
            "commands": [],
            "stdout": "PLAY_RC=0\nGDB_HIT_COUNT=3\nWARNING_ROWS=6\nWARNING_NONZERO_COUNT=0\nError in sourced command file\n",
        },
        run={"run_id": "gdb-disturbance", "data_fingerprint": "d", "source_context_id": "c"},
    )
    assert evidence["disturbance"]["status"] == "suspected"
    assert evidence["disturbance"]["metrics"]["gdb_hit_count"] == 3
    assert evidence["disturbance"]["metrics"]["warning_nonzero_count"] == 0
    assert evidence["observations"][0]["disturbance"]["status"] == "suspected"


def test_runtime_normalizer_does_not_call_missing_gdb_symbol_replay_disturbance():
    evidence = normalize_runtime_evidence(
        {
            "schema_version": "gdb-session.v1",
            "target": {"radar_id": 2, "frame_id": 100},
            "commands": [],
            "stdout": (
                'CR60_GDB_EXPR token="macro_value" phase="during"\n'
                'CR60_GDB_ERROR token="macro_value" error=No symbol "macro_value" in current context.\n'
            ),
        },
        run={"run_id": "gdb-missing-symbol", "data_fingerprint": "d", "source_context_id": "c"},
    )
    assert evidence["disturbance"]["status"] == "not_evaluated"
    assert "disturbance was not established" in evidence["disturbance"]["reason"]


def test_runtime_normalizer_keeps_blocked_attach_as_attempt_without_observation():
    evidence = normalize_runtime_evidence(
        {
            "schema_version": "gdb-session.v1",
            "status": "blocked",
            "target": {
                "radar_id": 2,
                "frame_id": 100,
                "attach_status": "blocked",
                "attach_blocked_reason": "gdb_attach_failed",
                "source_context_id": "ctx-1",
                "bag": "/data/C1/a.bag",
            },
            "commands": ["continue"],
            "stdout": (
                "ATTACH_STATUS=blocked\nATTACH_BLOCKED_REASON=gdb_attach_failed\n"
                "Could not attach to process.\nptrace: Operation not permitted.\n"
            ),
        }
    )
    assert evidence["status"] == "blocked"
    assert evidence["observations"] == []
    assert evidence["attempts"][0]["status"] == "blocked"
    assert evidence["attempts"][0]["reason"] == "gdb_attach_failed"


def test_runtime_composite_does_not_poison_valid_evidence_with_blocked_attempt():
    valid = _evidence()
    blocked = normalize_runtime_evidence(
        {
            "schema_version": "gdb-session.v1",
            "status": "blocked",
            "target": {"radar_id": 2, "frame_id": 100, "attach_status": "blocked", "bag": "/data/C1/a.bag"},
            "stdout": "ATTACH_STATUS=blocked\nATTACH_BLOCKED_REASON=ptrace_scope\n",
        },
        run={"run_id": "blocked-run", "data_fingerprint": "data-1", "source_context_id": "ctx-1", "bag": "/data/C1/a.bag"},
    )
    combined = compose_runtime_evidence(valid, blocked)
    assert combined["status"] == "partial"
    assert len(combined["observations"]) == 1
    assert len(combined["attempts"]) == 1
    assert combined["run"]["run_id"] == "run-1"


def test_runtime_merge_is_additive_and_matches_same_radar_frame_object():
    bundle = _bundle()
    evidence = _evidence()
    merged = merge_runtime_evidence(bundle, evidence)
    assert merged["runtime_merge"]["status"] == "partial"  # no binary fingerprint in static bundle
    assert merged["runtime_merge"]["matched_observation_count"] == 1
    event = merged["alarm_events"][0]
    assert event["static_fact"] == "must-remain"
    assert event["runtime_overlay"]["observation_ids"] == ["hit-1"]
    assert merged["alarm_events"][0]["replay_plan"]["target_frame_id"] == 100
    assert validate_runtime_binding(bundle, evidence)["overlay_eligible"] is True


def test_runtime_merge_can_materialize_only_the_current_event_slice():
    bundle = _bundle()
    evidence = _evidence()
    extra = deepcopy(evidence["observations"][0])
    extra["observation_id"] = "outside-window"
    extra["identity"]["frame_id"] = 999
    evidence["observations"].append(extra)

    merged = merge_runtime_evidence(
        bundle,
        evidence,
        scope={"event_id": "event-1"},
    )
    runtime = merged["runtime_evidence"]
    assert [item["observation_id"] for item in runtime["observations"]] == ["hit-1"]
    assert merged["runtime_merge"]["scope"]["mode"] == "event_slice"
    assert merged["runtime_merge"]["scope"]["source_observation_count"] == 2
    assert merged["runtime_merge"]["scope"]["selected_observation_count"] == 1


def test_runtime_merge_does_not_fall_back_to_full_evidence_for_unknown_event_scope():
    merged = merge_runtime_evidence(
        _bundle(),
        _evidence(),
        scope={"event_id": "missing-event"},
    )
    assert merged["runtime_evidence"]["observations"] == []
    assert merged["runtime_merge"]["scope"]["selected_observation_count"] == 0
    assert "scope_event_not_found" in merged["runtime_merge"]["scope"]["diagnostics"]


def test_runtime_merge_preserves_multiple_producer_runs_and_observations():
    first = _evidence()
    second = deepcopy(first)
    second["run"]["run_id"] = "run-2"
    second["observations"][0]["observation_id"] = "hit-2"
    second["observations"][0]["fields"][1]["value"] = 6
    combined = compose_runtime_evidence(first, second)
    assert combined["run_count"] == 2
    assert {item["observation_id"] for item in combined["observations"]} == {"hit-1", "hit-2"}
    assert combined["producer"]["kind"] == "runtime-evidence-composite"
    field_comparisons = [item for item in combined["comparisons"] if item["status"] == "different"]
    assert any("objInfo->trcOutData[i].flag" in item["differences"][0]["token"] for item in field_comparisons)
    bundle = _bundle()
    bundle["runtime_evidence"] = first
    merged = merge_runtime_evidence(bundle, second)
    assert merged["runtime_evidence"]["run_count"] == 2
    assert {item["observation_id"] for item in merged["runtime_evidence"]["observations"]} == {"hit-1", "hit-2"}


def test_runtime_source_conflict_blocks_overlay():
    bundle = _bundle(context="ctx-static")
    evidence = _evidence(context="ctx-runtime")
    merged = merge_runtime_evidence(bundle, evidence)
    assert merged["runtime_merge"]["status"] == "blocked"
    assert merged["runtime_merge"]["matched_observation_count"] == 1
    assert merged["alarm_events"][0]["runtime_overlay"]["status"] == "blocked"
    assert merged["alarm_events"][0]["runtime_overlay"]["observation_ids"] == []
    # The identity match is retained for audit, but the event reference is
    # empty so downstream cannot treat conflicting facts as valid overlay.
    assert "binding_conflict:source_context_id" in merged["runtime_merge"]["diagnostics"]


def test_runtime_missing_required_identity_is_not_consumable_overlay():
    bundle = _bundle()
    evidence = _evidence()
    evidence["run"]["source_context_id"] = ""
    evidence["run"].pop("bag")
    merged = merge_runtime_evidence(bundle, evidence)
    assert merged["runtime_merge"]["status"] == "blocked"
    assert merged["runtime_merge"]["binding"]["overlay_eligible"] is False
    assert merged["alarm_events"][0]["runtime_overlay"]["status"] == "blocked"
    assert merged["alarm_events"][0]["runtime_overlay"]["observation_ids"] == []


def test_runtime_modules_are_pi_registered_and_cli_callable(tmp_path):
    assert MODULE_REGISTRY["runtime-evidence-normalize"] is RuntimeEvidenceNormalizeModule
    assert MODULE_REGISTRY["runtime-evidence-validate"] is RuntimeEvidenceValidateModule
    assert MODULE_REGISTRY["runtime-evidence-compose"] is RuntimeEvidenceComposeModule
    assert MODULE_REGISTRY["runtime-evidence-merge"] is RuntimeEvidenceMergeModule
    catalog = {item["name"]: item for item in capability_catalog()}
    assert catalog["runtime-evidence-normalize"]["expose_to_pi"] is True
    assert "atomic" in catalog["runtime-evidence-merge"]["tags"]
    assert catalog["runtime-evidence-compose"]["expose_to_pi"] is True

    evidence_path = tmp_path / "runtime.json"
    result = RuntimeEvidenceNormalizeModule().safe_run(
        transcript="CR60_RUNTIME observation_id=x frame_id=100 radar_id=2 field_token=i field_value=0",
        run={"run_id": "r", "data_fingerprint": "d", "source_context_id": "c"},
        output=str(evidence_path),
    )
    assert result.ok is True
    assert json.loads(evidence_path.read_text(encoding="utf-8"))["schema_version"] == "runtime-case-evidence.v1"

    public_result = RuntimeEvidenceNormalizeModule().safe_run(
        public_runtime_snapshot={
            "schema_version": "runtime-snapshot-with-frame.v1",
            "status": "ready",
            "source_context": {"source_snapshot_hash": "s"},
            "snapshots": [{
                "radar_id": 1,
                "frame_id": 1,
                "warning": {
                    "source": "warning_status_with_frame",
                    "data": [1, 1] + [0] * 15,
                    "warnings": [0] * 15,
                },
            }],
            "unbound_objects": [],
            "diagnostics": [],
        },
        run={"run_id": "public", "data_fingerprint": "d", "source_context_id": "c"},
    )
    assert public_result.ok is True
    assert public_result.data["schema_version"] == "runtime-case-evidence.v1"


def test_runtime_evidence_compose_module_keeps_public_and_gdb_producers(tmp_path):
    left_path = tmp_path / "public.json"
    right_path = tmp_path / "gdb.json"
    output = tmp_path / "combined.json"
    left_path.write_text(json.dumps(_evidence()), encoding="utf-8")
    right = deepcopy(_evidence())
    right["run"]["run_id"] = "run-2"
    right["observations"][0]["observation_id"] = "hit-2"
    right_path.write_text(json.dumps(right), encoding="utf-8")

    result = RuntimeEvidenceComposeModule().safe_run(
        left_path=str(left_path), right_path=str(right_path), output=str(output)
    )
    assert result.ok
    assert output.exists()
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["run_count"] == 2
    assert {item["observation_id"] for item in payload["observations"]} == {"hit-1", "hit-2"}
