# -*- coding: utf-8 -*-
"""Unit tests for plugins.analysis.rule_engine.RuleEngine.

Covers:
- YAML rule loading (valid / invalid / missing file)
- Signal rules: reaches value, max/min comparison, value changes, count
- Log rules: no error, no warning, runnables_loaded, connections, version contains
- File rules: file exists, file size
- Signal not found → skip
- pass / fail status correctness
"""

import os
import textwrap

import pytest
import yaml

from core.models import LogEntry, LogSummary, RuleResult, SignalData
from plugins.analysis.rule_engine import RuleEngine


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _write_rules(tmp_path, rules_yaml: str) -> str:
    """Write a rules YAML string to a temp file and return the path."""
    path = str(tmp_path / "rules.yaml")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(rules_yaml)
    return path


def _write_file(tmp_path, name: str, size: int = 0) -> str:
    """Create a dummy file with *size* bytes and return its path."""
    path = str(tmp_path / name)
    with open(path, "wb") as fh:
        fh.write(b"\x00" * size)
    return path


def _make_engine(tmp_path, rules_yaml: str) -> RuleEngine:
    """Load a RuleEngine from a YAML string."""
    path = _write_rules(tmp_path, rules_yaml)
    engine = RuleEngine()
    engine.load_rules(path)
    return engine


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------

@pytest.fixture
def engine():
    return RuleEngine()


@pytest.fixture
def signals():
    return {
        "FCTA_State": SignalData(
            name="FCTA_State",
            timestamps=[0.0, 0.1, 0.2, 0.3],
            values=[0.0, 0.5, 1.0, 1.0],
            unit="",
        ),
        "TGU_Distance": SignalData(
            name="TGU_Distance",
            timestamps=list(range(10)),
            values=[10.0, 20.0, 50.0, 100.0, 200.0, 300.0, 400.0, 150.0, 50.0, 10.0],
            unit="m",
        ),
        "Constant_Sig": SignalData(
            name="Constant_Sig",
            timestamps=[0.0, 1.0, 2.0],
            values=[42.0, 42.0, 42.0],
        ),
        "Sparse_Sig": SignalData(
            name="Sparse_Sig",
            timestamps=[0.0, 1.0],
            values=[1.0, 2.0],
        ),
    }


@pytest.fixture
def log_clean():
    return LogSummary(
        version="1.18.0 Roberta",
        runnables_loaded=42,
        connections=12,
        errors=[],
        warnings=[],
        duration_sec=5.5,
    )


@pytest.fixture
def log_with_errors():
    return LogSummary(
        version="1.17.0 Alpha",
        runnables_loaded=20,
        connections=5,
        errors=[
            LogEntry(timestamp="10:00:00.000", level="error", message="Timeout reached"),
            LogEntry(timestamp="10:00:01.000", level="error", message="Connection lost"),
        ],
        warnings=[
            LogEntry(timestamp="10:00:00.500", level="warning", message="Low signal"),
        ],
        duration_sec=3.2,
    )


# ------------------------------------------------------------------
# YAML loading tests
# ------------------------------------------------------------------

class TestLoadRules:
    def test_load_valid_rules(self, engine, tmp_path):
        path = _write_rules(tmp_path, textwrap.dedent("""\
            rules:
              - name: "test_rule"
                source: "signal"
                signal: "X"
                condition: "value reaches 1"
                severity: "P0"
        """))
        engine.load_rules(path)
        assert len(engine.rules) == 1
        assert engine.rules[0]["name"] == "test_rule"

    def test_load_multiple_rules(self, engine, tmp_path):
        path = _write_rules(tmp_path, textwrap.dedent("""\
            rules:
              - name: "r1"
                source: "signal"
                signal: "A"
                condition: "value reaches 1"
                severity: "P0"
              - name: "r2"
                source: "log"
                condition: "no error entries in log"
                severity: "P1"
              - name: "r3"
                source: "file"
                condition: "output_mf4 file exists"
                severity: "P2"
        """))
        engine.load_rules(path)
        assert len(engine.rules) == 3

    def test_load_missing_file(self, engine):
        with pytest.raises(FileNotFoundError):
            engine.load_rules("/nonexistent/path/rules.yaml")

    def test_load_invalid_yaml_no_rules_key(self, engine, tmp_path):
        path = str(tmp_path / "bad.yaml")
        with open(path, "w") as fh:
            fh.write('{"not_rules": []}')
        with pytest.raises(ValueError):
            engine.load_rules(path)

    def test_load_empty_yaml(self, engine, tmp_path):
        path = str(tmp_path / "empty.yaml")
        with open(path, "w") as fh:
            fh.write("")
        with pytest.raises(ValueError):
            engine.load_rules(path)


