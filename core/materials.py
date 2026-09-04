# -*- coding: utf-8 -*-
"""
Material Registry and StructuredRequirementSet — formal models for
customer requirement materials and derived knowledge.

This module replaces the ad-hoc practice of stuffing customer materials
as prompt text.  Instead, materials are registered with identity, hashed,
tagged, and tracked for provenance.

Core models:
    RegisteredMaterial    — one material file in the registry
    MaterialRegistry      — store + lookup for materials (JSON file-backed)
    RequirementSpec       — a single parsed requirement derived from material
    StructuredRequirementSet — collection of RequirementSpecs for a variant

Priority rule: AuthoritativeMaterial > LearnedKnowledge
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


# ─── Material Types ─────────────────────────────────────────────────

class MaterialType(str, Enum):
    """File format / material category."""
    PDF = "pdf"
    DOCX = "docx"
    MD = "md"
    XLSX = "xlsx"
    DBC = "dbc"
    JSON = "json"
    YAML = "yaml"
    TXT = "txt"
    CSV = "csv"

    @classmethod
    def from_path(cls, path: Path | str) -> MaterialType:
        ext = Path(path).suffix.lstrip(".").lower()
        try:
            return cls(ext)
        except ValueError:
            return cls.TXT


class MaterialCategory(str, Enum):
    """Authoritative vs learned knowledge — affects priority in diagnosis."""
    AUTHORITATIVE = "authoritative"
    LEARNED = "learned"


# ─── RegisteredMaterial ─────────────────────────────────────────────

@dataclass
class RegisteredMaterial:
    """One material file registered in the system.

    Fields:
        material_id:      Unique ID (auto-generated from variant + hash).
        variant_id:       Which variant this material belongs to.
        material_type:    MaterialType (pdf, dbc, xlsx, etc.).
        source_path:      Absolute or relative path to the source file.
        hash:             SHA256 hash of the file content.
        version:          Human-readable version string.
        category:         MaterialCategory (authoritative / learned).
        tags:             Free-form tags for filtering.
        title:            Human-readable title.
        created_at:       Registration timestamp.
        updated_at:       Last update timestamp.
        metadata:         Arbitrary additional metadata.
    """
    material_id: str = ""
    variant_id: str = ""
    material_type: str = "txt"
    source_path: str = ""
    hash: str = ""
    version: str = "1.0"
    category: str = MaterialCategory.AUTHORITATIVE.value
    tags: list[str] = field(default_factory=list)
    title: str = ""
    created_at: str = ""
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def register(
        cls,
        source_path: Path | str,
        variant_id: str,
        version: str = "1.0",
        category: str = MaterialCategory.AUTHORITATIVE.value,
        tags: list[str] | None = None,
        title: str = "",
    ) -> RegisteredMaterial:
        """Register a material file, computing hash and ID.

        Args:
            source_path:  Path to the material file.
            variant_id:   Variant this material belongs to.
            version:      Version string.
            category:     authoritative or learned.
            tags:         Optional tags.
            title:        Optional human-readable title.

        Returns:
            RegisteredMaterial with auto-generated material_id.
        """
        sp = Path(source_path)
        now = datetime.now(timezone.utc).isoformat()

        file_hash = ""
        if sp.exists():
            h = hashlib.sha256()
            with open(sp, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    h.update(chunk)
            file_hash = h.hexdigest()

        mat_type = MaterialType.from_path(sp)
        id_input = f"{variant_id}:{sp.name}:{file_hash}"
        material_id = f"mat-{hashlib.sha256(id_input.encode()).hexdigest()[:12]}"

        if not title:
            title = sp.stem

        return cls(
            material_id=material_id,
            variant_id=variant_id,
            material_type=mat_type.value,
            source_path=str(sp),
            hash=file_hash,
            version=version,
            category=category,
            tags=tags or [],
            title=title,
            created_at=now,
            updated_at=now,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "material_id": self.material_id,
            "variant_id": self.variant_id,
            "material_type": self.material_type,
            "source_path": self.source_path,
            "hash": self.hash,
            "version": self.version,
            "category": self.category,
            "tags": self.tags,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            **({"metadata": self.metadata} if self.metadata else {}),
        }

    @classmethod
    def from_dict(cls, d: dict) -> RegisteredMaterial:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ─── MaterialRegistry ───────────────────────────────────────────────

@dataclass
class MaterialRegistry:
    """File-backed registry for materials.

    Stores RegisteredMaterial objects in a JSON index file.
    Supports registration, lookup, and change detection.

    Fields:
        registry_path: Path to the JSON index file.
        materials:     Dict[material_id, RegisteredMaterial].
    """
    registry_path: Path
    materials: dict[str, RegisteredMaterial] = field(default_factory=dict)

    def __post_init__(self):
        self.registry_path = Path(self.registry_path)
        self._load()

    def _load(self):
        """Load registry from disk."""
        if self.registry_path.exists():
            try:
                data = json.loads(self.registry_path.read_text(encoding="utf-8"))
                self.materials = {
                    k: RegisteredMaterial.from_dict(v)
                    for k, v in data.get("materials", {}).items()
                }
            except (json.JSONDecodeError, KeyError) as e:
                log.warning(f"Failed to load material registry: {e}")
                self.materials = {}

    def _save(self):
        """Persist registry to disk."""
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "registry_path": str(self.registry_path),
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "materials": {k: v.to_dict() for k, v in self.materials.items()},
        }
        self.registry_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def register(
        self,
        source_path: Path | str,
        variant_id: str,
        version: str = "1.0",
        category: str = MaterialCategory.AUTHORITATIVE.value,
        tags: list[str] | None = None,
        title: str = "",
    ) -> RegisteredMaterial:
        """Register a material, auto-detecting changes.

        If the same file (by path) already exists with a different hash,
        it is updated (new material_id, new hash).
        """
        mat = RegisteredMaterial.register(
            source_path=source_path,
            variant_id=variant_id,
            version=version,
            category=category,
            tags=tags,
            title=title,
        )

        # Check if we already have this file registered
        existing = self._find_by_path(str(Path(source_path).resolve()))
        if existing:
            existing_id = existing.material_id
            if existing.hash != mat.hash:
                log.info(
                    f"Material changed: {existing_id} → {mat.material_id} "
                    f"(hash: {existing.hash[:8]} → {mat.hash[:8]})"
                )
            else:
                # Same content, reuse existing ID
                mat.material_id = existing_id
                mat.created_at = existing.created_at
        else:
            log.info(f"Registered new material: {mat.material_id}")

        self.materials[mat.material_id] = mat
        self._save()
        return mat

    def get(self, material_id: str) -> RegisteredMaterial | None:
        """Get a material by ID."""
        return self.materials.get(material_id)

    def list_by_variant(self, variant_id: str) -> list[RegisteredMaterial]:
        """List all materials for a given variant."""
        return [m for m in self.materials.values() if m.variant_id == variant_id]

    def list_by_category(
        self, variant_id: str, category: str
    ) -> list[RegisteredMaterial]:
        """List materials filtered by variant and category."""
        return [
            m for m in self.materials.values()
            if m.variant_id == variant_id and m.category == category
        ]

    def list_authoritative(self, variant_id: str) -> list[RegisteredMaterial]:
        """List only authoritative materials for a variant."""
        return self.list_by_category(variant_id, MaterialCategory.AUTHORITATIVE.value)

    def _find_by_path(self, resolved_path: str) -> RegisteredMaterial | None:
        """Find existing registration by resolved source path."""
        for m in self.materials.values():
            if Path(m.source_path).resolve() == Path(resolved_path):
                return m
        return None

    @classmethod
    def for_variant(
        cls, project_root: Path, variant_id: str
    ) -> MaterialRegistry:
        """Create a MaterialRegistry for a specific variant.

        Registry file is stored at:
            project_root / "materials" / "<variant_safe>" / "registry.json"
        """
        safe_id = variant_id.replace("/", "_").replace(" ", "_").lower()
        registry_path = project_root / "materials" / safe_id / "registry.json"
        return cls(registry_path=registry_path)


# ─── RequirementSpec ────────────────────────────────────────────────

@dataclass
class RequirementSpec:
    """A single parsed requirement, derived from a material.

    Fields:
        requirement_id:   Unique ID.
        material_id:      Source material this came from.
        variant_id:       Variant scope.
        scope:            Domain scope (function / module / signal / state).
        statement:        Human-readable requirement statement.
        normalized_logic: Formalized logic expression (optional).
        linked_signals:   Related CAN signal names.
        linked_files:     Related source file paths.
        linked_functions: Related function names.
        priority:         Priority level (critical / high / medium / low).
        evidence_policy:  What constitutes evidence for this requirement.
        metadata:         Additional metadata.
    """
    requirement_id: str = ""
    material_id: str = ""
    variant_id: str = ""
    scope: str = ""
    statement: str = ""
    normalized_logic: str = ""
    linked_signals: list[str] = field(default_factory=list)
    linked_files: list[str] = field(default_factory=list)
    linked_functions: list[str] = field(default_factory=list)
    priority: str = "medium"
    evidence_policy: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "requirement_id": self.requirement_id,
            "material_id": self.material_id,
            "variant_id": self.variant_id,
            "scope": self.scope,
            "statement": self.statement,
            **({"normalized_logic": self.normalized_logic} if self.normalized_logic else {}),
            **({"linked_signals": self.linked_signals} if self.linked_signals else {}),
            **({"linked_files": self.linked_files} if self.linked_files else {}),
            **({"linked_functions": self.linked_functions} if self.linked_functions else {}),
            "priority": self.priority,
            **({"evidence_policy": self.evidence_policy} if self.evidence_policy else {}),
            **({"metadata": self.metadata} if self.metadata else {}),
        }

    @classmethod
    def from_dict(cls, d: dict) -> RequirementSpec:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ─── StructuredRequirementSet ───────────────────────────────────────

@dataclass
class StructuredRequirementSet:
    """Collection of parsed requirements for a variant.

    Stores RequirementSpec objects indexed by requirement_id.
    Supports file-backed persistence for audit trail.

    Fields:
        variant_id:       Which variant this requirement set belongs to.
        snapshot_id:      Optional snapshot reference for auditability.
        requirements:     Dict[requirement_id, RequirementSpec].
    """
    variant_id: str = ""
    snapshot_id: str = ""
    requirements: dict[str, RequirementSpec] = field(default_factory=dict)

    def add(self, spec: RequirementSpec) -> None:
        """Add a requirement to this set."""
        self.requirements[spec.requirement_id] = spec

    def get(self, requirement_id: str) -> RequirementSpec | None:
        """Get a requirement by ID."""
        return self.requirements.get(requirement_id)

    def list_by_scope(self, scope: str) -> list[RequirementSpec]:
        """List requirements filtered by scope."""
        return [r for r in self.requirements.values() if r.scope == scope]

    def list_by_signals(self, signal_name: str) -> list[RequirementSpec]:
        """List requirements that reference a specific signal."""
        return [
            r for r in self.requirements.values()
            if signal_name in r.linked_signals
        ]

    def list_critical(self) -> list[RequirementSpec]:
        """List critical-priority requirements."""
        return [r for r in self.requirements.values() if r.priority == "critical"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "variant_id": self.variant_id,
            **({"snapshot_id": self.snapshot_id} if self.snapshot_id else {}),
            "requirements": {k: v.to_dict() for k, v in self.requirements.items()},
        }

    @classmethod
    def from_dict(cls, d: dict) -> StructuredRequirementSet:
        reqs = {
            k: RequirementSpec.from_dict(v)
            for k, v in d.get("requirements", {}).items()
        }
        return cls(
            variant_id=d.get("variant_id", ""),
            snapshot_id=d.get("snapshot_id", ""),
            requirements=reqs,
        )

    def save(self, path: Path) -> None:
        """Save to JSON file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: Path) -> StructuredRequirementSet:
        """Load from JSON file."""
        return cls.from_dict(
            json.loads(path.read_text(encoding="utf-8"))
        )

    @classmethod
    def for_variant(
        cls, project_root: Path, variant_id: str
    ) -> StructuredRequirementSet:
        """Load or create a StructuredRequirementSet for a variant.

        File: project_root / "materials" / "<variant_safe>" / "requirements.json"
        """
        safe_id = variant_id.replace("/", "_").replace(" ", "_").lower()
        req_path = project_root / "materials" / safe_id / "requirements.json"
        if req_path.exists():
            return cls.load(req_path)
        return cls(variant_id=variant_id)


