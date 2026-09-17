# -*- coding: utf-8 -*-
"""Pi's single JSON boundary for radarAnalyze capabilities.

The generated TypeScript extension is intentionally thin.  It calls this
module with ``--name`` and ``--params``; this bridge then dispatches to either
the existing ``BaseTool`` registry or a registered leaf ``BaseModule`` adapter.
This keeps Pi's tool protocol, approval gate, and JSON envelope in one place.

The bridge never grants side-effect permission by default.  A future
supervisor may call :func:`invoke_capability` with ``allow_execution=True``
after a user approval artifact has been created; the Pi extension itself never
passes that flag.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

from ai.tools import TOOL_REGISTRY
from ai.capability.module_bridge import (
    _DEFAULT_EXCLUDED_MODULES,
    available_module_tools,
    build_module_tool_registry,
)
from ai.capability.tool_bridge import available_tools, invoke_tool

log = logging.getLogger(__name__)

_ANALYSIS_RUN_BOUND_CAPABILITIES = {
    "analysis-run-read",
    "analysis-run-update",
    "analysis-step-record",
    "analysis-claim-append",
    "analysis-hypothesis-record",
    "debug-experiment-record",
    "analysis-user-observation",
}


def _bind_current_analysis_run(
    params: dict[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    """Bind Pi ledger tools to the active durable run, rejecting run/path overrides."""
    run_id = str(os.environ.get("CR60_PI_ANALYSIS_RUN_ID", "") or "").strip()
    ledger_root = str(os.environ.get("CR60_PI_ANALYSIS_LEDGER_ROOT", "") or "").strip()
    if not run_id or not ledger_root:
        return None, "Pi ledger tool requires an active AnalysisRun binding"

    requested_run_id = str(params.get("run_id") or "").strip()
    if requested_run_id and requested_run_id != run_id:
        return None, "run_id conflicts with the current Pi AnalysisRun binding"

    requested_root = str(params.get("ledger_root") or "").strip()
    if requested_root:
        expected = os.path.normcase(os.path.realpath(os.path.expanduser(ledger_root)))
        supplied = os.path.normcase(os.path.realpath(os.path.expanduser(requested_root)))
        if supplied != expected:
            return None, "ledger_root conflicts with the current Pi AnalysisRun binding"

    bound = dict(params)
    bound["run_id"] = run_id
    bound["ledger_root"] = ledger_root
    return bound, None


def available_capabilities() -> dict[str, dict[str, Any]]:
    """Return the Pi-visible capability catalog without instantiation."""
    result: dict[str, dict[str, Any]] = {}
    for name, item in available_module_tools().items():
        if item.get("expose_to_pi", True):
            result[name] = {**item, "kind": "module", "expose_to_pi": True}
    for name, item in available_tools().items():
        cls = TOOL_REGISTRY.get(name)
        if cls is not None and not bool(getattr(cls, "expose_to_pi", True)):
            continue
        if name not in result:
            result[name] = {**item, "kind": "tool", "expose_to_pi": True}
    return dict(sorted(result.items()))


def _error(message: str, *, data: Any = None) -> dict[str, Any]:
    return {
        "status": "error",
        "message": str(message),
        "data": data if isinstance(data, (dict, list)) else ({} if data is None else {"value": data}),
        "artifacts": [],
    }


def _load_bound_code_context() -> tuple[dict[str, Any] | None, Path | None, str | None]:
    path_text = str(os.environ.get("CR60_PI_CODE_CONTEXT_PATH", "") or "").strip()
    if not path_text:
        return None, None, None
    expected_hash = str(os.environ.get("CR60_PI_CODE_CONTEXT_SHA256", "") or "").strip().lower()
    if not expected_hash:
        return None, None, "bound code-context artifact hash is missing"
    path = Path(path_text).expanduser().resolve()
    if not path.is_file():
        return None, None, "bound code-context artifact is unavailable"
    try:
        context_bytes = path.read_bytes()
        payload = json.loads(context_bytes.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return None, None, f"bound code-context artifact cannot be read: {type(exc).__name__}"
    if hashlib.sha256(context_bytes).hexdigest() != expected_hash:
        return None, None, "bound code-context artifact hash changed"
    if not isinstance(payload, dict) or payload.get("schema_version") != "code-context.v1":
        return None, None, "bound code-context artifact schema is invalid"
    source = payload.get("source_context") if isinstance(payload.get("source_context"), dict) else {}
    artifacts = payload.get("artifacts") if isinstance(payload.get("artifacts"), dict) else {}
    if str(source.get("source_root", "") or "") != str(os.environ.get("CR60_PI_SOURCE_ROOT", "") or ""):
        try:
            same_root = Path(str(source.get("source_root", ""))).expanduser().resolve() == Path(
                str(os.environ.get("CR60_PI_SOURCE_ROOT", ""))
            ).expanduser().resolve()
        except (OSError, RuntimeError, TypeError, ValueError):
            same_root = False
        if not same_root:
            return None, None, "bound code-context source root changed"
    if str(source.get("snapshot_hash", "") or "") != str(os.environ.get("CR60_PI_SOURCE_SNAPSHOT_HASH", "") or ""):
        return None, None, "bound code-context source snapshot changed"
    expected_index_path = str(os.environ.get("CR60_PI_CODE_INDEX_PATH", "") or "").strip()
    expected_index_hash = str(os.environ.get("CR60_PI_CODE_INDEX_SHA256", "") or "").strip().lower()
    context_index_path = str(artifacts.get("code_index", "") or "").strip()
    context_index_hash = str(artifacts.get("code_index_sha256", "") or "").strip().lower()
    try:
        same_index_path = bool(expected_index_path and context_index_path) and (
            Path(expected_index_path).expanduser().resolve() == Path(context_index_path).expanduser().resolve()
        )
    except (OSError, RuntimeError, TypeError, ValueError):
        same_index_path = False
    if not same_index_path or not expected_index_hash or context_index_hash != expected_index_hash:
        return None, None, "bound code-context index reference changed"
    for env_name, field in (("CR60_PI_PROJECT_ID", "project_id"), ("CR60_PI_VARIANT_ID", "variant_id")):
        expected = str(os.environ.get(env_name, "") or "")
        actual = str(source.get(field, "") or "")
        if expected and actual and expected != actual:
            return None, None, f"bound code-context {field} changed"
    return payload, path, None


def _bind_current_code_context(params: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    path_text = str(os.environ.get("CR60_PI_CODE_CONTEXT_PATH", "") or "").strip()
    if not path_text:
        return dict(params), None
    _, bound_path, error = _load_bound_code_context()
    if error:
        return None, error
    assert bound_path is not None
    bound = dict(params)
    explicit_path = str(bound.get("context_path", "") or "").strip()
    if explicit_path:
        try:
            if Path(explicit_path).expanduser().resolve() != bound_path:
                return None, "requested context_path conflicts with PiRunContext"
        except (OSError, RuntimeError, TypeError, ValueError):
            return None, "requested context_path is invalid"
    bound["context_path"] = str(bound_path)
    return bound, None


def _bind_current_event_code_path(params: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    bound, error = _bind_current_code_context(params)
    if error:
        return None, error
    bound = bound or {}
    expected_index_path = str(os.environ.get("CR60_PI_CODE_INDEX_PATH", "") or "").strip()
    requested_index_path = str(bound.get("code_index_path", "") or "").strip()
    if requested_index_path:
        try:
            if not expected_index_path or Path(requested_index_path).expanduser().resolve() != Path(expected_index_path).expanduser().resolve():
                return None, "requested code_index_path conflicts with PiRunContext"
        except (OSError, RuntimeError, TypeError, ValueError):
            return None, "requested code_index_path is invalid"
        # Keep the context loader as the canonical route so enclosing identity
        # is preserved in the derived event path.
        bound.pop("code_index_path", None)
    expected_root = str(os.environ.get("CR60_PI_SOURCE_ROOT", "") or "").strip()
    requested_root = str(bound.get("source_root", "") or "").strip()
    if requested_root and expected_root:
        try:
            if Path(requested_root).expanduser().resolve() != Path(expected_root).expanduser().resolve():
                return None, "requested source_root conflicts with PiRunContext"
        except (OSError, RuntimeError, TypeError, ValueError):
            return None, "requested source_root is invalid"
    if expected_root:
        bound["source_root"] = expected_root
    return bound, None


def _bind_current_code_index(params: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    """Inject and verify the source index bound by the parent Pi turn."""
    path_text = str(os.environ.get("CR60_PI_CODE_INDEX_PATH", "") or "").strip()
    if not path_text:
        return dict(params), None
    expected_hash = str(os.environ.get("CR60_PI_CODE_INDEX_SHA256", "") or "").strip().lower()
    expected_root = str(os.environ.get("CR60_PI_SOURCE_ROOT", "") or "").strip()
    expected_snapshot = str(os.environ.get("CR60_PI_SOURCE_SNAPSHOT_HASH", "") or "").strip()
    if not expected_hash or not expected_root or not expected_snapshot:
        return None, "bound source code-index identity is incomplete"
    _, _, context_error = _load_bound_code_context()
    if context_error:
        return None, context_error

    path = Path(path_text).expanduser().resolve()
    if not path.is_file():
        return None, "bound source code-index file is unavailable"
    try:
        index_bytes = path.read_bytes()
        actual_hash = hashlib.sha256(index_bytes).hexdigest()
        index = json.loads(index_bytes.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return None, f"bound source code-index cannot be read: {type(exc).__name__}"
    if actual_hash != expected_hash:
        return None, "bound source code-index file hash changed"
    if not isinstance(index, dict) or index.get("schema_version") != "code-index.v1":
        return None, "bound source code-index schema is invalid"
    try:
        if Path(str(index.get("source_root", ""))).expanduser().resolve() != Path(expected_root).expanduser().resolve():
            return None, "bound source code-index root does not match PiRunContext"
    except (OSError, RuntimeError, TypeError, ValueError):
        return None, "bound source code-index root is invalid"
    if str(index.get("snapshot_hash", "") or "") != expected_snapshot:
        return None, "bound source code-index snapshot does not match PiRunContext"

    bound = dict(params)
    if isinstance(bound.get("code_index"), dict):
        return None, "inline code_index cannot override the PiRunContext-bound source index"
    explicit_context_path = str(bound.get("context_path", "") or "").strip()
    bound_context_path = str(os.environ.get("CR60_PI_CODE_CONTEXT_PATH", "") or "").strip()
    if explicit_context_path:
        try:
            if not bound_context_path or Path(explicit_context_path).expanduser().resolve() != Path(bound_context_path).expanduser().resolve():
                return None, "requested context_path conflicts with PiRunContext"
        except (OSError, RuntimeError, TypeError, ValueError):
            return None, "requested context_path is invalid"
    explicit_path = str(bound.get("code_index_path", "") or "").strip()
    if explicit_path:
        try:
            if Path(explicit_path).expanduser().resolve() != path:
                return None, "requested code_index_path conflicts with PiRunContext"
        except (OSError, RuntimeError, TypeError, ValueError):
            return None, "requested code_index_path is invalid"
    explicit_root = str(bound.get("source_root", "") or "").strip()
    if explicit_root:
        try:
            if Path(explicit_root).expanduser().resolve() != Path(expected_root).expanduser().resolve():
                return None, "requested source_root conflicts with PiRunContext"
        except (OSError, RuntimeError, TypeError, ValueError):
            return None, "requested source_root is invalid"
    if bound.get("db_path"):
        return None, "db_path cannot override the PiRunContext-bound source index"
    bound["code_index_path"] = str(path)
    bound["source_root"] = expected_root
    return bound, None


def invoke_capability(
    name: str,
    params: dict[str, Any] | None = None,
    *,
    allow_execution: bool = False,
) -> dict[str, Any]:
    """Dispatch one Pi capability through the canonical Python boundary."""
    capability_name = str(name or "").strip()
    if not capability_name:
        return _error("capability name is required")
    if capability_name in _DEFAULT_EXCLUDED_MODULES:
        return _error(f"capability '{capability_name}' is an orchestration root, not a Pi leaf tool")

    call_params = dict(params or {})
    if capability_name in _ANALYSIS_RUN_BOUND_CAPABILITIES:
        call_params, binding_error = _bind_current_analysis_run(call_params)
        if binding_error:
            return _error(binding_error)
        call_params = call_params or {}
    elif (
        capability_name == "analysis-run-create"
        and str(os.environ.get("CR60_PI_ANALYSIS_RUN_ID", "") or "").strip()
    ):
        return _error("Pi already has an active AnalysisRun; use its bound ledger tools")

    source_bound_read_tools = {
        "code-analyze", "code-context-read", "event-code-path", "code-gdb-plan",
    }
    if (
        str(os.environ.get("CR60_PI_TASK_SCOPE", "") or "").strip() == "source_code"
        and capability_name in source_bound_read_tools
        and str(call_params.get("output", "") or "").strip()
    ):
        return _error(
            "source_code Pi tools return inline results; output file paths are disabled",
            data={
                "project_id": os.environ.get("CR60_PI_PROJECT_ID", ""),
                "variant_id": os.environ.get("CR60_PI_VARIANT_ID", ""),
                "source_snapshot_hash": os.environ.get("CR60_PI_SOURCE_SNAPSHOT_HASH", ""),
            },
        )
    if capability_name in {"code-analyze", "code-gdb-plan"}:
        call_params, binding_error = _bind_current_code_index(call_params)
        if binding_error:
            return _error(binding_error, data={
                "project_id": os.environ.get("CR60_PI_PROJECT_ID", ""),
                "variant_id": os.environ.get("CR60_PI_VARIANT_ID", ""),
                "source_snapshot_hash": os.environ.get("CR60_PI_SOURCE_SNAPSHOT_HASH", ""),
            })
        call_params = call_params or {}
    elif capability_name == "code-context-read":
        call_params, binding_error = _bind_current_code_context(call_params)
        if binding_error:
            return _error(binding_error, data={
                "project_id": os.environ.get("CR60_PI_PROJECT_ID", ""),
                "variant_id": os.environ.get("CR60_PI_VARIANT_ID", ""),
                "source_snapshot_hash": os.environ.get("CR60_PI_SOURCE_SNAPSHOT_HASH", ""),
            })
        call_params = call_params or {}
    elif capability_name == "event-code-path":
        call_params, binding_error = _bind_current_event_code_path(call_params)
        if binding_error:
            return _error(binding_error, data={
                "project_id": os.environ.get("CR60_PI_PROJECT_ID", ""),
                "variant_id": os.environ.get("CR60_PI_VARIANT_ID", ""),
                "source_snapshot_hash": os.environ.get("CR60_PI_SOURCE_SNAPSHOT_HASH", ""),
            })
        call_params = call_params or {}

    module_registry = build_module_tool_registry(
        names=[capability_name], allow_execution=allow_execution
    )
    module_tool = module_registry.get(capability_name)
    if module_tool is not None:
        return module_tool.safe_execute(call_params)
    if capability_name in TOOL_REGISTRY:
        return invoke_tool(capability_name, call_params)

    return _error(
        f"unknown Pi capability '{capability_name}'",
        data={"available": sorted(available_capabilities())},
    )


def _main(argv: list[str] | None = None) -> int:
    # Pi invokes this process from Node/VS Code on Windows as well as from a
    # UTF-8 Linux terminal.  Reconfigure the process boundary before any
    # catalog/result JSON is printed so Chinese diagnostics cannot fail on a
    # cp1252 console after the tool itself has already succeeded.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass
    parser = argparse.ArgumentParser(description="Pi unified capability bridge")
    parser.add_argument("--name", "--tool", dest="name", help="Pi capability name")
    parser.add_argument("--params", default="{}", help="JSON object passed to the capability")
    parser.add_argument("--list", action="store_true", help="print Pi-visible capability catalog")
    parser.add_argument(
        "--allow-execution",
        action="store_true",
        help="internal supervisor-only switch; never used by the generated Pi extension",
    )
    args = parser.parse_args(argv)
    if args.list:
        print(json.dumps(available_capabilities(), ensure_ascii=False, indent=2))
        return 0
    if not args.name:
        print(json.dumps(_error("--name is required"), ensure_ascii=False))
        return 1
    try:
        params = json.loads(args.params) if args.params else {}
    except json.JSONDecodeError as exc:
        print(json.dumps(_error(f"params is not valid JSON: {exc.msg}"), ensure_ascii=False))
        return 1
    if not isinstance(params, dict):
        print(json.dumps(_error("params must decode to a JSON object"), ensure_ascii=False))
        return 1
    result = invoke_capability(args.name, params, allow_execution=args.allow_execution)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if result.get("status") == "ok" else 1


__all__ = ["available_capabilities", "invoke_capability"]


if __name__ == "__main__":
    raise SystemExit(_main())
