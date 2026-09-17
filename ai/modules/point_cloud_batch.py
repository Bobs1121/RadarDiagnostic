"""Fault-isolated batch projection for point-cloud perception artifacts."""
from __future__ import annotations

import hashlib
import html
import json
import csv
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

from .base import BaseModule, ModuleResult
from .point_cloud import PointCloudAnalyzeModule
from engines.point_cloud_replay import load_perception_artifact


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()


def _load_json(path: str | Path) -> tuple[Any, str]:
    try:
        return json.loads(Path(path).expanduser().read_text(encoding="utf-8")), ""
    except FileNotFoundError:
        return None, "input_missing"
    except (OSError, UnicodeError):
        return None, "input_unreadable"
    except json.JSONDecodeError as exc:
        return None, f"invalid_json:{exc.msg}"


def _case_rows(manifest: Any, input_dir: str = "") -> list[dict[str, Any]]:
    if isinstance(manifest, Mapping):
        values = manifest.get("cases") or manifest.get("items") or []
    elif isinstance(manifest, Sequence) and not isinstance(manifest, (str, bytes, bytearray)):
        values = manifest
    else:
        values = []
    rows = [dict(item) for item in values if isinstance(item, Mapping)]
    if rows:
        return rows
    if not input_dir:
        return []
    root = Path(input_dir).expanduser()
    if not root.is_dir():
        return []
    paths = [path for suffix in ("*.json", "*.jsonl", "*.ndjson", "*.csv", "*.mf4", "*.blf", "*.bag") for path in root.glob(suffix)]
    return [{"case_id": path.stem, "capture_path": str(path)} for path in sorted(set(paths))]


def _html_index(payload: Mapping[str, Any]) -> str:
    rows = []
    output_root = Path(str(payload.get("output_dir", ""))).resolve() if payload.get("output_dir") else None
    for item in payload.get("cases", []) or []:
        if not isinstance(item, Mapping):
            continue
        report = str(item.get("report_html") or "")
        if report and output_root:
            try:
                report = Path(report).resolve().relative_to(output_root).as_posix()
            except ValueError:
                pass
        link = f'<a href="{html.escape(report, quote=True)}">report</a>' if report else "unavailable"
        row_values = (
            item.get("case_id", ""), item.get("project_id", ""), item.get("function", ""),
            item.get("stage", ""), item.get("conclusion_level", ""), item.get("status", ""),
            item.get("failure_reason", ""),
        )
        cells = "".join(f"<td>{html.escape(str(value))}</td>" for value in row_values)
        cells += f"<td>{link}</td>"
        rows.append("<tr data-search=\"" + html.escape(" ".join(str(value) for value in row_values), quote=True) + "\">" + cells + "</tr>")
    return """<!doctype html><html lang="zh-CN"><meta charset="utf-8"><link rel="icon" href="data:,"><title>Point-cloud batch index</title>
<style>body{font:14px system-ui,sans-serif;background:#101615;color:#e5f1eb;margin:24px}table{border-collapse:collapse;width:100%%}td,th{border:1px solid #365048;padding:7px;text-align:left}a{color:#8fe3bd}</style>
<h1>Point-cloud batch index</h1><p>Status: <code>%s</code>; cases: %s; completed: %s; failed: %s</p>
<label>Filter <input id="filter" type="search" placeholder="project / function / stage / status"></label>
<table id="cases"><thead><tr><th>Case</th><th>Project</th><th>Function</th><th>Stage</th><th>Conclusion</th><th>Status</th><th>Failure</th><th>Report</th></tr></thead><tbody>%s</tbody></table>
<p><a href="perception-batch-metrics.csv">Download metrics CSV</a></p>
<script>const input=document.getElementById('filter');input.addEventListener('input',()=>{const q=input.value.toLowerCase();document.querySelectorAll('#cases tbody tr').forEach(row=>{row.hidden=q && !(row.dataset.search||'').toLowerCase().includes(q);});});</script></html>""" % (
        html.escape(str(payload.get("status", "blocked"))),
        html.escape(str(payload.get("case_count", 0))),
        html.escape(str(payload.get("completed_count", 0))),
        html.escape(str(payload.get("failed_count", 0))),
        "".join(rows) or "<tr><td colspan=8>no cases</td></tr>",
    )


