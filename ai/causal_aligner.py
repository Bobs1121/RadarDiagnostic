# -*- coding: utf-8 -*-
"""
Causal Aligner
==============

The missing link between :mod:`pattern_extractor` (code-side patterns)
and :mod:`temporal_analyzer` (data-side features).

Responsibilities
----------------
Given

1. a list of :class:`~ai.pattern_extractor.CodePattern` objects describing
   temporal behaviours in the source code;
2. per-signal :class:`~ai.temporal_analyzer.TemporalFeature` objects
   describing the runtime fingerprint of those signals;
3. a signal-mapping table that tells us which CAN signal backs an
   internal variable,

this module figures out **whether the pattern has ever fired in the
captured data**, when, for how long, and whether the firing correlates
with observed state changes (state machine transitions, warning edges,
etc.).

The output is a list of :class:`PatternEvidence` records that can be
rendered into an expert-facing evidence block. The algorithm is fully
deterministic; no LLM calls are made.

Logical model
-------------
A HoldRelease pattern like ``if (!A && !B) { flag = false; time = 0 }``
fires at instant ``t`` iff at that instant ``A == 0`` **and** ``B == 0``.
We express this as "the intersection of the A's ``0`` runs with B's
``0`` runs", yielding a list of time intervals during which the pattern
would fire. For each interval we also record nearby state transitions
(within ±500 ms) as circumstantial evidence.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Iterable, Optional

from .pattern_extractor import CodePattern
from .temporal_analyzer import (
    TemporalAnalyzer, TemporalFeature, SignalTimeline,
)


__all__ = [
    "Interval",
    "PatternEvidence",
    "CausalAligner",
    "format_evidence_block",
]


# ── Datatypes ────────────────────────────────────────────────────────────


@dataclass
class Interval:
    """A closed half-open time interval (seconds)."""
    t_start: float
    t_end: float

    @property
    def duration(self) -> float:
        return max(0.0, self.t_end - self.t_start)


@dataclass
class PatternHit:
    """A single moment when the pattern's trigger condition was satisfied."""
    interval: Interval
    signals_at_start: dict[str, object]
    nearby_state_changes: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "t_start": round(self.interval.t_start, 3),
            "t_end": round(self.interval.t_end, 3),
            "duration_ms": round(self.interval.duration * 1000, 1),
            "signals_at_start": self.signals_at_start,
            "nearby_state_changes": self.nearby_state_changes,
        }


@dataclass
class PatternEvidence:
    """Collected evidence for/against a single :class:`CodePattern`."""
    pattern: CodePattern
    resolution: dict[str, str]
    verdict: str
    hits: list[PatternHit]
    unresolved_signals: list[str] = field(default_factory=list)
    missing_signals: list[str] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> dict:
        return {
            "pattern": self.pattern.to_dict(),
            "resolution": self.resolution,
            "verdict": self.verdict,
            "hit_count": len(self.hits),
            "hits": [h.to_dict() for h in self.hits],
            "unresolved_signals": self.unresolved_signals,
            "missing_signals": self.missing_signals,
            "summary": self.summary,
        }


# ── Aligner ──────────────────────────────────────────────────────────────


