# -*- coding: utf-8 -*-
from __future__ import annotations

from engines.evidence_query import _bound_field_list, build_evidence_query


def _event() -> dict:
    return {
        "event_id": "evt-1",
        "function": "FCTA_R",
        "radar_id": 2,
        "frame_precheck": {"alarm_first_frame_id": 100},
        "details": {"feature": {"entry_function": "FrontCrossTrafficAlertAndBrake"}},
        "target": {"selected": {"obj_id": 44}},
    }


def test_runtime_join_keeps_source_entry_gdb_and_selected_public_object():
    runtime = {
        "observations": [
            {
                "observation_id": "public-frame",
                "layer": "runtime_with_frame",
                "identity": {"radar_id": 2, "frame_id": 100},
                "fields": [],
            },
            {
                "observation_id": "public-other-object",
                "layer": "objectlist_candidate",
                "identity": {"radar_id": 2, "frame_id": 100, "object_id": 7},
                "fields": [],
            },
            {
                "observation_id": "public-selected-object",
                "layer": "objectlist_candidate",
                "identity": {"radar_id": 2, "frame_id": 100, "object_id": 44},
                "fields": [{"token": "objID", "value": 44}],
            },
            {
                "observation_id": "gdb-source-entry",
                "layer": "gdb_observation",
                "identity": {
                    "radar_id": 2,
                    "frame_id": 100,
                    "object_id": 44,
                    "function": "FrontCrossTrafficAlertAndBrake",
                },
                "fields": [{"token": "fTTMX", "value": 1.0}],
            },
        ],
    }
    result = build_evidence_query(
        bundle={"alarm_events": [_event()]},
        viewer_model={"events": [_event()]},
        runtime_evidence=runtime,
        function="FCTA",
        side="R",
        radar_id=2,
        frame_id=100,
        max_events=1,
        max_frames=3,
        max_targets=4,
        include_details=True,
    )
    rows = result["events"][0]["runtime_observations"]
    ids = {row["observation_id"] for row in rows}
    assert "gdb-source-entry" in ids
    assert "public-selected-object" in ids
    assert "public-frame" in ids
    assert result["events"][0]["runtime_association"] == "exact_event_or_frame_truncated"


def test_bounded_runtime_fields_keep_numeric_prediction_over_pointer_or_missing_token():
    rows = [
        {"token": "frameID", "value": 47877, "status": "observed"},
        {"token": "fInterX", "value": "", "status": "not_found"},
        {"token": "fInterX", "value": "0x7fffffffcb08", "status": "observed"},
    ]
    rows.extend({"token": f"noise_{index}", "value": index, "status": "observed"} for index in range(400))
    rows.extend([
        {"token": "fInterX", "value": 8.38272381, "status": "observed"},
        {"token": "fInterY", "value": 0.0, "status": "observed"},
        {"token": "fTTMY", "value": 0.564559579, "status": "observed"},
    ])

    bounded = _bound_field_list(rows, 256)
    numeric_x = [row for row in bounded if row.get("token") == "fInterX" and isinstance(row.get("value"), (int, float))]
    assert numeric_x
    assert numeric_x[-1]["value"] == 8.38272381
