# -*- coding: utf-8 -*-
"""ReqAnalyzeModule (V4 P7) — 需求→代码 gap 分析（复噪 core/materials + code-analyze）。

P7 需求：输入需求 + 代码仓 + 分支 → gap 报告（violations + requirement_trace），
并验证"新增模块后 pi 工具目录自动出现、无需改 pi 核心"（Q5 可插拔红线）。

与既有 ``req-review``（综述+review）的分工：``req-analyze`` 侧重**需求所引用
的代码符号（linked_functions / linked_files）在 CodeGraph 中是否真实存在**，
对缺失项标注 violation，对存在项补充调用链/信号上下文（复用 code-analyze）。

确定性、默认无 LLM：
- 需求从 ``req-dir`` 经 :class:`ai.requirements.loader.RequirementLoader` 加载；
- 需求→信号/源码 trace 经 :class:`ai.requirements.tracer.RequirementTracer`；
- 需求→代码 gap 用 CodeGraph（``get_function_by_name`` / ``get_signals_used_by``）
  逐条核对，缺失 → violation。

独立运行::

    python cli.py req-analyze --req-dir <requirements/> --variant gen6/byd_sc6h
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .base import BaseModule, ModuleResult
from core.materials import RequirementSpec, StructuredRequirementSet

log = logging.getLogger(__name__)


class ReqAnalyzeModule(BaseModule):
    name = "req-analyze"
    description = "需求→代码 gap 分析（violations + requirement_trace，复用 code-analyze）"

    def __init__(
        self,
        *,
        req_dir: str = "",
        variant_id: str = "",
        codegraph: Any | None = None,
        db_path: str = "",
    ):
        self.req_dir = Path(req_dir) if req_dir else None
        self.variant_id = variant_id
        self.codegraph = codegraph
        self.db_path = Path(db_path) if db_path else None

    def run(self, *, req_dir: str = "", variant_id: str = "",
            max_trace: int = 5, **_: Any) -> ModuleResult:
        req_dir = req_dir or (str(self.req_dir) if self.req_dir else "")
        variant_id = variant_id or self.variant_id
        if not req_dir:
            return ModuleResult.fail("需要 req_dir（需求 *.yaml 目录）", module=self.name)
        req_dir = Path(req_dir)
        if not req_dir.exists() or not req_dir.is_dir():
            return ModuleResult.fail(f"需求目录不存在: {req_dir}", module=self.name)

        # 1) 加载需求
        from ai.requirements.loader import RequirementLoader
        req_set = RequirementLoader().load_yaml_dir(req_dir, variant_id=variant_id)
        if not req_set.requirements:
            return ModuleResult.fail(f"未解析到任何需求: {req_dir}", module=self.name)

        # 2) 需求→信号 trace（复用 RequirementTracer）
        from ai.requirements.tracer import RequirementTracer
        tracer = RequirementTracer(
            codegraph=self._get_codegraph(), signal_mapping=None,
        )
        traces = tracer.trace_set(req_set)

        # 3) 需求→代码 gap：核对 linked_functions 是否存在于 CodeGraph
        graph = self._get_codegraph()
        violations, checked = self._code_gap(req_set, graph, max_trace)

        covered = sum(1 for t in traces if t.get("coverage") == "full")
        return ModuleResult.success(
            message=(
                f"req-analyze: {len(req_set.requirements)} requirement(s), "
                f"{len(violations)} code-gap violation(s), "
                f"trace {covered}/{len(traces)} fully covered"
            ),
            module=self.name,
            variant_id=req_set.variant_id,
            n_reqs=len(req_set.requirements),
            requirement_trace=traces,
            violations=violations,
            checked=checked,
        )

    # ── code-gap 分析 ------------------------------------------------

    def _code_gap(self, req_set: StructuredRequirementSet, graph, max_trace: int) -> tuple[list[dict], dict]:
        """逐需求核对 linked_functions 是否在 CodeGraph 中实现。

        返回 (violations, checked)：
        - violations: 需求引用但代码缺失的函数（含所在需求 id/优先级）。
        - checked:    统计（n_reqs / n_funcs / existing / missing）。
        """
        if graph is None:
            # 无 CodeGraph：降级为"无法核对"，不硬判 violation（Q4 鲁棒）
            return [], {"n_reqs": len(req_set.requirements), "codegraph": False}

        violations: list[dict] = []
        n_funcs_total = 0
        n_existing = 0
        for req in req_set.requirements.values():
            for fn in req.linked_functions:
                n_funcs_total += 1
                if graph.get_function_by_name(fn) is not None:
                    n_existing += 1
                    continue
                violations.append({
                    "requirement_id": req.requirement_id,
                    "priority": req.priority,
                    "function": fn,
                    "reason": "linked_function 未在 CodeGraph 中索引",
                    "scope": req.scope,
                })

        # 去重 + 上限
        seen: set[tuple] = set()
        deduped: list[dict] = []
        for v in violations:
            key = (v["requirement_id"], v["function"])
            if key in seen:
                continue
            seen.add(key)
            deduped.append(v)
            if len(deduped) >= max_trace:
                break

        return deduped, {
            "n_reqs": len(req_set.requirements),
            "n_function_refs": n_funcs_total,
            "existing": n_existing,
            "missing": len(deduped),
            "codegraph_available": True,
        }

    # ── codegraph 打开 ---------------------------------------------

    def _get_codegraph(self):
        if self.codegraph is not None:
            return self.codegraph
        if not self.db_path:
            try:
                from config import load_config, resolve_codegraph_db
                self.db_path = resolve_codegraph_db(load_config(), Path.cwd())
            except Exception:  # noqa: BLE001
                return None
        if not self.db_path or not self.db_path.exists():
            return None
        try:
            from ai.codegraph.query import CodeGraph
            graph = CodeGraph(self.db_path)
            if not getattr(graph, "is_available", True):
                return None
            self.codegraph = graph
            return graph
        except Exception:  # noqa: BLE001
            return None

    # ── CLI ---------------------------------------------

    @classmethod
    def register_cli(cls, subparsers: Any) -> Any:
        p = super().register_cli(subparsers)
        p.add_argument("--req-dir", default="", help="需求 *.yaml 目录")
        p.add_argument("--variant", default="", help="variant 作用域")
        p.add_argument("--max-trace", type=int, default=5, help="violation 输出上限")
        p.add_argument("--db-path", default="", help="codegraph.db 路径覆盖")
        p.set_defaults(_module_cls=cls)
        return p

    @classmethod
    def from_cli_args(cls, args: Any) -> "ReqAnalyzeModule":
        return cls(
            req_dir=getattr(args, "req_dir", ""),
            variant_id=getattr(args, "variant", ""),
            db_path=getattr(args, "db_path", ""),
        )


__all__ = ["ReqAnalyzeModule"]