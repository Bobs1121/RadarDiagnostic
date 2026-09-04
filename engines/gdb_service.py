# -*- coding: utf-8 -*-
"""Generic headless GDB service primitives.

The service knows only a target and structured GDB command lines.  It has no
ADAS feature names and no built-in breakpoint.  A separate code-analysis
capability supplies source locations/conditions; Pi may then pass the
resulting commands here.  Execution is an explicit, approval-gated side
effect because attaching GDB stops/perturbs a running process.
"""
from __future__ import annotations

import shlex
import subprocess
import time
from dataclasses import dataclass
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Mapping, Protocol


SCHEMA_VERSION = "gdb-session.v1"
_ALLOWED_GDB_COMMANDS = {
    "set",
    "directory",
    "break",
    "tbreak",
    "rbreak",
    "condition",
    "commands",
    "silent",
    "end",
    "bt",
    "backtrace",
    "info",
    "p",
    "print",
    "printf",
    "display",
    "undisplay",
    "continue",
    "c",
    "next",
    "n",
    "step",
    "s",
    "finish",
    "thread",
    "frame",
    "up",
    "down",
    "detach",
    "quit",
}
_BLOCKED_GDB_COMMANDS = {"shell", "python", "source", "define", "document", "add-auto-load-safe-path"}
_PRINT_COMMANDS = {"p", "print"}
_BACKTRACE_RE = re.compile(r"^#(?P<level>\d+)\s+(?P<frame>.+)$")
_GDB_VALUE_RE = re.compile(r"^\$(?P<index>\d+)\s*=\s*(?P<value>.*)$")
_GDB_EXPR_MARKER_RE = re.compile(r"^CR60_GDB_EXPR\s+(?P<body>.*)$")


@dataclass(frozen=True)
class GdbCommandResult:
    command: tuple[str, ...]
    returncode: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    duration_sec: float = 0.0

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": list(self.command),
            "returncode": self.returncode,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "timed_out": self.timed_out,
            "duration_sec": round(self.duration_sec, 6),
            "ok": self.ok,
        }


class GdbCommandExecutor(Protocol):
    def run(self, command: list[str], *, timeout_sec: float) -> GdbCommandResult:
        ...


class LocalGdbCommandExecutor:
    """Execute GDB or SSH argv without a local shell."""

    def run(self, command: list[str], *, timeout_sec: float) -> GdbCommandResult:
        started = time.monotonic()
        frozen = tuple(str(item) for item in command)
        try:
            completed = subprocess.run(
                frozen,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=max(0.1, float(timeout_sec)),
                check=False,
                shell=False,
            )
            return GdbCommandResult(
                command=frozen,
                returncode=completed.returncode,
                stdout=completed.stdout,
                stderr=completed.stderr,
                duration_sec=time.monotonic() - started,
            )
        except subprocess.TimeoutExpired as exc:
            return GdbCommandResult(
                command=frozen,
                returncode=124,
                stdout=_as_text(exc.stdout),
                stderr=_as_text(exc.stderr),
                timed_out=True,
                duration_sec=time.monotonic() - started,
            )
        except OSError as exc:
            return GdbCommandResult(
                command=frozen,
                returncode=127,
                stderr=f"{type(exc).__name__}: {exc}",
                duration_sec=time.monotonic() - started,
            )


def _as_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def validate_gdb_commands(commands: list[str]) -> list[str]:
    """Validate one-line structured GDB commands before execution."""
    errors: list[str] = []
    for index, raw in enumerate(commands):
        command = str(raw or "").strip()
        if not command:
            errors.append(f"command[{index}]_empty")
            continue
        if "\n" in command or "\r" in command or ";" in command:
            errors.append(f"command[{index}]_contains_control_separator")
            continue
        verb = command.split(None, 1)[0].lower()
        if verb in _BLOCKED_GDB_COMMANDS:
            errors.append(f"command[{index}]_blocked:{verb}")
        elif verb not in _ALLOWED_GDB_COMMANDS:
            errors.append(f"command[{index}]_unsupported:{verb}")
    return errors


def _command_verb(command: str) -> str:
    return str(command or "").strip().split(None, 1)[0].lower()


def _command_argument(command: str) -> str:
    text = str(command or "").strip()
    return text.split(None, 1)[1].strip() if " " in text else ""


def _expression_marker(expression: str) -> str:
    """Build a literal marker that does not evaluate the watched expression."""
    escaped = str(expression or "").replace("\\", "\\\\").replace('"', '\\"')
    return f'printf "CR60_GDB_EXPR token=\\"{escaped}\\" phase=\\"unknown\\"\\n"'


