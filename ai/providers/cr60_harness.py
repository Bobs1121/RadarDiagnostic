# -*- coding: utf-8 -*-
"""Narrow adapter from Pi to the independent ``cr60-debug-harness`` project.

The provider owns only process invocation and handoff normalization.  Bag
parsing, frame/object association, source indexing, geometry evidence and
HTML rendering remain in the sibling harness.  Commands are passed as an
argument list with ``shell=False`` so dialogue text never becomes shell code.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol


PROVIDER_SCHEMA_VERSION = "cr60-harness-provider.v1"
HANDOFF_SCHEMA_VERSION = "cr60-analysis-intake.v1"
MANIFEST_SCHEMA_VERSION = "intake-manifest.v1"


@dataclass(frozen=True)
class HarnessCommandResult:
    """Captured result of one harness CLI invocation."""

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


class HarnessCommandExecutor(Protocol):
    def run(
        self,
        command: list[str],
        *,
        cwd: Path,
        timeout_sec: float,
    ) -> HarnessCommandResult:
        ...


class LocalHarnessCommandExecutor:
    """Run a generated harness command locally without a shell."""

    def run(
        self,
        command: list[str],
        *,
        cwd: Path,
        timeout_sec: float,
    ) -> HarnessCommandResult:
        import time

        started = time.monotonic()
        frozen_command = tuple(str(item) for item in command)
        try:
            completed = subprocess.run(
                frozen_command,
                cwd=str(cwd),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=max(0.1, float(timeout_sec)),
                check=False,
                shell=False,
            )
            return HarnessCommandResult(
                command=frozen_command,
                returncode=completed.returncode,
                stdout=completed.stdout,
                stderr=completed.stderr,
                duration_sec=time.monotonic() - started,
            )
        except subprocess.TimeoutExpired as exc:
            return HarnessCommandResult(
                command=frozen_command,
                returncode=124,
                stdout=_as_text(exc.stdout),
                stderr=_as_text(exc.stderr),
                timed_out=True,
                duration_sec=time.monotonic() - started,
            )
        except OSError as exc:
            return HarnessCommandResult(
                command=frozen_command,
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


def _safe_id(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._-")
    return cleaned or "case-unknown"


def _file_stem(path: str) -> str:
    name = str(path).replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
    return name.rsplit(".", 1)[0] if "." in name else name


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _bag_items(case: Mapping[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    raw_items = case.get("bag_paths")
    if raw_items is None:
        raw_items = case.get("files")
    if raw_items is None and case.get("bag"):
        raw_items = [case.get("bag")]
    items: list[tuple[str, dict[str, Any]]] = []
    for item in _as_list(raw_items):
        if isinstance(item, str):
            path = item.strip()
            metadata: dict[str, Any] = {}
        elif isinstance(item, Mapping):
            path = str(item.get("path") or item.get("bag") or "").strip()
            metadata = dict(item)
        else:
            path = ""
            metadata = {}
        if path:
            items.append((path, metadata))
    return items


def convert_intake_to_manifest(
    payload: Mapping[str, Any], *, source_path: str = "", allow_partial: bool = False
) -> tuple[dict[str, Any] | None, list[str], list[str]]:
    """Normalize a canonical intake payload to the harness manifest contract.

    This intentionally mirrors only the handoff boundary.  It does not read
    bags, connect to SSH, inspect source, or alter the remote workspace.
    """
    errors: list[str] = []
    warnings: list[str] = []
    if str(payload.get("schema_version", "")) != HANDOFF_SCHEMA_VERSION:
        errors.append(
            f"unsupported intake schema: expected {HANDOFF_SCHEMA_VERSION}, "
            f"got {payload.get('schema_version', 'missing')}"
        )
    status = str(payload.get("status", "blocked"))
    if status == "blocked":
        errors.append("intake status is blocked; resolve missing/conflicting inputs first")
    if status == "partial" and not allow_partial:
        errors.append("intake status is partial; require explicit allow_partial confirmation")
    if status not in {"ready", "partial", "blocked"}:
        errors.append(f"unsupported intake status: {status}")

    environment = payload.get("environment")
    data = payload.get("data")
    if not isinstance(environment, Mapping):
        errors.append("intake.environment must be an object")
        environment = {}
    if not isinstance(data, Mapping):
        errors.append("intake.data must be an object")
        data = {}
    raw_cases = data.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        errors.append("intake.data.cases must be a non-empty list")
        raw_cases = []

    manifest_cases: list[dict[str, Any]] = []
    used_ids: dict[str, int] = {}
    for case_index, raw_case in enumerate(raw_cases):
        if not isinstance(raw_case, Mapping):
            errors.append(f"data.cases[{case_index}] must be an object")
            continue
        base_id = _safe_id(
            str(raw_case.get("case_id") or raw_case.get("tr_id") or "")
        )
        bag_items = _bag_items(raw_case)
        if not bag_items:
            errors.append(f"data.cases[{case_index}] has no bag_paths/files/bag")
            continue
        functions = raw_case.get("functions_hint", raw_case.get("functions", []))
        if isinstance(functions, str):
            functions = [functions]
        if not isinstance(functions, list):
            warnings.append(f"{base_id}: functions hint is not a list; discarded")
            functions = []
        for bag_index, (bag_path, file_metadata) in enumerate(bag_items):
            candidate_id = base_id
            if len(bag_items) > 1:
                candidate_id = _safe_id(f"{base_id}__{_file_stem(bag_path)}")
            used_ids[candidate_id] = used_ids.get(candidate_id, 0) + 1
            if used_ids[candidate_id] > 1:
                candidate_id = f"{candidate_id}__{used_ids[candidate_id]}"
            suffix = Path(bag_path.replace("\\", "/")).suffix.lower()
            if suffix and suffix != ".bag":
                warnings.append(
                    f"{candidate_id}: {suffix} is preserved and will be marked unsupported"
                )
            manifest_cases.append(
                {
                    "case_id": candidate_id,
                    "parent_case_id": str(
                        raw_case.get("case_id") or raw_case.get("tr_id") or candidate_id
                    ),
                    "tr_id": raw_case.get("tr_id"),
                    "bag": bag_path,
                    "format": file_metadata.get("format") or suffix.lstrip("."),
                    "size_bytes": file_metadata.get("size_bytes"),
                    "sha256": file_metadata.get("sha256"),
                    "functions": list(functions),
                    "customer_claim": raw_case.get("customer_claim", ""),
                    "preferred_radar": raw_case.get("preferred_radar", "auto"),
                    "source_selector": dict(raw_case.get("source_selector", {}) or {}),
                    "upstream_provenance": {
                        "handoff_id": payload.get("handoff_id", ""),
                        "handoff_path": source_path,
                        "case_index": case_index,
                        "bag_index": bag_index,
                        "data_dir": raw_case.get("data_dir", ""),
                        "file_metadata": file_metadata,
                    },
                }
            )

    if errors:
        return None, errors, warnings
    return (
        {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "source_kind": HANDOFF_SCHEMA_VERSION,
            "upstream_handoff": {
                "schema_version": payload.get("schema_version"),
                "handoff_id": payload.get("handoff_id", ""),
                "status": status,
                "path": source_path,
            },
            "upstream_environment": dict(environment),
            "data_root": data.get("root", ""),
            "cases": manifest_cases,
        },
        errors,
        warnings,
    )


def _last_json_object(text: str) -> dict[str, Any] | None:
    decoder = json.JSONDecoder()
    found: dict[str, Any] | None = None
    found_end = -1
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        absolute_end = index + end
        # Prefer the outermost/largest complete JSON document.  Harness
        # summaries can contain nested objects; simply keeping the last
        # opening brace would incorrectly return the final nested object.
        if isinstance(value, dict) and absolute_end > found_end:
            found = value
            found_end = absolute_end
    return found


class Cr60HarnessProvider:
    """Plan/execute the independent harness CLI with explicit approval."""

    def __init__(
        self,
        *,
        harness_root: str | Path,
        executor: HarnessCommandExecutor | None = None,
        python_executable: str = "",
        timeout_sec: float = 3600.0,
    ) -> None:
        self.harness_root = Path(harness_root).expanduser().resolve()
        self.executor = executor or LocalHarnessCommandExecutor()
        self.python_executable = python_executable or sys.executable
        self.timeout_sec = max(1.0, float(timeout_sec))

    def validate_root(self) -> list[str]:
        problems: list[str] = []
        required = (
            self.harness_root / "cr60_debug_harness" / "cli.py",
            self.harness_root / "tools" / "build_html_reports.py",
            self.harness_root / "web",
        )
        for path in required:
            if not path.exists():
                problems.append(f"harness_path_missing:{path}")
        return problems

    def validate_profile(self, profile: str | Path) -> list[str]:
        path = self._resolve_profile(profile)
        if not path.is_file():
            return [f"profile_missing:{path}"]
        if path.suffix.lower() not in {".toml", ".json"}:
            return [f"profile_format_unsupported:{path.suffix or '<none>'}"]
        return []

    def validate_context(self, context: str) -> list[str]:
        if not context:
            return []
        path = Path(context).expanduser().resolve()
        return [] if path.is_file() else [f"analysis_context_missing:{path}"]

    def _resolve_profile(self, profile: str | Path) -> Path:
        path = Path(profile).expanduser()
        if not path.is_absolute():
            path = self.harness_root / path
        return path.resolve()

    def _base_command(self, profile: str | Path) -> list[str]:
        del profile
        return [self.python_executable, "-m", "cr60_debug_harness.cli"]

    def _common_args(
        self,
        command: list[str],
        *,
        context: str,
        prepare_context: bool,
        max_source_files: int,
        functions: list[str],
        customer_claim: str,
        web_dist: str,
    ) -> None:
        if context:
            command.extend(["--context", str(Path(context).expanduser().resolve())])
        elif prepare_context:
            command.append("--prepare-context")
            command.extend(["--max-source-files", str(int(max_source_files))])
        if functions:
            for function in functions:
                command.extend(["--function", function])
        if customer_claim:
            command.extend(["--customer-claim", customer_claim])
        command.extend(["--web-dist", web_dist])

    def build_folder_command(
        self,
        *,
        profile: str | Path,
        input_dir: str,
        output_dir: str | Path,
        context: str = "",
        prepare_context: bool = False,
        max_source_files: int = 800,
        functions: list[str] | None = None,
        customer_claim: str = "",
        web_dist: str = "web/dist",
    ) -> list[str]:
        command = self._base_command(profile) + [
            "folder-analyze",
            "--profile",
            str(self._resolve_profile(profile)),
            "--input-dir",
            input_dir,
            "--output",
            str(Path(output_dir).expanduser().resolve()),
            "--html",
        ]
        self._common_args(
            command,
            context=context,
            prepare_context=prepare_context,
            max_source_files=max_source_files,
            functions=list(functions or []),
            customer_claim=customer_claim,
            web_dist=web_dist,
        )
        return command

    def build_batch_command(
        self,
        *,
        profile: str | Path,
        manifest: str | Path,
        output_dir: str | Path,
        context: str = "",
        prepare_context: bool = False,
        max_source_files: int = 800,
        web_dist: str = "web/dist",
    ) -> list[str]:
        command = self._base_command(profile) + [
            "batch-analyze",
            "--profile",
            str(self._resolve_profile(profile)),
            "--manifest",
            str(Path(manifest).expanduser().resolve()),
            "--output",
            str(Path(output_dir).expanduser().resolve()),
            "--html",
        ]
        self._common_args(
            command,
            context=context,
            prepare_context=prepare_context,
            max_source_files=max_source_files,
            functions=[],
            customer_claim="",
            web_dist=web_dist,
        )
        return command

    def build_gdb_plan_command(
        self,
        *,
        profile: str | Path,
        bag: str,
        debug_plan: str | Path,
        target_frame: int,
        radar_id: int,
        master_port: int = 11322,
        start_sec: float = 504.0,
        duration_sec: float = 22.0,
        session_output: str | Path = "",
        keep_remote_logs: bool = False,
    ) -> list[str]:
        """Build the isolated plan-bound GDB runner command.

        This remains an adapter to the sibling harness.  The provider does
        not know feature names or construct GDB expressions; those come from
        ``runtime-debug-plan.v1``.
        """
        command = [
            self.python_executable,
            "-m",
            "tools.run_gdb_isolated_smoke",
            "--profile",
            str(self._resolve_profile(profile)),
            "--bag",
            str(bag),
            "--start-sec",
            str(float(start_sec)),
            "--duration-sec",
            str(float(duration_sec)),
            "--target-frame",
            str(int(target_frame)),
            "--radar-id",
            str(int(radar_id)),
            "--master-port",
            str(int(master_port)),
            "--debug-plan",
            str(Path(debug_plan).expanduser().resolve()),
        ]
        if session_output:
            command.extend(["--session-output", str(Path(session_output).expanduser().resolve())])
        if keep_remote_logs:
            command.append("--keep-remote-logs")
        return command

    def run_gdb_plan(
        self,
        *,
        profile: str | Path,
        bag: str,
        debug_plan: str | Path,
        target_frame: int,
        radar_id: int,
        master_port: int = 11322,
        start_sec: float = 504.0,
        duration_sec: float = 22.0,
        session_output: str | Path = "",
        keep_remote_logs: bool = False,
        execute: bool = False,
    ) -> dict[str, Any]:
        """Plan/execute one isolated, plan-bound GDB session."""
        problems = self.validate_root()
        problems.extend(self.validate_profile(profile))
        plan_path = Path(debug_plan).expanduser().resolve()
        if not plan_path.is_file():
            problems.append(f"runtime_debug_plan_missing:{plan_path}")
        if not str(bag or "").strip():
            problems.append("bag_required")
        if int(radar_id) not in {1, 2, 3, 4}:
            problems.append(f"radar_id_invalid:{radar_id}")
        if problems:
            return {
                "schema_version": PROVIDER_SCHEMA_VERSION,
                "status": "blocked",
                "mode": "gdb_isolated_plan",
                "harness_root": str(self.harness_root),
                "blockers": problems,
            }
        command = self.build_gdb_plan_command(
            profile=profile,
            bag=bag,
            debug_plan=plan_path,
            target_frame=int(target_frame),
            radar_id=int(radar_id),
            master_port=int(master_port),
            start_sec=float(start_sec),
            duration_sec=float(duration_sec),
            session_output=session_output,
            keep_remote_logs=bool(keep_remote_logs),
        )
        output_dir = Path(session_output).expanduser().resolve().parent if session_output else self.harness_root / "outputs"
        result = self.run_command(
            command,
            execute=bool(execute),
            mode="gdb_isolated_plan",
            output_dir=output_dir,
        )
        result["session_output"] = str(Path(session_output).expanduser().resolve()) if session_output else ""
        if session_output and Path(session_output).expanduser().resolve().is_file():
            session_path = Path(session_output).expanduser().resolve()
            result["artifacts"].append(str(session_path))
            try:
                session_payload = json.loads(session_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                session_payload = {}
            if isinstance(session_payload, Mapping):
                result["gdb_session_status"] = session_payload.get("status", "")
                result["gdb_evidence_status"] = session_payload.get("evidence_status", "not_available")
                session_diagnostics = list(session_payload.get("diagnostics", []) or [])
                if session_diagnostics:
                    result["diagnostics"] = session_diagnostics
                    if result.get("status") == "completed":
                        result["status"] = "completed_with_runtime_warnings"
        return result

    def build_gdb_attach_plan_command(
        self,
        *,
        profile: str | Path,
        bag: str,
        debug_plan: str | Path,
        target_frame: int,
        radar_id: int,
        start_sec: float = 504.0,
        duration_sec: float = 22.0,
        node_pattern: str = "/radar{radar_id}_visualization_engine/arbe_visualization_engine",
        topic: str = "",
        ros_master_uri: str = "http://127.0.0.1:11311",
        replay: bool = False,
        wait_sec: float = 30.0,
        session_output: str | Path = "",
        keep_remote_logs: bool = False,
    ) -> list[str]:
        """Build the formal existing-PID attach runner command.

        The sibling runner owns remote ROS/GDB shell details.  This adapter
        only passes the already validated source-bound plan and explicit
        runtime choices; it never starts ``bash start`` or invents watches.
        """
        command = [
            self.python_executable,
            "-m",
            "tools.run_gdb_attach_plan",
            "--profile",
            str(self._resolve_profile(profile)),
            "--bag",
            str(bag),
            "--debug-plan",
            str(Path(debug_plan).expanduser().resolve()),
            "--target-frame",
            str(int(target_frame)),
            "--radar-id",
            str(int(radar_id)),
            "--start-sec",
            str(float(start_sec)),
            "--duration-sec",
            str(float(duration_sec)),
            "--node-pattern",
            str(node_pattern),
            "--ros-master-uri",
            str(ros_master_uri),
            "--wait-sec",
            str(float(wait_sec)),
        ]
        if topic:
            command.extend(["--topic", str(topic)])
        if replay:
            command.append("--replay")
        if session_output:
            command.extend(["--session-output", str(Path(session_output).expanduser().resolve())])
        if keep_remote_logs:
            command.append("--keep-remote-logs")
        return command

    def run_gdb_attach_plan(
        self,
        *,
        profile: str | Path,
        bag: str,
        debug_plan: str | Path,
        target_frame: int,
        radar_id: int,
        start_sec: float = 504.0,
        duration_sec: float = 22.0,
        node_pattern: str = "/radar{radar_id}_visualization_engine/arbe_visualization_engine",
        topic: str = "",
        ros_master_uri: str = "http://127.0.0.1:11311",
        replay: bool = False,
        wait_sec: float = 30.0,
        session_output: str | Path = "",
        keep_remote_logs: bool = False,
        execute: bool = False,
    ) -> dict[str, Any]:
        """Plan/execute an existing-PID formal arbe GDB attach."""
        problems = self.validate_root()
        problems.extend(self.validate_profile(profile))
        plan_path = Path(debug_plan).expanduser().resolve()
        if not plan_path.is_file():
            problems.append(f"runtime_debug_plan_missing:{plan_path}")
        if not str(bag or "").strip():
            problems.append("bag_required")
        if int(radar_id) not in {1, 2, 3, 4}:
            problems.append(f"radar_id_invalid:{radar_id}")
        if not str(ros_master_uri or "").strip():
            problems.append("ros_master_uri_required")
        if problems:
            return {
                "schema_version": PROVIDER_SCHEMA_VERSION,
                "status": "blocked",
                "mode": "gdb_formal_attach",
                "harness_root": str(self.harness_root),
                "blockers": problems,
            }
        command = self.build_gdb_attach_plan_command(
            profile=profile,
            bag=bag,
            debug_plan=plan_path,
            target_frame=int(target_frame),
            radar_id=int(radar_id),
            start_sec=float(start_sec),
            duration_sec=float(duration_sec),
            node_pattern=str(node_pattern),
            topic=str(topic),
            ros_master_uri=str(ros_master_uri),
            replay=bool(replay),
            wait_sec=float(wait_sec),
            session_output=session_output,
            keep_remote_logs=bool(keep_remote_logs),
        )
        output_dir = Path(session_output).expanduser().resolve().parent if session_output else self.harness_root / "outputs"
        result = self.run_command(
            command,
            execute=bool(execute),
            mode="gdb_formal_attach",
            output_dir=output_dir,
        )
        result["session_output"] = str(Path(session_output).expanduser().resolve()) if session_output else ""
        if session_output:
            session_path = Path(session_output).expanduser().resolve()
            if session_path.is_file():
                result["artifacts"].append(str(session_path))
                try:
                    session_payload = json.loads(session_path.read_text(encoding="utf-8"))
                except (OSError, UnicodeError, json.JSONDecodeError):
                    session_payload = {}
                if isinstance(session_payload, Mapping):
                    result["gdb_session_status"] = session_payload.get("status", "")
                    result["gdb_evidence_status"] = session_payload.get("evidence_status", "not_available")
                    result["attach_status"] = (session_payload.get("target", {}) or {}).get("attach_status", "")
                    session_diagnostics = list(session_payload.get("diagnostics", []) or [])
                    if session_diagnostics:
                        result["diagnostics"] = session_diagnostics
                    if session_payload.get("status") == "blocked":
                        result["status"] = "blocked"
        return result

    def build_formal_start_command(
        self,
        *,
        profile: str | Path,
        ros_master_uri: str = "http://127.0.0.1:11311",
        start_path: str = "",
        ready_timeout_sec: float = 45.0,
        clean_remote_log: bool = False,
        session_output: str | Path = "",
    ) -> list[str]:
        """Build the explicit formal ``bash start`` adapter command."""
        command = [
            self.python_executable,
            "-m",
            "tools.run_arbe_formal_start",
            "--profile",
            str(self._resolve_profile(profile)),
            "--ros-master-uri",
            str(ros_master_uri),
            "--ready-timeout-sec",
            str(float(ready_timeout_sec)),
        ]
        if start_path:
            command.extend(["--start-path", str(start_path)])
        if clean_remote_log:
            command.append("--clean-remote-log")
        if session_output:
            command.extend(["--session-output", str(Path(session_output).expanduser().resolve())])
        return command

    def run_formal_start(
        self,
        *,
        profile: str | Path,
        ros_master_uri: str = "http://127.0.0.1:11311",
        start_path: str = "",
        ready_timeout_sec: float = 45.0,
        clean_remote_log: bool = False,
        session_output: str | Path = "",
        execute: bool = False,
    ) -> dict[str, Any]:
        """Plan/execute the owned formal ``bash start`` session."""
        problems = self.validate_root()
        problems.extend(self.validate_profile(profile))
        if not str(ros_master_uri or "").strip():
            problems.append("ros_master_uri_required")
        if problems:
            return {
                "schema_version": PROVIDER_SCHEMA_VERSION,
                "status": "blocked",
                "mode": "arbe_formal_start",
                "harness_root": str(self.harness_root),
                "blockers": problems,
            }
        command = self.build_formal_start_command(
            profile=profile,
            ros_master_uri=ros_master_uri,
            start_path=start_path,
            ready_timeout_sec=ready_timeout_sec,
            clean_remote_log=clean_remote_log,
            session_output=session_output,
        )
        output_dir = Path(session_output).expanduser().resolve().parent if session_output else self.harness_root / "outputs"
        result = self.run_command(
            command,
            execute=bool(execute),
            mode="arbe_formal_start",
            output_dir=output_dir,
        )
        result["session_output"] = str(Path(session_output).expanduser().resolve()) if session_output else ""
        if session_output:
            session_path = Path(session_output).expanduser().resolve()
            if session_path.is_file():
                result["artifacts"].append(str(session_path))
                try:
                    payload = json.loads(session_path.read_text(encoding="utf-8"))
                except (OSError, UnicodeError, json.JSONDecodeError):
                    payload = {}
                if isinstance(payload, Mapping):
                    result["start_status"] = payload.get("status", "")
                    result["ownership"] = payload.get("ownership", "")
                    result["session_id"] = payload.get("session_id", "")
                    if payload.get("status") in {"blocked", "failed", "already_running"}:
                        result["status"] = str(payload.get("status"))
        return result

    def build_formal_stop_command(
        self,
        *,
        profile: str | Path,
        session_path: str | Path,
        output: str | Path = "",
    ) -> list[str]:
        """Build the guarded formal process-group stop command."""
        command = [
            self.python_executable,
            "-m",
            "tools.run_arbe_formal_stop",
            "--profile",
            str(self._resolve_profile(profile)),
            "--session-path",
            str(Path(session_path).expanduser().resolve()),
        ]
        if output:
            command.extend(["--output", str(Path(output).expanduser().resolve())])
        return command

    def run_formal_stop(
        self,
        *,
        profile: str | Path,
        session_path: str | Path,
        output: str | Path = "",
        execute: bool = False,
    ) -> dict[str, Any]:
        """Plan/execute a stop for a tool-owned formal start session."""
        problems = self.validate_root()
        problems.extend(self.validate_profile(profile))
        session = Path(session_path).expanduser().resolve()
        if not session.is_file():
            problems.append(f"arbe_start_session_missing:{session}")
        else:
            try:
                session_payload = json.loads(session.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                session_payload = None
            if not isinstance(session_payload, Mapping):
                problems.append("arbe_start_session_invalid")
            elif session_payload.get("ownership") != "tool_started":
                problems.append("arbe_start_session_not_tool_owned")
            else:
                start = session_payload.get("start", {}) or {}
                if not isinstance(start, Mapping) or not isinstance(start.get("pid"), int):
                    problems.append("arbe_start_session_pid_unresolved")
        if problems:
            return {
                "schema_version": PROVIDER_SCHEMA_VERSION,
                "status": "blocked",
                "mode": "arbe_formal_stop",
                "harness_root": str(self.harness_root),
                "blockers": problems,
            }
        command = self.build_formal_stop_command(profile=profile, session_path=session, output=output)
        output_dir = Path(output).expanduser().resolve().parent if output else self.harness_root / "outputs"
        result = self.run_command(
            command,
            execute=bool(execute),
            mode="arbe_formal_stop",
            output_dir=output_dir,
        )
        if output:
            output_path = Path(output).expanduser().resolve()
            if output_path.is_file():
                try:
                    payload = json.loads(output_path.read_text(encoding="utf-8"))
                except (OSError, UnicodeError, json.JSONDecodeError):
                    payload = {}
                if isinstance(payload, Mapping):
                    result["stop_status"] = payload.get("status", "")
                    result["artifacts"].append(str(output_path))
                    if payload.get("status") not in {"stopped", "completed"}:
                        result["status"] = "blocked"
                    session_diagnostics = list(payload.get("diagnostics", []) or [])
                    if session_diagnostics:
                        result["diagnostics"] = session_diagnostics
        return result

    def run_command(
        self, command: list[str], *, execute: bool, mode: str, output_dir: str | Path
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "schema_version": PROVIDER_SCHEMA_VERSION,
            "mode": mode,
            "harness_root": str(self.harness_root),
            "command": list(command),
            "command_display": " ".join(_display_arg(item) for item in command),
            "execute_requested": bool(execute),
            "status": "planned",
            "artifacts": [],
        }
        if not execute:
            result["status"] = "planned"
            return result
        command_result = self.executor.run(
            command,
            cwd=self.harness_root,
            timeout_sec=self.timeout_sec,
        )
        result["command_result"] = command_result.to_dict()
        result["stdout"] = command_result.stdout
        result["stderr"] = command_result.stderr
        parsed = _last_json_object(command_result.stdout)
        if parsed is not None:
            result["harness_result"] = parsed
        output_path = Path(output_dir).expanduser().resolve()
        result["output_dir"] = str(output_path)
        for relative in ("batch_summary.json", "index.html", "batch-index.json"):
            artifact = output_path / relative
            if artifact.exists():
                result["artifacts"].append(str(artifact))
        case_artifacts: list[dict[str, Any]] = []
        cases_root = output_path / "cases"
        data_root = output_path / "data"
        if cases_root.is_dir():
            for bundle_path in sorted(cases_root.glob("*/diagnosis_bundle.json")):
                case_id = bundle_path.parent.name
                data_dir = data_root / case_id
                ref: dict[str, Any] = {
                    "case_id": case_id,
                    "bundle_path": str(bundle_path),
                }
                for name, key in (
                    ("viewer-model.json", "viewer_model_path"),
                    ("runtime_evidence.json", "runtime_evidence_path"),
                    ("runtime_debug_plan.json", "runtime_debug_plan_path"),
                    ("runtime_schema.json", "runtime_schema_path"),
                ):
                    candidate = data_dir / name
                    if candidate.is_file():
                        ref[key] = str(candidate)
                report = data_dir / "report.html"
                if report.is_file():
                    ref["report_path"] = str(report)
                case_artifacts.append(ref)
        result["case_artifacts"] = case_artifacts
        if command_result.timed_out:
            result["status"] = "timeout"
        elif command_result.returncode != 0:
            # The harness deliberately returns non-zero for blocked/unsupported
            # cases while still emitting valid per-case artifacts.
            result["status"] = "completed_with_case_failures" if parsed else "failed"
        else:
            result["status"] = "completed"
        return result

    def run_folder(self, **kwargs: Any) -> dict[str, Any]:
        problems = self.validate_root()
        problems.extend(self.validate_profile(kwargs.get("profile", "")))
        problems.extend(self.validate_context(str(kwargs.get("context", ""))))
        if problems:
            return {
                "schema_version": PROVIDER_SCHEMA_VERSION,
                "status": "blocked",
                "mode": "folder",
                "harness_root": str(self.harness_root),
                "blockers": problems,
            }
        execute = bool(kwargs.pop("execute", False))
        output_dir = kwargs["output_dir"]
        command = self.build_folder_command(**kwargs)
        return self.run_command(
            command,
            execute=execute,
            mode="folder",
            output_dir=output_dir,
        )

    def run_handoff(
        self,
        *,
        profile: str | Path,
        intake_path: str | Path,
        output_dir: str | Path,
        context: str = "",
        prepare_context: bool = False,
        max_source_files: int = 800,
        web_dist: str = "web/dist",
        allow_partial: bool = False,
        execute: bool = False,
    ) -> dict[str, Any]:
        problems = self.validate_root()
        problems.extend(self.validate_profile(profile))
        problems.extend(self.validate_context(context))
        if problems:
            return {
                "schema_version": PROVIDER_SCHEMA_VERSION,
                "status": "blocked",
                "mode": "handoff",
                "harness_root": str(self.harness_root),
                "blockers": problems,
            }
        path = Path(intake_path).expanduser().resolve()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return {
                "schema_version": PROVIDER_SCHEMA_VERSION,
                "status": "blocked",
                "mode": "handoff",
                "blockers": [f"intake_read_failed:{type(exc).__name__}:{exc}"],
            }
        if not isinstance(payload, Mapping):
            return {
                "schema_version": PROVIDER_SCHEMA_VERSION,
                "status": "blocked",
                "mode": "handoff",
                "blockers": ["intake_root_must_be_object"],
            }
        manifest, errors, warnings = convert_intake_to_manifest(
            payload, source_path=str(path), allow_partial=allow_partial
        )
        if errors or manifest is None:
            return {
                "schema_version": PROVIDER_SCHEMA_VERSION,
                "status": "blocked",
                "mode": "handoff",
                "intake_path": str(path),
                "errors": errors,
                "warnings": warnings,
            }
        output_path = Path(output_dir).expanduser().resolve()
        manifest_path = output_path / "intake_manifest.json"
        if execute:
            output_path.mkdir(parents=True, exist_ok=True)
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        command = self.build_batch_command(
            profile=profile,
            manifest=manifest_path,
            output_dir=output_path,
            context=context,
            prepare_context=prepare_context,
            max_source_files=max_source_files,
            web_dist=web_dist,
        )
        result = self.run_command(
            command,
            execute=execute,
            mode="handoff",
            output_dir=output_path,
        )
        result.update(
            {
                "intake_path": str(path),
                "manifest_path": str(manifest_path),
                "manifest_case_count": len(manifest.get("cases", [])),
                "warnings": warnings,
            }
        )
        if execute and manifest_path.exists():
            result["artifacts"].insert(0, str(manifest_path))
        return result

    def run_manifest(
        self,
        *,
        profile: str | Path,
        manifest: str | Path,
        output_dir: str | Path,
        context: str = "",
        prepare_context: bool = False,
        max_source_files: int = 800,
        web_dist: str = "web/dist",
        execute: bool = False,
    ) -> dict[str, Any]:
        """Plan/execute an already prepared harness manifest."""
        problems = self.validate_root()
        problems.extend(self.validate_profile(profile))
        problems.extend(self.validate_context(context))
        manifest_path = Path(manifest).expanduser().resolve()
        if not manifest_path.is_file():
            problems.append(f"manifest_missing:{manifest_path}")
        if problems:
            return {
                "schema_version": PROVIDER_SCHEMA_VERSION,
                "status": "blocked",
                "mode": "manifest",
                "harness_root": str(self.harness_root),
                "blockers": problems,
            }
        output_path = Path(output_dir).expanduser().resolve()
        command = self.build_batch_command(
            profile=profile,
            manifest=manifest_path,
            output_dir=output_path,
            context=context,
            prepare_context=prepare_context,
            max_source_files=max_source_files,
            web_dist=web_dist,
        )
        result = self.run_command(
            command,
            execute=execute,
            mode="manifest",
            output_dir=output_path,
        )
        result["manifest_path"] = str(manifest_path)
        return result


def _display_arg(value: str) -> str:
    # Output is informational only; retain exact argv separately in `command`.
    if not value or re.search(r"[\s\"']", value):
        return json.dumps(value, ensure_ascii=False)
    return value


__all__ = [
    "PROVIDER_SCHEMA_VERSION",
    "Cr60HarnessProvider",
    "HarnessCommandExecutor",
    "HarnessCommandResult",
    "LocalHarnessCommandExecutor",
    "convert_intake_to_manifest",
]
