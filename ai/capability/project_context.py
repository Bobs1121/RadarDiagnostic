# -*- coding: utf-8 -*-
"""project_context — V4 P6 多项目上下文解析与隔离门禁。

把"variant / project_key / case_dir"解析为可用的项目上下文（代码/数据/索引/
记忆/workspace），为多项目隔离打底：

* 每个项目绑定的 workspace / 索引 / 记忆路径都隔离到 ``.workspaces/<variant>/``，
  不会跨项目混用；
* :func:`guard_project` 提供 **fail-closed** 断言：当某个资源实际落在别的项目
  workspace 下时，明确抛错拒绝，而不是静默回退到其他项目知识（P6 验收红线）。

设计上**不复制** config 的路径解析逻辑，而是复用 ``config.resolve_*`` 系列函数，
保证与 orchestrator / pi_bridge 单一来源一致。
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger(__name__)


class ProjectIsolationError(RuntimeError):
    """跨项目引用被拒绝时抛出（fail-closed 门禁）。"""


@dataclass
class ProjectContext:
    """一个项目（variant）的隔离绑定。所有字段均为解析后的路径。"""

    variant_id: str
    project_root: Path
    project_key: str = ""                 # 旧式 project_key（可空）
    workspace_dir: Path = field(default_factory=Path)
    codegraph_db: Path = field(default_factory=Path)
    source_docs_dir: Path = field(default_factory=Path)
    memory_dir: Path = field(default_factory=Path)
    snapshots_dir: Path = field(default_factory=Path)

    def to_dict(self) -> dict[str, Any]:
        """JSON 友好序列化；用于共享/展示/断言。"""
        d = asdict(self)
        for k, v in d.items():
            if isinstance(v, Path):
                d[k] = str(v)
        return d

    def namespace(self) -> str:
        """项目隔离命名空间：以 memory 目录名（sanitized variant）作 key。"""
        return self.memory_dir.name if self.memory_dir.name else self.variant_id

    def contains(self, path: str | Path | None) -> bool:
        """判断给定路径是否属于本项目隔离区（fail-closed 门禁用）。"""
        if path is None:
            return True
        p = Path(path).expanduser()
        try:
            p = p.resolve()
            mem = self.memory_dir.resolve()
            wsp = self.workspace_dir.resolve()
            return p.is_relative_to(mem) or p.is_relative_to(wsp)
        except (ValueError, OSError):
            return False


def resolve_project_context(
    config: dict,
    project_root: str | Path,
    variant_id: str | None = None,
    project_key: str | None = None,
) -> ProjectContext:
    """把 variant / project_key 解析为隔离的 :class:`ProjectContext`。

    复用 ``config`` 的路径解析函数，与 orchestrator / pi_bridge 完全一致。
    variant_id 优先，其次 project_key，最后 default_variant。
    """
    from config import (
        resolve_codegraph_db,
        resolve_memory_dir,
        resolve_snapshots_dir,
        resolve_source_docs_dir,
        resolve_workspace_dir,
        resolve_variant_id,
    )

    root = Path(project_root)
    eff_variant = variant_id
    if not eff_variant and project_key:
        eff_variant = resolve_variant_id(config, project_key)
    if not eff_variant:
        eff_variant = resolve_variant_id(config, None)

    return ProjectContext(
        variant_id=eff_variant,
        project_root=root,
        project_key=project_key or "",
        workspace_dir=resolve_workspace_dir(config, root, project_key=project_key,
                                            variant_id=eff_variant),
        codegraph_db=resolve_codegraph_db(config, root, project_key=project_key,
                                          variant_id=eff_variant),
        source_docs_dir=resolve_source_docs_dir(config, root, project_key=project_key,
                                                variant_id=eff_variant),
        memory_dir=resolve_memory_dir(config, root, project_key=project_key,
                                      variant_id=eff_variant),
        snapshots_dir=resolve_snapshots_dir(config, root, project_key=project_key,
                                            variant_id=eff_variant),
    )


def resolve_project_context_from_case(
    config: dict,
    project_root: str | Path,
    case_dir: str | Path,
) -> ProjectContext:
    """从案例目录推断项目 variant 并加载上下文。

    复用 ``cli._resolve_variant_from_case_metadata``（读 case.yaml / metadata.json
    匹配 variant）；无法识别时回退 default_variant。
    """
    vid = None
    try:
        import cli as _cli
        meta = _cli._resolve_variant_from_case_metadata(config, case_dir)
        if meta and meta.get("variant_id"):
            vid = meta["variant_id"]
    except Exception:  # noqa: BLE001 - 无法识别则不绑定，回退 default
        vid = None
    if vid:
        return resolve_project_context(config, project_root, variant_id=vid)
    return resolve_project_context(config, project_root)


def guard_project(
    ctx: ProjectContext,
    path: str | Path | None,
    *,
    what: str = "资源",
    on_mismatch: str = "raise",
) -> bool:
    """fail-closed 门禁：断言 ``path`` 属于项目 ``ctx`` 隔离区。

    ``on_mismatch="raise"``（默认）：不属于本项目时抛 :class:`ProjectIsolationError`。
    传 ``"ignore"`` 时仅返回 ``False``。用于防止跨项目回退到其他项目记忆/索引。
    """
    if ctx.contains(path):
        return True
    if on_mismatch == "raise":
        raise ProjectIsolationError(
            f"{what} 属于其他项目，禁止跨项目引用: {path} (project={ctx.variant_id})"
        )
    return False


__all__ = [
    "ProjectContext",
    "ProjectIsolationError",
    "resolve_project_context",
    "resolve_project_context_from_case",
    "guard_project",
]