"""Persistent semantic vectors, selected only from an authorized document snapshot."""

import hashlib
import json
import math
import os
from threading import Lock

from enterprise_rag_system.ingestion import chunk_documents
from enterprise_rag_system.models import Document


class ProductVectors:
    model = "text-embedding-3-small"
    dimensions = 1536

    def __init__(self, registry, embed=None):
        self.registry = registry
        self.embed = embed or self._openai
        self.lock = Lock()
        self.storage = os.getenv("RAG_PRODUCT_VECTOR_STORE", "sqlite")
        if self.storage not in {"sqlite", "qdrant"}:
            raise ValueError("RAG_PRODUCT_VECTOR_STORE must be sqlite or qdrant")
        self.remote = None
        if self.storage == "qdrant":
            from enterprise_rag_system.product_qdrant import ProductQdrant

            self.remote = ProductQdrant(self.model, self.dimensions)
        with registry.connection(write=True) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS semantic_vectors (
                tenant TEXT NOT NULL, model TEXT NOT NULL, digest TEXT NOT NULL,
                vector TEXT NOT NULL, PRIMARY KEY(tenant,model,digest))""")

    @staticmethod
    def chunks(rows):
        return chunk_documents(
            [Document(doc_id=r["doc_id"], title=r["title"], text=r["text"]) for r in rows]
        )

    @staticmethod
    def content(chunk):
        return f"{chunk.title}\n{chunk.text}"

    def digest(self, chunk):
        return hashlib.sha256(self.content(chunk).encode()).hexdigest()

    def _openai(self, texts):
        from openai import OpenAI

        with OpenAI(api_key=os.environ.get("OPENAI_API_KEY"), timeout=30, max_retries=1) as client:
            response = client.embeddings.create(
                model=self.model, input=texts, dimensions=self.dimensions
            )
        items = sorted(response.data, key=lambda item: item.index)
        if [item.index for item in items] != list(range(len(texts))):
            raise ValueError("Embedding response indices mismatch")
        return [item.embedding for item in items]

    def validated(self, vectors, count):
        if len(vectors) != count:
            raise ValueError("Embedding count mismatch")
        result = []
        for vector in vectors:
            if len(vector) != self.dimensions or not all(math.isfinite(v) for v in vector):
                raise ValueError("Invalid embedding")
            norm = math.sqrt(sum(v * v for v in vector))
            if not norm:
                raise ValueError("Zero embedding")
            result.append([v / norm for v in vector])
        return result

    def ensure(self, tenant, chunks):
        # Serialize cache population; never hold a database transaction during network I/O.
        with self.lock:
            unique = {self.digest(c): self.content(c) for c in chunks}
            found = {}
            with self.registry.connection() as db:
                for digest in unique:
                    row = db.execute(
                        "SELECT vector FROM semantic_vectors WHERE tenant=? "
                        "AND model=? AND digest=?",
                        (tenant, self.model, digest),
                    ).fetchone()
                    if row:
                        found[digest] = self.validated([json.loads(row["vector"])], 1)[0]
            missing = [key for key in unique if key not in found]
            for start in range(0, len(missing), 32):
                batch = missing[start : start + 32]
                vectors = self.validated(self.embed([unique[key] for key in batch]), len(batch))
                with self.registry.connection(write=True) as db:
                    for digest, vector in zip(batch, vectors, strict=True):
                        db.execute(
                            "INSERT OR REPLACE INTO semantic_vectors VALUES(?,?,?,?)",
                            (tenant, self.model, digest, json.dumps(vector)),
                        )
                        found[digest] = vector
            return {c.chunk_id: found[self.digest(c)] for c in chunks}

    def index(self, tenant, chunks):
        if self.remote is None:
            return self.ensure(tenant, chunks)
        digests = {self.digest(c) for c in chunks}
        present = self.remote.present(tenant, digests)
        missing = [c for c in chunks if self.digest(c) not in present]
        if missing:
            cached = self.ensure(tenant, missing)
            self.remote.put(tenant, {self.digest(c): cached[c.chunk_id] for c in missing})
        return {c.chunk_id: None for c in chunks}

    def sync(self, token):
        principal, revision, rows = self.registry.documents(token)
        chunks = self.chunks(rows)
        vectors = self.index(principal.tenant, chunks)
        with self.registry.connection() as db:
            self.registry._principal(db, token)
        return {
            "model": self.model,
            "dimensions": self.dimensions,
            "documents": len(rows),
            "chunks": len(vectors),
            "corpus_revision": revision,
            "storage": self.storage,
            "status": "ready",
        }

    def rank(self, tenant, chunks, question, lexical, top_k):
        if not chunks:
            return []
        vectors = self.index(tenant, chunks)
        query = self.validated(self.embed([question]), 1)[0]
        if self.remote:
            scores = self.remote.search(tenant, [self.digest(c) for c in chunks], query)
            semantic = {
                c.chunk_id: scores[self.digest(c)] for c in chunks if self.digest(c) in scores
            }
        else:
            semantic = {
                key: sum(a * b for a, b in zip(query, vector, strict=True))
                for key, vector in vectors.items()
            }
        # RRF combines independent rank scales. The semantic floor is a pilot
        # relevance heuristic, not a confidence guarantee or a factuality check.
        rankings = [
            sorted(
                (key for key in lexical if lexical[key] > 0), key=lambda key: (-lexical[key], key)
            ),
            sorted(
                (key for key in semantic if semantic[key] >= 0.3),
                key=lambda key: (-semantic[key], key),
            ),
        ]
        fused: dict[str, float] = {}
        for ranking in rankings:
            for rank, key in enumerate(ranking[:50], 1):
                fused[key] = fused.get(key, 0) + 1 / (60 + rank)
        by_id = {c.chunk_id: c for c in chunks}
        return [by_id[key] for key in sorted(fused, key=lambda k: (-fused[k], k))[:top_k]]
