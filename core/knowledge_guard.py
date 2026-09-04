"""Fail-closed freshness guard for knowledge entering AI context."""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True)
class KnowledgeDecision:
    category: str
    allowed: bool
    reasons: tuple[str, ...] = ()


_STALE_ON: Mapping[str, tuple[str, ...]] = {
    "source_docs": ("code_changed", "constants_changed", "identity_changed"),
    "conditions": ("code_changed", "constants_changed", "identity_changed"),
    "code_knowledge": ("code_changed", "constants_changed", "identity_changed"),
    "variable_chains": ("code_changed", "constants_changed", "identity_changed"),
    "codegraph": ("code_changed", "constants_changed", "identity_changed"),
    "dbc_knowledge": ("dbc_changed", "identity_changed"),
    "requirements": ("requirements_changed", "identity_changed"),
    "case_history": ("identity_changed",),
}

_SIGNATURE_FIELDS: Mapping[str, tuple[str, ...]] = {
    "source_docs": ("source_root", "current_commit", "key_source_files_hash", "source_scope_hash", "constants_source_hash", "config_identity_hash"),
    "conditions": ("source_root", "current_commit", "source_scope_hash", "constants_source_hash", "config_identity_hash"),
    "code_knowledge": ("source_root", "current_commit", "key_source_files_hash", "source_scope_hash", "constants_source_hash", "config_identity_hash"),
    "variable_chains": ("source_root", "current_commit", "source_scope_hash", "config_identity_hash"),
    "codegraph": ("source_root", "current_commit", "source_scope_hash", "config_identity_hash"),
    "dbc_knowledge": ("dbc_hash", "config_identity_hash"),
    "requirements": ("requirements_hash", "config_identity_hash"),
    "case_history": ("config_identity_hash",),
}

KNOWLEDGE_MANIFEST_FILE = "knowledge_manifest.json"


class KnowledgeFreshnessGuard:
    """Decide whether a variant-scoped knowledge category may be consumed."""

    def __init__(self, config: Mapping[str, Any] | Any) -> None:
        self._config = config
        self._manifest_cache: dict[str, Any] | None = None

    def _freshness(self) -> Mapping[str, Any] | None:
        if isinstance(self._config, Mapping):
            identity = self._config.get("identity")
        else:
            identity = getattr(self._config, "identity", None)
        if isinstance(identity, Mapping):
            freshness = identity.get("freshness")
        else:
            freshness = getattr(identity, "freshness", None)
        return freshness if isinstance(freshness, Mapping) else None

    def decision(self, category: str) -> KnowledgeDecision:
        base_category = _base_category(category)
        stale_flags = _STALE_ON.get(base_category)
        if stale_flags is None:
            return KnowledgeDecision(category, False, ("unknown_category",))
        freshness = self._freshness()
        if freshness is None:
            return KnowledgeDecision(category, False, ("freshness_missing",))
        if freshness.get("available") is False:
            return KnowledgeDecision(category, False, ("freshness_unavailable",))
        if self._manifest_allows(category, freshness):
            return KnowledgeDecision(category, True, ())
        reasons = tuple(flag for flag in stale_flags if bool(freshness.get(flag)))
        return KnowledgeDecision(category, not reasons, reasons)

    def _manifest_allows(
        self, category: str, freshness: Mapping[str, Any]
    ) -> bool:
        path = _manifest_path(freshness)
        if path is None or not path.exists():
            return False
        if self._manifest_cache is None:
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                self._manifest_cache = loaded if isinstance(loaded, dict) else {}
            except (OSError, json.JSONDecodeError):
                self._manifest_cache = {}
        entry = self._manifest_cache.get("categories", {}).get(category, {})
        return bool(
            entry.get("status") == "fresh"
            and entry.get("input_signature") == category_input_signature(freshness, category)
        )

    def allows(self, category: str) -> bool:
        return self.decision(category).allowed

    def blocked_reason(self, category: str) -> str | None:
        decision = self.decision(category)
        return None if decision.allowed else ", ".join(decision.reasons)


def runtime_knowledge_decision(
    config: Mapping[str, Any] | Any,
    category: str,
) -> KnowledgeDecision:
    """Enforce fail-closed freshness for variant runs, preserve legacy mode."""
    if isinstance(config, Mapping):
        identity = config.get("identity")
    else:
        identity = getattr(config, "identity", None)
    if isinstance(identity, Mapping):
        variant_id = identity.get("variant_id")
    else:
        variant_id = getattr(identity, "variant_id", None)
    if not variant_id:
        return KnowledgeDecision(category, True, ())
    return KnowledgeFreshnessGuard(config).decision(category)


