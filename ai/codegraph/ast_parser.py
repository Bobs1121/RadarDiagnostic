# -*- coding: utf-8 -*-
"""
AST Parser — tree-sitter wrapper for C source code analysis.

Replaces regex-based analysis (analyzer.py) with proper AST traversal.
Provides low-level C parsing utilities that ast_builder.py consumes to
produce CodeGraph nodes and edges.

API:
    parser = CParser()
    tree, source = parser.parse_file(path)
    for node in parser.walk(tree):
        ...
    funcs = parser.extract_functions(tree, source)
    calls = parser.extract_calls(tree, source)
    signals = parser.extract_signal_interfaces(tree, source)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import tree_sitter as ts
import tree_sitter_c as ts_c

log = logging.getLogger(__name__)


# ── Data classes ───────────────────────────────────────────────────────

@dataclass
class ASTNode:
    """A node from the AST with source context."""
    type: str
    text: str
    start_line: int       # 1-indexed
    start_col: int
    end_line: int
    end_col: int
    children: list["ASTNode"] = field(default_factory=list)
    child_count: int = 0


@dataclass
class FunctionDef:
    """Extracted C function definition."""
    name: str
    return_type: str
    params: str           # raw param string
    start_line: int       # 1-indexed
    end_line: int
    is_static: bool = False
    body_text: str = ""
    qualifiers: list[str] = field(default_factory=list)  # static, inline, const


@dataclass
class FunctionCall:
    """Function call site inside a function body."""
    callee: str
    line: int             # 1-indexed
    column: int
    full_text: str        # the whole call expression
    caller_func: str = "" # filled by caller


@dataclass
class SignalInterface:
    """AUTOSAR/RTE signal read/write."""
    direction: str        # "read" or "write"
    signal_name: str
    rte_function: str     # full function name e.g. Rte_Read_BSM_BSDObjectLeft
    line: int
    column: int
    pattern: str = ""     # "Rte_Read", "RteLite_Read", "ReadSignal", "RteComMapping_ReadSignal", etc.


@dataclass
class VariableAccess:
    """Variable read or write."""
    var_name: str
    access_type: str      # "read" or "write"
    line: int
    column: int
    context: str = ""     # surrounding expression


@dataclass
class StateMachine:
    """State machine element."""
    state_var: str        # e.g. systemState, context->systemState
    state_name: str       # state value assigned or compared
    action: str           # "assign" or "compare"
    line: int
    column: int


@dataclass
class IncludeDirective:
    """#include directive."""
    path: str
    is_system: bool       # True if <> brackets
    line: int


# ── Tree-sitter helpers ────────────────────────────────────────────────

def _node_text(node: ts.Node, source: bytes) -> str:
    """Get text of a tree-sitter node."""
    return node.text.decode("utf-8", errors="replace")


def _node_lines(node: ts.Node) -> tuple[int, int, int, int]:
    """Return (start_line, start_col, end_line, end_col), 1-indexed."""
    return (
        node.start_point[0] + 1,
        node.start_point[1],
        node.end_point[0] + 1,
        node.end_point[1],
    )


def _is_descendant_of(node: ts.Node, ancestor: ts.Node) -> bool:
    """Check if node is a descendant of ancestor."""
    return (
        node.start_byte >= ancestor.start_byte
        and node.end_byte <= ancestor.end_byte
    )


def _walk_subtree(node: ts.Node, source: bytes, node_type: Optional[str] = None) -> list[ts.Node]:
    """
    DFS walk returning nodes matching node_type (or all nodes if None).
    Uses tree-sitter 0.21.x cursor API (node.walk()).
    """
    results = []
    cursor = node.walk()
    _walk_recursive(cursor, node_type, results, source)
    return results


def _walk_recursive(cursor: ts.TreeCursor, node_type: Optional[str], results: list, source: bytes):
    if not node_type or cursor.node.type == node_type:
        results.append(cursor.node)
    if cursor.goto_first_child():
        try:
            _walk_recursive(cursor, node_type, results, source)
        finally:
            cursor.goto_parent()
    while cursor.goto_next_sibling():
        _walk_recursive(cursor, node_type, results, source)


def _find_child(node: ts.Node, child_type: str) -> Optional[ts.Node]:
    """Find the first child of a given type."""
    for child in node.children:
        if child.type == child_type:
            return child
    return None


def _find_descendant(node: ts.Node, descendant_type: str) -> Optional[ts.Node]:
    """Find the first descendant of a given type (DFS)."""
    for n in _walk_subtree(node, b"", descendant_type):
        return n
    return None


