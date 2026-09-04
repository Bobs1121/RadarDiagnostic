# -*- coding: utf-8 -*-
"""
CodeFixEngine — 从专家面板结论生成可执行的 unified diff。

流程:
  1. 解析 final_verdict，提取修复建议和代码定位 (file:line)
  2. CodeGraph 精确查找代码位置
  3. coder LLM 生成 unified diff
  4. 安全审查 (embedded-c-runtime-safety 规则)
  5. 语法验证 (clang -fsyntax-only)

输出: FixResult (diff patch, 安全报告, 效果预估)
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


# ── Data Models ────────────────────────────────────────────────────────

@dataclass
class FixLocation:
    """一个需要修改的代码位置。"""
    file_path: str          # 相对 source_root 的路径
    start_line: int
    end_line: int
    function_name: Optional[str] = None
    context: str = ""       # 原始代码片段 (source_root/file_path 的内容)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SafetyIssue:
    """安全审查发现的问题。"""
    severity: str           # "critical" / "warning" / "info"
    category: str           # "buffer_overflow" / "null_ptr" / "race_condition" / etc.
    description: str
    line: Optional[int] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class FixResult:
    """CodeFixEngine 的最终产物。"""
    success: bool
    fix_suggestions: list[str]         # 专家原始建议
    locations: list[dict]              # FixLocation.to_dict()
    diffs: list[str]                   # unified diff 字符串
    safety_issues: list[dict]          # SafetyIssue.to_dict()
    syntax_check: str                  # "pass" / "fail" / "skipped"
    effect_estimate: str               # LLM 生成的效果预估
    error: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


# ── Location Parser ────────────────────────────────────────────────────

# 匹配 file:line 格式: "adasFunc.c:6378-6382" 或 "ASWIN_SystemState.c:123"
_FILE_LINE_RE = re.compile(
    r'(?P<file>[\w][\w./\-]*(?:\.(?:c|h|cpp|hpp)))'
    r'[:]\s*'
    r'(?P<start>\d+)'
    r'(?:\s*[-~]\s*(?P<end>\d+))?'
)


def _parse_code_locations(verdict: str) -> list[dict]:
    """从 final_verdict 文本中提取 file:line 定位。

    Returns list of {file, start_line, end_line}.
    """
    locations = []
    for m in _FILE_LINE_RE.finditer(verdict):
        file_name = m.group("file")
        start = int(m.group("start"))
        end_str = m.group("end")
        end = int(end_str) if end_str else start + 5  # default 5 lines

        # Deduplicate by (file, start)
        key = (file_name, start)
        if not any((l["file"], l["start_line"]) == key for l in locations):
            locations.append({
                "file": file_name,
                "start_line": start,
                "end_line": end,
            })

    return locations


def _parse_fix_suggestions(verdict: str) -> list[str]:
    """从 final_verdict 中提取 "### 修复建议" 段落。"""
    # 尝试匹配 markdown heading
    m = re.search(r'###\s*修复建议\s*\n(.*?)(?=\n###|\n##|\Z)', verdict, re.DOTALL)
    if m:
        text = m.group(1).strip()
        # 拆成独立建议行
        suggestions = []
        for line in text.split("\n"):
            line = line.strip()
            # 去掉序号 "1. xxx"
            line = re.sub(r'^\d+[\.\、\)]\s*', '', line).strip()
            if line and len(line) > 2:
                suggestions.append(line)
        if suggestions:
            return suggestions

    # fallback: 全文返回
    return [verdict[:2000]]


# ── CodeGraph Locator ─────────────────────────────────────────────────

_CONTEXT_LINES = 20  # 代码片段前后扩展行数


def _resolve_locations_with_codegraph(
    raw_locations: list[dict],
    func_name: str,
    codegraph_db_path: str | Path,
    source_root: str | Path,
) -> list[FixLocation]:
    """用 CodeGraph DB 解析模糊的文件名 → 精确路径 + 源代码上下文。"""
    source_root = Path(source_root)
    cg_path = Path(codegraph_db_path)

    if not cg_path.exists():
        log.warning("CodeFixEngine: CodeGraph DB not found at %s", cg_path)
        return _resolve_locations_fallback(raw_locations, source_root)

    try:
        from .codegraph.query import CodeGraph
        cg = CodeGraph(cg_path)
    except Exception as e:
        log.warning("CodeFixEngine: failed to open CodeGraph (%s), using fallback", e)
        return _resolve_locations_fallback(raw_locations, source_root)

    locations = []
    seen = set()

    for raw in raw_locations:
        file_name = raw["file"]
        start_line = raw["start_line"]
        end_line = raw["end_line"]

        # 1) 尝试通过文件名找到完整 file_path
        file_path = _find_file_in_codegraph(cg, file_name)
        if not file_path:
            log.info("CodeFixEngine: could not resolve file %s in CodeGraph", file_name)
            continue

        # 2) 如果有函数名，用函数边界收紧范围
        if func_name:
            func_node = cg.get_function_by_name(func_name)
            if func_node and func_node.file_path == file_path:
                # 检查给定的行号是否在函数范围内
                if func_node.start_line and func_node.end_line:
                    if start_line < func_node.start_line:
                        start_line = func_node.start_line
                    if end_line > func_node.end_line:
                        end_line = func_node.end_line

        # 3) 读取源代码上下文
        full_path = source_root / file_path
        context = _read_code_context(full_path, start_line, end_line)
        if not context:
            continue

        key = (file_path, start_line)
        if key not in seen:
            seen.add(key)
            locations.append(FixLocation(
                file_path=file_path,
                start_line=start_line,
                end_line=end_line,
                function_name=func_name,
                context=context,
            ))

    cg.close()
    return locations


def _find_file_in_codegraph(cg: "CodeGraph", file_name: str) -> Optional[str]:
    """在 CodeGraph DB 中搜索匹配 file_name 的完整 file_path。"""
    # 直接查 nodes 表的 file_path 列
    rows = cg.conn.execute(
        "SELECT DISTINCT file_path FROM nodes WHERE file_path LIKE ? ORDER BY file_path",
        (f"%{file_name}%",),
    ).fetchall()
    for row in rows:
        fp = row["file_path"]
        # 精确匹配文件名 (去掉目录前缀)
        if fp.endswith(file_name) or file_name in fp:
            return fp

    return None


def _resolve_locations_fallback(
    raw_locations: list[dict],
    source_root: Path,
) -> list[FixLocation]:
    """当 CodeGraph 不可用时，直接在 source_root 中递归搜索文件。"""
    locations = []
    for raw in raw_locations:
        file_name = raw["file"]
        start_line = raw["start_line"]
        end_line = raw["end_line"]

        # 递归搜索
        full_path = _find_file_in_tree(source_root, file_name)
        if not full_path:
            continue

        file_path = str(full_path.relative_to(source_root))
        context = _read_code_context(full_path, start_line, end_line)
        if not context:
            continue

        locations.append(FixLocation(
            file_path=file_path,
            start_line=start_line,
            end_line=end_line,
            context=context,
        ))

    return locations


def _find_file_in_tree(root: Path, file_name: str) -> Optional[Path]:
    """在目录树中递归搜索文件。"""
    try:
        matches = list(root.rglob(file_name))
        return matches[0] if matches else None
    except Exception:
        return None


def _read_code_context(full_path: Path, start: int, end: int) -> str:
    """读取文件内容，返回带行号的代码上下文。"""
    try:
        content = full_path.read_text(encoding="utf-8", errors="replace")
        lines = content.splitlines()
        total = len(lines)

        # 扩展上下文
        s = max(1, start - _CONTEXT_LINES)
        e = min(total, end + _CONTEXT_LINES)

        code_lines = []
        for i in range(s, e + 1):
            code_lines.append(f"{i}|{lines[i - 1]}")

        return "\n".join(code_lines)
    except Exception as e:
        log.warning("CodeFixEngine: cannot read %s (%s)", full_path, e)
        return ""


# ── Diff Generator (Coder LLM) ────────────────────────────────────────

DIFF_GENERATION_PROMPT = """\
你是一名嵌入式 C 代码专家。请根据以下诊断结论和修复建议，生成 **unified diff** 格式的补丁。

