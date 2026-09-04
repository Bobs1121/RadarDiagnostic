# -*- coding: utf-8 -*-
"""
AST-based Behaviour Pattern Extractor
======================================

Replaces the regex-based ``ai/pattern_extractor.py`` with tree-sitter AST
traversal.  The six pattern types remain the same:

* **HoldRelease** — ``if (cond) { flag = false; time = 0 }``
* **HoldEntry**   — ``if (cond) { flag = true; ... }``
* **Accumulate**  — ``time += dt`` paired with ``time = 0`` reset.
* **Hysteresis**  — asymmetric enter/exit thresholds.
* **Debounce**    — ``cnt++ / if (cnt >= N)`` latches.
* **EdgeTrigger** — ``prev == 0 && cur != 0`` predicates.

AST advantages over regex
-------------------------
1. **Brace matching** — nested ``{}`` no longer breaks body boundaries.
2. **Scope awareness** — patterns are attributed to the enclosing function
   via the AST hierarchy, not a backward line scan.
3. **Multi-line conditions** — no heuristic parenthesis counting; the AST
   node text is the full condition.
4. **False-positive reduction** — we can distinguish assignment targets
   (LHS of ``=``) from reads, struct fields vs local variables, etc.

API
---
    extractor = ASTPatternExtractor(source_root, target_files=...)
    patterns = extractor.extract_all()          # list[CodePattern]
    summary  = summarise_patterns(patterns)     # str

Cache output: ``source_docs/code_patterns_ast.json``
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Iterable, Optional

import tree_sitter as ts

from .ast_parser import (
    CParser,
    FunctionDef,
    _walk_subtree,
    _node_text,
    _node_lines,
    _find_child,
)

log = logging.getLogger(__name__)

__all__ = [
    "CodePattern",
    "ASTPatternExtractor",
    "PATTERN_TYPES",
    "load_patterns",
    "summarise_patterns",
]

# ── Pattern catalogue (identical to regex version) ────────────────────

PATTERN_TYPES = {
    "HoldRelease":  "if (cond) { flag=false; time=0 } — 保持失效",
    "HoldEntry":    "if (cond) { flag=true; ... }   — 保持进入",
    "Accumulate":   "time += dt 配合 time = 0        — 时间累积器",
    "Hysteresis":   "enter_thresh != exit_thresh    — 阈值迟滞",
    "Debounce":     "cnt++ / if (cnt >= N)          — 防抖计数",
    "EdgeTrigger":  "prev==A && cur==B              — 边沿触发",
}

# ADAS function keywords (mirrors legacy version)
_FUNC_KEYWORDS = {
    "FCTA": ["fcta", "fctaSkip", "bFcta"],
    "FCTB": ["fctb", "bFctb", "fFctb"],
    "RCTA": ["rcta", "rctaSkip", "bRcta"],
    "RCTB": ["rctb", "bRctb", "fRctb"],
    "BSD":  ["bsd", "bBsd", "bsdSkip"],
    "LCA":  ["lca", "bLca"],
    "DOW":  ["dow", "bDow"],
    "RCW":  ["rcw", "bRcw"],
}

# Minimum body assignments to consider a pattern match
_MIN_HOLD_SIZE = 2
_MAX_BODY_DESCENDANTS = 80   # skip enormous blocks


# ── Data classes ──────────────────────────────────────────────────────

@dataclass
class CodePattern:
    """One behavioural pattern located in the source code."""

    pattern_type: str
    file: str
    line_start: int
    line_end: int
    function: str = ""
    trigger_condition: str = ""
    trigger_variables: list[str] = field(default_factory=list)
    consequence_variables: list[str] = field(default_factory=list)
    adas_function: str = ""
    snippet: str = ""
    notes: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


# ── Helpers ───────────────────────────────────────────────────────────

def _leaf_name(ident: str) -> str:
    """Strip struct/pointer prefixes: ``ctx->bFlag`` → ``bFlag``."""
    for sep in ("->", "."):
        if sep in ident:
            ident = ident.rsplit(sep, 1)[-1]
    return ident


def _is_flag_like(name: str) -> bool:
    leaf = _leaf_name(name).lower()
    return (leaf.startswith("b")
            and any(k in leaf for k in ("flg", "flag", "keep", "enable")))


def _is_timer_like(name: str) -> bool:
    leaf = _leaf_name(name).lower()
    return leaf.startswith("f") or any(k in leaf for k in ("time", "timer", "event"))


def _extract_idents_from_expr(expr: str) -> list[str]:
    """Pull identifiers out of an expression string (non-AST fallback)."""
    keywords = {"if", "else", "return", "true", "false", "TRUE", "FALSE",
                "NULL", "while", "for", "do", "switch", "case", "break",
                "continue", "static", "const", "volatile"}
    result = []
    for tok in re.findall(r'[A-Za-z_]\w*', expr):
        if tok in keywords or tok[0].isdigit():
            continue
        if tok not in result:
            result.append(tok)
    return result


def _guess_adas_function(haystack: str) -> str:
    scores: dict[str, int] = {}
    hl = haystack.lower()
    for func_name, kws in _FUNC_KEYWORDS.items():
        hits = sum(1 for kw in kws if kw.lower() in hl)
        if hits:
            scores[func_name] = hits
    return max(scores.items(), key=lambda kv: kv[1])[0] if scores else ""


# ── AST helpers for finding function context ──────────────────────────

def _find_enclosing_function(
    root: ts.Node, line: int, source: bytes,
) -> str:
    """Find the function_definition that contains *line* (1-indexed)."""
    for node in _walk_subtree(root, source, "function_definition"):
        start = node.start_point[0] + 1
        end = node.end_point[0] + 1
        if start <= line <= end:
            for child in node.children:
                if child.type in ("function_declarator", "declarator"):
                    for gc in child.children:
                        if gc.type == "identifier":
                            return _node_text(gc, source)
            break
    return ""


def _count_descendants(node: ts.Node) -> int:
    """Rough descendant count without allocating."""
    count = 0
    stack = [node]
    while stack:
        n = stack.pop()
        count += 1
        for c in n.children:
            stack.append(c)
    return count


# ── Pattern detectors ─────────────────────────────────────────────────

class _HoldDetector:
    """Detect HoldRelease and HoldEntry patterns via AST.

    Strategy: walk ``if`` statements, inspect the compound_statement body
    for assignment expressions that zero (or set true) flag-like and
    timer-like variables.
    """

    @staticmethod
    def detect(
        tree: ts.Tree,
        source: bytes,
        source_text: str,
        rel_path: str,
    ) -> list[CodePattern]:
        patterns: list[CodePattern] = []

        if_nodes = _walk_subtree(tree.root_node, source, "if_statement")

        for if_node in if_nodes:
            # Condition — in tree-sitter C it's "parenthesized_expression"
            cond_child = _find_child(if_node, "parenthesized_expression")
            if not cond_child:
                continue
            cond_text = _node_text(cond_child, source)
            # Strip outer parentheses
            if cond_text.startswith("(") and cond_text.endswith(")"):
                cond_text = cond_text[1:-1]

            # Body (compound_statement)
            body = _find_child(if_node, "compound_statement")
            if not body:
                continue

            # Skip huge bodies
            if _count_descendants(body) > _MAX_BODY_DESCENDANTS:
                continue

            # Collect assignment targets inside body
            assignments = _collect_assignments_in_node(body, source)
            if len(assignments) < _MIN_HOLD_SIZE:
                continue

            # Classify: HoldRelease (zeroing) vs HoldEntry (setting true)
            zero_vars = [a["var"] for a in assignments if a["is_zero"]]
            true_vars = [a["var"] for a in assignments if a["is_true"]]

            if zero_vars and _looks_like_hold_clear(zero_vars):
                # HoldRelease
                sl, _, el, _ = _node_lines(if_node)
                enclosing = _find_enclosing_function(tree.root_node, sl, source)
                snippet_lines = source_text.split("\n")
                snippet = "\n".join(snippet_lines[sl - 1:el])[:800]
                trigger_vars = _extract_idents_from_expr(cond_text)
                adas = _guess_adas_function(cond_text + " " + " ".join(zero_vars))

                patterns.append(CodePattern(
                    pattern_type="HoldRelease",
                    file=rel_path,
                    line_start=sl,
                    line_end=el,
                    function=enclosing,
                    trigger_condition=cond_text[:200],
                    trigger_variables=trigger_vars,
                    consequence_variables=zero_vars,
                    adas_function=adas,
                    snippet=snippet,
                    notes="AST检测到：触发条件满足时保持标志位清零 + 累积器归零，"
                           "任何瞬态满足都会打断保持。",
                ))

            elif true_vars and any(_is_flag_like(v) for v in true_vars):
                # HoldEntry
                sl, _, el, _ = _node_lines(if_node)
                enclosing = _find_enclosing_function(tree.root_node, sl, source)
                snippet_lines = source_text.split("\n")
                snippet = "\n".join(snippet_lines[sl - 1:el])[:800]
                trigger_vars = _extract_idents_from_expr(cond_text)
                adas = _guess_adas_function(cond_text + " " + " ".join(true_vars))

                patterns.append(CodePattern(
                    pattern_type="HoldEntry",
                    file=rel_path,
                    line_start=sl,
                    line_end=el,
                    function=enclosing,
                    trigger_condition=cond_text[:200],
                    trigger_variables=trigger_vars,
                    consequence_variables=true_vars,
                    adas_function=adas,
                    snippet=snippet,
                    notes="AST检测到：触发条件满足时保持标志位置位，进入保持状态。",
                ))

        return patterns


def _looks_like_hold_clear(zero_vars: list[str]) -> bool:
    """HoldRelease has >=1 flag AND >=1 timer, or >=2 flag-like vars."""
    has_flag = any(_is_flag_like(v) for v in zero_vars)
    has_timer = any(_is_timer_like(v) for v in zero_vars)
    if has_flag and has_timer:
        return True
    return len(zero_vars) >= 2 and has_flag


def _collect_assignments_in_node(
    node: ts.Node, source: bytes,
) -> list[dict]:
    """Return [{var, is_zero, is_true, line}, ...] from assignment expressions."""
    results = []
    for assign in _walk_subtree(node, source, "assignment_expression"):
        # LHS: first child is usually identifier or field_expression
        lhs = assign.children[0] if assign.children else None
        rhs = assign.children[-1] if assign.children else None
        if not lhs or not rhs:
            continue

        var_text = _node_text(lhs, source)
        rhs_text = _node_text(rhs, source).strip()

        is_zero = rhs_text in ("false", "0.0f", "0.0", "0", "FALSE", "(bool)0",
                               "(bool)false", "0u", "(uint8_t)0")
        is_true = rhs_text in ("true", "1", "TRUE", "(bool)1",
                               "(bool)true", "1u")

        results.append({
            "var": var_text,
            "is_zero": is_zero,
            "is_true": is_true,
            "line": _node_lines(assign)[0],
        })

    # Also check update_expression (++, --)
    for upd in _walk_subtree(node, source, "update_expression"):
        # Variable can be identifier, field_expression, etc.
        var_node = None
        for child in upd.children:
            if child.type not in ("++", "--"):
                var_node = child
                break
        if var_node:
            results.append({
                "var": _node_text(var_node, source),
                "is_zero": False,
                "is_true": False,
                "line": _node_lines(upd)[0],
            })

    return results


class _AccumulateDetector:
    """Detect Accumulate patterns: ``var += dt`` with nearby ``var = 0`` reset.

    AST approach: find all ``augmented_assignment`` (+=) and regular
    assignments (= 0) to the same variable within a function scope.
    """

    RADIUS = 30  # lines between accum and reset to be considered related

    @staticmethod
    def detect(
        tree: ts.Tree,
        source: bytes,
        source_text: str,
        rel_path: str,
    ) -> list[CodePattern]:
        patterns: list[CodePattern] = []

        # Collect augmented assignments (+=, -=)
        # In tree-sitter C, += is assignment_expression with a "+=" child token
        accum_by_var: dict[str, ts.Node] = {}
        for node in _walk_subtree(tree.root_node, source, "assignment_expression"):
            op_child = None
            for child in node.children:
                if child.type in ("+=", "-="):
                    op_child = child
                    break
            if op_child is None:
                continue
            lhs = node.children[0] if node.children else None
            if lhs:
                var_text = _node_text(lhs, source)
                accum_by_var[var_text] = node

        # Also look for update_expression (var++)
        for node in _walk_subtree(tree.root_node, source, "update_expression"):
            # The variable can be an identifier, field_expression, or other
            var_node = None
            for child in node.children:
                if child.type not in ("++", "--"):
                    var_node = child
                    break
            if var_node:
                var_text = _node_text(var_node, source)
                if var_text not in accum_by_var:
                    accum_by_var[var_text] = node

        # For each accumulator, find nearby reset (= 0)
        for var, accum_node in accum_by_var.items():
            accum_line = _node_lines(accum_node)[0]
            reset_node = _find_nearby_zero_assign(
                tree.root_node, source, var, accum_line, _AccumulateDetector.RADIUS,
            )
            if reset_node is None:
                continue

            reset_line = _reset_line(reset_node, source)
            start = min(accum_line, reset_line)
            end = max(accum_line, reset_line)
            enclosing = _find_enclosing_function(tree.root_node, start, source)

            snippet_lines = source_text.split("\n")
            snippet = "\n".join(snippet_lines[start - 1:end])[:600]
            adas = _guess_adas_function(var)

            patterns.append(CodePattern(
                pattern_type="Accumulate",
                file=rel_path,
                line_start=start,
                line_end=end,
                function=enclosing,
                trigger_condition=f"{var} += dt ... {var} = 0",
                trigger_variables=[var],
                consequence_variables=[var],
                adas_function=adas,
                snippet=snippet,
                notes="AST检测到：时间累积器；被重置的条件一旦频繁触发，累积永远达不到阈值。",
            ))

        return patterns


def _find_nearby_zero_assign(
    root: ts.Node,
    source: bytes,
    var: str,
    target_line: int,
    radius: int,
) -> Optional[ts.Node]:
    """Find ``var = 0`` within ±radius lines."""
    lo = max(1, target_line - radius)
    hi = target_line + radius
    for node in _walk_subtree(root, source, "assignment_expression"):
        if len(node.children) < 2:
            continue
        lhs = node.children[0]
        rhs = node.children[-1]
        lhs_text = _node_text(lhs, source).strip()
        if lhs_text != var:
            continue
        rhs_text = _node_text(rhs, source).strip()
        if rhs_text not in ("0", "0.0f", "0.0", "false", "FALSE", "0u",
                            "(uint8_t)0", "(bool)0"):
            continue
        nl = _node_lines(node)[0]
        if lo <= nl <= hi and nl != target_line:
            return node
    return None


def _reset_line(node: ts.Node, source: bytes) -> int:
    return _node_lines(node)[0]


class _HysteresisDetector:
    """Detect Hysteresis: asymmetric thresholds on the same variable.

    Strategy: within a function, find two comparisons to the same variable
    using different constant thresholds (e.g. ``x > THRESH_HI`` vs ``x < THRESH_LO``).
    """

    @staticmethod
    def detect(
        tree: ts.Tree,
        source: bytes,
        source_text: str,
        rel_path: str,
    ) -> list[CodePattern]:
        patterns: list[CodePattern] = []

        # Find all function bodies
        func_nodes = _walk_subtree(tree.root_node, source, "function_definition")

        for func_node in func_nodes:
            body = _find_child(func_node, "compound_statement")
            if not body:
                continue

            # Collect binary comparisons (>, <, >=, <=) involving identifiers and constants
            comparisons = _extract_comparisons(body, source)
            if len(comparisons) < 2:
                continue

            # Group by variable
            by_var: dict[str, list[dict]] = {}
            for comp in comparisons:
                by_var.setdefault(comp["var"], []).append(comp)

            for var, comps in by_var.items():
                if len(comps) < 2:
                    continue
                # Look for asymmetric thresholds
                thresholds = set()
                for c in comps:
                    if c["const_val"] is not None:
                        thresholds.add(c["const_val"])

                if len(thresholds) >= 2:
                    sl, _, el, _ = _node_lines(func_node)
                    func_name_node = _find_child(func_node, "function_declarator")
                    func_name = ""
                    if func_name_node:
                        for gc in func_name_node.children:
                            if gc.type == "identifier":
                                func_name = _node_text(gc, source)
                                break

                    snippet_lines = source_text.split("\n")
                    snippet = "\n".join(snippet_lines[sl - 1:min(el, sl + 20)])[:600]
                    adas = _guess_adas_function(var)

                    patterns.append(CodePattern(
                        pattern_type="Hysteresis",
                        file=rel_path,
                        line_start=sl,
                        line_end=el,
                        function=func_name,
                        trigger_condition=f"{var} 使用多个阈值: {sorted(thresholds)}",
                        trigger_variables=[var],
                        consequence_variables=[],
                        adas_function=adas,
                        snippet=snippet,
                        notes=f"AST检测到：变量 {var} 在同一函数中使用 {len(thresholds)} 个不同阈值，"
                               "存在迟滞行为。",
                    ))

        return patterns


def _extract_comparisons(
    body: ts.Node, source: bytes,
) -> list[dict]:
    """Extract binary comparisons (>, <, >=, <=) with constant thresholds."""
    results = []
    for node in _walk_subtree(body, source, "binary_expression"):
        op_child = None
        for child in node.children:
            if child.type in (">", "<", ">=", "<="):
                op_child = child
                break
        if op_child is None or len(node.children) < 3:
            continue

        left = node.children[0]
        right = node.children[2]
        left_text = _node_text(left, source).strip()
        right_text = _node_text(right, source).strip()

        # Determine which side is the variable and which is the constant
        var = None
        const_val = None
        if _looks_like_constant(right_text):
            var = left_text
            try:
                clean = right_text.strip().rstrip("fFuUlLuULUl")
                const_val = float(clean)
            except ValueError:
                const_val = right_text  # keep as string for macro names
        elif _looks_like_constant(left_text):
            var = right_text
            try:
                clean = left_text.strip().rstrip("fFuUlLuULUl")
                const_val = float(clean)
            except ValueError:
                const_val = left_text

        if var and const_val is not None:
            results.append({
                "var": var,
                "op": op_child.type,
                "const_val": const_val,
                "line": _node_lines(node)[0],
            })

    return results


def _looks_like_constant(text: str) -> bool:
    """Check if a string looks like a numeric constant or macro."""
    try:
        # Strip C-style suffixes: f, F, u, U, l, L, ul, UL
        clean = text.strip().rstrip("fFuUlLuULUl")
        float(clean)
        return True
    except ValueError:
        pass
    # Macro-style constants
    return bool(re.match(r'^[A-Z][A-Z0-9_]+$', text))


class _DebounceDetector:
    """Detect Debounce: counter increment + threshold check.

    AST: look for ``cnt++`` (update_expression) and ``cnt >= N`` in the same
    function, or ``cnt++`` followed by ``if (cnt >= N)``.
    """

    @staticmethod
    def detect(
        tree: ts.Tree,
        source: bytes,
        source_text: str,
        rel_path: str,
    ) -> list[CodePattern]:
        patterns: list[CodePattern] = []

        func_nodes = _walk_subtree(tree.root_node, source, "function_definition")

        for func_node in func_nodes:
            body = _find_child(func_node, "compound_statement")
            if not body:
                continue

            # Find update expressions (++ / --)
            inc_vars: dict[str, int] = {}
            for upd in _walk_subtree(body, source, "update_expression"):
                # The variable can be identifier, field_expression, etc.
                var_node = None
                for child in upd.children:
                    if child.type not in ("++", "--"):
                        var_node = child
                        break
                if var_node:
                    var = _node_text(var_node, source)
                    inc_vars[var] = _node_lines(upd)[0]

            # Find threshold comparisons (>= with constant)
            # In tree-sitter C, >= is a binary_expression with ">" child token
            thresh_checks: dict[str, list[tuple[int, str]]] = {}
            for cmp in _walk_subtree(body, source, "binary_expression"):
                op = None
                for child in cmp.children:
                    if child.type in (">=", "<="):
                        op = child
                        break
                if op is None or len(cmp.children) < 3:
                    continue
                left_text = _node_text(cmp.children[0], source).strip()
                right_text = _node_text(cmp.children[2], source).strip()

                # Check if LHS is an increment variable and RHS is a constant
                if left_text in inc_vars and _looks_like_constant(right_text):
                    thresh_checks.setdefault(left_text, []).append(
                        (_node_lines(cmp)[0], right_text))

            for var, checks in thresh_checks.items():
                if not checks:
                    continue
                inc_line = inc_vars[var]
                check_line = checks[0][0]
                start = min(inc_line, check_line)
                end = max(inc_line, check_line)

                func_name_node = _find_child(func_node, "function_declarator")
                func_name = ""
                if func_name_node:
                    for gc in func_name_node.children:
                        if gc.type == "identifier":
                            func_name = _node_text(gc, source)
                            break

                snippet_lines = source_text.split("\n")
                snippet = "\n".join(snippet_lines[start - 1:end])[:600]
                adas = _guess_adas_function(var)

                patterns.append(CodePattern(
                    pattern_type="Debounce",
                    file=rel_path,
                    line_start=start,
                    line_end=end,
                    function=func_name,
                    trigger_condition=f"{var}++ ... if ({var} >= {checks[0][1]})",
                    trigger_variables=[var],
                    consequence_variables=[],
                    adas_function=adas,
                    snippet=snippet,
                    notes=f"AST检测到：{var} 计数后需达到 {checks[0][1]} 才触发，"
                           "防抖/去抖行为。",
                ))

        return patterns


class _EdgeTriggerDetector:
    """Detect EdgeTrigger: prev == A && cur != B predicates.

    AST: find binary expressions with && (logical_and) where one side compares
    a 'prev' variable and the other compares a 'cur' variable.
    """

    _EDGE_KEYWORDS = {"prev", "last", "old", "previous", "cur", "curr",
                      "current", "new"}

    @staticmethod
    def detect(
        tree: ts.Tree,
        source: bytes,
        source_text: str,
        rel_path: str,
    ) -> list[CodePattern]:
        patterns: list[CodePattern] = []

        # Find binary expressions with && (logical AND)
        # In tree-sitter C, && is represented as a binary_expression with
        # a child token of type "&&"
        for node in _walk_subtree(tree.root_node, source, "binary_expression"):
            # Check if this is a && expression
            is_and = False
            for child in node.children:
                if child.type == "&&":
                    is_and = True
                    break
            if not is_and or len(node.children) < 3:
                continue

            left_text = _node_text(node.children[0], source)
            right_text = _node_text(node.children[2], source)
            combined = (left_text + " " + right_text).lower()

            # Check if it references prev/cur or last/current style vars
            edge_vars = [kw for kw in _EdgeTriggerDetector._EDGE_KEYWORDS
                         if kw in combined]
            if len(edge_vars) < 2:
                continue

            sl, _, el, _ = _node_lines(node)
            enclosing = _find_enclosing_function(tree.root_node, sl, source)

            snippet_lines = source_text.split("\n")
            snippet = "\n".join(snippet_lines[sl - 1:sl + 2])[:400]
            all_idents = _extract_idents_from_expr(left_text + " " + right_text)
            adas = _guess_adas_function(left_text + " " + right_text)

            patterns.append(CodePattern(
                pattern_type="EdgeTrigger",
                file=rel_path,
                line_start=sl,
                line_end=el,
                function=enclosing,
                trigger_condition=combined[:200],
                trigger_variables=all_idents,
                consequence_variables=[],
                adas_function=adas,
                snippet=snippet,
                notes="AST检测到：边沿触发条件（prev/cur 比较），信号变化时才激活。",
            ))

        return patterns


# ── Main Extractor ─────────────────────────────────────────────────────

class ASTPatternExtractor:
    """
    Scan a source tree using tree-sitter AST and return every CodePattern match.

    API:
        extractor = ASTPatternExtractor(source_root, target_files=[...])
        patterns = extractor.extract_all()  # list[CodePattern]
    """

    TARGET_FILES: list[str] = [
        "coem/GWM_B26/components/AswPerception/func/adasFunc.c",
        "coem/GWM_B26/components/AswIf/ASW_IN/ASWIN_SystemState.c",
        "adas/symmetry/perception/src/objAttribCal.c",
        "adas/symmetry/perception/src/track.c",
    ]

    def __init__(
        self,
        source_root: Path,
        cache_dir: Optional[Path] = None,
        target_files: Optional[Iterable[str]] = None,
    ):
        self.source_root = Path(source_root)
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.target_files = list(target_files) if target_files else list(self.TARGET_FILES)
        self.parser = CParser()

    def extract_all(self, use_cache: bool = True) -> list[CodePattern]:
        """Run all detectors over all target files."""
        if use_cache and self.cache_dir is not None:
            cached = self._load_cached(self._files_hash())
            if cached is not None:
                return cached

        out: list[CodePattern] = []
        for rel in self.target_files:
            full = self.source_root / rel
            if not full.exists():
                continue
            try:
                patterns = self._scan_file(full, rel)
                out.extend(patterns)
            except Exception as e:
                log.warning("AST pattern scan failed for %s: %s", rel, e, exc_info=True)

        if self.cache_dir is not None:
            self._save_cache(out, self._files_hash())

        return out

    def _scan_file(self, full_path: Path, rel_path: str) -> list[CodePattern]:
        """Parse a single file with AST and run all detectors."""
        source_bytes = full_path.read_bytes()
        source_text = source_bytes.decode("utf-8", errors="replace")

        try:
            tree, _ = self.parser.parse_file(full_path)
        except Exception as e:
            log.warning("AST parse failed for %s: %s", rel_path, e)
            return []

        patterns: list[CodePattern] = []

        # Run all detectors
        patterns.extend(_HoldDetector.detect(tree, source_bytes, source_text, rel_path))
        patterns.extend(_AccumulateDetector.detect(tree, source_bytes, source_text, rel_path))
        patterns.extend(_HysteresisDetector.detect(tree, source_bytes, source_text, rel_path))
        patterns.extend(_DebounceDetector.detect(tree, source_bytes, source_text, rel_path))
        patterns.extend(_EdgeTriggerDetector.detect(tree, source_bytes, source_text, rel_path))

        log.info("AST patterns in %s: %d", rel_path, len(patterns))
        return patterns

    # ── Cache ────────────────────────────────────────────────────────

    def _files_hash(self) -> str:
        h = hashlib.sha256()
        for rel in self.target_files:
            full = self.source_root / rel
            if full.exists():
                try:
                    data = full.read_bytes()
                except Exception:
                    continue
                h.update(rel.encode("utf-8"))
                h.update(hashlib.sha256(data).digest())
        return h.hexdigest()

    def _cache_path(self) -> Optional[Path]:
        if not self.cache_dir:
            return None
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        return self.cache_dir / "code_patterns_ast.json"

    def _load_cached(self, expected_hash: str) -> Optional[list[CodePattern]]:
        path = self._cache_path()
        if not path or not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        if data.get("source_hash") != expected_hash:
            return None
        return [CodePattern(**p) for p in data.get("patterns", [])]

    def _save_cache(self, patterns: list[CodePattern], source_hash: str) -> None:
        path = self._cache_path()
        if not path:
            return
        payload = {
            "source_hash": source_hash,
            "extractor": "ast",
            "pattern_type_catalogue": PATTERN_TYPES,
            "patterns": [p.to_dict() for p in patterns],
        }
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


# ── Public helpers (drop-in for legacy) ────────────────────────────────

def load_patterns(cache_dir: Path) -> list[CodePattern]:
    """Load patterns from AST cache file."""
    path = Path(cache_dir) / "code_patterns_ast.json"
    if not path.exists():
        # Fallback to legacy cache
        legacy = Path(cache_dir) / "code_patterns.json"
        if not legacy.exists():
            return []
        path = legacy
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return [CodePattern(**p) for p in data.get("patterns", [])]


def summarise_patterns(patterns: list[CodePattern]) -> str:
    """Condense patterns into a compact overview for expert prompts."""
    if not patterns:
        return "(未识别出时序行为模式)"

    by_type: dict[str, list[CodePattern]] = {}
    for p in patterns:
        by_type.setdefault(p.pattern_type, []).append(p)

    parts: list[str] = [f"### 代码行为模式 ({len(patterns)}处)"]
    for ptype, group in by_type.items():
        parts.append(f"\n**{ptype}** x {len(group)}")
        for p in group[:10]:
            scope = f"{p.file}:{p.line_start}-{p.line_end}"
            if p.function:
                scope += f" ({p.function})"
            parts.append(f"  - {scope}")
            parts.append(f"    ADAS: {p.adas_function or '?'}  "
                         f"触发: `{p.trigger_condition[:80]}`")
            parts.append(f"    结果: {', '.join(p.consequence_variables)}")
    return "\n".join(parts)
