from __future__ import annotations

import datetime as _dt
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from config import get_variant, resolve_variant_id

FRESHNESS_STATE_FILE = "freshness_state.json"
_SOURCE_FILE_SUFFIXES = {".c", ".h", ".cpp", ".hpp"}
_REQUIREMENT_FILE_SUFFIXES = {".yaml", ".yml", ".md", ".txt", ".pdf", ".docx", ".xlsx"}
_CONSTANT_SOURCE_BASENAMES = {
    "adasfunc.c",
    "adasfunc.h",
    "dotcalibdefine.h",
    "globalvardefine.h",
    "paradefine.h",
    "perception_public_def.h",
    "structdefine.h",
}
_MAX_SCOPE_FILES = 2000
_MAX_REQUIREMENT_HASH_BYTES = 5 * 1024 * 1024
_SCHEMA_VERSION = 1


def compute_variant_fingerprint(config: dict, project_root: str | Path) -> dict[str, Any]:
    """Compute a deterministic fingerprint for the active variant inputs."""
    project_root = Path(project_root).resolve()
    variant_id = (
        config.get("identity", {}).get("variant_id")
        or resolve_variant_id(config, None)
    )
    variant, codebase, _ = get_variant(config, variant_id)
    variant_cfg = config.get("variants", {}).get(variant_id, {})

    source_root = _resolve_source_root(config, project_root, codebase.root_path)
    current_branch, current_commit = _detect_git_state(source_root)

    key_source_files = _hash_declared_files(
        declared_paths=variant.key_source_files or [],
        source_root=source_root,
        project_root=project_root,
    )
    scope_files = _hash_scoped_source_files(
        source_root=source_root,
        include_globs=list(variant.scope.include_globs or []),
        exclude_globs=list(variant.scope.exclude_globs or []),
    )
    constants_files = _select_constant_files(key_source_files["files"], scope_files["files"])
    dbc_files = _hash_dbc_files(
        dbc_sets=list(variant.dbc_sets or []),
        source_root=source_root,
        project_root=project_root,
    )
    requirements = _hash_requirement_overlays(
        overlays=list(variant.requirement_overlays or []),
        source_root=source_root,
        project_root=project_root,
    )

    config_identity = {
        "variant_id": variant_id,
        "source_root": str(source_root) if source_root else None,
        "customer": variant_cfg.get("customer"),
        "vehicle_project": variant_cfg.get("vehicle_project"),
        "coem_project_dir": variant_cfg.get("coem_project_dir"),
        "scope_include_globs": list(variant.scope.include_globs or []),
        "scope_exclude_globs": list(variant.scope.exclude_globs or []),
        "dbc_paths": [entry["configured_path"] for entry in dbc_files["files"]],
        "requirement_paths": [entry["configured_path"] for entry in requirements["sources"]],
    }

    return {
        "schema_version": _SCHEMA_VERSION,
        "variant_id": variant_id,
        "source_root": str(source_root) if source_root else None,
        "current_branch": current_branch,
        "current_commit": current_commit,
        "key_source_files": key_source_files["files"],
        "key_source_files_hash": key_source_files["aggregate_hash"],
        "source_scope": {
            "include_globs": list(variant.scope.include_globs or []),
            "exclude_globs": list(variant.scope.exclude_globs or []),
            "file_count": scope_files["file_count"],
            "truncated": scope_files["truncated"],
            "max_files": _MAX_SCOPE_FILES,
        },
        "source_scope_hash": scope_files["aggregate_hash"],
        "constants_files": constants_files["files"],
        "constants_source_hash": constants_files["aggregate_hash"],
        "dbc_files": dbc_files["files"],
        "dbc_hash": dbc_files["aggregate_hash"],
        "requirements_sources": requirements["sources"],
        "requirements_files": requirements["files"],
        "requirements_hash": requirements["aggregate_hash"],
        "config_identity": config_identity,
        "config_identity_hash": _stable_hash(config_identity),
    }


