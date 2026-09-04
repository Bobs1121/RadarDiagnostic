# -*- coding: utf-8 -*-
"""Stage 2 tests: unified plugin framework (core/plugin.py + parsers/plugins)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ── core.plugin.PluginRegistry ─────────────────────────────────────────────

class TestPluginRegistry:
    def test_register_and_get(self):
        from core.plugin import PluginRegistry

        PluginRegistry.clear("kind_a")
        @PluginRegistry.register("kind_a", "key1")
        class _P:
            pass

        assert PluginRegistry.get("kind_a", "key1") is _P
        assert PluginRegistry.get("kind_a", "missing") is None

    def test_registered_lists_keys(self):
        from core.plugin import PluginRegistry

        PluginRegistry.clear("kind_a")
        PluginRegistry.clear("kind_b")
        @PluginRegistry.register("kind_b", "x")
        class _Px:
            pass
        @PluginRegistry.register("kind_b", "y")
        class _Py:
            pass

        assert PluginRegistry.registered("kind_b") == ["x", "y"]
        assert PluginRegistry.registered("kind_a") == []

    def test_clear_resets_one_kind_only(self):
        import parsers.plugins  # noqa: F401  — ensure built-in parser plugins registered
        from core.plugin import PluginRegistry

        PluginRegistry.clear("kind_c")
        @PluginRegistry.register("kind_c", "k")
        class _P:
            pass
        assert PluginRegistry.get("kind_c", "k") is not None
        # Clearing one kind must NOT wipe the built-in parser plugins.
        assert PluginRegistry.get("parser", ".bag") is not None
        PluginRegistry.clear("kind_c")
        assert PluginRegistry.get("kind_c", "k") is None
        assert PluginRegistry.get("parser", ".bag") is not None

    def test_module_level_aliases(self):
        from core import plugin as m

        assert m.register is m.PluginRegistry.register
        assert m.get is m.PluginRegistry.get
        assert m.clear is m.PluginRegistry.clear


# ── parsers.plugins ────────────────────────────────────────────────────────

class TestParserPlugins:
    def test_builtin_formats_registered(self):
        from parsers.plugins import get_parser_plugin, registered_extensions

        for ext in (".bag", ".blf", ".mf4"):
            assert get_parser_plugin(ext) is not None
        assert set(registered_extensions()) >= {".bag", ".blf", ".mf4"}

    def test_blf_plugin_degrades_on_malformed(self, tmp_path: Path):
        from parsers.plugins.blf_plugin import BlfParserPlugin
        from parsers.frame_store import FrameStore
        from parsers.plugins.base import ParserContext

        # A plugin must not raise on an empty file; it degrades to a warning.
        f = tmp_path / "x.blf"
        f.write_bytes(b"")
        store = FrameStore(":memory:")
        ctx = ParserContext(config={}, project_root=tmp_path, on_status=None)
        res = BlfParserPlugin().load(f, store, ctx)
        assert res is not None
        if res.metadata is None:
            assert res.warnings, "expected a warning for malformed BLF"

    def test_mf4_plugin_degrades_on_malformed(self, tmp_path: Path):
        from parsers.plugins.mf4_plugin import Mf4ParserPlugin
        from parsers.frame_store import FrameStore
        from parsers.plugins.base import ParserContext

        f = tmp_path / "x.mf4"
        f.write_bytes(b"not-an-mf4")
        store = FrameStore(":memory:")
        ctx = ParserContext(config={}, project_root=tmp_path, on_status=None)
        res = Mf4ParserPlugin().load(f, store, ctx)
        # Plugin must not raise on malformed input — degrades to a warning.
        assert res is not None
        if res.metadata is None:
            assert res.warnings, "expected a warning for malformed MF4"

    def test_case_loader_routes_blf_through_plugin(self, tmp_path: Path, monkeypatch):
        """case_loader uses the registry for .blf (no DbcLoader when no DBC)."""
        from parsers import case_loader
        from parsers import blf_parser as _blf_mod

        case_dir = tmp_path / "case"
        case_dir.mkdir()
        (case_dir / "capture.blf").write_bytes(b"")
        project_root = tmp_path / "project"
        project_root.mkdir()

        captured = {}

        class FakeBlfParser:
            def __init__(self, blf_path, dbc_loader=None):
                captured["dbc_loader"] = dbc_loader
            def get_metadata(self):
                return {"file": "capture.blf"}
            def iter_frames(self, decode=True):
                return []

        def fail_dbc(*a, **k):
            raise AssertionError("DbcLoader should not be constructed")

        monkeypatch.setattr(case_loader, "DbcLoader", fail_dbc)
        monkeypatch.setattr(_blf_mod, "BlfParser", FakeBlfParser)

        class _StubWS:
            def get_dbc_files(self):
                return []

        result = case_loader.load_case_data(
            case_dir, {"paths": {"dbc_files": []}}, project_root,
            workspace=_StubWS(),
        )
        assert result.dbc is None
        assert captured["dbc_loader"] is None
        assert result.blf_meta == {"file": "capture.blf"}