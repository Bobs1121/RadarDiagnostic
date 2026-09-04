# -*- coding: utf-8 -*-
"""SignalExtractModule (V4 P3) — 信号抽取 + 绘图。

用户核心诉求"帮我抽取某某信号"：模糊匹配（精确/别名/语义）+ 跨源对齐，
输出 JSON/CSV + plot HTML。确定性，无 LLM。

独立运行::

    python cli.py signal-extract "车速" --case-dir cases/xxx --plot
    python cli.py signal-extract "speed" --case-dir cases/xxx --no-plot
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from .base import BaseModule, ModuleResult

log = logging.getLogger(__name__)


class SignalExtractModule(BaseModule):
    name = "signal-extract"
    description = "信号抽取 + 绘图：模糊匹配 CAN / 雷达内部信号并输出时间线/曲线"

    def __init__(self, *, store: Any = None, case_dir: str = ""):
        self._store = store
        self.case_dir = Path(case_dir) if case_dir else None

    # ── 主入口 ────────────────────────────────────────────────────

    def run(self, *, query: str = "", case_dir: str = "", plot: bool = True,
            write_csv: bool = True, **kwargs: Any) -> ModuleResult:
        """抽取信号；``no_plot``（CLI flag）会关闭绘图。"""
        # CLI 传入的 --no-plot 在此消费（与 plot 默认值取反）
        if kwargs.get("no_plot"):
            plot = False
        if not query:
            return ModuleResult.fail("query 不能为空 (signal-extract)", module=self.name)

        store = self._store
        if store is None:
            if not case_dir and self.case_dir:
                case_dir = str(self.case_dir)
            if not case_dir:
                return ModuleResult.fail(
                    "需要 case_dir 或注入的 store", module=self.name,
                )
            store = self._load_store(case_dir)
            if store is None:
                return ModuleResult.fail(
                    f"加载案例失败: {case_dir}", module=self.name,
                )
            self._store = store

        from engines.signal_catalog import SignalCatalog
        from engines.signal_extract import SignalExtractor

        catalog = SignalCatalog(store).build()
        extractor = SignalExtractor(store, catalog=catalog)
        output_dir = self._resolve_output_dir(case_dir)
        result = extractor.extract(query, output_dir=output_dir, write_csv=write_csv)

        plot_path = ""
        if plot and result.signals:
            plot_path = self._plot(result, output_dir)

        matched = [s for s in result.signals if s.matched]
        data = result.to_dict()
        if plot_path:
            data["plot_path"] = plot_path
        artifacts = [p for p in (result.csv_path, plot_path) if p]
        return ModuleResult.success(
            message=(
                f"signal-extract: matched {len(matched)}/{len(result.signals)}"
                + (f", plot: {plot_path}" if plot_path else "")
            ),
            module=self.name,
            artifacts=artifacts,
            **data,
        )

    # ── 内部实现 ──────────────────────────────────────────────────

    def _load_store(self, case_dir: str) -> Any:
        try:
            from parsers.case_loader import load_case_data
            from config import load_config
            cfg = load_config()
            project_root = Path(case_dir).resolve().parents[0]
            res = load_case_data(Path(case_dir), cfg, project_root)
            return res.store if res else None
        except Exception as exc:  # noqa: BLE001
            log.warning("signal-extract: load_case_data failed: %s", exc)
            return None

    def _resolve_output_dir(self, case_dir: str) -> Path:
        base = Path(case_dir) if case_dir else (self.case_dir or Path("."))
        return base

    def _plot(self, result, output_dir: Path) -> str:
        try:
            import plotly.graph_objects as go
            safe = re.sub(r"[^A-Za-z0-9_]", "_", result.query)[:60] or "signal"
            path = Path(output_dir) / f"signal_extract_{safe}.html"
            fig = go.Figure()
            for s in result.signals:
                if not s.matched or not s.samples:
                    continue
                ts = [sm["t"] for sm in s.samples]
                vs = [sm["value"] for sm in s.samples]
                fig.add_trace(go.Scatter(x=ts, y=vs, mode="lines",
                                         name=f"{s.name} ({s.source})"))
            fig.update_layout(title=f"signal: {result.query}", xaxis_title="t (s)")
            fig.write_html(str(path), include_plotlyjs="cdn")
            return str(path)
        except Exception as exc:  # noqa: BLE001
            log.warning("signal-extract: plot failed: %s", exc)
            return ""

    # ── CLI ───────────────────────────────────────────────────────

    @classmethod
    def register_cli(cls, subparsers: Any) -> Any:
        p = super().register_cli(subparsers)
        p.add_argument("--query", default="", help="信号名或自然语言查询，如'车速'")
        p.add_argument("--case-dir", default="", help="数据目录（bag/blf）")
        p.add_argument("--no-plot", action="store_true", help="不生成曲线图")
        p.set_defaults(_module_cls=cls)
        return p

    @classmethod
    def from_cli_args(cls, args: Any) -> "SignalExtractModule":
        return cls(case_dir=getattr(args, "case_dir", ""))


__all__ = ["SignalExtractModule"]