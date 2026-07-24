"""Pluggable embedding backends behind a single interface.

Three interchangeable strategies:

- ``HashingEmbedder`` — dependency-free hashed bag-of-words. Deterministic
  across processes (uses ``hashlib``, not Python's randomized ``hash()``), so
  it keeps demos, tests and CI reproducible offline.
- ``TfidfEmbedder`` — scikit-learn TF-IDF vectors fitted on the indexed
  corpus. Better lexical-semantic signal than hashing, still fully offline.
- ``SentenceTransformerEmbedder`` — real dense semantic embeddings
  (``all-MiniLM-L6-v2`` by default). Requires the optional
  ``sentence-transformers`` dependency.

``build_embedder`` selects a backend from ``RAG_EMBEDDING_BACKEND``.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from math import sqrt
from typing import List, Protocol, Sequence

logger = logging.getLogger(__name__)

DEFAULT_ST_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


class Embedder(Protocol):
    """Turns text into vectors comparable by cosine similarity."""

    name: str

    def fit(self, corpus: Sequence[str]) -> None:
        """Prepare the backend on the indexed corpus (no-op when unneeded)."""
        ...

    def embed_texts(self, texts: Sequence[str]) -> List[List[float]]:
        ...

    def embed_query(self, text: str) -> List[float]:
        ...


def _normalize(vector: List[float]) -> List[float]:
    norm = sqrt(sum(v * v for v in vector)) or 1.0
    return [v / norm for v in vector]


def _tokenize(text: str) -> List[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


class HashingEmbedder:
    """Hashed bag-of-words embedding, stable across processes and machines.

    Uses ``hashlib.md5`` for token bucketing instead of Python's built-in
    ``hash()``, which is randomized per process (``PYTHONHASHSEED``) and would
    silently break any persisted index or cross-run comparison.
    """

    name = "hashing"

    def __init__(self, dims: int = 48):
        self.dims = dims

    def fit(self, corpus: Sequence[str]) -> None:
        return None

    def _bucket(self, token: str) -> int:
        digest = hashlib.md5(token.encode("utf-8")).digest()
        return int.from_bytes(digest[:8], "big") % self.dims

    def embed_texts(self, texts: Sequence[str]) -> List[List[float]]:
        return [self._embed_one(text) for text in texts]

    def embed_query(self, text: str) -> List[float]:
        return self._embed_one(text)

    def _embed_one(self, text: str) -> List[float]:
        vector = [0.0] * self.dims
        for token in _tokenize(text):
            vector[self._bucket(token)] += 1.0
        return _normalize(vector)


class TfidfEmbedder:
    """TF-IDF vectors fitted on the indexed corpus (requires scikit-learn)."""

    name = "tfidf"

    def __init__(self, max_features: int = 2048):
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
        except ImportError as exc:  # pragma: no cover - exercised via build_embedder
            raise RuntimeError(
                "scikit-learn is required for the tfidf embedding backend. "
                "Install it with `pip install -r requirements-extras.txt`."
            ) from exc
        self._vectorizer = TfidfVectorizer(
            lowercase=True,
            stop_words="english",
            max_features=max_features,
            ngram_range=(1, 2),
        )
        self._fitted = False

    @property
    def dims(self) -> int:
        if not self._fitted:
            raise RuntimeError("TfidfEmbedder must be fitted before use.")
        return len(self._vectorizer.vocabulary_)

    def fit(self, corpus: Sequence[str]) -> None:
        documents = [text for text in corpus if text.strip()]
        if not documents:
            return
        self._vectorizer.fit(documents)
        self._fitted = True
        logger.info("Fitted TF-IDF vectorizer: %d features.", self.dims)

    def embed_texts(self, texts: Sequence[str]) -> List[List[float]]:
        if not self._fitted:
            self.fit(texts)
        if not self._fitted:
            raise RuntimeError("TfidfEmbedder could not be fitted (empty corpus).")
        matrix = self._vectorizer.transform(list(texts)).toarray()
        return [_normalize([float(v) for v in row]) for row in matrix]

    def embed_query(self, text: str) -> List[float]:
        return self.embed_texts([text])[0]


class SentenceTransformerEmbedder:
    """Dense semantic embeddings via sentence-transformers (optional)."""

    name = "sentence-transformer"

    def __init__(self, model_name: str = DEFAULT_ST_MODEL):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # pragma: no cover - exercised via build_embedder
            raise RuntimeError(
                "sentence-transformers is required for this backend. "
                "Install it with `pip install sentence-transformers`."
            ) from exc
        logger.info("Loading sentence-transformer model: %s", model_name)
        self._model = SentenceTransformer(model_name)

    def fit(self, corpus: Sequence[str]) -> None:
        return None

    def embed_texts(self, texts: Sequence[str]) -> List[List[float]]:
        vectors = self._model.encode(
            list(texts),
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return [[float(v) for v in row] for row in vectors]

    def embed_query(self, text: str) -> List[float]:
        return self.embed_texts([text])[0]


def _importable(module: str) -> bool:
    try:
        __import__(module)
    except ImportError:
        return False
    return True


def build_embedder() -> Embedder:
    """Select an embedding backend from the environment.

    ``RAG_EMBEDDING_BACKEND``:
        - ``hashing`` (default) — dependency-free, deterministic, offline.
        - ``tfidf`` — scikit-learn TF-IDF fitted on the corpus.
        - ``sentence-transformer`` — dense semantic embeddings.
        - ``auto`` — best available: sentence-transformer > tfidf > hashing.
    """
    backend = os.getenv("RAG_EMBEDDING_BACKEND", "hashing").lower()

    if backend == "hashing":
        return HashingEmbedder()
    if backend == "tfidf":
        return TfidfEmbedder()
    if backend in ("sentence-transformer", "sentence_transformer", "st"):
        return SentenceTransformerEmbedder()
    if backend == "auto":
        if _importable("sentence_transformers"):
            return SentenceTransformerEmbedder()
        if _importable("sklearn"):
            return TfidfEmbedder()
        logger.info("No optional embedding backend installed; using hashing.")
        return HashingEmbedder()
    raise ValueError(
        f"Unknown RAG_EMBEDDING_BACKEND={backend!r}. "
        "Expected one of: hashing, tfidf, sentence-transformer, auto."
    )
