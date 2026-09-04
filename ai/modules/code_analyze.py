# -*- coding: utf-8 -*-
"""CodeAnalyzeModule (V4 P5) — 代码分析（调用链 / 依赖 / 语义）。

基于 CodeGraph（.workspaces/<variant>/memory/codegraph/codegraph.db）回答
代码结构问题，供 pi 调度做代码层级分析 / 定位。确定性、无 LLM。

独立运行::

    python cli.py code-analyze --kind callers --name FctbAlarmProcess
    python cli.py code-analyze --kind call_chain --name FctbAlarmProcess --max-depth 5
"""
from __future__ import annotations

import dataclasses
import json
import logging
from pathlib import Path
from collections.abc import Mapping
from typing import Any

from .base import BaseModule, ModuleResult

log = logging.getLogger(__name__)

KINDS: tuple[str, ...] = (
    "function",      # 查函数定义
    "callers",       # 谁调用它
    "callees",       # 它调用谁
    "call_chain",    # 完整调用链
    "signals_of",    # 该函数用到的信号
    "vars_read",     # 读的变量
    "vars_written",  # 写的变量
    "calib",         # 标定参数
    "conditions",    # 源码条件
    "stats",         # 索引统计
)


def _to_jsonable(obj: Any) -> Any:
    if obj is None:
        return None
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return dataclasses.asdict(obj)
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(x) for x in obj]
    if isinstance(obj, set):
        return [_to_jsonable(x) for x in sorted(obj, key=str)]
    return obj


