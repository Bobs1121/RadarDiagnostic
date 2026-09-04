# -*- coding: utf-8 -*-
"""
Diagnosis artifacts: DiagnosisBundle, RootCausePattern, FixPlaybook.

These models formalize the output of the diagnosis pipeline and the
knowledge沉淀 (knowledge crystallization) system.

- DiagnosisBundle: structured diagnosis output with evidence chain,
  reasoning graph, and output gating.  Replaces the ad-hoc report.md
  with a machine-readable bundle that can also render to HTML/MD.

- RootCausePattern: reusable knowledge about recurring failure modes.
  Indexed by variant scope, trigger conditions, and evidence signatures.

- FixPlaybook: prescriptive fix templates linked to RootCausePattern.
  Contains change templates, pre/post conditions, and validation checks.

Persistence:
    All models support to_dict/from_dict and JSON serialization.
    Bundle and Pattern have save()/load() for file-backed storage.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


# ─── Evidence ───────────────────────────────────────────────────────

@dataclass
class Evidence:
    """A single piece of evidence in a diagnosis.

    Fields:
        evidence_id:  Unique identifier.
        source:       Source type (signal / code / dbc / material / log).
        description:  Human-readable description.
        location:     Where this evidence was found (file:line, signal:time, etc.).
        raw_data:     Raw data snippet (optional).
        confidence:   Confidence score 0.0-1.0.
        metadata:     Additional context.
    """
    evidence_id: str = ""
    source: str = ""
    description: str = ""
    location: str = ""
    raw_data: str = ""
    confidence: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "source": self.source,
            "description": self.description,
            **({"location": self.location} if self.location else {}),
            **({"raw_data": self.raw_data} if self.raw_data else {}),
            "confidence": self.confidence,
            **({"metadata": self.metadata} if self.metadata else {}),
        }

    @classmethod
    def from_dict(cls, d: dict) -> Evidence:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ─── CodeLocation ───────────────────────────────────────────────────

@dataclass
class CodeLocation:
    """A specific location in source code.

    Fields:
        file_path:   Relative path to source file.
        line_start:  Starting line number.
        line_end:    Ending line number (inclusive).
        function:    Function name (if applicable).
        symbol:      Symbol name (variable, macro, etc.).
    """
    file_path: str = ""
    line_start: int = 0
    line_end: int = 0
    function: str = ""
    symbol: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_path": self.file_path,
            "line_start": self.line_start,
            **({"line_end": self.line_end} if self.line_end else {}),
            **({"function": self.function} if self.function else {}),
            **({"symbol": self.symbol} if self.symbol else {}),
        }

    @classmethod
    def from_dict(cls, d: dict) -> CodeLocation:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ─── DiagnosisBundle ────────────────────────────────────────────────

class ConclusionLevel(str):
    """Diagnosis conclusion confidence levels."""
    CONFIRMED = "confirmed_root_cause"
    CANDIDATE = "candidate_root_causes"
    EVIDENCE_ONLY = "evidence_summary_only"


@dataclass
class ChangeProposal:
    """Proposed code change for fixing a root cause.

    Gate rule: no executable diff without reliable code localization.
    """
    proposal_id: str = ""
    bundle_id: str = ""
    root_cause_pattern_ids: list[str] = field(default_factory=list)
    target_files: list[str] = field(default_factory=list)
    target_functions: list[str] = field(default_factory=list)
    diff_text: str = ""
    risk_notes: str = ""
    expected_effect: str = ""
    required_simulation: str = ""
    approval_state: str = "draft"  # draft / reviewed / approved / rejected
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            **({"bundle_id": self.bundle_id} if self.bundle_id else {}),
            **({"root_cause_pattern_ids": self.root_cause_pattern_ids} if self.root_cause_pattern_ids else {}),
            **({"target_files": self.target_files} if self.target_files else {}),
            **({"target_functions": self.target_functions} if self.target_functions else {}),
            **({"diff_text": self.diff_text} if self.diff_text else {}),
            **({"risk_notes": self.risk_notes} if self.risk_notes else {}),
            **({"expected_effect": self.expected_effect} if self.expected_effect else {}),
            **({"required_simulation": self.required_simulation} if self.required_simulation else {}),
            "approval_state": self.approval_state,
            **({"metadata": self.metadata} if self.metadata else {}),
        }

    @classmethod
    def from_dict(cls, d: dict) -> ChangeProposal:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class DiagnosisBundle:
    """Structured output of a full diagnosis run.

    Replaces the ad-hoc report.md with a machine-readable bundle.
    Contains: problem statement, evidence chain, reasoning graph,
    root cause assessment, code localization, change proposals,
    and requirement trace.

    Output gating:
        - No `confirmed_root_cause` without complete evidence chain.
        - No executable diff without reliable code localization.

    Fields:
        bundle_id:            Unique ID (auto-generated).
        case_id:              Case directory name.
        variant_id:           Variant this diagnosis was run against.
        snapshot_id:          Snapshot reference for auditability.
        created_at:           Timestamp.
        problem_statement:    Problem description + expected behavior.
        classification:       Task classification (function, component, etc.).
        conclusion_level:     One of CONFIRMED / CANDIDATE / EVIDENCE_ONLY.
        root_cause:           Primary root cause description.
        root_cause_confidence: 0.0-1.0 confidence score.
        evidence_chain:       List of Evidence objects.
        reasoning_graph:      Dict describing the reasoning flow.
        code_localization:    List of CodeLocation objects.
        change_proposals:     List of ChangeProposal objects.
        requirement_trace:    Dict mapping requirement_id to relevance.
        signal_analysis:      Dict of signal-level findings.
        metadata:             Additional metadata.
    """
    bundle_id: str = ""
    case_id: str = ""
    variant_id: str = ""
    snapshot_id: str = ""
    created_at: str = ""
    problem_statement: str = ""
    expected_behavior: str = ""
    classification: str = ""
    conclusion_level: str = ConclusionLevel.EVIDENCE_ONLY
    root_cause: str = ""
    root_cause_confidence: float = 0.0
    candidate_root_causes: list[str] = field(default_factory=list)
    evidence_chain: list[Evidence] = field(default_factory=list)
    reasoning_graph: dict[str, Any] = field(default_factory=dict)
    code_localization: list[CodeLocation] = field(default_factory=list)
    change_proposals: list[ChangeProposal] = field(default_factory=list)
    requirement_trace: dict[str, Any] = field(default_factory=dict)
    signal_analysis: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def _ensure_id(self):
        if not self.bundle_id:
            hash_input = json.dumps({
                "case": self.case_id,
                "variant": self.variant_id,
                "problem": self.problem_statement,
                "ts": self.created_at,
            }, sort_keys=True)
            self.bundle_id = f"diag-{hashlib.sha256(hash_input.encode()).hexdigest()[:12]}"

    def _check_gating(self) -> list[str]:
        """Check output gating rules. Returns list of violations."""
        violations = []
        if self.conclusion_level == ConclusionLevel.CONFIRMED:
            if not self.evidence_chain:
                violations.append(
                    "CONFIRMED root_cause requires evidence_chain"
                )
            if not self.code_localization:
                violations.append(
                    "CONFIRMED root_cause requires code_localization"
                )
        for cp in self.change_proposals:
            if cp.diff_text and not self.code_localization:
                violations.append(
                    f"ChangeProposal {cp.proposal_id} has diff but no code_localization"
                )
        return violations

    def add_evidence(self, evidence: Evidence):
        """Add an evidence item to the chain."""
        self.evidence_chain.append(evidence)

    def upgrade_to_candidate(self):
        """Upgrade from evidence_only to candidate if enough evidence."""
        if self.conclusion_level == ConclusionLevel.EVIDENCE_ONLY:
            if len(self.evidence_chain) >= 2:
                self.conclusion_level = ConclusionLevel.CANDIDATE
                log.info("Upgraded to CANDIDATE based on evidence count")

    def upgrade_to_confirmed(self):
        """Upgrade to confirmed_root_cause if all gates pass."""
        if self.conclusion_level in (ConclusionLevel.EVIDENCE_ONLY, ConclusionLevel.CANDIDATE):
            if self.evidence_chain and self.code_localization:
                self.conclusion_level = ConclusionLevel.CONFIRMED
                log.info("Upgraded to CONFIRMED — evidence + localization present")

    def to_dict(self) -> dict[str, Any]:
        self._ensure_id()
        violations = self._check_gating()
        return {
            "bundle_id": self.bundle_id,
            "case_id": self.case_id,
            "variant_id": self.variant_id,
            **({"snapshot_id": self.snapshot_id} if self.snapshot_id else {}),
            "created_at": self.created_at,
            "problem_statement": self.problem_statement,
            **({"expected_behavior": self.expected_behavior} if self.expected_behavior else {}),
            **({"classification": self.classification} if self.classification else {}),
            "conclusion_level": self.conclusion_level,
            **({"root_cause": self.root_cause} if self.root_cause else {}),
            "root_cause_confidence": self.root_cause_confidence,
            **({"candidate_root_causes": self.candidate_root_causes} if self.candidate_root_causes else {}),
            "evidence_chain": [e.to_dict() for e in self.evidence_chain],
            **({"reasoning_graph": self.reasoning_graph} if self.reasoning_graph else {}),
            "code_localization": [c.to_dict() for c in self.code_localization],
            "change_proposals": [c.to_dict() for c in self.change_proposals],
            **({"requirement_trace": self.requirement_trace} if self.requirement_trace else {}),
            **({"signal_analysis": self.signal_analysis} if self.signal_analysis else {}),
            **({"gating_violations": violations} if violations else {}),
            **({"metadata": self.metadata} if self.metadata else {}),
        }

    @classmethod
    def from_dict(cls, d: dict) -> DiagnosisBundle:
        evidence = [Evidence.from_dict(e) for e in d.get("evidence_chain", [])]
        locations = [CodeLocation.from_dict(c) for c in d.get("code_localization", [])]
        proposals = [ChangeProposal.from_dict(c) for c in d.get("change_proposals", [])]
        # Exclude nested-list fields from **spread to avoid duplicate kwarg
        skip_fields = {"evidence_chain", "code_localization", "change_proposals"}
        flat = {k: v for k, v in d.items()
                if k in cls.__dataclass_fields__ and k not in skip_fields}
        return cls(
            **flat,
            evidence_chain=evidence,
            code_localization=locations,
            change_proposals=proposals,
        )

    def save(self, path: Path) -> None:
        """Save bundle to JSON file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_id()
        path.write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        log.info(f"Saved DiagnosisBundle {self.bundle_id} → {path}")

    @classmethod
    def load(cls, path: Path) -> DiagnosisBundle:
        """Load bundle from JSON file."""
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))

    @classmethod
    def for_case(
        cls,
        project_root: Path,
        case_id: str,
        variant_id: str,
        problem: str,
        expected: str = "",
    ) -> DiagnosisBundle:
        """Create a new empty bundle for a case."""
        return cls(
            case_id=case_id,
            variant_id=variant_id,
            created_at=datetime.now(timezone.utc).isoformat(),
            problem_statement=problem,
            expected_behavior=expected,
        )


