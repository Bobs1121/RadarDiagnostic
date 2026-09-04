# -*- coding: utf-8 -*-
"""AskHumanTool — deterministic human-in-the-loop pause primitive.

Registered under the ``ask_user`` name in ``ai.tools.TOOL_REGISTRY``. It is the
concrete realization of the ``input_required`` / ``pending_input`` pause
mechanism already present in ``ai/agent_loop.py``: when the Agent loop hits a
tool whose name matches ``ask_human_tool_name`` it short-circuits and marks the
state ``input_required`` *without* ever invoking the tool's ``execute``. This
class therefore serves two roles:

1. A discoverable, importable tool class that downstream callers (ReAct planner,
   CLI, conversation bridge) can register and route questions through.
2. A safe fallback path when invoked directly (e.g. outside the Agent loop):
   it reads one line from stdin. If stdin is unavailable (EOFError / no tty /
   ``RADAR_ANALYZE_NON_INTERACTIVE`` env flag set), it returns a structured
   ``status="pending"`` result instead of hanging, so batch / CI runs never
   block on a missing human.

The result envelope always conforms to ``ai.tools.base.build_tool_result``:
``{status, message, data, artifacts}`` with ``data`` carrying the ``question``
and (when answered) the ``answer``.
"""
from __future__ import annotations

import os
import sys
from typing import Any

from .base import BaseTool


_NON_INTERACTIVE_ENV = "RADAR_ANALYZE_NON_INTERACTIVE"


class AskHumanTool(BaseTool):
    """Pause for human input; never raises across Agent boundaries."""

    name = "ask_user"
    # Human interaction is native to Pi/RPC. Keep this primitive available to
    # the offline AgentLoop, but do not expose a second ask-user protocol as a
    # generated Pi business tool.
    expose_to_pi = False
    description = (
        "Ask the human operator a clarifying question and pause for a "
        "textual answer. Returns status='pending' (with the question) when "
        "no interactive stdin is available, otherwise status='ok' with "
        "the captured answer."
    )
    parameters_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "The clarifying question to present to the human.",
            },
            "context": {
                "type": "string",
                "description": "Optional context / reasoning to show alongside the question.",
            },
        },
        "required": ["question"],
        "additionalProperties": False,
    }

    def execute(self, params: dict[str, Any]) -> dict[str, Any]:
        question = str(params.get("question") or "").strip()
        context = str(params.get("context") or "").strip()
        if not question:
            return self.error("missing required parameter: question")

        # Non-interactive fast path: env flag explicitly disables prompting,
        # or there is no live stdin (piped/closed/CI). Emit a pending result
        # so the caller (Agent loop / orchestrator / CLI) can surface the
        # question to a real UI instead of hanging forever.
        if os.environ.get(_NON_INTERACTIVE_ENV):
            return self._pending(question, context, reason="non_interactive_env")

        if not self._stdin_is_interactive():
            return self._pending(question, context, reason="no_interactive_stdin")

        prompt_text = f"[ask_user] {question}"
        if context:
            prompt_text += f"\n  context: {context}"
        prompt_text += "\nAnswer (one line, empty to skip): "

        try:
            answer = input(prompt_text)
        except EOFError:
            return self._pending(question, context, reason="stdin_eof")
        except (KeyboardInterrupt, OSError):
            return self._pending(question, context, reason="stdin_unavailable")

        answer = (answer or "").strip()
        if not answer:
            return self._pending(question, context, reason="empty_answer")

        return self.ok(
            data={"question": question, "answer": answer, "context": context or None},
            message=f"Answered: {answer[:80]}",
            artifacts=[],
        )

    # ------------------------------------------------------------------
    @staticmethod
    def _stdin_is_interactive() -> bool:
        try:
            return bool(sys.stdin and sys.stdin.isatty())
        except Exception:  # noqa: BLE001 - defensive; never block on a probe
            return False

    def _pending(self, question: str, context: str, *, reason: str) -> dict[str, Any]:
        """Return a pending envelope (status='ok', data.pending=True).

        We deliberately use ``status="ok"`` (not ``error``) so a caller that
        only checks ``status`` does not treat the pause as a hard failure; the
        explicit ``pending`` flag + ``reason`` let richer consumers branch.
        """
        return self.ok(
            data={
                "question": question,
                "context": context or None,
                "pending": True,
                "reason": reason,
                "answer": None,
            },
            message=f"Human input pending ({reason})",
            artifacts=[],
        )


__all__ = ["AskHumanTool"]
