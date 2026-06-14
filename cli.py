# -*- coding: utf-8 -*-
"""
Corner Radar Analysis Tool — Unified CLI

Three modes:
  Diagnosis:   python cli.py <case_folder> -p "problem" -e "expected"
  Data Query:  python cli.py <case_folder> -q "FCTB触发时AEBIB是否激活"
  Dream:       python cli.py --dream

Everything else is automatic.
"""
import os
import re
import sys
import io
import argparse
import yaml
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown

console = Console()
PROJECT_ROOT = Path(__file__).parent

load_dotenv(PROJECT_ROOT / ".env")

_config_cache: dict[str, dict] = {}  # project_key -> config (fixes cross-project pollution)
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


def _get_default_project_key() -> str:
    """Get the default project key from config.yaml without loading full config."""
    import yaml
    with open(PROJECT_ROOT / "config.yaml", "r") as f:
        raw = yaml.safe_load(f)
    return raw.get("default_project", "gwm_b26")


def load_config(
    project_key: str | None = None,
    variant_id: str | None = None,
    package_profile_id: str | None = None,
) -> dict:
    """Load config.yaml, resolve env vars, and merge in project config.

    New identity parameters:
        variant_id:          Canonical variant ID (e.g. "gen6/gwm_b26").
        package_profile_id:  Package profile ID (e.g. "gen6/gwm_b26/default").

    Backward compat:
        project_key:         Legacy project key (e.g. "gwm_b26").  Still works
                             but maps to the new variant system internally.

    Precedence: --variant > -P/--project > default_variant > default_project
    """
    global _config_cache

    from config import (
        load_config as _load_config_base,
        get_project,
        resolve_variant_id,
        resolve_source_code,
    )

    # Resolve the effective identifier
    cfg = _load_config_base(PROJECT_ROOT / "config.yaml")

    if variant_id:
        effective_variant = variant_id
    elif project_key:
        effective_variant = resolve_variant_id(cfg, project_key)
    else:
        effective_variant = resolve_variant_id(cfg, None)

    effective_key = effective_variant
    if effective_key in _config_cache:
        return _config_cache[effective_key]

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
        proj_safe = effective_variant.replace("/", "_").replace(" ", "_").lower()
        proj = {
            "display_name": variant.display_name,
            "source_code": source_code,
            "key_source_files": variant.key_source_files,
            "dbc_files": [],
            "source_domains": variant.source_domains,
            "source_docs_dir": str(PROJECT_ROOT / "source_docs" / proj_safe),
            "memory_dir": str(PROJECT_ROOT / "memory" / "projects" / proj_safe),
            "codegraph_db_path": str(
                PROJECT_ROOT / "memory" / "codegraph" / f"codegraph_{proj_safe}.db"
            ),
            "_project_key": variant.compat_project_key,
            "_variant_id": variant.variant_id,
        }
        # Flatten DBC sets into a list
        for dbc_set in variant.dbc_sets:
            proj["dbc_files"].extend(dbc_set.files)
    except (ValueError, ImportError):
        # Fallback to legacy project system
        legacy_key = resolve_variant_id(cfg, project_key) if project_key else None
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

    _config_cache[effective_key] = cfg
    return cfg


def get_router(config: dict | None = None):
    global _router_cache
    if _router_cache is not None:
        return _router_cache
    from ai.model_router import ModelRouter
    if config is None:
        config = load_config()
    _router_cache = ModelRouter(config)
    return _router_cache


def main():
    parser = argparse.ArgumentParser(
        description="Corner Radar AI Analysis Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python cli.py cases/FCTA001 -p "FCTA没有触发" -e "应该触发"
  python cli.py cases/FCTA001 -q "FCTB触发时AEBIB是否激活"
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
    id_group.add_argument("-P", "--project", default=None,
        help="[LEGACY] Project key from config.yaml (default: uses default_project). "
             "Prefer --variant instead.")

    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--query", "-q", help="Data query (natural language question)")
    mode_group.add_argument("--problem", "-p", help="Problem description (diagnosis mode)")

    parser.add_argument("--expected", "-e", help="Expected behavior (diagnosis mode)")
    parser.add_argument("--dream", action="store_true", help="Force memory consolidation")
    parser.add_argument(
        "--learn-constants",
        action="store_true",
        help="Re-learn the global numeric constants table (paraDefine.h / dotCalibDefine.h / "
             "adasFunc.c). Fast (1 AI call) and skipped automatically if source is unchanged.",
    )
    parser.add_argument(
        "--codegraph-stats",
        action="store_true",
        help="Show CodeGraph statistics (debug only).",
    )
    args = parser.parse_args()

    # ── Load config early (needed by all sub-commands) ──────────────
    config = load_config(
        project_key=args.project,
        variant_id=args.variant,
        package_profile_id=args.package_profile,
    )

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

    # ── Learn-constants only mode ───────────────────────────────────────
    if args.learn_constants:
        _run_learn_constants(config)
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
        console.print("  [cyan]python cli.py --dream[/cyan]  (memory consolidation)")
        console.print("  [cyan]python cli.py --learn-constants[/cyan]  (re-learn numeric constants table)")
        return

    # ── Validate case_dir ───────────────────────────────────────────────
    case_dir = Path(args.case_dir)
    if not case_dir.is_absolute():
        case_dir = PROJECT_ROOT / case_dir

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

    # ── Auto-dream (only when case_dir is present, not forced) ──────────
    if not args.dream:
        _run_dream(force=False, config=config)

    # ── Determine mode ──────────────────────────────────────────────────
    mode = None
    if args.query:
        mode = "query"
    elif args.problem:
        mode = "diagnose"

    if mode is None:
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
    if mode == "query":
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
    from config import resolve_variant_id, get_variant

    store = SnapshotStore(project_root / "memory" / "snapshots")

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

def _run_dream(force: bool = False, config: dict | None = None):
    from memory.memory_system import MemorySystem
    from memory.auto_dream import AutoDream

    if config is None:
        config = load_config()
    proj = config.get("project", {})
    memory_root = Path(proj.get("memory_dir", PROJECT_ROOT / "memory"))

    memory = MemorySystem(PROJECT_ROOT, memory_dir=memory_root)
    dreamer = AutoDream(memory, get_router(config), PROJECT_ROOT, config=config)

    if force:
        console.print(Panel(
            "[bold]Forced Dream Cycle[/bold]",
            border_style="magenta",
        ))

    result = dreamer.try_dream(
        on_status=lambda s, d: console.print(f"  [dim magenta][dream] {d}[/dim magenta]"),
        force=force,
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
    main()
