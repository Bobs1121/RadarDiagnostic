# -*- coding: utf-8 -*-
"""Atomic audit of non-GDB evidence already present in a Sprint1 bundle."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from engines.arbe.public_evidence import audit_public_bundle, load_json_mapping

from .base import BaseModule, ModuleResult


class PublicEvidenceAuditModule(BaseModule):
    """Report exact public evidence and GDB-only gaps without diagnosis inference."""

    name = "public-evidence-audit"
    description = "Audit per-frame ego/object/warning evidence available without GDB"
    tags = ["arbe", "ros", "public-evidence", "audit", "atomic"]
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "bundle_path": {"type": "string"},
            "output": {"type": "string"},
        },
        "required": ["bundle_path"],
        "additionalProperties": False,
    }
    output_schema: dict[str, Any] = {
        "type": "object",
        "required": ["schema_version", "status", "frame_evidence", "ego_evidence", "object_evidence"],
    }

    def run(
        self, *, bundle_path: str, output: str = "", **_: Any
    ) -> ModuleResult:
        try:
            bundle = load_json_mapping(bundle_path)
            payload = audit_public_bundle(bundle)
        except Exception as exc:  # noqa: BLE001 - external artifact boundary
            return ModuleResult.fail(
                f"public evidence audit failed: {type(exc).__name__}: {exc}",
                module=self.name,
            )
        artifacts: list[str] = []
        if output:
            path = Path(output).expanduser().resolve()
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
                artifacts.append(str(path))
                payload["artifact_path"] = str(path)
            except OSError as exc:
                return ModuleResult(
                    ok=False,
                    message=f"public evidence audit output failed: {type(exc).__name__}: {exc}",
                    module=self.name,
                    data=payload,
                    artifacts=artifacts,
                )
        return ModuleResult(
            ok=payload.get("status") != "blocked",
            message=f"public-evidence-audit:{payload.get('status', 'unknown')}",
            module=self.name,
            data=payload,
            artifacts=artifacts,
        )

    @classmethod
    def register_cli(cls, subparsers: Any) -> Any:
        parser = super().register_cli(subparsers)
        parser.add_argument("--bundle-path", required=True)
        parser.add_argument("--output", default="")
        return parser

    @classmethod
    def from_cli_args(cls, args: Any) -> "PublicEvidenceAuditModule":
        return cls()


__all__ = ["PublicEvidenceAuditModule"]
