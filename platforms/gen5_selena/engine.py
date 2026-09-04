# -*- coding: utf-8 -*-
"""Gen5 Selena Simulation Engine.

Launches ``selena.exe`` in headless (nogui) mode, waits for it to
complete, and collects the output artefacts (MF4, log, MAT) into a
:class:`~core.models.SimResult`.

Key constraints (from ADAPTIVITY.md):
- R1: Never pass ``--platformpluginpath`` to selena.exe.
- R3: ``nogui=true`` is set inside the config file, not on the CLI.
- R5: The executable is ``selena.exe`` (not daddy.exe).
- CLI invocation is always: ``selena.exe --paramconfig <config.txt>``.

Example::

    engine = Gen5SimulationEngine(config)
    result = engine.run("output/selena_config.txt", timeout=300)

    if result.status == "completed":
        print(f"Output MF4: {result.output_mf4}")
    else:
        print(f"Simulation failed: {result.status}")

"""
from __future__ import annotations

import logging
import os
import subprocess
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from core.models import SimConfig, SimResult

logger = logging.getLogger(__name__)


class Gen5SimulationEngine:
    """Runs Gen5 Selena simulations headlessly and collects results.

    Expects a configuration dict with the following shape::

        {
            "paths": {
                "build_output": "C:/BYD_OVS_CB/ip_dc/build/ROS_PER_SIT_RPM_FCT_RECR",
            },
            "selena": {
                "executable_name": "selena.exe",
                "exe_pattern": "dc_tools/selena/core/{build_mode}/selena.exe",
                "build_mode": "RelWithDebInfo",
            },
            "environment": {
                "path_prefix": [
                    "C:/Program Files/MATLAB/R2023b/bin/win64",
                    ...
                ],
                "python3_path": "C:/TCC/Tools/selena_environment/.../python3.exe",
                "boost_root": "C:/TCC/Tools/boost/1.63.0_WIN64",
            },
        }

    Attributes:
        config: Raw configuration dictionary (as returned by
                :func:`~config.load_config`).
    """

    def __init__(self, config: dict) -> None:
        """Initialise the engine.

        Args:
            config: Configuration dictionary with ``paths``, ``selena``,
                    and ``environment`` sections.
        """
        self.config = config

    # ------------------------------------------------------------------
    # Path resolution
    # ------------------------------------------------------------------

    def _get_selena_exe(self) -> str:
        """Locate the ``selena.exe`` binary on disk.

        Constructs the path from::

            {build_output}/{exe_pattern.format(build_mode)}/{executable_name}

        where the individual parts are read from the configuration dict.

        Returns:
            Absolute path string to ``selena.exe``.

        Raises:
            FileNotFoundError: If the resolved path does not exist.
        """
        paths_cfg = self.config.get("paths", {})
        selena_cfg = self.config.get("selena", {})

        build_output = paths_cfg.get("build_output", "")
        exe_pattern = selena_cfg.get(
            "exe_pattern", "dc_tools/selena/core/{build_mode}/selena.exe"
        )
        build_mode = selena_cfg.get("build_mode", "RelWithDebInfo")
        executable_name = selena_cfg.get("executable_name", "selena.exe")

        exe_dir = os.path.join(build_output, exe_pattern.format(build_mode=build_mode))
        exe_path = os.path.join(exe_dir, executable_name)

        if not Path(exe_path).exists():
            raise FileNotFoundError(
                f"selena.exe not found at: {exe_path}\n"
                f"  build_output = {build_output}\n"
                f"  exe_pattern  = {exe_pattern}\n"
                f"  build_mode   = {build_mode}"
            )

        return exe_path

    # ------------------------------------------------------------------
    # Environment
    # ------------------------------------------------------------------

    def _build_sim_env(self) -> dict:
        """Build the environment dictionary for launching selena.exe.

        Prepends configured paths to ``PATH`` and sets ``BOOST_ROOT``.

        Returns:
            A copy of ``os.environ`` with the additional entries set.
        """
        env = os.environ.copy()
        env_cfg = self.config.get("environment", {})

        # Build new PATH prefix list
        path_prefixes: list[str] = env_cfg.get("path_prefix", [])

        # Add the directory containing python3.exe
        python3_path = env_cfg.get("python3_path", "")
        if python3_path:
            path_prefixes.append(str(Path(python3_path).parent))

        # Add Boost library directory
        boost_root = env_cfg.get("boost_root", "")
        if boost_root:
            boost_lib = os.path.join(boost_root, "lib64-msvc-14.0")
            path_prefixes.append(boost_lib)

        # Prepend to existing PATH
        existing_path = env.get("PATH", "")
        all_paths = path_prefixes + ([existing_path] if existing_path else [])
        env["PATH"] = os.pathsep.join(all_paths)

        # Set BOOST_ROOT
        if boost_root:
            env["BOOST_ROOT"] = boost_root

        return env

    # ------------------------------------------------------------------
    # Config file parsing helpers
    # ------------------------------------------------------------------

    def _parse_config_value(self, config_path: str, key: str) -> str:
        """Extract a ``key=value`` pair from a selena config text file.

        Args:
            config_path: Path to the ``.txt`` configuration file.
            key: Key name to search for (e.g. ``"output"``, ``"log"``).

        Returns:
            The value string, or empty string if the key is not found.
        """
        config_text = Path(config_path).read_text(encoding="utf-8")

        for line in config_text.splitlines():
            stripped = line.strip()
            if stripped.startswith(f"{key}="):
                return stripped.split("=", 1)[1].strip()

        return ""

    def _find_output_mf4(self, config_path: str) -> str:
        """Find the output MF4 path specified in the config file.

        Parses the ``output=`` line from the config text.

        Args:
            config_path: Path to the selena config text file.

        Returns:
            Path to the output MF4 file, or empty string if not found.
        """
        return self._parse_config_value(config_path, "output")

    def _find_log(self, config_path: str) -> str:
        """Find the log file path specified in the config file.

        Parses the ``log=`` line from the config text.

        Args:
            config_path: Path to the selena config text file.

        Returns:
            Path to the log file, or empty string if not found.
        """
        return self._parse_config_value(config_path, "log")

    def _find_mat(self, config_path: str) -> str:
        """Infer the MAT file path from the config file.

        First checks the ``matfilefilter=`` line; if not present,
        derives the path by replacing the ``.mf4`` extension of the
        output file with ``.mat``.

        Args:
            config_path: Path to the selena config text file.

        Returns:
            Path to the MAT file, or empty string if not derivable.
        """
        matfilefilter = self._parse_config_value(config_path, "matfilefilter")
        if matfilefilter:
            return matfilefilter

        output_mf4 = self._find_output_mf4(config_path)
        if output_mf4:
            return str(Path(output_mf4).with_suffix(".mat"))

        return ""

    # ------------------------------------------------------------------
    # Main execution
    # ------------------------------------------------------------------

    def run(self, config_path: str, timeout: int = 600) -> SimResult:
        """Execute a Gen5 Selena simulation and collect the results.

        Steps:
            1. Generate a short ``sim_id`` (first 8 hex chars of a UUID).
            2. Resolve the ``selena.exe`` path.
            3. Build the environment dictionary.
            4. Construct the command: ``[selena_exe, "--paramconfig", config_path]``.
            5. Launch the process via ``subprocess.Popen``.
            6. Wait up to ``timeout`` seconds.
            7. If the process times out, kill it and return ``timed_out``.
            8. Otherwise collect the output artefacts and return the result.

        Args:
            config_path: Absolute path to the selena ``.txt`` config file.
            timeout: Maximum seconds to wait before killing the process
                     (default 600).

        Returns:
            A :class:`~core.models.SimResult` with the simulation outcome.
        """
        sim_id = uuid.uuid4().hex[:8]
        timestamp = datetime.now()

        # Build a minimal SimConfig from the config file
        output_dir = str(Path(config_path).parent)
        sim_cfg = SimConfig(
            config_file=config_path,
            input_mf4=self._parse_config_value(config_path, "input"),
            output_dir=output_dir,
            runtime_xml=self._parse_config_value(config_path, "config"),
            timeout_sec=timeout,
        )

        # Resolve executable
        try:
            selena_exe = self._get_selena_exe()
        except FileNotFoundError as exc:
            logger.error("Failed to locate selena.exe: %s", exc)
            return SimResult(
                id=sim_id,
                timestamp=timestamp,
                config=sim_cfg,
                status="failed",
                exit_code=-1,
            )

        # Build environment
        env = self._build_sim_env()

        # Working directory: selena.exe parent (for DLL resolution)
        cwd = str(Path(selena_exe).parent)

        # Build command — ONLY --paramconfig, no --platformpluginpath (R1)
        command = [selena_exe, "--paramconfig", config_path]
        logger.info("Launching: %s", " ".join(command))
        logger.info("Working directory: %s", cwd)

        start_time = time.monotonic()

        try:
            proc = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                cwd=cwd,
            )
        except OSError as exc:
            logger.error("Failed to start selena.exe: %s", exc)
            duration = time.monotonic() - start_time
            return SimResult(
                id=sim_id,
                timestamp=timestamp,
                config=sim_cfg,
                status="failed",
                exit_code=-1,
                duration_sec=duration,
            )

        # Wait for process to complete (with timeout)
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
            exit_code = proc.returncode
            status = "completed" if exit_code == 0 else "failed"
            logger.info(
                "selena.exe exited with code %d (%s)", exit_code, status
            )
        except subprocess.TimeoutExpired:
            logger.warning("Timeout after %ds — killing process tree", timeout)
            self._kill_process_tree(proc)
            duration = time.monotonic() - start_time
            return SimResult(
                id=sim_id,
                timestamp=timestamp,
                config=sim_cfg,
                status="timed_out",
                exit_code=-1,
                duration_sec=duration,
            )

        duration = time.monotonic() - start_time

        # Collect output artefacts
        output_mf4 = self._find_output_mf4(config_path)
        log_file = self._find_log(config_path)
        mat_file = self._find_mat(config_path) if status == "completed" else ""

        return SimResult(
            id=sim_id,
            timestamp=timestamp,
            config=sim_cfg,
            status=status,
            exit_code=exit_code,
            duration_sec=duration,
            output_mf4=output_mf4,
            log_file=log_file,
            mat_file=mat_file if mat_file else None,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _kill_process_tree(proc: subprocess.Popen) -> None:
        """Kill a process and all of its child processes.

        On Windows this uses ``taskkill /T /F`` to terminate the entire
        process tree.  On Unix it sends ``SIGKILL`` to the process group.

        Args:
            proc: The running subprocess.Popen instance.
        """
        pid = proc.pid
        try:
            if os.name == "nt":
                # Windows: taskkill with /T (tree) /F (force)
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(pid)],
                    capture_output=True,
                    timeout=10,
                )
            else:
                # Unix: kill process group
                import signal
                os.killpg(os.getpgid(pid), signal.SIGKILL)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to kill process tree (pid=%d): %s", pid, exc)
        finally:
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                pass
