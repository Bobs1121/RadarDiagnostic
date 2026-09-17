"""Validate current DDD structure and task state, never product acceptance."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def validate_state(state: dict[str, Any], acceptance_ids: set[str]) -> list[str]:
    errors: list[str] = []
    tasks = state.get("tasks", [])
    if not isinstance(tasks, list) or not all(isinstance(t, dict) for t in tasks):
        return ["tasks_must_be_object_list"]
    by_id = {t.get("id"): t for t in tasks}
    if len(by_id) != len(tasks) or None in by_id:
        errors.append("task_ids_not_unique")
    modules, covered = set(), set()
    for task in tasks:
        ident, status = task.get("id"), task.get("status")
        if status not in {"todo", "in_progress", "verifying", "done", "blocked"}:
            errors.append(f"{ident}:invalid_status")
        modules.update(task.get("modules", []))
        covered.update(task.get("acceptance", []))
        for dep in task.get("depends_on", []):
            if dep not in by_id:
                errors.append(f"{ident}:missing_dependency:{dep}")
            elif status in {"in_progress", "verifying", "done"} and by_id[dep].get("status") != "done":
                errors.append(f"{ident}:dependency_not_done:{dep}")
        if status == "done" and not task.get("evidence"):
            errors.append(f"{ident}:done_without_evidence")
        if status == "blocked" and not task.get("blockers"):
            errors.append(f"{ident}:blocked_without_reason")
    if modules != {f"M{i:02}" for i in range(1, 13)}:
        errors.append("module_coverage_must_be_M01_to_M12")
    if covered != acceptance_ids:
        errors.append("acceptance_task_coverage_mismatch")
    visiting, visited = set(), set()

    def visit(ident):
        if ident in visiting:
            errors.append(f"dependency_cycle:{ident}")
            return
        if ident in visited or ident not in by_id:
            return
        visiting.add(ident)
        for dep in by_id[ident].get("depends_on", []):
            visit(dep)
        visiting.remove(ident)
        visited.add(ident)

    for ident in by_id:
        visit(ident)
    active = [t["id"] for t in tasks if t.get("status") in {"in_progress", "verifying"}]
    if len(active) > 1:
        errors.append("multiple_active_integration_slices")
    current = state.get("current_task")
    if (current is not None or active) and current not in active:
        errors.append("current_task_not_active")
    next_task = state.get("next_task")
    if next_task is not None:
        row = by_id.get(next_task, {})
        if row.get("status") != "todo" or any(by_id.get(d, {}).get("status") != "done" for d in row.get("depends_on", [])):
            errors.append("next_task_not_ready")
    return errors


def check(root: Path = ROOT) -> dict[str, Any]:
    root = root.resolve()
    base = root / "docs/technical"
    errors: list[str] = []
    manifest = json.loads((base / "release_acceptance.v1.json").read_text(encoding="utf-8"))
    state = json.loads((base / "gen6_execution_state.v1.json").read_text(encoding="utf-8"))
    entries = manifest["entries"]
    ids = {entry["id"] for entry in entries}
    if ids != {f"G6-AC{i:02}" for i in range(1, 17)} or len(entries) != len(ids):
        errors.append("release_acceptance_ids_changed")
    if not all(entry.get("required_for_release") for entry in entries):
        errors.append("required_acceptance_downgraded")
    errors.extend(validate_state(state, ids))
    documents = sorted(base.glob("GEN6_AI_*.md"))
    for path in documents:
        text = path.read_text(encoding="utf-8")
        if text.count("```") % 2:
            errors.append(f"{path.name}:unbalanced_fence")
        for raw in re.findall(r"\]\(([^)]+)\)", text):
            if "://" in raw or raw.startswith("#"):
                continue
            if not (path.parent / raw.split("#", 1)[0].strip("<>")).is_file():
                errors.append(f"{path.name}:missing_link:{raw}")
    for path in (root / "docs").rglob("*.md"):
        relative = path.relative_to(root / "docs")
        if relative.parts[0] != "archive" and relative.as_posix() != "README.md" and not path.name.startswith("GEN6_AI_"):
            errors.append(f"parallel_active_document:{relative.as_posix()}")
    archive_map = root / "docs/archive/2026-09-17/archive-map.json"
    for row in json.loads(archive_map.read_text(encoding="utf-8"))["entries"]:
        target = root / row["to"]
        if not target.is_file():
            errors.append(f"archive_missing:{row['to']}")
        elif hashlib.sha256(target.read_bytes()).hexdigest() != row["archived_sha256"]:
            errors.append(f"archive_changed:{row['to']}")
    return {"status": "documents_valid" if not errors else "invalid", "release_acceptance": "not_evaluated",
            "document_count": len(documents), "task_count": len(state.get("tasks", [])), "acceptance_count": len(entries), "errors": errors}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = check(args.root)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        result = {"status": "invalid", "errors": [f"{type(exc).__name__}:{exc}"]}
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if result["status"] == "documents_valid" else 1


if __name__ == "__main__":
    raise SystemExit(main())
