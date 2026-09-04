# -*- coding: utf-8 -*-
"""Read-only CUDA/config resolution for a configured arbe workspace.

The upstream ``cr60light-arbe-build`` workflow resolves the CUDA workbook
*after* the algorithm submodule has been selected.  This module exposes that
discovery step as a feature-neutral, Pi-callable engine.  It deliberately does
not copy a workbook, edit YAML, checkout a branch, or build the workspace.

The result is an auditable ``arbe-cuda-resolution.v1`` payload.  A later
approval-gated config/apply capability may consume the selected candidate, but
it must never rediscover a workbook from an old cache or silently overwrite a
dirty workspace.
"""
from __future__ import annotations

import json
import re
import shlex
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Protocol

from .preflight import CommandResult, LocalShellRunner, SshCommandRunner


SCHEMA_VERSION = "arbe-cuda-resolution.v1"
_CUDA_BEGIN = "__CR60_CUDA_SOURCE_BEGIN__"
_CUDA_END = "__CR60_CUDA_SOURCE_END__"
_CONFIG_BEGIN = "__CR60_CONFIG_BEGIN__"
_CONFIG_END = "__CR60_CONFIG_END__"
_COMPONENT_RE = re.compile(r"^[^/\\\x00-\x1f\x7f]+$")
_CONFIG_LINE_RE = re.compile(
    r"^\s*(?P<key>xlsx_path|xlsx_sheet|type)\s*:\s*(?P<value>.*?)\s*$"
)


class CudaResolutionRunner(Protocol):
    """Runner for the generated, read-only remote command."""

    def run(self, command: str, *, timeout_sec: float) -> CommandResult:
        ...


def _q(value: str) -> str:
    return shlex.quote(str(value))


def _join_remote(root: str, relative: str) -> str:
    return str(PurePosixPath(str(root).rstrip("/")) / relative.lstrip("/"))


def _validate_component(value: str, field: str) -> str:
    text = str(value or "").strip()
    if not text or not _COMPONENT_RE.fullmatch(text) or text in {".", ".."}:
        raise ValueError(
            f"{field} must be one safe path component; received {value!r}"
        )
    return text


def _validate_config_name(value: str) -> str:
    text = str(value or "").strip()
    if not text or "/" in text or "\\" in text or text in {".", ".."}:
        raise ValueError(f"config_name must be a file name; received {value!r}")
    return text


def _normalise_value(value: Any) -> Any:
    if isinstance(value, list):
        return value[0] if len(value) == 1 else value
    return value


def _field_value(payload: Mapping[str, Any], group: str, field: str) -> Any:
    """Read an intake field without assuming one artifact shape."""

    group_value = payload.get(group)
    if isinstance(group_value, Mapping):
        item = group_value.get(field)
        if isinstance(item, Mapping) and "value" in item:
            return _normalise_value(item.get("value"))
        if item not in (None, ""):
            return item
    return None


def _load_artifact(
    value: Mapping[str, Any] | None,
    path: str,
    *,
    label: str,
) -> tuple[dict[str, Any], str]:
    if value is not None:
        if not isinstance(value, Mapping):
            raise ValueError(f"{label} must be a JSON object")
        return dict(value), "inline"
    text = str(path or "").strip()
    if not text:
        return {}, ""
    artifact_path = Path(text).expanduser().resolve()
    try:
        loaded = json.loads(artifact_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"{label} artifact cannot be read: {artifact_path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} artifact is not valid JSON: {artifact_path}: {exc.msg}") from exc
    if not isinstance(loaded, Mapping):
        raise ValueError(f"{label} artifact must contain a JSON object: {artifact_path}")
    return dict(loaded), str(artifact_path)


