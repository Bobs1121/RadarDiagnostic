# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from ai.data_query_engine import DataQueryEngine
from ai.investigation_engine import EngineeringInvestigator
from engines.signal_mapper import extract_signal_mapping
from parsers.frame_store import FrameStore


def _write_knowledge(docs: Path, conditions: list[dict], mapping: dict | None = None):
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "RCTA_conditions.json").write_text(
        json.dumps({"function": "RCTA", "thresholds": conditions}),
        encoding="utf-8",
    )
    if mapping is not None:
        (docs / "signal_mapping.json").write_text(
            json.dumps(mapping), encoding="utf-8",
        )


def _store_with_signals(signal_values: dict[str, list[float]]) -> FrameStore:
    store = FrameStore()
    count = max(len(values) for values in signal_values.values())
    rows = []
    for index in range(count):
        rows.append({
            "timestamp": float(index),
            "can_id": 0x100,
            "can_id_hex": "0x100",
            "message_name": "VehicleState",
            "signals": {
                name: values[index]
                for name, values in signal_values.items()
                if index < len(values)
            },
        })
    store.bulk_insert_can_from_dict(rows)
    return store


def _lookup(*names: str) -> dict:
    return {
        name: {"can_id": 0x100, "message_name": "VehicleState"}
        for name in names
    }


class _FakeCodeGraph:
    is_available = True
    conn = None

    def __init__(self):
        self.closed = False

    def get_functions_in_range(self, start, end, file_path=None):
        if file_path == "logic.c" and start == 42:
            return [SimpleNamespace(name="RctaTriggerCheck")]
        return []

    def get_callers(self, name):
        return [{"caller_name": "RctaMain"}]

    def get_callees(self, name):
        return [{"callee_name": "ReadGear"}]

    def close(self):
        self.closed = True


def test_condition_results_cover_satisfied_violated_mixed_and_unknown(tmp_path):
    docs = tmp_path / "docs"
    conditions = [
        {"condition": "sat == 1", "variable": "sat", "operator": "==", "threshold": "1", "source": "logic.c:42"},
        {"condition": "fail == 1", "variable": "fail", "operator": "==", "threshold": "1", "source": "logic.c:43"},
        {"condition": "mixed == 1", "variable": "mixed", "operator": "==", "threshold": "1", "source": "logic.c:44"},
        {"condition": "hidden == 1", "variable": "hidden", "operator": "==", "threshold": "1", "source": "logic.c:45"},
    ]
    mapping = {
        "internal_to_can": {"sat": ["SatSig"], "fail": ["FailSig"], "mixed": ["MixedSig"]},
        "fullpath_to_can": {},
    }
    _write_knowledge(docs, conditions, mapping)
    store = _store_with_signals({
        "SatSig": [1, 1], "FailSig": [0, 0], "MixedSig": [0, 1],
    })
    graph = _FakeCodeGraph()
    engine = EngineeringInvestigator(
        {"paths": {"source_docs": str(docs)}}, tmp_path,
        codegraph_factory=lambda _: graph,
    )

    result = engine.investigate(
        store, "为什么RCTA异常", {"functions": ["RCTA"], "need_code_analysis": True},
        _lookup("SatSig", "FailSig", "MixedSig"),
    )

    by_variable = {check.variables[0]: check for check in result.condition_checks}
    assert by_variable["sat"].result == "satisfied"
    assert by_variable["fail"].result == "violated"
    assert by_variable["mixed"].result == "mixed"
    assert by_variable["hidden"].result == "unknown"
    assert by_variable["hidden"].observation["mapping_status"] == "unmapped"
    assert by_variable["mixed"].observation["sample_count"] == 2
    assert graph.closed is True
    store.close()


