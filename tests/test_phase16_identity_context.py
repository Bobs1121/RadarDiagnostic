# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from config import load_config
from ai.orchestrator import (
    Orchestrator,
    _normalize_report_section_headings,
    _resolve_identity_context,
)


def test_identity_context_resolves_default_variant(tmp_path: Path) -> None:
    from config import resolve_variant_id, get_variant

    config = load_config()

    ctx = _resolve_identity_context(config, tmp_path)

    # The resolved default variant comes from config (default_variant /
    # default_project / project_intake.default), which may differ between
    # environments (e.g. config.local.yaml). Assert consistency with the
    # config's own resolution instead of hardcoding a value.
    expected_default = resolve_variant_id(config, None)
    assert ctx.variant_id == expected_default
    assert ctx.display_name
    # Every resolved variant must exist and be backed by a codebase.
    variant, _codebase, _platform = get_variant(config, ctx.variant_id)
    assert variant is not None
    assert _codebase is not None
    # IdentityContext scopes artifacts under the V3 workspace sandbox.
    safe = ctx.variant_id.replace("/", "_")
    assert ctx.source_docs_dir == tmp_path / ".workspaces" / safe / "source_docs"
    assert ctx.memory_dir == tmp_path / ".workspaces" / safe / "memory"


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


def test_normalize_report_section_headings_promotes_known_bold_labels() -> None:
    diagnosis = """**根因**
根因内容。

### 已有标题
保留不变。

**关键证据链(结构化)**
1. **信号**: test_sig | **时间**: t=1

**置信度: 92/100**
段落里的 **粗体强调** 不应变化。
"""

    normalized = _normalize_report_section_headings(diagnosis)

    assert "### 根因" in normalized
    assert "### 已有标题" in normalized
    assert "### 关键证据链(结构化)" in normalized
    assert "### 置信度: 92/100" in normalized
    assert "1. **信号**: test_sig | **时间**: t=1" in normalized
    assert "段落里的 **粗体强调** 不应变化。" in normalized
    assert "**根因**" not in normalized
    assert "**置信度: 92/100**" not in normalized


def test_orchestrator_save_report_normalizes_section_headings(
    tmp_path: Path, monkeypatch
) -> None:
    config = load_config()
    monkeypatch.setattr(Orchestrator, "_init_signal_maps", lambda self: None)

    orchestrator = Orchestrator(config, tmp_path)
    case_dir = tmp_path / "case"
    case_dir.mkdir()

    report_path = orchestrator._save_report(
        case_dir=case_dir,
        diagnosis="""**根因**
根因内容。

**修复建议**
1. 调整阈值

1. **信号**: demo_sig | **时间**: t=2
""",
        problem="problem",
        expected="expected",
        func_name="FCTA",
        bag_meta={},
        blf_meta={},
        windows=[],
    )

    report = Path(report_path).read_text(encoding="utf-8")
    assert "### 根因" in report
    assert "### 修复建议" in report
    assert "1. **信号**: demo_sig | **时间**: t=2" in report
