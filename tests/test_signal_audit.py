# -*- coding: utf-8 -*-
"""
Tests for engines/signal_audit — key-chain signal audit (M10).

Covers the deterministic enum/contract audit against a synthetic
FrameStore + DBCLoader:

* ADCMode_UI_Status sustained Reserved(3) must be flagged as anomaly
* FCTA_FCTB_Status_S all-Invalid with old-UI mode must be explained by
  the "old UI does not echo" contract (not treated as radar-missing)
* absent 0x32B new-UI signal must be reported as 缺席
* generic extract_signal works for arbitrary user-selected signals

Run with::

    pytest tests/test_signal_audit.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from engines.signal_audit import SIGNAL_AUDIT_CONTRACT, SignalAuditEngine  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────
# Fakes — minimal FrameStore/DBCLoader duck types.
# ─────────────────────────────────────────────────────────────────────────

class FakeStore:
    """In-memory signal timeline store (FrameStore duck type)."""

    def __init__(self, timelines: dict[tuple[int, str], list[dict]]) -> None:
        self._timelines = timelines
        self._inventory: dict[str, dict] = {}
        for (can_id, name), rows in timelines.items():
            self._inventory[name] = {
                "can_id": can_id,
                "message_name": f"MSG_0x{can_id:X}",
            }

    def get_signal_inventory(self) -> list[dict]:
        out = []
        seen_ids: set[int] = set()
        for (can_id, _name), _rows in self._timelines.items():
            if can_id in seen_ids:
                continue
            seen_ids.add(can_id)
            signals = [
                name for (cid, name) in self._timelines if cid == can_id
            ]
            out.append({
                "can_id": can_id,
                "message_name": f"MSG_0x{can_id:X}",
                "signals": signals,
            })
        return out

    def query_signal_timeline(self, can_id: int, signal_name: str) -> list[dict]:
        return list(self._timelines.get((can_id, signal_name), []))


class FakeDbc:
    """DBCLoader duck type with signal choices and reverse lookup."""

    def __init__(self, choices_by_signal: dict[str, dict], by_id: dict[int, str]) -> None:
        self._choices = choices_by_signal
        self._by_id = by_id
        self._signal_to_msg = {
            name: (can_id, f"MSG_0x{can_id:X}")
            for can_id, names in by_id.items()
            for name in names
        }

    def get_signal_choices(self, can_id: int, signal_name: str) -> dict | None:
        return self._choices.get(signal_name)

    def find_message_by_signal(self, signal_name: str) -> tuple[int, str] | None:
        return self._signal_to_msg.get(signal_name)


# ── DBC choices mirroring the BYD-UKE PublicCAN value tables ────────────

_CHOICES = {
    "ADCMode_UI_Status": {0: "Invalid", 1: "Old UI", 2: "New UI", 3: "Reserved"},
    "FCTA_Enable_S": {0: "Invalid", 1: "Switchoff", 2: "Switchon", 3: "Reserved"},
    "FCTB_Enable_S": {0: "Invalid", 1: "Switchoff", 2: "Switchon", 3: "Reserved"},
    "FCTA_FCTB_Enable_S": {
        0: "invaild", 1: "close", 2: "earlywarning", 3: "brake",
        4: "EarlywarningAndBrake",
    },
    "FCTA_FCTB_Status_S": {
        0: "Invalid", 1: "FCTA_OFF_FCTB_OFF", 2: "FCTA_ON_FCTB_OFF",
        3: "FCTA_OFF_FCTB_ON", 4: "FCTA_ON_FCTB_ON", 5: "fault",
    },
    "Sts_FCTA_S": {0: "OFF", 1: "Standby", 2: "Active", 3: "Fault"},
    "Sts_FCTB_S": {0: "OFF", 1: "Standby", 2: "Active", 3: "Fault"},
}

_IDS = {
    0x432: ["ADCMode_UI_Status"],
    0x4EF: ["FCTA_Enable_S", "FCTB_Enable_S"],
    0x32B: ["FCTA_FCTB_Enable_S"],
    0x2CA: ["FCTA_FCTB_Status_S", "Sts_FCTA_S", "Sts_FCTB_S"],
}


def _make_store(ui_mode: int | None = 3, echo_all_invalid: bool = True) -> FakeStore:
    """Synthetic EM2E-like recording.

    Old-UI chain (0x4EF off-press bursts, no 0x32B, no status echo).
    """
    timelines: dict[tuple[int, str], list[dict]] = {
        (0x432, "ADCMode_UI_Status"): (
            [{"timestamp": i * 0.5, "value": ui_mode} for i in range(10)]
            if ui_mode is not None else []
        ),
        (0x4EF, "FCTA_Enable_S"): [
            {"timestamp": 0.0, "value": 1},
            {"timestamp": 0.1, "value": 1},
            {"timestamp": 3.5, "value": 1},
        ],
        (0x4EF, "FCTB_Enable_S"): [
            {"timestamp": 0.6, "value": 1},
            {"timestamp": 4.1, "value": 1},
        ],
        (0x2CA, "Sts_FCTA_S"): [
            {"timestamp": i * 0.05, "value": 1} for i in range(20)
        ],
        (0x2CA, "Sts_FCTB_S"): [
            {"timestamp": i * 0.05, "value": 1} for i in range(20)
        ],
    }
    if echo_all_invalid:
        timelines[(0x2CA, "FCTA_FCTB_Status_S")] = [
            {"timestamp": i * 0.05, "value": 0} for i in range(20)
        ]
    return FakeStore(timelines)


# ─────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────

class TestSignalAuditEngine:
    def test_adcmode_reserved_flag(self):
        store = _make_store(ui_mode=3)
        dbc = FakeDbc(_CHOICES, _IDS)
        result = SignalAuditEngine().audit(store, dbc)

        assert any(
            e.name == "ADCMode_UI_Status" and e.is_anomalous
            for e in result["entries"]
        )
        assert any("持续发送异常枚举 [3]" in a for a in result["anomalies"])
        assert "ADCMode_UI_Status" in result["markdown"]

    def test_old_ui_echo_contract_not_misread(self):
        """Old-UI: all-Invalid echo must NOT be flagged as radar-missing."""
        store = _make_store(ui_mode=3, echo_all_invalid=True)
        dbc = FakeDbc(_CHOICES, _IDS)
        result = SignalAuditEngine().audit(store, dbc)

        echo = next(e for e in result["entries"] if e.name == "FCTA_FCTB_Status_S")
        assert not echo.is_anomalous
        assert any("旧 UI 不回传状态" in n for n in echo.notes)
        assert any("不构成雷达未响应证据" in n for n in echo.notes)

    def test_new_ui_echo_missing_is_not_contract_explained(self):
        """New-UI (mode=2): all-Invalid echo stays unexplained, not contracted."""
        store = _make_store(ui_mode=2, echo_all_invalid=True)
        dbc = FakeDbc(_CHOICES, _IDS)
        result = SignalAuditEngine().audit(store, dbc)

        echo = next(e for e in result["entries"] if e.name == "FCTA_FCTB_Status_S")
        assert not echo.is_anomalous
        assert any("若为新 UI 则回传缺失" in n for n in echo.notes)

    def test_missing_new_ui_chain_signal_reported_absent(self):
        """0x32B absent on the bus -> 缺席 (not an anomaly by itself)."""
        store = _make_store(ui_mode=3)
        dbc = FakeDbc(_CHOICES, _IDS)
        result = SignalAuditEngine().audit(store, dbc)

        enable32b = next(
            e for e in result["entries"] if e.name == "FCTA_FCTB_Enable_S"
        )
        assert not enable32b.present
        assert not enable32b.is_anomalous
        assert enable32b.frame_count == 0

    def test_illegal_enum_value_detected(self):
        """A value outside the DBC value table must be flagged."""
        store = _make_store(ui_mode=7)  # 7 not in ADCMode choices {0..3}
        dbc = FakeDbc(_CHOICES, _IDS)
        result = SignalAuditEngine().audit(store, dbc)

        mode = next(e for e in result["entries"] if e.name == "ADCMode_UI_Status")
        assert any("非法枚举值 7" in a for a in mode.anomalies)

    def test_extract_signal_generic(self):
        """Generic extraction works for arbitrary signals (user queries)."""
        store = _make_store(ui_mode=1)
        dbc = FakeDbc(_CHOICES, _IDS)
        engine = SignalAuditEngine()
        out = engine.extract_signal(store, "FCTA_Enable_S", dbc)
        assert out["present"] is True
        assert out["observed_values"] == {1: 3}
        assert out["legal_choices"][1] == "Switchoff"

        missing = engine.extract_signal(store, "NoSuchSignal", dbc)
        assert missing["present"] is False
        assert missing["frame_count"] == 0

    def test_contract_table_wellformed(self):
        """Every contract entry has the fields the engine relies on."""
        for spec in SIGNAL_AUDIT_CONTRACT:
            assert spec["name"]
            assert spec["role"]
            assert spec["expect"]
            assert spec["contract"]
            assert isinstance(spec.get("anomaly_values", []), list)
