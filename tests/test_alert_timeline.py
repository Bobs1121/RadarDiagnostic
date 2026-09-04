from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from ai.modules import MODULE_REGISTRY
from ai.modules.alert_timeline import AlertTimelineModule
from engines.alert_timeline import build_alert_timeline
from engines.diagnostic_report import build_diagnostic_report


def _bundle() -> dict:
    return {
        "schema_version": "diagnosis-bundle.v1",
        "data_fingerprint": "data-1",
        "case": {"case_id": "CASE-1", "bag": "/data/demo.bag"},
        "provenance": {"source_context_id": "source-1"},
        "alarm_events": [
            {
                "event_id": "event-a",
                "function": "FUNC_A_L",
                "radar_id": 3,
                "source": "recorded_raw",
                "start_time_sec": 1.0,
                "first_on_frame": 100,
                "selected_target": {"obj_id": 44, "raw_sgu_index": 0, "algorithm_object_index": 1, "objectlist_index": 2},
            }
        ],
    }


def _viewer() -> dict:
    return {
        "schema_version": "viewer-model.v1",
        "events": [
            {
                "event_id": "event-a",
                "identity": {"function": "FUNC_A_L", "side": "L", "radar_id": 3},
                "frame": {"target_frame": 100, "target_frame_source": "wfAutosarData.frameID", "selection_confidence": "observed"},
                "timeline": {
                    "frames": [
                        {"frame_id": 99, "frame_id_source": "wfAutosarData.frameID", "timestamp_sec": 0.9},
                        {"frame_id": 100, "frame_id_source": "wfAutosarData.frameID", "timestamp_sec": 1.0},
                    ]
                },
            }
        ],
    }


def _runtime() -> dict:
    return {
        "schema_version": "runtime-case-evidence.v1",
        "run": {"run_id": "r1", "data_fingerprint": "data-1", "source_context_id": "source-1"},
        "evidence_layers": [],
        "observations": [],
        "warning_rising_edges": [
            {"signal_name": "FUNC_A_L", "radar_id": 3, "frame_id": 100, "frame_status": "frame_verified", "value": 1}
        ],
    }


def test_alert_timeline_keeps_layer_identity_and_compares_exact_frames():
    payload = build_alert_timeline(
        bundle=_bundle(), viewer_model=_viewer(), runtime_evidence=_runtime(), event_id="event-a"
    )
    assert payload["schema_version"] == "alert-timeline.v1"
    assert {row["layer"] for row in payload["rows"]} == {"recorded_raw", "runtime_with_frame"}
    assert any(row["frame_status"] == "observed" and row["frame_id"] == 100 for row in payload["rows"])
    compare = next(item for item in payload["comparisons"] if item["right"] == "runtime_with_frame" and item["left"] == "recorded_raw")
    assert compare["status"] == "same"
    assert [item["state"] for item in payload["playback_frame_map"]] == ["context", "selected_analysis_frame"]
    Draft202012Validator(
        json.loads(Path("contracts/alert-timeline.v1.schema.json").read_text(encoding="utf-8"))
    ).validate(payload)


def test_alert_timeline_does_not_claim_missing_replay_or_can():
    payload = build_alert_timeline(bundle=_bundle(), viewer_model=_viewer(), event_id="event-a")
    states = {item["layer"]: item["status"] for item in payload["sources"]}
    assert states["recorded_raw"] in {"observed", "derived"}
    assert states["replay_algorithm"] == "not_available"
    assert states["can_tx_observation"] == "not_available"
    assert all(item["status"] == "not_evaluated" for item in payload["comparisons"] if item["right"] == "replay_algorithm" or item["right"] == "can_tx_observation")


def test_alert_timeline_blocks_runtime_identity_conflict():
    runtime = _runtime()
    runtime["run"]["source_context_id"] = "different-source"
    payload = build_alert_timeline(bundle=_bundle(), runtime_evidence=runtime, event_id="event-a")
    assert payload["status"] == "blocked"
    assert payload["conflicts"][0]["field"] == "source_context_id"


def test_alert_timeline_does_not_call_different_target_identity_same():
    runtime = _runtime()
    runtime["warning_rising_edges"][0]["obj_id"] = 99
    runtime["warning_rising_edges"][0]["algorithm_object_index"] = 4
    payload = build_alert_timeline(
        bundle=_bundle(), runtime_evidence=runtime, event_id="event-a"
    )
    compare = next(item for item in payload["comparisons"] if item["right"] == "runtime_with_frame")
    assert compare["status"] == "different"
    assert any(item["kind"] == "target_identity" for item in compare["differences"])


def test_alert_timeline_consumes_local_replay_result_shape():
    replay = {
        "schema_version": "arbe-replay-result.v1",
        "status": "ready",
        "mode": "local",
        "trace": [{
            "event_sec": 1.0,
            "radar_id": 3,
            "frame_id": 100,
            "frame_id_source": "replay_trace.frame_id",
            "warnings": {"FUNC_A_L": True},
        }],
        "warning_mapping_source": "explicit_names",
    }
    payload = build_alert_timeline(bundle=_bundle(), runtime_evidence=replay, event_id="event-a")
    assert any(row["layer"] == "replay_algorithm" and row["function"] == "FUNC_A_L" for row in payload["rows"])


def test_alert_timeline_marks_rising_only_after_an_explicit_zero():
    replay = {
        "schema_version": "arbe-replay-result.v1",
        "status": "ready",
        "mode": "local",
        "trace": [
            {"radar_id": 3, "frame_id": 99, "frame_id_source": "replay_trace.frame_id", "warnings": {"FUNC_A_L": False}},
            {"radar_id": 3, "frame_id": 100, "frame_id_source": "replay_trace.frame_id", "warnings": {"FUNC_A_L": True}},
        ],
        "warning_mapping_source": "explicit_names",
    }
    payload = build_alert_timeline(bundle=_bundle(), runtime_evidence=replay, event_id="event-a")
    rows = [row for row in payload["rows"] if row["layer"] == "replay_algorithm"]
    assert [row["transition"] for row in rows] == ["inactive", "rising"]


def test_alert_timeline_is_pi_visible_and_report_projects_conclusion():
    assert MODULE_REGISTRY["alert-timeline"] is AlertTimelineModule
    result = AlertTimelineModule().safe_run(bundle=_bundle(), event_id="event-a")
    assert result.ok
    report = build_diagnostic_report(bundle=_bundle(), viewer_model=_viewer(), event_id="event-a")
    assert report["alert_timeline"]["schema_version"] == "alert-timeline.v1"
    assert report["conclusion"]["level"] == "facts_only"
    assert report["conclusion"]["status"] == "partial"
