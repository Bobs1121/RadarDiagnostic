# -*- coding: utf-8 -*-
"""RemoteArbeReplayProvider — 远程 SSH arbe 公共输出回放提供者。

公共输出 capture 已通过注入的 SSH/scp 底座实现真实短时回放；历史 trace job 接口保留兼容语义。
远端只运行既有 ROS/arbe，不安装文件或修改工作区。

SSH 流程（对齐 skill `cr60light-arbe-build` / 服务器 10.190.171.44）：

1. `submit`、`poll`、`fetch_trace`、`fetch_kpi` 是旧 trace job 兼容接口，
   当前仍保留 fail-soft 语义。
2. `capture_public` 通过注入的 SSH/scp runner 执行短窗口公共 topic 录制，
   并可将 capture JSON 拉回本地。

所有方法对未实现的 SSH 底座都 fail-soft（返回空/降级 status），不 raise。

"""
from __future__ import annotations

import base64
import json
import logging
import math
import shlex
import shutil
import subprocess
import tempfile
import time
from pathlib import Path, PurePosixPath
from typing import Any, Optional, Protocol, Sequence

from .preflight import CommandResult, SshCommandRunner
from .replay_provider import (
    ArbeReplayProvider,
    TraceEvent,
    WARNING_BITS,
    parse_warning_trace_csv,
)
from .ros_inventory import validate_topics

log = logging.getLogger(__name__)

PUBLIC_CAPTURE_SCHEMA = "arbe-public-replay-session.v1"
_CAPTURE_BEGIN = "__CR60_PUBLIC_CAPTURE_BEGIN__"
_CAPTURE_END = "__CR60_PUBLIC_CAPTURE_END__"

# The extractor is deliberately generic at the ROS message boundary.  It
# serialises ROS messages through __slots__ and only gives special treatment to
# the three current public channels and their topic-derived radar id.  This
# keeps the remote provider independent of a particular feature or object
# field set; the normalizer and current-source schema decide the meaning later.
_PUBLIC_CAPTURE_EXTRACTOR = r'''
import json
import sys
import rosbag

path = sys.argv[1]

def plain(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    slots = getattr(value, "__slots__", None)
    if slots is not None:
        return {str(name): plain(getattr(value, name)) for name in slots}
    return str(value)

capture = {
    "schema_version": "public-runtime-capture.v1",
    "warning_rows": [],
    "radar_info_rows": [],
    "object_rows": [],
    "roi_rows": [],
}

message_seq = 0
with rosbag.Bag(path, "r") as bag:
    for topic, msg, bag_time in bag.read_messages():
        message_seq += 1
        stamp = bag_time.to_sec()
        if topic in ("/corner_radar/warning_status", "/corner_radar/warning_status_raw", "/corner_radar/warning_status_with_frame"):
            capture["warning_rows"].append({
                "topic": topic,
                "record_time": stamp,
                "message_seq": message_seq,
                "source": topic.rsplit("/", 1)[-1],
                "data": [int(value) for value in list(getattr(msg, "data", []))],
            })
        elif topic == "/corner_radar/radar_info":
            capture["radar_info_rows"].append({
                "topic": topic,
                "record_time": stamp,
                "message_seq": message_seq,
                "source": "radar_info",
                "data": [float(value) for value in list(getattr(msg, "data", []))],
            })
        elif topic.startswith("/wf/objectlist_"):
            try:
                radar_id = int(topic.rsplit("_", 1)[1])
            except (TypeError, ValueError):
                radar_id = None
            header = getattr(msg, "header", None)
            header_stamp = header.stamp.to_sec() if header is not None else None
            for index, obj in enumerate(getattr(msg, "ObjectsBuffer", [])):
                row = plain(obj)
                if isinstance(row, dict):
                    row.update({
                        "topic": topic,
                        "record_time": stamp,
                        "object_message_seq": message_seq,
                        "header_stamp": header_stamp,
                        "radar_id": radar_id,
                        "object_index": index,
                    })
                    capture["object_rows"].append(row)
        elif topic.startswith("/corner_radar/rviz/") and "Area_" in topic:
            try:
                radar_id = int(topic.rsplit("_", 1)[1])
            except (TypeError, ValueError):
                radar_id = None
            points = []
            for marker in getattr(msg, "markers", []):
                for point in getattr(marker, "points", []):
                    points.append({"x": float(point.x), "y": float(point.y), "z": float(point.z)})
            capture["roi_rows"].append({
                "topic": topic,
                "record_time": stamp,
                "message_seq": message_seq,
                "radar_id": radar_id,
                "point_count": len(points),
                "points": points,
            })

json.dump(capture, sys.stdout, ensure_ascii=False, allow_nan=True)
'''


