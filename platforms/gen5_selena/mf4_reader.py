# -*- coding: utf-8 -*-
"""Gen5 MF4 Reader — extract signal data from ASAM MFD4 measurement files.

Uses the ``asammdf`` library to open a ``.mf4`` file and pull out named
signals as :class:`~core.models.SignalData` objects.

This module does **not** require asammdf at import time — the import
happens lazily inside :meth:`Gen5Mf4Reader.extract` so that unit tests
can run without the dependency installed.

Typical usage::

    reader = Gen5Mf4Reader()
    signals = reader.extract(
        "output/selena_result.mf4",
        ["egoSpeed", "objDistX", "fTTC"],
    )

    for name, sig in signals.items():
        print(f"{name}: {len(sig.values)} samples, unit={sig.unit}")

Known issues (ADAPTIVITY.md):
    - **M1**: MF4 format is tied to the runtime version (does not affect
      reading as long as asammdf supports the MFD4 spec version).
    - **M2**: Large files (~270 MB) benefit from block-level streaming
      rather than loading the entire file into memory.
    - **M3**: asammdf compatibility should be verified against the actual
      MF4 files produced by the Gen5 runtime.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from core.models import SignalData

logger = logging.getLogger(__name__)

# asammdf is the only mandatory dependency for MF4 reading. Imported at
# module level so that tests can ``@patch("platforms.gen5_selena.mf4_reader.MDF")``
# without the patch failing on ``AttributeError: module ... has no attribute 'MDF'``.
# The previous lazy-import inside ``extract`` was documented in the docstring
# ("does not require asammdf at import time") but in practice the library
# is always installed in any environment that runs the pipeline; users who
# genuinely lack it get a clear ImportError on first use.
try:
    from asammdf import MDF  # noqa: F401  (re-exported for test patching)
except ImportError as _asammdf_exc:  # pragma: no cover - environment guard
    MDF = None  # type: ignore[assignment]
    _ASAMMDF_IMPORT_ERROR = _asammdf_exc
else:
    _ASAMMDF_IMPORT_ERROR = None


class Gen5Mf4Reader:
    """Read signal channels from ASAM MFD4 (.mf4) measurement files.

    Opens an MF4 file via ``asammdf``, iterates over a list of requested
    signal names, and returns a ``dict[str, SignalData]`` mapping each
    signal name to its time-series data.

    If a requested signal name does not exist in the file an *exact*
    match fails, a fuzzy match (case-insensitive / substring) is attempted
    as a fallback.

    Args:
        config: Optional configuration dictionary. Currently reserved for
                future extensions; no keys are consumed yet.

    Example::

        reader = Gen5Mf4Reader(config={})
        signals = reader.extract("output.mf4", ["egoSpeed", "objDistX"])
    """

    def __init__(self, config: dict | None = None) -> None:
        """Initialise the MF4 reader.

        Args:
            config: Optional configuration dictionary. Reserved for
                    future use.
        """
        self.config = config or {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract(
        self, output_file: str, signal_names: list[str]
    ) -> dict[str, SignalData]:
        """Extract named signals from an MF4 file.

        Opens the file with ``asammdf.MDF``, iterates over the requested
        signal names, and returns a mapping of each name to a
        :class:`~core.models.SignalData` instance.

        For each requested signal:
        1. Attempts an **exact** match against the keys in the MF4 file.
        2. If not found, falls back to **fuzzy matching**
           (:meth:`_fuzzy_match`).
        3. On a successful match extracts timestamps, values, and unit.
        4. If the signal still cannot be found it is silently skipped
           and logged as a warning.

        Args:
            output_file: Path to the ``.mf4`` measurement file.
            signal_names: List of signal names to extract.

        Returns:
            A ``dict`` mapping each successfully extracted signal name
            (the name that was requested, not the matched MF4 key) to a
            :class:`~core.models.SignalData` instance.

        Raises:
            FileNotFoundError:  If the MF4 file does not exist on disk.
            PermissionError:    If the MF4 file cannot be opened.
            ImportError:        If ``asammdf`` is not installed.
        """
        output_path = Path(output_file)

        if not output_path.exists():
            raise FileNotFoundError(f"MF4 file not found: {output_file}")

        if MDF is None:
            raise ImportError(
                "asammdf is required for MF4 reading. "
                "Install with: pip install asammdf"
            ) from _ASAMMDF_IMPORT_ERROR

        mdf = MDF(str(output_path))
        available = list(mdf.keys())
        result: dict[str, SignalData] = {}

        try:
            for sig_name in signal_names:
                # (1) Exact match
                matched_key: Optional[str] = sig_name if sig_name in available else None

                # (2) Fuzzy match fallback
                if matched_key is None:
                    matched_key = self._fuzzy_match(sig_name, available)

                if matched_key is None:
                    logger.warning(
                        "Signal '%s' not found in MF4 (tried exact + fuzzy). "
                        "Available signals: %s",
                        sig_name,
                        available[:20],
                    )
                    continue

                # (3) Extract signal data
                sig = mdf[matched_key]
                timestamps = sig.timestamps.tolist()
                values = sig.values.tolist()
                unit: str = getattr(sig, "unit", "") or ""

                result[sig_name] = SignalData(
                    name=sig_name,
                    timestamps=timestamps,
                    values=values,
                    unit=unit,
                    source_mf4=str(output_path),
                )

                logger.debug(
                    "Extracted signal '%s' (matched='%s'): %d samples, unit='%s'",
                    sig_name,
                    matched_key,
                    len(values),
                    unit,
                )
        finally:
            mdf.close()

        return result

    def list_available_signals(self, mf4_path: str) -> list[str]:
        """List all signal names available in an MF4 file.

        Args:
            mf4_path: Path to the ``.mf4`` measurement file.

        Returns:
            A list of all channel/signal names stored in the file.

        Raises:
            FileNotFoundError:  If the file does not exist.
            PermissionError:    If the file cannot be opened.
            ImportError:        If ``asammdf`` is not installed.
        """
        mf4_file = Path(mf4_path)

        if not mf4_file.exists():
            raise FileNotFoundError(f"MF4 file not found: {mf4_path}")

        if MDF is None:
            raise ImportError(
                "asammdf is required for MF4 reading. "
                "Install with: pip install asammdf"
            ) from _ASAMMDF_IMPORT_ERROR

        mdf = MDF(str(mf4_file))
        try:
            return list(mdf.keys())
        finally:
            mdf.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _fuzzy_match(target: str, available: list[str]) -> Optional[str]:
        """Attempt a fuzzy name match against available signal names.

        Matching strategy (in priority order):
        1. **Case-insensitive exact match** — ``target.lower() ==
           candidate.lower()``.
        2. **Substring match** — ``target.lower()`` is a substring of
           ``candidate.lower()``. Returns the first match found.

        Args:
            target: The signal name to look for.
            available: List of signal names present in the MF4 file.

        Returns:
            The matched signal name from ``available``, or ``None`` if
            no fuzzy match could be found.
        """
        target_lower = target.lower()

        # Guard: empty target can never meaningfully match
        if not target_lower:
            return None

        # Strategy 1: case-insensitive exact match
        for name in available:
            if name.lower() == target_lower:
                return name

        # Strategy 2: substring match (target is a substring of candidate)
        for name in available:
            if target_lower in name.lower():
                return name

        return None
