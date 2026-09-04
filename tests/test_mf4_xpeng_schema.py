# -*- coding: utf-8 -*-
"""Tests for Xpeng RCC1010 MF4 channel classification."""
from __future__ import annotations

import pytest

from parsers.mf4_parser import classify_xpeng_mf4_channels, is_xpeng_data_channel


class TestClassifyXpengMf4Channels:
    """Test classify_xpeng_mf4_channels categorizes signal names correctly."""

    def test_radar_output_signals(self):
        channels = [
            "BYD_5R1V_RadarRearcorner_V2_5.RRL_RCTBTrgtDcl",
            "BYD_5R1V_RadarRearcorner_V2_5.RRR_BSDSelReq",
        ]
        result = classify_xpeng_mf4_channels(channels)
        assert result["radar_output"] == channels

    def test_can_public_signals(self):
        channels = [
            "CR_PublicCAN_Matrix_V1_2_0_20260402.RCTB_Enable_S",
            "CR_PublicCAN_Matrix_V1_2_0_20260402.Radar_RCTA_Warn_Right_S",
        ]
        result = classify_xpeng_mf4_channels(channels)
        assert result["can_public"] == channels

    def test_fused_objects_signals(self):
        channels = [
            "FusedObjects.DynamicObjCount",
            "per_fusedObjects.DynamicObjCount",
        ]
        result = classify_xpeng_mf4_channels(channels)
        assert result["fused_objects"] == channels

    def test_lane_boundary_signals(self):
        channels = [
            "CR60LT_L.LaneExists",
            "CR60LT_LS.LaneCurvature",
        ]
        result = classify_xpeng_mf4_channels(channels)
        assert result["lane_boundary"] == channels

    def test_failure_diag_signals(self):
        channels = [
            "FailureReactionStates.RadarFailure",
            "DsmState.ServiceState",
            "Outspec.RadarSensor",
        ]
        result = classify_xpeng_mf4_channels(channels)
        assert result["failure_diag"] == channels

    def test_unknown_signals_go_to_unknown(self):
        channels = [
            "ABS_Active",
            "CarSpeed",
            "YawRate",
        ]
        result = classify_xpeng_mf4_channels(channels)
        assert set(result["unknown"]) == set(channels)

    def test_empty_list(self):
        result = classify_xpeng_mf4_channels([])
        assert result == {}

    def test_categories_returned_as_dict_without_empty_keys(self):
        channels = [
            "BYD_5R1V_RadarRearcorner_V2_5.RRL_RCTBTrgtDcl",
            "ABS_Active",
        ]
        result = classify_xpeng_mf4_channels(channels)
        assert "radar_output" in result
        assert "unknown" in result
        # Empty categories should be excluded
        assert "fused_objects" not in result


class TestIsXpengDataChannel:
    """Test is_xpeng_data_channel filters non-data channels."""

    def test_data_channels(self):
        assert is_xpeng_data_channel("RCTB_Enable_S") is True
        assert is_xpeng_data_channel("CarSpeed") is True
        assert is_xpeng_data_channel("ABS_Active") is True

    def test_skip_channels(self):
        assert is_xpeng_data_channel("t") is False
        assert is_xpeng_data_channel("BusChannel") is False
        assert is_xpeng_data_channel("CAN_DataFrame") is False
        assert is_xpeng_data_channel("isADASSyncSeqCtr") is False
        assert is_xpeng_data_channel("CR_PublicCAN_Matrix_V1_2_0_20260402.Child_ID_1C6_S") is False
