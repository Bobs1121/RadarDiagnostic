# -*- coding: utf-8 -*-
"""Unit tests for the Gen5 MF4 Reader module.

Tests cover:
- ``_fuzzy_match`` fuzzy matching logic (case-insensitive, substring, no match).
- ``extract`` happy path with mocked ``asammdf.MDF``.
- ``extract`` when a signal does not exist (skipped + warning).
- ``extract`` with fuzzy match fallback.
- ``list_available_signals`` returns the correct list.
- ``extract`` / ``list_available_signals`` raise ``FileNotFoundError``
  when the MF4 file does not exist.
- ``extract`` / ``list_available_signals`` raise ``PermissionError``
  when the MF4 file cannot be opened.

Run with::

    pytest tests/test_mf4_reader.py -v

All asammdf interactions are mocked so these tests pass without the
library installed.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure project root is on sys.path for imports
_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent
if str(_PROJECT_ROOT) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(_PROJECT_ROOT))

from core.models import SignalData  # noqa: E402
from platforms.gen5_selena.mf4_reader import Gen5Mf4Reader  # noqa: E402


# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture
def reader() -> Gen5Mf4Reader:
    """Return a Gen5Mf4Reader with default config."""
    return Gen5Mf4Reader()


@pytest.fixture
def reader_with_config() -> Gen5Mf4Reader:
    """Return a Gen5Mf4Reader with a non-empty config dict."""
    return Gen5Mf4Reader(config={"some_key": "some_value"})


# ── Helpers ──────────────────────────────────────────────────────────────


def _make_mock_signal(timestamps: list[float], values: list[float], unit: str = "") -> MagicMock:
    """Create a mock signal object that behaves like an asammdf Signal."""
    sig = MagicMock()
    sig.timestamps.tolist.return_value = timestamps
    sig.values.tolist.return_value = values
    sig.unit = unit
    return sig


def _make_mock_mdf(
    keys: list[str] | None = None,
    signals: dict[str, MagicMock] | None = None,
) -> MagicMock:
    """Create a mock MDF object with the given keys and signals.

    Args:
        keys: Signal names returned by ``mdf.keys()``.
        signals: Mapping from signal name to mock Signal objects.

    Returns:
        A MagicMock configured to behave like ``asammdf.MDF``.
    """
    keys = keys or ["SignalA", "SignalB"]
    signals = signals or {
        "SignalA": _make_mock_signal([0.0, 0.1, 0.2], [1.0, 2.0, 3.0], "m/s"),
        "SignalB": _make_mock_signal([0.0, 0.1], [100.0, 200.0], "Pa"),
    }

    mdf = MagicMock()
    mdf.keys.return_value = keys
    mdf.__getitem__.side_effect = lambda name: signals[name]
    return mdf


# ── Tests: __init__ ──────────────────────────────────────────────────────


class TestInit:
    """Test Gen5Mf4Reader initialisation."""

    def test_default_config(self, reader: Gen5Mf4Reader) -> None:
        """Should use an empty dict when no config is provided."""
        assert reader.config == {}

    def test_custom_config(self, reader_with_config: Gen5Mf4Reader) -> None:
        """Should store the provided config dict."""
        assert reader_with_config.config == {"some_key": "some_value"}

    def test_none_config(self) -> None:
        """Passing None explicitly should result in an empty dict."""
        r = Gen5Mf4Reader(config=None)
        assert r.config == {}


# ── Tests: _fuzzy_match ─────────────────────────────────────────────────


class TestFuzzyMatch:
    """Test the ``_fuzzy_match`` method."""

    def test_case_insensitive_exact_match(self, reader: Gen5Mf4Reader) -> None:
        """Should match when case differs but the name is the same."""
        result = reader._fuzzy_match("signalspeed", ["SignalSpeed", "Other"])
        assert result == "SignalSpeed"

    def test_substring_match(self, reader: Gen5Mf4Reader) -> None:
        """Should match when target is a substring of an available name."""
        result = reader._fuzzy_match("Speed", ["EgoSpeedKmh", "OtherSignal"])
        assert result == "EgoSpeedKmh"

    def test_substring_match_case_insensitive(self, reader: Gen5Mf4Reader) -> None:
        """Substring match should also be case-insensitive."""
        result = reader._fuzzy_match("speed", ["EgoSpeedKmh"])
        assert result == "EgoSpeedKmh"

    def test_no_match_returns_none(self, reader: Gen5Mf4Reader) -> None:
        """Should return None when no fuzzy match exists."""
        result = reader._fuzzy_match("TotallyDifferent", ["SignalA", "SignalB"])
        assert result is None

    def test_exact_match_takes_priority(self, reader: Gen5Mf4Reader) -> None:
        """Case-insensitive exact match should win over substring."""
        result = reader._fuzzy_match("Speed", ["Speed", "EgoSpeedKmh"])
        assert result == "Speed"

    def test_empty_available_list(self, reader: Gen5Mf4Reader) -> None:
        """Should return None for an empty available list."""
        result = reader._fuzzy_match("Signal", [])
        assert result is None

    def test_target_empty_string(self, reader: Gen5Mf4Reader) -> None:
        """An empty target should not match anything."""
        result = reader._fuzzy_match("", ["SignalA"])
        assert result is None


# ── Tests: extract ───────────────────────────────────────────────────────


class TestExtract:
    """Test the ``extract`` method."""

    @patch("platforms.gen5_selena.mf4_reader.MDF")
    @patch("pathlib.Path.exists", return_value=True)
    def test_extract_success(
        self,
        _mock_exists: MagicMock,
        mock_mdf_class: MagicMock,
        reader: Gen5Mf4Reader,
        tmp_path: Path,
    ) -> None:
        """Should extract signals and return a dict of SignalData."""
        mdf_instance = _make_mock_mdf(
            keys=["SignalA", "SignalB"],
            signals={
                "SignalA": _make_mock_signal([0.0, 0.1], [1.0, 2.0], "m/s"),
                "SignalB": _make_mock_signal([0.0], [100.0], "Pa"),
            },
        )
        mock_mdf_class.return_value = mdf_instance

        mf4_file = tmp_path / "output.mf4"
        mf4_file.touch()

        result = reader.extract(str(mf4_file), ["SignalA", "SignalB"])

        assert len(result) == 2
        assert result["SignalA"].name == "SignalA"
        assert result["SignalA"].timestamps == [0.0, 0.1]
        assert result["SignalA"].values == [1.0, 2.0]
        assert result["SignalA"].unit == "m/s"
        assert result["SignalB"].name == "SignalB"
        assert result["SignalB"].timestamps == [0.0]
        assert result["SignalB"].values == [100.0]
        assert result["SignalB"].unit == "Pa"
        mdf_instance.close.assert_called_once()

    @patch("platforms.gen5_selena.mf4_reader.MDF")
    @patch("pathlib.Path.exists", return_value=True)
    def test_extract_signal_not_found(
        self,
        _mock_exists: MagicMock,
        mock_mdf_class: MagicMock,
        reader: Gen5Mf4Reader,
        tmp_path: Path,
    ) -> None:
        """Should skip signals that do not exist and not raise."""
        mdf_instance = _make_mock_mdf(
            keys=["SignalA"],
            signals={
                "SignalA": _make_mock_signal([0.0], [1.0], ""),
            },
        )
        mock_mdf_class.return_value = mdf_instance

        mf4_file = tmp_path / "output.mf4"
        mf4_file.touch()

        result = reader.extract(str(mf4_file), ["SignalA", "NonExistent"])

        assert len(result) == 1
        assert "SignalA" in result
        assert "NonExistent" not in result

    @patch("platforms.gen5_selena.mf4_reader.MDF")
    @patch("pathlib.Path.exists", return_value=True)
    def test_extract_fuzzy_match_fallback(
        self,
        _mock_exists: MagicMock,
        mock_mdf_class: MagicMock,
        reader: Gen5Mf4Reader,
        tmp_path: Path,
    ) -> None:
        """Should use fuzzy match when exact match fails."""
        mdf_instance = _make_mock_mdf(
            keys=["EgoSpeedKmh"],
            signals={
                "EgoSpeedKmh": _make_mock_signal([0.0, 0.1], [50.0, 55.0], "km/h"),
            },
        )
        mock_mdf_class.return_value = mdf_instance

        mf4_file = tmp_path / "output.mf4"
        mf4_file.touch()

        # Request "EgoSpeed" — not an exact match but a substring of "EgoSpeedKmh"
        result = reader.extract(str(mf4_file), ["EgoSpeed"])

        assert len(result) == 1
        assert "EgoSpeed" in result
        assert result["EgoSpeed"].name == "EgoSpeed"
        assert result["EgoSpeed"].values == [50.0, 55.0]
        assert result["EgoSpeed"].unit == "km/h"

    @patch("platforms.gen5_selena.mf4_reader.MDF")
    @patch("pathlib.Path.exists", return_value=True)
    def test_extract_source_mf4_set(
        self,
        _mock_exists: MagicMock,
        mock_mdf_class: MagicMock,
        reader: Gen5Mf4Reader,
        tmp_path: Path,
    ) -> None:
        """Should set source_mf4 on the returned SignalData."""
        mdf_instance = _make_mock_mdf(
            keys=["SignalA"],
            signals={"SignalA": _make_mock_signal([0.0], [1.0], "")},
        )
        mock_mdf_class.return_value = mdf_instance

        mf4_file = tmp_path / "test.mf4"
        mf4_file.touch()

        result = reader.extract(str(mf4_file), ["SignalA"])

        assert result["SignalA"].source_mf4 == str(mf4_file)

    @patch("platforms.gen5_selena.mf4_reader.MDF")
    @patch("pathlib.Path.exists", return_value=True)
    def test_extract_empty_signal_names(
        self,
        _mock_exists: MagicMock,
        mock_mdf_class: MagicMock,
        reader: Gen5Mf4Reader,
        tmp_path: Path,
    ) -> None:
        """Should return an empty dict when no signal names are requested."""
        mdf_instance = _make_mock_mdf()
        mock_mdf_class.return_value = mdf_instance

        mf4_file = tmp_path / "output.mf4"
        mf4_file.touch()

        result = reader.extract(str(mf4_file), [])

        assert result == {}
        mdf_instance.close.assert_called_once()

    def test_extract_file_not_found(self, reader: Gen5Mf4Reader) -> None:
        """Should raise FileNotFoundError for a non-existent MF4 file."""
        with pytest.raises(FileNotFoundError, match="MF4 file not found"):
            reader.extract("/nonexistent/path/output.mf4", ["SignalA"])

    @patch("platforms.gen5_selena.mf4_reader.MDF", side_effect=PermissionError("access denied"))
    @patch("pathlib.Path.exists", return_value=True)
    def test_extract_permission_error(
        self,
        _mock_exists: MagicMock,
        mock_mdf_class: MagicMock,
        reader: Gen5Mf4Reader,
        tmp_path: Path,
    ) -> None:
        """Should raise PermissionError when the file cannot be opened."""
        mf4_file = tmp_path / "output.mf4"
        mf4_file.touch()

        with pytest.raises(PermissionError, match="access denied"):
            reader.extract(str(mf4_file), ["SignalA"])

    @patch("pathlib.Path.exists", return_value=True)
    def test_extract_asammdf_not_installed(
        self,
        _mock_exists: MagicMock,
        reader: Gen5Mf4Reader,
        tmp_path: Path,
    ) -> None:
        """Should raise ImportError with a helpful message when asammdf is missing."""
        mf4_file = tmp_path / "output.mf4"
        mf4_file.touch()

        with patch.dict("sys.modules", {"asammdf": None}):
            with pytest.raises(ImportError, match="asammdf is required"):
                reader.extract(str(mf4_file), ["SignalA"])

    @patch("platforms.gen5_selena.mf4_reader.MDF")
    @patch("pathlib.Path.exists", return_value=True)
    def test_extract_mdf_closed_on_exception(
        self,
        _mock_exists: MagicMock,
        mock_mdf_class: MagicMock,
        reader: Gen5Mf4Reader,
        tmp_path: Path,
    ) -> None:
        """Should close the MDF file even if extraction raises an error."""
        mdf_instance = _make_mock_mdf(
            keys=["SignalA"],
            signals={
                "SignalA": _make_mock_signal([0.0], [1.0], ""),
            },
        )
        # Make tolist() raise on second call
        sig = mdf_instance["SignalA"]
        values = sig.values.tolist.return_value
        call_count = [0]

        def failing_tolist():
            call_count[0] += 1
            if call_count[0] == 1:
                return values
            raise RuntimeError("Simulated error")

        sig.timestamps.tolist.side_effect = failing_tolist
        mock_mdf_class.return_value = mdf_instance

        mf4_file = tmp_path / "output.mf4"
        mf4_file.touch()

        with pytest.raises(RuntimeError):
            reader.extract(str(mf4_file), ["SignalA"])

        mdf_instance.close.assert_called_once()


# ── Tests: list_available_signals ────────────────────────────────────────


class TestListAvailableSignals:
    """Test the ``list_available_signals`` method."""

    @patch("platforms.gen5_selena.mf4_reader.MDF")
    @patch("pathlib.Path.exists", return_value=True)
    def test_returns_signal_names(
        self,
        _mock_exists: MagicMock,
        mock_mdf_class: MagicMock,
        reader: Gen5Mf4Reader,
        tmp_path: Path,
    ) -> None:
        """Should return the list of available signal names."""
        mdf_instance = MagicMock()
        mdf_instance.keys.return_value = ["SignalA", "SignalB", "SignalC"]
        mock_mdf_class.return_value = mdf_instance

        mf4_file = tmp_path / "output.mf4"
        mf4_file.touch()

        result = reader.list_available_signals(str(mf4_file))

        assert result == ["SignalA", "SignalB", "SignalC"]
        mdf_instance.close.assert_called_once()

    def test_file_not_found(self, reader: Gen5Mf4Reader) -> None:
        """Should raise FileNotFoundError for a non-existent file."""
        with pytest.raises(FileNotFoundError, match="MF4 file not found"):
            reader.list_available_signals("/nonexistent/output.mf4")

    @patch("platforms.gen5_selena.mf4_reader.MDF", side_effect=PermissionError("locked"))
    @patch("pathlib.Path.exists", return_value=True)
    def test_permission_error(
        self,
        _mock_exists: MagicMock,
        mock_mdf_class: MagicMock,
        reader: Gen5Mf4Reader,
        tmp_path: Path,
    ) -> None:
        """Should raise PermissionError when the file is locked."""
        mf4_file = tmp_path / "output.mf4"
        mf4_file.touch()

        with pytest.raises(PermissionError, match="locked"):
            reader.list_available_signals(str(mf4_file))

    @patch("pathlib.Path.exists", return_value=True)
    def test_asammdf_not_installed(
        self,
        _mock_exists: MagicMock,
        reader: Gen5Mf4Reader,
        tmp_path: Path,
    ) -> None:
        """Should raise ImportError when asammdf is missing."""
        mf4_file = tmp_path / "output.mf4"
        mf4_file.touch()

        with patch.dict("sys.modules", {"asammdf": None}):
            with pytest.raises(ImportError, match="asammdf is required"):
                reader.list_available_signals(str(mf4_file))

    @patch("platforms.gen5_selena.mf4_reader.MDF")
    @patch("pathlib.Path.exists", return_value=True)
    def test_empty_file(
        self,
        _mock_exists: MagicMock,
        mock_mdf_class: MagicMock,
        reader: Gen5Mf4Reader,
        tmp_path: Path,
    ) -> None:
        """Should return an empty list for an MF4 with no signals."""
        mdf_instance = MagicMock()
        mdf_instance.keys.return_value = []
        mock_mdf_class.return_value = mdf_instance

        mf4_file = tmp_path / "empty.mf4"
        mf4_file.touch()

        result = reader.list_available_signals(str(mf4_file))
        assert result == []
