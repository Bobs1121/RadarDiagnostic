# -*- coding: utf-8 -*-
"""SimVerifyModule (V4 P4) — 仿真验证（arbe-replay）。

本地模式解析已产出的 warning trace / KPI；远程模式通过 SSH 复用当前 ROS/arbe
会话采集公共输出，再交给 public-runtime-normalize 归一化，供 Pi 调度验证。

独立运行::

    python cli.py sim-verify --case-dir cases/xxx --mode local
"""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Mapping, Sequence

from .base import BaseModule, ModuleResult

log = logging.getLogger(__name__)

MODES = ("local", "remote_public")
STRATEGIES = ("sgu_injection", "point_cloud")


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
            "strategy": {"type": "string", "enum": list(STRATEGIES)},
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
            "source_context_path": {"type": "string"},
            "execution_binding": {"type": "object"},
            "execution_binding_path": {"type": "string"},
            "point_cloud_plan": {"type": "object"},
            "point_cloud_plan_path": {"type": "string"},
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
        strategy: str = "sgu_injection",
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
        source_context_path: str = "",
        execution_binding: Mapping[str, Any] | None = None,
        execution_binding_path: str = "",
        point_cloud_plan: Mapping[str, Any] | None = None,
        point_cloud_plan_path: str = "",
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
        if execution_binding is None and execution_binding_path:
            try:
                value = json.loads(
                    Path(execution_binding_path).expanduser().read_text(encoding="utf-8")
                )
                execution_binding = value if isinstance(value, Mapping) else None
            except (OSError, UnicodeError, json.JSONDecodeError):
                execution_binding = None
        if source_context is None and source_context_path:
            try:
                value = json.loads(
                    Path(source_context_path).expanduser().read_text(encoding="utf-8")
                )
                source_context = value if isinstance(value, Mapping) else None
            except (OSError, UnicodeError, json.JSONDecodeError):
                source_context = None
        if point_cloud_plan is None and point_cloud_plan_path:
            try:
                value = json.loads(Path(point_cloud_plan_path).expanduser().read_text(encoding="utf-8"))
                point_cloud_plan = value if isinstance(value, Mapping) else None
            except (OSError, UnicodeError, json.JSONDecodeError):
                point_cloud_plan = None
        if strategy not in STRATEGIES:
            return ModuleResult.fail(f"不支持的 strategy '{strategy}'，可用: {STRATEGIES}", module=self.name)
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
                execution_binding=execution_binding,
                execute=execute,
                approved=approved,
                timeout_sec=timeout_sec,
                output=output,
                strategy=strategy,
                point_cloud_plan=point_cloud_plan,
            )
        if strategy == "point_cloud":
            return ModuleResult(
                ok=True,
                message="sim-verify:point_cloud_local_provider_unavailable",
                module=self.name,
                data={
                    "schema_version": "arbe-replay-result.v1",
                    "status": "blocked",
                    "mode": "local",
                    "strategy": strategy,
                    "diagnostics": ["point_cloud_requires_stage_bound_runtime_provider"],
                },
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
        execution_binding: Mapping[str, Any] | None,
        execute: bool,
        approved: bool,
        timeout_sec: float,
        output: str,
        strategy: str,
        point_cloud_plan: Mapping[str, Any] | None,
    ) -> ModuleResult:
        if not server_host or not remote_bag_path or not remote_capture_base:
            return ModuleResult.fail(
                "remote_public requires server_host, remote_bag_path and remote_capture_base",
                module=self.name,
            )
        if strategy == "point_cloud":
            plan = point_cloud_plan if isinstance(point_cloud_plan, Mapping) else {}
            plan_status = str(plan.get("status", "blocked"))
            if plan.get("mode") != "point_cloud" or plan_status != "ready":
                diagnostics = ["point_cloud_plan_required_and_must_be_ready"]
                diagnostics.extend(str(item) for item in (plan.get("diagnostics", []) or []))
                return ModuleResult(
                    ok=True,
                    message="sim-verify:point_cloud_plan_blocked",
                    module=self.name,
                    data={
                        "schema_version": "arbe-public-replay-session.v1",
                        "status": "blocked",
                        "mode": "remote_public",
                        "strategy": strategy,
                        "diagnostics": list(dict.fromkeys(diagnostics)),
                        "point_cloud_plan": dict(plan),
                    },
                )
            from engines.point_cloud_replay import audit_runtime_workspace_alignment
            runtime_binding = audit_runtime_workspace_alignment(preflight)
            if runtime_binding.get("status") == "conflict" or (
                runtime_binding.get("workspace_root")
                and runtime_binding.get("status") != "aligned"
            ):
                return ModuleResult(
                    ok=True,
                    message="sim-verify:point_cloud_runtime_workspace_blocked",
                    module=self.name,
                    data={
                        "schema_version": "arbe-public-replay-session.v1",
                        "status": "blocked",
                        "mode": "remote_public",
                        "strategy": strategy,
                        "runtime_binding": runtime_binding,
                        "diagnostics": list(runtime_binding.get("diagnostics", []) or []),
                    },
                )
            plan_target = plan.get("target") if isinstance(plan.get("target"), Mapping) else {}
            mismatches = []
            plan_server = plan_target.get("server") if isinstance(plan_target.get("server"), Mapping) else {}
            for key, actual in (("host", server_host), ("user", server_user), ("port", server_port)):
                if key in plan_server and str(plan_server.get(key)) != str(actual):
                    mismatches.append(f"point_cloud_plan_target_mismatch:server_{key}")
            for key, actual in (("remote_bag_path", remote_bag_path), ("remote_capture_base", remote_capture_base), ("start_sec", start_sec), ("duration_sec", duration_sec)):
                if key in plan_target and str(plan_target.get(key)) != str(actual):
                    mismatches.append(f"point_cloud_plan_target_mismatch:{key}")
            plan_topics = plan_target.get("output_topics") if isinstance(plan_target.get("output_topics"), list) else None
            if plan_topics is not None and [str(item) for item in output_topics] != [str(item) for item in plan_topics]:
                mismatches.append("point_cloud_plan_target_mismatch:output_topics")
            if mismatches:
                return ModuleResult(
                    ok=True,
                    message="sim-verify:point_cloud_plan_mismatch",
                    module=self.name,
                    data={
                        "schema_version": "arbe-public-replay-session.v1",
                        "status": "blocked",
                        "mode": "remote_public",
                        "strategy": strategy,
                        "diagnostics": mismatches,
                    },
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
        execution_plan = {
            "server": {"host": server_host, "user": server_user, "port": int(server_port)},
            "remote_bag_path": remote_bag_path,
            "remote_capture_base": remote_capture_base,
            "start_sec": start_sec,
            "duration_sec": duration_sec,
            "input_topics": list(input_topics),
            "output_topics": list(output_topics),
            "ros_setup": ros_setup,
            "workspace_setup": workspace_setup,
            "ros_master_uri": ros_master_uri,
        }
        if strategy == "point_cloud":
            execution_plan["strategy"] = strategy
            plan_execution = point_cloud_plan.get("execution_plan") if isinstance(point_cloud_plan, Mapping) and isinstance(point_cloud_plan.get("execution_plan"), Mapping) else {}
            for key in ("frame_period_sec", "warmup_duration_sec", "warmup_frames"):
                if key in plan_execution:
                    execution_plan[key] = plan_execution[key]
        binding_check = None
        if execute:
            from engines.arbe.execution_binding import (
                derive_execution_identity,
                verify_execution_binding,
            )

            current_identity, identity_provenance = derive_execution_identity(
                preflight=preflight,
                source_context=source_context,
            )
            identity_conflicts = str(identity_provenance.get("__conflicts__") or "").strip()
            if identity_conflicts:
                return ModuleResult(
                    ok=True,
                    message="sim-verify:identity_conflict",
                    module=self.name,
                    data={
                        "schema_version": "arbe-public-replay-session.v1",
                        "status": "blocked",
                        "mode": "remote_public",
                        "strategy": strategy,
                        "identity_provenance": identity_provenance,
                        "diagnostics": identity_conflicts.split(";"),
                    },
                )
            binding_check = verify_execution_binding(
                execution_binding,
                current_identity=current_identity,
                approved=approved,
                plan=execution_plan,
            )
            if binding_check["status"] != "verified":
                return ModuleResult(
                    ok=True,
                    message="sim-verify:execution_binding_blocked",
                    module=self.name,
                    data={
                        "schema_version": "arbe-public-replay-session.v1",
                        "status": "blocked",
                        "mode": "remote_public",
                        "strategy": strategy,
                        "execution_binding": binding_check,
                        "identity_provenance": identity_provenance,
                        "diagnostics": list(binding_check.get("reasons", [])),
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
                attempt_id=str((execution_binding or {}).get("run_id") or ""),
                execute=bool(execute and approved),
                local_capture_path=local_capture_path,
                timeout_sec=timeout_sec,
            )
            payload["strategy"] = strategy
            if strategy == "point_cloud":
                payload["point_cloud_plan_hash"] = str((point_cloud_plan or {}).get("plan_hash") or "")
            if binding_check is not None:
                payload["execution_binding"] = binding_check
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
                if strategy == "point_cloud":
                    from engines.point_cloud_replay import (
                        audit_perception_capture,
                        build_perception_run_evidence,
                        build_stage_coverage,
                    )

                    capture_audit = audit_perception_capture(capture)
                    stage_evidence = capture.get("stage_evidence") if isinstance(capture.get("stage_evidence"), list) else []
                    completion = capture.get("completion") if isinstance(capture.get("completion"), Mapping) else {}
                    observed_frames = [
                        row.get("frame_id") for row in stage_evidence
                        if isinstance(row, Mapping) and row.get("frame_id") not in (None, "")
                    ]
                    run_evidence = build_perception_run_evidence(
                        run_id=str((execution_binding or {}).get("run_id") or payload.get("target", {}).get("attempt_id") or ""),
                        attempt_id=str((execution_binding or {}).get("run_id") or payload.get("target", {}).get("attempt_id") or ""),
                        plan_hash=str((point_cloud_plan or {}).get("plan_hash") or ""),
                        terminal_status="completed" if str(payload.get("status")) == "completed" else str(payload.get("status", "partial")),
                        warmup_requested=int((point_cloud_plan or {}).get("strategy", {}).get("warmup_frames_requested", 175) or 175) if isinstance((point_cloud_plan or {}).get("strategy"), Mapping) else 175,
                        warmup_completed=None,
                        observed_frames=observed_frames,
                        completed_frames=observed_frames if str(completion.get("status")) == "completed" else [],
                        stage_evidence=stage_evidence,
                        reset_events=[],
                        identity=(point_cloud_plan or {}).get("identity", {}) if isinstance((point_cloud_plan or {}).get("identity"), Mapping) else {},
                        diagnostics=list(capture.get("diagnostics", []) or []),
                        failure_reason="" if str(payload.get("status")) == "completed" else "capture_stage_completion_missing",
                    )
                    encoded_run = json.dumps(run_evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
                    run_digest = hashlib.sha256(encoded_run.encode("utf-8")).hexdigest()[:12]
                    run_evidence_path = str(
                        Path(local_json).with_name(f"{Path(local_json).stem}.perception-run-{run_digest}.json")
                    )
                    run_evidence_file = Path(run_evidence_path)
                    if not run_evidence_file.exists():
                        run_evidence_file.write_text(encoded_run + "\n", encoding="utf-8")
                    if run_evidence_path not in list(payload.get("artifacts", []) or []):
                        payload.setdefault("artifacts", []).append(run_evidence_path)
                    payload["perception_capture"] = {
                        "input_audit": capture_audit,
                        "stage_coverage": build_stage_coverage(stage_evidence),
                        "run_evidence": run_evidence,
                        "run_evidence_path": run_evidence_path,
                        "point_count": len(capture.get("point_rows", []) or []),
                        "cluster_count": len(capture.get("cluster_rows", []) or []),
                        "track_count": len(capture.get("track_rows", []) or []),
                        "output_count": len(capture.get("output_rows", []) or []),
                        "stage_counts": {
                            str(stage): sum(1 for row in stage_evidence if isinstance(row, Mapping) and str(row.get("stage")) == str(stage))
                            for stage in sorted({str(row.get("stage")) for row in stage_evidence if isinstance(row, Mapping)})
                        },
                        "limitations": [
                            "remote capture evidence is public topic output; it does not prove private stage variables",
                            "reset and warm-up completion require a producer-owned acknowledgement",
                        ],
                    }
                    if str(run_evidence.get("status")) != "completed":
                        payload["status"] = "partial"
                        payload.setdefault("diagnostics", []).append("perception_run_lifecycle_incomplete")
                    if strategy == "point_cloud":
                        handoff_source_context = dict(source_context)
                        binding_identity = execution_binding.get("identity") if isinstance(execution_binding, Mapping) else {}
                        binding_identity = dict(binding_identity) if isinstance(binding_identity, Mapping) else {}
                        handoff_identity_conflicts = [
                            str(item) for item in handoff_source_context.get("identity_conflicts", []) or [] if str(item).strip()
                        ]
                        for field in ("data_fingerprint", "source_context_id", "binary_fingerprint", "config_fingerprint", "session_id"):
                            bound_value = str(binding_identity.get(field) or "").strip()
                            context_value = str(handoff_source_context.get(field) or "").strip()
                            if bound_value and context_value and bound_value != context_value:
                                handoff_identity_conflicts.append(field)
                            elif bound_value and not context_value:
                                handoff_source_context[field] = bound_value
                        handoff_identity_conflicts = list(dict.fromkeys(handoff_identity_conflicts))
                        handoff_source_context["identity_conflicts"] = handoff_identity_conflicts
                        handoff_source_context["source_context_binding_status"] = (
                            "conflict" if handoff_identity_conflicts else "verified" if binding_check and binding_check.get("status") == "verified" else "not_available"
                        )
                        handoff_binding = dict(binding_check or {})
                        handoff_binding["point_cloud_plan_hash"] = str((point_cloud_plan or {}).get("plan_hash") or "")
                        if isinstance(execution_binding, Mapping):
                            handoff_binding["approved_binding_hash"] = str(execution_binding.get("binding_hash") or "")
                        payload["analysis_handoff"] = {
                            "status": "ready",
                            "recommended_tool": "point-cloud-analyze",
                            "capture_path": local_json,
                            "source_context": handoff_source_context,
                            "replay_plan_hash": str((point_cloud_plan or {}).get("plan_hash") or ""),
                            "execution_binding_run_id": str((execution_binding or {}).get("run_id") or ""),
                            "analysis_inputs": {
                                "capture_path": local_json,
                                "source_context": handoff_source_context,
                                "replay_plan": dict(point_cloud_plan) if isinstance(point_cloud_plan, Mapping) else {},
                                "execution_binding": handoff_binding,
                                "run_evidence_path": run_evidence_path,
                            },
                            "provenance": {
                                "capture": "remote_public_replay.local_capture_json",
                                "plan": "point_cloud_plan.plan_hash",
                                "binding": "execution_binding.run_id",
                            },
                            "limitations": [
                                "the handoff is an analysis input, not a root-cause conclusion",
                                "private stage trace and reset/warm-up ACK remain separate evidence gates",
                            ],
                        }
            elif strategy == "point_cloud":
                payload["analysis_handoff"] = {
                    "status": "not_available",
                    "recommended_tool": "point-cloud-analyze",
                    "capture_path": local_json,
                    "diagnostics": ["local_capture_json_missing_after_replay"],
                }
            if strategy == "point_cloud" and bool(execute) and str(payload.get("status")) == "completed":
                completion = payload.get("completion") if isinstance(payload.get("completion"), Mapping) else {}
                if str(completion.get("status")) != "completed" or not int(completion.get("stage_count", 0) or 0):
                    payload["status"] = "partial"
                    payload.setdefault("diagnostics", []).append("point_cloud_completion_ack_missing")
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
        p.add_argument("--strategy", default="sgu_injection", choices=STRATEGIES, help="回放路径")
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
        p.add_argument("--execution-binding", dest="execution_binding_path", default="")
        p.add_argument("--point-cloud-plan", dest="point_cloud_plan_path", default="")
        p.add_argument("--source-context-path", dest="source_context_path", default="")
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