def _get_string_children(node: ts.Node, source: bytes) -> list[str]:
    """Get text of all string_literal children."""
    return [_node_text(c, source) for c in node.children if c.type == "type_identifier"]


# ── CParser class ──────────────────────────────────────────────────────

class CParser:
    """
    tree-sitter based C parser.

    Usage:
        parser = CParser()
        tree, source = parser.parse_file(Path("foo.c"))
        funcs = parser.extract_functions(tree, source)
    """

    def __init__(self):
        # tree-sitter 0.21.3 + tree-sitter-c 0.21.4 API
        lang_ptr = ts_c.language()
        self._lang = ts.Language(lang_ptr, "c")
        self._parser = ts.Parser()
        self._parser.set_language(self._lang)

    def parse_file(self, path: Path) -> tuple[ts.Tree, str]:
        """Parse a C file. Returns (tree, source_text)."""
        source = path.read_bytes()
        tree = self._parser.parse(source)
        source_text = source.decode("utf-8", errors="replace")
        return tree, source_text

    def parse_bytes(self, source: bytes) -> tuple[ts.Tree, str]:
        """Parse C source from bytes. Returns (tree, source_text)."""
        tree = self._parser.parse(source)
        source_text = source.decode("utf-8", errors="replace")
        return tree, source_text

    def walk(self, tree: ts.Tree, node_type: Optional[str] = None) -> list[ASTNode]:
        """
        Walk the AST, returning ASTNode objects.
        If node_type is set, only yield nodes of that type.
        """
        root = tree.root_node
        source = tree.root_node.text  # This won't work directly; need source from outside
        # We'll just return a flat list for the caller
        if node_type:
            nodes = _walk_subtree(root, b"", node_type)
        else:
            nodes = _walk_subtree(root, b"", None)
        return [_to_ast_node(n, b"") for n in nodes]

    # ── Extractors ──────────────────────────────────────────────────────

    def extract_functions(
        self,
        tree: ts.Tree,
        source: bytes,
    ) -> list[FunctionDef]:
        """Extract all function definitions from the AST."""
        funcs = []
        for node in _walk_subtree(tree.root_node, source, "function_definition"):
            func = _parse_function_def(node, source)
            if func:
                funcs.append(func)
        return funcs

    def extract_calls(
        self,
        tree: ts.Tree,
        source: bytes,
    ) -> list[FunctionCall]:
        """Extract all function call expressions from the AST."""
        calls = []
        for node in _walk_subtree(tree.root_node, source, "call_expression"):
            call = _parse_call_expr(node, source)
            if call:
                calls.append(call)
        return calls

    def extract_calls_in_function(
        self,
        func_node: ts.Node,
        source: bytes,
        func_name: str,
    ) -> list[FunctionCall]:
        """Extract function calls within a specific function body."""
        calls = []
        body = _find_child(func_node, "compound_statement")
        if not body:
            return calls
        for node in _walk_subtree(body, source, "call_expression"):
            call = _parse_call_expr(node, source)
            if call:
                call.caller_func = func_name
                calls.append(call)
        return calls

    def extract_signal_interfaces(
        self,
        tree: ts.Tree,
        source: bytes,
    ) -> list[SignalInterface]:
        """Extract AUTOSAR/RTE signal read/write calls."""
        signals = []
        for node in _walk_subtree(tree.root_node, source, "call_expression"):
            sig = _parse_signal_call(node, source)
            if sig:
                signals.append(sig)
        return signals

    def extract_variable_writes(
        self,
        tree: ts.Tree,
        source: bytes,
    ) -> list[VariableAccess]:
        """Extract variable write accesses (assignment targets)."""
        writes = []
        # assignment_expression where LHS is an identifier
        for node in _walk_subtree(tree.root_node, source, "assignment_expression"):
            lhs = _find_child(node, "identifier")
            if lhs:
                sl, sc, _, _ = _node_lines(lhs)
                writes.append(VariableAccess(
                    var_name=_node_text(lhs, source),
                    access_type="write",
                    line=sl,
                    column=sc,
                    context=_node_text(node, source),
                ))
            # struct->field = or struct.field =
            for child in node.children:
                if child.type in ("field_expression", "pointer_expression"):
                    # Try to extract the base identifier
                    base = _find_descendant(child, "identifier")
                    if base:
                        sl, sc, _, _ = _node_lines(base)
                        writes.append(VariableAccess(
                            var_name=_node_text(base, source),
                            access_type="write",
                            line=sl,
                            column=sc,
                            context=_node_text(node, source),
                        ))
        # ++ and -- operators
        for node in _walk_subtree(tree.root_node, source, "update_expression"):
            ident = _find_child(node, "identifier")
            if ident:
                sl, sc, _, _ = _node_lines(ident)
                writes.append(VariableAccess(
                    var_name=_node_text(ident, source),
                    access_type="write",
                    line=sl,
                    column=sc,
                    context=_node_text(node, source),
                ))
        return writes

    def extract_state_machine(
        self,
        tree: ts.Tree,
        source: bytes,
    ) -> list[StateMachine]:
        """Extract state machine assignments and comparisons."""
        states = []
        # Look for assignments to *systemState* variables
        for node in _walk_subtree(tree.root_node, source, "assignment_expression"):
            text = _node_text(node, source)
            if "systemState" not in text:
                continue
            sl, sc, _, _ = _node_lines(node)
            # Extract state var (LHS)
            lhs_text = _node_text(node.children[0], source) if node.children else ""
            # Extract state value (RHS)
            rhs = node.children[-1] if node.children else None
            rhs_text = _node_text(rhs, source) if rhs else ""
            states.append(StateMachine(
                state_var=lhs_text,
                state_name=rhs_text,
                action="assign",
                line=sl,
                column=sc,
            ))
        # Look for comparisons with systemState in if/switch
        for node in _walk_subtree(tree.root_node, source, "binary_expression"):
            text = _node_text(node, source)
            if "systemState" not in text:
                continue
            sl, sc, _, _ = _node_lines(node)
            # Determine which side has systemState
            parts = text.split("==")
            state_var = parts[0].strip() if parts else ""
            state_val = parts[1].strip() if len(parts) > 1 else ""
            states.append(StateMachine(
                state_var=state_var,
                state_name=state_val,
                action="compare",
                line=sl,
                column=sc,
            ))
        return states

    def extract_includes(
        self,
        tree: ts.Tree,
        source: bytes,
    ) -> list[IncludeDirective]:
        """Extract #include directives."""
        includes = []
        for node in _walk_subtree(tree.root_node, source, "preproc_include"):
            path_node = _find_child(node, "string_literal") or _find_child(node, "preproc_arg")
            if path_node:
                path_text = _node_text(path_node, source).strip("\"<>")
                sl, _, _, _ = _node_lines(node)
                includes.append(IncludeDirective(
                    path=path_text,
                    is_system="<" in _node_text(node, source),
                    line=sl,
                ))
        return includes

    def extract_struct_definitions(
        self,
        tree: ts.Tree,
        source: bytes,
    ) -> list[dict]:
        """Extract struct/typedef definitions."""
        structs = []
        for node in _walk_subtree(tree.root_node, source, "struct_specifier"):
            tag = _find_child(node, "type_identifier")
            body = _find_child(node, "field_declaration_list")
            sl, sc, el, ec = _node_lines(node)
            info = {
                "name": _node_text(tag, source) if tag else "anonymous",
                "start_line": sl,
                "end_line": el,
                "fields": [],
            }
            if body:
                for fd in _walk_subtree(body, source, "field_declaration"):
                    for ident in _walk_subtree(fd, source, "type_identifier"):
                        itext = _node_text(ident, source)
                        isl, _, _, _ = _node_lines(ident)
                        info["fields"].append({"name": itext, "line": isl})
            structs.append(info)
        return structs


