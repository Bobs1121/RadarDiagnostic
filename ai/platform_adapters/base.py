# -*- coding: utf-8 -*-
"""
Platform Adapters: 插件式平台适配层，使分析工具在 Gen5 ReCo 和 Gen6 Symmetry
两种完全不同的代码架构之间自动切换。

设计原则：
  1. 统一接口 —— 每种"智能模块"（code_learner / condition_extractor / signal_mapper）
     都有一个对应的 BaseAdapter 定义统一方法签名
  2. 职责分离 —— Gen5/Gen6 的特定逻辑只存在于各自的 adapter 实现中，
     调度层（code_learner.py 等）只做 dispatch，不碰 if/elif
  3. 配置驱动 —— PlatformFamily 在 config.yaml 中指定 platform_id，
     Orchestrator 根据 platform_id 加载对应 adapter

架构映射:
  Gen6 Symmetry (C 单体):
    - 单一 adasFunc.c 包含所有功能逻辑
    - RteComMapping.c 做 CAN 信号 ↔ 内部变量映射
    - paraDefine.h 放所有阈值常量
    - 单一函数内 if-else 状态机 (0-6 states)

  Gen5 ReCo (C++ Flux/DADDY 分布式):
    - 661+ 文件分散在 PER/SIT/FCT/HMI 多层架构
    - 无 RteComMapping —— 输出直接到 DADDY 通道 或 MF4 信号
    - PAD XML/Header 文件定义阈值 (padfct_s_par_gen.h 等)
    - PSS StateMachine<T> 模板 + 每个功能独立 StateMachine
    - Flux XML 定义组件拓扑 (11 flux files)
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional


# ====================================================================
# Base Adapter Interface
# ====================================================================


class BaseCodeLearnerAdapter(ABC):
    """CodeLearner 的平台适配器接口。

    CodeLearner 通过此接口获取 Gen5/Gen6 特定的：
      - 关键文件列表 (key_source_files)
      - 源码领域分布 (source_domains)
      - 焦点文件映射 (focus_files)
      - 功能关键字 (func_keywords)
      - 常量文件 (constants_files)
      - AI Prompt 模板 (prompt_templates)
    """

    @abstractmethod
    def get_key_source_files(self) -> list[str]:
        """返回所有功能的汇总关键源码文件列表。"""
        ...

    @abstractmethod
    def get_source_domains(self) -> dict[str, list[str]]:
        """返回按功能域划分的源码文件映射。

        返回格式: {domain_name: [relative_path, ...]}
        """
        ...

    @abstractmethod
    def get_focus_files(self, focus: str) -> list[str]:
        """返回给定 focus (alarm_logic/calculation_chain/...) 需要扫描的文件。"""
        ...

    @abstractmethod
    def get_func_keywords(self, func: str) -> list[str]:
        """返回给定功能的代码关键字列表（用于片段抽取）。"""
        ...

    @abstractmethod
    def get_constants_source_files(self) -> list[str]:
        """返回包含数值常量的源头文件。"""
        ...

    @abstractmethod
    def build_prompt_template(self, focus: str) -> dict[str, str]:
        """返回该平台特有的学习 prompt 模板。

        返回 {"system": "...", "user_template": "..."}
        user_template 中应包含 {func} 和 {snippets} 占位符。
        """
        ...

    @abstractmethod
    def build_overview_prompt(self) -> tuple[str, str]:
        """返回概览文档生成的 system/user prompt 对。"""
        ...

    @abstractmethod
    def get_priority_functions(self) -> list[str]:
        """返回优先学习功能列表。"""
        ...

    @abstractmethod
    def get_focuses(self) -> list[str]:
        """返回支持的焦点类型列表。"""
        ...


class BaseConditionExtractorAdapter(ABC):
    """ConditionExtractor 的平台适配器接口。"""

    @abstractmethod
    def get_source_domains(self) -> dict[str, list[str]]:
        """返回条件提取所需的源码领域分布。"""
        ...

    @abstractmethod
    def get_extraction_prompt(self, func_name: str) -> tuple[str, str]:
        """返回条件提取的 system/user prompt。

        user prompt 应包含 {func_name} 和 {source_code} 占位符。
        """
        ...

    @abstractmethod
    def get_func_keywords(self, func: str) -> list[str]:
        """返回条件提取用到的功能关键字。"""
        ...

    @abstractmethod
    def format_conditions(self, conditions: dict) -> str:
        """将提取的条件格式化为可读文本。不同平台的条件结构不同。"""
        ...


class BaseSignalMapperAdapter(ABC):
    """SignalMapper 的平台适配器接口。"""

    @abstractmethod
    def extract_signal_mapping(self, source_root: Path,
                               output_dir: Path) -> dict:
        """从源码中提取信号映射（内部变量 ↔ CAN 信号）。

        不同平台的映射方式完全不同:
          - Gen6: 解析 RteComMapping.c
          - Gen5: 无 RteComMapping，可能需要从 DBC/MF4 或 DADDY channel 定义提取
        """
        ...

    @abstractmethod
    def extract_output_mapping(self, source_root: Path,
                               output_dir: Path) -> dict:
        """提取输出信号映射 (WriteSignal side)。"""
        ...

    @abstractmethod
    def resolve_internal_to_can(self, var_name: str, mapping: dict,
                                extra: Optional[dict] = None) -> list[str]:
        """解析内部变量 → CAN 信号。"""
        ...

    @abstractmethod
    def resolve_can_to_internal(self, can_signal: str,
                                mapping: dict) -> list[str]:
        """解析 CAN 信号 → 内部变量。"""
        ...

    @abstractmethod
    def get_output_signals_for_function(self, func_name: str) -> list[str]:
        """返回给定功能的输出 CAN 信号列表。"""
        ...
