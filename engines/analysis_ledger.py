# -*- coding: utf-8 -*-
"""Deterministic, append-audited Analysis Ledger.

The ledger is the durable product state behind Pi conversations and report
projections.  It stores only structured engineering records and artifact
references; it does not run an LLM, decode data, or infer root causes.

MVP entities:

* ``analysis-run.v1`` — one recoverable investigation;
* ``analysis-step.v1`` — one visible investigation stage;
* ``claim.v1`` — one evidence-bound engineering statement.

Hypothesis, DebugExperiment and user-observation contracts are separate entity
files, while their persistence still uses the same run/step/claim ledger.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import time
import uuid
from contextlib import AbstractContextManager
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


RUN_SCHEMA_VERSION = "analysis-run.v1"
STEP_SCHEMA_VERSION = "analysis-step.v1"
CLAIM_SCHEMA_VERSION = "claim.v1"
HYPOTHESIS_SCHEMA_VERSION = "hypothesis.v1"
EXPERIMENT_SCHEMA_VERSION = "debug-experiment.v1"
USER_OBSERVATION_SCHEMA_VERSION = "user-observation.v1"

RUN_STATUSES = {"created", "running", "partial", "blocked", "failed", "completed"}
STEP_STATUSES = {"running", "completed", "partial", "blocked", "failed", "skipped"}
CLAIM_STATUSES = {"observed", "derived", "inferred", "contradicted", "not_available"}
CLAIM_ACTORS = {"tool", "ai", "user"}
HYPOTHESIS_STATUSES = {
    "open", "testing", "supported", "weakened", "rejected", "confirmed_by_user",
}
HYPOTHESIS_CONFIDENCE_BANDS = {"low", "medium", "high", "unknown"}
HYPOTHESIS_ACTORS = {"tool", "ai", "user", "pi"}
EXPERIMENT_METHODS = {
    "static_query", "public_runtime", "replay", "gdb", "manual_vscode", "parameter_what_if",
}
EXPERIMENT_STATUSES = {
    "planned", "approval_required", "running", "completed", "partial", "blocked", "failed",
}
USER_OBSERVATION_KINDS = {"manual_vscode", "gdb_transcript", "screenshot", "note"}
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class LedgerError(RuntimeError):
    """Base handled error for ledger operations."""


class LedgerConflict(LedgerError):
    """Requested mutation conflicts with current durable state."""


class LedgerNotFound(LedgerError):
    """Requested run/entity does not exist."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _safe_id(value: str, *, field: str) -> str:
    text = str(value or "").strip()
    if not text or not _ID_RE.fullmatch(text):
        raise ValueError(f"{field} must match {_ID_RE.pattern}")
    return text


