"""Answer generation from retrieved chunks.

Two interchangeable strategies share one interface:

- ``DeterministicAnswerGenerator`` composes a template answer from the top
  chunk. It needs no network access, so it keeps demos and CI reproducible.
- ``LLMAnswerGenerator`` calls Claude to synthesize a grounded, citation-aware
  answer over the retrieved passages.

``build_answer_generator`` picks between them from the environment, defaulting
to the deterministic path unless a Claude API key is available.
"""

from __future__ import annotations

import os
from typing import List, Protocol

from enterprise_rag_system.models import SearchResult


SYSTEM_PROMPT = (
    "You are an enterprise knowledge assistant. Answer the user's question "
    "using ONLY the numbered context passages provided. Cite every claim with "
    "bracketed markers such as [1] or [2] that refer to the passage numbers. "
    "If the passages do not contain the answer, say so plainly instead of "
    "guessing. Keep the answer concise and grounded."
)

DEFAULT_MODEL = "claude-opus-4-8"


class AnswerGenerator(Protocol):
    """Composes a final answer from ranked search results."""

    mode: str

    def compose(self, question: str, results: List[SearchResult]) -> str:
        ...


def _format_context(results: List[SearchResult]) -> str:
    """Render ranked chunks as a numbered, citable context block."""
    lines = []
    for index, result in enumerate(results, start=1):
        chunk = result.chunk
        lines.append(f"[{index}] {chunk.title} ({chunk.doc_id})\n{chunk.text}")
    return "\n\n".join(lines)


class DeterministicAnswerGenerator:
    """Template answer used for offline demos, tests and CI."""

    mode = "deterministic"

    def compose(self, question: str, results: List[SearchResult]) -> str:
        if not results:
            return "I could not find grounded information in the indexed documents."
        leading = results[0].chunk
        return (
            f"Based on {leading.title}, the answer should be grounded in the cited policy. "
            f"Most relevant passage: {leading.text}"
        )


class LLMAnswerGenerator:
    """Grounded answer synthesized by Claude over the retrieved passages.

    The ``anthropic`` client resolves credentials from the environment
    (``ANTHROPIC_API_KEY`` or an ``ant auth login`` profile). If a request
    fails, the generator falls back to the deterministic template so a query
    never hard-fails on a transient API error.
    """

    mode = "llm"

    def __init__(self, model: str = DEFAULT_MODEL, max_tokens: int = 1024):
        import anthropic  # imported lazily so the package stays optional

        self.model = model
        self.max_tokens = max_tokens
        self._client = anthropic.Anthropic()
        self._fallback = DeterministicAnswerGenerator()

    def compose(self, question: str, results: List[SearchResult]) -> str:
        if not results:
            return "I could not find grounded information in the indexed documents."
        context = _format_context(results)
        user_prompt = (
            f"Question: {question}\n\n"
            f"Context passages:\n{context}\n\n"
            "Answer the question grounded in the passages above, with bracketed "
            "citations."
        )
        try:
            message = self._client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )
        except Exception:
            # Never let a transient API error break the query path.
            return self._fallback.compose(question, results)
        return "".join(
            block.text for block in message.content if block.type == "text"
        ).strip()


def _llm_available() -> bool:
    """True when the Anthropic SDK is importable and a key is configured."""
    if not os.getenv("ANTHROPIC_API_KEY"):
        return False
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return True


def build_answer_generator() -> AnswerGenerator:
    """Select a generator from the environment.

    ``RAG_LLM_MODE``:
        - ``deterministic`` — always use the template (default in CI).
        - ``llm`` — always use Claude (raises if the SDK/key is missing).
        - ``auto`` (default) — use Claude when available, else the template.

    ``RAG_LLM_MODEL`` overrides the Claude model id (default ``claude-opus-4-8``).
    """
    mode = os.getenv("RAG_LLM_MODE", "auto").lower()
    model = os.getenv("RAG_LLM_MODEL", DEFAULT_MODEL)

    if mode == "deterministic":
        return DeterministicAnswerGenerator()
    if mode == "llm":
        return LLMAnswerGenerator(model=model)
    # auto
    if _llm_available():
        return LLMAnswerGenerator(model=model)
    return DeterministicAnswerGenerator()
