# -*- coding: utf-8 -*-
"""Evidence-bound evaluation of source conditions.

This module is deliberately smaller than a C interpreter.  It keeps the
current source expression and provenance intact, then evaluates only a safe
scalar subset when every operand has an explicit value from the selected
frame or the current source parameter index.  Missing values are evidence
gaps, not failed conditions.
"""
from __future__ import annotations

import ast
from copy import deepcopy
from pathlib import Path
import re
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = "condition-trace.v1"

_C_CAST_RE = re.compile(
    r"\(\s*(?:const\s+)?(?:u?int(?:8|16|32|64)?_t|size_t|float|double|bool|char|short|long)\s*\)"
)
_NUMBER_SUFFIX_RE = re.compile(r"(?<=\d)[fFuUlL]+\b")
_TOKEN_RE = re.compile(
    r"\b[A-Za-z_]\w*(?:(?:->|\.)[A-Za-z_]\w*|\[[A-Za-z0-9_+\- ]+\])*"
)
_IDENTIFIER_RE = re.compile(r"\b[A-Za-z_]\w*\b")
_SOURCE_ALIAS_ASSIGNMENT_RE = re.compile(
    r"^\s*(?:[A-Za-z_]\w*(?:\s+|[*&]\s*))+(?P<alias>[A-Za-z_]\w*)\s*"
    r"=\s*&?(?P<source>[A-Za-z_]\w*(?:(?:->|\.)[A-Za-z_]\w*|\[[^\]]+\])+)\s*;"
)
_KNOWN_TOKENS = {
    "if", "else", "true", "false", "TRUE", "FALSE", "nullptr", "NULL",
    "and", "or", "not", "abs", "fabs", "fabsf", "min", "max", "round",
    "float", "double", "int", "bool", "uint8_t", "uint16_t", "uint32_t",
    "uint64_t", "int8_t", "int16_t", "int32_t", "int64_t", "size_t",
    "const", "static", "struct", "enum", "sizeof",
}


class ConditionTraceError(ValueError):
    """Raised when a condition trace input violates its artifact contract."""


def _as_rows(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, Mapping):
        return [dict(value)]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [dict(item) for item in value if isinstance(item, Mapping)]
    raise ConditionTraceError("conditions/parameters must be an object or array")


def _fact_from_value(value: Any, *, source_kind: str = "provided_value") -> dict[str, Any]:
    if isinstance(value, Mapping) and "value" in value:
        return deepcopy(dict(value))
    return {"value": value, "source_kind": source_kind, "confidence": "explicit"}


