"""Answer-quality evaluation: is the generated answer grounded in retrieval?

Retrieval metrics (Recall@K, MRR) say whether the right passages reached the
generator; they say nothing about whether the *answer* stuck to them. This
module judges faithfulness — the fraction of answer claims supported by the
retrieved passages — with two interchangeable judges:

- ``HeuristicAnswerJudge`` — lexical containment per answer sentence against
  the retrieved context. Deterministic and offline, so CI can gate on it.
- ``LLMAnswerJudge`` — Claude scores faithfulness and lists unsupported
  claims. Falls back to the heuristic judge on any API error (logged).

``build_answer_judge`` picks between them from ``RAG_JUDGE_MODE``.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Protocol

from enterprise_rag_system import llm_client
from enterprise_rag_system.models import AnswerJudgement, SearchResult

logger = logging.getLogger(__name__)

JUDGE_SYSTEM_PROMPT = (
    "You are a strict evaluator of RAG answer faithfulness. Given a question, "
    "numbered context passages and an answer, decide how well the answer is "
    "supported by the passages alone. Respond with ONLY a JSON object: "
    '{"faithfulness": <float 0.0-1.0>, "unsupported_claims": [<strings>]}. '
    "faithfulness is the fraction of the answer's factual claims that the "
    "passages support. List each unsupported claim verbatim."
)

DEFAULT_JUDGE_MODEL = llm_client.DEFAULT_ANTHROPIC_MODEL

# Common words that should not count as evidence of grounding.
_STOPWORDS = frozenset(
    [
        "a", "an", "and", "are", "as", "at", "be", "based", "by", "for",
        "from", "has", "have", "if", "in", "into", "is", "it", "its", "of",
        "on", "or", "should", "that", "the", "their", "this", "to", "was",
        "were", "will", "with", "must", "not",
    ]
)


class AnswerJudge(Protocol):
    """Scores how faithfully an answer sticks to the retrieved passages."""

    mode: str

    def judge(self, question: str, answer: str, results: list[SearchResult]) -> AnswerJudgement:
        ...


def _content_tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in _STOPWORDS}


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p.strip() for p in parts if p.strip()]


class HeuristicAnswerJudge:
    """Sentence-level lexical containment against the retrieved context.

    A sentence counts as supported when at least ``threshold`` of its content
    tokens appear in the retrieved passages. Cheap and deterministic — a
    proxy, not a semantic entailment check; its job is to catch answers that
    drift away from the retrieved evidence, and to keep the answer-quality
    gate runnable in CI without secrets.
    """

    mode = "heuristic"

    def __init__(self, threshold: float = 0.5):
        self.threshold = threshold

    def judge(self, question: str, answer: str, results: list[SearchResult]) -> AnswerJudgement:
        context_tokens: set[str] = set()
        for result in results:
            context_tokens |= _content_tokens(f"{result.chunk.title} {result.chunk.text}")

        sentences = _sentences(answer)
        if not sentences or not context_tokens:
            return AnswerJudgement(
                faithfulness=0.0, unsupported_claims=sentences, judge_mode=self.mode
            )

        unsupported = []
        supported_count = 0
        for sentence in sentences:
            tokens = _content_tokens(sentence)
            if not tokens:
                supported_count += 1  # nothing factual to support
                continue
            containment = len(tokens & context_tokens) / len(tokens)
            if containment >= self.threshold:
                supported_count += 1
            else:
                unsupported.append(sentence)
        return AnswerJudgement(
            faithfulness=round(supported_count / len(sentences), 4),
            unsupported_claims=unsupported,
            judge_mode=self.mode,
        )


class LLMAnswerJudge:
    """Claude as a faithfulness judge, with heuristic fallback on errors."""

    mode = "llm"

    def __init__(self, model: str | None = None, max_tokens: int = 1024):
        self.model = model
        self.max_tokens = max_tokens
        self._fallback = HeuristicAnswerJudge()

    def judge(self, question: str, answer: str, results: list[SearchResult]) -> AnswerJudgement:
        context = "\n\n".join(
            f"[{index}] {r.chunk.title} ({r.chunk.doc_id})\n{r.chunk.text}"
            for index, r in enumerate(results, start=1)
        )
        user_prompt = (
            f"Question: {question}\n\n"
            f"Context passages:\n{context}\n\n"
            f"Answer to evaluate:\n{answer}"
        )
        try:
            raw = llm_client.complete(
                JUDGE_SYSTEM_PROMPT, user_prompt, model=self.model, max_tokens=self.max_tokens
            )
            return self._parse(raw)
        except Exception:
            logger.exception(
                "LLM judge failed (model=%s); falling back to heuristic judge.",
                llm_client.describe(self.model),
            )
            fallback = self._fallback.judge(question, answer, results)
            return fallback.model_copy(update={"judge_mode": "heuristic-fallback"})

    def _parse(self, raw: str) -> AnswerJudgement:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            raise ValueError(f"Judge returned no JSON object: {raw[:200]!r}")
        payload = json.loads(match.group(0))
        return AnswerJudgement(
            faithfulness=round(max(0.0, min(1.0, float(payload["faithfulness"]))), 4),
            unsupported_claims=[str(c) for c in payload.get("unsupported_claims", [])],
            judge_mode=self.mode,
        )


def _llm_available() -> bool:
    """True when a backend resolves and its SDK is importable."""
    return llm_client.is_available()


def build_answer_judge() -> AnswerJudge:
    """Select an answer judge from the environment.

    ``RAG_JUDGE_MODE``:
        - ``heuristic`` (default) — deterministic lexical containment, CI-safe.
        - ``llm`` — always call the model (``RAG_JUDGE_MODEL`` overrides the id).
        - ``auto`` — call the model when available, else heuristic.
    """
    mode = os.getenv("RAG_JUDGE_MODE", "heuristic").lower()
    model = os.getenv("RAG_JUDGE_MODEL") or None

    if mode == "heuristic":
        return HeuristicAnswerJudge()
    if mode == "llm":
        return LLMAnswerJudge(model=model)
    if mode == "auto":
        if _llm_available():
            return LLMAnswerJudge(model=model)
        return HeuristicAnswerJudge()
    raise ValueError(
        f"Unknown RAG_JUDGE_MODE={mode!r}. Expected one of: heuristic, llm, auto."
    )
