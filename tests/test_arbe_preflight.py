# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
from unittest.mock import patch
from pathlib import Path
from jsonschema import Draft202012Validator

from ai.modules.arbe_preflight import ArbePreflightModule
from ai.modules.base import ModuleResult
from engines.arbe.preflight import ArbePreflight, CommandResult
from engines.arbe.preflight import SshCommandRunner


class _FakeRunner:
    def __init__(self) -> None:
        self.commands: list[str] = []

    def run(self, command: str, *, timeout_sec: float) -> CommandResult:
        del timeout_sec
        self.commands.append(command)
        if "test -d" in command:
            return CommandResult(command, 0, "directory_present\n")
        if "rev-parse --show-toplevel" in command:
            return CommandResult(command, 0, "/home/test/arbe\n")
        if "rev-parse HEAD" in command:
            if "/src/algo_source" in command:
                return CommandResult(command, 0, "algo-commit\n")
            return CommandResult(command, 0, "outer-commit\n")
        if "status --short --branch" in command:
            if "/src/algo_source" in command:
                return CommandResult(command, 0, "## HEAD (detached)\n")
            return CommandResult(command, 0, "## develop_LGU_Simulation\n")
        if "submodule status" in command:
            return CommandResult(command, 0, "+algo-commit src/algo_source\n")
        if "launch_config" in command or "sed -n '1,240p'" in command:
            return CommandResult(
                command,
                0,
                "\n".join(
                    [
                        "ros:",
                        "    enable_gui: true",
                        "radars_setup:",
                        "    multiple_radars:",
                        "        n_radars: 4",
                        "    installation:",
                        "        radar_id: [1,2,3,4]",
                        "        radar_pos: [1,2,3,4]",
                        "        orientation: [2,1,1,2]",
                        "        radar_x_offset: [3.3,3.3,-0.6,-0.7]",
                        "        radar_y_offset: [0.7,-0.7,0.7,-0.7]",
                        "        xlsx_path: CUDA_TEST.xlsx",
                        "        xlsx_sheet: 03_QZH",
                        "car:",
                        "    type: BYD_UKE",
                    ]
                )
                + "\n",
            )
        if "arbe_radar_vis.launch" in command:
            return CommandResult(command, 0, "<node type=\"arbe_visualization_engine\"/>\n")
        if "/visualization_node.cpp" in command and "grep -nE" in command:
            return CommandResult(
                command,
                0,
                "\n".join(
                    [
                        "/home/test/arbe/src/visualization_node.cpp:3577:void corner_radar_post_process_data_callback(const Msg& msg)",
                        "/home/test/arbe/src/visualization_node.cpp:4052:    wf_object_display_handler();",
                        "/home/test/arbe/src/visualization_node.cpp:4087:    wf_adas_warn_status_with_frame_pub.publish(adas_warn_status_with_frame);",
                        "/home/test/arbe/src/visualization_node.cpp:2032:    wf_objectlist_pub.publish(ObjectListMsg_global);",
                    ]
                )
                + "\n",
            )
        if "paraDefine.h" in command:
            return CommandResult(
                command,
                0,
                "#define BUILDMODEL 2\n#define HILMODEL 2\n",
            )
        if "find " in command and "arbe_visualization_engine" in command:
            return CommandResult(
                command,
                0,
                "/home/test/arbe/devel/lib/arbe_phoenix_radar_driver/arbe_visualization_engine\n",
            )
        if "command -v gdb" in command:
            return CommandResult(command, 0, "/usr/bin/gdb\nGNU gdb (Ubuntu) 12.1\n0\n")
        if "grep -R -nE" in command or "grep -HnE" in command:
            return CommandResult(
                command,
                0,
                "\n".join(
                    [
                        "/home/test/arbe/src/algo/RteComMapping_Tx.c:38:void RteComMapping_TxRunnable_FuncSignal(void)",
                        "/home/test/arbe/src/algo/RteComMapping_Tx.c:144:RteComMapping_WriteSignal(RRadar_FCTA_Warning_Left_S)((AdasStM.Frontleft_FCTA == 1) ? 1u:0u);",
                        "/home/test/arbe/src/algo/rteLite.c:10:RteLite_Write_RRadar_FCTA_Warning_Left_S(VAR(uint8, AUTOMATIC) data)",
                        "/home/test/arbe/src/algo/rteLite.c:20:Com_SendSignal(ComConf_ComSignal_S_RRadar_FCTA_Warning_Left_S_Can_Network_Channel_CAN_Tx, &data)",
                    ]
                )
                + "\n",
            )
        if "ps -eo" in command:
            return CommandResult(
                command,
                0,
                "1234 /home/test/arbe/devel/lib/arbe_phoenix_radar_driver/arbe_visualization_engine __ns:=/radar2_visualization_engine\n",
            )
        if "rosnode list" in command:
            return CommandResult(
                command,
                0,
                "/radar2_visualization_engine/arbe_visualization_engine\n",
            )
        return CommandResult(command, 1, stderr="unexpected fake command")


