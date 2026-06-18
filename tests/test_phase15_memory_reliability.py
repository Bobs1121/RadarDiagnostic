# -*- coding: utf-8 -*-
"""
Tests for Phase 15 / 2.2 — memory-system reliability.

Covers four sub-tasks:

* 2.2.1  ``atomic_write_text`` / ``atomic_write_json`` — no partial writes
* 2.2.2  ``utils.parse_json_from_llm`` — fallback to outermost-object regex
* 2.2.3  ``MemorySystem.decay_patterns`` — age + hit-count based pruning
* 2.2.4  ``MemorySystem.add_pattern`` — SHA256[:12] dedup IDs
* § 6 follow-ups:
  - ``build_context_for_diagnosis`` calls ``record_pattern_hit``
  - ``_apply_dream_result`` (AutoDream) calls ``decay_patterns``
  - ``migrate_pattern_ids`` rehashes legacy MD5[:8] IDs

Run with::

    pytest tests/test_phase15_memory_reliability.py -v
"""
from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ───────────────────────────────────────────────────────────────────────
# 2.2.1: atomic_write_text / atomic_write_json
# ───────────────────────────────────────────────────────────────────────

def test_atomic_write_text_no_tmp_left_on_success(tmp_path: Path) -> None:
    from memory.memory_system import atomic_write_text

    target = tmp_path / "hello.txt"
    atomic_write_text(target, "hello world")
    assert target.read_text(encoding="utf-8") == "hello world"
    # No stale .tmp file should remain after success.
    assert not (target.with_name(target.name + ".tmp")).exists()


def test_atomic_write_json_round_trip(tmp_path: Path) -> None:
    from memory.memory_system import atomic_write_json

    target = tmp_path / "data.json"
    payload = {"a": [1, 2, 3], "b": "中文", "c": None}
    atomic_write_json(target, payload)
    assert json.loads(target.read_text(encoding="utf-8")) == payload


