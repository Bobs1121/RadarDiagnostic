# -*- coding: utf-8 -*-
"""
Agent-callable code tools for V3 PR3.

These wrappers expose deterministic CodeGraph / SignalBridge / RequirementTracer
capabilities behind a small ``BaseTool``-style contract. They are dependency
light by design:

- if ``ai.tools.base.BaseTool`` exists, these classes reuse it;
- otherwise they fall back to a local ``safe_execute()`` implementation that
  always returns JSON-serializable dicts and never raises across the tool
  boundary.
"""
from __future__ import annotations

import dataclasses
import logging
from pathlib import Path
from typing import Any

from core.materials import RequirementSpec, StructuredRequirementSet

from ..requirements.tracer import RequirementTracer

log = logging.getLogger(__name__)


def _to_jsonable(obj: Any) -> Any:
    """Normalize tool payloads into JSON-safe plain Python types."""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, Path):
        return str(obj)
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {k: _to_jsonable(v) for k, v in dataclasses.asdict(obj).items()}
    if isinstance(obj, dict):
        return {str(k): _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_to_jsonable(v) for v in obj]
    to_dict = getattr(obj, "to_dict", None)
    if callable(to_dict):
        return _to_jsonable(to_dict())
    return str(obj)


def _ok(tool_name: str, **payload: Any) -> dict[str, Any]:
    result = {"status": "ok", "tool": tool_name}
    result.update(_to_jsonable(payload))
    return result


def _error(tool_name: str, message: str, **payload: Any) -> dict[str, Any]:
    result = {"status": "error", "tool": tool_name, "message": message}
    result.update(_to_jsonable(payload))
    return result


def _normalize_module_like_result(result: Any) -> tuple[Any, str | None]:
    """Unwrap a BaseModule-style result into a plain payload."""
    if result is None:
        return None, "empty result"

    if hasattr(result, "ok") and hasattr(result, "data"):
        if not getattr(result, "ok", False):
            return None, str(getattr(result, "message", "") or "module query failed")
        payload = getattr(result, "data", {}) or {}
        if isinstance(payload, dict) and "data" in payload:
            return payload["data"], None
        return payload, None

    if isinstance(result, dict):
        if result.get("ok") is False or result.get("status") == "error":
            return None, str(result.get("message") or "module query failed")
        if "data" in result and len(result) == 1:
            return result["data"], None
        return result, None

    return result, None


def _coerce_requirement_spec(spec: RequirementSpec | dict[str, Any] | None) -> RequirementSpec | None:
    if spec is None:
        return None
    if isinstance(spec, RequirementSpec):
        return spec
    if not isinstance(spec, dict):
        return None

    data = dict(spec)
    if "requirement_id" not in data and "req_id" in data:
        data["requirement_id"] = data.pop("req_id")
    if "statement" not in data and "description" in data:
        data["statement"] = data["description"]
    return RequirementSpec.from_dict(data)


def _coerce_requirement_set(
    req_set: StructuredRequirementSet | dict[str, Any] | None,
) -> StructuredRequirementSet | None:
    if req_set is None:
        return None
    if isinstance(req_set, StructuredRequirementSet):
        return req_set
    if not isinstance(req_set, dict):
        return None

    if "requirements" in req_set:
        try:
            return StructuredRequirementSet.from_dict(req_set)
        except Exception:
            return None

    structured = StructuredRequirementSet(variant_id=str(req_set.get("variant_id", "")))
    for req_id, raw_spec in req_set.items():
        if req_id == "variant_id":
            continue
        spec = _coerce_requirement_spec(raw_spec)
        if spec is None:
            continue
        if not spec.requirement_id:
            spec.requirement_id = str(req_id)
        structured.add(spec)
    return structured if structured.requirements else None


try:  # pragma: no cover - exercised only when integration owner adds ai.tools.base
    from .base import BaseTool  # type: ignore
