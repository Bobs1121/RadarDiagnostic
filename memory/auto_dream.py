# -*- coding: utf-8 -*-
"""
AutoDream: Memory consolidation system.
Inspired by Claude Code's auto-dream architecture.

Triggered explicitly (or optionally before case routing when enabled), the
dream cycle:
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
from config import resolve_source_docs_dir

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

    def __init__(self, memory_system, router, project_root: Path, config: Optional[dict] = None):
        self.memory = memory_system
        self.router = router
        self.project_root = project_root
        self.config = config or {}
        # Use MemorySystem's memory_dir (already project-scoped via config)
        self.memory_dir = memory_system.memory_dir
        self.lock_path = self.memory_dir / LOCK_FILE
        self.log_path = self.memory_dir / DREAM_LOG_FILE

    # ── Public API ──────────────────────────────────────────────────────

    def try_dream(
        self,
        on_status=None,
        force: bool = False,
        reason: Optional[str] = None,
    ) -> Optional[dict]:
        """
        Check gate conditions and run dream if appropriate.

        Args:
            on_status: callback (stage, msg) for progress
            force: bypass gate conditions

        Returns dream result dict or None if skipped.

        Note:
            代码学习量由 ``CodeLearner`` 内部自适应判断：冷启动（首次做梦）
            使用 ``warmup_pairs``，热启动使用 ``pairs_per_dream``。
            调用方无需关心学习策略。
        """
        def status(msg):
            if on_status:
                on_status("dream", msg)

        if not force and not self._is_gate_open():
            return None

        if self._is_locked():
            status("Another dream is in progress, skipping.")
            return None

        if force and reason:
            status(f"Forcing dream: {reason}")

        status("Memory consolidation starting...")
        self._acquire_lock()

        try:
            result = self._run_dream_cycle(status)
            freshness = (self.config or {}).get("identity", {}).get("freshness")
            if isinstance(freshness, dict):
                result["_freshness"] = {
                    "any_changed": freshness.get("any_changed", False),
                    "changed_keys": list(freshness.get("changed_keys", [])),
                    "state_path": freshness.get("state_path"),
                }
            if reason:
                result["_force_reason"] = reason
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

    def _read_lock_pid(self) -> Optional[int]:
        try:
            raw = self.lock_path.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        if not raw:
            return None
        try:
            pid = int(raw)
        except ValueError:
            return None
        return pid if pid > 0 else None

    def _pid_is_running(self, pid: int) -> Optional[bool]:
        if pid <= 0:
            return None

        if os.name == "nt":
            import ctypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            access = 0x00100000 | 0x1000  # SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION
            handle = kernel32.OpenProcess(access, False, pid)
            if handle:
                kernel32.CloseHandle(handle)
                return True

            error = ctypes.get_last_error()
            if error == 87:  # ERROR_INVALID_PARAMETER
                return False
            if error == 5:  # ERROR_ACCESS_DENIED
                return None
            return None

        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return None
        return True

    def _is_locked(self) -> bool:
        if not self.lock_path.exists():
            return False

        pid = self._read_lock_pid()
        if pid is not None:
            is_running = self._pid_is_running(pid)
            if is_running is False:
                self._release_lock()
                return False
            if is_running is True:
                return True

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
            from engines.signal_mapper import trace_variable_chains
            source_code = (self.config or {}).get("paths", {}).get("source_code", "")
            if source_code:
                result = trace_variable_chains(
                    Path(source_code),
                    resolve_source_docs_dir(self.config, self.project_root),
                )
                return {
                    "ok": True,
                    "alias_count": len(result.get("struct_aliases", {})),
                }
            return {"ok": False, "reason": "source_root_missing"}
        except Exception as exc:
            return {"ok": False, "error": str(exc)[:200]}

    def _run_code_learning(self, status) -> dict:
        """Phase 0 — 委托 CodeLearner 做增量代码学习 + MD 概览同步。

        两个子步骤：
          (a) ``learn()``                — 增量学习结构化 JSON（memory/code_knowledge/）
          (b) ``ensure_overview_docs()`` — 源码 hash 驱动刷新 MD 概览（source_docs/）

        学习量由 CodeLearner 内部自适应：
          - 冷启动（warmup_done=False）：使用 config.warmup_pairs
          - 热启动：使用 config.pairs_per_dream
        调用方无需关心策略细节。
        """
        try:
            from ai.code_learner import CodeLearner
        except Exception as e:  # noqa: BLE001
            status(f"CodeLearner import failed: {e}")
            return {"skipped": True, "reason": f"import_error: {e}"}

        if not self.config:
            status("No config provided, skipping code learning")
            return {"skipped": True, "reason": "no_config"}

        try:
            learner = CodeLearner(self.router, self.config, self.project_root)
        except Exception as e:  # noqa: BLE001
            status(f"CodeLearner init failed: {e}")
            return {"skipped": True, "reason": f"init_error: {e}"}

        learn_result = learner.learn(status_cb=lambda _s, d: status(d))

        # (b) MD 概览保鲜：hash 驱动，源码未变则 0 次 AI 调用
        try:
            overview_result = learner.ensure_overview_docs(
                status_cb=lambda _s, d: status(d),
            )
            learn_result["overview"] = {
                "generated": overview_result.get("generated", []),
                "skipped": overview_result.get("skipped", []),
                "skipped_count": len(overview_result.get("skipped", [])),
                "failed": overview_result.get("failed", []),
            }
        except Exception as e:  # noqa: BLE001
            status(f"Overview refresh failed: {e}")
            learn_result["overview"] = {"error": str(e)[:200]}

        return learn_result

    def _refresh_conditions(self, status) -> dict:
        """Refresh only condition modules already materialized for this variant."""
        freshness = self.config.get("identity", {}).get("freshness", {})
        if not any(freshness.get(key) for key in (
            "code_changed", "constants_changed", "identity_changed",
        )):
            return {"ok": True, "refreshed": [], "skipped": "no_code_drift"}
        try:
            from ai.condition_extractor import ConditionExtractor

            docs_dir = resolve_source_docs_dir(self.config, self.project_root)
            functions = sorted({
                path.name[:-len("_conditions.json")].upper()
                for path in docs_dir.glob("*_conditions.json")
            })
            if not functions:
                return {"ok": True, "refreshed": [], "skipped": "no_existing_modules"}
            extractor = ConditionExtractor(self.router, self.project_root, self.config)
            refreshed: list[str] = []
            failed: list[dict] = []
            for function in functions:
                try:
                    result = extractor.extract(function, force=True)
                    if result and "error" not in result:
                        refreshed.append(function)
                    else:
                        failed.append({"function": function, "error": result.get("error", "empty")})
                except Exception as exc:
                    failed.append({"function": function, "error": str(exc)[:200]})
            status(
                f"Condition modules refreshed: {len(refreshed)}, failed: {len(failed)}"
            )
            return {"ok": not failed, "refreshed": refreshed, "failed": failed}
        except Exception as exc:
            return {"ok": False, "error": str(exc)[:200]}

    def _refresh_codegraph(self, status) -> dict:
        """Incrementally refresh the active variant CodeGraph."""
        freshness = self.config.get("identity", {}).get("freshness", {})
        if not any(freshness.get(key) for key in (
            "code_changed", "constants_changed", "identity_changed",
        )):
            return {"ok": True, "skipped": "no_code_drift"}
        try:
            from ai.code_learner import FUNC_KEYWORDS
            from ai.codegraph import CodeGraphBuilder
            from config import get_variable_filter, resolve_codegraph_db

            source_root = Path(self.config["paths"]["source_code"])
            key_files = self.config.get("paths", {}).get("key_source_files", [])
            result = CodeGraphBuilder(
                db_path=resolve_codegraph_db(self.config, self.project_root),
                source_root=source_root,
                key_files=key_files,
                func_keywords=FUNC_KEYWORDS,
                calib_files=[
                    path for path in key_files
                    if any(name in path for name in (
                        "paraDefine", "structDefine", "globalVarDefine",
                    ))
                ],
                source_docs_dir=resolve_source_docs_dir(self.config, self.project_root),
                variable_filter=get_variable_filter(self.config),
            ).build()
            ok = bool(result.success or result.build_type == "skip")
            status(f"CodeGraph refresh: {result.build_type}, success={ok}")
            return {
                "ok": ok,
                "build_type": result.build_type,
                "error": result.error if not ok else "",
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)[:200]}

    # ── Dream Cycle ─────────────────────────────────────────────────────

    def _run_dream_cycle(self, status) -> dict:
        """Execute the 5-phase consolidation with AI.

        Phases:
          0. Study       — 增量学习源码（CodeLearner）
          1. Orient      — 审视各层记忆
          2. Gather      — 收集近期会话
          3. Consolidate — AI 合并、去重、解决冲突
          4. Prune       — 应用变更
        """
        status("Phase 0/4: Study — incremental code learning...")
        # Deterministic index products first: the AI learning pass below reads
        # signal_mapping.json / output_mapping.json / codegraph, so refresh them
        # before learning rather than after (first-principle: code is the only
        # source of truth; LLM summarization runs on top of fresh indices).
        signal_map_delta = self._refresh_signal_indices(status)
        code_delta = self._run_code_learning(status)
        conditions_delta = self._refresh_conditions(status)
        codegraph_delta = self._refresh_codegraph(status)

        status("Phase 1/4: Orient — surveying memories...")
        chain_delta = self._refresh_variable_chains()
        context = self._gather_all_memory_context()

        status("Phase 2/4: Gather — collecting recent sessions...")
        recent = self._gather_recent_sessions()

        status("Phase 3/4: Consolidate — AI merging & resolving conflicts...")
        prompt = self._build_prompt(context, recent, code_delta)
        result = self.router.complex(prompt, system=CONSOLIDATION_PROMPT)
        content = result.get("content", "{}")

        status("Phase 4/4: Prune — applying changes...")
        try:
            start = content.index("{")
            end = content.rindex("}") + 1
            parsed = json.loads(content[start:end])
        except (ValueError, json.JSONDecodeError):
            parsed = {
                "summary": "Dream completed but output parsing failed",
                "raw_output": content[:2000],
            }

        # 附带代码学习结果（供 _record_dream 与调用方使用）
        parsed["_signal_indices"] = signal_map_delta
        parsed["_code_learning"] = code_delta
        parsed["_variable_chains"] = chain_delta
        parsed["_conditions"] = conditions_delta
        parsed["_codegraph"] = codegraph_delta
        return parsed

    def _refresh_signal_indices(self, status) -> dict:
        """Refresh the deterministic signal indices (RX mapping + TX mapping).

        Both products are hash-cached inside signal_mapper, so a no-op when
        the RteComMapping sources did not change. The write-side (Tx) mapping
        is resolved with the same rte_file resolution as the read side so
        variants without the legacy GWM path still produce output_mapping.json.
        """
        try:
            from engines.signal_mapper import (
                extract_output_signal_mapping,
                extract_signal_mapping,
            )
            source_code = (self.config or {}).get("paths", {}).get("source_code", "")
            if not source_code:
                return {"ok": False, "reason": "source_root_missing"}
            rte_file = self._resolve_rte_file()
            source_root = Path(source_code)
            docs_dir = resolve_source_docs_dir(self.config, self.project_root)
            rx = extract_signal_mapping(source_root, docs_dir, rte_file=rte_file)
            tx = extract_output_signal_mapping(source_root, docs_dir, rte_file=rte_file)
            return {
                "ok": True,
                "rx_mapping_count": rx.get("mapping_count", 0),
                "tx_mapping_count": tx.get("mapping_count", 0),
                "rx_source_hash": rx.get("source_hash", ""),
                "tx_source_hash": tx.get("source_hash", ""),
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)[:200]}

    def _resolve_rte_file(self) -> str:
        """Resolve the variant's RteComMapping file (Rx side) for mapping."""
        try:
            key_files = (self.config or {}).get("paths", {}).get("key_source_files") or []
            for rel in key_files:
                leaf = str(rel).replace("\\", "/")
                if "/RteComMapping" in leaf or leaf.startswith("RteComMapping"):
                    return str(rel)
        except Exception:
            pass
        return r"coem\GWM_B26\components\AswIf\ASW_IN\RteComMapping.c"

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
        docs_dir = resolve_source_docs_dir(self.config, self.project_root)
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

        # L6: Code knowledge summary (built by CodeLearner during auto-dream)
        code_dir = self.memory_dir / "code_knowledge"
        if code_dir.exists():
            code_funcs = sorted([p.stem for p in code_dir.glob("*.json")
                                 if p.stem != "learning_state" and p.stem == p.stem.upper()])
            if code_funcs:
                lines = [f"## L6 代码知识 ({len(code_funcs)} 个功能已学)"]
                for func in code_funcs:
                    try:
                        data = json.loads(
                            (code_dir / f"{func}.json").read_text(encoding="utf-8")
                        )
                    except (json.JSONDecodeError, OSError):
                        continue
                    meta = data.get("_meta", {}) or {}
                    learned = meta.get("learned_focuses", [])
                    # 统计每个 focus 下的条目数
                    counts = []
                    for focus in ["alarm_logic", "calculation_chain", "output_chain", "state_machine"]:
                        sec = data.get(focus, {}) or {}
                        total = 0
                        for v in sec.values():
                            if isinstance(v, list):
                                total += len(v)
                            elif isinstance(v, dict):
                                total += len(v)
                        if total:
                            counts.append(f"{focus}={total}")
                    lines.append(f"- **{func}** focuses={learned}  items: {', '.join(counts) or '(empty)'}")
                parts.append("\n".join(lines))

            state_path = code_dir / "learning_state.json"
            if state_path.exists():
                try:
                    ls = json.loads(state_path.read_text(encoding="utf-8"))
                    parts.append(
                        "## L6 代码学习状态\n"
                        f"- warmup_done={ls.get('warmup_done')}  cursor={ls.get('cursor')}  "
                        f"total_pairs={ls.get('total_learned_pairs', 0)}"
                    )
                except (json.JSONDecodeError, OSError):
                    pass

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

    def _build_prompt(self, context: str, recent: str, code_delta: Optional[dict] = None) -> str:
        """Build the consolidation prompt for AI."""
        code_section = ""
        if code_delta and not code_delta.get("skipped"):
            learned = code_delta.get("learned", [])
            skipped = code_delta.get("skipped", [])
            if learned or skipped:
                code_section = (
                    "\n---\n\n## 本次代码学习 Delta\n"
                    f"新学: {len(learned)} 对；跳过: {len(skipped)} 对\n"
                )
                for it in learned[:20]:
                    code_section += (
                        f"- {it.get('func')}/{it.get('focus')}: "
                        f"+{it.get('items_added', 0)} 条 / ~{it.get('items_updated', 0)} 条\n"
                    )

        return f"""请整理以下角雷达分析系统的多层记忆。

{context}

---

{recent}
{code_section}

---

请执行四阶段记忆整理（Orient → Gather → Consolidate → Prune），特别注意:
1. 合并重复的模式条目
2. 解决前后矛盾的记忆（新的覆盖旧的，数据结论优先于推测）
3. 将散落的知识整合到功能知识文件中
4. 更新项目记忆中的固定信息（含“代码知识库学习进度”）
5. 提取用户的使用偏好和分析习惯
6. 如果 L6 代码知识的某些条目能与 L2 功能知识或 L3 模式库相互佐证，在 project.md 中说明

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

        # Phase 15 / 2.2 follow-up: prune stale, low-hit patterns after
        # the dream cycle. Guards: dry_run=False to actually prune;
        # default age/hit thresholds are conservative (90d / 3 hits).
        # If record_pattern_hit has been firing in build_context_for_diagnosis
        # (the other half of this hook), actively-cited patterns survive.
        try:
            decay_summary = self.memory.decay_patterns(
                max_age_days=90, min_hit_count=3, dry_run=False,
            )
            removed = decay_summary.get("removed", [])
            if removed:
                status(
                    f"Decayed {len(removed)} stale pattern(s) "
                    f"(age > 90d, hits < 3)"
                )
        except Exception as exc:
            # Decay is a best-effort optimisation; never fail the dream
            # cycle because of it.
            status(f"[WARN] decay_patterns failed: {exc}")

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
        code_delta = result.get("_code_learning", {}) or {}
        freshness = result.get("_freshness", {}) or {}
        entry = {
            "timestamp": datetime.datetime.now().isoformat(),
            "summary": result.get("summary", "completed"),
            "conflicts": len(result.get("conflicts_found", [])),
            "patterns_added": len(result.get("patterns_to_add", [])),
            "patterns_removed": len(result.get("patterns_to_remove", [])),
        }
        if code_delta and not code_delta.get("skipped"):
            entry["code_pairs_learned"] = code_delta.get("learned_count", 0)
            entry["code_pairs_skipped"] = code_delta.get("skipped_count", 0)
            entry["code_warmup_done"] = code_delta.get("warmup_done", False)
        if freshness:
            entry["freshness_any_changed"] = bool(freshness.get("any_changed"))
            if freshness.get("changed_keys"):
                entry["freshness_changed_keys"] = list(freshness["changed_keys"])
        if result.get("_force_reason"):
            entry["force_reason"] = result["_force_reason"]
        log.append(entry)
        if len(log) > 100:
            log = log[-100:]
        self.log_path.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
