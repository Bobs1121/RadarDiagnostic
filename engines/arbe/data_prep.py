# -*- coding: utf-8 -*-
"""Read-only data-preparation verification for the upstream transfer skill.

The upstream ``bosch-data-transfert`` skill owns the actual copy operation.
This engine owns the safe observation boundary: it maps an already declared
source path to the target Linux namespace, records files/size/hash, and can
compare them with an already prepared destination.  It never creates a
directory or copies a byte.
"""
from __future__ import annotations

import re
import shlex
from pathlib import PurePosixPath
from typing import Any, Mapping, Protocol

from .preflight import CommandResult


SCHEMA_VERSION = "cr60-data-prep-verification.v1"
_BEGIN = "__CR60_DATA_VERIFY_BEGIN__"
_END = "__CR60_DATA_VERIFY_END__"
_CASE_BEGIN = "__CR60_DATA_CASE_BEGIN__"
_CASE_END = "__CR60_DATA_CASE_END__"
_FILE_RE = re.compile(r"^[^\x00-\x1f\x7f]+$")


class DataPrepRunner(Protocol):
    def run(self, command: str, *, timeout_sec: float) -> CommandResult:
        ...


def _q(value: str) -> str:
    return shlex.quote(str(value))


def validate_extensions(extensions: list[str] | None) -> list[str]:
    values = extensions or [".bag", ".blf"]
    cleaned: list[str] = []
    for index, value in enumerate(values):
        text = str(value or "").strip().lower()
        if not text.startswith(".") or len(text) < 2 or not re.fullmatch(r"\.[a-z0-9]+", text):
            raise ValueError(f"extensions[{index}] must be a simple suffix such as .bag")
        if text not in cleaned:
            cleaned.append(text)
    if not cleaned:
        raise ValueError("extensions must not be empty")
    return cleaned


def _safe_case_id(value: str, fallback: str) -> str:
    text = str(value or "").strip()
    if not text:
        return fallback
    if not _FILE_RE.fullmatch(text) or text in {".", ".."} or "/" in text or "\\" in text:
        raise ValueError(f"case_id must be one safe path component: {value!r}")
    return text


def map_source_path(path: str, *, source_prefix: str = "") -> dict[str, Any]:
    """Map a declared source path without guessing an unavailable mount."""

    original = str(path or "").strip()
    normalized = original.replace("\\", "/")
    prefix = str(source_prefix or "").strip().rstrip("/")
    if normalized.startswith("//"):
        match = re.match(r"^//[^/]+/[^/]+(?P<rest>/.*)?$", normalized)
        if not prefix:
            return {
                "original": original,
                "mapped": "",
                "status": "needs_confirmation",
                "reason": "unc_path_requires_explicit_source_prefix",
            }
        if not match:
            return {
                "original": original,
                "mapped": "",
                "status": "blocked",
                "reason": "unc_path_format_invalid",
            }
        rest = match.group("rest") or ""
        mapped = prefix + rest
        return {
            "original": original,
            "mapped": mapped,
            "status": "mapped_unc",
            "mapping": "unc_server_share_removed_then_source_prefix_added",
        }
    if re.match(r"^[A-Za-z]:/", normalized):
        return {
            "original": original,
            "mapped": "",
            "status": "needs_confirmation",
            "reason": "windows_path_is_not_in_linux_namespace",
        }
    if not normalized.startswith("/"):
        return {
            "original": original,
            "mapped": "",
            "status": "needs_confirmation",
            "reason": "relative_path_requires_explicit_linux_root",
        }
    return {"original": original, "mapped": normalized, "status": "linux_absolute"}


