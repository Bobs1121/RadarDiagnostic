# -*- coding: utf-8 -*-
"""Pi capability that delegates Sprint1 precheck to ``cr60-debug-harness``.

The capability is an adapter only.  It keeps the harness as the single owner
of rosbag/frame/object/ROI extraction and HTML rendering, while Pi receives a
structured provider result and can decide what to do next.
"""
from __future__ import annotations

from typing import Any

from ai.providers.cr60_harness import Cr60HarnessProvider

from .base import BaseModule, ModuleResult


class CR60PrecheckModule(BaseModule):
    """Plan or execute one Sprint1 folder/handoff analysis."""

    name = "cr60-precheck"
    description = (
        "Delegate deterministic CR60 Sprint1 folder/handoff analysis to the "
        "independent cr60-debug-harness"
    )
    tags = ["cr60", "sprint1", "bag", "report", "harness"]
    requires_approval = True
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "mode": {"enum": ["folder", "handoff", "manifest"]},
            "harness_root": {"type": "string"},
            "profile": {"type": "string"},
            "input_dir": {"type": "string"},
            "intake_path": {"type": "string"},
            "manifest_path": {"type": "string"},
            "output_dir": {"type": "string"},
            "context": {"type": "string"},
            "prepare_context": {"type": "boolean"},
            "max_source_files": {"type": "integer"},
            "functions": {"type": "array", "items": {"type": "string"}},
            "customer_claim": {"type": "string"},
            "web_dist": {"type": "string"},
            "allow_partial": {"type": "boolean"},
            "execute": {"type": "boolean"},
            "python_executable": {"type": "string"},
            "timeout_sec": {"type": "number"},
        },
        "required": ["mode", "harness_root", "profile", "output_dir"],
        "additionalProperties": False,
    }
    output_schema: dict[str, Any] = {
        "type": "object",
        "required": ["schema_version", "status", "mode", "command"],
    }

    def run(
        self,
        *,
        mode: str,
        harness_root: str,
        profile: str,
        output_dir: str,
        input_dir: str = "",
        intake_path: str = "",
        manifest_path: str = "",
        context: str = "",
        prepare_context: bool = False,
        max_source_files: int = 800,
        functions: list[str] | None = None,
        customer_claim: str = "",
        web_dist: str = "web/dist",
        allow_partial: bool = False,
        execute: bool = False,
        python_executable: str = "",
        timeout_sec: float = 3600.0,
        **_: Any,
    ) -> ModuleResult:
        if mode not in {"folder", "handoff", "manifest"}:
            return ModuleResult.fail(
                f"unsupported CR60 precheck mode: {mode}", module=self.name
            )
        if not str(harness_root or "").strip():
            return ModuleResult.fail("harness_root is required", module=self.name)
        if not str(profile or "").strip():
            return ModuleResult.fail("profile is required", module=self.name)
        if not str(output_dir or "").strip():
            return ModuleResult.fail("output_dir is required", module=self.name)
        if not context and not prepare_context:
            return ModuleResult.fail(
                "analysis context is required: provide context or set prepare_context=true",
                module=self.name,
            )
        if mode == "folder" and not str(input_dir or "").strip():
            return ModuleResult.fail("input_dir is required for folder mode", module=self.name)
        if mode == "handoff" and not str(intake_path or "").strip():
            return ModuleResult.fail("intake_path is required for handoff mode", module=self.name)
        if mode == "manifest" and not str(manifest_path or "").strip():
            return ModuleResult.fail("manifest_path is required for manifest mode", module=self.name)

        provider = Cr60HarnessProvider(
            harness_root=harness_root,
            python_executable=python_executable,
            timeout_sec=timeout_sec,
        )
        if mode == "folder":
            payload = provider.run_folder(
                profile=profile,
                input_dir=input_dir,
                output_dir=output_dir,
                context=context,
                prepare_context=prepare_context,
                max_source_files=max_source_files,
                functions=list(functions or []),
                customer_claim=customer_claim,
                web_dist=web_dist,
                execute=execute,
            )
        elif mode == "handoff":
            payload = provider.run_handoff(
                profile=profile,
                intake_path=intake_path,
                output_dir=output_dir,
                context=context,
                prepare_context=prepare_context,
                max_source_files=max_source_files,
                web_dist=web_dist,
                allow_partial=allow_partial,
                execute=execute,
            )
        else:
            payload = provider.run_manifest(
                profile=profile,
                manifest=manifest_path,
                output_dir=output_dir,
                context=context,
                prepare_context=prepare_context,
                max_source_files=max_source_files,
                web_dist=web_dist,
                execute=execute,
            )

        artifacts = list(payload.get("artifacts", []) or [])
        if payload.get("status") == "blocked":
            return ModuleResult(
                ok=False,
                message="cr60-precheck:blocked",
                module=self.name,
                data=payload,
                artifacts=artifacts,
            )
        return ModuleResult(
            ok=True,
            message=f"cr60-precheck:{payload.get('status', 'unknown')}",
            module=self.name,
            data=payload,
            artifacts=artifacts,
        )

    @classmethod
    def register_cli(cls, subparsers: Any) -> Any:
        parser = super().register_cli(subparsers)
        parser.add_argument("--mode", choices=["folder", "handoff", "manifest"], required=True)
        parser.add_argument("--harness-root", required=True)
        parser.add_argument("--profile", required=True)
        parser.add_argument("--input-dir", default="")
        parser.add_argument("--intake-path", default="")
        parser.add_argument("--manifest-path", default="")
        parser.add_argument("--output-dir", required=True)
        parser.add_argument("--context", default="")
        parser.add_argument("--prepare-context", action="store_true")
        parser.add_argument("--max-source-files", type=int, default=800)
        parser.add_argument("--function", dest="functions", action="append", default=[])
        parser.add_argument("--customer-claim", default="")
        parser.add_argument("--web-dist", default="web/dist")
        parser.add_argument("--allow-partial", action="store_true")
        parser.add_argument("--execute", action="store_true", help="run the generated harness command")
        parser.add_argument("--python-executable", default="")
        parser.add_argument("--timeout-sec", type=float, default=3600.0)
        return parser

    @classmethod
    def from_cli_args(cls, args: Any) -> "CR60PrecheckModule":
        return cls()


__all__ = ["CR60PrecheckModule"]
