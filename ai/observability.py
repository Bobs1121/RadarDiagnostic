# -*- coding: utf-8 -*-
"""
Observability layer for the diagnosis pipeline.

Records per-step metrics (input summary, output summary, duration, tokens,
errors) and writes a structured JSON log at the end of each diagnosis run.
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, Optional


class StepLogger:
    """
    Lightweight step logger that records input/output summaries,
    durations, and token counts for each pipeline step.
    """

    def __init__(self, session_id: Optional[str] = None):
        self.session_id = session_id or uuid.uuid4().hex[:12]
        self.start_time = time.time()
        self.steps: list[dict[str, Any]] = []
        self._current: Optional[dict[str, Any]] = None

    def start(self, step: str, input_summary: str = "") -> None:
        """Mark the start of a pipeline step."""
        self._current = {
            "step": step,
            "input_summary": input_summary[:500],
            "started_at": time.time() - self.start_time,
        }

    def end(
        self,
        output_summary: str = "",
        tokens: int = 0,
        error: Optional[str] = None,
    ) -> None:
        """Mark the end of a pipeline step."""
        if self._current is None:
            return
        self._current["output_summary"] = output_summary[:500]
        self._current["tokens"] = tokens
        self._current["duration"] = time.time() - self.start_time - self._current["started_at"]
        if error:
            self._current["error"] = error[:500]
        self.steps.append(self._current)
        self._current = None

    def record(self, step: str, input_summary: str = "", output_summary: str = "",
               tokens: int = 0, error: Optional[str] = None) -> None:
        """Record a complete step in one call."""
        self.start(step, input_summary)
        self.end(output_summary, tokens, error)

    def save(self, path: str | Path) -> None:
        """Save the step log as JSON."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        log_data = {
            "session_id": self.session_id,
            "started_at": self.start_time,
            "total_duration": time.time() - self.start_time,
            "step_count": len(self.steps),
            "steps": self.steps,
        }
        path.write_text(json.dumps(log_data, indent=2, ensure_ascii=False), encoding="utf-8")

    def summary(self) -> dict:
        """Return a quick summary of the run so far."""
        total_tokens = sum(s.get("tokens", 0) for s in self.steps)
        total_duration = sum(s.get("duration", 0) for s in self.steps)
        errors = [s["step"] for s in self.steps if "error" in s]
        return {
            "session_id": self.session_id,
            "steps_completed": len(self.steps),
            "total_tokens": total_tokens,
            "total_duration": round(total_duration, 2),
            "errors": errors,
        }


class TokenTracker:
    """Accumulate token usage across multiple model calls."""

    def __init__(self):
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.call_count = 0
        self.by_model: dict[str, dict[str, int]] = {}

    def record(self, result: dict) -> None:
        """Record token usage from a model_router result."""
        self.call_count += 1
        usage = result.get("usage", {})
        pt = usage.get("prompt_tokens", 0)
        ct = usage.get("completion_tokens", 0)
        self.prompt_tokens += pt
        self.completion_tokens += ct

        model = result.get("model", "unknown")
        if model not in self.by_model:
            self.by_model[model] = {"prompt_tokens": 0, "completion_tokens": 0, "calls": 0}
        self.by_model[model]["prompt_tokens"] += pt
        self.by_model[model]["completion_tokens"] += ct
        self.by_model[model]["calls"] += 1

    def summary(self) -> dict:
        return {
            "total_prompt_tokens": self.prompt_tokens,
            "total_completion_tokens": self.completion_tokens,
            "total_tokens": self.prompt_tokens + self.completion_tokens,
            "total_calls": self.call_count,
            "by_model": dict(self.by_model),
        }


# ---------------------------------------------------------------------------
# Observable wrapper for orchestrator status callbacks
# ---------------------------------------------------------------------------

class ObservableStatus:
    """
    Wrap the user's on_status callback with StepLogger integration.
    Every status(step, detail) call is logged.
    """

    def __init__(self, on_status=None, logger: StepLogger | None = None):
        self.on_status = on_status
        self.logger = logger or StepLogger()
        self._last_step = None

    def __call__(self, step: str, detail: str = "") -> None:
        # Notify user
        if self.on_status:
            self.on_status(step, detail)

        # Log to step logger
        if step != self._last_step:
            # New step started
            if self._last_step is not None:
                self.logger.end()
            self.logger.start(step, detail)
            self._last_step = step
        else:
            # Same step, update with more detail
            if self.logger._current:
                self.logger._current["input_summary"] = (
                    self.logger._current.get("input_summary", "") + " | " + detail[:200]
                )[:500]

    def finish_step(self, output_summary: str = "", tokens: int = 0,
                    error: Optional[str] = None) -> None:
        """Explicitly finish the current step."""
        self.logger.end(output_summary, tokens, error)
        self._last_step = None
