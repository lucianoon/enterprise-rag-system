"""The single text analyzer shared by every retrieval and evaluation pipeline.

Documents and queries must go through the same transformation, otherwise an
accented query term can never match its indexed form. Earlier versions used
``re.findall(r"[a-z0-9]+", text.lower())`` in some pipelines, which splits
Portuguese words at every accent (``"política"`` became ``["pol", "tica"]``).
"""

import re
import unicodedata
from collections.abc import Iterable

_TOKEN = re.compile(r"[^\W_]+")

# Portuguese and English function words that carry no evidence of relevance
# in short questions. Stored already folded, so they match ``tokenize`` output.
FUNCTION_WORDS = frozenset(
    {
        "o", "a", "os", "as", "que", "e", "de", "do", "da", "um", "uma",
        "qual", "quais", "como", "the", "what", "is", "are",
    }
)


def fold(text: str) -> str:
    """Casefold, decompose (NFKD) and drop combining marks: ``"AÇÃO"`` -> ``"acao"``."""
    normalized = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in normalized if not unicodedata.combining(c))


def tokenize(text: str) -> list[str]:
    """Fold accents without breaking words; keep Unicode letters and digits.

    There is no language-specific stop list or stemming here. Underscores and
    punctuation separate tokens; non-Latin scripts are preserved.
    """
    return _TOKEN.findall(fold(text))


def content_terms(text: str, stopwords: Iterable[str] = FUNCTION_WORDS) -> list[str]:
    """Tokens of ``text`` without function words, preserving order and repeats."""
    stop = stopwords if isinstance(stopwords, frozenset | set) else frozenset(stopwords)
    return [token for token in tokenize(text) if token not in stop]
