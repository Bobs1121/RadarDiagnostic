# -*- coding: utf-8 -*-
"""Read-only, provenance-preserving access to existing diagnosis memory."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from core.knowledge_guard import runtime_knowledge_decision
from memory.memory_system import MemorySystem


SCHEMA_VERSION = "memory-recall.v1"
DEFAULT_LAYERS = (
    "project", "function", "patterns", "sessions", "case", "code_knowledge", "constants", "semantic",
)


class MemoryRecallError(ValueError):
    """Raised when a memory recall request is malformed."""


def _truncate(value: Any, limit: int) -> Any:
    if isinstance(value, str):
        return value if len(value) <= limit else value[: max(0, limit - 3)] + "..."
    if isinstance(value, Mapping):
        return {str(key): _truncate(item, limit) for key, item in list(value.items())[:80]}
    if isinstance(value, list):
        return [_truncate(item, limit) for item in value[:40]]
    return value


def _layer_item(
    *,
    layer: str,
    status: str,
    value: Any,
    memory_dir: Path,
    path: Path | None = None,
    reason: str = "",
    provenance: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    item = {
        "layer": layer,
        "status": status,
        "value": _truncate(deepcopy(value), 8_000),
        "provenance": {
            "memory_dir": str(memory_dir),
            **(dict(provenance) if isinstance(provenance, Mapping) else {}),
        },
    }
    if path is not None:
        item["provenance"]["path"] = str(path)
    if reason:
        item["reason"] = reason
    return item


def _resolve_memory_location(
    project_root: Path,
    memory_dir: str,
    variant_id: str,
    context: Mapping[str, Any] | None = None,
) -> tuple[Path, dict[str, Any]]:
    context_value = context if isinstance(context, Mapping) else {}
    context_project = context_value.get("project") if isinstance(context_value.get("project"), Mapping) else {}
    context_source = context_value.get("source") if isinstance(context_value.get("source"), Mapping) else {}
    context_variant = str(
        variant_id
        or context_value.get("variant_id")
        or context_project.get("variant_id")
        or ""
    ).strip()
    context_memory_dir = str(
        memory_dir
        or context_value.get("memory_dir")
        or context_value.get("knowledge_dir")
        or context_source.get("memory_dir")
        or ""
    ).strip()
    if context_memory_dir:
        return Path(context_memory_dir).expanduser().resolve(), {
            "source": "orchestration_context" if not str(memory_dir or "").strip() else "explicit_input",
            "field": "memory_dir",
            "variant_id": context_variant,
        }
    # Do not silently select config.default_variant for a caller that has not
    # bound this run to a variant.  That would make a standalone Pi question
    # read another vehicle/project's code knowledge.  The unscoped legacy
    # directory may still provide operator notes, while code-derived layers
    # are withheld below until a scope is explicit.
    if not context_variant:
        return (project_root / "memory").resolve(), {"source": "unscoped_legacy", "field": "memory_dir"}
    try:
        from config import load_config, resolve_memory_dir

        config_path = project_root / "config.yaml"
        config = load_config(config_path) if config_path.is_file() else {}
        if context_variant:
            config = {**config, "identity": {**dict(config.get("identity", {}) or {}), "variant_id": context_variant}}
        return resolve_memory_dir(config, project_root, variant_id=context_variant or None).resolve(), {
            "source": "config",
            "field": "memory_dir",
            "variant_id": context_variant,
        }
    except (OSError, TypeError, ValueError, ImportError):
        return (project_root / "memory").resolve(), {"source": "fallback", "field": "memory_dir"}


def recall_memory(
    *,
    project_root: str,
    function: str = "",
    query: str = "",
    case_dir: str = "",
    variant_id: str = "",
    memory_dir: str = "",
    context: Mapping[str, Any] | None = None,
    context_path: str = "",
    layers: Sequence[str] | str | None = None,
    max_items: int = 5,
    max_chars: int = 6_000,
) -> dict[str, Any]:
    """Return existing memory as hints; never write or mutate memory."""
    root = Path(project_root).expanduser().resolve()
    if not root.is_dir():
        raise MemoryRecallError(f"project_root is not a directory: {root}")
    requested = [str(item).strip() for item in layers] if isinstance(layers, Sequence) and not isinstance(layers, (str, bytes)) else [item.strip() for item in str(layers).split(",") if item.strip()] if isinstance(layers, str) else list(DEFAULT_LAYERS)
    unknown = sorted(set(requested) - set(DEFAULT_LAYERS))
    if unknown:
        raise MemoryRecallError("unsupported memory layers: " + ", ".join(unknown))
    context_obj = deepcopy(dict(context)) if isinstance(context, Mapping) else None
    if context_obj is None and str(context_path or "").strip():
        context_file = Path(context_path).expanduser().resolve()
        try:
            value = json.loads(context_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise MemoryRecallError(f"context_invalid:{type(exc).__name__}:{context_file}") from exc
        if not isinstance(value, Mapping):
            raise MemoryRecallError("context_must_be_object")
        context_obj = dict(value)
    context_project = context_obj.get("project") if isinstance(context_obj, Mapping) and isinstance(context_obj.get("project"), Mapping) else {}
    bound_variant = str(variant_id or (context_obj or {}).get("variant_id") or context_project.get("variant_id") or "").strip()
    memory_path, location_provenance = _resolve_memory_location(root, memory_dir, bound_variant, context_obj)
    if context_path:
        location_provenance["context_path"] = str(Path(context_path).expanduser().resolve())
    scoped_memory = bool(str(memory_dir or "").strip() or bound_variant or context_obj)
    config: dict[str, Any] = {}
    try:
        from config import load_config

        config_path = root / "config.yaml"
        if config_path.is_file():
            config = load_config(config_path)
    except (OSError, TypeError, ValueError, ImportError):
        config = {}
    if bound_variant:
        config = {**config, "identity": {**dict(config.get("identity", {}) or {}), "variant_id": bound_variant}}
    system = MemorySystem(root, memory_dir=memory_path, config=config)
    function_name = str(function or "").strip()
    problem = str(query or "").strip()
    case_path = Path(case_dir).expanduser().resolve() if case_dir else None
    items: list[dict[str, Any]] = []

    if "project" in requested:
        path = memory_path / "project.md"
        value = system.read_project_memory()
        items.append(_layer_item(layer="project", status="available" if value else "not_available", value=value[:max_chars], memory_dir=memory_path, path=path, provenance=location_provenance))
    if "function" in requested:
        path = memory_path / "functions" / f"{function_name.upper()}.json" if function_name else None
        value = system.read_function_knowledge(function_name) if function_name else {}
        items.append(_layer_item(layer="function", status="available" if value else "not_available", value=value, memory_dir=memory_path, path=path, provenance=location_provenance))
    if "patterns" in requested:
        decision = runtime_knowledge_decision(config, "case_history") if scoped_memory else None
        if not scoped_memory:
            items.append(_layer_item(layer="patterns", status="blocked_stale", value=[], memory_dir=memory_path, reason="variant_id_or_memory_dir_required", provenance=location_provenance))
        elif not decision.allowed:
            items.append(_layer_item(layer="patterns", status="blocked_stale", value=[], memory_dir=memory_path, reason=", ".join(decision.reasons), provenance=location_provenance))
        else:
            keywords = [part for part in problem.replace("，", " ").replace(",", " ").split() if len(part) > 1]
            value = system.find_similar_patterns(function_name, keywords)[:max(0, int(max_items))] if function_name else []
            items.append(_layer_item(layer="patterns", status="available" if value else "not_available", value=value, memory_dir=memory_path, path=memory_path / "patterns.json", provenance=location_provenance))
    if "sessions" in requested:
        keywords = [part for part in problem.replace("，", " ").replace(",", " ").split() if len(part) > 1]
        value = system.query_sessions(function_name, keywords, max_results=max(0, int(max_items))) if function_name else []
        items.append(_layer_item(layer="sessions", status="available" if value else "not_available", value=value, memory_dir=memory_path, path=memory_path / "sessions", provenance=location_provenance))
    if "case" in requested:
        value = system.read_case_memory(case_path) if case_path else {}
        items.append(_layer_item(layer="case", status="available" if value else "not_available", value=value, memory_dir=memory_path, path=(case_path / "memory.json" if case_path else None), provenance=location_provenance))
    for layer, reader, filename, category in (
        ("code_knowledge", lambda: system.read_code_knowledge(function_name) if function_name else {}, "code_knowledge", "code_knowledge"),
        ("constants", system.read_constants, "constants.json", "code_knowledge:constants"),
    ):
        if layer not in requested:
            continue
        decision = runtime_knowledge_decision(config, category) if scoped_memory else None
        if not scoped_memory:
            items.append(_layer_item(layer=layer, status="blocked_stale", value={}, memory_dir=memory_path, path=memory_path / "code_knowledge" / filename, reason="variant_id_or_memory_dir_required", provenance=location_provenance))
            continue
        if not decision.allowed:
            items.append(_layer_item(layer=layer, status="blocked_stale", value={}, memory_dir=memory_path, path=memory_path / "code_knowledge" / filename, reason=", ".join(decision.reasons), provenance=location_provenance))
            continue
        value = reader()
        items.append(_layer_item(layer=layer, status="available" if value else "not_available", value=value, memory_dir=memory_path, path=memory_path / "code_knowledge" / filename, provenance=location_provenance))
    if "semantic" in requested:
        decision = runtime_knowledge_decision(config, "case_history") if scoped_memory else None
        if not scoped_memory:
            items.append(_layer_item(layer="semantic", status="blocked_stale", value=[], memory_dir=memory_path, path=memory_path / "semantic", reason="variant_id_or_memory_dir_required", provenance=location_provenance))
        elif not decision.allowed:
            items.append(_layer_item(layer="semantic", status="blocked_stale", value=[], memory_dir=memory_path, path=memory_path / "semantic", reason=", ".join(decision.reasons), provenance=location_provenance))
        else:
            value = system.search_semantic_cases(function_name, problem, case_dir=case_path, max_results=max_items) if problem else []
            items.append(_layer_item(layer="semantic", status="available" if value else "not_available", value=value, memory_dir=memory_path, path=memory_path / "semantic", reason="semantic hits are hints, not deterministic evidence" if value else "", provenance=location_provenance))

    available = sum(1 for item in items if item["status"] == "available")
    stale = sum(1 for item in items if item["status"] == "blocked_stale")
    status = "ready" if available else "partial" if stale else "not_available"
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "scope": {"function": function_name, "query": problem, "case_dir": str(case_path) if case_path else "", "variant_id": bound_variant, "layers": requested},
        "items": items,
        "summary": {"requested_layers": len(requested), "available_layers": available, "blocked_stale_layers": stale, "max_items": max_items},
        "policy": "Memory is additive context only. Code-derived memory requires current freshness; stale or missing knowledge is never silently used as current truth.",
    }


__all__ = ["SCHEMA_VERSION", "MemoryRecallError", "recall_memory"]
