# -*- coding: utf-8 -*-
"""
Interactive HTML report for radar diagnosis results.

The visualizer turns pipeline artefacts (FrameStore, test windows, TPE
evidence, parameter sensitivity, expert verdict) into a single standalone
``report.html`` file.

Design goals:

* **Data-first**: the user must be able to re-derive the AI's conclusion
  from the charts even if the prose is wrong.
* **Offline**: plotly.js is inlined — the file opens without internet.
* **Typographic / clean**: professional blue-slate palette, cards,
  sticky TOC, markdown-rendered expert prose (tables, code blocks,
  bullet lists render *as* tables / code / lists, not as monospace text).
* **Generic**: no FCTB/front-corner special cases leak into the UI —
  the same template serves BSD / RCTB / LCA / DOW / RCW / RCTA / FCTA / FCTB
  and all four task types (diagnose / tune / verify / query).

Every chart builder returns a :class:`ChartSection` so the shell can
render uniform chart cards with anchor / title / caption.
"""

from __future__ import annotations

import html
import math
import re
import datetime as _dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

try:
    import plotly.graph_objects as go
    _PLOTLY_OK = True
except Exception:
    go = None
    _PLOTLY_OK = False

try:
    import markdown as _md
    _MARKDOWN_OK = True
except Exception:
    _md = None
    _MARKDOWN_OK = False

from .utils import get_func_fields
from engines.signal_mapper import get_output_signals_for_function


# ── Shared palette for plotly (keeps charts coherent) ───────────────────────

_PALETTE = [
    "#2563eb",  # primary blue
    "#0ea5e9",  # sky
    "#14b8a6",  # teal
    "#8b5cf6",  # violet
    "#f59e0b",  # amber
    "#ef4444",  # red
    "#10b981",  # emerald
    "#ec4899",  # pink
]


def _plotly_layout_defaults() -> dict:
    """Shared Plotly layout dict so every chart looks coherent."""
    return dict(
        template="plotly_white",
        font=dict(
            family=(
                '"Inter", "Segoe UI", -apple-system, BlinkMacSystemFont, '
                '"PingFang SC", "Microsoft YaHei", sans-serif'
            ),
            size=12,
            color="#1e293b",
        ),
        paper_bgcolor="white",
        plot_bgcolor="#f8fafc",
        colorway=_PALETTE,
        margin=dict(l=48, r=24, t=56, b=48),
        legend=dict(
            orientation="h", yanchor="bottom", y=1.02, x=0,
            font=dict(size=11),
            bgcolor="rgba(255,255,255,0.8)",
            bordercolor="#e2e8f0", borderwidth=1,
        ),
        hoverlabel=dict(
            font=dict(
                family=(
                    '"SF Mono", "Cascadia Mono", "Consolas", '
                    '"Microsoft YaHei Mono", monospace'
                ),
                size=12,
            ),
            bgcolor="white",
            bordercolor="#2563eb",
        ),
    )


# ── Public entry point ──────────────────────────────────────────────────────


@dataclass
class ChartSection:
    """One chart card. Rendered uniformly in the right-hand column."""
    anchor: str
    title: str
    caption: str = ""
    body_html: str = ""      # plotly div or arbitrary HTML body
    tag: str = ""            # small label in the corner (e.g. "基础信号")
    icon: str = "📊"         # emoji / text icon shown in TOC

    @property
    def empty(self) -> bool:
        return not self.body_html


@dataclass
class VisualizerResult:
    """Small summary returned to the orchestrator."""
    html_path: str
    charts_built: int
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "html_path": self.html_path,
            "charts_built": self.charts_built,
            "warnings": list(self.warnings),
        }


def build_report(
    *,
    case_dir: Path,
    func_name: str,
    task_type: str,
    problem: str,
    expected: str,
    diagnosis: str,
    store,
    windows: list,
    tpe_result=None,
    param_report=None,
    whatif_entries: Optional[list] = None,
    bag_meta: Optional[dict] = None,
    blf_meta: Optional[dict] = None,
) -> VisualizerResult:
    """Render all charts and write a single ``report.html`` next to ``report.md``.

    Caller is expected to pass the pipeline's live objects; we don't do
    any parsing of our own. This keeps the visualizer cheap (no duplicate
    reads) and honest (you see exactly what the pipeline saw).
    """
    case_dir = Path(case_dir)
    html_path = case_dir / "report.html"
    warnings: list[str] = []

    if not _PLOTLY_OK:
        _write_fallback_html(
            html_path, func_name, task_type, problem, expected, diagnosis,
            reason="plotly is not installed",
        )
        return VisualizerResult(
            html_path=str(html_path), charts_built=0,
            warnings=["plotly unavailable — fallback HTML emitted"],
        )

    sections: list[ChartSection] = []

    ego = _chart_ego_speed(store, func_name, windows)
    if ego and not ego.empty:
        sections.append(ego)
    else:
        warnings.append("ego speed chart skipped: no ego_info frames")

    out = _chart_output_signals(store, func_name, windows)
    if out and not out.empty:
        sections.append(out)
    else:
        warnings.append("output signal chart skipped: no CAN signals found")

    state = _chart_state_timeline(store, func_name, windows)
    if state and not state.empty:
        sections.append(state)

    tpe = _chart_tpe_triggers(tpe_result, windows)
    if tpe and not tpe.empty:
        sections.append(tpe)

    if task_type in ("tune", "verify"):
        psens = _chart_parameter_sensitivity(param_report)
        if psens and not psens.empty:
            sections.append(psens)
        wi = _chart_whatif(whatif_entries or [])
        if wi and not wi.empty:
            sections.append(wi)

    _write_html_shell(
        html_path=html_path,
        func_name=func_name,
        task_type=task_type,
        problem=problem,
        expected=expected,
        diagnosis=diagnosis,
        sections=sections,
        windows=windows,
        bag_meta=bag_meta,
        blf_meta=blf_meta,
        warnings=warnings,
    )
    return VisualizerResult(
        html_path=str(html_path),
        charts_built=len(sections),
        warnings=warnings,
    )


# ── Chart builders ──────────────────────────────────────────────────────────


