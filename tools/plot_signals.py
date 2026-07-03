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
        print("No data available to plot.")
        return False

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
        print("No signals identified to plot.")
        return 1

    out_file = args.case_dir / "signal_plot.html"
    success = plot_signals(store, signals_to_plot, out_file)
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())