# -*- coding: utf-8 -*-
"""
VariableQueryPlanner — LLM-driven planner that decides **what to measure**.

Design intent
-------------
The pipeline used to ask questions it had hand-coded into evidence extractors
(e.g. "extract target speeds", "extract ego speed", "extract warning
timeline"). That works for routine cases but fails whenever the actual root
cause lives in a variable no one wrote an extractor for — such as the LCA
lateral-ROI boundary case where ``objectRightCutIn = obj_y + 0.25*obj_width``
needs to be compared against ``LineBSDLCAL = -3.3 - EgoWidth/2``.

This planner delegates the "what to probe" decision to the LLM, grounded in:

  1. The ``problem`` and ``focus_parameters`` (from the classify phase)
  2. The L6 code knowledge for the function in question (variables, thresholds)
  3. A compact field inventory of the available data tables

The output is a strict JSON list of probe queries consumed by
:class:`engines.data_probe.DataProbe`. The planner never executes queries — it
only plans.

Contract with DataProbe
-----------------------
Each planned query must be representable as::

    {
      "field":     <column or arithmetic expression>,
      "table":     "radar_objects" | "radar_debug" | "warning_events",
      "group_by":  <column or semantic field, optional>,
      "filter":    <boolean expression, optional>,
      "stats":     ["count","min","max","mean","p50","p90"],
      "reasoning": <why this query, 1 sentence>
    }

Error behaviour
---------------
If the LLM produces malformed or empty JSON, the planner falls back to a
small default plan derived from the focus parameters (it still produces
*something* useful — never a hard failure).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from .utils import parse_json_from_llm, ALL_FUNCTIONS


_SYSTEM_PROMPT = """你是一个雷达数据诊断的"查询规划员"。

你的职责：**根据问题描述、功能代码知识、可查字段清单，规划出一组数据查询**，
让 Expert Panel 在后续诊断时看到"最能揭示问题"的统计证据。

你**不要**：
- 给出诊断结论
- 解释代码逻辑
- 建议要修改什么

你**必须**：
- 输出严格的 JSON，key = "queries"，value 是对象数组
- 每条查询只用给定的字段名或它们的算术表达式
- 用 `&` `|` `~` 做布尔组合（不要 `and` `or` `not`）——系统会自动转但建议直接用位运算符
- 对每条查询写一行 `reasoning`（为什么要查这个）
- 最多 6 条查询（保持聚焦）"""

_USER_TEMPLATE = """## 问题描述
{problem}

## 预期行为
{expected}

## 功能
{func_name}（fail_type: {fail_type}）

## 诊断焦点参数
{focus_params}

## 已学的代码知识（L6）
{code_knowledge}

## 已学数值常量（全局，可直接写入查询表达式）
{constants}

## 可查数据表 & 字段
{inventory}

## 语义派生字段（可直接用）
- `side`：`'left' if dist_y >= 0 else 'right'`（仅在 radar_objects 表可用）
- `in_window`：当前行时间戳是否落在任一测试窗口内（bool）
- `is_stable_target`：`life_cycle >= 5`（仅 radar_objects）—— 目标已被雷达稳定
  跟踪数帧，排除闪烁/瞬现鬼影。**对任何涉及目标距离/ROI/速度的查询，默认在
  filter 里加 `is_stable_target`**（除非你明确要研究跟踪不稳定性本身）。

## 已有基础 evidence（不要重复查）
Expert Panel 已经能看到：每个测试窗口的 target 速度/距离基础统计、ego 速度、
warning 状态跳变、帧级时间线。请**聚焦代码知识揭示的、不在基础 evidence 里的变量**。

## 重要：阈值数值化
如果"已学数值常量"里已经有某个 ROI 边界（例如 `LineBSDLCAL = -4.288 m`），
**请直接在 filter 里用数字**（如 `filter: "in_window & (dist_y < -4.288)"`），
这样 probe 返回的统计能直接被专家拿去做"超出/未超出"的数值判断。

