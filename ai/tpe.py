# -*- coding: utf-8 -*-
"""
Temporal Pattern Engine facade
==============================

The three primitives that make up the TPE are deliberately small and
decoupled:

* :class:`ai.pattern_extractor.PatternExtractor` — code side
* :class:`ai.temporal_analyzer.TemporalAnalyzer` — data side
* :class:`ai.causal_aligner.CausalAligner`       — glue

For day-to-day usage the orchestrator and frame analyzer would rather
treat the engine as a single black box that takes a ``FrameStore`` and a
set of patterns and returns "here is the evidence".

``TemporalPatternEngine`` is that facade. It:

* selects the right CAN signals to analyse based on the pattern catalogue,
* pulls timelines from the :class:`FrameStore` lazily,
* computes :class:`TemporalFeature` objects for every participating signal,
* hands everything to :class:`CausalAligner`, and
* surfaces a single structured result for downstream consumers.

The facade never creates ad-hoc regexes or touches the AI router — it
only stitches together deterministic pieces.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from .causal_aligner import (
    CausalAligner, PatternEvidence, format_evidence_block,
    state_timeline_from_transitions,
)
from .pattern_extractor import (
    CodePattern, PatternExtractor, summarise_patterns,
)
from .temporal_analyzer import (
    TemporalAnalyzer, TemporalFeature, SignalTimeline,
    format_temporal_features,
)


__all__ = ["TPEResult", "TemporalPatternEngine"]


@dataclass
class TPEResult:
    """Bundle of everything the engine produces for one case."""

    patterns: list[CodePattern]
    features: dict[str, TemporalFeature]
    evidence: list[PatternEvidence]
    unresolved_variables: set[str] = field(default_factory=set)
    internal_only_variables: set[str] = field(default_factory=set)
    missing_can_signals: set[str] = field(default_factory=set)
    notes: list[str] = field(default_factory=list)

    @property
    def triggered_count(self) -> int:
        return sum(1 for e in self.evidence if e.verdict == "triggered")

    @property
    def has_triggers(self) -> bool:
        return self.triggered_count > 0

    def to_expert_block(self) -> str:
        """Compact markdown block for injection into expert prompts.

        ``internal_only_variables`` (FIFO buffers, counters, local temps) are
        deliberately *not* surfaced here — they're noise for the expert
        panel. They remain on the result object for diagnostics / logging.
        """
        parts: list[str] = [
            "## ★★ 代码模式 × 数据时序 因果对齐 (TPE) ★★"
        ]
        if self.notes:
            parts.append("说明: " + "; ".join(self.notes))
        parts.append(format_evidence_block(self.evidence))
        if self.features:
            parts.append("\n" + format_temporal_features(self.features))
        if self.unresolved_variables:
            parts.append(
                "\n⚠ 未能解析为 CAN 信号的内部变量: "
                + ", ".join(sorted(self.unresolved_variables))
            )
        if self.missing_can_signals:
            parts.append(
                "\n⚠ CAN 信号在数据中缺失: "
                + ", ".join(sorted(self.missing_can_signals))
            )
        return "\n".join(parts)


class TemporalPatternEngine:
    """High-level orchestrator for the three TPE components."""

    def __init__(
        self,
        source_root: Path,
        cache_dir: Optional[Path] = None,
        signal_mapping: Optional[dict] = None,
        variable_chains: Optional[dict] = None,
        output_mapping: Optional[dict] = None,
        output_aliases: Optional[dict] = None,
    ):
        self.source_root = Path(source_root)
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.signal_mapping = signal_mapping or {}
        self.variable_chains = variable_chains or {}
        # WriteSignal-side data: curated aliases from L6 output_chain learner
        # (``output_aliases``) + heuristic reverse index from RteComMapping
        # expressions (``output_mapping.expr_to_can``). Both optional — pipeline
        # still works without them, just with more variables marked unresolved.
        self.output_mapping = output_mapping or {}
        self.output_aliases = output_aliases or {}
        self.pattern_extractor = PatternExtractor(
            source_root=self.source_root, cache_dir=self.cache_dir,
        )
        self.temporal_analyzer = TemporalAnalyzer()
        self.aligner = CausalAligner(
            signal_mapping=self.signal_mapping,
            variable_chains=self.variable_chains,
        )

    # ── Main entry points ────────────────────────────────────────────────

    def run(
        self,
        store,
        func_name: Optional[str] = None,
        extra_patterns: Optional[list[CodePattern]] = None,
        state_transitions: Optional[list[dict]] = None,
        time_window: Optional[tuple[float, float]] = None,
    ) -> TPEResult:
        """
        End-to-end pipeline: extract patterns, load timelines, align.

        Parameters
        ----------
        store : FrameStore-like
            Provides ``query_can_by_name`` / ``get_signal_inventory``.
        func_name : str, optional
            Filter patterns whose ``adas_function`` matches (case-insensitive).
            ``None`` keeps all patterns, which is useful when we want the
            aligner to see "every HoldRelease in the tree". In practice we
            filter by ``func_name`` to keep cost low.
        extra_patterns : list[CodePattern], optional
            Patterns supplied from outside (e.g. unit tests).
        state_transitions : list[dict], optional
            The ``state_transitions`` array from
            :meth:`FrameAnalyzer.extract_evidence`.
        time_window : (float, float), optional
            Seconds range used to clip CAN timelines before analysis.
            Without this we end up analysing the full recording which is
            usually fine but wastes memory on long bags.
        """
        patterns = self.pattern_extractor.extract_all(use_cache=True)
        if extra_patterns:
            patterns = list(patterns) + list(extra_patterns)

        filtered = self._filter_patterns(patterns, func_name)
        required_vars = self._collect_required_variables(filtered)
        required_signals, unresolved, internal_only = \
            self._resolve_required_can_signals(required_vars)

        features, missing = self._load_features(
            store, required_signals, time_window=time_window,
        )

        timeline = state_timeline_from_transitions(state_transitions or [])
        evidence = self.aligner.align(
            patterns=filtered, features=features,
            state_timeline=timeline, func_name_filter=None,
        )

        notes: list[str] = []
        notes.append(
            f"pattern_total={len(patterns)}, "
            f"used={len(filtered)}, "
            f"triggered={sum(1 for e in evidence if e.verdict=='triggered')}"
        )
        if func_name:
            notes.append(f"func_filter={func_name}")
        if time_window:
            notes.append(f"time_window={time_window}")
        if internal_only:
            notes.append(f"internal_only_vars={len(internal_only)}")

        return TPEResult(
            patterns=filtered,
            features=features,
            evidence=evidence,
            unresolved_variables=unresolved,
            internal_only_variables=internal_only,
            missing_can_signals=missing,
            notes=notes,
        )

    # ── Pattern filtering ────────────────────────────────────────────────

    def _filter_patterns(
        self, patterns: Iterable[CodePattern], func_name: Optional[str],
    ) -> list[CodePattern]:
        if not func_name:
            return list(patterns)
        target = func_name.upper()
        return [
            p for p in patterns
            if not p.adas_function or p.adas_function.upper() == target
        ]

    # ── Required signal resolution ───────────────────────────────────────

    def _collect_required_variables(
        self, patterns: Iterable[CodePattern],
    ) -> list[str]:
        seen: dict[str, None] = {}
        for p in patterns:
            for v in p.trigger_variables:
                leaf = v.split(".")[-1]
                if leaf and leaf not in seen:
                    seen[leaf] = None
                if v not in seen:
                    seen[v] = None
        return list(seen)

    def _resolve_required_can_signals(
        self, variables: list[str],
    ) -> tuple[list[str], set[str], set[str]]:
        """
        Map internal variables to CAN signal names using
        ``signal_mapper.resolve_internal_to_can``, which now consults both
        Read and Write directions (plus L6 ``output_chain`` aliases).

        Anything that still comes back empty is then sent through
        ``classify_unresolved`` to split FIFO-buffer / counter style
        *intentionally internal* variables from truly unknown ones. The
        expert prompt only sees the latter.

        Returns
        -------
        (resolved_can_signals, unresolved_variable_names, internal_only_variable_names)
        """
        if not variables:
            return [], set(), set()
        try:
            from .signal_mapper import (
                resolve_internal_to_can, classify_unresolved,
            )
        except Exception:
            return [], set(variables), set()

        resolved: list[str] = []
        unresolved: set[str] = set()
        internal_only: set[str] = set()
        seen: set[str] = set()
        for var in variables:
            cans = resolve_internal_to_can(
                var, self.signal_mapping, self.variable_chains,
                output_mapping=self.output_mapping,
                output_aliases=self.output_aliases,
            )
            if not cans:
                if classify_unresolved(var) == "internal_only":
                    internal_only.add(var)
                else:
                    unresolved.add(var)
                continue
            for c in cans:
                if c not in seen:
                    resolved.append(c)
                    seen.add(c)
        return resolved, unresolved, internal_only

    # ── Feature loading ──────────────────────────────────────────────────

    def _load_features(
        self,
        store,
        can_signal_names: list[str],
        time_window: Optional[tuple[float, float]] = None,
    ) -> tuple[dict[str, TemporalFeature], set[str]]:
        """
        For each CAN signal name, locate its parent message, pull the
        timeline, optionally clip to ``time_window``, and return the
        resulting :class:`TemporalFeature` keyed by the CAN signal name.
        """
        if not can_signal_names:
            return {}, set()

        inventory = store.get_signal_inventory() or []
        signal_to_message: dict[str, str] = {}
        for item in inventory:
            msg_name = item.get("message_name") or "?"
            for sig in item.get("signals", []):
                signal_to_message.setdefault(sig, msg_name)

        missing: set[str] = set()
        features: dict[str, TemporalFeature] = {}

        for can_sig in can_signal_names:
            msg_name = signal_to_message.get(can_sig)
            if not msg_name:
                msg_name = self._fuzzy_message_lookup(can_sig, signal_to_message)
            if not msg_name:
                missing.add(can_sig)
                continue

            tl = self.temporal_analyzer.load_can_signal(store, msg_name, can_sig)
            if not tl.samples and self._normalise_key(can_sig) != can_sig:
                tl = self.temporal_analyzer.load_can_signal(
                    store, msg_name, self._normalise_key(can_sig),
                )
            if not tl.samples:
                for real_sig in signal_to_message:
                    if self._normalise_key(real_sig) == self._normalise_key(can_sig):
                        tl = self.temporal_analyzer.load_can_signal(
                            store, signal_to_message[real_sig], real_sig,
                        )
                        if tl.samples:
                            can_sig = real_sig
                        break

            if not tl.samples:
                missing.add(can_sig)
                continue

            if time_window:
                tl = self._clip_timeline(tl, time_window)

            feature = self.temporal_analyzer.analyze(tl)
            if feature is None:
                missing.add(can_sig)
                continue
            features[can_sig] = feature

        return features, missing

    @staticmethod
    def _clip_timeline(
        tl: SignalTimeline, time_window: tuple[float, float],
    ) -> SignalTimeline:
        """
        Clip a timeline to ``time_window`` without losing the initial value.

        CAN signals are often sparse: the value is only reported on change,
        so a ``time_window`` that starts *after* the last change would be
        empty. We therefore:

        * keep every sample with ``t_start <= t <= t_end``;
        * additionally prepend the last sample with ``t < t_start`` (stamped
          at ``t_start``) so the analyser sees the correct baseline value.

        If the result is still empty we fall back to the full timeline —
        always better to over-report than to silently drop a signal.
        """
        t0, t1 = time_window
        inside: list[tuple[float, object]] = []
        carry: tuple[float, object] | None = None
        for (t, v) in tl.samples:
            if t < t0:
                carry = (t0, v)
            elif t0 <= t <= t1:
                inside.append((t, v))
            else:
                break
        clipped: list[tuple[float, object]] = []
        if carry and (not inside or inside[0][0] > t0):
            clipped.append(carry)
        clipped.extend(inside)
        if not clipped:
            return tl
        return SignalTimeline(name=tl.name, samples=clipped)

    @staticmethod
    def _fuzzy_message_lookup(can_sig: str, signal_to_message: dict[str, str]) -> str:
        """Locate a message via case-insensitive / ``_0x...`` stripped match."""
        norm = TemporalPatternEngine._normalise_key(can_sig)
        for sig, msg in signal_to_message.items():
            if TemporalPatternEngine._normalise_key(sig) == norm:
                return msg
        return ""

    @staticmethod
    def _normalise_key(name: str) -> str:
        if "_0x" in name:
            name = name.split("_0x")[0]
        return name.lower()

    # ── Re-exports for callers that only want narration ─────────────────

    @staticmethod
    def format_evidence(evidence: list[PatternEvidence]) -> str:
        return format_evidence_block(evidence)

    @staticmethod
    def format_features(features: dict[str, TemporalFeature]) -> str:
        return format_temporal_features(features)

    @staticmethod
    def format_patterns(patterns: list[CodePattern]) -> str:
        return summarise_patterns(patterns)
