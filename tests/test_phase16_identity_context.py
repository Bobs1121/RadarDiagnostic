# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from config import load_config
from ai.orchestrator import Orchestrator, _resolve_identity_context


def test_identity_context_resolves_default_variant(tmp_path: Path) -> None:
    config = load_config()

    ctx = _resolve_identity_context(config, tmp_path)

    assert ctx.variant_id == "gen6/gwm_b26"
    assert ctx.project_key == "gwm_b26"
    assert ctx.package_profile_id == "gen6/gwm_b26/default"
    assert ctx.display_name
    assert ctx.source_docs_dir == tmp_path / "source_docs" / "gen6_gwm_b26"
    assert ctx.memory_dir == tmp_path / "memory" / "projects" / "gen6_gwm_b26"


def test_identity_context_preserves_legacy_project_mapping(tmp_path: Path) -> None:
    config = load_config()
    config["identity"] = {"project_key": "gwm_b26", "snapshot_id": "snap-test"}
    config.pop("default_variant", None)

    ctx = _resolve_identity_context(config, tmp_path)

    assert ctx.variant_id == "gen6/gwm_b26"
    assert ctx.project_key == "gwm_b26"
    assert ctx.snapshot_id == "snap-test"


def test_orchestrator_report_uses_identity_context(
    tmp_path: Path, monkeypatch
) -> None:
    config = load_config()
    config["identity"] = {
        "variant_id": "gen6/gwm_b26",
        "project_key": "gwm_b26",
        "package_profile_id": "gen6/gwm_b26/default",
        "snapshot_id": "snap-test",
    }
    monkeypatch.setattr(Orchestrator, "_init_signal_maps", lambda self: None)

    orchestrator = Orchestrator(config, tmp_path)
    case_dir = tmp_path / "case"
    case_dir.mkdir()

    report_path = orchestrator._save_report(
        case_dir=case_dir,
        diagnosis="diagnosis body",
        problem="problem",
        expected="expected",
        func_name="FCTA",
        bag_meta={},
        blf_meta={},
        windows=[],
        snapshot_id=orchestrator.identity.snapshot_id,
    )

    report = Path(report_path).read_text(encoding="utf-8")
    assert "| Variant | `gen6/gwm_b26` |" in report
    assert "| Package | `gen6/gwm_b26/default` |" in report
    assert "| Project | `gwm_b26` |" in report
    assert "| 快照ID | `snap-test` |" in report
