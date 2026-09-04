# -*- coding: utf-8 -*-
"""
BSDDataBridgeModule (M9) — BSD signal matching + condition cross-validation.

Wraps the BSD pipeline scripts into one composable V3 module:

  1. Index     — map 32 BSD input signals to MF4 channel names
  2. Validate  — cross-validate PAD configs + conditions JSON against MF4 samples

Run standalone::

    python cli.py bsd-data-bridge --mode index --mf4-path record.MF4 --output-dir source_docs
    python cli.py bsd-data-bridge --mode validate --mf4-path record.MF4 --output-dir source_docs

or from Python::

    from ai.modules.bsd_data_bridge import BSDDataBridgeModule
    mod = BSDDataBridgeModule(mf4_path="record.MF4", output_dir="source_docs")
    res = mod.safe_run(mode="validate")
"""
from __future__ import annotations

import json
import logging
import math
import os
from pathlib import Path
from typing import Any

from .base import BaseModule, ModuleResult

log = logging.getLogger(__name__)

BSD_MODES: tuple[str, ...] = ("index", "validate", "summary")

# Canonical BSD signal list (derived from bsd_signal_index_mf4.py)
BSD_SIGNAL_LIST: list[dict[str, Any]] = [
    # Global inputs
    {"signal": "egoSpeed_vxvRef", "keyword": ["EgoSpeed", "vxvRef", "actualSpd", "vehSpd", "vehVel"], "category": "GLOBAL"},
    {"signal": "egoVehicleWidth", "keyword": ["VehicleWidth", "vehicleWidth"], "category": "GLOBAL"},
    {"signal": "rearBumper_dx", "keyword": ["rearBumper", "rearOverhang"], "category": "GLOBAL"},
    {"signal": "frontBumper_dx", "keyword": ["frontBumper", "frontOverhang"], "category": "GLOBAL"},
    {"signal": "bpillerDx", "keyword": ["bPillar", "BPillar"], "category": "GLOBAL_PARAMS"},
    {"signal": "driverIntentionKeeping", "keyword": ["laneKeeping", "IntentionLane"], "category": "GLOBAL"},
    {"signal": "parallelLanes_laneInfo", "keyword": ["parallelLanes", "laneCenter", "laneCenterDy"], "category": "GLOBAL"},
    {"signal": "objectLaneRelation_OLR", "keyword": ["OLR", "laneRelation", "laneProb", "EgoLaneProb", "ObjLaneProb", "laneIndex"], "category": "GLOBAL"},
    # Per-object signals
    {"signal": "obj_dx", "keyword": ["_dx", "AbsDx", "LongitudinalDx"], "category": "OBJECT"},
    {"signal": "obj_dy", "keyword": ["_dy", "AbsDy", "LateralDy"], "category": "OBJECT"},
    {"signal": "obj_vx", "keyword": ["_vx", "RelVx", "relativeVx"], "category": "OBJECT"},
    {"signal": "obj_vy", "keyword": ["_vy", "RelVy", "relativeVy"], "category": "OBJECT"},
    {"signal": "obj_yawAngle", "keyword": ["yawAngle", "YawAngle", "theta", "Theta"], "category": "OBJECT"},
    {"signal": "obj_existProb", "keyword": ["existProb", "ExistProb", "wExistProb"], "category": "OBJECT"},
    {"signal": "obj_obstacleProb", "keyword": ["obstacleProb", "ObstacleProb", "obstProb"], "category": "OBJECT"},
    {"signal": "obj_mobileProb", "keyword": ["mobileProb", "MobileProb"], "category": "OBJECT"},
    {"signal": "obj_stoppedProb", "keyword": ["stoppedProb", "StoppedProb"], "category": "OBJECT"},
    {"signal": "obj_vxOverGround", "keyword": ["vxOverGround", "vxGround", "OnGroundVx"], "category": "OBJECT"},
    {"signal": "obj_euclideanDist", "keyword": ["EuclidianDist", "euclidianDist", "EuclideanDist"], "category": "OBJECT"},
    {"signal": "obj_aliveCount", "keyword": ["AliveCnt", "aliveCount", "nCount", "m_age"], "category": "OBJECT"},
    {"signal": "obj_pTruck", "keyword": ["pTruck", "PTruck"], "category": "OBJECT"},
    {"signal": "obj_oncomingLane", "keyword": ["oncomingLane", "oncoming", "isOncoming"], "category": "OBJECT"},
    {"signal": "obj_laneIndex", "keyword": ["laneIndex", "LaneIndex"], "category": "OBJECT"},
    # Config parameters / PAD
    {"signal": "existProbThreshold_f", "keyword": ["ExistProbThreshold", "BSDLCAExistProbThreshold"], "category": "CONFIG"},
    {"signal": "existProbThresholdHysteresis_f", "keyword": ["ExistProbThresholdHyst", "BSDLCAExistProbThresholdHysteresis"], "category": "CONFIG"},
    {"signal": "minVxSuppressOn_F", "keyword": ["MinVxSuppressOn", "BSDLCA*MinVxSuppressOn"], "category": "CONFIG"},
    {"signal": "minVxSuppressOff_F", "keyword": ["MinVxSuppressOff", "BSDLCA*MinVxSuppressOff"], "category": "CONFIG"},
    # Output signals
    {"signal": "bsdWarnLValue", "keyword": ["bsdlcaWarnLValue", "BSD*WarnLValue", "BSD*WarnL"], "category": "OUTPUT"},
    {"signal": "bsdWarnRValue", "keyword": ["bsdlcaWarnRValue", "BSD*WarnRValue", "BSD*WarnR"], "category": "OUTPUT"},
    {"signal": "necessity", "keyword": ["necessityIntention", "necessityInten", "_m_necessity"], "category": "OUTPUT"},
    {"signal": "Blindness_st", "keyword": ["Blindness_st"], "category": "OUTPUT"},
    {"signal": "nfsigFCR_Blindness_Status_S", "keyword": ["nfsigFCR_Blindness_Status", "nfsigState_FCR_Blindness"], "category": "OUTPUT"},
]