def test_radar_debug_alias_requires_real_schema_column(tmp_path):
    docs = tmp_path / "docs"
    _write_knowledge(docs, [
        {
            "condition": "g_egoCarInfo.actual_gear == 7",
            "variable": "g_egoCarInfo.actual_gear",
            "operator": "==",
            "threshold": "7",
            "source": "logic.c:42",
        },
    ])
    store = FrameStore()
    store.conn.executemany(
        "INSERT INTO radar_debug(timestamp_ns, radar_id, frame_id, actual_gear) VALUES(?,?,?,?)",
        [(1_000_000_000, 0, 1, 7), (2_000_000_000, 0, 2, 7)],
    )
    store.conn.commit()
    engine = EngineeringInvestigator(
        {"paths": {"source_docs": str(docs)}}, tmp_path,
        codegraph_factory=lambda _: _FakeCodeGraph(),
    )

    result = engine.investigate(store, "RCTA挡位条件", {"functions": ["RCTA"]}, {})

    check = result.condition_checks[0]
    assert check.signals == ["radar_debug.actual_gear"]
    assert check.result == "satisfied"
    assert result.data_facts[0].sample_count == 2
    store.close()


def test_signal_mapping_discovers_rx_companion_and_invalidates_cache(tmp_path):
    source_root = tmp_path / "source"
    mapping_dir = source_root / "coem" / "customer" / "ASW_ComMapping"
    mapping_dir.mkdir(parents=True)
    primary = mapping_dir / "RteComMapping.c"
    companion = mapping_dir / "RteComMapping_Rx.c"
    primary.write_text("void Run(void) { RteComMapping_RxRunnable(); }", encoding="utf-8")
    companion.write_text(
        "RteComMapping_ReadSignal(Vehicle_speed)(&ftmp);\n"
        "VehcleInfoUpdate.actual_spd = ftmp / 3.6f;\n",
        encoding="utf-8",
    )
    docs = tmp_path / "docs"
    rte_file = str(primary.relative_to(source_root))

    first = extract_signal_mapping(source_root, docs, rte_file=rte_file)
    assert first["mapping_count"] == 1
    assert len(first["source_files"]) == 2
    assert first["fullpath_to_can"]["VehcleInfoUpdate.actual_spd"] == ["Vehicle_speed"]

    companion.write_text(
        companion.read_text(encoding="utf-8")
        + "RteComMapping_ReadSignal(Yaw_Rate)(&ftmp);\n"
        + "VehcleInfoUpdate.yaw_rate = ftmp;\n",
        encoding="utf-8",
    )
    second = extract_signal_mapping(source_root, docs, rte_file=rte_file)
    assert second["source_hash"] != first["source_hash"]
    assert second["mapping_count"] == 2


def test_investigator_builds_mapping_from_minimal_project_config(tmp_path):
    source_root = tmp_path / "source"
    mapping_dir = source_root / "coem" / "customer" / "ASW_ComMapping"
    mapping_dir.mkdir(parents=True)
    primary = mapping_dir / "RteComMapping.c"
    primary.write_text(
        "RteComMapping_ReadSignal(GearSig)(&u8tmp);\n"
        "VehcleInfoUpdate.actual_gear = u8tmp;\n",
        encoding="utf-8",
    )
    docs = tmp_path / "docs"
    _write_knowledge(docs, [{
        "condition": "VehcleInfoUpdate.actual_gear == 7",
        "variable": "VehcleInfoUpdate.actual_gear",
        "operator": "==",
        "threshold": "7",
        "source": "logic.c:42",
    }])
    store = _store_with_signals({"GearSig": [7, 7]})
    config = {
        "paths": {"source_docs": str(docs)},
        "project": {
            "source_code": str(source_root),
            "source_domains": {"signal_chain": [str(primary.relative_to(source_root))]},
        },
    }
    engine = EngineeringInvestigator(
        config, tmp_path, codegraph_factory=lambda _: _FakeCodeGraph(),
    )

    result = engine.investigate(
        store, "RCTA挡位条件", {"functions": ["RCTA"]}, _lookup("GearSig"),
    )

    assert result.condition_checks[0].result == "satisfied"
    assert result.to_dict()["deterministic_conclusion_available"] is True
    assert (docs / "signal_mapping.json").exists()
    store.close()


