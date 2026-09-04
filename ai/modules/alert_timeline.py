"""Pi-visible atomic projection of cross-layer alarm timelines."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from engines.alert_timeline import AlertTimelineError, build_alert_timeline

from .base import BaseModule, ModuleResult


class AlertTimelineModule(BaseModule):
    """Build a generic raw/replay/runtime/GDB/CAN alarm timeline."""

    name = "alert-timeline"
    description = "将原始、回放、运行态、GDB 和 CAN 证据投影为可比较报警时间线"
    tags = ["timeline", "alarm", "evidence", "comparison", "atomic"]
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "bundle": {"type": "object"},
            "bundle_path": {"type": "string"},
            "viewer_model": {"type": "object"},
            "viewer_model_path": {"type": "string"},
            "runtime_evidence": {"type": "object"},
            "runtime_evidence_path": {"type": "string"},
            "selected_event": {"type": "object"},
            "event_id": {"type": "string"},
            "function": {"type": "string"},
            "side": {"type": "string"},
            "radar_id": {"type": ["string", "integer"]},
            "frame_id": {"type": ["string", "integer"]},
            "max_rows": {"type": "integer", "default": 240},
            "output": {"type": "string"},
        },
        "anyOf": [
            {"required": ["bundle"]},
            {"required": ["bundle_path"]},
            {"required": ["viewer_model"]},
            {"required": ["viewer_model_path"]},
            {"required": ["selected_event"]},
        ],
        "additionalProperties": False,
    }
    output_schema: dict[str, Any] = {
        "type": "object",
        "required": ["schema_version", "status", "sources", "rows", "playback_frame_map", "comparisons"],
    }

    def run(
        self,
        *,
        bundle: Mapping[str, Any] | None = None,
        bundle_path: str = "",
        viewer_model: Mapping[str, Any] | None = None,
        viewer_model_path: str = "",
        runtime_evidence: Mapping[str, Any] | None = None,
        runtime_evidence_path: str = "",
        selected_event: Mapping[str, Any] | None = None,
        event_id: str = "",
        function: str = "",
        side: str = "",
        radar_id: str | int = "",
        frame_id: str | int = "",
        max_rows: int = 240,
        output: str = "",
        **_: Any,
    ) -> ModuleResult:
        try:
            payload = build_alert_timeline(
                bundle=bundle,
                bundle_path=bundle_path,
                viewer_model=viewer_model,
                viewer_model_path=viewer_model_path,
                runtime_evidence=runtime_evidence,
                runtime_evidence_path=runtime_evidence_path,
                selected_event=selected_event,
                event_id=event_id,
                function=function,
                side=side,
                radar_id=radar_id,
                frame_id=frame_id,
                max_rows=max_rows,
            )
        except (OSError, TypeError, ValueError, KeyError, AlertTimelineError) as exc:
            return ModuleResult.fail(
                f"alert-timeline:failed: {exc}",
                module=self.name,
                error_type=type(exc).__name__,
            )

        artifacts: list[str] = []
        if str(output or "").strip():
            path = Path(output).expanduser().resolve()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
            artifacts.append(str(path))
            payload = {**payload, "artifact_path": str(path)}
        status = str(payload.get("status", "partial"))
        return ModuleResult(
            ok=status != "blocked",
            message=f"alert-timeline:{status}",
            module=self.name,
            artifacts=artifacts,
            data=payload,
        )

    @classmethod
    def register_cli(cls, subparsers: Any) -> Any:
        parser = super().register_cli(subparsers)
        parser.add_argument("--bundle", dest="bundle_path", default="")
        parser.add_argument("--viewer-model", dest="viewer_model_path", default="")
        parser.add_argument("--runtime-evidence", dest="runtime_evidence_path", default="")
        parser.add_argument("--selected-event", type=json.loads, default=None)
        parser.add_argument("--event-id", default="")
        parser.add_argument("--function", default="")
        parser.add_argument("--side", default="")
        parser.add_argument("--radar-id", default="")
        parser.add_argument("--frame-id", default="")
        parser.add_argument("--max-rows", type=int, default=240)
        parser.add_argument("--output", default="")
        return parser


__all__ = ["AlertTimelineModule"]
