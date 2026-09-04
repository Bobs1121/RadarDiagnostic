# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path

from ai.modules import MODULE_REGISTRY
from ai.modules.code_context import CodeContextReadModule, CodeContextRefreshModule
from engines.code_context import (
    build_code_context,
    extract_source_conditions,
    query_code_context,
)


def _write_fixture(root: Path, *, extra: str = "") -> None:
    source = root / "src" / "logic.c"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(
        "#define ALERT_THRESHOLD 3\n"
        "static int helper(int frame_counter) { return frame_counter; }\n"
        "int gate(int frame_counter) {\n"
        "  if (frame_counter > ALERT_THRESHOLD) {\n"
        "    return helper(frame_counter);\n"
        "  }\n"
        "  return 0;\n"
        "}\n"
        + extra,
        encoding="utf-8",
    )


def test_code_context_builds_generic_index_and_reuses_snapshot(tmp_path: Path):
    source_root = tmp_path / "source"
    output_dir = tmp_path / "context"
    _write_fixture(source_root)

    first = build_code_context(
        source_root=source_root,
        output_dir=output_dir,
        use_ast=False,
    )
    assert first["schema_version"] == "code-context.v1"
    assert first["operation"] == "built"
    assert first["source_context"]["snapshot_hash"]
    assert first["summary"]["files"] == 1
    assert Path(first["artifacts"]["code_index"]).exists()

    index = json.loads(Path(first["artifacts"]["code_index"]).read_text(encoding="utf-8"))
    assert index["schema_version"] == "code-index.v1"
    assert {row["name"] for row in index["functions"]} >= {"gate", "helper"}
    assert "gate" in index["calls"]
    assert "helper" in index["calls"]["gate"]

    second = build_code_context(
        source_root=source_root,
        output_dir=output_dir,
        use_ast=False,
    )
    assert second["operation"] == "reused"
    assert second["current_snapshot_hash"] == first["source_context"]["snapshot_hash"]


def test_code_context_accepts_same_line_function_braces(tmp_path: Path):
    source_root = tmp_path / "source"
    output_dir = tmp_path / "context"
    _write_fixture(source_root, extra="int same_line(int value) { return value; }\n")

    context = build_code_context(source_root=source_root, output_dir=output_dir, use_ast=False)
    index = json.loads(Path(context["artifacts"]["code_index"]).read_text(encoding="utf-8"))
    assert "same_line" in {row["name"] for row in index["functions"]}


def test_source_condition_index_preserves_nested_parentheses(tmp_path: Path):
    source_root = tmp_path / "source"
    _write_fixture(
        source_root,
        extra=(
            "int nested(int frame_counter)\n"
            "{\n"
            "  if ((frame_counter > 0) && (frame_counter < 5))\n"
            "  {\n"
            "    return 1;\n"
            "  }\n"
            "  return 0;\n"
            "}\n"
        ),
    )
    source_file = source_root / "src" / "logic.c"
    lines = source_file.read_text(encoding="utf-8").splitlines()
    nested_start = lines.index("int nested(int frame_counter)") + 1
    conditions = extract_source_conditions(
        source_root=source_root,
        file_manifest=[{"path": "src/logic.c", "sha256": "fixture"}],
        functions=[
            {"name": "nested", "file_path": "src/logic.c", "start_line": nested_start, "end_line": len(lines)}
        ],
    )
    assert source_file.exists()
    nested = [row for row in conditions if row["function"] == "nested"]
    assert nested
    assert "frame_counter < 5" in nested[0]["expression"]


def test_code_context_read_is_bounded_and_does_not_need_source_scan(tmp_path: Path):
    source_root = tmp_path / "source"
    output_dir = tmp_path / "context"
    _write_fixture(source_root)
    context = build_code_context(source_root=source_root, output_dir=output_dir, use_ast=False)

    result = query_code_context(
        context["artifacts"]["code_context"],
        section="functions",
        query="gate",
        limit=1,
    )
    assert result["section"] == "functions"
    assert len(result["data"]) == 1
    assert result["data"][0]["name"] == "gate"

    module_result = CodeContextReadModule().safe_run(
        context_path=context["artifacts"]["code_context"],
        section="parameters",
    )
    assert module_result.ok
    assert module_result.data["index_path"] == context["artifacts"]["code_index"]


def test_code_context_rebuilds_after_source_change_but_rejects_other_root(tmp_path: Path):
    source_root = tmp_path / "source"
    output_dir = tmp_path / "context"
    _write_fixture(source_root)
    first = build_code_context(source_root=source_root, output_dir=output_dir, use_ast=False)

    source_file = source_root / "src" / "logic.c"
    source_file.write_text(
        source_file.read_text(encoding="utf-8") + "int newly_added(int value) { return value; }\n",
        encoding="utf-8",
    )
    rebuilt = build_code_context(source_root=source_root, output_dir=output_dir, use_ast=False)
    assert rebuilt["operation"] == "built"
    assert rebuilt["source_context"]["snapshot_hash"] != first["source_context"]["snapshot_hash"]

    other_root = tmp_path / "other-source"
    _write_fixture(other_root)
    blocked = CodeContextRefreshModule().safe_run(
        source_root=str(other_root), output_dir=str(output_dir), use_ast=False
    )
    assert not blocked.ok
    assert blocked.data["error_type"] == "CodeContextError"


def test_code_context_module_is_pi_registered_and_invalid_root_is_clean_failure(tmp_path: Path):
    assert MODULE_REGISTRY["code-context-refresh"] is CodeContextRefreshModule
    assert MODULE_REGISTRY["code-context-read"] is CodeContextReadModule

    result = CodeContextRefreshModule().safe_run(
        source_root=str(tmp_path / "missing"),
        output_dir=str(tmp_path / "context"),
    )
    assert not result.ok
    assert result.data["error_type"] == "CodeContextError"
