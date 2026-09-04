# -*- coding: utf-8 -*-
"""Per-step artifact registry — G2 intermediate-product channel.

The diagnosis pipeline historically only exposed its byproducts (signal
selection, test windows, TPE narration, probe results) inside the final
``report.md`` / ``diagnosis_bundle.json``. G2 introduces a lightweight,
JSON-serializable channel so any pipeline step can *emit* an artifact as soon
as it is produced; downstream consumers (CLI progress, conversation bridge,
pi-style inspector) can read the live registry without waiting for the run to
finish.

Design constraints (kept minimal by intent):

* No I/O — the registry is in-memory; callers decide whether to persist.
* JSON-serializable only — every record must round-trip through ``json.dumps``.
* Append-only — never mutate a previously emitted record; new revisions are
  new records (callers dedupe by ``name`` if they care about "latest").
* Thread-friendliness is not required; the orchestrator runs single-threaded.
  A simple lock is still included so future async callers are safe.

The :func:`emit_artifact` module-level helper targets the *active* registry
(the most recently created one, or one explicitly pinned via
``set_default_registry``). Direct construction of ``ArtifactRegistry`` is also
supported for tests and isolated runs.
"""
from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

# Allowed ``kind`` values — deliberately a closed set so consumers can branch
# on kind without a typo becoming an ad-hoc new channel.
_ARTIFACT_KINDS = frozenset({
    "signals",        # selected/relevant signal list
    "window",         # detected test window
    "tpe",            # temporal pattern engine narration/summary
    "probe",          # data probe results
    "conditions",     # extracted code condition tree
    "evidence",       # frame-level evidence summary
    "parameters",     # parameter sensitivity / what-if
    "fix",            # code fix suggestion
    "report",         # final report / bundle path
    "other",          # escape hatch (caller must self-describe in summary)
})


@dataclass
class ArtifactRecord:
    """One emitted intermediate product.

    ``path`` may be a filesystem path, a URI, or ``None`` for purely in-memory
    artifacts. ``summary`` is a short human-readable description; the full
    payload is intentionally NOT stored here to keep the registry small —
    callers that need the payload should write it to ``path`` and reference it.
    """

    name: str
    kind: str
    path: Optional[str]
    summary: str
    step: str = ""           # pipeline step that emitted it (e.g. "evidence")
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ArtifactRegistry:
    """Append-only registry of per-step artifacts.

    Typical usage inside an orchestrator step::

        from ai.capability import ArtifactRegistry
        reg = ArtifactRegistry()
        ...
        reg.emit("selected_signals", "signals", None,
                 "12 CAN signals selected for RCTA", step="signals")
        # later, in the deliver step:
        reg.to_list()  # -> list[dict] for JSON in report/bundle
    """

    def __init__(self) -> None:
        self._records: list[ArtifactRecord] = []
        self._lock = threading.Lock()

    # -- core API ------------------------------------------------------
    def emit(
        self,
        name: str,
        kind: str,
        path: Any = None,
        summary: str = "",
        *,
        step: str = "",
        metadata: Optional[dict[str, Any]] = None,
    ) -> ArtifactRecord:
        """Register a single artifact; returns the created record.

        ``path`` accepts :class:`pathlib.Path` for convenience and is
        serialized to a string. Unknown ``kind`` values are coerced to
        ``"other"`` (with a note in metadata) so a caller typo never breaks
        serialization — fail-open for observability.
        """
        if not isinstance(name, str) or not name.strip():
            raise ValueError("artifact name must be a non-empty string")
        meta = dict(metadata or {})
        if kind not in _ARTIFACT_KINDS:
            meta.setdefault("original_kind", kind)
            kind = "other"
        if isinstance(path, Path):
            path = str(path)
        elif path is not None and not isinstance(path, str):
            path = str(path)

        record = ArtifactRecord(
            name=name,
            kind=kind,
            path=path,
            summary="" if summary is None else str(summary),
            step=step or "",
            metadata=meta,
        )
        # Validate JSON-serializability eagerly — fail closed at emit time
        # rather than letting a bad record corrupt the whole registry later.
        json.dumps(record.to_dict())
        with self._lock:
            self._records.append(record)
        return record

    # -- read API ------------------------------------------------------
    def to_list(self) -> list[dict[str, Any]]:
        """Snapshot of all records as a list of JSON-friendly dicts."""
        with self._lock:
            return [r.to_dict() for r in self._records]

    def latest(self, name: str) -> Optional[ArtifactRecord]:
        """Return the most recently emitted record with ``name``, or None."""
        with self._lock:
            for record in reversed(self._records):
                if record.name == name:
                    return record
        return None

    def by_kind(self, kind: str) -> list[ArtifactRecord]:
        with self._lock:
            return [r for r in self._records if r.kind == kind]

    def __len__(self) -> int:
        with self._lock:
            return len(self._records)

    def __iter__(self):
        with self._lock:
            return iter(list(self._records))


# ---------------------------------------------------------------------
# Module-level default registry + helper
# ---------------------------------------------------------------------
_default_registry: Optional[ArtifactRegistry] = None
_default_lock = threading.Lock()


def set_default_registry(registry: Optional[ArtifactRegistry]) -> None:
    """Pin the registry targeted by the module-level :func:`emit_artifact`.

    Pass ``None`` to clear. Mainly useful for tests and for the orchestrator
    to bind a fresh registry to a diagnosis run.
    """
    global _default_registry
    with _default_lock:
        _default_registry = registry


def get_default_registry() -> ArtifactRegistry:
    """Return the active default registry, creating one lazily if needed."""
    global _default_registry
    with _default_lock:
        if _default_registry is None:
            _default_registry = ArtifactRegistry()
        return _default_registry


def emit_artifact(
    name: str,
    kind: str,
    path: Any = None,
    summary: str = "",
    *,
    step: str = "",
    metadata: Optional[dict[str, Any]] = None,
) -> ArtifactRecord:
    """Emit an artifact to the active (default) registry.

    Convenience wrapper so pipeline steps can do::

        from ai.capability import emit_artifact
        emit_artifact("tpe_narration", "tpe", None, narration[:200],
                      step="tpe")
    """
    return get_default_registry().emit(
        name, kind, path, summary, step=step, metadata=metadata,
    )


__all__ = [
    "ArtifactRecord",
    "ArtifactRegistry",
    "emit_artifact",
    "get_default_registry",
    "set_default_registry",
]
