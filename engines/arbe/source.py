# -*- coding: utf-8 -*-
"""Read-only source reference resolution for an arbe algorithm submodule."""
from __future__ import annotations

import re
import shlex
from pathlib import PurePosixPath
from typing import Any, Protocol

from .preflight import CommandResult


SCHEMA_VERSION = "arbe-source-resolution.v1"
_BEGIN = "__CR60_SOURCE_RESOLUTION_BEGIN__"
_END = "__CR60_SOURCE_RESOLUTION_END__"
_REMOTE_BEGIN = "__CR60_SOURCE_REMOTE_BEGIN__"
_REMOTE_END = "__CR60_SOURCE_REMOTE_END__"
_REF_RE = re.compile(r"^[^\x00-\x1f\x7f]+$")


class SourceResolutionRunner(Protocol):
    def run(self, command: str, *, timeout_sec: float) -> CommandResult:
        ...


def _q(value: str) -> str:
    return shlex.quote(str(value))


def _validate_ref(value: str, field: str = "requested_ref") -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    # This is a conservative input gate.  Git remains the authority on ref
    # syntax; rejecting controls/whitespace here prevents malformed command
    # records and avoids turning a user string into shell syntax.
    if not _REF_RE.fullmatch(text) or any(char.isspace() for char in text):
        raise ValueError(f"{field} contains unsupported whitespace/control characters")
    if text in {".", ".."} or text.startswith("/") or text.endswith("/"):
        raise ValueError(f"{field} is not a valid git ref candidate: {value!r}")
    if ".." in text or "@{" in text:
        raise ValueError(f"{field} is not a valid git ref candidate: {value!r}")
    return text


def _validate_component(value: str, field: str) -> str:
    text = str(value or "").strip()
    if not text or any(char in text for char in ("/", "\\", "\x00", "\n", "\r", "\t")):
        raise ValueError(f"{field} must be one safe component")
    return text


def derive_ref_from_version(
    *,
    software_version: str = "",
    ref_prefix: str = "",
    version_suffix_strip: str = "",
) -> dict[str, Any]:
    """Derive a ref only when the caller supplies an explicit mapping policy."""

    version = str(software_version or "").strip()
    prefix = str(ref_prefix or "")
    suffix = str(version_suffix_strip or "")
    if not version or not prefix:
        return {
            "status": "not_configured",
            "software_version": version,
            "ref_prefix": prefix,
            "version_suffix_strip": suffix,
            "derived_ref": "",
        }
    normalized = version[:-len(suffix)] if suffix and version.endswith(suffix) else version
    derived = _validate_ref(prefix + normalized, field="derived_ref")
    return {
        "status": "derived",
        "software_version": version,
        "normalized_version": normalized,
        "ref_prefix": prefix,
        "version_suffix_strip": suffix,
        "derived_ref": derived,
    }


def build_source_resolve_command(
    *,
    algo_source_root: str,
    requested_ref: str = "",
    remote_name: str = "origin",
    remote_query: bool = False,
) -> str:
    """Build a read-only source/ref probe; it never fetches or checks out."""

    root = str(algo_source_root or "").strip()
    if not root:
        raise ValueError("algo_source_root is required")
    ref = _validate_ref(requested_ref)
    remote = _validate_component(remote_name, "remote_name")
    git = f"git -C {_q(root)}"
    lines = [
        f"printf '%s\\n' {_q(_BEGIN)}",
        f"printf 'head\\t'; {git} rev-parse HEAD 2>/dev/null || true",
        f"printf 'branch\\t'; {git} symbolic-ref --quiet --short HEAD 2>/dev/null || printf 'DETACHED\\n'",
        f"printf 'exact_tag\\t'; {git} describe --tags --exact-match HEAD 2>/dev/null || true",
        f"printf 'dirty\\t'; if test -n \"$({git} status --porcelain --untracked-files=all 2>/dev/null)\"; then printf 'yes\\n'; else printf 'no\\n'; fi",
    ]
    if ref:
        ref_q = _q(ref)
        lines.extend(
            [
                f"printf 'target_ref\\t%s\\n' {ref_q}",
                f"printf 'target_branch_local\\t'; if {git} rev-parse --verify --quiet {_q('refs/heads/' + ref + '^{commit}')} >/dev/null; then printf 'yes\\n'; else printf 'no\\n'; fi",
                f"printf 'target_tag_local\\t'; if {git} rev-parse --verify --quiet {_q('refs/tags/' + ref + '^{commit}')} >/dev/null; then printf 'yes\\n'; else printf 'no\\n'; fi",
            ]
        )
    else:
        lines.append("printf 'target_ref\\t\\n'")
    if remote_query and ref:
        lines.extend(
            [
                f"printf '%s\\n' {_q(_REMOTE_BEGIN)}",
                f"{git} ls-remote --refs {_q(remote)} {_q('refs/heads/' + ref)} {_q('refs/tags/' + ref)} 2>/dev/null || true",
                f"printf '%s\\n' {_q(_REMOTE_END)}",
            ]
        )
    lines.append(f"printf '%s\\n' {_q(_END)}")
    return "; ".join(lines)


