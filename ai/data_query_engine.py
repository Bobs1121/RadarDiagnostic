# -*- coding: utf-8 -*-
"""
Data Query Engine: answer natural language questions about CAN/BAG data.

Lightweight alternative to the full diagnosis pipeline. Supports queries like:
  "FCTB触发时AEBIB是否激活"
  "car_spd在什么范围"
  "FCTA_SystemState的变化序列"

Flow:
  1. Parse data (BLF+DBC / BAG) into FrameStore
  2. Build signal inventory + reverse lookup table
  3. AI Step 1: question → identify relevant signals (validated)
  4. Extract signal timelines from store
  5. AI Step 2: data + question → structured answer
"""
from __future__ import annotations

import json
from collections import Counter
from difflib import get_close_matches
from pathlib import Path

from .model_router import ModelRouter
from .utils import parse_json_from_llm, ALL_FUNCTIONS

_QUERY_SYSTEM = """你是角雷达数据分析助手。你帮助用户查询和确认CAN/BAG数据中的信号状态。

你的能力:
- 查询CAN信号的时间线和变化
- 检查信号之间的关联关系（A触发时B的状态）
- 统计信号值的分布和变化
- 查询BAG中的egoCarInfo字段（car_spd, system_state等）

回答要求:
- 直接回答问题，给出具体数值和时间
- 如果数据中找不到信号，明确说明
- 用表格展示关键数值对比
- 简洁准确，不要啰嗦"""

_PLAN_PROMPT = """用户想查询以下数据问题:
"{question}"

## 可用信号完整列表

下面是数据中所有CAN消息及其信号名。**你必须从这个列表中选择信号，不要自己编造信号名。**

{signal_table}

{bag_inventory}

---

请从上面的列表中选择需要查询的信号。输出JSON:
{{
  "can_signals": [
    {{"signal_name": "信号名(必须与上面列表完全一致)", "role": "primary/check"}}
  ],
  "bag_fields": [
    {{"topic": "话题路径", "fields": ["字段名"], "role": "primary/check"}}
  ],
  "radar_objects": [
    {{"func_name": "BSD/LCA/DOW/RCW/RCTA/RCTB/FCTA/FCTB", "role": "查看该ADAS功能告警目标的dist/TTC/DDCI"}}
  ],
  "include_warning_events": true,
  "query_type": "correlation/timeline/statistics/threshold/object_analysis",
  "summary": "一句话描述查询意图"
}}

**关键规则**:
1. signal_name 必须是上面列表中**完全一致**的名称（含后缀如_0x137）
2. 不需要填 message_name，系统会自动查找
3. 如果用户说"FCTB触发"，对应信号可能叫 FCTBTrig 或 FCTB_Trigger 等——从列表中找
4. 如果用户说"AEBIB"，对应信号可能叫 AEBIBActv 或 EB_AEBIBActv 等——从列表中找
5. 如果用户说"车速"，对应信号可能叫 VehSpd 或 VehSpd_0x137 等——从列表中找
6. primary=触发条件/主信号, check=需要检查/确认的信号
7. 只选必要的信号
8. 如果问题涉及目标物/告警/TTC/DDCI，使用 radar_objects 查询对应 ADAS 功能的告警目标
9. 如果需要告警事件时间线，设置 include_warning_events=true

只输出JSON。"""

_ANSWER_PROMPT = """用户问题: "{question}"

查询意图: {summary}

以下是从数据中提取的实际信号数据:

{data_text}

---

请根据以上数据回答用户的问题。要求:
1. 直接回答问题（是/否/具体数值）
2. 给出关键时间段的数据佐证
3. 如果是关联查询(A触发时B的状态)，列出每个触发时段B的值
4. 用简洁的表格或列表展示关键数据
5. 如果数据不足以回答，说明缺少什么
6. 总结不超过500字"""


