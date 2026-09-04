# -*- coding: utf-8 -*-
"""
CodeReviewModule (M7) — deterministic, offline code review skeleton.

This standalone module reviews either unified diff text and/or one or more source
files with simple embedded-C safety heuristics. It does not require an LLM and
can optionally run a syntax hook through an injected runner or an auto-discovered
``clang``/``gcc`` ``-fsyntax-only`` command.
"""
from __future__ import annotations

import logging
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from .base import BaseModule, ModuleResult

log = logging.getLogger(__name__)

_SYNTAX_EXTENSIONS = frozenset({".c", ".cc", ".cpp", ".cxx"})
_CPP_EXTENSIONS = frozenset({".cc", ".cpp", ".cxx"})
_TODO_RE = re.compile(r"\b(TODO|FIXME|HACK|XXX)\b", re.IGNORECASE)
_HUNK_RE = re.compile(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


@dataclass(frozen=True)
class ReviewFinding:
    severity: str
    category: str
    message: str
    source: str
    line: int | None = None
    symbol: str = ""
    snippet: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SyntaxCheckResult:
    status: str
    checked_files: list[str]
    skipped_files: list[dict[str, str]]
    errors: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class _HeuristicRule:
    severity: str
    category: str
    pattern: re.Pattern[str]
    message: str


_HEURISTIC_RULES: tuple[_HeuristicRule, ...] = (
    _HeuristicRule(
        severity="critical",
        category="unsafe-function",
        pattern=re.compile(r"\b(gets|strcpy|strcat|sprintf|vsprintf)\s*\("),
        message="Replace with a bounded helper and explicit buffer-length handling.",
    ),
    _HeuristicRule(
        severity="warning",
        category="bounded-string-api",
        pattern=re.compile(r"\b(strncpy|strncat)\s*\("),
        message="Verify truncation handling and explicit null termination.",
    ),
    _HeuristicRule(
        severity="warning",
        category="scanf-family",
        pattern=re.compile(r"\b(scanf|fscanf|sscanf|vscanf|vfscanf|vsscanf)\s*\("),
        message="Verify field widths and check the parser return value.",
    ),
    _HeuristicRule(
        severity="warning",
        category="dynamic-allocation",
        pattern=re.compile(r"\b(malloc|calloc|realloc|free)\s*\("),
        message="Dynamic allocation in embedded paths should be justified or replaced with static storage.",
    ),
)


class CodeReviewModule(BaseModule):
    """M7 — deterministic standalone code review over diffs and source files."""

    name = "code-review"
    description = "Offline deterministic code review with safety/syntax hooks (M7)"

    def __init__(
        self,
        *,
        syntax_runner: Callable[[Path], Any] | None = None,
        syntax_enabled: bool = True,
        syntax_tool: str | None = None,
    ) -> None:
        self._syntax_runner = syntax_runner
        self._syntax_enabled = syntax_enabled
        self._syntax_tool = syntax_tool

    def run(
        self,
        *,
        diff_text: str = "",
        diff_file: str | Path | None = None,
        file_path: str | Path | None = None,
        file_paths: list[str | Path] | tuple[str | Path, ...] | str | Path | None = None,
        syntax_check: bool | None = None,
        **_: Any,
    ) -> ModuleResult:
        review_diff = self._resolve_diff_text(diff_text=diff_text, diff_file=diff_file)
        requested_files = self._resolve_file_paths(file_path=file_path, file_paths=file_paths)

        findings: list[ReviewFinding] = []
        readable_files: list[Path] = []

        for path in requested_files:
            if not path.exists():
                log.warning("CodeReviewModule: file not found: %s", path)
                findings.append(ReviewFinding(
                    severity="warning",
                    category="input",
                    message="file path does not exist",
                    source=str(path),
                ))
                continue
            if not path.is_file():
                log.warning("CodeReviewModule: not a file: %s", path)
                findings.append(ReviewFinding(
                    severity="warning",
                    category="input",
                    message="path is not a file",
                    source=str(path),
                ))
                continue
            readable_files.append(path)

        if review_diff:
            findings.extend(self._review_diff(review_diff))
        for path in readable_files:
            findings.extend(self._review_file(path))

        syntax = self._run_syntax_checks(readable_files, syntax_check=syntax_check)
        inputs = {
            "has_diff": bool(review_diff),
            "diff_file": str(diff_file) if diff_file else "",
            "requested_files": [str(path) for path in requested_files],
            "reviewed_files": [str(path) for path in readable_files],
        }
        summary = self._build_summary(findings, inputs=inputs, syntax=syntax)
        finding_dicts = [finding.to_dict() for finding in findings]

        if not review_diff and not readable_files:
            return ModuleResult.fail(
                "no reviewable input provided (pass diff_text/diff_file and/or file_path(s))",
                module=self.name,
                findings=finding_dicts,
                summary=summary,
                syntax=syntax.to_dict(),
                inputs=inputs,
            )

        return ModuleResult.success(
            message=(
                f"code-review: {summary['finding_count']} finding(s); "
                f"syntax={syntax.status}"
            ),
            module=self.name,
            findings=finding_dicts,
            summary=summary,
            syntax=syntax.to_dict(),
            inputs=inputs,
        )

    @staticmethod
    def _resolve_diff_text(
        *,
        diff_text: str,
        diff_file: str | Path | None,
    ) -> str:
        parts: list[str] = []
        if diff_text:
            parts.append(str(diff_text).strip())
        if diff_file:
            parts.append(Path(diff_file).read_text(encoding="utf-8", errors="replace").strip())
        return "\n".join(part for part in parts if part).strip()

    @staticmethod
    def _resolve_file_paths(
        *,
        file_path: str | Path | None,
        file_paths: list[str | Path] | tuple[str | Path, ...] | str | Path | None,
    ) -> list[Path]:
        raw_values: list[str | Path] = []
        if file_path:
            raw_values.append(file_path)
        if file_paths:
            if isinstance(file_paths, (str, Path)):
                raw_values.extend(
                    chunk.strip() for chunk in str(file_paths).split(",") if chunk.strip()
                )
            else:
                raw_values.extend(file_paths)

        resolved: list[Path] = []
        seen: set[str] = set()
        for value in raw_values:
            path = Path(value)
            key = str(path)
            if key not in seen:
                seen.add(key)
                resolved.append(path)
        return resolved

    def _review_diff(self, diff_text: str) -> list[ReviewFinding]:
        findings: list[ReviewFinding] = []
        for source, line_number, content in self._iter_diff_added_lines(diff_text):
            findings.extend(self._review_line(content, source=source, line_number=line_number))
        return findings

    def _review_file(self, file_path: Path) -> list[ReviewFinding]:
        findings: list[ReviewFinding] = []
        content = file_path.read_text(encoding="utf-8", errors="replace")
        for index, line in enumerate(content.splitlines(), start=1):
            findings.extend(
                self._review_line(line, source=str(file_path), line_number=index),
            )
        return findings

    def _review_line(
        self,
        line: str,
        *,
        source: str,
        line_number: int | None,
    ) -> list[ReviewFinding]:
        findings: list[ReviewFinding] = []
        snippet = line.strip()[:200]

        for rule in _HEURISTIC_RULES:
            match = rule.pattern.search(line)
            if not match:
                continue
            findings.append(ReviewFinding(
                severity=rule.severity,
                category=rule.category,
                message=f"{match.group(1)} detected. {rule.message}",
                source=source,
                line=line_number,
                symbol=match.group(1),
                snippet=snippet,
            ))

        todo_match = _TODO_RE.search(line)
        if todo_match:
            findings.append(ReviewFinding(
                severity="info",
                category="todo-marker",
                message=f"{todo_match.group(1).upper()} marker should be resolved before merge.",
                source=source,
                line=line_number,
                symbol=todo_match.group(1).upper(),
                snippet=snippet,
            ))

        return findings

    @staticmethod
    def _iter_diff_added_lines(diff_text: str) -> list[tuple[str, int | None, str]]:
        current_file = "diff"
        current_line: int | None = None
        additions: list[tuple[str, int | None, str]] = []

        for raw_line in diff_text.splitlines():
            if raw_line.startswith("+++ "):
                current_file = raw_line[4:].strip()
                if current_file.startswith("b/"):
                    current_file = current_file[2:]
                continue

            if raw_line.startswith("@@"):
                match = _HUNK_RE.search(raw_line)
                current_line = int(match.group(1)) if match else None
                continue

            if raw_line.startswith("\\"):
                continue

            if raw_line.startswith("+") and not raw_line.startswith("+++"):
                additions.append((current_file, current_line, raw_line[1:]))
                if current_line is not None:
                    current_line += 1
                continue

            if raw_line.startswith(" ") and current_line is not None:
                current_line += 1

        return additions

    def _run_syntax_checks(
        self,
        file_paths: list[Path],
        *,
        syntax_check: bool | None,
    ) -> SyntaxCheckResult:
        enabled = self._syntax_enabled if syntax_check is None else bool(syntax_check)
        if not file_paths:
            return SyntaxCheckResult(
                status="skipped",
                checked_files=[],
                skipped_files=[],
                errors=[],
            )
        if not enabled:
            return SyntaxCheckResult(
                status="skipped",
                checked_files=[],
                skipped_files=[
                    {"file": str(path), "reason": "disabled"} for path in file_paths
                ],
                errors=[],
            )

        runner = self._resolve_syntax_runner()
        if runner is None:
            return SyntaxCheckResult(
                status="skipped",
                checked_files=[],
                skipped_files=[
                    {"file": str(path), "reason": "tool-unavailable"} for path in file_paths
                ],
                errors=[],
            )

        checked_files: list[str] = []
        skipped_files: list[dict[str, str]] = []
        errors: list[dict[str, Any]] = []

        for path in file_paths:
            if path.suffix.lower() not in _SYNTAX_EXTENSIONS:
                skipped_files.append(
                    {"file": str(path), "reason": "unsupported-extension"},
                )
                continue

            outcome = self._normalize_syntax_outcome(path, runner(path))
            if outcome["status"] == "skipped":
                skipped_files.append(
                    {"file": str(path), "reason": outcome["message"] or "runner-skipped"},
                )
                continue

            checked_files.append(str(path))
            if outcome["status"] != "pass":
                errors.append({
                    "file": str(path),
                    "message": outcome["message"] or "syntax check failed",
                })

        status = "fail" if errors else ("pass" if checked_files else "skipped")
        return SyntaxCheckResult(
            status=status,
            checked_files=checked_files,
            skipped_files=skipped_files,
            errors=errors,
        )

    def _resolve_syntax_runner(self) -> Callable[[Path], Any] | None:
        if self._syntax_runner is not None:
            return self._syntax_runner

        tool = self._syntax_tool or self._discover_syntax_tool()
        if not tool:
            return None
        self._syntax_tool = tool
        return lambda path: self._invoke_syntax_tool(tool, path)

    @staticmethod
    def _discover_syntax_tool() -> str | None:
        for candidate in ("clang", "gcc", "cc"):
            resolved = shutil.which(candidate)
            if resolved:
                return resolved
        return None

    @staticmethod
    def _invoke_syntax_tool(tool: str, file_path: Path) -> dict[str, str]:
        language = "c++" if file_path.suffix.lower() in _CPP_EXTENSIONS else "c"
        standard = "c++11" if language == "c++" else "c99"
        result = subprocess.run(
            [tool, "-fsyntax-only", f"-std={standard}", "-x", language, str(file_path)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return {
            "status": "pass" if result.returncode == 0 else "fail",
            "message": (result.stderr or result.stdout).strip(),
        }

    @staticmethod
    def _normalize_syntax_outcome(
        file_path: Path,
        raw: Any,
    ) -> dict[str, str]:
        if isinstance(raw, SyntaxCheckResult):
            return {
                "status": raw.status,
                "message": "; ".join(error.get("message", "") for error in raw.errors),
            }
        if isinstance(raw, bool):
            return {"status": "pass" if raw else "fail", "message": ""}
        if isinstance(raw, str):
            return {"status": raw, "message": ""}
        if isinstance(raw, tuple) and len(raw) == 2:
            ok, message = raw
            return {"status": "pass" if ok else "fail", "message": str(message)}
        if isinstance(raw, dict):
            status = str(raw.get("status") or ("pass" if raw.get("ok", True) else "fail"))
            message = raw.get("message") or raw.get("output") or raw.get("stderr") or ""
            return {"status": status, "message": str(message)}
        raise TypeError(
            f"unsupported syntax runner result for {file_path}: {type(raw).__name__}",
        )

    @staticmethod
    def _build_summary(
        findings: list[ReviewFinding],
        *,
        inputs: dict[str, Any],
        syntax: SyntaxCheckResult,
    ) -> dict[str, Any]:
        severity_counts = {"critical": 0, "warning": 0, "info": 0}
        category_counts: dict[str, int] = {}

        for finding in findings:
            severity_counts[finding.severity] = severity_counts.get(finding.severity, 0) + 1
            category_counts[finding.category] = category_counts.get(finding.category, 0) + 1

        return {
            "finding_count": len(findings),
            "severity_counts": severity_counts,
            "category_counts": category_counts,
            "syntax_status": syntax.status,
            "checked_files": list(syntax.checked_files),
            "skipped_syntax_files": list(syntax.skipped_files),
            "input_file_count": len(inputs.get("reviewed_files", [])),
            "has_diff": bool(inputs.get("has_diff")),
        }

    @classmethod
    def register_cli(cls, subparsers: Any) -> Any:
        parser = super().register_cli(subparsers)
        parser.add_argument(
            "--diff-text", default="",
            help="Unified diff text to review directly.",
        )
        parser.add_argument(
            "--diff-file", default=None,
            help="Path to a unified diff file to load and review.",
        )
        parser.add_argument(
            "--file-path", dest="file_paths", action="append", default=[],
            help="Source file path to scan. Repeat for multiple files.",
        )
        parser.add_argument(
            "--no-syntax-check", action="store_true",
            help="Disable optional clang/gcc syntax validation.",
        )
        parser.add_argument(
            "--syntax-tool", default=None,
            help="Explicit clang/gcc executable for -fsyntax-only checks.",
        )
        return parser

    @classmethod
    def from_cli_args(cls, args: Any) -> "CodeReviewModule":
        return cls(
            syntax_enabled=not getattr(args, "no_syntax_check", False),
            syntax_tool=getattr(args, "syntax_tool", None),
        )


__all__ = ["CodeReviewModule", "ReviewFinding", "SyntaxCheckResult"]
