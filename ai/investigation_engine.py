# -*- coding: utf-8 -*-
"""Deterministically join recorded data with cached source-code conditions."""
from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from engines.signal_mapper import extract_signal_mapping, resolve_internal_to_can
from .utils import ALL_FUNCTIONS


_COMPARE_RE = re.compile(
    r"(?P<op><=|>=|==|!=|<|>)\s*"
    r"(?P<value>-?(?:0[xX][0-9a-fA-F]+|(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?))"
)
_SOURCE_RE = re.compile(r"^(?P<path>.+):(?P<line>\d+)$")
_DEBUG_METADATA = {"id", "timestamp_ns", "radar_id", "frame_id"}
_MISSING_SIGNAL_NAMES = {"", "n/a", "na", "none", "unknown", "-"}


@dataclass
class InvestigationPlan:
    functions: list[str] = field(default_factory=list)
    code_symbols: list[str] = field(default_factory=list)
    can_signals: list[str] = field(default_factory=list)
    question_type: str = "unknown"
    need_code_analysis: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CodeFact:
    expression: str
    source_ref: str
    function_name: str
    file_path: str
    line: int | None
    callers: list[str] = field(default_factory=list)
    callees: list[str] = field(default_factory=list)
    snippet: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DataFact:
    source: str
    field: str
    sample_count: int
    minimum: float | None
    maximum: float | None
    start_time: float | None
    end_time: float | None
    distinct_values: list[float] = field(default_factory=list)
    windowed: bool = False
    carry_forward_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ConditionCheck:
    expression: str
    code_ref: str
    variables: list[str]
    signals: list[str]
    observation: dict[str, Any]
    result: str
    evidence_refs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class InvestigationResult:
    plan: InvestigationPlan
    analysis_windows: list[dict[str, Any]] = field(default_factory=list)
    code_facts: list[CodeFact] = field(default_factory=list)
    data_facts: list[DataFact] = field(default_factory=list)
    condition_checks: list[ConditionCheck] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        check_summary = {name: 0 for name in ("satisfied", "violated", "mixed", "unknown")}
        for item in self.condition_checks:
            check_summary[item.result] = check_summary.get(item.result, 0) + 1
        return {
            "plan": self.plan.to_dict(),
            "diagnostic_posture": {
                "ai_reasoning_required": True,
                "deterministic_checks_are_advisory": True,
            },
            "check_summary": check_summary,
            "deterministic_conclusion_available": any(
                item.result != "unknown" for item in self.condition_checks
            ),
            "analysis_windows": list(self.analysis_windows),
            "code_facts": [item.to_dict() for item in self.code_facts],
            "data_facts": [item.to_dict() for item in self.data_facts],
            "condition_checks": [item.to_dict() for item in self.condition_checks],
            "limitations": list(self.limitations),
        }

    def to_prompt_text(self, max_chars: int = 10000) -> str:
        payload = self.to_dict()
        payload["truncated"] = False
        text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        while len(text) > max_chars:
            trimmed = False
            for key in ("limitations", "code_facts", "data_facts", "condition_checks"):
                minimum = 3 if key == "condition_checks" else 0
                if len(payload[key]) > minimum:
                    payload[key].pop()
                    payload["truncated"] = True
                    trimmed = True
                    break
            if not trimmed:
                payload = {
                    "plan": payload["plan"],
                    "diagnostic_posture": payload["diagnostic_posture"],
                    "check_summary": payload["check_summary"],
                    "deterministic_conclusion_available": payload[
                        "deterministic_conclusion_available"
                    ],
                    "analysis_windows": payload["analysis_windows"][:3],
                    "condition_checks": payload["condition_checks"][:3],
                    "limitations": ["investigation evidence exceeded prompt budget"],
                    "truncated": True,
                }
            text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            if not trimmed:
                break
        return text


