# -*- coding: utf-8 -*-
from __future__ import annotations

from engines.diagnostic_report import _condition_facts_from_event, _detect_can_data_status, _source_snapshot_hash


def test_source_snapshot_precedes_legacy_index_hash():
    value = {
        "provenance": {"source_index_hash": "legacy-index"},
        "source_context": {"source_snapshot_hash": "current-source"},
    }
    assert _source_snapshot_hash(value) == "current-source"


def test_index_hash_remains_fallback_for_legacy_artifact():
    value = {"provenance": {"source_index_hash": "legacy-index"}}
    assert _source_snapshot_hash(value) == "legacy-index"


def test_unlocated_gdb_locals_are_not_condition_bindings():
    values, _ = _condition_facts_from_event({
        "summary": {"first_frame": {"frame_id": 100}},
        "runtime_association": "exact_event_or_frame",
        "runtime_observations": [{
            "layer": "gdb_observation",
            "identity": {"frame_id": 100},
            "fields": [
                {"token": "rightFctaWarningNum", "value": 0, "status": "observed", "scope": "locals"},
                {"token": "fTTMX", "value": 1.0, "status": "observed", "scope": ""},
            ],
        }],
    })
    assert "rightFctaWarningNum" not in values
    assert values["fTTMX"]["value"] == 1.0


def test_can_endpoint_is_not_required_without_can_inventory():
    assert _detect_can_data_status(
        {"data_quality": {"camera_topics": {"/camera": {"message_count": 1}}}},
        {"observations": []},
    ) == "not_detected"


def test_can_endpoint_is_enabled_when_runtime_can_layer_is_present():
    assert _detect_can_data_status(
        {},
        {"observations": [{"layer": "can_tx_observation"}]},
    ) == "present"
