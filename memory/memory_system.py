# -*- coding: utf-8 -*-
"""
Multi-layer memory system for the Corner Radar Analyzer.

Inspired by Claude Code's tiered memory architecture:

  L1 - Project Memory (project.md)
       Global knowledge: project conventions, system architecture overview,
       known quirks, model-specific notes. Persists across all sessions.

  L2 - Function Knowledge (functions/<FUNC>.json)
       Per-ADAS-function deep knowledge: state machines, thresholds,
       key variables, code cross-references. Auto-populated from source
       analysis, enriched by diagnosis experience.

  L3 - Pattern Memory (patterns.json)
       Learned diagnosis patterns: common root causes, symptom-to-cause
       mappings, historical fix suggestions. Grows with each diagnosis.

  L4 - Session Memory (sessions/<session_id>.json)
       Per-diagnosis session: intermediate findings, reasoning chain,
       data snapshots. Enables resume and cross-reference.

  L5 - Case Memory (cases/<case_id>/memory.json)
       Per-case persistent context: what was found, which frames matter,
       final verdict. Lives alongside the case data files.

  L6 - Code Knowledge (code_knowledge/<FUNC>.json)
       Per-function deep code knowledge accumulated by CodeLearner
       during auto-dream cycles: alarm logic, calculation chains,
       output chains, state machines. Grows incrementally.
"""
import json
import hashlib
import datetime
from pathlib import Path
from typing import Optional, Any


