# -*- coding: utf-8 -*-
"""
Fallback strategies for LLM-dependent pipeline steps.

When a model call fails (network error, quota exceeded, timeout), the
orchestrator can fall back to a deterministic or cached answer so the
pipeline keeps running instead of crashing.

Each fallback function returns the same type the original LLM step would
return, so callers don't need to change their error handling.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Fallback registry
# ---------------------------------------------------------------------------

# Maps step name -> fallback function.
# Each fallback receives **kwargs and returns a result dict.
_FALLBACKS: dict[str, callable] = {}


def register_fallback(step: str):
    """Decorator to register a fallback handler for a pipeline step."""
    def wrapper(fn):
        _FALLBACKS[step] = fn
        return fn
    return wrapper


def get_fallback(step: str) -> Optional[callable]:
    """Look up the fallback handler for a step."""
    return _FALLBACKS.get(step)


# ---------------------------------------------------------------------------
# Step-specific fallbacks
# ---------------------------------------------------------------------------

@register_fallback("classify")
def fallback_classify(**kwargs) -> dict:
    """Fallback for problem classification: default to 'diagnose' with all experts."""
    func_name = kwargs.get("func_name", "UNKNOWN")
    logger.warning("[fallback] classify -> default diagnose with all experts")
    return {
        "task_type": "diagnose",
        "func_name": func_name,
        "confidence": 0.5,
        "reasoning": "(fallback) LLM unavailable, defaulting to full diagnosis",
        "focus_params": [],
    }


@register_fallback("conditions")
def fallback_conditions(func_name: str, source_docs_dir: str | Path, **kwargs) -> dict:
    """Fallback for condition extraction: try cached conditions file."""
    cache_path = Path(source_docs_dir) / f"{func_name}_conditions.json"
    if cache_path.exists():
        try:
            conditions = json.loads(cache_path.read_text(encoding="utf-8"))
            logger.warning("[fallback] conditions -> loaded from cache: %s", cache_path)
            return conditions
        except json.JSONDecodeError:
            logger.error("[fallback] conditions cache is corrupted: %s", cache_path)
    logger.warning("[fallback] conditions -> empty condition tree")
    return {
        "activation": {"type": "AND", "children": []},
        "suppression": {"type": "AND", "children": []},
    }


@register_fallback("probe")
def fallback_probe(**kwargs) -> dict:
    """Fallback for data probing: return empty results."""
    logger.warning("[fallback] probe -> skipped, returning empty results")
    return {}


@register_fallback("expert_panel")
def fallback_expert_panel(problem: str, expected: str, func_name: str,
                          evidence: str = "", **kwargs) -> dict:
    """Fallback for expert panel: single-expert direct output without debate."""
    logger.warning(
        "[fallback] expert_panel -> single-pass summary without debate rounds"
    )
    verdict = (
        f"### 诊断结果（降级模式 — LLM 不可用）\n\n"
        f"**功能**: {func_name}\n"
        f"**问题**: {problem}\n"
        f"**期望**: {expected}\n\n"
        f"由于模型不可用，无法执行完整的专家面板分析。"
        f"建议检查模型服务后重新运行诊断。\n\n"
        f"### 已知证据\n{evidence[:2000]}"
    )
    return {
        "expert_opinions": [],
        "moderator_challenges": [],
        "final_verdict": verdict,
        "confidence": 0.0,
        "rounds": 0,
    }


@register_fallback("understand")
def fallback_understand(problem: str, **kwargs) -> dict:
    """Fallback for problem understanding: extract function name from keywords."""
    func_keywords = {
        "BSD": "BSD", "LCA": "LCA", "DOW": "DOW", "RCW": "RCW",
        "RCTA": "RCTA", "RCTB": "RCTB", "FCTA": "FCTA", "FCTB": "FCTB",
    }
    func_name = "UNKNOWN"
    for kw, fn in func_keywords.items():
        if kw in problem:
            func_name = fn
            break

    logger.warning("[fallback] understand -> func_name=%s from keyword match", func_name)
    return {
        "function": func_name,
        "confidence": 0.3,
        "reasoning": f"(fallback) Keyword match in: {problem}",
        "fail_type": "OTHER",
        "key_variables": [],
        "related_functions": [],
    }


@register_fallback("codefix")
def fallback_codefix(verdict: str, **kwargs) -> dict:
    """Fallback for code fix generation: return text suggestion only."""
    logger.warning("[fallback] codefix -> text suggestion only")
    return {
        "fix_type": "text_suggestion",
        "suggestion": verdict[:2000],
        "diffs": [],
        "confidence": 0.0,
    }


# ---------------------------------------------------------------------------
# Wrapper: safe_llm_call
# ---------------------------------------------------------------------------

def safe_llm_call(
    step: str,
    call_fn: callable,
    fallback_kwargs: dict | None = None,
    **call_kwargs,
) -> Any:
    """
    Wrap an LLM call with automatic fallback.

    Args:
        step: Pipeline step name (e.g. 'classify', 'conditions').
        call_fn: The function that makes the LLM call.
        fallback_kwargs: Extra kwargs to pass to the fallback function.
        **call_kwargs: Kwargs forwarded to both call_fn and fallback.

    Returns:
        Result from call_fn on success, or fallback result on failure.
    """
    try:
        return call_fn(**call_kwargs)
    except Exception as e:
        logger.error("LLM call failed for step '%s': %s", step, e)
        fb = get_fallback(step)
        if fb is None:
            logger.error("No fallback registered for step '%s' — re-raising", step)
            raise
        merged = {**call_kwargs, **(fallback_kwargs or {})}
        return fb(**merged)