# ─── RootCausePattern ───────────────────────────────────────────────

@dataclass
class RootCausePattern:
    """Reusable knowledge about a recurring failure mode.

    Fields:
        pattern_id:             Unique identifier.
        variant_scope:          Which variants this applies to (list).
        platform_scope:         Which platform(s) this applies to.
        category:               Category (algorithm / signal_chain / param / state_machine).
        title:                  Short descriptive title.
        description:            Full description of the pattern.
        trigger_conditions:     Conditions that trigger this pattern.
        evidence_signature:     What evidence to look for.
        associated_signals:     CAN signals involved.
        associated_states:      System states involved.
        associated_code:        Code locations typically affected.
        confidence:             0.0-1.0 confidence in this pattern.
        source_case_ids:        Cases that led to this pattern.
        source_snapshot_ids:    Snapshots referenced by source cases.
        created_at:             Creation timestamp.
        metadata:               Additional context.
    """
    pattern_id: str = ""
    variant_scope: list[str] = field(default_factory=list)
    platform_scope: list[str] = field(default_factory=list)
    category: str = ""
    title: str = ""
    description: str = ""
    trigger_conditions: list[str] = field(default_factory=list)
    evidence_signature: str = ""
    associated_signals: list[str] = field(default_factory=list)
    associated_states: list[str] = field(default_factory=list)
    associated_code: list[str] = field(default_factory=list)
    confidence: float = 0.0
    source_case_ids: list[str] = field(default_factory=list)
    source_snapshot_ids: list[str] = field(default_factory=list)
    created_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "pattern_id": self.pattern_id,
            **({"variant_scope": self.variant_scope} if self.variant_scope else {}),
            **({"platform_scope": self.platform_scope} if self.platform_scope else {}),
            **({"category": self.category} if self.category else {}),
            "title": self.title,
            "description": self.description,
            **({"trigger_conditions": self.trigger_conditions} if self.trigger_conditions else {}),
            **({"evidence_signature": self.evidence_signature} if self.evidence_signature else {}),
            **({"associated_signals": self.associated_signals} if self.associated_signals else {}),
            **({"associated_states": self.associated_states} if self.associated_states else {}),
            **({"associated_code": self.associated_code} if self.associated_code else {}),
            "confidence": self.confidence,
            **({"source_case_ids": self.source_case_ids} if self.source_case_ids else {}),
            **({"source_snapshot_ids": self.source_snapshot_ids} if self.source_snapshot_ids else {}),
            **({"created_at": self.created_at} if self.created_at else {}),
            **({"metadata": self.metadata} if self.metadata else {}),
        }

    @classmethod
    def from_dict(cls, d: dict) -> RootCausePattern:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


