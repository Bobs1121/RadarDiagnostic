from __future__ import annotations

import argparse
import json
from pathlib import Path

from ai.capability.registry import capability_catalog
from ai.modules import MODULE_REGISTRY
from ai.modules.arbe_source_resolve import ArbeSourceResolveModule
from ai.modules.base import ModuleResult
from engines.arbe.preflight import CommandResult
from engines.arbe.source import (
    build_source_resolve_command,
    derive_ref_from_version,
    parse_source_resolve_output,
    resolve_source,
)


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


def _source_output(*, dirty: str = "no", branch: str = "DETACHED", branch_local: str = "no", tag_local: str = "yes") -> str:
    return "\n".join(
        [
            "__CR60_SOURCE_RESOLUTION_BEGIN__",
            "head\t" + "a" * 40,
            f"branch\t{branch}",
            "exact_tag\tCURRENT_TAG",
            f"dirty\t{dirty}",
            "target_ref\tBYD_UKE_BL03RC02.7",
            f"target_branch_local\t{branch_local}",
            f"target_tag_local\t{tag_local}",
            "__CR60_SOURCE_RESOLUTION_END__",
            "",
        ]
    )


def test_derive_ref_requires_explicit_configured_mapping():
    assert derive_ref_from_version(software_version="BL03RC02.7_S")["status"] == "not_configured"
    result = derive_ref_from_version(
        software_version="BL03RC02.7_S",
        ref_prefix="BYD_UKE_",
        version_suffix_strip="_S",
    )
    assert result["status"] == "derived"
    assert result["normalized_version"] == "BL03RC02.7"
    assert result["derived_ref"] == "BYD_UKE_BL03RC02.7"


def test_source_parser_keeps_current_identity_and_remote_refs():
    text = _source_output() + "\n".join(
        [
            "__CR60_SOURCE_REMOTE_BEGIN__",
            "b" * 40 + "\trefs/tags/BYD_UKE_BL03RC02.7",
            "__CR60_SOURCE_REMOTE_END__",
        ]
    )
    parsed = parse_source_resolve_output(text)
    assert parsed["status"] == "ready"
    assert parsed["observed"]["head"] == "a" * 40
    assert parsed["observed"]["dirty"] == "no"
    assert parsed["remote_refs"][0]["ref"] == "refs/tags/BYD_UKE_BL03RC02.7"


def test_command_never_fetches_or_checks_out():
    command = build_source_resolve_command(
        algo_source_root="/home/test/algo",
        requested_ref="feature/runtime-debug",
        remote_query=True,
    )
    assert "git checkout" not in command
    assert "git fetch" not in command
    assert "ls-remote" in command
    assert "feature/runtime-debug" in command
    try:
        build_source_resolve_command(algo_source_root="/home/test/algo", requested_ref="bad ref")
    except ValueError as exc:
        assert "whitespace" in str(exc)
    else:
        raise AssertionError("invalid ref was accepted")


def test_resolve_source_plan_does_not_call_runner():
    runner = _FakeRunner(_source_output())
    payload = resolve_source(
        runner=runner,
        algo_source_root="/home/test/algo",
        requested_ref="TARGET",
    )
    assert payload["status"] == "planned"
    assert payload["resolution"]["effective_ref"] == "TARGET"
    assert runner.calls == []


def test_resolve_source_exec_reports_local_target_and_dirty_state():
    runner = _FakeRunner(_source_output(dirty="yes", tag_local="no", branch_local="yes"))
    payload = resolve_source(
        runner=runner,
        algo_source_root="/home/test/algo",
        requested_ref="BYD_UKE_BL03RC02.7",
        execute=True,
    )
    assert payload["status"] == "partial"
    assert payload["resolution"]["status"] == "resolved_local"
    assert "algo_source_dirty_requires_confirmation_before_checkout" in payload["diagnostics"]
    assert payload["current_source"]["head"] == "a" * 40


def test_resolve_source_conflicting_explicit_and_derived_ref_is_blocked():
    runner = _FakeRunner(_source_output())
    payload = resolve_source(
        runner=runner,
        algo_source_root="/home/test/algo",
        requested_ref="OTHER",
        software_version="BL03RC02.7_S",
        ref_prefix="BYD_UKE_",
        version_suffix_strip="_S",
    )
    assert payload["status"] == "blocked"
    assert "requested_ref_conflicts_with_configured_version_mapping" in payload["diagnostics"]
    assert runner.calls == []


def test_source_module_derives_inputs_from_intake_and_writes_artifact(tmp_path: Path):
    runner = _FakeRunner(_source_output())
    output = tmp_path / "source.json"
    intake = {
        "schema_version": "cr60-analysis-intake.v1",
        "environment": {
            "server": {"host": "10.0.0.1", "user": "tester", "port": 22},
            "arbe": {"workspace": "/home/test/arbe", "algo_source_root": "/home/test/algo"},
            "build": {"software_version": "BL03RC02.7_S"},
        },
    }
    result = ArbeSourceResolveModule(runner=runner).safe_run(
        intake=intake,
        ref_prefix="BYD_UKE_",
        version_suffix_strip="_S",
        execute=True,
        output=str(output),
    )
    assert isinstance(result, ModuleResult)
    assert result.ok is True
    assert result.data["resolution"]["effective_ref"] == "BYD_UKE_BL03RC02.7"
    assert result.data["target"]["server_host"] == "10.0.0.1"
    assert json.loads(output.read_text(encoding="utf-8"))["schema_version"] == "arbe-source-resolution.v1"


def test_source_module_is_registered_and_cli_wiring_is_stable():
    assert MODULE_REGISTRY["arbe-source-resolve"] is ArbeSourceResolveModule
    entry = {item["name"]: item for item in capability_catalog()}["arbe-source-resolve"]
    assert entry["expose_to_pi"] is True
    assert entry["requires_approval"] is False
    assert "requested_ref" in entry["parameters"]["properties"]

    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers()
    ArbeSourceResolveModule.register_cli(sub)
    args = parser.parse_args(
        [
            "arbe-source-resolve",
            "--algo-source-root",
            "/home/test/algo",
            "--requested-ref",
            "TARGET",
        ]
    )
    assert args._module_cls is ArbeSourceResolveModule


def test_source_module_does_not_bypass_blocked_intake():
    runner = _FakeRunner(_source_output())
    result = ArbeSourceResolveModule(runner=runner).safe_run(
        intake={"schema_version": "cr60-analysis-intake.v1", "status": "blocked"},
        algo_source_root="/home/test/algo",
        requested_ref="TARGET",
        execute=True,
    )
    assert result.ok is False
    assert result.data["status"] == "blocked"
    assert runner.calls == []
