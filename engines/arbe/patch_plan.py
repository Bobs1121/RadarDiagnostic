# -*- coding: utf-8 -*-
"""Read-only simulation-patch inspection for a configured arbe workspace.

The upstream build skill has a small set of simulation-adaptation checks.  We
expose them as data-driven checks rather than embedding a mutating patcher:
the caller may replace the check list when an arbe version changes its source
layout or interface.  This engine only reads files, hashes them, inspects
matches and captures the relevant git diff.
"""
from __future__ import annotations

import re
import shlex
from pathlib import PurePosixPath
from typing import Any, Mapping, Protocol

from .preflight import CommandResult


SCHEMA_VERSION = "arbe-patch-plan.v1"
_BEGIN = "__CR60_PATCH_PLAN_BEGIN__"
_END = "__CR60_PATCH_PLAN_END__"
_SOURCE_BEGIN = "__CR60_PATCH_SOURCE_BEGIN__"
_SOURCE_END = "__CR60_PATCH_SOURCE_END__"
_CHECK_BEGIN = "__CR60_PATCH_CHECK_BEGIN__"
_CHECK_END = "__CR60_PATCH_CHECK_END__"
_MATCH_BEGIN = "__CR60_PATCH_MATCH_BEGIN__"
_MATCH_END = "__CR60_PATCH_MATCH_END__"
_DIFF_BEGIN = "__CR60_PATCH_DIFF_BEGIN__"
_DIFF_END = "__CR60_PATCH_DIFF_END__"
_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


class PatchPlanRunner(Protocol):
    def run(self, command: str, *, timeout_sec: float) -> CommandResult:
        ...


DEFAULT_CHECKS: list[dict[str, Any]] = [
    {
        "id": "visualization_post_process_task_time",
        "scope": "arbe",
        "relative_path": "src/arbe_phoenix_radar_driver-master/arbe_gui/src/arbe_visualization_engine/visualization_node.cpp",
        "patterns": [r"PostProcessMainTI", r"taskTime[ \t]*,[ \t]*taskTime"],
        "required": True,
        "description": "GUI simulation call must expose the current taskTime to the algorithm host",
    },
    {
        "id": "buildmodel_ros_gui",
        "scope": "algo",
        "relative_path": "adas/symmetry/perception/include/paraDefine.h",
        "patterns": [r"^[[:space:]]*#define[[:space:]]+BUILDMODEL[[:space:]]+2\b"],
        "required": True,
        "description": "ROS GUI build model macro",
    },
    {
        "id": "hilmodel_sgu",
        "scope": "algo",
        "relative_path": "adas/symmetry/perception/include/paraDefine.h",
        "patterns": [r"^[[:space:]]*#define[[:space:]]+HILMODEL[[:space:]]+2\b"],
        "required": True,
        "description": "SGU/HILMODEL=2 compile-time mode",
    },
    {
        "id": "sgu_injection_macro",
        "scope": "algo",
        "relative_path": "adas/symmetry/perception/include/paraDefine.h",
        "patterns": [r"^[ \t]*#define[ \t]+PF_BUILD_FUNTEST_SGU_INJECTION\b"],
        "required": False,
        "description": "Optional SGU injection compile-time define; an #ifdef reference alone is not treated as enabled",
    },
]


def _q(value: str) -> str:
    return shlex.quote(str(value))


def _validate_id(value: str, field: str) -> str:
    text = str(value or "").strip()
    if not text or not _ID_RE.fullmatch(text):
        raise ValueError(f"{field} must match [A-Za-z0-9_.-]+")
    return text


def _validate_relative_path(value: str, field: str) -> str:
    text = str(value or "").strip().replace("\\", "/")
    path = PurePosixPath(text)
    if not text or text.startswith("/") or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"{field} must be a relative path without traversal")
    if any(ord(char) < 32 for char in text):
        raise ValueError(f"{field} contains a control character")
    return text


