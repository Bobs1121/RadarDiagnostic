# -*- coding: utf-8 -*-
"""
CodeGraph: 确定性代码知识图谱 — 用户无感的后台静态分析引擎。

自动在 orchestrator Step 1 中增量构建，不新增 CLI 命令，不改变诊断行为。
"""
from .builder import CodeGraphBuilder
from .query import CodeGraph
from .render import CodeGraphRenderer

__all__ = ["CodeGraphBuilder", "CodeGraph", "CodeGraphRenderer"]
