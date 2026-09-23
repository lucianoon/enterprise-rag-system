"""Pluggable embedding backends behind a single interface.

Three interchangeable strategies:

- ``HashingEmbedder`` — dependency-free hashed bag-of-words. Deterministic
  across processes (uses ``hashlib``, not Python's randomized ``hash()``), so
  it keeps demos, tests and CI reproducible offline.
- ``TfidfEmbedder`` — scikit-learn TF-IDF vectors fitted on the indexed
  corpus. Better lexical-semantic signal than hashing, still fully offline.
- ``SentenceTransformerEmbedder`` — real dense multilingual embeddings
  (``intfloat/multilingual-e5-small`` at a pinned revision by default).
  Requires the optional ``semantic`` extra (sentence-transformers + torch CPU).

``build_embedder`` selects a backend from ``RAG_EMBEDDING_BACKEND``.
"""

from __future__ import annotations

import hashlib
import logging
import os
from collections import Counter
from collections.abc import Sequence
from math import sqrt
from typing import Protocol

from enterprise_rag_system.tokenization import tokenize

logger = logging.getLogger(__name__)

# Multilingual (Portuguese included), 384 dimensions, MIT licensed. The revision
# is a Hugging Face commit, so a benchmark rerun downloads the same weights.
DEFAULT_ST_MODEL = "intfloat/multilingual-e5-small"
DEFAULT_ST_REVISION = "614241f622f53c4eeff9890bdc4f31cfecc418b3"


class Embedder(Protocol):
    """Turns text into vectors comparable by cosine similarity."""

    name: str

    def fit(self, corpus: Sequence[str]) -> None:
        """Prepare the backend on the indexed corpus (no-op when unneeded)."""
        ...

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        ...

    def embed_query(self, text: str) -> list[float]:
        ...


def _normalize(vector: list[float]) -> list[float]:
    norm = sqrt(sum(v * v for v in vector)) or 1.0
    return [v / norm for v in vector]


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

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed_one(text)

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dims
        for token in tokenize(text):
            vector[self._bucket(token)] += 1.0
        return _normalize(vector)


class TfidfEmbedder:
    """TF-IDF vectors fitted on the indexed corpus (requires scikit-learn).

    The vocabulary keeps the ``max_features`` most frequent terms, like
    scikit-learn's own ``max_features``, but ties are broken by the term itself.
    scikit-learn ranks with an unstable ``argsort`` whose tie order depends on
    NumPy's SIMD dispatch (AVX-512 or not), so the same corpus could keep a
    different vocabulary, and rank differently, on another CPU.
    """

    name = "tfidf"

    def __init__(self, max_features: int = 2048):
        if max_features < 1:
            raise ValueError("max_features must be positive")
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
        except ImportError as exc:  # pragma: no cover - exercised via build_embedder
            raise RuntimeError(
                "scikit-learn is required for the tfidf embedding backend. "
                "Install it with `uv sync --extra extras`."
            ) from exc
        self.max_features = max_features
        self._vectorizer_class = TfidfVectorizer
        self._vectorizer = self._new_vectorizer()
        self._fitted = False

    def _new_vectorizer(self, vocabulary: Sequence[str] | None = None):
        return self._vectorizer_class(
            # Same analyzer as BM25/lexical/hashing; n-grams are built on its tokens.
            tokenizer=tokenize,
            lowercase=False,
            token_pattern=None,
            stop_words="english",
            ngram_range=(1, 2),
            vocabulary=vocabulary,
        )

    def _select_vocabulary(self, documents: Sequence[str]) -> list[str]:
        """Top ``max_features`` terms by corpus frequency, ties broken by term."""
        analyze = self._new_vectorizer().build_analyzer()
        frequencies: Counter[str] = Counter()
        for document in documents:
            frequencies.update(analyze(document))
        if not frequencies:
            raise ValueError("TF-IDF vocabulary is empty (only stop words?)")
        ranked = sorted(frequencies, key=lambda term: (-frequencies[term], term))
        return sorted(ranked[:self.max_features])

    @property
    def dims(self) -> int:
        if not self._fitted:
            raise RuntimeError("TfidfEmbedder must be fitted before use.")
        return len(self._vectorizer.vocabulary_)

    def fit(self, corpus: Sequence[str]) -> None:
        documents = [text for text in corpus if text.strip()]
        if not documents:
            return
        self._vectorizer = self._new_vectorizer(self._select_vocabulary(documents))
        self._vectorizer.fit(documents)
        self._fitted = True
        logger.info("Fitted TF-IDF vectorizer: %d features.", self.dims)

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        if not self._fitted:
            self.fit(texts)
        if not self._fitted:
            raise RuntimeError("TfidfEmbedder could not be fitted (empty corpus).")
        matrix = self._vectorizer.transform(list(texts)).toarray()
        return [_normalize([float(v) for v in row]) for row in matrix]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_texts([text])[0]