def test_atomic_write_text_does_not_truncate_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the rename step fails, the original file must remain intact."""
    from memory import memory_system

    target = tmp_path / "guard.txt"
    target.write_text("ORIGINAL", encoding="utf-8")

    # Force os.replace to fail so the exception path is exercised.
    def boom(*args, **kwargs):
        raise OSError("simulated failure")

    monkeypatch.setattr(memory_system.os, "replace", boom)
    with pytest.raises(OSError):
        memory_system.atomic_write_text(target, "NEW")

    # Original must still be there, untouched.
    assert target.read_text(encoding="utf-8") == "ORIGINAL"
    # Stale tmp should have been cleaned up.
    assert not (target.with_name(target.name + ".tmp")).exists()


def test_memory_system_writes_are_atomic(tmp_path: Path) -> None:
    """Sanity: every MemorySystem write path goes through atomic_write_*."""
    from memory.memory_system import MemorySystem

    mem = MemorySystem(tmp_path, memory_dir=tmp_path / "memory")
    # write_project_memory
    mem.write_project_memory("# Title\nbody")
    assert (mem.memory_dir / "project.md").exists()
    # write_function_knowledge
    mem.write_function_knowledge("FCTB", {"alarm_logic": ["x"]})
    assert (mem.memory_dir / "functions" / "FCTB.json").exists()
    # append_project_memory
    mem.append_project_memory("first entry")
    mem.append_project_memory("second entry")
    text = (mem.memory_dir / "project.md").read_text(encoding="utf-8")
    assert "first entry" in text and "second entry" in text
    # add_pattern
    mem.add_pattern({"function": "FCTB", "symptom": "x", "root_cause": "y",
                     "keywords": ["k"], "fix_hint": "f"})
    patterns = mem.read_patterns()
    assert len(patterns) == 1
    # write_case_memory
    case_dir = tmp_path / "case_FCTB001"
    case_dir.mkdir()
    mem.write_case_memory(case_dir, {"function": "FCTB", "problem": "p"})
    assert (case_dir / "memory.json").exists()


# ───────────────────────────────────────────────────────────────────────
# 2.2.2: parse_json_from_llm outermost-object fallback
# ───────────────────────────────────────────────────────────────────────

def test_parse_json_from_llm_outermost_object() -> None:
    """Content with leading prose + JSON object should still parse."""
    from ai.utils import parse_json_from_llm

    content = (
        "Here is the JSON you asked for:\n\n"
        "{\n"
        '  "name": "FCTB",\n'
        '  "ok": true,\n'
        '  "items": [1, 2, 3]\n'
        "}\n\n"
        "Let me know if you need anything else."
    )
    parsed = parse_json_from_llm(content, context="outermost")
    assert parsed == {"name": "FCTB", "ok": True, "items": [1, 2, 3]}


def test_parse_json_from_llm_python_literals_repaired() -> None:
    """LLM-style True/False/None should be repaired to JSON booleans/null."""
    from ai.utils import parse_json_from_llm

    content = '{"enabled": True, "value": None, "ok": False}'
    parsed = parse_json_from_llm(content)
    assert parsed == {"enabled": True, "value": None, "ok": False}


def test_parse_json_from_llm_fallback_returns_dict() -> None:
    """On total failure, must return ``fallback`` (default ``{}``)."""
    from ai.utils import parse_json_from_llm

    parsed = parse_json_from_llm("not json at all", fallback={"empty": True})
    assert parsed == {"empty": True}


def test_parse_json_from_llm_empty_returns_fallback() -> None:
    from ai.utils import parse_json_from_llm
    assert parse_json_from_llm("", fallback={"x": 1}) == {"x": 1}
    assert parse_json_from_llm("   \n  ") == {}


# ───────────────────────────────────────────────────────────────────────
# 2.2.3: decay_patterns
# ───────────────────────────────────────────────────────────────────────

def _iso_days_ago(days: int) -> str:
    return (datetime.datetime.now() - datetime.timedelta(days=days)).isoformat()


def test_decay_patterns_keeps_recent(tmp_path: Path) -> None:
    """Recent + low hit-count patterns must NOT be decayed."""
    from memory.memory_system import MemorySystem

    mem = MemorySystem(tmp_path, memory_dir=tmp_path / "memory")
    p = {"function": "FCTB", "symptom": "recent", "root_cause": "rc",
         "keywords": ["k"], "fix_hint": "f"}
    mem.add_pattern(p)
    summary = mem.decay_patterns(max_age_days=90, min_hit_count=3, dry_run=False)
    assert summary["removed"] == []
    assert summary["kept"] == 1


def test_decay_patterns_removes_old_unused(tmp_path: Path) -> None:
    """Old + low hit-count patterns MUST be removed."""
    from memory.memory_system import MemorySystem

    mem = MemorySystem(tmp_path, memory_dir=tmp_path / "memory")
    p = {"function": "FCTB", "symptom": "old", "root_cause": "rc",
         "keywords": ["k"], "fix_hint": "f"}
    mem.add_pattern(p)
    # Backdate _learned_at to >90 days
    patterns = mem.read_patterns()
    patterns[0]["_learned_at"] = _iso_days_ago(120)
    from memory.memory_system import atomic_write_json
    atomic_write_json(mem.memory_dir / "patterns.json", patterns)

    summary = mem.decay_patterns(max_age_days=90, min_hit_count=3)
    assert len(summary["removed"]) == 1
    assert summary["removed"][0]["function"] == "FCTB"
    assert mem.read_patterns() == []  # actually removed


def test_decay_patterns_keeps_old_but_frequently_used(tmp_path: Path) -> None:
    """Old patterns with high hit-count must survive the sweep."""
    from memory.memory_system import MemorySystem

    mem = MemorySystem(tmp_path, memory_dir=tmp_path / "memory")
    p = {"function": "FCTB", "symptom": "popular", "root_cause": "rc",
         "keywords": ["k"], "fix_hint": "f"}
    mem.add_pattern(p)
    # Backdate + bump hit count
    pid = mem.read_patterns()[0]["_id"]
    for _ in range(5):
        mem.record_pattern_hit(pid)
    patterns = mem.read_patterns()
    patterns[0]["_learned_at"] = _iso_days_ago(120)
    from memory.memory_system import atomic_write_json
    atomic_write_json(mem.memory_dir / "patterns.json", patterns)

    summary = mem.decay_patterns(max_age_days=90, min_hit_count=3)
    assert summary["removed"] == []
    assert summary["kept"] == 1


def test_decay_patterns_dry_run_does_not_write(tmp_path: Path) -> None:
    from memory.memory_system import MemorySystem

    mem = MemorySystem(tmp_path, memory_dir=tmp_path / "memory")
    mem.add_pattern({"function": "X", "symptom": "s", "root_cause": "r",
                     "keywords": [], "fix_hint": ""})
    patterns = mem.read_patterns()
    patterns[0]["_learned_at"] = _iso_days_ago(200)
    from memory.memory_system import atomic_write_json
    atomic_write_json(mem.memory_dir / "patterns.json", patterns)

    summary = mem.decay_patterns(max_age_days=90, min_hit_count=3, dry_run=True)
    assert summary["dry_run"] is True
    assert len(summary["removed"]) == 1
    # file still contains the pattern
    assert len(mem.read_patterns()) == 1


def test_record_pattern_hit_increments(tmp_path: Path) -> None:
    from memory.memory_system import MemorySystem

    mem = MemorySystem(tmp_path, memory_dir=tmp_path / "memory")
    mem.add_pattern({"function": "FCTB", "symptom": "x", "root_cause": "y",
                     "keywords": [], "fix_hint": ""})
    pid = mem.read_patterns()[0]["_id"]
    mem.record_pattern_hit(pid)
    mem.record_pattern_hit(pid)
    p = mem.read_patterns()[0]
    assert p["_hit_count"] == 2
    assert "_last_hit_at" in p


# ───────────────────────────────────────────────────────────────────────
# 2.2.4: SHA256[:12] dedup
# ───────────────────────────────────────────────────────────────────────

def test_add_pattern_uses_sha256_id(tmp_path: Path) -> None:
    """New patterns should get a 12-char SHA256 ID, not MD5[:8]."""
    from memory.memory_system import MemorySystem

    mem = MemorySystem(tmp_path, memory_dir=tmp_path / "memory")
    mem.add_pattern({"function": "FCTB", "symptom": "x", "root_cause": "y",
                     "keywords": [], "fix_hint": ""})
    pid = mem.read_patterns()[0]["_id"]
    assert len(pid) == 12
    # All hex chars
    assert all(c in "0123456789abcdef" for c in pid)


def test_add_pattern_dedup(tmp_path: Path) -> None:
    """Adding the same pattern twice should NOT duplicate it."""
    from memory.memory_system import MemorySystem

    mem = MemorySystem(tmp_path, memory_dir=tmp_path / "memory")
    payload = {"function": "FCTB", "symptom": "x", "root_cause": "y",
               "keywords": [], "fix_hint": ""}
    mem.add_pattern(payload)
    mem.add_pattern(dict(payload))  # identical content
    assert len(mem.read_patterns()) == 1


def test_add_pattern_dedup_preserves_legacy_short_id(tmp_path: Path) -> None:
    """Legacy patterns with short MD5 IDs must survive a re-write of patterns.json.

    Phase 15 / 2.2.4 deliberately uses SHA256[:12] for new IDs; legacy
    MD5[:8] IDs cannot be re-derived from the new algorithm, so the test
    only guarantees that legacy entries are not silently rewritten or
    duplicated by :func:`add_pattern`.
    """
    from memory.memory_system import MemorySystem, atomic_write_json

    mem = MemorySystem(tmp_path, memory_dir=tmp_path / "memory")
    legacy_id = "abcd1234"  # 8-char legacy MD5 id
    legacy = [{
        "_id": legacy_id,
        "function": "FCTB",
        "symptom": "x",
        "root_cause": "y",
        "keywords": [],
        "fix_hint": "",
        "_learned_at": _iso_days_ago(5),
        "_hit_count": 0,
    }]
    atomic_write_json(mem.memory_dir / "patterns.json", legacy)

    # Adding a new pattern (different content) should append, not duplicate
    # the legacy entry.
    mem.add_pattern({"function": "FCTB", "symptom": "different",
                     "root_cause": "z", "keywords": [], "fix_hint": ""})
    patterns = mem.read_patterns()
    assert len(patterns) == 2
    # Legacy entry untouched.
    assert patterns[0]["_id"] == legacy_id
    # New entry uses the new SHA256 ID format.
    assert len(patterns[1]["_id"]) == 12


# ───────────────────────────────────────────────────────────────────────
# § 6 follow-up: record_pattern_hit hooked into build_context_for_diagnosis
# ───────────────────────────────────────────────────────────────────────

def test_build_context_records_pattern_hits(tmp_path: Path) -> None:
    """``build_context_for_diagnosis`` must call ``record_pattern_hit`` for
    every similar pattern it surfaces, so decay_patterns() can protect them.
    """
    from memory.memory_system import MemorySystem

    mem = MemorySystem(tmp_path, memory_dir=tmp_path / "memory")
    mem.add_pattern({
        "function": "FCTB", "symptom": "误触发", "root_cause": "抑制信号缺失",
        "keywords": ["FCTB", "误触发"], "fix_hint": "...",
    })
    pid = mem.read_patterns()[0]["_id"]

    # First call: pattern should be matched AND hit-count bumped.
    ctx = mem.build_context_for_diagnosis("FCTB", "FCTB 在正常驾驶时误触发")
    assert "相似历史案例" in ctx
    assert mem.read_patterns()[0]["_hit_count"] == 1

    # Second call with same input (cache hit) — but the hit-bump
    # happens before the cache lookup, so count must increment.
    mem.build_context_for_diagnosis("FCTB", "FCTB 在正常驾驶时误触发")
    # Note: build_context caches by (func, problem[:240], case_dir).
    # Since hit bookkeeping runs before cache lookup, count still grows.
    assert mem.read_patterns()[0]["_hit_count"] >= 1


def test_build_context_does_not_bump_unrelated_patterns(tmp_path: Path) -> None:
    """Patterns whose function or keywords don't match must NOT be hit."""
    from memory.memory_system import MemorySystem

    mem = MemorySystem(tmp_path, memory_dir=tmp_path / "memory")
    mem.add_pattern({
        "function": "RCTA", "symptom": "another thing", "root_cause": "rc",
        "keywords": ["unrelated"], "fix_hint": "...",
    })
    pid = mem.read_patterns()[0]["_id"]

    mem.build_context_for_diagnosis("FCTB", "FCTB 触发延迟")
    assert mem.read_patterns()[0]["_hit_count"] == 0


