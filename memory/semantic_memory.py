# -*- coding: utf-8 -*-
"""
Semantic Memory (M5) — vector-similarity recall for the Corner Radar Analyzer.

This is a *purely additive* layer that complements the existing keyword-only
JSON memory (``memory/memory_system.py`` layers L1-L6). It does **not** modify
or depend on the runtime behaviour of that module; it simply provides a second
recall channel: "find past triage records whose *meaning* is close to this
query", which keyword/set-intersection matching cannot do.

Backends
--------
* **lancedb** — used automatically when the optional ``lancedb`` package is
  importable. Records are stored in an on-disk LanceDB table and searched with
  cosine distance.
* **fallback** — a dependency-free, pure-Python cosine store persisted to a
  single JSON file (``<store_dir>/fallback_vectors.json``). Used whenever
  ``lancedb`` is absent *or* fails to initialise. Everything works fully
  offline with zero models installed.

The active backend is exposed via the :attr:`SemanticMemory.backend` attribute
(``"lancedb"`` or ``"fallback"``) so callers and tests can assert which path is
live.

Embedding
---------
The embedder is pluggable via the constructor's ``embedder`` argument
(``Callable[[str], list[float]]``). When it is ``None`` a deterministic,
dependency-free *feature-hashing* embedder is used so that similarity works
offline with no model downloads. A real local embedding model (e.g. a small
sentence-transformer or an ONNX/GGUF encoder) can be injected later by passing
it as ``embedder`` — no other code needs to change.

Isolation
---------
There is no global state. The store location is injected
(``store_dir``), so each workspace/variant keeps its own semantic index. Use
``SemanticMemory.for_variant(project_root, variant)`` to place the index at the
V3 workspace path ``.workspaces/<sanitized-variant>/memory/lancedb/``.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

__all__ = ["SemanticMemory"]

# ── Optional dependency: lancedb ─────────────────────────────────────────
#
# The whole point of the fallback backend is that this import may fail. We
# probe it once at module load and record the result; ``SemanticMemory``
# re-reads this flag at construction time so tests can monkeypatch it.
try:  # pragma: no cover - trivial import guard
    import lancedb  # type: ignore

    _HAS_LANCEDB = True
except Exception:  # pragma: no cover - depends on the environment
    lancedb = None  # type: ignore
    _HAS_LANCEDB = False


_FALLBACK_FILENAME = "fallback_vectors.json"


# ── Small, self-contained helpers (no dependency on memory_system.py) ────

def _atomic_write_json(path: Path, data: object) -> None:
    """Atomically write ``data`` as JSON to ``path`` (``.tmp`` -> ``os.replace``).

    Mirrors the atomic-write convention used across ``memory/`` so a crash
    mid-write leaves the previous file intact rather than a truncated one.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    payload = json.dumps(data, ensure_ascii=False, default=str)
    try:
        with open(tmp, "w", encoding="utf-8", newline="") as f:
            f.write(payload)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                # fsync unsupported on this platform; best-effort only.
                pass
        os.replace(tmp, path)
    except Exception:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
        raise


def _tokenize(text: str) -> list[str]:
    """Split ``text`` into ASCII alphanumeric words and individual CJK chars.

    ADAS symptoms mix English signal names (``AEBBAActv``) with Chinese prose,
    and Chinese has no whitespace, so each CJK character becomes its own token
    to give the hashing embedder something to differentiate.
    """
    return re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]", text.lower())


def _l2_normalize(vec: list[float]) -> list[float]:
    """Return ``vec`` scaled to unit L2 norm; a zero vector is returned as-is."""
    norm = math.sqrt(sum(x * x for x in vec))
    if norm <= 0.0:
        return vec
    return [x / norm for x in vec]


