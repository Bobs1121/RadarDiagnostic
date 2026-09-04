# -*- coding: utf-8 -*-
"""
parsers.providers — V4 P2 数据源统一接入层。

按文件类型分发到对应 Provider，底层仍复用现有 BagParser / BlfParser /
Mf4Parser / DbcLoader 解析逻辑，Provider 只做"按类型路由 + 元数据收集 +
溯源"的统一封装。

导入入口：
    from parsers.providers import BagProvider, BlfProvider, Mf4Provider
    from parsers.providers import DbcProvider, CodeRepoProvider
    from parsers.providers.base import DataProvider, LoadConfig
"""
from __future__ import annotations

from .base import DataProvider, LoadConfig, ProvenanceRecord
from .bag_provider import BagProvider
from .blf_provider import BlfProvider
from .mf4_provider import Mf4Provider
from .dbc_provider import DbcProvider
from .code_repo_provider import CodeRepoProvider

#: 文件扩展名 → Provider 类 的注册表（case_loader 可按扩展名取用）
PROVIDER_REGISTRY: dict[str, type[DataProvider]] = {
    ".bag": BagProvider,
    ".blf": BlfProvider,
    ".mf4": Mf4Provider,
}


def get_provider_class(ext: str) -> type[DataProvider] | None:
    """按文件扩展名返回 Provider 类，未注册返回 None（fail-soft）。"""
    return PROVIDER_REGISTRY.get(ext.lower())


__all__ = [
    "DataProvider",
    "LoadConfig",
    "ProvenanceRecord",
    "BagProvider",
    "BlfProvider",
    "Mf4Provider",
    "DbcProvider",
    "CodeRepoProvider",
    "PROVIDER_REGISTRY",
    "get_provider_class",
]
