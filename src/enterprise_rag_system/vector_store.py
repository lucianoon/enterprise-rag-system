"""Vector store backends behind a single interface.

- ``InMemoryVectorStore`` — dependency-free cosine search over a dict. Used
  for demos, tests and CI.
- ``QdrantVectorStore`` — real ANN index in Qdrant. Points at the instance
  from ``QDRANT_URL`` (the one ``docker-compose.yml`` starts) and also
  supports ``:memory:`` mode for offline tests.

``build_vector_store`` selects a backend from ``RAG_VECTOR_STORE``.
"""

from __future__ import annotations

import hashlib
import logging
import os
import uuid
from collections.abc import Sequence
from math import isfinite
from threading import Lock
from typing import Protocol

logger = logging.getLogger(__name__)

DEFAULT_COLLECTION = "enterprise_docs"
DEFAULT_URL = "http://localhost:6333"


def _validated_vectors(
    chunk_ids: Sequence[str], vectors: Sequence[Sequence[float]]
) -> dict[str, list[float]]:
    """Copy and validate the entire replacement before changing any stored data."""
    if len(chunk_ids) != len(vectors):
        raise ValueError("Chunk and vector counts must match")
    if len(set(chunk_ids)) != len(chunk_ids) or any(not key.strip() for key in chunk_ids):
        raise ValueError("Chunk ids must be unique and non-empty")
    copied = {key: [float(v) for v in vector]
              for key, vector in zip(chunk_ids, vectors, strict=True)}
    if copied:
        dims = len(next(iter(copied.values())))
        if not dims or any(len(v) != dims for v in copied.values()):
            raise ValueError("Vectors must have the same positive dimension")
        if any(not isfinite(value) for vector in copied.values() for value in vector):
            raise ValueError("Vectors must contain only finite values")
    return copied


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
        self._vectors = _validated_vectors(chunk_ids, vectors)

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
    keeps the original id in its payload. Each replacement builds a new physical
    collection and pins this instance to it only after acknowledged writes and
    exact count validation. No existing collection is overwritten or deleted.
    This is an index generation, not a Qdrant backup/snapshot archive.
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
        self._active_collection: str | None = None
        self._index_lock = Lock()
        logger.info("Qdrant vector store namespace: %s", self.collection)

    @property
    def active_collection(self) -> str | None:
        """Physical generation pinned to this instance, for operational inspection."""
        return self._active_collection

    def index(self, chunk_ids: Sequence[str], vectors: Sequence[Sequence[float]]) -> None:
        from qdrant_client.models import Distance, PointStruct, UpdateStatus, VectorParams

        prepared = _validated_vectors(chunk_ids, vectors)
        # Serialize replacements on this instance; searches keep using the old
        # immutable generation while the new one is built.
        with self._index_lock:
            if not prepared:
                self._active_collection = None
                return
            dims = len(next(iter(prepared.values())))
            prefix = self.collection
            if len(prefix.encode("utf-8")) > 210:
                digest = hashlib.sha256(prefix.encode("utf-8")).hexdigest()[:16]
                prefix = (
                    prefix.encode("utf-8")[:193].decode("utf-8", errors="ignore")
                    + "_" + digest
                )
            candidate = f"{prefix}__generation_{uuid.uuid4().hex}"
            logger.info("Building generation %s", candidate)
            if not self._client.create_collection(
                collection_name=candidate,
                vectors_config=VectorParams(size=dims, distance=Distance.COSINE),
            ):
                raise RuntimeError("Qdrant did not confirm creation of a new generation")
            try:
                items = list(prepared.items())
                for offset in range(0, len(items), 256):
                    points = [
                        PointStruct(
                            id=str(uuid.uuid5(uuid.NAMESPACE_URL, chunk_id)),
                            vector=vector,
                            payload={"chunk_id": chunk_id},
                        )
                        for chunk_id, vector in items[offset:offset + 256]
                    ]
                    result = self._client.upsert(
                        collection_name=candidate, points=points, wait=True,
                    )
                    if result.status != UpdateStatus.COMPLETED:
                        raise RuntimeError("Qdrant did not complete the generation write")
                count = self._client.count(collection_name=candidate, exact=True).count
                if count != len(prepared):
                    raise RuntimeError("Qdrant generation count does not match the input")
            except Exception:
                # Retain incomplete generations too: a network timeout leaves the
                # outcome uncertain. No automatic deletion can affect other readers.
                logger.warning("Generation was not activated: %s", candidate)
                raise
            self._active_collection = candidate
            logger.info("Activated generation %s (%d vectors, %d dims)", candidate, count, dims)

    def search(self, vector: Sequence[float], top_k: int) -> list[tuple[str, float]]:
        active = self._active_collection
        if active is None:
            return []
        response = self._client.query_points(
            collection_name=active,
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
