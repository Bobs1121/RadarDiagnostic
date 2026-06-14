# -*- coding: utf-8 -*-
"""
ContextBudget — priority-aware context assembly for long-prompt scenarios.

Problem this solves
-------------------
Expert-panel and understand-problem prompts combine many pieces of evidence:
memory context, data summary, timeline, state transitions, TPE block,
suppression analysis, output signal analysis, threshold reference, parameter
analysis, etc. Each piece was historically truncated to its own
``max_chars`` budget, but there was **no global cap** — so on complex cases
the final prompt could bloat past 80 KB. Over-long prompts:
  - dilute the model's attention,
  - incur token cost linearly,
  - risk hitting the remote model's context window.

Design
------
``ContextBudget`` accepts a total char budget (default 60 KB) and a set of
named pieces with integer priorities (higher = more important). When the
pieces fit, they are concatenated as-is; when they exceed the budget,
lower-priority pieces are truncated first, down to their declared
``min_chars`` floor (so every piece retains its most critical information).

Dynamic budget calculation
--------------------------
``compute_budget()`` calculates total_chars from:
  - Base: 40 KB minimum
  - CodeGraph scale: +5 KB per 500 nodes (more code = more context needed)
  - Test windows: +2 KB per window (more windows = more timeline data)
  - Case duration: +1 KB per 100s of recording
  - Model context window: clamp to 75% of model's available context (default 128K tokens)
  - Caps: 30 KB minimum, 120 KB maximum

Priorities (recommended)
------------------------
  100   evidence / KEY_FACTS / timeline         # what actually happened
   90   TPE block / suppression / output signals # direct causal evidence
   80   memory_context (L1-L6 from MemorySystem)
   70   threshold_reference ({func}.md)
   60   conditions_text
   50   data_summary / inventory
   40   parameter analysis

Typical usage
-------------
>>> budget = ContextBudget(total_chars=60_000)
>>> budget.add("evidence", evidence_text, priority=100, min_chars=8_000)
>>> budget.add("memory", memory_context, priority=80, min_chars=3_000)
>>> budget.add("threshold", threshold_ref, priority=70, min_chars=1_500)
>>> sections = budget.render()  # returns list[(name, truncated_text)]
>>> report = budget.format_report()  # human-readable size stats
"""
from __future__ import annotations

from dataclasses import dataclass, field


def compute_budget(
    codegraph_nodes: int = 0,
    test_window_count: int = 0,
    case_duration_sec: float = 0.0,
    model_context_tokens: int = 128_000,
) -> int:
    """Compute dynamic context budget based on case complexity and model capacity.

    Args:
        codegraph_nodes: Number of nodes in CodeGraph (0 = unknown, uses base).
        test_window_count: Number of test windows detected (0 = unknown).
        case_duration_sec: Total recording duration in seconds (0 = unknown).
        model_context_tokens: Model's context window in tokens (default 128K).

    Returns:
        total_chars: Dynamic budget in characters (30K–120K range).
    """
    # 1 char ≈ 0.5 token for mixed Chinese/English
    # Use 80% of model context as hard ceiling (leave 20% for response)
    max_chars = int(model_context_tokens * 0.5 * 0.8)

    # Base budget
    budget = 40_000

    # CodeGraph scale: more code → more context for code snippets
    if codegraph_nodes > 0:
        budget += int(codegraph_nodes / 500) * 5_000

    # Test windows: more windows → more timeline/timing data
    if test_window_count > 0:
        budget += test_window_count * 2_000

    # Case duration: longer recordings → more data summary needed
    if case_duration_sec > 0:
        budget += int(case_duration_sec / 100) * 1_000

    # Clamp: model ceiling, hard floor 30K, hard cap 120K
    budget = min(budget, max_chars)
    budget = max(30_000, min(120_000, budget))

    return budget


@dataclass
class _Piece:
    name: str
    content: str
    priority: int = 50
    min_chars: int = 500
    # Filled during ``render()`` so callers can inspect actual sizes.
    rendered: str = ""
    truncated: bool = False


