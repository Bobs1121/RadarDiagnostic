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
import logging
import os
import tempfile
from pathlib import Path
from typing import Optional, Any


# ── Atomic write helpers (Phase 15 / 2.2.1) ──────────────────────────
#
# Concurrent diagnosis + auto_dream writers must not corrupt each other.
# ``atomic_write_text`` / ``atomic_write_json`` write to ``<path>.tmp`` first,
# then ``os.replace`` (atomic on POSIX, best-effort atomic on Windows) to the
# final path. A crash mid-write leaves the original file untouched and a
# stale ``.tmp`` that subsequent reads will simply ignore.

def atomic_write_text(path: Path, content: str, encoding: str = "utf-8") -> None:
    """Atomically write ``content`` to ``path``.

    Writes via ``path.with_suffix(path.suffix + '.tmp')`` then ``os.replace``.
    The parent directory is created if missing. Existing files are never
    truncated to zero before the rename — readers will always see either the
    old content or the new content, never partial bytes.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        with open(tmp, "w", encoding=encoding, newline="") as f:
            f.write(content)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                # fsync not supported on this platform; skip silently.
                pass
        os.replace(tmp, path)
    except Exception:
        # Leave any .tmp behind for forensics; do NOT remove the original.
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
        raise


def atomic_write_json(path: Path, data: Any, encoding: str = "utf-8",
                      ensure_ascii: bool = False, indent: int = 2) -> None:
    """Atomically write JSON-serialisable ``data`` to ``path``."""
    payload = json.dumps(data, ensure_ascii=ensure_ascii, indent=indent,
                         default=str)
    atomic_write_text(path, payload, encoding=encoding)


logger = logging.getLogger(__name__)


class MemorySystem:
    """Multi-layer persistent memory for the radar analysis system."""

    def __init__(
        self,
        project_root: Path | str,
        memory_dir: Path | str | None = None,
        config: Optional[dict] = None,
    ):
        self.root = Path(project_root)
        self.memory_dir = Path(memory_dir) if memory_dir else (self.root / "memory")
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        (self.memory_dir / "functions").mkdir(exist_ok=True)
        (self.memory_dir / "sessions").mkdir(exist_ok=True)
        (self.memory_dir / "code_knowledge").mkdir(exist_ok=True)
        self._config = config if isinstance(config, dict) else None
        self._config_loaded = config is not None
        self._semantic_memory = None
        self._semantic_ready = False

        # Session-level context cache.
        # Avoids rebuilding the diagnosis context multiple times per run
        # (orchestrator calls build_context_for_diagnosis ~3 times per case).
        # Cache is invalidated when this MemorySystem instance is discarded.
        self._ctx_cache: dict[tuple, str] = {}
        self._ctx_cache_hits: int = 0
        self._ctx_cache_misses: int = 0

    def _load_runtime_config(self) -> dict:
        """Load config.yaml lazily when the caller did not inject a config dict."""
        if self._config_loaded:
            return self._config or {}

        self._config_loaded = True
        config_path = self.root / "config.yaml"
        if not config_path.exists():
            self._config = {}
            return {}

        try:
            from config import load_config as load_project_config

            loaded = load_project_config(config_path)
            self._config = loaded if isinstance(loaded, dict) else {}
        except Exception as exc:
            logger.warning("failed to load memory config from %s: %s", config_path, exc)
            self._config = {}
        return self._config or {}

    def _semantic_index_settings(self) -> dict:
        """Return semantic-index settings with safe defaults."""
        cfg = self._load_runtime_config()
        raw = cfg.get("memory", {}).get("semantic_index", {}) if isinstance(cfg, dict) else {}
        if not isinstance(raw, dict):
            raw = {}
        enabled = raw.get("enabled", True)
        try:
            max_hits = int(raw.get("max_hits", 3))
        except (TypeError, ValueError):
            max_hits = 3
        return {
            "enabled": bool(enabled),
            "max_hits": max(1, max_hits),
        }

    def _get_semantic_memory(self):
        """Lazily create the variant-scoped SemanticMemory index.

        Uses the V3 workspace sandbox path ``.workspaces/<variant>/memory/lancedb``
        (via ``SemanticMemory.for_variant``) when a variant_id is resolvable,
        otherwise falls back to the local ``memory_dir/semantic``.
        """
        settings = self._semantic_index_settings()
        if not settings.get("enabled", True):
            return None
        if self._semantic_ready:
            return self._semantic_memory
        if self._semantic_memory is False:
            return None

        try:
            from memory.semantic_memory import SemanticMemory

            variant_id = self._resolve_variant_id()
            if variant_id:
                self._semantic_memory = SemanticMemory.for_variant(
                    self.root, variant_id,
                )
            else:
                self._semantic_memory = SemanticMemory(
                    store_dir=self.memory_dir / "semantic",
                )
            self._semantic_ready = True
        except Exception as exc:
            self._semantic_memory = False
            logger.warning("semantic index unavailable for %s: %s", self.memory_dir, exc)
            return None
        return self._semantic_memory

    def _resolve_variant_id(self) -> str:
        """Best-effort variant_id from injected config, else empty string."""
        if self._config is None:
            return ""
        identity = self._config.get("identity") or {}
        return str(identity.get("variant_id") or "") or ""

    def _code_learning_stale(self) -> bool:
        """Whether code-derived learning products should be withheld.

        Returns True when the current code/constants/identity have drifted since
        the last freshness snapshot. This gates the code-derived learning layers
        (L3 auto-dream patterns, semantic hits, and L6 — already gated) out of
        the AI context, while leaving operator/user notes (L1/L2/L4/L5)
        unaffected. Mirrors the AGENTS.md freshness hard constraint.
        """
        cfg = self._load_runtime_config()
        freshness = (cfg.get("identity") or {}).get("freshness") or {}
        if not isinstance(freshness, dict):
            return False
        return bool(
            freshness.get("code_changed")
            or freshness.get("constants_changed")
            or freshness.get("identity_changed")
        )

    def _relative_provenance_path(self, path: Path) -> str:
        """Render a stable provenance path, preferring project-relative paths."""
        try:
            return str(path.resolve().relative_to(self.root.resolve()))
        except Exception:
            try:
                return str(path.relative_to(self.root))
            except Exception:
                return str(path)

    @staticmethod
    def _truncate_text(text: Any, limit: int = 120) -> str:
        text = str(text or "").strip()
        if len(text) <= limit:
            return text
        return text[: max(0, limit - 3)] + "..."

    def _index_case_memory_semantically(self, case_dir: Path, memory: dict) -> None:
        """Add a compact provenance-linked semantic record for this case."""
        semantic = self._get_semantic_memory()
        if semantic is None:
            return

        case_id = case_dir.name if case_dir.name else str(case_dir)
        case_memory_path = case_dir / "memory.json"
        report_path = case_dir / "report.md"
        report_provenance = (
            self._relative_provenance_path(report_path) if report_path.exists() else ""
        )
        function_name = str(memory.get("function") or memory.get("func_name") or "UNKNOWN")
        symptom = str(memory.get("problem") or memory.get("symptom") or case_id)
        conclusion = str(
            memory.get("root_cause")
            or memory.get("conclusion")
            or memory.get("diagnosis_summary")
            or memory.get("result_summary")
            or ""
        )
        fix_hint = str(memory.get("fix_hint") or memory.get("fix") or "")
        updated_at = str(memory.get("_updated") or datetime.datetime.now().isoformat())
        metadata = {
            "function": function_name,
            "case_id": case_id,
            "updated_at": updated_at,
            "fix_hint": fix_hint,
            "case_dir": self._relative_provenance_path(case_dir),
            "case_memory_path": self._relative_provenance_path(case_memory_path),
            "report_path": report_provenance,
            "provenance": {
                "case_dir": self._relative_provenance_path(case_dir),
                "case_memory_path": self._relative_provenance_path(case_memory_path),
                "report_path": report_provenance,
            },
        }
        try:
            semantic.add(
                symptom=symptom,
                signal=function_name,
                code_line=fix_hint,
                conclusion=conclusion,
                metadata=metadata,
            )
        except Exception as exc:
            logger.warning("semantic index add failed for %s: %s", case_id, exc)

    def _search_semantic_cases(
        self,
        func_name: str,
        problem: str,
        *,
        case_dir: Optional[Path] = None,
    ) -> list[dict]:
        """Return compact semantic hits for prior related cases."""
        semantic = self._get_semantic_memory()
        if semantic is None:
            return []

        settings = self._semantic_index_settings()
        limit = int(settings.get("max_hits", 3))
        query = "\n".join(
            part for part in [(func_name or "").upper(), (problem or "").strip()] if part
        )
        if not query:
            return []

        try:
            raw_hits = semantic.search(query, k=max(limit * 2, limit))
        except Exception as exc:
            logger.warning("semantic index search failed for %s: %s", func_name, exc)
            return []

        current_case_id = case_dir.name if case_dir else ""
        func_upper = (func_name or "").upper()
        preferred: list[dict] = []
        fallback: list[dict] = []
        for hit in raw_hits:
            score = float(hit.get("score", 0.0) or 0.0)
            if score <= 0.0:
                continue
            meta = hit.get("metadata", {}) or {}
            case_id = str(meta.get("case_id") or "")
            if current_case_id and case_id == current_case_id:
                continue
            hit_func = str(meta.get("function") or hit.get("signal") or "").upper()
            if func_upper and hit_func == func_upper:
                preferred.append(hit)
            else:
                fallback.append(hit)
        return (preferred + fallback)[:limit]

    def search_semantic_cases(
        self,
        func_name: str,
        problem: str,
        *,
        case_dir: Optional[Path] = None,
        max_results: int = 3,
    ) -> list[dict]:
        """Public read-only semantic recall boundary for Pi capabilities.

        The existing private implementation remains the single source of
        ranking/filtering behavior; this narrow wrapper lets an atomic tool
        expose it without coupling Pi to private method names.
        """
        hits = self._search_semantic_cases(func_name, problem, case_dir=case_dir)
        return hits[:max(0, int(max_results))]

    def _render_semantic_hits(self, hits: list[dict]) -> str:
        """Render semantic recall as a clearly non-deterministic hint block."""
        if not hits:
            return ""

        lines = [
            "## 语义相似案例（SemanticMemory 索引，仅供参考，非确定性证据）"
        ]
        for hit in hits:
            meta = hit.get("metadata", {}) or {}
            case_id = str(meta.get("case_id") or "?")
            score = float(hit.get("score", 0.0) or 0.0)
            symptom = self._truncate_text(hit.get("symptom", "?"), limit=80)
            conclusion = self._truncate_text(hit.get("conclusion", ""), limit=100)
            fix_hint = self._truncate_text(meta.get("fix_hint", ""), limit=80)
            report_path = (
                meta.get("report_path")
                or meta.get("case_memory_path")
                or meta.get("case_dir")
                or ""
            )
            line = f"- score={score:.3f} | case={case_id} | 症状: {symptom}"
            if conclusion:
                line += f" | 结论: {conclusion}"
            if fix_hint:
                line += f" | 修复: {fix_hint}"
            lines.append(line)
            if report_path:
                lines.append(f"  provenance: `{report_path}`")
        return "\n".join(lines)

    # ── L1: Project Memory ──────────────────────────────────────────────

    def read_project_memory(self) -> str:
        """Read the global project memory."""
        path = self.memory_dir / "project.md"
        if path.exists():
            return path.read_text(encoding="utf-8")
        return ""

    def write_project_memory(self, content: str) -> None:
        """Overwrite project memory (AI manages the content)."""
        atomic_write_text(self.memory_dir / "project.md", content)

    def append_project_memory(self, entry: str) -> None:
        """Append a new entry to project memory."""
        path = self.memory_dir / "project.md"
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        new_content = f"{existing}\n\n## [{timestamp}]\n{entry}" if existing else f"# Project Memory\n\n## [{timestamp}]\n{entry}"
        atomic_write_text(path, new_content)

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
        atomic_write_json(path, knowledge)

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
        """Add a new learned pattern from a diagnosis, deduplicating by content hash.

        Phase 15 / 2.2.4: switched from MD5[:8] (32-bit, collision-prone at scale)
        to SHA256[:12] (48-bit, ~2^-24 collision probability). Existing
        short-MD5 IDs are still recognised on lookup because the comparison is
        a plain ``==`` over the ``_id`` string field — both encodings coexist.
        """
        patterns = self.read_patterns()

        content_key = {
            k: v for k, v in pattern.items()
            if not k.startswith("_")
        }
        # SHA256[:12] = 12 hex chars = 48-bit hash. Collision probability
        # at N=10k entries is ~N^2/2^49 ≈ 1.7e-8, which is acceptable.
        content_hash = hashlib.sha256(
            json.dumps(content_key, sort_keys=True, default=str).encode()
        ).hexdigest()[:12]

        if any(p.get("_id") == content_hash for p in patterns):
            return

        pattern["_learned_at"] = datetime.datetime.now().isoformat()
        pattern["_id"] = content_hash
        # Initial hit_count: zero — incremented by record_pattern_hit()
        pattern.setdefault("_hit_count", 0)
        patterns.append(pattern)
        atomic_write_json(self.memory_dir / "patterns.json", patterns)

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

    def record_pattern_hit(self, pattern_id: str) -> None:
        """Increment ``_hit_count`` for a pattern matched during diagnosis.

        Phase 15 / 2.2.3 — patterns that are actively cited should resist
        the decay sweep. Calling site: ``build_context_for_diagnosis`` when
        a pattern from ``find_similar_patterns`` is included in context.
        """
        patterns = self.read_patterns()
        touched = False
        for p in patterns:
            if p.get("_id") == pattern_id:
                p["_hit_count"] = int(p.get("_hit_count", 0)) + 1
                p["_last_hit_at"] = datetime.datetime.now().isoformat()
                touched = True
                break
        if touched:
            atomic_write_json(self.memory_dir / "patterns.json", patterns)

    def decay_patterns(self, max_age_days: int = 90, min_hit_count: int = 3,
                        dry_run: bool = False) -> dict:
        """Phase 15 / 2.2.3 — prune stale patterns.

        Removes patterns whose ``_learned_at`` is older than ``max_age_days``
        AND whose ``_hit_count`` is below ``min_hit_count``. This keeps the
        memory small and biased toward recent, actively-cited patterns.

        Returns a summary dict ``{"removed": [...], "kept": int, "dry_run": bool}``.
        """
        patterns = self.read_patterns()
        now = datetime.datetime.now()
        kept: list[dict] = []
        removed: list[dict] = []
        for p in patterns:
            learned = p.get("_learned_at")
            hit_count = int(p.get("_hit_count", 0))
            age_days: Optional[int] = None
            if learned:
                try:
                    age_days = (now - datetime.datetime.fromisoformat(learned)).days
                except ValueError:
                    age_days = None
            stale = (age_days is not None and age_days > max_age_days
                     and hit_count < min_hit_count)
            if stale:
                removed.append({
                    "_id": p.get("_id"),
                    "function": p.get("function"),
                    "age_days": age_days,
                    "hit_count": hit_count,
                })
            else:
                kept.append(p)

        if not dry_run and removed:
            atomic_write_json(self.memory_dir / "patterns.json", kept)

        return {"removed": removed, "kept": len(kept), "dry_run": dry_run}

    def migrate_pattern_ids(self, dry_run: bool = True) -> dict:
        """Phase 15 / 2.2.4 follow-up: re-hash legacy MD5[:8] IDs to SHA256[:12].

        Legacy patterns have 8-char hex IDs from the MD5-based ``add_pattern``.
        New entries get 12-char SHA256 IDs. Because the two encodings cannot
        collide, ``add_pattern`` cannot recognise an existing legacy entry as
        a duplicate of a re-added identical-content one — leading to slow
        duplication over time.

        This method walks ``patterns.json``, recomputes SHA256[:12] for every
        pattern whose ``_id`` is shorter than 12 chars, and rewrites the file
        with the new IDs.

        Returns a summary dict ``{"migrated": int, "already_new": int,
        "duplicates_removed": int, "dry_run": bool}``.
        """
        patterns = self.read_patterns()
        migrated = 0
        already_new = 0
        seen_new_ids: dict[str, dict] = {}
        deduped: list[dict] = []
        duplicates_removed = 0
        for p in patterns:
            old_id = p.get("_id", "")
            if len(old_id) >= 12:
                already_new += 1
                # Still fold into the dedup map so legacy entries that
                # happen to match a new entry's hash get culled.
                if old_id in seen_new_ids:
                    duplicates_removed += 1
                    continue
                seen_new_ids[old_id] = p
                deduped.append(p)
                continue

            # Recompute SHA256[:12] from content (everything except
            # underscore-prefixed internal fields).
            content_key = {
                k: v for k, v in p.items() if not k.startswith("_")
            }
            new_id = hashlib.sha256(
                json.dumps(content_key, sort_keys=True, default=str).encode()
            ).hexdigest()[:12]
            p["_id"] = new_id
            migrated += 1
            if new_id in seen_new_ids:
                # Re-add of identical content after migration → drop.
                duplicates_removed += 1
                continue
            seen_new_ids[new_id] = p
            deduped.append(p)

        if not dry_run and (migrated or duplicates_removed):
            atomic_write_json(self.memory_dir / "patterns.json", deduped)

        return {
            "migrated": migrated,
            "already_new": already_new,
            "duplicates_removed": duplicates_removed,
            "dry_run": dry_run,
        }

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
        atomic_write_json(path, data)

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
        atomic_write_json(case_dir / "memory.json", memory)
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
        self._index_case_memory_semantically(case_dir, memory)

    # ── L6: Code Knowledge (auto-dream 学到的代码知识) ─────────────────

    def read_code_knowledge(self, func_name: str) -> dict:
        """读取某功能的深度代码知识（由 CodeLearner 填充）。

        优先从 per-project 目录读取，若不存在则回退到 legacy 全局目录
        ``memory/code_knowledge/``（兼容旧数据迁移前的路径）。
        """
        config = self._load_runtime_config()
        from core.knowledge_guard import runtime_knowledge_decision

        if not runtime_knowledge_decision(
            config, f"code_knowledge:{func_name.upper()}"
        ).allowed:
            return {}
        variant_scoped = bool(config.get("identity", {}).get("variant_id"))
        func_upper = func_name.upper()
        path = self.memory_dir / "code_knowledge" / f"{func_upper}.json"
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
        if variant_scoped:
            return {}
        # Backward-compat fallback for unscoped legacy mode only.
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
        注意：这是**整文件覆盖**。跨来源合并请用 :meth:`merge_code_knowledge`。
        """
        d = self.memory_dir / "code_knowledge"
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{func_name.upper()}.json"
        atomic_write_json(path, data)

    def merge_code_knowledge(self, func_name: str, updates: dict) -> dict:
        """增量合并代码知识到 L6 ``{FUNC}.json``（单一写入口 / 统一 schema）。

        读取**底层原始文件**（不受 freshness 门控，避免 stale 时读到空而覆盖
        CodeLearner 已学数据），按 focus 逐键合并：

        * list 条目按 ``id`` 幂等合并（新覆盖旧）；
        * dict 条目按键覆盖；
        * 保留 ``_meta``（learned_focuses / last_updated）。

        返回合并后的完整 dict。调用方（orchestrator ``_precipitate_knowledge``）
        应改用此方法，而不是 ``read_code_knowledge()`` + ``write_code_knowledge()``。
        """
        func_upper = func_name.upper()
        d = self.memory_dir / "code_knowledge"
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{func_upper}.json"

        existing: dict = {}
        if path.exists():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    existing = loaded
            except (json.JSONDecodeError, OSError):
                existing = {}

        meta = existing.setdefault(
            "_meta", {"function": func_upper, "learned_focuses": []}
        )

        for focus, focus_data in (updates or {}).items():
            if not isinstance(focus_data, dict) or focus == "_meta":
                continue
            existing_focus = existing.setdefault(focus, {})

            for key, new_items in focus_data.items():
                if isinstance(new_items, list):
                    existing_list = existing_focus.setdefault(key, [])
                    existing_ids = {
                        item.get("id") for item in existing_list
                        if isinstance(item, dict) and item.get("id")
                    }
                    for item in new_items:
                        if not isinstance(item, dict):
                            continue
                        item_id = item.get("id")
                        if item_id:
                            existing_list = [
                                i for i in existing_list
                                if not isinstance(i, dict) or i.get("id") != item_id
                            ]
                        existing_list.append(item)
                    existing_focus[key] = existing_list
                elif isinstance(new_items, dict):
                    existing_key = existing_focus.setdefault(key, {})
                    for sub_key, sub_val in new_items.items():
                        existing_key[sub_key] = sub_val

            if focus not in meta.get("learned_focuses", []):
                meta.setdefault("learned_focuses", []).append(focus)

        atomic_write_json(path, existing)
        return existing

    def read_code_knowledge_raw(self, func_name: str) -> dict:
        """读取 L6 ``{FUNC}.json`` 的**底层原始内容**（不受 freshness 门控）。

        仅供跨来源合并 / 审计读取使用；喂给 AI prompt 前必须走
        :meth:`read_code_knowledge`（freshness 门控）。
        """
        func_upper = func_name.upper()
        path = self.memory_dir / "code_knowledge" / f"{func_upper}.json"
        if not path.exists():
            return {}
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            return loaded if isinstance(loaded, dict) else {}
        except (json.JSONDecodeError, OSError):
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

        优先从 per-project 目录读取，若不存在则回退到 legacy 全局目录。
        由 ``CodeLearner._learn_constants_if_needed()`` 写入。所有功能共享。
        若文件不存在或损坏返回空 dict。
        """
        config = self._load_runtime_config()
        from core.knowledge_guard import runtime_knowledge_decision

        if not runtime_knowledge_decision(
            config, "code_knowledge:constants"
        ).allowed:
            return {}
        variant_scoped = bool(config.get("identity", {}).get("variant_id"))
        path = self.memory_dir / "code_knowledge" / "constants.json"
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
        if variant_scoped:
            return {}
        # Backward-compat fallback for unscoped legacy mode only.
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

        # L3 — auto-dream learned patterns (code-derived learning product)
        learning_stale = self._code_learning_stale()
        keywords = [w for w in problem.replace("，", " ").replace(",", " ").split() if len(w) > 1]
        similar: list[dict] = []
        if learning_stale:
            parts.append(
                "## 相似历史案例\n_（代码已漂移，Auto-Dream 学习产物暂不注入，避免污染当前分析）_"
            )
        else:
            similar = self.find_similar_patterns(func_name, keywords)
            if similar:
                parts.append(f"## 相似历史案例 ({len(similar)} 条)")
                for p in similar[:3]:
                    parts.append(f"- 症状: {p.get('symptom', '?')} -> 根因: {p.get('root_cause', '?')}")
                # Phase 15 / 2.2 follow-up: bump _hit_count for every pattern
                # actually surfaced into the diagnosis context. Patterns that
                # never appear here will get pruned by decay_patterns()
                # even if they were once useful.
                for p in similar[:3]:
                    pid = p.get("_id")
                    if pid:
                        try:
                            self.record_pattern_hit(pid)
                        except Exception:
                            # Hit bookkeeping must NEVER break diagnosis.
                            pass

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

        if learning_stale:
            parts.append(
                "## 语义记忆\n_（代码已漂移，语义记忆暂不注入）_"
            )
        else:
            semantic_hits = self._search_semantic_cases(func_name, problem, case_dir=case_dir)
            semantic_block = self._render_semantic_hits(semantic_hits)
            if semantic_block:
                parts.append(semantic_block)

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