def render_material_summary(
    project_root: Path,
    variant_id: str,
    *,
    max_materials: int = 8,
    max_requirements: int = 12,
    max_chars: int = 4000,
) -> dict[str, Any]:
    """Render a bounded, deterministic material summary for diagnosis context.

    Empty registries are represented in metadata but return an empty
    ``prompt_text`` so expert prompts do not get noisy placeholder sections.
    """
    registry = MaterialRegistry.for_variant(project_root, variant_id)
    req_set = StructuredRequirementSet.for_variant(project_root, variant_id)

    materials = sorted(
        registry.list_by_variant(variant_id),
        key=lambda m: (m.category != MaterialCategory.AUTHORITATIVE.value, m.title, m.material_id),
    )
    authoritative = [m for m in materials if m.category == MaterialCategory.AUTHORITATIVE.value]
    requirements = sorted(
        req_set.requirements.values(),
        key=lambda r: (
            {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(r.priority, 4),
            r.scope,
            r.requirement_id,
        ),
    )

    result: dict[str, Any] = {
        "variant_id": variant_id,
        "material_count": len(materials),
        "authoritative_count": len(authoritative),
        "requirement_count": len(requirements),
        "critical_requirement_count": len([r for r in requirements if r.priority == "critical"]),
        "material_ids": [m.material_id for m in materials],
        "requirement_ids": [r.requirement_id for r in requirements],
        "prompt_text": "",
    }

    if not materials and not requirements:
        return result

    lines = [
        "## ★★ 权威材料摘要(Material Registry) ★★",
        f"- Variant: `{variant_id}`",
        f"- Materials: {len(materials)} total, {len(authoritative)} authoritative",
        f"- Structured requirements: {len(requirements)} total",
    ]

    if materials:
        lines.append("\n### Registered Materials")
        for mat in materials[:max_materials]:
            tags = f" tags={','.join(mat.tags)}" if mat.tags else ""
            hash_preview = mat.hash[:12] if mat.hash else "no-hash"
            lines.append(
                f"- `{mat.material_id}` {mat.title or Path(mat.source_path).name} "
                f"({mat.material_type}, {mat.category}, v{mat.version}, hash={hash_preview}){tags}"
            )
        if len(materials) > max_materials:
            lines.append(f"- ... {len(materials) - max_materials} more material(s)")

    if requirements:
        lines.append("\n### Structured Requirements")
        for req in requirements[:max_requirements]:
            linked = []
            if req.linked_signals:
                linked.append("signals=" + ",".join(req.linked_signals[:4]))
            if req.linked_functions:
                linked.append("functions=" + ",".join(req.linked_functions[:4]))
            suffix = f" ({'; '.join(linked)})" if linked else ""
            statement = req.statement.replace("\n", " ").strip()
            if len(statement) > 180:
                statement = statement[:177] + "..."
            lines.append(
                f"- `{req.requirement_id}` [{req.priority}] {req.scope}: {statement}{suffix}"
            )
        if len(requirements) > max_requirements:
            lines.append(f"- ... {len(requirements) - max_requirements} more requirement(s)")

    text = "\n".join(lines)
    if len(text) > max_chars:
        text = text[: max_chars - 18] + "\n... [truncated]"
    result["prompt_text"] = text
    return result