def _new_id(prefix: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    return f"{prefix}-{stamp}-{uuid.uuid4().hex[:10]}"


def _as_mapping(value: Mapping[str, Any] | None, *, field: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be an object")
    return dict(value)


def _as_string_list(value: Sequence[Any] | None, *, field: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError(f"{field} must be an array")
    result: list[str] = []
    for index, item in enumerate(value):
        text = str(item or "").strip()
        if not text:
            raise ValueError(f"{field}[{index}] must not be empty")
        result.append(text)
    return result


def _as_list(value: Sequence[Any] | None, *, field: str) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError(f"{field} must be an array")
    return list(value)


def _normalize_refs(value: Sequence[Any] | None, *, field: str) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError(f"{field} must be an array")
    result: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        if isinstance(item, str):
            text = item.strip()
            if not text:
                raise ValueError(f"{field}[{index}] must not be empty")
            result.append({"path": text})
        elif isinstance(item, Mapping):
            normalized = dict(item)
            if not any(normalized.get(key) for key in ("path", "artifact_id", "uri", "ref")):
                raise ValueError(
                    f"{field}[{index}] must contain path, artifact_id, uri, or ref"
                )
            result.append(normalized)
        else:
            raise ValueError(f"{field}[{index}] must be a string or object")
    return result


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, default=str)
            handle.write("\n")
            handle.flush()
            try:
                os.fsync(handle.fileno())
            except OSError:
                pass
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise LedgerNotFound(f"{label} not found: {path}") from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LedgerError(f"{label} cannot be read: {path}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise LedgerError(f"{label} must contain a JSON object: {path}")
    return dict(payload)


class _RunLock(AbstractContextManager["_RunLock"]):
    """Small cross-platform lock based on atomic exclusive file creation."""

    def __init__(self, path: Path, *, timeout_sec: float = 5.0, stale_sec: float = 120.0) -> None:
        self.path = path
        self.timeout_sec = max(0.1, float(timeout_sec))
        self.stale_sec = max(self.timeout_sec, float(stale_sec))
        self._fd: int | None = None

    def __enter__(self) -> "_RunLock":
        deadline = time.monotonic() + self.timeout_sec
        self.path.parent.mkdir(parents=True, exist_ok=True)
        while True:
            try:
                self._fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(self._fd, f"pid={os.getpid()} created={_utc_now()}\n".encode("utf-8"))
                return self
            except FileExistsError:
                try:
                    age_sec = time.time() - self.path.stat().st_mtime
                    if age_sec > self.stale_sec:
                        self.path.unlink(missing_ok=True)
                        continue
                except OSError:
                    pass
                if time.monotonic() >= deadline:
                    raise LedgerConflict(f"ledger lock timeout: {self.path}")
                time.sleep(0.05)

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            pass
        return None


class AnalysisLedger:
    """Local deterministic store for one or more analysis runs."""

    def __init__(self, ledger_root: str | Path) -> None:
        self.root = Path(ledger_root).expanduser().resolve()

    def _run_dir(self, run_id: str) -> Path:
        return self.root / _safe_id(run_id, field="run_id")

    @staticmethod
    def _run_path(run_dir: Path) -> Path:
        return run_dir / "analysis-run.json"

    @staticmethod
    def _entity_path(run_dir: Path, kind: str, entity_id: str) -> Path:
        directories = {
            "step": "steps",
            "claim": "claims",
            "hypothesis": "hypotheses",
            "experiment": "experiments",
            "user_observation": "user-observations",
        }
        if kind not in directories:
            raise ValueError(f"unsupported ledger entity kind: {kind}")
        safe_entity_id = _safe_id(entity_id, field=f"{kind}_id")
        return run_dir / directories[kind] / f"{safe_entity_id}.json"

    @staticmethod
    def _ref(kind: str, entity_id: str, path: Path) -> dict[str, Any]:
        return {"kind": kind, "id": entity_id, "path": str(path)}

    def _append_event(self, run_dir: Path, run: dict[str, Any], event: dict[str, Any]) -> None:
        sequence = int(run.get("event_sequence", 0)) + 1
        run["event_sequence"] = sequence
        event_payload = {
            "schema_version": "analysis-ledger-event.v1",
            "sequence": sequence,
            "run_id": run["run_id"],
            "recorded_at": _utc_now(),
            **event,
        }
        event_path = run_dir / "events.jsonl"
        line = json.dumps(event_payload, ensure_ascii=False, separators=(",", ":"), default=str) + "\n"
        with event_path.open("a", encoding="utf-8", newline="") as handle:
            handle.write(line)
            handle.flush()
            try:
                os.fsync(handle.fileno())
            except OSError:
                pass

    def _load_run(self, run_dir: Path) -> dict[str, Any]:
        run = _read_json(self._run_path(run_dir), label="analysis run")
        if run.get("schema_version") != RUN_SCHEMA_VERSION:
            raise LedgerError(
                f"unsupported analysis run schema: {run.get('schema_version', 'missing')}"
            )
        return run

    def _save_run(self, run_dir: Path, run: dict[str, Any]) -> None:
        run["updated_at"] = _utc_now()
        _atomic_write_json(self._run_path(run_dir), run)

    def create_run(
        self,
        *,
        goal: Mapping[str, Any],
        binding: Mapping[str, Any] | None = None,
        policy: Mapping[str, Any] | None = None,
        artifact_refs: Sequence[Any] | None = None,
        run_id: str = "",
        owner: str = "",
    ) -> dict[str, Any]:
        normalized_goal = _as_mapping(goal, field="goal")
        if not str(normalized_goal.get("question", "")).strip():
            raise ValueError("goal.question is required")
        selected_run_id = _safe_id(run_id, field="run_id") if run_id else _new_id("run")
        run_dir = self._run_dir(selected_run_id)
        try:
            run_dir.mkdir(parents=True, exist_ok=False)
        except FileExistsError as exc:
            raise LedgerConflict(f"analysis run already exists: {selected_run_id}") from exc
        for directory in (
            "steps",
            "claims",
            "hypotheses",
            "experiments",
            "user-observations",
        ):
            (run_dir / directory).mkdir(parents=True, exist_ok=True)
        created_at = _utc_now()
        payload: dict[str, Any] = {
            "schema_version": RUN_SCHEMA_VERSION,
            "run_id": selected_run_id,
            "owner": str(owner or ""),
            "goal": normalized_goal,
            "binding": _as_mapping(binding, field="binding"),
            "policy": _as_mapping(policy, field="policy"),
            "status": "created",
            "current_stage": "intake",
            "created_at": created_at,
            "updated_at": created_at,
            "event_sequence": 0,
            "steps": [],
            "claims": [],
            "hypotheses": [],
            "experiments": [],
            "user_observations": [],
            "artifacts": _normalize_refs(artifact_refs, field="artifact_refs"),
            "metrics": {
                "time_to_first_useful_clue_sec": None,
                "time_to_debug_ready_sec": None,
                "bag_full_read_count": 0,
                "replay_attempt_count": 0,
                "gdb_stop_count": 0,
                "user_intervention_count": 0,
            },
        }
        self._append_event(run_dir, payload, {"event": "run_created", "actor": owner or "tool"})
        _atomic_write_json(self._run_path(run_dir), payload)
        return {**payload, "run_dir": str(run_dir), "artifact_path": str(self._run_path(run_dir))}

    def read_run(self, run_id: str, *, include_entities: bool = False) -> dict[str, Any]:
        run_dir = self._run_dir(run_id)
        run = self._load_run(run_dir)
        result = dict(run)
        result["run_dir"] = str(run_dir)
        result["artifact_path"] = str(self._run_path(run_dir))
        result["summary"] = self._summary(run)
        if include_entities:
            result["entities"] = {
                "steps": self._load_refs(run.get("steps", []), label="step"),
                "claims": self._load_refs(run.get("claims", []), label="claim"),
                "hypotheses": self._load_refs(run.get("hypotheses", []), label="hypothesis"),
                "experiments": self._load_refs(run.get("experiments", []), label="experiment"),
                "user_observations": self._load_refs(
                    run.get("user_observations", []), label="user observation"
                ),
            }
        return result

    @staticmethod
    def _load_refs(refs: Any, *, label: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        if not isinstance(refs, list):
            return rows
        for ref in refs:
            if not isinstance(ref, Mapping) or not ref.get("path"):
                continue
            rows.append(_read_json(Path(str(ref["path"])), label=label))
        return rows

    def _summary(self, run: Mapping[str, Any]) -> dict[str, Any]:
        critical_gap_count = 0
        for item in run.get("steps", []) or []:
            if not isinstance(item, Mapping):
                continue
            if "critical_gap_count" in item:
                critical_gap_count += int(item.get("critical_gap_count", 0) or 0)
                continue
            # Backward-compatible read for runs created before the compact
            # step ref carried a critical gap count.  This is read-only and
            # keeps resume/project views accurate without rewriting history.
            if item.get("path"):
                try:
                    step = _read_json(Path(str(item["path"])), label="analysis step")
                except LedgerError:
                    continue
                critical_gap_count += sum(
                    1
                    for gap in step.get("gaps", []) or []
                    if isinstance(gap, Mapping) and gap.get("critical") is True
                )
        return {
            "run_id": run.get("run_id"),
            "status": run.get("status"),
            "current_stage": run.get("current_stage"),
            "step_count": len(run.get("steps", []) or []),
            "claim_count": len(run.get("claims", []) or []),
            "hypothesis_count": len(run.get("hypotheses", []) or []),
            "experiment_count": len(run.get("experiments", []) or []),
            "user_observation_count": len(run.get("user_observations", []) or []),
            "critical_gap_count": critical_gap_count,
            "updated_at": run.get("updated_at"),
        }

    def begin_step(
        self,
        run_id: str,
        *,
        stage: str,
        input_artifact_refs: Sequence[Any] | None = None,
        tool_calls: Sequence[Any] | None = None,
        created_by: str = "tool",
        step_id: str = "",
        metrics: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        selected_step_id = _safe_id(step_id, field="step_id") if step_id else _new_id("step")
        stage_name = _safe_id(stage, field="stage")
        run_dir = self._run_dir(run_id)
        with _RunLock(run_dir / ".ledger.lock"):
            run = self._load_run(run_dir)
            step_path = self._entity_path(run_dir, "step", selected_step_id)
            if step_path.exists():
                raise LedgerConflict(f"analysis step already exists: {selected_step_id}")
            started_at = _utc_now()
            normalized_tool_calls = _as_list(tool_calls, field="tool_calls")
            step: dict[str, Any] = {
                "schema_version": STEP_SCHEMA_VERSION,
                "step_id": selected_step_id,
                "run_id": run["run_id"],
                "stage": stage_name,
                "status": "running",
                "created_by": str(created_by or "tool"),
                "started_at": started_at,
                "finished_at": "",
                "duration_sec": None,
                "input_artifact_refs": _normalize_refs(
                    input_artifact_refs, field="input_artifact_refs"
                ),
                "output_artifact_refs": [],
                "tool_calls": [
                    dict(item) if isinstance(item, Mapping) else {"name": str(item)}
                    for item in normalized_tool_calls
                ],
                "observations": [],
                "claim_refs": [],
                "gaps": [],
                "conflicts": [],
                "user_visible_summary": "",
                "next_action_candidates": [],
                "metrics": _as_mapping(metrics, field="metrics"),
            }
            _atomic_write_json(step_path, step)
            step_ref = {
                **self._ref("step", selected_step_id, step_path),
                "stage": stage_name,
                "status": "running",
                "started_at": started_at,
                "gap_count": 0,
                "critical_gap_count": 0,
                "conflict_count": 0,
            }
            run.setdefault("steps", []).append(step_ref)
            run["status"] = "running"
            run["current_stage"] = stage_name
            self._append_event(
                run_dir,
                run,
                {"event": "step_started", "actor": created_by or "tool", "step_ref": step_ref},
            )
            self._save_run(run_dir, run)
            return {**step, "artifact_path": str(step_path), "run_artifact_path": str(self._run_path(run_dir))}

    def complete_step(
        self,
        run_id: str,
        step_id: str,
        *,
        status: str = "completed",
        output_artifact_refs: Sequence[Any] | None = None,
        observations: Sequence[Any] | None = None,
        gaps: Sequence[Any] | None = None,
        conflicts: Sequence[Any] | None = None,
        user_visible_summary: str = "",
        next_action_candidates: Sequence[Any] | None = None,
        metrics: Mapping[str, Any] | None = None,
        actor: str = "tool",
    ) -> dict[str, Any]:
        final_status = str(status or "").strip()
        if final_status not in STEP_STATUSES - {"running"}:
            raise ValueError(f"unsupported final step status: {final_status}")
        run_dir = self._run_dir(run_id)
        selected_step_id = _safe_id(step_id, field="step_id")
        with _RunLock(run_dir / ".ledger.lock"):
            run = self._load_run(run_dir)
            step_path = self._entity_path(run_dir, "step", selected_step_id)
            step = _read_json(step_path, label="analysis step")
            if step.get("run_id") != run["run_id"]:
                raise LedgerConflict("step belongs to another analysis run")
            if step.get("status") != "running":
                raise LedgerConflict(
                    f"analysis step is not running: {selected_step_id}:{step.get('status')}"
                )
            finished_at = _utc_now()
            step["status"] = final_status
            step["finished_at"] = finished_at
            try:
                start = datetime.fromisoformat(str(step["started_at"]).replace("Z", "+00:00"))
                finish = datetime.fromisoformat(finished_at.replace("Z", "+00:00"))
                step["duration_sec"] = round((finish - start).total_seconds(), 6)
            except (KeyError, TypeError, ValueError):
                step["duration_sec"] = None
            step["output_artifact_refs"] = _normalize_refs(
                output_artifact_refs, field="output_artifact_refs"
            )
            step["observations"] = _as_list(observations, field="observations")
            step["gaps"] = _as_list(gaps, field="gaps")
            step["conflicts"] = _as_list(conflicts, field="conflicts")
            step["user_visible_summary"] = str(user_visible_summary or "")
            step["next_action_candidates"] = _as_list(
                next_action_candidates, field="next_action_candidates"
            )
            if not isinstance(step.get("metrics"), Mapping):
                step["metrics"] = {}
            else:
                step["metrics"] = dict(step["metrics"])
            step["metrics"].update(_as_mapping(metrics, field="metrics"))
            _atomic_write_json(step_path, step)

            critical_gap_count = sum(
                1
                for gap in step["gaps"]
                if isinstance(gap, Mapping) and gap.get("critical") is True
            )

            for step_ref in run.get("steps", []):
                if isinstance(step_ref, dict) and step_ref.get("id") == selected_step_id:
                    step_ref.update(
                        {
                            "status": final_status,
                            "finished_at": finished_at,
                            "gap_count": len(step["gaps"]),
                            "critical_gap_count": critical_gap_count,
                            "conflict_count": len(step["conflicts"]),
                            "summary": step["user_visible_summary"],
                            "metrics": dict(step["metrics"]),
                        }
                    )
                    break

            run["current_stage"] = step["stage"]
            run["status"] = (
                "blocked"
                if final_status == "blocked"
                else "failed"
                if final_status == "failed"
                else "partial"
                if final_status == "partial"
                else "running"
            )
            if step["observations"] and run["metrics"].get("time_to_first_useful_clue_sec") is None:
                try:
                    created = datetime.fromisoformat(str(run["created_at"]).replace("Z", "+00:00"))
                    finish = datetime.fromisoformat(finished_at.replace("Z", "+00:00"))
                    run["metrics"]["time_to_first_useful_clue_sec"] = round(
                        (finish - created).total_seconds(), 6
                    )
                except (KeyError, TypeError, ValueError):
                    pass
            for metric_name in (
                "bag_full_read_count",
                "replay_attempt_count",
                "gdb_stop_count",
                "user_intervention_count",
            ):
                value = step["metrics"].get(metric_name)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    current = run["metrics"].get(metric_name, 0)
                    if not isinstance(current, (int, float)) or isinstance(current, bool):
                        current = 0
                    run["metrics"][metric_name] = current + value
            self._append_event(
                run_dir,
                run,
                {
                    "event": "step_completed",
                    "actor": actor or "tool",
                    "step_ref": self._ref("step", selected_step_id, step_path),
                    "status": final_status,
                },
            )
            self._save_run(run_dir, run)
            return {**step, "artifact_path": str(step_path), "run_artifact_path": str(self._run_path(run_dir))}

    def update_run(
        self,
        run_id: str,
        *,
        status: str = "",
        current_stage: str = "",
        metrics: Mapping[str, Any] | None = None,
        metric_mode: str = "merge",
        actor: str = "tool",
        binding: Mapping[str, Any] | None = None,
        artifact_refs: Sequence[Any] | None = None,
    ) -> dict[str, Any]:
        run_dir = self._run_dir(run_id)
        selected_status = str(status or "").strip()
        if selected_status and selected_status not in RUN_STATUSES:
            raise ValueError(f"unsupported run status: {selected_status}")
        stage_name = _safe_id(current_stage, field="current_stage") if current_stage else ""
        mode = str(metric_mode or "merge").strip()
        if mode not in {"merge", "increment"}:
            raise ValueError("metric_mode must be merge or increment")
        metric_values = _as_mapping(metrics, field="metrics")
        binding_values = _as_mapping(binding, field="binding")
        refs = _normalize_refs(artifact_refs, field="artifact_refs")
        with _RunLock(run_dir / ".ledger.lock"):
            run = self._load_run(run_dir)
            existing_binding = run.get("binding")
            if not isinstance(existing_binding, Mapping):
                existing_binding = {}
            for key, value in binding_values.items():
                if value in (None, "", []):
                    continue
                if key in existing_binding and existing_binding[key] not in (None, "", []) and str(existing_binding[key]) != str(value):
                    raise LedgerConflict(
                        f"run binding conflict for {key}: {existing_binding[key]!r} != {value!r}"
                    )
            run["binding"] = {**dict(existing_binding), **binding_values}
            if refs:
                current_refs = run.get("artifacts")
                if not isinstance(current_refs, list):
                    current_refs = []
                merged_refs = list(current_refs)
                for ref in refs:
                    if not any(
                        isinstance(item, Mapping)
                        and item.get("path") == ref.get("path")
                        and item.get("kind") == ref.get("kind")
                        for item in merged_refs
                    ):
                        merged_refs.append(ref)
                run["artifacts"] = merged_refs
            if selected_status:
                run["status"] = selected_status
            if stage_name:
                run["current_stage"] = stage_name
            run_metrics = run.get("metrics")
            if not isinstance(run_metrics, Mapping):
                run_metrics = {}
            run["metrics"] = dict(run_metrics)
            for key, value in metric_values.items():
                if mode == "increment":
                    if not isinstance(value, (int, float)) or isinstance(value, bool):
                        raise ValueError(f"increment metric must be numeric: {key}")
                    current = run["metrics"].get(key, 0)
                    if not isinstance(current, (int, float)) or isinstance(current, bool):
                        current = 0
                    run["metrics"][key] = current + value
                else:
                    run["metrics"][key] = value
            self._append_event(
                run_dir,
                run,
                {
                    "event": "run_updated",
                    "actor": actor or "tool",
                    "status": selected_status or run.get("status"),
                    "current_stage": stage_name or run.get("current_stage"),
                    "metric_mode": mode,
                    "metrics": metric_values,
                    "binding_keys": sorted(binding_values),
                    "artifact_ref_count": len(refs),
                },
            )
            self._save_run(run_dir, run)
            result = dict(run)
            result["run_dir"] = str(run_dir)
            result["artifact_path"] = str(self._run_path(run_dir))
            result["summary"] = self._summary(run)
            return result

    @staticmethod
    def _ensure_binding_compatible(
        run: Mapping[str, Any],
        binding: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        """Reject an entity update that would cross the run identity."""
        incoming = _as_mapping(binding, field="binding")
        existing = run.get("binding") if isinstance(run.get("binding"), Mapping) else {}
        for key, value in incoming.items():
            if value in (None, "", []):
                continue
            if key in existing and existing.get(key) not in (None, "", []) and str(existing[key]) != str(value):
                raise LedgerConflict(
                    f"run binding conflict for {key}: {existing[key]!r} != {value!r}"
                )
        return incoming

    @staticmethod
    def _replace_entity_ref(refs: list[Any], ref: Mapping[str, Any]) -> None:
        """Insert or update one compact entity ref without reordering history."""
        entity_id = str(ref.get("id") or "")
        for index, item in enumerate(refs):
            if isinstance(item, Mapping) and str(item.get("id") or "") == entity_id:
                refs[index] = dict(ref)
                return
        refs.append(dict(ref))

    def upsert_hypothesis(
        self,
        run_id: str,
        *,
        category: str = "",
        statement: str = "",
        status: str = "open",
        rank: int | None = None,
        confidence_band: str = "unknown",
        supporting_claim_refs: Sequence[Any] | None = None,
        contradicting_claim_refs: Sequence[Any] | None = None,
        required_evidence: Sequence[Any] | None = None,
        experiment_refs: Sequence[Any] | None = None,
        binding: Mapping[str, Any] | None = None,
        reason: str = "",
        actor: str = "tool",
        hypothesis_id: str = "",
    ) -> dict[str, Any]:
        """Create/update one hypothesis while preserving every state change."""
        actor_name = str(actor or "tool").strip()
        if actor_name not in HYPOTHESIS_ACTORS:
            raise ValueError(f"actor must be one of {sorted(HYPOTHESIS_ACTORS)}")
        requested_status = str(status or "").strip()
        if requested_status and requested_status not in HYPOTHESIS_STATUSES:
            raise ValueError(f"unsupported hypothesis status: {requested_status}")
        requested_confidence = str(confidence_band or "").strip()
        if requested_confidence and requested_confidence not in HYPOTHESIS_CONFIDENCE_BANDS:
            raise ValueError(f"unsupported confidence_band: {requested_confidence}")
        category_text = str(category or "").strip()
        statement_text = str(statement or "").strip()
        selected_id = _safe_id(hypothesis_id, field="hypothesis_id") if hypothesis_id else _new_id("hyp")
        run_dir = self._run_dir(run_id)
        with _RunLock(run_dir / ".ledger.lock"):
            run = self._load_run(run_dir)
            binding_values = self._ensure_binding_compatible(run, binding)
            hypothesis_path = self._entity_path(run_dir, "hypothesis", selected_id)
            if hypothesis_path.exists():
                hypothesis = _read_json(hypothesis_path, label="hypothesis")
                if str(hypothesis.get("run_id")) != str(run["run_id"]):
                    raise LedgerConflict("hypothesis belongs to another analysis run")
                previous_status = str(hypothesis.get("status") or "open")
                selected_status = requested_status or previous_status
                selected_confidence = requested_confidence or str(hypothesis.get("confidence_band") or "unknown")
                if previous_status == "confirmed_by_user" and selected_status != previous_status and actor_name != "user":
                    raise LedgerConflict("a user-confirmed hypothesis cannot be changed by a non-user actor")
                if selected_status == "confirmed_by_user" and actor_name != "user":
                    raise ValueError("only a user may confirm a hypothesis")
                if category_text:
                    hypothesis["category"] = category_text
                if statement_text:
                    hypothesis["statement"] = statement_text
                if rank is not None:
                    if isinstance(rank, bool) or int(rank) < 1:
                        raise ValueError("rank must be an integer >= 1")
                    hypothesis["rank"] = int(rank)
                hypothesis["confidence_band"] = selected_confidence
                hypothesis["status"] = selected_status
                if supporting_claim_refs is not None:
                    hypothesis["supporting_claim_refs"] = _normalize_refs(
                        supporting_claim_refs, field="supporting_claim_refs"
                    )
                if contradicting_claim_refs is not None:
                    hypothesis["contradicting_claim_refs"] = _normalize_refs(
                        contradicting_claim_refs, field="contradicting_claim_refs"
                    )
                if required_evidence is not None:
                    hypothesis["required_evidence"] = _as_list(required_evidence, field="required_evidence")
                if experiment_refs is not None:
                    hypothesis["experiment_refs"] = _normalize_refs(experiment_refs, field="experiment_refs")
                if binding_values:
                    hypothesis["binding"] = {**dict(hypothesis.get("binding", {}) or {}), **binding_values}
                history = hypothesis.setdefault("history", [])
                if not isinstance(history, list):
                    history = []
                    hypothesis["history"] = history
                history.append({
                    "event": "updated",
                    "at": _utc_now(),
                    "actor": actor_name,
                    "status_before": previous_status,
                    "status_after": selected_status,
                    "reason": str(reason or ""),
                    "supporting_claim_refs": _normalize_refs(supporting_claim_refs, field="supporting_claim_refs") if supporting_claim_refs is not None else [],
                    "contradicting_claim_refs": _normalize_refs(contradicting_claim_refs, field="contradicting_claim_refs") if contradicting_claim_refs is not None else [],
                })
            else:
                if not category_text:
                    raise ValueError("category is required when creating a hypothesis")
                if not statement_text:
                    raise ValueError("statement is required when creating a hypothesis")
                selected_status = requested_status or "open"
                selected_confidence = requested_confidence or "unknown"
                if selected_status == "confirmed_by_user" and actor_name != "user":
                    raise ValueError("only a user may confirm a hypothesis")
                if rank is not None and (isinstance(rank, bool) or int(rank) < 1):
                    raise ValueError("rank must be an integer >= 1")
                hypothesis = {
                    "schema_version": HYPOTHESIS_SCHEMA_VERSION,
                    "hypothesis_id": selected_id,
                    "run_id": run["run_id"],
                    "category": category_text,
                    "statement": statement_text,
                    "rank": int(rank) if rank is not None else None,
                    "confidence_band": selected_confidence,
                    "status": selected_status,
                    "supporting_claim_refs": _normalize_refs(supporting_claim_refs, field="supporting_claim_refs"),
                    "contradicting_claim_refs": _normalize_refs(contradicting_claim_refs, field="contradicting_claim_refs"),
                    "required_evidence": _as_list(required_evidence, field="required_evidence"),
                    "experiment_refs": _normalize_refs(experiment_refs, field="experiment_refs"),
                    "history": [{
                        "event": "created",
                        "at": _utc_now(),
                        "actor": actor_name,
                        "status_after": selected_status,
                        "reason": str(reason or ""),
                    }],
                    "binding": binding_values,
                }
            if selected_confidence not in HYPOTHESIS_CONFIDENCE_BANDS:
                raise ValueError(f"unsupported confidence_band: {selected_confidence}")
            hypothesis["updated_at"] = _utc_now()
            _atomic_write_json(hypothesis_path, hypothesis)
            ref = {
                **self._ref("hypothesis", selected_id, hypothesis_path),
                "category": hypothesis.get("category", ""),
                "status": hypothesis.get("status", "open"),
                "rank": hypothesis.get("rank"),
                "confidence_band": hypothesis.get("confidence_band", "unknown"),
                "statement": hypothesis.get("statement", ""),
            }
            self._replace_entity_ref(run.setdefault("hypotheses", []), ref)
            self._append_event(
                run_dir,
                run,
                {"event": "hypothesis_upserted", "actor": actor_name, "hypothesis_ref": ref},
            )
            self._save_run(run_dir, run)
            return {
                **hypothesis,
                "artifact_path": str(hypothesis_path),
                "run_artifact_path": str(self._run_path(run_dir)),
            }

    def record_experiment(
        self,
        run_id: str,
        *,
        question: str = "",
        method: str = "",
        status: str = "planned",
        target: Mapping[str, Any] | None = None,
        plan_ref: Mapping[str, Any] | None = None,
        approval: Mapping[str, Any] | None = None,
        session_ref: Mapping[str, Any] | None = None,
        watch_groups: Sequence[Any] | None = None,
        expected_discrimination: Sequence[Any] | None = None,
        observations: Sequence[Any] | None = None,
        disturbance: Mapping[str, Any] | None = None,
        conclusion_delta: Sequence[Any] | None = None,
        hypothesis_refs: Sequence[Any] | None = None,
        binding: Mapping[str, Any] | None = None,
        reason: str = "",
        actor: str = "tool",
        experiment_id: str = "",
    ) -> dict[str, Any]:
        """Create/update a planned experiment or record its result."""
        actor_name = str(actor or "tool").strip()
        if actor_name not in HYPOTHESIS_ACTORS:
            raise ValueError(f"actor must be one of {sorted(HYPOTHESIS_ACTORS)}")
        requested_method = str(method or "").strip()
        if requested_method and requested_method not in EXPERIMENT_METHODS:
            raise ValueError(f"unsupported experiment method: {requested_method}")
        selected_status = str(status or "planned").strip()
        if selected_status not in EXPERIMENT_STATUSES:
            raise ValueError(f"unsupported experiment status: {selected_status}")
        question_text = str(question or "").strip()
        selected_id = _safe_id(experiment_id, field="experiment_id") if experiment_id else _new_id("experiment")
        run_dir = self._run_dir(run_id)
        with _RunLock(run_dir / ".ledger.lock"):
            run = self._load_run(run_dir)
            binding_values = self._ensure_binding_compatible(run, binding)
            experiment_path = self._entity_path(run_dir, "experiment", selected_id)
            is_update = experiment_path.exists()
            if is_update:
                experiment = _read_json(experiment_path, label="debug experiment")
                if str(experiment.get("run_id")) != str(run["run_id"]):
                    raise LedgerConflict("experiment belongs to another analysis run")
                selected_method = requested_method or str(experiment.get("method") or "")
                if selected_method not in EXPERIMENT_METHODS:
                    raise ValueError(f"unsupported experiment method: {selected_method}")
                if (
                    selected_status in {"completed", "partial", "failed"}
                    and str(experiment.get("status") or "") not in {"planned", "approval_required", "running"}
                    and not experiment.get("plan_ref")
                    and not plan_ref
                ):
                    raise ValueError("experiment result requires a previously recorded plan")
                if question_text:
                    experiment["question"] = question_text
                experiment["method"] = selected_method
                experiment["status"] = selected_status
                for key, value in (
                    ("target", target), ("plan_ref", plan_ref), ("approval", approval),
                    ("session_ref", session_ref), ("disturbance", disturbance),
                ):
                    if value is not None:
                        experiment[key] = deepcopy(dict(value))
                for key, value in (
                    ("watch_groups", watch_groups), ("expected_discrimination", expected_discrimination),
                    ("observations", observations), ("conclusion_delta", conclusion_delta),
                    ("hypothesis_refs", hypothesis_refs),
                ):
                    if value is not None:
                        if key == "hypothesis_refs":
                            experiment[key] = _normalize_refs(value, field=key)
                        else:
                            experiment[key] = _as_list(value, field=key)
                if binding_values:
                    experiment["binding"] = {**dict(experiment.get("binding", {}) or {}), **binding_values}
                updates = experiment.setdefault("updates", [])
                if not isinstance(updates, list):
                    updates = []
                    experiment["updates"] = updates
                updates.append({
                    "at": _utc_now(),
                    "actor": actor_name,
                    "status": selected_status,
                    "reason": str(reason or ""),
                })
            else:
                if not question_text:
                    raise ValueError("question is required when creating an experiment")
                selected_method = requested_method or ""
                if selected_method not in EXPERIMENT_METHODS:
                    raise ValueError("method is required when creating an experiment")
                if selected_status != "planned":
                    raise ValueError("create an experiment as planned before recording a result")
                experiment = {
                    "schema_version": EXPERIMENT_SCHEMA_VERSION,
                    "experiment_id": selected_id,
                    "run_id": run["run_id"],
                    "question": question_text,
                    "method": selected_method,
                    "target": deepcopy(dict(target or {})),
                    "plan_ref": deepcopy(dict(plan_ref)) if isinstance(plan_ref, Mapping) else None,
                    "approval": deepcopy(dict(approval or {})),
                    "session_ref": deepcopy(dict(session_ref)) if isinstance(session_ref, Mapping) else None,
                    "watch_groups": _as_list(watch_groups, field="watch_groups"),
                    "expected_discrimination": _as_list(expected_discrimination, field="expected_discrimination"),
                    "observations": _as_list(observations, field="observations"),
                    "disturbance": deepcopy(dict(disturbance or {})),
                    "conclusion_delta": _as_list(conclusion_delta, field="conclusion_delta"),
                    "hypothesis_refs": _normalize_refs(hypothesis_refs, field="hypothesis_refs"),
                    "status": "planned",
                    "updates": [{
                        "at": _utc_now(),
                        "actor": actor_name,
                        "status": "planned",
                        "reason": str(reason or ""),
                    }],
                    "binding": binding_values,
                }
            experiment["updated_at"] = _utc_now()
            _atomic_write_json(experiment_path, experiment)
            ref = {
                **self._ref("experiment", selected_id, experiment_path),
                "status": experiment.get("status", "planned"),
                "method": experiment.get("method", selected_method),
                "question": experiment.get("question", ""),
            }
            self._replace_entity_ref(run.setdefault("experiments", []), ref)
            self._append_event(
                run_dir,
                run,
                {"event": "experiment_recorded", "actor": actor_name, "experiment_ref": ref},
            )
            self._save_run(run_dir, run)
            return {
                **experiment,
                "artifact_path": str(experiment_path),
                "run_artifact_path": str(self._run_path(run_dir)),
            }

    def append_user_observation(
        self,
        run_id: str,
        *,
        kind: str = "note",
        summary: str,
        content: str = "",
        artifact_refs: Sequence[Any] | None = None,
        target: Mapping[str, Any] | None = None,
        experiment_id: str = "",
        hypothesis_refs: Sequence[Any] | None = None,
        binding: Mapping[str, Any] | None = None,
        observation_id: str = "",
        created_by: str = "user",
    ) -> dict[str, Any]:
        """Persist a user's manual observation without upgrading its authority."""
        actor_name = str(created_by or "user").strip()
        if actor_name != "user":
            raise ValueError("user observations must be created_by=user")
        kind_name = str(kind or "note").strip()
        if kind_name not in USER_OBSERVATION_KINDS:
            raise ValueError(f"unsupported user observation kind: {kind_name}")
        summary_text = str(summary or "").strip()
        if not summary_text:
            raise ValueError("summary is required")
        selected_id = _safe_id(observation_id, field="observation_id") if observation_id else _new_id("user-observation")
        run_dir = self._run_dir(run_id)
        with _RunLock(run_dir / ".ledger.lock"):
            run = self._load_run(run_dir)
            binding_values = self._ensure_binding_compatible(run, binding)
            observation_path = self._entity_path(run_dir, "user_observation", selected_id)
            if observation_path.exists():
                raise LedgerConflict(f"user observation already exists: {selected_id}")
            observation = {
                "schema_version": USER_OBSERVATION_SCHEMA_VERSION,
                "observation_id": selected_id,
                "run_id": run["run_id"],
                "kind": kind_name,
                "summary": summary_text,
                "content": str(content or ""),
                "artifact_refs": _normalize_refs(artifact_refs, field="artifact_refs"),
                "target": deepcopy(dict(target or {})),
                "experiment_id": str(experiment_id or ""),
                "hypothesis_refs": _normalize_refs(hypothesis_refs, field="hypothesis_refs"),
                "created_by": actor_name,
                "created_at": _utc_now(),
                "binding": binding_values,
                "evidence_layer": "user_observation",
                "runtime_eligible": False,
            }
            _atomic_write_json(observation_path, observation)
            ref = {
                **self._ref("user_observation", selected_id, observation_path),
                "kind": kind_name,
                "summary": summary_text,
                "created_by": actor_name,
            }
            self._replace_entity_ref(run.setdefault("user_observations", []), ref)
            self._append_event(
                run_dir,
                run,
                {"event": "user_observation_appended", "actor": actor_name, "observation_ref": ref},
            )
            self._save_run(run_dir, run)
            return {
                **observation,
                "artifact_path": str(observation_path),
                "run_artifact_path": str(self._run_path(run_dir)),
            }

    def append_claim(
        self,
        run_id: str,
        *,
        scope: str,
        statement: str,
        status: str,
        created_by: str,
        evidence_refs: Sequence[Any] | None = None,
        assumptions: Sequence[Any] | None = None,
        conflicts: Sequence[Any] | None = None,
        binding: Mapping[str, Any] | None = None,
        step_id: str = "",
        claim_id: str = "",
    ) -> dict[str, Any]:
        claim_status = str(status or "").strip()
        actor = str(created_by or "").strip()
        if claim_status not in CLAIM_STATUSES:
            raise ValueError(f"unsupported claim status: {claim_status}")
        if actor not in CLAIM_ACTORS:
            raise ValueError(f"created_by must be one of {sorted(CLAIM_ACTORS)}")
        if actor == "ai" and claim_status == "observed":
            raise ValueError("AI-created claims cannot be marked observed")
        evidence = _normalize_refs(evidence_refs, field="evidence_refs")
        if claim_status == "observed" and not evidence:
            raise ValueError("observed claims require at least one evidence_ref")
        statement_text = str(statement or "").strip()
        if not statement_text:
            raise ValueError("claim.statement is required")
        scope_name = _safe_id(scope, field="scope")
        selected_claim_id = _safe_id(claim_id, field="claim_id") if claim_id else _new_id("claim")
        run_dir = self._run_dir(run_id)
        with _RunLock(run_dir / ".ledger.lock"):
            run = self._load_run(run_dir)
            claim_path = self._entity_path(run_dir, "claim", selected_claim_id)
            if claim_path.exists():
                raise LedgerConflict(f"claim already exists: {selected_claim_id}")
            selected_step_id = _safe_id(step_id, field="step_id") if step_id else ""
            claim: dict[str, Any] = {
                "schema_version": CLAIM_SCHEMA_VERSION,
                "claim_id": selected_claim_id,
                "run_id": run["run_id"],
                "step_id": selected_step_id,
                "scope": scope_name,
                "statement": statement_text,
                "status": claim_status,
                "created_by": actor,
                "created_at": _utc_now(),
                "evidence_refs": evidence,
                "assumptions": _as_list(assumptions, field="assumptions"),
                "conflicts": _as_list(conflicts, field="conflicts"),
                "binding": _as_mapping(binding, field="binding"),
            }
            _atomic_write_json(claim_path, claim)
            claim_ref = {
                **self._ref("claim", selected_claim_id, claim_path),
                "scope": scope_name,
                "status": claim_status,
                "statement": statement_text,
                "created_by": actor,
            }
            run.setdefault("claims", []).append(claim_ref)
            if selected_step_id:
                step_path = self._entity_path(run_dir, "step", selected_step_id)
                step = _read_json(step_path, label="analysis step")
                step.setdefault("claim_refs", []).append(claim_ref)
                _atomic_write_json(step_path, step)
            self._append_event(
                run_dir,
                run,
                {"event": "claim_appended", "actor": actor, "claim_ref": claim_ref},
            )
            self._save_run(run_dir, run)
            return {**claim, "artifact_path": str(claim_path), "run_artifact_path": str(self._run_path(run_dir))}


__all__ = [
    "AnalysisLedger",
    "CLAIM_ACTORS",
    "CLAIM_SCHEMA_VERSION",
    "CLAIM_STATUSES",
    "EXPERIMENT_METHODS",
    "EXPERIMENT_SCHEMA_VERSION",
    "EXPERIMENT_STATUSES",
    "HYPOTHESIS_ACTORS",
    "HYPOTHESIS_CONFIDENCE_BANDS",
    "HYPOTHESIS_SCHEMA_VERSION",
    "HYPOTHESIS_STATUSES",
    "LedgerConflict",
    "LedgerError",
    "LedgerNotFound",
    "RUN_SCHEMA_VERSION",
    "RUN_STATUSES",
    "STEP_SCHEMA_VERSION",
    "STEP_STATUSES",
    "USER_OBSERVATION_KINDS",
    "USER_OBSERVATION_SCHEMA_VERSION",
]
