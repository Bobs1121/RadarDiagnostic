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
    expand_project_intake(config, project_root) → config with generated internal entries
    get_project(config, key)         → legacy project dict (bridged)
    get_variant(config, variant_id)  → Variant object
    get_codebase(config, codebase_id)→ Codebase object
    get_platform(config, platform_id)→ PlatformFamily object
    get_package_profile(config, pid) → PackageProfile object
    resolve_variant_id(config, project_key_or_variant) → str
    resolve_codegraph_db(...), resolve_source_docs_dir(...), resolve_memory_dir(...)
    resolve_workspace_dir(...), resolve_snapshots_dir(...)
    get_variable_filter(config)
    should_include_variable(name, scope, filter_cfg)
"""
from __future__ import annotations

import logging
import re as _re
import os
from pathlib import Path
from typing import Any, Optional, Dict, List

import yaml

log = logging.getLogger(__name__)

_ENV_RE = _re.compile(r"\$\{(\w+)(?::-([^}]*))?\}")
_INTAKE_KEY_SOURCE_BASENAMES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("algorithm", ("adasFunc.c", "adasFunc.h")),
    ("system_state", ("ASWIN_SystemState.c", "ASWIN_SystemState.h",
                      "ASWIN_AdasState.c", "ASWIN_AdasState.h")),
    ("constants", ("dotCalibDefine.h", "AswIfSchedule.c")),
    ("signal_chain", ("RteComMapping.c", "RteComMapping.h")),
    ("output", ("ASWOUT_OutCalc.c",)),
    (
        "perception",
        (
            "objAttribCal.c",
            "track.c",
            "postProcess.c",
            "perception_public_def.h",
            "structDefine.h",
            "paraDefine.h",
            "globalVarDefine.h",
        ),
    ),
    # ── Xpeng Reco (Bosch gen5 RCC1010 CornerBase) ────────────────────
    (
        "xpeng_fct_cfm",
        (
            "sit_s_runnableCfmRearCrossTraffic.cpp",
            "sit_s_runnableCfmDoorOpening.cpp",
            "sit_s_behaviorRctaBrakingFM.cpp",
            "sit_s_behaviorRctaWarningFM.cpp",
        ),
    ),
    (
        "xpeng_per_spp",
        (
            "per_sppRLocRunnable.cpp",
            "per_sppBdmRunnable.cpp",
            "per_sppStalinRunnable.cpp",
        ),
    ),
    (
        "xpeng_sit_object",
        (
            "sit_s_objectSelector.hpp",
        ),
    ),
    (
        "xpeng_per_interfaces",
        (
            "per_fusedObjectsDynamic.hpp",
            "per_blindnessDetectionData.hpp",
            "per_radarBoschGen5Feature.hpp",
        ),
    ),
    (
        "xpeng_fct_fsm",
        (
            "fct_s_pssStateMachine.hpp",
            "fct_s_behaviorManager.cpp",
            "decisionMakerController.hpp",
        ),
    ),
)


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


def _deep_merge_config(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge dictionaries while letting override values replace base values."""
    merged = dict(base)
    for key, value in override.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged[key] = _deep_merge_config(current, value)
        else:
            merged[key] = value
    return merged