class ScpArtifactFetcher(Protocol):
    def fetch(self, remote_path: str, local_path: str | Path, *, timeout_sec: float) -> CommandResult:
        ...


class SubprocessScpFetcher:
    """Small injectable scp adapter; it does not install anything remotely."""

    def __init__(self, *, host: str, username: str = "", port: int = 22, identity_file: str = "") -> None:
        self.host = str(host).strip()
        self.username = str(username).strip()
        self.port = int(port)
        self.identity_file = str(identity_file).strip()

    @property
    def destination(self) -> str:
        return f"{self.username}@{self.host}" if self.username else self.host

    def fetch(self, remote_path: str, local_path: str | Path, *, timeout_sec: float) -> CommandResult:
        started = time.monotonic()
        target = Path(local_path).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        args = ["scp", "-q", "-o", "BatchMode=yes", "-o", f"ConnectTimeout={max(1, int(min(timeout_sec, 60.0)))}", "-P", str(self.port)]
        if self.identity_file:
            args.extend(["-i", self.identity_file])
        args.extend([f"{self.destination}:{remote_path}", str(target)])
        display = " ".join(shlex.quote(item) for item in args)
        try:
            completed = subprocess.run(
                args, capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=max(0.1, float(timeout_sec)), check=False,
            )
            return CommandResult(
                command=display,
                returncode=completed.returncode,
                stdout=completed.stdout,
                stderr=completed.stderr,
                duration_sec=time.monotonic() - started,
            )
        except subprocess.TimeoutExpired as exc:
            return CommandResult(
                command=display,
                returncode=124,
                stdout=str(exc.stdout or ""),
                stderr=str(exc.stderr or ""),
                timed_out=True,
                duration_sec=time.monotonic() - started,
            )
        except OSError as exc:
            return CommandResult(
                command=display,
                returncode=127,
                stderr=f"{type(exc).__name__}: {exc}",
                duration_sec=time.monotonic() - started,
            )


def _remote_absolute_path(value: str, field: str) -> str:
    text = str(value or "").strip()
    if not text or not text.startswith("/"):
        raise ValueError(f"{field} must be an absolute remote POSIX path")
    if any(char in text for char in ("\x00", "\r", "\n")):
        raise ValueError(f"{field} contains a control character")
    return text


def _finite_number(value: float, field: str, *, minimum: float = 0.0) -> float:
    result = float(value)
    if not math.isfinite(result) or result < minimum:
        raise ValueError(f"{field} must be a finite number >= {minimum}")
    return result