class DataQueryEngine:
    """Answer natural-language questions about CAN/BAG data."""

    def __init__(self, router: ModelRouter, config: dict, project_root: Path):
        self.router = router
        self.config = config
        self.project_root = project_root
        self._sync = None

    def run_query(
        self,
        case_dir: Path,
        question: str,
        on_status=None,
    ) -> str:
        def status(step, detail=""):
            if on_status:
                on_status(step, detail)

        # 1. Parse data
        status("parse", "Loading data...")
        store, dbc = self._parse_data(case_dir, status)

        # 2. Build inventory + lookup
        status("inventory", "Scanning available signals...")
        signal_lookup, signal_table = self._build_signal_lookup(store)
        bag_inventory = self._build_bag_inventory(store)
        knowledge_ctx = self._build_knowledge_context(question)
        status("inventory", f"Found {len(signal_lookup)} CAN signals")

        # 3. AI: plan query
        status("plan", "AI understanding your question...")
        plan = self._plan_query(question, signal_table, bag_inventory, knowledge_ctx)
        plan_summary = plan.get("summary", question)
        query_type = plan.get("query_type", "unknown")

        # 4. Validate & correct the plan
        plan = self._validate_plan(plan, signal_lookup)
        n_signals = len(plan.get("can_signals", []))
        status("plan", f"Query: {query_type} — {plan_summary} ({n_signals} signals)")

        # 5. Extract data
        status("extract", "Extracting signal data...")
        data_text = self._extract_data(store, plan, signal_lookup)
        status("extract", f"Extracted {len(data_text)} chars of data")

        # 6. AI: answer
        status("answer", "AI analyzing data and answering...")
        answer = self._answer_question(question, plan_summary, data_text, knowledge_ctx)

        store.close()
        return answer

    # ── Data Parsing ─────────────────────────────────────────────────────

    def _parse_data(self, case_dir: Path, status):
        from parsers.case_loader import load_case_data
        r = load_case_data(case_dir, self.config, self.project_root, on_status=status)
        self._sync = r.sync
        return r.store, r.dbc

    # ── Signal Lookup Table ──────────────────────────────────────────────

    @staticmethod
    def _build_signal_lookup(store) -> tuple[dict, str]:
        """
        Build two things:
        1. signal_lookup: {signal_name: {can_id, can_id_hex, message_name}} for auto-resolution
        2. signal_table: formatted text for AI consumption — one signal per line
        """
        inventory = store.get_signal_inventory()
        if not inventory:
            return {}, "(无CAN数据)"

        lookup: dict[str, dict] = {}
        table_lines: list[str] = []

        for item in inventory:
            msg = item["message_name"]
            can_hex = item["can_id_hex"]
            can_id = item["can_id"]
            count = item["frame_count"]

            table_lines.append(f"\n### {can_hex} {msg} ({count}帧)")

            for sig in item["signals"]:
                lookup[sig] = {
                    "can_id": can_id,
                    "can_id_hex": can_hex,
                    "message_name": msg,
                }
                table_lines.append(f"  - {sig}")

        return lookup, "\n".join(table_lines)

    @staticmethod
    def _build_bag_inventory(store) -> str:
        topics = store.get_bag_topics()
        if not topics:
            return ""
        lines = ["\n## BAG话题"]
        for t in topics:
            lines.append(f"  {t['topic']} ({t['count']}帧, {t.get('msg_type', '?')})")
        return "\n".join(lines)

    # ── Knowledge Context ─────────────────────────────────────────────────

    def _build_knowledge_context(self, question: str) -> str:
        """Load signal mapping, radar knowledge, and function docs relevant to the question."""
        parts: list[str] = []
        docs_dir = self.project_root / "source_docs"

        sig_map_path = docs_dir / "signal_mapping.json"
        if sig_map_path.exists():
            try:
                sig_map = json.loads(sig_map_path.read_text(encoding="utf-8"))
                i2c = sig_map.get("internal_to_can", {})
                if i2c:
                    lines = ["## 内部变量 → CAN信号 映射表 (来自RteComMapping.c)"]
                    for var, sigs in sorted(i2c.items()):
                        lines.append(f"  {var} → {', '.join(sigs)}")
                    parts.append("\n".join(lines))
            except Exception:
                pass

        radar_kb_path = docs_dir / "radar_knowledge.json"
        if radar_kb_path.exists():
            try:
                rkb = json.loads(radar_kb_path.read_text(encoding="utf-8"))
                kb_lines = ["## 雷达数据知识库"]
                # Warning byte map
                wmap = rkb.get("warning_status_raw_byte_map", {}).get("bytes", {})
                if wmap:
                    kb_lines.append("### warning_status_raw 字节含义")
                    for idx, name in sorted(wmap.items(), key=lambda x: int(x[0])):
                        kb_lines.append(f"  byte[{idx}] = {name}")
                # A2L mapping
                a2l = rkb.get("a2l_to_egoCarInfo", {}).get("mappings", {})
                if a2l:
                    kb_lines.append("### A2L变量 → egoCarInfo字段映射")
                    for src, dst in sorted(a2l.items()):
                        kb_lines.append(f"  {src} → {dst}")
                # CAN ID → radar
                cid_map = rkb.get("can_id_to_radar", {})
                if cid_map:
                    kb_lines.append("### CAN ID → 雷达位置")
                    for cid, info in sorted(cid_map.items()):
                        kb_lines.append(f"  {cid} = {info['name']} ({info['position']})")
                parts.append("\n".join(kb_lines))
            except Exception:
                pass

        func_names = ALL_FUNCTIONS
        q_upper = question.upper()
        matched_funcs = [f for f in func_names if f in q_upper]

        for fn in matched_funcs:
            cond_path = docs_dir / f"{fn}_conditions.json"
            if cond_path.exists():
                try:
                    cond = json.loads(cond_path.read_text(encoding="utf-8"))
                    summary = f"## {fn} 激活条件摘要\n"
                    for cat in ["activation", "external_suppression"]:
                        items = cond.get(cat, [])
                        if items:
                            summary += f"\n### {cat}\n"
                            for it in items[:10]:
                                desc = it.get("condition") or it.get("description", "?")
                                var = it.get("variable", "")
                                summary += f"  - {desc} (var: {var})\n"
                    parts.append(summary)
                except Exception:
                    pass

            doc_path = docs_dir / f"{fn}.md"
            if doc_path.exists():
                try:
                    content = doc_path.read_text(encoding="utf-8")
                    parts.append(f"## {fn} 功能文档摘要\n{content[:1500]}")
                except Exception:
                    pass

        return "\n\n".join(parts) if parts else ""

    # ── AI: Query Planning ───────────────────────────────────────────────

    def _plan_query(self, question: str, signal_table: str, bag_inventory: str,
                    knowledge_ctx: str = "") -> dict:
        prompt = _PLAN_PROMPT.format(
            question=question,
            signal_table=signal_table,
            bag_inventory=bag_inventory,
        )
        if knowledge_ctx:
            prompt += f"\n\n## 补充知识（内部变量映射与功能条件）\n{knowledge_ctx[:8000]}"
        result = self.router.complex(prompt, system=_QUERY_SYSTEM)
        return parse_json_from_llm(result.get("content", ""), fallback={
            "can_signals": [],
            "bag_fields": [],
            "query_type": "unknown",
            "summary": question,
        })

    # ── Plan Validation & Correction ─────────────────────────────────────

    @staticmethod
    def _validate_plan(plan: dict, signal_lookup: dict) -> dict:
        """
        Validate AI's plan against actual signal inventory.
        Auto-correct signal names using fuzzy matching if needed.
        """
        all_signal_names = list(signal_lookup.keys())
        corrected_signals = []

        for sig_req in plan.get("can_signals", []):
            sig_name = sig_req.get("signal_name", "")
            role = sig_req.get("role", "check")

            if sig_name in signal_lookup:
                info = signal_lookup[sig_name]
                corrected_signals.append({
                    "signal_name": sig_name,
                    "message_name": info["message_name"],
                    "can_id": info["can_id"],
                    "role": role,
                    "corrected": False,
                })
                continue

            # Fuzzy match: try close matches
            matches = get_close_matches(sig_name, all_signal_names, n=3, cutoff=0.5)

            # Also try substring match (user might say "FCTB" and mean "FCTBTrig")
            if not matches:
                sig_lower = sig_name.lower().replace("_", "")
                for real_name in all_signal_names:
                    real_lower = real_name.lower().replace("_", "")
                    if sig_lower in real_lower or real_lower in sig_lower:
                        matches.append(real_name)
                matches = matches[:3]

            if matches:
                best = matches[0]
                info = signal_lookup[best]
                corrected_signals.append({
                    "signal_name": best,
                    "message_name": info["message_name"],
                    "can_id": info["can_id"],
                    "role": role,
                    "corrected": True,
                    "original": sig_name,
                })
            else:
                corrected_signals.append({
                    "signal_name": sig_name,
                    "message_name": "",
                    "can_id": None,
                    "role": role,
                    "corrected": False,
                    "not_found": True,
                })

        plan["can_signals"] = corrected_signals
        return plan

    # ── Data Extraction ──────────────────────────────────────────────────

    def _extract_data(self, store, plan: dict, signal_lookup: dict) -> str:
        parts: list[str] = []

        # CAN signals
        for sig_req in plan.get("can_signals", []):
            sig_name = sig_req.get("signal_name", "")
            msg_name = sig_req.get("message_name", "")
            role = sig_req.get("role", "")
            corrected = sig_req.get("corrected", False)
            not_found = sig_req.get("not_found", False)

            prefix = f"CAN {msg_name}.{sig_name}"
            if corrected:
                prefix += f" (AI原始请求: {sig_req.get('original', '?')}, 已自动纠正)"

            if not_found:
                parts.append(f"### {prefix} [{role}]: ⚠ 信号在DBC中不存在(DBC未定义或信号名拼写错误)")
                continue

            frames = store.query_can_by_name(msg_name) if msg_name else []
            if not frames and sig_req.get("can_id") is not None:
                frames = store.query_can_by_id(sig_req["can_id"])

            if not frames:
                has_any_can = bool(store.get_can_ids())
                if has_any_can:
                    parts.append(f"### {prefix} [{role}]: ⚠ 消息'{msg_name}'在BLF中无数据帧(DBC解码可能失败或该消息未在总线上发送)")
                else:
                    parts.append(f"### {prefix} [{role}]: ⚠ 无CAN数据(未加载BLF文件)")
                continue

            timeline = []
            for f in frames:
                signals = f.get("signals", {})
                val = signals.get(sig_name)
                if val is not None:
                    timeline.append((f["timestamp"], val))

            if not timeline:
                available = set()
                has_empty_signals = False
                for f in frames[:5]:
                    sigs = f.get("signals", {})
                    if not sigs:
                        has_empty_signals = True
                    available.update(sigs.keys())
                if has_empty_signals and not available:
                    parts.append(
                        f"### {prefix} [{role}]: ⚠ DBC解码失败(帧存在但signals为空，检查DBC与CAN ID匹配)"
                    )
                else:
                    parts.append(
                        f"### {prefix} [{role}]: 消息中不含此信号\n"
                        f"  该消息可用信号: {', '.join(sorted(available)[:30])}"
                    )
                continue

            transform_note = self._get_transform_note(sig_name)
            header = self._format_signal_timeline(prefix, role, timeline)
            if transform_note:
                header += f"\n  📎 内部变量映射: {transform_note}"
            parts.append(header)

        # BAG fields
        for bag_req in plan.get("bag_fields", []):
            topic = bag_req.get("topic", "")
            fields = bag_req.get("fields", [])
            role = bag_req.get("role", "")

            frames = store.query_bag_by_topic(topic)
            if not frames:
                parts.append(f"### BAG {topic} [{role}]: (未找到数据)")
                continue

            for field_name in fields:
                timeline = []
                for f in frames:
                    flds = f.get("fields", {})
                    val = flds.get(field_name)
                    if val is not None:
                        timeline.append((f["timestamp_sec"], val))

                if not timeline:
                    parts.append(f"### BAG {topic}.{field_name} [{role}]: (字段不存在)")
                    continue

                parts.append(self._format_signal_timeline(
                    f"BAG {topic}.{field_name}", role, timeline,
                ))

        # Radar object queries
        for obj_req in plan.get("radar_objects", []):
            func = obj_req.get("func_name", "")
            role = obj_req.get("role", "查看告警目标")
            try:
                warned = store.query_objects_with_warning(func)
            except Exception:
                warned = []
            if not warned:
                parts.append(f"### 雷达目标 {func} [{role}]: (无告警目标)")
                continue
            lines = [f"### 雷达目标 {func} [{role}] ({len(warned)} 条记录)"]
            for o in warned[:30]:
                t_sec = round(o["timestamp_ns"] / 1e9, 3)
                lines.append(
                    f"  t={t_sec} r={o['radar_id']} obj={o['obj_id']} "
                    f"dx={o.get('dist_x','?')} dy={o.get('dist_y','?')} "
                    f"ttc={o.get('ttc','?')} ddci={o.get('ddci','?')}"
                )
            if len(warned) > 30:
                lines.append(f"  ... (共{len(warned)}条, 仅显示前30)")
            parts.append("\n".join(lines))

        # Warning events
        if plan.get("include_warning_events"):
            try:
                w_events = store.query_warning_events()
            except Exception:
                w_events = []
            if w_events:
                lines = [f"### 告警事件列表 ({len(w_events)}个)"]
                for e in w_events[:50]:
                    s = round(e["start_ns"] / 1e9, 3)
                    dur = e.get("duration_ms")
                    lines.append(
                        f"  {e['func_name']} radar={e['radar_id']} "
                        f"t={s}s dur={dur}ms obj={e.get('associated_obj_id')} "
                        f"min_d={e.get('min_dist')} max_ttc={e.get('max_ttc')}"
                    )
                parts.append("\n".join(lines))

        return "\n\n".join(parts) if parts else "(未提取到任何数据)"

    @staticmethod
    def _format_signal_timeline(
        label: str, role: str, timeline: list[tuple],
    ) -> str:
        """Format a signal timeline with statistics and change events."""
        lines = [f"### {label} [{role}] ({len(timeline)}帧)"]

        values = [v for _, v in timeline if isinstance(v, (int, float))]
        if values:
            lines.append(
                f"  范围: [{min(values)}, {max(values)}], "
                f"均值: {sum(values)/len(values):.4f}"
            )
            vc = Counter(values)
            if len(vc) <= 15:
                lines.append(f"  值分布: {dict(vc.most_common())}")

        # Change events
        changes = []
        prev_val = None
        active_start = None
        for t, v in timeline:
            if prev_val is not None and v != prev_val:
                change = {"t": round(t, 3), "from": prev_val, "to": v}
                if isinstance(v, (int, float)) and v > 0 and (isinstance(prev_val, (int, float)) and prev_val == 0):
                    active_start = t
                elif isinstance(v, (int, float)) and v == 0 and isinstance(prev_val, (int, float)) and prev_val > 0:
                    if active_start is not None:
                        change["active_duration"] = round(t - active_start, 3)
                    active_start = None
                changes.append(change)
            prev_val = v

        if changes:
            lines.append(f"  变化次数: {len(changes)}")
            lines.append("  变化事件:")
            for c in changes[:60]:
                line = f"    t={c['t']}s: {c['from']} → {c['to']}"
                if "active_duration" in c:
                    line += f" (持续{c['active_duration']}s)"
                lines.append(line)
            if len(changes) > 60:
                lines.append(f"    ... +{len(changes)-60} more")
        else:
            lines.append(f"  无变化 (恒定值: {timeline[0][1]})")

        lines.append(f"  时间: {timeline[0][0]:.3f}s ~ {timeline[-1][0]:.3f}s")

        # Sampled data
        if len(timeline) > 40:
            step = len(timeline) // 40
            sampled = timeline[::step][:40]
        else:
            sampled = timeline
        lines.append("  采样:")
        for t, v in sampled:
            lines.append(f"    t={t:.3f}  v={v}")

        return "\n".join(lines)

    def _get_transform_note(self, signal_name: str) -> str:
        """Look up signal_mapping.json for transform info on a CAN signal."""
        sig_map_path = self.project_root / "source_docs" / "signal_mapping.json"
        if not sig_map_path.exists():
            return ""
        try:
            sig_map = json.loads(sig_map_path.read_text(encoding="utf-8"))
            for m in sig_map.get("mappings", []):
                if m.get("can_signal") == signal_name:
                    var = m.get("internal_var", "?")
                    transform = m.get("transform", "?")
                    dtype = m.get("data_type", "?")
                    return f"{signal_name} → {var} (type={dtype}, transform={transform})"
        except Exception:
            pass
        return ""

    # ── AI: Answer Question ──────────────────────────────────────────────

    def _answer_question(self, question: str, summary: str, data_text: str,
                         knowledge_ctx: str = "") -> str:
        if len(data_text) > 12000:
            data_text = data_text[:12000] + "\n... (数据过长，已截断)"

        prompt = _ANSWER_PROMPT.format(
            question=question,
            summary=summary,
            data_text=data_text,
        )
        if knowledge_ctx:
            prompt += f"\n\n## 参考知识\n{knowledge_ctx[:4000]}"
        result = self.router.complex(prompt, system=_QUERY_SYSTEM)
        return result.get("content", "分析失败，请检查数据文件和问题描述。")