## 诊断结论
{diagnosis_summary}

## 修复建议
{fix_suggestions}

## 源代码上下文
{code_context}

## 要求
1. 输出 **纯 unified diff** 格式，以 `--- a/` 开头
2. 只修改必要的最小代码范围
3. 保持 C 代码风格一致（缩进、命名）
4. 添加注释解释修改原因
5. 确保编译通过（语法正确）
6. 如果是修改阈值/参数，保持原有变量类型和声明方式
7. 不要删除原有的函数签名和必要的头文件包含

## 输出格式
只输出 diff 内容，不要包含 markdown 代码块标记（```diff ... ```）。
"""

DIFF_SYSTEM_PROMPT = """\
你是嵌入式 C 代码的 diff 生成专家。你只输出有效的 unified diff 补丁，
不包含任何解释文本。严格遵守 AUTOSAR 嵌入式 C 编码规范（MISRA C 兼容）。
"""


def generate_diffs(
    locations: list[FixLocation],
    diagnosis: str,
    fix_suggestions: list[str],
    router,
    on_status=None,
) -> list[str]:
    """调用 coder LLM 为每个代码位置生成 unified diff。

    Returns list of diff strings (one per location).
    """
    if not locations:
        return []

    diffs = []
    for idx, loc in enumerate(locations):
        if on_status:
            on_status("code_fix", f"Generating diff for {loc.file_path} ({idx+1}/{len(locations)})...")

        suggestions_text = "\n".join(f"- {s}" for s in fix_suggestions)

        # 诊断摘要 — 只取根因和修复建议部分
        diagnosis_summary = _extract_root_cause(diagnosis)

        prompt = DIFF_GENERATION_PROMPT.format(
            diagnosis_summary=diagnosis_summary,
            fix_suggestions=suggestions_text,
            code_context=loc.context,
        )

        try:
            t0 = time.perf_counter()
            result = router.complex(
                prompt,
                system=DIFF_SYSTEM_PROMPT,
                thinking=False,
            )
            elapsed = time.perf_counter() - t0

            diff_text = result.get("content", "").strip()
            # 清理 markdown 代码块标记
            diff_text = _clean_diff(diff_text)

            log.info("CodeFixEngine: diff generated in %.1fs (%d chars)", elapsed, len(diff_text))
            diffs.append(diff_text)

        except Exception as e:
            log.error("CodeFixEngine: diff generation failed (%s)", e)
            diffs.append(f"(diff generation failed: {e})")

    return diffs


def _extract_root_cause(diagnosis: str) -> str:
    """从 final_verdict 中提取根因部分。"""
    # 提取 "### 根因" 到下一个 "###" 之间
    m = re.search(r'###\s*根因\s*\n(.*?)(?=\n###|\Z)', diagnosis, re.DOTALL)
    if m:
        return m.group(1).strip()[:1500]

    # fallback: 取前 1500 字符
    return diagnosis[:1500]


def _clean_diff(diff_text: str) -> str:
    """清理 diff 输出，去掉 markdown 标记。"""
    # 去掉 ```diff ... ``` 或 ``` ... ```
    diff_text = re.sub(r'^```(?:diff)?\s*', '', diff_text.strip())
    diff_text = re.sub(r'\s*```$', '', diff_text.strip())
    return diff_text


# ── Safety Review ──────────────────────────────────────────────────────

SAFETY_REVIEW_PROMPT = """\
你是一名嵌入式 C 代码安全审查专家。请审查以下 unified diff 补丁是否存在运行时安全问题。

