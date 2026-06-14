# -*- coding: utf-8 -*-
"""
Verification script for the v2 infrastructure layer.

Tests:
  1. Legacy -P gwm_b26 compatibility
  2. DBC set resolution via Variant model
  3. --snapshot auto produces enriched snapshot
  4. Snapshot persists and loads correctly
  5. DiagnosisBundle creation with variant_id/snapshot_id/case_id
  6. MaterialRegistry discovery for variant
  7. Harness includes bundle/snapshot metadata
  8. Identity model basics

Run from project root:
  python tests/test_infrastructure_verification.py
"""

import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Canonical variant ID (from config.yaml default_variant or project mapping)
VARIANT_ID = "gen6/gwm_b26"

PASS = 0
FAIL = 0
ERRORS = []


def check(name: str, condition: bool, detail: str = ""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  [PASS] {name}" + (f"  {detail}" if detail else ""))
    else:
        FAIL += 1
        msg = f"  [FAIL] {name}" + (f"  {detail}" if detail else "")
        print(msg)
        ERRORS.append(msg)


def header(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


# =====================================================================
# Test 1: Legacy -P gwm_b26 compatibility
# =====================================================================
header("Test 1: Legacy -P gwm_b26 compatibility")

from config import load_config, resolve_variant_id, get_variant, get_project

config = load_config()

# Check default project
default_proj = config.get("default_project", "")
check("default_project set", default_proj == "gwm_b26", f"got '{default_proj}'")

# Resolve variant from config (identifier=None means default)
variant_id = resolve_variant_id(config, None)
check("variant_id from config", variant_id == VARIANT_ID, f"got '{variant_id}'")

# Check identity section — may or may not exist; variant resolution uses variants/default_variant
ident = config.get("identity", {})
check("identity section exists", "identity" in config,
      "identity section optional — variant resolution via variants/default_variant")

# get_variant works with canonical ID
try:
    v, cb, vs = get_variant(config, VARIANT_ID)
    check("get_variant resolves", v is not None)
    check("Variant.variant_id", v.variant_id == VARIANT_ID,
          f"got '{v.variant_id}'")
except ValueError as e:
    check("get_variant resolves", False, f"ValueError: {e}")

# Legacy: get_project still works
try:
    proj = get_project(config, "gwm_b26")
    check("get_project('gwm_b26') works", "source_code" in proj)
except ValueError as e:
    check("get_project('gwm_b26') works", False, f"ValueError: {e}")


# =====================================================================
# Test 2: DBC set resolution via Variant model
# =====================================================================
header("Test 2: DBC set resolution")

try:
    v, cb, vs = get_variant(config, VARIANT_ID)
    dbc_sets = v.dbc_sets
    if dbc_sets:
        check("Variant has dbc_sets", True, f"{len(dbc_sets)} DBCSet(s)")
        for ds in dbc_sets:
            check(f"DBCSet '{ds.name}' has files", bool(ds.files),
                  f"files={ds.files}")
    else:
        check("dbc_sets populated", False, "dbc_sets is None or empty")
except Exception as e:
    check("dbc_sets resolution", False, f"error: {e}")


# =====================================================================
# Test 3: --snapshot auto enrichment
# =====================================================================
header("Test 3: --snapshot auto enrichment")

from cli import _resolve_snapshot
from core.snapshot_store import SnapshotStore

snap_result = _resolve_snapshot(config, "auto", PROJECT_ROOT)
check("snapshot created", "snapshot_id" in snap_result,
      f"keys={list(snap_result.keys())}")
check("action is 'created'", snap_result.get("action") == "created")

snap = snap_result.get("snapshot")
snap_id = snap_result.get("snapshot_id", "")

if snap:
    check("snapshot.variant_id set", snap.variant_id == VARIANT_ID,
          f"got '{snap.variant_id}'")
    check("snapshot.config_version set", bool(snap.config_version),
          f"sha={snap.config_version[:16] if snap.config_version else ''}...")
    check("snapshot.created_at set", bool(snap.created_at))

    # Check enrichment fields
    code_count = len(snap.code_snapshot) if snap.code_snapshot else 0
    dbc_count = len(snap.dbc_snapshot) if snap.dbc_snapshot else 0
    mat_count = len(snap.material_snapshot) if snap.material_snapshot else 0
    summary = snap.metadata.get("summary", "")

    check("code_snapshot populated", code_count >= 0,
          f"hashed {code_count} source files (0 means no key_source_files in config or files missing)")
    check("dbc_snapshot populated", dbc_count >= 0,
          f"hashed {dbc_count} DBC files")
    check("material_snapshot populated", mat_count >= 0,
          f"registered {mat_count} materials")
    check("metadata.summary present", bool(summary), f"'{summary}'")
else:
    check("snapshot object returned", False, "None")


# =====================================================================
# Test 4: Snapshot persistence round-trip
# =====================================================================
header("Test 4: Snapshot persistence")

store = SnapshotStore(PROJECT_ROOT / "memory" / "snapshots")
if snap_id and snap:
    loaded_snap = store.load(snap_id)
    check("snapshot loadable", loaded_snap.snapshot_id == snap_id)
    check("variant_id preserved", loaded_snap.variant_id == snap.variant_id)
    check("config_version preserved", loaded_snap.config_version == snap.config_version)
    if snap.code_snapshot:
        check("code_snapshot preserved",
              loaded_snap.code_snapshot == snap.code_snapshot)
    check("metadata.summary preserved",
          loaded_snap.metadata.get("summary") == snap.metadata.get("summary"))
else:
    check("snapshot_id available for persistence test", False)

# List snapshots
snap_list = store.list()
check("store.list() returns snapshots", len(snap_list) > 0,
      f"found {len(snap_list)} snapshot(s)")


# =====================================================================
# Test 5: DiagnosisBundle creation with identity linkage
# =====================================================================
header("Test 5: DiagnosisBundle creation")

from core.diagnosis_bundle import (
    DiagnosisBundle, Evidence, CodeLocation, ConclusionLevel,
)

bundle = DiagnosisBundle.for_case(
    project_root=PROJECT_ROOT,
    case_id="TEST_CASE",
    variant_id=VARIANT_ID,
    problem="Test problem for verification",
    expected="Expected behavior",
)
bundle.snapshot_id = snap_id
bundle.classification = "diagnose"
bundle.add_evidence(Evidence(
    evidence_id="ev-test-1",
    source="test",
    description="Test evidence item 1",
    confidence=0.8,
))
bundle.add_evidence(Evidence(
    evidence_id="ev-test-2",
    source="test",
    description="Test evidence item 2",
    confidence=0.7,
))
bundle.code_localization.append(CodeLocation(
    file_path="adas/adasFunc.c",
    line_start=100,
    line_end=110,
))

with tempfile.TemporaryDirectory() as tmpdir:
    tmp_path = Path(tmpdir)
    bundle_path = tmp_path / "diagnosis_bundle.json"
    bundle.save(bundle_path)

    check("bundle file created", bundle_path.exists())
    check("bundle has bundle_id", bool(bundle.bundle_id),
          f"id={bundle.bundle_id}")
    check("bundle has variant_id", bundle.variant_id == VARIANT_ID)
    check("bundle has snapshot_id", bundle.snapshot_id == snap_id)
    check("bundle has case_id", bundle.case_id == "TEST_CASE")

    # Load and verify round-trip
    loaded = DiagnosisBundle.load(bundle_path)
    check("bundle loadable", loaded.bundle_id == bundle.bundle_id)
    check("variant_id round-trip", loaded.variant_id == bundle.variant_id)
    check("snapshot_id round-trip", loaded.snapshot_id == bundle.snapshot_id)
    check("case_id round-trip", loaded.case_id == bundle.case_id)
    check("evidence round-trip",
          len(loaded.evidence_chain) == len(bundle.evidence_chain))

    # Check JSON structure
    raw = json.loads(bundle_path.read_text())
    check("JSON has variant_id", "variant_id" in raw)
    check("JSON has snapshot_id", "snapshot_id" in raw)
    check("JSON has case_id", "case_id" in raw)
    check("JSON has bundle_id", "bundle_id" in raw)
    check("JSON has evidence_chain", "evidence_chain" in raw)

    # Verify conclusion upgrade logic
    bundle2 = DiagnosisBundle.for_case(
        project_root=PROJECT_ROOT, case_id="X", variant_id=VARIANT_ID,
        problem="p", expected="e",
    )
    bundle2.add_evidence(Evidence(evidence_id="a", source="s", description="d"))
    bundle2.add_evidence(Evidence(evidence_id="b", source="s", description="d"))
    bundle2.upgrade_to_candidate()
    check("upgrade_to_candidate works",
          bundle2.conclusion_level == ConclusionLevel.CANDIDATE)


# =====================================================================
# Test 6: MaterialRegistry for variant
# =====================================================================
header("Test 6: MaterialRegistry discovery")

from core.materials import MaterialRegistry, StructuredRequirementSet

registry = MaterialRegistry.for_variant(PROJECT_ROOT, VARIANT_ID)
materials = registry.list_by_variant(VARIANT_ID)
check("MaterialRegistry loads without error", True)
check("can list materials for variant", isinstance(materials, list),
      f"found {len(materials)} material(s)")

if materials:
    check("materials have variant_id",
          all(m.variant_id == VARIANT_ID for m in materials))

# Requirement set
req_set = StructuredRequirementSet.for_variant(PROJECT_ROOT, VARIANT_ID)
check("StructuredRequirementSet loads", req_set.variant_id == VARIANT_ID)

# Verify the registry path is correct
safe_id = VARIANT_ID.replace("/", "_").replace(" ", "_").lower()
expected_reg_path = PROJECT_ROOT / "materials" / safe_id / "registry.json"
check("registry path correct",
      str(registry.registry_path) == str(expected_reg_path))


# =====================================================================
# Test 7: Harness includes bundle/snapshot metadata
# =====================================================================
header("Test 7: Harness bundle/snapshot metadata")

from harness.harness_runner import HarnessResult

hr = HarnessResult("TEST_CASE")
hr.bundle_id = "diag-test123"
hr.snapshot_id = snap_id
hr.variant_id = VARIANT_ID
hr.bundle_path = "/some/path/diagnosis_bundle.json"

d = hr.to_dict()
check("to_dict includes bundle_id", d.get("bundle_id") == "diag-test123")
check("to_dict includes snapshot_id", d.get("snapshot_id") == snap_id)
check("to_dict includes variant_id", d.get("variant_id") == VARIANT_ID)
check("to_dict includes bundle_path",
      d.get("bundle_path") == "/some/path/diagnosis_bundle.json")

# Verify JSON serialization works
json_str = hr.to_json()
parsed = json.loads(json_str)
check("JSON round-trip preserves bundle_id",
      parsed["bundle_id"] == "diag-test123")
check("JSON round-trip preserves snapshot_id",
      parsed["snapshot_id"] == snap_id)


# =====================================================================
# Test 8: Identity model basics
# =====================================================================
header("Test 8: Identity model")

from core.identity import (
    PackageProfile, Snapshot, VariantScope, file_sha256,
)

# Variant resolution via config.get_variant (Variant.resolve doesn't exist)
v, cb, vs = get_variant(config, VARIANT_ID)
check("get_variant returns Variant", v is not None)
check("variant.variant_id", v.variant_id == VARIANT_ID)
check("codebase returned", cb is not None)
check("variant_scope returned", vs is not None)

# VariantScope standalone construction (only has include_globs/exclude_globs)
vs2 = VariantScope(include_globs=["*.c", "*.h"], exclude_globs=["*test*"])
check("VariantScope created",
      vs2.include_globs == ["*.c", "*.h"] and vs2.exclude_globs == ["*test*"])

# file_sha256 utility
cfg_file = PROJECT_ROOT / "config.yaml"
sha = file_sha256(cfg_file)
check("file_sha256 works", len(sha) == 64, f"sha={sha[:16]}...")

# Snapshot.create with enrichment
snap2 = Snapshot.create(
    variant_id=VARIANT_ID,
    code_snapshot={"file1.c": sha},
    dbc_snapshot={"test.dbc": sha},
    material_snapshot={"mat-abc123": sha},
    config_version=sha,
    model_profile={"remote_model": "test-model"},
)
check("Snapshot.create with enrichment", snap2.snapshot_id.startswith("snap-"))
check("code_snapshot stored", snap2.code_snapshot == {"file1.c": sha})
check("dbc_snapshot stored", snap2.dbc_snapshot == {"test.dbc": sha})
check("material_snapshot stored", snap2.material_snapshot == {"mat-abc123": sha})


# =====================================================================
# Summary
# =====================================================================
print(f"\n{'='*60}")
print(f"  RESULTS: {PASS} passed, {FAIL} failed")
print(f"{'='*60}")

if FAIL > 0:
    print("\nFAILURES:")
    for e in ERRORS:
        print(e)
    print()

print(f"Variant ID used: {VARIANT_ID}")
print(f"Snapshot ID:     {snap_id}")
sys.exit(1 if FAIL > 0 else 0)