class EngineeringInvestigator:
    """Collect bounded code/data evidence without asking an LLM to infer facts."""

    def __init__(
        self,
        config: dict,
        project_root: str | Path,
        max_conditions: int = 15,
        codegraph_factory: Callable[[Path], Any] | None = None,
    ) -> None:
        self.config = config
        self.project_root = Path(project_root)
        self.max_conditions = max(1, int(max_conditions))
        self.codegraph_factory = codegraph_factory

    def investigate(
        self,
        store: Any,
        question: str,
        plan: dict[str, Any] | InvestigationPlan,
        signal_lookup: dict[str, dict[str, Any]],
    ) -> InvestigationResult:
        normalized = self._normalize_plan(question, plan)
        result = InvestigationResult(plan=normalized)
        limitations = result.limitations
        try:
            from config import resolve_codegraph_db, resolve_source_docs_dir
            from core.knowledge_guard import runtime_knowledge_decision

            docs_dir = resolve_source_docs_dir(self.config, self.project_root)
            chains_decision = runtime_knowledge_decision(self.config, "variable_chains")
            codegraph_decision = runtime_knowledge_decision(self.config, "codegraph")
            allowed_functions: list[str] = []
            for function in normalized.functions:
                decision = runtime_knowledge_decision(
                    self.config, f"conditions:{function.upper()}",
                )
                if decision.allowed:
                    allowed_functions.append(function)
                else:
                    limitations.append(
                        f"stale structured conditions excluded for {function.upper()}: "
                        + ", ".join(decision.reasons)
                    )
            if allowed_functions:
                conditions = self._load_conditions(
                    docs_dir, allowed_functions, limitations,
                )
            else:
                conditions = []
            mapping = self._load_or_build_mapping(docs_dir, limitations)
            if chains_decision.allowed:
                chains = self._load_json(
                    docs_dir / "variable_chains.json", {}, limitations, optional=True,
                )
            else:
                chains = {}
                limitations.append(
                    "stale variable chains excluded: "
                    + ", ".join(chains_decision.reasons)
                )
            selected = self._select_conditions(conditions, question, normalized)
            result.analysis_windows = self._derive_analysis_windows(
                store, plan, signal_lookup,
            )
            debug_columns = self._debug_columns(store)
            fact_cache: dict[tuple[str, str], tuple[DataFact, list[float]]] = {}

            for item in selected:
                try:
                    check = self._check_condition(
                        item, store, signal_lookup, mapping, chains,
                        debug_columns, fact_cache, result.analysis_windows,
                    )
                    result.condition_checks.append(check)
                except Exception as exc:
                    limitations.append(f"condition query failed: {exc}")

            result.data_facts = [fact for fact, _ in fact_cache.values()]
            if codegraph_decision.allowed:
                result.code_facts = self._build_code_facts(
                    selected,
                    resolve_codegraph_db(self.config, self.project_root),
                    limitations,
                )
            else:
                limitations.append(
                    "stale CodeGraph excluded: "
                    + ", ".join(codegraph_decision.reasons)
                )
        except Exception as exc:
            limitations.append(f"investigation partially failed: {exc}")

        if normalized.need_code_analysis and not result.condition_checks:
            limitations.append("no structured code conditions were available for this question")
        if result.condition_checks:
            if any(
                item.observation.get("mapping_status") == "unmapped"
                for item in result.condition_checks
            ):
                limitations.append("some code variables could not be mapped to recorded signals")
            if any(
                item.observation.get("mapping_status") == "transformed_signal_mapping"
                for item in result.condition_checks
            ):
                limitations.append(
                    "some mapped signals require code transforms and cannot be compared as raw values"
                )
            if any(
                item.observation.get("mapping_status") == "partial_enum_mapping"
                for item in result.condition_checks
            ):
                limitations.append("some enum mappings did not cover all recorded values")
            if all(item.result == "unknown" for item in result.condition_checks):
                limitations.append(
                    "no code condition could be deterministically verified from this case data"
                )
        if result.data_facts and all(item.sample_count == 0 for item in result.data_facts):
            limitations.append("mapped data fields have no recorded samples")
        result.limitations = _dedupe(limitations)
        return result

    def _load_or_build_mapping(
        self, docs_dir: Path, limitations: list[str]
    ) -> dict[str, Any]:
        path = docs_dir / "signal_mapping.json"
        mapping = self._load_json(path, {}, limitations, optional=True)
        project = self.config.get("project", {})
        source_root_value = (
            project.get("source_code")
            or project.get("source_root")
            or self.config.get("source_context", {}).get("source_root")
        )
        candidates = list(project.get("source_domains", {}).get("signal_chain", []))
        candidates.extend(project.get("key_source_files", []))
        rte_file = next(
            (
                str(value) for value in candidates
                if str(value).lower().endswith(".c")
                and "rtecommapping" in Path(str(value)).name.lower()
            ),
            "",
        )
        if source_root_value and rte_file:
            try:
                mapping = extract_signal_mapping(
                    Path(source_root_value), docs_dir, rte_file=rte_file,
                )
            except Exception as exc:
                limitations.append(f"signal mapping generation failed: {exc}")
        if mapping.get("mapping_count", len(mapping.get("mappings", []))) <= 0:
            limitations.append("signal mapping unavailable or empty; code variables remain unknown")
        return mapping

    @staticmethod
    def _normalize_plan(
        question: str, plan: dict[str, Any] | InvestigationPlan
    ) -> InvestigationPlan:
        if isinstance(plan, InvestigationPlan):
            raw = plan.to_dict()
        else:
            raw = plan or {}
        functions = _string_list(raw.get("functions"))
        upper_question = question.upper()
        for name in ALL_FUNCTIONS:
            if name in upper_question and name not in functions:
                functions.append(name)
        functions = [name.upper() for name in functions if name.upper() in ALL_FUNCTIONS]
        code_symbols = _string_list(raw.get("code_symbols"))
        can_signals: list[str] = []
        for item in raw.get("can_signals", []) or []:
            name = item.get("signal_name") if isinstance(item, dict) else item
            if name:
                can_signals.append(str(name))
        need_code = raw.get("need_code_analysis")
        if need_code is None:
            need_code = bool(functions or code_symbols)
        return InvestigationPlan(
            functions=_dedupe(functions),
            code_symbols=_dedupe(code_symbols),
            can_signals=_dedupe(can_signals),
            question_type=str(raw.get("query_type") or raw.get("question_type") or "unknown"),
            need_code_analysis=bool(need_code),
        )

    def _load_conditions(
        self, docs_dir: Path, functions: list[str], limitations: list[str]
    ) -> list[dict[str, Any]]:
        flattened: list[dict[str, Any]] = []
        for func in functions:
            path = docs_dir / f"{func}_conditions.json"
            if not path.exists():
                limitations.append(f"missing structured conditions: {path.name}")
                continue
            data = self._load_json(path, {}, limitations)
            flattened.extend(self._flatten_conditions(data, func))
        seen: set[tuple[str, ...]] = set()
        output: list[dict[str, Any]] = []
        for item in flattened:
            key = tuple(str(item.get(name, "")) for name in (
                "function", "condition", "expression", "variable", "operator",
                "threshold", "normal_value", "suppression_trigger", "source",
            ))
            if key not in seen:
                seen.add(key)
                output.append(item)
        return output

    def _flatten_conditions(
        self, value: Any, function: str, path: tuple[str, ...] = ()
    ) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        if isinstance(value, list):
            for item in value:
                output.extend(self._flatten_conditions(item, function, path))
        elif isinstance(value, dict):
            has_subject = any(value.get(key) not in (None, "") for key in (
                "condition", "expression", "variable",
            ))
            has_detail = any(key in value for key in (
                "operator", "threshold", "normal_value", "suppression_trigger",
                "source", "can_signal",
            ))
            if has_subject and has_detail:
                item = dict(value)
                item.setdefault("function", function)
                item.setdefault("category", ".".join(path))
                output.append(item)
            for key, child in value.items():
                if isinstance(child, (dict, list)):
                    output.extend(self._flatten_conditions(child, function, path + (str(key),)))
        return output

    def _select_conditions(
        self, conditions: list[dict[str, Any]], question: str, plan: InvestigationPlan
    ) -> list[dict[str, Any]]:
        anchors = _tokens(question)
        for value in plan.code_symbols + plan.can_signals:
            anchors.update(_tokens(value))
            anchors.add(_normalize(value))
        scored: list[tuple[int, int, dict[str, Any]]] = []
        for index, item in enumerate(conditions):
            haystack = _normalize(" ".join(str(item.get(key, "")) for key in (
                "condition", "expression", "variable", "can_signal", "source", "category",
            )))
            score = sum(4 for anchor in anchors if len(anchor) >= 2 and anchor in haystack)
            if item.get("source"):
                score += 1
            if "external_suppression" in str(item.get("category", "")).lower():
                score += 2
            scored.append((score, index, item))
        scored.sort(key=lambda row: (-row[0], row[1]))
        return [row[2] for row in scored[:self.max_conditions]]

    @staticmethod
    def _load_json(
        path: Path, fallback: dict[str, Any], limitations: list[str], optional: bool = False
    ) -> dict[str, Any]:
        if not path.exists():
            if not optional:
                limitations.append(f"missing knowledge file: {path.name}")
            return fallback
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else fallback
        except (OSError, json.JSONDecodeError) as exc:
            limitations.append(f"unreadable knowledge file {path.name}: {exc}")
            return fallback

    def _check_condition(
        self,
        item: dict[str, Any],
        store: Any,
        signal_lookup: dict[str, dict[str, Any]],
        mapping: dict[str, Any],
        chains: dict[str, Any],
        debug_columns: set[str],
        fact_cache: dict[tuple[str, str], tuple[DataFact, list[float]]],
        analysis_windows: list[dict[str, Any]],
    ) -> ConditionCheck:
        variable = str(item.get("variable") or "").strip()
        expression, operator, threshold = _parse_comparison(item, variable)
        signals, mapping_status = self._resolve_signals(
            item, variable, mapping, chains, signal_lookup, debug_columns
        )
        values: list[float] = []
        raw_values_seen: list[float] = []
        effective_mapping_status = mapping_status
        evidence_refs: list[str] = []
        source_ref = str(item.get("source") or "").strip()
        if source_ref:
            evidence_refs.append(f"code:{source_ref}")
        for signal in signals:
            if signal.startswith("radar_debug."):
                source, field_name = "radar_debug", signal.split(".", 1)[1]
            else:
                source, field_name = "can", signal
            key = (source, field_name)
            if key not in fact_cache:
                fact_cache[key] = self._query_data_fact(
                    store, source, field_name, signal_lookup, analysis_windows,
                )
            fact, raw_values = fact_cache[key]
            raw_values_seen.extend(raw_values)
            transformed, complete = self._apply_mapping_transform(
                variable, signal, raw_values, mapping, mapping_status,
            )
            values.extend(transformed)
            if not complete:
                effective_mapping_status = "partial_enum_mapping"
            evidence_refs.append(f"data:{source}:{field_name}")

        result, observation = _evaluate(
            operator, threshold, values, effective_mapping_status,
        )
        observation["raw_min"] = min(raw_values_seen) if raw_values_seen else None
        observation["raw_max"] = max(raw_values_seen) if raw_values_seen else None
        observation["evaluated_domain"] = (
            "internal_after_mapping"
            if mapping_status in {"signal_mapping_enum", "partial_enum_mapping"}
            else "raw_recorded_value"
        )
        mapping_evidence = self._mapping_evidence(variable, signals, mapping)
        if mapping_evidence:
            observation["mapping_evidence"] = mapping_evidence
        return ConditionCheck(
            expression=expression or str(item.get("condition") or item.get("expression") or ""),
            code_ref=source_ref,
            variables=[variable] if variable else [],
            signals=signals,
            observation=observation,
            result=result,
            evidence_refs=_dedupe(evidence_refs),
        )

    @staticmethod
    def _derive_analysis_windows(
        store: Any,
        plan: dict[str, Any] | InvestigationPlan,
        signal_lookup: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if isinstance(plan, InvestigationPlan):
            return []
        requests = plan.get("can_signals", []) if isinstance(plan, dict) else []
        functions = {
            str(value).lower() for value in (plan.get("functions", []) or [])
        }
        candidates: list[tuple[int, str]] = []
        for item in requests or []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("signal_name") or "")
            normalized = name.lower()
            if name and any(token in normalized for token in ("enable", "switch", "swt")):
                score = 10 * sum(1 for function in functions if function in normalized)
                if str(item.get("role") or "").lower() == "primary":
                    score += 5
                if "enable" in normalized:
                    score += 2
                candidates.append((score, name))
        candidates.sort(key=lambda item: -item[0])
        for _, name in candidates:
            info = signal_lookup.get(name, {})
            can_id = info.get("can_id")
            if can_id is None:
                continue
            timeline = store.query_signal_timeline(can_id, name)
            windows: list[dict[str, Any]] = []
            start: float | None = None
            last_active_time: float | None = None
            for row in timeline:
                value = row.get("value")
                timestamp = float(row.get("timestamp", 0.0))
                if not _finite_number(value):
                    continue
                active = float(value) > 0
                if active and start is None:
                    start = timestamp
                if active:
                    last_active_time = timestamp
                elif not active and start is not None:
                    windows.append({
                        "source_signal": name,
                        "start": start,
                        "end": last_active_time if last_active_time is not None else start,
                        "rule": "recorded value > 0",
                    })
                    start = None
            if start is not None and last_active_time is not None:
                windows.append({
                    "source_signal": name,
                    "start": start,
                    "end": last_active_time,
                    "rule": "recorded value > 0",
                })
            if windows:
                return windows[:10]
        return []

    @staticmethod
    def _resolve_signals(
        item: dict[str, Any],
        variable: str,
        mapping: dict[str, Any],
        chains: dict[str, Any],
        signal_lookup: dict[str, dict[str, Any]],
        debug_columns: set[str],
    ) -> tuple[list[str], str]:
        signals: list[str] = []
        explicit = str(item.get("can_signal") or "").strip()
        if explicit.lower() not in _MISSING_SIGNAL_NAMES:
            matched = _lookup_signal_name(signal_lookup, explicit)
            if matched:
                signals.append(matched)
                return signals, "explicit"
        if variable:
            try:
                resolved = resolve_internal_to_can(variable, mapping, chains)
            except Exception:
                resolved = []
            for candidate in resolved or []:
                name = candidate if isinstance(candidate, str) else candidate.get("signal_name", "")
                matched = _lookup_signal_name(signal_lookup, str(name))
                if matched and matched not in signals:
                    signals.append(matched)
            if signals:
                return signals, EngineeringInvestigator._mapping_status(
                    variable, signals, mapping,
                )
            leaf = variable.rsplit(".", 1)[-1]
            if leaf in debug_columns and leaf not in _DEBUG_METADATA:
                return [f"radar_debug.{leaf}"], "radar_debug_schema"
        return [], "unmapped"

    @staticmethod
    def _mapping_status(
        variable: str, signals: list[str], mapping: dict[str, Any]
    ) -> str:
        """Only raw-value-equivalent mappings are safe for direct comparisons."""
        entries = mapping.get("mappings", [])
        if not entries:
            return "signal_mapping"
        leaf = variable.rsplit(".", 1)[-1].lower()
        matched = []
        for entry in entries:
            internal = str(entry.get("internal_var") or "").lower()
            full_path = str(entry.get("internal_full_path") or "").lower()
            can_signal = str(entry.get("can_signal") or "")
            if can_signal in signals and (internal == leaf or full_path == variable.lower()):
                matched.append(entry)
        if not matched:
            return "signal_mapping"
        has_enum = False
        for entry in matched:
            transform = str(entry.get("transform") or "").strip().lower()
            scaling = str(entry.get("scaling") or "").strip().lower()
            if transform == "enum" and isinstance(entry.get("enum_map"), dict):
                has_enum = True
                continue
            if transform != "passthrough" and scaling != "1:1":
                return "transformed_signal_mapping"
        return "signal_mapping_enum" if has_enum else "signal_mapping"

    @staticmethod
    def _apply_mapping_transform(
        variable: str,
        signal: str,
        values: list[float],
        mapping: dict[str, Any],
        mapping_status: str,
    ) -> tuple[list[float], bool]:
        if mapping_status != "signal_mapping_enum":
            return values, True
        leaf = variable.rsplit(".", 1)[-1].lower()
        for entry in mapping.get("mappings", []):
            if str(entry.get("can_signal") or "") != signal:
                continue
            internal = str(entry.get("internal_var") or "").lower()
            full_path = str(entry.get("internal_full_path") or "").lower()
            if internal != leaf and full_path != variable.lower():
                continue
            enum_map = entry.get("enum_map", {})
            default = entry.get("default")
            transformed: list[float] = []
            complete = True
            for value in values:
                key = str(int(value)) if float(value).is_integer() else str(value)
                output = enum_map.get(key, default)
                if _finite_number(output):
                    transformed.append(float(output))
                else:
                    complete = False
            return transformed, complete
        return [], False

    @staticmethod
    def _mapping_evidence(
        variable: str, signals: list[str], mapping: dict[str, Any]
    ) -> list[dict[str, Any]]:
        leaf = variable.rsplit(".", 1)[-1].lower()
        evidence: list[dict[str, Any]] = []
        for entry in mapping.get("mappings", []):
            internal = str(entry.get("internal_var") or "").lower()
            full_path = str(entry.get("internal_full_path") or "").lower()
            if str(entry.get("can_signal") or "") not in signals:
                continue
            if internal != leaf and full_path != variable.lower():
                continue
            evidence.append({
                key: entry.get(key)
                for key in (
                    "can_signal", "internal_full_path", "transform", "scaling",
                    "enum_map", "default",
                )
                if entry.get(key) not in (None, "", {})
            })
            if len(evidence) >= 3:
                break
        return evidence

    @staticmethod
    def _debug_columns(store: Any) -> set[str]:
        try:
            return {str(row[1]) for row in store.conn.execute("PRAGMA table_info(radar_debug)")}
        except Exception:
            return set()

    @staticmethod
    def _query_data_fact(
        store: Any,
        source: str,
        field_name: str,
        signal_lookup: dict[str, dict[str, Any]],
        analysis_windows: list[dict[str, Any]] | None = None,
    ) -> tuple[DataFact, list[float]]:
        samples: list[tuple[float, float]] = []
        carry_forward_count = 0
        if source == "can":
            info = signal_lookup.get(field_name, {})
            can_id = info.get("can_id")
            if can_id is not None:
                for row in store.query_signal_timeline(can_id, field_name):
                    value = row.get("value")
                    if _finite_number(value):
                        samples.append((float(row.get("timestamp", 0.0)), float(value)))
        else:
            allowed = {str(row[1]) for row in store.conn.execute("PRAGMA table_info(radar_debug)")}
            if field_name in allowed and field_name not in _DEBUG_METADATA:
                sql = f'SELECT timestamp_ns, "{field_name}" FROM radar_debug WHERE "{field_name}" IS NOT NULL ORDER BY timestamp_ns'
                for timestamp_ns, value in store.conn.execute(sql):
                    if _finite_number(value):
                        samples.append((float(timestamp_ns) / 1e9, float(value)))
        if analysis_windows:
            all_samples = samples
            samples = []
            for window in analysis_windows:
                start = float(window["start"])
                end = float(window["end"])
                in_window = [sample for sample in all_samples if start <= sample[0] <= end]
                if in_window:
                    samples.extend(in_window)
                    continue
                previous = [sample for sample in all_samples if sample[0] <= start]
                if previous:
                    samples.append(previous[-1])
                    carry_forward_count += 1
        values = [value for _, value in samples]
        distinct = sorted(set(values))[:12]
        fact = DataFact(
            source=source,
            field=field_name,
            sample_count=len(values),
            minimum=min(values) if values else None,
            maximum=max(values) if values else None,
            start_time=samples[0][0] if samples else None,
            end_time=samples[-1][0] if samples else None,
            distinct_values=distinct,
            windowed=bool(analysis_windows),
            carry_forward_count=carry_forward_count,
        )
        return fact, values

    def _build_code_facts(
        self, conditions: list[dict[str, Any]], db_path: Path, limitations: list[str]
    ) -> list[CodeFact]:
        if not conditions:
            return []
        graph = None
        try:
            if self.codegraph_factory:
                graph = self.codegraph_factory(db_path)
            else:
                from .codegraph.query import CodeGraph
                graph = CodeGraph(db_path)
            if not getattr(graph, "is_available", True):
                limitations.append(f"CodeGraph unavailable: {db_path}")
                return []
            facts: list[CodeFact] = []
            seen: set[tuple[str, str]] = set()
            for item in conditions:
                source_ref = str(item.get("source") or "")
                parsed = _parse_source(source_ref)
                if not parsed:
                    continue
                file_path, line = parsed
                functions = graph.get_functions_in_range(line, line, file_path)
                if not functions:
                    functions = self._find_by_basename(graph, file_path, line)
                for node in functions[:1]:
                    name = _node_value(node, "name")
                    key = (source_ref, name)
                    if not name or key in seen:
                        continue
                    seen.add(key)
                    callers = _relation_names(graph.get_callers(name), "caller_name")
                    callees = _relation_names(graph.get_callees(name), "callee_name")
                    facts.append(CodeFact(
                        expression=str(item.get("condition") or item.get("expression") or ""),
                        source_ref=source_ref,
                        function_name=name,
                        file_path=file_path,
                        line=line,
                        callers=callers,
                        callees=callees,
                        snippet=self._source_snippet(file_path, line),
                    ))
            return facts
        except Exception as exc:
            limitations.append(f"CodeGraph query failed: {exc}")
            return []
        finally:
            if graph is not None:
                try:
                    graph.close()
                except Exception:
                    pass

    def _source_snippet(self, file_path: str, line: int | None) -> str:
        if not line:
            return ""
        source_root = self.config.get("project", {}).get("source_code")
        if not source_root:
            return ""
        path = Path(source_root) / file_path.replace("/", "\\")
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return ""
        start = max(0, line - 3)
        end = min(len(lines), line + 2)
        return "\n".join(f"{index + 1}: {lines[index]}" for index in range(start, end))

    @staticmethod
    def _find_by_basename(graph: Any, file_path: str, line: int) -> list[Any]:
        connection = getattr(graph, "conn", None)
        if connection is None:
            return []
        basename = file_path.replace("\\", "/").rsplit("/", 1)[-1].lower()
        rows = connection.execute(
            "SELECT id FROM nodes WHERE type='FILE' AND (lower(id) LIKE ? OR lower(id) LIKE ?)",
            (f"%/{basename}", f"%:{basename}"),
        ).fetchall()
        for row in rows:
            candidate = str(row[0])
            if candidate.startswith("FILE:"):
                candidate = candidate[5:]
            functions = graph.get_functions_in_range(line, line, candidate)
            if functions:
                return functions
        return []