## Diff 补丁
{diff}

## 审查规则 (基于 MISRA C / AUTOSAR 编码规范)
1. **缓冲区溢出**: 字符串操作是否检查长度？数组索引是否越界？
2. **空指针解引用**: 是否增加了指针使用但未检查 NULL？
3. **整数溢出**: 算术运算是否可能溢出？
4. **未初始化变量**: 新引入的变量是否正确初始化？
5. **类型安全**: 强制类型转换是否安全？
6. **资源泄漏**: 内存/文件句柄是否正确释放？
7. **并发安全**: 是否涉及共享变量访问但无锁保护？
8. **死循环/无限递归**: 循环终止条件是否正确？

## 输出格式 (JSON)
返回一个 JSON 数组，每个元素包含:
{
  "severity": "critical|warning|info",
  "category": "问题类别",
  "description": "问题描述和修复建议",
  "line": 行号 (可选)
}
如果没有问题，返回空数组 []。
"""

SAFETY_SYSTEM_PROMPT = """\
你是嵌入式 C 代码安全审查专家。你只返回 JSON 格式的安全审查结果，
不包含任何其他文本。
"""


def review_safety(
    diffs: list[str],
    router,
    on_status=None,
) -> list[SafetyIssue]:
    """对生成的 diff 进行安全审查。"""
    if not diffs:
        return []

    all_issues: list[SafetyIssue] = []

    for idx, diff in enumerate(diffs):
        if not diff or diff.startswith("("):
            continue

        if on_status:
            on_status("code_fix", "Running safety review...")

        prompt = SAFETY_REVIEW_PROMPT.format(diff=diff)

        try:
            result = router.complex(
                prompt,
                system=SAFETY_SYSTEM_PROMPT,
                thinking=False,
            )

            text = result.get("content", "[]").strip()
            text = _clean_json(text)

            issues_data = json.loads(text)
            for item in issues_data:
                all_issues.append(SafetyIssue(
                    severity=item.get("severity", "info"),
                    category=item.get("category", "unknown"),
                    description=item.get("description", ""),
                    line=item.get("line"),
                ))

        except json.JSONDecodeError:
            log.warning("CodeFixEngine: safety review returned invalid JSON")
        except Exception as e:
            log.warning("CodeFixEngine: safety review failed (%s)", e)

    return all_issues


def _clean_json(text: str) -> str:
    """清理 JSON 输出。"""
    text = text.strip()
    # 去掉 markdown 代码块
    text = re.sub(r'^```(?:json)?\s*', '', text)
    text = re.sub(r'\s*```$', '', text)
    return text.strip()


# ── Syntax Check ───────────────────────────────────────────────────────

def check_syntax(
    diffs: list[str],
    source_root: str | Path,
    locations: list[FixLocation],
) -> str:
    """尝试用 clang 做语法检查。

    Returns "pass" / "fail" / "skipped".
    """
    source_root = Path(source_root)
    clang = _find_clang()
    if not clang:
        log.info("CodeFixEngine: clang not found, skipping syntax check")
        return "skipped"

    # 尝试应用 diff 到临时文件，然后用 clang 检查
    import tempfile
    import shutil

    passed = True
    for loc, diff in zip(locations, diffs):
        if not diff or diff.startswith("("):
            continue

        full_path = source_root / loc.file_path
        if not full_path.exists():
            continue

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_file = Path(tmpdir) / full_path.name

            # 复制原文件
            shutil.copy2(full_path, tmp_file)

            # 尝试应用 patch
            patch_file = Path(tmpdir) / "fix.patch"
            patch_file.write_text(diff, encoding="utf-8")

            # 使用 patch 命令应用
            result = subprocess.run(
                ["patch", "-p0", str(tmp_file), "-i", str(patch_file), "--dry-run"],
                capture_output=True,
                text=True,
                timeout=10,
            )

            if result.returncode != 0:
                log.warning("CodeFixEngine: patch dry-run failed for %s", loc.file_path)
                passed = False
                continue

            # 真正应用 patch
            subprocess.run(
                ["patch", "-p0", str(tmp_file), "-i", str(patch_file)],
                capture_output=True,
                text=True,
                timeout=10,
            )

            # clang 语法检查
            clang_result = subprocess.run(
                [clang, "-fsyntax-only", "-std=c99", "-x", "c", str(tmp_file)],
                capture_output=True,
                text=True,
                timeout=30,
            )

            if clang_result.returncode != 0:
                log.warning(
                    "CodeFixEngine: clang syntax check failed for %s: %s",
                    loc.file_path, clang_result.stderr[:200],
                )
                passed = False

    return "pass" if passed else "fail"


def _find_clang() -> Optional[str]:
    """查找 clang 编译器。"""
    for name in ["clang", "clang-14", "clang-13", "gcc"]:
        try:
            result = subprocess.run(
                ["which", name],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            continue
    return None


# ── Effect Estimation ──────────────────────────────────────────────────

EFFECT_ESTIMATE_PROMPT = """\
你是一名 ADAS 功能诊断专家。请评估以下代码修改对本次问题的预期效果。

