# -*- coding: utf-8 -*-
"""
BagProvider — ROS Bag 数据源 Provider（V4 P2）。

封装现有 :class:`parsers.bag_parser.BagParser` 的 bag 解析逻辑：
- 读取 bag 文件，逐帧写入 FrameStore.bag_frames；
- 复用 case_loader 既有的 wfAutosarData / wfObjectMsg 深度解析
  （radar_objects / radar_debug），避免逻辑重复；
- **占位 CAN 信号标 invalid**：bag 回放产生的 PublicCan*Signals 消息
  （``/front/signals``、``/rear/signals``）在源端用 ``signal_valid``
  数组标记每个信号是否真实有效。本 Provider 把这些消息里的信号值
  连同 ``signal_valid`` 一起写入 can_frames，并在 provenance.extra
  记录占位信号统计，供 :class:`engines.data_quality.DataQualityAuditor`
  识别 is_placeholder。

本 Provider 不替代 case_loader 的编排（topic discovery、warning events
等仍在 case_loader），而是把"bag 文件 → store + meta + 溯源"这一段
抽成可独立调用、可测的单元。
"""
from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .base import DataProvider

if TYPE_CHECKING:
    from parsers.frame_store import FrameStore

# PublicCan 占位消息 topic（来自 scripts/_validate_fields.py / _scan_ctx.py）
# 这些 topic 由 common_can_signal_publisher 发布，signal_valid 数组按
# generated_signal_map.SIGNALS 顺序排列；signal_valid[i]==0 表示该信号
# 从未被真实 CAN 帧更新过，其字段值是类型默认零值/上次残留——占位数据。
_PUBLICCAN_TOPICS = {"/front/signals", "/rear/signals"}
_PUBLICCAN_MSGTYPES = {
    "common_can_signal_publisher/msg/PublicCanFrontSignals",
    "common_can_signal_publisher/msg/PublicCanRearSignals",
}


