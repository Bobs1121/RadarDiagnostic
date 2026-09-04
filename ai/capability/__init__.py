# -*- coding: utf-8 -*-
"""Per-step capability artifacts for the diagnosis pipeline.

This package hosts lightweight, JSON-serializable channels that the
orchestrator / ReAct agent / conversation bridge can use to surface
intermediate products (signals, windows, TPE hits, probe results) while a run
is still in progress, instead of only at final report time.

Public API:

* :func:`emit_artifact` — register a single artifact with the active registry.
* :class:`ArtifactRegistry` — append-only registry of per-step artifacts.
* :func:`resolve_project_context` — variant → isolated project context (P6).
* :func:`guard_project` — fail-closed cross-project guard (P6).
"""
from __future__ import annotations

from .artifacts import (
    ArtifactRegistry,
    ArtifactRecord,
    emit_artifact,
    get_default_registry,
    set_default_registry,
)
from .registry import (
    Capability,
    capability_catalog,
    catalog_json,
    list_capabilities,
)
from .project_context import (
    ProjectContext,
    ProjectIsolationError,
    guard_project,
    resolve_project_context,
    resolve_project_context_from_case,
)
from .module_bridge import (
    ModuleToolAdapter,
    available_module_tools,
    build_module_tool_registry,
)

__all__ = [
    "ArtifactRegistry",
    "ArtifactRecord",
    "emit_artifact",
    "get_default_registry",
    "set_default_registry",
    "Capability",
    "capability_catalog",
    "catalog_json",
    "list_capabilities",
    "ProjectContext",
    "ProjectIsolationError",
    "guard_project",
    "resolve_project_context",
    "resolve_project_context_from_case",
    "ModuleToolAdapter",
    "available_module_tools",
    "build_module_tool_registry",
]
