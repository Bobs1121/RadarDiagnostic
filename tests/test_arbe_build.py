# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path

from ai.capability.module_bridge import build_module_tool_registry
from ai.capability.registry import capability_catalog
from ai.modules import MODULE_REGISTRY
from ai.modules.arbe_build import ArbeBuildModule
from engines.arbe.build import build_catkin_make_command, run_catkin_make
from engines.arbe.preflight import CommandResult


class _FakeRunner:
    def __init__(self, result: CommandResult | None = None) -> None:
        self.calls: list[str] = []
        self.result = result or CommandResult("", 0, "Build finished\n")

    def run(self, command: str, *, timeout_sec: float) -> CommandResult:
        self.calls.append(command)
        return CommandResult(command, self.result.returncode, self.result.stdout, self.result.stderr, self.result.timed_out)


def test_build_command_is_explicit_and_rejects_shell_fragments():
    command = build_catkin_make_command(
        arbe_root="/home/test/arbe",
        ros_setup="/opt/ros/noetic/setup.bash",
        catkin_make_args=["--cmake-args", "-DCMAKE_BUILD_TYPE=RelWithDebInfo"],
    )
    assert command == "source /opt/ros/noetic/setup.bash && cd /home/test/arbe && catkin_make --cmake-args -DCMAKE_BUILD_TYPE=RelWithDebInfo"
    try:
        build_catkin_make_command(arbe_root="/home/test/arbe", catkin_make_args=["; rm -rf /"])
    except ValueError as exc:
        assert "unsafe shell" in str(exc)
    else:
        raise AssertionError("unsafe catkin_make arg was accepted")


def test_build_engine_plan_only_and_execute_states():
    fake = _FakeRunner()
    planned = run_catkin_make(runner=fake, arbe_root="/home/test/arbe")
    assert planned["status"] == "planned"
    assert fake.calls == []
    completed = run_catkin_make(runner=fake, arbe_root="/home/test/arbe", execute=True)
    assert completed["status"] == "completed"
    assert len(fake.calls) == 1


def test_arbe_build_module_is_pi_registered_and_approval_gated(tmp_path: Path):
    assert MODULE_REGISTRY["arbe-build"] is ArbeBuildModule
    entry = {item["name"]: item for item in capability_catalog()}["arbe-build"]
    assert entry["expose_to_pi"] is True
    assert entry["requires_approval"] is True
    output = tmp_path / "build.json"
    result = ArbeBuildModule(runner=_FakeRunner()).safe_run(
        arbe_root="/home/test/arbe",
        execute=True,
        approved=False,
        output=str(output),
    )
    assert result.ok is True
    assert result.data["status"] == "approval_required"
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "approval_required"


def test_module_bridge_blocks_build_execution_without_supervisor_permission():
    tools = build_module_tool_registry(names=["arbe-build"])
    result = tools["arbe-build"].safe_execute(
        {"arbe_root": "/home/test/arbe", "execute": True, "approved": True}
    )
    assert result["status"] == "error"
    assert result["data"]["approval_required"] is True
