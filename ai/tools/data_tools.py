# -*- coding: utf-8 -*-
"""
Agent-callable data tools built on top of deterministic V3 data engines.

These wrappers expose the existing DataProbe and Temporal Pattern Engine
through a simple tool contract:

* ``execute(params)`` takes one JSON-like dict.
* ``parameters_schema`` describes the accepted arguments.
* ``safe_execute(params)`` never raises across the tool boundary and returns
  ``{"status": "error", ...}`` on failure.

The repository's shared ``ai.tools.base.BaseTool`` contract is still being
landed. When it is present we subclass it directly; otherwise we provide a
small compatible fallback locally so this file remains usable and testable.
"""
from __future__ import annotations

import json
import logging
import math
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Callable, Optional

log = logging.getLogger(__name__)


def _json_safe(value: Any) -> Any:
    """Recursively coerce values into plain JSON-serializable data."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _json_safe(value.to_dict())
    if is_dataclass(value):
        return _json_safe(asdict(value))

    item = getattr(value, "item", None)
    if callable(item):
        try:
            return _json_safe(item())
        except Exception:
            pass

    tolist = getattr(value, "tolist", None)
    if callable(tolist):
        try:
            return _json_safe(tolist())
        except Exception:
            pass

    return str(value)


try:
    from .base import BaseTool  # type: ignore
except Exception:
    class BaseTool:  # type: ignore[override]
        """Fallback BaseTool until the shared contract lands in ai/tools/base.py."""

        name: str = "base-tool"
        description: str = ""
        parameters_schema: dict[str, Any] = {
            "type": "object",
            "properties": {},
            "additionalProperties": True,
        }

        def execute(self, params: dict[str, Any]) -> dict[str, Any]:
            raise NotImplementedError

        def ok(self, *, data: Any = None, message: str = "", artifacts: Any = None) -> dict[str, Any]:
            return {
                "status": "ok",
                "message": message,
                "data": _json_safe(data if data is not None else {}),
                "artifacts": _json_safe(artifacts if artifacts is not None else []),
            }

        def error(self, message: str, *, data: Any = None, artifacts: Any = None) -> dict[str, Any]:
            return {
                "status": "error",
                "message": message,
                "data": _json_safe(data if data is not None else {}),
                "artifacts": _json_safe(artifacts if artifacts is not None else []),
            }

        def safe_execute(self, params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
            try:
                result = self.execute(dict(params or {}))
                if not isinstance(result, dict):
                    return self.error(
                        f"{self.name}.execute() returned {type(result).__name__}, expected dict",
                    )
                result.setdefault("status", "ok")
                result.setdefault("message", "")
                result["data"] = _json_safe(result.get("data", {}))
                result.setdefault("artifacts", [])
                return result
            except Exception as exc:  # noqa: BLE001 - tool boundary guard by design
                log.exception("Tool '%s' failed", self.name)
                return self.error(f"{type(exc).__name__}: {exc}")


def _normalise_stats(raw: Any) -> list[str] | None:
    if raw is None:
        return None
    if isinstance(raw, str):
        stats = [part.strip() for part in raw.split(",") if part.strip()]
        return stats or None
    if isinstance(raw, list):
        stats = [str(part).strip() for part in raw if str(part).strip()]
        return stats or None
    raise ValueError("'stats' must be a comma string or list of strings")


def _normalise_time_window(raw: Any) -> tuple[float, float] | None:
    if raw is None:
        return None
    if not isinstance(raw, (list, tuple)) or len(raw) != 2:
        raise ValueError("'time_window' must be a two-item list or tuple")
    start = float(raw[0])
    end = float(raw[1])
    if end < start:
        raise ValueError("'time_window' end must be >= start")
    return (start, end)


def _load_jsonish(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _build_pattern_objects(raw_patterns: Any) -> list[Any] | None:
    if raw_patterns is None:
        return None
    if not isinstance(raw_patterns, list):
        raise ValueError("'extra_patterns' must be a list")

    from engines.pattern_extractor import CodePattern

    patterns: list[CodePattern] = []
    for item in raw_patterns:
        if isinstance(item, CodePattern):
            patterns.append(item)
            continue
        if isinstance(item, dict):
            patterns.append(CodePattern(**item))
            continue
        raise ValueError(
            "'extra_patterns' items must be CodePattern instances or plain dicts",
        )
    return patterns


def _serialise_tpe_result(result: Any) -> Any:
    if isinstance(result, dict):
        return _json_safe(result)

    patterns = getattr(result, "patterns", None)
    features = getattr(result, "features", None)
    evidence = getattr(result, "evidence", None)
    notes = getattr(result, "notes", None)
    if patterns is None and features is None and evidence is None:
        return _json_safe(result)

    payload: dict[str, Any] = {
        "patterns": [_json_safe(p) for p in list(patterns or [])],
        "features": {
            str(name): _json_safe(feature)
            for name, feature in dict(features or {}).items()
        },
        "evidence": [_json_safe(item) for item in list(evidence or [])],
        "unresolved_variables": sorted(str(v) for v in set(getattr(result, "unresolved_variables", set()))),
        "internal_only_variables": sorted(
            str(v) for v in set(getattr(result, "internal_only_variables", set()))
        ),
        "missing_can_signals": sorted(
            str(v) for v in set(getattr(result, "missing_can_signals", set()))
        ),
        "notes": [str(note) for note in list(notes or [])],
    }

    try:
        payload["triggered_count"] = int(getattr(result, "triggered_count"))
    except Exception:
        payload["triggered_count"] = sum(
            1 for item in payload["evidence"] if isinstance(item, dict) and item.get("verdict") == "triggered"
        )
    try:
        payload["has_triggers"] = bool(getattr(result, "has_triggers"))
    except Exception:
        payload["has_triggers"] = payload["triggered_count"] > 0

    expert_block = getattr(result, "to_expert_block", None)
    if callable(expert_block):
        try:
            payload["expert_block"] = str(expert_block())
        except Exception as exc:  # noqa: BLE001 - formatting must not break tool output
            payload["expert_block_error"] = f"{type(exc).__name__}: {exc}"

    return _json_safe(payload)


class QueryCanDataTool(BaseTool):
    """Agent-facing wrapper around :class:`engines.data_probe.DataProbe`."""

    name = "query_can_data"
    description = "Query recorded CAN/bag-derived data summaries via DataProbe"
    parameters_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "field": {"type": "string", "description": "Column name or arithmetic expression."},
            "table": {
                "type": "string",
                "enum": ["radar_objects", "radar_debug", "warning_events"],
                "default": "radar_objects",
            },
            "group_by": {"type": "string"},
            "filter": {"type": "string"},
            "stats": {
                "oneOf": [
                    {"type": "string"},
                    {"type": "array", "items": {"type": "string"}},
                ],
            },
            "max_rows": {"type": "integer", "minimum": 1, "default": 500000},
        },
        "required": ["field"],
        "additionalProperties": False,
    }

    def __init__(
        self,
        *,
        store: Any | None = None,
        windows: Optional[list[Any]] = None,
        probe: Any | None = None,
        probe_factory: Optional[Callable[[Any, list[Any]], Any]] = None,
    ) -> None:
        self._store = store
        self._windows = list(windows or [])
        self._probe = probe
        self._probe_factory = probe_factory

    def _get_probe(self) -> tuple[Any | None, str]:
        if self._probe is not None:
            return self._probe, "injected"
        if self._probe_factory is not None:
            return self._probe_factory(self._store, list(self._windows)), "factory"
        if self._store is None:
            return None, "missing"

        from engines.data_probe import DataProbe

        self._probe = DataProbe(self._store, windows=self._windows)
        return self._probe, "data-probe"

    def execute(self, params: dict[str, Any]) -> dict[str, Any]:
        field = str(params.get("field") or "").strip()
        if not field:
            return self.error("'field' is required")

        probe, probe_source = self._get_probe()
        if probe is None:
            return self.error(
                "no data store/probe available; inject store=... or probe=...",
                data={"probe_source": probe_source},
            )

        table = str(params.get("table") or "radar_objects")
        group_by = str(params.get("group_by") or "").strip() or None
        filter_expr = str(params.get("filter") or "").strip() or None
        stats = _normalise_stats(params.get("stats"))
        max_rows = int(params.get("max_rows", 500000))

        result = probe.query(
            field=field,
            table=table,
            group_by=group_by,
            filter=filter_expr,
            stats=stats,
            max_rows=max_rows,
        )
        if not isinstance(result, dict):
            return self.error(
                f"probe returned {type(result).__name__}, expected dict",
                data={"probe_source": probe_source, "result": result},
            )
        if result.get("error"):
            return self.error(
                str(result.get("error")),
                data={
                    "probe_source": probe_source,
                    "query": {
                        "field": field,
                        "table": table,
                        "group_by": group_by,
                        "filter": filter_expr,
                        "stats": stats,
                        "max_rows": max_rows,
                    },
                    "result": result,
                },
            )
        return self.ok(
            message=f"query_can_data:{table}.{field}",
            data={
                "probe_source": probe_source,
                "query": {
                    "field": field,
                    "table": table,
                    "group_by": group_by,
                    "filter": filter_expr,
                    "stats": stats,
                    "max_rows": max_rows,
                },
                "window_count": len(self._windows),
                "result": result,
            },
        )


class DetectTimePatternTool(BaseTool):
    """Agent-facing wrapper around :class:`engines.tpe.TemporalPatternEngine`."""

    name = "detect_time_pattern"
    description = "Run the deterministic Temporal Pattern Engine on recorded data"
    parameters_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "func_name": {"type": "string", "description": "Optional ADAS function filter."},
            "extra_patterns": {"type": "array", "items": {"type": "object"}},
            "state_transitions": {"type": "array", "items": {"type": "object"}},
            "time_window": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 2,
                "maxItems": 2,
            },
        },
        "additionalProperties": False,
    }

    def __init__(
        self,
        *,
        store: Any | None = None,
        engine: Any | None = None,
        engine_factory: Optional[Callable[..., Any]] = None,
        source_root: str | Path | None = None,
        cache_dir: str | Path | None = None,
        signal_mapping: Optional[dict[str, Any]] = None,
        variable_chains: Optional[dict[str, Any]] = None,
        output_mapping: Optional[dict[str, Any]] = None,
        output_aliases: Optional[dict[str, Any]] = None,
    ) -> None:
        self._store = store
        self._engine = engine
        self._engine_factory = engine_factory
        self._source_root = Path(source_root) if source_root is not None else None
        self._cache_dir = Path(cache_dir) if cache_dir is not None else None
        self._signal_mapping = signal_mapping
        self._variable_chains = variable_chains
        self._output_mapping = output_mapping
        self._output_aliases = output_aliases

    def _get_engine(self) -> tuple[Any | None, str]:
        if self._engine is not None:
            return self._engine, "injected"
        if self._engine_factory is not None:
            self._engine = self._engine_factory(
                source_root=self._source_root,
                cache_dir=self._cache_dir,
                signal_mapping=self._signal_mapping,
                variable_chains=self._variable_chains,
                output_mapping=self._output_mapping,
                output_aliases=self._output_aliases,
            )
            return self._engine, "factory"
        if self._source_root is None:
            return None, "missing"

        from engines.tpe import TemporalPatternEngine

        self._engine = TemporalPatternEngine(
            source_root=self._source_root,
            cache_dir=self._cache_dir,
            signal_mapping=self._signal_mapping,
            variable_chains=self._variable_chains,
            output_mapping=self._output_mapping,
            output_aliases=self._output_aliases,
        )
        return self._engine, "temporal-pattern-engine"

    def execute(self, params: dict[str, Any]) -> dict[str, Any]:
        if self._store is None:
            return self.error("no data store available; inject store=...")

        engine, engine_source = self._get_engine()
        if engine is None:
            return self.error(
                "no TemporalPatternEngine available; inject engine=... or source_root=...",
                data={"engine_source": engine_source},
            )

        func_name = str(params.get("func_name") or "").strip() or None
        extra_patterns = _build_pattern_objects(params.get("extra_patterns"))
        state_transitions = params.get("state_transitions")
        if state_transitions is not None and not isinstance(state_transitions, list):
            return self.error("'state_transitions' must be a list when provided")
        time_window = _normalise_time_window(params.get("time_window"))

        result = engine.run(
            self._store,
            func_name=func_name,
            extra_patterns=extra_patterns,
            state_transitions=state_transitions,
            time_window=time_window,
        )
        return self.ok(
            message=f"detect_time_pattern:{func_name or 'all'}",
            data={
                "engine_source": engine_source,
                "input": {
                    "func_name": func_name,
                    "extra_pattern_count": len(extra_patterns or []),
                    "state_transition_count": len(state_transitions or []),
                    "time_window": list(time_window) if time_window else None,
                },
                "result": _serialise_tpe_result(result),
            },
        )


class PlotSignalTool(BaseTool):
    """Return a structured plotting intent with optional lightweight preview data."""

    name = "plot_signal"
    description = "Describe a requested signal plot and optionally preview points"
    parameters_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "message_name": {"type": "string"},
            "signal_name": {"type": "string"},
            "topic": {"type": "string"},
            "field": {"type": "string"},
            "time_window": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 2,
                "maxItems": 2,
            },
            "preview_limit": {"type": "integer", "minimum": 1, "default": 20},
            "output_path": {"type": "string"},
            "title": {"type": "string"},
        },
        "additionalProperties": False,
    }

    def __init__(self, *, store: Any | None = None) -> None:
        self._store = store

    def _preview_can_signal(
        self,
        message_name: str,
        signal_name: str,
        preview_limit: int,
    ) -> dict[str, Any]:
        if self._store is None or not hasattr(self._store, "query_can_by_name"):
            return {"preview_status": "store_unavailable", "preview": None}

        frames = self._store.query_can_by_name(message_name) or []
        points: list[dict[str, Any]] = []
        for frame in frames:
            signals = _load_jsonish(frame.get("signals"))
            if not isinstance(signals, dict):
                signals = _load_jsonish(frame.get("signals_json"))
            if not isinstance(signals, dict) or signal_name not in signals:
                continue
            points.append({
                "timestamp": frame.get("timestamp"),
                "value": _json_safe(signals.get(signal_name)),
            })
            if len(points) >= preview_limit:
                break
        return {
            "preview_status": "available" if points else "empty",
            "preview": {
                "series_type": "can_signal",
                "frame_count": len(frames),
                "point_count": len(points),
                "points": points,
            },
        }

    def _preview_bag_field(
        self,
        topic: str,
        field: str,
        preview_limit: int,
    ) -> dict[str, Any]:
        if self._store is None or not hasattr(self._store, "query_bag_by_topic"):
            return {"preview_status": "store_unavailable", "preview": None}

        rows = self._store.query_bag_by_topic(topic) or []
        points: list[dict[str, Any]] = []
        for row in rows:
            fields = _load_jsonish(row.get("fields"))
            if not isinstance(fields, dict):
                fields = _load_jsonish(row.get("fields_json"))
            if not isinstance(fields, dict) or field not in fields:
                continue
            points.append({
                "timestamp_ns": row.get("timestamp_ns"),
                "value": _json_safe(fields.get(field)),
            })
            if len(points) >= preview_limit:
                break
        return {
            "preview_status": "available" if points else "empty",
            "preview": {
                "series_type": "bag_field",
                "row_count": len(rows),
                "point_count": len(points),
                "points": points,
            },
        }

    def execute(self, params: dict[str, Any]) -> dict[str, Any]:
        message_name = str(params.get("message_name") or "").strip()
        signal_name = str(params.get("signal_name") or "").strip()
        topic = str(params.get("topic") or "").strip()
        field = str(params.get("field") or "").strip()
        if not ((message_name and signal_name) or (topic and field)):
            return self.error(
                "provide either message_name+signal_name or topic+field",
            )

        preview_limit = int(params.get("preview_limit", 20))
        time_window = _normalise_time_window(params.get("time_window"))
        artifact = {
            "kind": "plot_signal",
            "backend": "deferred",
            "title": str(params.get("title") or "").strip() or None,
            "output_path": str(params.get("output_path") or "").strip() or None,
            "time_window": list(time_window) if time_window else None,
            "series": {
                "message_name": message_name or None,
                "signal_name": signal_name or None,
                "topic": topic or None,
                "field": field or None,
            },
        }

        if message_name and signal_name:
            preview_info = self._preview_can_signal(message_name, signal_name, preview_limit)
        else:
            preview_info = self._preview_bag_field(topic, field, preview_limit)

        return self.ok(
            message="plot_signal:deferred",
            data={
                "artifact": artifact,
                **preview_info,
            },
        )


__all__ = [
    "BaseTool",
    "QueryCanDataTool",
    "DetectTimePatternTool",
    "PlotSignalTool",
]
