# -*- coding: utf-8 -*-
"""
Tests for the signal-mapping chain fixes (A-group refactor).

Covers:
* dotted-target ReadSignal parsing (18 warning/brake signals restored)
* write-side (Tx) mapping extraction with dynamic rte_file discovery
* variant-truth output signal resolution (real DBC names over legacy table)
* get_output_signals_for_function fallback behaviour

Run with::

    pytest tests/test_signal_mapper_tx.py -v
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from engines.signal_mapper import (  # noqa: E402
    extract_output_signal_mapping,
    _parse_rte_com_mapping,
    _parse_rte_write_mapping,
    get_output_signals_for_function,
)

# ── Synthetic sources mirroring BYD_UKE RteComMapping_Rx.c / Tx.c ───────

_RX_SAMPLE = """\
void RteComMapping_RxRunnable_BodySignal(void)
{
    uint8 u8tmp = 0;
    RteComMapping_ReadSignal(IPB_Vehicle_Speed_S)(&ftmp);
    VehcleInfoUpdate.actual_spd = ftmp / 3.6f;

    RteComMapping_ReadSignal(FCTA_Enable_S)(&u8tmp);
    g_ADAS_Input_HMIReq_st.FCTASelReq_u8 = u8tmp;

    // Dotted-target reads: warning/brake signals land directly on struct members
    RteComMapping_ReadSignal(RRL_LBSDAndLCAWrnng)(&AdasStM.BSD_LCA_warningReqleft);
    RteComMapping_ReadSignal(RFL_LFCTAWrnng)(&AdasStM.FCTA_warningReqLeft);
    RteComMapping_ReadSignal(RFL_FCTBReq)(&AdasStM.RSDS_FLBrkgReq);
    RteComMapping_ReadSignal(RFL_FCTASysSts)(&AdasStM.FLFCTA_St);
}

void RteComMapping_RxRunnable_FuncSignal(void)
{
    uint8 u8tmp = 0;
    RteComMapping_ReadSignal(FCTB_Enable_S)(&u8tmp);
    g_ADAS_Input_HMIReq_st.FCTBSelReq_u8 = u8tmp;
}
"""

_TX_SAMPLE = """\
void RteComMapping_TxRunnable_FuncSignal(void)
{
    RteComMapping_WriteSignal(Sts_FCTA_S)(AdasStM.fctaSysState);
    RteComMapping_WriteSignal(Sts_FCTB_S)(AdasStM.fctbSysState);
    RteComMapping_WriteSignal(RRadar_FCTA_Warning_Left_S)((AdasStM.Frontleft_FCTA == 1) ? 1u:0u);
    RteComMapping_WriteSignal(FCTBBrkReq_S)(l_temp_u8_FCTB);
    RteComMapping_WriteSignal(FCTA_FCTB_Status_S)(AdasStM.FCTS_Status);
}

