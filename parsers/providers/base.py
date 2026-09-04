# -*- coding: utf-8 -*-
"""
DataProvider SPI — 统一多源数据接入契约（V4 P2）。

将 bag / blf / mf4 / dbc / code_repo 五类异构数据源收口到同一抽象：
每个 Provider 负责把自己那部分解析逻辑封装好，产出 CaseLoadResult
片段（store + meta），并向下游暴露数据来源溯源信息（provenance）。

设计原则：
- **不重复造解析**：底层仍复用现有 BagParser / BlfParser / Mf4Parser /
  DbcLoader，Provider 只是把"按文件类型分发 + 元数据收集 + 溯源"做成
  可插拔的统一入口。
- **可独立可测**：每个 Provider 不依赖 orchestrator，可被 case_loader
  组合调用，也可被单元测试单独实例化。
- **数据质量旁路**：Provider 不直接判占位/恒定值（那是
  :class:`engines.data_quality.DataQualityAuditor` 的职责），但要在
  provenance 里声明 source_kind / file / 解析器版本，方便后续审计。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, Protocol, runtime_checkable

if TYPE_CHECKING:
    from core.workspace import Workspace
    from parsers.case_loader import CaseLoadResult
    from parsers.frame_store import FrameStore


# ── 状态回调类型 ──────────────────────────────────────────────────────
# 复用 case_loader 既有的 (step, detail) 二元回调约定，避免引入新协议。
StatusCallback = Optional[callable]


@dataclass
class LoadConfig:
    """跨 Provider 共享的加载上下文（轻量、可演化）。

    把 case_loader.load_case_data 现有入参显式打包，避免 Provider 各自
    重新声明一串参数；后续新增字段不破坏已有 Provider。
    """

    config: dict
    project_root: Path
    case_dir: Optional[Path] = None
    workspace: "Optional[Workspace]" = None
    dbc: Any = None  # DbcLoader 实例（BLF / MF4 需要）
    on_status: StatusCallback = None

    def status(self, step: str, detail: str = "") -> None:
        if self.on_status:
            self.on_status(step, detail)


@dataclass
class ProvenanceRecord:
    """单条数据来源溯源记录。

    字段保持扁平、JSON 可序列化，便于写入 source_docs / 报告。
    """

    source_kind: str  # bag | blf | mf4 | dbc | code_repo
    file: str = ""
    parser: str = ""  # 实际解析器类名，如 "BagParser"
    message_count: int = 0
    size_mb: float = 0.0
    duration_sec: float = 0.0
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "source_kind": self.source_kind,
            "file": self.file,
            "parser": self.parser,
            "message_count": self.message_count,
            "size_mb": round(self.size_mb, 3),
            "duration_sec": round(self.duration_sec, 3),
            "extra": self.extra,
        }


class DataProvider(ABC):
    """数据源统一 SPI。

    子类必须声明 :attr:`source_kind`（用于 availability 分类与溯源），
    并实现 :meth:`load` 与 :meth:`provenance`。

    生命周期约定：
    1. case_loader 在开始解析前，按文件类型实例化对应 Provider；
    2. 对每个匹配文件调用 ``load``，Provider 把数据写入 *store* 并返回
       自己产出的 metadata 片段（可为空 dict）；
    3. 全部加载完成后，case_loader 汇总各 Provider 的 ``provenance``
       写入 CaseLoadResult（见 :func:`parsers.case_loader.load_case_data`
       的 availability 挂点）。

    **fail-soft 契约**：load 遇到单文件损坏/依赖缺失时记录 warning 并
    返回空 meta，**不得 raise**——保持与现有 case_loader 的优雅降级行为
    一致（见 PARALLEL_DEV_BOUNDARIES：现有 load_case_data 已优雅处理缺失
    文件，务必保持不 raise）。
    """

    #: 数据源类型标识，子类覆盖为 ``"bag"`` / ``"blf"`` 等。
    source_kind: str = ""

    def __init__(self, ctx: LoadConfig):
        self.ctx = ctx
        self._provenance: list[ProvenanceRecord] = []

    @abstractmethod
    def load(self, path: Path, store: "FrameStore") -> dict:
        """解析单个 *path* 写入 *store*，返回该文件的 metadata 片段。

        实现要求：
        - 对缺失/损坏文件 fail-soft（记 warning，返回 ``{}``）；
        - 把解析器实例名、文件大小、消息数等填入 provenance。
        """
        raise NotImplementedError

    @abstractmethod
    def provenance(self) -> list[dict]:
        """返回本 Provider 本次 load 产生的所有溯源记录（list[dict]）。"""
        raise NotImplementedError

    # ── 共享工具 ─────────────────────────────────────────────────────

    def _record(self, **kwargs) -> None:
        """子类在 load 成功后调用，追加一条溯源记录。"""
        kwargs.setdefault("source_kind", self.source_kind)
        self._provenance.append(ProvenanceRecord(**kwargs))

    @staticmethod
    def _file_size_mb(path: Path) -> float:
        try:
            return path.stat().st_size / 1024 / 1024
        except OSError:
            return 0.0