# ------------------------------------------------------------------
# Signal rule tests
# ------------------------------------------------------------------

class TestSignalRules:

    def test_value_reaches_pass(self, tmp_path, signals):
        engine = _make_engine(tmp_path, textwrap.dedent("""\
            rules:
              - name: "fcta_activates"
                source: "signal"
                signal: "FCTA_State"
                condition: "value reaches 1"
                severity: "P0"
        """))
        results = engine.check(signals, LogSummary())
        assert len(results) == 1
        assert results[0].status == "pass"
        assert results[0].name == "fcta_activates"

    def test_value_reaches_fail(self, tmp_path, signals):
        engine = _make_engine(tmp_path, textwrap.dedent("""\
            rules:
              - name: "too_high"
                source: "signal"
                signal: "FCTA_State"
                condition: "value reaches 99"
                severity: "P1"
        """))
        results = engine.check(signals, LogSummary())
        assert results[0].status == "fail"

    def test_max_value_lt_pass(self, tmp_path, signals):
        engine = _make_engine(tmp_path, textwrap.dedent("""\
            rules:
              - name: "distance_reasonable"
                source: "signal"
                signal: "TGU_Distance"
                condition: "max value < 500"
                severity: "P1"
        """))
        results = engine.check(signals, LogSummary())
        assert results[0].status == "pass"
        assert results[0].severity == "P1"

    def test_max_value_lt_fail(self, tmp_path, signals):
        engine = _make_engine(tmp_path, textwrap.dedent("""\
            rules:
              - name: "distance_tight"
                source: "signal"
                signal: "TGU_Distance"
                condition: "max value < 350"
                severity: "P1"
        """))
        results = engine.check(signals, LogSummary())
        assert results[0].status == "fail"

    def test_max_value_gt_pass(self, tmp_path, signals):
        engine = _make_engine(tmp_path, textwrap.dedent("""\
            rules:
              - name: "max_gt"
                source: "signal"
                signal: "TGU_Distance"
                condition: "max value > 100"
                severity: "P2"
        """))
        results = engine.check(signals, LogSummary())
        assert results[0].status == "pass"

    def test_min_value_lt_pass(self, tmp_path, signals):
        engine = _make_engine(tmp_path, textwrap.dedent("""\
            rules:
              - name: "min_lt"
                source: "signal"
                signal: "TGU_Distance"
                condition: "min value < 50"
                severity: "P2"
        """))
        results = engine.check(signals, LogSummary())
        assert results[0].status == "pass"

    def test_min_value_gt_fail(self, tmp_path, signals):
        engine = _make_engine(tmp_path, textwrap.dedent("""\
            rules:
              - name: "min_gt_fail"
                source: "signal"
                signal: "FCTA_State"
                condition: "min value > 5"
                severity: "P2"
        """))
        results = engine.check(signals, LogSummary())
        assert results[0].status == "fail"

    def test_value_changes_pass(self, tmp_path, signals):
        engine = _make_engine(tmp_path, textwrap.dedent("""\
            rules:
              - name: "fcta_changes"
                source: "signal"
                signal: "FCTA_State"
                condition: "value changes"
                severity: "P1"
        """))
        results = engine.check(signals, LogSummary())
        assert results[0].status == "pass"

    def test_value_changes_fail_constant(self, tmp_path, signals):
        engine = _make_engine(tmp_path, textwrap.dedent("""\
            rules:
              - name: "const_changes"
                source: "signal"
                signal: "Constant_Sig"
                condition: "value changes"
                severity: "P2"
        """))
        results = engine.check(signals, LogSummary())
        assert results[0].status == "fail"

    def test_count_gt_pass(self, tmp_path, signals):
        engine = _make_engine(tmp_path, textwrap.dedent("""\
            rules:
              - name: "sparse_count"
                source: "signal"
                signal: "Sparse_Sig"
                condition: "count > 1"
                severity: "P2"
        """))
        results = engine.check(signals, LogSummary())
        assert results[0].status == "pass"

    def test_count_gt_fail(self, tmp_path, signals):
        engine = _make_engine(tmp_path, textwrap.dedent("""\
            rules:
              - name: "sparse_count_fail"
                source: "signal"
                signal: "Sparse_Sig"
                condition: "count > 5"
                severity: "P2"
        """))
        results = engine.check(signals, LogSummary())
        assert results[0].status == "fail"

    def test_signal_not_found_skip(self, tmp_path, signals):
        engine = _make_engine(tmp_path, textwrap.dedent("""\
            rules:
              - name: "missing_signal"
                source: "signal"
                signal: "DoesNotExist"
                condition: "value reaches 1"
                severity: "P0"
        """))
        results = engine.check(signals, LogSummary())
        assert results[0].status == "skip"