class BagProvider(DataProvider):
    """ROS Bag (.bag) 数据源 Provider。"""

    source_kind = "bag"

    def load(self, path: Path, store: "FrameStore") -> dict:
        """解析单个 .bag 文件，写入 store，返回 metadata 片段。

        复用 BagParser 的基础帧迭代 + 深度解析；对 PublicCan 占位消息
        走专用路径，把 signal_valid 暴露到 signals_json 里供后续审计。
        """
        from parsers.bag_parser import BagParser, discover_radar_topics

        if not path.exists():
            self.ctx.status("parse", f"Bag not found: {path}")
            return {}

        parser = BagParser(path)
        meta = parser.get_metadata()

        # PublicCan 占位信号统计（写入 provenance.extra）
        placeholder_signal_count = 0
        publiccan_msg_count = 0

        for frame in parser.iter_frames():
            store.insert_bag_frame(frame)

            # ── PublicCan 占位消息：把 signal_valid 标记进 signals_json ──
            if frame.topic in _PUBLICCAN_TOPICS:
                decoded = self._decode_publiccan_placeholder(frame.raw_bytes)
                if decoded is not None:
                    publiccan_msg_count += 1
                    invalid = sum(1 for v in decoded.get("signal_valid", []) if v == 0)
                    placeholder_signal_count += invalid
                    # 作为"伪 CAN 帧"写入 can_frames，便于下游统一审计。
                    # can_id 用 topic hash 区分；signals 同时含值与 valid 标记。
                    store.insert_can_frame(_PublicCanCanFrame(
                        timestamp=frame.timestamp_ns / 1e9,
                        datetime_str="",
                        channel=decoded.get("channel", 0),
                        can_id=_publiccan_topic_can_id(frame.topic),
                        can_id_hex=f"0x{_publiccan_topic_can_id(frame.topic):X}",
                        dlc=0,
                        message_name=frame.topic,
                        raw_hex=frame.raw_bytes[:64].hex(" "),
                        signals=decoded,
                    ))

        # 记录溯源
        self._record(
            file=path.name,
            parser="BagProvider/BagParser",
            message_count=meta.get("message_count", 0),
            size_mb=self._file_size_mb(path),
            duration_sec=meta.get("duration_sec", 0.0),
            extra={
                "topics": list(meta.get("topics", {}).keys()),
                "publiccan_msg_count": publiccan_msg_count,
                "publiccan_placeholder_signals": placeholder_signal_count,
            },
        )
        return meta

    def provenance(self) -> list[dict]:
        return [p.to_dict() for p in self._provenance]

    # ── PublicCan 占位消息解码 ──────────────────────────────────────
    # 复用 scripts/_decode_publiccan.py 的 ROS1 布局，但只提取
    # signal_valid 数组 + 标量字段，不依赖外部 msgdef 文件（轻量）。
    @staticmethod
    def _decode_publiccan_placeholder(raw: bytes) -> dict | None:
        """从 PublicCan*Signals 原始字节中提取 signal_valid 数组。

        ROS1 序列化布局（见 scripts/_decode_publiccan.py）：
          header: seq(u32) stamp_sec(u32) stamp_nsec(u32) frame_id(string)
          channel: u8
          received_frame_count: u32
          decoded_frame_count: u32
          signal_valid: u32 len + uint8[]
          signal_age_ms: u32 len + float32[]
          后续为 DBC 衍生标量字段（本函数不解析，只标记 valid）。
        """
        if len(raw) < 30:
            return None
        out: dict[str, Any] = {}
        off = 0
        try:
            # header
            off += 12  # seq + stamp_sec + stamp_nsec
            fid_len = struct.unpack_from("<I", raw, off)[0]; off += 4
            off += fid_len  # skip frame_id bytes
            off += 1  # channel
            off += 8  # received_frame_count + decoded_frame_count
            n_valid = struct.unpack_from("<I", raw, off)[0]; off += 4
            if n_valid < 0 or off + n_valid > len(raw):
                return None
            out["signal_valid"] = list(struct.unpack_from(f"<{n_valid}B", raw, off))
            off += n_valid
            # signal_age_ms array
            if off + 4 <= len(raw):
                n_age = struct.unpack_from("<I", raw, off)[0]; off += 4
                if n_age >= 0 and off + n_age * 4 <= len(raw):
                    out["signal_age_ms"] = list(struct.unpack_from(f"<{n_age}f", raw, off))
            out["placeholder_signal_count"] = sum(1 for v in out["signal_valid"] if v == 0)
            return out
        except (struct.error, IndexError):
            return None


# ── 辅助：把 PublicCan topic 映射到稳定 can_id（避免与真实 CAN ID 冲突）──
# 用 0x7Fx 段（真实 CAN ID 通常 < 0x700），仅用于 store 内部占位标记。
_PUBLICCAN_TOPIC_CAN_ID = {
    "/front/signals": 0x7F0,
    "/rear/signals": 0x7F1,
}


def _publiccan_topic_can_id(topic: str) -> int:
    return _PUBLICCAN_TOPIC_CAN_ID.get(topic, 0x7FF)


# ── 适配器：让 insert_can_frame 能直接吃 PublicCan 帧 ──────────────────
# FrameStore.insert_can_frame 期望一个有 timestamp/datetime_str/.../signals
# 属性的对象（见 parsers/frame_store.py:158-172）。PublicCan 已解码为
# dict，这里包一层 dataclass 适配，字段与 CanFrame 保持一致（去掉了
# insert_can_frame 不读取的 raw_data/is_extended/is_fd，避免误导）。
import dataclasses as _dc


@_dc.dataclass
class _PublicCanCanFrame:
    timestamp: float
    datetime_str: str
    channel: int
    can_id: int
    can_id_hex: str
    dlc: int
    message_name: str
    raw_hex: str
    signals: dict