def build_public_capture_command(
    *,
    remote_bag_path: str,
    remote_capture_base: str,
    start_sec: float,
    duration_sec: float,
    input_topics: Sequence[str],
    output_topics: Sequence[str],
    ros_setup: str = "/opt/ros/noetic/setup.bash",
    workspace_setup: str = "",
    ros_master_uri: str = "http://localhost:11311",
) -> dict[str, Any]:
    """Build an SSH command that records public outputs during a short replay."""
    bag = _remote_absolute_path(remote_bag_path, "remote_bag_path")
    base = _remote_absolute_path(remote_capture_base, "remote_capture_base").removesuffix(".bag")
    start = _finite_number(start_sec, "start_sec")
    duration = _finite_number(duration_sec, "duration_sec", minimum=0.01)
    inputs = [str(item).strip() for item in input_topics if str(item).strip()]
    outputs = [str(item).strip() for item in output_topics if str(item).strip()]
    errors = validate_topics([*inputs, *outputs])
    if errors:
        raise ValueError("; ".join(errors))
    if not inputs:
        raise ValueError("input_topics is required")
    if not outputs:
        raise ValueError("output_topics is required")
    setup = str(ros_setup or "").strip()
    if not setup:
        raise ValueError("ros_setup is required")
    master = str(ros_master_uri or "").strip()
    if not master or any(char in master for char in ("\x00", "\r", "\n")):
        raise ValueError("ros_master_uri is required and must be one line")

    bag_path = f"{base}.bag"
    json_path = f"{base}.json"
    log_path = f"{base}.log"
    play_log_path = f"{base}.play.log"
    parent = PurePosixPath(base).parent.as_posix()
    encoded_extractor = base64.b64encode(_PUBLIC_CAPTURE_EXTRACTOR.encode("utf-8")).decode("ascii")
    lines = [
        f"source {shlex.quote(setup)}",
    ]
    if workspace_setup:
        lines.append(f"source {shlex.quote(str(workspace_setup))}")
    capture_body = [
        f"export ROS_MASTER_URI={shlex.quote(master)}",
        f"mkdir -p {shlex.quote(parent)}",
        f"rm -f {shlex.quote(bag_path)} {shlex.quote(bag_path + '.active')} {shlex.quote(json_path)} {shlex.quote(log_path)} {shlex.quote(play_log_path)}",
        f"rosbag record -O {shlex.quote(base)} {' '.join(shlex.quote(item) for item in outputs)} >{shlex.quote(log_path)} 2>&1 & rec=$!",
        "sleep 2",
        f"timeout {duration + 15.0:g}s rosbag play --clock --start {start:g} --duration {duration:g} {shlex.quote(bag)} --topics {' '.join(shlex.quote(item) for item in inputs)} >{shlex.quote(play_log_path)} 2>&1; play_rc=$?",
        "sleep 1",
        # rosbag record is a Python wrapper around a C++ recorder. Sending the
        # interrupt to its direct child avoids the known Noetic wrapper handler
        # issue and lets the recorder close its index normally.
        "children=$(pgrep -P \"$rec\" 2>/dev/null || true); for child in $children; do kill -INT \"$child\" 2>/dev/null || true; done",
        "wait \"$rec\" 2>/dev/null; record_rc=$?",
        "for child in $(pgrep -P \"$rec\" 2>/dev/null || true); do kill -TERM \"$child\" 2>/dev/null || true; done",
        f"printf '%s\\n' {shlex.quote(_CAPTURE_BEGIN)}",
        f"printf 'play_rc\\t%s\\n' \"$play_rc\"",
        f"printf 'record_rc\\t%s\\n' \"$record_rc\"",
        f"printf 'capture_bag\\t%s\\n' {shlex.quote(bag_path)}",
        f"printf 'capture_json\\t%s\\n' {shlex.quote(json_path)}",
        f"printf '%s' {encoded_extractor} | base64 -d | python3 - {shlex.quote(bag_path)} >{shlex.quote(json_path)}; extract_rc=$?",
        f"printf 'extract_rc\\t%s\\n' \"$extract_rc\"",
        f"if test -s {shlex.quote(json_path)}; then printf 'capture_json_present\\tyes\\n'; else printf 'capture_json_present\\tno\\n'; fi",
        f"printf '%s\\n' {shlex.quote(_CAPTURE_END)}",
    ]
    # Keep all recorder variables in the same shell process.  Without this
    # group, `cmd1 && background & rec=$! && cmd2` backgrounds the whole
    # preparation chain and loses the sourced ROS environment in cmd2.
    lines.append("( " + "; ".join(capture_body) + " )")
    return {
        "command": " && ".join(lines),
        "remote_capture_base": base,
        "remote_capture_bag": bag_path,
        "remote_capture_json": json_path,
        "input_topics": inputs,
        "output_topics": outputs,
        "start_sec": start,
        "duration_sec": duration,
    }


