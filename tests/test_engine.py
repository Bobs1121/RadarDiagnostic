# -*- coding: utf-8 -*-
"""Unit tests for the Gen5 Selena Simulation Engine.

Tests cover:
- Config value parsing from .txt files (_parse_config_value)
- Output file discovery (_find_output_mf4, _find_log, _find_mat)
- selena.exe path resolution (_get_selena_exe)
- Environment variable assembly (_build_sim_env)
- Full run() happy path (exit_code=0, status=completed)
- Full run() failure path (exit_code!=0, status=failed)
- Timeout handling (TimeoutExpired → kill → status=timed_out)
- Command does NOT contain --platformpluginpath (R1 constraint)

Run with::

    pytest tests/test_engine.py -v

"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure project root is on sys.path for imports
_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent
if str(_PROJECT_ROOT) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(_PROJECT_ROOT))

from platforms.gen5_selena.engine import Gen5SimulationEngine  # noqa: E402


# ── Fixtures ─────────────────────────────────────────────────────────────


def _make_config(
    build_output: str = "C:/build/output",
    exe_pattern: str = "dc_tools/selena/core/{build_mode}/selena.exe",
    build_mode: str = "RelWithDebInfo",
    executable_name: str = "selena.exe",
    path_prefix: list[str] | None = None,
    python3_path: str = "C:/Python3/python3.exe",
    boost_root: str = "C:/boost/1.63.0",
) -> dict:
    """Build a minimal config dict for testing."""
    cfg: dict = {
        "paths": {
            "build_output": build_output,
        },
        "selena": {
            "executable_name": executable_name,
            "exe_pattern": exe_pattern,
            "build_mode": build_mode,
        },
        "environment": {
            "path_prefix": path_prefix or [
                "C:/MATLAB/R2023b/bin/win64",
                "C:/Qt/5.8/bin",
            ],
            "python3_path": python3_path,
            "boost_root": boost_root,
        },
    }
    return cfg


@pytest.fixture
def config() -> dict:
    """Return a default test configuration dict."""
    return _make_config()


@pytest.fixture
def engine(config: dict) -> Gen5SimulationEngine:
    """Return a Gen5SimulationEngine with default config."""
    return Gen5SimulationEngine(config)


@pytest.fixture
def tmp_config_file(tmp_path: Path) -> Path:
    """Create a minimal selena config .txt file in a temp directory."""
    config_file = tmp_path / "selena_config.txt"
    config_file.write_text(
        "config=C:/tools/Runtime.xml\n"
        "input=C:/data/front_right.mf4\n"
        "output=C:/results/output.mf4\n"
        "log=C:/results/CRlog.log\n"
        "source=RadarFR\n"
        "nogui=true\n"
        "write-mat=true\n"
        "matfilefilter=C:/results/output.mat\n",
        encoding="utf-8",
    )
    return config_file


# ── Tests: _parse_config_value ───────────────────────────────────────────


class TestParseConfigValue:
    """Test the ``_parse_config_value`` method."""

    def test_parse_existing_key(self, engine: Gen5SimulationEngine, tmp_config_file: Path) -> None:
        """Should return the value for an existing key."""
        result = engine._parse_config_value(str(tmp_config_file), "source")
        assert result == "RadarFR"

    def test_parse_output_key(self, engine: Gen5SimulationEngine, tmp_config_file: Path) -> None:
        """Should parse the output= line correctly."""
        result = engine._parse_config_value(str(tmp_config_file), "output")
        assert result == "C:/results/output.mf4"

    def test_parse_nonexistent_key(self, engine: Gen5SimulationEngine, tmp_config_file: Path) -> None:
        """Should return empty string for a key that doesn't exist."""
        result = engine._parse_config_value(str(tmp_config_file), "nonexistent")
        assert result == ""

    def test_parse_value_with_equals(self, engine: Gen5SimulationEngine, tmp_path: Path) -> None:
        """Should handle values that contain '=' characters."""
        config_file = tmp_path / "test.txt"
        config_file.write_text("param=value=with=equals\n", encoding="utf-8")
        result = engine._parse_config_value(str(config_file), "param")
        assert result == "value=with=equals"


# ── Tests: _find_output_mf4 ──────────────────────────────────────────────