def test_transformed_mapping_keeps_raw_can_comparison_unknown(tmp_path):
    docs = tmp_path / "docs"
    _write_knowledge(docs, [{
        "condition": "actual_gear == 7",
        "variable": "actual_gear",
        "operator": "==",
        "threshold": "7",
        "source": "logic.c:42",
    }], {
        "mapping_count": 1,
        "internal_to_can": {"actual_gear": ["Rnk_hw"]},
        "fullpath_to_can": {},
        "mappings": [{
            "can_signal": "Rnk_hw",
            "internal_var": "actual_gear",
            "internal_full_path": "VehcleInfoUpdate.actual_gear",
            "transform": "8u",
            "scaling": "",
        }],
    })
    store = _store_with_signals({"Rnk_hw": [2, 2]})
    engine = EngineeringInvestigator(
        {"paths": {"source_docs": str(docs)}}, tmp_path,
        codegraph_factory=lambda _: _FakeCodeGraph(),
    )

    result = engine.investigate(
        store, "RCTA挡位条件", {"functions": ["RCTA"]}, _lookup("Rnk_hw"),
    )

    check = result.condition_checks[0]
    assert check.result == "unknown"
    assert check.observation["mapping_status"] == "transformed_signal_mapping"
    assert result.to_dict()["deterministic_conclusion_available"] is False
    assert any("require code transforms" in item for item in result.limitations)
    store.close()


def test_simple_enum_mapping_is_applied_before_condition_check(tmp_path):
    source_root = tmp_path / "source"
    mapping_dir = source_root / "coem" / "customer" / "ASW_ComMapping"
    mapping_dir.mkdir(parents=True)
    primary = mapping_dir / "RteComMapping.c"
    primary.write_text(
        "RteComMapping_ReadSignal(Rnk_hw)(&u8tmp);\n"
        "switch (u8tmp)\n{\n"
        "case 1:\nVehcleInfoUpdate.actual_gear = 8u;\nbreak;\n"
        "case 2:\nVehcleInfoUpdate.actual_gear = 7u;\nbreak;\n"
        "default:\nVehcleInfoUpdate.actual_gear = 0u;\nbreak;\n}\n",
        encoding="utf-8",
    )
    docs = tmp_path / "docs"
    mapping = extract_signal_mapping(
        source_root, docs, rte_file=str(primary.relative_to(source_root)),
    )
    assert mapping["mappings"][0]["transform"] == "enum"
    assert mapping["mappings"][0]["enum_map"] == {"1": 8, "2": 7}
    _write_knowledge(docs, [{
        "condition": "actual_gear == 7",
        "variable": "actual_gear",
        "operator": "==",
        "threshold": "7",
        "source": "logic.c:42",
    }], mapping)
    store = _store_with_signals({"Rnk_hw": [2, 2]})
    engine = EngineeringInvestigator(
        {"paths": {"source_docs": str(docs)}}, tmp_path,
        codegraph_factory=lambda _: _FakeCodeGraph(),
    )

    result = engine.investigate(
        store, "RCTA挡位条件", {"functions": ["RCTA"]}, _lookup("Rnk_hw"),
    )

    check = result.condition_checks[0]
    assert check.result == "satisfied"
    assert check.observation["mapping_status"] == "signal_mapping_enum"
    assert check.observation["min"] == 7
    assert check.observation["raw_min"] == 2
    assert check.observation["evaluated_domain"] == "internal_after_mapping"
    assert check.observation["mapping_evidence"][0]["enum_map"] == {"1": 8, "2": 7}
    store.close()