def parse_public_capture_result(text: str) -> dict[str, Any]:
    """Parse the bounded marker section emitted by the remote replay command."""
    values: dict[str, str] = {}
    section = False
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if line == _CAPTURE_BEGIN:
            section = True
            continue
        if line == _CAPTURE_END:
            section = False
            continue
        if section and "\t" in line:
            key, value = line.split("\t", 1)
            values[key.strip()] = value.strip()
    for key in ("play_rc", "record_rc", "extract_rc"):
        if key in values:
            try:
                values[key] = int(values[key])
            except ValueError:
                pass
    return values


class RemoteArbeReplayProvider(ArbeReplayProvider):
    """远程 SSH 回放提供者。

    默认不执行任何真实远程命令；``_ssh`` / ``_scp`` 需要被覆盖（适配
    paramiko / subprocess ssh / 现有 skill 脚本）才能真正工作。
    """

    source_kind = "arbe-remote"

    def __init__(
        self,
        host: str = "",
        work_dir: str = "",
        local_cache: str = "",
        username: str = "",
        port: int = 22,
        runner: Any | None = None,
        scp_fetcher: ScpArtifactFetcher | None = None,
    ):
        self.host = host
        self.username = username
        self.work_dir = work_dir
        self.local_cache = Path(local_cache) if local_cache else None
        self.port = int(port)
        self.runner = runner or (
            SshCommandRunner(host=self.host, username=self.username, port=self.port)
            if self.host else None
        )
        self.scp_fetcher = scp_fetcher or (
            SubprocessScpFetcher(host=self.host, username=self.username, port=self.port)
            if self.host else None
        )
        self._cache: dict[str, Path] = {}

    # ── 接口实现 ---------------------------------------------------

    def submit(self, case_dir: str, replay_mode: str = "fctb") -> str:
        job_id = f"arb_{abs(hash(case_dir or replay_mode)) % 10**6:06d}"
        if self.local_cache is not None:
            self.local_cache.mkdir(parents=True, exist_ok=True)
        log.info("RemoteArbeReplayProvider.submit: job=%s (SSH 提交未启用，仅记录)",
                 job_id)
        # 真实实现：scp case_dir → server:{work_dir}/{job_id}，后台起回放。
        # self._scp(case_dir, f"{self._host_path(job_id)}/")
        # self._ssh(f"cd {self._host_path(job_id)} && nohup bash replay.sh > log 2>&1 &")
        self._last_job = job_id
        return job_id

    def poll(self, job_ref: str) -> str:
        log.info("poll(%s): 远程轮询未启用, 返回 'pending'", job_ref)
        return "pending"

    def fetch_trace(self, job_ref: str) -> list[TraceEvent]:
        trace_path = self._pull_single(job_ref, "*_algo_warning_trace.csv",
                                        suffix="_trace.csv")
        if trace_path is None:
            return []
        return parse_warning_trace_csv(trace_path)

    def fetch_kpi(self, job_ref: str) -> dict:
        import json
        kpi_path = self._pull_single(job_ref, "*_kpi_summary*.json", "_kpi.json")
        if kpi_path is None:
            return {}
        try:
            return json.loads(kpi_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {}

    def capture_public(
        self,
        *,
        remote_bag_path: str,
        remote_capture_base: str,
        start_sec: float,
        duration_sec: float,
        input_topics: Sequence[str],
        output_topics: Sequence[str],
        ros_setup: str = "/opt/ros/noetic/setup.bash",
        workspace_setup: str = "",
        ros_master_uri: str = "http://localhost:11311",
        execute: bool = False,
        local_capture_path: str | Path = "",
        timeout_sec: float = 120.0,
    ) -> dict[str, Any]:
        """Plan/execute one public replay capture in an existing ROS session."""
        plan = build_public_capture_command(
            remote_bag_path=remote_bag_path,
            remote_capture_base=remote_capture_base,
            start_sec=start_sec,
            duration_sec=duration_sec,
            input_topics=input_topics,
            output_topics=output_topics,
            ros_setup=ros_setup,
            workspace_setup=workspace_setup,
            ros_master_uri=ros_master_uri,
        )
        payload: dict[str, Any] = {
            "schema_version": PUBLIC_CAPTURE_SCHEMA,
            "status": "planned",
            "mode": "remote_public",
            "target": {
                "host": self.host,
                "user": self.username,
                "port": self.port,
                "remote_bag_path": remote_bag_path,
                "ros_master_uri": ros_master_uri,
            },
            "command": plan["command"],
            "execute_requested": bool(execute),
            "remote_capture_bag": plan["remote_capture_bag"],
            "remote_capture_json": plan["remote_capture_json"],
            "diagnostics": [],
        }
        if not execute:
            return payload
        if self.runner is None:
            payload["status"] = "failed"
            payload["diagnostics"].append("remote_runner_unavailable")
            return payload
        result = self.runner.run(plan["command"], timeout_sec=max(1.0, float(timeout_sec)))
        marker_values = parse_public_capture_result(result.stdout)
        payload["command_result"] = result.to_dict()
        payload["marker_result"] = marker_values
        play_rc = marker_values.get("play_rc")
        extract_rc = marker_values.get("extract_rc")
        if result.timed_out:
            payload["status"] = "timeout"
            payload["diagnostics"].append("remote_public_capture_timeout")
        elif play_rc == 0 and extract_rc == 0 and marker_values.get("capture_json_present") == "yes":
            payload["status"] = "completed"
        elif play_rc == 0:
            payload["status"] = "partial"
            payload["diagnostics"].append("replay_completed_but_capture_extract_incomplete")
        else:
            payload["status"] = "failed"
            payload["diagnostics"].append(f"remote_replay_returncode:{play_rc}")

        if local_capture_path and payload["status"] in {"completed", "partial"}:
            if self.scp_fetcher is None:
                payload["diagnostics"].append("scp_fetcher_unavailable")
            else:
                local_path = Path(local_capture_path).expanduser().resolve()
                fetched = self.scp_fetcher.fetch(
                    str(marker_values.get("capture_json") or plan["remote_capture_json"]),
                    local_path,
                    timeout_sec=max(1.0, float(timeout_sec)),
                )
                payload["fetch_result"] = fetched.to_dict()
                if fetched.ok:
                    payload["local_capture_json"] = str(local_path)
                    payload.setdefault("artifacts", []).append(str(local_path))
                else:
                    payload["status"] = "partial"
                    payload["diagnostics"].append("local_capture_fetch_failed")
        return payload

    # ── 内部：legacy SSH 底座（公共 capture 使用 injected runner） ------

    def _host_path(self, job_ref: str) -> str:
        return f"{self.work_dir.rstrip('/')}/{job_ref}"

    def _pull_single(self, job_ref: str, pattern: str, suffix: str) -> Optional[Path]:
        """从服务器拉取一个匹配文件到本地缓存。默认未实现 → None。"""
        if self.local_cache is None:
            return None
        cache_hit = self._cached(job_ref, suffix)
        if cache_hit is not None:
            return cache_hit
        log.info("_pull_single(%s, %s): 远程 scp 未启用 (not implemented)", job_ref, pattern)
        return None

    def _cached(self, job_ref: str, suffix: str) -> Optional[Path]:
        p = self.local_cache / f"{job_ref}{suffix}"
        return p if p.exists() else None

    def _ssh(self, cmd: str) -> str:
        """执行远程命令。默认为 NotImplemented 语义（log 并返回空）。"""
        log.warning("RemoteArbReplayProvider._ssh 未实现: %s", cmd)
        return ""

    def _scp(self, src: str, dst: str) -> None:
        log.warning("RemoteArbReplayProvider._scp 未实现: %s -> %s", src, dst)

    @staticmethod
    def has_ssh() -> bool:
        return shutil.which("ssh") is not None


__all__ = [
    "PUBLIC_CAPTURE_SCHEMA",
    "RemoteArbeReplayProvider",
    "ScpArtifactFetcher",
    "SubprocessScpFetcher",
    "build_public_capture_command",
    "parse_public_capture_result",
]
