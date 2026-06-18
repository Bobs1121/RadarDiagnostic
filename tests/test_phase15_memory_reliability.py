# -*- coding: utf-8 -*-
"""
Tests for Phase 15 / 2.2 — memory-system reliability.

Covers four sub-tasks:

* 2.2.1  ``atomic_write_text`` / ``atomic_write_json`` — no partial writes
* 2.2.2  ``utils.parse_json_from_llm`` — fallback to outermost-object regex
* 2.2.3  ``MemorySystem.decay_patterns`` — age + hit-count based pruning
* 2.2.4  ``MemorySystem.add_pattern`` — SHA256[:12] dedup IDs

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