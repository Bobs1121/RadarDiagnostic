# -*- coding: utf-8 -*-
"""
CodeGraph Prompt Renderer.

Converts CodeGraph query results into compact Markdown text for LLM prompt injection.

Each render method has a character budget and returns text suitable for
direct insertion into an LLM system/user prompt.

If CodeGraph is not available, all render methods return empty string
(graceful fallback — the calling code falls back to old JSON files).
"""
from __future__ import annotations

import logging
from typing import Optional

from .query import CodeGraph

log = logging.getLogger(__name__)


class CodeGraphRenderer:
    """
    Render CodeGraph data as Markdown for LLM prompts.

    Usage:
        renderer = CodeGraphRenderer(codegraph)
        md = renderer.render_for_problem("FCTB", "FCTB没有触发报警")
        md = renderer.render_for_probe("fFctbActiveUpSpd")
    """

    def __init__(self, codegraph: Optional[CodeGraph] = None):
        self.cg = codegraph

    @property
    def available(self) -> bool:
        return self.cg is not None and self.cg.is_available

    # ── Render: Problem Understanding ────────────────────────────────────

    def render_for_problem(self, module: str, problem_desc: str = "", max_chars: int = 8000) -> str:
        """
        Render CodeGraph context for problem understanding phase.

        Includes:
        - Functions belonging to the module
        - Signal dependencies
        - State machine transitions
        - Behaviour patterns

        Returns empty string if CodeGraph not available.
        """
        if not self.available:
            return ""

        parts = [f"## CodeGraph: {module} 代码结构\n"]

        # Functions
        functions = self.cg.get_functions_by_module(module)
        if functions:
            parts.append(f"### 功能函数 ({len(functions)} 个)\n")
            for fn in functions:
                file_short = fn.file_path.split("/")[-1] if fn.file_path else "?"
                parts.append(
                    f"- **`{fn.name}`** (`{file_short}` L{fn.start_line}-{fn.end_line})"
                    f" → {fn.return_type or 'void'}"
                )
                if fn.params:
                    params_short = fn.params[:60]
                    if len(fn.params) > 60:
                        params_short += "..."
                    parts.append(f"  - 参数: `{params_short}`")

        # Signals
        all_signals = set()
        sig_details = []
        for fn in functions:
            sigs = self.cg.get_signals_used_by(fn.name)
            for s in sigs:
                sig_name = s.get("signal_name", "")
                if sig_name not in all_signals:
                    all_signals.add(sig_name)
                    sig_details.append({
                        "name": sig_name,
                        "access": s.get("type", ""),
                        "rte": s.get("rte_call", ""),
                        "used_by": fn.name,
                    })

        if sig_details:
            parts.append(f"\n### 信号依赖 ({len(sig_details)} 个)\n")
            rx_sigs = [s for s in sig_details if "READ" in s["access"]]
            tx_sigs = [s for s in sig_details if "WRITE" in s["access"]]
            if rx_sigs:
                parts.append("**Rx 信号:**")
                for s in rx_sigs:
                    parts.append(f"- `{s['name']}` (via `{s['rte']}`) — 被 `{s['used_by']}` 使用")
            if tx_sigs:
                parts.append("\n**Tx 信号:**")
                for s in tx_sigs:
                    parts.append(f"- `{s['name']}` (via `{s['rte']}`) — 被 `{s['used_by']}` 产生")

        # Call relationships
        call_info = []
        for fn in functions:
            callers = self.cg.get_callers(fn.name)
            if callers:
                caller_names = [c["caller_name"] for c in callers]
                call_info.append(f"- `{fn.name}` ← {', '.join(f'`{c}`' for c in caller_names)}")

        if call_info:
            parts.append(f"\n### 调用关系\n")
            parts.extend(call_info)

        # Behaviour patterns
        patterns = []
        for fn in functions:
            fn_patterns = self.cg.get_patterns_for(fn.name)
            for p in fn_patterns:
                if p.get("pattern"):
                    patterns.append(
                        f"- `{p['pattern']}` in `{fn.name}` (L{p.get('line', '?')})"
                    )

        if patterns:
            parts.append(f"\n### 行为模式\n")
            parts.extend(patterns)

        result = "\n".join(parts)

        # Truncate if needed
        if len(result) > max_chars:
            result = result[:max_chars] + "\n... (truncated)"

        return result

    # ── Render: Data Probe ──────────────────────────────────────────────

    def render_for_probe(self, entity: str, max_chars: int = 6000) -> str:
        """
        Render detailed CodeGraph info for a specific entity (function/variable/signal).

        Used in probe phase to give LLM precise code context.

        Returns empty string if CodeGraph not available.
        """
        if not self.available:
            return ""

        related = self.cg.find_related(entity)

        if related.get("entity_type") is None:
            return ""

        parts = [f"## CodeGraph: {related['entity_name']} ({related['entity_type']})\n"]

        if related.get("entity_type") == "FUNCTION":
            fn = self.cg.get_function_by_name(entity)
            if fn:
                file_short = fn.file_path.split("/")[-1] if fn.file_path else "?"
                parts.append(
                    f"- 位置: `{file_short}` L{fn.start_line}-{fn.end_line}"
                )
                parts.append(f"- 签名: `{fn.return_type or 'void'} {fn.name}({fn.params or ''})`")

            if related.get("module"):
                parts.append(f"- 所属功能: `{related['module']}`")

            if related.get("callers"):
                parts.append(f"\n### 被谁调用\n")
                for c in related["callers"]:
                    parts.append(f"- `{c}`")

            if related.get("callees"):
                parts.append(f"\n### 调用了谁\n")
                for c in related["callees"]:
                    parts.append(f"- `{c}`")

            if related.get("reads_vars"):
                parts.append(f"\n### 读取变量 ({len(related['reads_vars'])} 个)\n")
                parts.extend(f"- `{v}`" for v in related["reads_vars"])

            if related.get("writes_vars"):
                parts.append(f"\n### 写入变量 ({len(related['writes_vars'])} 个)\n")
                parts.extend(f"- `{v}`" for v in related["writes_vars"])

            if related.get("reads_signals"):
                parts.append(f"\n### Rx 信号\n")
                parts.extend(f"- `{s}`" for s in related["reads_signals"])

            if related.get("writes_signals"):
                parts.append(f"\n### Tx 信号\n")
                parts.extend(f"- `{s}`" for s in related["writes_signals"])

            if related.get("patterns"):
                parts.append(f"\n### 行为模式\n")
                for p in related["patterns"]:
                    parts.append(f"- `{p.get('pattern', '?')}` (L{p.get('line', '?')})")

        elif related.get("entity_type") == "SIGNAL":
            if related.get("read_by"):
                parts.append(f"### 被以下函数读取\n")
                parts.extend(f"- `{f}`" for f in related["read_by"])
            if related.get("written_by"):
                parts.append(f"\n### 被以下函数写入\n")
                parts.extend(f"- `{f}`" for f in related["written_by"])

        elif related.get("entity_type") == "VARIABLE":
            if related.get("read_by"):
                parts.append(f"### 被以下函数读取\n")
                parts.extend(f"- `{f}`" for f in related["read_by"])
            if related.get("written_by"):
                parts.append(f"\n### 被以下函数写入\n")
                parts.extend(f"- `{f}`" for f in related["written_by"])

        result = "\n".join(parts)

        if len(result) > max_chars:
            result = result[:max_chars] + "\n... (truncated)"

        return result

    # ── Render: Condition Extraction ────────────────────────────────────

    def render_for_conditions(self, module: str, max_chars: int = 5000) -> str:
        """
        Render CodeGraph context for condition extraction phase.

        Focuses on signal dependencies and state transitions relevant to
        trigger/alarm conditions.
        """
        if not self.available:
            return ""

        parts = [f"## CodeGraph: {module} 条件相关代码\n"]

        functions = self.cg.get_functions_by_module(module)

        # Signals with their conditions
        sig_conditions = {}
        for fn in functions:
            sigs = self.cg.get_signals_used_by(fn.name)
            for s in sigs:
                sig = s.get("signal_name", "")
                if sig not in sig_conditions:
                    sig_conditions[sig] = {
                        "signal": sig,
                        "rte": s.get("rte_call", ""),
                        "used_by": [],
                    }
                sig_conditions[sig]["used_by"].append(fn.name)

        if sig_conditions:
            parts.append(f"### 信号 → 函数映射 ({len(sig_conditions)} 个信号)\n")
            for sig_info in sig_conditions.values():
                users = ", ".join(f"`{u}`" for u in sig_info["used_by"])
                parts.append(f"- `{sig_info['signal']}` → {users}")
                if sig_info["rte"]:
                    parts.append(f"  - RTE: `{sig_info['rte']}`")

        # State transitions
        transitions = []
        for fn in functions:
            fn_transitions = self.cg.get_state_transitions(fn.name)
            for t in fn_transitions:
                transitions.append(
                    f"- `{fn.name}` → `{t.get('state_name', '?')}` (L{t.get('line', '?')})"
                )

        if transitions:
            parts.append(f"\n### 状态转换 ({len(transitions)} 条)\n")
            parts.extend(transitions)

        # Patterns relevant to conditions
        patterns = []
        for fn in functions:
            fn_patterns = self.cg.get_patterns_for(fn.name)
            for p in fn_patterns:
                if p.get("pattern") in ("HoldRelease", "EdgeTrigger", "Hysteresis", "Debounce"):
                    patterns.append(
                        f"- `{p['pattern']}` in `{fn.name}` (L{p.get('line', '?')})"
                    )

        if patterns:
            parts.append(f"\n### 条件相关行为模式\n")
            parts.extend(patterns)

        result = "\n".join(parts)

        if len(result) > max_chars:
            result = result[:max_chars] + "\n... (truncated)"

        return result

    # ── Render: Expert Panel ────────────────────────────────────────────

    def render_for_expert_panel(
        self,
        module: str,
        problem_desc: str = "",
        evidence: Optional[dict] = None,
        max_chars: int = 12000,
    ) -> str:
        """
        Render comprehensive CodeGraph context for expert panel diagnosis.

        Includes everything from problem render plus calibration params,
        cross-module analysis, and semantic knowledge.
        """
        if not self.available:
            return ""

        parts = []

        # Module structure
        problem_md = self.render_for_problem(module, problem_desc, max_chars=max_chars)
        if problem_md:
            parts.append(problem_md)

        # Calibration params
        calib_params = self.cg.get_calibration_params()
        if calib_params:
            parts.append(f"\n### 校准参数 ({len(calib_params)} 个)\n")
            for cp in calib_params:
                val_str = f" = {cp.value}" if cp.value is not None else ""
                unit_str = f" ({cp.unit})" if cp.unit else ""
                parts.append(f"- `{cp.name}`{val_str}{unit_str}")

        # Cross-module: shared functions/signals with other modules
        if self.cg.conn:
            mod_rows = self.cg.conn.execute(
                "SELECT name FROM nodes WHERE type='MODULE'"
            ).fetchall()
            module_names = [r["name"] for r in mod_rows]
        else:
            module_names = []

        for other_mod in module_names:
            if other_mod == module:
                continue
            shared = self.cg.get_shared_functions(module, other_mod)
            if shared:
                parts.append(f"\n### 与 {other_mod} 共享的函数 ({len(shared)} 个)\n")
                parts.extend(f"- `{fn.name}`" for fn in shared)

                shared_sigs = self.cg.get_shared_signals(module, other_mod)
                if shared_sigs:
                    parts.append(f"\n### 与 {other_mod} 共享的信号 ({len(shared_sigs)} 个)\n")
                    parts.extend(f"- `{sig.name}`" for sig in shared_sigs)

        # Build info
        if self.cg.conn:
            build = self.cg.conn.execute(
                "SELECT build_time, build_type, duration_sec FROM build_log ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if build:
                parts.append(f"\n*CodeGraph 构建: {build['build_time']} ({build['build_type']}, {build['duration_sec']:.1f}s)*")

        result = "\n".join(parts)

        if len(result) > max_chars:
            result = result[:max_chars] + "\n... (truncated)"

        return result

    def render_semantics_for_panel(
        self, module: str, max_chars: int = 5000
    ) -> str:
        """Render semantic annotations for the given module for expert panel."""
        if not self.cg.conn:
            return ""

        import json as _json

        focus_order = ["alarm_logic", "calculation_chain", "state_machine", "output_chain"]
        focus_labels = {
            "alarm_logic": "告警逻辑",
            "calculation_chain": "计算链路",
            "state_machine": "状态机",
            "output_chain": "输出链路",
        }

        parts = []
        patterns = [f"%{module}%", f"%{module.capitalize()}%", f"%{module.title()}%"]

        for focus in focus_order:
            wheres = " OR ".join([f"n.name LIKE ?" for _ in patterns])
            query = f"""
                SELECT ns.node_id, ns.semantic_json
                FROM node_semantics ns
                JOIN nodes n ON n.id = ns.node_id
                WHERE ns.focus = ? AND n.type = 'FUNCTION' AND ({wheres})
                LIMIT 20
            """
            params = [focus] + patterns
            rows = self.cg.conn.execute(query, params).fetchall()
            if not rows:
                continue

            label = focus_labels.get(focus, focus)
            parts.append(f"\n### {label} ({len(rows)} 个函数)\n")
            for row in rows:
                try:
                    sem = _json.loads(row["semantic_json"]) if isinstance(row["semantic_json"], str) else row["semantic_json"]
                    parts.append(self._render_semantic_block(focus, sem))
                except Exception:
                    pass

        result = "\n".join(parts)
        if len(result) > max_chars:
            result = result[:max_chars] + "\n... (truncated)"
        return result

    def _render_semantic_block(self, focus: str, sem: dict) -> str:
        """Render a single semantic annotation block."""
        lines = []
        if focus == "alarm_logic":
            triggers = sem.get("trigger_conditions", [])[:3]
            cancels = sem.get("cancel_conditions", [])[:3]
            if triggers:
                lines.append(f"  - 触发条件: {', '.join(str(t) for t in triggers)}")
            if cancels:
                lines.append(f"  - 取消条件: {', '.join(str(c) for c in cancels)}")
        elif focus == "calculation_chain":
            vars_ = sem.get("key_variables", [])[:5]
            chain = sem.get("derivation_chain", [])[:3]
            if vars_:
                lines.append(f"  - 关键变量: {', '.join(str(v) for v in vars_)}")
            if chain:
                lines.append(f"  - 推导链: {' -> '.join(str(c) for c in chain)}")
        elif focus == "state_machine":
            states = sem.get("states", [])[:5]
            transitions = sem.get("transitions", [])[:3]
            if states:
                lines.append(f"  - 状态: {', '.join(str(s) for s in states)}")
            for t in transitions:
                if isinstance(t, dict):
                    fr = t.get("from", "?")
                    to = t.get("to", "?")
                    cond = t.get("condition", "")
                    lines.append(f"    {fr} -> {to} [{cond}]")
                else:
                    lines.append(f"    {t}")
        elif focus == "output_chain":
            outputs = sem.get("outputs", [])[:5]
            gating = sem.get("external_gating", [])[:3]
            if outputs:
                lines.append(f"  - 输出信号: {', '.join(str(o) for o in outputs)}")
            if gating:
                lines.append(f"  - 外部门控: {', '.join(str(g) for g in gating)}")
        lines.append("")
        return "\n".join(lines)

    # ── Render: Stats (for --codegraph-stats) ────────────────────────────

    def render_stats(self) -> str:
        """Render CodeGraph statistics as human-readable text."""
        if not self.available:
            return "CodeGraph: 不可用 (DB 不存在)"

        stats = self.cg.get_stats()

        lines = ["## CodeGraph 统计\n"]

        lines.append(f"- DB 路径: `{stats['db_path']}`")
        lines.append(f"- 总节点: {stats['total_nodes']}")
        lines.append(f"- 总边: {stats['total_edges']}")

        if stats.get("node_counts"):
            lines.append("\n### 节点分布\n")
            for ntype, count in sorted(stats["node_counts"].items()):
                lines.append(f"- {ntype}: {count}")

        if stats.get("edge_counts"):
            lines.append("\n### 边分布\n")
            for etype, count in sorted(stats["edge_counts"].items()):
                lines.append(f"- {etype}: {count}")

        if stats.get("last_build"):
            lines.append(f"\n- 最后构建: {stats['last_build']}")
            lines.append(f"- 累计构建次数: {stats['total_builds']}")

        return "\n".join(lines)