class TestFindOutputMf4:
    """Test the ``_find_output_mf4`` method."""

    def test_finds_output(self, engine: Gen5SimulationEngine, tmp_config_file: Path) -> None:
        """Should find the output MF4 path from the config."""
        result = engine._find_output_mf4(str(tmp_config_file))
        assert result == "C:/results/output.mf4"

    def test_empty_when_missing(self, engine: Gen5SimulationEngine, tmp_path: Path) -> None:
        """Should return empty string if no output= line exists."""
        config_file = tmp_path / "test.txt"
        config_file.write_text("config=/foo.xml\ninput=/bar.mf4\n", encoding="utf-8")
        result = engine._find_output_mf4(str(config_file))
        assert result == ""


# ── Tests: _find_log ─────────────────────────────────────────────────────


class TestFindLog:
    """Test the ``_find_log`` method."""

    def test_finds_log(self, engine: Gen5SimulationEngine, tmp_config_file: Path) -> None:
        """Should find the log file path from the config."""
        result = engine._find_log(str(tmp_config_file))
        assert result == "C:/results/CRlog.log"

    def test_empty_when_missing(self, engine: Gen5SimulationEngine, tmp_path: Path) -> None:
        """Should return empty string if no log= line exists."""
        config_file = tmp_path / "test.txt"
        config_file.write_text("output=/foo.mf4\n", encoding="utf-8")
        result = engine._find_log(str(config_file))
        assert result == ""


# ── Tests: _find_mat ─────────────────────────────────────────────────────


class TestFindMat:
    """Test the ``_find_mat`` method."""

    def test_finds_mat_from_matfilefilter(self, engine: Gen5SimulationEngine, tmp_config_file: Path) -> None:
        """Should find the MAT path from the matfilefilter= line."""
        result = engine._find_mat(str(tmp_config_file))
        assert result == "C:/results/output.mat"

    def test_finds_mat_from_output_fallback(self, engine: Gen5SimulationEngine, tmp_path: Path) -> None:
        """Should derive MAT path from output= when matfilefilter= is missing."""
        config_file = tmp_path / "test.txt"
        config_file.write_text(
            "output=/some/path/result.mf4\n"
            "input=/data.mf4\n",
            encoding="utf-8",
        )
        result = engine._find_mat(str(config_file))
        # Use Path comparison because the implementation normalises
        # forward slashes on Windows via ``Path`` operations.
        assert Path(result) == Path("/some/path/result.mat")

    def test_empty_when_no_output(self, engine: Gen5SimulationEngine, tmp_path: Path) -> None:
        """Should return empty string if neither matfilefilter nor output exists."""
        config_file = tmp_path / "test.txt"
        config_file.write_text("config=/foo.xml\n", encoding="utf-8")
        result = engine._find_mat(str(config_file))
        assert result == ""


# ── Tests: _get_selena_exe ───────────────────────────────────────────────


class TestGetSelenaExe:
    """Test the ``_get_selena_exe`` method."""

    def test_raises_when_not_found(self, engine: Gen5SimulationEngine) -> None:
        """Should raise FileNotFoundError when the exe doesn't exist."""
        with pytest.raises(FileNotFoundError):
            engine._get_selena_exe()

    def test_resolves_correct_path(self, config: dict, tmp_path: Path) -> None:
        """Should resolve the full path correctly."""
        # Create a fake selena.exe on disk
        fake_dir = tmp_path / "dc_tools" / "selena" / "core" / "RelWithDebInfo"
        fake_dir.mkdir(parents=True)
        fake_exe = fake_dir / "selena.exe"
        fake_exe.touch()

        # Use an exe_pattern WITHOUT the trailing executable_name — the
        # engine appends ``executable_name`` separately.
        cfg = _make_config(
            build_output=str(tmp_path),
            exe_pattern="dc_tools/selena/core/{build_mode}",
        )
        engine_inst = Gen5SimulationEngine(cfg)
        result = engine_inst._get_selena_exe()

        # Compare as Path because Windows Path.join + os.path.join normalise
        # the slash direction.
        assert Path(result) == fake_exe


# ── Tests: _build_sim_env ────────────────────────────────────────────────


