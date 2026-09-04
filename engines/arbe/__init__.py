# -*- coding: utf-8 -*-
"""engines.arbe — arbe 仿真回放提供者（V4 P4）。

先抽象后远程：ArbeReplayProvider 接口 + LocalArbeReplayProvider（解析
warning trace csv / KPI）+ RemoteArbeReplayProvider（SSH 骨架，接口就绪、
实现后置，服务器 10.190.171.44 接入用）。
"""
from __future__ import annotations

from .remote_replay import RemoteArbeReplayProvider
from .public_runtime import detect_warning_rising_edges, normalize_public_runtime
from .build import build_catkin_make_command, run_catkin_make
from .cuda import build_cuda_resolve_command, parse_cuda_resolve_output, resolve_cuda
from .source import (
    build_source_resolve_command,
    derive_ref_from_version,
    parse_source_resolve_output,
    resolve_source,
)
from .patch_plan import (
    DEFAULT_CHECKS,
    build_patch_plan_command,
    parse_patch_plan_output,
    resolve_patch_plan,
)
from .data_prep import (
    build_data_verify_command,
    map_source_path,
    parse_data_verify_output,
    validate_extensions,
    verify_data,
)
from .transfer import build_transfer_command, run_transfer
from .preflight import (
    ArbePreflight,
    CommandResult,
    LocalShellRunner,
    SshCommandRunner,
)
from .intake import build_intake
from .public_evidence import audit_public_bundle, build_public_topic_plan
from .ros_inventory import RosTopicInventory, build_inventory_command, parse_inventory_output
from .replay_provider import (
    ArbeReplayProvider,
    JobStatus,
    LocalArbeReplayProvider,
    TraceEvent,
    WARNING_BITS,
    parse_warning_trace_csv,
)

__all__ = [
    "ArbeReplayProvider",
    "LocalArbeReplayProvider",
    "RemoteArbeReplayProvider",
    "build_catkin_make_command",
    "run_catkin_make",
    "build_cuda_resolve_command",
    "parse_cuda_resolve_output",
    "resolve_cuda",
    "build_source_resolve_command",
    "derive_ref_from_version",
    "parse_source_resolve_output",
    "resolve_source",
    "DEFAULT_CHECKS",
    "build_patch_plan_command",
    "parse_patch_plan_output",
    "resolve_patch_plan",
    "build_data_verify_command",
    "map_source_path",
    "parse_data_verify_output",
    "validate_extensions",
    "verify_data",
    "build_transfer_command",
    "run_transfer",
    "ArbePreflight",
    "CommandResult",
    "LocalShellRunner",
    "SshCommandRunner",
    "build_intake",
    "audit_public_bundle",
    "build_public_topic_plan",
    "RosTopicInventory",
    "build_inventory_command",
    "parse_inventory_output",
    "TraceEvent",
    "parse_warning_trace_csv",
    "JobStatus",
    "WARNING_BITS",
]
