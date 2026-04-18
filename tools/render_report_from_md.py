# -*- coding: utf-8 -*-
"""Utility: re-render ``report.html`` from an existing ``report.md``.

This is primarily a smoke-test / preview helper for the visualizer. It
strips the machine-generated front-matter (meta table + horizontal rule)
from ``report.md`` and feeds the remaining expert prose back into
``visualizer.build_report`` together with a minimal stub ``FrameStore``
so the new layout can be generated without re-running the full AI
pipeline.

Typical use::

    python tools/render_report_from_md.py cases/FCATB001 diagnose
    python tools/render_report_from_md.py cases/FCATB_TUNE_TEST verify

The stub store returns empty lists, so only the charts that require
data (ego speed / output signals / state) get skipped — the layout,
markdown rendering, windows strip and fallback messaging can all be
eye-balled from the resulting HTML.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai.visualizer import build_report


@dataclass
class _StubWindow:
    t_start: float
    t_end: float
    duration: float
    event_types: list[str]


class _StubStore:
    """Minimal FrameStore-compatible object. All queries return []."""
    def query_bag_by_topic(self, _topic: str):
        return []
    def get_signal_inventory(self):
        return []
    def query_signal_timeline(self, _can_id, _signal):
        return []


def _strip_front_matter(md: str) -> tuple[str, dict, list[_StubWindow]]:
    """Extract (prose, meta_dict, windows) from the machine-generated
    ``report.md`` front matter.

    The front matter looks like::

        # 角雷达问题诊断报告

        | 项目 | 内容 |
        | ... |
        | 测试窗口1 | 1775970397.0s~1775970409.4s (12.4s) — ... |
        | ...
        ---

    We pick off the meta table, extract windows from rows whose label
    starts with "测试窗口", and return whatever is left for markdown
    rendering.
    """
    meta: dict[str, str] = {}
    windows: list[_StubWindow] = []

    lines = md.splitlines()
    i = 0
    while i < len(lines) and not lines[i].startswith("|"):
        i += 1

    # Pipe-table block ends at the first --- divider or blank-blank.
    table_end = i
    while table_end < len(lines):
        ln = lines[table_end].rstrip()
        if ln.startswith("---"):
            break
        if not ln and table_end + 1 < len(lines) and not lines[table_end + 1].startswith("|"):
            break
        table_end += 1

    win_re = re.compile(
        r"\|\s*测试窗口\d+\s*\|\s*([\d.]+)s\s*~\s*([\d.]+)s\s*\(([\d.]+)s\)(?:\s*—\s*(.+?))?\s*\|"
    )
    for raw in lines[i:table_end]:
        m = re.match(r"\|\s*([^|]+?)\s*\|\s*(.+?)\s*\|\s*$", raw)
        if m and not m.group(1).strip().startswith(":") and "---" not in m.group(1):
            key = m.group(1).strip()
            val = m.group(2).strip()
            meta[key] = val
        wm = win_re.search(raw)
        if wm:
            t0 = float(wm.group(1))
            t1 = float(wm.group(2))
            dur = float(wm.group(3))
            reasons = [x.strip() for x in (wm.group(4) or "").split("+") if x.strip()]
            windows.append(_StubWindow(t_start=t0, t_end=t1, duration=dur, event_types=reasons))

    # Everything after the first --- that follows the table is the prose.
    rest_start = table_end
    while rest_start < len(lines) and not lines[rest_start].startswith("---"):
        rest_start += 1
    rest_start += 1
    prose = "\n".join(lines[rest_start:]).strip()
    return prose, meta, windows


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("case_dir", type=Path, help="cases/<id> containing report.md")
    p.add_argument("task_type", choices=["diagnose", "tune", "verify", "query"],
                   nargs="?", default="diagnose")
    p.add_argument("--func", default="FCTB")
    args = p.parse_args()

    case_dir = args.case_dir.resolve()
    md_path = case_dir / "report.md"
    if not md_path.exists():
        print(f"[render] {md_path} not found", file=sys.stderr)
        return 1

    md_text = md_path.read_text(encoding="utf-8")
    diagnosis, meta, windows = _strip_front_matter(md_text)

    problem = meta.get("问题现象", "")
    expected = meta.get("预期结果", "")

    bag_meta = blf_meta = None
    bag_line = meta.get("BAG数据", "")
    blf_line = meta.get("BLF数据", "")
    m_bag = re.match(r"(.+?)\s*\(([\d.]+)s,\s*(\d+)条\)", bag_line)
    if m_bag:
        bag_meta = {
            "file": m_bag.group(1),
            "duration_sec": float(m_bag.group(2)),
            "message_count": int(m_bag.group(3)),
        }
    m_blf = re.match(r"(.+?)\s*\(([\d.]+)s,\s*(\d+)条\)", blf_line)
    if m_blf:
        blf_meta = {
            "file": m_blf.group(1),
            "duration_sec": float(m_blf.group(2)),
            "message_count": int(m_blf.group(3)),
        }

    out = build_report(
        case_dir=case_dir,
        func_name=args.func,
        task_type=args.task_type,
        problem=problem,
        expected=expected,
        diagnosis=diagnosis,
        store=_StubStore(),
        windows=windows,
        bag_meta=bag_meta,
        blf_meta=blf_meta,
    )
    print(f"[render] wrote {out.html_path}  charts={out.charts_built}")
    if out.warnings:
        for w in out.warnings:
            print(f"[render]   warn: {w}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
