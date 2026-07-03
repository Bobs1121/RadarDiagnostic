# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from core.materials import (
    MaterialCategory,
    MaterialRegistry,
    RequirementSpec,
    StructuredRequirementSet,
    render_material_summary,
)


VARIANT_ID = "gen6/gwm_b26"


def test_render_material_summary_empty_registry_is_prompt_quiet(tmp_path: Path) -> None:
    summary = render_material_summary(tmp_path, VARIANT_ID)

    assert summary["variant_id"] == VARIANT_ID
    assert summary["material_count"] == 0
    assert summary["authoritative_count"] == 0
    assert summary["requirement_count"] == 0
    assert summary["prompt_text"] == ""


def test_render_material_summary_with_materials_and_requirements(
    tmp_path: Path,
) -> None:
    material_file = tmp_path / "fcta_requirements.md"
    material_file.write_text("# FCTA\nBrake request shall trigger.", encoding="utf-8")
    registry = MaterialRegistry.for_variant(tmp_path, VARIANT_ID)
    mat = registry.register(
        material_file,
        VARIANT_ID,
        version="2.0",
        category=MaterialCategory.AUTHORITATIVE.value,
        tags=["fcta", "brake"],
        title="FCTA Requirements",
    )

    req_set = StructuredRequirementSet.for_variant(tmp_path, VARIANT_ID)
    req_set.add(
        RequirementSpec(
            requirement_id="REQ-FCTA-001",
            material_id=mat.material_id,
            variant_id=VARIANT_ID,
            scope="FCTA",
            statement="FCTA shall issue brake request when TTC is below threshold.",
            linked_signals=["RSDS_AEBReq", "FCTA_TTC"],
            linked_functions=["FCTA"],
            priority="critical",
        )
    )
    safe_id = VARIANT_ID.replace("/", "_").replace(" ", "_").lower()
    req_set.save(tmp_path / "materials" / safe_id / "requirements.json")

    summary = render_material_summary(tmp_path, VARIANT_ID)

    assert summary["material_count"] == 1
    assert summary["authoritative_count"] == 1
    assert summary["requirement_count"] == 1
    assert summary["critical_requirement_count"] == 1
    assert summary["material_ids"] == [mat.material_id]
    assert summary["requirement_ids"] == ["REQ-FCTA-001"]
    assert "## ★★ 权威材料摘要(Material Registry) ★★" in summary["prompt_text"]
    assert "`REQ-FCTA-001` [critical] FCTA" in summary["prompt_text"]
    assert "signals=RSDS_AEBReq,FCTA_TTC" in summary["prompt_text"]


def test_render_material_summary_respects_max_chars(tmp_path: Path) -> None:
    material_file = tmp_path / "long.md"
    material_file.write_text("content", encoding="utf-8")
    registry = MaterialRegistry.for_variant(tmp_path, VARIANT_ID)
    registry.register(material_file, VARIANT_ID, title="Long Material")

    req_set = StructuredRequirementSet.for_variant(tmp_path, VARIANT_ID)
    req_set.add(
        RequirementSpec(
            requirement_id="REQ-LONG",
            material_id="mat-test",
            variant_id=VARIANT_ID,
            scope="FCTA",
            statement="x" * 500,
            priority="high",
        )
    )
    safe_id = VARIANT_ID.replace("/", "_").replace(" ", "_").lower()
    req_set.save(tmp_path / "materials" / safe_id / "requirements.json")

    summary = render_material_summary(tmp_path, VARIANT_ID, max_chars=220)

    assert len(summary["prompt_text"]) <= 220
    assert summary["prompt_text"].endswith("... [truncated]")
