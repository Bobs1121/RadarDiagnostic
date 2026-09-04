# -*- coding: utf-8 -*-
"""
Corner Radar Analysis Tool — Unified CLI

Three modes:
  Diagnosis:   python cli.py <case_folder> -p "problem" -e "expected"
  Data Query:  python cli.py <case_folder> -q "FCTB触发时AEBIB是否激活"
  Dream:       python cli.py --dream

Daily diagnosis stays non-blocking by default; dream/prewarm maintenance is explicit.
"""
import copy
import os
import re
import sys
import io
import argparse
import datetime
import json
import subprocess
import yaml
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown

console = Console()
PROJECT_ROOT = Path(__file__).parent

load_dotenv(PROJECT_ROOT / ".env")

_config_cache: dict[str, dict] = {}  # variant_id -> cached base config copied per run
_router_cache = None

_ENV_PATTERN = re.compile(r"\$\{([^}]+)\}")


def _resolve_env(value):
    """Recursively resolve ${VAR} and ${VAR:-default} placeholders in config values."""
    if isinstance(value, str):
        def _replacer(m):
            expr = m.group(1)
            if ":-" in expr:
                var, default = expr.split(":-", 1)
                return os.environ.get(var.strip(), default.strip())
            return os.environ.get(expr.strip(), m.group(0))
        return _ENV_PATTERN.sub(_replacer, value)
    if isinstance(value, dict):
        return {k: _resolve_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_env(v) for v in value]
    return value


def load_config(
    variant_id: str | None = None,
    package_profile_id: str | None = None,
) -> dict:
    """Load config.yaml, resolve env vars, and merge in project config.

    New identity parameters:
        variant_id:          Canonical variant ID (e.g. "gen6/gwm_b26").
        package_profile_id:  Package profile ID (e.g. "gen6/gwm_b26/default").

    Precedence: --variant > default_variant > default_project
    """
    global _config_cache

    from config import (
        load_config as _load_config_base,
        get_project,
        resolve_codegraph_db,
        resolve_memory_dir,
        resolve_snapshots_dir,
        resolve_source_docs_dir,
        resolve_variant_id,
        sanitize_variant_workspace_name,
    )

    # Resolve the effective identifier
    cfg = _load_config_base(PROJECT_ROOT / "config.yaml")

    if variant_id:
        effective_variant = variant_id
    else:
        effective_variant = resolve_variant_id(cfg, None)

    effective_key = effective_variant
    if effective_key in _config_cache:
        return copy.deepcopy(_config_cache[effective_key])

    # Try new variant system first, fall back to legacy get_project
    proj = {}
    try:
        from config import get_variant, get_package_profile
        variant, codebase, platform = get_variant(cfg, effective_variant)
        source_code = str(codebase.root_path)

        # Resolve package profile
        pkg = None
        if package_profile_id:
            pkg = get_package_profile(cfg, package_profile_id)
        elif variant.default_package_profile:
            try:
                pkg = get_package_profile(cfg, variant.default_package_profile)
            except ValueError:
                pass

        # Build derived paths
        source_docs_dir = resolve_source_docs_dir(
            cfg, PROJECT_ROOT, variant_id=effective_variant
        )
        memory_dir = resolve_memory_dir(
            cfg, PROJECT_ROOT, variant_id=effective_variant
        )
        codegraph_db_path = resolve_codegraph_db(
            cfg, PROJECT_ROOT, variant_id=effective_variant
        )
        snapshots_dir = resolve_snapshots_dir(
            cfg, PROJECT_ROOT, variant_id=effective_variant
        )
        proj = {
            "display_name": variant.display_name,
            "source_code": source_code,
            "key_source_files": variant.key_source_files,
            "dbc_files": [],
            "source_domains": variant.source_domains,
            "source_docs_dir": str(source_docs_dir),
            "memory_dir": str(memory_dir),
            "codegraph_db_path": str(codegraph_db_path),
            "snapshots_dir": str(snapshots_dir),
            "_project_key": variant.compat_project_key,
            "_variant_id": variant.variant_id,
        }
        # Flatten DBC sets into a list
        for dbc_set in variant.dbc_sets:
            proj["dbc_files"].extend(dbc_set.files)
    except (ValueError, ImportError):
        # Fallback to legacy project system
        legacy_key = resolve_variant_id(cfg, None)
        proj = get_project(cfg, legacy_key)

    # Inject into top-level config for backward compat
    cfg["paths"]["project_root"] = str(PROJECT_ROOT)
    cfg["paths"]["source_docs"] = proj["source_docs_dir"]
    cfg["paths"]["source_code"] = proj["source_code"]
    cfg["paths"]["key_source_files"] = proj.get("key_source_files", [])
    cfg["paths"]["dbc_files"] = proj.get("dbc_files", [])
    cfg["project"] = proj

    # Store identity chain if available
    if "_variant_id" in proj:
        cfg["identity"] = {
            "variant_id": proj["_variant_id"],
            "project_key": proj.get("_project_key", ""),
        }
        if package_profile_id or (pkg and hasattr(pkg, "package_profile_id")):
            pid = package_profile_id or (pkg.package_profile_id if pkg else "")
            cfg["identity"]["package_profile_id"] = pid

    _config_cache[effective_key] = copy.deepcopy(cfg)
    return copy.deepcopy(cfg)


def get_router(config: dict | None = None):
    global _router_cache
    if _router_cache is not None:
        return _router_cache
    from ai.model_router import ModelRouter
    if config is None:
        config = load_config()
    _router_cache = ModelRouter(config)
    return _router_cache


def _sanitize_workspace_name(identifier: str) -> str:
    """Keep CLI workspace naming aligned with Workspace.from_variant()."""
    from config import sanitize_variant_workspace_name

    return sanitize_variant_workspace_name(identifier)


def resolve_workspace_context(
    config: dict,
    workspace_override: str | None = None,
    project_root: Path | None = None,
) -> dict:
    """Resolve the workspace directory without requiring it to exist.

    This is intentionally reporting-only for PR1. The legacy CLI must remain
    runnable even when `.workspaces/` has not been created yet, so the main CLI
    does not instantiate `Workspace` here.
    """
    root = project_root or PROJECT_ROOT
    if workspace_override:
        workspace_name = _sanitize_workspace_name(workspace_override)
    else:
        variant_id = (
            config.get("identity", {}).get("variant_id")
            or config.get("default_variant", "")
            or "default"
        )
        workspace_name = _sanitize_workspace_name(variant_id)

    workspace_dir = root / ".workspaces" / workspace_name
    return {
        "name": workspace_name,
        "path": str(workspace_dir),
        "exists": workspace_dir.exists(),
    }


