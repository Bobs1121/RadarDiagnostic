# -*- coding: utf-8 -*-
"""Pi-visible ProjectCapabilityManifest builder."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from engines.project_capability import (
    ProjectCapabilityError,
    build_project_capability_manifest,
)

from .base import BaseModule, ModuleResult


def _json_object(text: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"expected JSON object: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise ValueError("expected JSON object")
    return value


class ProjectCapabilityManifestModule(BaseModule):
    """Build a current project capability declaration for Pi routing."""

    name = "project-capability-manifest"
    description = "生成当前项目/源码/数据的能力清单与缺口声明"
    tags = ["project", "capability", "manifest", "provenance", "atomic"]
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "identity": {"type": "object"},
            "project_id": {"type": "string"},
            "variant_id": {"type": "string"},
            "intake": {"type": "object"},
            "intake_path": {"type": "string"},
            "preflight": {"type": "object"},
            "preflight_path": {"type": "string"},
            "code_context": {"type": "object"},
            "code_context_path": {"type": "string"},
            "runtime_snapshot": {"type": "object"},
            "runtime_snapshot_path": {"type": "string"},
            "diagnosis_bundle": {"type": "object"},
            "diagnosis_bundle_path": {"type": "string"},
            "declared_capabilities": {"type": "object"},
            "output": {"type": "string"},
        },
        "additionalProperties": False,
    }
    output_schema: dict[str, Any] = {
        "type": "object",
        "required": [
            "schema_version",
            "status",
            "identity",
            "data_capabilities",
            "feature_capabilities",
            "code_capabilities",
            "replay_capabilities",
            "runtime_capabilities",
            "presentation_capabilities",
            "freshness",
            "unsupported",
            "conflicts",
        ],
    }

    def run(
        self,
        *,
        identity: Mapping[str, Any] | None = None,
        project_id: str = "",
        variant_id: str = "",
        intake: Mapping[str, Any] | None = None,
        intake_path: str = "",
        preflight: Mapping[str, Any] | None = None,
        preflight_path: str = "",
        code_context: Mapping[str, Any] | None = None,
        code_context_path: str = "",
        runtime_snapshot: Mapping[str, Any] | None = None,
        runtime_snapshot_path: str = "",
        diagnosis_bundle: Mapping[str, Any] | None = None,
        diagnosis_bundle_path: str = "",
        declared_capabilities: Mapping[str, Any] | None = None,
        output: str = "",
        **_: Any,
    ) -> ModuleResult:
        try:
            payload = build_project_capability_manifest(
                identity=identity,
                project_id=project_id,
                variant_id=variant_id,
                intake=intake,
                intake_path=intake_path,
                preflight=preflight,
                preflight_path=preflight_path,
                code_context=code_context,
                code_context_path=code_context_path,
                runtime_snapshot=runtime_snapshot,
                runtime_snapshot_path=runtime_snapshot_path,
                diagnosis_bundle=diagnosis_bundle,
                diagnosis_bundle_path=diagnosis_bundle_path,
                declared_capabilities=declared_capabilities,
            )
        except (ProjectCapabilityError, OSError, TypeError, ValueError) as exc:
            return ModuleResult.fail(
                f"project-capability-manifest:failed: {exc}",
                module=self.name,
                error_type=type(exc).__name__,
            )
        artifacts: list[str] = []
        if output:
            path = Path(output).expanduser().resolve()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            payload["artifact_path"] = str(path)
            artifacts.append(str(path))
        return ModuleResult(
            ok=payload["status"] != "blocked",
            message=f"project-capability-manifest:{payload['status']}",
            module=self.name,
            data=payload,
            artifacts=artifacts,
        )

    @classmethod
    def register_cli(cls, subparsers: Any) -> Any:
        parser = super().register_cli(subparsers)
        parser.add_argument("--identity", type=_json_object, default={})
        parser.add_argument("--project-id", default="")
        parser.add_argument("--variant-id", default="")
        parser.add_argument("--intake", dest="intake_path", default="")
        parser.add_argument("--preflight", dest="preflight_path", default="")
        parser.add_argument("--code-context", dest="code_context_path", default="")
        parser.add_argument("--runtime-snapshot", dest="runtime_snapshot_path", default="")
        parser.add_argument("--diagnosis-bundle", dest="diagnosis_bundle_path", default="")
        parser.add_argument("--declared-capabilities", type=_json_object, default={})
        parser.add_argument("--output", default="")
        return parser

    @classmethod
    def from_cli_args(cls, args: Any) -> "ProjectCapabilityManifestModule":
        return cls()


__all__ = ["ProjectCapabilityManifestModule"]
