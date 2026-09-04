# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path

from ai.capability.registry import capability_catalog
from ai.modules import MODULE_REGISTRY
from ai.modules.base import ModuleResult
from ai.modules.ros_topic_inventory import RosTopicInventoryModule
from engines.arbe.preflight import CommandResult
from engines.arbe.ros_inventory import (
    RosTopicInventory,
    build_inventory_command,
    build_sample_command,
    parse_inventory_output,
)


class _FakeRunner:
    def __init__(self) -> None:
        self.commands: list[str] = []

    def run(self, command: str, *, timeout_sec: float) -> CommandResult:
        del timeout_sec
        self.commands.append(command)
        return CommandResult(
            command=command,
            returncode=0,
            stdout=(
                "__CR60_TOPIC_START__/wf/objectlist_2\n"
                "arbe_msgs/wfObjectMsg\n"
                "Type: arbe_msgs/wfObjectMsg\n"
                "Publishers:\n"
                " * /radar2_visualization_engine/arbe_visualization_engine\n"
                "Subscribers:\n"
                " * /arbe_gui\n"
                "__CR60_TOPIC_END__\n"
                "__CR60_TOPIC_START__/wf/xcp_signals/front_left/parsed\n"
                "common_xcp_info_publisher_rvizbag/XcpEgoInfo\n"
                "Type: common_xcp_info_publisher_rvizbag/XcpEgoInfo\n"
                "Publishers:\n"
                "Subscribers:\n"
                " * /arbe_gui\n"
                "__CR60_TOPIC_END__\n"
            ),
        )


def test_inventory_parser_supports_rostopic_type_and_info_formats():
    rows = parse_inventory_output(
        "__CR60_TOPIC_START__/topic\n"
        "pkg/Msg\n"
        "Type: pkg/Msg\n"
        "Publishers:\n"
        " * /pub\n"
        "Subscribers:\n"
        " * /sub\n"
        "__CR60_TOPIC_END__\n"
    )
    assert rows == [
        {
            "topic": "/topic",
            "type": "pkg/Msg",
            "publishers": ["/pub"],
            "subscribers": ["/sub"],
            "publisher_count": 1,
            "subscriber_count": 1,
            "data_observable": True,
            "status": "ready",
        }
    ]


def test_inventory_rejects_shell_like_topic_and_builds_safe_command():
    try:
        build_inventory_command(topics=["/ok", "/bad;rm"])
    except ValueError as exc:
        assert "invalid" in str(exc)
    else:
        raise AssertionError("invalid topic should be rejected")
    command = build_inventory_command(
        topics=["/wf/objectlist_2"],
        ros_setup="/opt/ros/noetic/setup.bash",
        workspace_setup="/home/test/devel/setup.bash",
    )
    assert "source /opt/ros/noetic/setup.bash" in command
    assert "/wf/objectlist_2" in command


def test_inventory_executes_read_only_runner_and_preserves_topic_type():
    runner = _FakeRunner()
    payload = RosTopicInventory(
        runner=runner,
        server_host="10.190.171.44",
        server_user="hoz2wx",
    ).run(
        topics=["/wf/objectlist_2", "/wf/xcp_signals/front_left/parsed"],
        execute=True,
    )
    assert payload["status"] == "ready"
    assert payload["topics"][0]["type"] == "arbe_msgs/wfObjectMsg"
    assert payload["topics"][0]["data_observable"] is True
    assert payload["topics"][1]["type"] == "common_xcp_info_publisher_rvizbag/XcpEgoInfo"
    assert payload["topics"][1]["data_observable"] is False
    assert runner.commands


def test_inventory_can_sample_one_message_and_distinguish_publisher_from_data():
    class _SampleRunner(_FakeRunner):
        def run(self, command: str, *, timeout_sec: float) -> CommandResult:
            self.commands.append(command)
            if "rostopic echo" in command:
                return CommandResult(command, 124, stderr="timeout")
            return super().run(command, timeout_sec=timeout_sec)

    runner = _SampleRunner()
    payload = RosTopicInventory(runner=runner).run(
        topics=["/wf/objectlist_2", "/wf/xcp_signals/front_left/parsed"],
        execute=True,
        sample_once=True,
        sample_timeout_sec=1,
    )
    assert payload["sample_once"] is True
    assert payload["topics"][0]["publisher_present"] is True
    assert payload["topics"][0]["message_observable"] is False
    assert payload["topics"][0]["data_observable"] is False
    assert payload["topics"][0]["sample"]["status"] == "no_message"
    assert any("rostopic echo -n 1" in command for command in runner.commands)


def test_sample_command_is_allowlisted_and_bounded():
    command = build_sample_command(
        topic="/wf/objectlist_2",
        ros_setup="/opt/ros/noetic/setup.bash",
        workspace_setup="/home/test/devel/setup.bash",
        timeout_sec=2,
    )
    assert "timeout 2s rostopic echo -n 1 /wf/objectlist_2" in command
    try:
        build_sample_command(topic="/bad;rm", timeout_sec=2)
    except ValueError:
        pass
    else:
        raise AssertionError("invalid topic should be rejected")


def test_inventory_module_plan_is_registered(tmp_path: Path):
    output = tmp_path / "inventory.json"
    result = RosTopicInventoryModule().safe_run(
        topics=["/wf/objectlist_2"],
        server_host="10.190.171.44",
        server_user="hoz2wx",
        ros_setup="/opt/ros/noetic/setup.bash",
        output=str(output),
    )
    assert isinstance(result, ModuleResult)
    assert result.ok is True
    assert result.data["status"] == "planned"
    assert output.exists()
    assert MODULE_REGISTRY["ros-topic-inventory"] is RosTopicInventoryModule
    catalog = {item["name"]: item for item in capability_catalog()}
    assert "read-only" in catalog["ros-topic-inventory"]["tags"]