def test_arbe_preflight_collects_source_config_and_runtime():
    runner = _FakeRunner()
    payload = ArbePreflight(
        runner=runner,
        server_host="10.0.0.1",
        server_user="tester",
        arbe_root="/home/test/arbe",
    ).run()

    assert payload["schema_version"] == "arbe-preflight.v1"
    assert payload["status"] == "ready"
    assert payload["workspace"]["outer"]["head"] == "outer-commit"
    assert payload["workspace"]["algo_source"]["head"] == "algo-commit"
    assert payload["configuration"]["resolved"]["coem_name"] == "BYD_UKE"
    assert payload["configuration"]["resolved"]["xlsx_sheet"] == "03_QZH"
    assert payload["build"]["macros"]["HILMODEL"] == "2"
    assert payload["runtime"]["processes"][0]["radar_id"] == 2
    assert payload["gdb"]["path"] == "/usr/bin/gdb"
    assert payload["gdb"]["version"].startswith("GNU gdb")
    assert payload["gdb"]["ptrace_scope"] == "0"
    assert "RRadar_FCTA_Warning_Left_S" in payload["can_output"]["candidate_signal_tokens"]
    assert payload["can_output"]["write_mappings"][0]["signal"] == "RRadar_FCTA_Warning_Left_S"
    assert payload["can_output"]["write_mappings"][0]["source_ref"]["line"] == 144
    assert payload["can_output"]["transport_mappings"][0]["signal"] == "RRadar_FCTA_Warning_Left_S"
    assert payload["can_output"]["transport_mappings"][0]["com_signal"] == "RRadar_FCTA_Warning_Left_S"
    assert payload["can_output"]["observation_status"] == "candidate_source_found"
    assert payload["can_output"]["source_output_chain"]["schema_version"] == "arbe-source-output-chain.v1"
    assert payload["can_output"]["source_output_chain"]["status"] == "source_scanned"
    contract = payload["public_evidence"]["objectlist_frame_contract"]
    assert contract["status"] == "source_verified"
    assert contract["association_mode"] == "publication_order"
    assert contract["warning_with_frame_publish"]["line"] == 4087
    assert len(payload["commands"]) >= 10
    Draft202012Validator(
        json.loads(Path("contracts/arbe-preflight.v1.schema.json").read_text(encoding="utf-8"))
    ).validate(payload)


def test_arbe_preflight_can_bind_ros_master_explicitly():
    runner = _FakeRunner()
    payload = ArbePreflight(
        runner=runner,
        arbe_root="/home/test/arbe",
        ros_master_uri="http://localhost:11311",
    ).run()
    assert payload["runtime"]["ros_master_uri"] == "http://localhost:11311"
    assert payload["runtime"]["ros_setup"] == "/opt/ros/noetic/setup.bash"
    assert any("source /opt/ros/noetic/setup.bash" in command for command in runner.commands)
    assert any("export ROS_MASTER_URI=http://localhost:11311" in command for command in runner.commands)