# ── Parsing helpers ────────────────────────────────────────────────────

def _to_ast_node(node: ts.Node, source: bytes) -> ASTNode:
    """Convert a tree-sitter Node to our ASTNode dataclass."""
    sl, sc, el, ec = _node_lines(node)
    return ASTNode(
        type=node.type,
        text=_node_text(node, source) if source else "",
        start_line=sl,
        start_col=sc,
        end_line=el,
        end_col=ec,
        child_count=node.child_count,
    )


def _parse_function_def(node: ts.Node, source: bytes) -> Optional[FunctionDef]:
    """Parse a function_definition node into FunctionDef."""
    # In tree-sitter 0.21.x C grammar:
    # function_definition -> storage_class_specifier* + (primitive_type | type_identifier)
    #                     + (function_declarator | declarator) + compound_statement
    declarator = None
    for child in node.children:
        if child.type in ("function_declarator", "pointer_declarator", "declarator"):
            declarator = child
            break
    if not declarator:
        return None

    # Function name from declarator
    func_name_node = _find_descendant(declarator, "identifier")
    if not func_name_node:
        return None
    func_name = _node_text(func_name_node, source)

    # Return type
    ret_type = ""
    for child in node.children:
        if child.type in ("type_identifier", "primitive_type"):
            ret_type = _node_text(child, source)
            break

    # Parameters from parameter_list
    params = ""
    params_node = _find_descendant(declarator, "parameter_list")
    if params_node:
        params_text = _node_text(params_node, source)
        # Strip outer parentheses: "(foo)" -> "foo"
        if params_text.startswith("(") and params_text.endswith(")"):
            params = params_text[1:-1]
        else:
            params = params_text

    # Body
    body = _find_child(node, "compound_statement")
    body_text = _node_text(body, source) if body else ""

    # Qualifiers from direct children
    qualifiers = []
    for child in node.children:
        if child.type == "storage_class_specifier":
            for sc in child.children:
                if sc.type in ("static", "inline"):
                    qualifiers.append(sc.type)
        elif child.type in ("const", "volatile"):
            qualifiers.append(child.type)

    is_static = "static" in qualifiers

    sl, _, el, _ = _node_lines(node)

    return FunctionDef(
        name=func_name,
        return_type=ret_type,
        params=params,
        start_line=sl,
        end_line=el,
        is_static=is_static,
        body_text=body_text,
        qualifiers=qualifiers,
    )


