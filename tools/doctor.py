"""Local installation and runtime doctor for a radarAnalyze release.

The doctor is intentionally read-only.  It checks the supported Python
runtime, importable dependencies, repository entry points, and the capability
catalog without contacting an LLM, SSH host, ROS master, or GDB process.
"""
from __future__ import annotations

import argparse
import importlib.metadata
import importlib.util
import json
import platform
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]

REQUIRED_IMPORTS = {
    "yaml": "pyyaml",
    "dotenv": "python-dotenv",
    "rich": "rich",
    "can": "python-can",
    "cantools": "cantools",
    "rosbags": "rosbags",
    "asteval": "asteval",
}
OPTIONAL_IMPORTS = {
    "tree_sitter": "tree-sitter",
    "tree_sitter_c": "tree-sitter-c",
    "asammdf": "asammdf",
    "openai": "openai",
    "pydantic": "pydantic",
    "lancedb": "lancedb",
    "langgraph": "langgraph",
    "plotly": "plotly",
    "markdown": "markdown",
}


def _version(package: str) -> str | None:
    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return None


def _locked_requirements(project_root: Path) -> tuple[dict[str, str], list[str]]:
    path = project_root / "requirements.lock"
    if not path.is_file():
        return {}, ["requirements.lock"]
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return {}, ["requirements.lock"]
    expected: dict[str, str] = {}
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.match(r"^([A-Za-z0-9_.-]+)==([^#\s]+)$", line)
        if match:
            expected[match.group(1).lower().replace("_", "-")] = match.group(2)
    mismatches: list[str] = []
    for package, version in expected.items():
        actual = _version(package)
        if actual != version:
            mismatches.append(f"lock:{package} expected {version}, found {actual or 'missing'}")
    return expected, mismatches


def run_doctor(
    *,
    project_root: Path = PROJECT_ROOT,
    check_catalog: bool = True,
    catalog_timeout_sec: float = 180.0,
) -> dict[str, Any]:
    """Return a JSON-serializable, read-only installation report."""
    project_root = Path(project_root).resolve()
    required = {
        module: {
            "package": package,
            "available": importlib.util.find_spec(module) is not None,
            "version": _version(package),
        }
        for module, package in REQUIRED_IMPORTS.items()
    }
    optional = {
        module: {
            "package": package,
            "available": importlib.util.find_spec(module) is not None,
            "version": _version(package),
        }
        for module, package in OPTIONAL_IMPORTS.items()
    }
    files = {
        name: (project_root / name).is_file()
        for name in ("cli.py", "requirements.txt", "requirements.lock", ".env.example", "config.yaml")
    }
    locked_requirements, lock_mismatches = _locked_requirements(project_root)
    catalog: dict[str, Any] = {"status": "skipped"}
    if check_catalog and files["cli.py"]:
        try:
            proc = subprocess.run(
                [sys.executable, "cli.py", "capabilities", "--json"],
                cwd=project_root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=max(1.0, float(catalog_timeout_sec)),
                check=False,
            )
            catalog = {
                "status": "ready" if proc.returncode == 0 else "failed",
                "returncode": proc.returncode,
                "capability_count": _catalog_count(proc.stdout),
                "stderr_tail": proc.stderr[-1000:],
            }
        except (OSError, subprocess.TimeoutExpired) as exc:
            catalog = {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}
    required_missing = [module for module, item in required.items() if not item["available"]]
    missing_files = [name for name, present in files.items() if not present]
    failures = list(required_missing)
    if missing_files:
        failures.extend(f"file:{name}" for name in missing_files)
    if catalog.get("status") == "failed":
        failures.append("capability_catalog")
    failures.extend(lock_mismatches)
    return {
        "schema_version": "radar-analyze-doctor.v1",
        "status": "ready" if not failures else "blocked",
        "python": sys.version,
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "project_root": str(project_root),
        "required_imports": required,
        "optional_imports": optional,
        "entrypoint_files": files,
        "locked_requirements": locked_requirements,
        "lock_mismatches": lock_mismatches,
        "capability_catalog": catalog,
        "failures": failures,
    }


def _catalog_count(stdout: str) -> int | None:
    try:
        payload = json.loads(stdout)
    except (TypeError, json.JSONDecodeError):
        # Some Windows launchers prepend an informational line before the JSON
        # document.  Keep the probe read-only but tolerate that wrapper noise.
        text = str(stdout or "")
        starts = [index for index in (text.find("["), text.find("{")) if index >= 0]
        if not starts:
            return None
        try:
            payload = json.loads(text[min(starts):])
        except json.JSONDecodeError:
            return None
    if isinstance(payload, list):
        return len(payload)
    if isinstance(payload, dict):
        for key in ("capabilities", "items", "catalog"):
            value = payload.get(key)
            if isinstance(value, list):
                return len(value)
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    parser.add_argument("--no-catalog", action="store_true", help="skip the capability catalog probe")
    parser.add_argument("--catalog-timeout-sec", type=float, default=180.0)
    args = parser.parse_args(argv)
    report = run_doctor(
        check_catalog=not args.no_catalog,
        catalog_timeout_sec=args.catalog_timeout_sec,
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"doctor: {report['status']} ({len(report['failures'])} failure(s))")
        if report["failures"]:
            print("failures: " + ", ".join(report["failures"]))
    return 0 if report["status"] == "ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
