# -*- coding: utf-8 -*-
"""
Parameter analyzer: scan ADAS threshold parameters + what-if sensitivity.

This module is the **tune / verify** branch counterpart to the diagnose
pipeline. It is deliberately purely deterministic (regex scanning +
statistical comparison against recorded data), so results are reproducible
and explainable without hitting the LLM.

Three responsibilities:

1. **Inventory** — scan ``adasFunc.h`` / ``adasFunc.c`` / ``paraDefine.h``
   under ``config.paths.source_code`` and return one ``Parameter`` per
   threshold variable. Results are cached to
   ``source_docs/parameters.json`` (hash-keyed on the source files).

2. **Sensitivity** — given a parsed ``FrameStore`` + target function, for
   every parameter relevant to that function compute:

   * value range and histogram of the matching observed signal
     (e.g. ``fBsdActiveSpd`` ↔ ``car_spd``;
     ``fFctbObjWarningUpTTMY`` ↔ ``trc_N_ttm`` / ``ttc``);
   * number of crossings (how many times the observed signal crossed
     the threshold);
   * margin (|observed - threshold| distribution), which tells us how
     close we are to triggering — useful to answer "will a 10 % change
     flip behaviour?" without re-running the ECU.

3. **What-if** — given a proposed change ``{param: new_value}`` evaluate
   the delta number of crossings / time above the threshold / etc. This
   is the seed of an offline "should I bump ROI 0.5 m?" recommender.

The module never tries to **simulate the full ECU logic** — that would
require re-running the rule base end-to-end. Instead it gives the user a
principled starting point ("signal crosses threshold N times; change of
Δ would alter crossings to M") and defers the final judgement to the
expert panel (or the human reading the report).
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Iterable


# ── Category definition & regex matrix ─────────────────────────────────

CATEGORIES = (
    "ROI",        # distance polygon vertices, offsets
    "SPEED",      # ego-speed activation / deactivation band
    "OBJ_SPEED",  # target-speed enter/exit band
    "TTC",        # time-to-collision thresholds
    "TTM",        # time-to-maneuver thresholds
    "DDCI",       # DDCI / C-DDCI thresholds (longitudinal gap)
    "ANGLE",      # yaw / heading angle bounds
    "RATIO",      # overlap ratio / percentage
    "RADIUS",     # curb/curve radius bound
    "ACCEL",      # acceleration / deceleration threshold
    "HOLD",       # hold / keep-alive timers, debounce frames
    "DELAY",      # warn delay seconds
    "BRAKE_VAL",  # brake request value (only FCTB / RCTB)
    "FLAG",       # boolean enable / curb-dewarning switches
    "OTHER",
)

# Prefix ↔ ADAS function owner
_FUNC_PREFIXES = {
    "Bsd": "BSD", "Lca": "LCA", "Dow": "DOW", "Rcw": "RCW",
    "Rcta": "RCTA", "Rctb": "RCTB", "Fcta": "FCTA", "Fctb": "FCTB",
    "Fctx": "FCT_SHARED",   # fFctxCurbDewarningEnable — covers FCTA + FCTB
}

# Suffix / stem → category (ordered; first match wins)
_CATEGORY_RULES: list[tuple[str, str]] = [
    (r"RoiOffSet|OffSet[XY]\b", "ROI"),
    (r"Line(?:BSD|LCA|DOW|RCW)[A-Z]\w*", "ROI"),
    (r"Radius", "RADIUS"),
    (r"CurbRadius", "RADIUS"),
    (r"ActiveUpSpd|ActiveLowSpd|DeactiveUpSpd|DeactiveLowSpd", "SPEED"),
    (r"Detect(?:Up|Low)?Spd", "SPEED"),
    (r"ActiveSpd|DeactiveSpd|ActiveUpperSpd|DeactiveUpperSpd|ActiveMidSpd", "SPEED"),
    (r"WarnDelaySpd|WarnDeDelaySpd", "SPEED"),
    (r"ObjWarningSpd|ObjDeWarningSpd|ObjWarningUpSpd|ObjDeWarningUpSpd|"
     r"ObjWarningRelVx|ObjDeWarningRelVx|ObjKeySpd|StopSpd", "OBJ_SPEED"),
    (r"(?:ObjWarning|ObjDeWarning).*DDCI.*OffSet", "DDCI"),
    (r"(?:ObjWarning|ObjDeWarning).*BaseDDCI", "DDCI"),
    (r"YawAngle", "ANGLE"),
    (r"(?:ObjWarning|ObjDeWarning)TTC|ObjWarningTTC|ObjDeWarningTTC", "TTC"),
    (r"TTM\w*", "TTM"),
    (r"(?:ObjWarning|ObjDeWarning)?Ratio", "RATIO"),
    (r"DeAcc\b|WarningDeAcc", "ACCEL"),
    (r"BrakeValue|HoldValue|HighSpeedBrakeValue", "BRAKE_VAL"),
    (r"AEBActiveThresh|HoldTimeThresh", "HOLD"),
    (r"WarnDelay\b", "DELAY"),
]

# Which *observed* signal does a given category correspond to?
# Used to compute "number of crossings" against real data.
#
# Notes:
# - "car_spd" is tied to the egoCarInfo topic (m/s), we convert to km/h
#   before comparing against SPEED thresholds (code thresholds are km/h).
# - ``trc_*_vel_x`` tracks target velocity (m/s → km/h for OBJ_SPEED).
# - ``trc_*_ttc`` maps to TTC / TTM (both seconds).
# - ``trc_*_dist_x`` / ``_dist_y`` map to ROI distance thresholds.
_CATEGORY_OBSERVED: dict[str, tuple[str, float]] = {
    # category     → (signal_hint, conversion_to_match_unit)
    "SPEED":       ("car_spd_kmh", 1.0),
    "OBJ_SPEED":   ("trc_vel_kmh", 1.0),
    "TTC":         ("trc_ttc", 1.0),
    "TTM":         ("trc_ttc", 1.0),  # no separate TTM channel on BAG; reuse TTC
    "DDCI":        ("trc_ddci", 1.0),
    "ANGLE":       ("trc_yaw_angle", 1.0),
    "ROI":         ("trc_dist", 1.0),
    "RADIUS":      ("curve_radius", 1.0),
    "ACCEL":       ("trc_accel", 1.0),
    "RATIO":       (None, 1.0),       # cannot observe directly from BAG
    "HOLD":        (None, 1.0),
    "DELAY":       (None, 1.0),
    "BRAKE_VAL":   (None, 1.0),
    "FLAG":        (None, 1.0),
    "OTHER":       (None, 1.0),
}


# ── Data classes ───────────────────────────────────────────────────────

@dataclass
class Parameter:
    name: str
    func: str
    category: str
    value: float | None
    value_raw: str            # original token, e.g. "12.0f" or "-DISTANCEREAR"
    unit_hint: str            # derived from category ("km/h", "m", "s", ...)
    file: str                 # relative path
    line: int
    comment: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ParameterScanResult:
    source_hash: str
    parameters: list[Parameter] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "source_hash": self.source_hash,
            "count": len(self.parameters),
            "parameters": [p.to_dict() for p in self.parameters],
        }

    def by_function(self, func_name: str) -> list[Parameter]:
        fn = func_name.upper()
        return [p for p in self.parameters if p.func.upper() == fn]


@dataclass
class CrossingStats:
    crossings: int              # total up+down crossings
    crossings_up: int           # low→high
    crossings_down: int         # high→low
    frames_above: int           # frames with value > threshold
    frames_below: int           # frames with value < threshold
    frames_total: int
    min_margin: float | None    # min |observed - threshold|
    median_margin: float | None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SensitivityEntry:
    parameter: Parameter
    observed_signal: str
    observed_unit: str
    observed_range: tuple[float, float] | None
    stats: CrossingStats | None
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "parameter": self.parameter.to_dict(),
            "observed_signal": self.observed_signal,
            "observed_unit": self.observed_unit,
            "observed_range": self.observed_range,
            "stats": self.stats.to_dict() if self.stats else None,
            "note": self.note,
        }


# ── Scanner ────────────────────────────────────────────────────────────

_FLOAT_LITERAL_RE = re.compile(
    r"\b([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([^;]+?);"
)

# Boolean defines we care about (function enable / curb-dewarning flags)
_BOOL_DECL_RE = re.compile(
    r"\bbool\s+(b(?:Bsd|Lca|Dow|Rcw|Rcta|Rctb|Fcta|Fctb|Fctx)\w*)\s*=\s*(true|false)\s*;",
    re.IGNORECASE,
)

# Float declarations in adasFunc.c. Definitions look like:
#   float32 fBsdActiveSpd = 12.0f;
#   float32 fRcwObjKeySpd = 30.0f;
# We tolerate ``float`` / ``float32`` / ``f32`` / ``static const float``.
_FLOAT_DECL_RE = re.compile(
    r"\b(?:(?:static\s+)?(?:const\s+)?)?(?:float32|f32|float)\s+"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?P<value>[^;]+?);"
)


def _resolve_category(name: str) -> str:
    for pattern, category in _CATEGORY_RULES:
        if re.search(pattern, name):
            return category
    if name.startswith("b"):
        return "FLAG"
    return "OTHER"


def _resolve_func(name: str) -> str:
    stripped = name[1:] if name and name[0] in ("f", "b") else name
    for prefix, func in _FUNC_PREFIXES.items():
        if stripped.startswith(prefix):
            return func
    return ""


def _unit_for_category(cat: str) -> str:
    return {
        "SPEED": "km/h", "OBJ_SPEED": "km/h",
        "TTC": "s", "TTM": "s",
        "ROI": "m", "DDCI": "m", "RADIUS": "m",
        "ANGLE": "deg", "RATIO": "-",
        "ACCEL": "m/s^2", "HOLD": "s", "DELAY": "s",
        "BRAKE_VAL": "m/s^2", "FLAG": "bool",
    }.get(cat, "")


def _parse_numeric_token(raw: str) -> float | None:
    """Best-effort numeric extraction from tokens like '12.0f' or '-DISTANCEREAR + 0.1f'."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None

    # Strip trailing 'f'/'F' suffix, handle simple numeric literals
    m = re.match(r"^\s*([-+]?\d+(?:\.\d+)?)(?:[fF])?\s*$", s)
    if m:
        return float(m.group(1))

    # A single macro-only expression? leave unresolved
    if re.match(r"^[A-Z_][A-Z0-9_]*(?:\s*/\s*\d+)?\s*$", s):
        return None

    # Try first numeric literal inside the expression (best we can do without
    # macro expansion). We keep both the raw string and this best effort.
    m2 = re.search(r"([-+]?\d+(?:\.\d+)?)(?:[fF])?", s)
    if m2:
        try:
            return float(m2.group(1))
        except ValueError:
            return None
    return None


