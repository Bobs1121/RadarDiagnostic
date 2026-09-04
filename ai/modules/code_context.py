# -*- coding: utf-8 -*-
"""Pi-visible atomic modules for one-time current-source indexing."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from engines.code_context import (
    CodeContextError,
    build_code_context,
    query_code_context,
)

from .base import BaseModule, ModuleResult


def _json_object(text: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"expected JSON object: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise ValueError("expected JSON object")
    return value


def _json_array(text: str) -> list[Any]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"expected JSON array: {exc.msg}") from exc
    if not isinstance(value, list):
        raise ValueError("expected JSON array")
    return value


class CodeContextRefreshModule(BaseModule):
    """Build or reuse a source-bound Code Context Snapshot."""

    name = "code-context-refresh"
    description = "一次性建立当前源码的确定性 Code Context Snapshot"
    tags = ["code", "context", "snapshot", "source-bound", "atomic", "local-write"]
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "source_root": {"type": "string"},
            "output_dir": {"type": "string"},
            "db_path": {"type": "string"},
            "key_files": {"type": "array", "items": {"type": "string"}},
            "calib_files": {"type": "array", "items": {"type": "string"}},
            "function_keywords": {"type": "object"},
            "source_identity": {"type": "object"},
            "source_docs_dir": {"type": "string"},
            "probe_git": {"type": "boolean"},
            "use_ast": {"type": "boolean"},
            "no_ast": {"type": "boolean"},
            "force": {"type": "boolean"},
            "max_files": {"type": "integer"},
        },
        "required": ["source_root"],
        "additionalProperties": False,
    }
    output_schema: dict[str, Any] = {
        "type": "object",
        "required": ["schema_version", "context_id", "source_context", "artifacts", "summary"],
    }

    def run(
        self,
        *,
        source_root: str,
        output_dir: str = "outputs/code_context",
        db_path: str = "",
        key_files: Sequence[str] | None = None,
        calib_files: Sequence[str] | None = None,
        function_keywords: Mapping[str, Sequence[str]] | None = None,
        source_identity: Mapping[str, Any] | None = None,
        source_docs_dir: str = "",
        probe_git: bool = True,
        use_ast: bool = True,
        no_ast: bool = False,
        force: bool = False,
        max_files: int = 20_000,
        **_: Any,
    ) -> ModuleResult:
        try:
            payload = build_code_context(
                source_root=source_root,
                output_dir=output_dir,
                db_path=db_path or None,
                key_files=key_files,
                calib_files=calib_files,
                function_keywords=function_keywords,
                source_identity=source_identity,
                source_docs_dir=source_docs_dir or None,
                probe_git=probe_git,
                use_ast=bool(use_ast) and not bool(no_ast),
                force=force,
                max_files=max_files,
            )
        except (CodeContextError, OSError, TypeError, ValueError) as exc:
            return ModuleResult.fail(
                f"code-context-refresh:failed: {exc}",
                module=self.name,
                error_type=type(exc).__name__,
            )

        artifacts = payload.get("artifacts", {}) or {}
        artifact_paths = [
            str(artifacts[key])
            for key in ("code_context", "code_index", "codegraph_db")
            if artifacts.get(key)
        ]
        operation = payload.get("operation", "built")
        return ModuleResult(
            ok=True,
            message=f"code-context-refresh:{operation}",
            module=self.name,
            artifacts=artifact_paths,
            data=payload,
        )

    @classmethod
    def register_cli(cls, subparsers: Any) -> Any:
        parser = super().register_cli(subparsers)
        parser.add_argument("--source-root", required=True)
        parser.add_argument("--output-dir", default="outputs/code_context")
        parser.add_argument("--db-path", default="")
        parser.add_argument("--key-file", dest="key_files", action="append", default=[])
        parser.add_argument("--calib-file", dest="calib_files", action="append", default=[])
        parser.add_argument("--function-keywords", type=_json_object, default={})
        parser.add_argument("--source-identity", type=_json_object, default={})
        parser.add_argument("--source-docs-dir", default="")
        parser.add_argument("--no-git-probe", dest="probe_git", action="store_false", default=True)
        parser.add_argument("--no-ast", action="store_true")
        parser.add_argument("--force", action="store_true")
        parser.add_argument("--max-files", type=int, default=20_000)
        return parser

    @classmethod
    def from_cli_args(cls, args: Any) -> "CodeContextRefreshModule":
        return cls()


class CodeContextReadModule(BaseModule):
    """Read a bounded section from a prepared context without scanning source."""

    name = "code-context-read"
    description = "读取已建立 Code Context 的指定代码关系或摘要"
    tags = ["code", "context", "read", "source-bound", "atomic", "read-only"]
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "context_path": {"type": "string"},
            "section": {
                "type": "string",
                "enum": [
                    "summary", "files", "functions", "calls", "variables_read",
                    "call_chain", "variables_written", "signals", "output_mapping", "conditions", "states",
                    "parameters", "semantics", "edges",
                ],
            },
            "query": {"type": "string"},
            "limit": {"type": "integer"},
        },
        "required": ["context_path"],
        "additionalProperties": False,
    }
    output_schema: dict[str, Any] = {
        "type": "object",
        "required": ["schema_version", "context", "section", "data", "index_path"],
    }

    def run(
        self,
        *,
        context_path: str,
        section: str = "summary",
        query: str = "",
        limit: int = 200,
        **_: Any,
    ) -> ModuleResult:
        try:
            payload = query_code_context(
                context_path,
                section=section,
                query=query,
                limit=limit,
            )
        except (CodeContextError, OSError, TypeError, ValueError) as exc:
            return ModuleResult.fail(
                f"code-context-read:failed: {exc}",
                module=self.name,
                error_type=type(exc).__name__,
            )
        return ModuleResult(
            ok=True,
            message=f"code-context-read:{payload['section']}",
            module=self.name,
            artifacts=[payload["context"]["artifact_path"], payload["index_path"]],
            data=payload,
        )

    @classmethod
    def register_cli(cls, subparsers: Any) -> Any:
        parser = super().register_cli(subparsers)
        parser.add_argument("--context-path", required=True)
        parser.add_argument("--section", default="summary")
        parser.add_argument("--query", default="")
        parser.add_argument("--limit", type=int, default=200)
        return parser

    @classmethod
    def from_cli_args(cls, args: Any) -> "CodeContextReadModule":
        return cls()


__all__ = ["CodeContextReadModule", "CodeContextRefreshModule"]