def _chart_ego_speed(store, func_name: str, windows: list) -> Optional[ChartSection]:
    """Ego-speed timeline with per-function speed thresholds and test windows."""
    fmap = get_func_fields(func_name)
    topics = fmap.get("ego_topics", []) or []
    series: list[tuple[float, float, str]] = []
    for topic in topics:
        try:
            frames = store.query_bag_by_topic(topic) or []
        except Exception:
            frames = []
        for f in frames:
            fields = f.get("fields", {}) or {}
            spd = fields.get("car_spd")
            if spd is None:
                continue
            ts = f.get("timestamp_sec")
            if ts is None:
                continue
            try:
                series.append((float(ts), float(spd), topic))
            except (TypeError, ValueError):
                continue
    if not series:
        return None

    series.sort(key=lambda x: x[0])
    t0 = series[0][0]
    by_topic: dict[str, list[tuple[float, float]]] = {}
    for t, v, tp in series:
        by_topic.setdefault(tp, []).append((t - t0, v))

    fig = go.Figure()
    for tp, pts in by_topic.items():
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        fig.add_trace(go.Scatter(
            x=xs, y=ys, mode="lines", name=tp.split("/")[-2] or tp,
            line=dict(width=2),
            hovertemplate="t=%{x:.2f}s<br>spd=%{y:.2f} km/h<extra></extra>",
        ))

    _add_window_shapes(fig, windows, t0)
    layout = _plotly_layout_defaults()
    layout.update(dict(
        title=dict(text="车速时间线", font=dict(size=15)),
        xaxis_title="时间 (s, 相对起点)",
        yaxis_title="car_spd (km/h)",
        height=360,
    ))
    fig.update_layout(**layout)
    body = fig.to_html(full_html=False, include_plotlyjs=False)
    return ChartSection(
        anchor="ego-speed",
        title=f"车速时间线 ({func_name})",
        caption=(
            "自车速度相对起点的时间演化；浅蓝竖条为系统识别出的测试窗口。"
            "若车速在功能激活阈值附近反复穿越，容易触发状态机抖动，"
            "这是低速场景典型的失效来源。"
        ),
        body_html=body,
        tag="基础信号",
        icon="🚗",
    )


def _chart_output_signals(store, func_name: str, windows: list) -> Optional[ChartSection]:
    """Brake / warning / state signals pulled directly from CAN (BLF)."""
    wanted = list(get_output_signals_for_function(func_name))
    if not wanted:
        return None

    inventory = _safe_get_signal_inventory(store)
    sig_lookup: dict[str, tuple[int, str]] = {}
    for info in inventory:
        can_id = info.get("can_id")
        for sig in info.get("signals", []):
            if sig in wanted and sig not in sig_lookup:
                sig_lookup[sig] = (can_id, info.get("message_name") or "?")
    if not sig_lookup:
        return None

    traces: list[tuple[str, list[tuple[float, float]], str]] = []
    t_min: Optional[float] = None
    for sig, (can_id, msg_name) in sig_lookup.items():
        timeline = _safe_signal_timeline(store, can_id, sig)
        if not timeline:
            continue
        pts: list[tuple[float, float]] = []
        for row in timeline:
            ts = row.get("timestamp")
            v = row.get("value")
            if ts is None or v is None:
                continue
            try:
                pts.append((float(ts), float(v)))
            except (TypeError, ValueError):
                continue
        if not pts:
            continue
        if t_min is None or pts[0][0] < t_min:
            t_min = pts[0][0]
        traces.append((sig, pts, msg_name))
    if not traces or t_min is None:
        return None

    fig = go.Figure()
    for sig, pts, msg_name in traces:
        xs = [p[0] - t_min for p in pts]
        ys = [p[1] for p in pts]
        fig.add_trace(go.Scatter(
            x=xs, y=ys, mode="lines+markers",
            name=f"{sig} ({msg_name})",
            line=dict(shape="hv", width=2),
            marker=dict(size=4),
            hovertemplate=f"{sig}<br>t=%{{x:.2f}}s<br>val=%{{y}}<extra></extra>",
        ))
    _add_window_shapes(fig, windows, t_min)
    layout = _plotly_layout_defaults()
    layout.update(dict(
        title=dict(text="CAN 输出信号实测", font=dict(size=15)),
        xaxis_title="时间 (s, 相对起点)",
        yaxis_title="信号值",
        height=400,
    ))
    fig.update_layout(**layout)
    body = fig.to_html(full_html=False, include_plotlyjs=False)
    return ChartSection(
        anchor="output-signals",
        title=f"CAN 输出信号实测 ({func_name})",
        caption=(
            "直接取自 BLF 的功能输出：制动请求 / 预警 / 状态 / TTC 等。"
            "这是判断\"功能到底有没有触发、触发了多久\"的唯一权威来源，"
            "其它证据都必须和它对得上。"
        ),
        body_html=body,
        tag="权威输出",
        icon="📡",
    )


def _chart_state_timeline(store, func_name: str, windows: list) -> Optional[ChartSection]:
    """Step plot of the function's internal state variable."""
    fmap = get_func_fields(func_name)
    state_field = fmap.get("state") or ""
    if not state_field:
        return None
    topics = fmap.get("ego_topics", []) or []

    pts_by_topic: dict[str, list[tuple[float, int]]] = {}
    t_min: Optional[float] = None
    for topic in topics:
        try:
            frames = store.query_bag_by_topic(topic) or []
        except Exception:
            frames = []
        pts: list[tuple[float, int]] = []
        for f in frames:
            fields = f.get("fields", {}) or {}
            v = fields.get(state_field)
            ts = f.get("timestamp_sec")
            if v is None or ts is None:
                continue
            try:
                pts.append((float(ts), int(v)))
            except (TypeError, ValueError):
                continue
        if pts:
            pts.sort(key=lambda x: x[0])
            pts_by_topic[topic] = pts
            if t_min is None or pts[0][0] < t_min:
                t_min = pts[0][0]
    if not pts_by_topic or t_min is None:
        return None

    fig = go.Figure()
    for topic, pts in pts_by_topic.items():
        xs = [p[0] - t_min for p in pts]
        ys = [p[1] for p in pts]
        fig.add_trace(go.Scatter(
            x=xs, y=ys, mode="lines+markers",
            name=topic.split("/")[-2] or topic,
            line=dict(shape="hv", width=2),
            marker=dict(size=4),
            hovertemplate=f"{state_field}<br>t=%{{x:.2f}}s<br>state=%{{y}}<extra></extra>",
        ))
    _add_window_shapes(fig, windows, t_min)
    layout = _plotly_layout_defaults()
    layout.update(dict(
        title=dict(text=f"{state_field} 状态跳变", font=dict(size=15)),
        xaxis_title="时间 (s, 相对起点)",
        yaxis_title=state_field,
        height=300,
    ))
    fig.update_layout(**layout)
    body = fig.to_html(full_html=False, include_plotlyjs=False)
    return ChartSection(
        anchor="state-timeline",
        title=f"{state_field} 状态机跳变",
        caption=(
            "功能内部状态变量的阶跃序列。相邻状态之间的高频跳变，"
            "往往意味着激活条件处在\"临界边缘\"——例如车速/目标消失/外部抑制"
            "等子条件刚好交替导致 Active → Standby → Active 来回切换。"
        ),
        body_html=body,
        tag="状态机",
        icon="🔁",
    )


