# -*- coding: utf-8 -*-
"""
Core data models for the radar-sim build pipeline.

Provides ``BuildOptions`` (input parameters for a build invocation)
and ``BuildResult`` (output / status returned by a builder).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class SimConfig:
    """Simulation configuration passed to a simulation engine.

    Attributes:
        config_file:  Path to the selena config text file (.txt).
        input_mf4:    Path to the input MF4 data file.
        output_dir:   Directory where output artefacts are written.
        runtime_xml:  Path to the runtime XML configuration.
        source:       Radar source identifier (e.g. ``"RadarFR"``).
        mounting_position: Mounting position code (e.g. ``"CFR"``).
        timeout_sec:  Maximum wall-clock seconds before the run is killed.
    """

    config_file: str
    input_mf4: str
    output_dir: str
    runtime_xml: str
    source: str = "RadarFR"
    mounting_position: str = "CFR"
    timeout_sec: int = 600


@dataclass
class SimResult:
    """Result returned after a simulation run.

    Attributes:
        id:           Short unique identifier (first 8 hex chars of a UUID).
        timestamp:    When the simulation started.
        config:       The ``SimConfig`` used for this run.
        status:       One of ``"completed"``, ``"failed"``, or ``"timed_out"``.
        exit_code:    Process exit code (``-1`` if the process was killed).
        duration_sec: Wall-clock seconds the simulation took.
        output_mf4:   Path to the output MF4 file produced by selena.
        log_file:     Path to the log file (e.g. ``CRlog.log``).
        mat_file:     Path to the optional ``.mat`` output file.
        signals:      Signal metrics extracted from the output.
        log_summary:  Parsed summary of the log file (set by a log analyser).
        rule_results: List of rule-check results (set by a rule engine).
        ai_analysis:  Optional AI-generated analysis text.
        report_path:  Path to a generated report file.
    """

    id: str
    timestamp: datetime
    config: SimConfig
    status: str  # "completed" | "failed" | "timed_out"
    exit_code: int = -1
    duration_sec: float = 0.0
    output_mf4: str = ""
    log_file: str = ""
    mat_file: Optional[str] = None
    signals: dict = field(default_factory=dict)
    log_summary: Optional[object] = None
    rule_results: list = field(default_factory=list)
    ai_analysis: Optional[str] = None
    report_path: Optional[str] = None


@dataclass
class BuildOptions:
    """Parameters passed to a build invocation.

    Attributes:
        build_config:  Path to the R2D2 build-config file (.config).
        build_mode:    CMake build mode (e.g. ``RelWithDebInfo``, ``Debug``).
        clean:         Whether to clean the build directory before building.
        vs_version:    Optional VS version override (e.g. ``vs15``).
                       If ``None`` the builder auto-detects from CMakeCache.txt.
    """

    build_config: str
    build_mode: str = "RelWithDebInfo"
    clean: bool = False
    vs_version: Optional[str] = None


@dataclass
class BuildResult:
    """Result returned after a build attempt.

    Attributes:
        success:           ``True`` if the build succeeded.
        executable_path:   Absolute path to the produced executable (if found).
        log_path:          Path to the build log file on disk (if saved).
        duration_sec:      Wall-clock seconds the build took.
        errors:            List of error messages extracted from the build log.
        warnings:          List of warning messages extracted from the build log.
    """

    success: bool
    executable_path: Optional[str] = None
    log_path: Optional[str] = None
    duration_sec: float = 0.0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class SignalData:
    """Signal data extracted from an MF4 measurement file.

    Attributes:
        name:           Signal name as it appears in the MF4 file.
        timestamps:     List of timestamp values (seconds).
        values:         List of signal values.
        unit:           Physical unit string (e.g. ``"m/s"``), empty if
                        unavailable.
        source_mf4:     Path to the MF4 file this signal was extracted from.
    """

    name: str
    timestamps: list[float]
    values: list[float]
    unit: str = ""
    source_mf4: str = ""


@dataclass
class LogEntry:
    """A single log entry parsed from a Selena log file.

    Attributes:
        timestamp: Time string in ``HH:MM:SS.mmm`` format.
        level:     Log level — ``"error"``, ``"warning"``, or ``"info"``.
        message:   The message text.
        source:    Optional source identifier (e.g. thread ID or component).
    """

    timestamp: str
    level: str  # "error" | "warning" | "info"
    message: str
    source: str = ""


@dataclass
class LogSummary:
    """Summary produced by parsing a Selena log file.

    Attributes:
        version:          Selena version string (e.g. ``"1.18.0 Roberta"``).
        runnables_loaded: Number of unique runnables detected.
        connections:      Connection count extracted from the log.
        errors:           List of ``LogEntry`` with level ``"error"``.
        warnings:         List of ``LogEntry`` with level ``"warning"`` / ``"warn"``.
        duration_sec:     Elapsed seconds between the first and last log line.
        raw_path:         Path to the source log file.
    """

    version: str = ""
    runnables_loaded: int = 0
    connections: int = 0
    errors: list[LogEntry] = field(default_factory=list)
    warnings: list[LogEntry] = field(default_factory=list)
    duration_sec: float = 0.0
    raw_path: str = ""


@dataclass
class RuleResult:
    """Result of evaluating a single rule in the rule engine.

    Attributes:
        name:     Rule name (taken from the YAML config).
        status:   One of ``"pass"``, ``"fail"``, ``"warn"``, or ``"skip"``.
        severity: Priority level ``"P0"``, ``"P1"``, or ``"P2"``.
        message:  Human-readable description of the result.
        details:  Optional extra detail (e.g. actual values, file paths).
    """

    name: str
    status: str  # "pass" | "fail" | "warn" | "skip"
    severity: str  # "P0" | "P1" | "P2"
    message: str
    details: str = ""
