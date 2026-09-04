# -*- coding: utf-8 -*-
"""Pi-visible read-only recall of existing variant-scoped memory."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from engines.memory_recall import MemoryRecallError, recall_memory

from .base import BaseModule, ModuleResult


class MemoryRecallModule(BaseModule):
    name = "memory-recall"
    description = "读取当前项目/功能/案例的历史记忆和相似案例"
    tags = ["memory", "recall", "provenance", "freshness", "read-only", "atomic"]
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "project_root": {"type": "string"},
            "function": {"type": "string"},
            "query": {"type": "string"},
            "case_dir": {"type": "string"},
            "variant_id": {"type": "string"},
            "memory_dir": {"type": "string"},
            "context": {"type": "object"},
            "context_path": {"type": "string"},
            "layers": {"type": ["array", "string"], "items": {"type": "string"}},
            "max_items": {"type": "integer", "default": 5},
            "max_chars": {"type": "integer", "default": 6000},
            "output": {"type": "string"},
        },
        "required": ["project_root"],
        "additionalProperties": False,
    }
    output_schema: dict[str, Any] = {"type": "object", "required": ["schema_version", "status", "items", "summary"]}

    def run(self, *, project_root: str, function: str = "", query: str = "", case_dir: str = "", variant_id: str = "", memory_dir: str = "", context: Mapping[str, Any] | None = None, context_path: str = "", layers: Any = None, max_items: int = 5, max_chars: int = 6000, output: str = "", **_: Any) -> ModuleResult:
        try:
            payload = recall_memory(project_root=project_root, function=function, query=query, case_dir=case_dir, variant_id=variant_id, memory_dir=memory_dir, context=context, context_path=context_path, layers=layers, max_items=max_items, max_chars=max_chars)
        except (MemoryRecallError, OSError, TypeError, ValueError) as exc:
            return ModuleResult.fail(f"memory-recall:failed: {exc}", module=self.name, error_type=type(exc).__name__)
        artifacts: list[str] = []
        if str(output or "").strip():
            path = Path(output).expanduser().resolve()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            payload["artifact_path"] = str(path)
            artifacts.append(str(path))
        return ModuleResult(ok=True, message=f"memory-recall:{payload.get('status')}", module=self.name, artifacts=artifacts, data=payload)

    @classmethod
    def register_cli(cls, subparsers: Any) -> Any:
        parser = super().register_cli(subparsers)
        parser.add_argument("--project-root", required=True)
        parser.add_argument("--function", default="")
        parser.add_argument("--query", default="")
        parser.add_argument("--case-dir", default="")
        parser.add_argument("--variant-id", default="")
        parser.add_argument("--memory-dir", default="")
        parser.add_argument("--context", dest="context_path", default="")
        parser.add_argument("--layers", default="")
        parser.add_argument("--max-items", type=int, default=5)
        parser.add_argument("--max-chars", type=int, default=6000)
        parser.add_argument("--output", default="")
        return parser

    @classmethod
    def from_cli_args(cls, args: Any) -> "MemoryRecallModule":
        if getattr(args, "layers", ""):
            args.layers = [item.strip() for item in str(args.layers).split(",") if item.strip()]
        return cls()


__all__ = ["MemoryRecallModule"]
