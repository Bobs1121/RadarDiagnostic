"""Contract tests for the read-only operator capability catalog."""
from __future__ import annotations

import json

from cli import _run_capabilities_subcommand


def test_capabilities_command_emits_pi_registry_catalog(capsys):
    rc = _run_capabilities_subcommand(["capabilities", "--json"])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    names = {item["name"] for item in payload}
    assert "diagnosis-report" in names
    assert "condition-trace" in names
    assert "pi" not in names
    assert all(item["expose_to_pi"] for item in payload if item["name"] != "pi")


def test_capabilities_command_can_filter_registry_kind(capsys):
    rc = _run_capabilities_subcommand(["capabilities", "--kind", "tool"])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload
    assert {item["kind"] for item in payload} == {"tool"}