def test_arbe_preflight_reports_not_running_as_partial():
    class _NoProcessRunner(_FakeRunner):
        def run(self, command: str, *, timeout_sec: float) -> CommandResult:
            result = super().run(command, timeout_sec=timeout_sec)
            if "ps -eo" in command:
                return CommandResult(command, 1, stderr="no process")
            return result

    payload = ArbePreflight(
        runner=_NoProcessRunner(),
        arbe_root="/home/test/arbe",
    ).run()

    assert payload["status"] == "partial"
    assert payload["runtime"]["status"] == "not_running"
    assert payload["runtime"]["bash_start_required"] is True


def test_arbe_preflight_module_writes_local_artifact(tmp_path: Path):
    runner = _FakeRunner()
    output = tmp_path / "preflight.json"
    result = ArbePreflightModule(runner=runner).safe_run(
        arbe_root="/home/test/arbe",
        server_host="10.0.0.1",
        server_user="tester",
        output=str(output),
    )

    assert isinstance(result, ModuleResult)
    assert result.ok is True
    assert result.module == "arbe-preflight"
    assert result.data["schema_version"] == "arbe-preflight.v1"
    assert result.data["status"] == "ready"
    assert output.exists()
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert saved["schema_version"] == "arbe-preflight.v1"
    assert str(output) in result.artifacts


def test_arbe_preflight_module_requires_workspace():
    result = ArbePreflightModule().safe_run(arbe_root="")
    assert result.ok is False
    assert "arbe_root is required" in result.message


def test_arbe_preflight_cli_wiring():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers()
    ArbePreflightModule.register_cli(sub)
    args = parser.parse_args(
        [
            "arbe-preflight",
            "--host",
            "10.0.0.1",
            "--user",
            "tester",
            "--arbe-root",
            "/home/test/arbe",
        ]
    )
    assert args._module_cls is ArbePreflightModule
    assert args.server_host == "10.0.0.1"
    assert ArbePreflightModule.from_cli_args(args).__class__ is ArbePreflightModule


def test_ssh_runner_keeps_remote_bash_command_as_one_argument():
    class _Completed:
        returncode = 0
        stdout = "ok\n"
        stderr = ""

    runner = SshCommandRunner(
        host="10.0.0.1",
        username="tester",
        port=22,
    )
    with patch("engines.arbe.preflight.subprocess.run", return_value=_Completed()) as run:
        result = runner.run("git -C '/tmp/arbe' rev-parse HEAD", timeout_sec=5)

    assert result.ok is True
    args = run.call_args.args[0]
    assert args[-2] == "tester@10.0.0.1"
    assert args[-1].startswith("bash -lc ")
    assert "git -C" in args[-1]
    assert len(args) == 9


def test_process_parser_resolves_radar_from_rosout_log_name():
    from engines.arbe.preflight import _parse_binary_fingerprint, _parse_processes, _parse_macro_values

    processes = _parse_processes(
        "3662064 /home/test/.ros/log/abc/radar2_visualization_engine-arbe_visualization_engine-1.log "
        "/home/test/arbe/devel/lib/arbe_phoenix_radar_driver/arbe_visualization_engine\n"
    )
    assert processes[0]["namespace"] == "radar2_visualization_engine"
    assert processes[0]["radar_id"] == 2

    assert _parse_macro_values("10:#define HILMODEL 2\n11:#define BUILDMODEL 2\n") == {
        "HILMODEL": "2",
        "BUILDMODEL": "2",
    }
    assert _parse_binary_fingerprint("a" * 64 + "  /home/test/arbe/devel/lib/arbe_visualization_engine\n") == "a" * 64
