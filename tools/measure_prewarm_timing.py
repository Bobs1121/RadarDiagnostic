# -*- coding: utf-8 -*-
"""
Measure repeated ``cli._run_prewarm`` timing for a single variant.

This is an offline harness for Phase 16.1. It keeps diagnosis out of the
picture and patches the LLM-backed learner/router so the prewarm step can
be timed without API availability.
"""
from __future__ import annotations

import argparse
import copy
import io
import json
import sys
import time
from contextlib import contextmanager
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
else:
    sys.stdout = io.TextIOWrapper(
        sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True
    )
    sys.stderr = io.TextIOWrapper(
        sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True
    )

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import get_variant, load_config, resolve_source_docs_dir, resolve_variant_id
from cli import _run_prewarm


class _OfflineRouter:
    pass


class _OfflineCodeLearner:
    def __init__(self, router, cfg, root):
        self.router = router
        self.cfg = cfg
        self.root = root

    def learn(self, status_cb=None, force_pairs=None, force_constants=False):
        return {"learned_count": 0, "skipped_count": 0, "error_count": 0}

    def ensure_overview_docs(self, funcs=None, force=False, status_cb=None):
        return {
            "generated": [],
            "skipped": list(funcs or []),
            "failed": [],
            "reason": "all_up_to_date",
        }


@contextmanager
def _offline_prewarm_mode():
    import ai.code_learner as code_learner_mod
    import cli as cli_mod

    original_router = cli_mod.get_router
    original_learner = code_learner_mod.CodeLearner
    cli_mod.get_router = lambda cfg: _OfflineRouter()
    code_learner_mod.CodeLearner = _OfflineCodeLearner
    try:
        yield
    finally:
        cli_mod.get_router = original_router
        code_learner_mod.CodeLearner = original_learner


def _safe_variant_name(variant_id: str) -> str:
    return variant_id.replace("/", "_").replace(" ", "_").lower()


def _build_runtime_config(variant_id: str) -> tuple[dict, str, Path, Path]:
    config = load_config()
    resolved_variant_id = resolve_variant_id(config, variant_id)
    _, codebase, _ = get_variant(config, resolved_variant_id)
    source_code = Path(codebase.root_path)
    source_docs_dir = resolve_source_docs_dir(
        config, PROJECT_ROOT, variant_id=resolved_variant_id
    )

    runtime_config = copy.deepcopy(config)
    runtime_config.setdefault("paths", {})
    runtime_config["paths"]["source_code"] = str(source_code)
    runtime_config["paths"]["source_docs"] = str(source_docs_dir)
    runtime_config.setdefault("identity", {})
    runtime_config["identity"]["variant_id"] = resolved_variant_id
    runtime_config["default_variant"] = resolved_variant_id
    return runtime_config, resolved_variant_id, source_code, source_docs_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--variant",
        required=True,
        help="Variant ID or legacy project key to prewarm",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=2,
        help="Number of times to call cli._run_prewarm",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Write the JSON timing report to this file",
    )
    args = parser.parse_args(argv)

    if args.runs < 1:
        parser.error("--runs must be at least 1")

    runtime_config, resolved_variant_id, source_code, source_docs_dir = (
        _build_runtime_config(args.variant)
    )
    source_docs_dir.mkdir(parents=True, exist_ok=True)

    output_path = args.output
    if output_path is None:
        output_path = PROJECT_ROOT / "reports" / (
            f"prewarm_timing_{_safe_variant_name(resolved_variant_id)}.json"
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)

    runs: list[dict] = []
    total_started = time.perf_counter()
    with _offline_prewarm_mode():
        for idx in range(1, args.runs + 1):
            marker_path = source_docs_dir / "variable_chains.meta.json"
            cache_hit_before = marker_path.exists()
            started = time.perf_counter()
            summary = _run_prewarm(config=runtime_config, force=False)
            elapsed = time.perf_counter() - started
            runs.append(
                {
                    "run_index": idx,
                    "elapsed_sec": round(elapsed, 6),
                    "cache_hit": cache_hit_before,
                    "variable_chains_meta_exists": marker_path.exists(),
                    "summary": summary,
                }
            )
            state = "cache-hit" if cache_hit_before else "cold"
            print(f"[{idx}/{args.runs}] {state} {elapsed:.3f}s")

    report = {
        "variant_id": resolved_variant_id,
        "requested_variant": args.variant,
        "runs_requested": args.runs,
        "total_elapsed_sec": round(time.perf_counter() - total_started, 6),
        "source_code_dir": str(source_code),
        "source_docs_dir": str(source_docs_dir),
        "output_path": str(output_path),
        "cache_hit_runs": sum(1 for run in runs if run["cache_hit"]),
        "runs": runs,
    }
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[report] wrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