# ------------------------------------------------------------------
# Log rule tests
# ------------------------------------------------------------------

class TestLogRules:

    def test_no_error_pass(self, tmp_path, log_clean):
        engine = _make_engine(tmp_path, textwrap.dedent("""\
            rules:
              - name: "no_runtime_error"
                source: "log"
                condition: "no error entries in log"
                severity: "P0"
        """))
        results = engine.check({}, log_clean)
        assert results[0].status == "pass"

    def test_no_error_fail(self, tmp_path, log_with_errors):
        engine = _make_engine(tmp_path, textwrap.dedent("""\
            rules:
              - name: "no_runtime_error"
                source: "log"
                condition: "no error entries in log"
                severity: "P0"
        """))
        results = engine.check({}, log_with_errors)
        assert results[0].status == "fail"
        assert "2" in results[0].message

    def test_no_warning_pass(self, tmp_path, log_clean):
        engine = _make_engine(tmp_path, textwrap.dedent("""\
            rules:
              - name: "no_warnings"
                source: "log"
                condition: "no warning entries in log"
                severity: "P1"
        """))
        results = engine.check({}, log_clean)
        assert results[0].status == "pass"

    def test_no_warning_fail(self, tmp_path, log_with_errors):
        engine = _make_engine(tmp_path, textwrap.dedent("""\
            rules:
              - name: "no_warnings"
                source: "log"
                condition: "no warning entries in log"
                severity: "P1"
        """))
        results = engine.check({}, log_with_errors)
        assert results[0].status == "fail"

    def test_runnables_loaded_pass(self, tmp_path, log_clean):
        engine = _make_engine(tmp_path, textwrap.dedent("""\
            rules:
              - name: "runnables_loaded"
                source: "log"
                condition: "runnables_loaded >= 30"
                severity: "P1"
        """))
        results = engine.check({}, log_clean)
        assert results[0].status == "pass"

    def test_runnables_loaded_fail(self, tmp_path, log_with_errors):
        engine = _make_engine(tmp_path, textwrap.dedent("""\
            rules:
              - name: "runnables_loaded"
                source: "log"
                condition: "runnables_loaded >= 30"
                severity: "P1"
        """))
        results = engine.check({}, log_with_errors)
        assert results[0].status == "fail"

    def test_connections_pass(self, tmp_path, log_clean):
        engine = _make_engine(tmp_path, textwrap.dedent("""\
            rules:
              - name: "connections_check"
                source: "log"
                condition: "connections >= 10"
                severity: "P2"
        """))
        results = engine.check({}, log_clean)
        assert results[0].status == "pass"

    def test_connections_fail(self, tmp_path, log_with_errors):
        engine = _make_engine(tmp_path, textwrap.dedent("""\
            rules:
              - name: "connections_check"
                source: "log"
                condition: "connections >= 10"
                severity: "P2"
        """))
        results = engine.check({}, log_with_errors)
        assert results[0].status == "fail"

    def test_version_contains_pass(self, tmp_path, log_clean):
        engine = _make_engine(tmp_path, textwrap.dedent("""\
            rules:
              - name: "version_ok"
                source: "log"
                condition: "version contains Roberta"
                severity: "P2"
        """))
        results = engine.check({}, log_clean)
        assert results[0].status == "pass"

    def test_version_contains_fail(self, tmp_path, log_clean):
        engine = _make_engine(tmp_path, textwrap.dedent("""\
            rules:
              - name: "version_wrong"
                source: "log"
                condition: "version contains Zeus"
                severity: "P2"
        """))
        results = engine.check({}, log_clean)
        assert results[0].status == "fail"


# ------------------------------------------------------------------
# File rule tests
# ------------------------------------------------------------------

