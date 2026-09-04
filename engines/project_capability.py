# -*- coding: utf-8 -*-
"""Build a source/data-bound ProjectCapabilityManifest for Pi routing.

The manifest is a deterministic capability declaration, not a diagnosis and
not an LLM summary.  It reports what the supplied artifacts prove about the
current project and keeps unavailable capabilities explicit.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = "project-capability-manifest.v1"


class ProjectCapabilityError(ValueError):
    """Raised when a manifest input is malformed or ambiguous."""


def _canonical_hash(value: object) -> str:
    text = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _load_object(
    value: Mapping[str, Any] | None,
    path_text: str,
    *,
    label: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, str | None]:
    if value is not None:
        if not isinstance(value, Mapping):
            return None, None, f"{label}_must_be_object"
        payload = deepcopy(dict(value))
        return payload, {
            "label": label,
            "source": "inline",
            "sha256": _canonical_hash(payload),
            "schema_version": payload.get("schema_version", ""),
        }, None
    if not str(path_text or "").strip():
        return None, None, None
    path = Path(path_text).expanduser().resolve()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return None, None, f"{label}_invalid:{type(exc).__name__}:{path}"
    if not isinstance(payload, Mapping):
        return None, None, f"{label}_must_be_object:{path}"
    data = dict(payload)
    return data, {
        "label": label,
        "source": "file",
        "path": str(path),
        "sha256": _canonical_hash(data),
        "schema_version": data.get("schema_version", ""),
    }, None


def _status(payload: Mapping[str, Any] | None) -> str:
    if not isinstance(payload, Mapping):
        return "not_available"
    return str(payload.get("status") or payload.get("intake_status") or "unknown")


def _resolved_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        if value.get("status") == "resolved":
            return value.get("value")
        return None
    return value if value not in (None, "", []) else None


def _copy_explicit_identity(
    target: dict[str, Any],
    provenance: dict[str, Any],
    source: Mapping[str, Any] | None,
    *,
    source_label: str,
) -> None:
    if not isinstance(source, Mapping):
        return
    for key, raw in source.items():
        value = _resolved_value(raw)
        if value in (None, "", []):
            continue
        if key not in target:
            target[str(key)] = deepcopy(value)
            provenance[str(key)] = {
                "source": source_label,
                "field": str(key),
            }


def _entry(
    capability_id: str,
    *,
    status: str = "available",
    evidence: list[Mapping[str, Any]] | None = None,
    details: Mapping[str, Any] | None = None,
    requires: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": capability_id,
        "status": status,
        "evidence_refs": [dict(item) for item in (evidence or [])],
        "details": deepcopy(dict(details or {})),
        "requires": list(requires or []),
    }


def _append_unique(items: list[dict[str, Any]], item: dict[str, Any]) -> None:
    if not any(str(row.get("id")) == str(item.get("id")) for row in items):
        items.append(item)


def _schema_is(payload: Mapping[str, Any] | None, *names: str) -> bool:
    return isinstance(payload, Mapping) and str(payload.get("schema_version", "")) in names


def build_project_capability_manifest(
    *,
    identity: Mapping[str, Any] | None = None,
    intake: Mapping[str, Any] | None = None,
    intake_path: str = "",
    preflight: Mapping[str, Any] | None = None,
    preflight_path: str = "",
    code_context: Mapping[str, Any] | None = None,
    code_context_path: str = "",
    runtime_snapshot: Mapping[str, Any] | None = None,
    runtime_snapshot_path: str = "",
    diagnosis_bundle: Mapping[str, Any] | None = None,
    diagnosis_bundle_path: str = "",
    declared_capabilities: Mapping[str, Any] | None = None,
    project_id: str = "",
    variant_id: str = "",
) -> dict[str, Any]:
    """Build one manifest from explicit artifacts without path-name inference."""
    loaded: dict[str, dict[str, Any] | None] = {}
    refs: list[dict[str, Any]] = []
    errors: list[str] = []
    for label, value, path in (
        ("intake", intake, intake_path),
        ("preflight", preflight, preflight_path),
        ("code_context", code_context, code_context_path),
        ("runtime_snapshot", runtime_snapshot, runtime_snapshot_path),
        ("diagnosis_bundle", diagnosis_bundle, diagnosis_bundle_path),
    ):
        payload, ref, error = _load_object(value, path, label=label)
        loaded[label] = payload
        if ref is not None:
            refs.append(ref)
        if error:
            errors.append(error)

    explicit_identity: dict[str, Any] = dict(identity or {})
    identity_provenance: dict[str, Any] = {
        str(key): {"source": "explicit_input", "field": str(key)}
        for key in explicit_identity
    }
    if project_id and "project_id" not in explicit_identity:
        explicit_identity["project_id"] = project_id
        identity_provenance["project_id"] = {"source": "explicit_input", "field": "project_id"}
    if variant_id and "variant_id" not in explicit_identity:
        explicit_identity["variant_id"] = variant_id
        identity_provenance["variant_id"] = {"source": "explicit_input", "field": "variant_id"}

    intake_obj = loaded["intake"]
    if isinstance(intake_obj, Mapping):
        _copy_explicit_identity(
            explicit_identity,
            identity_provenance,
            intake_obj.get("identity"),
            source_label="intake.identity",
        )
        environment = intake_obj.get("environment")
        if isinstance(environment, Mapping):
            _copy_explicit_identity(
                explicit_identity,
                identity_provenance,
                environment.get("vehicle"),
                source_label="intake.environment.vehicle",
            )
    code_obj = loaded["code_context"]
    code_source_context = code_obj.get("source_context", {}) if isinstance(code_obj, Mapping) else {}
    if isinstance(code_source_context, Mapping):
        for field in (
            "project_id",
            "variant_id",
            "customer",
            "vehicle",
            "coem",
            "remote_host",
            "remote_source_root",
            "source_root",
            "remote_git_head",
            "git_head",
            "git_branch",
            "git_dirty",
            "source_snapshot_hash",
            "snapshot_hash",
        ):
            if field not in explicit_identity and code_source_context.get(field) not in (None, "", []):
                explicit_identity[field] = deepcopy(code_source_context[field])
                identity_provenance[field] = {
                    "source": "code_context.source_context",
                    "field": field,
                }

    data_capabilities: list[dict[str, Any]] = []
    feature_capabilities: list[dict[str, Any]] = []
    code_capabilities: list[dict[str, Any]] = []
    replay_capabilities: list[dict[str, Any]] = []
    runtime_capabilities: list[dict[str, Any]] = []
    presentation_capabilities: list[dict[str, Any]] = []
    unsupported: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []

    source_hashes: dict[str, str] = {}
    if isinstance(code_source_context, Mapping):
        value = code_source_context.get("source_snapshot_hash") or code_source_context.get("snapshot_hash")
        if value:
            source_hashes["code_context"] = str(value)
    bundle_obj = loaded["diagnosis_bundle"]
    bundle_provenance = bundle_obj.get("provenance", {}) if isinstance(bundle_obj, Mapping) else {}
    bundle_source = bundle_obj.get("source_context", {}) if isinstance(bundle_obj, Mapping) else {}
    bundle_identity = bundle_source.get("identity", {}) if isinstance(bundle_source, Mapping) else {}
    if isinstance(bundle_provenance, Mapping) and bundle_provenance.get("source_snapshot_hash"):
        source_hashes["diagnosis_bundle"] = str(bundle_provenance["source_snapshot_hash"])
    elif isinstance(bundle_source, Mapping) and bundle_source.get("source_snapshot_hash"):
        source_hashes["diagnosis_bundle"] = str(bundle_source["source_snapshot_hash"])
    elif isinstance(bundle_identity, Mapping) and bundle_identity.get("source_snapshot_hash"):
        source_hashes["diagnosis_bundle"] = str(bundle_identity["source_snapshot_hash"])
    runtime_obj = loaded["runtime_snapshot"]
    runtime_source = runtime_obj.get("source_context", {}) if isinstance(runtime_obj, Mapping) else {}
    if isinstance(runtime_source, Mapping) and runtime_source.get("source_snapshot_hash"):
        source_hashes["runtime_snapshot"] = str(runtime_source["source_snapshot_hash"])
    if len(set(source_hashes.values())) > 1:
        conflicts.append({
            "field": "source_snapshot_hash",
            "values": source_hashes,
            "reason": "project_artifacts_are_bound_to_different_source_snapshots",
        })
        unsupported.append({
            "id": "source-consistency",
            "reason": "source_snapshot_hash_conflict",
            "required_inputs": ["artifacts generated from one current source snapshot"],
        })

    if intake_obj is not None:
        _append_unique(data_capabilities, _entry("intake-binding", evidence=[refs[0]] if refs else []))
    elif explicit_identity:
        _append_unique(data_capabilities, _entry(
            "intake-binding",
            status="explicit_identity",
            details={"source": "explicit_identity"},
        ))
    else:
        unsupported.append({
            "id": "intake-binding",
            "reason": "intake_artifact_not_supplied",
            "required_inputs": ["cr60-analysis-intake.v1 or explicit identity"],
        })

    data_group = intake_obj.get("data", {}) if isinstance(intake_obj, Mapping) else {}
    data_path = _resolved_value(data_group.get("path")) if isinstance(data_group, Mapping) else None
    if data_path or isinstance(loaded["diagnosis_bundle"], Mapping):
        _append_unique(data_capabilities, _entry(
            "recorded-data",
            evidence=[ref for ref in refs if ref["label"] in {"intake", "diagnosis_bundle"}],
            details={"path": data_path} if data_path else {},
        ))
    else:
        unsupported.append({
            "id": "recorded-data",
            "reason": "recorded_data_artifact_not_declared",
            "required_inputs": ["intake.data.path or diagnosis bundle"],
        })

    functions: list[str] = []
    function_value = explicit_identity.get("function") or explicit_identity.get("function_scope")
    if isinstance(function_value, str):
        functions = [function_value]
    elif isinstance(function_value, (list, tuple)):
        functions = [str(item) for item in function_value if str(item)]
    if functions:
        _append_unique(feature_capabilities, _entry(
            "declared-feature-scope",
            evidence=[ref for ref in refs if ref["label"] == "intake"],
            details={"functions": functions},
        ))
    elif isinstance(code_obj, Mapping) and (code_obj.get("summary") or code_obj.get("index")):
        _append_unique(feature_capabilities, _entry(
            "source-feature-discovery",
            evidence=[ref for ref in refs if ref["label"] == "code_context"],
            details={"source_derived": True},
        ))
    else:
        unsupported.append({
            "id": "feature-scope",
            "reason": "feature_scope_not_explicit_or_source_indexed",
            "required_inputs": ["intake identity.function or ready code-context"],
        })

    code_ready = isinstance(code_obj, Mapping) and _status(code_obj) == "ready"
    if code_ready:
        code_evidence = [ref for ref in refs if ref["label"] == "code_context"]
        for capability_id in ("source-context", "code-index", "code-analyze", "code-gdb-plan"):
            _append_unique(code_capabilities, _entry(
                capability_id,
                evidence=code_evidence,
                details={"source_snapshot_hash": code_source_context.get("source_snapshot_hash", "")}
                if isinstance(code_source_context, Mapping) else {},
            ))
    else:
        unsupported.append({
            "id": "code-index",
            "reason": "ready code_context_not_available",
            "required_inputs": ["code-context.v1 status=ready"],
        })

    preflight_obj = loaded["preflight"]
    preflight_workspace = (
        preflight_obj.get("workspace", {})
        if isinstance(preflight_obj, Mapping)
        else {}
    )
    workspace_present = isinstance(preflight_workspace, Mapping) and bool(
        preflight_workspace.get("arbe_root")
        or preflight_workspace.get("path")
        or preflight_workspace.get("exists")
    )
    if workspace_present:
        _append_unique(replay_capabilities, _entry(
            "arbe-workspace",
            evidence=[ref for ref in refs if ref["label"] == "preflight"],
            details={"preflight_status": _status(preflight_obj)},
        ))
    else:
        unsupported.append({
            "id": "arbe-workspace",
            "reason": "preflight_workspace_not_proven",
            "required_inputs": ["arbe-preflight.v1 with workspace evidence"],
        })

    runtime_ready = isinstance(loaded["runtime_snapshot"], Mapping) and _status(
        loaded["runtime_snapshot"]
    ) in {"ready", "partial"}
    if runtime_ready:
        _append_unique(runtime_capabilities, _entry(
            "public-runtime-snapshot",
            evidence=[ref for ref in refs if ref["label"] == "runtime_snapshot"],
            details={"snapshot_status": _status(loaded["runtime_snapshot"])},
        ))
    else:
        unsupported.append({
            "id": "public-runtime-snapshot",
            "reason": "runtime_snapshot_not_supplied_or_not_ready",
            "required_inputs": ["runtime-snapshot-with-frame.v1"],
        })

    if isinstance(preflight_obj, Mapping):
        gdb = preflight_obj.get("gdb", {})
        if isinstance(gdb, Mapping) and (
            gdb.get("available") is True or gdb.get("status") in {"ready", "available"}
        ):
            _append_unique(runtime_capabilities, _entry(
                "headless-gdb",
                evidence=[ref for ref in refs if ref["label"] == "preflight"],
                details={"gdb": dict(gdb)},
            ))
        else:
            unsupported.append({
                "id": "headless-gdb",
                "reason": "preflight_gdb_not_proven",
                "required_inputs": ["preflight.gdb.available/status"],
            })
    else:
        unsupported.append({
            "id": "headless-gdb",
            "reason": "preflight_not_supplied",
            "required_inputs": ["arbe-preflight.v1 with gdb evidence"],
        })

    if isinstance(bundle_obj, Mapping) and _schema_is(bundle_obj, "diagnosis-bundle.v1", "viewer-model.v1"):
        _append_unique(presentation_capabilities, _entry(
            "sprint1-report",
            evidence=[ref for ref in refs if ref["label"] == "diagnosis_bundle"],
            details={"schema_version": bundle_obj.get("schema_version", "")},
        ))
        _append_unique(presentation_capabilities, _entry(
            "detailed-diagnostic-report",
            evidence=[ref for ref in refs if ref["label"] == "diagnosis_bundle"],
            details={"projection": "diagnostic-report.v1"},
            requires=["evidence-query"],
        ))
    else:
        unsupported.append({
            "id": "sprint1-report",
            "reason": "diagnosis_bundle_or_viewer_model_not_supplied",
            "required_inputs": ["diagnosis-bundle.v1/viewer-model.v1"],
        })

    # Explicit declarations are additive, but never replace evidence from
    # source/data artifacts. This lets a project adapter describe a capability
    # that cannot be inferred from the generic artifact envelope.
    if isinstance(declared_capabilities, Mapping):
        groups = {
            "data_capabilities": data_capabilities,
            "feature_capabilities": feature_capabilities,
            "code_capabilities": code_capabilities,
            "replay_capabilities": replay_capabilities,
            "runtime_capabilities": runtime_capabilities,
            "presentation_capabilities": presentation_capabilities,
        }
        for group_name, target in groups.items():
            declared = declared_capabilities.get(group_name, [])
            if not isinstance(declared, list):
                continue
            for item in declared:
                if isinstance(item, Mapping) and item.get("id"):
                    _append_unique(target, _entry(
                        str(item["id"]),
                        status=str(item.get("status", "declared")),
                        evidence=[ref for ref in refs if ref["label"] == str(item.get("evidence_label", ""))],
                        details=item.get("details", {}),
                        requires=item.get("requires", []),
                    ))

    diagnostics = list(dict.fromkeys(errors))
    if not refs:
        diagnostics.append("no_manifest_input_artifact")
    if errors or conflicts:
        status = "blocked"
    elif unsupported:
        status = "partial"
    elif code_ready and (data_capabilities or runtime_capabilities):
        status = "ready"
    else:
        status = "partial"
    source_snapshot_hash = (
        code_source_context.get("source_snapshot_hash")
        if isinstance(code_source_context, Mapping)
        else None
    )
    freshness = {
        "status": "fresh" if source_snapshot_hash and code_ready else "unknown",
        "source_snapshot_hash": source_snapshot_hash or "",
        "input_fingerprints": {
            ref["label"]: ref["sha256"] for ref in refs
        },
        "knowledge_consumption": "manifest_only",
    }
    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "identity": explicit_identity,
        "identity_provenance": identity_provenance,
        "data_capabilities": data_capabilities,
        "feature_capabilities": feature_capabilities,
        "code_capabilities": code_capabilities,
        "replay_capabilities": replay_capabilities,
        "runtime_capabilities": runtime_capabilities,
        "presentation_capabilities": presentation_capabilities,
        "freshness": {
            **freshness,
            "status": "conflict" if conflicts else freshness["status"],
        },
        "unsupported": unsupported,
        "conflicts": conflicts,
        "input_refs": refs,
        "diagnostics": diagnostics,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    manifest["manifest_fingerprint"] = _canonical_hash({
        key: value for key, value in manifest.items() if key not in {"generated_at", "manifest_fingerprint"}
    })
    return manifest


__all__ = [
    "ProjectCapabilityError",
    "SCHEMA_VERSION",
    "build_project_capability_manifest",
]