def _normalise_checks(checks: list[Mapping[str, Any]] | None) -> list[dict[str, Any]]:
    raw_checks = checks if checks is not None else DEFAULT_CHECKS
    if not isinstance(raw_checks, list) or not raw_checks:
        raise ValueError("checks must be a non-empty list")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_checks):
        if not isinstance(raw, Mapping):
            raise ValueError(f"checks[{index}] must be an object")
        check_id = _validate_id(str(raw.get("id", "")), f"checks[{index}].id")
        if check_id in seen:
            raise ValueError(f"duplicate check id: {check_id}")
        seen.add(check_id)
        scope = str(raw.get("scope", "")).strip().lower()
        if scope not in {"arbe", "algo"}:
            raise ValueError(f"checks[{index}].scope must be arbe or algo")
        relative_path = _validate_relative_path(
            str(raw.get("relative_path", raw.get("path", ""))),
            f"checks[{index}].relative_path",
        )
        patterns = raw.get("patterns", [])
        if isinstance(patterns, str):
            patterns = [patterns]
        if not isinstance(patterns, list) or not patterns:
            raise ValueError(f"checks[{index}].patterns must be a non-empty list")
        clean_patterns: list[str] = []
        for pattern_index, pattern in enumerate(patterns):
            pattern_text = str(pattern or "")
            if not pattern_text or any(ord(char) < 32 for char in pattern_text):
                raise ValueError(
                    f"checks[{index}].patterns[{pattern_index}] is empty or contains control characters"
                )
            # Compile locally so a bad regex is blocked before any remote call.
            try:
                # The remote matcher is grep -E, whose POSIX character
                # classes are not understood by Python's re validator.  Use
                # an equivalent validation spelling without changing the
                # original pattern recorded in the artifact.
                validation_pattern = pattern_text.replace("[[:space:]]", r"[ \t]")
                re.compile(validation_pattern)
            except re.error as exc:
                raise ValueError(
                    f"checks[{index}].patterns[{pattern_index}] invalid regex: {exc}"
                ) from exc
            clean_patterns.append(pattern_text)
        normalized.append(
            {
                "id": check_id,
                "scope": scope,
                "relative_path": relative_path,
                "patterns": clean_patterns,
                "required": bool(raw.get("required", True)),
                "description": str(raw.get("description", "")).strip(),
            }
        )
    return normalized


def build_patch_plan_command(
    *,
    arbe_root: str,
    algo_source_root: str = "",
    checks: list[Mapping[str, Any]] | None = None,
    include_diff: bool = True,
) -> str:
    """Build a read-only command for the configured check definitions."""

    root = str(arbe_root or "").strip()
    if not root:
        raise ValueError("arbe_root is required")
    algo = str(algo_source_root or "").strip() or str(PurePosixPath(root) / "src/algo_source")
    normalized = _normalise_checks(checks)
    commands = [f"printf '%s\\n' {_q(_BEGIN)}"]
    commands.extend(
        [
            f"printf '%s\\n' {_q(_SOURCE_BEGIN)}",
            f"printf 'outer_head\\t'; git -C {_q(root)} rev-parse HEAD 2>/dev/null || true",
            f"printf 'outer_branch\\t'; git -C {_q(root)} symbolic-ref --quiet --short HEAD 2>/dev/null || printf 'DETACHED\\n'",
            f"printf 'outer_dirty\\t'; if test -n \"$(git -C {_q(root)} status --porcelain --untracked-files=all 2>/dev/null)\"; then printf 'yes\\n'; else printf 'no\\n'; fi",
            f"printf 'algo_head\\t'; git -C {_q(algo)} rev-parse HEAD 2>/dev/null || true",
            f"printf 'algo_branch\\t'; git -C {_q(algo)} symbolic-ref --quiet --short HEAD 2>/dev/null || printf 'DETACHED\\n'",
            f"printf 'algo_dirty\\t'; if test -n \"$(git -C {_q(algo)} status --porcelain --untracked-files=all 2>/dev/null)\"; then printf 'yes\\n'; else printf 'no\\n'; fi",
            f"printf '%s\\n' {_q(_SOURCE_END)}",
        ]
    )
    match_script_template = (
        f"printf '%%s\\n' {_q(_MATCH_BEGIN)}%d; "
        "grep -nE %s %s 2>/dev/null | head -40 || true; "
        f"printf '%%s\\n' {_q(_MATCH_END)}%d"
    )
    for check in normalized:
        check_id = check["id"]
        scope_root = root if check["scope"] == "arbe" else algo
        file_path = str(PurePosixPath(scope_root) / check["relative_path"])
        commands.append(f"printf '%s\\n' {_q(_CHECK_BEGIN + check_id)}")
        commands.append(f"printf 'path\\t%s\\n' {_q(file_path)}")
        check_block = [f"if test -f {_q(file_path)}; then printf 'file_present\\ttrue\\n'"]
        check_block.append(
            f"printf 'sha256\\t'; sha256sum {_q(file_path)} 2>/dev/null | awk '{{print $1}}' || true"
        )
        for pattern_index, pattern in enumerate(check["patterns"]):
            check_block.append(
                match_script_template
                % (pattern_index, _q(pattern), _q(file_path), pattern_index)
            )
        if include_diff:
            check_block.extend(
                [
                    f"printf '%s\\n' {_q(_DIFF_BEGIN)}",
                    f"git -C {_q(scope_root)} diff --no-ext-diff --unified=0 -- {_q(check['relative_path'])} 2>/dev/null | head -c 24000 || true",
                    f"printf '%s\\n' {_q(_DIFF_END)}",
                ]
            )
        check_block.extend(["else printf 'file_present\\tfalse\\n'", "fi"])
        # Keep each if/else compound command contiguous.  Joining individual
        # fragments with a top-level ';' creates the invalid ``then;`` form in
        # bash/dash on the remote host.
        commands.append("; ".join(check_block))
        commands.append(f"printf '%s\\n' {_q(_CHECK_END + check_id)}")
    commands.append(f"printf '%s\\n' {_q(_END)}")
    return "; ".join(commands)


