"""Hybrid retrieval: lexical scoring fused with vector search.

Lexical scoring (BM25-style IDF + log-TF) runs in-process. Vector scoring is
delegated to a pluggable :class:`~enterprise_rag_system.embeddings.Embedder`
and :class:`~enterprise_rag_system.vector_store.VectorStore`, so the same
retriever runs against the offline in-memory backends or a real Qdrant
instance without code changes.
"""

import logging
import re
from collections import Counter
from collections.abc import Iterable
from math import log

from enterprise_rag_system.embeddings import Embedder, build_embedder
from enterprise_rag_system.models import Chunk, SearchResult
from enterprise_rag_system.vector_store import VectorStore, build_vector_store

logger = logging.getLogger(__name__)


def tokenize(text: str) -> list[str]:
    """Normalize text into searchable tokens."""
    return re.findall(r"[a-z0-9]+", text.lower())


class HybridRetriever:
    """Combines lexical and vector retrieval."""

    def __init__(
        self,
        chunks: Iterable[Chunk],
        embedder: Embedder | None = None,
        vector_store: VectorStore | None = None,
    ):
        self.chunks = list(chunks)
        self.chunk_tokens = {c.chunk_id: tokenize(f"{c.title} {c.text}") for c in self.chunks}
        self.idf = self._build_idf()

        self.embedder = embedder or build_embedder()
        self.vector_store = vector_store or build_vector_store()
        texts = [f"{c.title} {c.text}" for c in self.chunks]
        self.embedder.fit(texts)
        if self.chunks:
            vectors = self.embedder.embed_texts(texts)
            self.vector_store.index([c.chunk_id for c in self.chunks], vectors)
        logger.info(
            "Indexed %d chunks (embedder=%s, vector_store=%s).",
            len(self.chunks),
            self.embedder.name,
            self.vector_store.name,
        )

    def search(self, question: str, top_k: int = 3) -> list[SearchResult]:
        query_tokens = tokenize(question)
        # Every chunk gets a hybrid score, so ask the store for the full
        # ranking. Fine at document-collection scale; for very large corpora
        # this becomes a candidate pool instead.
        vector_scores: dict[str, float] = {}
        if self.chunks:
            query_vector = self.embedder.embed_query(question)
            vector_scores = dict(self.vector_store.search(query_vector, top_k=len(self.chunks)))
        scored = []
        for chunk in self.chunks:
            lexical = self._lexical_score(query_tokens, self.chunk_tokens[chunk.chunk_id])
            vector = vector_scores.get(chunk.chunk_id, 0.0)
            hybrid = (0.55 * lexical) + (0.45 * vector)
            scored.append(
                SearchResult(
                    chunk=chunk,
                    lexical_score=round(lexical, 4),
                    vector_score=round(vector, 4),
                    hybrid_score=round(hybrid, 4),
                )
            )
        scored.sort(key=lambda item: item.hybrid_score, reverse=True)
        return scored[:top_k]

    def _build_idf(self) -> dict[str, float]:
        doc_count = len(self.chunks) or 1
        frequencies: Counter[str] = Counter()
        for tokens in self.chunk_tokens.values():
            frequencies.update(set(tokens))
        return {
            token: log((doc_count + 1) / (freq + 1)) + 1
            for token, freq in frequencies.items()
        }

    def _lexical_score(self, query_tokens: list[str], chunk_tokens: list[str]) -> float:
        if not query_tokens or not chunk_tokens:
            return 0.0
        chunk_counts = Counter(chunk_tokens)
        score = 0.0
        for token in query_tokens:
            if token in chunk_counts:
                score += self.idf.get(token, 1.0) * (1 + log(chunk_counts[token]))
        return score / len(set(query_tokens))


class Reranker:
    """Lightweight reranker for exact phrase and title matches."""

    def rerank(self, question: str, results: list[SearchResult]) -> list[SearchResult]:
        query = question.lower()
        query_tokens = set(tokenize(question))
        for result in results:
            title_tokens = set(tokenize(result.chunk.title))
            title_overlap = len(query_tokens & title_tokens) / (len(query_tokens) or 1)
            exact_bonus = 0.25 if result.chunk.title.lower() in query else 0.0
            result.rerank_score = round(result.hybrid_score + title_overlap + exact_bonus, 4)
        return sorted(results, key=lambda item: item.rerank_score, reverse=True)
