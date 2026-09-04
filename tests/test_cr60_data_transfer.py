from __future__ import annotations

import argparse
import json
from pathlib import Path

from ai.capability.registry import capability_catalog
from ai.modules import MODULE_REGISTRY
from ai.modules.base import ModuleResult
from ai.modules.cr60_data_transfer import CR60DataTransferModule
from engines.arbe.preflight import CommandResult
from engines.arbe.transfer import build_transfer_command, run_transfer


class _FakeRunner:
    def __init__(self, returncode: int = 0, stderr: str = "") -> None:
        self.returncode = returncode
        self.stderr = stderr
        self.calls: list[str] = []

    def run(self, command: str, *, timeout_sec: float) -> CommandResult:
        self.calls.append(command)
        return CommandResult(command, self.returncode, "transfer output\n", self.stderr)


def test_transfer_command_is_explicit_and_shell_quoted():
    command = build_transfer_command(
        script_path="/opt/tools/data_transfert.py",
        input_path="/home/test/list with spaces.txt",
        destination_root="/home/test/CR60 data",
        source_type="list",
        source_prefix="/mnt/cluster",
    )
    assert "data_transfert.py" in command
    assert "--src-type list" in command
    assert "--src /mnt/cluster" in command
    assert "--dst '/home/test/CR60 data'" in command
    assert "git checkout" not in command
    try:
        build_transfer_command(
            script_path="/opt/script.py",
            input_path="/opt/input",
            destination_root="relative/path",
        )
    except ValueError as exc:
        assert "destination_root" in str(exc)
    else:
        raise AssertionError("relative destination was accepted")


def test_transfer_plan_and_approval_gate_do_not_run_without_approval():
    runner = _FakeRunner()
    planned = run_transfer(
        runner=runner,
        script_path="/opt/tools/data_transfert.py",
        input_path="/home/test/list.txt",
        destination_root="/home/test/data",
    )
    assert planned["status"] == "planned"
    assert runner.calls == []

    approval = run_transfer(
        runner=runner,
        script_path="/opt/tools/data_transfert.py",
        input_path="/home/test/list.txt",
        destination_root="/home/test/data",
        execute=True,
        approved=False,
    )
    assert approval["status"] == "approval_required"
    assert runner.calls == []


def test_transfer_exec_preserves_upstream_result_and_failure():
    runner = _FakeRunner()
    payload = run_transfer(
        runner=runner,
        server_host="10.0.0.1",
        server_user="tester",
        script_path="/opt/tools/data_transfert.py",
        input_path="/home/test/list.txt",
        destination_root="/home/test/data",
        execute=True,
        approved=True,
    )
    assert payload["status"] == "completed"
    assert payload["upstream"] == "bosch-data-transfert"
    assert len(runner.calls) == 1

    failed = run_transfer(
        runner=_FakeRunner(returncode=3, stderr="copy failed"),
        script_path="/opt/tools/data_transfert.py",
        input_path="/home/test/list.txt",
        destination_root="/home/test/data",
        execute=True,
        approved=True,
    )
    assert failed["status"] == "failed"
    assert "data_transfer_returncode:3" in failed["diagnostics"]


def test_module_is_registered_approval_gated_and_writes_artifact(tmp_path: Path):
    assert MODULE_REGISTRY["cr60-data-transfer"] is CR60DataTransferModule
    entry = {item["name"]: item for item in capability_catalog()}["cr60-data-transfer"]
    assert entry["expose_to_pi"] is True
    assert entry["requires_approval"] is True
    output = tmp_path / "transfer.json"
    runner = _FakeRunner()
    result = CR60DataTransferModule(runner=runner).safe_run(
        server_host="10.0.0.1",
        server_user="tester",
        script_path="/opt/tools/data_transfert.py",
        input_path="/home/test/list.txt",
        destination_root="/home/test/data",
        execute=True,
        approved=False,
        output=str(output),
    )
    assert isinstance(result, ModuleResult)
    assert result.ok is True
    assert result.data["status"] == "approval_required"
    assert not runner.calls
    assert json.loads(output.read_text(encoding="utf-8"))["schema_version"] == "cr60-data-transfer-session.v1"


def test_transfer_module_cli_wiring():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers()
    CR60DataTransferModule.register_cli(sub)
    args = parser.parse_args(
        [
            "cr60-data-transfer",
            "--script-path",
            "/opt/tools/data_transfert.py",
            "--input-path",
            "/home/test/list.txt",
            "--destination-root",
            "/home/test/data",
            "--execute",
            "--approved",
        ]
    )
    assert args._module_cls is CR60DataTransferModule
    assert args.approved is True
