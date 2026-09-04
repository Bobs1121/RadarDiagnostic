# -*- coding: utf-8 -*-
"""
radarAnalyze core module.

Identity hierarchy:
    core/identity.py     — PlatformFamily, Codebase, Variant, PackageProfile, Snapshot
Materials system:
    core/materials.py    — MaterialRegistry, RegisteredMaterial, StructuredRequirementSet
Diagnosis artifacts:
    core/diagnosis_bundle.py — DiagnosisBundle, RootCausePattern, FixPlaybook, KnowledgeStore
Simulation/build models:
    core/models.py       — SimConfig, SimResult, BuildOptions, etc.
"""

# Identity
from core.identity import (
    PlatformFamily,
    Codebase,
    Variant,
    VariantScope,
    DBCSet,
    PackageProfile,
    BuildFlags,
    PatchSet,
    Snapshot,
    file_sha256,
    hash_files,
    hash_directory,
)

# Materials
from core.materials import (
    MaterialType,
    MaterialCategory,
    RegisteredMaterial,
    MaterialRegistry,
    RequirementSpec,
    StructuredRequirementSet,
)

# Diagnosis
from core.diagnosis_bundle import (
    Evidence,
    CodeLocation,
    ConclusionLevel,
    ChangeProposal,
    DiagnosisBundle,
    RootCausePattern,
    FixPlaybook,
    KnowledgeStore,
)

__all__ = [
    # Identity
    "PlatformFamily", "Codebase", "Variant", "VariantScope", "DBCSet",
    "PackageProfile", "BuildFlags", "PatchSet", "Snapshot",
    "file_sha256", "hash_files", "hash_directory",
    # Materials
    "MaterialType", "MaterialCategory",
    "RegisteredMaterial", "MaterialRegistry",
    "RequirementSpec", "StructuredRequirementSet",
    # Diagnosis
    "Evidence", "CodeLocation", "ConclusionLevel", "ChangeProposal",
    "DiagnosisBundle", "RootCausePattern", "FixPlaybook", "KnowledgeStore",
]
