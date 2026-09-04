# -*- coding: utf-8 -*-
"""
CodeRepoProvider — 源码仓数据源 Provider（V4 P2）。

source_docs/codegraph 的深度索引由 ai/code_learner 与
engines/codegraph 负责（V4 设计文档分层），本 Provider 只做**轻量
存在性 + 指纹**：确认 source_root 是否存在、是否是 git 仓、当前
HEAD commit，供 :func:`engines.data_availability.classify_availability`
判定 has_source。

本 Provider 不修改 git 仓（不 fetch/pull/checkout，与 AGENTS.md
"source-context validation ... never mutate" 一致），只读 HEAD 信息。
"""
from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from .base import DataProvider

if TYPE_CHECKING:
    from parsers.frame_store import FrameStore


class CodeRepoProvider(DataProvider):
    """源码仓数据源 Provider（轻量存在性 + HEAD 指纹）。"""

    source_kind = "code_repo"

    def load(self, path: Path, store: "FrameStore") -> dict:
        if not path.exists():
            self.ctx.status("parse", f"Source root not found: {path}")
            self._record(
                file=str(path),
                parser="CodeRepoProvider",
                message_count=0,
                size_mb=0.0,
                duration_sec=0.0,
                extra={"exists": False},
            )
            return {}

        is_git = (path / ".git").exists()
        head_commit = ""
        branch = ""
        dirty = False
        if is_git:
            head_commit = self._git_rev_parse(path)
            branch = self._git_branch(path)
            dirty = self._git_dirty(path)

        meta = {
            "source_root": str(path),
            "is_git_repo": is_git,
            "head_commit": head_commit,
            "branch": branch,
            "dirty": dirty,
        }
        self._record(
            file=str(path),
            parser="CodeRepoProvider",
            message_count=0,
            size_mb=self._dir_size_mb(path),
            duration_sec=0.0,
            extra=meta,
        )
        return meta

    def provenance(self) -> list[dict]:
        return [p.to_dict() for p in self._provenance]

    # ── git 只读辅助（绝不 mutate）──────────────────────────────────
    @staticmethod
    def _git_rev_parse(root: Path) -> str:
        try:
            out = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=str(root), capture_output=True, text=True, timeout=10,
            )
            if out.returncode == 0:
                return out.stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            pass
        return ""

    @staticmethod
    def _git_branch(root: Path) -> str:
        try:
            out = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=str(root), capture_output=True, text=True, timeout=10,
            )
            if out.returncode == 0:
                return out.stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            pass
        return ""

    @staticmethod
    def _git_dirty(root: Path) -> bool:
        try:
            out = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=str(root), capture_output=True, text=True, timeout=10,
            )
            return bool(out.stdout.strip())
        except (OSError, subprocess.TimeoutExpired):
            return False

    @staticmethod
    def _dir_size_mb(root: Path) -> float:
        """Best-effort 目录大小（仅统计顶层 .c/.h 文件，避免全量遍历）。"""
        total = 0
        try:
            for ext in ("*.c", "*.h", "*.cpp", "*.hpp"):
                for fp in root.rglob(ext):
                    try:
                        total += fp.stat().st_size
                    except OSError:
                        continue
        except OSError:
            pass
        return total / 1024 / 1024
