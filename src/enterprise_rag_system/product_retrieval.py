"""Lexical retrieval for the pilot product, built on the shared core.

The product reuses the core analyzer (:mod:`enterprise_rag_system.tokenization`)
and :class:`~enterprise_rag_system.ranking.BM25Index`. Each query sees only the
documents its principal may read, so the index is keyed by that authorized
snapshot: a tenant plus the exact content of every visible document. Any edit,
restore, deletion or permission change produces a different key, so a stale
index can never be served; unchanged snapshots skip re-chunking and re-indexing.
"""

import hashlib
from collections import OrderedDict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from threading import Lock
from typing import Any

from enterprise_rag_system.ingestion import chunk_documents
from enterprise_rag_system.models import Chunk, Document
from enterprise_rag_system.ranking import BM25Index
from enterprise_rag_system.tokenization import content_terms

Row = Mapping[str, Any]


@dataclass(frozen=True)
class LexicalSnapshot:
    """Chunks and BM25 index of one authorized document snapshot."""

    chunks: tuple[Chunk, ...]
    index: BM25Index

    def rank(self, question: str, top_k: int) -> tuple[dict[str, float], list[Chunk]]:
        """BM25 scores for every chunk and the top positive-score chunks (ties by ID)."""
        scores = self.index.score(question)
        ranked = sorted(self.chunks, key=lambda c: (-scores.get(c.chunk_id, 0), c.chunk_id))
        return scores, [c for c in ranked if scores.get(c.chunk_id, 0) > 0][:top_k]


def lexical_question(question: str) -> str:
    """Question without function words; falls back to the original when nothing remains."""
    return " ".join(content_terms(question)) or question


def snapshot_key(tenant: str, rows: Iterable[Row]) -> tuple[str, str]:
    """Content digest of an authorized snapshot, independent of row order."""
    digest = hashlib.sha256()
    for row in sorted(rows, key=lambda r: r["doc_id"]):
        for field in (row["doc_id"], row["title"], row["text"]):
            digest.update(field.encode("utf-8"))
            digest.update(b"\0")
    return tenant, digest.hexdigest()


def build_snapshot(rows: Iterable[Row]) -> LexicalSnapshot:
    chunks = chunk_documents(
        [Document(doc_id=r["doc_id"], title=r["title"], text=r["text"]) for r in rows]
    )
    return LexicalSnapshot(
        chunks=tuple(chunks),
        index=BM25Index({c.chunk_id: f"{c.title} {c.text}" for c in chunks}),
    )


class LexicalIndexCache:
    """Small thread-safe LRU of :class:`LexicalSnapshot` keyed by :func:`snapshot_key`."""

    def __init__(self, maxsize: int = 32):
        if maxsize < 1:
            raise ValueError("maxsize must be positive")
        self.maxsize = maxsize
        self.hits = 0
        self.misses = 0
        self._entries: OrderedDict[tuple[str, str], LexicalSnapshot] = OrderedDict()
        self._lock = Lock()

    def get(self, tenant: str, rows: list[Row]) -> LexicalSnapshot:
        key = snapshot_key(tenant, rows)
        with self._lock:
            cached = self._entries.get(key)
            if cached is not None:
                self._entries.move_to_end(key)
                self.hits += 1
                return cached
        # Build outside the lock; a concurrent duplicate build is harmless.
        snapshot = build_snapshot(rows)
        with self._lock:
            self.misses += 1
            self._entries[key] = snapshot
            self._entries.move_to_end(key)
            while len(self._entries) > self.maxsize:
                self._entries.popitem(last=False)
        return snapshot

    def __len__(self) -> int:
        return len(self._entries)
