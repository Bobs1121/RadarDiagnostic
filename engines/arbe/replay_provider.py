# -*- coding: utf-8 -*-
"""arbe 回放提供者抽象（V4 P4）。

P6 先抽象后远程：定义 ArbeReplayProvider 接口（submit/poll/fetch_trace/
fetch_kpi），提供本地实现 LocalArbeReplayProvider（解析 arbe 产出的
`_algo_warning_trace.csv`），远程 SSH 实现在后续接入。

warning trace 格式（来自 tools/arbe/FCTB_Batch_Replay_Operation_Guide.md）：
    event_sec, radar_id, w1...wN
    具体 wN→功能名由当前 runtime/source contract 或调用方传入；没有映射时保留 wN。
"""
from __future__ import annotations

import csv
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence


#: legacy warning 位索引 → 语义名（只作为兼容导出，不是跨项目默认事实）
# Kept as a compatibility export for old callers.  It is deliberately not
# used as the parser default: a different Gen6 project may have a different
# warning contract.
LEGACY_WARNING_BITS: dict[int, str] = {
    1: "BSD_L", 2: "BSD_R", 3: "LCA_L", 4: "LCA_R",
    5: "DOW_L", 6: "DOW_R", 7: "RCW",
    8: "RCTA_L", 9: "RCTA_R", 10: "RCTB_L", 11: "RCTB_R",
    12: "FCTA_L", 13: "FCTA_R", 14: "FCTB_L", 15: "FCTB_R",
}
WARNING_BITS = LEGACY_WARNING_BITS


@dataclass
class TraceEvent:
    """一条报警轨迹事件。"""

    event_sec: float
    radar_id: int = 0
    frame_id: int = 0
    warnings: dict[str, bool] = field(default_factory=dict)  # 语义名 → 是否触发
    warning_mapping_source: str = "not_provided"

    def active_warnings(self) -> list[str]:
        return [name for name, active in self.warnings.items() if active]

    def to_dict(self) -> dict:
        return {
            "event_sec": self.event_sec,
            "radar_id": self.radar_id,
            "frame_id": self.frame_id,
            "frame_id_source": "replay_trace.frame_id" if self.frame_id not in (None, 0) else "not_available",
            "warnings": self.warnings,
            "active": self.active_warnings(),
            "warning_mapping_source": self.warning_mapping_source,
        }


class ArbeReplayProvider(ABC):
    """arb 回放提供者统一接口。

    生命周期：
        1. submit(case_dir, mode) → job_ref
        2. poll(job_ref) → JobStatus（running/done/failed）
        3. fetch_trace(job_ref) → list[TraceEvent]
        4. fetch_kpi(job_ref) → dict
    """

    source_kind = "arbe"

    @abstractmethod
    def submit(self, case_dir: str, replay_mode: str = "fctb") -> str:
        """提交回放任务，返回 job reference（字符串）。"""
        raise NotImplementedError

    @abstractmethod
    def poll(self, job_ref: str) -> str:
        """查询任务状态：running / done / failed。"""
        raise NotImplementedError

    @abstractmethod
    def fetch_trace(self, job_ref: str) -> list[TraceEvent]:
        """拉取报警轨迹。"""
        raise NotImplementedError

    @abstractmethod
    def fetch_kpi(self, job_ref: str) -> dict:
        """拉取 KPI 结果（dict）。"""
        raise NotImplementedError


@dataclass
class JobStatus:
    status: str
    detail: str = ""
    job_ref: str = ""


def _warning_mapping(
    warning_names: Sequence[str] | Mapping[int, str] | None,
) -> tuple[dict[int, str], str]:
    if isinstance(warning_names, Mapping):
        mapping: dict[int, str] = {}
        for key, value in warning_names.items():
            try:
                index = int(key)
            except (TypeError, ValueError):
                continue
            name = str(value or "").strip()
            if index > 0 and name:
                mapping[index] = name
        return mapping, "explicit_mapping"
    if isinstance(warning_names, Sequence) and not isinstance(warning_names, (str, bytes, bytearray)):
        return {
            index: str(name).strip()
            for index, name in enumerate(warning_names, start=1)
            if str(name or "").strip()
        }, "explicit_names"
    return {}, "not_provided"