class MemorySystem:
    """Multi-layer persistent memory for the radar analysis system."""

    def __init__(self, project_root: Path):
        self.root = project_root
        self.memory_dir = project_root / "memory"
        self.memory_dir.mkdir(exist_ok=True)
        (self.memory_dir / "functions").mkdir(exist_ok=True)
        (self.memory_dir / "sessions").mkdir(exist_ok=True)
        (self.memory_dir / "code_knowledge").mkdir(exist_ok=True)

        # Session-level context cache.
        # Avoids rebuilding the diagnosis context multiple times per run
        # (orchestrator calls build_context_for_diagnosis ~3 times per case).
        # Cache is invalidated when this MemorySystem instance is discarded.
        self._ctx_cache: dict[tuple, str] = {}
        self._ctx_cache_hits: int = 0
        self._ctx_cache_misses: int = 0

    # ── L1: Project Memory ──────────────────────────────────────────────

    def read_project_memory(self) -> str:
        """Read the global project memory."""
        path = self.memory_dir / "project.md"
        if path.exists():
            return path.read_text(encoding="utf-8")
        return ""

    def write_project_memory(self, content: str) -> None:
        """Overwrite project memory (AI manages the content)."""
        (self.memory_dir / "project.md").write_text(content, encoding="utf-8")

    def append_project_memory(self, entry: str) -> None:
        """Append a new entry to project memory."""
        path = self.memory_dir / "project.md"
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        new_content = f"{existing}\n\n## [{timestamp}]\n{entry}" if existing else f"# Project Memory\n\n## [{timestamp}]\n{entry}"
        path.write_text(new_content, encoding="utf-8")

    # ── L2: Function Knowledge ──────────────────────────────────────────

    def read_function_knowledge(self, func_name: str) -> dict:
        """Read stored knowledge for a specific ADAS function."""
        path = self.memory_dir / "functions" / f"{func_name.upper()}.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return {}

    def write_function_knowledge(self, func_name: str, knowledge: dict) -> None:
        """Store knowledge for a function."""
        path = self.memory_dir / "functions" / f"{func_name.upper()}.json"
        knowledge["_updated"] = datetime.datetime.now().isoformat()
        path.write_text(json.dumps(knowledge, ensure_ascii=False, indent=2), encoding="utf-8")

    def get_all_function_names(self) -> list[str]:
        """List all functions that have stored knowledge."""
        return [
            p.stem for p in (self.memory_dir / "functions").glob("*.json")
        ]

    def has_function_knowledge(self, func_name: str) -> bool:
        return (self.memory_dir / "functions" / f"{func_name.upper()}.json").exists()

    # ── L3: Pattern Memory ──────────────────────────────────────────────

    def read_patterns(self) -> list[dict]:
        """Read learned diagnosis patterns."""
        path = self.memory_dir / "patterns.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return []

    def add_pattern(self, pattern: dict) -> None:
        """Add a new learned pattern from a diagnosis, deduplicating by content hash."""
        patterns = self.read_patterns()

        content_key = {
            k: v for k, v in pattern.items()
            if not k.startswith("_")
        }
        content_hash = hashlib.md5(
            json.dumps(content_key, sort_keys=True, default=str).encode()
        ).hexdigest()[:8]

        if any(p.get("_id") == content_hash for p in patterns):
            return

        pattern["_learned_at"] = datetime.datetime.now().isoformat()
        pattern["_id"] = content_hash
        patterns.append(pattern)
        (self.memory_dir / "patterns.json").write_text(
            json.dumps(patterns, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def find_similar_patterns(self, func_name: str, symptom_keywords: list[str]) -> list[dict]:
        """Find patterns that match the given function and symptoms."""
        patterns = self.read_patterns()
        matches = []
        for p in patterns:
            if p.get("function", "").upper() != func_name.upper():
                continue
            p_keywords = set(k.lower() for k in p.get("keywords", []))
            overlap = p_keywords & set(k.lower() for k in symptom_keywords)
            if overlap:
                p["_match_score"] = len(overlap) / max(len(p_keywords), 1)
                matches.append(p)
        return sorted(matches, key=lambda x: x.get("_match_score", 0), reverse=True)

    # ── L4: Session Memory ──────────────────────────────────────────────

    def create_session(self, case_id: str, problem: str, expected: str) -> str:
        """Create a new diagnosis session, return session_id."""
        session_id = f"{case_id}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
        session = {
            "session_id": session_id,
            "case_id": case_id,
            "problem": problem,
            "expected": expected,
            "created_at": datetime.datetime.now().isoformat(),
            "status": "started",
            "steps": [],
            "findings": [],
        }
        self._write_session(session_id, session)
        return session_id

    def log_step(self, session_id: str, step_name: str, detail: Any) -> None:
        """Log a diagnosis step to the session."""
        session = self._read_session(session_id)
        if session:
            session["steps"].append({
                "step": step_name,
                "timestamp": datetime.datetime.now().isoformat(),
                "detail": detail if isinstance(detail, (str, dict, list)) else str(detail),
            })
            self._write_session(session_id, session)

    def log_finding(self, session_id: str, finding: dict) -> None:
        """Log a key finding during diagnosis."""
        session = self._read_session(session_id)
        if session:
            finding["_timestamp"] = datetime.datetime.now().isoformat()
            session["findings"].append(finding)
            self._write_session(session_id, session)

    def complete_session(self, session_id: str, result_summary: str) -> None:
        """Mark session as complete."""
        session = self._read_session(session_id)
        if session:
            session["status"] = "completed"
            session["completed_at"] = datetime.datetime.now().isoformat()
            session["result_summary"] = result_summary
            self._write_session(session_id, session)

    def _read_session(self, session_id: str) -> Optional[dict]:
        path = self.memory_dir / "sessions" / f"{session_id}.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return None

    def _write_session(self, session_id: str, data: dict) -> None:
        path = self.memory_dir / "sessions" / f"{session_id}.json"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    # ── L5: Case Memory ─────────────────────────────────────────────────

    def read_case_memory(self, case_dir: Path) -> dict:
        """Read per-case persistent memory."""
        path = case_dir / "memory.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return {}

    def write_case_memory(self, case_dir: Path, memory: dict) -> None:
        """Write per-case persistent memory."""
        memory["_updated"] = datetime.datetime.now().isoformat()
        (case_dir / "memory.json").write_text(
            json.dumps(memory, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # ── L6: Code Knowledge (auto-dream 学到的代码知识) ─────────────────

    def read_code_knowledge(self, func_name: str) -> dict:
        """读取某功能的深度代码知识（由 CodeLearner 填充）。"""
        path = self.memory_dir / "code_knowledge" / f"{func_name.upper()}.json"
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
        return {}

    def list_code_knowledge_funcs(self) -> list[str]:
        """列出已有代码知识的功能名。"""
        d = self.memory_dir / "code_knowledge"
        if not d.exists():
            return []
        return [p.stem for p in d.glob("*.json") if p.stem.upper() == p.stem]

    def read_code_learning_state(self) -> dict:
        """读取代码学习状态（游标、warmup 进度等）。"""
        path = self.memory_dir / "code_knowledge" / "learning_state.json"
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
        return {}

    def read_constants(self) -> dict:
        """读取全局数值常量表（``memory/code_knowledge/constants.json``）。

        由 ``CodeLearner._learn_constants_if_needed()`` 写入。所有功能共享。
        若文件不存在或损坏返回空 dict。
        """
        path = self.memory_dir / "code_knowledge" / "constants.json"
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def render_constants_for_context(
        self,
        func_name: Optional[str] = None,
        max_chars: int = 2000,
    ) -> str:
        """把数值常量表渲染成紧凑 markdown 段，供 Planner / Expert Panel 使用。

        若 ``func_name`` 提供，则优先展示与该功能相关的条目（按 ``used_by``
        字段过滤）；其他功能仍会被展示，但放在 "其他相关" 折叠区。

        返回空串表示暂无常量知识。
        """
        data = self.read_constants()
        if not data:
            return ""

        vc = data.get("vehicle_config") or {}
        ft = data.get("function_thresholds") or {}
        roi = data.get("roi_derived") or {}
        if not (vc or ft or roi):
            return ""

        fn_upper = (func_name or "").upper()

        def _is_for(item: dict) -> bool:
            if not fn_upper:
                return True
            used = {u.upper() for u in (item.get("used_by") or [])}
            return (not used) or (fn_upper in used)

        lines: list[str] = ["## 已学数值常量（全局，可用于数值对比）"]
        if vc:
            lines.append("**vehicle_config**（基础物理常量）:")
            for name, it in list(vc.items())[:20]:
                if not isinstance(it, dict):
                    continue
                v = it.get("value", "?")
                u = it.get("unit", "")
                desc = it.get("description", "")
                lines.append(f"  - `{name}` = **{v}{(' ' + u) if u else ''}**  _{desc}_")

        if roi:
            lines.append("")
            lines.append("**roi_derived**（边界数值 = 公式 + 已算出的数字）:")
            related = [(n, it) for n, it in roi.items() if isinstance(it, dict) and _is_for(it)]
            others = [(n, it) for n, it in roi.items() if isinstance(it, dict) and not _is_for(it)]
            for name, it in related[:20]:
                cv = it.get("computed_value", "?")
                u = it.get("unit", "")
                formula = it.get("formula", "")
                used = "/".join(it.get("used_by") or [])
                desc = it.get("description", "")
                lines.append(
                    f"  - `{name}` = **{cv}{(' ' + u) if u else ''}**  "
                    f"[公式: {formula}]  [{used}]  _{desc}_"
                )
            if others and fn_upper:
                lines.append(f"  _其他 ROI 边界 ({len(others)} 条) 与 {fn_upper} 不直接相关，已省略_")

        if ft:
            lines.append("")
            lines.append("**function_thresholds**（按功能命名的阈值）:")
            related = [(n, it) for n, it in ft.items() if isinstance(it, dict) and _is_for(it)]
            others_count = len(ft) - len(related)
            for name, it in related[:25]:
                v = it.get("value", "?")
                u = it.get("unit", "")
                role = it.get("role", "")
                used = "/".join(it.get("used_by") or [])
                lines.append(
                    f"  - `{name}` = **{v}{(' ' + u) if u else ''}**  [{used}]  _{role}_"
                )
            if others_count and fn_upper:
                lines.append(f"  _其他 ({others_count}) 与 {fn_upper} 无关_")

        text = "\n".join(lines)
        if len(text) > max_chars:
            text = text[: max_chars - 40] + "\n... [constants truncated] ..."
        return text

    def render_code_knowledge_for_context(
        self, func_name: str, max_chars: int = 6000,
    ) -> str:
        """把某功能的代码知识渲染成精炼 markdown，供诊断 context 使用。

        只渲染已学过的 focus，条目按 id 去重，限制总字符数。
        """
        data = self.read_code_knowledge(func_name)
        if not data:
            return ""

        meta = data.get("_meta", {}) or {}
        learned = meta.get("learned_focuses", [])
        if not learned:
            return ""

        lines: list[str] = [
            f"## {func_name.upper()} 代码知识（auto-dream 固化）",
            f"_已学焦点: {', '.join(learned)} | 最后更新: {meta.get('last_updated', '?')[:19]}_",
            "",
        ]

        def _render_section(focus: str, section: dict) -> list[str]:
            out: list[str] = [f"### {focus}"]
            for key, val in section.items():
                if key.startswith("_"):
                    continue
                if isinstance(val, list):
                    out.append(f"**{key}** ({len(val)} 条):")
                    for it in val[:8]:
                        if not isinstance(it, dict):
                            continue
                        desc = it.get("description") or it.get("name") or it.get("c_expression") or it.get("condition") or ""
                        ref = it.get("code_ref") or {}
                        ref_str = ""
                        if isinstance(ref, dict) and ref.get("file"):
                            ref_str = f" [{ref.get('file')}:{ref.get('line', '?')}]"
                        out.append(f"  - {desc}{ref_str}")
                elif isinstance(val, dict):
                    out.append(f"**{key}**:")
                    for k, v in list(val.items())[:10]:
                        if k.startswith("_"):
                            continue
                        if isinstance(v, dict):
                            desc = v.get("description") or v.get("formula") or ""
                            out.append(f"  - `{k}`: {desc}")
                        else:
                            out.append(f"  - `{k}`: {v}")
            return out

        for focus in ["state_machine", "alarm_logic", "calculation_chain", "output_chain"]:
            if focus not in data:
                continue
            section = data.get(focus)
            if not isinstance(section, dict) or not section:
                continue
            lines.extend(_render_section(focus, section))
            lines.append("")

        text = "\n".join(lines)
        if len(text) > max_chars:
            text = text[: max_chars - 30] + "\n... [code knowledge truncated] ..."
        return text

    # ── Context Builder ─────────────────────────────────────────────────

    def build_context_for_diagnosis(
        self, func_name: str, problem: str, case_dir: Optional[Path] = None,
    ) -> str:
        """
        Build a comprehensive memory context string for the AI orchestrator.
        Combines relevant memories from all layers (L1-L6).

        **Session-level cache**: repeated calls with identical
        (func, problem, case) return the cached string without touching disk.
        Orchestrator typically calls this 3 times per diagnosis (understand,
        classify, expert_panel) — this deduplicates file IO to just once.
        """
        # problem 可能很长，截前 240 字作为缓存键（足够区分不同问题）
        cache_key = (
            (func_name or "UNKNOWN").upper(),
            (problem or "")[:240],
            str(case_dir) if case_dir else "",
        )
        cached = self._ctx_cache.get(cache_key)
        if cached is not None:
            self._ctx_cache_hits += 1
            return cached

        self._ctx_cache_misses += 1
        parts: list[str] = []

        # L1
        project_mem = self.read_project_memory()
        if project_mem:
            parts.append(f"## 项目记忆\n{project_mem[:2000]}")

        # L2
        func_knowledge = self.read_function_knowledge(func_name)
        if func_knowledge:
            k = func_knowledge.copy()
            k.pop("_updated", None)
            parts.append(f"## {func_name} 功能知识\n```json\n{json.dumps(k, ensure_ascii=False, indent=1)[:3000]}\n```")

        # L6 — 代码知识（auto-dream 固化）
        code_ctx = self.render_code_knowledge_for_context(func_name, max_chars=6000)
        if code_ctx:
            parts.append(code_ctx)

        # L3
        keywords = [w for w in problem.replace("，", " ").replace(",", " ").split() if len(w) > 1]
        similar = self.find_similar_patterns(func_name, keywords)
        if similar:
            parts.append(f"## 相似历史案例 ({len(similar)} 条)")
            for p in similar[:3]:
                parts.append(f"- 症状: {p.get('symptom', '?')} -> 根因: {p.get('root_cause', '?')}")

        # L5
        if case_dir:
            case_mem = self.read_case_memory(case_dir)
            if case_mem:
                parts.append(f"## 本案例历史记忆\n{json.dumps(case_mem, ensure_ascii=False, indent=1)[:1500]}")

        result = "\n\n".join(parts) if parts else "(暂无历史记忆)"
        self._ctx_cache[cache_key] = result
        return result

    def invalidate_context_cache(self) -> None:
        """Clear cached diagnosis contexts.

        Call this after writing new memories (L2/L3/L5) within the same
        MemorySystem lifetime if you need the next call to see the updated
        data on disk.
        """
        self._ctx_cache.clear()

    def context_cache_stats(self) -> dict:
        """Return hit/miss counters for diagnostics."""
        return {
            "hits": self._ctx_cache_hits,
            "misses": self._ctx_cache_misses,
            "size": len(self._ctx_cache),
        }