def instrument_gdb_print_commands(commands: list[str]) -> list[str]:
    """Add stable expression markers before each print command.

    GDB's ``$N`` output is positional and becomes ambiguous after multiple
    breakpoint stops.  The marker is a literal ``printf`` and does not touch
    process state; the parser uses it to associate the following value with
    the original source token.  Existing markers are not duplicated.
    """
    instrumented: list[str] = []
    for command in commands:
        if _command_verb(command) in _PRINT_COMMANDS:
            expression = _command_argument(command)
            if expression:
                instrumented.append(_expression_marker(expression))
        instrumented.append(str(command))
    return instrumented


def _marker_fields(body: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for token in shlex.split(str(body or ""), posix=True):
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        if key:
            fields[key] = value
    return fields


def _parse_marked_expressions(stdout: str) -> tuple[list[dict[str, Any]], set[str]]:
    """Parse expression markers emitted immediately before a GDB ``print``."""
    lines = [line.strip() for line in str(stdout or "").splitlines()]
    observations: list[dict[str, Any]] = []
    marked_tokens: set[str] = set()
    for index, line in enumerate(lines):
        match = _GDB_EXPR_MARKER_RE.match(line)
        if not match:
            continue
        fields = _marker_fields(match.group("body"))
        expression = str(fields.get("token", "")).strip()
        if not expression:
            continue
        marked_tokens.add(expression)
        raw = ""
        value = ""
        status = "not_observed"
        for following in lines[index + 1 :]:
            if not following:
                continue
            value_match = _GDB_VALUE_RE.match(following)
            if value_match:
                raw = following
                value = value_match.group("value")
                status = "optimized_out" if "optimized out" in value else "observed"
                break
            if _GDB_EXPR_MARKER_RE.match(following):
                break
            if any(marker in following for marker in ("No symbol", "Cannot access memory", "No frame", "No stack")):
                raw = following
                status = "not_found"
                break
        observations.append({
            "expression": expression,
            "status": status,
            "value": value,
            "raw": raw,
            "phase": fields.get("phase", "unknown"),
            "scope": fields.get("scope", ""),
        })
    return observations, marked_tokens


def _parse_variable_observations(stdout: str, commands: list[str]) -> list[dict[str, Any]]:
    """Associate generic ``print`` commands with GDB's ``$N = value`` output.

    GDB batch output does not carry a stable machine-readable envelope.  This
    parser intentionally keeps the raw line and uses the order of print
    commands, rather than guessing feature-specific names.  It reports
    ``optimized_out``/``not_found`` explicitly instead of replacing them with
    a value from another frame.
    """
    print_expressions = [
        _command_argument(command)
        for command in commands
        if _command_verb(command) in _PRINT_COMMANDS and _command_argument(command)
    ]
    output_lines = [line.strip() for line in str(stdout or "").splitlines()]
    marked, marked_tokens = _parse_marked_expressions(stdout)
    # The isolated plan runner evaluates expressions through GDB's embedded
    # Python API so one missing local cannot abort the enclosing breakpoint
    # command list.  Such a transcript has no literal ``p ...`` command in
    # the outer command list, but its marker/value pairs are still authoritative
    # and must be parsed here.
    if not print_expressions and marked:
        return marked
    if not print_expressions:
        return []
    if marked:
        # An instrumented transcript is the only safe way to associate values
        # when a command list contains several self-continuing breakpoints.
        # Keep marked values and explicitly report every unmarked expression as
        # unavailable instead of shifting a later $N onto the wrong token.
        observations = list(marked)
        for expression in print_expressions:
            if expression in marked_tokens:
                continue
            observations.append({
                "expression": expression,
                "status": "not_observed",
                "value": "",
                "raw": "unmarked_expression_in_transcript",
            })
        return observations
    # GDB's plain batch output does not echo which expression generated $N.
    # A single-stop transcript is historically supported; with multiple stack
    # stops the positional association is unsafe and must fail closed.
    if len(re.findall(r"^#0\s+", str(stdout or ""), flags=re.MULTILINE)) > 1:
        return [
            {
                "expression": expression,
                "status": "not_observed",
                "value": "",
                "raw": "ambiguous_unmarked_expression_mapping",
            }
            for expression in print_expressions
        ]
    value_lines = [line for line in output_lines if _GDB_VALUE_RE.match(line)]
    observations: list[dict[str, Any]] = []
    value_index = 0
    for expression in print_expressions:
        raw = value_lines[value_index] if value_index < len(value_lines) else ""
        if raw:
            match = _GDB_VALUE_RE.match(raw)
            value = match.group("value") if match else raw
            status = "optimized_out" if "optimized out" in value else "observed"
        else:
            matching_error = next(
                (
                    line
                    for line in output_lines
                    if "No symbol" in line or "Cannot access memory" in line
                ),
                "",
            )
            raw = matching_error
            value = ""
            status = "not_found" if matching_error else "not_observed"
        observations.append(
            {
                "expression": expression,
                "status": status,
                "value": value,
                "raw": raw,
            }
        )
        if value_lines and value_index < len(value_lines):
            value_index += 1
    return observations


def _parse_local_rows(stdout: str, *, section: str) -> list[dict[str, Any]]:
    """Parse simple ``name = value`` rows from ``info args/locals`` output."""
    rows: list[dict[str, Any]] = []
    for raw in str(stdout or "").splitlines():
        line = raw.strip()
        if not line or line.startswith(("No ", "Thread ", "Breakpoint ", "#")):
            continue
        if " = " not in line or line.startswith("$"):
            continue
        name, value = line.split(" = ", 1)
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(?:\[[^]]+\])?", name.strip()):
            continue
        value_text = value.strip()
        rows.append(
            {
                "name": name.strip(),
                "value": value_text,
                "status": "optimized_out" if "optimized out" in value_text else "observed",
                "section": section,
                "raw": line,
            }
        )
    return rows


