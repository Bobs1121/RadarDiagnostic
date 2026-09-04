# -*- coding: utf-8 -*-
from __future__ import annotations

from ai.capability.registry import capability_catalog
from ai.modules import MODULE_REGISTRY
from ai.modules.gdb_service import GdbServiceModule
from engines.gdb_service import (
    GdbCommandResult,
    HeadlessGdbService,
    build_gdb_argv,
    parse_gdb_transcript,
    instrument_gdb_print_commands,
    validate_gdb_commands,
)


class _FakeExecutor:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def run(self, command: list[str], *, timeout_sec: float) -> GdbCommandResult:
        del timeout_sec
        self.calls.append(command)
        return GdbCommandResult(tuple(command), 0, "hit\n")


def test_gdb_service_has_no_default_breakpoint_and_builds_remote_argv():
    target = {
        "host": "10.190.171.44",
        "user": "hoz2wx",
        "port": 22,
        "pid": 3662064,
        "program": "/home/test/arbe_visualization_engine",
        "gdb_path": "/usr/bin/gdb",
    }
    commands = ["set pagination off", "break src/algo/gate.c:42 if sObj->objID == 44", "p sObj"]
    argv = build_gdb_argv(target=target, commands=commands)
    assert argv[0] == "ssh"
    assert argv[-2] == "hoz2wx@10.190.171.44"
    assert "/usr/bin/gdb" in argv[-1]
    assert "break src/algo/gate.c:42 if sObj->objID == 44" in argv[-1]
    assert "FCTA" not in " ".join(argv)


def test_gdb_service_blocks_shell_escape_and_unapproved_execution():
    assert any("blocked:shell" in item for item in validate_gdb_commands(["shell rm -rf /tmp/x"]))
    fake = _FakeExecutor()
    service = HeadlessGdbService(executor=fake)
    target = {"pid": 42, "program": "/tmp/program"}
    commands = ["p frame_counter"]
    planned = service.run(target=target, commands=commands)
    assert planned["status"] == "planned"
    assert fake.calls == []
    blocked = service.run(target=target, commands=commands, execute=True, approved=False)
    assert blocked["status"] == "approval_required"
    assert fake.calls == []
    executed = service.run(target=target, commands=commands, execute=True, approved=True)
    assert executed["status"] == "succeeded"
    assert fake.calls
    assert any("CR60_GDB_EXPR" in item for item in executed["execution_commands"])


def test_gdb_service_module_is_registered_and_plan_is_pi_callable():
    result = GdbServiceModule().safe_run(
        target={"pid": 42, "program": "/tmp/program"},
        commands=["p frame_counter"],
    )
    assert result.ok is True
    assert result.data["schema_version"] == "gdb-session.v1"
    assert result.data["status"] == "planned"
    assert MODULE_REGISTRY["gdb-service"] is GdbServiceModule
    catalog = {item["name"]: item for item in capability_catalog()}
    assert "atomic" in catalog["gdb-service"]["tags"]
    assert catalog["gdb-service"]["parameters"]["required"] == ["target", "commands"]


def test_gdb_transcript_is_normalized_without_feature_specific_assumptions():
    transcript = """Breakpoint 1, gate () at gate.c:42
#0  gate () at gate.c:42
#1  main () at main.c:9
frame_counter = 47877
sObj = <optimized out>
$1 = 47877
$2 = <optimized out>
"""
    observations = parse_gdb_transcript(
        transcript,
        ["bt 12", "info locals", "p frame_counter", "p sObj"],
    )
    assert observations["stops"]
    assert observations["backtrace"][0]["level"] == 0
    assert {row["name"] for row in observations["locals"]} == {"frame_counter", "sObj"}
    assert observations["expressions"][0]["status"] == "observed"
    assert observations["expressions"][1]["status"] == "optimized_out"
    assert "optimized_out_present" in observations["diagnostics"]


def test_executed_gdb_service_contains_structured_observations():
    class _TranscriptExecutor:
        def run(self, command: list[str], *, timeout_sec: float) -> GdbCommandResult:
            del timeout_sec
            return GdbCommandResult(
                tuple(command),
                0,
                "#0  gate () at gate.c:42\n$1 = 7\n",
            )

    result = HeadlessGdbService(executor=_TranscriptExecutor()).run(
        target={"pid": 42, "program": "/tmp/program"},
        commands=["bt 2", "p frame_counter"],
        execute=True,
        approved=True,
    )
    assert result["status"] == "succeeded"
    assert result["observations"]["expressions"][0]["value"] == "7"


def test_gdb_transcript_keeps_stderr_failures_as_evidence_diagnostics():
    observations = parse_gdb_transcript(
        "",
        ["p missing_symbol"],
        stderr="No symbol \"missing_symbol\" in current context.\n",
    )
    assert observations["expressions"][0]["status"] == "not_found"
    assert "gdb_command_error_present" in observations["diagnostics"]


def test_gdb_transcript_uses_literal_markers_for_repeated_stops():
    commands = instrument_gdb_print_commands(["bt 2", "p ego.speed", "p sObj->objID"])
    assert commands[1].startswith("printf \"CR60_GDB_EXPR")
    transcript = (
        'CR60_GDB_EXPR token="ego.speed" phase="unknown"\n'
        "$1 = 4.5\n"
        'CR60_GDB_EXPR token="sObj->objID" phase="unknown"\n'
        "$2 = 44\n"
    )
    observations = parse_gdb_transcript(transcript, commands)
    assert [(item["expression"], item["value"]) for item in observations["expressions"]] == [
        ("ego.speed", "4.5"),
        ("sObj->objID", "44"),
    ]
    assert "unmarked_expression_mapping_ambiguous" not in observations["diagnostics"]


def test_gdb_transcript_parses_resilient_plan_markers_without_outer_print_commands():
    transcript = (
        'CR60_GDB_EXPR token="i" phase="during" scope="Handler"\n'
        "$1 = 0\n"
        'CR60_GDB_EXPR token="missing_local" phase="during" scope="Handler"\n'
        'CR60_GDB_ERROR token="missing_local" error=No symbol "missing_local" in current context.\n'
    )
    observations = parse_gdb_transcript(transcript, ["python", "end"])
    assert [(item["expression"], item["status"]) for item in observations["expressions"]] == [
        ("i", "observed"),
        ("missing_local", "not_found"),
    ]


def test_gdb_transcript_does_not_shift_unmarked_values_across_stops():
    observations = parse_gdb_transcript(
        "#0 first() at a.c:1\n$1 = 4\n#0 second() at b.c:2\n$2 = 44\n",
        ["p ego.speed", "p sObj->objID"],
    )
    assert all(item["status"] == "not_observed" for item in observations["expressions"])
    assert "unmarked_expression_mapping_ambiguous" in observations["diagnostics"]


def test_gdb_plan_does_not_create_a_deleted_windows_script():
    from engines.gdb_service import HeadlessGdbService

    planned = HeadlessGdbService().run(
        target={"program": r"C:\\MinGW\\bin\\gdb.exe"},
        commands=["p 1"],
        execute=False,
    )
    assert planned["status"] == "planned"
    assert "--command" not in planned["argv"]
