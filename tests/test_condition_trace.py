# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from ai.modules import MODULE_REGISTRY
from ai.modules.condition_trace import ConditionTraceModule
from engines.condition_trace import build_condition_trace
from engines.diagnostic_report import build_diagnostic_report, write_diagnostic_report


def test_condition_trace_evaluates_current_source_parameters_and_same_frame_values():
    payload = build_condition_trace(
        conditions=[
            {"function": "BlindSpotsAlert", "file_path": "adasFunc.c", "line": 1,
             "expression": "if (fabsf(sObj.velAbsX) > fBsdObjWarningSpd * System_Kmh2ms)"},
            {"function": "BlindSpotsAlert", "file_path": "adasFunc.c", "line": 2,
             "expression": "&& (sObj.distY >= leftRoiInnerY)"},
        ],
        values={
            "sObj.velAbsX": {"value": 2.02, "source_kind": "observed_in_bag"},
            "sObj.distY": {"value": 4.96, "source_kind": "observed_in_bag"},
            "leftRoiInnerY": {"value": 0.988, "source_kind": "derived_from_code"},
        },
        parameters=[
            {"name": "fBsdObjWarningSpd", "value": "7.2f", "file_path": "para.c", "line": 2},
            {"name": "System_Kmh2ms", "value": "0.2777777778f", "file_path": "unit.h", "line": 1},
        ],
        function="BlindSpotsAlert",
        frame_id=10,
    )
    assert payload["status"] == "ready"
    assert payload["summary"]["satisfied"] == 1
    assert payload["conditions"][0]["evaluation"]["status"] == "satisfied"
    assert "2.02" in payload["conditions"][0]["substituted_expression"]
    Draft202012Validator(
        json.loads(Path("contracts/condition-trace.v1.schema.json").read_text(encoding="utf-8"))
    ).validate(payload)


def test_condition_trace_never_converts_missing_value_to_false():
    payload = build_condition_trace(
        conditions=[{"function": "Any", "line": 7, "expression": "if (runtimeFlag > 0)"}],
        values={},
        function="Any",
        frame_id=7,
    )
    condition = payload["conditions"][0]
    assert condition["evaluation"]["status"] == "not_evaluable"
    assert condition["evaluation"]["value"] is None
    assert condition["missing_tokens"] == ["runtimeFlag"]


def test_condition_trace_reads_current_source_macros(tmp_path: Path):
    header = tmp_path / "paraDefine.h"
    header.write_text("#define System_Kmh2ms 0.277777778f\n#define EGOCARWIDTH 1.976f\n", encoding="utf-8")
    payload = build_condition_trace(
        conditions=[{"function": "Any", "file_path": "x.c", "line": 1,
                     "expression": "if (speed <= 7.2f * System_Kmh2ms && EGOCARWIDTH > 0.0f)"}],
        values={"speed": {"value": 1.0, "source_kind": "observed_in_bag"}},
        source_root=str(tmp_path),
    )
    condition = payload["conditions"][0]
    assert condition["evaluation"]["status"] == "satisfied"
    assert {item["token"] for item in condition["bindings"] if item["status"] == "bound"} == {
        "speed", "System_Kmh2ms", "EGOCARWIDTH"
    }


def test_condition_trace_reads_multiline_enum_constants_from_current_source(tmp_path: Path):
    header = tmp_path / "paraDefine.h"
    header.write_text(
        "enum emWarningFlag\n{\n    WarningFlag_Normal = 0U,\n    WarningFlag_Warning = 4U,\n};\n",
        encoding="utf-8",
    )
    payload = build_condition_trace(
        conditions=[{"function": "Any", "file_path": "x.c", "line": 1,
                     "expression": "if (objFlag > WarningFlag_Normal && objFlag == WarningFlag_Warning)"}],
        values={"objFlag": {"value": 4, "source_kind": "runtime_gdb_observation"}},
        source_root=str(tmp_path),
    )
    condition = payload["conditions"][0]
    assert condition["evaluation"]["status"] == "satisfied"
    assert condition["bindings"][1]["token"] == "WarningFlag_Normal"
    assert condition["bindings"][1]["value"] == 0


