"""Pi-facing read-only query over existing CR60 evidence artifacts."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from engines.evidence_query import EvidenceQueryError, build_evidence_query

from .base import BaseModule, ModuleResult


def _json_object(text: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"expected JSON object: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise ValueError("expected JSON object")
    return value


def _json_array(text: str) -> list[Any]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"expected JSON array: {exc.msg}") from exc
    if not isinstance(value, list):
        raise ValueError("expected JSON array")
    return value


class EvidenceQueryModule(BaseModule):
    """Return one bounded event/frame/field slice for Pi or a report."""

    name = "evidence-query"
    description = "按事件、帧、功能和字段查询已有 CR60 证据 artifact"
    tags = ["evidence", "query", "event", "frame", "target", "ego", "read-only", "atomic"]
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "bundle": {"type": "object"},
            "bundle_path": {"type": "string"},
            "viewer_model": {"type": "object"},
            "viewer_model_path": {"type": "string"},
            "runtime_evidence": {"type": "object"},
            "runtime_evidence_path": {"type": "string"},
            "event_id": {"type": "string"},
            "event_index": {"type": "integer"},
            "function": {"type": "string", "description": "功能/事件函数 token；精确匹配，也允许 token_侧别 前缀匹配"},
            "side": {"type": "string"},
            "radar_id": {"type": ["string", "integer"]},
            "frame_id": {"type": ["string", "integer"]},
            "fields": {"type": "array", "items": {"type": "string"}, "description": "真实 artifact 点号字段路径，例如 target.fields、ego.fields、frame、code.call_chain"},
            "max_events": {"type": "integer", "default": 20},
            "max_frames": {"type": "integer", "default": 24},
            "max_targets": {"type": "integer", "default": 24},
            "include_details": {"type": "boolean", "default": False},
            "max_field_rows": {"type": "integer", "default": 32},
            "output": {
                "type": "string",
                "description": "可选输出文件路径；仅在用户明确要求落盘且给出路径时传入，不要填写 json/text 等格式名",
            },
        },
        "anyOf": [
            {"required": ["bundle"]},
            {"required": ["bundle_path"]},
            {"required": ["viewer_model"]},
            {"required": ["viewer_model_path"]},
        ],
        "additionalProperties": False,
    }
    output_schema: dict[str, Any] = {
        "type": "object",
        "required": ["schema_version", "status", "query", "events", "matched_event_count"],
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
        event_id: str = "",
        event_index: int | None = None,
        function: str = "",
        side: str = "",
        radar_id: str | int = "",
        frame_id: str | int = "",
        fields: Sequence[str] | str | None = None,
        max_events: int = 20,
        max_frames: int = 24,
        max_targets: int = 24,
        include_details: bool = False,
        max_field_rows: int = 32,
        output: str = "",
        **_: Any,
    ) -> ModuleResult:
        try:
            payload = build_evidence_query(
                bundle=bundle,
                bundle_path=bundle_path,
                viewer_model=viewer_model,
                viewer_model_path=viewer_model_path,
                runtime_evidence=runtime_evidence,
                runtime_evidence_path=runtime_evidence_path,
                event_id=event_id,
                event_index=event_index,
                function=function,
                side=side,
                radar_id=radar_id,
                frame_id=frame_id,
                fields=fields,
                max_events=max_events,
                max_frames=max_frames,
                max_targets=max_targets,
                include_details=include_details,
                max_field_rows=max_field_rows,
            )
        except (EvidenceQueryError, OSError, TypeError, ValueError) as exc:
            return ModuleResult.fail(
                f"evidence-query:failed: {exc}",
                module=self.name,
                error_type=type(exc).__name__,
            )

        artifacts: list[str] = []
        # Some providers treat an optional path field as an output format and
        # send ``output=\"json\"``.  Do not create a misleading file in the
        # project root; a real output path must be explicitly path-like.
        output_text = str(output or "").strip()
        if output_text.lower() in {"json", "jsonl", "text", "markdown", "md"}:
            output_text = ""
        if output_text:
            path = Path(output_text).expanduser().resolve()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            payload["artifact_path"] = str(path)
            artifacts.append(str(path))

        status = str(payload.get("status", "blocked"))
        return ModuleResult(
            ok=status in {"ready", "not_found"},
            message=f"evidence-query:{status}",
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
        parser.add_argument("--event-id", default="")
        parser.add_argument("--event-index", type=int, default=None)
        parser.add_argument("--function", default="")
        parser.add_argument("--side", default="")
        parser.add_argument("--radar-id", default="")
        parser.add_argument("--frame-id", default="")
        parser.add_argument("--fields", type=_json_array, default=[])
        parser.add_argument("--max-events", type=int, default=20)
        parser.add_argument("--max-frames", type=int, default=24)
        parser.add_argument("--max-targets", type=int, default=24)
        parser.add_argument("--include-details", action="store_true")
        parser.add_argument("--max-field-rows", type=int, default=32)
        parser.add_argument("--output", default="")
        return parser

    @classmethod
    def from_cli_args(cls, args: Any) -> "EvidenceQueryModule":
        return cls()


__all__ = ["EvidenceQueryModule"]
