# -*- coding: utf-8 -*-
"""Deterministic, source-bound code context snapshots.

The diagnostic product should not rediscover an entire repository every time a
user asks about a bag.  This engine makes that one-time operation explicit:

* fingerprint the exact readable C/C++ source snapshot;
* reuse the existing :class:`CodeGraphBuilder` instead of implementing a
  second parser;
* export a small, JSON-serialisable ``code-index.v1`` which existing
  ``code-analyze`` and ``code-gdb-plan`` can consume;
* fail closed when the source changes during the build or an output directory
  is already bound to another source root.

No feature name, warning bit, ROI, or function is required by this module.  A
caller may provide optional ``function_keywords`` for project-specific module
binding, but the generic function/call/variable/signal/condition/parameter
index is always derived from the current source and CodeGraph database.
"""
from __future__ import annotations

import datetime as _datetime
import hashlib
import json
import os
import sqlite3
import subprocess
import re
from pathlib import Path
from typing import Any, Mapping, Sequence


CONTEXT_SCHEMA_VERSION = "code-context.v1"
INDEX_SCHEMA_VERSION = "code-index.v1"
SOURCE_EXTENSIONS = frozenset({
    ".c", ".h", ".cc", ".hh", ".cpp", ".hpp", ".cxx", ".hxx",
})
DEFAULT_EXCLUDED_DIRS = frozenset({
    ".git", ".svn", ".hg", "build", "devel", "install", "log",
    "logs", "node_modules", "__pycache__", ".cache", ".tox",
})
DEFAULT_CALIBRATION_HINTS = (
    "paraDefine", "dotCalibDefine", "globalVarDefine", "structDefine",
    "perception_public_def", "calib",
)
_CONTROL_CONDITION_RE = re.compile(r"\b(if|while|for|switch)\s*\(")


class CodeContextError(RuntimeError):
    """Raised when a source-bound context cannot be safely produced."""


class SourceChangedDuringBuild(CodeContextError):
    """The input source was modified while CodeGraph was being built."""


def _utc_now() -> str:
    return _datetime.datetime.now(_datetime.timezone.utc).isoformat()


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def _normalise_relative(path: Path) -> str:
    return path.as_posix().lstrip("./")


def _resolve_source_file(source_root: Path, value: str | Path) -> Path:
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = source_root / candidate
    try:
        resolved = candidate.resolve()
        resolved.relative_to(source_root)
    except ValueError as exc:
        raise CodeContextError(
            f"source file is outside source_root: {value}"
        ) from exc
    return resolved


def discover_source_files(
    source_root: str | Path,
    requested_files: Sequence[str | Path] | None = None,
    *,
    max_files: int = 20_000,
    excluded_dirs: Sequence[str] | None = None,
) -> list[Path]:
    """Discover source files without assuming a project layout.

    ``requested_files`` is an explicit allow-list.  When omitted, the source
    root is recursively scanned, excluding generated/build directories.  The
    returned paths are absolute, unique, and sorted for stable fingerprints.
    """
    root = Path(source_root).expanduser().resolve()
    if not root.is_dir():
        raise CodeContextError(f"source_root is not a directory: {root}")
    excluded = set(excluded_dirs or DEFAULT_EXCLUDED_DIRS)
    paths: dict[str, Path] = {}

    if requested_files:
        for value in requested_files:
            path = _resolve_source_file(root, value)
            if not path.is_file():
                raise CodeContextError(f"requested source file not found: {value}")
            if path.suffix.lower() not in SOURCE_EXTENSIONS:
                raise CodeContextError(f"requested file is not C/C++ source: {value}")
            paths[_normalise_relative(path.relative_to(root))] = path
    else:
        for current, dirs, files in os.walk(root, topdown=True):
            dirs[:] = sorted(
                name for name in dirs
                if name not in excluded and not name.startswith(".")
            )
            for filename in sorted(files):
                path = Path(current) / filename
                if path.suffix.lower() not in SOURCE_EXTENSIONS:
                    continue
                try:
                    relative = _normalise_relative(path.relative_to(root))
                except ValueError:
                    continue
                paths[relative] = path.resolve()
                if len(paths) > max(1, int(max_files)):
                    raise CodeContextError(
                        f"source file count exceeds max_files={max_files}; "
                        "provide an explicit key_files allow-list or raise the limit"
                    )

    if not paths:
        raise CodeContextError(f"no C/C++ source files found below {root}")
    return [paths[key] for key in sorted(paths)]


