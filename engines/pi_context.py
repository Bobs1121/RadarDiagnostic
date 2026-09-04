# -*- coding: utf-8 -*-
"""Deterministic builder for the Pi orchestration context.

The context is an immutable, JSON-serialisable run binding assembled from
explicit inputs and upstream artifacts. It does not infer a vehicle, branch,
COEM, radar mapping, or runtime fact from a path name. Missing or conflicting
identity is preserved as a gate for Pi instead of being silently repaired.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .runtime_evidence import (
    runtime_summary,
    validate_runtime_binding,
    validate_runtime_evidence,
)
from .runtime_debug_plan import validate_runtime_debug_plan


SCHEMA_VERSION = "pi-orchestration-context.v1"


def _json_file(path_text: str, *, label: str) -> tuple[dict[str, Any] | None, str | None]:
    path = Path(path_text).expanduser()
    if not path.exists():
        return None, f"{label}_not_found:{path}"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return None, f"{label}_invalid:{type(exc).__name__}:{path}"
    if not isinstance(value, dict):
        return None, f"{label}_must_be_object:{path}"
    return value, None


def _artifact_input(
    value: Mapping[str, Any] | None,
    path_text: str,
    *,
    label: str,
) -> tuple[dict[str, Any] | None, str | None, dict[str, Any] | None]:
    if value is not None:
        if not isinstance(value, Mapping):
            return None, f"{label}_must_be_object", None
        return dict(value), None, {"kind": label, "source": "inline"}
    if not str(path_text or "").strip():
        return None, None, None
    payload, error = _json_file(str(path_text), label=label)
    return payload, error, {"kind": label, "path": str(Path(path_text).expanduser())}


def _resolved_field(group: Mapping[str, Any] | None, field: str) -> tuple[Any, dict[str, Any] | None]:
    """Read an intake field only when it is explicitly resolved."""
    if not isinstance(group, Mapping) or field not in group:
        return None, None
    entry = group.get(field)
    if isinstance(entry, Mapping):
        if entry.get("status") != "resolved" or entry.get("value") in (None, "", []):
            return None, None
        return entry.get("value"), deepcopy(dict(entry.get("selected_from") or {}))
    if entry not in (None, "", []):
        return entry, {"source": "normalised_input", "field": field}
    return None, None


def _put_value(
    values: dict[str, Any],
    provenance: dict[str, Any],
    name: str,
    value: Any,
    source: Mapping[str, Any] | None,
) -> None:
    if value in (None, "", []):
        return
    values[name] = deepcopy(value)
    if source:
        provenance[name] = deepcopy(dict(source))


def _dedupe_strings(items: list[Any]) -> list[str]:
    result: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _fingerprint(value: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_pi_orchestration_context(
    *,
    intake: Mapping[str, Any] | None = None,
    intake_path: str = "",
    preflight: Mapping[str, Any] | None = None,
    preflight_path: str = "",
    case_dir: str = "",
    project_root: str = "",
    project_id: str = "",
    variant_id: str = "",
    operator: str = "",
    run_id: str = "",
    replay_strategy: str = "",
    radar_id: str = "",
    freshness: Mapping[str, Any] | None = None,
    policy: Mapping[str, Any] | None = None,
    artifact_refs: list[Mapping[str, Any]] | None = None,
    runtime_evidence: Mapping[str, Any] | None = None,
    runtime_evidence_path: str = "",
    diagnosis_bundle: Mapping[str, Any] | None = None,
    diagnosis_bundle_path: str = "",
    runtime_debug_plan: Mapping[str, Any] | None = None,
    runtime_debug_plan_path: str = "",
    capability_manifest: Mapping[str, Any] | None = None,
    capability_manifest_path: str = "",
) -> dict[str, Any]:
    """Build a fail-closed ``pi-orchestration-context.v1`` payload."""
    intake_obj, intake_error, intake_ref = _artifact_input(
        intake, intake_path, label="intake"
    )
    preflight_obj, preflight_error, preflight_ref = _artifact_input(
        preflight, preflight_path, label="preflight"
    )
    runtime_evidence_obj, runtime_evidence_error, runtime_evidence_ref = _artifact_input(
        runtime_evidence, runtime_evidence_path, label="runtime_evidence"
    )
    diagnosis_bundle_obj, diagnosis_bundle_error, diagnosis_bundle_ref = _artifact_input(
        diagnosis_bundle, diagnosis_bundle_path, label="diagnosis_bundle"
    )
    runtime_debug_plan_obj, runtime_debug_plan_error, runtime_debug_plan_ref = _artifact_input(
        runtime_debug_plan, runtime_debug_plan_path, label="runtime_debug_plan"
    )
    capability_manifest_obj, capability_manifest_error, capability_manifest_ref = _artifact_input(
        capability_manifest, capability_manifest_path, label="capability_manifest"
    )
    # A merged bundle is itself a valid runtime producer artifact. Prefer an
    # explicitly supplied runtime artifact, but let Pi consume the canonical
    # static-plus-runtime bundle without requiring callers to split it first.
    if runtime_evidence_obj is None and isinstance(diagnosis_bundle_obj, Mapping):
        embedded_runtime = diagnosis_bundle_obj.get("runtime_evidence")
        if isinstance(embedded_runtime, Mapping):
            runtime_evidence_obj = deepcopy(dict(embedded_runtime))
            runtime_evidence_ref = {
                "kind": "runtime_evidence",
                "source": "embedded_in_diagnosis_bundle",
                "path": diagnosis_bundle_ref.get("path", "") if diagnosis_bundle_ref else "",
            }
    if runtime_debug_plan_obj is None and isinstance(diagnosis_bundle_obj, Mapping):
        embedded_plan = diagnosis_bundle_obj.get("runtime_debug_plan")
        if isinstance(embedded_plan, Mapping):
            runtime_debug_plan_obj = deepcopy(dict(embedded_plan))
            runtime_debug_plan_ref = {
                "kind": "runtime_debug_plan",
                "source": "embedded_in_diagnosis_bundle",
                "path": diagnosis_bundle_ref.get("path", "") if diagnosis_bundle_ref else "",
            }

    # A plan is an explicit runtime selection artifact.  It may therefore
    # supply strategy/radar defaults when the caller is continuing a run from
    # artifacts, while a bare case directory still cannot manufacture either
    # value from its name.
    plan_event = runtime_debug_plan_obj.get("event", {}) if isinstance(runtime_debug_plan_obj, Mapping) else {}
    plan_replay = runtime_debug_plan_obj.get("replay", {}) if isinstance(runtime_debug_plan_obj, Mapping) else {}
    plan_radar = (
        plan_event.get("radar_id")
        if isinstance(plan_event, Mapping)
        else None
    )
    if plan_radar in (None, "") and isinstance(runtime_debug_plan_obj, Mapping):
        plan_radar = (runtime_debug_plan_obj.get("radar", {}) or {}).get("radar_id")
    effective_replay_strategy = replay_strategy or (
        str(plan_replay.get("strategy", ""))
        if isinstance(plan_replay, Mapping)
        else ""
    )
    effective_radar_id = radar_id or (str(plan_radar) if plan_radar not in (None, "") else "")
    errors = _dedupe_strings(
        [
            intake_error,
            preflight_error,
            runtime_evidence_error,
            diagnosis_bundle_error,
            runtime_debug_plan_error,
            capability_manifest_error,
        ]
    )
    missing: list[str] = []
    conflicts: list[dict[str, Any]] = []
    diagnostics: list[str] = []

    capability_context: dict[str, Any] = {
        "status": "not_provided",
        "manifest_fingerprint": "",
        "available": {},
        "unsupported": [],
        "freshness": {},
    }
    if isinstance(capability_manifest_obj, Mapping):
        if capability_manifest_obj.get("schema_version") != "project-capability-manifest.v1":
            errors.append("capability_manifest_schema_version_mismatch")
        capability_status = str(capability_manifest_obj.get("status", "partial"))
        capability_context = {
            "schema_version": capability_manifest_obj.get("schema_version"),
            "status": capability_status,
            "manifest_fingerprint": capability_manifest_obj.get("manifest_fingerprint", ""),
            "identity": {
                key: capability_manifest_obj.get("identity", {}).get(key)
                for key in ("project_id", "variant_id", "customer", "vehicle", "coem")
                if isinstance(capability_manifest_obj.get("identity"), Mapping)
                and capability_manifest_obj.get("identity", {}).get(key) not in (None, "", [])
            },
            "available": {
                category: [
                    {
                        "id": item.get("id"),
                        "status": item.get("status"),
                    }
                    for item in capability_manifest_obj.get(category, []) or []
                    if isinstance(item, Mapping) and item.get("id")
                ]
                for category in (
                    "data_capabilities",
                    "feature_capabilities",
                    "code_capabilities",
                    "replay_capabilities",
                    "runtime_capabilities",
                    "presentation_capabilities",
                )
            },
            "unsupported": [
                {
                    "id": item.get("id"),
                    "reason": item.get("reason"),
                }
                for item in capability_manifest_obj.get("unsupported", []) or []
                if isinstance(item, Mapping)
            ],
            "freshness": deepcopy(dict(capability_manifest_obj.get("freshness", {}) or {})),
        }
        if capability_status == "blocked":
            errors.append("capability_manifest_blocked")
        elif capability_status == "partial":
            diagnostics.append("capability_manifest_partial")
    elif capability_manifest_path or capability_manifest is not None:
        errors.append("capability_manifest_invalid_or_unavailable")

    if isinstance(intake_obj, Mapping):
        missing.extend(str(item) for item in intake_obj.get("missing", []) or [])
        conflicts.extend(
            deepcopy(item)
            for item in intake_obj.get("conflicts", []) or []
            if isinstance(item, Mapping)
        )
        if intake_obj.get("intake_status") == "blocked_missing_input":
            diagnostics.append("intake_blocked_missing_input")
        elif intake_obj.get("intake_status") == "needs_confirmation":
            diagnostics.append("intake_needs_confirmation")

    identity: dict[str, Any] = {}
    identity_provenance: dict[str, Any] = {}
    intake_identity = intake_obj.get("identity", {}) if isinstance(intake_obj, Mapping) else {}
    identity_fields = (
        "ticket_id", "function", "customer", "vehicle", "coem",
        "software_version", "code_branch", "cuda_sheet",
    )
    for field in identity_fields:
        value, source = _resolved_field(intake_identity, field)
        _put_value(identity, identity_provenance, field, value, source)
    _put_value(identity, identity_provenance, "project_id", project_id, {"source": "explicit_input", "field": "project_id"})
    _put_value(identity, identity_provenance, "variant_id", variant_id, {"source": "explicit_input", "field": "variant_id"})

    # A diagnosis bundle is a first-class upstream artifact, not merely a
    # report to be displayed.  When an intake artifact is unavailable, carry
    # forward only fields explicitly present in the bundle; do not infer a
    # vehicle/COEM/branch from a directory or bag filename.  This lets Pi
    # continue an artifact-driven run after Sprint1/runtime stages without
    # forcing callers to split the bundle back into an intake by hand.
    bundle_case = diagnosis_bundle_obj.get("case", {}) if isinstance(diagnosis_bundle_obj, Mapping) else {}
    bundle_provenance = diagnosis_bundle_obj.get("provenance", {}) if isinstance(diagnosis_bundle_obj, Mapping) else {}
    bundle_source_context = diagnosis_bundle_obj.get("source_context", {}) if isinstance(diagnosis_bundle_obj, Mapping) else {}
    bundle_source_identity = (
        bundle_source_context.get("identity", {})
        if isinstance(bundle_source_context, Mapping)
        else {}
    )
    if isinstance(bundle_case, Mapping):
        _put_value(
            identity,
            identity_provenance,
            "case_id",
            bundle_case.get("case_id"),
            {"source": "diagnosis_bundle.case", "field": "case_id"},
        )
        _put_value(
            identity,
            identity_provenance,
            "function_scope",
            bundle_case.get("functions"),
            {"source": "diagnosis_bundle.case", "field": "functions"},
        )
        _put_value(
            identity,
            identity_provenance,
            "vehicle_params",
            bundle_case.get("vehicle"),
            {"source": "diagnosis_bundle.case", "field": "vehicle"},
        )
    if isinstance(bundle_provenance, Mapping):
        _put_value(
            identity,
            identity_provenance,
            "project_id",
            bundle_provenance.get("project"),
            {"source": "diagnosis_bundle.provenance", "field": "project"},
        )

    bundle_source_values = {
        "source_context_id": (
            bundle_source_context.get("source_context_id")
            if isinstance(bundle_source_context, Mapping)
            else None
        )
        or (bundle_provenance.get("source_context_id") if isinstance(bundle_provenance, Mapping) else None),
        "source_snapshot_hash": (
            bundle_source_identity.get("source_snapshot_hash")
            if isinstance(bundle_source_identity, Mapping)
            else None
        )
        or (bundle_provenance.get("source_snapshot_hash") if isinstance(bundle_provenance, Mapping) else None),
        "code_index_hash": (
            bundle_source_context.get("code_index_hash")
            if isinstance(bundle_source_context, Mapping)
            else None
        )
        or (bundle_provenance.get("source_index_hash") if isinstance(bundle_provenance, Mapping) else None),
    }
    environment = intake_obj.get("environment", {}) if isinstance(intake_obj, Mapping) else {}
    env_vehicle = environment.get("vehicle", {}) if isinstance(environment, Mapping) else {}
    env_build = environment.get("build", {}) if isinstance(environment, Mapping) else {}
    for source_group, source_name in (
        (env_vehicle, "intake.environment.vehicle"),
        (env_build, "intake.environment.build"),
    ):
        for field, identity_field in (
            ("customer", "customer"), ("model", "vehicle"), ("coem", "coem"),
            ("cuda_sheet", "cuda_sheet"), ("software_version", "software_version"),
            ("code_branch", "code_branch"),
        ):
            if identity_field in identity or not isinstance(source_group, Mapping):
                continue
            value = source_group.get(field)
            _put_value(
                identity, identity_provenance, identity_field, value,
                {"source": source_name, "field": field},
            )

    workspace = preflight_obj.get("workspace", {}) if isinstance(preflight_obj, Mapping) else {}
    configuration = preflight_obj.get("configuration", {}) if isinstance(preflight_obj, Mapping) else {}
    build = preflight_obj.get("build", {}) if isinstance(preflight_obj, Mapping) else {}
    runtime = preflight_obj.get("runtime", {}) if isinstance(preflight_obj, Mapping) else {}
    gdb = preflight_obj.get("gdb", {}) if isinstance(preflight_obj, Mapping) else {}

    source: dict[str, Any] = {}
    source_provenance: dict[str, Any] = {}
    intake_source = intake_obj.get("source_context", {}) if isinstance(intake_obj, Mapping) else {}
    for field in ("server_host", "server_user", "arbe_root", "algo_source_root", "code_root", "dbc"):
        value, selected = _resolved_field(intake_source, field)
        _put_value(
            source, source_provenance, field, value,
            selected or {"source": "intake.source_context", "field": field},
        )

    for field, value in bundle_source_values.items():
        _put_value(
            source,
            source_provenance,
            field,
            value,
            {"source": "diagnosis_bundle", "field": field},
        )

    if isinstance(bundle_source_identity, Mapping):
        for source_field, identity_field in (
            ("remote_host", "server_host"),
            ("remote_workspace", "arbe_root"),
            ("outer_head", "outer_head"),
            ("outer_branch", "outer_branch"),
            ("outer_dirty", "outer_dirty"),
            ("outer_status", "outer_status"),
            ("algo_head", "algo_head"),
            ("algo_branch", "algo_branch"),
            ("algo_dirty", "algo_dirty"),
            ("algo_status", "algo_status"),
        ):
            if identity_field in source:
                continue
            _put_value(
                source,
                source_provenance,
                identity_field,
                bundle_source_identity.get(source_field),
                {"source": "diagnosis_bundle.source_context.identity", "field": source_field},
            )

    if isinstance(workspace, Mapping):
        for field in ("arbe_root", "algo_source_root"):
            value = workspace.get(field)
            if field not in source:
                _put_value(source, source_provenance, field, value, {"source": "preflight.workspace", "field": field})
        for section in ("outer", "algo_source"):
            item = workspace.get(section, {})
            if isinstance(item, Mapping):
                for field in ("head", "status", "status_ok", "branch"):
                    _put_value(source, source_provenance, f"{section}_{field}", item.get(field), {"source": f"preflight.workspace.{section}", "field": field})
    if isinstance(configuration, Mapping) and configuration:
        source["configuration"] = deepcopy(dict(configuration))
        source_provenance["configuration"] = {"source": "preflight.configuration"}
    if isinstance(build, Mapping) and build:
        source["build_probe"] = deepcopy(dict(build))
        source_provenance["build_probe"] = {"source": "preflight.build"}

    if isinstance(capability_manifest_obj, Mapping):
        manifest_identity = capability_context.get("identity", {})
        for field in ("project_id", "variant_id", "customer", "vehicle", "coem"):
            left = identity.get(field)
            right = manifest_identity.get(field) if isinstance(manifest_identity, Mapping) else None
            if left not in (None, "", []) and right not in (None, "", []) and str(left) != str(right):
                conflicts.append({
                    "field": f"capability_manifest.identity.{field}",
                    "context_value": left,
                    "manifest_value": right,
                    "reason": "capability_manifest_identity_mismatch",
                })
                errors.append(f"capability_manifest_identity_conflict:{field}")
        manifest_freshness = capability_context.get("freshness", {})
        manifest_hash = (
            manifest_freshness.get("source_snapshot_hash")
            if isinstance(manifest_freshness, Mapping)
            else None
        )
        context_hash = source.get("source_snapshot_hash")
        if manifest_hash and context_hash and str(manifest_hash) != str(context_hash):
            conflicts.append({
                "field": "capability_manifest.freshness.source_snapshot_hash",
                "context_value": context_hash,
                "manifest_value": manifest_hash,
                "reason": "capability_manifest_source_snapshot_mismatch",
            })
            errors.append("capability_manifest_source_snapshot_conflict")

    data_obj = intake_obj.get("data", {}) if isinstance(intake_obj, Mapping) else {}
    data: dict[str, Any] = deepcopy(dict(data_obj)) if isinstance(data_obj, Mapping) else {}
    if case_dir and not data.get("root"):
        data["root"] = str(case_dir)
    if case_dir and not data.get("cases"):
        data["cases"] = [{"data_dir": str(case_dir), "case_id": Path(case_dir).name}]
    if not data.get("paths") and not data.get("cases") and isinstance(bundle_case, Mapping):
        # ``case.bag``/``provenance.bag_path`` are explicit artifact fields.
        # Binding them here is safe; deriving a case from a filename would not
        # be.  Keep the remote/local path as supplied so the next provider can
        # decide whether it is reachable.
        bundle_bag = bundle_case.get("bag") or (
            bundle_provenance.get("bag_path") if isinstance(bundle_provenance, Mapping) else ""
        )
        if bundle_bag:
            case_id = bundle_case.get("case_id")
            case_entry: dict[str, Any] = {"bag_paths": [str(bundle_bag)]}
            if case_id not in (None, ""):
                case_entry["case_id"] = str(case_id)
            data["paths"] = [{"path": str(bundle_bag), "source": "diagnosis_bundle.case.bag"}]
            data["cases"] = [case_entry]
            diagnostics.append("data_bound_from_diagnosis_bundle")
    if not data.get("paths") and not data.get("cases"):
        missing.append("data.case_or_intake")
    if not data.get("paths") and data.get("cases"):
        diagnostics.append("data_paths_not_materialized")

    runtime_context: dict[str, Any] = {
        "status": runtime.get("status", "not_started") if isinstance(runtime, Mapping) else "not_started",
        "strategy": effective_replay_strategy,
        "radar_id": effective_radar_id,
        "preflight": deepcopy(dict(runtime)) if isinstance(runtime, Mapping) else {},
        "gdb": deepcopy(dict(gdb)) if isinstance(gdb, Mapping) else {},
    }
    runtime_context["strategy_status"] = "selected" if effective_replay_strategy else "not_selected"
    runtime_context["radar_id_source"] = (
        "explicit_input" if radar_id else
        "runtime_debug_plan" if effective_radar_id and isinstance(runtime_debug_plan_obj, Mapping) else
        "preflight_process_candidate" if isinstance(runtime, Mapping) and runtime.get("processes") else
        "not_available"
    )
    if not replay_strategy and effective_replay_strategy and isinstance(runtime_debug_plan_obj, Mapping):
        runtime_context["strategy_source"] = "runtime_debug_plan"
    runtime_context["evidence_status"] = "not_provided"
    if isinstance(runtime_evidence_obj, Mapping):
        runtime_validation_errors = validate_runtime_evidence(runtime_evidence_obj)
        runtime_binding = (
            validate_runtime_binding(diagnosis_bundle_obj, runtime_evidence_obj)
            if isinstance(diagnosis_bundle_obj, Mapping)
            else None
        )
        if runtime_validation_errors:
            errors.extend(f"runtime_evidence:{item}" for item in runtime_validation_errors)
            runtime_context["evidence_status"] = "blocked"
        elif runtime_binding and runtime_binding.get("status") == "conflict":
            errors.append("runtime_evidence_binding_conflict")
            runtime_context["evidence_status"] = "blocked"
        else:
            runtime_context["evidence_status"] = (
                "partial"
                if runtime_binding is None
                else str(runtime_binding.get("status", "partial"))
            )
        runtime_context["evidence"] = runtime_summary(
            runtime_evidence_obj,
            {
                "status": runtime_context["evidence_status"],
                "binding": runtime_binding,
            },
        )
        if runtime_evidence_ref:
            runtime_context["evidence_ref"] = deepcopy(runtime_evidence_ref)
        if runtime_binding:
            runtime_context["evidence_binding"] = deepcopy(runtime_binding)
        if diagnosis_bundle_ref:
            runtime_context["diagnosis_bundle_ref"] = deepcopy(diagnosis_bundle_ref)
        runtime_context["evidence_diagnostics"] = list(
            dict.fromkeys(
                [
                    *list(runtime_evidence_obj.get("diagnostics", []) or []),
                    *list((runtime_binding or {}).get("diagnostics", []) or []),
                ]
            )
        )
    elif runtime_evidence_path or runtime_evidence is not None:
        runtime_context["evidence_status"] = "blocked"
    runtime_context["debug_plan_status"] = "not_provided"
    if isinstance(runtime_debug_plan_obj, Mapping):
        plan_errors = validate_runtime_debug_plan(runtime_debug_plan_obj)
        if plan_errors:
            runtime_context["debug_plan_status"] = "blocked"
            errors.extend(f"runtime_debug_plan:{item}" for item in plan_errors)
        else:
            runtime_context["debug_plan_status"] = str(runtime_debug_plan_obj.get("status", "partial"))
        runtime_context["debug_plan"] = {
            "schema_version": runtime_debug_plan_obj.get("schema_version"),
            "status": runtime_debug_plan_obj.get("status"),
            "execution_status": runtime_debug_plan_obj.get("execution_status"),
            "plan_fingerprint": runtime_debug_plan_obj.get("plan_fingerprint", ""),
            "event": deepcopy(dict(runtime_debug_plan_obj.get("event", {}) or {})),
            "radar": deepcopy(dict(runtime_debug_plan_obj.get("radar", {}) or {})),
            "target": deepcopy(dict(runtime_debug_plan_obj.get("target", {}) or {})),
            "readiness": deepcopy(dict(runtime_debug_plan_obj.get("readiness", {}) or {})),
            "breakpoints": deepcopy(list(runtime_debug_plan_obj.get("breakpoints", []) or [])),
            "gdb_commands": list(runtime_debug_plan_obj.get("gdb_commands", []) or []),
            "capture_fields": deepcopy(list(runtime_debug_plan_obj.get("capture_fields", []) or [])),
            "diagnostics": list(runtime_debug_plan_obj.get("diagnostics", []) or []),
        }
        if runtime_debug_plan_ref:
            runtime_context["debug_plan_ref"] = deepcopy(runtime_debug_plan_ref)
    elif runtime_debug_plan_path or runtime_debug_plan is not None:
        runtime_context["debug_plan_status"] = "blocked"

    default_policy: dict[str, Any] = {
        "mode": "read_only",
        "execution": "plan_only",
        "approval_required_for": ["remote_write", "checkout", "build", "start", "gdb_attach", "gdb_execute"],
        "allowed_side_effects": [],
        "operator_confirmation": False,
    }
    if isinstance(policy, Mapping):
        default_policy.update(deepcopy(dict(policy)))
    if default_policy.get("allowed_side_effects") and not default_policy.get("operator_confirmation"):
        diagnostics.append("side_effects_requested_without_confirmation")

    artifact_list: list[dict[str, Any]] = [
        deepcopy(dict(ref)) for ref in (artifact_refs or []) if isinstance(ref, Mapping)
    ]
    for ref in (
        intake_ref,
        preflight_ref,
        runtime_evidence_ref,
        diagnosis_bundle_ref,
        runtime_debug_plan_ref,
        capability_manifest_ref,
    ):
        if ref:
            artifact_list.append(ref)
    unique_artifacts: list[dict[str, Any]] = []
    seen_artifacts: set[str] = set()
    for ref in artifact_list:
        key = json.dumps(ref, ensure_ascii=False, sort_keys=True, default=str)
        if key not in seen_artifacts:
            seen_artifacts.add(key)
            unique_artifacts.append(ref)

    freshness_obj = deepcopy(dict(freshness)) if isinstance(freshness, Mapping) else {"status": "not_provided"}
    identity["provenance"] = identity_provenance
    source["provenance"] = source_provenance
    has_source_binding = any(
        key not in {"provenance", "source_context_fingerprint"}
        for key in source
    )
    source["source_context_fingerprint"] = _fingerprint({k: v for k, v in source.items() if k != "provenance"})
    data["data_fingerprint"] = _fingerprint(data)

    missing = _dedupe_strings(missing)
    blocked = bool(errors) or (not data.get("paths") and not data.get("cases"))
    if isinstance(intake_obj, Mapping) and intake_obj.get("status") == "blocked":
        blocked = True
    capability_partial = capability_context.get("status") not in {"not_provided", "ready"}
    status = (
        "blocked"
        if blocked
        else "partial"
        if (missing or conflicts or not has_source_binding or capability_partial)
        else "ready"
    )
    if blocked:
        diagnostics.append("context_blocked")
    elif status == "partial":
        diagnostics.append("context_requires_confirmation_or_more_artifacts")

    canonical = {
        "project": {k: v for k, v in identity.items() if k != "provenance"},
        "data": data,
        "source": {k: v for k, v in source.items() if k != "provenance"},
        "build": build,
        "runtime": runtime_context,
        "capabilities": capability_context,
        "policy": default_policy,
        "artifacts": unique_artifacts,
        "freshness": freshness_obj,
    }
    context_fingerprint = _fingerprint(canonical)
    effective_run_id = str(run_id or "").strip() or "pi-run-" + context_fingerprint[:16]
    effective_project_root = str(project_root or source.get("arbe_root", "") or "")
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "run_id": effective_run_id,
        "context_fingerprint": context_fingerprint,
        "operator": str(operator or ""),
        "project_root": effective_project_root,
        "project": identity,
        "data": data,
        "source": source,
        "build": deepcopy(dict(build)) if isinstance(build, Mapping) else {},
        "runtime": runtime_context,
        "capabilities": capability_context,
        "policy": default_policy,
        "artifacts": unique_artifacts,
        "freshness": freshness_obj,
        "missing": missing,
        "conflicts": conflicts,
        "diagnostics": _dedupe_strings(diagnostics + errors),
    }


__all__ = ["SCHEMA_VERSION", "build_pi_orchestration_context"]
