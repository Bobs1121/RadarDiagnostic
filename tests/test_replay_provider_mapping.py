from __future__ import annotations

from pathlib import Path

from ai.modules.sim_verify import SimVerifyModule
from engines.arbe.replay_provider import parse_warning_trace_csv


def test_warning_trace_keeps_generic_bits_without_current_mapping(tmp_path: Path):
    path = tmp_path / "trace.csv"
    path.write_text("event_sec,radar_id,frame_id,w1,w2\n1.0,2,10,1,0\n", encoding="utf-8")
    rows = parse_warning_trace_csv(path)
    assert rows[0].active_warnings() == ["w1"]
    assert rows[0].warning_mapping_source == "not_provided"


def test_warning_trace_uses_explicit_current_mapping(tmp_path: Path):
    path = tmp_path / "trace.csv"
    path.write_text("event_sec,radar_id,frame_id,w1,w2\n1.0,2,10,1,0\n", encoding="utf-8")
    rows = parse_warning_trace_csv(path, warning_names=["PROJECT_WARN_A", "PROJECT_WARN_B"])
    assert rows[0].active_warnings() == ["PROJECT_WARN_A"]
    assert rows[0].warning_mapping_source == "explicit_names"


def test_sim_verify_local_reads_case_runtime_warning_contract_and_writes_replay_artifact(tmp_path: Path):
    (tmp_path / "runtime_schema.json").write_text(
        '{"warning_contract":{"bits":{"1":"PROJECT_WARN_A"}}}',
        encoding="utf-8",
    )
    (tmp_path / "sample_algo_warning_trace.csv").write_text(
        "event_sec,radar_id,frame_id,w1\n1.0,2,10,1\n",
        encoding="utf-8",
    )
    output = tmp_path / "replay.json"
    result = SimVerifyModule().safe_run(
        mode="local", case_dir=str(tmp_path), output=str(output)
    )
    assert result.ok
    assert result.data["schema_version"] == "arbe-replay-result.v1"
    assert result.data["active_warnings"] == {"PROJECT_WARN_A": 1}
    assert output.is_file()