def _detect_git_branch(source_root: Path) -> tuple[str | None, str, str | None]:
    """Probe git branch state without mutating the target repository."""
    try:
        repo_check = subprocess.run(
            ["git", "-C", str(source_root), "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            check=False,
            text=True,
        )
    except OSError as exc:
        return None, "git_unavailable", str(exc)

    if repo_check.returncode != 0 or repo_check.stdout.strip().lower() != "true":
        detail = repo_check.stderr.strip() or repo_check.stdout.strip() or "Source root is not a git repository."
        return None, "not_git_repo", detail

    branch_check = subprocess.run(
        ["git", "-C", str(source_root), "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True,
        check=False,
        text=True,
    )
    if branch_check.returncode != 0:
        detail = branch_check.stderr.strip() or branch_check.stdout.strip() or "Failed to detect current git branch."
        return None, "git_error", detail

    return branch_check.stdout.strip(), "git_repo", None


def _resolve_source_root_path(source_root_value: str, root: Path) -> str:
    source_root = Path(source_root_value).expanduser()
    if not source_root.is_absolute():
        source_root = (root / source_root).resolve()
    else:
        source_root = source_root.resolve()
    if not source_root.exists():
        raise ValueError(f"Source root not found: {source_root}")
    if not source_root.is_dir():
        raise ValueError(f"Source root is not a directory: {source_root}")
    return str(source_root)


def _resolve_case_dir_path(case_dir_value: str | Path, project_root: Path | None = None) -> Path:
    case_dir = Path(case_dir_value).expanduser()
    root = project_root or PROJECT_ROOT
    if not case_dir.is_absolute():
        case_dir = root / case_dir
    return case_dir.resolve() if case_dir.exists() else case_dir


def _normalize_case_metadata_value(value: object) -> str:
    if value is None:
        return ""
    return "".join(re.findall(r"[a-z0-9]+", str(value).lower()))


def _normalize_coem_project_value(value: object) -> str:
    tokens = re.findall(r"[a-z0-9]+", str(value).lower())
    if tokens and tokens[0] == "coem":
        tokens = tokens[1:]
    return "".join(tokens)


def _load_case_metadata_payload(metadata_path: Path) -> dict:
    try:
        if metadata_path.suffix.lower() == ".json":
            payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        else:
            payload = yaml.safe_load(metadata_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
        raise ValueError(f"Invalid case metadata file '{metadata_path}': {exc}") from exc

    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ValueError(f"Case metadata file '{metadata_path}' must contain a mapping/object.")
    return payload


def _get_case_metadata_value(payload: dict, *keys: str) -> str | None:
    scopes = [payload]
    for section_name in ("identity", "project"):
        section = payload.get(section_name)
        if isinstance(section, dict):
            scopes.append(section)

    for scope in scopes:
        for key in keys:
            value = scope.get(key)
            if value is None:
                continue
            text = str(value).strip()
            if text:
                return text
    return None


def _load_case_identity_metadata(case_dir: str | Path) -> dict | None:
    case_path = Path(case_dir)
    if not case_path.exists() or not case_path.is_dir():
        return None

    for metadata_name in ("case.yaml", "case.yml", "metadata.json"):
        metadata_path = case_path / metadata_name
        if not metadata_path.is_file():
            continue

        payload = _load_case_metadata_payload(metadata_path)
        metadata = {
            "source_path": str(metadata_path),
            "source_name": metadata_path.name,
        }
        variant_id = _get_case_metadata_value(payload, "variant_id", "variant")
        customer = _get_case_metadata_value(payload, "customer")
        vehicle_project = _get_case_metadata_value(payload, "vehicle_project")
        coem_project_dir = _get_case_metadata_value(
            payload,
            "coem_project_dir",
            "coem_project",
        )

        if variant_id:
            metadata["variant_id"] = variant_id
        if customer:
            metadata["customer"] = customer
        if vehicle_project:
            metadata["vehicle_project"] = vehicle_project
        if coem_project_dir:
            metadata["coem_project_dir"] = coem_project_dir

        if any(key in metadata for key in ("variant_id", "customer", "vehicle_project", "coem_project_dir")):
            return metadata

    return None


def _resolve_variant_from_case_metadata(config: dict, case_dir: str | Path) -> dict | None:
    metadata = _load_case_identity_metadata(case_dir)
    if metadata is None:
        return None

    variants = config.get("variants") or {}
    if not isinstance(variants, dict) or not variants:
        return None

    metadata_variant_id = metadata.get("variant_id")
    if metadata_variant_id:
        from config import resolve_variant_id

        candidate = resolve_variant_id(config, str(metadata_variant_id))
        if candidate in variants:
            return {
                "variant_id": candidate,
                "origin": "case_metadata",
                "metadata": metadata,
            }

    customer_key = _normalize_case_metadata_value(metadata.get("customer"))
    vehicle_key = _normalize_case_metadata_value(metadata.get("vehicle_project"))
    coem_key = _normalize_coem_project_value(metadata.get("coem_project_dir"))
    has_customer_vehicle = bool(customer_key and vehicle_key)
    if not has_customer_vehicle and not coem_key:
        return None

    matches: list[str] = []
    for variant_id, variant_raw in variants.items():
        if not isinstance(variant_raw, dict):
            continue

        if has_customer_vehicle:
            variant_customer = _normalize_case_metadata_value(variant_raw.get("customer"))
            variant_vehicle = _normalize_case_metadata_value(variant_raw.get("vehicle_project"))
            if variant_customer != customer_key or variant_vehicle != vehicle_key:
                continue

        if coem_key:
            variant_coem = _normalize_coem_project_value(variant_raw.get("coem_project_dir"))
            if variant_coem != coem_key:
                continue

        matches.append(variant_id)

    if len(matches) == 1:
        return {
            "variant_id": matches[0],
            "origin": "case_metadata",
            "metadata": metadata,
        }
    if len(matches) > 1:
        candidates = ", ".join(sorted(matches))
        source_name = metadata.get("source_name", "case metadata")
        raise ValueError(
            f"Case metadata in '{source_name}' matches multiple variants: {candidates}. "
            "Pass --variant to select one explicitly."
        )
    return None


def _resolve_source_context_defaults(config: dict) -> tuple[dict, dict]:
    """Merge top-level and per-variant source_context defaults."""
    defaults = config.get("source_context") or {}
    variant_id = (
        config.get("identity", {}).get("variant_id")
        or config.get("default_variant", "")
    )
    variant_defaults = {}
    if variant_id:
        variant_defaults = (
            config.get("variants", {}).get(variant_id, {}).get("source_context") or {}
        )

    merged = {}
    origins = {}
    for key in ("source_root", "code_branch", "allow_branch_mismatch"):
        if key in defaults:
            merged[key] = defaults.get(key)
            origins[key] = "config"
        if key in variant_defaults:
            merged[key] = variant_defaults.get(key)
            origins[key] = f"variant:{variant_id}"
    return merged, origins


def apply_source_context(
    config: dict,
    source_root_override: str | None = None,
    code_branch: str | None = None,
    allow_branch_mismatch: bool | None = None,
    project_root: Path | None = None,
) -> dict:
    """Apply source-root and branch metadata without mutating git state."""
    root = project_root or PROJECT_ROOT
    paths = config.setdefault("paths", {})
    project = config.setdefault("project", {})
    identity = config.setdefault("identity", {})
    source_context_defaults, source_context_origins = _resolve_source_context_defaults(config)

    source_root_value = paths.get("source_code") or project.get("source_code")
    source_root_origin = "derived_codebase" if source_root_value else None

    configured_source_root = source_context_defaults.get("source_root")
    if isinstance(configured_source_root, str):
        configured_source_root = configured_source_root.strip()

    if source_root_override:
        source_root_value = _resolve_source_root_path(source_root_override, root)
        source_root_origin = "cli"
    elif configured_source_root:
        source_root_value = _resolve_source_root_path(configured_source_root, root)
        source_root_origin = source_context_origins.get("source_root", "config")
    if source_root_value:
        paths["source_code"] = source_root_value
        project["source_code"] = source_root_value

    expected_branch = code_branch
    code_branch_origin = "cli" if code_branch else None
    if expected_branch is None:
        expected_branch = source_context_defaults.get("code_branch")
        if isinstance(expected_branch, str):
            expected_branch = expected_branch.strip()
        if not expected_branch:
            expected_branch = None
        if expected_branch:
            code_branch_origin = source_context_origins.get("code_branch", "config")

    allow_branch_mismatch_value = allow_branch_mismatch
    allow_branch_mismatch_origin = "cli" if allow_branch_mismatch is not None else None
    if allow_branch_mismatch_value is None:
        allow_branch_mismatch_value = bool(
            source_context_defaults.get("allow_branch_mismatch", False)
        )
        allow_branch_mismatch_origin = source_context_origins.get(
            "allow_branch_mismatch", "default"
        )

    identity["source_root"] = source_root_value
    if source_root_origin:
        identity["source_root_origin"] = source_root_origin
    else:
        identity.pop("source_root_origin", None)
    identity["code_branch_expected"] = expected_branch
    identity["code_branch_current"] = None
    identity["code_branch_status"] = "not_checked"
    identity["allow_branch_mismatch"] = allow_branch_mismatch_value
    identity["allow_branch_mismatch_origin"] = allow_branch_mismatch_origin
    if code_branch_origin:
        identity["code_branch_origin"] = code_branch_origin
    else:
        identity.pop("code_branch_origin", None)
    source_origins = {origin for origin in (source_root_origin, code_branch_origin) if origin}
    if len(source_origins) == 1:
        identity["source_context_origin"] = source_origins.pop()
    elif len(source_origins) > 1:
        identity["source_context_origin"] = "mixed"
    else:
        identity.pop("source_context_origin", None)
    identity.pop("code_branch_note", None)

    if not expected_branch:
        return identity

    if not source_root_value:
        identity["code_branch_status"] = "source_root_unset"
        identity["code_branch_note"] = "No source root is configured, so branch validation was skipped."
        return identity

    source_root = Path(source_root_value)
    if not source_root.exists():
        identity["code_branch_status"] = "source_root_missing"
        identity["code_branch_note"] = f"Source root does not exist: {source_root}"
        return identity
    if not source_root.is_dir():
        identity["code_branch_status"] = "source_root_not_dir"
        identity["code_branch_note"] = f"Source root is not a directory: {source_root}"
        return identity

    current_branch, repo_status, detail = _detect_git_branch(source_root)
    if repo_status != "git_repo":
        identity["code_branch_status"] = repo_status
        if detail:
            identity["code_branch_note"] = detail
        return identity

    identity["code_branch_current"] = current_branch
    if current_branch == expected_branch:
        identity["code_branch_status"] = "match"
        return identity

    mismatch_note = (
        f"Code branch mismatch for source root '{source_root}': expected '{expected_branch}', "
        f"current '{current_branch}'."
    )
    identity["code_branch_note"] = mismatch_note
    if allow_branch_mismatch_value:
        identity["code_branch_status"] = "mismatch_allowed"
        return identity

    identity["code_branch_status"] = "mismatch"
    raise ValueError(
        mismatch_note + " Set source_context.allow_branch_mismatch: true or re-run with --allow-branch-mismatch to continue without changing git state."
    )


def _run_module_subcommand(argv: list[str]) -> int:
    """Dispatch a V3 standalone-module subcommand (M1..M8).

    Additive and backward-compatible: this is only invoked when ``argv[0]``
    matches a registered module name (e.g. ``code-query``, ``data-explore``,
    ``req-review``). All legacy invocations (case_dir first, ``--dream``, etc.)
    bypass this path entirely.
    """
    from ai.modules import MODULE_REGISTRY

    name = argv[0]
    module_cls = MODULE_REGISTRY.get(name)
    if module_cls is None:
        console.print(f"[red]Unknown module '{name}'.[/red] "
                      f"Available: {', '.join(sorted(MODULE_REGISTRY)) or '(none)'}")
        return 2

    sub = argparse.ArgumentParser(prog=f"cli.py {name}", description=module_cls.description)
    fake_subparsers = argparse.ArgumentParser().add_subparsers()
    # Let the module declare its own args via the frozen BaseModule contract.
    module_parser = module_cls.register_cli(fake_subparsers)
    for action in module_parser._actions:  # re-home the module's args onto `sub`
        if action.dest in ("help", "_module_cls"):
            continue
        argspec = _clone_argparse_action(action)
        if argspec is not None:
            opt_strings, kwargs = argspec
            sub.add_argument(*opt_strings, **kwargs)
    args = sub.parse_args(argv[1:])

    try:
        module = module_cls.from_cli_args(args)
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]Failed to init module '{name}': {exc}[/red]")
        return 1

    kwargs = {k: v for k, v in vars(args).items() if not k.startswith("_")}
    result = module.safe_run(**kwargs)
    console.print_json(data=result.to_dict())
    return 0 if result.ok else 1


def _run_capabilities_subcommand(argv: list[str]) -> int:
    """Print the Pi-visible atomic capability catalog.

    The product entry point is Pi, but a small catalog command is useful for
    operators and CI to verify that the generated extension and the Python
    registry expose the same leaf capabilities.  Keep this command
    read-only: it must never instantiate or execute a capability.
    """
    parser = argparse.ArgumentParser(
        prog="cli.py capabilities",
        description="List registered Pi atomic capabilities",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit the machine-readable Pi capability catalog (default)",
    )
    parser.add_argument(
        "--kind",
        choices=("all", "module", "tool"),
        default="all",
        help="filter the catalog by registry kind",
    )
    args = parser.parse_args(argv[1:])

    from ai.capability.registry import list_capabilities

    capabilities = list_capabilities(
        include_modules=args.kind in {"all", "module"},
        include_tools=args.kind in {"all", "tool"},
    )
    capabilities = [
        item for item in capabilities
        if item.expose_to_pi
        and item.name not in {"pi", "agent-repl", "agent-loop", "ask_user"}
    ]
    # ``--json`` is intentionally accepted for compatibility with the
    # documented operator command.  JSON is the default because Pi/CI should
    # consume the same catalog without parsing human-oriented output.
    import json

    print(json.dumps([item.to_dict() for item in capabilities], ensure_ascii=False, indent=2))
    return 0


def _clone_argparse_action(action) -> tuple[list[str], dict] | None:
    """Copy a module-owned optional argparse action onto the dispatch parser."""
    opt_strings = list(getattr(action, "option_strings", []) or [])
    if not opt_strings:
        return None

    kwargs = {"help": action.help, "dest": action.dest}
    action_name = action.__class__.__name__
    if action_name == "_StoreTrueAction":
        kwargs["action"] = "store_true"
        return opt_strings, kwargs
    if action_name == "_StoreFalseAction":
        kwargs["action"] = "store_false"
        return opt_strings, kwargs
    if action_name == "_AppendAction":
        kwargs["action"] = "append"

    for attr in ("default", "choices", "required", "type", "nargs", "const", "metavar"):
        value = getattr(action, attr, None)
        if value is not None:
            kwargs[attr] = value
    return opt_strings, kwargs


def _auto_dream_on_case_start_enabled(config: dict) -> bool:
    runtime = config.get("runtime")
    if not isinstance(runtime, dict):
        return False
    return bool(runtime.get("auto_dream_on_case_start", False))


def _affected_freshness_caches(freshness: dict) -> list[str]:
    caches: list[str] = []
    if (
        freshness.get("code_changed")
        or freshness.get("constants_changed")
        or freshness.get("identity_changed")
    ):
        caches.extend(["source_docs", "memory/code_knowledge", "variable_chains"])
    if freshness.get("dbc_changed"):
        caches.append("DBC-backed analysis context")
    if freshness.get("requirements_changed") or freshness.get("identity_changed"):
        caches.append("requirements/material knowledge")
    if freshness.get("any_changed"):
        caches.append("auto-dream provenance")
    deduped: list[str] = []
    for item in caches:
        if item not in deduped:
            deduped.append(item)
    return deduped


def _check_variant_freshness(
    config: dict,
    project_root: Path,
    update: bool = False,
) -> dict:
    from config import resolve_memory_dir
    from core.freshness import (
        compute_variant_fingerprint,
        compare_freshness,
        load_freshness_state,
        write_freshness_state,
    )

    variant_id = config.get("identity", {}).get("variant_id")
    memory_dir = resolve_memory_dir(config, project_root, variant_id=variant_id)
    state_path = memory_dir / "freshness_state.json"
    try:
        previous_state = load_freshness_state(memory_dir)
        current = compute_variant_fingerprint(config, project_root)
        delta = compare_freshness(previous_state, current)
        if update:
            previous_state = write_freshness_state(memory_dir, current)
            # The just-published fingerprint is the new baseline for this run.
            delta = compare_freshness(current, current)
        summary = {
            "variant_id": current.get("variant_id"),
            "source_root": current.get("source_root"),
            "current_branch": current.get("current_branch"),
            "current_commit": current.get("current_commit"),
            "key_source_files_hash": current.get("key_source_files_hash"),
            "source_scope_hash": current.get("source_scope_hash"),
            "constants_source_hash": current.get("constants_source_hash"),
            "dbc_hash": current.get("dbc_hash"),
            "requirements_hash": current.get("requirements_hash"),
            "config_identity_hash": current.get("config_identity_hash"),
            "state_path": str(state_path),
            "memory_dir": str(memory_dir),
            "updated_at": (previous_state or {}).get("updated_at"),
            "affected_caches": _affected_freshness_caches(delta),
            **delta,
        }
    except Exception as exc:
        summary = {
            "available": False,
            "any_changed": False,
            "changed_keys": [],
            "state_path": str(state_path),
            "memory_dir": str(memory_dir),
            "error": str(exc),
        }
    config.setdefault("identity", {})["freshness"] = summary
    return summary


def _print_variant_freshness(freshness: dict) -> None:
    if freshness.get("available") is False:
        console.print(f"  [yellow]Freshness check skipped:[/yellow] {freshness.get('error', 'unavailable')}")
        return
    if freshness.get("any_changed"):
        changed = ", ".join(freshness.get("changed_keys", [])) or "unknown"
        caches = ", ".join(freshness.get("affected_caches", [])) or "knowledge caches"
        console.print(
            f"  [yellow]Freshness drift:[/yellow] {changed} "
            f"[dim](affected: {caches})[/dim]"
        )
        return

    console.print("  [dim]Freshness: current[/dim]")


def main():
    # Read-only operator/CI catalog.  This must run before legacy argparse,
    # otherwise ``capabilities --json`` is interpreted as a case directory.
    if len(sys.argv) > 1 and sys.argv[1] in {"capabilities", "capability-catalog"}:
        sys.exit(_run_capabilities_subcommand(sys.argv[1:]))

    # ── V3 standalone-module dispatch (additive, backward-compatible) ──
    # If the first CLI token names a registered module, route to it and exit
    # before the legacy diagnosis/query parser runs.
    try:
        from ai.modules import MODULE_REGISTRY
        if len(sys.argv) > 1 and sys.argv[1] in MODULE_REGISTRY:
            sys.exit(_run_module_subcommand(sys.argv[1:]))
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001 - never let dispatch break the legacy CLI
        pass

    parser = argparse.ArgumentParser(
        description="Corner Radar AI Analysis Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python cli.py cases/FCTA001 -p "FCTA没有触发" -e "应该触发"
  python cli.py cases/FCTA001 -q "FCTB触发时AEBIB是否激活"
  python cli.py cases/FCTA001 -p "FCTA没有触发" -e "应该触发" --auto-dream
  python cli.py --dream                  # memory consolidation (冷启动会自动深度学习源代码)
        """,
    )
    parser.add_argument("case_dir", nargs="?", help="Case folder containing .bag/.blf files")

    # ── Identity selection (new + legacy) ──────────────────────────
    # Identity arguments
    id_group = parser.add_argument_group("Identity (variant/snapshot)")
    id_group.add_argument("--variant", default=None,
        help="Variant path (e.g. coem/GWM_B26). Overrides config.yaml variant.")
    id_group.add_argument("--package-profile", default=None,
        help="Package profile ID (e.g. gen6/gwm_b26/default). "
             "Auto-resolved from variant if omitted.")
    id_group.add_argument("--snapshot", default=None,
        help="Snapshot ID to load (replay), 'auto' to create one for this run. "
             "Default: 'auto' for diagnosis mode, None otherwise.")
    id_group.add_argument("--workspace", default=None,
        help="Workspace directory override under .workspaces/ (e.g. coem_GWM_B26). "
             "Defaults to the sanitized variant id and is reporting-only for now.")
    id_group.add_argument("--source-root", default=None,
        help="Source code root override for this run only. Does not update config.yaml or git.")
    id_group.add_argument("--code-branch", default=None,
        help="Expected git branch for the source root. Validation only; never checks out branches.")
    id_group.add_argument("--allow-branch-mismatch", action="store_true", default=None,
        help="Continue when --code-branch does not match the current git branch.")

    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--query", "-q", help="Data query (natural language question)")
    mode_group.add_argument("--problem", "-p", help="Problem description (diagnosis mode)")
    mode_group.add_argument("--plot-signals", help="Comma-separated list of CAN signals to plot (e.g. 'VehSpd_0x137,FCTA_Warn')")
    mode_group.add_argument("--plot-query", help="Natural language query to automatically select and plot relevant signals")

    parser.add_argument("--expected", "-e", help="Expected behavior (diagnosis mode)")
    parser.add_argument("--dream", action="store_true", help="Force memory consolidation")
    parser.add_argument(
        "--auto-dream",
        action="store_true",
        help="Run one gated auto-dream pass before case mode routing for this run.",
    )
    parser.add_argument(
        "--learn-constants",
        action="store_true",
        help="Re-learn the global numeric constants table (paraDefine.h / dotCalibDefine.h / "
             "adasFunc.c). Fast (1 AI call) and skipped automatically if source is unchanged.",
    )
    parser.add_argument(
        "--prewarm",
        action="store_true",
        help="Phase 15 (2.1.1): pre-warm source_docs + code knowledge + variable_chains "
             "cache before diagnosis (skips Step-1 LLM if cache is fresh).",
    )
    parser.add_argument(
        "--prewarm-force",
        action="store_true",
        help="Force full rebuild during --prewarm (bypass all caches).",
    )
    parser.add_argument(
        "--codegraph-stats",
        action="store_true",
        help="Show CodeGraph statistics (debug only).",
    )
    args = parser.parse_args()

    case_variant_context = None
    effective_variant = args.variant
    if not effective_variant and args.case_dir:
        case_dir = _resolve_case_dir_path(args.case_dir, PROJECT_ROOT)
        if case_dir.exists() and case_dir.is_dir():
            from config import load_config as _load_base_config

            base_config = _load_base_config(PROJECT_ROOT / "config.yaml")
            try:
                case_variant_context = _resolve_variant_from_case_metadata(base_config, case_dir)
            except ValueError as exc:
                parser.error(str(exc))
            if case_variant_context:
                effective_variant = case_variant_context["variant_id"]
                args.variant = effective_variant

    # ── Load config early (needed by all sub-commands) ──────────────
    config = load_config(
        variant_id=effective_variant,
        package_profile_id=args.package_profile,
    )
    if case_variant_context:
        identity = config.setdefault("identity", {})
        identity["variant_origin"] = "case_metadata"
        identity["case_metadata_source"] = case_variant_context["metadata"].get("source_path")
        identity["case_metadata"] = {
            key: value
            for key, value in case_variant_context["metadata"].items()
            if key not in {"source_name", "source_path"}
        }

    try:
        apply_source_context(
            config,
            source_root_override=args.source_root,
            code_branch=args.code_branch,
            allow_branch_mismatch=args.allow_branch_mismatch,
            project_root=PROJECT_ROOT,
        )
    except ValueError as exc:
        parser.error(str(exc))

    freshness = _check_variant_freshness(config, PROJECT_ROOT, update=False)
    # First-run bootstrap: persist a freshness baseline so the next run can
    # actually detect code drift. Without this, freshness_state.json never
    # exists and every run reports "freshness_state_missing", which keeps all
    # gated knowledge (L6/L3/semantic) permanently stale.
    if (
        "freshness_state_missing" in freshness.get("changed_keys", [])
        and config.get("identity", {}).get("variant_id")
    ):
        _check_variant_freshness(config, PROJECT_ROOT, update=True)

    # ── Resolve snapshot ────────────────────────────────────────────
    snapshot_ctx = _resolve_snapshot(config, args.snapshot, PROJECT_ROOT)
    if snapshot_ctx.get("snapshot_id"):
        ident = config.setdefault("identity", {})
        ident["snapshot_id"] = snapshot_ctx["snapshot_id"]
        sid = snapshot_ctx["snapshot_id"]
        action = snapshot_ctx.get("action", "unknown")
        console.print(f"  [dim]Snapshot: {sid} ({action})[/dim]")

    if args.query and args.expected:
        parser.error("-e/--expected is only used with -p/--problem (diagnosis mode)")

    # ── Show identity context ────────────────────────────────────────
    ident = config.get("identity", {})
    if ident:
        vid = ident.get("variant_id", "")
        pid = ident.get("package_profile_id", "")
        console.print(f"  [dim]Identity: variant={vid}  package={pid}[/dim]")
    source_root = ident.get("source_root", "")
    source_root_origin = ident.get("source_root_origin", "")
    if source_root and (
        source_root_origin != "derived_codebase"
        or ident.get("code_branch_expected")
    ):
        source_root_line = f"  [dim]Source root: {source_root}"
        if source_root_origin:
            source_root_line += f"  origin={source_root_origin}"
        source_root_line += "[/dim]"
        console.print(source_root_line)
    if ident.get("code_branch_expected"):
        expected_branch = ident.get("code_branch_expected", "")
        current_branch = ident.get("code_branch_current")
        status = ident.get("code_branch_status", "not_checked")
        branch_line = f"  [dim]Code branch: expected={expected_branch}"
        if current_branch:
            branch_line += f"  current={current_branch}"
        code_branch_origin = ident.get("code_branch_origin")
        if code_branch_origin:
            branch_line += f"  origin={code_branch_origin}"
        branch_line += f"  status={status}[/dim]"
        console.print(branch_line)
        if status in {
            "git_error",
            "git_unavailable",
            "mismatch_allowed",
            "not_git_repo",
            "source_root_missing",
            "source_root_not_dir",
            "source_root_unset",
        }:
            note = ident.get("code_branch_note")
            if note:
                console.print(f"  [yellow]Branch check warning:[/yellow] {note}")
    _print_variant_freshness(freshness)

    ws_ctx = resolve_workspace_context(config, args.workspace, PROJECT_ROOT)
    ident = config.setdefault("identity", {})
    ident["workspace"] = ws_ctx["name"]
    ident["workspace_dir"] = ws_ctx["path"]
    ws_state = "present" if ws_ctx["exists"] else "absent"
    console.print(
        f"  [dim]Workspace: {ws_ctx['name']} ({ws_state}) -> {ws_ctx['path']}[/dim]"
    )

    # ── Learn-constants only mode ───────────────────────────────────────
    if args.learn_constants:
        _run_learn_constants(config)
        if not args.case_dir:
            return

    # ── Pre-warm (Phase 15 / 2.1.1) ────────────────────────────────────
    # Pre-warms source_docs + L6 code_knowledge + variable_chains cache.
    # If --case-dir is also provided, pre-warm runs before diagnosis;
    # otherwise pre-warm is a standalone command and exits.
    if args.prewarm:
        _run_prewarm(config, force=args.prewarm_force)
        if not args.case_dir:
            return

    # ── CodeGraph stats (debug only) ────────────────────────────────────
    if args.codegraph_stats:
        _show_codegraph_stats(config)
        if not args.case_dir:
            return

    # ── Dream-only mode ─────────────────────────────────────────────────
    if args.dream:
        _run_dream(force=True, config=config)
        if not args.case_dir:
            return

    # ── No case_dir → show usage ────────────────────────────────────────
    if not args.case_dir:
        console.print("[yellow]Usage:[/yellow]")
        console.print("  [cyan]python cli.py <case_dir> -q \"your question\"[/cyan]  (data query)")
        console.print("  [cyan]python cli.py <case_dir> -p \"problem\" -e \"expected\"[/cyan]  (diagnosis)")
        console.print("  [cyan]python cli.py <case_dir> -p \"problem\" -e \"expected\" --auto-dream[/cyan]  (diagnosis + gated dream)")
        console.print("  [cyan]python cli.py --dream[/cyan]  (memory consolidation)")
        console.print("  [cyan]python cli.py --learn-constants[/cyan]  (re-learn numeric constants table)")
        console.print("  [cyan]python cli.py --prewarm[/cyan]  (Phase 15: prewarm source_docs + caches)")
        return

    # ── Validate case_dir ───────────────────────────────────────────────
    case_dir = _resolve_case_dir_path(args.case_dir, PROJECT_ROOT)

    if not case_dir.exists():
        console.print(f"[red]Case folder not found: {case_dir}[/red]")
        sys.exit(1)

    bag_files = list(case_dir.glob("*.bag"))
    blf_files = list(case_dir.glob("*.blf"))
    mf4_files = list(case_dir.glob("*.mf4"))

    console.print(Panel(
        f"[bold]{case_dir.name}[/bold]\n"
        f"BAG: {len(bag_files)} file(s)  {', '.join(f.name for f in bag_files) or '-'}\n"
        f"BLF: {len(blf_files)} file(s)  {', '.join(f.name for f in blf_files) or '-'}\n"
        f"MF4: {len(mf4_files)} file(s)  {', '.join(f.name for f in mf4_files) or '-'}",
        title="Corner Radar Analysis",
        border_style="blue",
    ))

    if not bag_files and not blf_files and not mf4_files:
        console.print("[red]No .bag, .blf, or .mf4 files in the case folder![/red]")
        sys.exit(1)

    # ── Optional auto-dream before case routing ──────────────────────────
    if not args.dream and (
        args.auto_dream or _auto_dream_on_case_start_enabled(config)
    ):
        _run_dream(force=False, config=config)

    # ── Determine mode ──────────────────────────────────────────────────
    mode = None
    if args.query:
        mode = "query"
    elif args.problem:
        mode = "diagnose"

    if mode is None:
        if args.plot_signals or args.plot_query:
            mode = "plot"
        else:
            console.print("\n[bold]Select mode:[/bold]")
            console.print("  [cyan]1[/cyan] Data query  (ask a question about the data)")
            console.print("  [cyan]2[/cyan] Diagnosis   (full problem diagnosis)")
            choice = console.input("\n[bold cyan]Choice (1/2): [/bold cyan]").strip()
            if choice == "1":
                mode = "query"
                args.query = console.input("[bold cyan]Question: [/bold cyan]")
            elif choice == "2":
                mode = "diagnose"
            else:
                console.print("[red]Invalid choice. Use 1 or 2.[/red]")
                sys.exit(1)

    # ── Default snapshot to 'auto' for diagnosis mode ─────────────────
    if mode == "diagnose" and args.snapshot is None:
        args.snapshot = "auto"
        console.print("[dim]Auto-enabling --snapshot auto for diagnosis mode[/dim]")

    # ── Route ───────────────────────────────────────────────────────────
    if mode == "plot":
        # Launch tools.plot_signals inline
        import subprocess
        cmd = [sys.executable, str(PROJECT_ROOT / "tools" / "plot_signals.py"), str(case_dir)]
        if args.plot_signals:
            cmd.extend(["--signals", args.plot_signals])
        else:
            cmd.extend(["--query", args.plot_query])
        if args.variant:
            cmd.extend(["--variant", args.variant])
        
        console.print(f"[dim]Running Plotter: {' '.join(cmd)}[/dim]")
        sys.exit(subprocess.call(cmd))
    elif mode == "query":
        _run_query(case_dir, args.query, config)
    else:
        problem = args.problem
        expected = args.expected
        if not problem:
            problem = console.input("\n[bold cyan]Problem description: [/bold cyan]")
        if not expected:
            expected = console.input("[bold cyan]Expected behavior:   [/bold cyan]")
        if not problem.strip():
            console.print("[red]Problem description cannot be empty.[/red]")
            sys.exit(1)
        console.print(f"\n[dim]Problem:  {problem}[/dim]")
        console.print(f"[dim]Expected: {expected}[/dim]\n")
        _run_diagnosis(case_dir, problem, expected, config)


# ── Snapshot resolution ──────────────────────────────────────────────

def _resolve_snapshot(config: dict, snapshot_arg, project_root: Path) -> dict:
    """Resolve or create a snapshot based on CLI --snapshot argument.

    Returns dict with keys: snapshot_id, snapshot (object), action (created|loaded).
    Returns empty dict if no snapshot requested.

    Independent of CLI-injected config["project"]: resolves variant/codebase
    directly from config.raw yaml via get_variant, then derives source_code,
    key_source_files, and dbc_files from the Variant model.
    """
    if snapshot_arg is None:
        return {}

    from core.snapshot_store import SnapshotStore
    from core.identity import Snapshot, file_sha256
    from core.materials import MaterialRegistry
    from config import resolve_snapshots_dir, resolve_variant_id, get_variant

    store = SnapshotStore(resolve_snapshots_dir(config, project_root))

    # ── Resolve variant_id without relying on config["identity"] ──────
    variant_id = config.get("identity", {}).get("variant_id", "")
    if not variant_id:
        variant_id = resolve_variant_id(config, None)

    # ── Resolve variant + codebase from config.yaml directly ───────────
    source_root = ""
    key_files: list[str] = []
    dbc_files: list[str] = []
    source_docs_dir = ""

    try:
        variant, codebase, _ = get_variant(config, variant_id)
        source_root = str(codebase.root_path)
        key_files = variant.key_source_files or []
        for dbc_set in (variant.dbc_sets or []):
            dbc_files.extend(dbc_set.files)
        proj_safe = variant_id.replace("/", "_").replace(" ", "_").lower()
        source_docs_dir = str(project_root / "source_docs" / proj_safe)
    except (ValueError, AttributeError):
        # Fallback: try legacy config["project"] if it exists
        proj = config.get("project", {})
        source_root = proj.get("source_code", "")
        key_files = proj.get("key_source_files", [])
        dbc_files = proj.get("dbc_files", [])
        source_docs_dir = proj.get("source_docs_dir", "")

    if snapshot_arg == "auto":
        # ── Enrich with code / DBC / material hashes ──────────────
        code_snapshot = {}
        dbc_snapshot = {}
        material_snapshot = {}
        summary_parts = []

        # 1) Code snapshot — hash key source files from variant config
        if source_root and key_files:
            source_path = Path(source_root)
            for rf in key_files:
                fp = source_path / rf
                if fp.exists():
                    code_snapshot[str(fp.relative_to(source_path))] = file_sha256(fp)
            summary_parts.append(f"code={len(code_snapshot)} files hashed")

        # 2) DBC snapshot — hash DBC files referenced by variant
        if dbc_files:
            for dbc_name in dbc_files:
                for candidate_root in [Path(source_root), project_root]:
                    fp = candidate_root / dbc_name
                    if fp.exists():
                        dbc_snapshot[dbc_name] = file_sha256(fp)
                        break
            summary_parts.append(f"dbc={len(dbc_snapshot)} files hashed")

        # 3) Material snapshot — discover registered materials for variant
        if variant_id:
            try:
                registry = MaterialRegistry.for_variant(project_root, variant_id)
                for mat in registry.list_by_variant(variant_id):
                    material_snapshot[mat.material_id] = mat.hash
            except Exception:
                pass

            # Auto-register DBC files as materials if they exist
            if dbc_files and source_root:
                try:
                    reg = MaterialRegistry.for_variant(project_root, variant_id)
                    for dbc_name in dbc_files:
                        fp = Path(source_root) / dbc_name
                        if fp.exists():
                            m = reg.register(fp, variant_id, category="authoritative",
                                             tags=["dbc", "auto_registered"])
                            material_snapshot[m.material_id] = m.hash
                except Exception:
                    pass

            if material_snapshot:
                summary_parts.append(f"materials={len(material_snapshot)} registered")

        # 4) Source docs snapshot
        if source_docs_dir:
            sdd = Path(source_docs_dir)
            if sdd.exists():
                doc_files = list(sdd.glob("*.md")) + list(sdd.glob("*.json"))
                summary_parts.append(f"source_docs={len(doc_files)} files")

        snap = Snapshot.create(
            variant_id=variant_id,
            package_profile_id=config.get("identity", {}).get("package_profile_id"),
            code_snapshot=code_snapshot,
            dbc_snapshot=dbc_snapshot,
            material_snapshot=material_snapshot,
            config_version=file_sha256(project_root / "config.yaml") if (project_root / "config.yaml").exists() else "",
            model_profile={
                "remote_model": config.get("ai", {}).get("remote", {}).get("model", ""),
                "local_model": config.get("ai", {}).get("local", {}).get("model", ""),
            },
        )
        snap.metadata["summary"] = "; ".join(summary_parts) if summary_parts else "empty snapshot"
        snap.metadata["source_code"] = source_root
        snap.metadata["variant_id"] = variant_id

        store.save(snap)
        return {"snapshot_id": snap.snapshot_id, "snapshot": snap, "action": "created"}
    else:
        snap = store.load(snapshot_arg)
        return {"snapshot_id": snap.snapshot_id, "snapshot": snap, "action": "loaded"}


# ── Dream ───────────────────────────────────────────────────────────────

def _collect_dream_fresh_categories(result: dict) -> list[str]:
    """Return only module scopes whose refresh result proves success."""
    categories: list[str] = []
    code_delta = result.get("_code_learning") or {}
    if code_delta and not code_delta.get("skipped") and not code_delta.get("error"):
        categories.extend(
            f"code_knowledge:{str(item.get('func', '')).upper()}"
            for item in code_delta.get("learned", [])
            if item.get("func")
        )
        constants_delta = code_delta.get("constants") or {}
        if constants_delta and not constants_delta.get("skipped") and not constants_delta.get("error"):
            categories.append("code_knowledge:constants")
    overview = code_delta.get("overview") or {}
    if overview and not overview.get("error"):
        categories.extend(
            f"source_docs:{str(function).upper()}"
            for function in (overview.get("generated", []) + overview.get("skipped", []))
        )
    chains_delta = result.get("_variable_chains") or {}
    if chains_delta.get("ok"):
        categories.append("variable_chains")
    conditions_delta = result.get("_conditions") or {}
    categories.extend(
        f"conditions:{str(function).upper()}"
        for function in conditions_delta.get("refreshed", [])
    )
    if (result.get("_codegraph") or {}).get("ok"):
        categories.append("codegraph")
    return list(dict.fromkeys(category for category in categories if category))

def _run_dream(force: bool = False, config: dict | None = None):
    from memory.memory_system import MemorySystem
    from memory.auto_dream import AutoDream

    if config is None:
        config = load_config()
    freshness = config.get("identity", {}).get("freshness")
    if not isinstance(freshness, dict):
        freshness = _check_variant_freshness(config, PROJECT_ROOT, update=False)
    proj = config.get("project", {})
    memory_root = Path(proj.get("memory_dir", PROJECT_ROOT / "memory"))

    memory = MemorySystem(PROJECT_ROOT, memory_dir=memory_root, config=config)
    dreamer = AutoDream(memory, get_router(config), PROJECT_ROOT, config=config)
    freshness_force = bool(freshness.get("any_changed"))
    effective_force = force or freshness_force
    force_reason = None
    if freshness_force:
        changed = ", ".join(freshness.get("changed_keys", [])) or "variant inputs changed"
        force_reason = f"variant freshness drift: {changed}"

    if effective_force:
        console.print(Panel(
            "[bold]Forced Dream Cycle[/bold]",
            border_style="magenta",
        ))

    result = dreamer.try_dream(
        on_status=lambda s, d: console.print(f"  [dim magenta][dream] {d}[/dim magenta]"),
        force=effective_force,
        reason=force_reason,
    )
    if result and "error" not in result:
        summary = result.get("summary", "done")
        conflicts = result.get("conflicts_found", [])
        console.print(f"  [magenta]Memory consolidated: {summary}[/magenta]")
        code_delta = result.get("_code_learning") or {}
        if code_delta and not code_delta.get("skipped"):
            learned = code_delta.get("learned_count", 0)
            skipped = code_delta.get("skipped_count", 0)
            warmup = "✓" if code_delta.get("warmup_done") else "…"
            console.print(
                f"  [magenta]Code learning: +{learned} pairs  "
                f"(skipped {skipped})  warmup={warmup}[/magenta]"
            )
            constants_delta = code_delta.get("constants") or {}
            if constants_delta and not constants_delta.get("skipped"):
                cc = constants_delta.get("counts", {})
                console.print(
                    "  [magenta]Constants learned:[/magenta]  "
                    f"vehicle={cc.get('vehicle_config', 0)}, "
                    f"thresholds={cc.get('function_thresholds', 0)}, "
                    f"roi_derived={cc.get('roi_derived', 0)}"
                )
            elif constants_delta.get("skipped"):
                reason = constants_delta.get("reason", "?")
                if reason != "source_unchanged":
                    console.print(f"  [yellow]Constants skipped: {reason}[/yellow]")
        overview = (code_delta or {}).get("overview") or {}
        if overview.get("generated"):
            console.print(
                f"  [magenta]MD overview refreshed: "
                f"{', '.join(overview['generated'])}[/magenta]"
            )
        if conflicts:
            console.print(f"  [yellow]Conflicts resolved: {len(conflicts)}[/yellow]")
        published_categories = _collect_dream_fresh_categories(result)
        if published_categories:
            try:
                from core.knowledge_guard import (
                    partition_stable_categories,
                    publish_knowledge_categories,
                )

                post_freshness = _check_variant_freshness(
                    config, PROJECT_ROOT, update=False
                )
                published_categories, changed_during_refresh = (
                    partition_stable_categories(
                        freshness,
                        post_freshness,
                        published_categories,
                    )
                )
                if changed_during_refresh:
                    console.print(
                        "  [yellow]Knowledge publish withheld; inputs changed "
                        "during Dream:[/yellow] "
                        + ", ".join(changed_during_refresh)
                    )
                if not published_categories:
                    return result

                manifest = publish_knowledge_categories(
                    config,
                    list(dict.fromkeys(published_categories)),
                    producer="auto_dream",
                )
                console.print(
                    "  [magenta]Fresh knowledge published:[/magenta] "
                    + ", ".join(manifest["published"])
                )
            except Exception as exc:
                console.print(f"  [yellow]Knowledge publish skipped: {exc}[/yellow]")

    return result


def _show_codegraph_stats(config: dict | None = None):
    """Show CodeGraph statistics (debug only)."""
    from ai.codegraph import CodeGraph, CodeGraphRenderer

    if config is None:
        config = load_config()
    from config import resolve_codegraph_db
    db_path = resolve_codegraph_db(config, PROJECT_ROOT)
    cg = CodeGraph(db_path)
    renderer = CodeGraphRenderer(cg)
    md = renderer.render_stats()

    console.print(Panel(md, title="CodeGraph Stats", border_style="cyan"))
    cg.close()


def _run_learn_constants(config: dict | None = None):
    """Re-learn the global numeric-constants table."""
    from ai.code_learner import CodeLearner

    if config is None:
        config = load_config()

    console.print(Panel(
        "[bold]Numeric Constants Learning[/bold]\n"
        "[dim]Reading paraDefine.h / dotCalibDefine.h / globalVarDefine.h /\n"
        " adasFunc.c …[/dim]",
        border_style="magenta",
    ))

    try:
        learner = CodeLearner(get_router(config), config, PROJECT_ROOT)
    except Exception as e:
        console.print(f"[red]CodeLearner init failed: {e}[/red]")
        return

    def status(msg: str) -> None:
        console.print(f"  [dim magenta]{msg}[/dim magenta]")

    result = learner._learn_constants_if_needed(status, force=True)

    if result.get("skipped"):
        console.print(f"[yellow]Skipped: {result.get('reason', '?')}[/yellow]")
    else:
        counts = result.get("counts", {})
        console.print(
            "[green]Constants learned:[/green]  "
            f"vehicle_config={counts.get('vehicle_config', 0)}  "
            f"function_thresholds={counts.get('function_thresholds', 0)}  "
            f"roi_derived={counts.get('roi_derived', 0)}"
        )
        console.print(
            f"  [dim]→ saved to memory/code_knowledge/constants.json[/dim]"
        )


# ── Pre-warm (Phase 15 / 2.1.1) ─────────────────────────────────────────

def _run_prewarm(config: dict | None = None, force: bool = False,
                 pair_budget: int | None = None) -> dict:
    """Phase 15 (2.1.1): prewarm source_docs + L6 code_knowledge + variable_chains.

    Three operations run in sequence:
      1. CodeLearner.learn()      — incremental L6 code knowledge (may call LLM)
      2. ensure_overview_docs()    — refresh MD overviews (hash cache; fast if unchanged)
      3. trace_variable_chains()   — build variable_chains.json + .meta.json cache

    Run before diagnosis to avoid Step-1 latency. When ``force=True``,
    every cache is bypassed (full rebuild).

    Returns a dict summary for testing / programmatic use.
    """
    from ai.code_learner import CodeLearner
    from engines.signal_mapper import trace_variable_chains
    from ai.utils import ALL_FUNCTIONS

    if config is None:
        config = load_config()
    freshness = config.get("identity", {}).get("freshness")
    if not isinstance(freshness, dict):
        freshness = _check_variant_freshness(config, PROJECT_ROOT, update=False)

    summary: dict = {"force": force, "operations": {}}
    started = datetime.datetime.now()

    console.print(Panel(
        "[bold]Pre-warming source_docs + code knowledge[/bold]\n"
        f"[dim]Phase 15 (2.1.1) — force={force}  pair_budget={pair_budget}[/dim]",
        border_style="cyan",
    ))

    try:
        learner = CodeLearner(get_router(config), config, PROJECT_ROOT)
    except Exception as e:
        console.print(f"[red]CodeLearner init failed: {e}[/red]")
        summary["error"] = f"init_failed: {e}"
        return summary

    # ── 1. CodeLearner.learn() ─────────────────────────────────────────
    console.print("[cyan]1/3 Code knowledge L6 learn...[/cyan]")

    def learn_status(step: str, detail: str) -> None:
        console.print(f"  [dim cyan][{step}] {detail}[/dim cyan]")

    try:
        learn_delta = learner.learn(
            status_cb=learn_status,
            force_pairs=pair_budget,
            force_constants=force,
        )
        summary["operations"]["learn"] = {
            "learned_count": learn_delta.get("learned_count", 0),
            "skipped_count": learn_delta.get("skipped_count", 0),
            "error_count": learn_delta.get("error_count", 0),
            "learned_functions": sorted({
                str(item.get("func", "")).upper()
                for item in learn_delta.get("learned", [])
                if item.get("func")
            }),
            "constants_refreshed": bool(
                learn_delta.get("constants")
                and not learn_delta.get("constants", {}).get("skipped")
            ),
        }
        if learn_delta.get("learned_count", 0) > 0:
            console.print(
                f"  [green]learned {learn_delta['learned_count']} pairs[/green]"
            )
        else:
            console.print(
                f"  [dim]learned={learn_delta.get('learned_count', 0)}, "
                f"skipped={learn_delta.get('skipped_count', 0)}[/dim]"
            )
    except Exception as e:
        console.print(f"  [red]learn failed: {e}[/red]")
        summary["operations"]["learn"] = {"error": str(e)[:200]}

    # ── 2. ensure_overview_docs() ──────────────────────────────────────
    console.print("[cyan]2/3 MD overview docs...[/cyan]")
    try:
        overview = learner.ensure_overview_docs(
            funcs=ALL_FUNCTIONS,
            force=force,
            status_cb=lambda step, msg: console.print(
                f"  [dim cyan]{msg}[/dim cyan]"
            ),
        )
        summary["operations"]["overview"] = {
            "generated": overview.get("generated", []),
            "skipped": overview.get("skipped", []),
            "failed": overview.get("failed", []),
            "reason": overview.get("reason", ""),
        }
        if overview.get("generated"):
            console.print(
                f"  [green]generated: {', '.join(overview['generated'])}[/green]"
            )
        elif overview.get("reason") == "all_up_to_date":
            console.print("  [dim]all up to date[/dim]")
        if overview.get("failed"):
            for failed in overview["failed"]:
                console.print(
                    f"  [yellow][WARN] {failed['func']}: {failed['error']}[/yellow]"
                )
    except Exception as e:
        console.print(f"  [red]overview failed: {e}[/red]")
        summary["operations"]["overview"] = {"error": str(e)[:200]}

    # ── 3. trace_variable_chains() ─────────────────────────────────────
    console.print("[cyan]3/3 variable_chains cache...[/cyan]")
    alias_count = 0
    # Resolve docs_dir up-front (shared with operation 4 below).
    # Prefer config["paths"]["source_docs"] so tests / non-standard layouts
    # don't accidentally write into the real PROJECT_ROOT.
    source_root = Path(config["paths"]["source_code"])
    configured_docs = (config.get("paths") or {}).get("source_docs")
    proj_safe = (
        config.get("identity", {}).get("variant_id")
        or config.get("default_variant", "default")
    ).replace("/", "_").replace(" ", "_").lower()
    docs_dir = Path(configured_docs) if configured_docs else (
        PROJECT_ROOT / "source_docs" / proj_safe
    )
    docs_dir.mkdir(parents=True, exist_ok=True)
    try:
        chains = trace_variable_chains(source_root, docs_dir, force=force)
        alias_count = len(chains.get("struct_aliases", {}))
        meta_path = docs_dir / "variable_chains.meta.json"
        meta_info = (
            " (forced rebuild)" if force else
            (" (cache hit)" if meta_path.exists() else " (initial build)")
        )
        console.print(f"  [green]{alias_count} struct aliases{meta_info}[/green]")
        summary["operations"]["variable_chains"] = {
            "alias_count": alias_count,
            "meta_path": str(meta_path),
            "meta_exists": meta_path.exists(),
        }
    except Exception as e:
        console.print(f"  [red]variable_chains failed: {e}[/red]")
        summary["operations"]["variable_chains"] = {"error": str(e)[:200]}

    # ── 4. Write prewarm_meta.json ─────────────────────────────────────
    # Use the same per-project source_docs dir as the variable_chains call
    # above (resolved from config), not the bare PROJECT_ROOT path — that
    # would write into the wrong variant's folder.
    elapsed = (datetime.datetime.now() - started).total_seconds()
    summary["timestamp"] = datetime.datetime.now().isoformat()
    summary["elapsed_sec"] = elapsed
    try:
        # Reuse the resolved docs_dir from operation 3 to avoid drift.
        meta_dir = docs_dir if "docs_dir" in locals() else (
            PROJECT_ROOT / "source_docs" / (
                config.get("identity", {}).get("variant_id", "default")
                .replace("/", "_").replace(" ", "_").lower()
            )
        )
        meta_path = meta_dir / "prewarm_meta.json"
        meta_dir.mkdir(parents=True, exist_ok=True)
        meta_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        console.print(
            f"  [dim]→ prewarm_meta.json ({elapsed:.1f}s)[/dim]"
        )
    except Exception as e:
        console.print(f"  [yellow]meta write skipped: {e}[/yellow]")

    operations = summary.get("operations", {})
    operation_errors = [
        name for name, data in operations.items()
        if isinstance(data, dict) and (
            data.get("error")
            or data.get("failed")
            or int(data.get("error_count", 0)) > 0
        )
    ]
    published_categories: list[str] = []
    learn_op = operations.get("learn", {})
    if not learn_op.get("error") and int(learn_op.get("error_count", 0)) == 0:
        published_categories.extend(
            f"code_knowledge:{function}"
            for function in learn_op.get("learned_functions", [])
        )
        if learn_op.get("constants_refreshed"):
            published_categories.append("code_knowledge:constants")
    overview_op = operations.get("overview", {})
    if not overview_op.get("error") and not overview_op.get("failed"):
        published_categories.extend(
            f"source_docs:{str(function).upper()}"
            for function in (
                overview_op.get("generated", []) + overview_op.get("skipped", [])
            )
        )
    chains_op = operations.get("variable_chains", {})
    if chains_op and not chains_op.get("error"):
        published_categories.append("variable_chains")

    manifest_result = None
    if published_categories:
        try:
            from core.knowledge_guard import publish_knowledge_categories

            manifest_result = publish_knowledge_categories(
                config,
                list(dict.fromkeys(published_categories)),
                producer="prewarm",
            )
        except Exception as exc:
            operation_errors.append(f"manifest:{exc}")
    summary["freshness"] = {
        "updated": bool(manifest_result),
        "state_path": freshness.get("state_path"),
        "published": (manifest_result or {}).get("published", []),
        "errors": operation_errors,
    }

    return summary


# ── Query Mode ──────────────────────────────────────────────────────────

def _run_query(case_dir: Path, question: str, config: dict | None = None):
    """Lightweight data query pipeline."""
    from ai.data_query_engine import DataQueryEngine

    if config is None:
        config = load_config()
    engine = DataQueryEngine(get_router(config), config, PROJECT_ROOT)

    steps_display = {
        "parse": "Parsing data",
        "inventory": "Scanning signals",
        "plan": "Understanding question",
        "extract": "Extracting data",
        "investigate": "Linking data and code",
        "answer": "Analyzing",
    }

    def on_status(step, detail=""):
        label = steps_display.get(step, step)
        if detail:
            console.print(f"  [dim]{label}:[/dim] {detail}")
        else:
            console.print(f"  [bold]{label}...[/bold]")

    console.print(Panel(
        f"[bold cyan]{question}[/bold cyan]",
        title="Data Query",
        border_style="cyan",
    ))

    try:
        answer = engine.run_query(
            case_dir=case_dir,
            question=question,
            on_status=on_status,
        )
        console.print()
        console.print(Panel(
            Markdown(answer),
            title="Answer",
            border_style="green",
        ))

    except Exception as e:
        console.print(f"\n[bold red]Error: {e}[/bold red]")
        import traceback
        console.print(f"[dim]{traceback.format_exc()}[/dim]")
        sys.exit(1)


# ── Diagnosis Mode ──────────────────────────────────────────────────────

def _run_diagnosis(case_dir: Path, problem: str, expected: str, config: dict | None = None):
    """Full diagnosis pipeline."""
    from ai.orchestrator import Orchestrator

    if config is None:
        config = load_config()
    orchestrator = Orchestrator(config, PROJECT_ROOT)

    steps_display = {
        "init": "Checking prerequisites",
        "source_docs": "Generating source docs",
        "classify": "Understanding problem and classifying task",
        "extract": "Parsing data and extracting features",
        "evidence": "Gathering evidence (conditions + TPE + probe)",
        "signals": "Analyzing CAN signals",
        "suppression": "Checking suppression signals",
        "output_signals": "Analyzing output signals",
        "tpe": "Temporal Pattern Engine",
        "diagnose": "Expert panel diagnosis",
        "fix": "Generating code fix suggestions",
        "deliver": "Generating report and delivering results",
    }

    def on_status(step, detail=""):
        label = steps_display.get(step, step)
        if detail:
            console.print(f"  [dim]{label}:[/dim] {detail}")
        else:
            console.print(f"  [bold]{label}...[/bold]")

    try:
        report_path = orchestrator.run_diagnosis(
            case_dir=case_dir,
            problem=problem,
            expected=expected,
            on_status=on_status,
        )

        console.print(f"\n[bold green]Report saved: {report_path}[/bold green]\n")

        report_content = Path(report_path).read_text(encoding="utf-8")
        console.print(Panel(
            Markdown(report_content),
            title="Diagnosis Report",
            border_style="green",
        ))

    except Exception as e:
        console.print(f"\n[bold red]Error: {e}[/bold red]")
        import traceback
        console.print(f"[dim]{traceback.format_exc()}[/dim]")
        sys.exit(1)


if __name__ == "__main__":
    # Keep pytest/global capture stable on import; only reconfigure streams
    # when running cli.py as a script.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    else:
        sys.stdout = io.TextIOWrapper(
            sys.stdout.buffer,
            encoding="utf-8",
            errors="replace",
            line_buffering=True,
        )
        sys.stderr = io.TextIOWrapper(
            sys.stderr.buffer,
            encoding="utf-8",
            errors="replace",
            line_buffering=True,
        )
    main()
