#!/usr/bin/env python3
import os
import threading

import cantools
import rospy
from canlib import canlib

from common_can_signal_publisher.msg import PublicCanSignals
from generated_signal_map import SIGNALS


class PublicCanSignalPublisher:
    def __init__(self):
        rospy.init_node('public_can_signal_publisher', anonymous=True)

        self.channel = int(rospy.get_param('~channel', 0))
        self.dbc_path = rospy.get_param(
            '~dbc_path',
            os.path.join(
                os.path.dirname(__file__),
                '../config/CR_DBC_V3.1_20250715.dbc',
            ),
        )
        self.topic = rospy.get_param('~topic', '/public_can/signals')
        self.publish_period_ms = float(rospy.get_param('~publish_period_ms', 20.0))

        self.db = cantools.database.load_file(self.dbc_path, strict=False)
        self.signal_fields = {}
        self.signal_types = {}
        self.signal_indices = {}
        for frame_id, _message_name, signal_name, field_name, ros_type, index in SIGNALS:
            self.signal_fields[(frame_id, signal_name)] = field_name
            self.signal_types[field_name] = ros_type
            self.signal_indices[field_name] = index

        self.lock = threading.Lock()
        self.values = {
            field_name: self._default_value(ros_type)
            for *_unused, field_name, ros_type, _index in SIGNALS
        }
        self.signal_valid = [0] * len(SIGNALS)
        self.signal_last_update = [None] * len(SIGNALS)
        self.received_frame_count = 0
        self.decoded_frame_count = 0

        self.publisher = rospy.Publisher(self.topic, PublicCanSignals, queue_size=10)
        self.can_bus = self._open_can_channel()
        self.publish_timer = rospy.Timer(
            rospy.Duration(self.publish_period_ms / 1000.0),
            self._publish_snapshot,
        )

        rospy.loginfo(
            '公共CAN信号发布节点已启动: channel=%s, dbc=%s, topic=%s, period=%.1fms, signals=%d',
            self.channel,
            self.dbc_path,
            self.topic,
            self.publish_period_ms,
            len(SIGNALS),
        )

    def _open_can_channel(self):
        bus = canlib.openChannel(self.channel, canlib.canOPEN_CAN_FD)
        bus.setBusParams(canlib.canFD_BITRATE_500K_80P)
        bus.setBusParamsFd(canlib.canFD_BITRATE_2M_80P)
        bus.busOn()
        return bus

    def _default_value(self, ros_type):
        if ros_type == 'bool':
            return False
        if ros_type in ('float32', 'float64'):
            return float('nan')
        return 0

    def _coerce_value(self, value, ros_type):
        raw_value = getattr(value, 'value', value)
        if ros_type == 'bool':
            return bool(raw_value)
        if ros_type in ('float32', 'float64'):
            return float(raw_value)
        return int(raw_value)

    def _publish_snapshot(self, _event):
        now = rospy.Time.now()
        with self.lock:
            msg = PublicCanSignals()
            msg.header.stamp = now
            msg.header.frame_id = f'can{self.channel}'
            msg.channel = self.channel
            msg.received_frame_count = self.received_frame_count
            msg.decoded_frame_count = self.decoded_frame_count
            msg.signal_valid = list(self.signal_valid)
            msg.signal_age_ms = [
                -1.0 if stamp is None else (now - stamp).to_sec() * 1000.0
                for stamp in self.signal_last_update
            ]
            for field_name, value in self.values.items():
                setattr(msg, field_name, value)

        self.publisher.publish(msg)

    def _decode_frame(self, frame):
        try:
            decoded = self.db.decode_message(
                frame.id,
                bytes(frame.data),
                decode_choices=False,
                decode_containers=True,
            )
        except Exception:
            return False

        flat = {}
        self._flatten(decoded, flat)
        if not flat:
            return False

        updated = 0
        now = rospy.Time.now()
        with self.lock:
            for signal_name, value in flat.items():
                field_name = self.signal_fields.get((frame.id, signal_name))
                if not field_name:
                    continue
                ros_type = self.signal_types[field_name]
                signal_index = self.signal_indices[field_name]
                try:
                    self.values[field_name] = self._coerce_value(value, ros_type)
                    self.signal_valid[signal_index] = 1
                    self.signal_last_update[signal_index] = now
                    updated += 1
                except (TypeError, ValueError):
                    continue
            if updated:
                self.decoded_frame_count += 1
        return bool(updated)

    def _flatten(self, value, out):
        if isinstance(value, dict):
            for key, sub_value in value.items():
                if isinstance(sub_value, (dict, list, tuple)):
                    self._flatten(sub_value, out)
                else:
                    out[key] = sub_value
        elif isinstance(value, list):
            for item in value:
                self._flatten(item, out)
        elif isinstance(value, tuple):
            if len(value) == 2 and isinstance(value[1], dict):
                self._flatten(value[1], out)

    def run(self):
        while not rospy.is_shutdown():
            try:
                while True:
                    frame = self.can_bus.read(timeout=0)
                    with self.lock:
                        self.received_frame_count += 1
                    self._decode_frame(frame)
            except canlib.canNoMsg:
                pass
            except canlib.canError as exc:
                rospy.logwarn('CAN读取异常: %s', exc)

            rospy.sleep(0.0005)

    def close(self):
        try:
            if getattr(self, 'publish_timer', None):
                self.publish_timer.shutdown()
            if getattr(self, 'can_bus', None):
                self.can_bus.busOff()
                self.can_bus.close()
        except Exception as exc:
            rospy.logwarn('关闭CAN接口异常: %s', exc)


if __name__ == '__main__':
    node = None
    try:
        node = PublicCanSignalPublisher()
        node.run()
    except rospy.ROSInterruptException:
        pass
    except Exception as exc:
        rospy.logerr('公共CAN信号发布节点异常: %s', exc)
    finally:
        if node:
            node.close()