def parse_warning_trace_csv(
    path: str | Path,
    *,
    warning_names: Sequence[str] | Mapping[int, str] | None = None,
) -> list[TraceEvent]:
    """解析 arbe 产出的 `_algo_warning_trace.csv` → list[TraceEvent]。

    列布局：event_sec, radar_id, w1...w15（wN 为 0/1 或 True/False）。
    缺位/坏值 → 置 False（fail-soft，不 raise）。
    """
    path = Path(path)
    events: list[TraceEvent] = []
    warning_mapping, mapping_source = _warning_mapping(warning_names)
    if not path.exists():
        return events
    try:
        with open(path, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return events
            for row in reader:
                try:
                    event_sec = float(row.get("event_sec", 0) or 0)
                except ValueError:
                    event_sec = 0.0
                try:
                    radar_id = int(row.get("radar_id", 0) or 0)
                except ValueError:
                    radar_id = 0
                try:
                    frame_id = int(row.get("frame_id", 0) or 0)
                except ValueError:
                    frame_id = 0
                warnings: dict[str, bool] = {}
                for i in range(1, 16):
                    key = f"w{i}"
                    raw = row.get(key)
                    if raw is None:
                        continue
                    try:
                        val = raw.strip().lower()
                        active = val in ("1", "true", "yes", "t", "active", "on")
                    except Exception:
                        active = False
                    warnings[warning_mapping.get(i, f"w{i}")] = active
                events.append(TraceEvent(
                    event_sec=event_sec, radar_id=radar_id,
                    frame_id=frame_id, warnings=warnings,
                    warning_mapping_source=mapping_source,
                ))
    except Exception:
        return []
    return events


class LocalArbeReplayProvider(ArbeReplayProvider):
    """本地实现：解析已产出的 warning trace csv / KPI json。

    适用场景：arbe 回放已在服务器跑完，trace 文件已拷贝到本地 case_dir
    （或指定路径）。远程 SSH 实现在后续轮实现。
    """

    #: 缺省 KPI 文件名约定（可被 caller 覆盖）
    TRACE_GLOB = "*_algo_warning_trace.csv"
    KPI_GLOB = "*_adas_kpi_summary*.json"

    def __init__(
        self,
        output_dir: str = "",
        provider_name: str = "local",
        warning_names: Sequence[str] | Mapping[int, str] | None = None,
    ):
        self.output_dir = Path(output_dir) if output_dir else None
        self.provider_name = provider_name
        self.warning_names = warning_names

    # -- 实现 --------------------------------------------------------

    def submit(self, case_dir: str, replay_mode: str = "factb") -> str:
        # 本地模式无异步提交，直接用 case_dir 定位 trace
        return case_dir

    def poll(self, job_ref: str) -> str:
        # 本地同步：文件在就 done
        events = self.fetch_trace(job_ref)
        return "done" if events else "failed"

    def fetch_trace(self, job_ref: str) -> list[TraceEvent]:
        base = Path(job_ref)
        if not base.exists():
            return []
        trace_path = self._find_trace(base)
        if trace_path is None:
            return []
        return parse_warning_trace_csv(trace_path, warning_names=self.warning_names)

    def fetch_kpi(self, job_ref: str) -> dict:
        base = Path(job_ref)
        if not base.exists():
            return {}
        kpi = self._find_kpi(base)
        if kpi is None:
            return {}
        try:
            return json.loads(kpi.read_text(encoding="utf-8"))
        except Exception:
            return {}

    # -- 内部 --------------------------------------------------------

    def _find_trace(self, base: Path) -> Optional[Path]:
        if self.output_dir and self.output_dir.exists():
            base = self.output_dir
        hits = list(base.glob(self.TRACE_GLOB))
        if hits:
            return hits[0]
        # 递归兜底
        hits2 = list(base.rglob(self.TRACE_GLOB))
        return hits2[0] if hits2 else None

    def _find_kpi(self, base: Path) -> Optional[Path]:
        if self.output_dir and self.output_dir.exists():
            base = self.output_dir
        hits = list(base.glob(self.KPI_GLOB))
        if hits:
            return hits[0]
        hits2 = list(base.rglob(self.KPI_GLOB))
        return hits2[0] if hits2 else None


__all__ = [
    "ArbeReplayProvider",
    "LocalArbeReplayProvider",
    "TraceEvent",
    "parse_warning_trace_csv",
    "JobStatus",
    "WARNING_BITS",
]
