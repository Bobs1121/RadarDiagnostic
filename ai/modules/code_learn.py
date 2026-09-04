# -*- coding: utf-8 -*-
"""CodeLearnModule (V4 P5) — 代码学习：激活 AST 索引构建 / 重索引 / 按需检索。

对应 P5 ``code_learn.py``：把源码建成 CodeGraph（默认 AST，可回退 regex），
再对其做按需检索。供 pi 调度在分析前主动建图 / 增量刷新。

独立运行::

    python cli.py code-learn --aggressive   # AST 全量重建当前 variant 的 codegraph
    python cli.py code-learn --rebuild      # 忽略增量，强制全量重建
    python cli.py code-learn --no-ast       # 强制 regex 建图（AST 不可用时自动回退）
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .base import BaseModule, ModuleResult

log = logging.getLogger(__name__)


def _config_paths(cfg: dict):
    """从 config 中提取 source_root / key_files / calib_files / source_docs_dir。"""
    source_root = Path(cfg.get("paths", {}).get("source_code") or ".")
    key_files = list(cfg.get("paths", {}).get("key_source_files", []) or [])
    calib_files = [
        p for p in key_files
        if "paraDefine" in p or "structDefine" in p or "globalVarDefine" in p
    ]
    source_docs_dir = None
    try:
        from config import resolve_source_docs_dir
        source_docs_dir = resolve_source_docs_dir(cfg, Path.cwd())
    except Exception:  # noqa: BLE001
        pass
    return source_root, key_files, calib_files, source_docs_dir


class CodeLearnModule(BaseModule):
    name = "code-learn"
    description = "代码学习：AST 建图 / 增量刷新 CodeGraph（P5 入口）"

    def __init__(self, *, db_path: str = "", source_root: str = "",
                 variable_filter: Any = None):
        self.db_path = Path(db_path) if db_path else None
        self.source_root = source_root
        self.variable_filter = variable_filter

    def run(
        self,
        *,
        rebuild: bool = False,
        use_ast: bool = True,
        aggressive: bool = False,
        no_ast: bool = False,
        **_: Any,
    ) -> ModuleResult:
        if no_ast:
            use_ast = False
        if aggressive:
            rebuild = True
            use_ast = True

        from .code_analyze import CodeAnalyzeModule  # 复用 db 解析

        cfg = self._load_config()
        if cfg is None:
            return ModuleResult.fail("无法加载 config", module=self.name)

        source_root, key_files, calib_files, source_docs_dir = _config_paths(cfg)
        if self.source_root:
            source_root = Path(self.source_root)
        if not key_files and source_root.exists():
            # 未配置 key_files 时，退化为轻量 regex 建库
            log.warning("code-learn: 无 key_source_files，将全量扫描源码目录")
            # Keep the no-config path usable for a newly onboarded project.
            # The helper is intentionally generic and returns relative source
            # paths; the old name did not exist and made this fallback fail
            # before CodeGraphBuilder could start.
            key_files = self._build_candidates(source_root)

        if not self.db_path:
            try:
                from config import resolve_codegraph_db
                self.db_path = resolve_codegraph_db(cfg, Path.cwd())
            except Exception:  # noqa: BLE001
                return ModuleResult.fail(
                    "无法解析 codegraph db 路径", module=self.name
                )
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        if rebuild and self.db_path.exists():
            self.db_path.unlink()  # 强制全量重建
            log.info("code-learn: --rebuild，删除旧 DB 强制全量")

        func_keywords = self._load_func_keywords()

        try:
            from ai.codegraph import CodeGraphBuilder
        except Exception as exc:  # noqa: BLE001
            return ModuleResult.fail(
                f"CodeGraphBuilder 导入失败: {exc}", module=self.name
            )

        var_filter = self.variable_filter
        if var_filter is None:
            try:
                from config import get_variable_filter
                var_filter = get_variable_filter(cfg)
            except Exception:  # noqa: BLE001
                var_filter = None

        builder = CodeGraphBuilder(
            db_path=self.db_path,
            source_root=source_root,
            key_files=key_files,
            func_keywords=func_keywords,
            calib_files=calib_files,
            use_ast=use_ast,
            source_docs_dir=source_docs_dir,
            variable_filter=var_filter,
        )
        result = builder.build()

        if not result.success:
            return ModuleResult.fail(
                f"codegraph build failed: {result.error}", module=self.name
            )
        return ModuleResult.success(
            message=(
                f"code-learn: {result.build_type} "
                f"(+{result.nodes_added} nodes, +{result.edges_added} edges, "
                f"{result.duration_sec:.1f}s)"
            ),
            module=self.name,
            build_type=result.build_type,
            nodes_added=result.nodes_added,
            edges_added=result.edges_added,
            files_scanned=result.files_scanned,
            files_changed=result.files_changed,
            duration_sec=result.duration_sec,
        )

    # ------------------------------------------------------------------

    def _load_config(self):
        try:
            from config import load_config
            return load_config()
        except Exception:  # noqa: BLE001
            return None

    @staticmethod
    def _load_func_keywords() -> dict:
        try:
            from ai.code_learner import FUNC_KEYWORDS
            return dict(FUNC_KEYWORDS)
        except Exception:  # noqa: BLE001
            return dict()

    @staticmethod
    def _build_candidates(source_root: Path) -> list[str]:
        """无 key_files 时的轻量兜底：找源码根下的 .c/.cpp/.h 相对路径。"""
        exts = {".c", ".cpp", ".h", ".hpp"}
        out: list[str] = []
        for root, _dirs, files in source_root.walk():
            for fn in files:
                if Path(fn).suffix.lower() in exts:
                    rel = root.relative_to(source_root)
                    out.append(rel.joinpath(fn).as_posix())
            if len(out) > 800:
                break
        return out

    @classmethod
    def register_cli(cls, subparsers):
        p = super().register_cli(subparsers)
        p.add_argument("--rebuild", action="store_true",
                       help="删除旧 DB 强制全量重建")
        p.add_argument("--aggressive", action="store_true",
                       help="AST 全量重建（等价 --rebuild + --ast）")
        p.add_argument("--no-ast", action="store_true",
                       help="强制使用 regex，不使用 AST")
        p.add_argument("--source-root", default="", help="覆盖源码根目录")
        p.add_argument("--db-path", default="", help="codegraph.db 路径覆盖")
        p.set_defaults(_module_cls=cls)
        return p

    @classmethod
    def from_cli_args(cls, args: Any) -> "CodeLearnModule":
        return cls(db_path=getattr(args, "db_path", ""),
                   source_root=getattr(args, "source_root", ""))


__all__ = ["CodeLearnModule"]
