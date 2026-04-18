# CAN Signal Chain Reference

Auto-generated from RteComMapping.c (91 mappings)

## Vehicle Dynamics (车辆动力学)

| CAN Signal | Internal Variable | Full Path | Type | Transform |
|------------|-------------------|-----------|------|-----------|
| PushrodStauts | PushrodStauts | AdasStM.PushrodStauts | uint8 | 1:1 |
| PushrodStauts | egoBrakePedalPos | PEROutput.objEDRInfo.egoBrakePedalPos | uint8 | 1:1 |
| SteerWheelAng | steer_angle | VehcleInfoUpdate.steer_angle | float | 1:1 |
| SteerWheelAng | egoSteeringWheel | PEROutput.objEDRInfo.egoSteeringWheel | float | 1:1 |
| SteerWheelAngSign | steer_angle_sign | VehcleInfoUpdate.steer_angle_sign | uint8 | 1:1 |
| SteerWheelSpd | SteerWheelSpd | AdasStM.SteerWheelSpd | float | 1:1 |
| SteerWheelSpd | egoSteeringWheelSpd | PEROutput.objEDRInfo.egoSteeringWheelSpd | float | 1:1 |
| VCU_ActAccrPedlRat | AccPedPosDiag | AdasStM.AccPedPosDiag | float | 1:1 |
| VehLatAccel | lat_accel | VehcleInfoUpdate.lat_accel | float | 1:1 |
| VehLatAccelVld | lat_accel_valid | VehcleInfoUpdate.lat_accel_valid | uint8 | 1:1 |
| VehLgtAccel | long_accel | VehcleInfoUpdate.long_accel | float | 1:1 |
| VehLgtAccel | egoAx | PEROutput.objEDRInfo.egoAx | float | 1:1 |
| VehLgtAccelVld | long_accel_valid | VehcleInfoUpdate.long_accel_valid | uint8 | 1:1 |
| VehSpdVld_0x137 | actual_spd_valid | VehcleInfoUpdate.actual_spd_valid | uint8 | 1:1 |
| VehSpd_0x137 | actual_spd | VehcleInfoUpdate.actual_spd | float | *System_Kmh2ms |
| VehSpd_0x137 | egoVx | PEROutput.objEDRInfo.egoVx | float | *System_Kmh2ms |
| VehSpd_0x137 | egoMileage | PEROutput.objEDRInfo.egoMileage | float | *0.02 |
| VehYawRate | yaw_rate | VehcleInfoUpdate.yaw_rate | float | *System_R2D |
| VehYawRate | yaw_rate_sign | VehcleInfoUpdate.yaw_rate_sign | float | (ftmp > 0.0f) ? 0u : 1u |

## Function Switches (功能开关)

| CAN Signal | Internal Variable | Full Path | Type | Transform |
|------------|-------------------|-----------|------|-----------|
| DOWSwtReq | bDOWEnable | PERInputUpdate.adasEnable.bDOWEnable | uint8 | (u8tmp == 1) ? TRUE : FALSE |
| FCTABrkSwtReq | bFCTAEnable | PERInputUpdate.adasEnable.bFCTAEnable | uint8 | (u8tmp == 1) ? TRUE : FALSE |
| FCTABrkSwtReq | bFCTBEnable | PERInputUpdate.adasEnable.bFCTBEnable | uint8 | (u8tmp == 1) ? TRUE : FALSE |
| FCTABrkSwtReq | bFCTBEnable | PERInputUpdate.adasEnable.bFCTBEnable | uint8 | ((u8tmp == 1) ? TRUE : FALSE) |
| FCTASwtReq | bFCTAEnable | PERInputUpdate.adasEnable.bFCTAEnable | uint8 | (u8tmp == 1) ? TRUE : FALSE |
| LCASwtReq | bBSDEnable | PERInputUpdate.adasEnable.bBSDEnable | uint8 | (u8tmp == 1) ? TRUE : FALSE |
| LCASwtReq | bLCAEnable | PERInputUpdate.adasEnable.bLCAEnable | uint8 | (u8tmp == 1) ? TRUE : FALSE |
| RCTABrkSwtReq | bRCTAEnable | PERInputUpdate.adasEnable.bRCTAEnable | uint8 | (u8tmp == 1) ? TRUE : FALSE |
| RCTABrkSwtReq | bRCTBEnable | PERInputUpdate.adasEnable.bRCTBEnable | uint8 | (u8tmp == 1) ? TRUE : FALSE |
| RCTABrkSwtReq | bRCTBEnable | PERInputUpdate.adasEnable.bRCTBEnable | uint8 | ((u8tmp == 1) ? TRUE : FALSE) |
| RCTASwtReq | bRCTAEnable | PERInputUpdate.adasEnable.bRCTAEnable | uint8 | (u8tmp == 1) ? TRUE : FALSE |
| RCWSwtReq | bRCWEnable | PERInputUpdate.adasEnable.bRCWEnable | uint8 | (u8tmp == 1) ? TRUE : FALSE |

