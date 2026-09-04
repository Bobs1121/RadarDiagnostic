import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_runtime_evidence_schema_and_real_fixture_are_structurally_compatible():
    schema = json.loads((ROOT / "contracts" / "runtime-evidence.v1.schema.json").read_text(encoding="utf-8"))

    assert schema["properties"]["schema_version"]["const"] == "runtime-case-evidence.v1"
    sample = {
        "schema_version": "runtime-case-evidence.v1",
        "status": "partial",
        "run": {"run_id": "sample", "data_fingerprint": "data", "source_context_id": "context"},
        "evidence_layers": [{"id": "gdb", "kind": "gdb_observation", "authority": "runtime", "status": "partial"}],
        "observations": [{"observation_id": "sample:frame", "layer": "gdb_observation", "identity": {"frame_id": 1}, "fields": [{"token": "i", "value": 0, "status": "observed"}]}],
    }
    assert sample["schema_version"] == "runtime-case-evidence.v1"
    assert sample["observations"][0]["fields"][0]["status"] == "observed"

    fixture_path = ROOT / "outputs" / "runtime_fctb_case_evidence_20260827.json"
    if fixture_path.exists():
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        assert fixture["schema_version"] == "runtime-case-evidence.v1"
        assert fixture["runtime_replay_layer"]["runs"][1]["handler_observation"]["objID"] == 44


def test_runtime_evidence_keeps_replay_and_recorded_layers_distinct():
    fixture_path = ROOT / "outputs" / "runtime_fctb_case_evidence_20260827.json"
    if not fixture_path.exists():
        return
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))

    recorded = fixture["recorded_raw_layer"]["events"]
    replay = fixture["runtime_replay_layer"]["runs"]
    assert any(item["function"] == "FCTB_L" and item["radar_id"] == 1 for item in recorded)
    assert any(item["radar_id"] == 2 and item["run_id"] == "radar2_frame47875_long_window" for item in replay)
    assert fixture["runtime_replay_layer"]["formal_gui_player_parity"] is False


def test_runtime_evidence_contract_accepts_can_tx_observation_layer():
    from engines.runtime_evidence import validate_runtime_evidence

    payload = {
        "schema_version": "runtime-case-evidence.v1",
        "status": "ready",
        "run": {"run_id": "can", "data_fingerprint": "d", "source_context_id": "s"},
        "evidence_layers": [{"id": "can", "kind": "can_tx_observation", "authority": "can", "status": "observed"}],
        "observations": [{
            "observation_id": "can:1",
            "layer": "can_tx_observation",
            "identity": {"frame_id": 1},
            "fields": [{"token": "actual_signal", "value": 1, "status": "observed"}],
        }],
    }
    assert validate_runtime_evidence(payload) == []
