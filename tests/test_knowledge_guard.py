from __future__ import annotations

from dataclasses import FrozenInstanceError
import json

import pytest

from core.knowledge_guard import (
    KnowledgeDecision, KnowledgeFreshnessGuard, partition_stable_categories,
    publish_knowledge_categories, runtime_knowledge_decision,
)


_CATEGORIES = (
    "source_docs", "conditions", "code_knowledge", "variable_chains",
    "codegraph", "dbc_knowledge", "requirements", "case_history",
)


def _config(**changes):
    freshness = {
        "code_changed": False,
        "constants_changed": False,
        "dbc_changed": False,
        "requirements_changed": False,
        "identity_changed": False,
        **changes,
    }
    return {"identity": {"freshness": freshness}}


def test_fresh_guard_allows_every_known_category():
    guard = KnowledgeFreshnessGuard(_config())
    assert all(guard.allows(category) for category in _CATEGORIES)


def test_guard_fails_closed_for_missing_unavailable_and_unknown():
    assert not KnowledgeFreshnessGuard({}).allows("source_docs")
    assert not KnowledgeFreshnessGuard(
        {"identity": {"freshness": {"available": False}}}
    ).allows("source_docs")
    assert not KnowledgeFreshnessGuard(_config()).allows("other")


@pytest.mark.parametrize("flag", ["code_changed", "constants_changed"])
def test_code_drift_only_blocks_code_derived_categories(flag):
    guard = KnowledgeFreshnessGuard(_config(**{flag: True}))
    for category in ("source_docs", "conditions", "code_knowledge", "variable_chains", "codegraph"):
        assert not guard.allows(category)
        assert flag in guard.decision(category).reasons
    assert guard.allows("dbc_knowledge")
    assert guard.allows("requirements")
    assert guard.allows("case_history")


def test_dbc_and_requirement_drift_are_category_scoped():
    dbc_guard = KnowledgeFreshnessGuard(_config(dbc_changed=True))
    assert not dbc_guard.allows("dbc_knowledge")
    assert dbc_guard.allows("code_knowledge")
    req_guard = KnowledgeFreshnessGuard(_config(requirements_changed=True))
    assert not req_guard.allows("requirements")
    assert req_guard.allows("source_docs")


def test_identity_change_blocks_all_variant_knowledge():
    guard = KnowledgeFreshnessGuard(_config(identity_changed=True))
    assert all(not guard.allows(category) for category in _CATEGORIES)


def test_decision_is_immutable_and_reason_is_readable():
    decision = KnowledgeFreshnessGuard(_config(code_changed=True)).decision("conditions")
    assert decision == KnowledgeDecision("conditions", False, ("code_changed",))
    assert KnowledgeFreshnessGuard(_config(code_changed=True)).blocked_reason("conditions") == "code_changed"
    with pytest.raises(FrozenInstanceError):
        decision.allowed = True


def test_runtime_guard_preserves_legacy_but_variant_runs_fail_closed():
    assert runtime_knowledge_decision({}, "source_docs").allowed
    decision = runtime_knowledge_decision(
        {"identity": {"variant_id": "gen6/byd_sc6h"}}, "source_docs",
    )
    assert not decision.allowed
    assert decision.reasons == ("freshness_missing",)


def test_memory_blocks_stale_variant_code_knowledge(tmp_path):
    from memory.memory_system import MemorySystem

    memory = MemorySystem(
        tmp_path,
        memory_dir=tmp_path / "variant_memory",
        config={
            "identity": {
                "variant_id": "gen6/byd_sc6h",
                "freshness": {"code_changed": True},
            }
        },
    )
    path = memory.memory_dir / "code_knowledge" / "RCTA.json"
    path.write_text(json.dumps({"stale": True}), encoding="utf-8")
    assert memory.read_code_knowledge("RCTA") == {}


