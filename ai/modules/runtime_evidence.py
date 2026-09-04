# -*- coding: utf-8 -*-
"""Pi-callable runtime evidence producer/validator/merge capabilities."""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from engines.runtime_evidence import (
    compose_runtime_evidence,
    merge_runtime_evidence,
    normalize_runtime_evidence,
    runtime_summary,
    load_runtime_input,
    validate_runtime_binding,
    validate_runtime_evidence,
)

from .base import BaseModule, ModuleResult


def _write_json(payload: Mapping[str, Any], output: str, *, label: str) -> list[str]:
    if not str(output or "").strip():
        return []
    path = Path(output).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return [str(path)]


class RuntimeEvidenceNormalizeModule(BaseModule):
    """Convert a generic ``gdb-session.v1``/transcript into runtime evidence."""

    name = "runtime-evidence-normalize"
    description = "Normalize headless GDB or public arbe runtime facts into runtime-case-evidence.v1"
    tags = ["runtime", "gdb", "evidence", "normalize", "atomic"]
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "gdb_session": {"type": "object"},
            "gdb_session_path": {"type": "string"},
            "public_runtime_snapshot": {"type": "object"},
            "public_runtime_snapshot_path": {"type": "string"},
            "public_warning_names": {"type": "array", "items": {"type": "string"}},
            "transcript": {"type": "string"},
            "transcript_path": {"type": "string"},
            "stderr": {"type": "string"},
            "commands": {"type": "array", "items": {"type": "string"}},
            "run": {"type": "object"},
            "binding": {"type": "object"},
            "marker_field_map": {"type": "object"},
            "artifacts": {"type": "object"},
            "output": {"type": "string"},
        },
        "additionalProperties": False,
    }
    output_schema: dict[str, Any] = {
        "type": "object",
        "required": ["schema_version", "status", "run", "evidence_layers", "observations"],
    }

    def run(
        self,
        *,
        gdb_session: Mapping[str, Any] | None = None,
        gdb_session_path: str = "",
        public_runtime_snapshot: Mapping[str, Any] | None = None,
        public_runtime_snapshot_path: str = "",
        public_warning_names: list[str] | None = None,
        transcript: str = "",
        transcript_path: str = "",
        stderr: str = "",
        commands: list[str] | None = None,
        run: Mapping[str, Any] | None = None,
        binding: Mapping[str, Any] | None = None,
        marker_field_map: Mapping[str, Any] | None = None,
        artifacts: Mapping[str, Any] | None = None,
        output: str = "",
        **_: Any,
    ) -> ModuleResult:
        try:
            session = load_runtime_input(gdb_session, gdb_session_path, label="gdb_session")
            public_snapshot = load_runtime_input(
                public_runtime_snapshot,
                public_runtime_snapshot_path,
                label="public_runtime_snapshot",
            )
            effective_transcript = str(transcript or "")
            if transcript_path:
                effective_transcript = Path(transcript_path).expanduser().read_text(
                    encoding="utf-8", errors="replace"
                )
            if session is not None and public_snapshot is not None:
                return ModuleResult.fail(
                    "provide one runtime producer: GDB session or public runtime snapshot",
                    module=self.name,
                )
            payload = normalize_runtime_evidence(
                public_snapshot if public_snapshot is not None else session,
                transcript=effective_transcript,
                stderr=stderr,
                commands=list(commands or []),
                run=run,
                binding=binding,
                marker_field_map=marker_field_map,
                artifacts=artifacts,
                public_warning_names=public_warning_names,
            )
            artifact_paths = _write_json(payload, output, label="runtime_evidence")
            if artifact_paths:
                payload["artifact_path"] = artifact_paths[0]
        except (OSError, ValueError, TypeError) as exc:
            return ModuleResult.fail(
                f"runtime evidence normalization failed: {type(exc).__name__}: {exc}",
                module=self.name,
            )
        status = str(payload.get("status", "partial"))
        result_data = runtime_summary(payload)
        if artifact_paths:
            result_data["artifact_path"] = artifact_paths[0]
        return ModuleResult(
            ok=status not in {"blocked", "failed"},
            message=f"runtime-evidence-normalize:{status}",
            module=self.name,
            data=result_data,
            artifacts=[artifact_paths[0]] if artifact_paths else [],
        )

    @classmethod
    def register_cli(cls, subparsers: Any) -> Any:
        parser = super().register_cli(subparsers)
        parser.add_argument("--gdb-session-path", default="")
        parser.add_argument("--public-runtime-snapshot-path", default="")
        parser.add_argument("--public-warning-names", default="", help="JSON array")
        parser.add_argument("--transcript-path", default="")
        parser.add_argument("--transcript", default="")
        parser.add_argument("--stderr", default="")
        parser.add_argument("--command", dest="commands", action="append", default=[])
        parser.add_argument("--run", default="", help="JSON run binding")
        parser.add_argument("--binding", default="", help="JSON marker binding")
        parser.add_argument("--marker-field-map", default="", help="JSON marker-to-source-token map")
        parser.add_argument("--artifact", dest="artifacts", action="append", default=[], help="key=value artifact reference")
        parser.add_argument("--output", default="")
        return parser

    @classmethod
    def from_cli_args(cls, args: Any) -> "RuntimeEvidenceNormalizeModule":
        for name in ("run", "binding", "marker_field_map"):
            text = str(getattr(args, name, "") or "")
            if text:
                value = json.loads(text)
                if not isinstance(value, dict):
                    raise ValueError(f"{name} must be a JSON object")
                setattr(args, name, value)
            else:
                setattr(args, name, None)
        warning_names_text = str(getattr(args, "public_warning_names", "") or "")
        if warning_names_text:
            value = json.loads(warning_names_text)
            if not isinstance(value, list):
                raise ValueError("public_warning_names must decode to a JSON array")
            args.public_warning_names = [str(item) for item in value]
        else:
            args.public_warning_names = None
        artifacts: dict[str, str] = {}
        for item in getattr(args, "artifacts", []) or []:
            if "=" not in item:
                raise ValueError("--artifact must use key=value")
            key, value = item.split("=", 1)
            artifacts[key] = value
        args.artifacts = artifacts
        return cls()