# PAD config defaults (from gen5_bsd_signal_mapping.json)
DEFAULT_PAD_VALUES: dict[str, float] = {
    'BSDLCAIsoLineCOffset_F': 4.0,
    'BSDLCAIsoLineSlope_F': 0.075,
    'BSDLCAbPillarDx_F': 1.134,
    'BSDLCAMinVxSuppressOn_F': -4.0,
    'BSDLCAMinVxSuppressOff_F': 0.0,
    'BSDLCAMinVxEgo_Delta': -9.0,
    'BSDLCALyColl_F': 3.75,
    'BSDLCALyMax_F': 20.0,
    'BSDLCALongitudinalOffset_F': 2.0,
    'BSDLCAExistProbThreshold_f': 0.6,
    'BSDLCAExistProbThresholdHysteresis_f': 0.41,
    'BSDLCAExistProbCutoff_f': 0.3,
    'BSDLCAObjExistProbCutoff_f': 0.2,
}


def _load_json(path: Path) -> Any | None:
    """Load a JSON file, returning None on any failure."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        log.exception("Failed to load JSON: %s", path)
        return None


def _is_mdf_available() -> bool:
    """Check if asammdf is importable."""
    try:
        import asammdf  # noqa: F401
        return True
    except ImportError:
        return False


class BSDDataBridgeModule(BaseModule):
    """M9 — BSD signal matching + condition cross-validation."""

    name = "bsd-data-bridge"
    description = "BSD signal matching + condition cross-validation (M9)"

    def __init__(
        self,
        *,
        mf4_path: str | Path | None = None,
        cases_dir: str | Path | None = None,
        source_root: str | Path | None = None,
        output_dir: str | Path | None = None,
        pad_values: dict[str, float] | None = None,
    ) -> None:
        self._mf4_path = Path(mf4_path) if mf4_path else None
        self._cases_dir = Path(cases_dir) if cases_dir else None
        self._source_root = Path(source_root) if source_root else None
        self._output_dir = Path(output_dir) if output_dir else None
        self._pad_values = pad_values or dict(DEFAULT_PAD_VALUES)
        self._signal_index: dict[str, Any] | None = None
        self._dynamic_signals: dict[str, Any] | None = None
        self._conditions: dict[str, Any] | None = None

    # ── signal index (mode "index" / "summary") ───────────────────────

    def _index_signals(self) -> dict[str, Any]:
        """Map all 32 BSD input signals to actual MF4 channel names."""
        if self._signal_index is not None:
            return self._signal_index

        mf4_path_str = str(self._mf4_path) if self._mf4_path else None
        if not mf4_path_str or not os.path.isfile(mf4_path_str):
            raise FileNotFoundError(f"MF4 file not found: {mf4_path_str}")

        try:
            import asammdf
        except ImportError:
            raise ImportError(
                "asammdf is required for BSD signal indexing; "
                "install with `pip install asammdf`"
            )

        with asammdf.MDF(mf4_path_str) as mdf:
            all_channel_names = list(mdf.channels_db.keys())
            log.info("MF4: %d groups, %d unique channels", len(mdf.groups), len(all_channel_names))

            results: dict[str, Any] = {}
            for bs in BSD_SIGNAL_LIST:
                signal_name = bs["signal"]
                keywords = bs["keyword"]

                matches: list[str] = []
                for ch_name in all_channel_names:
                    ch_lower = ch_name.lower()
                    for kw in keywords:
                        if kw.lower() in ch_lower:
                            matches.append(ch_name)
                            break

                # Deduplicate preserving order
                seen: set[str] = set()
                unique_matches: list[str] = []
                for m in matches:
                    if m not in seen:
                        seen.add(m)
                        unique_matches.append(m)

                results[signal_name] = {
                    "category": bs["category"],
                    "keywords_tried": keywords,
                    "mf4_matches": unique_matches,
                    "found": len(unique_matches) > 0,
                    "match_count": len(unique_matches),
                }

        self._signal_index = results
        return results

    def _build_summary(self, signal_index: dict[str, Any]) -> dict[str, Any]:
        """Build a quick summary of BSD signal availability in an MF4 file."""
        categories = sorted(set(s["category"] for s in signal_index.values()))
        cat_counts: dict[str, dict[str, int]] = {}
        for cat in categories:
            cat_sigs = [s for s in signal_index.values() if s["category"] == cat]
            cat_counts[cat] = {
                "total": len(cat_sigs),
                "found": sum(1 for s in cat_sigs if s["found"]),
                "missing": sum(1 for s in cat_sigs if not s["found"]),
            }

        total_found = sum(1 for s in signal_index.values() if s["found"])
        total_missing = len(signal_index) - total_found

        sample_signals: list[dict[str, Any]] = []
        for sig_name, info in sorted(
            signal_index.items(), key=lambda x: x[1]["found"], reverse=True,
        )[:10]:
            sample_signals.append({
                "signal": sig_name,
                "found": info["found"],
                "matches": info["mf4_matches"][:3],
            })

        return {
            "mode": "summary",
            "total_signals": len(signal_index),
            "total_found": total_found,
            "total_missing": total_missing,
            "categories": cat_counts,
            "sample_signals": sample_signals,
        }

    # ── dynamic signal reading ────────────────────────────────────────

    @staticmethod
    def _read_signal(
        mdf: Any, sig_name: str, group: int, index: int,
    ) -> tuple[Any, Any, str]:
        """Read a signal via mdf.get(name, group=G, index=I)."""
        try:
            sig = mdf.get(sig_name, group=group, index=index)
            if sig is None:
                return None, None, ""
            unit = getattr(sig, "unit", "") or ""
            return sig.samples, sig.timestamps, unit
        except Exception:
            log.exception("Failed to read %s (group=%d, index=%d)", sig_name, group, index)
            return None, None, ""

    def _analyze_samples(self, samples: Any, unit: str) -> dict[str, Any]:
        """Analyze signal samples: count, unique values, non-zero stats."""
        if samples is None:
            return {"status": "ERROR_READING"}
        n = len(samples)
        if isinstance(samples, tuple):
            return {"status": "TUPLE_DATA", "sample_count": n}

        vals: list[float] = []
        for v in samples:
            try:
                f = float(v)
                if not math.isnan(f):
                    vals.append(f)
            except (ValueError, TypeError):
                continue

        unique_vals = sorted(set(vals))
        non_zero = [v for v in vals if v != 0]
        result: dict[str, Any] = {
            "status": "OK" if unique_vals and n > 0 else (
                "ALL_ZERO" if n > 0 else "NO_DATA"
            ),
            "sample_count": n,
            "unique_count": len(unique_vals),
            "unique_first20": unique_vals[:20],
            "non_zero_count": len(non_zero),
            "non_zero_pct": round(100.0 * len(non_zero) / max(n, 1), 1),
            "unit": unit,
        }
        if non_zero:
            result["non_zero_min"] = min(non_zero)
            result["non_zero_max"] = max(non_zero)
        return result

    def _read_dynamic_signals(self, mdf: Any) -> dict[str, Any]:
        """Scan MF4 for BSD output signals and read their dynamic data."""
        target_keywords = [
            "bsdlcaWarnLValue", "bsdlcaWarnRValue", "_Blindness_st",
            "necessityIntention", "existProb", "laneProb",
            "bsdLevel2Warn", "bsdHardSwitchStatus",
            "bsdlcaWarnLValuePre", "bsdlcaWarnRValuePre",
        ]

        cdb = mdf.channels_db
        bsd_signals: dict[str, list[tuple[int, int]]] = {}

        for name in cdb:
            lower = name.lower()
            for kw in target_keywords:
                if kw.lower() in lower:
                    occ = cdb.get(name)
                    if isinstance(occ, tuple):
                        occurrences: list[tuple[int, int]] = []
                        for t in occ:
                            if isinstance(t, tuple) and len(t) == 2 and t[0] > 0:
                                occurrences.append((t[0], t[1]))
                        if occurrences:
                            bsd_signals[name] = occurrences
                    break

        results: dict[str, Any] = {}
        for name, occurrences in bsd_signals.items():
            g, i = occurrences[0]
            samples, timestamps, unit = self._read_signal(mdf, name, g, i)
            stats = self._analyze_samples(samples, unit)

            if timestamps is not None:
                ts_list = list(timestamps) if hasattr(timestamps, "__iter__") else []
                if ts_list:
                    stats["time_range_s"] = [
                        round(float(ts_list[0]), 3),
                        round(float(ts_list[-1]), 3),
                    ]

            results[name] = {
                "read_from_group": g,
                "read_from_index": i,
                "total_occurrences": len(occurrences),
                "analysis": stats,
            }

        self._dynamic_signals = results
        return results

    # ── cross-validation (mode "validate") ────────────────────────────

    def _load_conditions(self) -> dict[str, Any]:
        """Load BSD_conditions.json from source_docs."""
        if self._conditions is not None:
            return self._conditions

        base_dir = str(Path(__file__).resolve().parents[2])
        conditions_path = os.path.join(base_dir, "source_docs", "BSD_conditions.json")
        data = _load_json(Path(conditions_path))
        if data is None:
            raise FileNotFoundError(f"BSD_conditions.json not found at {conditions_path}")

        self._conditions = {k: v for k, v in data.items()}
        return self._conditions

    def _load_mapping(self) -> dict[str, Any]:
        """Load gen5_bsd_signal_mapping.json from source_docs."""
        base_dir = str(Path(__file__).resolve().parents[2])
        mapping_path = os.path.join(base_dir, "source_docs", "gen5_bsd_signal_mapping.json")
        data = _load_json(Path(mapping_path))
        if data is None:
            log.warning("gen5_bsd_signal_mapping.json not found; PAD lookups may be incomplete")
            return {"mappings": []}
        return data

    @staticmethod
    def _build_signal_short_lookup(signals: dict[str, Any]) -> dict[str, dict[str, Any]]:
        """Build short-name signal lookup (last segment → analysis)."""
        sig_short: dict[str, Any] = {}
        for full_name, info in signals.items():
            parts = full_name.rsplit(".", 1)
            sname = parts[-1]
            if sname not in sig_short:
                sig_short[sname] = (
                    info.get("analysis", {}) if isinstance(info, dict) else {}
                )
        return sig_short

    def _validate_conditions(self) -> dict[str, Any]:
        """Cross-validate PAD configs + conditions JSON against MF4 signal data.

        BSD_conditions.json is structured by category (not step-number keyed):
          {"description": "...", "system_state": {...}, "object_selector": {
              "conditions": [{"condition": "...", "variable": "...", "threshold": "...", ...}]
          }, ...}

        This method iterates over all top-level keys that contain conditions
        and validates each one against MF4 data.
        """
        conditions = self._load_conditions()
        mapping = self._load_mapping()
        dynamic_signals = self._dynamic_signals or {}

        sig_short = self._build_signal_short_lookup(dynamic_signals)
        map_by_var: dict[str, list[str]] = {}
        for entry in mapping.get("mappings", []):
            var_name = entry.get("internal_var", "")
            can_sig = entry.get("can_signal", "")
            if var_name:
                map_by_var.setdefault(var_name, []).append(can_sig)

        validation_results: list[dict[str, Any]] = []
        total_conditions = 0

        for section_key, section_val in conditions.items():
            # Skip non-section keys (description, ego_speed_ranges, etc.)
            step_results: list[dict[str, Any]] = []

            # A section is a "conditions section" if it has a "conditions" key
            cond_list: list[dict[str, Any]] = []
            if isinstance(section_val, dict) and "conditions" in section_val:
                cond_list = section_val.get("conditions", [])
            elif isinstance(section_val, list):
                # Some sections may be a flat list of conditions (unlikely but handle)
                cond_list = section_val

            if not cond_list:
                continue

            for idx, cond in enumerate(cond_list):
                if not isinstance(cond, dict):
                    continue

                # Support both flat structure (ConditionExtractor output)
                # and step-number structure (legacy BSDLCA conditions format)
                cond_id = cond.get("id", f"{section_key}-{idx + 1}")
                desc_text = cond.get("description", cond.get("condition", ""))
                cond_type = cond.get("type", section_key)
                signal_name = cond.get("signal_name", cond.get("variable", ""))
                threshold = cond.get("threshold", "")
                short_sig = signal_name.rsplit(".", 1)[-1] if signal_name else ""

                # Check for PAD value — match by variable name (cond_type can also help)
                pad_match: str | None = None
                # First: try exact variable name
                for pname in self._pad_values:
                    if pname.lower() == short_sig.lower():
                        pad_match = str(self._pad_values[pname])
                        break
                # Second: try contains match
                if pad_match is None:
                    for pname in self._pad_values:
                        if short_sig and pname.lower() in short_sig.lower():
                            pad_match = str(self._pad_values[pname])
                            break

                analysis = sig_short.get(short_sig, {})
                sample_count = analysis.get("sample_count", 0)
                nz_count = analysis.get("non_zero_count", 0)
                status = analysis.get("status", "NO_DATA")

                triggered = (
                    "YES" if nz_count > 0
                    else ("NO (all zero)" if sample_count > 0 else "N/A")
                )

                if status in ("OK", "ALL_ZERO"):
                    ver_status = "VERIFIED"
                elif status == "NO_DATA":
                    ver_status = "NO DATA"
                else:
                    ver_status = f"SKIP ({status})"

                step_results.append({
                    "id": cond_id,
                    "description": desc_text,
                    "type": cond_type,
                    "variable": short_sig,
                    "threshold": threshold,
                    "pad_value": pad_match,
                    "can_signal": map_by_var.get(short_sig, [])[:3],
                    "sample_count": sample_count,
                    "non_zero_count": nz_count,
                    "triggered": triggered,
                    "verification": ver_status,
                })

            if step_results:
                validation_results.append({
                    "section": section_key,
                    "conditions": step_results,
                })
                total_conditions += len(step_results)

        verified = sum(
            1
            for sr in validation_results
            for c in sr["conditions"]
            if c["verification"] == "VERIFIED"
        )
        activated = sum(
            1
            for sr in validation_results
            for c in sr["conditions"]
            if c["non_zero_count"] > 0
        )
        no_data = total_conditions - verified

        return {
            "mode": "validate",
            "conditions": validation_results,
            "summary": {
                "total_conditions": total_conditions,
                "verified": verified,
                "verified_pct": round(100.0 * verified / max(total_conditions, 1), 1),
                "activated": activated,
                "constant_zero": verified - activated,
                "no_data": no_data,
            },
            "pad_values_used": self._pad_values,
            "dynamic_signals": dynamic_signals,
        }

    # ── BSD knowledge from condition files ────────────────────────────

    def get_bsd_knowledge(self) -> dict[str, Any]:
        """Return BSD signal knowledge extracted from condition files."""
        signal_knowledge: list[dict[str, Any]] = []
        for bs in BSD_SIGNAL_LIST:
            signal_knowledge.append({
                "signal": bs["signal"],
                "category": bs["category"],
                "keywords": bs["keyword"],
            })

        conditions: dict[str, Any] = {}
        try:
            conditions = self._load_conditions()
        except (FileNotFoundError, Exception):
            log.warning("Could not load conditions for knowledge extraction")

        return {
            "signals": signal_knowledge,
            "conditions": conditions,
            "pad_values": self._pad_values,
            "total_signals": len(signal_knowledge),
        }

    # ── result persistence ────────────────────────────────────────────

    def _save_result(self, filename: str, data: Any) -> str | None:
        """Save JSON data to output directory."""
        if not self._output_dir:
            return None
        try:
            self._output_dir.mkdir(parents=True, exist_ok=True)
            out_path = self._output_dir / filename
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            log.info("Saved %s (%d bytes)", out_path, out_path.stat().st_size)
            return str(out_path)
        except Exception:
            log.exception("Failed to save %s", filename)
            return None

    # ── main entry point ──────────────────────────────────────────────

    def run(self, *, mode: str, **kwargs: Any) -> ModuleResult:
        """Execute the BSD data bridge pipeline.

        Args:
            mode: One of "summary", "index", "validate".
            **kwargs: Additional arguments (ignored for known modes).

        Returns:
            ModuleResult with structured data.
        """
        if mode not in BSD_MODES:
            return ModuleResult.fail(
                f"unknown mode {mode!r}; choose one of {list(BSD_MODES)}",
                module=self.name,
            )

        if mode in ("summary", "index") and not self._mf4_path:
            return ModuleResult.fail(
                f"mode {mode!r} requires --mf4-path",
                module=self.name,
            )

        if not _is_mdf_available():
            return ModuleResult.fail(
                "asammdf is not installed; run `pip install asammdf`",
                module=self.name,
            )

        import asammdf  # noqa: F401  (already checked above)

        if mode == "summary":
            return self._run_summary()
        if mode == "index":
            return self._run_index()
        if mode == "validate":
            return self._run_validate()

        return ModuleResult.fail(f"unhandled mode {mode!r}", module=self.name)

    def _run_summary(self) -> ModuleResult:
        """Mode 'summary' — quick summary of BSD signals in an MF4 file."""
        try:
            signal_index = self._index_signals()
            summary = self._build_summary(signal_index)
            artifact = self._save_result("bsd_signal_index.json", signal_index)
            artifacts = [artifact] if artifact else []
            return ModuleResult.success(
                message="bsd-data-bridge:summary",
                module=self.name,
                artifacts=artifacts,
                **summary,
            )
        except Exception as exc:
            return ModuleResult.fail(
                f"index failed: {type(exc).__name__}: {exc}",
                module=self.name,
            )

    def _run_index(self) -> ModuleResult:
        """Mode 'index' — full BSD signal to MF4 channel mapping."""
        try:
            signal_index = self._index_signals()
            artifact = self._save_result("bsd_signal_index.json", signal_index)
            artifacts = [artifact] if artifact else []
            return ModuleResult.success(
                message="bsd-data-bridge:index",
                module=self.name,
                artifacts=artifacts,
                signal_index=signal_index,
            )
        except Exception as exc:
            return ModuleResult.fail(
                f"index failed: {type(exc).__name__}: {exc}",
                module=self.name,
            )

    def _run_validate(self) -> ModuleResult:
        """Mode 'validate' — cross-validate PAD configs + conditions against MF4 data."""
        mf4_path_str = str(self._mf4_path) if self._mf4_path else None
        if not mf4_path_str or not os.path.isfile(mf4_path_str):
            return ModuleResult.fail(
                f"MF4 file not found: {mf4_path_str}",
                module=self.name,
            )

        try:
            with asammdf.MDF(mf4_path_str) as mdf:
                dynamic_signals = self._read_dynamic_signals(mdf)

            sig_artifact = self._save_result(
                "bsd_dynamic_signals_full.json", dynamic_signals,
            )
            validation = self._validate_conditions()
            report_artifact = self._save_result(
                "bsd_cross_validation_report.json", validation,
            )

            artifacts = [a for a in [sig_artifact, report_artifact] if a]

            return ModuleResult.success(
                message="bsd-data-bridge:validate",
                module=self.name,
                artifacts=artifacts,
                **validation,
            )
        except Exception as exc:
            return ModuleResult.fail(
                f"validate failed: {type(exc).__name__}: {exc}",
                module=self.name,
            )

    # ── CLI ───────────────────────────────────────────────────────────

    @classmethod
    def register_cli(cls, subparsers: Any) -> Any:
        parser = super().register_cli(subparsers)
        parser.add_argument(
            "--mode",
            required=True,
            choices=list(BSD_MODES),
            help="BSD pipeline mode: summary, index, or validate.",
        )
        parser.add_argument(
            "--mf4-path", default=None,
            help="Path to the MF4 recording file.",
        )
        parser.add_argument(
            "--case-dir", default=None,
            help="Cases directory for loading test cases.",
        )
        parser.add_argument(
            "--source-root", default=None,
            help="Code source root (BYD_OVS_CB).",
        )
        parser.add_argument(
            "--output-dir", default=None,
            help="Directory to store result JSON files.",
        )
        return parser

    @classmethod
    def from_cli_args(cls, args: Any) -> "BSDDataBridgeModule":
        return cls(
            mf4_path=getattr(args, "mf4_path", None),
            cases_dir=getattr(args, "case_dir", None),
            source_root=getattr(args, "source_root", None),
            output_dir=getattr(args, "output_dir", None),
        )
