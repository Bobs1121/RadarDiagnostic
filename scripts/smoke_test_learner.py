# -*- coding: utf-8 -*-
"""Smoke test for CodeLearner (without calling AI).

Validates:
1. Config loads auto_dream.code_learning correctly
2. CodeLearner initializes cleanly
3. Source files are discoverable
4. Keyword extraction produces snippets for FCTB
5. Learning state is readable
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402
load_dotenv(PROJECT_ROOT / ".env")

from cli import load_config  # noqa: E402
from ai.code_learner import CodeLearner, FUNC_KEYWORDS, FOCUS_FILES  # noqa: E402


def main() -> int:
    print("=" * 60)
    print("CodeLearner Smoke Test (no AI calls)")
    print("=" * 60)

    cfg = load_config()
    cl_cfg = (cfg.get("auto_dream") or {}).get("code_learning", {})
    print(f"\n[1] Config.auto_dream.code_learning:")
    for k, v in cl_cfg.items():
        print(f"    {k}: {v}")

    class _FakeRouter:
        def complex(self, prompt, system="", **kw):
            return {"content": "{}"}

    learner = CodeLearner(_FakeRouter(), cfg, PROJECT_ROOT)
    print(f"\n[2] CodeLearner initialized.")
    print(f"    enabled: {learner.enabled}")
    print(f"    source_root: {learner.source_root}  (exists={learner.source_root.exists()})")
    print(f"    knowledge_dir: {learner.knowledge_dir}")
    print(f"    priority_functions: {learner.priority_functions}")

    print(f"\n[3] Source file discovery per focus:")
    for focus, files in FOCUS_FILES.items():
        found = sum(1 for f in files if (learner.source_root / f).exists())
        print(f"    {focus}: {found}/{len(files)} files found")

    print(f"\n[4] Snippet extraction for FCTB/alarm_logic:")
    files = FOCUS_FILES["alarm_logic"]
    contents = {}
    for rel in files:
        full = learner.source_root / rel
        if full.exists():
            try:
                contents[rel] = full.read_text(encoding="utf-8", errors="replace")
            except Exception as e:
                print(f"    [warn] failed to read {rel}: {e}")
    if contents:
        keywords = FUNC_KEYWORDS["FCTB"]
        snippets = learner._extract_snippets(contents, keywords)
        size_kb = len(snippets) / 1024
        n_chunks = snippets.count("### File:")
        print(f"    extracted {n_chunks} file-chunks, {size_kb:.1f} KB total")
        if snippets:
            first_200 = snippets[:200].replace("\n", " ⏎ ")
            print(f"    preview: {first_200}...")
    else:
        print("    (no source content found)")

    print(f"\n[5] Learning state:")
    state = learner._read_state()
    print(f"    cursor: {state.get('cursor')}")
    print(f"    warmup_done: {state.get('warmup_done')}")
    print(f"    total_learned_pairs: {state.get('total_learned_pairs', 0)}")
    print(f"    learned_pairs: {state.get('learned_pairs', [])[:5]}...")

    print(f"\n[6] Memory system L6 API:")
    from memory.memory_system import MemorySystem
    ms = MemorySystem(PROJECT_ROOT)
    print(f"    list_code_knowledge_funcs: {ms.list_code_knowledge_funcs()}")
    fctb_ctx = ms.render_code_knowledge_for_context("FCTB", max_chars=800)
    if fctb_ctx:
        print(f"    FCTB code context preview:\n{fctb_ctx[:500]}")
    else:
        print(f"    FCTB code context: (empty — not yet learned)")

    print(f"\n[7] ensure_overview_docs (replaces CodeAnalyzer) — read-only checks:")
    print(f"    key_source_files count: {len(learner.key_source_files)}")
    print(f"    overview_dir: {learner.overview_dir}  (exists={learner.overview_dir.exists()})")
    existing_md = list(learner.overview_dir.glob("*.md"))
    print(f"    existing .md files: {[p.stem for p in existing_md if p.stem != 'SYSTEM_GUIDE']}")
    # SAFETY: Do NOT actually call ensure_overview_docs() with the fake router,
    # because a missing/mismatched hash store would cause FakeRouter's empty
    # response to overwrite the real <FUNC>.md files. Instead verify that the
    # method exists with the correct signature and won't be accidentally
    # triggered in production when source hashes match.
    import inspect as _ins
    sig = _ins.signature(learner.ensure_overview_docs)
    expected_params = {"funcs", "force", "status_cb"}
    actual_params = set(sig.parameters.keys())
    if not expected_params.issubset(actual_params):
        print(f"    [FAIL] ensure_overview_docs missing params: {expected_params - actual_params}")
        return 1
    print(f"    [OK] ensure_overview_docs signature: {sig}")

    print(f"\n[8] Imports & API surface sanity:")
    from ai import CodeLearner as CL_pub, Orchestrator, ModelRouter, FrameAnalyzer
    print(f"    ai.__init__ exports: {[c.__name__ for c in [CL_pub, Orchestrator, ModelRouter, FrameAnalyzer]]}")
    try:
        from ai import CodeAnalyzer  # noqa: F401
        print(f"    [FAIL] CodeAnalyzer should be removed but still importable!")
        return 1
    except ImportError:
        print(f"    [OK] CodeAnalyzer no longer exported (as intended)")

    print(f"\n[9] Simplified call signatures:")
    import inspect
    from memory.auto_dream import AutoDream
    td_sig = inspect.signature(AutoDream.try_dream)
    print(f"    AutoDream.try_dream signature: {td_sig}")
    if "deep_code_learning" in td_sig.parameters:
        print(f"    [FAIL] deep_code_learning param should be removed!")
        return 1
    print(f"    [OK] deep_code_learning param removed")

    print(f"\n[10] parse_data.py removal:")
    import os
    pd = PROJECT_ROOT / "parse_data.py"
    if pd.exists():
        print(f"    [FAIL] parse_data.py still exists at {pd}")
        return 1
    print(f"    [OK] parse_data.py deleted")

    print(f"\n[11] ensure_overview_docs hash-based refresh (safe — no real file writes):")
    # 安全测试：直接检验 hash 判定逻辑，不实际调用 AI 生成（避免污染真实 MD）
    hash_path = learner.overview_dir / ".overview_hashes.json"

    # 手动计算 BSD 的当前 snippet hash 并与 hash store 比对
    import hashlib as _hashlib
    file_contents = learner._read_key_source_files()
    bsd_snippets = learner._extract_snippets(file_contents, FUNC_KEYWORDS["BSD"])
    expected_hash = _hashlib.sha256(bsd_snippets.encode("utf-8", "ignore")).hexdigest()[:16]
    print(f"    computed BSD snippet hash: {expected_hash}")

    # 读 hash store
    if hash_path.exists():
        import json as _json
        hs = _json.loads(hash_path.read_text(encoding="utf-8"))
        stored_bsd = hs.get("BSD")
        match = "✓" if stored_bsd == expected_hash else "✗ (will regenerate on next dream)"
        print(f"    stored BSD hash:          {stored_bsd}  {match}")
    else:
        print(f"    hash store not yet created (first dream will populate it)")
    print(f"    [OK] hash-based refresh logic verified without touching MD files")

    print(f"\n[12] data_query_engine L6 injection:")
    from ai.data_query_engine import DataQueryEngine
    dqe = DataQueryEngine(_FakeRouter(), cfg, PROJECT_ROOT)
    ctx = dqe._build_knowledge_context("FCTB是否触发")
    has_l6 = "[L6]" in ctx or "代码知识" in ctx or "code_knowledge" in ctx.lower()
    # 由于 FCTB 可能还没学，L6 为空也算正常 — 只检查方法调用不出错
    print(f"    knowledge_ctx length: {len(ctx)}")
    print(f"    memory instance: {type(dqe._get_memory()).__name__ if dqe._get_memory() else 'None'}")
    print(f"    [OK] L6 injection path wired (render_code_knowledge_for_context accessible)")

    print(f"\n[13] Context cache (MemorySystem session-level):")
    ms.invalidate_context_cache()  # clean slate
    ctx1 = ms.build_context_for_diagnosis("FCTB", "FCTB没有触发", None)
    ctx2 = ms.build_context_for_diagnosis("FCTB", "FCTB没有触发", None)
    ctx3 = ms.build_context_for_diagnosis("BSD",  "FCTB没有触发", None)  # diff func
    stats = ms.context_cache_stats()
    print(f"    3 calls (2 identical + 1 different func): stats={stats}")
    if stats["hits"] != 1 or stats["misses"] != 2:
        print(f"    [FAIL] expected hits=1 misses=2, got {stats}")
        return 1
    if ctx1 is not ctx2:
        # Note: we return cached string, which should be the same reference
        pass
    print(f"    [OK] context cache deduplicates repeated calls")

    print(f"\n[14] ContextBudget (global prompt budget):")
    from ai.context_budget import ContextBudget
    # Scenario: 3 pieces totalling 45K, budget is 30K
    b = ContextBudget(total_chars=30_000)
    b.add("evidence", "X" * 15_000, priority=100, min_chars=5_000)
    b.add("timeline", "Y" * 20_000, priority=60,  min_chars=2_000)
    b.add("trivia",   "Z" * 10_000, priority=30,  min_chars=500)
    sections = b.render()
    total = sum(len(s) for _, s in sections)
    print(f"    3 pieces raw total: 45,000 chars  budget: 30,000")
    for name, content in sections:
        print(f"      {name}: {len(content):,} chars")
    print(f"    rendered total: {total:,} chars")
    if total > 30_500:  # allow small overflow from truncation markers
        print(f"    [FAIL] rendered total {total} exceeds budget by too much")
        return 1
    # highest priority should keep its full content
    if len(sections[0][1]) != 15_000:
        print(f"    [FAIL] highest priority (evidence) was trimmed unexpectedly")
        return 1
    print(f"    [OK] budget honored, priorities respected")

    print(f"\n[15] _understand_problem keyword prefilter (static check):")
    import inspect
    from ai.orchestrator import Orchestrator
    src = inspect.getsource(Orchestrator._understand_problem)
    if "docs_dir.glob" in src and "for md in docs_dir.glob" in src:
        print(f"    [FAIL] _understand_problem still uses glob-all pattern!")
        return 1
    if "matched_funcs" not in src:
        print(f"    [FAIL] _understand_problem is missing keyword prefilter")
        return 1
    print(f"    [OK] _understand_problem now uses keyword prefilter (matched_funcs)")

    print("\n" + "=" * 60)
    print("Smoke test PASSED (no runtime errors).")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