def _resolve_inputs(
    *,
    intake: Mapping[str, Any] | None,
    intake_path: str,
    arbe_root: str,
    algo_source_root: str,
    vehicle: str,
    coem: str,
    cuda_sheet: str,
    server_host: str,
    server_user: str,
    server_port: int,
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    intake_payload, intake_ref = _load_artifact(intake, intake_path, label="intake")
    intake_status = str(intake_payload.get("status", "")).strip()
    intake_detail_status = str(intake_payload.get("intake_status", "")).strip()
    if intake_status == "blocked" or intake_detail_status == "blocked_missing_input":
        return (
            {
                "arbe_root": str(arbe_root or "").strip(),
                "algo_source_root": str(algo_source_root or "").strip(),
                "vehicle": str(vehicle or "").strip(),
                "coem": str(coem or "").strip(),
                "cuda_sheet": str(cuda_sheet or "").strip(),
                "server_host": str(server_host or "").strip(),
                "server_user": str(server_user or "").strip(),
                "server_port": int(server_port),
            },
            {
                "intake_ref": intake_ref,
                "intake_status": intake_status,
                "intake_detail_status": intake_detail_status,
            },
            ["intake_blocked_requires_confirmation"],
        )
    environment = intake_payload.get("environment")
    if not isinstance(environment, Mapping):
        environment = {}
    server = environment.get("server") if isinstance(environment.get("server"), Mapping) else {}
    arbe = environment.get("arbe") if isinstance(environment.get("arbe"), Mapping) else {}
    intake_arbe_root = str(arbe.get("workspace") or "").strip()
    intake_algo_root = str(arbe.get("algo_source_root") or "").strip()
    intake_vehicle = str(
        (environment.get("vehicle") or {}).get("model", "")
        if isinstance(environment.get("vehicle"), Mapping)
        else ""
    ).strip()
    intake_coem = str(
        (environment.get("vehicle") or {}).get("coem", "")
        if isinstance(environment.get("vehicle"), Mapping)
        else ""
    ).strip()
    intake_sheet = str(
        (environment.get("vehicle") or {}).get("cuda_sheet", "")
        if isinstance(environment.get("vehicle"), Mapping)
        else ""
    ).strip()

    selected_root = str(arbe_root or intake_arbe_root).strip()
    selected_algo = str(algo_source_root or intake_algo_root).strip()
    selected_vehicle = str(vehicle or intake_vehicle or "").strip()
    selected_coem = str(coem or intake_coem or "").strip()
    selected_sheet = str(cuda_sheet or intake_sheet or "").strip()
    selected_host = str(server_host or server.get("host") or "").strip()
    selected_user = str(server_user or server.get("user") or "").strip()
    selected_port = int(server_port or server.get("port") or 22)

    missing: list[str] = []
    if not selected_root:
        missing.append("arbe_root")
    if not selected_vehicle:
        missing.append("vehicle")
    if selected_port < 1 or selected_port > 65535:
        missing.append("server_port")
    if missing:
        return (
            {
                "arbe_root": selected_root,
                "algo_source_root": selected_algo,
                "vehicle": selected_vehicle,
                "coem": selected_coem,
                "cuda_sheet": selected_sheet,
                "server_host": selected_host,
                "server_user": selected_user,
                "server_port": selected_port,
            },
            {"intake_ref": intake_ref},
            missing,
        )

    # Validate the model directory before it can become part of a remote path.
    _validate_component(selected_vehicle, "vehicle")
    return (
        {
            "arbe_root": selected_root,
            "algo_source_root": selected_algo or _join_remote(selected_root, "src/algo_source"),
            "vehicle": selected_vehicle,
            "coem": selected_coem,
            "cuda_sheet": selected_sheet,
            "server_host": selected_host,
            "server_user": selected_user,
            "server_port": selected_port,
        },
        {"intake_ref": intake_ref, "handoff_id": str(intake_payload.get("handoff_id", ""))},
        [],
    )


def build_cuda_resolve_command(
    *,
    arbe_root: str,
    vehicle: str,
    algo_source_root: str = "",
    config_dir: str = "",
    config_name: str = "launch_config_4radars.yaml",
) -> str:
    """Create a parameterized, read-only scan command.

    The command emits explicit markers so SSH transport noise and an absent
    directory are distinguishable from an empty workbook list.  The nested
    shell script receives paths as positional arguments; user values are never
    interpolated into its body.
    """

    root = str(arbe_root or "").strip()
    if not root:
        raise ValueError("arbe_root is required")
    model = _validate_component(vehicle, "vehicle")
    algo = str(algo_source_root or "").strip() or _join_remote(root, "src/algo_source")
    config_root = str(config_dir or "").strip() or _join_remote(
        root, "src/arbe_phoenix_radar_driver-master/arbe_gui/Config"
    )
    yaml_name = _validate_config_name(config_name)
    cuda_dir = _join_remote(
        algo, f"coem/{model}/tools/container_input/08_CustData"
    )
    config_path = _join_remote(config_root, yaml_name)
    record_script = (
        "for f do "
        "mtime=$(stat -c %Y \"$f\" 2>/dev/null || printf '0'); "
        "size=$(stat -c %s \"$f\" 2>/dev/null || printf '0'); "
        "hash=$(sha256sum \"$f\" 2>/dev/null | awk '{print $1}'); "
        "printf '%s\\t%s\\t%s\\t%s\\n' \"$mtime\" \"$size\" \"$hash\" \"$f\"; "
        "done"
    )
    scan = (
        f"printf '%s\\n' {_q(_CUDA_BEGIN)}; "
        f"if test -d {_q(cuda_dir)}; then "
        "printf 'directory_present\\n'; "
        f"find {_q(cuda_dir)} -maxdepth 1 -type f -name 'CUDA_*.xlsx' "
        f"-exec sh -c {_q(record_script)} _ {{}} + 2>/dev/null || true; "
        "else printf 'directory_missing\\n'; fi; "
        f"printf '%s\\n' {_q(_CUDA_END)}; "
        f"printf '%s\\n' {_q(_CONFIG_BEGIN)}; "
        f"if test -f {_q(config_path)}; then "
        f"grep -nE '^[[:space:]]*(xlsx_path|xlsx_sheet|type):' {_q(config_path)} "
        "2>/dev/null || true; "
        "else printf 'config_missing\\n'; fi; "
        f"printf '%s\\n' {_q(_CONFIG_END)}"
    )
    return scan


def _parse_config_lines(lines: list[str]) -> dict[str, Any]:
    values: dict[str, list[dict[str, Any]]] = {}
    for raw in lines:
        line = str(raw).strip()
        if not line or line == "config_missing":
            continue
        line_no: int | None = None
        match_line = re.match(r"^(?P<num>[0-9]+):(.*)$", line)
        if match_line:
            line_no = int(match_line.group("num"))
            line = match_line.group(2).strip()
        match = _CONFIG_LINE_RE.match(line)
        if not match:
            continue
        value = match.group("value").split(" #", 1)[0].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        item: dict[str, Any] = {"value": value, "raw": raw}
        if line_no is not None:
            item["line"] = line_no
        values.setdefault(match.group("key"), []).append(item)

    resolved: dict[str, Any] = {}
    conflicts: list[dict[str, Any]] = []
    for key, items in values.items():
        unique = list(dict.fromkeys(str(item.get("value", "")) for item in items))
        if len(unique) == 1:
            resolved[key] = unique[0]
        elif unique:
            conflicts.append({"field": key, "values": unique, "records": items})
    return {
        "lines": lines,
        "values": values,
        "resolved": resolved,
        "conflicts": conflicts,
        "status": "ready" if values else "not_available",
    }


def parse_cuda_resolve_output(text: str) -> dict[str, Any]:
    """Parse the marker protocol produced by :func:`build_cuda_resolve_command`."""

    section = ""
    cuda_dir_status = "unknown"
    candidates: list[dict[str, Any]] = []
    config_lines: list[str] = []
    for raw in str(text or "").splitlines():
        line = raw.rstrip("\r")
        if line == _CUDA_BEGIN:
            section = "cuda"
            continue
        if line == _CUDA_END:
            section = ""
            continue
        if line == _CONFIG_BEGIN:
            section = "config"
            continue
        if line == _CONFIG_END:
            section = ""
            continue
        if section == "cuda":
            if line in {"directory_present", "directory_missing"}:
                cuda_dir_status = line.removesuffix("_present").removesuffix("_missing")
                # The string above intentionally keeps the source readable;
                # normalize the two exact values below.
                cuda_dir_status = "present" if line == "directory_present" else "missing"
                continue
            fields = line.split("\t", 3)
            if len(fields) != 4:
                continue
            mtime, size, sha256, path = fields
            try:
                mtime_value: int | float = int(mtime)
            except ValueError:
                try:
                    mtime_value = float(mtime)
                except ValueError:
                    mtime_value = 0
            try:
                size_value: int | None = int(size)
            except ValueError:
                size_value = None
            candidate_path = path.strip()
            if not candidate_path:
                continue
            candidates.append(
                {
                    "path": candidate_path,
                    "basename": PurePosixPath(candidate_path).name,
                    "mtime_epoch": mtime_value,
                    "size_bytes": size_value,
                    "sha256": sha256.strip().lower(),
                    "source": "remote_08_CustData_scan",
                }
            )
        elif section == "config":
            config_lines.append(line)

    candidates.sort(
        key=lambda item: (float(item.get("mtime_epoch") or 0), str(item.get("path", ""))),
        reverse=True,
    )
    return {
        "cuda_source_dir_status": cuda_dir_status,
        "candidates": candidates,
        "configuration": _parse_config_lines(config_lines),
    }


def _config_alignment(
    *,
    configuration: Mapping[str, Any],
    selected: Mapping[str, Any],
    expected_sheet: str,
) -> tuple[str, list[str]]:
    resolved = configuration.get("resolved")
    if not isinstance(resolved, Mapping):
        return "not_available", ["config_values_not_available"]
    diagnostics: list[str] = []
    current_xlsx = str(resolved.get("xlsx_path", "")).strip()
    current_sheet = str(resolved.get("xlsx_sheet", "")).strip()
    selected_name = str(selected.get("basename", "")).strip()
    if not current_xlsx:
        diagnostics.append("config_xlsx_path_not_found")
    elif PurePosixPath(current_xlsx).name != selected_name:
        diagnostics.append("config_xlsx_path_differs_from_latest_candidate")
    if expected_sheet and current_sheet != expected_sheet:
        diagnostics.append("config_xlsx_sheet_differs_from_requested_sheet")
    if configuration.get("conflicts"):
        diagnostics.append("config_has_conflicting_values")
    return ("aligned" if not diagnostics else "needs_update", diagnostics)


def resolve_cuda(
    *,
    runner: CudaResolutionRunner,
    arbe_root: str,
    vehicle: str,
    algo_source_root: str = "",
    config_dir: str = "",
    config_name: str = "launch_config_4radars.yaml",
    expected_sheet: str = "",
    coem: str = "",
    server_host: str = "",
    server_user: str = "",
    server_port: int = 22,
    execute: bool = False,
    timeout_sec: float = 30.0,
    intake: Mapping[str, Any] | None = None,
    intake_path: str = "",
    preflight: Mapping[str, Any] | None = None,
    preflight_path: str = "",
) -> dict[str, Any]:
    """Plan or execute one read-only current-source CUDA resolution."""

    inputs, intake_meta, missing = _resolve_inputs(
        intake=intake,
        intake_path=intake_path,
        arbe_root=arbe_root,
        algo_source_root=algo_source_root,
        vehicle=vehicle,
        coem=coem,
        cuda_sheet=expected_sheet,
        server_host=server_host,
        server_user=server_user,
        server_port=server_port,
    )
    if missing:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "blocked",
            "target": inputs,
            "candidates": [],
            "selected": None,
            "configuration": {"status": "not_available"},
            "diagnostics": [f"missing_input:{item}" for item in missing],
            "provenance": {"intake": intake_meta},
        }

    # Make the preflight reference visible without treating it as a substitute
    # for the current scan.  A caller may pass either the payload or its path.
    preflight_payload, preflight_ref = _load_artifact(
        preflight, preflight_path, label="preflight"
    )
    command = build_cuda_resolve_command(
        arbe_root=inputs["arbe_root"],
        vehicle=inputs["vehicle"],
        algo_source_root=inputs["algo_source_root"],
        config_dir=config_dir,
        config_name=config_name,
    )
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": "planned",
        "target": {
            **inputs,
            "config_dir": str(config_dir or "").strip()
            or _join_remote(
                inputs["arbe_root"],
                "src/arbe_phoenix_radar_driver-master/arbe_gui/Config",
            ),
            "config_name": config_name,
        },
        "command": command,
        "execute_requested": bool(execute),
        "cuda_source_dir_status": "unknown",
        "candidates": [],
        "selected": None,
        "configuration": {"status": "not_available"},
        "provenance": {
            "intake": intake_meta,
            "preflight_ref": preflight_ref,
            "preflight_schema_version": str(preflight_payload.get("schema_version", "")),
            "resolution_basis": "current_source_08_CustData_latest_mtime",
            "read_only": True,
        },
        "diagnostics": [],
    }
    if not execute:
        return payload

    result = runner.run(command, timeout_sec=max(0.5, float(timeout_sec)))
    payload["command_result"] = result.to_dict()
    if not result.ok:
        payload["status"] = "failed"
        payload["diagnostics"] = [
            "cuda_resolution_command_failed",
            *([result.stderr.strip()] if result.stderr.strip() else []),
        ]
        return payload

    parsed = parse_cuda_resolve_output(result.stdout)
    payload["cuda_source_dir_status"] = parsed["cuda_source_dir_status"]
    payload["candidates"] = parsed["candidates"]
    configuration = dict(parsed["configuration"])
    payload["configuration"] = configuration
    candidates = list(parsed["candidates"])
    if parsed["cuda_source_dir_status"] == "missing":
        payload["status"] = "blocked"
        payload["diagnostics"] = ["cuda_source_directory_missing"]
        return payload
    if not candidates:
        payload["status"] = "blocked"
        payload["diagnostics"] = ["cuda_xlsx_candidate_not_found"]
        return payload

    selected = dict(candidates[0])
    selected["selection_basis"] = "highest_remote_mtime_then_path"
    payload["selected"] = selected
    alignment, alignment_diagnostics = _config_alignment(
        configuration=configuration,
        selected=selected,
        expected_sheet=str(inputs.get("cuda_sheet", "")).strip(),
    )
    payload["configuration"]["alignment"] = alignment
    payload["configuration"]["alignment_diagnostics"] = alignment_diagnostics
    payload["diagnostics"] = alignment_diagnostics
    payload["status"] = (
        "partial"
        if configuration.get("status") == "not_available"
        else "ready"
    )
    return payload


__all__ = [
    "CudaResolutionRunner",
    "SCHEMA_VERSION",
    "build_cuda_resolve_command",
    "parse_cuda_resolve_output",
    "resolve_cuda",
    "LocalShellRunner",
    "SshCommandRunner",
]
