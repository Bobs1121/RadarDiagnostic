# -*- coding: utf-8 -*-
"""
Unit tests for the Gen5 Selena Config Generator.

Tests cover:
- Source detection from various MF4 path patterns (FR / FL / RR / RL / unknown)
- Mounting position mapping
- Full config file generation
- nogui=true presence enforcement
- User override application
- Template exist / not-exist code paths
- Auto-creation of output directories

Run with::

    pytest tests/test_config_gen.py -v

"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

# Ensure project root is on sys.path for imports
_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent
if str(_PROJECT_ROOT) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(_PROJECT_ROOT))

from platforms.gen5_selena.config_gen import Gen5ConfigGenerator  # noqa: E402


# ── Fixtures ─────────────────────────────────────────────────────────────

def _make_config(
    runtime_xml: str = "C:/tools/Runtime_BYD_OVRS25_CR5CB_BL16_RC36.xml",
    config_template: str | None = None,
) -> dict[str, Any]:
    """Build a minimal config dict for testing."""
    cfg: dict[str, Any] = {
        "selena": {
            "runtime_xml": runtime_xml,
        },
        "paths": {
            "results_dir": "results",
        },
    }
    if config_template is not None:
        cfg["selena"]["config_template"] = config_template
    return cfg


@pytest.fixture
def generator() -> Gen5ConfigGenerator:
    """Return a Gen5ConfigGenerator with default config (no template)."""
    return Gen5ConfigGenerator(_make_config())


@pytest.fixture
def generator_with_template(tmp_path: Path) -> tuple[Gen5ConfigGenerator, str]:
    """Return a generator that points to an existing template file."""
    template = tmp_path / "template.txt"
    template.write_text(
        "config={runtime_xml}\ninput={input_mf4}\ncustom_key=original\n",
        encoding="utf-8",
    )
    gen = Gen5ConfigGenerator(
        _make_config(config_template=str(template))
    )
    return gen, str(template)


# ── Tests: _detect_source ────────────────────────────────────────────────

class TestDetectSource:
    """Test the ``_detect_source`` method against various path inputs."""

    def test_detect_fr(self, generator: Gen5ConfigGenerator) -> None:
        assert generator._detect_source("data/front_right.mf4") == "RadarFR"

    def test_detect_fr_upper(self, generator: Gen5ConfigGenerator) -> None:
        assert generator._detect_source("DATA/FR_DATA.mf4") == "RadarFR"

    def test_detect_fr_front_right(self, generator: Gen5ConfigGenerator) -> None:
        assert generator._detect_source(
            "data/FRONT_RIGHT_RADAR.mf4"
        ) == "RadarFR"

    def test_detect_fl(self, generator: Gen5ConfigGenerator) -> None:
        assert generator._detect_source("data/front_left.mf4") == "RadarFL"

    def test_detect_fl_front_left(self, generator: Gen5ConfigGenerator) -> None:
        assert generator._detect_source(
            "data/FRONT_LEFT.mf4"
        ) == "RadarFL"

    def test_detect_rr(self, generator: Gen5ConfigGenerator) -> None:
        assert generator._detect_source("data/rear_right.mf4") == "RadarRR"

    def test_detect_rr_rear_right(self, generator: Gen5ConfigGenerator) -> None:
        assert generator._detect_source(
            "data/REAR_RIGHT.mf4"
        ) == "RadarRR"

    def test_detect_rl(self, generator: Gen5ConfigGenerator) -> None:
        assert generator._detect_source("data/rear_left.mf4") == "RadarRL"

    def test_detect_rl_rear_left(self, generator: Gen5ConfigGenerator) -> None:
        assert generator._detect_source(
            "data/REAR_LEFT.mf4"
        ) == "RadarRL"

    def test_detect_unknown_defaults_to_fr(self, generator: Gen5ConfigGenerator) -> None:
        """Unknown path should default to RadarFR."""
        assert generator._detect_source("data/unknown_capture.mf4") == "RadarFR"
        assert generator._detect_source("C:/temp/test.mf4") == "RadarFR"


# ── Tests: _detect_mounting ──────────────────────────────────────────────

class TestDetectMounting:
    """Test the ``_detect_mounting`` method mapping."""

    def test_fr_to_cfr(self, generator: Gen5ConfigGenerator) -> None:
        assert generator._detect_mounting("RadarFR") == "CFR"

    def test_fl_to_cfl(self, generator: Gen5ConfigGenerator) -> None:
        assert generator._detect_mounting("RadarFL") == "CFL"

    def test_rr_to_crr(self, generator: Gen5ConfigGenerator) -> None:
        assert generator._detect_mounting("RadarRR") == "CRR"

    def test_rl_to_crl(self, generator: Gen5ConfigGenerator) -> None:
        assert generator._detect_mounting("RadarRL") == "CRL"

    def test_unknown_defaults_to_cfr(self, generator: Gen5ConfigGenerator) -> None:
        assert generator._detect_mounting("UnknownSource") == "CFR"


# ── Tests: generate ─────────────────────────────────────────────────────

class TestGenerate:
    """Integration-style tests for the ``generate`` method."""

    def test_generate_creates_config_file(
        self, generator: Gen5ConfigGenerator, tmp_path: Path
    ) -> None:
        mf4 = tmp_path / "test.mf4"
        mf4.touch()
        out_dir = tmp_path / "out"

        cfg_path = generator.generate(str(mf4), str(out_dir))

        assert Path(cfg_path).exists()
        assert Path(cfg_path).name == "selena_config.txt"

    def test_generate_content_correct(
        self, generator: Gen5ConfigGenerator, tmp_path: Path
    ) -> None:
        mf4 = tmp_path / "front_right_test.mf4"
        mf4.touch()
        out_dir = tmp_path / "out"

        cfg_path = generator.generate(str(mf4), str(out_dir))
        content = Path(cfg_path).read_text(encoding="utf-8")

        # Check key lines are present
        assert "source=RadarFR" in content
        assert "userparam=mountingPosition=CFR" in content
        assert "config=C:/tools/Runtime_BYD_OVRS25_CR5CB_BL16_RC36.xml" in content
        assert "input=" in content
        assert "output=" in content

    def test_generate_detects_source_from_path(
        self, generator: Gen5ConfigGenerator, tmp_path: Path
    ) -> None:
        """Verify source is detected from the MF4 filename."""
        mf4 = tmp_path / "rear_left_capture.mf4"
        mf4.touch()
        out_dir = tmp_path / "out_rl"

        cfg_path = generator.generate(str(mf4), str(out_dir))
        content = Path(cfg_path).read_text(encoding="utf-8")

        assert "source=RadarRL" in content
        assert "userparam=mountingPosition=CRL" in content

    def test_nogui_true_present(
        self, generator: Gen5ConfigGenerator, tmp_path: Path
    ) -> None:
        """nogui=true must be in the generated config."""
        mf4 = tmp_path / "test.mf4"
        mf4.touch()

        cfg_path = generator.generate(str(mf4), str(tmp_path / "out"))
        content = Path(cfg_path).read_text(encoding="utf-8")

        assert "nogui=true" in content

    def test_nogui_true_enforced_even_when_missing(
        self, generator_with_template: tuple[Gen5ConfigGenerator, str], tmp_path: Path
    ) -> None:
        """nogui=true should be appended if template has no nogui line."""
        gen, _ = generator_with_template
        mf4 = tmp_path / "test.mf4"
        mf4.touch()

        cfg_path = gen.generate(str(mf4), str(tmp_path / "out"))
        content = Path(cfg_path).read_text(encoding="utf-8")

        assert "nogui=true" in content

    def test_nogui_overridden_to_true(
        self, tmp_path: Path
    ) -> None:
        """Even if template has nogui=false, it should be forced to true."""
        template = tmp_path / "template_no_nogui.txt"
        template.write_text(
            "config={runtime_xml}\nnogui=false\ninput={input_mf4}\n",
            encoding="utf-8",
        )
        gen = Gen5ConfigGenerator(
            _make_config(config_template=str(template))
        )
        mf4 = tmp_path / "test.mf4"
        mf4.touch()

        cfg_path = gen.generate(str(mf4), str(tmp_path / "out"))
        content = Path(cfg_path).read_text(encoding="utf-8")

        assert "nogui=false" not in content
        assert "nogui=true" in content

    def test_overrides_replace_existing_lines(
        self, generator: Gen5ConfigGenerator, tmp_path: Path
    ) -> None:
        """User overrides should replace existing config lines."""
        mf4 = tmp_path / "test.mf4"
        mf4.touch()
        out_dir = tmp_path / "out"

        cfg_path = generator.generate(
            str(mf4), str(out_dir),
            overrides={"tolerant": "true", "write-mat": "false"},
        )
        content = Path(cfg_path).read_text(encoding="utf-8")

        assert "tolerant=true" in content
        assert "write-mat=false" in content

    def test_overrides_append_new_lines(
        self, generator: Gen5ConfigGenerator, tmp_path: Path
    ) -> None:
        """User overrides for keys not in the template are appended."""
        mf4 = tmp_path / "test.mf4"
        mf4.touch()
        out_dir = tmp_path / "out"

        cfg_path = generator.generate(
            str(mf4), str(out_dir),
            overrides={"custom_param": "custom_value"},
        )
        content = Path(cfg_path).read_text(encoding="utf-8")

        assert "custom_param=custom_value" in content

    def test_template_used_when_exists(
        self, generator_with_template: tuple[Gen5ConfigGenerator, str], tmp_path: Path
    ) -> None:
        """Config template is used when it exists on disk."""
        gen, _ = generator_with_template
        mf4 = tmp_path / "test.mf4"
        mf4.touch()

        cfg_path = gen.generate(str(mf4), str(tmp_path / "out"))
        content = Path(cfg_path).read_text(encoding="utf-8")

        # Template had custom_key=original
        assert "custom_key=original" in content

    def test_template_not_exists_falls_back_to_default(
        self, tmp_path: Path
    ) -> None:
        """Missing template falls back to the built-in default."""
        gen = Gen5ConfigGenerator(
            _make_config(
                config_template=str(tmp_path / "does_not_exist.txt")
            )
        )
        mf4 = tmp_path / "test.mf4"
        mf4.touch()

        cfg_path = gen.generate(str(mf4), str(tmp_path / "out"))
        content = Path(cfg_path).read_text(encoding="utf-8")

        # Default template has these lines
        assert "enable-doorkeeper=true" in content
        assert "enable-multibuffer-border=true" in content
        assert "disable-sequence-check=false" in content

    def test_output_dir_auto_created(
        self, generator: Gen5ConfigGenerator, tmp_path: Path
    ) -> None:
        """Output directory is created automatically if it doesn't exist."""
        mf4 = tmp_path / "test.mf4"
        mf4.touch()
        nested = tmp_path / "a" / "b" / "c"

        cfg_path = generator.generate(str(mf4), str(nested))

        assert nested.exists()
        assert Path(cfg_path).exists()

    def test_returns_absolute_path(
        self, generator: Gen5ConfigGenerator, tmp_path: Path
    ) -> None:
        """generate() returns an absolute path string."""
        mf4 = tmp_path / "test.mf4"
        mf4.touch()

        cfg_path = generator.generate(str(mf4), str(tmp_path / "out"))

        assert os.path.isabs(cfg_path)

    def test_overrides_with_nogui_still_enforced(
        self, generator: Gen5ConfigGenerator, tmp_path: Path
    ) -> None:
        """Even when overrides try to set nogui=false, it stays true."""
        mf4 = tmp_path / "test.mf4"
        mf4.touch()
        out_dir = tmp_path / "out"

        cfg_path = generator.generate(
            str(mf4), str(out_dir),
            overrides={"nogui": "false"},
        )
        content = Path(cfg_path).read_text(encoding="utf-8")

        # _ensure_nogui runs after overrides, so nogui=true wins
        assert "nogui=true" in content
        assert "nogui=false" not in content

    def test_returns_correct_path(
        self, generator: Gen5ConfigGenerator, tmp_path: Path
    ) -> None:
        """The returned path should be selena_config.txt inside output_dir."""
        mf4 = tmp_path / "test.mf4"
        mf4.touch()
        out_dir = tmp_path / "my_output"

        cfg_path = generator.generate(str(mf4), str(out_dir))

        expected = str((out_dir / "selena_config.txt").resolve())
        assert cfg_path == expected