class RuntimeEvidenceValidateModule(BaseModule):
    """Validate runtime evidence and optionally bind it to a static bundle."""

    name = "runtime-evidence-validate"
    description = "Validate runtime-case-evidence identity and event binding without changing artifacts"
    tags = ["runtime", "evidence", "validate", "atomic"]
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "runtime_evidence": {"type": "object"},
            "runtime_evidence_path": {"type": "string"},
            "bundle": {"type": "object"},
            "bundle_path": {"type": "string"},
        },
        "additionalProperties": False,
    }

    def run(
        self,
        *,
        runtime_evidence: Mapping[str, Any] | None = None,
        runtime_evidence_path: str = "",
        bundle: Mapping[str, Any] | None = None,
        bundle_path: str = "",
        **_: Any,
    ) -> ModuleResult:
        try:
            evidence = load_runtime_input(runtime_evidence, runtime_evidence_path, label="runtime_evidence")
            static_bundle = load_runtime_input(bundle, bundle_path, label="bundle")
            if evidence is None:
                return ModuleResult.fail("runtime_evidence or runtime_evidence_path is required", module=self.name)
            errors = validate_runtime_evidence(evidence)
            binding = validate_runtime_binding(static_bundle, evidence) if static_bundle is not None else None
            status = "blocked" if errors or binding and binding.get("status") == "conflict" else str((binding or {}).get("status", "partial"))
            payload = {
                "schema_version": "runtime-evidence-validation.v1",
                "status": status,
                "schema_errors": errors,
                "binding": binding,
                "summary": runtime_summary(evidence),
            }
        except (OSError, ValueError, TypeError) as exc:
            return ModuleResult.fail(
                f"runtime evidence validation failed: {type(exc).__name__}: {exc}",
                module=self.name,
            )
        return ModuleResult(
            ok=status not in {"blocked", "failed"},
            message=f"runtime-evidence-validate:{status}",
            module=self.name,
            data=payload,
        )

    @classmethod
    def register_cli(cls, subparsers: Any) -> Any:
        parser = super().register_cli(subparsers)
        parser.add_argument("--runtime-evidence-path", required=True)
        parser.add_argument("--bundle-path", default="")
        return parser


class RuntimeEvidenceComposeModule(BaseModule):
    """Compose already-normalized public/GDB producers into one evidence envelope."""

    name = "runtime-evidence-compose"
    description = "Compose public runtime and headless GDB evidence without dropping producer history"
    tags = ["runtime", "evidence", "compose", "atomic"]
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "left": {"type": "object"},
            "left_path": {"type": "string"},
            "right": {"type": "object"},
            "right_path": {"type": "string"},
            "output": {"type": "string"},
        },
        "required": ["output"],
        "additionalProperties": False,
    }
    output_schema: dict[str, Any] = {
        "type": "object",
        "required": ["schema_version", "status", "run_count", "evidence_layers", "observations"],
    }

    def run(
        self,
        *,
        left: Mapping[str, Any] | None = None,
        left_path: str = "",
        right: Mapping[str, Any] | None = None,
        right_path: str = "",
        output: str = "",
        **_: Any,
    ) -> ModuleResult:
        try:
            if not str(output or "").strip():
                return ModuleResult.fail(
                    "output is required for runtime-evidence-compose",
                    module=self.name,
                )
            left_obj = load_runtime_input(left, left_path, label="left_runtime_evidence")
            right_obj = load_runtime_input(right, right_path, label="right_runtime_evidence")
            if left_obj is None or right_obj is None:
                return ModuleResult.fail(
                    "left/left_path and right/right_path are required",
                    module=self.name,
                )
            payload = compose_runtime_evidence(left_obj, right_obj)
            artifact_paths = _write_json(payload, output, label="runtime_evidence_composite")
            if artifact_paths:
                payload["artifact_path"] = artifact_paths[0]
        except (OSError, ValueError, TypeError) as exc:
            return ModuleResult.fail(
                f"runtime evidence composition failed: {type(exc).__name__}: {exc}",
                module=self.name,
            )
        result_data = runtime_summary(payload)
        if artifact_paths:
            result_data["artifact_path"] = artifact_paths[0]
        return ModuleResult(
            ok=payload.get("status") not in {"blocked", "failed"},
            message=f"runtime-evidence-compose:{payload.get('status', 'partial')}",
            module=self.name,
            data=result_data,
            artifacts=artifact_paths,
        )

    @classmethod
    def register_cli(cls, subparsers: Any) -> Any:
        parser = super().register_cli(subparsers)
        parser.add_argument("--left-path", required=True)
        parser.add_argument("--right-path", required=True)
        parser.add_argument("--output", required=True)
        return parser


