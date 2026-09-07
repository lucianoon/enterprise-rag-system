"""Offline BM25 and reciprocal rank fusion, independent of vector providers."""

import re
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from math import log1p


def normalize_tokens(text: str) -> list[str]:
    """Fold accents without breaking words; retain Unicode letters and numbers.

    This analyzer has no language-specific stop list or stemming. The same
    transformation is applied to documents and queries, including decomposed
    accents and uppercase text.
    """
    normalized = unicodedata.normalize("NFKD", text.casefold())
    folded = "".join(c for c in normalized if not unicodedata.combining(c))
    return re.findall(r"[^\W_]+", folded)


class BM25Index:
    """BM25 over title + body chunks (k1=1.2, b=0.75).

    Uses positive Robertson IDF, term-frequency saturation and length
    normalization. Query terms are unique; repeated query words do not boost
    a document. Posting lists avoid rescanning every document for every query.
    """

    def __init__(self, texts: Mapping[str, str]):
        self.lengths: dict[str, int] = {}
        self.postings: dict[str, dict[str, int]] = defaultdict(dict)
        for chunk_id, text in texts.items():
            tokens = normalize_tokens(text)
            self.lengths[chunk_id] = len(tokens)
            for token, count in Counter(tokens).items():
                self.postings[token][chunk_id] = count
        count = len(texts)
        self.average_length = sum(self.lengths.values()) / count if count else 0.0
        self.idf = {
            token: log1p((count - len(posting) + 0.5) / (len(posting) + 0.5))
            for token, posting in self.postings.items()
        }

    def score(self, question: str) -> dict[str, float]:
        scores: dict[str, float] = defaultdict(float)
        if not self.average_length:
            return {}
        # Sorted terms keep floating point accumulation reproducible across processes.
        for token in sorted(set(normalize_tokens(question))):
            for chunk_id, frequency in self.postings.get(token, {}).items():
                length_ratio = self.lengths[chunk_id] / self.average_length
                denominator = frequency + 1.2 * (0.25 + 0.75 * length_ratio)
                scores[chunk_id] += self.idf[token] * frequency * 2.2 / denominator
        return dict(scores)


def reciprocal_rank_fusion(rankings: Sequence[Sequence[str]]) -> dict[str, float]:
    """Equal-weight RRF with rank constant 60 and one vote per item per list.

    Callers supply rankings containing actual candidates, not zero-score
    padding. Empty rankings contribute nothing. Ranks start at one.
    """
    scores: dict[str, float] = defaultdict(float)
    for ranking in rankings:
        seen: set[str] = set()
        for rank, chunk_id in enumerate(ranking, 1):
            if chunk_id not in seen:
                scores[chunk_id] += 1 / (60 + rank)
                seen.add(chunk_id)
    return dict(scores)