def _parse_comparison(
    item: dict[str, Any], variable: str
) -> tuple[str, str | None, float | None]:
    explicit_op = str(item.get("operator") or "").strip()
    explicit_threshold = str(item.get("threshold") or "").strip()
    if explicit_op in {"==", "!=", "<", "<=", ">", ">="}:
        value = _number(explicit_threshold)
        if value is not None:
            return f"{variable or 'value'} {explicit_op} {value:g}", explicit_op, value
    for key in ("condition", "expression", "threshold", "normal_value", "suppression_trigger"):
        text = str(item.get(key) or "").strip()
        if not text or "&&" in text or "||" in text:
            continue
        match = _COMPARE_RE.search(text)
        if match:
            value = _number(match.group("value"))
            if value is not None:
                op = match.group("op")
                return f"{variable or 'value'} {op} {value:g}", op, value
    return str(item.get("condition") or item.get("expression") or ""), None, None


def _evaluate(
    operator: str | None,
    threshold: float | None,
    values: list[float],
    mapping_status: str,
) -> tuple[str, dict[str, Any]]:
    observation: dict[str, Any] = {
        "sample_count": len(values),
        "min": min(values) if values else None,
        "max": max(values) if values else None,
        "pass_count": 0,
        "pass_ratio": None,
        "mapping_status": mapping_status,
    }
    if (
        operator is None
        or threshold is None
        or not values
        or mapping_status in {"transformed_signal_mapping", "partial_enum_mapping"}
    ):
        return "unknown", observation
    operations = {
        "==": lambda value: value == threshold,
        "!=": lambda value: value != threshold,
        "<": lambda value: value < threshold,
        "<=": lambda value: value <= threshold,
        ">": lambda value: value > threshold,
        ">=": lambda value: value >= threshold,
    }
    passed = sum(1 for value in values if operations[operator](value))
    observation["pass_count"] = passed
    observation["pass_ratio"] = passed / len(values)
    if passed == len(values):
        return "satisfied", observation
    if passed == 0:
        return "violated", observation
    return "mixed", observation


