# -*- coding: utf-8 -*-
"""
Requirement loader (M3): parse structured requirement YAML into a
:class:`~core.materials.StructuredRequirementSet`.

Two schemas are supported transparently in the same directory:

* **V3 schema** — ``req_id`` / ``feature`` / ``description`` with
  ``preconditions`` + ``activation_conditions`` (lists of typed conditions)
  and ``expected_output_signal``.
* **RequirementSpec schema** — the flat fields already defined by
  :class:`core.materials.RequirementSpec` (``requirement_id``, ``statement``,
  ``linked_signals`` ...).

A single ``*.yaml`` file may hold one requirement (a mapping) or several
(a list of mappings, or a ``{"requirements": [...]}`` wrapper). Linked signals
are harvested from every condition ``signal_alias`` and from
``expected_output_signal``.

Validation runs *with or without* :mod:`pydantic`. When pydantic is importable a
strict schema pass (:class:`RequirementModel`) augments the deterministic
:meth:`RequirementLoader.validate_structure`; otherwise the deterministic path
still catches the common structural defects.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from core.materials import RequirementSpec, StructuredRequirementSet

log = logging.getLogger(__name__)

#: Canonical comparison operators accepted in requirement conditions.
VALID_OPERATORS = frozenset({">", "<", ">=", "<=", "==", "!="})

#: Keys that hold condition lists inside a requirement mapping.
_CONDITION_KEYS = ("preconditions", "activation_conditions", "conditions")


# ── Optional pydantic strict layer ─────────────────────────────────────

try:  # pragma: no cover - branch depends on the environment
    import pydantic  # noqa: F401
    from pydantic import BaseModel

    _HAS_PYDANTIC = True
except Exception:  # noqa: BLE001 - any import failure => degrade gracefully
    pydantic = None  # type: ignore[assignment]
    BaseModel = object  # type: ignore[assignment,misc]
    _HAS_PYDANTIC = False


if _HAS_PYDANTIC:

    class Condition(BaseModel):  # type: ignore[misc,valid-type]
        """One typed activation/pre condition (pydantic-validated)."""

        signal_alias: str
        operator: str
        value: Any
        duration_ms: int | None = None

    class RequirementModel(BaseModel):  # type: ignore[misc,valid-type]
        """Strict V3 requirement schema (only defined when pydantic present)."""

        req_id: str
        feature: str = ""
        description: str = ""
        preconditions: list[Condition] = []
        activation_conditions: list[Condition] = []
        expected_output_signal: str = ""

else:  # lightweight placeholders so the names always exist for import/export

    class Condition:  # type: ignore[no-redef]
        """Fallback stub used when pydantic is unavailable."""

    class RequirementModel:  # type: ignore[no-redef]
        """Fallback stub used when pydantic is unavailable."""


class RequirementLoader:
    """Parse requirement YAML files into a :class:`StructuredRequirementSet`."""

    # ── public API ─────────────────────────────────────────────────────

    def load_yaml_dir(
        self, req_dir: Path | str, variant_id: str = ""
    ) -> StructuredRequirementSet:
        """Load and merge every ``*.yaml`` / ``*.yml`` file in ``req_dir``.

        Duplicate requirement ids are preserved (the later one is suffixed with
        ``#dupN`` and marked via ``metadata['duplicate_of']``) so the reviewer
        can surface them rather than silently dropping data.
        """
        req_dir = Path(req_dir)
        req_set = StructuredRequirementSet(variant_id=variant_id)
        if not req_dir.exists() or not req_dir.is_dir():
            log.warning("Requirement dir not found: %s", req_dir)
            return req_set

        files = sorted(req_dir.glob("*.yaml")) + sorted(req_dir.glob("*.yml"))
        for path in files:
            for spec in self.load_yaml_file(path, variant_id=variant_id):
                self._add_dedup(req_set, spec)
        return req_set

    def load_yaml_file(
        self, path: Path | str, variant_id: str = ""
    ) -> list[RequirementSpec]:
        """Parse a single YAML file into a list of :class:`RequirementSpec`."""
        path = Path(path)
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            log.warning("Failed to read requirement file %s: %s", path, exc)
            return []

        specs: list[RequirementSpec] = []
        for rec in self._as_records(raw):
            if not isinstance(rec, dict):
                log.warning("Skipping non-mapping requirement in %s: %r", path, rec)
                continue
            specs.append(
                self._to_spec(rec, variant_id=variant_id, source_file=str(path))
            )
        return specs

    def validate_structure(self, raw: dict) -> list[str]:
        """Return a list of structural problems for a raw requirement mapping.

        Works fully without pydantic. When pydantic *is* present and the record
        carries an id, a best-effort strict schema pass is appended.
        """
        if not isinstance(raw, dict):
            return ["requirement must be a mapping"]

        problems: list[str] = []
        req_id = raw.get("req_id") or raw.get("requirement_id")
        if not req_id or not str(req_id).strip():
            problems.append("missing req_id")

        has_condition = False
        for key in _CONDITION_KEYS:
            conds = raw.get(key)
            if conds is None:
                continue
            if not isinstance(conds, list):
                problems.append(f"{key} must be a list")
                continue
            for idx, cond in enumerate(conds):
                if not isinstance(cond, dict):
                    problems.append(f"{key}[{idx}] must be a mapping")
                    continue
                has_condition = True
                alias = cond.get("signal_alias") or cond.get("signal")
                if not alias or not str(alias).strip():
                    problems.append(f"{key}[{idx}] missing signal_alias")
                op = cond.get("operator")
                if op is None:
                    problems.append(f"{key}[{idx}] missing operator")
                elif op not in VALID_OPERATORS:
                    problems.append(f"{key}[{idx}] invalid operator {op!r}")
                if "value" not in cond:
                    problems.append(f"{key}[{idx}] missing value")

        if not has_condition and not (
            raw.get("normalized_logic") or raw.get("linked_signals")
        ):
            problems.append("no conditions defined")

        if _HAS_PYDANTIC and req_id:
            problems.extend(self._pydantic_problems(raw))

        return problems

    # ── internals ──────────────────────────────────────────────────────

    @staticmethod
    def _as_records(raw: Any) -> list[Any]:
        """Normalize parsed YAML into a flat list of requirement records."""
        if raw is None:
            return []
        if isinstance(raw, list):
            return raw
        if isinstance(raw, dict):
            reqs = raw.get("requirements")
            if isinstance(reqs, list):
                return reqs
            return [raw]
        return []

    def _to_spec(
        self, rec: dict, *, variant_id: str, source_file: str
    ) -> RequirementSpec:
        schema_problems = self.validate_structure(rec)
        req_id = str(rec.get("req_id") or rec.get("requirement_id") or "").strip()
        statement = str(
            rec.get("statement")
            or rec.get("description")
            or rec.get("feature")
            or ""
        ).strip()
        scope = str(rec.get("scope") or rec.get("feature") or "").strip()
        priority = str(rec.get("priority") or "medium").strip() or "medium"

        metadata = dict(rec.get("metadata") or {})
        for key in _CONDITION_KEYS:
            if isinstance(rec.get(key), list):
                metadata[key] = rec[key]
        if rec.get("expected_output_signal"):
            metadata["expected_output_signal"] = rec["expected_output_signal"]
        if rec.get("feature"):
            metadata.setdefault("feature", rec["feature"])
        if source_file:
            metadata.setdefault("source_file", source_file)
        if schema_problems:
            metadata["schema_problems"] = schema_problems

        return RequirementSpec(
            requirement_id=req_id,
            material_id=str(rec.get("material_id") or ""),
            variant_id=str(rec.get("variant_id") or variant_id or ""),
            scope=scope,
            statement=statement,
            normalized_logic=str(rec.get("normalized_logic") or ""),
            linked_signals=self._extract_signals(rec),
            linked_files=list(rec.get("linked_files") or []),
            linked_functions=list(rec.get("linked_functions") or []),
            priority=priority,
            evidence_policy=str(rec.get("evidence_policy") or ""),
            metadata=metadata,
        )

    @classmethod
    def _extract_signals(cls, rec: dict) -> list[str]:
        """Harvest signal names from linked_signals, conditions, and output."""
        signals: list[str] = []
        seen: set[str] = set()

        def _add(name: Any) -> None:
            if isinstance(name, str) and name.strip() and name not in seen:
                seen.add(name)
                signals.append(name)

        for s in rec.get("linked_signals") or []:
            _add(s)
        for cond in cls._iter_conditions(rec):
            _add(cond.get("signal_alias") or cond.get("signal"))
        _add(rec.get("expected_output_signal"))
        return signals

    @staticmethod
    def _iter_conditions(rec: dict) -> list[dict]:
        conds: list[dict] = []
        for key in _CONDITION_KEYS:
            val = rec.get(key)
            if isinstance(val, list):
                conds.extend(c for c in val if isinstance(c, dict))
        return conds

    @staticmethod
    def _add_dedup(req_set: StructuredRequirementSet, spec: RequirementSpec) -> None:
        rid = spec.requirement_id or "REQ-UNSPECIFIED"
        if rid not in req_set.requirements:
            spec.requirement_id = rid
            req_set.add(spec)
            return
        n = 1
        new_id = f"{rid}#dup{n}"
        while new_id in req_set.requirements:
            n += 1
            new_id = f"{rid}#dup{n}"
        spec.requirement_id = new_id
        spec.metadata = dict(spec.metadata or {})
        spec.metadata["duplicate_of"] = rid
        req_set.add(spec)

    @staticmethod
    def _pydantic_problems(raw: dict) -> list[str]:
        if not _HAS_PYDANTIC:
            return []
        try:
            RequirementModel(
                req_id=str(raw.get("req_id") or raw.get("requirement_id") or ""),
                feature=raw.get("feature", ""),
                description=raw.get("description") or raw.get("statement", ""),
                preconditions=raw.get("preconditions") or [],
                activation_conditions=raw.get("activation_conditions") or [],
                expected_output_signal=raw.get("expected_output_signal", ""),
            )
        except Exception as exc:  # noqa: BLE001 - pydantic.ValidationError etc.
            return [f"schema: {exc}"]
        return []
