# -*- coding: utf-8 -*-
"""
Config loader with multi-project support and identity hierarchy.

Loads config.yaml, resolves environment variables, and provides helpers
for both the legacy `project_key` model and the new five-layer identity
hierarchy (PlatformFamily → Codebase → Variant → PackageProfile → Snapshot).

Backward compatibility:
    - `get_project(key)` still works — internally bridges to Variant.
    - `load_config()` backfills `paths.*` from the default project.
    - New code should use `get_variant()`, `get_package_profile()`, etc.

Public API:
    load_config(path)               → full config dict
    get_project(config, key)         → legacy project dict (bridged)
    get_variant(config, variant_id)  → Variant object
    get_codebase(config, codebase_id)→ Codebase object
    get_platform(config, platform_id)→ PlatformFamily object
    get_package_profile(config, pid) → PackageProfile object
    resolve_variant_id(config, project_key_or_variant) → str
    resolve_codegraph_db(...), resolve_source_docs_dir(...), resolve_memory_dir(...)
    get_variable_filter(config)
    should_include_variable(name, scope, filter_cfg)
"""
from __future__ import annotations

import logging
import re as _re
import os
from pathlib import Path
from typing import Any, Optional

import yaml

log = logging.getLogger(__name__)

_ENV_RE = _re.compile(r"\$\{(\w+)(?::-([^}]*))?\}")


def _resolve_env(value: str) -> str:
    """Expand ${VAR} and ${VAR:-default} placeholders in strings."""

    def _replacer(m: _re.Match) -> str:
        var_name = m.group(1)
        default = m.group(2)
        return os.environ.get(var_name, default if default is not None else "")

    return _ENV_RE.sub(_replacer, value)


