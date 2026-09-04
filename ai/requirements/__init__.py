# -*- coding: utf-8 -*-
"""
ai.requirements — Requirement↔Code traceability (M3) and requirement review (M8).

Public API:
    RequirementLoader   — parse requirement YAML into a StructuredRequirementSet.
    RequirementTracer   — build requirement↔code↔signal traceability (deterministic).
    RequirementReviewer — audit requirements for structural/semantic defects.
    RequirementModule   — BaseModule wrapper exposing both as a composable capability.
"""
from __future__ import annotations

from .loader import RequirementLoader
from .reviewer import RequirementReviewer
from .tracer import RequirementTracer
from .module import RequirementModule

__all__ = [
    "RequirementLoader",
    "RequirementTracer",
    "RequirementReviewer",
    "RequirementModule",
]
