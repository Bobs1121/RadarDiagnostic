from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from engines.diagnostic_narrative import build_diagnostic_narrative


def _event() -> dict:
    return {
        "event_id": "event-a",
        "summary": {
            "function": "PROJECT_WARN_L",
            "side": "L",
            "radar_id": 1,
            "target_obj_id": 44,
            "target_index": {"raw_sgu_index": 0, "algorithm_object_index": 2},
            "first_frame": {"frame_id": 100, "confidence": "selected_frame_not_alarm_edge"},
        },
    }


def _timeline() -> dict:
    return {
        "sources": [
            {"layer": "recorded_raw", "status": "derived"},
            {"layer": "replay_algorithm", "status": "not_available"},
            {"layer": "runtime_with_frame", "status": "not_available"},
            {"layer": "gdb_observation", "status": "not_available"},
            {"layer": "can_tx_observation", "status": "not_available"},
        ],
        "rows": [{"layer": "recorded_raw", "function": "PROJECT_WARN_L", "side": "L", "radar_id": 1, "frame_id": 100, "frame_status": "derived", "transition": "rising_candidate", "value": 1}],
    }


def test_narrative_keeps_raw_only_alarm_indeterminate_and_explains_missing_runtime():
    result = build_diagnostic_narrative(
        selected_event=_event(),
        condition_trace={
            "conditions": [{"condition_id": "c1", "function": "Project", "expression": "if (flag > 0)", "source_ref": {"file_path": "project.c", "line": 8}, "missing_tokens": ["flag"], "evaluation": {"status": "not_evaluable", "reason": "missing tokens: flag"}}],
            "summary": {"total": 1, "satisfied": 0, "not_satisfied": 0, "not_evaluable": 1, "unsupported": 0},
        },
        alert_timeline=_timeline(),
    )
    assert result["alarm_assessment"]["should_alert"] == "indeterminate"
    assert any("暂不能判断" in line for line in result["narrative"])
    Draft202012Validator(
        json.loads(Path("contracts/diagnostic-narrative.v1.schema.json").read_text(encoding="utf-8"))
    ).validate(result)


def test_narrative_can_report_observed_can_tx_without_calling_it_a_code_proof():
    timeline = _timeline()
    timeline["sources"][-1]["status"] = "observed"
    timeline["rows"].append({
        "layer": "can_tx_observation", "function": "PROJECT_WARN_L", "side": "L", "radar_id": 1,
        "frame_id": 100, "frame_status": "observed", "transition": "rising", "value": 1,
    })
    result = build_diagnostic_narrative(
        selected_event=_event(),
        condition_trace={"summary": {"total": 0}},
        alert_timeline=timeline,
        output_endpoint="can_tx",
    )
    assert result["alarm_assessment"]["should_alert"] == "yes_observed"
    assert result["alarm_assessment"]["can_tx_observed"] is True
    assert result["alarm_assessment"]["can_tx_rising_frames"] == [100]


def test_narrative_uses_algorithm_output_when_can_is_not_detected():
    timeline = _timeline()
    timeline["sources"][1]["status"] = "observed"
    timeline["sources"][2]["status"] = "observed"
    timeline["rows"].append({
        "layer": "runtime_with_frame", "function": "PROJECT_WARN_L", "side": "L", "radar_id": 1,
        "frame_id": 100, "frame_status": "observed", "transition": "rising", "value": 1,
    })
    result = build_diagnostic_narrative(
        selected_event=_event(),
        condition_trace={"summary": {"total": 0}},
        alert_timeline=timeline,
        can_data_status="absent",
    )
    assert result["output_policy"]["effective_endpoint"] == "algorithm"
    assert result["output_policy"]["can_required"] is False
    assert result["alarm_assessment"]["should_alert"] == "yes_observed"
    assert result["alarm_assessment"]["algorithm_output_is_terminal"] is True
    assert any("作为报警首帧线索" in line for line in result["narrative"])