def _resolve_values(obj):
    """Recursively expand env vars in strings inside dicts/lists."""
    if isinstance(obj, str):
        return _resolve_env(obj)
    if isinstance(obj, dict):
        return {k: _resolve_values(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_resolve_values(v) for v in obj]
    return obj


def load_config(config_path: str | Path | None = None) -> dict:
    """Load config.yaml and return the fully resolved configuration dict.

    Args:
        config_path: Path to config.yaml.  Defaults to `config.yaml`
                     next to this file (radarAnalyze project root).
    """
    if config_path is None:
        config_path = Path(__file__).parent / "config.yaml"
    else:
        config_path = Path(config_path)

    if not config_path.exists():
        raise FileNotFoundError(f"Config not found: {config_path}")

    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config = _resolve_values(raw)

    # ── Backward-compat shim: populate paths.source_code from default project ──
    projects = config.get("projects", {})
    default_key = config.get("default_project", "")

    if default_key and default_key in projects:
        proj = projects[default_key]
        paths = config.setdefault("paths", {})
        # Only set if not already present (explicit paths.source_code wins)
        if "source_code" not in paths and "source_code" in proj:
            paths["source_code"] = proj["source_code"]
        if "dbc_files" not in paths and "dbc_files" in proj:
            paths["dbc_files"] = proj["dbc_files"]
        if "key_source_files" not in paths and "key_source_files" in proj:
            paths["key_source_files"] = proj["key_source_files"]
    elif "paths" in config and "source_code" in config["paths"]:
        log.warning(
            "paths.source_code is deprecated; use projects/<key>/source_code instead"
        )

    return config


# ─── Legacy: get_project (bridges to Variant internally) ──────────────

# Mapping from legacy project_key → variant_id
_PROJECT_KEY_TO_VARIANT: dict[str, str] = {
    "gwm_b26": "gen6/gwm_b26",
    "sc6h": "gen6/byd_sc6h",
    "cr5cb": "gen5/byd",
}


def get_project(config: dict, project_key: str | None = None) -> dict:
    """Return the resolved project configuration dict.

    LEGACY API — bridges to the new identity hierarchy.  If the variant
    system has a matching entry, its data is used.  Otherwise falls back
    to the old `projects.*` block.

    Args:
        config: Loaded configuration dict (from `load_config`).
        project_key: Project key from CLI -P flag.  Falls back to
                     `default_project` in config.

    Returns:
        Dict with keys: display_name, source_code, key_source_files,
        dbc_files, source_docs_dir, memory_dir, codegraph_db_path.
    """
    projects = config.get("projects", {})
    if not project_key:
        project_key = config.get("default_project", "")

    if not project_key or project_key not in projects:
        raise ValueError(
            f"Project '{project_key}' not found. "
            f"Available: {list(projects.keys())}"
        )

    proj = dict(projects[project_key])
    project_root = Path(__file__).parent  # radarAnalyze root

    # Compute derived paths — per-project scopes
    proj_safe = project_key.replace(" ", "_").lower()
    proj["source_docs_dir"] = str(project_root / "source_docs" / proj_safe)
    proj["memory_dir"] = str(project_root / "memory" / "projects" / proj_safe)
    proj["codegraph_db_path"] = str(
        project_root / "memory" / "codegraph" / f"codegraph_{proj_safe}.db"
    )
    proj["_project_key"] = project_key

    # Resolve source_code to absolute path
    source_code = proj.get("source_code", "")
    if source_code and not Path(source_code).is_absolute():
        source_code = str(project_root / source_code)
    proj["source_code"] = source_code

    return proj


# ─── New: Identity Hierarchy Accessors ───────────────────────────────

def _import_identity_models():
    """Lazy import to avoid circular dependency."""
    from core.identity import (
        PlatformFamily, Codebase, Variant, VariantScope, DBCSet,
        PackageProfile, BuildFlags, PatchSet,
    )
    return PlatformFamily, Codebase, Variant, VariantScope, DBCSet, PackageProfile, BuildFlags, PatchSet


def get_platform(config: dict, platform_id: str) -> Any:
    """Get a PlatformFamily by ID."""
    platforms = config.get("platforms", {})
    if platform_id not in platforms:
        raise ValueError(f"Platform '{platform_id}' not found. Available: {list(platforms.keys())}")
    PF, = _import_identity_models()[0],
    pf_raw = {**platforms[platform_id], "platform_id": platform_id}
    return PF.from_dict(pf_raw)


def get_codebase(config: dict, codebase_id: str) -> Any:
    """Get a Codebase by ID."""
    codebases = config.get("codebases", {})
    if codebase_id not in codebases:
        raise ValueError(f"Codebase '{codebase_id}' not found. Available: {list(codebases.keys())}")
    CB, = _import_identity_models()[1:2]
    cb_raw = {**codebases[codebase_id], "codebase_id": codebase_id}
    return CB.from_dict(cb_raw)


def get_variant(config: dict, variant_id: str | None = None) -> tuple[Any, Any, Any]:
    """Get a Variant by ID, resolving to full identity chain.

    Returns:
        (variant, codebase, platform) — all as dataclass objects.
    """
    if not variant_id:
        variant_id = config.get("default_variant", "")
        if not variant_id:
            # Fall back: derive from default_project
            default_proj = config.get("default_project", "")
            variant_id = _PROJECT_KEY_TO_VARIANT.get(default_proj, default_proj)

    variants = config.get("variants", {})
    if variant_id not in variants:
        raise ValueError(f"Variant '{variant_id}' not found. Available: {list(variants.keys())}")

    PF, CB, V = _import_identity_models()[:3]
    v_raw = variants[variant_id]
    # Inject variant_id into raw dict so from_dict can use it
    v_raw_with_id = {**v_raw, "variant_id": variant_id}
    variant = V.from_dict(v_raw_with_id)

    cb_id = variant.codebase_id
    codebase = get_codebase(config, cb_id)
    platform = None
    if codebase.platform_id:
        try:
            platform = get_platform(config, codebase.platform_id)
        except ValueError:
            pass

    return variant, codebase, platform


def get_package_profile(config: dict, profile_id: str | None = None) -> Any:
    """Get a PackageProfile by ID."""
    profiles = config.get("package_profiles", {})
    if not profile_id:
        # Default: resolve from default_variant's default_package_profile
        variant, _, _ = get_variant(config)
        profile_id = variant.default_package_profile

    if profile_id not in profiles:
        raise ValueError(f"PackageProfile '{profile_id}' not found. Available: {list(profiles.keys())}")

    _, _, _, _, _, PP, _, _ = _import_identity_models()
    # Inject package_profile_id into raw dict so from_dict can use it
    pp_raw = {**profiles[profile_id], "package_profile_id": profile_id}
    return PP.from_dict(pp_raw)


def resolve_variant_id(config: dict, identifier: str | None) -> str:
    """Resolve a project_key OR variant_id to a canonical variant_id.

    Accepts:
        - Legacy project_key (e.g. "gwm_b26") → maps to variant_id
        - Variant_id (e.g. "gen6/gwm_b26") → returns as-is
        - None → uses default_variant or default_project

    This is the bridge function for CLI args and config resolution.
    """
    if not identifier:
        identifier = config.get("default_variant", "")
        if not identifier:
            dp = config.get("default_project", "")
            identifier = _PROJECT_KEY_TO_VARIANT.get(dp, dp)

    # Check if it's already a variant_id
    variants = config.get("variants", {})
    if identifier in variants:
        return identifier

    # Try to map from project_key
    mapped = _PROJECT_KEY_TO_VARIANT.get(identifier)
    if mapped:
        return mapped

    # If neither, assume it's a variant_id anyway (may fail later)
    return identifier


def resolve_source_code(config: dict, project_key: str | None = None) -> str:
    """Resolve the source_code path for a given project_key or variant_id.

    Tries variant system first, falls back to legacy projects.*
    """
    try:
        variant_id = resolve_variant_id(config, project_key)
        variant, codebase, _ = get_variant(config, variant_id)
        return str(codebase.root_path)
    except ValueError:
        pass

    # Fallback to legacy
    proj = get_project(config, project_key)
    return proj.get("source_code", "")


def resolve_codegraph_db(config: dict, project_root: Path, project_key: str | None = None, variant_id: str | None = None) -> Path:
    """Resolve CodeGraph DB path from config.

    Supports both legacy project_key and new variant_id.
    Priority: variant_id > project_key > config["project"] (injected by CLI) > global default.
    """
    # 1. Try variant system
    if variant_id or project_key:
        effective_variant = resolve_variant_id(config, variant_id or project_key)
        try:
            variant, codebase, _ = get_variant(config, effective_variant)
            proj_safe = effective_variant.replace("/", "_").replace(" ", "_").lower()
            return project_root / "memory" / "codegraph" / f"codegraph_{proj_safe}.db"
        except ValueError:
            pass

    # 2. Try legacy project_key
    if project_key:
        try:
            proj = get_project(config, project_key)
            return Path(proj.get("codegraph_db_path", project_root / "memory" / "codegraph.db"))
        except ValueError:
            pass

    # 3. Fall back to config["project"] (injected by cli.load_config)
    proj = config.get("project", {})
    if proj:
        path = proj.get("codegraph_db_path")
        if path:
            return Path(path)

    # 4. Global default
    return project_root / "memory" / "codegraph.db"


def resolve_source_docs_dir(config: dict, project_root: Path, project_key: str | None = None, variant_id: str | None = None) -> Path:
    """Resolve source_docs directory from config.

    Supports both legacy project_key and new variant_id.
    Priority: variant_id > project_key > config["paths"] > global default.
    """
    # 1. Try variant system
    if variant_id or project_key:
        effective_variant = resolve_variant_id(config, variant_id or project_key)
        try:
            variant, codebase, _ = get_variant(config, effective_variant)
            proj_safe = effective_variant.replace("/", "_").replace(" ", "_").lower()
            return project_root / "source_docs" / proj_safe
        except ValueError:
            pass

    # 2. Try legacy project_key
    if project_key:
        try:
            proj = get_project(config, project_key)
            return Path(proj.get("source_docs_dir", project_root / "source_docs"))
        except ValueError:
            pass

    # 3. Fall back to config["paths"] (injected by cli.load_config)
    return Path(config.get("paths", {}).get("source_docs", project_root / "source_docs"))


def resolve_memory_dir(config: dict, project_root: Path, project_key: str | None = None, variant_id: str | None = None) -> Path:
    """Resolve memory directory from config.

    Supports both legacy project_key and new variant_id.
    Priority: variant_id > project_key > config["project"] > global default.
    """
    # 1. Try variant system
    if variant_id or project_key:
        effective_variant = resolve_variant_id(config, variant_id or project_key)
        try:
            variant, codebase, _ = get_variant(config, effective_variant)
            proj_safe = effective_variant.replace("/", "_").replace(" ", "_").lower()
            return project_root / "memory" / "projects" / proj_safe
        except ValueError:
            pass

    # 2. Try legacy project_key
    if project_key:
        try:
            proj = get_project(config, project_key)
            return Path(proj.get("memory_dir", project_root / "memory"))
        except ValueError:
            pass

    # 3. Fall back to config["project"] (injected by cli.load_config)
    proj = config.get("project", {})
    if proj:
        path = proj.get("memory_dir")
        if path:
            return Path(path)

    # 4. Global default
    return project_root / "memory"


# ── Variable Filter (Phase 5B) ─────────────────────────────────────────────
import re as _variable_re

def get_variable_filter(config: dict) -> dict:
    """Return the variable filter configuration with defaults.

    Returns a dict with keys:
      min_name_length (int)
      exclude_patterns (list[str])  — precompiled regex
      include_patterns (list[str])  — precompiled regex
      scopes (list[str])
    """
    vf = config.get("variable_filter", {})
    min_len = int(vf.get("min_name_length", 4))

    exclude_raw = vf.get("exclude_patterns", [])
    include_raw = vf.get("include_patterns", [])
    scopes = vf.get("scopes", ["global", "file_static"])

    return {
        "min_name_length": min_len,
        "exclude_patterns": [_variable_re.compile(p) for p in exclude_raw],
        "include_patterns": [_variable_re.compile(p) for p in include_raw],
        "scopes": scopes,
    }


def should_include_variable(name: str, scope: str | None, filter_cfg: dict) -> bool:
    """Check if a variable should be included in CodeGraph.

    Args:
        name: Variable identifier name.
        scope: Variable scope ("global", "file_static", "local", "parameter").
        filter_cfg: Output of get_variable_filter().

    Returns:
        True if the variable should be kept, False if it should be filtered out.
    """
    min_len = filter_cfg["min_name_length"]
    allowed_scopes = filter_cfg["scopes"]

    # 1. Scope filter
    if scope and scope not in allowed_scopes:
        return False

    # 2. Length filter — short names are almost always noise
    if len(name) < min_len:
        return False

    # 3. Exclude patterns (hard exclusion)
    for pattern in filter_cfg["exclude_patterns"]:
        if pattern.search(name):
            return False

    # 4. Include patterns (whitelist — if any matches, keep it)
    for pattern in filter_cfg["include_patterns"]:
        if pattern.search(name):
            return True

    # 5. Default: reject variables that don't match any include pattern
    #    This ensures we only keep diagnostically meaningful variables
    return False