def _value_facts(values: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    if values is None:
        return {}
    if not isinstance(values, Mapping):
        raise ConditionTraceError("values must be an object")
    return {
        str(key): _fact_from_value(item)
        for key, item in values.items()
        if str(key).strip()
    }


def _parameter_facts(parameters: Any) -> dict[str, dict[str, Any]]:
    if parameters is None:
        return {}
    if isinstance(parameters, Mapping):
        rows = [
            {"name": str(key), "value": value, "source_kind": "source_static_code"}
            for key, value in parameters.items()
        ]
    else:
        rows = _as_rows(parameters)
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        name = str(row.get("name", "") or "").strip()
        if not name:
            continue
        fact = deepcopy(dict(row))
        fact.setdefault("source_kind", "source_static_code")
        fact.setdefault("confidence", "code-index")
        if "code_ref" not in fact and fact.get("file_path"):
            fact["code_ref"] = {
                "file": fact.get("file_path"),
                "line": fact.get("line"),
                "confidence": fact.get("confidence", "code-index"),
            }
        result[name] = fact
    return result


def _source_parameter_rows(source_root: str | Path, names: set[str]) -> list[dict[str, Any]]:
    """Read missing macros/global constants from the current source snapshot."""
    if not str(source_root or "").strip() or not names:
        return []
    root = Path(source_root).expanduser()
    if not root.is_dir():
        return []
    try:
        paths = [
            path for path in root.rglob("*")
            if path.is_file() and path.suffix.lower() in {".h", ".hpp", ".c", ".cc", ".cpp"}
            and not any(part in {"build", "devel", "install", ".git"} for part in path.parts)
        ][:5000]
    except OSError:
        return []
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in paths:
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        try:
            relative = str(path.relative_to(root)).replace("\\", "/")
        except ValueError:
            relative = str(path)
        enum_mode = False
        enum_pending = False
        enum_value = 0
        for line_number, line in enumerate(lines, start=1):
            macro = re.match(r"^\s*#\s*define\s+([A-Za-z_]\w*)(?!\s*\()\s+(.+?)\s*$", line)
            if macro and macro.group(1) in names and macro.group(1) not in seen:
                seen.add(macro.group(1))
                rows.append({
                    "name": macro.group(1), "value": macro.group(2).split("//", 1)[0].strip(),
                    "file_path": relative, "line": line_number,
                    "kind": "source-macro", "source_kind": "source_macro",
                    "confidence": "source-line-resolved",
                })
                continue
            # File-scope scalar definitions are useful when the sibling
            # index omitted a parameter.  Requiring no indentation avoids
            # treating function-local counters as constants.
            assignment = re.match(
                r"^(?:static\s+|const\s+|volatile\s+)*(?:float|double|int|unsigned|uint\w*|bool)\s+([A-Za-z_]\w*)\s*=\s*([^;]+)",
                line,
            )
            if assignment and assignment.group(1) in names and assignment.group(1) not in seen:
                seen.add(assignment.group(1))
                rows.append({
                    "name": assignment.group(1), "value": assignment.group(2).strip(),
                    "file_path": relative, "line": line_number,
                    "kind": "source-global-definition", "source_kind": "source_static_code",
                    "confidence": "source-line-resolved",
                })
                continue
            if re.search(r"\benum\b", line) and "{" in line:
                enum_mode = True
                enum_pending = False
                enum_value = 0
            elif re.search(r"\benum\b", line) and "{" not in line:
                enum_pending = True
            elif enum_pending and "{" in line:
                enum_mode = True
                enum_pending = False
                enum_value = 0
            if enum_mode:
                for item in re.finditer(r"\b([A-Za-z_]\w*)\b\s*(?:=\s*([-+]?\d+)[uUlL]*)?\s*,?", line):
                    enum_name = item.group(1)
                    if enum_name in _KNOWN_TOKENS or enum_name in {"enum", "typedef"}:
                        continue
                    explicit = item.group(2)
                    if explicit is not None:
                        enum_value = int(explicit)
                    if enum_name in names and enum_name not in seen:
                        seen.add(enum_name)
                        rows.append({
                            "name": enum_name, "value": str(enum_value),
                            "file_path": relative, "line": line_number,
                            "kind": "source-enum", "source_kind": "source_enum",
                            "confidence": "source-line-resolved",
                        })
                    enum_value += 1
                if "}" in line:
                    enum_mode = False
    return rows


def _strip_condition_wrapper(expression: str) -> str:
    text = re.sub(r"//.*$", "", str(expression or "").strip())
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL).strip()
    if re.match(r"if\s*\(", text):
        open_index = text.find("(")
        depth = 0
        close_index = None
        for index in range(open_index, len(text)):
            if text[index] == "(":
                depth += 1
            elif text[index] == ")":
                depth -= 1
                if depth == 0:
                    close_index = index
                    break
        if close_index is not None:
            text = text[open_index + 1:close_index] + text[close_index + 1:]
    if text.endswith("{"):
        text = text[:-1].rstrip()
    return text.rstrip(";").strip()


def _balanced_outer_pair(text: str) -> bool:
    if len(text) < 2 or text[0] != "(" or text[-1] != ")":
        return False
    depth = 0
    for index, char in enumerate(text):
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0 and index != len(text) - 1:
                return False
            if depth < 0:
                return False
    return depth == 0


def _normalise_expression(expression: str) -> str:
    text = _strip_condition_wrapper(expression)
    while _balanced_outer_pair(text):
        text = text[1:-1].strip()
    text = _C_CAST_RE.sub("", text)
    text = _NUMBER_SUFFIX_RE.sub("", text)
    text = text.replace("&&", " and ").replace("||", " or ")
    text = re.sub(r"!(?!=)", " not ", text)
    text = re.sub(r"\b(?:fabsf|fabs)\s*\(", "abs(", text)
    text = re.sub(r"\bTRUE\b", "True", text)
    text = re.sub(r"\bFALSE\b", "False", text)
    text = re.sub(r"\b(?:NULL|nullptr)\b", "None", text)
    return re.sub(r"\s+", " ", text).strip()