## Safety Systems (安全系统: AEB/ESP/...)

| CAN Signal | Internal Variable | Full Path | Type | Transform |
|------------|-------------------|-----------|------|-----------|
| AEBBAActv_0x137 | bAEBBAActiveFlg | PERInputCapture.DTCCode.bAEBBAActiveFlg | bool | bool |
| AEBIBActv_0x137 | bAEBIBActiveFlg | PERInputCapture.DTCCode.bAEBIBActiveFlg | bool | bool |
| BTCActv_0x137 | BTCActv | AdasStM.BTCActv | uint8 | 1:1 |
| BTCActv_RA_0x137 | BTCActv_RA | AdasStM.BTCActv_RA | uint8 | 1:1 |
| ESPFailSts_0x137 | Vld_ESPFailSts | Vld_ESPFailSts | uint8 | 1:1 |
| ESPFuncOffSts_0x137 | ESPFUN | AdasStM.ESPFUN | uint8 | 1:1 |
| ESP_DiagActv_0x137 | ESPDiagActv | AdasStM.ESPDiagActv | uint8 | 1:1 |
| ESP_MasterCylBrkPressVld_0x137 | Vld_ESP_MasterCylBrkPressVld | Vld_ESP_MasterCylBrkPressVld | uint8 | 1:1 |
| ESP_MasterCylBrkPress_0x137 | Vld_ESP_MasterCylBrkPress | Vld_ESP_MasterCylBrkPress | float | 1:1 |
| MSRActv_0x137 | MSRActv | AdasStM.MSRActv | uint8 | 1:1 |
| MSRActv_RA_0x137 | MSRActv_RA | AdasStM.MSRActv_RA | uint8 | 1:1 |
| PTCActv_0x137 | PTCActv | AdasStM.PTCActv | uint8 | 1:1 |
| PTCActv_RA_0x137 | PTCActv_RA | AdasStM.PTCActv_RA | uint8 | 1:1 |
| VCU_ActAccrPedlRat | egoAccelPedalPosDiagc | PEROutput.objEDRInfo.egoAccelPedalPosDiagc | float | 1:1 |
| VDCActv_0x137 | VDCActv | AdasStM.VDCActv | uint8 | 1:1 |

## Door & Body (车门/车身)

| CAN Signal | Internal Variable | Full Path | Type | Transform |
|------------|-------------------|-----------|------|-----------|
| DrvDoorSts | open_door_right_top | VehcleInfoUpdate.open_door_right_top | uint8 | 1:1 |
| DrvDoorSts | open_door_left_top | VehcleInfoUpdate.open_door_left_top | uint8 | 1:1 |
| DrvDoorSts | DrvDoorSts | AdasStM.DrvDoorSts | uint8 | 1:1 |
| LRDoorSts | open_door_left_bottom | VehcleInfoUpdate.open_door_left_bottom | uint8 | 1:1 |
| LRDoorSts | LRDoorSts | AdasStM.LRDoorSts | uint8 | 1:1 |
| LTurnLmpSwtSts | turn_light_left | VehcleInfoUpdate.turn_light_left | uint8 | 1:1 |
| PassengerDoorSts | open_door_left_top | VehcleInfoUpdate.open_door_left_top | uint8 | 1:1 |
| PassengerDoorSts | open_door_right_top | VehcleInfoUpdate.open_door_right_top | uint8 | 1:1 |
| PassengerDoorSts | PassengerDoorSts | AdasStM.PassengerDoorSts | uint8 | 1:1 |
| RRDoorSts | open_door_right_bottom | VehcleInfoUpdate.open_door_right_bottom | uint8 | 1:1 |
| RRDoorSts | RRDoorSts | AdasStM.RRDoorSts | uint8 | 1:1 |
| RSDS_Driver_LED_Sts | Vld_RSDS_Driver_LED_Sts | Vld_RSDS_Driver_LED_Sts | uint8 | 1:1 |
| RSDS_Pass_LED_Sts | Vld_RSDS_Pass_LED_Sts | Vld_RSDS_Pass_LED_Sts | uint8 | 1:1 |
| RTurnLmpSwtSts | turn_light_right | VehcleInfoUpdate.turn_light_right | uint8 | 1:1 |
| SysPowerMod | SysPowerMod | AdasStM.SysPowerMod | uint8 | 1:1 |
| SysPowerMod | SysPowerMod | SysselfTestMgr.SysPowerMod | uint8 | 1:1 |
| SysPowerModVld | SysPowerModVld | AdasStM.SysPowerModVld | uint8 | 1:1 |
| TrailerSts | TrailerSts | AdasStM.TrailerSts | uint8 | 1:1 |
| TrailerSts | TrailerSts | AdasStM.TrailerSts | uint8 | 0 |