def test_narrative_uses_arbe_alarm_output_as_default_even_when_can_is_present():
    timeline = _timeline()
    timeline["sources"][1]["status"] = "observed"
    timeline["sources"][2]["status"] = "observed"
    timeline["sources"][-1]["status"] = "observed"
    timeline["rows"].extend([
        {
            "layer": "runtime_with_frame", "function": "PROJECT_WARN_L", "side": "L", "radar_id": 1,
            "frame_id": 100, "frame_status": "observed", "transition": "active", "value": 1,
        },
        {
            "layer": "can_tx_observation", "function": "PROJECT_WARN_L", "side": "L", "radar_id": 1,
            "frame_id": 100, "frame_status": "observed", "transition": "rising", "value": 1,
        },
    ])
    result = build_diagnostic_narrative(
        selected_event=_event(), condition_trace={"summary": {"total": 0}}, alert_timeline=timeline
    )
    assert result["output_policy"]["effective_endpoint"] == "algorithm"
    assert result["alarm_assessment"]["should_alert"] == "yes_observed"
    assert "CAN 数据" not in result["alarm_assessment"]["statement"]


def test_narrative_walks_algorithm_output_through_internal_and_external_mapping():
    event = _event()
    event["summary"]["function"] = "FCTA_R"
    event["summary"]["side"] = "R"
    event["summary"]["radar_id"] = 2
    event["runtime_observations"] = [{
        "layer": "gdb_observation",
        "identity": {"frame_id": 100, "object_id": 44},
        "fields": [{"token": "adasWarning->bRightFctaWarning", "value": 2, "status": "observed"}],
    }]
    timeline = _timeline()
    timeline["rows"] = [{
        "layer": "runtime_with_frame", "function": "FCTA_R", "side": "R", "radar_id": 2,
        "frame_id": 100, "frame_status": "observed", "transition": "active", "value": 2,
    }]
    result = build_diagnostic_narrative(
        selected_event=event,
        condition_trace={"summary": {"total": 0}},
        alert_timeline=timeline,
        can_output={
            "signals": [{
                "signal": "RRadar_FCTA_Warning_Right_S",
                "expression": "(AdasStM.Frontright_FCTA == 2) ? 1u:0u",
                "source_ref": {"path": "/src/RteComMapping_Tx.c", "line": 147},
                "internal_member_paths": ["AdasStM.Frontright_FCTA"],
                "assignment_status": "active_assignment_found",
                "internal_assignments": [{
                    "token": "AdasStM.Frontright_FCTA", "active": True,
                    "rhs": "ADAS_Warn_Process_FrontRight_FCTA(PEROutput.adasWarning.bRightFctaWarning)",
                    "source_ref": {"path": "/src/ADAS_HMI.c", "line": 3623},
                }],
                "producer_function_names": ["ADAS_Warn_Process_FrontRight_FCTA"],
                "transport_mappings": [{
                    "rte_lite_function": "RteLite_Write_RRadar_FCTA_Warning_Right_S",
                    "source_ref": {"path": "/src/rteLite.c", "line": 171},
                    "com_send_source_ref": {"path": "/src/rteLite.c", "line": 177},
                }],
            }],
            "source_output_chain": {"status": "source_scanned"},
        },
    )
    chain = result["diagnostic_story"]["output_chain"]
    assert chain["primary_internal_signal"] == "AdasStM.Frontright_FCTA"
    assert chain["primary_external_signal"] == "RRadar_FCTA_Warning_Right_S"
    assert chain["status"] == "algorithm_observed_source_mapping_candidate"
    assert "adasWarning->bRightFctaWarning" in chain["text"]
    assert "AdasStM.Frontright_FCTA" in result["diagnostic_story"]["conclusion"]["text"]


def test_narrative_distinguishes_object_warning_from_final_can_output():
    event = _event()
    event["summary"]["function"] = "FCTA_R"
    event["summary"]["side"] = "R"
    event["runtime_observations"] = [{
        "layer": "gdb_observation",
        "identity": {"frame_id": 100, "object_id": 44},
        "fields": [
            {"token": "objInfo->trcOutData[i].objFctaWarningFlag", "value": 4, "status": "observed"},
            {"token": "objInfo->trcOutData[i].rightFctaFlag", "value": True, "status": "observed"},
        ],
    }]
    result = build_diagnostic_narrative(
        selected_event=event,
        condition_trace={"summary": {"total": 0}},
        alert_timeline=_timeline(),
    )
    assert result["alarm_assessment"]["status"] == "object_warning_observed"
    assert result["alarm_assessment"]["should_alert"] == "indeterminate"
    assert result["object_warning_observed"] is True
    assert any("目标级报警状态" in line and "objInfo->trcOutData[i].objFctaWarningFlag=4" in line for line in result["narrative"])