def _chart_tpe_triggers(tpe_result, windows: list) -> Optional[ChartSection]:
    """Gantt-style view of each TPE pattern's trigger intervals."""
    if tpe_result is None:
        return None
    evidence = getattr(tpe_result, "evidence", None) or []
    triggered = [e for e in evidence if getattr(e, "verdict", "") == "triggered"]
    if not triggered:
        return None

    rows: list[dict] = []
    t_ref: Optional[float] = None
    for e in triggered:
        pattern = getattr(e, "pattern", None)
        pname = getattr(pattern, "name", None) or getattr(pattern, "pattern_type", "?")
        for h in getattr(e, "hits", []) or []:
            iv = getattr(h, "interval", None)
            if iv is None:
                continue
            t0 = float(getattr(iv, "t_start", 0.0))
            t1 = float(getattr(iv, "t_end", t0))
            rows.append({"pattern": pname, "t_start": t0, "t_end": t1})
            if t_ref is None or t0 < t_ref:
                t_ref = t0
    if not rows or t_ref is None:
        return None

    patterns = sorted({r["pattern"] for r in rows})
    pat_to_y = {p: i for i, p in enumerate(patterns)}

    fig = go.Figure()
    for r in rows:
        y = pat_to_y[r["pattern"]]
        fig.add_trace(go.Scatter(
            x=[r["t_start"] - t_ref, r["t_end"] - t_ref],
            y=[y, y],
            mode="lines",
            line=dict(width=14),
            name=r["pattern"], showlegend=False,
            hovertemplate=(
                f"{r['pattern']}<br>"
                f"t=[{r['t_start'] - t_ref:.2f}s, {r['t_end'] - t_ref:.2f}s]"
                "<extra></extra>"
            ),
        ))
    _add_window_shapes(fig, windows, t_ref)
    layout = _plotly_layout_defaults()
    layout.update(dict(
        title=dict(text="TPE 代码模式触发区间", font=dict(size=15)),
        xaxis_title="时间 (s, 相对起点)",
        height=max(240, 40 + 36 * len(patterns)),
        yaxis=dict(
            tickmode="array",
            tickvals=list(pat_to_y.values()),
            ticktext=list(pat_to_y.keys()),
            automargin=True,
        ),
        showlegend=False,
    ))
    fig.update_layout(**layout)
    body = fig.to_html(full_html=False, include_plotlyjs=False)
    return ChartSection(
        anchor="tpe-triggers",
        title="TPE 代码模式触发时间轴",
        caption=(
            "每条泳道是一个 TPE（时序耦合）代码模式——HoldRelease / Debounce / "
            "Accumulate / Suppression 等——在本次录制中实际触发的时间段。"
            "若某专家结论提到的代码模式在这里没出现，该结论就需要重新审视。"
        ),
        body_html=body,
        tag="代码模式",
        icon="🧩",
    )


def _chart_parameter_sensitivity(param_report) -> Optional[ChartSection]:
    """Horizontal bar: per-parameter min |Δ| margin + crossing count.

    The SensitivityEntry produced by ``parameter_analyzer.py`` exposes
    ``entry.stats`` (a ``CrossingStats``) and ``entry.observed_signal`` /
    ``entry.parameter``. We ignore entries whose stats are absent — they
    could not be evaluated against observed data.
    """
    if param_report is None:
        return None
    entries = getattr(param_report, "entries", None) or []
    observable = [e for e in entries if getattr(e, "stats", None) is not None]
    if not observable:
        return None

    rows = []
    for e in observable:
        stats = getattr(e, "stats")
        margin = getattr(stats, "min_margin", None)
        total = int(getattr(stats, "crossings", 0) or 0)
        param = getattr(e, "parameter")
        value = getattr(param, "value", None)
        rows.append({
            "name": getattr(param, "name", "?"),
            "current": value,
            "min_margin": float(margin) if margin is not None else None,
            "crossings": total,
            "category": getattr(param, "category", "") or "",
            "signal": getattr(e, "observed_signal", "") or "",
        })

    rows.sort(key=lambda r: (r["min_margin"] if r["min_margin"] is not None else math.inf))
    rows = rows[:30]
    labels = [r["name"] for r in rows]
    margins = [r["min_margin"] or 0.0 for r in rows]
    customdata = [[r["current"], r["crossings"], r["category"], r["signal"]] for r in rows]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=margins, y=labels, orientation="h",
        marker=dict(
            color=[
                ("#ef4444" if (r["crossings"] or 0) > 0 else "#10b981")
                for r in rows
            ],
            line=dict(color="white", width=0.5),
        ),
        customdata=customdata,
        hovertemplate=(
            "<b>%{y}</b><br>"
            "当前值=%{customdata[0]}<br>"
            "min|Δ|=%{x:.3g}<br>"
            "穿越次数=%{customdata[1]}<br>"
            "category=%{customdata[2]}<br>"
            "signal=%{customdata[3]}<extra></extra>"
        ),
        name="min |Δ|",
    ))
    layout = _plotly_layout_defaults()
    layout.update(dict(
        title=dict(text="参数敏感性（越接近 0 代表越临界）", font=dict(size=15)),
        xaxis_title="min |Δ|（观测值到阈值的最小距离）",
        height=max(280, 28 * len(labels) + 120),
        margin=dict(l=200, r=24, t=56, b=48),
        showlegend=False,
    ))
    fig.update_layout(**layout)
    body = fig.to_html(full_html=False, include_plotlyjs=False)
    return ChartSection(
        anchor="param-sensitivity",
        title="参数敏感性",
        caption=(
            "红色 = 本录制中观测信号已经穿越过该阈值；"
            "绿色 = 还有距离。"
            "min|Δ| 越小代表当前值越贴近阈值——即使没穿越，也只需轻微扰动就会触发/抑制。"
        ),
        body_html=body,
        tag="tune / verify",
        icon="🎛️",
    )


