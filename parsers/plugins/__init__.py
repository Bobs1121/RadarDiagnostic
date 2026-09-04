# -*- coding: utf-8 -*-
"""
Parser plugins package.

Each supported format is a :class:`ParserPlugin` registered under its file
extension via ``@PluginRegistry.register("parser", ext)``. Importing this
package triggers registration of the built-in bag / blf / mf4 plugins.
"""
from __future__ import annotations

from typing import Optional, Type

from core.plugin import PluginRegistry, discover
from parsers.plugins.base import ParserContext, ParserPlugin, ParserResult

# Import plugin modules so their @register decorators run.
from parsers.plugins import bag_plugin  # noqa: F401
from parsers.plugins import blf_plugin  # noqa: F401
from parsers.plugins import mf4_plugin  # noqa: F401


def get_parser_plugin(extension: str) -> Optional[Type[ParserPlugin]]:
    """Return a registered parser plugin class for ``extension`` (e.g. ".bag")."""
    return PluginRegistry.get("parser", extension.lower())


def registered_extensions() -> list[str]:
    return PluginRegistry.registered("parser")


# Re-export the discovery helper scoped to this package.
def discover_parser_plugins(*, on_error=None) -> None:
    discover("parsers.plugins", on_error=on_error)


__all__ = [
    "ParserContext", "ParserPlugin", "ParserResult",
    "get_parser_plugin", "registered_extensions", "discover_parser_plugins",
]