class PointCloudBatchModule(BaseModule):
    """Analyze each manifest item independently and write a batch index."""

    name = "point-cloud-batch"
    description = "批量生成点云感知报告和故障隔离索引"
    tags = ["point-cloud", "perception", "batch", "report", "atomic"]
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "manifest": {"type": ["object", "array"]},
            "manifest_path": {"type": "string"},
            "input_dir": {"type": "string"},
            "output_dir": {"type": "string"},
            "source_context": {"type": "object"},
            "strategy": {"type": "string", "enum": ["point_cloud", "sgu_injection"]},
        },
        "required": ["output_dir"],
        "additionalProperties": False,
    }
    output_schema: dict[str, Any] = {"type": "object", "required": ["schema_version", "status", "cases", "case_count"]}

    def run(
        self,
        *,
        manifest: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None = None,
        manifest_path: str = "",
        input_dir: str = "",
        output_dir: str = "",
        source_context: Mapping[str, Any] | None = None,
        strategy: str = "point_cloud",
        **_: Any,
    ) -> ModuleResult:
        if not str(output_dir or "").strip():
            return ModuleResult.fail("output_dir is required", module=self.name)
        manifest_obj: Any = manifest
        manifest_error = ""
        if manifest_obj is None and manifest_path:
            manifest_obj, manifest_error = _load_json(manifest_path)
        rows = _case_rows(manifest_obj, input_dir=input_dir)
        batch_started_at = time.monotonic()
        output_root = Path(output_dir).expanduser().resolve()
        output_root.mkdir(parents=True, exist_ok=True)
        entries: list[dict[str, Any]] = []
        used_case_dirs: set[str] = set()
        for index, row in enumerate(rows):
            case_id = str(row.get("case_id") or row.get("id") or f"case-{index + 1}")
            raw_safe_id = "".join(char if char.isalnum() or char in "-_" else "_" for char in case_id).strip("_") or f"case-{index + 1}"
            safe_id = raw_safe_id
            # Sanitization can collapse distinct case ids (for example
            # ``A/B`` and ``A_B``).  A deterministic identity suffix keeps
            # reruns resumable while isolating genuinely different inputs.
            if raw_safe_id != case_id:
                safe_id = f"{raw_safe_id}__{_hash({'case_id': case_id, 'project_id': row.get('project_id', ''), 'variant_id': row.get('variant_id', ''), 'capture_path': row.get('capture_path', row.get('path', ''))})[:10]}"
            candidate = safe_id
            suffix = 2
            while candidate in used_case_dirs or (output_root / "cases" / candidate).exists():
                candidate = f"{safe_id}__{index + 1 if suffix == 2 else suffix}"
                suffix += 1
            safe_id = candidate
            used_case_dirs.add(safe_id)
            case_dir = output_root / "cases" / safe_id
            entry: dict[str, Any] = {
                "case_id": case_id,
                "project_id": str(row.get("project_id", "")),
                "variant_id": str(row.get("variant_id", "")),
                "function": str(row.get("function", "")),
                "stage": str(row.get("stage", "")),
                "conclusion_level": str(row.get("conclusion_level", "")),
                "strategy": str(row.get("strategy") or strategy),
                "status": "blocked",
                "failure_reason": "",
                "report_json": "",
                "report_html": "",
            }
            capture: Mapping[str, Any] | None = row.get("capture") if isinstance(row.get("capture"), Mapping) else None
            if capture is None and any(key in row for key in ("point_rows", "points", "dot_rows", "stage_evidence", "lineage_edges")):
                capture = {key: value for key, value in row.items() if key not in {"case_id", "id", "source_context", "strategy"}}
            capture_path = str(row.get("capture_path") or row.get("path") or "")
            module_capture_path = ""
            if capture is None and capture_path:
                module_capture_path = capture_path
                capture_value, audit = load_perception_artifact(capture_path).copy(), {}
                audit = capture_value.pop("_artifact_audit", {}) if isinstance(capture_value, Mapping) else {}
                entry["artifact_audit"] = dict(audit) if isinstance(audit, Mapping) else {}
                if isinstance(audit, Mapping) and audit.get("status") != "supported":
                    entry["failure_reason"] = ";".join(str(item) for item in audit.get("diagnostics", []) or []) or "artifact_unsupported"
                    entries.append(entry)
                    continue
                capture = capture_value if isinstance(capture_value, Mapping) else None
                if capture is None:
                    entry["failure_reason"] = "capture_not_object"
                    entries.append(entry)
                    continue
            if capture is None:
                entry["failure_reason"] = "capture_missing"
                entries.append(entry)
                continue
            result = PointCloudAnalyzeModule().safe_run(
                capture=None if module_capture_path else capture,
                capture_path=module_capture_path,
                source_context={
                    **(dict(source_context) if isinstance(source_context, Mapping) else {}),
                    **(dict(row.get("source_context")) if isinstance(row.get("source_context"), Mapping) else {}),
                },
                strategy=str(row.get("strategy") or strategy),
                output_dir=str(case_dir),
            )
            payload = result.data if isinstance(result.data, Mapping) else {}
            analysis = payload.get("analysis") if isinstance(payload.get("analysis"), Mapping) else {}
            contract = analysis.get("input_contract") if isinstance(analysis.get("input_contract"), Mapping) else {}
            scene = analysis.get("scene") if isinstance(analysis.get("scene"), Mapping) else {}
            warmup = analysis.get("warmup_analysis") if isinstance(analysis.get("warmup_analysis"), Mapping) else {}
            entry["artifact_audit"] = dict(payload.get("artifact_audit", {}) or {}) if isinstance(payload.get("artifact_audit"), Mapping) else entry.get("artifact_audit", {})
            validation = payload.get("validation") if isinstance(payload.get("validation"), Mapping) else {}
            entry["validation_status"] = str(validation.get("status", ""))
            entry["point_count"] = contract.get("point_count", "")
            entry["selected_frame"] = scene.get("selected_frame", "")
            entry["warmup_status"] = warmup.get("status", "")
            entry["status"] = str(payload.get("status") or ("completed" if result.ok else "failed"))
            analysis = payload.get("analysis") if isinstance(payload.get("analysis"), Mapping) else {}
            entry["conclusion_level"] = str(analysis.get("conclusion_level") or entry.get("conclusion_level") or "")
            if not entry.get("stage"):
                coverage = analysis.get("stage_coverage") if isinstance(analysis.get("stage_coverage"), Mapping) else {}
                stages = coverage.get("stages") if isinstance(coverage.get("stages"), list) else []
                entry["stage"] = ",".join(str(item.get("stage")) for item in stages if isinstance(item, Mapping) and str(item.get("status")) in {"observed", "completed"})
            entry["failure_reason"] = "" if result.ok and entry["status"] not in {"blocked", "failed"} else str(result.message or "analysis_failed")
            entry["report_json"] = str(case_dir / "perception-report.json") if (case_dir / "perception-report.json").is_file() else ""
            entry["report_html"] = str(case_dir / "perception-report.html") if (case_dir / "perception-report.html").is_file() else ""
            entry["artifacts"] = list(result.artifacts)
            entries.append(entry)
        if manifest_error:
            diagnostics = [manifest_error]
        elif not rows:
            diagnostics = ["batch_cases_missing"]
        else:
            diagnostics = []
        completed = sum(item.get("status") in {"ready", "completed", "partial"} for item in entries)
        failed = len(entries) - completed
        if not entries:
            status = "blocked"
        elif failed:
            status = "partial"
        else:
            status = "completed"
        payload = {
            "schema_version": "perception-batch-index.v1",
            "status": status,
            "output_dir": str(output_root),
            "manifest_hash": _hash(manifest_obj if manifest_obj is not None else {"input_dir": input_dir}),
            "cases": entries,
            "case_count": len(entries),
            "completed_count": completed,
            "failed_count": failed,
            "diagnostics": diagnostics,
            "performance": {"batch_duration_sec": round(time.monotonic() - batch_started_at, 6)},
        }
        metrics_path = output_root / "perception-batch-metrics.csv"
        metric_fields = [
            "case_id", "project_id", "variant_id", "function", "stage", "strategy",
            "status", "conclusion_level", "failure_reason", "artifact_format", "artifact_status",
            "point_count", "selected_frame", "warmup_status", "validation_status", "report_json", "report_html",
        ]
        with metrics_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=metric_fields)
            writer.writeheader()
            for item in entries:
                audit = item.get("artifact_audit") if isinstance(item.get("artifact_audit"), Mapping) else {}
                writer.writerow({
                    "case_id": item.get("case_id", ""),
                    "project_id": item.get("project_id", ""),
                    "variant_id": item.get("variant_id", ""),
                    "function": item.get("function", ""),
                    "stage": item.get("stage", ""),
                    "strategy": item.get("strategy", ""),
                    "status": item.get("status", ""),
                    "conclusion_level": item.get("conclusion_level", ""),
                    "failure_reason": item.get("failure_reason", ""),
                    "artifact_format": audit.get("format", ""),
                    "artifact_status": audit.get("status", ""),
                    "point_count": item.get("point_count", ""),
                    "selected_frame": item.get("selected_frame", ""),
                    "warmup_status": item.get("warmup_status", ""),
                    "validation_status": item.get("validation_status", ""),
                    "report_json": item.get("report_json", ""),
                    "report_html": item.get("report_html", ""),
                })
        payload["metrics_csv"] = str(metrics_path)
        json_path = output_root / "perception-batch-index.json"
        html_path = output_root / "perception-batch-index.html"
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        html_path.write_text(_html_index(payload), encoding="utf-8")
        payload["artifact_paths"] = [str(json_path), str(html_path), str(metrics_path)]
        return ModuleResult(ok=True, message=f"point-cloud-batch:{status}", module=self.name, artifacts=[str(json_path), str(html_path), str(metrics_path)], data=payload)

    @classmethod
    def register_cli(cls, subparsers: Any) -> Any:
        parser = super().register_cli(subparsers)
        parser.add_argument("--manifest-path", default="")
        parser.add_argument("--input-dir", default="")
        parser.add_argument("--output-dir", required=True)
        parser.add_argument("--source-context", type=json.loads, default=None)
        parser.add_argument("--strategy", choices=["point_cloud", "sgu_injection"], default="point_cloud")
        return parser

    @classmethod
    def from_cli_args(cls, args: Any) -> "PointCloudBatchModule":
        return cls()


__all__ = ["PointCloudBatchModule"]
