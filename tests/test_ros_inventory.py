# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
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
    build_message_definition_command,
    build_sample_command,
    parse_inventory_output,
    parse_message_definition,
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
    assert payload["topics"][0]["sample"]["stdout_truncated"] is False
    assert payload["topics"][0]["sample"]["stdout_sha256"]
    assert payload["observed_at_utc"].endswith("Z")
    assert payload["topics"][0]["sample"]["observed_at_utc"].endswith("Z")
    assert any("rostopic echo -n 1" in command for command in runner.commands)


def test_inventory_sample_bounds_payload_and_preserves_full_payload_hash():
    full_text = "x" * 21000

    class _LargeSampleRunner(_FakeRunner):
        def run(self, command: str, *, timeout_sec: float) -> CommandResult:
            self.commands.append(command)
            if "rostopic echo" in command:
                return CommandResult(command, 0, stdout=full_text)
            return super().run(command, timeout_sec=timeout_sec)

    payload = RosTopicInventory(runner=_LargeSampleRunner()).run(
        topics=["/wf/objectlist_2"], execute=True, sample_once=True
    )
    sample = payload["topics"][0]["sample"]
    assert sample["stdout_truncated"] is True
    assert sample["stdout_char_count"] == len(full_text)
    assert len(sample["stdout"]) == 20000
    assert sample["stdout_sha256"] == hashlib.sha256(full_text.encode("utf-8")).hexdigest()


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


def test_rosmsg_definition_parser_exposes_current_root_and_nested_field_paths():
    fields = parse_message_definition(
        "uint32 object_count\n"
        "arbe_msgs/wfSObj[] ObjectsBuffer\n"
        "MSG: arbe_msgs/wfSObj\n"
        "int32 ID\n"
        "uint32 objID\n"
        "float32 distX\n",
        root_type="arbe_msgs/wfObjectMsg",
    )
    assert fields == [
        {
            "message_type": "arbe_msgs/wfObjectMsg",
            "name": "object_count",
            "type": "uint32",
            "path": "arbe_msgs/wfObjectMsg.object_count",
        },
        {
            "message_type": "arbe_msgs/wfObjectMsg",
            "name": "ObjectsBuffer",
            "type": "arbe_msgs/wfSObj[]",
            "path": "arbe_msgs/wfObjectMsg.ObjectsBuffer",
        },
        {
            "message_type": "arbe_msgs/wfSObj",
            "name": "ID",
            "type": "int32",
            "path": "arbe_msgs/wfSObj.ID",
        },
        {
            "message_type": "arbe_msgs/wfSObj",
            "name": "objID",
            "type": "uint32",
            "path": "arbe_msgs/wfSObj.objID",
        },
        {
            "message_type": "arbe_msgs/wfSObj",
            "name": "distX",
            "type": "float32",
            "path": "arbe_msgs/wfSObj.distX",
        },
    ]


def test_message_definition_command_validates_ros_type_and_sources_workspace():
    command = build_message_definition_command(
        message_type="arbe_msgs/wfObjectMsg",
        ros_setup="/opt/ros/noetic/setup.bash",
        workspace_setup="/home/test/devel/setup.bash",
    )
    assert "source /opt/ros/noetic/setup.bash" in command
    assert "source /home/test/devel/setup.bash" in command
    assert command.endswith("rosmsg show arbe_msgs/wfObjectMsg")
    try:
        build_message_definition_command(message_type="arbe_msgs/Type;touch /tmp/x")
    except ValueError:
        pass
    else:
        raise AssertionError("shell-like message type should be rejected")


