# -*- coding: utf-8 -*-
"""
AST Builder — Bridge from tree-sitter AST to CodeGraph nodes/edges.

Takes the output of ast_parser.CParser and converts AST nodes/dataclasses
into the dict format expected by CodeGraphBuilder.insert_* methods.

Usage:
    builder = ASTBuilder()
    result = builder.build_file(parser, full_path, rel_path)
    # result.nodes = list of node dicts (ready for INSERT)
    # result.edges  = list of edge dicts  (ready for INSERT)

Design goals:
- Drop-in replacement for regex-based analyzer phases 1-7, 9-10
- Produces identical node/edge format as existing builder expects
- Preserves line/column accuracy (1-indexed)
- Adds AST-derived metadata: struct field chains, macro expansion hints
"""
from __future__ import annotations

import logging
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .ast_parser import CParser, FunctionDef, FunctionCall, SignalInterface

log = logging.getLogger(__name__)


# ── Result containers ──────────────────────────────────────────────────

@dataclass
class FileResult:
    """Result of building one file."""
    file_path: str
    hash: str
    line_count: int
    exists: bool = True
    functions: list[dict] = field(default_factory=list)
    calls: list[dict] = field(default_factory=list)
    signals: list[dict] = field(default_factory=list)
    states: list[dict] = field(default_factory=list)
    var_writes: list[dict] = field(default_factory=list)
    includes: list[dict] = field(default_factory=list)
    structs: list[dict] = field(default_factory=list)
    bindings: list[dict] = field(default_factory=list)
    patterns: list[dict] = field(default_factory=list)
    calibration_params: list[dict] = field(default_factory=list)


@dataclass
class BuildResult:
    """Aggregated result for multiple files."""
    files_scanned: int = 0
    files_changed: int = 0
    nodes_added: int = 0
    edges_added: int = 0
    error: Optional[str] = None


# ── AST Builder ────────────────────────────────────────────────────────

