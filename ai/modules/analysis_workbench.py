# -*- coding: utf-8 -*-
"""Read-only AnalysisRun Workbench projection."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from engines.analysis_workbench import AnalysisWorkbenchError, build_analysis_workbench, write_analysis_workbench

from .base import BaseModule, ModuleResult


class AnalysisWorkbenchModule(BaseModule):
    name = "analysis-workbench"
    description = "将现有 AnalysisRun/ledger 投影为只读 Workbench JSON/HTML，不创建平行状态树"
    tags = ["analysis", "workbench", "ledger", "feedback", "read-only", "local-write", "atomic"]
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "analysis_run": {"type": "object"},
            "analysis_run_path": {"type": "string"},
            "feedback_review": {"type": "object"},
            "feedback_review_path": {"type": "string"},
            "output_dir": {"type": "string"},
        },
        "anyOf": [{"required": ["analysis_run"]}, {"required": ["analysis_run_path"]}],
        "additionalProperties": False,
    }
    output_schema: dict[str, Any] = {"type": "object", "required": ["schema_version", "status", "run", "counts", "policy"]}

    def run(
        self,
        *,
        analysis_run: Mapping[str, Any] | None = None,
        analysis_run_path: str = "",
        feedback_review: Mapping[str, Any] | None = None,
        feedback_review_path: str = "",
        output_dir: str = "",
        **_: Any,
    ) -> ModuleResult:
        try:
            payload = build_analysis_workbench(
                analysis_run=analysis_run,
                analysis_run_path=analysis_run_path,
                feedback_review=feedback_review,
                feedback_review_path=feedback_review_path,
            )
        except (AnalysisWorkbenchError, OSError, TypeError, ValueError) as exc:
            return ModuleResult.fail(f"analysis-workbench:failed:{exc}", module=self.name, error_type=type(exc).__name__)
        artifacts: list[str] = []
        if output_dir:
            artifacts = write_analysis_workbench(payload, output_dir)
            payload["artifact_paths"] = artifacts
        return ModuleResult(ok=True, message=f"analysis-workbench:{payload.get('status')}", module=self.name, artifacts=artifacts, data=payload)

    @classmethod
    def register_cli(cls, subparsers: Any) -> Any:
        parser = super().register_cli(subparsers)
        parser.add_argument("--analysis-run", dest="analysis_run_path", default="")
        parser.add_argument("--feedback-review", dest="feedback_review_path", default="")
        parser.add_argument("--output-dir", default="")
        return parser

    @classmethod
    def from_cli_args(cls, args: Any) -> "AnalysisWorkbenchModule":
        return cls()


__all__ = ["AnalysisWorkbenchModule"]