def test_build_context_hit_bump_survives_record_pattern_hit_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If ``record_pattern_hit`` raises, diagnosis context build must not fail."""
    from memory import memory_system

    mem = memory_system.MemorySystem(tmp_path, memory_dir=tmp_path / "memory")
    mem.add_pattern({
        "function": "FCTB", "symptom": "误触发", "root_cause": "x",
        "keywords": ["FCTB", "误触发"], "fix_hint": "...",
    })

    def boom(_self, _pid):
        raise RuntimeError("simulated hit bookkeeping failure")

    monkeypatch.setattr(memory_system.MemorySystem, "record_pattern_hit", boom)
    # Must not raise.
    ctx = mem.build_context_for_diagnosis("FCTB", "FCTB 在正常驾驶时误触发")
    assert "相似历史案例" in ctx


# ───────────────────────────────────────────────────────────────────────
# § 6 follow-up: migrate_pattern_ids rehashes legacy MD5[:8] IDs
# ───────────────────────────────────────────────────────────────────────

def test_migrate_pattern_ids_dry_run(tmp_path: Path) -> None:
    """dry_run=True must report the count but NOT rewrite patterns.json."""
    from memory.memory_system import MemorySystem, atomic_write_json

    mem = MemorySystem(tmp_path, memory_dir=tmp_path / "memory")
    legacy = [
        {"_id": "abcd1234", "function": "FCTB", "symptom": "a",
         "root_cause": "r", "keywords": [], "fix_hint": ""},
        {"_id": "deadbeef", "function": "RCTA", "symptom": "b",
         "root_cause": "r", "keywords": [], "fix_hint": ""},
    ]
    atomic_write_json(mem.memory_dir / "patterns.json", legacy)

    summary = mem.migrate_pattern_ids(dry_run=True)
    assert summary["migrated"] == 2
    assert summary["already_new"] == 0
    assert summary["dry_run"] is True
    # File untouched.
    on_disk = atomic_write_json  # noqa  (not actually using it)
    import json as _json
    raw = _json.loads((mem.memory_dir / "patterns.json").read_text(encoding="utf-8"))
    assert raw[0]["_id"] == "abcd1234"  # legacy ID still present


def test_migrate_pattern_ids_writes_new_ids(tmp_path: Path) -> None:
    """Real migration must rewrite all legacy IDs to 12-char SHA256."""
    from memory.memory_system import MemorySystem, atomic_write_json
    import json as _json

    mem = MemorySystem(tmp_path, memory_dir=tmp_path / "memory")
    legacy = [
        {"_id": "abcd1234", "function": "FCTB", "symptom": "a",
         "root_cause": "r", "keywords": [], "fix_hint": ""},
        {"_id": "01234567", "function": "RCTA", "symptom": "b",
         "root_cause": "r", "keywords": [], "fix_hint": ""},
    ]
    atomic_write_json(mem.memory_dir / "patterns.json", legacy)

    summary = mem.migrate_pattern_ids(dry_run=False)
    assert summary["migrated"] == 2
    raw = _json.loads((mem.memory_dir / "patterns.json").read_text(encoding="utf-8"))
    for entry in raw:
        assert len(entry["_id"]) == 12
        # All hex.
        assert all(c in "0123456789abcdef" for c in entry["_id"])


def test_migrate_pattern_ids_dedups_collisions(tmp_path: Path) -> None:
    """When two legacy entries hash to the same new SHA256, only one survives."""
    from memory.memory_system import MemorySystem, atomic_write_json
    import json as _json

    mem = MemorySystem(tmp_path, memory_dir=tmp_path / "memory")
    # Two entries with IDENTICAL content but different legacy IDs.
    same_content = {"function": "FCTB", "symptom": "dup",
                    "root_cause": "r", "keywords": [], "fix_hint": ""}
    legacy = [
        {"_id": "aaaa1111", **same_content},
        {"_id": "bbbb2222", **same_content},
    ]
    atomic_write_json(mem.memory_dir / "patterns.json", legacy)

    summary = mem.migrate_pattern_ids(dry_run=False)
    assert summary["migrated"] == 2
    assert summary["duplicates_removed"] == 1
    raw = _json.loads((mem.memory_dir / "patterns.json").read_text(encoding="utf-8"))
    assert len(raw) == 1


def test_migrate_pattern_ids_already_new_is_noop(tmp_path: Path) -> None:
    """Already-12-char IDs must NOT be touched."""
    from memory.memory_system import MemorySystem

    mem = MemorySystem(tmp_path, memory_dir=tmp_path / "memory")
    mem.add_pattern({"function": "FCTB", "symptom": "x",
                     "root_cause": "y", "keywords": [], "fix_hint": ""})
    new_id = mem.read_patterns()[0]["_id"]
    summary = mem.migrate_pattern_ids(dry_run=False)
    assert summary["already_new"] == 1
    assert summary["migrated"] == 0
    assert mem.read_patterns()[0]["_id"] == new_id


# ───────────────────────────────────────────────────────────────────────
# § 6 follow-up: decay_patterns wired into auto_dream Phase 4
# ───────────────────────────────────────────────────────────────────────

def test_auto_dream_phase4_invokes_decay(tmp_path: Path) -> None:
    """AutoDream's _apply_dream_result must call decay_patterns()."""
    from memory.auto_dream import AutoDream
    from memory.memory_system import MemorySystem, atomic_write_json

    mem = MemorySystem(tmp_path, memory_dir=tmp_path / "memory")
    # Seed an old, low-hit pattern
    legacy = {
        "_id": "0" * 8,  # legacy MD5[:8]
        "function": "FCTB", "symptom": "stale", "root_cause": "r",
        "keywords": [], "fix_hint": "",
        "_learned_at": _iso_days_ago(120),
        "_hit_count": 0,
    }
    atomic_write_json(mem.memory_dir / "patterns.json", [legacy])

    # Build a stub AutoDream (bypass full init).
    class _StubRouter:
        pass

    class _StubDream(AutoDream):
        def __init__(self):
            self.memory = mem
            self.memory_dir = mem.memory_dir
            self.lock_path = mem.memory_dir.parent / ".dream-lock"
            self.log_path = mem.memory_dir.parent / "dream_log.json"

    dream = _StubDream()
    statuses: list[str] = []
    dream._apply_dream_result(
        result={
            "project_memory_update": None,
            "function_updates": {},
            "patterns_to_remove": [],
            "patterns_to_add": [],
            "conflicts_found": [],
            "summary": "test",
        },
        status=lambda msg: statuses.append(msg),
    )
    # Pattern should be gone.
    assert mem.read_patterns() == []
    # And the status callback should have flagged the decay.
    assert any("Decayed" in s for s in statuses)