void RteComMapping_TxRunnable_Other(void)
{
    RteComMapping_WriteSignal(RCW_Warning_S)(AdasStM.RCW_Warn);
}
"""


class TestDottedTargetReadMapping:
    def test_dotted_targets_parsed(self):
        mappings = _parse_rte_com_mapping(_RX_SAMPLE)
        by_signal = {m["can_signal"]: m for m in mappings}
        # Previously-missing warning/brake signals must now resolve.
        assert by_signal["RRL_LBSDAndLCAWrnng"]["internal_full_path"] == \
            "AdasStM.BSD_LCA_warningReqleft"
        assert by_signal["RFL_LFCTAWrnng"]["internal_full_path"] == \
            "AdasStM.FCTA_warningReqLeft"
        assert by_signal["RFL_FCTBReq"]["internal_full_path"] == "AdasStM.RSDS_FLBrkgReq"
        assert by_signal["RFL_FCTASysSts"]["internal_full_path"] == "AdasStM.FLFCTA_St"

    def test_plain_targets_still_work(self):
        mappings = _parse_rte_com_mapping(_RX_SAMPLE)
        by_signal = {m["can_signal"]: m for m in mappings}
        assert by_signal["FCTA_Enable_S"]["internal_full_path"] == \
            "g_ADAS_Input_HMIReq_st.FCTASelReq_u8"
        assert by_signal["IPB_Vehicle_Speed_S"]["transform"] != "passthrough"


class TestWriteMappingParsing:
    def test_write_mapping_without_void_prefix(self):
        """Real Tx.c calls omit the (void) prefix; both forms must parse."""
        mappings = _parse_rte_write_mapping(_TX_SAMPLE)
        by_signal = {m["can_signal"]: m for m in mappings}
        assert by_signal["Sts_FCTA_S"]["expression"] == "AdasStM.fctaSysState"
        assert by_signal["RRadar_FCTA_Warning_Left_S"]["expression"] == \
            "(AdasStM.Frontleft_FCTA == 1) ? 1u:0u"
        assert by_signal["FCTBBrkReq_S"]["expression"] == "l_temp_u8_FCTB"
        assert by_signal["FCTA_FCTB_Status_S"]["expression"] == "AdasStM.FCTS_Status"

    def test_explicit_missing_mapping_does_not_scan_another_coem(self, tmp_path: Path):
        source_root = tmp_path / "source"
        other_tx = source_root / "coem" / "BYD_SC6H" / "components" / "AswIf" / "ASW_ComMapping" / "RteComMapping_Tx.c"
        other_tx.parent.mkdir(parents=True)
        other_tx.write_text(_TX_SAMPLE, encoding="utf-8")
        docs_dir = tmp_path / "docs"

        result = extract_output_signal_mapping(
            source_root,
            docs_dir,
            rte_file=r"coem\GWM_B26\components\AswIf\ASW_IN\RteComMapping.c",
        )

        assert result["selection_status"] == "explicit_not_found"
        assert result["mappings"] == []
        assert result["signal_to_expr"] == {}
        cached = json.loads((docs_dir / "output_mapping.json").read_text(encoding="utf-8"))
        assert cached["source_files"] == []


class TestVariantTruthOutputSignals:
    _TX = {
        "Sts_FCTA_S": ["AdasStM.fctaSysState"],
        "Sts_FCTB_S": ["AdasStM.fctbSysState"],
        "RRadar_FCTA_Warning_Left_S": ["(AdasStM.Frontleft_FCTA == 1) ? 1u:0u"],
        "RRadar_FCTA_Warning_Right_S": ["(AdasStM.Frontright_FCTA == 2) ? 1u:0u"],
        "FCTBBrkReq_S": ["l_temp_u8_FCTB"],
        "FCTA_FCTB_Status_S": ["AdasStM.FCTS_Status"],
        "RCW_Warning_S": ["AdasStM.RCW_Warn"],
    }

    def test_fcta_outputs_use_real_names(self):
        out = get_output_signals_for_function(
            "FCTA", tx_signals=self._TX, dbc_signals=set(self._TX),
        )
        assert "RRadar_FCTA_Warning_Left_S" in out
        assert "Sts_FCTA_S" in out
        assert "FCTA_FCTB_Status_S" in out
        # Legacy GWM-era names must NOT be returned when real names exist.
        assert "FCTA_Warn" not in out

    def test_rcw_keeps_legacy_name_when_no_variant_match(self):
        # RCW's write references AdasStM.RCW_Warn -> matches expression scan.
        out = get_output_signals_for_function(
            "RCW", tx_signals=self._TX, dbc_signals=set(self._TX),
        )
        assert "RCW_Warning_S" in out

    def test_fallback_without_variant_data(self):
        out = get_output_signals_for_function("FCTA")
        assert out == ["FCTA_Warn", "FCTA_B_FuncSts", "CR_FCTA_Resp",
                       "CR_FCTB_Resp", "CR_ErrSts", "CR_BliSts"]
