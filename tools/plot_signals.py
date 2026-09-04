# -*- coding: utf-8 -*-
"""
Standalone Signal Plotter.
Extracts specific signals or uses AI to find relevant signals from a query,
and visualizes them in an interactive HTML report.
"""
import sys
import argparse
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cli import load_config
from ai.model_router import ModelRouter
from ai.data_query_engine import DataQueryEngine
from parsers.case_loader import load_case_data
from parsers.frame_store import FrameStore
try:
    import plotly.graph_objects as go
except ImportError:
    go = None

def _plotly_layout_defaults() -> dict:
    """Shared Plotly layout dict."""
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
        margin=dict(l=48, r=24, t=56, b=48),
        legend=dict(
            orientation="h", yanchor="bottom", y=1.02, x=0,
            font=dict(size=11),
            bgcolor="rgba(255,255,255,0.8)",
            bordercolor="#e2e8f0", borderwidth=1,
        )
    )

def get_signal_timeline(store: FrameStore, can_id: int, signal_name: str):
    try:
        return store.query_signal_timeline(can_id, signal_name) or []
    except Exception:
        return []

def _has_radar_tables(store: FrameStore) -> bool:
    """True if the store has non-empty radar_objects or radar_debug tables."""
    try:
        cur = store.conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name IN ('radar_objects','radar_debug')"
        )
        names = {row[0] for row in cur.fetchall()}
        if not names:
            return False
        for tbl in ("radar_objects", "radar_debug"):
            if tbl in names:
                cnt = store.conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
                if cnt > 0:
                    return True
        return False
    except Exception:
        return False