class TestBuildSimEnv:
    """Test the ``_build_sim_env`` method."""

    def test_sets_boost_root(self, engine: Gen5SimulationEngine) -> None:
        """Should set BOOST_ROOT from config."""
        env = engine._build_sim_env()
        assert env["BOOST_ROOT"] == "C:/boost/1.63.0"

    def test_prepends_path_prefixes(self, engine: Gen5SimulationEngine) -> None:
        """Should prepend configured path_prefixes to PATH."""
        env = engine._build_sim_env()
        path_entries = env["PATH"].split(os.pathsep)
        # First entries should be the configured prefixes
        assert "C:/MATLAB/R2023b/bin/win64" in path_entries
        assert "C:/Qt/5.8/bin" in path_entries

    def test_includes_python3_dir(self, engine: Gen5SimulationEngine) -> None:
        """Should add the directory containing python3.exe to PATH."""
        env = engine._build_sim_env()
        path_entries = [Path(p) for p in env["PATH"].split(os.pathsep)]
        assert Path("C:/Python3") in path_entries

    def test_includes_boost_lib(self, engine: Gen5SimulationEngine) -> None:
        """Should add the Boost lib directory to PATH."""
        env = engine._build_sim_env()
        path_entries = [Path(p) for p in env["PATH"].split(os.pathsep)]
        assert Path("C:/boost/1.63.0/lib64-msvc-14.0") in path_entries


# ── Tests: run() ─────────────────────────────────────────────────────────


