"""Optional multilingual cross-encoder reranking (``semantic`` extra, CPU).

A cross-encoder reads question and passage together, so it can judge answer
relevance instead of keyword overlap. It is much slower than first-stage
retrieval, so it only reorders a bounded candidate pool produced by BM25/RRF.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from enterprise_rag_system.models import SearchResult

logger = logging.getLogger(__name__)

# mMiniLMv2 fine-tuned on mMARCO (Portuguese included), Apache-2.0.
DEFAULT_CE_MODEL = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
DEFAULT_CE_REVISION = "1427fd652930e4ba29e8149678df786c240d8825"


class CrossEncoderReranker:
    """Reorders candidates by cross-encoder relevance; ties break by chunk ID."""

    def __init__(
        self,
        model_name: str = DEFAULT_CE_MODEL,
        revision: str | None = DEFAULT_CE_REVISION,
        *,
        device: str = "cpu",
        max_length: int = 512,
        model=None,
    ):
        self.model_name = model_name
        self.revision = revision
        if model is None:
            try:
                from sentence_transformers import CrossEncoder
            except ImportError as exc:
                raise RuntimeError(
                    "sentence-transformers is required for cross-encoder reranking. "
                    "Install it with `uv sync --extra semantic`."
                ) from exc
            logger.info("Loading cross-encoder %s@%s", model_name, revision or "latest")
            model = CrossEncoder(
                model_name, revision=revision, device=device, max_length=max_length
            )
        self._model = model

    def scores(self, question: str, passages: Sequence[str]) -> list[float]:
        if not passages:
            return []
        values = self._model.predict(
            [(question, passage) for passage in passages], show_progress_bar=False
        )
        return [float(v) for v in values]

    def rerank(self, question: str, results: list[SearchResult]) -> list[SearchResult]:
        passages = [f"{r.chunk.title}\n{r.chunk.text}" for r in results]
        scored = list(zip(self.scores(question, passages), results, strict=True))
        for score, result in scored:
            result.rerank_score = round(score, 4)
        scored.sort(key=lambda item: (-item[0], item[1].chunk.chunk_id))
        return [result for _, result in scored]
