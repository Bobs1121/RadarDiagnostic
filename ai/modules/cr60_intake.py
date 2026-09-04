# -*- coding: utf-8 -*-
"""Pi capability for material-first CR60 case/source intake.

This wrapper owns no inference.  It exposes :func:`engines.arbe.intake.build_intake`
as a standalone module so Pi can collect missing fields conversationally and
pass the resulting ``cr60-analysis-intake.v1`` artifact to data-prep,
arbe-preflight, code-learning, replay, and GDB capabilities.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from engines.arbe.intake import build_intake

from .base import BaseModule, ModuleResult


class CR60IntakeModule(BaseModule):
    """Build a provenance-preserving CR60 data/software binding artifact."""

    name = "cr60-intake"
    description = (
        "Read CR60 materials and explicit inputs; resolve data/software/vehicle/"
        "COEM candidates without guessing"
    )
    tags = ["cr60", "intake", "materials", "provenance"]
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "data_paths": {"type": "array", "items": {"type": "string"}},
            "material_paths": {"type": "array", "items": {"type": "string"}},
            "match_text": {"type": "array", "items": {"type": "string"}},
            "software_version": {"type": "string"},
            "vehicle": {"type": "string"},
            "customer": {"type": "string"},
            "coem": {"type": "string"},
            "code_branch": {"type": "string"},
            "ticket_id": {"type": "string"},
            "function": {"type": "array", "items": {"type": "string"}},
            "server_host": {"type": "string"},
            "server_user": {"type": "string"},
            "server_port": {"type": "integer"},
            "arbe_root": {"type": "string"},
            "algo_source_root": {"type": "string"},
            "code_root": {"type": "string"},
            "dbc": {"type": "string"},
            "cuda_sheet": {"type": "string"},
            "customer_claim": {"type": "string"},
            "preferred_radar": {},
            "output": {"type": "string"},
        },
        "additionalProperties": False,
    }
    output_schema: dict[str, Any] = {
        "type": "object",
        "required": ["schema_version", "status", "data", "identity", "source_context"],
    }

    def __init__(self, *, project_root: Path | str | None = None) -> None:
        self._project_root = (
            Path(project_root).resolve()
            if project_root
            else Path(__file__).resolve().parents[2]
        )

    def _resolve_output(self, output: str) -> Path:
        path = Path(output).expanduser()
        if not path.is_absolute():
            path = self._project_root / path
        return path.resolve()

    def run(
        self,
        *,
        data_paths: list[str] | None = None,
        material_paths: list[str] | None = None,
        match_text: list[str] | None = None,
        software_version: str = "",
        vehicle: str = "",
        customer: str = "",
        coem: str = "",
        code_branch: str = "",
        ticket_id: str = "",
        function: list[str] | None = None,
        server_host: str = "",
        server_user: str = "",
        server_port: int = 22,
        arbe_root: str = "",
        algo_source_root: str = "",
        code_root: str = "",
        dbc: str = "",
        cuda_sheet: str = "",
        customer_claim: str = "",
        preferred_radar: str = "auto",
        output: str = "",
        **_: Any,
    ) -> ModuleResult:
        try:
            payload = build_intake(
                data_paths=data_paths,
                material_paths=material_paths,
                match_text=match_text,
                software_version=software_version,
                vehicle=vehicle,
                customer=customer,
                coem=coem,
                code_branch=code_branch,
                ticket_id=ticket_id,
                function=function,
                server_host=server_host,
                server_user=server_user,
                server_port=int(server_port),
                arbe_root=arbe_root,
                algo_source_root=algo_source_root,
                code_root=code_root,
                dbc=dbc,
                cuda_sheet=cuda_sheet,
                customer_claim=customer_claim,
                preferred_radar=preferred_radar,
            )
        except Exception as exc:  # noqa: BLE001 - external material boundary
            return ModuleResult.fail(
                f"CR60 intake failed: {type(exc).__name__}: {exc}",
                module=self.name,
            )

        artifacts: list[str] = []
        if str(output or "").strip():
            output_path = self._resolve_output(output)
            try:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                artifacts.append(str(output_path))
                payload["artifact_path"] = str(output_path)
            except OSError as exc:
                return ModuleResult(
                    ok=False,
                    message=f"CR60 intake output write failed: {type(exc).__name__}: {exc}",
                    module=self.name,
                    data=payload,
                    artifacts=artifacts,
                )

        return ModuleResult.success(
            message=f"cr60-intake:{payload.get('status', 'unknown')}",
            module=self.name,
            artifacts=artifacts,
            **payload,
        )

    @classmethod
    def register_cli(cls, subparsers: Any) -> Any:
        parser = super().register_cli(subparsers)
        parser.add_argument(
            "--data",
            dest="data_paths",
            action="append",
            default=[],
            help="Data bag/file/directory; repeat for multiple data inputs.",
        )
        parser.add_argument(
            "--material",
            dest="material_paths",
            action="append",
            default=[],
            help="Material file or directory; repeatable.",
        )
        parser.add_argument(
            "--match",
            dest="match_text",
            action="append",
            default=[],
            help="Text used to select the matching row in an XLSX material.",
        )
        parser.add_argument("--software-version", default="")
        parser.add_argument("--vehicle", default="")
        parser.add_argument("--customer", default="")
        parser.add_argument("--coem", default="")
        parser.add_argument("--code-branch", default="")
        parser.add_argument("--ticket-id", default="")
        parser.add_argument(
            "--function",
            action="append",
            default=[],
            help="Known function; repeatable (e.g. FCTA, FCTB).",
        )
        parser.add_argument("--host", dest="server_host", default="")
        parser.add_argument("--user", dest="server_user", default="")
        parser.add_argument("--port", dest="server_port", type=int, default=22)
        parser.add_argument("--arbe-root", default="")
        parser.add_argument("--algo-source-root", default="")
        parser.add_argument("--code-root", default="")
        parser.add_argument("--dbc", default="")
        parser.add_argument("--cuda-sheet", default="")
        parser.add_argument("--customer-claim", default="")
        parser.add_argument("--preferred-radar", default="auto")
        parser.add_argument("--output", default="")
        return parser

    @classmethod
    def from_cli_args(cls, args: Any) -> "CR60IntakeModule":
        return cls()


__all__ = ["CR60IntakeModule"]
