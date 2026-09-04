# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from engines.diagnostic_report import _geometry_projection, _parameter_table_html, _scene_svg


def test_geometry_projection_explains_roi_gate_and_draws_predicted_intersection(tmp_path: Path):
    source = tmp_path / "adas.c"
    source.write_text(
        "\n".join([
            "void F(void) {",
            "    if (rightFctaRoi->num > 0U) {",
            "        rightFlag = true;",
            "    }",
            "}",
        ]),
        encoding="utf-8",
    )
    selected = {
        "summary": {"function": "FCTA_R", "side": "R", "first_frame": {"frame_id": 100}},
        "details": {
            "target": {"obj_id": 44, "geometry": {"polygon": [
                {"x": 6, "y": -3}, {"x": 5, "y": -3},
                {"x": 5, "y": -2}, {"x": 6, "y": -2},
            ]}},
        },
        "runtime_observations": [{
            "observation_id": "gdb-1",
            "layer": "gdb_observation",
            "identity": {"frame_id": 100, "object_id": 44},
            "fields": [
                {"token": "fInterX", "value": 8.0, "status": "observed"},
                {"token": "fInterY", "value": 0.0, "status": "observed"},
                {"token": "fTTMY", "value": 0.5, "status": "observed"},
            ],
            "geometry": {
                "runtime_target_polygon": [
                    [6, -3], [5, -3], [5, -2], [6, -2],
                ],
                "runtime_roi": {
                    "rightRoi": {"num": 10, "points": [
                        [3, 0], [9, 0], [9, -1], [3, -1],
                    ]},
                },
            },
        }],
    }
    trace = {
        "conditions": [{
            "condition_id": "condition-1",
            "expression": "rightFctaRoi->num > 0U",
            "source_ref": {"file_path": "adas.c", "line": 2},
            "evaluation": {"status": "satisfied", "value": True},
        }],
    }
    projection = _geometry_projection(
        selected,
        condition_trace=trace,
        source_root=str(tmp_path),
    )
    assert projection["collision_status"] == "observed_disjoint"
    assert projection["predicted_intersection"]["x"] == 8.0
    assert projection["predicted_intersection"]["roi_relations"][0]["relation"] == "on_or_inside"
    assert projection["algorithm_branch"]["flag_token"] == "rightFlag"
    assert projection["algorithm_branch"]["source_assignment"]["line"] == 3

    html = _scene_svg({"selected_event": selected, "geometry_projection": projection})
    assert "predicted fInterX=8, fInterY=0" in html
    assert "instantaneous: observed_disjoint" in html


def test_geometry_prediction_token_names_come_from_runtime_evidence():
    selected = {
        "summary": {"function": "CUSTOM_R", "side": "R", "first_frame": {"frame_id": 100}},
        "details": {"target": {"obj_id": 7, "geometry": {"polygon": [
            {"x": 6, "y": -3}, {"x": 5, "y": -3}, {"x": 5, "y": -2}, {"x": 6, "y": -2},
        ]}}},
        "runtime_observations": [{
            "observation_id": "custom-runtime",
            "layer": "gdb_observation",
            "identity": {"frame_id": 100, "object_id": 7},
            "fields": [
                {"token": "intersection_x", "value": 8.0, "status": "observed"},
                {"token": "intersection_y", "value": 0.0, "status": "observed"},
                {"token": "time_to_cross", "value": 0.8, "status": "observed"},
            ],
            "geometry": {
                "runtime_target_polygon": [[6, -3], [5, -3], [5, -2], [6, -2]],
                "runtime_roi": {"rightRoi": {"num": 4, "points": [[3, 0], [9, 0], [9, -1], [3, -1]]}},
            },
        }],
    }
    projection = _geometry_projection(selected)
    prediction = projection["predicted_intersection"]
    assert prediction["x_token"] == "intersection_x"
    assert prediction["y_token"] == "intersection_y"
    assert prediction["time_token"] == "time_to_cross"
    assert prediction["time"] == 0.8


def test_parameter_table_keeps_input_source_and_runtime_layers_separate():
    report = {
        "selected_event": {"summary": {"first_frame": {"frame_id": 100}}},
        "diagnostic_narrative": {
            "operating_condition": {
                "ego": [{"token": "ego.speed", "value": 4.4, "unit": "m/s", "status": "observed_in_bag", "source": {"topic": "/ego", "frame_id": 100}}],
                "target": [{"token": "obj.id", "value": 44, "status": "observed_runtime_input", "source": {"topic": "/objects", "frame_id": 100}}],
            },
            "condition_items": [{
                "source_ref": {"file_path": "feature.c", "line": 22},
                "bindings": [{"token": "warning_threshold", "value": 2.0, "status": "bound"}],
            }],
            "runtime_facts": [{"token": "fTTM", "value": 0.5, "status": "observed", "layer": "gdb_observation", "frame_id": 100, "source": {"kind": "gdb_expression"}}],
        },
        "geometry_projection": {},
    }
    rendered = _parameter_table_html(report)
    assert "ego.speed" in rendered
    assert "warning_threshold" in rendered
    assert "fTTM" in rendered
    assert "parameter-scroll" in rendered
    assert "observed_in_bag" in rendered
    assert "bound" in rendered
