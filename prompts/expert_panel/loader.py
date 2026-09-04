"""
Expert Panel prompt loader — loads prompts from .md files.

Usage:
    from prompts.expert_panel.loader import (
        load_expert_system, load_moderator_system,
        load_task_header, load_expert_analyze_prompt,
        load_expert_respond_prompt, load_moderator_challenge_prompt,
        load_moderator_synthesize_prompt, load_retry_strict_json,
    )

All functions return the file content as a string. If the file is missing,
a RuntimeError is raised with the expected path.

Multi-project support:
    Pass project_key (e.g. "sc6h", "gwm_b26", "cr5cb") to load_expert_system().
    The loader checks prompts/expert_panel/experts/<project_key>/<expert_id>.md
    first, falling back to the default experts/<expert_id>.md.
"""

from __future__ import annotations

import json
from pathlib import Path

_PROMPTS_DIR = Path(__file__).parent


def _read(name: str) -> str:
    """Read a .md file from the prompts/expert_panel/ directory."""
    p = _PROMPTS_DIR / name
    if not p.exists():
        raise RuntimeError(f"Prompt file not found: {p}")
    return p.read_text(encoding="utf-8").strip()


def load_expert_system(expert_id: str, project_key: str = "") -> str:
    """Load system prompt for a specific expert (signal_chain, algorithm, etc.).

    If project_key is provided, checks for project-specific override first:
        prompts/expert_panel/experts/<project_key>/<expert_id>.md
    Falls back to the default:
        prompts/expert_panel/experts/<expert_id>.md
    """
    if project_key:
        override = _PROMPTS_DIR / "experts" / project_key / f"{expert_id}.md"
        if override.exists():
            return override.read_text(encoding="utf-8").strip()
    return _read(f"experts/{expert_id}.md")


def load_moderator_system() -> str:
    """Load moderator system prompt."""
    return _read("moderator_system.md")


def load_task_header(task: str) -> str:
    """Load task-type header (diagnose/tune/verify/query).

    task_headers.md format:
        ---
        task: <type>
        ---
        <content>

        ---
        task: <type2>
        ---
        <content>
    """
    text = _read("task_headers.md")
    # Split on the YAML-style separator block
    separator = f"\ntask: {task}\n---\n"
    parts = text.split(separator, 1)
    if len(parts) < 2:
        raise RuntimeError(f"Task header '{task}' not found in task_headers.md")
    section = parts[1]
    # Stop at next 'task:' separator
    next_sep = "\ntask: "
    idx = section.find(next_sep)
    if idx >= 0:
        section = section[:idx]
    return section.strip()


def load_expert_analyze_prompt(case_context: str, source_code: str,
                               expert_domain: str) -> str:
    """Load Round 1 expert analysis user prompt and fill in template vars."""
    template = _read("expert_analyze.md")
    return template.format(
        case_context=case_context,
        source_code=source_code,
        expert_domain=expert_domain,
    )


def load_expert_respond_prompt(question: str, all_opinions: str,
                               my_analysis: str, source_code: str) -> str:
    """Load Round 2 expert rebuttal user prompt."""
    template = _read("expert_respond.md")
    return template.format(
        question=question,
        all_opinions=all_opinions,
        my_analysis=my_analysis,
        source_code=source_code,
    )


def load_moderator_challenge_prompt(case_context: str, all_opinions: str,
                                    expert_count: int, panel_hint: str,
                                    questions_template: str) -> str:
    """Load moderator challenge user prompt."""
    template = _read("moderator_challenge.md")
    return template.format(
        case_context=case_context,
        expert_count=expert_count,
        all_opinions=all_opinions,
        panel_hint=panel_hint,
        questions_template=questions_template,
    )


def load_moderator_synthesize_prompt(case_context: str, all_opinions: str,
                                     contradictions: list, gaps: list) -> str:
    """Load moderator final synthesis user prompt."""
    template = _read("moderator_synthesize.md")
    return template.format(
        case_context=case_context,
        all_opinions=all_opinions,
        contradictions=json.dumps(contradictions, ensure_ascii=False),
        gaps=json.dumps(gaps, ensure_ascii=False),
    )


def load_retry_strict_json() -> str:
    """Load strict JSON retry prefix."""
    return _read("retry_strict_json.md")