def category_input_signature(
    freshness: Mapping[str, Any], category: str,
) -> str:
    fields = _SIGNATURE_FIELDS.get(_base_category(category))
    if fields is None:
        return ""
    payload = {field: freshness.get(field) for field in fields}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:24]


def partition_stable_categories(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    categories: list[str],
) -> tuple[list[str], list[str]]:
    """Split refreshed scopes by whether their source inputs stayed unchanged."""
    stable: list[str] = []
    changed: list[str] = []
    for category in dict.fromkeys(categories):
        if category_input_signature(before, category) == category_input_signature(
            after, category
        ):
            stable.append(category)
        else:
            changed.append(category)
    return stable, changed


def publish_knowledge_categories(
    config: Mapping[str, Any],
    categories: list[str] | tuple[str, ...],
    *,
    producer: str,
) -> dict[str, Any]:
    """Atomically publish module-level freshness for the current variant."""
    freshness = config.get("identity", {}).get("freshness")
    if not isinstance(freshness, Mapping):
        raise ValueError("freshness_missing")
    path = _manifest_path(freshness)
    if path is None:
        raise ValueError("freshness_state_path_missing")
    existing: dict[str, Any] = {}
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            existing = loaded if isinstance(loaded, dict) else {}
        except (OSError, json.JSONDecodeError):
            existing = {}
    entries = existing.setdefault("categories", {})
    now = _dt.datetime.now().isoformat()
    published: list[str] = []
    for category in categories:
        if _base_category(category) not in _SIGNATURE_FIELDS:
            raise ValueError(f"unknown_category:{category}")
        entries[category] = {
            "status": "fresh",
            "input_signature": category_input_signature(freshness, category),
            "producer": producer,
            "updated_at": now,
        }
        published.append(category)
    existing["schema_version"] = 1
    existing["variant_id"] = config.get("identity", {}).get("variant_id")
    existing["artifacts"] = _collect_artifact_state(path.parent, categories)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)
    return {"path": str(path), "published": published}


def _collect_artifact_state(
    memory_dir: Path, categories: list[str] | tuple[str, ...]
) -> dict[str, Any]:
    """Record whether each published category has actual artifacts on disk.

    Guards against the manifest claiming "fresh" for categories whose
    products were never written (e.g. code_knowledge when the FOCUS files
    are missing). Consumers can inspect this to distinguish "fresh by
    signature" from "fresh and present".
    """
    state: dict[str, Any] = {}
    # Workspace layout: memory_dir = <workspace>/memory, and the sibling
    # <workspace>/source_docs holds the deterministic index products.
    source_docs_dir = memory_dir.parent / "source_docs"
    for category in dict.fromkeys(categories):
        base = _base_category(category)
        artifacts: list[str] = []
        if base == "source_docs":
            for pattern in ("*.md", "*_conditions.json"):
                artifacts.extend(
                    str(p.relative_to(memory_dir)).replace("\\", "/")
                    for p in source_docs_dir.glob(pattern)
                )
        elif base == "code_knowledge":
            artifacts.extend(
                str(p.relative_to(memory_dir)).replace("\\", "/")
                for p in (memory_dir / "code_knowledge").glob("*.json")
                if p.name != "learning_state.json"
            )
        elif base == "variable_chains":
            p = source_docs_dir / "variable_chains.json"
            if p.exists():
                artifacts.append("source_docs/variable_chains.json")
        elif base == "codegraph":
            p = memory_dir / "codegraph" / "codegraph.db"
            if p.exists():
                artifacts.append("codegraph/codegraph.db")
        state[category] = {
            "present": bool(artifacts),
            "artifacts": sorted(artifacts)[:50],
            "count": len(artifacts),
        }
    return state


def _manifest_path(freshness: Mapping[str, Any]) -> Path | None:
    state_path = freshness.get("state_path")
    if not state_path:
        return None
    return Path(str(state_path)).parent / KNOWLEDGE_MANIFEST_FILE


def _base_category(category: str) -> str:
    return str(category).split(":", 1)[0]


__all__ = [
    "KnowledgeDecision", "KnowledgeFreshnessGuard", "runtime_knowledge_decision",
    "category_input_signature", "partition_stable_categories",
    "publish_knowledge_categories",
]
