# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import hashlib
from pathlib import Path
import pytest

from ai.modules import MODULE_REGISTRY
from ai.modules.code_context import CodeContextReadModule, CodeContextRefreshModule
from engines.code_context import (
    build_code_context,
    CodeContextError,
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
    assert first["artifacts"]["code_index_sha256"] == hashlib.sha256(
        Path(first["artifacts"]["code_index"]).read_bytes()
    ).hexdigest()

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

    index_path = Path(first["artifacts"]["code_index"])
    index_path.write_text(index_path.read_text(encoding="utf-8") + " ", encoding="utf-8")
    rebuilt = build_code_context(
        source_root=source_root,
        output_dir=output_dir,
        use_ast=False,
    )
    assert rebuilt["operation"] == "built"
    assert rebuilt["artifacts"]["code_index_sha256"] == hashlib.sha256(index_path.read_bytes()).hexdigest()


def test_code_context_read_rejects_index_tampering(tmp_path: Path):
    source_root = tmp_path / "source"
    output_dir = tmp_path / "context"
    _write_fixture(source_root)
    context = build_code_context(source_root=source_root, output_dir=output_dir, use_ast=False)
    index_path = Path(context["artifacts"]["code_index"])
    index_path.write_text(index_path.read_text(encoding="utf-8") + " ", encoding="utf-8")

    with pytest.raises(CodeContextError, match="file hash does not match"):
        query_code_context(context["artifacts"]["code_context"], section="summary")


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


def test_code_context_uses_and_hashes_variant_output_mapping_sources(tmp_path: Path, monkeypatch):
    source_root = tmp_path / "source"
    output_dir = tmp_path / "context"
    _write_fixture(source_root)
    mapping_dir = source_root / "coem" / "BYD_SC6H" / "components" / "AswIf" / "ASW_ComMapping"
    mapping_dir.mkdir(parents=True)
    tx_path = mapping_dir / "RteComMapping_Tx.c"
    sgu_path = mapping_dir / "RteComMapping_TxSGU.c"
    tx_path.write_text("void tx(void) { }\n", encoding="utf-8")
    sgu_path.write_text("void tx_sgu(void) { }\n", encoding="utf-8")
    # A different COEM is present so a legacy/default choice would be visible.
    gwm_path = source_root / "coem" / "GWM_B26" / "components" / "AswIf" / "ASW_IN" / "RteComMapping.c"
    gwm_path.parent.mkdir(parents=True)
    gwm_path.write_text("void write_gwm(void) { }\n", encoding="utf-8")

    calls = []

    def fake_extract(source, _output, rte_file):
        calls.append((str(rte_file), source))
        return {
            "source_hash": "fixture-output-map",
            "mappings": [{"can_signal": "Warn", "expression": "fctaWarning"}],
            "signal_to_expr": {"Warn": ["fctaWarning"]},
        }

    monkeypatch.setattr("engines.signal_mapper.extract_output_signal_mapping", fake_extract)
    first = build_code_context(
        source_root=source_root,
        output_dir=output_dir,
        key_files=["src/logic.c"],
        source_identity={"coem": "BYD_SC6H"},
        use_ast=False,
    )
    assert calls[0][0] == "coem/BYD_SC6H/components/AswIf/ASW_ComMapping/RteComMapping_Tx.c"
    first_hash = first["source_context"]["snapshot_hash"]
    first_paths = {row["path"] for row in first["source_context"]["files"]}
    assert "coem/BYD_SC6H/components/AswIf/ASW_ComMapping/RteComMapping_Tx.c" in first_paths
    assert "coem/BYD_SC6H/components/AswIf/ASW_ComMapping/RteComMapping_TxSGU.c" in first_paths
    assert "coem/GWM_B26/components/AswIf/ASW_IN/RteComMapping.c" not in first_paths
    assert first["source_context"]["output_mapping_selection"] == "coem_identity"

    sgu_path.write_text("void tx_sgu(void) { return; }\n", encoding="utf-8")
    rebuilt = build_code_context(
        source_root=source_root,
        output_dir=output_dir,
        key_files=["src/logic.c"],
        source_identity={"coem": "BYD_SC6H"},
        use_ast=False,
    )
    assert rebuilt["operation"] == "built"
    assert rebuilt["source_context"]["snapshot_hash"] != first_hash


def test_code_context_does_not_fall_back_to_another_coem_mapping(tmp_path: Path, monkeypatch):
    source_root = tmp_path / "source"
    output_dir = tmp_path / "context"
    output_dir.mkdir()
    stale_mapping = output_dir / "output_mapping.json"
    stale_mapping.write_text(
        json.dumps({"source_hash": "stale-gwm", "mappings": [{"can_signal": "GWM_Warn"}], "signal_to_expr": {}}),
        encoding="utf-8",
    )
    _write_fixture(source_root)
    gwm_path = source_root / "coem" / "GWM_B26" / "components" / "AswIf" / "ASW_IN" / "RteComMapping.c"
    gwm_path.parent.mkdir(parents=True)
    gwm_path.write_text("void write_gwm(void) { }\n", encoding="utf-8")

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("missing BYD mapping must not fall back to GWM")

    monkeypatch.setattr("engines.signal_mapper.extract_output_signal_mapping", fail_if_called)
    context = build_code_context(
        source_root=source_root,
        output_dir=output_dir,
        key_files=["src/logic.c"],
        source_identity={"coem": "BYD_SC6H"},
        use_ast=False,
    )
    index = json.loads(Path(context["artifacts"]["code_index"]).read_text(encoding="utf-8"))
    assert context["source_context"]["output_mapping_selection"] == "coem_mapping_unavailable"
    assert context["source_context"]["output_mapping_files"] == []
    assert index["output_mapping"]["selection_status"] == "coem_mapping_not_found"
    assert index["output_mapping"]["mappings"] == []
    disk_mapping = json.loads(stale_mapping.read_text(encoding="utf-8"))
    assert disk_mapping["selection_status"] == "coem_mapping_not_found"
    assert disk_mapping["mappings"] == []


def test_code_context_module_forwards_explicit_output_mapping_file(tmp_path: Path, monkeypatch):
    captured = {}

    def fake_build(**kwargs):
        captured.update(kwargs)
        return {
            "schema_version": "code-context.v1",
            "context_id": "context-1",
            "source_context": {},
            "artifacts": {"code_context": str(tmp_path / "code-context.json")},
            "summary": {},
            "operation": "built",
        }

    monkeypatch.setattr("ai.modules.code_context.build_code_context", fake_build)
    result = CodeContextRefreshModule().safe_run(
        source_root=str(tmp_path),
        output_mapping_rte_file="coem/BYD_SC6H/RteComMapping_Tx.c",
    )
    assert result.ok
    assert captured["output_mapping_rte_file"] == "coem/BYD_SC6H/RteComMapping_Tx.c"
    assert "output_mapping_rte_file" in CodeContextRefreshModule.input_schema["properties"]


def test_code_context_without_variant_identity_does_not_use_legacy_gwm_mapping(tmp_path: Path, monkeypatch):
    source_root = tmp_path / "source"
    output_dir = tmp_path / "context"
    _write_fixture(source_root)
    gwm_path = source_root / "coem" / "GWM_B26" / "components" / "AswIf" / "ASW_IN" / "RteComMapping.c"
    gwm_path.parent.mkdir(parents=True)
    gwm_path.write_text("void write_gwm(void) { }\n", encoding="utf-8")

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("missing variant identity must not use a legacy default")

    monkeypatch.setattr("engines.signal_mapper.extract_output_signal_mapping", fail_if_called)
    context = build_code_context(
        source_root=source_root,
        output_dir=output_dir,
        key_files=["src/logic.c"],
        use_ast=False,
    )
    index = json.loads(Path(context["artifacts"]["code_index"]).read_text(encoding="utf-8"))
    assert context["source_context"]["output_mapping_selection"] == "coem_identity_required"
    assert context["source_context"]["output_mapping_files"] == []
    assert index["output_mapping"]["selection_status"] == "coem_identity_required"
    assert index["output_mapping"]["mappings"] == []