class ASTBuilder:
    """
    Convert AST output to CodeGraph node/edge dictionaries.

    The dicts match the format expected by CodeGraphBuilder methods:
    - Function dict: {name, start_line, end_line, return_type, params, is_static, body_text}
    - Call dict:     {caller, callee, line}
    - Signal dict:   {signal_name, access_type, line, rte_call, function}
    - State dict:    {function, state_value, line}
    """

    def __init__(
        self,
        func_keywords: Optional[dict[str, list[str]]] = None,
        calib_patterns: Optional[list[str]] = None,
    ):
        self.parser = CParser()
        # Module binding keywords: module_name -> [function_name_keywords]
        self.func_keywords = func_keywords or {}
        # Calibration parameter patterns
        self.calib_patterns = calib_patterns or [
            r"^\s*#define\s+(?:MAX|MIN|LIMIT|THRESHOLD|DEFAULT|OFFSET|GAIN|FACTOR|SCALE|STEP|DELAY|TIME|TIMEOUT|RADIUS|ANGLE|SPEED|DISTANCE)[A-Z_]+\s+"
        ]

    def build_file(self, full_path: Path, rel_path: str) -> FileResult:
        """
        Parse a single C file with tree-sitter and extract all CodeGraph elements.

        Replaces analyzer.phase1-10 for the given file.
        """
        result = FileResult(
            file_path=rel_path,
            hash="",
            line_count=0,
        )

        if not full_path.exists():
            result.exists = False
            return result

        # Read and hash
        source_bytes = full_path.read_bytes()
        result.hash = hashlib.sha256(source_bytes).hexdigest()[:16]
        source_text = source_bytes.decode("utf-8", errors="replace")
        result.line_count = source_text.count("\n") + 1

        # Parse
        try:
            tree, _ = self.parser.parse_file(full_path)
        except Exception as e:
            log.warning("AST parse failed for %s: %s", rel_path, e)
            return result

        # Extract functions
        func_defs = self.parser.extract_functions(tree, source_bytes)
        result.functions = [self._func_def_to_dict(f, rel_path) for f in func_defs]

        # Extract calls (per function for caller context)
        for func_def in func_defs:
            func_node = self._find_func_node(tree, source_bytes, func_def.name)
            if func_node:
                calls = self.parser.extract_calls_in_function(
                    func_node, source_bytes, func_def.name,
                )
                result.calls.extend([self._call_to_dict(c) for c in calls])

        # Extract signal interfaces
        signals = self.parser.extract_signal_interfaces(tree, source_bytes)
        result.signals = [self._signal_to_dict(s, self._find_caller(tree, source_bytes, s.line)) for s in signals]

        # Extract state machine
        states_raw = self.parser.extract_state_machine(tree, source_bytes)
        result.states = [self._state_to_dict(s, self._find_caller(tree, source_bytes, s.line)) for s in states_raw]

        # Extract variable writes
        writes = self.parser.extract_variable_writes(tree, source_bytes)
        result.var_writes = [self._var_write_to_dict(w, self._find_caller(tree, source_bytes, w.line)) for w in writes]

        # Extract includes
        includes = self.parser.extract_includes(tree, source_bytes)
        result.includes = [self._include_to_dict(i) for i in includes]

        # Extract structs
        result.structs = self.parser.extract_struct_definitions(tree, source_bytes)

        # Module bindings
        result.bindings = self._extract_module_bindings(result.functions)

        # Calibration params (only for header files)
        if rel_path.endswith(".h"):
            result.calibration_params = self._extract_calibration_params(source_text, rel_path)

        return result

    # ── Converters ───────────────────────────────────────────────────────

    def _func_def_to_dict(self, func: FunctionDef, file_path: str) -> dict:
        """FunctionDef -> dict matching existing builder format."""
        return {
            "name": func.name,
            "start_line": func.start_line,
            "end_line": func.end_line,
            "return_type": func.return_type,
            "params": func.params,
            "is_static": func.is_static,
            "body_text": func.body_text,
            "qualifiers": func.qualifiers,
            "file_path": file_path,
        }

    def _call_to_dict(self, call: FunctionCall) -> dict:
        """FunctionCall -> dict matching existing builder format."""
        return {
            "caller": call.caller_func,
            "callee": call.callee,
            "line": call.line,
            "column": call.column,
            "full_text": call.full_text,
        }

    def _signal_to_dict(self, sig: SignalInterface, caller: str) -> dict:
        """SignalInterface -> dict matching existing builder format."""
        return {
            "signal_name": sig.signal_name,
            "signal_module": "",
            "access_type": sig.direction,  # "read" or "write"
            "line": sig.line,
            "column": sig.column,
            "rte_call": sig.rte_function,
            "pattern": sig.pattern,
            "function": caller,
        }

    def _state_to_dict(self, state, caller: str) -> dict:
        """StateMachine -> dict matching existing builder format."""
        return {
            "function": caller,
            "state_value": state.state_name,
            "state_var": state.state_var,
            "action": state.action,
            "line": state.line,
            "column": state.column,
        }

    def _var_write_to_dict(self, var, caller: str) -> dict:
        """VariableAccess -> dict for variable tracking."""
        return {
            "var_name": var.var_name,
            "access_type": var.access_type,
            "line": var.line,
            "column": var.column,
            "context": var.context,
            "function": caller,
        }

    def _include_to_dict(self, inc) -> dict:
        """IncludeDirective -> dict."""
        return {
            "path": inc.path,
            "is_system": inc.is_system,
            "line": inc.line,
        }

    # ── Module binding ──────────────────────────────────────────────────

    def _extract_module_bindings(self, functions: list[dict]) -> list[dict]:
        """Match functions to modules based on keywords."""
        bindings = []
        for func in functions:
            fname = func["name"].lower()
            for module, keywords in self.func_keywords.items():
                for kw in keywords:
                    if kw.lower() in fname:
                        bindings.append({
                            "function": func["name"],
                            "module": module,
                            "binding_method": "keyword",
                        })
                        break
                else:
                    continue
                break
        return bindings

    # ── Calibration params ───────────────────────────────────────────────

    def _extract_calibration_params(self, source_text: str, file_path: str) -> list[dict]:
        """Extract #define calibration parameters."""
        import re
        params = []
        for pattern in self.calib_patterns:
            for m in re.finditer(pattern, source_text):
                line_num = source_text[:m.start()].count("\n") + 1
                # Extract name and value
                rest = m.group(0).strip()
                parts = rest.split()
                if len(parts) >= 3:
                    name = parts[2]
                    try:
                        value = float(parts[3])
                    except (ValueError, IndexError):
                        value = None
                    params.append({
                        "name": name,
                        "value": value,
                        "line": line_num,
                        "source_file": file_path,
                        "category": "calibration",
                    })
        return params

    # ── AST helpers ──────────────────────────────────────────────────────

    def _find_func_node(self, tree, source: bytes, func_name: str):
        """Find the function_definition node for a given function name."""
        from .ast_parser import _walk_subtree, _node_text
        for node in _walk_subtree(tree.root_node, source, "function_definition"):
            declarator = None
            for child in node.children:
                if child.type in ("function_declarator", "pointer_declarator", "declarator"):
                    declarator = child
                    break
            if declarator:
                for c in declarator.children:
                    if c.type == "identifier" and _node_text(c, source) == func_name:
                        return node
        return None

    def _find_caller(self, tree, source: bytes, line: int) -> str:
        """Find the function name that contains the given line."""
        from .ast_parser import _walk_subtree
        for node in _walk_subtree(tree.root_node, source, "function_definition"):
            start = node.start_point[0] + 1  # 1-indexed
            end = node.end_point[0] + 1
            if start <= line <= end:
                # Extract function name
                declarator = None
                for child in node.children:
                    if child.type in ("function_declarator", "pointer_declarator", "declarator"):
                        declarator = child
                        break
                if declarator:
                    for c in declarator.children:
                        if c.type == "identifier":
                            return c.text.decode("utf-8", errors="replace")
                break
        return ""

    # ── Batch build ──────────────────────────────────────────────────────

    def build_files(self, files: list[tuple[Path, str]]) -> list[FileResult]:
        """Build multiple files. Returns list of FileResult."""
        results = []
        for full_path, rel_path in files:
            try:
                result = self.build_file(full_path, rel_path)
                results.append(result)
            except Exception as e:
                log.error("AST build failed for %s: %s", rel_path, e, exc_info=True)
                results.append(FileResult(
                    file_path=rel_path,
                    hash="",
                    line_count=0,
                ))
        return results