except Exception:  # noqa: BLE001 - optional integration boundary
    class BaseTool:
        """Fallback BaseTool contract for the current worktree."""

        name = "base-tool"
        description = ""
        parameters_schema: dict[str, Any] = {
            "type": "object",
            "properties": {},
            "additionalProperties": True,
        }

        def execute(self, params: dict[str, Any]) -> dict[str, Any]:
            raise NotImplementedError

        def safe_execute(self, params: Any = None) -> dict[str, Any]:
            try:
                if params is None:
                    params = {}
                if not isinstance(params, dict):
                    return _error(self.name, "params must be a dict")
                result = self.execute(dict(params))
            except Exception as exc:  # noqa: BLE001 - tool boundary guard
                log.exception("Tool '%s' failed", self.name)
                return _error(
                    self.name,
                    f"{type(exc).__name__}: {exc}",
                    error={"type": type(exc).__name__},
                )

            if not isinstance(result, dict):
                return _error(
                    self.name,
                    f"{self.name}.execute() returned {type(result).__name__}, expected dict",
                )

            result = _to_jsonable(result)
            result.setdefault("status", "ok")
            result.setdefault("tool", self.name)
            return result


class _ToolCompatMixin:
    """Accept either ``safe_execute({...})`` or keyword-style calls in tests."""

    def safe_execute(self, params: Any = None, **kwargs: Any) -> dict[str, Any]:
        if params is not None and not isinstance(params, dict):
            if kwargs:
                return _error(getattr(self, "name", "tool"), "params must be a dict")
            result = super().safe_execute(params)  # type: ignore[misc]
            if isinstance(result, dict):
                result.setdefault("tool", getattr(self, "name", "tool"))
            return result

        merged = {
            str(key): _to_jsonable(value)
            for key, value in dict(params or {}).items()
        }
        if kwargs:
            merged.update({
                str(key): _to_jsonable(value)
                for key, value in kwargs.items()
            })

        result = super().safe_execute(merged)  # type: ignore[misc]
        if isinstance(result, dict):
            result.setdefault("tool", getattr(self, "name", "tool"))
        return result


class _CodeBackendSupport:
    """Shared CodeGraph / CodeStructureModule resolution helpers."""

    def __init__(
        self,
        *,
        codegraph: Any | None = None,
        code_structure: Any | None = None,
        db_path: str | Path | None = None,
    ) -> None:
        self._codegraph = codegraph
        self._code_structure = code_structure
        self._db_path = Path(db_path) if db_path else None

    def _resolve_graph(self) -> tuple[Any | None, str]:
        if self._codegraph is not None:
            return self._codegraph, "injected"

        module = self._code_structure
        if module is not None:
            getter = getattr(module, "_get_graph", None)
            if callable(getter):
                try:
                    graph = getter()
                except Exception:
                    log.exception("code_structure._get_graph failed")
                else:
                    if graph is not None:
                        return graph, "code-structure-graph"

            if hasattr(module, "get_function_by_name"):
                return module, "code-structure-like"

        if self._db_path is None:
            return None, "missing"

        try:
            from ..codegraph.query import CodeGraph
        except Exception:  # noqa: BLE001 - optional dependency guard
            log.exception("CodeGraph import failed")
            return None, "import-error"

        graph = CodeGraph(self._db_path)
        if not getattr(graph, "is_available", True):
            return None, "db-missing"

        self._codegraph = graph
        return graph, "db-path"

    def _query_code(
        self,
        query_type: str,
        *,
        name: str,
        max_depth: int = 5,
    ) -> tuple[Any | None, str | None, str]:
        graph, source = self._resolve_graph()
        if graph is not None:
            method_map = {
                "function": "get_function_by_name",
                "callers": "get_callers",
                "callees": "get_callees",
                "call_chain": "get_call_chain",
                "signals_of": "get_signals_used_by",
                "vars_read": "get_variables_read_by",
                "vars_written": "get_variables_written_by",
            }
            method_name = method_map[query_type]
            method = getattr(graph, method_name, None)
            if not callable(method):
                return None, f"backend does not implement {method_name}", source
            try:
                if query_type == "call_chain":
                    return method(name, max_depth), None, source
                return method(name), None, source
            except Exception as exc:  # noqa: BLE001 - read-only backend guard
                return None, f"{method_name} failed: {type(exc).__name__}: {exc}", source

        module = self._code_structure
        if module is not None:
            runner = getattr(module, "safe_run", None) or getattr(module, "run", None)
            if callable(runner):
                try:
                    payload, error = _normalize_module_like_result(
                        runner(query_type=query_type, name=name, max_depth=max_depth)
                    )
                except Exception as exc:  # noqa: BLE001 - module boundary guard
                    return None, f"module query failed: {type(exc).__name__}: {exc}", "code-structure-module"
                return payload, error, "code-structure-module"

        return None, "no CodeGraph available; pass codegraph=..., code_structure=..., or db_path=<existing DB>", source