def _load_yaml_mapping(path: Path, *, label: str) -> dict[str, Any]:
    """Load a YAML mapping, raising a clear ValueError for invalid local config."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid {label} YAML at {path}: {exc}") from exc

    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(f"{label} at {path} must contain a YAML mapping/object")
    return raw


def sanitize_variant_workspace_name(variant_id: str) -> str:
    """Return the workspace-safe sandbox name for a variant id."""
    return variant_id.replace("/", "_").replace("\\", "_")


def _resolve_path_setting(project_root: Path, value: Any) -> Path | None:
    """Resolve config path values relative to the project root when needed."""
    if value in (None, ""):
        return None
    path = Path(str(value)).expanduser()
    if not path.is_absolute():
        path = (project_root / path).resolve()
    else:
        path = path.resolve()
    return path


def _resolve_source_context_settings(config: dict, variant_id: str | None = None) -> dict[str, Any]:
    """Return top-level source_context merged with per-variant overrides."""
    merged: dict[str, Any] = {}
    base = config.get("source_context")
    if isinstance(base, dict):
        merged = _deep_merge_config(merged, base)
    if variant_id:
        variant = config.get("variants", {}).get(variant_id, {})
        variant_ctx = variant.get("source_context") if isinstance(variant, dict) else None
        if isinstance(variant_ctx, dict):
            merged = _deep_merge_config(merged, variant_ctx)
    return merged


def _normalize_identity_segment(value: str) -> str:
    slug = _re.sub(r"[^a-z0-9]+", "_", str(value).lower()).strip("_")
    slug = _re.sub(r"_+", "_", slug)
    return slug or "project"


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _resolve_intake_path(project_root: Path, value: str) -> Path:
    expanded = _resolve_env(str(value).strip())
    path = Path(expanded).expanduser()
    if not path.is_absolute():
        path = (project_root / path).resolve()
    else:
        path = path.resolve()
    return path


def _relative_posix(path: Path, root: Path) -> str:
    return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")


def _relative_windows(path: Path, root: Path) -> str:
    return str(path.resolve().relative_to(root.resolve())).replace("/", "\\")


def _coerce_string_list(value: Any, field_path: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        stripped = value.strip()
        return [stripped] if stripped else []
    if not isinstance(value, list):
        raise ValueError(f"{field_path} must be a string or list of strings")

    values: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str):
            raise ValueError(f"{field_path}[{index}] must be a string")
        stripped = item.strip()
        if stripped:
            values.append(stripped)
    return values


def _require_project_intake_field(entry: dict[str, Any], project_key: str, field_name: str) -> str:
    value = entry.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            f"project_intake.projects.{project_key}.{field_name} is required"
        )
    return value.strip()


def _normalize_coem_project_dir(coem_value: str, *, prepend_coem: bool = True) -> str:
    normalized = str(coem_value).strip().replace("\\", "/").strip("/")
    if normalized.startswith("coem/"):
        normalized = normalized[5:]
    normalized = normalized.strip("/")
    if not normalized:
        raise ValueError("coem cannot be empty")
    if prepend_coem:
        return f"coem/{normalized}"
    return normalized


def _infer_customer_vehicle(
    coem_project_dir: str,
    *,
    customer: Any = None,
    vehicle_project: Any = None,
) -> tuple[str, str]:
    coem_name = coem_project_dir.replace("\\", "/").split("/")[-1]
    tokens = [token for token in _re.split(r"[^A-Za-z0-9]+", coem_name) if token]
    inferred_customer = tokens[0] if tokens else coem_name
    inferred_vehicle = "_".join(tokens[1:]) if len(tokens) > 1 else ""

    explicit_customer = str(customer).strip() if customer is not None else ""
    explicit_vehicle = str(vehicle_project).strip() if vehicle_project is not None else ""
    return explicit_customer or inferred_customer, explicit_vehicle or inferred_vehicle


def _generate_project_intake_codebase_id(
    project_key: str,
    code_root_path: Path,
    existing_codebases: dict[str, Any],
    generated_codebases: dict[str, Any],
) -> str:
    preferred = _normalize_identity_segment(code_root_path.name)
    existing_root = existing_codebases.get(preferred, {}).get("root_path")
    generated_root = generated_codebases.get(preferred, {}).get("root_path")
    if existing_root == str(code_root_path) or generated_root == str(code_root_path):
        return preferred
    if preferred not in existing_codebases and preferred not in generated_codebases:
        return preferred

    project_suffix = _normalize_identity_segment(project_key)
    fallback = f"{preferred}_{project_suffix}"
    existing_root = existing_codebases.get(fallback, {}).get("root_path")
    generated_root = generated_codebases.get(fallback, {}).get("root_path")
    if existing_root == str(code_root_path) or generated_root == str(code_root_path):
        return fallback
    if fallback not in existing_codebases and fallback not in generated_codebases:
        return fallback

    raise ValueError(
        "Unable to generate a stable codebase id for "
        f"project_intake.projects.{project_key}; tried '{preferred}' and '{fallback}'"
    )


def _expand_project_intake_dbc_files(
    project_root: Path,
    project_key: str,
    dbc_value: Any,
) -> list[str]:
    dbc_inputs = _coerce_string_list(
        dbc_value,
        f"project_intake.projects.{project_key}.dbc",
    )
    if not dbc_inputs:
        raise ValueError(f"project_intake.projects.{project_key}.dbc is required")

    resolved_files: list[Path] = []
    for index, raw_path in enumerate(dbc_inputs):
        field_path = f"project_intake.projects.{project_key}.dbc[{index}]"
        path = _resolve_intake_path(project_root, raw_path)
        if not path.exists():
            raise ValueError(f"{field_path} not found: {path}")
        if path.is_dir():
            matches = sorted(
                [item.resolve() for item in path.rglob("*.dbc") if item.is_file()],
                key=lambda item: str(item).lower(),
            )
            if not matches:
                raise ValueError(f"{field_path} contains no .dbc files: {path}")
            resolved_files.extend(matches)
            continue
        resolved_files.append(path.resolve())

    ordered = _dedupe_preserve_order([str(path) for path in resolved_files])
    return sorted(ordered, key=str.lower)


def _expand_project_intake_requirement_paths(
    project_root: Path,
    project_key: str,
    requirements_value: Any,
) -> list[str]:
    requirement_inputs = _coerce_string_list(
        requirements_value,
        f"project_intake.projects.{project_key}.requirements",
    )
    resolved_paths: list[str] = []
    for index, raw_path in enumerate(requirement_inputs):
        field_path = f"project_intake.projects.{project_key}.requirements[{index}]"
        path = _resolve_intake_path(project_root, raw_path)
        if not path.exists():
            raise ValueError(f"{field_path} not found: {path}")
        resolved_paths.append(str(path))
    return _dedupe_preserve_order(resolved_paths)


def _build_project_intake_scope(code_root_path: Path, coem_project_dir: str) -> dict[str, list[str]]:
    include_globs = [f"{coem_project_dir}/**"]
    for relative in ("adas", "asw"):
        if (code_root_path / relative).exists():
            include_globs.append(f"{relative}/**")
    return {
        "include_globs": include_globs,
        "exclude_globs": [
            "**/.git/**",
            "**/build/**",
            "**/__pycache__/**",
        ],
    }


def _build_project_intake_source_context(
    code_root_path: Path,
    variant_id: str,
    branch: str,
) -> dict[str, Any]:
    workspace_name = sanitize_variant_workspace_name(variant_id)
    workspace_rel = Path(".workspaces") / workspace_name
    workspace_rel_text = str(workspace_rel).replace("\\", "/")
    return {
        "source_root": str(code_root_path),
        "code_branch": branch,
        "allow_branch_mismatch": False,
        "workspace_dir": workspace_rel_text,
        "source_docs_dir": f"{workspace_rel_text}/source_docs",
        "memory_dir": f"{workspace_rel_text}/memory",
        "codegraph_db_path": f"{workspace_rel_text}/memory/codegraph/codegraph.db",
        "snapshots_dir": f"{workspace_rel_text}/memory/snapshots",
        "semantic_index_dir": f"{workspace_rel_text}/memory/semantic",
    }


def _infer_project_intake_build_entry(code_root_path: Path, coem_project_dir: str) -> str | None:
    candidates = [
        code_root_path / coem_project_dir / "buildscripts" / "build.bat",
        code_root_path / coem_project_dir / "buildscripts" / "build.sh",
        code_root_path / coem_project_dir / "tools" / "build.bat",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate.resolve().relative_to(code_root_path.resolve())).replace("\\", "/")
    return None


_EXCLUDE_DIR_NAMES = frozenset((
    "test", "tests", "Test",
    "BUILD", "build", "Build",
    "cmake", "cmake-build",
    "bin", "lib", "libs", "vendor", "external",
    "__pycache__", ".git", "buildscripts",
))


def _build_basename_index(
    root: Path,
    target_basenames: frozenset[str],
) -> Dict[str, List[Path]]:
    """Single-pass walk of *root* returning basename→[Path] for *target_basenames*."""
    index: Dict[str, List[Path]] = {bn: [] for bn in target_basenames}
    for dirpath, dirnames, filenames in os.walk(str(root)):
        # Prune excluded directories in-place so os.walk never descends into them
        dirnames[:] = [
            d for d in dirnames
            if d not in _EXCLUDE_DIR_NAMES
        ]
        for fn in filenames:
            if fn in target_basenames:
                index[fn].append(Path(dirpath) / fn)
    return index


def _pick_project_intake_source_match(
    matches: list[Path],
    code_root_path: Path,
    primary_dir: Path,
) -> Path | None:
    if not matches:
        return None

    primary_prefix = _relative_posix(primary_dir, code_root_path).lower()
    ranked: list[tuple[int, str, Path]] = []
    for path in matches:
        relative = _relative_posix(path, code_root_path).lower()
        if relative.startswith("coem/") and not relative.startswith(f"{primary_prefix}/"):
            continue
        score = 0
        if relative.startswith(primary_prefix):
            score += 10
        if "adas/symmetry" in relative:
            score += 3
        ranked.append((-score, relative, path))
    if not ranked:
        return None
    ranked.sort()
    return ranked[0][2]


def _infer_project_intake_key_sources(
    code_root_path: Path,
    primary_dir: Path,
    coem_project_dir: str,
) -> tuple[list[str], dict[str, list[str]]]:
    # Collect every basename we might need, deduplicated
    unique_basenames: frozenset[str] = frozenset(
        bn
        for _, basenames in _INTAKE_KEY_SOURCE_BASENAMES
        for bn in basenames
    )

    # Single-pass file index (no rglob per basename)
    index = _build_basename_index(code_root_path, unique_basenames)

    key_files: list[str] = []
    source_domains: dict[str, list[str]] = {"customer_project": [coem_project_dir]}
    seen: set[str] = set()

    for domain, basenames in _INTAKE_KEY_SOURCE_BASENAMES:
        domain_paths: list[str] = []
        for basename in basenames:
            matches = index.get(basename, [])
            picked = _pick_project_intake_source_match(
                matches, code_root_path, primary_dir
            )
            if picked is None:
                continue
            relative = _relative_windows(picked, code_root_path)
            if relative not in seen:
                key_files.append(relative)
                seen.add(relative)
            if relative not in domain_paths:
                domain_paths.append(relative)
        if domain_paths:
            source_domains[domain] = domain_paths

    return key_files, source_domains


def expand_project_intake(config: dict[str, Any], project_root: Path) -> dict[str, Any]:
    """Expand user-facing project_intake entries into standard internal config."""
    intake_raw = config.get("project_intake")
    if intake_raw is None:
        return config
    if not isinstance(intake_raw, dict):
        raise ValueError("project_intake must be a YAML mapping/object")

    projects_raw = intake_raw.get("projects", {})
    if not isinstance(projects_raw, dict):
        raise ValueError("project_intake.projects must be a YAML mapping/object")

    default_key_raw = intake_raw.get("default")
    default_key = str(default_key_raw).strip() if default_key_raw is not None else ""
    if default_key and default_key not in projects_raw:
        raise ValueError(
            f"project_intake.default '{default_key}' not found in project_intake.projects"
        )

    existing_codebases = config.get("codebases", {})
    if not isinstance(existing_codebases, dict):
        existing_codebases = {}
    generated_patch: dict[str, Any] = {
        "codebases": {},
        "variants": {},
        "package_profiles": {},
    }

    for project_key, entry_raw in projects_raw.items():
        if not isinstance(entry_raw, dict):
            raise ValueError(
                f"project_intake.projects.{project_key} must be a YAML mapping/object"
            )

        code_root_value = _require_project_intake_field(entry_raw, project_key, "code_root")
        coem_value = _require_project_intake_field(entry_raw, project_key, "coem")
        code_root_path = _resolve_intake_path(project_root, code_root_value)
        if not code_root_path.exists() or not code_root_path.is_dir():
            raise ValueError(
                f"project_intake.projects.{project_key}.code_root not found or not a directory: {code_root_path}"
            )

        # Allow explicit component_root override (e.g. "reco_fw" for gen5 projects)
        # When set, component_root takes precedence over coem for path resolution
        # while still using coem for variant_id generation.
        component_root_value = str(entry_raw.get("component_root", "") or "").strip()
        if component_root_value:
            coem_project_dir = _normalize_coem_project_dir(component_root_value, prepend_coem=False)
        else:
            coem_project_dir = _normalize_coem_project_dir(coem_value)
        coem_dir_path = (code_root_path / coem_project_dir).resolve()
        if not coem_dir_path.exists() or not coem_dir_path.is_dir():
            raise ValueError(
                f"project_intake.projects.{project_key}.coem not found under code_root: {coem_dir_path}"
            )

        branch_value = str(entry_raw.get("branch", "") or "").strip()
        resolved_customer, resolved_vehicle_project = _infer_customer_vehicle(
            coem_project_dir,
            customer=entry_raw.get("customer"),
            vehicle_project=entry_raw.get("vehicle_project"),
        )
        coem_leaf = coem_project_dir.split("/")[-1]
        # Detect project generation: gen5 if component_root == "reco_fw" or
        # "component_root" is explicitly set to a non-coem value
        _is_gen5 = (component_root_value != "" and component_root_value != coem_value)
        gen_prefix = "gen5" if _is_gen5 else "gen6"
        variant_id = f"{gen_prefix}/{_normalize_identity_segment(coem_leaf)}"
        codebase_id = _generate_project_intake_codebase_id(
            str(project_key),
            code_root_path,
            existing_codebases,
            generated_patch["codebases"],
        )
        package_profile_id = f"{variant_id}/default"
        key_source_files, source_domains = _infer_project_intake_key_sources(
            code_root_path,
            coem_dir_path,
            coem_project_dir,
        )

        variant_entry: dict[str, Any] = {
            "codebase_id": codebase_id,
            "display_name": coem_leaf,
            "customer": resolved_customer,
            "vehicle_project": resolved_vehicle_project,
            "coem_project_dir": coem_project_dir,
            "scope": _build_project_intake_scope(code_root_path, coem_project_dir),
            "dbc_sets": {
                "default": {
                    "files": _expand_project_intake_dbc_files(
                        project_root,
                        str(project_key),
                        entry_raw.get("dbc"),
                    ),
                }
            },
            "requirement_overlays": _expand_project_intake_requirement_paths(
                project_root,
                str(project_key),
                entry_raw.get("requirements"),
            ),
            "default_package_profile": package_profile_id,
            "key_source_files": key_source_files,
            "source_domains": source_domains,
            "source_context": _build_project_intake_source_context(
                code_root_path,
                variant_id,
                branch_value,
            ),
            "knowledge_policy": {
                "reuse_from": [],
                "invalidate_on": [
                    "code_commit_change",
                    "dbc_hash_change",
                    "requirement_hash_change",
                    "source_scope_change",
                ],
            },
            "intake_key": str(project_key),
            "project_key": str(project_key),
        }

        build_entry = _infer_project_intake_build_entry(code_root_path, coem_project_dir)
        if build_entry:
            variant_entry["build_entry"] = build_entry

        data_value = ""
        for candidate_key in ("data", "data_dir", "case_dir"):
            candidate = entry_raw.get(candidate_key)
            if isinstance(candidate, str) and candidate.strip():
                data_value = candidate.strip()
                break
        if data_value:
            resolved_data = str(_resolve_intake_path(project_root, data_value))
            variant_entry["data_dir"] = resolved_data
            variant_entry["case_dir"] = resolved_data

        generated_patch["codebases"][codebase_id] = {
            "root_path": str(code_root_path),
            "platform_id": str(entry_raw.get("platform") or "gen6_c_radar"),
            "branch": branch_value,
        }
        generated_patch["variants"][variant_id] = variant_entry
        generated_patch["package_profiles"][package_profile_id] = {
            "variant_id": variant_id,
            "build_flags": {},
        }

        if default_key and str(project_key) == default_key:
            generated_patch["default_variant"] = variant_id

    return _deep_merge_config(config, generated_patch)


def _resolve_variant_path_override(
    config: dict,
    project_root: Path,
    key: str,
    variant_id: str | None = None,
) -> Path | None:
    """Resolve a generated-asset path override from source_context."""
    settings = _resolve_source_context_settings(config, variant_id)
    return _resolve_path_setting(project_root, settings.get(key))


def load_config(config_path: str | Path | None = None) -> dict:
    """Load config.yaml plus optional config.local.yaml and resolve env vars.

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
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ValueError(f"Config at {config_path} must contain a YAML mapping/object")

    local_path = config_path.with_name("config.local.yaml")
    if local_path.exists():
        local_raw = _load_yaml_mapping(local_path, label="local config")
        raw = _deep_merge_config(raw, local_raw)

    raw = expand_project_intake(raw, config_path.parent)
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
        # Active-run variant (set by CLI --variant / case metadata) wins over
        # the static default; without this, cache dirs resolve to the wrong
        # workspace whenever the run variant differs from default_variant.
        identity = config.get("identity") if isinstance(config, dict) else None
        if isinstance(identity, dict):
            identifier = identity.get("variant_id") or ""
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
    effective_variant = None
    if variant_id or project_key:
        effective_variant = resolve_variant_id(config, variant_id or project_key)
    else:
        try:
            effective_variant = resolve_variant_id(config, None)
        except Exception:
            effective_variant = None

    if effective_variant:
        override = _resolve_variant_path_override(
            config, project_root, "codegraph_db_path", effective_variant
        )
        if override:
            return override

    # 1. Try variant system
    if effective_variant:
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
    effective_variant = None
    if variant_id or project_key:
        effective_variant = resolve_variant_id(config, variant_id or project_key)
    else:
        try:
            effective_variant = resolve_variant_id(config, None)
        except Exception:
            effective_variant = None

    if effective_variant:
        override = _resolve_variant_path_override(
            config, project_root, "source_docs_dir", effective_variant
        )
        if override:
            return override

    # 1. Try variant system
    if effective_variant:
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
    fallback = config.get("paths", {}).get("source_docs", project_root / "source_docs")
    return _resolve_path_setting(project_root, fallback) or (project_root / "source_docs")


