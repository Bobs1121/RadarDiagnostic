# -*- coding: utf-8 -*-
"""Rule engine for automated signal/log/file validation.

Loads rules from a YAML configuration file and evaluates each rule against
simulated signal data, log summaries, and filesystem artefacts.

Supported rule sources
---------------------
* ``signal`` -- checks properties of a :class:`SignalData` instance.
* ``log``    -- checks attributes of a :class:`LogSummary` instance.
* ``file``   -- checks file existence / size on disk.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

import yaml

from core.models import LogSummary, RuleResult, SignalData


class RuleEngine:
    """Evaluates YAML-defined rules against simulation artefacts.

    Each rule specifies a ``source`` type (``"signal"``, ``"log"``, ``"file"``),
    a ``condition`` string, and a ``severity`` level. The engine parses the
    condition using regular expressions and returns a list of :class:`RuleResult`
    objects after evaluation.

    Example YAML::

        rules:
          - name: "fcta_activates"
            source: "signal"
            signal: "FCTA_State"
            condition: "value reaches 1"
            severity: "P0"

    Attributes:
        rules: List of parsed rule dictionaries (populated by :meth:`load_rules`).
    """

    def __init__(self) -> None:
        self.rules: list[dict] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_rules(self, rules_file: str) -> None:
        """Load rules from a YAML configuration file.

        Args:
            rules_file: Path to the YAML file containing a ``rules`` list.

        Raises:
            FileNotFoundError: If the file does not exist.
            ValueError: If the YAML does not contain a ``rules`` key.
        """
        path = Path(rules_file)
        if not path.exists():
            raise FileNotFoundError(f"Rules file not found: {rules_file}")

        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)

        if not data or "rules" not in data:
            raise ValueError(f"Invalid rules file — expected 'rules' key: {rules_file}")

        self.rules = data["rules"]

    def check(
        self,
        signals: dict[str, SignalData],
        log_summary: LogSummary,
        sim_context: dict | None = None,
    ) -> list[RuleResult]:
        """Evaluate all loaded rules and return a list of results.

        Args:
            signals: Mapping of signal name to :class:`SignalData`.
            log_summary: Parsed log summary.
            sim_context: Optional dict with runtime paths, e.g.
                ``{"output_mf4": "...", "log_file": "..."}``.

        Returns:
            A list of :class:`RuleResult` — one per loaded rule.
        """
        sim_context = sim_context or {}
        results: list[RuleResult] = []

        for rule in self.rules:
            source = rule.get("source", "").lower()

            if source == "signal":
                result = self._check_signal_rule(rule, signals)
            elif source == "log":
                result = self._check_log_rule(rule, log_summary)
            elif source == "file":
                result = self._check_file_rule(rule, sim_context)
            else:
                result = RuleResult(
                    name=rule.get("name", "unknown"),
                    status="skip",
                    severity=rule.get("severity", "P2"),
                    message=f"Unsupported rule source: {source}",
                )

            results.append(result)

        return results

    # ------------------------------------------------------------------
    # Signal rules
    # ------------------------------------------------------------------

    def _check_signal_rule(
        self, rule: dict, signals: dict[str, SignalData]
    ) -> RuleResult:
        """Evaluate a single signal-based rule.

        Supported conditions:

        * ``value reaches X``      — at least one sample >= X
        * ``max value < X``        — peak below threshold
        * ``max value > X``        — peak above threshold
        * ``min value < X``        — trough below threshold
        * ``min value > X``        — trough above threshold
        * ``value changes``        — not all samples are identical
        * ``count > X``            — number of samples exceeds X

        Args:
            rule: Rule dictionary with ``name``, ``signal``, ``condition``,
                and ``severity`` keys.
            signals: Mapping of signal name to :class:`SignalData`.

        Returns:
            :class:`RuleResult` with ``status`` set to ``"pass"``, ``"fail"``,
            or ``"skip"`` (signal not found).
        """
        rule_name = rule.get("name", "unknown")
        signal_name = rule.get("signal", "")
        condition = rule.get("condition", "")
        severity = rule.get("severity", "P2")

        if signal_name not in signals:
            return RuleResult(
                name=rule_name,
                status="skip",
                severity=severity,
                message=f"Signal '{signal_name}' not found in data",
            )

        sig = signals[signal_name]
        values = sig.values

        # ----- condition parsing -----
        # value reaches X
        m = re.match(r"value\s+reaches\s+([\d.eE+\-]+)", condition)
        if m:
            target = float(m.group(1))
            passed = any(v >= target for v in values)
            return RuleResult(
                name=rule_name,
                status="pass" if passed else "fail",
                severity=severity,
                message=f"Signal {signal_name} reaches {target}" if passed
                else f"Signal {signal_name} does not reach {target}",
                details=f"max={max(values):.4f}  min={min(values):.4f}"
                if values else "",
            )

        # max/min value < or > X
        m = re.match(r"(max|min)\s+value\s+(<|>)\s+([\d.eE+\-]+)", condition)
        if m:
            agg = m.group(1)
            op = m.group(2)
            threshold = float(m.group(3))
            actual = max(values) if agg == "max" else min(values)
            passed = actual < threshold if op == "<" else actual > threshold
            return RuleResult(
                name=rule_name,
                status="pass" if passed else "fail",
                severity=severity,
                message=f"{agg.title()} value {op} {threshold}: {actual:.4f}" if passed
                else f"{agg.title()} value {op} {threshold}: got {actual:.4f}",
                details=f"{agg}={actual:.4f}",
            )

        # value changes
        if re.match(r"value\s+changes", condition):
            if not values:
                passed = False
            else:
                passed = len(set(values)) > 1
            return RuleResult(
                name=rule_name,
                status="pass" if passed else "fail",
                severity=severity,
                message=f"Signal {signal_name} changes" if passed
                else f"Signal {signal_name} is constant",
                details=f"unique={len(set(values))}  samples={len(values)}",
            )

        # count > X
        m = re.match(r"count\s+>\s+([\d.eE+\-]+)", condition)
        if m:
            threshold = float(m.group(1))
            passed = len(values) > threshold
            return RuleResult(
                name=rule_name,
                status="pass" if passed else "fail",
                severity=severity,
                message=f"Count > {threshold}: {len(values)}" if passed
                else f"Count > {threshold}: got {len(values)}",
                details=f"count={len(values)}",
            )

        # Fallback — condition not recognised
        return RuleResult(
            name=rule_name,
            status="skip",
            severity=severity,
            message=f"Unrecognised signal condition: {condition}",
        )

    # ------------------------------------------------------------------
    # Log rules
    # ------------------------------------------------------------------

    def _check_log_rule(
        self, rule: dict, log_summary: LogSummary
    ) -> RuleResult:
        """Evaluate a single log-based rule.

        Supported conditions:

        * ``no error entries in log``    — zero error entries
        * ``no warning entries in log``  — zero warning entries
        * ``runnables_loaded >= X``      — at least X runnables
        * ``connections >= X``           — at least X connections
        * ``version contains X``         — version string contains X

        Args:
            rule: Rule dictionary.
            log_summary: Parsed log summary.

        Returns:
            :class:`RuleResult`.
        """
        rule_name = rule.get("name", "unknown")
        condition = rule.get("condition", "")
        severity = rule.get("severity", "P2")

        # no error entries in log
        if re.match(r"no\s+error\s+entries\s+in\s+log", condition):
            passed = len(log_summary.errors) == 0
            return RuleResult(
                name=rule_name,
                status="pass" if passed else "fail",
                severity=severity,
                message="No errors in log" if passed
                else f"Found {len(log_summary.errors)} error(s) in log",
                details=f"errors={len(log_summary.errors)}",
            )

        # no warning entries in log
        if re.match(r"no\s+warning\s+entries\s+in\s+log", condition):
            passed = len(log_summary.warnings) == 0
            return RuleResult(
                name=rule_name,
                status="pass" if passed else "fail",
                severity=severity,
                message="No warnings in log" if passed
                else f"Found {len(log_summary.warnings)} warning(s) in log",
                details=f"warnings={len(log_summary.warnings)}",
            )

        # runnables_loaded >= X
        m = re.match(r"runnables_loaded\s+>=\s+([\d.eE+\-]+)", condition)
        if m:
            threshold = float(m.group(1))
            passed = log_summary.runnables_loaded >= threshold
            return RuleResult(
                name=rule_name,
                status="pass" if passed else "fail",
                severity=severity,
                message=f"runnables_loaded >= {threshold}: {log_summary.runnables_loaded}"
                if passed
                else f"runnables_loaded >= {threshold}: got {log_summary.runnables_loaded}",
                details=f"runnables_loaded={log_summary.runnables_loaded}",
            )

        # connections >= X
        m = re.match(r"connections\s+>=\s+([\d.eE+\-]+)", condition)
        if m:
            threshold = float(m.group(1))
            passed = log_summary.connections >= threshold
            return RuleResult(
                name=rule_name,
                status="pass" if passed else "fail",
                severity=severity,
                message=f"connections >= {threshold}: {log_summary.connections}"
                if passed
                else f"connections >= {threshold}: got {log_summary.connections}",
                details=f"connections={log_summary.connections}",
            )

        # version contains X
        m = re.match(r"version\s+contains\s+(.+)", condition)
        if m:
            substring = m.group(1).strip()
            passed = substring in log_summary.version
            return RuleResult(
                name=rule_name,
                status="pass" if passed else "fail",
                severity=severity,
                message=f"Version contains '{substring}'" if passed
                else f"Version does not contain '{substring}'",
                details=f"version='{log_summary.version}'",
            )

        # Fallback
        return RuleResult(
            name=rule_name,
            status="skip",
            severity=severity,
            message=f"Unrecognised log condition: {condition}",
        )

    # ------------------------------------------------------------------
    # File rules
    # ------------------------------------------------------------------

    def _check_file_rule(
        self, rule: dict, sim_context: dict | None
    ) -> RuleResult:
        """Evaluate a single file-based rule.

        Supported conditions:

        * ``output_mf4 file exists``                — checks ``sim_context["output_mf4"]``
        * ``file exists and size > X``              — same as above, plus size check
        * ``log file exists``                        — checks ``sim_context["log_file"]``

        Args:
            rule: Rule dictionary.
            sim_context: Runtime context dict with file paths.

        Returns:
            :class:`RuleResult`.
        """
        rule_name = rule.get("name", "unknown")
        condition = rule.get("condition", "")
        severity = rule.get("severity", "P2")
        sim_context = sim_context or {}

        # file exists and size > X
        m = re.match(r"file\s+exists\s+and\s+size\s+>\s+([\d.eE+\-]+)", condition)
        if m:
            threshold = float(m.group(1))
            # Try output_mf4 first, then output_file
            file_path = sim_context.get("output_mf4") or sim_context.get("output_file", "")
            if not file_path:
                return RuleResult(
                    name=rule_name,
                    status="skip",
                    severity=severity,
                    message="No output_mf4 path in sim_context",
                )
            exists = os.path.isfile(file_path)
            if not exists:
                return RuleResult(
                    name=rule_name,
                    status="fail",
                    severity=severity,
                    message=f"File not found: {file_path}",
                    details=f"path={file_path}",
                )
            size = os.path.getsize(file_path)
            passed = size > threshold
            return RuleResult(
                name=rule_name,
                status="pass" if passed else "fail",
                severity=severity,
                message=f"File size > {threshold}: {size}" if passed
                else f"File size > {threshold}: got {size}",
                details=f"path={file_path}  size={size}",
            )

        # output_mf4 file exists
        if re.match(r"output_mf4\s+file\s+exists", condition):
            file_path = sim_context.get("output_mf4", "")
            if not file_path:
                return RuleResult(
                    name=rule_name,
                    status="skip",
                    severity=severity,
                    message="No output_mf4 path in sim_context",
                )
            passed = os.path.isfile(file_path)
            return RuleResult(
                name=rule_name,
                status="pass" if passed else "fail",
                severity=severity,
                message=f"output_mf4 exists: {file_path}" if passed
                else f"output_mf4 not found: {file_path}",
                details=f"path={file_path}",
            )

        # log file exists
        if re.match(r"log\s+file\s+exists", condition):
            file_path = sim_context.get("log_file", "")
            if not file_path:
                return RuleResult(
                    name=rule_name,
                    status="skip",
                    severity=severity,
                    message="No log_file path in sim_context",
                )
            passed = os.path.isfile(file_path)
            return RuleResult(
                name=rule_name,
                status="pass" if passed else "fail",
                severity=severity,
                message=f"log file exists: {file_path}" if passed
                else f"log file not found: {file_path}",
                details=f"path={file_path}",
            )

        # Fallback
        return RuleResult(
            name=rule_name,
            status="skip",
            severity=severity,
            message=f"Unrecognised file condition: {condition}",
        )