def test_memory_allows_fresh_variant_and_disables_legacy_fallback(tmp_path):
    from memory.memory_system import MemorySystem

    config = {
        "identity": {
            "variant_id": "gen6/byd_sc6h",
            "freshness": {
                "code_changed": False,
                "constants_changed": False,
                "identity_changed": False,
            },
        }
    }
    memory = MemorySystem(tmp_path, memory_dir=tmp_path / "variant_memory", config=config)
    legacy = tmp_path / "memory" / "code_knowledge" / "RCTA.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(json.dumps({"wrong_project": True}), encoding="utf-8")
    assert memory.read_code_knowledge("RCTA") == {}
    current = memory.memory_dir / "code_knowledge" / "RCTA.json"
    current.write_text(json.dumps({"current": True}), encoding="utf-8")
    assert memory.read_code_knowledge("RCTA") == {"current": True}


def test_module_manifest_allows_only_published_current_category(tmp_path):
    state_path = tmp_path / "variant" / "memory" / "freshness_state.json"
    config = _config(code_changed=True)
    config["identity"].update({
        "variant_id": "gen6/byd_sc6h",
        "freshness": {
            **config["identity"]["freshness"],
            "state_path": str(state_path),
            "source_root": "D:/cr60_light",
            "current_commit": "abc123",
            "source_scope_hash": "scope-a",
            "key_source_files_hash": "keys-a",
            "constants_source_hash": "constants-a",
            "config_identity_hash": "identity-a",
        },
    })
    assert not runtime_knowledge_decision(config, "code_knowledge").allowed
    publish_knowledge_categories(config, ["code_knowledge"], producer="test")
    assert runtime_knowledge_decision(config, "code_knowledge").allowed
    assert not runtime_knowledge_decision(config, "conditions").allowed

    publish_knowledge_categories(config, ["conditions:RCTA"], producer="test")
    assert runtime_knowledge_decision(config, "conditions:RCTA").allowed
    assert not runtime_knowledge_decision(config, "conditions:BSD").allowed

    config["identity"]["freshness"]["current_commit"] = "def456"
    assert not runtime_knowledge_decision(config, "code_knowledge").allowed


def test_module_manifests_are_isolated_by_variant_state_path(tmp_path):
    def variant_config(name: str, commit: str):
        config = _config(code_changed=True)
        config["identity"].update({
            "variant_id": name,
            "freshness": {
                **config["identity"]["freshness"],
                "state_path": str(tmp_path / name.replace("/", "_") / "freshness_state.json"),
                "current_commit": commit,
                "config_identity_hash": name,
            },
        })
        return config

    first = variant_config("gen6/byd_sc6h", "a")
    second = variant_config("gen6/gwm_b26", "b")
    publish_knowledge_categories(first, ["source_docs"], producer="test")
    assert runtime_knowledge_decision(first, "source_docs").allowed
    assert not runtime_knowledge_decision(second, "source_docs").allowed


def test_partition_stable_categories_rejects_inputs_changed_during_refresh():
    before = {
        "source_scope_hash": "code-v1",
        "dbc_hash": "dbc-v1",
        "config_identity_hash": "identity-a",
    }
    after = {
        **before,
        "source_scope_hash": "code-v2",
    }

    stable, changed = partition_stable_categories(
        before,
        after,
        ["conditions:RCTA", "dbc_knowledge"],
    )

    assert stable == ["dbc_knowledge"]
    assert changed == ["conditions:RCTA"]


def test_dream_publishes_successful_scopes_and_keeps_failed_scopes_stale():
    from cli import _collect_dream_fresh_categories

    categories = _collect_dream_fresh_categories({
        "_code_learning": {
            "learned": [{"func": "RCTA"}],
            "errors": [{"func": "BSD", "error": "failed"}],
            "constants": {"error": "failed"},
            "overview": {
                "generated": ["RCTA"],
                "skipped": [],
                "failed": [{"func": "BSD", "error": "failed"}],
            },
        },
        "_variable_chains": {"ok": False, "error": "failed"},
        "_conditions": {"refreshed": ["RCTA"], "failed": [{"function": "BSD"}]},
        "_codegraph": {"ok": False, "error": "failed"},
    })
    assert "code_knowledge:RCTA" in categories
    assert "source_docs:RCTA" in categories
    assert "conditions:RCTA" in categories
    assert "code_knowledge:constants" not in categories
    assert "variable_chains" not in categories
    assert "codegraph" not in categories
    assert all("BSD" not in category for category in categories)
