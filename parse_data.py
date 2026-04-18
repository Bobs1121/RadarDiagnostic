# -*- coding: utf-8 -*-
"""
Corner Radar & CAN Bus Data Parser
Parses .bag (ROS Bag V2.0) and .blf (Vector BLF CAN log) files.

Dependencies: pip install rosbags python-can
"""
import sys
import io
import argparse
import csv
import datetime
from pathlib import Path
from collections import Counter, defaultdict

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def parse_bag(bag_path, export_csv=False, output_dir=None):
    from rosbags.rosbag1 import Reader

    bag_path = Path(bag_path)
    if not bag_path.exists():
        print(f"[ERROR] File not found: {bag_path}")
        return

    with Reader(bag_path) as reader:
        print("=" * 70)
        print("  ROS BAG FILE ANALYSIS")
        print("=" * 70)
        print(f"  File:       {bag_path.name}")
        print(f"  Size:       {bag_path.stat().st_size / 1024 / 1024:.2f} MB")
        print(f"  Duration:   {reader.duration / 1e9:.2f} seconds")
        print(f"  Start:      {reader.start_time} ns")
        print(f"  End:        {reader.end_time} ns")
        print(f"  Messages:   {reader.message_count}")
        print(f"  Topics:     {len(reader.topics)}")
        print("-" * 70)

        for topic_name, topic_info in reader.topics.items():
            print(f"  [{topic_info.msgcount:>5d} msgs]  {topic_name}")
            print(f"              Type: {topic_info.msgtype}")

        if export_csv:
            out = Path(output_dir) if output_dir else bag_path.parent
            out.mkdir(parents=True, exist_ok=True)

            topic_files = {}
            topic_counters = defaultdict(int)

            for conn, timestamp, rawdata in reader.messages():
                topic_key = conn.topic.replace("/", "_").strip("_")
                topic_counters[conn.topic] += 1

                if conn.topic not in topic_files:
                    csv_path = out / f"bag_{topic_key}.csv"
                    f = open(csv_path, "w", newline="", encoding="utf-8")
                    writer = csv.writer(f)
                    writer.writerow(["timestamp_ns", "topic", "msg_type", "data_size", "data_hex_preview"])
                    topic_files[conn.topic] = (f, writer)

                _, writer = topic_files[conn.topic]
                preview = rawdata[:64].hex(" ")
                writer.writerow([timestamp, conn.topic, conn.msgtype, len(rawdata), preview])

            for f, _ in topic_files.values():
                f.close()

            print(f"\n  [EXPORT] CSV files saved to: {out}")
            for topic, count in topic_counters.items():
                topic_key = topic.replace("/", "_").strip("_")
                print(f"    bag_{topic_key}.csv  ({count} rows)")


