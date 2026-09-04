# -*- coding: utf-8 -*-
"""
SignalBridgeModule (M2) — deterministic CAN/internal signal resolution without
recorded data.

This standalone wrapper exposes the signal-mapper utilities as a stable V3
module boundary. It can work entirely offline with injected mapping dicts, or
load/calculate mapping caches from a source tree when paths are provided.

Run standalone::

    python cli.py signal-bridge --mode mapping-summary --output-dir source_docs
    python cli.py signal-bridge --mode internal-to-can --query bLcaLeftWarningFlg

or from Python::

    from ai.modules.signal_bridge import SignalBridgeModule
    mod = SignalBridgeModule(mapping=my_mapping, chains=my_chains)
    res = mod.safe_run(mode="can-to-internal", query="FCTA_Warn")
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Mapping

from engines.signal_mapper import (
    build_expr_to_can_index,
    extract_output_signal_mapping,
    extract_signal_mapping,
    get_output_signals_for_function,
    load_output_chain_aliases,
    load_variable_chains,
    resolve_can_to_internal,
    resolve_internal_to_can,
    trace_variable_chains,
)
from .base import BaseModule, ModuleResult

log = logging.getLogger(__name__)

DEFAULT_RTE_FILE = r"coem\GWM_B26\components\AswIf\ASW_IN\RteComMapping.c"
BRIDGE_MODES: tuple[str, ...] = (
    "mapping-summary",
    "internal-to-can",
    "can-to-internal",
    "function-outputs",
)


def _empty_mapping() -> dict[str, Any]:
    return {
        "mappings": [],
        "internal_to_can": {},
        "can_to_internal": {},
        "fullpath_to_can": {},
    }


def _empty_chains() -> dict[str, Any]:
    return {
        "struct_aliases": {},
        "raw_copies": [],
        "rte_write_prefixes": [],
    }


def _empty_output_mapping() -> dict[str, Any]:
    return {
        "mappings": [],
        "signal_to_expr": {},
        "expr_to_can": {},
    }


def _load_json_dict(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


class SignalBridgeModule(BaseModule):
    """M2 — deterministic bridge between internal variables and CAN signals."""

    name = "signal-bridge"
    description = "Resolve CAN/internal signal mappings without recorded data (M2)"

    def __init__(
        self,
        *,
        mapping: dict[str, Any] | None = None,
        chains: dict[str, Any] | None = None,
        output_mapping: dict[str, Any] | None = None,
        output_aliases: dict[str, list[str]] | None = None,
        source_root: str | Path | None = None,
        output_dir: str | Path | None = None,
        knowledge_dir: str | Path | None = None,
        rte_file: str = DEFAULT_RTE_FILE,
    ) -> None:
        self._mapping = mapping
        self._chains = chains
        self._output_mapping = output_mapping
        self._output_aliases = output_aliases
        self._source_root = Path(source_root) if source_root else None
        self._output_dir = Path(output_dir) if output_dir else None
        self._knowledge_dir = Path(knowledge_dir) if knowledge_dir else None
        self._rte_file = rte_file

    def _get_mapping(self) -> tuple[dict[str, Any], str]:
        if self._mapping is not None:
            return self._mapping, "injected"
        if self._source_root is not None and self._output_dir is not None:
            try:
                self._mapping = extract_signal_mapping(
                    self._source_root,
                    self._output_dir,
                    rte_file=self._rte_file,
                )
                return self._mapping, "source"
            except Exception:
                log.exception("extract_signal_mapping failed")
        if self._output_dir is not None:
            cached = _load_json_dict(self._output_dir / "signal_mapping.json")
            if cached is not None:
                self._mapping = cached
                return cached, "cache"
        return _empty_mapping(), "missing"

    def _get_chains(self) -> tuple[dict[str, Any], str]:
        if self._chains is not None:
            return self._chains, "injected"
        if self._source_root is not None and self._output_dir is not None:
            try:
                self._chains = trace_variable_chains(
                    self._source_root,
                    self._output_dir,
                    rte_file=self._rte_file,
                )
                return self._chains, "source"
            except Exception:
                log.exception("trace_variable_chains failed")
        if self._output_dir is not None:
            cache_path = self._output_dir / "variable_chains.json"
            if cache_path.exists():
                self._chains = load_variable_chains(self._output_dir)
                return self._chains, "cache"
        return _empty_chains(), "missing"

    def _get_output_mapping(self) -> tuple[dict[str, Any], str]:
        output_mapping: dict[str, Any]
        source = "missing"
        if self._output_mapping is not None:
            output_mapping = self._output_mapping
            source = "injected"
        elif self._source_root is not None and self._output_dir is not None:
            try:
                output_mapping = extract_output_signal_mapping(
                    self._source_root,
                    self._output_dir,
                    rte_file=self._rte_file,
                )
                self._output_mapping = output_mapping
                source = "source"
            except Exception:
                log.exception("extract_output_signal_mapping failed")
                output_mapping = _empty_output_mapping()
        elif self._output_dir is not None:
            cached = _load_json_dict(self._output_dir / "output_mapping.json")
            if cached is not None:
                output_mapping = cached
                self._output_mapping = cached
                source = "cache"
            else:
                output_mapping = _empty_output_mapping()
        else:
            output_mapping = _empty_output_mapping()

        try:
            build_expr_to_can_index(output_mapping)
        except Exception:
            log.exception("build_expr_to_can_index failed")
        return output_mapping, source

    def _get_output_aliases(self) -> tuple[dict[str, list[str]], str]:
        if self._output_aliases is not None:
            return self._output_aliases, "injected"
        if self._knowledge_dir is not None:
            try:
                self._output_aliases = load_output_chain_aliases(self._knowledge_dir)
                return self._output_aliases, "knowledge"
            except Exception:
                log.exception("load_output_chain_aliases failed")
        return {}, "missing"

    @staticmethod
    def _has_forward_resolution_data(
        mapping: dict[str, Any],
        output_mapping: dict[str, Any],
        output_aliases: dict[str, list[str]],
    ) -> bool:
        return bool(
            mapping.get("internal_to_can")
            or mapping.get("fullpath_to_can")
            or output_mapping.get("expr_to_can")
            or output_aliases
        )

    @staticmethod
    def _build_summary(
        *,
        mapping: dict[str, Any],
        chains: dict[str, Any],
        output_mapping: dict[str, Any],
        output_aliases: dict[str, list[str]],
        sources: dict[str, str],
    ) -> dict[str, Any]:
        can_signals = sorted((mapping.get("can_to_internal") or {}).keys())
        internal_vars = sorted((mapping.get("internal_to_can") or {}).keys())
        return {
            "mode": "mapping-summary",
            "available": bool(
                mapping.get("mappings")
                or mapping.get("internal_to_can")
                or output_mapping.get("signal_to_expr")
                or output_aliases
            ),
            "mapping_count": mapping.get("mapping_count", len(mapping.get("mappings", []))),
            "read_signal_count": len(can_signals),
            "internal_variable_count": len(internal_vars),
            "fullpath_count": len(mapping.get("fullpath_to_can", {})),
            "struct_alias_count": len(chains.get("struct_aliases", {})),
            "write_signal_count": len(output_mapping.get("signal_to_expr", {})),
            "expr_identifier_count": len(output_mapping.get("expr_to_can", {})),
            "output_alias_count": len(output_aliases),
            "sample_can_signals": can_signals[:5],
            "sample_internal_vars": internal_vars[:5],
            "sources": sources,
        }

    def run(
        self,
        *,
        mode: str,
        query: str = "",
        func_name: str = "",
        **_: Any,
    ) -> ModuleResult:
        if mode not in BRIDGE_MODES:
            return ModuleResult.fail(
                f"unknown mode {mode!r}; choose one of {list(BRIDGE_MODES)}",
                module=self.name,
            )

        mapping, mapping_source = self._get_mapping()
        chains, chains_source = self._get_chains()
        output_mapping, output_mapping_source = self._get_output_mapping()
        output_aliases, output_aliases_source = self._get_output_aliases()
        sources = {
            "mapping": mapping_source,
            "chains": chains_source,
            "output_mapping": output_mapping_source,
            "output_aliases": output_aliases_source,
        }

        if mode == "mapping-summary":
            return ModuleResult.success(
                message="signal-bridge:mapping-summary",
                module=self.name,
                data=self._build_summary(
                    mapping=mapping,
                    chains=chains,
                    output_mapping=output_mapping,
                    output_aliases=output_aliases,
                    sources=sources,
                ),
            )

        if mode == "function-outputs":
            func_name = (func_name or query).strip()
            if not func_name:
                return ModuleResult.fail(
                    "mode 'function-outputs' requires 'func_name' or 'query'",
                    module=self.name,
                )
            # The active variant's Tx mapping is authoritative.  Falling
            # back to the legacy compatibility table is allowed only when the
            # source mapping has no matching expression.
            outputs = get_output_signals_for_function(
                func_name,
                tx_signals=output_mapping.get("signal_to_expr") if isinstance(output_mapping, Mapping) else None,
            )
            return ModuleResult.success(
                message="signal-bridge:function-outputs",
                module=self.name,
                data={
                    "mode": mode,
                    "query": func_name,
                    "matches": outputs,
                    "match_count": len(outputs),
                    "sources": sources,
                },
            )

        query = query.strip()
        if not query:
            return ModuleResult.fail(
                f"mode {mode!r} requires 'query'",
                module=self.name,
            )

        if mode == "internal-to-can":
            if not self._has_forward_resolution_data(
                mapping, output_mapping, output_aliases,
            ):
                return ModuleResult.fail(
                    "no signal bridge data available; pass mapping/output_mapping/"
                    "output_aliases or source_root+output_dir",
                    module=self.name,
                )
            matches = resolve_internal_to_can(
                query,
                mapping,
                chains=chains,
                output_mapping=output_mapping,
                output_aliases=output_aliases,
            )
            return ModuleResult.success(
                message="signal-bridge:internal-to-can",
                module=self.name,
                data={
                    "mode": mode,
                    "query": query,
                    "matches": matches,
                    "match_count": len(matches),
                    "sources": sources,
                },
            )

        if not mapping.get("can_to_internal"):
            return ModuleResult.fail(
                "no reverse CAN mapping available; pass mapping=... or "
                "source_root+output_dir",
                module=self.name,
            )
        matches = resolve_can_to_internal(query, mapping)
        return ModuleResult.success(
            message="signal-bridge:can-to-internal",
            module=self.name,
            data={
                "mode": mode,
                "query": query,
                "matches": matches,
                "match_count": len(matches),
                "sources": sources,
            },
        )

    @classmethod
    def register_cli(cls, subparsers: Any) -> Any:
        parser = super().register_cli(subparsers)
        parser.add_argument(
            "--mode",
            required=True,
            choices=list(BRIDGE_MODES),
            help="Bridge operation to run.",
        )
        parser.add_argument(
            "--query",
            default="",
            help="Internal variable, CAN signal, or function name depending on --mode.",
        )
        parser.add_argument(
            "--func-name",
            default="",
            help="Function name for --mode function-outputs.",
        )
        parser.add_argument(
            "--source-root",
            default=None,
            help="Source tree root used to extract fresh signal mappings.",
        )
        parser.add_argument(
            "--output-dir",
            default=None,
            help="Directory containing signal_mapping.json and related caches.",
        )
        parser.add_argument(
            "--knowledge-dir",
            default=None,
            help="Directory containing code_knowledge JSON files for output aliases.",
        )
        parser.add_argument(
            "--rte-file",
            default=DEFAULT_RTE_FILE,
            help="Relative path to RteComMapping.c within --source-root.",
        )
        return parser

    @classmethod
    def from_cli_args(cls, args: Any) -> "SignalBridgeModule":
        return cls(
            source_root=getattr(args, "source_root", None),
            output_dir=getattr(args, "output_dir", None),
            knowledge_dir=getattr(args, "knowledge_dir", None),
            rte_file=getattr(args, "rte_file", DEFAULT_RTE_FILE),
        )