def _chart_whatif(whatif_entries: list) -> Optional[ChartSection]:
    """Bar chart: crossings before vs after each proposed change."""
    if not whatif_entries:
        return None

    rows = []
    for w in whatif_entries:
        try:
            baseline = int(getattr(w, "current_crossings", 0) or 0)
            proposed = int(getattr(w, "proposed_crossings", 0) or 0)
        except Exception:
            baseline, proposed = 0, 0
        rows.append({
            "name": getattr(w, "parameter_name", "?"),
            "baseline": baseline,
            "proposed": proposed,
            "old": getattr(w, "current_value", None),
            "new": getattr(w, "proposed_value", None),
        })
    if not rows:
        return None

    names = [r["name"] for r in rows]
    baseline = [r["baseline"] for r in rows]
    proposed = [r["proposed"] for r in rows]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=names, y=baseline, name="当前（穿越次数）",
        marker=dict(color="#2563eb", line=dict(color="white", width=0.5)),
        hovertemplate="%{x}<br>当前=%{y}<extra></extra>",
    ))
    fig.add_trace(go.Bar(
        x=names, y=proposed, name="提案（穿越次数）",
        marker=dict(color="#f59e0b", line=dict(color="white", width=0.5)),
        hovertemplate="%{x}<br>提案=%{y}<extra></extra>",
    ))
    layout = _plotly_layout_defaults()
    layout.update(dict(
        title=dict(text="What-if 提案评估 — 穿越次数对比", font=dict(size=15)),
        barmode="group",
        height=360,
    ))
    fig.update_layout(**layout)
    fig.update_xaxes(tickangle=-20)
    body = fig.to_html(full_html=False, include_plotlyjs=False)
    return ChartSection(
        anchor="whatif",
        title="What-if 提案评估",
        caption=(
            "同一份录制，把候选参数值代入后，观测信号穿越该阈值的次数"
            "如何变化。次数减少 ≈ 问题更少触发；次数增加 ≈ 触发更灵敏。"
            "这是验证参数调整方向最快的经验法。"
        ),
        body_html=body,
        tag="tune / verify",
        icon="🔮",
    )


# ── Helpers ────────────────────────────────────────────────────────────────


def _add_window_shapes(fig, windows: Iterable, t_ref: float) -> None:
    """Draw light-blue translucent rectangles for each test window."""
    for i, w in enumerate(windows or []):
        try:
            t0 = float(w.t_start) - t_ref
            t1 = float(w.t_end) - t_ref
        except Exception:
            continue
        if t1 <= t0:
            continue
        fig.add_vrect(
            x0=t0, x1=t1,
            fillcolor="#2563eb", opacity=0.08,
            line_width=0,
            annotation_text=f"W{i+1}",
            annotation_position="top left",
            annotation=dict(font_size=10, font_color="#1e40af"),
        )


def _safe_get_signal_inventory(store) -> list[dict]:
    try:
        return store.get_signal_inventory() or []
    except Exception:
        return []


def _safe_signal_timeline(store, can_id: int, signal_name: str) -> list[dict]:
    try:
        return store.query_signal_timeline(can_id, signal_name) or []
    except Exception:
        return []


# ── Markdown rendering ──────────────────────────────────────────────────────


_FALLBACK_RULES = [
    # fenced code blocks (``` ... ```)
    (re.compile(r"```(?:[a-zA-Z0-9_-]+)?\n(.*?)```", re.DOTALL),
     lambda m: f"<pre class=\"md-code\"><code>{html.escape(m.group(1))}</code></pre>"),
    # horizontal rules
    (re.compile(r"^---+\s*$", re.MULTILINE), lambda _m: "<hr/>"),
    # headings
    (re.compile(r"^####\s+(.+)$", re.MULTILINE), lambda m: f"<h4>{m.group(1)}</h4>"),
    (re.compile(r"^###\s+(.+)$", re.MULTILINE),  lambda m: f"<h3>{m.group(1)}</h3>"),
    (re.compile(r"^##\s+(.+)$",  re.MULTILINE),  lambda m: f"<h2>{m.group(1)}</h2>"),
    (re.compile(r"^#\s+(.+)$",   re.MULTILINE),  lambda m: f"<h1>{m.group(1)}</h1>"),
    # bold / italic / inline code
    (re.compile(r"\*\*(.+?)\*\*"), lambda m: f"<strong>{m.group(1)}</strong>"),
    (re.compile(r"`([^`]+)`"),      lambda m: f"<code>{html.escape(m.group(1))}</code>"),
]


def _md_to_html(text: str) -> str:
    """Convert a markdown string to HTML.

    Uses python-markdown when available (with tables / fenced code /
    attribute lists / smart line breaks). Falls back to a minimal
    regex-based converter so the HTML report still looks acceptable if
    the optional dependency is missing.
    """
    if not text:
        return ""

    if _MARKDOWN_OK:
        try:
            return _md.markdown(
                text,
                extensions=[
                    "fenced_code",
                    "tables",
                    "sane_lists",
                    "nl2br",
                    "attr_list",
                ],
                output_format="html5",
            )
        except Exception:
            pass

    # Fallback: crude but safe.
    escaped = html.escape(text)
    html_body = escaped
    for pattern, repl in _FALLBACK_RULES:
        html_body = pattern.sub(repl, html_body)
    # Paragraphs: blank-line separated.
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", html_body) if p.strip()]
    return "\n".join(
        p if p.startswith("<") else f"<p>{p.replace(chr(10), '<br/>')}</p>"
        for p in paragraphs
    )