def parse_patch_plan_output(text: str, checks: list[Mapping[str, Any]] | None = None) -> dict[str, Any]:
    normalized = _normalise_checks(checks)
    specs = {item["id"]: item for item in normalized}
    section = ""
    current: dict[str, Any] | None = None
    current_pattern: int | None = None
    parsed_source: dict[str, str] = {}
    parsed_checks: list[dict[str, Any]] = []
    for raw in str(text or "").splitlines():
        line = raw.rstrip("\r")
        if line == _BEGIN:
            section = "root"
            continue
        if line == _SOURCE_BEGIN:
            section = "source"
            continue
        if line == _SOURCE_END:
            section = "root"
            continue
        if line.startswith(_CHECK_BEGIN):
            check_id = line[len(_CHECK_BEGIN) :]
            current = {
                **dict(specs.get(check_id, {"id": check_id, "patterns": [], "required": True})),
                "path": "",
                "file_present": False,
                "sha256": "",
                "matches": {},
                "diff": "",
            }
            section = "check"
            current_pattern = None
            continue
        if line.startswith(_CHECK_END):
            if current is not None:
                parsed_checks.append(current)
            current = None
            current_pattern = None
            section = "root"
            continue
        if line == _DIFF_BEGIN:
            section = "diff"
            continue
        if line == _DIFF_END:
            section = "check"
            continue
        match_start = re.fullmatch(re.escape(_MATCH_BEGIN) + r"(\d+)", line)
        if match_start:
            current_pattern = int(match_start.group(1))
            if current is not None:
                current["matches"].setdefault(current_pattern, [])
            section = "match"
            continue
        if re.fullmatch(re.escape(_MATCH_END) + r"\d+", line):
            section = "check"
            current_pattern = None
            continue
        if section == "source" and "\t" in line:
            key, value = line.split("\t", 1)
            parsed_source[key] = value
            continue
        if current is None:
            continue
        if section == "match" and current_pattern is not None:
            if line:
                current["matches"].setdefault(current_pattern, []).append(line)
            continue
        if section == "diff":
            current["diff"] += line + "\n"
            continue
        if section == "check" and "\t" in line:
            key, value = line.split("\t", 1)
            if key == "path":
                current["path"] = value
            elif key == "file_present":
                current["file_present"] = value == "true"
            elif key == "sha256":
                current["sha256"] = value
    parsed_checks.sort(key=lambda item: str(item.get("id", "")))
    return {"source": parsed_source, "checks": parsed_checks}


