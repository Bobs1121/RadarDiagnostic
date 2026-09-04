# -*- coding: utf-8 -*-
"""
Offline unit tests for the M5 semantic-memory layer.

These tests run FULLY offline and pass WITHOUT ``lancedb`` installed: they
exercise the pure-Python cosine *fallback* backend. Where deterministic
ranking matters, a tiny controlled embedder is injected so ordering does not
depend on hashing collisions.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import memory.semantic_memory as sm  # noqa: E402
from memory.semantic_memory import SemanticMemory  # noqa: E402


# ── A tiny, fully deterministic embedder for stable ranking ─────────────
#
# 4 axes keyed to keywords. Records/queries containing a keyword get weight on
# that axis, so cosine ordering is exactly predictable.
_AXES = ("brake", "jitter", "speed", "distance")


def tiny_embedder(text: str) -> list[float]:
    low = text.lower()
    return [float(low.count(axis)) for axis in _AXES]


@pytest.fixture(autouse=True)
def _force_fallback(monkeypatch):
    """Force the fallback backend regardless of the local environment."""
    monkeypatch.setattr(sm, "_HAS_LANCEDB", False)


def _make(tmp_path: Path, embedder=tiny_embedder, dim: int = 4) -> SemanticMemory:
    return SemanticMemory(store_dir=tmp_path, embedder=embedder, dim=dim)


# ── Tests ───────────────────────────────────────────────────────────────

def test_add_then_search_returns_record_with_positive_score(tmp_path):
    mem = _make(tmp_path)
    rid = mem.add(
        symptom="brake hold delay",
        signal="AEBBAActv",
        conclusion="brake timer priority",
    )
    results = mem.search("brake release", k=5)

    assert results, "search must return the added record"
    assert results[0]["id"] == rid
    assert results[0]["score"] > 0
    assert results[0]["symptom"] == "brake hold delay"


def test_semantically_close_query_ranks_right_record_first(tmp_path):
    mem = _make(tmp_path)
    brake_id = mem.add(symptom="brake hold delay", conclusion="brake timer")
    jitter_id = mem.add(symptom="target jitter speed threshold")

    brake_hits = mem.search("brake release", k=5)
    assert brake_hits[0]["id"] == brake_id
    assert brake_hits[0]["score"] > 0

    jitter_hits = mem.search("jitter speed", k=5)
    assert jitter_hits[0]["id"] == jitter_id
    # The unrelated record must rank strictly below the matching one.
    assert jitter_hits[0]["score"] > jitter_hits[-1]["score"]


def test_default_hashing_embedder_recalls_exact_text(tmp_path):
    # No injected embedder -> deterministic feature-hashing default (dim=256).
    mem = SemanticMemory(store_dir=tmp_path)
    assert mem.backend == "fallback"
    rid = mem.add(symptom="FCTB short duration jitter", signal="fctb_obj_flag")
    hits = mem.search("FCTB short duration jitter\nfctb_obj_flag", k=3)
    assert hits[0]["id"] == rid
    assert hits[0]["score"] > 0.99  # identical text -> cosine ~1.0


def test_dedup_same_content_keeps_single_record(tmp_path):
    mem = _make(tmp_path)
    first = mem.add(symptom="brake hold delay", conclusion="brake timer")
    second = mem.add(symptom="brake hold delay", conclusion="brake timer")
    assert first == second
    assert mem.count() == 1


def test_backend_is_fallback_without_lancedb(tmp_path):
    mem = _make(tmp_path)
    assert mem.backend == "fallback"


def test_persistence_across_instances(tmp_path):
    mem = _make(tmp_path)
    id_a = mem.add(symptom="brake hold delay", conclusion="brake timer")
    id_b = mem.add(symptom="target jitter speed")
    assert mem.count() == 2

    # A brand-new instance on the same directory must see the same records.
    reopened = _make(tmp_path)
    assert reopened.count() == 2
    hits = reopened.search("brake release", k=5)
    assert hits[0]["id"] == id_a
    assert {id_a, id_b} == {h["id"] for h in reopened.search("brake jitter speed", k=5)}


def test_empty_store_search_returns_empty(tmp_path):
    mem = _make(tmp_path)
    assert mem.count() == 0
    assert mem.search("anything at all", k=5) == []


def test_clear_empties_the_store(tmp_path):
    mem = _make(tmp_path)
    mem.add(symptom="brake hold delay")
    mem.add(symptom="target jitter speed")
    assert mem.count() == 2

    mem.clear()
    assert mem.count() == 0
    assert mem.search("brake", k=5) == []

    # Clear must also survive a reopen (persisted empty).
    reopened = _make(tmp_path)
    assert reopened.count() == 0


def test_min_score_filters_low_similarity(tmp_path):
    mem = _make(tmp_path)
    mem.add(symptom="brake hold delay", conclusion="brake timer")
    mem.add(symptom="target jitter speed")
    # "brake" is orthogonal to the jitter/speed record -> that record scores 0
    # and is filtered out by a positive threshold.
    hits = mem.search("brake", k=5, min_score=0.5)
    assert len(hits) == 1
    assert hits[0]["symptom"] == "brake hold delay"


def test_equal_scores_are_ordered_by_stable_id(tmp_path):
    mem = _make(tmp_path)
    ids = [
        mem.add(symptom="brake case z", conclusion="same vector"),
        mem.add(symptom="brake case a", conclusion="same vector"),
    ]

    hits = mem.search("brake", k=5)

    assert [h["id"] for h in hits] == sorted(ids)


def test_for_variant_uses_workspace_isolated_lancedb_path(tmp_path):
    class VariantLike:
        variant_id = "coem/GWM_B26"

    mem = SemanticMemory.for_variant(
        tmp_path,
        VariantLike(),
        embedder=tiny_embedder,
        dim=4,
    )

    expected = tmp_path / ".workspaces" / "coem_GWM_B26" / "memory" / "lancedb"
    assert mem.store_dir == expected
    assert mem.backend == "fallback"
    assert expected.exists()
