"""Qdrant index with content-addressed IDs and mandatory authorized-snapshot filters."""

import os
import uuid
from threading import Lock


class ProductQdrant:
    name = "qdrant"

    def __init__(self, model, dimensions, client=None):
        from qdrant_client import QdrantClient

        self.client = client or QdrantClient(
            url=os.environ.get("QDRANT_URL", "http://qdrant:6333"),
            api_key=os.environ.get("QDRANT_API_KEY"),
            timeout=15,
        )
        self.model = model
        self.dimensions = dimensions
        self.collection = "product_" + model.replace("-", "_") + "_" + str(dimensions)
        self.lock = Lock()

    def point_id(self, tenant, digest):
        # Length-delimited namespace avoids ambiguous tenant/digest concatenation.
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{len(tenant)}:{tenant}:{self.model}:{digest}"))

    def prepare(self):
        from qdrant_client import models as m

        with self.lock:
            if not self.client.collection_exists(self.collection):
                try:
                    self.client.create_collection(
                        self.collection,
                        vectors_config=m.VectorParams(
                            size=self.dimensions, distance=m.Distance.COSINE
                        ),
                    )
                except Exception:
                    # Another worker may have created the same compatible collection.
                    if not self.client.collection_exists(self.collection):
                        raise
            info = self.client.get_collection(self.collection)
            if "tenant" not in info.payload_schema:
                self.client.create_payload_index(
                    self.collection, "tenant", m.PayloadSchemaType.KEYWORD, wait=True
                )
            config = info.config.params.vectors
            if (
                not isinstance(config, m.VectorParams)
                or config.size != self.dimensions
                or config.distance != m.Distance.COSINE
            ):
                raise ValueError("Incompatible Qdrant collection")

    def present(self, tenant, digests):
        self.prepare()
        mapping = {self.point_id(tenant, digest): digest for digest in digests}
        found = set()
        keys = list(mapping)
        for start in range(0, len(keys), 128):
            points = self.client.retrieve(
                self.collection,
                ids=keys[start : start + 128],
                with_payload=True,
                with_vectors=False,
            )
            for point in points:
                payload = point.payload or {}
                if (
                    payload.get("tenant") == tenant
                    and payload.get("digest") == mapping[str(point.id)]
                ):
                    found.add(mapping[str(point.id)])
        return found

    def put(self, tenant, vectors):
        from qdrant_client import models as m

        items = list(vectors.items())
        for start in range(0, len(items), 64):
            result = self.client.upsert(
                self.collection,
                wait=True,
                points=[
                    m.PointStruct(
                        id=self.point_id(tenant, digest),
                        vector=vector,
                        payload={"tenant": tenant, "digest": digest, "model": self.model},
                    )
                    for digest, vector in items[start : start + 64]
                ],
            )
            if result.status != m.UpdateStatus.COMPLETED:
                raise RuntimeError("Qdrant did not acknowledge indexing")
        if self.present(tenant, list(vectors)) != set(vectors):
            raise RuntimeError("Qdrant index verification failed")

    def search(self, tenant, digests, query):
        from qdrant_client import models as m

        if not digests:
            return {}
        mapping = {self.point_id(tenant, digest): digest for digest in digests}
        points = self.client.query_points(
            self.collection,
            query=query,
            limit=50,
            score_threshold=0.3,
            query_filter=m.Filter(
                must=[
                    m.FieldCondition(key="tenant", match=m.MatchValue(value=tenant)),
                    m.HasIdCondition(has_id=list(mapping)),
                ]
            ),
            with_payload=True,
            with_vectors=False,
        ).points
        # Defense in depth: never accept an ID outside the authorized snapshot.
        return {
            mapping[str(point.id)]: point.score
            for point in points
            if str(point.id) in mapping and (point.payload or {}).get("tenant") == tenant
        }
