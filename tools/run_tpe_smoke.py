# -*- coding: utf-8 -*-
"""
Standalone TPE smoke-runner.

Purpose
-------
Validate the Temporal Pattern Engine on *real* case data (BAG + BLF)
without hitting the LLM router, the expert panel or the memory system.

Typical use:

    python -m tools.run_tpe_smoke cases/FCATB001 --func FCTB

Output is a plain-text TPE block identical to the one injected into the
expert-panel prompt by :meth:`Orchestrator._run_tpe`. If this block
clearly labels the FCATB001 root cause as a *triggered HoldRelease*,
we have empirical confidence that the full pipeline will follow suit.

Exits with:
  * 0 → at least one pattern triggered (in line with the case hypothesis)
  * 1 → no pattern triggered (expected for a healthy recording)
  * 2 → loader / extraction error
"""
from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
else:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                   errors="replace", line_buffering=True)
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8",
                                   errors="replace", line_buffering=True)

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _load_config() -> dict:
    import yaml
    with open(PROJECT_ROOT / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _status(step: str, detail: str = "") -> None:
    print(f"[{step}] {detail}")


def _gather_state_transitions(store, func_name: str) -> list[dict]:
    """Minimal replacement for FrameAnalyzer — only what TPE needs."""
    from ai.utils import get_func_fields

    fmap = get_func_fields(func_name)
    state_fields: list[str] = []
    for k in ("state", "enable"):
        if fmap.get(k):
            state_fields.append(fmap[k])
    state_fields.extend(fmap.get("warnings", []))

    ego_topics = fmap.get("ego_topics", [])
    transitions: list[dict] = []
    for topic in ego_topics:
        frames = store.query_bag_by_topic(topic)
        if not frames:
            continue
        prev: dict = {}
        for f in frames:
            fields = f.get("fields", {})
            ts = f.get("timestamp_sec", 0)
            for sk in state_fields:
                cur = fields.get(sk)
                if cur is None:
                    continue
                prior = prev.get(sk)
                if prior is not None and cur != prior:
                    transitions.append({
                        "t": round(ts, 3),
                        "field": sk,
                        "from": prior,
                        "to": cur,
                    })
                prev[sk] = cur
    return transitions


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case_dir", type=Path,
                        help="Case directory containing *.bag / *.blf")
    parser.add_argument("--func", default=None,
                        help="ADAS function filter (FCTB/FCTA/BSD/...)")
    parser.add_argument("--time-window", nargs=2, type=float, default=None,
                        metavar=("T_START", "T_END"),
                        help="Optional (t_start, t_end) seconds clip")
    parser.add_argument("--output", "-o", type=Path, default=None,
                        help="Write UTF-8 report to this file (in addition to stdout)")
    args = parser.parse_args()

    case_dir: Path = args.case_dir.resolve()
    if not case_dir.is_dir():
        _status("error", f"{case_dir} is not a directory")
        return 2

    bags = list(case_dir.glob("*.bag"))
    blfs = list(case_dir.glob("*.blf"))
    if not bags and not blfs:
        _status("error", f"no BAG/BLF files in {case_dir}")
        _status("hint", "Place recording files in the case directory and retry.")
        return 2

    config = _load_config()
    _status("load", f"Parsing {len(bags)} BAG(s), {len(blfs)} BLF(s)...")
    from parsers.case_loader import load_case_data
    try:
        result = load_case_data(case_dir, config, PROJECT_ROOT, on_status=_status)
    except Exception as exc:
        _status("error", f"load_case_data failed: {exc}")
        import traceback; traceback.print_exc()
        return 2

    store = result.store

    if args.func:
        func_name = args.func.upper()
    else:
        from ai.utils import FUNC_FIELD_MAP
        guess = case_dir.name[:4].upper()
        if guess in FUNC_FIELD_MAP:
            func_name = guess
        else:
            _status("error",
                    f"Cannot infer ADAS function from case dir '{case_dir.name}'. "
                    "Pass --func explicitly (e.g. --func BSD / FCTB / RCTB / ...).")
            return 2
    _status("tpe", f"Running TPE for func={func_name}")

    try:
        transitions = _gather_state_transitions(store, func_name)
    except Exception as exc:
        _status("warn", f"state-transition gathering failed: {exc}")
        transitions = []

    from ai.signal_mapper import (
        extract_signal_mapping, trace_variable_chains, load_variable_chains,
    )
    source_root = Path(config["paths"]["source_code"])
    from config import resolve_source_docs_dir
    docs_dir = resolve_source_docs_dir({}, PROJECT_ROOT)
    try:
        sig_mapping = extract_signal_mapping(source_root, docs_dir)
    except Exception as exc:
        _status("warn", f"signal mapping failed: {exc}")
        sig_mapping = {}
    try:
        chains = load_variable_chains(docs_dir)
        if not chains.get("struct_aliases"):
            chains = trace_variable_chains(source_root, docs_dir)
    except Exception:
        chains = {}

    from ai.tpe import TemporalPatternEngine
    engine = TemporalPatternEngine(
        source_root=source_root, cache_dir=docs_dir,
        signal_mapping=sig_mapping, variable_chains=chains,
    )
    tpe_result = engine.run(
        store=store, func_name=func_name,
        state_transitions=transitions,
        time_window=tuple(args.time_window) if args.time_window else None,
    )

    block = tpe_result.to_expert_block()
    separator = "=" * 70
    rendered = f"\n{separator}\n{block}\n{separator}\n"
    print(rendered)

    summary_line = (
        f"patterns={len(tpe_result.patterns)} "
        f"triggered={tpe_result.triggered_count} "
        f"unresolved={len(tpe_result.unresolved_variables)} "
        f"missing_can={len(tpe_result.missing_can_signals)}"
    )
    _status("summary", summary_line)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            rendered + f"\n[summary] {summary_line}\n",
            encoding="utf-8",
        )
        _status("output", f"UTF-8 report written to {args.output}")

    store.close()
    return 0 if tpe_result.has_triggers else 1


if __name__ == "__main__":
    raise SystemExit(main())