class FindCodeDefinitionTool(_CodeBackendSupport, _ToolCompatMixin, BaseTool):
    """Find a function definition from CodeGraph or a CodeStructureModule-like backend."""

    name = "find-code-definition"
    description = "Locate a function definition in the CodeGraph"
    # Kept for the legacy AgentLoop. Pi routes definition queries through
    # code-analyze so the source index and snapshot remain attached.
    expose_to_pi = False
    parameters_schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
        },
        "required": ["name"],
        "additionalProperties": False,
    }

    def __init__(
        self,
        *,
        codegraph: Any | None = None,
        code_structure: Any | None = None,
        db_path: str | Path | None = None,
    ) -> None:
        _CodeBackendSupport.__init__(
            self,
            codegraph=codegraph,
            code_structure=code_structure,
            db_path=db_path,
        )

    def execute(self, params: dict[str, Any]) -> dict[str, Any]:
        name = str(params.get("name", "")).strip()
        if not name:
            return _error(self.name, "missing required argument: name")

        definition, error, source = self._query_code("function", name=name)
        if error is not None:
            return _error(
                self.name,
                error,
                query={"name": name},
                backend={"available": False, "source": source},
            )

        definition = _to_jsonable(definition)
        return _ok(
            self.name,
            query={"name": name},
            backend={"available": True, "source": source},
            found=definition is not None,
            definition=definition,
        )


class ExtractASTDependencyTool(_CodeBackendSupport, _ToolCompatMixin, BaseTool):
    """Collect caller/callee/signal/variable relationships for a function."""

    name = "extract-ast-dependency"
    description = "Extract callers, callees, signals, and vars for a function"
    # Kept for the legacy AgentLoop; code-analyze is the canonical Pi entry.
    expose_to_pi = False
    parameters_schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "max_depth": {"type": "integer", "minimum": 1},
        },
        "required": ["name"],
        "additionalProperties": False,
    }

    def __init__(
        self,
        *,
        codegraph: Any | None = None,
        code_structure: Any | None = None,
        signal_bridge: Any | None = None,
        db_path: str | Path | None = None,
    ) -> None:
        _CodeBackendSupport.__init__(
            self,
            codegraph=codegraph,
            code_structure=code_structure,
            db_path=db_path,
        )
        self._signal_bridge = signal_bridge

    def execute(self, params: dict[str, Any]) -> dict[str, Any]:
        name = str(params.get("name", "")).strip()
        if not name:
            return _error(self.name, "missing required argument: name")

        max_depth = params.get("max_depth", 5)
        max_depth = max(1, int(max_depth))
        section_map = {
            "callers": "callers",
            "callees": "callees",
            "call_chain": "call_chain",
            "signals": "signals_of",
            "vars_read": "vars_read",
            "vars_written": "vars_written",
        }

        dependencies: dict[str, Any] = {}
        section_errors: dict[str, str] = {}
        backend_source = "missing"

        for section_name, query_type in section_map.items():
            payload, error, source = self._query_code(
                query_type,
                name=name,
                max_depth=max_depth,
            )
            backend_source = source if source != "missing" else backend_source
            dependencies[section_name] = _to_jsonable(payload or [])
            if error is not None:
                section_errors[section_name] = error

        function_outputs, bridge_meta = self._get_function_outputs(name)
        dependencies["function_outputs"] = function_outputs

        counts = {
            section_name: len(value) if isinstance(value, list) else 0
            for section_name, value in dependencies.items()
        }

        if len(section_errors) == len(section_map):
            return _error(
                self.name,
                "no AST dependency data available",
                query={"name": name, "max_depth": max_depth},
                backend={"available": False, "source": backend_source},
                dependencies=dependencies,
                counts=counts,
                section_errors=section_errors,
                signal_bridge=bridge_meta,
            )

        return _ok(
            self.name,
            query={"name": name, "max_depth": max_depth},
            backend={"available": True, "source": backend_source},
            dependencies=dependencies,
            counts=counts,
            section_errors=section_errors,
            signal_bridge=bridge_meta,
        )

    def _get_function_outputs(self, func_name: str) -> tuple[list[Any], dict[str, Any]]:
        if self._signal_bridge is None:
            return [], {"available": False, "source": "missing"}

        runner = getattr(self._signal_bridge, "safe_run", None) or getattr(self._signal_bridge, "run", None)
        if not callable(runner):
            return [], {
                "available": False,
                "source": "invalid",
                "message": "signal_bridge does not provide safe_run() or run()",
            }

        try:
            payload, error = _normalize_module_like_result(
                runner(mode="function-outputs", query=func_name)
            )
        except Exception as exc:  # noqa: BLE001 - bridge boundary guard
            return [], {
                "available": True,
                "source": "signal-bridge",
                "status": "error",
                "message": f"{type(exc).__name__}: {exc}",
            }

        if error is not None:
            return [], {
                "available": True,
                "source": "signal-bridge",
                "status": "error",
                "message": error,
            }

        payload = payload or {}
        if not isinstance(payload, dict):
            return _to_jsonable(payload), {
                "available": True,
                "source": "signal-bridge",
                "status": "ok",
            }

        return _to_jsonable(payload.get("matches", [])), {
            "available": True,
            "source": "signal-bridge",
            "status": "ok",
            "sources": _to_jsonable(payload.get("sources", {})),
        }


