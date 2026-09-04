# -*- coding: utf-8 -*-
"""
DiagnosisPanelModule (M6) - classify a diagnosis request and optionally run the
expert panel without touching the legacy orchestrator.

The module is intentionally offline-friendly:

* callers may inject a classifier and/or panel stub for tests;
* classify-only mode never requires LLM or LangGraph dependencies;
* panel acquisition degrades to a structured classification-only result when
  the panel stack is unavailable.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ..utils import ALL_FUNCTIONS
from .base import BaseModule, ModuleResult

log = logging.getLogger(__name__)

PANEL_MODES: tuple[str, ...] = ("classify", "panel", "auto")


class _FallbackClassifier:
    """Small local fallback used only when ProblemClassifier cannot import."""

    def __init__(self, reason: str) -> None:
        self.reason = reason

    def classify(
        self,
        problem: str,
        expected: str = "",
        memory_hint: str = "",
    ) -> dict[str, Any]:
        text = f"{problem}\n{expected}".strip()
        up = text.upper()
        target = next((fn for fn in ALL_FUNCTIONS if fn in up), "UNKNOWN")
        confidence = 0.0 if not text else 0.3
        if not text:
            reasoning = "Empty problem description; defaulting to diagnose."
        else:
            reasoning = f"ProblemClassifier unavailable; default diagnose. {self.reason}"
        return {
            "task_type": "diagnose",
            "confidence": confidence,
            "target_function": target,
            "focus_parameters": [],
            "focus_signals": [],
            "reasoning": reasoning[:500],
        }


def _normalise_list(raw: Any) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, str):
        raw = [raw]
    out: list[str] = []
    for item in raw:
        value = str(item).strip()
        if value and value not in out:
            out.append(value)
    return out


def _normalise_classification(raw: Any) -> dict[str, Any]:
    if raw is None:
        raw = {}

    if hasattr(raw, "to_dict") and callable(raw.to_dict):
        raw = raw.to_dict()
    elif not isinstance(raw, dict):
        raw = {
            "task_type": getattr(raw, "task_type", "diagnose"),
            "confidence": getattr(raw, "confidence", 0.0),
            "target_function": getattr(raw, "target_function", "UNKNOWN"),
            "focus_parameters": getattr(raw, "focus_parameters", []),
            "focus_signals": getattr(raw, "focus_signals", []),
            "reasoning": getattr(raw, "reasoning", ""),
        }

    try:
        confidence = float(raw.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0

    target = str(raw.get("target_function", "UNKNOWN")).upper() or "UNKNOWN"
    if target not in ALL_FUNCTIONS:
        target = "UNKNOWN"

    task_type = str(raw.get("task_type", "diagnose")).lower() or "diagnose"
    if task_type not in ("diagnose", "tune", "verify", "query"):
        task_type = "diagnose"

    return {
        "task_type": task_type,
        "confidence": round(confidence, 2),
        "target_function": target,
        "focus_parameters": _normalise_list(raw.get("focus_parameters")),
        "focus_signals": _normalise_list(raw.get("focus_signals")),
        "reasoning": str(raw.get("reasoning", ""))[:500],
    }


class DiagnosisPanelModule(BaseModule):
    """M6 standalone wrapper over ProblemClassifier + ExpertPanel."""

    name = "diagnosis-panel"
    description = "Classify a diagnosis request and optionally run the panel (M6)"

    def __init__(
        self,
        *,
        classifier: Any = None,
        panel: Any = None,
        panel_factory: Any = None,
        router: Any = None,
        config: dict[str, Any] | None = None,
        project_root: str | Path | None = None,
    ) -> None:
        self._classifier = classifier
        self._panel = panel
        self._panel_factory = panel_factory
        self.router = router
        self.config = config or {}
        self.project_root = Path(project_root) if project_root else None

    def _get_classifier(self) -> Any:
        if self._classifier is not None:
            return self._classifier

        try:
            from ..problem_classifier import ProblemClassifier
        except Exception as exc:  # noqa: BLE001 - optional import guard
            reason = f"{type(exc).__name__}: {exc}"
            log.warning("ProblemClassifier unavailable for %s: %s", self.name, reason)
            self._classifier = _FallbackClassifier(reason)
            return self._classifier

        self._classifier = ProblemClassifier(router=self.router)
        return self._classifier

    def _build_panel(self) -> tuple[Any | None, str]:
        if self._panel is not None:
            return self._panel, ""

        if self._panel_factory is not None:
            try:
                self._panel = self._panel_factory(
                    self.router, self.config, self.project_root,
                )
                return self._panel, ""
            except Exception as exc:  # noqa: BLE001 - explicit structured degrade
                return None, f"{type(exc).__name__}: {exc}"

        if self.router is None or not self.config or self.project_root is None:
            return None, "router, config, and project_root are required for panel mode"

        errors: list[str] = []
        for label, builder in (
            ("langgraph", self._build_langgraph_panel),
            ("procedural", self._build_procedural_panel),
        ):
            try:
                panel = builder()
            except Exception as exc:  # noqa: BLE001 - optional dependency guard
                errors.append(f"{label}={type(exc).__name__}: {exc}")
                continue
            self._panel = panel
            return panel, ""

        return None, "; ".join(errors) or "no panel implementation available"

    def _build_langgraph_panel(self) -> Any:
        from ..expert_panel_langgraph import ExpertPanel

        return ExpertPanel(self.router, self.config, self.project_root)

    def _build_procedural_panel(self) -> Any:
        from ..expert_panel import ExpertPanel

        return ExpertPanel(self.router, self.config, self.project_root)

    def run(
        self,
        *,
        problem: str,
        expected: str = "",
        mode: str = "auto",
        func_name: str = "",
        data_summary: str = "",
        memory_context: str = "",
        fail_type: str = "OTHER",
        task_type: str = "",
        on_status: Any = None,
        **_: Any,
    ) -> ModuleResult:
        mode = (mode or "auto").lower()
        if mode not in PANEL_MODES:
            return ModuleResult.fail(
                f"unknown mode {mode!r}; choose one of {list(PANEL_MODES)}",
                module=self.name,
            )

        classifier = self._get_classifier()
        classify = getattr(classifier, "classify", None)
        if not callable(classify):
            return ModuleResult.fail(
                "classifier does not provide classify(problem, expected, memory_hint)",
                module=self.name,
            )

        classification = _normalise_classification(
            classify(problem, expected=expected, memory_hint=memory_context),
        )

        resolved_func = (func_name or classification["target_function"] or "UNKNOWN").upper()
        if resolved_func not in ALL_FUNCTIONS:
            resolved_func = "UNKNOWN"
        resolved_task_type = (task_type or classification["task_type"] or "diagnose").lower()
        if resolved_task_type not in ("diagnose", "tune", "verify", "query"):
            resolved_task_type = "diagnose"

        payload: dict[str, Any] = {
            "requested_mode": mode,
            "effective_mode": "classify",
            "classification": classification,
            "panel_result": None,
            "panel_status": "not_requested",
            "func_name": resolved_func,
            "task_type": resolved_task_type,
            "fail_type": fail_type,
        }

        if mode == "classify":
            return ModuleResult.success(
                message="diagnosis-panel:classify",
                module=self.name,
                **payload,
            )

        panel, panel_error = self._build_panel()
        if panel is None:
            payload["panel_status"] = "unavailable"
            payload["panel_error"] = panel_error
            return ModuleResult.success(
                message="diagnosis-panel:classification-only",
                module=self.name,
                **payload,
            )

        run_panel = getattr(panel, "run_panel", None)
        if not callable(run_panel):
            payload["panel_status"] = "unavailable"
            payload["panel_error"] = "panel object does not provide run_panel(...)"
            return ModuleResult.fail(
                "panel object does not provide run_panel(...)",
                module=self.name,
                **payload,
            )

        try:
            panel_result = run_panel(
                problem=problem,
                expected=expected,
                func_name=resolved_func,
                data_summary=data_summary,
                memory_context=memory_context,
                on_status=on_status,
                fail_type=fail_type,
                task_type=resolved_task_type,
            )
        except Exception as exc:  # noqa: BLE001 - surface panel failures explicitly
            payload["panel_status"] = "failed"
            payload["panel_error"] = f"{type(exc).__name__}: {exc}"
            return ModuleResult.fail(
                f"panel run failed: {type(exc).__name__}: {exc}",
                module=self.name,
                **payload,
            )

        payload["effective_mode"] = "panel"
        payload["panel_status"] = "completed"
        payload["panel_result"] = panel_result
        return ModuleResult.success(
            message="diagnosis-panel:panel",
            module=self.name,
            **payload,
        )

    @classmethod
    def register_cli(cls, subparsers: Any) -> Any:
        parser = super().register_cli(subparsers)
        parser.add_argument(
            "--problem", required=True,
            help="Problem statement to classify or diagnose.",
        )
        parser.add_argument(
            "--expected", default="",
            help="Expected behavior for the case.",
        )
        parser.add_argument(
            "--mode", choices=list(PANEL_MODES), default="auto",
            help="classify=classifier only, panel=run panel if available, auto=best effort panel.",
        )
        parser.add_argument(
            "--func-name", default="",
            help="Override the target ADAS function instead of using classification output.",
        )
        parser.add_argument(
            "--data-summary", default="",
            help="Prepared data summary/context for the expert panel.",
        )
        parser.add_argument(
            "--memory-context", default="",
            help="Optional memory/context summary used for classification and paneling.",
        )
        parser.add_argument(
            "--fail-type", default="OTHER",
            help="Failure type hint passed to the expert panel (FP/FN/DELAY/STATE/OTHER).",
        )
        parser.add_argument(
            "--task-type", default="",
            help="Override the task type instead of using classifier output.",
        )
        return parser

    @classmethod
    def from_cli_args(cls, args: Any) -> "DiagnosisPanelModule":
        mode = getattr(args, "mode", "auto")
        if mode == "classify":
            return cls()

        try:
            from config import load_config

            from ..model_router import ModelRouter
        except Exception:
            return cls()

        try:
            config = load_config()
            project_root = Path(__file__).resolve().parents[2]
            router = ModelRouter(config)
        except Exception:
            return cls()

        return cls(router=router, config=config, project_root=project_root)
