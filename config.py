# -*- coding: utf-8 -*-
"""
Config loader with multi-project support.

Loads config.yaml, resolves environment variables, and provides a
`get_project(key)` helper that returns the resolved project dict.

Backward compatibility: code that reads config["paths"]["source_code"]
will get a deprecation warning but still works — the value is forwarded
from the default project's `source_code`.
"""
from __future__ import annotations

import logging
import re as _re
import os
from pathlib import Path

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


def get_project(config: dict, project_key: str | None = None) -> dict:
    """Return the resolved project configuration dict.

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


def resolve_codegraph_db(config: dict, project_root: Path, project_key: str | None = None) -> Path:
    """Resolve CodeGraph DB path from config, with fallback.

    If project_key is given, uses get_project(config, project_key) to find
    the per-project DB path.  Otherwise falls back to config["project"]
    (injected by cli.load_config) or the global default.
    """
    if project_key:
        proj = get_project(config, project_key)
        return Path(proj.get("codegraph_db_path", project_root / "memory" / "codegraph.db"))
    proj = config.get("project", {})
    return Path(proj.get("codegraph_db_path", project_root / "memory" / "codegraph.db"))


def resolve_source_docs_dir(config: dict, project_root: Path, project_key: str | None = None) -> Path:
    """Resolve source_docs directory from config, with fallback.

    If project_key is given, uses get_project(config, project_key) to find
    the per-project source_docs_dir.  Otherwise falls back to config["paths"]
    (injected by cli.load_config) or the global default.
    """
    if project_key:
        proj = get_project(config, project_key)
        return Path(proj.get("source_docs_dir", project_root / "source_docs"))
    return Path(config.get("paths", {}).get("source_docs", project_root / "source_docs"))


def resolve_memory_dir(config: dict, project_root: Path, project_key: str | None = None) -> Path:
    """Resolve memory directory from config, with fallback.

    If project_key is given, uses get_project(config, project_key) to find
    the per-project memory_dir.  Otherwise falls back to config["project"]
    (injected by cli.load_config) or the global default.
    """
    if project_key:
        proj = get_project(config, project_key)
        return Path(proj.get("memory_dir", project_root / "memory"))
    proj = config.get("project", {})
    return Path(proj.get("memory_dir", project_root / "memory"))


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
