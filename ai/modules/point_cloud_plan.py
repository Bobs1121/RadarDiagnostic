"""Plan-only point-cloud perception replay capability."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from engines.point_cloud_replay import (
    audit_perception_capture,
    build_perception_input_contract,
    build_point_cloud_replay_plan,
    load_perception_artifact,
)

from .base import BaseModule, ModuleResult


class PointCloudPlanModule(BaseModule):
    """Build a point-cloud plan; never starts ROS or changes a workspace."""

    name = "point-cloud-plan"
    description = "生成点云前级感知回放计划并校验 HILMODEL/身份/预热门"
    tags = ["point-cloud", "perception", "plan", "arbe", "read-only", "atomic"]
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "server_host": {"type": "string"},
            "server_user": {"type": "string"},
            "server_port": {"type": "integer", "default": 22},
            "remote_bag_path": {"type": "string"},
            "point_cloud_topic": {"type": "string"},
            "output_topics": {"type": "array", "items": {"type": "string"}},
            "remote_capture_base": {"type": "string"},
            "input_topics": {"type": "array", "items": {"type": "string"}},
            "ros_setup": {"type": "string"},
            "workspace_setup": {"type": "string"},
            "ros_master_uri": {"type": "string"},
            "start_sec": {"type": "number"},
            "duration_sec": {"type": "number"},
            "frame_period_sec": {"type": "number", "default": 0.066},
            "warmup_frames": {"type": "integer", "default": 175},
            "preflight": {"type": "object"},
            "preflight_path": {"type": "string"},
            "source_context": {"type": "object"},
            "source_context_path": {"type": "string"},
            "layout_profile": {"type": "object"},
            "input_contract": {"type": "object"},
            "input_contract_path": {"type": "string"},
            "input_capture": {"type": "object"},
            "input_capture_path": {"type": "string"},
            "topic_inventory": {"type": "object"},
            "topic_inventory_path": {"type": "string"},
            "stage_map": {"type": "object"},
            "source_root": {"type": "string"},
            "source_files": {"type": "array", "items": {"type": "string"}},
            "run_id": {"type": "string"},
            "output": {"type": "string"},
        },
        "additionalProperties": False,
    }
    output_schema: dict[str, Any] = {"type": "object", "required": ["schema_version", "status", "gates", "diagnostics"]}

    def run(
        self,
        *,
        server_host: str = "",
        server_user: str = "",
        server_port: int = 22,
        remote_bag_path: str = "",
        point_cloud_topic: str = "",
        output_topics: Sequence[str] | None = None,
        remote_capture_base: str = "",
        input_topics: Sequence[str] | None = None,
        ros_setup: str = "/opt/ros/noetic/setup.bash",
        workspace_setup: str = "",
        ros_master_uri: str = "http://localhost:11311",
        start_sec: float = 0.0,
        duration_sec: float = 4.0,
        frame_period_sec: float = 0.066,
        warmup_frames: int = 175,
        preflight: Mapping[str, Any] | None = None,
        preflight_path: str = "",
        source_context: Mapping[str, Any] | None = None,
        source_context_path: str = "",
        layout_profile: Mapping[str, Any] | None = None,
        input_contract: Mapping[str, Any] | None = None,
        input_contract_path: str = "",
        input_capture: Mapping[str, Any] | None = None,
        input_capture_path: str = "",
        topic_inventory: Mapping[str, Any] | None = None,
        topic_inventory_path: str = "",
        stage_map: Mapping[str, Any] | None = None,
        source_root: str = "",
        source_files: Sequence[str] | None = None,
        run_id: str = "",
        output: str = "",
        **_: Any,
    ) -> ModuleResult:
        def load(value: Mapping[str, Any] | None, path: str) -> dict[str, Any]:
            if isinstance(value, Mapping):
                return dict(value)
            if not path:
                return {}
            try:
                item = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                return {}
            return dict(item) if isinstance(item, Mapping) else {}

        effective_capture: dict[str, Any] = dict(input_capture) if isinstance(input_capture, Mapping) else {}
        artifact_audit: dict[str, Any] = {}
        if not effective_capture and input_capture_path:
            loaded = load_perception_artifact(input_capture_path)
            artifact_audit = loaded.pop("_artifact_audit", {}) if isinstance(loaded, Mapping) else {}
            effective_capture = dict(loaded) if isinstance(loaded, Mapping) else {}
        effective_source_context = load(source_context, source_context_path)
        if isinstance(layout_profile, Mapping):
            effective_source_context.setdefault("layout_profile", dict(layout_profile))
        if not effective_source_context and isinstance(effective_capture.get("source_context"), Mapping):
            effective_source_context = dict(effective_capture.get("source_context") or {})
        effective_contract = load(input_contract, input_contract_path)
        effective_inventory = load(topic_inventory, topic_inventory_path)
        inventory_rows = effective_inventory.get("topics") if isinstance(effective_inventory.get("topics"), list) else []
        if isinstance(inventory_rows, list):
            usable = [row for row in inventory_rows if isinstance(row, Mapping) and str(row.get("status", "ready")) not in {"failed", "not_found"}]
            if not point_cloud_topic:
                input_candidate = next((row for row in usable if "lgu_data" in str(row.get("topic", "")) or "PointCloud" in str(row.get("type", ""))), None)
                if input_candidate:
                    point_cloud_topic = str(input_candidate.get("topic", ""))
            if not output_topics:
                output_topics = [
                    str(row.get("topic")) for row in usable
                    if str(row.get("topic", "")) and (
                        "PointCloud2" in str(row.get("type", ""))
                        or "MarkerArray" in str(row.get("type", ""))
                        or "wfObjectMsg" in str(row.get("type", ""))
                    )
                ]
        if not effective_contract and effective_capture:
            input_audit = audit_perception_capture(effective_capture)
            capture_schema = dict(effective_capture.get("message_schema") or {}) if isinstance(effective_capture.get("message_schema"), Mapping) else {}
            bound_layout = effective_source_context.get("layout_profile")
            if isinstance(bound_layout, Mapping):
                capture_schema["layout_profile"] = dict(bound_layout)
            effective_contract = build_perception_input_contract(
                effective_capture.get("point_rows") or effective_capture.get("points") or effective_capture.get("dot_rows"),
                source_context=effective_source_context,
                message_schema=capture_schema,
                target_rows=effective_capture.get("target_rows") or effective_capture.get("object_rows"),
                target_usage=effective_capture.get("target_usage"),
                conversion=effective_capture.get("conversion"),
                payload_audit=input_audit,
                artifact_audit=artifact_audit,
            )
        if not point_cloud_topic and effective_capture.get("topic"):
            point_cloud_topic = str(effective_capture.get("topic"))
        plan = build_point_cloud_replay_plan(
            server_host=server_host,
            server_user=server_user,
            server_port=server_port,
            remote_bag_path=remote_bag_path,
            point_cloud_topic=point_cloud_topic,
            output_topics=output_topics,
            remote_capture_base=remote_capture_base,
            input_topics=input_topics,
            ros_setup=ros_setup,
            workspace_setup=workspace_setup,
            ros_master_uri=ros_master_uri,
            start_sec=start_sec,
            duration_sec=duration_sec,
            frame_period_sec=frame_period_sec,
            warmup_frames=warmup_frames,
            preflight=load(preflight, preflight_path),
            source_context=effective_source_context,
            input_contract=effective_contract,
            topic_inventory=effective_inventory,
            stage_map=stage_map,
            source_root=source_root,
            source_files=source_files,
            run_id=run_id,
        )
        artifacts: list[str] = []
        if str(output or "").strip():
            path = Path(output).expanduser().resolve()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            plan["artifact_path"] = str(path)
            artifacts.append(str(path))
        return ModuleResult(
            ok=True,
            message=f"point-cloud-plan:{plan['status']}",
            module=self.name,
            artifacts=artifacts,
            data=plan,
        )

    @classmethod
    def register_cli(cls, subparsers: Any) -> Any:
        parser = super().register_cli(subparsers)
        parser.add_argument("--remote-bag-path", default="")
        parser.add_argument("--server-host", default="")
        parser.add_argument("--server-user", default="")
        parser.add_argument("--server-port", type=int, default=22)
        parser.add_argument("--point-cloud-topic", default="")
        parser.add_argument("--output-topic", dest="output_topics", action="append", default=[])
        parser.add_argument("--remote-capture-base", default="")
        parser.add_argument("--input-topic", dest="input_topics", action="append", default=[])
        parser.add_argument("--ros-setup", default="/opt/ros/noetic/setup.bash")
        parser.add_argument("--workspace-setup", default="")
        parser.add_argument("--ros-master-uri", default="http://localhost:11311")
        parser.add_argument("--start-sec", type=float, default=0.0)
        parser.add_argument("--duration-sec", type=float, default=4.0)
        parser.add_argument("--frame-period-sec", type=float, default=0.066)
        parser.add_argument("--warmup-frames", type=int, default=175)
        parser.add_argument("--preflight-path", default="")
        parser.add_argument("--source-context-path", default="")
        parser.add_argument("--input-contract-path", default="")
        parser.add_argument("--input-capture-path", default="")
        parser.add_argument("--topic-inventory-path", default="")
        parser.add_argument("--source-root", default="")
        parser.add_argument("--source-file", dest="source_files", action="append", default=[])
        parser.add_argument("--run-id", default="")
        parser.add_argument("--output", default="")
        return parser

    @classmethod
    def from_cli_args(cls, args: Any) -> "PointCloudPlanModule":
        return cls()


__all__ = ["PointCloudPlanModule"]
