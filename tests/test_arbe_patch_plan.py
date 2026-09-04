from __future__ import annotations

import argparse
import json
from pathlib import Path

from ai.capability.registry import capability_catalog
from ai.modules import MODULE_REGISTRY
from ai.modules.arbe_patch_plan import ArbePatchPlanModule
from ai.modules.base import ModuleResult
from engines.arbe.patch_plan import (
    build_patch_plan_command,
    parse_patch_plan_output,
    resolve_patch_plan,
)
from engines.arbe.preflight import CommandResult


CHECKS = [
    {
        "id": "gui_task_time",
        "scope": "arbe",
        "relative_path": "src/visualization_node.cpp",
        "patterns": ["PostProcessMainTI", "taskTime"],
        "required": True,
    },
    {
        "id": "optional_macro",
        "scope": "algo",
        "relative_path": "include/paraDefine.h",
        "patterns": [r"PF_BUILD_FUNTEST_SGU_INJECTION"],
        "required": False,
    },
]


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


def _output(*, optional_present: bool = False, dirty: str = "no") -> str:
    optional_match = "7:#define PF_BUILD_FUNTEST_SGU_INJECTION 1\n" if optional_present else ""
    return "\n".join(
        [
            "__CR60_PATCH_PLAN_BEGIN__",
            "__CR60_PATCH_SOURCE_BEGIN__",
            "outer_head\t" + "a" * 40,
            "outer_branch\tdevelop_LGU_Simulation",
            f"outer_dirty\t{dirty}",
            "algo_head\t" + "b" * 40,
            "algo_branch\tDETACHED",
            "algo_dirty\tno",
            "__CR60_PATCH_SOURCE_END__",
            "__CR60_PATCH_CHECK_BEGIN__gui_task_time",
            "path\t/home/test/arbe/src/visualization_node.cpp",
            "file_present\ttrue",
            "sha256\t" + "c" * 64,
            "__CR60_PATCH_MATCH_BEGIN__0",
            "12: PostProcessMainTI(... taskTime, taskTime)",
            "__CR60_PATCH_MATCH_END__0",
            "__CR60_PATCH_MATCH_BEGIN__1",
            "12: PostProcessMainTI(... taskTime, taskTime)",
            "__CR60_PATCH_MATCH_END__1",
            "__CR60_PATCH_DIFF_BEGIN__",
            "@@ -12 +12 @@",
            "+PostProcessMainTI(... taskTime, taskTime)",
            "__CR60_PATCH_DIFF_END__",
            "__CR60_PATCH_CHECK_END__gui_task_time",
            "__CR60_PATCH_CHECK_BEGIN__optional_macro",
            "path\t/home/test/algo/include/paraDefine.h",
            "file_present\ttrue",
            "sha256\t" + "d" * 64,
            "__CR60_PATCH_MATCH_BEGIN__0",
            optional_match.rstrip("\n"),
            "__CR60_PATCH_MATCH_END__0",
            "__CR60_PATCH_DIFF_BEGIN__",
            "__CR60_PATCH_DIFF_END__",
            "__CR60_PATCH_CHECK_END__optional_macro",
            "__CR60_PATCH_PLAN_END__",
            "",
        ]
    )


def test_patch_parser_preserves_source_hash_and_diff():
    parsed = parse_patch_plan_output(_output(optional_present=True), checks=CHECKS)
    assert parsed["source"]["outer_head"] == "a" * 40
    assert parsed["checks"][0]["sha256"] == "c" * 64
    assert "taskTime" in parsed["checks"][0]["diff"]
    assert parsed["checks"][1]["matches"][0]


def test_patch_command_is_parameterized_and_non_mutating():
    command = build_patch_plan_command(
        arbe_root="/home/test/arbe",
        algo_source_root="/home/test/algo",
        checks=CHECKS,
    )
    assert "git checkout" not in command
    assert "git fetch" not in command
    assert " diff --no-ext-diff" in command
    assert "cp " not in command
    try:
        build_patch_plan_command(
            arbe_root="/home/test/arbe",
            checks=[{"id": "bad", "scope": "arbe", "relative_path": "../x", "patterns": ["x"]}],
        )
    except ValueError as exc:
        assert "traversal" in str(exc)
    else:
        raise AssertionError("path traversal check was accepted")


def test_patch_plan_is_plan_only_without_runner_call():
    runner = _FakeRunner(_output())
    payload = resolve_patch_plan(
        runner=runner,
        arbe_root="/home/test/arbe",
        algo_source_root="/home/test/algo",
        checks=CHECKS,
    )
    assert payload["status"] == "planned"
    assert runner.calls == []


def test_patch_plan_reports_required_and_optional_checks_separately():
    runner = _FakeRunner(_output(optional_present=False, dirty="yes"))
    payload = resolve_patch_plan(
        runner=runner,
        arbe_root="/home/test/arbe",
        algo_source_root="/home/test/algo",
        checks=CHECKS,
        execute=True,
    )
    assert payload["status"] == "partial"
    assert payload["checks"][0]["status"] == "present"
    assert payload["checks"][1]["status"] == "missing"
    assert "outer_workspace_dirty" in payload["diagnostics"]
    assert "optional_simulation_check_missing" in payload["diagnostics"]


def test_patch_plan_missing_required_check_needs_action():
    missing = _output().replace("file_present\ttrue", "file_present\tfalse", 1)
    runner = _FakeRunner(missing)
    payload = resolve_patch_plan(
        runner=runner,
        arbe_root="/home/test/arbe",
        algo_source_root="/home/test/algo",
        checks=CHECKS,
        execute=True,
    )
    assert payload["status"] == "needs_action"
    assert payload["checks"][0]["status"] == "not_available"


def test_patch_module_is_registered_and_fails_closed_on_blocked_intake(tmp_path: Path):
    assert MODULE_REGISTRY["arbe-patch-plan"] is ArbePatchPlanModule
    entry = {item["name"]: item for item in capability_catalog()}["arbe-patch-plan"]
    assert entry["expose_to_pi"] is True
    assert entry["requires_approval"] is False
    result = ArbePatchPlanModule(runner=_FakeRunner(_output())).safe_run(
        intake={"status": "blocked"},
        arbe_root="/home/test/arbe",
        checks=CHECKS,
        execute=True,
        output=str(tmp_path / "patch.json"),
    )
    assert isinstance(result, ModuleResult)
    assert result.ok is False
    assert result.data["status"] == "blocked"


def test_patch_module_writes_result_and_cli_parses_checks(tmp_path: Path):
    output = tmp_path / "patch.json"
    result = ArbePatchPlanModule(runner=_FakeRunner(_output(optional_present=True))).safe_run(
        arbe_root="/home/test/arbe",
        algo_source_root="/home/test/algo",
        checks=CHECKS,
        execute=True,
        output=str(output),
    )
    assert result.ok is True
    assert json.loads(output.read_text(encoding="utf-8"))["schema_version"] == "arbe-patch-plan.v1"

    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers()
    ArbePatchPlanModule.register_cli(sub)
    args = parser.parse_args(
        [
            "arbe-patch-plan",
            "--arbe-root",
            "/home/test/arbe",
            "--checks",
            json.dumps(CHECKS),
        ]
    )
    module = ArbePatchPlanModule.from_cli_args(args)
    assert isinstance(module, ArbePatchPlanModule)
    assert args.checks[0]["id"] == "gui_task_time"
