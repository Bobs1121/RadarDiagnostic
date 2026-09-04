# -*- coding: utf-8 -*-
"""
Unified plugin registry for radarAnalyze.

Provides a single decorator-driven registry + automatic package discovery so
that new parsers / platform adapters / codegraph backends / memory backends can
be added WITHOUT editing dispatch code (see docs/production/31-software-architecture.md §2).

Usage::

    from core.plugin import PluginRegistry

    @PluginRegistry.register("parser", ".bag")
    class BagParserPlugin(ParserPlugin):
        ...

    plugin_cls = PluginRegistry.get("parser", ".bag")

Discovery replaces the hardcoded import lists (e.g. the old
``ai/platform_adapters/factory.py:53-61``) with ``PluginRegistry.discover(pkg)``.
"""
from __future__ import annotations

import importlib
import pkgutil
from typing import Any, Callable, Optional, Type

# Maps f"{kind}:{key}" -> plugin class.
_REGISTRY: dict[str, type[Any]] = {}


class PluginRegistry:
    """Decorator-driven registry + automatic package discovery."""

    @staticmethod
    def register(kind: str, key: str):
        """Return a decorator that registers a class under ``kind`` + ``key``."""

        def deco(cls: Type[Any]) -> Type[Any]:
            _REGISTRY[f"{kind}:{key}"] = cls
            return cls

        return deco

    @staticmethod
    def get(kind: str, key: str) -> Optional[Type[Any]]:
        """Return a registered plugin class (or None)."""
        return _REGISTRY.get(f"{kind}:{key}")

    @staticmethod
    def registered(kind: str) -> list[str]:
        """List all keys registered under ``kind``."""
        prefix = f"{kind}:"
        return sorted(k[len(prefix):] for k in _REGISTRY if k.startswith(prefix))

    @staticmethod
    def clear(kind: Optional[str] = None) -> None:
        """Reset the registry.

        With no ``kind``, clears everything (use only in tests). With a ``kind``,
        only clears plugins of that kind — safe for tests that register their own
        kinds without wiping built-in plugins (e.g. parser plugins).
        """
        if kind is None:
            _REGISTRY.clear()
            return
        prefix = f"{kind}:"
        for k in [k for k in _REGISTRY if k.startswith(prefix)]:
            _REGISTRY.pop(k, None)

    @staticmethod
    def discover(
        package: str,
        *,
        on_error: Optional[Callable[[BaseException], None]] = None,
    ) -> None:
        """Import every module under ``package``, triggering decorators.

        Replaces hardcoded import lists. ``on_error`` (if given) is called with
        the exception for a module that fails to import; otherwise errors propagate.
        """
        try:
            pkg = importlib.import_module(package)
        except Exception:
            if on_error:
                return
            raise
        for mod in pkgutil.iter_modules(pkg.__path__):
            if mod.name.startswith("_"):
                continue
            try:
                importlib.import_module(f"{package}.{mod.name}")
            except Exception as exc:  # pragma: no cover - defensive
                if on_error:
                    on_error(exc)
                else:
                    raise


# Backward-compatible module-level aliases.
register = PluginRegistry.register
get = PluginRegistry.get
registered = PluginRegistry.registered
clear = PluginRegistry.clear
discover = PluginRegistry.discover