def test_enable_signal_limits_condition_checks_to_active_window(tmp_path):
    docs = tmp_path / "docs"
    _write_knowledge(docs, [{
        "condition": "gear == 7",
        "variable": "gear",
        "operator": "==",
        "threshold": "7",
        "source": "logic.c:42",
    }], {
        "mapping_count": 1,
        "internal_to_can": {"gear": ["GearSig"]},
        "fullpath_to_can": {},
        "mappings": [{
            "can_signal": "GearSig", "internal_var": "gear",
            "internal_full_path": "state.gear", "transform": "passthrough",
            "scaling": "1:1",
        }],
    })
    store = _store_with_signals({
        "FCTA_Enable_S": [2, 2, 2, 2],
        "RCTA_Enable_S": [0, 2, 2, 0],
        "GearSig": [7],
    })
    engine = EngineeringInvestigator(
        {"paths": {"source_docs": str(docs)}}, tmp_path,
        codegraph_factory=lambda _: _FakeCodeGraph(),
    )
    plan = {
        "functions": ["RCTA"],
        "can_signals": [
            {"signal_name": "FCTA_Enable_S", "role": "primary"},
            {"signal_name": "RCTA_Enable_S", "role": "primary"},
            {"signal_name": "GearSig", "role": "check"},
        ],
    }

    result = engine.investigate(
        store, "RCTA为何未触发", plan,
        _lookup("FCTA_Enable_S", "RCTA_Enable_S", "GearSig"),
    )

    assert result.analysis_windows == [{
        "source_signal": "RCTA_Enable_S", "start": 1.0, "end": 2.0,
        "rule": "recorded value > 0",
    }]
    assert result.condition_checks[0].result == "satisfied"
    assert result.data_facts[0].windowed is True
    assert result.data_facts[0].carry_forward_count == 1
    store.close()


def test_incomplete_enum_coverage_cannot_report_satisfied(tmp_path):
    docs = tmp_path / "docs"
    _write_knowledge(docs, [{
        "condition": "gear == 7", "variable": "gear", "operator": "==",
        "threshold": "7", "source": "logic.c:42",
    }], {
        "mapping_count": 1,
        "internal_to_can": {"gear": ["GearSig"]},
        "fullpath_to_can": {},
        "mappings": [{
            "can_signal": "GearSig", "internal_var": "gear",
            "internal_full_path": "state.gear", "transform": "enum",
            "enum_map": {"2": 7},
        }],
    })
    store = _store_with_signals({"GearSig": [2, 9]})
    engine = EngineeringInvestigator(
        {"paths": {"source_docs": str(docs)}}, tmp_path,
        codegraph_factory=lambda _: _FakeCodeGraph(),
    )

    result = engine.investigate(
        store, "RCTA档位", {"functions": ["RCTA"]}, _lookup("GearSig"),
    )

    check = result.condition_checks[0]
    assert check.result == "unknown"
    assert check.observation["mapping_status"] == "partial_enum_mapping"
    assert check.observation["sample_count"] == 1
    assert any("did not cover" in item for item in result.limitations)
    store.close()


def test_selection_is_bounded_and_source_ref_reaches_codegraph(tmp_path):
    docs = tmp_path / "docs"
    conditions = [
        {
            "condition": f"value_{index} > {index}",
            "variable": f"value_{index}",
            "operator": ">",
            "threshold": str(index),
            "source": "logic.c:42",
        }
        for index in range(20)
    ]
    _write_knowledge(docs, conditions)
    store = FrameStore()
    engine = EngineeringInvestigator(
        {"paths": {"source_docs": str(docs)}}, tmp_path, max_conditions=3,
        codegraph_factory=lambda _: _FakeCodeGraph(),
    )

    result = engine.investigate(store, "RCTA value_19", {"functions": ["RCTA"]}, {})

    assert len(result.condition_checks) == 3
    assert result.condition_checks[0].variables == ["value_19"]
    assert result.condition_checks[0].code_ref == "logic.c:42"
    assert result.code_facts[0].function_name == "RctaTriggerCheck"
    assert result.code_facts[0].callers == ["RctaMain"]
    assert result.code_facts[0].callees == ["ReadGear"]
    store.close()


class _FakeRouter:
    def __init__(self):
        self.prompts: list[str] = []

    def complex(self, prompt, system="", **kwargs):
        self.prompts.append(prompt)
        if len(self.prompts) == 1:
            return {"content": json.dumps({
                "can_signals": [{"signal_name": "GearSig", "role": "check"}],
                "bag_fields": [],
                "functions": ["RCTA"],
                "code_symbols": ["actual_gear"],
                "need_code_analysis": True,
                "query_type": "threshold",
                "summary": "check gear",
            })}
        return {"content": "answer"}


