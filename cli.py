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

_config_cache: dict | None = None
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


def load_config() -> dict:
    global _config_cache
    if _config_cache is not None:
        return _config_cache
    config_path = PROJECT_ROOT / "config.yaml"
    if not config_path.exists():
        console.print("[red]config.yaml not found![/red]")
        sys.exit(1)
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg = _resolve_env(cfg)
    cfg["paths"]["project_root"] = str(PROJECT_ROOT)
    cfg["paths"]["source_docs"] = str(PROJECT_ROOT / "source_docs")
    _config_cache = cfg
    return cfg


def get_router():
    global _router_cache
    if _router_cache is not None:
        return _router_cache
    from ai.model_router import ModelRouter
    _router_cache = ModelRouter(load_config())
    return _router_cache


def main():
    parser = argparse.ArgumentParser(
        description="Corner Radar AI Analysis Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python cli.py cases/FCTA001 -p "FCTA没有触发" -e "应该触发"
  python cli.py cases/FCTA001 -q "FCTB触发时AEBIB是否激活"
  python cli.py --dream
        """,
    )
    parser.add_argument("case_dir", nargs="?", help="Case folder containing .bag/.blf files")

    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--query", "-q", help="Data query (natural language question)")
    mode_group.add_argument("--problem", "-p", help="Problem description (diagnosis mode)")

    parser.add_argument("--expected", "-e", help="Expected behavior (diagnosis mode)")
    parser.add_argument("--dream", action="store_true", help="Force memory consolidation")
    args = parser.parse_args()

    if args.query and args.expected:
        parser.error("-e/--expected is only used with -p/--problem (diagnosis mode)")

    # ── Dream-only mode ─────────────────────────────────────────────────
    if args.dream:
        _run_dream(force=True)
        if not args.case_dir:
            return

    # ── No case_dir → show usage ────────────────────────────────────────
    if not args.case_dir:
        console.print("[yellow]Usage:[/yellow]")
        console.print("  [cyan]python cli.py <case_dir> -q \"your question\"[/cyan]  (data query)")
        console.print("  [cyan]python cli.py <case_dir> -p \"problem\" -e \"expected\"[/cyan]  (diagnosis)")
        console.print("  [cyan]python cli.py --dream[/cyan]  (memory consolidation)")
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

    console.print(Panel(
        f"[bold]{case_dir.name}[/bold]\n"
        f"BAG: {len(bag_files)} file(s)  {', '.join(f.name for f in bag_files) or '-'}\n"
        f"BLF: {len(blf_files)} file(s)  {', '.join(f.name for f in blf_files) or '-'}",
        title="Corner Radar Analysis",
        border_style="blue",
    ))

    if not bag_files and not blf_files:
        console.print("[red]No .bag or .blf files in the case folder![/red]")
        sys.exit(1)

    # ── Auto-dream (only when case_dir is present, not forced) ──────────
    if not args.dream:
        _run_dream(force=False)

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

    # ── Route ───────────────────────────────────────────────────────────
    if mode == "query":
        _run_query(case_dir, args.query)
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
        _run_diagnosis(case_dir, problem, expected)


# ── Dream ───────────────────────────────────────────────────────────────

def _run_dream(force: bool = False):
    from memory.memory_system import MemorySystem
    from memory.auto_dream import AutoDream

    memory = MemorySystem(PROJECT_ROOT)
    dreamer = AutoDream(memory, get_router(), PROJECT_ROOT)

    if force:
        console.print(Panel("[bold]Forced Dream Cycle[/bold]", border_style="magenta"))

    result = dreamer.try_dream(
        on_status=lambda s, d: console.print(f"  [dim magenta][dream] {d}[/dim magenta]"),
        force=force,
    )
    if result and "error" not in result:
        summary = result.get("summary", "done")
        conflicts = result.get("conflicts_found", [])
        console.print(f"  [magenta]Memory consolidated: {summary}[/magenta]")
        if conflicts:
            console.print(f"  [yellow]Conflicts resolved: {len(conflicts)}[/yellow]")


# ── Query Mode ──────────────────────────────────────────────────────────

def _run_query(case_dir: Path, question: str):
    """Lightweight data query pipeline."""
    from ai.data_query_engine import DataQueryEngine

    config = load_config()
    engine = DataQueryEngine(get_router(), config, PROJECT_ROOT)

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

def _run_diagnosis(case_dir: Path, problem: str, expected: str):
    """Full diagnosis pipeline."""
    from ai.orchestrator import Orchestrator

    config = load_config()
    orchestrator = Orchestrator(config, PROJECT_ROOT)

    steps_display = {
        "init": "Checking prerequisites",
        "source_docs": "Generating source docs",
        "understand": "Understanding problem",
        "parse": "Parsing data",
        "detect_window": "Detecting test windows",
        "analyze": "Analyzing frames",
        "conditions": "Extracting conditions",
        "tpe": "Temporal Pattern Engine",
        "suppression": "Checking suppression signals",
        "output_signals": "Analyzing output signals",
        "diagnose": "Expert panel diagnosis",
        "expert_panel": "Expert panel",
        "report": "Generating report",
        "done": "Complete",
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
