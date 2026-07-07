"""Answer generation tests (no network access required)."""

from enterprise_rag_system.generation import (
    DeterministicAnswerGenerator,
    build_answer_generator,
)
from enterprise_rag_system.models import Chunk, SearchResult


def _result(title: str = "Refund Policy") -> SearchResult:
    chunk = Chunk(
        chunk_id="policy_refunds:0",
        doc_id="policy_refunds",
        title=title,
        text="Refunds are issued within 30 days of a valid request.",
    )
    return SearchResult(chunk=chunk, lexical_score=1.0, vector_score=1.0, hybrid_score=1.0)


def test_deterministic_generator_grounds_on_top_chunk():
    generator = DeterministicAnswerGenerator()
    answer = generator.compose("What does the refund policy require?", [_result()])

    assert "Refund Policy" in answer
    assert "30 days" in answer


def test_deterministic_generator_handles_empty_results():
    answer = DeterministicAnswerGenerator().compose("anything", [])

    assert "could not find" in answer.lower()


def test_build_answer_generator_defaults_to_deterministic(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("RAG_LLM_MODE", raising=False)

    generator = build_answer_generator()

    assert generator.mode == "deterministic"


def test_build_answer_generator_forces_deterministic_mode(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("RAG_LLM_MODE", "deterministic")

    generator = build_answer_generator()

    assert generator.mode == "deterministic"
