# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path

from engines.arbe.preflight import CommandResult
from engines.arbe.remote_replay import (
    RemoteArbeReplayProvider,
    build_public_capture_command,
    parse_public_capture_result,
)


def test_public_capture_command_is_existing_sim_verify_replay_plan():
    plan = build_public_capture_command(
        remote_bag_path="/data/example.bag",
        remote_capture_base="/tmp/run-1/public",
        start_sec=518.9,
        duration_sec=4.0,
        input_topics=["/wf/corner_radar/lgu_data_1"],
        output_topics=["/corner_radar/warning_status_with_frame", "/wf/objectlist_1"],
        workspace_setup="/workspace/devel/setup.bash",
    )
    assert "rosbag record" in plan["command"]
    assert "rosbag play --clock --start 518.9 --duration 4" in plan["command"]
    assert "base64 -d | python3 -" in plan["command"]
    assert plan["remote_capture_bag"] == "/tmp/run-1/public.bag"
    assert plan["remote_capture_json"] == "/tmp/run-1/public.json"


def test_public_capture_markers_parse_numeric_status():
    values = parse_public_capture_result(
        "noise\n"
        "__CR60_PUBLIC_CAPTURE_BEGIN__\n"
        "play_rc\t0\nrecord_rc\t143\ncapture_json\t/tmp/a.json\n"
        "extract_rc\t0\ncapture_json_present\tyes\n"
        "__CR60_PUBLIC_CAPTURE_END__\n"
    )
    assert values["play_rc"] == 0
    assert values["record_rc"] == 143
    assert values["extract_rc"] == 0
    assert values["capture_json_present"] == "yes"


class _FakeRunner:
    def run(self, command: str, *, timeout_sec: float) -> CommandResult:
        assert "rosbag play" in command
        return CommandResult(
            command=command,
            returncode=0,
            stdout=(
                "__CR60_PUBLIC_CAPTURE_BEGIN__\n"
                "play_rc\t0\nrecord_rc\t0\n"
                "capture_bag\t/tmp/run-1/public.bag\n"
                "capture_json\t/tmp/run-1/public.json\n"
                "extract_rc\t0\ncapture_json_present\tyes\n"
                "__CR60_PUBLIC_CAPTURE_END__\n"
            ),
        )


class _FakeScp:
    def fetch(self, remote_path: str, local_path: str | Path, *, timeout_sec: float) -> CommandResult:
        Path(local_path).write_text(
            json.dumps({
                "warning_rows": [{"source": "warning_status_with_frame", "data": [2, 20] + [0] * 15}],
                "radar_info_rows": [{"data": [2, 4.0, 0.0, 10, 20, 60.0, 0, 0, 0]}],
                "object_rows": [{"radar_id": 2, "object_index": 0, "objID": 44}],
            }),
            encoding="utf-8",
        )
        return CommandResult(command=f"scp {remote_path}", returncode=0)


def test_remote_provider_executes_and_fetches_capture_without_new_capability(tmp_path: Path):
    local_capture = tmp_path / "capture.json"
    provider = RemoteArbeReplayProvider(
        host="server",
        username="user",
        runner=_FakeRunner(),
        scp_fetcher=_FakeScp(),
    )
    payload = provider.capture_public(
        remote_bag_path="/data/example.bag",
        remote_capture_base="/tmp/run-1/public",
        start_sec=1,
        duration_sec=2,
        input_topics=["/wf/corner_radar/lgu_data_2"],
        output_topics=["/corner_radar/warning_status_with_frame"],
        execute=True,
        local_capture_path=local_capture,
    )
    assert payload["status"] == "completed"
    assert payload["local_capture_json"] == str(local_capture.resolve())
    assert local_capture.exists()