def parse_source_resolve_output(text: str) -> dict[str, Any]:
    section = ""
    values: dict[str, str] = {}
    remote_refs: list[dict[str, str]] = []
    for raw in str(text or "").splitlines():
        line = raw.rstrip("\r")
        if line == _BEGIN:
            section = "main"
            continue
        if line == _END:
            section = ""
            continue
        if line == _REMOTE_BEGIN:
            section = "remote"
            continue
        if line == _REMOTE_END:
            section = "main"
            continue
        if section == "remote":
            parts = line.split("\t", 1)
            if len(parts) == 2 and parts[0].strip() and parts[1].strip():
                remote_refs.append({"commit": parts[0].strip(), "ref": parts[1].strip()})
            continue
        if section != "main":
            continue
        if "\t" in line:
            key, value = line.split("\t", 1)
            values[key.strip()] = value.strip()
    return {
        "observed": values,
        "remote_refs": remote_refs,
        "status": "ready" if values.get("head") else "not_available",
    }


def resolve_source(
    *,
    runner: SourceResolutionRunner,
    algo_source_root: str,
    arbe_root: str = "",
    requested_ref: str = "",
    software_version: str = "",
    ref_prefix: str = "",
    version_suffix_strip: str = "",
    remote_name: str = "origin",
    remote_query: bool = False,
    server_host: str = "",
    server_user: str = "",
    server_port: int = 22,
    execute: bool = False,
    timeout_sec: float = 30.0,
) -> dict[str, Any]:
    """Plan or execute source/ref discovery against the current source tree."""

    root = str(algo_source_root or "").strip()
    derived = derive_ref_from_version(
        software_version=software_version,
        ref_prefix=ref_prefix,
        version_suffix_strip=version_suffix_strip,
    )
    explicit = _validate_ref(requested_ref)
    derived_ref = str(derived.get("derived_ref", ""))
    diagnostics: list[str] = []
    if explicit and derived_ref and explicit != derived_ref:
        diagnostics.append("requested_ref_conflicts_with_configured_version_mapping")
    effective_ref = explicit or derived_ref
    command = build_source_resolve_command(
        algo_source_root=root,
        requested_ref=effective_ref,
        remote_name=remote_name,
        remote_query=remote_query,
    )
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": "planned",
        "target": {
            "arbe_root": str(arbe_root or "").strip(),
            "algo_source_root": root,
            "server_host": str(server_host or "").strip(),
            "server_user": str(server_user or "").strip(),
            "server_port": int(server_port),
        },
        "command": command,
        "execute_requested": bool(execute),
        "current_source": {
            "head": "",
            "branch": "",
            "exact_tag": "",
            "dirty": "unknown",
        },
        "resolution": {
            "requested_ref": explicit,
            "effective_ref": effective_ref,
            "ref_source": "explicit_input" if explicit else "configured_version_mapping" if derived_ref else "not_provided",
            "derived": derived,
            "target_branch_local": "unknown",
            "target_tag_local": "unknown",
            "remote_refs": [],
            "status": "not_requested" if not effective_ref else "unresolved",
        },
        "provenance": {
            "read_only": True,
            "remote_query": bool(remote_query),
            "remote_name": remote_name,
            "arbe_root": str(arbe_root or "").strip(),
        },
        "diagnostics": diagnostics,
    }
    if diagnostics:
        payload["status"] = "blocked"
        return payload
    if not execute:
        return payload

    result = runner.run(command, timeout_sec=max(0.5, float(timeout_sec)))
    payload["command_result"] = result.to_dict()
    if not result.ok:
        payload["status"] = "failed"
        payload["diagnostics"] = [
            "source_resolution_command_failed",
            *([result.stderr.strip()] if result.stderr.strip() else []),
        ]
        return payload

    parsed = parse_source_resolve_output(result.stdout)
    observed = parsed.get("observed", {})
    current = payload["current_source"]
    for field in ("head", "branch", "exact_tag", "dirty"):
        if field in observed:
            current[field] = observed[field]
    resolution = payload["resolution"]
    resolution["target_branch_local"] = observed.get("target_branch_local", "unknown")
    resolution["target_tag_local"] = observed.get("target_tag_local", "unknown")
    resolution["remote_refs"] = parsed.get("remote_refs", [])
    if not current["head"]:
        payload["status"] = "failed"
        payload["diagnostics"] = ["algo_source_head_not_observed"]
        return payload
    if not effective_ref:
        resolution["status"] = "not_requested"
        payload["status"] = "needs_confirmation"
        payload["diagnostics"] = ["target_ref_or_version_mapping_missing"]
        return payload

    local_found = resolution["target_branch_local"] == "yes" or resolution["target_tag_local"] == "yes"
    remote_found = bool(resolution["remote_refs"])
    if local_found or remote_found:
        resolution["status"] = "resolved_local" if local_found else "resolved_remote"
        payload["status"] = "partial" if current.get("dirty") == "yes" else "ready"
        if current.get("dirty") == "yes":
            payload["diagnostics"].append("algo_source_dirty_requires_confirmation_before_checkout")
    else:
        resolution["status"] = "not_found"
        payload["status"] = "needs_confirmation"
        payload["diagnostics"] = ["target_ref_not_found_in_local_or_requested_remote"]
    return payload


__all__ = [
    "SCHEMA_VERSION",
    "SourceResolutionRunner",
    "build_source_resolve_command",
    "derive_ref_from_version",
    "parse_source_resolve_output",
    "resolve_source",
]
