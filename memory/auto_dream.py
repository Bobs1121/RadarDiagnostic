# -*- coding: utf-8 -*-
"""
AutoDream: Memory consolidation system.
Inspired by Claude Code's auto-dream architecture.

Triggered on startup, the dream cycle:
1. Orient  — Survey all memory layers, identify what's new
2. Gather  — Collect recent sessions, findings, patterns
3. Consolidate — Merge, deduplicate, resolve conflicts, update project memory
4. Prune   — Remove stale entries, update index

Gate conditions (must all be true to trigger):
- Time since last dream >= DREAM_INTERVAL (default 4h)
- New sessions since last dream >= MIN_NEW_SESSIONS (default 2)
- No other dream in progress (lock file)
"""
import json
import os
import time
import datetime
from pathlib import Path
from typing import Optional

# ── Configuration ───────────────────────────────────────────────────────

DREAM_INTERVAL_HOURS = 4
MIN_NEW_SESSIONS = 2
LOCK_FILE = ".dream-lock"
DREAM_LOG_FILE = "dream_log.json"

# ── Consolidation Prompt ────────────────────────────────────────────────

CONSOLIDATION_PROMPT = """你是角雷达问题分析系统的记忆整理专家。
你的任务是整合、去重、修正系统的多层记忆，使之保持精确、一致、有用。

## 你的四阶段工作流

### Phase 1 — Orient (定向)
审视当前记忆全貌:
- 项目记忆 (project.md) 的内容是否准确、完整
- 各功能知识 (functions/*.json) 是否与最新诊断经验一致
- 模式库 (patterns.json) 是否有重复或矛盾
- 近期会话记录中是否有值得固化的新知识

### Phase 2 — Gather (收集)
从近期会话中提取:
- 新发现的规律或模式
- 纠正了之前错误认知的信息
- 用户的分析偏好和习惯
- 项目特有的固定信息（如DBC映射、topic含义、阈值默认值）

### Phase 3 — Consolidate (整合)
核心工作:
- 将新知识合并到已有记忆中，不要创建近似重复条目
- **冲突处理规则**:
  - 时间优先: 较新的诊断结论覆盖较旧的（旧记忆可能基于错误假设）
  - 数据优先: 从实际数据得出的结论优先于推测
  - 频率优先: 多次验证的模式优先于单次出现的
  - 如果冲突无法自动解决，标记为 [CONFLICT] 供人工审核
- 将散落的片段知识整合成结构化的功能知识
- 更新项目记忆中的固定信息

### Phase 4 — Prune (修剪)
清理:
- 删除完全重复的模式条目
- 合并相似度>80%的模式
- 移除已被更新结论取代的旧条目
- 确保每个功能的知识文件不超过合理大小

## 输出格式
请输出JSON:
{
  "project_memory_update": "更新后的项目记忆内容(markdown格式)",
  "function_updates": {
    "FUNC_NAME": {"key": "value", ...}
  },
  "patterns_to_remove": ["pattern_id_1", ...],
  "patterns_to_add": [{"function": "...", "symptom": "...", "root_cause": "...", "keywords": [...], "fix_hint": "..."}],
  "conflicts_found": [{"description": "冲突描述", "resolution": "解决方式", "confidence": 0.0-1.0}],
  "summary": "本次整理的一句话总结"
}"""


