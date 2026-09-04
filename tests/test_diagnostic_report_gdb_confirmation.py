# -*- coding: utf-8 -*-
from engines.diagnostic_report import _gdb_confirmation


def test_gdb_confirmation_requires_matching_frame_radar_and_object():
    selected = {
        "summary": {
            "first_frame": {"frame_id": 47877},
            "radar_id": 2,
            "target_obj_id": 44,
            "function": "PROJECT_WARN_R",
        },
        "runtime_observations": [{
            "layer": "gdb_observation",
            "identity": {
                "frame_id": 47877,
                "radar_id": 2,
                "object_id": 44,
                "source_location": {"file": "feature.c", "line": 100},
            },
            "fields": [{"token": "frameID", "value": 47877, "status": "observed"},
                       {"token": "objInfo->trcOutData[i].objID", "value": 44, "status": "observed"},
                       {"token": "adasWarning->bRightWarning", "value": 2, "status": "observed"}],
        }],
    }
    runtime = {
        "evidence_layers": [{"id": "gdb_observation", "status": "observed"}],
        "artifacts": {"gdb_transcript": "gdb.log"},
        "run": {"run_id": "gdb-run"},
        "diagnostics": ["gdb_expression_not_observed"],
    }
    result = _gdb_confirmation(runtime, selected, {"status": "succeeded"})
    assert result["status"] == "confirmed"
    assert result["actual_hit"] is True
    assert result["session_status"] == "succeeded"
    assert result["runner_status_verified"] is True
    assert result["source_location"]["line"] == 100
    assert {item["token"] for item in result["captured_fields"]} == {
        "frameID", "objInfo->trcOutData[i].objID", "adasWarning->bRightWarning",
    }


def test_gdb_confirmation_does_not_accept_mismatched_identity():
    selected = {
        "summary": {"first_frame": {"frame_id": 47877}, "radar_id": 2, "target_obj_id": 44},
        "runtime_observations": [{
            "layer": "gdb_observation",
            "identity": {"frame_id": 47876, "radar_id": 2, "object_id": 44},
            "fields": [{"token": "frameID", "value": 47876, "status": "observed"}],
        }],
    }
    runtime = {
        "evidence_layers": [{"id": "gdb_observation", "status": "observed"}],
        "artifacts": {"gdb_transcript": "gdb.log"},
    }
    result = _gdb_confirmation(runtime, selected)
    assert result["actual_hit"] is False
    assert result["status"] == "partial"
