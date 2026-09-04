from __future__ import annotations

import argparse
import json
from pathlib import Path

from ai.capability.registry import capability_catalog
from ai.modules import MODULE_REGISTRY
from ai.modules.base import ModuleResult
from ai.modules.cr60_data_prep_verify import CR60DataPrepVerifyModule
from engines.arbe.data_prep import (
    build_data_verify_command,
    map_source_path,
    parse_data_verify_output,
    verify_data,
)
from engines.arbe.preflight import CommandResult


class _FakeRunner:
    def __init__(self, stdout: str, returncode: int = 0, stderr: str = "") -> None:
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = stderr
        self.calls: list[str] = []

    def run(self, command: str, *, timeout_sec: float) -> CommandResult:
        del timeout_sec
        self.calls.append(command)
        return CommandResult(command, self.returncode, self.stdout, self.stderr)


def _output() -> str:
    sha = "a" * 64
    return "\n".join(
        [
            "__CR60_DATA_VERIFY_BEGIN__",
            "__CR60_DATA_CASE_BEGIN__0",
            "source_present\ttrue",
            f"file\t/home/test/source/a.bag\ta.bag\t10\t100\t{sha}",
            "destination_present\ttrue",
            f"file\t/home/test/dest/a.bag\ta.bag\t10\t101\t{sha}",
            "__CR60_DATA_CASE_END__0",
            "__CR60_DATA_CASE_BEGIN__1",
            "source_present\ttrue",
            f"file\t/home/test/source/b.blf\tb.blf\t20\t100\t{sha}",
            "destination_present\ttrue",
            f"file\t/home/test/dest/b.blf\tb.blf\t20\t101\t{sha}",
            "__CR60_DATA_CASE_END__1",
            "__CR60_DATA_VERIFY_END__",
            "",
        ]
    )


def test_map_source_path_is_explicit_for_unc_and_windows_paths():
    assert map_source_path("/home/test/a.bag")["status"] == "linux_absolute"
    mapped = map_source_path(r"\\server\share\qzh\a.bag", source_prefix="/mnt/cluster")
    assert mapped["status"] == "mapped_unc"
    assert mapped["mapped"] == "/mnt/cluster/qzh/a.bag"
    assert map_source_path(r"C:\data\a.bag")["status"] == "needs_confirmation"
    assert map_source_path(r"\\server\share\a.bag")["status"] == "needs_confirmation"


def test_data_verify_command_is_read_only_and_preserves_entry_identity():
    command = build_data_verify_command(
        entries=[
            {
                "entry_index": 7,
                "case_id": "CASE-7",
                "source_path": "/home/test/a.bag",
                "mapped_source_path": "/home/test/a.bag",
            }
        ],
        check_destination=False,
    )
    assert "sha256sum" in command
    assert "cp " not in command
    assert "mkdir" not in command
    assert "entry_index" not in command
    assert "__CR60_DATA_CASE_BEGIN__7" in command


def test_data_verify_parser_keeps_distinct_entries_even_with_same_case_id():
    entries = [
        {
            "entry_index": 0,
            "case_id": "CASE",
            "source_path": "/home/test/a.bag",
            "mapped_source_path": "/home/test/a.bag",
        },
        {
            "entry_index": 1,
            "case_id": "CASE",
            "source_path": "/home/test/b.blf",
            "mapped_source_path": "/home/test/b.blf",
        },
    ]
    parsed = parse_data_verify_output(_output(), entries=entries)
    assert len(parsed["cases"]) == 2
    assert [item["entry_index"] for item in parsed["cases"]] == [0, 1]
    assert parsed["cases"][0]["source_files"][0]["basename"] == "a.bag"


def test_verify_data_plan_does_not_call_runner_and_flags_unc_without_mount():
    runner = _FakeRunner(_output())
    payload = verify_data(
        runner=runner,
        entries=[
            {"case_id": "CASE", "source_path": r"\\server\share\a.bag"},
            {"case_id": "CASE", "source_path": "/home/test/a.bag"},
        ],
    )
    assert payload["status"] == "planned"
    assert payload["entries"][0]["source_mapping"]["status"] == "needs_confirmation"
    assert len(payload["command"]) > 0
    assert runner.calls == []


def test_verify_data_exec_compares_source_and_destination():
    entries = [
        {
            "case_id": "CASE-1",
            "source_path": "/home/test/source/a.bag",
            "destination_dir": "/home/test/dest",
        },
        {
            "case_id": "CASE-2",
            "source_path": "/home/test/source/b.blf",
            "destination_dir": "/home/test/dest",
        },
    ]
    runner = _FakeRunner(_output())
    payload = verify_data(
        runner=runner,
        entries=entries,
        check_destination=True,
        execute=True,
    )
    assert payload["status"] == "ready"
    assert all(item["comparison"]["status"] == "matched" for item in payload["cases"])
    assert len(runner.calls) == 1


def test_verify_data_marks_destination_mismatch():
    text = _output().replace("\t20\t101\t" + "a" * 64, "\t21\t101\t" + "a" * 64)
    runner = _FakeRunner(text)
    payload = verify_data(
        runner=runner,
        entries=[
            {
                "case_id": "CASE-1",
                "source_path": "/home/test/source/a.bag",
                "destination_dir": "/home/test/dest",
            },
            {
                "case_id": "CASE-2",
                "source_path": "/home/test/source/b.blf",
                "destination_dir": "/home/test/dest",
            },
        ],
        check_destination=True,
        execute=True,
    )
    assert payload["status"] == "partial"
    assert "CASE-2:destination_not_verified" in payload["diagnostics"]


def test_module_is_registered_and_fails_closed_on_blocked_intake(tmp_path: Path):
    assert MODULE_REGISTRY["cr60-data-prep-verify"] is CR60DataPrepVerifyModule
    entry = {item["name"]: item for item in capability_catalog()}["cr60-data-prep-verify"]
    assert entry["expose_to_pi"] is True
    assert entry["requires_approval"] is False
    result = CR60DataPrepVerifyModule(runner=_FakeRunner(_output())).safe_run(
        intake={"status": "blocked"},
        data_paths=["/home/test/a.bag"],
        execute=True,
        output=str(tmp_path / "verify.json"),
    )
    assert isinstance(result, ModuleResult)
    assert result.ok is False
    assert result.data["status"] == "blocked"


def test_module_writes_artifact_and_cli_wires_inputs(tmp_path: Path):
    output = tmp_path / "verify.json"
    result = CR60DataPrepVerifyModule(runner=_FakeRunner(_output())).safe_run(
        data_paths=["/home/test/source/a.bag", "/home/test/source/b.blf"],
        execute=True,
        output=str(output),
    )
    assert result.ok is True
    assert json.loads(output.read_text(encoding="utf-8"))["schema_version"] == "cr60-data-prep-verification.v1"

    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers()
    CR60DataPrepVerifyModule.register_cli(sub)
    args = parser.parse_args(
        ["cr60-data-prep-verify", "--data", "/home/test/a.bag", "--source-prefix", "/mnt/cluster"]
    )
    assert args._module_cls is CR60DataPrepVerifyModule
    assert args.data_paths == ["/home/test/a.bag"]