class AutoDream:
    """
    Memory consolidation engine.
    Call `try_dream()` on startup; it checks gate conditions and runs
    the consolidation cycle if needed.
    """

    def __init__(self, memory_system, router, project_root: Path):
        self.memory = memory_system
        self.router = router
        self.project_root = project_root
        self.memory_dir = project_root / "memory"
        self.lock_path = self.memory_dir / LOCK_FILE
        self.log_path = self.memory_dir / DREAM_LOG_FILE

    # ── Public API ──────────────────────────────────────────────────────

    def try_dream(self, on_status=None, force: bool = False) -> Optional[dict]:
        """
        Check gate conditions and run dream if appropriate.
        Returns dream result dict or None if skipped.
        """
        def status(msg):
            if on_status:
                on_status("dream", msg)

        if not force and not self._is_gate_open():
            return None

        if self._is_locked():
            status("Another dream is in progress, skipping.")
            return None

        status("Memory consolidation starting...")
        self._acquire_lock()

        try:
            result = self._run_dream_cycle(status)
            self._apply_dream_result(result, status)
            self._record_dream(result)
            self._release_lock()
            status(f"Dream complete: {result.get('summary', 'done')}")
            return result
        except Exception as e:
            self._release_lock()
            status(f"Dream failed: {e}")
            return {"error": str(e)}

    # ── Gate Logic ──────────────────────────────────────────────────────

    def _is_gate_open(self) -> bool:
        """Check if conditions are met for a dream cycle."""
        hours_since = self._hours_since_last_dream()
        if hours_since < DREAM_INTERVAL_HOURS:
            return False

        new_sessions = self._count_new_sessions()
        if new_sessions < MIN_NEW_SESSIONS:
            return False

        return True

    def _hours_since_last_dream(self) -> float:
        """Hours since last completed dream."""
        log = self._read_dream_log()
        if not log:
            return float("inf")
        last = log[-1]
        last_time = datetime.datetime.fromisoformat(last["timestamp"])
        delta = datetime.datetime.now() - last_time
        return delta.total_seconds() / 3600

    def _count_new_sessions(self) -> int:
        """Count sessions created since last dream."""
        log = self._read_dream_log()
        last_dream_time = None
        if log:
            last_dream_time = datetime.datetime.fromisoformat(log[-1]["timestamp"])

        sessions_dir = self.memory_dir / "sessions"
        count = 0
        for f in sessions_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                created = datetime.datetime.fromisoformat(data.get("created_at", "1970-01-01"))
                if last_dream_time is None or created > last_dream_time:
                    count += 1
            except Exception:
                pass
        return count

    # ── Lock ────────────────────────────────────────────────────────────

    def _is_locked(self) -> bool:
        if not self.lock_path.exists():
            return False
        try:
            mtime = os.path.getmtime(self.lock_path)
            age_hours = (time.time() - mtime) / 3600
            if age_hours > 1:  # Stale lock (>1 hour)
                self._release_lock()
                return False
            return True
        except Exception:
            return False

    def _acquire_lock(self):
        self.lock_path.write_text(str(os.getpid()), encoding="utf-8")

    def _release_lock(self):
        try:
            self.lock_path.unlink(missing_ok=True)
        except Exception:
            pass

    def _refresh_variable_chains(self):
        """Refresh variable_chains.json from source code (struct alias tracing)."""
        try:
            from ai.signal_mapper import trace_variable_chains
            source_code = self.config.get("paths", {}).get("source_code", "")
            if source_code:
                trace_variable_chains(
                    Path(source_code),
                    self.project_root / "source_docs",
                )
        except Exception:
            pass

    # ── Dream Cycle ─────────────────────────────────────────────────────

    def _run_dream_cycle(self, status) -> dict:
        """Execute the 4-phase consolidation with AI."""
        status("Phase 1/4: Orient — surveying memories...")
        self._refresh_variable_chains()
        context = self._gather_all_memory_context()

        status("Phase 2/4: Gather — collecting recent sessions...")
        recent = self._gather_recent_sessions()

        status("Phase 3/4: Consolidate — AI merging & resolving conflicts...")
        prompt = self._build_prompt(context, recent)
        result = self.router.complex(prompt, system=CONSOLIDATION_PROMPT)
        content = result.get("content", "{}")

        status("Phase 4/4: Prune — applying changes...")
        try:
            start = content.index("{")
            end = content.rindex("}") + 1
            return json.loads(content[start:end])
        except (ValueError, json.JSONDecodeError):
            return {
                "summary": "Dream completed but output parsing failed",
                "raw_output": content[:2000],
            }

    def _gather_all_memory_context(self) -> str:
        """Gather current state of all memory layers."""
        parts = []

        # L1
        project_mem = self.memory.read_project_memory()
        parts.append(f"## L1 项目记忆 (project.md)\n{project_mem}")

        # L2
        func_names = self.memory.get_all_function_names()
        for name in func_names:
            k = self.memory.read_function_knowledge(name)
            parts.append(f"## L2 功能知识: {name}\n{json.dumps(k, ensure_ascii=False, indent=1)[:2000]}")

        # L3
        patterns = self.memory.read_patterns()
        if patterns:
            parts.append(f"## L3 模式库 ({len(patterns)} 条)\n{json.dumps(patterns, ensure_ascii=False, indent=1)[:3000]}")

        # Source docs summary (*.md)
        docs_dir = self.project_root / "source_docs"
        for md in docs_dir.glob("*.md"):
            try:
                content = md.read_text(encoding="utf-8")
                parts.append(f"## 源码文档: {md.stem}\n{content[:500]}...")
            except Exception:
                pass

        # Signal mapping summary
        sig_map_path = docs_dir / "signal_mapping.json"
        if sig_map_path.exists():
            try:
                sig_map = json.loads(sig_map_path.read_text(encoding="utf-8"))
                count = sig_map.get("mapping_count", 0)
                i2c = sig_map.get("internal_to_can", {})
                sample = list(i2c.items())[:20]
                lines = [f"## 信号映射 (signal_mapping.json, {count}条)"]
                for var, sigs in sample:
                    lines.append(f"  {var} → {', '.join(sigs)}")
                if len(i2c) > 20:
                    lines.append(f"  ... +{len(i2c)-20} more")
                parts.append("\n".join(lines))
            except Exception:
                pass

        # Variable chains summary
        chains_path = docs_dir / "variable_chains.json"
        if chains_path.exists():
            try:
                chains = json.loads(chains_path.read_text(encoding="utf-8"))
                aliases = chains.get("struct_aliases", {})
                alias_details = chains.get("alias_details", {})
                ambiguous = chains.get("ambiguous", {})
                if aliases or ambiguous:
                    lines = [f"## 变量链 (variable_chains.json, {len(aliases)}条别名)"]
                    for gvar, prefix in aliases.items():
                        detail = alias_details.get(gvar, {})
                        conf = detail.get("confidence", "?")
                        reason = detail.get("reason", "?")
                        lines.append(f"  {gvar}.* → {prefix}.* [confidence={conf}, {reason}]")
                    if ambiguous:
                        lines.append(f"  ⚠ 歧义未收录 ({len(ambiguous)}): {', '.join(ambiguous.keys())}")
                    parts.append("\n".join(lines))
            except Exception:
                pass

        # L5: Recent case memories
        cases_dir = self.project_root / "cases"
        if cases_dir.exists():
            case_mems = []
            for mem_file in sorted(cases_dir.glob("*/memory.json"),
                                   key=lambda p: p.stat().st_mtime, reverse=True)[:5]:
                try:
                    data = json.loads(mem_file.read_text(encoding="utf-8"))
                    case_id = mem_file.parent.name
                    case_mems.append(f"- {case_id}: {json.dumps(data, ensure_ascii=False, default=str)[:300]}")
                except Exception:
                    pass
            if case_mems:
                parts.append(f"## L5 近期案例记忆 ({len(case_mems)} 个)\n" + "\n".join(case_mems))

        return "\n\n".join(parts)

    def _gather_recent_sessions(self) -> str:
        """Gather recent session data for consolidation."""
        sessions_dir = self.memory_dir / "sessions"
        sessions = []
        for f in sorted(sessions_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                sessions.append(data)
            except Exception:
                pass

        if not sessions:
            return "(无近期会话)"

        parts = [f"## 近期会话 ({len(sessions)} 个)"]
        for s in sessions[:10]:  # Cap at 10 most recent
            parts.append(f"\n### Session: {s.get('session_id', '?')}")
            parts.append(f"- 问题: {s.get('problem', '?')}")
            parts.append(f"- 状态: {s.get('status', '?')}")
            parts.append(f"- 结果: {s.get('result_summary', '?')[:300]}")
            findings = s.get("findings", [])
            if findings:
                parts.append(f"- 关键发现: {json.dumps(findings[:3], ensure_ascii=False, default=str)[:500]}")

        return "\n".join(parts)

    def _build_prompt(self, context: str, recent: str) -> str:
        """Build the consolidation prompt for AI."""
        return f"""请整理以下角雷达分析系统的多层记忆。

{context}

---

{recent}

---

请执行四阶段记忆整理（Orient → Gather → Consolidate → Prune），特别注意:
1. 合并重复的模式条目
2. 解决前后矛盾的记忆（新的覆盖旧的，数据结论优先于推测）
3. 将散落的知识整合到功能知识文件中
4. 更新项目记忆中的固定信息
5. 提取用户的使用偏好和分析习惯

输出上述指定的JSON格式。"""

    # ── Apply Results ───────────────────────────────────────────────────

    def _apply_dream_result(self, result: dict, status):
        """Apply the AI's consolidation results to memory files."""
        # Update project memory
        if result.get("project_memory_update"):
            status("Updating project memory...")
            self.memory.write_project_memory(result["project_memory_update"])

        # Update function knowledge
        for func_name, updates in result.get("function_updates", {}).items():
            status(f"Updating {func_name} knowledge...")
            existing = self.memory.read_function_knowledge(func_name)
            existing.update(updates)
            self.memory.write_function_knowledge(func_name, existing)

        # Remove old patterns
        to_remove = set(result.get("patterns_to_remove", []))
        if to_remove:
            patterns = self.memory.read_patterns()
            patterns = [p for p in patterns if p.get("_id") not in to_remove]
            (self.memory_dir / "patterns.json").write_text(
                json.dumps(patterns, ensure_ascii=False, indent=2), encoding="utf-8"
            )

        # Add new patterns
        for p in result.get("patterns_to_add", []):
            self.memory.add_pattern(p)

        # Log conflicts
        conflicts = result.get("conflicts_found", [])
        if conflicts:
            status(f"Found {len(conflicts)} conflict(s)")

    # ── Dream Log ───────────────────────────────────────────────────────

    def _read_dream_log(self) -> list[dict]:
        if self.log_path.exists():
            try:
                return json.loads(self.log_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return []

    def _record_dream(self, result: dict):
        """Record this dream in the log."""
        log = self._read_dream_log()
        log.append({
            "timestamp": datetime.datetime.now().isoformat(),
            "summary": result.get("summary", "completed"),
            "conflicts": len(result.get("conflicts_found", [])),
            "patterns_added": len(result.get("patterns_to_add", [])),
            "patterns_removed": len(result.get("patterns_to_remove", [])),
        })
        if len(log) > 100:
            log = log[-100:]
        self.log_path.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
