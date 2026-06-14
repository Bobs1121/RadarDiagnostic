# -*- coding: utf-8 -*-
"""
Snapshot store — persistent storage for diagnostic snapshots.

Provides create/load/list/delete operations for Snapshot objects.
Snapshots are stored as JSON files under memory/snapshots/.

Directory layout:
    memory/snapshots/
        snap-abcdef123456.json
        snap-xyz789abcdef.json

Each snapshot file is a self-contained JSON with the full Snapshot.to_dict() output.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from core.identity import Snapshot

log = logging.getLogger(__name__)


class SnapshotStore:
    """File-based snapshot store.

    Args:
        snapshots_dir: Directory to store snapshot JSON files.
                       Defaults to project_root/memory/snapshots/.
    """

    def __init__(self, snapshots_dir: Optional[Path] = None):
        if snapshots_dir is None:
            snapshots_dir = Path(__file__).parent.parent / "memory" / "snapshots"
        self.snapshots_dir = snapshots_dir
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path:
        """Path to a specific snapshot file."""
        return self.snapshots_dir

    def _snapshot_path(self, snapshot_id: str) -> Path:
        """Return the file path for a snapshot ID."""
        return self.snapshots_dir / f"{snapshot_id}.json"

    def save(self, snapshot: Snapshot) -> Path:
        """Save a snapshot to disk. Returns the file path."""
        path = self._snapshot_path(snapshot.snapshot_id)
        snapshot.save(path)
        log.info("Snapshot saved: %s -> %s", snapshot.snapshot_id, path)
        return path

    def load(self, snapshot_id: str) -> Snapshot:
        """Load a snapshot by ID. Raises FileNotFoundError if not found."""
        path = self._snapshot_path(snapshot_id)
        if not path.exists():
            raise FileNotFoundError(f"Snapshot not found: {snapshot_id} at {path}")
        return Snapshot.load(path)

    def list(self) -> list[dict]:
        """List all snapshots (returns minimal metadata for each)."""
        results = []
        for f in sorted(self.snapshots_dir.glob("snap-*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                results.append({
                    "snapshot_id": data.get("snapshot_id", f.stem),
                    "variant_id": data.get("variant_id", ""),
                    "created_at": data.get("created_at", ""),
                    "package_profile_id": data.get("package_profile_id"),
                })
            except (json.JSONDecodeError, KeyError):
                log.warning("Failed to read snapshot file: %s", f)
        return results

    def delete(self, snapshot_id: str) -> bool:
        """Delete a snapshot by ID. Returns True if deleted."""
        path = self._snapshot_path(snapshot_id)
        if path.exists():
            path.unlink()
            log.info("Snapshot deleted: %s", snapshot_id)
            return True
        return False
