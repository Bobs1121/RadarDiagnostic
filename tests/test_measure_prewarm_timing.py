# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path


def test_measure_prewarm_timing_writes_report(
    tmp_path: Path, monkeypatch
) -> None:
    import tools.measure_prewarm_timing as mpt

    docs_dir = tmp_path / "source_docs" / "gen6_gwm_b26"
    docs_dir.mkdir(parents=True, exist_ok=True)
    output_path = tmp_path / "report.json"
    calls: list[dict] = []

    monkeypatch.setattr(mpt, "load_config", lambda: {"paths": {}, "identity": {}})
    monkeypatch.setattr(mpt, "resolve_variant_id", lambda config, value: "gen6/gwm_b26")

    class _Codebase:
        root_path = tmp_path / "src"

    monkeypatch.setattr(
        mpt,
        "get_variant",
        lambda config, variant_id: (object(), _Codebase(), None),
    )
    monkeypatch.setattr(mpt, "resolve_source_docs_dir", lambda *args, **kwargs: docs_dir)

    def fake_run_prewarm(*, config, force):
        marker = docs_dir / "variable_chains.meta.json"
        calls.append(
            {
                "variant_id": config["identity"]["variant_id"],
                "source_code": config["paths"]["source_code"],
                "source_docs": config["paths"]["source_docs"],
                "force": force,
                "cache_hit_before": marker.exists(),
            }
        )
        if not marker.exists():
            marker.write_text("{}", encoding="utf-8")
        return {"force": force, "operations": {"variable_chains": {"meta_exists": True}}}

    monkeypatch.setattr(mpt, "_run_prewarm", fake_run_prewarm)

    exit_code = mpt.main(
        [
            "--variant",
            "gen6/gwm_b26",
            "--runs",
            "2",
            "--output",
            str(output_path),
        ]
    )

    assert exit_code == 0
    assert len(calls) == 2
    assert calls[0]["cache_hit_before"] is False
    assert calls[1]["cache_hit_before"] is True

    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert report["variant_id"] == "gen6/gwm_b26"
    assert report["runs_requested"] == 2
    assert report["cache_hit_runs"] == 1
    assert len(report["runs"]) == 2
    assert report["runs"][0]["cache_hit"] is False
    assert report["runs"][1]["cache_hit"] is True
    assert report["runs"][1]["summary"]["operations"]["variable_chains"]["meta_exists"]