class RuntimeEvidenceMergeModule(BaseModule):
    """Create a static-plus-runtime derived bundle without overwriting facts."""

    name = "runtime-evidence-merge"
    description = "Bind runtime evidence to a diagnosis bundle and emit additive runtime overlay"
    tags = ["runtime", "evidence", "merge", "atomic"]
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "bundle": {"type": "object"},
            "bundle_path": {"type": "string"},
            "runtime_evidence": {"type": "object"},
            "runtime_evidence_path": {"type": "string"},
            "scope": {"type": "object"},
            "output": {"type": "string"},
        },
        "required": ["output"],
        "additionalProperties": False,
    }
    output_schema: dict[str, Any] = {
        "type": "object",
        "required": ["schema_version", "runtime_evidence", "runtime_merge"],
    }

    def run(
        self,
        *,
        bundle: Mapping[str, Any] | None = None,
        bundle_path: str = "",
        runtime_evidence: Mapping[str, Any] | None = None,
        runtime_evidence_path: str = "",
        scope: Mapping[str, Any] | None = None,
        output: str = "",
        **_: Any,
    ) -> ModuleResult:
        try:
            if not str(output or "").strip():
                return ModuleResult.fail(
                    "output is required for runtime-evidence-merge; use the artifact reference for Pi composition",
                    module=self.name,
                )
            static_bundle = load_runtime_input(bundle, bundle_path, label="bundle")
            evidence = load_runtime_input(runtime_evidence, runtime_evidence_path, label="runtime_evidence")
            if static_bundle is None or evidence is None:
                return ModuleResult.fail(
                    "bundle/bundle_path and runtime_evidence/runtime_evidence_path are required",
                    module=self.name,
                )
            merged = merge_runtime_evidence(static_bundle, evidence, scope=scope)
            artifact_paths = _write_json(merged, output, label="merged_bundle")
            if artifact_paths:
                merged["artifact_path"] = artifact_paths[0]
        except (OSError, ValueError, TypeError) as exc:
            return ModuleResult.fail(
                f"runtime evidence merge failed: {type(exc).__name__}: {exc}",
                module=self.name,
            )
        status = str((merged.get("runtime_merge", {}) or {}).get("status", "blocked"))
        result_data: dict[str, Any]
        if artifact_paths:
            # The merged bundle can contain thousands of frame records.  Pi
            # receives the artifact reference and a bounded deterministic
            # summary; callers that explicitly need the full bundle read the
            # declared artifact rather than flooding the tool response.
            result_data = {
                "schema_version": merged.get("schema_version", "diagnosis-bundle.v1"),
                "status": status,
                "runtime_evidence": runtime_summary(merged.get("runtime_evidence", {}) or {}),
                "runtime_merge": deepcopy(dict(merged.get("runtime_merge", {}) or {})),
                "bundle_artifact": artifact_paths[0],
            }
        else:
            result_data = merged
        return ModuleResult(
            ok=status not in {"blocked", "failed"},
            message=f"runtime-evidence-merge:{status}",
            module=self.name,
            data=result_data,
            artifacts=artifact_paths if artifact_paths else [],
        )

    @classmethod
    def register_cli(cls, subparsers: Any) -> Any:
        parser = super().register_cli(subparsers)
        parser.add_argument("--bundle-path", required=True)
        parser.add_argument("--runtime-evidence-path", required=True)
        parser.add_argument("--scope", type=json.loads, default=None, help="JSON event/frame/object slice")
        parser.add_argument("--output", required=True)
        return parser


__all__ = [
    "RuntimeEvidenceComposeModule",
    "RuntimeEvidenceMergeModule",
    "RuntimeEvidenceNormalizeModule",
    "RuntimeEvidenceValidateModule",
]
