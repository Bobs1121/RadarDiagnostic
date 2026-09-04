# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse

from ai.modules.base import BaseModule, ModuleResult
from ai.modules.signal_bridge import SignalBridgeModule


def _make_mapping() -> dict:
    return {
        "mapping_count": 2,
        "mappings": [
            {
                "can_signal": "VehSpd",
                "internal_var": "VehSpd",
                "internal_full_path": "g_vehicle.VehSpd",
            },
            {
                "can_signal": "WarnCAN",
                "internal_var": "WarnFlag",
                "internal_full_path": "rte.prefix.WarnFlag",
            },
        ],
        "internal_to_can": {
            "VehSpd": ["VehSpd"],
            "WarnFlag": ["WarnCAN"],
        },
        "can_to_internal": {
            "VehSpd": ["VehSpd"],
            "WarnCAN": ["WarnFlag"],
        },
        "fullpath_to_can": {
            "g_vehicle.VehSpd": ["VehSpd"],
            "rte.prefix.WarnFlag": ["WarnCAN"],
        },
    }


def test_signal_bridge_is_base_module_with_name():
    assert issubclass(SignalBridgeModule, BaseModule)
    assert SignalBridgeModule.name == "signal-bridge"


def test_signal_bridge_mapping_summary_from_injected_data():
    mod = SignalBridgeModule(
        mapping=_make_mapping(),
        chains={"struct_aliases": {"g_alias": "rte.prefix"}},
        output_mapping={"signal_to_expr": {"TEMP_CAN": ["l_temp_u8 + 1"]}},
        output_aliases={"bFctbKeepBrakeFlg": ["CR_BrkgReq"]},
    )

    res = mod.safe_run(mode="mapping-summary")

    assert isinstance(res, ModuleResult)
    assert res.ok is True
    payload = res.data["data"]
    assert payload["mapping_count"] == 2
    assert payload["read_signal_count"] == 2
    assert payload["struct_alias_count"] == 1
    assert payload["write_signal_count"] == 1
    assert payload["expr_identifier_count"] >= 1
    assert payload["output_alias_count"] == 1
    assert payload["sources"]["mapping"] == "injected"


def test_signal_bridge_internal_to_can_uses_struct_aliases():
    mod = SignalBridgeModule(
        mapping=_make_mapping(),
        chains={"struct_aliases": {"g_alias": "rte.prefix"}},
    )

    res = mod.safe_run(mode="internal-to-can", query="g_alias.WarnFlag")

    assert res.ok is True
    assert res.data["data"]["matches"] == ["WarnCAN"]


def test_signal_bridge_internal_to_can_uses_output_mapping_expr_index():
    mod = SignalBridgeModule(
        mapping={},
        output_mapping={"signal_to_expr": {"TEMP_CAN": ["l_temp_u8 + 1"]}},
    )

    res = mod.safe_run(mode="internal-to-can", query="l_temp_u8")

    assert res.ok is True
    assert res.data["data"]["matches"] == ["TEMP_CAN"]


def test_signal_bridge_internal_to_can_uses_output_aliases():
    mod = SignalBridgeModule(
        mapping={},
        output_aliases={"bFctbKeepBrakeFlg": ["CR_BrkgReq"]},
    )

    res = mod.safe_run(mode="internal-to-can", query="bFctbKeepBrakeFlg")

    assert res.ok is True
    assert res.data["data"]["matches"] == ["CR_BrkgReq"]


def test_signal_bridge_can_to_internal_is_case_insensitive():
    mod = SignalBridgeModule(mapping=_make_mapping())

    res = mod.safe_run(mode="can-to-internal", query="warncan")

    assert res.ok is True
    assert res.data["data"]["matches"] == ["WarnFlag"]


def test_signal_bridge_function_outputs_uses_static_lookup():
    mod = SignalBridgeModule()

    res = mod.safe_run(mode="function-outputs", query="FCTA")

    assert res.ok is True
    assert "FCTA_Warn" in res.data["data"]["matches"]


def test_signal_bridge_function_outputs_prefers_active_tx_mapping():
    mod = SignalBridgeModule(
        output_mapping={
            "signal_to_expr": {
                "Sts_FCTA_S": ["AdasStM.fctaSysState"],
                "RRadar_FCTA_Warning_Right_S": ["(AdasStM.Frontright_FCTA == 2) ? 1u:0u"],
            }
        }
    )

    res = mod.safe_run(mode="function-outputs", query="FrontCrossTrafficAlertAndBrake")

    assert res.ok is True
    assert res.data["data"]["matches"] == ["Sts_FCTA_S", "RRadar_FCTA_Warning_Right_S"]
    assert "FCTA_Warn" not in res.data["data"]["matches"]


def test_signal_bridge_missing_mapping_fails_gracefully():
    mod = SignalBridgeModule()

    res = mod.safe_run(mode="can-to-internal", query="VehSpd")

    assert isinstance(res, ModuleResult)
    assert res.ok is False
    assert "no reverse CAN mapping available" in res.message


def test_signal_bridge_cli_wiring():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers()
    SignalBridgeModule.register_cli(sub)
    args = parser.parse_args(
        ["signal-bridge", "--mode", "mapping-summary", "--output-dir", "docs"],
    )

    assert args.mode == "mapping-summary"
    assert args._module_cls is SignalBridgeModule
    mod = SignalBridgeModule.from_cli_args(args)
    assert isinstance(mod, SignalBridgeModule)
