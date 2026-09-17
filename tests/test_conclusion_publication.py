from __future__ import annotations

from core.diagnosis_bundle import CodeLocation, ConclusionLevel, DiagnosisBundle, Evidence


def _bundle() -> DiagnosisBundle:
    bundle = DiagnosisBundle.for_case(
        project_root=None,  # factory keeps the identity fields only
        case_id="CASE-CONCLUSION",
        variant_id="gen6/test",
        problem="test",
        expected="expected",
    )
    bundle.add_evidence(Evidence(evidence_id="ev-1", source="recorded_raw", description="observed"))
    bundle.add_evidence(Evidence(evidence_id="ev-2", source="runtime_with_frame", description="runtime"))
    bundle.code_localization.append(CodeLocation(file_path="adas.c", line_start=10))
    bundle.root_cause = "verified cause"
    return bundle


def test_static_evidence_and_source_path_cannot_confirm_root_cause():
    bundle = _bundle()
    assert bundle.upgrade_to_confirmed() is False
    assert bundle.conclusion_level == ConclusionLevel.EVIDENCE_ONLY
    bundle.upgrade_to_candidate()
    assert bundle.conclusion_level == ConclusionLevel.CANDIDATE
    assert "confirmation_gate" not in bundle.metadata


def test_confirmation_requires_identity_and_explicit_evidence_reference():
    bundle = _bundle()
    assert bundle.upgrade_to_confirmed({"runtime_verified": True}) is False
    assert bundle.conclusion_level == ConclusionLevel.EVIDENCE_ONLY
    assert bundle.upgrade_to_confirmed(
        {
            "runtime_verified": True,
            "identity_verified": True,
            "evidence_refs": ["runtime-session-1"],
        }
    ) is True
    assert bundle.conclusion_level == ConclusionLevel.CONFIRMED
    assert bundle.to_dict().get("gating_violations") is None


def test_identity_conflict_blocks_confirmation():
    bundle = _bundle()
    assert bundle.upgrade_to_confirmed(
        {
            "replay_verified": True,
            "identity_verified": True,
            "identity_conflict": True,
            "evidence_refs": ["replay-1"],
        }
    ) is False
    assert bundle.conclusion_level == ConclusionLevel.EVIDENCE_ONLY