def _parse_call_expr(node: ts.Node, source: bytes) -> Optional[FunctionCall]:
    """Parse a call_expression node into FunctionCall."""
    # call_expression -> function + arguments
    func_part = node.children[0] if node.children else None
    if not func_part:
        return None

    callee = _node_text(func_part, source)
    # For simple identifier calls, callee is just the name
    # For qualified calls (e.g. foo.bar()), keep the full text
    sl, sc, _, _ = _node_lines(node)

    return FunctionCall(
        callee=callee,
        line=sl,
        column=sc,
        full_text=_node_text(node, source),
    )


# ── Signal pattern matching ────────────────────────────────────────────

# RTE function patterns (name -> (pattern, signal_capture_group))
_SIGNAL_PATTERNS = [
    # Rte_Read_Module_Signal(&var)
    (r"^Rte_(?:\w+_)?Read_(?P<module>\w+)_(?P<signal>\w+)$", "Rte_Read"),
    (r"^Rte_(?:\w+_)?Write_(?P<module>\w+)_(?P<signal>\w+)$", "Rte_Write"),
    # RteLite_Read_SignalName(&port)
    (r"^RteLite_Read_(?P<signal>\w+)$", "RteLite_Read"),
    (r"^RteLite_Write_(?P<signal>\w+)$", "RteLite_Write"),
    # ReadSignal(signal) / WriteSignal(signal, &var)
    (r"^ReadSignal$", "ReadSignal"),
    (r"^WriteSignal$", "WriteSignal"),
    # RteComMapping macros
    (r"^RteComMapping_ReadSignal$", "RteComMapping_ReadSignal"),
    (r"^RteComMapping_WriteSignal$", "RteComMapping_WriteSignal"),
]

import re as _re

def _parse_signal_call(node: ts.Node, source: bytes) -> Optional[SignalInterface]:
    """Check if a call_expression is a signal interface call."""
    func_part = node.children[0] if node.children else None
    if not func_part:
        return None

    func_text = _node_text(func_part, source)

    for pattern_str, pattern_name in _SIGNAL_PATTERNS:
        m = _re.match(pattern_str, func_text)
        if m:
            sl, sc, _, _ = _node_lines(node)
            groups = m.groupdict()
            signal_name = groups.get("signal", groups.get("module", ""))
            if "signal" in groups:
                is_read = "Read" in pattern_name
                return SignalInterface(
                    direction="read" if is_read else "write",
                    signal_name=groups["signal"],
                    rte_function=func_text,
                    line=sl,
                    column=sc,
                    pattern=pattern_name,
                )
            elif "module" in groups:
                # Rte_Read_Module_Signal pattern
                is_read = "Read" in pattern_name
                return SignalInterface(
                    direction="read" if is_read else "write",
                    signal_name=groups.get("signal", ""),
                    rte_function=func_text,
                    line=sl,
                    column=sc,
                    pattern=pattern_name,
                )
            else:
                # Bare ReadSignal/WriteSignal
                is_read = "Read" in pattern_name
                return SignalInterface(
                    direction="read" if is_read else "write",
                    signal_name="",  # will be filled from args
                    rte_function=func_text,
                    line=sl,
                    column=sc,
                    pattern=pattern_name,
                )

    return None
