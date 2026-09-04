# -*- coding: utf-8 -*-
"""
RuleConditionExtractor: Deterministic condition extraction from C source code.

Unlike ConditionExtractor (LLM-based), this module uses regex patterns, AST
analysis, and heuristic rules to extract activation conditions directly from
source code — no LLM calls required.

This provides the first layer of the dual-layer condition extraction:
  1. RuleConditionExtractor — deterministic, fast, guaranteed structure
  2. ConditionExtractor     — LLM-based, richer semantics, slower

Output format is compatible with ConditionExtractor's JSON schema, so they
can be merged seamlessly by the ConditionExtractor wrapper.

Key capabilities
----------------
- Threshold extraction: var >= X, var <= X patterns
- State machine transitions: if (state == A) { state = B; }
- Boolean flag conditions: !A && !B, A == TRUE
- Speed range extraction: ego speed high/low thresholds
- Suppression signal detection: external system references (AEB, ACC, ESP)
- Hold time patterns: timer-based activation requirements
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ── Domain keywords ──────────────────────────────────────────────────────

_SUPPRESSION_KEYWORDS = [
    "aeb", "acc", "esp", "tcs", "dtc", "epb", "esc",
    "brake", "steer", "throttle", "gear", "door", "parking",
    "driver", "pedal", "hander", "park", "reverse",
    "suppress", "disable", "deactivate", "inhibit", "block",
]

_SPEED_KEYWORDS = [
    "ego_speed", "egospeed", "v_ego", "vehicle_speed", "carspeed",
    "ego_vehicle_speed", "veh_speed", "speed_ego",
]

_STATE_KEYWORDS = [
    "state", "mode", "status", "sts", "stat", "mode",
]


# ── Data structures ──────────────────────────────────────────────────────

@dataclass
class RuleCondition:
    """A single extracted condition from deterministic analysis."""
    category: str         # "threshold", "state_transition", "flag", "speed_range", "suppression", "hold_time"
    condition: str         # Human-readable description
    variable: str          # C variable name
    operator: str = ""     # >=, <=, ==, !=, <, >, !
    threshold: str = ""    # Numeric threshold or symbolic value
    source_file: str = ""  # Relative file path
    source_line: int = 0   # Line number
    snippet: str = ""      # Code snippet context
    confidence: float = 0.8  # 0-1, deterministic = high confidence


@dataclass
class RuleConditionResult:
    """Aggregated deterministic conditions for a single ADAS function."""
    function: str = ""
    thresholds: list[RuleCondition] = field(default_factory=list)
    state_transitions: list[RuleCondition] = field(default_factory=list)
    flag_conditions: list[RuleCondition] = field(default_factory=list)
    speed_ranges: list[RuleCondition] = field(default_factory=list)
    suppression_signals: list[RuleCondition] = field(default_factory=list)
    hold_times: list[RuleCondition] = field(default_factory=list)
    raw_conditions: list[RuleCondition] = field(default_factory=list)


# ── Regex patterns ───────────────────────────────────────────────────────

_THRESH_RE = re.compile(
    r'(\w+(?:\.\w+)?)\s*(>=|<=|!=|==|>|<)\s*(\d+(?:\.\d+)?)',
)

_HOLD_TIME_RE = re.compile(
    r'(?:hold|timer|count|timeout|duration|Timer|TimerCnt|HoldTime|HoldTimer)\s*[_.->]*\s*(\w+)\s*(?:==|>=|<=|>|<)\s*(\d+(?:\.\d+)?)',
)

_SPEED_THRESHOLD_RE = re.compile(
    r'(speed|Speed|SPEED|vEgo|VEgo|V_Ego|EgoSpeed|ego_speed|CarSpeed|carspeed)\s*[_.->]*\s*(\w*)\s*(?:==|>=|<=|>|<)\s*(\d+(?:\.\d+)?)',
)

_SUPP_VAR_RE = re.compile(
    r'([A-Za-z_]\w*)\s*(?:==|!=|>=|<=)\s*(\w+)',
)

_STATE_TRANS_RE = re.compile(
    r'([A-Za-z_]\w*(?:State|state|STATE|Mode|mode|MODE)\w*)\s*=\s*(\w+)',
)


# ── Extractor ────────────────────────────────────────────────────────────

class RuleConditionExtractor:
    """Extract conditions from C source code using deterministic rules."""

    def __init__(self, source_root: Path, func_name: str):
        self.source_root = Path(source_root)
        self.func_name = func_name.upper()
        self.func_keywords = [
            self.func_name.lower(),
            self.func_name.replace("_", "").lower(),
            func_name.lower(),
        ]

    def extract(self, files: list[str] | list[Path]) -> RuleConditionResult:
        """Extract all deterministic conditions from the given source files.

        Args:
            files: List of file paths (relative to source_root or absolute).
        """
        result = RuleConditionResult(function=self.func_name)

        for file_path in files:
            path = Path(file_path)
            if not path.is_absolute():
                path = self.source_root / path

            if not path.exists():
                continue

            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except (PermissionError, OSError):
                continue

            lines = content.split("\n")
            rel_path = str(path.relative_to(self.source_root))

            func_conditions = self._scan_for_function(rel_path, lines)
            result.raw_conditions.extend(func_conditions)

            # Categorize conditions
            for cond in func_conditions:
                if cond.category == "threshold":
                    result.thresholds.append(cond)
                elif cond.category == "state_transition":
                    result.state_transitions.append(cond)
                elif cond.category == "flag":
                    result.flag_conditions.append(cond)
                elif cond.category == "speed_range":
                    result.speed_ranges.append(cond)
                elif cond.category == "suppression":
                    result.suppression_signals.append(cond)
                elif cond.category == "hold_time":
                    result.hold_times.append(cond)

        return result

    def _scan_for_function(self, rel_path: str, lines: list[str]) -> list[RuleCondition]:
        """Scan a file for conditions related to the target function."""
        conditions: list[RuleCondition] = []
        n = len(lines)

        # First, find code blocks related to the target function
        func_lines = self._find_function_blocks(lines)
        if not func_lines:
            return conditions

        # Scan those lines for conditions
        for line_idx in func_lines:
            raw = lines[line_idx]
            stripped = raw.strip()

            if stripped.startswith("//") or stripped.startswith("/*"):
                continue

            # Extract thresholds
            conditions.extend(self._extract_thresholds(rel_path, lines, line_idx))

            # Extract state transitions
            conditions.extend(self._extract_state_transitions(rel_path, lines, line_idx))

            # Extract suppression signals
            conditions.extend(self._extract_suppression(rel_path, lines, line_idx))

            # Extract speed ranges
            conditions.extend(self._extract_speed_ranges(rel_path, lines, line_idx))

            # Extract hold time patterns
            conditions.extend(self._extract_hold_times(rel_path, lines, line_idx))

        return conditions

    def _find_function_blocks(self, lines: list[str]) -> set[int]:
        """Find line numbers related to the target function.

        Uses keyword matching on function names, variable names,
        and comment headers.
        """
        func_lines: set[int] = set()
        n = len(lines)

        # Join all content for context
        full_lower = "\n".join(lines).lower()

        # Check if this file is relevant to the function at all
        is_relevant = False
        for kw in self.func_keywords:
            if kw in full_lower:
                is_relevant = True
                break

        if not is_relevant:
            return func_lines

        # Find all lines that reference the function
        for i, line in enumerate(lines):
            line_lower = line.lower()
            for kw in self.func_keywords:
                if kw in line_lower:
                    # Include surrounding context (5 lines before/after)
                    for j in range(max(0, i - 5), min(n, i + 6)):
                        func_lines.add(j)
                    break

            # Also include lines near relevant #define or enum
            if f"#define" in line and any(
                kw in line_lower.replace("_", "") for kw in self.func_keywords
            ):
                for j in range(max(0, i - 2), min(n, i + 10)):
                    func_lines.add(j)

        return func_lines

    def _extract_thresholds(self, rel_path: str, lines: list[str], line_idx: int) -> list[RuleCondition]:
        """Extract threshold comparisons: var >= X, var <= X."""
        conditions: list[RuleCondition] = []
        raw = lines[line_idx]

        for match in _THRESH_RE.finditer(raw):
            var = match.group(1)
            op = match.group(2)
            val = match.group(3)

            # Skip common non-signal variables
            leaf = var.split(".")[-1].split("->")[-1]
            if leaf.lower() in ("i", "j", "k", "n", "idx", "index", "len", "size", "count"):
                continue

            conditions.append(RuleCondition(
                category="threshold",
                condition=f"{var} {op} {val}",
                variable=var,
                operator=op,
                threshold=val,
                source_file=rel_path,
                source_line=line_idx + 1,
                snippet=raw.strip()[:100],
                confidence=0.9,
            ))

        return conditions

    def _extract_state_transitions(self, rel_path: str, lines: list[str], line_idx: int) -> list[RuleCondition]:
        """Extract state machine transitions."""
        conditions: list[RuleCondition] = []
        raw = lines[line_idx]

        for match in _STATE_TRANS_RE.finditer(raw):
            state_var = match.group(1)
            new_state = match.group(2)

            conditions.append(RuleCondition(
                category="state_transition",
                condition=f"{state_var} = {new_state}",
                variable=state_var,
                operator="=",
                threshold=new_state,
                source_file=rel_path,
                source_line=line_idx + 1,
                snippet=raw.strip()[:100],
                confidence=0.85,
            ))

        return conditions

    def _extract_suppression(self, rel_path: str, lines: list[str], line_idx: int) -> list[RuleCondition]:
        """Detect suppression signals from external systems."""
        conditions: list[RuleCondition] = []
        raw = lines[line_idx]
        stripped = raw.strip()

        if not any(kw in stripped.lower() for kw in _SUPPRESSION_KEYWORDS):
            return conditions

        for match in _SUPP_VAR_RE.finditer(raw):
            var = match.group(1)
            val = match.group(2)

            # Only add if the variable looks suppression-related
            var_lower = var.lower()
            if not any(kw in var_lower for kw in _SUPPRESSION_KEYWORDS):
                # Check context line for suppression keywords
                context = " ".join(lines[max(0, line_idx-2):line_idx+1]).lower()
                if not any(kw in context for kw in _SUPPRESSION_KEYWORDS):
                    continue

            conditions.append(RuleCondition(
                category="suppression",
                condition=f"{var} {val} (suppression-related)",
                variable=var,
                operator="==",
                threshold=val,
                source_file=rel_path,
                source_line=line_idx + 1,
                snippet=raw.strip()[:100],
                confidence=0.7,
            ))

        return conditions

    def _extract_speed_ranges(self, rel_path: str, lines: list[str], line_idx: int) -> list[RuleCondition]:
        """Extract ego speed range thresholds."""
        conditions: list[RuleCondition] = []
        raw = lines[line_idx]

        for match in _SPEED_THRESHOLD_RE.finditer(raw, re.IGNORECASE):
            speed_var = match.group(1)
            suffix = match.group(2)
            val = match.group(3)

            full_var = f"{speed_var}{suffix}" if suffix else speed_var
            conditions.append(RuleCondition(
                category="speed_range",
                condition=f"Speed threshold: {full_var} = {val}",
                variable=full_var,
                operator="",
                threshold=val,
                source_file=rel_path,
                source_line=line_idx + 1,
                snippet=raw.strip()[:100],
                confidence=0.85,
            ))

        return conditions

    def _extract_hold_times(self, rel_path: str, lines: list[str], line_idx: int) -> list[RuleCondition]:
        """Extract hold time / timer-based activation requirements."""
        conditions: list[RuleCondition] = []
        raw = lines[line_idx]

        for match in _HOLD_TIME_RE.finditer(raw):
            timer_var = match.group(1)
            threshold = match.group(2)

            conditions.append(RuleCondition(
                category="hold_time",
                condition=f"Timer/hold: {timer_var} reaches {threshold}",
                variable=timer_var,
                operator="",
                threshold=threshold,
                source_file=rel_path,
                source_line=line_idx + 1,
                snippet=raw.strip()[:100],
                confidence=0.8,
            ))

        return conditions

    def to_json(self, result: RuleConditionResult) -> dict:
        """Convert RuleConditionResult to JSON-compatible dict.

        Format is compatible with ConditionExtractor's output schema
        for easy merging.
        """
        output = {
            "function": result.function,
            "extractor": "RuleConditionExtractor",
            "total_conditions": len(result.raw_conditions),
            "thresholds": [],
            "state_transitions": [],
            "flag_conditions": [],
            "speed_ranges": [],
            "external_suppression": [],
            "hold_times": [],
        }

        for cond in result.thresholds:
            output["thresholds"].append({
                "condition": cond.condition,
                "variable": cond.variable,
                "operator": cond.operator,
                "threshold": cond.threshold,
                "source": f"{cond.source_file}:{cond.source_line}",
                "confidence": cond.confidence,
            })

        for cond in result.state_transitions:
            output["state_transitions"].append({
                "from": "*",
                "to": cond.threshold,
                "condition": cond.condition,
                "variable": cond.variable,
                "source": f"{cond.source_file}:{cond.source_line}",
            })

        for cond in result.flag_conditions:
            output["flag_conditions"].append({
                "condition": cond.condition,
                "variable": cond.variable,
                "source": f"{cond.source_file}:{cond.source_line}",
            })

        for cond in result.speed_ranges:
            output["speed_ranges"].append({
                "condition": cond.condition,
                "variable": cond.variable,
                "threshold": cond.threshold,
                "source": f"{cond.source_file}:{cond.source_line}",
            })

        for cond in result.suppression_signals:
            output["external_suppression"].append({
                "condition": cond.condition,
                "variable": cond.variable,
                "suppression_trigger": cond.threshold,
                "source": f"{cond.source_file}:{cond.source_line}",
                "confidence": cond.confidence,
            })

        for cond in result.hold_times:
            output["hold_times"].append({
                "condition": cond.condition,
                "variable": cond.variable,
                "threshold": cond.threshold,
                "source": f"{cond.source_file}:{cond.source_line}",
            })

        return output