def _referenced_tokens(expression: str) -> list[str]:
    tokens: list[str] = []
    for token in _TOKEN_RE.findall(_strip_condition_wrapper(expression)):
        if token in _KNOWN_TOKENS or token.isdigit():
            continue
        # A chained path is one source token.  Do not separately report its
        # members; GDB users need the exact C token shown by the source.
        if token not in tokens:
            tokens.append(token)
    return tokens


def _literal_value(value: Any) -> tuple[Any, bool]:
    if isinstance(value, bool):
        return value, True
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value, True
    if not isinstance(value, str):
        return value, value is not None
    text = _normalise_expression(value)
    if text in {"True", "False"}:
        return text == "True", True
    if text == "None":
        return None, True
    try:
        number = float(text)
    except ValueError:
        return value, False
    if number.is_integer() and not any(char in text.lower() for char in (".", "e")):
        return int(number), True
    return number, True


class _SafeExpression:
    """Evaluate a restricted Python AST produced from a C expression."""

    def __init__(self, symbols: Mapping[str, Any]):
        self.symbols = dict(symbols)

    def evaluate(self, expression: str) -> Any:
        tree = ast.parse(expression, mode="eval")
        return self._node(tree.body)

    def _node(self, node: ast.AST) -> Any:
        if isinstance(node, ast.Constant) and isinstance(node.value, (bool, int, float, type(None))):
            return node.value
        if isinstance(node, ast.Name) and node.id in self.symbols:
            return self.symbols[node.id]
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.Not, ast.UAdd, ast.USub)):
            value = self._node(node.operand)
            if isinstance(node.op, ast.Not):
                return not bool(value)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise ValueError("unary numeric operator requires a number")
            return +value if isinstance(node.op, ast.UAdd) else -value
        if isinstance(node, ast.BoolOp) and isinstance(node.op, (ast.And, ast.Or)):
            values = [bool(self._node(item)) for item in node.values]
            return all(values) if isinstance(node.op, ast.And) else any(values)
        if isinstance(node, ast.BinOp) and isinstance(
            node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod, ast.Pow)
        ):
            left = self._node(node.left)
            right = self._node(node.right)
            if not all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in (left, right)):
                raise ValueError("arithmetic operator requires numeric operands")
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                return left / right
            if isinstance(node.op, ast.Mod):
                return left % right
            return left ** right
        if isinstance(node, ast.Compare):
            left = self._node(node.left)
            for operator, comparator in zip(node.ops, node.comparators):
                right = self._node(comparator)
                if isinstance(operator, ast.Eq):
                    result = left == right
                elif isinstance(operator, ast.NotEq):
                    result = left != right
                elif isinstance(operator, ast.Lt):
                    result = left < right
                elif isinstance(operator, ast.LtE):
                    result = left <= right
                elif isinstance(operator, ast.Gt):
                    result = left > right
                elif isinstance(operator, ast.GtE):
                    result = left >= right
                else:
                    raise ValueError(f"unsupported comparison: {type(operator).__name__}")
                if not result:
                    return False
                left = right
            return True
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {"abs", "min", "max", "round"}:
            args = [self._node(arg) for arg in node.args]
            if not all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in args):
                raise ValueError("numeric helper requires numeric arguments")
            return {"abs": abs, "min": min, "max": max, "round": round}[node.func.id](*args)
        raise ValueError(f"unsupported AST node: {type(node).__name__}")


def _substitute(expression: str, replacements: Mapping[str, Any]) -> str:
    text = _normalise_expression(expression)
    for token in sorted(replacements, key=len, reverse=True):
        safe = repr(replacements[token])
        text = re.sub(rf"(?<![A-Za-z0-9_]){re.escape(token)}(?![A-Za-z0-9_])", safe, text)
    return text