def parse_blf(blf_path, export_csv=False, output_dir=None, dbc_paths=None):
    import can

    blf_path = Path(blf_path)
    db = None
    if dbc_paths:
        try:
            import cantools
            db = cantools.db.Database()
            for dp in dbc_paths:
                if Path(dp).exists():
                    db.add_dbc_file(str(dp))
            print(f"  [DBC] Loaded {len(db.messages)} message definitions")
        except Exception as e:
            print(f"  [DBC] Load failed: {e}")
            db = None
    if not blf_path.exists():
        print(f"[ERROR] File not found: {blf_path}")
        return

    reader = can.BLFReader(str(blf_path))

    msg_count = 0
    arb_ids = Counter()
    channels = Counter()
    dlc_dist = Counter()
    first_ts = None
    last_ts = None
    all_msgs = []

    for msg in reader:
        msg_count += 1
        arb_ids[msg.arbitration_id] += 1
        if msg.channel is not None:
            channels[msg.channel] += 1
        dlc_dist[msg.dlc] += 1
        if first_ts is None:
            first_ts = msg.timestamp
        last_ts = msg.timestamp
        if export_csv:
            all_msgs.append(msg)

    print("=" * 70)
    print("  BLF (CAN BUS) FILE ANALYSIS")
    print("=" * 70)
    print(f"  File:       {blf_path.name}")
    print(f"  Size:       {blf_path.stat().st_size / 1024 / 1024:.2f} MB")
    print(f"  Messages:   {msg_count}")

    if first_ts and last_ts:
        print(f"  Duration:   {last_ts - first_ts:.2f} seconds")
        print(f"  Start:      {datetime.datetime.fromtimestamp(first_ts)}")
        print(f"  End:        {datetime.datetime.fromtimestamp(last_ts)}")
        print(f"  Avg rate:   {msg_count / (last_ts - first_ts):.0f} msgs/sec")

    print(f"  CAN IDs:    {len(arb_ids)} unique")
    print(f"  Channels:   {len(channels)}")
    print("-" * 70)

    print("\n  Channel distribution:")
    for ch, count in channels.most_common():
        print(f"    Channel {ch}: {count:>8d} messages ({count/msg_count*100:.1f}%)")

    print("\n  DLC distribution:")
    for dlc, count in sorted(dlc_dist.items()):
        print(f"    DLC {dlc:>2d}: {count:>8d} messages")

    print(f"\n  All CAN IDs (sorted by frequency):")
    print(f"  {'CAN ID':>10s}  {'Count':>8s}  {'%':>6s}  {'DLC':>4s}")
    print("  " + "-" * 35)

    id_dlc = defaultdict(set)
    if export_csv:
        for m in all_msgs:
            id_dlc[m.arbitration_id].add(m.dlc)
    else:
        reader2 = can.BLFReader(str(blf_path))
        for m in reader2:
            id_dlc[m.arbitration_id].add(m.dlc)

    for arb_id, count in arb_ids.most_common():
        dlcs = ",".join(str(d) for d in sorted(id_dlc[arb_id]))
        pct = count / msg_count * 100
        print(f"  0x{arb_id:>08X}  {count:>8d}  {pct:>5.1f}%  {dlcs:>4s}")

    if export_csv:
        out = Path(output_dir) if output_dir else blf_path.parent
        out.mkdir(parents=True, exist_ok=True)
        csv_path = out / f"blf_{blf_path.stem}.csv"

        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            header = ["timestamp", "datetime", "channel", "can_id_hex", "can_id_dec",
                       "dlc", "is_extended", "is_fd", "data_hex"]
            if db:
                header.append("decoded_signals")
            writer.writerow(header)
            for msg in all_msgs:
                data_hex = " ".join(f"{b:02x}" for b in msg.data)
                dt = datetime.datetime.fromtimestamp(msg.timestamp).isoformat()
                row = [
                    f"{msg.timestamp:.6f}", dt, msg.channel,
                    f"0x{msg.arbitration_id:X}", msg.arbitration_id,
                    msg.dlc, msg.is_extended_id, msg.is_fd, data_hex,
                ]
                if db:
                    try:
                        decoded = db.decode_message(msg.arbitration_id, msg.data)
                        row.append(str(decoded))
                    except Exception:
                        row.append("")
                writer.writerow(row)

        print(f"\n  [EXPORT] CSV saved to: {csv_path}")
        print(f"    Total rows: {len(all_msgs)}")


def main():
    parser = argparse.ArgumentParser(description="Parse ROS Bag (.bag) and Vector BLF (.blf) files")
    parser.add_argument("files", nargs="+", help="Input .bag or .blf files")
    parser.add_argument("--export-csv", action="store_true", help="Export data to CSV files")
    parser.add_argument("--output-dir", type=str, help="Output directory for CSV export")
    parser.add_argument("--dbc", nargs="*", help="DBC file(s) for CAN signal decoding (BLF only)")
    args = parser.parse_args()

    for filepath in args.files:
        ext = Path(filepath).suffix.lower()
        if ext == ".bag":
            parse_bag(filepath, args.export_csv, args.output_dir)
        elif ext == ".blf":
            parse_blf(filepath, args.export_csv, args.output_dir, dbc_paths=args.dbc)
        else:
            print(f"[WARN] Unsupported format: {ext} ({filepath})")
        print()


if __name__ == "__main__":
    main()
