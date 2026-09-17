# -*- coding: utf-8 -*-
from __future__ import annotations

from engines.diagnostic_report import _condition_facts_from_event, _detect_can_data_status, _source_snapshot_hash, build_diagnostic_report, write_diagnostic_report


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


def test_diagnostic_report_keeps_perception_analysis_as_additive_layer():
    report = build_diagnostic_report(
        bundle={"schema_version": "diagnosis_bundle.v1", "events": []},
        perception_analysis={
            "schema_version": "perception-analysis.v1",
            "status": "partial",
            "conclusion_level": "facts_only",
            "input_contract": {"point_count": 1},
            "stage_coverage": {"available_stage_count": 0, "total_stage_count": 8, "stages": []},
            "lineage": {"status": "not_available", "edge_count": 0},
            "gaps": [{"id": "perception_stage_evidence_partial"}],
        },
    )
    assert report["perception_analysis"]["status"] == "partial"
    assert any(layer["layer"] == "perception" for layer in report["evidence_layers"])


def test_diagnostic_report_projects_perception_scene_and_timeline_in_html(tmp_path):
    report = build_diagnostic_report(
        bundle={"schema_version": "diagnosis_bundle.v1", "events": []},
        perception_analysis={
            "schema_version": "perception-analysis.v1",
            "status": "partial",
            "conclusion_level": "facts_only",
            "input_contract": {"point_count": 1},
            "stage_coverage": {"available_stage_count": 1, "total_stage_count": 8, "stages": []},
            "lineage": {"status": "not_available", "edge_count": 0},
            "scene": {"schema_version": "perception-scene.v1", "status": "observed", "selected_frame": "10", "counts": {"points": 1, "clusters": 0, "tracks": 1, "outputs": 0}},
            "timeline": {"schema_version": "perception-timeline.v1", "status": "observed", "rows": [{"frame_key": "10", "stages": [{"stage": "track"}], "track_ids": ["t1"], "output_ids": []}]},
            "gaps": [],
        },
    )
    paths = write_diagnostic_report(report, tmp_path)
    html = (tmp_path / "diagnostic-report.html").read_text(encoding="utf-8")
    assert "selected frame" in html
    assert "Exact-frame perception timeline" in html
    assert paths


def test_diagnostic_report_keeps_unbound_runtime_snapshot_as_partial_layer():
    snapshot = {
        "schema_version": "runtime-snapshot-with-frame.v1",
        "status": "partial",
        "capture_metadata": {
            "identity_binding": {"status": "not_bound"},
            "inventory_sha256": "inventory-sha",
            "topic_samples": [{
                "topic": "/wf/objectlist_2",
                "message_schema_status": "ready",
                "message_definition_sha256": "definition-sha",
                "object_field_catalog": [
                    {"token": "objID", "type": "uint32", "source_path": "arbe_msgs/wfSObj.objID"}
                ],
            }],
        },
        "snapshots": [],
        "unbound_objects": [{
            "association_status": "unbound",
            "radar_id": 2,
            "frame_id": None,
            "fields": {
                "objID": 44,
                "topic": "/wf/objectlist_2",
                "source_ref": {"topic": "/wf/objectlist_2", "sample_sha256": "sample-sha"},
            },
        }],
        "association_policy": {"time_neighbour_matching": False},
        "diagnostics": ["objectlist_rows_without_frame_or_callback_remain_unbound"],
    }
    report = build_diagnostic_report(
        bundle={"schema_version": "diagnosis_bundle.v1", "events": []},
        runtime_snapshot=snapshot,
        radar_id=2,
    )
    assert report["runtime_snapshot_rows"]
    assert report["runtime_snapshot_rows"][0]["association_status"] == "unbound"
    assert report["overview"]["runtime_snapshot_status"] == "partial"
    assert report["status"] == "partial"
    assert any(layer["layer"] == "runtime_snapshot" and layer["status"] == "partial" for layer in report["evidence_layers"])
    assert "runtime_snapshot_identity_not_bound" in report["diagnostics"]
    action_ids = {item.get("id") for item in report["next_actions"]}
    assert "snapshot-source-navigation" in action_ids
    assert "snapshot-debug-experiment" in action_ids
    navigation = next(item for item in report["next_actions"] if item.get("id") == "snapshot-source-navigation")
    assert navigation["target"]["radar_ids"] == ["2"]
    assert navigation["target"]["association_statuses"] == ["unbound"]
    assert navigation["handoff_status"] == "requires_event_and_source_binding"


def test_diagnostic_report_html_shows_independent_objectlist_snapshot(tmp_path):
    snapshot = {
        "schema_version": "runtime-snapshot-with-frame.v1",
        "status": "partial",
        "capture_metadata": {"identity_binding": {"status": "not_bound"}},
        "snapshots": [],
        "unbound_objects": [{
            "association_status": "unbound",
            "radar_id": 2,
            "frame_id": None,
            "topic": "/wf/objectlist_2",
            "field_rows": [{"token": "objID", "value": 44, "status": "observed"}],
            "sample_observed_at_utc": "2026-09-15T06:20:01Z",
        }],
        "association_policy": {"time_neighbour_matching": False},
    }
    report = build_diagnostic_report(
        bundle={"schema_version": "diagnosis_bundle.v1", "events": []},
        runtime_snapshot=snapshot,
    )
    paths = write_diagnostic_report(report, tmp_path)
    html = (tmp_path / "diagnostic-report.html").read_text(encoding="utf-8")
    markdown = (tmp_path / "diagnostic-report.md").read_text(encoding="utf-8")
    assert "Independent ObjectList snapshot" in html
    assert "独立 ObjectList snapshot" in html
    assert "Independent ObjectList snapshot" in markdown
    assert paths


def test_diagnostic_report_html_shows_feedback_review_as_separate_layer(tmp_path):
    report = build_diagnostic_report(
        bundle={"schema_version": "diagnosis_bundle.v1", "events": []},
        feedback_review={
            "schema_version": "feedback-review.v1",
            "status": "ready",
            "run_id": "run-feedback",
            "counts": {"feedback_confirmed": 1, "feedback_rejected": 0, "feedback_irrelevant": 0},
            "feedback": [{"kind": "feedback_confirmed", "summary": "用户确认正报"}],
            "conflicts": [],
            "diagnostics": [],
            "knowledge_publish_gate": {"status": "approval_required", "writes_knowledge": False},
        },
    )
    write_diagnostic_report(report, tmp_path)
    html = (tmp_path / "diagnostic-report.html").read_text(encoding="utf-8")
    markdown = (tmp_path / "diagnostic-report.md").read_text(encoding="utf-8")
    assert "Feedback review" in html
    assert "knowledge publish gate" in html
    assert "Feedback review" in markdown
    assert "用户反馈是独立 evidence layer" in html