class CodeAnalyzeModule(BaseModule):
    name = "code-analyze"
    description = "代码分析：调用链 / 依赖 / 语义（基于 CodeGraph）"
    tags = ["code", "analyze", "source-bound", "atomic"]
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": list(KINDS)},
            "name": {"type": "string"},
            "signal": {"type": "string"},
            "max_depth": {"type": "integer"},
            "db_path": {"type": "string"},
            "source_root": {"type": "string"},
            "code_index_path": {"type": "string"},
            "code_index": {"type": "object"},
            "output": {"type": "string"},
        },
        "additionalProperties": False,
    }
    output_schema: dict[str, Any] = {
        "type": "object",
        "required": ["kind", "backend", "source_context", "data"],
    }

    def __init__(
        self,
        *,
        db_path: str = "",
        source_root: str = "",
        code_index_path: str = "",
        code_index: Mapping[str, Any] | None = None,
    ):
        self.db_path = Path(db_path) if db_path else None
        self.source_root = source_root
        self.code_index_path = Path(code_index_path) if code_index_path else None
        self._source_index = dict(code_index) if isinstance(code_index, Mapping) else None
        self._graph = None

    def _get_graph(self):
        if self._graph is not None:
            return self._graph
        if not self.db_path or not self.db_path.exists():
            # 尝试从 config 解析默认 codegraph 路径
            try:
                from config import load_config, resolve_codegraph_db
                cfg = load_config()
                self.db_path = resolve_codegraph_db(cfg, Path.cwd())
            except Exception:
                return None
        if not self.db_path or not self.db_path.exists():
            return None
        try:
            from ..codegraph.query import CodeGraph
        except Exception:  # noqa: BLE001
            return None
        graph = CodeGraph(self.db_path)
        if not getattr(graph, "is_available", True):
            return None
        self._graph = graph
        return graph

    def run(
        self,
        *,
        kind: str = "callers",
        name: str = "",
        signal: str = "",
        max_depth: int = 5,
        code_index_path: str = "",
        code_index: Mapping[str, Any] | None = None,
        output: str = "",
        **_: Any,
    ) -> ModuleResult:
        if kind not in KINDS:
            return ModuleResult.fail(f"kind 需 ∈ {KINDS}", module=self.name)

        # A prepared CR60 analysis context owns the source index for the exact
        # outer/algo snapshot. Prefer it over the legacy project-default DB so
        # a different vehicle/branch's graph cannot be queried accidentally.
        try:
            index = self._load_source_index(code_index_path, code_index)
        except Exception as exc:  # noqa: BLE001 - artifact boundary
            return ModuleResult.fail(
                f"source code-index analysis failed: {type(exc).__name__}: {exc}",
                module=self.name,
            )
        if index is not None:
            try:
                data = self._dispatch_source_index(index, kind, name, signal, max_depth)
            except Exception as exc:  # noqa: BLE001 - artifact boundary
                return ModuleResult.fail(
                    f"source code-index analysis failed: {type(exc).__name__}: {exc}",
                    module=self.name,
                )
            if data is None:
                return ModuleResult.fail(f"未找到: {name or signal}", module=self.name)
            result = ModuleResult.success(
                message=f"code-analyze {kind}: source-index done",
                module=self.name,
                kind=kind,
                backend="source_code_index",
                source_context=self._source_context(index),
                data=_to_jsonable(data),
            )
            return self._write_output(result, output)

        if kind == "conditions":
            return ModuleResult.fail(
                "conditions 查询需要当前 source code_index.json；请传入 code_index_path",
                module=self.name,
            )

        graph = self._get_graph()
        if graph is None:
            return ModuleResult.fail(
                "CodeGraph 不可用（缺少 codegraph.db，" 
                "先运行 --codegraph-stats 或诊断触发建图）",
                module=self.name,
            )

        try:
            data = self._dispatch(kind, graph, name, signal, max_depth)
        except Exception as exc:  # noqa: BLE001
            return ModuleResult.fail(f"{type(exc).__name__}: {exc}", module=self.name)

        if data is None:
            return ModuleResult.fail(f"未找到: {name or signal}", module=self.name)
        result = ModuleResult.success(
            message=f"code-analyze {kind}: done",
            module=self.name,
            backend="codegraph_db",
            source_context={"source_root": self.source_root},
            kind=kind,
            data=_to_jsonable(data),
        )
        return self._write_output(result, output)

    @staticmethod
    def _write_output(result: ModuleResult, output: str) -> ModuleResult:
        if not str(output or "").strip():
            return result
        path = Path(output).expanduser().resolve()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(result.data, ensure_ascii=False, indent=2), encoding="utf-8")
            result.artifacts.append(str(path))
            result.data["artifact_path"] = str(path)
            return result
        except OSError as exc:
            return ModuleResult.fail(
                f"code-analyze output failed: {type(exc).__name__}: {exc}",
                module="code-analyze",
            )

    def _load_source_index(
        self,
        code_index_path: str,
        code_index: Mapping[str, Any] | None,
    ) -> dict[str, Any] | None:
        if isinstance(code_index, Mapping):
            return dict(code_index)
        path = Path(code_index_path).expanduser() if code_index_path else self.code_index_path
        if path is None:
            return self._source_index
        if not path.exists():
            raise FileNotFoundError(f"code index not found: {path}")
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("code index root must be an object")
        return value

    @staticmethod
    def _source_context(index: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "source_root": index.get("source_root", ""),
            "snapshot_hash": index.get("snapshot_hash", ""),
            "parser": index.get("parser", "unknown"),
            "diagnostics": list(index.get("diagnostics", []) or []),
        }

    @staticmethod
    def _source_functions(index: Mapping[str, Any]) -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in index.get("functions", []) or []
            if isinstance(row, Mapping)
        ]

    @classmethod
    def _source_function(cls, index: Mapping[str, Any], name: str) -> dict[str, Any] | None:
        rows = [row for row in cls._source_functions(index) if str(row.get("name", "")) == name]
        return rows[0] if len(rows) == 1 else None

    @staticmethod
    def _source_edges(index: Mapping[str, Any], function: str) -> list[str]:
        calls = index.get("calls", {})
        if isinstance(calls, Mapping):
            value = calls.get(function, [])
            if isinstance(value, list):
                return [str(item) for item in value if str(item).strip()]
        return []

    @classmethod
    def _source_callers(cls, index: Mapping[str, Any], function: str) -> list[str]:
        calls = index.get("calls", {})
        if not isinstance(calls, Mapping):
            return []
        return sorted(
            {
                str(caller)
                for caller, callees in calls.items()
                if isinstance(callees, list) and function in {str(item) for item in callees}
            }
        )

    @classmethod
    def _source_rows(cls, index: Mapping[str, Any], key: str, function: str) -> list[Any]:
        value = index.get(key, {})
        if isinstance(value, Mapping):
            rows = value.get(function, [])
            return list(rows) if isinstance(rows, list) else []
        return [
            dict(row)
            for row in value or []
            if isinstance(row, Mapping) and str(row.get("function", "")) == function
        ]

    @classmethod
    def _source_call_chain(
        cls, index: Mapping[str, Any], root: str, max_depth: int
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        queue: list[tuple[str, int, list[str]]] = [(root, 0, [root])]
        seen: set[tuple[str, tuple[str, ...]]] = set()
        while queue:
            current, depth, path = queue.pop(0)
            if depth >= max(1, int(max_depth)):
                continue
            for callee in cls._source_edges(index, current):
                next_path = [*path, callee]
                marker = (callee, tuple(next_path))
                if marker in seen:
                    continue
                seen.add(marker)
                result.append(
                    {
                        "caller": current,
                        "callee": callee,
                        "depth": depth + 1,
                        "path": " -> ".join(next_path),
                    }
                )
                if callee not in path:
                    queue.append((callee, depth + 1, next_path))
        return result

    @classmethod
    def _dispatch_source_index(
        cls,
        index: Mapping[str, Any],
        kind: str,
        name: str,
        signal: str,
        max_depth: int,
    ) -> Any:
        if kind == "stats":
            calls = index.get("calls", {})
            return {
                "source_root": index.get("source_root", ""),
                "snapshot_hash": index.get("snapshot_hash", ""),
                "files": len(index.get("files", []) or []),
                "functions": len(index.get("functions", []) or []),
                "calls": len(calls) if isinstance(calls, Mapping) else len(calls or []),
                "conditions": len(index.get("conditions", []) or []),
                "parameters": len(index.get("parameters", []) or []),
            }
        if kind == "calib":
            rows = [
                dict(row)
                for row in index.get("parameters", []) or []
                if isinstance(row, Mapping)
            ]
            return [
                row
                for row in rows
                if not name
                or str(row.get("category", "")) == name
                or name in str(row.get("name", ""))
            ]
        if kind == "conditions":
            rows = [
                dict(row)
                for row in index.get("conditions", []) or []
                if isinstance(row, Mapping)
            ]
            if name:
                rows = [row for row in rows if str(row.get("function", "")) == name]
            if signal:
                rows = [row for row in rows if signal in str(row.get("expression", ""))]
            return rows
        if kind == "signals_of":
            return cls._source_rows(index, "signals", name) or cls._source_rows(
                index, "variables_read", name
            )
        if not name:
            return None
        if kind == "function":
            return cls._source_function(index, name)
        if kind == "callers":
            return cls._source_callers(index, name)
        if kind == "callees":
            return cls._source_edges(index, name)
        if kind == "call_chain":
            return cls._source_call_chain(index, name, max_depth)
        if kind == "vars_read":
            return cls._source_rows(index, "variables_read", name)
        if kind == "vars_written":
            return cls._source_rows(index, "variables_written", name)
        return None

    # ------------------------------------------------------------------

    def _dispatch(self, kind, graph, name, signal, max_depth):
        if kind == "function":
            return graph.get_function_by_name(name) if name else None
        if kind == "callers":
            return self._name(graph.get_callers(name), "caller_name") if name else []
        if kind == "callees":
            return self._name(graph.get_callees(name), "callee_name") if name else []
        if kind == "call_chain":
            return graph.get_call_chain(name, max_depth=max_depth) if name else []
        if kind == "signals_of":
            return graph.get_signals_used_by(name) if name else []
        if kind == "vars_read":
            return graph.get_variables_read_by(name) if name else []
        if kind == "vars_written":
            return graph.get_variables_written_by(name) if name else []
        if kind == "calib":
            # name 作 category 过滤（可空）；返回 CALIB_PARAM 节点列表
            return graph.get_calibration_params(name or None)
        if kind == "stats":
            return graph.get_stats()
        return None

    @staticmethod
    def _name(rows, key):
        if not rows:
            return []
        out = []
        for row in rows:
            if isinstance(row, dict):
                v = row.get(key) or row.get("name")
            else:
                v = getattr(row, key, None) or getattr(row, "name", None)
            if v and v not in out:
                out.append(str(v))
        return out[:50]

    @classmethod
    def register_cli(cls, subparsers):
        p = super().register_cli(subparsers)
        p.add_argument("--kind", default="callers", choices=KINDS)
        p.add_argument("--name", default="", help="函数名")
        p.add_argument("--signal", default="", help="信号名")
        p.add_argument("--max-depth", type=int, default=5)
        p.add_argument("--db-path", default="", help="codegraph.db 路径")
        p.add_argument("--source-root", default="", help="代码根")
        p.add_argument("--code-index-path", default="", help="当前 source snapshot 的 code_index.json")
        p.set_defaults(_module_cls=cls)
        return p

    @classmethod
    def from_cli_args(cls, args: Any) -> "CodeAnalyzeModule":
        return cls(db_path=getattr(args, "db_path", ""),
                   source_root=getattr(args, "source_root", ""),
                   code_index_path=getattr(args, "code_index_path", ""))


__all__ = ["CodeAnalyzeModule", "KINDS"]