def _parse_source(source_ref: str) -> tuple[str, int] | None:
    match = _SOURCE_RE.match(source_ref.strip())
    if not match:
        return None
    return match.group("path").replace("\\", "/"), int(match.group("line"))


def _number(value: Any) -> float | None:
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(int(text, 16)) if text.lower().startswith(("0x", "-0x")) else float(text)
    except ValueError:
        return None


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _lookup_signal_name(signal_lookup: dict[str, Any], name: str) -> str | None:
    if name in signal_lookup:
        return name
    lower = name.lower()
    return next((key for key in signal_lookup if key.lower() == lower), None)


def _node_value(node: Any, key: str) -> str:
    if isinstance(node, dict):
        return str(node.get(key) or "")
    return str(getattr(node, key, "") or "")


def _relation_names(rows: list[Any], preferred_key: str) -> list[str]:
    names: list[str] = []
    for row in rows or []:
        name = _node_value(row, preferred_key) or _node_value(row, "name")
        if name and name not in names:
            names.append(name)
        if len(names) >= 5:
            break
    return names


def _normalize(value: Any) -> str:
    return re.sub(r"[^a-z0-9_]+", "", str(value).lower())


def _tokens(value: Any) -> set[str]:
    return {_normalize(token) for token in re.findall(r"[A-Za-z_][A-Za-z0-9_.]*", str(value))}


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value if item]
    return []


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


__all__ = [
    "CodeFact", "ConditionCheck", "DataFact", "EngineeringInvestigator",
    "InvestigationPlan", "InvestigationResult",
]
