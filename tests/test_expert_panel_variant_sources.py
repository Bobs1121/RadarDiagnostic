# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from ai.expert_panel import EXPERTS, ExpertPanel


class _Router:
    thinking_mode = "off"


def test_expert_panel_reads_effective_variant_domains_not_legacy_global(tmp_path: Path):
    source_root = tmp_path / "source"
    byd_rte = source_root / "coem" / "BYD_SC6H" / "components" / "AswIf" / "ASW_ComMapping" / "RteComMapping.c"
    gwm_rte = source_root / "coem" / "GWM_B26" / "components" / "AswIf" / "ASW_IN" / "RteComMapping.c"
    byd_rte.parent.mkdir(parents=True)
    gwm_rte.parent.mkdir(parents=True)
    byd_rte.write_text("/* CURRENT_BYD_SIGNAL_MAP */\n", encoding="utf-8")
    gwm_rte.write_text("/* STALE_GWM_SIGNAL_MAP */\n", encoding="utf-8")
    config = {
        "default_variant": "gen6/byd_sc6h",
        "paths": {"source_code": str(source_root)},
        "source_domains": {
            "signal_chain": ["coem/GWM_B26/components/AswIf/ASW_IN/RteComMapping.c"],
        },
        "codebases": {"byd": {"root_path": str(source_root)}},
        "variants": {
            "gen6/byd_sc6h": {
                "codebase_id": "byd",
                "source_domains": {
                    "signal_chain": [
                        "coem/BYD_SC6H/components/AswIf/ASW_ComMapping/RteComMapping.c",
                    ],
                },
            },
        },
    }

    panel = ExpertPanel(_Router(), config, tmp_path)
    source = panel._load_expert_sources(EXPERTS["signal_chain"])

    assert "CURRENT_BYD_SIGNAL_MAP" in source
    assert "STALE_GWM_SIGNAL_MAP" not in source
    assert "g_GWMSpecificVariant" not in EXPERTS["signal_chain"]["system"]
