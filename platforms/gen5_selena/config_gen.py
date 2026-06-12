# -*- coding: utf-8 -*-
"""
Gen5 Selena Config Generator.

Automatically generates Selena ``.txt`` configuration files from
input ``.mf4`` data files.  Reads an optional template file and
fills in all placeholders (runtime_xml, input/output paths, source,
mounting position, etc.).

Example::

    config = {
        "selena": {
            "runtime_xml": "C:/tools/Runtime_BYD_OVRS25_CR5CB_BL16_RC36.xml",
            "config_template": "C:/tools/byd_CR_Selena_Config_ovrs.txt",
        },
        "paths": {
            "results_dir": "results",
        },
    }

    gen = Gen5ConfigGenerator(config)
    cfg_path = gen.generate("data/front_right_capture.mf4", "output/fr")

"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


# ── Default Selena config line template ──────────────────────────────────
_DEFAULT_TEMPLATE = """\
config={runtime_xml}
input={input_mf4}
output={output_mf4}
log={log_file}
source={source}
nogui=true
write-mat=true
tolerant=false
userparam=mountingPosition={mounting_position}
disable-sequence-check=false
enable-multibuffer-border=true
enable-doorkeeper=true
matfilefilter={matfilefilter}
"""


class Gen5ConfigGenerator:
    """Generates Selena ``.txt`` configuration files from ``.mf4`` inputs.

    The generator auto-detects radar source (FR / FL / RR / RL) and the
    corresponding mounting position (CFR / CFL / CRR / CRL) from the MF4
    file path.  It can read an existing template file or generate the
    config from a built-in default template.

    Attributes:
        config: Configuration dict with ``selena.runtime_xml`` and
                ``selena.config_template`` keys.
    """

    # Mapping from detected source string to mounting position code
    _MOUNTING_MAP: dict[str, str] = {
        "RadarFR": "CFR",
        "RadarFL": "CFL",
        "RadarRR": "CRR",
        "RadarRL": "CRL",
    }

    def __init__(self, config: dict) -> None:
        """Initialise the generator.

        Args:
            config: Configuration dictionary.  Expected keys::

                {
                    "selena": {
                        "runtime_xml": "<path to runtime XML>",
                        "config_template": "<path to template .txt>",  # optional
                    },
                    "paths": {
                        "results_dir": "<default results directory>",
                    },
                }
        """
        self.config = config

    # ── Path-based detection helpers ────────────────────────────────────

    def _detect_source(self, mf4_path: str) -> str:
        """Infer radar source from the MF4 file path or name.

        Looks for ``FR``/``FRONT_RIGHT``, ``FL``/``FRONT_LEFT``,
        ``RR``/``REAR_RIGHT``, or ``RL``/``REAR_LEFT`` in the
        uppercased path.  Falls back to ``"RadarFR"``.

        Args:
            mf4_path: Absolute or relative path to the input .mf4 file.

        Returns:
            One of ``"RadarFR"``, ``"RadarFL"``, ``"RadarRR"``,
            ``"RadarRL"``.
        """
        path = mf4_path.upper()
        # Check explicit multi-word identifiers first to avoid prefix collisions
        # (e.g. "FRONT_LEFT" contains "FR" so FRONT_RIGHT must be checked before FR)
        if "FRONT_RIGHT" in path:
            return "RadarFR"
        if "FRONT_LEFT" in path:
            return "RadarFL"
        if "REAR_RIGHT" in path:
            return "RadarRR"
        if "REAR_LEFT" in path:
            return "RadarRL"
        # Fall back to two-letter abbreviations
        if "FR" in path:
            return "RadarFR"
        if "FL" in path:
            return "RadarFL"
        if "RR" in path:
            return "RadarRR"
        if "RL" in path:
            return "RadarRL"
        return "RadarFR"

    def _detect_mounting(self, source: str) -> str:
        """Infer mounting position code from the radar source.

        Args:
            source: Radar source string (e.g. ``"RadarFR"``).

        Returns:
            Mounting position code (e.g. ``"CFR"``).  Defaults to
            ``"CFR"`` for unknown sources.
        """
        return self._MOUNTING_MAP.get(source, "CFR")

    # ── Main generation logic ──────────────────────────────────────────

    def generate(
        self,
        input_mf4: str,
        output_dir: str,
        overrides: Optional[dict] = None,
    ) -> str:
        """Generate a Selena configuration file.

        Steps:
            1. Ensure ``output_dir`` exists on disk.
            2. Detect source and mounting position from ``input_mf4``.
            3. Derive output file names (output.mf4, CRlog.log, output.mat).
            4. Read ``config_template`` if it exists; otherwise use the
               built-in default template.
            5. Replace all ``{placeholder}`` tokens.
            6. Apply user-provided ``overrides`` on top.
            7. Guarantee that ``nogui=true`` is present.
            8. Write the final content to ``selena_config.txt``.
            9. Return the absolute path to the generated file.

        Args:
            input_mf4:  Path to the input .mf4 data file.
            output_dir: Directory where the config and output files will
                        be placed.  Created automatically if it does not
                        exist.
            overrides:  Optional dict of key-value pairs that override the
                        generated config lines (e.g. ``{"tolerant": "true"}``).

        Returns:
            Absolute path to the generated ``selena_config.txt`` file.
        """
        input_path = Path(input_mf4).resolve()
        output_path = Path(output_dir).resolve()

        # 1. Ensure output directory exists
        output_path.mkdir(parents=True, exist_ok=True)

        # 2. Detect source and mounting position
        source = self._detect_source(str(input_path))
        mounting_position = self._detect_mounting(source)

        # 3. Derive output file names
        output_mf4 = str(output_path / "output.mf4")
        log_file = str(output_path / "CRlog.log")
        matfilefilter = str(output_path / "output.mat")

        # 4. Build placeholder values
        runtime_xml = self.config.get("selena", {}).get(
            "runtime_xml", ""
        )

        placeholders = {
            "runtime_xml": runtime_xml,
            "input_mf4": str(input_path),
            "output_mf4": output_mf4,
            "log_file": log_file,
            "source": source,
            "mounting_position": mounting_position,
            "matfilefilter": matfilefilter,
        }

        # 5. Read template (or use built-in default)
        template_path = self.config.get("selena", {}).get("config_template")
        if template_path and Path(template_path).exists():
            config_text = Path(template_path).read_text(encoding="utf-8")
        else:
            config_text = _DEFAULT_TEMPLATE

        # 6. Replace placeholders
        for key, value in placeholders.items():
            config_text = config_text.replace(f"{{{key}}}", str(value))

        # 7. Apply user overrides
        if overrides:
            config_text = self._apply_overrides(config_text, overrides)

        # 8. Guarantee nogui=true is present
        config_text = self._ensure_nogui(config_text)

        # 9. Write the config file
        config_file = output_path / "selena_config.txt"
        config_file.write_text(config_text, encoding="utf-8")

        return str(config_file)

    # ── Override & safety helpers ──────────────────────────────────────

    @staticmethod
    def _apply_overrides(text: str, overrides: dict) -> str:
        """Apply key=value overrides to the config text.

        If an override key already exists as a line in the config, it is
        replaced in-place.  Otherwise the override is appended at the end.

        Args:
            text: Current config text content.
            overrides: Dict of ``{key: value}`` overrides.

        Returns:
            Config text with overrides applied.
        """
        lines = text.splitlines()

        for key, value in overrides.items():
            found = False
            for i, line in enumerate(lines):
                stripped = line.strip()
                if stripped.startswith(f"{key}=") or stripped.startswith(
                    f"{{{key}}}="
                ):
                    lines[i] = f"{key}={value}"
                    found = True
                    break
            if not found:
                lines.append(f"{key}={value}")

        return "\n".join(lines)

    @staticmethod
    def _ensure_nogui(text: str) -> str:
        """Ensure ``nogui=true`` appears in the config text.

        If a ``nogui`` line already exists it is updated to ``nogui=true``.
        If no such line exists ``nogui=true`` is appended.

        Args:
            text: Current config text content.

        Returns:
            Config text guaranteed to contain ``nogui=true``.
        """
        lines = text.splitlines()

        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("nogui"):
                lines[i] = "nogui=true"
                return "\n".join(lines)

        lines.append("nogui=true")
        return "\n".join(lines)
