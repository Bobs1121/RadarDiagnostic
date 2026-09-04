from __future__ import annotations

import argparse
import json
from pathlib import Path

from ai.capability.registry import capability_catalog
from ai.modules import MODULE_REGISTRY
from ai.modules.arbe_cuda_resolve import ArbeCudaResolveModule
from ai.modules.base import ModuleResult
from engines.arbe.cuda import (
    build_cuda_resolve_command,
    parse_cuda_resolve_output,
    resolve_cuda,
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
        return CommandResult(
            command=command,
            returncode=self.returncode,
            stdout=self.stdout,
            stderr=self.stderr,
        )


def _scan_output() -> str:
    return "\n".join(
        [
            "__CR60_CUDA_SOURCE_BEGIN__",
            "directory_present",
            "200\t100\t" + "a" * 64 + "\t/home/test/algo/coem/CAR_A/tools/container_input/08_CustData/CUDA_A_old.xlsx",
            "300\t200\t" + "b" * 64 + "\t/home/test/algo/coem/CAR_A/tools/container_input/08_CustData/CUDA_A_new.xlsx",
            "__CR60_CUDA_SOURCE_END__",
            "__CR60_CONFIG_BEGIN__",
            "53:  xlsx_path: \"CUDA_A_old.xlsx\"",
            "54:  xlsx_sheet: \"SHEET_A\"",
            "75:  type: CAR_A",
            "__CR60_CONFIG_END__",
            "",
        ]
    )


def test_parser_preserves_candidates_and_config_provenance():
    payload = parse_cuda_resolve_output(_scan_output())
    assert payload["cuda_source_dir_status"] == "present"
    assert payload["candidates"][0]["basename"] == "CUDA_A_new.xlsx"
    assert payload["candidates"][0]["sha256"] == "b" * 64
    assert payload["configuration"]["resolved"] == {
        "xlsx_path": "CUDA_A_old.xlsx",
        "xlsx_sheet": "SHEET_A",
        "type": "CAR_A",
    }
    assert payload["configuration"]["values"]["xlsx_path"][0]["line"] == 53


def test_command_is_read_only_and_parameterized():
    command = build_cuda_resolve_command(
        arbe_root="/home/test/arbe",
        algo_source_root="/home/test/arbe/src/algo_source",
        vehicle="CAR_A",
    )
    assert "find /home/test/arbe/src/algo_source/coem/CAR_A/tools/container_input/08_CustData" in command
    assert "sha256sum" in command
    assert "git checkout" not in command
    assert "cp " not in command
    try:
        build_cuda_resolve_command(arbe_root="/home/test/arbe", vehicle="../CAR_A")
    except ValueError as exc:
        assert "safe path component" in str(exc)
    else:
        raise AssertionError("path traversal vehicle was accepted")


def test_resolve_cuda_plan_does_not_call_runner():
    runner = _FakeRunner(_scan_output())
    payload = resolve_cuda(
        runner=runner,
        arbe_root="/home/test/arbe",
        vehicle="CAR_A",
        coem="CUSTOMER_A",
        expected_sheet="SHEET_A",
    )
    assert payload["status"] == "planned"
    assert payload["target"]["coem"] == "CUSTOMER_A"
    assert runner.calls == []


def test_resolve_cuda_exec_selects_latest_and_reports_config_drift():
    runner = _FakeRunner(_scan_output())
    payload = resolve_cuda(
        runner=runner,
        arbe_root="/home/test/arbe",
        vehicle="CAR_A",
        expected_sheet="SHEET_A",
        execute=True,
    )
    assert payload["status"] == "ready"
    assert payload["selected"]["basename"] == "CUDA_A_new.xlsx"
    assert payload["selected"]["selection_basis"] == "highest_remote_mtime_then_path"
    assert payload["configuration"]["alignment"] == "needs_update"
    assert "config_xlsx_path_differs_from_latest_candidate" in payload["diagnostics"]
    assert len(runner.calls) == 1


def test_resolve_cuda_can_derive_target_from_intake_and_write_artifact(tmp_path: Path):
    runner = _FakeRunner(_scan_output())
    output = tmp_path / "cuda.json"
    intake = {
        "schema_version": "cr60-analysis-intake.v1",
        "handoff_id": "handoff-1",
        "environment": {
            "server": {"host": "10.0.0.1", "user": "tester", "port": 2222},
            "arbe": {
                "workspace": "/home/test/arbe",
                "algo_source_root": "/home/test/arbe/src/algo_source",
            },
            "vehicle": {"model": "CAR_A", "coem": "CUSTOMER_A", "cuda_sheet": "SHEET_A"},
        },
    }
    result = ArbeCudaResolveModule(runner=runner).safe_run(
        intake=intake,
        execute=True,
        output=str(output),
    )
    assert isinstance(result, ModuleResult)
    assert result.ok is True
    assert result.data["target"]["vehicle"] == "CAR_A"
    assert result.data["target"]["server_host"] == "10.0.0.1"
    assert result.data["target"]["server_port"] == 2222
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert saved["schema_version"] == "arbe-cuda-resolution.v1"
    assert str(output) in result.artifacts


def test_resolve_cuda_missing_target_is_blocked_without_guessing():
    runner = _FakeRunner(_scan_output())
    result = ArbeCudaResolveModule(runner=runner).safe_run(
        arbe_root="/home/test/arbe",
        execute=True,
    )
    assert result.ok is False
    assert result.data["status"] == "blocked"
    assert "missing_input:vehicle" in result.data["diagnostics"]
    assert runner.calls == []


def test_resolve_cuda_does_not_bypass_blocked_intake():
    runner = _FakeRunner(_scan_output())
    payload = resolve_cuda(
        runner=runner,
        intake={"schema_version": "cr60-analysis-intake.v1", "status": "blocked"},
        arbe_root="/home/test/arbe",
        vehicle="CAR_A",
        execute=True,
    )
    assert payload["status"] == "blocked"
    assert "missing_input:intake_blocked_requires_confirmation" in payload["diagnostics"]
    assert runner.calls == []


def test_module_is_registered_and_cli_wiring_is_stable():
    assert MODULE_REGISTRY["arbe-cuda-resolve"] is ArbeCudaResolveModule
    entry = {item["name"]: item for item in capability_catalog()}["arbe-cuda-resolve"]
    assert entry["expose_to_pi"] is True
    assert entry["requires_approval"] is False
    assert "vehicle" in entry["parameters"]["properties"]

    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers()
    ArbeCudaResolveModule.register_cli(sub)
    args = parser.parse_args(
        [
            "arbe-cuda-resolve",
            "--arbe-root",
            "/home/test/arbe",
            "--vehicle",
            "CAR_A",
            "--execute",
        ]
    )
    assert args._module_cls is ArbeCudaResolveModule
    assert args.execute is True