@dataclass
class ContextBudget:
    """Assemble prompt pieces within a global character budget.

    Attributes:
        total_chars: Soft cap on combined rendered size. Pieces are trimmed
            to fit but each keeps at least its ``min_chars``.
        pieces: Accumulated pieces (ordered by insertion).
    """
    total_chars: int = 60_000
    pieces: list[_Piece] = field(default_factory=list)

    def add(
        self,
        name: str,
        content: str,
        priority: int = 50,
        min_chars: int = 500,
    ) -> "ContextBudget":
        """Register a piece of context. Empty strings are silently dropped."""
        if not content:
            return self
        self.pieces.append(_Piece(
            name=name,
            content=str(content),
            priority=max(0, int(priority)),
            min_chars=max(0, int(min_chars)),
        ))
        return self

    def render(self) -> list[tuple[str, str]]:
        """Return [(name, content)] trimmed to fit the budget.

        Algorithm (greedy, priority-first):
          1. Sort pieces DESC by priority.
          2. Walk in order; give each its full content if remaining budget
             allows, else truncate to max(remaining, min_chars).
          3. If min_chars already exceeds remaining, the piece is still
             emitted at min_chars (we honor the floor even if it overflows
             the budget; in practice min_chars are set conservatively).
          4. Preserve original insertion order in the returned list.
        """
        if not self.pieces:
            return []

        total_raw = sum(len(p.content) for p in self.pieces)
        if total_raw <= self.total_chars:
            # Everything fits — no truncation needed
            for p in self.pieces:
                p.rendered = p.content
                p.truncated = False
            return [(p.name, p.rendered) for p in self.pieces]

        # Need to truncate: give each piece max(budget_share, min_chars)
        # using priority as the tie-breaker.
        sorted_pieces = sorted(
            self.pieces, key=lambda p: (-p.priority, self.pieces.index(p)),
        )

        remaining = self.total_chars
        # Reserve min_chars for each piece up-front (so low-priority still
        # gets its floor).
        reserved = sum(min(p.min_chars, len(p.content)) for p in self.pieces)
        remaining -= reserved
        # remaining is now the "extra pool" distributable to higher-priority
        # pieces beyond their floor.

        for p in sorted_pieces:
            floor = min(p.min_chars, len(p.content))
            if remaining <= 0:
                allowed = floor
            else:
                available = floor + remaining
                allowed = min(len(p.content), available)
                extra = allowed - floor
                if extra > 0:
                    remaining -= extra

            if allowed < len(p.content):
                p.rendered = p.content[:allowed - 20] + "\n... [truncated]"
                p.truncated = True
            else:
                p.rendered = p.content
                p.truncated = False

        return [(p.name, p.rendered) for p in self.pieces]

    def format_report(self) -> str:
        """Human-readable budget usage report, useful for status lines."""
        if not self.pieces:
            return "(empty budget)"

        # Ensure render() has run at least once
        if not any(p.rendered for p in self.pieces):
            self.render()

        lines = [f"Context budget: {self.total_chars:,} chars"]
        total_rendered = 0
        for p in self.pieces:
            raw = len(p.content)
            rendered = len(p.rendered)
            total_rendered += rendered
            mark = " ⚠trimmed" if p.truncated else ""
            lines.append(
                f"  [{p.priority:3}] {p.name:20s} "
                f"{rendered:>7,} / {raw:>7,} chars{mark}"
            )
        usage_pct = total_rendered / max(self.total_chars, 1) * 100
        lines.append(
            f"  TOTAL rendered: {total_rendered:,} chars "
            f"({usage_pct:.1f}% of budget)"
        )
        return "\n".join(lines)

    def concat(self, joiner: str = "\n\n") -> str:
        """Convenience: render and join all pieces into a single string."""
        sections = self.render()
        return joiner.join(content for _, content in sections if content)
