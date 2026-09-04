# -*- coding: utf-8 -*-
"""SimVerifyModule (V4 P4) — 仿真验证（arbe-replay）。

本地模式解析已产出的 warning trace / KPI；远程模式通过 SSH 复用当前 ROS/arbe
会话采集公共输出，再交给 public-runtime-normalize 归一化，供 Pi 调度验证。

独立运行::

    python cli.py sim-verify --case-dir cases/xxx --mode local
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Mapping, Sequence

from .base import BaseModule, ModuleResult

log = logging.getLogger(__name__)

MODES = ("local", "remote_public")


def _warning_contract_from_case(case_dir: str, explicit: Sequence[str] | None) -> Sequence[str]:
    """Prefer the current case/runtime schema over the legacy CR60 map."""
    values = [str(item).strip() for item in (explicit or []) if str(item).strip()]
    if values:
        return values
    root = Path(case_dir).expanduser()
    candidates = [root / "runtime_schema.json", root.parent / "runtime_schema.json"]
    for path in candidates:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        contract = payload.get("warning_contract") if isinstance(payload, Mapping) else None
        bits = contract.get("bits") if isinstance(contract, Mapping) else None
        if isinstance(bits, Mapping):
            ordered = []
            for key in sorted(bits, key=lambda item: int(item) if str(item).isdigit() else 10**9):
                value = str(bits[key] or "").strip()
                if value:
                    ordered.append(value)
            if ordered:
                return ordered
        names = payload.get("warning_names") if isinstance(payload, Mapping) else None
        if isinstance(names, list) and names:
            return [str(item).strip() for item in names if str(item).strip()]
    return []


class SimVerifyModule(BaseModule):
    name = "sim-verify"
    description = "仿真验证：解析 arbe 回放产生的 warning trace / KPI"
    tags = ["arbe", "replay", "verify", "public-runtime", "atomic"]
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "mode": {"type": "string", "enum": list(MODES)},
            "case_dir": {"type": "string"},
            "output_dir": {"type": "string"},
            "server_host": {"type": "string"},
            "server_user": {"type": "string"},
            "server_port": {"type": "integer"},
            "remote_bag_path": {"type": "string"},
            "remote_capture_base": {"type": "string"},
            "local_capture_path": {"type": "string"},
            "input_topics": {"type": "array", "items": {"type": "string"}},
            "output_topics": {"type": "array", "items": {"type": "string"}},
            "ros_setup": {"type": "string"},
            "workspace_setup": {"type": "string"},
            "ros_master_uri": {"type": "string"},
            "start_sec": {"type": "number"},
            "duration_sec": {"type": "number"},
            "warning_names": {"type": "array", "items": {"type": "string"}},
            "object_association_mode": {"type": "string", "enum": ["auto", "strict", "publication_order"]},
            "object_validity_policy": {"type": "string", "enum": ["preserve", "arbe_wf_sobj"]},
            "preflight": {"type": "object"},
            "preflight_path": {"type": "string"},
            "source_context": {"type": "object"},
            "execute": {"type": "boolean"},
            "approved": {"type": "boolean"},
            "timeout_sec": {"type": "number"},
            "output": {"type": "string"},
        },
        "additionalProperties": False,
    }
    output_schema: dict[str, Any] = {
        "type": "object",
        "required": ["schema_version", "status", "mode"],
        "properties": {
            "schema_version": {"type": "string"},
            "status": {"type": "string"},
            "mode": {"type": "string"},
            "trace": {"type": "array"},
            "active_warnings": {"type": "object"},
            "warning_mapping_source": {"type": "string"},
        },
    }

    def __init__(self, *, case_dir: str = "", mode: str = "local",
                 output_dir: str = ""):
        self.case_dir = Path(case_dir) if case_dir else None
        self.mode = mode
        self.output_dir = Path(output_dir) if output_dir else None

    def run(
        self,
        *,
        mode: str = "",
        case_dir: str = "",
        output_dir: str = "",
        server_host: str = "",
        server_user: str = "",
        server_port: int = 22,
        remote_bag_path: str = "",
        remote_capture_base: str = "",
        local_capture_path: str = "",
        input_topics: Sequence[str] | None = None,
        output_topics: Sequence[str] | None = None,
        ros_setup: str = "/opt/ros/noetic/setup.bash",
        workspace_setup: str = "",
        ros_master_uri: str = "http://localhost:11311",
        start_sec: float = 0.0,
        duration_sec: float = 4.0,
        warning_names: Sequence[str] | None = None,
        object_association_mode: str = "auto",
        object_validity_policy: str = "preserve",
        preflight: Mapping[str, Any] | None = None,
        preflight_path: str = "",
        source_context: Mapping[str, Any] | None = None,
        execute: bool = False,
        approved: bool = False,
        timeout_sec: float = 120.0,
        output: str = "",
        **_: Any,
    ) -> ModuleResult:
        if not mode:
            mode = self.mode
        if mode not in MODES:
            return ModuleResult.fail(f"不支持的 mode '{mode}'，可用: {MODES}",
                                     module=self.name)
        if not case_dir and self.case_dir:
            case_dir = str(self.case_dir)
        if preflight is None and preflight_path:
            try:
                value = json.loads(Path(preflight_path).expanduser().read_text(encoding="utf-8"))
                preflight = value if isinstance(value, Mapping) else None
            except (OSError, UnicodeError, json.JSONDecodeError):
                preflight = None
        if mode == "remote_public":
            return self._run_remote_public(
                server_host=server_host,
                server_user=server_user,
                server_port=server_port,
                remote_bag_path=remote_bag_path,
                remote_capture_base=remote_capture_base,
                local_capture_path=local_capture_path,
                input_topics=list(input_topics or []),
                output_topics=list(output_topics or []),
                ros_setup=ros_setup,
                workspace_setup=workspace_setup,
                ros_master_uri=ros_master_uri,
                start_sec=start_sec,
                duration_sec=duration_sec,
                warning_names=list(warning_names or []),
                object_association_mode=object_association_mode,
                object_validity_policy=object_validity_policy,
                preflight=preflight,
                source_context=source_context or {},
                execute=execute,
                approved=approved,
                timeout_sec=timeout_sec,
                output=output,
            )
        if not case_dir:
            return ModuleResult.fail("需要 case_dir（含 arbe 产出或输出目录）",
                                     module=self.name)

        from engines.arbe.replay_provider import LocalArbeReplayProvider
        resolved_warning_names = _warning_contract_from_case(case_dir, warning_names)
        provider = LocalArbeReplayProvider(
            output_dir=output_dir or str(self.output_dir or ""),
            warning_names=resolved_warning_names,
        )

        job = provider.submit(case_dir, replay_mode="trace")
        events = provider.fetch_trace(job)
        kpi = provider.fetch_kpi(job)

        # 统计各 warning 位触发帧数
        active_count: dict[str, int] = {}
        for ev in events:
            for name in ev.active_warnings():
                active_count[name] = active_count.get(name, 0) + 1
        payload: dict[str, Any] = {
            "schema_version": "arbe-replay-result.v1",
            "status": "ready" if events else "partial",
            "mode": "local",
            "trace": [ev.to_dict() for ev in events],
            "event_count": len(events),
            "active_warnings": active_count,
            "kpi": kpi,
            "warning_mapping_source": "case_runtime_schema_or_explicit" if resolved_warning_names else "not_provided_generic_wN",
            "diagnostics": [] if resolved_warning_names else ["warning_mapping_not_provided_features_remain_generic_wN"],
        }
        artifacts: list[str] = []
        if str(output or "").strip():
            path = Path(output).expanduser().resolve()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            payload["artifact_path"] = str(path)
            artifacts.append(str(path))
        return ModuleResult(
            ok=True,
            message=f"sim-verify: {len(events)} trace 事件, {len(active_count)} 个报警位触发",
            module=self.name,
            artifacts=artifacts,
            data=payload,
        )

    def _run_remote_public(
        self,
        *,
        server_host: str,
        server_user: str,
        server_port: int,
        remote_bag_path: str,
        remote_capture_base: str,
        local_capture_path: str,
        input_topics: list[str],
        output_topics: list[str],
        ros_setup: str,
        workspace_setup: str,
        ros_master_uri: str,
        start_sec: float,
        duration_sec: float,
        warning_names: list[str],
        object_association_mode: str,
        object_validity_policy: str,
        preflight: Mapping[str, Any] | None,
        source_context: Mapping[str, Any],
        execute: bool,
        approved: bool,
        timeout_sec: float,
        output: str,
    ) -> ModuleResult:
        if not server_host or not remote_bag_path or not remote_capture_base:
            return ModuleResult.fail(
                "remote_public requires server_host, remote_bag_path and remote_capture_base",
                module=self.name,
            )
        if execute and not approved:
            return ModuleResult(
                ok=True,
                message="sim-verify:approval_required",
                module=self.name,
                data={
                    "schema_version": "arbe-public-replay-session.v1",
                    "status": "approval_required",
                    "mode": "remote_public",
                    "diagnostics": ["remote public replay requires approved=true"],
                },
            )
        try:
            from engines.arbe.remote_replay import RemoteArbeReplayProvider

            provider = RemoteArbeReplayProvider(
                host=server_host,
                username=server_user,
                port=server_port,
            )
            payload = provider.capture_public(
                remote_bag_path=remote_bag_path,
                remote_capture_base=remote_capture_base,
                start_sec=start_sec,
                duration_sec=duration_sec,
                input_topics=input_topics,
                output_topics=output_topics,
                ros_setup=ros_setup,
                workspace_setup=workspace_setup,
                ros_master_uri=ros_master_uri,
                execute=bool(execute and approved),
                local_capture_path=local_capture_path,
                timeout_sec=timeout_sec,
            )
            payload["analysis_options"] = {
                "object_association_mode": object_association_mode,
                "object_validity_policy": object_validity_policy,
            }
            local_json = str(payload.get("local_capture_json", ""))
            if local_json and Path(local_json).is_file():
                from engines.arbe.public_runtime import load_capture, normalize_public_runtime

                capture = load_capture(local_json)
                payload["runtime_snapshot"] = normalize_public_runtime(
                    warning_rows=capture.get("warning_rows"),
                    radar_info_rows=capture.get("radar_info_rows"),
                    object_rows=capture.get("object_rows"),
                    source_context={
                        **dict(source_context),
                        "server": server_host,
                        "remote_bag_path": remote_bag_path,
                    },
                    warning_names=warning_names,
                    object_association_mode=object_association_mode,
                    object_validity_policy=object_validity_policy,
                    preflight=preflight,
                )
            if output and payload.get("status") not in {"blocked", "failed"}:
                path = Path(output).expanduser().resolve()
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                payload["artifact_path"] = str(path)
                artifacts = [str(path)]
            else:
                artifacts = list(payload.get("artifacts", []) or [])
        except (OSError, TypeError, ValueError, KeyError) as exc:
            return ModuleResult.fail(
                f"remote public simulation failed: {type(exc).__name__}: {exc}",
                module=self.name,
            )
        status = str(payload.get("status", "failed"))
        return ModuleResult(
            ok=status in {"planned", "approval_required", "completed", "partial"},
            message=f"sim-verify:{status}",
            module=self.name,
            artifacts=artifacts,
            data=payload,
        )

    @classmethod
    def register_cli(cls, subparsers: Any) -> Any:
        p = super().register_cli(subparsers)
        p.add_argument("--case-dir", default="", help="数据目录（含 arbe 产出）")
        p.add_argument("--mode", default="local", choices=MODES, help="运行模式")
        p.add_argument("--output-dir", default="", help="arbe 产出目录")
        p.add_argument("--host", dest="server_host", default="")
        p.add_argument("--user", dest="server_user", default="")
        p.add_argument("--port", dest="server_port", type=int, default=22)
        p.add_argument("--remote-bag-path", default="")
        p.add_argument("--remote-capture-base", default="")
        p.add_argument("--local-capture-path", default="")
        p.add_argument("--input-topic", dest="input_topics", action="append", default=[])
        p.add_argument("--output-topic", dest="output_topics", action="append", default=[])
        p.add_argument("--ros-setup", default="/opt/ros/noetic/setup.bash")
        p.add_argument("--workspace-setup", default="")
        p.add_argument("--ros-master-uri", default="http://localhost:11311")
        p.add_argument("--start-sec", type=float, default=0.0)
        p.add_argument("--duration-sec", type=float, default=4.0)
        p.add_argument("--warning-names", type=json.loads, default=[])
        p.add_argument("--object-association-mode", choices=["auto", "strict", "publication_order"], default="auto")
        p.add_argument("--object-validity-policy", choices=["preserve", "arbe_wf_sobj"], default="preserve")
        p.add_argument("--preflight", dest="preflight_path", default="")
        p.add_argument("--execute", action="store_true")
        p.add_argument("--approved", action="store_true")
        p.add_argument("--timeout-sec", type=float, default=120.0)
        p.add_argument("--output", default="")
        p.set_defaults(_module_cls=cls)
        return p

    @classmethod
    def from_cli_args(cls, args: Any) -> "SimVerifyModule":
        return cls(
            case_dir=getattr(args, "case_dir", ""),
            mode=getattr(args, "mode", "local"),
            output_dir=getattr(args, "output_dir", ""),
        )


__all__ = ["SimVerifyModule", "MODES"]
