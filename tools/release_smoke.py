"""Fast, side-effect-free checks used by the M0-M4 release contract.

The full pytest suite remains the broad regression test.  These checks are
deliberately small and process-safe so ``release_gate`` can be invoked from
CI or from a pytest run without recursively launching another pytest tree.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _m0() -> dict[str, Any]:
    # M0-M4 exercise the archived local contract, not the new Gen6 release scope.
    path = ROOT / "docs" / "archive" / "2026-09-17" / "technical" / "release_acceptance.v1.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    entries = payload.get("entries", [])
    ids = [str(item.get("id", "")) for item in entries]
    required = [item for item in entries if item.get("required_for_release")]
    assert payload.get("schema_version") == "release-acceptance.v1"
    assert len(ids) == len(set(ids))
    assert required and all(item.get("status") == "accepted" for item in required)
    for item in required:
        for evidence in item.get("evidence", []):
            assert (ROOT / str(evidence["path"])).is_file(), evidence["path"]
    return {"phase": "M0", "required_entries": len(required), "status": "passed"}


def _m1() -> dict[str, Any]:
    from core.diagnosis_bundle import CodeLocation, DiagnosisBundle, Evidence
    from core.knowledge_guard import runtime_knowledge_decision

    decision = runtime_knowledge_decision(
        {"identity": {"variant_id": "smoke/variant", "freshness": {"available": True}}},
        "conditions:RCTA",
    )
    assert not decision.allowed and "manifest_missing" in decision.reasons
    bundle = DiagnosisBundle.for_case(None, "smoke", "smoke/variant", "question")
    bundle.add_evidence(Evidence(evidence_id="e1", source="recorded_raw", description="observed"))
    bundle.code_localization.append(CodeLocation(file_path="logic.c", line_start=1))
    assert bundle.upgrade_to_confirmed() is False
    return {"phase": "M1", "freshness": "fail_closed", "confirmation_gate": "required", "status": "passed"}


def _m2() -> dict[str, Any]:
    from ai.modules.execution_binding import ExecutionBindingModule
    from ai.modules.sim_verify import SimVerifyModule
    from engines.analysis_ledger import AnalysisLedger
    from engines.arbe.execution_binding import build_execution_binding, verify_execution_binding
    from engines.arbe.remote_replay import build_public_capture_command

    identity = {
        "data_fingerprint": "data",
        "source_context_id": "source",
        "binary_fingerprint": "binary",
        "config_fingerprint": "config",
        "session_id": "session",
    }
    plan = {"remote_bag_path": "/data/case.bag", "duration_sec": 1}
    binding = build_execution_binding(
        plan=plan, identity=identity, approval_id="approval", approved=True, run_id="attempt-1"
    )
    assert verify_execution_binding(binding, current_identity=identity, approved=True, plan=plan)["status"] == "verified"
    module_binding = ExecutionBindingModule().safe_run(
        plan=plan,
        identity=identity,
        approval_id="approval-smoke",
        approved=True,
        run_id="attempt-smoke",
    )
    assert module_binding.ok and module_binding.data["schema_version"] == "arbe-execution-binding.v1"
    changed = {**identity, "binary_fingerprint": "other"}
    assert verify_execution_binding(binding, current_identity=changed, approved=True, plan=plan)["status"] == "blocked"
    capture = build_public_capture_command(
        remote_bag_path="/data/case.bag",
        remote_capture_base="/tmp/capture",
        start_sec=0,
        duration_sec=1,
        input_topics=["/wf/corner_radar/lgu_data_1"],
        output_topics=["/corner_radar/warning_status_with_frame"],
        attempt_id="attempt-1",
    )
    assert "trap cleanup INT TERM EXIT" in capture["command"]
    blocked = SimVerifyModule().safe_run(
        mode="remote_public",
        server_host="server",
        remote_bag_path="/data/case.bag",
        remote_capture_base="/tmp/capture",
        input_topics=["/wf/corner_radar/lgu_data_1"],
        output_topics=["/corner_radar/warning_status_with_frame"],
        execute=True,
        approved=True,
    )
    assert blocked.data.get("status") == "blocked"
    with tempfile.TemporaryDirectory(prefix="radar-ledger-smoke-") as directory:
        ledger = AnalysisLedger(Path(directory) / "ledger")
        ledger.create_run(
            run_id="smoke-run",
            owner="release-smoke",
            goal={"question": "smoke"},
            binding={"variant_id": "smoke/variant", "data_fingerprint": "data"},
            artifact_refs=[],
        )
        ledger.begin_step("smoke-run", step_id="step-1", stage="smoke")
        ledger.complete_step("smoke-run", "step-1", status="completed", user_visible_summary="smoke")
        assert ledger.read_run("smoke-run")["summary"]["step_count"] == 1
    return {
        "phase": "M2",
        "execution_binding": "verified_and_blocked_on_drift",
        "ledger": "create_begin_complete_read",
        "status": "passed",
    }


def _m3() -> dict[str, Any]:
    from tools.doctor import run_doctor

    report = run_doctor(project_root=ROOT, check_catalog=True)
    assert report["status"] == "ready", report.get("failures")
    return {
        "phase": "M3",
        "doctor": report["status"],
        "capability_count": report.get("capability_catalog", {}).get("capability_count"),
        "status": "passed",
    }


def _m4() -> dict[str, Any]:
    from config import load_config
    from ai.capability.project_context import resolve_project_context

    config = load_config()
    with tempfile.TemporaryDirectory(prefix="radar-release-smoke-") as directory:
        first = resolve_project_context(config, directory, variant_id="gen6/byd_sc6h")
        second = resolve_project_context(config, directory, variant_id="gen6/gwm_b26")
        assert first.namespace() != second.namespace()
        assert first.memory_dir != second.memory_dir
    return {"phase": "M4", "variant_namespaces": [first.namespace(), second.namespace()], "status": "passed"}


PHASES = {"M0": _m0, "M1": _m1, "M2": _m2, "M3": _m3, "M4": _m4}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", required=True, choices=sorted(PHASES))
    args = parser.parse_args(argv)
    try:
        result = PHASES[args.phase]()
    except Exception as exc:  # pragma: no cover - CLI boundary
        print(json.dumps({"phase": args.phase, "status": "failed", "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