def _cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity of two vectors, guarding against zero-norm inputs."""
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return dot / math.sqrt(na * nb)


def _variant_workspace_name(variant: object) -> str:
    """Return the Workspace-compatible sandbox name for a Variant or id string."""
    variant_id = getattr(variant, "variant_id", None) or str(variant)
    return variant_id.replace("/", "_").replace("\\", "_")


class SemanticMemory:
    """Vector-similarity store for past diagnosis / triage records.

    Parameters
    ----------
    store_dir:
        Directory that owns this semantic index. Created if missing. Passing a
        workspace-scoped path keeps per-project isolation (no global state).
    embedder:
        Optional ``Callable[[str], list[float]]``. When ``None`` a deterministic
        feature-hashing embedder of dimension ``dim`` is used so the store works
        offline with zero models. Inject a real local embedding model here later.
    dim:
        Dimension of the default hashing embedder. Ignored for the length of an
        injected embedder's output, but the injected output length should be
        stable across calls (LanceDB requires a fixed vector width).
    table:
        Logical table name (LanceDB table / namespace label for the fallback).

    Attributes
    ----------
    backend:
        ``"lancedb"`` when the LanceDB backend is active, otherwise
        ``"fallback"``.
    """

    def __init__(
        self,
        store_dir: Path | str,
        embedder: Optional[Callable[[str], list[float]]] = None,
        dim: int = 256,
        table: str = "triage_history",
    ) -> None:
        self.store_dir = Path(store_dir)
        self.store_dir.mkdir(parents=True, exist_ok=True)
        self._embedder = embedder
        self.dim = int(dim)
        self.table = table

        # Content ids seen so far (dedup + count), maintained for both backends.
        self._ids: set[str] = set()

        # LanceDB handles (populated only when the lancedb backend is live).
        self._db = None
        self._tbl = None

        # Fallback in-memory records: each is a full row incl. its vector.
        self._fallback_path = self.store_dir / _FALLBACK_FILENAME
        self._records: list[dict] = []

        # Re-read the module flag at construction time so tests can force the
        # fallback path via monkeypatch even in environments with lancedb.
        self.backend = "fallback"
        if _HAS_LANCEDB:
            try:
                self._init_lancedb()
                self.backend = "lancedb"
            except Exception as exc:  # pragma: no cover - env dependent
                logger.warning(
                    "lancedb backend init failed (%s); using fallback store", exc
                )
                self.backend = "fallback"

        if self.backend == "fallback":
            self._load_fallback()

        logger.debug(
            "SemanticMemory ready: backend=%s dim=%d table=%s store=%s count=%d",
            self.backend, self.dim, self.table, self.store_dir, len(self._ids),
        )

    @classmethod
    def for_variant(
        cls,
        project_root: Path | str,
        variant: object,
        *,
        embedder: Optional[Callable[[str], list[float]]] = None,
        dim: int = 256,
        table: str = "triage_history",
    ) -> "SemanticMemory":
        """Create a semantic store under the V3 workspace sandbox for ``variant``.

        The path mirrors ``core.workspace.Workspace.from_variant``:
        ``<project_root>/.workspaces/<variant_id with slashes as _>/memory/lancedb``.
        Accepts either a ``Variant``-like object with ``.variant_id`` or a plain
        variant-id string.
        """
        return cls(
            store_dir=cls.store_dir_for_variant(project_root, variant),
            embedder=embedder,
            dim=dim,
            table=table,
        )

    @staticmethod
    def store_dir_for_variant(project_root: Path | str, variant: object) -> Path:
        """Return the V3 variant-scoped semantic-memory directory."""
        return (
            Path(project_root)
            / ".workspaces"
            / _variant_workspace_name(variant)
            / "memory"
            / "lancedb"
        )

    # ── Shared logic (embedding + dedup id) ─────────────────────────────

    def _embed(self, text: str) -> list[float]:
        """Embed ``text`` into a vector using the injected or default embedder."""
        if self._embedder is not None:
            try:
                vec = [float(x) for x in self._embedder(text)]
                return vec
            except Exception as exc:  # pragma: no cover - user embedder bug
                logger.warning("injected embedder failed (%s); using default", exc)
        return self._hash_embed(text)

    def _hash_embed(self, text: str) -> list[float]:
        """Deterministic, dependency-free feature-hashing embedder (L2-normed).

        Uses MD5 (stable across processes, unlike the salted built-in ``hash``)
        to map each token to a bucket and a sign, then L2-normalizes. Purely a
        zero-dependency offline default — not a semantic model.
        """
        vec = [0.0] * self.dim
        for tok in _tokenize(text):
            digest = hashlib.md5(tok.encode("utf-8")).digest()
            idx = int.from_bytes(digest[:4], "big") % self.dim
            sign = 1.0 if (digest[4] & 1) else -1.0
            vec[idx] += sign
        return _l2_normalize(vec)

    @staticmethod
    def _compose(symptom: str, signal: str, code_line: str, conclusion: str) -> str:
        """Compose the canonical text that is embedded and hashed for the id."""
        return f"{symptom}\n{signal}\n{code_line}\n{conclusion}"

    @staticmethod
    def _payload_id(text: str) -> str:
        """Stable content id = first 12 hex chars of ``sha1(text)`` (dedup key)."""
        return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]

    # ── Public API ──────────────────────────────────────────────────────

    def add(
        self,
        *,
        symptom: str,
        signal: str = "",
        code_line: str = "",
        conclusion: str = "",
        metadata: dict | None = None,
    ) -> str:
        """Embed and store a triage record; return its content id.

        The id is ``sha1[:12]`` of the composed ``symptom/signal/code_line/
        conclusion`` text (metadata is *not* part of the dedup key). If a record
        with the same id already exists it is left untouched and its id is
        returned, so calling ``add`` twice with identical content is a no-op.
        """
        text = self._compose(symptom, signal, code_line, conclusion)
        rec_id = self._payload_id(text)
        if rec_id in self._ids:
            return rec_id

        vector = self._embed(text)
        record = {
            "id": rec_id,
            "symptom": symptom,
            "signal": signal,
            "code_line": code_line,
            "conclusion": conclusion,
            "metadata": dict(metadata) if metadata else {},
        }

        if self.backend == "lancedb":
            stored = self._add_lancedb(record, vector)
        else:
            stored = self._add_fallback(record, vector)

        if stored:
            self._ids.add(rec_id)
        return rec_id

    def search(self, query: str, k: int = 5, min_score: float = 0.0) -> list[dict]:
        """Return the top-``k`` records most similar to ``query``.

        Each result is ``{id, score, symptom, signal, code_line, conclusion,
        metadata}`` with ``score`` the cosine similarity (``[-1, 1]``). Results
        are sorted by descending score and filtered to ``score >= min_score``.
        An empty store (or ``k <= 0``) yields ``[]``; this never raises.
        """
        if k <= 0 or not self._ids:
            return []
        query_vec = self._embed(query)
        if self.backend == "lancedb":
            hits = self._search_lancedb(query_vec, k)
        else:
            hits = self._search_fallback(query_vec)

        hits = [h for h in hits if h["score"] >= min_score]
        hits.sort(key=lambda h: (-float(h["score"]), str(h.get("id", ""))))
        return hits[:k]

    def count(self) -> int:
        """Number of distinct records currently stored."""
        return len(self._ids)

    def clear(self) -> None:
        """Remove every record from the store (both memory and disk)."""
        if self.backend == "lancedb":
            self._clear_lancedb()
        else:
            self._clear_fallback()
        self._ids = set()

    # ── Fallback backend ────────────────────────────────────────────────

    def _load_fallback(self) -> None:
        """Load persisted fallback records if the JSON file exists."""
        if not self._fallback_path.exists():
            return
        try:
            data = json.loads(self._fallback_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning(
                "corrupt fallback store %s (%s); starting empty",
                self._fallback_path, exc,
            )
            return
        stored_dim = data.get("dim")
        if stored_dim is not None and int(stored_dim) != self.dim:
            logger.warning(
                "fallback store dim=%s != current dim=%d; similarity may drift",
                stored_dim, self.dim,
            )
        records = data.get("records", [])
        if isinstance(records, list):
            self._records = records
            self._ids = {r["id"] for r in records if isinstance(r, dict) and "id" in r}

    def _persist_fallback(self) -> None:
        """Atomically write the fallback records to disk (logs, never raises)."""
        try:
            _atomic_write_json(
                self._fallback_path, {"dim": self.dim, "records": self._records}
            )
        except Exception as exc:  # pragma: no cover - disk failure is abnormal
            logger.error("failed to persist fallback store: %s", exc)

    def _add_fallback(self, record: dict, vector: list[float]) -> bool:
        row = dict(record)
        row["vector"] = vector
        self._records.append(row)
        self._persist_fallback()
        return True

    def _search_fallback(self, query_vec: list[float]) -> list[dict]:
        results: list[dict] = []
        for row in self._records:
            score = _cosine(query_vec, row.get("vector", []))
            results.append(
                {
                    "id": row.get("id", ""),
                    "score": score,
                    "symptom": row.get("symptom", ""),
                    "signal": row.get("signal", ""),
                    "code_line": row.get("code_line", ""),
                    "conclusion": row.get("conclusion", ""),
                    "metadata": row.get("metadata", {}) or {},
                }
            )
        return results

    def _clear_fallback(self) -> None:
        self._records = []
        self._persist_fallback()

    # ── LanceDB backend (optional; exercised only when lancedb installed) ─

    def _init_lancedb(self) -> None:  # pragma: no cover - requires lancedb
        """Open (or defer creation of) the LanceDB table and load existing ids."""
        self._db = lancedb.connect(str(self.store_dir))
        if self.table in set(self._db.table_names()):
            self._tbl = self._db.open_table(self.table)
            try:
                for row in self._tbl.to_arrow().to_pylist():
                    rid = row.get("id")
                    if rid:
                        self._ids.add(rid)
            except Exception as exc:
                logger.warning("could not preload lancedb ids: %s", exc)
        else:
            # Created lazily on first add (LanceDB needs data/schema up front).
            self._tbl = None

    def _lancedb_row(self, record: dict, vector: list[float]) -> dict:  # pragma: no cover
        return {
            "id": record["id"],
            "vector": vector,
            "symptom": record["symptom"],
            "signal": record["signal"],
            "code_line": record["code_line"],
            "conclusion": record["conclusion"],
            # LanceDB columns are typed; store metadata as a JSON string.
            "metadata": json.dumps(record.get("metadata", {}), ensure_ascii=False),
        }

    def _add_lancedb(self, record: dict, vector: list[float]) -> bool:  # pragma: no cover
        row = self._lancedb_row(record, vector)
        try:
            if self._tbl is None:
                self._tbl = self._db.create_table(self.table, data=[row])
            else:
                self._tbl.add([row])
            return True
        except Exception as exc:
            logger.error("lancedb add failed: %s", exc)
            return False

    def _search_lancedb(self, query_vec: list[float], k: int) -> list[dict]:  # pragma: no cover
        if self._tbl is None:
            return []
        try:
            rows = (
                self._tbl.search(query_vec)
                .metric("cosine")
                .limit(k)
                .to_list()
            )
        except Exception as exc:
            logger.error("lancedb search failed: %s", exc)
            return []
        results: list[dict] = []
        for row in rows:
            # LanceDB returns cosine *distance* in ``_distance``; similarity is
            # ``1 - distance``.
            distance = row.get("_distance")
            score = (1.0 - float(distance)) if distance is not None else 0.0
            meta_raw = row.get("metadata", "")
            try:
                metadata = json.loads(meta_raw) if meta_raw else {}
            except (TypeError, ValueError):
                metadata = {}
            results.append(
                {
                    "id": row.get("id", ""),
                    "score": score,
                    "symptom": row.get("symptom", ""),
                    "signal": row.get("signal", ""),
                    "code_line": row.get("code_line", ""),
                    "conclusion": row.get("conclusion", ""),
                    "metadata": metadata,
                }
            )
        return results

    def _clear_lancedb(self) -> None:  # pragma: no cover - requires lancedb
        try:
            if self._db is not None and self.table in set(self._db.table_names()):
                self._db.drop_table(self.table)
        except Exception as exc:
            logger.error("lancedb clear failed: %s", exc)
        self._tbl = None
