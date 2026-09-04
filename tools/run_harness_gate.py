# -*- coding: utf-8 -*-
"""Local regression gate for radarAnalyze Harness results."""
from __future__ import annotations

import argparse
import io
import json
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

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

from harness.harness_runner import HarnessRunner

KNOWN_EDGE_CASES = {"sc6hrcta001"}


def _split_cases(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    return [part.strip() for part in raw.split(",") if part.strip()]


def run_gate(
    *,
    cases: list[str] | None = None,
    output: Path | None = None,
    allow_known_edge: bool = False,
    runner: HarnessRunner | None = None,
) -> tuple[int, dict]:
    """Run harness regression and return ``(exit_code, gate_report)``."""
    runner = runner or HarnessRunner()
    results = runner.run_all_cases(cases)
    aggregate = runner.generate_aggregate_report(results)

    failed = [r.case_id for r in results if not r.passed]
    allowed = sorted(set(failed) & KNOWN_EDGE_CASES) if allow_known_edge else []
    blocking = [case_id for case_id in failed if case_id not in allowed]
    exit_code = 0 if not blocking else 1

    gate_report = {
        "report_type": "harness_gate",
        "generated_at": datetime.now().isoformat(),
        "exit_code": exit_code,
        "total_cases": len(results),
        "passed": sum(1 for r in results if r.passed),
        "failed": len(failed),
        "failed_cases": failed,
        "allowed_edge_cases": allowed,
        "blocking_failures": blocking,
        "aggregate": aggregate,
    }

    if output is None:
        output = PROJECT_ROOT / "reports" / (
            f"harness_gate_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(gate_report, ensure_ascii=False, indent=2), encoding="utf-8")
    gate_report["output_path"] = str(output)

    return exit_code, gate_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cases",
        default=None,
        help="Comma-separated case IDs. Defaults to all golden-truth cases.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Path for gate JSON report. Defaults to reports/harness_gate_<timestamp>.json.",
    )
    parser.add_argument(
        "--allow-known-edge",
        action="store_true",
        help="Allow known edge-case failures such as sc6hrcta001.",
    )
    parser.add_argument("--json", action="store_true", help="Print full gate report JSON.")
    args = parser.parse_args(argv)

    exit_code, report = run_gate(
        cases=_split_cases(args.cases),
        output=args.output,
        allow_known_edge=args.allow_known_edge,
    )

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(
            f"Harness gate: {report['passed']}/{report['total_cases']} passed, "
            f"blocking={len(report['blocking_failures'])}, output={report['output_path']}"
        )
        if report["allowed_edge_cases"]:
            print(f"Allowed edge cases: {', '.join(report['allowed_edge_cases'])}")
        if report["blocking_failures"]:
            print(f"Blocking failures: {', '.join(report['blocking_failures'])}")

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