def test_condition_trace_uses_source_proven_local_object_copy_alias(tmp_path: Path):
    source = tmp_path / "adasFunc.c"
    source.write_text(
        """
void Alarm(objOutStruct* objInfo) {
    for (int i = 0; i < objInfo->trcNum; ++i) {
        objOutDataStruct sObj = objInfo->trcOutData[i];
        sObj.velAbsX = sObj.velX + ego.speed;
        if (sObj.objFctaWarningFlag > (int8_t)WarningFlag_Normal) {
            emit_warning();
        }
    }
}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    payload = build_condition_trace(
        conditions=[{
            "function": "Alarm", "file_path": "adasFunc.c", "line": 5,
            "expression": "if (sObj.objFctaWarningFlag > 0)",
        }],
        values={
            "objInfo->trcOutData[i].objFctaWarningFlag": {
                "value": 4, "source_kind": "runtime_gdb_observation",
            },
        },
        source_root=str(tmp_path),
    )
    condition = payload["conditions"][0]
    assert condition["evaluation"]["status"] == "satisfied"
    assert condition["bindings"][0]["token"] == "sObj.objFctaWarningFlag"
    assert condition["bindings"][0]["source_kind"] == "runtime_gdb_observation"
    assert payload["source_alias_bindings"][0]["source"] == "objInfo->trcOutData[i]"


def test_condition_trace_module_is_pi_visible():
    assert MODULE_REGISTRY["condition-trace"] is ConditionTraceModule
    result = ConditionTraceModule().safe_run(
        conditions=[{"expression": "if (flag == 1)", "line": 4}],
        values={"flag": {"value": 1, "source_kind": "runtime"}},
    )
    assert result.ok
    assert result.data["summary"]["satisfied"] == 1


def test_diagnostic_report_projects_condition_trace_and_scene(tmp_path: Path):
    bundle = {
        "schema_version": "diagnosis-bundle.v1",
        "case": {"case_id": "CASE-1", "bag": "/data/demo.bag"},
        "provenance": {"project": "demo", "source_context_id": "source-1", "source_snapshot_hash": "src-1"},
        "alarm_events": [{
            "event_id": "event-a", "function": "FUNC_A_L", "radar_id": 3,
            "source": "algorithm_output", "first_on_frame": 100,
            "selected_target": {"obj_id": 44},
            "breakpoint_pack": {"breakpoints": [{"function": "FuncA", "condition": "frame_counter == 100"}]},
        }],
    }
    viewer = {
        "schema_version": "viewer-model.v1", "data_name": "demo.bag",
        "case": {"case_id": "CASE-1", "bag": "/data/demo.bag"},
        "events": [{
            "event_id": "event-a",
            "identity": {"function": "FUNC_A_L", "side": "L", "radar_id": 3, "radar_name": "Rear_Left"},
            "alarm": {"start_time_sec": 1.0, "end_time_sec": 2.0, "sample_count": 1},
                "frame": {"target_frame": 100, "target_frame_source": "first_on_frame", "selection_confidence": "observed"},
                "breakpoint_pack": {"breakpoints": [{"function": "FuncA", "condition": "frame_counter == 100"}]},
                "ego": {"polygon": [{"x": 0, "y": 1}, {"x": 4, "y": 1}, {"x": 4, "y": -1}, {"x": 0, "y": -1}], "fields": []},
            "target": {"selected": True, "obj_id": 44, "fields": [{"code_token": "objInfo->trcOutData[i].objID", "value": 44}],
                       "geometry": {"polygon": [{"x": 6, "y": 3}, {"x": 5, "y": 3}, {"x": 5, "y": 2}, {"x": 6, "y": 2}], "position": {"x": 5.5, "y": 2.5}}},
        }],
    }
    code = {
        "schema_version": "event-code-path.v1",
        "resolution": {"conditions": [{"function": "FuncA", "file_path": "adas.c", "line": 12, "expression": "if (objInfo->trcOutData[i].objID == 44)"}]},
    }
    report = build_diagnostic_report(
        bundle=bundle, viewer_model=viewer, event_id="event-a", event_code_path=code,
    )
    assert report["condition_trace"]["summary"]["satisfied"] == 1
    paths = write_diagnostic_report(report, tmp_path)
    html = Path(next(path for path in paths if path.endswith(".html"))).read_text(encoding="utf-8")
    assert "完整代码条件明细" in html
    assert "scene-svg" in html
    assert "Diagnostic narrative" in html
    assert "代码条件支持报警" in html
    assert "Debug anchors" in html
    assert "frame_counter == 100" in html


def test_diagnostic_report_re_evaluates_condition_from_exact_runtime_observation():
    bundle = {
        "schema_version": "diagnosis-bundle.v1",
        "case": {"case_id": "CASE-RUNTIME", "bag": "/data/runtime.bag"},
        "alarm_events": [{
            "event_id": "runtime-event",
            "function": "FUNC_R",
            "radar_id": 2,
            "source": "recorded_raw",
            "first_on_frame": 100,
        }],
    }
    viewer = {
        "schema_version": "viewer-model.v1",
        "events": [{
            "event_id": "runtime-event",
            "identity": {"function": "FUNC_R", "side": "R", "radar_id": 2},
            "frame": {"target_frame": 100, "target_frame_source": "wfAutosarData.frameID", "selection_confidence": "observed"},
        }],
    }
    runtime = {
        "schema_version": "runtime-case-evidence.v1",
        "run": {"run_id": "runtime-run", "data_fingerprint": "d", "source_context_id": "s"},
        "evidence_layers": [],
        "observations": [{
            "layer": "gdb_observation",
            "identity": {"function": "FUNC_R", "radar_id": 2, "frame_id": 100},
            "fields": [{"token": "runtimeFlag", "value": 1, "status": "observed"}],
        }],
    }
    code = {
        "schema_version": "event-code-path.v1",
        "resolution": {"conditions": [{"function": "FUNC_R", "file_path": "func.c", "line": 9, "expression": "if (runtimeFlag == 1)"}]},
    }
    report = build_diagnostic_report(
        bundle=bundle, viewer_model=viewer, runtime_evidence=runtime,
        event_code_path=code, event_id="runtime-event",
    )
    assert report["selected_event"]["runtime_association"] == "exact_event_or_frame"
    assert report["condition_trace"]["conditions"][0]["evaluation"]["status"] == "satisfied"
    assert report["condition_trace"]["conditions"][0]["bindings"][0]["source_kind"] == "runtime_gdb_observation"


def test_diagnostic_report_projects_source_geometry_relation_for_current_side():
    bundle = {
        "schema_version": "diagnosis-bundle.v1",
        "case": {"case_id": "CASE-GEOMETRY", "bag": "/data/geometry.bag"},
        "alarm_events": [{
            "event_id": "geometry-event", "function": "FCTA_R", "radar_id": 2,
            "source": "recorded_raw", "first_on_frame": 100,
            "selected_target": {"obj_id": 44},
        }],
    }
    viewer = {
        "schema_version": "viewer-model.v1",
        "events": [{
            "event_id": "geometry-event",
            "identity": {"function": "FCTA_R", "side": "R", "radar_id": 2},
            "frame": {"target_frame": 100, "target_frame_source": "wfAutosarData.frameID", "selection_confidence": "observed"},
            "target": {
                "selected": True, "obj_id": 44,
                "geometry": {"polygon": [
                    {"x": 6, "y": -3}, {"x": 5, "y": -3},
                    {"x": 5, "y": -2}, {"x": 6, "y": -2},
                ]},
            },
            "roi_layers": [{
                "feature": "FCTA", "polygons": {
                    "left": [{"x": 3, "y": 1}, {"x": 4, "y": 1}, {"x": 4, "y": 0}, {"x": 3, "y": 0}],
                    "right": [{"x": 3, "y": 0}, {"x": 7, "y": 0}, {"x": 7, "y": -1}, {"x": 3, "y": -1}],
                },
            }],
        }],
    }
    report = build_diagnostic_report(bundle=bundle, viewer_model=viewer, event_id="geometry-event")
    assert report["geometry_projection"]["collision_status"] == "source_derived_disjoint"
    assert report["geometry_projection"]["collision_evidence"][0]["relation"] == "disjoint"
    assert "source_derived_disjoint" in report["diagnostic_narrative"]["executive_summary"]


def test_diagnostic_report_falls_back_to_event_code_output_mapping_without_preflight():
    bundle = {
        "schema_version": "diagnosis-bundle.v1",
        "case": {"case_id": "CASE-TX-FALLBACK", "bag": "/data/tx.bag"},
        "alarm_events": [{
            "event_id": "tx-fallback", "function": "FCTA_R", "radar_id": 2,
            "first_on_frame": 100,
        }],
    }
    viewer = {
        "schema_version": "viewer-model.v1",
        "events": [{
            "event_id": "tx-fallback",
            "identity": {"function": "FCTA_R", "side": "R", "radar_id": 2},
            "frame": {"target_frame": 100, "selection_confidence": "observed"},
        }],
    }
    code = {
        "schema_version": "event-code-path.v1",
        "resolution": {"output_signals": [{
            "signal_name": "RRadar_FCTA_Warning_Right_S",
            "expression": "(AdasStM.Frontright_FCTA == 2)",
            "file_path": "RteComMapping_Tx.c", "line": 147,
        }]},
    }
    report = build_diagnostic_report(
        bundle=bundle, viewer_model=viewer, event_code_path=code, event_id="tx-fallback",
    )
    assert report["can_output"]["source"] == "event_code_path.resolution.output_signals"
    assert report["can_output"]["signals"][0]["signal"] == "RRadar_FCTA_Warning_Right_S"


def test_diagnostic_report_surfaces_conflicting_embedded_radar_mapping():
    bundle = {
        "schema_version": "diagnosis-bundle.v1",
        "case": {"case_id": "CASE-MAPPING", "bag": "/data/mapping.bag"},
        "alarm_events": [{"event_id": "mapping-event", "function": "FCTA_R", "radar_id": 2, "first_on_frame": 100}],
    }
    viewer = {
        "schema_version": "viewer-model.v1",
        "events": [{
            "event_id": "mapping-event",
            "identity": {"function": "FCTA_R", "side": "R", "radar_id": 2},
            "frame": {
                "target_frame": 100,
                "source_ref": {"topic": "/wf/corner_radar/lgu_data_2"},
                "gui_main_mapping": {"radar_id": 3, "topic": "/wf/corner_radar/lgu_data_3", "frame_id": 100},
            },
        }],
    }
    report = build_diagnostic_report(bundle=bundle, viewer_model=viewer, event_id="mapping-event")
    assert report["frame_mapping_conflicts"][0]["actual_radar_id"] == 3
    assert "frame_radar_mapping_conflict" in {item["id"] for item in report["diagnosis"]["evidence_gaps"]}
    assert "radar/frame 冲突" in "\n".join(report["diagnostic_narrative"]["narrative"])


def test_diagnostic_report_projects_event_scoped_source_can_output_mapping(tmp_path: Path):
    bundle = {
        "schema_version": "diagnosis-bundle.v1",
        "case": {"case_id": "CASE-TX", "bag": "/data/tx.bag"},
        "alarm_events": [{
            "event_id": "tx-event", "function": "FCTA_R", "side": "R", "radar_id": 2,
            "first_on_frame": 100,
        }],
    }
    viewer = {
        "schema_version": "viewer-model.v1",
        "events": [{
            "event_id": "tx-event",
            "identity": {"function": "FCTA_R", "side": "R", "radar_id": 2},
            "frame": {"target_frame": 100, "target_frame_source": "wfAutosarData.frameID", "selection_confidence": "observed"},
        }],
    }
    preflight = {
        "schema_version": "arbe-preflight.v1", "status": "ready",
        "can_output": {
            "candidate_signal_tokens": [
                "RRadar_FCTA_Warning_Left_S", "RRadar_FCTA_Warning_Right_S", "FCTA_Assemble_Status_S",
            ],
            "write_mappings": [
                {"signal": "RRadar_FCTA_Warning_Left_S", "expression": "AdasStM.Frontleft_FCTA", "source_ref": {"path": "/src/RteComMapping_Tx.c", "line": 144}},
                {"signal": "RRadar_FCTA_Warning_Right_S", "expression": "AdasStM.Frontright_FCTA", "source_ref": {"path": "/src/RteComMapping_Tx.c", "line": 147}},
                {"signal": "FCTA_Assemble_Status_S", "expression": "AdasStM.fctaSysState", "source_ref": {"path": "/src/RteComMapping_Tx.c", "line": 170}},
                {"signal": "RRadar_FCTB_Warning_Right_S", "expression": "AdasStM.Frontright_FCTB", "source_ref": {"path": "/src/RteComMapping_Tx.c", "line": 180}},
            ],
            "transport_mappings": [
                {"signal": "RRadar_FCTA_Warning_Right_S", "rte_lite_function": "RteLite_Write_RRadar_FCTA_Warning_Right_S", "com_signal": "RRadar_FCTA_Warning_Right_S", "source_ref": {"path": "/src/rteLite.c", "line": 20}, "com_send_source_ref": {"path": "/src/rteLite.c", "line": 26}},
                {"signal": "RRadar_FCTA_Warning_Left_S", "rte_lite_function": "RteLite_Write_RRadar_FCTA_Warning_Left_S", "com_signal": "RRadar_FCTA_Warning_Left_S", "source_ref": {"path": "/src/rteLite.c", "line": 30}, "com_send_source_ref": {"path": "/src/rteLite.c", "line": 36}},
            ],
        },
    }
    report = build_diagnostic_report(
        bundle=bundle, viewer_model=viewer, preflight=preflight, event_id="tx-event",
    )
    signals = {item["signal"] for item in report["can_output"]["signals"]}
    assert "RRadar_FCTA_Warning_Right_S" in signals
    assert "FCTA_Assemble_Status_S" in signals
    assert "RRadar_FCTA_Warning_Left_S" not in signals
    assert "RRadar_FCTB_Warning_Right_S" not in signals
    assert report["can_output"]["signals"][0]["transport_mappings"][0]["rte_lite_function"] == "RteLite_Write_RRadar_FCTA_Warning_Right_S"
    assert report["diagnostic_narrative"]["can_output"]["status"] == "source_candidate"
    assert any("下游输出映射候选" in line for line in report["diagnostic_narrative"]["narrative"])
    paths = write_diagnostic_report(report, tmp_path)
    html = Path(next(path for path in paths if path.endswith(".html"))).read_text(encoding="utf-8")
    assert "Source output chain" in html
    assert "RRadar_FCTA_Warning_Right_S" in html
    assert "运行时执行观测仍是独立证据层" in html