def _e5_prefixes(model_name: str) -> tuple[str, str]:
    """E5 models are trained with ``query: `` / ``passage: `` prefixes; others use none."""
    return ("query: ", "passage: ") if "e5" in model_name.rsplit("/", 1)[-1].lower() else ("", "")


class SentenceTransformerEmbedder:
    """Dense semantic embeddings via sentence-transformers on CPU (optional extra).

    ``revision`` pins the Hugging Face commit; ``None`` means "latest", which is
    not reproducible and is only meant for exploration. Queries and passages get
    the model's asymmetric prefixes (E5) unless explicit prefixes are given.
    """

    name = "sentence-transformer"

    def __init__(
        self,
        model_name: str = DEFAULT_ST_MODEL,
        revision: str | None = DEFAULT_ST_REVISION,
        *,
        query_prefix: str | None = None,
        passage_prefix: str | None = None,
        device: str = "cpu",
        model=None,
    ):
        default_query, default_passage = _e5_prefixes(model_name)
        self.model_name = model_name
        self.revision = revision
        self.query_prefix = default_query if query_prefix is None else query_prefix
        self.passage_prefix = default_passage if passage_prefix is None else passage_prefix
        if model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise RuntimeError(
                    "sentence-transformers is required for this backend. "
                    "Install it with `uv sync --extra semantic`."
                ) from exc
            logger.info("Loading sentence-transformer %s@%s", model_name, revision or "latest")
            model = SentenceTransformer(model_name, revision=revision, device=device)
        self._model = model

    @property
    def dims(self) -> int:
        # sentence-transformers >= 5 renamed the accessor; keep both working.
        getter = getattr(self._model, "get_embedding_dimension", None) or (
            self._model.get_sentence_embedding_dimension
        )
        return int(getter())

    def fit(self, corpus: Sequence[str]) -> None:
        return None

    def _encode(self, texts: Sequence[str]) -> list[list[float]]:
        vectors = self._model.encode(
            list(texts),
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return [[float(v) for v in row] for row in vectors]

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        return self._encode([self.passage_prefix + text for text in texts])

    def embed_query(self, text: str) -> list[float]:
        return self._encode([self.query_prefix + text])[0]


def sentence_transformer_from_env() -> SentenceTransformerEmbedder:
    """``RAG_ST_MODEL`` / ``RAG_ST_REVISION`` override the pinned default model."""
    model = os.getenv("RAG_ST_MODEL") or DEFAULT_ST_MODEL
    default_revision = DEFAULT_ST_REVISION if model == DEFAULT_ST_MODEL else None
    return SentenceTransformerEmbedder(model, os.getenv("RAG_ST_REVISION") or default_revision)


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
        return sentence_transformer_from_env()
    if backend == "auto":
        if _importable("sentence_transformers"):
            return sentence_transformer_from_env()
        if _importable("sklearn"):
            return TfidfEmbedder()
        logger.info("No optional embedding backend installed; using hashing.")
        return HashingEmbedder()
    raise ValueError(
        f"Unknown RAG_EMBEDDING_BACKEND={backend!r}. "
        "Expected one of: hashing, tfidf, sentence-transformer, auto."
    )