class CausalAligner:
    """
    Build :class:`PatternEvidence` objects from patterns + data features.

    Typical usage::

        aligner = CausalAligner(sig_mapping, chains)
        evidence = aligner.align(
            patterns, features,
            state_timeline=[{"t": 1.0, "field": "fctb_system_state",
                             "from": 3, "to": 2}, ...],
        )
    """

    NEARBY_WINDOW_SEC = 0.5
    MIN_TRIGGER_DURATION_SEC = 0.0

    def __init__(
        self,
        signal_mapping: Optional[dict] = None,
        variable_chains: Optional[dict] = None,
    ):
        self.signal_mapping = signal_mapping or {}
        self.variable_chains = variable_chains or {}

    def align(
        self,
        patterns: Iterable[CodePattern],
        features: dict[str, TemporalFeature],
        state_timeline: Optional[list[dict]] = None,
        func_name_filter: Optional[str] = None,
    ) -> list[PatternEvidence]:
        """Return one :class:`PatternEvidence` per input pattern."""
        state_timeline = state_timeline or []
        out: list[PatternEvidence] = []
        for p in patterns:
            if func_name_filter and p.adas_function and \
                    p.adas_function.upper() != func_name_filter.upper():
                continue
            evidence = self._align_one(p, features, state_timeline)
            out.append(evidence)
        return out

    def _align_one(
        self,
        pattern: CodePattern,
        features: dict[str, TemporalFeature],
        state_timeline: list[dict],
    ) -> PatternEvidence:
        """Core routine — resolves signals, intersects runs, collects hits."""
        terms = self._parse_condition_terms(pattern.trigger_condition)

        resolution: dict[str, str] = {}
        trigger_terms: list[tuple[str, object]] = []
        unresolved: list[str] = []
        missing: list[str] = []

        for var, trigger_value in terms:
            feature_key = self._resolve_feature_key(var, features)
            if feature_key is None:
                unresolved.append(var)
                resolution[var] = "?"
                continue
            if feature_key == "__missing__":
                missing.append(var)
                resolution[var] = "数据缺失"
                continue
            resolution[var] = feature_key
            trigger_terms.append((feature_key, trigger_value))

        if not trigger_terms or unresolved or missing:
            verdict = "insufficient_data" if unresolved or missing else "unknown"
            summary = self._summarise_insufficient(pattern, unresolved, missing)
            return PatternEvidence(
                pattern=pattern, resolution=resolution, verdict=verdict,
                hits=[], unresolved_signals=unresolved,
                missing_signals=missing, summary=summary,
            )

        intervals = self._intersect_runs(trigger_terms, features)
        hits: list[PatternHit] = []
        for iv in intervals:
            if iv.duration < self.MIN_TRIGGER_DURATION_SEC:
                continue
            signals_at_start = {
                key: self._value_at(features[key], iv.t_start)
                for key, _ in trigger_terms
            }
            near = self._state_changes_near(state_timeline, iv.t_start)
            hits.append(PatternHit(
                interval=iv,
                signals_at_start=signals_at_start,
                nearby_state_changes=near,
            ))

        verdict = "triggered" if hits else "not_triggered"
        summary = self._summarise(pattern, hits, trigger_terms, features)
        return PatternEvidence(
            pattern=pattern, resolution=resolution, verdict=verdict,
            hits=hits, summary=summary,
        )

    # ── Condition parsing ────────────────────────────────────────────────

    _NOT_RE = re.compile(r'!\s*(?!=)\s*([A-Za-z_][\w.]*)')
    _EQ_RE = re.compile(
        r'([A-Za-z_][\w.]*)\s*==\s*([A-Za-z_0-9.]+)'
    )
    _NEQ_RE = re.compile(
        r'([A-Za-z_][\w.]*)\s*!=\s*([A-Za-z_0-9.]+)'
    )

    def _parse_condition_terms(self, cond: str) -> list[tuple[str, object]]:
        """
        Translate a C boolean expression into ``[(variable, trigger_value)]``.

        Examples:
            ``!A && !B``              -> [("A", 0), ("B", 0)]
            ``A == 0 && B == FALSE``  -> [("A", 0), ("B", 0)]
            ``flag``                  -> [("flag", "truthy")]
        """
        cond = cond.replace("\n", " ").strip()
        if not cond:
            return []

        clauses = re.split(r'\s*&&\s*', cond)
        out: list[tuple[str, object]] = []
        seen: set[str] = set()

        for clause in clauses:
            clause = clause.strip("() ")
            if not clause:
                continue

            m = self._NOT_RE.match(clause)
            if m:
                var = m.group(1)
                if var not in seen:
                    out.append((var, 0))
                    seen.add(var)
                continue

            m = self._EQ_RE.match(clause)
            if m:
                var = m.group(1)
                value = self._normalise_literal(m.group(2))
                if var not in seen:
                    out.append((var, value))
                    seen.add(var)
                continue

            m = self._NEQ_RE.match(clause)
            if m:
                var = m.group(1)
                value = self._normalise_literal(m.group(2))
                if var not in seen:
                    out.append((var, ("!=", value)))
                    seen.add(var)
                continue

            var_match = re.match(r'([A-Za-z_][\w.]*)', clause)
            if var_match:
                var = var_match.group(1)
                if var not in seen:
                    out.append((var, "truthy"))
                    seen.add(var)

        return out

    @staticmethod
    def _normalise_literal(tok: str) -> object:
        upper = tok.upper()
        if upper in ("TRUE",):
            return 1
        if upper in ("FALSE",):
            return 0
        try:
            return int(tok)
        except ValueError:
            try:
                return float(tok)
            except ValueError:
                return tok

    # ── Signal resolution ────────────────────────────────────────────────

    def _resolve_feature_key(
        self, var: str, features: dict[str, TemporalFeature],
    ) -> Optional[str]:
        """
        Map a C identifier to a key in ``features``.

        Returns:
            * an existing key on success,
            * ``"__missing__"`` when a CAN signal was resolved but its
              data is not present in ``features``,
            * ``None`` when the variable could not be resolved at all.
        """
        if var in features:
            return var

        last = var.split(".")[-1]
        if last in features:
            return last

        for key in features:
            if key.endswith("." + last) or key.endswith("." + var):
                return key
            if last.lower() == key.split(".")[-1].lower():
                return key

        can_candidates = self._resolve_to_can(var)
        if not can_candidates:
            return None

        for can_name in can_candidates:
            if can_name in features:
                return can_name
            core = can_name.split("_0x")[0].lower()
            for key in features:
                leaf = key.split(".")[-1].lower()
                if leaf == can_name.lower() or leaf.split("_0x")[0] == core:
                    return key

        return "__missing__"

    def _resolve_to_can(self, var: str) -> list[str]:
        """Thin wrapper around :func:`signal_mapper.resolve_internal_to_can`."""
        if not self.signal_mapping:
            return []
        try:
            from .signal_mapper import resolve_internal_to_can
        except Exception:
            return []
        return resolve_internal_to_can(var, self.signal_mapping, self.variable_chains)

    # ── Run intersection ─────────────────────────────────────────────────

    def _intersect_runs(
        self,
        trigger_terms: list[tuple[str, object]],
        features: dict[str, TemporalFeature],
    ) -> list[Interval]:
        """
        Intersect "runs at trigger value" across all trigger terms.

        Runs that satisfy ``trigger_value`` are computed per term, then
        merged using a classic sweep-line algorithm.
        """
        per_term_intervals: list[list[Interval]] = []
        for key, trigger in trigger_terms:
            feature = features[key]
            matching_runs = self._runs_matching_trigger(feature, trigger)
            per_term_intervals.append([
                Interval(r.t_start, r.t_end) for r in matching_runs
            ])

        if not per_term_intervals:
            return []

        current = per_term_intervals[0]
        for other in per_term_intervals[1:]:
            current = self._intersect_two(current, other)
            if not current:
                break
        return current

    @staticmethod
    def _runs_matching_trigger(feature: TemporalFeature, trigger):
        if isinstance(trigger, tuple) and trigger and trigger[0] == "!=":
            target = trigger[1]
            return [r for r in feature.runs if r.value != target]
        if trigger == "truthy":
            return [r for r in feature.runs if r.value not in (0, 0.0, False, None)]
        return [r for r in feature.runs if r.value == trigger]

    @staticmethod
    def _intersect_two(a: list[Interval], b: list[Interval]) -> list[Interval]:
        out: list[Interval] = []
        i = j = 0
        while i < len(a) and j < len(b):
            s = max(a[i].t_start, b[j].t_start)
            e = min(a[i].t_end, b[j].t_end)
            if e > s:
                out.append(Interval(s, e))
            if a[i].t_end < b[j].t_end:
                i += 1
            else:
                j += 1
        return out

    # ── Context gathering ────────────────────────────────────────────────

    def _value_at(self, feature: TemporalFeature, t: float) -> object:
        """
        Return the signal value at time ``t``.

        At a run boundary (``t == r.t_end`` which also equals the next
        run's ``t_start``) we prefer the *next* run. Without this, the
        intersection start ``t_start`` of a newly-entered run would pick
        up the *previous* run's value and mislabel the hit.
        """
        if not feature.runs:
            return None

        for i, r in enumerate(feature.runs):
            is_last = (i == len(feature.runs) - 1)
            if is_last:
                if r.t_start <= t <= r.t_end:
                    return r.value
            else:
                if r.t_start <= t < r.t_end:
                    return r.value

        if t <= feature.runs[0].t_start:
            return feature.runs[0].value
        return feature.runs[-1].value

    def _state_changes_near(
        self, timeline: list[dict], t: float,
    ) -> list[dict]:
        hits: list[dict] = []
        for item in timeline:
            t_item = item.get("t")
            if t_item is None:
                continue
            if abs(t_item - t) <= self.NEARBY_WINDOW_SEC:
                hits.append({
                    "t": round(t_item, 3),
                    "field": item.get("field", "?"),
                    "from": item.get("from"),
                    "to": item.get("to"),
                    "dt_ms": round((t_item - t) * 1000, 1),
                })
        return hits

    # ── Narrative ────────────────────────────────────────────────────────

    def _summarise_insufficient(
        self, pattern: CodePattern,
        unresolved: list[str], missing: list[str],
    ) -> str:
        if unresolved:
            return (f"无法判定：未能解析 {', '.join(unresolved)} 到 CAN 信号，"
                    f"建议补充 variable_chains 或确认变量拼写。")
        if missing:
            return (f"无法判定：{', '.join(missing)} 映射到的 CAN 信号不在数据中，"
                    f"无法验证模式是否触发。")
        return "无法判定：条件无法解析。"

    def _summarise(
        self,
        pattern: CodePattern,
        hits: list[PatternHit],
        trigger_terms: list[tuple[str, object]],
        features: dict[str, TemporalFeature],
    ) -> str:
        if not hits:
            return (f"✅ 模式 {pattern.pattern_type} 未触发："
                    f"条件 `{pattern.trigger_condition[:60]}` 在数据窗口内"
                    f"从未同时满足。")
        brief = sum(1 for h in hits if h.interval.duration < 0.5)
        earliest = min(h.interval.t_start for h in hits)
        longest = max(h.interval.duration for h in hits)
        var_summary = ", ".join(
            f"{self._short(k)}→值={self._describe_trigger(t)}"
            for k, t in trigger_terms
        )
        msg = (f"⚠️ 模式 {pattern.pattern_type} 在数据中触发 {len(hits)} 次 "
               f"(首次 t={earliest:.2f}s, 最长持续 {longest*1000:.0f}ms, "
               f"其中短脉冲{brief}次)。")
        if pattern.adas_function:
            msg += f" 影响功能：{pattern.adas_function}。"
        msg += f"\n  → 触发信号：{var_summary}"
        if pattern.consequence_variables:
            msg += (f"\n  → 清零副作用：{', '.join(pattern.consequence_variables)}"
                    " — 累积器/保持标志被重置。")
        return msg

    @staticmethod
    def _describe_trigger(trigger) -> str:
        if isinstance(trigger, tuple) and trigger and trigger[0] == "!=":
            return f"!= {trigger[1]}"
        if trigger == "truthy":
            return "非零"
        return str(trigger)

    @staticmethod
    def _short(key: str) -> str:
        return key.split(".")[-1] if "." in key else key