def _normalize_entries(entries: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(entries, list) or not entries:
        raise ValueError("entries must be a non-empty list")
    result: list[dict[str, Any]] = []
    for index, raw in enumerate(entries):
        if not isinstance(raw, Mapping):
            raise ValueError(f"entries[{index}] must be an object")
        case_id = _safe_case_id(str(raw.get("case_id", "")), f"case-{index + 1}")
        source_path = str(raw.get("source_path", raw.get("path", ""))).strip()
        if not source_path:
            raise ValueError(f"entries[{index}].source_path is required")
        mapped = str(raw.get("mapped_source_path", "")).strip()
        if not mapped:
            raise ValueError(f"entries[{index}].mapped_source_path is required")
        destination = str(raw.get("destination_dir", "")).strip()
        if destination and (
            not destination.startswith("/")
            or "\x00" in destination
            or ".." in PurePosixPath(destination).parts
        ):
            raise ValueError(f"entries[{index}].destination_dir must be an absolute Linux path")
        try:
            entry_index = int(raw.get("entry_index", index))
        except (TypeError, ValueError):
            entry_index = index
        result.append(
            {
                "entry_index": entry_index,
                "case_id": case_id,
                "source_path": source_path,
                "mapped_source_path": mapped,
                "destination_dir": destination,
            }
        )
    return result


def build_data_verify_command(
    *,
    entries: list[Mapping[str, Any]],
    extensions: list[str] | None = None,
    check_destination: bool = False,
) -> str:
    """Build a bounded read-only file/stat/hash scan command."""

    normalized = _normalize_entries(entries)
    suffixes = validate_extensions(extensions)
    record_script = (
        "for f do "
        "size=$(stat -c %s \"$f\" 2>/dev/null || printf '0'); "
        "mtime=$(stat -c %Y \"$f\" 2>/dev/null || printf '0'); "
        "hash=$(sha256sum \"$f\" 2>/dev/null | awk '{print $1}'); "
        "base=$(basename \"$f\"); "
        "printf 'file\\t%s\\t%s\\t%s\\t%s\\t%s\\n' \"$f\" \"$base\" \"$size\" \"$mtime\" \"$hash\"; "
        "done"
    )
    suffix_expr = " -o ".join(f"-iname {_q('*' + suffix)}" for suffix in suffixes)
    commands = [f"printf '%s\\n' {_q(_BEGIN)}"]
    for entry in normalized:
        index = int(entry["entry_index"])
        source = str(entry["mapped_source_path"])
        destination = str(entry.get("destination_dir", ""))
        commands.append(f"printf '%s\\n' {_q(_CASE_BEGIN + str(index))}")
        source_block = [
            f"if test -f {_q(source)}; then printf 'source_present\\ttrue\\n';",
            f"sh -c {_q(record_script)} _ {_q(source)};",
            f"elif test -d {_q(source)}; then printf 'source_present\\ttrue\\n';",
            f"find {_q(source)} -maxdepth 1 -type f \\( {suffix_expr} \\) -exec sh -c {_q(record_script)} _ {{}} + 2>/dev/null || true;",
            "else printf 'source_present\\tfalse\\n'; fi",
        ]
        commands.append(" ".join(source_block))
        if check_destination and destination:
            destination_block = [
                f"if test -d {_q(destination)}; then printf 'destination_present\\ttrue\\n';",
                f"find {_q(destination)} -maxdepth 1 -type f \\( {suffix_expr} \\) -exec sh -c {_q(record_script)} _ {{}} + 2>/dev/null || true;",
                "else printf 'destination_present\\tfalse\\n'; fi",
            ]
            commands.append(" ".join(destination_block))
        elif check_destination:
            commands.append("printf 'destination_present\\tfalse\\n'")
        commands.append(f"printf '%s\\n' {_q(_CASE_END + str(index))}")
    commands.append(f"printf '%s\\n' {_q(_END)}")
    return "; ".join(commands)


def parse_data_verify_output(text: str, entries: list[Mapping[str, Any]]) -> dict[str, Any]:
    normalized = _normalize_entries(entries)
    by_index = {int(item["entry_index"]): item for item in normalized}
    cases: dict[int, dict[str, Any]] = {}
    section = ""
    current_index: int | None = None
    for raw in str(text or "").splitlines():
        line = raw.rstrip("\r")
        if line == _BEGIN:
            section = "root"
            continue
        if line == _END:
            section = ""
            continue
        if line.startswith(_CASE_BEGIN):
            try:
                current_index = int(line[len(_CASE_BEGIN) :])
            except ValueError:
                current_index = None
            if current_index in by_index:
                cases[current_index] = {
                    **by_index[current_index],
                    "source_present": False,
                    "source_files": [],
                    "destination_present": None,
                    "destination_files": [],
                }
                section = "source"
            continue
        if line.startswith(_CASE_END):
            current_index = None
            section = "root"
            continue
        if current_index is None or current_index not in cases:
            continue
        current = cases[current_index]
        if "\t" in line and line.split("\t", 1)[0] in {"source_present", "destination_present"}:
            key, value = line.split("\t", 1)
            current[key] = value == "true"
            section = "destination" if key == "destination_present" else "source"
            continue
        if line.startswith("file\t"):
            fields = line.split("\t", 5)
            if len(fields) != 6:
                continue
            _, path, basename, size, mtime, sha256 = fields
            try:
                size_value: int | None = int(size)
            except ValueError:
                size_value = None
            try:
                mtime_value: int | float = int(mtime)
            except ValueError:
                mtime_value = 0
            current[f"{section}_files"].append(
                {
                    "path": path,
                    "basename": basename,
                    "size_bytes": size_value,
                    "mtime_epoch": mtime_value,
                    "sha256": sha256,
                }
            )
    return {"cases": [cases[index] for index in sorted(cases)]}


def _compare_files(source_files: list[Mapping[str, Any]], destination_files: list[Mapping[str, Any]]) -> dict[str, Any]:
    source_by_name = {str(item.get("basename", "")): item for item in source_files}
    destination_by_name = {str(item.get("basename", "")): item for item in destination_files}
    missing = sorted(set(source_by_name) - set(destination_by_name))
    extra = sorted(set(destination_by_name) - set(source_by_name))
    mismatch: list[str] = []
    for name in sorted(set(source_by_name) & set(destination_by_name)):
        source = source_by_name[name]
        destination = destination_by_name[name]
        if source.get("size_bytes") != destination.get("size_bytes") or (
            source.get("sha256") and destination.get("sha256") and source.get("sha256") != destination.get("sha256")
        ):
            mismatch.append(name)
    status = "matched" if not missing and not extra and not mismatch else "mismatch"
    return {"status": status, "missing": missing, "extra": extra, "mismatch": mismatch}


def verify_data(
    *,
    runner: DataPrepRunner,
    entries: list[Mapping[str, Any]],
    extensions: list[str] | None = None,
    source_prefix: str = "",
    check_destination: bool = False,
    server_host: str = "",
    server_user: str = "",
    server_port: int = 22,
    execute: bool = False,
    timeout_sec: float = 60.0,
) -> dict[str, Any]:
    normalized: list[dict[str, Any]] = []
    mapping_diagnostics: list[str] = []
    for index, raw in enumerate(entries):
        item = dict(raw)
        original = str(item.get("source_path", item.get("path", ""))).strip()
        mapping = map_source_path(original, source_prefix=source_prefix)
        item["entry_index"] = index
        item["case_id"] = _safe_case_id(str(item.get("case_id", "")), f"case-{index + 1}")
        item["source_path"] = original
        item["mapped_source_path"] = mapping.get("mapped", "")
        item["source_mapping"] = mapping
        if mapping.get("status") not in {"linux_absolute", "mapped_unc"}:
            mapping_diagnostics.append(
                f"{item['case_id']}:{mapping.get('reason', 'source_path_not_mappable')}"
            )
        normalized.append(item)
    valid_entries = [item for item in normalized if item.get("mapped_source_path")]
    command = ""
    if valid_entries:
        command = build_data_verify_command(
            entries=valid_entries,
            extensions=extensions,
            check_destination=check_destination,
        )
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": "planned",
        "server": {
            "host": str(server_host or "").strip(),
            "user": str(server_user or "").strip(),
            "port": int(server_port),
        },
        "verification_policy": {
            "extensions": validate_extensions(extensions),
            "source_prefix": str(source_prefix or ""),
            "check_destination": bool(check_destination),
            "read_only": True,
        },
        "entries": normalized,
        "command": command,
        "execute_requested": bool(execute),
        "cases": [],
        "diagnostics": mapping_diagnostics,
        "provenance": {
            "source": "cr60-analysis-intake.v1_or_explicit_entries",
            "upstream_executor": "bosch-data-transfert",
            "read_only": True,
        },
    }
    if not valid_entries:
        payload["status"] = "blocked" if mapping_diagnostics else "needs_confirmation"
        if not mapping_diagnostics:
            payload["diagnostics"].append("no_data_entries")
        return payload
    if not execute:
        return payload
    result = runner.run(command, timeout_sec=max(0.5, float(timeout_sec)))
    payload["command_result"] = result.to_dict()
    if not result.ok:
        payload["status"] = "failed"
        payload["diagnostics"].append("data_verification_command_failed")
        if result.stderr.strip():
            payload["diagnostics"].append(result.stderr.strip())
        return payload
    parsed = parse_data_verify_output(result.stdout, entries=valid_entries)
    parsed_by_entry = {int(item.get("entry_index", -1)): item for item in parsed["cases"]}
    all_ready = True
    for item in normalized:
        observed = dict(parsed_by_entry.get(int(item["entry_index"]), {}))
        if not observed:
            observed = {
                **item,
                "source_present": False,
                "source_files": [],
                "destination_present": None,
                "destination_files": [],
            }
        observed["source_status"] = (
            "ready" if observed.get("source_present") and observed.get("source_files") else "missing"
        )
        if check_destination:
            if observed.get("destination_present") and observed.get("destination_files"):
                observed["destination_status"] = "ready"
                observed["comparison"] = _compare_files(
                    list(observed.get("source_files", [])),
                    list(observed.get("destination_files", [])),
                )
            else:
                observed["destination_status"] = "missing"
                observed["comparison"] = {"status": "not_available"}
        else:
            observed["destination_status"] = "not_checked"
            observed["comparison"] = {"status": "not_checked"}
        if observed["source_status"] != "ready":
            all_ready = False
            payload["diagnostics"].append(f"{observed['case_id']}:source_missing_or_empty")
        if check_destination and observed["comparison"].get("status") != "matched":
            all_ready = False
            payload["diagnostics"].append(f"{observed['case_id']}:destination_not_verified")
        payload["cases"].append(observed)
    payload["status"] = "ready" if all_ready and not mapping_diagnostics else "partial"
    return payload


__all__ = [
    "DataPrepRunner",
    "SCHEMA_VERSION",
    "build_data_verify_command",
    "map_source_path",
    "parse_data_verify_output",
    "validate_extensions",
    "verify_data",
]
