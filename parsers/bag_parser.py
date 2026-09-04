# -*- coding: utf-8 -*-
"""
ROS Bag V1 parser with structured message extraction.
Handles arbe_msgs and standard ROS message types.

Deep-parses wfAutosarData (object list + debug/ego/ADAS/BLD from outputData),
wfObjectMsg (full wfSObj fields), and warning_status_raw (semantic byte map).
"""
import math
import struct
from pathlib import Path
from typing import Iterator, Optional
from dataclasses import dataclass, field
from rosbags.rosbag1 import Reader

# ---------------------------------------------------------------------------
# Constants ported from cr60_light_convert_radar_dataset
# ---------------------------------------------------------------------------
_OBJ_TRANS_OFFSET = 8
_OBJ_STRUCT_SIZE = 36
_OBJ_STRUCT_FMT = "<hhHHhBBBbbbbbbbBBBxhhhhHh"
_MAX_OBJ_COUNT = 68
_FIXED_LENGTH = 728
_DEBUG_INFO_SIZE = 144
_DEBUG_INFO_OFFSET = _FIXED_LENGTH - _DEBUG_INFO_SIZE

# Topic suffix → radar_id (FR=1, FL=2, RL=3, RR=4)
TOPIC_RADAR_ID = {
    "/wf/corner_radar/lgu_data_1": 1,
    "/wf/corner_radar/lgu_data_2": 2,
    "/wf/corner_radar/lgu_data_3": 3,
    "/wf/corner_radar/lgu_data_4": 4,
    "/wf/objectlist_1": 1,
    "/wf/objectlist_2": 2,
    "/wf/objectlist_3": 3,
    "/wf/objectlist_4": 4,
}

# warning_status_raw byte index → semantic name (from kWarningSignalMap)
WARNING_SIGNAL_MAP = {
    0: "radar_id", 1: "BSD_L", 2: "BSD_R", 3: "LCA_L", 4: "LCA_R",
    5: "DOW_L", 6: "DOW_R", 7: "RCW", 8: "RCTA_L", 9: "RCTA_R",
    10: "RCTB_L", 11: "RCTB_R", 12: "FCTA_L", 13: "FCTA_R",
    14: "FCTB_L", 15: "FCTB_R",
}

# wfSObj serialized size: int64 + floats/ints + nested Slam types + warnings
_WFSOBJ_SIZE = 185
_WFSOBJ_FMT = (
    "<"    # little-endian
    "q"    # int64   ID
    "f"    # float32 obj_conf
    "H"    # uint16  obj_class
    "f"    # float32 class_conf
    "6f"   # arbeTSlamPos (x,y,z,dx,dy,dz)
    "5f"   # arbeTSlamVelocity (x_dot,y_dot,dx_dot,dy_dot,velocity)
    "8f"   # arbeTSlamBox (scale_x/y/z, unc x/y/z, orient_unc, orient)
    "4f"   # azimuth, elevation, power, rcs
    "I"    # uint32  age
    "H"    # uint16  last_frame_update
    "9f"   # RxReal,RyReal,RzReal,Spd,Ang,Rng,Vx,Vy,Vz
    "B"    # uint8   objID
    "4f"   # distX, distY, velAbsX, velAbsY
    "2f"   # fTTC, fDDCI
    "8b"   # 8× int8 warning flags
)


@dataclass
class BagFrame:
    """A single parsed frame from the bag file."""
    timestamp_ns: int
    topic: str
    msg_type: str
    data_size: int
    raw_bytes: bytes
    fields: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Topic auto-discovery
# ---------------------------------------------------------------------------

# Keywords that indicate radar-related topics
_RADAR_TOPIC_KEYWORDS = [
    "wf", "radar", "corner", "object", "target", "lgu_data",
    "objectlist", "autosar", "ego_car", "warning_status",
]

# Suffix pattern for radar ID extraction: _1, _2, _3, _4
import re as _re
_RADAR_ID_SUFFIX_RE = _re.compile(r"_(\d+)$")


