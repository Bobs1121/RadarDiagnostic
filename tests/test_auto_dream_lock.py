# -*- coding: utf-8 -*-
"""Targeted tests for AutoDream lock-file handling."""
from __future__ import annotations

import os
from pathlib import Path

from memory.auto_dream import AutoDream


def _stub_dream(lock_path: Path) -> AutoDream:
    dream = AutoDream.__new__(AutoDream)
    dream.lock_path = lock_path
    return dream


def test_auto_dream_lock_with_active_pid_stays_locked(tmp_path: Path) -> None:
    lock_path = tmp_path / ".dream-lock"
    lock_path.write_text(str(os.getpid()), encoding="utf-8")

    dream = _stub_dream(lock_path)

    assert dream._is_locked() is True
    assert lock_path.exists()


def test_auto_dream_lock_with_stale_pid_releases_immediately(tmp_path: Path) -> None:
    lock_path = tmp_path / ".dream-lock"
    lock_path.write_text("99999999", encoding="utf-8")

    dream = _stub_dream(lock_path)

    assert dream._is_locked() is False
    assert not lock_path.exists()


def test_auto_dream_lock_with_non_pid_uses_age_fallback(tmp_path: Path) -> None:
    lock_path = tmp_path / ".dream-lock"
    lock_path.write_text("unknown-owner", encoding="utf-8")

    dream = _stub_dream(lock_path)

    assert dream._is_locked() is True
    assert lock_path.exists()
