# -*- coding: utf-8 -*-
"""Pi-visible read-only review of user feedback before knowledge publication."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from engines.feedback_review import FeedbackReviewError, review_feedback

from .base import BaseModule, ModuleResult


class FeedbackReviewModule(BaseModule):
    name = "feedback-review"
    description = "审查当前 AnalysisRun 用户确认/否定/无关反馈及知识发布门禁，不写 knowledge"
    tags = ["analysis", "feedback", "provenance", "freshness", "read-only", "atomic"]
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "analysis_run": {"type": "object"},
            "analysis_run_path": {"type": "string"},
            "require_user_confirmation": {"type": "boolean", "default": True},
            "output": {"type": "string"},
        },
        "anyOf": [{"required": ["analysis_run"]}, {"required": ["analysis_run_path"]}],
        "additionalProperties": False,
    }
    output_schema: dict[str, Any] = {"type": "object", "required": ["schema_version", "status", "knowledge_publish_gate"]}

    def run(
        self,
        *,
        analysis_run: Mapping[str, Any] | None = None,
        analysis_run_path: str = "",
        require_user_confirmation: bool = True,
        output: str = "",
        **_: Any,
    ) -> ModuleResult:
        try:
            payload = review_feedback(
                analysis_run=analysis_run,
                analysis_run_path=analysis_run_path,
                require_user_confirmation=require_user_confirmation,
            )
        except (FeedbackReviewError, OSError, TypeError, ValueError) as exc:
            return ModuleResult.fail(f"feedback-review:failed: {exc}", module=self.name, error_type=type(exc).__name__)
        artifacts: list[str] = []
        if str(output or "").strip():
            path = Path(output).expanduser().resolve()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            payload["artifact_path"] = str(path)
            artifacts.append(str(path))
        return ModuleResult(
            ok=payload.get("status") != "blocked",
            message=f"feedback-review:{payload.get('status')}",
            module=self.name,
            artifacts=artifacts,
            data=payload,
        )

    @classmethod
    def register_cli(cls, subparsers: Any) -> Any:
        parser = super().register_cli(subparsers)
        parser.add_argument("--analysis-run", dest="analysis_run_path", default="")
        parser.add_argument("--require-user-confirmation", action="store_true", default=True)
        parser.add_argument("--output", default="")
        return parser

    @classmethod
    def from_cli_args(cls, args: Any) -> "FeedbackReviewModule":
        return cls()


__all__ = ["FeedbackReviewModule"]