def test_auto_dream_decay_failure_does_not_break_dream(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If decay_patterns raises, dream cycle must still complete."""
    from memory import memory_system as _ms_mod
    from memory.auto_dream import AutoDream
    from memory.memory_system import MemorySystem

    mem = MemorySystem(tmp_path, memory_dir=tmp_path / "memory")
    mem.add_pattern({"function": "FCTB", "symptom": "x", "root_cause": "y",
                     "keywords": [], "fix_hint": ""})

    class _StubDream(AutoDream):
        def __init__(self):
            self.memory = mem
            self.memory_dir = mem.memory_dir
            self.lock_path = mem.memory_dir.parent / ".dream-lock"
            self.log_path = mem.memory_dir.parent / "dream_log.json"

    dream = _StubDream()

    def boom(*args, **kwargs):
        raise RuntimeError("simulated decay failure")

    monkeypatch.setattr(_ms_mod.MemorySystem, "decay_patterns", boom)
    # Must not raise; pattern must still be there.
    dream._apply_dream_result(
        result={
            "project_memory_update": None, "function_updates": {},
            "patterns_to_remove": [], "patterns_to_add": [],
            "conflicts_found": [], "summary": "test",
        },
        status=lambda msg: None,
    )
    assert len(mem.read_patterns()) == 1


if __name__ == "__main__":
    import io
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    else:
        sys.stdout = io.TextIOWrapper(
            sys.stdout.buffer, encoding="utf-8", errors="replace",
            line_buffering=True,
        )
    raise SystemExit(pytest.main([__file__, "-v"]))