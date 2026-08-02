"""Vector store backends behind a single interface.

- ``InMemoryVectorStore`` — dependency-free cosine search over a dict. Used
  for demos, tests and CI.
- ``QdrantVectorStore`` — real ANN index in Qdrant. Points at the instance
  from ``QDRANT_URL`` (the one ``docker-compose.yml`` starts) and also
  supports ``:memory:`` mode for offline tests.

``build_vector_store`` selects a backend from ``RAG_VECTOR_STORE``.
"""

from __future__ import annotations

import logging
import os
import uuid
from collections.abc import Sequence
from typing import Protocol

logger = logging.getLogger(__name__)

DEFAULT_COLLECTION = "enterprise_docs"
DEFAULT_URL = "http://localhost:6333"


class VectorStore(Protocol):
    """Indexes chunk vectors and answers nearest-neighbour queries."""

    name: str

    def index(self, chunk_ids: Sequence[str], vectors: Sequence[Sequence[float]]) -> None:
        """Replace the index contents with the given vectors."""
        ...

    def search(self, vector: Sequence[float], top_k: int) -> list[tuple[str, float]]:
        """Return ``(chunk_id, cosine_score)`` pairs, best first."""
        ...


class InMemoryVectorStore:
    """Exact cosine search over an in-process dict."""

    name = "memory"

    def __init__(self) -> None:
        self._vectors: dict[str, list[float]] = {}

    def index(self, chunk_ids: Sequence[str], vectors: Sequence[Sequence[float]]) -> None:
        self._vectors = {
            chunk_id: [float(v) for v in vector]
            for chunk_id, vector in zip(chunk_ids, vectors, strict=True)
        }

    def search(self, vector: Sequence[float], top_k: int) -> list[tuple[str, float]]:
        query = [float(v) for v in vector]
        scored = [
            (chunk_id, sum(q * d for q, d in zip(query, stored, strict=True)))
            for chunk_id, stored in self._vectors.items()
        ]
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[:top_k]


class QdrantVectorStore:
    """Qdrant-backed vector index.

    Chunk ids are strings like ``policy_sla:0``, which Qdrant does not accept
    as point ids, so each point gets a UUIDv5 derived from the chunk id and
    keeps the original id in its payload.
    """

    name = "qdrant"

    def __init__(self, url: str | None = None, collection: str | None = None):
        try:
            from qdrant_client import QdrantClient
        except ImportError as exc:
            raise RuntimeError(
                "qdrant-client is required for the qdrant vector store. "
                "Install it with `uv sync --extra extras`."
            ) from exc

        self.url: str = url or os.environ.get("QDRANT_URL") or DEFAULT_URL
        self.collection: str = (
            collection or os.environ.get("COLLECTION_NAME") or DEFAULT_COLLECTION
        )
        if self.url == ":memory:":
            self._client = QdrantClient(":memory:")
        else:
            self._client = QdrantClient(url=self.url)
        logger.info("Qdrant vector store: url=%s collection=%s", self.url, self.collection)

    def index(self, chunk_ids: Sequence[str], vectors: Sequence[Sequence[float]]) -> None:
        from qdrant_client.models import Distance, PointStruct, VectorParams

        if not chunk_ids:
            return
        dims = len(vectors[0])
        if self._client.collection_exists(self.collection):
            self._client.delete_collection(self.collection)
        self._client.create_collection(
            collection_name=self.collection,
            vectors_config=VectorParams(size=dims, distance=Distance.COSINE),
        )
        points = [
            PointStruct(
                id=str(uuid.uuid5(uuid.NAMESPACE_URL, chunk_id)),
                vector=[float(v) for v in vector],
                payload={"chunk_id": chunk_id},
            )
            for chunk_id, vector in zip(chunk_ids, vectors, strict=True)
        ]
        self._client.upsert(collection_name=self.collection, points=points)
        logger.info("Indexed %d vectors (%d dims) into %s.", len(points), dims, self.collection)

    def search(self, vector: Sequence[float], top_k: int) -> list[tuple[str, float]]:
        response = self._client.query_points(
            collection_name=self.collection,
            query=[float(v) for v in vector],
            limit=top_k,
            with_payload=True,
        )
        return [
            (str(point.payload["chunk_id"]), float(point.score))
            for point in response.points
            if point.payload and "chunk_id" in point.payload
        ]


def build_vector_store() -> VectorStore:
    """Select a vector store backend from the environment.

    ``RAG_VECTOR_STORE``:
        - ``memory`` (default) — in-process exact search, no dependencies.
        - ``qdrant`` — Qdrant at ``QDRANT_URL`` using ``COLLECTION_NAME``.
    """
    backend = os.getenv("RAG_VECTOR_STORE", "memory").lower()
    if backend == "memory":
        return InMemoryVectorStore()
    if backend == "qdrant":
        return QdrantVectorStore()
    raise ValueError(
        f"Unknown RAG_VECTOR_STORE={backend!r}. Expected one of: memory, qdrant."
    )