# ── Formatting ───────────────────────────────────────────────────────────


def format_evidence_block(
    evidence_list: list[PatternEvidence],
    max_hits_per_pattern: int = 5,
) -> str:
    """Condense evidence into a markdown block suitable for expert prompts."""
    if not evidence_list:
        return "(无代码模式证据)"

    triggered = [e for e in evidence_list if e.verdict == "triggered"]
    silent = [e for e in evidence_list if e.verdict == "not_triggered"]
    unresolved = [e for e in evidence_list if e.verdict not in ("triggered", "not_triggered")]

    parts: list[str] = []
    parts.append("### 代码模式 × 数据时序 因果对齐结果")
    parts.append(f"- 总模式数: {len(evidence_list)} "
                 f"| 触发: {len(triggered)} | 未触发: {len(silent)} | 无法判定: {len(unresolved)}")

    if triggered:
        parts.append("\n#### ⚠️ 已触发模式（高优先级）")
        for e in triggered:
            p = e.pattern
            parts.append(
                f"\n**{p.pattern_type}** @ `{p.file}:{p.line_start}-{p.line_end}` "
                f"({p.function or '?'}) · 功能 {p.adas_function or '?'}"
            )
            parts.append(f"  触发条件: `{p.trigger_condition[:100]}`")
            parts.append(f"  清零副作用: {', '.join(p.consequence_variables)}")
            parts.append(f"  {e.summary}")

            for h in e.hits[:max_hits_per_pattern]:
                parts.append(
                    f"    · t=[{h.interval.t_start:.3f}, {h.interval.t_end:.3f}]s "
                    f"({h.interval.duration*1000:.0f}ms) "
                    f"信号={h.signals_at_start}"
                )
                if h.nearby_state_changes:
                    near = "; ".join(
                        f"{c['field']}: {c['from']}→{c['to']} (Δ{c['dt_ms']:+.0f}ms)"
                        for c in h.nearby_state_changes[:3]
                    )
                    parts.append(f"      附近状态变化: {near}")
            if len(e.hits) > max_hits_per_pattern:
                parts.append(f"    ...+{len(e.hits) - max_hits_per_pattern} 更多触发点")

    if silent:
        parts.append("\n#### ✅ 未触发模式")
        for e in silent[:10]:
            p = e.pattern
            parts.append(
                f"  - {p.pattern_type} @ {p.file}:{p.line_start} "
                f"({p.adas_function or '?'}) — {e.summary}"
            )

    if unresolved:
        parts.append("\n#### ❓ 无法判定的模式")
        for e in unresolved[:10]:
            p = e.pattern
            parts.append(
                f"  - {p.pattern_type} @ {p.file}:{p.line_start} "
                f"({p.adas_function or '?'}) — {e.summary}"
            )

    return "\n".join(parts)


def state_timeline_from_transitions(transitions: list[dict]) -> list[dict]:
    """Adapt :func:`FrameAnalyzer.extract_evidence` transitions to aligner format."""
    out = []
    for tr in transitions:
        if "t" not in tr:
            continue
        out.append({
            "t": tr["t"],
            "field": tr.get("field", ""),
            "from": tr.get("from"),
            "to": tr.get("to"),
        })
    return out