def test_narrative_surfaces_runtime_disturbance():
    timeline = _timeline()
    timeline["disturbance"] = {"status": "suspected", "reason": "gdb stopped replay"}
    result = build_diagnostic_narrative(
        selected_event=_event(), condition_trace={"summary": {"total": 0}}, alert_timeline=timeline
    )
    assert any("gdb stopped replay" in line for line in result["narrative"])
    assert result["evidence_summary"]["disturbance_status"] == "suspected"


def test_narrative_default_is_compact_but_keeps_evidence_digest_and_real_tokens():
    event = _event()
    event["details"] = {
        "ego": {"fields": [
            {"code_token": "g_egoCarAddInfo.carSpd", "value": 4.4, "unit": "m/s"},
            {"code_token": "g_egoCarAddInfo.actual_gear", "value": 4},
        ]},
        "target": {"fields": [
            {"code_token": "objInfo->trcOutData[i].objID", "value": 44},
            {"code_token": "objInfo->trcOutData[i].distX", "value": 5.9, "unit": "m"},
            {"code_token": "objInfo->trcOutData[i].distY", "value": -4.7, "unit": "m"},
        ]},
    }
    conditions = [
        {
            "condition_id": f"c{index}", "function": "Project",
            "expression": f"if (g_egoCarAddInfo.carSpd > {index})",
            "source_ref": {"file_path": "project.c", "line": index},
            "missing_tokens": [f"value{index}"],
            "evaluation": {"status": "not_evaluable", "reason": "missing"},
        }
        for index in range(12)
    ]
    result = build_diagnostic_narrative(
        selected_event=event,
        condition_trace={
            "conditions": conditions,
            "summary": {"total": 12, "satisfied": 0, "not_satisfied": 0, "not_evaluable": 12, "unsupported": 0},
        },
        alert_timeline=_timeline(),
    )
    assert len(result["condition_items"]) == 10
    assert result["condition_digest"]["omitted_count"] == 2
    assert "g_egoCarAddInfo.carSpd=4.4" in result["executive_summary"]
    assert "objInfo->trcOutData[i].objID=44" in result["executive_summary"]
    flow = result["analysis_flow"]
    assert flow["schema_version"] == "diagnostic-analysis-flow.v1"
    assert [step["kind"] for step in flow["steps"]] == [
        "input_context", "source_condition_walk", "geometry_and_prediction", "output_decision", "fct_output_mapping",
    ]
    assert len(flow["steps"][1]["conditions"]) == 10
    assert "bindings" in flow["steps"][1]["conditions"][0]


def test_narrative_reports_pointer_dot_alias_as_unbound_hint():
    event = _event()
    event["summary"]["function"] = "FCTA_R"
    event["summary"]["side"] = "R"
    event["runtime_observations"] = [{
        "layer": "gdb_observation",
        "identity": {"frame_id": 100, "object_id": 44},
        "fields": [{"token": "sObj->objFctaWarningFlag", "value": 4, "status": "observed"}],
    }]
    result = build_diagnostic_narrative(
        selected_event=event,
        condition_trace={
            "conditions": [{
                "condition_id": "c1", "function": "FCTA_R",
                "expression": "if (sObj.objFctaWarningFlag > 0)",
                "source_ref": {"file_path": "adasFunc.c", "line": 10},
                "missing_tokens": ["sObj.objFctaWarningFlag"],
                "evaluation": {"status": "not_evaluable", "reason": "missing"},
            }],
            "summary": {"total": 1, "satisfied": 0, "not_satisfied": 0, "not_evaluable": 1, "unsupported": 0},
        },
        alert_timeline=_timeline(),
    )
    assert result["condition_digest"]["alias_hints"][0]["observed_token"] == "sObj->objFctaWarningFlag"
    assert any("变量映射线索" in line for line in result["narrative"])
