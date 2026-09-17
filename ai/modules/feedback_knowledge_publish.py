# -*- coding: utf-8 -*-
"""Approved, variant-scoped feedback knowledge publication leaf."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from engines.feedback_review import FeedbackReviewError, publish_feedback_knowledge

from .base import BaseModule, ModuleResult


class FeedbackKnowledgePublishModule(BaseModule):
    name = "feedback-knowledge-publish"
    description = "在用户批准且 variant scope/freshness gate 通过后发布 feedback pattern"
    tags = ["feedback", "knowledge", "write", "approval", "provenance", "atomic"]
    requires_approval = True
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "publish_plan": {"type": "object"},
            "publish_plan_path": {"type": "string"},
            "knowledge_dir": {"type": "string"},
            "actor": {"type": "string", "enum": ["user", "ai", "tool", "pi"], "default": "user"},
            "approved": {"type": "boolean", "default": False},
            "output": {"type": "string"},
        },
        "anyOf": [{"required": ["publish_plan"]}, {"required": ["publish_plan_path"]}],
        "required": ["knowledge_dir"],
        "additionalProperties": False,
    }
    output_schema: dict[str, Any] = {"type": "object", "required": ["schema_version", "status", "writes_knowledge"]}

    def run(
        self,
        *,
        publish_plan: Mapping[str, Any] | None = None,
        publish_plan_path: str = "",
        knowledge_dir: str,
        actor: str = "user",
        approved: bool = False,
        output: str = "",
        **_: Any,
    ) -> ModuleResult:
        try:
            plan = dict(publish_plan or {})
            if not plan and publish_plan_path:
                plan = json.loads(Path(publish_plan_path).expanduser().resolve().read_text(encoding="utf-8"))
            payload = publish_feedback_knowledge(
                publish_plan=plan,
                knowledge_dir=knowledge_dir,
                actor=actor,
                approved=approved,
            )
        except (FeedbackReviewError, OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            return ModuleResult.fail(f"feedback-knowledge-publish:failed:{exc}", module=self.name, error_type=type(exc).__name__)
        artifacts: list[str] = []
        if output:
            path = Path(output).expanduser().resolve()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            payload["artifact_path"] = str(path)
            artifacts.append(str(path))
        return ModuleResult(ok=True, message="feedback-knowledge-publish:published", module=self.name, artifacts=artifacts, data=payload)

    @classmethod
    def register_cli(cls, subparsers: Any) -> Any:
        parser = super().register_cli(subparsers)
        parser.add_argument("--publish-plan", dest="publish_plan_path", default="")
        parser.add_argument("--knowledge-dir", required=True)
        parser.add_argument("--actor", choices=["user", "ai", "tool", "pi"], default="user")
        parser.add_argument("--approved", action="store_true")
        parser.add_argument("--output", default="")
        return parser

    @classmethod
    def from_cli_args(cls, args: Any) -> "FeedbackKnowledgePublishModule":
        return cls()


__all__ = ["FeedbackKnowledgePublishModule"]
