# -*- coding: utf-8 -*-
"""
Pattern Extractor
=================

Mines *temporal behaviour patterns* out of the algorithm C source tree.

Scope
-----
Rather than treating code as a bag of conditions we scan for six generic
shapes that tend to cause data-correlated bugs:

* **HoldRelease** — ``if (cond) { flag = false; time = 0 }`` — a hold is
  broken as soon as ``cond`` becomes true (even momentarily).
* **HoldEntry**   — ``if (cond) { flag = true; time = 0 }`` — a hold is
  latched when ``cond`` first becomes true.
* **Accumulate**  — ``time += dt`` paired with ``time = 0`` in an ``else``
  branch or sibling ``if``.
* **Hysteresis**  — asymmetric enter/exit thresholds acting on the same
  variable.
* **Debounce**    — ``cnt++ / if (cnt >= N)`` style latches.
* **EdgeTrigger** — ``prev == 0 && cur != 0`` predicates.

For the initial release we ship a high-precision regex-only detector for
**HoldRelease** and a lightweight heuristic for **Accumulate** — the two
patterns that are directly implicated by the FCATB001 blind-test case.
The other pattern types are declared in :data:`PATTERN_TYPES` so future
detectors can plug in without touching call sites.

The output is deterministic (identical input → identical output) and is
cached to ``source_docs/code_patterns.json``. AI involvement is intentionally
optional and only used later by ``causal_aligner`` to pretty-print.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Iterable, Optional


__all__ = [
    "CodePattern",
    "PatternExtractor",
    "PATTERN_TYPES",
    "load_patterns",
]


# ── Catalogue of supported pattern types ─────────────────────────────────

PATTERN_TYPES = {
    "HoldRelease":  "if (cond) { flag=false; time=0 } — 保持失效",
    "HoldEntry":    "if (cond) { flag=true; ... }   — 保持进入",
    "Accumulate":   "time += dt 配合 time = 0        — 时间累积器",
    "Hysteresis":   "enter_thresh != exit_thresh    — 阈值迟滞",
    "Debounce":     "cnt++ / if (cnt >= N)          — 防抖计数",
    "EdgeTrigger":  "prev==A && cur==B              — 边沿触发",
}


@dataclass
class CodePattern:
    """One behavioural pattern located in the source code."""

    pattern_type: str
    file: str
    line_start: int
    line_end: int
    function: str = ""
    trigger_condition: str = ""
    trigger_variables: list[str] = field(default_factory=list)
    consequence_variables: list[str] = field(default_factory=list)
    adas_function: str = ""
    snippet: str = ""
    notes: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


# ── Extractor ────────────────────────────────────────────────────────────


class PatternExtractor:
    """
    Scan a source tree and return every :class:`CodePattern` match.

    The extractor is intentionally conservative: it is better to miss a
    pattern than to surface a false positive, because downstream the
    causal aligner will faithfully report "this pattern triggered" as
    evidence.
    """

    TARGET_FILES: list[str] = [
        "coem/GWM_B26/components/AswPerception/func/adasFunc.c",
        "coem/GWM_B26/components/AswIf/ASW_IN/ASWIN_SystemState.c",
        "adas/symmetry/perception/src/objAttribCal.c",
        "adas/symmetry/perception/src/track.c",
    ]

    _FUNC_KEYWORDS = {
        "FCTA": ["fcta", "fctaSkip", "bFcta"],
        "FCTB": ["fctb", "bFctb", "fFctb"],
        "RCTA": ["rcta", "rctaSkip", "bRcta"],
        "RCTB": ["rctb", "bRctb", "fRctb"],
        "BSD":  ["bsd", "bBsd", "bsdSkip"],
        "LCA":  ["lca", "bLca"],
        "DOW":  ["dow", "bDow"],
        "RCW":  ["rcw", "bRcw"],
    }

    _FUNC_BOUNDARY_RE = re.compile(
        r'^(?:static\s+)?(?:inline\s+)?(?:void|bool|int|uint8_t|uint16_t|uint32_t|int8_t|int16_t|int32_t|float|double)\s+'
        r'(\w+)\s*\([^)]*\)\s*(?:\{|$)',
    )

    # ``if (EXPR)`` at any indentation; EXPR captured non-greedily up to the
    # trailing brace / end-of-line. We intentionally allow multi-line EXPR via
    # the flags at match time.
    _IF_RE = re.compile(r'^\s*if\s*\((.+?)\)\s*\{?\s*$')

    _ASSIGN_ZERO_RE = re.compile(
        r'^\s*(\w+(?:\.\w+)?(?:->\w+)?)\s*=\s*(?:\(\s*bool\s*\)\s*)?(?:false|0\.0f|0\.0|0|FALSE)\s*;\s*$',
        re.IGNORECASE,
    )

    _ASSIGN_TRUE_RE = re.compile(
        r'^\s*(\w+(?:\.\w+)?(?:->\w+)?)\s*=\s*(?:\(\s*bool\s*\)\s*)?(?:true|TRUE|1)\s*;\s*$',
    )

    _ACCUMULATE_RE = re.compile(
        r'^\s*(\w+(?:\.\w+)?)\s*\+=\s*[\w.\->]+\s*;\s*$',
    )

    # ``!x``, ``!x.y``, ``!g_X.y.z`` all need to yield the leaf identifier.
    _IDENT_RE = re.compile(r'[A-Za-z_][\w.]*')

    MIN_BODY_SIZE = 2
    MAX_BODY_SCAN = 20

    def __init__(
        self,
        source_root: Path,
        cache_dir: Optional[Path] = None,
        target_files: Optional[Iterable[str]] = None,
    ):
        self.source_root = Path(source_root)
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.target_files = list(target_files) if target_files else list(self.TARGET_FILES)

    def extract_all(self, use_cache: bool = True) -> list[CodePattern]:
        """Run every detector over every target file and aggregate results."""
        if use_cache and self.cache_dir is not None:
            cached = self._load_cached(self._files_hash())
            if cached is not None:
                return cached

        out: list[CodePattern] = []
        for rel in self.target_files:
            full = self.source_root / rel
            if not full.exists():
                continue
            try:
                text = full.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            out.extend(self._scan_file(rel, text))

        if self.cache_dir is not None:
            self._save_cache(out, self._files_hash())
        return out

    def _scan_file(self, rel_path: str, text: str) -> list[CodePattern]:
        lines = text.split("\n")
        patterns: list[CodePattern] = []
        patterns.extend(self._scan_hold_release(rel_path, lines))
        patterns.extend(self._scan_accumulate(rel_path, lines))
        return patterns

    # ── Detector: HoldRelease ────────────────────────────────────────────

    def _scan_hold_release(self, rel_path: str, lines: list[str]) -> list[CodePattern]:
        """Locate ``if(...) { flag=false; time=0; ... }`` blocks.

        Every line is visited once; nested ``if`` statements are therefore
        examined on their own merits. We deduplicate by ``(line_start)``
        in case the regex fires multiple times on the same span.
        """
        patterns: list[CodePattern] = []
        n = len(lines)
        emitted: set[int] = set()

        for i in range(n):
            raw = lines[i]
            stripped = raw.strip()
            if stripped.startswith("//") or stripped.startswith("/*"):
                continue

            if_match = self._IF_RE.match(raw)
            if not if_match:
                continue

            cond_text, cond_end_idx = self._collect_condition(lines, i)
            body_start, body_end = self._find_brace_body(lines, cond_end_idx)
            if body_start is None or body_end is None:
                continue
            if body_end - body_start > self.MAX_BODY_SCAN:
                continue

            body_lines = lines[body_start:body_end + 1]
            zero_assigns = self._collect_zero_assigns(body_lines)
            if len(zero_assigns) < self.MIN_BODY_SIZE:
                continue

            if not self._looks_like_hold_clear(zero_assigns):
                continue
            if (i + 1) in emitted:
                continue

            trigger_vars = self._extract_identifiers(cond_text)
            adas_func = self._guess_adas_function(cond_text, zero_assigns)
            enclosing = self._find_enclosing_function(lines, i)
            snippet = "\n".join(lines[i:body_end + 1])[:800]

            patterns.append(CodePattern(
                pattern_type="HoldRelease",
                file=rel_path,
                line_start=i + 1,
                line_end=body_end + 1,
                function=enclosing,
                trigger_condition=cond_text.strip(),
                trigger_variables=trigger_vars,
                consequence_variables=zero_assigns,
                adas_function=adas_func,
                snippet=snippet,
                notes=("触发条件满足时保持标志位清零 + 累积器归零，"
                       "任何瞬态满足都会打断保持。"),
            ))
            emitted.add(i + 1)

        return patterns

    # ── Detector: Accumulate ─────────────────────────────────────────────

    def _scan_accumulate(self, rel_path: str, lines: list[str]) -> list[CodePattern]:
        """Match ``time += dt;`` adjacent to a ``time = 0;`` reset."""
        patterns: list[CodePattern] = []
        accum_by_var: dict[str, int] = {}
        for idx, raw in enumerate(lines):
            m = self._ACCUMULATE_RE.match(raw)
            if m:
                accum_by_var.setdefault(m.group(1), idx)

        for var, accum_line in accum_by_var.items():
            reset_line = self._find_nearby_reset(lines, var, accum_line,
                                                 radius=30)
            if reset_line is None:
                continue
            start = min(accum_line, reset_line)
            end = max(accum_line, reset_line)
            enclosing = self._find_enclosing_function(lines, start)
            snippet = "\n".join(lines[start:end + 1])[:600]
            adas_func = self._adas_func_for_identifier(var)
            patterns.append(CodePattern(
                pattern_type="Accumulate",
                file=rel_path,
                line_start=start + 1,
                line_end=end + 1,
                function=enclosing,
                trigger_condition=f"{var} += dt ... {var} = 0",
                trigger_variables=[var],
                consequence_variables=[var],
                adas_function=adas_func,
                snippet=snippet,
                notes="时间累积器；被重置的条件一旦频繁触发，累积永远达不到阈值。",
            ))
        return patterns

    # ── Helpers ──────────────────────────────────────────────────────────

    def _collect_condition(
        self, lines: list[str], start: int,
    ) -> tuple[str, int]:
        """Collect a possibly multi-line condition back into one string."""
        raw = lines[start]
        m = self._IF_RE.match(raw)
        if m:
            return m.group(1), start

        chunks = [raw.strip()]
        i = start
        depth = raw.count("(") - raw.count(")")
        while depth > 0 and i + 1 < len(lines):
            i += 1
            chunks.append(lines[i].strip())
            depth += lines[i].count("(") - lines[i].count(")")
        combined = " ".join(chunks)
        parts = combined.split("(", 1)
        if len(parts) == 2:
            inner = parts[1]
            level = 1
            body = []
            for ch in inner:
                if ch == "(":
                    level += 1
                elif ch == ")":
                    level -= 1
                    if level == 0:
                        break
                body.append(ch)
            return "".join(body), i
        return combined, i

    def _find_brace_body(
        self, lines: list[str], start_idx: int,
    ) -> tuple[Optional[int], Optional[int]]:
        """Given the last line of an ``if`` condition, return its ``{..}`` span."""
        open_idx = None
        for k in range(start_idx, min(start_idx + 3, len(lines))):
            if "{" in lines[k]:
                open_idx = k
                break
        if open_idx is None:
            return None, None

        depth = 0
        started = False
        for j in range(open_idx, len(lines)):
            for ch in lines[j]:
                if ch == "{":
                    depth += 1
                    started = True
                elif ch == "}":
                    depth -= 1
                    if started and depth == 0:
                        return open_idx + 1, j - 1
        return None, None

    def _collect_zero_assigns(self, body_lines: list[str]) -> list[str]:
        """Return every variable assigned to zero inside the body."""
        zero_targets: list[str] = []
        for line in body_lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("//"):
                continue
            m = self._ASSIGN_ZERO_RE.match(stripped)
            if m:
                zero_targets.append(m.group(1))
        return zero_targets

    def _looks_like_hold_clear(self, zero_assigns: list[str]) -> bool:
        """HoldRelease has ≥1 bool-ish flag AND ≥1 time-looking accumulator."""
        has_flag = any(self._looks_like_flag(v) for v in zero_assigns)
        has_timer = any(self._looks_like_timer(v) for v in zero_assigns)
        if has_flag and has_timer:
            return True
        return len(zero_assigns) >= 2 and has_flag

    @staticmethod
    def _looks_like_flag(name: str) -> bool:
        leaf = name.split(".")[-1].split("->")[-1].lower()
        return leaf.startswith("b") and any(k in leaf for k in ("flg", "flag", "keep", "enable"))

    @staticmethod
    def _looks_like_timer(name: str) -> bool:
        leaf = name.split(".")[-1].split("->")[-1].lower()
        return leaf.startswith("f") or "time" in leaf or "timer" in leaf or "event" in leaf

    def _extract_identifiers(self, expr: str) -> list[str]:
        """Return leaf identifiers used in ``expr`` (no duplicates)."""
        out: list[str] = []
        for tok in self._IDENT_RE.findall(expr):
            if tok in {"if", "else", "return", "true", "false", "TRUE", "FALSE", "NULL"}:
                continue
            leaf = tok.split(".")[-1]
            if leaf.isdigit():
                continue
            if leaf not in out:
                out.append(leaf)
            if tok not in out:
                out.append(tok)
        return out

    def _find_enclosing_function(self, lines: list[str], target_idx: int) -> str:
        """Return the nearest preceding ``<type> foo(...)`` signature."""
        for k in range(target_idx, max(-1, target_idx - 200), -1):
            m = self._FUNC_BOUNDARY_RE.match(lines[k])
            if m:
                return m.group(1)
        return ""

    def _guess_adas_function(
        self, cond_text: str, zero_assigns: list[str],
    ) -> str:
        """Heuristically tag the pattern with BSD/LCA/FCTA/… by keywords."""
        haystack = cond_text.lower() + " " + " ".join(zero_assigns).lower()
        scores: dict[str, int] = {}
        for func_name, keywords in self._FUNC_KEYWORDS.items():
            hits = sum(1 for kw in keywords if kw.lower() in haystack)
            if hits:
                scores[func_name] = hits
        if not scores:
            return ""
        return max(scores.items(), key=lambda kv: kv[1])[0]

    def _adas_func_for_identifier(self, ident: str) -> str:
        lower = ident.lower()
        for func_name, keywords in self._FUNC_KEYWORDS.items():
            if any(kw.lower() in lower for kw in keywords):
                return func_name
        return ""

    def _find_nearby_reset(
        self, lines: list[str], var: str, accum_line: int, radius: int,
    ) -> Optional[int]:
        """Look for ``var = 0`` within ±radius lines of the ``+=`` occurrence."""
        var_escaped = re.escape(var)
        reset_re = re.compile(
            rf'^\s*{var_escaped}\s*=\s*0(?:\.0f?|u)?\s*;\s*$',
        )
        lo = max(0, accum_line - radius)
        hi = min(len(lines), accum_line + radius + 1)
        for k in range(lo, hi):
            if k == accum_line:
                continue
            if reset_re.match(lines[k]):
                return k
        return None

    # ── Cache ────────────────────────────────────────────────────────────

    def _files_hash(self) -> str:
        h = hashlib.sha1()
        for rel in self.target_files:
            full = self.source_root / rel
            if full.exists():
                try:
                    data = full.read_bytes()
                except Exception:
                    continue
                h.update(rel.encode("utf-8"))
                h.update(hashlib.sha1(data).digest())
        return h.hexdigest()

    def _cache_path(self) -> Optional[Path]:
        if not self.cache_dir:
            return None
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        return self.cache_dir / "code_patterns.json"

    def _load_cached(self, expected_hash: str) -> Optional[list[CodePattern]]:
        path = self._cache_path()
        if not path or not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        if data.get("source_hash") != expected_hash:
            return None
        return [CodePattern(**p) for p in data.get("patterns", [])]

    def _save_cache(self, patterns: list[CodePattern], source_hash: str) -> None:
        path = self._cache_path()
        if not path:
            return
        payload = {
            "source_hash": source_hash,
            "pattern_type_catalogue": PATTERN_TYPES,
            "patterns": [p.to_dict() for p in patterns],
        }
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


# ── Helpers for callers ──────────────────────────────────────────────────


def load_patterns(cache_dir: Path) -> list[CodePattern]:
    """Re-hydrate :class:`CodePattern` objects from the cache file."""
    path = Path(cache_dir) / "code_patterns.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return [CodePattern(**p) for p in data.get("patterns", [])]


def summarise_patterns(patterns: list[CodePattern]) -> str:
    """Condense patterns into a compact overview for expert prompts."""
    if not patterns:
        return "(未识别出时序行为模式)"

    by_type: dict[str, list[CodePattern]] = {}
    for p in patterns:
        by_type.setdefault(p.pattern_type, []).append(p)

    parts: list[str] = [f"### 代码行为模式 ({len(patterns)}处)"]
    for ptype, group in by_type.items():
        parts.append(f"\n**{ptype}** × {len(group)}")
        for p in group[:10]:
            scope = f"{p.file}:{p.line_start}-{p.line_end}"
            if p.function:
                scope += f" ({p.function})"
            parts.append(f"  - {scope}")
            parts.append(f"    ADAS: {p.adas_function or '?'}  "
                         f"触发: `{p.trigger_condition[:80]}`")
            parts.append(f"    清零: {', '.join(p.consequence_variables)}")
    return "\n".join(parts)
