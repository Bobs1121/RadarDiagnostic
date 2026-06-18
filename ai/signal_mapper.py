# -*- coding: utf-8 -*-
"""
Signal Mapper: Extract CAN signal ↔ internal variable mapping from RteComMapping.c.

Uses regex parsing (no AI needed) to build a deterministic bidirectional mapping:
  internal variable name  →  CAN signal name (as in DBC)
  CAN signal name         →  internal variable(s)

The mapping is cached to source_docs/signal_mapping.json and only regenerated
when the source file changes (hash check).
"""
from __future__ import annotations

import datetime
import hashlib
import json
import re
from pathlib import Path

_READ_SIGNAL_RE = re.compile(
    r'^\s*\(void\)\s*RteComMapping_ReadSignal\((\w+)\)\s*\(\s*&\s*(\w+)\s*\)',
)

_ASSIGN_RE = re.compile(
    r'^\s*([\w.]+(?:\[[\w\d]+\])?)\s*=\s*(.+?)\s*;',
)

_WRITE_SIGNAL_RE = re.compile(
    r'\(void\)\s*RteComMapping_WriteSignal\((\w+)\)\((.+)\)\s*;',
)


def _parse_rte_com_mapping(source_text: str) -> list[dict]:
    """Parse active (non-commented) ReadSignal calls and their target assignments."""
    lines = source_text.split("\n")
    mappings: list[dict] = []

    i = 0
    while i < len(lines):
        line = lines[i].strip()

        if line.startswith("//") or line.startswith("/*"):
            i += 1
            continue

        m = _READ_SIGNAL_RE.match(lines[i])
        if not m:
            i += 1
            continue

        can_signal = m.group(1)
        temp_var = m.group(2)

        targets: list[dict] = []
        for j in range(i + 1, min(i + 6, len(lines))):
            nxt = lines[j].strip()
            if not nxt or nxt.startswith("//"):
                continue
            if "RteComMapping_ReadSignal" in nxt:
                break

            am = _ASSIGN_RE.match(nxt)
            if am:
                full_var = am.group(1)
                expr = am.group(2)

                parts = full_var.split(".")
                short_var = parts[-1] if len(parts) > 1 else full_var

                is_boolean = "!= 0" in expr or "== 0" in expr
                is_passthrough = expr.strip() == temp_var
                has_transform = not is_passthrough and not is_boolean

                scaling = _extract_scaling(expr, temp_var)

                targets.append({
                    "full_path": full_var,
                    "short_name": short_var,
                    "transform": "bool" if is_boolean else ("passthrough" if is_passthrough else expr),
                    "scaling": scaling,
                    "data_type": "bool" if is_boolean else ("float" if temp_var == "ftmp" else "uint8"),
                })

        if targets:
            for tgt in targets:
                mappings.append({
                    "can_signal": can_signal,
                    "internal_var": tgt["short_name"],
                    "internal_full_path": tgt["full_path"],
                    "transform": tgt["transform"],
                    "scaling": tgt.get("scaling", ""),
                    "data_type": tgt.get("data_type", "unknown"),
                    "direction": "read",
                })

        i += 1

    return mappings


def _build_indices(mappings: list[dict]) -> dict:
    """Build bidirectional lookup indices, including full-path keys."""
    internal_to_can: dict[str, list[str]] = {}
    can_to_internal: dict[str, list[str]] = {}
    fullpath_to_can: dict[str, list[str]] = {}

    for m in mappings:
        iv = m["internal_var"]
        cs = m["can_signal"]
        fp = m.get("internal_full_path", "")

        internal_to_can.setdefault(iv, [])
        if cs not in internal_to_can[iv]:
            internal_to_can[iv].append(cs)

        can_to_internal.setdefault(cs, [])
        if iv not in can_to_internal[cs]:
            can_to_internal[cs].append(iv)

        if fp:
            fullpath_to_can.setdefault(fp, [])
            if cs not in fullpath_to_can[fp]:
                fullpath_to_can[fp].append(cs)

    return {
        "internal_to_can": internal_to_can,
        "can_to_internal": can_to_internal,
        "fullpath_to_can": fullpath_to_can,
    }


