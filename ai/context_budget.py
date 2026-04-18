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