def build_source_manifest(source_root: str | Path, files: Sequence[Path]) -> tuple[list[dict[str, Any]], str]:
    """Return per-file content fingerprints and a stable aggregate hash."""
    root = Path(source_root).expanduser().resolve()
    manifest: list[dict[str, Any]] = []
    for path in files:
        try:
            stat = path.stat()
            content_hash = _sha256_file(path)
            line_count = path.read_text(encoding="utf-8", errors="replace").count("\n") + 1
        except OSError as exc:
            raise CodeContextError(f"cannot read source file {path}: {exc}") from exc
        manifest.append({
            "path": _normalise_relative(path.relative_to(root)),
            "sha256": content_hash,
            "size": int(stat.st_size),
            "line_count": int(line_count),
        })
    aggregate = hashlib.sha256(_json_dump(manifest).encode("utf-8")).hexdigest()
    return manifest, aggregate


def _git_probe(source_root: Path) -> dict[str, Any]:
    """Read git identity only; never fetch, checkout, or mutate the repo."""
    result: dict[str, Any] = {
        "repository_root": "",
        "head": "",
        "branch": "",
        "detached": False,
        "dirty": None,
        "available": False,
    }

    def run(*args: str) -> str:
        completed = subprocess.run(
            ["git", "-C", str(source_root), *args],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        if completed.returncode != 0:
            return ""
        return completed.stdout.strip()

    try:
        repository_root = run("rev-parse", "--show-toplevel")
        if not repository_root:
            return result
        result["available"] = True
        result["repository_root"] = repository_root
        result["head"] = run("rev-parse", "HEAD")
        branch = run("symbolic-ref", "--short", "-q", "HEAD")
        result["branch"] = branch
        result["detached"] = not bool(branch)
        result["dirty"] = bool(run("status", "--porcelain", "--untracked-files=no"))
    except (OSError, subprocess.SubprocessError):
        # A non-git source root is valid; the content hash remains authoritative.
        return result
    return result


def _row_dict(cursor: sqlite3.Cursor, row: sqlite3.Row | tuple[Any, ...]) -> dict[str, Any]:
    columns = [item[0] for item in cursor.description or []]
    return {name: row[index] for index, name in enumerate(columns)}


def _function_row(node: Mapping[str, Any], file_nodes: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    file_node = file_nodes.get(str(node.get("file_id", "")), {})
    file_path = str(file_node.get("file_path", "") or "")
    name = str(node.get("name", "") or "")
    params = str(node.get("params", "") or "")
    return {
        "id": node.get("id", ""),
        "name": name,
        "file_path": file_path,
        "file_id": node.get("file_id"),
        "start_line": node.get("start_line"),
        "end_line": node.get("end_line"),
        "return_type": node.get("return_type"),
        "params": node.get("params"),
        "signature": f"{node.get('return_type') or ''} {name}({params})".strip(),
        "is_static": bool(node.get("is_static", False)),
        "source_hash": node.get("source_hash", ""),
    }


def _edge_row(edge: Mapping[str, Any], nodes: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    source = nodes.get(str(edge.get("source", "")), {})
    target = nodes.get(str(edge.get("target", "")), {})
    return {
        "id": edge.get("id", ""),
        "source": edge.get("source", ""),
        "target": edge.get("target", ""),
        "source_name": source.get("name", ""),
        "target_name": target.get("name", ""),
        "source_type": source.get("type", ""),
        "target_type": target.get("type", ""),
        "type": edge.get("type", ""),
        "line": edge.get("line"),
        "column": edge.get("column"),
        "condition": edge.get("condition"),
        "pattern": edge.get("pattern"),
        "rte_call": edge.get("rte_call"),
        "binding_method": edge.get("binding_method"),
        "macro_name": edge.get("macro_name"),
        "struct_name": edge.get("struct_name"),
        "field_name": edge.get("field_name"),
    }


def extract_source_conditions(
    *,
    source_root: str | Path,
    file_manifest: Sequence[Mapping[str, Any]],
    functions: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Extract raw control expressions with real file/function/line refs.

    CodeGraph currently stores relationships and state-transition guards, but
    a number of valid projects do not populate an edge ``condition`` column
    for ordinary ``if``/``while``/``for``/``switch`` statements.  This small
    lexical pass fills that *evidence index* gap without assigning business
    meaning to the expression.  It deliberately returns raw source text and
    never evaluates the condition.
    """
    root = Path(source_root).expanduser().resolve()
    hashes = {
        str(row.get("path", "")): str(row.get("sha256", ""))
        for row in file_manifest
        if str(row.get("path", ""))
    }
    functions_by_file: dict[str, list[Mapping[str, Any]]] = {}
    for function in functions:
        file_path = str(function.get("file_path", "") or "")
        if file_path:
            functions_by_file.setdefault(file_path.replace("\\", "/"), []).append(function)
    for rows in functions_by_file.values():
        rows.sort(key=lambda row: (row.get("start_line") or 0, row.get("end_line") or 0))

    result: list[dict[str, Any]] = []
    seen: set[tuple[str, int, str, str]] = set()
    for relative, content_hash in hashes.items():
        path = root / relative
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        file_functions = functions_by_file.get(relative, [])
        line_number = 0
        while line_number < len(lines):
            raw_line = lines[line_number]
            if raw_line.lstrip().startswith("#"):
                line_number += 1
                continue
            # This is a lexical evidence extractor, not a C preprocessor. It
            # removes the common single-line comment/string false positives
            # while preserving the expression text as much as possible.
            clean = re.sub(r"//.*$", "", raw_line)
            clean = re.sub(r'"(?:\\.|[^"\\])*"', '""', clean)
            match = _CONTROL_CONDITION_RE.search(clean)
            if not match:
                line_number += 1
                continue
            open_index = clean.find("(", match.start())
            depth = 1
            cursor_line = line_number
            cursor_text = clean
            cursor_index = open_index + 1
            expression_parts: list[str] = []
            closed = False
            while depth > 0:
                closing_index: int | None = None
                for index in range(cursor_index, len(cursor_text)):
                    char = cursor_text[index]
                    if char == "(":
                        depth += 1
                    elif char == ")":
                        depth -= 1
                        if depth == 0:
                            closing_index = index
                            break
                if closing_index is not None:
                    expression_parts.append(cursor_text[cursor_index:closing_index])
                    closed = True
                    break
                expression_parts.append(cursor_text[cursor_index:])
                cursor_line += 1
                if cursor_line >= len(lines):
                    break
                cursor_text = re.sub(r"//.*$", "", lines[cursor_line])
                cursor_index = 0
            if not closed:
                line_number += 1
                continue
            expression = " ".join(expression_parts).strip()
            if not expression:
                line_number += 1
                continue
            function_name = None
            for function in file_functions:
                start = int(function.get("start_line") or 0)
                end = int(function.get("end_line") or 0)
                if start <= line_number + 1 <= max(start, end):
                    function_name = str(function.get("name", "")) or None
                    break
            key = (relative, line_number + 1, match.group(1), expression)
            if key not in seen:
                seen.add(key)
                result.append({
                    "function": function_name,
                    "condition_kind": match.group(1),
                    "expression": expression,
                    "file_path": relative,
                    "line": line_number + 1,
                    "source_hash": content_hash,
                    "source": "raw_source_control_expression",
                })
            line_number = max(line_number + 1, cursor_line + 1)
    result.sort(key=lambda row: (str(row.get("file_path", "")), row.get("line") or 0))
    return result


def export_code_index(
    *,
    db_path: str | Path,
    source_root: str | Path,
    snapshot_hash: str,
    file_manifest: Sequence[Mapping[str, Any]],
    parser: str = "codegraph_sqlite",
    diagnostics: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Export the current CodeGraph DB into the generic index contract."""
    path = Path(db_path).expanduser().resolve()
    if not path.exists():
        raise CodeContextError(f"CodeGraph database not found after build: {path}")
    try:
        conn = sqlite3.connect(str(path))
        conn.row_factory = sqlite3.Row
    except sqlite3.Error as exc:
        raise CodeContextError(f"cannot open CodeGraph database: {exc}") from exc

    try:
        node_cursor = conn.execute("SELECT * FROM nodes ORDER BY type, name, id")
        raw_nodes = [_row_dict(node_cursor, row) for row in node_cursor.fetchall()]
        edge_cursor = conn.execute("SELECT * FROM edges ORDER BY type, line, id")
        raw_edges = [_row_dict(edge_cursor, row) for row in edge_cursor.fetchall()]
    except sqlite3.Error as exc:
        raise CodeContextError(f"cannot export CodeGraph database: {exc}") from exc
    finally:
        conn.close()

    nodes = {str(row.get("id", "")): row for row in raw_nodes}
    file_nodes = {
        key: value for key, value in nodes.items() if value.get("type") == "FILE"
    }
    function_nodes = {
        key: value for key, value in nodes.items() if value.get("type") == "FUNCTION"
    }

    functions = [
        _function_row(row, file_nodes)
        for row in function_nodes.values()
    ]
    functions.sort(key=lambda row: (str(row.get("file_path", "")), row.get("start_line") or 0, row["name"]))
    function_by_id = {str(row["id"]): row for row in functions}

    calls: dict[str, list[str]] = {}
    variable_reads: list[dict[str, Any]] = []
    variable_writes: list[dict[str, Any]] = []
    signal_rows: list[dict[str, Any]] = []
    conditions: list[dict[str, Any]] = []
    states: list[dict[str, Any]] = []
    edge_rows: list[dict[str, Any]] = []

    for raw_edge in raw_edges:
        edge = _edge_row(raw_edge, nodes)
        edge_rows.append(edge)
        source_id = str(raw_edge.get("source", ""))
        source_fn = function_by_id.get(source_id)
        source_name = str((source_fn or {}).get("name", "") or "")
        edge_type = str(raw_edge.get("type", "") or "")
        target_id = str(raw_edge.get("target", ""))
        target_node = nodes.get(target_id, {})

        if edge_type == "CALLS" and source_name:
            target_name = str(target_node.get("name", "") or "")
            if target_name:
                calls.setdefault(source_name, []).append(target_name)
        elif edge_type in {"READS_VAR", "WRITES_VAR"} and source_name:
            row = {
                "function": source_name,
                "var_name": target_node.get("name", ""),
                "variable_id": target_id,
                "data_type": target_node.get("data_type"),
                "scope": target_node.get("scope"),
                "defined_in": target_node.get("defined_in"),
                "line": raw_edge.get("line"),
                "column": raw_edge.get("column"),
                "condition": raw_edge.get("condition"),
                "pattern": raw_edge.get("pattern"),
                "struct_name": raw_edge.get("struct_name"),
                "field_name": raw_edge.get("field_name"),
            }
            (variable_reads if edge_type == "READS_VAR" else variable_writes).append(row)
        elif edge_type in {"READS_SIGNAL", "WRITES_SIGNAL"}:
            signal_rows.append({
                "function": source_name or None,
                "access": "read" if edge_type == "READS_SIGNAL" else "write",
                "signal_id": target_id,
                "signal_name": target_node.get("name", ""),
                "direction": target_node.get("direction"),
                "can_name": target_node.get("can_name"),
                "can_id": target_node.get("can_id"),
                "internal_var": target_node.get("internal_var"),
                "rte_read_fn": target_node.get("rte_read_fn"),
                "rte_write_fn": target_node.get("rte_write_fn"),
                "line": raw_edge.get("line"),
                "rte_call": raw_edge.get("rte_call"),
            })

        if raw_edge.get("condition") not in (None, ""):
            conditions.append({
                "function": source_name or None,
                "expression": raw_edge.get("condition"),
                "target": target_node.get("name", ""),
                "target_id": target_id,
                "edge_type": edge_type,
                "file_path": (source_fn or {}).get("file_path", ""),
                "line": raw_edge.get("line"),
                "column": raw_edge.get("column"),
                "source_hash": (source_fn or {}).get("source_hash", ""),
            })
        if edge_type == "TRANSITION":
            states.append({
                "function": source_name or None,
                "state": target_node.get("name", ""),
                "state_id": target_id,
                "line": raw_edge.get("line"),
                "condition": raw_edge.get("condition"),
                "file_path": (source_fn or {}).get("file_path", ""),
            })

    for key in list(calls):
        calls[key] = list(dict.fromkeys(calls[key]))

    parameters: list[dict[str, Any]] = []
    for node in nodes.values():
        if node.get("type") != "CALIB_PARAM":
            continue
        defined_in = str(node.get("defined_in", "") or "")
        parameters.append({
            "id": node.get("id", ""),
            "name": node.get("name", ""),
            "value": node.get("value"),
            "computed_value": node.get("computed_value"),
            "unit": node.get("unit"),
            "category": node.get("category"),
            "formula": node.get("formula"),
            "file_path": defined_in or None,
            "line": node.get("line"),
            "source_hash": node.get("source_hash", ""),
        })
    parameters.sort(key=lambda row: str(row.get("name", "")))

    semantics: list[dict[str, Any]] = []
    try:
        conn = sqlite3.connect(str(path))
        conn.row_factory = sqlite3.Row
        semantic_cursor = conn.execute(
            "SELECT node_id, focus, semantic_json, source_hash, learned_at "
            "FROM node_semantics ORDER BY node_id, focus"
        )
        for row in semantic_cursor.fetchall():
            try:
                semantic_value = json.loads(row["semantic_json"])
            except (TypeError, json.JSONDecodeError):
                semantic_value = row["semantic_json"]
            semantics.append({
                "node_id": row["node_id"],
                "focus": row["focus"],
                "semantic": semantic_value,
                "source_hash": row["source_hash"],
                "learned_at": row["learned_at"],
            })
    except sqlite3.Error:
        # Older/partial CodeGraph databases may not contain semantic rows.
        semantics = []
    finally:
        try:
            conn.close()
        except (NameError, AttributeError):
            pass

    index = {
        "schema_version": INDEX_SCHEMA_VERSION,
        "source_root": str(Path(source_root).expanduser().resolve()),
        "snapshot_hash": snapshot_hash,
        "parser": parser,
        "files": [dict(row) for row in file_manifest],
        "functions": functions,
        "calls": calls,
        "variables_read": variable_reads,
        "variables_written": variable_writes,
        "signals": signal_rows,
        "conditions": conditions,
        "states": states,
        "parameters": parameters,
        "semantics": semantics,
        "edges": edge_rows,
        "diagnostics": list(diagnostics or []),
        "summary": {
            "files": len(file_manifest),
            "functions": len(functions),
            "calls": sum(len(value) for value in calls.values()),
            "variables_read": len(variable_reads),
            "variables_written": len(variable_writes),
            "signals": len(signal_rows),
            "conditions": len(conditions),
            "states": len(states),
            "parameters": len(parameters),
            "semantics": len(semantics),
            "edges": len(edge_rows),
        },
    }
    return index


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CodeContextError(f"cannot read JSON artifact {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise CodeContextError(f"JSON artifact root must be object: {path}")
    return value


def _output_bound_to_other_source(context: Mapping[str, Any], source_root: Path) -> bool:
    existing = str((context.get("source_context", {}) or {}).get("source_root", ""))
    return bool(existing) and Path(existing).expanduser().resolve() != source_root


def _identity_conflicts(
    context: Mapping[str, Any],
    source_identity: Mapping[str, Any],
) -> list[str]:
    existing = context.get("source_context", {}) or {}
    conflicts: list[str] = []
    if not isinstance(existing, Mapping):
        return conflicts
    for key, value in source_identity.items():
        # Content/git identity is expected to change and is handled by the
        # snapshot hash.  Project/variant/customer bindings are the values
        # that must not be silently reused across contexts.
        if key in {"source_root", "source_snapshot_hash", "snapshot_hash"} or str(key).startswith("git_"):
            continue
        if value in (None, "", [], {}):
            continue
        old = existing.get(key)
        if old not in (None, "", [], {}) and str(old) != str(value):
            conflicts.append(str(key))
    return conflicts


def _context_identity(
    source_root: Path,
    snapshot_hash: str,
    source_identity: Mapping[str, Any] | None,
) -> str:
    return hashlib.sha256(
        _json_dump({
            "source_root": str(source_root),
            "snapshot_hash": snapshot_hash,
            "identity": dict(source_identity or {}),
        }).encode("utf-8")
    ).hexdigest()


def build_code_context(
    *,
    source_root: str | Path,
    output_dir: str | Path,
    db_path: str | Path | None = None,
    key_files: Sequence[str | Path] | None = None,
    calib_files: Sequence[str | Path] | None = None,
    function_keywords: Mapping[str, Sequence[str]] | None = None,
    source_identity: Mapping[str, Any] | None = None,
    source_docs_dir: str | Path | None = None,
    probe_git: bool = True,
    use_ast: bool = True,
    force: bool = False,
    max_files: int = 20_000,
) -> dict[str, Any]:
    """Build or reuse a deterministic ``code-context.v1`` artifact."""
    root = Path(source_root).expanduser().resolve()
    output = Path(output_dir).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    context_path = output / "code-context.json"
    index_path = output / "code-index.json"
    graph_path = (
        Path(db_path).expanduser().resolve()
        if db_path
        else output / "codegraph.db"
    )

    files = discover_source_files(root, key_files, max_files=max_files)
    file_manifest, snapshot_hash = build_source_manifest(root, files)
    identity = dict(source_identity or {})
    identity.setdefault("source_root", str(root))
    identity.setdefault("source_snapshot_hash", snapshot_hash)
    # A remote-source mirror may live inside the radarAnalyze checkout.  In
    # that case probing ``git -C`` locally would report the harness repository,
    # not the remote algo_source.  Providers can disable the local probe and
    # pass the remote git identity through ``source_identity`` instead.
    git_identity = _git_probe(root) if probe_git else {
        "repository_root": "",
        "head": "",
        "branch": "",
        "detached": False,
        "dirty": None,
        "available": False,
    }
    for key, value in git_identity.items():
        identity.setdefault(f"git_{key}", value)

    if context_path.exists():
        existing = _load_json(context_path)
        if _output_bound_to_other_source(existing, root):
            raise CodeContextError(
                f"output directory is bound to another source_root: "
                f"{existing.get('source_context', {}).get('source_root')}"
            )
        identity_conflicts = _identity_conflicts(existing, identity)
        if identity_conflicts:
            raise CodeContextError(
                "output context identity conflicts with current source identity: "
                + ",".join(identity_conflicts)
            )
        existing_source = existing.get("source_context", {}) or {}
        existing_artifacts = existing.get("artifacts", {}) or {}
        existing_index = Path(str(existing_artifacts.get("code_index", index_path)))
        existing_output_mapping = Path(str(existing_artifacts.get("output_mapping", ""))).expanduser() if existing_artifacts.get("output_mapping") else None
        embedded_output_mapping = False
        if existing_index.exists():
            try:
                embedded_output_mapping = "output_mapping" in _load_json(existing_index)
            except CodeContextError:
                embedded_output_mapping = False
        has_output_mapping = bool(
            existing_index.exists()
            and (
                existing_output_mapping is not None and existing_output_mapping.exists()
                or embedded_output_mapping
            )
        )
        if (
            not force
            and
            str(existing_source.get("snapshot_hash", "")) == snapshot_hash
            and existing_index.exists()
            and has_output_mapping
        ):
            reused = dict(existing)
            reused["operation"] = "reused"
            reused["current_snapshot_hash"] = snapshot_hash
            return reused

    if key_files:
        graph_key_files = [
            _normalise_relative(_resolve_source_file(root, value).relative_to(root))
            for value in key_files
        ]
    else:
        graph_key_files = [str(row["path"]) for row in file_manifest]
    if calib_files:
        graph_calib_files = [
            _normalise_relative(_resolve_source_file(root, value).relative_to(root))
            for value in calib_files
        ]
    else:
        graph_calib_files = [
            str(row["path"])
            for row in file_manifest
            if any(hint.lower() in str(row["path"]).lower() for hint in DEFAULT_CALIBRATION_HINTS)
        ]

    try:
        from ai.codegraph import CodeGraphBuilder
    except Exception as exc:  # pragma: no cover - import failure is environment-specific
        raise CodeContextError(f"CodeGraphBuilder import failed: {exc}") from exc

    builder = CodeGraphBuilder(
        db_path=graph_path,
        source_root=root,
        key_files=graph_key_files,
        func_keywords={
            str(key): [str(item) for item in value]
            for key, value in (function_keywords or {}).items()
        },
        calib_files=graph_calib_files,
        use_ast=bool(use_ast),
        source_docs_dir=Path(source_docs_dir).expanduser().resolve() if source_docs_dir else None,
    )
    result = builder.build()
    if not result.success:
        raise CodeContextError(f"CodeGraph build failed: {result.error}")

    # Do not publish an index if the input moved while it was being parsed.
    end_files = discover_source_files(root, key_files, max_files=max_files)
    end_manifest, end_hash = build_source_manifest(root, end_files)
    if end_hash != snapshot_hash:
        raise SourceChangedDuringBuild(
            f"source snapshot changed during build: {snapshot_hash} -> {end_hash}"
        )

    build_info = {
        "build_type": result.build_type,
        "files_scanned": result.files_scanned,
        "files_changed": result.files_changed,
        "nodes_added": result.nodes_added,
        "edges_added": result.edges_added,
        "nodes_removed": result.nodes_removed,
        "edges_removed": result.edges_removed,
        "duration_sec": result.duration_sec,
        "use_ast_requested": bool(use_ast),
    }
    index = export_code_index(
        db_path=graph_path,
        source_root=root,
        snapshot_hash=snapshot_hash,
        file_manifest=end_manifest,
        diagnostics=[],
    )
    # Reuse the existing generic Tx parser so the one-time code context also
    # carries the current source's output signals.  This is still a source
    # artifact, not a feature rule: no FCTA/FCTB names are required here.
    output_mapping_dir = (
        Path(source_docs_dir).expanduser().resolve()
        if source_docs_dir
        else output
    )
    output_mapping_path = output_mapping_dir / "output_mapping.json"
    try:
        from engines.signal_mapper import extract_output_signal_mapping

        output_mapping = extract_output_signal_mapping(
            root,
            output_mapping_dir,
        )
    except (ImportError, OSError, TypeError, ValueError):
        output_mapping = {"mappings": [], "signal_to_expr": {}, "source": "unavailable"}
    if not output_mapping_path.exists():
        _atomic_write_json(output_mapping_path, output_mapping)
    index["output_mapping"] = output_mapping
    index["output_mapping_path"] = str(output_mapping_path)
    index.setdefault("summary", {})["output_mappings"] = len(output_mapping.get("mappings", []) or [])
    raw_conditions = extract_source_conditions(
        source_root=root,
        file_manifest=end_manifest,
        functions=index.get("functions", []),
    )
    # Preserve graph-originated guards first and append raw controls that are
    # not already represented. Both remain source evidence; neither is a
    # trigger/suppression interpretation.
    existing_conditions = list(index.get("conditions", []) or [])
    condition_keys = {
        (
            str(row.get("file_path", "")),
            int(row.get("line") or 0),
            str(row.get("expression", "")),
        )
        for row in existing_conditions
        if isinstance(row, Mapping)
    }
    for row in raw_conditions:
        key = (str(row.get("file_path", "")), int(row.get("line") or 0), str(row.get("expression", "")))
        if key not in condition_keys:
            existing_conditions.append(row)
    index["conditions"] = existing_conditions
    index.setdefault("summary", {})["conditions"] = len(existing_conditions)
    _atomic_write_json(index_path, index)

    context = {
        "schema_version": CONTEXT_SCHEMA_VERSION,
        "context_id": _context_identity(root, snapshot_hash, identity),
        "status": "ready",
        "operation": "built",
        "created_at": _utc_now(),
        "source_context": {
            **identity,
            "source_root": str(root),
            "snapshot_hash": snapshot_hash,
            "git": git_identity,
            "files": end_manifest,
        },
        "build": build_info,
        "artifacts": {
            "code_context": str(context_path),
            "code_index": str(index_path),
            "codegraph_db": str(graph_path),
            "output_mapping": str(output_mapping_path),
        },
        "summary": dict(index.get("summary", {})),
        "diagnostics": list(index.get("diagnostics", [])),
    }
    _atomic_write_json(context_path, context)
    return context


def load_code_context(path: str | Path) -> dict[str, Any]:
    """Load a context artifact without reading source or executing code."""
    context_path = Path(path).expanduser().resolve()
    context = _load_json(context_path)
    if context.get("schema_version") != CONTEXT_SCHEMA_VERSION:
        raise CodeContextError(
            f"unsupported code context schema: {context.get('schema_version')}"
        )
    context["artifact_path"] = str(context_path)
    return context


def query_code_context(
    context_path: str | Path,
    *,
    section: str = "summary",
    query: str = "",
    limit: int = 200,
) -> dict[str, Any]:
    """Read a bounded section from a previously prepared context."""
    context = load_code_context(context_path)
    artifacts = context.get("artifacts", {}) or {}
    index_path = Path(str(artifacts.get("code_index", ""))).expanduser().resolve()
    if not index_path.exists():
        raise CodeContextError(f"code index artifact not found: {index_path}")
    index = _load_json(index_path)
    sections = {
        "files", "functions", "calls", "call_chain", "variables_read", "variables_written",
        "signals", "output_mapping", "conditions", "states", "parameters", "semantics", "edges",
        "summary",
    }
    selected = str(section or "summary").strip() or "summary"
    if selected not in sections:
        raise CodeContextError(f"unsupported code context section: {selected}")
    if selected == "call_chain":
        value = index.get("calls", {})
    else:
        value = index.get(selected, {} if selected in {"calls", "summary", "output_mapping"} else [])
    needle = str(query or "").strip().lower()
    if needle and selected in {"calls", "call_chain"} and isinstance(value, Mapping):
        value = {
            str(key): [item for item in items if needle in str(item).lower() or needle in str(key).lower()]
            for key, items in value.items()
            if needle in str(key).lower()
            or any(needle in str(item).lower() for item in items)
        }
    elif needle and isinstance(value, list):
        value = [
            item for item in value
            if needle in _json_dump(item).lower()
        ][: max(1, int(limit))]
    elif isinstance(value, list):
        value = value[: max(1, int(limit))]
    return {
        "schema_version": CONTEXT_SCHEMA_VERSION,
        "context": {
            "context_id": context.get("context_id", ""),
            "source_context": context.get("source_context", {}),
            "artifact_path": context.get("artifact_path", ""),
        },
        "section": selected,
        "query": query,
        "data": value,
        "index_path": str(index_path),
    }


__all__ = [
    "CONTEXT_SCHEMA_VERSION",
    "INDEX_SCHEMA_VERSION",
    "CodeContextError",
    "SourceChangedDuringBuild",
    "build_code_context",
    "build_source_manifest",
    "discover_source_files",
    "extract_source_conditions",
    "export_code_index",
    "load_code_context",
    "query_code_context",
]
