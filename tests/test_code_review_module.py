# -*- coding: utf-8 -*-
"""Offline tests for the M7 code-review standalone module."""
from __future__ import annotations

import argparse
import textwrap

from ai.modules.base import BaseModule, ModuleResult
from ai.modules.code_review import CodeReviewModule


def test_code_review_module_is_base_subclass_with_name():
    assert issubclass(CodeReviewModule, BaseModule)
    assert CodeReviewModule.name == "code-review"


def test_code_review_diff_detects_embedded_c_risks():
    diff_text = textwrap.dedent("""\
        --- a/src/demo.c
        +++ b/src/demo.c
        @@ -10,2 +10,4 @@
         void demo(void) {
        +    strcpy(dst, src);
        +    /* TODO: remove debug path */
         }
    """)
    module = CodeReviewModule(syntax_enabled=False)

    result = module.safe_run(diff_text=diff_text)

    assert isinstance(result, ModuleResult)
    assert result.ok is True
    assert result.module == "code-review"
    assert result.data["summary"]["finding_count"] == 2
    assert result.data["summary"]["severity_counts"]["critical"] == 1
    assert result.data["summary"]["severity_counts"]["info"] == 1
    assert result.data["summary"]["syntax_status"] == "skipped"
    assert any(
        finding["category"] == "unsafe-function"
        and finding["symbol"] == "strcpy"
        and finding["line"] == 11
        and finding["source"] == "src/demo.c"
        for finding in result.data["findings"]
    )
    assert any(
        finding["category"] == "todo-marker"
        and finding["line"] == 12
        for finding in result.data["findings"]
    )


def test_code_review_file_scan_and_injected_syntax_runner(tmp_path):
    file_path = tmp_path / "alarm.c"
    file_path.write_text(
        "void review(void) {\n"
        "    sprintf(buf, \"%s\", src);\n"
        "}\n",
        encoding="utf-8",
    )
    calls: list[str] = []

    def fake_runner(path):
        calls.append(str(path))
        return {"status": "pass", "message": ""}

    module = CodeReviewModule(syntax_runner=fake_runner)

    result = module.safe_run(file_path=str(file_path))

    assert result.ok is True
    assert result.data["summary"]["finding_count"] == 1
    assert result.data["summary"]["syntax_status"] == "pass"
    assert result.data["syntax"]["checked_files"] == [str(file_path)]
    assert result.data["syntax"]["errors"] == []
    assert calls == [str(file_path)]
    assert result.data["inputs"]["reviewed_files"] == [str(file_path)]


def test_code_review_skips_syntax_when_tool_unavailable(tmp_path, monkeypatch):
    file_path = tmp_path / "alarm.c"
    file_path.write_text("void review(void) {}\n", encoding="utf-8")
    module = CodeReviewModule()
    monkeypatch.setattr(module, "_discover_syntax_tool", lambda: None)

    result = module.safe_run(file_path=str(file_path))

    assert result.ok is True
    assert result.data["summary"]["syntax_status"] == "skipped"
    assert result.data["syntax"]["checked_files"] == []
    assert result.data["syntax"]["skipped_files"] == [
        {"file": str(file_path), "reason": "tool-unavailable"}
    ]


def test_code_review_requires_reviewable_input():
    result = CodeReviewModule(syntax_enabled=False).safe_run()

    assert result.ok is False
    assert "no reviewable input" in result.message.lower()


def test_code_review_safe_run_wraps_runner_exception(tmp_path):
    file_path = tmp_path / "alarm.c"
    file_path.write_text("void review(void) {}\n", encoding="utf-8")

    def exploding_runner(_path):
        raise RuntimeError("boom")

    result = CodeReviewModule(syntax_runner=exploding_runner).safe_run(
        file_path=str(file_path),
    )

    assert result.ok is False
    assert "RuntimeError: boom" in result.message


def test_code_review_cli_wiring(tmp_path):
    diff_file = tmp_path / "demo.diff"
    diff_file.write_text(
        "--- a/a.c\n+++ b/a.c\n@@ -1 +1,2 @@\n+strcpy(dst, src);\n",
        encoding="utf-8",
    )

    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers()
    CodeReviewModule.register_cli(sub)
    args = parser.parse_args([
        "code-review",
        "--diff-file", str(diff_file),
        "--file-path", "src\\a.c",
        "--file-path", "src\\b.c",
        "--no-syntax-check",
        "--syntax-tool", "clang",
    ])

    assert args._module_cls is CodeReviewModule
    assert args.diff_file == str(diff_file)
    assert args.file_paths == ["src\\a.c", "src\\b.c"]
    assert args.no_syntax_check is True
    assert args.syntax_tool == "clang"

    module = CodeReviewModule.from_cli_args(args)
    assert isinstance(module, CodeReviewModule)
    assert module._syntax_enabled is False
    assert module._syntax_tool == "clang"
