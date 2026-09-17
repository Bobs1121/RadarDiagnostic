"""Read-only validation of an existing perception-report artifact."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from engines.point_cloud_replay import build_perception_validation

from .base import BaseModule, ModuleResult


def _load(value: Mapping[str, Any] | None, path: str) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if not path:
        return {}
    try:
        payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


class PointCloudValidateModule(BaseModule):
    """Validate report invariants without changing the report or running ROS."""

    name = "point-cloud-validate"
    description = "校验已有 perception-report 的 schema、计数和 runtime 完整性"
    tags = ["point-cloud", "perception", "validate", "read-only", "atomic"]
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "report": {"type": "object"},
            "report_path": {"type": "string"},
            "output": {"type": "string"},
        },
        "anyOf": [{"required": ["report"]}, {"required": ["report_path"]}],
        "additionalProperties": False,
    }
    output_schema: dict[str, Any] = {
        "type": "object",
        "required": ["schema_version", "status", "errors", "warnings", "checks"],
    }

    def run(
        self,
        *,
        report: Mapping[str, Any] | None = None,
        report_path: str = "",
        output: str = "",
        **_: Any,
    ) -> ModuleResult:
        payload = _load(report, report_path)
        if not payload:
            return ModuleResult(
                ok=True,
                message="point-cloud-validate:blocked",
                module=self.name,
                data={
                    "schema_version": "perception-validation.v1",
                    "status": "invalid",
                    "errors": ["report_missing_or_invalid_json"],
                    "warnings": [],
                    "checks": {},
                    "conclusion_level": "validation_only",
                },
            )
        analysis = payload.get("analysis") if isinstance(payload.get("analysis"), Mapping) else payload
        validation = build_perception_validation(report=payload, analysis=analysis)
        artifacts: list[str] = []
        if str(output or "").strip():
            path = Path(output).expanduser().resolve()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(validation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            validation["artifact_path"] = str(path)
            artifacts.append(str(path))
        return ModuleResult(
            ok=True,
            message=f"point-cloud-validate:{validation['status']}",
            module=self.name,
            artifacts=artifacts,
            data=validation,
        )

    @classmethod
    def register_cli(cls, subparsers: Any) -> Any:
        parser = super().register_cli(subparsers)
        parser.add_argument("--report-path", default="")
        parser.add_argument("--output", default="")
        return parser

    @classmethod
    def from_cli_args(cls, args: Any) -> "PointCloudValidateModule":
        return cls()


__all__ = ["PointCloudValidateModule"]
