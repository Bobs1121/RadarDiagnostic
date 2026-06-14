# -*- coding: utf-8 -*-
"""
Identity model for variant / package_profile / snapshot hierarchy.

This module defines the core identity primitives that replace the flat
`project_key` model.  The five layers are::

    PlatformFamily  (technology plugin - gen6_c_radar, gen5_cpp_radar)
      +-- Codebase   (physical workspace - e.g. D:/GWM-CR60LIGHT/cr60_light)
            +-- Variant     (customer project - coem/GWM_B26, apl/byd)
                  +-- PackageProfile  (build parameter combo)
                        +-- Snapshot  (auditable point-in-time state)

Backward compatibility:
    - `project_key` still works as an alias for `variant_id` when passed
      to legacy code.  A `compat_project_key` property bridges old callers.
    - Existing `config.yaml` `projects.*` entries are automatically
      upgraded to `variants` on first load (via `config.py`).

All models are serializable via `to_dict()` / `from_dict()` and
`to_json()` / `from_json()` for persistence.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


# ─── PlatformFamily ──────────────────────────────────────────────────

@dataclass
class PlatformFamily:
    """Technology-level platform plugin definition.

    Fields:
        platform_id:   Unique identifier, e.g. "gen6_c_radar".
        language:      Source language — "c" or "cpp".
        build_system:  Build system — "scons" or "cmake".
        codegraph_plugin:  Optional codegraph builder plugin name.
        parser_plugin:     Optional data parser plugin name.
        symbol_ruleset:    Optional symbol extraction ruleset name.
        default_pipeline_profile: Optional pipeline profile name.
    """
    platform_id: str
    language: str = "c"
    build_system: str = "scons"
    codegraph_plugin: Optional[str] = None
    parser_plugin: Optional[str] = None
    symbol_ruleset: Optional[str] = None
    default_pipeline_profile: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "platform_id": self.platform_id,
            "language": self.language,
            "build_system": self.build_system,
            **{k: v for k, v in (
                ("codegraph_plugin", self.codegraph_plugin),
                ("parser_plugin", self.parser_plugin),
                ("symbol_ruleset", self.symbol_ruleset),
                ("default_pipeline_profile", self.default_pipeline_profile),
            ) if v is not None},
        }

    @classmethod
    def from_dict(cls, d: dict) -> PlatformFamily:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ─── Codebase ────────────────────────────────────────────────────────

@dataclass
class Codebase:
    """Physical code workspace.

    Fields:
        codebase_id:  Unique identifier, e.g. "gwm_cr60light".
        root_path:    Absolute path to the code workspace root.
        repo_url:     Optional git repository URL.
        branch:       Optional branch name.
        commit:       Optional commit hash.
        platform_id:  Reference to PlatformFamily.platform_id.
    """
    codebase_id: str
    root_path: str
    repo_url: Optional[str] = None
    branch: Optional[str] = None
    commit: Optional[str] = None
    platform_id: Optional[str] = None

    @property
    def root(self) -> Path:
        return Path(self.root_path)

    def to_dict(self) -> dict[str, Any]:
        return {
            "codebase_id": self.codebase_id,
            "root_path": self.root_path,
            "platform_id": self.platform_id,
            **{k: v for k, v in (
                ("repo_url", self.repo_url),
                ("branch", self.branch),
                ("commit", self.commit),
            ) if v is not None},
        }

    @classmethod
    def from_dict(cls, d: dict) -> Codebase:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ─── Variant ─────────────────────────────────────────────────────────

@dataclass
class VariantScope:
    """Code scope filter for a variant.

    Fields:
        include_globs:  Glob patterns to include.
        exclude_globs:  Glob patterns to exclude.
    """
    include_globs: list[str] = field(default_factory=list)
    exclude_globs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "include_globs": self.include_globs,
            **({"exclude_globs": self.exclude_globs} if self.exclude_globs else {}),
        }

    @classmethod
    def from_dict(cls, d: dict) -> VariantScope:
        return cls(
            include_globs=d.get("include_globs", d.get("include", [])),
            exclude_globs=d.get("exclude_globs", d.get("exclude", [])),
        )


@dataclass
class DBCSet:
    """Named set of DBC files.

    Fields:
        name:     Set name, e.g. "default".
        files:    List of DBC file paths (relative to codebase root or absolute).
    """
    name: str = "default"
    files: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "files": self.files}

    @classmethod
    def from_dict(cls, d: dict) -> DBCSet:
        if isinstance(d, dict):
            return cls(name=d.get("name", "default"), files=d.get("files", []))
        # If it's a simple list of files
        if isinstance(d, list):
            return cls(name="default", files=d)
        return cls()


@dataclass
class Variant:
    """Customer project variant — the primary identity for knowledge isolation.

    A variant defines the customer-specific boundaries: which source files
    belong to this customer project, which DBC files apply, which build
    entry point to use, etc.

    Examples:
        - "gen6/gwm_b26"  (coem/GWM_B26/)
        - "gen6/byd_sc6h" (coem/BYD_SC6H/)
        - "gen5/byd"      (apl/byd/)
        - "gen5/gwm"      (apl/gwm/)

    Fields:
        variant_id:            Unique identifier, e.g. "gen6/gwm_b26".
        codebase_id:           Reference to Codebase.codebase_id.
        display_name:          Human-readable name.
        scope:                 Code scope (include/exclude globs).
        build_entry:           Path to build script entry point.
        default_package_profile: Default package_profile_id.
        dbc_sets:              List of DBC file sets.
        key_source_files:      List of key source file paths (relative).
        source_domains:        Dict[str, list[str]] domain groupings.
        signal_alias_overrides: Dict[str, str] CAN signal alias map.
        requirement_overlays:  List of requirement material references.
        project_key:           DEPRECATED — backward compat alias.
    """
    variant_id: str
    codebase_id: str
    display_name: str = ""
    scope: VariantScope = field(default_factory=VariantScope)
    build_entry: Optional[str] = None
    default_package_profile: Optional[str] = None
    dbc_sets: list[DBCSet] = field(default_factory=list)
    key_source_files: list[str] = field(default_factory=list)
    source_domains: dict[str, list[str]] = field(default_factory=dict)
    signal_alias_overrides: dict[str, str] = field(default_factory=dict)
    requirement_overlays: list[str] = field(default_factory=list)
    project_key: Optional[str] = None  # DEPRECATED

    @property
    def compat_project_key(self) -> str:
        """Return a backward-compatible project_key derived from variant_id.

        This bridges old code that expects `project_key`.  If the legacy
        `project_key` field is explicitly set, prefer that.
        """
        if self.project_key:
            return self.project_key
        # Derive from variant_id: "gen6/gwm_b26" -> "gwm_b26"
        parts = self.variant_id.split("/")
        return parts[-1] if len(parts) > 1 else self.variant_id

    @property
    def gen_prefix(self) -> str:
        """Return the generation prefix: "gen6" or "gen5"."""
        parts = self.variant_id.split("/")
        return parts[0] if parts else ""

    def to_dict(self) -> dict[str, Any]:
        dbc_list = [s.to_dict() if isinstance(s, DBCSet) else s for s in self.dbc_sets]
        return {
            "variant_id": self.variant_id,
            "codebase_id": self.codebase_id,
            "display_name": self.display_name,
            "scope": self.scope.to_dict(),
            **({"build_entry": self.build_entry} if self.build_entry else {}),
            **({"default_package_profile": self.default_package_profile} if self.default_package_profile else {}),
            **({"dbc_sets": dbc_list} if dbc_list else {}),
            **({"key_source_files": self.key_source_files} if self.key_source_files else {}),
            **({"source_domains": self.source_domains} if self.source_domains else {}),
            **({"signal_alias_overrides": self.signal_alias_overrides} if self.signal_alias_overrides else {}),
            **({"requirement_overlays": self.requirement_overlays} if self.requirement_overlays else {}),
        }

    @classmethod
    def from_dict(cls, d: dict) -> Variant:
        scope_raw = d.get("scope", {})
        scope = VariantScope.from_dict(scope_raw) if isinstance(scope_raw, dict) else VariantScope()

        dbc_raw = d.get("dbc_sets", d.get("dbc_files", []))
        if isinstance(dbc_raw, list):
            dbc_sets = [DBCSet.from_dict(x) for x in dbc_raw]
        elif isinstance(dbc_raw, dict):
            # dbc_raw can be either:
            # A) A single DBCSet dict: {"name": "default", "files": [...]}
            # B) A dict-of-DBCSet keyed by name: {"default": {"name": "default", "files": [...]}, ...}
            # Distinguish: if the dict contains "files" key, it's a single DBCSet (A)
            #              otherwise it's a keyed dict (B)
            if "files" in dbc_raw or "name" in dbc_raw:
                dbc_sets = [DBCSet.from_dict(dbc_raw)]
            else:
                dbc_sets = [DBCSet.from_dict(v) for v in dbc_raw.values()]
        else:
            dbc_sets = []

        return cls(
            variant_id=d["variant_id"],
            codebase_id=d["codebase_id"],
            display_name=d.get("display_name", ""),
            scope=scope,
            build_entry=d.get("build_entry"),
            default_package_profile=d.get("default_package_profile"),
            dbc_sets=dbc_sets,
            key_source_files=d.get("key_source_files", d.get("key_source_files", [])),
            source_domains=d.get("source_domains", {}),
            signal_alias_overrides=d.get("signal_alias_overrides", {}),
            requirement_overlays=d.get("requirement_overlays", []),
            project_key=d.get("project_key"),
        )


# ─── PackageProfile ──────────────────────────────────────────────────

@dataclass
class BuildFlags:
    """Build parameters that define a software package variant.

    These map directly to SCons/CMake command-line flags from the
    real build scripts (scons_gen.bat, cmake_gen.bat).

    Gen6 flags (from scons_gen.bat):
        vehicleType, powerSupply, antenna, cyctime,
        swBuildType, funTestType, testMode

    Gen5 flags:
        customer-specific flags from cmake_gen.bat ARGS

    Fields:
        vehicle_type:   Vehicle type, e.g. "GWM_B26".
        power_supply:   Power supply mode, e.g. "KL15".
        antenna:        Antenna type, e.g. "SYMMETRY".
        cycle_time:     Cycle time, e.g. "T66MS".
        sw_build_type:  Build type, e.g. "DEVELOP".
        fun_test_type:  Functional test mode, e.g. "OFF".
        test_mode:      Test mode, e.g. "OFF".
        custom_flags:   Additional platform-specific flags.
    """
    vehicle_type: Optional[str] = None
    power_supply: Optional[str] = None
    antenna: Optional[str] = None
    cycle_time: Optional[str] = None
    sw_build_type: Optional[str] = None
    fun_test_type: Optional[str] = None
    test_mode: Optional[str] = None
    custom_flags: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        result = {}
        for k, v in (
            ("vehicle_type", self.vehicle_type),
            ("power_supply", self.power_supply),
            ("antenna", self.antenna),
            ("cycle_time", self.cycle_time),
            ("sw_build_type", self.sw_build_type),
            ("fun_test_type", self.fun_test_type),
            ("test_mode", self.test_mode),
        ):
            if v is not None:
                result[k] = v
        if self.custom_flags:
            result["custom_flags"] = self.custom_flags
        return result

    @classmethod
    def from_dict(cls, d: dict) -> BuildFlags:
        if not d:
            return cls()
        return cls(
            vehicle_type=d.get("vehicle_type", d.get("vehicleType")),
            power_supply=d.get("power_supply", d.get("powerSupply")),
            antenna=d.get("antenna"),
            cycle_time=d.get("cycle_time", d.get("cyctime")),
            sw_build_type=d.get("sw_build_type", d.get("swBuildType")),
            fun_test_type=d.get("fun_test_type", d.get("funTestType")),
            test_mode=d.get("test_mode", d.get("testMode")),
            custom_flags=d.get("custom_flags", {}),
        )


@dataclass
class PatchSet:
    """Patch set applied during build.

    Fields:
        source_dir: Path to patch source directory.
        files:      List of individual patch files.
    """
    source_dir: Optional[str] = None
    files: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            **({"source_dir": self.source_dir} if self.source_dir else {}),
            **({"files": self.files} if self.files else {}),
        }

    @classmethod
    def from_dict(cls, d: dict) -> PatchSet:
        if not d:
            return cls()
        if isinstance(d, str):
            return cls(source_dir=d)
        return cls(
            source_dir=d.get("source_dir", d.get("source")),
            files=d.get("files", []),
        )


@dataclass
class PackageProfile:
    """Build parameter combination that determines the software package.

    A PackageProfile captures the exact build flags, macro set, and
    patch configuration that produces a specific software package from
    a Variant's code.

    Example:
        "gen6/gwm_b26/default" = KL15 + SYMMETRY + T66MS + DEVELOP

    Fields:
        package_profile_id: Unique identifier, e.g. "gen6/gwm_b26/default".
        variant_id:         Reference to Variant.variant_id.
        build_flags:        BuildFlags — core build parameters.
        macro_set:          Dict of preprocessor macros.
        patch_set:          PatchSet — build-time file patches.
        artifact_rules:     Dict of artifact output rules.
    """
    package_profile_id: str
    variant_id: str
    build_flags: BuildFlags = field(default_factory=BuildFlags)
    macro_set: dict[str, str] = field(default_factory=dict)
    patch_set: Optional[PatchSet] = None
    artifact_rules: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "package_profile_id": self.package_profile_id,
            "variant_id": self.variant_id,
            "build_flags": self.build_flags.to_dict(),
            **({"macro_set": self.macro_set} if self.macro_set else {}),
            **({"patch_set": self.patch_set.to_dict()} if self.patch_set else {}),
            **({"artifact_rules": self.artifact_rules} if self.artifact_rules else {}),
        }

    @classmethod
    def from_dict(cls, d: dict) -> PackageProfile:
        pf = d.get("build_flags", {})
        return cls(
            package_profile_id=d["package_profile_id"],
            variant_id=d["variant_id"],
            build_flags=BuildFlags.from_dict(pf),
            macro_set=d.get("macro_set", {}),
            patch_set=PatchSet.from_dict(d.get("patch_set")) if d.get("patch_set") else None,
            artifact_rules=d.get("artifact_rules", {}),
        )


# ─── Snapshot ────────────────────────────────────────────────────────

@dataclass
class Snapshot:
    """Auditable point-in-time snapshot of code + config + materials.

    Every diagnosis, knowledge artifact, and Harness evaluation should
    reference a snapshot_id to ensure reproducibility.

    Fields:
        snapshot_id:      Unique identifier (auto-generated from hash).
        variant_id:       Reference to Variant.
        package_profile_id: Reference to PackageProfile.
        created_at:       ISO timestamp of creation.
        code_snapshot:    Dict with commit hash or file hash summary.
        dbc_snapshot:     Dict mapping DBC filename -> file hash.
        material_snapshot: Dict mapping material_id -> file hash.
        config_version:   Hash or version string of config.yaml.
        model_profile:    Dict describing LLM model config used.
        metadata:         Free-form additional metadata.
    """
    snapshot_id: str = ""
    variant_id: str = ""
    package_profile_id: Optional[str] = None
    created_at: str = ""
    code_snapshot: dict[str, str] = field(default_factory=dict)
    dbc_snapshot: dict[str, str] = field(default_factory=dict)
    material_snapshot: dict[str, str] = field(default_factory=dict)
    config_version: str = ""
    model_profile: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        variant_id: str,
        package_profile_id: Optional[str] = None,
        code_snapshot: Optional[dict[str, str]] = None,
        dbc_snapshot: Optional[dict[str, str]] = None,
        material_snapshot: Optional[dict[str, str]] = None,
        config_version: str = "",
        model_profile: Optional[dict[str, str]] = None,
    ) -> Snapshot:
        """Create a new Snapshot with auto-generated snapshot_id.

        The snapshot_id is derived from a hash of the variant_id,
        package_profile_id, code_snapshot, dbc_snapshot, and a
        timestamp to ensure uniqueness.
        """
        now = datetime.now(timezone.utc).isoformat()
        hash_input = json.dumps({
            "variant_id": variant_id,
            "package_profile_id": package_profile_id,
            "code": code_snapshot or {},
            "dbc": dbc_snapshot or {},
            "ts": now,
        }, sort_keys=True)
        snapshot_id = f"snap-{hashlib.sha256(hash_input.encode()).hexdigest()[:12]}"

        return cls(
            snapshot_id=snapshot_id,
            variant_id=variant_id,
            package_profile_id=package_profile_id,
            created_at=now,
            code_snapshot=code_snapshot or {},
            dbc_snapshot=dbc_snapshot or {},
            material_snapshot=material_snapshot or {},
            config_version=config_version,
            model_profile=model_profile or {},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "variant_id": self.variant_id,
            **({"package_profile_id": self.package_profile_id} if self.package_profile_id else {}),
            "created_at": self.created_at,
            **({"code_snapshot": self.code_snapshot} if self.code_snapshot else {}),
            **({"dbc_snapshot": self.dbc_snapshot} if self.dbc_snapshot else {}),
            **({"material_snapshot": self.material_snapshot} if self.material_snapshot else {}),
            **({"config_version": self.config_version} if self.config_version else {}),
            **({"model_profile": self.model_profile} if self.model_profile else {}),
            **({"metadata": self.metadata} if self.metadata else {}),
        }

    @classmethod
    def from_dict(cls, d: dict) -> Snapshot:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)

    def save(self, path: Path) -> None:
        """Save snapshot to a JSON file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json(), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> Snapshot:
        """Load snapshot from a JSON file."""
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))


# ─── Convenience: file hashing ───────────────────────────────────────

def file_sha256(filepath: Path) -> str:
    """Compute SHA256 hash of a file, return hex digest."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def hash_files(file_paths: list[Path]) -> dict[str, str]:
    """Return {relative_path: sha256_hex} for each file."""
    result = {}
    for p in file_paths:
        if p.exists():
            result[str(p)] = file_sha256(p)
    return result


def hash_directory(dir_path: Path, glob_pattern: str = "**/*.c") -> dict[str, str]:
    """Hash all files matching glob_pattern under dir_path."""
    return hash_files(list(dir_path.glob(glob_pattern)))
