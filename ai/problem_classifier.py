# -*- coding: utf-8 -*-
"""
Problem classifier: decide which analytic path a user's request should take.

The platform deals with **at least four** kinds of questions:

* ``diagnose`` — Functional bug: the feature should trigger but doesn't, or
  triggers wrongly (FP / FN / DELAY / STATE). Requires the full causal
  pipeline (evidence + TPE + expert panel + root-cause chain).
* ``tune`` — Parameter optimisation: user wants to adjust a threshold (ROI /
  TTC / DDCI / speed band / hold time / …) and asks whether the new value
  will behave better on this recording or in general. Requires the
  parameter-sensitivity + what-if branch, **not** root-cause search.
* ``verify`` — "Given my proposed change X, does this recording now match
  the expected behaviour?" Close to ``tune`` but more specific (explicit
  proposed value).
* ``query`` — Plain data lookup: "show me the car_spd between 10-20 s" /
  "list every warning event". No diagnosis needed, just data extraction.

Classification runs as an extremely cheap first step in the pipeline —
deterministic keyword match first, LLM fallback only when necessary.

The result drives which downstream modules execute; a bad classification
is safer than a missing one, so we always fall back to ``diagnose``.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Iterable

from .model_router import ModelRouter
from .utils import parse_json_from_llm, ALL_FUNCTIONS


TASK_TYPES = ("diagnose", "tune", "verify", "query")

# ── Deterministic hints ────────────────────────────────────────────────

_TUNE_HINTS_STRONG = [
    r"调阈值", r"调参", r"调优", r"阈值优化", r"参数优化",
    r"调整阈值", r"优化参数",
    r"tune\b", r"tuning\b", r"optimize", r"optimis",
    r"threshold adjust",
]

_TUNE_HINTS_WEAK = [
    r"调整.*(?:阈值|ROI|TTC|DDCI|车速|角度|延时|保持|距离)",
    r"(?:提高|降低|加大|减小|扩大|缩小).*(?:阈值|ROI|TTC|DDCI|车速|角度|延时|距离)",
    r"(?:优化|改进|改善|提升).*效果",
    r"修改.*(?:ROI|TTC|DDCI|TTM|阈值)",
]

_TUNE_HINTS = _TUNE_HINTS_STRONG + _TUNE_HINTS_WEAK

_VERIFY_HINTS = [
    r"改成.*之后", r"改为.*后.*效果", r"如果.*改.*会",
    r"把.*设为", r"把.*改成", r"把.*从.*改到",
    r"验证.*方案", r"验证.*改动", r"验证.*阈值",
    r"what\s*if",
    r"设定为", r"set.*to", r"change.*to",
]

_EXPLICIT_VALUE_RE = re.compile(
    r"(?:从\s*[-+]?\d+(?:\.\d+)?\s*"
    r"(?:改到|改成|改为|调到|调至|调整到|调优到|到|至|→|->|to)\s*"
    r"[-+]?\d+(?:\.\d+)?)"
    r"|(?:(?:改为|改成|设为|设定为|=\s*)[-+]?\d+(?:\.\d+)?)"
    r"|(?:\b[-+]?\d+(?:\.\d+)?\s*(?:调到|调至|改到|改成|调优到|调整到)\s*"
    r"[-+]?\d+(?:\.\d+)?)",
    flags=re.IGNORECASE,
)

_QUERY_HINTS = [
    r"列出", r"查看", r"看一下", r"打印", r"显示", r"导出",
    r"between\s+\d", r"what\s+is\s+the",
    r"多少次", r"多少帧",
]

_DIAGNOSE_HINTS = [
    r"没触发", r"不触发", r"未触发", r"漏报", r"误报",
    r"误触发", r"异常退出", r"提前退出", r"延迟触发",
    r"触发时间.*(?:很短|过短|太短|异常)",
    r"状态.*异常", r"状态.*卡住", r"状态.*不对",
    r"failure", r"miss.*trigger", r"false.*alarm",
]


# ── Parameter hints: well-known threshold buckets per function ─────────

PARAM_KEYWORDS: dict[str, list[str]] = {
    "ROI": ["roi", "ROI", "RoiOffSet", "Line", "OffSet", "ROI区域", "检测区域"],
    "SPEED": ["车速", "Active.*Spd", "Deactive.*Spd", "Detect.*Spd", "ActiveUpSpd",
              "ActiveLowSpd", "Spd", "speed", "km/h"],
    "TTC": ["TTC", "ttc", "时间"],
    "TTM": ["TTM", "TTMX", "TTMY"],
    "DDCI": ["DDCI", "C-DDCI", "CDDCI"],
    "ANGLE": ["角度", "YawAngle", "航向角", "Angle"],
    "HOLD": ["保持", "保压", "Hold", "HoldTime", "hold time"],
    "DEBOUNCE": ["防抖", "Debounce", "Keep.*Frm"],
    "RATIO": ["Ratio", "比例"],
    "RADIUS": ["弯道", "Radius", "半径"],
}


@dataclass
class ClassificationResult:
    task_type: str          # diagnose | tune | verify | query
    confidence: float       # 0..1
    target_function: str    # uppercase, e.g. "BSD"; may be "" if unknown
    focus_parameters: list[str] = field(default_factory=list)   # e.g. ["TTC", "ROI"]
    focus_signals: list[str] = field(default_factory=list)      # e.g. ["car_spd"]
    reasoning: str = ""

    def to_dict(self) -> dict:
        return {
            "task_type": self.task_type,
            "confidence": round(self.confidence, 2),
            "target_function": self.target_function,
            "focus_parameters": self.focus_parameters,
            "focus_signals": self.focus_signals,
            "reasoning": self.reasoning,
        }


class ProblemClassifier:
    """Classify the user's request into one of the four analytic paths."""

    SYSTEM_PROMPT = """你是角雷达问题分析平台的任务分类器。
根据用户问题和预期结果，识别任务类型（不要做诊断，只做分类）。

任务类型定义:
- diagnose: 功能行为异常（漏报/误报/提前退出/状态卡住等），需要根因分析
- tune: 调阈值/调参以优化效果（用户知道大方向但没定具体值）
- verify: 已有明确改动方案，验证该方案在本次录制中的效果
- query: 仅查询数据，不需要诊断推理

8 个 ADAS 功能: BSD, LCA, DOW, RCW, RCTA, RCTB, FCTA, FCTB。
识别用户最关心的参数类别（ROI/SPEED/TTC/TTM/DDCI/ANGLE/HOLD/DEBOUNCE/RATIO/RADIUS）。

返回 JSON，不要任何额外说明。"""

    _JSON_SCHEMA_HINT = """
{
  "task_type": "diagnose | tune | verify | query",
  "confidence": 0.0-1.0,
  "target_function": "BSD|LCA|DOW|RCW|RCTA|RCTB|FCTA|FCTB|UNKNOWN",
  "focus_parameters": ["ROI", "TTC", ...],
  "focus_signals": ["car_spd", "trc_0_vel_x", ...],
  "reasoning": "一句话解释"
}"""

    def __init__(self, router: ModelRouter | None = None):
        self.router = router

    # ── Deterministic fast-path first ─────────────────────────────

    def classify(
        self,
        problem: str,
        expected: str = "",
        memory_hint: str = "",
    ) -> ClassificationResult:
        """Classify with deterministic rules first, LLM fallback on tie."""
        text = f"{problem}\n{expected}".strip()
        if not text:
            return ClassificationResult(
                task_type="diagnose", confidence=0.0,
                target_function="UNKNOWN",
                reasoning="Empty problem description; defaulting to diagnose.",
            )

        rule_result = self._rule_based(text)
        if rule_result is not None:
            return rule_result

        if self.router is None:
            # No LLM available — fall back to "diagnose" with low confidence.
            return ClassificationResult(
                task_type="diagnose", confidence=0.3,
                target_function=_guess_function(text),
                focus_parameters=_guess_param_buckets(text),
                reasoning="No rule match & no router; default diagnose.",
            )

        return self._llm_classify(problem, expected, memory_hint)

    # ── Rule path ──────────────────────────────────────────────────

    def _rule_based(self, text: str) -> ClassificationResult | None:
        tune_strong = _any_match(text, _TUNE_HINTS_STRONG)
        tune_weak = _any_match(text, _TUNE_HINTS_WEAK)
        tune_hit = tune_strong or tune_weak

        verify_hit = _any_match(text, _VERIFY_HINTS)
        query_hit = _any_match(text, _QUERY_HINTS)
        diag_hit = _any_match(text, _DIAGNOSE_HINTS)
        explicit_value = bool(_EXPLICIT_VALUE_RE.search(text))

        # Explicit-value + tune intent → verify (strongest signal).
        if explicit_value and (tune_hit or verify_hit):
            return ClassificationResult(
                task_type="verify", confidence=0.92,
                target_function=_guess_function(text),
                focus_parameters=_guess_param_buckets(text),
                reasoning=(
                    "Explicit numeric change detected "
                    f"(tune_hit={tune_hit or '-'} verify_hit={verify_hit or '-'})"
                ),
            )

        # Verify pattern with no numeric target (e.g. "如果阈值改大").
        if verify_hit:
            return ClassificationResult(
                task_type="verify", confidence=0.85,
                target_function=_guess_function(text),
                focus_parameters=_guess_param_buckets(text),
                reasoning=f"Verify pattern matched: {verify_hit}",
            )

        # Strong tune verb (调优/调参/...) overrides diag even if diag also fires —
        # user may just be listing the problem they're trying to improve.
        if tune_strong:
            return ClassificationResult(
                task_type="tune", confidence=0.88,
                target_function=_guess_function(text),
                focus_parameters=_guess_param_buckets(text),
                reasoning=f"Strong tune verb matched: {tune_strong}",
            )

        if tune_weak and not diag_hit:
            return ClassificationResult(
                task_type="tune", confidence=0.8,
                target_function=_guess_function(text),
                focus_parameters=_guess_param_buckets(text),
                reasoning=f"Tune pattern matched: {tune_weak}",
            )

        if query_hit and not diag_hit and not tune_hit:
            return ClassificationResult(
                task_type="query", confidence=0.75,
                target_function=_guess_function(text),
                focus_parameters=_guess_param_buckets(text),
                focus_signals=_guess_signals(text),
                reasoning=f"Query pattern matched: {query_hit}",
            )

        if diag_hit:
            return ClassificationResult(
                task_type="diagnose", confidence=0.85,
                target_function=_guess_function(text),
                focus_parameters=_guess_param_buckets(text),
                focus_signals=_guess_signals(text),
                reasoning=f"Diagnose pattern matched: {diag_hit}",
            )

        return None

    # ── LLM fallback ───────────────────────────────────────────────

    def _llm_classify(
        self, problem: str, expected: str, memory_hint: str,
    ) -> ClassificationResult:
        prompt = f"""## 用户问题
{problem}

## 预期结果
{expected if expected else "(未提供)"}

## 历史记忆摘要
{memory_hint[:1500] if memory_hint else "(无)"}

请分析并返回 JSON，字段固定为:
{self._JSON_SCHEMA_HINT}"""
        try:
            result = self.router.simple(prompt, system=self.SYSTEM_PROMPT)
            content = result if isinstance(result, str) else result.get("content", "")
        except Exception as exc:
            return ClassificationResult(
                task_type="diagnose", confidence=0.2,
                target_function=_guess_function(problem + " " + expected),
                reasoning=f"LLM classify failed: {exc}",
            )

        data = parse_json_from_llm(content, fallback={})
        task_type = str(data.get("task_type", "diagnose")).lower()
        if task_type not in TASK_TYPES:
            task_type = "diagnose"

        try:
            conf = float(data.get("confidence", 0.5))
        except (TypeError, ValueError):
            conf = 0.5

        target_raw = str(data.get("target_function", "")).upper()
        target = target_raw if target_raw in ALL_FUNCTIONS else _guess_function(
            problem + " " + expected,
        )

        focus_params = _normalise_list(data.get("focus_parameters", []))
        focus_signals = _normalise_list(data.get("focus_signals", []))

        return ClassificationResult(
            task_type=task_type,
            confidence=conf,
            target_function=target,
            focus_parameters=focus_params,
            focus_signals=focus_signals,
            reasoning=str(data.get("reasoning", ""))[:500],
        )