# ─── FixPlaybook ────────────────────────────────────────────────────

@dataclass
class FixPlaybook:
    """Prescriptive fix template linked to a RootCausePattern.

    Cannot exist without a RootCausePattern.
    Must have source cases and validation records.

    Fields:
        playbook_id:            Unique identifier.
        pattern_id:             Linked RootCausePattern.
        title:                  Short title.
        description:            Fix description.
        applicable_variants:    Which variants this applies to.
        change_templates:       Dict of target_file -> change_description.
        preconditions:          Pre-conditions before applying fix.
        risk_checks:            Risk assessment steps.
        post_checks:            Post-fix validation steps.
        simulation_checks:      Simulation recommendations.
        validated_case_ids:     Cases where this playbook was validated.
        created_at:             Creation timestamp.
        metadata:               Additional context.
    """
    playbook_id: str = ""
    pattern_id: str = ""
    title: str = ""
    description: str = ""
    applicable_variants: list[str] = field(default_factory=list)
    change_templates: dict[str, str] = field(default_factory=dict)
    preconditions: list[str] = field(default_factory=list)
    risk_checks: list[str] = field(default_factory=list)
    post_checks: list[str] = field(default_factory=list)
    simulation_checks: list[str] = field(default_factory=list)
    validated_case_ids: list[str] = field(default_factory=list)
    created_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "playbook_id": self.playbook_id,
            "pattern_id": self.pattern_id,
            "title": self.title,
            "description": self.description,
            **({"applicable_variants": self.applicable_variants} if self.applicable_variants else {}),
            **({"change_templates": self.change_templates} if self.change_templates else {}),
            **({"preconditions": self.preconditions} if self.preconditions else {}),
            **({"risk_checks": self.risk_checks} if self.risk_checks else {}),
            **({"post_checks": self.post_checks} if self.post_checks else {}),
            **({"simulation_checks": self.simulation_checks} if self.simulation_checks else {}),
            **({"validated_case_ids": self.validated_case_ids} if self.validated_case_ids else {}),
            **({"created_at": self.created_at} if self.created_at else {}),
            **({"metadata": self.metadata} if self.metadata else {}),
        }

    @classmethod
    def from_dict(cls, d: dict) -> FixPlaybook:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