class TestRun:
    """Test the ``run`` method end-to-end."""

    @patch("platforms.gen5_selena.engine.subprocess.Popen")
    @patch.object(Gen5SimulationEngine, "_get_selena_exe")
    def test_successful_run(
        self,
        mock_get_exe: MagicMock,
        mock_popen: MagicMock,
        engine: Gen5SimulationEngine,
        tmp_config_file: Path,
    ) -> None:
        """Test a successful simulation run (exit_code=0)."""
        mock_get_exe.return_value = "C:/build/output/selena.exe"

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = (b"", b"")
        mock_popen.return_value = mock_proc

        result = engine.run(str(tmp_config_file), timeout=60)

        assert result.status == "completed"
        assert result.exit_code == 0
        assert result.output_mf4 == "C:/results/output.mf4"
        assert result.log_file == "C:/results/CRlog.log"
        assert result.mat_file == "C:/results/output.mat"
        assert result.duration_sec >= 0
        assert len(result.id) == 8

    @patch("platforms.gen5_selena.engine.subprocess.Popen")
    @patch.object(Gen5SimulationEngine, "_get_selena_exe")
    def test_failed_run_nonzero_exit(
        self,
        mock_get_exe: MagicMock,
        mock_popen: MagicMock,
        engine: Gen5SimulationEngine,
        tmp_config_file: Path,
    ) -> None:
        """Test a failed simulation run (exit_code!=0)."""
        mock_get_exe.return_value = "C:/build/output/selena.exe"

        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.communicate.return_value = (b"", b"Error occurred")
        mock_popen.return_value = mock_proc

        result = engine.run(str(tmp_config_file), timeout=60)

        assert result.status == "failed"
        assert result.exit_code == 1

    @patch("platforms.gen5_selena.engine.subprocess.Popen")
    @patch.object(Gen5SimulationEngine, "_get_selena_exe")
    def test_timeout_handling(
        self,
        mock_get_exe: MagicMock,
        mock_popen: MagicMock,
        engine: Gen5SimulationEngine,
        tmp_config_file: Path,
    ) -> None:
        """Test that a timeout kills the process and returns timed_out."""
        mock_get_exe.return_value = "C:/build/output/selena.exe"

        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_proc.communicate.side_effect = subprocess.TimeoutExpired(
            cmd="selena.exe", timeout=60
        )
        mock_popen.return_value = mock_proc

        result = engine.run(str(tmp_config_file), timeout=60)

        assert result.status == "timed_out"
        assert result.exit_code == -1
        mock_proc.kill.assert_called()

    @patch("platforms.gen5_selena.engine.subprocess.Popen")
    @patch.object(Gen5SimulationEngine, "_get_selena_exe")
    def test_no_platformpluginpath_in_command(
        self,
        mock_get_exe: MagicMock,
        mock_popen: MagicMock,
        engine: Gen5SimulationEngine,
        tmp_config_file: Path,
    ) -> None:
        """Verify that --platformpluginpath is NOT in the launch command (R1)."""
        mock_get_exe.return_value = "C:/build/output/selena.exe"

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = (b"", b"")
        mock_popen.return_value = mock_proc

        engine.run(str(tmp_config_file), timeout=60)

        # Check the command that was passed to Popen
        call_args = mock_popen.call_args
        command = call_args[0][0]  # First positional arg
        assert "--platformpluginpath" not in command
        assert "--paramconfig" in command

    @patch("platforms.gen5_selena.engine.subprocess.Popen")
    @patch.object(Gen5SimulationEngine, "_get_selena_exe")
    def test_command_contains_only_paramconfig(
        self,
        mock_get_exe: MagicMock,
        mock_popen: MagicMock,
        engine: Gen5SimulationEngine,
        tmp_config_file: Path,
    ) -> None:
        """Verify the command is exactly [exe, '--paramconfig', config_path]."""
        mock_get_exe.return_value = "C:/build/output/selena.exe"

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = (b"", b"")
        mock_popen.return_value = mock_proc

        engine.run(str(tmp_config_file), timeout=60)

        call_args = mock_popen.call_args
        command = call_args[0][0]
        assert len(command) == 3
        assert command[0] == "C:/build/output/selena.exe"
        assert command[1] == "--paramconfig"
        assert command[2] == str(tmp_config_file)

    @patch("platforms.gen5_selena.engine.subprocess.Popen")
    @patch.object(Gen5SimulationEngine, "_get_selena_exe")
    def test_cwd_is_selena_dir(
        self,
        mock_get_exe: MagicMock,
        mock_popen: MagicMock,
        engine: Gen5SimulationEngine,
        tmp_config_file: Path,
    ) -> None:
        """Verify that cwd is set to the directory containing selena.exe."""
        mock_get_exe.return_value = "C:/build/output/selena.exe"

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = (b"", b"")
        mock_popen.return_value = mock_proc

        engine.run(str(tmp_config_file), timeout=60)

        call_kwargs = mock_popen.call_args[1]
        # On Windows, ``Path("C:/build/output/selena.exe").parent`` normalises
        # the forward slashes to backslashes; compare via Path instead of str.
        assert Path(call_kwargs["cwd"]) == Path("C:/build/output")

    @patch("platforms.gen5_selena.engine.subprocess.Popen")
    @patch.object(Gen5SimulationEngine, "_get_selena_exe")
    def test_env_passed_to_popen(
        self,
        mock_get_exe: MagicMock,
        mock_popen: MagicMock,
        engine: Gen5SimulationEngine,
        tmp_config_file: Path,
    ) -> None:
        """Verify that the built environment is passed to Popen."""
        mock_get_exe.return_value = "C:/build/output/selena.exe"

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = (b"", b"")
        mock_popen.return_value = mock_proc

        engine.run(str(tmp_config_file), timeout=60)

        call_kwargs = mock_popen.call_args[1]
        assert "env" in call_kwargs
        env = call_kwargs["env"]
        assert env["BOOST_ROOT"] == "C:/boost/1.63.0"

    @patch("platforms.gen5_selena.engine.subprocess.Popen")
    @patch.object(Gen5SimulationEngine, "_get_selena_exe")
    def test_exe_not_found_returns_failed(
        self,
        mock_get_exe: MagicMock,
        mock_popen: MagicMock,
        engine: Gen5SimulationEngine,
        tmp_config_file: Path,
    ) -> None:
        """When selena.exe is not found, run() should return status=failed."""
        mock_get_exe.side_effect = FileNotFoundError("not found")

        result = engine.run(str(tmp_config_file), timeout=60)

        assert result.status == "failed"
        assert result.exit_code == -1
        mock_popen.assert_not_called()

    @patch("platforms.gen5_selena.engine.subprocess.Popen")
    @patch.object(Gen5SimulationEngine, "_get_selena_exe")
    def test_successful_run_has_mat_file(
        self,
        mock_get_exe: MagicMock,
        mock_popen: MagicMock,
        engine: Gen5SimulationEngine,
        tmp_config_file: Path,
    ) -> None:
        """Completed runs should include the mat_file path."""
        mock_get_exe.return_value = "C:/build/output/selena.exe"

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = (b"", b"")
        mock_popen.return_value = mock_proc

        result = engine.run(str(tmp_config_file), timeout=60)

        assert Path(result.mat_file) == Path("C:/results/output.mat")

    @patch("platforms.gen5_selena.engine.subprocess.Popen")
    @patch.object(Gen5SimulationEngine, "_get_selena_exe")
    def test_failed_run_no_mat_file(
        self,
        mock_get_exe: MagicMock,
        mock_popen: MagicMock,
        engine: Gen5SimulationEngine,
        tmp_config_file: Path,
    ) -> None:
        """Failed runs should NOT include the mat_file path."""
        mock_get_exe.return_value = "C:/build/output/selena.exe"

        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.communicate.return_value = (b"", b"Error")
        mock_popen.return_value = mock_proc

        result = engine.run(str(tmp_config_file), timeout=60)

        # When the run fails, mat_file is either empty string or None —
        # both signal "no output produced". Use falsy check rather than
        # an exact comparison.
        assert not result.mat_file
