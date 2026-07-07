"""Hybrid retrieval primitives."""

from collections import Counter
from math import log, sqrt
import re
from typing import Dict, Iterable, List

from enterprise_rag_system.models import Chunk, SearchResult


def tokenize(text: str) -> List[str]:
    """Normalize text into searchable tokens."""
    return re.findall(r"[a-z0-9]+", text.lower())


def embed(text: str, dims: int = 48) -> List[float]:
    """Deterministic local embedding for offline demos and CI."""
    vector = [0.0] * dims
    for token in tokenize(text):
        bucket = hash(token) % dims
        vector[bucket] += 1.0
    norm = sqrt(sum(v * v for v in vector)) or 1.0
    return [v / norm for v in vector]


def cosine(a: List[float], b: List[float]) -> float:
    """Cosine similarity for normalized vectors."""
    return sum(x * y for x, y in zip(a, b))


class HybridRetriever:
    """Combines lexical and vector retrieval."""

    def __init__(self, chunks: Iterable[Chunk]):
        self.chunks = list(chunks)
        self.chunk_tokens = {c.chunk_id: tokenize(f"{c.title} {c.text}") for c in self.chunks}
        self.chunk_vectors = {c.chunk_id: embed(f"{c.title} {c.text}") for c in self.chunks}
        self.idf = self._build_idf()

    def search(self, question: str, top_k: int = 3) -> List[SearchResult]:
        query_tokens = tokenize(question)
        query_vector = embed(question)
        scored = []
        for chunk in self.chunks:
            lexical = self._lexical_score(query_tokens, self.chunk_tokens[chunk.chunk_id])
            vector = cosine(query_vector, self.chunk_vectors[chunk.chunk_id])
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

    def _build_idf(self) -> Dict[str, float]:
        doc_count = len(self.chunks) or 1
        frequencies = Counter()
        for tokens in self.chunk_tokens.values():
            frequencies.update(set(tokens))
        return {
            token: log((doc_count + 1) / (freq + 1)) + 1
            for token, freq in frequencies.items()
        }

    def _lexical_score(self, query_tokens: List[str], chunk_tokens: List[str]) -> float:
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

    def rerank(self, question: str, results: List[SearchResult]) -> List[SearchResult]:
        query = question.lower()
        query_tokens = set(tokenize(question))
        for result in results:
            title_tokens = set(tokenize(result.chunk.title))
            title_overlap = len(query_tokens & title_tokens) / (len(query_tokens) or 1)
            exact_bonus = 0.25 if result.chunk.title.lower() in query else 0.0
            result.rerank_score = round(result.hybrid_score + title_overlap + exact_bonus, 4)
        return sorted(results, key=lambda item: item.rerank_score, reverse=True)

