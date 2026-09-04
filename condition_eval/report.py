# -*- coding: utf-8 -*-
"""
ConditionCoverageReport — 覆盖率报告的纯文本与 Markdown 渲染。

提供两种输出格式：
- ``render_txt()`` — 纯文本，适合终端和日志文件
- ``render_md()`` — Markdown，适合 Wiki 和报告归档
"""
from __future__ import annotations

from .models import ConditionReport


class ConditionCoverageReport:
    """覆盖率报告渲染器。

    Attributes:
        report: 由 ConditionEvaluator.generate_coverage_report() 返回的报告。
    """

    def __init__(self, report: ConditionReport) -> None:
        self.report = report

    # ── 纯文本 ──────────────────────────────────────────────────────────

    def render_txt(self) -> str:
        """生成纯文本覆盖率报告。"""
        lines: list[str] = []
        r = self.report

        lines.append("=" * 60)
        lines.append("  BSD Condition Coverage Report")
        lines.append("=" * 60)
        lines.append("")

        case_line = f"Case: {r.case_name or 'default'}"
        if r.duration_sec > 0:
            case_line += f" ({r.duration_sec:.1f}s"
            if r.total_frames > 0:
                case_line += f", {r.total_frames} frames"
            case_line += ")"
        lines.append(case_line)
        lines.append(f"Total conditions: {r.total_conditions}")

        sc = r.signal_coverage
        if sc:
            lines.append(f"Unique MF4 signals needed: {sc.get('referenced_count', 0)}")
            lines.append(f"Signals found in MF4: {sc.get('found_count', 0)}")
            lines.append(f"Signals missing: {sc.get('missing_count', 0)}")

        lines.append("")

        # 条件命中表
        lines.append("Condition Hits:")
        lines.append("-" * 60)

        for cs in r.condition_stats:
            name = cs["name"]
            step = cs["step"]
            hit_rate = cs["hit_rate"]
            total = cs["total"]
            hit = cs["hit"]
            miss = cs["miss"]
            missing_signal = cs["missing_signal"]

            if hit_rate == 100.0:
                bar = "HIT "
                pct_str = f"{hit_rate:.0f}%"
                extra = ""
            elif hit_rate == 0.0 and total > 0:
                bar = "MISS"
                pct_str = f"{hit_rate:.0f}%"
                extra = ""
            elif hit_rate > 0 and total > 0:
                bar = "HIT "
                pct_str = f"{hit_rate:.0f}%"
                extra = f" [{miss} frames failed]"
            else:
                bar = "---"
                pct_str = "N/A"
                extra = ""

            if missing_signal > 0:
                bar = "MISS_SIG"
                pct_str = f"({missing_signal}/{total} missing signals)"
                extra = ""

            # 步骤编号右对齐
            step_str = f"Step {step}"
            name_short = name[:30].ljust(30)
            lines.append(
                f"  {step_str} ({name_short}): {bar} {pct_str} ({hit}/{total}){extra}"
            )

        lines.append("")

        # 缺失信号
        missing_sigs = sc.get("missing", []) if sc else []
        if missing_sigs:
            lines.append("Missing Signals:")
            for entry in getattr(self.report, "_missing_signals_detail", []):
                sig = entry["signal"]
                by = entry["referenced_by"]
                lines.append(f"  - {sig} (referenced in {by[0] if by else 'unknown condition'})")

        lines.append("")

        # 总结
        fc = getattr(self.report, "_fully_covered", None)
        pc = getattr(self.report, "_partially_covered", None)
        fm = getattr(self.report, "_fully_missing_count", None)
        if fc is not None:
            lines.append("Summary:")
            lines.append(f"  Conditions fully covered (all signals present): {fc}/{r.total_conditions}")
            lines.append(f"  Conditions partially covered (1-2 signals missing): {pc}/{r.total_conditions}")
            lines.append(f"  Conditions fully missing (3+ signals missing): {fm}/{r.total_conditions}")

        always_zero = getattr(self.report, "_always_zero", [])
        if always_zero:
            lines.append(f"  Conditions that NEVER fired: {always_zero}")

        always_100 = getattr(self.report, "_always_100", [])
        if always_100:
            lines.append(f"  Conditions that ALWAYS fired: {always_100}")

        lines.append("")
        lines.append("=" * 60)

        return "\n".join(lines)

    # ── Markdown ────────────────────────────────────────────────────────

    def render_md(self) -> str:
        """生成 Markdown 覆盖率报告。"""
        lines: list[str] = []
        r = self.report

        lines.append("# BSD Condition Coverage Report")
        lines.append("")

        case_line = f"**Case:** {r.case_name or 'default'}"
        if r.duration_sec > 0:
            case_line += f" | Duration: {r.duration_sec:.1f}s"
            if r.total_frames > 0:
                case_line += f" | Frames: {r.total_frames}"
        lines.append(case_line)
        lines.append("")
        lines.append(f"**Total conditions:** {r.total_conditions}")

        sc = r.signal_coverage
        if sc:
            lines.append(f"**Unique MF4 signals needed:** {sc.get('referenced_count', 0)}")
            lines.append(f"**Signals found in MF4:** {sc.get('found_count', 0)}")
            lines.append(f"**Signals missing:** {sc.get('missing_count', 0)}")

        lines.append("")

        # 条件命中表
        lines.append("## Condition Hits")
        lines.append("")
        lines.append("| Step | Condition | Hit Rate | Hit / Total | Missing Signals | Failure Reasons |")
        lines.append("|------|-----------|----------|-------------|-----------------|-----------------|")

        for cs in r.condition_stats:
            name = cs["name"]
            step = cs["step"]
            hit_rate = cs["hit_rate"]
            total = cs["total"]
            hit = cs["hit"]
            miss = cs["miss"]
            missing_signal = cs["missing_signal"]

            if hit_rate == 100.0:
                hit_label = f"**{hit_rate:.0f}% (HIT)**"
            elif hit_rate == 0.0 and total > 0:
                hit_label = f"**{hit_rate:.0f}% (MISS)**"
            elif hit_rate > 0 and total > 0:
                hit_label = f"{hit_rate:.0f}%"
            elif total == 0:
                hit_label = "N/A"
            else:
                hit_label = f"{hit_rate:.0f}%"

            missing_str = str(missing_signal) if missing_signal > 0 else ""

            reasons_str = ""
            fr = cs.get("failure_reasons", {})
            if fr:
                reason_items = []
                for reason, count in list(fr.items())[:3]:
                    msg = reason.split(":", 1)[-1].strip() if ":" in reason else reason
                    if msg and msg != "formula failed":
                        reason_items.append(f"{msg} ({count})")
                reasons_str = "; ".join(reason_items)

            lines.append(
                f"| {step} | {name} | {hit_label} | {hit}/{total} "
                f"| {missing_str} | {reasons_str} |"
            )

        lines.append("")

        # 缺失信号
        missing_sigs = sc.get("missing", []) if sc else []
        _detail = getattr(self.report, "_missing_signals_detail", [])
        if missing_sigs or _detail:
            lines.append("## Missing Signals")
            lines.append("")
            for entry in _detail:
                sig = entry["signal"]
                by = entry["referenced_by"]
                ref_parts = []
                for b in by:
                    ref_parts.append(f"`{b}`")
                lines.append(f"- `{sig}` — referenced in {', '.join(ref_parts)}")
            lines.append("")

        # 总结
        fc = getattr(self.report, "_fully_covered", None)
        pc = getattr(self.report, "_partially_covered", None)
        fm = getattr(self.report, "_fully_missing_count", None)
        if fc is not None:
            lines.append("## Summary")
            lines.append("")
            lines.append(f"- Conditions fully covered (all signals present): **{fc}/{r.total_conditions}**")
            lines.append(f"- Conditions partially covered (1-2 signals missing): **{pc}/{r.total_conditions}**")
            lines.append(f"- Conditions fully missing (3+ signals missing): **{fm}/{r.total_conditions}**")

        always_zero = getattr(self.report, "_always_zero", [])
        if always_zero:
            lines.append(f"- **Conditions that NEVER fired** (0% hit rate):")
            for az in always_zero:
                lines.append(f"  - `{az}`")

        always_100 = getattr(self.report, "_always_100", [])
        if always_100:
            lines.append(f"- **Conditions that ALWAYS fired** (100% hit rate):")
            for a100 in always_100:
                lines.append(f"  - `{a100}`")

        lines.append("")
        return "\n".join(lines)

    # ── 输出文件 ────────────────────────────────────────────────────────

    def write_txt(self, path: str) -> str:
        """将纯文本报告写入文件。

        Args:
            path: 输出文件路径。

        Returns:
            写入的文件路径（绝对路径）。
        """
        import os
        content = self.render_txt()
        abs_path = os.path.abspath(path)
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(content)
        return abs_path

    def write_md(self, path: str) -> str:
        """将 Markdown 报告写入文件。

        Args:
            path: 输出文件路径。

        Returns:
            写入的文件路径（绝对路径）。
        """
        import os
        content = self.render_md()
        abs_path = os.path.abspath(path)
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(content)
        return abs_path

    def write_reports(self, case_dir: str, case_name: str = "") -> tuple[str, str]:
        """同时输出 .txt 和 .md 报告到指定目录。

        Args:
            case_dir: 用例输出目录。
            case_name: 用例名称（用作文件名前缀）。

        Returns:
            (txt_path, md_path) 两个文件的绝对路径。
        """
        import os
        prefix = case_name or "condition_coverage"

        txt_path = os.path.join(case_dir, f"{prefix}.txt")
        md_path = os.path.join(case_dir, f"{prefix}.md")

        os.makedirs(case_dir, exist_ok=True)
        self.write_txt(txt_path)
        self.write_md(md_path)

        return os.path.abspath(txt_path), os.path.abspath(md_path)