def extract_signal_mapping(
    source_root: Path,
    output_dir: Path,
    rte_file: str = r"coem\GWM_B26\components\AswIf\ASW_IN\RteComMapping.c",
) -> dict:
    """
    Extract signal mapping from RteComMapping.c and cache to signal_mapping.json.

    Returns the full mapping dict with keys:
      - mappings: list of individual mapping entries
      - internal_to_can: {internal_var: [can_signal, ...]}
      - can_to_internal: {can_signal: [internal_var, ...]}
      - source_hash: SHA256 of the source file
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    cache_path = output_dir / "signal_mapping.json"
    rte_path = source_root / rte_file

    if not rte_path.exists():
        return {"mappings": [], "internal_to_can": {}, "can_to_internal": {}}

    source_text = rte_path.read_text(encoding="utf-8", errors="replace")
    source_hash = hashlib.sha256(source_text.encode()).hexdigest()[:16]

    if cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if cached.get("source_hash") == source_hash:
                chain_path = output_dir / "signal_chain.md"
                if not chain_path.exists():
                    build_signal_chain_summary(cached, output_dir)
                return cached
        except (json.JSONDecodeError, KeyError):
            pass

    mappings = _parse_rte_com_mapping(source_text)
    indices = _build_indices(mappings)

    result = {
        "source_hash": source_hash,
        "source_file": rte_file,
        "mapping_count": len(mappings),
        "mappings": mappings,
        **indices,
    }

    cache_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    build_signal_chain_summary(result, output_dir)
    return result


_FUNC_OUTPUT_SIGNALS: dict[str, list[str]] = {
    "FCTB": ["CR_BrkgReq", "CR_BrkgReqVal", "FCTBTrig", "FCTA_Warn", "FCTA_B_FuncSts",
             "CR_FCTB_Resp", "CR_FCTA_Resp", "CR_ErrSts"],
    "FCTA": ["FCTA_Warn", "FCTA_B_FuncSts", "CR_FCTA_Resp", "CR_FCTB_Resp",
             "CR_ErrSts", "CR_BliSts"],
    "RCTB": ["RSDS_BrkgReq", "RSDS_BrkgReqVal", "RSDS_BrkgTrig", "RCTB_State",
             "RSDS_RCTABrkResp", "RCTA_warningReqRight", "RCTA_warningReqLeft",
             "RSDS_ErrSts"],
    "RCTA": ["RCTA_warningReqRight", "RCTA_warningReqLeft", "RCTA_State", "RCTA_B_TTC",
             "RSDS_RCTAResp", "RSDS_CTA_Actv", "RSDS_RCTABrkResp", "RSDS_ErrSts"],
    "BSD":  ["BSD_LCA_warningReqRight", "BSD_LCA_warningReqleft", "BSD_State", "RSDS_ErrSts"],
    "LCA":  ["BSD_LCA_warningReqRight", "BSD_LCA_warningReqleft", "LCA_State", "RSDS_ErrSts"],
    "DOW":  ["DOW_warningReqRight", "DOW_warningReqleft", "DOW_State", "RSDS_ErrSts"],
    "RCW":  ["RSDS_RCW_Trigger", "RCW_State", "RSDS_RCWResp", "RCW_TTC", "RSDS_ErrSts"],
}


def _parse_rte_write_mapping(source_text: str) -> list[dict]:
    """Parse active (non-commented) WriteSignal calls from RteComMapping.c."""
    mappings: list[dict] = []
    for line in source_text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("//"):
            continue
        clean = re.sub(r'//.*$', '', stripped)
        m = _WRITE_SIGNAL_RE.search(clean)
        if m:
            can_signal = m.group(1)
            expression = m.group(2).strip()
            if expression.startswith("(") and expression.endswith(")"):
                expression = expression[1:-1].strip()
            mappings.append({
                "can_signal": can_signal,
                "expression": expression,
                "direction": "write",
            })
    return mappings


def extract_output_signal_mapping(
    source_root: Path,
    output_dir: Path,
    rte_file: str = r"coem\GWM_B26\components\AswIf\ASW_IN\RteComMapping.c",
) -> dict:
    """Extract output (WriteSignal) mapping and cache to output_mapping.json."""
    output_dir.mkdir(parents=True, exist_ok=True)
    cache_path = output_dir / "output_mapping.json"
    rte_path = source_root / rte_file

    if not rte_path.exists():
        return {"mappings": [], "signal_to_expr": {}}

    source_text = rte_path.read_text(encoding="utf-8", errors="replace")
    source_hash = hashlib.sha256(source_text.encode()).hexdigest()[:16]

    if cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if cached.get("source_hash") == source_hash:
                return cached
        except (json.JSONDecodeError, KeyError):
            pass

    mappings = _parse_rte_write_mapping(source_text)
    sig_to_expr: dict[str, list[str]] = {}
    for m in mappings:
        sig_to_expr.setdefault(m["can_signal"], [])
        if m["expression"] not in sig_to_expr[m["can_signal"]]:
            sig_to_expr[m["can_signal"]].append(m["expression"])

    result = {
        "source_hash": source_hash,
        "mapping_count": len(mappings),
        "mappings": mappings,
        "signal_to_expr": sig_to_expr,
    }
    cache_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def get_output_signals_for_function(func_name: str) -> list[str]:
    """Return the list of CAN output signals relevant to a given ADAS function."""
    return _FUNC_OUTPUT_SIGNALS.get(func_name.upper(), [])


def resolve_internal_to_can(
    var_name: str,
    mapping: dict,
    chains: dict | None = None,
    output_mapping: dict | None = None,
    output_aliases: dict | None = None,
) -> list[str]:
    """
    Given an internal variable name, find corresponding CAN signal name(s).

    Resolution order:
      1. Exact match on short name / full path (ReadSignal side)
      2. Last component of dotted path
      3. Struct alias expansion via variable_chains
      4. Case-insensitive match on ReadSignal side
      5. Core keyword substring match (strict: core must be >=5 chars)
      6. L6 ``output_chain.outputs[].internal_var`` mapping (WriteSignal side,
         curated by code_learner)
      7. ``output_mapping.expr_to_can`` reverse index — variable appears as an
         identifier inside a WriteSignal expression (catches short-hop
         intermediates like ``l_temp_u8``)

    The WriteSignal-side sources (6/7) are only consulted when ReadSignal
    resolution fails; they use the same "leaf name + case-insensitive" fallback
    so ``bLcaLeftWarningFlg`` and ``g_xxx.bLcaLeftWarningFlg`` both resolve.
    """
    i2c = mapping.get("internal_to_can", {})
    fp2c = mapping.get("fullpath_to_can", {})

    if var_name in i2c:
        return i2c[var_name]
    if var_name in fp2c:
        return fp2c[var_name]

    parts = var_name.split(".")
    if len(parts) > 1:
        last = parts[-1]
        if last in i2c:
            return i2c[last]
        for fp, cans in fp2c.items():
            if fp.endswith("." + last) or fp == var_name:
                return cans

    aliases = (chains or {}).get("struct_aliases", {})
    if aliases and len(parts) >= 2:
        prefix_candidates = [
            parts[0],
            ".".join(parts[:2]) if len(parts) >= 3 else None,
        ]
        for prefix in prefix_candidates:
            if not prefix:
                continue
            rte_prefix = aliases.get(prefix)
            if rte_prefix:
                field = ".".join(parts[1:]) if prefix == parts[0] else parts[-1]
                aliased_path = f"{rte_prefix}.{field}"
                if aliased_path in fp2c:
                    return fp2c[aliased_path]
                for fp, cans in fp2c.items():
                    if fp.endswith("." + parts[-1]):
                        return cans

    var_lower = var_name.lower()
    last_lower = parts[-1].lower() if len(parts) > 1 else var_lower
    for k, v in i2c.items():
        if k.lower() == last_lower:
            return v

    core = _extract_core_keyword(parts[-1] if len(parts) > 1 else var_name)
    if core and len(core) >= 5:
        for k, v in i2c.items():
            if core.lower() in k.lower() or k.lower() in core.lower():
                return v

    # ── WriteSignal-side fallback (for output variables) ─────────────────
    leaf = parts[-1] if len(parts) > 1 else var_name

    if output_aliases:
        hit = output_aliases.get(var_name) or output_aliases.get(leaf)
        if not hit:
            for k, v in output_aliases.items():
                if k.lower() == leaf.lower():
                    hit = v
                    break
        if hit:
            return list(hit)

    if output_mapping:
        e2c = output_mapping.get("expr_to_can") or {}
        hit = e2c.get(var_name) or e2c.get(leaf)
        if not hit:
            for k, v in e2c.items():
                if k.lower() == leaf.lower():
                    hit = v
                    break
        if hit:
            return list(hit)

    return []


def resolve_can_to_internal(
    can_signal: str,
    mapping: dict,
) -> list[str]:
    """Given a CAN signal name, find corresponding internal variable name(s)."""
    c2i = mapping.get("can_to_internal", {})

    if can_signal in c2i:
        return c2i[can_signal]

    sig_lower = can_signal.lower()
    for k, v in c2i.items():
        if k.lower() == sig_lower:
            return v

    return []


_SCALING_RE = re.compile(r'\*\s*([\d.]+f?|System_\w+)')


def _extract_scaling(expr: str, temp_var: str) -> str:
    """Extract scaling factor from transform expression."""
    if expr.strip() == temp_var:
        return "1:1"
    if "!= 0" in expr or "== 0" in expr:
        return "bool"
    m = _SCALING_RE.search(expr)
    if m:
        factor = m.group(1).rstrip("f")
        return f"*{factor}"
    return ""


def build_signal_chain_summary(mapping: dict, output_dir: Path) -> str:
    """
    Generate source_docs/signal_chain.md from the mapping data.
    Organized by category for human and AI consumption.
    """
    mappings = mapping.get("mappings", [])
    if not mappings:
        return ""

    categories: dict[str, list[dict]] = {
        "vehicle_dynamics": [],
        "function_switches": [],
        "safety_signals": [],
        "door_body": [],
        "wheel_speed": [],
        "other": [],
    }

    _CATEGORY_RULES = {
        "vehicle_dynamics": ["VehSpd", "VehYaw", "VehLat", "VehLgt", "SteerWheel", "AccPed", "Pushrod"],
        "function_switches": ["SwtReq", "Enable", "Switch"],
        "safety_signals": ["AEB", "ESP", "MSR", "VDC", "PTC", "BTC", "ABP", "Diag"],
        "door_body": ["Door", "Turn", "Trailer", "LED", "Blind", "Power"],
        "wheel_speed": ["Wheel"],
    }

    for m in mappings:
        sig = m.get("can_signal", "")
        var = m.get("internal_var", "")
        combined = sig + var
        placed = False
        for cat, keywords in _CATEGORY_RULES.items():
            if any(kw.lower() in combined.lower() for kw in keywords):
                categories[cat].append(m)
                placed = True
                break
        if not placed:
            categories["other"].append(m)

    lines = [
        "# CAN Signal Chain Reference",
        "",
        f"Auto-generated from RteComMapping.c ({mapping.get('mapping_count', 0)} mappings)",
        "",
    ]

    cat_names = {
        "vehicle_dynamics": "Vehicle Dynamics (车辆动力学)",
        "function_switches": "Function Switches (功能开关)",
        "safety_signals": "Safety Systems (安全系统: AEB/ESP/...)",
        "door_body": "Door & Body (车门/车身)",
        "wheel_speed": "Wheel Speed (轮速)",
        "other": "Other (其他)",
    }

    for cat, items in categories.items():
        if not items:
            continue
        lines.append(f"## {cat_names.get(cat, cat)}")
        lines.append("")
        lines.append("| CAN Signal | Internal Variable | Full Path | Type | Transform |")
        lines.append("|------------|-------------------|-----------|------|-----------|")
        for m in sorted(items, key=lambda x: x["can_signal"]):
            cs = m["can_signal"]
            iv = m["internal_var"]
            fp = m["internal_full_path"]
            dt = m.get("data_type", "?")
            sc = m.get("scaling", "") or m.get("transform", "")
            if len(sc) > 30:
                sc = sc[:27] + "..."
            lines.append(f"| {cs} | {iv} | {fp} | {dt} | {sc} |")
        lines.append("")

    content = "\n".join(lines)
    out_path = output_dir / "signal_chain.md"
    out_path.write_text(content, encoding="utf-8")
    return content


_PREFIX_RE = re.compile(r'^[bfug]_?|^(get_rda|set_rda|is_)')
_SUFFIX_RE = re.compile(r'(Flg|Flag|Sts|Status|Valid|Vld|Req|Val)$', re.IGNORECASE)


def _extract_core_keyword(var_name: str) -> str:
    """
    Extract the core semantic keyword from a variable name.
    e.g. 'bAEBIBActiveFlg' → 'AEBIBActive'
         'VCU_APedlPosVld' → 'VCU_APedlPos'
    """
    name = _PREFIX_RE.sub('', var_name)
    name = _SUFFIX_RE.sub('', name)
    return name if len(name) >= 3 else var_name


# ── Variable chain tracing (struct alias discovery) ──────────────────

_STRUCT_COPY_RE = re.compile(
    r'^\s*(g_\w+)\s*=\s*\*(\w+)\s*;',
)
_FUNC_SIG_RE = re.compile(
    r'void\s+(\w+)\s*\(([^)]+)\)',
)
_PARAM_RE = re.compile(
    r'(\w+)\s*\*\s*(\w+)',
)
_DIRECT_ASSIGN_RE = re.compile(
    r'^\s*(g_\w+)\s*=\s*([a-zA-Z_]\w*)\s*;',
)

_CHAIN_FILES = [
    r"adas\symmetry\perception\src\globalVariDef.c",
    r"adas\beamform\perception\src\globalVariDef.c",
]
_CHAIN_FILE_PATTERNS = ["globalVariDef.c", "globalVariDef_*.c"]


def _discover_chain_files(
    source_root: Path,
    extra_files: list[str] | None = None,
) -> list[str]:
    """Auto-discover files likely to contain global variable struct copies.

    Combines hardcoded _CHAIN_FILES, caller-supplied extra_files, and
    auto-discovered files matching _CHAIN_FILE_PATTERNS via rglob.
    """
    known = set(_CHAIN_FILES)
    if extra_files:
        known.update(extra_files)
    try:
        for pat in _CHAIN_FILE_PATTERNS:
            for fp in source_root.rglob(pat):
                try:
                    known.add(str(fp.relative_to(source_root)))
                except ValueError:
                    pass
    except OSError:
        pass
    return sorted(known)


def _match_aliases(
    raw_copies: list[dict],
    rte_prefixes: set[str],
) -> tuple[dict[str, str], dict[str, dict], dict[str, list]]:
    """Multi-strategy alias matching with confidence scoring & conflict resolution.

    Strategies (by confidence):
      100 – param_name exact match in RTE prefix components
       90 – global_var stem (g_ stripped) exact match, when different from param_name
       70 – param_name case-insensitive match in prefix components

    Conflict resolution per global_var:
      - Single prefix candidate → accept
      - Multiple prefixes, one strictly higher confidence → accept winner
      - Tied confidence, different prefixes → mark ambiguous, reject
    """
    per_gv: dict[str, list[tuple[str, int, str]]] = {}

    for c in raw_copies:
        gv = c["global_var"]
        pn = c["param_name"]
        stem = gv[2:] if gv.startswith("g_") else gv

        for pfx in rte_prefixes:
            parts = pfx.split(".")
            if pn in parts:
                per_gv.setdefault(gv, []).append((pfx, 100, "param_exact"))
            elif stem != pn and stem in parts:
                per_gv.setdefault(gv, []).append((pfx, 90, "stem_exact"))
            elif pn.lower() in [p.lower() for p in parts] and pn not in parts:
                per_gv.setdefault(gv, []).append((pfx, 70, "param_icase"))

    aliases: dict[str, str] = {}
    details: dict[str, dict] = {}
    ambiguous: dict[str, list] = {}

    for gv, cands in per_gv.items():
        best: dict[str, tuple[int, str]] = {}
        for pfx, conf, reason in cands:
            if pfx not in best or conf > best[pfx][0]:
                best[pfx] = (conf, reason)

        unique = list(best.keys())
        if len(unique) == 1:
            pfx = unique[0]
            conf, reason = best[pfx]
            aliases[gv] = pfx
            details[gv] = {"rte_prefix": pfx, "confidence": conf, "reason": reason}
        elif len(unique) > 1:
            ranked = sorted(best.items(), key=lambda x: -x[1][0])
            if ranked[0][1][0] > ranked[1][1][0]:
                pfx = ranked[0][0]
                conf, reason = ranked[0][1]
                aliases[gv] = pfx
                details[gv] = {
                    "rte_prefix": pfx,
                    "confidence": conf,
                    "reason": reason,
                    "note": f"won_over_{len(unique) - 1}_alternatives",
                }
            else:
                ambiguous[gv] = [
                    {"prefix": p, "confidence": c, "reason": r}
                    for p, (c, r) in ranked
                ]

    return aliases, details, ambiguous


def trace_variable_chains(
    source_root: Path,
    output_dir: Path,
    rte_file: str = r"coem\GWM_B26\components\AswIf\ASW_IN\RteComMapping.c",
    extra_files: list[str] | None = None,
    force: bool = False,
) -> dict:
    """Trace struct copy chains to build global variable → RTE prefix aliases.

    Phase 1 – Discover: auto-find globalVariDef*.c + hardcoded + extras
    Phase 2 – Parse: extract g_XXX = *param / g_XXX = param patterns
    Phase 3 – Match: multi-strategy scoring (100/90/70)
    Phase 4 – Deduplicate: conflict resolution, ambiguous entries rejected

    Results cached to source_docs/variable_chains.json.
    Per-file SHA256 metadata cached to source_docs/variable_chains.meta.json
    so subsequent calls with unchanged source files skip the full scan.

    Phase 15 (2.1.2): Incremental SHA256 cache — pass ``force=True`` to bypass.
    struct_aliases remains {str: str} for backward compatibility.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    cache_path = output_dir / "variable_chains.json"
    cache_meta_path = output_dir / "variable_chains.meta.json"

    rte_path = source_root / rte_file

    scan_files = _discover_chain_files(source_root, extra_files)

    # ── Incremental cache check (Phase 15 / 2.1.2) ────────────────────
    # If every scanned file's SHA256 matches the recorded hash AND the
    # set of scanned files is unchanged, reuse the cached result.
    # We do this BEFORE any heavy work (rte_prefixes, raw_copies) so
    # that a cache hit truly costs ~file-HMAC operations only.
    if not force and cache_path.exists() and cache_meta_path.exists():
        try:
            cached_meta = json.loads(cache_meta_path.read_text(encoding="utf-8"))
            cached_hashes: dict[str, str] = cached_meta.get("file_hashes", {})
            current_hashes: dict[str, str] = {}
            all_match = True
            for rel in scan_files:
                fp = source_root / rel
                if not fp.exists():
                    # File absent in source tree (e.g. _CHAIN_FILES hardcoded
                    # path that doesn't exist in this checkout). Don't fail
                    # the cache check just because of an irrelevant missing
                    # entry — skip it. meta writes also skip non-existent
                    # files, so they never appear in cached_hashes.
                    continue
                h = hashlib.sha256(fp.read_bytes()).hexdigest()[:16]
                current_hashes[rel] = h
                if cached_hashes.get(rel) != h:
                    all_match = False
                    break
            # Existing file that was in cache has now disappeared → invalidate
            existing_files = {rel for rel in scan_files
                              if (source_root / rel).exists()}
            if all_match and existing_files != set(cached_hashes.keys()):
                all_match = False
            # RTE file itself unchanged
            rte_now = (
                hashlib.sha256(rte_path.read_bytes()).hexdigest()[:16]
                if rte_path.exists() else ""
            )
            if cached_meta.get("rte_hash") != rte_now:
                all_match = False
            if all_match:
                return json.loads(cache_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, KeyError):
            # Corrupted cache → fall through to full scan
            pass

    rte_prefixes = _extract_rte_write_prefixes(rte_path) if rte_path.exists() else set()

    raw_copies: list[dict] = []
    for rel in scan_files:
        fp = source_root / rel
        if not fp.exists():
            continue
        text = fp.read_text(encoding="utf-8", errors="replace")
        copies = _parse_struct_copies(text)
        for c in copies:
            c["source_file"] = rel
        raw_copies.extend(copies)

    aliases, alias_details, ambiguous = _match_aliases(raw_copies, rte_prefixes)

    result = {
        "struct_aliases": aliases,
        "alias_details": alias_details,
        "ambiguous": ambiguous,
        "raw_copies": raw_copies,
        "rte_write_prefixes": sorted(rte_prefixes),
        "scanned_files": scan_files,
    }

    cache_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # ── Write per-file SHA256 metadata for next call's cache check ────
    # Best-effort: a failure here doesn't affect diagnostic correctness;
    # it just means the next call will re-scan.
    try:
        file_hashes: dict[str, str] = {}
        for rel in scan_files:
            fp = source_root / rel
            if fp.exists():
                file_hashes[rel] = hashlib.sha256(fp.read_bytes()).hexdigest()[:16]
        meta = {
            "file_hashes": file_hashes,
            "updated_at": datetime.datetime.now().isoformat(),
            "rte_file": rte_file,
            "rte_hash": (
                hashlib.sha256(rte_path.read_bytes()).hexdigest()[:16]
                if rte_path.exists() else ""
            ),
            "alias_count": len(result.get("struct_aliases", {})),
            "version": 1,
        }
        cache_meta_path.write_text(
            json.dumps(meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass  # meta is best-effort

    return result


def _extract_rte_write_prefixes(rte_path: Path) -> set[str]:
    """Extract unique struct prefixes from RteComMapping.c write targets."""
    text = rte_path.read_text(encoding="utf-8", errors="replace")
    prefixes: set[str] = set()
    for line in text.split("\n"):
        m = _ASSIGN_RE.match(line.strip())
        if m:
            full_var = m.group(1)
            parts = full_var.split(".")
            if len(parts) >= 2:
                prefixes.add(".".join(parts[:-1]))
    return prefixes


def _parse_struct_copies(text: str) -> list[dict]:
    """Parse struct copy patterns within function bodies.

    Matches two forms:
      - Pointer dereference: g_XXX = *param;
      - Direct parameter assign: g_XXX = param;  (only when RHS is a
        known function parameter, avoiding false positives like g_flag = 0)
    """
    lines = text.split("\n")
    results: list[dict] = []
    current_func = ""
    current_params: dict[str, str] = {}

    for line in lines:
        fm = _FUNC_SIG_RE.search(line)
        if fm:
            current_func = fm.group(1)
            current_params = {}
            for pm in _PARAM_RE.finditer(fm.group(2)):
                type_name, param_name = pm.group(1), pm.group(2)
                current_params[param_name] = type_name

        cm = _STRUCT_COPY_RE.match(line)
        if cm:
            global_var = cm.group(1)
            param_name = cm.group(2)
            param_type = current_params.get(param_name, "unknown")
            results.append({
                "global_var": global_var,
                "param_name": param_name,
                "param_type": param_type,
                "function": current_func,
                "copy_type": "deref",
            })
            continue

        dm = _DIRECT_ASSIGN_RE.match(line)
        if dm:
            global_var = dm.group(1)
            rhs = dm.group(2)
            if rhs in current_params:
                results.append({
                    "global_var": global_var,
                    "param_name": rhs,
                    "param_type": current_params[rhs],
                    "function": current_func,
                    "copy_type": "direct",
                })

    return results


def load_variable_chains(output_dir: Path) -> dict:
    """Load cached variable chains, return empty dict if not found."""
    cache_path = output_dir / "variable_chains.json"
    if cache_path.exists():
        try:
            return json.loads(cache_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, KeyError):
            pass
    return {"struct_aliases": {}, "raw_copies": [], "rte_write_prefixes": []}


# ── WriteSignal-side resolution helpers ───────────────────────────────

_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

_EXPR_SKIP = {
    # Keywords / common helpers that are not variables we'd want to resolve.
    "if", "else", "return", "void", "uint8", "uint16", "uint32", "int8",
    "int16", "int32", "float", "double", "bool", "true", "false", "TRUE",
    "FALSE", "NULL", "static", "const", "sizeof", "u8", "u16", "u32",
}


def build_expr_to_can_index(output_mapping: dict) -> dict[str, list[str]]:
    """Build a reverse index from identifier → CAN signals that use it.

    ``output_mapping.signal_to_expr`` maps ``CAN signal → [expr, ...]`` for
    every ``RteComMapping_WriteSignal(sig)(expr)`` call. We scan each
    expression for identifiers (``l_temp_u8``, ``GetRL_BsdLca_Warning``, ...)
    and add them to the reverse index. One identifier can map to multiple CAN
    signals (e.g. a shared temp variable); that's fine, callers treat the
    result as a candidate set.

    This is side-effect free and cached back into ``output_mapping`` so we
    don't rebuild it per call.
    """
    if not output_mapping:
        return {}
    if isinstance(output_mapping.get("expr_to_can"), dict):
        return output_mapping["expr_to_can"]

    index: dict[str, list[str]] = {}
    sig_to_expr = output_mapping.get("signal_to_expr") or {}
    for can_sig, exprs in sig_to_expr.items():
        # ``signal_to_expr`` values may be a single expression string or a
        # list of expressions, depending on when the cache was produced.
        # Normalise to an iterable.
        if isinstance(exprs, str):
            expr_iter: list[str] = [exprs]
        elif isinstance(exprs, list):
            expr_iter = [e for e in exprs if isinstance(e, str)]
        else:
            continue
        for expr in expr_iter:
            for m in _IDENT_RE.finditer(expr):
                tok = m.group(0)
                if tok in _EXPR_SKIP:
                    continue
                if tok.isdigit():
                    continue
                bucket = index.setdefault(tok, [])
                if can_sig not in bucket:
                    bucket.append(can_sig)

    output_mapping["expr_to_can"] = index
    return index


def load_output_chain_aliases(knowledge_dir: Path) -> dict[str, list[str]]:
    """Scan ``memory/code_knowledge/*.json`` and extract curated
    ``internal_var → can_signal`` aliases from every function's
    ``output_chain.outputs[]`` list.

    This is the high-confidence path: each entry is a single LLM-confirmed
    mapping (e.g. ``bFctbKeepBrakeFlg → CR_BrkgReq``) so we trust it over the
    heuristic ``expr_to_can`` index when both hit.

    Non-function files (``constants.json``, ``learning_state.json``) are
    skipped — they don't carry an ``output_chain`` key anyway, so an explicit
    allowlist isn't needed.
    """
    aliases: dict[str, list[str]] = {}
    if not knowledge_dir or not Path(knowledge_dir).exists():
        return aliases

    for fp in Path(knowledge_dir).glob("*.json"):
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(data, dict):
            continue
        outputs = ((data.get("output_chain") or {}).get("outputs")) or []
        if not isinstance(outputs, list):
            continue
        for item in outputs:
            if not isinstance(item, dict):
                continue
            iv = item.get("internal_var")
            cs = item.get("can_signal")
            if not iv or not cs:
                continue
            bucket = aliases.setdefault(iv, [])
            if cs not in bucket:
                bucket.append(cs)

    return aliases


# ── Unresolved-variable classifier ────────────────────────────────────

# Heuristic patterns for *intentionally internal* variables: FIFO buffers,
# cursor indices, aggregate counters, local temps. These **never** have a
# CAN mapping by design, so classifying them as "internal_only" lets TPE
# stop reporting them as unresolved and cluttering the expert log.
_INTERNAL_ONLY_RE = re.compile(
    r"""(?x)
    ^total[A-Z][A-Za-z]*State$         # totalLeftLcaWarningState (FIFO sum)
    | Buffer$                          # bLcaLeftBuffer, warningBuffer, ...
    | UseLoc$                          # bLcaLeftUseLoc (FIFO cursor)
    | Counter$ | Cnt$                  # ttlCounter, errCnt, ...
    | ^l_(temp|tmp)_                   # AUTOSAR local temps l_temp_u8
    | ^s_(temp|tmp)_                   #   & static versions
    | (Idx|_idx|_index)$               # loop indices / cursors (bufferIdx, ..)
    | ^loc_                            # locXxx loop-scoped vars
    """,
)


def classify_unresolved(var_name: str) -> str:
    """Return ``"internal_only"`` if *var_name* looks like a FIFO buffer /
    counter / local temp — otherwise ``"unknown"``.

    The classifier is deliberately conservative: we'd rather let a real
    unmapped variable fall through to ``unknown`` than silently hide a
    variable that *should* have a CAN signal.
    """
    if not var_name:
        return "unknown"
    leaf = var_name.split(".")[-1]
    return "internal_only" if _INTERNAL_ONLY_RE.search(leaf) else "unknown"