## Wheel Speed (轮速)

| CAN Signal | Internal Variable | Full Path | Type | Transform |
|------------|-------------------|-----------|------|-----------|
| FLWheelDriveDirection_0x13B | Vld_FLWheelDriveDirection | Vld_FLWheelDriveDirection | uint8 | 1:1 |
| FLWheelSpdVld_0x13B | fl_whl_spd_valid | VehcleInfoUpdate.fl_whl_spd_valid | uint8 | 1:1 |
| FLWheelSpd_0x13B | fl_whl_spd | VehcleInfoUpdate.fl_whl_spd | float | 1:1 |
| FRWheelDriveDirection_0x13B | Vld_FRWheelDriveDirection | Vld_FRWheelDriveDirection | uint8 | 1:1 |
| FRWheelSpdVld_0x13B | fr_whl_spd_valid | VehcleInfoUpdate.fr_whl_spd_valid | uint8 | 1:1 |
| FRWheelSpd_0x13B | fr_whl_spd | VehcleInfoUpdate.fr_whl_spd | float | 1:1 |
| RLWheelDriveDirection_0x13B | Vld_RLWheelDriveDirection | Vld_RLWheelDriveDirection | uint8 | 1:1 |
| RLWheelSpdVld_0x13B | rl_whl_spd_valid | VehcleInfoUpdate.rl_whl_spd_valid | uint8 | 1:1 |
| RLWheelSpd_0x13B | rl_whl_spd | VehcleInfoUpdate.rl_whl_spd | float | 1:1 |
| RRWheelDriveDirection_0x13B | Vld_RRWheelDriveDirection | Vld_RRWheelDriveDirection | uint8 | 1:1 |
| RRWheelSpdVld_0x13B | rr_whl_spd_valid | VehcleInfoUpdate.rr_whl_spd_valid | uint8 | 1:1 |
| RRWheelSpd_0x13B | rr_whl_spd | VehcleInfoUpdate.rr_whl_spd | float | 1:1 |

## Other (其他)

| CAN Signal | Internal Variable | Full Path | Type | Transform |
|------------|-------------------|-----------|------|-----------|
| RCTA_B__L__TTC_0x301_RX | rcta_b_ttc_min | rcta_b_ttc_min | uint8 | 1:1 |
| RCTA_B__L__TTC_0x301_RX | has_valid_value | has_valid_value | uint8 | true |
| SAS_Sts | Vld_SAS_Sts | Vld_SAS_Sts | uint8 | 1:1 |
| TGS_LEVER | Vld_TGS_LEVER | Vld_TGS_LEVER | uint8 | 1:1 |
| Time_Day | egoDay | PEROutput.objEDRInfo.egoDay | uint8 | 1:1 |
| Time_Hour | egoHour | PEROutput.objEDRInfo.egoHour | uint8 | (u8tmp <= 23) ? u8tmp : 0 |
| Time_Minutes | egoMinute | PEROutput.objEDRInfo.egoMinute | uint8 | 1:1 |
| Time_Month | egoMonth | PEROutput.objEDRInfo.egoMonth | uint8 | 1:1 |
| Time_Second | egoSecond | PEROutput.objEDRInfo.egoSecond | uint8 | 1:1 |
| Time_Year_Right | egoYear | PEROutput.objEDRInfo.egoYear | uint8 | ((u8tmp_TL & 0xF) << 4) | (... |
| VCU_APedlPosVld | Vld_VCU_APedlPosVld | Vld_VCU_APedlPosVld | uint8 | 1:1 |
| VCU_ActAccrPedlRat | egoAccelPedalPos | PEROutput.objEDRInfo.egoAccelPedalPos | float | 1:1 |
| VehDynYawRateVld | yaw_rate_valid | VehcleInfoUpdate.yaw_rate_valid | uint8 | 1:1 |
| VehStandstill_0x137 | Vld_VehStandstill | Vld_VehStandstill | uint8 | 1:1 |