# ── HTML shell ──────────────────────────────────────────────────────────────


_PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>{title}</title>
<script type="text/javascript">{plotly_js}</script>
<style>
{css}
</style>
</head>
<body>

<header class="page-header">
  <div class="page-header__inner">
    <div class="page-header__left">
      <div class="eyebrow">radarAnalyze · 可视化报告</div>
      <h1>{title}</h1>
      <div class="hero-badges">
        <span class="badge badge--{task_badge_class}">{task_type_label}</span>
        <span class="badge badge--func">{func_name}</span>
        <span class="badge badge--soft">生成时间 {generated_at}</span>
        <span class="badge badge--soft">{chart_count} 张图表</span>
      </div>
    </div>
  </div>
</header>

<main class="page-main">

  <aside class="toc" aria-label="目录">
    <div class="toc__title">目录</div>
    <nav>
      <ul>
        <li><a href="#summary">案件摘要</a></li>
        <li><a href="#windows">测试窗口</a></li>
        {toc_chart_items}
        <li><a href="#diagnosis">专家完整分析</a></li>
        {toc_meta_item}
      </ul>
    </nav>
  </aside>

  <section class="page-body">

    <article id="summary" class="card">
      <header class="card__header">
        <span class="card__icon">📝</span>
        <h2>案件摘要</h2>
      </header>
      <div class="card__body">
        <div class="kv-grid">
          <div class="kv">
            <div class="kv__label">任务类型</div>
            <div class="kv__value"><span class="badge badge--{task_badge_class}">{task_type_label}</span></div>
          </div>
          <div class="kv">
            <div class="kv__label">涉及功能</div>
            <div class="kv__value"><span class="badge badge--func">{func_name}</span></div>
          </div>
          <div class="kv">
            <div class="kv__label">图表数量</div>
            <div class="kv__value">{chart_count} 张</div>
          </div>
          <div class="kv">
            <div class="kv__label">测试窗口</div>
            <div class="kv__value">{window_count} 个</div>
          </div>
        </div>
        <div class="divider"></div>
        <div class="kv-stack">
          <div class="kv kv--wide">
            <div class="kv__label">问题现象</div>
            <div class="kv__value kv__value--prose">{problem_html}</div>
          </div>
          <div class="kv kv--wide">
            <div class="kv__label">预期结果</div>
            <div class="kv__value kv__value--prose">{expected_html}</div>
          </div>
        </div>
      </div>
    </article>

    <article id="windows" class="card">
      <header class="card__header">
        <span class="card__icon">🪟</span>
        <h2>测试窗口</h2>
        <span class="card__tag">来自 TestWindowDetector</span>
      </header>
      <div class="card__body">
        {windows_block}
      </div>
    </article>

    {charts_html}

    <article id="diagnosis" class="card">
      <header class="card__header">
        <span class="card__icon">🧠</span>
        <h2>专家完整分析</h2>
        <span class="card__tag">Markdown 渲染</span>
      </header>
      <div class="card__body markdown-body">
        {diagnosis_html}
      </div>
    </article>

    {warning_block}

    {meta_card}

  </section>
</main>

<footer class="page-footer">
  <span>radarAnalyze · 诊断 + 参数调优 + 可视化一体化平台</span>
  <span>· 本文件完全离线可读 · 图表交互由 plotly.js 提供</span>
</footer>

</body>
</html>
"""


_CSS = """
:root {
  --c-bg: #f3f5fb;
  --c-surface: #ffffff;
  --c-surface-alt: #f8fafc;
  --c-text: #1e293b;
  --c-text-muted: #64748b;
  --c-text-soft: #94a3b8;
  --c-border: #e2e8f0;
  --c-border-strong: #cbd5e1;
  --c-primary: #2563eb;
  --c-primary-soft: #dbeafe;
  --c-primary-dark: #1e3a8a;
  --c-accent: #0ea5e9;
  --c-success: #10b981;
  --c-warning: #f59e0b;
  --c-danger: #ef4444;
  --c-diag: #2563eb;
  --c-tune: #14b8a6;
  --c-verify: #f59e0b;
  --c-query: #8b5cf6;
  --radius: 10px;
  --radius-sm: 6px;
  --shadow-sm: 0 1px 2px rgba(15,23,42,0.05);
  --shadow-md: 0 4px 14px -4px rgba(15,23,42,0.12);
}

* { box-sizing: border-box; }

body {
  margin: 0;
  padding: 0;
  font-family:
    "Inter", "Segoe UI", -apple-system, BlinkMacSystemFont,
    "PingFang SC", "Microsoft YaHei", sans-serif;
  color: var(--c-text);
  background: var(--c-bg);
  font-size: 14px;
  line-height: 1.6;
}

a { color: var(--c-primary); text-decoration: none; }
a:hover { text-decoration: underline; }

/* ── Header ──────────────────────────────────────────────────── */

