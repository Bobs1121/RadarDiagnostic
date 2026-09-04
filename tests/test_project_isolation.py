# -*- coding: utf-8 -*-
"""P6 · 多项目适配 + 记忆/数据隔离测试（V4_PI_BASED_PLAN Slice P6）。

验收（对应计划）：
1. 两个不同 variant 并行解析上下文，workspace/记忆/索引路径不串扰；
2. 跨项目禁止回退到其他项目知识（fail closed，guard_project 抛错）；
3. 会话/资源绑定项目，隔离正确（路径 belongs 断言）。

这些测试是离线/确定性：不触发 LLM、不读真实数据，只用 ``tmp_path`` 构造
隔离目录 + 真实 config 解析器。运行::

    pytest tests/test_project_isolation.py -v
"""
from __future__ import annotations

from pathlib import Path

import pytest

from ai.capability import (
    ProjectContext,
    ProjectIsolationError,
    guard_project,
    resolve_project_context,
    resolve_project_context_from_case,
)
import config as config_module


# 两份最小但结构真实（含 source_context/workspace_dir 覆盖）的 variant 配置
def _base_config() -> dict:
    return {
        "default_variant": "gen6/gwm_b26",
        "codebases": {
            "legacy": {"root_path": str(Path("/fake/source/gwm")), "platform_id": "gen6_c_radar"},
            "cr60_light": {"root_path": str(Path("/fake/source/byd")), "platform_id": "gen6_c_radar"},
        },
        "variants": {
            "gen6/gwm_b26": {
                "codebase_id": "legacy",
                "customer": "GWM",
                "vehicle_project": "B26",
            },
            "gen6/byd_sc6h": {
                "codebase_id": "cr60_light",
                "customer": "BYD",
                "vehicle_project": "SC6H",
            },
            "gen6/byd_uke_em2e_index_8": {
                "codebase_id": "cr60_light",
                "customer": "BYD",
                "vehicle_project": "UKE",
            },
        },
    }


def test_two_variants_resolve_to_disjoint_workspaces(tmp_path: Path) -> None:
    """两个 variant 的 workspace/memory/索引路径互不重合。"""
    cfg = _base_config()
    a = resolve_project_context(cfg, tmp_path, variant_id="gen6/gwm_b26")
    b = resolve_project_context(cfg, tmp_path, variant_id="gen6/byd_sc6h")

    assert a.variant_id == "gen6/gwm_b26"
    assert b.variant_id == "gen6/byd_sc6h"
    assert a.workspace_dir != b.workspace_dir, "workspace 必须按 variant 隔离"
    assert a.memory_dir != b.memory_dir
    assert a.codegraph_db != b.codegraph_db
    assert a.source_docs_dir != b.source_docs_dir
    assert a.snapshots_dir != b.snapshots_dir
    # 每个 workspace 落在 tmp_path/.workspaces/<variant>/（按 variant 命名隔离）
    assert a.workspace_dir.parent == tmp_path / ".workspaces"
    assert b.workspace_dir.parent == tmp_path / ".workspaces"
    assert a.workspace_dir.name != b.workspace_dir.name


def test_namespace_differs_across_variants(tmp_path: Path) -> None:
    cfg = _base_config()
    a = resolve_project_context(cfg, tmp_path, variant_id="gen6/byd_sc6h")
    b = resolve_project_context(cfg, tmp_path, variant_id="gen6/byd_uke_em2e_index_8")
    assert a.namespace() != b.namespace(), "记忆/会话命名空间必须按项目区分"


def test_guard_project_accepts_own_region_rejects_foreign(tmp_path: Path) -> None:
    """fail-closed：属于本项目的路径放行；其他项目的路径拒绝。"""
    cfg = _base_config()
    own = resolve_project_context(cfg, tmp_path, variant_id="gen6/byd_sc6h")
    other = resolve_project_context(cfg, tmp_path, variant_id="gen6/gwm_b26")

    own_region = own.memory_dir / "sub" / "file.json"
    own_region.parent.mkdir(parents=True, exist_ok=True)
    # 本项目路径 -> 放行
    assert guard_project(own, own_region) is True
    # 空路径 -> 放行（无可引用）
    assert guard_project(own, None) is True

    # 别的项目路径 -> 拒绝（默认 raise）
    with pytest.raises(ProjectIsolationError):
        guard_project(own, other.memory_dir / "knowledge_manifest.json")

    # on_mismatch="ignore" 不抛，仅返回 False
    assert guard_project(own, other.workspace_dir, on_mismatch="ignore") is False


def test_resolve_project_context_from_case_metadata(tmp_path: Path) -> None:
    """case 目录带 case.yaml(identity.variant) 时按 metadata 绑定项目。"""
    cfg = _base_config()
    case_dir = tmp_path / "CASE001"
    case_dir.mkdir()
    (case_dir / "case.yaml").write_text(
        "identity:\n  variant: sc6h\n", encoding="utf-8"
    )
    ctx = resolve_project_context_from_case(cfg, tmp_path, case_dir)
    assert ctx.variant_id == "gen6/byd_sc6h"


def test_default_variant_fallback_without_case_metadata(tmp_path: Path) -> None:
    """无 metadata 的 case 回退 default_variant。"""
    cfg = _base_config()
    empty_case = tmp_path / "EMPTY"
    empty_case.mkdir()
    ctx = resolve_project_context_from_case(cfg, tmp_path, empty_case)
    assert ctx.variant_id == "gen6/gwm_b26"  # default_variant


def test_context_to_dict_is_json_serializable(tmp_path: Path) -> None:
    import json

    cfg = _base_config()
    ctx = resolve_project_context(cfg, tmp_path, variant_id="gen6/byd_sc6h")
    d = ctx.to_dict()
    json.dumps(d)  # 不抛即序列化通过
    assert isinstance(d["workspace_dir"], str)
    assert d["variant_id"] == "gen6/byd_sc6h"