def test_inventory_can_inspect_active_message_schema_without_hard_coded_fields():
    class _SchemaRunner(_FakeRunner):
        def run(self, command: str, *, timeout_sec: float) -> CommandResult:
            if "rosmsg show" in command:
                self.commands.append(command)
                return CommandResult(
                    command,
                    0,
                    stdout=(
                        "int32 ID\n"
                        "uint32 objID\n"
                        "float32 distX\n"
                        "MSG: geometry_msgs/Point\n"
                        "float64 x\n"
                        "float64 y\n"
                    ),
                )
            return super().run(command, timeout_sec=timeout_sec)

    runner = _SchemaRunner()
    payload = RosTopicInventory(runner=runner).run(
        topics=["/wf/objectlist_2"],
        execute=True,
        inspect_message_schemas=True,
    )
    schema = payload["topics"][0]["message_schema"]
    assert payload["inspect_message_schemas"] is True
    assert schema["status"] == "ready"
    assert schema["message_type"] == "arbe_msgs/wfObjectMsg"
    assert schema["message_definition_sha256"]
    assert schema["field_count"] == 5
    assert "message_definition" not in schema
    assert schema["definition_truncated"] is False
    assert [item["path"] for item in schema["field_catalog"]] == [
        "arbe_msgs/wfObjectMsg.ID",
        "arbe_msgs/wfObjectMsg.objID",
        "arbe_msgs/wfObjectMsg.distX",
        "geometry_msgs/Point.x",
        "geometry_msgs/Point.y",
    ]
    assert any("rosmsg show arbe_msgs/wfObjectMsg" in command for command in runner.commands)


def test_inventory_marks_large_message_field_catalog_partial_and_bounded():
    class _LargeSchemaRunner(_FakeRunner):
        def run(self, command: str, *, timeout_sec: float) -> CommandResult:
            if "rosmsg show" in command:
                self.commands.append(command)
                return CommandResult(
                    command,
                    0,
                    stdout="\n".join(f"float32 field_{index}" for index in range(520)),
                )
            return super().run(command, timeout_sec=timeout_sec)

    payload = RosTopicInventory(runner=_LargeSchemaRunner()).run(
        topics=["/wf/objectlist_2"],
        execute=True,
        inspect_message_schemas=True,
    )
    schema = payload["topics"][0]["message_schema"]
    assert schema["status"] == "partial"
    assert schema["field_count"] == 520
    assert len(schema["field_catalog"]) == 512
    assert schema["field_catalog_truncated"] is True
    assert "message_definition_field_catalog_truncated" in schema["diagnostics"]


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


def test_inventory_module_binds_server_and_workspace_from_preflight(tmp_path: Path):
    preflight = {
        "schema_version": "arbe-preflight.v1",
        "status": "ready",
        "server": {"host": "10.190.171.44", "user": "hoz2wx", "port": 22, "transport": "ssh"},
        "workspace": {
            "arbe_root": "/home/hoz2wx/arbe",
            "algo_source": {"head": "abc", "content_fingerprint": "def"},
        },
        "build": {"binary_fingerprint": "binary-sha"},
        "configuration": {"content_fingerprint": "config-sha"},
    }
    preflight_path = tmp_path / "preflight.json"
    preflight_path.write_text(json.dumps(preflight), encoding="utf-8")
    result = RosTopicInventoryModule().safe_run(
        topics=["/wf/objectlist_2"],
        preflight_path=str(preflight_path),
    )
    assert result.ok is True
    assert result.data["server"]["host"] == "10.190.171.44"
    assert result.data["runtime_binding"]["status"] == "preflight_bound"
    assert result.data["runtime_binding"]["workspace"] == preflight["workspace"]
    assert result.data["runtime_binding"]["preflight_sha256"] == hashlib.sha256(
        preflight_path.read_bytes()
    ).hexdigest()


def test_inventory_module_rejects_explicit_server_conflict_with_preflight(tmp_path: Path):
    preflight_path = tmp_path / "preflight.json"
    preflight_path.write_text(
        json.dumps({
            "schema_version": "arbe-preflight.v1",
            "status": "ready",
            "server": {"host": "10.190.171.44", "user": "hoz2wx", "port": 22},
            "workspace": {"arbe_root": "/home/hoz2wx/arbe"},
        }),
        encoding="utf-8",
    )
    result = RosTopicInventoryModule().safe_run(
        topics=["/wf/objectlist_2"],
        server_host="10.190.171.99",
        preflight_path=str(preflight_path),
    )
    assert result.ok is False
    assert "server_host conflicts with preflight identity" in result.message
