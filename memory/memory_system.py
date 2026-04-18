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

    # ── Context Builder ─────────────────────────────────────────────────

    def build_context_for_diagnosis(
        self, func_name: str, problem: str, case_dir: Optional[Path] = None,
    ) -> str:
        """
        Build a comprehensive memory context string for the AI orchestrator.
        Combines relevant memories from all layers.
        """
        parts = []

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

        return "\n\n".join(parts) if parts else "(暂无历史记忆)"