def discover_radar_topics(bag_path: str | Path) -> dict:
    """Auto-discover radar-related topics from a bag file.

    Returns a dict mapping topic name to discovery metadata:
        {
            "/wf/corner_radar/lgu_data_1": {
                "radar_id": 1,
                "msg_type": "arbe_msgs/msg/wfAutosarData",
                "type": "wfa",          # wfa | wfo | ego | warning | other
                "keyword_match": ["wf", "radar", "lgu_data"],
            },
            ...
        }
    """
    from rosbags.rosbag1 import Reader

    result = {}
    bag = Path(bag_path)
    if not bag.exists():
        return result

    with Reader(bag) as reader:
        for name, info in reader.topics.items():
            name_lower = name.lower()
            matched_keywords = [k for k in _RADAR_TOPIC_KEYWORDS if k in name_lower]
            if not matched_keywords:
                continue

            # Determine topic type
            if "lgu_data" in name_lower or "autosar" in info.msgtype.lower():
                topic_type = "wfa"
            elif "objectlist" in name_lower or "wfobject" in info.msgtype.lower():
                topic_type = "wfo"
            elif "ego_car" in name_lower:
                topic_type = "ego"
            elif "warning" in name_lower:
                topic_type = "warning"
            else:
                topic_type = "other"

            # Extract radar_id from topic suffix (_1, _2, _3, _4)
            suffix_match = _RADAR_ID_SUFFIX_RE.search(name)
            radar_id = int(suffix_match.group(1)) if suffix_match else 0

            result[name] = {
                "radar_id": radar_id,
                "msg_type": info.msgtype,
                "type": topic_type,
                "keyword_match": matched_keywords,
            }

    return result