def parse_gdb_transcript(
    stdout: str,
    commands: list[str] | None = None,
    *,
    stderr: str = "",
) -> dict[str, Any]:
    """Normalize generic GDB batch output into runtime evidence.

    The result is deliberately feature-neutral.  Consumers may attach a
    source-bound event/radar/object identity, but this function only reports
    what GDB printed: stops, stack frames, args, locals, expressions and
    parser diagnostics.
    """
    command_list = list(commands or [])
    combined = "\n".join(
        item for item in (str(stdout or ""), str(stderr or "")) if item
    )
    lines = [line.strip() for line in combined.splitlines()]
    backtrace: list[dict[str, Any]] = []
    stops: list[str] = []
    for line in lines:
        match = _BACKTRACE_RE.match(line)
        if match:
            backtrace.append(
                {"level": int(match.group("level")), "frame": match.group("frame"), "raw": line}
            )
        if "Breakpoint " in line and ("hit" in line or " at " in line):
            stops.append(line)
    diagnostics: list[str] = []
    if "<optimized out>" in combined:
        diagnostics.append("optimized_out_present")
    if not re.search(r"^CR60_GDB_EXPR\s+", combined, flags=re.MULTILINE) and len(re.findall(r"^#0\s+", combined, flags=re.MULTILINE)) > 1:
        diagnostics.append("unmarked_expression_mapping_ambiguous")
    if any(
        any(
            marker in line
            for marker in (
                "No symbol",
                "Cannot access memory",
                "No frame",
                "No such file or directory",
                "Can't attach",
                "Could not attach",
                "Cannot attach",
                "ptrace:",
                "Operation not permitted",
                "Argument required",
                "No stack",
                "The history is empty",
                "not in executable format",
                "no core file handler",
                "Error in sourced command file",
            )
        )
        for line in lines
    ):
        diagnostics.append("gdb_expression_not_observed")
        diagnostics.append("gdb_command_error_present")
    return {
        "stops": stops,
        "backtrace": backtrace,
        "args": _parse_local_rows(combined, section="args")
        if any(_command_verb(command) == "info" and _command_argument(command).startswith("args") for command in command_list)
        else [],
        "locals": _parse_local_rows(combined, section="locals")
        if any(_command_verb(command) == "info" and _command_argument(command).startswith("locals") for command in command_list)
        else [],
        "expressions": _parse_variable_observations(combined, command_list),
        "diagnostics": diagnostics,
    }


def _target_value(target: Mapping[str, Any], key: str, default: Any = "") -> Any:
    value = target.get(key, default)
    return default if value is None else value


def build_gdb_argv(
    *,
    target: Mapping[str, Any],
    commands: list[str],
    command_file: str = "",
    ssh_binary: str = "ssh",
    connect_timeout_sec: float = 10.0,
) -> list[str]:
    """Build a local or SSH GDB batch argv from a generic target."""
    problems: list[str] = []
    pid = str(_target_value(target, "pid", "")).strip()
    program = str(_target_value(target, "program", "")).strip()
    if not pid and not program:
        problems.append("target_requires_pid_or_program")
    if pid and not pid.isdigit():
        problems.append("target.pid_must_be_numeric")
    command_errors = validate_gdb_commands(commands)
    problems.extend(command_errors)
    if problems:
        raise ValueError("; ".join(problems))

    gdb_path = str(_target_value(target, "gdb_path", "gdb")).strip() or "gdb"
    gdb_args = ["--quiet", "--nx", "--batch"]
    if program:
        gdb_args.append(program)
        if pid:
            gdb_args.append(pid)
    elif pid:
        gdb_args.extend(["-ex", f"attach {pid}"])
    if command_file:
        gdb_args.extend(["--command", str(command_file).strip()])
    else:
        for command in commands:
            gdb_args.extend(["-ex", str(command).strip()])

    host = str(_target_value(target, "host", "")).strip()
    if not host:
        return [gdb_path, *gdb_args]
    user = str(_target_value(target, "user", "")).strip()
    destination = f"{user}@{host}" if user else host
    port = int(_target_value(target, "port", 22))
    ssh_args = [
        ssh_binary,
        "-o",
        "BatchMode=yes",
        "-o",
        f"ConnectTimeout={max(1, int(min(float(connect_timeout_sec), 60.0)))}",
        "-p",
        str(port),
    ]
    identity_file = str(_target_value(target, "identity_file", "")).strip()
    if identity_file:
        ssh_args.extend(["-i", identity_file])
    remote_command = " ".join(shlex.quote(item) for item in [gdb_path, *gdb_args])
    return [*ssh_args, destination, remote_command]


