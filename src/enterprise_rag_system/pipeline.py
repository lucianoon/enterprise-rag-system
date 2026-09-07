"""End-to-end RAG pipeline."""

import logging
from collections.abc import Iterable
from time import perf_counter
from typing import get_args
from uuid import uuid4

from enterprise_rag_system.embeddings import Embedder
from enterprise_rag_system.generation import (
    AnswerGenerator,
    build_answer_generator,
    generate_answer,
)
from enterprise_rag_system.models import Chunk, Citation, QueryResponse, SearchResult
from enterprise_rag_system.retrieval import HybridRetriever, Reranker, RetrievalMode
from enterprise_rag_system.vector_store import VectorStore

logger = logging.getLogger(__name__)


class RAGPipeline:
    """Hybrid retrieval and citation-aware answer composition."""

    def __init__(
        self,
        chunks: Iterable[Chunk],
        answer_generator: AnswerGenerator | None = None,
        embedder: Embedder | None = None,
        vector_store: VectorStore | None = None,
        *, retrieval_mode: RetrievalMode = "hybrid",
    ):
        if retrieval_mode not in get_args(RetrievalMode):
            raise ValueError(f"Unknown retrieval mode: {retrieval_mode!r}")
        self.retrieval_mode = retrieval_mode
        self.retriever = HybridRetriever(chunks, embedder=embedder, vector_store=vector_store)
        self.reranker = Reranker()
        self.answer_generator = answer_generator or build_answer_generator()

    def retrieve(
        self, question: str, top_k: int = 3, *,
        mode: RetrievalMode | None = None, rerank: bool | None = None,
    ) -> list[SearchResult]:
        """Retrieve evidence without invoking the answer generator."""
        mode = mode if mode is not None else self.retrieval_mode
        # The legacy title bonus is calibrated to legacy scores, not BM25/RRF.
        if rerank is None:
            rerank = mode not in ("bm25", "rrf")
        initial = self.retriever.search(question, top_k=top_k * 2, mode=mode)
        ranked = self.reranker.rerank(question, initial) if rerank else initial
        return ranked[:top_k]

    def query(self, question: str, top_k: int = 3) -> QueryResponse:
        started = perf_counter()
        results = self.retrieve(question, top_k=top_k)
        citations = [
            Citation(doc_id=r.chunk.doc_id, title=r.chunk.title, chunk_id=r.chunk.chunk_id)
            for r in results
        ]
        generated = generate_answer(self.answer_generator, question, results)
        latency_ms = round((perf_counter() - started) * 1000, 3)
        logger.info(
            "query answered: top_k=%d results=%d mode=%s latency_ms=%.1f",
            top_k,
            len(results),
            generated.mode,
            latency_ms,
        )
        return QueryResponse(
            answer=generated.text,
            citations=citations,
            results=results,
            metadata={
                "query_id": str(uuid4()),
                "latency_ms": latency_ms,
                "top_k": top_k,
                "result_count": len(results),
                "generation_mode": generated.mode,
                "retrieval_mode": self.retrieval_mode,
            },
        )
