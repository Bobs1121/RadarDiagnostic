# -*- coding: utf-8 -*-
"""
ProjectInitModule — minimal-input project onboarding with variant-scoped isolation.

This standalone module turns a code repo root + DBC files into a local
``config.local.yaml`` overlay plus a variant-scoped workspace sandbox under
``.workspaces/<sanitized-variant>/``. It keeps generated knowledge isolated per
variant and never mutates the target code repository.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

from config import sanitize_variant_workspace_name

from .base import BaseModule, ModuleResult

_KEY_SOURCE_BASENAMES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("algorithm", ("adasFunc.c", "adasFunc.h")),
    ("system_state", ("ASWIN_SystemState.c", "ASWIN_SystemState.h")),
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
)
_EXCLUDE_GLOBS = [
    "**/.git/**",
    "**/build/**",
    "**/dist/**",
    "**/out/**",
    "**/__pycache__/**",
]
_DEFAULT_PLATFORM = "gen6_c_radar"
_REQUIREMENT_FILE_SUFFIXES = {".yaml", ".yml", ".md", ".txt", ".pdf", ".docx", ".xlsx"}
_REQUIREMENT_HASH_LIMIT_BYTES = 5 * 1024 * 1024


def _normalize_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _normalize_identity_segment(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    slug = re.sub(r"_+", "_", slug)
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


def _relative_posix(path: Path, root: Path) -> str:
    return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")


def _relative_windows(path: Path, root: Path) -> str:
    return str(path.resolve().relative_to(root.resolve())).replace("/", "\\")


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid local config at {path}: {exc}") from exc
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(f"Local config at {path} must contain a YAML mapping/object")
    return raw


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged[key] = _deep_merge(current, value)
        else:
            merged[key] = value
    return merged


def _resolve_output_path(project_root: Path, output: str) -> Path:
    candidate = Path(output).expanduser()
    if not candidate.is_absolute():
        candidate = (project_root / candidate).resolve()
    else:
        candidate = candidate.resolve()
    return candidate


def _resolve_existing_dir(path_value: str, *, label: str) -> Path:
    path = Path(path_value).expanduser()
    if not path.is_absolute():
        path = path.resolve()
    else:
        path = path.resolve()
    if not path.exists():
        raise ValueError(f"{label} not found: {path}")
    if not path.is_dir():
        raise ValueError(f"{label} is not a directory: {path}")
    return path


def _resolve_existing_file(path_value: str, *, label: str) -> Path:
    path = Path(path_value).expanduser()
    if not path.is_absolute():
        path = path.resolve()
    else:
        path = path.resolve()
    if not path.exists():
        raise ValueError(f"{label} not found: {path}")
    if not path.is_file():
        raise ValueError(f"{label} is not a file: {path}")
    return path


def _resolve_existing_path(path_value: str, *, label: str) -> Path:
    path = Path(path_value).expanduser()
    if not path.is_absolute():
        path = path.resolve()
    else:
        path = path.resolve()
    if not path.exists():
        raise ValueError(f"{label} not found: {path}")
    return path


def _detect_git_metadata(code_root: Path) -> tuple[str | None, str | None]:
    try:
        repo_check = subprocess.run(
            ["git", "-C", str(code_root), "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            check=False,
            text=True,
        )
    except OSError:
        return None, None

    if repo_check.returncode != 0 or repo_check.stdout.strip().lower() != "true":
        return None, None

    branch = None
    commit = None
    branch_check = subprocess.run(
        ["git", "-C", str(code_root), "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True,
        check=False,
        text=True,
    )
    if branch_check.returncode == 0:
        branch_value = branch_check.stdout.strip()
        branch = branch_value if branch_value and branch_value != "HEAD" else None

    commit_check = subprocess.run(
        ["git", "-C", str(code_root), "rev-parse", "HEAD"],
        capture_output=True,
        check=False,
        text=True,
    )
    if commit_check.returncode == 0:
        commit = commit_check.stdout.strip() or None
    return branch, commit


def _list_child_dirs(root: Path) -> list[Path]:
    if not root.exists() or not root.is_dir():
        return []
    return sorted(
        [path for path in root.iterdir() if path.is_dir()],
        key=lambda item: item.name.lower(),
    )


def _candidate_list_text(candidates: list[Path]) -> str:
    return ", ".join(child.name for child in candidates)


def _match_single_candidate(
    children: list[Path],
    *,
    customer: str,
    vehicle_project: str,
    project_name: str,
) -> Path | None:
    child_tokens = {child: _normalize_token(child.name) for child in children}

    exact_aliases: set[str] = set()
    if customer and vehicle_project:
        exact_aliases.add(_normalize_token(f"{customer}_{vehicle_project}"))
        exact_aliases.add(_normalize_token(f"{customer}{vehicle_project}"))
    if project_name:
        exact_aliases.add(_normalize_token(project_name))

    exact_matches = [
        child
        for child, token in child_tokens.items()
        if token and token in exact_aliases
    ]
    if len(exact_matches) == 1:
        return exact_matches[0]
    if len(exact_matches) > 1:
        return None

    token_groups: list[list[str]] = []
    if customer and vehicle_project:
        token_groups.append(
            [
                _normalize_token(customer),
                _normalize_token(vehicle_project),
            ]
        )
    if project_name:
        parts = [
            _normalize_token(part)
            for part in re.split(r"[^A-Za-z0-9]+", project_name)
            if _normalize_token(part)
        ]
        if len(parts) >= 2:
            token_groups.append(parts)

    inferred: list[Path] = []
    for tokens in token_groups:
        matches = [
            child
            for child, token in child_tokens.items()
            if token and all(part in token for part in tokens)
        ]
        for match in matches:
            if match not in inferred:
                inferred.append(match)
    if len(inferred) == 1:
        return inferred[0]
    return None


def _resolve_coem_project_dir(
    code_root: Path,
    *,
    coem_project: str | None,
    customer: str,
    vehicle_project: str,
    project_name: str,
) -> Path:
    coem_root = code_root / "coem"
    if not coem_root.exists() or not coem_root.is_dir():
        raise ValueError(f"COEM root not found under code root: {coem_root}")

    candidates = _list_child_dirs(coem_root)
    if not candidates:
        raise ValueError(f"No COEM project directories found under {coem_root}")

    if coem_project:
        raw = str(coem_project).strip().replace("\\", "/").strip("/")
        if not raw:
            raise ValueError("--coem-project cannot be empty")
        if raw.startswith("coem/"):
            raw = raw[5:]
        resolved = (coem_root / raw).resolve()
        try:
            resolved.relative_to(coem_root.resolve())
        except ValueError as exc:
            raise ValueError(
                f"--coem-project must point under {coem_root}. Got: {coem_project}"
            ) from exc
        if not resolved.exists() or not resolved.is_dir():
            raise ValueError(
                f"COEM project not found: {resolved}. Candidates: {_candidate_list_text(candidates)}"
            )
        return resolved

    if len(candidates) == 1:
        return candidates[0]

    matched = _match_single_candidate(
        candidates,
        customer=customer,
        vehicle_project=vehicle_project,
        project_name=project_name,
    )
    if matched is not None:
        return matched

    raise ValueError(
        f"Unable to resolve COEM project under {coem_root}. "
        f"Candidates: {_candidate_list_text(candidates)}. "
        "Pass --coem-project explicitly."
    )


def _derive_customer_vehicle(
    coem_dir: Path,
    *,
    customer: str | None,
    vehicle_project: str | None,
) -> tuple[str, str]:
    explicit_customer = str(customer or "").strip()
    explicit_vehicle = str(vehicle_project or "").strip()

    parts = [part for part in re.split(r"[^A-Za-z0-9]+", coem_dir.name) if part]
    parsed_customer = parts[0] if parts else coem_dir.name
    parsed_vehicle = "_".join(parts[1:]) if len(parts) > 1 else ""

    resolved_customer = explicit_customer or parsed_customer
    resolved_vehicle = explicit_vehicle or parsed_vehicle
    return resolved_customer, resolved_vehicle


def _build_variant_id(
    explicit_variant: str | None,
    *,
    customer: str,
    vehicle_project: str,
    coem_dir: Path,
) -> str:
    if explicit_variant and str(explicit_variant).strip():
        variant_id = str(explicit_variant).strip()
        if variant_id:
            return variant_id

    if customer and vehicle_project:
        segment = f"{_normalize_identity_segment(customer)}_{_normalize_identity_segment(vehicle_project)}"
    else:
        segment = _normalize_identity_segment(coem_dir.name)
    return f"gen6/{segment}"


def _infer_scope(code_root: Path, coem_project_dir: str) -> dict[str, list[str]]:
    include_globs = [f"{coem_project_dir}/**"]
    for relative in ("common", "shared", "adas/symmetry"):
        if (code_root / relative).exists():
            include_globs.append(f"{relative}/**")
    return {
        "include_globs": _dedupe_preserve_order(include_globs),
        "exclude_globs": list(_EXCLUDE_GLOBS),
    }


def _infer_build_entry(code_root: Path, primary_dir: Path | None) -> str | None:
    candidates: list[Path] = []
    if primary_dir is not None:
        rel_primary = primary_dir.resolve().relative_to(code_root.resolve())
        candidates.extend(
            [
                code_root / rel_primary / "buildscripts" / "build.bat",
                code_root / rel_primary / "buildscripts" / "build.sh",
                code_root / rel_primary / "tools" / "build.bat",
            ]
        )
    candidates.extend(
        [
            code_root / "buildscripts" / "build.bat",
            code_root / "buildscripts" / "build.sh",
            code_root / "build.bat",
            code_root / "scons_gen.bat",
            code_root / "cmake_gen.bat",
        ]
    )

    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if resolved.exists():
            return _relative_posix(resolved, code_root)

    for pattern in (
        "buildscripts/build.bat",
        "buildscripts/build.sh",
        "build.bat",
        "scons_gen.bat",
        "cmake_gen.bat",
    ):
        matches = sorted(code_root.rglob(pattern.split("/")[-1]))
        for match in matches:
            relative = _relative_posix(match, code_root)
            if relative.endswith(pattern) or relative == pattern:
                return relative
    return None


def _preferred_match(paths: list[Path], code_root: Path, primary_dir: Path | None) -> Path | None:
    if not paths:
        return None
    if primary_dir is None:
        return sorted(
            paths,
            key=lambda item: (_relative_posix(item, code_root).lower(), len(str(item))),
        )[0]

    primary_prefix = _relative_posix(primary_dir, code_root).lower()
    ranked: list[tuple[int, str, Path]] = []
    for path in paths:
        relative = _relative_posix(path, code_root).lower()
        score = 0
        if relative.startswith(primary_prefix):
            score += 10
        if "adas/symmetry" in relative:
            score += 3
        ranked.append((-score, relative, path))
    ranked.sort()
    return ranked[0][2]


def _infer_key_source_files(code_root: Path, primary_dir: Path | None) -> tuple[list[str], dict[str, list[str]]]:
    key_files: list[str] = []
    source_domains: dict[str, list[str]] = {}
    seen: set[str] = set()

    for domain, basenames in _KEY_SOURCE_BASENAMES:
        domain_paths: list[str] = []
        for basename in basenames:
            matches = [path for path in code_root.rglob(basename) if path.is_file()]
            picked = _preferred_match(matches, code_root, primary_dir)
            if picked is None:
                continue
            relative = _relative_windows(picked, code_root)
            if relative not in seen:
                key_files.append(relative)
                seen.add(relative)
            if relative not in domain_paths:
                domain_paths.append(relative)
        if domain_paths:
            source_domains[domain] = domain_paths

    return key_files, source_domains


def _package_profile_key(variant_id: str) -> str:
    return f"{variant_id}/default"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _file_stat_manifest(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "name": path.name,
        "source_path": str(path),
        "size_bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def _build_dbc_manifest(dbc_paths: list[Path]) -> dict[str, Any]:
    return {
        "dbc_sources": [
            {
                **_file_stat_manifest(path),
                "sha256": _sha256_file(path),
            }
            for path in dbc_paths
        ]
    }


def _iter_requirement_dir_files(root: Path) -> list[Path]:
    matches = [
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in _REQUIREMENT_FILE_SUFFIXES
    ]
    return sorted(matches, key=lambda item: _relative_posix(item, root).lower())


def _build_requirement_manifest(requirement_paths: list[Path]) -> dict[str, Any]:
    sources: list[dict[str, Any]] = []
    for path in requirement_paths:
        if path.is_file():
            sources.append(
                {
                    "type": "file",
                    **_file_stat_manifest(path),
                    "sha256": _sha256_file(path),
                }
            )
            continue

        directory_files = _iter_requirement_dir_files(path)
        file_entries: list[dict[str, Any]] = []
        for child in directory_files:
            entry = {
                "relative_path": _relative_posix(child, path),
                **_file_stat_manifest(child),
            }
            if child.stat().st_size <= _REQUIREMENT_HASH_LIMIT_BYTES:
                entry["sha256"] = _sha256_file(child)
            else:
                entry["sha256_skipped"] = "size_exceeds_limit"
            file_entries.append(entry)

        sources.append(
            {
                "type": "directory",
                "source_path": str(path),
                "file_count": len(file_entries),
                "files": file_entries,
            }
        )

    return {
        "requirement_sources": sources,
        "validated_paths": [str(path) for path in requirement_paths],
    }


class ProjectInitModule(BaseModule):
    """Generate a local onboarding config and isolated workspace sandbox."""

    name = "project-init"
    description = "Bootstrap config.local.yaml and a variant-scoped workspace sandbox"
    # This module writes config/workspace files.  It remains discoverable by
    # Pi, but the module bridge requires an explicit supervisor approval before
    # it can be invoked as a tool.
    requires_approval = True
    approval_mode = "always"

    def __init__(self, *, project_root: Path | str | None = None) -> None:
        self.project_root = Path(project_root) if project_root else Path(__file__).resolve().parents[2]

    def run(
        self,
        *,
        name: str,
        code_root: str,
        dbcs: list[str] | tuple[str, ...] | None = None,
        customer: str | None = None,
        vehicle_project: str | None = None,
        coem_project: str | None = None,
        requirements: list[str] | tuple[str, ...] | None = None,
        expected_branch: str = "master",
        case_dir: str | None = None,
        platform: str = _DEFAULT_PLATFORM,
        variant: str | None = None,
        output: str = "config.local.yaml",
        dry_run: bool = False,
        no_set_default: bool = False,
        branch: str | None = None,
        **_: Any,
    ) -> ModuleResult:
        project_name = str(name or "").strip()
        if not project_name:
            raise ValueError("--name is required")

        dbc_inputs = [str(item) for item in (dbcs or []) if str(item).strip()]
        if not dbc_inputs:
            raise ValueError("At least one --dbc path is required")

        expected_branch_value = str(expected_branch or "").strip() or "master"
        legacy_branch = str(branch or "").strip()
        if legacy_branch and expected_branch_value == "master":
            expected_branch_value = legacy_branch

        code_root_path = _resolve_existing_dir(code_root, label="Code root")
        dbc_paths = [
            _resolve_existing_file(dbc_path, label=f"DBC file #{index + 1}")
            for index, dbc_path in enumerate(dbc_inputs)
        ]
        requirement_paths = _dedupe_preserve_order(
            [
                str(_resolve_existing_path(requirement_path, label=f"Requirement path #{index + 1}"))
                for index, requirement_path in enumerate(requirements or [])
                if str(requirement_path).strip()
            ]
        )
        requirement_path_objs = [Path(path) for path in requirement_paths]
        case_dir_path = (
            _resolve_existing_dir(case_dir, label="Case directory") if case_dir else None
        )

        current_branch, current_commit = _detect_git_metadata(code_root_path)
        coem_dir = _resolve_coem_project_dir(
            code_root_path,
            coem_project=coem_project,
            customer=str(customer or "").strip(),
            vehicle_project=str(vehicle_project or "").strip(),
            project_name=project_name,
        )
        coem_project_dir = _relative_posix(coem_dir, code_root_path)
        resolved_customer, resolved_vehicle_project = _derive_customer_vehicle(
            coem_dir,
            customer=customer,
            vehicle_project=vehicle_project,
        )

        variant_id = _build_variant_id(
            variant,
            customer=resolved_customer,
            vehicle_project=resolved_vehicle_project,
            coem_dir=coem_dir,
        )
        if not variant_id:
            raise ValueError("Variant id cannot be empty")

        codebase_id = _normalize_identity_segment(code_root_path.name)
        workspace_name = sanitize_variant_workspace_name(variant_id)
        workspace_dir = (self.project_root / ".workspaces" / workspace_name).resolve()

        scope = _infer_scope(code_root_path, coem_project_dir)
        build_entry = _infer_build_entry(code_root_path, coem_dir)
        key_source_files, inferred_domains = _infer_key_source_files(code_root_path, coem_dir)
        source_domains: dict[str, list[str]] = {"customer_project": [coem_project_dir]}
        source_domains.update(inferred_domains)

        package_profile_id = _package_profile_key(variant_id)
        workspace_rel = Path(".workspaces") / workspace_name
        variant_source_context = {
            "source_root": str(code_root_path),
            "code_branch": expected_branch_value,
            "allow_branch_mismatch": False,
            "workspace_dir": str(workspace_rel),
            "source_docs_dir": str(workspace_rel / "source_docs"),
            "memory_dir": str(workspace_rel / "memory"),
            "codegraph_db_path": str(workspace_rel / "memory" / "codegraph" / "codegraph.db"),
            "snapshots_dir": str(workspace_rel / "memory" / "snapshots"),
            "semantic_index_dir": str(workspace_rel / "memory" / "semantic"),
            "dbc_workspace_dir": str(workspace_rel / "dbc"),
        }

        patch_set = None
        if build_entry:
            build_path = Path(build_entry)
            patch_dir = build_path.parent / "patch"
            if (code_root_path / patch_dir).exists():
                patch_set = {"source_dir": str(patch_dir).replace("\\", "/")}

        package_profile: dict[str, Any] = {
            "variant_id": variant_id,
            "build_flags": {},
        }
        if coem_dir.name:
            package_profile["build_flags"] = {"vehicle_type": coem_dir.name}
        if patch_set:
            package_profile["patch_set"] = patch_set

        knowledge_policy = {
            "reuse_from": [],
            "invalidate_on": [
                "code_commit_change",
                "dbc_hash_change",
                "requirement_hash_change",
                "source_scope_change",
            ],
        }
        local_patch: dict[str, Any] = {
            "codebases": {
                codebase_id: {
                    "root_path": str(code_root_path),
                    "platform_id": platform or _DEFAULT_PLATFORM,
                    "branch": expected_branch_value,
                    "expected_branch": expected_branch_value,
                    "current_branch": current_branch,
                    "current_commit": current_commit,
                    "commit": current_commit,
                }
            },
            "variants": {
                variant_id: {
                    "codebase_id": codebase_id,
                    "display_name": project_name,
                    "customer": resolved_customer,
                    "vehicle_project": resolved_vehicle_project,
                    "coem_project_dir": coem_project_dir,
                    "requirement_overlays": [str(path) for path in requirement_path_objs],
                    "knowledge_policy": knowledge_policy,
                    "scope": scope,
                    "dbc_sets": {
                        "default": {
                            "files": [str(path) for path in dbc_paths],
                        }
                    },
                    "key_source_files": key_source_files,
                    "source_domains": source_domains,
                    "default_package_profile": package_profile_id,
                    "source_context": variant_source_context,
                }
            },
            "package_profiles": {
                package_profile_id: package_profile,
            },
        }
        if build_entry:
            local_patch["variants"][variant_id]["build_entry"] = build_entry
        if not no_set_default:
            local_patch["default_variant"] = variant_id

        dbc_manifest = {
            "variant_id": variant_id,
            "codebase_id": codebase_id,
            **_build_dbc_manifest(dbc_paths),
        }
        requirement_manifest = {
            "variant_id": variant_id,
            "codebase_id": codebase_id,
            **_build_requirement_manifest(requirement_path_objs),
        }
        workspace_manifest = {
            "workspace_id": workspace_name,
            "variant_id": variant_id,
            "codebase_id": codebase_id,
            "customer": resolved_customer,
            "vehicle_project": resolved_vehicle_project,
            "coem_project_dir": coem_project_dir,
            "source_root": str(code_root_path),
            "expected_branch": expected_branch_value,
            "current_branch": current_branch,
            "current_commit": current_commit,
            "dbc_manifest": dbc_manifest,
            "requirement_manifest": requirement_manifest,
            "knowledge_dirs": {
                "workspace_dir": str(workspace_rel),
                "source_docs_dir": str(workspace_rel / "source_docs"),
                "memory_dir": str(workspace_rel / "memory"),
                "codegraph_db_path": str(workspace_rel / "memory" / "codegraph" / "codegraph.db"),
                "snapshots_dir": str(workspace_rel / "memory" / "snapshots"),
                "semantic_index_dir": str(workspace_rel / "memory" / "semantic"),
                "dbc_workspace_dir": str(workspace_rel / "dbc"),
                "requirements_workspace_dir": str(workspace_rel / "requirements"),
            },
        }
        if case_dir_path is not None:
            workspace_manifest["case_dir"] = str(case_dir_path)

        output_path = _resolve_output_path(self.project_root, output)
        existing_local = _load_yaml_mapping(output_path) if output_path.exists() else {}
        merged_local = _deep_merge(existing_local, local_patch)

        workspace_config_path = workspace_dir / "config.yaml"
        workspace_manifest_path = workspace_dir / "manifest.yaml"
        workspace_dbc_sources_path = workspace_dir / "dbc" / "sources.yaml"
        workspace_requirement_sources_path = workspace_dir / "requirements" / "sources.yaml"
        workspace_assets = [
            workspace_dir,
            workspace_dir / "source_docs",
            workspace_dir / "memory",
            workspace_dir / "memory" / "codegraph",
            workspace_dir / "memory" / "snapshots",
            workspace_dir / "memory" / "semantic",
            workspace_dir / "dbc",
            workspace_dir / "requirements",
        ]
        generated_files = [
            str(output_path),
            str(workspace_config_path),
            str(workspace_manifest_path),
            str(workspace_dbc_sources_path),
            str(workspace_requirement_sources_path),
        ]

        if not dry_run:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                yaml.safe_dump(merged_local, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )

            for asset_dir in workspace_assets:
                asset_dir.mkdir(parents=True, exist_ok=True)

            workspace_config = {
                "workspace_id": workspace_name,
                "variant_id": variant_id,
                "codebase_id": codebase_id,
                "display_name": project_name,
                "resources": {
                    "source_root": str(code_root_path),
                    "dbc_manifest": "dbc/sources.yaml",
                    "requirement_manifest": "requirements/sources.yaml",
                    "workspace_manifest": "manifest.yaml",
                },
            }
            if case_dir_path is not None:
                workspace_config["resources"]["case_dir"] = str(case_dir_path)
            workspace_config_path.write_text(
                yaml.safe_dump(workspace_config, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            workspace_manifest_path.write_text(
                yaml.safe_dump(workspace_manifest, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            workspace_dbc_sources_path.write_text(
                yaml.safe_dump(dbc_manifest, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            workspace_requirement_sources_path.write_text(
                yaml.safe_dump(requirement_manifest, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )

        run_case = str(case_dir_path) if case_dir_path is not None else "<case_dir>"
        run_command = (
            f'python cli.py "{run_case}" -p "<problem>" -e "<expected>" --variant "{variant_id}"'
        )
        hit_resolution = {
            "priority": [
                "explicit --variant",
                "case metadata",
                "config.local default_variant",
            ],
            "resolved": {
                "variant_id": variant_id,
                "codebase_id": codebase_id,
                "customer": resolved_customer,
                "vehicle_project": resolved_vehicle_project,
                "coem_project_dir": coem_project_dir,
                "expected_branch": expected_branch_value,
                "current_branch": current_branch,
                "current_commit": current_commit,
                "dbc": [str(path) for path in dbc_paths],
                "requirements": [str(path) for path in requirement_path_objs],
            },
        }

        return ModuleResult.success(
            message="project-init:ready" if dry_run else "project-init:written",
            module=self.name,
            variant_id=variant_id,
            codebase_id=codebase_id,
            customer=resolved_customer,
            vehicle_project=resolved_vehicle_project,
            coem_project_dir=coem_project_dir,
            expected_branch=expected_branch_value,
            current_branch=current_branch,
            current_commit=current_commit,
            workspace_dir=str(workspace_dir),
            config_path=str(output_path),
            generated_files=generated_files,
            workspace_assets=[str(path) for path in workspace_assets],
            run_command=run_command,
            dry_run=bool(dry_run),
            local_config=merged_local,
            dbc_manifest=dbc_manifest,
            requirement_manifest=requirement_manifest,
            workspace_manifest=workspace_manifest,
            hit_resolution=hit_resolution,
        )

    @classmethod
    def register_cli(cls, subparsers: Any) -> Any:
        parser = super().register_cli(subparsers)
        parser.add_argument("--name", required=True, help="Display name for the onboarded radar project.")
        parser.add_argument("--code-root", required=True, help="Absolute or relative path to the source repo root.")
        parser.add_argument(
            "--dbc",
            dest="dbcs",
            action="append",
            default=[],
            metavar="PATH",
            help="DBC file path. Repeat for multiple files.",
        )
        parser.add_argument("--customer", default=None, help="Optional customer name used for variant identity and COEM matching.")
        parser.add_argument("--vehicle-project", default=None, help="Optional vehicle project name used for variant identity and COEM matching.")
        parser.add_argument(
            "--coem-project",
            default=None,
            help="COEM directory name or relative path under coem/, for example BYD_SC6H or coem/BYD_SC6H.",
        )
        parser.add_argument(
            "--requirements",
            action="append",
            default=[],
            metavar="PATH",
            help="Requirement material root. Repeat for files or directories.",
        )
        parser.add_argument(
            "--expected-branch",
            default="master",
            help="Expected source git branch for validation metadata only. Defaults to master.",
        )
        parser.add_argument("--branch", dest="branch", default=None, help=argparse.SUPPRESS)
        parser.add_argument("--case-dir", default=None, help="Optional default case directory for command previews.")
        parser.add_argument("--platform", default=_DEFAULT_PLATFORM, help="Platform family id. Defaults to gen6_c_radar.")
        parser.add_argument("--variant", default=None, help="Canonical variant id. Defaults to gen6/<customer>_<vehicle> or coem project.")
        parser.add_argument("--output", default="config.local.yaml", help="Output local config path. Defaults to config.local.yaml.")
        parser.add_argument("--dry-run", action="store_true", help="Preview the generated config without writing files.")
        parser.add_argument("--no-set-default", action="store_true", help="Do not update default_variant in the local overlay.")
        return parser

    @classmethod
    def from_cli_args(cls, args: Any) -> "ProjectInitModule":
        return cls()


__all__ = ["ProjectInitModule"]


def _sync_parent_registry() -> None:
    """Keep ai.modules.MODULE_REGISTRY coherent on direct submodule imports."""
    parent = sys.modules.get("ai.modules")
    if parent is None:
        return

    registry = getattr(parent, "MODULE_REGISTRY", None)
    if isinstance(registry, dict):
        registry.setdefault(ProjectInitModule.name, ProjectInitModule)

    exported = getattr(parent, "__all__", None)
    if isinstance(exported, list) and "ProjectInitModule" not in exported:
        exported.append("ProjectInitModule")


_sync_parent_registry()