def resolve_memory_dir(config: dict, project_root: Path, project_key: str | None = None, variant_id: str | None = None) -> Path:
    """Resolve memory directory from config.

    Supports both legacy project_key and new variant_id.
    Priority: variant_id > project_key > config["project"] > global default.
    """
    effective_variant = None
    if variant_id or project_key:
        effective_variant = resolve_variant_id(config, variant_id or project_key)
    else:
        try:
            effective_variant = resolve_variant_id(config, None)
        except Exception:
            effective_variant = None

    if effective_variant:
        override = _resolve_variant_path_override(
            config, project_root, "memory_dir", effective_variant
        )
        if override:
            return override

    # 1. Try variant system
    if effective_variant:
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
            resolved = _resolve_path_setting(project_root, path)
            if resolved:
                return resolved

    # 4. Global default
    return project_root / "memory"


def resolve_workspace_dir(
    config: dict,
    project_root: Path,
    project_key: str | None = None,
    variant_id: str | None = None,
) -> Path:
    """Resolve the variant workspace sandbox directory."""
    effective_variant = variant_id
    if not effective_variant and project_key:
        effective_variant = resolve_variant_id(config, project_key)
    if not effective_variant:
        try:
            effective_variant = resolve_variant_id(config, None)
        except Exception:
            effective_variant = None

    if effective_variant:
        override = _resolve_variant_path_override(
            config, project_root, "workspace_dir", effective_variant
        )
        if override:
            return override
        return project_root / ".workspaces" / sanitize_variant_workspace_name(effective_variant)

    return project_root / ".workspaces" / "default"


def resolve_snapshots_dir(
    config: dict,
    project_root: Path,
    project_key: str | None = None,
    variant_id: str | None = None,
) -> Path:
    """Resolve the snapshot directory, preferring variant-scoped workspace paths."""
    effective_variant = variant_id
    if not effective_variant and project_key:
        effective_variant = resolve_variant_id(config, project_key)
    if not effective_variant:
        try:
            effective_variant = resolve_variant_id(config, None)
        except Exception:
            effective_variant = None

    if effective_variant:
        override = _resolve_variant_path_override(
            config, project_root, "snapshots_dir", effective_variant
        )
        if override:
            return override

    memory_dir = resolve_memory_dir(
        config,
        project_root,
        project_key=project_key,
        variant_id=effective_variant,
    )
    if memory_dir != project_root / "memory":
        return memory_dir / "snapshots"
    return project_root / "memory" / "snapshots"


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