def scan_parameters(
    source_root: Path | str,
    cache_dir: Path | str | None = None,
    force: bool = False,
) -> ParameterScanResult:
    """Scan adasFunc.[hc] + paraDefine.h → cached ``ParameterScanResult``.

    The cache file is ``source_docs/parameters.json``; invalidates when the
    hash of the concatenated source changes.
    """
    source_root = Path(source_root)
    cache_path: Path | None = None
    if cache_dir is not None:
        cache_dir = Path(cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path = cache_dir / "parameters.json"

    targets: list[Path] = []
    for rel in (
        r"coem\GWM_B26\components\AswPerception\func\adasFunc.c",
        r"coem\GWM_B26\components\AswPerception\func\adasFunc.h",
        r"adas\symmetry\perception\include\paraDefine.h",
    ):
        p = source_root / rel
        if p.exists():
            targets.append(p)

    if not targets:
        return ParameterScanResult(source_hash="")

    hasher = hashlib.sha1()
    raw_bodies: list[tuple[Path, str]] = []
    for path in targets:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            text = ""
        raw_bodies.append((path, text))
        hasher.update(text.encode("utf-8", errors="replace"))
    src_hash = hasher.hexdigest()

    if cache_path and cache_path.exists() and not force:
        try:
            data = json.loads(cache_path.read_text(encoding="utf-8"))
            if data.get("source_hash") == src_hash:
                params = [Parameter(**p) for p in data.get("parameters", [])]
                return ParameterScanResult(source_hash=src_hash, parameters=params)
        except Exception:
            pass

    params: list[Parameter] = []

    for path, body in raw_bodies:
        rel = str(path.relative_to(source_root)) if path.is_relative_to(source_root) else path.name
        lines = body.split("\n")

        for idx, line in enumerate(lines):
            if not line.strip() or line.strip().startswith("//"):
                continue

            for m in _BOOL_DECL_RE.finditer(line):
                name = m.group(1)
                func = _resolve_func(name)
                if not func:
                    continue
                params.append(Parameter(
                    name=name,
                    func=func,
                    category="FLAG",
                    value=1.0 if m.group(2).lower() == "true" else 0.0,
                    value_raw=m.group(2),
                    unit_hint="bool",
                    file=rel,
                    line=idx + 1,
                    comment=_extract_inline_comment(line),
                ))

            for m in _FLOAT_DECL_RE.finditer(line):
                name = m.group("name")
                if not (name.startswith("f") or name.startswith("Line")):
                    continue
                func = _resolve_func(name) or _resolve_line_owner(name)
                if not func:
                    continue
                category = _resolve_category(name)
                raw_val = m.group("value").strip()
                params.append(Parameter(
                    name=name,
                    func=func,
                    category=category,
                    value=_parse_numeric_token(raw_val),
                    value_raw=raw_val,
                    unit_hint=_unit_for_category(category),
                    file=rel,
                    line=idx + 1,
                    comment=_extract_inline_comment(line),
                ))

    seen: dict[tuple[str, str], Parameter] = {}
    for p in params:
        key = (p.name, p.file)
        if key in seen and seen[key].value is not None:
            continue
        seen[key] = p
    params = list(seen.values())

    result = ParameterScanResult(source_hash=src_hash, parameters=params)
    if cache_path:
        try:
            cache_path.write_text(
                json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass
    return result


def _resolve_line_owner(name: str) -> str:
    """'LineBSD*' → BSD; 'LineRCW*' → RCW; 'LineDOW*' → DOW; 'LineLCA*' → LCA."""
    m = re.match(r"Line(BSD|LCA|DOW|RCW)[A-Z]\w*", name)
    return m.group(1) if m else ""


_INLINE_COMMENT_RE = re.compile(r"//\s*(.+?)$|/\*\s*(.+?)\s*\*/")


def _extract_inline_comment(line: str) -> str:
    m = _INLINE_COMMENT_RE.search(line)
    if not m:
        return ""
    txt = m.group(1) or m.group(2) or ""
    return txt.strip()[:200]


# ── Observed-signal matchers ───────────────────────────────────────────

def _collect_car_speeds_kmh(store) -> list[float]:
    """Pull ego ``car_spd`` (m/s) from every egoCarInfo topic and convert to km/h."""
    values: list[float] = []
    topics = [
        "/wf/ego_car_info/front_left/parsed",
        "/wf/ego_car_info/front_right/parsed",
        "/wf/ego_car_info/rear_left/parsed",
        "/wf/ego_car_info/rear_right/parsed",
    ]
    seen_ts: set[int] = set()
    for tp in topics:
        try:
            frames = store.query_bag_by_topic(tp)
        except Exception:
            frames = []
        for f in frames:
            ts = f.get("timestamp_ns", 0)
            if ts in seen_ts:
                continue
            seen_ts.add(ts)
            spd_ms = f.get("fields", {}).get("car_spd")
            if spd_ms is None:
                continue
            try:
                values.append(float(spd_ms) * 3.6)
            except (TypeError, ValueError):
                continue
    return values


def _collect_trc_field_kmh(store, fields: Iterable[str], kmh: bool) -> list[float]:
    """Collect per-object field values. ``kmh=True`` converts m/s → km/h."""
    values: list[float] = []
    topics = [
        "/wf/ego_car_info/front_left/parsed",
        "/wf/ego_car_info/front_right/parsed",
        "/wf/ego_car_info/rear_left/parsed",
        "/wf/ego_car_info/rear_right/parsed",
    ]
    for tp in topics:
        try:
            frames = store.query_bag_by_topic(tp)
        except Exception:
            frames = []
        for f in frames:
            flds = f.get("fields", {}) or {}
            for fld in fields:
                v = flds.get(fld)
                if v is None:
                    continue
                try:
                    fv = float(v)
                except (TypeError, ValueError):
                    continue
                if kmh:
                    fv *= 3.6
                values.append(fv)
    return values


def _observed_values_for(store, category: str) -> tuple[list[float], str, str]:
    """Return (values, signal_label, unit) for a parameter category."""
    if category == "SPEED":
        return _collect_car_speeds_kmh(store), "car_spd (ego)", "km/h"

    if category == "OBJ_SPEED":
        flds = [f"trc_{i}_vel_x" for i in range(4)]
        return _collect_trc_field_kmh(store, flds, kmh=True), "trc_*_vel_x", "km/h"

    if category in ("TTC", "TTM"):
        flds = [f"trc_{i}_ttc" for i in range(4)]
        return _collect_trc_field_kmh(store, flds, kmh=False), "trc_*_ttc", "s"

    if category == "ROI":
        flds: list[str] = []
        for i in range(4):
            flds.extend([f"trc_{i}_dist_x", f"trc_{i}_dist_y"])
        return _collect_trc_field_kmh(store, flds, kmh=False), "trc_*_dist_{x,y}", "m"

    if category == "DDCI":
        flds = [f"trc_{i}_ddci" for i in range(4)]
        return _collect_trc_field_kmh(store, flds, kmh=False), "trc_*_ddci", "m"

    return [], "", ""


# ── Crossings / margin computation ─────────────────────────────────────

def _compute_crossings(values: list[float], threshold: float) -> CrossingStats:
    above = 0
    below = 0
    up = 0
    down = 0
    prev: float | None = None
    margins: list[float] = []
    for v in values:
        if v > threshold:
            above += 1
        elif v < threshold:
            below += 1
        if prev is not None:
            if prev < threshold <= v:
                up += 1
            elif prev >= threshold > v:
                down += 1
        margins.append(abs(v - threshold))
        prev = v
    margins.sort()
    n = len(margins)
    return CrossingStats(
        crossings=up + down,
        crossings_up=up,
        crossings_down=down,
        frames_above=above,
        frames_below=below,
        frames_total=len(values),
        min_margin=margins[0] if margins else None,
        median_margin=margins[n // 2] if n else None,
    )


# ── Top-level public API ───────────────────────────────────────────────

@dataclass
class SensitivityReport:
    func: str
    total_parameters: int
    parameters_analyzed: int
    entries: list[SensitivityEntry]
    uncovered_categories: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "func": self.func,
            "total_parameters": self.total_parameters,
            "parameters_analyzed": self.parameters_analyzed,
            "entries": [e.to_dict() for e in self.entries],
            "uncovered_categories": self.uncovered_categories,
        }


def analyze_sensitivity(
    source_root: Path | str,
    cache_dir: Path | str,
    store,
    func_name: str,
    focus_categories: Iterable[str] | None = None,
) -> SensitivityReport:
    """Scan parameters and compare against observed data in ``store``.

    Returns an entry per parameter that has a matching observable signal
    channel. Parameters whose category is ``FLAG`` / ``HOLD`` / ``DELAY``
    are recorded but marked "cannot be directly observed".
    """
    scan = scan_parameters(source_root, cache_dir)
    params = scan.by_function(func_name) + scan.by_function("FCT_SHARED")

    if focus_categories:
        focus_set = {c.upper() for c in focus_categories}
        params = [p for p in params if p.category in focus_set] or params

    cache_by_category: dict[str, tuple[list[float], str, str]] = {}
    entries: list[SensitivityEntry] = []
    uncovered: set[str] = set()

    for param in params:
        cat = param.category
        if cat not in cache_by_category:
            cache_by_category[cat] = _observed_values_for(store, cat)
        values, sig_label, unit = cache_by_category[cat]

        if not sig_label:
            uncovered.add(cat)
            entries.append(SensitivityEntry(
                parameter=param, observed_signal="",
                observed_unit="",
                observed_range=None,
                stats=None,
                note=f"类别 {cat}: 无可直接观测的信号，调优依赖专家判断。",
            ))
            continue

        if not values or param.value is None:
            entries.append(SensitivityEntry(
                parameter=param, observed_signal=sig_label,
                observed_unit=unit,
                observed_range=None,
                stats=None,
                note=("参数值无法解析" if param.value is None
                      else f"未在本次录制中找到 {sig_label} 数据"),
            ))
            continue

        stats = _compute_crossings(values, float(param.value))
        entries.append(SensitivityEntry(
            parameter=param,
            observed_signal=sig_label,
            observed_unit=unit,
            observed_range=(round(min(values), 3), round(max(values), 3)),
            stats=stats,
        ))

    return SensitivityReport(
        func=func_name.upper(),
        total_parameters=len(params),
        parameters_analyzed=sum(1 for e in entries if e.stats),
        entries=entries,
        uncovered_categories=sorted(uncovered),
    )


# ── What-if (proposed-value deltas) ────────────────────────────────────

@dataclass
class WhatIfEntry:
    parameter_name: str
    category: str
    current_value: float
    proposed_value: float
    current_crossings: int
    proposed_crossings: int
    delta_crossings: int
    current_frames_above: int
    proposed_frames_above: int
    delta_frames_above: int

    def to_dict(self) -> dict:
        return asdict(self)


def what_if(
    sensitivity: SensitivityReport,
    proposals: dict[str, float],
    store=None,
) -> list[WhatIfEntry]:
    """Re-evaluate crossings at the proposed values.

    ``proposals`` maps parameter name → new numeric threshold (same unit as
    the parameter). Unknown parameter names are silently ignored.
    """
    out: list[WhatIfEntry] = []
    if not proposals:
        return out

    by_name = {e.parameter.name: e for e in sensitivity.entries}
    for name, new_val in proposals.items():
        entry = by_name.get(name)
        if not entry or not entry.stats:
            continue
        observed = None
        if store is not None:
            observed, _, _ = _observed_values_for(store, entry.parameter.category)
        if observed is None:
            observed, _, _ = _observed_values_for(None, entry.parameter.category)
        if not observed:
            continue

        new_stats = _compute_crossings(observed, float(new_val))
        cur_stats = entry.stats
        out.append(WhatIfEntry(
            parameter_name=name,
            category=entry.parameter.category,
            current_value=float(entry.parameter.value or 0),
            proposed_value=float(new_val),
            current_crossings=cur_stats.crossings,
            proposed_crossings=new_stats.crossings,
            delta_crossings=new_stats.crossings - cur_stats.crossings,
            current_frames_above=cur_stats.frames_above,
            proposed_frames_above=new_stats.frames_above,
            delta_frames_above=new_stats.frames_above - cur_stats.frames_above,
        ))
    return out


# ── Markdown rendering ─────────────────────────────────────────────────

def render_sensitivity_markdown(
    report: SensitivityReport,
    max_rows_per_cat: int = 8,
) -> str:
    """Produce a human-readable markdown digest of the report."""
    if not report.entries:
        return f"(无法扫描到 {report.func} 的任何参数)"

    lines: list[str] = []
    lines.append(
        f"### 参数敏感性分析 · {report.func} "
        f"(总参数 {report.total_parameters}, "
        f"可观测 {report.parameters_analyzed})"
    )
    if report.uncovered_categories:
        lines.append(
            "- 以下类别无可直接观测的信号，需要专家人工判断："
            + ", ".join(report.uncovered_categories)
        )

    by_cat: dict[str, list[SensitivityEntry]] = {}
    for e in report.entries:
        by_cat.setdefault(e.parameter.category, []).append(e)

    category_order = [c for c in CATEGORIES if c in by_cat]
    for cat in category_order:
        entries = by_cat[cat]
        entries_with_stats = [e for e in entries if e.stats]
        entries_with_stats.sort(
            key=lambda e: (e.stats.min_margin if e.stats else 9e9)
        )
        head = entries_with_stats[:max_rows_per_cat] or entries[:max_rows_per_cat]
        lines.append(f"\n#### [{cat}] ({len(entries)} 参数)")

        if not head[0].stats:
            for e in head:
                lines.append(
                    f"- `{e.parameter.name}` "
                    f"= {e.parameter.value_raw} "
                    f"(未做数值对齐) — {e.note}"
                )
            continue

        lines.append(
            "| 参数 | 当前值 | 观测信号范围 | 穿越次数 | frames 超/欠 | min |Δ| | 注解 |"
        )
        lines.append("|------|--------|--------------|---------|--------------|---------|------|")
        for e in head:
            if not e.stats:
                lines.append(
                    f"| `{e.parameter.name}` "
                    f"| {_fmt_value(e.parameter.value, e.parameter.unit_hint)} "
                    f"| — | — | — | — | {e.note} |"
                )
                continue
            obs_min, obs_max = e.observed_range or (None, None)
            obs_text = (f"[{obs_min:.2f}, {obs_max:.2f}] {e.observed_unit}"
                        if obs_min is not None else "无")
            min_margin = (f"{e.stats.min_margin:.3f}"
                          if e.stats.min_margin is not None else "—")
            note_parts: list[str] = []
            if e.stats.crossings > 0:
                note_parts.append("有穿越")
            elif e.stats.frames_above == 0 and e.stats.frames_below > 0:
                note_parts.append("恒在阈值之下")
            elif e.stats.frames_below == 0 and e.stats.frames_above > 0:
                note_parts.append("恒在阈值之上")
            if e.stats.min_margin is not None and e.stats.min_margin < 1.0:
                note_parts.append("接近阈值")
            note = " / ".join(note_parts) or "远离阈值"
            lines.append(
                f"| `{e.parameter.name}` "
                f"| {_fmt_value(e.parameter.value, e.parameter.unit_hint)} "
                f"| {obs_text} "
                f"| {e.stats.crossings} "
                f"| {e.stats.frames_above}/{e.stats.frames_below}/{e.stats.frames_total} "
                f"| {min_margin} "
                f"| {note} |"
            )
    return "\n".join(lines)


def render_what_if_markdown(entries: list[WhatIfEntry]) -> str:
    if not entries:
        return ""
    lines = ["### What-if 阈值调整影响"]
    lines.append("| 参数 | 类别 | 当前→建议 | 穿越次数 Δ | 超阈值帧 Δ |")
    lines.append("|------|------|----------|-----------|-----------|")
    for e in entries:
        lines.append(
            f"| `{e.parameter_name}` "
            f"| {e.category} "
            f"| {e.current_value} → {e.proposed_value} "
            f"| {e.current_crossings} → {e.proposed_crossings} "
            f"({e.delta_crossings:+d}) "
            f"| {e.current_frames_above} → {e.proposed_frames_above} "
            f"({e.delta_frames_above:+d}) |"
        )
    return "\n".join(lines)


def _fmt_value(v: float | None, unit: str) -> str:
    if v is None:
        return "—"
    if abs(v) >= 100:
        return f"{v:.1f} {unit}".strip()
    if abs(v) >= 1:
        return f"{v:.3f} {unit}".strip()
    return f"{v:.4f} {unit}".strip()


__all__ = [
    "CATEGORIES",
    "CrossingStats",
    "Parameter",
    "ParameterScanResult",
    "SensitivityEntry",
    "SensitivityReport",
    "WhatIfEntry",
    "analyze_sensitivity",
    "render_sensitivity_markdown",
    "render_what_if_markdown",
    "scan_parameters",
    "what_if",
]