# ─── KnowledgeStore ────────────────────────────────────────────────

@dataclass
class KnowledgeStore:
    """File-backed store for RootCausePatterns and FixPlaybooks.

    Directory layout under project_root/memory/knowledge/:
        patterns/     — one JSON file per RootCausePattern
        playbooks/    — one JSON file per FixPlaybook
        index.json    — summary index of all patterns/playbooks
    """
    knowledge_dir: Path
    patterns: dict[str, RootCausePattern] = field(default_factory=dict)
    playbooks: dict[str, FixPlaybook] = field(default_factory=dict)

    def __post_init__(self):
        self.knowledge_dir = Path(self.knowledge_dir)
        self._load()

    def _load(self):
        """Load all patterns and playbooks from disk."""
        pattern_dir = self.knowledge_dir / "patterns"
        playbook_dir = self.knowledge_dir / "playbooks"

        if pattern_dir.exists():
            for f in pattern_dir.glob("*.json"):
                try:
                    p = RootCausePattern.from_dict(
                        json.loads(f.read_text(encoding="utf-8"))
                    )
                    self.patterns[p.pattern_id] = p
                except Exception as e:
                    log.warning(f"Failed to load pattern {f}: {e}")

        if playbook_dir.exists():
            for f in playbook_dir.glob("*.json"):
                try:
                    pb = FixPlaybook.from_dict(
                        json.loads(f.read_text(encoding="utf-8"))
                    )
                    self.playbooks[pb.playbook_id] = pb
                except Exception as e:
                    log.warning(f"Failed to load playbook {f}: {e}")

    def add_pattern(self, pattern: RootCausePattern) -> RootCausePattern:
        """Add a pattern, persisting to disk."""
        if not pattern.pattern_id:
            pattern.pattern_id = (
                f"rcp-{hashlib.sha256(pattern.title.encode()).hexdigest()[:12]}"
            )
        pattern_dir = self.knowledge_dir / "patterns"
        pattern_dir.mkdir(parents=True, exist_ok=True)
        pattern.save(pattern_dir / f"{pattern.pattern_id}.json")
        self.patterns[pattern.pattern_id] = pattern
        return pattern

    def add_playbook(self, playbook: FixPlaybook) -> FixPlaybook:
        """Add a playbook, persisting to disk."""
        if not playbook.playbook_id:
            playbook.playbook_id = (
                f"fb-{hashlib.sha256(playbook.title.encode()).hexdigest()[:12]}"
            )
        playbook_dir = self.knowledge_dir / "playbooks"
        playbook_dir.mkdir(parents=True, exist_ok=True)
        playbook.save(playbook_dir / f"{playbook.playbook_id}.json")
        self.playbooks[playbook.playbook_id] = playbook
        return playbook

    def find_patterns_by_signal(self, signal_name: str) -> list[RootCausePattern]:
        """Find patterns that reference a specific signal."""
        return [
            p for p in self.patterns.values()
            if signal_name in p.associated_signals
        ]

    def find_patterns_by_variant(self, variant_id: str) -> list[RootCausePattern]:
        """Find patterns applicable to a specific variant."""
        return [
            p for p in self.patterns.values()
            if variant_id in p.variant_scope or not p.variant_scope
        ]

    def find_playbook_for_pattern(self, pattern_id: str) -> list[FixPlaybook]:
        """Find playbooks linked to a specific pattern."""
        return [
            pb for pb in self.playbooks.values()
            if pb.pattern_id == pattern_id
        ]

    @classmethod
    def for_project(cls, project_root: Path) -> KnowledgeStore:
        """Create a KnowledgeStore for the radarAnalyze project."""
        return cls(knowledge_dir=project_root / "memory" / "knowledge")
