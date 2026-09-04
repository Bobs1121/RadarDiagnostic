# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path

from ai.capability.registry import capability_catalog
from ai.modules import MODULE_REGISTRY
from ai.modules.base import ModuleResult
from ai.modules.public_evidence_audit import PublicEvidenceAuditModule
from ai.modules.public_topic_plan import PublicTopicPlanModule
from engines.arbe.public_evidence import audit_public_bundle, build_public_topic_plan


def _profile() -> dict:
    return {
        "arbe": {
            "lgu_topic_pattern": "/wf/corner_radar/lgu_data_{radar_id}",
            "object_topic_pattern": "/wf/objectlist_{radar_id}",
            "warning_topic": "/corner_radar/warning_status",
            "warning_with_frame_topic": "/corner_radar/warning_status_with_frame",
            "raw_warning_topic": "/corner_radar/warning_status_raw",
            "radar1": {"side": "left"},
            "radar2": {"side": "right"},
        }
    }


def test_public_topic_plan_keeps_frame_and_display_guarantees_separate():
    payload = build_public_topic_plan(
        profile=_profile(),
        topic_inventory={
            "topics": [
                {
                    "topic": "/wf/objectlist_2",
                    "type": "arbe_msgs/wfObjectMsg",
                    "publisher_count": 1,
                    "subscriber_count": 1,
                    "data_observable": True,
                    "status": "ready",
                }
            ]
        },
    )
    assert payload["schema_version"] == "public-topic-plan.v1"
    assert payload["status"] == "ready"
    lgu = next(item for item in payload["channels"] if item["channel_id"] == "lgu_input")
    objects = next(item for item in payload["channels"] if item["channel_id"] == "algorithm_object_display")
    assert lgu["frame_key"] == "wfAutosarData.frameID"
    assert lgu["gdb_required"] is False
    assert objects["frame_key"] == "not_in_message"
    object_2 = next(item for item in payload["channels"] if item["channel_id"] == "algorithm_object_display_2")
    assert object_2["runtime_observation"]["data_observable"] is True
    lgu_2 = next(item for item in payload["channels"] if item["channel_id"] == "lgu_input_2")
    assert lgu_2["topic"] == "/wf/corner_radar/lgu_data_2"
    assert any("i" in item for item in lgu["notes"])


def test_public_bundle_audit_reports_no_gdb_fields_and_preserves_source():
    bundle = {
        "case": {"case_id": "case-1"},
        "source_context": {"source_context_id": "ctx"},
        "recorded_warning": {
            "topics": {
                "raw": {"topic": "/corner_radar/warning_status_raw", "present": True},
                "with_frame": {"topic": "/corner_radar/warning_status_with_frame", "present": False},
            }
        },
        "alarm_events": [
            {
                "frame_evidence": [
                    {
                        "frame_id": 47877,
                        "frame_id_source": "wfAutosarData.frameID",
                        "ego": {"actual_spd": 0.2, "actual_gear": 4},
                        "objects": [
                            {
                                "source_layer": "raw_sgu_input",
                                "raw_sgu_index": 2,
                                "algorithm_object_index": 0,
                                "obj_id": 44,
                                "distX": 5.0,
                            }
                        ],
                    }
                ]
            }
        ],
        "decoder_contract": {"name": "active-layout"},
        "evidence_gaps": ["g_egoCarAddInfo requires runtime probe"],
    }
    payload = audit_public_bundle(bundle)
    assert payload["status"] == "ready"
    assert payload["frame_evidence"]["exact_frame_available"] is True
    assert payload["ego_evidence"]["fields_observed"] == ["actual_gear", "actual_spd"]
    assert "raw_sgu_index" in payload["object_evidence"]["index_tokens"]
    assert payload["warning_evidence"]["can_tx_observed"] is False
    assert payload["source_context"]["source_context_id"] == "ctx"


def test_public_modules_are_registered_and_write_audit_artifact(tmp_path: Path):
    assert MODULE_REGISTRY["public-topic-plan"] is PublicTopicPlanModule
    assert MODULE_REGISTRY["public-evidence-audit"] is PublicEvidenceAuditModule
    plan_output = tmp_path / "public_plan.json"
    result = PublicTopicPlanModule().safe_run(output=str(plan_output))
    assert isinstance(result, ModuleResult)
    assert result.ok is False  # no profile means no configured channels
    assert plan_output.exists()
    assert json.loads(plan_output.read_text(encoding="utf-8"))["status"] == "blocked"


def test_public_capabilities_expose_atomic_tags_and_schemas():
    catalog = {item["name"]: item for item in capability_catalog()}
    assert "atomic" in catalog["public-topic-plan"]["tags"]
    assert catalog["public-evidence-audit"]["parameters"]["required"] == ["bundle_path"]
