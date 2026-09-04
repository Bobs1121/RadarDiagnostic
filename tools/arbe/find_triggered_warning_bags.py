#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import os
import sys

import rosbag


def has_triggered_warning(msg) -> bool:
    data = getattr(msg, "data", None)
    if data is None or len(data) < 2:
        return False
    for value in data[1:]:
        try:
            if int(value) != 0:
                return True
        except Exception:
            continue
    return False


def find_bag_files(root_dir: str):
    bag_files = []
    for current_root, _, files in os.walk(root_dir):
        for name in files:
            if name.endswith(".bag"):
                bag_files.append(os.path.join(current_root, name))
    bag_files.sort()
    return bag_files


def bag_has_triggered_topic(bag_path: str, warning_topic: str) -> bool:
    bag = None
    try:
        bag = rosbag.Bag(bag_path, "r")
        topic_info = bag.get_type_and_topic_info()[1]
        if warning_topic not in topic_info:
            return False

        for _, msg, _ in bag.read_messages(topics=[warning_topic]):
            if has_triggered_warning(msg):
                return True
        return False
    finally:
        if bag is not None:
            bag.close()


def main():
    parser = argparse.ArgumentParser(
        description="遍历文件夹内 bag，筛出包含触发告警（warning data 非全0）的 bag。"
    )
    parser.add_argument("bag_dir", help="bag 文件夹路径")
    parser.add_argument(
        "--warning-topic",
        default="/corner_radar/warning_status_raw",
        help="告警话题名（默认: /corner_radar/warning_status_raw）",
    )
    parser.add_argument(
        "--output",
        default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "triggered_warning_bags.txt"),
        help="输出 txt 路径（默认脚本同目录 triggered_warning_bags.txt）",
    )
    args = parser.parse_args()

    bag_dir = os.path.abspath(args.bag_dir)
    if not os.path.isdir(bag_dir):
        print(f"[ERROR] bag_dir 不存在: {bag_dir}", file=sys.stderr)
        return 1

    bag_files = find_bag_files(bag_dir)
    if not bag_files:
        print(f"[WARN] 未找到 bag 文件: {bag_dir}")
        with open(args.output, "w", encoding="utf-8") as f:
            pass
        return 0

    triggered_bags = []
    for bag_path in bag_files:
        try:
            if bag_has_triggered_topic(bag_path, args.warning_topic):
                triggered_bags.append(os.path.basename(bag_path))
        except Exception as e:
            print(f"[WARN] 跳过异常 bag: {bag_path}, err={e}", file=sys.stderr)

    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        for rel_path in triggered_bags:
            f.write(rel_path + "\n")

    print(f"[INFO] 扫描 bag 总数: {len(bag_files)}")
    print(f"[INFO] 含触发告警 bag 数: {len(triggered_bags)}")
    print(f"[INFO] 输出文件: {os.path.abspath(args.output)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