.page-header {
  background:
    radial-gradient(1200px 400px at 15% -10%, rgba(14,165,233,0.18), transparent 60%),
    linear-gradient(135deg, #0f172a 0%, #1e3a8a 60%, #1e40af 100%);
  color: #e2e8f0;
  padding: 40px 48px 36px;
  box-shadow: var(--shadow-md);
}
.page-header__inner { max-width: 1400px; margin: 0 auto; }
.page-header h1 {
  margin: 6px 0 14px;
  font-size: 26px;
  font-weight: 700;
  letter-spacing: -0.01em;
  color: #f8fafc;
}
.eyebrow {
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  color: #93c5fd;
  font-weight: 600;
}
.hero-badges { display: flex; flex-wrap: wrap; gap: 8px; }

/* ── Badges ──────────────────────────────────────────────────── */

.badge {
  display: inline-flex;
  align-items: center;
  padding: 3px 10px;
  font-size: 12px;
  font-weight: 600;
  border-radius: 999px;
  background: rgba(255,255,255,0.14);
  color: #f1f5f9;
  border: 1px solid rgba(255,255,255,0.2);
}
.badge--soft {
  background: rgba(255,255,255,0.06);
  color: #cbd5e1;
  font-weight: 500;
}
.badge--diag    { background: var(--c-diag);    color: white; border-color: transparent; }
.badge--tune    { background: var(--c-tune);    color: white; border-color: transparent; }
.badge--verify  { background: var(--c-verify);  color: white; border-color: transparent; }
.badge--query   { background: var(--c-query);   color: white; border-color: transparent; }
.badge--func {
  background: #f8fafc;
  color: var(--c-primary-dark);
  border-color: #e2e8f0;
}

.card__body .badge {
  background: var(--c-primary-soft);
  color: var(--c-primary-dark);
  border: none;
}
.card__body .badge--diag    { background: var(--c-diag);    color: white; }
.card__body .badge--tune    { background: var(--c-tune);    color: white; }
.card__body .badge--verify  { background: var(--c-verify);  color: white; }
.card__body .badge--query   { background: var(--c-query);   color: white; }
.card__body .badge--func    { background: #e0e7ff; color: var(--c-primary-dark); }

/* ── Main 2-col layout ──────────────────────────────────────── */

.page-main {
  display: grid;
  grid-template-columns: 220px minmax(0, 1fr);
  max-width: 1400px;
  margin: -20px auto 0;
  padding: 0 24px 48px;
  gap: 28px;
}
@media (max-width: 960px) {
  .page-main { grid-template-columns: 1fr; padding: 0 14px 40px; }
  .toc { position: static !important; max-height: none !important; }
}

.toc {
  position: sticky;
  top: 20px;
  align-self: start;
  max-height: calc(100vh - 40px);
  overflow-y: auto;
  background: var(--c-surface);
  border: 1px solid var(--c-border);
  border-radius: var(--radius);
  padding: 14px 14px 18px;
  box-shadow: var(--shadow-sm);
}
.toc__title {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.14em;
  color: var(--c-text-soft);
  font-weight: 700;
  margin-bottom: 10px;
}
.toc ul { list-style: none; padding: 0; margin: 0; }
.toc li { margin: 4px 0; }
.toc a {
  display: block;
  padding: 6px 10px;
  border-radius: var(--radius-sm);
  font-size: 13px;
  color: var(--c-text);
  transition: background 0.15s, color 0.15s;
}
.toc a:hover {
  background: var(--c-primary-soft);
  color: var(--c-primary-dark);
  text-decoration: none;
}

/* ── Cards ──────────────────────────────────────────────────── */

.card {
  background: var(--c-surface);
  border: 1px solid var(--c-border);
  border-radius: var(--radius);
  box-shadow: var(--shadow-sm);
  margin-bottom: 22px;
  overflow: hidden;
}
.card__header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 16px 22px 12px;
  border-bottom: 1px solid var(--c-border);
  background: linear-gradient(180deg, #fafbfe 0%, #ffffff 100%);
}
.card__header h2 {
  margin: 0;
  font-size: 16px;
  font-weight: 700;
  color: var(--c-text);
  flex: 1;
}
.card__icon { font-size: 18px; }
.card__tag {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 999px;
  background: var(--c-primary-soft);
  color: var(--c-primary-dark);
  font-weight: 600;
}
.card__body { padding: 18px 22px 22px; }
.card__caption {
  color: var(--c-text-muted);
  font-size: 13px;
  margin: -6px 0 14px;
  max-width: 900px;
}

/* ── Key-value grid ─────────────────────────────────────────── */

.kv-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 14px 18px;
  margin-bottom: 12px;
}
.kv-stack { display: flex; flex-direction: column; gap: 12px; }
.kv { min-width: 0; }
.kv__label {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  color: var(--c-text-soft);
  font-weight: 600;
  margin-bottom: 4px;
}
.kv__value {
  font-size: 14px;
  color: var(--c-text);
  word-break: break-word;
}
.kv__value--prose { line-height: 1.55; }
.divider { height: 1px; background: var(--c-border); margin: 14px 0; }

/* ── Windows strip ──────────────────────────────────────────── */

.window-strip {
  margin-top: 10px;
  padding: 14px 16px;
  background: var(--c-surface-alt);
  border: 1px solid var(--c-border);
  border-radius: var(--radius-sm);
}
.window-strip__track {
  position: relative;
  height: 32px;
  background: #eef2ff;
  border-radius: var(--radius-sm);
  overflow: hidden;
}
.window-strip__seg {
  position: absolute;
  top: 0; bottom: 0;
  background: linear-gradient(180deg, rgba(37,99,235,0.85), rgba(37,99,235,0.65));
  color: white;
  font-size: 10px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  border-right: 1px solid rgba(255,255,255,0.35);
}
.window-strip__axis {
  display: flex;
  justify-content: space-between;
  font-size: 11px;
  color: var(--c-text-soft);
  margin-top: 6px;
}
.window-list {
  margin-top: 16px;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 8px 12px;
  font-size: 12.5px;
}
.window-list > div {
  padding: 6px 10px;
  border-left: 3px solid var(--c-primary);
  background: var(--c-surface-alt);
  border-radius: var(--radius-sm);
  color: var(--c-text);
}
.window-list > div b { color: var(--c-primary-dark); }

/* ── Markdown body ──────────────────────────────────────────── */

.markdown-body { font-size: 14px; line-height: 1.7; }
.markdown-body h1,
.markdown-body h2,
.markdown-body h3,
.markdown-body h4 {
  margin: 28px 0 12px;
  font-weight: 700;
  color: var(--c-text);
  line-height: 1.35;
}
.markdown-body h1 { font-size: 20px; border-bottom: 2px solid var(--c-border); padding-bottom: 8px; }
.markdown-body h2 { font-size: 17px; color: var(--c-primary-dark); }
.markdown-body h3 { font-size: 15.5px; }
.markdown-body h4 { font-size: 14px; color: var(--c-text-muted); }
.markdown-body p { margin: 10px 0; }
.markdown-body strong { color: var(--c-text); font-weight: 700; }
.markdown-body code {
  background: #eef2ff;
  color: #1e3a8a;
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 12.5px;
  font-family: "SF Mono", "Cascadia Mono", Consolas, "Microsoft YaHei Mono", monospace;
}
.markdown-body pre,
.markdown-body .md-code {
  background: #0f172a;
  color: #e2e8f0;
  padding: 14px 18px;
  border-radius: var(--radius-sm);
  overflow-x: auto;
  font-size: 12.5px;
  line-height: 1.55;
  font-family: "SF Mono", "Cascadia Mono", Consolas, "Microsoft YaHei Mono", monospace;
  border: 1px solid #1e293b;
}
.markdown-body pre code { background: transparent; color: inherit; padding: 0; }

.markdown-body ul,
.markdown-body ol { padding-left: 26px; margin: 10px 0; }
.markdown-body li { margin: 4px 0; }

.markdown-body blockquote {
  margin: 12px 0;
  padding: 10px 16px;
  border-left: 4px solid var(--c-warning);
  background: #fffbeb;
  color: #78350f;
  border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
}

.markdown-body hr {
  border: none;
  border-top: 1px dashed var(--c-border-strong);
  margin: 22px 0;
}

.markdown-body table {
  width: 100%;
  border-collapse: separate;
  border-spacing: 0;
  margin: 14px 0;
  font-size: 13px;
  background: var(--c-surface);
  border: 1px solid var(--c-border);
  border-radius: var(--radius-sm);
  overflow: hidden;
}
.markdown-body th {
  background: #eef2ff;
  color: var(--c-primary-dark);
  font-weight: 700;
  text-align: left;
  padding: 9px 12px;
  border-bottom: 1px solid var(--c-border);
}
.markdown-body td {
  padding: 8px 12px;
  border-bottom: 1px solid var(--c-border);
  vertical-align: top;
  color: var(--c-text);
}
.markdown-body tr:last-child td { border-bottom: none; }
.markdown-body tr:nth-child(even) td { background: #f8fafc; }
.markdown-body tr:hover td { background: #eef2ff; }

/* ── Warning block ──────────────────────────────────────────── */

.warn-card {
  background: #fffbeb;
  border: 1px solid #fde68a;
  color: #78350f;
  border-radius: var(--radius);
  padding: 14px 18px;
  margin-bottom: 22px;
  font-size: 13px;
}
.warn-card b { color: #b45309; }
.warn-card ul { margin: 6px 0 0 20px; padding: 0; }

/* ── Meta card (BAG/BLF etc.) ────────────────────────────── */

.meta-row {
  display: grid;
  grid-template-columns: 90px 1fr;
  gap: 10px 14px;
  font-size: 13px;
  padding: 6px 0;
  border-bottom: 1px dashed var(--c-border);
}
.meta-row:last-child { border-bottom: none; }
.meta-row__label { color: var(--c-text-soft); font-weight: 600; }
.meta-row__value { color: var(--c-text); word-break: break-all; }

/* ── Footer ────────────────────────────────────────────────── */

.page-footer {
  text-align: center;
  color: var(--c-text-soft);
  font-size: 12px;
  padding: 24px 20px;
}
.page-footer span { display: inline-block; margin: 0 4px; }

/* ── Plotly fine-tuning ────────────────────────────────────── */

.js-plotly-plot .plotly .modebar { opacity: 0.35; }
.js-plotly-plot .plotly .modebar:hover { opacity: 1; }
.chart-host { margin-top: 4px; }
"""


def _window_strip_html(windows: list) -> str:
    """Build a graphical strip of test windows plus a descriptive list."""
    if not windows:
        return '<p style="color:var(--c-text-muted)">本次录制未检测到有效测试窗口。</p>'

    try:
        t_min = min(float(w.t_start) for w in windows)
        t_max = max(float(w.t_end) for w in windows)
    except Exception:
        t_min = 0.0
        t_max = 1.0
    span = max(t_max - t_min, 1e-6)

    segs = []
    for i, w in enumerate(windows):
        try:
            t0 = float(w.t_start)
            t1 = float(w.t_end)
        except Exception:
            continue
        left = (t0 - t_min) / span * 100.0
        width = max((t1 - t0) / span * 100.0, 0.6)
        dur = t1 - t0
        segs.append(
            f'<div class="window-strip__seg" style="left:{left:.3f}%; width:{width:.3f}%;" '
            f'title="W{i+1}: {t0:.2f}s~{t1:.2f}s ({dur:.2f}s)">'
            f'W{i+1}</div>'
        )

    tmin_disp = f"t₀ = {t_min:.2f}s"
    tmax_disp = f"t_end = {t_max:.2f}s ({t_max - t_min:.2f}s)"

    items = []
    for i, w in enumerate(windows):
        try:
            t0 = float(w.t_start)
            t1 = float(w.t_end)
            dur = float(getattr(w, "duration", t1 - t0))
        except Exception:
            continue
        reasons = ""
        ev_types = getattr(w, "event_types", None) or []
        if ev_types:
            reasons = " · " + html.escape(", ".join(str(x) for x in ev_types))
        items.append(
            f"<div><b>W{i+1}</b> · {t0:.2f}s~{t1:.2f}s "
            f"<span style='color:var(--c-text-muted)'>({dur:.2f}s{reasons})</span></div>"
        )

    return (
        '<div class="window-strip">'
        '  <div class="window-strip__track">' + "".join(segs) + '</div>'
        f'  <div class="window-strip__axis"><span>{tmin_disp}</span><span>{tmax_disp}</span></div>'
        '</div>'
        '<div class="window-list">' + "".join(items) + '</div>'
    )


def _meta_card_html(bag_meta: Optional[dict], blf_meta: Optional[dict]) -> str:
    rows: list[str] = []

    def _row(label: str, value: str) -> str:
        return (
            f'<div class="meta-row">'
            f'  <div class="meta-row__label">{label}</div>'
            f'  <div class="meta-row__value">{value}</div>'
            f'</div>'
        )

    if bag_meta:
        rows.append(_row(
            "BAG",
            (
                f"<b>{html.escape(str(bag_meta.get('file', '?')))}</b>"
                f" · {bag_meta.get('duration_sec', 0):.1f}s"
                f" · {bag_meta.get('message_count', 0)} 帧"
            ),
        ))
    if blf_meta:
        rows.append(_row(
            "BLF",
            (
                f"<b>{html.escape(str(blf_meta.get('file', '?')))}</b>"
                f" · {blf_meta.get('duration_sec', 0):.1f}s"
                f" · {blf_meta.get('message_count', 0)} 帧"
            ),
        ))
    if not rows:
        return ""

    return (
        '<article id="meta" class="card">'
        '  <header class="card__header">'
        '    <span class="card__icon">🗃️</span>'
        '    <h2>元数据</h2>'
        '    <span class="card__tag">数据来源</span>'
        '  </header>'
        f'  <div class="card__body">{"".join(rows)}</div>'
        '</article>'
    )


def _sections_html(sections: list[ChartSection]) -> str:
    if not sections:
        return (
            '<article class="card">'
            '  <div class="card__body" style="color:var(--c-text-muted)">'
            '    没有可绘制的数据 — 检查 BAG/BLF 是否成功解析。'
            '  </div>'
            '</article>'
        )
    parts: list[str] = []
    for i, s in enumerate(sections, 1):
        tag_html = (
            f'<span class="card__tag">{html.escape(s.tag)}</span>'
            if s.tag else ""
        )
        caption_html = (
            f'<p class="card__caption">{html.escape(s.caption)}</p>'
            if s.caption else ""
        )
        parts.append(
            f'<article id="{html.escape(s.anchor)}" class="card">'
            f'  <header class="card__header">'
            f'    <span class="card__icon">{s.icon}</span>'
            f'    <h2>图 {i}. {html.escape(s.title)}</h2>'
            f'    {tag_html}'
            f'  </header>'
            f'  <div class="card__body">'
            f'    {caption_html}'
            f'    <div class="chart-host">{s.body_html}</div>'
            f'  </div>'
            f'</article>'
        )
    return "\n".join(parts)


def _toc_items(sections: list[ChartSection]) -> str:
    return "\n".join(
        f'        <li><a href="#{html.escape(s.anchor)}">{s.icon} 图{i}. {html.escape(s.title)}</a></li>'
        for i, s in enumerate(sections, 1)
    )


_TASK_LABELS = {
    "diagnose": "诊断 (diagnose)",
    "tune":     "调优 (tune)",
    "verify":   "验证 (verify)",
    "query":    "信息检索 (query)",
}
_TASK_TITLES = {
    "diagnose": "角雷达问题诊断报告",
    "tune":     "角雷达参数调优报告",
    "verify":   "角雷达参数验证报告",
    "query":    "角雷达信息检索报告",
}


def _write_html_shell(
    *,
    html_path: Path,
    func_name: str,
    task_type: str,
    problem: str,
    expected: str,
    diagnosis: str,
    sections: list[ChartSection],
    windows: list,
    bag_meta: Optional[dict],
    blf_meta: Optional[dict],
    warnings: list[str],
) -> None:
    tt_norm = (task_type or "diagnose").lower()
    title = _TASK_TITLES.get(tt_norm, _TASK_TITLES["diagnose"])
    task_label = _TASK_LABELS.get(tt_norm, _TASK_LABELS["diagnose"])

    diagnosis_html = _md_to_html(diagnosis or "")
    problem_html = _md_to_html(problem or "") or "<em>（未提供）</em>"
    expected_html = _md_to_html(expected or "") or "<em>（未提供）</em>"

    windows_block = _window_strip_html(windows)
    charts_html = _sections_html(sections)
    meta_card = _meta_card_html(bag_meta, blf_meta)

    warning_block = ""
    if warnings:
        bullets = "".join(f"<li>{html.escape(w)}</li>" for w in warnings)
        warning_block = (
            '<div class="warn-card">'
            f'<b>以下步骤被跳过</b><ul>{bullets}</ul>'
            '</div>'
        )

    page = _PAGE_TEMPLATE.format(
        title=html.escape(title),
        plotly_js=_load_plotly_js(),
        css=_CSS,
        task_type_label=html.escape(task_label),
        task_badge_class=tt_norm,
        func_name=html.escape(func_name),
        generated_at=_dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        chart_count=len(sections),
        window_count=len(windows or []),
        problem_html=problem_html,
        expected_html=expected_html,
        windows_block=windows_block,
        charts_html=charts_html,
        diagnosis_html=diagnosis_html,
        toc_chart_items=_toc_items(sections),
        toc_meta_item='<li><a href="#meta">元数据</a></li>' if meta_card else "",
        warning_block=warning_block,
        meta_card=meta_card,
    )
    html_path.write_text(page, encoding="utf-8")


def _write_fallback_html(
    html_path: Path,
    func_name: str,
    task_type: str,
    problem: str,
    expected: str,
    diagnosis: str,
    *,
    reason: str,
) -> None:
    """Emit a minimal (no-chart) report so downstream tooling still works."""
    body = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>Report</title>
<style>
body {{ font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
  max-width: 900px; margin: 40px auto; padding: 0 20px; color: #1e293b; }}
h1 {{ color: #b45309; }}
pre {{ background: #f1f5f9; padding: 14px; border-radius: 6px; white-space: pre-wrap; }}
</style>
</head>
<body>
<h1>可视化报告不可用</h1>
<p style="color:#b14100"><b>原因</b>: {html.escape(reason)}</p>
<h2>元信息</h2>
<ul>
<li>任务类型: {html.escape(task_type)}</li>
<li>功能: {html.escape(func_name)}</li>
<li>问题: {html.escape(problem or '')}</li>
<li>预期: {html.escape(expected or '')}</li>
</ul>
<h2>专家结论</h2>
<pre>{html.escape(diagnosis or '')}</pre>
</body></html>"""
    html_path.write_text(body, encoding="utf-8")


def _load_plotly_js() -> str:
    """Return the plotly.js bundle as a string, inlined into the HTML.

    Inlining keeps the report 100% offline. If the bundle cannot be
    located (unusual plotly install) we fall back to the CDN script tag;
    the fallback still renders as long as the host has internet access.
    """
    try:
        from plotly.offline import get_plotlyjs
        return get_plotlyjs()
    except Exception:
        return (
            "/* plotly.js bundle unavailable; loading from CDN */"
            "document.write("
            "'<script src=\"https://cdn.plot.ly/plotly-latest.min.js\"></' + 'script>'"
            ");"
        )
