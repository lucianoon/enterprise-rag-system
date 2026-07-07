"""End-to-end RAG pipeline."""

from time import perf_counter
from typing import Iterable, List
from uuid import uuid4

from enterprise_rag_system.models import Chunk, Citation, QueryResponse
from enterprise_rag_system.retrieval import HybridRetriever, Reranker


class RAGPipeline:
    """Hybrid retrieval and citation-aware answer composition."""

    def __init__(self, chunks: Iterable[Chunk]):
        self.retriever = HybridRetriever(chunks)
        self.reranker = Reranker()

    def query(self, question: str, top_k: int = 3) -> QueryResponse:
        started = perf_counter()
        initial = self.retriever.search(question, top_k=max(top_k * 2, top_k))
        results = self.reranker.rerank(question, initial)[:top_k]
        citations = [
            Citation(doc_id=r.chunk.doc_id, title=r.chunk.title, chunk_id=r.chunk.chunk_id)
            for r in results
        ]
        answer = self._compose_answer(question, results)
        return QueryResponse(
            answer=answer,
            citations=citations,
            results=results,
            metadata={
                "query_id": str(uuid4()),
                "latency_ms": round((perf_counter() - started) * 1000, 3),
                "top_k": top_k,
                "result_count": len(results),
            },
        )

    def _compose_answer(self, question: str, results: List) -> str:
        if not results:
            return "I could not find grounded information in the indexed documents."
        leading = results[0].chunk
        return (
            f"Based on {leading.title}, the answer should be grounded in the cited policy. "
            f"Most relevant passage: {leading.text}"
        )

