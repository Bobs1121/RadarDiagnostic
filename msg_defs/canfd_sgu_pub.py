#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
XCP over CAN-FD:
Read selected internal signals and publish to egoCarInfo topic.
"""

import collections
import os
import re
import struct
import threading
import time

import rospy
from canlib import Frame, canlib

from arbe_msgs.msg import egoCarInfo


# (A2L measurement name, ROS msg field name, data type)
# dtype: f32 / u8 / s8
BASE_SIGNAL_SPECS = [
    ("g_egoCarAddInfo.actual_gear", "actual_gear", "u8"),
    ("g_egoCarAddInfo.carSpd", "car_spd", "f32"),
    ("g_egoCarAddInfo.carAccXR", "car_acc_xr", "f32"),
    ("g_egoCarAddInfo.yawRate", "yaw_rate", "f32"),
    ("fctaSystemState", "fcta_system_state", "u8"),
    ("fctbSystemState", "fctb_system_state", "u8"),
    ("AdasStM.SysPowerMod", "sys_power_mod", "u8"),
    ("PERInputUpdate.adasEnable.bFCTAEnable", "fcta_enable", "s8"),
    ("PERInputUpdate.adasEnable.bFCTBEnable", "fctb_enable", "s8"),
    ("AdasStM.SteerWheelSpd", "steer_wheel_spd", "f32"),
    ("AdasStM.AccPedPosDiag", "acc_ped_pos_diag", "u8"),
    ("AdasStM.TrailerSts", "trailer_sts", "u8"),
    ("AdasStM.ESPDiagActv", "esp_diag_actv", "u8"),
    ("VehcleInfoUpdate.steer_angle", "steer_angle", "f32"),
    ("AdasStM.ESPFUN", "esp_fun", "u8"),
    ("AdasStM.GetRDAFCTAErrorStatus", "get_rdafcta_error_status", "s8"),
    ("AdasStM.GetRDAFCTBErrorStatus", "get_rdafctb_error_status", "s8"),
    ("AdasStM.MSRActv", "msr_actv", "u8"),
    ("AdasStM.VDCActv", "vdc_actv", "u8"),
    ("AdasStM.PTCActv", "ptc_actv", "u8"),
    ("AdasStM.BTCActv", "btc_actv", "u8"),
    ("AdasStM.PTCActv_RA", "ptc_actv_ra", "u8"),
    ("AdasStM.BTCActv_RA", "btc_actv_ra", "u8"),
    ("AdasStM.MSRActv_RA", "msr_actv_ra", "u8"),
    ("AdasStM.DrvDoorSts", "drv_door_sts", "u8"),
    ("AdasStM.PassengerDoorSts", "passenger_door_sts", "u8"),
    ("AdasStM.LRDoorSts", "lr_door_sts", "u8"),
    ("AdasStM.RRDoorSts", "rr_door_sts", "u8"),
    ("PEROutput.adasWarning.bLeftFctaWarning", "left_fcta_warning", "u8"),
    ("PEROutput.adasWarning.bRightFctaWarning", "right_fcta_warning", "u8"),
    ("PERInputCapture.adasEnable.bFCTAEnable", "fcta_enable_capture", "s8"),
    ("PERInputCapture.adasEnable.bFCTBEnable", "fctb_enable_capture", "s8"),
]

TRC_OUT_SIGNAL_TEMPLATES = [
    ("objFctaWarningFlag", "obj_fcta_warning_flag", "s8"),
    ("objFctbWarningFlag", "obj_fctb_warning_flag", "s8"),
    ("distX", "dist_x", "f32"),
    ("distY", "dist_y", "f32"),
    ("velX", "vel_x", "f32"),
    ("leftFctaFlag", "left_fcta_flag", "s8"),
    ("rightFctaFlag", "right_fcta_flag", "s8"),
    ("fTTC", "ttc", "f32"),
    ("fDDCI", "ddci", "f32"),
]

SIGNAL_SPECS = list(BASE_SIGNAL_SPECS)
for trc_idx in range(4):
    for a2l_tail, field_tail, dtype in TRC_OUT_SIGNAL_TEMPLATES:
        SIGNAL_SPECS.append(
            (
                f"PEROutput.objInfo.trcOutData._{trc_idx}_.{a2l_tail}",
                f"trc_{trc_idx}_{field_tail}",
                dtype,
            )
        )


class EgoCarInfoNode:
    def __init__(self):
        rospy.init_node("ego_car_info_node", anonymous=True)

        # A2L
        self.a2lpath = rospy.get_param(
            "~a2l_path",
            os.path.join(os.path.dirname(__file__), "../config/CR60Light.A2L"),
        )

        # Basic params
        self.channel = rospy.get_param("~channel", 0)
        self.use_fd = rospy.get_param("~use_fd", True)
        self.use_brs = rospy.get_param("~use_brs", True)
        self.read_timeout_ms = rospy.get_param("~read_timeout_ms", 10)
        self.is_left = rospy.get_param("~is_left", False)
        self.topic_name = rospy.get_param("~topic_name", "/wf/ego_car_info/parsed")
        default_radar_label = "front_left" if self.is_left else "front_right"
        self.radar_label = rospy.get_param("~radar_label", default_radar_label)

        # XCP IDs
        self.xcp_left_tx_id = rospy.get_param("~xcp_left_tx_id", 0x0F3)
        self.xcp_left_rx_id = rospy.get_param("~xcp_left_rx_id", 0x6F3)
        self.xcp_right_tx_id = rospy.get_param("~xcp_right_tx_id", 0x0F2)
        self.xcp_right_rx_id = rospy.get_param("~xcp_right_rx_id", 0x6F2)

        # F5 max length
        self.f5_max_len = max(1, min(int(rospy.get_param("~f5_max_len", 0x3F)), 0x3F))

        # Open CAN
        self.ch = self._open_can_bus_initial()

        # RX queue
        self._rx_queues = {
            self.xcp_left_rx_id: collections.deque(maxlen=512),
            self.xcp_right_rx_id: collections.deque(maxlen=512),
        }
        self._rx_lock = threading.Lock()
        self._stop_rx = threading.Event()
        self._rx_thread = threading.Thread(target=self._rx_worker, daemon=True)
        self._rx_thread.start()

        self._left_req_lock = threading.Lock()
        self._right_req_lock = threading.Lock()

        # Parse A2L and resolve addresses
        self.load_a2l_file()
        self.signal_addrs = {}
        self.missing_a2l_signals = []
        for a2l_name, _, _ in SIGNAL_SPECS:
            addr = self.get_ecu_address(a2l_name)
            self.signal_addrs[a2l_name] = addr
            if addr is None:
                self.missing_a2l_signals.append(a2l_name)

        if self.missing_a2l_signals:
            rospy.logwarn(
                "A2L missing %d/%d required signals. They will publish default values. missing=%s",
                len(self.missing_a2l_signals),
                len(SIGNAL_SPECS),
                ",".join(self.missing_a2l_signals),
            )
        else:
            rospy.loginfo("A2L check OK: all %d required signals found.", len(SIGNAL_SPECS))

        # ROS publisher
        self.pub_ego = rospy.Publisher(self.topic_name, egoCarInfo, queue_size=10)
        rospy.loginfo(
            "egoCarInfo topic=%s side=%s radar_label=%s",
            self.topic_name,
            "left" if self.is_left else "right",
            self.radar_label,
        )

    # ---------------- A2L & CAN ----------------
    def load_a2l_file(self):
        try:
            with open(self.a2lpath, "r", encoding="utf-8", errors="ignore") as f:
                self.a2l_content = f.read()
            rospy.loginfo("Successfully loaded A2L file: %s", self.a2lpath)
            return True
        except Exception as exc:
            self.a2l_content = ""
            rospy.logerr("Error loading A2L file: %s", exc)
            return False

    def get_ecu_address(self, symbol_name):
        if not self.a2l_content:
            rospy.logwarn("A2L content not loaded")
            return None
        pattern = (
            rf"/begin MEASUREMENT\s+{re.escape(symbol_name)}.*?"
            rf"ECU_ADDRESS\s+(0x[0-9A-Fa-f]+).*?/end MEASUREMENT"
        )
        match = re.search(pattern, self.a2l_content, re.DOTALL | re.IGNORECASE)
        if match:
            return int(match.group(1), 16)
        return None

    def _open_can_bus_initial(self):
        flags = canlib.canOPEN_ACCEPT_VIRTUAL
        if self.use_fd:
            flags |= canlib.canOPEN_CAN_FD
        ch = canlib.openChannel(self.channel, flags)
        if self.use_fd:
            ch.setBusParams(canlib.canFD_BITRATE_500K_80P)
            ch.setBusParamsFd(canlib.canFD_BITRATE_2M_80P)
        else:
            ch.setBusParams(canlib.canBITRATE_500K)
        ch.busOn()
        return ch

    def _rx_worker(self):
        while not self._stop_rx.is_set():
            try:
                frame = self.ch.read(self.read_timeout_ms)
                with self._rx_lock:
                    dq = self._rx_queues.get(frame.id)
                    if dq is not None:
                        dq.append(frame)
            except canlib.canNoMsg:
                continue

    def _flush_rx_queue(self, rx_id):
        with self._rx_lock:
            dq = self._rx_queues.get(rx_id)
            if dq is not None:
                dq.clear()

    def _wait_for_frame(self, rx_id, predicate, timeout_sec=0.2):
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            frame = None
            with self._rx_lock:
                dq = self._rx_queues.get(rx_id)
                if dq and dq:
                    frame = dq.popleft()
            if frame is None:
                time.sleep(0.001)
                continue
            if predicate(frame):
                return frame
        return None

    def _side_lock(self, is_left):
        return self._left_req_lock if is_left else self._right_req_lock

    def send_can_frame(self, tx_id, data_bytes):
        flags = canlib.MessageFlag.STD
        if self.use_fd:
            flags |= canlib.MessageFlag.FDF
            if self.use_brs:
                flags |= canlib.MessageFlag.BRS
        frame = Frame(id_=tx_id, data=bytes(data_bytes), flags=flags)
        self.ch.write(frame)

    def send_xcp_command(self, cmd, is_left):
        tx_id = self.xcp_left_tx_id if is_left else self.xcp_right_tx_id
        self.send_can_frame(tx_id, cmd)

    def send_and_wait(self, cmd, is_left, expect_pred, timeout_sec=0.2):
        rx_id = self.xcp_left_rx_id if is_left else self.xcp_right_rx_id
        lock = self._side_lock(is_left)
        with lock:
            self._flush_rx_queue(rx_id)
            self.send_xcp_command(cmd, is_left)
            return self._wait_for_frame(rx_id, expect_pred, timeout_sec)

    def build_read_memory_cmd(self, address):
        cmd = bytearray()
        cmd.append(0xF6)  # SET_MTA
        cmd.append(0x00)
        cmd.append(0x00)
        cmd.append(0x60)
        cmd += struct.pack("<I", address)
        return cmd

    def read_memory_chunked(self, addr, total_len, is_left):
        cmd_f6 = self.build_read_memory_cmd(addr)
        ok = self.send_and_wait(
            cmd_f6,
            is_left,
            lambda f: len(f.data) >= 1 and f.data[0] == 0xFF,
            timeout_sec=0.2,
        )
        if ok is None:
            rospy.logwarn("[XCP] F6 response failed addr=0x%08X", addr)
            return None

        out = bytearray()
        remaining = total_len
        while remaining > 0:
            this_len = min(remaining, self.f5_max_len)
            cmd_f5 = bytearray([0xF5, this_len])
            resp = self.send_and_wait(
                cmd_f5,
                is_left,
                lambda f: (len(f.data) >= 1 and f.data[0] == 0xFE)
                or len(f.data) >= (1 + this_len),
                timeout_sec=0.2,
            )
            if resp is None or resp.data[0] == 0xFE:
                rospy.logwarn("[XCP] F5 read failed addr=0x%08X", addr)
                return None
            out.extend(bytes(resp.data[1 : 1 + this_len]))
            remaining -= this_len
        return bytes(out)

    # ---------------- signal read ----------------
    def _read_f32(self, addr):
        if addr is None:
            return 0.0
        data = self.read_memory_chunked(addr, 4, self.is_left)
        if not data or len(data) < 4:
            return 0.0
        try:
            return struct.unpack("<f", data[:4])[0]
        except struct.error:
            return 0.0

    def _read_u8(self, addr):
        if addr is None:
            return 0
        data = self.read_memory_chunked(addr, 1, self.is_left)
        if not data or len(data) < 1:
            return 0
        return int(data[0])

    def _read_s8(self, addr):
        if addr is None:
            return 0
        data = self.read_memory_chunked(addr, 1, self.is_left)
        if not data or len(data) < 1:
            return 0
        return struct.unpack("<b", bytes([data[0]]))[0]

    def _read_by_dtype(self, addr, dtype):
        if dtype == "f32":
            return self._read_f32(addr)
        if dtype == "s8":
            return self._read_s8(addr)
        return self._read_u8(addr)

    def read_ego_signals(self):
        msg = egoCarInfo()
        msg.header.stamp = rospy.Time.now()
        msg.header.frame_id = self.radar_label

        for a2l_name, field_name, dtype in SIGNAL_SPECS:
            value = self._read_by_dtype(self.signal_addrs.get(a2l_name), dtype)
            try:
                setattr(msg, field_name, value)
            except AttributeError:
                rospy.logerr_throttle(
                    5.0,
                    "egoCarInfo missing field '%s'. Rebuild messages after updating egoCarInfo.msg",
                    field_name,
                )
        return msg

    # ---------------- connect/run ----------------
    def connect(self):
        retries = 10
        timeout_sec = 0.2
        side = "左" if self.is_left else "右"
        for _ in range(retries):
            try:
                cmd = bytes([0xFF, 0x00])  # CONNECT
                resp = self.send_and_wait(
                    cmd,
                    self.is_left,
                    expect_pred=lambda f: len(f.data) >= 1 and f.data[0] == 0xFF,
                    timeout_sec=timeout_sec,
                )
                if resp is not None:
                    rospy.loginfo("%s雷达 XCP 握手成功", side)
                    return True
            except Exception as exc:
                rospy.logwarn("%s雷达握手失败: %s", side, exc)
        rospy.logerr("XCP 握手失败，请检查硬件连接")
        return False

    def run(self):
        rate = rospy.Rate(rospy.get_param("~rate_hz", 15))
        if not self.connect():
            return
        while not rospy.is_shutdown():
            msg = self.read_ego_signals()
            self.pub_ego.publish(msg)
            rate.sleep()


if __name__ == "__main__":
    try:
        node = EgoCarInfoNode()
        node.run()
    except rospy.ROSInterruptException:
        pass
