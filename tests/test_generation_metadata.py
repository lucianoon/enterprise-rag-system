"""Generation mode must describe each response, including concurrent queries."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import Mock

from enterprise_rag_system import llm_client
from enterprise_rag_system.generation import LLMAnswerGenerator
from enterprise_rag_system.models import Chunk
from enterprise_rag_system.pipeline import RAGPipeline


def _pipeline(generator=None):
    return RAGPipeline(
        [Chunk(chunk_id="refund:0", doc_id="refund", title="Refund", text="Refunds take 30 days.")],
        answer_generator=generator or LLMAnswerGenerator(),
    )


def test_fallback_mode_does_not_leak_into_next_success(monkeypatch, caplog):
    complete = Mock(side_effect=[RuntimeError("offline test failure"), "Answer [1]."])
    monkeypatch.setattr(llm_client, "complete", complete)
    pipeline = _pipeline()

    with caplog.at_level("INFO", logger="enterprise_rag_system.pipeline"):
        failed = pipeline.query("Refund timeframe?")
        succeeded = pipeline.query("Refund timeframe?")

    assert "30 days" in failed.answer
    assert failed.metadata["generation_mode"] == "deterministic-fallback"
    assert succeeded.answer == "Answer [1]."
    assert succeeded.metadata["generation_mode"] == "llm"
    assert pipeline.answer_generator.mode == "llm"
    assert "mode=deterministic-fallback" in caplog.text
    assert "mode=llm" in caplog.text


def test_concurrent_queries_report_their_own_generation_mode(monkeypatch):
    barrier = Barrier(2, timeout=5)

    def complete(system, prompt, **kwargs):
        barrier.wait()
        if "failed request" in prompt:
            raise RuntimeError("offline test failure")
        return "Answer [1]."

    monkeypatch.setattr(llm_client, "complete", complete)
    pipeline = _pipeline()

    with ThreadPoolExecutor(max_workers=2) as executor:
        failed, succeeded = list(executor.map(pipeline.query, ["failed request", "good request"]))

    assert failed.metadata["generation_mode"] == "deterministic-fallback"
    assert "30 days" in failed.answer
    assert succeeded.metadata["generation_mode"] == "llm"
    assert succeeded.answer == "Answer [1]."


def test_empty_context_reports_deterministic_abstention(monkeypatch):
    complete = Mock(side_effect=AssertionError("No LLM call is needed without context"))
    monkeypatch.setattr(llm_client, "complete", complete)

    response = RAGPipeline([], answer_generator=LLMAnswerGenerator()).query("anything")

    assert "could not find" in response.answer
    assert response.metadata["generation_mode"] == "deterministic"
    complete.assert_not_called()


def test_compose_still_returns_plain_text(monkeypatch):
    monkeypatch.setattr(llm_client, "complete", Mock(return_value="Answer [1]."))
    pipeline = _pipeline()
    results = pipeline.retriever.search("refund")

    answer = pipeline.answer_generator.compose("refund", results)

    assert type(answer) is str
    assert answer == "Answer [1]."


def test_existing_custom_generators_remain_compatible():
    class CustomGenerator:
        mode = "custom"

        def compose(self, question, results):
            return "Custom answer."

    response = _pipeline(CustomGenerator()).query("refund")

    assert response.answer == "Custom answer."
    assert response.metadata["generation_mode"] == "custom"