class HeadlessGdbService:
    """Stateless, one-shot GDB batch service with explicit approval."""

    def __init__(
        self,
        *,
        executor: GdbCommandExecutor | None = None,
        timeout_sec: float = 120.0,
    ) -> None:
        self.executor = executor or LocalGdbCommandExecutor()
        self.timeout_sec = max(1.0, float(timeout_sec))

    def run(
        self,
        *,
        target: Mapping[str, Any],
        commands: list[str],
        execute: bool = False,
        approved: bool = False,
    ) -> dict[str, Any]:
        script_path: Path | None = None
        effective_target = dict(target)
        execution_commands = instrument_gdb_print_commands(commands) if execute else list(commands)
        # Older Windows/MinGW GDB builds can split a quoted -ex argument at
        # spaces.  Use a command file for local Windows execution so the same
        # generic service remains usable from a Windows Pi host.  Remote arbe
        # execution still uses Linux GDB's normal -ex path.
        if (
            execute
            and os.name == "nt"
            and not str(target.get("host", "")).strip()
            and commands
        ):
            try:
                handle = tempfile.NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    suffix=".gdb",
                    prefix="cr60_gdb_",
                    delete=False,
                )
                with handle:
                    handle.write("\n".join(str(command).strip() for command in execution_commands))
                    handle.write("\n")
                script_path = Path(handle.name)
                effective_target["command_file"] = str(script_path)
            except OSError as exc:
                return {
                    "schema_version": SCHEMA_VERSION,
                    "status": "blocked",
                    "target": dict(target),
                    "commands": list(commands),
                    "diagnostics": [f"gdb_command_file_create_failed:{type(exc).__name__}: {exc}"],
                }
        try:
            argv = build_gdb_argv(
                target=effective_target,
                commands=execution_commands,
                command_file=str(effective_target.get("command_file", "")),
            )
        except (TypeError, ValueError) as exc:
            if script_path:
                script_path.unlink(missing_ok=True)
            return {
                "schema_version": SCHEMA_VERSION,
                "status": "blocked",
                "target": dict(target),
                "commands": list(commands),
                "execution_commands": list(execution_commands),
                "diagnostics": [str(exc)],
            }
        payload: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "status": "planned",
            "target": dict(target),
            "commands": list(commands),
            "execution_commands": list(execution_commands),
            "argv": list(argv),
            "execute_requested": bool(execute),
            "approved": bool(approved),
            "side_effects": [
                "attach may stop or perturb the target process",
                "continue may change runtime state",
            ],
            "diagnostics": [],
        }
        if not execute:
            if script_path:
                script_path.unlink(missing_ok=True)
            return payload
        if not approved:
            payload["status"] = "approval_required"
            payload["diagnostics"].append("GDB execution requires explicit user/supervisor approval")
            if script_path:
                script_path.unlink(missing_ok=True)
            return payload
        try:
            result = self.executor.run(argv, timeout_sec=self.timeout_sec)
            payload["command_result"] = result.to_dict()
            payload["stdout"] = result.stdout
            payload["stderr"] = result.stderr
            payload["observations"] = parse_gdb_transcript(
                result.stdout,
                execution_commands,
                stderr=result.stderr,
            )
            observation = payload["observations"]
            has_evidence = any(
                observation.get(key)
                for key in ("stops", "backtrace", "args", "locals", "expressions")
            )
            payload["evidence_status"] = (
                "partial"
                if observation.get("diagnostics")
                else "complete"
                if has_evidence
                else "not_available"
            )
            payload["diagnostics"].extend(payload["observations"].get("diagnostics", []))
            payload["status"] = "timeout" if result.timed_out else "succeeded" if result.ok else "failed"
        finally:
            if script_path:
                script_path.unlink(missing_ok=True)
        return payload


__all__ = [
    "GdbCommandExecutor",
    "GdbCommandResult",
    "HeadlessGdbService",
    "LocalGdbCommandExecutor",
    "SCHEMA_VERSION",
    "build_gdb_argv",
    "instrument_gdb_print_commands",
    "parse_gdb_transcript",
    "validate_gdb_commands",
]