def test_data_query_engine_injects_investigation_evidence_and_closes_store(tmp_path, monkeypatch):
    docs = tmp_path / "docs"
    _write_knowledge(docs, [
        {
            "condition": "gear == 7",
            "variable": "gear",
            "can_signal": "GearSig",
            "operator": "==",
            "threshold": "7",
            "source": "logic.c:42",
        },
    ])
    store = _store_with_signals({"GearSig": [7, 7]})
    router = _FakeRouter()
    engine = DataQueryEngine(router, {"paths": {"source_docs": str(docs)}}, tmp_path)
    monkeypatch.setattr(engine, "_parse_data", lambda case_dir, status: (store, None))

    answer = engine.run_query(tmp_path, "为什么RCTA没有触发")

    assert answer == "answer"
    final_prompt = router.prompts[-1]
    assert '"condition_checks"' in final_prompt
    assert '"result":"satisfied"' in final_prompt
    assert '"deterministic_checks_are_advisory":true' in final_prompt
    assert "unknown 只表示未观测或无法映射" in final_prompt
    assert "不能因为单项检查 unknown 就停止分析" in final_prompt
    try:
        store.conn.execute("SELECT 1")
        assert False, "FrameStore should be closed in run_query finally"
    except Exception:
        pass


def test_stale_variant_conditions_are_excluded_from_query_and_investigation(tmp_path):
    docs = tmp_path / "docs"
    _write_knowledge(docs, [{
        "condition": "gear == 7", "variable": "gear", "operator": "==",
        "threshold": "7", "source": "logic.c:42",
    }], {
        "mapping_count": 1,
        "internal_to_can": {"gear": ["GearSig"]},
        "fullpath_to_can": {},
        "mappings": [],
    })
    (docs / "RCTA.md").write_text("STALE_FUNCTION_DOC", encoding="utf-8")
    config = {
        "paths": {"source_docs": str(docs)},
        "identity": {
            "variant_id": "gen6/byd_sc6h",
            "freshness": {"code_changed": True},
        },
    }
    query = DataQueryEngine(_FakeRouter(), config, tmp_path)
    context = query._build_knowledge_context("RCTA为什么未触发")
    assert "STALE_FUNCTION_DOC" not in context
    assert "Stale knowledge was excluded" in context

    store = _store_with_signals({"GearSig": [7, 7]})
    result = EngineeringInvestigator(
        config, tmp_path, codegraph_factory=lambda _: _FakeCodeGraph(),
    ).investigate(
        store, "RCTA为什么未触发", {"functions": ["RCTA"]}, _lookup("GearSig"),
    )
    assert result.condition_checks == []
    assert result.code_facts == []
    assert any("stale structured conditions excluded" in item for item in result.limitations)
    assert any("stale CodeGraph excluded" in item for item in result.limitations)
    store.close()


def test_fresh_variant_conditions_remain_available(tmp_path):
    docs = tmp_path / "docs"
    _write_knowledge(docs, [{
        "condition": "gear == 7", "variable": "gear", "can_signal": "GearSig",
        "operator": "==", "threshold": "7", "source": "logic.c:42",
    }])
    config = {
        "paths": {"source_docs": str(docs)},
        "identity": {
            "variant_id": "gen6/byd_sc6h",
            "freshness": {
                "code_changed": False, "constants_changed": False,
                "identity_changed": False,
            },
        },
    }
    store = _store_with_signals({"GearSig": [7]})
    result = EngineeringInvestigator(
        config, tmp_path, codegraph_factory=lambda _: _FakeCodeGraph(),
    ).investigate(
        store, "RCTA为什么未触发", {"functions": ["RCTA"]}, _lookup("GearSig"),
    )
    assert result.condition_checks[0].result == "satisfied"
    assert result.code_facts
    store.close()