class BagParser:
    """Parse ROS bag files and extract structured per-frame data."""

    TOPIC_ALIASES = {
        "/wf/corner_radar/lgu_data_1": "radar_1",
        "/wf/corner_radar/lgu_data_2": "radar_2",
        "/wf/corner_radar/lgu_data_3": "radar_3",
        "/wf/corner_radar/lgu_data_4": "radar_4",
        "/wf/objectlist_1": "objects_1",
        "/wf/objectlist_2": "objects_2",
        "/wf/objectlist_3": "objects_3",
        "/wf/objectlist_4": "objects_4",
        "/wf/ego_car_info/front_left/parsed": "ego_front_left",
        "/wf/ego_car_info/front_right/parsed": "ego_front_right",
        "/corner_radar/warning_status_raw": "warning_status",
        "/cv_camera_0/image_raw/compressed": "camera_0",
        "/cv_camera_2/image_raw/compressed": "camera_2",
    }

    def __init__(self, bag_path: str | Path):
        self.bag_path = Path(bag_path)
        if not self.bag_path.exists():
            raise FileNotFoundError(f"Bag file not found: {self.bag_path}")
        self._metadata = None

    def get_metadata(self) -> dict:
        """Get bag file metadata without iterating all messages."""
        if self._metadata:
            return self._metadata
        with Reader(self.bag_path) as reader:
            topics = {}
            for name, info in reader.topics.items():
                topics[name] = {
                    "msg_type": info.msgtype,
                    "msg_count": info.msgcount,
                    "alias": self.TOPIC_ALIASES.get(name, name),
                }
            self._metadata = {
                "file": self.bag_path.name,
                "size_mb": self.bag_path.stat().st_size / 1024 / 1024,
                "duration_sec": reader.duration / 1e9,
                "start_ns": reader.start_time,
                "end_ns": reader.end_time,
                "message_count": reader.message_count,
                "topic_count": len(reader.topics),
                "topics": topics,
            }
        return self._metadata

    def iter_frames(
        self,
        topics: Optional[list[str]] = None,
        skip_images: bool = True,
    ) -> Iterator[BagFrame]:
        """
        Iterate over all messages, yielding structured BagFrame objects.

        Args:
            topics: Filter to specific topics. None = all topics.
            skip_images: If True, skip compressed image topics for performance.
        """
        image_topics = {
            "/cv_camera_0/image_raw/compressed",
            "/cv_camera_2/image_raw/compressed",
        }
        with Reader(self.bag_path) as reader:
            for conn, timestamp, rawdata in reader.messages():
                if skip_images and conn.topic in image_topics:
                    continue
                if topics and conn.topic not in topics:
                    continue

                frame = BagFrame(
                    timestamp_ns=timestamp,
                    topic=conn.topic,
                    msg_type=conn.msgtype,
                    data_size=len(rawdata),
                    raw_bytes=rawdata,
                )
                frame.fields = self._decode_fields(conn.topic, conn.msgtype, rawdata)
                yield frame

    @staticmethod
    def _normalize_msgtype(msg_type: str) -> str:
        """Normalize both 'pkg/Type' and 'pkg/msg/Type' to 'pkg/msg/Type'."""
        parts = msg_type.split("/")
        if len(parts) == 2:
            return f"{parts[0]}/msg/{parts[1]}"
        return msg_type

    def _decode_fields(self, topic: str, msg_type: str, raw: bytes) -> dict:
        """Attempt to decode raw bytes into structured fields based on msg type."""
        norm = self._normalize_msgtype(msg_type)
        try:
            if norm == "std_msgs/msg/UInt8MultiArray":
                return self._decode_uint8_multi_array(raw)
            elif norm == "arbe_msgs/msg/egoCarInfo":
                return self._decode_ego_car_info(raw)
            elif norm == "arbe_msgs/msg/wfObjectMsg":
                return self._decode_object_msg(raw)
            elif norm == "arbe_msgs/msg/wfAutosarData":
                return self._decode_autosar_data(raw, topic)
        except Exception:
            pass
        return {"raw_hex": raw[:64].hex(" ")}

    def _decode_uint8_multi_array(self, raw: bytes) -> dict:
        """Decode std_msgs/UInt8MultiArray with semantic warning signal names."""
        offset = 0
        if len(raw) < 4:
            return {"raw_hex": raw[:64].hex(" ")}
        dim_count = struct.unpack_from("<I", raw, offset)[0]
        offset += 4
        for _ in range(dim_count):
            if offset + 4 > len(raw):
                break
            label_len = struct.unpack_from("<I", raw, offset)[0]
            offset += 4 + label_len + 8
        if offset + 4 <= len(raw):
            offset += 4  # data_offset
        if offset + 4 > len(raw):
            return {"raw_hex": raw[:64].hex(" ")}
        data_len = struct.unpack_from("<I", raw, offset)[0]
        offset += 4
        data_bytes = raw[offset:offset + data_len]

        result = {
            "warning_bytes": list(data_bytes),
            "warning_hex": data_bytes.hex(" "),
            "byte_count": len(data_bytes),
        }
        # Semantic decoding using kWarningSignalMap from cr60_light_arbe
        if len(data_bytes) >= 16:
            result["radar_id"] = data_bytes[0]
            for idx in range(1, 16):
                name = WARNING_SIGNAL_MAP[idx]
                result[name] = int(data_bytes[idx])
            result["any_warning_active"] = any(data_bytes[i] != 0 for i in range(1, 16))
        return result

    # Field layout from egoCarInfo.msg (after std_msgs/Header)
    # (field_name, struct_format) — 'B'=uint8, 'b'=int8, '<f'=float32
    _EGO_FIELDS = [
        ("actual_gear", "B"),
        ("car_spd", "<f"),
        ("car_acc_xr", "<f"),
        ("yaw_rate", "<f"),
        ("fcta_system_state", "B"),
        ("fctb_system_state", "B"),
        ("sys_power_mod", "B"),
        ("fcta_enable", "b"),
        ("fctb_enable", "b"),
        ("steer_wheel_spd", "<f"),
        ("acc_ped_pos_diag", "B"),
        ("trailer_sts", "B"),
        ("esp_diag_actv", "B"),
        ("steer_angle", "<f"),
        ("esp_fun", "B"),
        ("get_rdafcta_error_status", "b"),
        ("get_rdafctb_error_status", "b"),
        ("msr_actv", "B"),
        ("vdc_actv", "B"),
        ("ptc_actv", "B"),
        ("btc_actv", "B"),
        ("ptc_actv_ra", "B"),
        ("btc_actv_ra", "B"),
        ("msr_actv_ra", "B"),
        ("drv_door_sts", "B"),
        ("passenger_door_sts", "B"),
        ("lr_door_sts", "B"),
        ("rr_door_sts", "B"),
        ("left_fcta_warning", "B"),
        ("right_fcta_warning", "B"),
        ("fcta_enable_capture", "b"),
        ("fctb_enable_capture", "b"),
    ]
    # 4 tracks × 9 fields each
    _TRC_FIELDS = [
        ("obj_fcta_warning_flag", "b"),
        ("obj_fctb_warning_flag", "b"),
        ("dist_x", "<f"),
        ("dist_y", "<f"),
        ("vel_x", "<f"),
        ("left_fcta_flag", "b"),
        ("right_fcta_flag", "b"),
        ("ttc", "<f"),
        ("ddci", "<f"),
    ]

    def _decode_ego_car_info(self, raw: bytes) -> dict:
        """Decode arbe_msgs/egoCarInfo using exact field layout from .msg definition."""
        fields = {}
        if len(raw) < 30:
            return {"raw_hex": raw[:64].hex(" ")}
        offset = 0

        # ROS1 Header: seq(u32) + stamp.secs(u32) + stamp.nsecs(u32) + frame_id(string)
        fields["seq"] = struct.unpack_from("<I", raw, offset)[0]; offset += 4
        fields["stamp_sec"] = struct.unpack_from("<I", raw, offset)[0]; offset += 4
        fields["stamp_nsec"] = struct.unpack_from("<I", raw, offset)[0]; offset += 4
        if offset + 4 <= len(raw):
            fid_len = struct.unpack_from("<I", raw, offset)[0]; offset += 4
            if offset + fid_len <= len(raw):
                fields["frame_id"] = raw[offset:offset + fid_len].decode("utf-8", errors="replace")
                offset += fid_len

        # Base fields
        for name, fmt in self._EGO_FIELDS:
            sz = struct.calcsize(fmt)
            if offset + sz > len(raw):
                break
            fields[name] = struct.unpack_from(fmt, raw, offset)[0]
            if fmt == "<f":
                fields[name] = round(fields[name], 4)
            offset += sz

        # 4 tracks
        for i in range(4):
            for name, fmt in self._TRC_FIELDS:
                sz = struct.calcsize(fmt)
                if offset + sz > len(raw):
                    break
                val = struct.unpack_from(fmt, raw, offset)[0]
                if fmt == "<f":
                    val = round(val, 4)
                fields[f"trc_{i}_{name}"] = val
                offset += sz

        return fields

    def _decode_object_msg(self, raw: bytes) -> dict:
        """
        Decode arbe_msgs/wfObjectMsg with full wfSObj fields.
        Extracts objID, position, velocity, TTC, DDCI, and all 8 warning flags.
        """
        fields = {}
        if len(raw) < 30:
            return {"raw_hex": raw.hex(" ")}
        offset = 0
        fields["seq"] = struct.unpack_from("<I", raw, offset)[0]; offset += 4
        fields["stamp_sec"] = struct.unpack_from("<I", raw, offset)[0]; offset += 4
        fields["stamp_nsec"] = struct.unpack_from("<I", raw, offset)[0]; offset += 4
        if offset + 4 <= len(raw):
            fid_len = struct.unpack_from("<I", raw, offset)[0]; offset += 4
            if offset + fid_len <= len(raw):
                fields["frame_id"] = raw[offset:offset + fid_len].decode("utf-8", errors="replace")
                offset += fid_len

        # ObjectsBuffer is a ROS array: uint32 count + count × wfSObj
        if offset + 4 > len(raw):
            return fields
        obj_count = struct.unpack_from("<I", raw, offset)[0]
        offset += 4
        fields["object_count"] = obj_count

        objects = []
        sz = _WFSOBJ_SIZE
        fmt = _WFSOBJ_FMT
        for i in range(min(obj_count, _MAX_OBJ_COUNT)):
            if offset + sz > len(raw):
                break
            vals = struct.unpack_from(fmt, raw, offset)
            offset += sz
            # vals layout: ID, obj_conf, obj_class, class_conf,
            #   pos(6), vel(5), box(8),
            #   azimuth,elevation,power,rcs, age,last_frame_update,
            #   RxReal..Vz(9), objID, distX,distY,velAbsX,velAbsY, fTTC,fDDCI,
            #   bsd,lca,dow,rcw,rcta,rctb,fcta,fctb
            # Index map for _WFSOBJ_FMT (53 values total):
            #  0=ID, 1=obj_conf, 2=obj_class, 3=class_conf,
            #  4-9=SlamPos, 10-14=SlamVelocity, 15-22=SlamBox,
            #  23-26=azimuth/elevation/power/rcs, 27=age, 28=last_frame_update,
            #  29-37=RxReal..Vz, 38=objID, 39-42=distX/distY/velAbsX/velAbsY,
            #  43=fTTC, 44=fDDCI, 45-52=warning flags (bsd/lca/dow/rcw/rcta/rctb/fcta/fctb)
            obj = {
                "ID": vals[0],
                "obj_class": vals[2],
                "age": vals[27],
                "objID": vals[38],
                "distX": round(vals[39], 4),
                "distY": round(vals[40], 4),
                "velAbsX": round(vals[41], 4),
                "velAbsY": round(vals[42], 4),
                "fTTC": round(vals[43], 4),
                "fDDCI": round(vals[44], 4),
                "objBsdWarningFlag": vals[45],
                "objLcaWarningFlag": vals[46],
                "objDowWarningFlag": vals[47],
                "objRcwWarningFlag": vals[48],
                "objRctaWarningFlag": vals[49],
                "objRctbWarningFlag": vals[50],
                "objFctaWarningFlag": vals[51],
                "objFctbWarningFlag": vals[52],
                "pos_x": round(vals[4], 4),
                "pos_y": round(vals[5], 4),
                "vel_x": round(vals[10], 4),
                "vel_y": round(vals[11], 4),
                "Rng": round(vals[34], 4),
                "Spd": round(vals[32], 4),
            }
            has_data = (
                abs(obj["distX"]) > 0.01
                or abs(obj["distY"]) > 0.01
                or any(vals[k] != 0 for k in range(45, 53))
            )
            if has_data:
                objects.append(obj)

        fields["objects"] = objects
        fields["active_object_count"] = len(objects)
        return fields

    def _decode_autosar_data(self, raw: bytes, topic: str = "") -> dict:
        """
        Deep-decode arbe_msgs/wfAutosarData.
        Navigates the ROS serialization to extract outputData, then parses:
        - Object list (36 bytes each, from C struct layout)
        - Debug info (144 bytes: ego, calibration, ADAS enables, BLD)
        """
        fields = {}
        if len(raw) < 30:
            return {"raw_hex": raw.hex(" ")}
        offset = 0
        # --- ROS Header ---
        fields["seq"] = struct.unpack_from("<I", raw, offset)[0]; offset += 4
        fields["stamp_sec"] = struct.unpack_from("<I", raw, offset)[0]; offset += 4
        fields["stamp_nsec"] = struct.unpack_from("<I", raw, offset)[0]; offset += 4
        if offset + 4 <= len(raw):
            fid_len = struct.unpack_from("<I", raw, offset)[0]; offset += 4
            if offset + fid_len <= len(raw):
                fields["frame_id"] = raw[offset:offset + fid_len].decode("utf-8", errors="replace")
                offset += fid_len

        # --- wfAutosarData fields after header ---
        if offset + 10 > len(raw):
            return fields
        wfa_frame_id, lgu_num, sgu_num, padding, bytelength = struct.unpack_from(
            "<HHBBI", raw, offset
        )
        offset += 10
        fields["wfa_frame_id"] = wfa_frame_id
        fields["lgu_num"] = lgu_num
        fields["sgu_num"] = sgu_num

        # Skip uintData array (uint32 len + N×uint32)
        if offset + 4 > len(raw):
            return fields
        arr_len = struct.unpack_from("<I", raw, offset)[0]; offset += 4
        offset += arr_len * 4
        # Skip floatData array (uint32 len + N×float32)
        if offset + 4 > len(raw):
            return fields
        arr_len = struct.unpack_from("<I", raw, offset)[0]; offset += 4
        offset += arr_len * 4
        # Read outputData array (uint32 len + N×uint8)
        if offset + 4 > len(raw):
            return fields
        output_len = struct.unpack_from("<I", raw, offset)[0]; offset += 4
        if offset + output_len > len(raw):
            return fields
        output_data = raw[offset:offset + output_len]
        fields["payload_size"] = output_len

        # --- Deep parse outputData (the assembled radar payload) ---
        radar_id = TOPIC_RADAR_ID.get(topic, 0)
        fields["radar_id"] = radar_id

        # Parse objects from outputData
        objs = self._parse_wfa_objects(output_data, sgu_num)
        if objs:
            fields["objects"] = objs
            fields["active_object_count"] = len(objs)

        # Parse debug info (ego, ADAS enables, BLD)
        dbg = self._parse_wfa_debug(output_data)
        if dbg:
            fields["debug_info"] = dbg

        return fields

    @staticmethod
    def _parse_wfa_objects(payload: bytes, sgu_num: int) -> list[dict]:
        """Parse object list from wfAutosarData outputData using C struct layout."""
        max_from_payload = max(0, (len(payload) - _OBJ_TRANS_OFFSET) // _OBJ_STRUCT_SIZE)
        count = min(int(sgu_num), _MAX_OBJ_COUNT, max_from_payload)
        objects = []
        for i in range(count):
            off = _OBJ_TRANS_OFFSET + i * _OBJ_STRUCT_SIZE
            if off + _OBJ_STRUCT_SIZE > len(payload):
                break
            vals = struct.unpack_from(_OBJ_STRUCT_FMT, payload, off)
            (dist_x, dist_y, length, width, yaw_ang,
             obj_id, obj_type, dyn_flg,
             bsd, lca, dow, rcw, rcta, rctb, fcta, fctb,
             refer_pt, life_cycle,
             vel_x, vel_y, vel_abs_x, vel_abs_y, f_ttc, f_ddci) = vals

            has_data = (
                abs(dist_x) > 50 or abs(dist_y) > 50  # > 0.5m in centimeters
                or any(v != 0 for v in (bsd, lca, dow, rcw, rcta, rctb, fcta, fctb))
                or life_cycle > 3
            )
            if not has_data:
                continue

            objects.append({
                "obj_id": int(obj_id),
                "obj_class": int(obj_type),
                "life_cycle": int(life_cycle),
                "dist_x": round(dist_x / 100.0, 2),
                "dist_y": round(dist_y / 100.0, 2),
                "vel_x": round(vel_x / 100.0, 2),
                "vel_y": round(vel_y / 100.0, 2),
                "vel_abs_x": round(vel_abs_x / 100.0, 2),
                "vel_abs_y": round(vel_abs_y / 100.0, 2),
                "ttc": round(f_ttc / 100.0, 2),
                "ddci": round(f_ddci / 100.0, 2),
                "length": round(length / 100.0, 2),
                "width": round(width / 100.0, 2),
                "bsd_flag": int(bsd),
                "lca_flag": int(lca),
                "dow_flag": int(dow),
                "rcw_flag": int(rcw),
                "rcta_flag": int(rcta),
                "rctb_flag": int(rctb),
                "fcta_flag": int(fcta),
                "fctb_flag": int(fctb),
            })
        return objects

    @staticmethod
    def _parse_wfa_debug(payload: bytes) -> Optional[dict]:
        """Parse 144-byte debug info from wfAutosarData outputData tail."""
        if len(payload) < _DEBUG_INFO_OFFSET + _DEBUG_INFO_SIZE:
            return None
        off = _DEBUG_INFO_OFFSET
        out: dict = {}

        # Ego car info
        ego: dict = {}
        (ego["actual_spd"], ego["yaw_rate"],
         ego["lat_accel"], ego["long_accel"]) = struct.unpack_from("<ffff", payload, off)
        off += 16
        (ego["yaw_rate_sign"], ego["actual_gear"],
         ego["turn_light_left"], ego["turn_light_right"],
         ego["open_door_left_top"], ego["open_door_right_top"],
         ego["open_door_left_bottom"], ego["open_door_right_bottom"],
         ego["actual_spd_valid"], ego["yaw_rate_valid"],
         ego["lat_accel_valid"], ego["long_accel_valid"],
         ) = struct.unpack_from("<12B", payload, off)
        off += 12
        (ego["steer_angle"], ego["fl_whl_spd"], ego["fr_whl_spd"],
         ego["rl_whl_spd"], ego["rr_whl_spd"]) = struct.unpack_from("<fffff", payload, off)
        off += 20
        (ego["fl_whl_spd_valid"], ego["rr_whl_spd_valid"],
         ego["fr_whl_spd_valid"], ego["rl_whl_spd_valid"],
         ego["steer_angle_sign"], ego["wiper_gear"],
         ) = struct.unpack_from("<6B", payload, off)
        off += 6 + 2  # +2 for padding bytes
        (ego["mileage"],) = struct.unpack_from("<I", payload, off)
        off += 4
        for k, v in ego.items():
            if isinstance(v, float):
                ego[k] = round(v, 4)
        out["ego"] = ego

        # Calibration
        calib: dict = {}
        (calib["egoCarSpdCoef"], calib["finalAziResult"],
         calib["finalEleResult"]) = struct.unpack_from("<fff", payload, off)
        off += 12
        out["calibration"] = {k: round(v, 4) for k, v in calib.items()}

        # ADAS enable flags
        adas_raw = struct.unpack_from("<12B", payload, off)
        off += 12
        out["adas_enables"] = {
            "bsd": bool(adas_raw[0]), "lca": bool(adas_raw[1]),
            "dow": bool(adas_raw[2]), "rcw": bool(adas_raw[3]),
            "rcta": bool(adas_raw[4]), "rctb": bool(adas_raw[5]),
            "fcta": bool(adas_raw[6]), "fctb": bool(adas_raw[7]),
            "tgu": bool(adas_raw[8]), "elk": bool(adas_raw[9]),
            "ess": bool(adas_raw[10]), "user_define": bool(adas_raw[11]),
        }

        # BLD (blockage detection)
        bld: dict = {}
        (bld["LGUDeleteNum"], bld["noDymObjFlg"], bld["noObjFlg"]) = \
            struct.unpack_from("<HBB", payload, off)
        off += 4
        off += 16  # ChanPowRatio 8×uint16
        bld_wf, bld_pct, bld_score = struct.unpack_from("<Bbh", payload, off)
        off += 4
        bld["bld_warning_flag"] = bld_wf
        bld["bld_percent"] = bld_pct
        bld["bld_score"] = bld_score
        out["bld"] = bld

        return out

    def get_warning_timeline(self) -> list[dict]:
        """Extract warning_status_raw as a timeline for quick overview."""
        timeline = []
        for frame in self.iter_frames(topics=["/corner_radar/warning_status_raw"]):
            entry = {
                "timestamp_ns": frame.timestamp_ns,
                "timestamp_sec": frame.timestamp_ns / 1e9,
            }
            entry.update(frame.fields)
            timeline.append(entry)
        return timeline
