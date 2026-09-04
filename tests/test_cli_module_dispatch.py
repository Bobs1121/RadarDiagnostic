# -*- coding: utf-8 -*-
"""Offline tests for V3 standalone-module CLI dispatch."""
from __future__ import annotations

from typing import Any

from ai.modules import MODULE_REGISTRY
from ai.modules.base import BaseModule, ModuleResult
from ai.modules.code_review import CodeReviewModule
from cli import _run_module_subcommand


class _TypedDummyModule(BaseModule):
    name = "typed-dummy"
    description = "typed dummy"
    last_kwargs: dict[str, Any] = {}

    def run(self, **kwargs: Any) -> ModuleResult:
        type(self).last_kwargs = kwargs
        return ModuleResult.success(module=self.name, **kwargs)

    @classmethod
    def register_cli(cls, subparsers: Any) -> Any:
        parser = super().register_cli(subparsers)
        parser.add_argument("--count", type=int, required=True)
        parser.add_argument("--flag", action="store_true")
        parser.add_argument("--mode", choices=["a", "b"], default="a")
        return parser


def test_module_dispatch_preserves_argparse_action_semantics(monkeypatch):
    monkeypatch.setitem(MODULE_REGISTRY, _TypedDummyModule.name, _TypedDummyModule)

    rc = _run_module_subcommand(
        ["typed-dummy", "--count", "7", "--flag", "--mode", "b"]
    )

    assert rc == 0
    assert _TypedDummyModule.last_kwargs["count"] == 7
    assert isinstance(_TypedDummyModule.last_kwargs["count"], int)
    assert _TypedDummyModule.last_kwargs["flag"] is True
    assert _TypedDummyModule.last_kwargs["mode"] == "b"


def test_registry_includes_pr2_standalone_modules():
    expected = {
        "agent-loop",
        "code-query",
        "data-explore",
        "signal-bridge",
        "diagnosis-panel",
        "code-review",
        "project-init",
    }

    assert expected.issubset(set(MODULE_REGISTRY))


def test_module_dispatch_preserves_append_actions(monkeypatch, tmp_path):
    reviewed: dict[str, object] = {}

    def fake_safe_run(self, **kwargs):
        reviewed.update(kwargs)
        return ModuleResult.success(module=self.name, seen=kwargs)

    monkeypatch.setattr(CodeReviewModule, "safe_run", fake_safe_run)

    rc = _run_module_subcommand([
        "code-review",
        "--file-path", str(tmp_path / "a.c"),
        "--file-path", str(tmp_path / "b.c"),
        "--no-syntax-check",
    ])

    assert rc == 0
    assert reviewed["file_paths"] == [
        str(tmp_path / "a.c"),
        str(tmp_path / "b.c"),
    ]
    assert reviewed["no_syntax_check"] is True


def test_module_dispatch_runs_agent_loop_with_safe_real_tool():
    rc = _run_module_subcommand([
        "agent-loop",
        "--objective", "preview warning signal",
        "--tool-call",
        '{"tool":"plot_signal","params":{"message_name":"ADASWarnMsg","signal_name":"WarnCAN"}}',
    ])

    assert rc == 0
