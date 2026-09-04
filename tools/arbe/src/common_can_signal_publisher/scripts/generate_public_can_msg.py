#!/usr/bin/env python3
import argparse
import os
import re
from collections import Counter

import cantools


def sanitize_name(value):
    name = re.sub(r'[^0-9A-Za-z_]', '_', value)
    name = re.sub(r'_+', '_', name).strip('_').lower()
    if not name or not re.match(r'[a-z]', name[0]):
        name = f's_{name}'
    return name


def make_field_name(message, signal):
    return sanitize_name(f'm_{message.frame_id:03x}_{message.name}_{signal.name}')


def ros_type_for_signal(signal):
    if getattr(signal, 'is_float', False):
        return 'float64'

    if signal.scale != 1 or signal.offset != 0:
        return 'float64'

    if signal.length == 1 and not signal.choices:
        return 'bool'

    if signal.length <= 8:
        return 'int8' if signal.is_signed else 'uint8'
    if signal.length <= 16:
        return 'int16' if signal.is_signed else 'uint16'
    if signal.length <= 32:
        return 'int32' if signal.is_signed else 'uint32'
    return 'int64' if signal.is_signed else 'uint64'


def main():
    parser = argparse.ArgumentParser(
        description='Generate PublicCanSignals.msg and generated_signal_map.py from a DBC.'
    )
    parser.add_argument(
        '--dbc',
        default=os.path.join(
            os.path.dirname(__file__),
            '../config/CR_DBC_V3.1_20250715.dbc',
        ),
        help='Input DBC path.',
    )
    parser.add_argument(
        '--msg',
        default=os.path.join(os.path.dirname(__file__), '../msg/PublicCanSignals.msg'),
        help='Output ROS msg path.',
    )
    parser.add_argument(
        '--map',
        default=os.path.join(os.path.dirname(__file__), 'generated_signal_map.py'),
        help='Output Python signal map path.',
    )
    args = parser.parse_args()

    db = cantools.database.load_file(args.dbc, strict=False)
    fields = []
    used = Counter()

    for message in sorted(db.messages, key=lambda item: item.frame_id):
        for signal in message.signals:
            base = make_field_name(message, signal)
            used[base] += 1
            field_name = base if used[base] == 1 else f'{base}_{used[base]}'
            fields.append(
                (
                    message.frame_id,
                    message.name,
                    signal.name,
                    field_name,
                    ros_type_for_signal(signal),
                )
            )

    os.makedirs(os.path.dirname(args.msg), exist_ok=True)
    with open(args.msg, 'w', encoding='utf-8') as f:
        f.write('# Auto-generated from DBC. Regenerate with scripts/generate_public_can_msg.py.\n')
        f.write('# Each signal field stores the latest decoded physical value using a DBC-derived ROS type.\n')
        f.write('# signal_valid/signal_age_ms arrays follow the same order as generated_signal_map.SIGNALS.\n')
        f.write('std_msgs/Header header\n')
        f.write('uint8 channel\n')
        f.write('uint32 received_frame_count\n')
        f.write('uint32 decoded_frame_count\n')
        f.write('uint8[] signal_valid\n')
        f.write('float32[] signal_age_ms\n')
        for _, _, _, field_name, ros_type in fields:
            f.write(f'{ros_type} {field_name}\n')

    os.makedirs(os.path.dirname(args.map), exist_ok=True)
    with open(args.map, 'w', encoding='utf-8') as f:
        f.write('# Auto-generated from DBC. Regenerate with scripts/generate_public_can_msg.py.\n')
        f.write('SIGNALS = [\n')
        for index, (frame_id, message_name, signal_name, field_name, ros_type) in enumerate(fields):
            f.write(
                f'    ({frame_id}, {message_name!r}, {signal_name!r}, '
                f'{field_name!r}, {ros_type!r}, {index}),\n'
            )
        f.write(']\n')

    print(f'Generated {len(fields)} signal fields')
    print(args.msg)
    print(args.map)


if __name__ == '__main__':
    main()
