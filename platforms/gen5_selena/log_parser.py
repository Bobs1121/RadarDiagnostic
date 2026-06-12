# -*- coding: utf-8 -*-
"""Gen5 Selena log parser.

Parses ``CRlog.log`` files produced by the Selena simulation platform
and extracts key information such as version, runnable count, connection
count, errors, and warnings.

Usage::

    from platforms.gen5_selena.log_parser import Gen5LogParser

    parser = Gen5LogParser()
    summary = parser.parse("path/to/CRlog.log")
    print(summary.version)       # e.g. "1.18.0 Roberta"
    print(summary.errors)        # list of LogEntry for error lines
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from core.models import LogEntry, LogSummary

# ---------------------------------------------------------------------------
# Compiled regular expressions
# ---------------------------------------------------------------------------

# Matches a log line: [HH:MM:SS.mmm] (thread PID) [level]: message
LOG_PATTERN = re.compile(
    r"\[(?P<timestamp>\d{2}:\d{2}:\d{2}\.\d{3})\]\s*"
    r"\(thread\s+\d+\)\s*"
    r"\[(?P<level>\w+)\]:\s*(?P<message>.*)"
)

# Matches version strings like "Selena 1.18.0 Roberta"
VERSION_PATTERN = re.compile(
    r"Selena\s+(?P<version>[\d.]+)\s*(?P<codename>\w+)"
)

# Matches runnable loading: "Loading runnable: Xxx" or "loaded runnable: Xxx"
RUNNABLE_PATTERN = re.compile(
    r"(?:loading|loaded)\s+runnable[:\s]+(?P<name>\w+)", re.IGNORECASE
)

# Matches connection counts like "3 connections" or "1 connection"
CONNECTION_PATTERN = re.compile(
    r"(?P<count>\d+)\s+connection", re.IGNORECASE
)


def _parse_timestamp(ts_str: str) -> datetime:
    """Parse a ``HH:MM:SS.mmm`` timestamp string into a ``datetime``.

    Args:
        ts_str: Timestamp in ``HH:MM:SS.mmm`` format.

    Returns:
        A ``datetime`` object with a default date (1900-01-01) and the
        parsed time components.
    """
    return datetime.strptime(ts_str, "%H:%M:%S.%f")


class Gen5LogParser:
    """Parser for Selena ``CRlog.log`` files.

    Extracts version info, runnable/connection counts, and classifies
    log entries by severity (error, warning, info).

    Attributes:
        config: Optional configuration dictionary (reserved for future use).
    """

    def __init__(self, config: Optional[dict] = None) -> None:
        """Initialise the parser.

        Args:
            config: Optional configuration dict. Currently unused but
                    reserved for future tuning (e.g. custom patterns).
        """
        self.config = config or {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def parse(self, log_file: str) -> LogSummary:
        """Parse a Selena log file and return a structured summary.

        Reads the file line by line (memory-efficient for 10 MB+ logs)
        and extracts:

        * **Version** — from ``Selena X.Y.Z Codename`` strings.
        * **Runnables** — unique count of runnables loaded.
        * **Connections** — connection count from the log.
        * **Errors** — log lines with level ``error``.
        * **Warnings** — log lines with level ``warning`` or ``warn``.
        * **Duration** — seconds between the first and last log entries.

        Args:
            log_file: Path to the log file (e.g. ``CRlog.log``).

        Returns:
            A ``LogSummary`` populated with extracted data.

        Raises:
            FileNotFoundError: If the log file does not exist.
            PermissionError:   If the log file cannot be read.
        """
        path = Path(log_file)

        if not path.exists():
            raise FileNotFoundError(f"Log file not found: {log_file}")

        summary = LogSummary(raw_path=str(path))

        first_ts: Optional[datetime] = None
        last_ts: Optional[datetime] = None
        runnables: set[str] = set()

        # Read line-by-line for memory efficiency on large files
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.rstrip("\n\r")

                # --- Match log entry lines ---
                log_match = LOG_PATTERN.search(line)
                if log_match:
                    timestamp_str = log_match.group("timestamp")
                    level = log_match.group("level").lower()
                    message = log_match.group("message")

                    ts = _parse_timestamp(timestamp_str)

                    if first_ts is None:
                        first_ts = ts
                    last_ts = ts

                    entry = LogEntry(
                        timestamp=timestamp_str,
                        level=level,
                        message=message,
                    )

                    if level == "error":
                        summary.errors.append(entry)
                    elif level in ("warning", "warn"):
                        summary.warnings.append(entry)
                    # info level is skipped (not stored)

                # --- Extract version ---
                ver_match = VERSION_PATTERN.search(line)
                if ver_match:
                    ver = ver_match.group("version")
                    codename = ver_match.group("codename")
                    summary.version = f"{ver} {codename}"

                # --- Extract runnable names ---
                run_match = RUNNABLE_PATTERN.search(line)
                if run_match:
                    runnables.add(run_match.group("name"))

                # --- Extract connection count ---
                conn_match = CONNECTION_PATTERN.search(line)
                if conn_match:
                    summary.connections = int(conn_match.group("count"))

        # --- Compute duration ---
        if first_ts is not None and last_ts is not None:
            delta = last_ts - first_ts
            summary.duration_sec = delta.total_seconds()

        # --- Set runnable count ---
        summary.runnables_loaded = len(runnables)

        return summary
