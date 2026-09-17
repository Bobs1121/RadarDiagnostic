# -*- coding: utf-8 -*-
"""Plan a user-approved knowledge publication without writing knowledge."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from engines.feedback_review import FeedbackReviewError, build_knowledge_publish_plan

from .base import BaseModule, ModuleResult


def _json_object(text: str) -> dict[str, Any]:
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError("expected JSON object")
    return value


class FeedbackKnowledgePlanModule(BaseModule):
    name = "feedback-knowledge-plan"
    description = "生成用户反馈驱动的 knowledge publish plan；只读，不写 memory"
    tags = ["feedback", "knowledge", "freshness", "provenance", "read-only", "atomic"]
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "feedback_review": {"type": "object"},
            "feedback_review_path": {"type": "string"},
            "candidate_pattern": {"type": "object"},
            "candidate_pattern_path": {"type": "string"},
            "approved": {"type": "boolean", "default": False},
            "actor": {"type": "string", "enum": ["user", "ai", "tool", "pi"], "default": "user"},
            "freshness": {"type": "object"},
            "freshness_path": {"type": "string"},
            "output": {"type": "string"},
        },
        "anyOf": [
            {"required": ["feedback_review"]},
            {"required": ["feedback_review_path"]},
        ],
        "additionalProperties": False,
    }
    output_schema: dict[str, Any] = {"type": "object", "required": ["schema_version", "status", "writes_knowledge", "next_action"]}

    def run(
        self,
        *,
        feedback_review: Mapping[str, Any] | None = None,
        feedback_review_path: str = "",
        candidate_pattern: Mapping[str, Any] | None = None,
        candidate_pattern_path: str = "",
        approved: bool = False,
        actor: str = "user",
        freshness: Mapping[str, Any] | None = None,
        freshness_path: str = "",
        output: str = "",
        **_: Any,
    ) -> ModuleResult:
        try:
            review = dict(feedback_review or {})
            if not review and feedback_review_path:
                review = json.loads(Path(feedback_review_path).expanduser().resolve().read_text(encoding="utf-8"))
            pattern = dict(candidate_pattern or {})
            if not pattern and candidate_pattern_path:
                pattern = json.loads(Path(candidate_pattern_path).expanduser().resolve().read_text(encoding="utf-8"))
            fresh = dict(freshness or {})
            if not fresh and freshness_path:
                fresh = json.loads(Path(freshness_path).expanduser().resolve().read_text(encoding="utf-8"))
            payload = build_knowledge_publish_plan(
                feedback_review=review,
                candidate_pattern=pattern,
                approved=approved,
                actor=actor,
                freshness=fresh,
            )
        except (FeedbackReviewError, OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            return ModuleResult.fail(f"feedback-knowledge-plan:failed:{exc}", module=self.name, error_type=type(exc).__name__)
        artifacts: list[str] = []
        if output:
            path = Path(output).expanduser().resolve()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            payload["artifact_path"] = str(path)
            artifacts.append(str(path))
        return ModuleResult(ok=payload.get("status") != "blocked", message=f"feedback-knowledge-plan:{payload.get('status')}", module=self.name, artifacts=artifacts, data=payload)

    @classmethod
    def register_cli(cls, subparsers: Any) -> Any:
        parser = super().register_cli(subparsers)
        parser.add_argument("--feedback-review", dest="feedback_review_path", default="")
        parser.add_argument("--candidate-pattern", dest="candidate_pattern_path", default="")
        parser.add_argument("--approved", action="store_true")
        parser.add_argument("--actor", choices=["user", "ai", "tool", "pi"], default="user")
        parser.add_argument("--freshness", dest="freshness_path", default="")
        parser.add_argument("--output", default="")
        return parser

    @classmethod
    def from_cli_args(cls, args: Any) -> "FeedbackKnowledgePlanModule":
        return cls()


__all__ = ["FeedbackKnowledgePlanModule"]