# ── Helpers ────────────────────────────────────────────────────────────

def _any_match(text: str, patterns: Iterable[str]) -> str:
    for pat in patterns:
        if re.search(pat, text, flags=re.IGNORECASE):
            return pat
    return ""


def _guess_function(text: str) -> str:
    """Pick the most-mentioned ADAS function in the text."""
    up = text.upper()
    hits: dict[str, int] = {}
    for fn in ALL_FUNCTIONS:
        hits[fn] = up.count(fn)
    best = max(hits.items(), key=lambda kv: kv[1])
    return best[0] if best[1] > 0 else "UNKNOWN"


def _guess_param_buckets(text: str) -> list[str]:
    """Return parameter categories the user referred to, in order seen."""
    seen: list[str] = []
    for bucket, kws in PARAM_KEYWORDS.items():
        for kw in kws:
            if re.search(kw, text, flags=re.IGNORECASE):
                if bucket not in seen:
                    seen.append(bucket)
                break
    return seen


_SIGNAL_LIKE_RE = re.compile(
    r"\b(?:car_spd|trc_\d_\w+|obj_\w+_flag|"
    r"[A-Z][a-zA-Z]+_0x[0-9A-Fa-f]{3}|[A-Z][a-zA-Z]+Actv|"
    r"[A-Z][a-zA-Z]+Req|CR_[A-Za-z]+|RSDS_[A-Za-z]+)"
)


def _guess_signals(text: str) -> list[str]:
    """Pull out signal-like identifiers that the user wrote explicitly."""
    found = _SIGNAL_LIKE_RE.findall(text)
    seen: list[str] = []
    for s in found:
        if s not in seen:
            seen.append(s)
    return seen


def _normalise_list(raw) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, str):
        raw = [raw]
    out: list[str] = []
    for item in raw:
        s = str(item).strip()
        if s and s not in out:
            out.append(s)
    return out


__all__ = [
    "ClassificationResult",
    "PARAM_KEYWORDS",
    "ProblemClassifier",
    "TASK_TYPES",
]
