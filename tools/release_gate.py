"""Validate and optionally execute the machine-readable release contract."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


PROJECT_ROOT = Path(__file__).resolve().parents[1]
VALID_STATUSES = {"specified", "implemented", "partially-verified", "accepted", "blocked", "deferred"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _commit(project_root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=project_root, capture_output=True, text=True, check=False
        )
        return result.stdout.strip() if result.returncode == 0 else "unknown"
    except OSError:
        return "unknown"


def _normalise_command(command: list[str], project_root: Path) -> list[str]:
    if not command:
        return []
    result = list(command)
    if result[0] in {"python", "python3"}:
        result[0] = sys.executable
    return result


def evaluate_manifest(
    manifest_path: Path,
    *,
    project_root: Path = PROJECT_ROOT,
    run_checks: bool = True,
) -> dict[str, Any]:
    """Evaluate required entries and return a release-gate report."""
    manifest_path = Path(manifest_path).resolve()
    project_root = Path(project_root).resolve()
    errors: list[str] = []
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return {
            "schema_version": "release-gate.v1",
            "status": "blocked",
            "errors": [f"manifest_read_failed:{type(exc).__name__}:{exc}"],
            "entries": [],
        }
    if not isinstance(manifest, Mapping) or manifest.get("schema_version") != "release-acceptance.v1":
        errors.append("manifest_schema_mismatch")
    entries = manifest.get("entries", []) if isinstance(manifest, Mapping) else []
    if not isinstance(entries, list) or not entries:
        errors.append("manifest_entries_missing")
        entries = []
    ids = [str(item.get("id", "")) for item in entries if isinstance(item, Mapping)]
    duplicates = sorted({item for item in ids if item and ids.count(item) > 1})
    errors.extend(f"duplicate_entry:{item}" for item in duplicates)
    evaluated: list[dict[str, Any]] = []
    for raw in entries:
        item = dict(raw) if isinstance(raw, Mapping) else {}
        entry_id = str(item.get("id") or "")
        required = bool(item.get("required_for_release", False))
        status = str(item.get("status") or "")
        entry_errors: list[str] = []
        if not entry_id:
            entry_errors.append("id_missing")
        if status not in VALID_STATUSES:
            entry_errors.append("status_invalid")
        if required and status != "accepted":
            entry_errors.append(f"required_status:{status or 'missing'}")
        evidence_rows: list[dict[str, Any]] = []
        for evidence in item.get("evidence", []) if isinstance(item.get("evidence", []), list) else []:
            evidence = dict(evidence) if isinstance(evidence, Mapping) else {"path": str(evidence)}
            raw_path = str(evidence.get("path") or "")
            path = (project_root / raw_path).resolve() if raw_path else project_root / "__missing__"
            row = {"path": raw_path, "exists": path.is_file()}
            if path.is_file():
                row["sha256"] = _sha256(path)
                expected_hash = str(evidence.get("sha256") or "")
                if expected_hash and expected_hash != row["sha256"]:
                    row["hash_match"] = False
                    entry_errors.append(f"evidence_hash_mismatch:{raw_path}")
                else:
                    row["hash_match"] = True
            else:
                entry_errors.append(f"evidence_missing:{raw_path}")
            evidence_rows.append(row)
        if required and not evidence_rows:
            entry_errors.append("evidence_missing")
        if required and entry_id.startswith("G6-AC"):
            required_levels = item.get("required_test_levels", [])
            verified_levels = {
                str(row.get("test_level"))
                for row in item.get("evidence", [])
                if isinstance(row, Mapping) and row.get("sha256")
            }
            if not isinstance(required_levels, list) or not required_levels:
                entry_errors.append("required_test_levels_missing")
            else:
                for level in required_levels:
                    if level not in verified_levels:
                        entry_errors.append(f"test_level_evidence_missing:{level}")
        command_result: dict[str, Any] = {"status": "not_run"}
        command = item.get("command")
        if run_checks and isinstance(command, list) and command:
            argv = _normalise_command([str(part) for part in command], project_root)
            try:
                completed = subprocess.run(
                    argv,
                    cwd=project_root,
                    capture_output=True,
                    text=True,
                    timeout=float(item.get("timeout_sec", 300)),
                    check=False,
                )
                command_result = {
                    "status": "passed" if completed.returncode == 0 else "failed",
                    "argv": argv,
                    "returncode": completed.returncode,
                    "stdout_tail": completed.stdout[-2000:],
                    "stderr_tail": completed.stderr[-2000:],
                }
                if completed.returncode != 0 and required:
                    entry_errors.append("command_failed")
            except (OSError, subprocess.TimeoutExpired) as exc:
                command_result = {"status": "failed", "argv": argv, "error": f"{type(exc).__name__}: {exc}"}
                if required:
                    entry_errors.append("command_failed")
        elif required and (not isinstance(command, list) or not command):
            entry_errors.append("command_missing")
        if required and not run_checks:
            entry_errors.append("checks_not_run")
        evaluated.append({
            "id": entry_id,
            "phase": item.get("phase", ""),
            "title": item.get("title", ""),
            "required_for_release": required,
            "declared_status": status,
            "passed": not entry_errors,
            "errors": entry_errors,
            "evidence": evidence_rows,
            "command": command_result,
        })
        if entry_errors and required:
            errors.extend(f"{entry_id}:{error}" for error in entry_errors)
    required_entries = [item for item in evaluated if item["required_for_release"]]
    passed_required = sum(1 for item in required_entries if item["passed"])
    status = "accepted" if not errors and required_entries and passed_required == len(required_entries) else "blocked"
    return {
        "schema_version": "release-gate.v1",
        "status": status,
        "release_id": manifest.get("release_id") if isinstance(manifest, Mapping) else "",
        "baseline_version": manifest.get("baseline_version") if isinstance(manifest, Mapping) else "",
        "workspace_commit": _commit(project_root),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "required_entries": len(required_entries),
        "passed_required": passed_required,
        "errors": errors,
        "entries": evaluated,
    }


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=PROJECT_ROOT / "docs" / "technical" / "release_acceptance.v1.json")
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--plan-only", action="store_true", help="validate structure/evidence without running commands")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = evaluate_manifest(args.manifest, project_root=args.project_root, run_checks=not args.plan_only)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"release gate: {report['status']} ({report['passed_required']}/{report['required_entries']} required entries)")
        if report["errors"]:
            print("errors: " + ", ".join(report["errors"]))
    return 0 if report["status"] == "accepted" else 1


if __name__ == "__main__":
    raise SystemExit(main())
