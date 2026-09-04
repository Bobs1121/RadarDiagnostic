# -*- coding: utf-8 -*-
"""
AST-based State Machine Extractor
==================================

Extracts finite state machines (FSM) from C source code using tree-sitter AST.

Supports two FSM patterns:
  1. **switch-case** on a state variable
     ``switch (ctx->state) { case STATE_A: ... ctx->state = STATE_B; ... }``
  2. **if-elif chain** on a state variable
     ``if (state == A) { ... } else if (state == B) { ... }``

For each FSM it produces:
  - **states**: the set of all state values (enum literals, numeric constants)
  - **transitions**: state -> [(condition, next_state), ...]
  - **initial_state**: first-assigned value (global/static initializer)

Output format
-------------
    extractor = StateMachineExtractor(source_root)
    machines = extractor.extract_file(full_path, rel_path)   # list[StateMachineDef]
    summary  = summarise_machines(machines)                  # str

Cache output: ``source_docs/state_machines_ast.json``

Integration with CodeGraph
--------------------------
Transitions are emitted as ``TRANSITION`` edges in the ``edges`` table:
    source=STATE:var.StateA, target=STATE:var.StateB, condition="guard_expr"

The ``node_semantics`` table stores the full FSM graph under focus="state_machine".
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

import tree_sitter as ts

# Use try/except to support both package import and standalone import
try:
    from .ast_parser import (
        CParser,
        StateMachine,
        _walk_subtree,
        _node_text,
        _node_lines,
        _find_child,
    )
except ImportError:
    from ast_parser import (
        CParser,
        StateMachine,
        _walk_subtree,
        _node_text,
        _node_lines,
        _find_child,
    )

log = logging.getLogger(__name__)

__all__ = [
    "FSMTransition",
    "StateMachineDef",
    "StateMachineExtractor",
    "load_machines",
    "summarise_machines",
]

# ── Data classes ────────────────────────────────────────────────────────


@dataclass
class FSMTransition:
    """One transition in a state machine."""
    from_state: str       # state value / enum literal
    to_state: str         # next state value ("" if no explicit transition)
    condition: str        # guard expression ("" if unconditional)
    line: int             # 1-indexed line of the transition
    snippet: str = ""     # source code excerpt


@dataclass
class StateMachineDef:
    """A complete state machine definition."""
    state_var: str        # e.g. "ctx->systemState", "session.state"
    func: str             # function containing the FSM
    fsm_type: str         # "switch-case" or "if-elif"
    file: str = ""        # relative file path (filled by extractor)
    states: list[str] = field(default_factory=list)
    transitions: list[FSMTransition] = field(default_factory=list)
    initial_state: str = ""
    line_start: int = 0
    line_end: int = 0
    notes: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        # Ensure transitions serialises
        return d


# ── State variable heuristics ──────────────────────────────────────────

# Patterns that look like state variables
_STATE_VAR_PATTERNS = [
    re.compile(r"\b(?:state|State|STATE)\w*$"),              # e.g. systemState, State_e
    re.compile(r"\w+(?:State|STATE|_state)(?:_e|_en|_enm)?\b"),  # SessionState_e
    re.compile(r"\w+StM\w*"),                                # AdasStM
]


def _looks_like_state_var(name: str) -> bool:
    """Check if an identifier looks like a state variable."""
    leaf = name.rsplit(".", 1)[-1].rsplit("->", 1)[-1]
    return any(p.search(leaf) for p in _STATE_VAR_PATTERNS)


def _is_enum_like(name: str) -> bool:
    """Check if a name looks like an enum constant."""
    return (name.isupper() and "_" in name) or \
           name.endswith("_e") or \
           re.match(r"^\w+(?:State|INIT|IDLE|RUN|DONE|ERR|ERROR|OK)\w*$", name) is not None


# ── Helpers ─────────────────────────────────────────────────────────────

def _strip_parens(text: str) -> str:
    """Remove outer parentheses."""
    t = text.strip()
    while t.startswith("(") and t.endswith(")"):
        t = t[1:-1].strip()
    return t


def _paren_expr(paren_node: ts.Node) -> ts.Node:
    """From a parenthesized_expression, get the inner expression node.

    tree-sitter layout:  ( <expr> )  — children[0] is '(', children[-1] is ')'.
    """
    kids = paren_node.children
    if len(kids) >= 3:
        return kids[1]
    return kids[0] if kids else paren_node


def _extract_assigned_state(body_node: ts.Node, source: bytes) -> list[tuple[str, int, str]]:
    """Find ``state_var = VALUE`` assignments inside a body node.
    
    Returns list of (value, line, full_assignment_text).
    """
    results = []
    for assign in _walk_subtree(body_node, source, "assignment_expression"):
        lhs = _node_text(assign.children[0], source) if assign.children else ""
        rhs = _node_text(assign.children[-1], source) if assign.child_count > 1 else ""
        sl, _, _, _ = _node_lines(assign)
        full_text = _node_text(assign, source)
        results.append((rhs, sl, full_text))
    return results


def _extract_conditions_in_body(
    body_node: ts.Node, source: bytes, target_var: str,
) -> list[tuple[str, int]]:
    """Find if-conditions inside a case/body that reference the state var.
    
    Returns list of (condition_text, line).
    """
    conditions = []
    for if_node in _walk_subtree(body_node, source, "if_statement"):
        paren = _find_child(if_node, "parenthesized_expression")
        if paren:
            cond_text = _node_text(paren, source)
            cond_inner = _strip_parens(cond_text)
            if target_var in cond_inner or any(
                kw in cond_inner for kw in ("true", "false", "TRUE", "FALSE", "TRUE", "FALSE")
            ):
                sl, _, _, _ = _node_lines(if_node)
                conditions.append((cond_inner, sl))
    return conditions


# ── Switch-Case FSM Detector ───────────────────────────────────────────

class _SwitchCaseDetector:
    """Detect state machines built with switch-case on a state variable."""

    def detect(
        self, func_node: ts.Node, func_name: str, source: bytes,
    ) -> list[StateMachineDef]:
        """Scan a function for switch-case FSMs."""
        machines = []
        for switch_node in _walk_subtree(func_node, source, "switch_statement"):
            # Extract the switch expression (state variable)
            paren = _find_child(switch_node, "parenthesized_expression")
            if not paren or not paren.children:
                continue
            inner = _paren_expr(paren)
            state_var = _node_text(inner, source)
            
            # Must look like a state variable
            if not _looks_like_state_var(state_var):
                continue
            
            body = _find_child(switch_node, "compound_statement")
            if not body:
                continue

            sl, _, el, _ = _node_lines(switch_node)
            machine = StateMachineDef(
                state_var=state_var,
                func=func_name,
                fsm_type="switch-case",
                line_start=sl,
                line_end=el,
            )

            states_seen = set()
            prev_case_state = ""

            for child in body.children:
                if child.type == "case_statement":
                    # Extract case value
                    case_val_node = _find_child(child, "identifier") or \
                                     _find_child(child, "preproc_defined") or \
                                     child.children[0]
                    if case_val_node:
                        case_val = _node_text(case_val_node, source).rstrip(":")
                        prev_case_state = case_val
                        states_seen.add(case_val)
                    
                    # Look for state assignments in the case body
                    assigned = _extract_assigned_state(child, source)
                    for rhs_val, rhs_line, rhs_text in assigned:
                        # Check if LHS is the state variable
                        lhs_in_text = rhs_text.split("=")[0].strip().rstrip("=")
                        if state_var in lhs_in_text:
                            states_seen.add(rhs_val)
                            condition_parts = []
                            conds = _extract_conditions_in_body(child, source, state_var)
                            for cond_text, _ in conds:
                                condition_parts.append(cond_text)
                            
                            cond_str = "; ".join(condition_parts) if condition_parts else ""
                            machine.transitions.append(FSMTransition(
                                from_state=prev_case_state,
                                to_state=rhs_val,
                                condition=cond_str,
                                line=rhs_line,
                                snippet=rhs_text[:200],
                            ))

                elif child.type == "default":
                    # default: block — note it but don't add as a named state
                    pass

            machine.states = sorted(states_seen)
            machines.append(machine)

        return machines


# ── If-Elif Chain FSM Detector ─────────────────────────────────────────

class _IfElseDetector:
    """Detect state machines built with if-else if chains on a state variable."""

    def detect(
        self, func_node: ts.Node, func_name: str, source: bytes,
    ) -> list[StateMachineDef]:
        """Scan a function for if-elif FSMs."""
        machines = []
        
        # Find top-level if-statements in the function body
        body_node = _find_child(func_node, "compound_statement")
        if not body_node:
            return machines

        # Walk immediate children for if-statements that could be FSMs
        seen_vars = {}  # state_var -> list[if_node]

        for child in body_node.children:
            if child.type == "if_statement":
                fsm_var = self._extract_if_state_var(child, source)
                if fsm_var:
                    seen_vars.setdefault(fsm_var, []).append(child)

        for state_var, if_nodes in seen_vars.items():
            if len(if_nodes) < 2:
                # Need at least 2 branches to be a state machine
                continue

            machine = StateMachineDef(
                state_var=state_var,
                func=func_name,
                fsm_type="if-elif",
            )

            states_seen = set()
            first_sl = None
            last_el = None

            for if_node in if_nodes:
                sl, _, el, _ = _node_lines(if_node)
                if first_sl is None:
                    first_sl = sl
                last_el = el

                # Extract the comparison value from the condition
                paren = _find_child(if_node, "parenthesized_expression")
                if not paren:
                    continue
                cond_text = _strip_parens(_node_text(paren, source))
                
                # Parse: state_var == VALUE  or  state_var != VALUE
                match = re.match(
                    r"(.+?)\s*(?:==|!=)\s*(.+)",
                    cond_text,
                )
                if match:
                    comp_val = match.group(2).strip()
                    states_seen.add(comp_val)

                # Find state assignments in the if body
                if_body = _find_child(if_node, "compound_statement")
                if not if_body:
                    # Single statement body
                    stmt = if_node.children[-2] if len(if_node.children) >= 2 else None
                    if stmt and stmt.type == "expression_statement":
                        assigned = _extract_assigned_state(stmt, source)
                    else:
                        assigned = []
                else:
                    assigned = _extract_assigned_state(if_body, source)

                for rhs_val, rhs_line, rhs_text in assigned:
                    lhs_in_text = rhs_text.split("=")[0].strip().rstrip("=")
                    if state_var in lhs_in_text:
                        states_seen.add(rhs_val)
                        machine.transitions.append(FSMTransition(
                            from_state=comp_val if match else "",
                            to_state=rhs_val,
                            condition=cond_text,
                            line=rhs_line,
                            snippet=rhs_text[:200],
                        ))

            machine.states = sorted(states_seen)
            machine.line_start = first_sl or 0
            machine.line_end = last_el or 0
            machines.append(machine)

        return machines

    @staticmethod
    def _extract_if_state_var(if_node: ts.Node, source: bytes) -> str:
        """Extract the state variable from an if-statement condition, if it looks like an FSM."""
        paren = _find_child(if_node, "parenthesized_expression")
        if not paren or not paren.children:
            return ""
        
        # Look for binary_expression: var == VALUE
        bin_expr = _paren_expr(paren)
        if bin_expr.type != "binary_expression" or len(bin_expr.children) < 3:
            return ""
        
        op_node = bin_expr.children[1]
        op_text = _node_text(op_node, source)
        if op_text not in ("==", "!="):
            return ""
        
        left_text = _node_text(bin_expr.children[0], source)
        right_text = _node_text(bin_expr.children[2], source)
        
        # Determine which side is the state variable
        if _looks_like_state_var(left_text):
            return left_text
        if _looks_like_state_var(right_text):
            return right_text
        
        return ""


# ── Initial State Detector ─────────────────────────────────────────────

class _InitialStateDetector:
    """Find the initial value of a state variable (global/static initialization)."""

    def detect(
        self, tree: ts.Tree, source: bytes, state_var: str,
    ) -> str:
        """Look for global/static assignments that initialize the state var."""
        # Pattern 1: Type varName = VALUE; at file scope
        for decl in _walk_subtree(tree.root_node, source, "declaration"):
            text = _node_text(decl, source)
            if state_var in text and "=" in text:
                # Extract the value after the state_var
                idx = text.find(state_var)
                rest = text[idx + len(state_var):]
                eq_match = re.match(r"\s*=\s*(\w+)", rest)
                if eq_match:
                    val = eq_match.group(1)
                    if val not in ("0", "NULL"):
                        return val
                    return "INIT"  # zero-initialized
        return ""


# ── Main Extractor ──────────────────────────────────────────────────────

class StateMachineExtractor:
    """
    Extract state machines from C source files.

    Usage:
        extractor = StateMachineExtractor(source_root)
        machines = extractor.extract_file(full_path, rel_path)

    Or standalone:
        extractor = StateMachineExtractor()
        parser = CParser()
        tree, source = parser.parse_file(path)
        machines = extractor.extract_from_tree(tree, source, rel_path)
    """

    def __init__(self, source_root: Optional[str] = None):
        self.source_root = source_root
        self.parser = CParser()
        self._switch_detector = _SwitchCaseDetector()
        self._if_detector = _IfElseDetector()
        self._init_detector = _InitialStateDetector()

    def extract_file(
        self, full_path: Path, rel_path: str,
    ) -> list[StateMachineDef]:
        """Parse a single file and extract all state machines."""
        if not full_path.exists():
            return []

        try:
            source_bytes = full_path.read_bytes()
            tree, _ = self.parser.parse_file(full_path)
        except Exception as e:
            log.warning("Failed to parse %s: %s", rel_path, e)
            return []

        return self.extract_from_tree(tree, source_bytes, rel_path)

    def extract_from_tree(
        self, tree: ts.Tree, source: bytes, rel_path: str,
    ) -> list[StateMachineDef]:
        """Extract FSMs from an already-parsed AST tree."""
        all_machines = []

        # 1. Find all functions
        func_defs = self.parser.extract_functions(tree, source)

        for func_def in func_defs:
            # Find the function_definition node in the tree
            func_node = None
            for node in _walk_subtree(tree.root_node, source, "function_definition"):
                # Check if this node's name matches func_def.name
                for child in node.children:
                    if child.type in ("function_declarator", "declarator"):
                        for gc in child.children:
                            if gc.type == "identifier":
                                name = _node_text(gc, source)
                                if name == func_def.name:
                                    func_node = node
                                    break
                if func_node:
                    break

            if not func_node:
                continue

            # Skip very large functions (likely not FSMs)
            if func_def.end_line - func_def.start_line > 2000:
                continue

            # 2. Switch-case detection
            switch_machines = self._switch_detector.detect(
                func_node, func_def.name, source,
            )
            all_machines.extend(switch_machines)

            # 3. If-elif chain detection
            if_machines = self._if_detector.detect(
                func_node, func_def.name, source,
            )
            all_machines.extend(if_machines)

        # 4. Fill in metadata
        for m in all_machines:
            m.file = rel_path
            # Try to find initial state
            if not m.initial_state:
                m.initial_state = self._init_detector.detect(
                    tree, source, m.state_var,
                )
            # If initial state still empty, try first state in list
            if not m.initial_state and m.states:
                m.initial_state = m.states[0]

        return all_machines


# ── File I/O ─────────────────────────────────────────────────────────────

_CACHE_PATH = Path("source_docs/state_machines_ast.json")


def _compute_file_hash(full_path: Path) -> str:
    return hashlib.sha256(full_path.read_bytes()).hexdigest()[:16]


def load_machines(
    source_root: str,
    target_files: Optional[list[str]] = None,
    use_cache: bool = True,
) -> list[StateMachineDef]:
    """
    Load state machines from source files, with optional cache.

    Args:
        source_root: Root directory of C source code.
        target_files: Optional list of relative file paths to analyse.
        use_cache: If True, use cached results when available.
    """
    root = Path(source_root)
    if target_files is None:
        target_files = [str(p.relative_to(root)) for p in root.rglob("*.c")]

    # Check cache
    if use_cache and _CACHE_PATH.exists():
        try:
            cached = json.loads(_CACHE_PATH.read_text())
            cache_hash = cached.get("_file_hashes", {})
            all_valid = True
            for f in target_files:
                full = root / f
                if full.exists():
                    current_hash = _compute_file_hash(full)
                    if cache_hash.get(f) != current_hash:
                        all_valid = False
                        break
            if all_valid and cached.get("machines"):
                return [StateMachineDef(**m) for m in cached["machines"]]
        except (json.JSONDecodeError, KeyError):
            pass

    # Extract fresh
    extractor = StateMachineExtractor(str(root))
    all_machines = []
    for rel_path in target_files:
        full = root / rel_path
        if full.exists():
            machines = extractor.extract_file(full, rel_path)
            all_machines.extend(machines)

    # Save cache
    cache_data = {
        "_file_hashes": {
            f: _compute_file_hash(root / f)
            for f in target_files
            if (root / f).exists()
        },
        "machines": [m.to_dict() for m in all_machines],
        "total": len(all_machines),
    }
    _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CACHE_PATH.write_text(json.dumps(cache_data, indent=2))

    return all_machines


# ── Summary ─────────────────────────────────────────────────────────────

def summarise_machines(machines: list[StateMachineDef]) -> str:
    """Generate a human-readable summary of extracted state machines."""
    if not machines:
        return "No state machines detected."

    lines = [f"Detected {len(machines)} state machine(s):\n"]
    for i, m in enumerate(machines, 1):
        lines.append(f"--- FSM #{i} ---")
        lines.append(f"  Variable : {m.state_var}")
        lines.append(f"  Function : {m.func}")
        lines.append(f"  File     : {m.file}")
        lines.append(f"  Type     : {m.fsm_type}")
        lines.append(f"  States   : {', '.join(m.states)} (total {len(m.states)})")
        lines.append(f"  Initial  : {m.initial_state or 'unknown'}")
        lines.append(f"  Lines    : {m.line_start}-{m.line_end}")
        if m.transitions:
            lines.append(f"  Transitions ({len(m.transitions)}):")
            for t in m.transitions:
                cond = f" [if {t.condition}]" if t.condition else ""
                lines.append(f"    {t.from_state} -> {t.to_state}{cond}  (L{t.line})")
        lines.append("")

    return "\n".join(lines)
