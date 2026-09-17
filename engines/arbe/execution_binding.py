"""Approval-bound identity for side-effecting replay execution.

The public replay provider can build a command, but a command is not an
execution authorization.  This module freezes the data/source/binary/config
and session identity that was reviewed by the caller and verifies it again
immediately before a remote capture starts.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping


SCHEMA_VERSION = "arbe-execution-binding.v1"
REQUIRED_IDENTITY_FIELDS = (
    "data_fingerprint",
    "source_context_id",
    "binary_fingerprint",
    "config_fingerprint",
    "session_id",
)


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def derive_execution_identity(
    *,
    identity: Mapping[str, Any] | None = None,
    preflight: Mapping[str, Any] | None = None,
    source_context: Mapping[str, Any] | None = None,
) -> tuple[dict[str, str], dict[str, str]]:
    """Resolve identity fields from explicit context and preflight artifacts.

    Technical fields are discovered from the structured preflight shape.  Only
    data identity must be supplied by an intake/bundle; it is never guessed
    from a path.  Derived fields keep a provenance label for the caller.
    """
    explicit: dict[str, Any] = {}
    provenance: dict[str, str] = {}
    for value, label in (
        (preflight, "preflight"),
        (source_context, "source_context"),
        (identity, "identity"),
    ):
        if not isinstance(value, Mapping):
            continue
        for section_name in ("data", "source", "build", "runtime"):
            section = value.get(section_name)
            if isinstance(section, Mapping):
                for key, item in section.items():
                    if item not in (None, "") and not isinstance(item, (dict, list)):
                        explicit.setdefault(str(key), item)
                        provenance.setdefault(str(key), f"{label}.{section_name}.{key}")
        nested = value.get("identity")
        if isinstance(nested, Mapping):
            for key, item in nested.items():
                if item not in (None, ""):
                    explicit.setdefault(str(key), item)
                    provenance.setdefault(str(key), f"{label}.identity")
        for key, item in value.items():
            if item not in (None, "") and not isinstance(item, (dict, list)):
                explicit[str(key)] = item
                provenance[str(key)] = label

    if not explicit.get("source_context_id") and explicit.get("source_context_fingerprint"):
        explicit["source_context_id"] = explicit["source_context_fingerprint"]
        provenance["source_context_id"] = "source_context.source_context_fingerprint"
    if not explicit.get("data_fingerprint"):
        data_section = source_context.get("data") if isinstance(source_context, Mapping) else None
        if isinstance(data_section, Mapping):
            candidate = data_section.get("data_fingerprint") or data_section.get("fingerprint")
            if candidate:
                explicit["data_fingerprint"] = candidate
                provenance["data_fingerprint"] = "source_context.data"

    pf = preflight if isinstance(preflight, Mapping) else {}
    workspace = pf.get("workspace") if isinstance(pf.get("workspace"), Mapping) else {}
    outer = workspace.get("outer") if isinstance(workspace.get("outer"), Mapping) else {}
    algo = workspace.get("algo_source") if isinstance(workspace.get("algo_source"), Mapping) else {}
    build = pf.get("build") if isinstance(pf.get("build"), Mapping) else {}
    configuration = pf.get("configuration") if isinstance(pf.get("configuration"), Mapping) else {}
    runtime = pf.get("runtime") if isinstance(pf.get("runtime"), Mapping) else {}

    if not explicit.get("binary_fingerprint") and build.get("binary_fingerprint"):
        explicit["binary_fingerprint"] = build["binary_fingerprint"]
        provenance["binary_fingerprint"] = "preflight.build.binary_fingerprint"
    conflicts: list[str] = []
    if outer.get("head") and algo.get("head"):
        source_material = {
            "outer_head": outer["head"],
            "outer_content_fingerprint": outer.get("content_fingerprint", ""),
            "outer_status": outer.get("status", ""),
            "algo_head": algo["head"],
            "algo_content_fingerprint": algo.get("content_fingerprint", ""),
            "algo_status": algo.get("status", ""),
        }
        derived_source_id = _canonical_hash(source_material)
        live_content_bound = bool(outer.get("content_fingerprint") or algo.get("content_fingerprint"))
        if explicit.get("source_context_id") and str(explicit["source_context_id"]) != derived_source_id and live_content_bound:
            conflicts.append("source_context_id:explicit_vs_live_preflight")
        elif not explicit.get("source_context_id") or live_content_bound:
            explicit["source_context_id"] = derived_source_id
            provenance["source_context_id"] = "derived:preflight.workspace.git_heads_and_content"
    if configuration:
        config_content = str(configuration.get("content_fingerprint") or "")
        resolved_config = configuration.get("resolved", configuration)
        derived_config_id = config_content or _canonical_hash(resolved_config)
        if explicit.get("config_fingerprint") and str(explicit["config_fingerprint"]) != derived_config_id and config_content:
            conflicts.append("config_fingerprint:explicit_vs_live_preflight")
        elif not explicit.get("config_fingerprint") or config_content:
            explicit["config_fingerprint"] = derived_config_id
            provenance["config_fingerprint"] = "derived:preflight.configuration_content" if config_content else "derived:preflight.configuration"
    if not explicit.get("session_id") and runtime:
        processes = runtime.get("processes", [])
        process_ids = sorted(
            str(item.get("pid"))
            for item in processes
            if isinstance(item, Mapping) and item.get("pid") not in (None, "")
        )
        session_material = {
            "server": pf.get("server", {}),
            "ros_master_uri": runtime.get("ros_master_uri", ""),
            "pids": process_ids,
            "binary_fingerprint": explicit.get("binary_fingerprint", ""),
        }
        if process_ids or runtime.get("ros_master_uri"):
            explicit["session_id"] = _canonical_hash(session_material)
            provenance["session_id"] = "derived:preflight.runtime"

    # A binding must never silently combine two snapshots.  Preserve the
    # selected value for diagnostics, but expose conflicts to the caller so an
    # approval-bound module can fail closed before any side effect.
    if conflicts:
        provenance["__conflicts__"] = ";".join(conflicts)

    returned_provenance = {key: provenance.get(key, "") for key in REQUIRED_IDENTITY_FIELDS}
    if provenance.get("__conflicts__"):
        returned_provenance["__conflicts__"] = provenance["__conflicts__"]
    return (
        {key: str(explicit.get(key) or "") for key in REQUIRED_IDENTITY_FIELDS},
        returned_provenance,
    )


def build_execution_binding(
    *,
    plan: Mapping[str, Any],
    identity: Mapping[str, Any],
    approval_id: str,
    approved: bool,
    run_id: str,
) -> dict[str, Any]:
    """Create the immutable payload a side-effecting runner must consume."""
    missing = [key for key in REQUIRED_IDENTITY_FIELDS if not str(identity.get(key) or "").strip()]
    if missing:
        raise ValueError("execution_binding_missing_identity:" + ",".join(missing))
    if not str(approval_id or "").strip():
        raise ValueError("execution_binding_missing_approval_id")
    if not approved:
        raise ValueError("execution_binding_not_approved")
    if not str(run_id or "").strip():
        raise ValueError("execution_binding_missing_run_id")
    frozen_identity = {key: str(identity[key]) for key in REQUIRED_IDENTITY_FIELDS}
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "approved",
        "approval_id": str(approval_id),
        "run_id": str(run_id),
        "plan_hash": _canonical_hash(dict(plan)),
        "identity": frozen_identity,
        "binding_hash": _canonical_hash({"plan": dict(plan), "identity": frozen_identity, "run_id": run_id}),
    }


def verify_execution_binding(
    binding: Mapping[str, Any] | None,
    *,
    current_identity: Mapping[str, Any],
    approved: bool,
    plan: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Verify a previously approved binding against the live execution target."""
    reasons: list[str] = []
    if not isinstance(binding, Mapping):
        reasons.append("execution_binding_missing")
        return {"schema_version": SCHEMA_VERSION, "status": "blocked", "reasons": reasons}
    if binding.get("schema_version") != SCHEMA_VERSION:
        reasons.append("execution_binding_schema_mismatch")
    if binding.get("status") != "approved":
        reasons.append("execution_binding_not_approved")
    if not approved:
        reasons.append("approval_required")
    frozen = binding.get("identity")
    if not isinstance(frozen, Mapping):
        reasons.append("execution_binding_identity_missing")
        frozen = {}
    for key in REQUIRED_IDENTITY_FIELDS:
        expected = str(frozen.get(key) or "")
        actual = str(current_identity.get(key) or "")
        if not expected:
            reasons.append(f"binding_identity_missing:{key}")
        elif not actual:
            reasons.append(f"current_identity_missing:{key}")
        elif expected != actual:
            reasons.append(f"identity_mismatch:{key}")
    if plan is not None:
        if binding.get("plan_hash") != _canonical_hash(dict(plan)):
            reasons.append("execution_plan_changed")
        expected_binding_hash = _canonical_hash({
            "plan": dict(plan),
            "identity": {key: str(frozen.get(key) or "") for key in REQUIRED_IDENTITY_FIELDS},
            "run_id": str(binding.get("run_id") or ""),
        })
        if binding.get("binding_hash") and str(binding.get("binding_hash")) != expected_binding_hash:
            reasons.append("execution_binding_hash_mismatch")
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "verified" if not reasons else "blocked",
        "binding_hash": binding.get("binding_hash", ""),
        "run_id": binding.get("run_id", ""),
        "reasons": reasons,
    }


__all__ = [
    "SCHEMA_VERSION",
    "REQUIRED_IDENTITY_FIELDS",
    "build_execution_binding",
    "derive_execution_identity",
    "verify_execution_binding",
]