## 输出格式（严格 JSON）
```json
{{
  "queries": [
    {{
      "field": "dist_y + 0.25 * 2.0",
      "table": "radar_objects",
      "group_by": "side",
      "filter": "in_window & (dist_x < 0)",
      "stats": ["count", "min", "max", "p50", "p90"],
      "reasoning": "LCA 横向 ROI 判定：目标最远角点 rightCutIn 与边界 ±4.12 比较"
    }}
  ]
}}
```

请基于**本次问题 + 功能的 L6 知识**给出查询。"""


class QueryPlan:
    """One planned probe query (thin validated wrapper around dict)."""

    ALLOWED_TABLES = ("radar_objects", "radar_debug", "warning_events")
    ALLOWED_STATS = {"count", "min", "max", "mean", "std", "p10", "p50", "p90"}

    def __init__(self, spec: dict):
        self.field: str = str(spec.get("field", "")).strip()
        self.table: str = str(spec.get("table", "radar_objects")).strip()
        self.group_by: Optional[str] = spec.get("group_by") or None
        self.filter: Optional[str] = spec.get("filter") or None
        raw_stats = spec.get("stats") or ["count", "min", "max", "p50", "p90"]
        self.stats: list[str] = [s for s in raw_stats if s in self.ALLOWED_STATS]
        self.reasoning: str = str(spec.get("reasoning", "")).strip()

    # ------------------------------------------------------------------

    def is_valid(self) -> bool:
        if not self.field:
            return False
        if self.table not in self.ALLOWED_TABLES:
            return False
        if not self.stats:
            return False
        return True

    def to_dict(self) -> dict:
        """Full spec including ``reasoning`` (for logging/rendering)."""
        d: dict[str, Any] = {
            "field": self.field,
            "table": self.table,
            "stats": self.stats,
        }
        if self.group_by:
            d["group_by"] = self.group_by
        if self.filter:
            d["filter"] = self.filter
        if self.reasoning:
            d["reasoning"] = self.reasoning
        return d

    def to_query_args(self) -> dict:
        """Args suitable for :meth:`DataProbe.query` (drops ``reasoning``)."""
        d: dict[str, Any] = {
            "field": self.field,
            "table": self.table,
            "stats": self.stats,
        }
        if self.group_by:
            d["group_by"] = self.group_by
        if self.filter:
            d["filter"] = self.filter
        return d

    def __repr__(self) -> str:
        parts = [f"field={self.field!r}", f"table={self.table!r}"]
        if self.group_by:
            parts.append(f"group_by={self.group_by!r}")
        if self.filter:
            parts.append(f"filter={self.filter!r}")
        return "QueryPlan(" + ", ".join(parts) + ")"


class VariableQueryPlanner:
    """Produce a list of :class:`QueryPlan` for the Expert Panel to consume."""

    def __init__(self, router, memory_system, project_root: Path, config: dict | None = None):
        self.router = router
        self.memory = memory_system
        self.project_root = project_root
        self.config = config or {}

    # ------------------------------------------------------------------

    def plan(
        self,
        problem: str,
        expected: str,
        func_name: str,
        fail_type: str,
        focus_params: list[str],
        store,
        *,
        max_queries: int = 6,
        use_thinking: bool = False,
    ) -> list[QueryPlan]:
        """Generate a query plan.

        Uses the remote (complex) model with a short ``max_tokens`` budget
        since the output is a small JSON. Falls back to a deterministic
        default plan on any error.
        """
        knowledge_txt = self._render_code_knowledge(func_name)
        constants_txt = self._render_constants(func_name)
        inventory_txt = self._render_inventory(store)
        focus_txt = ", ".join(focus_params) if focus_params else "(未分类)"

        user_msg = _USER_TEMPLATE.format(
            problem=problem or "(未提供)",
            expected=expected or "(未提供)",
            func_name=func_name or "UNKNOWN",
            fail_type=fail_type or "UNKNOWN",
            focus_params=focus_txt,
            code_knowledge=knowledge_txt,
            constants=constants_txt,
            inventory=inventory_txt,
        )

        try:
            resp = self.router.chat(
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                complexity="complex",
                temperature=0.2,
                max_tokens=1800,
                thinking=use_thinking,
            )
            raw = resp.get("content", "") if isinstance(resp, dict) else ""
        except Exception as e:
            return self._fallback_plan(focus_params, func_name, reason=f"router error: {e}")

        parsed = parse_json_from_llm(raw, fallback={})
        queries = parsed.get("queries") if isinstance(parsed, dict) else None
        if not isinstance(queries, list) or not queries:
            return self._fallback_plan(focus_params, func_name,
                                       reason="empty or malformed plan")

        plans: list[QueryPlan] = []
        for spec in queries[:max_queries]:
            if not isinstance(spec, dict):
                continue
            qp = QueryPlan(spec)
            if qp.is_valid():
                plans.append(qp)

        if not plans:
            return self._fallback_plan(focus_params, func_name,
                                       reason="no valid query in response")
        return plans

    # ------------------------------------------------------------------

    def _render_code_knowledge(self, func_name: str, max_chars: int = 4000) -> str:
        """Pull code knowledge for ``func_name``.

        Priority: CodeGraph (structured) > L6 JSON (legacy).
        """
        # Try CodeGraph first
        codegraph_md = ""
        try:
            from .codegraph import CodeGraph, CodeGraphRenderer
            from config import resolve_codegraph_db
            cg_path = resolve_codegraph_db(self.config, self.project_root)
            if cg_path.exists():
                cg = CodeGraph(cg_path)
                renderer = CodeGraphRenderer(cg)
                if func_name:
                    codegraph_md = renderer.render_for_probe(func_name, max_chars=max_chars)
                # Also try module-level context
                for module in ALL_FUNCTIONS:
                    funcs = cg.get_functions_by_module(module)
                    func_names = [f.name for f in funcs]
                    if func_name in func_names or any(func_name.lower() in fn.lower() for fn in func_names):
                        module_md = renderer.render_for_problem(module, max_chars=max_chars // 2)
                        if module_md and module_md not in codegraph_md:
                            codegraph_md = module_md + "\n" + codegraph_md
                        break
                cg.close()
        except Exception:
            pass

        if codegraph_md:
            return codegraph_md[:max_chars]

        # Fallback to legacy L6 JSON
        if not self.memory or not func_name:
            return "(暂无代码知识)"
        try:
            rendered = self.memory.render_code_knowledge_for_context(
                func_name, max_chars=max_chars
            )
        except Exception:
            rendered = ""
        return rendered or "(暂无代码知识)"

    def _render_constants(self, func_name: str, max_chars: int = 1800) -> str:
        """Pull the global numeric-constants table, filtered to ``func_name``.

        This is what makes the Planner able to write
        ``filter: "abs(dist_y) > 4.288"`` instead of the vague
        ``"abs(dist_y) > ROI_THRESHOLD"``.
        """
        if not self.memory:
            return "(暂无常量表)"
        try:
            rendered = self.memory.render_constants_for_context(
                func_name, max_chars=max_chars
            )
        except Exception:
            rendered = ""
        return rendered or "(暂无常量表 — 请先运行 `python cli.py --learn-constants`)"

    # ------------------------------------------------------------------

    def _render_inventory(self, store) -> str:
        """Compact inventory: just column names per table, with row counts."""
        lines: list[str] = []
        for table, cols in (
            ("radar_objects", _COLS_RADAR_OBJECTS),
            ("radar_debug",   _COLS_RADAR_DEBUG),
            ("warning_events", _COLS_WARNING_EVENTS),
        ):
            try:
                cur = store.conn.execute(f"SELECT COUNT(*) FROM {table}")
                cnt = cur.fetchone()[0]
            except Exception:
                cnt = "?"
            lines.append(f"### {table}  ({cnt} rows)")
            lines.append("  " + ", ".join(cols))
        return "\n".join(lines)

    # ------------------------------------------------------------------

    def _fallback_plan(
        self, focus_params: list[str], func_name: str, reason: str,
    ) -> list[QueryPlan]:
        """Conservative default plan — generic statistics keyed by focus."""
        focus_set = {f.upper() for f in (focus_params or [])}
        plans: list[dict] = []

        # Always useful: target lateral distribution per side
        plans.append({
            "field": "dist_y",
            "table": "radar_objects",
            "group_by": "side",
            "filter": "in_window",
            "stats": ["count", "min", "max", "p50", "p90"],
            "reasoning": "[fallback] 左右侧目标横向分布（焦点参数未驱动出具体查询）",
        })
        if "TTC" in focus_set:
            plans.append({
                "field": "ttc",
                "table": "radar_objects",
                "filter": "in_window & (ttc > 0)",
                "stats": ["count", "min", "p10", "p50"],
                "reasoning": "[fallback] 测试窗口内 TTC 分布",
            })
        if "ROI" in focus_set or "ANGLE" in focus_set:
            plans.append({
                "field": "dist_x",
                "table": "radar_objects",
                "group_by": "side",
                "filter": "in_window",
                "stats": ["count", "min", "max", "p50", "p90"],
                "reasoning": "[fallback] 纵向距离分布（ROI 前后边界）",
            })

        result: list[QueryPlan] = []
        for spec in plans:
            spec["reasoning"] = f"{spec['reasoning']} — planner fallback: {reason}"
            qp = QueryPlan(spec)
            if qp.is_valid():
                result.append(qp)
        return result


# Keep in sync with FrameStore.TABLE_COLUMNS; duplicated here for speed
# (avoids circular imports and SQL introspection).
_COLS_RADAR_OBJECTS = [
    "timestamp_ns", "radar_id", "obj_id", "obj_class", "life_cycle",
    "dist_x", "dist_y", "vel_x", "vel_y", "vel_abs_x", "vel_abs_y",
    "ttc", "ddci",
    "bsd_flag", "lca_flag", "dow_flag", "rcw_flag",
    "rcta_flag", "rctb_flag", "fcta_flag", "fctb_flag",
]
_COLS_RADAR_DEBUG = [
    "timestamp_ns", "radar_id",
    "actual_spd", "yaw_rate", "lat_accel", "long_accel",
    "steer_angle", "actual_gear",
    "fl_whl_spd", "fr_whl_spd", "rl_whl_spd", "rr_whl_spd",
    "bsd_enable", "lca_enable", "dow_enable", "rcw_enable",
    "rcta_enable", "rctb_enable", "fcta_enable", "fctb_enable",
    "bld_warning_flag", "bld_percent", "bld_score",
]
_COLS_WARNING_EVENTS = [
    "func_name", "direction", "radar_id",
    "start_ns", "end_ns", "duration_ms",
    "trigger_source", "associated_obj_id", "max_ttc", "min_dist",
]


# ── Rendering for Expert Panel prompt ─────────────────────────────────────

def render_probe_results_for_prompt(
    plans: list[QueryPlan],
    results: list[dict],
    max_chars: int = 6000,
) -> str:
    """Format planner + executor output as a markdown section for the panel.

    Each query is shown with:
      - its ``reasoning``
      - the compact stats block (either global or grouped)
    The section fits into a ContextBudget piece, so it's length-bounded.
    """
    if not plans:
        return ""

    lines: list[str] = ["## 按问题动态探查 (Variable Probe)"]
    lines.append("> 由 VariableQueryPlanner 根据问题+L6代码知识自动生成的查询结果")
    for qp, result in zip(plans, results):
        lines.append("")
        header = f"### {qp.field}"
        if qp.group_by:
            header += f"  (group_by={qp.group_by})"
        if qp.filter:
            header += f"  [filter: {qp.filter}]"
        lines.append(header)
        if qp.reasoning:
            lines.append(f"_规划理由_: {qp.reasoning}")
        rc = result.get("row_count", 0)
        lines.append(f"- 参与行数: {rc}")
        if result.get("error"):
            lines.append(f"- **错误**: {result['error']}")
            continue
        if "groups" in result:
            for key, stats in result["groups"].items():
                stats_str = " ".join(f"{k}={v}" for k, v in stats.items())
                lines.append(f"- `{key}`: {stats_str}")
        elif "global" in result:
            stats_str = " ".join(f"{k}={v}" for k, v in result["global"].items())
            lines.append(f"- 全局: {stats_str}")

    text = "\n".join(lines)
    if len(text) > max_chars:
        text = text[: max_chars - 50] + "\n... (truncated)"
    return text