def load_freshness_state(memory_dir_or_workspace_dir: str | Path) -> dict[str, Any] | None:
    """Load freshness_state.json from a memory or workspace directory."""
    path = _resolve_state_path(memory_dir_or_workspace_dir)
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def write_freshness_state(
    memory_dir_or_workspace_dir: str | Path,
    fingerprint: dict[str, Any],
) -> dict[str, Any]:
    """Persist freshness_state.json next to variant memory."""
    path = _resolve_state_path(memory_dir_or_workspace_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    state = {
        "schema_version": _SCHEMA_VERSION,
        "updated_at": _dt.datetime.now().isoformat(),
        "fingerprint": fingerprint,
    }
    path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return state


def compare_freshness(
    previous: dict[str, Any] | None,
    current: dict[str, Any],
) -> dict[str, Any]:
    """Compare two freshness fingerprints and classify what changed."""
    previous_fp = _unwrap_fingerprint(previous)
    changed_keys: list[str] = []

    def _changed(key: str) -> bool:
        if previous_fp is None:
            changed_keys.append(key)
            return True
        if previous_fp.get(key) != current.get(key):
            changed_keys.append(key)
            return True
        return False

    code_changed = any(
        _changed(key)
        for key in (
            "source_root",
            "current_branch",
            "current_commit",
            "key_source_files_hash",
            "source_scope_hash",
        )
    )
    constants_changed = _changed("constants_source_hash")
    dbc_changed = _changed("dbc_hash")
    requirements_changed = _changed("requirements_hash")
    identity_changed = any(
        _changed(key)
        for key in (
            "variant_id",
            "config_identity_hash",
        )
    )

    if previous_fp is None:
        changed_keys.insert(0, "freshness_state_missing")

    return {
        "code_changed": code_changed,
        "constants_changed": constants_changed,
        "dbc_changed": dbc_changed,
        "requirements_changed": requirements_changed,
        "identity_changed": identity_changed,
        "any_changed": any(
            (
                code_changed,
                constants_changed,
                dbc_changed,
                requirements_changed,
                identity_changed,
            )
        ),
        "changed_keys": changed_keys,
        "previous_state_available": previous_fp is not None,
    }


def _resolve_state_path(memory_dir_or_workspace_dir: str | Path) -> Path:
    base = Path(memory_dir_or_workspace_dir)
    if base.suffix.lower() == ".json":
        return base
    if base.name.lower() == "memory":
        return base / FRESHNESS_STATE_FILE
    if (base / "memory").exists() or base.name.startswith(".workspaces"):
        return base / "memory" / FRESHNESS_STATE_FILE
    return base / FRESHNESS_STATE_FILE


def _unwrap_fingerprint(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    fingerprint = value.get("fingerprint")
    if isinstance(fingerprint, dict):
        return fingerprint
    return value


def _resolve_source_root(
    config: dict,
    project_root: Path,
    codebase_root: str | None,
) -> Path | None:
    source_root = (
        config.get("identity", {}).get("source_root")
        or config.get("paths", {}).get("source_code")
        or config.get("project", {}).get("source_code")
        or codebase_root
    )
    if not source_root:
        return None
    path = Path(str(source_root)).expanduser()
    if not path.is_absolute():
        path = (project_root / path).resolve()
    else:
        path = path.resolve()
    return path


def _detect_git_state(source_root: Path | None) -> tuple[str | None, str | None]:
    if source_root is None or not source_root.exists() or not source_root.is_dir():
        return None, None
    try:
        repo_check = subprocess.run(
            ["git", "-C", str(source_root), "rev-parse", "--is-inside-work-tree"],
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
    branch_result = subprocess.run(
        ["git", "-C", str(source_root), "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True,
        check=False,
        text=True,
    )
    if branch_result.returncode == 0:
        branch_value = branch_result.stdout.strip()
        branch = branch_value if branch_value and branch_value != "HEAD" else None

    commit_result = subprocess.run(
        ["git", "-C", str(source_root), "rev-parse", "HEAD"],
        capture_output=True,
        check=False,
        text=True,
    )
    if commit_result.returncode == 0:
        commit = commit_result.stdout.strip() or None
    return branch, commit


def _hash_declared_files(
    *,
    declared_paths: list[str],
    source_root: Path | None,
    project_root: Path,
) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    for raw_path in declared_paths:
        resolved = _resolve_candidate_path(raw_path, source_root, project_root)
        entry = {
            "configured_path": raw_path,
            "resolved_path": str(resolved) if resolved else None,
            "exists": bool(resolved and resolved.exists() and resolved.is_file()),
            "sha256": None,
        }
        if resolved and resolved.exists() and resolved.is_file():
            entry["sha256"] = _hash_file(resolved)
            entry["relative_path"] = _relative_to_source_root(resolved, source_root)
        files.append(entry)
    files.sort(key=lambda item: item["configured_path"])
    return {
        "files": files,
        "aggregate_hash": _stable_hash(files),
    }


def _hash_scoped_source_files(
    *,
    source_root: Path | None,
    include_globs: list[str],
    exclude_globs: list[str],
) -> dict[str, Any]:
    if source_root is None or not source_root.exists() or not source_root.is_dir():
        return {
            "files": [],
            "aggregate_hash": _stable_hash([]),
            "file_count": 0,
            "truncated": False,
        }

    candidates: dict[str, Path] = {}
    for pattern in include_globs:
        for matched in source_root.glob(pattern):
            if not matched.is_file():
                continue
            if matched.suffix.lower() not in _SOURCE_FILE_SUFFIXES:
                continue
            rel = _relative_to_source_root(matched, source_root)
            if _matches_any_glob(rel, exclude_globs):
                continue
            candidates[rel] = matched

    ordered = sorted(candidates.items(), key=lambda item: item[0].lower())
    truncated = len(ordered) > _MAX_SCOPE_FILES
    files: list[dict[str, Any]] = []
    for rel, full_path in ordered[:_MAX_SCOPE_FILES]:
        files.append(
            {
                "relative_path": rel,
                "sha256": _hash_file(full_path),
            }
        )
    if truncated:
        files.append({"relative_path": "__TRUNCATED__", "sha256": f"remaining:{len(ordered) - _MAX_SCOPE_FILES}"})

    return {
        "files": files,
        "aggregate_hash": _stable_hash(files),
        "file_count": len(ordered),
        "truncated": truncated,
    }


def _select_constant_files(
    key_source_files: list[dict[str, Any]],
    scoped_files: list[dict[str, Any]],
) -> dict[str, Any]:
    deduped: dict[str, dict[str, Any]] = {}
    for entry in list(key_source_files) + list(scoped_files):
        rel = str(entry.get("relative_path") or entry.get("configured_path") or "")
        if not rel:
            continue
        name = Path(rel).name.lower()
        if name not in _CONSTANT_SOURCE_BASENAMES:
            continue
        deduped[rel] = {
            "relative_path": rel,
            "sha256": entry.get("sha256"),
        }
    files = [deduped[key] for key in sorted(deduped)]
    return {
        "files": files,
        "aggregate_hash": _stable_hash(files),
    }


def _hash_dbc_files(
    *,
    dbc_sets: list[Any],
    source_root: Path | None,
    project_root: Path,
) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    for dbc_set in dbc_sets:
        set_name = getattr(dbc_set, "name", "default")
        for raw_path in list(getattr(dbc_set, "files", []) or []):
            resolved = _resolve_candidate_path(raw_path, source_root, project_root)
            entry = {
                "set": set_name,
                "configured_path": raw_path,
                "resolved_path": str(resolved) if resolved else None,
                "exists": bool(resolved and resolved.exists() and resolved.is_file()),
                "sha256": None,
            }
            if resolved and resolved.exists() and resolved.is_file():
                entry["sha256"] = _hash_file(resolved)
            files.append(entry)
    files.sort(key=lambda item: (item["set"], item["configured_path"]))
    return {
        "files": files,
        "aggregate_hash": _stable_hash(files),
    }


def _hash_requirement_overlays(
    *,
    overlays: list[str],
    source_root: Path | None,
    project_root: Path,
) -> dict[str, Any]:
    sources: list[dict[str, Any]] = []
    files: list[dict[str, Any]] = []
    for raw_path in overlays:
        resolved = _resolve_candidate_path(raw_path, source_root, project_root)
        source_entry = {
            "configured_path": raw_path,
            "resolved_path": str(resolved) if resolved else None,
            "exists": bool(resolved and resolved.exists()),
            "type": None,
        }
        if resolved and resolved.exists() and resolved.is_file():
            source_entry["type"] = "file"
            hashed = _hash_requirement_file(resolved)
            hashed["configured_path"] = raw_path
            files.append(hashed)
        elif resolved and resolved.exists() and resolved.is_dir():
            source_entry["type"] = "directory"
            for path in sorted(resolved.rglob("*"), key=lambda item: str(item).lower()):
                if not path.is_file():
                    continue
                if path.suffix.lower() not in _REQUIREMENT_FILE_SUFFIXES:
                    continue
                hashed = _hash_requirement_file(path, root=resolved)
                hashed["configured_path"] = raw_path
                files.append(hashed)
        sources.append(source_entry)
    sources.sort(key=lambda item: item["configured_path"])
    files.sort(key=lambda item: (item["configured_path"], item["relative_path"]))
    return {
        "sources": sources,
        "files": files,
        "aggregate_hash": _stable_hash(files),
    }


def _hash_requirement_file(path: Path, root: Path | None = None) -> dict[str, Any]:
    size = path.stat().st_size
    content_hash = _hash_file(path, max_bytes=_MAX_REQUIREMENT_HASH_BYTES)
    return {
        "relative_path": _relative_path(path, root),
        "sha256": content_hash,
        "size": size,
        "truncated": size > _MAX_REQUIREMENT_HASH_BYTES,
    }


def _resolve_candidate_path(
    raw_path: str,
    source_root: Path | None,
    project_root: Path,
) -> Path | None:
    if not raw_path:
        return None
    candidate = Path(raw_path).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()

    search_roots: list[Path] = []
    if source_root is not None:
        search_roots.append(source_root)
    search_roots.append(project_root)
    for base in search_roots:
        resolved = (base / candidate).resolve()
        if resolved.exists():
            return resolved
    return (search_roots[0] / candidate).resolve() if search_roots else candidate.resolve()


def _hash_file(path: Path, max_bytes: int | None = None) -> str:
    hasher = hashlib.sha256()
    remaining = max_bytes
    with path.open("rb") as handle:
        while True:
            chunk_size = 1024 * 1024
            if remaining is not None:
                if remaining <= 0:
                    break
                chunk_size = min(chunk_size, remaining)
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            hasher.update(chunk)
            if remaining is not None:
                remaining -= len(chunk)
    return hasher.hexdigest()


def _relative_to_source_root(path: Path, source_root: Path | None) -> str:
    return _relative_path(path, source_root)


def _relative_path(path: Path, root: Path | None) -> str:
    if root is not None:
        try:
            return str(path.resolve().relative_to(root.resolve())).replace("/", "\\")
        except ValueError:
            pass
    return str(path.resolve())


def _matches_any_glob(relative_path: str, patterns: list[str]) -> bool:
    normalized = relative_path.replace("\\", "/")
    return any(Path(normalized).match(pattern) for pattern in patterns)


def _stable_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