## 问题描述
{problem}

## 根因诊断
{root_cause}

## 代码修改 (diff)
{diffs}

## 请评估
1. **预期效果**: 修改后是否解决根本问题？
2. **影响范围**: 修改是否可能影响其他功能？
3. **风险评估**: 是否存在副作用或引入新问题的风险？
4. **置信度**: 你对这个修复方案的信心 (0-100%)

用 3-5 行中文简要回答。
"""


def estimate_effect(
    problem: str,
    diagnosis: str,
    diffs: list[str],
    router,
    on_status=None,
) -> str:
    """调用 LLM 预估代码修改的效果。"""
    if not diffs:
        return "(未生成代码修改，无法预估效果)"

    root_cause = _extract_root_cause(diagnosis)
    diffs_text = "\n\n".join(diffs)

    if on_status:
        on_status("code_fix", "Estimating fix effect...")

    prompt = EFFECT_ESTIMATE_PROMPT.format(
        problem=problem[:500],
        root_cause=root_cause,
        diffs=diffs_text[:3000],
    )

    try:
        result = router.complex(
            prompt,
            system="你是 ADAS 功能诊断专家，用中文回答。",
            thinking=False,
        )
        return result.get("content", "(效果预估失败)").strip()
    except Exception as e:
        log.warning("CodeFixEngine: effect estimation failed (%s)", e)
        return f"(效果预估失败: {e})"


# ── Markdown Renderer ──────────────────────────────────────────────────

def render_fix_report_markdown(fix_result: FixResult) -> str:
    """将 FixResult 渲染为 markdown 报告。"""
    lines = []
    lines.append("## 代码修改方案 (CodeFixEngine)")
    lines.append("")

    if not fix_result.success:
        lines.append(f"**状态**: 生成失败 — {fix_result.error}")
        lines.append("")
        return "\n".join(lines)

    # 修复建议
    lines.append("### 修复建议")
    for s in fix_result.fix_suggestions:
        lines.append(f"- {s}")
    lines.append("")

    # 代码位置
    if fix_result.locations:
        lines.append("### 修改位置")
        for loc in fix_result.locations:
            fp = loc.get("file_path", "")
            sl = loc.get("start_line", 0)
            el = loc.get("end_line", 0)
            fn = loc.get("function_name", "")
            lines.append(f"- `{fp}` ({sl}-{el})" + (f" — {fn}" if fn else ""))
        lines.append("")

    # Diff 补丁
    for i, diff in enumerate(fix_result.diffs):
        if diff and not diff.startswith("("):
            lines.append(f"### 补丁 {i+1}")
            lines.append("```diff")
            lines.append(diff)
            lines.append("```")
            lines.append("")

    # 安全审查
    critical = [x for x in fix_result.safety_issues if x.get("severity") == "critical"]
    warnings = [x for x in fix_result.safety_issues if x.get("severity") == "warning"]

    if critical or warnings:
        lines.append("### 安全审查结果")
        if critical:
            lines.append("")
            lines.append("**严重问题 (Critical)**:")
            for issue in critical:
                line_info = f" (行 {issue.get('line', '?')})" if issue.get("line") else ""
                lines.append(f"- [{issue['category']}]{line_info}: {issue['description']}")
        if warnings:
            lines.append("")
            lines.append("**警告 (Warning)**:")
            for issue in warnings:
                line_info = f" (行 {issue.get('line', '?')})" if issue.get("line") else ""
                lines.append(f"- [{issue['category']}]{line_info}: {issue['description']}")
        lines.append("")

    # 语法检查
    syntax = fix_result.syntax_check
    syntax_icon = {"pass": "✅", "fail": "❌", "skipped": "⏭️"}.get(syntax, "?")
    lines.append(f"### 语法检查: {syntax_icon} {syntax}")
    lines.append("")

    # 效果预估
    if fix_result.effect_estimate:
        lines.append("### 效果预估")
        lines.append(fix_result.effect_estimate)
        lines.append("")

    return "\n".join(lines)


# ── Public API ─────────────────────────────────────────────────────────

def generate_fix(
    problem: str,
    diagnosis: str,
    func_name: str,
    codegraph_db_path: str | Path,
    source_root: str | Path,
    router,
    on_status=None,
) -> FixResult:
    """
    从专家面板结论生成代码修改方案。

    Args:
        problem: 问题描述
        diagnosis: 专家面板 final_verdict
        func_name: 涉及的功能/函数名
        codegraph_db_path: CodeGraph SQLite DB 路径
        source_root: 源代码根目录
        router: ModelRouter 实例
        on_status: 状态回调 callback(step, message)

    Returns:
        FixResult with diffs, safety review, and effect estimate.
    """
    if on_status:
        on_status("code_fix", "Starting CodeFixEngine...")

    # Step 1: 解析修复建议和代码定位
    fix_suggestions = _parse_fix_suggestions(diagnosis)
    raw_locations = _parse_code_locations(diagnosis)

    if not raw_locations and not fix_suggestions:
        return FixResult(
            success=False,
            fix_suggestions=[],
            locations=[],
            diffs=[],
            safety_issues=[],
            syntax_check="skipped",
            effect_estimate="(诊断结论中未找到可执行的修复建议)",
            error="No actionable fix suggestions in diagnosis.",
        )

    if on_status:
        on_status("code_fix", f"Parsed {len(raw_locations)} code location(s), {len(fix_suggestions)} suggestion(s)")

    # Step 2: CodeGraph 定位 + 读取源代码
    locations = _resolve_locations_with_codegraph(
        raw_locations, func_name, codegraph_db_path, source_root,
    )

    if not locations:
        # 即使没有精确定位，如果有修复建议仍可尝试
        if fix_suggestions:
            if on_status:
                on_status("code_fix", "No precise code locations found; will generate advice-only fix")
            return FixResult(
                success=True,
                fix_suggestions=fix_suggestions,
                locations=[],
                diffs=[],
                safety_issues=[],
                syntax_check="skipped",
                effect_estimate=estimate_effect(problem, diagnosis, [], router, on_status),
            )
        return FixResult(
            success=False,
            fix_suggestions=fix_suggestions,
            locations=[],
            diffs=[],
            safety_issues=[],
            syntax_check="skipped",
            effect_estimate="(无法定位代码位置)",
            error="Could not resolve code locations from diagnosis.",
        )

    if on_status:
        on_status("code_fix", f"Resolved {len(locations)} location(s) with source context")

    # Step 3: 生成 diff
    diffs = generate_diffs(locations, diagnosis, fix_suggestions, router, on_status)

    # Step 4: 安全审查
    safety_issues = review_safety(diffs, router, on_status)

    # Step 5: 语法检查
    syntax_check = check_syntax(diffs, source_root, locations)

    # Step 6: 效果预估
    effect_estimate = estimate_effect(problem, diagnosis, diffs, router, on_status)

    return FixResult(
        success=True,
        fix_suggestions=fix_suggestions,
        locations=[loc.to_dict() for loc in locations],
        diffs=diffs,
        safety_issues=[issue.to_dict() for issue in safety_issues],
        syntax_check=syntax_check,
        effect_estimate=effect_estimate,
    )


__all__ = [
    "FixResult",
    "FixLocation",
    "SafetyIssue",
    "generate_fix",
    "render_fix_report_markdown",
]
