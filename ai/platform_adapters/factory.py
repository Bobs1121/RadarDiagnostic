# -*- coding: utf-8 -*-
"""
Platform Adapters —— Factory + 自动注册。

根据 platform_id 加载对应的适配器实现。
新增 Gen7/Gen8 只需实现 BaseAdapter 子类 + 注册即可，不需要修改任何调度代码。

本实现委托给统一注册表 :class:`core.plugin.PluginRegistry`，并支持通过
``PluginRegistry.discover()`` 自动发现适配器模块（替换旧的硬编码导入列表）。
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from core.plugin import PluginRegistry
from .base import (
    BaseCodeLearnerAdapter,
    BaseConditionExtractorAdapter,
    BaseSignalMapperAdapter,
)

# 适配器 kind 常量（统一注册表命名空间）。
_KIND_CL = "platform_code_learner"
_KIND_CE = "platform_condition_extractor"
_KIND_SM = "platform_signal_mapper"


def register_code_learner(platform_id: str):
    return PluginRegistry.register(_KIND_CL, platform_id)


def register_condition_extractor(platform_id: str):
    return PluginRegistry.register(_KIND_CE, platform_id)


def register_signal_mapper(platform_id: str):
    return PluginRegistry.register(_KIND_SM, platform_id)


# ── Lazy-load adapters (avoid circular imports) ──────────────────────

_adapter_modules_loaded = False


def _ensure_adapters_loaded() -> None:
    """自动发现 adapter 模块，触发 @register 装饰器执行。

    通过 ``PluginRegistry.discover`` 遍历 ``ai.platform_adapters`` 包内模块，
    取代旧的硬编码 ``from . import gen6_symmetry / gen5_reco_pl`` 列表。
    """
    global _adapter_modules_loaded
    if _adapter_modules_loaded:
        return

    def _on_err(exc: Exception) -> None:
        import logging
        logging.getLogger(__name__).error(
            "Platform adapter module failed to import (will be ignored): %s", exc,
        )

    # 先显式导入已知实现（确定性），再自动发现补全第三方/新平台适配器。
    from . import gen6_symmetry  # noqa: F401
    from . import gen5_reco_pl   # noqa: F401
    PluginRegistry.discover("ai.platform_adapters", on_error=_on_err)
    _adapter_modules_loaded = True


# ── Public factories ─────────────────────────────────────────────────

def get_code_learner_adapter(
    platform_id: str,
    source_root: Path,
    config: dict,
    project_root: Path,
) -> BaseCodeLearnerAdapter:
    _ensure_adapters_loaded()
    cls = PluginRegistry.get(_KIND_CL, platform_id)
    if not cls:
        raise KeyError(
            f"No CodeLearnerAdapter for platform '{platform_id}'. "
            f"Registered: {PluginRegistry.registered(_KIND_CL)}"
        )
    return cls(source_root, config, project_root)


def get_condition_extractor_adapter(
    platform_id: str,
    source_root: Path,
    config: dict,
    project_root: Path,
) -> BaseConditionExtractorAdapter:
    _ensure_adapters_loaded()
    cls = PluginRegistry.get(_KIND_CE, platform_id)
    if not cls:
        raise KeyError(
            f"No ConditionExtractorAdapter for platform '{platform_id}'. "
            f"Registered: {PluginRegistry.registered(_KIND_CE)}"
        )
    return cls(source_root, config, project_root)


def get_signal_mapper_adapter(
    platform_id: str,
    source_root: Path,
    output_dir: Path,
    config: dict,
    project_root: Path,
) -> BaseSignalMapperAdapter:
    _ensure_adapters_loaded()
    cls = PluginRegistry.get(_KIND_SM, platform_id)
    if not cls:
        # Fallback: use default (gen6-style) signal mapper
        return _default_signal_mapper(source_root, output_dir, config, project_root)
    return cls(source_root, output_dir, config, project_root)


# Default (gen6-style) signal-mapper fallback for unregistered platforms.
def _default_signal_mapper(source_root, output_dir, config, project_root):
    from .gen6_symmetry import _SignalMapperDefault
    return _SignalMapperDefault(source_root, output_dir, config, project_root)