def plot_radar_fallback(store: FrameStore, output_html: Path) -> bool:
    """G4: when no CAN signals are available, plot radar-internal/object curves.

    Draws, when the tables are populated:
      * radar_debug.actual_spd (ego speed) vs time
      * radar_objects.dist_x per (radar_id, obj_id) vs time (subsampled)

    Returns True on success, False if no radar data either.
    """
    if not go:
        print("[Error] plotly is required for visualization. pip install plotly")
        return False

    traces = []
    t_min = None

    # ---- radar_debug: ego dynamics ---------------------------------
    try:
        rows = [
            dict(r) for r in store.conn.execute(
                "SELECT timestamp_ns, actual_spd, yaw_rate, lat_accel, long_accel, "
                "steer_angle FROM radar_debug ORDER BY timestamp_ns"
            ).fetchall()
        ]
    except Exception:
        rows = []

    dbg_fields = ("actual_spd", "yaw_rate", "lat_accel", "long_accel", "steer_angle")
    for field in dbg_fields:
        pts = []
        for r in rows:
            v = r.get(field)
            ts = r.get("timestamp_ns")
            if v is None or ts is None:
                continue
            try:
                pts.append((float(ts) / 1e9, float(v)))
            except (TypeError, ValueError):
                continue
        if pts:
            if t_min is None or pts[0][0] < t_min:
                t_min = pts[0][0]
            traces.append((f"radar_debug.{field}", pts, "ego"))

    # ---- radar_objects: per-object dist_x trajectory ----------------
    try:
        obj_rows = [
            dict(r) for r in store.conn.execute(
                "SELECT timestamp_ns, radar_id, obj_id, dist_x, vel_abs_x, ttc "
                "FROM radar_objects ORDER BY timestamp_ns"
            ).fetchall()
        ]
    except Exception:
        obj_rows = []

    # group by (radar_id, obj_id), subsample to keep traces light
    by_key: dict[tuple, list[tuple[float, float, float, float]]] = {}
    for r in obj_rows:
        key = (r.get("radar_id"), r.get("obj_id"))
        ts = r.get("timestamp_ns")
        dx = r.get("dist_x")
        vx = r.get("vel_abs_x")
        ttc = r.get("ttc")
        if ts is None:
            continue
        try:
            t = float(ts) / 1e9
            by_key.setdefault(key, []).append((
                t,
                float(dx) if dx is not None else float("nan"),
                float(vx) if vx is not None else float("nan"),
                float(ttc) if ttc is not None else float("nan"),
            ))
        except (TypeError, ValueError):
            continue

    for (radar_id, obj_id), pts in by_key.items():
        if not pts:
            continue
        if t_min is None or pts[0][0] < t_min:
            t_min = pts[0][0]
        # dist_x trace (primary); subsample >500 pts
        step = max(1, len(pts) // 500)
        sub = pts[::step]
        dx_pts = [(p[0], p[1]) for p in sub if p[1] == p[1]]  # drop NaN
        if dx_pts:
            traces.append((
                f"obj r{radar_id}#{obj_id}.dist_x",
                dx_pts,
                "objects",
            ))
        ttc_pts = [(p[0], p[3]) for p in sub if p[3] == p[3]]
        if ttc_pts:
            traces.append((
                f"obj r{radar_id}#{obj_id}.ttc",
                ttc_pts,
                "objects",
            ))

    if not traces:
        print("No CAN signals and no radar_objects/radar_debug data available to plot.")
        return False

    fig = go.Figure()
    for sig, pts, group in traces:
        xs = [p[0] - (t_min or 0.0) for p in pts]
        ys = [p[1] for p in pts]
        fig.add_trace(go.Scatter(
            x=xs, y=ys, mode="lines+markers",
            name=f"{sig} ({group})",
            line=dict(shape="hv", width=2),
            marker=dict(size=3),
        ))

    layout = _plotly_layout_defaults()
    layout.update(dict(
        title=dict(
            text="Radar-Internal / Object Visualization (no CAN)",
            font=dict(size=18),
        ),
        xaxis_title="Time (s)",
        yaxis_title="Value (radar units)",
        height=600,
    ))
    fig.update_layout(**layout)

    html_content = fig.to_html(full_html=True, include_plotlyjs='cdn')
    output_html.write_text(html_content, encoding="utf-8")
    print(f"[Success] Radar fallback plot generated at {output_html.absolute()}")
    return True


def plot_signals(store: FrameStore, signals: list[str], output_html: Path):
    if not go:
        print("[Error] plotly is required for visualization. pip install plotly")
        return False

    inventory = store.get_signal_inventory() or []
    sig_lookup = {}
    for info in inventory:
        can_id = info.get("can_id")
        for sig in info.get("signals", []):
            if sig in signals:
                sig_lookup[sig] = (can_id, info.get("message_name") or "?")

    traces = []
    t_min = None
    for sig in signals:
        if sig not in sig_lookup:
            print(f"[Warning] Signal {sig} not found in inventory.")
            continue
        can_id, msg_name = sig_lookup[sig]
        timeline = get_signal_timeline(store, can_id, sig)
        if not timeline:
            print(f"[Warning] No data for signal {sig}.")
            continue
        
        pts = []
        for row in timeline:
            ts = row.get("timestamp")
            v = row.get("value")
            if ts is None or v is None: continue
            try:
                pts.append((float(ts), float(v)))
            except:
                pass
        
        if pts:
            traces.append((sig, pts, msg_name))
            if t_min is None or pts[0][0] < t_min:
                t_min = pts[0][0]

    if not traces:
        print("No CAN signal data found; trying radar_objects/radar_debug fallback...")
        return plot_radar_fallback(store, output_html)

    fig = go.Figure()
    for sig, pts, msg_name in traces:
        xs = [p[0] - t_min for p in pts]
        ys = [p[1] for p in pts]
        fig.add_trace(go.Scatter(
            x=xs, y=ys, mode="lines+markers",
            name=f"{sig} ({msg_name})",
            line=dict(shape="hv", width=2),
            marker=dict(size=4)
        ))

    layout = _plotly_layout_defaults()
    layout.update(dict(
        title=dict(text="Standalone Signal Visualization", font=dict(size=18)),
        xaxis_title="Time (s)",
        yaxis_title="Signal Value",
        height=600,
    ))
    fig.update_layout(**layout)

    html_content = fig.to_html(full_html=True, include_plotlyjs='cdn')
    output_html.write_text(html_content, encoding="utf-8")
    print(f"[Success] Plot generated at {output_html.absolute()}")
    return True

def main():
    parser = argparse.ArgumentParser("Standalone Signal Plotter")
    parser.add_argument("case_dir", type=Path, help="Case folder containing .bag/.blf files")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--signals", type=str, help="Comma-separated list of signals (e.g. 'VehSpd_0x137,FCTA_Warn')")
    group.add_argument("--query", type=str, help="Natural language query to auto-select signals")
    parser.add_argument("--variant", type=str, default=None)
    args = parser.parse_args()

    config = load_config(variant_id=args.variant)

    from parsers.case_loader import load_case_data

    print(f"Loading data from {args.case_dir}...")
    load_result = load_case_data(args.case_dir, config, Path(config["paths"]["project_root"]))
    store = load_result.store

    signals_to_plot = []
    if args.signals:
        signals_to_plot = [s.strip() for s in args.signals.split(",")]
    else:
        print(f"Using AI to find relevant signals for query: {args.query}")
        router = ModelRouter(config)
        engine = DataQueryEngine(router, config, Path(config["paths"]["project_root"]))
        
        signal_lookup, signal_table = engine._build_signal_lookup(store)
        bag_inventory = engine._build_bag_inventory(store)
        knowledge_ctx = ""
        
        plan = engine._plan_query(args.query, signal_table, bag_inventory, knowledge_ctx)
        can_signals = plan.get("can_signals", [])
        signals_to_plot = [s.get("signal_name") for s in can_signals if s.get("signal_name")]
        
        print(f"AI identified signals: {signals_to_plot}")

    if not signals_to_plot:
        print("No CAN signals identified; checking for radar-only data...")
        out_file = args.case_dir / "signal_plot.html"
        if _has_radar_tables(store):
            success = plot_radar_fallback(store, out_file)
            return 0 if success else 1
        print("No signals and no radar data available to plot.")
        return 1

    out_file = args.case_dir / "signal_plot.html"
    success = plot_signals(store, signals_to_plot, out_file)
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())