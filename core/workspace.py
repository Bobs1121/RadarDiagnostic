# -*- coding: utf-8 -*-
"""
Workspace Management System (V3)
Handles Core + COEM project isolation, local configurations, and asset resolution.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional
import yaml

logger = logging.getLogger(__name__)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Merge nested config dictionaries while letting local values win."""
    merged = dict(base)
    for key, value in override.items():
        base_value = merged.get(key)
        if isinstance(base_value, dict) and isinstance(value, dict):
            merged[key] = _deep_merge(base_value, value)
        else:
            merged[key] = value
    return merged


class Workspace:
    """
    Represents a sandboxed environment for a specific project or COEM variant.
    Handles inheritance from a 'base_core' workspace if defined in config.
    """
    
    def __init__(self, workspace_name: str, workspaces_dir: Path):
        self.name = workspace_name
        self.workspace_dir = workspaces_dir / workspace_name
        self.config: dict = {}
        self.base_workspace: Optional['Workspace'] = None
        
        self._load()

    @classmethod
    def from_variant(cls, variant: object, workspaces_dir: Path) -> "Workspace":
        """Derive a runtime Workspace sandbox from a Variant (identity layer).

        The identity model (``core/identity.py``) answers *who / what* (which
        customer project); the Workspace answers *where / how to cascade*
        (Core+COEM resource resolution). This factory bridges the two without a
        hard import of ``core.identity`` — it accepts either a ``Variant``
        instance (duck-typed via ``.variant_id``) or a plain variant-id string.

        The workspace directory name is the sanitized variant id, e.g.
        ``"coem/GWM_B26"`` -> ``.workspaces/coem_GWM_B26``.
        """
        variant_id = getattr(variant, "variant_id", None) or str(variant)
        workspace_name = variant_id.replace("/", "_").replace("\\", "_")
        return cls(workspace_name, Path(workspaces_dir))

    def _load(self):
        """Loads the local config and resolves inheritance."""
        if not self.workspace_dir.exists():
            raise FileNotFoundError(f"Workspace directory not found: {self.workspace_dir}")
            
        config_path = self.workspace_dir / "config.yaml"
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                self.config = yaml.safe_load(f) or {}
                
        # Resolve Core+COEM inheritance
        inherits_from = self.config.get("inherits_from")
        if inherits_from:
            base_dir = self.workspace_dir.parent / inherits_from
            if base_dir.exists() and base_dir != self.workspace_dir:
                self.base_workspace = Workspace(inherits_from, self.workspace_dir.parent)
                logger.info(f"Workspace '{self.name}' inherits from '{inherits_from}'")
            else:
                logger.warning(f"Base workspace '{inherits_from}' not found.")

    def get_config(self) -> dict:
        """Returns the merged configuration (Core + COEM)."""
        merged = {}
        if self.base_workspace:
            merged = self.base_workspace.get_config()
        merged = _deep_merge(merged, self.config)
        return merged

    def get_dbc_files(self) -> list[Path]:
        """Resolves DBC files, prioritizing COEM specific files, then base files."""
        dbcs = []
        # Add base DBCs first
        if self.base_workspace:
            dbcs.extend(self.base_workspace.get_dbc_files())
            
        # Add local DBCs (overrides/additions)
        local_dbc_dir = self.workspace_dir / "dbc"
        if local_dbc_dir.exists():
            dbcs.extend(list(local_dbc_dir.glob("*.dbc")))
            
        return dbcs

    def get_memory_dir(self) -> Path:
        """Returns the isolated memory directory for this workspace."""
        mem_dir = self.workspace_dir / "memory"
        mem_dir.mkdir(parents=True, exist_ok=True)
        return mem_dir

    def get_source_paths(self) -> list[Path]:
        """Returns paths to scan for source code, handling COEM overrides."""
        paths = []

        def _append(path: Path) -> None:
            if path.exists() and path not in paths:
                paths.append(path)

        # COEM specific overrides. If a workspace has no COEM source override,
        # fall back to its common/core source tree.
        local_src = self.workspace_dir / "coem"
        if local_src.exists():
            _append(local_src)
        else:
            _append(self.workspace_dir / "common")
            _append(self.workspace_dir / "code")
            
        # Base common code
        if self.base_workspace:
            for path in self.base_workspace.get_source_paths():
                _append(path)
            
        return paths

    def get_requirements_schema(self) -> dict:
        """Loads and merges YAML requirements from the workspace."""
        req_dir = self.workspace_dir / "requirements"
        schemas = {}
        
        # Load base requirements
        if self.base_workspace:
            schemas.update(self.base_workspace.get_requirements_schema())
            
        # Override with local requirements
        if req_dir.exists():
            for req_file in req_dir.glob("*.yaml"):
                with open(req_file, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                # Key by 'feature' (V3 schema, aligned with M3/M8); fall back to
                # legacy 'function' for backward compatibility.
                if isinstance(data, dict):
                    key = data.get("feature") or data.get("function")
                    if key:
                        schemas[key] = data
                        
        return schemas
