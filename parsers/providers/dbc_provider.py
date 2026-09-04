# -*- coding: utf-8 -*-
"""
DbcProvider — DBC (CAN 数据库) 数据源 Provider（V4 P2）。

封装现有 :class:`parsers.dbc_loader.DbcLoader`：加载 DBC 文件，产出
DbcLoader 实例（不写 store——DBC 是元数据，不是时间序列）。

设计说明：
- DbcLoader 构造期即消费所有路径并按"首文件优先"解析冲突（见
  ``parsers/dbc_loader.py`` L17-L58）；本 Provider 不重新实现合并逻辑，
  只在 ``ctx.dbc`` 为空时构造一次 loader，后续 DBC 文件仅记录溯源，
  实际合并由 case_loader 在 load_case_data 入口统一做（见
  ``parsers/case_loader.py`` _resolve_dbc_paths + DbcLoader 构造）。
- 这样避免触碰 DbcLoader 的私有属性，保持 fail-soft 与可测性。
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from .base import DataProvider

if TYPE_CHECKING:
    from parsers.frame_store import FrameStore


class DbcProvider(DataProvider):
    """DBC (.dbc) CAN 数据库数据源 Provider。"""

    source_kind = "dbc"

    def load(self, path: Path, store: "FrameStore") -> dict:
        from parsers.dbc_loader import DbcLoader

        if not path.exists():
            self.ctx.status("parse", f"DBC not found: {path}")
            return {}

        # 仅在 ctx.dbc 为空时构造 loader；case_loader 的统一入口已经
        # 用 _resolve_dbc_paths + DbcLoader(...) 处理了多文件合并，
        # 这里只对单独 DBC 文件做溯源记录。
        loader = self.ctx.dbc
        if loader is None:
            loader = DbcLoader([path], base_dir=self.ctx.project_root)
            self.ctx.dbc = loader

        meta = {
            "file": path.name,
            "message_count": len(loader.known_ids),
            "conflicts": loader.conflicts,
        }
        self._record(
            file=path.name,
            parser="DbcProvider/DbcLoader",
            message_count=meta["message_count"],
            size_mb=self._file_size_mb(path),
            duration_sec=0.0,
            extra={
                "known_ids": len(loader.known_ids),
                "conflicts": len(loader.conflicts),
            },
        )
        return meta

    def provenance(self) -> list[dict]:
        return [p.to_dict() for p in self._provenance]
