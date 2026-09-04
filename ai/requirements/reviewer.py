# -*- coding: utf-8 -*-
"""
Requirement reviewer (M8): audit a :class:`~core.materials.StructuredRequirementSet`
for structural and semantic defects.

Deterministic checks (always run, no services required):

* **completeness** — every requirement has an id, a statement, and at least one
  condition or normalized logic / linked signal.
* **duplicate ids** — surfaced from the loader's ``duplicate_of`` marker.
* **contradiction** — the same signal constrained to an impossible numeric range
  (e.g. ``>= 150`` and ``<= 30``) or two conflicting ``==`` values.
* **testability** — at least one measurable condition (valid operator + value).
* **dbc-observability** — every ``expected_output_signal`` and condition signal
  exists in the injected ``signal_mapping``.

An optional single LLM consistency pass runs only when a ``router`` is injected;
the deterministic path is fully functional without one.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from core.materials import RequirementSpec, StructuredRequirementSet

from .loader import VALID_OPERATORS

log = logging.getLogger(__name__)

_SEVERITIES = ("error", "warning", "info")
_CONDITION_KEYS = ("preconditions", "activation_conditions", "conditions")
_LOWER_OPS = {">", ">="}
_UPPER_OPS = {"<", "<="}


class RequirementReviewer:
    """Audit requirements for structural/semantic defects (M8)."""

    def __init__(self, router: Any = None, signal_mapping: dict | None = None) -> None:
        self.router = router
        self.signal_mapping = signal_mapping or {}
        self._known_signals = self._build_known_signals(self.signal_mapping)

    # ── public API ─────────────────────────────────────────────────────

    def review(self, req_set: StructuredRequirementSet | dict | None) -> dict:
        """Run all checks and return ``{summary, issues}``."""
        specs = self._as_specs(req_set)
        issues: list[dict] = []
        for spec in specs:
            issues.extend(self._check_completeness(spec))
            issues.extend(self._check_schema_validation(spec))
            issues.extend(self._check_duplicate(spec))
            issues.extend(self._check_thresholds(spec))
            issues.extend(self._check_testability(spec))
            issues.extend(self._check_dbc(spec))

        if self.router is not None and specs:
            try:
                issues.extend(self._llm_consistency(specs))
            except Exception as exc:  # noqa: BLE001 - LLM guard, never fatal
                log.debug("LLM consistency pass skipped: %s", exc)

        by_severity = {s: 0 for s in _SEVERITIES}
        for it in issues:
            sev = it.get("severity", "info")
            by_severity[sev] = by_severity.get(sev, 0) + 1

        return {
            "summary": {
                "n_reqs": len(specs),
                "n_issues": len(issues),
                "by_severity": by_severity,
            },
            "issues": issues,
        }

    # ── deterministic checks ───────────────────────────────────────────

    def _check_completeness(self, spec: RequirementSpec) -> list[dict]:
        rid = spec.requirement_id or "<unknown>"
        out: list[dict] = []
        if not spec.requirement_id:
            out.append(self._issue(rid, "error", "completeness", "missing requirement_id"))
        if not (spec.statement or "").strip():
            out.append(self._issue(rid, "warning", "completeness", "missing statement/description"))
        if not self._conditions(spec) and not (spec.normalized_logic or spec.linked_signals):
            out.append(self._issue(rid, "warning", "completeness", "no conditions or linked signals"))
        return out

    def _check_duplicate(self, spec: RequirementSpec) -> list[dict]:
        original = (spec.metadata or {}).get("duplicate_of")
        if original:
            return [self._issue(
                spec.requirement_id, "warning", "duplicate",
                f"duplicate requirement id '{original}'",
            )]
        return []

    def _check_schema_validation(self, spec: RequirementSpec) -> list[dict]:
        problems = (spec.metadata or {}).get("schema_problems") or []
        if not isinstance(problems, list):
            return []
        rid = spec.requirement_id or "<unknown>"
        out: list[dict] = []
        for problem in problems:
            message = str(problem).strip()
            if not message:
                continue
            severity = "warning" if message == "no conditions defined" else "error"
            out.append(self._issue(rid, severity, "schema-validation", message))
        return out

    def _check_thresholds(self, spec: RequirementSpec) -> list[dict]:
        rid = spec.requirement_id or "<unknown>"
        out: list[dict] = []
        by_signal: dict[str, list[dict]] = {}
        for c in self._conditions(spec):
            alias = c.get("signal_alias") or c.get("signal")
            if alias:
                by_signal.setdefault(str(alias), []).append(c)

        for sig, conds in by_signal.items():
            lower: float | None = None  # greatest lower bound
            upper: float | None = None  # least upper bound
            eq_values: set = set()
            for c in conds:
                op = c.get("operator")
                if op == "==":
                    eq_values.add(c.get("value"))
                val = self._num(c.get("value"))
                if val is None:
                    continue
                if op in _LOWER_OPS:
                    lower = val if lower is None else max(lower, val)
                elif op in _UPPER_OPS:
                    upper = val if upper is None else min(upper, val)
            if lower is not None and upper is not None and lower > upper:
                out.append(self._issue(
                    rid, "error", "contradiction",
                    f"signal {sig}: lower bound {lower} > upper bound {upper}",
                ))
            if len(eq_values) > 1:
                out.append(self._issue(
                    rid, "error", "contradiction",
                    f"signal {sig}: conflicting equality values "
                    f"{sorted(str(v) for v in eq_values)}",
                ))
        return out

    def _check_testability(self, spec: RequirementSpec) -> list[dict]:
        rid = spec.requirement_id or "<unknown>"
        for c in self._conditions(spec):
            if c.get("operator") in VALID_OPERATORS and "value" in c:
                return []
        if (spec.normalized_logic or "").strip():
            return []
        return [self._issue(rid, "warning", "testability", "no measurable condition")]

    def _check_dbc(self, spec: RequirementSpec) -> list[dict]:
        if not self._known_signals:
            return []  # cannot verify observability without a mapping
        rid = spec.requirement_id or "<unknown>"
        out: list[dict] = []
        checked: set[str] = set()
        for sig in self._signals_to_check(spec):
            if sig in checked:
                continue
            checked.add(sig)
            if sig not in self._known_signals:
                out.append(self._issue(
                    rid, "error", "dbc-observability",
                    f"signal {sig} not found in DBC/signal mapping",
                ))
        return out

    # ── optional LLM pass ──────────────────────────────────────────────

    def _llm_consistency(self, specs: list[RequirementSpec]) -> list[dict]:
        system = (
            "You are an ADAS requirements auditor. Identify logical "
            "inconsistencies, ambiguities, or overlaps across the requirement "
            "set. Respond with a JSON array of objects "
            '{"req_id": str, "severity": "error|warning|info", "message": str}. '
            "Return [] if there are none."
        )
        prompt = "Requirements:\n" + self._compact_summary(specs)
        raw = self.router.complex(prompt, system=system, max_tokens=2048)
        content = raw.get("content", "") if isinstance(raw, dict) else str(raw)

        out: list[dict] = []
        for item in self._parse_json_array(content):
            if not isinstance(item, dict):
                continue
            sev = item.get("severity", "info")
            if sev not in _SEVERITIES:
                sev = "info"
            out.append(self._issue(
                str(item.get("req_id", "")), sev, "llm-consistency",
                str(item.get("message", "")).strip(),
            ))
        return out

    # ── helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _issue(req_id: str, severity: str, category: str, message: str) -> dict:
        return {
            "req_id": req_id,
            "severity": severity,
            "category": category,
            "message": message,
        }

    @staticmethod
    def _as_specs(req_set) -> list[RequirementSpec]:
        if req_set is None:
            return []
        reqs = getattr(req_set, "requirements", None)
        if reqs is None and isinstance(req_set, dict):
            reqs = req_set
        return list(reqs.values()) if reqs else []

    @staticmethod
    def _conditions(spec: RequirementSpec) -> list[dict]:
        md = spec.metadata or {}
        conds: list[dict] = []
        for key in _CONDITION_KEYS:
            val = md.get(key)
            if isinstance(val, list):
                conds.extend(c for c in val if isinstance(c, dict))
        return conds

    def _signals_to_check(self, spec: RequirementSpec) -> list[str]:
        sigs: list[str] = []
        for c in self._conditions(spec):
            alias = c.get("signal_alias") or c.get("signal")
            if alias:
                sigs.append(str(alias))
        expected = (spec.metadata or {}).get("expected_output_signal")
        if expected:
            sigs.append(str(expected))
        sigs.extend(spec.linked_signals or [])
        return sigs

    @staticmethod
    def _num(value: Any) -> float | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                return None
        return None

    @staticmethod
    def _compact_summary(specs: list[RequirementSpec]) -> str:
        lines: list[str] = []
        for s in specs:
            md = s.metadata or {}
            conds: list[str] = []
            for key in ("preconditions", "activation_conditions"):
                for c in md.get(key) or []:
                    if isinstance(c, dict):
                        conds.append(
                            f"{c.get('signal_alias', '?')} "
                            f"{c.get('operator', '?')} {c.get('value', '?')}"
                        )
            lines.append(
                f"- {s.requirement_id}: {(s.statement or '')[:120]} "
                f"| conds: {'; '.join(conds) or 'none'} "
                f"| out: {md.get('expected_output_signal', 'none')}"
            )
        return "\n".join(lines)

    @staticmethod
    def _parse_json_array(text: str) -> list:
        text = (text or "").strip()
        if not text:
            return []
        if text.startswith("```"):
            text = text.strip("`")
            nl = text.find("\n")
            if nl != -1:
                text = text[nl + 1:]
        start, end = text.find("["), text.rfind("]")
        if start == -1 or end == -1 or end <= start:
            return []
        try:
            data = json.loads(text[start:end + 1])
        except (json.JSONDecodeError, ValueError):
            return []
        return data if isinstance(data, list) else []

    @staticmethod
    def _build_known_signals(signal_mapping: dict) -> set[str]:
        known: set[str] = set()
        if not isinstance(signal_mapping, dict):
            return known
        c2i = signal_mapping.get("can_to_internal")
        if isinstance(c2i, dict):
            known.update(k for k in c2i if isinstance(k, str))
        i2c = signal_mapping.get("internal_to_can")
        if isinstance(i2c, dict):
            for vals in i2c.values():
                if isinstance(vals, list):
                    known.update(v for v in vals if isinstance(v, str))
        for m in signal_mapping.get("mappings") or []:
            if isinstance(m, dict) and isinstance(m.get("can_signal"), str):
                known.add(m["can_signal"])
        s2e = signal_mapping.get("signal_to_expr")
        if isinstance(s2e, dict):
            known.update(k for k in s2e if isinstance(k, str))
        return known
