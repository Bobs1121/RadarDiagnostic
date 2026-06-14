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
import glob
import json
import hashlib
import datetime
from pathlib import Path
from typing import Optional, Any


class MemorySystem:
    """Multi-layer persistent memory for the radar analysis system."""

    def __init__(self, project_root: Path | str, memory_dir: Path | str | None = None):
        self.root = Path(project_root)
        self.memory_dir = Path(memory_dir) if memory_dir else (self.root / "memory")
        self.memory_dir.mkdir(parents=True, exist_ok=True)
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
        """Create a new diagnosis session, return session_id.

        会话上限: 只保留最近 20 条，超出时自动清理最旧的。
        """
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
        # 清理过期 session — 只保留最近 20 条
        self._prune_old_sessions(max_count=20)
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

    def query_sessions(self, func_name: str, keywords: list[str],
                       max_results: int = 5) -> list[dict]:
        """查询历史诊断 session，按相关性排序返回。

        匹配策略：
        1. **func 匹配** — case_id 包含 func_name（不区分大小写）
        2. **关键词匹配** — problem 描述中包含 keywords
        3. **去重** — 同一 case 只保留最近的 session

        返回字段：session_id, case_id, problem, expected, status,
                  completed_at, steps_count, relevance_score
        """
        sessions_dir = self.memory_dir / "sessions"
        if not sessions_dir.exists():
            return []

        func_upper = func_name.upper()
        kw_lower = [k.lower() for k in keywords if len(k) > 1]

        candidates: list[dict] = []
        for fp in sessions_dir.glob("*.json"):
            try:
                s = json.loads(fp.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue

            case_id = s.get("case_id", "")
            # 过滤：case_id 应包含 func_name
            if func_upper not in case_id.upper():
                continue

            problem = s.get("problem", "")
            # 关键词得分
            kw_score = sum(1 for k in kw_lower if k in problem.lower())
            # 时间得分（越新越好）
            completed = s.get("completed_at", s.get("created_at", ""))
            time_score = 1.0 if completed else 0.5
            # 状态加分（completed > started）
            status = s.get("status", "started")
            status_score = 1.0 if status == "completed" else 0.3

            score = (kw_score * 2.0) + time_score + status_score
            candidates.append({
                "session_id": s.get("session_id", fp.stem),
                "case_id": case_id,
                "problem": problem,
                "expected": s.get("expected", ""),
                "status": status,
                "completed_at": completed,
                "created_at": s.get("created_at", ""),
                "steps_count": len(s.get("steps", [])),
                "findings_count": len(s.get("findings", [])),
                "result_summary": s.get("result_summary", "")[:200],
                "relevance_score": round(score, 2),
                "file_path": str(fp),
            })

        # 按分数降序
        candidates.sort(key=lambda x: x["relevance_score"], reverse=True)

        # 同一 case 只保留最新的一条
        seen_cases: dict[str, dict] = {}
        for c in candidates:
            cid = c["case_id"]
            if cid not in seen_cases:
                seen_cases[cid] = c
        deduped = list(seen_cases.values())

        return deduped[:max_results]

    def get_session_details(self, session_id: str,
                            max_steps: int = 10) -> dict:
        """获取单个 session 的详细步骤摘要，用于注入专家面板。

        只提取关键步骤（understand, classify, conditions, expert_panel），
        避免把全部 steps dump 进 prompt。
        """
        session = self._read_session(session_id)
        if not session:
            return {}

        # 关键步骤名称
        key_steps = {"understand", "classify", "conditions", "tpe",
                     "expert_panel", "suppression_check", "output_signal_analysis"}
        summary_steps = []
        for step in session.get("steps", [])[:max_steps]:
            name = step.get("step", "")
            detail = step.get("detail", {})
            if name in key_steps:
                if isinstance(detail, dict):
                    # 只取前 300 字
                    detail_str = json.dumps(detail, ensure_ascii=False)[:300]
                else:
                    detail_str = str(detail)[:300]
                summary_steps.append(f"  [{name}] {detail_str}")

        return {
            "session_id": session.get("session_id"),
            "case_id": session.get("case_id"),
            "problem": session.get("problem"),
            "status": session.get("status"),
            "completed_at": session.get("completed_at"),
            "key_steps": summary_steps,
            "result_summary": session.get("result_summary", ""),
        }

    def _read_session(self, session_id: str) -> Optional[dict]:
        path = self.memory_dir / "sessions" / f"{session_id}.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return None

    def _write_session(self, session_id: str, data: dict) -> None:
        path = self.memory_dir / "sessions" / f"{session_id}.json"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _prune_old_sessions(self, max_count: int = 20) -> int:
        """清理过期 session，只保留最近 max_count 条。

        清理策略：按 created_at 排序，移除超出限制的 session 文件。
        返回被清理的 session 数量。
        """
        sessions_dir = self.memory_dir / "sessions"
        if not sessions_dir.exists():
            return 0

        # 收集所有 session 文件及时间戳
        sessions_with_mtime: list[tuple[Path, float]] = []
        for fp in sessions_dir.glob("*.json"):
            sessions_with_mtime.append((fp, fp.stat().st_mtime))

        if len(sessions_with_mtime) <= max_count:
            return 0

        # 按 mtime 排序，移除最旧的
        sessions_with_mtime.sort(key=lambda x: x[1])
        to_remove = sessions_with_mtime[:len(sessions_with_mtime) - max_count]

        removed = 0
        for fp, _ in to_remove:
            try:
                fp.unlink()
                removed += 1
            except OSError:
                pass

        return removed

    # ── L5: Case Memory ── (merged into L3 patterns since v2) ──────────

    def read_case_memory(self, case_dir: Path) -> dict:
        """Read per-case persistent memory.

        v2 模式: 优先从 case_dir/memory.json 读取（兼容旧数据），
        若不存在则从 L3 patterns 中查找匹配的条目。
        """
        # 兼容旧数据：仍然可以读 case_dir/memory.json
        path = case_dir / "memory.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))

        # v2: 从 patterns 查找 — case_dir 名作为 symptom 匹配
        case_name = case_dir.name if case_dir.name else str(case_dir)
        patterns = self.read_patterns()
        matches = [p for p in patterns if p.get("symptom", "") == case_name or case_name in p.get("case_id", "")]
        if matches:
            return {"patterns": matches, "_source": "patterns"}
        return {}

    def write_case_memory(self, case_dir: Path, memory: dict) -> None:
        """Write per-case persistent memory.

        v2 模式: case 记忆自动转换为 pattern 条目写入 L3。
        同时将原始数据写入 case_dir/memory.json 以保持兼容。
        """
        memory["_updated"] = datetime.datetime.now().isoformat()
        # 保持旧格式兼容
        (case_dir / "memory.json").write_text(
            json.dumps(memory, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        # v2: 自动转换为 pattern 条目
        case_name = case_dir.name if case_dir.name else str(case_dir)
        pattern = {
            "function": memory.get("function", memory.get("func_name", "UNKNOWN")),
            "symptom": memory.get("problem", memory.get("symptom", case_name)),
            "root_cause": memory.get("root_cause", memory.get("conclusion", "")),
            "keywords": memory.get("keywords", []),
            "fix_hint": memory.get("fix_hint", memory.get("fix", "")),
            "case_id": case_name,
            "_learned_at": datetime.datetime.now().isoformat(),
        }
        self.add_pattern(pattern)

    # ── L6: Code Knowledge (auto-dream 学到的代码知识) ─────────────────

    def read_code_knowledge(self, func_name: str) -> dict:
        """读取某功能的深度代码知识（由 CodeLearner 填充）。

        优先从 per-project 目录读取，若不存在则回退到 legacy 全局目录
        ``memory/code_knowledge/``（兼容旧数据迁移前的路径）。
        """
        func_upper = func_name.upper()
        path = self.memory_dir / "code_knowledge" / f"{func_upper}.json"
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
        # Backward-compat fallback: legacy global code_knowledge
        legacy = self.root / "memory" / "code_knowledge" / f"{func_upper}.json"
        if legacy.exists():
            try:
                return json.loads(legacy.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
        return {}

    def write_code_knowledge(self, func_name: str, data: dict) -> None:
        """写入某功能的深度代码知识（L6）。

        由 CodeLearner（auto-dream）或诊断管线（_precipitate_knowledge）写入。
        """
        d = self.memory_dir / "code_knowledge"
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{func_name.upper()}.json"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

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

        优先从 per-project 目录读取，若不存在则回退到 legacy 全局目录。
        由 ``CodeLearner._learn_constants_if_needed()`` 写入。所有功能共享。
        若文件不存在或损坏返回空 dict。
        """
        path = self.memory_dir / "code_knowledge" / "constants.json"
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
        # Backward-compat fallback
        legacy = self.root / "memory" / "code_knowledge" / "constants.json"
        if legacy.exists():
            try:
                return json.loads(legacy.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
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

        # L4 — 历史诊断 Session（完整诊断记录）
        session_history = self.query_sessions(func_name, keywords, max_results=3)
        if session_history:
            l4_lines = [f"## 历史诊断记录 ({len(session_history)} 条相关 session)"]
            for sh in session_history:
                l4_lines.append(f"### Case: {sh['case_id']} (session: {sh['session_id']})")
                l4_lines.append(f"- 问题描述: {sh['problem']}")
                l4_lines.append(f"- 期望: {sh['expected']}")
                l4_lines.append(f"- 状态: {sh['status']} | 步骤数: {sh['steps_count']} | 相关度: {sh['relevance_score']}")
                if sh.get("result_summary"):
                    l4_lines.append(f"- 结论: {sh['result_summary']}")
                # 附加关键步骤摘要
                details = self.get_session_details(sh["session_id"])
                if details.get("key_steps"):
                    l4_lines.append("- 关键步骤摘要:")
                    for ks in details["key_steps"][:5]:
                        l4_lines.append(f"  {ks}")
            parts.append("\n".join(l4_lines))

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