class TestFileRules:

    def test_output_mf4_exists_pass(self, tmp_path):
        mf4_path = _write_file(tmp_path, "output.mf4", size=5000)
        engine = _make_engine(tmp_path, textwrap.dedent(f"""\
            rules:
              - name: "output_mf4_generated"
                source: "file"
                condition: "output_mf4 file exists"
                severity: "P0"
        """))
        results = engine.check({}, LogSummary(), sim_context={"output_mf4": mf4_path})
        assert results[0].status == "pass"

    def test_output_mf4_exists_fail(self, tmp_path):
        engine = _make_engine(tmp_path, textwrap.dedent("""\
            rules:
              - name: "output_mf4_generated"
                source: "file"
                condition: "output_mf4 file exists"
                severity: "P0"
        """))
        results = engine.check({}, LogSummary(), sim_context={"output_mf4": "/no/such/file.mf4"})
        assert results[0].status == "fail"

    def test_file_exists_size_pass(self, tmp_path):
        mf4_path = _write_file(tmp_path, "big.mf4", size=5000)
        engine = _make_engine(tmp_path, textwrap.dedent("""\
            rules:
              - name: "output_mf4_generated"
                source: "file"
                condition: "file exists and size > 1000"
                severity: "P0"
        """))
        results = engine.check({}, LogSummary(), sim_context={"output_mf4": mf4_path})
        assert results[0].status == "pass"

    def test_file_exists_size_fail(self, tmp_path):
        mf4_path = _write_file(tmp_path, "tiny.mf4", size=100)
        engine = _make_engine(tmp_path, textwrap.dedent("""\
            rules:
              - name: "output_mf4_generated"
                source: "file"
                condition: "file exists and size > 1000"
                severity: "P0"
        """))
        results = engine.check({}, LogSummary(), sim_context={"output_mf4": mf4_path})
        assert results[0].status == "fail"

    def test_file_exists_not_found(self, tmp_path):
        engine = _make_engine(tmp_path, textwrap.dedent("""\
            rules:
              - name: "output_mf4_generated"
                source: "file"
                condition: "file exists and size > 1000"
                severity: "P0"
        """))
        results = engine.check({}, LogSummary(), sim_context={"output_mf4": "/no/such.mf4"})
        assert results[0].status == "fail"

    def test_log_file_exists_pass(self, tmp_path):
        log_path = _write_file(tmp_path, "CRlog.log", size=2048)
        engine = _make_engine(tmp_path, textwrap.dedent("""\
            rules:
              - name: "log_present"
                source: "file"
                condition: "log file exists"
                severity: "P1"
        """))
        results = engine.check({}, LogSummary(), sim_context={"log_file": log_path})
        assert results[0].status == "pass"

    def test_log_file_exists_fail(self, tmp_path):
        engine = _make_engine(tmp_path, textwrap.dedent("""\
            rules:
              - name: "log_present"
                source: "file"
                condition: "log file exists"
                severity: "P1"
        """))
        results = engine.check({}, LogSummary(), sim_context={"log_file": "/no/log.log"})
        assert results[0].status == "fail"

    def test_file_rule_no_context_skip(self, tmp_path):
        engine = _make_engine(tmp_path, textwrap.dedent("""\
            rules:
              - name: "no_context"
                source: "file"
                condition: "output_mf4 file exists"
                severity: "P0"
        """))
        results = engine.check({}, LogSummary(), sim_context={})
        assert results[0].status == "skip"


# ------------------------------------------------------------------
# Integration — full check() with mixed rules
# ------------------------------------------------------------------

class TestMixedCheck:

    def test_mixed_rules(self, tmp_path, signals, log_clean):
        rules_yaml = textwrap.dedent("""\
            rules:
              - name: "fcta_activates"
                source: "signal"
                signal: "FCTA_State"
                condition: "value reaches 1"
                severity: "P0"
              - name: "no_runtime_error"
                source: "log"
                condition: "no error entries in log"
                severity: "P0"
              - name: "runnables_loaded"
                source: "log"
                condition: "runnables_loaded >= 30"
                severity: "P1"
              - name: "missing_sig"
                source: "signal"
                signal: "Ghost"
                condition: "value reaches 1"
                severity: "P2"
        """)
        engine = _make_engine(tmp_path, rules_yaml)
        results = engine.check(signals, log_clean)

        assert len(results) == 4
        assert results[0].status == "pass"   # fcta_activates
        assert results[1].status == "pass"   # no_runtime_error
        assert results[2].status == "pass"   # runnables_loaded
        assert results[3].status == "skip"   # missing_sig

    def test_empty_rules(self, tmp_path, signals, log_clean):
        path = _write_rules(tmp_path, "rules: []")
        engine = RuleEngine()
        engine.load_rules(path)
        results = engine.check(signals, log_clean)
        assert results == []

    def test_unknown_source_skip(self, tmp_path, signals, log_clean):
        engine = _make_engine(tmp_path, textwrap.dedent("""\
            rules:
              - name: "weird"
                source: "database"
                condition: "SELECT * FROM rules"
                severity: "P2"
        """))
        results = engine.check(signals, log_clean)
        assert len(results) == 1
        assert results[0].status == "skip"
