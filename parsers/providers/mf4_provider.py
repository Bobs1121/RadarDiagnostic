# -*- coding: utf-8 -*-
"""
Mf4Provider — MF4 (ASAM MFD4 测量文件) 数据源 Provider（V4 P2）。

封装现有 :class:`parsers.mf4_parser.Mf4Parser`：把测量通道数据写入
FrameStore.can_frames。Provider 不重新实现通道交织/解码，只做统一接入
与溯源。
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from .base import DataProvider

if TYPE_CHECKING:
    from parsers.frame_store import FrameStore


class Mf4Provider(DataProvider):
    """MF4 (.mf4) 测量文件数据源 Provider。"""

    source_kind = "mf4"

    def load(self, path: Path, store: "FrameStore") -> dict:
        from parsers.mf4_parser import Mf4Parser, check_mf4_dependency

        if not path.exists():
            self.ctx.status("parse", f"MF4 not found: {path}")
            return {}

        # 优先走 ParserPlugin SPI（若已注册），否则 legacy Mf4Parser 直连。
        try:
            from parsers.plugins import get_parser_plugin
            from parsers.plugins.base import ParserContext
            _has_plugins = True
        except Exception:
            _has_plugins = False

        plugin = get_parser_plugin(".mf4") if _has_plugins else None
        warnings: list[str] = []
        if plugin is not None:
            pctx = ParserContext(
                config=self.ctx.config, project_root=self.ctx.project_root,
                workspace=self.ctx.workspace, dbc=self.ctx.dbc,
                on_status=self.ctx.on_status,
            )
            pres = plugin().load(path, store, pctx)
            meta = pres.metadata or {}
            warnings = pres.warnings or []
        else:
            if not check_mf4_dependency():
                msg = (f"MF4 {path.name} found but asammdf/mffparser "
                       f"not installed — skipping")
                self.ctx.status("parse", msg)
                warnings.append(msg)
                self._record(
                    file=path.name, parser="Mf4Provider/Mf4Parser",
                    message_count=0, size_mb=self._file_size_mb(path),
                    duration_sec=0.0, extra={"skipped": "missing_dependency"},
                )
                return {}
            parser = Mf4Parser(path)
            meta = parser.get_metadata()
            parser.write_to_store(store)

        self._record(
            file=path.name,
            parser="Mf4Provider/Mf4Parser",
            message_count=meta.get("sample_count", 0),
            size_mb=self._file_size_mb(path),
            duration_sec=meta.get("duration_sec", 0.0),
            extra={
                "channel_count": meta.get("channel_count", 0),
                "start_time": meta.get("start_time"),
                "end_time": meta.get("end_time"),
                "warnings": warnings,
            },
        )
        return meta

    def provenance(self) -> list[dict]:
        return [p.to_dict() for p in self._provenance]
