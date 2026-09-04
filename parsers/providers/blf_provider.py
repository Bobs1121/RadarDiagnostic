# -*- coding: utf-8 -*-
"""
BlfProvider — BLF (Binary Log File, CAN bus) 数据源 Provider（V4 P2）。

封装现有 :class:`parsers.blf_parser.BlfParser`：用 DBC 解码 CAN 信号，
写入 FrameStore.can_frames。Provider 不重新实现解码逻辑，只做"按文件
加载 + 元数据收集 + 溯源"的统一封装。
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from .base import DataProvider

if TYPE_CHECKING:
    from parsers.frame_store import FrameStore


class BlfProvider(DataProvider):
    """BLF (.blf) CAN 日志数据源 Provider。"""

    source_kind = "blf"

    def load(self, path: Path, store: "FrameStore") -> dict:
        from parsers.blf_parser import BlfParser

        if not path.exists():
            self.ctx.status("parse", f"BLF not found: {path}")
            return {}

        # 优先走 ParserPlugin SPI（若已注册），保持与 case_loader 一致；
        # 否则走 legacy BlfParser 直连。
        try:
            from parsers.plugins import get_parser_plugin  # noqa: WPS433
            from parsers.plugins.base import ParserContext
            _has_plugins = True
        except Exception:
            _has_plugins = False

        plugin = get_parser_plugin(".blf") if _has_plugins else None
        if plugin is not None:
            pctx = ParserContext(
                config=self.ctx.config, project_root=self.ctx.project_root,
                workspace=self.ctx.workspace, dbc=self.ctx.dbc,
                on_status=self.ctx.on_status,
            )
            pres = plugin().load(path, store, pctx)
            meta = pres.metadata or {}
        else:
            parser = BlfParser(path, dbc_loader=self.ctx.dbc)
            meta = parser.get_metadata()
            store.bulk_insert_can(parser.iter_frames(decode=True))

        self._record(
            file=path.name,
            parser="BlfProvider/BlfParser",
            message_count=meta.get("message_count", 0),
            size_mb=self._file_size_mb(path),
            duration_sec=meta.get("duration_sec", 0.0),
            extra={
                "unique_can_ids": meta.get("unique_can_ids", 0),
                "start_time": meta.get("start_time"),
                "end_time": meta.get("end_time"),
            },
        )
        return meta

    def provenance(self) -> list[dict]:
        return [p.to_dict() for p in self._provenance]