class TraceRequirementTool(_CodeBackendSupport, _ToolCompatMixin, BaseTool):
    """Trace a requirement spec or requirement set through RequirementTracer."""

    name = "trace-requirement"
    description = "Build deterministic requirement-to-code traceability"
    parameters_schema = {
        "type": "object",
        "properties": {
            "req_id": {"type": "string"},
            "spec": {"type": ["object", "null"]},
            "req_set": {"type": ["object", "null"]},
        },
        "additionalProperties": False,
    }

    def __init__(
        self,
        *,
        tracer: RequirementTracer | None = None,
        req_set: StructuredRequirementSet | dict[str, Any] | None = None,
        spec: RequirementSpec | dict[str, Any] | None = None,
        codegraph: Any | None = None,
        code_structure: Any | None = None,
        signal_mapping: dict[str, Any] | None = None,
        db_path: str | Path | None = None,
    ) -> None:
        _CodeBackendSupport.__init__(
            self,
            codegraph=codegraph,
            code_structure=code_structure,
            db_path=db_path,
        )
        self._tracer = tracer
        self._req_set = _coerce_requirement_set(req_set)
        self._spec = _coerce_requirement_spec(spec)
        self._signal_mapping = signal_mapping or {}

    def execute(self, params: dict[str, Any]) -> dict[str, Any]:
        resolved_spec = _coerce_requirement_spec(params.get("spec")) or self._spec
        resolved_req_set = _coerce_requirement_set(params.get("req_set")) or self._req_set
        req_id = str(params.get("req_id", "")).strip()

        tracer = self._build_tracer()

        if resolved_spec is not None:
            trace = tracer.trace(resolved_spec)
            return _ok(
                self.name,
                mode="trace-one",
                req_id=resolved_spec.requirement_id,
                trace=_to_jsonable(trace),
            )

        if req_id:
            if resolved_req_set is None:
                return _error(
                    self.name,
                    "req_id was provided but no requirement set is available",
                    req_id=req_id,
                )
            selected = resolved_req_set.get(req_id)
            if selected is None:
                return _error(
                    self.name,
                    f"requirement not found: {req_id}",
                    req_id=req_id,
                    available_req_ids=sorted(resolved_req_set.requirements),
                )
            trace = tracer.trace(selected)
            return _ok(
                self.name,
                mode="trace-one",
                req_id=req_id,
                trace=_to_jsonable(trace),
            )

        if resolved_req_set is not None:
            traces = tracer.trace_set(resolved_req_set)
            return _ok(
                self.name,
                mode="trace-set",
                variant_id=resolved_req_set.variant_id,
                trace_count=len(traces),
                traces=_to_jsonable(traces),
            )

        return _error(
            self.name,
            "no requirement input provided; pass spec=..., req_set=..., or req_id with an injected req_set",
        )

    def _build_tracer(self) -> RequirementTracer:
        if self._tracer is not None:
            return self._tracer
        graph, _ = self._resolve_graph()
        return RequirementTracer(
            codegraph=graph,
            signal_mapping=self._signal_mapping,
        )


__all__ = [
    "BaseTool",
    "FindCodeDefinitionTool",
    "ExtractASTDependencyTool",
    "TraceRequirementTool",
]
