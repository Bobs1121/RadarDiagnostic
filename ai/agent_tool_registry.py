# -*- coding: utf-8 -*-
"""Workspace-aware builder for deterministic AgentLoop tool registries."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.materials import RequirementSpec, StructuredRequirementSet

from ai.tools.base import BaseTool

log = logging.getLogger(__name__)


@dataclass
class AgentToolContext:
    """Resolved inputs for deterministic tool construction."""

    project_root: Path | None = None
    config: dict[str, Any] | None = None
    workspace: Any | None = None
    store: Any | None = None
    codegraph: Any | None = None
    codegraph_db_path: Path | None = None
    req_set: Any | None = None
    requirement_dir: Path | None = None
    signal_mapping: dict[str, Any] | None = None
    source_root: Path | None = None
    cache_dir: Path | None = None


def _as_path(value: str | Path | None, project_root: Path | None = None) -> Path | None:
    if value in (None, ""):
        return None
    path = Path(value)
    if not path.is_absolute() and project_root is not None:
        path = project_root / path
    return path


def _first_non_empty(*values: Any) -> Any:
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return None


def _resolve_variant_id(config: dict[str, Any] | None) -> str:
    if not isinstance(config, dict):
        return ""

    identity = config.get("identity")
    if isinstance(identity, dict):
        variant_id = identity.get("variant_id")
        if isinstance(variant_id, str) and variant_id.strip():
            return variant_id.strip()

    try:
        from config import resolve_variant_id

        return str(resolve_variant_id(config, None) or "").strip()
    except Exception:
        return ""


def _load_signal_mapping(cache_dir: Path | None) -> dict[str, Any] | None:
    if cache_dir is None:
        return None
    path = cache_dir / "signal_mapping.json"
    if not path.exists() or not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("Failed to read signal mapping cache %s: %s", path, exc)
        return None
    return data if isinstance(data, dict) else None


def _has_requirements(req_set: Any) -> bool:
    if req_set is None:
        return False
    reqs = getattr(req_set, "requirements", None)
    if isinstance(reqs, dict):
        return bool(reqs)
    if isinstance(req_set, dict):
        nested = req_set.get("requirements")
        if isinstance(nested, dict):
            return bool(nested)
        return any(key != "variant_id" for key in req_set)
    return False


def _coerce_workspace_requirements(raw: Any, variant_id: str = "") -> StructuredRequirementSet | None:
    """Convert Workspace.get_requirements_schema() output into a requirement set."""
    if not isinstance(raw, dict) or not raw:
        return None

    req_set = StructuredRequirementSet(variant_id=variant_id)
    for key, value in raw.items():
        if not isinstance(value, dict):
            continue
        spec = RequirementSpec.from_dict(value)
        if not spec.requirement_id:
            spec.requirement_id = str(
                value.get("req_id")
                or value.get("requirement_id")
                or key
            )
        if not spec.statement:
            spec.statement = str(
                value.get("statement")
                or value.get("description")
                or value.get("feature")
                or ""
            )
        if not spec.variant_id:
            spec.variant_id = variant_id
        req_set.add(spec)

    return req_set if req_set.requirements else None


def resolve_agent_tool_context(
    *,
    config: dict[str, Any] | None = None,
    workspace: Any | None = None,
    project_root: str | Path | None = None,
    store: Any | None = None,
    codegraph: Any | None = None,
    codegraph_db_path: str | Path | None = None,
    req_set: Any | None = None,
    requirement_dir: str | Path | None = None,
    signal_mapping: dict[str, Any] | None = None,
    source_root: str | Path | None = None,
    cache_dir: str | Path | None = None,
) -> AgentToolContext:
    """Resolve deterministic tool-construction inputs from config/workspace."""

    resolved_project_root = _as_path(project_root)

    workspace_config: dict[str, Any] | None = None
    if workspace is not None:
        try:
            candidate = workspace.get_config()
        except Exception as exc:
            log.warning("workspace.get_config() failed during tool context resolution: %s", exc)
        else:
            if isinstance(candidate, dict):
                workspace_config = candidate

    resolved_config = config if isinstance(config, dict) else workspace_config
    variant_id = _resolve_variant_id(resolved_config) or _resolve_variant_id(workspace_config)

    resolved_source_root = _as_path(source_root, resolved_project_root)
    if resolved_source_root is None:
        raw_source = None
        if isinstance(resolved_config, dict):
            raw_source = _first_non_empty(
                resolved_config.get("paths", {}).get("source_code")
                if isinstance(resolved_config.get("paths"), dict) else None,
                resolved_config.get("project", {}).get("source_code")
                if isinstance(resolved_config.get("project"), dict) else None,
            )
        resolved_source_root = _as_path(raw_source, resolved_project_root)

    if resolved_source_root is None and workspace is not None:
        try:
            source_paths = workspace.get_source_paths()
        except Exception as exc:
            log.warning("workspace.get_source_paths() failed during tool context resolution: %s", exc)
        else:
            for candidate in source_paths or []:
                candidate_path = _as_path(candidate)
                if candidate_path is not None:
                    resolved_source_root = candidate_path
                    break

    resolved_cache_dir = _as_path(cache_dir, resolved_project_root)
    if resolved_cache_dir is None and isinstance(resolved_config, dict):
        raw_cache = _first_non_empty(
            resolved_config.get("project", {}).get("source_docs_dir")
            if isinstance(resolved_config.get("project"), dict) else None,
            resolved_config.get("paths", {}).get("source_docs")
            if isinstance(resolved_config.get("paths"), dict) else None,
        )
        resolved_cache_dir = _as_path(raw_cache, resolved_project_root)

    if resolved_cache_dir is None and resolved_project_root is not None and isinstance(resolved_config, dict):
        try:
            from config import resolve_source_docs_dir

            resolved_cache_dir = resolve_source_docs_dir(
                resolved_config,
                resolved_project_root,
                variant_id=variant_id or None,
            )
        except Exception:
            resolved_cache_dir = None

    if resolved_cache_dir is None and workspace is not None:
        try:
            resolved_cache_dir = _as_path(workspace.get_memory_dir())
        except Exception as exc:
            log.warning("workspace.get_memory_dir() failed during tool context resolution: %s", exc)

    resolved_codegraph_db_path = _as_path(codegraph_db_path, resolved_project_root)
    has_explicit_config_db_path = False
    if resolved_codegraph_db_path is None and isinstance(resolved_config, dict):
        raw_db_path = None
        project_cfg = resolved_config.get("project")
        if isinstance(project_cfg, dict):
            raw_db_path = project_cfg.get("codegraph_db_path")
        if raw_db_path:
            resolved_codegraph_db_path = _as_path(raw_db_path, resolved_project_root)
            has_explicit_config_db_path = True

    if not has_explicit_config_db_path and workspace is not None:
        try:
            memory_dir = _as_path(workspace.get_memory_dir())
        except Exception as exc:
            log.warning("workspace.get_memory_dir() failed during codegraph resolution: %s", exc)
            memory_dir = None
        if memory_dir is not None:
            for candidate in (
                memory_dir / "codegraph.db",
                memory_dir / "codegraph" / "codegraph.db",
                memory_dir / "codegraph" / f"codegraph_{workspace.name}.db",
            ):
                if candidate.exists():
                    resolved_codegraph_db_path = candidate
                    break

    if resolved_codegraph_db_path is None and isinstance(resolved_config, dict):
        if resolved_project_root is not None:
            try:
                from config import resolve_codegraph_db

                resolved_codegraph_db_path = resolve_codegraph_db(
                    resolved_config,
                    resolved_project_root,
                    variant_id=variant_id or None,
                )
            except Exception:
                resolved_codegraph_db_path = None

    resolved_requirement_dir = _as_path(requirement_dir, resolved_project_root)
    if resolved_requirement_dir is None and isinstance(resolved_config, dict):
        raw_req_dir = None
        project_cfg = resolved_config.get("project")
        if isinstance(project_cfg, dict):
            raw_req_dir = project_cfg.get("requirement_dir")
        if raw_req_dir:
            resolved_requirement_dir = _as_path(raw_req_dir, resolved_project_root)

    if resolved_requirement_dir is None and workspace is not None:
        workspace_dir = _as_path(getattr(workspace, "workspace_dir", None))
        if workspace_dir is not None:
            resolved_requirement_dir = workspace_dir / "requirements"

    resolved_signal_mapping = signal_mapping
    if resolved_signal_mapping is None:
        resolved_signal_mapping = _load_signal_mapping(resolved_cache_dir)

    resolved_req_set = req_set
    if resolved_req_set is None and resolved_requirement_dir is not None:
        if resolved_requirement_dir.exists() and resolved_requirement_dir.is_dir():
            from ai.requirements.loader import RequirementLoader

            resolved_req_set = RequirementLoader().load_yaml_dir(
                resolved_requirement_dir,
                variant_id=variant_id,
            )

    if resolved_req_set is None and workspace is not None:
        try:
            raw_workspace_reqs = workspace.get_requirements_schema()
        except Exception as exc:
            log.warning("workspace.get_requirements_schema() failed during tool context resolution: %s", exc)
        else:
            resolved_req_set = _coerce_workspace_requirements(raw_workspace_reqs, variant_id)

    return AgentToolContext(
        project_root=resolved_project_root,
        config=resolved_config,
        workspace=workspace,
        store=store,
        codegraph=codegraph,
        codegraph_db_path=resolved_codegraph_db_path,
        req_set=resolved_req_set,
        requirement_dir=resolved_requirement_dir,
        signal_mapping=resolved_signal_mapping,
        source_root=resolved_source_root,
        cache_dir=resolved_cache_dir,
    )


def build_agent_tool_registry(context: AgentToolContext) -> dict[str, BaseTool]:
    """Build a deterministic tool registry from resolved runtime context."""

    from ai.tools.code_tools import (
        ExtractASTDependencyTool,
        FindCodeDefinitionTool,
        TraceRequirementTool,
    )
    from ai.tools.data_tools import (
        DetectTimePatternTool,
        PlotSignalTool,
        QueryCanDataTool,
    )

    registry: dict[str, BaseTool] = {}

    if context.store is not None:
        registry[QueryCanDataTool.name] = QueryCanDataTool(store=context.store)
        registry[PlotSignalTool.name] = PlotSignalTool(store=context.store)

        if context.source_root is not None and context.source_root.exists():
            registry[DetectTimePatternTool.name] = DetectTimePatternTool(
                store=context.store,
                source_root=context.source_root,
                cache_dir=context.cache_dir,
                signal_mapping=context.signal_mapping,
            )

    has_code_backend = context.codegraph is not None or (
        context.codegraph_db_path is not None and context.codegraph_db_path.exists()
    )
    if not has_code_backend:
        return registry

    code_kwargs: dict[str, Any] = {}
    if context.codegraph is not None:
        code_kwargs["codegraph"] = context.codegraph
    if context.codegraph_db_path is not None and context.codegraph_db_path.exists():
        code_kwargs["db_path"] = context.codegraph_db_path

    registry[FindCodeDefinitionTool.name] = FindCodeDefinitionTool(**code_kwargs)
    registry[ExtractASTDependencyTool.name] = ExtractASTDependencyTool(**code_kwargs)

    if _has_requirements(context.req_set):
        registry[TraceRequirementTool.name] = TraceRequirementTool(
            req_set=context.req_set,
            signal_mapping=context.signal_mapping,
            **code_kwargs,
        )

    return registry


__all__ = [
    "AgentToolContext",
    "build_agent_tool_registry",
    "resolve_agent_tool_context",
]