def resolve_patch_plan(
    *,
    runner: PatchPlanRunner,
    arbe_root: str,
    algo_source_root: str = "",
    checks: list[Mapping[str, Any]] | None = None,
    include_diff: bool = True,
    server_host: str = "",
    server_user: str = "",
    server_port: int = 22,
    execute: bool = False,
    timeout_sec: float = 30.0,
) -> dict[str, Any]:
    normalized = _normalise_checks(checks)
    command = build_patch_plan_command(
        arbe_root=arbe_root,
        algo_source_root=algo_source_root,
        checks=normalized,
        include_diff=include_diff,
    )
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": "planned",
        "target": {
            "arbe_root": str(arbe_root or "").strip(),
            "algo_source_root": str(algo_source_root or "").strip()
            or str(PurePosixPath(str(arbe_root).rstrip("/")) / "src/algo_source"),
            "server_host": str(server_host or "").strip(),
            "server_user": str(server_user or "").strip(),
            "server_port": int(server_port),
        },
        "command": command,
        "execute_requested": bool(execute),
        "check_specs": normalized,
        "source": {},
        "checks": [],
        "diagnostics": [],
        "provenance": {
            "read_only": True,
            "include_diff": bool(include_diff),
            "check_source": "configured_input" if checks is not None else "upstream_cr60light_arbe_build_default",
        },
    }
    if not execute:
        return payload
    result = runner.run(command, timeout_sec=max(0.5, float(timeout_sec)))
    payload["command_result"] = result.to_dict()
    if not result.ok:
        payload["status"] = "failed"
        payload["diagnostics"] = [
            "patch_plan_command_failed",
            *([result.stderr.strip()] if result.stderr.strip() else []),
        ]
        return payload
    parsed = parse_patch_plan_output(result.stdout, checks=normalized)
    payload["source"] = parsed["source"]
    parsed_by_id = {str(item.get("id", "")): item for item in parsed["checks"]}
    required_missing = False
    optional_missing = False
    for spec in normalized:
        item = dict(parsed_by_id.get(spec["id"], {}))
        matches = item.get("matches") if isinstance(item.get("matches"), Mapping) else {}
        pattern_results: list[dict[str, Any]] = []
        for index, pattern in enumerate(spec["patterns"]):
            rows = list(matches.get(index, []) or [])
            pattern_results.append(
                {
                    "pattern": pattern,
                    "matched": bool(rows),
                    "lines": rows,
                }
            )
        missing_patterns = [row["pattern"] for row in pattern_results if not row["matched"]]
        file_present = bool(item.get("file_present"))
        check_status = "present" if file_present and not missing_patterns else "missing"
        if not file_present:
            check_status = "not_available"
        item["pattern_results"] = pattern_results
        item["missing_patterns"] = missing_patterns
        item["status"] = check_status
        item["diff_status"] = "modified" if str(item.get("diff", "")).strip() else "clean"
        item["required"] = bool(spec["required"])
        if check_status != "present":
            if spec["required"]:
                required_missing = True
            else:
                optional_missing = True
        item.pop("matches", None)
        payload["checks"].append(item)
    if required_missing:
        payload["status"] = "needs_action"
        payload["diagnostics"].append("required_simulation_check_missing")
    elif optional_missing:
        payload["status"] = "partial"
        payload["diagnostics"].append("optional_simulation_check_missing")
    else:
        payload["status"] = "ready"
    if str(payload["source"].get("outer_dirty", "")) == "yes":
        payload["diagnostics"].append("outer_workspace_dirty")
    if str(payload["source"].get("algo_dirty", "")) == "yes":
        payload["diagnostics"].append("algo_source_dirty")
    if payload["status"] == "ready" and any(
        str(payload["source"].get(key, "")) == "yes"
        for key in ("outer_dirty", "algo_dirty")
    ):
        payload["status"] = "partial"
        payload["diagnostics"].append("dirty_workspace_requires_confirmation_before_build")
    return payload


__all__ = [
    "DEFAULT_CHECKS",
    "SCHEMA_VERSION",
    "PatchPlanRunner",
    "build_patch_plan_command",
    "parse_patch_plan_output",
    "resolve_patch_plan",
]