def _group_conditions(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Join multiline ``&&``/``||`` source rows while retaining line refs."""
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for row in rows:
        expression = str(row.get("expression", "") or "").strip()
        if not expression:
            continue
        key = (str(row.get("function", "")), str(row.get("line", "")), expression)
        if key in seen:
            continue
        seen.add(key)
        current = dict(row)
        if result:
            previous = result[-1]
            continuation = expression.lstrip().startswith(("&&", "||"))
            same_function = str(previous.get("function", "")) == str(row.get("function", ""))
            try:
                adjacent = int(row.get("line")) <= int(previous.get("line")) + 1
            except (TypeError, ValueError):
                adjacent = False
            if continuation and same_function and adjacent:
                previous["expression"] = f"{previous.get('expression', '')} {expression}"
                previous["end_line"] = row.get("line")
                continue
        result.append(current)
    return result


def _resolve_parameters(
    facts: Mapping[str, dict[str, Any]],
) -> dict[str, tuple[Any, dict[str, Any]]]:
    resolved: dict[str, tuple[Any, dict[str, Any]]] = {}
    resolving: set[str] = set()

    def resolve(name: str) -> tuple[Any, dict[str, Any]]:
        if name in resolved:
            return resolved[name]
        fact = facts[name]
        raw = fact.get("value")
        literal, is_literal = _literal_value(raw)
        if is_literal:
            resolved[name] = (literal, fact)
            return resolved[name]
        if name in resolving:
            return raw, fact
        resolving.add(name)
        expression = _normalise_expression(str(raw))
        references = _referenced_tokens(str(raw))
        symbols: dict[str, Any] = {}
        replacements: dict[str, Any] = {}
        missing = False
        for token in references:
            if token not in facts:
                missing = True
                continue
            value, _ = resolve(token)
            value_literal, value_ok = _literal_value(value)
            if not value_ok:
                missing = True
                continue
            safe_name = f"p{len(symbols)}"
            symbols[safe_name] = value_literal
            replacements[token] = value_literal
        if missing:
            resolving.discard(name)
            return raw, fact
        substituted = _substitute(expression, replacements)
        try:
            value = _SafeExpression({}).evaluate(substituted)
        except (SyntaxError, ValueError, TypeError, ZeroDivisionError):
            resolving.discard(name)
            return raw, fact
        resolved[name] = (value, {**fact, "raw_value": raw, "resolved_expression": substituted})
        resolving.discard(name)
        return resolved[name]

    for name in facts:
        resolve(name)
    return resolved


def _condition_ref(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: deepcopy(row[key])
        for key in ("file_path", "line", "end_line", "column", "source_hash", "confidence")
        if row.get(key) not in (None, "", [])
    }


def _source_alias_values(
    source_root: str | Path,
    rows: Sequence[Mapping[str, Any]],
    value_facts: Mapping[str, Mapping[str, Any]],
    *,
    max_distance: int = 160,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Bind a local copy only when the current source proves the assignment.

    The arbe FCTA implementation copies ``objInfo->trcOutData[i]`` into the
    local ``sObj`` before evaluating several conditions.  Public/GDB evidence
    often exposes the former spelling while the condition uses the latter.
    This small source bridge is intentionally narrower than a C alias engine:
    it requires a nearby declaration assignment, copies only unchanged fields,
    and records the declaration as provenance.  Missing/ambiguous aliases stay
    missing rather than being guessed.
    """
    root = Path(source_root).expanduser()
    if not root.is_dir() or not value_facts:
        return {str(key): deepcopy(dict(value)) for key, value in value_facts.items()}, []
    result = {str(key): deepcopy(dict(value)) for key, value in value_facts.items()}
    bindings: list[dict[str, Any]] = []
    file_cache: dict[Path, list[str]] = {}
    for row in rows:
        file_text = str(row.get("file_path") or "").strip()
        try:
            condition_line = int(row.get("line") or 0)
        except (TypeError, ValueError):
            condition_line = 0
        if not file_text or condition_line <= 0:
            continue
        source_file = Path(file_text).expanduser()
        if not source_file.is_absolute():
            source_file = root / source_file
        try:
            source_file = source_file.resolve()
            source_file.relative_to(root.resolve())
        except (OSError, ValueError):
            continue
        try:
            lines = file_cache.setdefault(
                source_file,
                source_file.read_text(encoding="utf-8", errors="replace").splitlines(),
            )
        except OSError:
            continue
        if condition_line > len(lines):
            continue
        start = max(0, condition_line - 1 - max_distance)
        # The closest declaration wins for this source condition.  This also
        # avoids borrowing an alias from an earlier function with the same
        # local name.
        for index in range(condition_line - 2, start - 1, -1):
            match = _SOURCE_ALIAS_ASSIGNMENT_RE.match(lines[index])
            if not match:
                continue
            alias = str(match.group("alias") or "").strip()
            source = str(match.group("source") or "").strip()
            if not alias or not source:
                continue
            try:
                relative = str(source_file.relative_to(root)).replace("\\", "/")
            except ValueError:
                relative = str(source_file)
            declaration_ref = {
                "file_path": relative,
                "line": index + 1,
                "expression": f"{alias} = {source}",
                "confidence": "source_alias_assignment",
            }
            copied = 0
            for source_token, fact in value_facts.items():
                if not str(source_token).startswith(source):
                    continue
                suffix = str(source_token)[len(source):]
                if not suffix.startswith((".", "->")):
                    continue
                field = suffix[1:] if suffix.startswith(".") else suffix[2:]
                # A local copy is valid only until that particular field is
                # assigned again.  Other fields (e.g. velAbsX in HILMODEL)
                # may legitimately diverge and remain unbound.
                assignment_re = re.compile(
                    rf"\b{re.escape(alias)}\s*(?:\.|->)\s*{re.escape(field)}\s*="
                )
                if any(assignment_re.search(line) for line in lines[index + 1:condition_line - 1]):
                    continue
                alias_token = alias + suffix
                alias_fact = deepcopy(dict(fact))
                alias_fact["binding_origin"] = "source_alias"
                alias_fact["alias_source_token"] = str(source_token)
                alias_fact["alias_source_ref"] = deepcopy(declaration_ref)
                alias_fact["confidence"] = "source_alias_proven"
                result.setdefault(alias_token, alias_fact)
                copied += 1
            if copied:
                bindings.append({
                    "alias": alias,
                    "source": source,
                    "condition_line": condition_line,
                    "source_ref": declaration_ref,
                    "copied_field_count": copied,
                })
            break
    return result, bindings


def build_condition_trace(
    *,
    conditions: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None,
    values: Mapping[str, Any] | None = None,
    parameters: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None = None,
    event_id: str = "",
    function: str = "",
    frame_id: Any = None,
    source_root: str = "",
    max_conditions: int = 80,
) -> dict[str, Any]:
    """Build a source-bound, non-guessing condition trace."""
    rows = _group_conditions(_as_rows(conditions))[: max(1, int(max_conditions))]
    value_facts = _value_facts(values)
    value_facts, source_alias_bindings = _source_alias_values(source_root, rows, value_facts)
    parameter_rows = _as_rows(parameters) if parameters is not None else []
    needed_names = {
        token for row in rows for token in _referenced_tokens(str(row.get("expression", "") or ""))
    }
    parameter_rows.extend(_source_parameter_rows(source_root, needed_names))
    parameter_facts = _parameter_facts(parameter_rows)
    parameter_values = _resolve_parameters(parameter_facts)
    for name, (value, fact) in parameter_values.items():
        if _literal_value(value)[1]:
            candidate = {
                **deepcopy(fact),
                "value": value,
                "source_kind": fact.get("source_kind", "source_static_code"),
                "confidence": fact.get("confidence", "code-index"),
            }
            existing = value_facts.get(name)
            existing_value, existing_literal = (
                _literal_value(existing.get("value"))
                if isinstance(existing, Mapping)
                else (None, False)
            )
            # Runtime values win when they are usable.  If GDB prints an enum
            # symbol (for example ``WarningFlag_Normal``) or a missing marker,
            # the current-source numeric macro/enum is the more precise fact
            # for deterministic condition evaluation and may fill that gap.
            if (
                existing is None
                or not existing_literal
                or existing.get("status") in {"not_found", "not_available", "optimized_out"}
                or existing_value in (None, "")
            ):
                value_facts[name] = candidate

    traces: list[dict[str, Any]] = []
    counts = {"satisfied": 0, "not_satisfied": 0, "not_evaluable": 0, "unsupported": 0}
    for index, row in enumerate(rows):
        expression = str(row.get("expression", "") or "").strip()
        tokens = _referenced_tokens(expression)
        bindings: list[dict[str, Any]] = []
        replacements: dict[str, Any] = {}
        missing: list[str] = []
        for token in tokens:
            fact = value_facts.get(token)
            if fact is None or fact.get("value") in (None, ""):
                missing.append(token)
                bindings.append({"token": token, "status": "missing", "source_kind": "not_available"})
                continue
            value, literal = _literal_value(fact.get("value"))
            if not literal:
                missing.append(token)
                bindings.append({
                    "token": token,
                    "status": "unresolved_expression",
                    "raw_value": fact.get("value"),
                    "source_kind": fact.get("source_kind", "not_available"),
                    "source_ref": deepcopy(fact.get("source_ref", {})),
                    "code_ref": deepcopy(fact.get("code_ref", {})),
                })
                continue
            binding = {
                "token": token,
                "status": "bound",
                "value": value,
                "source_kind": fact.get("source_kind", "provided_value"),
                "confidence": fact.get("confidence", "explicit"),
            }
            for key in ("source_ref", "code_ref", "runtime_ref", "unit"):
                if fact.get(key) not in (None, "", {}):
                    binding[key] = deepcopy(fact[key])
            bindings.append(binding)
            replacements[token] = value

        normalised = _normalise_expression(expression)
        substituted = _substitute(normalised, replacements)
        status = "not_evaluable"
        reason = "missing explicit operands"
        result_value: Any = None
        if missing:
            reason = "missing tokens: " + ", ".join(missing)
        else:
            try:
                result_value = _SafeExpression({}).evaluate(substituted)
                status = "satisfied" if bool(result_value) else "not_satisfied"
                reason = "all operands bound; safe expression evaluated"
            except (SyntaxError, ValueError, TypeError, ZeroDivisionError) as exc:
                status = "unsupported"
                reason = f"safe evaluator cannot evaluate expression: {exc}"
        counts[status] += 1
        trace = {
            "condition_id": f"condition-{index + 1}",
            "function": row.get("function") or function,
            "expression": expression,
            "source_ref": _condition_ref(row),
            "referenced_tokens": tokens,
            "bindings": bindings,
            "missing_tokens": missing,
            "normalised_expression": normalised,
            "substituted_expression": substituted,
            "evaluation": {
                "status": status,
                "value": result_value,
                "reason": reason,
            },
        }
        # Preserve the source-call-path metadata when the caller supplied a
        # dynamically built condition chain.  These labels describe
        # candidate provenance; they are not proof that every branch ran.
        for key in (
            "condition_kind",
            "chain_function",
            "chain_relation",
            "chain_function_order",
            "chain_source_order",
            "chain_call_site_line",
        ):
            if row.get(key) not in (None, ""):
                trace[key] = row.get(key)
        traces.append(trace)

    gaps: list[dict[str, Any]] = []
    for trace in traces:
        evaluation = trace["evaluation"]
        if evaluation["status"] in {"not_evaluable", "unsupported"}:
            gaps.append({
                "condition_id": trace["condition_id"],
                "status": evaluation["status"],
                "missing_tokens": trace.get("missing_tokens", []),
                "reason": evaluation["reason"],
                "source_ref": trace.get("source_ref", {}),
            })
    if not traces:
        status = "not_available"
    elif counts["not_evaluable"] or counts["unsupported"]:
        status = "partial"
    else:
        status = "ready"
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "event": {key: value for key, value in {
            "event_id": event_id,
            "function": function,
            "frame_id": frame_id,
        }.items() if value not in (None, "", [])},
        "conditions": traces,
        "summary": {
            "total": len(traces),
            **counts,
            "evaluated": counts["satisfied"] + counts["not_satisfied"],
        },
        "gaps": gaps,
        "source_alias_bindings": source_alias_bindings,
        "policy": "Only same-frame explicit values and current-source parameter facts are evaluated; missing values never mean false.",
    }


__all__ = ["SCHEMA_VERSION", "ConditionTraceError", "build_condition_trace"]
